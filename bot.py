import os
import sqlite3
import logging
import random
import asyncio
import subprocess
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "zerikdim.db"

# ==========================================================
# HOMIY KANALLAR
# ==========================================================

SPONSOR_CHANNELS = [
    "@FORUMUZ_Z",
    "@premyumstarstekin",
]

SPONSOR_URLS = [
    "https://t.me/FORUMUZ_Z",
    "https://t.me/premyumstarstekin",
]

BUY_STARS_URL = "https://t.me/premyumstarstekin/933"

REFERRAL_REWARD = 9.0
GAME_REWARD = 0.02
TASK_REWARD = 5.0

MIN_WITHDRAW = 200.0
MIN_REFERRALS = 20
GAME_COOLDOWN = 30

PAGE_SIZE = 10

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

log = logging.getLogger("zerikdim")

# ==========================================================
# O'YINLAR
# ==========================================================

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

# QIYINROQ SAVOLLAR
QUIZ = [
    (
        "O‘zbekiston Konstitutsiyasi qaysi yilda qabul qilingan?",
        ["1991", "1992", "1993", "1994"],
        1
    ),
    (
        "1 dan 20 gacha bo‘lgan sonlar yig‘indisi nechaga teng?",
        ["190", "200", "210", "220"],
        2
    ),
    (
        "Yer Quyosh atrofini taxminan necha kunda aylanib chiqadi?",
        ["180", "265", "365", "400"],
        2
    ),
    (
        "Agar 3 ta qalam 15 000 so‘m bo‘lsa, 7 ta qalam qancha?",
        ["25 000", "30 000", "35 000", "40 000"],
        2
    ),
    (
        "Eng katta okean qaysi?",
        ["Atlantika", "Hind", "Tinch", "Shimoliy Muz"],
        2
    ),
    (
        "2^5 nechaga teng?",
        ["16", "24", "32", "64"],
        2
    ),
    (
        "1 kilometr necha metr?",
        ["100", "500", "1000", "1500"],
        2
    ),
    (
        "12 × 8 − 17 nechaga teng?",
        ["69", "79", "89", "97"],
        1
    ),
]

LOGIC_QUESTIONS = [
    (
        "Ketma-ketlikni davom ettir: 2, 6, 12, 20, 30, ?",
        ["36", "40", "42", "44"],
        2
    ),
    (
        "5, 10, 20, 40, ?",
        ["60", "70", "80", "90"],
        2
    ),
    (
        "1, 4, 9, 16, 25, ?",
        ["30", "32", "36", "49"],
        2
    ),
    (
        "100, 90, 81, 73, ?",
        ["64", "66", "67", "68"],
        1
    ),
    (
        "3, 9, 27, 81, ?",
        ["162", "243", "324", "729"],
        1
    ),
]

WORDS = [
    ("HSTOAN", "TOSHAN"),
    ("KTOBII", "KITOBI"),
    ("MRAKTA", "MARKET"),
    ("LQAMA", "QALAM"),
    ("GOLBA", "BOGLA"),
    ("TNAEK", "KENTA"),
    ("DORS", "DORS"),
]

COLORS = [
    ("🔴 QIZIL", "qizil"),
    ("🔵 KO‘K", "ko‘k"),
    ("🟢 YASHIL", "yashil"),
    ("🟡 SARIQ", "sariq"),
]

KNOWLEDGE = [
    (
        "Dunyodagi eng katta qit’a qaysi?",
        ["Osiyo", "Afrika", "Yevropa", "Avstraliya"],
        0
    ),
    (
        "Suvning kimyoviy formulasi?",
        ["CO2", "H2O", "O2", "NaCl"],
        1
    ),
    (
        "Python dasturlash tilining belgisi ko‘proq nima bilan bog‘liq?",
        ["Ilon", "Qush", "Sher", "Baliq"],
        0
    ),
    (
        "Bir sutkada nechta soat bor?",
        ["12", "18", "24", "48"],
        2
    ),
]

# ==========================================================
# YORDAMCHI
# ==========================================================

def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    return sqlite3.connect(DB_FILE, timeout=30)


# ==========================================================
# GITHUBGA BAZANI SAQLASH
# ==========================================================

save_lock = asyncio.Lock()


async def save_database():
    async with save_lock:

        def _save():
            try:
                subprocess.run(
                    ["git", "config", "user.name", "Zerikdim Bot"],
                    check=False
                )

                subprocess.run(
                    [
                        "git",
                        "config",
                        "user.email",
                        "zerikdim-bot@users.noreply.github.com"
                    ],
                    check=False
                )

                subprocess.run(
                    ["git", "add", DB_FILE],
                    check=False
                )

                result = subprocess.run(
                    ["git", "diff", "--cached", "--quiet"],
                    capture_output=True
                )

                if result.returncode == 0:
                    return

                subprocess.run(
                    [
                        "git",
                        "commit",
                        "-m",
                        "Update Zerikdim database"
                    ],
                    check=False
                )

                subprocess.run(
                    ["git", "push"],
                    check=False
                )

                log.info("Database GitHubga saqlandi.")

            except Exception as e:
                log.error("Database save error: %s", e)

        await asyncio.to_thread(_save)


async def periodic_database_backup():
    while True:
        try:
            await asyncio.sleep(60)
            await save_database()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Backup error: %s", e)


# ==========================================================
# DATABASE
# ==========================================================

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_claims(
        user_id INTEGER,
        task_id INTEGER,
        created_at TEXT,
        PRIMARY KEY(user_id, task_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_stats(
        id INTEGER PRIMARY KEY CHECK(id=1),
        started_at TEXT,
        total_users INTEGER DEFAULT 0
    )
    """)

    cur.execute(
        "SELECT COUNT(*) FROM users"
    )
    current_users = cur.fetchone()[0]

    cur.execute(
        "SELECT id, total_users FROM bot_stats WHERE id=1"
    )
    stats = cur.fetchone()

    if not stats:
        cur.execute("""
        INSERT INTO bot_stats
        (id, started_at, total_users)
        VALUES (1, ?, ?)
        """, (now(), current_users))
    elif current_users > stats[1]:
        cur.execute("""
        UPDATE bot_stats
        SET total_users=?
        WHERE id=1
        """, (current_users,))

    con.commit()
    con.close()


# ==========================================================
# USER
# ==========================================================

def add_user_sync(user_id, username=None, ref=None):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    )

    exists = cur.fetchone()

    if not exists:

        valid_ref = (
            ref
            if ref and ref != user_id
            else None
        )

        cur.execute("""
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
            valid_ref,
            now()
        ))

        cur.execute("""
        UPDATE bot_stats
        SET total_users=total_users+1
        WHERE id=1
        """)

        if valid_ref:

            cur.execute(
                "SELECT id FROM users WHERE id=?",
                (valid_ref,)
            )

            ref_exists = cur.fetchone()

            if ref_exists:

                cur.execute("""
                UPDATE users
                SET points=points+?,
                    referrals=referrals+1
                WHERE id=?
                """, (
                    REFERRAL_REWARD,
                    valid_ref
                ))

                cur.execute("""
                UPDATE users
                SET referral_rewarded=1
                WHERE id=?
                """, (user_id,))

    else:

        cur.execute("""
        UPDATE users
        SET username=?,
            last_seen=?,
            blocked=0
        WHERE id=?
        """, (
            username,
            now(),
            user_id
        ))

    con.commit()
    con.close()


async def add_user(user_id, username=None, ref=None):
    await asyncio.to_thread(
        add_user_sync,
        user_id,
        username,
        ref
    )


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


def change_points_sync(user_id, amount):
    con = db()
    cur = con.cursor()

    cur.execute("""
    UPDATE users
    SET points=MAX(0, points+?)
    WHERE id=?
    """, (
        amount,
        user_id
    ))

    con.commit()
    con.close()


async def change_points(user_id, amount):
    await asyncio.to_thread(
        change_points_sync,
        user_id,
        amount
    )


def game_result_sync(user_id, won):
    con = db()
    cur = con.cursor()

    cur.execute("""
    UPDATE users
    SET games=games+1,
        wins=wins+?
    WHERE id=?
    """, (
        1 if won else 0,
        user_id
    ))

    con.commit()
    con.close()


async def game_result(user_id, won):
    await asyncio.to_thread(
        game_result_sync,
        user_id,
        won
    )


# ==========================================================
# MAJBURIY OBUNA
# ==========================================================

async def subscribed(bot, user_id):

    for channel in SPONSOR_CHANNELS:

        try:
            member = await bot.get_chat_member(
                channel,
                user_id
            )

            if member.status not in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER
            ):
                return False

        except TelegramError as e:
            log.error(
                "Obuna tekshirish xatosi %s: %s",
                channel,
                e
            )
            return False

    return True


async def require_subscription(update, context):

    user_id = update.effective_user.id

    # Admin majburiy obunadan o'tadi
    if user_id == ADMIN_ID:
        return True

    if await subscribed(
        context.bot,
        user_id
    ):
        return True

    keyboard = [
        [
            InlineKeyboardButton(
                "📢 FORUMUZ_Z",
                url=SPONSOR_URLS[0]
            )
        ],
        [
            InlineKeyboardButton(
                "📢 Premium Stars",
                url=SPONSOR_URLS[1]
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
        "🔒 <b>Botdan foydalanish uchun 2 ta kanalga "
        "majburiy obuna bo‘ling.</b>\n\n"
        "1️⃣ FORUMUZ_Z\n"
        "2️⃣ Premium Stars\n\n"
        "Obuna bo‘lgach, «Tekshirish» tugmasini bosing."
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    return False


# ==========================================================
# ASOSIY MENYU
# ==========================================================

def main_menu(is_admin=False):

    keyboard = [
        [
            InlineKeyboardButton(
                "⭐ STARS OLISH",
                callback_data="buy"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 STARS ISHLASH",
                callback_data="games"
            )
        ],
        [
            InlineKeyboardButton(
                "🎮 O‘YINLAR",
                callback_data="other_games"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 BALANS",
                callback_data="balance"
            ),
            InlineKeyboardButton(
                "🎁 TOPSHIRIQLAR",
                callback_data="tasks"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="ref"
            ),
            InlineKeyboardButton(
                "💸 YECHIB OLISH",
                callback_data="withdraw"
            )
        ],
        [
            InlineKeyboardButton(
                "🏆 REYTING",
                callback_data="rating"
            ),
            InlineKeyboardButton(
                "👤 PROFIL",
                callback_data="profile"
            )
        ]
    ]

    if is_admin:
        keyboard.append([
            InlineKeyboardButton(
                "⚙️ ADMIN PANEL",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(keyboard)


# ==========================================================
# START
# ==========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    ref = None

    if context.args:
        try:
            ref = int(context.args[0])
        except ValueError:
            ref = None

    await add_user(
        user.id,
        user.username,
        ref
    )

    if not await require_subscription(
        update,
        context
    ):
        return

    admin = user.id == ADMIN_ID

    await update.message.reply_text(
        "👋 <b>Zerikdim Botga xush kelibsiz!</b>\n\n"
        "⭐ Stars ishlang, topshiriqlar bajaring va "
        "do‘stlaringizni taklif qiling.\n\n"
        "👇 Kerakli bo‘limni tanlang:",
        parse_mode="HTML",
        reply_markup=main_menu(admin)
    )


# ==========================================================
# O'YINLAR MENYUSI
# ==========================================================

def games_menu():
    keyboard = []

    for i in range(0, len(GAMES), 2):
        row = []

        name1, code1 = GAMES[i]
        row.append(
            InlineKeyboardButton(
                name1,
                callback_data=f"game_{code1}"
            )
        )

        if i + 1 < len(GAMES):
            name2, code2 = GAMES[i + 1]
            row.append(
                InlineKeyboardButton(
                    name2,
                    callback_data=f"game_{code2}"
                )
            )

        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Bosh menyu",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(keyboard)


# ==========================================================
# GAME COOLDOWN
# ==========================================================

def can_play(context, user_id):

    key = f"game_last_{user_id}"

    last = context.user_data.get(key)

    if last is None:
        return True, 0

    elapsed = asyncio.get_event_loop().time() - last

    if elapsed < GAME_COOLDOWN:
        return False, int(GAME_COOLDOWN - elapsed)

    return True, 0


def mark_game(context, user_id):
    context.user_data[
        f"game_last_{user_id}"
    ] = asyncio.get_event_loop().time()


# ==========================================================
# GAME START
# ==========================================================

async def start_game(update, context, game):

    user_id = update.effective_user.id

    allowed, wait = can_play(
        context,
        user_id
    )

    if not allowed:
        await update.callback_query.message.reply_text(
            f"⏳ Keyingi o‘yinni boshlash uchun "
            f"<b>{wait} soniya</b> kuting.",
            parse_mode="HTML"
        )
        return

    mark_game(context, user_id)

    q = update.callback_query

    # ------------------------------------------------------
    # QUIZ
    # ------------------------------------------------------

    if game == "quiz":

        question, answers, correct = random.choice(QUIZ)

        context.user_data["game"] = {
            "type": "quiz",
            "correct": correct,
            "reward": 1.0
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    answer,
                    callback_data=f"answer_{i}"
                )
            ]
            for i, answer in enumerate(answers)
        ]

        await q.message.reply_text(
            "🧠 <b>Qiyin savol</b>\n\n"
            f"{question}\n\n"
            "To‘g‘ri javobni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------------------------------------------
    # NUMBER
    # ------------------------------------------------------

    if game == "number":

        number = random.randint(1, 100)

        context.user_data["game"] = {
            "type": "number",
            "number": number,
            "tries": 0,
            "reward": 1.5
        }

        await q.message.reply_text(
            "🔢 <b>Sonni toping</b>\n\n"
            "Men 1 dan 100 gacha bitta son o‘yladim.\n"
            "Uni topish uchun son yuboring.\n\n"
            "⚠️ 7 ta urinish bor.",
            parse_mode="HTML"
        )
        return

    # ------------------------------------------------------
    # CHOICE
    # ------------------------------------------------------

    if game == "choice":

        options = [
            "A", "B", "C", "D", "E"
        ]

        correct = random.choice(options)

        context.user_data["game"] = {
            "type": "choice",
            "correct": correct,
            "reward": 1.0
        }

        random.shuffle(options)

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"choice_{x}"
                )
                for x in options[:3]
            ],
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"choice_{x}"
                )
                for x in options[3:]
            ]
        ]

        await q.message.reply_text(
            "⚡ <b>Tez tanla</b>\n\n"
            "To‘g‘ri variantni toping.\n"
            "5 ta variantdan faqat bittasi to‘g‘ri.\n\n"
            f"🔐 Maxfiy javob: {correct}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Maxfiy javobni xabarda ko‘rsatmaslik uchun qayta
        await q.message.delete()
        await q.message.chat.send_message(
            "⚡ <b>Tez tanla</b>\n\n"
            "5 ta variantdan to‘g‘ri javobni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------------------------------------------
    # LOGIC
    # ------------------------------------------------------

    if game == "logic":

        question, answers, correct = random.choice(
            LOGIC_QUESTIONS
        )

        context.user_data["game"] = {
            "type": "logic",
            "correct": correct,
            "reward": 1.5
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"logic_{i}"
                )
            ]
            for i, x in enumerate(answers)
        ]

        await q.message.reply_text(
            "🧩 <b>Mantiqiy masala</b>\n\n"
            f"{question}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------------------------------------------
    # TARGET
    # ------------------------------------------------------

    if game == "target":

        target = random.randint(1, 9)

        context.user_data["game"] = {
            "type": "target",
            "correct": target,
            "reward": 1.0
        }

        keyboard = []

        nums = list(range(1, 10))

        for i in range(0, 9, 3):
            keyboard.append([
                InlineKeyboardButton(
                    str(x),
                    callback_data=f"target_{x}"
                )
                for x in nums[i:i + 3]
            ])

        await q.message.reply_text(
            "🎯 <b>Nishon</b>\n\n"
            "Quyidagi raqamlar ichidan yashirin "
            "nishonni toping.\n\n"
            "💡 Ishora: nishon juft yoki toq bo‘lishi mumkin.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------------------------------------------
    # WORD
    # ------------------------------------------------------

    if game == "word":

        scrambled, correct_word = random.choice(WORDS)

        # oddiy so'zlar uchun qayta aralashtirish
        letters = list(correct_word)
        random.shuffle(letters)

        scrambled = "".join(letters)

        context.user_data["game"] = {
            "type": "word",
            "correct_word": correct_word.lower(),
            "reward": 1.3
        }

        await q.message.reply_text(
            "🔤 <b>So‘zni toping</b>\n\n"
            f"Aralashtirilgan harflar:\n"
            f"🔀 <code>{scrambled}</code>\n\n"
            "So‘zni yozib yuboring.",
            parse_mode="HTML"
        )
        return

    # ------------------------------------------------------
    # MATH
    # ------------------------------------------------------

    if game == "math":

        a = random.randint(15, 80)
        b = random.randint(5, 40)
        c = random.randint(2, 9)

        operations = [
            ("+", a + b * c),
            ("-", a * c - b),
            ("×", a * b + c),
        ]

        operation, answer = random.choice(operations)

        if operation == "+":
            text = f"{a} + {b} × {c}"
        elif operation == "-":
            text = f"{a} × {c} − {b}"
        else:
            text = f"{a} × {b} + {c}"

        context.user_data["game"] = {
            "type": "math",
            "correct": answer,
            "reward": 1.7
        }

        await q.message.reply_text(
            "🧮 <b>Hisoblang</b>\n\n"
            f"❓ {text} = ?\n\n"
            "⚠️ Amallar tartibiga e’tibor bering.",
            parse_mode="HTML"
        )
        return

    # ------------------------------------------------------
    # ATTENTION
    # ------------------------------------------------------

    if game == "attention":

        nums = list(range(1, 10))
        random.shuffle(nums)

        special = random.choice(nums)

        context.user_data["game"] = {
            "type": "attention",
            "correct": special,
            "reward": 1.2
        }

        keyboard = []

        for i in range(0, 9, 3):
            keyboard.append([
                InlineKeyboardButton(
                    str(x),
                    callback_data=f"attention_{x}"
                )
                for x in nums[i:i + 3]
            ])

        await q.message.reply_text(
            "👀 <b>Diqqat!</b>\n\n"
            "Quyidagi raqamlardan tasodifiy "
            "bittasi yashirin nishon.\n"
            "Uni toping.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------------------------------------------
    # COLOR
    # ------------------------------------------------------

    if game == "color":

        correct_text, correct_value = random.choice(COLORS)

        options = [x[1] for x in COLORS]
        random.shuffle(options)

        context.user_data["game"] = {
            "type": "color",
            "correct": correct_value,
            "reward": 1.2
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"color_{x}"
                )
                for x in options[:2]
            ],
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"color_{x}"
                )
                for x in options[2:]
            ]
        ]

        await q.message.reply_text(
            "🎨 <b>Rangni toping</b>\n\n"
            f"Rang belgisi: {correct_text}\n\n"
            "Mos nomni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------------------------------------------
    # CODE
    # ------------------------------------------------------

    if game == "code":

        digits = random.sample(
            range(0, 10),
            4
        )

        code = "".join(
            str(x) for x in digits
        )

        context.user_data["game"] = {
            "type": "code",
            "correct": code,
            "reward": 2.0
        }

        await q.message.reply_text(
            "🔐 <b>Kodni toping</b>\n\n"
            "4 xonali kod yashirildi.\n"
            "Koddagi raqamlarning yig‘indisi "
            f"<b>{sum(digits)}</b> ga teng.\n\n"
            "Kodda raqamlar takrorlanmaydi.\n"
            "Kodni yozib yuboring.",
            parse_mode="HTML"
        )
        return

    # ------------------------------------------------------
    # KNOWLEDGE
    # ------------------------------------------------------

    if game == "knowledge":

        question, answers, correct = random.choice(
            KNOWLEDGE
        )

        context.user_data["game"] = {
            "type": "knowledge",
            "correct": correct,
            "reward": 1.3
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"knowledge_{i}"
                )
            ]
            for i, x in enumerate(answers)
        ]

        await q.message.reply_text(
            "📚 <b>Bilim savoli</b>\n\n"
            f"{question}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------------------------------------------
    # SPEED
    # ------------------------------------------------------

    if game == "speed":

        a = random.randint(10, 30)
        b = random.randint(5, 20)

        answer = a + b

        context.user_data["game"] = {
            "type": "speed",
            "correct": answer,
            "reward": 2.0
        }

        await q.message.reply_text(
            "⏱ <b>TEZLIK TESTI</b>\n\n"
            f"⚡ {a} + {b} = ?\n\n"
            "Javobni imkon qadar tez yuboring!",
            parse_mode="HTML"
        )
        return


# ==========================================================
# GAME ANSWERS
# ==========================================================

async def process_game_answer(update, context):

    user_id = update.effective_user.id
    game = context.user_data.get("game")

    if not game:
        return

    answer_text = update.message.text.strip()

    game_type = game.get("type")
    correct = False

    # NUMBER
    if game_type == "number":

        try:
            value = int(answer_text)
        except ValueError:
            await update.message.reply_text(
                "❌ Faqat raqam yuboring."
            )
            return

        game["tries"] += 1

        if value == game["number"]:
            correct = True

        elif game["tries"] >= 7:
            await game_result(user_id, False)
            context.user_data.pop("game", None)

            await update.message.reply_text(
                f"❌ Yutqazdingiz.\n\n"
                f"🔐 To‘g‘ri son: {game['number']}"
            )
            return

        else:
            if value < game["number"]:
                hint = "⬆️ Kattaroq son."
            else:
                hint = "⬇️ Kichikroq son."

            await update.message.reply_text(
                f"{hint}\n"
                f"🎯 Qolgan urinish: {7 - game['tries']}"
            )
            return

    # WORD
    elif game_type == "word":

        if answer_text.lower() == game["correct_word"]:
            correct = True

    # MATH / CODE / SPEED
    elif game_type in (
        "math",
        "code",
        "speed"
    ):

        if answer_text == str(game["correct"]):
            correct = True

    if correct:

        reward = float(
            game.get("reward", GAME_REWARD)
        )

        await change_points(
            user_id,
            reward
        )

        await game_result(
            user_id,
            True
        )

        context.user_data.pop(
            "game",
            None
        )

        await update.message.reply_text(
            "🎉 <b>TO‘G‘RI!</b>\n\n"
            f"⭐ +{reward:g} Stars\n\n"
            "🔥 Juda yaxshi!",
            parse_mode="HTML"
        )

    else:

        await game_result(
            user_id,
            False
        )

        context.user_data.pop(
            "game",
            None
        )

        await update.message.reply_text(
            "❌ <b>Noto‘g‘ri javob.</b>\n\n"
            "Keyingi o‘yinda yana urinib ko‘ring.",
            parse_mode="HTML"
        )


# ==========================================================
# CALLBACK
# ==========================================================

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    user = q.from_user
    data = q.data

    await add_user(
        user.id,
        user.username
    )

    # Obunani tekshirish tugmasi
    if data == "check_sub":

        if await subscribed(
            context.bot,
            user.id
        ):

            await q.message.reply_text(
                "✅ <b>Obuna tasdiqlandi!</b>\n\n"
                "Endi botdan foydalanishingiz mumkin.",
                parse_mode="HTML",
                reply_markup=main_menu(
                    user.id == ADMIN_ID
                )
            )

        else:

            await q.message.reply_text(
                "❌ Hali ikkala kanalga ham "
                "obuna bo‘lmagansiz.\n\n"
                "Ikkalasiga obuna bo‘lib, yana tekshiring."
            )

        return

    # Admin obunani bypass qiladi
    if user.id != ADMIN_ID:

        if not await subscribed(
            context.bot,
            user.id
        ):

            await require_subscription(
                update,
                context
            )
            return

    # HOME
    if data == "home":

        await q.message.reply_text(
            "🏠 <b>Asosiy menyu</b>",
            parse_mode="HTML",
            reply_markup=main_menu(
                user.id == ADMIN_ID
            )
        )
        return

    # BUY
    if data == "buy":

        keyboard = [
            [
                InlineKeyboardButton(
                    "⭐ 50 Stars",
                    callback_data="buy_50"
                ),
                InlineKeyboardButton(
                    "⭐ 100 Stars",
                    callback_data="buy_100"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 200 Stars",
                    callback_data="buy_200"
                ),
                InlineKeyboardButton(
                    "⭐ 500 Stars",
                    callback_data="buy_500"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 1000 Stars",
                    callback_data="buy_1000"
                ),
                InlineKeyboardButton(
                    "⭐ 2000 Stars",
                    callback_data="buy_2000"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ 5000 Stars",
                    callback_data="buy_5000"
                )
            ],
            [
                InlineKeyboardButton(
                    "💳 Sotib olish",
                    url=BUY_STARS_URL
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
            "Kerakli Stars paketini tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # BUY PACKAGE
    if data.startswith("buy_"):

        amount = data.replace(
            "buy_",
            ""
        )

        await q.message.reply_text(
            f"⭐ <b>{amount} Stars</b>\n\n"
            "Sotib olish uchun quyidagi tugmadan "
            "foydalaning:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💳 Sotib olish",
                        url=BUY_STARS_URL
                    )
                ]
            ])
        )
        return

    # BALANCE
    if data == "balance":

        row = get_user(user.id)

        points = row[2] if row else 0
        referrals = row[5] if row else 0

        await q.message.reply_text(
            "💰 <b>BALANS</b>\n\n"
            f"⭐ Stars: <b>{points:.2f}</b>\n"
            f"👥 Referallar: <b>{referrals}</b>\n\n"
            "Stars yig‘ish uchun «🎯 STARS ISHLASH» "
            "bo‘limiga kiring.",
            parse_mode="HTML"
        )
        return

    # PROFILE
    if data == "profile":

        row = get_user(user.id)

        if not row:
            return

        await q.message.reply_text(
            "👤 <b>PROFIL</b>\n\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"👤 Username: @{user.username or 'yo‘q'}\n"
            f"⭐ Stars: <b>{row[2]:.2f}</b>\n"
            f"🎮 O‘yinlar: <b>{row[3]}</b>\n"
            f"🏆 G‘alabalar: <b>{row[4]}</b>\n"
            f"👥 Referallar: <b>{row[5]}</b>",
            parse_mode="HTML"
        )
        return

    # REFERRAL
    if data == "ref":

        bot_info = await context.bot.get_me()

        link = (
            f"https://t.me/{bot_info.username}"
            f"?start={user.id}"
        )

        row = get_user(user.id)
        refs = row[5] if row else 0

        await q.message.reply_text(
            "👥 <b>REFERAL TIZIMI</b>\n\n"
            f"Har bir taklif uchun: ⭐ <b>{REFERRAL_REWARD:g}</b>\n"
            f"Sizning referallaringiz: <b>{refs}</b>\n\n"
            "🔗 Sizning havolangiz:\n"
            f"<code>{link}</code>\n\n"
            "Havolani do‘stlaringizga yuboring.",
            parse_mode="HTML"
        )
        return

    # TASKS
    if data == "tasks":

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT id, text, reward, url
        FROM tasks
        ORDER BY id DESC
        """)

        tasks = cur.fetchall()

        con.close()

        if not tasks:

            await q.message.reply_text(
                "🎁 Hozircha topshiriqlar yo‘q."
            )
            return

        for task_id, text, reward, url in tasks:

            keyboard = [
                [
                    InlineKeyboardButton(
                        "📲 Topshiriq",
                        url=url
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"✅ Bajardim (+{reward:g} ⭐)",
                        callback_data=f"taskdone_{task_id}"
                    )
                ]
            ]

            await q.message.reply_text(
                f"🎁 <b>Topshiriq #{task_id}</b>\n\n"
                f"{text}\n\n"
                f"💰 Mukofot: ⭐ <b>{reward:g}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return

    # TASK DONE
    if data.startswith("taskdone_"):

        try:
            task_id = int(
                data.replace(
                    "taskdone_",
                    ""
                )
            )
        except ValueError:
            return

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT reward
        FROM tasks
        WHERE id=?
        """, (task_id,))

        task = cur.fetchone()

        if not task:
            con.close()
            await q.message.reply_text(
                "❌ Topshiriq topilmadi."
            )
            return

        reward = float(task[0])

        cur.execute("""
        SELECT 1
        FROM task_claims
        WHERE user_id=? AND task_id=?
        """, (
            user.id,
            task_id
        ))

        already = cur.fetchone()

        if already:
            con.close()
            await q.message.reply_text(
                "⚠️ Bu topshiriq uchun Stars olgansiz."
            )
            return

        cur.execute("""
        INSERT INTO task_claims
        (user_id, task_id, created_at)
        VALUES (?, ?, ?)
        """, (
            user.id,
            task_id,
            now()
        ))

        cur.execute("""
        UPDATE users
        SET points=points+?
        WHERE id=?
        """, (
            reward,
            user.id
        ))

        con.commit()
        con.close()

        await q.message.reply_text(
            f"🎉 Topshiriq qabul qilindi!\n\n"
            f"⭐ +{reward:g} Stars qo‘shildi.",
            parse_mode="HTML"
        )

        await save_database()
        return

    # RATING
    if data == "rating":

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT username, points
        FROM users
        ORDER BY points DESC
        LIMIT 10
        """)

        rows = cur.fetchall()

        con.close()

        text = "🏆 <b>TOP 10 REYTING</b>\n\n"

        if not rows:
            text += "Hali foydalanuvchilar yo‘q."
        else:
            for i, (username, points) in enumerate(
                rows,
                start=1
            ):
                name = (
                    f"@{username}"
                    if username
                    else "Foydalanuvchi"
                )

                text += (
                    f"{i}. {name} — "
                    f"⭐ {points:.2f}\n"
                )

        await q.message.reply_text(
            text,
            parse_mode="HTML"
        )
        return

    # WITHDRAW
    if data == "withdraw":

        row = get_user(user.id)

        if not row:
            return

        points = float(row[2])
        referrals = int(row[5])

        if points < MIN_WITHDRAW:

            await q.message.reply_text(
                f"💸 Yechish uchun kamida "
                f"⭐ <b>{MIN_WITHDRAW:g}</b> kerak.\n\n"
                f"Sizda: ⭐ <b>{points:.2f}</b>",
                parse_mode="HTML"
            )
            return

        if referrals < MIN_REFERRALS:

            await q.message.reply_text(
                f"👥 Yechish uchun kamida "
                f"<b>{MIN_REFERRALS}</b> ta referral kerak.\n\n"
                f"Sizda: <b>{referrals}</b>",
                parse_mode="HTML"
            )
            return

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT id
        FROM withdrawals
        WHERE user_id=?
        AND status='pending'
        """, (user.id,))

        pending = cur.fetchone()

        con.close()

        if pending:

            await q.message.reply_text(
                "⏳ Sizda allaqachon kutayotgan "
                "yechish so‘rovi bor."
            )
            return

        con = db()
        cur = con.cursor()

        # 200 Stars yechiladi
        cur.execute("""
        UPDATE users
        SET points=points-?
        WHERE id=?
        AND points>=?
        """, (
            MIN_WITHDRAW,
            user.id,
            MIN_WITHDRAW
        ))

        if cur.rowcount == 0:
            con.close()

            await q.message.reply_text(
                "❌ Balans yetarli emas."
            )
            return

        cur.execute("""
        INSERT INTO withdrawals
        (user_id, amount, status, created_at)
        VALUES (?, ?, 'pending', ?)
        """, (
            user.id,
            MIN_WITHDRAW,
            now()
        ))

        withdrawal_id = cur.lastrowid

        con.commit()
        con.close()

        await q.message.reply_text(
            "✅ <b>Yechish so‘rovingiz muvaffaqiyatli qabul qilindi!</b>\n\n"
            "💰 Miqdor: ⭐ <b>200</b>\n"
            "⏳ 24 soat ichida ko‘rib chiqiladi.",
            parse_mode="HTML"
        )

        if ADMIN_ID:

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Tasdiqlash",
                        callback_data=f"approve_{withdrawal_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ Rad etish",
                        callback_data=f"reject_{withdrawal_id}"
                    )
                ]
            ])

            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    "💸 <b>Yangi YECHISH SO‘ROVI</b>\n\n"
                    f"🆔 User ID: <code>{user.id}</code>\n"
                    f"👤 @{user.username or 'yo‘q'}\n"
                    f"⭐ Miqdor: <b>{MIN_WITHDRAW:g}</b>\n"
                    f"📄 So‘rov: <b>#{withdrawal_id}</b>",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except TelegramError as e:
                log.error(
                    "Admin notification error: %s",
                    e
                )

        await save_database()
        return

    # APPROVE
    if data.startswith("approve_"):

        if user.id != ADMIN_ID:
            return

        withdrawal_id = int(
            data.replace(
                "approve_",
                ""
            )
        )

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT user_id, amount, status
        FROM withdrawals
        WHERE id=?
        """, (withdrawal_id,))

        withdrawal = cur.fetchone()

        if not withdrawal:
            con.close()

            await q.message.reply_text(
                "❌ So‘rov topilmadi."
            )
            return

        target_user, amount, status = withdrawal

        if status != "pending":
            con.close()

            await q.message.reply_text(
                "⚠️ Bu so‘rov allaqachon ko‘rib chiqilgan."
            )
            return

        cur.execute("""
        UPDATE withdrawals
        SET status='approved'
        WHERE id=?
        """, (withdrawal_id,))

        con.commit()
        con.close()

        await q.message.reply_text(
            f"✅ So‘rov #{withdrawal_id} tasdiqlandi."
        )

        try:
            await context.bot.send_message(
                target_user,
                "🎉 <b>Yechish so‘rovingiz tasdiqlandi!</b>\n\n"
                f"⭐ Miqdor: <b>{amount:g}</b>\n\n"
                "Admin tomonidan tasdiqlandi.",
                parse_mode="HTML"
            )
        except TelegramError:
            pass

        await save_database()
        return

    # REJECT
    if data.startswith("reject_"):

        if user.id != ADMIN_ID:
            return

        withdrawal_id = int(
            data.replace(
                "reject_",
                ""
            )
        )

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT user_id, amount, status
        FROM withdrawals
        WHERE id=?
        """, (withdrawal_id,))

        withdrawal = cur.fetchone()

        if not withdrawal:
            con.close()

            await q.message.reply_text(
                "❌ So‘rov topilmadi."
            )
            return

        target_user, amount, status = withdrawal

        if status != "pending":
            con.close()

            await q.message.reply_text(
                "⚠️ Bu so‘rov allaqachon ko‘rib chiqilgan."
            )
            return

        cur.execute("""
        UPDATE withdrawals
        SET status='rejected'
        WHERE id=?
        """, (withdrawal_id,))

        cur.execute("""
        UPDATE users
        SET points=points+?
        WHERE id=?
        """, (
            amount,
            target_user
        ))

        con.commit()
        con.close()

        await q.message.reply_text(
            f"❌ So‘rov #{withdrawal_id} rad etildi.\n"
            f"⭐ {amount:g} Stars balansga qaytarildi."
        )

        try:
            await context.bot.send_message(
                target_user,
                "❌ <b>Yechish so‘rovingiz rad etildi.</b>\n\n"
                f"⭐ {amount:g} Stars balansingizga qaytarildi.",
                parse_mode="HTML"
            )
        except TelegramError:
            pass

        await save_database()
        return

    # GAMES
    if data == "games":

        await q.message.reply_text(
            "🎯 <b>STARS ISHLASH</b>\n\n"
            "⚠️ O‘yinlar avvalgidan qiyinroq.\n"
            "To‘g‘ri javob bersangiz ⭐ Stars olasiz.\n\n"
            "⏳ Har bir o‘yin orasida cooldown bor.",
            parse_mode="HTML",
            reply_markup=games_menu()
        )
        return

    # START GAME
    if data.startswith("game_"):

        game = data.replace(
            "game_",
            ""
        )

        valid = [
            x[1]
            for x in GAMES
        ]

        if game not in valid:
            return

        await start_game(
            update,
            context,
            game
        )
        return

    # QUIZ ANSWER
    if data.startswith("answer_"):

        game = context.user_data.get(
            "game"
        )

        if not game:
            return

        try:
            selected = int(
                data.replace(
                    "answer_",
                    ""
                )
            )
        except ValueError:
            return

        if selected == game["correct"]:

            reward = game["reward"]

            await change_points(
                user.id,
                reward
            )

            await game_result(
                user.id,
                True
            )

            context.user_data.pop(
                "game",
                None
            )

            await q.message.reply_text(
                f"🎉 <b>TO‘G‘RI!</b>\n\n"
                f"⭐ +{reward:g} Stars",
                parse_mode="HTML"
            )

        else:

            await game_result(
                user.id,
                False
            )

            context.user_data.pop(
                "game",
                None
            )

            await q.message.reply_text(
                "❌ Noto‘g‘ri javob."
            )

        await save_database()
        return

    # LOGIC ANSWER
    if data.startswith("logic_"):

        game = context.user_data.get(
            "game"
        )

        if not game:
            return

        selected = int(
            data.replace(
                "logic_",
                ""
            )
        )

        if selected == game["correct"]:

            reward = game["reward"]

            await change_points(
                user.id,
                reward
            )

            await game_result(
                user.id,
                True
            )

            await q.message.reply_text(
                f"🧠 🎉 To‘g‘ri!\n"
                f"⭐ +{reward:g} Stars",
                parse_mode="HTML"
            )

        else:

            await game_result(
                user.id,
                False
            )

            await q.message.reply_text(
                "❌ Mantiqiy javob noto‘g‘ri."
            )

        context.user_data.pop(
            "game",
            None
        )

        await save_database()
        return

    # TARGET
    if data.startswith("target_"):

        game = context.user_data.get(
            "game"
        )

        if not game:
            return

        selected = int(
            data.replace(
                "target_",
                ""
            )
        )

        correct = selected == game["correct"]

        if correct:

            reward = game["reward"]

            await change_points(
                user.id,
                reward
            )

            await game_result(
                user.id,
                True
            )

            await q.message.reply_text(
                f"🎯 🎉 Nishon topildi!\n"
                f"⭐ +{reward:g} Stars",
                parse_mode="HTML"
            )

        else:

            await game_result(
                user.id,
                False
            )

            await q.message.reply_text(
                "❌ Nishon noto‘g‘ri."
            )

        context.user_data.pop(
            "game",
            None
        )

        await save_database()
        return

    # ATTENTION
    if data.startswith("attention_"):

        game = context.user_data.get(
            "game"
        )

        if not game:
            return

        selected = int(
            data.replace(
                "attention_",
                ""
            )
        )

        if selected == game["correct"]:

            reward = game["reward"]

            await change_points(
                user.id,
                reward
            )

            await game_result(
                user.id,
                True
            )

            await q.message.reply_text(
                f"👀 🎉 Diqqat yaxshi!\n"
                f"⭐ +{reward:g} Stars",
                parse_mode="HTML"
            )

        else:

            await game_result(
                user.id,
                False
            )

            await q.message.reply_text(
                "❌ Noto‘g‘ri raqam."
            )

        context.user_data.pop(
            "game",
            None
        )

        await save_database()
        return

    # COLOR
    if data.startswith("color_"):

        game = context.user_data.get(
            "game"
        )

        if not game:
            return

        selected = data.replace(
            "color_",
            ""
        )

        if selected == game["correct"]:

            reward = game["reward"]

            await change_points(
                user.id,
                reward
            )

            await game_result(
                user.id,
                True
            )

            await q.message.reply_text(
                f"🎨 🎉 To‘g‘ri rang!\n"
                f"⭐ +{reward:g} Stars",
                parse_mode="HTML"
            )

        else:

            await game_result(
                user.id,
                False
            )

            await q.message.reply_text(
                "❌ Noto‘g‘ri rang."
            )

        context.user_data.pop(
            "game",
            None
        )

        await save_database()
        return

    # KNOWLEDGE
    if data.startswith("knowledge_"):

        game = context.user_data.get(
            "game"
        )

        if not game:
            return

        selected = int(
            data.replace(
                "knowledge_",
                ""
            )
        )

        if selected == game["correct"]:

            reward = game["reward"]

            await change_points(
                user.id,
                reward
            )

            await game_result(
                user.id,
                True
            )

            await q.message.reply_text(
                f"📚 🎉 To‘g‘ri!\n"
                f"⭐ +{reward:g} Stars",
                parse_mode="HTML"
            )

        else:

            await game_result(
                user.id,
                False
            )

            await q.message.reply_text(
                "❌ Noto‘g‘ri javob."
            )

        context.user_data.pop(
            "game",
            None
        )

        await save_database()
        return

    # CHOICE
    if data.startswith("choice_"):

        game = context.user_data.get(
            "game"
        )

        if not game:
            return

        selected = data.replace(
            "choice_",
            ""
        )

        # Bu o‘yinda to‘g‘ri variant context'da saqlangan
        if selected == game["correct"]:

            reward = game["reward"]

            await change_points(
                user.id,
                reward
            )

            await game_result(
                user.id,
                True
            )

            await q.message.reply_text(
                f"⚡ 🎉 To‘g‘ri tanlov!\n"
                f"⭐ +{reward:g} Stars",
                parse_mode="HTML"
            )

        else:

            await game_result(
                user.id,
                False
            )

            await q.message.reply_text(
                "❌ Noto‘g‘ri tanlov."
            )

        context.user_data.pop(
            "game",
            None
        )

        await save_database()
        return

    # OTHER GAMES
    if data == "other_games":

        await q.message.reply_text(
            "🎮 <b>O‘YINLAR</b>\n\n"
            "Bu bo‘limdagi mavjud o‘yinlarni "
            "keyingi versiyalarda kengaytirish mumkin.",
            parse_mode="HTML"
        )
        return

    # ADMIN
    if data == "admin":

        if user.id != ADMIN_ID:
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    "📊 STATISTIKA",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 USERLAR",
                    callback_data="admin_users"
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 XABAR YUBORISH",
                    callback_data="admin_broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ TOPSHIRIQ QO‘SHISH",
                    callback_data="admin_addtask"
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 TOPSHIRIQLAR",
                    callback_data="admin_tasks"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Bosh menyu",
                    callback_data="home"
                )
            ]
        ]

        await q.message.reply_text(
            "⚙️ <b>ADMIN PANEL</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ADMIN STATS
    if data == "admin_stats":

        if user.id != ADMIN_ID:
            return

        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM users"
        )
        users_count = cur.fetchone()[0]

        cur.execute(
            "SELECT SUM(points) FROM users"
        )
        total_points = cur.fetchone()[0] or 0

        cur.execute(
            "SELECT SUM(referrals) FROM users"
        )
        referrals = cur.fetchone()[0] or 0

        cur.execute("""
        SELECT COUNT(*)
        FROM withdrawals
        WHERE status='pending'
        """)
        pending = cur.fetchone()[0]

        cur.execute("""
        SELECT total_users
        FROM bot_stats
        WHERE id=1
        """)
        total_since_start = cur.fetchone()[0] or users_count

        con.close()

        await q.message.reply_text(
            "📊 <b>BOT STATISTIKASI</b>\n\n"
            f"👥 Jami userlar: <b>{users_count}</b>\n"
            f"📈 Bot ochilgandan beri: <b>{total_since_start}</b>\n"
            f"⭐ Jami Stars: <b>{total_points:.2f}</b>\n"
            f"👥 Jami referallar: <b>{referrals}</b>\n"
            f"💸 Kutilayotgan yechish: <b>{pending}</b>",
            parse_mode="HTML"
        )
        return

    # ADMIN USERS
    if data == "admin_users":

        if user.id != ADMIN_ID:
            return

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT COUNT(*)
        FROM users
        """)

        count = cur.fetchone()[0]

        con.close()

        await q.message.reply_text(
            f"👥 <b>Jami foydalanuvchilar:</b> "
            f"<b>{count}</b>",
            parse_mode="HTML"
        )
        return

    # ADMIN BROADCAST
    if data == "admin_broadcast":

        if user.id != ADMIN_ID:
            return

        context.user_data["admin_action"] = "broadcast"

        await q.message.reply_text(
            "📢 <b>Broadcast</b>\n\n"
            "Yubormoqchi bo‘lgan xabaringizni "
            "shu yerga yuboring.",
            parse_mode="HTML"
        )
        return

    # ADMIN ADD TASK
    if data == "admin_addtask":

        if user.id != ADMIN_ID:
            return

        context.user_data["admin_action"] = "add_task"

        await q.message.reply_text(
            "➕ <b>TOPSHIRIQ QO‘SHISH</b>\n\n"
            "Quyidagi formatda yuboring:\n\n"
            "<code>MATN | REWARD | URL</code>\n\n"
            "Masalan:\n"
            "<code>Kanalga obuna bo‘ling | 5 | https://t.me/example</code>",
            parse_mode="HTML"
        )
        return

    # ADMIN TASK LIST
    if data == "admin_tasks":

        if user.id != ADMIN_ID:
            return

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT id, text, reward, url
        FROM tasks
        ORDER BY id DESC
        """)

        rows = cur.fetchall()

        con.close()

        if not rows:
            await q.message.reply_text(
                "📋 Hali topshiriqlar yo‘q."
            )
            return

        text = "📋 <b>TOPSHIRIQLAR</b>\n\n"

        for task_id, task_text, reward, url in rows:

            text += (
                f"#{task_id} — {task_text}\n"
                f"⭐ {reward:g}\n"
                f"{url}\n\n"
            )

        await q.message.reply_text(
            text,
            parse_mode="HTML"
        )
        return


# ==========================================================
# ADMIN MESSAGE
# ==========================================================

async def admin_message(update, context):

    user = update.effective_user

    if user.id != ADMIN_ID:
        return

    action = context.user_data.get(
        "admin_action"
    )

    if action == "broadcast":

        text = update.message.text

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT id
        FROM users
        WHERE blocked=0
        """)

        users = cur.fetchall()

        con.close()

        sent = 0
        blocked = 0

        await update.message.reply_text(
            f"📢 Xabar {len(users)} ta userga yuborilmoqda..."
        )

        for (user_id,) in users:

            try:

                await context.bot.send_message(
                    user_id,
                    text
                )

                sent += 1

                await asyncio.sleep(0.04)

            except Forbidden:

                blocked += 1

                con = db()
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

            except TelegramError:
                pass

        context.user_data.pop(
            "admin_action",
            None
        )

        await update.message.reply_text(
            "✅ <b>Broadcast tugadi.</b>\n\n"
            f"📨 Yuborildi: <b>{sent}</b>\n"
            f"🚫 Bloklaganlar: <b>{blocked}</b>",
            parse_mode="HTML"
        )

        await save_database()
        return

    if action == "add_task":

        try:
            parts = [
                x.strip()
                for x in update.message.text.split("|")
            ]

            if len(parts) != 3:
                raise ValueError

            text = parts[0]
            reward = float(parts[1])
            url = parts[2]

            if not text or not url:
                raise ValueError

        except ValueError:

            await update.message.reply_text(
                "❌ Format noto‘g‘ri.\n\n"
                "<code>MATN | REWARD | URL</code>",
                parse_mode="HTML"
            )
            return

        con = db()
        cur = con.cursor()

        cur.execute("""
        INSERT INTO tasks
        (text, reward, url)
        VALUES (?, ?, ?)
        """, (
            text,
            reward,
            url
        ))

        task_id = cur.lastrowid

        con.commit()
        con.close()

        context.user_data.pop(
            "admin_action",
            None
        )

        await update.message.reply_text(
            f"✅ Topshiriq #{task_id} qo‘shildi.\n\n"
            f"🎁 {text}\n"
            f"⭐ Reward: {reward:g}\n"
            f"🔗 {url}",
            parse_mode="HTML"
        )

        await save_database()
        return


# ==========================================================
# ERROR
# ==========================================================

async def error_handler(update, context):

    error = context.error

    log.error(
        "Exception while handling update: %s",
        error,
        exc_info=True
    )


# ==========================================================
# POST INIT
# ==========================================================

async def post_init(application):

    init_db()

    application.create_task(
        periodic_database_backup()
    )

    log.info(
        "Zerikdim Bot ishga tushdi."
    )


# ==========================================================
# POST SHUTDOWN
# ==========================================================

async def post_shutdown(application):

    try:
        await save_database()
    except Exception as e:
        log.error(
            "Shutdown backup error: %s",
            e
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi!"
        )

    if not ADMIN_ID:
        log.warning(
            "ADMIN_ID sozlanmagan."
        )

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            menu
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            process_game_answer
        )
    )

    application.add_handler(
        MessageHandler(
            filters.ALL,
            admin_message
        )
    )

    application.add_error_handler(
        error_handler
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
