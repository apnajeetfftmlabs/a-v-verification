import telebot
import requests
import os
import json
import time
from datetime import datetime
import re
import firebase_admin
from firebase_admin import db, credentials

# ============================================
# 🔥 CONFIG
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8601876917:AAFuvwzoWbBsUZr26Q-svPnsxcdYop-yYds")
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', "-1003804079056")
HF_SPACE_URL = "https://dailyupdate8399-apnajeet-video-verifier.hf.space"

# ============================================
# 🔥 FIREBASE SETUP
# ============================================
try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDS')
    if firebase_creds_json:
        firebase_creds = json.loads(firebase_creds_json)
        cred = credentials.Certificate(firebase_creds)
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://apnajeet-email-default-rtdb.firebaseio.com/'
        })
        print("✅ Firebase connected")
    else:
        print("⚠️ FIREBASE_CREDS not found")
except Exception as e:
    print(f"❌ Firebase error: {e}")

bot = telebot.TeleBot(BOT_TOKEN)
user_state = {}

# ============================================
# FIREBASE FUNCTIONS
# ============================================
def get_email_template(date):
    """Firebase se email template lo"""
    try:
        ref = db.reference(f'email_templates/{date}/client1')
        return ref.get()
    except Exception as e:
        print(f"Firebase error: {e}")
        return None

def get_ad_template():
    """Firebase se ad template lo"""
    try:
        ref = db.reference('ad_pages/client1')
        return ref.get()
    except Exception as e:
        print(f"Firebase error: {e}")
        return None

def verify_with_firebase(extracted_data):
    """Extracted data ko Firebase se match karo"""
    today = datetime.now().strftime('%Y-%m-%d')
    email_template = get_email_template(today)
    ad_template = get_ad_template()
    
    if not email_template:
        return {'verified': False, 'reason': 'No email template found'}
    
    template_lines = email_template.get('lines', [])
    extracted_lines = extracted_data.get('email_lines', [])
    
    matching_lines = []
    for t_line in template_lines:
        for e_line in extracted_lines:
            if len(t_line) > 20 and len(e_line) > 20:
                t_words = set(t_line.lower().split())
                e_words = set(e_line.lower().split())
                common = t_words.intersection(e_words)
                if len(common) >= 3:
                    matching_lines.append(t_line)
                    break
    
    ad_match = False
    if ad_template and extracted_data.get('ad_lines'):
        required = ad_template.get('required_phrases', [])
        found = 0
        for phrase in required:
            for ad_line in extracted_data['ad_lines']:
                if phrase.lower() in ad_line.lower():
                    found += 1
                    break
        ad_match = found >= len(required) * 0.5
    
    date_match = False
    if extracted_data.get('profile_date') and extracted_data.get('email_date'):
        try:
            profile = datetime.strptime(extracted_data['profile_date'], '%d/%m/%Y')
            email = datetime.strptime(extracted_data['email_date'], '%B %d, %Y')
            date_match = abs((profile - email).days) <= 1
        except:
            pass
    
    score = len(matching_lines) / len(template_lines) * 100 if template_lines else 0
    
    return {
        'verified': score >= 20 and date_match and ad_match,
        'score': round(score, 1),
        'matching_lines': len(matching_lines),
        'date_match': date_match,
        'ad_match': ad_match
    }

# ============================================
# BOT COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, """
🎮 ApnaJeet Video Verification Bot

Send /verify to begin
    """)

@bot.message_handler(commands=['verify'])
def verify_start(message):
    user_id = message.chat.id
    user_state[user_id] = {'step': 'waiting_video'}
    bot.reply_to(message, "🎥 Send your screen recording video")

# ============================================
# HANDLE VIDEO
# ============================================
@bot.message_handler(content_types=['video'])
def handle_video(message):
    user_id = message.chat.id
    
    if user_id not in user_state:
        bot.reply_to(message, "Start with /verify first")
        return
    
    bot.reply_to(message, "📥 Video received! Processing... (60 seconds)")
    
    try:
        # Download video
        file_id = message.video.file_id
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        # Save temp
        temp_file = f"temp_{user_id}.mp4"
        with open(temp_file, 'wb') as f:
            f.write(downloaded)
        
        # Send to Hugging Face
        with open(temp_file, 'rb') as f:
            files = {'files': ('video.mp4', f, 'video/mp4')}
            response = requests.post(
                f"{HF_SPACE_URL}/run/predict",
                files=files,
                timeout=120
            )
        
        if response.status_code == 200:
            extracted = response.json()
            if isinstance(extracted, str):
                extracted = json.loads(extracted)
            
            verification = verify_with_firebase(extracted)
            
            result = f"""
🔍 VERIFICATION RESULT
━━━━━━━━━━━━━━━━━━━━━━
👤 Player ID: {extracted.get('player_id', '❌')}
📅 Profile Date: {extracted.get('profile_date', '❌')}
📧 Email Date: {extracted.get('email_date', '❌')}

📊 Score: {verification.get('score', 0)}%
📝 Lines: {verification.get('matching_lines', 0)}
📅 Date: {'✅' if verification.get('date_match') else '❌'}
📢 Ad: {'✅' if verification.get('ad_match') else '❌'}

⏰ {datetime.now().strftime('%H:%M')}

{'✅ VERIFIED - Add 10 coins' if verification.get('verified') else '❌ NOT VERIFIED'}
            """
            
            bot.send_message(ADMIN_CHAT_ID, result)
            bot.send_message(user_id, "✅ Video processed!")
            
        else:
            bot.send_message(ADMIN_CHAT_ID, f"❌ HF Error: {response.status_code}")
        
        os.remove(temp_file)
        user_state.pop(user_id, None)
        
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ Error: {str(e)[:100]}")
        if os.path.exists(temp_file):
            os.remove(temp_file)

# ============================================
# START
# ============================================
if __name__ == "__main__":
    print("🤖 Bot starting...")
    bot.infinity_polling()
