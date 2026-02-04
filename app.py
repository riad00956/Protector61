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

active_sessions = {} # {admin_id: user_id} and {user_id: admin_id}
cooldowns = {} 

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
                          (id INTEGER PRIMARY KEY DEFAULT 1, maintenance INTEGER DEFAULT 0, 
                           link_filter INTEGER DEFAULT 1, leave_msg TEXT DEFAULT "আমি বের হয়ে যাচ্ছি, ভালো থেকো।")''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                          (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, is_banned INTEGER DEFAULT 0)''')
        # এককালীন সেটিংস ইনসার্ট
        cursor.execute('INSERT OR IGNORE INTO settings (id) VALUES (1)')
        conn.commit()
        conn.close()

init_db()

# --- Helpers ---
def get_global_setting(key):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'SELECT {key} FROM settings WHERE id = 1')
        res = cursor.fetchone()
        conn.close()
        return res[0] if res else None

def is_admin(user_id):
    if user_id == SUPER_ADMIN: return True
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        conn.close()
        return True if res else False

def is_banned(user_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res[0] == 1 if res else False

# ================= KEYBOARDS =================
def main_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📂 Group Manager", callback_data="list_groups"),
        types.InlineKeyboardButton("📥 Inbox Messages", callback_data="inbox_list"),
        types.InlineKeyboardButton("📋 Admin List", callback_data="admin_list"),
        types.InlineKeyboardButton("➕ Add Admin", callback_data="add_admin")
    )
    markup.add(types.InlineKeyboardButton("📢 Global Broadcast", callback_data="bc_all"))
    markup.add(types.InlineKeyboardButton("✍️ Set Leave Msg", callback_data="set_leave_msg"))
    return markup

def user_manage_keyboard(user_id, banned):
    markup = types.InlineKeyboardMarkup()
    btn_text = "🔓 Unban User" if banned else "🚫 Ban User"
    markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"ban_toggle_{user_id}"))
    markup.add(types.InlineKeyboardButton("💬 Start Chat", callback_data=f"start_sess_{user_id}"))
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="inbox_list"))
    return markup

# ================= HANDLERS =================

@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if message.chat.type != "private": return
    
    # Save user to DB
    with db_lock:
        conn = get_db_connection()
        conn.cursor().execute('INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)', 
                             (uid, message.from_user.username, message.from_user.first_name))
        conn.commit()
        conn.close()

    if is_banned(uid):
        bot.send_message(uid, "❌ You are banned from using this bot.")
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🙋 Request to Chat", callback_data="req_chat"))
    bot.send_message(uid, f"Hello {message.from_user.first_name}! Welcome. Click below to chat with Admin.", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "🏮 **Admin Control Panel**", reply_markup=main_admin_keyboard(), parse_mode="Markdown")

@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document'])
def handle_all(message):
    uid = message.from_user.id
    cid = message.chat.id

    if message.chat.type == "private":
        if is_banned(uid): return

        # Active Chat Session
        if uid in active_sessions:
            target_id = active_sessions[uid]
            try:
                if message.text: bot.send_message(target_id, f"💬 **Message:**\n{message.text}", parse_mode="Markdown")
                elif message.photo: bot.send_photo(target_id, message.photo[-1].file_id, caption=message.caption)
                elif message.video: bot.send_video(target_id, message.video.file_id, caption=message.caption)
                elif message.document: bot.send_document(target_id, message.document.file_id, caption=message.caption)
            except:
                bot.send_message(uid, "❌ Session ended or failed to deliver.")
                active_sessions.pop(uid, None)
            return
        
        if not is_admin(uid) and message.text != "/start":
            bot.send_message(uid, "⚠️ No active chat. Use /start to request.")

    else:
        # Group logic (Link Filter & Maintenance)
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('INSERT OR REPLACE INTO groups VALUES (?, ?)', (cid, message.chat.title))
            conn.commit()
            conn.close()
        
        # Link Filter
        if get_global_setting('link_filter') == 1 and not is_admin(uid):
            text = message.text or message.caption or ""
            if "http" in text.lower() or "t.me" in text.lower():
                try: bot.delete_message(cid, message.message_id)
                except: pass

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    if call.data == "req_chat":
        bot.edit_message_text("⏳ Request sent. Waiting for approval...", cid, mid)
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Accept", callback_data=f"acc_{uid}"),
            types.InlineKeyboardButton("❌ Reject", callback_data=f"rej_{uid}")
        )
        bot.send_message(SUPER_ADMIN, f"🙋 **New Chat Request!**\nName: {call.from_user.first_name}\nID: `{uid}`", reply_markup=markup, parse_mode="Markdown")

    elif call.data.startswith("acc_"):
        target_id = int(call.data.split("_")[1])
        active_sessions[uid] = target_id
        active_sessions[target_id] = uid
        bot.send_message(target_id, "✅ Your chat request was accepted! You can now talk to the admin.")
        bot.edit_message_text("✅ Chat session started. Send a message to reply.", cid, mid)

    elif call.data.startswith("rej_"):
        target_id = int(call.data.split("_")[1])
        bot.send_message(target_id, "❌ Sorry, your chat request was rejected.")
        bot.edit_message_text("❌ Request Rejected.", cid, mid)

    elif call.data == "inbox_list":
        if not is_admin(uid): return
        with db_lock:
            conn = get_db_connection()
            users = conn.cursor().execute('SELECT user_id, first_name FROM users LIMIT 20').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for u in users:
            markup.add(types.InlineKeyboardButton(f"👤 {u[1]}", callback_data=f"view_u_{u[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📥 **User Inbox:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("view_u_"):
        target_id = int(call.data.split("_")[2])
        banned = is_banned(target_id)
        bot.edit_message_text(f"👤 **User Management**\nID: `{target_id}`", cid, mid, 
                              reply_markup=user_manage_keyboard(target_id, banned), parse_mode="Markdown")

    elif call.data.startswith("ban_toggle_"):
        target_id = int(call.data.split("_")[2])
        new_status = 0 if is_banned(target_id) else 1
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('UPDATE users SET is_banned = ? WHERE user_id = ?', (new_status, target_id))
            conn.commit()
            conn.close()
        bot.answer_callback_query(call.id, "Status Updated!")
        bot.edit_message_reply_markup(cid, mid, reply_markup=user_manage_keyboard(target_id, new_status))

    elif call.data == "set_leave_msg":
        msg = bot.send_message(cid, "✍️ Send the message you want the bot to say before leaving:")
        bot.register_next_step_handler(msg, process_set_leave_msg)

    elif call.data == "list_groups":
        with db_lock:
            conn = get_db_connection()
            groups = conn.cursor().execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for g in groups:
            markup.add(types.InlineKeyboardButton(f"📍 {g[1]}", callback_data=f"leave_confirm_{g[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📂 **Click a group to make the bot leave:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("leave_confirm_"):
        target_id = int(call.data.split("_")[2])
        leave_msg = get_global_setting('leave_msg')
        try:
            bot.send_message(target_id, leave_msg)
            bot.leave_chat(target_id)
            bot.answer_callback_query(call.id, "Successfully Left!")
            # Remove from DB
            with db_lock:
                conn = get_db_connection()
                conn.cursor().execute('DELETE FROM groups WHERE chat_id = ?', (target_id,))
                conn.commit()
                conn.close()
        except:
            bot.answer_callback_query(call.id, "Error leaving group.")

    elif call.data == "back_main":
        bot.edit_message_text("🏮 **Admin Control Panel**", cid, mid, reply_markup=main_admin_keyboard(), parse_mode="Markdown")

# ================= NEXT STEPS =================
def process_set_leave_msg(message):
    new_msg = message.text
    if new_msg:
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('UPDATE settings SET leave_msg = ? WHERE id = 1', (new_msg,))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, f"✅ Leave message updated to:\n`{new_msg}`")
    else:
        bot.send_message(message.chat.id, "❌ Invalid text.")

def process_global_broadcast(message):
    with db_lock:
        conn = get_db_connection()
        groups = conn.cursor().execute('SELECT chat_id FROM groups').fetchall()
        conn.close()
    for g in groups:
        try: bot.send_message(g[0], message.text)
        except: continue
    bot.send_message(message.chat.id, "✅ Broadcast Done.")

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    while True:
        try: bot.polling(none_stop=True)
        except: time.sleep(5)
