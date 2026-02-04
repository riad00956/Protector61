import telebot
import sqlite3
import datetime
import threading
import time
from telebot import types
from flask import Flask

# ================= FLASK SERVER =================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running perfectly!"

def run_web_server():
    app.run(host='0.0.0.0', port=10000)

# ================= CONFIGURATION =================
TOKEN = "8000160699:AAHq1VLvd05PFxFVibuErFx4E6Uf7y6F8HE"
SUPER_ADMIN = 7832264582 
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=25)

active_sessions = {}  # {admin_id: user_id}
chat_requests = {}  # {user_id: {"time": timestamp, "status": "pending"}}
cooldowns = {}  # {user_id: timestamp}

try:
    bot.remove_webhook()
except:
    pass

# ================= DATABASE SYSTEM =================
db_lock = threading.Lock()

def get_db_connection():
    return sqlite3.connect('bot_final.db', check_same_thread=False)

def init_db():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Admins table
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins 
                          (user_id INTEGER PRIMARY KEY, target_group INTEGER DEFAULT 0, perms TEXT)''')
        # Groups table
        cursor.execute('''CREATE TABLE IF NOT EXISTS groups 
                          (chat_id INTEGER PRIMARY KEY, title TEXT, 
                           maintenance INTEGER DEFAULT 0, link_filter INTEGER DEFAULT 1, 
                           bot_status INTEGER DEFAULT 1, leave_msg TEXT DEFAULT "আমি বের হয়ে যাচ্ছি, ভালো থেকো।")''')
        # Users table
        cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                          (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
                           last_seen TEXT, is_banned INTEGER DEFAULT 0, 
                           chat_requests INTEGER DEFAULT 0)''')
        # Messages table for user messages
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_messages 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                           message_text TEXT, message_type TEXT, 
                           timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()

init_db()

# ================= HELPER FUNCTIONS =================
def get_setting(chat_id, key):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'SELECT {key} FROM groups WHERE chat_id = ?', (chat_id,))
        res = cursor.fetchone()
        conn.close()
        if res is None:
            if key == 'leave_msg': 
                return "আমি বের হয়ে যাচ্ছি, ভালো থেকো।"
            elif key == 'bot_status':
                return 1
            else:
                return 0
        return res[0]

def update_setting(chat_id, key, value):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)', (chat_id, "Group"))
        cursor.execute(f'UPDATE groups SET {key} = ? WHERE chat_id = ?', (value, chat_id))
        conn.commit()
        conn.close()

def toggle_setting(chat_id, key):
    current = get_setting(chat_id, key)
    new_val = 1 if current == 0 else 0
    update_setting(chat_id, key, new_val)
    return new_val

def register_user(user_id, username, first_name):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''INSERT OR REPLACE INTO users 
                          (user_id, username, first_name, last_seen) 
                          VALUES (?, ?, ?, ?)''', 
                       (user_id, username, first_name, now))
        conn.commit()
        conn.close()

def update_user_last_seen(user_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('UPDATE users SET last_seen = ? WHERE user_id = ?', (now, user_id))
        conn.commit()
        conn.close()

def increment_chat_requests(user_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET chat_requests = chat_requests + 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

def is_admin(user_id, chat_id=None):
    if user_id == SUPER_ADMIN: 
        return True
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT target_group FROM admins WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        conn.close()
        if res:
            if chat_id and res[0] != 0 and res[0] != chat_id: 
                return False
            return True
        return False

def get_user_info(user_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT username, first_name, last_seen, is_banned, chat_requests FROM users WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        conn.close()
        if res:
            return {
                "username": res[0] or "No username",
                "first_name": res[1] or "No name",
                "last_seen": res[2] or "Never",
                "is_banned": bool(res[3]),
                "chat_requests": res[4]
            }
        return None

def toggle_ban_user(user_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        if res:
            new_status = 0 if res[0] == 1 else 1
            cursor.execute('UPDATE users SET is_banned = ? WHERE user_id = ?', (new_status, user_id))
            conn.commit()
            conn.close()
            return new_status
        conn.close()
        return None

def save_user_message(user_id, message_text, message_type):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO user_messages (user_id, message_text, message_type) 
                          VALUES (?, ?, ?)''', (user_id, message_text, message_type))
        conn.commit()
        conn.close()

# ================= KEYBOARDS =================
def main_admin_keyboard(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if uid == SUPER_ADMIN:
        markup.add(
            types.InlineKeyboardButton("📂 Group Manager", callback_data="list_groups"),
            types.InlineKeyboardButton("📋 Admin List", callback_data="admin_list")
        )
        markup.add(
            types.InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
            types.InlineKeyboardButton("➖ Remove Admin", callback_data="del_admin_list")
        )
        markup.add(
            types.InlineKeyboardButton("📢 Global Broadcast", callback_data="bc_all"),
            types.InlineKeyboardButton("📥 Inbox Messages", callback_data="inbox_list")
        )
        markup.add(types.InlineKeyboardButton("✍️ Set Leave Msg", callback_data="set_leave_msg"))
    else:
        markup.add(types.InlineKeyboardButton("📂 View Groups", callback_data="list_groups"))
        markup.add(types.InlineKeyboardButton("📥 Inbox Messages", callback_data="inbox_list"))
    return markup

def group_control_keyboard(chat_id):
    m = get_setting(chat_id, 'maintenance')
    l = get_setting(chat_id, 'link_filter')
    s = get_setting(chat_id, 'bot_status')
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"{'🔴' if m else '🟢'} Maintenance: {'ON' if m else 'OFF'}", 
                                   callback_data=f"tog_m_{chat_id}"),
        types.InlineKeyboardButton(f"{'🟢' if l else '🔴'} Link Filter: {'ON' if l else 'OFF'}", 
                                   callback_data=f"tog_l_{chat_id}"),
        types.InlineKeyboardButton(f"{'✅' if s else '⏸'} Bot Status: {'Active' if s else 'Paused'}", 
                                   callback_data=f"tog_s_{chat_id}"),
        types.InlineKeyboardButton("📢 Group Broadcast", callback_data=f"bc_{chat_id}"),
        types.InlineKeyboardButton("🚪 Leave Group", callback_data=f"leave_{chat_id}"),
        types.InlineKeyboardButton("⬅️ Back", callback_data="list_groups")
    )
    return markup

def user_request_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🙋 Request to Chat", callback_data="req_chat"))
    return markup

def user_menu_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    user_info = get_user_info(user_id)
    if user_info and user_info["is_banned"]:
        markup.add(types.InlineKeyboardButton("🔓 Unban User", callback_data=f"toggle_ban_{user_id}"))
    else:
        markup.add(types.InlineKeyboardButton("🔨 Ban User", callback_data=f"toggle_ban_{user_id}"))
    
    markup.add(
        types.InlineKeyboardButton("💬 Start Chat", callback_data=f"start_chat_{user_id}"),
        types.InlineKeyboardButton("📝 Send Message", callback_data=f"send_msg_{user_id}")
    )
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="inbox_list"))
    return markup

def chat_request_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Accept", callback_data=f"accept_req_{user_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_req_{user_id}")
    )
    return markup

# ================= MESSAGE HANDLERS =================
@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'sticker'])
def handle_all(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Update user information
    register_user(user_id, message.from_user.username, message.from_user.first_name)
    update_user_last_seen(user_id)
    
    # Save user message if not admin
    if not is_admin(user_id) and message.content_type == 'text' and message.text:
        save_user_message(user_id, message.text, 'text')
    
    # Handle private chat
    if message.chat.type == "private":
        # Check if admin is in session with this user
        admin_id = None
        for admin, user in active_sessions.items():
            if user == user_id:
                admin_id = admin
                break
        
        if admin_id:
            # Forward user message to admin
            try:
                if message.text:
                    bot.send_message(admin_id, f"👤 *User Message:*\n{message.text}", parse_mode="Markdown")
                elif message.photo:
                    bot.send_photo(admin_id, message.photo[-1].file_id, caption=f"👤 User sent photo\nCaption: {message.caption}")
                elif message.video:
                    bot.send_video(admin_id, message.video.file_id, caption=f"👤 User sent video\nCaption: {message.caption}")
                elif message.document:
                    bot.send_document(admin_id, message.document.file_id, caption=f"👤 User sent document\nCaption: {message.caption}")
                elif message.audio:
                    bot.send_audio(admin_id, message.audio.file_id, caption=f"👤 User sent audio")
                elif message.sticker:
                    bot.send_sticker(admin_id, message.sticker.file_id)
                    bot.send_message(admin_id, "👤 User sent a sticker")
            except Exception as e:
                print(f"Error forwarding message: {e}")
            return
        
        # Check if user is banned
        user_info = get_user_info(user_id)
        if user_info and user_info["is_banned"]:
            bot.send_message(chat_id, "🚫 You are banned from using this bot.")
            return
        
        # Handle commands
        if message.text == "/start":
            welcome_text = f"👋 Hello {message.from_user.first_name}!\n\nWelcome to the bot. You can request to chat with an admin using the button below."
            bot.send_message(chat_id, welcome_text, reply_markup=user_request_keyboard())
        
        elif message.text == "/admin":
            if is_admin(user_id):
                bot.send_message(chat_id, "🏮 **Admin Control Panel**", 
                               reply_markup=main_admin_keyboard(user_id), parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "⚠️ You are not an admin.")
        else:
            # If user sends any other message
            if not is_admin(user_id):
                bot.send_message(chat_id, "Please use the buttons below to interact with the bot.", 
                               reply_markup=user_request_keyboard())
    
    # Handle group messages
    else:
        # Update group info
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO groups (chat_id, title) VALUES (?, ?)', 
                         (chat_id, message.chat.title))
            conn.commit()
            conn.close()
        
        # Check bot status
        if get_setting(chat_id, 'bot_status') == 0:
            return
        
        # Check maintenance mode
        if get_setting(chat_id, 'maintenance') == 1 and not is_admin(user_id, chat_id):
            try:
                bot.delete_message(chat_id, message.message_id)
            except:
                pass
            return
        
        # Check link filter
        if get_setting(chat_id, 'link_filter') == 1:
            text = message.text or message.caption or ""
            if ("http://" in text.lower() or "https://" in text.lower() or "t.me/" in text.lower()) and not is_admin(user_id, chat_id):
                try:
                    bot.delete_message(chat_id, message.message_id)
                    bot.send_message(chat_id, 
                                   f"@{message.from_user.username or message.from_user.first_name} হ্যাঁ ভাই🙂, উরাধুরা লিংক দাও, জায়গাটা কি তোমার বাপ কিনা রাখছে? 😒")
                except:
                    pass

# ================= CALLBACK HANDLERS =================
@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    # Handle chat request from user
    if call.data == "req_chat":
        # Check if user is banned
        user_info = get_user_info(user_id)
        if user_info and user_info["is_banned"]:
            bot.answer_callback_query(call.id, "🚫 You are banned from requesting chat.", show_alert=True)
            return
        
        # Check cooldown
        now = time.time()
        if user_id in cooldowns and now - cooldowns[user_id] < 600:
            remaining = int((600 - (now - cooldowns[user_id])) / 60)
            bot.answer_callback_query(call.id, f"Please wait {remaining} minutes before requesting again.", show_alert=True)
            return
        
        # Set cooldown
        cooldowns[user_id] = now
        
        # Store request
        chat_requests[user_id] = {
            "time": now,
            "status": "pending",
            "name": call.from_user.first_name,
            "username": call.from_user.username
        }
        
        # Update database
        increment_chat_requests(user_id)
        
        # Notify user
        bot.edit_message_text("✅ Your chat request has been sent to admins. Please wait for a response.", 
                            chat_id, message_id)
        
        # Send notification to SUPER_ADMIN
        user_info = get_user_info(user_id)
        request_text = f"🙋 **New Chat Request!**\n\n"
        request_text += f"👤 Name: {call.from_user.first_name}\n"
        if call.from_user.username:
            request_text += f"📱 Username: @{call.from_user.username}\n"
        request_text += f"🆔 ID: `{user_id}`\n"
        request_text += f"📅 Last Seen: {user_info['last_seen'] if user_info else 'Unknown'}\n"
        request_text += f"📞 Total Requests: {user_info['chat_requests'] if user_info else 0}"
        
        try:
            bot.send_message(SUPER_ADMIN, request_text, 
                           reply_markup=chat_request_keyboard(user_id), parse_mode="Markdown")
        except:
            pass
        
        # Also notify other admins
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            admins = cursor.execute('SELECT user_id FROM admins').fetchall()
            conn.close()
        
        for admin in admins:
            if admin[0] != SUPER_ADMIN:
                try:
                    bot.send_message(admin[0], request_text, parse_mode="Markdown")
                except:
                    pass
    
    # Handle admin accepting chat request
    elif call.data.startswith("accept_req_"):
        if not is_admin(user_id):
            return
        
        target_user_id = int(call.data.split("_")[2])
        
        # Update request status
        if target_user_id in chat_requests:
            chat_requests[target_user_id]["status"] = "accepted"
        
        # Start session
        active_sessions[user_id] = target_user_id
        active_sessions[target_user_id] = user_id
        
        # Notify admin
        bot.edit_message_text(f"✅ Chat session started with user `{target_user_id}`.\n\nYou can now chat with the user directly.", 
                            chat_id, message_id, parse_mode="Markdown")
        
        # Notify user
        try:
            bot.send_message(target_user_id, "✅ Your chat request has been accepted! You can now chat with the admin.")
        except:
            pass
    
    # Handle admin rejecting chat request
    elif call.data.startswith("reject_req_"):
        if not is_admin(user_id):
            return
        
        target_user_id = int(call.data.split("_")[2])
        
        # Update request status
        if target_user_id in chat_requests:
            chat_requests[target_user_id]["status"] = "rejected"
        
        # Notify admin
        bot.edit_message_text(f"❌ Chat request from user `{target_user_id}` has been rejected.", 
                            chat_id, message_id, parse_mode="Markdown")
        
        # Notify user
        try:
            bot.send_message(target_user_id, "❌ Your chat request has been rejected by the admin.")
        except:
            pass
    
    # Handle admin panel navigation
    elif call.data == "back_main":
        if not is_admin(user_id):
            return
        bot.edit_message_text("🏮 **Admin Control Panel**", chat_id, message_id, 
                            reply_markup=main_admin_keyboard(user_id), parse_mode="Markdown")
    
    elif call.data == "list_groups":
        if not is_admin(user_id):
            return
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT chat_id, title FROM groups')
            rows = cursor.fetchall()
            conn.close()
        
        if not rows:
            bot.edit_message_text("📭 No groups found.", chat_id, message_id)
            return
        
        markup = types.InlineKeyboardMarkup()
        for row in rows:
            group_id, title = row
            if is_admin(user_id, group_id):
                markup.add(types.InlineKeyboardButton(f"📍 {title[:30]}", callback_data=f"mng_{group_id}"))
        
        if markup.keyboard:
            markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
            bot.edit_message_text("📂 **Manage Groups:**", chat_id, message_id, reply_markup=markup)
        else:
            bot.edit_message_text("📭 No groups available for you to manage.", chat_id, message_id)
    
    elif call.data.startswith("mng_"):
        if not is_admin(user_id):
            return
        
        target_id = int(call.data.split("_")[1])
        if not is_admin(user_id, target_id):
            bot.answer_callback_query(call.id, "You don't have permission to manage this group.", show_alert=True)
            return
        
        group_info = ""
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT title FROM groups WHERE chat_id = ?', (target_id,))
            res = cursor.fetchone()
            if res:
                group_info = res[0]
            conn.close()
        
        bot.edit_message_text(f"⚙️ **Group Settings for:** {group_info}\n🆔 `{target_id}`", 
                            chat_id, message_id, reply_markup=group_control_keyboard(target_id), parse_mode="Markdown")
    
    elif call.data.startswith("tog_"):
        if not is_admin(user_id):
            return
        
        parts = call.data.split("_")
        setting_type = parts[1]
        target_id = int(parts[2])
        
        if not is_admin(user_id, target_id):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True)
            return
        
        key_map = {'m': 'maintenance', 'l': 'link_filter', 's': 'bot_status'}
        new_val = toggle_setting(target_id, key_map[setting_type])
        
        bot.edit_message_reply_markup(chat_id, message_id, reply_markup=group_control_keyboard(target_id))
    
    elif call.data.startswith("leave_"):
        if not is_admin(user_id) or user_id != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "Only Super Admin can remove bot from groups.", show_alert=True)
            return
        
        target_id = int(call.data.split("_")[1])
        leave_msg = get_setting(target_id, 'leave_msg')
        
        try:
            # Send leave message
            if leave_msg:
                bot.send_message(target_id, leave_msg)
            
            # Leave group
            bot.leave_chat(target_id)
            
            # Remove from database
            with db_lock:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('DELETE FROM groups WHERE chat_id = ?', (target_id,))
                conn.commit()
                conn.close()
            
            bot.edit_message_text(f"✅ Successfully left group `{target_id}`", chat_id, message_id, parse_mode="Markdown")
        except Exception as e:
            bot.answer_callback_query(call.id, f"Failed to leave group: {str(e)}", show_alert=True)
    
    elif call.data == "set_leave_msg":
        if not is_admin(user_id) or user_id != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "Only Super Admin can set leave message.", show_alert=True)
            return
        
        msg = bot.send_message(chat_id, "✍️ Please send the leave message (emojis allowed):")
        bot.register_next_step_handler(msg, process_set_leave_msg)
    
    elif call.data == "bc_all":
        if not is_admin(user_id) or user_id != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "Only Super Admin can broadcast globally.", show_alert=True)
            return
        
        msg = bot.send_message(chat_id, "📢 Send message for global broadcast:")
        bot.register_next_step_handler(msg, process_global_broadcast)
    
    elif call.data.startswith("bc_"):
        if not is_admin(user_id):
            return
        
        target_id = int(call.data.split("_")[1])
        if not is_admin(user_id, target_id):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True)
            return
        
        msg = bot.send_message(chat_id, f"📢 Send message for group broadcast:")
        bot.register_next_step_handler(msg, process_group_broadcast, target_id)
    
    elif call.data == "inbox_list":
        if not is_admin(user_id):
            return
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, username, first_name, last_seen FROM users ORDER BY last_seen DESC LIMIT 30')
            users = cursor.fetchall()
            conn.close()
        
        if not users:
            bot.edit_message_text("📭 No users found.", chat_id, message_id)
            return
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        for u in users:
            user_id_db, username, first_name, last_seen = u
            display_name = username if username else first_name if first_name else f"User {user_id_db}"
            button_text = f"👤 {display_name[:15]}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=f"view_user_{user_id_db}"))
        
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📥 **Recent Users:** (Last 30)", chat_id, message_id, reply_markup=markup)
    
    elif call.data.startswith("view_user_"):
        if not is_admin(user_id):
            return
        
        target_user_id = int(call.data.split("_")[2])
        user_info = get_user_info(target_user_id)
        
        if not user_info:
            bot.answer_callback_query(call.id, "User not found.", show_alert=True)
            return
        
        user_text = f"👤 **User Information**\n\n"
        user_text += f"🆔 ID: `{target_user_id}`\n"
        user_text += f"📛 Name: {user_info['first_name']}\n"
        user_text += f"📱 Username: @{user_info['username']}\n"
        user_text += f"⏰ Last Seen: {user_info['last_seen']}\n"
        user_text += f"📞 Total Requests: {user_info['chat_requests']}\n"
        user_text += f"🚫 Status: {'Banned' if user_info['is_banned'] else 'Active'}"
        
        bot.edit_message_text(user_text, chat_id, message_id, 
                            reply_markup=user_menu_keyboard(target_user_id), parse_mode="Markdown")
    
    elif call.data.startswith("toggle_ban_"):
        if not is_admin(user_id):
            return
        
        target_user_id = int(call.data.split("_")[2])
        new_status = toggle_ban_user(target_user_id)
        
        if new_status is not None:
            status_text = "banned" if new_status == 1 else "unbanned"
            bot.answer_callback_query(call.id, f"User {status_text} successfully.")
            
            # Update the message
            user_info = get_user_info(target_user_id)
            user_text = f"👤 **User Information**\n\n"
            user_text += f"🆔 ID: `{target_user_id}`\n"
            user_text += f"📛 Name: {user_info['first_name']}\n"
            user_text += f"📱 Username: @{user_info['username']}\n"
            user_text += f"⏰ Last Seen: {user_info['last_seen']}\n"
            user_text += f"📞 Total Requests: {user_info['chat_requests']}\n"
            user_text += f"🚫 Status: {'Banned' if user_info['is_banned'] else 'Active'}"
            
            bot.edit_message_text(user_text, chat_id, message_id, 
                                reply_markup=user_menu_keyboard(target_user_id), parse_mode="Markdown")
    
    elif call.data.startswith("start_chat_"):
        if not is_admin(user_id):
            return
        
        target_user_id = int(call.data.split("_")[2])
        
        # Start session
        active_sessions[user_id] = target_user_id
        active_sessions[target_user_id] = user_id
        
        # Notify admin
        bot.edit_message_text(f"💬 **Chat session started**\n\nYou are now chatting with user `{target_user_id}`.\n\nSend messages normally to communicate.", 
                            chat_id, message_id, parse_mode="Markdown")
        
        # Notify user
        try:
            bot.send_message(target_user_id, "💬 An admin has started a chat session with you. You can now chat directly.")
        except:
            pass
    
    elif call.data.startswith("send_msg_"):
        if not is_admin(user_id):
            return
        
        target_user_id = int(call.data.split("_")[2])
        msg = bot.send_message(chat_id, f"✍️ Send a message to user `{target_user_id}`:")
        bot.register_next_step_handler(msg, process_send_message, target_user_id)
    
    elif call.data == "add_admin":
        if not is_admin(user_id) or user_id != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "Only Super Admin can add admins.", show_alert=True)
            return
        
        msg = bot.send_message(chat_id, "🆔 Send User ID to add as admin:")
        bot.register_next_step_handler(msg, process_add_admin_step1)
    
    elif call.data == "admin_list":
        if not is_admin(user_id):
            return
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, target_group FROM admins')
            admins = cursor.fetchall()
            conn.close()
        
        admin_text = "📋 **Admin List:**\n\n"
        for admin in admins:
            admin_id, target_group = admin
            admin_text += f"• `{admin_id}` - Group: `{target_group if target_group != 0 else 'All'}`\n"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text(admin_text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data == "del_admin_list":
        if not is_admin(user_id) or user_id != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "Only Super Admin can remove admins.", show_alert=True)
            return
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM admins WHERE user_id != ?', (SUPER_ADMIN,))
            admins = cursor.fetchall()
            conn.close()
        
        if not admins:
            bot.edit_message_text("📭 No admins to remove.", chat_id, message_id)
            return
        
        markup = types.InlineKeyboardMarkup()
        for admin in admins:
            markup.add(types.InlineKeyboardButton(f"Remove Admin {admin[0]}", callback_data=f"rm_adm_{admin[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        
        bot.edit_message_text("🗑 **Select Admin to Remove:**", chat_id, message_id, reply_markup=markup)
    
    elif call.data.startswith("rm_adm_"):
        if not is_admin(user_id) or user_id != SUPER_ADMIN:
            return
        
        admin_id = int(call.data.split("_")[2])
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
            conn.commit()
            conn.close()
        
        bot.edit_message_text(f"✅ Admin `{admin_id}` removed successfully.", 
                            chat_id, message_id, reply_markup=main_admin_keyboard(user_id), parse_mode="Markdown")

# ================= NEXT STEP HANDLERS =================
def process_set_leave_msg(message):
    try:
        new_msg = message.text
        if not new_msg or len(new_msg) > 1000:
            bot.send_message(message.chat.id, "❌ Please send a valid message (max 1000 characters).")
            return
        
        # Update global leave message by updating all groups
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE groups SET leave_msg = ?', (new_msg,))
            conn.commit()
            conn.close()
        
        bot.send_message(message.chat.id, f"✅ Leave message updated globally:\n\n`{new_msg}`", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {str(e)}")

def process_add_admin_step1(message):
    try:
        new_id = int(message.text)
        msg = bot.send_message(message.chat.id, "📍 Send Group ID for this admin (send `0` for all groups):")
        bot.register_next_step_handler(msg, process_add_admin_step2, new_id)
    except:
        bot.send_message(message.chat.id, "❌ Invalid User ID.")

def process_add_admin_step2(message, new_id):
    try:
        target_gid = int(message.text)
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO admins (user_id, target_group) VALUES (?, ?)', 
                         (new_id, target_gid))
            conn.commit()
            conn.close()
        
        scope = "all groups" if target_gid == 0 else f"group {target_gid}"
        bot.send_message(message.chat.id, f"✅ Admin `{new_id}` added successfully for {scope}.")
    except:
        bot.send_message(message.chat.id, "❌ Invalid Group ID.")

def process_group_broadcast(message, target_id):
    try:
        if message.text:
            bot.send_message(target_id, message.text, parse_mode="Markdown")
        elif message.photo:
            bot.send_photo(target_id, message.photo[-1].file_id, caption=message.caption)
        elif message.video:
            bot.send_video(target_id, message.video.file_id, caption=message.caption)
        elif message.document:
            bot.send_document(target_id, message.document.file_id, caption=message.caption)
        
        bot.send_message(message.chat.id, "✅ Broadcast sent successfully!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Failed to send broadcast: {str(e)}")

def process_global_broadcast(message):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        groups = cursor.execute('SELECT chat_id FROM groups').fetchall()
        conn.close()
    
    success = 0
    failed = 0
    
    for group in groups:
        try:
            if message.text:
                bot.send_message(group[0], message.text, parse_mode="Markdown")
            elif message.photo:
                bot.send_photo(group[0], message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                bot.send_video(group[0], message.video.file_id, caption=message.caption)
            elif message.document:
                bot.send_document(group[0], message.document.file_id, caption=message.caption)
            success += 1
        except:
            failed += 1
    
    bot.send_message(message.chat.id, 
                   f"📊 **Broadcast Results:**\n✅ Success: {success}\n❌ Failed: {failed}")

def process_send_message(message, target_user_id):
    try:
        if message.text:
            bot.send_message(target_user_id, f"📨 **Message from Admin:**\n\n{message.text}")
            bot.send_message(message.chat.id, f"✅ Message sent to user `{target_user_id}`", parse_mode="Markdown")
        elif message.photo:
            bot.send_photo(target_user_id, message.photo[-1].file_id, 
                         caption=f"📨 Message from Admin:\n\n{message.caption}")
            bot.send_message(message.chat.id, f"✅ Photo sent to user `{target_user_id}`", parse_mode="Markdown")
        elif message.video:
            bot.send_video(target_user_id, message.video.file_id, 
                         caption=f"📨 Message from Admin:\n\n{message.caption}")
            bot.send_message(message.chat.id, f"✅ Video sent to user `{target_user_id}`", parse_mode="Markdown")
        elif message.document:
            bot.send_document(target_user_id, message.document.file_id, 
                            caption=f"📨 Message from Admin:\n\n{message.caption}")
            bot.send_message(message.chat.id, f"✅ Document sent to user `{target_user_id}`", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Failed to send message: {str(e)}")

# ================= RUN BOT =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    print("🤖 Bot is starting...")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            print(f"⚠️ Polling error: {e}")
            time.sleep(5)
