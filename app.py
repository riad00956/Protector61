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
        # Admin table: mapping user to specific group and permissions
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins 
                          (user_id INTEGER PRIMARY KEY, target_group INTEGER, perms TEXT)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (chat_id INTEGER PRIMARY KEY, maintenance INTEGER DEFAULT 0, 
                           link_filter INTEGER DEFAULT 1, bot_status INTEGER DEFAULT 1)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS logs (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)')
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

# ================= KEYBOARDS (ENGLISH DASHBOARD) =================
def main_admin_keyboard(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if uid == SUPER_ADMIN:
        markup.add(
            types.InlineKeyboardButton("📊 Analytics", callback_data="show_graph"),
            types.InlineKeyboardButton("📂 Group Manager", callback_data="list_groups"),
            types.InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
            types.InlineKeyboardButton("➖ Remove Admin", callback_data="del_admin_list"),
            types.InlineKeyboardButton("📋 Admin List", callback_data="admin_list"),
            types.InlineKeyboardButton("📢 Global Broadcast", callback_data="bc_all")
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

# ================= HANDLERS =================
@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document'])
def handle_all(message):
    uid = message.from_user.id
    cid = message.chat.id
    log_message()

    if message.chat.type != "private":
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO groups VALUES (?, ?)', (cid, message.chat.title))
            conn.commit()
            conn.close()

    if (message.text == "/admin" or message.text == "/start") and is_admin(uid):
        bot.send_message(cid, "🏮 **Admin Control Panel**", reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")
        return

    if message.chat.type != "private" and get_setting(cid, 'bot_status') == 0: return
    if message.chat.type != "private" and get_setting(cid, 'maintenance') == 1 and not is_admin(uid): return
    if message.chat.type != "private" and get_setting(cid, 'link_filter') == 1:
        text = message.text or message.caption or ""
        if ("http" in text or "t.me" in text) and not is_admin(uid):
            try:
                bot.delete_message(cid, message.message_id)
                bot.send_message(cid, f"🚫 গ্রুপ তো তোমার বাপের {message.from_user.first_name}, দেও লিংক দাও সমস্যা নাই 🙄")
            except: pass

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    if not is_admin(uid): 
        bot.answer_callback_query(call.id, "Access Denied!")
        return

    if call.data == "show_graph":
        bot.answer_callback_query(call.id, "Processing...")
        graph = generate_log_graph()
        if graph: bot.send_photo(cid, graph, caption="Activity Statistics (Last 7 Days)")
        
    elif call.data == "list_groups":
        if uid != SUPER_ADMIN:
             bot.answer_callback_query(call.id, "Permission Denied!")
             return
        with db_lock:
            conn = get_db_connection()
            rows = conn.cursor().execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for row in rows: markup.add(types.InlineKeyboardButton(f"📍 {row[1]}", callback_data=f"mng_{row[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📂 **Select a group to manage:**", cid, mid, reply_markup=markup, parse_mode="Markdown")

    elif call.data.startswith("mng_"):
        target_id = int(call.data.split("_")[1])
        if is_admin(uid, target_id):
            bot.edit_message_text(f"⚙️ **Management Console**\nTarget ID: `{target_id}`", cid, mid, 
                                 parse_mode="Markdown", reply_markup=group_control_keyboard(target_id))
        else:
            bot.answer_callback_query(call.id, "Unauthorized for this group!")

    elif call.data.startswith("tog_"):
        _, key_code, target_id = call.data.split("_")
        key_map = {'m': 'maintenance', 'l': 'link_filter', 's': 'bot_status'}
        toggle_setting(int(target_id), key_map[key_code])
        bot.edit_message_reply_markup(cid, mid, reply_markup=group_control_keyboard(int(target_id)))

    elif call.data.startswith("leave_"):
        target_id = call.data.split("_")[1]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Yes, Leave", callback_data=f"conf_leave_{target_id}"),
                   types.InlineKeyboardButton("❌ No, Stay", callback_data=f"mng_{target_id}"))
        bot.edit_message_text("⚠️ **Are you sure you want the bot to leave this group?**", cid, mid, reply_markup=markup, parse_mode="Markdown")

    elif call.data.startswith("conf_leave_"):
        target_id = int(call.data.split("_")[2])
        try:
            bot.send_message(target_id, "👋 বিদায় বন্ধুরা! সুপার এডমিনের নির্দেশে আমি এই গ্রুপ থেকে বিদায় নিচ্ছি। ভালো থাকবেন।")
            bot.leave_chat(target_id)
            bot.edit_message_text("✅ Bot has successfully left the group.", cid, mid, reply_markup=main_admin_keyboard(uid))
        except: bot.answer_callback_query(call.id, "Failed to leave!")

    elif call.data == "add_admin":
        if uid != SUPER_ADMIN: return
        msg = bot.send_message(cid, "🆔 Please enter the **User ID** for the new Admin:")
        bot.register_next_step_handler(msg, process_admin_id)

    elif call.data == "del_admin_list":
        if uid != SUPER_ADMIN: return
        with db_lock:
            conn = get_db_connection()
            admins = conn.cursor().execute('SELECT user_id FROM admins').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for a in admins: markup.add(types.InlineKeyboardButton(f"❌ Remove {a[0]}", callback_data=f"rem_{a[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("Select an admin to revoke access:", cid, mid, reply_markup=markup)

    elif call.data.startswith("rem_"):
        target_uid = call.data.split("_")[1]
        with db_lock:
            conn = get_db_connection()
            conn.cursor().execute('DELETE FROM admins WHERE user_id = ?', (target_uid,))
            conn.commit()
            conn.close()
        bot.answer_callback_query(call.id, "Access Revoked!")
        bot.edit_message_text("🏮 **Admin Panel**", cid, mid, reply_markup=main_admin_keyboard(uid))

    elif call.data == "admin_list":
        with db_lock:
            conn = get_db_connection()
            admins = conn.cursor().execute('SELECT user_id, target_group FROM admins').fetchall()
            conn.close()
        text = f"👑 **Super Admin:** `{SUPER_ADMIN}`\n\n"
        for a in admins: text += f"👤 **Admin:** `{a[0]}` (Target Group: `{a[1]}`)\n"
        bot.send_message(cid, text, parse_mode="Markdown")

    elif call.data == "bc_all":
        msg = bot.send_message(cid, "📢 Send your **Broadcast Message**\n(Timeout: 1m 12s):")
        timer = threading.Timer(72.0, timeout_bc, args=[cid, uid])
        timer.start()
        bot.register_next_step_handler(msg, start_bc, "all", timer)

    elif call.data.startswith("bc_"):
        target_id = call.data.split("_")[1]
        msg = bot.send_message(cid, f"📢 Send message for Group `{target_id}`\n(Timeout: 1m 12s):")
        timer = threading.Timer(72.0, timeout_bc, args=[cid, uid])
        timer.start()
        bot.register_next_step_handler(msg, start_bc, target_id, timer)

    elif call.data == "back_main":
        bot.edit_message_text("🏮 **Admin Control Panel**", cid, mid, reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")

# ================= HELPERS (ADMIN & BC) =================
def process_admin_id(message):
    try:
        new_id = int(message.text)
        with db_lock:
            conn = get_db_connection()
            groups = conn.cursor().execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for g in groups: markup.add(types.InlineKeyboardButton(f"Group: {g[1]}", callback_data=f"setadm_{new_id}_{g[0]}"))
        bot.send_message(message.chat.id, "📍 Select the group this admin will manage:", reply_markup=markup)
    except: bot.send_message(message.chat.id, "❌ Error: Invalid User ID!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("setadm_"))
def finalize_admin(call):
    _, aid, gid = call.data.split("_")
    with db_lock:
        conn = get_db_connection()
        conn.cursor().execute('INSERT OR REPLACE INTO admins VALUES (?, ?, ?)', (aid, gid, "full"))
        conn.commit()
        conn.close()
    bot.edit_message_text(f"✅ **New Admin Added!**\nAdmin ID: `{aid}`\nTarget Group: `{gid}`", call.message.chat.id, call.message.message_id, reply_markup=main_admin_keyboard(call.from_user.id), parse_mode="Markdown")

def timeout_bc(cid, uid):
    bot.clear_step_handler_by_chat_id(cid)
    bot.send_message(cid, "⏰ **Session Timeout!**\nYou didn't send a message in time. Returning to Dashboard.", reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")

def start_bc(message, target, timer):
    timer.cancel()
    with db_lock:
        conn = get_db_connection()
        ids = [r[0] for r in conn.cursor().execute('SELECT chat_id FROM groups').fetchall()] if target == "all" else [int(target)]
        conn.close()
    
    def send_task():
        success = 0
        for tid in ids:
            try:
                if message.content_type == 'text': bot.send_message(tid, message.text)
                elif message.content_type == 'photo': bot.send_photo(tid, message.photo[-1].file_id, caption=message.caption)
                elif message.content_type == 'video': bot.send_video(tid, message.video.file_id, caption=message.caption)
                success += 1
                time.sleep(0.05)
            except: pass
        bot.send_message(message.chat.id, f"✅ **Broadcast Complete!**\nSuccessfully sent to {success} groups.", reply_markup=main_admin_keyboard(message.from_user.id), parse_mode="Markdown")

    threading.Thread(target=send_task).start()

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    print("System Online. Monitoring updates...")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=30)
        except Exception:
            time.sleep(5)
            
