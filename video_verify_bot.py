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

Send /verify to begin
    """)

@bot.message_handler(commands=['verify'])
def verify_start(message):
    user_id = message.chat.id
    user_state[user_id] = {
        'step': 'waiting_video',
        'username': message.from_user.username,
        'name': message.from_user.full_name,
        'retry_count': 0
    }
    bot.reply_to(message, "🎥 Send your screen recording video (30-60 seconds)")

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
    
    # Save video temporarily
    video_path = f"videos/{user_id}_{int(time.time())}.mp4"
    os.makedirs("videos", exist_ok=True)
    with open(video_path, 'wb') as f:
        f.write(downloaded_file)
    
    # Process video
    process_video(user_id, video_path, message)

def extract_text_from_frame(frame):
    """Enhanced text extraction with better preprocessing"""
    try:
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Multiple preprocessing techniques
        texts = []
        
        # 1. Original grayscale
        text1 = pytesseract.image_to_string(gray, config='--psm 6')
        texts.append(text1)
        
        # 2. Thresholding
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        text2 = pytesseract.image_to_string(thresh, config='--psm 6')
        texts.append(text2)
        
        # 3. Adaptive thresholding (better for varying lighting)
        thresh2 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                        cv2.THRESH_BINARY, 11, 2)
        text3 = pytesseract.image_to_string(thresh2, config='--psm 6')
        texts.append(text3)
        
        # 4. Increase contrast
        enhanced = cv2.equalizeHist(gray)
        text4 = pytesseract.image_to_string(enhanced, config='--psm 6')
        texts.append(text4)
        
        # 5. Resize (make larger)
        height, width = gray.shape
        if height < 500:
            scale = 2.0
            new_width = int(width * scale)
            new_height = int(height * scale)
            resized = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
            text5 = pytesseract.image_to_string(resized, config='--psm 6')
            texts.append(text5)
        
        # Combine all texts
        combined = " ".join(texts)
        return combined
        
    except Exception as e:
        print(f"OCR Error: {e}")
        return ""

def process_video(user_id, video_path, message):
    """Extract and verify without requiring player ID in Firebase"""
    try:
        # Get video duration
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        cap.release()
        
        print(f"Video duration: {duration:.1f} seconds")
        
        # Extract frames - har second ka frame
        timestamps = []
        for i in range(1, int(duration)):
            timestamps.append(i)
        
        frames = extract_frames(video_path, timestamps)
        print(f"Extracted {len(frames)} frames")
        
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
        frame_count = 0
        for frame in frames:
            frame_count += 1
            text = extract_text_from_frame(frame)
            
            # Skip if no text
            if not text or len(text) < 10:
                continue
            
            print(f"Frame {frame_count}: Found {len(text)} chars")
            
            # 1. Extract Player ID (10 digits) - MULTIPLE PATTERNS
            if not extracted_data['player_id']:
                # Try multiple patterns
                patterns = [
                    r'(\d{10})',  # 1234567890
                    r'(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})',  # 123-456-7890
                    r'ID[:\s]*(\d{10})',  # ID: 1234567890
                    r'Player[:\s]*ID[:\s]*(\d{10})',  # Player ID: 1234567890
                    r'(\d{3}[-]\d{3}[-]\d{4})',  # 123-456-7890 with dash
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        # Clean up - remove non-digits
                        candidate = re.sub(r'[^0-9]', '', match.group(1))
                        if len(candidate) >= 10:
                            extracted_data['player_id'] = candidate[:10]  # Take first 10 digits
                            print(f"✅ Found Player ID: {extracted_data['player_id']} (pattern: {pattern})")
                            break
                
                # If still not found, try to find any 10-digit number
                if not extracted_data['player_id']:
                    all_numbers = re.findall(r'\d+', text)
                    for num in all_numbers:
                        if len(num) == 10:
                            extracted_data['player_id'] = num
                            print(f"✅ Found Player ID (any 10-digit): {extracted_data['player_id']}")
                            break
            
            # 2. Extract Profile Date (DD/MM/YYYY)
            if not extracted_data['profile_date']:
                date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', text)
                if date_match:
                    extracted_data['profile_date'] = date_match.group(1).replace('-', '/')
                    print(f"✅ Found Profile Date: {extracted_data['profile_date']}")
            
            # 3. Extract Email Date (Month DD, YYYY)
            if not extracted_data['email_date']:
                email_date_match = re.search(r'([A-Z][a-z]+ \d{1,2}, \d{4})', text)
                if email_date_match:
                    extracted_data['email_date'] = email_date_match.group(1)
                    print(f"✅ Found Email Date: {extracted_data['email_date']}")
            
            # 4. Collect email lines
            keywords = ['gold', 'stansberry', 'cramer', 'investment', 'stock', 'dear reader', 
                        'market', 'trade', 'club', 'elite', 'price']
            if any(keyword in text.lower() for keyword in keywords):
                lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 15]
                extracted_data['email_lines'].extend(lines)
            
            # 5. Collect ad text
            ad_keywords = ['elite trade club', 'start your day', 'pre-market report', 
                          'closing bell', 'subscribe', 'newsletter']
            if any(keyword in text.lower() for keyword in ad_keywords):
                extracted_data['ad_text'] += text + "\n"
        
        # Remove duplicates
        extracted_data['email_lines'] = list(dict.fromkeys(extracted_data['email_lines']))
        
        print(f"Extracted: Player ID={extracted_data['player_id']}, Profile Date={extracted_data['profile_date']}, Email Date={extracted_data['email_date']}")
        print(f"Email lines: {len(extracted_data['email_lines'])}")
        
        # Verify with Firebase
        verification_result = verify_extracted_data(extracted_data)
        
        # Prepare result message
        if verification_result['verified']:
            admin_msg = f"""
✅ VERIFICATION SUCCESSFUL
━━━━━━━━━━━━━━━━━━━━━━
👤 Player ID: {extracted_data['player_id']}
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
            # Send failure to admin for manual check
            admin_msg = f"""
❌ VERIFICATION FAILED
━━━━━━━━━━━━━━━━━━
👤 User: @{user_state[user_id]['username'] or 'N/A'}
🆔 Player ID: {extracted_data['player_id'] or 'Not found'}
📅 Profile Date: {extracted_data['profile_date'] or 'Not found'}
📧 Email Date: {extracted_data['email_date'] or 'Not found'}
❌ Reason: {verification_result['reason']}

Check video manually if needed.
            """
            bot.send_message(ADMIN_CHAT_ID, admin_msg)
            
            bot.send_message(user_id, f"""
❌ VERIFICATION FAILED
Reason: {verification_result['reason']}

Please record again showing:
• Profile screen clearly (zoom if needed)
• Full email content (scroll slowly)
• Ad page after clicking link

If problem persists, contact admin.
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
    if not extracted['player_id']:
        return {'verified': False, 'reason': 'Player ID not found - make sure 10-digit number is visible'}
    
    if len(extracted['player_id']) != 10:
        return {'verified': False, 'reason': f'Player ID should be 10 digits, got {len(extracted["player_id"])}'}
    
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
                # Check if line contains key parts
                if t_clean in e_clean or e_clean in t_clean:
                    matching_lines.append(t_line)
                    break
                # Or check word overlap
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

@bot.message_handler(commands=['stats'])
def admin_stats(message):
    if message.chat.id != int(ADMIN_CHAT_ID):
        return
    
    bot.send_message(message.chat.id, "📊 Bot is running normally!")

# ============================================
# START BOT
# ============================================
print("=" * 50)
print("🤖 ApnaJeet Video Verification Bot")
print("✅ Version: 2.0 (Enhanced OCR)")
print(f"✅ Admin Chat ID: {ADMIN_CHAT_ID}")
print("=" * 50)

try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
except Exception as e:
    print(f"❌ Bot polling error: {e}")
    time.sleep(5)
    bot.infinity_polling()
