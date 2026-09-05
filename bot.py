import os
import sqlite3
import asyncio
import random
import logging
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
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8679536810"))

DB = "zerikdim.db"

STARS_BUY_URL = "https://t.me/premyumstarstekin/933"

# =========================================================
# REFERRAL / WITHDRAW SETTINGS
# =========================================================

# 1 ta tasdiqlangan do'st uchun
REFERRAL_REWARD = 9

# Pul/Stars yechish uchun jami 20 ta tasdiqlangan referral
WITHDRAW_REFERRALS = 20

# Minimal yechish
MIN_WITHDRAW = 50


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

def connect():
    return sqlite3.connect(DB)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    con = connect()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            points INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER,
            last_daily TEXT,
            last_seen TEXT,
            blocked INTEGER DEFAULT 0,
            referral_rewarded INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            channel TEXT PRIMARY KEY
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    columns = [
        row[1]
        for row in cur.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    ]

    if "blocked" not in columns:
        cur.execute(
            "ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0"
        )

    if "referral_rewarded" not in columns:
        cur.execute(
            "ALTER TABLE users ADD COLUMN referral_rewarded INTEGER DEFAULT 0"
        )

    con.commit()
    con.close()


# =========================================================
# USERS
# =========================================================

def add_user(user_id, username=None, referrer_id=None):
    con = connect()
    cur = con.cursor()

    cur.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    )

    exists = cur.fetchone()

    if exists:
        cur.execute("""
            UPDATE users
            SET username=?,
                last_seen=?,
                blocked=0
            WHERE id=?
        """, (
            username,
            now_utc(),
            user_id,
        ))

        con.commit()
        con.close()
        return False

    valid_referrer = None

    if referrer_id:
        if referrer_id != user_id:
            cur.execute(
                "SELECT id FROM users WHERE id=?",
                (referrer_id,)
            )

            if cur.fetchone():
                valid_referrer = referrer_id

    cur.execute("""
        INSERT INTO users
        (
            id,
            username,
            points,
            wins,
            games,
            referrals,
            referred_by,
            last_daily,
            last_seen,
            blocked,
            referral_rewarded
        )
        VALUES (?, ?, 0, 0, 0, ?, ?, NULL, ?, 0, 0)
    """, (
        user_id,
        username,
        0,
        valid_referrer,
        now_utc(),
    ))

    con.commit()
    con.close()

    return True


# =========================================================
# REFERRAL REWARD
# =========================================================

def reward_referral(user_id):
    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT referred_by, referral_rewarded
        FROM users
        WHERE id=?
    """, (user_id,))

    row = cur.fetchone()

    if not row:
        con.close()
        return False

    referred_by, rewarded = row

    # Oldin berilgan bo'lsa qayta bermaydi
    if not referred_by or rewarded:
        con.close()
        return False

    # O'zini o'zi referral qilishi mumkin emas
    if referred_by == user_id:
        con.close()
        return False

    cur.execute(
        "SELECT id FROM users WHERE id=?",
        (referred_by,)
    )

    if not cur.fetchone():
        con.close()
        return False

    # 1 ta haqiqiy referral = 9 ⭐
    cur.execute("""
        UPDATE users
        SET points = points + ?,
            referrals = referrals + 1
        WHERE id=?
    """, (
        REFERRAL_REWARD,
        referred_by,
    ))

    # Shu user uchun referral mukofoti berildi
    cur.execute("""
        UPDATE users
        SET referral_rewarded=1
        WHERE id=?
    """, (user_id,))

    con.commit()
    con.close()

    return True


def add_points(user_id, amount):
    con = connect()
    cur = con.cursor()

    cur.execute("""
        UPDATE users
        SET points = points + ?
        WHERE id=?
    """, (
        amount,
        user_id,
    ))

    con.commit()
    con.close()


def add_game_result(user_id, win=False):
    con = connect()
    cur = con.cursor()

    if win:
        cur.execute("""
            UPDATE users
            SET games=games+1,
                wins=wins+1
            WHERE id=?
        """, (user_id,))
    else:
        cur.execute("""
            UPDATE users
            SET games=games+1
            WHERE id=?
        """, (user_id,))

    con.commit()
    con.close()


def get_user(user_id):
    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT
            id,
            username,
            points,
            wins,
            games,
            referrals,
            referred_by,
            last_daily,
            last_seen,
            blocked,
            referral_rewarded
        FROM users
        WHERE id=?
    """, (user_id,))

    row = cur.fetchone()

    con.close()
    return row


def get_user_count():
    con = connect()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM users")

    result = cur.fetchone()[0]

    con.close()

    return result


def get_sponsors():
    con = connect()
    cur = con.cursor()

    cur.execute(
        "SELECT channel FROM sponsors ORDER BY channel"
    )

    result = [x[0] for x in cur.fetchall()]

    con.close()

    return result


# =========================================================
# SUBSCRIPTION
# =========================================================

async def check_subscription(user_id, context):
    if user_id == ADMIN_ID:
        return True

    sponsors = get_sponsors()

    if not sponsors:
        return True

    for channel in sponsors:
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel,
                user_id=user_id
            )

            if member.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.KICKED,
            ):
                return False

        except TelegramError as e:
            logger.error(
                "Subscription check error %s: %s",
                channel,
                e
            )

            # Bot kanalga kira olmasa xavfsizlik uchun
            # subscription bajarilmagan deb hisoblanadi.
            return False

    return True


def subscription_message():
    sponsors = get_sponsors()

    text = (
        "🔒 <b>BOTDAN FOYDALANISH UCHUN OBUNA BO‘LING</b>\n\n"
        "📢 Quyidagi homiy kanallarga obuna bo‘lish shart.\n\n"
        "1️⃣ Kanalga kiring\n"
        "2️⃣ Obuna bo‘ling\n"
        "3️⃣ <b>✅ OBUNA BO‘LDIM</b> tugmasini bosing"
    )

    buttons = []

    for channel in sponsors:
        clean = channel.replace("@", "")

        buttons.append([
            InlineKeyboardButton(
                f"📢 {channel}",
                url=f"https://t.me/{clean}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✅ OBUNA BO‘LDIM",
            callback_data="check_sub"
        )
    ])

    return text, InlineKeyboardMarkup(buttons)


async def require_subscription(update, context):
    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        return True

    if await check_subscription(user_id, context):
        return True

    text, markup = subscription_message()

    if update.callback_query:
        try:
            await update.callback_query.answer(
                "❌ Avval homiy kanallarga obuna bo‘ling!",
                show_alert=True
            )

            await update.callback_query.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception:
            pass

    elif update.message:
        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML"
        )

    return False


# =========================================================
# MAIN MENU
# =========================================================

def main_menu(user_id):
    count = get_user_count()

    buttons = [
        [
            InlineKeyboardButton(
                "🎮 O‘YINLAR",
                callback_data="games"
            ),
            InlineKeyboardButton(
                "⭐ BALL",
                callback_data="balance"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 DAILY",
                callback_data="daily"
            ),
            InlineKeyboardButton(
                "👥 DO‘ST TAKLIF",
                callback_data="ref"
            )
        ],
        [
            InlineKeyboardButton(
                "💸 STARS YECHISH",
                callback_data="withdraw"
            ),
            InlineKeyboardButton(
                "⭐ STARS OLISH",
                callback_data="buy_stars"
            )
        ],
        [
            InlineKeyboardButton(
                "🏆 REYTING",
                callback_data="top"
            ),
            InlineKeyboardButton(
                "👤 PROFIL",
                callback_data="profile"
            )
        ],
        [
            InlineKeyboardButton(
                f"👥 FOYDALANUVCHILAR: {count}",
                callback_data="user_count"
            )
        ],
    ]

    if user_id == ADMIN_ID:
        buttons.append([
            InlineKeyboardButton(
                "⚙️ ADMIN PANEL",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(buttons)


async def send_main_menu(update, context, edit=False):
    user_id = update.effective_user.id

    text = (
        "🎉 <b>ZERIKDIM BOT</b>\n\n"
        "😎 Zerikdingizmi? Unda o‘yin o‘ynang!\n"
        "⭐ Ball yig‘ing, do‘stlaringizni taklif qiling "
        "va bonuslarga ega bo‘ling.\n\n"
        "👇 Kerakli bo‘limni tanlang:"
    )

    markup = main_menu(user_id)

    if edit and update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text,
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode="HTML"
            )
    else:
        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML"
        )


# =========================================================
# GAMES MENU
# =========================================================

def games_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎯 DARTS",
                callback_data="dart"
            ),
            InlineKeyboardButton(
                "🎳 BOWLING",
                callback_data="bowling"
            )
        ],
        [
            InlineKeyboardButton(
                "🎲 ZAR",
                callback_data="dice"
            ),
            InlineKeyboardButton(
                "🧠 SAVOL-JAVOB",
                callback_data="quiz"
            )
        ],
        [
            InlineKeyboardButton(
                "🔢 SON TOP",
                callback_data="number"
            ),
            InlineKeyboardButton(
                "🏝️ OROL",
                callback_data="island"
            )
        ],
        [
            InlineKeyboardButton(
                "🇺🇳 BAYROQ",
                callback_data="flag"
            ),
            InlineKeyboardButton(
                "🧩 TOPISHMOQ",
                callback_data="riddle"
            )
        ],
        [
            InlineKeyboardButton(
                "⚡ TEZKOR",
                callback_data="quick"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 ORQAGA",
                callback_data="home"
            )
        ],
    ])


async def games(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    await update.callback_query.message.edit_text(
        "🎮 <b>O‘YINLAR</b>\n\n"
        "👇 O‘ynash uchun o‘yinni tanlang:",
        reply_markup=games_menu(),
        parse_mode="HTML"
    )


# =========================================================
# QUIZ
# =========================================================

QUIZES = [
    (
        "Agar 5 ta mashina 5 daqiqada 5 ta detal ishlab chiqarsa, "
        "100 ta mashina 100 ta detalni necha daqiqada ishlab chiqaradi?",
        ["5", "20", "100", "1"],
        0
    ),
    (
        "Ketma-ketlikni davom ettiring: 2, 6, 12, 20, 30, 42, ?",
        ["54", "56", "58", "60"],
        1
    ),
    (
        "Bir sonning 40 foizi 28 ga teng. Sonning o‘zi nechaga teng?",
        ["56", "65", "70", "72"],
        2
    ),
    (
        "Agar x + y = 17 va x - y = 5 bo‘lsa, x nechaga teng?",
        ["6", "11", "12", "13"],
        1
    ),
    (
        "3² + 4² + 5² qiymati nechaga teng?",
        ["25", "40", "50", "60"],
        1
    ),
    (
        "Soat 3:30 da soat va minut strelkalari orasidagi kichik burchak nechaga teng?",
        ["60°", "75°", "90°", "105°"],
        1
    ),
    (
        "1 dan 100 gacha bo‘lgan sonlarda 0 raqami jami necha marta uchraydi?",
        ["10", "11", "12", "20"],
        2
    ),
    (
        "Agar barcha ZOR lar MUK bo‘lsa va ba’zi MUK lar TAR bo‘lsa, "
        "qaysi xulosa doimo to‘g‘ri?",
        [
            "Barcha ZOR lar TAR",
            "Ba'zi ZOR lar TAR",
            "Hech bir ZOR TAR emas",
            "Aniq xulosa qilib bo‘lmaydi"
        ],
        3
    ),
    (
        "Fibonachchi ketma-ketligi: 1, 1, 2, 3, 5, 8, ?",
        ["11", "12", "13", "15"],
        2
    ),
    (
        "√144 + √81 - √25 = ?",
        ["14", "16", "18", "20"],
        1
    ),
    (
        "Agar 2x - 7 = 15 bo‘lsa, x nechaga teng?",
        ["9", "10", "11", "12"],
        1
    ),
    (
        "Qaysi son tub son emas?",
        ["29", "31", "37", "39"],
        3
    ),
    (
        "Bir uchburchak burchaklari 2x, 3x va 4x. "
        "Eng katta burchak nechaga teng?",
        ["60°", "70°", "80°", "90°"],
        2
    ),
    (
        "Ketma-ketlik: 1, 4, 9, 16, 25, ?",
        ["30", "36", "40", "49"],
        1
    ),
    (
        "Agar 3 ta ishchi ishni 12 kunda tugatsa, "
        "bir xil tezlikda 6 ta ishchi necha kunda tugatadi?",
        ["2", "4", "6", "8"],
        2
    ),
    (
        "2³ × 3² qiymati nechaga teng?",
        ["36", "54", "72", "81"],
        2
    ),
    (
        "Bir sonning 25 foizi 45 bo‘lsa, 60 foizi nechaga teng?",
        ["90", "108", "120", "135"],
        1
    ),
    (
        "Qaysi biri boshqa uchalasidan farq qiladi?",
        ["16", "25", "36", "48"],
        3
    ),
    (
        "Agar bugun chorshanba bo‘lsa, 100 kundan keyin qaysi kun bo‘ladi?",
        ["Dushanba", "Chorshanba", "Juma", "Yakshanba"],
        2
    ),
    (
        "5x + 10 = 3x + 24. x nechaga teng?",
        ["5", "6", "7", "8"],
        2
    ),
    (
        "Bir son 20% ga oshirilganda 72 bo‘ldi. "
        "Boshlang‘ich son nechaga teng?",
        ["50", "55", "60", "65"],
        2
    ),
    (
        "Ketma-ketlik: 3, 8, 15, 24, 35, ?",
        ["46", "48", "50", "52"],
        1
    ),
    (
        "Qaysi sayyora Quyoshga eng yaqin?",
        ["Venera", "Mars", "Merkuriy", "Yer"],
        2
    ),
    (
        "Agar barcha A lar B bo‘lsa va hech bir B C bo‘lmasa, "
        "qaysi gap to‘g‘ri?",
        [
            "Ba'zi A lar C",
            "Barcha A lar C",
            "Hech bir A C emas",
            "Aniqlab bo‘lmaydi"
        ],
        2
    ),
    (
        "12 × 12 - 11 × 11 = ?",
        ["21", "23", "25", "27"],
        1
    ),
    (
        "Bir qutida 3 ta qizil, 4 ta ko‘k va 5 ta yashil shar bor. "
        "Ko‘z yumib bitta rangdan kamida 2 ta shar olish kafolatlanishi uchun "
        "kamida nechta shar olish kerak?",
        ["4", "5", "6", "7"],
        1
    ),
    (
        "Agar 7² - 5² = x bo‘lsa, x nechaga teng?",
        ["20", "24", "25", "30"],
        1
    ),
    (
        "1000 sonining 10% i 100 bo‘lsa, uning 2.5% i nechaga teng?",
        ["20", "25", "30", "40"],
        1
    ),
    (
        "Ketma-ketlik: 81, 27, 9, 3, ?",
        ["0", "1", "2", "6"],
        1
    ),
    (
        "Bir oilada 4 aka-uka bor. Har birining bittadan singlisi bor. "
        "Oilada jami nechta farzand bor?",
        ["4", "5", "8", "9"],
        1
    ),
]


async def quiz_start(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    q, options, correct = random.choice(QUIZES)

    context.user_data["quiz"] = {
        "correct": correct,
        "question": q,
    }

    buttons = []

    for i, option in enumerate(options):
        buttons.append([
            InlineKeyboardButton(
                option,
                callback_data=f"quiz_answer_{i}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 O‘YINLAR",
            callback_data="games"
        )
    ])

    await update.callback_query.message.edit_text(
        f"🧠 <b>SAVOL-JAVOB</b>\n\n{q}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )


async def quiz_answer(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    try:
        answer = int(
            update.callback_query.data.split("_")[-1]
        )
    except Exception:
        return

    quiz = context.user_data.get("quiz")

    if not quiz:
        await quiz_start(update, context)
        return

    correct = quiz["correct"]

    if answer == correct:
        add_points(update.effective_user.id, 2)
        add_game_result(
            update.effective_user.id,
            True
        )

        text = (
            "🎉 <b>TO‘G‘RI!</b>\n\n"
            "⭐ Sizga <b>+2 ball</b> berildi."
        )
    else:
        add_game_result(
            update.effective_user.id,
            False
        )

        text = (
            "❌ <b>NOTO‘G‘RI!</b>\n\n"
            "😅 Yana urinib ko‘ring."
        )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🧠 YANA SAVOL",
                    callback_data="quiz"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# RIDDLES
# =========================================================

RIDDLES = [
    (
        "Men gapirmayman, lekin sen gapirsang javob qaytaraman. Men kimman?",
        ["Kitob", "Aks-sado", "Telefon", "Radio"],
        1
    ),
    (
        "Qanoti bor, qush emas. Osmonda uchadi, samolyot emas. Bu nima?",
        ["Bulut", "Kapalak", "Shamol", "Barg"],
        0
    ),
    (
        "Qancha ko‘p olsang, shuncha kattalashadi. Bu nima?",
        ["Teshik", "Pul", "Suv", "Vaqt"],
        0
    ),
    (
        "Tili bor, lekin gapirmaydi. Og‘zi bor, lekin ovqat yemaydi.",
        ["Qo‘ng‘iroq", "Daryo", "Kitob", "Stol"],
        1
    ),
    (
        "Ichida hech narsa yo‘q, lekin narsalarni saqlaydi. Bu nima?",
        ["Quti", "Bulut", "Ko‘zgu", "Soyabon"],
        0
    ),
    (
        "Har kuni yuradi, lekin joyidan siljimaydi.",
        ["Soat", "Odam", "Mashina", "Daraxt"],
        0
    ),
]


async def riddle_start(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    q, options, correct = random.choice(RIDDLES)

    context.user_data["riddle"] = correct

    buttons = []

    for i, option in enumerate(options):
        buttons.append([
            InlineKeyboardButton(
                option,
                callback_data=f"riddle_answer_{i}"
            )
        ])

    await update.callback_query.message.edit_text(
        f"🧩 <b>TOPISHMOQ</b>\n\n{q}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )


async def riddle_answer(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    try:
        answer = int(
            update.callback_query.data.split("_")[-1]
        )
    except Exception:
        return

    correct = context.user_data.get("riddle")

    if answer == correct:
        add_points(update.effective_user.id, 2)
        add_game_result(
            update.effective_user.id,
            True
        )

        text = "🎉 <b>TO‘G‘RI!</b>\n⭐ +2 ball"
    else:
        add_game_result(
            update.effective_user.id,
            False
        )

        text = "❌ <b>NOTO‘G‘RI!</b>"

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🧩 YANA",
                    callback_data="riddle"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# FLAGS
# =========================================================

FLAGS = [
    ("🇺🇿", ["O‘zbekiston", "Qozog‘iston", "Turkiya", "Pokiston"], 0),
    ("🇯🇵", ["Xitoy", "Yaponiya", "Koreya", "Vetnam"], 1),
    ("🇹🇷", ["Turkiya", "Tunis", "Marokash", "Misr"], 0),
    ("🇰🇷", ["Yaponiya", "Koreya", "Xitoy", "Tailand"], 1),
    ("🇺🇸", ["AQSH", "Kanada", "Angliya", "Avstraliya"], 0),
    ("🇬🇧", ["AQSH", "Buyuk Britaniya", "Fransiya", "Irlandiya"], 1),
    ("🇩🇪", ["Belgiya", "Germaniya", "Avstriya", "Polsha"], 1),
    ("🇫🇷", ["Fransiya", "Italiya", "Niderlandiya", "Belgiya"], 0),
]


async def flag_start(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    flag, options, correct = random.choice(FLAGS)

    context.user_data["flag"] = correct

    buttons = []

    for i, option in enumerate(options):
        buttons.append([
            InlineKeyboardButton(
                option,
                callback_data=f"flag_answer_{i}"
            )
        ])

    await update.callback_query.message.edit_text(
        f"🇺🇳 <b>BAYROQNI TOPING</b>\n\n"
        f"Qaysi davlat bayrog‘i?\n\n"
        f"<b>{flag}</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )


async def flag_answer(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    try:
        answer = int(
            update.callback_query.data.split("_")[-1]
        )
    except Exception:
        return

    correct = context.user_data.get("flag")

    if answer == correct:
        add_points(update.effective_user.id, 2)
        add_game_result(
            update.effective_user.id,
            True
        )

        text = "🎉 <b>TO‘G‘RI!</b>\n⭐ +2 ball"
    else:
        add_game_result(
            update.effective_user.id,
            False
        )

        text = "❌ <b>NOTO‘G‘RI!</b>"

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🇺🇳 YANA",
                    callback_data="flag"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# QUICK
# =========================================================

async def quick_start(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    number = random.randint(1, 9)

    context.user_data["quick"] = number

    await update.callback_query.message.edit_text(
        f"⚡ <b>TEZKOR</b>\n\n"
        f"Quyidagi raqamni tanlang:\n\n"
        f"🎯 <b>{number}</b>",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1", callback_data="quick_1"),
                InlineKeyboardButton("2", callback_data="quick_2"),
                InlineKeyboardButton("3", callback_data="quick_3")
            ],
            [
                InlineKeyboardButton("4", callback_data="quick_4"),
                InlineKeyboardButton("5", callback_data="quick_5"),
                InlineKeyboardButton("6", callback_data="quick_6")
            ],
            [
                InlineKeyboardButton("7", callback_data="quick_7"),
                InlineKeyboardButton("8", callback_data="quick_8"),
                InlineKeyboardButton("9", callback_data="quick_9")
            ],
        ])
    )


async def quick_answer(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    try:
        answer = int(
            update.callback_query.data.split("_")[-1]
        )
    except Exception:
        return

    correct = context.user_data.get("quick")

    if answer == correct:
        add_points(update.effective_user.id, 2)
        add_game_result(
            update.effective_user.id,
            True
        )

        text = (
            "⚡🎉 <b>TEZKOR VA TO‘G‘RI!</b>\n"
            "⭐ +2 ball"
        )
    else:
        add_game_result(
            update.effective_user.id,
            False
        )

        text = "❌ <b>XATO!</b>"

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⚡ YANA",
                    callback_data="quick"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# NUMBER
# =========================================================

async def number_start(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    number = random.randint(1, 10)

    context.user_data["number"] = number

    await update.callback_query.message.edit_text(
        "🔢 <b>SON TOP</b>\n\n"
        "1 dan 10 gacha yashirilgan sonni toping!",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1", callback_data="number_1"),
                InlineKeyboardButton("2", callback_data="number_2"),
                InlineKeyboardButton("3", callback_data="number_3"),
                InlineKeyboardButton("4", callback_data="number_4"),
                InlineKeyboardButton("5", callback_data="number_5"),
            ],
            [
                InlineKeyboardButton("6", callback_data="number_6"),
                InlineKeyboardButton("7", callback_data="number_7"),
                InlineKeyboardButton("8", callback_data="number_8"),
                InlineKeyboardButton("9", callback_data="number_9"),
                InlineKeyboardButton("10", callback_data="number_10"),
            ],
        ])
    )


async def number_answer(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    try:
        answer = int(
            update.callback_query.data.split("_")[-1]
        )
    except Exception:
        return

    correct = context.user_data.get("number")

    if answer == correct:
        add_points(update.effective_user.id, 3)
        add_game_result(
            update.effective_user.id,
            True
        )

        text = (
            "🎉 <b>TOPDINGIZ!</b>\n"
            "⭐ +3 ball"
        )
    else:
        add_game_result(
            update.effective_user.id,
            False
        )

        text = (
            f"❌ <b>TOPA OLMADINGIZ.</b>\n\n"
            f"To‘g‘ri javob: <b>{correct}</b>"
        )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔢 YANA",
                    callback_data="number"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# ISLAND
# =========================================================

async def island_start(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    correct = random.randint(0, 2)

    context.user_data["island"] = correct

    await update.callback_query.message.edit_text(
        "🏝️ <b>OROL</b>\n\n"
        "Xazina qaysi orolda yashiringan?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏝️ Orol 1",
                    callback_data="island_0"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏝️ Orol 2",
                    callback_data="island_1"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏝️ Orol 3",
                    callback_data="island_2"
                )
            ],
        ])
    )


async def island_answer(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    try:
        answer = int(
            update.callback_query.data.split("_")[-1]
        )
    except Exception:
        return

    correct = context.user_data.get("island")

    if answer == correct:
        add_points(update.effective_user.id, 4)
        add_game_result(
            update.effective_user.id,
            True
        )

        text = (
            "🏆💰 <b>XAZINANI TOPDINGIZ!</b>\n"
            "⭐ +4 ball"
        )
    else:
        add_game_result(
            update.effective_user.id,
            False
        )

        text = "🌊❌ <b>Xazina bu orolda emas!</b>"

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏝️ YANA",
                    callback_data="island"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# MATH
# =========================================================

def make_math():
    a = random.randint(5, 30)
    b = random.randint(2, 20)

    operation = random.choice([
        "+",
        "-",
        "*"
    ])

    if operation == "+":
        correct = a + b
    elif operation == "-":
        correct = a - b
    else:
        correct = a * b

    answers = {correct}

    while len(answers) < 4:
        answers.add(
            correct + random.randint(-15, 15)
        )

    answers = list(answers)
    random.shuffle(answers)

    return (
        f"{a} {operation} {b} = ?",
        [str(x) for x in answers],
        answers.index(correct)
    )


async def math_start(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    q, options, correct = make_math()

    context.user_data["math"] = correct

    buttons = []

    for i, option in enumerate(options):
        buttons.append([
            InlineKeyboardButton(
                option,
                callback_data=f"math_{i}"
            )
        ])

    await update.callback_query.message.edit_text(
        f"➕ <b>MATEMATIKA</b>\n\n{q}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )


async def math_answer(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    try:
        answer = int(
            update.callback_query.data.split("_")[-1]
        )
    except Exception:
        return

    correct = context.user_data.get("math")

    if answer == correct:
        add_points(update.effective_user.id, 2)
        add_game_result(
            update.effective_user.id,
            True
        )

        text = (
            "🎉 <b>TO‘G‘RI!</b>\n"
            "⭐ +2 ball"
        )
    else:
        add_game_result(
            update.effective_user.id,
            False
        )

        text = "❌ <b>NOTO‘G‘RI!</b>"

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "➕ YANA",
                    callback_data="math"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# TELEGRAM DICE GAMES
# =========================================================

async def dart(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    msg = await update.callback_query.message.reply_dice(
        emoji="🎯"
    )

    value = msg.dice.value

    add_game_result(
        update.effective_user.id,
        value >= 4
    )

    if value >= 4:
        add_points(
            update.effective_user.id,
            2
        )

        text = (
            "🎯🎉 <b>YAXSHI OTISH!</b>\n"
            "⭐ +2 ball"
        )
    else:
        text = "🎯😅 Yana urinib ko‘ring!"

    await asyncio.sleep(1)

    await update.callback_query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎯 YANA",
                    callback_data="dart"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


async def bowling(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    msg = await update.callback_query.message.reply_dice(
        emoji="🎳"
    )

    value = msg.dice.value

    add_game_result(
        update.effective_user.id,
        value >= 4
    )

    if value >= 4:
        add_points(
            update.effective_user.id,
            2
        )

        text = (
            "🎳🎉 <b>STRIKEGA YAQIN!</b>\n"
            "⭐ +2 ball"
        )
    else:
        text = "🎳😅 Yana urinib ko‘ring!"

    await asyncio.sleep(1)

    await update.callback_query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎳 YANA",
                    callback_data="bowling"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


async def dice(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    msg = await update.callback_query.message.reply_dice(
        emoji="🎲"
    )

    value = msg.dice.value

    add_game_result(
        update.effective_user.id,
        value >= 4
    )

    if value >= 4:
        add_points(
            update.effective_user.id,
            1
        )

        text = (
            f"🎲 <b>{value}</b>\n"
            "⭐ +1 ball"
        )
    else:
        text = (
            f"🎲 <b>{value}</b>\n"
            "😅 Bu safar omad kelmadi."
        )

    await asyncio.sleep(1)

    await update.callback_query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎲 YANA",
                    callback_data="dice"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# DAILY
# =========================================================

async def daily(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    user_id = update.effective_user.id

    row = get_user(user_id)

    if not row:
        return

    last_daily = row[7]

    today = datetime.now(
        timezone.utc
    ).date()

    if last_daily:
        try:
            last_date = datetime.fromisoformat(
                last_daily
            ).date()

            if last_date == today:
                await update.callback_query.message.edit_text(
                    "🎁 <b>DAILY</b>\n\n"
                    "⏳ Bugungi bonusni allaqachon oldingiz.\n"
                    "🌙 Ertaga yana qaytib keling!",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "🔙 MENU",
                                callback_data="home"
                            )
                        ]
                    ]),
                    parse_mode="HTML"
                )

                return

        except Exception:
            pass

    bonus = random.randint(2, 5)

    con = connect()
    cur = con.cursor()

    cur.execute("""
        UPDATE users
        SET points=points+?,
            last_daily=?
        WHERE id=?
    """, (
        bonus,
        now_utc(),
        user_id,
    ))

    con.commit()
    con.close()

    await update.callback_query.message.edit_text(
        "🎁 <b>DAILY BONUS!</b>\n\n"
        f"⭐ Siz <b>+{bonus} ball</b> oldingiz!\n\n"
        "🔥 Ertaga yana kirishni unutmang.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 MENU",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# BALANCE
# =========================================================

async def balance(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    row = get_user(
        update.effective_user.id
    )

    points = row[2] if row else 0

    await update.callback_query.message.edit_text(
        "⭐ <b>SIZNING BALLARINGIZ</b>\n\n"
        f"💰 Balans: <b>{points} ⭐</b>",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💸 YECHISH",
                    callback_data="withdraw"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 MENU",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# REFERRAL
# =========================================================

async def referral(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    user_id = update.effective_user.id

    row = get_user(user_id)

    referrals = row[5] if row else 0

    bot = await context.bot.get_me()

    link = (
        f"https://t.me/{bot.username}"
        f"?start=ref_{user_id}"
    )

    if referrals < 10:
        progress_text = (
            "🎯 <b>10 ta referral</b>ga yeting.\n"
            f"📊 Qolgan: <b>{10 - referrals} ta</b>"
        )

    elif referrals < WITHDRAW_REFERRALS:
        progress_text = (
            "🔥 Siz 10 ta referralga yetdingiz!\n\n"
            "💸 Yechish uchun yana:\n"
            f"👥 <b>{WITHDRAW_REFERRALS - referrals} ta</b> "
            "tasdiqlangan do‘st kerak."
        )

    else:
        progress_text = (
            "✅ <b>Yechish sharti bajarildi!</b>\n"
            "💸 Endi Stars yechishingiz mumkin."
        )

    await update.callback_query.message.edit_text(
        "👥 <b>DO‘ST TAKLIF QILING</b>\n\n"
        "🔗 Sizning referral havolangiz:\n\n"
        f"<code>{link}</code>\n\n"
        "🎁 Har bir tasdiqlangan do‘st uchun:\n"
        f"⭐ <b>+{REFERRAL_REWARD} ⭐</b>\n\n"
        f"👥 Taklif qilganlaringiz: <b>{referrals}</b>\n\n"
        f"{progress_text}\n\n"
        "📢 Do‘stingiz homiy kanallarga obuna bo‘lgandan "
        "keyingina referral hisoblanadi.\n\n"
        "⚠️ Bir odam faqat bir marta hisoblanadi.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📤 ULASHISH",
                    url=(
                        "https://t.me/share/url?"
                        f"url={link}&"
                        "text=Zerikdim%20botga%20qo‘shiling!"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 MENU",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# BUY STARS
# =========================================================

async def buy_stars(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    await update.callback_query.message.edit_text(
        "⭐ <b>STARS OLISH</b>\n\n"
        "Telegram Stars olish uchun quyidagi tugmani bosing:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⭐ STARS OLISH",
                    url=STARS_BUY_URL
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 MENU",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# WITHDRAW
# =========================================================

async def withdraw(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    row = get_user(
        update.effective_user.id
    )

    if not row:
        return

    points = row[2]
    referrals = row[5]

    # 20 ta referral bo'lmasa yechishga ruxsat yo'q
    if referrals < WITHDRAW_REFERRALS:
        remaining = WITHDRAW_REFERRALS - referrals

        await update.callback_query.message.edit_text(
            "💸 <b>STARS YECHISH</b>\n\n"
            f"❌ Yechish uchun jami "
            f"<b>{WITHDRAW_REFERRALS} ta tasdiqlangan referral</b> "
            "kerak.\n\n"
            f"👥 Sizda: <b>{referrals}</b>\n"
            f"🎯 Qolgan: <b>{remaining} ta</b>\n\n"
            "🔥 Do‘stlaringizni taklif qiling!",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "👥 DO‘ST TAKLIF",
                        callback_data="ref"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 MENU",
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    if points < MIN_WITHDRAW:
        await update.callback_query.message.edit_text(
            "💸 <b>STARS YECHISH</b>\n\n"
            f"❌ Minimal yechish: "
            f"<b>{MIN_WITHDRAW} ⭐</b>\n\n"
            f"⭐ Sizda: <b>{points} ⭐</b>",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎮 O‘YIN O‘YNASH",
                        callback_data="games"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 MENU",
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    context.user_data["waiting_withdraw"] = True

    await update.callback_query.message.edit_text(
        "💸 <b>STARS YECHISH</b>\n\n"
        f"⭐ Balansingiz: <b>{points} ⭐</b>\n"
        f"👥 Referral: <b>{referrals}/{WITHDRAW_REFERRALS}</b>\n\n"
        "✍️ Qancha ⭐ yechmoqchi ekaningizni yozing:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ BEKOR QILISH",
                    callback_data="cancel"
                )
            ]
        ]),
        parse_mode="HTML"
    )


async def process_withdraw(update, context):
    user = update.effective_user

    try:
        amount = int(
            update.message.text.strip()
        )
    except ValueError:
        await update.message.reply_text(
            "❌ Faqat raqam yuboring.\n\n"
            f"Minimal: {MIN_WITHDRAW} ⭐"
        )

        return

    row = get_user(user.id)

    if not row:
        return

    points = row[2]
    referrals = row[5]

    if referrals < WITHDRAW_REFERRALS:
        context.user_data.pop(
            "waiting_withdraw",
            None
        )

        await update.message.reply_text(
            "❌ Yechish uchun "
            f"{WITHDRAW_REFERRALS} ta tasdiqlangan referral kerak."
        )

        return

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimal yechish: {MIN_WITHDRAW} ⭐"
        )

        return

    if amount > points:
        await update.message.reply_text(
            "❌ Balansingiz yetarli emas."
        )

        return

    username = user.username or "username_yoq"

    con = connect()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO withdrawals
        (
            user_id,
            username,
            amount,
            status,
            created_at
        )
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        user.id,
        username,
        amount,
        now_utc(),
    ))

    withdrawal_id = cur.lastrowid

    con.commit()
    con.close()

    context.user_data.pop(
        "waiting_withdraw",
        None
    )

    await update.message.reply_text(
        "✅ <b>ARIZA QABUL QILINDI!</b>\n\n"
        f"⭐ Miqdor: <b>{amount} ⭐</b>\n"
        f"👥 Referral: <b>{referrals}</b>\n"
        f"🆔 Ariza: <b>#{withdrawal_id}</b>\n\n"
        "⏳ Admin tekshiradi.",
        parse_mode="HTML"
    )

    try:
        await context.bot.send_message(
            ADMIN_ID,
            "💸 <b>YANGI YECHISH ARIZASI</b>\n\n"
            f"👤 User: @{username}\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"⭐ Miqdor: <b>{amount}</b>\n"
            f"👥 Referral: <b>{referrals}</b>\n"
            f"📋 Ariza: <b>#{withdrawal_id}</b>",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(
            "Admin notification error: %s",
            e
        )


# =========================================================
# PROFILE
# =========================================================

async def profile(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    row = get_user(
        update.effective_user.id
    )

    if not row:
        return

    username = row[1] or "yo‘q"
    points = row[2]
    wins = row[3]
    games_count = row[4]
    referrals = row[5]

    await update.callback_query.message.edit_text(
        "👤 <b>PROFIL</b>\n\n"
        f"🆔 ID: <code>{row[0]}</code>\n"
        f"👤 Username: @{username}\n\n"
        f"⭐ Ball: <b>{points}</b>\n"
        f"🎮 O‘yinlar: <b>{games_count}</b>\n"
        f"🏆 G‘alabalar: <b>{wins}</b>\n"
        f"👥 Referral: <b>{referrals}</b>",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 MENU",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# TOP
# =========================================================

async def top(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT username, points
        FROM users
        ORDER BY points DESC
        LIMIT 10
    """)

    rows = cur.fetchall()

    con.close()

    text = "🏆 <b>TOP 10</b>\n\n"

    if not rows:
        text += "Hali hech kim yo‘q."
    else:
        medals = [
            "🥇",
            "🥈",
            "🥉",
            "4️⃣",
            "5️⃣",
            "6️⃣",
            "7️⃣",
            "8️⃣",
            "9️⃣",
            "🔟",
        ]

        for i, row in enumerate(rows):
            username = row[0] or "Noma'lum"
            points = row[1]

            text += (
                f"{medals[i]} "
                f"@{username} — "
                f"<b>{points} ⭐</b>\n"
            )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 MENU",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# USER COUNT
# =========================================================

async def show_user_count(update, context):
    if not await require_subscription(update, context):
        return

    await update.callback_query.answer()

    count = get_user_count()

    await update.callback_query.message.edit_text(
        "👥 <b>FOYDALANUVCHILAR</b>\n\n"
        f"📊 Botdan foydalanishni boshlaganlar: "
        f"<b>{count}</b>\n\n"
        "ℹ️ Bu hisobga botni oldin ishga tushirgan "
        "foydalanuvchilar ham kiradi.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 MENU",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# ADMIN MENU
# =========================================================

def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 STATISTIKA",
                callback_data="admin_stats"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 XABAR YUBORISH",
                callback_data="broadcast"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ HOMIY QO‘SHISH",
                callback_data="sponsor_add"
            )
        ],
        [
            InlineKeyboardButton(
                "➖ HOMIY O‘CHIRISH",
                callback_data="sponsor_remove"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 HOMIYLAR",
                callback_data="sponsor_list"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 MENU",
                callback_data="home"
            )
        ],
    ])


async def admin_panel(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.callback_query.answer(
            "❌ Siz admin emassiz!",
            show_alert=True
        )
        return

    await update.callback_query.answer()

    await update.callback_query.message.edit_text(
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        "Kerakli bo‘limni tanlang:",
        reply_markup=admin_menu(),
        parse_mode="HTML"
    )


# =========================================================
# ADMIN STATS
# =========================================================

async def admin_stats(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.callback_query.answer()

    con = connect()
    cur = con.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM users"
    )
    total = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM users WHERE blocked=1"
    )
    blocked = cur.fetchone()[0]

    cur.execute(
        "SELECT SUM(points) FROM users"
    )
    total_points = cur.fetchone()[0] or 0

    cur.execute(
        "SELECT SUM(games) FROM users"
    )
    total_games = cur.fetchone()[0] or 0

    cur.execute(
        "SELECT SUM(referrals) FROM users"
    )
    total_referrals = cur.fetchone()[0] or 0

    cur.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE last_seen IS NOT NULL
        AND last_seen >= ?
    """, (
        (
            datetime.now(timezone.utc)
            - timedelta(days=1)
        ).isoformat(),
    ))

    active_24h = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM withdrawals
        WHERE status='pending'
    """)

    pending_withdrawals = cur.fetchone()[0]

    con.close()

    await update.callback_query.message.edit_text(
        "📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Jami userlar: <b>{total}</b>\n"
        f"🟢 Faol 24 soat: <b>{active_24h}</b>\n"
        f"🚫 Block qilganlar: <b>{blocked}</b>\n\n"
        f"⭐ Jami ball: <b>{total_points}</b>\n"
        f"🎮 Jami o‘yinlar: <b>{total_games}</b>\n"
        f"👥 Jami referral: <b>{total_referrals}</b>\n"
        f"💸 Kutilayotgan yechishlar: "
        f"<b>{pending_withdrawals}</b>",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 YANGILASH",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 ADMIN",
                    callback_data="admin"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# SPONSOR ADD
# =========================================================

async def sponsor_add(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.callback_query.answer()

    context.user_data["waiting_sponsor_add"] = True

    await update.callback_query.message.edit_text(
        "➕ <b>HOMIY KANAL QO‘SHISH</b>\n\n"
        "Kanal username'ini yuboring.\n\n"
        "Masalan:\n"
        "<code>@premyumstarstekin</code>\n\n"
        "⚠️ Bot kanalga administrator qilib "
        "qo‘shilgan bo‘lishi kerak.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ BEKOR",
                    callback_data="cancel"
                )
            ]
        ]),
        parse_mode="HTML"
    )


async def process_sponsor_add(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    channel = update.message.text.strip()

    if not channel.startswith("@"):
        await update.message.reply_text(
            "❌ Kanal username @ bilan boshlanishi kerak.\n\n"
            "Masalan: @premyumstarstekin"
        )
        return

    # =====================================================
    # BOTNING KANALDAGI HUQUQINI TEKSHIRISH
    # =====================================================

    try:
        bot_member = await context.bot.get_chat_member(
            chat_id=channel,
            user_id=context.bot.id
        )

        if bot_member.status not in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            await update.message.reply_text(
                "❌ <b>BOT KANALDA ADMIN EMAS!</b>\n\n"
                f"📢 Kanal: <b>{channel}</b>\n\n"
                "Avval botni shu kanalga "
                "administrator qilib qo‘ying.",
                parse_mode="HTML"
            )
            return

    except TelegramError as e:
        logger.error(
            "Sponsor validation error: %s",
            e
        )

        await update.message.reply_text(
            "❌ <b>KANALNI TEKSHIRIB BO‘LMADI.</b>\n\n"
            f"📢 {channel}\n\n"
            "Bot kanalga qo‘shilganini va "
            "administrator ekanini tekshiring.",
            parse_mode="HTML"
        )

        return

    # =====================================================
    # DATABASEGA QO‘SHISH
    # =====================================================

    con = connect()
    cur = con.cursor()

    try:
        cur.execute(
            "INSERT INTO sponsors(channel) VALUES (?)",
            (channel,)
        )

        con.commit()

        text = (
            "✅ <b>HOMIY QO‘SHILDI!</b>\n\n"
            f"📢 <b>{channel}</b>\n\n"
            "🔒 Endi bu kanal barcha foydalanuvchilar "
            "uchun majburiy obuna bo‘ladi.\n\n"
            "⭐ Referral ham faqat shu kanalga "
            "obuna bo‘lgandan keyin hisoblanadi."
        )

    except sqlite3.IntegrityError:
        text = (
            "⚠️ Bu kanal allaqachon "
            "homiy sifatida qo‘shilgan."
        )

    con.close()

    context.user_data.pop(
        "waiting_sponsor_add",
        None
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# SPONSOR LIST
# =========================================================

async def sponsor_list(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.callback_query.answer()

    sponsors = get_sponsors()

    if not sponsors:
        text = (
            "📋 <b>HOMIY KANALLAR</b>\n\n"
            "Hozircha kanal yo‘q."
        )
    else:
        text = (
            "📋 <b>HOMIY KANALLAR</b>\n\n"
        )

        for i, channel in enumerate(
            sponsors,
            1
        ):
            text += (
                f"{i}. 📢 {channel}\n"
            )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "➕ QO‘SHISH",
                    callback_data="sponsor_add"
                )
            ],
            [
                InlineKeyboardButton(
                    "➖ O‘CHIRISH",
                    callback_data="sponsor_remove"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 ADMIN",
                    callback_data="admin"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# SPONSOR REMOVE
# =========================================================

async def sponsor_remove(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.callback_query.answer()

    sponsors = get_sponsors()

    if not sponsors:
        await update.callback_query.message.edit_text(
            "📋 O‘chirish uchun homiy kanal yo‘q.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 ADMIN",
                        callback_data="admin"
                    )
                ]
            ])
        )
        return

    buttons = []

    for channel in sponsors:
        buttons.append([
            InlineKeyboardButton(
                f"❌ {channel}",
                callback_data=f"remove_sponsor:{channel}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 ADMIN",
            callback_data="admin"
        )
    ])

    await update.callback_query.message.edit_text(
        "➖ <b>HOMIY O‘CHIRISH</b>\n\n"
        "O‘chiriladigan kanalni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )


async def remove_sponsor_confirm(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.callback_query.answer()

    channel = update.callback_query.data.split(
        "remove_sponsor:",
        1
    )[1]

    con = connect()
    cur = con.cursor()

    cur.execute(
        "DELETE FROM sponsors WHERE channel=?",
        (channel,)
    )

    con.commit()
    con.close()

    await update.callback_query.message.edit_text(
        f"✅ <b>{channel}</b> o‘chirildi.\n\n"
        "🔓 Endi bu kanal majburiy obuna ro‘yxatida emas.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📋 HOMIYLAR",
                    callback_data="sponsor_list"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 ADMIN",
                    callback_data="admin"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# BROADCAST
# =========================================================

async def broadcast_start(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.callback_query.answer()

    context.user_data["broadcast"] = True

    await update.callback_query.message.edit_text(
        "📢 <b>XABAR YUBORISH</b>\n\n"
        "Endi yubormoqchi bo‘lgan xabaringizni jo‘nating.\n\n"
        "✅ Oddiy text\n"
        "🖼 Rasm\n"
        "🎥 Video\n"
        "🎞 GIF\n"
        "🎵 Audio\n"
        "📄 Fayl\n"
        "🎨 Sticker\n"
        "✨ Premium custom emoji\n"
        "va captionli media ham ishlaydi.\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML"
    )


async def send_broadcast(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.user_data.get("broadcast"):
        return

    source_message = update.message

    context.user_data.pop(
        "broadcast",
        None
    )

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT id
        FROM users
        WHERE blocked=0
    """)

    users = [
        row[0]
        for row in cur.fetchall()
    ]

    con.close()

    sent = 0
    failed = 0
    blocked = 0

    await update.message.reply_text(
        "📢 Xabar "
        f"<b>{len(users)}</b> ta userga yuborilmoqda...",
        parse_mode="HTML"
    )

    for user_id in users:
        try:
            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=source_message.chat_id,
                message_id=source_message.message_id
            )

            sent += 1

        except Forbidden:
            blocked += 1

            con = connect()
            cur = con.cursor()

            cur.execute("""
                UPDATE users
                SET blocked=1
                WHERE id=?
            """, (user_id,))

            con.commit()
            con.close()

        except RetryAfter as e:
            await asyncio.sleep(
                e.retry_after
            )

            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=source_message.chat_id,
                    message_id=source_message.message_id
                )

                sent += 1

            except Forbidden:
                blocked += 1

                con = connect()
                cur = con.cursor()

                cur.execute("""
                    UPDATE users
                    SET blocked=1
                    WHERE id=?
                """, (user_id,))

                con.commit()
                con.close()

            except Exception:
                failed += 1

        except TelegramError as e:
            logger.warning(
                "Broadcast failed for %s: %s",
                user_id,
                e
            )

            failed += 1

        except Exception as e:
            logger.error(
                "Broadcast unknown error %s: %s",
                user_id,
                e
            )

            failed += 1

        # Telegram flood limitiga tushmaslik uchun
        await asyncio.sleep(0.05)

    await update.message.reply_text(
        "✅ <b>YUBORISH TUGADI</b>\n\n"
        f"📨 Yuborildi: <b>{sent}</b>\n"
        f"❌ Xato: <b>{failed}</b>\n"
        f"🚫 Block qilgan: <b>{blocked}</b>\n\n"
        f"👥 Jami: <b>{len(users)}</b>",
        parse_mode="HTML"
    )


# =========================================================
# CANCEL
# =========================================================

async def cancel(update, context):
    if update.effective_user.id != ADMIN_ID:
        context.user_data.pop(
            "waiting_withdraw",
            None
        )
        return

    context.user_data.pop(
        "broadcast",
        None
    )

    context.user_data.pop(
        "waiting_sponsor_add",
        None
    )

    context.user_data.pop(
        "waiting_withdraw",
        None
    )

    await update.message.reply_text(
        "❌ Amal bekor qilindi."
    )


# =========================================================
# START
# =========================================================

async def start(update, context):
    user = update.effective_user

    referrer_id = None

    if context.args:
        arg = context.args[0]

        if arg.startswith("ref_"):
            try:
                referrer_id = int(
                    arg.replace(
                        "ref_",
                        "",
                        1
                    )
                )
            except ValueError:
                referrer_id = None

    is_new = add_user(
        user.id,
        user.username,
        referrer_id
    )

    subscribed = await check_subscription(
        user.id,
        context
    )

    if not subscribed and user.id != ADMIN_ID:
        text, markup = subscription_message()

        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML"
        )

        return

    # Yangi user homiylarga obuna bo'lganidan keyin
    # referral mukofoti beriladi.
    if is_new:
        reward_referral(user.id)

    await send_main_menu(
        update,
        context
    )


# =========================================================
# CHECK SUB BUTTON
# =========================================================

async def check_sub(update, context):
    user_id = update.effective_user.id

    if await check_subscription(
        user_id,
        context
    ):
        rewarded = reward_referral(user_id)

        await update.callback_query.answer(
            "✅ Obuna tasdiqlandi!",
            show_alert=False
        )

        if rewarded:
            extra_text = (
                f"\n\n🎁 Referral tasdiqlandi!\n"
                f"⭐ Do‘stingizga +{REFERRAL_REWARD} ⭐ berildi."
            )
        else:
            extra_text = ""

        await update.callback_query.message.edit_text(
            "✅ <b>OBUNA TASDIQLANDI!</b>\n\n"
            "🎉 Endi botdan foydalanishingiz mumkin."
            f"{extra_text}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 MENU",
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

    else:
        await update.callback_query.answer(
            "❌ Hali barcha homiy kanallarga obuna bo‘lmagansiz!",
            show_alert=True
        )

        text, markup = subscription_message()

        try:
            await update.callback_query.message.edit_text(
                text,
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode="HTML"
            )


# =========================================================
# CALLBACK ROUTER
# =========================================================

async def callback_router(update, context):
    query = update.callback_query
    data = query.data

    user_id = update.effective_user.id

    admin_callbacks = {
        "admin",
        "admin_stats",
        "broadcast",
        "sponsor_add",
        "sponsor_remove",
        "sponsor_list",
        "cancel",
    }

    if (
        user_id != ADMIN_ID
        and data not in admin_callbacks
        and not data.startswith(
            "remove_sponsor:"
        )
    ):
        if data == "check_sub":
            await check_sub(
                update,
                context
            )
            return

        if not await require_subscription(
            update,
            context
        ):
            return

    if data == "check_sub":
        await check_sub(
            update,
            context
        )

    elif data == "home":
        await query.answer()

        await send_main_menu(
            update,
            context,
            edit=True
        )

    elif data == "games":
        await games(
            update,
            context
        )

    elif data == "quiz":
        await quiz_start(
            update,
            context
        )

    elif data.startswith(
        "quiz_answer_"
    ):
        await quiz_answer(
            update,
            context
        )

    elif data == "riddle":
        await riddle_start(
            update,
            context
        )

    elif data.startswith(
        "riddle_answer_"
    ):
        await riddle_answer(
            update,
            context
        )

    elif data == "flag":
        await flag_start(
            update,
            context
        )

    elif data.startswith(
        "flag_answer_"
    ):
        await flag_answer(
            update,
            context
        )

    elif data == "quick":
        await quick_start(
            update,
            context
        )

    elif data.startswith("quick_"):
        await quick_answer(
            update,
            context
        )

    elif data == "number":
        await number_start(
            update,
            context
        )

    elif data.startswith("number_"):
        await number_answer(
            update,
            context
        )

    elif data == "island":
        await island_start(
            update,
            context
        )

    elif data.startswith("island_"):
        await island_answer(
            update,
            context
        )

    elif data == "dart":
        await dart(
            update,
            context
        )

    elif data == "bowling":
        await bowling(
            update,
            context
        )

    elif data == "dice":
        await dice(
            update,
            context
        )

    elif data == "math":
        await math_start(
            update,
            context
        )

    elif data.startswith("math_"):
        await math_answer(
            update,
            context
        )

    elif data == "daily":
        await daily(
            update,
            context
        )

    elif data == "balance":
        await balance(
            update,
            context
        )

    elif data == "ref":
        await referral(
            update,
            context
        )

    elif data == "buy_stars":
        await buy_stars(
            update,
            context
        )

    elif data == "withdraw":
        await withdraw(
            update,
            context
        )

    elif data == "profile":
        await profile(
            update,
            context
        )

    elif data == "top":
        await top(
            update,
            context
        )

    elif data == "user_count":
        await show_user_count(
            update,
            context
        )

    # =====================================================
    # ADMIN
    # =====================================================

    elif data == "admin":
        await admin_panel(
            update,
            context
        )

    elif data == "admin_stats":
        await admin_stats(
            update,
            context
        )

    elif data == "broadcast":
        await broadcast_start(
            update,
            context
        )

    elif data == "sponsor_add":
        await sponsor_add(
            update,
            context
        )

    elif data == "sponsor_remove":
        await sponsor_remove(
            update,
            context
        )

    elif data == "sponsor_list":
        await sponsor_list(
            update,
            context
        )

    elif data.startswith(
        "remove_sponsor:"
    ):
        await remove_sponsor_confirm(
            update,
            context
        )

    elif data == "cancel":
        context.user_data.clear()

        await query.answer(
            "❌ Bekor qilindi."
        )

        await query.message.edit_text(
            "❌ Amal bekor qilindi.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 MENU",
                        callback_data="home"
                    )
                ]
            ])
        )


# =========================================================
# MESSAGE ROUTER
# =========================================================

async def message_router(update, context):
    if not update.message:
        return

    user_id = update.effective_user.id

    # =====================================================
    # ADMIN BROADCAST
    # =====================================================

    if (
        user_id == ADMIN_ID
        and context.user_data.get(
            "broadcast"
        )
    ):
        await send_broadcast(
            update,
            context
        )
        return

    # =====================================================
    # ADMIN SPONSOR
    # =====================================================

    if (
        user_id == ADMIN_ID
        and context.user_data.get(
            "waiting_sponsor_add"
        )
    ):
        await process_sponsor_add(
            update,
            context
        )
        return

    # =====================================================
    # WITHDRAW
    # =====================================================

    if context.user_data.get(
        "waiting_withdraw"
    ):
        if user_id != ADMIN_ID:

            if not await require_subscription(
                update,
                context
            ):
                return

        await process_withdraw(
            update,
            context
        )

        return


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    logger.error(
        "Exception while handling update:",
        exc_info=context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi! "
            "GitHub Secrets ichiga BOT_TOKEN qo‘shing."
        )

    init_db()

    application = (
        Application.builder()
        .token(TOKEN)
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
            "cancel",
            cancel
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            message_router
        )
    )

    application.add_error_handler(
        error_handler
    )

    print(
        "🔥 Zerikdim Bot ishga tushdi!"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
