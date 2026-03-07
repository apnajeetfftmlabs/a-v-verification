import telebot
import firebase_admin
from firebase_admin import db, credentials
import cv2
import pytesseract
import numpy as np
import re
import time
from datetime import datetime, timedelta
import os
import json

# ============================================
# 🔥 CONFIG
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8601876917:AAFuvwzoWbBsUZr26Q-svPnsxcdYop-yYds")
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', "-1003804079056")

# ============================================
# 🔥 FIREBASE SETUP
# ============================================
try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDS')
    if firebase_creds_json:
        firebase_creds = json.loads(firebase_creds_json)
        cred = credentials.Certificate(firebase_creds)
        print("✅ Firebase connected using env")
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
        print("⚠️ Using local file")
    
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://apnajeet-email-default-rtdb.firebaseio.com/'
    })
    
except Exception as e:
    print(f"❌ Firebase error: {e}")

# ============================================
# 🔥 TESSERACT SETUP
# ============================================
try:
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    print("✅ Tesseract configured")
except Exception as e:
    print(f"⚠️ Tesseract error: {e}")

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
3. Send screen recording video

Bot will verify email and ad page only.
    """)

@bot.message_handler(commands=['verify'])
def verify_start(message):
    user_id = message.chat.id
    user_state[user_id] = {
        'step': 'waiting_player_id',
        'username': message.from_user.username,
        'name': message.from_user.full_name
    }
    bot.reply_to(message, "🔢 Please type your 10-digit Player ID (from Profile screen):")

# ============================================
# HANDLE PLAYER ID
# ============================================
@bot.message_handler(func=lambda message: user_state.get(message.chat.id, {}).get('step') == 'waiting_player_id')
def handle_player_id(message):
    user_id = message.chat.id
    player_id = message.text.strip()
    
    # Remove any non-digits
    player_id = re.sub(r'[^0-9]', '', player_id)
    
    if len(player_id) == 10:
        user_state[user_id]['player_id'] = player_id
        user_state[user_id]['step'] = 'waiting_video'
        bot.reply_to(message, f"✅ Player ID saved: {player_id}\n\n🎥 Now send your screen recording video (30-60 seconds)")
    else:
        bot.reply_to(message, f"❌ Invalid Player ID. Please enter exactly 10 digits (you entered {len(player_id)} digits)")

# ============================================
# RECEIVE VIDEO
# ============================================
@bot.message_handler(content_types=['video'])
def handle_video(message):
    user_id = message.chat.id
    
    if user_id not in user_state:
        bot.reply_to(message, "Please start with /verify first")
        return
    
    if user_state[user_id].get('step') != 'waiting_video':
        bot.reply_to(message, "Please type your Player ID first using /verify")
        return
    
    bot.reply_to(message, "📥 Video received! Processing... This may take 30-60 seconds.")
    
    # Download video
    file_id = message.video.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Save video temporarily
    video_path = f"videos/{user_id}_{int(time.time())}.mp4"
    os.makedirs("videos", exist_ok=True)
    with open(video_path, 'wb') as f:
        f.write(downloaded_file)
    
    # Process video
    process_video(user_id, video_path, message)

def extract_text_from_frame(frame):
    """Extract text using pytesseract"""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        text = pytesseract.image_to_string(thresh)
        return text
    except Exception as e:
        print(f"OCR Error: {e}")
        return ""

def process_video(user_id, video_path, message):
    """Extract and verify - using manual Player ID"""
    try:
        # Get video duration
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        cap.release()
        
        print(f"Video duration: {duration:.1f} seconds")
        
        # Extract frames - har 2 second ka frame
        timestamps = []
        for i in range(2, int(duration), 2):
            timestamps.append(i)
        
        frames = extract_frames(video_path, timestamps)
        print(f"Extracted {len(frames)} frames")
        
        # Initialize extracted data
        extracted_data = {
            'player_id': user_state[user_id]['player_id'],  # Manual entry
            'profile_date': None,
            'email_date': None,
            'email_lines': [],
            'ad_text': "",
        }
        
        # Process each frame
        for frame in frames:
            text = extract_text_from_frame(frame)
            
            # Skip if no text
            if not text or len(text) < 10:
                continue
            
            # Extract Profile Date (DD/MM/YYYY)
            if not extracted_data['profile_date']:
                date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', text)
                if date_match:
                    extracted_data['profile_date'] = date_match.group(1).replace('-', '/')
                    print(f"✅ Found Profile Date: {extracted_data['profile_date']}")
            
            # Extract Email Date (Month DD, YYYY)
            if not extracted_data['email_date']:
                email_date_match = re.search(r'([A-Z][a-z]+ \d{1,2}, \d{4})', text)
                if email_date_match:
                    extracted_data['email_date'] = email_date_match.group(1)
                    print(f"✅ Found Email Date: {extracted_data['email_date']}")
            
            # Collect email lines
            keywords = ['gold', 'stansberry', 'cramer', 'investment', 'stock', 'dear reader', 
                        'market', 'trade', 'club', 'elite', 'price']
            if any(keyword in text.lower() for keyword in keywords):
                lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 15]
                extracted_data['email_lines'].extend(lines)
            
            # Collect ad text
            ad_keywords = ['elite trade club', 'start your day', 'pre-market report', 
                          'closing bell', 'subscribe', 'newsletter']
            if any(keyword in text.lower() for keyword in ad_keywords):
                extracted_data['ad_text'] += text + "\n"
        
        # Remove duplicates
        extracted_data['email_lines'] = list(dict.fromkeys(extracted_data['email_lines']))
        
        print(f"Manual Player ID: {extracted_data['player_id']}")
        print(f"Profile Date: {extracted_data['profile_date']}")
        print(f"Email Date: {extracted_data['email_date']}")
        print(f"Email lines: {len(extracted_data['email_lines'])}")
        
        # Verify with Firebase
        verification_result = verify_extracted_data(extracted_data)
        
        # Prepare result message
        if verification_result['verified']:
            admin_msg = f"""
✅ VERIFICATION SUCCESSFUL
━━━━━━━━━━━━━━━━━━━━━━
👤 User: @{user_state[user_id]['username'] or 'N/A'}
👤 Player ID: {extracted_data['player_id']} (manual)
📅 Profile Date: {extracted_data['profile_date']}
📧 Email Date: {extracted_data['email_date']}
📊 Match: {verification_result['match_score']}%
📝 Lines: {verification_result['matching_lines']}
🔗 Ad: {verification_result['ad_match']}

⏰ {datetime.now().strftime('%H:%M:%S')}

👉 Add 10 coins manually
            """
            bot.send_message(ADMIN_CHAT_ID, admin_msg)
            
            bot.send_message(user_id, f"""
✅ VERIFICATION SUCCESSFUL!

Player ID: {extracted_data['player_id']}
Match Score: {verification_result['match_score']}%

Admin will add coins within 24 hours.
Thank you for your patience!
            """)
        else:
            bot.send_message(user_id, f"""
❌ VERIFICATION FAILED
Reason: {verification_result['reason']}

Please record again showing:
• Profile screen with date
• Full email content (scroll slowly)
• Ad page after clicking link
            """)
        
        # Cleanup
        os.remove(video_path)
        user_state.pop(user_id, None)
        
    except Exception as e:
        bot.send_message(user_id, "❌ Error processing video. Please try again.")
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ Error: {str(e)}")
        print(f"Error: {e}")

# ============================================
# VERIFICATION FUNCTION
# ============================================
def verify_extracted_data(extracted):
    """Match extracted data with Firebase templates"""
    
    # Check required fields
    if not extracted['profile_date']:
        return {'verified': False, 'reason': 'Profile date not found - show DD/MM/YYYY'}
    
    if not extracted['email_date']:
        return {'verified': False, 'reason': 'Email date not found - show Month DD, YYYY'}
    
    if len(extracted['email_lines']) < 3:
        return {'verified': False, 'reason': f'Only {len(extracted["email_lines"])} email lines found - need at least 3'}
    
    # Get templates from Firebase
    today = datetime.now().strftime('%Y-%m-%d')
    email_ref = db.reference(f'email_templates/{today}/client1')
    email_template = email_ref.get()
    
    ad_ref = db.reference('ad_pages/client1')
    ad_template = ad_ref.get()
    
    if not email_template:
        return {'verified': False, 'reason': 'No email template found for today'}
    
    # Match email lines
    template_lines = email_template.get('lines', [])
    matching_lines = []
    
    for t_line in template_lines:
        t_clean = t_line.lower().strip()
        for e_line in extracted['email_lines']:
            e_clean = e_line.lower().strip()
            if len(t_clean) > 15 and len(e_clean) > 15:
                # Check word overlap
                t_words = set(t_clean.split())
                e_words = set(e_clean.split())
                common = t_words.intersection(e_words)
                if len(common) >= 3:
                    matching_lines.append(t_line)
                    break
    
    # Date match (allow ±1 day)
    date_match = dates_match(extracted['profile_date'], extracted['email_date'])
    
    # Ad page match
    ad_match = False
    ad_phrases = 0
    if ad_template and extracted['ad_text']:
        required = ad_template.get('required_phrases', [])
        for phrase in required:
            if phrase.lower() in extracted['ad_text'].lower():
                ad_phrases += 1
        ad_match = ad_phrases >= len(required) * 0.5
    
    # Calculate score
    match_score = len(matching_lines) / len(template_lines) * 100 if template_lines else 0
    
    # Decision
    if match_score >= 20 and date_match and ad_match:
        return {
            'verified': True,
            'match_score': round(match_score, 1),
            'matching_lines': len(matching_lines),
            'ad_match': f"{ad_phrases}/{len(ad_template.get('required_phrases', []))}"
        }
    else:
        reasons = []
        if match_score < 20:
            reasons.append(f"Email mismatch ({round(match_score,1)}%)")
        if not date_match:
            reasons.append("Date mismatch")
        if not ad_match:
            reasons.append("Ad page mismatch")
        
        return {'verified': False, 'reason': ', '.join(reasons)}

# ============================================
# HELPER FUNCTIONS
# ============================================
def extract_frames(video_path, timestamps):
    frames = []
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    for ts in timestamps:
        frame_number = int(ts * fps)
        if frame_number < 0:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    
    cap.release()
    return frames

def dates_match(profile_date, email_date):
    try:
        profile = datetime.strptime(profile_date, '%d/%m/%Y')
        email = datetime.strptime(email_date, '%B %d, %Y')
        diff = abs((profile - email).days)
        return diff <= 1
    except Exception as e:
        print(f"Date match error: {e}")
        return False

# ============================================
# ADMIN COMMANDS
# ============================================
@bot.message_handler(commands=['upload_email'])
def admin_upload_email(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    msg = bot.reply_to(message, "📧 Paste today's email content:")
    bot.register_next_step_handler(msg, save_email)

def save_email(message):
    text = message.text
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    today = datetime.now().strftime('%Y-%m-%d')
    ref = db.reference(f'email_templates/{today}/client1')
    ref.set({
        'lines': lines,
        'line_count': len(lines),
        'uploaded_at': time.time()
    })
    
    bot.reply_to(message, f"✅ Saved! {len(lines)} lines for {today}")

# ============================================
# START BOT
# ============================================
print("=" * 50)
print("🤖 ApnaJeet Video Verification Bot")
print("✅ Version: 3.0 (Manual Player ID)")
print(f"✅ Admin Chat ID: {ADMIN_CHAT_ID}")
print("=" * 50)

try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
except Exception as e:
    print(f"❌ Bot polling error: {e}")
    time.sleep(5)
    bot.infinity_polling()
