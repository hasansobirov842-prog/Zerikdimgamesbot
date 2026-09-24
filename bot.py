import os
import sqlite3
import random
import asyncio
import logging
import subprocess
from html import escape
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ============================================================
# ZERIKDIM GAMES - FULL BOT
# Existing DB/data are preserved.
# Sponsors are managed ONLY from the admin panel.
# ============================================================

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8679536810"))
DB_FILE = "zerikdim.db"

BUY_STARS_URL = "https://t.me/premyumstarstekin/933"
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "KARTA_RAQAMINI_GITHUB_SECRETGA_QOYING")
STARS_RATE = 205
PREMIUM_1M = 40000
PREMIUM_3M = 135000
NUMBER_PRICE = 25000

REFERRAL_REWARD = 9.0
REFERRAL_CASH = 1000.0
PREMIUM_REFERRALS_1M = 25
PREMIUM_REFERRALS_3M = 70
TASK_REWARD = 5.0
MIN_WITHDRAW = 200.0
MIN_REFERRALS = 20
GAME_COOLDOWN = 30

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("zerikdim")
save_lock = asyncio.Lock()


# =========================
# QUESTIONS / GAMES
# =========================

QUIZ = [
    ("O‘zbekiston Konstitutsiyasi qaysi yilda qabul qilingan?",
     ["1991", "1992", "1993", "1994"], 1),
    ("1 dan 20 gacha bo‘lgan sonlar yig‘indisi nechaga teng?",
     ["190", "200", "210", "220"], 2),
    ("Yer Quyosh atrofini taxminan necha kunda aylanib chiqadi?",
     ["180", "265", "365", "400"], 2),
    ("Agar 3 ta qalam 15 000 so‘m bo‘lsa, 7 ta qalam qancha?",
     ["25 000", "30 000", "35 000", "40 000"], 2),
    ("Eng katta okean qaysi?",
     ["Atlantika", "Hind", "Tinch", "Shimoliy Muz"], 2),
    ("2^5 nechaga teng?",
     ["16", "24", "32", "64"], 2),
    ("1 kilometr necha metr?",
     ["100", "500", "1000", "1500"], 2),
    ("12 × 8 − 17 nechaga teng?",
     ["69", "79", "89", "97"], 1),
]

LOGIC_QUESTIONS = [
    ("Ketma-ketlikni davom ettir: 2, 6, 12, 20, 30, ?",
     ["36", "40", "42", "44"], 2),
    ("5, 10, 20, 40, ?",
     ["60", "70", "80", "90"], 2),
    ("1, 4, 9, 16, 25, ?",
     ["30", "32", "36", "49"], 2),
    ("100, 90, 81, 73, ?",
     ["64", "66", "67", "68"], 0),
    ("3, 9, 27, 81, ?",
     ["162", "243", "324", "729"], 1),
]

WORDS = [
    ("HSTOAN", "TOSHAN"),
    ("KTOBII", "KITOBI"),
    ("MRAKTA", "MARKET"),
    ("LQAMA", "QALAM"),
    ("GOLBA", "BOGLA"),
    ("TNAEK", "KENTA"),
    ("DORS", "DORS"),
]

COLORS = [
    ("🔴", "qizil"),
    ("🔵", "ko‘k"),
    ("🟢", "yashil"),
    ("🟡", "sariq"),
]

KNOWLEDGE = [
    ("Dunyodagi eng katta qit’a qaysi?",
     ["Osiyo", "Afrika", "Yevropa", "Avstraliya"], 0),
    ("Suvning kimyoviy formulasi?",
     ["CO2", "H2O", "O2", "NaCl"], 1),
    ("Python dasturlash tilining belgisi ko‘proq nima bilan bog‘liq?",
     ["Ilon", "Qush", "Sher", "Baliq"], 0),
    ("Bir sutkada nechta soat bor?",
     ["12", "18", "24", "48"], 2),
]

GAMES = [
    ("🧠 Tezkor savol", "quiz"),
    ("🔢 Sonni top", "number"),
    ("⚡ Tez tanla", "choice"),
    ("🧩 Mantiq", "logic"),
    ("🎯 Nishon", "target"),
    ("🔤 So‘zni top", "word"),
    ("🧮 Hisobla", "math"),
    ("👀 Diqqat", "attention"),
    ("🎨 Rangni top", "color"),
    ("🔐 Kodni top", "code"),
    ("📚 Bilim", "knowledge"),
    ("⏱ Tezlik", "speed"),
]


# =========================
# DATABASE
# =========================

def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT,
            points REAL DEFAULT 0,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER,
            last_seen TEXT,
            blocked INTEGER DEFAULT 0,
            referral_rewarded INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            reward REAL DEFAULT 5,
            url TEXT NOT NULL,
            channel TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_claims(
            user_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            created_at TEXT,
            claimed_at TEXT,
            PRIMARY KEY(user_id, task_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_stats(
            id INTEGER PRIMARY KEY CHECK(id=1),
            started_at TEXT,
            total_users INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsor_settings(
            id INTEGER PRIMARY KEY CHECK(id=1),
            active INTEGER DEFAULT 1,
            disabled_at TEXT
        )
    """)

    # =========================
    # NEW SERVICE SYSTEM (keeps old DB/data)
    # =========================
    cur.execute("""CREATE TABLE IF NOT EXISTS money_payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, requested_amount REAL DEFAULT 0,
        admin_amount REAL DEFAULT 0, receipt_file_id TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS money_withdrawals(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, card TEXT,
        status TEXT DEFAULT 'pending', created_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS numbers(
        id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, number TEXT UNIQUE, price REAL DEFAULT 25000,
        sold INTEGER DEFAULT 0, buyer_id INTEGER, sold_at TEXT DEFAULT '')""")
    cur.execute("""CREATE TABLE IF NOT EXISTS service_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, platform TEXT, service TEXT,
        quantity INTEGER, link TEXT, amount REAL DEFAULT 0, status TEXT DEFAULT 'pending', created_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS premium_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, months INTEGER, amount REAL,
        status TEXT DEFAULT 'pending', created_at TEXT)""")
    # Existing users get new money columns without losing old Stars/games/referrals.
    cols = {r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()}
    for name, typ in [("money_balance","REAL DEFAULT 0"),("total_deposited","REAL DEFAULT 0"),("total_spent","REAL DEFAULT 0")]:
        if name not in cols:
            cur.execute(f"ALTER TABLE users ADD COLUMN {name} {typ}")

    # IMPORTANT: sponsors are NOT deleted/recreated on restart.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsors(
            channel TEXT PRIMARY KEY,
            url TEXT NOT NULL
        )
    """)

    cur.execute(
        "INSERT OR IGNORE INTO bot_stats(id, started_at, total_users) VALUES(1, ?, 0)",
        (now(),)
    )
    cur.execute(
        "INSERT OR IGNORE INTO sponsor_settings(id, active, disabled_at) VALUES(1, 1, NULL)"
    )

    # Repair old installations where total_users was not synced.
    cur.execute("SELECT COUNT(*) AS c FROM users")
    actual = cur.fetchone()["c"]
    cur.execute("SELECT total_users FROM bot_stats WHERE id=1")
    saved = cur.fetchone()["total_users"] or 0
    if actual > saved:
        cur.execute("UPDATE bot_stats SET total_users=? WHERE id=1", (actual,))

    con.commit()
    con.close()


def get_total_users():
    con = db()
    row = con.execute(
        "SELECT total_users FROM bot_stats WHERE id=1"
    ).fetchone()
    con.close()
    return int(row["total_users"]) if row else 0


def get_user(user_id):
    con = db()
    row = con.execute(
        "SELECT * FROM users WHERE id=?", (user_id,)
    ).fetchone()
    con.close()
    return row


def add_user_sync(user_id, username, ref=None):
    con = db()
    cur = con.cursor()

    existing = cur.execute(
        "SELECT id FROM users WHERE id=?", (user_id,)
    ).fetchone()

    if existing:
        cur.execute("""
            UPDATE users
            SET username=?, last_seen=?, blocked=0
            WHERE id=?
        """, (username or "", now(), user_id))
        con.commit()
        con.close()
        return False

    if ref == user_id:
        ref = None

    valid_ref = None
    if ref:
        r = cur.execute(
            "SELECT id FROM users WHERE id=?", (ref,)
        ).fetchone()
        if r:
            valid_ref = ref

    cur.execute("""
        INSERT INTO users(
            id, username, points, games, wins, referrals,
            referred_by, last_seen, blocked, referral_rewarded
        )
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        user_id, username or "", 0, 0, 0, 0,
        valid_ref, now(), 0, 0
    ))

    cur.execute("""
        UPDATE bot_stats
        SET total_users = total_users + 1
        WHERE id=1
    """)

    if valid_ref:
        cur.execute("""
            UPDATE users
            SET points=points+?, money_balance=money_balance+?, referrals=referrals+1
            WHERE id=?
        """, (REFERRAL_REWARD, REFERRAL_CASH, valid_ref))

        cur.execute("""
            UPDATE users SET referral_rewarded=1 WHERE id=?
        """, (user_id,))

    con.commit()
    con.close()
    return True


def change_points(user_id, amount):
    con = db()
    con.execute("""
        UPDATE users
        SET points=MAX(0, points+?)
        WHERE id=?
    """, (amount, user_id))
    con.commit()
    con.close()


def game_result(user_id, won):
    con = db()
    con.execute("""
        UPDATE users
        SET games=games+1, wins=wins+?
        WHERE id=?
    """, (1 if won else 0, user_id))
    con.commit()
    con.close()


# =========================
# SPONSORS
# =========================

def sponsor_active_sync():
    con = db()
    row = con.execute(
        "SELECT active FROM sponsor_settings WHERE id=1"
    ).fetchone()
    con.close()
    return bool(row["active"]) if row else True


def disable_sponsor_sync():
    con = db()
    con.execute("""
        UPDATE sponsor_settings
        SET active=0, disabled_at=?
        WHERE id=1
    """, (now(),))
    con.commit()
    con.close()


def enable_sponsor_sync():
    con = db()
    con.execute("""
        UPDATE sponsor_settings
        SET active=1, disabled_at=NULL
        WHERE id=1
    """)
    con.commit()
    con.close()


def get_sponsors():
    con = db()
    rows = con.execute(
        "SELECT channel,url FROM sponsors ORDER BY channel"
    ).fetchall()
    con.close()
    return rows


def normalize_channel(value):
    value = (value or "").strip()
    for prefix in (
        "https://t.me/",
        "http://t.me/",
        "https://telegram.me/",
        "http://telegram.me/"
    ):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break

    value = value.split("?")[0].split("/")[0].strip()
    if not value:
        return ""
    if not value.startswith("@"):
        value = "@" + value
    return value


def channel_url(channel):
    return "https://t.me/" + channel.lstrip("@")


def add_sponsor(channel, url=None):
    channel = normalize_channel(channel)
    if not channel:
        return False

    url = (url or "").strip() or channel_url(channel)
    if not url.startswith(("https://t.me/", "http://t.me/")):
        url = channel_url(channel)

    con = db()
    con.execute("""
        INSERT INTO sponsors(channel,url)
        VALUES(?,?)
        ON CONFLICT(channel) DO UPDATE SET url=excluded.url
    """, (channel, url))
    con.commit()
    con.close()
    return True


def remove_sponsor(channel):
    channel = normalize_channel(channel)
    con = db()
    cur = con.execute(
        "DELETE FROM sponsors WHERE channel=?", (channel,)
    )
    con.commit()
    changed = cur.rowcount > 0
    con.close()
    return changed


async def check_sponsor_membership(bot, user_id):
    if not sponsor_active_sync():
        return True

    sponsors = get_sponsors()
    if not sponsors:
        return True

    for s in sponsors:
        try:
            member = await bot.get_chat_member(s["channel"], user_id)
            if member.status not in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER
            ):
                return False
        except TelegramError:
            # If Telegram cannot inspect the channel, don't falsely lock
            # every user out. Admin can fix channel permissions.
            log.exception("Sponsor membership check failed: %s", s["channel"])
            return False

    return True


async def sponsor_limit_check(bot):
    # Kept compatible with the old 750-user first-sponsor behavior.
    sponsors = get_sponsors()
    if not sponsor_active_sync() or not sponsors:
        return

    first = sponsors[0]["channel"]

    try:
        count = await bot.get_chat_member_count(first)
        if count >= 750:
            disable_sponsor_sync()
            if ADMIN_ID:
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"⚠️ Homiy kanal {first} 750+ a'zoga yetdi.\n"
                        "Majburiy homiy obunasi avtomatik o‘chirildi."
                    )
                except TelegramError:
                    pass
    except TelegramError:
        log.exception("Sponsor count check failed")


def sponsor_keyboard():
    rows = []
    for s in get_sponsors():
        rows.append([
            InlineKeyboardButton(
                f"📢 {s['channel']}",
                url=s["url"]
            )
        ])
    rows.append([
        InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub")
    ])
    return InlineKeyboardMarkup(rows)


async def require_subscription(update, context):
    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        return True

    if await check_chat_subscription(context.bot, user_id):
        return True

    sponsors = get_sponsors()
    if not sponsors:
        return True

    text = (
        "🔒 <b>Davom etish uchun homiy kanallarga obuna bo‘ling.</b>\n\n"
        "Obuna bo‘lgach, <b>✅ Tekshirish</b> tugmasini bosing."
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text, parse_mode="HTML", reply_markup=sponsor_keyboard()
        )
    else:
        await update.effective_message.reply_text(
            text, parse_mode="HTML", reply_markup=sponsor_keyboard()
        )
    return False


async def check_chat_subscription(bot, user_id):
    return await check_sponsor_membership(bot, user_id)


# =========================
# GITHUB DATABASE BACKUP
# =========================

def git_command(*args):
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        timeout=60
    )


async def save_database():
    async with save_lock:
        try:
            con = db()
            try:
                con.execute("PRAGMA wal_checkpoint(FULL)")
            finally:
                con.close()

            if not os.path.exists(".git"):
                return

            git_command("config", "user.name", "zerikdim-bot")
            git_command("config", "user.email", "zerikdim-bot@users.noreply.github.com")

            git_command("add", "-f", DB_FILE)

            check = git_command("diff", "--cached", "--quiet")
            if check.returncode == 0:
                return

            git_command(
                "commit", "-m",
                f"Save Zerikdim database {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
            )

            branch = git_command(
                "rev-parse", "--abbrev-ref", "HEAD"
            )
            branch_name = branch.stdout.strip() or "main"

            push = git_command("push", "origin", branch_name)
            if push.returncode != 0:
                log.warning("Database push failed: %s", push.stderr[-1000:])

        except Exception:
            log.exception("Database backup error")


async def backup_loop():
    while True:
        await asyncio.sleep(300)
        await save_database()


async def sponsor_loop(bot):
    while True:
        await asyncio.sleep(60)
        await sponsor_limit_check(bot)


# =========================
# UI
# =========================

def main_keyboard():
    rows = [
        [InlineKeyboardButton("💰 PUL ISHLASH", callback_data="earn_money"), InlineKeyboardButton("⭐ STARS ISHLASH", callback_data="games")],
        [InlineKeyboardButton("💎 PREMIUM ISHLASH", callback_data="premium_earn"), InlineKeyboardButton("📱 NOMER OLISH", callback_data="numbers")],
        [InlineKeyboardButton("🚀 NAKRUTKA", callback_data="nakrutka"), InlineKeyboardButton("🛒 DO‘KON", callback_data="shop")],
        [InlineKeyboardButton("💳 HISOB TO‘LDIRISH", callback_data="topup"), InlineKeyboardButton("👤 MENING HISOBIM", callback_data="my_account")],
        [InlineKeyboardButton("🎮 O‘YINLAR", callback_data="games"), InlineKeyboardButton("🎁 TOPSHIRIQLAR", callback_data="tasks")],
        [InlineKeyboardButton("👥 REFERAL", callback_data="referral"), InlineKeyboardButton("💸 YECHIB OLISH", callback_data="withdraw")],
        [InlineKeyboardButton("🏆 REYTING", callback_data="rating"), InlineKeyboardButton("👤 PROFIL", callback_data="profile")],
    ]
    if ADMIN_ID:
        rows.append([InlineKeyboardButton("⚙️ ADMIN PANEL", callback_data="admin")])
    return InlineKeyboardMarkup(rows)


def home_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")]
    ])


def games_keyboard():
    rows = []
    for i in range(0, len(GAMES), 2):
        row = []
        for title, code in GAMES[i:i+2]:
            row.append(InlineKeyboardButton(title, callback_data=f"game_{code}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 STATISTIKA", callback_data="admin_stats"),
            InlineKeyboardButton("👥 USERLAR", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("📢 XABAR YUBORISH", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton("➕ HOMIY QO‘SHISH", callback_data="admin_add_sponsor"),
            InlineKeyboardButton("🗑 HOMIY O‘CHIRISH", callback_data="admin_remove_sponsor")
        ],
        [
            InlineKeyboardButton("📢 HOMIYLAR", callback_data="admin_sponsors")
        ],
        [
            InlineKeyboardButton("➕ TOPSHIRIQ", callback_data="admin_add_task"),
            InlineKeyboardButton("📋 TOPSHIRIQLAR", callback_data="admin_tasks")
        ],
        [
            InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")
        ],
    ])


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref = None

    if context.args:
        try:
            ref = int(context.args[0])
        except ValueError:
            ref = None

    add_user_sync(user.id, user.username, ref)
    await sponsor_limit_check(context.bot)

    if not await require_subscription(update, context):
        return

    total = get_total_users()

    if user.id == ADMIN_ID:
        text = (
            "👑 <b>Admin, xush kelibsiz!</b>\n\n"
            f"👥 Botdagi jami foydalanuvchilar: <b>{total}</b>\n\n"
            "Kerakli bo‘limni tanlang:"
        )
    else:
        text = (
            "🎮 <b>ZERIKDIM GAMES</b>\n\n"
            "⭐ O‘yinlar o‘ynang, topshiriqlarni bajaring va Stars yig‘ing!\n\n"
            "Quyidagi menyudan foydalaning:"
        )

    await update.message.reply_text(
        text, parse_mode="HTML", reply_markup=main_keyboard()
    )


# =========================
# GAME START
# =========================

async def start_game(update, context, game):
    user_id = update.effective_user.id
    key = f"game_last_{user_id}"

    loop = asyncio.get_running_loop()
    last = context.user_data.get(key, 0)
    left = GAME_COOLDOWN - (loop.time() - last)

    if left > 0:
        await update.effective_message.reply_text(
            f"⏳ Bu o‘yinni yana {int(left)+1} soniyadan keyin boshlashingiz mumkin.",
            reply_markup=home_button()
        )
        return

    context.user_data[key] = loop.time()

    if game == "quiz":
        q, opts, correct = random.choice(QUIZ)
        context.user_data["game"] = {
            "type": "choice",
            "correct": correct,
            "reward": 1.0
        }

        kb = [
            [InlineKeyboardButton(
                f"{i+1}. {opt}",
                callback_data=f"answer_{i}"
            )]
            for i, opt in enumerate(opts)
        ]
        kb.append([InlineKeyboardButton("❌ To‘xtatish", callback_data="home")])

        await update.effective_message.reply_text(
            f"🧠 <b>Savol</b>\n\n{escape(q)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif game == "number":
        target = random.randint(1, 100)
        context.user_data["game"] = {
            "type": "number", "target": target,
            "tries": 0, "reward": 1.5
        }
        await update.effective_message.reply_text(
            "🔢 <b>Sonni toping!</b>\n\n1–100 oralig‘ida son yozing.\n"
            "7 ta urinish bor.",
            parse_mode="HTML", reply_markup=home_button()
        )

    elif game == "choice":
        opts = ["A", "B", "C", "D", "E"]
        correct = random.randrange(5)
        context.user_data["game"] = {
            "type": "choice_letter",
            "correct": correct,
            "reward": 1.0
        }
        kb = [[
            InlineKeyboardButton(x, callback_data=f"choice_{i}")
            for i, x in enumerate(opts)
        ]]
        kb.append([InlineKeyboardButton("❌ To‘xtatish", callback_data="home")])
        await update.effective_message.reply_text(
            "⚡ <b>Tez tanla!</b>\n\n"
            "To‘g‘ri variantni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif game == "logic":
        q, opts, correct = random.choice(LOGIC_QUESTIONS)
        context.user_data["game"] = {
            "type": "logic", "correct": correct, "reward": 1.5
        }
        kb = [
            [InlineKeyboardButton(
                f"{i+1}. {x}", callback_data=f"logic_{i}"
            )]
            for i, x in enumerate(opts)
        ]
        await update.effective_message.reply_text(
            f"🧩 <b>Mantiq</b>\n\n{escape(q)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif game == "target":
        target = random.randint(1, 9)
        context.user_data["game"] = {
            "type": "target", "correct": target, "reward": 1.0
        }
        kb = []
        nums = list(range(1, 10))
        for i in range(0, 9, 3):
            kb.append([
                InlineKeyboardButton(
                    str(x), callback_data=f"target_{x}"
                ) for x in nums[i:i+3]
            ])
        await update.effective_message.reply_text(
            f"🎯 <b>Nishon: {target}</b>\n\n"
            "Nishonni tanlang!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif game == "word":
        scrambled, correct = random.choice(WORDS)
        context.user_data["game"] = {
            "type": "word", "correct": correct.lower(), "reward": 1.3
        }
        await update.effective_message.reply_text(
            f"🔤 <b>So‘zni toping:</b>\n\n"
            f"<code>{escape(scrambled)}</code>\n\n"
            "Javobni yozing.",
            parse_mode="HTML",
            reply_markup=home_button()
        )

    elif game == "math":
        a = random.randint(10, 50)
        b = random.randint(2, 20)
        op = random.choice(["+", "-", "×"])
        answer = a + b if op == "+" else a - b if op == "-" else a * b
        context.user_data["game"] = {
            "type": "text", "correct": str(answer), "reward": 1.7
        }
        await update.effective_message.reply_text(
            f"🧮 <b>Hisoblang:</b>\n\n"
            f"{a} {op} {b} = ?\n\nJavobni yozing.",
            parse_mode="HTML", reply_markup=home_button()
        )

    elif game == "attention":
        nums = random.sample(range(1, 10), 9)
        special = random.choice(nums)
        context.user_data["game"] = {
            "type": "attention", "correct": special, "reward": 1.2
        }
        kb = []
        for i in range(0, 9, 3):
            kb.append([
                InlineKeyboardButton(
                    str(x), callback_data=f"attention_{x}"
                ) for x in nums[i:i+3]
            ])
        await update.effective_message.reply_text(
            f"👀 <b>Diqqat!</b>\n\n"
            f"Quyidagilardan <b>{special}</b> ni tanlang.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif game == "color":
        symbol, correct = random.choice(COLORS)
        context.user_data["game"] = {
            "type": "color", "correct": correct, "reward": 1.2
        }
        kb = [[
            InlineKeyboardButton(x[1], callback_data=f"color_{x[1]}")
            for x in COLORS
        ]]
        await update.effective_message.reply_text(
            f"🎨 <b>Rangni toping:</b>\n\n{symbol}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif game == "code":
        digits = random.sample(range(1, 10), 4)
        code = "".join(map(str, digits))
        total = sum(digits)
        context.user_data["game"] = {
            "type": "text", "correct": code, "reward": 2.0
        }
        await update.effective_message.reply_text(
            "🔐 <b>Kodni toping!</b>\n\n"
            f"4 ta raqam bor. Raqamlar yig‘indisi: <b>{total}</b>\n"
            "Kodning 4 raqamini yozing.",
            parse_mode="HTML", reply_markup=home_button()
        )

    elif game == "knowledge":
        q, opts, correct = random.choice(KNOWLEDGE)
        context.user_data["game"] = {
            "type": "knowledge", "correct": correct, "reward": 1.3
        }
        kb = [
            [InlineKeyboardButton(
                f"{i+1}. {x}", callback_data=f"knowledge_{i}"
            )]
            for i, x in enumerate(opts)
        ]
        await update.effective_message.reply_text(
            f"📚 <b>Bilim</b>\n\n{escape(q)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif game == "speed":
        a = random.randint(10, 40)
        b = random.randint(10, 40)
        answer = a + b
        context.user_data["game"] = {
            "type": "text", "correct": str(answer), "reward": 2.0
        }
        await update.effective_message.reply_text(
            f"⏱ <b>Tezlik!</b>\n\n"
            f"{a} + {b} = ?\n\nJavobni yozing.",
            parse_mode="HTML", reply_markup=home_button()
        )


async def finish_game(update, context, correct):
    user_id = update.effective_user.id
    game = context.user_data.pop("game", None)

    if not game:
        return

    if correct:
        reward = float(game.get("reward", 1.0))
        change_points(user_id, reward)
        game_result(user_id, True)
        await update.effective_message.reply_text(
            f"🎉 <b>To‘g‘ri!</b>\n\n⭐ +{reward:g} Stars",
            parse_mode="HTML",
            reply_markup=games_keyboard()
        )
    else:
        game_result(user_id, False)
        await update.effective_message.reply_text(
            "❌ <b>Noto‘g‘ri!</b>\n\n"
            "Keyingi o‘yinda omad! 🍀",
            parse_mode="HTML",
            reply_markup=games_keyboard()
        )

    await save_database()


async def process_text_game(update, context):
    game = context.user_data.get("game")
    if not game:
        return False

    text = update.message.text.strip()

    if game["type"] == "number":
        try:
            guess = int(text)
        except ValueError:
            await update.message.reply_text("🔢 Faqat son yuboring.")
            return True

        game["tries"] += 1
        target = game["target"]

        if guess == target:
            await finish_game(update, context, True)
            return True

        if game["tries"] >= 7:
            context.user_data.pop("game", None)
            game_result(update.effective_user.id, False)
            await update.message.reply_text(
                f"❌ Urinishlar tugadi. To‘g‘ri javob: {target}",
                reply_markup=games_keyboard()
            )
            await save_database()
            return True

        hint = "⬆️ Kattaroq son kiriting." if guess < target else "⬇️ Kichikroq son kiriting."
        await update.message.reply_text(
            f"{hint}\nQolgan urinish: {7-game['tries']}"
        )
        return True

    if game["type"] in ("text", "word"):
        answer = str(game["correct"]).strip().lower()
        if text.lower() == answer:
            await finish_game(update, context, True)
        else:
            await finish_game(update, context, False)
        return True

    return False


# =========================
# TASKS
# =========================

def list_tasks():
    con = db()
    rows = con.execute(
        "SELECT * FROM tasks ORDER BY id DESC"
    ).fetchall()
    con.close()
    return rows


# =========================
# CALLBACK HANDLER
# =========================

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user = q.from_user
    add_user_sync(user.id, user.username)

    data = q.data

    if data == "check_sub":
        if await check_chat_subscription(context.bot, user.id):
            await q.message.reply_text(
                "✅ Obuna tasdiqlandi!",
                reply_markup=main_keyboard()
            )
        else:
            await q.message.reply_text(
                "❌ Hali barcha homiy kanallarga obuna bo‘lmagansiz.",
                reply_markup=sponsor_keyboard()
            )
        return

    if user.id != ADMIN_ID:
        if not await check_chat_subscription(context.bot, user.id):
            await q.message.reply_text(
                "🔒 Avval homiy kanallarga obuna bo‘ling.",
                reply_markup=sponsor_keyboard()
            )
            return

    if data == "home":
        context.user_data.pop("game", None)
        context.user_data.pop("admin_action", None)
        await q.message.reply_text(
            "🏠 <b>Bosh menyu</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
        return

    # =========================
    # NEW SERVICE MENUS
    # =========================
    if data == "earn_money":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start={user.id}"
        await q.message.reply_text("💰 <b>PUL ISHLASH</b>\n\n" f"👥 Referal: har bir yangi user uchun +{REFERRAL_REWARD:g} ⭐\n" f"🔗 Link: <code>{link}</code>", parse_mode="HTML", reply_markup=home_button())
        return

    if data == "premium_earn":
        u=get_user(user.id); refs=u["referrals"]
        buttons=[]
        if refs >= PREMIUM_REFERRALS_3M: buttons.append([InlineKeyboardButton("💎 3 OY PREMIUM",callback_data="prem_claim_3")])
        if refs >= PREMIUM_REFERRALS_1M: buttons.append([InlineKeyboardButton("💎 1 OY PREMIUM",callback_data="prem_claim_1")])
        buttons.append([InlineKeyboardButton("🏠 Bosh menyu",callback_data="home")])
        await q.message.reply_text(f"💎 <b>PREMIUM ISHLASH</b>\n\n👥 Sizda: <b>{refs}</b> referal\n🎁 25 ta → 1 oy\n🎁 70 ta → 3 oy",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons)); return

    if data.startswith("prem_claim_"):
        months=int(data.split("_")[-1]); need=PREMIUM_REFERRALS_1M if months==1 else PREMIUM_REFERRALS_3M; u=get_user(user.id)
        if u["referrals"]<need: await q.message.reply_text(f"❌ {need} ta referal kerak.",reply_markup=home_button()); return
        con=db(); cur=con.execute("INSERT INTO premium_orders(user_id,months,amount,status,created_at) VALUES(?,?,?,'pending',?)",(user.id,months,0,now())); oid=cur.lastrowid; con.commit(); con.close(); await q.message.reply_text(f"✅ {months} oylik Premium so‘rovi #{oid} adminga yuborildi.",reply_markup=home_button())
        if ADMIN_ID: await context.bot.send_message(ADMIN_ID,f"🎁 PREMIUM REFERRAL #{oid}\n👤 {user.id}\n👥 {u['referrals']} referal\n💎 {months} oy",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ BERILDI",callback_data=f"premdone_{oid}"),InlineKeyboardButton("❌ RAD",callback_data=f"premrefund_{oid}")]]))
        return

    if data == "numbers":
        await q.message.reply_text("📱 <b>NOMER OLISH</b>\n\n🇹🇯 Tojikiston — 25 000 so‘m\n🇷🇺 Rossiya — 25 000 so‘m\n\nKerakli davlatni tanlang:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🇹🇯 Tojikiston — 25 000", callback_data="num_TJ")],[InlineKeyboardButton("🇷🇺 Rossiya — 25 000", callback_data="num_RU")],[InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")]]))
        return

    if data.startswith("num_"):
        country=data[4:]
        con=db(); row=con.execute("SELECT * FROM numbers WHERE country=? AND sold=0 ORDER BY id LIMIT 1",(country,)).fetchone(); con.close()
        if not row:
            await q.message.reply_text("❌ Hozircha bu davlat uchun nomer qolmagan.", reply_markup=home_button()); return
        u=get_user(user.id)
        money=float(u["money_balance"] or 0)
        if money < row["price"]:
            await q.message.reply_text(f"❌ Balans yetarli emas.\n\n💰 Narx: {row['price']:,.0f} so‘m\n💳 Sizda: {money:,.0f} so‘m", reply_markup=home_button()); return
        con=db(); con.execute("UPDATE users SET money_balance=money_balance-?, total_spent=total_spent+? WHERE id=?",(row["price"],row["price"],user.id)); con.execute("UPDATE numbers SET sold=1,buyer_id=?,sold_at=? WHERE id=?",(user.id,now(),row["id"])); con.commit(); con.close()
        await q.message.reply_text(f"✅ Nomer olindi!\n\n🌍 {country}\n📱 <code>{escape(row['number'])}</code>",parse_mode="HTML",reply_markup=home_button()); await save_database(); return

    if data == "nakrutka":
        await q.message.reply_text("🚀 <b>NAKRUTKA</b>\n\nPlatformani tanlang:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Telegram", callback_data="plat_Telegram")],[InlineKeyboardButton("🎵 TikTok", callback_data="plat_TikTok")],[InlineKeyboardButton("📸 Instagram", callback_data="plat_Instagram")],[InlineKeyboardButton("▶️ YouTube", callback_data="plat_YouTube")],[InlineKeyboardButton("📘 Facebook", callback_data="plat_Facebook")],[InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")]]))
        return

    if data.startswith("plat_"):
        platform=data[5:]
        sub="6 000 so‘m / 1K" if platform=="Telegram" else "26 000 so‘m / 1K"
        view="3 000 so‘m / 1K ko‘rish" if platform=="Telegram" else "15 000 so‘m / 1K ko‘rish"
        await q.message.reply_text(f"{platform}\n\n👥 Obunachi: <b>{sub}</b>\n👁 Ko‘rish: <b>{view}</b>\n\nXizmatni tanlang:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👥 OBUNACHI",callback_data=f"svc_{platform}_followers")],[InlineKeyboardButton("👁 KO‘RISH / PRASMOTR",callback_data=f"svc_{platform}_views")],[InlineKeyboardButton("🏠 Bosh menyu",callback_data="home")]])); return

    if data.startswith("svc_"):
        _,platform,service=data.split("_",2); context.user_data["order_draft"]={"platform":platform,"service":service}; context.user_data["state"]="order_qty"
        await q.message.reply_text("🔢 Miqdorni yozing. Masalan: 1000 yoki 10000\n\nBekor qilish: /cancel"); return

    if data == "shop":
        await q.message.reply_text("🛒 <b>DO‘KON</b>\n\n⭐ Telegram Stars\n💎 Premium\n📱 Nomer\n🚀 Nakrutka",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Stars",callback_data="buy")],[InlineKeyboardButton("💎 Premium",callback_data="premium_buy")],[InlineKeyboardButton("📱 Nomer",callback_data="numbers")],[InlineKeyboardButton("🚀 Nakrutka",callback_data="nakrutka")],[InlineKeyboardButton("🏠 Bosh menyu",callback_data="home")]])); return

    if data == "premium_buy":
        await q.message.reply_text("💎 <b>PREMIUM</b>\n\n1 oy — 40 000 so‘m\n3 oy — 135 000 so‘m",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("1 oy — 40 000",callback_data="prem_1")],[InlineKeyboardButton("3 oy — 135 000",callback_data="prem_3")],[InlineKeyboardButton("🏠 Bosh menyu",callback_data="home")]])); return

    if data.startswith("prem_"):
        months=int(data.split("_")[1]); amount=PREMIUM_1M if months==1 else PREMIUM_3M; u=get_user(user.id); money=float(u["money_balance"] or 0)
        if money<amount: await q.message.reply_text(f"❌ Balans yetarli emas.\nKerak: {amount:,.0f} so‘m\nSizda: {money:,.0f} so‘m",reply_markup=home_button()); return
        con=db(); cur=con.execute("INSERT INTO premium_orders(user_id,months,amount,status,created_at) VALUES(?,?,?,'pending',?)",(user.id,months,amount,now())); oid=cur.lastrowid; con.execute("UPDATE users SET money_balance=money_balance-?, total_spent=total_spent+? WHERE id=?",(amount,amount,user.id)); con.commit(); con.close()
        await q.message.reply_text(f"✅ Premium so‘rovi #{oid} yuborildi.\n⏳ Admin tasdig‘ini kuting.",reply_markup=home_button())
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID,f"💎 PREMIUM BUY #{oid}\n👤 {user.id}\n📦 {months} oy\n💰 {amount:,.0f} so‘m",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ BERILDI",callback_data=f"premdone_{oid}"),InlineKeyboardButton("❌ RAD + QAYTARISH",callback_data=f"premrefund_{oid}")]]))
        await save_database(); return

    if data == "my_account":
        u=get_user(user.id); money=float(u["money_balance"] or 0)
        await q.message.reply_text(f"👤 <b>MENING HISOBIM</b>\n\n💰 Pul: <b>{money:,.0f} so‘m</b>\n⭐ Stars: <b>{u['points']:.1f}</b>\n👥 Referal: <b>{u['referrals']}</b>\n🎮 O‘yinlar: <b>{u['games']}</b>",parse_mode="HTML",reply_markup=home_button()); return

    if data == "topup":
        context.user_data["state"]="topup_amount"; await q.message.reply_text(f"💳 <b>HISOB TO‘LDIRISH</b>\n\nKarta: <code>{escape(PAYMENT_CARD)}</code>\n\nQancha to‘lov qilganingizni yozing, keyin chek rasmini yuboring.",parse_mode="HTML"); return

    if data == "games":
        await q.message.reply_text(
            "🎯 <b>STARS ISHLASH</b>\n\n"
            "O‘yinlardan birini tanlang:",
            parse_mode="HTML",
            reply_markup=games_keyboard()
        )
        return

    if data.startswith("game_"):
        await start_game(update, context, data[5:])
        return

    # Quiz / logic / target / attention / color / knowledge buttons
    if data.startswith("answer_"):
        game = context.user_data.get("game")
        if not game or game.get("type") != "choice":
            await q.message.reply_text("❌ O‘yin topilmadi.")
            return
        try:
            selected = int(data.split("_", 1)[1])
        except ValueError:
            return
        await finish_game(update, context, selected == game["correct"])
        return

    if data.startswith("choice_"):
        game = context.user_data.get("game")
        if not game:
            return
        selected = int(data.split("_", 1)[1])
        await finish_game(update, context, selected == game["correct"])
        return

    if data.startswith("logic_"):
        game = context.user_data.get("game")
        if not game:
            return
        selected = int(data.split("_", 1)[1])
        await finish_game(update, context, selected == game["correct"])
        return

    if data.startswith("target_"):
        game = context.user_data.get("game")
        if not game:
            return
        selected = int(data.split("_", 1)[1])
        await finish_game(update, context, selected == game["correct"])
        return

    if data.startswith("attention_"):
        game = context.user_data.get("game")
        if not game:
            return
        selected = int(data.split("_", 1)[1])
        await finish_game(update, context, selected == game["correct"])
        return

    if data.startswith("color_"):
        game = context.user_data.get("game")
        if not game:
            return
        selected = data.split("_", 1)[1].lower()
        await finish_game(update, context, selected == str(game["correct"]).lower())
        return

    if data.startswith("knowledge_"):
        game = context.user_data.get("game")
        if not game:
            return
        selected = int(data.split("_", 1)[1])
        await finish_game(update, context, selected == game["correct"])
        return

    if data == "buy":
        prices = {50:10999,100:22500,200:44000,500:99500,1000:199000,5000:999000}
        kb = [[InlineKeyboardButton(f"⭐ {a} — {prices[a]:,} so‘m", callback_data=f"buy_{a}")] for a in prices]
        kb += [[InlineKeyboardButton("🛒 Stars sotib olish", url=BUY_STARS_URL)], [InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")]]
        await q.message.reply_text("⭐ <b>STARS OLISH</b>\n\nKerakli paketni tanlang:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("buy_"):
        amount=int(data[4:]); prices={50:10999,100:22500,200:44000,500:99500,1000:199000,5000:999000}; price=prices.get(amount,amount*STARS_RATE)
        await q.message.reply_text(f"⭐ <b>{amount} Stars</b>\n\n💰 Narxi: <b>{price:,} so‘m</b>\n📌 Kurs: 1 ⭐ = {STARS_RATE} so‘m",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Sotib olish",url=BUY_STARS_URL)],[InlineKeyboardButton("🏠 Bosh menyu",callback_data="home")]])); return

    if data == "balance":
        row = get_user(user.id)
        await q.message.reply_text(
            f"💰 <b>Balans</b>\n\n"
            f"💵 Pul: <b>{float(row['money_balance'] or 0):,.0f} so‘m</b>\n"
            f"⭐ Stars: <b>{row['points']:.2f}</b>\n"
            f"👥 Referallar: <b>{row['referrals']}</b>",
            parse_mode="HTML",
            reply_markup=home_button()
        )
        return

    if data == "profile":
        row = get_user(user.id)
        await q.message.reply_text(
            f"👤 <b>Profil</b>\n\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"👤 Username: @{escape(user.username or 'yo‘q')}\n"
            f"⭐ Stars: <b>{row['points']:.2f}</b>",
            parse_mode="HTML",
            reply_markup=home_button()
        )
        return

    if data == "referral":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start={user.id}"
        await q.message.reply_text(
            "👥 <b>REFERAL TIZIMI</b>\n\n"
            f"Har bir taklif qilingan faol user uchun: "
            f"<b>+{REFERRAL_REWARD:g} ⭐</b>\n\n"
            f"🔗 Sizning linkingiz:\n<code>{link}</code>",
            parse_mode="HTML",
            reply_markup=home_button()
        )
        return

    if data == "tasks":
        rows = list_tasks()
        if not rows:
            await q.message.reply_text(
                "🎁 Hozircha topshiriqlar yo‘q.",
                reply_markup=home_button()
            )
            return

        buttons = []
        text = "🎁 <b>TOPSHIRIQLAR</b>\n\n"
        for t in rows:
            text += (
                f"🆔 {t['id']} — {escape(t['text'])}\n"
                f"⭐ +{t['reward']:g}\n\n"
            )
            buttons.append([
                InlineKeyboardButton(
                    f"🎁 {t['id']}-topshiriq",
                    url=t["url"]
                ),
                InlineKeyboardButton(
                    "✅ Bajardim",
                    callback_data=f"taskdone_{t['id']}"
                )
            ])

        buttons.append([
            InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")
        ])

        await q.message.reply_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("taskdone_"):
        task_id = int(data.split("_", 1)[1])
        con = db()
        task = con.execute(
            "SELECT * FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        claimed = con.execute(
            "SELECT 1 FROM task_claims WHERE user_id=? AND task_id=?",
            (user.id, task_id)
        ).fetchone()
        con.close()

        if not task:
            await q.message.reply_text("❌ Topshiriq topilmadi.")
            return

        if claimed:
            await q.message.reply_text("ℹ️ Bu topshiriqni oldin bajargansiz.")
            return

        channel = normalize_channel(task["channel"] or task["url"])

        if not channel:
            await q.message.reply_text(
                "⚠️ Bu topshiriq uchun kanal sozlanmagan. Adminga murojaat qiling."
            )
            return

        try:
            member = await context.bot.get_chat_member(channel, user.id)
            ok = member.status in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER
            )
        except TelegramError:
            ok = False

        if not ok:
            await q.message.reply_text(
                "❌ Avval topshiriqdagi kanalga obuna bo‘ling."
            )
            return

        con = db()
        con.execute("""
            INSERT OR IGNORE INTO task_claims(
                user_id,task_id,created_at,claimed_at
            ) VALUES(?,?,?,?)
        """, (user.id, task_id, now(), now()))
        con.execute(
            "UPDATE users SET points=points+? WHERE id=?",
            (float(task["reward"]), user.id)
        )
        con.commit()
        con.close()

        await q.message.reply_text(
            f"🎉 Topshiriq bajarildi!\n\n"
            f"⭐ +{float(task['reward']):g} Stars",
            reply_markup=home_button()
        )
        await save_database()
        return

    if data == "rating":
        con = db()
        rows = con.execute("""
            SELECT username, points
            FROM users
            ORDER BY points DESC
            LIMIT 10
        """).fetchall()
        con.close()

        text = "🏆 <b>TOP 10 REYTING</b>\n\n"
        if not rows:
            text += "Hozircha ma’lumot yo‘q."
        else:
            for i, r in enumerate(rows, 1):
                name = escape(r["username"] or "User")
                text += f"{i}. @{name} — ⭐ {r['points']:.2f}\n"

        await q.message.reply_text(
            text, parse_mode="HTML", reply_markup=home_button()
        )
        return

    if data == "withdraw":
        row = get_user(user.id)

        if row["points"] < MIN_WITHDRAW:
            await q.message.reply_text(
                f"❌ Yechib olish uchun kamida ⭐ {MIN_WITHDRAW:g} kerak.\n"
                f"Sizda: ⭐ {row['points']:.2f}",
                reply_markup=home_button()
            )
            return

        if row["referrals"] < MIN_REFERRALS:
            await q.message.reply_text(
                f"❌ Kamida {MIN_REFERRALS} ta referal kerak.\n"
                f"Sizda: {row['referrals']} ta",
                reply_markup=home_button()
            )
            return

        con = db()
        pending = con.execute("""
            SELECT id FROM withdrawals
            WHERE user_id=? AND status='pending'
            LIMIT 1
        """, (user.id,)).fetchone()

        if pending:
            con.close()
            await q.message.reply_text(
                "⏳ Sizda allaqachon kutilayotgan yechib olish so‘rovi bor.",
                reply_markup=home_button()
            )
            return

        con.execute(
            "UPDATE users SET points=points-? WHERE id=?",
            (MIN_WITHDRAW, user.id)
        )
        cur = con.execute("""
            INSERT INTO withdrawals(user_id,amount,status,created_at)
            VALUES(?,?,?,?)
        """, (user.id, MIN_WITHDRAW, "pending", now()))
        wid = cur.lastrowid
        con.commit()
        con.close()

        await q.message.reply_text(
            "✅ Yechib olish so‘rovi yuborildi.\n"
            f"⭐ Miqdor: {MIN_WITHDRAW:g}\n"
            "👑 Admin tasdiqlashini kuting.",
            reply_markup=home_button()
        )

        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"💸 <b>YANGI WITHDRAWAL</b>\n\n"
                    f"🆔 User: <code>{user.id}</code>\n"
                    f"👤 @{escape(user.username or 'yo‘q')}\n"
                    f"⭐ Miqdor: <b>{MIN_WITHDRAW:g}</b>\n"
                    f"📌 ID: <code>{wid}</code>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ TASDIQLASH", callback_data=f"approve_{wid}"),
                        InlineKeyboardButton("❌ RAD ETISH", callback_data=f"reject_{wid}")
                    ]])
                )
            except TelegramError:
                pass

        await save_database()
        return

    if data.startswith("premdone_") or data.startswith("premrefund_"):
        if user.id != ADMIN_ID: return
        oid=int(data.split("_")[1]); approve=data.startswith("premdone_"); con=db(); row=con.execute("SELECT * FROM premium_orders WHERE id=?",(oid,)).fetchone()
        if not row or row["status"]!="pending": con.close(); await q.answer("So‘rov allaqachon ko‘rilgan",show_alert=True); return
        status="approved" if approve else "refunded"; con.execute("UPDATE premium_orders SET status=? WHERE id=?",(status,oid))
        if not approve: con.execute("UPDATE users SET money_balance=money_balance+? WHERE id=?",(row["amount"],row["user_id"]))
        con.commit(); con.close(); await context.bot.send_message(row["user_id"],("✅ Premium berildi." if approve else "❌ Premium so‘rovi rad etildi, pul qaytarildi.")); await q.edit_message_reply_markup(reply_markup=None); return

    if data.startswith("payapprove_") or data.startswith("payreject_"):
        if user.id != ADMIN_ID: return
        pid=int(data.split("_")[1]); approve=data.startswith("payapprove_"); con=db(); row=con.execute("SELECT * FROM money_payments WHERE id=?",(pid,)).fetchone()
        if not row or row["status"]!="pending": con.close(); await q.answer("So‘rov allaqachon ko‘rilgan",show_alert=True); return
        status="approved" if approve else "rejected"; con.execute("UPDATE money_payments SET status=?,admin_amount=? WHERE id=?",(status,row["requested_amount"] if approve else 0,pid))
        if approve: con.execute("UPDATE users SET money_balance=money_balance+?,total_deposited=total_deposited+? WHERE id=?",(row["requested_amount"],row["requested_amount"],row["user_id"]))
        con.commit(); con.close(); await context.bot.send_message(row["user_id"],f"{'✅ Hisobingizga pul qo‘shildi: '+format(row['requested_amount'],',.0f')+' so‘m' if approve else '❌ To‘lov rad etildi.'}"); await q.edit_message_reply_markup(reply_markup=None); return

    if data.startswith("orddone_") or data.startswith("ordrefund_"):
        if user.id != ADMIN_ID: return
        oid=int(data.split("_")[1]); approve=data.startswith("orddone_"); con=db(); row=con.execute("SELECT * FROM service_orders WHERE id=?",(oid,)).fetchone()
        if not row or row["status"]!="pending": con.close(); await q.answer("So‘rov allaqachon ko‘rilgan",show_alert=True); return
        con.execute("UPDATE service_orders SET status=? WHERE id=?",("done" if approve else "refunded",oid))
        if not approve: con.execute("UPDATE users SET money_balance=money_balance+? WHERE id=?",(row["amount"],row["user_id"]))
        con.commit(); con.close(); await context.bot.send_message(row["user_id"],("✅ Buyurtma bajarildi." if approve else "❌ Buyurtma rad etildi, pul qaytarildi.")); await q.edit_message_reply_markup(reply_markup=None); return

    # =========================
    # ADMIN
    # =========================

    if data == "admin":
        if user.id != ADMIN_ID:
            return
        await q.message.reply_text(
            "⚙️ <b>ADMIN PANEL</b>",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        return

    if data == "admin_stats":
        if user.id != ADMIN_ID:
            return

        con = db()
        users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        points = con.execute("SELECT COALESCE(SUM(points),0) s FROM users").fetchone()["s"]
        refs = con.execute("SELECT COALESCE(SUM(referrals),0) s FROM users").fetchone()["s"]
        pending = con.execute(
            "SELECT COUNT(*) c FROM withdrawals WHERE status='pending'"
        ).fetchone()["c"]
        games = con.execute("SELECT COALESCE(SUM(games),0) s FROM users").fetchone()["s"]
        wins = con.execute("SELECT COALESCE(SUM(wins),0) s FROM users").fetchone()["s"]
        con.close()

        sponsors = get_sponsors()
        sponsor_text = "\n".join(
            f"• {escape(s['channel'])}" for s in sponsors
        ) or "• Homiy kanal yo‘q"

        status = "🟢 Yoqilgan" if sponsor_active_sync() else "🔴 O‘chirilgan"

        await q.message.reply_text(
            "📊 <b>BOT STATISTIKASI</b>\n\n"
            f"👥 Hozirgi userlar: <b>{users}</b>\n"
            f"💾 Saqlangan jami userlar: <b>{get_total_users()}</b>\n"
            f"⭐ Jami balans: <b>{points:.2f}</b>\n"
            f"👥 Jami referallar: <b>{refs}</b>\n"
            f"🎮 O‘yinlar: <b>{games}</b>\n"
            f"🏆 G‘alabalar: <b>{wins}</b>\n"
            f"💸 Kutilayotgan withdrawal: <b>{pending}</b>\n\n"
            f"🔒 Majburiy homiy obunasi: <b>{status}</b>\n"
            f"📢 <b>Homiylar:</b>\n{sponsor_text}",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        return

    if data == "admin_users":
        if user.id != ADMIN_ID:
            return
        await q.message.reply_text(
            f"👥 <b>Jami foydalanuvchilar:</b> {get_total_users()}",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        return

    if data == "admin_broadcast":
        if user.id != ADMIN_ID:
            return
        context.user_data["admin_action"] = "broadcast"
        await q.message.reply_text(
            "📢 <b>BROADCAST</b>\n\n"
            "Barcha bot foydalanuvchilariga yuboriladigan xabarni yozing.\n"
            "Bekor qilish: /cancel",
            parse_mode="HTML"
        )
        return

    if data == "admin_add_sponsor":
        if user.id != ADMIN_ID:
            return
        context.user_data["admin_action"] = "add_sponsor"
        await q.message.reply_text(
            "➕ <b>HOMIY QO‘SHISH</b>\n\n"
            "Kanal username yoki link yuboring.\n\n"
            "Masalan:\n"
            "<code>@kanal</code>\n"
            "yoki\n"
            "<code>https://t.me/kanal</code>\n\n"
            "Bot kanalga admin qilingan bo‘lishi kerak.",
            parse_mode="HTML"
        )
        return

    if data == "admin_remove_sponsor":
        if user.id != ADMIN_ID:
            return

        sponsors = get_sponsors()
        if not sponsors:
            await q.message.reply_text(
                "📢 Homiy kanallar yo‘q.",
                reply_markup=admin_keyboard()
            )
            return

        kb = [
            [InlineKeyboardButton(
                f"🗑 {s['channel']}",
                callback_data=f"remove_sponsor:{s['channel'].lstrip('@')}"
            )]
            for s in sponsors
        ]
        kb.append([InlineKeyboardButton("⬅️ Admin", callback_data="admin")])

        await q.message.reply_text(
            "🗑 O‘chiriladigan homiyni tanlang:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if data.startswith("remove_sponsor:"):
        if user.id != ADMIN_ID:
            return
        channel = "@" + data.split(":", 1)[1]
        if remove_sponsor(channel):
            await q.message.reply_text(
                f"✅ {channel} o‘chirildi.",
                reply_markup=admin_keyboard()
            )
        else:
            await q.message.reply_text(
                "❌ Kanal topilmadi.",
                reply_markup=admin_keyboard()
            )
        return

    if data == "admin_sponsors":
        if user.id != ADMIN_ID:
            return
        sponsors = get_sponsors()
        text = "📢 <b>HOMIY KANALLAR</b>\n\n"
        if sponsors:
            for i, s in enumerate(sponsors, 1):
                text += f"{i}. {escape(s['channel'])}\n{s['url']}\n\n"
        else:
            text += "Homiy kanal qo‘shilmagan.\n\n"
        text += (
            f"🔒 Majburiy obuna: "
            f"{'🟢 YOQILGAN' if sponsor_active_sync() else '🔴 O‘CHIRILGAN'}"
        )
        await q.message.reply_text(
            text, parse_mode="HTML", reply_markup=admin_keyboard()
        )
        return

    if data == "admin_add_task":
        if user.id != ADMIN_ID:
            return
        context.user_data["admin_action"] = "add_task"
        await q.message.reply_text(
            "➕ <b>TOPSHIRIQ QO‘SHISH</b>\n\n"
            "Shu formatda yuboring:\n\n"
            "<code>Matn | 5 | https://t.me/kanal</code>\n\n"
            "Reward raqam bo‘lishi kerak.",
            parse_mode="HTML"
        )
        return

    if data == "admin_tasks":
        if user.id != ADMIN_ID:
            return
        rows = list_tasks()
        text = "📋 <b>TOPSHIRIQLAR</b>\n\n"
        if not rows:
            text += "Topshiriqlar yo‘q."
        else:
            for t in rows:
                text += (
                    f"🆔 {t['id']}\n"
                    f"📝 {escape(t['text'])}\n"
                    f"⭐ {t['reward']:g}\n"
                    f"🔗 {t['url']}\n\n"
                )
        await q.message.reply_text(
            text, parse_mode="HTML", reply_markup=admin_keyboard()
        )
        return

    if data.startswith("approve_") or data.startswith("reject_"):
        if user.id != ADMIN_ID:
            return

        try:
            wid = int(data.split("_", 1)[1])
        except ValueError:
            return

        action = "approved" if data.startswith("approve_") else "rejected"

        con = db()
        row = con.execute(
            "SELECT * FROM withdrawals WHERE id=?", (wid,)
        ).fetchone()

        if not row or row["status"] != "pending":
            con.close()
            await q.answer("Bu so‘rov allaqachon ko‘rilgan.", show_alert=True)
            return

        con.execute(
            "UPDATE withdrawals SET status=? WHERE id=?",
            (action, wid)
        )

        if action == "rejected":
            con.execute(
                "UPDATE users SET points=points+? WHERE id=?",
                (row["amount"], row["user_id"])
            )

        con.commit()
        con.close()

        try:
            if action == "approved":
                await context.bot.send_message(
                    row["user_id"],
                    f"✅ Withdrawal #{wid} tasdiqlandi.\n"
                    f"⭐ Miqdor: {row['amount']:g}"
                )
            else:
                await context.bot.send_message(
                    row["user_id"],
                    f"❌ Withdrawal #{wid} rad etildi.\n"
                    f"⭐ {row['amount']:g} Stars balansingizga qaytarildi."
                )
        except TelegramError:
            pass

        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(
            f"✅ So‘rov #{wid}: {action}",
            reply_markup=admin_keyboard()
        )
        await save_database()
        return


# =========================
# ADMIN TEXT ACTIONS
# =========================

async def admin_message(update, context):
    user = update.effective_user

    if user.id != ADMIN_ID:
        return False

    action = context.user_data.get("admin_action")
    if not action:
        return False

    text = update.message.text.strip()

    if action == "broadcast":
        con = db()
        rows = con.execute(
            "SELECT id FROM users WHERE blocked=0"
        ).fetchall()
        con.close()

        sent = 0
        blocked = 0

        for r in rows:
            uid = r["id"]
            try:
                await context.bot.send_message(uid, text)
                sent += 1
                await asyncio.sleep(0.04)
            except Forbidden:
                con = db()
                con.execute(
                    "UPDATE users SET blocked=1 WHERE id=?", (uid,)
                )
                con.commit()
                con.close()
                blocked += 1
            except RetryAfter as e:
                await asyncio.sleep(float(e.retry_after) + 1)
                try:
                    await context.bot.send_message(uid, text)
                    sent += 1
                except TelegramError:
                    pass
            except TelegramError:
                pass

        context.user_data.pop("admin_action", None)

        await update.message.reply_text(
            f"📢 <b>Broadcast tugadi</b>\n\n"
            f"✅ Yuborildi: {sent}\n"
            f"🚫 Bloklaganlar: {blocked}",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        await save_database()
        return True

    if action == "add_sponsor":
        channel = normalize_channel(text)

        if not channel:
            await update.message.reply_text("❌ Kanal noto‘g‘ri.")
            return True

        add_sponsor(channel, channel_url(channel))
        context.user_data.pop("admin_action", None)

        await update.message.reply_text(
            f"✅ Homiy kanal qo‘shildi: {channel}\n\n"
            "⚠️ Botni shu kanalga admin qiling.",
            reply_markup=admin_keyboard()
        )
        return True

    if action == "add_task":
        parts = [x.strip() for x in text.split("|", 2)]

        if len(parts) != 3:
            await update.message.reply_text(
                "❌ Format xato.\n\n"
                "To‘g‘ri:\n"
                "Matn | 5 | https://t.me/kanal"
            )
            return True

        task_text, reward_text, url = parts

        try:
            reward = float(reward_text)
        except ValueError:
            await update.message.reply_text("❌ Reward raqam bo‘lishi kerak.")
            return True

        if not url.startswith(("https://t.me/", "http://t.me/")):
            await update.message.reply_text(
                "❌ URL Telegram kanal linki bo‘lishi kerak."
            )
            return True

        channel = normalize_channel(url)

        con = db()
        con.execute("""
            INSERT INTO tasks(text,reward,url,channel)
            VALUES(?,?,?,?)
        """, (task_text, reward, url, channel))
        con.commit()
        con.close()

        context.user_data.pop("admin_action", None)

        await update.message.reply_text(
            f"✅ Topshiriq qo‘shildi!\n\n"
            f"📝 {escape(task_text)}\n"
            f"⭐ {reward:g}\n"
            f"📢 {escape(channel)}",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        await save_database()
        return True

    return False


# =========================
# NEW SERVICE TEXT / PHOTO ROUTERS
# =========================
async def new_service_text(update, context):
    state=context.user_data.get("state"); text=(update.message.text or "").strip(); uid=update.effective_user.id
    if state=="topup_amount":
        try: amount=float(text.replace(" ","").replace(",","."))
        except ValueError: await update.message.reply_text("❌ Summani raqam bilan yozing."); return True
        if amount<=0: await update.message.reply_text("❌ Summa 0 dan katta bo‘lsin."); return True
        context.user_data["topup_amount"]=amount; context.user_data["state"]="topup_receipt"; await update.message.reply_text(f"💰 {amount:,.0f} so‘m\n📸 Endi chek rasmini yuboring."); return True
    if state=="order_qty":
        try: qty=int(text.replace(" ",""))
        except ValueError: await update.message.reply_text("❌ Miqdorni son bilan yozing."); return True
        if qty<1000: await update.message.reply_text("❌ Minimal miqdor 1000."); return True
        d=context.user_data.get("order_draft")
        if not d: context.user_data.clear(); return False
        per=6000 if d["platform"]=="Telegram" and d["service"]=="followers" else 3000 if d["platform"]=="Telegram" else 26000 if d["service"]=="followers" else 15000
        amount=per*(qty/1000); context.user_data["order_draft"].update(quantity=qty,amount=amount); context.user_data["state"]="order_link"; await update.message.reply_text(f"💰 Narx: {amount:,.0f} so‘m\n🔗 Endi kanal/post/video havolasini yuboring."); return True
    if state=="order_link":
        d=context.user_data.get("order_draft"); u=get_user(uid); amount=float(d["amount"]); money=float(u["money_balance"] or 0)
        if money<amount: await update.message.reply_text(f"❌ Balans yetarli emas. Kerak: {amount:,.0f} so‘m\nSizda: {money:,.0f} so‘m"); return True
        con=db(); cur=con.execute("INSERT INTO service_orders(user_id,platform,service,quantity,link,amount,status,created_at) VALUES(?,?,?,?,?,?,?,?)",(uid,d["platform"],d["service"],d["quantity"],text,amount,"pending",now())); oid=cur.lastrowid; con.execute("UPDATE users SET money_balance=money_balance-?,total_spent=total_spent+? WHERE id=?",(amount,amount,uid)); con.commit(); con.close(); context.user_data.clear(); await update.message.reply_text(f"✅ Buyurtma #{oid} qabul qilindi.\n💰 {amount:,.0f} so‘m\n⏳ Admin tekshiradi.",reply_markup=home_button());
        if ADMIN_ID: await context.bot.send_message(ADMIN_ID,f"🚀 NAKRUTKA #{oid}\n👤 {uid}\n📱 {d['platform']}\n📦 {d['service']}\n🔢 {d['quantity']}\n💰 {amount:,.0f}\n🔗 {text}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ BAJARILDI",callback_data=f"orddone_{oid}"),InlineKeyboardButton("❌ RAD + QAYTARISH",callback_data=f"ordrefund_{oid}")]]))
        await save_database(); return True
    return False

async def new_photo_router(update, context):
    if context.user_data.get("state")!="topup_receipt": return False
    amount=context.user_data.get("topup_amount")
    if not amount: return False
    fid=update.message.photo[-1].file_id; con=db(); cur=con.execute("INSERT INTO money_payments(user_id,requested_amount,receipt_file_id,status,created_at) VALUES(?,?,?,?,?)",(update.effective_user.id,amount,fid,"pending",now())); pid=cur.lastrowid; con.commit(); con.close(); context.user_data.clear(); await update.message.reply_text(f"✅ Chek #{pid} adminga yuborildi.\n⏳ Tasdiqlashni kuting.")
    if ADMIN_ID: await context.bot.send_photo(ADMIN_ID,fid,caption=f"💳 CHEK #{pid}\n👤 User: {update.effective_user.id}\n💰 Summa: {amount:,.0f} so‘m",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ TASDIQLASH",callback_data=f"payapprove_{pid}"),InlineKeyboardButton("❌ RAD ETISH",callback_data=f"payreject_{pid}")]]))
    return True

# =========================
# TEXT ROUTER
# =========================

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_message(update, context): return
    if await new_service_text(update, context): return
    if await process_text_game(update, context): return
    await update.message.reply_text("🏠 Menyudan foydalaning:", reply_markup=main_keyboard())


# =========================
# COMMANDS
# =========================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Bekor qilindi.",
        reply_markup=main_keyboard()
    )


async def user_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Sizning ID: <code>{update.effective_user.id}</code>",
        parse_mode="HTML"
    )


# =========================
# ERROR / LIFECYCLE
# =========================

async def error_handler(update, context):
    log.exception("Unhandled error", exc_info=context.error)


async def post_init(application):
    init_db()

    try:
        await application.bot.set_my_short_description("@bookmeet")
    except TelegramError:
        pass

    application.create_task(backup_loop())
    application.create_task(sponsor_loop(application.bot))

    await save_database()

    log.info(
        "Bot started. Users=%s Sponsors=%s",
        get_total_users(),
        len(get_sponsors())
    )


async def post_shutdown(application):
    await save_database()


def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN GitHub Secret/environment variable topilmadi."
        )

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("id", user_id_command))

    app.add_handler(CallbackQueryHandler(menu))
    app.add_handler(MessageHandler(filters.PHOTO, new_photo_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    app.add_error_handler(error_handler)

    log.info("Polling started")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
