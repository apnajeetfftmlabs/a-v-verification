import telebot
import requests
import os
import time
from datetime import datetime
import re

# ============================================
# 🔥 CONFIG
# ============================================
BOT_TOKEN = "8601876917:AAFuvwzoWbBsUZr26Q-svPnsxcdYop-yYds"
ADMIN_CHAT_ID = "-1003804079056"
HF_SPACE_URL = "https://dailyupdate8399-apnajeet-video-verifier.hf.space"

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
2. Type Player ID
3. Type Date
4. Send video
    """)

@bot.message_handler(commands=['verify'])
def verify_start(message):
    user_id = message.chat.id
    user_state[user_id] = {'step': 'waiting_player_id'}
    bot.reply_to(message, "🔢 Step 1/3: Type your 10-digit Player ID:")

# ============================================
# HANDLE PLAYER ID
# ============================================
@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get('step') == 'waiting_player_id')
def handle_player_id(message):
    user_id = message.chat.id
    player_id = re.sub(r'\D', '', message.text.strip())
    
    if len(player_id) == 10:
        user_state[user_id]['player_id'] = player_id
        user_state[user_id]['step'] = 'waiting_profile_date'
        bot.reply_to(message, f"✅ Player ID: {player_id}\n\n📅 Step 2/3: Type Date (DD/MM/YYYY)")
    else:
        bot.reply_to(message, "❌ Enter 10 digits")

# ============================================
# HANDLE DATE
# ============================================
@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get('step') == 'waiting_profile_date')
def handle_profile_date(message):
    user_id = message.chat.id
    date_str = message.text.strip()
    
    if re.match(r'^\d{2}/\d{2}/\d{4}$', date_str):
        user_state[user_id]['profile_date'] = date_str
        user_state[user_id]['step'] = 'waiting_video'
        bot.reply_to(message, f"✅ Date: {date_str}\n\n🎥 Step 3/3: Send video")
    else:
        bot.reply_to(message, "❌ Use DD/MM/YYYY")

# ============================================
# HANDLE VIDEO
# ============================================
@bot.message_handler(content_types=['video'])
def handle_video(message):
    user_id = message.chat.id
    
    if user_id not in user_state or user_state[user_id].get('step') != 'waiting_video':
        bot.reply_to(message, "Start with /verify first")
        return
    
    bot.reply_to(message, "📥 Video received! Admin will verify.")
    
    # Send to admin group
    admin_msg = f"""🔍 NEW VERIFICATION
👤 User: @{message.from_user.username or 'N/A'}
🆔 Player ID: {user_state[user_id]['player_id']}
📅 Date: {user_state[user_id]['profile_date']}
⏰ {datetime.now().strftime('%H:%M')}

👉 Check video manually"""
    
    bot.send_message(ADMIN_CHAT_ID, admin_msg)
    user_state.pop(user_id, None)

# ============================================
# STATUS COMMAND
# ============================================
@bot.message_handler(commands=['status'])
def status(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    # Check HF Space
    hf_status = "❌ Down"
    try:
        r = requests.get(HF_SPACE_URL, timeout=3)
        hf_status = "✅ Online" if r.status_code == 200 else f"⚠️ {r.status_code}"
    except:
        hf_status = "❌ Unreachable"
    
    bot.reply_to(message, f"📊 BOT STATUS\n✅ Bot: Running\n🤖 HF: {hf_status}\n👥 Users: {len(user_state)}")

# ============================================
# START
# ============================================
if __name__ == "__main__":
    print("🤖 Bot starting...")
    bot.infinity_polling()
