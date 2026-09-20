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
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Number Bot is Alive and Running!")
        
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
BOT_TOKEN = "8914904533:AAHIKpWeSmLNfvOn1miW--incomezonex4bot"
BOT_USERNAME = "incomezonex4bot"

# MONGODB CONNECTION SETUP (এখানে আপনার সঠিক এবং সম্পূর্ণ MongoDB Atlas URI বসাবেন)
MONGO_URI = "mongodb+srv://skijihadff013-pixel:your_actual_password@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client['incomezone_bot_db']
bot_data_col = mongo_db['bot_state']

def load_data():
    try:
        doc = bot_data_col.find_one({"_id": "data"})
        if doc:
            return doc.get('data', {}), doc.get('users', {}), doc.get('pending_requests', {})
        else:
            force_channels = ['@IncomeZoneChannel', '@IncomeZoneChat']
            config = {'force_channels': force_channels, 'min_withdraw': 30.0}
            bot_data_col.insert_one({"_id": "data", "data": {}, "users": {}, "pending_requests": {}, "config": config})
            return {}, {}, {}
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return {}, {}, {}

def save_data():
    try:
        bot_data_col.update_one(
            {"_id": "data"},
            {"$set": {"data": data, "users": users, "pending_requests": pending_requests, "config": config}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving data: {e}")

data, users, pending_requests = load_data()
config_doc = bot_data_col.find_one({"_id": "data"})
config = config_doc.get('config', {
    'force_channels': ['@IncomeZoneChannel', '@IncomeZoneChat'],
    'min_withdraw': 30.0
}) if config_doc else {
    'force_channels': ['@IncomeZoneChannel', '@IncomeZoneChat'],
    'min_withdraw': 30.0
}

WITHDRAW_METHOD, WITHDRAW_AMT = range(2)

# --- HELPER FUNCTIONS ---
def is_admin(user_id):
    return user_id == ADMIN_ID

async def check_force_join(user_id, context):
    if user_id == ADMIN_ID:
        return True
    for ch in config.get('force_channels', []):
        try:
            member = await context.bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            pass
    return True

def send_force_join_msg(update: Update):
    kb = []
    for ch in config.get('force_channels', []):
        kb.append([InlineKeyboardButton(f"📢 Join {ch}", url=f"https://t.me/{ch.replace('@', '')}")])
    kb.append([InlineKeyboardButton("🔄 Joined Check", callback_data="check_join")])
    text = "⚠️ **আমাদের বটটি ব্যবহার করতে হলে অবশ্যই নিচের চ্যানেলগুলোতে জয়েন করতে হবে!**\n\nজয়েন করার পর নিচের বাটনে চাপ দিন।"
    if update.callback_query:
        return update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        return update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# --- START & MAIN MENU ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_force_join(user_id, context):
        await send_force_join_msg(update)
        return

    if str(user_id) not in users:
        users[str(user_id)] = {
            'balance': 0.0,
            'total_otp': 0,
            'referrals': 0,
            'status': 'Active'
        }
        if context.args:
            try:
                ref_id = int(context.args[0])
                if str(ref_id) in users and ref_id != user_id:
                    users[str(ref_id)]['balance'] += 0.2
                    users[str(ref_id)]['referrals'] += 1
            except:
                pass
        save_data()

    text = (
        f"🤖 **4X INCOME ZONE বটে স্বাগতম!**\n\n"
        f"নিচে থেকে আপনার প্রয়োজনীয় অপশন সিলেক্ট করুন:"
    )
    kb = [
        [InlineKeyboardButton("📱 GET NUMBER", callback_data="get_number"), InlineKeyboardButton("⚡ 2FA ONLINE", callback_data="ifa_online")],
        [InlineKeyboardButton("👥 Refer & Earn 💵", callback_data="refer"), InlineKeyboardButton("💸 WITHDRAWAL", callback_data="withdraw")],
        [InlineKeyboardButton("💳 Payment Channel", url="https://t.me/"), InlineKeyboardButton("🎧 SUPPORT", callback_data="support")],
        [InlineKeyboardButton("👤 MY PROFILE", callback_data="my_profile")]
    ]
    if is_admin(user_id):
        kb.append([InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")])

    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "check_join":
        if await check_force_join(user_id, context):
            await start(update, context)
        else:
            await query.answer("⚠️ আপনি সব চ্যানেলে জয়েন করেননি!", show_alert=True)

    elif query.data == "get_number":
        text = "📱 **Select a service for WhatsApp Traffic:**"
        kb = [
            [InlineKeyboardButton("🟢 WhatsApp", callback_data="service_whatsapp")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif query.data == "service_whatsapp":
        text = "🌍 **Select a country for WhatsApp:**"
        kb = [
            [InlineKeyboardButton("Ivory Coast 0.5TK", callback_data="buy_num_ivory"), InlineKeyboardButton("Madagascar 0.5TK", callback_data="buy_num_madagascar")],
            [InlineKeyboardButton("Malaysia 0.5TK", callback_data="buy_num_malaysia"), InlineKeyboardButton("Togo 0.5TK", callback_data="buy_num_togo")],
            [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif query.data.startswith("buy_num_"):
        await query.message.edit_text("⏳ **PROCESSING:**\nFinding your number...", parse_mode='Markdown')
        await asyncio.sleep(2)
        
        phone_nums = ["+2250172429969", "+2250172871835", "+2250172555782"]
        selected_num = random.choice(phone_nums)
        
        text = (
            f"Active 15min • Awaiting OTP signature\n\n"
            f"**WhatsApp**\n\n"
            f"`{selected_num}`\n\n"
            f"chawal aur sabji ban gaye hain sab yah rakom"
        )
        kb = [
            [InlineKeyboardButton("🔄 Change Number", callback_data="get_number"), InlineKeyboardButton("👥 OTP Group", url="https://t.me/")],
            [InlineKeyboardButton("❌ Close", callback_data="main_menu")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif query.data == "ifa_online":
        await query.message.edit_text("⚡ 2FA Online Service is active and working seamlessly.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]))

    elif query.data == "refer":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        text = (
            f"👥 **REFER & EARN 💵**\n\n"
            f"YOUR LINK:\n`{ref_link}`\n\n"
            f"TOTAL REFERS: {users.get(str(user_id), {}).get('referrals', 0)}\n"
            f"PER REFER: 0.2 TK"
        )
        kb = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif query.data == "withdraw":
        u_bal = users.get(str(user_id), {}).get('balance', 0.0)
        text = (
            f"💸 **WITHDRAWAL**\n\n"
            f"Total Otp: {users.get(str(user_id), {}).get('total_otp', 0)}\n"
            f"Total Referrer: {users.get(str(user_id), {}).get('referrals', 0)}\n"
            f"BALANCE: {u_bal:.1f} TK\n"
            f"MINIMUM: {config['min_withdraw']} TK\n\n"
            f"SELECT METHOD:"
        )
        kb = [
            [InlineKeyboardButton("bKash", callback_data="wd_bkash"), InlineKeyboardButton("Nagad", callback_data="wd_nagad")],
            [InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif query.data in ["wd_bkash", "wd_nagad"]:
        context.user_data['wd_method'] = "bKash" if "bkash" in query.data else "Nagad"
        await query.message.edit_text("📱 **আপনার পেমেন্ট নম্বরটি (বিকাশ/নগদ) পাঠান:**", parse_mode='Markdown')
        return WITHDRAW_AMT

    elif query.data == "support":
        text = "🎧 **Contact us for any help:**"
        kb = [
            [InlineKeyboardButton("Contact Support", url="https://t.me/")],
            [InlineKeyboardButton("Close", callback_data="main_menu")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif query.data == "my_profile":
        u_info = users.get(str(user_id), {'balance': 0.0, 'total_otp': 0, 'referrals': 0})
        text = (
            f"👤 **YOUR PROFILE**\n\n"
            f"🆔 User ID: `{user_id}`\n\n"
            f"💰 Balance: {u_info['balance']:.1f} TK\n"
            f"🔥 Total OTPs: {u_info['total_otp']}\n"
            f"👥 Referrals: {u_info['referrals']}\n\n"
            f"📦 Subscription: Free access\n"
            f"Status: ✅ Active"
        )
        kb = [
            [InlineKeyboardButton("🔗 My Referral Link", callback_data="refer")],
            [InlineKeyboardButton("❌ Close", callback_data="main_menu")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif query.data == "admin_panel" and is_admin(user_id):
        text = "🛠️ **ADMIN PANEL**\n\nবটের সবকিছু নিয়ন্ত্রণ ও লাইভ এক্সেস ম্যানেজ করুন:"
        kb = [
            [InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast")],
            [InlineKeyboardButton("⚙️ Set Minimum Withdraw", callback_data="admin_set_min")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif query.data == "admin_broadcast" and is_admin(user_id):
        await query.message.edit_text("📢 ব্রডকাস্ট করার জন্য মেসেজটি পাঠান:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))

    elif query.data == "main_menu":
        await start(update, context)

async def withdraw_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    amt_text = update.message.text
    try:
        amt = float(amt_text)
        if amt < config['min_withdraw']:
            await update.message.reply_text(f"⚠️ সর্বনিম্ন উইথড্র পরিমাণ {config['min_withdraw']} TK!")
            return ConversationHandler.END
        
        if users[str(user_id)]['balance'] < amt:
            await update.message.reply_text("⚠️ আপনার পর্যাপ্ত ব্যালেন্স নেই!")
            return ConversationHandler.END

        users[str(user_id)]['balance'] -= amt
        save_data()
        await update.message.reply_text("✅ আপনার উইথড্র রিকোয়েস্ট সফলভাবে জমা হয়েছে!")
        await start(update, context)
    except:
        await update.message.reply_text("⚠️ সঠিক পরিমাণ লিখুন!")
    return ConversationHandler.END

# --- MAIN EXECUTION ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).request(HTTPXRequest(connection_pool_size=8, read_timeout=20.0)).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^wd_(bkash|nagad)$")],
        states={
            WITHDRAW_AMT: [MessageHandler(filters=~filters.COMMAND, callback=withdraw_amount_received)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^main_menu$")]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
