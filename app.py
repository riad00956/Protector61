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
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import re

# Initialize Flask app for 24/7 uptime
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
user_message_states = {}  # Track user's current state/command
admin_panel_messages = {}  # Track admin panel messages for editing
group_broadcast_messages = {}  # Track broadcast messages per group

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
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_broadcast TIMESTAMP
    )
    ''')
    
    # Admins table with permissions
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        admin_id INTEGER PRIMARY KEY,
        username TEXT,
        is_super INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        permissions TEXT DEFAULT '{}'
    )
    ''')
    
    # Admin-Group assignments
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admin_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        group_id INTEGER,
        can_broadcast INTEGER DEFAULT 0,
        can_manage_settings INTEGER DEFAULT 0,
        can_ban_users INTEGER DEFAULT 0,
        can_view_inbox INTEGER DEFAULT 0,
        UNIQUE(admin_id, group_id)
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
    
    # Session history table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        admin_id INTEGER,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        status TEXT DEFAULT 'active',
        is_paused INTEGER DEFAULT 0
    )
    ''')
    
    # Messages table for inbox
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message_type TEXT,
        content TEXT,
        file_id TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_read INTEGER DEFAULT 0
    )
    ''')
    
    # Add super admin if not exists
    cursor.execute('INSERT OR IGNORE INTO admins (admin_id, username, is_super) VALUES (?, ?, ?)',
                   (SUPER_ADMIN_ID, 'super_admin', 1))
    
    # Add default settings if not exists
    cursor.execute('INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES (?, ?)',
                   ('leave_message', '👋 Goodbye!'))
    cursor.execute('INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES (?, ?)',
                   ('link_warning_image', 'AgACAgQAAxkBAAMQZ7hS39l0l1K-zLhQz7VbJ_T0XZUAAtjMMRtdqjFTAU-D1taQvcoBAAMCAAN5AAM2BA'))
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

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

def update_user_activity(user_id):
    """Update user's last activity time"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
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
    
    # Get total count
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

def get_group(group_id):
    """Get group details"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM groups WHERE group_id = ?', (group_id,))
    group = cursor.fetchone()
    conn.close()
    return group

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
    
    # Get total count
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

def add_admin(admin_id, username, permissions='{}', is_super=0):
    """Add an admin with permissions"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO admins (admin_id, username, is_super, permissions)
        VALUES (?, ?, ?, ?)
    ''', (admin_id, username, is_super, permissions))
    conn.commit()
    conn.close()

def get_admin(admin_id):
    """Get admin details"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admins WHERE admin_id = ?', (admin_id,))
    admin = cursor.fetchone()
    conn.close()
    return admin

def get_admins():
    """Get all admins"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT admin_id, username, is_super, permissions FROM admins ORDER BY added_at DESC')
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

def get_admin_permissions(admin_id):
    """Get admin permissions"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT permissions FROM admins WHERE admin_id = ?', (admin_id,))
    result = cursor.fetchone()
    conn.close()
    if result and result[0]:
        return json.loads(result[0])
    return {}

def set_admin_permissions(admin_id, permissions):
    """Set admin permissions"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE admins SET permissions = ? WHERE admin_id = ?', (json.dumps(permissions), admin_id))
    conn.commit()
    conn.close()

def add_admin_to_group(admin_id, group_id, can_broadcast=0, can_manage_settings=0, can_ban_users=0, can_view_inbox=0):
    """Assign admin to group with specific permissions"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO admin_groups (admin_id, group_id, can_broadcast, can_manage_settings, can_ban_users, can_view_inbox)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (admin_id, group_id, can_broadcast, can_manage_settings, can_ban_users, can_view_inbox))
    conn.commit()
    conn.close()

def get_admin_group_permissions(admin_id, group_id):
    """Get admin permissions for specific group"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT can_broadcast, can_manage_settings, can_ban_users, can_view_inbox 
        FROM admin_groups 
        WHERE admin_id = ? AND group_id = ?
    ''', (admin_id, group_id))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {
            'can_broadcast': bool(result[0]),
            'can_manage_settings': bool(result[1]),
            'can_ban_users': bool(result[2]),
            'can_view_inbox': bool(result[3])
        }
    return None

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
    cursor.execute('INSERT OR REPLACE INTO settings (setting_key, setting_value) VALUES (?, ?)', (key, value))
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
    cursor.execute('UPDATE sessions SET status = "ended", ended_at = CURRENT_TIMESTAMP WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()

def add_message_to_inbox(user_id, message_type, content, file_id=None):
    """Add message to user's inbox"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO messages (user_id, message_type, content, file_id)
        VALUES (?, ?, ?, ?)
    ''', (user_id, message_type, content, file_id))
    conn.commit()
    conn.close()

def get_user_messages(user_id, limit=50):
    """Get user's messages"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT message_type, content, file_id, sent_at 
        FROM messages 
        WHERE user_id = ? 
        ORDER BY sent_at DESC 
        LIMIT ?
    ''', (user_id, limit))
    messages = cursor.fetchall()
    conn.close()
    return messages

def increment_message_count(user_id):
    """Increment user's message count"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET message_count = message_count + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# ================ HELPER FUNCTIONS ================

def create_pagination_keyboard(current_page, total_pages, callback_prefix, extra_buttons=None):
    """Create pagination keyboard with previous/next buttons"""
    keyboard = InlineKeyboardMarkup(row_width=5)
    
    # Add page numbers
    page_buttons = []
    start_page = max(1, current_page - 2)
    end_page = min(total_pages, current_page + 2)
    
    for page in range(start_page, end_page + 1):
        if page == current_page:
            page_buttons.append(InlineKeyboardButton(f"•{page}•", callback_data=f"{callback_prefix}_page_{page}"))
        else:
            page_buttons.append(InlineKeyboardButton(str(page), callback_data=f"{callback_prefix}_page_{page}"))
    
    # Add navigation buttons
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"{callback_prefix}_page_{current_page-1}"))
    
    nav_buttons.append(InlineKeyboardButton("🏠 Home", callback_data="back_to_admin"))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"{callback_prefix}_page_{current_page+1}"))
    
    # Add buttons to keyboard
    if page_buttons:
        keyboard.add(*page_buttons)
    
    if nav_buttons:
        if len(nav_buttons) == 3:
            keyboard.row(*nav_buttons)
        else:
            for btn in nav_buttons:
                keyboard.add(btn)
    
    # Add extra buttons if provided
    if extra_buttons:
        for btn in extra_buttons:
            keyboard.add(btn)
    
    return keyboard

def delete_previous_messages(chat_id, message_id):
    """Delete previous bot messages to keep chat clean"""
    if chat_id in admin_panel_messages:
        for msg_id in admin_panel_messages[chat_id]:
            try:
                if msg_id != message_id:
                    bot.delete_message(chat_id, msg_id)
            except:
                pass
        admin_panel_messages[chat_id] = [message_id]
    else:
        admin_panel_messages[chat_id] = [message_id]

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
        if chat_id in admin_panel_messages:
            admin_panel_messages[chat_id].append(new_msg.message_id)
        else:
            admin_panel_messages[chat_id] = [new_msg.message_id]
        return new_msg.message_id

def can_admin_access_group(admin_id, group_id, permission_type=None):
    """Check if admin has access to group"""
    if is_super_admin(admin_id):
        return True
    
    permissions = get_admin_group_permissions(admin_id, group_id)
    if not permissions:
        return False
    
    if permission_type:
        return permissions.get(permission_type, False)
    
    return True

def get_admin_accessible_groups(admin_id):
    """Get groups that admin can access"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if is_super_admin(admin_id):
        cursor.execute('SELECT group_id, title FROM groups ORDER BY title')
    else:
        cursor.execute('''
            SELECT g.group_id, g.title 
            FROM groups g
            JOIN admin_groups ag ON g.group_id = ag.group_id
            WHERE ag.admin_id = ?
            ORDER BY g.title
        ''', (admin_id,))
    
    groups = cursor.fetchall()
    conn.close()
    return groups

# ================ BOT HANDLERS ================

@bot.message_handler(commands=['start'])
def handle_start(message):
    """Handle /start command"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Check if user is banned
    if is_banned(user_id):
        bot.send_message(user_id, "❌ You are banned from using this bot.")
        return
    
    # Register user in database
    add_user(user_id, username, first_name, last_name)
    
    # Check if in private chat
    if message.chat.type == 'private':
        # Clear any previous state
        if user_id in user_message_states:
            del user_message_states[user_id]
        
        # Create request chat button
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
    
    # Check cooldown
    if user_id in user_cooldowns:
        time_passed = time.time() - user_cooldowns[user_id]
        if time_passed < 600:  # 10 minutes in seconds
            remaining = int(600 - time_passed)
            minutes = remaining // 60
            seconds = remaining % 60
            bot.answer_callback_query(call.id, 
                                     f"⏳ Please wait {minutes}m {seconds}s before requesting again.", 
                                     show_alert=True)
            return
    
    # Check if already in active session
    if user_id in active_sessions:
        bot.answer_callback_query(call.id, "You already have an active session!", show_alert=True)
        return
    
    # Check if banned
    if is_banned(user_id):
        bot.answer_callback_query(call.id, "❌ You are banned from using this bot.", show_alert=True)
        return
    
    # Set cooldown
    user_cooldowns[user_id] = time.time()
    
    # Send request to admins with access to inbox
    admins = get_admins()
    request_text = f"""
📨 New Chat Request:

👤 User: {first_name} (@{username})
🆔 ID: {user_id}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    
    for admin_id, admin_username, _, _ in admins:
        # Check if admin has inbox access to any group
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM admin_groups WHERE admin_id = ? AND can_view_inbox = 1', (admin_id,))
        has_inbox_access = cursor.fetchone()[0] > 0
        conn.close()
        
        if has_inbox_access or is_super_admin(admin_id):
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
    
    # Start session
    session_id = add_session(user_id, admin_id)
    active_sessions[user_id] = {
        'admin_id': admin_id,
        'session_id': session_id,
        'start_time': datetime.now(),
        'is_paused': False
    }
    
    # Notify user
    try:
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session_id}"),
            InlineKeyboardButton("⏹️ End", callback_data=f"end_session_{session_id}")
        )
        bot.send_message(user_id, "✅ Your chat request has been accepted! You can now message the admin.", reply_markup=keyboard)
    except:
        pass
    
    # Notify admin
    user_info = get_user(user_id)
    user_name = user_info[2] if user_info else "User"
    
    # Create session management keyboard for admin
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session_id}"),
        InlineKeyboardButton("▶️ Resume", callback_data=f"resume_session_{session_id}")
    )
    keyboard.add(InlineKeyboardButton("⏹️ End Session", callback_data=f"end_session_{session_id}"))
    
    bot.answer_callback_query(call.id, f"✅ Chat started with {user_name}")
    
    # Edit admin message to show session started
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
    
    # Notify user
    try:
        bot.send_message(user_id, "❌ Your chat request has been rejected by the admin.")
    except:
        pass
    
    # Notify admin
    bot.answer_callback_query(call.id, "❌ Request rejected")
    
    # Edit admin message
    try:
        bot.edit_message_text(f"❌ Chat request rejected for User ID: {user_id}",
                              call.message.chat.id,
                              call.message.message_id)
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('pause_session_'))
def handle_pause_session(call):
    """Pause an active session"""
    session_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id
    
    # Find user_id for this session
    user_id = None
    for uid, session in active_sessions.items():
        if session['session_id'] == session_id:
            user_id = uid
            break
    
    if not user_id:
        bot.answer_callback_query(call.id, "Session not found!", show_alert=True)
        return
    
    # Check if admin owns this session
    if active_sessions[user_id]['admin_id'] != admin_id and not is_super_admin(admin_id):
        bot.answer_callback_query(call.id, "❌ You don't own this session!", show_alert=True)
        return
    
    # Pause session
    pause_session(session_id)
    active_sessions[user_id]['is_paused'] = True
    
    # Update admin message
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("▶️ Resume", callback_data=f"resume_session_{session_id}"),
        InlineKeyboardButton("⏹️ End", callback_data=f"end_session_{session_id}")
    )
    
    try:
        bot.edit_message_text(
            f"⏸️ Session PAUSED with User ID: {user_id}\n\nMessages will not be forwarded until resumed.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )
    except:
        pass
    
    # Notify user
    try:
        bot.send_message(user_id, "⏸️ Chat session has been paused by admin. Your messages will not be forwarded until resumed.")
    except:
        pass
    
    bot.answer_callback_query(call.id, "✅ Session paused")

@bot.callback_query_handler(func=lambda call: call.data.startswith('resume_session_'))
def handle_resume_session(call):
    """Resume a paused session"""
    session_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id
    
    # Find user_id for this session
    user_id = None
    for uid, session in active_sessions.items():
        if session['session_id'] == session_id:
            user_id = uid
            break
    
    if not user_id:
        bot.answer_callback_query(call.id, "Session not found!", show_alert=True)
        return
    
    # Check if admin owns this session
    if active_sessions[user_id]['admin_id'] != admin_id and not is_super_admin(admin_id):
        bot.answer_callback_query(call.id, "❌ You don't own this session!", show_alert=True)
        return
    
    # Resume session
    resume_session(session_id)
    active_sessions[user_id]['is_paused'] = False
    
    # Update admin message
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session_id}"),
        InlineKeyboardButton("⏹️ End", callback_data=f"end_session_{session_id}")
    )
    
    try:
        bot.edit_message_text(
            f"▶️ Session RESUMED with User ID: {user_id}\n\nMessages will now be forwarded again.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )
    except:
        pass
    
    # Notify user
    try:
        bot.send_message(user_id, "▶️ Chat session has been resumed by admin. Your messages will now be forwarded.")
    except:
        pass
    
    bot.answer_callback_query(call.id, "✅ Session resumed")

@bot.callback_query_handler(func=lambda call: call.data.startswith('end_session_'))
def handle_end_session(call):
    """End a session"""
    session_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id
    
    # Find user_id for this session
    user_id = None
    for uid, session in list(active_sessions.items()):
        if session['session_id'] == session_id:
            user_id = uid
            break
    
    if not user_id:
        bot.answer_callback_query(call.id, "Session not found!", show_alert=True)
        return
    
    # Check if admin owns this session
    if active_sessions[user_id]['admin_id'] != admin_id and not is_super_admin(admin_id):
        bot.answer_callback_query(call.id, "❌ You don't own this session!", show_alert=True)
        return
    
    # End session
    end_session(session_id)
    if user_id in active_sessions:
        del active_sessions[user_id]
    
    # Update admin message
    try:
        bot.edit_message_text(
            f"⏹️ Session ENDED with User ID: {user_id}",
            call.message.chat.id,
            call.message.message_id
        )
    except:
        pass
    
    # Notify user
    try:
        bot.send_message(user_id, "⏹️ Chat session has been ended by admin.")
    except:
        pass
    
    bot.answer_callback_query(call.id, "✅ Session ended")

@bot.message_handler(commands=['admin'])
def handle_admin_panel(message):
    """Handle /admin command"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(user_id, "❌ You are not authorized to access the admin panel.")
        return
    
    # Clear any previous state
    if user_id in user_message_states:
        del user_message_states[user_id]
    
    # Delete previous bot messages
    delete_previous_messages(message.chat.id, None)
    
    # Create admin panel keyboard
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if is_super_admin(user_id):
        keyboard.add(
            InlineKeyboardButton("📥 Inbox Manager", callback_data="inbox_manager_1"),
            InlineKeyboardButton("📂 Group Manager", callback_data="group_manager_1"),
            InlineKeyboardButton("👥 Admin Manager", callback_data="admin_manager_1"),
            InlineKeyboardButton("📢 Broadcast", callback_data="broadcast_menu"),
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu"),
            InlineKeyboardButton("📊 Statistics", callback_data="statistics")
        )
    else:
        # Limited access for regular admins
        keyboard.add(
            InlineKeyboardButton("📥 Inbox", callback_data="inbox_manager_1"),
            InlineKeyboardButton("📂 My Groups", callback_data="my_groups_1"),
            InlineKeyboardButton("📊 Statistics", callback_data="statistics")
        )
    
    admin_text = f"""
🛠️ <b>Admin Control Panel</b>

👤 Admin: {message.from_user.first_name}
🎯 Type: {'Super Admin' if is_super_admin(user_id) else 'Admin'}
🕒 Time: {datetime.now().strftime('%I:%M %p')}

Choose an option from below:
    """
    
    msg = bot.send_message(user_id, admin_text, reply_markup=keyboard, parse_mode='HTML')
    delete_previous_messages(message.chat.id, msg.message_id)

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
    
    # Calculate total pages
    total_pages = (total + 9) // 10
    
    # Create user list
    user_list = ""
    for i, user in enumerate(users, start=1):
        user_id, username, first_name, msg_count, last_active = user
        username_display = f"@{username}" if username else "No Username"
        name_display = first_name or "Unknown"
        
        # Format last active time
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
        user_list += f"   🆔: {user_id} | 📨: {msg_count} | ⏰: {last_seen}\n"
        user_list += f"   [Manage](tg://user?id={user_id})\n\n"
    
    text = f"""
📥 <b>Inbox Manager</b>

Total Users: {total}
Page: {page}/{total_pages}

{user_list}
    """
    
    # Create keyboard with pagination and user buttons
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    # Add user management buttons (first 5 users only for space)
    for i, user in enumerate(users[:5], start=1):
        user_id, username, first_name, _, _ = user
        name_display = first_name or f"User {user_id}"
        if len(name_display) > 15:
            name_display = name_display[:12] + "..."
        keyboard.add(InlineKeyboardButton(f"👤 {name_display}", callback_data=f"manage_user_{user_id}"))
    
    # Add pagination
    pagination_keyboard = create_pagination_keyboard(page, total_pages, "inbox_manager", 
                                                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin")])
    
    # Combine keyboards
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
    
    # Format user info
    username_display = f"@{username}" if username else "No Username"
    name_display = f"{first_name or ''} {last_name or ''}".strip() or "Unknown"
    created_date = created_at.split()[0] if created_at else "Unknown"
    
    # Check if user has active session
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
    
    # Message buttons
    if has_active_session:
        if active_sessions[user_id]['admin_id'] == call.from_user.id or is_super_admin(call.from_user.id):
            keyboard.add(InlineKeyboardButton("💬 In Session", callback_data=f"view_session_{user_id}"))
        else:
            keyboard.add(InlineKeyboardButton("💬 In Session (Other Admin)", callback_data="no_action"))
    else:
        keyboard.add(InlineKeyboardButton("💬 Start Chat", callback_data=f"admin_chat_{user_id}"))
    
    # Ban/Unban buttons
    if is_banned_user:
        keyboard.add(InlineKeyboardButton("🔓 Unban User", callback_data=f"unban_{user_id}"))
    else:
        keyboard.add(InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_{user_id}"))
    
    # View messages button
    keyboard.add(InlineKeyboardButton("📨 View Messages", callback_data=f"view_messages_{user_id}"))
    
    # Back button
    keyboard.add(InlineKeyboardButton("⬅️ Back to Inbox", callback_data="inbox_manager_1"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('view_messages_'))
def view_user_messages(call):
    """View user's messages"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[2])
    user_info = get_user(user_id)
    
    if not user_info:
        bot.answer_callback_query(call.id, "User not found!", show_alert=True)
        return
    
    messages = get_user_messages(user_id, 20)
    
    if not messages:
        text = f"""
📨 <b>Message History</b>

User: {user_info[2] or 'Unknown'}
Total Messages: {user_info[6] or 0}

No messages found in history.
        """
    else:
        message_history = ""
        for i, msg in enumerate(reversed(messages), start=1):
            msg_type, content, file_id, sent_at = msg
            time_str = sent_at.split()[1][:5] if ' ' in str(sent_at) else str(sent_at)[11:16]
            
            if msg_type == 'text':
                preview = content[:50] + "..." if len(content) > 50 else content
                message_history += f"{i}. 📝 {preview} [{time_str}]\n"
            elif msg_type == 'photo':
                message_history += f"{i}. 📸 Photo [{time_str}]\n"
            elif msg_type == 'video':
                message_history += f"{i}. 🎥 Video [{time_str}]\n"
            elif msg_type == 'document':
                message_history += f"{i}. 📄 Document [{time_str}]\n"
    
        text = f"""
📨 <b>Message History</b>

User: {user_info[2] or 'Unknown'}
Total Messages: {user_info[6] or 0}

<b>Recent Messages:</b>
{message_history}
        """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("⬅️ Back to User", callback_data=f"manage_user_{user_id}"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_chat_'))
def admin_start_chat(call):
    """Admin manually starts chat with user"""
    admin_id = call.from_user.id
    user_id = int(call.data.split('_')[2])
    
    # Check if user is already in session
    if user_id in active_sessions:
        bot.answer_callback_query(call.id, "User already has an active session!", show_alert=True)
        return
    
    # Start session
    session_id = add_session(user_id, admin_id)
    active_sessions[user_id] = {
        'admin_id': admin_id,
        'session_id': session_id,
        'start_time': datetime.now(),
        'is_paused': False
    }
    
    # Notify user
    try:
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session_id}"),
            InlineKeyboardButton("⏹️ End", callback_data=f"end_session_{session_id}")
        )
        bot.send_message(user_id, "👋 An admin has started a chat with you. You can now message them directly.", reply_markup=keyboard)
    except:
        pass
    
    # Update admin message with session controls
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('view_session_'))
def view_active_session(call):
    """View active session details"""
    user_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id
    
    if user_id not in active_sessions:
        bot.answer_callback_query(call.id, "No active session found!", show_alert=True)
        return
    
    session = active_sessions[user_id]
    
    # Check if admin has access to this session
    if session['admin_id'] != admin_id and not is_super_admin(admin_id):
        bot.answer_callback_query(call.id, "❌ You don't have access to this session!", show_alert=True)
        return
    
    user_info = get_user(user_id)
    user_name = user_info[2] if user_info else "Unknown"
    
    text = f"""
💬 <b>Active Session</b>

👤 User: {user_name}
🆔 ID: {user_id}
⏰ Started: {session['start_time'].strftime('%I:%M %p')}
🔄 Status: {'⏸️ PAUSED' if session['is_paused'] else '▶️ ACTIVE'}

<b>Session Controls:</b>
    """
    
    keyboard = InlineKeyboardMarkup()
    if session['is_paused']:
        keyboard.row(
            InlineKeyboardButton("▶️ Resume", callback_data=f"resume_session_{session['session_id']}"),
            InlineKeyboardButton("⏹️ End", callback_data=f"end_session_{session['session_id']}")
        )
    else:
        keyboard.row(
            InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_session_{session['session_id']}"),
            InlineKeyboardButton("⏹️ End", callback_data=f"end_session_{session['session_id']}")
        )
    keyboard.add(InlineKeyboardButton("⬅️ Back to User", callback_data=f"manage_user_{user_id}"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('ban_'))
def ban_user_handler(call):
    """Ban a user"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    ban_user(user_id)
    
    # End active session if exists
    if user_id in active_sessions:
        session_data = active_sessions.pop(user_id)
        end_session(session_data['session_id'])
    
    bot.answer_callback_query(call.id, "✅ User banned!")
    
    # Update the management message
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
    
    # Calculate total pages
    total_pages = (total + 7) // 8
    
    # Create group list
    group_list = ""
    for i, group in enumerate(groups, start=1):
        group_id, title, maintenance, link_filter, bot_active = group
        status_icon = "🟢" if bot_active else "🔴"
        mm_icon = "🔧" if maintenance else "⚙️"
        lf_icon = "🔗" if link_filter else "➖"
        
        # Truncate long titles
        display_title = title[:25] + "..." if len(title) > 25 else title
        
        group_list += f"{i}. {status_icon} {display_title}\n"
        group_list += f"   {mm_icon} {lf_icon} | ID: {group_id}\n\n"
    
    text = f"""
📂 <b>Group Manager</b>

Total Groups: {total}
Page: {page}/{total_pages}

{group_list}
    """
    
    # Create keyboard with group buttons
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    # Add group buttons (first 4 groups only for space)
    for i, group in enumerate(groups[:4], start=1):
        group_id, title, _, _, _ = group
        display_title = title[:15] + "..." if len(title) > 15 else title
        keyboard.add(InlineKeyboardButton(f"📊 {display_title}", callback_data=f"manage_group_{group_id}"))
    
    # Add pagination
    pagination_keyboard = create_pagination_keyboard(page, total_pages, "group_manager",
                                                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin")])
    
    # Combine keyboards
    for row in pagination_keyboard.keyboard:
        keyboard.add(*row)
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'my_groups_1')
def show_my_groups(call):
    """Show groups that admin has access to"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    admin_id = call.from_user.id
    groups = get_admin_accessible_groups(admin_id)
    
    if not groups:
        text = "📂 <b>My Groups</b>\n\nYou don't have access to any groups yet."
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)
        return
    
    # Create group list
    group_list = ""
    for i, (group_id, title) in enumerate(groups, start=1):
        group_info = get_group(group_id)
        if group_info:
            _, _, maintenance, link_filter, bot_active, _, _ = group_info
            status_icon = "🟢" if bot_active else "🔴"
            mm_icon = "🔧" if maintenance else "⚙️"
            lf_icon = "🔗" if link_filter else "➖"
        else:
            status_icon = "❓"
            mm_icon = "❓"
            lf_icon = "❓"
        
        # Truncate long titles
        display_title = title[:25] + "..." if len(title) > 25 else title
        
        group_list += f"{i}. {status_icon} {display_title}\n"
        group_list += f"   {mm_icon} {lf_icon} | ID: {group_id}\n\n"
    
    text = f"""
📂 <b>My Groups</b>

Total Groups: {len(groups)}

{group_list}
    """
    
    # Create keyboard with group buttons
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for i, (group_id, title) in enumerate(groups[:6], start=1):
        display_title = title[:15] + "..." if len(title) > 15 else title
        keyboard.add(InlineKeyboardButton(f"📊 {display_title}", callback_data=f"manage_group_{group_id}"))
    
    keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_group_'))
def manage_group(call):
    """Show group management options"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    group_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id
    
    # Check if admin has access to this group
    if not can_admin_access_group(admin_id, group_id):
        bot.answer_callback_query(call.id, "❌ You don't have access to this group!", show_alert=True)
        return
    
    group_info = get_group(group_id)
    if not group_info:
        bot.answer_callback_query(call.id, "Group not found!", show_alert=True)
        return
    
    _, title, maintenance_mode, link_filter, bot_active, added_at, _ = group_info
    
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
    
    # Toggle buttons
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
    
    # Leave button (only for super admin or if admin has manage settings permission)
    if is_super_admin(admin_id) or can_admin_access_group(admin_id, group_id, 'can_manage_settings'):
        keyboard.add(InlineKeyboardButton("🚪 Leave Group", callback_data=f"leave_group_{group_id}"))
    
    # Admin assignments button (only for super admin)
    if is_super_admin(admin_id):
        keyboard.add(InlineKeyboardButton("👥 Assign Admin", callback_data=f"assign_admin_{group_id}"))
    
    # Back button
    keyboard.add(InlineKeyboardButton("⬅️ Back to Groups", callback_data="group_manager_1"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_mm_'))
def toggle_maintenance_mode(call):
    """Toggle maintenance mode"""
    admin_id = call.from_user.id
    group_id = int(call.data.split('_')[2])
    
    # Check permissions
    if not can_admin_access_group(admin_id, group_id, 'can_manage_settings'):
        bot.answer_callback_query(call.id, "❌ You don't have permission to manage settings!", show_alert=True)
        return
    
    settings = get_group_settings(group_id)
    
    if settings:
        current_value = settings[0]
        new_value = 0 if current_value else 1
        update_group_setting(group_id, 'maintenance_mode', new_value)
        
        status = "ENABLED" if new_value else "DISABLED"
        bot.answer_callback_query(call.id, f"Maintenance Mode {status}")
        manage_group(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_lf_'))
def toggle_link_filter(call):
    """Toggle link filter"""
    admin_id = call.from_user.id
    group_id = int(call.data.split('_')[2])
    
    # Check permissions
    if not can_admin_access_group(admin_id, group_id, 'can_manage_settings'):
        bot.answer_callback_query(call.id, "❌ You don't have permission to manage settings!", show_alert=True)
        return
    
    settings = get_group_settings(group_id)
    
    if settings:
        current_value = settings[1]
        new_value = 0 if current_value else 1
        update_group_setting(group_id, 'link_filter', new_value)
        
        status = "ENABLED" if new_value else "DISABLED"
        bot.answer_callback_query(call.id, f"Link Filter {status}")
        manage_group(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_bs_'))
def toggle_bot_status(call):
    """Toggle bot status"""
    admin_id = call.from_user.id
    group_id = int(call.data.split('_')[2])
    
    # Check permissions
    if not can_admin_access_group(admin_id, group_id, 'can_manage_settings'):
        bot.answer_callback_query(call.id, "❌ You don't have permission to manage settings!", show_alert=True)
        return
    
    settings = get_group_settings(group_id)
    
    if settings:
        current_value = settings[2]
        new_value = 0 if current_value else 1
        update_group_setting(group_id, 'bot_active', new_value)
        
        status = "ACTIVATED" if new_value else "PAUSED"
        bot.answer_callback_query(call.id, f"Bot {status}")
        manage_group(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_broadcast_'))
def group_broadcast_menu(call):
    """Show broadcast menu for specific group"""
    admin_id = call.from_user.id
    group_id = int(call.data.split('_')[2])
    
    # Check permissions
    if not can_admin_access_group(admin_id, group_id, 'can_broadcast'):
        bot.answer_callback_query(call.id, "❌ You don't have permission to broadcast!", show_alert=True)
        return
    
    group_info = get_group(group_id)
    group_name = group_info[1] if group_info else f"Group {group_id}"
    
    text = f"""
📢 <b>Group Broadcast</b>

🏷️ Group: {group_name}
🆔 ID: {group_id}

Send the message you want to broadcast to this group:
    """
    
    # Set state for next message
    user_message_states[admin_id] = {
        'state': 'awaiting_group_broadcast',
        'group_id': group_id,
        'message_id': call.message.message_id
    }
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data=f"manage_group_{group_id}"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'broadcast_menu')
def global_broadcast_menu(call):
    """Show global broadcast menu"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can use this!", show_alert=True)
        return
    
    text = """
📢 <b>Global Broadcast</b>

Select broadcast type:

1. <b>All Groups</b> - Send to every group
2. <b>Selected Groups</b> - Choose specific groups
3. <b>All Users</b> - Send to all registered users
    """
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📂 All Groups", callback_data="broadcast_all_groups"),
        InlineKeyboardButton("🎯 Selected Groups", callback_data="broadcast_select_groups"),
        InlineKeyboardButton("👤 All Users", callback_data="broadcast_all_users"),
        InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin")
    )
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('leave_group_'))
def leave_group_handler(call):
    """Handle leaving group"""
    admin_id = call.from_user.id
    group_id = int(call.data.split('_')[2])
    
    # Check permissions
    if not (is_super_admin(admin_id) or can_admin_access_group(admin_id, group_id, 'can_manage_settings')):
        bot.answer_callback_query(call.id, "❌ You don't have permission to leave group!", show_alert=True)
        return
    
    # Get leave message from settings
    leave_message = get_setting('leave_message') or "👋 Goodbye!"
    
    # Send leave message to group
    try:
        bot.send_message(group_id, leave_message)
        time.sleep(1)  # Wait a bit before leaving
        bot.leave_chat(group_id)
        
        # Remove group from database
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM groups WHERE group_id = ?', (group_id,))
        cursor.execute('DELETE FROM admin_groups WHERE group_id = ?', (group_id,))
        conn.commit()
        conn.close()
        
        bot.answer_callback_query(call.id, "✅ Left group successfully!")
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Failed to leave group: {str(e)}", show_alert=True)
    
    # Go back to group manager
    show_group_manager(call)

@bot.callback_query_handler(func=lambda call: call.data == 'admin_manager_1')
def show_admin_manager(call):
    """Show admin management panel"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can manage admins!", show_alert=True)
        return
    
    admins = get_admins()
    
    admin_list = ""
    for i, admin in enumerate(admins, start=1):
        admin_id, username, is_super, permissions = admin
        username_display = f"@{username}" if username else "No Username"
        admin_type = "Super Admin" if is_super else "Admin"
        
        # Parse permissions
        perms = json.loads(permissions) if permissions else {}
        perm_count = len(perms)
        
        admin_list += f"{i}. {username_display}\n"
        admin_list += f"   🆔: {admin_id} | 👑: {admin_type} | ⚙️: {perm_count} perms\n\n"
    
    text = f"""
👥 <b>Admin Manager</b>

Total Admins: {len(admins)}

{admin_list}
    """
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("➕ Add Admin", callback_data="add_admin_menu"),
        InlineKeyboardButton("🗑️ Remove Admin", callback_data="remove_admin_menu"),
        InlineKeyboardButton("⚙️ Edit Permissions", callback_data="edit_admin_perms_menu"),
        InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin")
    )
    
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

You can get user ID by:
1. Forwarding their message to @userinfobot
2. Or send their username starting with @
    """
    
    # Set state for next message
    user_message_states[call.from_user.id] = {
        'state': 'awaiting_admin_id',
        'message_id': call.message.message_id
    }
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data="admin_manager_1"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('assign_admin_'))
def assign_admin_to_group(call):
    """Assign admin to group with permissions"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can assign admins!", show_alert=True)
        return
    
    group_id = int(call.data.split('_')[2])
    group_info = get_group(group_id)
    group_name = group_info[1] if group_info else f"Group {group_id}"
    
    text = f"""
👥 <b>Assign Admin to Group</b>

🏷️ Group: {group_name}
🆔 ID: {group_id}

Send the admin's user ID to assign them to this group:
    """
    
    # Set state for next message
    user_message_states[call.from_user.id] = {
        'state': 'awaiting_admin_for_group',
        'group_id': group_id,
        'message_id': call.message.message_id
    }
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data=f"manage_group_{group_id}"))
    
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
        InlineKeyboardButton("🖼️ Change Link Warning Image", callback_data="set_warning_image"),
        InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin")
    )
    
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
    
    # Set state for next message
    user_message_states[call.from_user.id] = {
        'state': 'awaiting_leave_message',
        'message_id': call.message.message_id
    }
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data="settings_menu"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'set_warning_image')
def set_warning_image(call):
    """Prompt admin to set warning image"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can change settings!", show_alert=True)
        return
    
    text = """
🖼️ <b>Set Link Warning Image</b>

When a link is deleted, this image will be sent as a warning.

Please send an image to use as warning:
    """
    
    # Set state for next message
    user_message_states[call.from_user.id] = {
        'state': 'awaiting_warning_image',
        'message_id': call.message.message_id
    }
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data="settings_menu"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'statistics')
def show_statistics(call):
    """Show bot statistics"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Get statistics
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM groups')
    total_groups = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM admins')
    total_admins = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM messages')
    total_messages = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM sessions WHERE status = "active"')
    active_sessions_count = cursor.fetchone()[0]
    
    # Get today's activity
    cursor.execute('SELECT COUNT(*) FROM users WHERE DATE(last_active) = DATE("now")')
    active_today = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM messages WHERE DATE(sent_at) = DATE("now")')
    messages_today = cursor.fetchone()[0]
    
    conn.close()
    
    text = f"""
📊 <b>Bot Statistics</b>

👤 <b>Users:</b> {total_users}
📂 <b>Groups:</b> {total_groups}
👥 <b>Admins:</b> {total_admins}
💬 <b>Active Sessions:</b> {active_sessions_count}

📨 <b>Total Messages:</b> {total_messages}
📈 <b>Active Today:</b> {active_today} users
📝 <b>Messages Today:</b> {messages_today}

⏰ <b>Last Updated:</b> {datetime.now().strftime('%I:%M %p')}
    """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔄 Refresh", callback_data="statistics"),
                InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
    
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

@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document', 'sticker'])
def handle_all_messages(message):
    """Handle all incoming messages"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Update user activity
    update_user_activity(user_id)
    
    # Handle group messages
    if message.chat.type in ['group', 'supergroup']:
        handle_group_message(message)
        return
    
    # Handle private messages
    if message.chat.type == 'private':
        handle_private_message(message)

def handle_group_message(message):
    """Handle messages in groups"""
    group_id = message.chat.id
    user_id = message.from_user.id
    
    # Auto-detect and add group to database
    if message.chat.type in ['group', 'supergroup']:
        group_info = get_group(group_id)
        if not group_info:
            add_group(group_id, message.chat.title)
            logger.info(f"Auto-detected new group: {message.chat.title} ({group_id})")
    
    # Get group settings
    settings = get_group_settings(group_id)
    if not settings:
        return
    
    maintenance_mode, link_filter, bot_active = settings
    
    # Check if bot is active in this group
    if not bot_active:
        return
    
    # Check maintenance mode
    if maintenance_mode and not is_admin(user_id):
        try:
            bot.delete_message(group_id, message.message_id)
        except:
            pass
        return
    
    # Check link filter
    if link_filter and not is_admin(user_id):
        text = message.text or message.caption or ""
        if text and ('http://' in text.lower() or 'https://' in text.lower() or 't.me/' in text.lower()):
            try:
                bot.delete_message(group_id, message.message_id)
                
                # Get warning image from settings
                warning_image_id = get_setting('link_warning_image')
                
                # Create reply with user mention
                username = message.from_user.username
                if username:
                    mention = f"@{username}"
                else:
                    mention = message.from_user.first_name
                
                reply_text = f"{mention} হ্যাঁ ভাই🙂, উরাধুরা লিংক দাও, জায়গাটা কি তোমার বাপ কিনা রাখছে? 😒"
                
                # Send warning with image if available
                if warning_image_id:
                    try:
                        bot.send_photo(group_id, warning_image_id, caption=reply_text)
                    except:
                        bot.send_message(group_id, reply_text)
                else:
                    bot.send_message(group_id, reply_text)
                    
            except Exception as e:
                logger.error(f"Error handling link filter: {e}")
            return

def handle_private_message(message):
    """Handle private messages"""
    user_id = message.from_user.id
    
    # Check for admin commands and states
    if user_id in user_message_states:
        state = user_message_states[user_id]
        
        # Handle awaiting admin ID
        if state['state'] == 'awaiting_admin_id':
            handle_admin_id_input(message, state)
            return
        
        # Handle awaiting admin for group assignment
        elif state['state'] == 'awaiting_admin_for_group':
            handle_admin_group_assignment(message, state)
            return
        
        # Handle awaiting leave message
        elif state['state'] == 'awaiting_leave_message':
            handle_leave_message_input(message, state)
            return
        
        # Handle awaiting warning image
        elif state['state'] == 'awaiting_warning_image':
            handle_warning_image_input(message, state)
            return
        
        # Handle awaiting group broadcast
        elif state['state'] == 'awaiting_group_broadcast':
            handle_group_broadcast_input(message, state)
            return
    
    # Check if user is banned
    if is_banned(user_id):
        bot.send_message(user_id, "❌ You are banned from using this bot.")
        return
    
    # Add message to inbox
    if message.content_type == 'text':
        add_message_to_inbox(user_id, 'text', message.text)
    elif message.content_type == 'photo':
        add_message_to_inbox(user_id, 'photo', message.caption, message.photo[-1].file_id)
    elif message.content_type == 'video':
        add_message_to_inbox(user_id, 'video', message.caption, message.video.file_id)
    elif message.content_type == 'document':
        add_message_to_inbox(user_id, 'document', message.caption, message.document.file_id)
    
    increment_message_count(user_id)
    
    # Check if user is in active session
    if user_id in active_sessions:
        session = active_sessions[user_id]
        
        # Check if session is paused
        if session['is_paused']:
            bot.send_message(user_id, "⏸️ Chat session is currently paused by admin. Your message was not sent.")
            return
        
        admin_id = session['admin_id']
        
        # Forward message to admin
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
    
    # Check if admin is messaging a user in session
    elif is_admin(user_id):
        # Check if this admin has any active sessions
        for uid, session in list(active_sessions.items()):
            if session['admin_id'] == user_id and not session['is_paused']:
                # Forward message to user
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
        
        # If admin is not in session and no state, show admin panel
        handle_admin_panel(message)

def handle_admin_id_input(message, state):
    """Handle admin ID input"""
    try:
        admin_id = int(message.text)
        
        # Try to get user info
        try:
            user_info = bot.get_chat(admin_id)
            username = user_info.username or "No Username"
            first_name = user_info.first_name or ""
        except:
            username = "Unknown"
            first_name = "Unknown"
        
        # Add as admin with default permissions
        default_permissions = {
            'can_broadcast': False,
            'can_manage_settings': False,
            'can_ban_users': False,
            'can_view_inbox': True
        }
        
        add_admin(admin_id, username, json.dumps(default_permissions))
        
        # Send success message
        success_text = f"""
✅ <b>Admin Added Successfully</b>

👤 New Admin: {first_name} (@{username})
🆔 ID: {admin_id}

Default permissions granted:
• 📥 Can view inbox
        """
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("⚙️ Edit Permissions", callback_data=f"edit_perms_{admin_id}"),
            InlineKeyboardButton("👥 Back to Admin Manager", callback_data="admin_manager_1")
        )
        
        update_admin_panel_message(message.chat.id, state['message_id'], success_text, keyboard)
        
        # Notify new admin
        try:
            bot.send_message(admin_id, f"""
🎉 <b>You have been added as an admin!</b>

You can now access the admin panel using /admin

<b>Your current permissions:</b>
• 📥 View inbox and user messages
• 💬 Start chat sessions with users

Contact the super admin for additional permissions.
            """, parse_mode='HTML')
        except:
            pass
        
        # Clear state
        del user_message_states[message.from_user.id]
        
    except ValueError:
        # Check if it's a username
        if message.text.startswith('@'):
            username = message.text[1:]
            # In a real implementation, you would need to resolve username to ID
            # For now, show error
            bot.send_message(message.chat.id, "❌ Please send the numeric user ID, not username.")
            return
        
        bot.send_message(message.chat.id, "❌ Invalid user ID. Please send a numeric ID.")

def handle_admin_group_assignment(message, state):
    """Handle admin assignment to group"""
    try:
        admin_id = int(message.text)
        group_id = state['group_id']
        
        # Check if admin exists
        admin_info = get_admin(admin_id)
        if not admin_info:
            bot.send_message(message.chat.id, "❌ Admin not found. Make sure they are added as admin first.")
            return
        
        # Show permission selection
        group_info = get_group(group_id)
        group_name = group_info[1] if group_info else f"Group {group_id}"
        
        text = f"""
👥 <b>Set Permissions for Admin</b>

👤 Admin: {admin_info[1] or 'Unknown'}
🏷️ Group: {group_name}

Select permissions to grant:
        """
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("📢 Can Broadcast", callback_data=f"set_perm_{admin_id}_{group_id}_broadcast"),
            InlineKeyboardButton("⚙️ Can Manage Settings", callback_data=f"set_perm_{admin_id}_{group_id}_settings")
        )
        keyboard.add(
            InlineKeyboardButton("🚫 Can Ban Users", callback_data=f"set_perm_{admin_id}_{group_id}_ban"),
            InlineKeyboardButton("📥 Can View Inbox", callback_data=f"set_perm_{admin_id}_{group_id}_inbox")
        )
        keyboard.add(InlineKeyboardButton("✅ Save All", callback_data=f"save_all_perms_{admin_id}_{group_id}"))
        keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data=f"manage_group_{group_id}"))
        
        update_admin_panel_message(message.chat.id, state['message_id'], text, keyboard)
        
        # Clear state
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
    
    # Clear state
    del user_message_states[message.from_user.id]

def handle_warning_image_input(message, state):
    """Handle warning image input"""
    if message.content_type != 'photo':
        bot.send_message(message.chat.id, "❌ Please send an image.")
        return
    
    # Save the file_id of the largest photo
    file_id = message.photo[-1].file_id
    update_setting('link_warning_image', file_id)
    
    success_text = """
✅ <b>Warning Image Updated</b>

The new image will be used when deleting links.
    """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("⬅️ Back to Settings", callback_data="settings_menu"))
    
    update_admin_panel_message(message.chat.id, state['message_id'], success_text, keyboard)
    
    # Clear state
    del user_message_states[message.from_user.id]

def handle_group_broadcast_input(message, state):
    """Handle group broadcast input"""
    admin_id = message.from_user.id
    group_id = state['group_id']
    
    # Check permissions again
    if not can_admin_access_group(admin_id, group_id, 'can_broadcast'):
        bot.send_message(admin_id, "❌ You don't have permission to broadcast to this group!")
        return
    
    group_info = get_group(group_id)
    group_name = group_info[1] if group_info else f"Group {group_id}"
    
    # Send broadcast
    try:
        if message.content_type == 'text':
            bot.send_message(group_id, message.text)
        elif message.content_type == 'photo':
            bot.send_photo(group_id, message.photo[-1].file_id, caption=message.caption)
        elif message.content_type == 'video':
            bot.send_video(group_id, message.video.file_id, caption=message.caption)
        elif message.content_type == 'document':
            bot.send_document(group_id, message.document.file_id, caption=message.caption)
        
        success_text = f"""
✅ <b>Broadcast Sent Successfully</b>

🏷️ Group: {group_name}
🆔 ID: {group_id}

Your message has been sent to the group.
        """
        
    except Exception as e:
        success_text = f"""
❌ <b>Failed to Send Broadcast</b>

🏷️ Group: {group_name}
🆔 ID: {group_id}

Error: {str(e)}
        """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("⬅️ Back to Group", callback_data=f"manage_group_{group_id}"))
    
    update_admin_panel_message(message.chat.id, state['message_id'], success_text, keyboard)
    
    # Clear state
    del user_message_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_perm_'))
def set_admin_permission(call):
    """Set specific permission for admin in group"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can set permissions!", show_alert=True)
        return
    
    parts = call.data.split('_')
    admin_id = int(parts[2])
    group_id = int(parts[3])
    perm_type = parts[4]
    
    # Map permission type to database field
    perm_map = {
        'broadcast': 'can_broadcast',
        'settings': 'can_manage_settings',
        'ban': 'can_ban_users',
        'inbox': 'can_view_inbox'
    }
    
    if perm_type not in perm_map:
        bot.answer_callback_query(call.id, "Invalid permission type!", show_alert=True)
        return
    
    # Get current permissions
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT can_broadcast, can_manage_settings, can_ban_users, can_view_inbox 
        FROM admin_groups 
        WHERE admin_id = ? AND group_id = ?
    ''', (admin_id, group_id))
    result = cursor.fetchone()
    
    if result:
        # Update existing record
        perms = list(result)
        if perm_type == 'broadcast':
            perms[0] = 1 - perms[0]  # Toggle
        elif perm_type == 'settings':
            perms[1] = 1 - perms[1]
        elif perm_type == 'ban':
            perms[2] = 1 - perms[2]
        elif perm_type == 'inbox':
            perms[3] = 1 - perms[3]
        
        cursor.execute('''
            UPDATE admin_groups 
            SET can_broadcast = ?, can_manage_settings = ?, can_ban_users = ?, can_view_inbox = ?
            WHERE admin_id = ? AND group_id = ?
        ''', (*perms, admin_id, group_id))
    else:
        # Create new record with this permission enabled
        perms = [0, 0, 0, 0]
        if perm_type == 'broadcast':
            perms[0] = 1
        elif perm_type == 'settings':
            perms[1] = 1
        elif perm_type == 'ban':
            perms[2] = 1
        elif perm_type == 'inbox':
            perms[3] = 1
        
        cursor.execute('''
            INSERT INTO admin_groups (admin_id, group_id, can_broadcast, can_manage_settings, can_ban_users, can_view_inbox)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (admin_id, group_id, *perms))
    
    conn.commit()
    conn.close()
    
    # Get updated permissions
    updated_perms = get_admin_group_permissions(admin_id, group_id)
    
    # Create permission status text
    perm_status = ""
    perm_status += "📢 Broadcast: " + ("✅" if updated_perms['can_broadcast'] else "❌") + "\n"
    perm_status += "⚙️ Manage Settings: " + ("✅" if updated_perms['can_manage_settings'] else "❌") + "\n"
    perm_status += "🚫 Ban Users: " + ("✅" if updated_perms['can_ban_users'] else "❌") + "\n"
    perm_status += "📥 View Inbox: " + ("✅" if updated_perms['can_view_inbox'] else "❌")
    
    admin_info = get_admin(admin_id)
    group_info = get_group(group_id)
    
    text = f"""
👥 <b>Permissions Updated</b>

👤 Admin: {admin_info[1] or 'Unknown'}
🏷️ Group: {group_info[1] if group_info else f'Group {group_id}'}

<b>Current Permissions:</b>
{perm_status}
        """
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📢 Toggle Broadcast", callback_data=f"set_perm_{admin_id}_{group_id}_broadcast"),
        InlineKeyboardButton("⚙️ Toggle Settings", callback_data=f"set_perm_{admin_id}_{group_id}_settings")
    )
    keyboard.add(
        InlineKeyboardButton("🚫 Toggle Ban", callback_data=f"set_perm_{admin_id}_{group_id}_ban"),
        InlineKeyboardButton("📥 Toggle Inbox", callback_data=f"set_perm_{admin_id}_{group_id}_inbox")
    )
    keyboard.add(InlineKeyboardButton("✅ Done", callback_data=f"manage_group_{group_id}"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)
    bot.answer_callback_query(call.id, "Permission updated!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_all_perms_'))
def save_all_permissions(call):
    """Save all permissions for admin in group"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can set permissions!", show_alert=True)
        return
    
    parts = call.data.split('_')
    admin_id = int(parts[3])
    group_id = int(parts[4])
    
    # Grant all permissions
    add_admin_to_group(admin_id, group_id, 1, 1, 1, 1)
    
    admin_info = get_admin(admin_id)
    group_info = get_group(group_id)
    
    text = f"""
✅ <b>All Permissions Granted</b>

👤 Admin: {admin_info[1] or 'Unknown'}
🏷️ Group: {group_info[1] if group_info else f'Group {group_id}'}

<b>Granted Permissions:</b>
• 📢 Can broadcast messages
• ⚙️ Can manage group settings
• 🚫 Can ban users in group
• 📥 Can view inbox for group
        """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("⬅️ Back to Group", callback_data=f"manage_group_{group_id}"))
    
    update_admin_panel_message(call.message.chat.id, call.message.message_id, text, keyboard)
    bot.answer_callback_query(call.id, "All permissions granted!")

# ================ FLASK ROUTES FOR 24/7 UPTIME ================

@app.route('/')
def home():
    return "🤖 Advanced Telegram Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return 'Bad request', 400

# ================ CLEANUP FUNCTIONS ================

def cleanup_sessions():
    """Clean up old sessions periodically"""
    while True:
        time.sleep(3600)  # Run every hour
        current_time = datetime.now()
        
        # Remove sessions older than 24 hours
        for user_id, session_data in list(active_sessions.items()):
            if (current_time - session_data['start_time']).total_seconds() > 86400:
                end_session(session_data['session_id'])
                active_sessions.pop(user_id, None)
                
                # Notify admin
                try:
                    bot.send_message(session_data['admin_id'], 
                                   f"⏰ Session with User ID {user_id} automatically ended (24h limit).")
                except:
                    pass
        
        # Clean up old cooldowns
        current_timestamp = time.time()
        for user_id, timestamp in list(user_cooldowns.items()):
            if current_timestamp - timestamp > 600:  # 10 minutes
                user_cooldowns.pop(user_id, None)
        
        # Clean up old message states (older than 30 minutes)
        for user_id in list(user_message_states.keys()):
            # Simple cleanup - remove states that might be stuck
            time.sleep(0.1)

def run_bot():
    """Run the bot with polling"""
    logger.info("Starting bot polling...")
    bot.remove_webhook()
    time.sleep(1)
    bot.polling(none_stop=True, interval=0, timeout=20)

# ================ MAIN FUNCTION ================

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Start session cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_sessions, daemon=True)
    cleanup_thread.start()
    
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Run Flask app with port 8080
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting Flask server on port {port}")
    
    # Keep main thread alive
    try:
        app.run(host='0.0.0.0', port=port, debug=False)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\n👋 Bot stopped.")
