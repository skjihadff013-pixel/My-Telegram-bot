# -*- coding: utf-8 -*-
"""
𝐒𝐦𝐚𝐫𝐭 𝐂𝐨ᴅᴇ 𝐖ᴏʀʟᴅ </> — Paid Hosting Bot
Single-file Telegram + SQLite + cPanel UAPI hosting system.

Install:
    pip install pyTelegramBotAPI requests

Configure environment variables or edit constants:
    BOT_TOKEN
    ADMIN_IDS=123456789,987654321
    CPANEL_HOST=https://cpanel.example.com:2083
    CPANEL_USERNAME=cpanel_user
    CPANEL_API_TOKEN=your_token
    PUBLIC_HOST_PREFIX=https://cdworld.top/file
    CPANEL_BASE_PATH=public_html/file

A user buys a plan with Coin, uploads a ZIP/HTML file, and the bot
creates /file/<unique-slug>/ through cPanel Fileman UAPI.

Security:
- ZIP path traversal checks
- file type restrictions
- upload size limits
- admin authorization
- SQLite transactions
- hosting expiry worker
- no secrets stored in SQLite
"""

import os
import re
import time
import uuid
import sqlite3
import secrets
import zipfile
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
import telebot
from telebot import types

# ========================= CONFIG =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8654281006:AAGaAvfpqy1Ghd1gnr4K2sV2sFbRFwKoubI")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "7125334953").split(",") if x.strip().isdigit()}
DB_FILE = os.getenv("DB_FILE", "smart_code_world_hosting.db")

CPANEL_HOST = os.getenv("CPANEL_HOST", "https://cdworld.top:2083").rstrip("/")
CPANEL_USERNAME = os.getenv("CPANEL_USERNAME", "cworldto")
CPANEL_API_TOKEN = os.getenv("CPANEL_API_TOKEN", "DTOG8Z69E43J6OIQ8C43QI56YOSH0NH2")

PUBLIC_HOST_PREFIX = os.getenv("PUBLIC_HOST_PREFIX", "https://cdworld.top/file").rstrip("/")
CPANEL_BASE_PATH = os.getenv("CPANEL_BASE_PATH", "public_html/file").strip("/")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
MAX_ARCHIVE_MB = int(os.getenv("MAX_ARCHIVE_MB", "250"))
MAX_ARCHIVE_FILES = int(os.getenv("MAX_ARCHIVE_FILES", "1000"))

BRAND = "𝐒𝐦𝐚𝐫𝐭 𝐂ᴏᴅᴇ 𝐖ᴏʀʟᴅ &lt;/&gt;"
LOG_FILE = "smart_code_world_hosting.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("hosting")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
states = {}
LOCK = threading.RLock()


# ========================= COMMON =========================
def now():
    return datetime.now(timezone.utc)

def stamp(dt=None):
    return (dt or now()).strftime("%Y-%m-%d %H:%M:%S UTC")

def esc(s):
    return telebot.util.escape(str(s or ""))

def money(v):
    return f"{float(v):.2f} Coin"

def is_admin(uid):
    return int(uid) in ADMIN_IDS

def header(title, icon="✨"):
    return f"╭━━━━━━━━━━━━━━━━━━━━╮\n┃ {icon} <b>{title}</b>\n╰━━━━━━━━━━━━━━━━━━━━╯"

def footer():
    return f"\n\n━━━━━━━━━━━━━━━━━━━━━\n<b>{BRAND}</b>"

def human_size(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{int(n)} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def kb_btn(text, style="primary"):
    try:
        return types.KeyboardButton(text, style=style)
    except (TypeError, ValueError):
        return types.KeyboardButton(text)

def in_btn(text, **kwargs):
    try:
        return types.InlineKeyboardButton(text, **kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return types.InlineKeyboardButton(text, **kwargs)

def main_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(kb_btn("🌐 হোস্টিং নিন", "success"), kb_btn("💎 আমার হোস্টিং", "primary"))
    kb.add(kb_btn("💰 আমার ব্যালেন্স", "primary"), kb_btn("👥 রেফার", "success"))
    kb.add(kb_btn("💳 ডিপোজিট", "success"), kb_btn("📦 হোস্টিং প্ল্যান", "primary"))
    kb.add(kb_btn("📊 পরিসংখ্যান", "primary"), kb_btn("💬 সাপোর্ট", "primary"))
    kb.add(kb_btn("👤 আমার প্রোফাইল", "primary"))
    if is_admin(uid):
        kb.add(kb_btn("⚙️ অ্যাডমিন প্যানেল", "danger"))
    return kb

def back_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(kb_btn("🔙 পিছনে", "primary"), kb_btn("🏠 হোম", "success"))
    return kb

def cancel_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(kb_btn("❌ বাতিল", "danger"))
    return kb


# ========================= DATABASE =========================
def db():
    c = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with LOCK, db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            balance REAL NOT NULL DEFAULT 0,
            referred_by INTEGER,
            referral_count INTEGER NOT NULL DEFAULT 0,
            referral_earned REAL NOT NULL DEFAULT 0,
            is_banned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS referrals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            reward REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            kind TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deposits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_taka REAL NOT NULL,
            coin_amount REAL NOT NULL,
            trx_id TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            reviewed_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS plans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            storage_mb INTEGER NOT NULL,
            duration_days INTEGER NOT NULL,
            max_websites INTEGER NOT NULL DEFAULT 1,
            php_allowed INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hostings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            project_name TEXT NOT NULL,
            url TEXT NOT NULL,
            cpanel_path TEXT NOT NULL,
            storage_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target TEXT DEFAULT '',
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """)
        defaults = {
            "referral_reward": "100",
            "min_deposit": "50",
            "coin_per_taka": "10",
            "maintenance": "0",
            "support": "@SmartCodeWorld",
            "payment_methods": "bKash: 01XXXXXXXXX\nNagad: 01XXXXXXXXX",
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        if c.execute("SELECT COUNT(*) n FROM plans").fetchone()["n"] == 0:
            c.executemany(
                """INSERT INTO plans(name,price,storage_mb,duration_days,max_websites,php_allowed,status,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                [
                    ("𝐁ᴀsɪᴄ Hᴏsᴛ", 500, 100, 30, 1, 0, "active", stamp()),
                    ("𝐏ʀᴏ Hᴏsᴛ", 1200, 500, 90, 3, 0, "active", stamp()),
                    ("𝐏ʀᴇᴍɪᴜᴍ Hᴏsᴛ", 2500, 2048, 180, 10, 1, "active", stamp()),
                ],
            )

def get_setting(k, default=""):
    with LOCK, db() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        return r["value"] if r else default

def set_setting(k, v):
    with LOCK, db() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, str(v)),
        )

def user(uid):
    with LOCK, db() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def register(tg, ref=None):
    uid = tg.id
    with LOCK, db() as c:
        if c.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
            c.execute(
                "UPDATE users SET first_name=?,username=?,last_seen=? WHERE user_id=?",
                (tg.first_name or "", tg.username or "", stamp(), uid),
            )
            return False
        valid_ref = None
        if ref and ref != uid and c.execute("SELECT 1 FROM users WHERE user_id=?", (ref,)).fetchone():
            valid_ref = ref
        c.execute(
            """INSERT INTO users(user_id,first_name,username,referred_by,created_at,last_seen)
               VALUES(?,?,?,?,?,?)""",
            (uid, tg.first_name or "", tg.username or "", valid_ref, stamp(), stamp()),
        )
        if valid_ref:
            reward = float(get_setting("referral_reward", "100"))
            c.execute(
                "INSERT OR IGNORE INTO referrals(referrer_id,referred_id,reward,created_at) VALUES(?,?,?,?)",
                (valid_ref, uid, reward, stamp()),
            )
            c.execute(
                "UPDATE users SET balance=balance+?,referral_count=referral_count+1,referral_earned=referral_earned+? WHERE user_id=?",
                (reward, reward, valid_ref),
            )
            c.execute(
                "INSERT INTO transactions(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",
                (valid_ref, reward, "referral", f"Referral {uid}", stamp()),
            )
        return True

def add_balance(uid, amount, kind, note=""):
    with LOCK, db() as c:
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))
        c.execute(
            "INSERT INTO transactions(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",
            (uid, amount, kind, note, stamp()),
        )

def take_balance(uid, amount, note=""):
    with LOCK, db() as c:
        r = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not r or r["balance"] < amount:
            return False
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid))
        c.execute(
            "INSERT INTO transactions(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",
            (uid, -amount, "hosting_purchase", note, stamp()),
        )
        return True


# ========================= CPANEL =========================
class CPanelError(Exception):
    pass

class CPanel:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"cpanel {CPANEL_USERNAME}:{CPANEL_API_TOKEN}"

    def call(self, module, function, data=None, files=None, timeout=120):
        url = f"{CPANEL_HOST}/execute/{module}/{function}"
        try:
            r = self.session.post(url, data=data or {}, files=files, timeout=timeout, verify=True)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            raise CPanelError(str(e))
        result = payload.get("result", {})
        if not isinstance(result, dict):
            raise CPanelError(f"Invalid cPanel UAPI response: {str(payload)[:1200]}")
        if result.get("status") != 1:
            errors = result.get("errors") or []
            if isinstance(errors, str):
                errors = [errors]
            messages = result.get("messages") or []
            if isinstance(messages, str):
                messages = [messages]
            details = [str(x) for x in errors + messages if x]
            if not details:
                details = [f"HTTP {r.status_code}: {str(payload)[:1200]}"]
            raise CPanelError("; ".join(details))
        return result.get("data")

    def api2(self, module, function, data=None, timeout=120):
        """Call legacy cPanel API 2 through the cPanel 2083 endpoint.

        cPanel documents no UAPI equivalent for Fileman::mkdir/fileop, so
        these filesystem operations use API 2 while uploads use UAPI.
        """
        url = f"{CPANEL_HOST}/json-api/cpanel"
        payload = {
            "cpanel_jsonapi_user": CPANEL_USERNAME,
            "cpanel_jsonapi_apiversion": "2",
            "cpanel_jsonapi_module": module,
            "cpanel_jsonapi_func": function,
        }
        payload.update(data or {})
        try:
            r = self.session.post(url, data=payload, timeout=timeout, verify=True)
            r.raise_for_status()
            body = r.json()
        except Exception as e:
            raise CPanelError(f"API2 request failed: {e}")

        result = body.get("cpanelresult", {})
        if result.get("event", {}).get("result") != 1:
            reasons = []
            for item in result.get("data", []) if isinstance(result.get("data"), list) else []:
                if isinstance(item, dict):
                    reasons.extend(str(item.get(k)) for k in ("reason", "err") if item.get(k))
            reason = result.get("reason") or "; ".join(reasons) or "Unknown cPanel API 2 error"
            raise CPanelError(str(reason))
        return result.get("data")

    def mkdir(self, path):
        parent, name = os.path.split(path.rstrip("/"))
        return self.api2("Fileman", "mkdir", {
            "path": parent, "name": name, "permissions": "0755"
        })

    def upload(self, local, remote_dir):
        """Upload one file with UAPI and explicitly validate the upload result.

        cPanel may return HTTP 200 even when the operation failed, and a
        successful response contains result.status=1 plus data.uploads.
        Treat a successful upload as success instead of interpreting the
        returned data dictionary as an error.
        """
        with open(local, "rb") as f:
            data = self.call(
                "Fileman", "upload_files",
                {"dir": remote_dir, "overwrite": "1"},
                {"file-1": (os.path.basename(local), f)},
                180,
            )

        if not isinstance(data, dict):
            raise CPanelError(f"Unexpected upload response: {str(data)[:1200]}")

        uploads = data.get("uploads")
        if isinstance(uploads, dict):
            uploads = [uploads]
        if not uploads:
            raise CPanelError(f"cPanel upload returned no upload record: {str(data)[:1200]}")

        failed = []
        for item in uploads:
            if not isinstance(item, dict) or item.get("status") != 1:
                failed.append(item)
        if failed:
            raise CPanelError(f"cPanel upload failed: {str(failed)[:1200]}")

        return data

    def extract(self, archive, destination):
        return self.api2("Fileman", "fileop", {
            "op": "extract",
            "sourcefiles": archive,
            "destfiles": destination,
            "doubledecode": "1",
        }, timeout=180)

    def delete(self, path):
        return self.api2("Fileman", "fileop", {
            "op": "trash",
            "sourcefiles": path,
            "doubledecode": "1",
        }, timeout=120)

CP = CPanel()


# ========================= FILE SECURITY =========================
ALLOWED = {
    ".html",".htm",".css",".js",".json",".txt",".xml",
    ".jpg",".jpeg",".png",".gif",".webp",".svg",".ico",
    ".mp3",".mp4",".webm",".pdf",".zip",".woff",".woff2",".ttf",".eot",".map"
}
BLOCKED_SERVER = {".php",".phtml",".phar",".cgi",".pl",".py",".sh",".exe",".dll"}

def download_file(file_id, filename):
    info = bot.get_file(file_id)
    data = bot.download_file(info.file_path)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"Maximum upload {MAX_UPLOAD_MB} MB")
    Path("tmp_uploads").mkdir(exist_ok=True)
    p = Path("tmp_uploads") / f"{uuid.uuid4().hex}_{Path(filename).name}"
    p.write_bytes(data)
    return p

def validate_zip(path, php_allowed=False):
    total = 0
    with zipfile.ZipFile(path, "r") as z:
        if len(z.infolist()) > MAX_ARCHIVE_FILES:
            raise ValueError("ZIP contains too many files.")
        for i in z.infolist():
            name = i.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("Unsafe ZIP path detected.")
            if i.is_dir():
                continue
            total += i.file_size
            ext = Path(name).suffix.lower()
            if ext in BLOCKED_SERVER and not (php_allowed and ext == ".php"):
                raise ValueError(f"Server-side file not allowed: {ext}")
        if total > MAX_ARCHIVE_MB * 1024 * 1024:
            raise ValueError(f"Archive expands beyond {MAX_ARCHIVE_MB} MB.")

def validate_file(name, php_allowed=False):
    ext = Path(name).suffix.lower()
    if ext in BLOCKED_SERVER:
        if not (php_allowed and ext == ".php"):
            raise ValueError("এই file type Plan-এ অনুমোদিত নয়।")
    elif ext not in ALLOWED:
        raise ValueError("এই file type অনুমোদিত নয়।")


# ========================= HELPERS =========================
def active_plans():
    with LOCK, db() as c:
        return c.execute("SELECT * FROM plans WHERE status='active' ORDER BY price").fetchall()

def plan(pid):
    with LOCK, db() as c:
        return c.execute("SELECT * FROM plans WHERE id=?", (pid,)).fetchone()

def hosting_count(uid):
    with LOCK, db() as c:
        return c.execute(
            "SELECT COUNT(*) n FROM hostings WHERE user_id=? AND status IN ('active','expired')", (uid,)
        ).fetchone()["n"]

def slugify(s):
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", s.strip().lower()).strip("-_")
    return s[:28] or "site"

def make_slug(uid, name):
    return f"{slugify(name)}-{str(uid)[-5:]}-{secrets.token_hex(2)}"

def create_hosting(uid, p, project, slug):
    started = now()
    expires = started + timedelta(days=p["duration_days"])
    path = f"{CPANEL_BASE_PATH}/{slug}"
    url = f"{PUBLIC_HOST_PREFIX}/{slug}/"
    with LOCK, db() as c:
        cur = c.execute(
            """INSERT INTO hostings
            (user_id,plan_id,slug,project_name,url,cpanel_path,started_at,expires_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (uid,p["id"],slug,project,url,path,stamp(started),stamp(expires),stamp()),
        )
        return cur.lastrowid, url, stamp(expires)

def notify_admins(text):
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text)
        except Exception:
            pass

def admin_log(uid, action, target="", details=""):
    with LOCK, db() as c:
        c.execute(
            "INSERT INTO admin_logs(admin_id,action,target,details,created_at) VALUES(?,?,?,?,?)",
            (uid,action,target,details[:1000],stamp()),
        )

def allowed_user(message):
    u = user(message.from_user.id)
    if u and u["is_banned"] and not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 আপনার অ্যাকাউন্ট বন্ধ করা হয়েছে।")
        return False
    if get_setting("maintenance","0") == "1" and not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "🛠️ বর্তমানে Bot maintenance mode-এ আছে।")
        return False
    return True


# ========================= START =========================
@bot.message_handler(commands=["start"])
def start(message):
    ref = None
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("ref_") and parts[1][4:].isdigit():
        ref = int(parts[1][4:])
    new = register(message.from_user, ref)
    if not allowed_user(message):
        return
    bot.send_message(
        message.chat.id,
        f"{header('𝐖ᴇʟᴄᴏᴍᴇ','🌐')}\n\n"
        f"👋 স্বাগতম <b>{esc(message.from_user.first_name)}</b>!\n\n"
        f"🚀 <b>{BRAND}</b>-এর Paid Hosting Platform-এ আপনাকে স্বাগতম।\n\n"
        f"💰 আপনার Coin: <b>{money(user(message.from_user.id)['balance'])}</b>\n"
        f"👥 প্রতি Referral: <b>{money(float(get_setting('referral_reward','100')))}</b>\n\n"
        "💳 Deposit অথবা Referral করে Coin সংগ্রহ করুন এবং Website Host করুন।"
        f"{footer()}",
        reply_markup=main_kb(message.from_user.id),
    )
    if new and ref and ref != message.from_user.id:
        try:
            bot.send_message(ref, f"🎉 নতুন Referral!\n💰 Reward: <b>{money(float(get_setting('referral_reward','100')))}</b>")
        except Exception:
            pass


# ========================= USER MENUS =========================
@bot.message_handler(func=lambda m: m.text == "🌐 হোস্টিং নিন")
def host_menu(message):
    if not allowed_user(message): return
    ps = active_plans()
    if not ps:
        bot.send_message(message.chat.id, "⚠️ কোনো Hosting Plan নেই।", reply_markup=back_kb()); return
    kb = types.InlineKeyboardMarkup()
    for p in ps:
        kb.add(in_btn(f"💎 {p['name']} • {p['price']:.0f} Coin", callback_data=f"choose:{p['id']}", style="success"))
    bot.send_message(message.chat.id, f"{header('𝐇ᴏsᴛɪɴɢ 𝐏ʟᴀɴ','📦')}\n\nএকটি Plan নির্বাচন করুন।{footer()}", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("choose:"))
def choose(call):
    if not allowed_user(call.message): return
    pid = int(call.data.split(":")[1]); p = plan(pid)
    if not p or p["status"] != "active":
        bot.answer_callback_query(call.id, "Plan unavailable", show_alert=True); return
    u = user(call.from_user.id)
    if u["balance"] < p["price"]:
        bot.answer_callback_query(call.id, "পর্যাপ্ত Coin নেই।", show_alert=True); return
    states[call.from_user.id] = {"type":"project","plan":pid}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"📝 <b>{esc(p['name'])}</b> নির্বাচিত।\n\nProject Name পাঠান।", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: m.text == "📦 হোস্টিং প্ল্যান")
def plans_menu(message):
    if not allowed_user(message): return
    ps = active_plans()
    text = [header("𝐇ᴏsᴛɪɴɢ 𝐏ʟᴀɴs","💎"),""]
    for p in ps:
        text.append(
            f"╭━━━ <b>{esc(p['name'])}</b> ━━━╮\n"
            f"💰 মূল্য: <b>{money(p['price'])}</b>\n"
            f"💾 Storage: <b>{p['storage_mb']} MB</b>\n"
            f"⏳ মেয়াদ: <b>{p['duration_days']} দিন</b>\n"
            f"🌐 Website: <b>{p['max_websites']}টি</b>\n"
            f"🐘 PHP: <b>{'হ্যাঁ' if p['php_allowed'] else 'না'}</b>\n"
            f"╰━━━━━━━━━━━━━━━━━━╯\n"
        )
    bot.send_message(message.chat.id, "\n".join(text)+footer(), reply_markup=back_kb())

@bot.message_handler(func=lambda m: m.text == "💎 আমার হোস্টিং")
def my_hosting(message):
    if not allowed_user(message): return
    with LOCK, db() as c:
        rows = c.execute(
            "SELECT h.*,p.name plan_name FROM hostings h JOIN plans p ON p.id=h.plan_id WHERE h.user_id=? ORDER BY h.id DESC",
            (message.from_user.id,),
        ).fetchall()
    if not rows:
        bot.send_message(message.chat.id, "📭 আপনার কোনো Hosting নেই।", reply_markup=back_kb()); return
    kb = types.InlineKeyboardMarkup(); parts = [header("𝐌ʏ 𝐇ᴏsᴛɪɴɢ","💎"),""]
    for h in rows:
        parts.append(
            f"{'🟢' if h['status']=='active' else '🔴'} <b>{esc(h['project_name'])}</b>\n"
            f"🌐 <code>{esc(h['url'])}</code>\n"
            f"💾 {human_size(h['storage_bytes'])}\n"
            f"⏳ {h['expires_at']}\n📌 {h['status']}\n"
        )
        if h["status"] in ("active","expired"):
            kb.row(
                in_btn("🌐 খুলুন", url=h["url"], style="primary"),
                in_btn("🔄 Renew", callback_data=f"renew:{h['id']}", style="success"),
                in_btn("🗑️ Delete", callback_data=f"delete:{h['id']}", style="danger"),
            )
    bot.send_message(message.chat.id, "\n".join(parts)+footer(), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("renew:"))
def renew(call):
    hid = int(call.data.split(":")[1]); uid = call.from_user.id
    with LOCK, db() as c:
        h = c.execute("SELECT h.*,p.* FROM hostings h JOIN plans p ON p.id=h.plan_id WHERE h.id=? AND h.user_id=?", (hid,uid)).fetchone()
    if not h: bot.answer_callback_query(call.id,"Hosting নেই",show_alert=True); return
    if not take_balance(uid,h["price"],f"Renew hosting #{hid}"):
        bot.answer_callback_query(call.id,"পর্যাপ্ত Coin নেই",show_alert=True); return
    try:
        base = max(datetime.strptime(h["expires_at"],"%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc), now())
    except Exception:
        base = now()
    exp = base + timedelta(days=h["duration_days"])
    with LOCK, db() as c:
        c.execute("UPDATE hostings SET status='active',expires_at=? WHERE id=?", (stamp(exp),hid))
    bot.answer_callback_query(call.id,"Renew সফল")
    bot.send_message(call.message.chat.id,f"✅ Hosting Renew হয়েছে।\n⏳ নতুন Expiry: <b>{stamp(exp)}</b>")

@bot.callback_query_handler(func=lambda c: c.data.startswith("delete:"))
def delete_prompt(call):
    hid = int(call.data.split(":")[1])
    kb = types.InlineKeyboardMarkup()
    kb.add(in_btn("✅ হ্যাঁ, মুছুন",callback_data=f"confirmdelete:{hid}",style="danger"),
           in_btn("❌ না",callback_data="no_delete",style="primary"))
    bot.send_message(call.message.chat.id,"⚠️ Website files-সহ Hosting মুছে যাবে। নিশ্চিত?",reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data=="no_delete")
def no_delete(call):
    bot.answer_callback_query(call.id,"বাতিল হয়েছে")

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirmdelete:"))
def delete_host(call):
    hid=int(call.data.split(":")[1]); uid=call.from_user.id
    with LOCK, db() as c:
        h=c.execute("SELECT * FROM hostings WHERE id=? AND user_id=?",(hid,uid)).fetchone()
    if not h: bot.answer_callback_query(call.id,"Hosting নেই",show_alert=True); return
    try: CP.delete(h["cpanel_path"])
    except Exception as e: log.warning("cPanel delete: %s",e)
    with LOCK, db() as c: c.execute("UPDATE hostings SET status='deleted' WHERE id=?",(hid,))
    bot.answer_callback_query(call.id,"Deleted")
    bot.send_message(call.message.chat.id,"🗑️ Hosting সফলভাবে মুছে ফেলা হয়েছে।")

@bot.message_handler(func=lambda m: m.text == "💰 আমার ব্যালেন্স")
def balance(message):
    if not allowed_user(message): return
    u=user(message.from_user.id)
    bot.send_message(message.chat.id,
        f"{header('𝐌ʏ 𝐁ᴀʟᴀɴᴄᴇ','💰')}\n\n"
        f"💎 Balance: <b>{money(u['balance'])}</b>\n"
        f"👥 Referral Earned: <b>{money(u['referral_earned'])}</b>"
        f"{footer()}", reply_markup=back_kb())

@bot.message_handler(func=lambda m: m.text == "👥 রেফার")
def referral(message):
    if not allowed_user(message): return
    uid=message.from_user.id; me=bot.get_me()
    link=f"https://t.me/{me.username}?start=ref_{uid}"
    u=user(uid)
    bot.send_message(message.chat.id,
        f"{header('𝐑ᴇғᴇʀʀᴀʟ','👥')}\n\n"
        f"💰 প্রতি Referral: <b>{money(float(get_setting('referral_reward','100')))}</b>\n"
        f"👤 Total Referral: <b>{u['referral_count']}</b>\n"
        f"💎 Earned: <b>{money(u['referral_earned'])}</b>\n\n"
        f"🔗 <code>{link}</code>{footer()}",
        reply_markup=types.InlineKeyboardMarkup().add(in_btn("🔗 বন্ধুদের সাথে শেয়ার করুন",url=f"https://t.me/share/url?url={link}",style="primary")))

@bot.message_handler(func=lambda m: m.text == "📊 পরিসংখ্যান")
def stats(message):
    if not allowed_user(message): return
    uid=message.from_user.id
    with LOCK, db() as c:
        h=c.execute("SELECT COUNT(*) n FROM hostings WHERE user_id=?",(uid,)).fetchone()["n"]
        a=c.execute("SELECT COUNT(*) n FROM hostings WHERE user_id=? AND status='active'",(uid,)).fetchone()["n"]
        d=c.execute("SELECT COALESCE(SUM(amount_taka),0) n FROM deposits WHERE user_id=? AND status='approved'",(uid,)).fetchone()["n"]
    bot.send_message(message.chat.id,f"{header('𝐌ʏ 𝐒ᴛᴀᴛɪsᴛɪᴄs','📊')}\n\n🌐 Hosting: <b>{h}</b>\n🟢 Active: <b>{a}</b>\n💳 Deposit: <b>{d:.2f} ৳</b>{footer()}",reply_markup=back_kb())

@bot.message_handler(func=lambda m: m.text == "👤 আমার প্রোফাইল")
def profile(message):
    u=user(message.from_user.id)
    bot.send_message(message.chat.id,
        f"{header('𝐌ʏ 𝐏ʀᴏғɪʟᴇ','👤')}\n\n"
        f"🆔 ID: <code>{u['user_id']}</code>\n👤 Name: <b>{esc(u['first_name'])}</b>\n"
        f"🔗 Username: @{esc(u['username']) if u['username'] else '—'}\n"
        f"💰 Balance: <b>{money(u['balance'])}</b>\n📅 Joined: {u['created_at']}{footer()}",
        reply_markup=back_kb())

@bot.message_handler(func=lambda m: m.text == "💬 সাপোর্ট")
def support(message):
    s=get_setting("support","@SmartCodeWorld")
    kb=types.InlineKeyboardMarkup()
    if s.startswith("@"): kb.add(in_btn("💬 অ্যাডমিনের সাথে যোগাযোগ",url=f"https://t.me/{s[1:]}",style="primary"))
    bot.send_message(message.chat.id,f"{header('𝐒ᴜᴘᴘᴏʀᴛ','💬')}\n\n🧑‍💻 Support: <b>{esc(s)}</b>{footer()}",reply_markup=kb)


# ========================= DEPOSIT =========================
@bot.message_handler(func=lambda m: m.text == "💳 ডিপোজিট")
def deposit(message):
    if not allowed_user(message): return
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(kb_btn("💰 ডিপোজিট করুন","success"),kb_btn("🧾 ডিপোজিট ইতিহাস","primary"))
    kb.add(kb_btn("🔙 পিছনে","primary"))
    bot.send_message(message.chat.id,
        f"{header('𝐃ᴇᴘᴏsɪᴛ','💳')}\n\n"
        f"💰 Minimum: <b>{get_setting('min_deposit','50')} ৳</b>\n"
        f"💎 Rate: <b>1৳ = {get_setting('coin_per_taka','10')} Coin</b>\n\n"
        f"💳 Methods:\n<code>{esc(get_setting('payment_methods',''))}</code>{footer()}",
        reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "💰 ডিপোজিট করুন")
def dep_start(message):
    states[message.from_user.id]={"type":"dep_amount"}
    bot.send_message(message.chat.id,"💳 Deposit Amount (৳) পাঠান।",reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: m.text == "🧾 ডিপোজিট ইতিহাস")
def dep_history(message):
    with LOCK, db() as c: rows=c.execute("SELECT * FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 10",(message.from_user.id,)).fetchall()
    if not rows: bot.send_message(message.chat.id,"📭 কোনো Deposit History নেই।",reply_markup=back_kb()); return
    lines=[header("𝐃ᴇᴘᴏsɪᴛ 𝐇ɪsᴛᴏʀʏ","🧾"),""]
    for d in rows: lines.append(f"#{d['id']} • {d['amount_taka']:.2f} ৳ → {d['coin_amount']:.0f} Coin • <b>{d['status']}</b>")
    bot.send_message(message.chat.id,"\n".join(lines)+footer(),reply_markup=back_kb())


# ========================= ADMIN =========================
def admin_kb():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
    kb.add(kb_btn("📊 বট পরিসংখ্যান","primary"),kb_btn("👥 ইউজার ম্যানেজমেন্ট","primary"))
    kb.add(kb_btn("🌐 হোস্টিং ম্যানেজমেন্ট","primary"),kb_btn("💎 প্ল্যান ম্যানেজমেন্ট","success"))
    kb.add(kb_btn("💰 ব্যালেন্স ম্যানেজমেন্ট","success"),kb_btn("💳 ডিপোজিট ম্যানেজমেন্ট","success"))
    kb.add(kb_btn("👥 রেফারেল সেটিংস","primary"),kb_btn("⚙️ সিস্টেম সেটিংস","primary"))
    kb.add(kb_btn("📢 ব্রডকাস্ট","danger"),kb_btn("📝 অ্যাডমিন লগ","primary"))
    kb.add(kb_btn("🏠 ইউজার প্যানেল","success"))
    return kb

@bot.message_handler(func=lambda m: m.text == "⚙️ অ্যাডমিন প্যানেল")
def admin_panel(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id,f"{header('𝐀ᴅᴍɪɴ 𝐏ᴀɴᴇʟ','⚙️')}\n\nসব গুরুত্বপূর্ণ System এখান থেকে Control করুন।{footer()}",reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "📊 বট পরিসংখ্যান")
def admin_stats(message):
    if not is_admin(message.from_user.id): return
    with LOCK, db() as c:
        u=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        h=c.execute("SELECT COUNT(*) n FROM hostings").fetchone()["n"]
        a=c.execute("SELECT COUNT(*) n FROM hostings WHERE status='active'").fetchone()["n"]
        d=c.execute("SELECT COALESCE(SUM(amount_taka),0) n FROM deposits WHERE status='approved'").fetchone()["n"]
        p=c.execute("SELECT COUNT(*) n FROM deposits WHERE status='pending'").fetchone()["n"]
        r=c.execute("SELECT COUNT(*) n FROM referrals").fetchone()["n"]
    bot.send_message(message.chat.id,f"{header('𝐁ᴏᴛ 𝐒ᴛᴀᴛɪsᴛɪᴄs','📊')}\n\n👥 Users: <b>{u}</b>\n🌐 Hosting: <b>{h}</b>\n🟢 Active: <b>{a}</b>\n👥 Referrals: <b>{r}</b>\n💳 Revenue: <b>{d:.2f} ৳</b>\n⏳ Pending Deposit: <b>{p}</b>{footer()}",reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "💳 ডিপোজিট ম্যানেজমেন্ট")
def admin_deposits(message):
    if not is_admin(message.from_user.id): return
    with LOCK, db() as c: rows=c.execute("SELECT * FROM deposits WHERE status='pending' ORDER BY id ASC LIMIT 30").fetchall()
    if not rows: bot.send_message(message.chat.id,"✅ Pending Deposit নেই।",reply_markup=admin_kb()); return
    for d in rows:
        kb=types.InlineKeyboardMarkup()
        kb.row(in_btn("✅ অনুমোদন",callback_data=f"approve:{d['id']}",style="success"),in_btn("❌ বাতিল",callback_data=f"reject:{d['id']}",style="danger"))
        bot.send_message(message.chat.id,f"💳 <b>Deposit #{d['id']}</b>\n👤 <code>{d['user_id']}</code>\n💰 {d['amount_taka']:.2f} ৳\n💎 {d['coin_amount']:.0f} Coin\n🔖 <code>{esc(d['trx_id'])}</code>",reply_markup=kb)

@bot.callback_query_handler(func=lambda c:c.data.startswith("approve:"))
def approve(call):
    if not is_admin(call.from_user.id): return
    did=int(call.data.split(":")[1])
    with LOCK, db() as c:
        d=c.execute("SELECT * FROM deposits WHERE id=? AND status='pending'",(did,)).fetchone()
        if not d: bot.answer_callback_query(call.id,"Already processed",show_alert=True); return
        c.execute("UPDATE deposits SET status='approved',reviewed_at=? WHERE id=?",(stamp(),did))
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(d["coin_amount"],d["user_id"]))
        c.execute("INSERT INTO transactions(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",(d["user_id"],d["coin_amount"],"deposit",f"Deposit #{did}",stamp()))
    admin_log(call.from_user.id,"deposit_approve",str(did),str(d["coin_amount"]))
    try: bot.send_message(d["user_id"],f"✅ Deposit Approved!\n💎 +{d['coin_amount']:.0f} Coin")
    except Exception: pass
    bot.answer_callback_query(call.id,"Approved")
    bot.edit_message_reply_markup(call.message.chat.id,call.message.message_id,reply_markup=None)

@bot.callback_query_handler(func=lambda c:c.data.startswith("reject:"))
def reject(call):
    if not is_admin(call.from_user.id): return
    did=int(call.data.split(":")[1])
    with LOCK, db() as c:
        d=c.execute("SELECT * FROM deposits WHERE id=? AND status='pending'",(did,)).fetchone()
        if not d: bot.answer_callback_query(call.id,"Already processed",show_alert=True); return
        c.execute("UPDATE deposits SET status='rejected',reviewed_at=? WHERE id=?",(stamp(),did))
    admin_log(call.from_user.id,"deposit_reject",str(did),"")
    try: bot.send_message(d["user_id"],f"❌ Deposit #{did} Rejected")
    except Exception: pass
    bot.answer_callback_query(call.id,"Rejected")
    bot.edit_message_reply_markup(call.message.chat.id,call.message.message_id,reply_markup=None)

@bot.message_handler(func=lambda m: m.text == "👥 রেফারেল সেটিংস")
def admin_ref(message):
    if not is_admin(message.from_user.id): return
    kb=types.InlineKeyboardMarkup()
    kb.add(in_btn("✏️ Referral Reward",callback_data="set:referral_reward",style="primary"))
    bot.send_message(message.chat.id,f"{header('𝐑ᴇғᴇʀʀᴀʟ 𝐒ᴇᴛᴛɪɴɢs','👥')}\n\n💰 Current: <b>{get_setting('referral_reward')}</b> Coin",reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "⚙️ সিস্টেম সেটিংস")
def admin_settings(message):
    if not is_admin(message.from_user.id): return
    kb=types.InlineKeyboardMarkup()
    for key,label in [("min_deposit","💳 Minimum Deposit"),("coin_per_taka","💎 Coin Rate"),("support","💬 Support"),("payment_methods","🏦 Payment Methods")]:
        kb.add(in_btn(label,callback_data=f"set:{key}",style="primary"))
    kb.add(in_btn("🛠️ Maintenance ON/OFF",callback_data="toggle:maintenance",style="danger"))
    bot.send_message(message.chat.id,f"{header('𝐒ʏsᴛᴇᴍ 𝐒ᴇᴛᴛɪɴɢs','⚙️')}\n\n💳 Minimum: {get_setting('min_deposit')} ৳\n💎 Rate: 1৳ = {get_setting('coin_per_taka')} Coin\n🛠️ Maintenance: {'ON' if get_setting('maintenance')=='1' else 'OFF'}",reply_markup=kb)

@bot.callback_query_handler(func=lambda c:c.data.startswith("set:"))
def setting_prompt(call):
    if not is_admin(call.from_user.id): return
    key=call.data.split(":",1)[1]
    states[call.from_user.id]={"type":"set","key":key}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,f"✏️ <b>{key}</b>-এর নতুন value পাঠান।",reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c:c.data=="toggle:maintenance")
def toggle(call):
    if not is_admin(call.from_user.id): return
    new="0" if get_setting("maintenance")=="1" else "1"; set_setting("maintenance",new)
    admin_log(call.from_user.id,"maintenance",new)
    bot.answer_callback_query(call.id,f"Maintenance {new}")
    admin_settings(call.message)

@bot.message_handler(func=lambda m: m.text == "💰 ব্যালেন্স ম্যানেজমেন্ট")
def admin_balance(message):
    if not is_admin(message.from_user.id): return
    states[message.from_user.id]={"type":"balance_user"}
    bot.send_message(message.chat.id,"👤 User Telegram ID দিন।",reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: m.text == "👥 ইউজার ম্যানেজমেন্ট")
def admin_users(message):
    if not is_admin(message.from_user.id): return
    states[message.from_user.id]={"type":"user_search"}
    bot.send_message(message.chat.id,"🔎 User Telegram ID দিন।",reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: m.text == "🌐 হোস্টিং ম্যানেজমেন্ট")
def admin_hosting(message):
    if not is_admin(message.from_user.id): return
    with LOCK, db() as c: rows=c.execute("SELECT * FROM hostings ORDER BY id DESC LIMIT 30").fetchall()
    if not rows: bot.send_message(message.chat.id,"📭 Hosting নেই।",reply_markup=admin_kb()); return
    text=[header("𝐇ᴏsᴛɪɴɢ 𝐌ᴀɴᴀɢᴇᴍᴇɴᴛ","🌐"),""]
    for h in rows: text.append(f"#{h['id']} • <b>{esc(h['project_name'])}</b> • <code>{h['user_id']}</code>\n🌐 {h['url']}\n📌 {h['status']} • ⏳ {h['expires_at']}\n")
    bot.send_message(message.chat.id,"\n".join(text)+footer(),reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "💎 প্ল্যান ম্যানেজমেন্ট")
def admin_plans(message):
    if not is_admin(message.from_user.id): return
    with LOCK, db() as c: rows=c.execute("SELECT * FROM plans ORDER BY id").fetchall()
    text=[header("𝐏ʟᴀɴ 𝐌ᴀɴᴀɢᴇᴍᴇɴᴛ","💎"),""]
    for p in rows: text.append(f"#{p['id']} <b>{esc(p['name'])}</b> • {p['price']:.0f} Coin • {p['storage_mb']}MB • {p['duration_days']} দিন • {p['status']}")
    bot.send_message(message.chat.id,"\n".join(text)+footer(),reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "📢 ব্রডকাস্ট")
def broadcast_start(message):
    if not is_admin(message.from_user.id): return
    states[message.from_user.id]={"type":"broadcast"}
    bot.send_message(message.chat.id,"📢 যে message Broadcast করবেন সেটি পাঠান।",reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: m.text == "📝 অ্যাডমিন লগ")
def logs(message):
    if not is_admin(message.from_user.id): return
    with LOCK, db() as c: rows=c.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 30").fetchall()
    if not rows: bot.send_message(message.chat.id,"📭 Log নেই।",reply_markup=admin_kb()); return
    text=[header("𝐀ᴅᴍɪɴ 𝐋ᴏɢs","📝"),""]
    for r in rows: text.append(f"#{r['id']} • {r['action']} • {r['target']} • {r['created_at']}")
    bot.send_message(message.chat.id,"\n".join(text)+footer(),reply_markup=admin_kb())


# ========================= DOCUMENT UPLOAD =========================
@bot.message_handler(content_types=["document"])
def document(message):
    uid=message.from_user.id
    if not allowed_user(message): return
    st=states.get(uid)
    if not st or st.get("type")!="upload":
        bot.send_message(message.chat.id,"📌 আগে Hosting Plan নির্বাচন করুন।",reply_markup=main_kb(uid)); return
    p=plan(st["plan"])
    if not p: bot.send_message(message.chat.id,"❌ Plan পাওয়া যায়নি।",reply_markup=main_kb(uid)); return
    path=None
    try:
        name=message.document.file_name or "website.zip"
        if not name.lower().endswith(".zip"):
            validate_file(name,bool(p["php_allowed"]))
        path=download_file(message.document.file_id,name)
        if name.lower().endswith(".zip"): validate_zip(path,bool(p["php_allowed"]))
        slug=make_slug(uid,st["project"])
        remote=f"{CPANEL_BASE_PATH}/{slug}"
        bot.send_message(message.chat.id,"⏳ cPanel-এ Website deploy হচ্ছে...")
        CP.mkdir(remote)
        upload_result = CP.upload(str(path), remote)
        log.info("cPanel upload succeeded: %s", upload_result)
        if name.lower().endswith(".zip"):
            archive=f"{remote}/{path.name}"
            CP.extract(archive, remote)
            try: CP.delete(archive)
            except Exception: pass
        hid,url,expires=create_hosting(uid,p,st["project"],slug)
        size=path.stat().st_size
        with LOCK, db() as c: c.execute("UPDATE hostings SET storage_bytes=? WHERE id=?",(size,hid))
        if not take_balance(uid,p["price"],f"Hosting #{hid}"):
            try: CP.delete(remote)
            except Exception: pass
            with LOCK, db() as c: c.execute("UPDATE hostings SET status='failed' WHERE id=?",(hid,))
            raise ValueError("Balance পরিবর্তিত হয়েছে। আবার চেষ্টা করুন।")
        states.pop(uid,None)
        path.unlink(missing_ok=True)
        kb=types.InlineKeyboardMarkup(); kb.add(in_btn("🌐 Website খুলুন",url=url,style="success"))
        bot.send_message(message.chat.id,
            f"{header('𝐇ᴏsᴛɪɴɢ 𝐑ᴇᴀᴅʏ','🚀')}\n\n"
            f"✅ Website সফলভাবে Host হয়েছে!\n\n"
            f"📦 Project: <b>{esc(st['project'])}</b>\n"
            f"🌐 URL: <code>{url}</code>\n"
            f"💰 Paid: <b>{money(p['price'])}</b>\n"
            f"💾 Upload: <b>{human_size(size)}</b>\n"
            f"⏳ Expiry: <b>{expires}</b>{footer()}",reply_markup=kb)
    except Exception as e:
        if path:
            try: path.unlink(missing_ok=True)
            except Exception: pass
        log.exception("deploy failed")
        bot.send_message(
            message.chat.id,
            f"❌ <b>Deploy Failed</b>\n\n<code>{esc(str(e)[:1200])}</code>\n\n"
            "💡 Upload সফল হলেও পরের ধাপে সমস্যা হলে উপরের API error-টি দেখুন।",
            reply_markup=main_kb(uid),
        )


# ========================= STATE ROUTER =========================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def text_router(message):
    uid=message.from_user.id; t=(message.text or "").strip()
    if t=="❌ বাতিল":
        states.pop(uid,None); bot.send_message(message.chat.id,"❌ বাতিল হয়েছে।",reply_markup=main_kb(uid)); return
    if t in ("🏠 হোম","🔙 পিছনে"):
        states.pop(uid,None); bot.send_message(message.chat.id,f"{header('𝐇ᴏᴍᴇ','🏠')}\n\n{BRAND}{footer()}",reply_markup=main_kb(uid)); return
    if not allowed_user(message): return
    st=states.get(uid)
    if not st: return
    typ=st.get("type")
    if typ=="project":
        if len(t)<2 or len(t)>40: bot.send_message(message.chat.id,"⚠️ Project Name 2–40 characters দিন।"); return
        p=plan(st["plan"])
        if not p: states.pop(uid,None); return
        states[uid]={"type":"upload","plan":p["id"],"project":t}
        bot.send_message(message.chat.id,
            f"{header('𝐔ᴘʟᴏᴀᴅ 𝐖ᴇʙsɪᴛᴇ','📤')}\n\n"
            f"📦 Project: <b>{esc(t)}</b>\n💾 Max: <b>{p['storage_mb']} MB</b>\n⏳ {p['duration_days']} দিন\n\n"
            "📤 এখন ZIP project পাঠান। ZIP-এর ভিতরে <code>index.html</code> রাখুন।",reply_markup=cancel_kb())
    elif typ=="dep_amount":
        try: amount=float(t.replace(",",""))
        except: bot.send_message(message.chat.id,"❌ সঠিক Amount দিন।"); return
        minimum=float(get_setting("min_deposit","50"))
        if amount<minimum: bot.send_message(message.chat.id,f"❌ Minimum {minimum:.2f} ৳"); return
        coin=amount*float(get_setting("coin_per_taka","10"))
        states[uid]={"type":"dep_trx","amount":amount,"coin":coin}
        bot.send_message(message.chat.id,f"💰 Amount: <b>{amount:.2f} ৳</b>\n💎 Coin: <b>{coin:.0f}</b>\n\nTransaction ID পাঠান।",reply_markup=cancel_kb())
    elif typ=="dep_trx":
        with LOCK, db() as c:
            cur=c.execute("INSERT INTO deposits(user_id,amount_taka,coin_amount,trx_id,status,created_at) VALUES(?,?,?,?,?,?)",(uid,st["amount"],st["coin"],t,"pending",stamp()))
            did=cur.lastrowid
        states.pop(uid,None)
        bot.send_message(message.chat.id,f"✅ Deposit Request #{did} submitted। Admin approval-এর পর Coin যোগ হবে।",reply_markup=main_kb(uid))
        notify_admins(f"💳 <b>New Deposit #{did}</b>\n👤 <code>{uid}</code>\n💰 {st['amount']:.2f} ৳\n💎 {st['coin']:.0f} Coin\n🔖 <code>{esc(t)}</code>")
    elif typ=="set" and is_admin(uid):
        set_setting(st["key"],t); admin_log(uid,"setting",st["key"],t); states.pop(uid,None)
        bot.send_message(message.chat.id,"✅ Setting updated.",reply_markup=admin_kb())
    elif typ=="balance_user" and is_admin(uid):
        if not t.isdigit(): bot.send_message(message.chat.id,"❌ সঠিক User ID দিন।"); return
        target=int(t)
        if not user(target): bot.send_message(message.chat.id,"❌ User নেই।"); return
        states[uid]={"type":"balance_amount","target":target}
        bot.send_message(message.chat.id,"💰 Coin amount দিন। Positive = Add, Negative = Remove।",reply_markup=cancel_kb())
    elif typ=="balance_amount" and is_admin(uid):
        try: amount=float(t)
        except: bot.send_message(message.chat.id,"❌ Number দিন।"); return
        target=st["target"]; u=user(target)
        if u["balance"]+amount<0: bot.send_message(message.chat.id,"❌ Balance 0-এর নিচে যাবে।"); return
        add_balance(target,amount,"admin_adjustment",f"Admin {uid}"); admin_log(uid,"balance_adjust",str(target),str(amount))
        states.pop(uid,None); bot.send_message(message.chat.id,"✅ Balance updated.",reply_markup=admin_kb())
    elif typ=="user_search" and is_admin(uid):
        if not t.isdigit(): bot.send_message(message.chat.id,"❌ সঠিক User ID দিন।"); return
        target=int(t); u=user(target)
        if not u: bot.send_message(message.chat.id,"❌ User নেই।"); return
        with LOCK,db() as c:
            h=c.execute("SELECT COUNT(*) n FROM hostings WHERE user_id=?",(target,)).fetchone()["n"]
            r=c.execute("SELECT COUNT(*) n FROM referrals WHERE referrer_id=?",(target,)).fetchone()["n"]
        states.pop(uid,None)
        bot.send_message(message.chat.id,f"{header('𝐔sᴇʀ 𝐃ᴇᴛᴀɪʟs','👤')}\n\n🆔 <code>{target}</code>\n👤 {esc(u['first_name'])}\n💰 {money(u['balance'])}\n🌐 Hosting: {h}\n👥 Referral: {r}\n🚫 Banned: {'Yes' if u['is_banned'] else 'No'}",reply_markup=admin_kb())
    elif typ=="broadcast" and is_admin(uid):
        states.pop(uid,None)
        with LOCK,db() as c: ids=[r["user_id"] for r in c.execute("SELECT user_id FROM users WHERE is_banned=0")]
        ok=bad=0
        for x in ids:
            try: bot.copy_message(x,message.chat.id,message.message_id); ok+=1
            except: bad+=1
            time.sleep(.04)
        bot.send_message(message.chat.id,f"📢 Broadcast শেষ।\n✅ {ok}\n❌ {bad}",reply_markup=admin_kb())


# ========================= PROFILE / HOME =========================
@bot.message_handler(func=lambda m: m.text == "🏠 ইউজার প্যানেল")
def user_panel(message):
    bot.send_message(message.chat.id,f"{header('𝐇ᴏᴍᴇ','🏠')}\n\n{BRAND}",reply_markup=main_kb(message.from_user.id))


# ========================= EXPIRY WORKER =========================
def expiry_worker():
    while True:
        try:
            with LOCK,db() as c:
                rows=c.execute("SELECT * FROM hostings WHERE status='active'").fetchall()
                for h in rows:
                    try: exp=datetime.strptime(h["expires_at"],"%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
                    except: continue
                    if exp<=now():
                        c.execute("UPDATE hostings SET status='expired' WHERE id=?",(h["id"],))
                        try: bot.send_message(h["user_id"],f"⏰ <b>Hosting Expired</b>\n\n🌐 {esc(h['url'])}\n🔄 Renew করতে My Hosting ব্যবহার করুন।")
                        except: pass
        except Exception: log.exception("expiry worker")
        time.sleep(300)


# ========================= RUN =========================
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise SystemExit("Set BOT_TOKEN first.")
    init_db()
    threading.Thread(target=expiry_worker,daemon=True).start()
    me=bot.get_me()
    log.info("Connected as @%s",me.username)
    bot.infinity_polling(skip_pending=True,allowed_updates=["message","callback_query"])

if __name__=="__main__":
    main()
