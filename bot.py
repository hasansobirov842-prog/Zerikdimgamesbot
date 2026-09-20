import os
import sqlite3
import logging
import asyncio
import html
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

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8679536810"))

DB_FILE = "zerikdim.db"

PAYMENT_CARD = "5614681008971867"
PAYMENT_OWNER = "RAKHMONOVA/O"

SPONSOR_CHANNEL = "@premyumstarstekin"
SPONSOR_URL = "https://t.me/premyumstarstekin"

REFERRAL_STARS = 9.0
REFERRAL_BONUS = 500.0

MIN_WITHDRAW = 10000
MIN_TOPUP = 1000

# =========================================================
# PRODUCTS
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

NAKRUTKA = {
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

STARS_PRICES = {
    50: 10999,
    100: 22500,
    200: 44000,
    500: 99500,
    1000: 199000,
}

PREMIUM_PRICES = {
    "1 oy": 45000,
    "3 oy": 120000,
    "6 oy": 200000,
    "12 oy": 299000,
}

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================================================
# DATABASE
# =========================================================


def db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_column(conn, table, column, definition):
    cols = [x["name"] for x in conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            reward REAL,
            url TEXT,
            channel TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_id INTEGER,
            created_at TEXT,
            UNIQUE(user_id, task_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_stats (
            id INTEGER PRIMARY KEY,
            started_at TEXT,
            total_users INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsor_settings (
            id INTEGER PRIMARY KEY,
            active INTEGER DEFAULT 1,
            disabled_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT UNIQUE,
            url TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            receipt_file_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS service_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            item TEXT,
            price REAL,
            target TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT,
            link TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS money_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        )
    """)

    # Existing DB ga tegmaydi.
    ensure_column(conn, "users", "money_balance", "REAL DEFAULT 0")
    ensure_column(conn, "users", "premium_1m", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "premium_3m", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "real_balance", "REAL DEFAULT 0")
    ensure_column(conn, "users", "bonus_balance", "REAL DEFAULT 0")
    ensure_column(conn, "users", "total_deposited", "REAL DEFAULT 0")
    ensure_column(conn, "users", "total_spent", "REAL DEFAULT 0")

    ensure_column(
        conn,
        "money_withdrawals",
        "reserved",
        "INTEGER DEFAULT 1",
    )

    ensure_column(
        conn,
        "service_orders",
        "balance_charged",
        "INTEGER DEFAULT 1",
    )

    cur.execute("""
        INSERT OR IGNORE INTO bot_stats
        (id, started_at, total_users)
        VALUES (1, ?, 0)
    """, (now(),))

    current_users = cur.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    cur.execute("""
        UPDATE bot_stats
        SET total_users =
            CASE
                WHEN total_users < ? THEN ?
                ELSE total_users
            END
        WHERE id=1
    """, (current_users, current_users))

    cur.execute("""
        INSERT OR IGNORE INTO sponsor_settings
        (id, active)
        VALUES (1, 1)
    """)

    cur.execute("""
        INSERT OR IGNORE INTO sponsors
        (channel, url)
        VALUES (?, ?)
    """, (SPONSOR_CHANNEL, SPONSOR_URL))

    conn.commit()
    conn.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def get_user(user_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    return row


def add_user(user_id, username):
    conn = db()
    cur = conn.cursor()

    row = cur.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,),
    ).fetchone()

    if row is None:
        cur.execute("""
            INSERT INTO users
            (id, username, points, games, wins, referrals,
             referred_by, last_seen, blocked, referral_rewarded,
             money_balance, premium_1m, premium_3m,
             real_balance, bonus_balance,
             total_deposited, total_spent)
            VALUES (?, ?, 0, 0, 0, 0, NULL, ?, 0, 0,
                    0, 0, 0, 0, 0, 0, 0)
        """, (user_id, username, now()))

        cur.execute("""
            UPDATE bot_stats
            SET total_users = total_users + 1
            WHERE id=1
        """)
    else:
        cur.execute("""
            UPDATE users
            SET username=?, last_seen=?
            WHERE id=?
        """, (username, now(), user_id))

    conn.commit()
    conn.close()


def money_format(value):
    try:
        return f"{float(value):,.0f}".replace(",", " ")
    except Exception:
        return "0"


# =========================================================
# SPONSORS
# =========================================================


def get_sponsors():
    conn = db()
    rows = conn.execute(
        "SELECT channel,url FROM sponsors ORDER BY id"
    ).fetchall()
    conn.close()

    if not rows:
        return [(SPONSOR_CHANNEL, SPONSOR_URL)]

    return [(x["channel"], x["url"]) for x in rows]


async def is_subscribed(bot, user_id, channel):
    try:
        member = await bot.get_chat_member(channel, user_id)

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception:
        return False


async def check_all_sponsors(bot, user_id):
    sponsors = get_sponsors()

    for channel, _ in sponsors:
        if not await is_subscribed(bot, user_id, channel):
            return False

    return True


async def show_sponsor(update):
    buttons = []

    for channel, url in get_sponsors():
        buttons.append([
            InlineKeyboardButton(
                f"📢 {channel}",
                url=url,
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✅ OBUNANI TEKSHIRISH",
            callback_data="sponsor_check",
        )
    ])

    text = (
        "🔒 <b>BOTDAN FOYDALANISH UCHUN</b>\n\n"
        "📢 Quyidagi kanalga obuna bo‘ling.\n"
        "Keyin <b>OBUNANI TEKSHIRISH</b> tugmasini bosing."
    )

    markup = InlineKeyboardMarkup(buttons)

    if update.callback_query:
        await update.callback_query.message.edit_text(
            text,
            reply_markup=markup,
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML",
        )


# =========================================================
# KEYBOARDS
# =========================================================


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["💰 PUL ISHLASH", "⭐ STARS ISHLASH"],
            ["💎 PREMIUM ISHLASH", "📱 NOMER OLISH"],
            ["📈 NAKRUTKA", "🛍 DO‘KON"],
            ["💳 HISOB TO‘LDIRISH", "👤 MENING HISOBIM"],
        ],
        resize_keyboard=True,
    )


def back_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬅️ ORQAGA",
                callback_data="back_main",
            )
        ]
    ])


# =========================================================
# START
# =========================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return

    user = update.effective_user
    add_user(user.id, user.username or "")

    args = context.args

    if args:
        try:
            ref_id = int(args[0])

            if ref_id != user.id:
                conn = db()

                current = conn.execute(
                    "SELECT referred_by FROM users WHERE id=?",
                    (user.id,),
                ).fetchone()

                if current and current["referred_by"] is None:
                    ref = conn.execute(
                        "SELECT * FROM users WHERE id=?",
                        (ref_id,),
                    ).fetchone()

                    if ref:
                        conn.execute("""
                            UPDATE users
                            SET referred_by=?
                            WHERE id=? AND referred_by IS NULL
                        """, (ref_id, user.id))

                        conn.execute("""
                            UPDATE users
                            SET referrals=referrals+1,
                                points=points+?,
                                bonus_balance=bonus_balance+?,
                                money_balance=money_balance+?
                            WHERE id=?
                        """, (
                            REFERRAL_STARS,
                            REFERRAL_BONUS,
                            REFERRAL_BONUS,
                            ref_id,
                        ))

                        new_ref = conn.execute(
                            "SELECT referrals,premium_1m,premium_3m "
                            "FROM users WHERE id=?",
                            (ref_id,),
                        ).fetchone()

                        if new_ref:
                            if (
                                new_ref["referrals"] >= 25
                                and not new_ref["premium_1m"]
                            ):
                                conn.execute("""
                                    UPDATE users
                                    SET premium_1m=1
                                    WHERE id=?
                                """, (ref_id,))

                            if (
                                new_ref["referrals"] >= 70
                                and not new_ref["premium_3m"]
                            ):
                                conn.execute("""
                                    UPDATE users
                                    SET premium_3m=1
                                    WHERE id=?
                                """, (ref_id,))

                        conn.commit()

                        try:
                            await context.bot.send_message(
                                ref_id,
                                "🎉 <b>Yangi referal!</b>\n\n"
                                f"⭐ +{REFERRAL_STARS:g} Stars\n"
                                f"💰 +{money_format(REFERRAL_BONUS)} so‘m\n\n"
                                "Referal tizimi orqali davom eting!",
                                parse_mode="HTML",
                            )

                            if new_ref:
                                if (
                                    new_ref["referrals"] >= 25
                                    and not new_ref["premium_1m"]
                                ):
                                    await context.bot.send_message(
                                        ref_id,
                                        "💎 <b>25 ta referal!</b>\n"
                                        "Sizga 1 oylik Premium berildi.",
                                        parse_mode="HTML",
                                    )

                                if (
                                    new_ref["referrals"] >= 70
                                    and not new_ref["premium_3m"]
                                ):
                                    await context.bot.send_message(
                                        ref_id,
                                        "💎 <b>70 ta referal!</b>\n"
                                        "Sizga 3 oylik Premium berildi.",
                                        parse_mode="HTML",
                                    )

                        except Exception:
                            pass

                conn.close()

            context.args = []

        except Exception:
            pass

    if not await check_all_sponsors(
        context.bot,
        user.id,
    ):
        await show_sponsor(update)
        return

    await update.message.reply_text(
        "🔥 <b>TEKIN STARS BOT</b>\n\n"
        "⭐ Stars ishlang\n"
        "💰 Pul ishlang\n"
        "💎 Premium ishlang\n"
        "📱 Nomer oling\n"
        "📈 Nakrutka buyurtma qiling\n"
        "🛍 Do‘kondan xarid qiling\n\n"
        "👇 Kerakli bo‘limni tanlang:",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


# =========================================================
# WORK SECTIONS
# =========================================================


async def money_work(update):
    user = get_user(update.effective_user.id)

    referrals = user["referrals"] if user else 0
    bonus = user["bonus_balance"] if user else 0

    text = (
        "💰 <b>PUL ISHLASH</b>\n\n"
        "👥 Har bir referal:\n"
        f"⭐ +{REFERRAL_STARS:g} Stars\n"
        f"💰 +{money_format(REFERRAL_BONUS)} so‘m bonus\n\n"
        f"👥 Sizning referallaringiz: <b>{referrals}</b>\n"
        f"💵 Bonus balans: <b>{money_format(bonus)} so‘m</b>\n\n"
        f"💸 Minimal yechish: <b>{money_format(MIN_WITHDRAW)} so‘m</b>"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="referral",
            )
        ],
        [
            InlineKeyboardButton(
                "💸 PUL YECHISH",
                callback_data="money_withdraw",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ ORQAGA",
                callback_data="back_main",
            )
        ],
    ])

    await update.message.reply_text(
        text,
        reply_markup=markup,
        parse_mode="HTML",
    )


async def stars_work(update):
    user = get_user(update.effective_user.id)

    points = user["points"] if user else 0

    text = (
        "⭐ <b>STARS ISHLASH</b>\n\n"
        "👥 Referal olib Stars ishlang.\n"
        "🎁 Har bir referal uchun:\n"
        f"⭐ +{REFERRAL_STARS:g} Stars\n\n"
        f"⭐ Sizning Stars: <b>{points:g}</b>"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="referral",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ ORQAGA",
                callback_data="back_main",
            )
        ],
    ])

    await update.message.reply_text(
        text,
        reply_markup=markup,
        parse_mode="HTML",
    )


async def premium_work(update):
    user = get_user(update.effective_user.id)

    p1 = user["premium_1m"] if user else 0
    p3 = user["premium_3m"] if user else 0
    refs = user["referrals"] if user else 0

    text = (
        "💎 <b>PREMIUM ISHLASH</b>\n\n"
        "👥 25 ta referal → 💎 1 oy Premium\n"
        "👥 70 ta referal → 💎 3 oy Premium\n\n"
        f"👥 Referallar: <b>{refs}</b>\n"
        f"💎 1 oy Premium: <b>{'BOR' if p1 else 'YO‘Q'}</b>\n"
        f"💎 3 oy Premium: <b>{'BOR' if p3 else 'YO‘Q'}</b>"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="referral",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ ORQAGA",
                callback_data="back_main",
            )
        ],
    ])

    await update.message.reply_text(
        text,
        reply_markup=markup,
        parse_mode="HTML",
    )


async def referral(update, context=None):
    user = get_user(update.effective_user.id)

    refs = user["referrals"] if user else 0

    bot_username = context.bot.username

    link = f"https://t.me/{bot_username}?start={update.effective_user.id}"

    text = (
        "👥 <b>REFERAL TIZIMI</b>\n\n"
        f"🔗 Sizning havolangiz:\n<code>{link}</code>\n\n"
        f"👥 Referallar: <b>{refs}</b>\n"
        f"⭐ Har bir referal: +{REFERRAL_STARS:g} Stars\n"
        f"💰 Har bir referal: +{money_format(REFERRAL_BONUS)} so‘m\n\n"
        "📌 25 referal → 1 oy Premium\n"
        "📌 70 referal → 3 oy Premium"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


# =========================================================
# NUMBERS
# =========================================================


async def numbers_menu(update):
    buttons = []

    for country, price in NUMBERS.items():
        buttons.append([
            InlineKeyboardButton(
                f"{country} — {money_format(price)} so‘m",
                callback_data=f"number:{country}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ ORQAGA",
            callback_data="back_main",
        )
    ])

    await update.message.reply_text(
        "📱 <b>NOMER OLISH</b>\n\n"
        "Kerakli davlatni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def create_number_order(update, country):
    price = NUMBERS.get(country)

    if price is None:
        return

    user_id = update.effective_user.id
    user = get_user(user_id)

    if user["real_balance"] < price:
        await update.callback_query.message.reply_text(
            "❌ Balansingiz yetarli emas.\n\n"
            f"💰 Narx: {money_format(price)} so‘m\n"
            f"💳 Balans: {money_format(user['real_balance'])} so‘m",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💳 HISOB TO‘LDIRISH",
                        callback_data="payment_menu",
                    )
                ]
            ]),
        )
        return

    conn = db()

    result = conn.execute("""
        UPDATE users
        SET real_balance=real_balance-?,
            total_spent=total_spent+?
        WHERE id=? AND real_balance>=?
    """, (price, price, user_id, price))

    if result.rowcount != 1:
        conn.close()
        await update.callback_query.message.reply_text(
            "❌ Balans yetarli emas."
        )
        return

    conn.execute("""
        INSERT INTO service_orders
        (user_id, category, item, price, target,
         status, created_at, balance_charged)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, 1)
    """, (
        user_id,
        "Nomer",
        country,
        price,
        country,
        now(),
    ))

    conn.commit()
    conn.close()

    await update.callback_query.message.reply_text(
        "✅ <b>Buyurtma qabul qilindi!</b>\n\n"
        f"📱 Davlat: {html.escape(country)}\n"
        f"💰 Narx: {money_format(price)} so‘m\n\n"
        "⏳ Admin sizga nomer va kerakli ma'lumotni yuboradi.",
        parse_mode="HTML",
    )

    await send_order_to_admin(
        update.get_bot(),
        user_id,
        "Nomer",
        country,
        price,
        country,
    )


# =========================================================
# NAKRUTKA
# =========================================================


async def nakrutka_menu(update):
    buttons = []

    for platform in NAKRUTKA:
        buttons.append([
            InlineKeyboardButton(
                f"📈 {platform}",
                callback_data=f"nakplatform:{platform}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ ORQAGA",
            callback_data="back_main",
        )
    ])

    await update.message.reply_text(
        "📈 <b>NAKRUTKA XIZMATLARI</b>\n\n"
        "Platformani tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def nak_platform(query, platform):
    prices = NAKRUTKA.get(platform)

    if not prices:
        return

    buttons = []

    for qty, price in prices.items():
        buttons.append([
            InlineKeyboardButton(
                f"{qty} — {money_format(price)} so‘m",
                callback_data=f"nak:{platform}:{qty}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ ORQAGA",
            callback_data="back_main",
        )
    ])

    await query.message.edit_text(
        f"📈 <b>{html.escape(platform)}</b>\n\n"
        "Miqdorni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# =========================================================
# SHOP
# =========================================================


async def shop_menu(update):
    buttons = [
        [
            InlineKeyboardButton(
                "⭐ STARS",
                callback_data="shop_stars",
            )
        ],
        [
            InlineKeyboardButton(
                "💎 PREMIUM",
                callback_data="shop_premium",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ ORQAGA",
                callback_data="back_main",
            )
        ],
    ]

    await update.message.reply_text(
        "🛍 <b>DO‘KON</b>\n\n"
        "Kerakli mahsulotni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def shop_stars(query):
    buttons = []

    for amount, price in STARS_PRICES.items():
        buttons.append([
            InlineKeyboardButton(
                f"⭐ {amount} Stars — {money_format(price)} so‘m",
                callback_data=f"buy_stars:{amount}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ ORQAGA",
            callback_data="back_main",
        )
    ])

    await query.message.edit_text(
        "⭐ <b>STARS SOTIB OLISH</b>\n\n"
        "Miqdorni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def shop_premium(query):
    buttons = []

    for period, price in PREMIUM_PRICES.items():
        buttons.append([
            InlineKeyboardButton(
                f"💎 {period} — {money_format(price)} so‘m",
                callback_data=f"buy_premium:{period}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ ORQAGA",
            callback_data="back_main",
        )
    ])

    await query.message.edit_text(
        "💎 <b>PREMIUM SOTIB OLISH</b>\n\n"
        "Muddatni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def target_menu(query, kind, item):
    buttons = [
        [
            InlineKeyboardButton(
                "👤 O‘ZIM UCHUN",
                callback_data=f"target:self:{kind}:{item}",
            )
        ],
        [
            InlineKeyboardButton(
                "👥 BOSHQA USER UCHUN",
                callback_data=f"target:other:{kind}:{item}",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ ORQAGA",
                callback_data="back_main",
            )
        ],
    ]

    await query.message.edit_text(
        "👤 <b>Kim uchun?</b>\n\n"
        "Mahsulotni kimga yuborishni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# =========================================================
# PAYMENT
# =========================================================


async def payment_menu(update):
    text = (
        "💳 <b>HISOB TO‘LDIRISH</b>\n\n"
        "To‘lov tizimi: 💳 Karta orqali\n\n"
        f"💳 Karta: <code>{PAYMENT_CARD}</code>\n"
        f"🆔 ID: <code>{ADMIN_ID}</code>\n\n"
        "💳 <b>Hisobni to‘ldirish tartibi</b>\n\n"
        "1. Kartaga kerakli summani o‘tkazing\n"
        "2. «💸 TO‘LOV QILDIM» tugmasini bosing\n"
        "3. O‘tkazgan summani kiriting\n"
        "4. To‘lov chekini yuboring\n\n"
        "⏳ Tasdiqlash muddati: 5 daqiqa – 24 soat"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💸 TO‘LOV QILDIM",
                callback_data="payment_done",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ ORQAGA",
                callback_data="back_main",
            )
        ],
    ])

    if update.callback_query:
        await update.callback_query.message.edit_text(
            text,
            reply_markup=markup,
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML",
        )


async def payment_done(query, context):
    context.user_data["waiting_payment_amount"] = True

    await query.message.reply_text(
        "💵 <b>To‘lov miqdorini kiriting:</b>\n\n"
        f"Minimal: <b>{money_format(MIN_TOPUP)} so‘m</b>\n\n"
        "Masalan: <code>10000</code>",
        parse_mode="HTML",
    )


async def receive_receipt(update, context):
    user_id = update.effective_user.id

    amount = context.user_data.get("payment_amount")

    if not amount:
        return

    photo = update.message.photo

    if not photo:
        return

    file_id = photo[-1].file_id

    conn = db()

    cur = conn.execute("""
        INSERT INTO payment_requests
        (user_id, amount, receipt_file_id, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        user_id,
        amount,
        file_id,
        now(),
    ))

    payment_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data.pop("payment_amount", None)
    context.user_data.pop("waiting_receipt", None)

    user = get_user(user_id)

    username = (
        f"@{user['username']}"
        if user and user["username"]
        else "username yo‘q"
    )

    caption = (
        "💳 <b>YANGI TO‘LOV</b>\n\n"
        f"🆔 To‘lov ID: <code>{payment_id}</code>\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"👤 Username: {html.escape(username)}\n"
        f"💵 Summa: <b>{money_format(amount)} so‘m</b>\n\n"
        "Tasdiqlaysizmi?"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ TASDIQLASH",
                callback_data=f"payment_approve:{payment_id}",
            ),
            InlineKeyboardButton(
                "❌ RAD ETISH",
                callback_data=f"payment_reject:{payment_id}",
            ),
        ]
    ])

    try:
        await context.bot.send_photo(
            ADMIN_ID,
            file_id,
            caption=caption,
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception:
        pass

    await update.message.reply_text(
        "✅ <b>Chek qabul qilindi!</b>\n\n"
        f"💵 Summa: {money_format(amount)} so‘m\n"
        "⏳ Admin tasdiqlashini kuting.",
        parse_mode="HTML",
    )


# =========================================================
# ACCOUNT
# =========================================================


async def my_account(update):
    user = get_user(update.effective_user.id)

    if not user:
        return

    text = (
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"🆔 ID: <code>{user['id']}</code>\n"
        f"👤 Username: @{html.escape(user['username'] or 'yo‘q')}\n\n"
        f"⭐ Stars: <b>{user['points']:g}</b>\n"
        f"💳 Real balans: <b>{money_format(user['real_balance'])} so‘m</b>\n"
        f"💰 Bonus balans: <b>{money_format(user['bonus_balance'])} so‘m</b>\n"
        f"👥 Referallar: <b>{user['referrals']}</b>\n\n"
        f"💵 Jami kiritilgan: <b>{money_format(user['total_deposited'])} so‘m</b>\n"
        f"🛍 Jami sarflangan: <b>{money_format(user['total_spent'])} so‘m</b>"
    )

    await update.message.reply_text(
        text,
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )


# =========================================================
# MONEY WITHDRAW
# =========================================================


async def money_withdraw_menu(query, context):
    user = get_user(query.from_user.id)

    if not user:
        return

    if user["bonus_balance"] < MIN_WITHDRAW:
        await query.message.reply_text(
            "❌ Pul yechish uchun balans yetarli emas.\n\n"
            f"💰 Sizda: {money_format(user['bonus_balance'])} so‘m\n"
            f"💸 Minimum: {money_format(MIN_WITHDRAW)} so‘m"
        )
        return

    context.user_data["waiting_money_withdraw"] = True

    await query.message.reply_text(
        "💸 <b>PUL YECHISH</b>\n\n"
        f"Minimum: <b>{money_format(MIN_WITHDRAW)} so‘m</b>\n\n"
        "Qancha yechmoqchisiz? Summani kiriting:",
        parse_mode="HTML",
    )


async def process_money_withdraw(update, context):
    try:
        amount = float(
            update.message.text.replace(" ", "").replace(",", "")
        )
    except Exception:
        await update.message.reply_text(
            "❌ Summani to‘g‘ri kiriting."
        )
        return

    user_id = update.effective_user.id

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimum {money_format(MIN_WITHDRAW)} so‘m."
        )
        return

    conn = db()

    result = conn.execute("""
        UPDATE users
        SET bonus_balance=bonus_balance-?
        WHERE id=? AND bonus_balance>=?
    """, (amount, user_id, amount))

    if result.rowcount != 1:
        conn.close()
        await update.message.reply_text(
            "❌ Bonus balansingiz yetarli emas."
        )
        return

    cur = conn.execute("""
        INSERT INTO money_withdrawals
        (user_id, amount, status, created_at, reserved)
        VALUES (?, ?, 'pending', ?, 1)
    """, (
        user_id,
        amount,
        now(),
    ))

    withdrawal_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data.pop("waiting_money_withdraw", None)

    user = get_user(user_id)

    await update.message.reply_text(
        "✅ <b>Pul yechish so‘rovi yuborildi!</b>\n\n"
        f"💵 Summa: {money_format(amount)} so‘m\n"
        "⏳ Admin ko‘rib chiqadi.",
        parse_mode="HTML",
    )

    await context.bot.send_message(
        ADMIN_ID,
        "💸 <b>YANGI PUL YECHISH</b>\n\n"
        f"🆔 ID: <code>{withdrawal_id}</code>\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"💵 Summa: <b>{money_format(amount)} so‘m</b>\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ TASDIQLASH",
                    callback_data=f"money_approve:{withdrawal_id}",
                ),
                InlineKeyboardButton(
                    "❌ RAD ETISH",
                    callback_data=f"money_reject:{withdrawal_id}",
                ),
            ]
        ]),
        parse_mode="HTML",
    )


# =========================================================
# SERVICE ORDER
# =========================================================


async def send_order_to_admin(
    bot,
    user_id,
    category,
    item,
    price,
    target,
):
    user = get_user(user_id)

    username = (
        f"@{user['username']}"
        if user and user["username"]
        else "username yo‘q"
    )

    conn = db()
    row = conn.execute("""
        SELECT id
        FROM service_orders
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,)).fetchone()
    conn.close()

    order_id = row["id"] if row else 0

    text = (
        "🛍 <b>YANGI BUYURTMA</b>\n\n"
        f"🆔 Buyurtma: <code>{order_id}</code>\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"👤 Username: {html.escape(username)}\n"
        f"📦 Kategoriya: <b>{html.escape(category)}</b>\n"
        f"📌 Mahsulot: <b>{html.escape(str(item))}</b>\n"
        f"🎯 Target: <code>{html.escape(str(target))}</code>\n"
        f"💰 Narx: <b>{money_format(price)} so‘m</b>"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ BAJARILDI",
                callback_data=f"order_finish:{order_id}",
            ),
            InlineKeyboardButton(
                "❌ RAD ETISH",
                callback_data=f"order_reject:{order_id}",
            ),
        ]
    ])

    await bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=markup,
        parse_mode="HTML",
    )


async def create_order(
    query,
    context,
    category,
    item,
    price,
    target,
):
    user_id = query.from_user.id

    conn = db()

    result = conn.execute("""
        UPDATE users
        SET real_balance=real_balance-?,
            total_spent=total_spent+?
        WHERE id=? AND real_balance>=?
    """, (price, price, user_id, price))

    if result.rowcount != 1:
        conn.close()

        await query.message.reply_text(
            "❌ Real balansingiz yetarli emas.\n\n"
            f"💰 Narx: {money_format(price)} so‘m"
        )
        return

    cur = conn.execute("""
        INSERT INTO service_orders
        (user_id, category, item, price, target,
         status, created_at, balance_charged)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, 1)
    """, (
        user_id,
        category,
        item,
        price,
        target,
        now(),
    ))

    conn.commit()
    conn.close()

    await query.message.reply_text(
        "✅ <b>Buyurtma qabul qilindi!</b>\n\n"
        f"📦 {html.escape(str(item))}\n"
        f"💰 {money_format(price)} so‘m\n"
        "⏳ Admin tez orada bajaradi.",
        parse_mode="HTML",
    )

    await send_order_to_admin(
        context.bot,
        user_id,
        category,
        item,
        price,
        target,
    )


# =========================================================
# CALLBACKS
# =========================================================


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""

    # Sponsor
    if data == "sponsor_check":
        if await check_all_sponsors(
            context.bot,
            query.from_user.id,
        ):
            await query.answer("✅ Tasdiqlandi!")
            await query.message.edit_text(
                "✅ <b>Obuna tasdiqlandi!</b>\n\n"
                "Botdan foydalanishingiz mumkin.",
                parse_mode="HTML",
            )
            await query.message.reply_text(
                "🔥 <b>TEKIN STARS BOT</b>\n\n"
                "👇 Kerakli bo‘limni tanlang:",
                reply_markup=main_keyboard(),
                parse_mode="HTML",
            )
        else:
            await query.answer(
                "❌ Avval kanalga obuna bo‘ling!",
                show_alert=True,
            )
        return

    if data == "back_main":
        await query.answer()
        await query.message.reply_text(
            "🔥 <b>TEKIN STARS BOT</b>\n\n"
            "👇 Kerakli bo‘limni tanlang:",
            reply_markup=main_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == "payment_menu":
        await query.answer()
        await payment_menu(update)
        return

    if data == "payment_done":
        await query.answer()
        await payment_done(query, context)
        return

    # Payment approve
    if data.startswith("payment_approve:"):
        await query.answer()

        try:
            payment_id = int(data.split(":")[1])
        except Exception:
            return

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM payment_requests
            WHERE id=? AND status='pending'
        """, (payment_id,)).fetchone()

        if not row:
            conn.close()
            await query.message.reply_text(
                "⚠️ Bu to‘lov allaqachon ko‘rib chiqilgan."
            )
            return

        amount = float(row["amount"])
        user_id = row["user_id"]

        conn.execute("""
            UPDATE users
            SET real_balance=real_balance+?,
                total_deposited=total_deposited+?
            WHERE id=?
        """, (amount, amount, user_id))

        conn.execute("""
            UPDATE payment_requests
            SET status='approved',
                processed_at=?
            WHERE id=? AND status='pending'
        """, (now(), payment_id))

        conn.commit()
        conn.close()

        await query.message.edit_reply_markup(reply_markup=None)

        await query.message.reply_text(
            "✅ <b>TO‘LOV TASDIQLANDI</b>\n\n"
            f"💵 {money_format(amount)} so‘m\n"
            f"👤 User: <code>{user_id}</code>",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                user_id,
                "🎉 <b>To‘lovingiz tasdiqlandi!</b>\n\n"
                f"💳 Balansingizga +{money_format(amount)} so‘m qo‘shildi.",
                parse_mode="HTML",
            )
        except Exception:
            pass

        return

    # Payment reject
    if data.startswith("payment_reject:"):
        await query.answer()

        try:
            payment_id = int(data.split(":")[1])
        except Exception:
            return

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM payment_requests
            WHERE id=? AND status='pending'
        """, (payment_id,)).fetchone()

        if not row:
            conn.close()
            await query.message.reply_text(
                "⚠️ Bu to‘lov allaqachon ko‘rib chiqilgan."
            )
            return

        conn.execute("""
            UPDATE payment_requests
            SET status='rejected',
                processed_at=?
            WHERE id=? AND status='pending'
        """, (now(), payment_id))

        conn.commit()
        conn.close()

        await query.message.edit_reply_markup(reply_markup=None)

        await query.message.reply_text(
            "❌ <b>TO‘LOV RAD ETILDI</b>",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                row["user_id"],
                "❌ <b>To‘lovingiz rad etildi.</b>\n\n"
                "Chek yoki summa noto‘g‘ri bo‘lishi mumkin.",
                parse_mode="HTML",
            )
        except Exception:
            pass

        return

    # Money withdraw
    if data == "money_withdraw":
        await query.answer()
        await money_withdraw_menu(query, context)
        return

    if data == "referral":
        await query.answer()

        bot_username = context.bot.username
        user = get_user(query.from_user.id)

        link = (
            f"https://t.me/{bot_username}"
            f"?start={query.from_user.id}"
        )

        refs = user["referrals"] if user else 0

        await query.message.reply_text(
            "👥 <b>REFERAL</b>\n\n"
            f"🔗 <code>{link}</code>\n\n"
            f"👥 Referallar: <b>{refs}</b>\n"
            f"⭐ Har bir referal: +{REFERRAL_STARS:g}\n"
            f"💰 Har bir referal: +{money_format(REFERRAL_BONUS)} so‘m",
            parse_mode="HTML",
        )
        return

    # Number
    if data.startswith("number:"):
        await query.answer()

        country = data.split(":", 1)[1]
        await create_number_order(update, country)
        return

    # Nakrutka platform
    if data.startswith("nakplatform:"):
        await query.answer()

        platform = data.split(":", 1)[1]
        await nak_platform(query, platform)
        return

    # Nakrutka quantity
    if data.startswith("nak:"):
        await query.answer()

        parts = data.split(":", 2)

        if len(parts) != 3:
            return

        platform = parts[1]
        qty = parts[2]

        price = NAKRUTKA.get(platform, {}).get(qty)

        if price is None:
            return

        context.user_data["nak_order"] = {
            "platform": platform,
            "qty": qty,
            "price": price,
        }

        await query.message.reply_text(
            "🔗 <b>Havolani yuboring:</b>\n\n"
            f"📈 Platforma: {html.escape(platform)}\n"
            f"📊 Miqdor: {html.escape(qty)}\n"
            f"💰 Narx: {money_format(price)} so‘m",
            parse_mode="HTML",
        )
        return

    # Shop
    if data == "shop_stars":
        await query.answer()
        await shop_stars(query)
        return

    if data == "shop_premium":
        await query.answer()
        await shop_premium(query)
        return

    if data.startswith("buy_stars:"):
        await query.answer()

        amount = int(data.split(":")[1])
        price = STARS_PRICES.get(amount)

        if price is None:
            return

        await target_menu(
            query,
            "stars",
            str(amount),
        )
        return

    if data.startswith("buy_premium:"):
        await query.answer()

        period = data.split(":", 1)[1]
        price = PREMIUM_PRICES.get(period)

        if price is None:
            return

        await target_menu(
            query,
            "premium",
            period,
        )
        return

    # Target
    if data.startswith("target:self:"):
        await query.answer()

        parts = data.split(":", 3)

        if len(parts) != 4:
            return

        kind = parts[2]
        item = parts[3]

        if kind == "stars":
            amount = int(item)
            price = STARS_PRICES[amount]

            await create_order(
                query,
                context,
                "Stars",
                f"{amount} Stars",
                price,
                str(query.from_user.id),
            )

        elif kind == "premium":
            price = PREMIUM_PRICES[item]

            await create_order(
                query,
                context,
                "Premium",
                item,
                price,
                str(query.from_user.id),
            )

        return

    if data.startswith("target:other:"):
        await query.answer()

        parts = data.split(":", 3)

        if len(parts) != 4:
            return

        context.user_data["other_order"] = {
            "kind": parts[2],
            "item": parts[3],
        }

        await query.message.reply_text(
            "👤 <b>Username kiriting:</b>\n\n"
            "Masalan: <code>@username</code>",
            parse_mode="HTML",
        )
        return

    # Admin money withdrawal
    if data.startswith("money_approve:"):
        await query.answer()

        withdrawal_id = int(data.split(":")[1])

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM money_withdrawals
            WHERE id=? AND status='pending'
        """, (withdrawal_id,)).fetchone()

        if not row:
            conn.close()
            await query.message.reply_text(
                "⚠️ So‘rov allaqachon ko‘rib chiqilgan."
            )
            return

        if row["reserved"]:
            conn.execute("""
                UPDATE money_withdrawals
                SET status='approved',
                    processed_at=?
                WHERE id=? AND status='pending'
            """, (now(), withdrawal_id))
        else:
            result = conn.execute("""
                UPDATE users
                SET bonus_balance=bonus_balance-?
                WHERE id=? AND bonus_balance>=?
            """, (
                row["amount"],
                row["user_id"],
                row["amount"],
            ))

            if result.rowcount != 1:
                conn.close()
                await query.message.reply_text(
                    "❌ User balansida yetarli mablag‘ yo‘q."
                )
                return

            conn.execute("""
                UPDATE money_withdrawals
                SET status='approved',
                    processed_at=?
                WHERE id=? AND status='pending'
            """, (now(), withdrawal_id))

        conn.commit()
        conn.close()

        await query.message.edit_reply_markup(reply_markup=None)

        await query.message.reply_text(
            "✅ <b>PUL YECHISH TASDIQLANDI</b>",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                row["user_id"],
                "✅ <b>Pul yechish so‘rovingiz tasdiqlandi.</b>\n\n"
                f"💵 Summa: {money_format(row['amount'])} so‘m",
                parse_mode="HTML",
            )
        except Exception:
            pass

        return

    if data.startswith("money_reject:"):
        await query.answer()

        withdrawal_id = int(data.split(":")[1])

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM money_withdrawals
            WHERE id=? AND status='pending'
        """, (withdrawal_id,)).fetchone()

        if not row:
            conn.close()
            await query.message.reply_text(
                "⚠️ So‘rov allaqachon ko‘rib chiqilgan."
            )
            return

        if row["reserved"]:
            conn.execute("""
                UPDATE users
                SET bonus_balance=bonus_balance+?
                WHERE id=?
            """, (
                row["amount"],
                row["user_id"],
            ))

        conn.execute("""
            UPDATE money_withdrawals
            SET status='rejected',
                processed_at=?
            WHERE id=? AND status='pending'
        """, (now(), withdrawal_id))

        conn.commit()
        conn.close()

        await query.message.edit_reply_markup(reply_markup=None)

        await query.message.reply_text(
            "❌ <b>PUL YECHISH RAD ETILDI</b>",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                row["user_id"],
                "❌ <b>Pul yechish so‘rovingiz rad etildi.</b>\n\n"
                "💰 Mablag‘ bonus balansingizga qaytarildi.",
                parse_mode="HTML",
            )
        except Exception:
            pass

        return

    # Order finish
    if data.startswith("order_finish:"):
        await query.answer()

        order_id = int(data.split(":")[1])

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM service_orders
            WHERE id=? AND status='pending'
        """, (order_id,)).fetchone()

        if not row:
            conn.close()
            await query.message.reply_text(
                "⚠️ Buyurtma allaqachon ko‘rib chiqilgan."
            )
            return

        conn.execute("""
            UPDATE service_orders
            SET status='completed',
                processed_at=?
            WHERE id=? AND status='pending'
        """, (now(), order_id))

        conn.commit()
        conn.close()

        await query.message.edit_reply_markup(reply_markup=None)

        await query.message.reply_text(
            "✅ <b>BUYURTMA BAJARILDI</b>",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                row["user_id"],
                "✅ <b>Buyurtmangiz bajarildi!</b>\n\n"
                f"📦 {html.escape(row['item'])}",
                parse_mode="HTML",
            )
        except Exception:
            pass

        return

    # Order reject
    if data.startswith("order_reject:"):
        await query.answer()

        order_id = int(data.split(":")[1])

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM service_orders
            WHERE id=? AND status='pending'
        """, (order_id,)).fetchone()

        if not row:
            conn.close()
            await query.message.reply_text(
                "⚠️ Buyurtma allaqachon ko‘rib chiqilgan."
            )
            return

        if row["balance_charged"]:
            conn.execute("""
                UPDATE users
                SET real_balance=real_balance+?,
                    total_spent=
                        CASE
                            WHEN total_spent>=?
                            THEN total_spent-?
                            ELSE 0
                        END
                WHERE id=?
            """, (
                row["price"],
                row["price"],
                row["price"],
                row["user_id"],
            ))

        conn.execute("""
            UPDATE service_orders
            SET status='rejected',
                processed_at=?
            WHERE id=? AND status='pending'
        """, (now(), order_id))

        conn.commit()
        conn.close()

        await query.message.edit_reply_markup(reply_markup=None)

        await query.message.reply_text(
            "❌ <b>BUYURTMA RAD ETILDI</b>\n"
            "💰 Mablag‘ qaytarildi.",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                row["user_id"],
                "❌ <b>Buyurtmangiz rad etildi.</b>\n\n"
                f"💰 {money_format(row['price'])} so‘m balansingizga qaytarildi.",
                parse_mode="HTML",
            )
        except Exception:
            pass

        return

    # Admin panel
    if data == "admin_stats":
        await query.answer()
        await admin_stats(query)
        return

    if data == "admin_payments":
        await query.answer()
        await admin_payments(query)
        return

    if data == "admin_orders":
        await query.answer()
        await admin_orders(query)
        return

    if data == "admin_withdrawals":
        await query.answer()
        await admin_withdrawals(query)
        return

    if data == "admin_back":
        await query.answer()
        await admin_panel_message(query)
        return

    if data == "admin_broadcast":
        await query.answer()
        context.user_data["broadcast"] = True
        await query.message.reply_text(
            "📢 <b>Broadcast</b>\n\n"
            "Yuboriladigan xabarni yozing:",
            parse_mode="HTML",
        )
        return


# =========================================================
# ADMIN
# =========================================================


async def admin_panel_message(target):
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 STATISTIKA",
                callback_data="admin_stats",
            )
        ],
        [
            InlineKeyboardButton(
                "💳 TO‘LOVLAR",
                callback_data="admin_payments",
            )
        ],
        [
            InlineKeyboardButton(
                "🛍 BUYURTMALAR",
                callback_data="admin_orders",
            )
        ],
        [
            InlineKeyboardButton(
                "💸 PUL YECHISHLAR",
                callback_data="admin_withdrawals",
            )
        ],
        [
            InlineKeyboardButton(
                "📢 BROADCAST",
                callback_data="admin_broadcast",
            )
        ],
    ])

    text = "🛠 <b>ADMIN PANEL</b>\n\nBo‘limni tanlang:"

    if hasattr(target, "message"):
        await target.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML",
        )
    else:
        await target.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML",
        )


async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await admin_panel_message(update)


async def admin_stats(query):
    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    active = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE last_seen >= ?
    """, (
        (
            datetime.now(timezone.utc)
            - timedelta(days=1)
        ).isoformat(),
    )).fetchone()[0]

    stats = conn.execute("""
        SELECT *
        FROM bot_stats
        WHERE id=1
    """).fetchone()

    real = conn.execute("""
        SELECT COALESCE(SUM(real_balance),0)
        FROM users
    """).fetchone()[0]

    bonus = conn.execute("""
        SELECT COALESCE(SUM(bonus_balance),0)
        FROM users
    """).fetchone()[0]

    deposited = conn.execute("""
        SELECT COALESCE(SUM(amount),0)
        FROM payment_requests
        WHERE status='approved'
    """).fetchone()[0]

    pending_payments = conn.execute("""
        SELECT COUNT(*)
        FROM payment_requests
        WHERE status='pending'
    """).fetchone()[0]

    pending_orders = conn.execute("""
        SELECT COUNT(*)
        FROM service_orders
        WHERE status='pending'
    """).fetchone()[0]

    pending_withdrawals = conn.execute("""
        SELECT COUNT(*)
        FROM money_withdrawals
        WHERE status='pending'
    """).fetchone()[0]

    conn.close()

    text = (
        "📊 <b>BOT STATISTIKA</b>\n\n"
        f"👥 Jami userlar: <b>{total}</b>\n"
        f"📈 Doimiy hisob: <b>{stats['total_users']}</b>\n"
        f"🟢 Faol 24 soat: <b>{active}</b>\n\n"
        f"💳 Real balanslar: <b>{money_format(real)} so‘m</b>\n"
        f"💰 Bonus balanslar: <b>{money_format(bonus)} so‘m</b>\n"
        f"💵 Jami depozit: <b>{money_format(deposited)} so‘m</b>\n\n"
        f"💳 Kutilayotgan to‘lov: <b>{pending_payments}</b>\n"
        f"🛍 Kutilayotgan buyurtma: <b>{pending_orders}</b>\n"
        f"💸 Kutilayotgan yechish: <b>{pending_withdrawals}</b>"
    )

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ ORQAGA",
                    callback_data="admin_back",
                )
            ]
        ]),
        parse_mode="HTML",
    )


async def admin_payments(query):
    conn = db()

    rows = conn.execute("""
        SELECT p.*,u.username
        FROM payment_requests p
        LEFT JOIN users u ON u.id=p.user_id
        WHERE p.status='pending'
        ORDER BY p.id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    if not rows:
        text = "💳 <b>KUTILAYOTGAN TO‘LOVLAR</b>\n\nYo‘q."
    else:
        lines = ["💳 <b>KUTILAYOTGAN TO‘LOVLAR</b>\n"]

        for r in rows:
            username = (
                f"@{r['username']}"
                if r["username"]
                else "username yo‘q"
            )

            lines.append(
                f"🆔 {r['id']} | "
                f"👤 {html.escape(username)} | "
                f"💵 {money_format(r['amount'])} so‘m"
            )

        text = "\n".join(lines)

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ ORQAGA",
                    callback_data="admin_back",
                )
            ]
        ]),
        parse_mode="HTML",
    )


async def admin_orders(query):
    conn = db()

    rows = conn.execute("""
        SELECT o.*,u.username
        FROM service_orders o
        LEFT JOIN users u ON u.id=o.user_id
        WHERE o.status='pending'
        ORDER BY o.id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    if not rows:
        text = "🛍 <b>KUTILAYOTGAN BUYURTMALAR</b>\n\nYo‘q."
    else:
        lines = ["🛍 <b>KUTILAYOTGAN BUYURTMALAR</b>\n"]

        for r in rows:
            username = (
                f"@{r['username']}"
                if r["username"]
                else "username yo‘q"
            )

            lines.append(
                f"🆔 {r['id']} | "
                f"{html.escape(r['category'])} | "
                f"{html.escape(r['item'])} | "
                f"{money_format(r['price'])} so‘m | "
                f"{html.escape(username)}"
            )

        text = "\n".join(lines)

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ ORQAGA",
                    callback_data="admin_back",
                )
            ]
        ]),
        parse_mode="HTML",
    )


async def admin_withdrawals(query):
    conn = db()

    rows = conn.execute("""
        SELECT w.*,u.username
        FROM money_withdrawals w
        LEFT JOIN users u ON u.id=w.user_id
        WHERE w.status='pending'
        ORDER BY w.id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    if not rows:
        text = "💸 <b>KUTILAYOTGAN PUL YECHISHLAR</b>\n\nYo‘q."
    else:
        lines = ["💸 <b>KUTILAYOTGAN PUL YECHISHLAR</b>\n"]

        for r in rows:
            username = (
                f"@{r['username']}"
                if r["username"]
                else "username yo‘q"
            )

            lines.append(
                f"🆔 {r['id']} | "
                f"👤 {html.escape(username)} | "
                f"💵 {money_format(r['amount'])} so‘m"
            )

        text = "\n".join(lines)

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ ORQAGA",
                    callback_data="admin_back",
                )
            ]
        ]),
        parse_mode="HTML",
    )


async def process_broadcast(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    text = update.message.text

    conn = db()

    rows = conn.execute(
        "SELECT id FROM users WHERE blocked=0"
    ).fetchall()

    conn.close()

    sent = 0

    for row in rows:
        try:
            await context.bot.send_message(
                row["id"],
                text,
            )
            sent += 1
            await asyncio.sleep(0.05)

        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)

        except Forbidden:
            conn = db()
            conn.execute(
                "UPDATE users SET blocked=1 WHERE id=?",
                (row["id"],),
            )
            conn.commit()
            conn.close()

        except Exception:
            pass

    context.user_data.pop("broadcast", None)

    await update.message.reply_text(
        f"✅ Broadcast tugadi.\n\n"
        f"📨 Yuborildi: {sent}"
    )


# =========================================================
# TEXT HANDLER
# =========================================================


async def text_handler(update, context):
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    text = update.message.text or ""

    add_user(
        user_id,
        update.effective_user.username or "",
    )

    # Admin broadcast
    if (
        user_id == ADMIN_ID
        and context.user_data.get("broadcast")
    ):
        await process_broadcast(update, context)
        return

    # Payment amount
    if context.user_data.get("waiting_payment_amount"):
        try:
            amount = float(
                text.replace(" ", "")
                .replace(",", "")
                .replace("so'm", "")
                .strip()
            )
        except Exception:
            await update.message.reply_text(
                "❌ Summani faqat raqam bilan kiriting.\n"
                "Masalan: 10000"
            )
            return

        if amount < MIN_TOPUP:
            await update.message.reply_text(
                f"❌ Minimal to‘lov: "
                f"{money_format(MIN_TOPUP)} so‘m"
            )
            return

        context.user_data.pop(
            "waiting_payment_amount",
            None,
        )

        context.user_data["payment_amount"] = amount
        context.user_data["waiting_receipt"] = True

        await update.message.reply_text(
            "📝 <b>To‘lov chekini rasmga olib yuboring.</b>\n\n"
            f"💵 Summa: <b>{money_format(amount)} so‘m</b>",
            parse_mode="HTML",
        )
        return

    # Receipt
    if (
        context.user_data.get("waiting_receipt")
        and update.message.photo
    ):
        await receive_receipt(update, context)
        return

    # Money withdraw
    if context.user_data.get("waiting_money_withdraw"):
        await process_money_withdraw(update, context)
        return

    # Other user
    if context.user_data.get("other_order"):
        data = context.user_data.pop("other_order")

        target = text.strip()

        if not target.startswith("@"):
            target = "@" + target

        kind = data["kind"]
        item = data["item"]

        if kind == "stars":
            amount = int(item)
            price = STARS_PRICES[amount]

            await create_order(
                DummyQuery(update),
                context,
                "Stars",
                f"{amount} Stars",
                price,
                target,
            )

        elif kind == "premium":
            price = PREMIUM_PRICES[item]

            await create_order(
                DummyQuery(update),
                context,
                "Premium",
                item,
                price,
                target,
            )

        return

    # Nakrutka link
    if context.user_data.get("nak_order"):
        order = context.user_data.pop("nak_order")

        platform = order["platform"]
        qty = order["qty"]
        price = order["price"]

        await create_order(
            DummyQuery(update),
            context,
            "Nakrutka",
            f"{platform} {qty}",
            price,
            text.strip(),
        )
        return

    # Sponsor
    if not await check_all_sponsors(
        context.bot,
        user_id,
    ):
        await show_sponsor(update)
        return

    # Main menu
    if text == "💰 PUL ISHLASH":
        await money_work(update)
        return

    if text == "⭐ STARS ISHLASH":
        await stars_work(update)
        return

    if text == "💎 PREMIUM ISHLASH":
        await premium_work(update)
        return

    if text == "📱 NOMER OLISH":
        await numbers_menu(update)
        return

    if text == "📈 NAKRUTKA":
        await nakrutka_menu(update)
        return

    if text == "🛍 DO‘KON":
        await shop_menu(update)
        return

    if text == "💳 HISOB TO‘LDIRISH":
        await payment_menu(update)
        return

    if text == "👤 MENING HISOBIM":
        await my_account(update)
        return

    await update.message.reply_text(
        "👇 Menyudan kerakli bo‘limni tanlang:",
        reply_markup=main_keyboard(),
    )


# =========================================================
# DUMMY QUERY
# =========================================================


class DummyMessage:
    def __init__(self, message):
        self.message = message

    async def reply_text(
        self,
        text,
        reply_markup=None,
        parse_mode=None,
    ):
        return await self.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )


class DummyQuery:
    def __init__(self, update):
        self.from_user = update.effective_user
        self.message = DummyMessage(update.message)


# =========================================================
# PHOTO HANDLER
# =========================================================


async def photo_handler(update, context):
    if not update.message or not update.effective_user:
        return

    if context.user_data.get("waiting_receipt"):
        await receive_receipt(update, context)


# =========================================================
# ERROR HANDLER
# =========================================================


async def error_handler(update, context):
    logger.exception(
        "Unhandled exception",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN GitHub Secrets/environment variable topilmadi."
        )

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(False)
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
            filters.PHOTO,
            photo_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info("TEKIN STARS BOT ishga tushmoqda...")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
