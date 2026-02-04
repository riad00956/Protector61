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
                          (user_id INTEGER PRIMARY KEY, target_group INTEGER, perms TEXT)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (chat_id INTEGER PRIMARY KEY, maintenance INTEGER DEFAULT 0, 
                           link_filter INTEGER DEFAULT 1, bot_status INTEGER DEFAULT 1)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS logs (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                          (user_id PRIMARY KEY, username TEXT, last_msg TEXT, is_banned INTEGER DEFAULT 0)''')
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
        return res[0] if res else (1 if key != 'maintenance' else 0)

def toggle_setting(chat_id, key):
    current = get_setting(chat_id, key)
    new_val = 1 if current == 0 else 0
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'INSERT OR IGNORE INTO settings (chat_id) VALUES (?)', (chat_id,))
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

def is_admin(user_id, chat_id=None):
    if user_id == SUPER_ADMIN: return True
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT target_group FROM admins WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        conn.close()
        if res:
            if chat_id and int(res[0]) != int(chat_id): return False
            return True
        return False

# ================= KEYBOARDS =================
def main_admin_keyboard(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if uid == SUPER_ADMIN:
        markup.add(
            types.InlineKeyboardButton("📊 Analytics", callback_data="show_graph"),
            types.InlineKeyboardButton("📂 Group Manager", callback_data="list_groups"),
            types.InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
            types.InlineKeyboardButton("➖ Remove Admin", callback_data="del_admin_list"),
            types.InlineKeyboardButton("📋 Admin List", callback_data="admin_list"),
            types.InlineKeyboardButton("📢 Global Broadcast", callback_data="bc_all"),
            types.InlineKeyboardButton("📥 Inbox Messages", callback_data="inbox_list")
        )
    else:
        with db_lock:
            conn = get_db_connection()
            res = conn.cursor().execute('SELECT target_group FROM admins WHERE user_id = ?', (uid,)).fetchone()
            conn.close()
        if res:
            markup.add(types.InlineKeyboardButton("📍 Manage Group", callback_data=f"mng_{res[0]}"))
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
        types.InlineKeyboardButton("🚪 Leave Group", callback_data=f"leave_{chat_id}"),
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
        if uid in active_sessions:
            target_id = active_sessions[uid]
            try:
                if message.text: bot.send_message(target_id, message.text)
                elif message.photo: bot.send_photo(target_id, message.photo[-1].file_id, caption=message.caption)
                elif message.video: bot.send_video(target_id, message.video.file_id, caption=message.caption)
                elif message.document: bot.send_document(target_id, message.document.file_id, caption=message.caption)
            except: pass
            return

        if message.text == "/admin":
            if is_admin(uid):
                bot.send_message(cid, "🏮 **Admin Control Panel**", reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")
            return
        
        if not is_admin(uid):
            username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
            with db_lock:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (uid,))
                exists = cursor.fetchone()
                cursor.execute('INSERT OR REPLACE INTO users (user_id, username, last_msg) VALUES (?, ?, ?)', 
                               (uid, username, message.text if message.text else "[Media]"))
                conn.commit()
                conn.close()
            
            if message.text == "/start":
                bot.send_message(cid, f"Hello {message.from_user.first_name}! Welcome.", reply_markup=user_request_keyboard())
                if not exists:
                    bot.send_message(SUPER_ADMIN, f"🆕 **New User Alert!**\nName: {message.from_user.first_name}\nID: `{uid}`", parse_mode="Markdown")
            else:
                bot.send_message(cid, "⚠️ You don't have an active session.", reply_markup=user_request_keyboard())

    if message.chat.type != "private":
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('INSERT OR REPLACE INTO groups VALUES (?, ?)', (cid, message.chat.title))
            conn.commit()
            conn.close()

        if get_setting(cid, 'bot_status') == 0: return
        if get_setting(cid, 'maintenance') == 1 and not is_admin(uid): return
        if get_setting(cid, 'link_filter') == 1:
            text = message.text or message.caption or ""
            if ("http" in text or "t.me" in text) and not is_admin(uid):
                try:
                    bot.delete_message(cid, message.message_id)
                    bot.send_message(cid, f"{message.from_user.first_name} হ্যাঁ ভাই, 🙂 তোমার ইচ্ছামত লিংক দাও জায়গাটা তো তোমার বাপের 😒")
                except: pass

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    if call.data == "req_chat":
        now = time.time()
        if uid in cooldowns and now - cooldowns[uid] < 600:
            bot.answer_callback_query(call.id, "Wait 10 mins.", show_alert=True)
            return
        cooldowns[uid] = now
        bot.edit_message_text("✅ Request sent.", cid, mid)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Start Session", callback_data=f"start_sess_{uid}"))
        bot.send_message(SUPER_ADMIN, f"🙋 **Chat Request!**\nName: {call.from_user.first_name}\nID: `{uid}`", reply_markup=markup, parse_mode="Markdown")
        return

    if not is_admin(uid): return

    if call.data == "list_groups":
        with db_lock:
            conn = get_db_connection()
            rows = conn.cursor().execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for row in rows: markup.add(types.InlineKeyboardButton(f"📍 {row[1]}", callback_data=f"mng_{row[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📂 **Manage Groups:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("mng_"):
        target_id = int(call.data.split("_")[1])
        bot.edit_message_text(f"⚙️ **Control:** `{target_id}`", cid, mid, reply_markup=group_control_keyboard(target_id))

    elif call.data.startswith("tog_"):
        _, key_code, target_id = call.data.split("_")
        key_map = {'m': 'maintenance', 'l': 'link_filter', 's': 'bot_status'}
        toggle_setting(int(target_id), key_map[key_code])
        bot.edit_message_reply_markup(cid, mid, reply_markup=group_control_keyboard(int(target_id)))

    elif call.data.startswith("bc_"):
        target_id = call.data.split("_")[1]
        msg = bot.send_message(cid, "✍️ Send the message for this group:")
        bot.register_next_step_handler(msg, process_group_broadcast, target_id)

    elif call.data == "bc_all":
        msg = bot.send_message(cid, "✍️ Send Global Announcement:")
        bot.register_next_step_handler(msg, process_global_broadcast)

    elif call.data == "inbox_list":
        with db_lock:
            conn = get_db_connection()
            users = conn.cursor().execute('SELECT user_id, username FROM users').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for u in users: markup.add(types.InlineKeyboardButton(f"👤 {u[1]}", callback_data=f"usr_{u[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📥 **Inbox Users:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("usr_"):
        target_uid = int(call.data.split("_")[1])
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Start Session", callback_data=f"start_sess_{target_uid}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="inbox_list"))
        bot.edit_message_text(f"👤 **User Detail:**\nID: `{target_uid}`", cid, mid, reply_markup=markup)

    elif call.data.startswith("start_sess_"):
        target_uid = int(call.data.split("_")[2])
        active_sessions[uid] = target_uid
        active_sessions[target_uid] = uid
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🛑 End Session", callback_data=f"end_sess_{target_uid}"))
        bot.send_message(uid, "✅ Session Started.", reply_markup=markup)
        bot.send_message(target_uid, "✅ Moderator accepted your request.")

    elif call.data.startswith("end_sess_"):
        target_uid = int(call.data.split("_")[2])
        active_sessions.pop(uid, None)
        active_sessions.pop(target_uid, None)
        bot.edit_message_text("❌ Session ended.", cid, mid)
        bot.send_message(target_uid, "⚠️ Session Expired.", reply_markup=user_request_keyboard())

    elif call.data == "add_admin":
        msg = bot.send_message(cid, "🆔 Send User ID for new Admin:")
        bot.register_next_step_handler(msg, process_add_admin)

    elif call.data == "del_admin_list":
        with db_lock:
            conn = get_db_connection()
            admins = conn.cursor().execute('SELECT user_id FROM admins').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for a in admins: markup.add(types.InlineKeyboardButton(f"❌ {a[0]}", callback_data=f"rm_adm_{a[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("➖ **Remove Admin:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("rm_adm_"):
        adm_id = int(call.data.split("_")[2])
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('DELETE FROM admins WHERE user_id = ?', (adm_id,))
            conn.commit()
            conn.close()
        bot.answer_callback_query(call.id, "Admin Removed!")
        bot.edit_message_text("✅ Success.", cid, mid, reply_markup=main_admin_keyboard(uid))

    elif call.data == "back_main":
        bot.edit_message_text("🏮 **Admin Control Panel**", cid, mid, reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")

# ================= HELPERS =================
def process_group_broadcast(message, target_id):
    try:
        bot.send_message(target_id, message.text, parse_mode="Markdown")
        bot.send_message(message.chat.id, "✅ Done!")
    except: bot.send_message(message.chat.id, "❌ Error.")

def process_global_broadcast(message):
    with db_lock:
        conn = get_db_connection()
        groups = conn.cursor().execute('SELECT chat_id FROM groups').fetchall()
        conn.close()
    for g in groups:
        try: bot.send_message(g[0], message.text, parse_mode="Markdown")
        except: continue
    bot.send_message(message.chat.id, "✅ Global broadcast done!")

def process_add_admin(message):
    try:
        new_id = int(message.text)
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (new_id,))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, f"✅ Admin added: `{new_id}`")
    except: bot.send_message(message.chat.id, "❌ Invalid ID!")

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    while True:
        try: bot.polling(none_stop=True, interval=0, timeout=30)
        except: time.sleep(5)
