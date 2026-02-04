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
                           link_filter INTEGER DEFAULT 1, bot_status INTEGER DEFAULT 1,
                           leave_msg TEXT DEFAULT "আমি বের হয়ে যাচ্ছি, ভালো থেকো।")''')
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
        if res is None:
            if key == 'leave_msg': return "আমি বের হয়ে যাচ্ছি, ভালো থেকো।"
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

def is_admin(user_id, chat_id=None):
    if user_id == SUPER_ADMIN: return True
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT target_group FROM admins WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        conn.close()
        if res:
            if chat_id and res[0] != 0 and res[0] != chat_id: return False
            return True
        return False

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
            except: 
                bot.send_message(uid, "❌ Failed to deliver message.")
            return

        if message.text == "/admin":
            if is_admin(uid):
                bot.send_message(cid, "🏮 **Admin Control Panel**", reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")
            return
        
        if not is_admin(uid):
            if message.text == "/start":
                bot.send_message(cid, f"Hello {message.from_user.first_name}! Welcome.", reply_markup=user_request_keyboard())
            else:
                bot.send_message(cid, "⚠️ You don't have an active session.", reply_markup=user_request_keyboard())

    else:
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('INSERT OR REPLACE INTO groups VALUES (?, ?)', (cid, message.chat.title))
            conn.commit()
            conn.close()

        if get_setting(cid, 'bot_status') == 0: return
        if get_setting(cid, 'maintenance') == 1 and not is_admin(uid, cid): 
            try: bot.delete_message(cid, message.message_id)
            except: pass
            return
            
        if get_setting(cid, 'link_filter') == 1:
            text = message.text or message.caption or ""
            if ("http" in text.lower() or "t.me" in text.lower()) and not is_admin(uid, cid):
                try:
                    bot.delete_message(cid, message.message_id)
                    bot.send_message(cid, f"@{message.from_user.username} হ্যাঁ ভাই🙂, উরাধুরা লিংক দাও, জায়গাটা কি তোমার বাপ কিনা রাখছে? 😒")
                except: pass

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    if call.data == "req_chat":
        now = time.time()
        if uid in cooldowns and now - cooldowns[uid] < 600: # 10 mins (600s)
            bot.answer_callback_query(call.id, "Please wait 10 mins before next request.", show_alert=True)
            return
        cooldowns[uid] = now
        bot.edit_message_text("✅ Your request has been sent to admins.", cid, mid)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Accept Chat", callback_data=f"start_sess_{uid}"))
        bot.send_message(SUPER_ADMIN, f"🙋 **Chat Request!**\nName: {call.from_user.first_name}\nID: `{uid}`", reply_markup=markup, parse_mode="Markdown")
        return

    if not is_admin(uid): return

    if call.data == "back_main":
        bot.edit_message_text("🏮 **Admin Control Panel**", cid, mid, reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")

    elif call.data == "list_groups":
        with db_lock:
            conn = get_db_connection()
            rows = conn.cursor().execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for row in rows: 
            if is_admin(uid, row[0]):
                markup.add(types.InlineKeyboardButton(f"📍 {row[1]}", callback_data=f"mng_{row[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📂 **Manage Groups:**", cid, mid, reply_markup=markup)

    elif call.data.startswith("mng_"):
        target_id = int(call.data.split("_")[1])
        bot.edit_message_text(f"⚙️ **Group Settings for:** `{target_id}`", cid, mid, reply_markup=group_control_keyboard(target_id), parse_mode="Markdown")

    elif call.data.startswith("tog_"):
        parts = call.data.split("_")
        target_id = int(parts[2])
        if not is_admin(uid, target_id): return
        key_map = {'m': 'maintenance', 'l': 'link_filter', 's': 'bot_status'}
        toggle_setting(target_id, key_map[parts[1]])
        bot.edit_message_reply_markup(cid, mid, reply_markup=group_control_keyboard(target_id))

    elif call.data.startswith("leave_"):
        target_id = int(call.data.split("_")[1])
        if uid != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "Only Super Admin can do this.", show_alert=True)
            return
        msg = get_setting(target_id, 'leave_msg')
        try:
            bot.send_message(target_id, msg)
            bot.leave_chat(target_id)
            bot.edit_message_text(f"✅ Left group `{target_id}` successfully.", cid, mid)
        except:
            bot.answer_callback_query(call.id, "Failed to leave group.")

    elif call.data == "set_leave_msg":
        msg = bot.send_message(cid, "✍️ Send the message you want the bot to say before leaving:")
        bot.register_next_step_handler(msg, process_set_leave_msg)

    elif call.data == "bc_all":
        msg = bot.send_message(cid, "✍️ Type for Global Broadcast:")
        bot.register_next_step_handler(msg, process_global_broadcast)

    elif call.data.startswith("bc_"):
        target_id = int(call.data.split("_")[1])
        msg = bot.send_message(cid, "✍️ Message for this group:")
        bot.register_next_step_handler(msg, process_group_broadcast, target_id)

    elif call.data == "inbox_list":
        with db_lock:
            conn = get_db_connection()
            users = conn.cursor().execute('SELECT user_id, username FROM users ORDER BY user_id DESC LIMIT 15').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for u in users: markup.add(types.InlineKeyboardButton(f"👤 {u[1]}", callback_data=f"usr_{u[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📥 **Recent Users:**", cid, mid, reply_markup=markup)

    elif call.data == "add_admin":
        msg = bot.send_message(cid, "🆔 Send the User ID for new Admin:")
        bot.register_next_step_handler(msg, process_add_admin_step1)

    elif call.data == "admin_list":
        with db_lock:
            conn = get_db_connection()
            admins = conn.cursor().execute('SELECT user_id, target_group FROM admins').fetchall()
            conn.close()
        text = "📋 **Admin List:**\n\n"
        for a in admins: text += f"• `{a[0]}` (Target: `{a[1] if a[1] != 0 else 'All'}`)\n"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text(text, cid, mid, reply_markup=markup, parse_mode="Markdown")

    elif call.data.startswith("rm_adm_"):
        adm_id = int(call.data.split("_")[2])
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('DELETE FROM admins WHERE user_id = ?', (adm_id,))
            conn.commit()
            conn.close()
        bot.edit_message_text("✅ Admin Removed.", cid, mid, reply_markup=main_admin_keyboard(uid))

# ================= NEXT STEP HANDLERS =================
def process_set_leave_msg(message):
    try:
        new_msg = message.text
        with db_lock:
            conn = get_db_connection()
            # Update for all or default (simple way)
            conn.cursor().execute('UPDATE settings SET leave_msg = ?', (new_msg,))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, "✅ Leave message updated!")
    except: bot.send_message(message.chat.id, "❌ Error.")

def process_add_admin_step1(message):
    try:
        new_id = int(message.text)
        msg = bot.send_message(message.chat.id, "📍 Send Group ID for this admin (or send `0` for all groups):")
        bot.register_next_step_handler(msg, process_add_admin_step2, new_id)
    except: bot.send_message(message.chat.id, "❌ Invalid ID.")

def process_add_admin_step2(message, new_id):
    try:
        target_gid = int(message.text)
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('INSERT OR REPLACE INTO admins (user_id, target_group) VALUES (?, ?)', (new_id, target_gid))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, f"✅ Admin `{new_id}` added for group `{target_gid if target_gid != 0 else 'All'}`.")
    except: bot.send_message(message.chat.id, "❌ Invalid Group ID.")

def process_group_broadcast(message, target_id):
    try:
        bot.send_message(target_id, message.text, parse_mode="Markdown")
        bot.send_message(message.chat.id, "✅ Done!")
    except: bot.send_message(message.chat.id, "❌ Failed.")

def process_global_broadcast(message):
    with db_lock:
        conn = get_db_connection()
        groups = conn.cursor().execute('SELECT chat_id FROM groups').fetchall()
        conn.close()
    for g in groups:
        try: bot.send_message(g[0], message.text, parse_mode="Markdown")
        except: continue
    bot.send_message(message.chat.id, "✅ Global broadcast done!")

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    while True:
        try: bot.polling(none_stop=True, interval=0, timeout=60)
        except: time.sleep(5)
