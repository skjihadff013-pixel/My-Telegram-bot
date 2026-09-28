import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, ContextTypes, filters

# Token & Logging
TOKEN = "8844457403:AAHy50iZPsadK-DRMicSSNBVSzgFMZckWxo"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# State constants
(MAIN_MENU, ADD_SEND_EMAIL, ADD_SEND_OTP, ADD_OTP_INPUT, CHECK_TOKEN,
 CHANGE_SEND_TOKEN, CHANGE_SEND_OLD_EMAIL, CHANGE_SEND_NEW_EMAIL,
 CHANGE_VERIFY_METHOD, CHANGE_OLD_OTP, CHANGE_OLD_PWD, CHANGE_NEW_OTP,
 UNBIND_SEND_TOKEN, UNBIND_SEND_EMAIL, UNBIND_METHOD, UNBIND_OTP, UNBIND_PWD,
 CANCEL_TOKEN, REVOKE_TOKEN, CHECK_PLATFORM, WAITING_INPUT) = range(21)

# Headers
HEADERS = {
    "User-Agent": "GarenaMSDK/4.0.41(TECNO KJ5 ;Android 13;en;HK;app 1.123.1 2019120270;)",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip"
}

def convert_seconds(s):
    d, h = divmod(s, 86400)
    h, m = divmod(h, 3600)
    m, s = divmod(m, 60)
    return f"{int(d)}d {int(h)}h {int(m)}m {int(s)}s"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - show main menu"""
    keyboard = [
        [InlineKeyboardButton("➕ Add Recovery Email", callback_data="add"),
         InlineKeyboardButton("🔍 Check Email", callback_data="check")],
        [InlineKeyboardButton("🔗 Check Platforms", callback_data="platforms"),
         InlineKeyboardButton("❌ Cancel Recovery", callback_data="cancel")],
        [InlineKeyboardButton("📝 Unbind Email", callback_data="unbind"),
         InlineKeyboardButton("🔄 Change Email", callback_data="change")],
        [InlineKeyboardButton("🔓 Revoke Token", callback_data="revoke")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎮 **Garena Account Tool**\nSelect an operation:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return MAIN_MENU

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "add":
        await query.edit_message_text("📧 Enter your email:")
        return ADD_SEND_EMAIL
    elif query.data == "check":
        await query.edit_message_text("🔐 Enter access token:")
        return CHECK_TOKEN
    elif query.data == "platforms":
        await query.edit_message_text("🔐 Enter access token:")
        return CHECK_PLATFORM
    elif query.data == "cancel":
        await query.edit_message_text("🔐 Enter access token:")
        return CANCEL_TOKEN
    elif query.data == "unbind":
        await query.edit_message_text("🔐 Enter access token:")
        return UNBIND_SEND_TOKEN
    elif query.data == "change":
        await query.edit_message_text("🔐 Enter access token:")
        return CHANGE_SEND_TOKEN
    elif query.data == "revoke":
        await query.edit_message_text("🔐 Enter access token:")
        return REVOKE_TOKEN

# ============== ADD RECOVERY EMAIL ==============
async def add_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get email for adding recovery email"""
    context.user_data['email'] = update.message.text.strip()
    await update.message.reply_text("📨 Sending OTP...")
    
    url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
    payload = {
        'email': context.user_data['email'],
        'locale': 'en_MA',
        'region': 'IND',
        'app_id': '100067',
        'access_token': context.user_data.get('temp_token', '')
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        if r.json().get("result") == 0:
            await update.message.reply_text("✅ OTP sent! Enter OTP:")
            return ADD_SEND_OTP
        else:
            await update.message.reply_text(f"❌ Failed to send OTP: {r.text}")
            return await start(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return await start(update, context)

async def add_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify OTP for adding recovery email"""
    otp = update.message.text.strip()
    await update.message.reply_text("⏳ Verifying OTP...")
    
    url = "https://100067.connect.garena.com/game/account_security/bind:verify_otp"
    payload = {
        'email': context.user_data['email'],
        'app_id': '100067',
        'access_token': context.user_data.get('temp_token', ''),
        'otp': otp
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        res = r.json()
        if r.status_code == 200:
            auth = res.get("verifier_token")
            if auth:
                context.user_data['verifier_token'] = auth
                await finalize_add_email(update, context)
                return await start(update, context)
            else:
                await update.message.reply_text("❌ No verifier token received")
                return await start(update, context)
        else:
            await update.message.reply_text(f"❌ OTP verification failed")
            return await start(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return await start(update, context)

async def finalize_add_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize email addition"""
    url = "https://100067.connect.garena.com/game/account_security/bind:create_bind_request"
    payload = {
        'app_id': '100067',
        'access_token': context.user_data.get('temp_token', ''),
        'verifier_token': context.user_data.get('verifier_token', ''),
        'secondary_password': "91B4D142823F7D20C5F08DF69122DE43F35F057A988D9619F6D3138485C9A203",
        'email': context.user_data['email']
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        if r.status_code == 200:
            await update.message.reply_text(f"✅ SUCCESS! Email {context.user_data['email']} added")
        else:
            await update.message.reply_text(f"❌ Failed: {r.text}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ============== CHECK RECOVERY EMAIL ==============
async def check_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check recovery email status"""
    access = update.message.text.strip()
    
    url = "https://100067.connect.garena.com/game/account_security/bind:get_bind_info"
    payload = {'app_id': "100067", 'access_token': access}
    
    try:
        r = requests.get(url, params=payload, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            data = r.json()
            email = data.get("email", "")
            email_to_be = data.get("email_to_be", "")
            countdown = data.get("request_exec_countdown", 0)
            
            if email == "" and email_to_be != "":
                msg = f"📧 Email: `{email_to_be}`\n⏳ Confirmed in: {convert_seconds(countdown)}"
            elif email != "" and email_to_be == "":
                msg = f"📧 Email: `{email}`\n✅ Confirmed: Yes"
            elif email == "" and email_to_be == "":
                msg = "⚠️ No recovery email set"
            else:
                msg = f"📧 Current: `{email}`\n📧 New: `{email_to_be}`\n⏳ In: {convert_seconds(countdown)}"
            
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ Error: {r.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    return await start(update, context)

# ============== CHECK PLATFORMS ==============
async def check_platform_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check linked platforms"""
    access = update.message.text.strip()
    
    url = "https://100067.connect.garena.com/bind/app/platform/info/get"
    headers = {
        "User-Agent": "GarenaMSDK/4.0.41(TECNO KJ5 ;Android 13;en;HK;app 1.123.1 2019120270;)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip"
    }
    
    try:
        r = requests.get(url, params={'access_token': access}, headers=headers, timeout=30)
        if r.status_code in [200, 201]:
            j = r.json()
            m = {3: "Facebook", 8: "Gmail", 10: "iCloud", 5: "VK", 11: "Twitter", 7: "Huawei"}
            b = j.get("bounded_accounts", [])
            a = j.get("available_platforms", [])
            
            msg = "🔗 **Linked Accounts:**\n"
            found = False
            for x in b:
                try:
                    p = x.get('platform')
                    uinfo = x.get('user_info', {})
                    e = uinfo.get('email', '')
                    n = uinfo.get('nickname', '')
                    if p in m:
                        msg += f"\n🔹 {m[p]}\n"
                        if e: msg += f"  📧 {e}\n"
                        if n: msg += f"  👤 {n}\n"
                        found = True
                except:
                    continue
            
            if not found:
                msg += "No linked accounts found"
            
            msg += "\n\n🎯 **Available to Link:**\n"
            for k in m:
                if k not in a:
                    msg += f"  • {m[k]}\n"
            
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ Failed to fetch platforms")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    return await start(update, context)

# ============== CANCEL RECOVERY ==============
async def cancel_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel pending recovery request"""
    access = update.message.text.strip()
    
    url = "https://100067.connect.garena.com/game/account_security/bind:cancel_request"
    payload = {'app_id': "100067", 'access_token': access}
    
    try:
        r = requests.post(url, data=payload, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            result = r.json().get("result", -1)
            if result == 0:
                await update.message.reply_text("✅ Recovery request cancelled")
            else:
                await update.message.reply_text(f"❌ Failed: {r.json()}")
        else:
            await update.message.reply_text(f"❌ No response")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    return await start(update, context)

# ============== REVOKE TOKEN ==============
async def revoke_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Revoke access token"""
    access = update.message.text.strip()
    
    url = f"https://100067.connect.garena.com/oauth/logout?access_token={access}"
    
    try:
        r = requests.get(url, timeout=30)
        if r.text.strip() == '{"result":0}':
            await update.message.reply_text("✅ Token revoked successfully 🎉")
        else:
            await update.message.reply_text(f"❌ Failed: {r.text}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    return await start(update, context)

# ============== UNBIND EMAIL ==============
async def unbind_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start unbind email process"""
    context.user_data['access_token'] = update.message.text.strip()
    await update.message.reply_text("📧 Enter email to unbind:")
    return UNBIND_SEND_EMAIL

async def unbind_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get email for unbind"""
    context.user_data['email'] = update.message.text.strip()
    
    keyboard = [
        [InlineKeyboardButton("📨 OTP Verification", callback_data="unbind_otp"),
         InlineKeyboardButton("🔐 Password Verification", callback_data="unbind_pwd")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose verification method:", reply_markup=reply_markup)
    return UNBIND_METHOD

async def unbind_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unbind method selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "unbind_otp":
        context.user_data['unbind_method'] = 'otp'
        await query.edit_message_text("📨 Sending OTP...")
        
        url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
        payload = {
            'email': context.user_data['email'],
            'locale': 'en_MA',
            'region': 'IND',
            'app_id': '100067',
            'access_token': context.user_data['access_token']
        }
        
        try:
            r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
            if r.json().get("result") == 0:
                await query.edit_message_text("✅ OTP sent! Enter OTP:")
                return UNBIND_OTP
        except:
            await query.edit_message_text("❌ Failed to send OTP")
    
    elif query.data == "unbind_pwd":
        context.user_data['unbind_method'] = 'password'
        await query.edit_message_text("🔐 Enter secondary password:")
        return UNBIND_PWD

async def unbind_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify OTP for unbind"""
    otp = update.message.text.strip()
    
    url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
    payload = {
        'email': context.user_data['email'],
        'otp': otp,
        'app_id': '100067',
        'access_token': context.user_data['access_token']
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        result = r.json()
        if result.get("result") == 0:
            identity_token = result.get("identity_token")
            if identity_token:
                context.user_data['identity_token'] = identity_token
                await finalize_unbind(update, context)
                return await start(update, context)
    except:
        pass
    
    await update.message.reply_text("❌ Verification failed")
    return await start(update, context)

async def unbind_pwd_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify password for unbind"""
    pwd = update.message.text.strip()
    
    url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
    payload = {
        'email': context.user_data['email'],
        'secondary_password': pwd,
        'app_id': '100067',
        'access_token': context.user_data['access_token']
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        result = r.json()
        if result.get("result") == 0:
            identity_token = result.get("identity_token")
            if identity_token:
                context.user_data['identity_token'] = identity_token
                await finalize_unbind(update, context)
                return await start(update, context)
    except:
        pass
    
    await update.message.reply_text("❌ Verification failed")
    return await start(update, context)

async def finalize_unbind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize unbind request"""
    url = "https://100067.connect.garena.com/game/account_security/bind:create_unbind_request"
    payload = {
        'app_id': '100067',
        'access_token': context.user_data['access_token'],
        'identity_token': context.user_data.get('identity_token', '')
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        if r.json().get("result") == 0:
            await update.message.reply_text("✅ Unbind request created successfully!")
        else:
            await update.message.reply_text(f"❌ Failed: {r.json()}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ============== CHANGE EMAIL ==============
async def change_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start change email process"""
    context.user_data['access_token'] = update.message.text.strip()
    await update.message.reply_text("📧 Enter old email:")
    return CHANGE_SEND_OLD_EMAIL

async def change_old_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get old email"""
    context.user_data['old_email'] = update.message.text.strip()
    
    keyboard = [
        [InlineKeyboardButton("📨 OTP Verification", callback_data="change_otp"),
         InlineKeyboardButton("🔐 Password Verification", callback_data="change_pwd")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose verification method:", reply_markup=reply_markup)
    return CHANGE_VERIFY_METHOD

async def change_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle change email verification method"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "change_otp":
        context.user_data['change_method'] = 'otp'
        await query.edit_message_text("📨 Sending OTP to old email...")
        
        url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
        payload = {
            'email': context.user_data['old_email'],
            'locale': 'en_MA',
            'region': 'IND',
            'app_id': '100067',
            'access_token': context.user_data['access_token']
        }
        
        try:
            r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
            if r.json().get("result") == 0:
                await query.edit_message_text("✅ OTP sent! Enter OTP:")
                return CHANGE_OLD_OTP
        except:
            pass
        
        await query.edit_message_text("❌ Failed to send OTP")
    
    elif query.data == "change_pwd":
        context.user_data['change_method'] = 'password'
        await query.edit_message_text("🔐 Enter secondary password:")
        return CHANGE_OLD_PWD

async def change_old_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify old email OTP"""
    otp = update.message.text.strip()
    
    url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
    payload = {
        'email': context.user_data['old_email'],
        'otp': otp,
        'app_id': '100067',
        'access_token': context.user_data['access_token']
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        result = r.json()
        if result.get("result") == 0:
            token = result.get("identity_token")
            if token:
                context.user_data['identity_token'] = token
                await update.message.reply_text("✅ Old email verified!\n📧 Enter new email:")
                return CHANGE_SEND_NEW_EMAIL
    except:
        pass
    
    await update.message.reply_text("❌ Verification failed")
    return await start(update, context)

async def change_old_pwd_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify old email password"""
    pwd = update.message.text.strip()
    
    url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
    payload = {
        'email': context.user_data['old_email'],
        'secondary_password': pwd,
        'app_id': '100067',
        'access_token': context.user_data['access_token']
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        result = r.json()
        if result.get("result") == 0:
            token = result.get("identity_token")
            if token:
                context.user_data['identity_token'] = token
                await update.message.reply_text("✅ Password verified!\n📧 Enter new email:")
                return CHANGE_SEND_NEW_EMAIL
    except:
        pass
    
    await update.message.reply_text("❌ Verification failed")
    return await start(update, context)

async def change_new_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get new email and send OTP"""
    context.user_data['new_email'] = update.message.text.strip()
    await update.message.reply_text("📨 Sending OTP to new email...")
    
    url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
    payload = {
        'email': context.user_data['new_email'],
        'locale': 'en_MA',
        'region': 'IND',
        'app_id': '100067',
        'access_token': context.user_data['access_token']
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        if r.json().get("result") == 0:
            await update.message.reply_text("✅ OTP sent! Enter OTP for new email:")
            return CHANGE_NEW_OTP
    except:
        pass
    
    await update.message.reply_text("❌ Failed to send OTP")
    return await start(update, context)

async def change_new_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify new email OTP and finalize"""
    otp = update.message.text.strip()
    
    url = "https://100067.connect.garena.com/game/account_security/bind:verify_otp"
    payload = {
        'email': context.user_data['new_email'],
        'app_id': '100067',
        'access_token': context.user_data['access_token'],
        'otp': otp
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        if r.status_code == 200:
            verifier = r.json().get("verifier_token")
            if verifier:
                context.user_data['verifier_token'] = verifier
                await finalize_change_email(update, context)
                return await start(update, context)
    except:
        pass
    
    await update.message.reply_text("❌ OTP verification failed")
    return await start(update, context)

async def finalize_change_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize email change"""
    url = "https://100067.connect.garena.com/game/account_security/bind:create_rebind_request"
    payload = {
        'identity_token': context.user_data.get('identity_token', ''),
        'email': context.user_data['new_email'],
        'app_id': '100067',
        'verifier_token': context.user_data.get('verifier_token', ''),
        'access_token': context.user_data['access_token']
    }
    
    try:
        r = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        if r.json().get("result") == 0:
            await update.message.reply_text(f"✅ Email change request created!\nOld: {context.user_data['old_email']}\nNew: {context.user_data['new_email']}")
        else:
            await update.message.reply_text(f"❌ Failed: {r.json()}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel operation"""
    await update.message.reply_text("❌ Operation cancelled")
    return ConversationHandler.END

def main():
    """Start the bot"""
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(menu_callback)],
            
            # Add email flow
            ADD_SEND_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_email_input)],
            ADD_SEND_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_otp_input)],
            
            # Check email
            CHECK_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_token_input)],
            
            # Check platforms
            CHECK_PLATFORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_platform_input)],
            
            # Cancel recovery
            CANCEL_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_token_input)],
            
            # Revoke token
            REVOKE_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, revoke_token_input)],
            
            # Unbind email flow
            UNBIND_SEND_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, unbind_token_input)],
            UNBIND_SEND_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, unbind_email_input)],
            UNBIND_METHOD: [CallbackQueryHandler(unbind_method_callback)],
            UNBIND_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, unbind_otp_input)],
            UNBIND_PWD: [MessageHandler(filters.TEXT & ~filters.COMMAND, unbind_pwd_input)],
            
            # Change email flow
            CHANGE_SEND_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_token_input)],
            CHANGE_SEND_OLD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_old_email_input)],
            CHANGE_VERIFY_METHOD: [CallbackQueryHandler(change_verify_callback)],
            CHANGE_OLD_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_old_otp_input)],
            CHANGE_OLD_PWD: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_old_pwd_input)],
            CHANGE_SEND_NEW_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_new_email_input)],
            CHANGE_NEW_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_new_otp_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
