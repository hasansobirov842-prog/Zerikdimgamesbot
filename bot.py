import os
import sqlite3
import asyncio
import logging
from datetime import datetime, timezone

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

# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "8679536810"))
except Exception:
    ADMIN_ID = 8679536810
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "")
PAYMENT_OWNER = os.getenv("PAYMENT_OWNER", "RAKHMONOVA/O")
DB_FILE = "zerikdim.db"

REFERRAL_STARS = 9.0
REFERRAL_MONEY = 500.0

MIN_MONEY_WITHDRAW = 10000

PAYMENT_CARD = os.getenv("PAYMENT_CARD", "").strip()
PAYMENT_OWNER = os.getenv("PAYMENT_OWNER", "R/O").strip()

SPONSOR_CHANNEL = "@premyumstarstekin"
SPONSOR_URL = "https://t.me/premyumstarstekin"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_FILE)
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

    # Eski users jadvali saqlanadi
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

    # Eski withdrawals
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
            url TEXT
        )
    """)

    # YANGI USTUNLAR
    ensure_column(
        conn,
        "users",
        "money_balance",
        "REAL DEFAULT 0"
    )

    ensure_column(
        conn,
        "users",
        "premium_1m",
        "INTEGER DEFAULT 0"
    )

    ensure_column(
        conn,
        "users",
        "premium_3m",
        "INTEGER DEFAULT 0"
    )

    # To'lovlar
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

    # Umumiy buyurtmalar
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

    # Pul yechish
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

    if conn.execute(
        "SELECT 1 FROM sponsor_settings WHERE id=1"
    ).fetchone() is None:

        conn.execute("""
            INSERT INTO sponsor_settings
            (id, active, disabled_at)
            VALUES (1, 1, NULL)
        """)

    conn.execute(
        "DELETE FROM sponsors WHERE channel != ?",
        (SPONSOR_CHANNEL,)
    )

    conn.execute("""
        INSERT OR REPLACE INTO sponsors(channel, url)
        VALUES (?, ?)
    """, (
        SPONSOR_CHANNEL,
        SPONSOR_URL,
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

    existing = conn.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    is_new = existing is None

    if is_new:

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
                referral_rewarded,
                money_balance,
                premium_1m,
                premium_3m
            )
            VALUES (
                ?, ?, 0, 0, 0, 0,
                NULL, ?, 0, 0,
                0, 0, 0
            )
        """, (
            user_id,
            username or "",
            now_iso(),
        ))

        conn.execute("""
            UPDATE bot_stats
            SET total_users = total_users + 1
            WHERE id=1
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
            user_id,
        ))

    conn.commit()

    total = conn.execute(
        "SELECT total_users FROM bot_stats WHERE id=1"
    ).fetchone()["total_users"]

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

async def is_subscribed(bot, user_id, channel):

    try:

        member = await bot.get_chat_member(
            chat_id=channel,
            user_id=user_id,
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except TelegramError:

        return False


async def check_sponsor(bot, user_id):

    return await is_subscribed(
        bot,
        user_id,
        SPONSOR_CHANNEL
    )


def sponsor_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 KANALGA OBUNA BO‘LISH",
                url=SPONSOR_URL
            )
        ],
        [
            InlineKeyboardButton(
                "✅ TASDIQLASH",
                callback_data="check_sponsor"
            )
        ]
    ])


async def show_sponsor(update):

    text = (
        "🔒 <b>BOTDAN FOYDALANISH UCHUN</b>\n\n"
        "📢 Avval kanalga obuna bo‘ling:\n\n"
        "⭐ @premyumstarstekin\n\n"
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
# ASOSIY MENU
# =========================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                "💰 PUL ISHLASH",
                "⭐ STARS ISHLASH"
            ],
            [
                "💎 PREMIUM ISHLASH",
                "📱 NOMER OLISH"
            ],
            [
                "📈 PROMO XIZMATLARI",
                "🛍 DO‘KON"
            ],
            [
                "💳 HISOB TO‘LDIRISH",
                "👤 MENING HISOBIM"
            ],
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

    # REFERAL
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

            already = conn.execute("""
                SELECT referred_by
                FROM users
                WHERE id=?
            """, (user.id,)).fetchone()

            if already and already["referred_by"] is None:

                conn.execute("""
                    UPDATE users
                    SET referred_by=?
                    WHERE id=?
                """, (
                    referrer_id,
                    user.id
                ))

                # STARS
                conn.execute("""
                    UPDATE users
                    SET referrals=referrals+1,
                        points=points+?,
                        money_balance=money_balance+?
                    WHERE id=?
                """, (
                    REFERRAL_STARS,
                    REFERRAL_MONEY,
                    referrer_id
                ))

            conn.commit()
            conn.close()

    if not await check_sponsor(
        context.bot,
        user.id
    ):

        await show_sponsor(update)
        return

    await update.message.reply_text(
        "🎉 <b>TEKIN STARS BOT</b>\n\n"
        "Xush kelibsiz!\n\n"
        "Kerakli bo‘limni tanlang.",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# PUL ISHLASH
# =========================================================

async def money_work(update, context):

    user = get_user(update.effective_user.id)

    referrals = int(user["referrals"] or 0)
    money = float(user["money_balance"] or 0)

    text = (
        "💰 <b>PUL ISHLASH</b>\n\n"
        f"💵 Virtual balans: <b>{money:,.0f} so‘m</b>\n"
        f"👥 Referallar: <b>{referrals}</b>\n\n"
        "👤 Har bir referal: <b>+500 so‘m</b>\n\n"
        "Pul balansingiz Stars balansidan alohida."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="referral"
            )
        ],
        [
            InlineKeyboardButton(
                "💸 PUL YECHISH",
                callback_data="money_withdraw"
            )
        ]
    ])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# STARS ISHLASH
# =========================================================

async def stars_work(update, context):

    user = get_user(update.effective_user.id)

    await update.message.reply_text(
        "⭐ <b>STARS ISHLASH</b>\n\n"
        f"⭐ Stars balans: <b>{float(user['points'] or 0):.2f}</b>\n"
        f"👥 Referallar: <b>{int(user['referrals'] or 0)}</b>\n\n"
        f"👤 Har bir referal: <b>+{REFERRAL_STARS:g} ⭐</b>\n\n"
        "Stars balansingiz pul balansidan alohida.",
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

    referrals = int(user["referrals"] or 0)

    one = int(user["premium_1m"] or 0)
    three = int(user["premium_3m"] or 0)

    text = (
        "💎 <b>PREMIUM ISHLASH</b>\n\n"
        f"👥 Referallar: <b>{referrals}</b>\n\n"
        "🎁 25 referal → 1 oy Premium\n"
        "🎁 70 referal → 3 oy Premium\n\n"
        f"1 oy mukofot: {'✅ Olingan' if one else '⏳ Kutilmoqda'}\n"
        f"3 oy mukofot: {'✅ Olingan' if three else '⏳ Kutilmoqda'}"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# REFERAL
# =========================================================

async def referral(update, context):

    user_id = update.effective_user.id

    user = get_user(user_id)

    me = await context.bot.get_me()

    referrals = int(user["referrals"] or 0)

    link = f"https://t.me/{me.username}?start={user_id}"

    await update.effective_message.reply_text(
        "👥 <b>REFERAL</b>\n\n"
        f"👤 Referallar: <b>{referrals}</b>\n"
        f"⭐ Har biri: <b>+{REFERRAL_STARS:g} ⭐</b>\n"
        f"💰 Har biri: <b>+{REFERRAL_MONEY:,.0f} so‘m</b>\n\n"
        f"🔗 Referal linkingiz:\n"
        f"<code>{link}</code>",
        parse_mode="HTML"
    )


# =========================================================
# NOMER OLISH
# =========================================================

NUMBERS = {
    "🇧🇩 Bangladesh": 6000,
    "🇺🇸 USA": 6000,
    "🇮🇳 India": 6000,
    "🇮🇩 Indonesia": 6000,
    "🇳🇬 Nigeria": 6000,
    "🇪🇹 Ethiopia": 6000,
    "🇲🇲 Myanmar": 6000,
    "🇺🇿 Uzbekistan": 12000,
}


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
        "Kerakli davlatni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def number_country(update, context, country):

    price = NUMBERS.get(country)

    if not price:
        return

    await update.callback_query.edit_message_text(
        f"📱 <b>{country}</b>\n\n"
        f"💰 Narx: <b>{price:,} so‘m</b>\n\n"
        "Buyurtma berish uchun tugmani bosing.",
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
# PROMO XIZMATLARI
# =========================================================

PROMO = {
    "Telegram": {
        "1K": 5000,
        "10K": 40000,
        "100K": 100000,
    },
    "TikTok": {
        "1K": 15000,
        "10K": 75000,
        "100K": 250000,
    },
    "YouTube": {
        "1K": 15000,
        "10K": 75000,
        "100K": 250000,
    },
    "Instagram": {
        "1K": 15000,
        "10K": 75000,
        "100K": 250000,
    },
}


async def promo_menu(update, context):

    buttons = []

    for platform in PROMO:

        buttons.append([
            InlineKeyboardButton(
                f"📈 {platform}",
                callback_data=f"promo_platform:{platform}"
            )
        ])

    await update.message.reply_text(
        "📈 <b>PROMO XIZMATLARI</b>\n\n"
        "Platformani tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def promo_platform(update, context, platform):

    buttons = []

    for quantity, price in PROMO[platform].items():

        buttons.append([
            InlineKeyboardButton(
                f"{quantity} — {price:,} so‘m",
                callback_data=f"promo:{platform}:{quantity}"
            )
        ])

    await update.callback_query.edit_message_text(
        f"📈 <b>{platform}</b>\n\n"
        "Miqdorni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# =========================================================
# DO‘KON
# =========================================================

async def shop(update, context):

    await update.message.reply_text(
        "🛍 <b>DO‘KON</b>\n\n"
        "Kerakli xizmatni tanlang:",
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

    prices = [
        ("50 ⭐", 10999),
        ("100 ⭐", 22500),
        ("200 ⭐", 44000),
        ("500 ⭐", 99500),
        ("1000 ⭐", 199000),
    ]

    buttons = []

    for stars, price in prices:

        buttons.append([
            InlineKeyboardButton(
                f"{stars} — {price:,} so‘m",
                callback_data=f"buy_stars:{stars.split()[0]}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✏️ BOSHQA MIQDOR",
            callback_data="custom_stars"
        )
    ])

    await update.callback_query.edit_message_text(
        "⭐ <b>STARS SOTIB OLISH</b>\n\n"
        "Miqdorni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def shop_premium(update, context):

    buttons = [
        [
            InlineKeyboardButton(
                "1 oy — 45,000 so‘m",
                callback_data="buy_premium:1"
            )
        ],
        [
            InlineKeyboardButton(
                "3 oy — 120,000 so‘m",
                callback_data="buy_premium:3"
            )
        ],
        [
            InlineKeyboardButton(
                "6 oy — 200,000 so‘m",
                callback_data="buy_premium:6"
            )
        ],
        [
            InlineKeyboardButton(
                "12 oy — 299,000 so‘m",
                callback_data="buy_premium:12"
            )
        ]
    ]

    await update.callback_query.edit_message_text(
        "💎 <b>PREMIUM SOTIB OLISH</b>\n\n"
        "Muddatni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# =========================================================
# BUYURTMA TARGET
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

    card = PAYMENT_CARD or "GitHub Secrets → PAYMENT_CARD"

    await update.message.reply_text(
        "💳 <b>HISOB TO‘LDIRISH</b>\n\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"👤 Karta egasi: <b>{PAYMENT_OWNER}</b>\n\n"
        "To‘lov qilgach:\n"
        "1️⃣ <b>💸 TO‘LOV QILDIM</b> ni bosing\n"
        "2️⃣ Chek rasmini yuboring\n"
        "3️⃣ Chek adminga yuboriladi\n"
        "4️⃣ Admin qo‘lda tekshiradi",
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

    context.user_data["waiting_receipt"] = True

    await update.callback_query.edit_message_text(
        "📸 <b>CHEKNI YUBORING</b>\n\n"
        "To‘lov chekini rasm qilib yuboring.",
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

    user = update.effective_user

    photo = update.message.photo[-1]

    conn = db()

    cur = conn.execute("""
        INSERT INTO payment_requests
        (
            user_id,
            amount,
            receipt_file_id,
            status,
            created_at
        )
        VALUES (?, 0, ?, 'pending', ?)
    """, (
        user.id,
        photo.file_id,
        now_iso()
    ))

    request_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data["waiting_receipt"] = False

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

    username = (
        f"@{user.username}"
        if user.username
        else "Username yo‘q"
    )

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo.file_id,
        caption=(
            "💳 <b>YANGI TO‘LOV CHEKI</b>\n\n"
            f"🆔 So‘rov: <code>#{request_id}</code>\n"
            f"👤 User: {username}\n"
            f"🆔 ID: <code>{user.id}</code>\n\n"
            "⚠️ Chekni tekshiring."
        ),
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await update.message.reply_text(
        "✅ <b>CHEK YUBORILDI</b>\n\n"
        "Chekingiz adminga yuborildi.\n"
        "Admin tekshirganidan keyin natija chiqadi.",
        parse_mode="HTML"
    )

    return True


# =========================================================
# MENING HISOBIM
# =========================================================

async def my_account(update, context):

    user = get_user(update.effective_user.id)

    money = float(user["money_balance"] or 0)
    stars = float(user["points"] or 0)
    refs = int(user["referrals"] or 0)

    await update.message.reply_text(
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"💰 Pul: <b>{money:,.0f} so‘m</b>\n"
        f"⭐ Stars: <b>{stars:.2f}</b>\n"
        f"👥 Referallar: <b>{refs}</b>\n\n"
        f"💎 Premium 1 oy: "
        f"{'✅' if user['premium_1m'] else '❌'}\n"
        f"💎 Premium 3 oy: "
        f"{'✅' if user['premium_3m'] else '❌'}",
        parse_mode="HTML"
    )


# =========================================================
# PUL YECHISH
# =========================================================

async def money_withdraw(update, context):

    user = get_user(update.effective_user.id)

    money = float(user["money_balance"] or 0)

    if money < MIN_MONEY_WITHDRAW:

        await update.effective_message.reply_text(
            "💸 <b>PUL YECHISH</b>\n\n"
            f"Minimal: <b>{MIN_MONEY_WITHDRAW:,} so‘m</b>\n"
            f"Sizda: <b>{money:,.0f} so‘m</b>",
            parse_mode="HTML"
        )

        return

    context.user_data["money_withdraw"] = True

    await update.effective_message.reply_text(
        "💸 <b>PUL YECHISH</b>\n\n"
        f"Balans: <b>{money:,.0f} so‘m</b>\n\n"
        "Qancha yechmoqchisiz?\n"
        "Masalan: <code>10000</code>",
        parse_mode="HTML"
    )


async def process_money_withdraw(update, context):

    if not context.user_data.get("money_withdraw"):
        return

    try:
        amount = float(
            update.message.text.replace(",", "").strip()
        )
    except Exception:

        await update.message.reply_text(
            "❌ Faqat raqam kiriting."
        )

        return

    context.user_data.pop("money_withdraw", None)

    user_id = update.effective_user.id

    user = get_user(user_id)

    balance = float(user["money_balance"] or 0)

    if amount < MIN_MONEY_WITHDRAW:

        await update.message.reply_text(
            f"❌ Minimal {MIN_MONEY_WITHDRAW:,} so‘m."
        )

        return

    if amount > balance:

        await update.message.reply_text(
            "❌ Balansingiz yetarli emas."
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

        await update.message.reply_text(
            "⏳ Sizda pending so‘rov mavjud."
        )

        return

    cur = conn.execute("""
        INSERT INTO money_withdrawals
        (
            user_id,
            amount,
            status,
            created_at
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

    await update.message.reply_text(
        "✅ <b>SO‘ROV YUBORILDI</b>\n\n"
        f"💰 Miqdor: <b>{amount:,.0f} so‘m</b>\n"
        "⏳ Holat: <b>Pending</b>",
        parse_mode="HTML"
    )

    await context.bot.send_message(
        ADMIN_ID,
        "💰 <b>YANGI PUL YECHISH</b>\n\n"
        f"🆔 User: <code>{user_id}</code>\n"
        f"💰 Miqdor: <b>{amount:,.0f} so‘m</b>\n"
        f"📌 ID: <code>{withdrawal_id}</code>",
        parse_mode="HTML"
    )


# =========================================================
# CALLBACK
# =========================================================

async def callbacks(update, context):

    query = update.callback_query

    data = query.data or ""

    user_id = query.from_user.id

    await query.answer()

    # HOMIY
    if data == "check_sponsor":

        if not await check_sponsor(
            context.bot,
            user_id
        ):

            await query.answer(
                "❌ Avval kanalga obuna bo‘ling!",
                show_alert=True
            )

            return

        await query.edit_message_text(
            "✅ <b>OBUNA TASDIQLANDI!</b>",
            parse_mode="HTML"
        )

        await query.message.reply_text(
            "🏠 <b>TEKIN STARS BOT</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        return

    # TO'LOV
    if data == "payment_done":

        await payment_done(update, context)

        return

    # PAYMENT APPROVE
    if data.startswith("payment_approve:"):

        if user_id != ADMIN_ID:
            return

        request_id = int(
            data.split(":")[1]
        )

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM payment_requests
            WHERE id=?
        """, (request_id,)).fetchone()

        if not row or row["status"] != "pending":

            conn.close()

            await query.answer(
                "Bu so‘rov allaqachon ko‘rilgan.",
                show_alert=True
            )

            return

        conn.execute("""
            UPDATE payment_requests
            SET status='approved',
                processed_at=?
            WHERE id=?
        """, (
            now_iso(),
            request_id
        ))

        conn.commit()
        conn.close()

        await query.edit_message_caption(
            caption=(
                query.message.caption or
                ""
            ) + "\n\n✅ <b>TASDIQLANDI</b>",
            parse_mode="HTML"
        )

        await context.bot.send_message(
            row["user_id"],
            "✅ <b>TO‘LOV TASDIQLANDI</b>\n\n"
            "Admin chekingizni tasdiqladi.",
            parse_mode="HTML"
        )

        return

    # PAYMENT REJECT
    if data.startswith("payment_reject:"):

        if user_id != ADMIN_ID:
            return

        request_id = int(
            data.split(":")[1]
        )

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM payment_requests
            WHERE id=?
        """, (request_id,)).fetchone()

        if not row or row["status"] != "pending":

            conn.close()

            await query.answer(
                "Bu so‘rov allaqachon ko‘rilgan.",
                show_alert=True
            )

            return

        conn.execute("""
            UPDATE payment_requests
            SET status='rejected',
                processed_at=?
            WHERE id=?
        """, (
            now_iso(),
            request_id
        ))

        conn.commit()
        conn.close()

        await query.edit_message_caption(
            caption=(
                query.message.caption or
                ""
            ) + "\n\n❌ <b>RAD ETILDI</b>",
            parse_mode="HTML"
        )

        await context.bot.send_message(
            row["user_id"],
            "❌ <b>TO‘LOV TASDIQLANMADI</b>\n\n"
            "Chek admin tomonidan rad etildi.",
            parse_mode="HTML"
        )

        return

    # REFERAL
    if data == "referral":

        await referral(update, context)

        return

    # MONEY WITHDRAW
    if data == "money_withdraw":

        await money_withdraw(update, context)

        return

    # NUMBER
    if data.startswith("number:"):

        country = data.split(":", 1)[1]

        await number_country(
            update,
            context,
            country
        )

        return

    # PROMO PLATFORM
    if data.startswith("promo_platform:"):

        platform = data.split(":", 1)[1]

        await promo_platform(
            update,
            context,
            platform
        )

        return

    # PROMO ORDER
    if data.startswith("promo:"):

        parts = data.split(":")

        platform = parts[1]
        quantity = parts[2]

        price = PROMO[platform][quantity]

        conn = db()

        cur = conn.execute("""
            INSERT INTO service_orders
            (
                user_id,
                category,
                item,
                price,
                target,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, '', 'pending', ?)
        """, (
            user_id,
            "promo",
            f"{platform} {quantity}",
            price,
            now_iso()
        ))

        order_id = cur.lastrowid

        conn.commit()
        conn.close()

        await query.edit_message_text(
            "✅ <b>BUYURTMA QABUL QILINDI</b>\n\n"
            f"📈 Xizmat: <b>{platform}</b>\n"
            f"📊 Miqdor: <b>{quantity}</b>\n"
            f"💰 Narx: <b>{price:,} so‘m</b>\n"
            f"🆔 Buyurtma: <code>#{order_id}</code>\n\n"
            "Admin sizdan kerakli linkni oladi.",
            parse_mode="HTML"
        )

        await context.bot.send_message(
            ADMIN_ID,
            "📈 <b>YANGI PROMO BUYURTMA</b>\n\n"
            f"🆔 Buyurtma: <code>#{order_id}</code>\n"
            f"👤 User: <code>{user_id}</code>\n"
            f"📈 Xizmat: <b>{platform}</b>\n"
            f"📊 Miqdor: <b>{quantity}</b>\n"
            f"💰 Narx: <b>{price:,} so‘m</b>",
            parse_mode="HTML"
        )

        return

    # SHOP
    if data == "shop_stars":

        await shop_stars(update, context)

        return

    if data == "shop_premium":

        await shop_premium(update, context)

        return

    # STARS BUY
    if data.startswith("buy_stars:"):

        stars = int(
            data.split(":")[1]
        )

        prices = {
            50: 10999,
            100: 22500,
            200: 44000,
            500: 99500,
            1000: 199000
        }

        price = prices[stars]

        context.user_data["pending_order"] = {
            "category": "stars",
            "item": f"{stars} Stars",
            "price": price
        }

        await target_menu(update, context)

        return

    # PREMIUM BUY
    if data.startswith("buy_premium:"):

        months = int(
            data.split(":")[1]
        )

        prices = {
            1: 45000,
            3: 120000,
            6: 200000,
            12: 299000
        }

        price = prices[months]

        context.user_data["pending_order"] = {
            "category": "premium",
            "item": f"{months} oy Premium",
            "price": price
        }

        await target_menu(update, context)

        return

    # TARGET
    if data == "target:self":

        order = context.user_data.get(
            "pending_order"
        )

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
            "Masalan:\n"
            "<code>@username</code>",
            parse_mode="HTML"
        )

        return


# =========================================================
# ORDER YARATISH
# =========================================================

async def create_order(update, context, order, target):

    user_id = update.effective_user.id

    conn = db()

    cur = conn.execute("""
        INSERT INTO service_orders
        (
            user_id,
            category,
            item,
            price,
            target,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    """, (
        user_id,
        order["category"],
        order["item"],
        order["price"],
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

    await update.callback_query.edit_message_text(
        "✅ <b>BUYURTMA YUBORILDI</b>\n\n"
        f"🛍 Xizmat: <b>{order['item']}</b>\n"
        f"💰 Narx: <b>{order['price']:,} so‘m</b>\n"
        f"👤 Qabul qiluvchi: <b>{target}</b>\n"
        f"🆔 Buyurtma: <code>#{order_id}</code>\n\n"
        "Buyurtma admin panelga yuborildi.",
        parse_mode="HTML"
    )

    await context.bot.send_message(
        ADMIN_ID,
        "🛍 <b>YANGI BUYURTMA</b>\n\n"
        f"🆔 ID: <code>#{order_id}</code>\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"🛍 Xizmat: <b>{order['item']}</b>\n"
        f"💰 Narx: <b>{order['price']:,} so‘m</b>\n"
        f"🎯 Kimga: <b>{target}</b>",
        parse_mode="HTML"
    )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(update, context):

    if not update.effective_user:
        return

    user_id = update.effective_user.id

    # CHEK
    if (
        update.message
        and update.message.photo
        and context.user_data.get("waiting_receipt")
    ):

        await receive_receipt(
            update,
            context
        )

        return

    # PUL YECHISH
    if (
        context.user_data.get("money_withdraw")
        and update.message
        and update.message.text
    ):

        await process_money_withdraw(
            update,
            context
        )

        return

    # BOSHQA USER
    if context.user_data.get("waiting_target"):

        if not update.message or not update.message.text:
            return

        target = update.message.text.strip()

        order = context.user_data.get(
            "pending_order"
        )

        context.user_data.pop(
            "waiting_target",
            None
        )

        if not order:
            return

        conn = db()

        cur = conn.execute("""
            INSERT INTO service_orders
            (
                user_id,
                category,
                item,
                price,
                target,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """, (
            user_id,
            order["category"],
            order["item"],
            order["price"],
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
            f"💰 {order['price']:,} so‘m\n"
            f"👤 {target}\n"
            f"🆔 #{order_id}",
            parse_mode="HTML"
        )

        await context.bot.send_message(
            ADMIN_ID,
            "🛍 <b>YANGI BUYURTMA</b>\n\n"
            f"🆔 #{order_id}\n"
            f"👤 User: <code>{user_id}</code>\n"
            f"🛍 {order['item']}\n"
            f"💰 {order['price']:,} so‘m\n"
            f"🎯 {target}",
            parse_mode="HTML"
        )

        return

    # HOMIY
    if not await check_sponsor(
        context.bot,
        user_id
    ):

        await show_sponsor(update)

        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text == "💰 PUL ISHLASH":

        await money_work(update, context)

    elif text == "⭐ STARS ISHLASH":

        await stars_work(update, context)

    elif text == "💎 PREMIUM ISHLASH":

        await premium_work(update, context)

    elif text == "📱 NOMER OLISH":

        await numbers_menu(update, context)

    elif text == "📈 PROMO XIZMATLARI":

        await promo_menu(update, context)

    elif text == "🛍 DO‘KON":

        await shop(update, context)

    elif text == "💳 HISOB TO‘LDIRISH":

        await payment_menu(update, context)

    elif text == "👤 MENING HISOBIM":

        await my_account(update, context)


# =========================================================
# ADMIN
# =========================================================

async def admin_command(update, context):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ Ruxsat yo‘q."
        )

        return

    await update.message.reply_text(
        "👑 <b>ADMIN PANEL</b>\n\n"
        "📊 Statistika\n"
        "💳 To‘lov cheklarini yuqoridagi xabarlardan tasdiqlashingiz mumkin.",
        parse_mode="HTML"
    )


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
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callbacks
        )
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
        "TEKIN STARS BOT ishga tushdi."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
