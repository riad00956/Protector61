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

active_sessions = {} # {user_id: admin_id}
cooldowns = {} # {user_id: timestamp}

# ================= DATABASE SYSTEM =================
db_lock = threading.Lock()

def get_db_connection():
    return sqlite3.connect('bot_final.db', check_same_thread=False)

def init_db():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins 
                          (user_id INTEGER PRIMARY KEY, target_group INTEGER DEFAULT 0)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (id INTEGER PRIMARY KEY DEFAULT 1, leave_msg TEXT DEFAULT "আমি বের হয়ে যাচ্ছি, ভালো থেকো।")''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS group_settings 
                          (chat_id INTEGER PRIMARY KEY, maintenance INTEGER DEFAULT 0, 
                           link_filter INTEGER DEFAULT 1, bot_status INTEGER DEFAULT 1)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                          (user_id INTEGER PRIMARY KEY, username TEXT, is_banned INTEGER DEFAULT 0)''')
        # লিভ মেসেজ ডিফল্ট সেট করা
        cursor.execute('INSERT OR IGNORE INTO settings (id, leave_msg) VALUES (1, "আমি বের হয়ে যাচ্ছি, ভালো থেকো।")')
        conn.commit()
        conn.close()

init_db()

# --- Helpers ---
def get_global_leave_msg():
    with db_lock:
        conn = get_db_connection()
        res = conn.execute('SELECT leave_msg FROM settings WHERE id = 1').fetchone()
        conn.close()
        return res[0] if res else "আমি বের হয়ে যাচ্ছি, ভালো থেকো।"

def is_banned(user_id):
    with db_lock:
        conn = get_db_connection()
        res = conn.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,)).fetchone()
        conn.close()
        return res[0] == 1 if res else False

def get_group_setting(chat_id, key):
    with db_lock:
        conn = get_db_connection()
        res = conn.execute(f'SELECT {key} FROM group_settings WHERE chat_id = ?', (chat_id,)).fetchone()
        conn.close()
        if res is None: return 1 if key != 'maintenance' else 0
        return res[0]

def is_admin(user_id, chat_id=None):
    if user_id == SUPER_ADMIN: return True
    with db_lock:
        conn = get_db_connection()
        res = conn.execute('SELECT target_group FROM admins WHERE user_id = ?', (user_id,)).fetchone()
        conn.close()
        if res:
            if chat_id and res[0] != 0 and res[0] != chat_id: return False
            return True
        return False

# ================= KEYBOARDS =================
def main_admin_keyboard(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("📂 Group Manager", callback_data="list_groups"),
               types.InlineKeyboardButton("📥 Inbox (Users)", callback_data="inbox_list"))
    if uid == SUPER_ADMIN:
        markup.add(types.InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
                   types.InlineKeyboardButton("➖ Remove Admin", callback_data="del_admin_list"))
        markup.add(types.InlineKeyboardButton("📢 Global BC", callback_data="bc_all"),
                   types.InlineKeyboardButton("✍️ Set Leave Msg", callback_data="set_leave_msg"))
    return markup

def user_manage_keyboard(target_uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    banned = is_banned(target_uid)
    markup.add(types.InlineKeyboardButton("💬 Chat", callback_data=f"start_sess_{target_uid}"),
               types.InlineKeyboardButton("🔴 Unban" if banned else "🚫 Ban", callback_data=f"toggle_ban_{target_uid}"))
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="inbox_list"))
    return markup

def group_control_keyboard(chat_id):
    m = get_group_setting(chat_id, 'maintenance')
    l = get_group_setting(chat_id, 'link_filter')
    s = get_group_setting(chat_id, 'bot_status')
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"Maintenance: {'ON' if m else 'OFF'}", callback_data=f"tog_m_{chat_id}"),
        types.InlineKeyboardButton(f"Link Filter: {'ON' if l else 'OFF'}", callback_data=f"tog_l_{chat_id}"),
        types.InlineKeyboardButton(f"Status: {'Active' if s else 'Paused'}", callback_data=f"tog_s_{chat_id}"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data=f"bc_{chat_id}"),
        types.InlineKeyboardButton("🚪 Leave Group", callback_data=f"leave_{chat_id}"),
        types.InlineKeyboardButton("⬅️ Back", callback_data="list_groups")
    )
    return markup

# ================= HANDLERS =================
@bot.message_handler(commands=['start', 'admin'])
def commands(message):
    uid = message.from_user.id
    if message.text == "/admin":
        if is_admin(uid):
            bot.send_message(uid, "🏮 **Admin Control Panel**", reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")
        return

    if message.chat.type == "private":
        if is_banned(uid):
            bot.send_message(uid, "❌ You are banned from using this bot.")
            return
        # Register User
        with db_lock:
            conn = get_db_connection()
            conn.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (uid, f"@{message.from_user.username}" or message.from_user.first_name))
            conn.commit()
            conn.close()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🙋 Request Chat", callback_data="req_chat"))
        bot.send_message(uid, f"Hello {message.from_user.first_name}! Use the button below to request a chat.", reply_markup=markup)

@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document'])
def handle_all(message):
    uid = message.from_user.id
    cid = message.chat.id

    if message.chat.type == "private":
        if is_banned(uid): return
        if uid in active_sessions:
            target = active_sessions[uid]
            try:
                if message.text: bot.send_message(target, message.text)
                elif message.photo: bot.send_photo(target, message.photo[-1].file_id, caption=message.caption)
                # ... other media ...
            except: bot.send_message(uid, "⚠️ Connection lost.")
        elif not is_admin(uid):
            bot.send_message(uid, "👋 Please request a chat first.")
    else:
        # Group Settings & Filters
        if get_group_setting(cid, 'bot_status') == 0: return
        if get_group_setting(cid, 'maintenance') == 1 and not is_admin(uid, cid):
            bot.delete_message(cid, message.message_id)
            return
        if get_group_setting(cid, 'link_filter') == 1:
            if "http" in (message.text or "").lower() and not is_admin(uid, cid):
                bot.delete_message(cid, message.message_id)
                bot.send_message(cid, f"@{message.from_user.username} " হ্যাঁ ভাই🙂, উরাধুরা লিংক দাও, জায়গাটা কি তোমার বাপ কিনা রাখছে? 😒)

@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    uid = call.from_user.id
    data = call.data

    if data == "req_chat":
        now = time.time()
        if uid in cooldowns and now - cooldowns[uid] < 600:
            bot.answer_callback_query(call.id, "Wait 10 mins!", show_alert=True)
            return
        cooldowns[uid] = now
        bot.edit_message_text("✅ Request sent to admins.", call.message.chat.id, call.message.message_id)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Accept", callback_data=f"acc_{uid}"),
                   types.InlineKeyboardButton("❌ Reject", callback_data=f"rej_{uid}"))
        bot.send_message(SUPER_ADMIN, f"📩 **Chat Request!**\nUser: {call.from_user.first_name}\nID: `{uid}`", reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("acc_"):
        target = int(data.split("_")[1])
        active_sessions[uid] = target
        active_sessions[target] = uid
        bot.send_message(target, "✅ Your chat request was accepted!")
        bot.edit_message_text(f"✅ Session started with {target}", call.message.chat.id, call.message.message_id)

    elif data.startswith("rej_"):
        target = int(data.split("_")[1])
        bot.send_message(target, "❌ Your chat request was rejected.")
        bot.edit_message_text("❌ Request Rejected.", call.message.chat.id, call.message.message_id)

    elif data == "inbox_list":
        if not is_admin(uid): return
        with db_lock:
            conn = get_db_connection()
            users = conn.execute('SELECT user_id, username FROM users LIMIT 20').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for u in users:
            markup.add(types.InlineKeyboardButton(f"👤 {u[1]}", callback_data=f"manage_usr_{u[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📥 **Recent Users:**", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data.startswith("manage_usr_"):
        target = int(data.split("_")[2])
        bot.edit_message_text(f"👤 **Managing User:** `{target}`", call.message.chat.id, call.message.message_id, reply_markup=user_manage_keyboard(target))

    elif data.startswith("toggle_ban_"):
        target = int(data.split("_")[2])
        new_status = 0 if is_banned(target) else 1
        with db_lock:
            conn = get_db_connection()
            conn.execute('UPDATE users SET is_banned = ? WHERE user_id = ?', (new_status, target))
            conn.commit()
            conn.close()
        bot.answer_callback_query(call.id, f"User {'Banned' if new_status else 'Unbanned'}")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=user_manage_keyboard(target))

    elif data == "set_leave_msg":
        msg = bot.send_message(uid, "✍️ Send the new leave message:")
        bot.register_next_step_handler(msg, save_leave_msg)

    elif data == "list_groups":
        with db_lock:
            conn = get_db_connection()
            groups = conn.execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for g in groups: markup.add(types.InlineKeyboardButton(f"📍 {g[1]}", callback_data=f"ctrl_{g[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📂 **Groups:**", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data.startswith("ctrl_"):
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=group_control_keyboard(int(data.split("_")[1])))

    elif data.startswith("leave_"):
        cid = int(data.split("_")[1])
        leave_text = get_global_leave_msg()
        try:
            bot.send_message(cid, leave_text)
            bot.leave_chat(cid)
            bot.answer_callback_query(call.id, "Left Group!")
        except: bot.answer_callback_query(call.id, "Error leaving.")

def save_leave_msg(message):
    with db_lock:
        conn = get_db_connection()
        conn.execute('UPDATE settings SET leave_msg = ? WHERE id = 1', (message.text,))
        conn.commit()
        conn.close()
    bot.send_message(message.chat.id, f"✅ Leave message updated to:\n`{message.text}`")

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    init_db()
    bot.polling(none_stop=True)
