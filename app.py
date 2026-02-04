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

# ================= DATABASE SYSTEM =================
db_lock = threading.Lock()

def get_db_connection():
    return sqlite3.connect('bot_final.db', check_same_thread=False)

def init_db():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        # admins টেবিল আপডেট করা হয়েছে গ্রুপ এবং পারমিশন হ্যান্ডেল করার জন্য
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins 
                          (user_id INTEGER PRIMARY KEY, 
                           target_group INTEGER, 
                           permissions TEXT)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (chat_id INTEGER PRIMARY KEY, maintenance INTEGER DEFAULT 0, 
                           link_filter INTEGER DEFAULT 1, bot_status INTEGER DEFAULT 1)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS logs (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)')
        conn.commit()
        conn.close()

init_db()

# --- Helper Functions ---
def is_super(uid):
    return uid == SUPER_ADMIN

def get_admin_data(uid):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT target_group, permissions FROM admins WHERE user_id = ?', (uid,))
        res = cursor.fetchone()
        conn.close()
        return res # (target_group, permissions_json)

def is_admin(uid, chat_id=None):
    if is_super(uid): return True
    data = get_admin_data(uid)
    if not data: return False
    target_group, perms = data
    if chat_id and int(target_group) != int(chat_id): return False
    return True

def get_setting(chat_id, key):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'SELECT {key} FROM settings WHERE chat_id = ?', (chat_id,))
        res = cursor.fetchone()
        conn.close()
        return res[0] if res else (1 if key != 'maintenance' else 0)

# ================= KEYBOARDS =================
def main_admin_keyboard(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    # শুধুমাত্র সুপার এডমিনের জন্য এডমিন ম্যানেজমেন্ট
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
        # সাধারণ এডমিন সরাসরি তার নির্দিষ্ট গ্রুপের কন্ট্রোল দেখবে
        data = get_admin_data(uid)
        if data:
            markup.add(types.InlineKeyboardButton("📍 Manage My Group", callback_data=f"mng_{data[0]}"))
    return markup

def group_control_keyboard(chat_id, uid):
    m = get_setting(chat_id, 'maintenance')
    l = get_setting(chat_id, 'link_filter')
    s = get_setting(chat_id, 'bot_status')
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # পারমিশন চেক (সুপার এডমিন সব পারে, এডমিন শুধু সিলেক্টেড গুলো)
    perms = []
    if not is_super(uid):
        data = get_admin_data(uid)
        perms = json.loads(data[1]) if data else []

    if is_super(uid) or "maintenance" in perms:
        markup.add(types.InlineKeyboardButton(f"{'🔴' if m else '🟢'} Maintenance: {'ON' if m else 'OFF'}", callback_data=f"tog_m_{chat_id}"))
    if is_super(uid) or "link_filter" in perms:
        markup.add(types.InlineKeyboardButton(f"{'🟢' if l else '🔴'} Link Filter: {'ON' if l else 'OFF'}", callback_data=f"tog_l_{chat_id}"))
    if is_super(uid) or "bot_status" in perms:
        markup.add(types.InlineKeyboardButton(f"{'✅' if s else '⏸'} Bot Status: {'Active' if s else 'Paused'}", callback_data=f"tog_s_{chat_id}"))
    if is_super(uid) or "broadcast" in perms:
        markup.add(types.InlineKeyboardButton("📢 Group Broadcast", callback_data=f"bc_{chat_id}"))
    
    # লিভ বাটন সবার জন্য (যদি এডমিন হয়)
    markup.add(types.InlineKeyboardButton("🚪 Leave Group", callback_data=f"leave_{chat_id}"))
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
    return markup

# ================= HANDLERS =================
@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document'])
def handle_all(message):
    uid = message.from_user.id
    cid = message.chat.id
    
    if message.chat.type != "private":
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO groups VALUES (?, ?)', (cid, message.chat.title))
            conn.commit()
            conn.close()

    if message.text == "/admin" and is_admin(uid):
        bot.send_message(cid, "🏮 **Admin Dashboard**", reply_markup=main_admin_keyboard(uid), parse_mode="Markdown")
        return

    # Maintenance & Link Filter logic remains same...
    if message.chat.type != "private" and get_setting(cid, 'bot_status') == 0: return
    if message.chat.type != "private" and get_setting(cid, 'maintenance') == 1 and not is_admin(uid): return
    if message.chat.type != "private" and get_setting(cid, 'link_filter') == 1:
        text = message.text or message.caption or ""
        if ("http" in text or "t.me" in text) and not is_admin(uid):
            try: bot.delete_message(cid, message.message_id)
            except: pass

@bot.callback_query_handler(func=lambda call: True)
def callback_logic(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    if not is_admin(uid): return

    if call.data == "add_admin":
        if not is_super(uid): return
        msg = bot.send_message(cid, "🆔 এডমিনের **User ID** দিন:")
        bot.register_next_step_handler(msg, process_admin_id)

    elif call.data.startswith("mng_"):
        target_id = int(call.data.split("_")[1])
        bot.edit_message_text(f"⚙️ **Group Settings**\nID: `{target_id}`", cid, mid, 
                             parse_mode="Markdown", reply_markup=group_control_keyboard(target_id, uid))

    elif call.data.startswith("leave_"):
        target_id = call.data.split("_")[1]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Yes", callback_data=f"confirm_leave_{target_id}"),
                   types.InlineKeyboardButton("❌ No", callback_data="back_main"))
        bot.edit_message_text("❓ আপনি কি নিশ্চিত যে গ্রুপ থেকে বটকে বের করে দিতে চান?", cid, mid, reply_markup=markup)

    elif call.data.startswith("confirm_leave_"):
        target_id = int(call.data.split("_")[2])
        try:
            bot.send_message(target_id, "👋 বিদায় বন্ধুরা! আবার দেখা হবে।")
            bot.leave_chat(target_id)
            bot.answer_callback_query(call.id, "বট গ্রুপ থেকে বের হয়ে গেছে।")
            bot.edit_message_text("✅ বট সফলভাবে গ্রুপ লিভ করেছে।", cid, mid)
        except:
            bot.answer_callback_query(call.id, "Error leaving group!")

    elif call.data.startswith("bc_"):
        target = call.data.split("_")[1]
        msg = bot.send_message(cid, "📢 ব্রডকাস্ট মেসেজটি পাঠান।\n(সময়সীমা: ১ মিনিট ১২ সেকেন্ড)")
        
        # টাইমআউট থ্রেড
        timer = threading.Timer(72.0, timeout_broadcast, args=[cid, uid])
        timer.start()
        bot.register_next_step_handler(msg, start_bc, target, timer)

    # ... (Other existing callbacks like list_groups, tog_, show_graph, etc. stay same)
    # Just ensure toggle functions check perms via group_control_keyboard filters

# ================= HELPERS (BROADCAST & ADMIN) =================
def timeout_broadcast(cid, uid):
    bot.clear_step_handler_by_chat_id(cid)
    bot.send_message(cid, "⏰ সময় শেষ! আপনি নির্দিষ্ট সময়ে কিছু না পাঠানোয় ড্যাশবোর্ডে ফেরত নেওয়া হলো।", 
                     reply_markup=main_admin_keyboard(uid))

def process_admin_id(message):
    try:
        new_admin_id = int(message.text)
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT chat_id, title FROM groups')
            groups = cursor.fetchall()
            conn.close()
        
        markup = types.InlineKeyboardMarkup()
        for g in groups:
            markup.add(types.InlineKeyboardButton(g[1], callback_data=f"selgrp_{new_admin_id}_{g[0]}"))
        bot.send_message(message.chat.id, "📍 এই এডমিন কোন গ্রুপ কন্ট্রোল করবে?", reply_markup=markup)
    except: bot.send_message(message.chat.id, "Invalid ID!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("selgrp_"))
def select_permissions(call):
    _, admin_id, group_id = call.data.split("_")
    markup = types.InlineKeyboardMarkup()
    # এডমিনকে কি কি ক্ষমতা দেওয়া হবে (সবগুলো সিলেক্ট করে সেভ করার সিস্টেম)
    # এখানে সিম্পল রাখার জন্য ডিরেক্ট একটি বাটন দিয়ে পারমিশন সেট করছি
    markup.add(types.InlineKeyboardButton("Full Control (Inside Group)", callback_data=f"setperm_{admin_id}_{group_id}_full"))
    bot.edit_message_text(f"🔑 Admin `{admin_id}` এর জন্য পারমিশন সেট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("setperm_"))
def final_add_admin(call):
    _, admin_id, group_id, mode = call.data.split("_")
    perms = ["maintenance", "link_filter", "bot_status", "broadcast"] # Full list
    perms_json = json.dumps(perms)
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO admins VALUES (?, ?, ?)', (admin_id, group_id, perms_json))
        conn.commit()
        conn.close()
    bot.edit_message_text(f"✅ এডমিন যুক্ত হয়েছে!\nID: `{admin_id}`\nGroup: `{group_id}`", call.message.chat.id, call.message.message_id)

def start_bc(message, target, timer):
    timer.cancel() # মেসেজ পেয়ে গেলে টাইমার বন্ধ
    # ... (আগের ব্রডকাস্ট লজিক ঠিক থাকবে)
    # target "all" হলে সব গ্রুপ, নাহলে নির্দিষ্ট ID
    # ... [Existing start_bc code] ...
    pass

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    init_db()
    print("Bot is running...")
    bot.infinity_polling()
