import os
import re
import asyncio
import aiohttp
import shutil
import time
import datetime
from typing import List, Tuple

# ─────────────────────────────────────────────
# Parse batch .txt file
# Supported formats (one per line):
#   Description | URL
#   Description \t URL
#   [Topic] Title : URL          (colon-separated last part)
#   raw URL only (description auto-generated)
# ─────────────────────────────────────────────
def parse_batch_file(file_path: str) -> List[Tuple[str, str]]:
    entries = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                desc, url = map(str.strip, line.split("|", 1))
            elif "\t" in line:
                desc, url = map(str.strip, line.split("\t", 1))
            else:
                # treat whole line as URL, generate fallback desc
                url = line.strip()
                desc = url.split("/")[-1].split("?")[0] or "file"
            entries.append((desc, url.strip()))
    return entries


# ─────────────────────────────────────────────
# Download HLS / video URL using yt-dlp
# (no ffmpeg required – uses native downloader)
# ─────────────────────────────────────────────
async def download_hls_ytdlp(url: str, out_path: str) -> bool:
    """Download m3u8/HLS stream using yt-dlp without requiring ffmpeg."""
    cmd = [
        "yt-dlp",
        "--no-check-certificate",
        "--hls-use-mpegts",          # native TS muxer – no ffmpeg needed
        "--no-part",
        "-R", "5",
        "--fragment-retries", "5",
        "-o", out_path,
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return os.path.isfile(out_path)


# ─────────────────────────────────────────────
# Generic download (PDF / image)
# ─────────────────────────────────────────────
async def download_file(url: str, out_path: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    return False
                with open(out_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)
        return os.path.isfile(out_path)
    except Exception:
        return False


# ─────────────────────────────────────────────
# Caption generator
# ─────────────────────────────────────────────
def generate_caption(idx: int, desc: str, url: str, credit_name: str,
                     topic_name: str = "", batch_name: str = "") -> str:
    vid_id_match = re.search(r"[?&]id=(\d+)", url)
    vid_id = vid_id_match.group(1) if vid_id_match else str(idx).zfill(3)
    is_pdf = ".pdf" in url.lower()
    icon = "📑" if is_pdf else "🎥"
    ext  = ".pdf" if is_pdf else ".mp4"
    title = f"{desc}{ext}"
    topic = topic_name or desc
    batch = batch_name or "Batch"
    return (
        f"[{icon}]Vid Id : {vid_id}\n"
        f"Video Title : {title}\n"
        f"Topic Name : {topic}\n"
        f"Batch Name : {batch}\n\n"
        f"Downloadd By ➤ {credit_name}"
    )


# ─────────────────────────────────────────────
# Main batch processor
# ─────────────────────────────────────────────
async def process_batch(
    txt_path: str,
    bot,
    chat_id: int,
    user_id: int,
    credit_name: str = "{CREDIT}",
    batch_name: str = "Batch",
):
    base_dir = os.path.dirname(txt_path)
    temp_dir = os.path.join(base_dir, f"temp_{chat_id}")
    os.makedirs(temp_dir, exist_ok=True)

    entries = parse_batch_file(txt_path)
    total = len(entries)
    await bot.send_message(chat_id, f"📋 **Batch started** – {total} items found. Processing...")

    success_cnt = 0
    fail_cnt = 0
    index_lines = []

    for idx, (desc, url) in enumerate(entries, start=1):
        # Sanitise for filename (no special chars)
        safe_desc = re.sub(r'[\\/*?:"<>|]', "", desc)[:80].strip()
        safe_desc = safe_desc.replace(" ", "_") or f"file_{idx}"

        progress_msg = await bot.send_message(
            chat_id, f"⏬ [{idx}/{total}] Downloading…\n`{desc[:80]}`"
        )

        try:
            # ── HLS / video ─────────────────────────────
            if "m3u8" in url.lower() or url.lower().endswith(".m3u8"):
                out_file = os.path.join(temp_dir, f"{safe_desc}.ts")
                ok = await download_hls_ytdlp(url, out_file)
                if ok:
                    cap = generate_caption(idx, desc, url, credit_name, desc, batch_name)
                    await bot.send_video(
                        chat_id=chat_id,
                        video=out_file,
                        caption=cap,
                        supports_streaming=True,
                    )
                    success_cnt += 1
                else:
                    fail_cnt += 1
                    await bot.send_message(
                        chat_id,
                        f"⚠️ **Downloading Failed**\n"
                        f"Name =>> `{desc}`\n"
                        f"Url =>> `{url}`\n\n"
                        f"Failed Reason: yt-dlp could not download the HLS stream.",
                        disable_web_page_preview=True,
                    )

            # ── PDF ─────────────────────────────────────
            elif ".pdf" in url.lower():
                out_file = os.path.join(temp_dir, f"{safe_desc}.pdf")
                ok = await download_file(url, out_file)
                if ok:
                    cap = generate_caption(idx, desc, url, credit_name, desc, batch_name)
                    await bot.send_document(chat_id=chat_id, document=out_file, caption=cap)
                    success_cnt += 1
                else:
                    fail_cnt += 1
                    await bot.send_message(
                        chat_id,
                        f"⚠️ **Downloading Failed**\nName =>> `{desc}`\nUrl =>> `{url}`\n\nFailed Reason: PDF download returned non-200.",
                        disable_web_page_preview=True,
                    )

            # ── Image ────────────────────────────────────
            elif any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png"]):
                ext_i = url.lower().rsplit(".", 1)[-1].split("?")[0]
                out_file = os.path.join(temp_dir, f"{safe_desc}.{ext_i}")
                ok = await download_file(url, out_file)
                if ok:
                    cap = generate_caption(idx, desc, url, credit_name, desc, batch_name)
                    await bot.send_photo(chat_id=chat_id, photo=out_file, caption=cap)
                    success_cnt += 1
                else:
                    fail_cnt += 1
                    await bot.send_message(chat_id, f"⚠️ Failed image: `{desc}`")

            # ── Fallback: yt-dlp for anything else ───────
            else:
                out_file = os.path.join(temp_dir, f"{safe_desc}.mp4")
                ok = await download_hls_ytdlp(url, out_file)
                if ok:
                    cap = generate_caption(idx, desc, url, credit_name, desc, batch_name)
                    await bot.send_video(
                        chat_id=chat_id, video=out_file,
                        caption=cap, supports_streaming=True
                    )
                    success_cnt += 1
                else:
                    fail_cnt += 1
                    await bot.send_message(
                        chat_id,
                        f"⚠️ **Downloading Failed**\nName =>> `{desc}`\nUrl =>> `{url}`",
                        disable_web_page_preview=True,
                    )

            # Add to index
            index_lines.append(f"{str(idx).zfill(2)}. [{desc}]({url})")

        except Exception as e:
            fail_cnt += 1
            await bot.send_message(
                chat_id,
                f"⚠️ **Error**\nName =>> `{desc}`\nReason: `{str(e)[:200]}`",
            )

        finally:
            # Delete progress message & clean temp files for this item
            try:
                await progress_msg.delete()
            except Exception:
                pass
            for p in os.listdir(temp_dir):
                try:
                    os.remove(os.path.join(temp_dir, p))
                except Exception:
                    pass

    # ── Summary ─────────────────────────────────
    await bot.send_message(
        chat_id,
        f"✅ **Batch Complete!**\n\n"
        f"• Total  : {total}\n"
        f"• Success: {success_cnt}\n"
        f"• Failed : {fail_cnt}",
    )

    # ── Index (WhatsApp style) ───────────────────
    if index_lines:
        ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        index_header = f"[{ts}] 𝓐𝓭𝓲𝓽𝔂𝓪: 📑 Topics covered in this Batch:\n\n"
        index_body = "\n".join(index_lines)
        # split if too long for one Telegram message
        full_index = index_header + index_body
        for chunk_start in range(0, len(full_index), 4000):
            await bot.send_message(chat_id, full_index[chunk_start:chunk_start + 4000])

    # ── Cleanup ──────────────────────────────────
    shutil.rmtree(temp_dir, ignore_errors=True)
    try:
        os.remove(txt_path)
    except Exception:
        pass
