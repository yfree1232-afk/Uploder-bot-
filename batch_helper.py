import os
import re
import asyncio
import aiohttp
import shutil
import time
import datetime
import requests as req_lib
from typing import List, Tuple

# ─────────────────────────────────────────────
# Appx/Classx direct URL decrypter & resolver
# ─────────────────────────────────────────────
def decrypt_appx_link(enc: str) -> str:
    import base64
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    try:
        enc_data = base64.b64decode(enc.split(':')[0])
        key = '638udh3829162018'.encode('utf-8')
        iv = 'fedcba9876543210'.encode('utf-8')
        if not enc_data:
            return ""
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plaintext = unpad(cipher.decrypt(enc_data), AES.block_size)
        return plaintext.decode('utf-8')
    except Exception as e:
        print(f"Decryption error: {e}")
        return ""

def resolve_appx_vercel_url(url: str) -> str:
    if "appxsignurl.vercel.app" not in url:
        return url
        
    import urllib.parse
    import requests
    import re
    try:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        userid = query.get("userid", ["446172"])[0]
        
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 4:
            tenant = path_parts[1]
            course_id = path_parts[2]
            filename = path_parts[3]
            fn_parts = filename.split(".")
            if len(fn_parts) >= 2:
                content_id = fn_parts[-2]
            else:
                return url
        else:
            return url
            
        api_base = f"https://{tenant}api.classx.co.in"
        api_url = f"{api_base}/get/fetchVideoDetailsById?course_id={course_id}&video_id={content_id}&ytflag=0&folder_wise_course=0"
        
        token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpZCI6IjQ0NjE3MiIsInRpbWVzdGFtcCI6MTc4MDczMzE4OSwiaXZfdmVyIjoyMywic2Vzc2lvbiI6ImV5SjBlWEFpT2lKS1YxUWlMQ0poYkdjaU9pSklVekkxTmlKOS5leUpwWkNJNklqUTBOakUzTWlJc0ltVnRZV2xzSWpvaWMzVnlZV3ByYUdGeWRXRnlZVUJuYldGcGJDNWpiMjBpTENKdVlXMWxJam9pVTNWeVlXb2dTM1Z0WVhJaUxDSjBaVzVoYm5SVWVYQmxJam9pZFhObGNpSXNJblJsYm1GdWRFNWhiV1VpT2lKcllYVjBhV3g1WVdGc2NHcGxYMlJpSWl3aWRHVnVZVzUwU1dRaU9pSWlMQ0prYVhOd2IzTmhZbXhsSWpwbVlXeHpaWDAuMHdiajdOellzZVNsUTJqQUpfTFFmMDlwMG1lM2NYVmlLWHg2YWZkWmRTdyJ9.Q4BxMCC6y9f14LXvGng8omlkeA5Hc1Jzw7C7exjSJGo"
        
        headers = {
            'Client-Service': 'Appx',
            'Auth-Key': 'appxapi',
            'User-ID': userid,
            'Authorization': token,
            'source': 'website',
            'Host': f"{tenant}api.classx.co.in",
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        }
        
        resp = requests.get(api_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            resp_json = resp.json()
            data = resp_json.get("data", {})
            download_link_enc = data.get("download_link") or data.get("pdf_link")
            if download_link_enc:
                decrypted = decrypt_appx_link(download_link_enc)
                if decrypted:
                    return decrypted
    except Exception as e:
        print(f"Error resolving appx URL: {e}")
        
    return url

# Parse batch .txt file
# Supported formats (one per line):
#   Description | URL
#   Description \t URL
#   raw URL only (description auto-generated)
# ─────────────────────────────────────────────
def parse_batch_file(file_path: str) -> List[Tuple[str, str]]:
    entries = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if " : https://" in line:
                desc, url = map(str.strip, line.split(" : https://", 1))
                url = "https://" + url
            elif " : http://" in line:
                desc, url = map(str.strip, line.split(" : http://", 1))
                url = "http://" + url
            elif ":https://" in line:
                desc, url = map(str.strip, line.split(":https://", 1))
                url = "https://" + url
            elif ":http://" in line:
                desc, url = map(str.strip, line.split(":http://", 1))
                url = "http://" + url
            elif "|" in line:
                desc, url = map(str.strip, line.split("|", 1))
            elif "\t" in line:
                desc, url = map(str.strip, line.split("\t", 1))
            else:
                url = line.strip()
                desc = url.split("/")[-1].split("?")[0] or "file"
            entries.append((desc, url.strip()))
    return entries


# ─────────────────────────────────────────────
# Try yt-dlp first (without aria2c for HLS)
# ─────────────────────────────────────────────
async def download_hls_ytdlp(url: str, out_path: str) -> bool:
    """Download m3u8/HLS using yt-dlp native downloader (no aria2c, no ffmpeg merge)."""
    cmd = [
        "yt-dlp",
        "--no-check-certificate",
        "--hls-use-mpegts",
        "--no-part",
        "-R", "5",
        "--fragment-retries", "10",
        "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "--add-header", "Origin:https://appx.co.in",
        "--add-header", "Referer:https://appx.co.in/",
        "-f", "b[height<=720]/best",
        "-o", out_path,
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
    return os.path.isfile(out_path) and os.path.getsize(out_path) > 1024


# ─────────────────────────────────────────────
# Manual m3u8 segment download (fallback)
# Works even if yt-dlp fails - downloads raw TS segments
# ─────────────────────────────────────────────
def download_hls_manual(url: str, out_path: str) -> bool:
    """Fetch m3u8 playlist and download+concatenate all TS segments manually."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Origin": "https://appx.co.in",
        "Referer": "https://appx.co.in/",
    }
    try:
        resp = req_lib.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"[HLS] m3u8 fetch failed: HTTP {resp.status_code}")
            return False

        playlist_text = resp.text
        lines = playlist_text.strip().splitlines()

        # If it's a master playlist, pick first variant stream
        if "#EXT-X-STREAM-INF" in playlist_text:
            variant_uri = None
            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF"):
                    variant_uri = lines[i + 1].strip()
                    break
            if variant_uri:
                if not variant_uri.startswith("http"):
                    base = url.rsplit("/", 1)[0] + "/"
                    variant_uri = base + variant_uri
                resp2 = req_lib.get(variant_uri, headers=headers, timeout=30)
                if resp2.status_code != 200:
                    return False
                playlist_text = resp2.text
                lines = playlist_text.strip().splitlines()
                base_url = variant_uri.rsplit("/", 1)[0] + "/"
            else:
                base_url = url.rsplit("/", 1)[0] + "/"
        else:
            base_url = url.rsplit("/", 1)[0] + "/"

        # Collect segment URIs
        segments = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                seg_url = line if line.startswith("http") else base_url + line
                segments.append(seg_url)

        if not segments:
            print("[HLS] No segments found in playlist")
            return False

        print(f"[HLS] Downloading {len(segments)} segments...")
        with open(out_path, "wb") as out_f:
            for i, seg_url in enumerate(segments):
                for attempt in range(3):
                    try:
                        seg_resp = req_lib.get(seg_url, headers=headers, timeout=60)
                        if seg_resp.status_code == 200:
                            out_f.write(seg_resp.content)
                            break
                    except Exception as e:
                        if attempt == 2:
                            print(f"[HLS] Segment {i} failed: {e}")
                        time.sleep(1)

        return os.path.isfile(out_path) and os.path.getsize(out_path) > 1024

    except Exception as e:
        print(f"[HLS] Manual download exception: {e}")
        return False


# ─────────────────────────────────────────────
# Combined HLS downloader: yt-dlp → manual fallback
# ─────────────────────────────────────────────
async def download_hls(url: str, out_path: str) -> bool:
    print(f"[HLS] Trying yt-dlp for: {url[:80]}")
    try:
        ok = await download_hls_ytdlp(url, out_path)
        if ok:
            return True
    except Exception as e:
        print(f"[HLS] yt-dlp failed: {e}")

    print("[HLS] Falling back to manual segment download...")
    return download_hls_manual(url, out_path)


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
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
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
    ext = ".pdf" if is_pdf else ".mp4"
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
    base_dir = os.path.dirname(txt_path) or "."
    temp_dir = os.path.join(base_dir, f"temp_{chat_id}")
    os.makedirs(temp_dir, exist_ok=True)

    entries = parse_batch_file(txt_path)
    total = len(entries)
    await bot.send_message(chat_id, f"📋 <b>Batch started</b> – {total} items found. Processing…")

    success_cnt = 0
    fail_cnt = 0
    index_lines = []

    for idx, (desc, url) in enumerate(entries, start=1):
        url = resolve_appx_vercel_url(url)
        safe_desc = re.sub(r'[\\/*?:"<>|]', "", desc)[:80].strip()
        safe_desc = safe_desc.replace(" ", "_") or f"file_{idx}"

        progress_msg = await bot.send_message(
            chat_id,
            f"⏬ <b>[{idx}/{total}]</b> Downloading…\n<code>{desc[:80]}</code>"
        )

        try:
            # ── HLS / video ─────────────────────────
            if "m3u8" in url.lower():
                out_file = os.path.join(temp_dir, f"{safe_desc}.ts")
                ok = await download_hls(url, out_file)
                if ok:
                    cap = generate_caption(idx, desc, url, credit_name, desc, batch_name)
                    await bot.send_video(
                        chat_id=chat_id,
                        video=out_file,
                        caption=cap,
                        supports_streaming=True,
                    )
                    success_cnt += 1
                    index_lines.append(f"{str(idx).zfill(2)}. {desc}")
                else:
                    fail_cnt += 1
                    await bot.send_message(
                        chat_id,
                        f"⚠️ <b>Downloading Failed</b>\n"
                        f"Name =&gt;&gt; <code>{desc}</code>\n"
                        f"Url =&gt;&gt; <code>{url}</code>\n\n"
                        f"Failed Reason: Both yt-dlp and manual segment download failed.",
                        disable_web_page_preview=True,
                    )

            # ── PDF ─────────────────────────────────
            elif ".pdf" in url.lower():
                out_file = os.path.join(temp_dir, f"{safe_desc}.pdf")
                ok = await download_file(url, out_file)
                if ok:
                    cap = generate_caption(idx, desc, url, credit_name, desc, batch_name)
                    await bot.send_document(chat_id=chat_id, document=out_file, caption=cap)
                    success_cnt += 1
                    index_lines.append(f"{str(idx).zfill(2)}. {desc}")
                else:
                    fail_cnt += 1
                    await bot.send_message(
                        chat_id,
                        f"⚠️ <b>Downloading Failed</b>\n"
                        f"Name =&gt;&gt; <code>{desc}</code>\n"
                        f"Failed Reason: PDF returned non-200.",
                        disable_web_page_preview=True,
                    )

            # ── Image ────────────────────────────────
            elif any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png"]):
                ext_i = url.lower().rsplit(".", 1)[-1].split("?")[0]
                out_file = os.path.join(temp_dir, f"{safe_desc}.{ext_i}")
                ok = await download_file(url, out_file)
                if ok:
                    cap = generate_caption(idx, desc, url, credit_name, desc, batch_name)
                    await bot.send_photo(chat_id=chat_id, photo=out_file, caption=cap)
                    success_cnt += 1
                    index_lines.append(f"{str(idx).zfill(2)}. {desc}")
                else:
                    fail_cnt += 1
                    await bot.send_message(chat_id, f"⚠️ Failed image: <code>{desc}</code>")

            # ── Other / fallback ─────────────────────
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
                    index_lines.append(f"{str(idx).zfill(2)}. {desc}")
                else:
                    fail_cnt += 1
                    await bot.send_message(
                        chat_id,
                        f"⚠️ <b>Downloading Failed</b>\n<code>{desc}</code>",
                        disable_web_page_preview=True,
                    )

        except Exception as e:
            fail_cnt += 1
            await bot.send_message(
                chat_id,
                f"⚠️ <b>Error</b>\nName =&gt;&gt; <code>{desc}</code>\nReason: <code>{str(e)[:200]}</code>",
            )

        finally:
            try:
                await progress_msg.delete()
            except Exception:
                pass
            # cleanup temp files for this item
            for p in os.listdir(temp_dir):
                try:
                    os.remove(os.path.join(temp_dir, p))
                except Exception:
                    pass

    # ── Summary ─────────────────────────────────
    await bot.send_message(
        chat_id,
        f"✅ <b>Batch Complete!</b>\n\n"
        f"• Total  : {total}\n"
        f"• Success: {success_cnt}\n"
        f"• Failed : {fail_cnt}",
    )

    # ── Index (WhatsApp style) ───────────────────
    if index_lines:
        ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        index_header = f"[{ts}] 𝓐𝓭𝓲𝓽𝔂𝓪: 📑 Topics covered in this Batch:\n\n"
        index_body = "\n".join(index_lines)
        full_index = index_header + index_body
        for chunk_start in range(0, len(full_index), 4000):
            await bot.send_message(chat_id, full_index[chunk_start:chunk_start + 4000])

    # ── Cleanup ──────────────────────────────────
    shutil.rmtree(temp_dir, ignore_errors=True)
    try:
        os.remove(txt_path)
    except Exception:
        pass
