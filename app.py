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

# রেন্ডারে Conflict এরর এড়ানোর জন্য
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
                          (user_id INTEGER PRIMARY KEY, target_group INTEGER, permissions TEXT)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (chat_id INTEGER PRIMARY KEY, maintenance INTEGER DEFAULT 0, 
                           link_filter INTEGER DEFAULT 1, bot_status INTEGER DEFAULT 1)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS logs (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)')
        conn.commit()
        conn.close()

init_db()

# --- Helpers ---
def is_super(uid): return uid == SUPER_ADMIN

def is_admin(uid, chat_id=None):
    if uid == SUPER_ADMIN: return True
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT target_group FROM admins WHERE user_id = ?', (uid,))
        res = cursor.fetchone()
        conn.close()
        if not res: return False
        if chat_id and int(res[0]) != int(chat_id): return False
        return True

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

# ================= KEYBOARDS =================
def main_admin_keyboard(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_super(uid):
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
            cursor = conn.cursor()
            cursor.execute('SELECT target_group FROM admins WHERE user_id = ?', (uid,))
            res = cursor.fetchone()
            conn.close()
        if res:
            markup.add(types.InlineKeyboardButton("📍 Manage My Group", callback_data=f"mng_{res[0]}"))
    return markup

def group_control_keyboard(chat_id, uid):
    m, l, s = get_setting(chat_id, 'maintenance'), get_setting(chat_id, 'link_filter'), get_setting(chat_id, 'bot_status')
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"{'🔴' if m else '🟢'} Maintenance: {'ON' if m else 'OFF'}", callback_data=f"tog_m_{chat_id}"),
        types.InlineKeyboardButton(f"{'🟢' if l else '🔴'} Link Filter: {'ON' if l else 'OFF'}", callback_data=f"tog_l_{chat_id}"),
        types.InlineKeyboardButton(f"{'✅' if s else '⏸'} Bot Status: {'Active' if s else 'Paused'}", callback_data=f"tog_s_{chat_id}"),
        types.InlineKeyboardButton("📢 Group Broadcast", callback_data=f"bc_{chat_id}"),
        types.InlineKeyboardButton("🚪 Leave Group", callback_data=f"leave_{chat_id}"),
        types.InlineKeyboardButton("⬅️ Back", callback_data="back_main")
    )
    return markup

# ================= HANDLERS =================
@bot.message_handler(commands=['start', 'admin'])
def admin_cmd(message):
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "🏮 **Admin Panel**", reply_markup=main_admin_keyboard(message.from_user.id), parse_mode="Markdown")

@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document'])
def handle_messages(message):
    uid, cid = message.from_user.id, message.chat.id
    if message.chat.type != "private":
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO groups VALUES (?, ?)', (cid, message.chat.title))
            conn.commit()
            conn.close()
        
        if get_setting(cid, 'bot_status') == 0: return
        if get_setting(cid, 'maintenance') == 1 and not is_admin(uid): return
        if get_setting(cid, 'link_filter') == 1:
            text = message.text or message.caption or ""
            if ("http" in text or "t.me" in text) and not is_admin(uid):
                try: 
                    bot.delete_message(cid, message.message_id)
                    bot.send_message(cid, f"🚫 নো লিংক এলাউড {message.from_user.first_name}!")
                except: pass

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid, cid, mid = call.from_user.id, call.message.chat.id, call.message.message_id
    if not is_admin(uid): return

    if call.data == "back_main":
        bot.edit_message_text("🏮 **Admin Panel**", cid, mid, reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")

    elif call.data == "list_groups":
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            rows = cursor.execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for r in rows: markup.add(types.InlineKeyboardButton(f"📍 {r[1]}", callback_data=f"mng_{r[0]}"))
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
        bot.edit_message_text("📂 সিলেক্ট গ্রুপ:", cid, mid, reply_markup=markup)

    elif call.data.startswith("mng_"):
        tid = int(call.data.split("_")[1])
        if is_admin(uid, tid):
            bot.edit_message_text(f"⚙️ **Group Management**\nID: `{tid}`", cid, mid, reply_markup=group_control_keyboard(tid, uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "আপনার এই গ্রুপের এক্সেস নেই!")

    elif call.data.startswith("tog_"):
        _, key, tid = call.data.split("_")
        key_map = {'m':'maintenance', 'l':'link_filter', 's':'bot_status'}
        toggle_setting(int(tid), key_map[key])
        bot.edit_message_reply_markup(cid, mid, reply_markup=group_control_keyboard(int(tid), uid))

    elif call.data.startswith("leave_"):
        tid = call.data.split("_")[1]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Yes", callback_data=f"conf_leave_{tid}"),
                   types.InlineKeyboardButton("❌ No", callback_data=f"mng_{tid}"))
        bot.edit_message_text("❓ গ্রুপ থেকে বের হতে চান?", cid, mid, reply_markup=markup)

    elif call.data.startswith("conf_leave_"):
        tid = int(call.data.split("_")[2])
        try:
            bot.send_message(tid, "👋 বিদায়! সুপার এডমিন আমাকে বের হয়ে যেতে বলেছে।")
            bot.leave_chat(tid)
            bot.edit_message_text("✅ সফলভাবে গ্রুপ লিভ করেছি।", cid, mid, reply_markup=main_admin_keyboard(uid))
        except: bot.answer_callback_query(call.id, "Error!")

    elif call.data == "add_admin":
        if not is_super(uid): return
        msg = bot.send_message(cid, "🆔 এডমিনের **User ID** দিন:")
        bot.register_next_step_handler(msg, process_admin_id)

    elif call.data.startswith("bc_"):
        target = call.data.split("_")[1]
        msg = bot.send_message(cid, "📢 ব্রডকাস্ট মেসেজটি দিন (টাইমআউট: ১ মি. ১২ সে.):")
        timer = threading.Timer(72.0, timeout_broadcast, args=[cid, uid])
        timer.start()
        bot.register_next_step_handler(msg, start_bc, target, timer)

# ================= BROADCAST & ADMIN HELPERS =================
def timeout_broadcast(cid, uid):
    bot.clear_step_handler_by_chat_id(cid)
    bot.send_message(cid, "⏰ সময় শেষ! আপনি কিছু না পাঠানোয় ড্যাশবোর্ডে ফেরত নেওয়া হলো।", reply_markup=main_admin_keyboard(uid))

def process_admin_id(message):
    try:
        new_id = int(message.text)
        with db_lock:
            conn = get_db_connection()
            groups = conn.cursor().execute('SELECT chat_id, title FROM groups').fetchall()
            conn.close()
        markup = types.InlineKeyboardMarkup()
        for g in groups: markup.add(types.InlineKeyboardButton(g[1], callback_data=f"setadm_{new_id}_{g[0]}"))
        bot.send_message(message.chat.id, "📍 কোন গ্রুপের জন্য এডমিন করবেন?", reply_markup=markup)
    except: bot.send_message(message.chat.id, "Invalid ID!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("setadm_"))
def final_admin(call):
    _, aid, gid = call.data.split("_")
    with db_lock:
        conn = get_db_connection()
        conn.cursor().execute('INSERT OR REPLACE INTO admins VALUES (?, ?, ?)', (aid, gid, "full"))
        conn.commit()
        conn.close()
    bot.edit_message_text(f"✅ এডমিন যুক্ত হয়েছে (ID: {aid})", call.message.chat.id, call.message.message_id, reply_markup=main_admin_keyboard(call.from_user.id))

def start_bc(message, target, timer):
    timer.cancel()
    with db_lock:
        conn = get_db_connection()
        ids = [r[0] for r in conn.cursor().execute('SELECT chat_id FROM groups').fetchall()] if target == "all" else [int(target)]
        conn.close()
    
    success = 0
    for tid in ids:
        try:
            if message.content_type == 'text': bot.send_message(tid, message.text)
            elif message.content_type == 'photo': bot.send_photo(tid, message.photo[-1].file_id, caption=message.caption)
            success += 1
        except: pass
    bot.send_message(message.chat.id, f"✅ সফল: {success}", reply_markup=main_admin_keyboard(message.from_user.id))

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    print("Bot is starting...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
