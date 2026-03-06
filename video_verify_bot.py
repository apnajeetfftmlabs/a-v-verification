import telebot
import firebase_admin
from firebase_admin import db, credentials
import cv2
import pytesseract
import numpy as np
import re
import time
from datetime import datetime
import os
import json

# 🔥 CONFIG - Environment variables se lo
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8601876917:AAFuvwzoWbBsUZr26Q-svPnsxcdYop-yYds")
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', "-1003804079056")  # Aapka Telegram ID

# 🔥 Firebase setup with environment variable
try:
    # Pehle env variable se try karo
    firebase_creds_json = os.environ.get('FIREBASE_CREDS')
    if firebase_creds_json:
        firebase_creds = json.loads(firebase_creds_json)
        cred = credentials.Certificate(firebase_creds)
        print("✅ Firebase connected using environment variable")
    else:
        # Fallback: local file (development ke liye)
        cred = credentials.Certificate("serviceAccountKey.json")
        print("⚠️ Using local serviceAccountKey.json (development mode)")
    
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://apnajeet-email-default-rtdb.firebaseio.com/'
    })
    
except Exception as e:
    print(f"❌ Firebase connection error: {e}")
    # Continue without Firebase? Bot will still work but verification will fail
    firebase_available = False

bot = telebot.TeleBot(BOT_TOKEN)

# User state
user_state = {}

# ============================================
# START COMMAND
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, """
🎮 ApnaJeet Video Verification Bot

Steps to get verified:
1. Start screen recording
2. Show ApnaJeet Profile (Player ID + Date)
3. Show Email content (at least 10 lines)
4. Click ad link and show page
5. Send video

Send /verify to begin
    """)

@bot.message_handler(commands=['verify'])
def verify_start(message):
    user_id = message.chat.id
    user_state[user_id] = {
        'step': 'waiting_video',
        'username': message.from_user.username,
        'name': message.from_user.full_name
    }
    bot.reply_to(message, """
🎥 Please send your screen recording video.

Make sure video clearly shows:
✅ Profile screen (Player ID + Date)
✅ Email content (at least 10 lines)
✅ Ad page after clicking link
    """)

# ============================================
# RECEIVE VIDEO
# ============================================
@bot.message_handler(content_types=['video'])
def handle_video(message):
    user_id = message.chat.id
    
    if user_id not in user_state:
        bot.reply_to(message, "Please start with /verify first")
        return
    
    bot.reply_to(message, "📥 Video received! Processing... This may take 30-60 seconds.")
    
    # Download video
    file_id = message.video.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Save video
    video_path = f"videos/{user_id}_{int(time.time())}.mp4"
    os.makedirs("videos", exist_ok=True)
    with open(video_path, 'wb') as f:
        f.write(downloaded_file)
    
    # Process video
    process_video(user_id, video_path, message)

def process_video(user_id, video_path, message):
    """Process video and extract information"""
    try:
        # Extract frames at different timestamps
        frames = extract_frames(video_path, [5, 15, 25, 35, 45])
        
        # Results
        player_id = None
        profile_date = None
        email_date = None
        email_text = ""
        ad_text = ""
        
        # Analyze each frame
        for frame in frames:
            text = extract_text_from_frame(frame)
            
            # Extract Player ID (10 digits)
            if not player_id:
                id_match = re.search(r'(\d{10})', text)
                if id_match:
                    player_id = id_match.group(1)
            
            # Extract Profile Date (DD/MM/YYYY)
            if not profile_date:
                date_match = re.search(r'(\d{2}/\d{2}/\d{4})', text)
                if date_match:
                    profile_date = date_match.group(1)
            
            # Extract Email Date (Month DD, YYYY)
            if not email_date:
                email_date_match = re.search(r'([A-Z][a-z]+ \d{1,2}, \d{4})', text)
                if email_date_match:
                    email_date = email_date_match.group(1)
            
            # Collect email text
            if "Few AI courses" in text or "Read Online" in text:
                email_text += text + "\n"
            
            # Collect ad text
            if "DeepView" in text or "OpenAI" in text:
                ad_text += text + "\n"
        
        # Verify with Firebase
        verification_result = verify_with_firebase(email_text, player_id, profile_date, email_date, ad_text)
        
        # Send result to ADMIN
        if verification_result['verified']:
            # Send to admin (aap)
            admin_message = f"""
✅ VERIFICATION SUCCESSFUL
━━━━━━━━━━━━━━━━━━━━━━
👤 User: @{user_state[user_id]['username'] or 'N/A'} ({user_state[user_id]['name']})
🆔 Player ID: {player_id}
📅 Profile Date: {profile_date}
📧 Email Date: {email_date}
📊 Match Score: {verification_result['match_score']}%
📝 Lines Matched: {verification_result['matching_lines']}/{verification_result['template_lines']}

🔗 Ad Page: Verified

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

👉 Please add 10 coins manually to this player.
            """
            bot.send_message(ADMIN_CHAT_ID, admin_message)
            
            # Send confirmation to user
            bot.send_message(user_id, f"""
✅ VERIFICATION SUCCESSFUL!

Player ID: {player_id}
Match Score: {verification_result['match_score']}%

⏳ Admin will add coins within 24 hours.
Thank you for your patience!
            """)
            
        else:
            # Send failure to admin (optional)
            admin_message = f"""
❌ VERIFICATION FAILED
━━━━━━━━━━━━━━━━━━
👤 User: @{user_state[user_id]['username'] or 'N/A'}
🆔 Player ID: {player_id or 'Not found'}
❌ Reason: {verification_result['reason']}

Check video manually if needed.
            """
            bot.send_message(ADMIN_CHAT_ID, admin_message)
            
            # Send failure to user
            bot.send_message(user_id, f"""
❌ VERIFICATION FAILED
Reason: {verification_result['reason']}

Please record again following all steps:
1. Show Profile screen clearly
2. Show full email content
3. Click ad link and show page
            """)
        
        # Cleanup
        os.remove(video_path)
        user_state.pop(user_id, None)
        
    except Exception as e:
        bot.send_message(user_id, f"❌ Error processing video. Please try again.")
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ Error: {str(e)}")
        print(f"Error: {e}")

# ============================================
# VIDEO PROCESSING FUNCTIONS
# ============================================
def extract_frames(video_path, timestamps):
    """Extract frames at given timestamps"""
    frames = []
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    for ts in timestamps:
        frame_number = int(ts * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    
    cap.release()
    return frames

def extract_text_from_frame(frame):
    """Extract text from frame using OCR"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    text = pytesseract.image_to_string(thresh)
    return text

# ============================================
# VERIFICATION FUNCTIONS
# ============================================
def verify_with_firebase(email_text, player_id, profile_date, email_date, ad_text):
    """Verify against Firebase templates"""
    
    # Get today's email template
    today = datetime.now().strftime('%Y-%m-%d')
    ref = db.reference(f'email_templates/{today}/client1')
    template = ref.get()
    
    if not template:
        return {'verified': False, 'reason': 'No email template found for today'}
    
    # Get ad template
    ad_ref = db.reference('ad_pages/client1')
    ad_template = ad_ref.get()
    
    # Check Player ID
    if not player_id:
        return {'verified': False, 'reason': 'Player ID not found in video'}
    
    # Check dates
    if not profile_date or not email_date:
        return {'verified': False, 'reason': 'Dates not found in video'}
    
    # Check if dates match (within 1 day)
    if not dates_match(profile_date, email_date):
        return {'verified': False, 'reason': f'Date mismatch: Profile {profile_date} vs Email {email_date}'}
    
    # Check email content
    template_lines = template.get('lines', [])
    email_lines = [line.strip() for line in email_text.split('\n') if line.strip()]
    
    matching_lines = []
    for t_line in template_lines:
        for e_line in email_lines:
            if similar_lines(t_line, e_line):
                matching_lines.append(t_line)
                break
    
    if len(matching_lines) < 10:
        return {
            'verified': False,
            'reason': f'Only {len(matching_lines)} lines matched. Need at least 10',
            'matching_lines': len(matching_lines),
            'template_lines': len(template_lines),
            'match_score': (len(matching_lines) / len(template_lines)) * 100 if template_lines else 0
        }
    
    # Check ad page
    if not ad_template:
        return {'verified': False, 'reason': 'No ad template found'}
    
    required_phrases = ad_template.get('required_phrases', [])
    found_phrases = []
    
    for phrase in required_phrases:
        if phrase.lower() in ad_text.lower():
            found_phrases.append(phrase)
    
    if len(found_phrases) < len(required_phrases) * 0.6:  # 60% match required
        return {
            'verified': False,
            'reason': f'Ad page mismatch. Found {len(found_phrases)}/{len(required_phrases)} phrases'
        }
    
    # All checks passed
    return {
        'verified': True,
        'player_id': player_id,
        'profile_date': profile_date,
        'email_date': email_date,
        'matching_lines': len(matching_lines),
        'template_lines': len(template_lines),
        'match_score': round((len(matching_lines) / len(template_lines)) * 100, 2) if template_lines else 0,
        'ad_match': len(found_phrases)
    }

def dates_match(profile_date, email_date):
    """Check if profile date matches email date"""
    try:
        # Profile: DD/MM/YYYY
        profile = datetime.strptime(profile_date, '%d/%m/%Y')
        
        # Email: Month DD, YYYY
        email = datetime.strptime(email_date, '%B %d, %Y')
        
        diff = abs((profile - email).days)
        return diff <= 1
    except:
        return False

def similar_lines(line1, line2, threshold=0.7):
    """Check if two lines are similar"""
    if abs(len(line1) - len(line2)) > 20:
        return False
    
    matches = sum(1 for a, b in zip(line1, line2) if a == b)
    similarity = matches / max(len(line1), len(line2))
    
    return similarity > threshold

# ============================================
# ADMIN COMMANDS
# ============================================
@bot.message_handler(commands=['upload_email'])
def admin_upload_email(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    msg = bot.reply_to(message, "Paste today's email content:")
    bot.register_next_step_handler(msg, save_email_template)

def save_email_template(message):
    email_text = message.text
    lines = [line.strip() for line in email_text.split('\n') if line.strip()]
    
    today = datetime.now().strftime('%Y-%m-%d')
    ref = db.reference(f'email_templates/{today}/client1')
    ref.set({
        'subject': lines[0] if lines else '',
        'body': email_text,
        'lines': lines,
        'line_count': len(lines),
        'uploaded_at': time.time()
    })
    
    bot.reply_to(message, f"✅ Email template saved! {len(lines)} lines")

@bot.message_handler(commands=['upload_ad'])
def admin_upload_ad(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    msg = bot.reply_to(message, "Paste ad page text and required phrases:")
    bot.register_next_step_handler(msg, save_ad_template)

def save_ad_template(message):
    text = message.text
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    ref = db.reference('ad_pages/client1')
    ref.set({
        'full_text': text,
        'required_phrases': lines[:5],
        'uploaded_at': time.time()
    })
    
    bot.reply_to(message, f"✅ Ad template saved! {len(lines)} lines")

@bot.message_handler(commands=['stats'])
def admin_stats(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    # Get today's verifications from Firebase
    ref = db.reference('verifications')
    verifications = ref.get() or {}
    
    today = datetime.now().strftime('%Y-%m-%d')
    today_count = 0
    total_coins = 0
    
    for vid, vdata in verifications.items():
        if vdata.get('date') == today:
            today_count += 1
            total_coins += vdata.get('coins', 0)
    
    bot.send_message(message.chat.id, f"""
📊 STATS
━━━━━━━━━━━━━━
Today's Verifications: {today_count}
Total Coins Given: {total_coins}
    """)

# ============================================
# START BOT
# ============================================
print("🤖 Video Verification Bot Started...")
print(f"Admin Chat ID: {ADMIN_CHAT_ID}")
print(f"Bot Token: {BOT_TOKEN[:10]}...")
print("=" * 40)

# Start bot
try:
    bot.infinity_polling()
except Exception as e:
    print(f"❌ Bot polling error: {e}")
    time.sleep(5)
    bot.infinity_polling()  # Retry
