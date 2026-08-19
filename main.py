import logging
import time
import json
import random
import os
import asyncio
import nest_asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, ConversationHandler, ContextTypes, filters
)
from telegram.error import TelegramError, RetryAfter
from telegram.request import HTTPXRequest

# --- DUMMY WEB SERVER FOR RENDER PORT BINDING ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running on Render!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

# Background Thread-এ পোর্ট চালু রাখা
threading.Thread(target=run_dummy_server, daemon=True).start()

# Event loop fix for Termux & Linux environments
nest_asyncio.apply()

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION & GLOBAL SETTINGS ---
ADMIN_ID = 7125334953
BOT_TOKEN = "8914904533:AAHIkpWEsNlVmf0n1NhJa9NvwTEJXQPL828"
BOT_USERNAME = "incomezone4xbot"
DATA_FILE = "bot_data.json"

# --- RANDOM BANGLADESHI NAMES ---
FIRST_NAMES = ["Tanvir", "Ashraful", "Mustafizur", "Mahfuzur", "Shahriar", "Nusrat", "Jahangir", "Kawsar", "Zubayer", "Mehedi"]
MIDDLE_NAMES = ["Hasan", "Alam", "Rahman", "Jahan", "Hossain", "Islam", "Iqbal", "Mahmud", "Ahmed", "Kabir"]
SUR_NAMES = ["Chowdhury", "Siddique", "Khandakar", "Sardar", "Bhuiyan", "Miah", "Sheikh", "Pramanik", "Talukdar", "Howlader"]

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data['users'] = {int(k): v for k, v in data.get('users', {}).items()}
                data['pending_requests'] = {int(k): v for k, v in data.get('pending_requests', {}).items()}
                if 'force_channels' not in data:
                    data['force_channels'] = []
                if 'tasks_status' not in data:
                    data['tasks_status'] = {'facebook': True, 'gmail': True}
                if 'available_tasks' not in data:
                    data['available_tasks'] = {'gmail': [], 'facebook': []}
                if 'config' not in data:
                    data['config'] = {}
                data['config'].setdefault('fb_pass', "Maruf@123")
                data['config'].setdefault('gmail_pass', "Maruf@gmail")
                data['config'].setdefault('fb_rate', 10.0)
                data['config'].setdefault('gmail_rate', 16.0)
                data['config'].setdefault('refer_instant', 1.0)
                data['config'].setdefault('refer_commission', 0.10)
                data['config'].setdefault('min_withdraw', 50.0)
                data['config'].setdefault('payment_channel', "https://t.me/your_payment_channel")
                data['config'].setdefault('support_username', "jh_husain_00")
                return data
        except Exception as e:
            logger.error(f"Error loading data: {e}")
    
    return {
        'users': {},
        'config': {
            'fb_rate': 10.0,
            'gmail_rate': 16.0,
            'refer_instant': 1.0,
            'refer_commission': 0.10,
            'min_withdraw': 50.0,
            'payment_channel': "https://t.me/your_payment_channel",
            'support_username': "jh_husain_00",
            'fb_pass': "Maruf@123",
            'gmail_pass': "Maruf@gmail"
        },
        'tasks_status': {'facebook': True, 'gmail': True},
        'available_tasks': {'gmail': [], 'facebook': []},
        'pending_requests': {},
        'request_counter': 1,
        'force_channels': []
    }

def save_data():
    try:
        data_to_save = {
            'users': {str(k): v for k, v in users.items()},
            'pending_requests': {str(k): v for k, v in pending_requests.items()},
            'config': config,
            'tasks_status': tasks_status,
            'available_tasks': available_tasks,
            'request_counter': db.get('request_counter', 1),
            'force_channels': force_channels
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving data: {e}")

db = load_data()
config = db['config']
users = db['users']
tasks_status = db['tasks_status']
available_tasks = db['available_tasks']
pending_requests = db['pending_requests']
force_channels = db['force_channels']

# --- CONVERSATION STATES ---
BAL_USER, BAL_ACTION, BAL_AMT = range(1, 4)
EDIT_CONFIG_VAL = 4
WITHDRAW_METHOD, WITHDRAW_NUM, WITHDRAW_AMT = range(5, 8)
ADD_TASK_TYPE, ADD_TASK_COUNT = range(8, 10)
ADD_CHANNEL_INPUT = 10
FB_SUBMIT_UID, FB_SUBMIT_COOKIES = range(11, 13)
BROADCAST_MSG = 13

def init_user(user_id, referrer_id=None):
    if user_id not in users:
        users[user_id] = {'balance': 0.0, 'referred_by': None, 'ref_count': 0, 'completed_tasks': 0}
        if referrer_id and referrer_id in users and referrer_id != user_id:
            users[user_id]['referred_by'] = referrer_id
            users[referrer_id]['balance'] += config['refer_instant']
            users[referrer_id]['ref_count'] += 1
            save_data()
            return referrer_id
        save_data()
    return None

def get_user_balance(user_id):
    init_user(user_id)
    return users[user_id]['balance']

# --- FORCE JOIN CHECKER ---
async def check_force_join(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if user_id == ADMIN_ID:
        return True
    for ch in force_channels:
        try:
            member = await context.bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            pass
    return True

async def send_force_join_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = []
    for idx, ch in enumerate(force_channels, 1):
        ch_link = f"https://t.me/{ch.replace('@', '')}" if ch.startswith("@") else ch
        kb.append([InlineKeyboardButton(f"📢 Join Channel {idx}", url=ch_link)])
    kb.append([InlineKeyboardButton("✅ Verify / Check Membership", callback_data="check_verify")])
    
    text = "⚠️ **আমাদের বটের সার্ভিস ব্যবহার করতে আপনাকে নিচের চ্যানেলে জয়েন করতে হবে।**\n\nজয়েন করার পর **Verify** বাটনে ক্লিক করুন:"
    reply_markup = InlineKeyboardMarkup(kb)
    
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# --- MAIN MENU & START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    referrer_id = int(args[0]) if args and args[0].isdigit() else None
    ref_notifier = init_user(user_id, referrer_id)
    
    if ref_notifier:
        try:
            await context.bot.send_message(
                chat_id=ref_notifier,
                text=f"🎉 আপনার রেফার লিংকে একজন নতুন ইউজার জয়েন করেছেন! আপনি ৳{config['refer_instant']} ইনস্ট্যান্ট রেফার বোনাস পেয়েছেন।"
            )
        except Exception: pass

    if not await check_force_join(user_id, context):
        await send_force_join_msg(update, context)
        return

    keyboard = [
        [InlineKeyboardButton("Jobs Work 💼", callback_data="jobs_menu")],
        [InlineKeyboardButton("My Balance 💰", callback_data="my_balance"),
         InlineKeyboardButton("Withdraw 💸", callback_data="withdraw")],
        [InlineKeyboardButton("Refer & Earn 👥", callback_data="referral")],
        [InlineKeyboardButton("Payment Channel 📢", url=config['payment_channel']),
         InlineKeyboardButton("Support 👨‍💻", url=f"https://t.me/{config['support_username'].replace('@', '')}")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        
    await update.message.reply_text(
        "👋 **4X INCOME ZONE** বটে স্বাগতম!\nনিচে থেকে আপনার প্রয়োজনীয় অপশন সিলেক্ট করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "check_verify":
        if await check_force_join(user_id, context):
            await query.message.reply_text("✅ ভেরিফিকেশন সফল হয়েছে! এখন সার্ভিস ব্যবহার করতে পারবেন।")
            keyboard = [
                [InlineKeyboardButton("Jobs Work 💼", callback_data="jobs_menu")],
                [InlineKeyboardButton("My Balance 💰", callback_data="my_balance"),
                 InlineKeyboardButton("Withdraw 💸", callback_data="withdraw")],
                [InlineKeyboardButton("Refer & Earn 👥", callback_data="referral")],
                [InlineKeyboardButton("Payment Channel 📢", url=config['payment_channel']),
                 InlineKeyboardButton("Support 👨‍💻", url=f"https://t.me/{config['support_username'].replace('@', '')}")]
            ]
            if user_id == ADMIN_ID:
                keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
            await query.message.reply_text("👋 **Main Menu:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await query.answer("❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি অথবা জয়েন করে লিভ নিয়েছেন!", show_alert=True)
        return

    if not await check_force_join(user_id, context):
        await send_force_join_msg(update, context)
        return

    if data == "jobs_menu":
        fb_is_on = tasks_status.get('facebook', True)
        gmail_is_on = tasks_status.get('gmail', True)
        
        fb_text = f"Facebook Work 📘 (৳{config['fb_rate']})" if fb_is_on else "Facebook Work 📘 (OFF 🔴)"
        gmail_text = f"Gmail Work 📧 (৳{config['gmail_rate']})" if gmail_is_on else "Gmail Work 📧 (OFF 🔴)"
        
        kb = [
            [InlineKeyboardButton(fb_text, callback_data="work_fb")],
            [InlineKeyboardButton(gmail_text, callback_data="work_gmail")],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")]
        ]
        await query.message.edit_text("💼 **উপলব্ধ কাজসমূহ:**\nনিচে থেকে কাজের টাইপ নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("Jobs Work 💼", callback_data="jobs_menu")],
            [InlineKeyboardButton("My Balance 💰", callback_data="my_balance"),
             InlineKeyboardButton("Withdraw 💸", callback_data="withdraw")],
            [InlineKeyboardButton("Refer & Earn 👥", callback_data="referral")],
            [InlineKeyboardButton("Payment Channel 📢", url=config['payment_channel']),
             InlineKeyboardButton("Support 👨‍💻", url=f"https://t.me/{config['support_username'].replace('@', '')}")]
        ]
        if user_id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        await query.message.edit_text("👋 **Main Menu:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "my_balance":
        bal = get_user_balance(user_id)
        completed = users[user_id].get('completed_tasks', 0)
        user_pending = sum(1 for req in pending_requests.values() if req['user_id'] == user_id)
        
        text = (
            "💳 **আপনার ব্যালেন্স:**\n"
            "──────────────────\n"
            f"💰 ব্যালেন্স: {bal:.2f} BDT\n"
            f"🔒 পেন্ডিং (উইথড্র): 0.00 BDT\n"
            f"💰 Total Income: {bal:.2f} BDT\n"
            "──────────────────\n"
            f"✅ সম্পন্ন কাজ: {completed} টি\n"
            f"⏳ রিভিউতে আছে: {user_pending} টি"
        )
        await query.message.reply_text(text, parse_mode="Markdown")

    elif data == "referral":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        msg = f"👥 **রেফারেল ও আজীবন কমিশন প্রোগ্রাম**\n\n🔹 ইনস্ট্যান্ট রেফার বোনাস: ৳{config['refer_instant']}\n🔹 লাইফটাইম কমিশন: ১০%\n\n🔗 আপনার রেফারেল লিংক:\n`{ref_link}`"
        await query.message.reply_text(msg, parse_mode="Markdown")

    elif data == "admin_panel":
        if user_id != ADMIN_ID: return
        fb_st = "ON 🟢" if tasks_status.get('facebook', True) else "OFF 🔴"
        gm_st = "ON 🟢" if tasks_status.get('gmail', True) else "OFF 🔴"
        kb = [
            [InlineKeyboardButton(f"FB Task ({fb_st})", callback_data="toggle_fb"),
             InlineKeyboardButton(f"Gmail Task ({gm_st})", callback_data="toggle_gmail")],
            [InlineKeyboardButton("➕ নতুন কাজ যোগ করুন", callback_data="admin_add_task")],
            [InlineKeyboardButton(f"📋 পেন্ডিং রিভিউ ({len(pending_requests)})", callback_data="admin_review_tasks")],
            [InlineKeyboardButton("📢 ব্রডকাস্ট মেসেজ (All User)", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📢 Force Join Channel Manager", callback_data="admin_channels")],
            [InlineKeyboardButton("⚙️ রেট ও সেটিংস পরিবর্তন", callback_data="admin_settings")],
            [InlineKeyboardButton("👤 ইউজার ব্যালেন্স অ্যাড/কাট", callback_data="admin_mod_bal")]
        ]
        await query.message.reply_text("⚙️ **ADMIN PANEL**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data in ["toggle_fb", "toggle_gmail"]:
        if user_id != ADMIN_ID: return
        target = 'facebook' if data == "toggle_fb" else 'gmail'
        
        tasks_status[target] = not tasks_status.get(target, True)
        save_data()
        
        fb_st = "ON 🟢" if tasks_status.get('facebook', True) else "OFF 🔴"
        gm_st = "ON 🟢" if tasks_status.get('gmail', True) else "OFF 🔴"
        kb = [
            [InlineKeyboardButton(f"FB Task ({fb_st})", callback_data="toggle_fb"),
             InlineKeyboardButton(f"Gmail Task ({gm_st})", callback_data="toggle_gmail")],
            [InlineKeyboardButton("➕ নতুন কাজ যোগ করুন", callback_data="admin_add_task")],
            [InlineKeyboardButton(f"📋 পেন্ডিং রিভিউ ({len(pending_requests)})", callback_data="admin_review_tasks")],
            [InlineKeyboardButton("📢 ব্রডকাস্ট মেসেজ (All User)", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📢 Force Join Channel Manager", callback_data="admin_channels")],
            [InlineKeyboardButton("⚙️ রেট ও সেটিংস পরিবর্তন", callback_data="admin_settings")],
            [InlineKeyboardButton("👤 ইউজার ব্যালেন্স অ্যাড/কাট", callback_data="admin_mod_bal")]
        ]
        try:
            await query.message.edit_text("⚙️ **ADMIN PANEL**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except Exception:
            pass

    elif data == "admin_channels":
        if user_id != ADMIN_ID: return
        text = "📢 **Force Join Channels List:**\n\n"
        if not force_channels:
            text += "কোনো চ্যানেল যুক্ত করা নেই।"
        else:
            for idx, ch in enumerate(force_channels, 1):
                text += f"{idx}. `{ch}`\n"
        
        kb = [[InlineKeyboardButton("➕ চ্যানেল যোগ করুন", callback_data="add_force_channel")]]
        if force_channels:
            kb.append([InlineKeyboardButton("🗑️ চ্যানেল ডিলিট করুন", callback_data="del_force_channel")])
        kb.append([InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")])
        
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "del_force_channel":
        if user_id != ADMIN_ID: return
        if force_channels:
            del_ch = force_channels.pop(0)
            save_data()
            await query.message.reply_text(f"✅ `{del_ch}` চ্যানেলটি ডিলিট করা হয়েছে।", parse_mode="Markdown")
        else:
            await query.message.reply_text("⚠️ ডিলিট করার মতো কোনো চ্যানেল নেই।")

    elif data == "admin_settings":
        if user_id != ADMIN_ID: return
        text = (
            "⚙️ **বর্তমান এডমিন সেটিংস:**\n\n"
            f"1️⃣ FB Work Rate: ৳{config.get('fb_rate', 10.0)}\n"
            f"2️⃣ Gmail Work Rate: ৳{config.get('gmail_rate', 16.0)}\n"
            f"3️⃣ Instant Refer Bonus: ৳{config.get('refer_instant', 1.0)}\n"
            f"4️⃣ Minimum Withdraw: ৳{config.get('min_withdraw', 50.0)}\n"
            f"5️⃣ FB Default Password: `{config.get('fb_pass', 'Maruf@123')}`\n"
            f"6️⃣ Gmail Default Password: `{config.get('gmail_pass', 'Maruf@gmail')}`\n"
            f"7️⃣ Payment Channel: {config.get('payment_channel', '')}\n"
            f"8️⃣ Support Username: @{config.get('support_username', '').replace('@', '')}\n\n"
            "যেটি পরিবর্তন করতে চান নিচের বাটনে চাপ দিন:"
        )
        kb = [
            [InlineKeyboardButton("Edit FB Rate", callback_data="cfg_fb_rate"),
             InlineKeyboardButton("Edit Gmail Rate", callback_data="cfg_gmail_rate")],
            [InlineKeyboardButton("Edit FB Pass 🔑", callback_data="cfg_fb_pass"),
             InlineKeyboardButton("Edit Gmail Pass 🔑", callback_data="cfg_gmail_pass")],
            [InlineKeyboardButton("Edit Refer Bonus", callback_data="cfg_refer_instant"),
             InlineKeyboardButton("Edit Min Withdraw", callback_data="cfg_min_withdraw")],
            [InlineKeyboardButton("Edit Payment Link", callback_data="cfg_payment_channel"),
             InlineKeyboardButton("Edit Support Username", callback_data="cfg_support_username")]
        ]
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "admin_review_tasks":
        if user_id != ADMIN_ID: return
        if not pending_requests:
            await query.message.reply_text("⚠️ বর্তমানে কোনো কাজ বা উইথড্র রিকোয়েস্ট পেন্ডিং রিভিউতে নেই।")
            return

        await query.message.reply_text(f"📋 **মোট পেন্ডিং রিকোয়েস্ট: {len(pending_requests)} টি**\nনিচে বিস্তারিত দেওয়া হলো:")
        for req_id, req in list(pending_requests.items()):
            t_type = req['type']
            u_id = req['user_id']
            kb = [[InlineKeyboardButton("Approve ✅", callback_data=f"app_{req_id}"), 
                   InlineKeyboardButton("Reject ❌", callback_data=f"rej_{req_id}")]]
            
            if t_type == 'facebook':
                details = req['data']
                msg = (
                    f"📘 **পেন্ডিং ফেসবুক কাজ #{req_id}**\n"
                    f"User ID: `{u_id}`\n"
                    f"Name: `{details['name']}`\n"
                    f"Password: `{details['pass']}`\n"
                    f"UID: `{details.get('uid', 'N/A')}`\n"
                    f"Cookies: `{details.get('cookies', 'N/A')}`"
                )
            elif t_type == 'gmail':
                details = req['data']
                msg = (
                    f"📧 **পেন্ডিং জিমেইল কাজ #{req_id}**\n"
                    f"User ID: `{u_id}`\n"
                    f"Name: `{details['name']}`\n"
                    f"Email: `{details['email']}`\n"
                    f"Password: `{details['pass']}`"
                )
            else:
                details = req['data']
                msg = (
                    f"💸 **পেন্ডিং উইথড্র রিকোয়েস্ট #{req_id}**\n"
                    f"User ID: `{u_id}`\n"
                    f"Method: {details['method']}\n"
                    f"Number: `{details['num']}`\n"
                    f"Amount: ৳{details['amount']}"
                )
            await context.bot.send_message(chat_id=ADMIN_ID, text=msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data.startswith("app_") or data.startswith("rej_"):
        if user_id != ADMIN_ID: return
        action, req_id = data.split("_")[0], int(data.split("_")[1])
        req = pending_requests.get(req_id)
        if not req:
            await query.message.reply_text("⚠️ এই রিকোয়েস্টটি আগেই প্রসেস করা হয়েছে।")
            return
        target_user = req['user_id']
        
        if action == "app":
            if req['type'] in ['gmail', 'facebook']:
                earned = config['gmail_rate'] if req['type'] == 'gmail' else config['fb_rate']
                users[target_user]['balance'] += earned
                users[target_user]['completed_tasks'] = users[target_user].get('completed_tasks', 0) + 1
                msg = f"🎉 আপনার {req['type'].capitalize()} কাজটি অ্যাপ্রুভ হয়েছে! ৳{earned:.2f} ব্যালেন্সে যুক্ত করা হয়েছে।"
                
                referrer = users[target_user].get('referred_by')
                if referrer and referrer in users:
                    commission = earned * config.get('refer_commission', 0.10)
                    users[referrer]['balance'] += commission
                    save_data()
                    try:
                        await context.bot.send_message(chat_id=referrer, text=f"🎁 **১০% রেফার কমিশন পাওয়া গেছে!**\nআপনার রেফারের একটি কাজ অ্যাপ্রুভ হওয়ায় ৳{commission:.2f} বোনাস যোগ হয়েছে।")
                    except Exception: pass
            elif req['type'] == 'withdraw':
                msg = f"🎉 আপনার ৳{req['data']['amount']} উইথড্র সফল হয়েছে!"
            
            try: await context.bot.send_message(chat_id=target_user, text=msg)
            except Exception: pass
            await query.message.edit_text(f"✅ Approved: Request #{req_id}")
        else:
            if req['type'] == 'withdraw':
                users[target_user]['balance'] += req['data']['amount']
                msg = f"❌ আপনার ৳{req['data']['amount']} উইথড্র রিকোয়েস্ট বাতিল করা হয়েছে।"
            else:
                msg = "❌ আপনার কাজটি এডমিন রিজেক্ট করেছেন।"
            try: await context.bot.send_message(chat_id=target_user, text=msg)
            except Exception: pass
            await query.message.edit_text(f"❌ Rejected: Request #{req_id}")
            
        del pending_requests[req_id]
        save_data()

    elif data == "work_gmail":
        if not tasks_status.get('gmail', True):
            await query.message.reply_text("🔴 দুঃখিত, Gmail-এর কাজ বর্তমানে বন্ধ রয়েছে।")
            return

        if not available_tasks.get('gmail'):
            await query.message.reply_text("⚠️ বর্তমানে কোনো Gmail কাজ এভেইলএবল নেই।")
            return

        task = available_tasks['gmail'].pop(0)
        context.user_data['current_task'] = task
        context.user_data['task_type'] = "gmail"
        save_data()

        msg = (
            "📧 **আপনার জন্য নতুন জিমেইল কাজ বরাদ্দ করা হয়েছে!**\n\n"
            f"👤 Name: `{task['name']}`\n"
            f"✉️ Email: `{task['email']}`\n"
            f"🔑 Password: `{task['pass']}`\n\n"
            "📌 অ্যাকাউন্ট তৈরি শেষ হলে নিচে **📥 কাজ সাবমিট করুন** বাটনে চাপ দিন।"
        )
        kb = [[InlineKeyboardButton("📥 কাজ সাবমিট করুন", callback_data="submit_gmail_task")],
              [InlineKeyboardButton("⬅️ ফিরে যান", callback_data="jobs_menu")]]
        await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "submit_gmail_task":
        task = context.user_data.get('current_task')
        if not task:
            await query.message.reply_text("⚠️ আপনার কোনো সক্রিয় কাজ পাওয়া যায়নি।")
            return

        req_id = db['request_counter']
        pending_requests[req_id] = {'user_id': user_id, 'type': 'gmail', 'data': task}
        db['request_counter'] += 1
        save_data()

        context.user_data.pop('current_task', None)
        context.user_data.pop('task_type', None)

        await query.message.reply_text("✅ আপনার কাজটি সফলভাবে রিভিউয়ের জন্য সাবমিট করা হয়েছে!")

        admin_text = f"📥 **New Gmail Task Submission** (#{req_id})\nUser ID: `{user_id}`\nDetails: `{task}`"
        kb = [[InlineKeyboardButton("Approve ✅", callback_data=f"app_{req_id}"), InlineKeyboardButton("Reject ❌", callback_data=f"rej_{req_id}")]]
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except Exception: pass

# --- BROADCAST SYSTEM ---
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    
    await query.message.reply_text("📢 **সব ইউজারকে যে মেসেজ, ফটো বা ভিডিও পাঠাতে চান তা এখানে সেন্ড করুন:**")
    return BROADCAST_MSG

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    
    msg = update.message
    total_users = len(users)
    success = 0
    failed = 0

    status_msg = await update.message.reply_text(f"🚀 **ব্রডকাস্ট শুরু হয়েছে...**\nমোট ইউজার: {total_users}")

    for u_id in list(users.keys()):
        try:
            await context.bot.copy_message(
                chat_id=u_id,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id
            )
            success += 1
            await asyncio.sleep(0.05)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await context.bot.copy_message(
                    chat_id=u_id,
                    from_chat_id=msg.chat_id,
                    message_id=msg.message_id
                )
                success += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ **ব্রডকাস্ট সম্পন্ন হয়েছে!**\n\n"
        f"🎯 সফলভাবে পাঠানো হয়েছে: {success} জন\n"
        f"❌ ব্যর্থ (ব্লক করেছে): {failed} জন"
    )
    return ConversationHandler.END

# --- FACEBOOK WORKFLOW ---
async def start_fb_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not tasks_status.get('facebook', True):
        await query.message.reply_text("🔴 দুঃখিত, Facebook-এর কাজ বর্তমানে বন্ধ রয়েছে।")
        return ConversationHandler.END

    if not available_tasks.get('facebook'):
        await query.message.reply_text("⚠️ বর্তমানে কোনো Facebook কাজ এভেইলএবল নেই। এডমিন কাজ যোগ করার পর চেষ্টা করুন।")
        return ConversationHandler.END

    task = available_tasks['facebook'].pop(0)
    context.user_data['current_fb_task'] = task
    save_data()

    msg = (
        "📘 **আপনার জন্য নতুন ফেসবুক কাজ বরাদ্দ করা হয়েছে!**\n\n"
        f"👤 Name: `{task['name']}`\n"
        f"🔑 Password: `{task['pass']}`\n\n"
        "📌 অ্যাকাউন্ট তৈরি শেষ হলে নিচে **📥 কাজ সাবমিট করুন** বাটনে চাপ দিন।"
    )
    kb = [[InlineKeyboardButton("📥 কাজ সাবমিট করুন", callback_data="fb_click_submit")]]
    await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return FB_SUBMIT_UID

async def fb_ask_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("👉 এবার তৈরি করা ফেসবুক আইডির **UID (User ID)** লিখুন:")
    return FB_SUBMIT_COOKIES

async def fb_ask_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid_val = update.message.text.strip()
    context.user_data['fb_uid'] = uid_val
    await update.message.reply_text("👉 এবার আইডির **Cookies** পাঠান:")
    return FB_SUBMIT_COOKIES + 1

async def fb_save_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cookies_val = update.message.text.strip()
    user_id = update.effective_user.id
    task = context.user_data.get('current_fb_task')
    uid_val = context.user_data.get('fb_uid')

    if not task:
        await update.message.reply_text("⚠️ কোনো সক্রিয় ফেসবুক কাজ পাওয়া যায়নি।")
        return ConversationHandler.END

    task['uid'] = uid_val
    task['cookies'] = cookies_val

    req_id = db['request_counter']
    pending_requests[req_id] = {'user_id': user_id, 'type': 'facebook', 'data': task}
    db['request_counter'] += 1
    save_data()

    context.user_data.pop('current_fb_task', None)
    context.user_data.pop('fb_uid', None)

    await update.message.reply_text("✅ আপনার ফেসবুক কাজটি সফলভাবে রিভিউয়ের জন্য সাবমিট করা হয়েছে!")

    admin_text = (
        f"📥 **New Facebook Submission** (#{req_id})\n"
        f"User ID: `{user_id}`\n"
        f"Name: `{task['name']}`\n"
        f"Pass: `{task['pass']}`\n"
        f"UID: `{uid_val}`\n"
        f"Cookies: `{cookies_val}`"
    )
    kb = [[InlineKeyboardButton("Approve ✅", callback_data=f"app_{req_id}"), InlineKeyboardButton("Reject ❌", callback_data=f"rej_{req_id}")]]
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    except Exception: pass

    return ConversationHandler.END

# --- ADD FORCE JOIN CHANNEL HANDLER ---
async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("👉 চ্যানেলের **Username** (যেমন: `@MyChannel`) অথবা **ID** পাঠান:\n\n⚠️ *মনে রাখবেন:* বটকে ওই চ্যানেলে এডমিন বানাতে হবে।")
    return ADD_CHANNEL_INPUT

async def save_force_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch_text = update.message.text.strip()
    if ch_text not in force_channels:
        force_channels.append(ch_text)
        save_data()
        await update.message.reply_text(f"✅ চ্যানেল `{ch_text}` সফলভাবে Force Join লিস্টে যোগ করা হয়েছে!", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ চ্যানেলটি ইতিমধ্যেই যুক্ত রয়েছে।")
    return ConversationHandler.END

# --- ADMIN ADD TASK WORKFLOW ---
async def start_add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    
    kb = [[InlineKeyboardButton("Gmail Task 📧", callback_data="add_t_gmail"),
           InlineKeyboardButton("FB Task 📘", callback_data="add_t_fb")]]
    await query.message.reply_text("👉 কোন ধরণের কাজ যুক্ত করতে চান সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(kb))
    return ADD_TASK_TYPE

async def get_add_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    t_type = "gmail" if query.data == "add_t_gmail" else "facebook"
    context.user_data['new_task_type'] = t_type
    
    await query.message.reply_text(f"👉 কতটি **{t_type.capitalize()}** কাজ যুক্ত করতে চান (সংখ্যা লিখুন, যেমন: 10):", parse_mode="Markdown")
    return ADD_TASK_COUNT

async def save_new_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t_type = context.user_data.get('new_task_type', 'facebook')
    text_val = update.message.text.strip()
    
    if not text_val.isdigit():
        await update.message.reply_text("❌ ভুল ইনপুট! শুধুমাত্র সংখ্যা লিখুন (যেমন: 5 বা 10)।")
        return ADD_TASK_COUNT

    count = int(text_val)

    if 'available_tasks' not in db or not isinstance(db['available_tasks'], dict):
        available_tasks = {'gmail': [], 'facebook': []}
        db['available_tasks'] = available_tasks
    else:
        available_tasks = db['available_tasks']
        if t_type not in available_tasks:
            available_tasks[t_type] = []

    for _ in range(count):
        f_name = random.choice(FIRST_NAMES)
        m_name = random.choice(MIDDLE_NAMES)
        s_name = random.choice(SUR_NAMES)
        full_name = f"{f_name} {m_name} {s_name}"
        
        if t_type == "gmail":
            rand_digits = random.randint(100000, 999999)
            email_user = f"{f_name.lower()}{m_name.lower()}{s_name.lower()}{rand_digits}@gmail.com"
            gmail_pass = config.get('gmail_pass', 'Maruf@gmail')
            
            new_task = {
                'name': full_name,
                'email': email_user,
                'pass': gmail_pass
            }
            available_tasks['gmail'].append(new_task)
        else:
            fb_pass = config.get('fb_pass', 'Maruf@123')
            new_task = {
                'name': full_name,
                'pass': fb_pass
            }
            available_tasks['facebook'].append(new_task)

    try:
        save_data()
        await update.message.reply_text(f"✅ সফলভাবে {count} টি নতুন **{t_type.capitalize()}** কাজ যুক্ত করা হয়েছে!", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Task save error: {e}")
        await update.message.reply_text("❌ ডেটা সেভ করতে সমস্যা হয়েছে, আবার চেষ্টা করুন।")

    context.user_data.pop('new_task_type', None)
    return ConversationHandler.END

# --- ADMIN CONFIG EDIT WORKFLOW ---
async def start_cfg_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("cfg_", "")
    context.user_data['edit_key'] = key
    
    prompts = {
        'fb_rate': "👉 Facebook কাজের নতুন রেট (টাকা) কত দিতে চান লিখুন:",
        'gmail_rate': "👉 Gmail কাজের নতুন রেট (টাকা) কত দিতে চান লিখুন:",
        'fb_pass': "👉 Facebook অ্যাকাউন্টের জন্য নতুন ডিফল্ট পাসওয়ার্ড লিখুন:",
        'gmail_pass': "👉 Gmail অ্যাকাউন্টের জন্য নতুন ডিফল্ট পাসওয়ার্ড লিখুন:",
        'refer_instant': "👉 ইনস্ট্যান্ট রেফার বোনাসের নতুন পরিমাণ (টাকা) লিখুন:",
        'min_withdraw': "👉 সর্বনিম্ন উইথড্র পরিমাণ (টাকা) কত দিতে চান লিখুন:",
        'payment_channel': "👉 পেমেন্ট চ্যানেলের নতুন লিংক লিখুন:",
        'support_username': "👉 সাপোর্ট ইউজারনেম লিখুন (যেমন: jh_husain_00):"
    }
    await query.message.reply_text(prompts.get(key, "নতুন মান টাইপ করুন:"))
    return EDIT_CONFIG_VAL

async def save_cfg_val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.user_data.get('edit_key')
    val_text = update.message.text.strip()
    
    try:
        if key in ['fb_rate', 'gmail_rate', 'refer_instant', 'min_withdraw']:
            config[key] = float(val_text)
        else:
            config[key] = val_text
            if key == 'fb_pass':
                for t in available_tasks.get('facebook', []):
                    t['pass'] = val_text
            elif key == 'gmail_pass':
                for t in available_tasks.get('gmail', []):
                    t['pass'] = val_text
            
        save_data()
        await update.message.reply_text(f"✅ **{key.upper().replace('_', ' ')}** সফলভাবে পরিবর্তন করা হয়েছে!\n✨ নতুন মান: `{val_text}`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ভুল তথ্য! সঠিক সংখ্যা লিখুন।")
        
    return ConversationHandler.END

# --- ADMIN BALANCE MOD WORKFLOW ---
async def start_mod_bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("👉 ব্যালেন্স পরিবর্তন করতে ব্যবহারকারীর **Telegram User ID** দিন:")
    return BAL_USER

async def get_bal_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['target_user'] = int(update.message.text.strip())
        kb = [
            [InlineKeyboardButton("Add Balance ➕", callback_data="bal_add"),
             InlineKeyboardButton("Deduct Balance ➖", callback_data="bal_sub")]
        ]
        await update.message.reply_text("👉 আপনি কী করতে চান সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(kb))
        return BAL_ACTION
    except ValueError:
        await update.message.reply_text("❌ ভুল User ID! শুধুমাত্র সংখ্যা দিন।")
        return ConversationHandler.END

async def get_bal_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['bal_action'] = query.data
    action_name = "যোগ করতে" if query.data == "bal_add" else "কাটতে/বিয়োগ করতে"
    await query.message.reply_text(f"👉 কত টাকা {action_name} চান তার পরিমাণ লিখুন:")
    return BAL_AMT

async def save_bal_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
        t_user = context.user_data['target_user']
        action = context.user_data['bal_action']
        
        get_user_balance(t_user)
        
        if action == "bal_add":
            users[t_user]['balance'] += amt
            msg = f"✅ User `{t_user}`-এর ব্যালেন্সে ৳{amt:.2f} যোগ করা হয়েছে। নতুন ব্যালেন্স: ৳{users[t_user]['balance']:.2f}"
            try: await context.bot.send_message(chat_id=t_user, text=f"🎉 এডমিন আপনার ব্যালেন্সে ৳{amt:.2f} যোগ করেছেন।")
            except Exception: pass
        else:
            users[t_user]['balance'] -= amt
            if users[t_user]['balance'] < 0: users[t_user]['balance'] = 0.0
            msg = f"✅ User `{t_user}`-এর ব্যালেন্স থেকে ৳{amt:.2f} কেটে নেওয়া হয়েছে। নতুন ব্যালেন্স: ৳{users[t_user]['balance']:.2f}"
            try: await context.bot.send_message(chat_id=t_user, text=f"⚠️ এডমিন আপনার ব্যালেন্স থেকে ৳{amt:.2f} কেটে নিয়েছেন।")
            except Exception: pass

        save_data()
        await update.message.reply_text(msg, parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ভুল পরিমাণ দেওয়া হয়েছে।")
        
    return ConversationHandler.END

# --- WITHDRAW WORKFLOW ---
async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    bal = get_user_balance(user_id)

    if bal < config['min_withdraw']:
        await query.message.reply_text(f"⚠️ উইথড্র করার জন্য সর্বনিম্ন ৳{config['min_withdraw']} ব্যালেন্স প্রয়োজন।\nআপনার বর্তমান ব্যালেন্স: ৳{bal:.2f}")
        return ConversationHandler.END

    kb = [[InlineKeyboardButton("Bkash 📱", callback_data="method_bkash"), InlineKeyboardButton("Nagad 📱", callback_data="method_nagad")]]
    await query.message.reply_text("💳 পেমেন্ট নেওয়ার মাধ্যম সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(kb))
    return WITHDRAW_METHOD

async def get_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['w_method'] = "Bkash" if query.data == "method_bkash" else "Nagad"
    await query.message.reply_text(f"👉 আপনার {context.user_data['w_method']} পার্সোনাল নম্বরটি দিন:")
    return WITHDRAW_NUM

async def get_withdraw_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_num'] = update.message.text
    await update.message.reply_text("👉 কত টাকা উইথড্র করতে চান পরিমাণ লিখুন:")
    return WITHDRAW_AMT

async def get_withdraw_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_user_balance(user_id)
    
    try:
        amt = float(update.message.text)
        if amt < config['min_withdraw'] or amt > bal:
            await update.message.reply_text("❌ ব্যালেন্স পর্যাপ্ত নয় অথবা সর্বনিম্ন পরিমাণের কম।")
            return ConversationHandler.END

        users[user_id]['balance'] -= amt
        req_id = db.get('request_counter', 1)
        method = context.user_data['w_method']
        num = context.user_data['w_num']
        
        pending_requests[req_id] = {'user_id': user_id, 'type': 'withdraw', 'data': {'method': method, 'num': num, 'amount': amt}}
        db['request_counter'] = req_id + 1
        save_data()
        
        await update.message.reply_text("✅ উইথড্র রিকোয়েস্ট সফলভাবে জমা হয়েছে!")
        admin_text = f"💸 **New Withdraw Request** (#{req_id})\nUser: {update.effective_user.full_name} (`{user_id}`)\nMethod: {method}\nNumber: `{num}`\nAmount: ৳{amt}"
        kb = [[InlineKeyboardButton("Approve ✅", callback_data=f"app_{req_id}"), InlineKeyboardButton("Reject ❌", callback_data=f"rej_{req_id}")]]
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except Exception: pass
        
    except ValueError:
        await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন।")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("প্রসেস বাতিল করা হয়েছে।")
    return ConversationHandler.END

# --- RUN BOT ---
def run_bot():
    request = HTTPXRequest(
        read_timeout=15,
        write_timeout=15,
        connect_timeout=15,
        pool_timeout=15
    )
    
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_broadcast, pattern="^admin_broadcast$")],
        states={
            BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, send_broadcast)]
        }, fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True, per_user=True
    )

    fb_work_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_fb_work, pattern="^work_fb$")],
        states={
            FB_SUBMIT_UID: [CallbackQueryHandler(fb_ask_uid, pattern="^fb_click_submit$")],
            FB_SUBMIT_COOKIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, fb_ask_cookies)],
            FB_SUBMIT_COOKIES + 1: [MessageHandler(filters.TEXT & ~filters.COMMAND, fb_save_task)]
        }, fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True, per_user=True
    )

    add_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_channel, pattern="^add_force_channel$")],
        states={
            ADD_CHANNEL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_force_channel)],
        }, fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True, per_user=True
    )

    add_task_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_task, pattern="^admin_add_task$")],
        states={
            ADD_TASK_TYPE: [CallbackQueryHandler(get_add_task_type, pattern="^add_t_")],
            ADD_TASK_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_task)],
        }, fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True, per_user=True
    )

    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_withdraw, pattern="^withdraw$")],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(get_withdraw_method, pattern="^method_")],
            WITHDRAW_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_withdraw_num)],
            WITHDRAW_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_withdraw_amt)],
        }, fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True, per_user=True
    )

    bal_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_mod_bal, pattern="^admin_mod_bal$")],
        states={
            BAL_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bal_user)],
            BAL_ACTION: [CallbackQueryHandler(get_bal_action, pattern="^bal_")],
            BAL_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_bal_amt)]
        }, fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True, per_user=True
    )

    cfg_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_cfg_edit, pattern="^cfg_")],
        states={
            EDIT_CONFIG_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_cfg_val)]
        }, fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True, per_user=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(broadcast_conv)
    app.add_handler(fb_work_conv)
    app.add_handler(add_channel_conv)
    app.add_handler(add_task_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(bal_conv)
    app.add_handler(cfg_conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Starting Telegram Bot...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    run_bot()
