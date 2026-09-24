
import os
import sqlite3
import logging
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# =========================================================
# SOZLAMALAR
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "KARTA_RAQAMINI_GITHUB_SECRETGA_QOYING")
DB_FILE = "zerikdim.db"

NUMBER_PRICE = 25000
STARS_RATE = 215                 # 1 Star = 215 so'm
MIN_STARS = 50
MAX_STARS = 1000

REFERRAL_CASH = 1000             # har bir referal uchun so'm
REFERRAL_STARS = 5               # har bir referal uchun Stars
PREMIUM_REFERRALS = 40           # 40 referal = 1 oylik Premium
MIN_WITHDRAW = 30000
TELEGRAM_SERVICE_PRICE = 7000    # Telegram xizmatining boshlang'ich narxi

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("TEKIN_STARS")


# =========================================================
# DATABASE
# =========================================================
def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            stars REAL DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT NULL,
            referral_rewarded INTEGER DEFAULT 0,
            premium_claimed INTEGER DEFAULT 0,
            created_at TEXT,
            last_seen TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            requested_amount REAL DEFAULT 0,
            admin_amount REAL DEFAULT 0,
            receipt_file_id TEXT DEFAULT '',
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
        CREATE TABLE IF NOT EXISTS numbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country TEXT,
            number TEXT UNIQUE,
            price REAL DEFAULT 25000,
            sold INTEGER DEFAULT 0,
            buyer_id INTEGER DEFAULT NULL,
            sold_at TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS premium_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            kind TEXT,
            details TEXT,
            amount REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    con.commit()
    con.close()


def upsert_user(user_id, username="", referred_by=None):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id FROM users WHERE id=?", (user_id,))
    exists = cur.fetchone()

    if not exists:
        cur.execute("""
            INSERT INTO users
            (id, username, referred_by, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username or "", referred_by, now(), now()))
    else:
        cur.execute(
            "UPDATE users SET username=?, last_seen=? WHERE id=?",
            (username or "", now(), user_id)
        )

    con.commit()
    con.close()


def get_user(user_id):
    con = db()
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return row


def add_balance(user_id, amount):
    con = db()
    con.execute(
        "UPDATE users SET balance=balance+? WHERE id=?",
        (float(amount), user_id)
    )
    con.commit()
    con.close()


def add_stars(user_id, amount):
    con = db()
    con.execute(
        "UPDATE users SET stars=stars+? WHERE id=?",
        (float(amount), user_id)
    )
    con.commit()
    con.close()


# =========================================================
# KLAVIATURA
# =========================================================
def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["📱 Nomer olish", "⭐ Stars olish"],
            ["💎 Premium olish", "💰 Pul ishlash"],
            ["💳 Balans", "💸 Pul chiqarish"],
            ["🛒 Telegram xizmat", "🆘 Yordam"],
        ],
        resize_keyboard=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        [
            ["📊 Statistika", "📨 Cheklar"],
            ["➕ Nomer qo'shish", "📱 Nomerlar"],
            ["➕ Balans qo'shish", "📢 Reklama"],
            ["⬅️ Oddiy menyu"],
        ],
        resize_keyboard=True
    )


# =========================================================
# START / REFERAL
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referrer = None

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer = int(arg[4:])
            except ValueError:
                referrer = None

    existing = get_user(user.id)
    if not existing:
        if referrer == user.id:
            referrer = None
        upsert_user(user.id, user.username or "", referrer)

        if referrer and get_user(referrer):
            # Referal mukofoti faqat yangi foydalanuvchiga bir marta beriladi.
            add_balance(referrer, REFERRAL_CASH)
            add_stars(referrer, REFERRAL_STARS)

            con = db()
            con.execute(
                "UPDATE users SET referrals=referrals+1 WHERE id=?",
                (referrer,)
            )
            con.commit()
            con.close()

            try:
                await context.bot.send_message(
                    referrer,
                    f"🎉 Yangi referal keldi!\n\n"
                    f"💰 +{REFERRAL_CASH:,.0f} so'm\n"
                    f"⭐ +{REFERRAL_STARS:g} Stars\n\n"
                    f"Har bir referal uchun shu mukofot beriladi."
                )
            except Exception:
                pass
    else:
        upsert_user(user.id, user.username or "")

    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "👑 Admin panel\n\nKerakli bo'limni tanlang.",
            reply_markup=admin_menu()
        )
    else:
        await update.message.reply_text(
            "🔥 TEKIN STARS BOT ga xush kelibsiz!\n\n"
            "📱 Nomer olish\n"
            "⭐ Stars olish\n"
            "💎 1 oylik Premium\n"
            "💰 Referal orqali pul va Stars ishlash\n"
            "💸 30 000 so'mdan pul chiqarish",
            reply_markup=main_menu()
        )


# =========================================================
# BALANS
# =========================================================
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        upsert_user(update.effective_user.id, update.effective_user.username or "")
        u = get_user(update.effective_user.id)

    await update.message.reply_text(
        f"💳 Sizning balansingiz:\n\n"
        f"💰 Pul: {u['balance']:,.0f} so'm\n"
        f"⭐ Stars: {u['stars']:g}\n"
        f"👥 Referallar: {u['referrals']} ta",
        reply_markup=main_menu()
    )


# =========================================================
# NOMER OLISH
# =========================================================
async def numbers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📱 NOMER OLISH\n\n"
        f"🇹🇯 Tojikiston — {NUMBER_PRICE:,.0f} so'm\n"
        f"🇷🇺 Rossiya — {NUMBER_PRICE:,.0f} so'm\n\n"
        "Kerakli davlatni tanlang:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇹🇯 Tojikiston — 25 000", callback_data="num_tj")],
            [InlineKeyboardButton("🇷🇺 Rossiya — 25 000", callback_data="num_ru")],
        ])
    )


async def number_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    country = "Tojikiston" if q.data == "num_tj" else "Rossiya"
    code = "TJ" if q.data == "num_tj" else "RU"

    con = db()
    row = con.execute(
        "SELECT * FROM numbers WHERE country=? AND sold=0 ORDER BY id LIMIT 1",
        (code,)
    ).fetchone()
    con.close()

    if not row:
        await q.message.reply_text(
            f"📱 {country} nomerlari hozircha qolmagan.\n"
            "Admin yangi nomer qo'shishi kerak."
        )
        return

    user = get_user(q.from_user.id)
    if user["balance"] < row["price"]:
        await q.message.reply_text(
            f"❌ Balansingiz yetarli emas.\n\n"
            f"💰 Narxi: {row['price']:,.0f} so'm\n"
            f"💳 Balansingiz: {user['balance']:,.0f} so'm\n\n"
            "Avval hisobni to'ldiring."
        )
        return

    con = db()
    con.execute(
        "UPDATE users SET balance=balance-? WHERE id=?",
        (row["price"], q.from_user.id)
    )
    con.execute("""
        UPDATE numbers
        SET sold=1, buyer_id=?, sold_at=?
        WHERE id=?
    """, (q.from_user.id, now(), row["id"]))
    con.execute("""
        INSERT INTO orders(user_id, kind, details, amount, status, created_at)
        VALUES (?, 'number', ?, ?, 'completed', ?)
    """, (q.from_user.id, f"{country}: {row['number']}", row["price"], now()))
    con.commit()
    con.close()

    await q.message.reply_text(
        f"✅ Nomer muvaffaqiyatli berildi!\n\n"
        f"🌍 Davlat: {country}\n"
        f"📱 Nomer: `{row['number']}`\n"
        f"💰 Narxi: {row['price']:,.0f} so'm",
        parse_mode="Markdown"
    )


# =========================================================
# STARS
# =========================================================
async def stars_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = []
    for qty in [50, 100, 200, 500, 1000]:
        price = qty * STARS_RATE
        buttons.append([
            InlineKeyboardButton(
                f"⭐ {qty} Stars — {price:,.0f} so'm",
                callback_data=f"stars_{qty}"
            )
        ])
    buttons.append([InlineKeyboardButton("✍️ Boshqa miqdor (50–1000)", callback_data="stars_custom")])

    await update.message.reply_text(
        "⭐ STARS OLISH\n\n"
        f"Kurs: 1 ⭐ = {STARS_RATE} so'm\n"
        "Miqdorni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def stars_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "stars_custom":
        context.user_data["state"] = "stars_custom"
        await q.message.reply_text("✍️ 50 dan 1000 gacha Stars miqdorini yozing:")
        return

    qty = int(q.data.split("_")[1])
    price = qty * STARS_RATE
    user = get_user(q.from_user.id)

    if user["balance"] < price:
        await q.message.reply_text(
            f"❌ Balans yetarli emas.\n"
            f"Kerak: {price:,.0f} so'm\n"
            f"Sizda: {user['balance']:,.0f} so'm"
        )
        return

    context.user_data["stars_order_qty"] = qty
    context.user_data["stars_order_price"] = price
    await q.message.reply_text(
        f"⭐ {qty} Stars\n"
        f"💰 {price:,.0f} so'm\n\n"
        "Buyurtmani tasdiqlash uchun tugmani bosing.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Buyurtma berish", callback_data="stars_confirm")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_order")],
        ])
    )


async def stars_custom_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "stars_custom":
        return

    try:
        qty = int(update.message.text.replace(" ", ""))
    except ValueError:
        await update.message.reply_text("❌ Faqat raqam yozing. Masalan: 300")
        return

    if qty < MIN_STARS or qty > MAX_STARS:
        await update.message.reply_text("❌ Miqdor 50–1000 oralig'ida bo'lishi kerak.")
        return

    context.user_data.pop("state", None)
    price = qty * STARS_RATE
    user = get_user(update.effective_user.id)

    if user["balance"] < price:
        await update.message.reply_text(
            f"❌ Balans yetarli emas.\n"
            f"Kerak: {price:,.0f} so'm\n"
            f"Sizda: {user['balance']:,.0f} so'm"
        )
        return

    context.user_data["stars_order_qty"] = qty
    context.user_data["stars_order_price"] = price

    await update.message.reply_text(
        f"⭐ {qty} Stars\n"
        f"💰 {price:,.0f} so'm\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Buyurtma berish", callback_data="stars_confirm")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_order")],
        ])
    )


async def stars_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    qty = context.user_data.get("stars_order_qty")
    price = context.user_data.get("stars_order_price")

    if not qty or not price:
        await q.message.reply_text("❌ Buyurtma ma'lumotlari topilmadi.")
        return

    user = get_user(q.from_user.id)
    if user["balance"] < price:
        await q.message.reply_text("❌ Balans yetarli emas.")
        return

    con = db()
    con.execute(
        "UPDATE users SET balance=balance-? WHERE id=?",
        (price, q.from_user.id)
    )
    cur = con.execute("""
        INSERT INTO orders(user_id, kind, details, amount, status, created_at)
        VALUES (?, 'stars', ?, ?, 'pending', ?)
    """, (q.from_user.id, f"{qty} Stars", price, now()))
    order_id = cur.lastrowid
    con.commit()
    con.close()

    context.user_data.pop("stars_order_qty", None)
    context.user_data.pop("stars_order_price", None)

    await q.message.reply_text(
        f"✅ Buyurtma #{order_id} qabul qilindi.\n\n"
        f"⭐ {qty} Stars\n"
        f"💰 {price:,.0f} so'm\n\n"
        "Admin tekshirganidan keyin Stars yuboriladi."
    )

    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"⭐ Yangi Stars buyurtma #{order_id}\n\n"
            f"👤 ID: {q.from_user.id}\n"
            f"🔹 Miqdor: {qty} Stars\n"
            f"💰 Summa: {price:,.0f} so'm",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Bajarildi", callback_data=f"order_done_{order_id}")],
                [InlineKeyboardButton("❌ Bekor + qaytarish", callback_data=f"order_refund_{order_id}")],
            ])
        )


# =========================================================
# PREMIUM
# =========================================================
async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)

    if u["premium_claimed"]:
        await update.message.reply_text("✅ Siz 1 oylik Premium mukofotingizni oldin olgansiz.")
        return

    if u["referrals"] < PREMIUM_REFERRALS:
        await update.message.reply_text(
            "💎 PREMIUM\n\n"
            "🎁 1 oylik Telegram Premium\n"
            f"👥 Kerak: {PREMIUM_REFERRALS} ta referal\n"
            f"👥 Sizda: {u['referrals']} ta\n\n"
            f"Yana: {PREMIUM_REFERRALS - u['referrals']} ta referal kerak."
        )
        return

    await update.message.reply_text(
        "💎 1 OYLIK PREMIUM\n\n"
        "Siz 40 ta referal shartini bajardingiz.\n"
        "Premium olish uchun so'rov yuboring.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Premium olish", callback_data="premium_request")]
        ])
    )


async def premium_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    u = get_user(q.from_user.id)
    if u["referrals"] < PREMIUM_REFERRALS:
        await q.message.reply_text("❌ Referal soni yetarli emas.")
        return

    con = db()
    pending = con.execute(
        "SELECT id FROM premium_requests WHERE user_id=? AND status='pending'",
        (q.from_user.id,)
    ).fetchone()

    if pending:
        con.close()
        await q.message.reply_text("⏳ So'rovingiz allaqachon adminga yuborilgan.")
        return

    cur = con.execute("""
        INSERT INTO premium_requests(user_id, status, created_at)
        VALUES (?, 'pending', ?)
    """, (q.from_user.id, now()))
    req_id = cur.lastrowid
    con.commit()
    con.close()

    await q.message.reply_text("✅ Premium so'rovi adminga yuborildi.")

    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"💎 PREMIUM SO'ROVI #{req_id}\n\n"
            f"👤 User ID: {q.from_user.id}\n"
            f"👥 Referallar: {u['referrals']}\n\n"
            "Premiumni qo'lda yuborganingizdan keyin Tasdiqlashni bosing.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Berildi", callback_data=f"premium_done_{req_id}")],
                [InlineKeyboardButton("❌ Rad etish", callback_data=f"premium_reject_{req_id}")],
            ])
        )


# =========================================================
# REFERAL / PUL ISHLASH
# =========================================================
async def earn_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{update.effective_user.id}"
    u = get_user(update.effective_user.id)

    await update.message.reply_text(
        "💰 PUL ISHLASH\n\n"
        f"👥 Referal: {u['referrals']} ta\n"
        f"💰 1 referal = {REFERRAL_CASH:,.0f} so'm\n"
        f"⭐ 1 referal = {REFERRAL_STARS:g} Stars\n"
        f"💎 {PREMIUM_REFERRALS} referal = 1 oylik Premium\n\n"
        "🔗 Sizning referal havolangiz:\n"
        f"{link}\n\n"
        "Havolani do'stlaringizga yuboring."
    )


# =========================================================
# PUL CHIQARISH
# =========================================================
async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)

    if u["balance"] < MIN_WITHDRAW:
        await update.message.reply_text(
            f"💸 Pul chiqarish uchun minimal summa {MIN_WITHDRAW:,.0f} so'm.\n\n"
            f"💰 Sizda: {u['balance']:,.0f} so'm"
        )
        return

    context.user_data["state"] = "withdraw_amount"
    await update.message.reply_text(
        f"💸 Pul chiqarish\n\n"
        f"Minimal: {MIN_WITHDRAW:,.0f} so'm\n"
        f"Mavjud: {u['balance']:,.0f} so'm\n\n"
        "Qancha chiqarmoqchisiz?"
    )


async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "withdraw_amount":
        return

    try:
        amount = float(update.message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Summani raqam bilan yozing.")
        return

    u = get_user(update.effective_user.id)

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ Minimum {MIN_WITHDRAW:,.0f} so'm.")
        return

    if amount > u["balance"]:
        await update.message.reply_text("❌ Balansingizda buncha pul yo'q.")
        return

    context.user_data["withdraw_amount"] = amount
    context.user_data["state"] = "withdraw_card"

    await update.message.reply_text("💳 Karta raqamingizni yuboring:")


async def withdraw_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "withdraw_card":
        return

    card = update.message.text.strip()
    amount = context.user_data.get("withdraw_amount")

    if not amount:
        await update.message.reply_text("❌ So'rov topilmadi. Qaytadan boshlang.")
        context.user_data.clear()
        return

    u = get_user(update.effective_user.id)
    if amount > u["balance"]:
        await update.message.reply_text("❌ Balans o'zgargan. Qaytadan urinib ko'ring.")
        context.user_data.clear()
        return

    con = db()
    con.execute(
        "UPDATE users SET balance=balance-? WHERE id=?",
        (amount, update.effective_user.id)
    )
    cur = con.execute("""
        INSERT INTO withdrawals(user_id, amount, card, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    """, (update.effective_user.id, amount, card, now()))
    wid = cur.lastrowid
    con.commit()
    con.close()

    context.user_data.clear()

    await update.message.reply_text(
        f"✅ Pul chiqarish so'rovi #{wid} yuborildi.\n\n"
        f"💰 Summa: {amount:,.0f} so'm\n"
        "⏳ Admin tekshiradi."
    )

    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"💸 PUL CHIQARISH #{wid}\n\n"
            f"👤 User ID: {update.effective_user.id}\n"
            f"💰 Summa: {amount:,.0f} so'm\n"
            f"💳 Karta: {card}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ To'landi", callback_data=f"wd_done_{wid}")],
                [InlineKeyboardButton("❌ Rad etish + qaytarish", callback_data=f"wd_refund_{wid}")],
            ])
        )


# =========================================================
# HISOB TO'LDIRISH / CHEK
# =========================================================
async def topup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "topup_amount"
    await update.message.reply_text(
        "💳 HISOB TO'LDIRISH\n\n"
        f"Karta: `{PAYMENT_CARD}`\n\n"
        "Qancha pul to'layotganingizni yozing.\n"
        "Keyin chek rasmini yuborasiz.",
        parse_mode="Markdown"
    )


async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "topup_amount":
        return

    try:
        amount = float(update.message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Summani raqam bilan yozing.")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Summa 0 dan katta bo'lishi kerak.")
        return

    context.user_data["topup_amount"] = amount
    context.user_data["state"] = "topup_receipt"

    await update.message.reply_text(
        f"💰 To'lov summasi: {amount:,.0f} so'm\n\n"
        "📸 Endi to'lov chekini RASM qilib yuboring."
    )


async def topup_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "topup_receipt":
        return

    if not update.message.photo:
        await update.message.reply_text("📸 Iltimos, chekni rasm qilib yuboring.")
        return

    amount = context.user_data.get("topup_amount")
    if not amount:
        await update.message.reply_text("❌ Summa topilmadi. Hisob to'ldirishni qaytadan boshlang.")
        context.user_data.clear()
        return

    file_id = update.message.photo[-1].file_id

    con = db()
    cur = con.execute("""
        INSERT INTO payments
        (user_id, requested_amount, receipt_file_id, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    """, (update.effective_user.id, amount, file_id, now()))
    payment_id = cur.lastrowid
    con.commit()
    con.close()

    context.user_data.clear()

    await update.message.reply_text(
        f"✅ Chek #{payment_id} adminga yuborildi.\n"
        "⏳ Tasdiqlanishini kuting."
    )

    if ADMIN_ID:
        caption = (
            f"💳 YANGI CHEK #{payment_id}\n\n"
            f"👤 User ID: {update.effective_user.id}\n"
            f"💰 Foydalanuvchi yozgan summa: {amount:,.0f} so'm\n\n"
            "Tasdiqlashdan oldin haqiqiy tushgan summani tekshiring.\n"
            "Keyin 'Summa kiritish' tugmasini bosing."
        )
        await context.bot.send_photo(
            ADMIN_ID,
            file_id,
            caption=caption,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Summa kiritish", callback_data=f"pay_amount_{payment_id}")],
                [InlineKeyboardButton("❌ Rad etish", callback_data=f"pay_reject_{payment_id}")],
            ])
        )


# =========================================================
# TELEGRAM XIZMAT
# =========================================================
async def telegram_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛒 TELEGRAM XIZMAT\n\n"
        f"📦 Xizmat narxi: {TELEGRAM_SERVICE_PRICE:,.0f} so'm\n\n"
        "Buyurtma berish uchun admin bilan bog'lanish yoki chek yuborish shart emas — "
        "bu bo'lim keyingi xizmat buyurtmalari uchun tayyor.\n\n"
        "Xizmat turini yozing: masalan, kanal / post / boshqa Telegram xizmati."
    )


# =========================================================
# YORDAM
# =========================================================
async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 YORDAM\n\n"
        "📱 Nomer olish — Tojikiston/Rossiya, 25 000 so'm\n"
        f"⭐ Stars — 50 dan 1000 gacha, 1 ⭐ = {STARS_RATE} so'm\n"
        "💎 Premium — 40 referalga 1 oy\n"
        f"💰 Referal — {REFERRAL_CASH:,.0f} so'm + {REFERRAL_STARS:g} Stars\n"
        f"💸 Pul chiqarish — minimum {MIN_WITHDRAW:,.0f} so'm\n"
        "💳 Hisob to'ldirish — chek orqali"
    )


# =========================================================
# ADMIN: STATISTIKA
# =========================================================
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    con = db()
    users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    pending_pay = con.execute(
        "SELECT COUNT(*) c FROM payments WHERE status='pending'"
    ).fetchone()["c"]
    numbers_tj = con.execute(
        "SELECT COUNT(*) c FROM numbers WHERE country='TJ' AND sold=0"
    ).fetchone()["c"]
    numbers_ru = con.execute(
        "SELECT COUNT(*) c FROM numbers WHERE country='RU' AND sold=0"
    ).fetchone()["c"]
    con.close()

    await update.message.reply_text(
        f"📊 STATISTIKA\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"💳 Kutilayotgan cheklar: {pending_pay}\n"
        f"🇹🇯 Qolgan Tojik nomer: {numbers_tj}\n"
        f"🇷🇺 Qolgan Rossiya nomer: {numbers_ru}",
        reply_markup=admin_menu()
    )


# =========================================================
# ADMIN: CHEKLAR
# =========================================================
async def admin_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    con = db()
    rows = con.execute("""
        SELECT * FROM payments
        WHERE status='pending'
        ORDER BY id DESC LIMIT 10
    """).fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("✅ Kutilayotgan chek yo'q.", reply_markup=admin_menu())
        return

    for row in rows:
        await update.message.reply_text(
            f"💳 Chek #{row['id']}\n"
            f"👤 User: {row['user_id']}\n"
            f"💰 Yozilgan summa: {row['requested_amount']:,.0f} so'm",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Summa kiritish", callback_data=f"pay_amount_{row['id']}")],
                [InlineKeyboardButton("❌ Rad etish", callback_data=f"pay_reject_{row['id']}")],
            ])
        )


# =========================================================
# ADMIN: BALANS QO'SHISH
# =========================================================
async def admin_add_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["state"] = "admin_balance"
    await update.message.reply_text(
        "➕ Balans qo'shish\n\n"
        "Shu formatda yozing:\n"
        "USER_ID SUMMA\n\n"
        "Masalan:\n"
        "123456789 50000"
    )


async def admin_balance_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if context.user_data.get("state") != "admin_balance":
        return

    parts = update.message.text.split()
    if len(parts) != 2:
        await update.message.reply_text("❌ Format: USER_ID SUMMA")
        return

    try:
        uid = int(parts[0])
        amount = float(parts[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ ID va summani raqam bilan yozing.")
        return

    if not get_user(uid):
        await update.message.reply_text("❌ Bunday foydalanuvchi topilmadi.")
        return

    add_balance(uid, amount)
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ {uid} hisobiga {amount:,.0f} so'm qo'shildi.",
        reply_markup=admin_menu()
    )

    try:
        await context.bot.send_message(
            uid,
            f"💳 Hisobingizga {amount:,.0f} so'm qo'shildi.\n"
            "Balans bo'limidan tekshirishingiz mumkin."
        )
    except Exception:
        pass


# =========================================================
# ADMIN: NOMER QO'SHISH
# =========================================================
async def admin_add_number_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["state"] = "admin_number"
    await update.message.reply_text(
        "➕ Nomer qo'shish\n\n"
        "Format:\n"
        "TJ +992XXXXXXXXX\n"
        "yoki\n"
        "RU +7XXXXXXXXXX\n\n"
        "Narx avtomatik 25 000 so'm."
    )


async def admin_number_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if context.user_data.get("state") != "admin_number":
        return

    parts = update.message.text.split()
    if len(parts) != 2 or parts[0].upper() not in ("TJ", "RU"):
        await update.message.reply_text("❌ Format: TJ +992... yoki RU +7...")
        return

    country, number = parts[0].upper(), parts[1]

    try:
        con = db()
        con.execute(
            "INSERT INTO numbers(country, number, price, sold) VALUES (?, ?, ?, 0)",
            (country, number, NUMBER_PRICE)
        )
        con.commit()
        con.close()
    except sqlite3.IntegrityError:
        await update.message.reply_text("❌ Bu nomer bazada allaqachon bor.")
        return

    context.user_data.clear()
    await update.message.reply_text(
        f"✅ {country} nomer qo'shildi: {number}\n"
        f"💰 Narx: {NUMBER_PRICE:,.0f} so'm",
        reply_markup=admin_menu()
    )


async def admin_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    con = db()
    rows = con.execute("""
        SELECT country, COUNT(*) c
        FROM numbers
        WHERE sold=0
        GROUP BY country
    """).fetchall()
    con.close()

    text = "📱 QOLGAN NOMERLAR\n\n"
    if not rows:
        text += "Hozircha nomer yo'q."
    else:
        for r in rows:
            text += f"{r['country']}: {r['c']} ta\n"

    await update.message.reply_text(text, reply_markup=admin_menu())


# =========================================================
# ADMIN: REKLAMA
# =========================================================
async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["state"] = "broadcast"
    await update.message.reply_text("📢 Yuboriladigan reklama matnini yozing:")


async def admin_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if context.user_data.get("state") != "broadcast":
        return

    text = update.message.text
    context.user_data.clear()

    con = db()
    rows = con.execute("SELECT id FROM users").fetchall()
    con.close()

    sent = 0
    for row in rows:
        try:
            await context.bot.send_message(row["id"], text)
            sent += 1
        except Exception:
            pass

    await update.message.reply_text(
        f"📢 Reklama yuborildi.\n✅ Yetib borgan: {sent}",
        reply_markup=admin_menu()
    )


# =========================================================
# ADMIN CALLBACKLAR
# =========================================================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query

    if q.from_user.id != ADMIN_ID:
        await q.answer("Ruxsat yo'q.", show_alert=True)
        return

    await q.answer()

    data = q.data

    # Chek: summa kiritish
    if data.startswith("pay_amount_"):
        payment_id = int(data.split("_")[-1])
        con = db()
        row = con.execute(
            "SELECT * FROM payments WHERE id=? AND status='pending'",
            (payment_id,)
        ).fetchone()
        con.close()

        if not row:
            await q.message.reply_text("❌ Chek topilmadi yoki allaqachon ishlangan.")
            return

        context.user_data["state"] = "admin_payment_amount"
        context.user_data["payment_id"] = payment_id

        await q.message.reply_text(
            f"💰 Chek #{payment_id}\n\n"
            "Haqiqatan hisobga qo'shiladigan summani yozing.\n"
            "Masalan: 50000"
        )
        return

    # Chekni rad etish
    if data.startswith("pay_reject_"):
        payment_id = int(data.split("_")[-1])
        con = db()
        row = con.execute(
            "SELECT * FROM payments WHERE id=? AND status='pending'",
            (payment_id,)
        ).fetchone()
        if row:
            con.execute(
                "UPDATE payments SET status='rejected' WHERE id=?",
                (payment_id,)
            )
            con.commit()
        con.close()

        await q.message.reply_text(f"❌ Chek #{payment_id} rad etildi.")
        if row:
            try:
                await context.bot.send_message(
                    row["user_id"],
                    f"❌ Chek #{payment_id} rad etildi."
                )
            except Exception:
                pass
        return

    # Stars order done/refund
    if data.startswith("order_done_") or data.startswith("order_refund_"):
        parts = data.split("_")
        action = parts[1]
        order_id = int(parts[2])

        con = db()
        row = con.execute(
            "SELECT * FROM orders WHERE id=? AND kind='stars'",
            (order_id,)
        ).fetchone()

        if not row or row["status"] != "pending":
            con.close()
            await q.message.reply_text("❌ Buyurtma topilmadi yoki ishlangan.")
            return

        if action == "done":
            con.execute(
                "UPDATE orders SET status='completed' WHERE id=?",
                (order_id,)
            )
            con.commit()
            con.close()

            await q.message.reply_text(f"✅ Stars buyurtma #{order_id} bajarildi.")
            try:
                await context.bot.send_message(
                    row["user_id"],
                    f"✅ Stars buyurtmangiz #{order_id} bajarildi.\n"
                    f"⭐ {row['details']} yuborildi."
                )
            except Exception:
                pass
        else:
            con.execute(
                "UPDATE orders SET status='refunded' WHERE id=?",
                (order_id,)
            )
            con.execute(
                "UPDATE users SET balance=balance+? WHERE id=?",
                (row["amount"], row["user_id"])
            )
            con.commit()
            con.close()

            await q.message.reply_text(f"↩️ Buyurtma #{order_id} summasi qaytarildi.")
            try:
                await context.bot.send_message(
                    row["user_id"],
                    f"↩️ Stars buyurtmangiz #{order_id} bekor qilindi.\n"
                    f"💰 {row['amount']:,.0f} so'm balansga qaytarildi."
                )
            except Exception:
                pass
        return

    # Premium
    if data.startswith("premium_done_") or data.startswith("premium_reject_"):
        parts = data.split("_")
        action = parts[1]
        req_id = int(parts[2])

        con = db()
        row = con.execute(
            "SELECT * FROM premium_requests WHERE id=?",
            (req_id,)
        ).fetchone()

        if not row or row["status"] != "pending":
            con.close()
            await q.message.reply_text("❌ So'rov topilmadi yoki ishlangan.")
            return

        if action == "done":
            con.execute(
                "UPDATE premium_requests SET status='completed' WHERE id=?",
                (req_id,)
            )
            con.execute(
                "UPDATE users SET premium_claimed=1 WHERE id=?",
                (row["user_id"],)
            )
            con.commit()
            con.close()

            await q.message.reply_text(f"✅ Premium so'rovi #{req_id} tasdiqlandi.")
            try:
                await context.bot.send_message(
                    row["user_id"],
                    "💎 Tabriklaymiz! 1 oylik Premium so'rovingiz tasdiqlandi."
                )
            except Exception:
                pass
        else:
            con.execute(
                "UPDATE premium_requests SET status='rejected' WHERE id=?",
                (req_id,)
            )
            con.commit()
            con.close()

            await q.message.reply_text(f"❌ Premium so'rovi #{req_id} rad etildi.")
            try:
                await context.bot.send_message(
                    row["user_id"],
                    "❌ Premium so'rovingiz rad etildi."
                )
            except Exception:
                pass
        return

    # Withdrawal
    if data.startswith("wd_done_") or data.startswith("wd_refund_"):
        parts = data.split("_")
        action = parts[1]
        wid = int(parts[2])

        con = db()
        row = con.execute(
            "SELECT * FROM withdrawals WHERE id=? AND status='pending'",
            (wid,)
        ).fetchone()

        if not row:
            con.close()
            await q.message.reply_text("❌ So'rov topilmadi yoki ishlangan.")
            return

        if action == "done":
            con.execute(
                "UPDATE withdrawals SET status='paid' WHERE id=?",
                (wid,)
            )
            con.commit()
            con.close()
            await q.message.reply_text(f"✅ Pul chiqarish #{wid} to'landi.")
            try:
                await context.bot.send_message(
                    row["user_id"],
                    f"✅ Pul chiqarish #{wid} to'landi.\n"
                    f"💰 {row['amount']:,.0f} so'm"
                )
            except Exception:
                pass
        else:
            con.execute(
                "UPDATE withdrawals SET status='rejected' WHERE id=?",
                (wid,)
            )
            con.execute(
                "UPDATE users SET balance=balance+? WHERE id=?",
                (row["amount"], row["user_id"])
            )
            con.commit()
            con.close()
            await q.message.reply_text(f"↩️ #{wid} rad etildi, pul balansga qaytarildi.")
            try:
                await context.bot.send_message(
                    row["user_id"],
                    f"↩️ Pul chiqarish #{wid} rad etildi.\n"
                    f"💰 {row['amount']:,.0f} so'm balansga qaytarildi."
                )
            except Exception:
                pass
        return


async def admin_payment_amount_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if context.user_data.get("state") != "admin_payment_amount":
        return

    try:
        amount = float(update.message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Summani raqam bilan yozing.")
        return

    payment_id = context.user_data.get("payment_id")
    if not payment_id:
        context.user_data.clear()
        await update.message.reply_text("❌ Chek ID topilmadi.")
        return

    con = db()
    row = con.execute(
        "SELECT * FROM payments WHERE id=? AND status='pending'",
        (payment_id,)
    ).fetchone()

    if not row:
        con.close()
        context.user_data.clear()
        await update.message.reply_text("❌ Chek topilmadi yoki allaqachon ishlangan.")
        return

    con.execute("""
        UPDATE payments
        SET admin_amount=?, status='approved'
        WHERE id=?
    """, (amount, payment_id))
    con.execute(
        "UPDATE users SET balance=balance+? WHERE id=?",
        (amount, row["user_id"])
    )
    con.commit()
    con.close()

    context.user_data.clear()

    await update.message.reply_text(
        f"✅ Chek #{payment_id} tasdiqlandi.\n"
        f"💰 {amount:,.0f} so'm balansga qo'shildi.",
        reply_markup=admin_menu()
    )

    try:
        await context.bot.send_message(
            row["user_id"],
            f"✅ To'lov tasdiqlandi.\n\n"
            f"💰 +{amount:,.0f} so'm balansingizga qo'shildi."
        )
    except Exception:
        pass


# =========================================================
# UMUMIY TEXT ROUTER
# =========================================================
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    uid = update.effective_user.id

    # Admin holatlari avval tekshiriladi
    if uid == ADMIN_ID:
        if context.user_data.get("state") == "admin_balance":
            await admin_balance_message(update, context)
            return
        if context.user_data.get("state") == "admin_number":
            await admin_number_message(update, context)
            return
        if context.user_data.get("state") == "broadcast":
            await admin_broadcast_message(update, context)
            return
        if context.user_data.get("state") == "admin_payment_amount":
            await admin_payment_amount_message(update, context)
            return

    # User holatlari
    if context.user_data.get("state") == "stars_custom":
        await stars_custom_message(update, context)
        return

    if context.user_data.get("state") == "topup_amount":
        await topup_amount(update, context)
        return

    if context.user_data.get("state") == "withdraw_amount":
        await withdraw_amount(update, context)
        return

    if context.user_data.get("state") == "withdraw_card":
        await withdraw_card(update, context)
        return

    if text == "📱 Nomer olish":
        await numbers_menu(update, context)
    elif text == "⭐ Stars olish":
        await stars_menu(update, context)
    elif text == "💎 Premium olish":
        await premium_menu(update, context)
    elif text == "💰 Pul ishlash":
        await earn_menu(update, context)
    elif text == "💳 Balans":
        await balance(update, context)
    elif text == "💸 Pul chiqarish":
        await withdraw_start(update, context)
    elif text == "🛒 Telegram xizmat":
        await telegram_service(update, context)
    elif text == "🆘 Yordam":
        await help_menu(update, context)

    # Admin menyu
    elif uid == ADMIN_ID and text == "📊 Statistika":
        await admin_stats(update, context)
    elif uid == ADMIN_ID and text == "📨 Cheklar":
        await admin_payments(update, context)
    elif uid == ADMIN_ID and text == "➕ Nomer qo'shish":
        await admin_add_number_start(update, context)
    elif uid == ADMIN_ID and text == "📱 Nomerlar":
        await admin_numbers(update, context)
    elif uid == ADMIN_ID and text == "➕ Balans qo'shish":
        await admin_add_balance_start(update, context)
    elif uid == ADMIN_ID and text == "📢 Reklama":
        await admin_broadcast_start(update, context)
    elif uid == ADMIN_ID and text == "⬅️ Oddiy menyu":
        await update.message.reply_text("Oddiy menyu:", reply_markup=main_menu())


async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") == "topup_receipt":
        await topup_receipt(update, context)


# =========================================================
# MAIN
# =========================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN GitHub Secretda yo'q.")
    if not ADMIN_ID:
        raise RuntimeError("ADMIN_ID GitHub Secretda yo'q.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(number_country, pattern=r"^num_(tj|ru)$"))
    app.add_handler(CallbackQueryHandler(stars_choice, pattern=r"^stars_(custom|\d+)$"))
    app.add_handler(CallbackQueryHandler(stars_confirm, pattern=r"^stars_confirm$"))
    app.add_handler(CallbackQueryHandler(premium_request, pattern=r"^premium_request$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^(pay_|order_|premium_|wd_)"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: u.callback_query.answer(),
        pattern=r"^cancel_order$"
    ))

    app.add_handler(MessageHandler(filters.PHOTO, photo_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    log.info("TEKIN STARS BOT ishga tushdi.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
