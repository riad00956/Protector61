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
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=20) # ফাস্ট রেসপন্সের জন্য থ্রেড বাড়ানো হয়েছে

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
        cursor.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
        cursor.execute('CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS maintenance (chat_id INTEGER PRIMARY KEY, status INTEGER DEFAULT 0)')
        cursor.execute('CREATE TABLE IF NOT EXISTS logs (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)')
        conn.commit()
        conn.close()

init_db()

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
        return res is not None

# ================= GRAPH =================
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
    chart_config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{"label": "Activity", "data": values, "fill": True, "backgroundColor": "rgba(54, 162, 235, 0.2)", "borderColor": "rgb(54, 162, 235)", "tension": 0.4}]
        }
    }
    config_str = json.dumps(chart_config)
    chart_url = f"https://quickchart.io/chart?c={config_str}&width=800&height=400"
    try:
        response = requests.get(chart_url, timeout=10)
        return io.BytesIO(response.content) if response.status_code == 200 else None
    except: return None

# ================= KEYBOARDS =================
def main_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 লাইভ এনালিটিক্স", callback_data="show_graph"),
        types.InlineKeyboardButton("📂 গ্রুপ ম্যানেজমেন্ট", callback_data="list_groups"),
        types.InlineKeyboardButton("➕ অ্যাডমিন যোগ", callback_data="add_admin"),
        types.InlineKeyboardButton("➖ অ্যাডমিন ডিলিট", callback_data="del_admin_list"),
        types.InlineKeyboardButton("📋 অ্যাডমিন তালিকা", callback_data="admin_list"),
        types.InlineKeyboardButton("📢 গ্লোবাল ব্রডকাস্ট", callback_data="bc_all")
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

    if message.text == "/admin" and is_admin(uid):
        bot.send_message(cid, "🏮 Trigger,👉 @xq_trigger_bot - Admin Panel", reply_markup=main_admin_keyboard())
        return

    # Link Filter
    text = message.text or message.caption or ""
    if ("http" in text or "t.me" in text) and not is_admin(uid) and message.chat.type != "private":
        try:
            bot.delete_message(cid, message.message_id)
            bot.send_message(cid, f"🚫 {message.from_user.first_name}, ডিলিট করো সমস্যা হবে 🐸💔🔥")
        except: pass

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    if not is_admin(uid): return

    if call.data == "show_graph":
        graph = generate_log_graph()
        if graph: bot.send_photo(cid, graph)
        
    elif call.data == "list_groups":
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT chat_id, title FROM groups')
            rows = cursor.fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for row in rows: markup.add(types.InlineKeyboardButton(f"📍 {row[1]}", callback_data=f"mng_{row[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ ব্যাক", callback_data="back_main"))
        bot.edit_message_text("📂 গ্রুপ তালিকা:", cid, mid, reply_markup=markup)

    elif call.data.startswith("mng_"):
        target_id = call.data.split("_")[1]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 এই গ্রুপে ব্রডকাস্ট", callback_data=f"bc_{target_id}"))
        markup.add(types.InlineKeyboardButton("⬅️ ব্যাক", callback_data="list_groups"))
        bot.edit_message_text(f"⚙️ গ্রুপ কন্ট্রোল: `{target_id}`", cid, mid, reply_markup=markup)

    elif call.data == "add_admin":
        msg = bot.send_message(cid, "🆔 নতুন অ্যাডমিনের User ID দিন:")
        bot.register_next_step_handler(msg, process_add_admin)

    elif call.data == "del_admin_list":
        if uid != SUPER_ADMIN:
            bot.answer_callback_query(call.id, "শুধুমাত্র মেইন ওনার অ্যাডমিন ডিলিট করতে পারবে!")
            return
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM admins')
            admins = cursor.fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for a in admins: markup.add(types.InlineKeyboardButton(f"❌ {a[0]}", callback_data=f"rem_{a[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ ব্যাক", callback_data="back_main"))
        bot.edit_message_text("কার আইডি রিমুভ করবেন?", cid, mid, reply_markup=markup)

    elif call.data.startswith("rem_"):
        target_uid = call.data.split("_")[1]
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM admins WHERE user_id = ?', (target_uid,))
            conn.commit()
            conn.close()
        bot.answer_callback_query(call.id, "অ্যাডমিন রিমুভ হয়েছে!")
        callback_logic(call) # Refresh list

    elif call.data == "admin_list":
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM admins')
            admins = cursor.fetchall()
            conn.close()
        text = f"👥 **অ্যাডমিন তালিকা:**\n\n👑 Owner: `{SUPER_ADMIN}`\n"
        for a in admins: text += f"👤 Admin: `{a[0]}`\n"
        bot.send_message(cid, text, parse_mode="Markdown")

    elif call.data == "bc_all":
        msg = bot.send_message(cid, "📢 ব্রডকাস্ট মেসেজটি দিন (Text/Photo/Video):")
        bot.register_next_step_handler(msg, start_bc, "all")

    elif call.data.startswith("bc_"):
        target_id = call.data.split("_")[1]
        msg = bot.send_message(cid, "📢 এই গ্রুপের জন্য মেসেজটি দিন:")
        bot.register_next_step_handler(msg, start_bc, target_id)

    elif call.data == "back_main":
        bot.edit_message_text("🏮 Admin Panel", cid, mid, reply_markup=main_admin_keyboard())

# ================= HELPERS =================
def process_add_admin(message):
    try:
        new_id = int(message.text)
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO admins VALUES (?)', (new_id,))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, f"✅ `{new_id}` অ্যাডমিন হয়েছে!")
    except: bot.send_message(message.chat.id, "❌ ভুল আইডি।")

def start_bc(message, target):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        ids = [r[0] for r in cursor.execute('SELECT chat_id FROM groups').fetchall()] if target == "all" else [int(target)]
        conn.close()
    
    def send_task():
        success = 0
        for tid in ids:
            try:
                if message.content_type == 'text': bot.send_message(tid, message.text)
                elif message.content_type == 'photo': bot.send_photo(tid, message.photo[-1].file_id, caption=message.caption)
                elif message.content_type == 'video': bot.send_video(tid, message.video.file_id, caption=message.caption)
                success += 1
                time.sleep(0.1) # টেলিগ্রাম স্প্যাম ফিল্টার এড়াতে
            except: pass
        bot.send_message(message.chat.id, f"📢 ব্রডকাস্ট রিপোর্ট: {success} টি গ্রুপে পাঠানো হয়েছে।")

    threading.Thread(target=send_task).start() # ব্রডকাস্ট ব্যাকগ্রাউন্ডে চলবে যাতে বট হ্যাং না হয়

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            time.sleep(5)
