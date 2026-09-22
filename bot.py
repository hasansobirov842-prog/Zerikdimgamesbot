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

REF_MONEY = 1000
REF_STARS = 5

MIN_WITHDRAW = 30000

STARS_RATE = 215

TAJIK_NUMBER_PRICE = 25000
RUSSIAN_NUMBER_PRICE = 25000

PREMIUM_REFERRALS = 40

PAYMENT_CARD = "5614681008971867"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

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
        stars REAL DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        referred_by INTEGER,
        premium_claimed INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        status TEXT DEFAULT 'pending',
        receipt_file TEXT,
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
    CREATE TABLE IF NOT EXISTS number_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        country TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
    """)

    con.commit()
    con.close()


def get_user(user_id):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return row


def add_user(user_id, username, referrer=None):
    if get_user(user_id):
        return

    con = db()
    cur = con.cursor()

    cur.execute("""
    INSERT INTO users
    (id, username, balance, stars, referrals, referred_by, premium_claimed, created_at)
    VALUES (?, ?, 0, 0, 0, ?, 0, ?)
    """, (
        user_id,
        username or "",
        referrer,
        datetime.now().isoformat()
    ))

    if referrer and referrer != user_id:
        cur.execute("""
        UPDATE users
        SET balance = balance + ?,
            stars = stars + ?,
            referrals = referrals + 1
        WHERE id=?
        """, (REF_MONEY, REF_STARS, referrer))

    con.commit()
    con.close()


def change_balance(user_id, amount):
    con = db()
    con.execute(
        "UPDATE users SET balance=balance+? WHERE id=?",
        (amount, user_id)
    )
    con.commit()
    con.close()


def change_stars(user_id, amount):
    con = db()
    con.execute(
        "UPDATE users SET stars=stars+? WHERE id=?",
        (amount, user_id)
    )
    con.commit()
    con.close()


def set_balance(user_id, amount):
    con = db()
    con.execute(
        "UPDATE users SET balance=? WHERE id=?",
        (amount, user_id)
    )
    con.commit()
    con.close()


def get_stats(user_id):
    con = db()
    cur = con.cursor()

    cur.execute("""
    SELECT balance, stars, referrals, premium_claimed
    FROM users WHERE id=?
    """, (user_id,))

    row = cur.fetchone()
    con.close()
    return row


# =========================================================
# KLAVIATURA
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📱 Nomer olish", "⭐ Stars olish"],
            ["💎 Premium olish", "💰 Pul ishlash"],
            ["💳 Hisobim", "💸 Pul chiqarish"],
            ["📋 Buyurtmalarim", "ℹ️ Yordam"],
        ],
        resize_keyboard=True
    )


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="admin_users"),
        ],
        [
            InlineKeyboardButton("💰 To‘lovlar", callback_data="admin_payments"),
            InlineKeyboardButton("📱 Nomer buyurtmalari", callback_data="admin_numbers"),
        ],
        [
            InlineKeyboardButton("💸 Pul chiqarish", callback_data="admin_withdraw"),
        ],
    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    referrer = None

    if context.args:
        try:
            referrer = int(context.args[0])
        except:
            referrer = None

    add_user(
        user.id,
        user.username,
        referrer
    )

    text = (
        "🔥 <b>ARZON BOT</b>\n\n"
        "Kerakli bo‘limni tanlang 👇\n\n"
        "📱 Nomer olish\n"
        "⭐ Telegram Stars olish\n"
        "💎 Premium olish\n"
        "💰 Referal orqali pul ishlash"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# HISOBIM
# =========================================================

async def account(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    row = get_stats(user_id)

    if not row:
        add_user(
            user_id,
            update.effective_user.username
        )
        row = get_stats(user_id)

    balance, stars, refs, premium = row

    await update.message.reply_text(
        f"💳 <b>Hisobingiz</b>\n\n"
        f"💰 Balans: <b>{balance:,.0f} so‘m</b>\n"
        f"⭐ Stars: <b>{stars:,.0f}</b>\n"
        f"👥 Referallar: <b>{refs} ta</b>",
        parse_mode="HTML"
    )


# =========================================================
# NOMER OLISH
# =========================================================

async def numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "📱 <b>NOMER OLISH</b>\n\n"
        "🇹🇯 Tojikiston — <b>25 000 so‘m</b>\n"
        "🇷🇺 Rossiya — <b>25 000 so‘m</b>\n\n"
        "Kerakli davlatni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🇹🇯 Tojikiston — 25 000",
                    callback_data="number_tajik"
                )
            ],
            [
                InlineKeyboardButton(
                    "🇷🇺 Rossiya — 25 000",
                    callback_data="number_russia"
                )
            ]
        ])
    )


async def number_order(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "number_tajik":
        country = "🇹🇯 Tojikiston"
        price = TAJIK_NUMBER_PRICE
    else:
        country = "🇷🇺 Rossiya"
        price = RUSSIAN_NUMBER_PRICE

    row = get_stats(user_id)

    if row[0] < price:
        await query.message.reply_text(
            f"❌ Balansingiz yetarli emas.\n\n"
            f"Narx: {price:,} so‘m\n"
            f"Balans: {row[0]:,.0f} so‘m"
        )
        return

    change_balance(user_id, -price)

    con = db()
    cur = con.cursor()

    cur.execute("""
    INSERT INTO number_orders
    (user_id, country, amount, status, created_at)
    VALUES (?, ?, ?, 'pending', ?)
    """, (
        user_id,
        country,
        price,
        datetime.now().isoformat()
    ))

    order_id = cur.lastrowid

    con.commit()
    con.close()

    await query.message.reply_text(
        f"✅ Buyurtma qabul qilindi!\n\n"
        f"📱 Davlat: {country}\n"
        f"💰 Narx: {price:,} so‘m\n"
        f"🆔 Buyurtma: #{order_id}\n\n"
        f"⏳ Admin tasdiqlashini kuting."
    )

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"📱 <b>YANGI NOMER BUYURTMASI</b>\n\n"
                f"👤 ID: <code>{user_id}</code>\n"
                f"🌍 {country}\n"
                f"💰 {price:,} so‘m\n"
                f"🆔 #{order_id}",
                parse_mode="HTML"
            )
        except:
            pass


# =========================================================
# STARS
# =========================================================

async def stars(update: Update, context: ContextTypes.DEFAULT_TYPE):

    buttons = [
        [
            InlineKeyboardButton("⭐ 50 Stars", callback_data="stars_50"),
            InlineKeyboardButton("⭐ 100 Stars", callback_data="stars_100"),
        ],
        [
            InlineKeyboardButton("⭐ 200 Stars", callback_data="stars_200"),
            InlineKeyboardButton("⭐ 500 Stars", callback_data="stars_500"),
        ],
        [
            InlineKeyboardButton("⭐ 1000 Stars", callback_data="stars_1000"),
        ],
        [
            InlineKeyboardButton(
                "✏️ Boshqa miqdor",
                callback_data="stars_custom"
            )
        ]
    ]

    await update.message.reply_text(
        "⭐ <b>STARS OLISH</b>\n\n"
        f"Kurs: <b>1 Stars = {STARS_RATE} so‘m</b>\n\n"
        "Kerakli miqdorni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def stars_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    amount = int(query.data.split("_")[1])
    price = amount * STARS_RATE

    user_id = query.from_user.id
    row = get_stats(user_id)

    if row[0] < price:
        await query.message.reply_text(
            f"❌ Balans yetarli emas.\n\n"
            f"⭐ {amount} Stars\n"
            f"💰 Narx: {price:,} so‘m\n"
            f"💳 Balansingiz: {row[0]:,.0f} so‘m"
        )
        return

    change_balance(user_id, -price)
    change_stars(user_id, amount)

    await query.message.reply_text(
        f"✅ <b>Stars qo‘shildi!</b>\n\n"
        f"⭐ Miqdor: {amount}\n"
        f"💰 To‘lov: {price:,} so‘m",
        parse_mode="HTML"
    )


async def stars_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["waiting_stars"] = True

    await update.callback_query.answer()

    await update.callback_query.message.reply_text(
        "✏️ Stars miqdorini yozing.\n\n"
        "Masalan: <b>750</b>",
        parse_mode="HTML"
    )


async def custom_stars_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("waiting_stars"):
        return False

    try:
        amount = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Faqat raqam yozing.")
        return True

    if amount < 1:
        await update.message.reply_text("❌ Miqdor 1 dan katta bo‘lsin.")
        return True

    price = amount * STARS_RATE
    user_id = update.effective_user.id

    row = get_stats(user_id)

    if row[0] < price:
        await update.message.reply_text(
            f"❌ Balans yetarli emas.\n\n"
            f"⭐ {amount} Stars\n"
            f"💰 Kerak: {price:,} so‘m\n"
            f"💳 Balans: {row[0]:,.0f} so‘m"
        )
        context.user_data["waiting_stars"] = False
        return True

    change_balance(user_id, -price)
    change_stars(user_id, amount)

    context.user_data["waiting_stars"] = False

    await update.message.reply_text(
        f"✅ <b>{amount} Stars</b> qo‘shildi!\n\n"
        f"💰 {price:,} so‘m",
        parse_mode="HTML"
    )

    return True


# =========================================================
# PREMIUM
# =========================================================

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):

    row = get_stats(update.effective_user.id)

    refs = row[2]
    claimed = row[3]

    if claimed:
        await update.message.reply_text(
            "❌ Siz 1 oylik Premiumni oldin olgansiz."
        )
        return

    if refs < PREMIUM_REFERRALS:

        left = PREMIUM_REFERRALS - refs

        await update.message.reply_text(
            f"💎 <b>TELEGRAM PREMIUM</b>\n\n"
            f"🎁 1 oylik Premium\n"
            f"👥 Kerak: <b>{PREMIUM_REFERRALS} ta referal</b>\n"
            f"👤 Sizda: <b>{refs} ta</b>\n\n"
            f"Qolgan: <b>{left} ta</b>",
            parse_mode="HTML"
        )

        return

    con = db()

    con.execute(
        "UPDATE users SET premium_claimed=1 WHERE id=?",
        (update.effective_user.id,)
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        "🎉 <b>Tabriklaymiz!</b>\n\n"
        "💎 Siz 1 oylik Telegram Premium uchun mukofotni oldingiz.\n\n"
        "Admin siz bilan bog‘lanadi.",
        parse_mode="HTML"
    )

    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"💎 <b>PREMIUM MUKOFOT</b>\n\n"
            f"👤 User ID: <code>{update.effective_user.id}</code>\n"
            f"👥 40 ta referal yig‘di.",
            parse_mode="HTML"
        )


# =========================================================
# PUL ISHLASH
# =========================================================

async def earning(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    bot_username = (await context.bot.get_me()).username

    link = f"https://t.me/{bot_username}?start={user_id}"

    row = get_stats(user_id)

    await update.message.reply_text(
        f"💰 <b>PUL ISHLASH</b>\n\n"
        f"👥 1 ta referal = <b>{REF_MONEY:,} so‘m</b>\n"
        f"⭐ 1 ta referal = <b>{REF_STARS} Stars</b>\n\n"
        f"👥 Sizning referallaringiz: <b>{row[2]} ta</b>\n\n"
        f"🔗 <b>Sizning referal havolangiz:</b>\n"
        f"<code>{link}</code>\n\n"
        f"40 ta referal yig‘sangiz:\n"
        f"💎 1 oylik Premium olish imkoniyati mavjud.",
        parse_mode="HTML"
    )


# =========================================================
# PUL TO‘LDIRISH
# =========================================================

async def topup(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["waiting_payment_amount"] = True

    await update.message.reply_text(
        f"💳 <b>HISOB TO‘LDIRISH</b>\n\n"
        f"💳 Karta: <code>{PAYMENT_CARD}</code>\n\n"
        f"1️⃣ Kartaga pul o‘tkazing.\n"
        f"2️⃣ To‘lov summasini yozing.\n"
        f"3️⃣ Keyin chek rasmini yuboring.\n\n"
        f"Masalan: <b>50000</b>",
        parse_mode="HTML"
    )


async def payment_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("waiting_payment_amount"):
        return False

    try:
        amount = float(update.message.text.replace(",", "").replace(" ", ""))
    except:
        await update.message.reply_text("❌ Summani raqamda yozing.")
        return True

    if amount < 1000:
        await update.message.reply_text(
            "❌ Minimal to‘lov 1 000 so‘m."
        )
        return True

    context.user_data["payment_amount"] = amount
    context.user_data["waiting_payment_amount"] = False
    context.user_data["waiting_receipt"] = True

    await update.message.reply_text(
        f"💰 Summa: <b>{amount:,.0f} so‘m</b>\n\n"
        "Endi <b>chek rasmini</b> yuboring.",
        parse_mode="HTML"
    )

    return True


async def receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("waiting_receipt"):
        return False

    if not update.message.photo:
        await update.message.reply_text(
            "❌ Chekni rasm ko‘rinishida yuboring."
        )
        return True

    amount = context.user_data.get("payment_amount")

    photo = update.message.photo[-1]

    con = db()
    cur = con.cursor()

    cur.execute("""
    INSERT INTO payments
    (user_id, amount, status, receipt_file, created_at)
    VALUES (?, ?, 'pending', ?, ?)
    """, (
        update.effective_user.id,
        amount,
        photo.file_id,
        datetime.now().isoformat()
    ))

    payment_id = cur.lastrowid

    con.commit()
    con.close()

    context.user_data["waiting_receipt"] = False
    context.user_data["payment_amount"] = None

    await update.message.reply_text(
        f"✅ Chek qabul qilindi.\n\n"
        f"💰 Summa: {amount:,.0f} so‘m\n"
        f"🆔 To‘lov: #{payment_id}\n\n"
        f"⏳ Admin tasdiqlashini kuting."
    )

    if ADMIN_ID:
        try:
            await context.bot.send_photo(
                ADMIN_ID,
                photo.file_id,
                caption=(
                    f"💳 YANGI TO‘LOV\n\n"
                    f"👤 User ID: {update.effective_user.id}\n"
                    f"💰 Summa: {amount:,.0f} so‘m\n"
                    f"🆔 #{payment_id}"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ Tasdiqlash",
                            callback_data=f"pay_ok_{payment_id}"
                        ),
                        InlineKeyboardButton(
                            "❌ Rad etish",
                            callback_data=f"pay_no_{payment_id}"
                        )
                    ]
                ])
            )
        except:
            pass

    return True


# =========================================================
# PUL CHIQARISH
# =========================================================

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):

    row = get_stats(update.effective_user.id)

    if row[0] < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Pul chiqarish uchun minimal summa "
            f"<b>{MIN_WITHDRAW:,} so‘m</b>.\n\n"
            f"💰 Sizda: {row[0]:,.0f} so‘m",
            parse_mode="HTML"
        )
        return

    context.user_data["withdraw_amount"] = True

    await update.message.reply_text(
        f"💸 <b>PUL CHIQARISH</b>\n\n"
        f"Minimal: {MIN_WITHDRAW:,} so‘m\n"
        f"Balans: {row[0]:,.0f} so‘m\n\n"
        f"Qancha chiqarishni yozing:",
        parse_mode="HTML"
    )


async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("withdraw_amount"):
        return False

    try:
        amount = float(update.message.text.replace(",", "").replace(" ", ""))
    except:
        await update.message.reply_text("❌ Raqam yozing.")
        return True

    user_id = update.effective_user.id
    row = get_stats(user_id)

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimal {MIN_WITHDRAW:,} so‘m."
        )
        return True

    if amount > row[0]:
        await update.message.reply_text(
            "❌ Balansingiz yetarli emas."
        )
        return True

    context.user_data["withdraw_amount_value"] = amount
    context.user_data["withdraw_amount"] = False
    context.user_data["waiting_card"] = True

    await update.message.reply_text(
        "💳 Pul tushadigan karta raqamini yuboring."
    )

    return True


async def withdraw_card(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("waiting_card"):
        return False

    card = update.message.text.strip()
    amount = context.user_data.get("withdraw_amount_value")
    user_id = update.effective_user.id

    row = get_stats(user_id)

    if amount > row[0]:
        await update.message.reply_text(
            "❌ Balans yetarli emas."
        )
        return True

    change_balance(user_id, -amount)

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

    withdrawal_id = cur.lastrowid

    con.commit()
    con.close()

    context.user_data["waiting_card"] = False
    context.user_data["withdraw_amount_value"] = None

    await update.message.reply_text(
        f"✅ Pul chiqarish so‘rovi yuborildi.\n\n"
        f"💰 Summa: {amount:,.0f} so‘m\n"
        f"🆔 #{withdrawal_id}\n\n"
        f"⏳ Admin to‘lovni amalga oshiradi."
    )

    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"💸 <b>PUL CHIQARISH</b>\n\n"
            f"👤 User: <code>{user_id}</code>\n"
            f"💰 {amount:,.0f} so‘m\n"
            f"💳 <code>{card}</code>\n"
            f"🆔 #{withdrawal_id}",
            parse_mode="HTML"
        )

    return True


# =========================================================
# BUYURTMALAR
# =========================================================

async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    con = db()
    cur = con.cursor()

    cur.execute("""
    SELECT id, country, amount, status
    FROM number_orders
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 10
    """, (user_id,))

    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text(
            "📋 Sizda hozircha buyurtmalar yo‘q."
        )
        return

    text = "📋 <b>BUYURTMALARIM</b>\n\n"

    for row in rows:
        text += (
            f"🆔 #{row[0]}\n"
            f"🌍 {row[1]}\n"
            f"💰 {row[2]:,.0f} so‘m\n"
            f"📌 {row[3]}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# YORDAM
# =========================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "ℹ️ <b>YORDAM</b>\n\n"
        "📱 Nomer olish — Tojik/Rossiya nomerlari\n"
        "⭐ Stars olish — 50 dan boshlab\n"
        "💎 Premium — 40 referalga\n"
        "💰 Pul ishlash — referal orqali\n"
        "💳 Hisobim — balans va Stars\n"
        "💸 Pul chiqarish — minimal 30 000 so‘m\n"
        "💳 Hisob to‘ldirish — chek orqali",
        parse_mode="HTML"
    )


# =========================================================
# ADMIN
# =========================================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "👑 <b>ADMIN PANEL</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    data = query.data

    # -----------------------------------------------------
    # TO‘LOV TASDIQLASH
    # -----------------------------------------------------

    if data.startswith("pay_ok_"):

        payment_id = int(data.split("_")[2])

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT user_id, amount, status
        FROM payments
        WHERE id=?
        """, (payment_id,))

        row = cur.fetchone()

        if not row:
            con.close()
            await query.message.reply_text("❌ To‘lov topilmadi.")
            return

        user_id, amount, status = row

        if status != "pending":
            con.close()
            await query.message.reply_text(
                "⚠️ Bu to‘lov allaqachon ko‘rib chiqilgan."
            )
            return

        cur.execute("""
        UPDATE payments
        SET status='approved'
        WHERE id=?
        """, (payment_id,))

        cur.execute("""
        UPDATE users
        SET balance=balance+?
        WHERE id=?
        """, (amount, user_id))

        con.commit()
        con.close()

        await query.message.reply_text(
            f"✅ To‘lov tasdiqlandi.\n"
            f"💰 {amount:,.0f} so‘m qo‘shildi."
        )

        try:
            await context.bot.send_message(
                user_id,
                f"✅ <b>To‘lov tasdiqlandi!</b>\n\n"
                f"💰 Balansingizga "
                f"<b>{amount:,.0f} so‘m</b> qo‘shildi.",
                parse_mode="HTML"
            )
        except:
            pass

    # -----------------------------------------------------
    # TO‘LOV RAD
    # -----------------------------------------------------

    elif data.startswith("pay_no_"):

        payment_id = int(data.split("_")[2])

        con = db()

        cur = con.cursor()

        cur.execute("""
        SELECT user_id, status
        FROM payments
        WHERE id=?
        """, (payment_id,))

        row = cur.fetchone()

        if not row:
            con.close()
            return

        user_id, status = row

        if status == "pending":
            cur.execute("""
            UPDATE payments
            SET status='rejected'
            WHERE id=?
            """, (payment_id,))

            con.commit()

        con.close()

        await query.message.reply_text(
            "❌ To‘lov rad etildi."
        )

        try:
            await context.bot.send_message(
                user_id,
                "❌ To‘lovingiz rad etildi. Chek yoki summa noto‘g‘ri bo‘lishi mumkin."
            )
        except:
            pass

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    elif data == "admin_users":

        con = db()
        cur = con.cursor()

        cur.execute("SELECT COUNT(*) FROM users")
        users = cur.fetchone()[0]

        cur.execute("SELECT SUM(balance) FROM users")
        balance = cur.fetchone()[0] or 0

        cur.execute("SELECT SUM(stars) FROM users")
        stars_total = cur.fetchone()[0] or 0

        con.close()

        await query.message.reply_text(
            f"👥 <b>STATISTIKA</b>\n\n"
            f"👤 Foydalanuvchilar: {users}\n"
            f"💰 Umumiy balans: {balance:,.0f} so‘m\n"
            f"⭐ Umumiy Stars: {stars_total:,.0f}",
            parse_mode="HTML"
        )

    # -----------------------------------------------------
    # PAYMENTS
    # -----------------------------------------------------

    elif data == "admin_payments":

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT id, user_id, amount, status
        FROM payments
        ORDER BY id DESC
        LIMIT 15
        """)

        rows = cur.fetchall()
        con.close()

        if not rows:
            await query.message.reply_text(
                "To‘lovlar yo‘q."
            )
            return

        text = "💳 <b>TO‘LOVLAR</b>\n\n"

        for r in rows:
            text += (
                f"#{r[0]} | "
                f"ID: {r[1]} | "
                f"{r[2]:,.0f} so‘m | "
                f"{r[3]}\n"
            )

        await query.message.reply_text(
            text,
            parse_mode="HTML"
        )

    # -----------------------------------------------------
    # NUMBERS
    # -----------------------------------------------------

    elif data == "admin_numbers":

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT id, user_id, country, amount, status
        FROM number_orders
        ORDER BY id DESC
        LIMIT 15
        """)

        rows = cur.fetchall()
        con.close()

        if not rows:
            await query.message.reply_text(
                "Nomer buyurtmalari yo‘q."
            )
            return

        text = "📱 <b>NOMER BUYURTMALARI</b>\n\n"

        for r in rows:
            text += (
                f"#{r[0]}\n"
                f"👤 {r[1]}\n"
                f"🌍 {r[2]}\n"
                f"💰 {r[3]:,.0f}\n"
                f"📌 {r[4]}\n\n"
            )

        await query.message.reply_text(
            text,
            parse_mode="HTML"
        )

    # -----------------------------------------------------
    # WITHDRAW
    # -----------------------------------------------------

    elif data == "admin_withdraw":

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT id, user_id, amount, card, status
        FROM withdrawals
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT 15
        """)

        rows = cur.fetchall()
        con.close()

        if not rows:
            await query.message.reply_text(
                "⏳ Kutilayotgan pul chiqarishlar yo‘q."
            )
            return

        text = "💸 <b>PUL CHIQARISHLAR</b>\n\n"

        for r in rows:
            text += (
                f"#{r[0]}\n"
                f"👤 {r[1]}\n"
                f"💰 {r[2]:,.0f} so‘m\n"
                f"💳 {r[3]}\n"
                f"📌 {r[4]}\n\n"
            )

        await query.message.reply_text(
            text,
            parse_mode="HTML"
        )


# =========================================================
# MESSAGE ROUTER
# =========================================================

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    # PHOTO / CHEK
    if update.message.photo:
        if await receipt(update, context):
            return

    text = update.message.text

    # MAXSUS INPUTLAR
    if text:
        if await custom_stars_message(update, context):
            return

        if await payment_amount(update, context):
            return

        if await withdraw_amount(update, context):
            return

        if await withdraw_card(update, context):
            return

    # MENU
    if text == "📱 Nomer olish":
        await numbers(update, context)

    elif text == "⭐ Stars olish":
        await stars(update, context)

    elif text == "💎 Premium olish":
        await premium(update, context)

    elif text == "💰 Pul ishlash":
        await earning(update, context)

    elif text == "💳 Hisobim":
        await account(update, context)

    elif text == "💸 Pul chiqarish":
        await withdraw(update, context)

    elif text == "📋 Buyurtmalarim":
        await orders(update, context)

    elif text == "ℹ️ Yordam":
        await help_command(update, context)

    elif text == "💳 Hisob to‘ldirish":
        await topup(update, context)


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        print("BOT_TOKEN topilmadi!")
        return

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("admin", admin)
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern=r"^(pay_ok_|pay_no_|admin_)"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            number_order,
            pattern=r"^number_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            stars_buy,
            pattern=r"^stars_(50|100|200|500|1000)$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            stars_custom,
            pattern=r"^stars_custom$"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            message_router
        )
    )

    print("BOT ISHLADI...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
