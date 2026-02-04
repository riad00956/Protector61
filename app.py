import telebot
import sqlite3
import datetime
import threading
import time
import os
from telebot import types
from flask import Flask

# ================= FLASK SERVER =================
app = Flask('')

@app.route('/')
def home():
    return "🤖 Bot is running perfectly! 🚀"

def run_web_server():
    app.run(host='0.0.0.0', port=10000)

# ================= CONFIGURATION =================
TOKEN = "8000160699:AAHq1VLvd05PFxFVibuErFx4E6Uf7y6F8HE"  # BotFather থেকে টোকেন দিন
SUPER_ADMIN = 7832264582 # আপনার টেলিগ্রাম আইডি
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=25)

# ================= GLOBAL VARIABLES =================
active_sessions = {}  # {admin_id: user_id, user_id: admin_id}
chat_requests = {}    # {user_id: {"time": timestamp, "status": "pending"}}
cooldowns = {}        # {user_id: timestamp}
broadcast_messages = {}  # {admin_id: {"text": "", "groups": []}}
user_stats = {}       # {user_id: {"messages_sent": 0, "last_active": ""}}
group_settings = {}   # {chat_id: {"link_filter": True, "maintenance": False}}
db_lock = threading.Lock()

try:
    bot.remove_webhook()
except:
    pass

# ================= DATABASE SYSTEM =================
def get_db_connection():
    return sqlite3.connect('bot_database.db', check_same_thread=False)

def init_db():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Users Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            join_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_banned INTEGER DEFAULT 0,
            total_messages INTEGER DEFAULT 0,
            chat_requests INTEGER DEFAULT 0,
            warning_count INTEGER DEFAULT 0
        )''')
        
        # Groups Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            total_messages INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            welcome_message TEXT DEFAULT "Welcome to the group! 👋",
            rules TEXT DEFAULT "Follow the rules and be respectful.",
            link_filter INTEGER DEFAULT 1,
            maintenance_mode INTEGER DEFAULT 0,
            bot_status INTEGER DEFAULT 1,
            leave_message TEXT DEFAULT "Goodbye! 👋"
        )''')
        
        # Admins Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_by INTEGER,
            added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            permissions TEXT DEFAULT "view",
            target_group INTEGER DEFAULT 0,
            is_super INTEGER DEFAULT 0
        )''')
        
        # Messages Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            message_text TEXT,
            message_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            forwarded_to INTEGER DEFAULT 0
        )''')
        
        # Broadcast History
        cursor.execute('''CREATE TABLE IF NOT EXISTS broadcasts (
            broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            message_text TEXT,
            total_groups INTEGER,
            success_count INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Session History
        cursor.execute('''CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            user_id INTEGER,
            start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            end_time DATETIME,
            total_messages INTEGER DEFAULT 0
        )''')
        
        conn.commit()
        conn.close()

init_db()

# ================= HELPER FUNCTIONS =================
def log_activity(user_id, activity_type, details=""):
    """লগ সংরক্ষণ"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO activity_logs 
                        (user_id, activity_type, details, timestamp) 
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)''',
                     (user_id, activity_type, details))
        conn.commit()
        conn.close()

def register_user(user_id, username, first_name, last_name=""):
    """ব্যবহারকারী নিবন্ধন"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''INSERT OR IGNORE INTO users 
                        (user_id, username, first_name, last_name, join_date, last_seen) 
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                     (user_id, username, first_name, last_name))
        conn.commit()
        conn.close()

def update_user_last_seen(user_id):
    """ব্যবহারকারীর সর্বশেষ দেখা আপডেট"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''UPDATE users SET last_seen = CURRENT_TIMESTAMP 
                        WHERE user_id = ?''', (user_id,))
        conn.commit()
        conn.close()

def increment_message_count(user_id, chat_id=None):
    """বার্তা গণনা বৃদ্ধি"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''UPDATE users SET total_messages = total_messages + 1 
                        WHERE user_id = ?''', (user_id,))
        if chat_id:
            cursor.execute('''UPDATE groups SET total_messages = total_messages + 1 
                            WHERE chat_id = ?''', (chat_id,))
        conn.commit()
        conn.close()

def get_user_info(user_id):
    """ব্যবহারকারীর তথ্য প্রাপ্তি"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT username, first_name, last_seen, 
                        is_banned, total_messages, chat_requests, warning_count 
                        FROM users WHERE user_id = ?''', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "username": row[0] or "No username",
                "first_name": row[1] or "No name",
                "last_seen": row[2],
                "is_banned": bool(row[3]),
                "total_messages": row[4],
                "chat_requests": row[5],
                "warning_count": row[6]
            }
        return None

def is_admin(user_id, check_super=False):
    """এডমিন চেক"""
    if user_id == SUPER_ADMIN:
        return True
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        if check_super:
            cursor.execute('SELECT is_super FROM admins WHERE user_id = ?', (user_id,))
        else:
            cursor.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

def add_admin(user_id, added_by, permissions="view"):
    """এডমিন যোগ"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        user_info = get_user_info(user_id)
        username = user_info["username"] if user_info else ""
        cursor.execute('''INSERT OR REPLACE INTO admins 
                        (user_id, username, added_by, permissions) 
                        VALUES (?, ?, ?, ?)''',
                     (user_id, username, added_by, permissions))
        conn.commit()
        conn.close()

def remove_admin(user_id):
    """এডমিন অপসারণ"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

def get_group_info(chat_id):
    """গ্রুপ তথ্য প্রাপ্তি"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT title, added_date, total_messages, 
                        link_filter, maintenance_mode, bot_status 
                        FROM groups WHERE chat_id = ?''', (chat_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "title": row[0],
                "added_date": row[1],
                "total_messages": row[2],
                "link_filter": bool(row[3]),
                "maintenance_mode": bool(row[4]),
                "bot_status": bool(row[5])
            }
        return None

def update_group_setting(chat_id, setting, value):
    """গ্রুপ সেটিং আপডেট"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'UPDATE groups SET {setting} = ? WHERE chat_id = ?', (value, chat_id))
        conn.commit()
        conn.close()

def save_message(user_id, chat_id, message_text, message_type):
    """বার্তা সংরক্ষণ"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO messages 
                        (user_id, chat_id, message_text, message_type) 
                        VALUES (?, ?, ?, ?)''',
                     (user_id, chat_id, message_text, message_type))
        conn.commit()
        conn.close()

# ================= CHAT SESSION MANAGEMENT =================
def start_chat_session(admin_id, user_id):
    """চ্যাট সেশন শুরু"""
    active_sessions[admin_id] = user_id
    active_sessions[user_id] = admin_id
    
    # সেশন লগ সংরক্ষণ
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO sessions (admin_id, user_id, start_time) 
                        VALUES (?, ?, CURRENT_TIMESTAMP)''',
                     (admin_id, user_id))
        conn.commit()
        conn.close()
    
    return cursor.lastrowid

def end_chat_session(user_id):
    """চ্যাট সেশন শেষ"""
    partner_id = active_sessions.get(user_id)
    
    if partner_id:
        # সেশন শেষ করা
        del active_sessions[user_id]
        if partner_id in active_sessions:
            del active_sessions[partner_id]
        
        # লগ আপডেট
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''UPDATE sessions SET end_time = CURRENT_TIMESTAMP 
                            WHERE (admin_id = ? AND user_id = ?) 
                            OR (admin_id = ? AND user_id = ?) 
                            ORDER BY start_time DESC LIMIT 1''',
                         (user_id, partner_id, partner_id, user_id))
            conn.commit()
            conn.close()
        
        return partner_id
    return None

def get_active_session_partner(user_id):
    """সক্রিয় সেশন পার্টনার খুঁজুন"""
    return active_sessions.get(user_id)

# ================= KEYBOARDS =================
def main_menu_keyboard(user_id):
    """প্রধান মেনু কীবোর্ড"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    if is_admin(user_id):
        markup.add("📊 ড্যাশবোর্ড", "👥 ব্যবহারকারী")
        markup.add("📢 ব্রডকাস্ট", "⚙️ সেটিংস")
        markup.add("ℹ️ সাহায্য", "🚪 লগআউট")
        
        if user_id in active_sessions:
            markup.add("🔴 সেশন শেষ করুন")
    else:
        markup.add("🙋‍♂️ সাহায্য চাই", "📞 যোগাযোগ")
        markup.add("ℹ️ তথ্য", "⭐ রেট দিন")
        
        if user_id in active_sessions:
            markup.add("🔴 চ্যাট শেষ করুন")
    
    return markup

def admin_dashboard_keyboard():
    """এডমিন ড্যাশবোর্ড কীবোর্ড"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    markup.add(
        types.InlineKeyboardButton("📈 পরিসংখ্যান", callback_data="stats"),
        types.InlineKeyboardButton("👥 ইউজার ম্যানেজ", callback_data="user_manage")
    )
    markup.add(
        types.InlineKeyboardButton("📢 ব্রডকাস্ট", callback_data="broadcast"),
        types.InlineKeyboardButton("⚙️ গ্রুপ সেটিং", callback_data="group_settings")
    )
    markup.add(
        types.InlineKeyboardButton("➕ এডমিন যোগ", callback_data="add_admin"),
        types.InlineKeyboardButton("➖ এডমিন অপসারণ", callback_data="remove_admin")
    )
    markup.add(
        types.InlineKeyboardButton("📋 লগ দেখুন", callback_data="view_logs"),
        types.InlineKeyboardButton("🔄 আপডেট", callback_data="refresh")
    )
    
    return markup

def user_management_keyboard():
    """ব্যবহারকারী ব্যবস্থাপনা কীবোর্ড"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    markup.add(
        types.InlineKeyboardButton("🔍 ইউজার খুঁজুন", callback_data="search_user"),
        types.InlineKeyboardButton("📊 সকল ইউজার", callback_data="all_users")
    )
    markup.add(
        types.InlineKeyboardButton("🔨 ব্যান ইউজার", callback_data="ban_user"),
        types.InlineKeyboardButton("✅ আনবেন", callback_data="unban_user")
    )
    markup.add(
        types.InlineKeyboardButton("💬 চ্যাট শুরু", callback_data="start_chat"),
        types.InlineKeyboardButton("📝 বার্তা পাঠান", callback_data="send_message")
    )
    markup.add(
        types.InlineKeyboardButton("⚠️ সতর্কতা", callback_data="warn_user"),
        types.InlineKeyboardButton("📋 রিকোয়েস্ট", callback_data="view_requests")
    )
    markup.add(
        types.InlineKeyboardButton("⬅️ পিছনে", callback_data="back_to_dashboard")
    )
    
    return markup

def broadcast_keyboard():
    """ব্রডকাস্ট কীবোর্ড"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    markup.add(
        types.InlineKeyboardButton("🌍 সকল গ্রুপ", callback_data="bc_all_groups"),
        types.InlineKeyboardButton("👥 সকল ইউজার", callback_data="bc_all_users")
    )
    markup.add(
        types.InlineKeyboardButton("📍 নির্দিষ্ট গ্রুপ", callback_data="bc_specific_group"),
        types.InlineKeyboardButton("👤 নির্দিষ্ট ইউজার", callback_data="bc_specific_user")
    )
    markup.add(
        types.InlineKeyboardButton("📅 সময়সূচি", callback_data="schedule_bc"),
        types.InlineKeyboardButton("📋 ইতিহাস", callback_data="bc_history")
    )
    markup.add(
        types.InlineKeyboardButton("⬅️ পিছনে", callback_data="back_to_dashboard")
    )
    
    return markup

def group_settings_keyboard(chat_id=None):
    """গ্রুপ সেটিংস কীবোর্ড"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if chat_id:
        group = get_group_info(chat_id)
        link_status = "✅" if group["link_filter"] else "❌"
        maint_status = "✅" if group["maintenance_mode"] else "❌"
        bot_status = "✅" if group["bot_status"] else "❌"
        
        markup.add(
            types.InlineKeyboardButton(f"{link_status} লিংক ফিল্টার", 
                                     callback_data=f"toggle_link_{chat_id}"),
            types.InlineKeyboardButton(f"{maint_status} মেইনটেনেন্স", 
                                     callback_data=f"toggle_maint_{chat_id}")
        )
        markup.add(
            types.InlineKeyboardButton(f"{bot_status} বট স্ট্যাটাস", 
                                     callback_data=f"toggle_bot_{chat_id}"),
            types.InlineKeyboardButton("📝 ওয়েলকাম মেসেজ", 
                                     callback_data=f"set_welcome_{chat_id}")
        )
        markup.add(
            types.InlineKeyboardButton("📋 নিয়ম", callback_data=f"set_rules_{chat_id}"),
            types.InlineKeyboardButton("🚪 লিভ মেসেজ", callback_data=f"set_leave_{chat_id}")
        )
        markup.add(
            types.InlineKeyboardButton("📊 পরিসংখ্যান", callback_data=f"group_stats_{chat_id}"),
            types.InlineKeyboardButton("👮‍♂️ অ্যাডমিন", callback_data=f"group_admins_{chat_id}")
        )
        markup.add(
            types.InlineKeyboardButton("🗑 গ্রুপ মুছুন", callback_data=f"delete_group_{chat_id}"),
            types.InlineKeyboardButton("🚪 গ্রুপ ছাড়ুন", callback_data=f"leave_group_{chat_id}")
        )
    else:
        markup.add(
            types.InlineKeyboardButton("📂 গ্রুপ তালিকা", callback_data="list_groups"),
            types.InlineKeyboardButton("➕ নতুন গ্রুপ", callback_data="add_group")
        )
    
    markup.add(types.InlineKeyboardButton("⬅️ পিছনে", callback_data="back_to_dashboard"))
    
    return markup

def session_control_keyboard(partner_id=None):
    """সেশন কন্ট্রোল কীবোর্ড"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    markup.add(
        types.InlineKeyboardButton("📎 ফাইল পাঠান", callback_data="send_file"),
        types.InlineKeyboardButton("🖼 ছবি পাঠান", callback_data="send_photo")
    )
    markup.add(
        types.InlineKeyboardButton("🎥 ভিডিও পাঠান", callback_data="send_video"),
        types.InlineKeyboardButton("📄 ডকুমেন্ট", callback_data="send_doc")
    )
    markup.add(
        types.InlineKeyboardButton("📋 লগ", callback_data="view_chat_log"),
        types.InlineKeyboardButton("⏸ বিরতি", callback_data="pause_chat")
    )
    markup.add(
        types.InlineKeyboardButton("🔴 সেশন শেষ", callback_data="end_session"),
        types.InlineKeyboardButton("🚪 প্রস্থান", callback_data="exit_chat")
    )
    
    return markup

def user_request_keyboard(user_id):
    """ব্যবহারকারীর রিকোয়েস্ট কীবোর্ড"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    markup.add(
        types.InlineKeyboardButton("✅ গ্রহণ করুন", callback_data=f"accept_{user_id}"),
        types.InlineKeyboardButton("❌ প্রত্যাখ্যান", callback_data=f"reject_{user_id}")
    )
    markup.add(
        types.InlineKeyboardButton("⏰ পরে দেখুন", callback_data=f"snooze_{user_id}"),
        types.InlineKeyboardButton("🔍 তথ্য দেখুন", callback_data=f"info_{user_id}")
    )
    
    return markup

def confirm_keyboard(action, target_id):
    """কনফার্মেশন কীবোর্ড"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    markup.add(
        types.InlineKeyboardButton("✅ হ্যাঁ", callback_data=f"confirm_{action}_{target_id}"),
        types.InlineKeyboardButton("❌ না", callback_data=f"cancel_{action}_{target_id}")
    )
    
    return markup

# ================= MESSAGE HANDLERS =================
@bot.message_handler(commands=['start', 'help', 'menu'])
def handle_start(message):
    """শুরু, সাহায্য, মেনু কমান্ড"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # ব্যবহারকারী নিবন্ধন
    register_user(user_id, message.from_user.username, 
                  message.from_user.first_name, message.from_user.last_name)
    update_user_last_seen(user_id)
    
    if message.chat.type == "private":
        if message.text == "/start":
            welcome_msg = f"""
🎉 স্বাগতম {message.from_user.first_name}!

🤖 *বট বৈশিষ্ট্য সমূহ:*
• এডমিনের সাথে সরাসরি চ্যাট
• গ্রুপ ম্যানেজমেন্ট
• স্বয়ংক্রিয় মডারেশন
• ব্রডকাস্ট সিস্টেম
• এবং আরও অনেক কিছু!

⚡ *কমান্ড সমূহ:*
/start - শুরু করুন
/help - সাহায্য পান
/menu - প্রধান মেনু
/stats - পরিসংখ্যান
/settings - সেটিংস

📞 সাহায্যের জন্য: @YourSupport
"""
            bot.send_message(chat_id, welcome_msg, parse_mode="Markdown", 
                           reply_markup=main_menu_keyboard(user_id))
        
        elif message.text == "/menu":
            if is_admin(user_id):
                bot.send_message(chat_id, "📊 *এডমিন ড্যাশবোর্ড*", 
                               parse_mode="Markdown", reply_markup=admin_dashboard_keyboard())
            else:
                bot.send_message(chat_id, "🏠 *প্রধান মেনু*", 
                               parse_mode="Markdown", reply_markup=main_menu_keyboard(user_id))
        
        elif message.text == "/help":
            help_msg = """
🆘 *সাহায্য কেন্দ্র*

📞 *যোগাযোগ:*
• সরাসরি সাহায্য: @YourSupport
• রিপোর্ট সমস্যা: /report
• পরামর্শ: /suggest

⚡ *দ্রুত কমান্ড:*
/start - বট শুরু করুন
/menu - মেনু দেখুন
/stats - পরিসংখ্যান দেখুন
/settings - সেটিংস

🔧 *সহায়িকা:*
1. এডমিনের সাথে কথা বলতে "সাহায্য চাই" বাটন ক্লিক করুন
2. অপেক্ষা করুন এডমিনের প্রতিক্রিয়ার জন্য
3. সরাসরি চ্যাট শুরু হলে নিয়মিত যোগাযোগ করুন

⚠️ *নিয়ম:*
• অশালীন ভাষা ব্যবহার নিষিদ্ধ
• স্প্যাম করবেন না
• এডমিনের নির্দেশনা মেনে চলুন
"""
            bot.send_message(chat_id, help_msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📊 ড্যাশবোর্ড")
def handle_dashboard(message):
    """ড্যাশবোর্ড হ্যান্ডলার"""
    user_id = message.from_user.id
    
    if is_admin(user_id):
        # পরিসংখ্যান সংগ্রহ
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # মোট ব্যবহারকারী
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            # মোট গ্রুপ
            cursor.execute('SELECT COUNT(*) FROM groups')
            total_groups = cursor.fetchone()[0]
            
            # আজকের বার্তা
            cursor.execute('''SELECT COUNT(*) FROM messages 
                            WHERE DATE(timestamp) = DATE('now')''')
            today_messages = cursor.fetchone()[0]
            
            # সক্রিয় সেশন
            active_sessions_count = len(active_sessions) // 2
            
            conn.close()
        
        stats_msg = f"""
📊 *সিস্টেম পরিসংখ্যান*

👥 *ব্যবহারকারী:* {total_users}
📂 *গ্রুপ:* {total_groups}
💬 *আজকের বার্তা:* {today_messages}
💬 *সক্রিয় সেশন:* {active_sessions_count}

📈 *দ্রুত অ্যাকশন:*
1️⃣ গ্রুপ ম্যানেজমেন্ট
2️⃣ ব্রডকাস্ট পাঠান
3️⃣ ইউজার দেখুন
4️⃣ সেটিংস পরিবর্তন
"""
        bot.send_message(message.chat.id, stats_msg, parse_mode="Markdown",
                       reply_markup=admin_dashboard_keyboard())
    else:
        bot.send_message(message.chat.id, "⚠️ আপনার এডমিন এক্সেস নেই!",
                       reply_markup=main_menu_keyboard(user_id))

@bot.message_handler(func=lambda m: m.text == "👥 ব্যবহারকারী")
def handle_users(message):
    """ব্যবহারকারী ম্যানেজমেন্ট"""
    user_id = message.from_user.id
    
    if is_admin(user_id):
        bot.send_message(message.chat.id, "👥 *ব্যবহারকারী ব্যবস্থাপনা*",
                       parse_mode="Markdown", reply_markup=user_management_keyboard())
    else:
        bot.send_message(message.chat.id, "⚠️ অনুমতি প্রয়োজন!")

@bot.message_handler(func=lambda m: m.text == "📢 ব্রডকাস্ট")
def handle_broadcast(message):
    """ব্রডকাস্ট হ্যান্ডলার"""
    user_id = message.from_user.id
    
    if is_admin(user_id):
        bot.send_message(message.chat.id, "📢 *ব্রডকাস্ট সিস্টেম*",
                       parse_mode="Markdown", reply_markup=broadcast_keyboard())
    else:
        bot.send_message(message.chat.id, "⚠️ অনুমতি প্রয়োজন!")

@bot.message_handler(func=lambda m: m.text == "⚙️ সেটিংস")
def handle_settings(message):
    """সেটিংস হ্যান্ডলার"""
    user_id = message.from_user.id
    
    if is_admin(user_id):
        bot.send_message(message.chat.id, "⚙️ *গ্রুপ সেটিংস*",
                       parse_mode="Markdown", reply_markup=group_settings_keyboard())
    else:
        # সাধারণ ব্যবহারকারীর সেটিংস
        settings_msg = """
⚙️ *আপনার সেটিংস*

🔔 *বিজ্ঞপ্তি:* সক্রিয়
🌐 *ভাষা:* বাংলা
🎨 *থিম:* ডিফল্ট

🔧 *অন্যান্য:*
• প্রাইভেসি সেটিংস
• ডাটা ব্যবহার
• সাহায্য ও সমর্থন
"""
        bot.send_message(message.chat.id, settings_msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🙋‍♂️ সাহায্য চাই")
def handle_help_request(message):
    """সাহায্য অনুরোধ"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # কো-ওল্ডাউন চেক
    now = time.time()
    if user_id in cooldowns and now - cooldowns[user_id] < 300:  # 5 মিনিট
        remaining = int((300 - (now - cooldowns[user_id])) / 60)
        bot.send_message(chat_id, f"⚠️ অনুগ্রহ করে {remaining} মিনিট পরে আবার চেষ্টা করুন।")
        return
    
    cooldowns[user_id] = now
    
    # রিকোয়েস্ট স্টোর
    chat_requests[user_id] = {
        "time": now,
        "status": "pending",
        "name": message.from_user.first_name,
        "username": message.from_user.username
    }
    
    # বার্তা প্রস্তুত
    request_msg = f"""
🚨 *নতুন সাহায্য অনুরোধ!*

👤 *ব্যবহারকারী:* {message.from_user.first_name}
📱 *ইউজারনেম:* @{message.from_user.username or 'N/A'}
🆔 *আইডি:* `{user_id}`
⏰ *সময়:* {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

📞 *দ্রুত প্রতিক্রিয়া প্রয়োজন!*
"""
    
    # সুপার এডমিনকে নোটিফাই
    try:
        bot.send_message(SUPER_ADMIN, request_msg, parse_mode="Markdown",
                       reply_markup=user_request_keyboard(user_id))
    except:
        pass
    
    # অন্যান্য এডমিনদের নোটিফাই
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        admins = cursor.execute('SELECT user_id FROM admins WHERE user_id != ?', (SUPER_ADMIN,)).fetchall()
        conn.close()
    
    for admin in admins:
        try:
            bot.send_message(admin[0], request_msg, parse_mode="Markdown")
        except:
            pass
    
    # ব্যবহারকারীকে কনফার্মেশন
    bot.send_message(chat_id, "✅ আপনার অনুরোধ পাঠানো হয়েছে! একজন এডমিন শীঘ্রই আপনার সাথে যোগাযোগ করবেন।")

@bot.message_handler(func=lambda m: m.text == "🔴 সেশন শেষ করুন")
def handle_end_session(message):
    """সেশন শেষ"""
    user_id = message.from_user.id
    
    if user_id in active_sessions:
        partner_id = end_chat_session(user_id)
        if partner_id:
            # দুজনকেই নোটিফাই
            bot.send_message(user_id, "✅ চ্যাট সেশন সফলভাবে শেষ হয়েছে।")
            try:
                bot.send_message(partner_id, "ℹ️ অন্য পক্ষ চ্যাট সেশন শেষ করেছেন।")
            except:
                pass
        else:
            bot.send_message(user_id, "❌ সেশন শেষ করতে সমস্যা হয়েছে।")
    else:
        bot.send_message(user_id, "ℹ️ আপনার কোনো সক্রিয় চ্যাট সেশন নেই।")

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio'])
def handle_all_messages(message):
    """সকল বার্তা হ্যান্ডলার"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # সর্বশেষ দেখা আপডেট
    update_user_last_seen(user_id)
    
    # বার্তা গণনা বৃদ্ধি
    increment_message_count(user_id, chat_id if message.chat.type != "private" else None)
    
    # চ্যাট সেশন চেক
    if message.chat.type == "private" and user_id in active_sessions:
        partner_id = active_sessions[user_id]
        
        # বার্তা ফরওয়ার্ড
        try:
            if message.text:
                bot.send_message(partner_id, f"💬 *ব্যবহারকারীর বার্তা:*\n\n{message.text}", parse_mode="Markdown")
            elif message.photo:
                bot.send_photo(partner_id, message.photo[-1].file_id, 
                             caption=f"📸 ব্যবহারকারীর ছবি\n\n{message.caption or ''}")
            elif message.video:
                bot.send_video(partner_id, message.video.file_id,
                             caption=f"🎥 ব্যবহারকারীর ভিডিও\n\n{message.caption or ''}")
            elif message.document:
                bot.send_document(partner_id, message.document.file_id,
                                caption=f"📄 ব্যবহারকারীর ডকুমেন্ট\n\n{message.caption or ''}")
            elif message.audio:
                bot.send_audio(partner_id, message.audio.file_id,
                             caption="🎵 ব্যবহারকারীর অডিও")
            
            # বার্তা লগ
            save_message(user_id, chat_id, 
                        message.text or message.caption or "Media file", 
                        message.content_type)
        except Exception as e:
            bot.send_message(user_id, f"❌ বার্তা পাঠাতে সমস্যা: {str(e)}")
        
        return
    
    # গ্রুপ বার্তা হ্যান্ডলিং
    if message.chat.type != "private":
        # গ্রুপ ডাটাবেসে সংরক্ষণ
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''INSERT OR IGNORE INTO groups 
                            (chat_id, title) VALUES (?, ?)''',
                         (chat_id, message.chat.title))
            conn.commit()
            conn.close()
        
        # গ্রুপ সেটিংস চেক
        group = get_group_info(chat_id)
        if group:
            # মেইনটেনেন্স মোড চেক
            if group["maintenance_mode"] and not is_admin(user_id):
                try:
                    bot.delete_message(chat_id, message.message_id)
                    bot.send_message(chat_id, "🔧 গ্রুপটি বর্তমানে মেইনটেনেন্স মোডে আছে।")
                except:
                    pass
                return
            
            # লিংক ফিল্টার চেক
            if group["link_filter"] and not is_admin(user_id):
                text = message.text or message.caption or ""
                if any(link in text.lower() for link in ["http://", "https://", "t.me/", "www."]):
                    try:
                        bot.delete_message(chat_id, message.message_id)
                        warning_msg = f"""
⚠️ @{message.from_user.username or message.from_user.first_name}
লিংক শেয়ার করার অনুমতি নেই!
                        """
                        bot.send_message(chat_id, warning_msg)
                    except:
                        pass
                    return
            
            # বট স্ট্যাটাস চেক
            if not group["bot_status"]:
                return
        
        # ওয়েলকাম মেসেজ (নতুন সদস্য)
        if message.new_chat_members:
            for member in message.new_chat_members:
                if member.id == bot.get_me().id:
                    welcome_msg = group["welcome_message"] if group else "🤖 বটটি সফলভাবে যোগ দেওয়া হয়েছে!"
                    bot.send_message(chat_id, welcome_msg)
                else:
                    welcome_user = group["welcome_message"] if group else f"🎉 স্বাগতম {member.first_name}!"
                    bot.send_message(chat_id, welcome_user)

# ================= CALLBACK HANDLERS =================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    """সকল কলব্যাক হ্যান্ডলার"""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    # কলব্যাক ডাটা পার্স
    data = call.data
    parts = data.split('_')
    
    try:
        if data == "stats":
            # পরিসংখ্যান দেখান
            show_statistics(call)
            
        elif data == "user_manage":
            # ব্যবহারকারী ব্যবস্থাপনা
            bot.edit_message_text("👥 *ব্যবহারকারী ব্যবস্থাপনা*", chat_id, message_id,
                                parse_mode="Markdown", reply_markup=user_management_keyboard())
        
        elif data == "broadcast":
            # ব্রডকাস্ট মেনু
            bot.edit_message_text("📢 *ব্রডকাস্ট সিস্টেম*", chat_id, message_id,
                                parse_mode="Markdown", reply_markup=broadcast_keyboard())
        
        elif data == "group_settings":
            # গ্রুপ সেটিংস
            bot.edit_message_text("⚙️ *গ্রুপ সেটিংস*", chat_id, message_id,
                                parse_mode="Markdown", reply_markup=group_settings_keyboard())
        
        elif data == "add_admin":
            # এডমিন যোগ
            msg = bot.send_message(chat_id, "➕ *নতুন এডমিন যোগ করুন*\n\nইউজার আইডি পাঠান:", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_add_admin)
        
        elif data == "remove_admin":
            # এডমিন অপসারণ
            show_admin_list_for_removal(call)
        
        elif data == "back_to_dashboard":
            # ড্যাশবোর্ডে ফিরে যান
            bot.edit_message_text("📊 *এডমিন ড্যাশবোর্ড*", chat_id, message_id,
                                parse_mode="Markdown", reply_markup=admin_dashboard_keyboard())
        
        elif data.startswith("accept_"):
            # রিকোয়েস্ট গ্রহণ
            target_user = int(data.split('_')[1])
            accept_chat_request(call, target_user)
        
        elif data.startswith("reject_"):
            # রিকোয়েস্ট প্রত্যাখ্যান
            target_user = int(data.split('_')[1])
            reject_chat_request(call, target_user)
        
        elif data == "end_session":
            # সেশন শেষ
            end_session_callback(call)
        
        elif data.startswith("toggle_link_"):
            # লিংক ফিল্টার টগল
            target_group = int(data.split('_')[2])
            toggle_group_setting(call, target_group, "link_filter")
        
        elif data.startswith("toggle_maint_"):
            # মেইনটেনেন্স টগল
            target_group = int(data.split('_')[2])
            toggle_group_setting(call, target_group, "maintenance_mode")
        
        elif data.startswith("toggle_bot_"):
            # বট স্ট্যাটাস টগল
            target_group = int(data.split('_')[2])
            toggle_group_setting(call, target_group, "bot_status")
        
        elif data == "list_groups":
            # গ্রুপ তালিকা
            list_all_groups(call)
        
        elif data.startswith("leave_group_"):
            # গ্রুপ ছাড়ুন
            target_group = int(data.split('_')[2])
            leave_group_confirmation(call, target_group)
        
        elif data == "bc_all_groups":
            # সকল গ্রুপে ব্রডকাস্ট
            start_broadcast_to_all_groups(call)
        
        elif data == "bc_all_users":
            # সকল ব্যবহারকারীকে ব্রডকাস্ট
            start_broadcast_to_all_users(call)
        
        elif data.startswith("confirm_"):
            # কনফার্মেশন হ্যান্ডল
            handle_confirmation(call, data)
        
        elif data.startswith("cancel_"):
            # ক্যান্সেল হ্যান্ডল
            bot.answer_callback_query(call.id, "❌ অপারেশন বাতিল করা হয়েছে।")
        
        else:
            bot.answer_callback_query(call.id, "ℹ️ এই বৈশিষ্ট্যটি শীঘ্রই আসছে!")
    
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ ত্রুটি: {str(e)}")

# ================= SPECIFIC FUNCTIONS =================
def show_statistics(call):
    """পরিসংখ্যান দেখান"""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # মোট ব্যবহারকারী
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        # সক্রিয় ব্যবহারকারী (সর্বশেষ 24 ঘন্টা)
        cursor.execute('''SELECT COUNT(*) FROM users 
                        WHERE last_seen > datetime('now', '-1 day')''')
        active_users = cursor.fetchone()[0]
        
        # মোট গ্রুপ
        cursor.execute('SELECT COUNT(*) FROM groups')
        total_groups = cursor.fetchone()[0]
        
        # আজকের বার্তা
        cursor.execute('''SELECT COUNT(*) FROM messages 
                        WHERE DATE(timestamp) = DATE('now')''')
        today_messages = cursor.fetchone()[0]
        
        # সক্রিয় সেশন
        active_sessions_count = len(active_sessions) // 2
        
        # সর্বোচ্চ বার্তা প্রেরক
        cursor.execute('''SELECT first_name, total_messages FROM users 
                        ORDER BY total_messages DESC LIMIT 5''')
        top_senders = cursor.fetchall()
        
        conn.close()
    
    # পরিসংখ্যান বার্তা
    stats_msg = f"""
📊 *বিস্তারিত পরিসংখ্যান*

👥 *ব্যবহারকারী:*
• মোট: {total_users}
• সক্রিয়: {active_users}
• নিষ্ক্রিয়: {total_users - active_users}

📂 *গ্রুপ:*
• মোট: {total_groups}
• সক্রিয়: {len([g for g in get_all_groups() if get_group_info(g)['bot_status']])}

💬 *বার্তা:*
• আজ: {today_messages}
• গড়: {today_messages // 24 if today_messages > 0 else 0}/ঘন্টা

💭 *সেশন:*
• সক্রিয়: {active_sessions_count}

🏆 *শীর্ষ বার্তা প্রেরক:*
"""
    
    for i, (name, count) in enumerate(top_senders, 1):
        stats_msg += f"{i}. {name}: {count} বার্তা\n"
    
    bot.edit_message_text(stats_msg, chat_id, message_id, parse_mode="Markdown",
                         reply_markup=admin_dashboard_keyboard())

def accept_chat_request(call, target_user):
    """চ্যাট রিকোয়েস্ট গ্রহণ"""
    user_id = call.from_user.id
    
    # সেশন শুরু
    session_id = start_chat_session(user_id, target_user)
    
    if session_id:
        # রিকোয়েস্ট স্ট্যাটাস আপডেট
        if target_user in chat_requests:
            chat_requests[target_user]["status"] = "accepted"
        
        # এডমিনকে নোটিফাই
        bot.edit_message_text(f"✅ আপনি এখন {target_user} আইডির ব্যবহারকারীর সাথে চ্যাট করছেন।",
                            call.message.chat.id, call.message.message_id)
        
        # ব্যবহারকারীকে নোটিফাই
        try:
            welcome_msg = f"""
🎉 আপনার অনুরোধ গ্রহণ করা হয়েছে!

🤖 এখন আপনি একজন এডমিনের সাথে সরাসরি চ্যাট করতে পারবেন।

💬 *নির্দেশনা:*
• সরাসরি বার্তা লিখুন
• ফাইল শেয়ার করতে পারেন
• প্রয়োজন শেষে "চ্যাট শেষ করুন" বাটন ক্লিক করুন

📞 সহায়তার জন্য: @YourSupport
"""
            bot.send_message(target_user, welcome_msg, parse_mode="Markdown",
                           reply_markup=session_control_keyboard())
            
            # ব্যবহারকারীর কীবোর্ড আপডেট
            bot.send_message(target_user, "💬 এখন চ্যাট শুরু করুন...",
                           reply_markup=main_menu_keyboard(target_user))
        except:
            bot.send_message(user_id, "⚠️ ব্যবহারকারীকে নোটিফিকেশন পাঠানো যায়নি।")
        
        # কীবোর্ড আপডেট (সেশন শেষ বাটন যোগ)
        markup = admin_dashboard_keyboard()
        if user_id in active_sessions:
            markup.add(types.InlineKeyboardButton("🔴 সেশন শেষ করুন", callback_data="end_session"))
        
        bot.send_message(user_id, "💬 চ্যাট সেশন শুরু হয়েছে! বার্তা লিখুন...",
                       reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "❌ সেশন শুরু করতে সমস্যা হয়েছে।")

def reject_chat_request(call, target_user):
    """চ্যাট রিকোয়েস্ট প্রত্যাখ্যান"""
    # রিকোয়েস্ট স্ট্যাটাস আপডেট
    if target_user in chat_requests:
        chat_requests[target_user]["status"] = "rejected"
    
    # এডমিনকে নোটিফাই
    bot.edit_message_text(f"❌ আপনি {target_user} আইডির ব্যবহারকারীর অনুরোধ প্রত্যাখ্যান করেছেন।",
                        call.message.chat.id, call.message.message_id)
    
    # ব্যবহারকারীকে নোটিফাই
    try:
        bot.send_message(target_user, "⚠️ আপনার সাহায্য অনুরোধ প্রত্যাখ্যান করা হয়েছে।")
    except:
        pass

def end_session_callback(call):
    """সেশন শেষ কলব্যাক"""
    user_id = call.from_user.id
    
    if user_id in active_sessions:
        partner_id = end_chat_session(user_id)
        
        if partner_id:
            # উভয়কে নোটিফাই
            bot.edit_message_text("✅ চ্যাট সেশন সফলভাবে শেষ হয়েছে।",
                                call.message.chat.id, call.message.message_id)
            
            try:
                bot.send_message(partner_id, "ℹ️ এডমিন চ্যাট সেশন শেষ করেছেন।")
            except:
                pass
            
            # কীবোর্ড রিফ্রেশ
            bot.send_message(user_id, "🏠 প্রধান মেনু",
                           reply_markup=admin_dashboard_keyboard())
        else:
            bot.answer_callback_query(call.id, "❌ সেশন শেষ করতে সমস্যা হয়েছে।")
    else:
        bot.answer_callback_query(call.id, "ℹ️ আপনার কোনো সক্রিয় সেশন নেই।")

def toggle_group_setting(call, group_id, setting):
    """গ্রুপ সেটিং টগল"""
    group = get_group_info(group_id)
    if not group:
        bot.answer_callback_query(call.id, "❌ গ্রুপ খুঁজে পাওয়া যায়নি।")
        return
    
    # বর্তমান মান
    current_value = group[setting]
    new_value = not current_value
    
    # আপডেট
    update_group_setting(group_id, setting, int(new_value))
    
    # নোটিফাই
    setting_names = {
        "link_filter": "লিংক ফিল্টার",
        "maintenance_mode": "মেইনটেনেন্স মোড",
        "bot_status": "বট স্ট্যাটাস"
    }
    
    status = "সক্রিয়" if new_value else "নিষ্ক্রিয়"
    bot.answer_callback_query(call.id, f"✅ {setting_names[setting]} {status} করা হয়েছে।")
    
    # কীবোর্ড রিফ্রেশ
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                reply_markup=group_settings_keyboard(group_id))

def list_all_groups(call):
    """সকল গ্রুপ তালিকা"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id, title FROM groups ORDER BY title')
        groups = cursor.fetchall()
        conn.close()
    
    if not groups:
        bot.edit_message_text("📭 কোনো গ্রুপ পাওয়া যায়নি।",
                            call.message.chat.id, call.message.message_id)
        return
    
    markup = types.InlineKeyboardMarkup()
    for chat_id, title in groups:
        markup.add(types.InlineKeyboardButton(f"📍 {title[:30]}", 
                                             callback_data=f"manage_group_{chat_id}"))
    
    markup.add(types.InlineKeyboardButton("⬅️ পিছনে", callback_data="group_settings"))
    
    bot.edit_message_text(f"📂 *গ্রুপ তালিকা ({len(groups)})*",
                         call.message.chat.id, call.message.message_id,
                         parse_mode="Markdown", reply_markup=markup)

def leave_group_confirmation(call, group_id):
    """গ্রুপ ছাড়ার কনফার্মেশন"""
    group = get_group_info(group_id)
    if not group:
        bot.answer_callback_query(call.id, "❌ গ্রুপ খুঁজে পাওয়া যায়নি।")
        return
    
    confirm_msg = f"""
🚪 *গ্রুপ ছাড়ার নিশ্চয়তা*

📛 গ্রুপ: {group['title']}
🆔 আইডি: `{group_id}`

⚠️ *সতর্কতা:*
• লিভ মেসেজ পাঠানো হবে
• গ্রুপ থেকে সরানো হবে
• ডাটাবেস থেকে মুছে যাবে

✅ আপনি কি নিশ্চিত?
"""
    
    bot.edit_message_text(confirm_msg, call.message.chat.id, call.message.message_id,
                         parse_mode="Markdown", reply_markup=confirm_keyboard("leave", group_id))

def start_broadcast_to_all_groups(call):
    """সকল গ্রুপে ব্রডকাস্ট শুরু"""
    msg = bot.send_message(call.message.chat.id, "📝 *ব্রডকাস্ট বার্তা লিখুন:*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_broadcast_to_groups)

def start_broadcast_to_all_users(call):
    """সকল ব্যবহারকারীকে ব্রডকাস্ট শুরু"""
    msg = bot.send_message(call.message.chat.id, "📝 *ব্যবহারকারীদের জন্য বার্তা লিখুন:*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_broadcast_to_users)

def handle_confirmation(call, data):
    """কনফার্মেশন হ্যান্ডল"""
    parts = data.split('_')
    action = parts[1]
    target_id = int(parts[2])
    
    if action == "leave":
        # গ্রুপ ছাড়ুন
        try:
            group = get_group_info(target_id)
            leave_msg = group["leave_message"] if group else "Goodbye! 👋"
            
            # লিভ মেসেজ পাঠান
            bot.send_message(target_id, leave_msg)
            
            # গ্রুপ ছাড়ুন
            bot.leave_chat(target_id)
            
            # ডাটাবেস থেকে মুছুন
            with db_lock:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('DELETE FROM groups WHERE chat_id = ?', (target_id,))
                conn.commit()
                conn.close()
            
            bot.edit_message_text(f"✅ গ্রুপ `{target_id}` থেকে সফলভাবে বেরিয়ে এসেছেন।",
                                call.message.chat.id, call.message.message_id,
                                parse_mode="Markdown")
        
        except Exception as e:
            bot.edit_message_text(f"❌ ত্রুটি: {str(e)}",
                                call.message.chat.id, call.message.message_id)

def process_add_admin(message):
    """এডমিন যোগ প্রক্রিয়া"""
    try:
        new_admin_id = int(message.text)
        
        # নিজেকে এডমিন করতে চাইলে
        if new_admin_id == message.from_user.id:
            bot.send_message(message.chat.id, "⚠️ আপনি ইতিমধ্যেই এডমিন!")
            return
        
        # ব্যবহারকারী আছে কিনা চেক
        user_info = get_user_info(new_admin_id)
        if not user_info:
            bot.send_message(message.chat.id, "❌ ব্যবহারকারী খুঁজে পাওয়া যায়নি!")
            return
        
        # এডমিন যোগ
        add_admin(new_admin_id, message.from_user.id)
        
        # নোটিফাই
        success_msg = f"""
✅ *নতুন এডমিন যোগ করা হয়েছে!*

👤 নাম: {user_info['first_name']}
🆔 আইডি: `{new_admin_id}`
📱 ইউজারনেম: @{user_info['username']}
👥 যোগ করেছেন: {message.from_user.first_name}

🔔 ব্যবহারকারীকে নোটিফিকেশন পাঠানো হয়েছে।
"""
        bot.send_message(message.chat.id, success_msg, parse_mode="Markdown")
        
        # নতুন এডমিনকে নোটিফাই
        try:
            bot.send_message(new_admin_id, f"""
🎉 আপনি এখন একজন এডমিন!

🤖 *এডমিন সুবিধা সমূহ:*
• গ্রুপ ম্যানেজমেন্ট
• ব্যবহারকারী ব্যবস্থাপনা
• ব্রডকাস্ট সিস্টেম
• চ্যাট সেশন

📊 ড্যাশবোর্ড দেখতে: /menu
            """)
        except:
            pass
    
    except ValueError:
        bot.send_message(message.chat.id, "❌ অবৈধ আইডি! শুধুমাত্র সংখ্যা দিন।")

def show_admin_list_for_removal(call):
    """এডমিন অপসারণ তালিকা"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT a.user_id, u.first_name, u.username 
                        FROM admins a 
                        LEFT JOIN users u ON a.user_id = u.user_id 
                        WHERE a.user_id != ?''', (SUPER_ADMIN,))
        admins = cursor.fetchall()
        conn.close()
    
    if not admins:
        bot.edit_message_text("📭 কোনো এডমিন পাওয়া যায়নি।",
                            call.message.chat.id, call.message.message_id)
        return
    
    markup = types.InlineKeyboardMarkup()
    for admin_id, name, username in admins:
        display_name = f"{name} (@{username})" if username else name
        markup.add(types.InlineKeyboardButton(f"➖ {display_name[:30]}", 
                                             callback_data=f"remove_admin_{admin_id}"))
    
    markup.add(types.InlineKeyboardButton("⬅️ পিছনে", callback_data="back_to_dashboard"))
    
    bot.edit_message_text(f"🗑 *এডমিন অপসারণ ({len(admins)})*",
                         call.message.chat.id, call.message.message_id,
                         parse_mode="Markdown", reply_markup=markup)

def process_broadcast_to_groups(message):
    """গ্রুপে ব্রডকাস্ট প্রক্রিয়া"""
    user_id = message.from_user.id
    broadcast_text = message.text
    
    if not broadcast_text or len(broadcast_text) < 5:
        bot.send_message(message.chat.id, "❌ বার্তাটি খুব ছোট! অন্তত ৫ অক্ষর লিখুন।")
        return
    
    # গ্রুপ তালিকা পান
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id, title FROM groups WHERE bot_status = 1')
        groups = cursor.fetchall()
        conn.close()
    
    if not groups:
        bot.send_message(message.chat.id, "❌ কোনো সক্রিয় গ্রুপ পাওয়া যায়নি।")
        return
    
    # ব্রডকাস্ট শুরু
    total = len(groups)
    success = 0
    failed = 0
    
    bot.send_message(message.chat.id, f"📤 {total}টি গ্রুপে ব্রডকাস্ট শুরু হচ্ছে...")
    
    for chat_id, title in groups:
        try:
            bot.send_message(chat_id, broadcast_text)
            success += 1
        except:
            failed += 1
    
    # রিপোর্ট
    report_msg = f"""
📊 *ব্রডকাস্ট রিপোর্ট*

✅ সফল: {success}
❌ ব্যর্থ: {failed}
📋 মোট: {total}

⏰ সময়: {datetime.datetime.now().strftime("%H:%M:%S")}
"""
    bot.send_message(message.chat.id, report_msg, parse_mode="Markdown")

def process_broadcast_to_users(message):
    """ব্যবহারকারীদের ব্রডকাস্ট প্রক্রিয়া"""
    user_id = message.from_user.id
    broadcast_text = message.text
    
    if not broadcast_text or len(broadcast_text) < 5:
        bot.send_message(message.chat.id, "❌ বার্তাটি খুব ছোট! অন্তত ৫ অক্ষর লিখুন।")
        return
    
    # ব্যবহারকারী তালিকা পান
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE is_banned = 0')
        users = cursor.fetchall()
        conn.close()
    
    if not users:
        bot.send_message(message.chat.id, "❌ কোনো ব্যবহারকারী পাওয়া যায়নি।")
        return
    
    # ব্রডকাস্ট শুরু
    total = len(users)
    success = 0
    failed = 0
    
    bot.send_message(message.chat.id, f"📤 {total}জন ব্যবহারকারীকে ব্রডকাস্ট শুরু হচ্ছে...")
    
    for user_row in users:
        user_id_target = user_row[0]
        try:
            bot.send_message(user_id_target, broadcast_text)
            success += 1
        except:
            failed += 1
    
    # রিপোর্ট
    report_msg = f"""
📊 *ব্যবহারকারী ব্রডকাস্ট রিপোর্ট*

✅ সফল: {success}
❌ ব্যর্থ: {failed}
📋 মোট: {total}

⏰ সময়: {datetime.datetime.now().strftime("%H:%M:%S")}
"""
    bot.send_message(message.chat.id, report_msg, parse_mode="Markdown")

def get_all_groups():
    """সকল গ্রুপ আইডি পান"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id FROM groups')
        groups = [row[0] for row in cursor.fetchall()]
        conn.close()
    return groups

# ================= START BOT =================
if __name__ == "__main__":
    print("""
    🤖 *Telegram Bot Starting...*
    
    🔧 Features Included:
    1. ✅ User Management System
    2. ✅ Group Management System
    3. ✅ Chat Session System
    4. ✅ Broadcast System
    5. ✅ Admin Panel
    6. ✅ Settings Management
    7. ✅ Statistics & Logs
    8. ✅ Full Control System
    
    🌐 Web Server: http://localhost:10000
    🚀 Bot Status: Running...
    """)
    
    # Flask ওয়েব সার্ভার শুরু করুন
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # বট পোলিং শুরু করুন
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)
