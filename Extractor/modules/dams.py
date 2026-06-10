import os
import re
import json
import logging
import asyncio
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
from Extractor import app
from config import BOT_TEXT

def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', str(name))
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_. ')
    return name if name else "Unknown_Course"

async def fetch_json_post(session, url, data=None, headers=None):
    try:
        async with session.post(url, data=data, headers=headers, timeout=30) as resp:
            return await resp.json()
    except Exception as e:
        logging.error(f"Error fetching JSON from {url}: {e}")
    return None

async def fetch_json_get(session, url, headers=None):
    try:
        async with session.get(url, headers=headers, timeout=30) as resp:
            return await resp.json()
    except Exception as e:
        logging.error(f"Error fetching JSON from {url}: {e}")
    return None

async def process_dams(bot: Client, m: Message, user_id: int):
    loop = asyncio.get_event_loop()
    CONNECTOR = aiohttp.TCPConnector(limit=100, loop=loop)

    async with aiohttp.ClientSession(connector=CONNECTOR, loop=loop) as session:
        # Step 1: Prompt for Mobile Number
        try:
            mobile_prompt = await m.reply_text("📱 **Please enter your DAMS Delhi Mobile Number:**")
            input_msg = await bot.listen(chat_id=m.chat.id, filters=filters.user(user_id), timeout=120)
            mobile = input_msg.text.strip()
            await input_msg.delete(True)
            await mobile_prompt.delete()
        except asyncio.TimeoutError:
            await m.reply_text("❌ **Timeout!**\nYou took too long to respond.")
            return

        editable = await m.reply_text(f"🔄 Requesting OTP for `{mobile}`...")

        # Request OTP
        api_base = "https://api.damsdelhi.com/v2_data_model"
        headers = {"User-Agent": "Mozilla/5.0"}
        login_url = f"{api_base}/login_authentication_v6"
        
        req_data = {'mobile': mobile}
        login_resp = await fetch_json_post(session, login_url, data=req_data, headers=headers)
        
        if not login_resp or not login_resp.get("status"):
            error_msg = login_resp.get("message", "Unknown error") if login_resp else "Connection failed"
            await editable.edit(f"❌ **OTP Request Failed**\n\nReason: `{error_msg}`")
            return
            
        await editable.edit("✅ **OTP Sent Successfully!**")

        # Step 2: Prompt for OTP
        try:
            otp_prompt = await m.reply_text("🔑 **Please enter the OTP received:**")
            input_msg2 = await bot.listen(chat_id=m.chat.id, filters=filters.user(user_id), timeout=120)
            otp = input_msg2.text.strip()
            await input_msg2.delete(True)
            await otp_prompt.delete()
        except asyncio.TimeoutError:
            await editable.edit("❌ **Timeout!**\nYou took too long to respond.")
            return

        await editable.edit("🔄 **Verifying OTP and Logging in...**")
        
        # Verify OTP
        verify_data = {'mobile': mobile, 'otp': otp}
        verify_resp = await fetch_json_post(session, login_url, data=verify_data, headers=headers)
        
        if not verify_resp or not verify_resp.get("status"):
            error_msg = verify_resp.get("message", "Unknown error") if verify_resp else "Verification failed"
            if "Already Login" in error_msg:
                await editable.edit(f"❌ **Login Failed**\n\nYour account is already logged in on another device.\nPlease logout from other devices first.")
            else:
                await editable.edit(f"❌ **OTP Verification Failed**\n\nReason: `{error_msg}`")
            return

        data_payload = verify_resp.get("data", {})
        jwt_token = verify_resp.get("jwt") or verify_resp.get("auth_code") or data_payload.get("dams_tokken")
        
        if not jwt_token:
            # Fallback: check if it's passed in headers or somewhere else
            await editable.edit("❌ **Auth Error**\n\nLogged in successfully but could not extract JWT token.")
            return

        # Fetch Courses
        await editable.edit("🔄 **Fetching your courses...**")
        auth_headers = {
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {jwt_token}" if not jwt_token.startswith("Bearer ") else jwt_token,
            "Content-Type": "application/json"
        }
        
        courses_url = f"{api_base}/get_user_courses_wishlist"
        courses_resp = await fetch_json_post(session, courses_url, data={"userid": data_payload.get("id")}, headers=auth_headers)
        
        if not courses_resp or not courses_resp.get("data"):
            await editable.edit("❌ **No Courses Found!**\n\nMake sure you have purchased courses on this account.")
            return
            
        batches = courses_resp.get("data", [])
        if not batches:
            await editable.edit("❌ **No Courses Found!**")
            return

        text = ''
        for cnt, batch in enumerate(batches):
            name = batch.get("course_name", "Unknown")
            price = batch.get("price", "Free")
            text += f"{cnt + 1}. {name} - Rs.{price}\n"
            
        course_details_file = f"{user_id}_dams_courses.txt"
        with open(course_details_file, 'w', encoding='utf-8') as f:
            f.write(text)
            
        caption = (
            f"🎓 <b>DAMS COURSES</b> 🎓\n\n"
            f"📚 <b>TOTAL COURSES:</b> {len(batches)}\n\n"
            f"<code>╾───• @PRO_TXT_EXTRATOR_BOT •───╼</code>\n\n"
            "Send the index number to download course"
        )
        
        await editable.delete()
        msg = await m.reply_document(
            document=course_details_file,
            caption=caption,
            file_name="dams_courses.txt"
        )
        
        try:
            os.remove(course_details_file)
        except:
            pass
            
        try:
            input_msg3 = await bot.listen(chat_id=m.chat.id, filters=filters.user(user_id), timeout=120)
            user_choice = input_msg3.text.strip()
            await input_msg3.delete(True)
        except:
            await msg.edit("❌ <b>Timeout!</b>\n\nYou took too long to respond.")
            return
            
        if not user_choice.isdigit() or not (1 <= int(user_choice) <= len(batches)):
            await msg.edit("❌ <b>Invalid Input!</b>\n\nPlease send a valid index number.")
            return
            
        selected_idx = int(user_choice) - 1
        selected_batch = batches[selected_idx]
        course_id = selected_batch.get("id")
        batch_title = selected_batch.get("course_name", "Unknown Batch")
        clean_batch_name = sanitize_filename(batch_title)
        
        status_msg = await m.reply_text(
            "🔄 <b>Processing Course</b>\n"
            f"└─ Current: <code>{batch_title}</code>\n"
            f"Extracting content directly from DAMS..."
        )

        # Extract course detail
        detail_url = f"{api_base}/get_course_detail"
        detail_data = {'course_id': course_id}
        course_resp = await fetch_json_post(session, detail_url, data=detail_data, headers=auth_headers)
        
        if not course_resp or not course_resp.get("data"):
            await status_msg.edit(f"❌ **Data Error**\n\nCould not fetch course details for {batch_title}.")
            return
            
        all_outputs = []
        course_data = course_resp.get("data", {})
        
        # In DAMS, topics are usually in 'topics' or 'subjects' or 'video_list'
        # Since we don't have the exact JSON schema of get_course_detail without a valid account,
        # we will do a recursive generic search for 'video_url', 'file_url', etc.
        
        def extract_links(node, current_topic=""):
            if isinstance(node, dict):
                title = node.get("title") or node.get("subject_name") or node.get("topic_name") or node.get("file_name") or node.get("video_title") or node.get("name")
                vid_url = node.get("video_url") or node.get("file_url") or node.get("url") or node.get("link")
                
                if vid_url and isinstance(vid_url, str) and vid_url.startswith("http"):
                    safe_title = sanitize_filename(title) if title else "Untitled"
                    all_outputs.append(f"{safe_title}:{vid_url}\n")
                    
                for k, v in node.items():
                    extract_links(v, title if title else current_topic)
                    
            elif isinstance(node, list):
                for item in node:
                    extract_links(item, current_topic)

        extract_links(course_data)
        
        if len(all_outputs) == 0:
            await status_msg.edit("❌ No content found for this course.")
            return
            
        clean_file_name = f"{user_id}_{clean_batch_name}"
        content = ''.join(all_outputs)
        
        with open(f"{clean_file_name}.txt", 'w', encoding='utf-8') as f:
            f.write(content)
            
        video_count = sum(1 for line in all_outputs if ".pdf" not in line.lower())
        pdf_count = sum(1 for line in all_outputs if ".pdf" in line.lower())
        total_links = video_count + pdf_count
        
        caption = (
            f"🎓 <b>DAMS EXTRACTED</b> 🎓\n\n"
            f"📚 <b>BATCH:</b> {batch_title}\n\n"
            f"📊 <b>CONTENT STATS</b>\n"
            f"├─ 📁 Total Links: {total_links}\n"
            f"├─ 🎬 Videos: {video_count}\n"
            f"└─ 📄 PDFs: {pdf_count}\n\n"
            f"🚀 <b>Extracted by</b>: @{(await app.get_me()).username}\n\n"
            f"<code>╾───• {BOT_TEXT} •───╼</code>"
        )
        
        with open(f"{clean_file_name}.txt", 'rb') as f:
            await msg.delete()
            await status_msg.delete()
            await m.reply_document(
                document=f,
                caption=caption,
                file_name=f"{clean_batch_name}.txt"
            )
            
        try:
            os.remove(f"{clean_file_name}.txt")
        except:
            pass


@app.on_message(filters.command(["dams"]))
async def dams_command(client, message):
    try:
        user_id = message.from_user.id
        await process_dams(client, message, user_id)
    except Exception as e:
        await message.reply_text(f"Error: {str(e)}")

@app.on_callback_query(filters.regex("^dams_$"))
async def dams_callback(client, callback_query):
    try:
        user_id = callback_query.from_user.id
        await callback_query.answer()
        await process_dams(client, callback_query.message, user_id)
    except Exception as e:
        try:
            await callback_query.message.reply_text(f"Error: {str(e)}")
        except:
            pass
