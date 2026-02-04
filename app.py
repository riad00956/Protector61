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

active_sessions = {} # {user_id: admin_id}
cooldowns = {} # {user_id: timestamp}

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
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins 
                          (user_id INTEGER PRIMARY KEY, target_group INTEGER DEFAULT 0, perms TEXT)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (chat_id INTEGER PRIMARY KEY, maintenance INTEGER DEFAULT 0, 
                           link_filter INTEGER DEFAULT 1, bot_status INTEGER DEFAULT 1)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS logs (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                          (user_id INTEGER PRIMARY KEY, username TEXT, last_msg TEXT, is_banned INTEGER DEFAULT 0)''')
        conn.commit()
        conn.close()

init_db()

# --- Helpers ---
def get_setting(chat_id, key):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'SELECT {key} FROM settings WHERE chat_id = ?', (chat_id,))
        res = cursor.fetchone()
        conn.close()
        # Default settings if not exists
        if res is None:
            return 0 if key == 'maintenance' else 1
        return res[0]

def toggle_setting(chat_id, key):
    current = get_setting(chat_id, key)
    new_val = 1 if current == 0 else 0
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO settings (chat_id) VALUES (?)', (chat_id,))
        cursor.execute(f'UPDATE settings SET {key} = ? WHERE chat_id = ?', (new_val, chat_id))
        conn.commit()
        conn.close()
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

def is_admin(user_id):
    if user_id == SUPER_ADMIN: return True
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        conn.close()
        return True if res else False

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
    else:
        # For Sub-Admins
        markup.add(types.InlineKeyboardButton("📂 View Groups", callback_data="list_groups"))
        markup.add(types.InlineKeyboardButton("📥 Inbox Messages", callback_data="inbox_list"))
    return markup

def group_control_keyboard(chat_id):
    m = get_setting(chat_id, 'maintenance')
    l = get_setting(chat_id, 'link_filter')
    s = get_setting(chat_id, 'bot_status')
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"{'🔴' if m else '🟢'} Maintenance: {'ON' if m else 'OFF'}", callback_data=f"tog_m_{chat_id}"),
        types.InlineKeyboardButton(f"{'🟢' if l else '🔴'} Link Filter: {'ON' if l else 'OFF'}", callback_data=f"tog_l_{chat_id}"),
        types.InlineKeyboardButton(f"{'✅' if s else '⏸'} Bot Status: {'Active' if s else 'Paused'}", callback_data=f"tog_s_{chat_id}"),
        types.InlineKeyboardButton("📢 Group Broadcast", callback_data=f"bc_{chat_id}"),
        types.InlineKeyboardButton("⬅️ Back", callback_data="list_groups")
    )
    return markup

def user_request_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🙋 Request to Chat", callback_data="req_chat"))
    return markup

# ================= HANDLERS =================
@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document'])
def handle_all(message):
    uid = message.from_user.id
    cid = message.chat.id
    log_message()

    if message.chat.type == "private":
        # Handle Active Chat Session
        if uid in active_sessions:
            target_id = active_sessions[uid]
            try:
                if message.text: bot.send_message(target_id, message.text)
                elif message.photo: bot.send_photo(target_id, message.photo[-1].file_id, caption=message.caption)
                elif message.video: bot.send_video(target_id, message.video.file_id, caption=message.caption)
                elif message.document: bot.send_document(target_id, message.document.file_id, caption=message.caption)
            except: 
                bot.send_message(uid, "❌ Failed to deliver message. Session may be broken.")
            return

        # Admin Command
        if message.text == "/admin":
            if is_admin(uid):
                bot.send_message(cid, "🏮 **Admin Control Panel**", reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")
            else:
                bot.send_message(cid, "❌ Access Denied.")
            return
        
        # Regular User Start or Message
        if not is_admin(uid):
            username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
            with db_lock:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('INSERT OR REPLACE INTO users (user_id, username, last_msg) VALUES (?, ?, ?)', 
                               (uid, username, message.text[:50] if message.text else "[Media]"))
                conn.commit()
                conn.close()
            
            if message.text == "/start":
                bot.send_message(cid, f"Hello {message.from_user.first_name}! Welcome.", reply_markup=user_request_keyboard())
            else:
                bot.send_message(cid, "⚠️ You don't have an active session.", reply_markup=user_request_keyboard())

    else:
        # Group Logic
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('INSERT OR REPLACE INTO groups VALUES (?, ?)', (cid, message.chat.title))
            conn.commit()
            conn.close()

        if get_setting(cid, 'bot_status') == 0: return
        if get_setting(cid, 'maintenance') == 1 and not is_admin(uid): 
            try: bot.delete_message(cid, message.message_id)
            except: pass
            return
            
        if get_setting(cid, 'link_filter') == 1:
            text = message.text or message.caption or ""
            if ("http" in text.lower() or "t.me" in text.lower()) and not is_admin(uid):
                try:
                    bot.delete_message(cid, message.message_id)
                    bot.send_message(cid, f"@{message.from_user.username} হ্যাঁ ভাই🙂, উরাধুরা লিংক দাও, জায়গাটা কি তোমার বাপ কিনা রাখছে? 😒")
                except: pass

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    # User Request Chat
    if call.data == "req_chat":
        now = time.time()
        if uid in cooldowns and now - cooldowns[uid] < 300: # 5 mins cooldown
            bot.answer_callback_query(call.id, "Please wait 5 mins before next request.", show_alert=True)
            return
        cooldowns[uid] = now
        bot.edit_message_text("✅ Your request has been sent to admins.", cid, mid)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Accept Chat", callback_data=f"start_sess_{uid}"))
        bot.send_message(SUPER_ADMIN, f"🙋 **Chat Request!**\nName: {call.from_user.first_name}\nID: `{uid}`", reply_markup=markup, parse_mode="Markdown")
        return

    # Check Admin Authority for other callbacks
    if not is_admin(uid):
        bot.answer_callback_query(call.id, "❌ You are not authorized.", show_alert=True)
        return

    # Back to Main Menu
    if call.data == "back_main":
        bot.edit_message_text("🏮 **Admin Control Panel**", cid, mid, reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")

    # Group Management
    elif call.data == "list_groups":
        with db_lock:
            conn = get_db_connection()
            rows = conn.cursor().execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for row in rows: 
            markup.add(types.InlineKeyboardButton(f"📍 {row[1]}", callback_data=f"mng_{row[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📂 **Manage Groups:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("mng_"):
        target_id = int(call.data.split("_")[1])
        bot.edit_message_text(f"⚙️ **Group Settings for:** `{target_id}`", cid, mid, reply_markup=group_control_keyboard(target_id), parse_mode="Markdown")

    elif call.data.startswith("tog_"):
        parts = call.data.split("_")
        key_code = parts[1]
        target_id = int(parts[2])
        key_map = {'m': 'maintenance', 'l': 'link_filter', 's': 'bot_status'}
        toggle_setting(target_id, key_map[key_code])
        bot.edit_message_reply_markup(cid, mid, reply_markup=group_control_keyboard(target_id))

    # Broadcast
    elif call.data.startswith("bc_"):
        target_id = call.data.split("_")[1]
        msg = bot.send_message(cid, "✍️ Type the message you want to broadcast to this group:")
        bot.register_next_step_handler(msg, process_group_broadcast, target_id)

    elif call.data == "bc_all":
        msg = bot.send_message(cid, "✍️ Type the message for Global Broadcast:")
        bot.register_next_step_handler(msg, process_global_broadcast)

    # Inbox System
    elif call.data == "inbox_list":
        with db_lock:
            conn = get_db_connection()
            users = conn.cursor().execute('SELECT user_id, username FROM users ORDER BY user_id DESC LIMIT 20').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for u in users: 
            markup.add(types.InlineKeyboardButton(f"👤 {u[1]}", callback_data=f"usr_{u[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📥 **Recent Users:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("usr_"):
        target_uid = int(call.data.split("_")[1])
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Start Session", callback_data=f"start_sess_{target_uid}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="inbox_list"))
        bot.edit_message_text(f"👤 **User Detail:**\nID: `{target_uid}`", cid, mid, reply_markup=markup, parse_mode="Markdown")

    # Session Control
    elif call.data.startswith("start_sess_"):
        target_uid = int(call.data.split("_")[2])
        active_sessions[uid] = target_uid
        active_sessions[target_uid] = uid
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🛑 End Session", callback_data=f"end_sess_{target_uid}"))
        bot.send_message(uid, f"✅ Session started with `{target_uid}`. You can chat now.", reply_markup=markup, parse_mode="Markdown")
        bot.send_message(target_uid, "✅ An admin is now chatting with you.")

    elif call.data.startswith("end_sess_"):
        target_uid = int(call.data.split("_")[2])
        active_sessions.pop(uid, None)
        active_sessions.pop(target_uid, None)
        bot.edit_message_text("❌ Session ended.", cid, mid)
        bot.send_message(target_uid, "⚠️ Session has been ended by the admin.", reply_markup=user_request_keyboard())

    # Admin Management
    elif call.data == "admin_list":
        with db_lock:
            conn = get_db_connection()
            admins = conn.cursor().execute('SELECT user_id FROM admins').fetchall()
            conn.close()
        text = "📋 **Admin List:**\n\n"
        for a in admins: text += f"• `{a[0]}`\n"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text(text, cid, mid, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "add_admin":
        msg = bot.send_message(cid, "🆔 Send the User ID of the new Admin:")
        bot.register_next_step_handler(msg, process_add_admin)

    elif call.data == "del_admin_list":
        with db_lock:
            conn = get_db_connection()
            admins = conn.cursor().execute('SELECT user_id FROM admins').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for a in admins: 
            markup.add(types.InlineKeyboardButton(f"❌ Remove {a[0]}", callback_data=f"rm_adm_{a[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("➖ **Select Admin to Remove:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("rm_adm_"):
        adm_id = int(call.data.split("_")[2])
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('DELETE FROM admins WHERE user_id = ?', (adm_id,))
            conn.commit()
            conn.close()
        bot.answer_callback_query(call.id, "Admin Removed Successfully!")
        bot.edit_message_text("✅ Done.", cid, mid, reply_markup=main_admin_keyboard(uid))

# ================= HELPERS FOR NEXT STEPS =================
def process_group_broadcast(message, target_id):
    try:
        bot.send_message(target_id, message.text, parse_mode="Markdown")
        bot.send_message(message.chat.id, "✅ Broadcast sent to group!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Failed: {e}")

def process_global_broadcast(message):
    with db_lock:
        conn = get_db_connection()
        groups = conn.cursor().execute('SELECT chat_id FROM groups').fetchall()
        conn.close()
    
    success = 0
    for g in groups:
        try:
            bot.send_message(g[0], message.text, parse_mode="Markdown")
            success += 1
        except: continue
    bot.send_message(message.chat.id, f"✅ Global broadcast completed! Sent to {success} groups.")

def process_add_admin(message):
    try:
        new_id = int(message.text)
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (new_id,))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, f"✅ `{new_id}` is now an admin.", parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Invalid ID format! Please send a numeric ID.")

# ================= RUN =================
if __name__ == "__main__":
    # Start Flask Web Server
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Start Bot Polling
    print("Bot is starting...")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)
