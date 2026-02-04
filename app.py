import os
import sqlite3
import threading
import time
import logging
from datetime import datetime, timedelta
from flask import Flask, request
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import re

# Initialize Flask app for 24/7 uptime
app = Flask(__name__)

# Initialize bot with your token
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
bot = telebot.TeleBot(BOT_TOKEN)

# Database setup
DB_NAME = 'bot_final.db'

# Super Admin ID (Replace with your Telegram ID)
SUPER_ADMIN_ID = 7832264582   # Change this to your actual Telegram ID

# Store active sessions and cooldowns
active_sessions = {}
user_cooldowns = {}

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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    # Session history table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        admin_id INTEGER,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        status TEXT DEFAULT 'active'
    )
    ''')
    
    # Add super admin if not exists
    cursor.execute('INSERT OR IGNORE INTO admins (admin_id, username, is_super) VALUES (?, ?, ?)',
                   (SUPER_ADMIN_ID, 'super_admin', 1))
    
    # Add default leave message if not exists
    cursor.execute('INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES (?, ?)',
                   ('leave_message', '👋 Goodbye!'))
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

def add_user(user_id, username, first_name=None, last_name=None):
    """Add or update user in database"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)
        VALUES (?, ?, ?, ?)
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

def get_all_users():
    """Get all registered users"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, first_name FROM users ORDER BY created_at DESC')
    users = cursor.fetchall()
    conn.close()
    return users

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
        INSERT OR REPLACE INTO groups (group_id, title)
        VALUES (?, ?)
    ''', (group_id, title))
    conn.commit()
    conn.close()

def get_all_groups():
    """Get all groups"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM groups ORDER BY added_at DESC')
    groups = cursor.fetchall()
    conn.close()
    return groups

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

def end_session(session_id):
    """End a session"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE sessions SET status = "ended", ended_at = CURRENT_TIMESTAMP WHERE session_id = ?',
                   (session_id,))
    conn.commit()
    conn.close()

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
    
    # Send request to super admin
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("✅ Accept", callback_data=f"accept_{user_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
    )
    
    request_text = f"""
📨 New Chat Request:

👤 User: {first_name} (@{username})
🆔 ID: {user_id}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    
    # Send to all admins
    admins = get_admins()
    for admin_id, admin_username, _ in admins:
        try:
            bot.send_message(admin_id, request_text, reply_markup=keyboard)
        except:
            pass
    
    bot.answer_callback_query(call.id, "✅ Your request has been sent to admins!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_'))
def handle_accept_request(call):
    """Handle accept request from admin"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ You are not authorized!", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    
    # Start session
    session_id = add_session(user_id, call.from_user.id)
    active_sessions[user_id] = {
        'admin_id': call.from_user.id,
        'session_id': session_id,
        'start_time': datetime.now()
    }
    
    # Notify user
    try:
        bot.send_message(user_id, "✅ Your chat request has been accepted! You can now message the admin.")
    except:
        pass
    
    # Notify admin
    user_info = get_user(user_id)
    user_name = user_info[2] if user_info else "User"
    bot.answer_callback_query(call.id, f"✅ Chat started with {user_name}")
    
    # Edit admin message
    try:
        bot.edit_message_text(f"✅ Chat accepted with User ID: {user_id}",
                              call.message.chat.id,
                              call.message.message_id)
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

@bot.message_handler(commands=['admin'])
def handle_admin_panel(message):
    """Handle /admin command"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(user_id, "❌ You are not authorized to access the admin panel.")
        return
    
    # Create admin panel keyboard
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📥 Inbox Manager", callback_data="inbox_manager"),
        InlineKeyboardButton("📂 Group Manager", callback_data="group_manager"),
        InlineKeyboardButton("✍️ Set Leave Msg", callback_data="set_leave_msg"),
        InlineKeyboardButton("📢 Global Broadcast", callback_data="global_broadcast"),
        InlineKeyboardButton("👥 Add Admin", callback_data="add_admin_menu"),
        InlineKeyboardButton("📊 Bot Status", callback_data="bot_status")
    )
    
    admin_text = """
🛠️ **Admin Control Panel**

Choose an option from below:
    """
    bot.send_message(user_id, admin_text, reply_markup=keyboard, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == 'inbox_manager')
def show_inbox_manager(call):
    """Show inbox manager with all users"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    users = get_all_users()
    
    if not users:
        bot.edit_message_text("📭 No registered users yet.",
                              call.message.chat.id,
                              call.message.message_id)
        return
    
    # Create paginated user list
    keyboard = InlineKeyboardMarkup()
    
    for user in users[:10]:  # Show first 10 users
        user_id, username, first_name = user
        display_name = first_name or username or f"User {user_id}"
        keyboard.add(InlineKeyboardButton(
            f"👤 {display_name}", 
            callback_data=f"manage_user_{user_id}"
        ))
    
    # Add back button
    keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
    
    bot.edit_message_text(
        f"📥 Inbox Manager\n\nTotal Users: {len(users)}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )

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
    
    username = user_info[1] or "No Username"
    first_name = user_info[2] or ""
    is_banned_user = user_info[4]
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if user_id in active_sessions:
        keyboard.add(InlineKeyboardButton("💬 In Session", callback_data="no_action"))
    else:
        keyboard.add(InlineKeyboardButton("💬 Start Chat", callback_data=f"admin_chat_{user_id}"))
    
    if is_banned_user:
        keyboard.add(InlineKeyboardButton("🔓 Unban User", callback_data=f"unban_{user_id}"))
    else:
        keyboard.add(InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_{user_id}"))
    
    keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="inbox_manager"))
    
    user_text = f"""
👤 **User Management**

🆔 ID: `{user_id}`
📛 Name: {first_name}
🔗 Username: @{username}
🚫 Status: {"Banned" if is_banned_user else "Active"}
    """
    
    bot.edit_message_text(
        user_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_chat_'))
def admin_start_chat(call):
    """Admin manually starts chat with user"""
    admin_id = call.from_user.id
    user_id = int(call.data.split('_')[2])
    
    # Start session
    session_id = add_session(user_id, admin_id)
    active_sessions[user_id] = {
        'admin_id': admin_id,
        'session_id': session_id,
        'start_time': datetime.now()
    }
    
    # Notify user
    try:
        bot.send_message(user_id, "👋 An admin has started a chat with you. You can now message them directly.")
    except:
        pass
    
    # Notify admin
    bot.answer_callback_query(call.id, "✅ Chat session started!")
    bot.send_message(admin_id, f"💬 You are now chatting with User ID: {user_id}\nSend /endchat to end this session.")

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

@bot.callback_query_handler(func=lambda call: call.data == 'group_manager')
def show_group_manager(call):
    """Show group manager"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    groups = get_all_groups()
    
    if not groups:
        bot.edit_message_text("📭 Bot is not in any groups yet.",
                              call.message.chat.id,
                              call.message.message_id)
        return
    
    keyboard = InlineKeyboardMarkup()
    
    for group in groups[:10]:  # Show first 10 groups
        group_id, title, maintenance, link_filter, bot_active, _ = group
        status_icon = "🟢" if bot_active else "🔴"
        keyboard.add(InlineKeyboardButton(
            f"{status_icon} {title[:20]}", 
            callback_data=f"manage_group_{group_id}"
        ))
    
    # Add back button
    keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
    
    bot.edit_message_text(
        f"📂 Group Manager\n\nTotal Groups: {len(groups)}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_group_'))
def manage_group(call):
    """Show group management options"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    group_id = int(call.data.split('_')[2])
    settings = get_group_settings(group_id)
    
    if not settings:
        bot.answer_callback_query(call.id, "Group not found!", show_alert=True)
        return
    
    maintenance_mode, link_filter, bot_active = settings
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    # Maintenance Mode toggle
    mm_text = "🔧 Maintenance: ON" if maintenance_mode else "🔧 Maintenance: OFF"
    keyboard.add(InlineKeyboardButton(mm_text, callback_data=f"toggle_mm_{group_id}"))
    
    # Link Filter toggle
    lf_text = "🔗 Link Filter: ON" if link_filter else "🔗 Link Filter: OFF"
    keyboard.add(InlineKeyboardButton(lf_text, callback_data=f"toggle_lf_{group_id}"))
    
    # Bot Status toggle
    bs_text = "🤖 Bot: ACTIVE" if bot_active else "🤖 Bot: PAUSED"
    keyboard.add(InlineKeyboardButton(bs_text, callback_data=f"toggle_bs_{group_id}"))
    
    # Leave Group button
    keyboard.add(InlineKeyboardButton("🚪 Leave Group", callback_data=f"leave_group_{group_id}"))
    
    # Back button
    keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="group_manager"))
    
    group_text = f"""
📂 **Group Management**

🆔 Group ID: `{group_id}`

Toggle the settings below:
- 🔧 Maintenance Mode: Only admins can chat when ON
- 🔗 Link Filter: Delete links from non-admins when ON
- 🤖 Bot Status: Activate/Pause bot functions
    """
    
    bot.edit_message_text(
        group_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_mm_'))
def toggle_maintenance_mode(call):
    """Toggle maintenance mode"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    group_id = int(call.data.split('_')[2])
    settings = get_group_settings(group_id)
    
    if settings:
        current_value = settings[0]
        new_value = 0 if current_value else 1
        update_group_setting(group_id, 'maintenance_mode', new_value)
        
        status = "ON" if new_value else "OFF"
        bot.answer_callback_query(call.id, f"Maintenance Mode turned {status}")
        manage_group(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_lf_'))
def toggle_link_filter(call):
    """Toggle link filter"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    group_id = int(call.data.split('_')[2])
    settings = get_group_settings(group_id)
    
    if settings:
        current_value = settings[1]
        new_value = 0 if current_value else 1
        update_group_setting(group_id, 'link_filter', new_value)
        
        status = "ON" if new_value else "OFF"
        bot.answer_callback_query(call.id, f"Link Filter turned {status}")
        manage_group(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_bs_'))
def toggle_bot_status(call):
    """Toggle bot status"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    group_id = int(call.data.split('_')[2])
    settings = get_group_settings(group_id)
    
    if settings:
        current_value = settings[2]
        new_value = 0 if current_value else 1
        update_group_setting(group_id, 'bot_active', new_value)
        
        status = "ACTIVE" if new_value else "PAUSED"
        bot.answer_callback_query(call.id, f"Bot status changed to {status}")
        manage_group(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('leave_group_'))
def leave_group_handler(call):
    """Handle leaving group"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    group_id = int(call.data.split('_')[2])
    
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
        conn.commit()
        conn.close()
        
        bot.answer_callback_query(call.id, "✅ Left group successfully!")
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Failed to leave group: {str(e)}", show_alert=True)
    
    # Go back to group manager
    show_group_manager(call)

@bot.callback_query_handler(func=lambda call: call.data == 'set_leave_msg')
def set_leave_message(call):
    """Prompt admin to set leave message"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    current_msg = get_setting('leave_message') or "👋 Goodbye!"
    
    bot.edit_message_text(
        f"✍️ **Set Leave Message**\n\nCurrent message: {current_msg}\n\nPlease send the new leave message:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )
    
    # Set next message handler for this admin
    @bot.message_handler(func=lambda m: m.from_user.id == call.from_user.id and m.chat.type == 'private')
    def handle_leave_message_input(message):
        new_message = message.text
        update_setting('leave_message', new_message)
        
        bot.send_message(message.chat.id, f"✅ Leave message updated to:\n{new_message}")
        
        # Go back to admin panel
        handle_admin_panel(message)
        
        # Remove this handler
        bot.message_handler(func=None)(handle_leave_message_input)

@bot.callback_query_handler(func=lambda call: call.data == 'global_broadcast')
def global_broadcast_menu(call):
    """Show global broadcast menu"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can use this!", show_alert=True)
        return
    
    bot.edit_message_text(
        "📢 **Global Broadcast**\n\nSend the message you want to broadcast to all groups:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )
    
    # Set next message handler for broadcast
    @bot.message_handler(func=lambda m: m.from_user.id == call.from_user.id and m.chat.type == 'private')
    def handle_broadcast_input(message):
        broadcast_message = message.text
        groups = get_all_groups()
        
        sent_count = 0
        for group in groups:
            group_id = group[0]
            try:
                bot.send_message(group_id, broadcast_message)
                sent_count += 1
                time.sleep(0.1)  # Avoid rate limiting
            except:
                pass
        
        bot.send_message(message.chat.id, f"✅ Broadcast sent to {sent_count}/{len(groups)} groups")
        
        # Go back to admin panel
        handle_admin_panel(message)
        
        # Remove this handler
        bot.message_handler(func=None)(handle_broadcast_input)

@bot.callback_query_handler(func=lambda call: call.data == 'add_admin_menu')
def add_admin_menu(call):
    """Show add admin menu"""
    if not is_super_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Only Super Admin can add admins!", show_alert=True)
        return
    
    bot.edit_message_text(
        "👥 **Add New Admin**\n\nSend the user ID of the person you want to make admin:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )
    
    # Set next message handler for adding admin
    @bot.message_handler(func=lambda m: m.from_user.id == call.from_user.id and m.chat.type == 'private')
    def handle_add_admin_input(message):
        try:
            new_admin_id = int(message.text)
            # Try to get username
            try:
                user_info = bot.get_chat(new_admin_id)
                username = user_info.username or "No Username"
            except:
                username = "Unknown"
            
            add_admin(new_admin_id, username)
            bot.send_message(message.chat.id, f"✅ User {new_admin_id} added as admin!")
            
            # Notify new admin
            try:
                bot.send_message(new_admin_id, "🎉 You have been added as an admin! Use /admin to access the admin panel.")
            except:
                pass
            
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid user ID. Please send a numeric ID.")
        
        # Go back to admin panel
        handle_admin_panel(message)
        
        # Remove this handler
        bot.message_handler(func=None)(handle_add_admin_input)

@bot.callback_query_handler(func=lambda call: call.data == 'bot_status')
def show_bot_status(call):
    """Show bot status"""
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
    
    users = get_all_users()
    groups = get_all_groups()
    admins = get_admins()
    active_session_count = len(active_sessions)
    
    status_text = f"""
📊 **Bot Status**

👤 Total Users: {len(users)}
📂 Total Groups: {len(groups)}
👥 Total Admins: {len(admins)}
💬 Active Sessions: {active_session_count}
🕒 Server Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
    
    bot.edit_message_text(
        status_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_admin')
def back_to_admin(call):
    """Go back to admin panel"""
    handle_admin_panel(call.message)

@bot.callback_query_handler(func=lambda call: call.data == 'no_action')
def no_action(call):
    """Handle no action button"""
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['endchat'])
def end_chat_session(message):
    """End an active chat session"""
    user_id = message.from_user.id
    
    # Check if user is in active session
    if user_id in active_sessions:
        session_data = active_sessions.pop(user_id)
        end_session(session_data['session_id'])
        
        # Notify both parties
        bot.send_message(user_id, "✅ Chat session ended.")
        if session_data['admin_id'] != user_id:
            try:
                bot.send_message(session_data['admin_id'], f"💬 Chat session with User ID {user_id} has ended.")
            except:
                pass
    else:
        # Check if admin is in session with someone
        for uid, session in list(active_sessions.items()):
            if session['admin_id'] == user_id:
                session_data = active_sessions.pop(uid)
                end_session(session_data['session_id'])
                
                bot.send_message(user_id, f"✅ Chat session with User ID {uid} ended.")
                try:
                    bot.send_message(uid, "✅ Chat session ended by admin.")
                except:
                    pass
                break
        else:
            bot.send_message(user_id, "❌ No active chat session found.")

@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document'])
def handle_all_messages(message):
    """Handle all incoming messages"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
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
    
    # Check if group is in database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM groups WHERE group_id = ?', (group_id,))
    group = cursor.fetchone()
    conn.close()
    
    # If group not in database, add it
    if not group:
        add_group(group_id, message.chat.title)
    
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
                
                # Reply to user with mention
                username = message.from_user.username or message.from_user.first_name
                reply_text = f"@{username} হ্যাঁ ভাই🙂, উরাধুরা লিংক দাও, জায়গাটা কি তোমার বাপ কিনা রাখছে? 😒"
                bot.send_message(group_id, reply_text, reply_to_message_id=message.message_id)
            except:
                pass
            return

def handle_private_message(message):
    """Handle private messages"""
    user_id = message.from_user.id
    
    # Check if user is banned
    if is_banned(user_id):
        bot.send_message(user_id, "❌ You are banned from using this bot.")
        return
    
    # Check if user is in active session
    if user_id in active_sessions:
        admin_id = active_sessions[user_id]['admin_id']
        
        # Forward message to admin
        try:
            if message.content_type == 'text':
                bot.send_message(admin_id, f"👤 User ({user_id}): {message.text}")
            elif message.content_type == 'photo':
                bot.send_photo(admin_id, message.photo[-1].file_id, caption=message.caption)
            elif message.content_type == 'video':
                bot.send_video(admin_id, message.video.file_id, caption=message.caption)
            elif message.content_type == 'document':
                bot.send_document(admin_id, message.document.file_id, caption=message.caption)
        except Exception as e:
            bot.send_message(user_id, "❌ Failed to send message to admin.")
            logger.error(f"Failed to forward message: {e}")
    
    # Check if admin is messaging a user in session
    elif is_admin(user_id):
        # Check if this admin has any active sessions
        for uid, session in list(active_sessions.items()):
            if session['admin_id'] == user_id:
                # Forward message to user
                try:
                    if message.content_type == 'text':
                        bot.send_message(uid, f"👮 Admin: {message.text}")
                    elif message.content_type == 'photo':
                        bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption)
                    elif message.content_type == 'video':
                        bot.send_video(uid, message.video.file_id, caption=message.caption)
                    elif message.content_type == 'document':
                        bot.send_document(uid, message.document.file_id, caption=message.caption)
                except Exception as e:
                    bot.send_message(user_id, f"❌ Failed to send message to user {uid}")
                    logger.error(f"Failed to forward message to user: {e}")
                return
        
        # If admin is not in session, show admin panel
        handle_admin_panel(message)

# ================ FLASK ROUTES FOR 24/7 UPTIME ================

@app.route('/')
def home():
    return "🤖 Telegram Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return 'Bad request', 400

# ================ THREADING FUNCTIONS ================

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
    
    # Run Flask app for webhook (optional) and 24/7 uptime
    # For production with webhook, use:
    # bot.remove_webhook()
    # time.sleep(1)
    # bot.set_webhook(url="https://your-domain.com/webhook")
    
    logger.info("Bot started successfully!")
    print("🤖 Bot is running... Press Ctrl+C to stop.")
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\n👋 Bot stopped.")
