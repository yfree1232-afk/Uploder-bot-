import os
import asyncio
import aiohttp
import subprocess
import shutil
from typing import List, Tuple

# Helper to parse the .txt batch file
def parse_batch_file(file_path: str) -> List[Tuple[str, str]]:
    entries = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Expect "Description | URL" (pipe separated). Fall back to tab.
            if "|" in line:
                desc, url = map(str.strip, line.split("|", 1))
            elif "\t" in line:
                desc, url = map(str.strip, line.split("\t", 1))
            else:
                # If format is unexpected, skip.
                continue
            entries.append((desc, url))
    return entries

# Download HLS video and extract a thumbnail (first frame)
async def download_hls(url: str, out_path: str, thumb_path: str) -> bool:
    # ffmpeg command to copy video
    cmd_video = ["ffmpeg", "-y", "-i", url, "-c", "copy", out_path]
    # ffmpeg command to grab a single frame as thumbnail
    cmd_thumb = ["ffmpeg", "-y", "-i", url, "-vframes", "1", "-q:v", "2", thumb_path]
    proc_vid = await asyncio.create_subprocess_exec(*cmd_video, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await proc_vid.communicate()
    proc_thumb = await asyncio.create_subprocess_exec(*cmd_thumb, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await proc_thumb.communicate()
    return os.path.isfile(out_path) and os.path.isfile(thumb_path)

# Generic download for PDFs or images using aiohttp streaming
async def download_file(url: str, out_path: str) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return False
            with open(out_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    f.write(chunk)
    return os.path.isfile(out_path)

# Main processing function called from the bot handler
async def process_batch(txt_path: str, bot, chat_id: int, user_id: int, credit_name: str = "{CREDIT}"):
    base_dir = os.path.dirname(txt_path)
    temp_dir = os.path.join(base_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    entries = parse_batch_file(txt_path)
    success_cnt = 0
    fail_cnt = 0
    index_lines = []
    for desc, url in entries:
        # Sanitize description for filename
        safe_desc = "_".join([s for s in desc.replace("|", "").split() if s])
        ext = os.path.splitext(url)[1].lower()
        if ext == ".m3u8" or "m3u8" in url:
            out_file = os.path.join(temp_dir, f"{safe_desc}.mp4")
            thumb_file = os.path.join(temp_dir, f"{safe_desc}_thumb.jpg")
            ok = await download_hls(url, out_file, thumb_file)
            if ok:
                caption = generate_caption(desc, url, credit_name)
                await bot.send_video(chat_id=chat_id, video=out_file, thumb=thumb_file, caption=caption)
                success_cnt += 1
            else:
                fail_cnt += 1
                await bot.send_message(chat_id, f"⚠️ Failed to download video for *{desc}*.")
        elif ext == ".pdf" or url.lower().endswith('.pdf'):
            out_file = os.path.join(temp_dir, f"{safe_desc}.pdf")
            ok = await download_file(url, out_file)
            if ok:
                caption = generate_caption(desc, url, credit_name)
                await bot.send_document(chat_id=chat_id, document=out_file, caption=caption)
                success_cnt += 1
            else:
                fail_cnt += 1
                await bot.send_message(chat_id, f"⚠️ Failed to download PDF for *{desc}*.")
        elif any(ext_img in url.lower() for ext_img in [".jpg", ".jpeg", ".png"]):
            out_file = os.path.join(temp_dir, f"{safe_desc}{ext}")
            ok = await download_file(url, out_file)
            if ok:
                caption = generate_caption(desc, url, credit_name)
                await bot.send_photo(chat_id=chat_id, photo=out_file, caption=caption)
                success_cnt += 1
            else:
                fail_cnt += 1
                await bot.send_message(chat_id, f"⚠️ Failed to download image for *{desc}*.")
        else:
            # Fallback: use yt-dlp to download whatever it can handle
            out_file = os.path.join(temp_dir, f"{safe_desc}.%(ext)s")
            dl_cmd = ["yt-dlp", "-o", out_file, url]
            proc = await asyncio.create_subprocess_exec(*dl_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
            # yt-dlp may produce multiple files; find the first one
            downloaded = None
            for f in os.listdir(temp_dir):
                if f.startswith(safe_desc) and not f.endswith('_thumb.jpg'):
                    downloaded = os.path.join(temp_dir, f)
                    break
            if downloaded:
                caption = generate_caption(desc, url, credit_name)
                await bot.send_document(chat_id=chat_id, document=downloaded, caption=caption)
                success_cnt += 1
            else:
                fail_cnt += 1
                await bot.send_message(chat_id, f"⚠️ yt-dlp could not fetch *{desc}*.")
        # Prepare index entry (clickable link to original URL)
        index_lines.append(f"[{desc}]({url})")
        # Cleanup per-item files (keep thumbnails for videos only for sending, then delete)
        for p in list(os.listdir(temp_dir)):
            p_path = os.path.join(temp_dir, p)
            try:
                os.remove(p_path)
            except Exception:
                pass
    # Send summary
    await bot.send_message(chat_id, f"✅ Batch completed: {success_cnt} succeeded, {fail_cnt} failed.")
    # Build index message with timestamp header
    index_msg = "[07/06/2026 17:12] 𝓐𝓭𝓲𝓽𝔂𝓪: 📑 Topics covered in this Batch:\n\n" + "\n".join(index_lines)
    await bot.send_message(chat_id, index_msg, parse_mode="MarkdownV2")
    # Cleanup temp directory and original txt file
    shutil.rmtree(temp_dir, ignore_errors=True)
    try:
        os.remove(txt_path)
    except Exception:
        pass

# Caption generator matching user supplied format
def generate_caption(desc: str, url: str, credit_name: str) -> str:
    # Attempt to extract a numeric video ID from the URL if present
    import re
    vid_id_match = re.search(r"[?&]id=(\d+)", url)
    vid_id = vid_id_match.group(1) if vid_id_match else "069"
    # For title we reuse the description (cleaned)
    title = f"{desc}.mp4"
    topic = desc
    batch_name = "Psychology"
    return f"[🎥]Vid Id : {vid_id}\nVideo Title : {title}\nTopic Name : {topic}\nBatch Name : {batch_name}\n\nDownloadd By ➤ {credit_name}"
