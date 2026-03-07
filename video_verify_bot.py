import telebot
import requests
import os
import time
import json
from datetime import datetime
import re

# ============================================
# 🔥 CONFIG
# ============================================
BOT_TOKEN = "8601876917:AAFuvwzoWbBsUZr26Q-svPnsxcdYop-yYds"
ADMIN_CHAT_ID = "-1003804079056"

# Hugging Face Space URL
# Line 11-12 mein yeh change karo:

# ✅ Updated URL (remove extra /gradio_api)
HF_SPACE_URL = "https://dailyupdate8399-apnajeet-video-verifier.hf.space"
HF_API_URL = f"{HF_SPACE_URL}/gradio_api/call/predict"  # ✅ Yeh sahi hai

bot = telebot.TeleBot(BOT_TOKEN)
user_state = {}

# ============================================
# START COMMAND
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, """
🎮 ApnaJeet Video Verification Bot

Steps:
1. Send /verify
2. Type your 10-digit Player ID
3. Type Profile Date (DD/MM/YYYY)
4. Send video
    """)

@bot.message_handler(commands=['verify'])
def verify_start(message):
    user_id = message.chat.id
    user_state[user_id] = {
        'step': 'waiting_player_id',
        'username': message.from_user.username,
        'name': message.from_user.full_name
    }
    bot.reply_to(message, "🔢 Step 1/3: Type your 10-digit Player ID:")

# ============================================
# HANDLE PLAYER ID
# ============================================
@bot.message_handler(func=lambda message: user_state.get(message.chat.id, {}).get('step') == 'waiting_player_id')
def handle_player_id(message):
    user_id = message.chat.id
    player_id = message.text.strip()
    player_id = ''.join(filter(str.isdigit, player_id))
    
    if len(player_id) == 10:
        user_state[user_id]['player_id'] = player_id
        user_state[user_id]['step'] = 'waiting_profile_date'
        bot.reply_to(message, f"✅ Player ID saved: {player_id}\n\n📅 Step 2/3: Type Profile Date (DD/MM/YYYY)")
    else:
        bot.reply_to(message, f"❌ Invalid ID. Enter 10 digits.")

# ============================================
# HANDLE PROFILE DATE
# ============================================
@bot.message_handler(func=lambda message: user_state.get(message.chat.id, {}).get('step') == 'waiting_profile_date')
def handle_profile_date(message):
    user_id = message.chat.id
    date_str = message.text.strip()
    
    date_pattern = r'^(\d{2})/(\d{2})/(\d{4})$'
    match = re.match(date_pattern, date_str)
    
    if match:
        day, month, year = match.groups()
        if 1 <= int(day) <= 31 and 1 <= int(month) <= 12 and 2000 <= int(year) <= 2100:
            user_state[user_id]['profile_date'] = date_str
            user_state[user_id]['step'] = 'waiting_video'
            bot.reply_to(message, f"✅ Date saved: {date_str}\n\n🎥 Step 3/3: Send video")
        else:
            bot.reply_to(message, "❌ Invalid date. Use DD/MM/YYYY")
    else:
        bot.reply_to(message, "❌ Invalid format. Use DD/MM/YYYY")

# ============================================
# HANDLE VIDEO
# ============================================
@bot.message_handler(content_types=['video'])
def handle_video(message):
    user_id = message.chat.id
    
    if user_id not in user_state:
        bot.reply_to(message, "Please start with /verify first")
        return
    
    if user_state[user_id].get('step') != 'waiting_video':
        bot.reply_to(message, "Please complete steps first")
        return
    
    bot.reply_to(message, "📥 Video received! Processing... (30-60 seconds)")
    
    try:
        # Download video
        file_id = message.video.file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save temp video
        temp_video = f"temp_{user_id}_{int(time.time())}.mp4"
        with open(temp_video, 'wb') as f:
            f.write(downloaded_file)
        
        # Check if Space is alive first
        try:
            health_check = requests.get(HF_SPACE_URL, timeout=5)
            if health_check.status_code != 200:
                bot.reply_to(message, "❌ AI service is currently unavailable. Please try later.")
                os.remove(temp_video)
                return
        except:
            bot.reply_to(message, "❌ Cannot connect to AI service. Please try later.")
            os.remove(temp_video)
            return
        
        # Send to Hugging Face
        with open(temp_video, 'rb') as f:
            files = {'data': ('video.mp4', f, 'video/mp4')}
            response = requests.post(HF_API_URL, files=files, timeout=60)
        
        if response.status_code == 200:
            event_id = response.text.strip()
            
            # Get result
            result_url = f"{HF_SPACE_URL}/gradio_api/call/predict/{event_id}"
            result_response = requests.get(result_url, timeout=30)
            
            ai_result = "No result"
            if result_response.status_code == 200:
                try:
                    result_data = result_response.json()
                    ai_result = json.dumps(result_data)[:150]
                except:
                    ai_result = result_response.text[:150]
            
            # Short result for message
            ai_result_short = ai_result[:100] + "..." if len(ai_result) > 100 else ai_result
            
            # Send to admin
            admin_msg = f"""✅ VERIFICATION
👤 ID: {user_state[user_id]['player_id']}
📅 Date: {user_state[user_id]['profile_date']}
🤖 AI: {ai_result_short}
⏰ {datetime.now().strftime('%H:%M')}"""
            
            bot.send_message(ADMIN_CHAT_ID, admin_msg)
            
            # Send to user
            bot.send_message(user_id, "✅ Video processed! Admin will verify and add coins.")
            
        else:
            error_msg = f"❌ HF Error: {response.status_code}"
            bot.send_message(user_id, "❌ AI service error. Please try later.")
            bot.send_message(ADMIN_CHAT_ID, f"{error_msg}")
        
        # Cleanup
        if os.path.exists(temp_video):
            os.remove(temp_video)
        if user_id in user_state:
            user_state.pop(user_id, None)
        
    except Exception as e:
        error_text = str(e)[:100]
        bot.send_message(user_id, f"❌ Error: Please try again.")
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ Error: {error_text}")
        if os.path.exists(temp_video):
            os.remove(temp_video)
        if user_id in user_state:
            user_state.pop(user_id, None)

# ============================================
# ADMIN COMMANDS
# ============================================
@bot.message_handler(commands=['status'])
def admin_status(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    # Check HF Space status
    hf_status = "❌ Down"
    try:
        r = requests.get(HF_SPACE_URL, timeout=3)
        if r.status_code == 200:
            hf_status = "✅ Online"
    except:
        hf_status = "❌ Unreachable"
    
    bot.send_message(message.chat.id, f"""
📊 BOT STATUS
━━━━━━━━━━━━━━━━
✅ Bot: Running
🤖 HF Space: {hf_status}
👥 Active users: {len(user_state)}
    """)

@bot.message_handler(commands=['restart_hf'])
def admin_restart_hf(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    bot.send_message(message.chat.id, "⚠️ Please restart HF Space manually from Hugging Face website.")

# ============================================
# START BOT
# ============================================
if __name__ == "__main__":
    print("=" * 50)
    print("🤖 ApnaJeet Verification Bot")
    print(f"✅ Admin Chat ID: {ADMIN_CHAT_ID}")
    print(f"✅ HF Space: {HF_SPACE_URL}")
    print("=" * 50)
    
    # Check HF Space
    try:
        r = requests.get(HF_SPACE_URL, timeout=5)
        if r.status_code == 200:
            print("✅ Hugging Face Space is online")
        else:
            print(f"⚠️ HF Space returned {r.status_code}")
    except Exception as e:
        print(f"⚠️ Cannot reach HF Space: {e}")
    
    print("\n🟢 Bot is running...")
    bot.infinity_polling(timeout=60)

