import telebot
import sqlite3
import io
import datetime
import requests
import json
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
        cursor.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, access_level INTEGER DEFAULT 1)')
        cursor.execute('CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT, assigned_admin INTEGER)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (chat_id INTEGER PRIMARY KEY, maintenance INTEGER DEFAULT 0, 
                           link_filter INTEGER DEFAULT 1, bot_status INTEGER DEFAULT 1,
                           welcome_msg TEXT DEFAULT "Welcome to the group!")''')
        cursor.execute('CREATE TABLE IF NOT EXISTS logs (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_requests 
                          (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                           status TEXT DEFAULT "pending", admin_id INTEGER, 
                           request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS active_chats 
                          (user_id INTEGER PRIMARY KEY, admin_id INTEGER,
                           start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, reason TEXT)')
        conn.commit()
        conn.close()

init_db()

def get_setting(chat_id, key):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'SELECT {key} FROM settings WHERE chat_id = ?', (chat_id,))
        res = cursor.fetchone()
        conn.close()
        if res: return res[0]
        if key == 'welcome_msg': return "Welcome to the group!"
        return 1 if key != 'maintenance' else 0

def update_setting(chat_id, key, value):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'INSERT OR IGNORE INTO settings (chat_id) VALUES (?)', (chat_id,))
        cursor.execute(f'UPDATE settings SET {key} = ? WHERE chat_id = ?', (value, chat_id))
        conn.commit()
        conn.close()

def toggle_setting(chat_id, key):
    current = get_setting(chat_id, key)
    new_val = 1 if current == 0 else 0
    update_setting(chat_id, key, new_val)
    return new_val

def log_message():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO logs VALUES (?, 0)', (today,))
        cursor.execute('UPDATE logs SET count = count + 1 WHERE date = ?', (today,))
        conn.commit()
        conn.close()

def is_admin(user_id, chat_id=None):
    if user_id == SUPER_ADMIN: return 3  # Super Admin level
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT access_level FROM admins WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        if not res: return 0
        
        # Check group assignment if chat_id provided
        if chat_id:
            cursor.execute('SELECT assigned_admin FROM groups WHERE chat_id = ?', (chat_id,))
            group_admin = cursor.fetchone()
            if group_admin and group_admin[0] and group_admin[0] != user_id:
                return 0  # Not assigned to this group
        
        conn.close()
        return res[0]

def get_assigned_groups(admin_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id, title FROM groups WHERE assigned_admin = ?', (admin_id,))
        groups = cursor.fetchall()
        conn.close()
    return groups

def generate_log_graph():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM logs ORDER BY date DESC LIMIT 7')
        data = cursor.fetchall()[::-1]
        conn.close()
    if not data: return None
    labels = [row[0][-5:] for row in data]
    values = [row[1] for row in data]
    chart_config = {"type": "line", "data": {"labels": labels, "datasets": [{"label": "Activity", "data": values, "fill": True, "backgroundColor": "rgba(54, 162, 235, 0.2)", "borderColor": "rgb(54, 162, 235)", "tension": 0.4}]}}
    config_str = json.dumps(chart_config)
    chart_url = f"https://quickchart.io/chart?c={config_str}&width=800&height=400"
    try:
        response = requests.get(chart_url, timeout=10)
        return io.BytesIO(response.content) if response.status_code == 200 else None
    except: return None

# ================= KEYBOARDS (ENGLISH) =================
def main_admin_keyboard(admin_level=1):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = [
        types.InlineKeyboardButton("📊 Analytics Dashboard", callback_data="show_graph"),
        types.InlineKeyboardButton("📂 Group Manager", callback_data="list_groups"),
        types.InlineKeyboardButton("👥 Admin Management", callback_data="admin_menu"),
        types.InlineKeyboardButton("🔄 System Settings", callback_data="system_settings"),
        types.InlineKeyboardButton("📨 Chat Requests", callback_data="view_requests"),
        types.InlineKeyboardButton("🚫 Banned Users", callback_data="banned_list")
    ]
    
    markup.add(*buttons[:2])
    markup.add(*buttons[2:4])
    markup.add(*buttons[4:6])
    
    if admin_level >= 2:
        markup.add(types.InlineKeyboardButton("⚙️ Advanced Controls", callback_data="advanced_menu"))
    
    return markup

def system_settings_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📢 Global Broadcast", callback_data="bc_all"),
        types.InlineKeyboardButton("📋 View All Groups", callback_data="view_all_groups"),
        types.InlineKeyboardButton("🛠️ Maintenance Mode", callback_data="toggle_maintenance"),
        types.InlineKeyboardButton("📊 Activity Logs", callback_data="activity_logs"),
        types.InlineKeyboardButton("⬅️ Back", callback_data="back_main")
    )
    return markup

def admin_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
        types.InlineKeyboardButton("➖ Remove Admin", callback_data="del_admin_list"),
        types.InlineKeyboardButton("📋 Admin List", callback_data="admin_list"),
        types.InlineKeyboardButton("🎚️ Set Admin Level", callback_data="set_admin_level"),
        types.InlineKeyboardButton("📝 Assign Group", callback_data="assign_group"),
        types.InlineKeyboardButton("⬅️ Back", callback_data="back_main")
    )
    return markup

def group_control_keyboard(chat_id, admin_level):
    m = get_setting(chat_id, 'maintenance')
    l = get_setting(chat_id, 'link_filter')
    s = get_setting(chat_id, 'bot_status')
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{'🔴' if m else '🟢'} Maintenance", callback_data=f"tog_m_{chat_id}"),
        types.InlineKeyboardButton(f"{'🟢' if l else '🔴'} Link Filter", callback_data=f"tog_l_{chat_id}"),
        types.InlineKeyboardButton(f"{'✅' if s else '⏸'} Bot Status", callback_data=f"tog_s_{chat_id}"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data=f"bc_{chat_id}")
    )
    
    if admin_level >= 2:
        markup.add(
            types.InlineKeyboardButton("✏️ Welcome Msg", callback_data=f"welcome_{chat_id}"),
            types.InlineKeyboardButton("👥 Assign Admin", callback_data=f"assign_{chat_id}")
        )
    
    markup.add(
        types.InlineKeyboardButton("📊 Group Stats", callback_data=f"stats_{chat_id}"),
        types.InlineKeyboardButton("⬅️ Back", callback_data="list_groups")
    )
    return markup

def chat_request_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Accept", callback_data=f"accept_{user_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
    )
    return markup

def active_chat_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("🚪 End Chat", callback_data=f"endchat_{user_id}"),
        types.InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_{user_id}"),
        types.InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_{user_id}")
    )
    return markup

def start_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📞 Request Chat with Admin"))
    markup.add(types.KeyboardButton("📋 Bot Commands"))
    return markup

# ================= HANDLERS =================
@bot.message_handler(commands=['start'])
def start_command(message):
    uid = message.from_user.id
    cid = message.chat.id
    
    if message.chat.type == "private":
        bot.send_message(cid, "👋 Welcome! Use the buttons below:", reply_markup=start_keyboard())
        
        # Log chat request
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT status FROM chat_requests WHERE user_id = ?', (uid,))
            existing = cursor.fetchone()
            
            if not existing:
                cursor.execute('''INSERT INTO chat_requests (user_id, username, first_name, status) 
                                  VALUES (?, ?, ?, "pending")''',
                              (uid, message.from_user.username, message.from_user.first_name))
                conn.commit()
                
                # Notify super admin
                bot.send_message(
                    SUPER_ADMIN,
                    f"📨 New Chat Request!\n\n"
                    f"👤 User: {message.from_user.first_name}\n"
                    f"🆔 ID: {uid}\n"
                    f"📛 Username: @{message.from_user.username if message.from_user.username else 'N/A'}\n"
                    f"🕐 Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    reply_markup=chat_request_keyboard(uid)
                )
            conn.close()

@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document'])
def handle_all(message):
    uid = message.from_user.id
    cid = message.chat.id
    log_message()

    # Handle private chat messages
    if message.chat.type == "private":
        # Check if user is in active chat with admin
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT admin_id FROM active_chats WHERE user_id = ?', (uid,))
            active_chat = cursor.fetchone()
            conn.close()
        
        if active_chat:
            # Forward message to admin
            try:
                bot.send_message(
                    active_chat[0],
                    f"📩 From User {uid}:\n{message.text if message.text else '[Media Message]'}"
                )
            except:
                pass
            return
        
        # Handle "Request Chat with Admin" button
        if message.text == "📞 Request Chat with Admin":
            start_command(message)
            return
        
        # Handle admin commands
        if message.text == "/admin" and is_admin(uid):
            admin_level = is_admin(uid)
            bot.send_message(cid, "🔧 **Admin Control Panel**", 
                           reply_markup=main_admin_keyboard(admin_level), 
                           parse_mode="Markdown")
            return
    
    # Group handling
    if message.chat.type != "private":
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO groups VALUES (?, ?, ?)', 
                         (cid, message.chat.title, None))
            conn.commit()
            conn.close()

        # ১. বট স্ট্যাটাস চেক
        if get_setting(cid, 'bot_status') == 0:
            return

        # ২. মেইনটেন্যান্স চেক
        if get_setting(cid, 'maintenance') == 1 and not is_admin(uid, cid):
            return

        # ৩. লিংক ফিল্টার (বাংলায় সতর্কবার্তা)
        if get_setting(cid, 'link_filter') == 1:
            text = message.text or message.caption or ""
            if any(link in text for link in ["http://", "https://", "t.me/", "www."]) and not is_admin(uid, cid):
                try:
                    bot.delete_message(cid, message.message_id)
                    warning_msg = f"🚫 {message.from_user.first_name}, লিংক শেয়ার করা নিষিদ্ধ! ❌\n\n"
                    warning_msg += f"📛 User ID: `{uid}`\n"
                    warning_msg += f"⏰ Time: {datetime.datetime.now().strftime('%H:%M:%S')}"
                    
                    bot.send_message(cid, warning_msg, parse_mode="Markdown")
                except Exception as e:
                    print(f"Error deleting message: {e}")

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    admin_level = is_admin(uid)
    if admin_level == 0 and not call.data.startswith("accept_") and not call.data.startswith("reject_"):
        bot.answer_callback_query(call.id, "⚠️ Access Denied!")
        return

    if call.data == "show_graph":
        bot.answer_callback_query(call.id, "📈 Generating graph...")
        graph = generate_log_graph()
        if graph: 
            bot.send_photo(cid, graph, caption="📊 **Activity Analytics (Last 7 Days)**", parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ No data available!")
        
    elif call.data == "list_groups":
        groups = get_assigned_groups(uid) if admin_level < 3 else []
        if admin_level < 3 and groups:
            markup = types.InlineKeyboardMarkup()
            for chat_id, title in groups:
                markup.add(types.InlineKeyboardButton(f"📍 {title}", callback_data=f"mng_{chat_id}"))
        else:
            with db_lock:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT chat_id, title FROM groups')
                rows = cursor.fetchall()
                conn.close()
            
            markup = types.InlineKeyboardMarkup()
            for row in rows:
                markup.add(types.InlineKeyboardButton(f"📍 {row[1]}", callback_data=f"mng_{row[0]}"))
        
        markup.add(types.InlineKeyboardButton("➕ Add New Group", callback_data="add_group"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        
        bot.edit_message_text("🏢 **Select a group to manage:**", cid, mid, 
                             reply_markup=markup, parse_mode="Markdown")

    elif call.data.startswith("mng_"):
        target_id = int(call.data.split("_")[1])
        bot.edit_message_text(f"⚙️ **Group Control Panel**\n\n📌 Group ID: `{target_id}`", 
                             cid, mid, parse_mode="Markdown", 
                             reply_markup=group_control_keyboard(target_id, admin_level))

    elif call.data.startswith("tog_"):
        _, key_code, target_id = call.data.split("_")
        key_map = {'m': 'maintenance', 'l': 'link_filter', 's': 'bot_status'}
        new_val = toggle_setting(int(target_id), key_map[key_code])
        status_text = "ON ✅" if new_val == 1 else "OFF ❌"
        bot.answer_callback_query(call.id, f"Status changed to {status_text}")
        bot.edit_message_reply_markup(cid, mid, 
                                     reply_markup=group_control_keyboard(int(target_id), admin_level))

    elif call.data == "admin_menu":
        bot.edit_message_text("👥 **Admin Management Panel**", cid, mid,
                             reply_markup=admin_management_keyboard(), parse_mode="Markdown")

    elif call.data == "add_admin":
        if uid != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "❌ Super Admin only!")
            return
        msg = bot.send_message(cid, "🆔 Send the **User ID** of the new admin:")
        bot.register_next_step_handler(msg, process_add_admin)

    elif call.data == "del_admin_list":
        if uid != SUPER_ADMIN: 
            bot.answer_callback_query(call.id, "❌ Super Admin only!")
            return
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM admins WHERE user_id != ?', (SUPER_ADMIN,))
            admins = cursor.fetchall()
            conn.close()
        
        if not admins:
            bot.answer_callback_query(call.id, "📭 No other admins found!")
            return
        
        markup = types.InlineKeyboardMarkup()
        for a in admins:
            markup.add(types.InlineKeyboardButton(f"❌ Remove Admin {a[0]}", 
                                                callback_data=f"rem_{a[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="admin_menu"))
        bot.edit_message_text("🗑️ **Select admin to remove:**", cid, mid, 
                             reply_markup=markup, parse_mode="Markdown")

    elif call.data.startswith("rem_"):
        if uid != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "❌ Super Admin only!")
            return
        
        target_uid = int(call.data.split("_")[1])
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM admins WHERE user_id = ?', (target_uid,))
            conn.commit()
            conn.close()
        
        bot.answer_callback_query(call.id, "✅ Admin removed successfully!")
        callback_logic(call)

    elif call.data == "admin_list":
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, access_level FROM admins')
            admins = cursor.fetchall()
            conn.close()
        
        text = "👑 **Administrators List:**\n\n"
        text += f"• 👑 Super Admin: `{SUPER_ADMIN}` (Level 3)\n"
        
        for a in admins:
            level_text = "Full" if a[1] == 2 else "Basic"
            text += f"• 👤 Admin `{a[0]}`: {level_text} Access (Level {a[1]})\n"
        
        bot.send_message(cid, text, parse_mode="Markdown")

    elif call.data == "view_requests":
        if uid != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "❌ Super Admin only!")
            return
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''SELECT user_id, username, first_name, request_time 
                              FROM chat_requests 
                              WHERE status = "pending" 
                              ORDER BY request_time DESC''')
            requests = cursor.fetchall()
            conn.close()
        
        if not requests:
            bot.send_message(cid, "📭 No pending chat requests.")
            return
        
        text = "📨 **Pending Chat Requests:**\n\n"
        for req in requests:
            text += f"👤 {req[2]} (@{req[1] if req[1] else 'N/A'})\n"
            text += f"🆔 ID: `{req[0]}`\n"
            text += f"🕐 Requested: {req[3]}\n"
            text += "─" * 20 + "\n"
        
        bot.send_message(cid, text, parse_mode="Markdown")

    elif call.data.startswith("accept_"):
        if uid != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "❌ Super Admin only!")
            return
        
        user_id = int(call.data.split("_")[1])
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Get user info
            cursor.execute('SELECT first_name FROM chat_requests WHERE user_id = ?', (user_id,))
            user_info = cursor.fetchone()
            
            # Update status
            cursor.execute('UPDATE chat_requests SET status = "accepted", admin_id = ? WHERE user_id = ?', 
                         (uid, user_id))
            
            # Create active chat
            cursor.execute('INSERT OR REPLACE INTO active_chats (user_id, admin_id) VALUES (?, ?)', 
                         (user_id, uid))
            
            conn.commit()
            conn.close()
        
        # Notify user
        try:
            bot.send_message(user_id, "✅ **Your chat request has been accepted!**\n\n"
                                    "You can now chat directly with the admin. Type your message below.")
        except:
            pass
        
        # Update admin message
        bot.edit_message_text(f"✅ Chat request accepted!\n\n👤 User ID: `{user_id}`\n📛 Name: {user_info[0]}", 
                             cid, mid, parse_mode="Markdown",
                             reply_markup=active_chat_keyboard(user_id))
        
        bot.answer_callback_query(call.id, "✅ Chat session started!")

    elif call.data.startswith("reject_"):
        if uid != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "❌ Super Admin only!")
            return
        
        user_id = int(call.data.split("_")[1])
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE chat_requests SET status = "rejected" WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
        
        # Notify user
        try:
            bot.send_message(user_id, "❌ Your chat request has been rejected by the admin.")
        except:
            pass
        
        bot.edit_message_text(f"❌ Chat request rejected!\n\nUser ID: `{user_id}`", 
                             cid, mid, parse_mode="Markdown")
        bot.answer_callback_query(call.id, "Request rejected!")

    elif call.data.startswith("endchat_"):
        user_id = int(call.data.split("_")[1])
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM active_chats WHERE user_id = ?', (user_id,))
            cursor.execute('UPDATE chat_requests SET status = "closed" WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
        
        # Notify user
        try:
            bot.send_message(user_id, "🔚 The chat session has been ended by the admin.")
        except:
            pass
        
        bot.edit_message_text(f"🔚 Chat session ended!\n\nUser ID: `{user_id}`", 
                             cid, mid, parse_mode="Markdown")
        bot.answer_callback_query(call.id, "Chat ended!")

    elif call.data.startswith("ban_"):
        user_id = int(call.data.split("_")[1])
        
        msg = bot.send_message(cid, f"🚫 Enter ban reason for user `{user_id}`:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_ban_user, user_id)

    elif call.data == "system_settings":
        bot.edit_message_text("⚙️ **System Settings Panel**", cid, mid,
                             reply_markup=system_settings_keyboard(), parse_mode="Markdown")

    elif call.data == "bc_all":
        if admin_level < 2:
            bot.answer_callback_query(call.id, "❌ Requires admin level 2+")
            return
        
        msg = bot.send_message(cid, "📢 Send your **Global Broadcast Message**:")
        bot.register_next_step_handler(msg, start_bc, "all")

    elif call.data.startswith("bc_"):
        target_id = call.data.split("_")[1]
        msg = bot.send_message(cid, f"📢 Send broadcast message for group `{target_id}`:")
        bot.register_next_step_handler(msg, start_bc, target_id)

    elif call.data == "assign_group":
        if uid != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "❌ Super Admin only!")
            return
        
        msg = bot.send_message(cid, "📝 Send: `group_id admin_id`\nExample: `-100123456789 123456789`", 
                             parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_assign_group)

    elif call.data == "back_main":
        admin_level = is_admin(uid)
        bot.edit_message_text("🔧 **Admin Control Panel**", cid, mid, 
                             reply_markup=main_admin_keyboard(admin_level), 
                             parse_mode="Markdown")

# ================= HELPER FUNCTIONS =================
def process_add_admin(message):
    try:
        new_id = int(message.text)
        if new_id == SUPER_ADMIN:
            bot.send_message(message.chat.id, "❌ This user is already Super Admin!")
            return
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (new_id,))
            conn.commit()
            conn.close()
        
        bot.send_message(message.chat.id, f"✅ Admin added successfully!\nUser ID: `{new_id}`", 
                        parse_mode="Markdown")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid User ID format!")

def process_assign_group(message):
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Invalid format! Use: `group_id admin_id`")
            return
        
        group_id = int(parts[0])
        admin_id = int(parts[1])
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE groups SET assigned_admin = ? WHERE chat_id = ?', 
                         (admin_id, group_id))
            conn.commit()
            conn.close()
        
        bot.send_message(message.chat.id, f"✅ Group `{group_id}` assigned to admin `{admin_id}`", 
                        parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Invalid input!")

def process_ban_user(message, user_id):
    reason = message.text
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO banned_users VALUES (?, ?)', (user_id, reason))
        
        # End active chat if exists
        cursor.execute('DELETE FROM active_chats WHERE user_id = ?', (user_id,))
        cursor.execute('UPDATE chat_requests SET status = "banned" WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
    
    # Notify user
    try:
        bot.send_message(user_id, f"🚫 You have been banned!\nReason: {reason}")
    except:
        pass
    
    bot.send_message(message.chat.id, f"✅ User `{user_id}` banned!\nReason: {reason}", 
                    parse_mode="Markdown")

def start_bc(message, target):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if target == "all":
            cursor.execute('SELECT chat_id FROM groups')
            ids = [r[0] for r in cursor.fetchall()]
            target_name = "All Groups"
        else:
            ids = [int(target)]
            cursor.execute('SELECT title FROM groups WHERE chat_id = ?', (int(target),))
            group_info = cursor.fetchone()
            target_name = group_info[0] if group_info else f"Group {target}"
        
        conn.close()
    
    def send_task():
        success = 0
        failed = 0
        
        for tid in ids:
            try:
                if message.content_type == 'text':
                    bot.send_message(tid, message.text)
                elif message.content_type == 'photo':
                    bot.send_photo(tid, message.photo[-1].file_id, caption=message.caption)
                elif message.content_type == 'video':
                    bot.send_video(tid, message.video.file_id, caption=message.caption)
                elif message.content_type == 'document':
                    bot.send_document(tid, message.document.file_id, caption=message.caption)
                
                success += 1
                time.sleep(0.1)
            except Exception as e:
                failed += 1
                print(f"Failed to send to {tid}: {e}")
        
        # Send report
        report = f"📊 **Broadcast Report**\n\n"
        report += f"✅ Success: {success}\n"
        report += f"❌ Failed: {failed}\n"
        report += f"🎯 Target: {target_name}\n"
        report += f"📅 Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        bot.send_message(message.chat.id, report, parse_mode="Markdown")
    
    threading.Thread(target=send_task).start()
    bot.send_message(message.chat.id, "⏳ Broadcast started... You'll get a report when done.")

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    print("🤖 Bot is running with enhanced admin panel...")
    print(f"👑 Super Admin ID: {SUPER_ADMIN}")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=30)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)
