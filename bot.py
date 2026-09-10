import os
import sqlite3
import random
import logging
import asyncio
import subprocess
from datetime import datetime, timezone, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "8679536810"))
except ValueError:
    ADMIN_ID = 8679536810

DB = "zerikdim.db"

# Stars
GAME_REWARD = 0.02
TASK_REWARD = 5.0
REFERRAL_REWARD = 9.0

# Withdraw
MIN_WITHDRAW = 200.0
MIN_REFERRALS = 20

# Game cooldown
GAME_COOLDOWN = 30

# Sponsor limit
SPONSOR_LIMIT = 20000

# Stars sotib olish linki
BUY_STARS_URL = "https://t.me/premyumstarstekin/933"

# Backup
BACKUP_INTERVAL = 300

PAGE_SIZE = 10

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("zerikdim")


# =========================================================
# YORDAMCHI
# =========================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def db_connect():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def is_admin(user_id):
    return int(user_id) == ADMIN_ID


def normalize_channel(value):
    value = (value or "").strip()

    if value.startswith("https://t.me/"):
        value = value.replace("https://t.me/", "")
    elif value.startswith("http://t.me/"):
        value = value.replace("http://t.me/", "")
    elif value.startswith("t.me/"):
        value = value.replace("t.me/", "")

    value = value.split("/")[0]
    value = value.split("?")[0]
    value = value.strip()

    if value and not value.startswith("@"):
        value = "@" + value

    return value


def normalize_url(channel):
    channel = normalize_channel(channel)
    return f"https://t.me/{channel.lstrip('@')}"


# =========================================================
# DATABASE
# =========================================================

def ensure_column(conn, table, column, definition):
    cols = conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    names = {row["name"] for row in cols}

    if column not in names:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    conn = db_connect()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            reward REAL DEFAULT 5,
            url TEXT,
            channel TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_claims (
            user_id INTEGER,
            task_id INTEGER,
            created_at TEXT,
            claimed_at TEXT,
            PRIMARY KEY(user_id, task_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_stats (
            id INTEGER PRIMARY KEY CHECK(id=1),
            started_at TEXT,
            total_users INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sponsor_settings (
            id INTEGER PRIMARY KEY CHECK(id=1),
            active INTEGER DEFAULT 1,
            disabled_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            channel TEXT PRIMARY KEY,
            url TEXT
        )
    """)

    # Eski DB lar uchun migration
    ensure_column(conn, "users", "username", "TEXT")
    ensure_column(conn, "users", "points", "REAL DEFAULT 0")
    ensure_column(conn, "users", "games", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "wins", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "referrals", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "referred_by", "INTEGER")
    ensure_column(conn, "users", "last_seen", "TEXT")
    ensure_column(conn, "users", "blocked", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "referral_rewarded", "INTEGER DEFAULT 0")

    conn.execute("""
        INSERT OR IGNORE INTO bot_stats
        (id, started_at, total_users)
        VALUES (1, ?, 0)
    """, (now_iso(),))

    conn.execute("""
        INSERT OR IGNORE INTO sponsor_settings
        (id, active, disabled_at)
        VALUES (1, 1, NULL)
    """)

    # Muhim:
    # mavjud statistika hech qachon 0 ga tushirilmaydi
    actual_users = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    stored = conn.execute(
        "SELECT total_users FROM bot_stats WHERE id=1"
    ).fetchone()["total_users"]

    if actual_users > stored:
        conn.execute(
            "UPDATE bot_stats SET total_users=? WHERE id=1",
            (actual_users,)
        )

    conn.commit()
    conn.close()


# =========================================================
# USER
# =========================================================

def add_user_sync(user_id, username, referred_by=None):
    conn = db_connect()

    existing = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    username = username or ""

    if existing is None:
        ref = None

        if referred_by:
            try:
                referred_by = int(referred_by)
            except Exception:
                referred_by = None

            if referred_by == user_id:
                referred_by = None

            if referred_by:
                ref_exists = conn.execute(
                    "SELECT id FROM users WHERE id=?",
                    (referred_by,)
                ).fetchone()

                if not ref_exists:
                    referred_by = None

            ref = referred_by

        conn.execute("""
            INSERT INTO users
            (
                id,
                username,
                points,
                games,
                wins,
                referrals,
                referred_by,
                last_seen,
                blocked,
                referral_rewarded
            )
            VALUES (?, ?, 0, 0, 0, 0, ?, ?, 0, 0)
        """, (
            user_id,
            username,
            ref,
            now_iso(),
        ))

        conn.execute("""
            UPDATE bot_stats
            SET total_users = total_users + 1
            WHERE id=1
        """)

        # Referal mukofoti
        if ref:
            conn.execute("""
                UPDATE users
                SET
                    points = points + ?,
                    referrals = referrals + 1
                WHERE id=?
            """, (
                REFERRAL_REWARD,
                ref,
            ))

        new_user = True

    else:
        conn.execute("""
            UPDATE users
            SET
                username=?,
                last_seen=?,
                blocked=0
            WHERE id=?
        """, (
            username,
            now_iso(),
            user_id,
        ))

        new_user = False

    conn.commit()
    conn.close()

    return new_user


def touch_user_sync(user_id, username=None):
    conn = db_connect()

    if username is None:
        conn.execute("""
            UPDATE users
            SET last_seen=?, blocked=0
            WHERE id=?
        """, (now_iso(), user_id))
    else:
        conn.execute("""
            UPDATE users
            SET username=?, last_seen=?, blocked=0
            WHERE id=?
        """, (
            username,
            now_iso(),
            user_id,
        ))

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db_connect()

    row = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    return row


def get_total_users():
    conn = db_connect()

    row = conn.execute(
        "SELECT total_users FROM bot_stats WHERE id=1"
    ).fetchone()

    conn.close()

    return int(row["total_users"]) if row else 0


def get_active_users():
    conn = db_connect()

    limit = (
        datetime.now(timezone.utc) -
        timedelta(days=7)
    ).isoformat()

    row = conn.execute("""
        SELECT COUNT(*) AS c
        FROM users
        WHERE last_seen >= ?
        AND blocked=0
    """, (limit,)).fetchone()

    conn.close()

    return int(row["c"])


# =========================================================
# BALANS
# =========================================================

def add_points(user_id, amount):
    conn = db_connect()

    conn.execute("""
        UPDATE users
        SET points = points + ?
        WHERE id=?
    """, (
        amount,
        user_id,
    ))

    conn.commit()
    conn.close()


def subtract_points(user_id, amount):
    conn = db_connect()

    cur = conn.execute("""
        UPDATE users
        SET points = points - ?
        WHERE id=?
        AND points >= ?
    """, (
        amount,
        user_id,
        amount,
    ))

    conn.commit()

    ok = cur.rowcount > 0

    conn.close()

    return ok


def add_game_result(user_id, won):
    conn = db_connect()

    conn.execute("""
        UPDATE users
        SET games=games+1,
            wins=wins+?
        WHERE id=?
    """, (
        1 if won else 0,
        user_id,
    ))

    if won:
        conn.execute("""
            UPDATE users
            SET points=points+?
            WHERE id=?
        """, (
            GAME_REWARD,
            user_id,
        ))

    conn.commit()
    conn.close()


# =========================================================
# SPONSOR
# =========================================================

def get_sponsors():
    conn = db_connect()

    rows = conn.execute("""
        SELECT channel, url
        FROM sponsors
        ORDER BY channel
    """).fetchall()

    conn.close()

    return rows


def add_sponsor_sync(channel, url):
    channel = normalize_channel(channel)

    if not channel:
        return False

    url = url.strip() if url else normalize_url(channel)

    conn = db_connect()

    conn.execute("""
        INSERT INTO sponsors(channel, url)
        VALUES(?, ?)
        ON CONFLICT(channel)
        DO UPDATE SET url=excluded.url
    """, (
        channel,
        url,
    ))

    # Shu homiy uchun avtomatik 5 Stars topshiriq
    exists = conn.execute("""
        SELECT id
        FROM tasks
        WHERE channel=?
        LIMIT 1
    """, (channel,)).fetchone()

    if exists is None:
        conn.execute("""
            INSERT INTO tasks(text, reward, url, channel)
            VALUES(?, ?, ?, ?)
        """, (
            f"📢 {channel} kanaliga obuna bo‘ling",
            TASK_REWARD,
            url,
            channel,
        ))

    conn.commit()
    conn.close()

    return True


def remove_sponsor_sync(channel):
    channel = normalize_channel(channel)

    conn = db_connect()

    conn.execute(
        "DELETE FROM sponsors WHERE channel=?",
        (channel,)
    )

    # Shu homiyga tegishli avtomatik topshiriqlarni ham o‘chiramiz
    conn.execute(
        "DELETE FROM tasks WHERE channel=?",
        (channel,)
    )

    conn.commit()
    conn.close()


def sponsor_active():
    conn = db_connect()

    row = conn.execute("""
        SELECT active
        FROM sponsor_settings
        WHERE id=1
    """).fetchone()

    conn.close()

    return bool(row["active"]) if row else True


def set_sponsor_active(value):
    conn = db_connect()

    conn.execute("""
        UPDATE sponsor_settings
        SET active=?,
            disabled_at=?
        WHERE id=1
    """, (
        1 if value else 0,
        None if value else now_iso(),
    ))

    conn.commit()
    conn.close()


async def check_sponsor_membership(bot, user_id):
    sponsors = get_sponsors()

    if not sponsors:
        return True

    if not sponsor_active():
        return True

    if is_admin(user_id):
        return True

    for sponsor in sponsors:
        channel = sponsor["channel"]

        try:
            member = await bot.get_chat_member(
                chat_id=channel,
                user_id=user_id,
            )

            status = member.status

            if status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.BANNED,
            ):
                return False

            if status == ChatMemberStatus.RESTRICTED:
                if hasattr(member, "is_member") and not member.is_member:
                    return False

        except TelegramError as e:
            logger.warning(
                "Sponsor tekshirish xatosi %s: %s",
                channel,
                e,
            )

            # Bot kanalni tekshira olmasa, foydalanuvchini bloklamaymiz
            continue

    return True


async def sponsor_limit_check(bot):
    sponsors = get_sponsors()

    if not sponsors:
        return

    for sponsor in sponsors:
        channel = sponsor["channel"]

        try:
            count = await bot.get_chat_member_count(channel)

            if count >= SPONSOR_LIMIT:
                set_sponsor_active(False)

                try:
                    await bot.send_message(
                        ADMIN_ID,
                        (
                            "⚠️ <b>Homiy obuna tizimi avtomatik o‘chirildi.</b>\n\n"
                            f"📢 Kanal: {channel}\n"
                            f"👥 A'zolar: {count}\n"
                            f"🔢 Limit: {SPONSOR_LIMIT}"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

                break

        except TelegramError:
            continue


# =========================================================
# TASKS
# =========================================================

def get_tasks():
    conn = db_connect()

    rows = conn.execute("""
        SELECT *
        FROM tasks
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return rows


def user_claimed_task(user_id, task_id):
    conn = db_connect()

    row = conn.execute("""
        SELECT 1
        FROM task_claims
        WHERE user_id=? AND task_id=?
    """, (
        user_id,
        task_id,
    )).fetchone()

    conn.close()

    return row is not None


def claim_task_sync(user_id, task_id):
    conn = db_connect()

    task = conn.execute("""
        SELECT *
        FROM tasks
        WHERE id=?
    """, (task_id,)).fetchone()

    if task is None:
        conn.close()
        return False, 0

    already = conn.execute("""
        SELECT 1
        FROM task_claims
        WHERE user_id=? AND task_id=?
    """, (
        user_id,
        task_id,
    )).fetchone()

    if already:
        conn.close()
        return False, 0

    conn.execute("""
        INSERT INTO task_claims
        (user_id, task_id, created_at, claimed_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        task_id,
        now_iso(),
        now_iso(),
    ))

    conn.execute("""
        UPDATE users
        SET points=points+?
        WHERE id=?
    """, (
        float(task["reward"]),
        user_id,
    ))

    conn.commit()
    conn.close()

    return True, float(task["reward"])


def add_custom_task(text, reward, url, channel=None):
    conn = db_connect()

    cur = conn.execute("""
        INSERT INTO tasks(text, reward, url, channel)
        VALUES (?, ?, ?, ?)
    """, (
        text,
        reward,
        url,
        channel,
    ))

    task_id = cur.lastrowid

    conn.commit()
    conn.close()

    return task_id


def delete_task(task_id):
    conn = db_connect()

    conn.execute(
        "DELETE FROM task_claims WHERE task_id=?",
        (task_id,)
    )

    conn.execute(
        "DELETE FROM tasks WHERE id=?",
        (task_id,)
    )

    conn.commit()
    conn.close()


# =========================================================
# WITHDRAW
# =========================================================

def has_pending_withdrawal(user_id):
    conn = db_connect()

    row = conn.execute("""
        SELECT id
        FROM withdrawals
        WHERE user_id=?
        AND status='pending'
        LIMIT 1
    """, (user_id,)).fetchone()

    conn.close()

    return row is not None


def create_withdrawal(user_id, amount):
    conn = db_connect()

    user = conn.execute("""
        SELECT points, referrals
        FROM users
        WHERE id=?
    """, (user_id,)).fetchone()

    if user is None:
        conn.close()
        return False, "user"

    if user["points"] < amount:
        conn.close()
        return False, "balance"

    if user["referrals"] < MIN_REFERRALS:
        conn.close()
        return False, "referrals"

    pending = conn.execute("""
        SELECT id
        FROM withdrawals
        WHERE user_id=?
        AND status='pending'
        LIMIT 1
    """, (user_id,)).fetchone()

    if pending:
        conn.close()
        return False, "pending"

    conn.execute("""
        UPDATE users
        SET points=points-?
        WHERE id=?
    """, (
        amount,
        user_id,
    ))

    cur = conn.execute("""
        INSERT INTO withdrawals
        (user_id, amount, status, created_at)
        VALUES (?, ?, 'pending', ?)
    """, (
        user_id,
        amount,
        now_iso(),
    ))

    withdrawal_id = cur.lastrowid

    conn.commit()
    conn.close()

    return withdrawal_id, "ok"


def get_pending_withdrawals():
    conn = db_connect()

    rows = conn.execute("""
        SELECT *
        FROM withdrawals
        WHERE status='pending'
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return rows


def approve_withdrawal_sync(withdrawal_id):
    conn = db_connect()

    cur = conn.execute("""
        UPDATE withdrawals
        SET status='approved'
        WHERE id=?
        AND status='pending'
    """, (withdrawal_id,))

    conn.commit()

    ok = cur.rowcount > 0

    row = conn.execute("""
        SELECT user_id, amount
        FROM withdrawals
        WHERE id=?
    """, (withdrawal_id,)).fetchone()

    conn.close()

    return ok, row


def reject_withdrawal_sync(withdrawal_id):
    conn = db_connect()

    row = conn.execute("""
        SELECT user_id, amount
        FROM withdrawals
        WHERE id=?
        AND status='pending'
    """, (withdrawal_id,)).fetchone()

    if row is None:
        conn.close()
        return False, None

    conn.execute("""
        UPDATE withdrawals
        SET status='rejected'
        WHERE id=?
        AND status='pending'
    """, (withdrawal_id,))

    conn.execute("""
        UPDATE users
        SET points=points+?
        WHERE id=?
    """, (
        row["amount"],
        row["user_id"],
    ))

    conn.commit()
    conn.close()

    return True, row


# =========================================================
# RATING
# =========================================================

def get_rating(limit=10):
    conn = db_connect()

    rows = conn.execute("""
        SELECT id, username, points, referrals, wins
        FROM users
        ORDER BY points DESC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()

    return rows


# =========================================================
# GAMES
# =========================================================

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


QUIZZES = [
    ("O‘zbekiston poytaxti qaysi?", ["Toshkent", "Samarqand", "Buxoro"], 0),
    ("2 + 2 × 2 = ?", ["6", "8", "4"], 0),
    ("Yerning tabiiy yo‘ldoshi?", ["Oy", "Mars", "Quyosh"], 0),
    ("Eng katta okean?", ["Tinch okeani", "Atlantika", "Hind"], 0),
    ("Bir haftada nechta kun bor?", ["5", "7", "10"], 1),
    ("Python nima?", ["Dasturlash tili", "O‘yin", "Telefon"], 0),
]


LOGIC = [
    ("Ketma-ketlikni davom ettir: 2, 4, 8, 16, ?", ["24", "32", "30"], 1),
    ("3, 6, 12, 24, ?", ["36", "48", "42"], 1),
    ("1, 4, 9, 16, ?", ["20", "25", "30"], 1),
]


KNOWLEDGE = [
    ("1 kilometr necha metr?", ["100", "1000", "10000"], 1),
    ("Haftada nechta kun?", ["6", "7", "8"], 1),
    ("O‘zbekiston qaysi qit'ada?", ["Osiyo", "Afrika", "Yevropa"], 0),
]


WORDS = [
    ("Kompyuter so‘zining bosh harfi?", ["K", "T", "P"], 0),
    ("Telegram so‘zining oxirgi harfi?", ["m", "n", "g"], 1),
    ("Python so‘zining birinchi harfi?", ["P", "Y", "T"], 0),
]


COLORS = [
    ("🔴", ["Qizil", "Ko‘k", "Yashil"], 0),
    ("🔵", ["Sariq", "Ko‘k", "Qora"], 1),
    ("🟢", ["Yashil", "Oq", "Qizil"], 0),
]


# =========================================================
# KEYBOARD
# =========================================================

def main_keyboard(user_id=None):
    rows = [
        [
            InlineKeyboardButton(
                "⭐ STARS OLISH",
                callback_data="stars_get"
            ),
            InlineKeyboardButton(
                "🎯 STARS ISHLASH",
                callback_data="games"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎮 O‘YINLAR",
                callback_data="games"
            ),
        ],
        [
            InlineKeyboardButton(
                "💰 BALANS",
                callback_data="balance"
            ),
            InlineKeyboardButton(
                "🎁 TOPSHIRIQLAR",
                callback_data="tasks"
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="referral"
            ),
            InlineKeyboardButton(
                "💸 YECHIB OLISH",
                callback_data="withdraw"
            ),
        ],
        [
            InlineKeyboardButton(
                "⭐ STARS SOTIB OLISH",
                url=BUY_STARS_URL
            ),
        ],
        [
            InlineKeyboardButton(
                "🏆 REYTING",
                callback_data="rating"
            ),
            InlineKeyboardButton(
                "👤 PROFIL",
                callback_data="profile"
            ),
        ],
    ]

    if user_id is not None and is_admin(user_id):
        rows.append([
            InlineKeyboardButton(
                "⚙️ ADMIN PANEL",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(rows)


def back_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 BOSH MENYU",
                callback_data="home"
            )
        ]
    ])


def games_keyboard():
    rows = []

    for i in range(0, len(GAMES), 2):
        row = []

        for name, key in GAMES[i:i + 2]:
            row.append(
                InlineKeyboardButton(
                    name,
                    callback_data=f"game:{key}"
                )
            )

        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            "🔙 BOSH MENYU",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(rows)


# =========================================================
# START / SUBSCRIPTION
# =========================================================

async def require_subscription(update, context):
    user = update.effective_user

    ok = await check_sponsor_membership(
        context.bot,
        user.id,
    )

    if ok:
        return True

    sponsors = get_sponsors()

    buttons = []

    for sponsor in sponsors:
        buttons.append([
            InlineKeyboardButton(
                f"📢 {sponsor['channel']}",
                url=sponsor["url"]
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✅ TEKSHIRISH",
            callback_data="check_sub"
        )
    ])

    text = (
        "🔒 <b>Botdan foydalanish uchun homiy kanallarga obuna bo‘ling.</b>\n\n"
        "Obuna bo‘lgach, <b>TEKSHIRISH</b> tugmasini bosing."
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        await update.effective_message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referred_by = None

    if context.args:
        try:
            referred_by = int(context.args[0])
        except Exception:
            referred_by = None

    add_user_sync(
        user.id,
        user.username,
        referred_by,
    )

    context.user_data.pop("action", None)
    context.user_data.pop("game", None)

    if not await require_subscription(update, context):
        return

    text = (
        "🎮 <b>ZERIKDIM GAMES</b>\n\n"
        "⭐ Stars ishlab o‘ynang!\n"
        "🎁 Topshiriqlarni bajaring!\n"
        "👥 Do‘stlaringizni taklif qiling!\n\n"
        "👇 Kerakli bo‘limni tanlang:"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(user.id),
    )


# =========================================================
# PROFILE / BALANCE
# =========================================================

async def show_balance(update, context):
    user = update.effective_user

    row = get_user(user.id)

    points = float(row["points"]) if row else 0

    text = (
        "💰 <b>BALANS</b>\n\n"
        f"⭐ Stars: <b>{points:.2f}</b>\n\n"
        f"💸 Yechish minimumi: <b>{MIN_WITHDRAW:.0f} ⭐</b>\n"
        f"👥 Kerakli referal: <b>{MIN_REFERRALS}</b>"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def show_profile(update, context):
    user = update.effective_user

    row = get_user(user.id)

    points = float(row["points"]) if row else 0

    username = (
        f"@{user.username}"
        if user.username
        else "username yo‘q"
    )

    text = (
        "👤 <b>PROFIL</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Username: {username}\n"
        f"⭐ Stars: <b>{points:.2f}</b>\n"
        f"👥 Referallar: <b>{row['referrals'] if row else 0}</b>"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


# =========================================================
# REFERRAL
# =========================================================

async def show_referral(update, context):
    user = update.effective_user

    row = get_user(user.id)

    referrals = row["referrals"] if row else 0

    me = await context.bot.get_me()

    link = f"https://t.me/{me.username}?start={user.id}"

    text = (
        "👥 <b>REFERAL TIZIMI</b>\n\n"
        f"👥 Referallar: <b>{referrals}</b>\n"
        f"🎁 Har bir yangi referal: <b>+{REFERRAL_REWARD:.0f} ⭐</b>\n\n"
        "🔗 Sizning referal linkingiz:\n"
        f"<code>{link}</code>"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


# =========================================================
# STARS OLISH
# =========================================================

async def show_stars_get(update, context):
    text = (
        "⭐ <b>STARS OLISH</b>\n\n"
        "🎁 Stars olish yo‘llari:\n\n"
        "🎯 O‘yinlarda g‘alaba qozoning\n"
        "📢 Homiy topshiriqlarini bajaring\n"
        "👥 Do‘stlaringizni taklif qiling\n\n"
        "⭐ Har bir topshiriq: "
        f"<b>+{TASK_REWARD:.0f} Stars</b>"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


# =========================================================
# TASKS
# =========================================================

async def show_tasks(update, context):
    user_id = update.effective_user.id

    tasks = get_tasks()

    if not tasks:
        await update.effective_message.reply_text(
            "🎁 Hozircha topshiriqlar mavjud emas.",
            reply_markup=back_keyboard(),
        )
        return

    buttons = []

    for task in tasks:
        claimed = user_claimed_task(
            user_id,
            task["id"],
        )

        if claimed:
            label = f"✅ {task['text']}"
        else:
            label = (
                f"🎁 {task['text']} "
                f"(+{float(task['reward']):.0f}⭐)"
            )

        buttons.append([
            InlineKeyboardButton(
                label[:60],
                callback_data=f"task:{task['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 BOSH MENYU",
            callback_data="home"
        )
    ])

    await update.effective_message.reply_text(
        "🎁 <b>TOPSHIRIQLAR</b>\n\n"
        "Topshiriqni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def task_click(update, context):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    try:
        task_id = int(q.data.split(":")[1])
    except Exception:
        return

    conn = db_connect()

    task = conn.execute(
        "SELECT * FROM tasks WHERE id=?",
        (task_id,)
    ).fetchone()

    conn.close()

    if task is None:
        await q.message.reply_text(
            "❌ Topshiriq topilmadi."
        )
        return

    if user_claimed_task(user_id, task_id):
        await q.message.reply_text(
            "✅ Bu topshiriqni avval bajargansiz."
        )
        return

    if task["channel"]:
        try:
            member = await context.bot.get_chat_member(
                task["channel"],
                user_id,
            )

            if member.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.BANNED,
            ):
                await q.message.reply_text(
                    "❌ Avval kanalga obuna bo‘ling.",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "📢 OBUNA BO‘LISH",
                                url=task["url"]
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🔄 TEKSHIRISH",
                                callback_data=f"task:{task_id}"
                            )
                        ],
                    ]),
                )
                return

        except TelegramError:
            await q.message.reply_text(
                "⚠️ Kanal obunasini tekshirib bo‘lmadi.\n"
                "Bot kanalga admin qilinganini tekshiring."
            )
            return

    ok, reward = claim_task_sync(
        user_id,
        task_id,
    )

    if not ok:
        await q.message.reply_text(
            "❌ Bu topshiriq allaqachon bajarilgan."
        )
        return

    await q.message.reply_text(
        f"🎉 <b>Topshiriq bajarildi!</b>\n\n"
        f"⭐ +{reward:.0f} Stars",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


# =========================================================
# GAMES
# =========================================================

def can_play(context):
    last = context.user_data.get("last_game_time")

    if not last:
        return True, 0

    diff = datetime.now(timezone.utc).timestamp() - last

    if diff < GAME_COOLDOWN:
        return False, int(GAME_COOLDOWN - diff)

    return True, 0


async def games_menu(update, context):
    await update.effective_message.reply_text(
        "🎮 <b>O‘YINLAR</b>\n\n"
        "⭐ G‘alaba qozonsangiz "
        f"<b>+{GAME_REWARD:.2f} Stars</b> olasiz.\n\n"
        "O‘yinni tanlang:",
        parse_mode="HTML",
        reply_markup=games_keyboard(),
    )


async def start_game(update, context, game_type):
    user = update.effective_user

    if not await require_subscription(update, context):
        return

    allowed, remaining = can_play(context)

    if not allowed:
        await update.effective_message.reply_text(
            f"⏳ Keyingi o‘yinni "
            f"<b>{remaining} soniya</b>dan keyin o‘ynang.",
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )
        return

    context.user_data["last_game_time"] = (
        datetime.now(timezone.utc).timestamp()
    )

    context.user_data["game"] = {
        "type": game_type,
        "started": now_iso(),
    }

    # Telegram native games
    if game_type == "target":
        await update.effective_message.reply_dice(
            emoji="🎯"
        )

        # 4+ ni yutuq deb hisoblaymiz
        # Telegram dice value qaytaradi
        context.user_data["native_game"] = True
        return

    if game_type == "quiz":
        question, options, correct = random.choice(QUIZZES)

        context.user_data["game"]["correct"] = correct

        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔹 {opt}",
                    callback_data=f"answer:{correct}:{i}"
                )
            ]
            for i, opt in enumerate(options)
        ]

        await update.effective_message.reply_text(
            f"🧠 <b>{question}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if game_type == "logic":
        question, options, correct = random.choice(LOGIC)

        context.user_data["game"]["correct"] = correct

        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔹 {opt}",
                    callback_data=f"answer:{correct}:{i}"
                )
            ]
            for i, opt in enumerate(options)
        ]

        await update.effective_message.reply_text(
            f"🧩 <b>{question}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if game_type == "knowledge":
        question, options, correct = random.choice(KNOWLEDGE)

        context.user_data["game"]["correct"] = correct

        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔹 {opt}",
                    callback_data=f"answer:{correct}:{i}"
                )
            ]
            for i, opt in enumerate(options)
        ]

        await update.effective_message.reply_text(
            f"📚 <b>{question}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if game_type == "word":
        question, options, correct = random.choice(WORDS)

        context.user_data["game"]["correct"] = correct

        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔹 {opt}",
                    callback_data=f"answer:{correct}:{i}"
                )
            ]
            for i, opt in enumerate(options)
        ]

        await update.effective_message.reply_text(
            f"🔤 <b>{question}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if game_type == "color":
        symbol, options, correct = random.choice(COLORS)

        context.user_data["game"]["correct"] = correct

        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔹 {opt}",
                    callback_data=f"answer:{correct}:{i}"
                )
            ]
            for i, opt in enumerate(options)
        ]

        await update.effective_message.reply_text(
            f"🎨 <b>Bu rangni toping:</b> {symbol}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if game_type == "number":
        number = random.randint(1, 10)

        context.user_data["game"]["number"] = number

        buttons = []

        nums = list(range(1, 11))
        random.shuffle(nums)

        for i in range(0, 10, 5):
            buttons.append([
                InlineKeyboardButton(
                    str(n),
                    callback_data=f"num:{number}:{n}"
                )
                for n in nums[i:i + 5]
            ])

        await update.effective_message.reply_text(
            "🔢 <b>1 dan 10 gacha son o‘yladim.</b>\n\n"
            "Toping:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if game_type == "choice":
        correct = random.randint(0, 2)

        context.user_data["game"]["correct"] = correct

        keyboard = [
            [
                InlineKeyboardButton(
                    f"🎁 {i + 1}",
                    callback_data=f"answer:{correct}:{i}"
                )
                for i in range(3)
            ]
        ]

        await update.effective_message.reply_text(
            "⚡ <b>To‘g‘ri variantni tanlang!</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if game_type == "math":
        a = random.randint(2, 20)
        b = random.randint(2, 20)

        op = random.choice(["+", "-", "×"])

        if op == "+":
            answer = a + b
        elif op == "-":
            answer = a - b
        else:
            answer = a * b

        context.user_data["game"]["answer"] = answer

        await update.effective_message.reply_text(
            f"🧮 <b>{a} {op} {b} = ?</b>\n\n"
            "Javobni raqam bilan yozing.",
            parse_mode="HTML",
        )
        return

    if game_type == "attention":
        sequence = "".join(
            random.choice("123456789")
            for _ in range(4)
        )

        context.user_data["game"]["answer"] = sequence

        await update.effective_message.reply_text(
            f"👀 <b>Diqqat!</b>\n\n"
            f"Raqamni eslab qoling: <code>{sequence}</code>\n\n"
            "Endi aynan shu raqamni yozing.",
            parse_mode="HTML",
        )
        return

    if game_type == "code":
        code = "".join(
            random.choice("123456789")
            for _ in range(4)
        )

        context.user_data["game"]["answer"] = code

        await update.effective_message.reply_text(
            "🔐 <b>4 xonali kodni toping!</b>\n\n"
            f"Maslahat: kod raqamlar yig‘indisi "
            f"<b>{sum(map(int, code))}</b>.\n\n"
            "Variantlar ichidan toping:",
            parse_mode="HTML",
        )

        variants = [code]

        while len(variants) < 3:
            candidate = "".join(
                random.choice("123456789")
                for _ in range(4)
            )

            if candidate not in variants:
                variants.append(candidate)

        random.shuffle(variants)

        keyboard = []

        for v in variants:
            keyboard.append([
                InlineKeyboardButton(
                    v,
                    callback_data=f"code:{code}:{v}"
                )
            ])

        await update.effective_message.reply_text(
            "🔐 Kodni tanlang:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if game_type == "speed":
        correct = random.randint(0, 1)

        context.user_data["game"]["correct"] = correct

        keyboard = [[
            InlineKeyboardButton(
                "🟢 BOS",
                callback_data=f"answer:{correct}:0"
            ),
            InlineKeyboardButton(
                "🔴 TO‘XTA",
                callback_data=f"answer:{correct}:1"
            ),
        ]]

        await update.effective_message.reply_text(
            "⏱ <b>Tezlik!</b>\n\n"
            "To‘g‘ri tugmani tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return


async def answer_game(update, context):
    q = update.callback_query
    await q.answer()

    data = q.data.split(":")

    if len(data) != 3:
        return

    try:
        correct = int(data[1])
        selected = int(data[2])
    except Exception:
        return

    game = context.user_data.get("game")

    if not game:
        await q.message.reply_text(
            "❌ O‘yin muddati tugagan."
        )
        return

    if selected == correct:
        add_game_result(q.from_user.id, True)

        await q.message.reply_text(
            "🎉 <b>TO‘G‘RI!</b>\n\n"
            f"⭐ +{GAME_REWARD:.2f} Stars",
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )
    else:
        add_game_result(q.from_user.id, False)

        await q.message.reply_text(
            "❌ <b>NOTO‘G‘RI!</b>\n\n"
            "Keyingi safar omad! 🍀",
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )

    context.user_data.pop("game", None)


async def number_answer(update, context):
    q = update.callback_query
    await q.answer()

    data = q.data.split(":")

    if len(data) != 3:
        return

    try:
        correct = int(data[1])
        selected = int(data[2])
    except Exception:
        return

    if selected == correct:
        add_game_result(q.from_user.id, True)

        text = (
            "🎉 <b>TOPDINGIZ!</b>\n\n"
            f"⭐ +{GAME_REWARD:.2f} Stars"
        )
    else:
        add_game_result(q.from_user.id, False)

        text = (
            "❌ <b>TOPA OLMADINGIZ</b>\n\n"
            f"Men o‘ylagan son: <b>{correct}</b>"
        )

    context.user_data.pop("game", None)

    await q.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def code_answer(update, context):
    q = update.callback_query
    await q.answer()

    data = q.data.split(":", 2)

    if len(data) != 3:
        return

    correct = data[1]
    selected = data[2]

    if selected == correct:
        add_game_result(q.from_user.id, True)

        text = (
            "🎉 <b>KOD TO‘G‘RI!</b>\n\n"
            f"⭐ +{GAME_REWARD:.2f} Stars"
        )
    else:
        add_game_result(q.from_user.id, False)

        text = (
            "❌ <b>NOTO‘G‘RI!</b>\n\n"
            f"To‘g‘ri kod: <code>{correct}</code>"
        )

    context.user_data.pop("game", None)

    await q.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


# =========================================================
# TEXT GAME ANSWERS
# =========================================================

async def handle_game_text(update, context):
    game = context.user_data.get("game")

    if not game:
        return False

    user_id = update.effective_user.id
    text = (update.effective_message.text or "").strip()

    game_type = game.get("type")

    if game_type == "math":
        try:
            answer = int(text)
        except Exception:
            await update.effective_message.reply_text(
                "🧮 Faqat raqam yozing."
            )
            return True

        correct = int(game["answer"])

        if answer == correct:
            add_game_result(user_id, True)

            result = (
                "🎉 <b>TO‘G‘RI!</b>\n\n"
                f"⭐ +{GAME_REWARD:.2f} Stars"
            )
        else:
            add_game_result(user_id, False)

            result = (
                "❌ <b>NOTO‘G‘RI!</b>\n\n"
                f"To‘g‘ri javob: <b>{correct}</b>"
            )

        context.user_data.pop("game", None)

        await update.effective_message.reply_text(
            result,
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )

        return True

    if game_type == "attention":
        correct = str(game["answer"])

        if text == correct:
            add_game_result(user_id, True)

            result = (
                "🎉 <b>DIQQATINGIZ ZO‘R!</b>\n\n"
                f"⭐ +{GAME_REWARD:.2f} Stars"
            )
        else:
            add_game_result(user_id, False)

            result = (
                "❌ <b>NOTO‘G‘RI!</b>\n\n"
                f"To‘g‘ri: <code>{correct}</code>"
            )

        context.user_data.pop("game", None)

        await update.effective_message.reply_text(
            result,
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )

        return True

    return False


# =========================================================
# WITHDRAW
# =========================================================

async def withdraw_menu(update, context):
    user = get_user(update.effective_user.id)

    points = float(user["points"]) if user else 0
    refs = int(user["referrals"]) if user else 0

    text = (
        "💸 <b>YECHIB OLISH</b>\n\n"
        f"⭐ Balans: <b>{points:.2f}</b>\n"
        f"👥 Referallar: <b>{refs}</b>\n\n"
        f"📌 Minimum: <b>{MIN_WITHDRAW:.0f} ⭐</b>\n"
        f"📌 Kerakli referal: <b>{MIN_REFERRALS}</b>\n\n"
        "Yechib olish uchun summani yozing."
    )

    context.user_data["action"] = "withdraw_amount"

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def process_withdraw_amount(update, context):
    user_id = update.effective_user.id

    try:
        amount = float(
            (update.effective_message.text or "").replace(",", ".")
        )
    except Exception:
        await update.effective_message.reply_text(
            "❌ Summani raqam bilan yozing. Masalan: <b>200</b>",
            parse_mode="HTML",
        )
        return

    if amount < MIN_WITHDRAW:
        await update.effective_message.reply_text(
            f"❌ Minimum <b>{MIN_WITHDRAW:.0f} Stars</b>.",
            parse_mode="HTML",
        )
        return

    result, reason = create_withdrawal(
        user_id,
        amount,
    )

    if reason != "ok":
        messages = {
            "balance": "❌ Balansingiz yetarli emas.",
            "referrals": (
                f"❌ Kamida {MIN_REFERRALS} ta referal kerak."
            ),
            "pending": (
                "⏳ Sizda allaqachon kutayotgan yechib olish so‘rovi bor."
            ),
            "user": "❌ Foydalanuvchi topilmadi.",
        }

        await update.effective_message.reply_text(
            messages.get(reason, "❌ Xatolik."),
            reply_markup=back_keyboard(),
        )

        context.user_data.pop("action", None)
        return

    withdrawal_id = result

    await update.effective_message.reply_text(
        "✅ <b>So‘rov yuborildi!</b>\n\n"
        f"⭐ Summa: <b>{amount:.2f}</b>\n"
        f"🆔 So‘rov: <code>#{withdrawal_id}</code>\n\n"
        "Admin tekshirganidan keyin tasdiqlanadi.",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )

    context.user_data.pop("action", None)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ TASDIQLASH",
                callback_data=f"approve:{withdrawal_id}"
            ),
            InlineKeyboardButton(
                "❌ RAD ETISH",
                callback_data=f"reject:{withdrawal_id}"
            ),
        ]
    ])

    try:
        await context.bot.send_message(
            ADMIN_ID,
            (
                "💸 <b>YANGI YECHIB OLISH SO‘ROVI</b>\n\n"
                f"🆔 So‘rov: <code>#{withdrawal_id}</code>\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"⭐ Summa: <b>{amount:.2f}</b>"
            ),
            parse_mode="HTML",
            reply_markup=buttons,
        )
    except Exception as e:
        logger.error("Admin withdraw yuborishda xato: %s", e)


# =========================================================
# RATING
# =========================================================

async def show_rating(update, context):
    rows = get_rating(10)

    if not rows:
        await update.effective_message.reply_text(
            "🏆 Reyting hozircha bo‘sh.",
            reply_markup=back_keyboard(),
        )
        return

    lines = [
        "🏆 <b>TOP 10 REYTING</b>\n"
    ]

    for i, row in enumerate(rows, 1):
        username = (
            f"@{row['username']}"
            if row["username"]
            else f"ID {row['id']}"
        )

        lines.append(
            f"{i}. {username} — "
            f"<b>{float(row['points']):.2f} ⭐</b>"
        )

    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


# =========================================================
# ADMIN PANEL
# =========================================================

def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 STATISTIKA",
                callback_data="admin_stats"
            ),
            InlineKeyboardButton(
                "👥 USERLAR",
                callback_data="admin_users"
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 XABAR YUBORISH",
                callback_data="admin_broadcast"
            ),
        ],
        [
            InlineKeyboardButton(
                "➕ HOMIY QO‘SHISH",
                callback_data="admin_add_sponsor"
            ),
            InlineKeyboardButton(
                "🗑 HOMIY O‘CHIRISH",
                callback_data="admin_del_sponsor"
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 HOMIYLAR",
                callback_data="admin_sponsors"
            ),
        ],
        [
            InlineKeyboardButton(
                "➕ TOPSHIRIQ",
                callback_data="admin_add_task"
            ),
            InlineKeyboardButton(
                "📋 TOPSHIRIQLAR",
                callback_data="admin_tasks"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔒/🔓 OBUNA",
                callback_data="admin_sub_toggle"
            ),
        ],
        [
            InlineKeyboardButton(
                "💸 YECHISHLAR",
                callback_data="admin_withdrawals"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 BOSH MENYU",
                callback_data="home"
            ),
        ],
    ])


async def admin_panel(update, context):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    sponsors = get_sponsors()

    status = (
        "🟢 YOQILGAN"
        if sponsor_active()
        else "🔴 O‘CHIRILGAN"
    )

    await update.effective_message.reply_text(
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        f"👥 Userlar: <b>{get_total_users()}</b>\n"
        f"📢 Homiylar: <b>{len(sponsors)}</b>\n"
        f"🔒 Obuna tizimi: <b>{status}</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def admin_stats(update, context):
    if not is_admin(update.effective_user.id):
        return

    conn = db_connect()

    row = conn.execute("""
        SELECT
            COUNT(*) AS users,
            COALESCE(SUM(points), 0) AS points,
            COALESCE(SUM(referrals), 0) AS refs,
            COALESCE(SUM(games), 0) AS games,
            COALESCE(SUM(wins), 0) AS wins
        FROM users
    """).fetchone()

    pending = conn.execute("""
        SELECT COUNT(*) AS c
        FROM withdrawals
        WHERE status='pending'
    """).fetchone()["c"]

    conn.close()

    await update.effective_message.reply_text(
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Jami userlar: <b>{get_total_users()}</b>\n"
        f"🟢 Aktiv (7 kun): <b>{get_active_users()}</b>\n"
        f"⭐ Jami Stars: <b>{float(row['points']):.2f}</b>\n"
        f"👥 Jami referallar: <b>{row['refs']}</b>\n"
        f"🎮 O‘yinlar: <b>{row['games']}</b>\n"
        f"🏆 G‘alabalar: <b>{row['wins']}</b>\n"
        f"💸 Kutilayotgan yechish: <b>{pending}</b>\n"
        f"📢 Homiylar: <b>{len(get_sponsors())}</b>",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def admin_users(update, context):
    if not is_admin(update.effective_user.id):
        return

    conn = db_connect()

    rows = conn.execute("""
        SELECT id, username, points
        FROM users
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    if not rows:
        text = "👥 Userlar yo‘q."
    else:
        lines = ["👥 <b>OXIRGI USERLAR</b>\n"]

        for row in rows:
            username = (
                f"@{row['username']}"
                if row["username"]
                else "username yo‘q"
            )

            lines.append(
                f"• <code>{row['id']}</code> "
                f"{username} — "
                f"{float(row['points']):.2f}⭐"
            )

        text = "\n".join(lines)

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


# =========================================================
# ADMIN SPONSORS
# =========================================================

async def admin_sponsors(update, context):
    if not is_admin(update.effective_user.id):
        return

    sponsors = get_sponsors()

    if not sponsors:
        text = (
            "📢 <b>HOMIYLAR</b>\n\n"
            "Hozircha homiy kanal qo‘shilmagan."
        )
    else:
        lines = [
            "📢 <b>HOMIY KANALLAR</b>\n"
        ]

        for i, sponsor in enumerate(sponsors, 1):
            lines.append(
                f"{i}. {sponsor['channel']}\n"
                f"🔗 {sponsor['url']}"
            )

        text = "\n\n".join(lines)

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def admin_add_sponsor_start(update, context):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["action"] = "add_sponsor"

    await update.effective_message.reply_text(
        "➕ <b>HOMIY KANAL QO‘SHISH</b>\n\n"
        "Shu formatda yuboring:\n\n"
        "<code>@kanal | https://t.me/kanal</code>\n\n"
        "Masalan:\n"
        "<code>@example | https://t.me/example</code>\n\n"
        "URL yozmasangiz ham bo‘ladi.",
        parse_mode="HTML",
    )


async def admin_add_sponsor_process(update, context):
    if not is_admin(update.effective_user.id):
        return

    text = (update.effective_message.text or "").strip()

    if "|" in text:
        channel, url = text.split("|", 1)
    else:
        channel = text
        url = normalize_url(channel)

    channel = normalize_channel(channel)
    url = url.strip()

    if not channel:
        await update.effective_message.reply_text(
            "❌ Kanal nomi noto‘g‘ri."
        )
        return

    if not url.startswith("http"):
        url = normalize_url(channel)

    add_sponsor_sync(
        channel,
        url,
    )

    context.user_data.pop("action", None)

    await update.effective_message.reply_text(
        "✅ <b>Homiy kanal qo‘shildi!</b>\n\n"
        f"📢 {channel}\n"
        f"🔗 {url}\n\n"
        f"🎁 Avtomatik topshiriq: +{TASK_REWARD:.0f}⭐",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def admin_del_sponsor_start(update, context):
    if not is_admin(update.effective_user.id):
        return

    sponsors = get_sponsors()

    if not sponsors:
        await update.effective_message.reply_text(
            "📢 O‘chirish uchun homiy yo‘q.",
            reply_markup=admin_keyboard(),
        )
        return

    buttons = []

    for sponsor in sponsors:
        buttons.append([
            InlineKeyboardButton(
                f"🗑 {sponsor['channel']}",
                callback_data=(
                    "delsp:" +
                    sponsor["channel"].lstrip("@")
                )
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 ADMIN",
            callback_data="admin"
        )
    ])

    await update.effective_message.reply_text(
        "🗑 <b>Qaysi homiyni o‘chiramiz?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_delete_sponsor(update, context):
    q = update.callback_query

    if not is_admin(q.from_user.id):
        await q.answer("Ruxsat yo‘q", show_alert=True)
        return

    await q.answer()

    channel = "@" + q.data.split(":", 1)[1]

    remove_sponsor_sync(channel)

    await q.message.reply_text(
        f"✅ <b>{channel}</b> o‘chirildi.\n\n"
        "Unga bog‘langan homiy topshirig‘i ham o‘chirildi.",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ADMIN TASKS
# =========================================================

async def admin_add_task_start(update, context):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["action"] = "add_task"

    await update.effective_message.reply_text(
        "➕ <b>TOPSHIRIQ QO‘SHISH</b>\n\n"
        "Format:\n\n"
        "<code>Matn | reward | url</code>\n\n"
        "Masalan:\n"
        "<code>📢 Kanalga kiring | 5 | https://t.me/example</code>",
        parse_mode="HTML",
    )


async def admin_add_task_process(update, context):
    if not is_admin(update.effective_user.id):
        return

    text = (update.effective_message.text or "").strip()

    parts = [x.strip() for x in text.split("|")]

    if len(parts) < 3:
        await update.effective_message.reply_text(
            "❌ Format noto‘g‘ri.\n\n"
            "<code>Matn | reward | url</code>",
            parse_mode="HTML",
        )
        return

    task_text = parts[0]

    try:
        reward = float(parts[1])
    except Exception:
        await update.effective_message.reply_text(
            "❌ Reward raqam bo‘lishi kerak."
        )
        return

    url = parts[2]

    task_id = add_custom_task(
        task_text,
        reward,
        url,
        None,
    )

    context.user_data.pop("action", None)

    await update.effective_message.reply_text(
        "✅ <b>Topshiriq qo‘shildi!</b>\n\n"
        f"🆔 ID: <code>{task_id}</code>\n"
        f"🎁 Reward: <b>{reward:g}⭐</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def admin_tasks(update, context):
    if not is_admin(update.effective_user.id):
        return

    tasks = get_tasks()

    if not tasks:
        await update.effective_message.reply_text(
            "📋 Topshiriqlar yo‘q.",
            reply_markup=admin_keyboard(),
        )
        return

    buttons = []

    for task in tasks:
        buttons.append([
            InlineKeyboardButton(
                f"🗑 #{task['id']} {task['text'][:35]}",
                callback_data=f"deltask:{task['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 ADMIN",
            callback_data="admin"
        )
    ])

    await update.effective_message.reply_text(
        "📋 <b>TOPSHIRIQLAR</b>\n\n"
        "O‘chirish uchun topshiriqni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_delete_task(update, context):
    q = update.callback_query

    if not is_admin(q.from_user.id):
        await q.answer("Ruxsat yo‘q", show_alert=True)
        return

    await q.answer()

    try:
        task_id = int(q.data.split(":")[1])
    except Exception:
        return

    delete_task(task_id)

    await q.message.reply_text(
        f"✅ #{task_id} topshiriq o‘chirildi.",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ADMIN SUBSCRIPTION
# =========================================================

async def admin_toggle_sub(update, context):
    if not is_admin(update.effective_user.id):
        return

    current = sponsor_active()

    set_sponsor_active(not current)

    status = (
        "🟢 YOQILDI"
        if not current
        else "🔴 O‘CHIRILDI"
    )

    await update.effective_message.reply_text(
        f"🔒 <b>Homiy obuna tizimi {status}</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ADMIN WITHDRAWALS
# =========================================================

async def admin_withdrawals(update, context):
    if not is_admin(update.effective_user.id):
        return

    rows = get_pending_withdrawals()

    if not rows:
        await update.effective_message.reply_text(
            "💸 Kutilayotgan yechish so‘rovlari yo‘q.",
            reply_markup=admin_keyboard(),
        )
        return

    for row in rows:
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ TASDIQLASH",
                    callback_data=f"approve:{row['id']}"
                ),
                InlineKeyboardButton(
                    "❌ RAD ETISH",
                    callback_data=f"reject:{row['id']}"
                ),
            ]
        ])

        await update.effective_message.reply_text(
            "💸 <b>YECHISH SO‘ROVI</b>\n\n"
            f"🆔 #{row['id']}\n"
            f"👤 User: <code>{row['user_id']}</code>\n"
            f"⭐ Summa: <b>{float(row['amount']):.2f}</b>",
            parse_mode="HTML",
            reply_markup=buttons,
        )


async def approve_withdrawal(update, context):
    q = update.callback_query

    if not is_admin(q.from_user.id):
        await q.answer(
            "Ruxsat yo‘q",
            show_alert=True,
        )
        return

    await q.answer()

    try:
        withdrawal_id = int(q.data.split(":")[1])
    except Exception:
        return

    ok, row = approve_withdrawal_sync(
        withdrawal_id
    )

    if not ok or row is None:
        await q.message.reply_text(
            "❌ So‘rov topilmadi yoki allaqachon ko‘rib chiqilgan."
        )
        return

    try:
        await context.bot.send_message(
            row["user_id"],
            (
                "✅ <b>Yechib olish so‘rovingiz tasdiqlandi!</b>\n\n"
                f"⭐ Summa: <b>{float(row['amount']):.2f}</b>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await q.message.reply_text(
        f"✅ #{withdrawal_id} tasdiqlandi."
    )


async def reject_withdrawal(update, context):
    q = update.callback_query

    if not is_admin(q.from_user.id):
        await q.answer(
            "Ruxsat yo‘q",
            show_alert=True,
        )
        return

    await q.answer()

    try:
        withdrawal_id = int(q.data.split(":")[1])
    except Exception:
        return

    ok, row = reject_withdrawal_sync(
        withdrawal_id
    )

    if not ok or row is None:
        await q.message.reply_text(
            "❌ So‘rov topilmadi yoki allaqachon ko‘rib chiqilgan."
        )
        return

    try:
        await context.bot.send_message(
            row["user_id"],
            (
                "❌ <b>Yechib olish so‘rovingiz rad etildi.</b>\n\n"
                f"⭐ <b>{float(row['amount']):.2f}</b> Stars "
                "balansingizga qaytarildi."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await q.message.reply_text(
        f"❌ #{withdrawal_id} rad etildi.\n"
        f"⭐ Stars user balansiga qaytarildi."
    )


# =========================================================
# BROADCAST
# =========================================================

async def admin_broadcast_start(update, context):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["action"] = "broadcast"

    await update.effective_message.reply_text(
        "📢 <b>UMUMIY XABAR</b>\n\n"
        "Endi yuboriladigan xabarni jo‘nating.\n\n"
        "Matn, rasm, video, sticker yoki boshqa xabar yuborishingiz mumkin.",
        parse_mode="HTML",
    )


async def do_broadcast(update, context):
    if not is_admin(update.effective_user.id):
        return

    message = update.effective_message

    conn = db_connect()

    users = conn.execute("""
        SELECT id
        FROM users
        WHERE blocked=0
    """).fetchall()

    conn.close()

    sent = 0
    failed = 0

    for row in users:
        uid = row["id"]

        try:
            await message.copy(
                chat_id=uid
            )

            sent += 1

            await asyncio.sleep(0.04)

        except RetryAfter as e:
            await asyncio.sleep(
                float(e.retry_after) + 1
            )

            try:
                await message.copy(
                    chat_id=uid
                )
                sent += 1
            except Exception:
                failed += 1

        except Forbidden:
            conn = db_connect()

            conn.execute("""
                UPDATE users
                SET blocked=1
                WHERE id=?
            """, (uid,))

            conn.commit()
            conn.close()

            failed += 1

        except Exception:
            failed += 1

    context.user_data.pop("action", None)

    await update.effective_message.reply_text(
        "📢 <b>XABAR YUBORILDI</b>\n\n"
        f"✅ Yuborildi: <b>{sent}</b>\n"
        f"❌ Xato: <b>{failed}</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# CALLBACK ROUTER
# =========================================================

async def callback_router(update, context):
    q = update.callback_query

    data = q.data

    user_id = q.from_user.id

    touch_user_sync(
        user_id,
        q.from_user.username,
    )

    # HOME
    if data == "home":
        await q.answer()

        if not await check_sponsor_membership(
            context.bot,
            user_id,
        ):
            await require_subscription(
                update,
                context,
            )
            return

        await q.message.reply_text(
            "🎮 <b>ZERIKDIM GAMES</b>\n\n"
            "👇 Bo‘limni tanlang:",
            parse_mode="HTML",
            reply_markup=main_keyboard(user_id),
        )
        return

    # Subscription check
    if data == "check_sub":
        await q.answer()

        if await check_sponsor_membership(
            context.bot,
            user_id,
        ):
            await q.message.reply_text(
                "✅ <b>Obuna tasdiqlandi!</b>\n\n"
                "Botdan foydalanishingiz mumkin.",
                parse_mode="HTML",
                reply_markup=main_keyboard(user_id),
            )
        else:
            await q.message.reply_text(
                "❌ Hali barcha homiy kanallarga obuna bo‘lmagansiz.",
                reply_markup=back_keyboard(),
            )

        return

    # Basic
    if data == "stars_get":
        await q.answer()

        if await require_subscription(update, context):
            await show_stars_get(update, context)

        return

    if data == "balance":
        await q.answer()

        if await require_subscription(update, context):
            await show_balance(update, context)

        return

    if data == "profile":
        await q.answer()

        if await require_subscription(update, context):
            await show_profile(update, context)

        return

    if data == "referral":
        await q.answer()

        if await require_subscription(update, context):
            await show_referral(update, context)

        return

    if data == "rating":
        await q.answer()

        if await require_subscription(update, context):
            await show_rating(update, context)

        return

    if data == "tasks":
        await q.answer()

        if await require_subscription(update, context):
            await show_tasks(update, context)

        return

    if data == "games":
        await q.answer()

        if await require_subscription(update, context):
            await games_menu(update, context)

        return

    if data == "withdraw":
        await q.answer()

        if await require_subscription(update, context):
            await withdraw_menu(update, context)

        return

    # Games
    if data.startswith("game:"):
        await q.answer()

        game_type = data.split(":", 1)[1]

        if await require_subscription(update, context):
            await start_game(
                update,
                context,
                game_type,
            )

        return

    if data.startswith("answer:"):
        await answer_game(update, context)
        return

    if data.startswith("num:"):
        await number_answer(update, context)
        return

    if data.startswith("code:"):
        await code_answer(update, context)
        return

    # Task
    if data.startswith("task:"):
        await task_click(update, context)
        return

    # Admin
    if data == "admin":
        await q.answer()

        if is_admin(user_id):
            await admin_panel(update, context)

        return

    if data == "admin_stats":
        await q.answer()

        if is_admin(user_id):
            await admin_stats(update, context)

        return

    if data == "admin_users":
        await q.answer()

        if is_admin(user_id):
            await admin_users(update, context)

        return

    if data == "admin_broadcast":
        await q.answer()

        if is_admin(user_id):
            await admin_broadcast_start(
                update,
                context,
            )

        return

    if data == "admin_add_sponsor":
        await q.answer()

        if is_admin(user_id):
            await admin_add_sponsor_start(
                update,
                context,
            )

        return

    if data == "admin_del_sponsor":
        await q.answer()

        if is_admin(user_id):
            await admin_del_sponsor_start(
                update,
                context,
            )

        return

    if data == "admin_sponsors":
        await q.answer()

        if is_admin(user_id):
            await admin_sponsors(
                update,
                context,
            )

        return

    if data == "admin_add_task":
        await q.answer()

        if is_admin(user_id):
            await admin_add_task_start(
                update,
                context,
            )

        return

    if data == "admin_tasks":
        await q.answer()

        if is_admin(user_id):
            await admin_tasks(
                update,
                context,
            )

        return

    if data == "admin_sub_toggle":
        await q.answer()

        if is_admin(user_id):
            await admin_toggle_sub(
                update,
                context,
            )

        return

    if data == "admin_withdrawals":
        await q.answer()

        if is_admin(user_id):
            await admin_withdrawals(
                update,
                context,
            )

        return

    if data.startswith("delsp:"):
        await admin_delete_sponsor(
            update,
            context,
        )
        return

    if data.startswith("deltask:"):
        await admin_delete_task(
            update,
            context,
        )
        return

    if data.startswith("approve:"):
        await approve_withdrawal(
            update,
            context,
        )
        return

    if data.startswith("reject:"):
        await reject_withdrawal(
            update,
            context,
        )
        return

    await q.answer()


# =========================================================
# TEXT ROUTER
# =========================================================

async def text_router(update, context):
    if not update.effective_user:
        return

    user = update.effective_user

    add_user_sync(
        user.id,
        user.username,
    )

    text = (
        update.effective_message.text or ""
    ).strip()

    # ADMIN BROADCAST
    if (
        is_admin(user.id)
        and context.user_data.get("action") == "broadcast"
    ):
        await do_broadcast(
            update,
            context,
        )
        return

    # Admin sponsor
    if (
        is_admin(user.id)
        and context.user_data.get("action") == "add_sponsor"
    ):
        await admin_add_sponsor_process(
            update,
            context,
        )
        return

    # Admin task
    if (
        is_admin(user.id)
        and context.user_data.get("action") == "add_task"
    ):
        await admin_add_task_process(
            update,
            context,
        )
        return

    # Withdraw
    if context.user_data.get("action") == "withdraw_amount":
        if not await require_subscription(
            update,
            context,
        ):
            return

        await process_withdraw_amount(
            update,
            context,
        )
        return

    # Game text
    if await handle_game_text(
        update,
        context,
    ):
        return

    # Buttons typed as text
    if text == "⭐ STARS OLISH":
        await show_stars_get(update, context)
        return

    if text in (
        "🎯 STARS ISHLASH",
        "🎮 O‘YINLAR",
    ):
        await games_menu(update, context)
        return

    if text == "💰 BALANS":
        await show_balance(update, context)
        return

    if text == "🎁 TOPSHIRIQLAR":
        await show_tasks(update, context)
        return

    if text == "👥 REFERAL":
        await show_referral(update, context)
        return

    if text == "💸 YECHIB OLISH":
        await withdraw_menu(update, context)
        return

    if text == "🏆 REYTING":
        await show_rating(update, context)
        return

    if text == "👤 PROFIL":
        await show_profile(update, context)
        return

    if text == "⚙️ ADMIN PANEL" and is_admin(user.id):
        await admin_panel(update, context)
        return

    await update.effective_message.reply_text(
        "👇 Menyudan kerakli bo‘limni tanlang.",
        reply_markup=main_keyboard(user.id),
    )


# =========================================================
# CANCEL / ID
# =========================================================

async def cancel(update, context):
    context.user_data.clear()

    await update.effective_message.reply_text(
        "❌ Bekor qilindi.",
        reply_markup=main_keyboard(
            update.effective_user.id
        ),
    )


async def get_id(update, context):
    await update.effective_message.reply_text(
        f"🆔 Sizning Telegram ID: <code>{update.effective_user.id}</code>",
        parse_mode="HTML",
    )


# =========================================================
# BACKUP
# =========================================================

def git_backup():
    try:
        if not os.path.exists(DB):
            return

        subprocess.run(
            ["git", "config", "user.name", "zerikdim-bot"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        subprocess.run(
            ["git", "config", "user.email", "zerikdim-bot@users.noreply.github.com"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        subprocess.run(
            ["git", "add", "-f", DB],
            capture_output=True,
            text=True,
            timeout=30,
        )

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if not status.stdout.strip():
            return

        subprocess.run(
            ["git", "commit", "-m", "Save Zerikdim database"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        branch = os.getenv(
            "GITHUB_REF_NAME",
            "main",
        )

        # Remote yangiliklarini olish
        subprocess.run(
            ["git", "fetch", "origin", branch],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Rebase qilish
        rebase = subprocess.run(
            ["git", "rebase", f"origin/{branch}"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if rebase.returncode != 0:
            subprocess.run(
                ["git", "rebase", "--abort"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            logger.warning(
                "DB backup rebase muvaffaqiyatsiz: %s",
                rebase.stderr,
            )

            return

        push = subprocess.run(
            [
                "git",
                "push",
                "origin",
                f"HEAD:{branch}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if push.returncode == 0:
            logger.info(
                "SQLite database GitHub ga saqlandi."
            )
        else:
            logger.warning(
                "DB push xatosi: %s",
                push.stderr,
            )

    except Exception as e:
        logger.warning(
            "Git backup xatosi: %s",
            e,
        )


async def backup_loop():
    while True:
        try:
            await asyncio.sleep(BACKUP_INTERVAL)

            await asyncio.to_thread(
                git_backup
            )

        except asyncio.CancelledError:
            break

        except Exception as e:
            logger.warning(
                "Backup loop xatosi: %s",
                e,
            )


async def sponsor_loop(application):
    while True:
        try:
            await asyncio.sleep(900)

            await sponsor_limit_check(
                application.bot
            )

        except asyncio.CancelledError:
            break

        except Exception as e:
            logger.warning(
                "Sponsor loop xatosi: %s",
                e,
            )


# =========================================================
# STARTUP / SHUTDOWN
# =========================================================

async def post_init(application):
    init_db()

    application.create_task(
        backup_loop()
    )

    application.create_task(
        sponsor_loop(application)
    )

    logger.info(
        "Zerikdim Games ishga tushdi."
    )


async def post_shutdown(application):
    try:
        await asyncio.to_thread(
            git_backup
        )
    except Exception as e:
        logger.warning(
            "Shutdown backup xatosi: %s",
            e,
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    logger.error(
        "Unhandled exception: %s",
        context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN GitHub Secrets ichida topilmadi!"
        )

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel,
        )
    )

    application.add_handler(
        CommandHandler(
            "id",
            get_id,
        )
    )

    # Callbacks
    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # Har qanday oddiy xabar
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            text_router,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Polling boshlandi..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
