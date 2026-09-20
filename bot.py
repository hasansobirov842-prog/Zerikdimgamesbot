
import os
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta

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
ADMIN_ID = int(os.getenv("ADMIN_ID", "8679536810"))

DB_FILE = "zerikdim.db"

PAYMENT_CARD = "5614681008971867"
PAYMENT_OWNER = "RAKHMONOVA/O"

SPONSOR = "@premyumstarstekin"
SPONSOR_URL = "https://t.me/premyumstarstekin"

STARS_RATE = 210

REFERRAL_STARS = 9
REFERRAL_MONEY = 500

MIN_WITHDRAW = 10000

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# NARXLAR
# =========================================================

NUMBERS = {
    "🇹🇯 Tojikiston": 12000,
    "🇮🇷 Eron": 8000,
    "🇷🇺 Rossiya": 22000,
    "🇺🇸 AQSH": 7000,
    "🇮🇳 Hindiston": 6000,
    "🇨🇱 Chili": 9000,
    "🇰🇪 Keniya": 8000,
    "🇦🇴 Angola": 8000,
    "🇵🇰 Pokiston": 8000,
}

GIFTS = {
    "⭐️ 15 talik 🧸💝": 4000,
    "⭐️ 25 talik 🎁🌹": 6000,
    "⭐️ 50 talik 🚀🎂": 12000,
    "⭐️ 100 talik 💎🏆💍": 22000,
}

STARS_PACKS = {
    50: 50 * STARS_RATE,
    100: 100 * STARS_RATE,
}

PREMIUM = {
    "💎 1 OY": 45000,
    "💎 3 OY": 120000,
    "💎 6 OY": 200000,
    "👑 12 OY": 299000,
}

NAKRUTKA = {
    "Telegram": 3000,
    "Instagram": 15000,
    "TikTok": 15000,
    "YouTube": 15000,
}


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            stars INTEGER DEFAULT 0,
            money REAL DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT NULL,
            blocked INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            receipt TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            item TEXT,
            quantity INTEGER DEFAULT 0,
            price REAL,
            target TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_stats (
            id INTEGER PRIMARY KEY,
            total_users INTEGER DEFAULT 0
        )
    """)

    cur.execute(
        "INSERT OR IGNORE INTO bot_stats(id,total_users) VALUES(1,0)"
    )

    con.commit()
    con.close()


# =========================================================
# USER
# =========================================================

def get_user(user_id):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    )
    row = cur.fetchone()
    con.close()
    return row


def add_user(user_id, username, referred_by=None):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    )

    exists = cur.fetchone()

    if not exists:
        cur.execute("""
            INSERT INTO users
            (id, username, stars, money, referrals,
             referred_by, blocked, created_at)
            VALUES (?, ?, 0, 0, 0, ?, 0, ?)
        """, (
            user_id,
            username or "",
            referred_by,
            datetime.now().isoformat(),
        ))

        cur.execute("""
            UPDATE bot_stats
            SET total_users = total_users + 1
            WHERE id=1
        """)
        con.commit()

        if referred_by and referred_by != user_id:
            cur.execute("""
                UPDATE users
                SET stars = stars + ?,
                    money = money + ?,
                    referrals = referrals + 1
                WHERE id=?
            """, (
                REFERRAL_STARS,
                REFERRAL_MONEY,
                referred_by,
            ))
            con.commit()

    else:
        cur.execute(
            "UPDATE users SET username=? WHERE id=?",
            (username or "", user_id)
        )
        con.commit()

    con.close()


def get_balance(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT stars,money,referrals FROM users WHERE id=?",
        (user_id,)
    )

    row = cur.fetchone()
    con.close()

    if not row:
        return 0, 0, 0

    return row


def change_stars(user_id, amount):
    con = db()
    con.execute(
        "UPDATE users SET stars=stars+? WHERE id=?",
        (amount, user_id)
    )
    con.commit()
    con.close()


def change_money(user_id, amount):
    con = db()
    con.execute(
        "UPDATE users SET money=money+? WHERE id=?",
        (amount, user_id)
    )
    con.commit()
    con.close()


# =========================================================
# SPONSOR
# =========================================================

async def is_subscribed(bot, user_id):
    try:
        member = await bot.get_chat_member(SPONSOR, user_id)

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except TelegramError:
        return False


def sponsor_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 HOMIY KANAL",
                url=SPONSOR_URL
            )
        ],
        [
            InlineKeyboardButton(
                "✅ OBUNANI TEKSHIRISH",
                callback_data="check_sponsor"
            )
        ]
    ])


async def sponsor_check(update, context):
    user_id = update.effective_user.id

    if await is_subscribed(context.bot, user_id):
        return True

    if update.callback_query:
        await update.callback_query.message.edit_text(
            "🔒 Botdan foydalanish uchun homiy kanalga obuna bo‘ling.\n\n"
            "1️⃣ Kanalga kiring\n"
            "2️⃣ Obuna bo‘ling\n"
            "3️⃣ Tekshirish tugmasini bosing.",
            reply_markup=sponsor_keyboard()
        )
    else:
        await update.message.reply_text(
            "🔒 Botdan foydalanish uchun homiy kanalga obuna bo‘ling.",
            reply_markup=sponsor_keyboard()
        )

    return False


# =========================================================
# MAIN MENU
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["💰 PUL ISHLASH", "⭐️ STARS ISHLASH"],
            ["💎 PREMIUM ISHLASH", "🎁 GIFT OLISH"],
            ["📱 NOMER OLISH", "📈 NAKRUTKA"],
            ["💳 HISOB TO‘LDIRISH", "👤 MENING HISOBIM"],
            ["💸 PUL YECHISH", "📦 BUYURTMALARIM"],
        ],
        resize_keyboard=True
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ref = None

    if context.args:
        try:
            ref = int(context.args[0])
        except ValueError:
            ref = None

    add_user(
        user.id,
        user.username,
        ref
    )

    if not await sponsor_check(update, context):
        return

    stars, money, refs = get_balance(user.id)

    await update.message.reply_text(
        "✨ <b>TEKIN STARS BOT</b> ✨\n\n"
        "💰 Pul ishlang\n"
        "⭐️ Stars ishlang\n"
        "💎 Premium xizmatlardan foydalaning\n"
        "🎁 Gift buyurtma qiling\n"
        "📱 Raqamlar oling\n"
        "📈 Nakrutka xizmatlari\n\n"
        f"⭐️ Stars: <b>{stars}</b>\n"
        f"💰 Bonus: <b>{money:,.0f} so‘m</b>\n"
        f"👥 Referallar: <b>{refs}</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# PROFILE
# =========================================================

async def profile(update, context):
    if not await sponsor_check(update, context):
        return

    user = update.effective_user
    stars, money, refs = get_balance(user.id)

    bot_username = (await context.bot.get_me()).username

    link = f"https://t.me/{bot_username}?start={user.id}"

    await update.message.reply_text(
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"⭐️ Stars: <b>{stars}</b>\n"
        f"💰 Bonus: <b>{money:,.0f} so‘m</b>\n"
        f"👥 Referallar: <b>{refs}</b>\n\n"
        f"🔗 Referal havolangiz:\n{link}\n\n"
        f"🎁 1 ta odam = {REFERRAL_STARS} ⭐️ + "
        f"{REFERRAL_MONEY:,} so‘m",
        parse_mode="HTML"
    )


# =========================================================
# STARS
# =========================================================

async def stars_menu(update, context):
    if not await sponsor_check(update, context):
        return

    keyboard = [
        [
            InlineKeyboardButton(
                f"⭐️ 50 — {STARS_PACKS[50]:,} so‘m",
                callback_data="stars_50"
            )
        ],
        [
            InlineKeyboardButton(
                f"⭐️ 100 — {STARS_PACKS[100]:,} so‘m",
                callback_data="stars_100"
            )
        ],
        [
            InlineKeyboardButton(
                "✍️ O‘ZIM MIQDOR YOZAMAN",
                callback_data="stars_custom"
            )
        ]
    ]

    await update.message.reply_text(
        "⭐️ <b>STARS OLISH</b>\n\n"
        f"💵 Kurs: <b>1 ⭐️ = {STARS_RATE} so‘m</b>\n\n"
        "⭐️ 50 Stars\n"
        "⭐️ 100 Stars\n"
        "⭐️ yoki kerakli miqdorni o‘zingiz yozing.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def stars_custom(update, context):
    q = update.callback_query
    await q.answer()

    context.user_data["state"] = "stars_custom"

    await q.message.reply_text(
        "⭐️ Qancha Stars kerak?\n\n"
        "Masalan: <b>250</b>\n\n"
        f"💵 1 ⭐️ = {STARS_RATE} so‘m",
        parse_mode="HTML"
    )


async def create_stars_order(update, context, amount):
    user_id = update.effective_user.id

    price = amount * STARS_RATE

    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO orders
        (user_id,category,item,quantity,price,target,status,created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        user_id,
        "STARS",
        "Telegram Stars",
        amount,
        price,
        str(user_id),
        "pending",
        datetime.now().isoformat()
    ))

    order_id = cur.lastrowid
    con.commit()
    con.close()

    await update.message.reply_text(
        f"⭐️ Buyurtma: <b>{amount}</b> Stars\n"
        f"💰 Narxi: <b>{price:,.0f} so‘m</b>\n\n"
        f"🆔 Buyurtma: <code>#{order_id}</code>\n\n"
        "💳 Hisobingizni to‘ldiring yoki mavjud balansdan foydalaning.\n"
        "Admin buyurtmani ko‘rib chiqadi.",
        parse_mode="HTML"
    )

    await notify_admin_order(
        context,
        order_id,
        user_id,
        "STARS",
        f"{amount} ⭐️",
        price
    )


# =========================================================
# GIFTS
# =========================================================

async def gifts_menu(update, context):
    if not await sponsor_check(update, context):
        return

    buttons = []

    for name, price in GIFTS.items():
        buttons.append([
            InlineKeyboardButton(
                f"{name} — {price:,} so‘m",
                callback_data=f"gift:{name}"
            )
        ])

    await update.message.reply_text(
        "🎁 <b>TELEGRAM GIFTLAR</b>\n\n"
        "Kerakli giftni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def gift_selected(update, context, name):
    price = GIFTS[name]

    context.user_data["pending"] = {
        "category": "GIFT",
        "item": name,
        "price": price,
    }

    await update.callback_query.message.reply_text(
        f"🎁 <b>{name}</b>\n\n"
        f"💰 Narxi: <b>{price:,} so‘m</b>\n\n"
        "📱 Gift kimga yuboriladi?\n"
        "Username yoki Telegram ID yuboring.",
        parse_mode="HTML"
    )

    context.user_data["state"] = "gift_target"


# =========================================================
# PREMIUM
# =========================================================

async def premium_menu(update, context):
    if not await sponsor_check(update, context):
        return

    buttons = [
        [
            InlineKeyboardButton(
                "💎 1 OY — 45 000 so‘m",
                callback_data="premium:💎 1 OY"
            )
        ],
        [
            InlineKeyboardButton(
                "💎 3 OY — 120 000 so‘m",
                callback_data="premium:💎 3 OY"
            )
        ],
        [
            InlineKeyboardButton(
                "💎 6 OY — 200 000 so‘m",
                callback_data="premium:💎 6 OY"
            )
        ],
        [
            InlineKeyboardButton(
                "👑 12 OY — 299 000 so‘m",
                callback_data="premium:👑 12 OY"
            )
        ],
    ]

    await update.message.reply_text(
        "💎✨ <b>TELEGRAM PREMIUM</b> ✨💎\n\n"
        "🌈 Premium xizmatlari\n"
        "⚡️ Tezkor buyurtma\n"
        "🎁 Premium muddatini tanlang\n\n"
        "👇 Kerakli muddatni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def premium_selected(update, context, name):
    price = PREMIUM[name]

    context.user_data["pending"] = {
        "category": "PREMIUM",
        "item": name,
        "price": price,
    }

    context.user_data["state"] = "premium_target"

    await update.callback_query.message.reply_text(
        f"💎 <b>PREMIUM {name}</b>\n\n"
        f"💰 Narxi: <b>{price:,} so‘m</b>\n\n"
        "👤 Premium kimga kerak?\n"
        "Username yoki Telegram ID yuboring.",
        parse_mode="HTML"
    )


# =========================================================
# RAQAMLAR
# =========================================================

async def numbers_menu(update, context):
    if not await sponsor_check(update, context):
        return

    buttons = []

    for country, price in NUMBERS.items():
        buttons.append([
            InlineKeyboardButton(
                f"{country} — {price:,} so‘m",
                callback_data=f"number:{country}"
            )
        ])

    await update.message.reply_text(
        "📱 <b>VIRTUAL RAQAMLAR</b>\n\n"
        "Kerakli davlatni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def number_selected(update, context, country):
    price = NUMBERS[country]

    context.user_data["pending"] = {
        "category": "NUMBER",
        "item": country,
        "price": price,
    }

    context.user_data["state"] = "number_target"

    await update.callback_query.message.reply_text(
        f"📱 {country}\n\n"
        f"💰 Narxi: <b>{price:,} so‘m</b>\n\n"
        "Buyurtmani tasdiqlash uchun <b>HA</b> deb yozing.",
        parse_mode="HTML"
    )


# =========================================================
# NAKRUTKA
# =========================================================

async def nakrutka_menu(update, context):
    if not await sponsor_check(update, context):
        return

    buttons = []

    for platform, price in NAKRUTKA.items():
        buttons.append([
            InlineKeyboardButton(
                f"📈 {platform} — 1K {price:,} so‘m",
                callback_data=f"nak:{platform}"
            )
        ])

    await update.message.reply_text(
        "📈 <b>NAKRUTKA</b>\n\n"
        "Narx 1K uchun hisoblanadi.\n"
        "Masalan 5K Telegram = 15 000 so‘m.\n\n"
        "Platformani tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def nakrutka_selected(update, context, platform):
    context.user_data["nak_platform"] = platform
    context.user_data["state"] = "nak_quantity"

    price = NAKRUTKA[platform]

    await update.callback_query.message.reply_text(
        f"📈 <b>{platform}</b>\n\n"
        f"💰 1K = {price:,} so‘m\n\n"
        "Qancha kerakligini yozing.\n"
        "Masalan: <b>5K</b> yoki <b>2000</b>",
        parse_mode="HTML"
    )


# =========================================================
# HISOB TO‘LDIRISH
# =========================================================

async def topup_menu(update, context):
    if not await sponsor_check(update, context):
        return

    context.user_data["state"] = "payment_amount"

    await update.message.reply_text(
        "💳 <b>HISOB TO‘LDIRISH</b>\n\n"
        f"💳 Karta:\n<code>{PAYMENT_CARD}</code>\n"
        f"👤 Karta egasi: <b>{PAYMENT_OWNER}</b>\n\n"
        "Qancha pul to‘ldirmoqchisiz?\n"
        "Masalan: <b>20000</b>",
        parse_mode="HTML"
    )


async def receive_payment_amount(update, context):
    try:
        amount = float(update.message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Raqam kiriting.")
        return

    if amount < 1000:
        await update.message.reply_text(
            "❌ Minimum to‘lov: 1 000 so‘m."
        )
        return

    context.user_data["payment_amount"] = amount
    context.user_data["state"] = "receipt"

    await update.message.reply_text(
        f"💰 To‘lov: <b>{amount:,.0f} so‘m</b>\n\n"
        "📸 Endi to‘lov chekini rasm qilib yuboring.",
        parse_mode="HTML"
    )


async def receive_receipt(update, context):
    amount = context.user_data.get("payment_amount")

    if not amount:
        await update.message.reply_text(
            "❌ Avval to‘lov summasini kiriting."
        )
        return

    photo = update.message.photo[-1]

    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO payments
        (user_id,amount,receipt,status,created_at)
        VALUES (?,?,?,?,?)
    """, (
        update.effective_user.id,
        amount,
        photo.file_id,
        "pending",
        datetime.now().isoformat()
    ))

    payment_id = cur.lastrowid

    con.commit()
    con.close()

    context.user_data.clear()

    await update.message.reply_text(
        "✅ Chek qabul qilindi.\n\n"
        f"🆔 To‘lov: #{payment_id}\n"
        "⏳ Admin tekshiradi."
    )

    try:
        await context.bot.send_photo(
            ADMIN_ID,
            photo.file_id,
            caption=(
                "💳 <b>YANGI TO‘LOV</b>\n\n"
                f"🆔 #{payment_id}\n"
                f"👤 User: <code>{update.effective_user.id}</code>\n"
                f"💰 Summa: <b>{amount:,.0f} so‘m</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ TASDIQLASH",
                        callback_data=f"pay_ok:{payment_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ RAD ETISH",
                        callback_data=f"pay_no:{payment_id}"
                    )
                ]
            ])
        )
    except TelegramError:
        pass


# =========================================================
# ORDER
# =========================================================

async def notify_admin_order(
    context,
    order_id,
    user_id,
    category,
    item,
    price
):
    try:
        await context.bot.send_message(
            ADMIN_ID,
            "🛒 <b>YANGI BUYURTMA</b>\n\n"
            f"🆔 #{order_id}\n"
            f"👤 User: <code>{user_id}</code>\n"
            f"📦 Xizmat: <b>{category}</b>\n"
            f"📌 {item}\n"
            f"💰 {price:,.0f} so‘m",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ BAJARILDI",
                        callback_data=f"order_ok:{order_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ RAD",
                        callback_data=f"order_no:{order_id}"
                    )
                ]
            ])
        )
    except TelegramError:
        pass


async def make_order(
    user_id,
    category,
    item,
    price,
    target,
    quantity=0
):
    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO orders
        (user_id,category,item,quantity,price,target,status,created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        user_id,
        category,
        item,
        quantity,
        price,
        target,
        "pending",
        datetime.now().isoformat()
    ))

    order_id = cur.lastrowid

    con.commit()
    con.close()

    return order_id


# =========================================================
# WITHDRAW
# =========================================================

async def withdraw_menu(update, context):
    if not await sponsor_check(update, context):
        return

    stars, money, refs = get_balance(update.effective_user.id)

    if money < MIN_WITHDRAW:
        await update.message.reply_text(
            f"💸 Pul yechish uchun kamida "
            f"<b>{MIN_WITHDRAW:,} so‘m</b> bonus kerak.\n\n"
            f"💰 Sizda: <b>{money:,.0f} so‘m</b>",
            parse_mode="HTML"
        )
        return

    context.user_data["state"] = "withdraw_amount"

    await update.message.reply_text(
        "💸 <b>PUL YECHISH</b>\n\n"
        f"💰 Bonus: {money:,.0f} so‘m\n\n"
        "⚠️ Ariza berishdan oldin referal havolani "
        "10 ta chatga o‘zingiz ulashing.\n\n"
        "Shundan keyin <b>TAYYOR</b> deb yozing.",
        parse_mode="HTML"
    )


async def withdraw_ready(update, context):
    if update.message.text.upper() != "TAYYOR":
        return

    user_id = update.effective_user.id

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT id FROM withdrawals
        WHERE user_id=? AND status='pending'
    """, (user_id,))

    if cur.fetchone():
        con.close()
        await update.message.reply_text(
            "⏳ Sizda allaqachon pending ariza bor."
        )
        return

    stars, money, refs = get_balance(user_id)

    if money < MIN_WITHDRAW:
        con.close()
        await update.message.reply_text("❌ Bonus yetarli emas.")
        return

    cur.execute("""
        INSERT INTO withdrawals
        (user_id,amount,status,created_at)
        VALUES (?,?,?,?)
    """, (
        user_id,
        money,
        "pending",
        datetime.now().isoformat()
    ))

    wid = cur.lastrowid

    cur.execute(
        "UPDATE users SET money=0 WHERE id=?",
        (user_id,)
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        "✅ Pul yechish arizasi yuborildi.\n\n"
        f"💰 Summa: <b>{money:,.0f} so‘m</b>\n"
        f"🆔 Ariza: #{wid}",
        parse_mode="HTML"
    )

    await context.bot.send_message(
        ADMIN_ID,
        "💸 <b>YANGI PUL YECHISH</b>\n\n"
        f"🆔 #{wid}\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"💰 {money:,.0f} so‘m",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ TO‘LANDI",
                    callback_data=f"wd_ok:{wid}"
                ),
                InlineKeyboardButton(
                    "❌ RAD",
                    callback_data=f"wd_no:{wid}"
                )
            ]
        ])
    )


# =========================================================
# ORDERS
# =========================================================

async def my_orders(update, context):
    if not await sponsor_check(update, context):
        return

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT id,category,item,price,status
        FROM orders
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (update.effective_user.id,))

    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text(
            "📦 Hozircha buyurtmalar yo‘q."
        )
        return

    text = "📦 <b>BUYURTMALARIM</b>\n\n"

    for oid, category, item, price, status in rows:
        if status == "pending":
            st = "⏳"
        elif status == "done":
            st = "✅"
        else:
            st = "❌"

        text += (
            f"{st} #{oid} — {category}\n"
            f"📌 {item}\n"
            f"💰 {price:,.0f} so‘m\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# ADMIN
# =========================================================

def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 STATISTIKA",
                callback_data="admin_stats"
            )
        ],
        [
            InlineKeyboardButton(
                "💳 TO‘LOVLAR",
                callback_data="admin_payments"
            ),
            InlineKeyboardButton(
                "🛒 BUYURTMALAR",
                callback_data="admin_orders"
            )
        ],
        [
            InlineKeyboardButton(
                "💸 PUL YECHISHLAR",
                callback_data="admin_withdrawals"
            )
        ]
    ])


async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "🛠 <b>ADMIN PANEL</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


async def admin_stats(update, context):
    con = db()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(stars),0) FROM users")
    stars = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(money),0) FROM users")
    money = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM orders")
    orders = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM orders WHERE status='pending'"
    )
    pending = cur.fetchone()[0]

    con.close()

    await update.callback_query.message.reply_text(
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"⭐️ Stars: <b>{stars}</b>\n"
        f"💰 Bonus: <b>{money:,.0f} so‘m</b>\n"
        f"📦 Buyurtmalar: <b>{orders}</b>\n"
        f"⏳ Pending: <b>{pending}</b>",
        parse_mode="HTML"
    )


# =========================================================
# CALLBACK
# =========================================================

async def callbacks(update, context):
    q = update.callback_query
    await q.answer()

    data = q.data

    if data == "check_sponsor":
        if await is_subscribed(context.bot, q.from_user.id):
            await q.message.reply_text(
                "✅ Obuna tasdiqlandi!",
                reply_markup=main_keyboard()
            )
        else:
            await q.answer(
                "❌ Avval kanalga obuna bo‘ling!",
                show_alert=True
            )
        return

    if q.from_user.id == ADMIN_ID:

        if data == "admin_stats":
            await admin_stats(update, context)
            return

        if data.startswith("pay_ok:"):
            pid = int(data.split(":")[1])

            con = db()
            cur = con.cursor()

            cur.execute(
                "SELECT user_id,amount FROM payments WHERE id=?",
                (pid,)
            )
            row = cur.fetchone()

            if row:
                uid, amount = row

                cur.execute("""
                    UPDATE users
                    SET money=money+?
                    WHERE id=?
                """, (amount, uid))

                cur.execute("""
                    UPDATE payments
                    SET status='approved'
                    WHERE id=?
                """, (pid,))

                con.commit()

                await context.bot.send_message(
                    uid,
                    f"✅ To‘lov tasdiqlandi!\n\n"
                    f"💰 +{amount:,.0f} so‘m balansga tushdi."
                )

            con.close()

            await q.message.reply_text(
                "✅ To‘lov tasdiqlandi."
            )
            return

        if data.startswith("pay_no:"):
            pid = int(data.split(":")[1])

            con = db()
            cur = con.cursor()

            cur.execute(
                "SELECT user_id FROM payments WHERE id=?",
                (pid,)
            )
            row = cur.fetchone()

            if row:
                uid = row[0]

                cur.execute("""
                    UPDATE payments
                    SET status='rejected'
                    WHERE id=?
                """, (pid,))

                con.commit()

                await context.bot.send_message(
                    uid,
                    "❌ To‘lovingiz rad etildi."
                )

            con.close()

            await q.message.reply_text(
                "❌ To‘lov rad etildi."
            )
            return

        if data.startswith("order_ok:"):
            oid = int(data.split(":")[1])

            con = db()
            cur = con.cursor()

            cur.execute(
                "SELECT user_id FROM orders WHERE id=?",
                (oid,)
            )
            row = cur.fetchone()

            cur.execute("""
                UPDATE orders
                SET status='done'
                WHERE id=?
            """, (oid,))

            con.commit()
            con.close()

            if row:
                await context.bot.send_message(
                    row[0],
                    f"✅ #{oid} buyurtmangiz bajarildi."
                )

            await q.message.reply_text(
                "✅ Buyurtma bajarildi."
            )
            return

        if data.startswith("order_no:"):
            oid = int(data.split(":")[1])

            con = db()
            cur = con.cursor()

            cur.execute(
                "SELECT user_id FROM orders WHERE id=?",
                (oid,)
            )
            row = cur.fetchone()

            cur.execute("""
                UPDATE orders
                SET status='rejected'
                WHERE id=?
            """, (oid,))

            con.commit()
            con.close()

            if row:
                await context.bot.send_message(
                    row[0],
                    f"❌ #{oid} buyurtmangiz rad etildi."
                )

            await q.message.reply_text(
                "❌ Buyurtma rad etildi."
            )
            return

        if data.startswith("wd_ok:"):
            wid = int(data.split(":")[1])

            con = db()
            cur = con.cursor()

            cur.execute(
                "SELECT user_id,amount FROM withdrawals WHERE id=?",
                (wid,)
            )

            row = cur.fetchone()

            if row:
                uid, amount = row

                cur.execute("""
                    UPDATE withdrawals
                    SET status='paid'
                    WHERE id=?
                """, (wid,))

                con.commit()

                await context.bot.send_message(
                    uid,
                    f"✅ Pul yechish tasdiqlandi.\n"
                    f"💰 {amount:,.0f} so‘m"
                )

            con.close()

            await q.message.reply_text(
                "✅ Pul yechish tasdiqlandi."
            )
            return

        if data.startswith("wd_no:"):
            wid = int(data.split(":")[1])

            con = db()
            cur = con.cursor()

            cur.execute("""
                SELECT user_id,amount
                FROM withdrawals
                WHERE id=?
            """, (wid,))

            row = cur.fetchone()

            if row:
                uid, amount = row

                cur.execute("""
                    UPDATE withdrawals
                    SET status='rejected'
                    WHERE id=?
                """, (wid,))

                cur.execute("""
                    UPDATE users
                    SET money=money+?
                    WHERE id=?
                """, (amount, uid))

                con.commit()

                await context.bot.send_message(
                    uid,
                    f"❌ Pul yechish rad etildi.\n"
                    f"💰 {amount:,.0f} so‘m qaytarildi."
                )

            con.close()

            await q.message.reply_text(
                "❌ Ariza rad etildi."
            )
            return

    # STARS
    if data == "stars_50":
        await create_stars_order_from_callback(
            update,
            context,
            50
        )
        return

    if data == "stars_100":
        await create_stars_order_from_callback(
            update,
            context,
            100
        )
        return

    if data == "stars_custom":
        context.user_data["state"] = "stars_custom"

        await q.message.reply_text(
            "⭐️ Qancha Stars kerak?\n"
            "Masalan: 250"
        )
        return

    # GIFTS
    if data.startswith("gift:"):
        name = data.split(":", 1)[1]
        await gift_selected(update, context, name)
        return

    # PREMIUM
    if data.startswith("premium:"):
        name = data.split(":", 1)[1]
        await premium_selected(update, context, name)
        return

    # NUMBER
    if data.startswith("number:"):
        country = data.split(":", 1)[1]
        await number_selected(update, context, country)
        return

    # NAKRUTKA
    if data.startswith("nak:"):
        platform = data.split(":", 1)[1]
        await nakrutka_selected(update, context, platform)
        return


async def create_stars_order_from_callback(
    update,
    context,
    amount
):
    q = update.callback_query
    price = amount * STARS_RATE

    order_id = await make_order(
        q.from_user.id,
        "STARS",
        f"{amount} ⭐️",
        price,
        str(q.from_user.id),
        amount
    )

    await q.message.reply_text(
        f"⭐️ <b>{amount} Stars</b>\n\n"
        f"💰 {price:,} so‘m\n"
        f"🆔 #{order_id}\n\n"
        "Admin buyurtmani ko‘rib chiqadi.",
        parse_mode="HTML"
    )

    await notify_admin_order(
        context,
        order_id,
        q.from_user.id,
        "STARS",
        f"{amount} ⭐️",
        price
    )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not await is_subscribed(context.bot, user_id):
        await sponsor_check(update, context)
        return

    state = context.user_data.get("state")

    # MENU
    if text == "👤 MENING HISOBIM":
        await profile(update, context)
        return

    if text == "⭐️ STARS ISHLASH":
        await stars_menu(update, context)
        return

    if text == "🎁 GIFT OLISH":
        await gifts_menu(update, context)
        return

    if text == "💎 PREMIUM ISHLASH":
        await premium_menu(update, context)
        return

    if text == "📱 NOMER OLISH":
        await numbers_menu(update, context)
        return

    if text == "📈 NAKRUTKA":
        await nakrutka_menu(update, context)
        return

    if text == "💳 HISOB TO‘LDIRISH":
        await topup_menu(update, context)
        return

    if text == "💸 PUL YECHISH":
        await withdraw_menu(update, context)
        return

    if text == "📦 BUYURTMALARIM":
        await my_orders(update, context)
        return

    if text == "💰 PUL ISHLASH":
        stars, money, refs = get_balance(user_id)

        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user_id}"

        await update.message.reply_text(
            "💰 <b>PUL ISHLASH</b>\n\n"
            f"💵 Bonus: <b>{money:,.0f} so‘m</b>\n"
            f"👥 Referallar: <b>{refs}</b>\n\n"
            f"🎁 1 referal = {REFERRAL_STARS} ⭐️ + "
            f"{REFERRAL_MONEY:,} so‘m\n\n"
            f"🔗 Sizning havolangiz:\n{link}",
            parse_mode="HTML"
        )
        return

    # STARS CUSTOM
    if state == "stars_custom":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ Faqat raqam yozing. Masalan: 250"
            )
            return

        if amount < 1:
            await update.message.reply_text(
                "❌ Miqdor 1 dan katta bo‘lishi kerak."
            )
            return

        context.user_data.clear()

        await create_stars_order(
            update,
            context,
            amount
        )
        return

    # PAYMENT
    if state == "payment_amount":
        await receive_payment_amount(update, context)
        return

    # RECEIPT
    if state == "receipt":
        await update.message.reply_text(
            "📸 Chekni rasm qilib yuboring."
        )
        return

    # NAKRUTKA QUANTITY
    if state == "nak_quantity":
        platform = context.user_data.get("nak_platform")

        value = text.upper().replace("K", "")

        try:
            quantity = float(value)
        except ValueError:
            await update.message.reply_text(
                "❌ Masalan: 5K yoki 2000 yozing."
            )
            return

        if "K" in text.upper():
            people = int(quantity * 1000)
        else:
            people = int(quantity)

        if people < 100:
            await update.message.reply_text(
                "❌ Minimum 100 ta."
            )
            return

        price = people / 1000 * NAKRUTKA[platform]

        context.user_data["nak_people"] = people
        context.user_data["nak_price"] = price
        context.user_data["state"] = "nak_link"

        await update.message.reply_text(
            f"📈 {platform}\n"
            f"👥 Miqdor: <b>{people:,}</b>\n"
            f"💰 Narx: <b>{price:,.0f} so‘m</b>\n\n"
            "🔗 Endi post/profil havolasini yuboring.",
            parse_mode="HTML"
        )
        return

    if state == "nak_link":
        platform = context.user_data["nak_platform"]
        people = context.user_data["nak_people"]
        price = context.user_data["nak_price"]

        order_id = await make_order(
            user_id,
            "NAKRUTKA",
            platform,
            price,
            text,
            people
        )

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Buyurtma qabul qilindi.\n\n"
            f"📈 {platform}\n"
            f"👥 {people:,}\n"
            f"💰 {price:,.0f} so‘m\n"
            f"🆔 #{order_id}",
            parse_mode="HTML"
        )

        await notify_admin_order(
            context,
            order_id,
            user_id,
            "NAKRUTKA",
            f"{platform} — {people:,}",
            price
        )
        return

    # TARGET
    if state in ("gift_target", "premium_target"):
        pending = context.user_data.get("pending")

        if not pending:
            return

        order_id = await make_order(
            user_id,
            pending["category"],
            pending["item"],
            pending["price"],
            text
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ Buyurtma qabul qilindi.\n\n"
            f"📦 {pending['category']}\n"
            f"📌 {pending['item']}\n"
            f"💰 {pending['price']:,} so‘m\n"
            f"🆔 #{order_id}",
            parse_mode="HTML"
        )

        await notify_admin_order(
            context,
            order_id,
            user_id,
            pending["category"],
            pending["item"],
            pending["price"]
        )
        return

    # NUMBER
    if state == "number_target":
        pending = context.user_data.get("pending")

        if not pending:
            return

        if text.upper() != "HA":
            await update.message.reply_text(
                "Tasdiqlash uchun HA deb yozing."
            )
            return

        order_id = await make_order(
            user_id,
            pending["category"],
            pending["item"],
            pending["price"],
            str(user_id)
        )

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Raqam buyurtmasi qabul qilindi.\n\n"
            f"📱 {pending['item']}\n"
            f"💰 {pending['price']:,} so‘m\n"
            f"🆔 #{order_id}",
            parse_mode="HTML"
        )

        await notify_admin_order(
            context,
            order_id,
            user_id,
            "NUMBER",
            pending["item"],
            pending["price"]
        )
        return

    # WITHDRAW
    if state == "withdraw_amount":
        await withdraw_ready(update, context)
        return


# =========================================================
# PHOTO HANDLER
# =========================================================

async def photo_handler(update, context):
    if context.user_data.get("state") == "receipt":
        await receive_receipt(update, context)


# =========================================================
# ERROR
# =========================================================

async def error_handler(update, context):
    logger.error(
        "Bot error: %s",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN GitHub Secrets ichida mavjud emas."
        )

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("admin", admin_command)
    )

    app.add_handler(
        CallbackQueryHandler(callbacks)
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    app.add_error_handler(error_handler)

    logger.info("TEKIN STARS BOT ishga tushdi.")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
