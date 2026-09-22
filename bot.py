import os
import sqlite3
import logging
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "zerikdim.db"

# 1 Stars = 215 so'm
STARS_RATE = 215

# Referal
REF_MONEY = 1000
REF_STARS = 5

# Premium
PREMIUM_REFERRALS = 40

# Pul chiqarish
MIN_WITHDRAW = 30000

# Nomer
NUMBER_PRICE = 25000

# Telegram nakrutka
NAKRUTKA_PRICE = 7000
NAKRUTKA_PROFIT = 1000

# Majburiy homiy
SPONSOR = "@premyumstarstekin"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

log = logging.getLogger("TEKIN_STARS")

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
            balance REAL DEFAULT 0,
            stars INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER,
            premium_referrals INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            photo_id TEXT,
            status TEXT DEFAULT 'pending',
            amount REAL DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS numbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country TEXT,
            number TEXT,
            sold INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL DEFAULT 0,
            details TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            card TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT UNIQUE
        )
    """)

    con.commit()
    con.close()


# =========================================================
# USER
# =========================================================

def get_user(user_id):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return row


def create_user(user_id, username, referred_by=None):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    )

    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users
            (id, username, balance, stars, referrals,
             referred_by, premium_referrals, created_at)
            VALUES (?, ?, 0, 0, 0, ?, 0, ?)
        """, (
            user_id,
            username or "",
            referred_by,
            datetime.now().isoformat()
        ))

        if referred_by and referred_by != user_id:
            cur.execute("""
                UPDATE users
                SET referrals = referrals + 1,
                    balance = balance + ?,
                    stars = stars + ?
                WHERE id=?
            """, (
                REF_MONEY,
                REF_STARS,
                referred_by
            ))

    else:
        cur.execute(
            "UPDATE users SET username=? WHERE id=?",
            (username or "", user_id)
        )

    con.commit()
    con.close()


def add_balance(user_id, amount):
    con = db()
    cur = con.cursor()

    cur.execute(
        "UPDATE users SET balance=balance+? WHERE id=?",
        (amount, user_id)
    )

    con.commit()
    con.close()


def add_stars(user_id, amount):
    con = db()
    cur = con.cursor()

    cur.execute(
        "UPDATE users SET stars=stars+? WHERE id=?",
        (amount, user_id)
    )

    con.commit()
    con.close()


def remove_balance(user_id, amount):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE id=?",
        (user_id,)
    )

    row = cur.fetchone()

    if not row or row[0] < amount:
        con.close()
        return False

    cur.execute(
        "UPDATE users SET balance=balance-? WHERE id=?",
        (amount, user_id)
    )

    con.commit()
    con.close()

    return True


# =========================================================
# HOMIY
# =========================================================

async def check_sponsor(user_id, context):
    try:
        member = await context.bot.get_chat_member(
            SPONSOR,
            user_id
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception:
        return False


def sponsor_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 Homiy kanal",
                url="https://t.me/premyumstarstekin"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Tekshirish",
                callback_data="check_sponsor"
            )
        ]
    ])


# =========================================================
# MENU
# =========================================================

def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["📱 Nomer olish", "⭐ Stars olish"],
            ["💎 Premium olish", "💰 Pul ishlash"],
            ["💳 Balans", "💸 Pul yechish"],
            ["📈 Telegram nakrutka", "📋 Buyurtmalarim"],
            ["👤 Profil", "ℹ️ Yordam"],
        ],
        resize_keyboard=True
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referred_by = None

    if context.args:
        try:
            referred_by = int(context.args[0])
        except:
            pass

    create_user(
        user.id,
        user.username,
        referred_by
    )

    if not await check_sponsor(user.id, context):
        await update.message.reply_text(
            "🔐 Botdan foydalanish uchun avval homiy kanalga obuna bo‘ling.",
            reply_markup=sponsor_keyboard()
        )
        return

    await update.message.reply_text(
        "🔥 TEKIN STARS BOT ga xush kelibsiz!\n\n"
        "Kerakli bo‘limni tanlang 👇",
        reply_markup=main_menu()
    )


# =========================================================
# SPONSOR TEKSHIRISH
# =========================================================

async def check_sponsor_callback(update, context):
    query = update.callback_query
    await query.answer()

    if await check_sponsor(query.from_user.id, context):
        await query.message.edit_text(
            "✅ Obuna tasdiqlandi!\n\n"
            "Endi botdan foydalanishingiz mumkin."
        )

        await query.message.reply_text(
            "🔥 Asosiy menyu:",
            reply_markup=main_menu()
        )
    else:
        await query.answer(
            "❌ Avval kanalga obuna bo‘ling!",
            show_alert=True
        )


# =========================================================
# BALANS
# =========================================================

async def balance(update, context):
    user = get_user(update.effective_user.id)

    if not user:
        return

    await update.message.reply_text(
        f"💳 BALANS\n\n"
        f"💰 Pul: {user[2]:,.0f} so‘m\n"
        f"⭐ Stars: {user[3]}\n"
        f"👥 Referallar: {user[4]} ta"
    )


# =========================================================
# PROFIL
# =========================================================

async def profile(update, context):
    user = get_user(update.effective_user.id)

    await update.message.reply_text(
        "👤 PROFIL\n\n"
        f"🆔 ID: {user[0]}\n"
        f"👤 Username: @{user[1] if user[1] else 'yo‘q'}\n"
        f"💰 Balans: {user[2]:,.0f} so‘m\n"
        f"⭐ Stars: {user[3]}\n"
        f"👥 Referallar: {user[4]} ta"
    )


# =========================================================
# PUL ISHLASH
# =========================================================

async def earn(update, context):
    user_id = update.effective_user.id

    me = await context.bot.get_me()

    link = f"https://t.me/{me.username}?start={user_id}"

    await update.message.reply_text(
        "💰 PUL ISHLASH\n\n"
        "Har bir taklif qilgan odamingiz uchun:\n\n"
        "💵 +1 000 so‘m\n"
        "⭐ +5 Stars\n\n"
        f"👥 Hozirgi referallar: "
        f"{get_user(user_id)[4]} ta\n\n"
        "🔗 Sizning referal linkingiz:\n"
        f"{link}\n\n"
        "💎 40 ta referal yig‘sangiz — 1 oylik Premium olishingiz mumkin."
    )


# =========================================================
# PREMIUM
# =========================================================

async def premium(update, context):
    user = get_user(update.effective_user.id)

    needed = PREMIUM_REFERRALS - user[4]

    if needed <= 0:
        await update.message.reply_text(
            "🎉 Tabriklaymiz!\n\n"
            "Siz 40 ta referalga yetdingiz.\n"
            "💎 1 oylik Telegram Premium olish uchun "
            "admin bilan bog‘laning."
        )
    else:
        await update.message.reply_text(
            "💎 TELEGRAM PREMIUM\n\n"
            "🎁 1 OYLIK PREMIUM\n\n"
            f"👥 Kerak: 40 referal\n"
            f"✅ Sizda: {user[4]} ta\n"
            f"⏳ Qoldi: {needed} ta"
        )


# =========================================================
# STARS
# =========================================================

async def stars_menu(update, context):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⭐ 50", callback_data="stars_50"),
            InlineKeyboardButton("⭐ 100", callback_data="stars_100"),
        ],
        [
            InlineKeyboardButton("⭐ 200", callback_data="stars_200"),
            InlineKeyboardButton("⭐ 500", callback_data="stars_500"),
        ],
        [
            InlineKeyboardButton("⭐ 1000", callback_data="stars_1000"),
        ],
        [
            InlineKeyboardButton(
                "✍️ Boshqa miqdor",
                callback_data="stars_custom"
            )
        ]
    ])

    await update.message.reply_text(
        "⭐ STARS OLISH\n\n"
        "Kurs: 1 Stars = 215 so‘m\n\n"
        "Kerakli miqdorni tanlang:",
        reply_markup=keyboard
    )


async def stars_callback(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "stars_custom":
        context.user_data["waiting_stars"] = True

        await query.message.reply_text(
            "✍️ Stars miqdorini yozing.\n\n"
            "Masalan: 350"
        )
        return

    amount = int(data.split("_")[1])
    price = amount * STARS_RATE

    context.user_data["star_order"] = amount

    await query.message.reply_text(
        f"⭐ {amount} Stars\n\n"
        f"💰 Narxi: {price:,} so‘m\n\n"
        "💳 Balansdan to‘lash uchun quyidagi tugmani bosing.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💳 Sotib olish",
                    callback_data=f"buy_stars_{amount}"
                )
            ]
        ])
    )


async def buy_stars(update, context):
    query = update.callback_query
    await query.answer()

    amount = int(query.data.split("_")[2])
    price = amount * STARS_RATE

    user_id = query.from_user.id

    if not remove_balance(user_id, price):
        await query.message.reply_text(
            "❌ Balansingiz yetarli emas.\n\n"
            f"Kerak: {price:,} so‘m\n"
            f"Balansingiz: {get_user(user_id)[2]:,.0f} so‘m"
        )
        return

    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO orders
        (user_id, type, amount, details, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        "stars",
        price,
        f"{amount} Stars",
        "pending",
        datetime.now().isoformat()
    ))

    order_id = cur.lastrowid

    con.commit()
    con.close()

    await query.message.reply_text(
        "✅ Buyurtma qabul qilindi!\n\n"
        f"⭐ Stars: {amount}\n"
        f"💰 To‘lov: {price:,} so‘m\n"
        f"🆔 Buyurtma: #{order_id}\n\n"
        "⏳ Admin tasdiqlagach Stars yuboriladi."
    )

    await context.bot.send_message(
        ADMIN_ID,
        f"⭐ YANGI STARS BUYURTMASI\n\n"
        f"🆔 Buyurtma: #{order_id}\n"
        f"👤 User: {user_id}\n"
        f"⭐ Stars: {amount}\n"
        f"💰 Summa: {price:,} so‘m"
    )


# =========================================================
# NOMER OLISH
# =========================================================

async def numbers_menu(update, context):
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT country, COUNT(*)
        FROM numbers
        WHERE sold=0
        GROUP BY country
    """)

    rows = cur.fetchall()
    con.close()

    keyboard = []

    for country, count in rows:
        keyboard.append([
            InlineKeyboardButton(
                f"{country} 🇹🇯 {NUMBER_PRICE:,} so‘m ({count})",
                callback_data=f"number_{country}"
            )
        ])

    if not keyboard:
        await update.message.reply_text(
            "📱 Hozircha mavjud nomer yo‘q."
        )
        return

    await update.message.reply_text(
        "📱 NOMER OLISH\n\n"
        f"💰 Narxi: {NUMBER_PRICE:,} so‘m\n\n"
        "Davlatni tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buy_number(update, context):
    query = update.callback_query
    await query.answer()

    country = query.data.replace("number_", "")
    user_id = query.from_user.id

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT id, number
        FROM numbers
        WHERE country=? AND sold=0
        LIMIT 1
    """, (country,))

    row = cur.fetchone()

    if not row:
        con.close()

        await query.message.reply_text(
            "❌ Bu davlat bo‘yicha nomer qolmagan."
        )
        return

    if not remove_balance(user_id, NUMBER_PRICE):
        con.close()

        await query.message.reply_text(
            f"❌ Balansingiz yetarli emas.\n\n"
            f"Kerak: {NUMBER_PRICE:,} so‘m\n"
            f"Balansingiz: {get_user(user_id)[2]:,.0f} so‘m"
        )
        return

    number_id, number = row

    cur.execute(
        "UPDATE numbers SET sold=1 WHERE id=?",
        (number_id,)
    )

    cur.execute("""
        INSERT INTO orders
        (user_id, type, amount, details, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        "number",
        NUMBER_PRICE,
        f"{country}: {number}",
        "completed",
        datetime.now().isoformat()
    ))

    con.commit()
    con.close()

    await query.message.reply_text(
        "✅ NOMER OLINDI!\n\n"
        f"🌍 Davlat: {country}\n"
        f"📱 Nomer: `{number}`\n\n"
        f"💰 To‘lov: {NUMBER_PRICE:,} so‘m",
        parse_mode="Markdown"
    )

    await context.bot.send_message(
        ADMIN_ID,
        f"📱 NOMER SOTILDI\n\n"
        f"👤 User: {user_id}\n"
        f"🌍 {country}\n"
        f"📱 {number}"
    )


# =========================================================
# NAKRUTKA
# =========================================================

async def nakrutka(update, context):
    await update.message.reply_text(
        "📈 TELEGRAM NAKRUTKA\n\n"
        f"📢 1 ta buyurtma: {NAKRUTKA_PRICE:,} so‘m\n\n"
        "Buyurtma berish uchun:\n"
        "kanal yoki guruh username'ini yuboring.\n\n"
        "Masalan:\n"
        "@kanal"
    )

    context.user_data["nakrutka"] = True


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(update, context):
    text = update.message.text
    user_id = update.effective_user.id

    # Stars custom
    if context.user_data.get("waiting_stars"):
        context.user_data["waiting_stars"] = False

        try:
            amount = int(text)

            if amount < 50 or amount > 1000:
                await update.message.reply_text(
                    "❌ Miqdor 50 dan 1000 gacha bo‘lishi kerak."
                )
                return

            price = amount * STARS_RATE

            context.user_data["custom_star_amount"] = amount

            await update.message.reply_text(
                f"⭐ {amount} Stars\n"
                f"💰 {price:,} so‘m\n\n"
                "Sotib olish uchun tasdiqlang.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ Sotib olish",
                            callback_data=f"buy_stars_{amount}"
                        )
                    ]
                ])
            )

        except:
            await update.message.reply_text(
                "❌ Faqat raqam yozing. Masalan: 350"
            )

        return

    # Nakrutka
    if context.user_data.get("nakrutka"):
        context.user_data["nakrutka"] = False

        order = text.strip()

        if not order.startswith("@"):
            await update.message.reply_text(
                "❌ Username @ bilan boshlanishi kerak."
            )
            return

        con = db()
        cur = con.cursor()

        cur.execute("""
            INSERT INTO orders
            (user_id, type, amount, details, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            "nakrutka",
            NAKRUTKA_PRICE,
            order,
            "pending",
            datetime.now().isoformat()
        ))

        order_id = cur.lastrowid

        con.commit()
        con.close()

        if not remove_balance(user_id, NAKRUTKA_PRICE):
            await update.message.reply_text(
                "❌ Balansingiz yetarli emas."
            )
            return

        await update.message.reply_text(
            f"✅ Buyurtma qabul qilindi!\n\n"
            f"📢 {order}\n"
            f"💰 {NAKRUTKA_PRICE:,} so‘m\n"
            f"🆔 #{order_id}"
        )

        await context.bot.send_message(
            ADMIN_ID,
            f"📈 NAKRUTKA BUYURTMASI\n\n"
            f"🆔 #{order_id}\n"
            f"👤 User: {user_id}\n"
            f"📢 {order}\n"
            f"💰 {NAKRUTKA_PRICE:,} so‘m"
        )

        return

    # Menu
    if text == "📱 Nomer olish":
        await numbers_menu(update, context)

    elif text == "⭐ Stars olish":
        await stars_menu(update, context)

    elif text == "💎 Premium olish":
        await premium(update, context)

    elif text == "💰 Pul ishlash":
        await earn(update, context)

    elif text == "💳 Balans":
        await balance(update, context)

    elif text == "👤 Profil":
        await profile(update, context)

    elif text == "📈 Telegram nakrutka":
        await nakrutka(update, context)

    elif text == "💸 Pul yechish":
        context.user_data["withdraw"] = True

        await update.message.reply_text(
            f"💸 PUL YECHISH\n\n"
            f"Minimum: {MIN_WITHDRAW:,} so‘m\n\n"
            "Avval summani yozing.\n"
            "Masalan: 30000"
        )

    elif text == "📋 Buyurtmalarim":
        await my_orders(update, context)

    elif text == "ℹ️ Yordam":
        await update.message.reply_text(
            "ℹ️ YORDAM\n\n"
            "Muammo yoki savollar bo‘lsa admin bilan bog‘laning."
        )

    elif text == "👑 Admin":
        if user_id == ADMIN_ID:
            await admin_menu(update, context)


# =========================================================
# PUL TO‘LDIRISH / CHEK
# =========================================================

async def payment_photo(update, context):
    user_id = update.effective_user.id

    if not update.message.photo:
        return

    photo = update.message.photo[-1].file_id

    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO payments
        (user_id, photo_id, status, created_at)
        VALUES (?, ?, 'pending', ?)
    """, (
        user_id,
        photo,
        datetime.now().isoformat()
    ))

    payment_id = cur.lastrowid

    con.commit()
    con.close()

    await update.message.reply_text(
        "✅ Chek qabul qilindi.\n\n"
        "⏳ Admin tekshiradi va tasdiqlagandan so‘ng "
        "hisobingizga pul qo‘shiladi."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💰 Summani kiritish",
                callback_data=f"payment_{payment_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Rad etish",
                callback_data=f"reject_payment_{payment_id}"
            )
        ]
    ])

    await context.bot.send_photo(
        ADMIN_ID,
        photo,
        caption=(
            f"💳 YANGI TO‘LOV CHEKI\n\n"
            f"🆔 Payment: #{payment_id}\n"
            f"👤 User ID: {user_id}\n\n"
            "Tasdiqlash uchun summani o‘zingiz kiriting."
        ),
        reply_markup=keyboard
    )


# =========================================================
# ADMIN TO‘LOV SUMMASI
# =========================================================

async def payment_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    payment_id = int(query.data.split("_")[1])

    context.user_data["payment_id"] = payment_id
    context.user_data["waiting_payment_amount"] = True

    await query.message.reply_text(
        f"💰 Payment #{payment_id}\n\n"
        "Hisobga qo‘shiladigan summani yozing.\n\n"
        "Masalan:\n50000"
    )


async def reject_payment(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    payment_id = int(query.data.split("_")[2])

    con = db()
    cur = con.cursor()

    cur.execute(
        "UPDATE payments SET status='rejected' WHERE id=?",
        (payment_id,)
    )

    con.commit()
    con.close()

    await query.message.reply_text(
        f"❌ Payment #{payment_id} rad etildi."
    )


# =========================================================
# WITHDRAW
# =========================================================

async def withdrawal_text(update, context):
    if not context.user_data.get("withdraw"):
        return False

    user_id = update.effective_user.id

    try:
        amount = float(update.message.text)

        if amount < MIN_WITHDRAW:
            await update.message.reply_text(
                f"❌ Minimum {MIN_WITHDRAW:,} so‘m."
            )
            return True

        user = get_user(user_id)

        if user[2] < amount:
            await update.message.reply_text(
                "❌ Balansingiz yetarli emas."
            )
            return True

        context.user_data["withdraw_amount"] = amount
        context.user_data["withdraw"] = False
        context.user_data["waiting_card"] = True

        await update.message.reply_text(
            "💳 Endi karta raqamingizni yuboring."
        )

        return True

    except:
        await update.message.reply_text(
            "❌ Summani to‘g‘ri yozing."
        )
        return True


async def withdrawal_card(update, context):
    if not context.user_data.get("waiting_card"):
        return False

    user_id = update.effective_user.id
    card = update.message.text.strip()
    amount = context.user_data["withdraw_amount"]

    if not remove_balance(user_id, amount):
        await update.message.reply_text(
            "❌ Balans yetarli emas."
        )
        return True

    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO withdrawals
        (user_id, amount, card, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        user_id,
        amount,
        card,
        datetime.now().isoformat()
    ))

    wid = cur.lastrowid

    con.commit()
    con.close()

    context.user_data["waiting_card"] = False

    await update.message.reply_text(
        f"✅ Pul yechish so‘rovi yuborildi.\n\n"
        f"💰 Summa: {amount:,.0f} so‘m\n"
        f"🆔 #{wid}\n\n"
        "⏳ Admin tekshiradi."
    )

    await context.bot.send_message(
        ADMIN_ID,
        f"💸 YANGI PUL YECHISH\n\n"
        f"🆔 #{wid}\n"
        f"👤 User: {user_id}\n"
        f"💰 {amount:,.0f} so‘m\n"
        f"💳 Karta: {card}"
    )

    return True


# =========================================================
# BUYURTMALAR
# =========================================================

async def my_orders(update, context):
    user_id = update.effective_user.id

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT id, type, amount, details, status
        FROM orders
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (user_id,))

    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text(
            "📋 Sizda hali buyurtmalar yo‘q."
        )
        return

    text = "📋 BUYURTMALARIM\n\n"

    for row in rows:
        text += (
            f"🆔 #{row[0]}\n"
            f"📦 {row[1]}\n"
            f"💰 {row[2]:,.0f} so‘m\n"
            f"📌 {row[4]}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# ADMIN MENU
# =========================================================

def admin_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["➕ Balans qo‘shish", "➕ Nomer qo‘shish"],
            ["⭐ Stars berish", "📊 Statistika"],
            ["📢 Reklama", "💸 Chiqimlar"],
            ["🏠 Asosiy menyu"],
        ],
        resize_keyboard=True
    )


async def admin_menu(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "👑 ADMIN PANEL",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN TEXT
# =========================================================

async def admin_text(update, context):
    if update.effective_user.id != ADMIN_ID:
        return False

    text = update.message.text

    if context.user_data.get("waiting_payment_amount"):
        try:
            amount = float(text)
        except:
            await update.message.reply_text(
                "❌ Summani raqam bilan yozing."
            )
            return True

        payment_id = context.user_data["payment_id"]

        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT user_id FROM payments WHERE id=?",
            (payment_id,)
        )

        row = cur.fetchone()

        if not row:
            con.close()
            return True

        user_id = row[0]

        cur.execute("""
            UPDATE payments
            SET status='approved', amount=?
            WHERE id=?
        """, (
            amount,
            payment_id
        ))

        cur.execute(
            "UPDATE users SET balance=balance+? WHERE id=?",
            (amount, user_id)
        )

        con.commit()
        con.close()

        context.user_data["waiting_payment_amount"] = False

        await update.message.reply_text(
            f"✅ Payment #{payment_id} tasdiqlandi.\n"
            f"💰 {amount:,.0f} so‘m qo‘shildi."
        )

        try:
            await context.bot.send_message(
                user_id,
                f"✅ To‘lov tasdiqlandi!\n\n"
                f"💰 Hisobingizga {amount:,.0f} so‘m qo‘shildi."
            )
        except:
            pass

        return True

    if text == "➕ Balans qo‘shish":
        context.user_data["admin_balance"] = True

        await update.message.reply_text(
            "👤 User ID va summani yozing.\n\n"
            "Misol:\n"
            "123456789 50000"
        )
        return True

    if context.user_data.get("admin_balance"):
        parts = text.split()

        if len(parts) != 2:
            await update.message.reply_text(
                "❌ Misol: 123456789 50000"
            )
            return True

        try:
            uid = int(parts[0])
            amount = float(parts[1])
        except:
            await update.message.reply_text(
                "❌ Xato."
            )
            return True

        add_balance(uid, amount)

        context.user_data["admin_balance"] = False

        await update.message.reply_text(
            "✅ Balans qo‘shildi."
        )

        try:
            await context.bot.send_message(
                uid,
                f"💰 Hisobingizga {amount:,.0f} so‘m qo‘shildi."
            )
        except:
            pass

        return True

    if text == "⭐ Stars berish":
        context.user_data["admin_stars"] = True

        await update.message.reply_text(
            "User ID va Stars miqdorini yozing.\n\n"
            "Misol:\n"
            "123456789 100"
        )
        return True

    if context.user_data.get("admin_stars"):
        parts = text.split()

        try:
            uid = int(parts[0])
            amount = int(parts[1])
        except:
            await update.message.reply_text(
                "❌ Misol: 123456789 100"
            )
            return True

        add_stars(uid, amount)

        context.user_data["admin_stars"] = False

        await update.message.reply_text(
            "✅ Stars berildi."
        )

        try:
            await context.bot.send_message(
                uid,
                f"⭐ Sizga {amount} Stars berildi!"
            )
        except:
            pass

        return True

    if text == "➕ Nomer qo‘shish":
        context.user_data["admin_number"] = True

        await update.message.reply_text(
            "Davlat va nomerni yozing.\n\n"
            "Misol:\n"
            "Tojikiston +992900000000\n\n"
            "Yoki:\n"
            "Rossiya +79990000000"
        )
        return True

    if context.user_data.get("admin_number"):
        parts = text.split(maxsplit=1)

        if len(parts) != 2:
            await update.message.reply_text(
                "❌ Davlat va nomerni yozing."
            )
            return True

        country = parts[0]
        number = parts[1]

        con = db()
        cur = con.cursor()

        cur.execute("""
            INSERT INTO numbers(country, number, sold)
            VALUES (?, ?, 0)
        """, (
            country,
            number
        ))

        con.commit()
        con.close()

        context.user_data["admin_number"] = False

        await update.message.reply_text(
            "✅ Nomer qo‘shildi."
        )

        return True

    if text == "📊 Statistika":
        con = db()
        cur = con.cursor()

        cur.execute("SELECT COUNT(*) FROM users")
        users = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(balance),0) FROM users")
        balance_sum = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM numbers WHERE sold=0")
        numbers = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM orders"
        )
        orders = cur.fetchone()[0]

        con.close()

        await update.message.reply_text(
            "📊 STATISTIKA\n\n"
            f"👥 Users: {users}\n"
            f"💰 Balanslar: {balance_sum:,.0f} so‘m\n"
            f"📱 Mavjud nomerlar: {numbers}\n"
            f"📦 Buyurtmalar: {orders}"
        )

        return True

    if text == "🏠 Asosiy menyu":
        await update.message.reply_text(
            "🏠 Asosiy menyu",
            reply_markup=main_menu()
        )
        return True

    return False


# =========================================================
# ADMIN COMMAND
# =========================================================

async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "👑 ADMIN PANEL",
        reply_markup=admin_keyboard()
    )


# =========================================================
# UNIVERSAL MESSAGE
# =========================================================

async def message_handler(update, context):
    if update.effective_user.id == ADMIN_ID:
        if await admin_text(update, context):
            return

    if await withdrawal_text(update, context):
        return

    if await withdrawal_card(update, context):
        return

    await text_handler(update, context)


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))

    app.add_handler(
        CallbackQueryHandler(
            check_sponsor_callback,
            pattern="^check_sponsor$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            stars_callback,
            pattern="^stars_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            buy_stars,
            pattern="^buy_stars_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            buy_number,
            pattern="^number_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            payment_callback,
            pattern="^payment_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            reject_payment,
            pattern="^reject_payment_"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            payment_photo
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    print("🔥 TEKIN STARS BOT ISHLAYAPTI")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
