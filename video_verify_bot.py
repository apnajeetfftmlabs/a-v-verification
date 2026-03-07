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
# 🔥 FIX TESSERACT PATH
# ============================================
try:
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    if os.path.exists('/usr/bin/tesseract'):
        print("✅ Tesseract found")
    else:
        print("⚠️ Tesseract not found")
        
    possible_paths = [
        '/usr/share/tesseract-ocr/5/tessdata/',
        '/usr/share/tesseract-ocr/4.00/tessdata/',
        '/usr/share/tesseract-ocr/tessdata/'
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            os.environ['TESSDATA_PREFIX'] = path
            print(f"✅ TESSDATA_PREFIX set")
            break
except Exception as e:
    print(f"⚠️ Error: {e}")

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

bot = telebot.TeleBot(BOT_TOKEN)
user_state = {}

# ============================================
# START COMMAND
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
    user_state[user_id] = {
        'step': 'waiting_video',
        'username': message.from_user.username,
        'name': message.from_user.full_name
    }
    bot.reply_to(message, "🎥 Send your screen recording video")

# ============================================
# RECEIVE VIDEO
# ============================================
@bot.message_handler(content_types=['video'])
def handle_video(message):
    user_id = message.chat.id
    
    if user_id not in user_state:
        bot.reply_to(message, "Please start with /verify first")
        return
    
    bot.reply_to(message, "📥 Video received! Processing...")
    
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

def process_video(user_id, video_path, message):
    """Extract and verify without requiring player ID in Firebase"""
    try:
        # Extract frames
        frames = extract_frames(video_path, [5, 10, 15, 20, 25, 30, 35, 40, 45, 50])
        
        # Initialize extracted data
        extracted_data = {
            'player_id': None,
            'profile_date': None,
            'email_date': None,
            'email_lines': [],
            'ad_text': "",
            'confidence': 0
        }
        
        # Process each frame
        for frame in frames:
            text = extract_text_from_frame(frame)
            
            # 1. Extract Player ID (10 digits) - more flexible regex
            if not extracted_data['player_id']:
                # Match 10 digits with possible spaces/dashes
                patterns = [
                    r'(\d{10})',  # 1234567890
                    r'(\d{3}[-\s]?\d{3}[-\s]?\d{4})',  # 123-456-7890
                    r'ID[:\s]*(\d{10})',  # ID: 1234567890
                    r'Player[:\s]*ID[:\s]*(\d{10})'  # Player ID: 1234567890
                ]
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        extracted_data['player_id'] = match.group(1).replace('-', '').replace(' ', '')
                        print(f"✅ Found Player ID: {extracted_data['player_id']}")
                        break
            
            # 2. Extract Profile Date (DD/MM/YYYY)
            if not extracted_data['profile_date']:
                date_match = re.search(r'(\d{2}/\d{2}/\d{4})', text)
                if date_match:
                    extracted_data['profile_date'] = date_match.group(1)
                    print(f"✅ Found Profile Date: {extracted_data['profile_date']}")
            
            # 3. Extract Email Date (Month DD, YYYY)
            if not extracted_data['email_date']:
                email_date_match = re.search(r'([A-Z][a-z]+ \d{1,2}, \d{4})', text)
                if email_date_match:
                    extracted_data['email_date'] = email_date_match.group(1)
                    print(f"✅ Found Email Date: {extracted_data['email_date']}")
            
            # 4. Collect email lines
            if any(keyword in text.lower() for keyword in ['gold', 'stansberry', 'cramer', 'investment', 'stock']):
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                extracted_data['email_lines'].extend(lines)
            
            # 5. Collect ad text
            if 'elite trade club' in text.lower() or 'start your day' in text.lower():
                extracted_data['ad_text'] += text + "\n"
        
        # Remove duplicates from email lines
        extracted_data['email_lines'] = list(dict.fromkeys(extracted_data['email_lines']))
        
        # Verify with Firebase
        verification_result = verify_extracted_data(extracted_data)
        
        # Prepare result message
        if verification_result['verified']:
            # Send to admin group
            admin_msg = f"""
✅ VERIFICATION SUCCESSFUL
━━━━━━━━━━━━━━━━━━━━━━
👤 User: @{extracted_data['player_id']}
📅 Profile Date: {extracted_data['profile_date']}
📧 Email Date: {extracted_data['email_date']}
📊 Match Score: {verification_result['match_score']}%
📝 Lines Matched: {verification_result['matching_lines']}
🔗 Ad Page: {verification_result['ad_match']}%

⏰ {datetime.now().strftime('%H:%M:%S')}

👉 Add 10 coins manually
            """
            bot.send_message(ADMIN_CHAT_ID, admin_msg)
            
            bot.send_message(user_id, f"""
✅ VERIFICATION SUCCESSFUL!

Player ID: {extracted_data['player_id']}
Match Score: {verification_result['match_score']}%

Admin will add coins.
            """)
        else:
            bot.send_message(user_id, f"""
❌ VERIFICATION FAILED
Reason: {verification_result['reason']}

Please record again showing:
• Profile screen
• Full email content
• Ad page
            """)
        
        # Cleanup
        os.remove(video_path)
        user_state.pop(user_id, None)
        
    except Exception as e:
        bot.send_message(user_id, "❌ Error. Please try again.")
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ Error: {str(e)}")
        print(f"Error: {e}")

# ============================================
# VERIFICATION FUNCTION
# ============================================
def verify_extracted_data(extracted):
    """Match extracted data with Firebase templates"""
    
    # Check required fields
    if not extracted['player_id']:
        return {'verified': False, 'reason': 'Player ID not clear. Make sure 10-digit number visible'}
    
    if not extracted['profile_date']:
        return {'verified': False, 'reason': 'Profile date not found'}
    
    if not extracted['email_date']:
        return {'verified': False, 'reason': 'Email date not found'}
    
    if len(extracted['email_lines']) < 5:
        return {'verified': False, 'reason': f'Only {len(extracted["email_lines"])} lines found. Need more'}
    
    # Get templates from Firebase
    today = datetime.now().strftime('%Y-%m-%d')
    email_ref = db.reference(f'email_templates/{today}/client1')
    email_template = email_ref.get()
    
    ad_ref = db.reference('ad_pages/client1')
    ad_template = ad_ref.get()
    
    if not email_template:
        return {'verified': False, 'reason': 'No template for today'}
    
    # Match email lines
    template_lines = email_template.get('lines', [])
    matching_lines = []
    
    for t_line in template_lines:
        for e_line in extracted['email_lines']:
            if len(t_line) > 10 and len(e_line) > 10:
                # Simple similarity check
                common = sum(1 for a, b in zip(t_line.lower(), e_line.lower()) if a == b)
                similarity = common / max(len(t_line), len(e_line))
                if similarity > 0.6:
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
        ad_match = ad_phrases >= len(required) * 0.6
    
    # Calculate score
    match_score = len(matching_lines) / len(template_lines) * 100 if template_lines else 0
    
    # Decision
    if match_score >= 30 and date_match and ad_match:
        return {
            'verified': True,
            'match_score': round(match_score, 1),
            'matching_lines': len(matching_lines),
            'ad_match': f"{ad_phrases}/{len(ad_template.get('required_phrases', []))}"
        }
    else:
        reasons = []
        if match_score < 30:
            reasons.append(f"Low match ({round(match_score,1)}%)")
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
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    
    cap.release()
    return frames

def extract_text_from_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    return pytesseract.image_to_string(thresh)

def dates_match(profile_date, email_date):
    try:
        profile = datetime.strptime(profile_date, '%d/%m/%Y')
        email = datetime.strptime(email_date, '%B %d, %Y')
        diff = abs((profile - email).days)
        return diff <= 1
    except:
        return False

# ============================================
# ADMIN COMMANDS
# ============================================
@bot.message_handler(commands=['upload_email'])
def admin_upload_email(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    msg = bot.reply_to(message, "Paste email content:")
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
    
    bot.reply_to(message, f"✅ Saved! {len(lines)} lines")

@bot.message_handler(commands=['stats'])
def admin_stats(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    bot.send_message(message.chat.id, "📊 Bot is running!")

# ============================================
# START BOT
# ============================================
print("=" * 40)
print("🤖 Bot Started")
print(f"✅ Admin: {ADMIN_CHAT_ID}")
print("=" * 40)

try:
    bot.infinity_polling()
except Exception as e:
    print(f"Error: {e}")
    time.sleep(5)
    bot.infinity_polling()
