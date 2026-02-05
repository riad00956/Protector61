import os
import sqlite3
import threading
import time
import logging
import json
from datetime import datetime, timedelta
from flask import Flask, request
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import re

# Initialize Flask app
app = Flask(__name__)

# Bot Token এবং Admin ID
BOT_TOKEN = '8000160699:AAHq1VLvd05PFxFVibuErFx4E6Uf7y6F8HE'
bot = telebot.TeleBot(BOT_TOKEN)

# Super Admin ID
SUPER_ADMIN_ID = 7832264582

# Database setup
DB_NAME = 'bot_final.db'

# Store active sessions, cooldowns, এবং message states
active_sessions = {}
user_cooldowns = {}
user_message_states = {}
admin_panel_messages = {}

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================ DATABASE FUNCTIONS ================

def init_db():
    """Initialize database with all required tables"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        is_banned INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        message_count INTEGER DEFAULT 0,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Groups table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS groups (
        group_id INTEGER PRIMARY KEY,
        title TEXT,
        maintenance_mode INTEGER DEFAULT 0,
        link_filter INTEGER DEFAULT 1,
        bot_active INTEGER DEFAULT 1,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Admins table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        admin_id INTEGER PRIMARY KEY,
        username TEXT,
        is_super INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Settings table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        setting_key TEXT UNIQUE,
        setting_value TEXT
    )
    ''')
    
    # Add super admin if not exists
    cursor.execute('INSERT OR IGNORE INTO admins (admin_id, username, is_super) VALUES (?, ?, ?)',
                   (SUPER_ADMIN_ID, 'super_admin', 1))
    
    # Add default settings
    cursor.execute('INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES (?, ?)',
                   ('leave_message', '👋 Goodbye!'))
    
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name=None, last_name=None):
    """Add or update user in database"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_active)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()

def get_user(user_id):
    """Get user details from database"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_all_users(page=0, limit=10):
    """Get paginated registered users"""
    offset = page * limit
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, first_name, message_count, last_active 
        FROM users 
        ORDER BY last_active DESC 
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    users = cursor.fetchall()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total = cursor.fetchone()[0]
    
    conn.close()
    return users, total

def ban_user(user_id):
    """Ban a user"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    """Unban a user"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def is_banned(user_id):
    """Check if user is banned"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1

def add_group(group_id, title):
    """Add or update group in database"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO groups (group_id, title)
        VALUES (?, ?)
    ''', (group_id, title))
    conn.commit()
    conn.close()

def get_all_groups(page=0, limit=10):
    """Get paginated groups"""
    offset = page * limit
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT group_id, title, maintenance_mode, link_filter, bot_active 
        FROM groups 
        ORDER BY added_at DESC 
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    groups = cursor.fetchall()
    
    cursor.execute('SELECT COUNT(*) FROM groups')
    total = cursor.fetchone()[0]
    
    conn.close()
    return groups, total

def update_group_setting(group_id, setting, value):
    """Update group setting"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if setting in ['maintenance_mode', 'link_filter', 'bot_active']:
        cursor.execute(f'UPDATE groups SET {setting} = ? WHERE group_id = ?', (value, group_id))
    conn.commit()
    conn.close()

def get_group_settings(group_id):
    """Get group settings"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT maintenance_mode, link_filter, bot_active FROM groups WHERE group_id = ?', (group_id,))
    settings = cursor.fetchone()
    conn.close()
    return settings

def add_admin(admin_id, username, is_super=0):
    """Add an admin"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO admins (admin_id, username, is_super) VALUES (?, ?, ?)',
                   (admin_id, username, is_super))
    conn.commit()
    conn.close()

def get_admins():
    """Get all admins"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT admin_id, username, is_super FROM admins')
    admins = cursor.fetchall()
    conn.close()
    return admins

def is_admin(user_id):
    """Check if user is admin"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT admin_id FROM admins WHERE admin_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def is_super_admin(user_id):
    """Check if user is super admin"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT admin_id FROM admins WHERE admin_id = ? AND is_super = 1', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_setting(key):
    """Get setting value"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT setting_value FROM settings WHERE setting_key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def update_setting(key, value):
    """Update setting"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (setting_key, setting_value) VALUES (?, ?)',
                   (key, value))
    conn.commit()
    conn.close()

def add_session(user_id, admin_id):
    """Add a new session"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sessions (user_id, admin_id, status)
        VALUES (?, ?, 'active')
    ''', (user_id, admin_id))
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id

def pause_session(session_id):
    """Pause a session"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE sessions SET is_paused = 1 WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()

def resume_session(session_id):
    """Resume a paused session"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE sessions SET is_paused = 0 WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()

def end_session(session_id):
    """End a session"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE sessions SET status = "ended", ended_at = CURRENT_TIMESTAMP WHERE session_id = ?',
                   (session_id,))
    conn.commit()
    conn.close()

# ================ HELPER FUNCTIONS ================

def create_pagination_keyboard(current_page, total_pages, callback_prefix, extra_buttons=None):
    """Create pagination keyboard"""
    keyboard = InlineKeyboardMarkup(row_width=5)
    
    page_buttons = []
    start_page = max(1, current_page - 2)
    end_page = min(total_pages, current_page + 2)
    
    for page in range(start_page, end_page + 1):
        if page == current_page:
            page_buttons.append(InlineKeyboardButton(f"•{page}•", callback_data=f"{callback_prefix}_page_{page}"))
        else:
            page_buttons.append(InlineKeyboardButton(str(page), callback_data=f"{callback_prefix}_page_{page}"))
    
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"{callback_prefix}_page_{current_page-1}"))
    
    nav_buttons.append(InlineKeyboardButton("🏠 Home", callback_data="back_to_admin"))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"{callback_prefix}_page_{current_page+1}"))
    
    if page_buttons:
        keyboard.add(*page_buttons)
    
    if nav_buttons:
        if len(nav_buttons) == 3:
            keyboard.row(*nav_buttons)
        else:
            for btn in nav_buttons:
                keyboard.add(btn)
    
    if extra_buttons:
        for btn in extra_buttons:
            keyboard.add(btn)
    
    return keyboard

def update_admin_panel_message(chat_id, message_id, text, reply_markup=None):
    """Update existing admin panel message"""
    try:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return message_id
    except:
        try:
            bot.delete_message(chat_id, message_id)
        except:
            pass
        new_msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode='HTML')
        return new_msg.message_id

# ================ BOT HANDLERS ================

@bot.message_handler(commands=['start'])
def handle_start(message):
    """Handle /start command"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    if is_banned(user_id):
        bot.send_message(user_id, "❌ You are banned from using this bot.")
        return
    
    add_user(user_id, username, first_name, last_name)
    
    if message.chat.type == 'private':
        if user_id in user_message_states:
            del user_message_states[user_id]
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🙋 Request Chat", callback_data="request_chat"))
        
        welcome_text = """
👋 Welcome to the Support Bot!

Click the button below to request a chat with an admin.

⚠️ Note: You cannot message admins directly. All communication must go through the request system.
        """
        bot.send_message(user_id, welcome_text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'request_chat')
def handle_chat_request(call):
    """Handle chat request from user"""
    user_id = call.from_user.id
    username = call.from_user.username or "No Username"
    first_name = call.from_user.first_name or ""
    
    if user_id in user_cooldowns:
        time_passed = time.time() - user_cooldowns[user_id]
        if time_passed < 600:
            remaining = int(600 - time_passed)
            minutes = remaining // 60
            seconds = remaining % 60
            bot.answer_callback_query(call.id, 
                                     f"⏳ Please wait {minutes}m {seconds}s before requesting again.", 
                                     show_alert=True)
            return
    
    if user_id in active_sessions:
        bot.answer_callback_query(call.id, "You already have an active session!", show_alert=True)
        return
    
    if is_banned(user_id):
        bot.answer_callback_query(call.id, "❌ You are banned from using this bot.", show_alert=True)
        return
    
    user_cooldowns[user_id] = time.time()
    
    admins = get_admins()
    request_text = f"""
📨 New Chat Request:

👤 User: {first_name} (@{username})
🆔 ID: {user_id}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    
    for admin_id, admin_username, _ in admins:
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("✅ Accept", callback_data=f"accept_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
        )
        try:
            bot.send_message(admin_id, request_text, reply_markup=keyboard)
        except:
            pass
    
    bot.answer_callback_query(call.id, "✅ Your request has been sent to admins!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_'))
def handle_accept_request(call):
    """Handle accept request from admin"""
    admin_id = call.from_user.id
    
    if not is_admin(admin_id):
        bot.answer_callback_query(call.id, "❌ You are not authorized!", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    
    session_id = add_session(user_id, admin_id)
    active_sessions[user_id] = {
        'admin_id': admin_id,
        'session_id': session_id,
        'start_time': datetime.now(),
        'is_paused': False
    }
    
    try:
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session_id}"),
            InlineKeyboardButton("⏹️ End", callback_data=f"end_session_{session_id}")
        )
        bot.send_message(user_id, "✅ Your chat request has been accepted! You can now message the admin.", reply_markup=keyboard)
    except:
        pass
    
    user_info = get_user(user_id)
    user_name = user_info[2] if user_info else "User"
    
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session_id}"),
        InlineKeyboardButton("▶️ Resume", callback_data=f"resume_session_{session_id}")
    )
    keyboard.add(InlineKeyboardButton("⏹️ End Session", callback_data=f"end_session_{session_id}"))
    
    bot.answer_callback_query(call.id, f"✅ Chat started with {user_name}")
    
    try:
        bot.edit_message_text(
            f"✅ Chat session started with User ID: {user_id}\n\nUse buttons below to manage session:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_'))
def handle_reject_request(call):
    """Handle reject request from admin"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ You are not authorized!", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    
    try:
        bot.send_message(user_id, "❌ Your chat request has been rejected by the admin.")
    except:
        pass
    
    bot.answer_callback_query(call.id, "❌ Request rejected")
    
    try:
        bot.edit_message_text(f"❌ Chat request rejected for User ID: {user_id}",
                              call.message.chat.id,
                              call.message.message_id)
    except:
        pass

@bot.message_handler(commands=['admin'])
def handle_admin_panel(message):
    """Handle /admin command"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(user_id, "❌ You are not authorized to access the admin panel.")
        return
    
    if user_id in user_message_states:
        del user_message_states[user_id]
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if is_super_admin(user_id):
        keyboard.add(
            InlineKeyboardButton("📥 Inbox Manager", callback_data="inbox_manager_1"),
            InlineKeyboardButton("📂 Group Manager", callback_data="group_manager_1"),
            InlineKeyboardButton("👥 Add Admin", callback_data="add_admin_menu"),
            InlineKeyboardButton("📢 Broadcast", callback_data="broadcast_menu"),
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu"),
            InlineKeyboardButton("📊 Statistics", callback_data="statistics")
        )
    else:
        keyboard.add(
            InlineKeyboardButton("📥 Inbox", callback_data="inbox_manager_1"),
            InlineKeyboardButton("📂 Groups", callback_data="group_manager_1"),
            InlineKeyboardButton("📊 Statistics", callback_data="statistics")
        )
    
    admin_text = f"""
🛠️ <b>Admin Control Panel</b>

👤 Admin: {message.from_user.first_name}
🎯 Type: {'Super Admin' if is_super_admin(user_id) else 'Admin'}
🕒 Time: {datetime.now().strftime('%I:%M %p')}

Choose an option from below:
    """
    
    bot.send_message(user_id, admin_text, reply_markup=keyboard, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('inbox_manager_'))
def show_inbox_manager(call):
    """Show inbox manager with paginated users"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    page = int(call.data.split('_')[2]) if len(call.data.split('_')) > 2 else 1
    users, total = get_all_users(page-1, 10)
    
    if not users:
        text = "📭 <b>Inbox Manager</b>\n\nNo registered users yet."
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)
        return
    
    total_pages = (total + 9) // 10
    
    user_list = ""
    for i, user in enumerate(users, start=1):
        user_id, username, first_name, msg_count, last_active = user
        username_display = f"@{username}" if username else "No Username"
        name_display = first_name or "Unknown"
        
        try:
            last_active_dt = datetime.strptime(last_active, '%Y-%m-%d %H:%M:%S')
            time_diff = datetime.now() - last_active_dt
            if time_diff.days > 0:
                last_seen = f"{time_diff.days}d ago"
            elif time_diff.seconds // 3600 > 0:
                last_seen = f"{time_diff.seconds // 3600}h ago"
            elif time_diff.seconds // 60 > 0:
                last_seen = f"{time_diff.seconds // 60}m ago"
            else:
                last_seen = "Just now"
        except:
            last_seen = "Unknown"
        
        user_list += f"{i}. {name_display} ({username_display})\n"
        user_list += f"   🆔: {user_id} | 📨: {msg_count} | ⏰: {last_seen}\n\n"
    
    text = f"""
📥 <b>Inbox Manager</b>

Total Users: {total}
Page: {page}/{total_pages}

{user_list}
    """
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for i, user in enumerate(users[:5], start=1):
        user_id, username, first_name, _, _ = user
        name_display = first_name or f"User {user_id}"
        if len(name_display) > 15:
            name_display = name_display[:12] + "..."
        keyboard.add(InlineKeyboardButton(f"👤 {name_display}", callback_data=f"manage_user_{user_id}"))
    
    pagination_keyboard = create_pagination_keyboard(page, total_pages, "inbox_manager", 
                                                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin")])
    
    for row in pagination_keyboard.keyboard:
        keyboard.add(*row)
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_user_'))
def manage_user(call):
    """Show user management options"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[2])
    user_info = get_user(user_id)
    
    if not user_info:
        bot.answer_callback_query(call.id, "User not found!", show_alert=True)
        return
    
    _, username, first_name, last_name, is_banned_user, created_at, msg_count, last_active = user_info
    
    username_display = f"@{username}" if username else "No Username"
    name_display = f"{first_name or ''} {last_name or ''}".strip() or "Unknown"
    created_date = created_at.split()[0] if created_at else "Unknown"
    
    has_active_session = user_id in active_sessions
    session_info = ""
    if has_active_session:
        session = active_sessions[user_id]
        session_info = f"\n💬 <b>Active Session:</b> {'⏸️ Paused' if session['is_paused'] else '▶️ Active'}"
    
    text = f"""
👤 <b>User Management</b>

📛 <b>Name:</b> {name_display}
🔗 <b>Username:</b> {username_display}
🆔 <b>ID:</b> <code>{user_id}</code>
📅 <b>Joined:</b> {created_date}
📨 <b>Messages:</b> {msg_count}
🚫 <b>Status:</b> {'Banned' if is_banned_user else 'Active'}
{session_info}

<b>Select an action:</b>
    """
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if has_active_session:
        if active_sessions[user_id]['admin_id'] == call.from_user.id or is_super_admin(call.from_user.id):
            keyboard.add(InlineKeyboardButton("💬 In Session", callback_data=f"view_session_{user_id}"))
        else:
            keyboard.add(InlineKeyboardButton("💬 In Session (Other Admin)", callback_data="no_action"))
    else:
        keyboard.add(InlineKeyboardButton("💬 Start Chat", callback_data=f"admin_chat_{user_id}"))
    
    if is_banned_user:
        keyboard.add(InlineKeyboardButton("🔓 Unban User", callback_data=f"unban_{user_id}"))
    else:
        keyboard.add(InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_{user_id}"))
    
    keyboard.add(InlineKeyboardButton("⬅️ Back to Inbox", callback_data="inbox_manager_1"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_chat_'))
def admin_start_chat(call):
    """Admin manually starts chat with user"""
    admin_id = call.from_user.id
    user_id = int(call.data.split('_')[2])
    
    if user_id in active_sessions:
        bot.answer_callback_query(call.id, "User already has an active session!", show_alert=True)
        return
    
    session_id = add_session(user_id, admin_id)
    active_sessions[user_id] = {
        'admin_id': admin_id,
        'session_id': session_id,
        'start_time': datetime.now(),
        'is_paused': False
    }
    
    try:
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session_id}"),
            InlineKeyboardButton("⏹️ End", callback_data=f"end_session_{session_id}")
        )
        bot.send_message(user_id, "👋 An admin has started a chat with you. You can now message them directly.", reply_markup=keyboard)
    except:
        pass
    
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session_id}"),
        InlineKeyboardButton("▶️ Resume", callback_data=f"resume_session_{session_id}")
    )
    keyboard.add(InlineKeyboardButton("⏹️ End Session", callback_data=f"end_session_{session_id}"))
    keyboard.add(InlineKeyboardButton("⬅️ Back to User", callback_data=f"manage_user_{user_id}"))
    
    text = f"""
💬 <b>Chat Session Started</b>

You are now chatting with:
👤 User ID: {user_id}
📛 Name: {get_user(user_id)[2] or 'Unknown'}

Use buttons below to manage the session.
    """
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)
    bot.answer_callback_query(call.id, "✅ Chat session started!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('ban_'))
def ban_user_handler(call):
    """Ban a user"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    ban_user(user_id)
    
    if user_id in active_sessions:
        session_data = active_sessions.pop(user_id)
        end_session(session_data['session_id'])
    
    bot.answer_callback_query(call.id, "✅ User banned!")
    manage_user(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('unban_'))
def unban_user_handler(call):
    """Unban a user"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    unban_user(user_id)
    bot.answer_callback_query(call.id, "✅ User unbanned!")
    manage_user(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_manager_'))
def show_group_manager(call):
    """Show group manager with pagination"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    page = int(call.data.split('_')[2]) if len(call.data.split('_')) > 2 else 1
    groups, total = get_all_groups(page-1, 8)
    
    if not groups:
        text = "📂 <b>Group Manager</b>\n\nBot is not in any groups yet."
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)
        return
    
    total_pages = (total + 7) // 8
    
    group_list = ""
    for i, group in enumerate(groups, start=1):
        group_id, title, maintenance, link_filter, bot_active = group
        status_icon = "🟢" if bot_active else "🔴"
        mm_icon = "🔧" if maintenance else "⚙️"
        lf_icon = "🔗" if link_filter else "➖"
        
        display_title = title[:25] + "..." if len(title) > 25 else title
        
        group_list += f"{i}. {status_icon} {display_title}\n"
        group_list += f"   {mm_icon} {lf_icon} | ID: {group_id}\n\n"
    
    text = f"""
📂 <b>Group Manager</b>

Total Groups: {total}
Page: {page}/{total_pages}

{group_list}
    """
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for i, group in enumerate(groups[:4], start=1):
        group_id, title, _, _, _ = group
        display_title = title[:15] + "..." if len(title) > 15 else title
        keyboard.add(InlineKeyboardButton(f"📊 {display_title}", callback_data=f"manage_group_{group_id}"))
    
    pagination_keyboard = create_pagination_keyboard(page, total_pages, "group_manager",
                                                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin")])
    
    for row in pagination_keyboard.keyboard:
        keyboard.add(*row)
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_group_'))
def manage_group(call):
    """Show group management options"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    group_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id
    
    group_info = get_group(group_id)
    if not group_info:
        bot.answer_callback_query(call.id, "Group not found!", show_alert=True)
        return
    
    _, title, maintenance_mode, link_filter, bot_active, added_at = group_info
    
    text = f"""
📂 <b>Group Management</b>

🏷️ <b>Title:</b> {title}
🆔 <b>ID:</b> <code>{group_id}</code>
📅 <b>Added:</b> {added_at.split()[0] if added_at else 'Unknown'}

<b>Current Settings:</b>
🔧 Maintenance: {'ON ✅' if maintenance_mode else 'OFF ❌'}
🔗 Link Filter: {'ON ✅' if link_filter else 'OFF ❌'}
🤖 Bot Status: {'ACTIVE 🟢' if bot_active else 'PAUSED 🔴'}

<b>Select action:</b>
    """
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    keyboard.add(
        InlineKeyboardButton(f"🔧 {'Disable' if maintenance_mode else 'Enable'} Maintenance", 
                           callback_data=f"toggle_mm_{group_id}"),
        InlineKeyboardButton(f"🔗 {'Disable' if link_filter else 'Enable'} Link Filter", 
                           callback_data=f"toggle_lf_{group_id}")
    )
    
    keyboard.add(
        InlineKeyboardButton(f"🤖 {'Pause' if bot_active else 'Activate'} Bot", 
                           callback_data=f"toggle_bs_{group_id}"),
        InlineKeyboardButton("📢 Broadcast", callback_data=f"group_broadcast_{group_id}")
    )
    
    if is_super_admin(admin_id):
        keyboard.add(InlineKeyboardButton("🚪 Leave Group", callback_data=f"leave_group_{group_id}"))
    
    keyboard.add(InlineKeyboardButton("⬅️ Back to Groups", callback_data="group_manager_1"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'add_admin_menu')
def add_admin_menu(call):
    """Show add admin menu"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can add admins!", show_alert=True)
        return
    
    text = """
👥 <b>Add New Admin</b>

Send the user ID of the person you want to make admin:
    """
    
    user_message_states[call.from_user.id] = {
        'state': 'awaiting_admin_id',
        'message_id': call.message.message_id
    }
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data="back_to_admin"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'set_leave_msg')
def set_leave_message(call):
    """Prompt admin to set leave message"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can change settings!", show_alert=True)
        return
    
    current_msg = get_setting('leave_message') or "👋 Goodbye!"
    
    text = f"""
✍️ <b>Set Leave Message</b>

Current message: {current_msg}

Please send the new leave message:
    """
    
    user_message_states[call.from_user.id] = {
        'state': 'awaiting_leave_message',
        'message_id': call.message.message_id
    }
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data="settings_menu"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'settings_menu')
def settings_menu(call):
    """Show settings menu"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can access settings!", show_alert=True)
        return
    
    leave_message = get_setting('leave_message') or "👋 Goodbye!"
    
    text = f"""
⚙️ <b>Bot Settings</b>

Current Settings:
✍️ Leave Message: {leave_message[:50]}{'...' if len(leave_message) > 50 else ''}

Select setting to modify:
    """
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✍️ Change Leave Message", callback_data="set_leave_msg"),
        InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin")
    )
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_admin')
def back_to_admin_panel(call):
    """Go back to admin panel"""
    handle_admin_panel(call.message)

@bot.callback_query_handler(func=lambda call: call.data == 'no_action')
def no_action(call):
    """Handle no action button"""
    bot.answer_callback_query(call.id)

# ================ MESSAGE HANDLERS ================

@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document'])
def handle_all_messages(message):
    """Handle all incoming messages"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.chat.type in ['group', 'supergroup']:
        handle_group_message(message)
        return
    
    if message.chat.type == 'private':
        handle_private_message(message)

def handle_group_message(message):
    """Handle messages in groups"""
    group_id = message.chat.id
    user_id = message.from_user.id
    
    if message.chat.type in ['group', 'supergroup']:
        add_group(group_id, message.chat.title)
    
    settings = get_group_settings(group_id)
    if not settings:
        return
    
    maintenance_mode, link_filter, bot_active = settings
    
    if not bot_active:
        return
    
    if maintenance_mode and not is_admin(user_id):
        try:
            bot.delete_message(group_id, message.message_id)
        except:
            pass
        return
    
    if link_filter and not is_admin(user_id):
        text = message.text or message.caption or ""
        if text and ('http://' in text.lower() or 'https://' in text.lower() or 't.me/' in text.lower()):
            try:
                bot.delete_message(group_id, message.message_id)
                
                username = message.from_user.username
                if username:
                    mention = f"@{username}"
                else:
                    mention = message.from_user.first_name
                
                reply_text = f"{mention} হ্যাঁ ভাই🙂, উরাধুরা লিংক দাও, জায়গাটা কি তোমার বাপ কিনা রাখছে? 😒"
                bot.send_message(group_id, reply_text)
                    
            except Exception as e:
                logger.error(f"Error handling link filter: {e}")
            return

def handle_private_message(message):
    """Handle private messages"""
    user_id = message.from_user.id
    
    if user_id in user_message_states:
        state = user_message_states[user_id]
        
        if state['state'] == 'awaiting_admin_id':
            handle_admin_id_input(message, state)
            return
        
        elif state['state'] == 'awaiting_leave_message':
            handle_leave_message_input(message, state)
            return
    
    if is_banned(user_id):
        bot.send_message(user_id, "❌ You are banned from using this bot.")
        return
    
    add_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    
    if user_id in active_sessions:
        session = active_sessions[user_id]
        
        if session['is_paused']:
            bot.send_message(user_id, "⏸️ Chat session is currently paused by admin. Your message was not sent.")
            return
        
        admin_id = session['admin_id']
        
        try:
            if message.content_type == 'text':
                bot.send_message(admin_id, f"👤 User ({user_id}): {message.text}")
            elif message.content_type == 'photo':
                bot.send_photo(admin_id, message.photo[-1].file_id, caption=f"👤 User ({user_id}): {message.caption}")
            elif message.content_type == 'video':
                bot.send_video(admin_id, message.video.file_id, caption=f"👤 User ({user_id}): {message.caption}")
            elif message.content_type == 'document':
                bot.send_document(admin_id, message.document.file_id, caption=f"👤 User ({user_id}): {message.caption}")
        except Exception as e:
            bot.send_message(user_id, "❌ Failed to send message to admin.")
            logger.error(f"Failed to forward message: {e}")
    
    elif is_admin(user_id):
        for uid, session in list(active_sessions.items()):
            if session['admin_id'] == user_id and not session['is_paused']:
                try:
                    if message.content_type == 'text':
                        bot.send_message(uid, f"👮 Admin: {message.text}")
                    elif message.content_type == 'photo':
                        bot.send_photo(uid, message.photo[-1].file_id, caption=f"👮 Admin: {message.caption}")
                    elif message.content_type == 'video':
                        bot.send_video(uid, message.video.file_id, caption=f"👮 Admin: {message.caption}")
                    elif message.content_type == 'document':
                        bot.send_document(uid, message.document.file_id, caption=f"👮 Admin: {message.caption}")
                except Exception as e:
                    bot.send_message(user_id, f"❌ Failed to send message to user {uid}")
                    logger.error(f"Failed to forward message to user: {e}")
                return
        
        handle_admin_panel(message)

def handle_admin_id_input(message, state):
    """Handle admin ID input"""
    try:
        admin_id = int(message.text)
        
        try:
            user_info = bot.get_chat(admin_id)
            username = user_info.username or "No Username"
            first_name = user_info.first_name or ""
        except:
            username = "Unknown"
            first_name = "Unknown"
        
        add_admin(admin_id, username)
        
        success_text = f"""
✅ <b>Admin Added Successfully</b>

👤 New Admin: {first_name} (@{username})
🆔 ID: {admin_id}
        """
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("👥 Back to Admin Panel", callback_data="back_to_admin"))
        
        update_admin_panel_message(message.chat.id, state['message_id'], success_text, keyboard)
        
        try:
            bot.send_message(admin_id, f"""
🎉 <b>You have been added as an admin!</b>

You can now access the admin panel using /admin
            """, parse_mode='HTML')
        except:
            pass
        
        del user_message_states[message.from_user.id]
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid user ID. Please send a numeric ID.")

def handle_leave_message_input(message, state):
    """Handle leave message input"""
    new_message = message.text
    update_setting('leave_message', new_message)
    
    success_text = f"""
✅ <b>Leave Message Updated</b>

New message:
{new_message}
    """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("⬅️ Back to Settings", callback_data="settings_menu"))
    
    update_admin_panel_message(message.chat.id, state['message_id'], success_text, keyboard)
    
    del user_message_states[message.from_user.id]

# ================ FLASK ROUTES FOR RENDER.COM ================

@app.route('/')
def home():
    return "🤖 Telegram Bot is running on Render!"

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint for Telegram"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return 'Bad request', 400

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Set webhook for Telegram bot"""
    webhook_url = f"https://{request.host}/webhook"
    
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=webhook_url)
        return f"✅ Webhook set successfully to: {webhook_url}"
    except Exception as e:
        return f"❌ Error setting webhook: {str(e)}"

# ================ CLEANUP FUNCTIONS ================

def cleanup_sessions():
    """Clean up old sessions periodically"""
    while True:
        time.sleep(3600)
        current_time = datetime.now()
        
        for user_id, session_data in list(active_sessions.items()):
            if (current_time - session_data['start_time']).total_seconds() > 86400:
                end_session(session_data['session_id'])
                active_sessions.pop(user_id, None)
                
                try:
                    bot.send_message(session_data['admin_id'], 
                                   f"⏰ Session with User ID {user_id} automatically ended (24h limit).")
                except:
                    pass
        
        current_timestamp = time.time()
        for user_id, timestamp in list(user_cooldowns.items()):
            if current_timestamp - timestamp > 600:
                user_cooldowns.pop(user_id, None)

# ================ MAIN FUNCTION ================

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_sessions, daemon=True)
    cleanup_thread.start()
    
    # Get Render URL
    render_url = os.environ.get('RENDER_EXTERNAL_URL', '')
    
    if render_url:
        # On Render - use webhook
        logger.info("Running on Render - using webhook mode")
        webhook_url = f"{render_url}/webhook"
        
        # Remove existing webhook and set new one
        bot.remove_webhook()
        time.sleep(1)
        
        try:
            bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook set to: {webhook_url}")
        except Exception as e:
            logger.error(f"Error setting webhook: {e}")
        
        # Run Flask app
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port, debug=False)
    else:
        # Local development - use polling
        logger.info("Running locally - using polling mode")
        
        # Remove webhook if exists
        bot.remove_webhook()
        time.sleep(1)
        
        # Start bot polling in a separate thread
        bot_thread = threading.Thread(target=bot.polling, kwargs={'none_stop': True, 'interval': 0, 'timeout': 20}, daemon=True)
        bot_thread.start()
        
        # Run Flask app for health check
        app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
