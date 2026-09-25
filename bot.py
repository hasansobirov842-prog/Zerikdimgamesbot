import os
import sqlite3
import logging
import asyncio
from datetime import datetime, timezone, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError, Forbidden, RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "8679536810"))
except Exception:
    ADMIN_ID = 8679536810

DB_FILE = "zerikdim.db"

PAYMENT_CARD = "5614681008971867"
PAYMENT_OWNER = "RAKHMONOVA/O"

DEFAULT_SPONSOR_CHANNEL = "@premyumstarstekin"
DEFAULT_SPONSOR_URL = "https://t.me/premyumstarstekin"
DEFAULT_SPONSOR_LIMIT = 10000

REFERRAL_STARS = 5.0
REFERRAL_BONUS = 1200.0
MIN_WITHDRAW = 10000
MIN_TOPUP = 2500

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =========================================================
# NOMERLAR
# =========================================================

NUMBERS = {
    "🇧🇩 Bangladesh": 5800,
    "🇺🇸 USA": 7000,
    "🇮🇳 India": 6000,
    "🇮🇩 Indonesia": 6000,
    "🇳🇬 Nigeria": 6000,
    "🇪🇹 Ethiopia": 6000,
    "🇷🇺 rusiya": 24000,
    "🇺🇿 Uzbekistan": 13000,
}

# =========================================================
# NAKRUTKA
# =========================================================

NAKRUTKA = {
    "Telegram": {
        "1K": 5000,
        "10K": 40000,
        "100K": 100000,
    },
    "TikTok": {
        "1K": 25000,
        "10K": 250000,
        "100K": 2500000,
    },
    "YouTube": {
        "1K": 25000,
        "10K": 250000,
        "100K": 2500000,
    },
    "Instagram": {
        "1K": 25000,
        "10K": 250000,
        "100K": 2500000,
    },
}

# =========================================================
# STARS
# =========================================================

STARS_PRICES = {
    50: 10999,
    100: 22500,
    200: 44000,
    500: 99500,
    1000: 199000,
}

# =========================================================
# PREMIUM
# =========================================================

PREMIUM_PRICES = {
    1: 45000,
    3: 120000,
    6: 200000,
    12: 299000,
}

# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def ensure_column(conn, table, column, definition):
    columns = [
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    ]

    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )

def init_db():
    conn = db()

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

    ensure_column(conn, "users", "money_balance", "REAL DEFAULT 0")
    ensure_column(conn, "users", "premium_1m", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "premium_3m", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "real_balance", "REAL DEFAULT 0")
    ensure_column(conn, "users", "bonus_balance", "REAL DEFAULT 0")
    ensure_column(conn, "users", "total_deposited", "REAL DEFAULT 0")
    ensure_column(conn, "users", "total_spent", "REAL DEFAULT 0")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
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
            PRIMARY KEY(user_id, task_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_stats (
            id INTEGER PRIMARY KEY,
            started_at TEXT,
            total_users INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sponsor_settings (
            id INTEGER PRIMARY KEY,
            active INTEGER DEFAULT 1,
            disabled_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            channel TEXT PRIMARY KEY,
            url TEXT,
            limit_users INTEGER DEFAULT 380,
            joined_users INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    ensure_column(
        conn,
        "sponsors",
        "limit_users",
        "INTEGER DEFAULT 380"
    )
    ensure_column(
        conn,
        "sponsors",
        "joined_users",
        "INTEGER DEFAULT 0"
    )
    ensure_column(
        conn,
        "sponsors",
        "active",
        "INTEGER DEFAULT 1"
    )
    ensure_column(
        conn,
        "sponsors",
        "created_at",
        "TEXT"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS payment_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL DEFAULT 0,
            receipt_file_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS service_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            item TEXT,
            price REAL DEFAULT 0,
            target TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        )
    """)

    ensure_column(
        conn,
        "service_orders",
        "link",
        "TEXT DEFAULT ''"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS money_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        )
    """)

    if conn.execute(
        "SELECT 1 FROM bot_stats WHERE id=1"
    ).fetchone() is None:
        conn.execute("""
            INSERT INTO bot_stats
            (id, started_at, total_users)
            VALUES (1, ?, 0)
        """, (now_iso(),))

    real_users = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    stats = conn.execute("""
        SELECT total_users
        FROM bot_stats
        WHERE id=1
    """).fetchone()

    if stats and int(stats["total_users"] or 0) < real_users:
        conn.execute("""
            UPDATE bot_stats
            SET total_users=?
            WHERE id=1
        """, (real_users,))

    conn.execute("""
        INSERT OR IGNORE INTO sponsor_settings
        (id, active, disabled_at)
        VALUES (1, 1, NULL)
    """)

    # Asosiy homiy
    existing = conn.execute("""
        SELECT *
        FROM sponsors
        WHERE channel=?
    """, (DEFAULT_SPONSOR_CHANNEL,)).fetchone()

    if existing is None:
        conn.execute("""
            INSERT INTO sponsors(
                channel,
                url,
                limit_users,
                joined_users,
                active,
                created_at
            )
            VALUES (?, ?, ?, 0, 1, ?)
        """, (
            DEFAULT_SPONSOR_CHANNEL,
            DEFAULT_SPONSOR_URL,
            DEFAULT_SPONSOR_LIMIT,
            now_iso()
        ))

    conn.execute("""
        UPDATE sponsor_settings
        SET active=1,
            disabled_at=NULL
        WHERE id=1
    """)

    conn.commit()
    conn.close()

# =========================================================
# USER
# =========================================================

def add_user(user_id, username):
    conn = db()

    row = conn.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    is_new = row is None

    if is_new:
        conn.execute("""
            INSERT INTO users (
                id, username, points, games, wins,
                referrals, referred_by, last_seen,
                blocked, referral_rewarded,
                money_balance, premium_1m, premium_3m,
                real_balance, bonus_balance,
                total_deposited, total_spent
            )
            VALUES (
                ?, ?, 0, 0, 0,
                0, NULL, ?, 0, 0,
                0, 0, 0, 0, 0, 0, 0
            )
        """, (
            user_id,
            username or "",
            now_iso()
        ))

        conn.execute("""
            UPDATE bot_stats
            SET total_users=total_users+1
            WHERE id=1
        """)

        # Har bir faol homiyga yangi START hisoblanadi
        conn.execute("""
            UPDATE sponsors
            SET joined_users=joined_users+1
            WHERE active=1
        """)

        # Limitga yetgan homiy avtomatik o'chadi
        conn.execute("""
            UPDATE sponsors
            SET active=0
            WHERE active=1
            AND joined_users >= limit_users
        """)

    else:
        conn.execute("""
            UPDATE users
            SET username=?,
                last_seen=?,
                blocked=0
            WHERE id=?
        """, (
            username or "",
            now_iso(),
            user_id
        ))

    conn.commit()

    total = conn.execute("""
        SELECT total_users
        FROM bot_stats
        WHERE id=1
    """).fetchone()["total_users"]

    conn.close()

    return is_new, int(total)

def get_user(user_id):
    conn = db()

    row = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    return row

# =========================================================
# HOMIY
# =========================================================

async def is_subscribed(bot, channel, user_id):
    try:
        member = await bot.get_chat_member(
            channel,
            user_id
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        )

    except TelegramError:
        return False

async def check_sponsor(bot, user_id):
    conn = db()

    sponsors = conn.execute("""
        SELECT *
        FROM sponsors
        WHERE active=1
    """).fetchall()

    conn.close()

    if not sponsors:
        return True

    for sponsor in sponsors:
        if not await is_subscribed(
            bot,
            sponsor["channel"],
            user_id
        ):
            return False

    return True

def sponsor_keyboard():
    conn = db()

    rows = conn.execute("""
        SELECT channel, url
        FROM sponsors
        WHERE active=1
    """).fetchall()

    conn.close()

    buttons = []

    for row in rows:
        buttons.append([
            InlineKeyboardButton(
                f"📢 {row['channel']}",
                url=row["url"]
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✅ TASDIQLASH",
            callback_data="check_sponsor"
        )
    ])

    return InlineKeyboardMarkup(buttons)

async def show_sponsor(update):
    text = (
        "🔒 <b>BOTDAN FOYDALANISH UCHUN</b>\n\n"
        "📢 Avval quyidagi kanal(lar)ga obuna bo‘ling.\n\n"
        "Keyin <b>✅ TASDIQLASH</b> tugmasini bosing."
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=sponsor_keyboard()
        )
    else:
        await update.effective_message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=sponsor_keyboard()
        )

# =========================================================
# MAIN MENU
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["💰 PUL ISHLASH"],
            ["💎 PREMIUM", "⭐ STARS"],
            ["📱 NOMER OLISH", "📈 NAKRUTKA"],
            ["🛍 DO‘KON", "💳 HISOB TO‘LDIRISH"],
            ["👤 MENING HISOBIM", "🤝 HOMIY"],
        ],
        resize_keyboard=True
    )


# =========================================================
# START
# =========================================================

async def start(update, context):
    user = update.effective_user

    is_new, total = add_user(
        user.id,
        user.username
    )

    if is_new and context.args:
        try:
            referrer_id = int(context.args[0])
        except Exception:
            referrer_id = 0

        if (
            referrer_id
            and referrer_id != user.id
            and get_user(referrer_id)
        ):
            conn = db()

            current = conn.execute("""
                SELECT referred_by
                FROM users
                WHERE id=?
            """, (user.id,)).fetchone()

            if current and current["referred_by"] is None:
                conn.execute("""
                    UPDATE users
                    SET referred_by=?
                    WHERE id=?
                """, (
                    referrer_id,
                    user.id
                ))

                conn.execute("""
                    UPDATE users
                    SET referrals=referrals+1,
                        points=points+?
                    WHERE id=?
                """, (
                    REFERRAL_STARS,
                    referrer_id
                ))

                conn.execute("""
                    UPDATE users
                    SET bonus_balance=bonus_balance+?,
                        money_balance=money_balance+?
                    WHERE id=?
                """, (
                    REFERRAL_BONUS,
                    REFERRAL_BONUS,
                    referrer_id
                ))

            conn.commit()
            conn.close()

    conn = db()

    ref_user = conn.execute("""
        SELECT referrals, premium_1m, premium_3m
        FROM users
        WHERE id=?
    """, (user.id,)).fetchone()

    if ref_user:
        refs = int(ref_user["referrals"] or 0)

        if refs >= 70 and not int(ref_user["premium_3m"] or 0):
            conn.execute("""
                UPDATE users
                SET premium_3m=1
                WHERE id=?
            """, (user.id,))

        elif refs >= 25 and not int(ref_user["premium_1m"] or 0):
            conn.execute("""
                UPDATE users
                SET premium_1m=1
                WHERE id=?
            """, (user.id,))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🖥 <b>Asosiy menyudasiz!</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

async def homiy_menu(update, context):
    await update.message.reply_text(
        "🤝 <b>HOMIY</b>\n\n"
        "📢 Homiy kanalimizga o‘tish uchun quyidagi tugmani bosing.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 HOMIY @rakhmonovrek", url="https://t.me/rakhmonovrek")]
        ])
    )

# =========================================================
# PUL ISHLASH
# =========================================================

async def money_work(update, context):
    user = get_user(update.effective_user.id)

    bonus = float(user["bonus_balance"] or 0)
    real = float(user["real_balance"] or 0)
    refs = int(user["referrals"] or 0)

    await update.message.reply_text(
        "💰 <b>PUL ISHLASH</b>\n\n"
        f"🎁 Bonus pul: <b>{bonus:,.0f} so‘m</b>\n"
        f"💳 Kiritilgan pul: <b>{real:,.0f} so‘m</b>\n"
        f"👥 Referallar: <b>{refs}</b>\n\n"
        f"🗣 1 referal = <b>+{REFERRAL_BONUS:,.0f} so‘m bonus</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👥 REFERAL",
                    callback_data="referral"
                )
            ],
            [
                InlineKeyboardButton(
                    "💸 BONUSNI YECHISH",
                    callback_data="money_withdraw"
                )
            ]
        ])
    )

# =========================================================
# STARS ISHLASH
# =========================================================

async def stars_work(update, context):
    user = get_user(update.effective_user.id)

    stars = float(user["points"] or 0)
    refs = int(user["referrals"] or 0)

    await update.message.reply_text(
        "⭐ <b>STARS ISHLASH</b>\n\n"
        f"⭐ Stars: <b>{stars:.2f}</b>\n"
        f"👥 Referallar: <b>{refs}</b>\n\n"
        f"🗣 1 referal = <b>+{REFERRAL_STARS:g} ⭐</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👥 REFERAL",
                    callback_data="referral"
                )
            ]
        ])
    )

# =========================================================
# PREMIUM ISHLASH
# =========================================================

async def premium_work(update, context):
    user = get_user(update.effective_user.id)

    refs = int(user["referrals"] or 0)

    p1 = int(user["premium_1m"] or 0)
    p3 = int(user["premium_3m"] or 0)

    await update.message.reply_text(
        "💎 <b>PREMIUM ISHLASH</b>\n\n"
        f"👥 Referallar: <b>{refs}</b>\n\n"
        "🎁 25 referal → 1 oy Premium\n"
        "🎁 70 referal → 3 oy Premium\n\n"
        f"1 oy: {'✅ Olingan' if p1 else '⏳ Kutilmoqda'}\n"
        f"3 oy: {'✅ Olingan' if p3 else '⏳ Kutilmoqda'}",
        parse_mode="HTML"
    )

# =========================================================
# REFERAL
# =========================================================

async def referral(update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user:
        return

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={user_id}"

    refs = int(user["referrals"] or 0)

    await update.effective_message.reply_text(
        "👥 <b>REFERAL</b>\n\n"
        f"👥 Referallar: <b>{refs}</b>\n"
        f"⭐ Har biri: <b>+{REFERRAL_STARS:g} ⭐</b>\n"
        f"🎁 Har biri: <b>+{REFERRAL_BONUS:,.0f} so‘m bonus</b>\n\n"
        f"🔗 Referal linkingiz:\n"
        f"<code>{link}</code>",
        parse_mode="HTML"
    )

# =========================================================
# NOMER
# =========================================================

async def numbers_menu(update, context):
    buttons = []

    for country, price in NUMBERS.items():
        buttons.append([
            InlineKeyboardButton(
                f"{country} — {price:,} so‘m",
                callback_data=f"number:{country}"
            )
        ])

    await update.message.reply_text(
        "📱 <b>NOMER OLISH</b>\n\n"
        "Davlatni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def number_country(update, context, country):
    price = NUMBERS.get(country)

    if price is None:
        return

    await update.callback_query.edit_message_text(
        f"📱 <b>{country}</b>\n\n"
        f"💰 Narx: <b>{price:,} so‘m</b>\n\n"
        "Buyurtma berish uchun:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🛒 BUYURTMA BERISH",
                    callback_data=f"order_number:{country}"
                )
            ]
        ])
    )

# =========================================================
# NOMER BUYURTMA
# =========================================================

async def create_number_order(update, context, country):
    user_id = update.effective_user.id
    price = NUMBERS.get(country)

    if price is None:
        return

    conn = db()

    cur = conn.execute("""
        UPDATE users
        SET real_balance=real_balance-?,
            total_spent=total_spent+?
        WHERE id=?
        AND real_balance>=?
    """, (
        price,
        price,
        user_id,
        price
    ))

    if cur.rowcount != 1:
        conn.close()

        await update.callback_query.answer(
            f"Balansingiz yetarli emas. Kerak: {price:,} so‘m",
            show_alert=True
        )
        return

    target = (
        f"@{update.effective_user.username}"
        if update.effective_user.username
        else str(user_id)
    )

    cur = conn.execute("""
        INSERT INTO service_orders (
            user_id, category, item, price,
            target, status, created_at, link
        )
        VALUES (?, 'number', ?, ?, ?, 'pending', ?, '')
    """, (
        user_id,
        f"Nomer — {country}",
        price,
        target,
        now_iso()
    ))

    order_id = cur.lastrowid

    conn.commit()
    conn.close()

    await update.callback_query.edit_message_text(
        "✅ <b>NOMER BUYURTMASI QABUL QILINDI</b>\n\n"
        f"📱 Davlat: <b>{country}</b>\n"
        f"💰 Narx: <b>{price:,} so‘m</b>\n"
        f"🆔 Buyurtma: <code>#{order_id}</code>\n\n"
        "Admin raqamni qo‘lda yuboradi.",
        parse_mode="HTML"
    )

    await send_order_to_admin(context, order_id)

# =========================================================
# NAKRUTKA
# =========================================================

async def nakrutka_menu(update, context):
    buttons = []

    for platform in NAKRUTKA:
        buttons.append([
            InlineKeyboardButton(
                f"📈 {platform}",
                callback_data=f"nak_platform:{platform}"
            )
        ])

    await update.message.reply_text(
        "📈 <b>NAKRUTKA</b>\n\n"
        "Platformani tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def nak_platform(update, context, platform):
    if platform not in NAKRUTKA:
        return

    buttons = []

    for quantity, price in NAKRUTKA[platform].items():
        buttons.append([
            InlineKeyboardButton(
                f"{quantity} — {price:,} so‘m",
                callback_data=f"nak:{platform}:{quantity}"
            )
        ])

    await update.callback_query.edit_message_text(
        f"📈 <b>{platform}</b>\n\n"
        "Miqdorni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def nak_quantity(update, context, platform, quantity):
    if platform not in NAKRUTKA:
        return

    if quantity not in NAKRUTKA[platform]:
        return

    price = NAKRUTKA[platform][quantity]

    context.user_data["nak_order"] = {
        "platform": platform,
        "quantity": quantity,
        "price": price
    }

    context.user_data["waiting_nak_link"] = True

    await update.callback_query.edit_message_text(
        "🔗 <b>LINKNI YUBORING</b>\n\n"
        f"📈 Platforma: <b>{platform}</b>\n"
        f"📊 Miqdor: <b>{quantity}</b>\n"
        f"💰 Narx: <b>{price:,} so‘m</b>\n\n"
        "Profil / kanal / video linkini yuboring.",
        parse_mode="HTML"
    )

async def process_nak_link(update, context):
    if not context.user_data.get("waiting_nak_link"):
        return False

    if not update.message or not update.message.text:
        return True

    link = update.message.text.strip()
    order = context.user_data.get("nak_order")

    if not order:
        return True

    if len(link) < 3:
        await update.message.reply_text(
            "❌ Linkni to‘g‘ri yuboring."
        )
        return True

    user_id = update.effective_user.id
    price = order["price"]

    conn = db()

    cur = conn.execute("""
        UPDATE users
        SET real_balance=real_balance-?,
            total_spent=total_spent+?
        WHERE id=?
        AND real_balance>=?
    """, (
        price,
        price,
        user_id,
        price
    ))

    if cur.rowcount != 1:
        conn.close()

        context.user_data.pop("waiting_nak_link", None)
        context.user_data.pop("nak_order", None)

        await update.message.reply_text(
            f"❌ Balansingiz yetarli emas.\n\n"
            f"Kerak: {price:,} so‘m"
        )
        return True

    cur = conn.execute("""
        INSERT INTO service_orders (
            user_id, category, item, price,
            target, status, created_at, link
        )
        VALUES (?, 'nakrutka', ?, ?, '', 'pending', ?, ?)
    """, (
        user_id,
        f"{order['platform']} {order['quantity']}",
        price,
        now_iso(),
        link
    ))

    order_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data.pop("waiting_nak_link", None)
    context.user_data.pop("nak_order", None)

    await update.message.reply_text(
        "✅ <b>NAKRUTKA BUYURTMASI YUBORILDI</b>\n\n"
        f"📈 {order['platform']}\n"
        f"📊 {order['quantity']}\n"
        f"💰 {price:,} so‘m\n"
        f"🆔 #{order_id}",
        parse_mode="HTML"
    )

    await send_order_to_admin(context, order_id)

    return True

# =========================================================
# DO‘KON
# =========================================================

async def shop(update, context):
    await update.message.reply_text(
        "🛍 <b>DO‘KON</b>\n\n"
        "Mahsulotni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⭐ STARS",
                    callback_data="shop_stars"
                )
            ],
            [
                InlineKeyboardButton(
                    "💎 PREMIUM",
                    callback_data="shop_premium"
                )
            ]
        ])
    )

async def shop_stars(update, context):
    buttons = []

    for stars, price in STARS_PRICES.items():
        buttons.append([
            InlineKeyboardButton(
                f"{stars} ⭐ — {price:,} so‘m",
                callback_data=f"buy_stars:{stars}"
            )
        ])

    await update.callback_query.edit_message_text(
        "⭐ <b>STARS SOTIB OLISH</b>\n\n"
        "Miqdorni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def shop_premium(update, context):
    buttons = []

    for months, price in PREMIUM_PRICES.items():
        buttons.append([
            InlineKeyboardButton(
                f"{months} oy — {price:,} so‘m",
                callback_data=f"buy_premium:{months}"
            )
        ])

    await update.callback_query.edit_message_text(
        "💎 <b>PREMIUM SOTIB OLISH</b>\n\n"
        "Muddatni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# =========================================================
# TARGET
# =========================================================

async def target_menu(update, context):
    await update.callback_query.edit_message_text(
        "👤 <b>KIM UCHUN?</b>\n\n"
        "Xizmat kimga beriladi?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👤 O‘ZIMGA",
                    callback_data="target:self"
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 BOSHQA USERGA",
                    callback_data="target:other"
                )
            ]
        ])
    )

# =========================================================
# HISOB TO‘LDIRISH
# =========================================================

async def payment_menu(update, context):
    await update.message.reply_text(
        "💳 <b>HISOB TO‘LDIRISH</b>\n\n"
        f"Karta: <code>{PAYMENT_CARD}</code>\n"
        f"Egasi: <b>{PAYMENT_OWNER}</b>\n\n"
        "1. Kartaga kerakli summani o‘tkazing.\n"
        "2. «💸 TO‘LOV QILDIM» tugmasini bosing.\n"
        "3. Summani kiriting.\n"
        "4. Chekni yuboring.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💸 TO‘LOV QILDIM",
                    callback_data="payment_done"
                )
            ]
        ])
    )

async def payment_done(update, context):
    context.user_data["waiting_payment_amount"] = True

    await update.callback_query.edit_message_text(
        "💵 <b>To‘lov miqdorini kiriting:</b>\n\n"
        "Minimal: <b>1 000 so‘m</b>",
        parse_mode="HTML"
    )

async def receive_receipt(update, context):
    if not context.user_data.get("waiting_receipt"):
        return False

    if not update.message.photo:
        await update.message.reply_text(
            "❌ Chekni rasm ko‘rinishida yuboring."
        )
        return True

    try:
        amount = float(
            context.user_data.get("payment_amount", 0)
        )
    except Exception:
        amount = 0

    if amount < MIN_TOPUP:
        context.user_data.clear()
        await update.message.reply_text(
            f"❌ To‘lov summasi kamida {MIN_TOPUP:,} so‘m bo‘lishi kerak."
        )
        return True

    user = update.effective_user
    photo = update.message.photo[-1]

    conn = db()

    cur = conn.execute("""
        INSERT INTO payment_requests (
            user_id, amount, receipt_file_id,
            status, created_at
        )
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        user.id,
        amount,
        photo.file_id,
        now_iso()
    ))

    request_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data.pop("waiting_receipt", None)
    context.user_data.pop("payment_amount", None)

    username = (
        f"@{user.username}"
        if user.username
        else "Username yo‘q"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ TASDIQLASH",
                callback_data=f"payment_approve:{request_id}"
            ),
            InlineKeyboardButton(
                "❌ RAD ETISH",
                callback_data=f"payment_reject:{request_id}"
            )
        ]
    ])

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo.file_id,
        caption=(
            "💳 <b>YANGI TO‘LOV CHEKI</b>\n\n"
            f"🆔 So‘rov: <code>#{request_id}</code>\n"
            f"👤 User: {username}\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"💵 Summa: <b>{amount:,.0f} so‘m</b>"
        ),
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await update.message.reply_text(
        "✅ <b>CHEK YUBORILDI</b>\n\n"
        f"💵 Summa: <b>{amount:,.0f} so‘m</b>\n"
        "⏳ Admin tekshiradi.",
        parse_mode="HTML"
    )

    return True

# =========================================================
# MENING HISOBIM
# =========================================================

async def my_account(update, context):
    user = get_user(update.effective_user.id)

    if not user:
        return

    real = float(user["real_balance"] or 0)
    bonus = float(user["bonus_balance"] or 0)
    stars = float(user["points"] or 0)
    refs = int(user["referrals"] or 0)

    conn = db()

    orders = conn.execute("""
        SELECT COUNT(*) AS c
        FROM service_orders
        WHERE user_id=?
    """, (user["id"],)).fetchone()["c"]

    deposited = conn.execute("""
        SELECT COALESCE(SUM(amount),0)
        FROM payment_requests
        WHERE user_id=?
        AND status='approved'
    """, (user["id"],)).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"💰 Pul: <b>{real:,.2f} so‘m</b>\n"
        f"🎁 Bonus: <b>{bonus:,.2f} so‘m</b>\n"
        f"⭐ Stars: <b>{stars:.2f}</b>\n"
        f"👥 Referallar: <b>{refs}</b>\n"
        f"🛍 Buyurtmalar: <b>{orders}</b>\n"
        f"💳 Kiritgan pullaringiz: <b>{float(deposited or 0):,.2f} so‘m</b>\n"
        f"💸 Jami sarflagan: <b>{float(user['total_spent'] or 0):,.2f} so‘m</b>\n\n"
        f"🆔 ID: <code>{user['id']}</code>",
        parse_mode="HTML"
    )

# =========================================================
# PUL YECHISH
# =========================================================

async def money_withdraw(update, context):
    user = get_user(update.effective_user.id)

    bonus = float(user["bonus_balance"] or 0)

    if bonus < MIN_WITHDRAW:
        await update.effective_message.reply_text(
            "💸 <b>BONUS PUL YECHISH</b>\n\n"
            f"Minimal: <b>{MIN_WITHDRAW:,} so‘m</b>\n"
            f"Bonus balans: <b>{bonus:,.0f} so‘m</b>",
            parse_mode="HTML"
        )
        return

    conn = db()

    pending = conn.execute("""
        SELECT id
        FROM money_withdrawals
        WHERE user_id=?
        AND status='pending'
    """, (update.effective_user.id,)).fetchone()

    conn.close()

    if pending:
        await update.effective_message.reply_text(
            "⏳ Sizda allaqachon pending pul yechish so‘rovi bor."
        )
        return

    context.user_data["money_withdraw"] = True

    await update.effective_message.reply_text(
        "💸 <b>BONUS PUL YECHISH</b>\n\n"
        f"🎁 Bonus: <b>{bonus:,.0f} so‘m</b>\n"
        f"Minimal: <b>{MIN_WITHDRAW:,} so‘m</b>\n\n"
        "Qancha yechmoqchisiz?\n"
        "Masalan: <code>10000</code>",
        parse_mode="HTML"
    )

async def process_money_withdraw(update, context):
    if not context.user_data.get("money_withdraw"):
        return

    try:
        amount = float(
            update.message.text.replace(",", "").replace(" ", "")
        )
    except Exception:
        await update.message.reply_text(
            "❌ Faqat raqam kiriting."
        )
        return

    user_id = update.effective_user.id

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimal {MIN_WITHDRAW:,} so‘m."
        )
        return

    conn = db()

    pending = conn.execute("""
        SELECT id
        FROM money_withdrawals
        WHERE user_id=?
        AND status='pending'
    """, (user_id,)).fetchone()

    if pending:
        conn.close()
        context.user_data.pop("money_withdraw", None)
        await update.message.reply_text(
            "⏳ Sizda pending so‘rov mavjud."
        )
        return

    cur = conn.execute("""
        UPDATE users
        SET bonus_balance=bonus_balance-?
        WHERE id=?
        AND bonus_balance>=?
    """, (
        amount,
        user_id,
        amount
    ))

    if cur.rowcount != 1:
        conn.close()
        await update.message.reply_text(
            "❌ Bonus balansingiz yetarli emas."
        )
        return

    cur = conn.execute("""
        INSERT INTO money_withdrawals (
            user_id, amount, status, created_at
        )
        VALUES (?, ?, 'pending', ?)
    """, (
        user_id,
        amount,
        now_iso()
    ))

    withdrawal_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data.pop("money_withdraw", None)

    await update.message.reply_text(
        "✅ <b>SO‘ROV YUBORILDI</b>\n\n"
        f"🎁 Bonus: <b>{amount:,.0f} so‘m</b>\n"
        "⏳ Admin ko‘rib chiqadi.",
        parse_mode="HTML"
    )

    await context.bot.send_message(
        ADMIN_ID,
        "💸 <b>YANGI BONUS YECHISH</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"💰 Miqdor: <b>{amount:,.0f} so‘m</b>\n"
        f"🆔 So‘rov: <code>#{withdrawal_id}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ TASDIQLASH",
                    callback_data=f"withdraw_approve:{withdrawal_id}"
                ),
                InlineKeyboardButton(
                    "❌ RAD ETISH",
                    callback_data=f"withdraw_reject:{withdrawal_id}"
                )
            ]
        ])
    )

# =========================================================
# ADMIN ORDER
# =========================================================

async def send_order_to_admin(context, order_id):
    conn = db()

    row = conn.execute("""
        SELECT *
        FROM service_orders
        WHERE id=?
    """, (order_id,)).fetchone()

    conn.close()

    if not row:
        return

    user = get_user(row["user_id"])

    username = (
        f"@{user['username']}"
        if user and user["username"]
        else "Username yo‘q"
    )

    text = (
        "🛍 <b>YANGI ZAYAVKA</b>\n\n"
        f"🆔 Buyurtma: <code>#{row['id']}</code>\n"
        f"👤 User: {username}\n"
        f"🆔 User ID: <code>{row['user_id']}</code>\n"
        f"🛍 Xizmat: <b>{row['item']}</b>\n"
        f"💰 Narx: <b>{float(row['price'] or 0):,.0f} so‘m</b>\n"
        f"🎯 Kimga: <b>{row['target'] or '—'}</b>\n"
    )

    if row["link"]:
        text += f"🔗 Link: <code>{row['link']}</code>\n"

    text += "\n⏳ Holat: <b>PENDING</b>"

    await context.bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ BAJARILDI",
                    callback_data=f"order_done:{row['id']}"
                ),
                InlineKeyboardButton(
                    "❌ RAD ETISH",
                    callback_data=f"order_reject:{row['id']}"
                )
            ]
        ])
    )

# =========================================================
# ADMIN HOMIY PANEL
# =========================================================

async def admin_sponsors(update, context):
    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM sponsors
        ORDER BY channel
    """).fetchall()

    conn.close()

    text = "📢 <b>HOMIY KANALLAR</b>\n\n"

    buttons = []

    if not rows:
        text += "Homiy kanal yo‘q.\n"
    else:
        for row in rows:
            status = "🟢 YOQILGAN" if row["active"] else "🔴 O‘CHIRILGAN"

            text += (
                f"📢 <b>{row['channel']}</b>\n"
                f"📌 Holat: {status}\n"
                f"👥 Kelgan: <b>{row['joined_users']}</b>\n"
                f"🎯 Limit: <b>{row['limit_users']}</b>\n\n"
            )

            buttons.append([
                InlineKeyboardButton(
                    "🔴 O‘CHIRISH" if row["active"] else "🟢 YOQISH",
                    callback_data=f"sponsor_toggle:{row['channel']}"
                ),
                InlineKeyboardButton(
                    "🔢 LIMIT",
                    callback_data=f"sponsor_limit:{row['channel']}"
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    "🗑 O‘CHIRISH",
                    callback_data=f"sponsor_delete:{row['channel']}"
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            "➕ HOMIY QO‘SHISH",
            callback_data="sponsor_add"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ ADMIN",
            callback_data="admin_back"
        )
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# =========================================================
# CREATE ORDER
# =========================================================

async def create_order(update, context, order, target):
    user_id = update.effective_user.id
    price = float(order["price"])

    conn = db()

    cur = conn.execute("""
        UPDATE users
        SET real_balance=real_balance-?,
            total_spent=total_spent+?
        WHERE id=?
        AND real_balance>=?
    """, (
        price,
        price,
        user_id,
        price
    ))

    if cur.rowcount != 1:
        conn.close()

        await update.callback_query.answer(
            f"Balans yetarli emas. Kerak: {price:,.0f} so‘m",
            show_alert=True
        )
        return

    cur = conn.execute("""
        INSERT INTO service_orders (
            user_id, category, item, price,
            target, status, created_at, link
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?, '')
    """, (
        user_id,
        order["category"],
        order["item"],
        price,
        target,
        now_iso()
    ))

    order_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data.pop("pending_order", None)

    await update.callback_query.edit_message_text(
        "✅ <b>BUYURTMA YUBORILDI</b>\n\n"
        f"🛍 Xizmat: <b>{order['item']}</b>\n"
        f"💰 Narx: <b>{price:,.0f} so‘m</b>\n"
        f"👤 Qabul qiluvchi: <b>{target}</b>\n"
        f"🆔 Buyurtma: <code>#{order_id}</code>",
        parse_mode="HTML"
    )

    await send_order_to_admin(context, order_id)

# =========================================================
# ADMIN ORDER DONE
# =========================================================

async def admin_finish_order(update, context, order_id):
    conn = db()

    row = conn.execute("""
        SELECT *
        FROM service_orders
        WHERE id=?
    """, (order_id,)).fetchone()

    if not row or row["status"] != "pending":
        conn.close()
        await update.callback_query.answer(
            "Bu buyurtma allaqachon ko‘rilgan.",
            show_alert=True
        )
        return

    cur = conn.execute("""
        UPDATE service_orders
        SET status='completed',
            processed_at=?
        WHERE id=?
        AND status='pending'
    """, (
        now_iso(),
        order_id
    ))

    conn.commit()
    conn.close()

    if cur.rowcount != 1:
        return

    try:
        await update.callback_query.edit_message_text(
            (update.callback_query.message.text or "")
            + "\n\n✅ <b>BAJARILDI</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await context.bot.send_message(
        row["user_id"],
        "✅ <b>BUYURTMANGIZ BAJARILDI</b>\n\n"
        f"🆔 #{order_id}\n"
        f"🛍 {row['item']}",
        parse_mode="HTML"
    )

# =========================================================
# ADMIN ORDER REJECT
# =========================================================

async def admin_reject_order(update, context, order_id):
    conn = db()

    row = conn.execute("""
        SELECT *
        FROM service_orders
        WHERE id=?
    """, (order_id,)).fetchone()

    if not row or row["status"] != "pending":
        conn.close()
        await update.callback_query.answer(
            "Bu buyurtma allaqachon ko‘rilgan.",
            show_alert=True
        )
        return

    cur = conn.execute("""
        UPDATE service_orders
        SET status='rejected',
            processed_at=?
        WHERE id=?
        AND status='pending'
    """, (
        now_iso(),
        order_id
    ))

    if cur.rowcount != 1:
        conn.close()
        return

    conn.execute("""
        UPDATE users
        SET real_balance=real_balance+?,
            total_spent=MAX(0, total_spent-?)
        WHERE id=?
    """, (
        row["price"],
        row["price"],
        row["user_id"]
    ))

    conn.commit()
    conn.close()

    try:
        await update.callback_query.edit_message_text(
            (update.callback_query.message.text or "")
            + "\n\n❌ <b>RAD ETILDI — PUL QAYTARILDI</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await context.bot.send_message(
        row["user_id"],
        "❌ <b>BUYURTMANGIZ RAD ETILDI</b>\n\n"
        f"🆔 #{order_id}\n"
        f"💰 {float(row['price']):,.0f} so‘m balansingizga qaytarildi.",
        parse_mode="HTML"
    )

# =========================================================
# WITHDRAW ADMIN
# =========================================================

async def admin_approve_withdraw(update, context, withdrawal_id):
    conn = db()

    row = conn.execute("""
        SELECT *
        FROM money_withdrawals
        WHERE id=?
    """, (withdrawal_id,)).fetchone()

    if not row or row["status"] != "pending":
        conn.close()
        await update.callback_query.answer(
            "Bu so‘rov allaqachon ko‘rilgan.",
            show_alert=True
        )
        return

    cur = conn.execute("""
        UPDATE money_withdrawals
        SET status='approved',
            processed_at=?
        WHERE id=?
        AND status='pending'
    """, (
        now_iso(),
        withdrawal_id
    ))

    conn.commit()
    conn.close()

    if cur.rowcount != 1:
        return

    try:
        await update.callback_query.edit_message_text(
            (update.callback_query.message.text or "")
            + "\n\n✅ <b>TASDIQLANDI</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await context.bot.send_message(
        row["user_id"],
        "✅ <b>SO‘ROVINGIZ KO‘RIB CHIQILDI</b>\n\n"
        f"💰 Miqdor: <b>{float(row['amount']):,.0f} so‘m</b>\n\n"
        "⏳ To‘lov 24 soat ichida amalga oshiriladi.",
        parse_mode="HTML"
    )

async def admin_reject_withdraw(update, context, withdrawal_id):
    conn = db()

    row = conn.execute("""
        SELECT *
        FROM money_withdrawals
        WHERE id=?
    """, (withdrawal_id,)).fetchone()

    if not row or row["status"] != "pending":
        conn.close()
        await update.callback_query.answer(
            "Bu so‘rov allaqachon ko‘rilgan.",
            show_alert=True
        )
        return

    cur = conn.execute("""
        UPDATE money_withdrawals
        SET status='rejected',
            processed_at=?
        WHERE id=?
        AND status='pending'
    """, (
        now_iso(),
        withdrawal_id
    ))

    if cur.rowcount != 1:
        conn.close()
        return

    conn.execute("""
        UPDATE users
        SET bonus_balance=bonus_balance+?
        WHERE id=?
    """, (
        row["amount"],
        row["user_id"]
    ))

    conn.commit()
    conn.close()

    try:
        await update.callback_query.edit_message_text(
            (update.callback_query.message.text or "")
            + "\n\n❌ <b>RAD ETILDI — BONUS QAYTARILDI</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await context.bot.send_message(
        row["user_id"],
        "❌ <b>PUL YECHISH RAD ETILDI</b>\n\n"
        f"🎁 {float(row['amount']):,.0f} so‘m qaytarildi.",
        parse_mode="HTML"
    )

# =========================================================
# STATISTIKA
# =========================================================

def get_statistics():
    conn = db()

    total_users = int(
        conn.execute("""
            SELECT total_users
            FROM bot_stats
            WHERE id=1
        """).fetchone()["total_users"]
    )

    day_ago = (
        datetime.now(timezone.utc)
        - timedelta(days=1)
    ).isoformat()

    active_24h = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE last_seen >= ?
    """, (day_ago,)).fetchone()[0]

    total_refs = conn.execute("""
        SELECT COALESCE(SUM(referrals),0)
        FROM users
    """).fetchone()[0]

    real_balance_sum = conn.execute("""
        SELECT COALESCE(SUM(real_balance),0)
        FROM users
    """).fetchone()[0]

    bonus_balance = conn.execute("""
        SELECT COALESCE(SUM(bonus_balance),0)
        FROM users
    """).fetchone()[0]

    stars = conn.execute("""
        SELECT COALESCE(SUM(points),0)
        FROM users
    """).fetchone()[0]

    deposited = conn.execute("""
        SELECT COALESCE(SUM(amount),0)
        FROM payment_requests
        WHERE status='approved'
    """).fetchone()[0]

    spent = conn.execute("""
        SELECT COALESCE(SUM(price),0)
        FROM service_orders
        WHERE status='completed'
    """).fetchone()[0]

    orders = conn.execute("""
        SELECT COUNT(*)
        FROM service_orders
    """).fetchone()[0]

    pending_orders = conn.execute("""
        SELECT COUNT(*)
        FROM service_orders
        WHERE status='pending'
    """).fetchone()[0]

    pending_payments = conn.execute("""
        SELECT COUNT(*)
        FROM payment_requests
        WHERE status='pending'
    """).fetchone()[0]

    pending_withdrawals = conn.execute("""
        SELECT COUNT(*)
        FROM money_withdrawals
        WHERE status='pending'
    """).fetchone()[0]

    conn.close()

    return {
        "total_users": total_users,
        "active_24h": int(active_24h),
        "total_refs": int(total_refs),
        "real_balance": float(real_balance_sum),
        "bonus_balance": float(bonus_balance),
        "stars": float(stars),
        "deposited": float(deposited),
        "spent": float(spent),
        "orders": int(orders),
        "pending_orders": int(pending_orders),
        "pending_payments": int(pending_payments),
        "pending_withdrawals": int(pending_withdrawals),
    }

async def admin_stats(update, context):
    s = get_statistics()

    await update.callback_query.edit_message_text(
        "📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Jami obunachi: <b>{s['total_users']}</b>\n"
        f"🟢 24 soat aktiv: <b>{s['active_24h']}</b>\n"
        f"🗣 Jami referallar: <b>{s['total_refs']}</b>\n\n"
        f"⭐ Jami Stars: <b>{s['stars']:.2f}</b>\n"
        f"💳 Kiritilgan: <b>{s['deposited']:,.2f} so‘m</b>\n"
        f"💰 Balanslar: <b>{s['real_balance']:,.2f} so‘m</b>\n"
        f"🎁 Bonuslar: <b>{s['bonus_balance']:,.2f} so‘m</b>\n"
        f"🛍 Sarflangan: <b>{s['spent']:,.2f} so‘m</b>\n\n"
        f"🛍 Buyurtmalar: <b>{s['orders']}</b>\n"
        f"⏳ Pending buyurtmalar: <b>{s['pending_orders']}</b>\n"
        f"💳 Pending to‘lovlar: <b>{s['pending_payments']}</b>\n"
        f"💸 Pending yechishlar: <b>{s['pending_withdrawals']}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 YANGILASH",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ ADMIN",
                    callback_data="admin_back"
                )
            ]
        ])
    )

# =========================================================
# ADMIN ORDERS
# =========================================================

async def admin_orders(update, context):
    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM service_orders
        ORDER BY id DESC
        LIMIT 15
    """).fetchall()

    conn.close()

    text = "🛍 <b>SO‘NGGI BUYURTMALAR</b>\n\n"

    if not rows:
        text += "Buyurtma yo‘q."
    else:
        for row in rows:
            text += (
                f"🆔 #{row['id']}\n"
                f"🛍 {row['item']}\n"
                f"💰 {float(row['price']):,.0f} so‘m\n"
                f"📌 {row['status']}\n\n"
            )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 YANGILASH",
                    callback_data="admin_orders"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ ADMIN",
                    callback_data="admin_back"
                )
            ]
        ])
    )

# =========================================================
# ADMIN PAYMENTS
# =========================================================

async def admin_payments(update, context):
    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM payment_requests
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT 15
    """).fetchall()

    conn.close()

    text = "💳 <b>PENDING TO‘LOVLAR</b>\n\n"

    if not rows:
        text += "Pending chek yo‘q."
    else:
        for row in rows:
            text += (
                f"🆔 #{row['id']}\n"
                f"👤 <code>{row['user_id']}</code>\n"
                f"💵 {float(row['amount']):,.0f} so‘m\n\n"
            )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 YANGILASH",
                    callback_data="admin_payments"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ ADMIN",
                    callback_data="admin_back"
                )
            ]
        ])
    )

# =========================================================
# ADMIN WITHDRAWALS
# =========================================================

async def admin_withdrawals(update, context):
    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM money_withdrawals
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT 15
    """).fetchall()

    conn.close()

    text = "💸 <b>PENDING YECHISHLAR</b>\n\n"

    if not rows:
        text += "Pending so‘rov yo‘q."
    else:
        for row in rows:
            text += (
                f"🆔 #{row['id']}\n"
                f"👤 <code>{row['user_id']}</code>\n"
                f"💰 {float(row['amount']):,.0f} so‘m\n\n"
            )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 YANGILASH",
                    callback_data="admin_withdrawals"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ ADMIN",
                    callback_data="admin_back"
                )
            ]
        ])
    )

# =========================================================
# ADMIN
# =========================================================

async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Ruxsat yo‘q.")
        return

    s = get_statistics()

    await update.message.reply_text(
        "👑 <b>ADMIN PANEL</b>\n\n"
        f"👥 Obunachilar: <b>{s['total_users']}</b>\n"
        f"🟢 24 soat aktiv: <b>{s['active_24h']}</b>\n"
        f"🗣 Referallar: <b>{s['total_refs']}</b>\n"
        f"⭐ Stars: <b>{s['stars']:.2f}</b>\n"
        f"💳 Kiritilgan: <b>{s['deposited']:,.0f} so‘m</b>\n"
        f"💰 Balanslar: <b>{s['real_balance']:,.0f} so‘m</b>\n\n"
        "Kerakli bo‘limni tanlang.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📊 STATISTIKA",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 HOMIYLAR",
                    callback_data="admin_sponsors"
                )
            ],
            [
                InlineKeyboardButton(
                    "💳 TO‘LOVLAR",
                    callback_data="admin_payments"
                )
            ],
            [
                InlineKeyboardButton(
                    "🛍 BUYURTMALAR",
                    callback_data="admin_orders"
                )
            ],
            [
                InlineKeyboardButton(
                    "💸 PUL YECHISHLAR",
                    callback_data="admin_withdrawals"
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 REKLAMA YUBORISH",
                    callback_data="admin_broadcast"
                )
            ]
        ])
    )

# =========================================================
# CALLBACKS
# =========================================================

async def callbacks(update, context):
    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id

    await query.answer()

    # =====================================================
    # SPONSOR CHECK
    # =====================================================

    if data == "check_sponsor":
        if not await check_sponsor(context.bot, user_id):
            await query.answer(
                "❌ Avval barcha homiy kanallarga obuna bo‘ling!",
                show_alert=True
            )
            return

        await query.edit_message_text(
            "✅ <b>OBUNA TASDIQLANDI!</b>",
            parse_mode="HTML"
        )

        await query.message.reply_text(
            "🖥 <b>Asosiy menyudasiz!</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
        return

    # =====================================================
    # ADMIN HOMIY
    # =====================================================

    if data == "admin_sponsors":
        if user_id != ADMIN_ID:
            return

        await admin_sponsors(update, context)
        return

    if data == "sponsor_add":
        if user_id != ADMIN_ID:
            return

        context.user_data["adding_sponsor"] = True

        await query.message.reply_text(
            "📢 <b>HOMIY QO‘SHISH</b>\n\n"
            "Kanal username yoki link yuboring:\n"
            "<code>@kanal</code> yoki <code>https://t.me/+...</code>",
            parse_mode="HTML"
        )
        return

    if data.startswith("sponsor_toggle:"):
        if user_id != ADMIN_ID:
            return

        channel = data.split(":", 1)[1]

        conn = db()

        conn.execute("""
            UPDATE sponsors
            SET active = CASE
                WHEN active=1 THEN 0
                ELSE 1
            END
            WHERE channel=?
        """, (channel,))

        conn.commit()
        conn.close()

        await admin_sponsors(update, context)
        return

    if data.startswith("sponsor_delete:"):
        if user_id != ADMIN_ID:
            return

        channel = data.split(":", 1)[1]

        conn = db()

        conn.execute("""
            DELETE FROM sponsors
            WHERE channel=?
        """, (channel,))

        conn.commit()
        conn.close()

        await admin_sponsors(update, context)
        return

    if data.startswith("sponsor_limit:"):
        if user_id != ADMIN_ID:
            return

        channel = data.split(":", 1)[1]

        context.user_data["sponsor_limit_channel"] = channel

        await query.message.reply_text(
            "🔢 <b>HOMIY LIMITI</b>\n\n"
            "Nechta yangi odam kelganda avtomatik o‘chsin?\n\n"
            "Masalan: <code>380</code>",
            parse_mode="HTML"
        )
        return

    # =====================================================
    # PAYMENT
    # =====================================================

    if data == "payment_done":
        await payment_done(update, context)
        return

    if data.startswith("payment_approve:"):
        if user_id != ADMIN_ID:
            return

        try:
            request_id = int(data.split(":")[1])
        except Exception:
            return

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM payment_requests
            WHERE id=?
        """, (request_id,)).fetchone()

        if not row or row["status"] != "pending":
            conn.close()
            await query.answer(
                "Bu to‘lov allaqachon ko‘rilgan.",
                show_alert=True
            )
            return

        amount = float(row["amount"] or 0)

        cur = conn.execute("""
            UPDATE payment_requests
            SET status='approved',
                processed_at=?
            WHERE id=?
            AND status='pending'
        """, (
            now_iso(),
            request_id
        ))

        if cur.rowcount != 1:
            conn.close()
            return

        conn.execute("""
            UPDATE users
            SET real_balance=real_balance+?,
                total_deposited=total_deposited+?
            WHERE id=?
        """, (
            amount,
            amount,
            row["user_id"]
        ))

        conn.commit()
        conn.close()

        try:
            await query.edit_message_caption(
                (query.message.caption or "")
                + "\n\n✅ <b>TASDIQLANDI</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await context.bot.send_message(
            row["user_id"],
            "✅ <b>TO‘LOV TASDIQLANDI</b>\n\n"
            f"💰 Balansingizga <b>{amount:,.0f} so‘m</b> qo‘shildi.",
            parse_mode="HTML"
        )
        return

    if data.startswith("payment_reject:"):
        if user_id != ADMIN_ID:
            return

        try:
            request_id = int(data.split(":")[1])
        except Exception:
            return

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM payment_requests
            WHERE id=?
        """, (request_id,)).fetchone()

        if not row or row["status"] != "pending":
            conn.close()
            return

        cur = conn.execute("""
            UPDATE payment_requests
            SET status='rejected',
                processed_at=?
            WHERE id=?
            AND status='pending'
        """, (
            now_iso(),
            request_id
        ))

        conn.commit()
        conn.close()

        if cur.rowcount != 1:
            return

        try:
            await query.edit_message_caption(
                (query.message.caption or "")
                + "\n\n❌ <b>RAD ETILDI</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await context.bot.send_message(
            row["user_id"],
            "❌ <b>TO‘LOV RAD ETILDI</b>",
            parse_mode="HTML"
        )
        return

    # =====================================================
    # REFERRAL / WITHDRAW
    # =====================================================

    if data == "referral":
        await referral(update, context)
        return

    if data == "money_withdraw":
        await money_withdraw(update, context)
        return

    # =====================================================
    # NUMBER
    # =====================================================

    if data.startswith("number:"):
        await number_country(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("order_number:"):
        await create_number_order(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    # =====================================================
    # NAKRUTKA
    # =====================================================

    if data.startswith("nak_platform:"):
        await nak_platform(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("nak:"):
        parts = data.split(":", 2)

        if len(parts) != 3:
            return

        await nak_quantity(
            update,
            context,
            parts[1],
            parts[2]
        )
        return

    # =====================================================
    # SHOP
    # =====================================================

    if data == "shop_stars":
        await shop_stars(update, context)
        return

    if data == "shop_premium":
        await shop_premium(update, context)
        return

    if data.startswith("buy_stars:"):
        try:
            stars = int(data.split(":")[1])
        except Exception:
            return

        if stars not in STARS_PRICES:
            return

        context.user_data["pending_order"] = {
            "category": "stars",
            "item": f"{stars} Stars",
            "price": STARS_PRICES[stars]
        }

        await target_menu(update, context)
        return

    if data.startswith("buy_premium:"):
        try:
            months = int(data.split(":")[1])
        except Exception:
            return

        if months not in PREMIUM_PRICES:
            return

        context.user_data["pending_order"] = {
            "category": "premium",
            "item": f"{months} oy Premium",
            "price": PREMIUM_PRICES[months]
        }

        await target_menu(update, context)
        return

    # =====================================================
    # TARGET
    # =====================================================

    if data == "target:self":
        order = context.user_data.get("pending_order")

        if not order:
            return

        target = (
            f"@{query.from_user.username}"
            if query.from_user.username
            else str(query.from_user.id)
        )

        await create_order(
            update,
            context,
            order,
            target
        )
        return

    if data == "target:other":
        context.user_data["waiting_target"] = True

        await query.edit_message_text(
            "👥 <b>BOSHQA USER</b>\n\n"
            "Username yuboring.\n\n"
            "Masalan: <code>@username</code>",
            parse_mode="HTML"
        )
        return

    # =====================================================
    # ADMIN ORDERS
    # =====================================================

    if data.startswith("order_done:"):
        if user_id != ADMIN_ID:
            return

        await admin_finish_order(
            update,
            context,
            int(data.split(":")[1])
        )
        return

    if data.startswith("order_reject:"):
        if user_id != ADMIN_ID:
            return

        await admin_reject_order(
            update,
            context,
            int(data.split(":")[1])
        )
        return

    # =====================================================
    # WITHDRAW ADMIN
    # =====================================================

    if data.startswith("withdraw_approve:"):
        if user_id != ADMIN_ID:
            return

        await admin_approve_withdraw(
            update,
            context,
            int(data.split(":")[1])
        )
        return

    if data.startswith("withdraw_reject:"):
        if user_id != ADMIN_ID:
            return

        await admin_reject_withdraw(
            update,
            context,
            int(data.split(":")[1])
        )
        return

    # =====================================================
    # ADMIN
    # =====================================================

    if data == "admin_stats":
        if user_id == ADMIN_ID:
            await admin_stats(update, context)
        return

    if data == "admin_orders":
        if user_id == ADMIN_ID:
            await admin_orders(update, context)
        return

    if data == "admin_payments":
        if user_id == ADMIN_ID:
            await admin_payments(update, context)
        return

    if data == "admin_withdrawals":
        if user_id == ADMIN_ID:
            await admin_withdrawals(update, context)
        return

    if data == "admin_broadcast":
        if user_id != ADMIN_ID:
            return

        context.user_data["broadcast"] = True

        await query.message.reply_text(
            "📢 <b>REKLAMA / XABAR</b>\n\n"
            "Hammaga yuboriladigan matnni yozing.",
            parse_mode="HTML"
        )
        return

    if data == "admin_back":
        if user_id != ADMIN_ID:
            return

        await query.message.reply_text(
            "👑 <b>ADMIN PANEL</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📊 STATISTIKA",
                        callback_data="admin_stats"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📢 HOMIYLAR",
                        callback_data="admin_sponsors"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💳 TO‘LOVLAR",
                        callback_data="admin_payments"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🛍 BUYURTMALAR",
                        callback_data="admin_orders"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💸 PUL YECHISHLAR",
                        callback_data="admin_withdrawals"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📢 REKLAMA",
                        callback_data="admin_broadcast"
                    )
                ]
            ])
        )
        return

# =========================================================
# BROADCAST
# =========================================================

async def process_broadcast(update, context):
    if update.effective_user.id != ADMIN_ID:
        return False

    if not context.user_data.get("broadcast"):
        return False

    if not update.message or not update.message.text:
        return True

    message_text = update.message.text.strip()

    context.user_data.pop("broadcast", None)

    conn = db()

    users = conn.execute("""
        SELECT id
        FROM users
        WHERE blocked=0
    """).fetchall()

    conn.close()

    sent = 0
    failed = 0

    await update.message.reply_text(
        "📢 Reklama yuborish boshlandi..."
    )

    for row in users:
        try:
            await context.bot.send_message(
                row["id"],
                message_text
            )

            sent += 1
            await asyncio.sleep(0.05)

        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after))

            try:
                await context.bot.send_message(
                    row["id"],
                    message_text
                )
                sent += 1
            except Exception:
                failed += 1

        except Forbidden:
            failed += 1

            conn = db()

            conn.execute("""
                UPDATE users
                SET blocked=1
                WHERE id=?
            """, (row["id"],))

            conn.commit()
            conn.close()

        except Exception:
            failed += 1

    await update.message.reply_text(
        "📢 <b>REKLAMA YAKUNLANDI</b>\n\n"
        f"✅ Yuborildi: <b>{sent}</b>\n"
        f"❌ Yuborilmadi: <b>{failed}</b>",
        parse_mode="HTML"
    )

    return True

# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(update, context):
    if not update.effective_user:
        return

    user_id = update.effective_user.id

    # ADMIN HOMIY QO‘SHISH
    if user_id == ADMIN_ID:

        if context.user_data.get("adding_sponsor"):
            raw = update.message.text.strip()

            if not raw:
                await update.message.reply_text("❌ Kanal username yoki link yuboring.")
                return

            # @username, t.me/username va private join-request/invite linklar qabul qilinadi.
            if raw.startswith("https://t.me/") or raw.startswith("http://t.me/"):
                url = raw.replace("http://", "https://", 1)
                tail = url.split("t.me/", 1)[1].strip("/")
                channel = "@" + tail if tail and not tail.startswith(("+", "joinchat/")) else url
            elif raw.startswith("t.me/"):
                url = "https://" + raw
                tail = raw.split("t.me/", 1)[1].strip("/")
                channel = "@" + tail if tail and not tail.startswith(("+", "joinchat/")) else url
            else:
                channel = raw if raw.startswith("@") else "@" + raw
                url = f"https://t.me/{channel.lstrip('@')}"

            conn = db()
            conn.execute("""
                INSERT OR REPLACE INTO sponsors(
                    channel, url, limit_users, joined_users, active, created_at
                )
                VALUES (?, ?, 380, 0, 1, ?)
            """, (channel, url, now_iso()))
            conn.commit()
            conn.close()

            context.user_data.pop("adding_sponsor", None)

            await update.message.reply_text(
                f"✅ <b>{channel}</b> homiy qo‘shildi.\n\n"
                f"🔗 {url}\n"
                "🎯 Limit: <b>380</b>",
                parse_mode="HTML"
            )
            return

        if context.user_data.get("sponsor_limit_channel"):
            try:
                limit = int(
                    update.message.text
                    .replace(" ", "")
                    .replace(",", "")
                )
            except Exception:
                await update.message.reply_text(
                    "❌ Faqat raqam kiriting."
                )
                return

            if limit < 1:
                await update.message.reply_text(
                    "❌ Limit 1 dan katta bo‘lishi kerak."
                )
                return

            channel = context.user_data.pop(
                "sponsor_limit_channel"
            )

            conn = db()

            conn.execute("""
                UPDATE sponsors
                SET limit_users=?,
                    active=CASE
                        WHEN joined_users >= ? THEN 0
                        ELSE 1
                    END
                WHERE channel=?
            """, (
                limit,
                limit,
                channel
            ))

            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>{channel}</b>\n\n"
                f"🎯 Yangi limit: <b>{limit}</b>",
                parse_mode="HTML"
            )

            return

    # BROADCAST
    if await process_broadcast(update, context):
        return

    # RECEIPT
    if (
        update.message
        and update.message.photo
        and context.user_data.get("waiting_receipt")
    ):
        await receive_receipt(update, context)
        return

    # PAYMENT AMOUNT
    if context.user_data.get("waiting_payment_amount"):

        try:
            amount = float(
                update.message.text
                .replace(",", "")
                .replace(" ", "")
            )
        except Exception:
            await update.message.reply_text(
                "❌ Faqat raqam kiriting."
            )
            return

        if amount < MIN_TOPUP:
            await update.message.reply_text(
                f"❌ Minimal: {MIN_TOPUP:,} so‘m."
            )
            return

        context.user_data.pop(
            "waiting_payment_amount",
            None
        )

        context.user_data["payment_amount"] = amount
        context.user_data["waiting_receipt"] = True

        await update.message.reply_text(
            "📝 <b>To‘lov chekini rasm qilib yuboring</b>\n\n"
            f"💵 Summa: <b>{amount:,.0f} so‘m</b>",
            parse_mode="HTML"
        )
        return

    # NAKRUTKA LINK
    if context.user_data.get("waiting_nak_link"):
        if await process_nak_link(update, context):
            return

    # WITHDRAW
    if (
        context.user_data.get("money_withdraw")
        and update.message
        and update.message.text
    ):
        await process_money_withdraw(update, context)
        return

    # OTHER USER
    if context.user_data.get("waiting_target"):

        target = update.message.text.strip()

        if not target:
            return

        order = context.user_data.get("pending_order")

        context.user_data.pop(
            "waiting_target",
            None
        )

        if not order:
            return

        price = float(order["price"])

        conn = db()

        cur = conn.execute("""
            UPDATE users
            SET real_balance=real_balance-?,
                total_spent=total_spent+?
            WHERE id=?
            AND real_balance>=?
        """, (
            price,
            price,
            user_id,
            price
        ))

        if cur.rowcount != 1:
            conn.close()

            context.user_data.pop(
                "pending_order",
                None
            )

            await update.message.reply_text(
                f"❌ Balansingiz yetarli emas.\n\n"
                f"Kerak: {price:,.0f} so‘m"
            )
            return

        cur = conn.execute("""
            INSERT INTO service_orders (
                user_id, category, item, price,
                target, status, created_at, link
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?, '')
        """, (
            user_id,
            order["category"],
            order["item"],
            price,
            target,
            now_iso()
        ))

        order_id = cur.lastrowid

        conn.commit()
        conn.close()

        context.user_data.pop(
            "pending_order",
            None
        )

        await update.message.reply_text(
            "✅ <b>BUYURTMA YUBORILDI</b>\n\n"
            f"🛍 {order['item']}\n"
            f"💰 {price:,.0f} so‘m\n"
            f"👤 {target}\n"
            f"🆔 #{order_id}",
            parse_mode="HTML"
        )

        await send_order_to_admin(
            context,
            order_id
        )
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text == "💰 PUL ISHLASH":
        await money_work(update, context)

    elif text == "⭐ STARS":
        await stars_work(update, context)

    elif text == "💎 PREMIUM":
        await premium_work(update, context)

    elif text == "📱 NOMER OLISH":
        await numbers_menu(update, context)

    elif text == "📈 NAKRUTKA":
        await nakrutka_menu(update, context)

    elif text == "🛍 DO‘KON":
        await shop(update, context)

    elif text == "💳 HISOB TO‘LDIRISH":
        await payment_menu(update, context)

    elif text == "👤 MENING HISOBIM":
        await my_account(update, context)

    elif text == "🤝 HOMIY":
        await homiy_menu(update, context)

# =========================================================
# ERROR
# =========================================================

async def error_handler(update, context):
    logger.error(
        "Exception:",
        exc_info=context.error
    )

# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN GitHub Secrets ichida topilmadi."
        )

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("admin", admin_command)
    )

    application.add_handler(
        CallbackQueryHandler(callbacks)
    )

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            text_handler
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "ARZON SMM BOT ishga tushdi."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    main()
