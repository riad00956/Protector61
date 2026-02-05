import os
import sqlite3
import threading
import time
import logging
import json
from datetime import datetime
from flask import Flask, request
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Initialize Flask app
app = Flask(__name__)

# Bot Token এবং Admin ID
BOT_TOKEN = '8000160699:AAHq1VLvd05PFxFVibuErFx4E6Uf7y6F8HE'
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# Super Admin ID
SUPER_ADMIN_ID = 7832264582

# Database setup
DB_NAME = 'bot_final.db'

# Storage
active_sessions = {}
user_cooldowns = {}
user_message_states = {}
admin_panel_messages = {}

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================ DATABASE FUNCTIONS (Thread Safe) ================

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
        last_name TEXT, is_banned INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        message_count INTEGER DEFAULT 0, last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Groups table
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
        group_id INTEGER PRIMARY KEY, title TEXT, maintenance_mode INTEGER DEFAULT 0, 
        link_filter INTEGER DEFAULT 1, bot_active INTEGER DEFAULT 1, 
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Admins table
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
        admin_id INTEGER PRIMARY KEY, username TEXT, is_super INTEGER DEFAULT 0, 
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, permissions TEXT DEFAULT '{}')''')
    
    # Admin-Group assignments
    cursor.execute('''CREATE TABLE IF NOT EXISTS admin_groups (
        admin_id INTEGER, group_id INTEGER, can_broadcast INTEGER DEFAULT 0, 
        can_manage_settings INTEGER DEFAULT 0, can_ban_users INTEGER DEFAULT 0, 
        can_view_inbox INTEGER DEFAULT 0, PRIMARY KEY(admin_id, group_id))''')
    
    # Settings table
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
        setting_key TEXT PRIMARY KEY, setting_value TEXT)''')

    # Sessions table
    cursor.execute('''CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
        admin_id INTEGER, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
        ended_at TIMESTAMP, status TEXT DEFAULT 'active', is_paused INTEGER DEFAULT 0)''')

    # Add super admin
    cursor.execute('INSERT OR IGNORE INTO admins (admin_id, username, is_super) VALUES (?, ?, ?)',
                   (SUPER_ADMIN_ID, 'super_admin', 1))
    
    # Default settings
    cursor.execute('INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES (?, ?)',
                   ('leave_message', '👋 Goodbye!'))
    
    conn.commit()
    conn.close()

def add_user(u):
    conn = get_db_connection()
    conn.execute('INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_active) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
                 (u.id, u.username, u.first_name, u.last_name))
    conn.commit()
    conn.close()

def add_group(chat_id, title):
    conn = get_db_connection()
    conn.execute('INSERT OR IGNORE INTO groups (group_id, title) VALUES (?, ?)', (chat_id, title))
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = get_db_connection()
    res = conn.execute('SELECT admin_id FROM admins WHERE admin_id = ?', (user_id,)).fetchone()
    conn.close()
    return res is not None or user_id == SUPER_ADMIN_ID

# ================ AUTO DETECTION LOGIC ================

# বট যখন কোনো গ্রুপে অ্যাড হয়
@bot.my_chat_member_handler()
def handle_bot_added(message):
    new_status = message.new_chat_member.status
    if new_status in ['member', 'administrator']:
        add_group(message.chat.id, message.chat.title)
        logger.info(f"Auto-detected and added Group: {message.chat.title}")

# সব মেসেজের ক্ষেত্রে ডাটা কালেকশন
@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document', 'sticker'])
def monitor_all(message):
    # ইউজার ডাটা আপডেট
    add_user(message.from_user)
    
    # গ্রুপ ডাটা আপডেট (যদি ডাটাবেসে না থাকে)
    if message.chat.type in ['group', 'supergroup']:
        add_group(message.chat.id, message.chat.title)
        handle_group_logic(message)
    else:
        handle_private_logic(message)

# ================ GROUP LOGIC ================

def handle_group_logic(message):
    gid = message.chat.id
    conn = get_db_connection()
    settings = conn.execute('SELECT * FROM groups WHERE group_id = ?', (gid,)).fetchone()
    conn.close()
    
    if not settings or settings['bot_active'] == 0:
        return

    # Maintenance Mode
    if settings['maintenance_mode'] == 1 and not is_admin(message.from_user.id):
        try: bot.delete_message(gid, message.message_id)
        except: pass
        return

    # Link Filter
    if settings['link_filter'] == 1 and not is_admin(message.from_user.id):
        text = message.text or message.caption or ""
        if 'http' in text.lower() or 't.me/' in text.lower():
            try:
                bot.delete_message(gid, message.message_id)
                bot.send_message(gid, f"❌ <b>{message.from_user.first_name}</b>, গ্রুপে লিংক শেয়ার করা নিষেধ!")
            except: pass

# ================ PRIVATE LOGIC & SESSION ================

def handle_private_logic(message):
    uid = message.from_user.id
    
    # Admin State check
    if uid in user_message_states:
        process_admin_states(message)
        return

    if message.text == '/start':
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🙋 Request Support Chat", callback_data="request_chat"))
        bot.send_message(uid, "👋 স্বাগতম! এডমিনের সাথে কথা বলতে নিচের বাটনে ক্লিক করুন।", reply_markup=kb)
        return

    # Forwarding message in active session
    if uid in active_sessions:
        session = active_sessions[uid]
        if not session['is_paused']:
            try:
                bot.send_message(session['admin_id'], f"💬 <b>User ({uid}):</b> {message.text}")
            except: pass

# ================ ADMIN PANEL & CALLBACKS ================

@bot.message_handler(commands=['admin'])
def admin_menu(message):
    if not is_admin(message.from_user.id): return
    
    kb = InlineKeyboardMarkup(row_width=2)
    btns = [
        InlineKeyboardButton("📥 Inbox", callback_data="admin_inbox_0"),
        InlineKeyboardButton("📂 Groups", callback_data="admin_groups_0"),
        InlineKeyboardButton("📢 Broadcast", callback_data="bc_menu"),
        InlineKeyboardButton("📊 Stats", callback_data="bot_stats")
    ]
    kb.add(*btns)
    bot.send_message(message.chat.id, "🛠 <b>Admin Panel</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid = call.from_user.id
    try:
        if call.data == "bc_menu":
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("👥 All Groups", callback_data="bc_all_groups"))
            kb.add(InlineKeyboardButton("👤 All Users", callback_data="bc_all_users"))
            bot.edit_message_text("📢 <b>ব্রডকাস্ট টাইপ সিলেক্ট করুন:</b>", call.message.chat.id, call.message.message_id, reply_markup=kb)
        
        elif call.data.startswith("bc_all_"):
            target = call.data.split('_')[2]
            user_message_states[uid] = {'state': f'waiting_bc_{target}', 'orig_msg': call.message.message_id}
            bot.send_message(call.message.chat.id, f"📝 এখন আপনার ব্রডকাস্ট মেসেজটি লিখুন (এটি সকল {target} এ যাবে):")
            
        elif call.data == "request_chat":
            process_support_request(call)
            
        elif call.data == "bot_stats":
            show_stats(call)

        # ... অন্যান্য কলব্যাক লজিক আগের মতই স্মুথ থাকবে ...
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Callback Error: {e}")

# ================ BROADCAST PROCESSOR ================

def process_admin_states(message):
    uid = message.from_user.id
    state_data = user_message_states[uid]
    state = state_data['state']
    
    conn = get_db_connection()
    
    if state == 'waiting_bc_users':
        users = conn.execute('SELECT user_id FROM users').fetchall()
        count = 0
        for u in users:
            try:
                bot.send_message(u['user_id'], message.text)
                count += 1
                time.sleep(0.05) # Rate limit protection
            except: continue
        bot.reply_to(message, f"✅ ব্রডকাস্টিং সম্পন্ন! {count} জন ইউজার মেসেজ পেয়েছেন।")
        
    elif state == 'waiting_bc_groups':
        groups = conn.execute('SELECT group_id FROM groups').fetchall()
        count = 0
        for g in groups:
            try:
                bot.send_message(g['group_id'], message.text)
                count += 1
                time.sleep(0.05)
            except: continue
        bot.reply_to(message, f"✅ ব্রডকাস্টিং সম্পন্ন! {count} টি গ্রুপে পাঠানো হয়েছে।")

    conn.close()
    del user_message_states[uid]

# ================ HELPERS ================

def process_support_request(call):
    user = call.from_user
    bot.send_message(SUPER_ADMIN_ID, f"📨 <b>New Request!</b>\nUser: {user.first_name}\nID: <code>{user.id}</code>\nUser: @{user.username}")
    bot.answer_callback_query(call.id, "✅ আপনার রিকোয়েস্ট পাঠানো হয়েছে।", show_alert=True)

def show_stats(call):
    conn = get_db_connection()
    u_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    g_count = conn.execute('SELECT COUNT(*) FROM groups').fetchone()[0]
    conn.close()
    
    text = f"📊 <b>Bot Statistics</b>\n\n👤 Total Users: {u_count}\n📂 Total Groups: {g_count}"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back", callback_data="bc_menu")))

# ================ RUNNER ================

@app.route('/')
def index():
    return "Bot is Running 24/7"

def run_bot():
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Polling Error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    init_db()
    
    # Start bot thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # Run Flask on Render's dynamic port
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
