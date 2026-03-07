import telebot
import requests
import os
import time
import json
from datetime import datetime
import re

# ============================================
# 🔥 CONFIG - FIXED URL
# ============================================
BOT_TOKEN = "8601876917:AAFuvwzoWbBsUZr26Q-svPnsxcdYop-yYds"
ADMIN_CHAT_ID = "-1003804079056"

# ✅ FIXED: Correct Gradio 5.x API endpoint
HF_SPACE_URL = "https://dailyupdate8399-apnajeet-video-verifier.hf.space/gradio_api/call/predict"

bot = telebot.TeleBot(BOT_TOKEN)

# User state for manual entry
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

Bot will verify using AI model on Hugging Face
    """)

@bot.message_handler(commands=['verify'])
def verify_start(message):
    user_id = message.chat.id
    user_state[user_id] = {
        'step': 'waiting_player_id',
        'username': message.from_user.username,
        'name': message.from_user.full_name
    }
    bot.reply_to(message, "🔢 Step 1/3: Type your 10-digit Player ID (from Profile screen):")

# ============================================
# HANDLE PLAYER ID
# ============================================
@bot.message_handler(func=lambda message: user_state.get(message.chat.id, {}).get('step') == 'waiting_player_id')
def handle_player_id(message):
    user_id = message.chat.id
    player_id = message.text.strip()
    
    # Remove any non-digits
    player_id = ''.join(filter(str.isdigit, player_id))
    
    if len(player_id) == 10:
        user_state[user_id]['player_id'] = player_id
        user_state[user_id]['step'] = 'waiting_profile_date'
        bot.reply_to(message, f"✅ Player ID saved: {player_id}\n\n📅 Step 2/3: Type Profile Date (DD/MM/YYYY) - example: 07/03/2026")
    else:
        bot.reply_to(message, f"❌ Invalid Player ID. Please enter exactly 10 digits (you entered {len(player_id)} digits)")

# ============================================
# HANDLE PROFILE DATE
# ============================================
@bot.message_handler(func=lambda message: user_state.get(message.chat.id, {}).get('step') == 'waiting_profile_date')
def handle_profile_date(message):
    user_id = message.chat.id
    date_str = message.text.strip()
    
    # Check date format (DD/MM/YYYY)
    date_pattern = r'^(\d{2})/(\d{2})/(\d{4})$'
    match = re.match(date_pattern, date_str)
    
    if match:
        day, month, year = match.groups()
        # Basic validation
        if 1 <= int(day) <= 31 and 1 <= int(month) <= 12 and 2000 <= int(year) <= 2100:
            user_state[user_id]['profile_date'] = date_str
            user_state[user_id]['step'] = 'waiting_video'
            bot.reply_to(message, f"✅ Profile Date saved: {date_str}\n\n🎥 Step 3/3: Now send your screen recording video (30-60 seconds)")
        else:
            bot.reply_to(message, "❌ Invalid date. Please use DD/MM/YYYY format (e.g., 07/03/2026)")
    else:
        bot.reply_to(message, "❌ Invalid format. Please use DD/MM/YYYY (e.g., 07/03/2026)")

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
        bot.reply_to(message, "Please complete steps first:\n1. Player ID\n2. Profile Date")
        return
    
    bot.reply_to(message, "📥 Video received! Sending to AI model for processing... (30-60 seconds)")
    
    try:
        # Download video
        file_id = message.video.file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save temp video with safe name
        temp_video = f"temp_{user_id}_{int(time.time())}.mp4"
        with open(temp_video, 'wb') as f:
            f.write(downloaded_file)
        
        # Send to Hugging Face Space
        with open(temp_video, 'rb') as f:
            files = {'data': ('video.mp4', f, 'video/mp4')}
            response = requests.post(HF_SPACE_URL, files=files, timeout=60)
        
        # Parse result
        if response.status_code == 200:
            # Gradio 5.x returns event_id first
            event_id = response.text.strip()
            
            # Get the actual result
            base_url = "https://dailyupdate8399-apnajeet-video-verifier.hf.space"
            result_url = f"{base_url}/gradio_api/call/predict/{event_id}"
            result_response = requests.get(result_url, timeout=30)
            
            ai_result = "No result"
            if result_response.status_code == 200:
                try:
                    result_data = result_response.json()
                    ai_result = json.dumps(result_data, indent=2)
                except:
                    ai_result = result_response.text[:200]
            else:
                ai_result = f"Error fetching result: {result_response.status_code}"
            
            # ✅ FIX: Truncate AI result to avoid 414 error
            ai_result_short = ai_result[:150] + "..." if len(ai_result) > 150 else ai_result
            
            # Combine with manual data - keep it SHORT
            final_result = f"""✅ VERIFICATION
👤 ID: {user_state[user_id]['player_id']}
📅 Date: {user_state[user_id]['profile_date']}
🤖 AI: {ai_result_short}
⏰ {datetime.now().strftime('%H:%M')}"""
            
            # Send to admin group
            bot.send_message(ADMIN_CHAT_ID, final_result)
            
            # Send to user
            user_msg = f"""✅ VIDEO PROCESSED!

Your Player ID: {user_state[user_id]['player_id']}
Profile Date: {user_state[user_id]['profile_date']}

Admin will verify and add coins within 24 hours.
Thank you for your patience!"""
            
            bot.send_message(user_id, user_msg)
            
        else:
            error_msg = f"❌ HF Error: {response.status_code}"
            bot.send_message(user_id, error_msg)
            bot.send_message(ADMIN_CHAT_ID, f"{error_msg} - {response.text[:100]}")
        
        # Cleanup
        if os.path.exists(temp_video):
            os.remove(temp_video)
        if user_id in user_state:
            user_state.pop(user_id, None)
        
    except requests.exceptions.Timeout:
        bot.send_message(user_id, "❌ AI processing timeout (60 seconds). Please try again.")
    except Exception as e:
        error_text = str(e)[:100]
        bot.send_message(user_id, f"❌ Error: {error_text}")
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
    
    bot.send_message(message.chat.id, f"""
📊 BOT STATUS
━━━━━━━━━━━━━━━━
✅ Bot: Running
✅ Hugging Face: Active
✅ Active users: {len(user_state)}
    """)

@bot.message_handler(commands=['test'])
def admin_test(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    bot.send_message(message.chat.id, "✅ Bot is working! Send a video to test HF Space.")

# ============================================
# START BOT
# ============================================
if __name__ == "__main__":
    print("=" * 50)
    print("🤖 ApnaJeet Verification Bot")
    print(f"✅ Bot Token: {BOT_TOKEN[:10]}...")
    print(f"✅ Admin Chat ID: {ADMIN_CHAT_ID}")
    print(f"✅ Hugging Face URL: {HF_SPACE_URL}")
    print("=" * 50)
    
    # Test HF Space connection
    try:
        test_url = "https://dailyupdate8399-apnajeet-video-verifier.hf.space"
        test_response = requests.get(test_url, timeout=5)
        if test_response.status_code == 200:
            print("✅ Hugging Face Space is reachable")
        else:
            print(f"⚠️ Hugging Face Space returned {test_response.status_code}")
    except Exception as e:
        print(f"⚠️ Cannot reach Hugging Face Space: {e}")
    
    # Start bot
    print("\n🟢 Bot is running...")
    bot.infinity_polling(timeout=60)
