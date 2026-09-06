import os
import sqlite3
import logging
import random
import asyncio
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_FILE = "zerikdim.db"

SPONSOR_CHANNEL = "@premyumstarstekin"
BUY_STARS_URL = "https://t.me/premyumstarstekin/933"

REFERRAL_REWARD = 9.0

# O'yin mukofoti
GAME_REWARD = 0.02

# Task mukofoti
TASK_REWARD = 5.0

# Withdraw
MIN_WITHDRAW = 200.0
MIN_REFERRALS = 20

# O'yinlar orasidagi kutish vaqti
GAME_COOLDOWN = 30

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

log = logging.getLogger("zerikdim")

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

QUIZ = [
    ("O‘zbekiston poytaxti qaysi?", ["Toshkent", "Samarqand", "Buxoro"], 0),
    ("2 + 2 nechchi?", ["3", "4", "5"], 1),
    ("Haftada nechta kun bor?", ["6", "7", "8"], 1),
    ("Yerning tabiiy yo‘ldoshi nima?", ["Oy", "Mars", "Quyosh"], 0),
    ("Bir yilda nechta oy bor?", ["10", "11", "12"], 2),
]

PAGE_SIZE = 10


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    return sqlite3.connect(DB_FILE)


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
        user_id INTEGER,
        amount REAL,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        reward REAL,
        url TEXT
    )
    """)

    # Taskni bir marta bajarishni nazorat qilish
    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_claims(
        user_id INTEGER,
        task_id INTEGER,
        created_at TEXT,
        PRIMARY KEY(user_id, task_id)
    )
    """)

    con.commit()
    con.close()


def add_user(user_id, username=None, ref=None):
    con = db()
    cur = con.cursor()

    cur.execute("SELECT id FROM users WHERE id=?", (user_id,))
    exists = cur.fetchone()

    if not exists:
        valid_ref = ref if ref and ref != user_id else None

        cur.execute("""
        INSERT INTO users
        (id,username,points,games,wins,referrals,referred_by,
         last_seen,blocked,referral_rewarded)
        VALUES (?, ?, 0, 0, 0, 0, ?, ?, 0, 0)
        """, (
            user_id,
            username,
            valid_ref,
            now()
        ))

        if valid_ref:
            cur.execute("""
            SELECT id FROM users WHERE id=?
            """, (valid_ref,))

            ref_exists = cur.fetchone()

            if ref_exists:
                cur.execute("""
                UPDATE users
                SET points=points+?, referrals=referrals+1
                WHERE id=?
                """, (REFERRAL_REWARD, valid_ref))

                cur.execute("""
                UPDATE users
                SET referral_rewarded=1
                WHERE id=?
                """, (user_id,))

    else:
        cur.execute(
            "UPDATE users SET username=?, last_seen=? WHERE id=?",
            (username, now(), user_id)
        )

    con.commit()
    con.close()


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


def change_points(user_id, amount):
    con = db()
    cur = con.cursor()

    cur.execute(
        "UPDATE users SET points=MAX(0,points+?) WHERE id=?",
        (amount, user_id)
    )

    con.commit()
    con.close()


def game_result(user_id, won):
    con = db()
    cur = con.cursor()

    cur.execute(
        "UPDATE users SET games=games+1,wins=wins+? WHERE id=?",
        (1 if won else 0, user_id)
    )

    con.commit()
    con.close()


async def subscribed(bot, user_id):
    try:
        member = await bot.get_chat_member(
            SPONSOR_CHANNEL,
            user_id
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        )

    except TelegramError:
        return False


async def require_subscription(update, context):
    if await subscribed(
        context.bot,
        update.effective_user.id
    ):
        return True

    kb = [
        [
            InlineKeyboardButton(
                "📢 Kanalga obuna bo‘lish",
                url="https://t.me/premyumstarstekin"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Tekshirish",
                callback_data="check_sub"
            )
        ]
    ]

    text = (
        "🔒 Davom etish uchun homiy kanalga "
        "obuna bo‘ling."
    )

    if update.callback_query:
        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    return False


def main_menu(user_id):
    rows = [
        [
            InlineKeyboardButton(
                "⭐ STARS OLISH",
                callback_data="buy"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 STARS ISHLASH",
                callback_data="work"
            )
        ],
        [
            InlineKeyboardButton(
                "🎮 O‘YINLAR",
                callback_data="games_0"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 BALANS",
                callback_data="balance"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 TOPSHIRIQLAR",
                callback_data="tasks"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="ref"
            )
        ],
        [
            InlineKeyboardButton(
                "💸 YECHIB OLISH",
                callback_data="withdraw"
            )
        ],
        [
            InlineKeyboardButton(
                "🏆 REYTING",
                callback_data="rating"
            )
        ],
        [
            InlineKeyboardButton(
                "👤 PROFIL",
                callback_data="profile"
            )
        ],
    ]

    if user_id == ADMIN_ID:
        rows.append([
            InlineKeyboardButton(
                "⚙️ ADMIN PANEL",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ref = None

    if context.args:
        try:
            ref = int(context.args[0])
        except ValueError:
            pass

    add_user(
        user.id,
        user.username,
        ref
    )

    text = (
        "✨ <b>Zerikdim Bot</b> ga xush kelibsiz!\n\n"
        "🎮 O‘yinlar o‘ynang\n"
        "⭐ Virtual Stars ishlang\n"
        "🎁 Topshiriqlar bajaring\n"
        "👥 Do‘stlaringizni taklif qiling\n\n"
        "👇 Menyudan tanlang:"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(user.id)
    )


async def menu(update, context):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id

    add_user(
        uid,
        q.from_user.username
    )

    data = q.data

    # =========================
    # OBUNA TEKSHIRISH
    # =========================

    if data == "check_sub":
        if await subscribed(
            context.bot,
            uid
        ):
            await q.message.reply_text(
                "✅ Obuna tasdiqlandi!",
                reply_markup=main_menu(uid)
            )
        else:
            await q.message.reply_text(
                "❌ Hali obuna bo‘lmagansiz."
            )

        return

    # =========================
    # HOME
    # =========================

    if data == "home":
        await q.message.reply_text(
            "🏠 Bosh menyu:",
            reply_markup=main_menu(uid)
        )
        return

    # =========================
    # STARS OLISH
    # =========================

    if data == "buy":
        kb = [
            [
                InlineKeyboardButton(
                    "⭐ 50 Stars",
                    callback_data="buy50"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 100 Stars",
                    callback_data="buy100"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 200 Stars",
                    callback_data="buy200"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 500 Stars",
                    callback_data="buy500"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 1000 Stars",
                    callback_data="buy1000"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 2000 Stars",
                    callback_data="buy2000"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 5000 Stars",
                    callback_data="buy5000"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Orqaga",
                    callback_data="home"
                )
            ]
        ]

        await q.message.reply_text(
            "⭐ <b>STARS OLISH</b>\n\n"
            "Kerakli paketni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

        return

    if data.startswith("buy"):
        await q.message.reply_text(
            f"⭐ Tanlangan paket: "
            f"<b>{data[3:]} Stars</b>\n\n"
            "Xarid uchun kanalga o‘ting:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🛒 Xarid qilish",
                        url=BUY_STARS_URL
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Orqaga",
                        callback_data="buy"
                    )
                ]
            ])
        )

        return

    # =========================
    # BALANCE
    # =========================

    if data == "balance":
        u = get_user(uid)

        await q.message.reply_text(
            f"💰 <b>Balansingiz:</b> "
            f"{u[2]:.2f} ⭐",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Orqaga",
                        callback_data="home"
                    )
                ]
            ])
        )

        return

    # =========================
    # PROFILE
    # =========================

    if data == "profile":
        u = get_user(uid)

        await q.message.reply_text(
            f"👤 <b>Profil</b>\n\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"⭐ Balans: {u[2]:.2f}\n"
            f"🎮 O‘yinlar: {u[3]}\n"
            f"🏆 G‘alabalar: {u[4]}\n"
            f"👥 Referallar: {u[5]}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Orqaga",
                        callback_data="home"
                    )
                ]
            ])
        )

        return

    # =========================
    # REFERAL
    # =========================

    if data == "ref":
        me = await context.bot.get_me()

        link = (
            f"https://t.me/{me.username}?start={uid}"
        )

        u = get_user(uid)

        await q.message.reply_text(
            f"👥 <b>REFERAL TIZIMI</b>\n\n"
            f"Har bir taklif uchun: "
            f"⭐ {REFERRAL_REWARD}\n"
            f"Referallaringiz: {u[5]}\n\n"
            f"🔗 Sizning linkingiz:\n"
            f"<code>{link}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Orqaga",
                        callback_data="home"
                    )
                ]
            ])
        )

        return

    # =========================
    # TASKS
    # =========================

    if data == "tasks":
        if not await require_subscription(
            update,
            context
        ):
            return

        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT id,text,reward,url FROM tasks"
        )

        rows = cur.fetchall()

        con.close()

        kb = []

        for tid, text, reward, url in rows:
            kb.append([
                InlineKeyboardButton(
                    f"🎁 {text} +{reward}⭐",
                    callback_data=f"task_{tid}"
                )
            ])

        kb.append([
            InlineKeyboardButton(
                "⬅️ Orqaga",
                callback_data="home"
            )
        ])

        await q.message.reply_text(
            "🎁 <b>TOPSHIRIQLAR</b>\n\n"
            "Topshiriqni tanlang.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

        return

    if data.startswith("task_"):
        tid = int(data.split("_")[1])

        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT text,reward,url FROM tasks WHERE id=?",
            (tid,)
        )

        row = cur.fetchone()

        con.close()

        if not row:
            await q.message.reply_text(
                "❌ Topshiriq topilmadi."
            )
            return

        text, reward, url = row

        await q.message.reply_text(
            f"🎁 <b>{text}</b>\n\n"
            "Vazifani bajaring, keyin "
            "tekshirish tugmasini bosing.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔗 Topshiriq",
                        url=url
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"✅ Bajardim +{reward}⭐",
                        callback_data=f"taskdone_{tid}"
                    )
                ]
            ])
        )

        return

    if data.startswith("taskdone_"):
        tid = int(data.split("_")[1])

        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT reward FROM tasks WHERE id=?",
            (tid,)
        )

        row = cur.fetchone()

        if not row:
            con.close()

            await q.message.reply_text(
                "❌ Topshiriq topilmadi."
            )

            return

        reward = float(row[0])

        # Oldin olganmi?
        cur.execute("""
            SELECT 1
            FROM task_claims
            WHERE user_id=? AND task_id=?
        """, (uid, tid))

        already = cur.fetchone()

        if already:
            con.close()

            await q.message.reply_text(
                "⚠️ Bu topshiriq uchun Stars "
                "allaqachon olingan."
            )

            return

        # Birinchi marta olsa yozib qo'yamiz
        cur.execute("""
            INSERT INTO task_claims
            (user_id,task_id,created_at)
            VALUES (?,?,?)
        """, (
            uid,
            tid,
            now()
        ))

        cur.execute("""
            UPDATE users
            SET points=points+?
            WHERE id=?
        """, (
            reward,
            uid
        ))

        con.commit()
        con.close()

        await q.message.reply_text(
            f"🎉 +{reward} ⭐ "
            "balansingizga qo‘shildi!"
        )

        return

    # =========================
    # RATING
    # =========================

    if data == "rating":
        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT username,points
        FROM users
        ORDER BY points DESC
        LIMIT 10
        """)

        rows = cur.fetchall()

        con.close()

        text = "🏆 <b>TOP 10</b>\n\n"

        for i, (name, points) in enumerate(
            rows,
            1
        ):
            text += (
                f"{i}. @{name or 'user'} — "
                f"⭐ {points:.2f}\n"
            )

        await q.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Orqaga",
                        callback_data="home"
                    )
                ]
            ])
        )

        return

    # =========================
    # WITHDRAW
    # =========================

    if data == "withdraw":

        WITHDRAW_AMOUNT = 200.0

        u = get_user(uid)

        if not u:
            await q.message.reply_text(
                "❌ Profil topilmadi."
            )
            return

        balance = float(u[2])
        referrals = int(u[5])

        if balance < WITHDRAW_AMOUNT:
            await q.message.reply_text(
                f"❌ Yechish uchun kamida "
                f"⭐ {WITHDRAW_AMOUNT:.0f} kerak.\n\n"
                f"💰 Sizning balansingiz: "
                f"⭐ {balance:.2f}"
            )
            return

        if referrals < MIN_REFERRALS:
            await q.message.reply_text(
                f"❌ Yechish uchun kamida "
                f"{MIN_REFERRALS} ta referal kerak.\n\n"
                f"👥 Sizda: {referrals} ta"
            )
            return

        con = db()
        cur = con.cursor()

        # Pending borligini tekshirish
        cur.execute("""
            SELECT id,amount,created_at
            FROM withdrawals
            WHERE user_id=?
            AND status='pending'
            ORDER BY id DESC
            LIMIT 1
        """, (uid,))

        pending = cur.fetchone()

        if pending:
            con.close()

            await q.message.reply_text(
                "⏳ <b>Sizning yechish "
                "so‘rovingiz allaqachon yuborilgan!</b>\n\n"
                f"💸 Miqdor: ⭐ {pending[1]:.0f}\n"
                "🕐 Holat: Kutilmoqda\n\n"
                "Iltimos, qayta so‘rov yubormang.\n"
                "So‘rovingiz 24 soat ichida "
                "ko‘rib chiqiladi.",
                parse_mode="HTML"
            )

            return

        try:
            # Bir vaqtning o'zida 2 ta requestdan himoya
            cur.execute("BEGIN IMMEDIATE")

            cur.execute("""
                SELECT points
                FROM users
                WHERE id=?
            """, (uid,))

            current = cur.fetchone()

            if (
                not current
                or float(current[0]) < WITHDRAW_AMOUNT
            ):
                con.rollback()
                con.close()

                await q.message.reply_text(
                    "❌ Balans yetarli emas."
                )

                return

            # 200 ⭐ ni darhol ayiramiz
            cur.execute("""
                UPDATE users
                SET points=points-?
                WHERE id=?
                AND points>=?
            """, (
                WITHDRAW_AMOUNT,
                uid,
                WITHDRAW_AMOUNT
            ))

            if cur.rowcount != 1:
                con.rollback()
                con.close()

                await q.message.reply_text(
                    "❌ Yechish amalga oshmadi."
                )

                return

            # Withdraw yaratamiz
            cur.execute("""
                INSERT INTO withdrawals
                (user_id,amount,status,created_at)
                VALUES (?,?,'pending',?)
            """, (
                uid,
                WITHDRAW_AMOUNT,
                now()
            ))

            withdrawal_id = cur.lastrowid

            con.commit()
            con.close()

        except Exception as e:
            log.error(
                f"Withdraw error: {e}"
            )

            try:
                con.rollback()
                con.close()
            except Exception:
                pass

            await q.message.reply_text(
                "❌ Xatolik yuz berdi. "
                "Qaytadan urinib ko‘ring."
            )

            return

        # Foydalanuvchiga xabar
        await q.message.reply_text(
            "✅ <b>Yechish so‘rovingiz "
            "muvaffaqiyatli qabul qilindi!</b>\n\n"
            f"💸 Miqdor: ⭐ {WITHDRAW_AMOUNT:.0f}\n"
            "💰 Balansingiz: ⭐ 0\n"
            "⏳ So‘rovingiz 24 soat ichida "
            "ko‘rib chiqilib, to‘lov qilinadi.\n\n"
            "❗ Qayta yechish so‘rovi yuborib "
            "bo‘lmaydi.",
            parse_mode="HTML"
        )

        # Admin
        try:
            admin_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ TASDIQLASH",
                        callback_data=(
                            f"wdapprove_{withdrawal_id}"
                        )
                    ),
                    InlineKeyboardButton(
                        "❌ RAD ETISH",
                        callback_data=(
                            f"wdreject_{withdrawal_id}"
                        )
                    )
                ]
            ])

            await context.bot.send_message(
                ADMIN_ID,
                f"💸 <b>YANGI YECHISH SO‘ROVI</b>\n\n"
                f"🆔 User ID: <code>{uid}</code>\n"
                f"⭐ Miqdor: "
                f"<b>{WITHDRAW_AMOUNT:.0f}</b>\n"
                f"📋 So‘rov ID: "
                f"<code>{withdrawal_id}</code>\n\n"
                "⏳ Holat: Kutilmoqda",
                parse_mode="HTML",
                reply_markup=admin_kb
            )

        except TelegramError as e:
            log.error(
                f"Admin notification error: {e}"
            )

        return

    # =========================
    # WITHDRAW APPROVE
    # =========================

    if data.startswith("wdapprove_"):

        if uid != ADMIN_ID:
            await q.answer(
                "❌ Ruxsat yo‘q.",
                show_alert=True
            )
            return

        withdrawal_id = int(
            data.split("_")[1]
        )

        con = db()
        cur = con.cursor()

        cur.execute("""
            SELECT user_id,amount,status
            FROM withdrawals
            WHERE id=?
        """, (withdrawal_id,))

        row = cur.fetchone()

        if not row:
            con.close()

            await q.answer(
                "❌ So‘rov topilmadi.",
                show_alert=True
            )

            return

        user_id, amount, status = row

        if status != "pending":
            con.close()

            await q.answer(
                f"❌ Bu so‘rov allaqachon: {status}",
                show_alert=True
            )

            return

        cur.execute("""
            UPDATE withdrawals
            SET status='approved'
            WHERE id=?
            AND status='pending'
        """, (withdrawal_id,))

        con.commit()
        con.close()

        await q.message.edit_reply_markup(
            reply_markup=None
        )

        await q.message.reply_text(
            f"✅ <b>YECHISH TASDIQLANDI</b>\n\n"
            f"🆔 User: <code>{user_id}</code>\n"
            f"⭐ Miqdor: {amount:.0f}",
            parse_mode="HTML"
        )

        try:
            await context.bot.send_message(
                user_id,
                "✅ <b>Yechish so‘rovingiz tasdiqlandi!</b>\n\n"
                f"⭐ Miqdor: {amount:.0f}\n\n"
                "💳 To‘lov amalga oshiriladi.",
                parse_mode="HTML"
            )

        except TelegramError:
            pass

        return

    # =========================
    # WITHDRAW REJECT
    # =========================

    if data.startswith("wdreject_"):

        if uid != ADMIN_ID:
            await q.answer(
                "❌ Ruxsat yo‘q.",
                show_alert=True
            )
            return

        withdrawal_id = int(
            data.split("_")[1]
        )

        con = db()
        cur = con.cursor()

        cur.execute("""
            SELECT user_id,amount,status
            FROM withdrawals
            WHERE id=?
        """, (withdrawal_id,))

        row = cur.fetchone()

        if not row:
            con.close()

            await q.answer(
                "❌ So‘rov topilmadi.",
                show_alert=True
            )

            return

        user_id, amount, status = row

        if status != "pending":
            con.close()

            await q.answer(
                f"❌ Bu so‘rov allaqachon: {status}",
                show_alert=True
            )

            return

        # Pulni qaytarish
        cur.execute("""
            UPDATE users
            SET points=points+?
            WHERE id=?
        """, (
            amount,
            user_id
        ))

        cur.execute("""
            UPDATE withdrawals
            SET status='rejected'
            WHERE id=?
            AND status='pending'
        """, (withdrawal_id,))

        con.commit()
        con.close()

        await q.message.edit_reply_markup(
            reply_markup=None
        )

        await q.message.reply_text(
            f"❌ <b>YECHISH RAD ETILDI</b>\n\n"
            f"🆔 User: <code>{user_id}</code>\n"
            f"⭐ Qaytarildi: {amount:.0f}",
            parse_mode="HTML"
        )

        try:
            await context.bot.send_message(
                user_id,
                "❌ <b>Yechish so‘rovingiz "
                "rad etildi.</b>\n\n"
                f"⭐ {amount:.0f} balansingizga "
                "qaytarildi.",
                parse_mode="HTML"
            )

        except TelegramError:
            pass

        return

    # =========================
    # GAMES
    # =========================

    if (
        data == "games_0"
        or data.startswith("games_")
    ):
        page = int(
            data.split("_")[1]
        )

        start_i = page * PAGE_SIZE

        items = GAMES[
            start_i:start_i + PAGE_SIZE
        ]

        kb = [
            [
                InlineKeyboardButton(
                    n,
                    callback_data=f"game_{t}"
                )
            ]
            for n, t in items
        ]

        nav = []

        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    "⬅️",
                    callback_data=f"games_{page-1}"
                )
            )

        if start_i + PAGE_SIZE < len(GAMES):
            nav.append(
                InlineKeyboardButton(
                    "➡️",
                    callback_data=f"games_{page+1}"
                )
            )

        if nav:
            kb.append(nav)

        kb.append([
            InlineKeyboardButton(
                "🏠 Menu",
                callback_data="home"
            )
        ])

        await q.message.reply_text(
            "🎮 <b>O‘YINLAR</b>\n\n"
            "O‘yinni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

        return

    # =========================
    # WORK
    # =========================

    if data == "work":
        kb = [
            [
                InlineKeyboardButton(
                    "🧠 Tezkor savol",
                    callback_data="work_quiz"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔢 Sonni top",
                    callback_data="work_number"
                )
            ],
            [
                InlineKeyboardButton(
                    "🧮 Hisobla",
                    callback_data="work_math"
                )
            ],
            [
                InlineKeyboardButton(
                    "⚡ Tez tanla",
                    callback_data="work_choice"
                )
            ],
            [
                InlineKeyboardButton(
                    "🧩 Mantiq",
                    callback_data="work_logic"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Orqaga",
                    callback_data="home"
                )
            ]
        ]

        await q.message.reply_text(
            "🎯 <b>STARS ISHLASH</b>\n\n"
            "Mini-o‘yinlarda to‘g‘ri javob "
            "berib virtual ⭐ ishlang.\n\n"
            f"🎁 To‘g‘ri javob: "
            f"+{GAME_REWARD} ⭐\n"
            f"⏳ Har o‘yindan keyin "
            f"{GAME_COOLDOWN} soniya kutish.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

        return

    # =========================
    # WORK GAME
    # =========================

    if data.startswith("work_"):

        # Cooldown
        last_game = context.user_data.get(
            "last_game_time",
            0
        )

        current_time = datetime.now(
            timezone.utc
        ).timestamp()

        remaining = (
            GAME_COOLDOWN
            - (current_time - last_game)
        )

        if remaining > 0:
            await q.answer(
                f"⏳ {int(remaining)+1} soniya kuting.",
                show_alert=True
            )
            return

        context.user_data[
            "last_game_time"
        ] = current_time

        kind = data[5:]

        if kind == "quiz":

            question, opts, correct = random.choice(
                QUIZ
            )

            kb = [
                [
                    InlineKeyboardButton(
                        x,
                        callback_data=(
                            f"ans_{correct}_{i}"
                        )
                    )
                ]
                for i, x in enumerate(opts)
            ]

            context.user_data[
                "answer"
            ] = correct

            await q.message.reply_text(
                "🧠 " + question,
                reply_markup=InlineKeyboardMarkup(kb)
            )

        elif kind == "number":

            n = random.randint(1, 5)

            context.user_data[
                "answer"
            ] = n

            kb = [[
                InlineKeyboardButton(
                    str(i),
                    callback_data=f"wn_{i}"
                )
                for i in range(1, 6)
            ]]

            await q.message.reply_text(
                "🔢 1 dan 5 gacha sonni toping:",
                reply_markup=InlineKeyboardMarkup(kb)
            )

        elif kind == "math":

            a = random.randint(2, 9)
            b = random.randint(2, 9)

            ans = a * b

            context.user_data[
                "answer"
            ] = ans

            options = [
                ans,
                ans + 1,
                ans - 1
            ]

            random.shuffle(options)

            kb = [[
                InlineKeyboardButton(
                    str(x),
                    callback_data=f"wm_{x}"
                )
                for x in options
            ]]

            await q.message.reply_text(
                f"🧮 {a} × {b} = ?",
                reply_markup=InlineKeyboardMarkup(kb)
            )

        elif kind == "choice":

            ans = random.choice(
                ["A", "B", "C"]
            )

            context.user_data[
                "answer"
            ] = ans

            await q.message.reply_text(
                f"⚡ To‘g‘ri variant: "
                f"{ans} ni tanlang:",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "A",
                            callback_data="wc_A"
                        ),
                        InlineKeyboardButton(
                            "B",
                            callback_data="wc_B"
                        ),
                        InlineKeyboardButton(
                            "C",
                            callback_data="wc_C"
                        )
                    ]
                ])
            )

        else:

            context.user_data[
                "answer"
            ] = 7

            await q.message.reply_text(
                "🧩 5 + 2 = ?",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "6",
                            callback_data="wl_6"
                        ),
                        InlineKeyboardButton(
                            "7",
                            callback_data="wl_7"
                        ),
                        InlineKeyboardButton(
                            "8",
                            callback_data="wl_8"
                        )
                    ]
                ])
            )

        return

    # =========================
    # WORK ANSWERS
    # =========================

    if data.startswith((
        "ans_",
        "wn_",
        "wm_",
        "wc_",
        "wl_"
    )):

        selected = data.split("_")[-1]

        try:
            selected_value = int(selected)
        except ValueError:
            selected_value = selected

        correct = context.user_data.get(
            "answer"
        )

        if correct is None:
            await q.message.reply_text(
                "❌ Bu savol muddati tugagan."
            )
            return

        won = selected_value == correct

        # Javobni o'chirish
        context.user_data.pop(
            "answer",
            None
        )

        game_result(
            uid,
            won
        )

        if won:
            change_points(
                uid,
                GAME_REWARD
            )

            await q.message.reply_text(
                f"🎉 To‘g‘ri!\n\n"
                f"⭐ +{GAME_REWARD} qo‘shildi.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🎯 Yana o‘ynash",
                            callback_data="work"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🏠 Menu",
                            callback_data="home"
                        )
                    ]
                ])
            )

        else:
            await q.message.reply_text(
                "❌ Noto‘g‘ri.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🎯 Yana o‘ynash",
                            callback_data="work"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🏠 Menu",
                            callback_data="home"
                        )
                    ]
                ])
            )

        return

    # =========================
    # OTHER GAMES
    # =========================

    if data.startswith("game_"):

        kind = data[5:]

        if kind == "quiz":

            question, opts, correct = random.choice(
                QUIZ
            )

            context.user_data[
                "game_answer"
            ] = correct

            await q.message.reply_text(
                "🎮 " + question,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            x,
                            callback_data=f"ga_{i}"
                        )
                    ]
                    for i, x in enumerate(opts)
                ])
            )

        else:

            a = random.randint(1, 9)
            b = random.randint(1, 9)

            ans = a + b

            context.user_data[
                "game_answer"
            ] = ans

            options = [
                ans - 1,
                ans,
                ans + 1
            ]

            random.shuffle(options)

            await q.message.reply_text(
                f"🎮 Hisoblang: "
                f"{a} + {b} = ?",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            str(x),
                            callback_data=f"gs_{x}"
                        )
                        for x in options
                    ]
                ])
            )

        return

    if data.startswith(("ga_", "gs_")):

        try:
            selected = int(
                data.split("_")[1]
            )
        except ValueError:
            return

        answer = context.user_data.get(
            "game_answer"
        )

        if answer is None:
            await q.message.reply_text(
                "❌ Bu savol muddati tugagan."
            )
            return

        won = selected == answer

        context.user_data.pop(
            "game_answer",
            None
        )

        game_result(
            uid,
            won
        )

        if won:
            change_points(
                uid,
                GAME_REWARD
            )

            msg = (
                f"🎉 To‘g‘ri!\n"
                f"⭐ +{GAME_REWARD}"
            )

        else:
            msg = "❌ Noto‘g‘ri."

        await q.message.reply_text(
            msg,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎮 O‘yinlar",
                        callback_data="games_0"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 Menu",
                        callback_data="home"
                    )
                ]
            ])
        )

        return

    # =========================
    # ADMIN PANEL
    # =========================

    if data == "admin":

        if uid != ADMIN_ID:
            return

        kb = [
            [
                InlineKeyboardButton(
                    "📊 Statistika",
                    callback_data="astats"
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 Foydalanuvchilar",
                    callback_data="ausers"
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 Reklama yuborish",
                    callback_data="abroadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ Task qo‘shish",
                    callback_data="atask"
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 Tasklar",
                    callback_data="atasks"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Orqaga",
                    callback_data="home"
                )
            ]
        ]

        await q.message.reply_text(
            "⚙️ <b>ADMIN PANEL</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

        return

    # =========================
    # ADMIN STATS
    # =========================

    if data == "astats" and uid == ADMIN_ID:

        con = db()
        cur = con.cursor()

        cur.execute("""
            SELECT
                COUNT(*),
                COALESCE(SUM(points),0),
                COALESCE(SUM(referrals),0)
            FROM users
        """)

        users, points, refs = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*)
            FROM withdrawals
            WHERE status='pending'
        """)

        withdrawals = cur.fetchone()[0]

        con.close()

        await q.message.reply_text(
            f"📊 <b>STATISTIKA</b>\n\n"
            f"👥 Users: {users}\n"
            f"⭐ Jami balans: {points:.2f}\n"
            f"🔗 Referallar: {refs}\n"
            f"💸 Kutilayotgan yechish: "
            f"{withdrawals}",
            parse_mode="HTML"
        )

        return

    # =========================
    # ADMIN USERS
    # =========================

    if data == "ausers" and uid == ADMIN_ID:

        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM users"
        )

        count = cur.fetchone()[0]

        con.close()

        await q.message.reply_text(
            f"👥 Bazadagi foydalanuvchilar: "
            f"{count}"
        )

        return

    # =========================
    # BROADCAST
    # =========================

    if data == "abroadcast" and uid == ADMIN_ID:

        context.user_data[
            "admin_action"
        ] = "broadcast"

        await q.message.reply_text(
            "📢 Yuboriladigan xabarni yozing."
        )

        return

    # =========================
    # ADD TASK
    # =========================

    if data == "atask" and uid == ADMIN_ID:

        context.user_data[
            "admin_action"
        ] = "task"

        await q.message.reply_text(
            "Format:\n"
            "MATN | REWARD | URL\n\n"
            "Masalan:\n"
            "Kanalga obuna | 5 | "
            "https://t.me/..."
        )

        return

    # =========================
    # TASK LIST
    # =========================

    if data == "atasks" and uid == ADMIN_ID:

        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT id,text,reward,url FROM tasks"
        )

        rows = cur.fetchall()

        con.close()

        text = "📋 <b>TASKLAR</b>\n\n"

        for tid, t, r, u in rows:
            text += (
                f"{tid}. {t} — {r}⭐\n"
                f"{u}\n\n"
            )

        await q.message.reply_text(
            text or "Task yo‘q.",
            parse_mode="HTML"
        )

        return


async def admin_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    action = context.user_data.get(
        "admin_action"
    )

    if not action:
        return

    # =========================
    # BROADCAST
    # =========================

    if action == "broadcast":

        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT id FROM users WHERE blocked=0"
        )

        ids = [
            x[0]
            for x in cur.fetchall()
        ]

        con.close()

        sent = 0

        for uid in ids:

            try:
                await context.bot.copy_message(
                    uid,
                    update.effective_chat.id,
                    update.message.message_id
                )

                sent += 1

                await asyncio.sleep(
                    0.03
                )

            except Forbidden:

                con = db()

                con.execute(
                    "UPDATE users SET blocked=1 "
                    "WHERE id=?",
                    (uid,)
                )

                con.commit()
                con.close()

            except RetryAfter as e:

                await asyncio.sleep(
                    e.retry_after
                )

            except TelegramError:
                pass

        context.user_data.pop(
            "admin_action",
            None
        )

        await update.message.reply_text(
            f"📢 Yuborildi: {sent}"
        )

        return

    # =========================
    # TASK
    # =========================

    if action == "task":

        try:
            text, reward, url = [
                x.strip()
                for x in update.message.text.split(
                    "|",
                    2
                )
            ]

            reward = float(reward)

            con = db()

            con.execute(
                """
                INSERT INTO tasks
                (text,reward,url)
                VALUES (?,?,?)
                """,
                (
                    text,
                    reward,
                    url
                )
            )

            con.commit()
            con.close()

            await update.message.reply_text(
                "✅ Task qo‘shildi."
            )

        except Exception:

            await update.message.reply_text(
                "❌ Format noto‘g‘ri.\n"
                "MATN | REWARD | URL"
            )

        context.user_data.pop(
            "admin_action",
            None
        )


async def error_handler(
    update,
    context
):

    log.error(
        "Bot xatosi: %s",
        context.error
    )


def main():

    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi!"
        )

    if not ADMIN_ID:
        raise RuntimeError(
            "ADMIN_ID topilmadi!"
        )

    init_db()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            menu
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_message
        )
    )

    app.add_error_handler(
        error_handler
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
