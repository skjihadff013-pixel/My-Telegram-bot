import logging
import time
import json
import random
import os
import asyncio
import nest_asyncio
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, ConversationHandler, ContextTypes, filters
)
from telegram.error import TelegramError, RetryAfter
from telegram.request import HTTPXRequest

# --- RENDER PORT BINDING & UPTIMEROBOT WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Number Bot is alive and running on Render with MongoDB!")

    def log_message(self, format, *args):
        return

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    httpd.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

nest_asyncio.apply()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION & GLOBAL SETTINGS ---
ADMIN_ID = 7125334953
BOT_TOKEN = "8914904533:AAHIkpWEsNlVmf0n1NhJa9NvwTEJXQPL828"
BOT_USERNAME = "incomezone4xbot"

# --- MINOSMS API SETTINGS ---
MINOSMS_API_KEY = "mino_live_d1d31e698862d84215537abec24fae3d"
MINOSMS_BASE_URL = "https://minosms.com"

# --- MONGODB CONNECTION SETUP ---
MONGO_URI = "mongodb+srv://skjihaddff013_db_user:cHMY5LhFbWYwQW6Y@cluster0.79uxlie.mongodb.net/?appName=Cluster0"
mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client['incomezone_bot_db']
bot_data_col = mongo_db['bot_state']

def load_data():
    try:
        doc = bot_data_col.find_one({"_id": "number_bot_main_data"})
        if doc:
            data = doc.get('data', {})
            data['users'] = {int(k): v for k, v in data.get('users', {}).items()}
            data['pending_requests'] = {int(k): v for k, v in data.get('pending_requests', {}).items()}
            
            if 'force_channels' not in data:
                data['force_channels'] = []
            if 'config' not in data:
                data['config'] = {}
                
            data['config'].setdefault('refer_instant', 1.0)
            data['config'].setdefault('refer_commission', 0.10)
            data['config'].setdefault('min_withdraw', 50.0)
            data['config'].setdefault('payment_channel', "https://t.me/your_payment_channel")
            data['config'].setdefault('support_username', "jh_husain_00")
            data['config'].setdefault('otp_reward', 0.20) # প্রতি ওটিপির জন্য ২০ পয়সা রিওয়ার্ড
            data.setdefault('request_counter', 1)
            return data
    except Exception as e:
        logger.error(f"Error loading data from MongoDB: {e}")
    
    return {
        'users': {},
        'config': {
            'refer_instant': 1.0,
            'refer_commission': 0.10,
            'min_withdraw': 50.0,
            'payment_channel': "https://t.me/your_payment_channel",
            'support_username': "jh_husain_00",
            'otp_reward': 0.20
        },
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
            'request_counter': db.get('request_counter', 1),
            'force_channels': force_channels
        }
        bot_data_col.update_one(
            {"_id": "number_bot_main_data"},
            {"$set": {"data": data_to_save}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving data to MongoDB: {e}")

db = load_data()
config = db['config']
users = db['users']
pending_requests = db['pending_requests']
force_channels = db['force_channels']

# --- CONVERSATION STATES ---
WITHDRAW_METHOD, WITHDRAW_NUM, WITHDRAW_AMT = range(1, 4)
GET_NUM_RANGE = 4

def init_user(user_id, referrer_id=None):
    if user_id not in users:
        users[user_id] = {'balance': 0.0, 'referred_by': None, 'ref_count': 0, 'otps_received': 0}
        if referrer_id and referrer_id in users and referrer_id != user_id:
            users[user_id]['referred_by'] = referrer_id
            users[referrer_id]['balance'] += config.get('refer_instant', 1.0)
            users[referrer_id]['ref_count'] = users[referrer_id].get('ref_count', 0) + 1
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
    
    text = "⚠️ **বটের সার্ভিস ব্যবহার করতে আপনাকে নিচের চ্যানেলে জয়েন করতে হবে।**\n\nজয়েন করার পর **Verify** বাটনে ক্লিক করুন:"
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
        [InlineKeyboardButton("🔥 Live Access & Numbers", callback_data="live_access_menu")],
        [InlineKeyboardButton("📱 Get Virtual Number", callback_data="get_num_prompt")],
        [InlineKeyboardButton("My Balance 💰", callback_data="my_balance"),
         InlineKeyboardButton("Withdraw 💸", callback_data="withdraw")],
        [InlineKeyboardButton("Refer & Earn 👥", callback_data="referral")],
        [InlineKeyboardButton("Payment Channel 📢", url=config['payment_channel']),
         InlineKeyboardButton("Support 👨‍💻", url=config['support_username'] if config['support_username'].startswith("http") else f"https://t.me/{config['support_username'].replace('@', '')}")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        
    await update.message.reply_text(
        "👋 **Virtual Number & OTP Bot**-এ স্বাগতম!\nনিচে থেকে আপনার প্রয়োজনীয় অপশন সিলেক্ট করুন:",
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
            await query.message.reply_text("✅ ভেরিফিকেশন সফল হয়েছে!")
            keyboard = [
                [InlineKeyboardButton("🔥 Live Access & Numbers", callback_data="live_access_menu")],
                [InlineKeyboardButton("📱 Get Virtual Number", callback_data="get_num_prompt")],
                [InlineKeyboardButton("My Balance 💰", callback_data="my_balance"),
                 InlineKeyboardButton("Withdraw 💸", callback_data="withdraw")],
                [InlineKeyboardButton("Refer & Earn 👥", callback_data="referral")],
                [InlineKeyboardButton("Payment Channel 📢", url=config['payment_channel']),
                 InlineKeyboardButton("Support 👨‍💻", url=config['support_username'] if config['support_username'].startswith("http") else f"https://t.me/{config['support_username'].replace('@', '')}")]
            ]
            if user_id == ADMIN_ID:
                keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
            await query.message.reply_text("👋 **Main Menu:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await query.answer("❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি!", show_alert=True)
        return

    if not await check_force_join(user_id, context):
        await send_force_join_msg(update, context)
        return

    if data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("🔥 Live Access & Numbers", callback_data="live_access_menu")],
            [InlineKeyboardButton("📱 Get Virtual Number", callback_data="get_num_prompt")],
            [InlineKeyboardButton("My Balance 💰", callback_data="my_balance"),
             InlineKeyboardButton("Withdraw 💸", callback_data="withdraw")],
            [InlineKeyboardButton("Refer & Earn 👥", callback_data="referral")],
            [InlineKeyboardButton("Payment Channel 📢", url=config['payment_channel']),
             InlineKeyboardButton("Support 👨‍💻", url=config['support_username'] if config['support_username'].startswith("http") else f"https://t.me/{config['support_username'].replace('@', '')}")]
        ]
        if user_id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        await query.message.edit_text("👋 **Main Menu:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "live_access_menu":
        # Minosms liveaccess.php কল করা
        url = f"{MINOSMS_BASE_URL}/liveaccess.php?api_key={MINOSMS_API_KEY}"
        try:
            res = requests.get(url, timeout=10)
            result = res.json()
            
            text = "🌐 **Live Number Traffic & Active Ranges:**\n\n"
            if isinstance(result, list) and len(result) > 0:
                for item in result[:10]: # টপ ১০ টি দেখানোর জন্য
                    text += f"🔹 Range/Info: `{item}`\n"
            elif isinstance(result, dict):
                text += f"📦 Response: `{json.dumps(result, indent=2)}`\n"
            else:
                text += "বর্তমানে কোনো লাইভ রেঞ্জ ডাটা পাওয়া যায়নি।"
                
            kb = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="live_access_menu")],
                [InlineKeyboardButton("📱 নাম্বার নিন (Get Number)", callback_data="get_num_prompt")],
                [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
            ]
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except Exception as e:
            await query.message.edit_text(f"❌ লাইভ এক্সেস ফেচ করতে সমস্যা হয়েছে: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]))

    elif data == "my_balance":
        bal = get_user_balance(user_id)
        otps = users[user_id].get('otps_received', 0)
        
        text = (
            "💳 **আপনার অ্যাকাউন্ট ব্যালেন্স:**\n"
            "──────────────────\n"
            f"💰 মূল ব্যালেন্স: ৳{bal:.2f} BDT\n"
            f"📥 সফল ওটিপি রিসিভ: {otps} টি\n"
            f"🎁 প্রতি ওটিপি রিওয়ার্ড: ৳{config.get('otp_reward', 0.20)}\n"
            "──────────────────"
        )
        kb = [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "referral":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        msg = f"👥 **রেফারেল ও কমিশন প্রোগ্রাম**\n\n🔹 ইনস্ট্যান্ট রেফার বোনাস: ৳{config['refer_instant']}\n🔹 লাইফটাইম কমিশন: ১০%\n\n🔗 আপনার রেফারেল লিংক:\n`{ref_link}`"
        kb = [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "admin_panel":
        if user_id != ADMIN_ID: return
        kb = [
            [InlineKeyboardButton("📢 ব্রডকাস্ট মেসেজ", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📢 Force Join Channels", callback_data="admin_channels")],
            [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
        ]
        await query.message.edit_text("⚙️ **ADMIN PANEL**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# --- NUMBER ALLOCATION & CHECK WORKFLOW ---
async def get_num_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "📱 **ভার্চুয়াল নাম্বার নেওয়ার জন্য টার্গেট রেঞ্জ দিন:**\n\n"
        "উদাহরণস্বরূপ: `88017XXX` বা আপনার নির্দিষ্ট রেঞ্জ লিখে পাঠান।"
    )
    return GET_NUM_RANGE

async def process_get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rid = update.message.text.strip()
    
    url = f"{MINOSMS_BASE_URL}/getnumber.php"
    headers = {"mauthapi": MINOSMS_API_KEY}
    payload = {"rid": rid}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        data = response.json()
        
        await update.message.reply_text(f"🌐 **API Response:**\n`{json.dumps(data, indent=2)}`", parse_mode="Markdown")
        
        # এখানে স্বয়ংক্রিয়ভাবে ওটিপি চেক করার লজিক বা ইনফো দিতে পারেন
    except Exception as e:
        await update.message.reply_text(f"❌ নাম্বার নিতে গিয়ে ত্রুটি ঘটেছে: {str(e)}")
        
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
        admin_text = f"💸 **New Withdraw Request** (#{req_id})\nUser ID: `{user_id}`\nMethod: {method}\nNumber: `{num}`\nAmount: ৳{amt}"
        kb = [[InlineKeyboardButton("Approve ✅", callback_data=f"app_{req_id}"), InlineKeyboardButton("Reject ❌", callback_data=f"rej_{req_id})"]]
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
    request = HTTPXRequest(read_timeout=15, write_timeout=15, connect_timeout=15, pool_timeout=15)
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    num_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(get_num_prompt, pattern="^get_num_prompt$")],
        states={
            GET_NUM_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_get_number)]
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(num_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Starting Premium Number & OTP Bot with MongoDB...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    run_bot()
