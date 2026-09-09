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

# =========================================================
# SOZLAMALAR
# =========================================================

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "zerikdim.db"

SPONSOR_CHANNEL = "@premyumstarstekin"
SPONSOR_URL = "https://t.me/premyumstarstekin"
SPONSOR_LIMIT = 2000

BUY_STARS_URL = "https://t.me/premyumstarstekin/933"

REFERRAL_REWARD = 9.0
GAME_REWARD = 0.02
TASK_REWARD = 5.0

MIN_WITHDRAW = 200.0
MIN_REFERRALS = 20

GAME_COOLDOWN = 30
PAGE_SIZE = 10

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# O'YINLAR
# =========================================================

GAMES = {
    "quiz": "🧠 Viktorina",
    "number": "🔢 Son topish",
    "choice": "🎯 Tanlov",
    "logic": "🧩 Mantiq",
    "target": "🎯 Nishon",
    "word": "🔤 So'z topish",
    "math": "➗ Matematika",
    "attention": "👀 Diqqat",
    "color": "🎨 Rang",
    "code": "🔐 Kod",
    "knowledge": "📚 Bilim",
    "speed": "⚡ Tezlik",
}

QUIZ = [
    ("O'zbekiston poytaxti qaysi?", ["Toshkent", "Samarqand", "Buxoro", "Andijon"], "Toshkent"),
    ("2 + 2 nechchi?", ["3", "4", "5", "6"], "4"),
    ("Yerning tabiiy yo'ldoshi nima?", ["Quyosh", "Oy", "Mars", "Yulduz"], "Oy"),
    ("Haftada nechta kun bor?", ["5", "6", "7", "8"], "7"),
    ("O'zbekiston pul birligi nima?", ["Dollar", "So'm", "Rubl", "Euro"], "So'm"),
    ("Bir yilda nechta oy bor?", ["10", "11", "12", "13"], "12"),
    ("5 × 5 nechchi?", ["20", "25", "30", "35"], "25"),
    ("Suvning kimyoviy formulasi?", ["CO2", "O2", "H2O", "NaCl"], "H2O"),
]

LOGIC_QUESTIONS = [
    ("3, 6, 9, 12, ?", ["14", "15", "16", "18"], "15"),
    ("2, 4, 8, 16, ?", ["24", "30", "32", "36"], "32"),
    ("1, 4, 9, 16, ?", ["20", "24", "25", "26"], "25"),
    ("10, 20, 30, 40, ?", ["45", "50", "55", "60"], "50"),
    ("5, 10, 20, 40, ?", ["50", "60", "70", "80"], "80"),
]

WORDS = [
    ("HSTOAN", "TOSHAN"),
    ("KTOBII", "KITOBI"),
    ("HOMAL", "OLMAH"),
    ("NOML", "NOLM"),
    ("TOSHKENT", "TOSHKENT"),
    ("DO'ST", "DO'ST"),
    ("YULDUZ", "YULDUZ"),
]

COLORS = [
    ("🔴", "Qizil"),
    ("🟢", "Yashil"),
    ("🔵", "Ko'k"),
    ("🟡", "Sariq"),
]

KNOWLEDGE = [
    (
        "Dunyodagi eng katta okean qaysi?",
        ["Tinch", "Atlantika", "Hind", "Shimoliy Muz"],
        "Tinch",
    ),
    (
        "O'zbekistonda nechta viloyat bor?",
        ["10", "12", "14", "16"],
        "12",
    ),
    (
        "Quyosh qaysi turdagi osmon jismi?",
        ["Sayyora", "Yulduz", "Yo'ldosh", "Asteroid"],
        "Yulduz",
    ),
    (
        "Eng kichik tub son qaysi?",
        ["0", "1", "2", "3"],
        "2",
    ),
]


# =========================================================
# YORDAMCHI FUNKSIYALAR
# =========================================================

def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def format_count(number):
    return f"{int(number):,}".replace(",", " ")


# =========================================================
# DATABASE
# =========================================================

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            points REAL DEFAULT 0,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT NULL,
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
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            reward REAL,
            url TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_claims (
            user_id INTEGER,
            task_id INTEGER,
            created_at TEXT,
            PRIMARY KEY(user_id, task_id)
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
        INSERT OR IGNORE INTO sponsor_settings
        (id, active, disabled_at)
        VALUES (1, 1, NULL)
    """)

    cur.execute("""
        SELECT COUNT(*) FROM users
    """)

    total_users = cur.fetchone()[0]

    cur.execute("""
        INSERT OR IGNORE INTO bot_stats
        (id, started_at, total_users)
        VALUES (1, ?, ?)
    """, (now(), total_users))

    cur.execute("""
        UPDATE bot_stats
        SET total_users =
            CASE
                WHEN total_users < ? THEN ?
                ELSE total_users
            END
        WHERE id = 1
    """, (total_users, total_users))

    con.commit()
    con.close()


# =========================================================
# SPONSOR
# =========================================================

def sponsor_is_active_sync():
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT active
        FROM sponsor_settings
        WHERE id = 1
    """)

    row = cur.fetchone()

    con.close()

    if row is None:
        return True

    return bool(row[0])


async def sponsor_is_active():
    return await asyncio.to_thread(sponsor_is_active_sync)


def disable_sponsor_sync():
    con = db()

    con.execute("""
        UPDATE sponsor_settings
        SET active = 0,
            disabled_at = ?
        WHERE id = 1
    """, (now(),))

    con.commit()
    con.close()


async def disable_sponsor():
    await asyncio.to_thread(disable_sponsor_sync)


async def check_sponsor_limit(bot):
    try:
        member_count = await bot.get_chat_member_count(SPONSOR_CHANNEL)

        if member_count >= SPONSOR_LIMIT:
            if await sponsor_is_active():
                await disable_sponsor()

                try:
                    await bot.send_message(
                        ADMIN_ID,
                        "⚠️ <b>Homiy kanal limiti to'ldi!</b>\n\n"
                        f"👥 A'zolar: <b>{format_count(member_count)}</b>\n"
                        f"🚫 Limit: <b>{format_count(SPONSOR_LIMIT)}</b>\n\n"
                        "Majburiy obuna avtomatik o'chirildi.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

                logger.warning(
                    "Sponsor limit reached: %s",
                    member_count
                )

    except Exception as e:
        logger.error("Sponsor limit error: %s", e)


async def periodic_sponsor_check(bot):
    while True:
        try:
            await check_sponsor_limit(bot)
        except Exception as e:
            logger.error("Periodic sponsor check: %s", e)

        await asyncio.sleep(60)


# =========================================================
# USERS
# =========================================================

def get_total_users_sync():
    con = db()

    cur = con.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM users
    """)

    total = cur.fetchone()[0]

    con.close()

    return total


async def get_total_users():
    return await asyncio.to_thread(get_total_users_sync)


async def update_bot_user_count(bot):
    try:
        await bot.set_my_short_description(
            "⭐ Stars ishlang va o'yinlarda qatnashing!"
        )
    except Exception:
        pass


def add_user_sync(
    user_id,
    username=None,
    referred_by=None,
):
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT id
        FROM users
        WHERE id = ?
    """, (user_id,))

    exists = cur.fetchone()

    if not exists:
        cur.execute("""
            INSERT INTO users (
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
            referred_by,
            now(),
        ))

        cur.execute("""
            UPDATE bot_stats
            SET total_users = total_users + 1
            WHERE id = 1
        """)

        if referred_by and referred_by != user_id:
            cur.execute("""
                SELECT id
                FROM users
                WHERE id = ?
            """, (referred_by,))

            referrer_exists = cur.fetchone()

            if referrer_exists:
                cur.execute("""
                    UPDATE users
                    SET referrals = referrals + 1,
                        points = points + ?
                    WHERE id = ?
                """, (
                    REFERRAL_REWARD,
                    referred_by,
                ))

                cur.execute("""
                    UPDATE users
                    SET referral_rewarded = 1
                    WHERE id = ?
                """, (user_id,))

        created = True

    else:
        cur.execute("""
            UPDATE users
            SET username = ?,
                last_seen = ?,
                blocked = 0
            WHERE id = ?
        """, (
            username,
            now(),
            user_id,
        ))

        created = False

    con.commit()
    con.close()

    return created


async def add_user(
    user_id,
    username=None,
    referred_by=None,
    bot=None,
):
    created = await asyncio.to_thread(
        add_user_sync,
        user_id,
        username,
        referred_by,
    )

    if created and bot:
        await update_bot_user_count(bot)

    return created


def get_user(user_id):
    con = db()

    cur = con.cursor()

    cur.execute("""
        SELECT
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
        FROM users
        WHERE id = ?
    """, (user_id,))

    row = cur.fetchone()

    con.close()

    return row


def change_points_sync(user_id, amount):
    con = db()

    cur = con.cursor()

    cur.execute("""
        UPDATE users
        SET points = points + ?
        WHERE id = ?
    """, (
        amount,
        user_id,
    ))

    con.commit()
    con.close()


async def change_points(user_id, amount):
    await asyncio.to_thread(
        change_points_sync,
        user_id,
        amount,
    )


def game_result_sync(user_id, win):
    con = db()

    cur = con.cursor()

    if win:
        cur.execute("""
            UPDATE users
            SET games = games + 1,
                wins = wins + 1
            WHERE id = ?
        """, (user_id,))
    else:
        cur.execute("""
            UPDATE users
            SET games = games + 1
            WHERE id = ?
        """, (user_id,))

    con.commit()
    con.close()


async def game_result(user_id, win):
    await asyncio.to_thread(
        game_result_sync,
        user_id,
        win,
    )


# =========================================================
# GITHUB DATABASE BACKUP
# =========================================================

save_lock = asyncio.Lock()


def git_command(command, timeout=60):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def save_database():
    async with save_lock:

        def _save():

            if not os.path.exists(DB_FILE):
                return False

            try:
                con = sqlite3.connect(DB_FILE)

                try:
                    con.execute("PRAGMA wal_checkpoint(FULL)")
                except Exception:
                    pass

                con.close()

                git_command([
                    "git",
                    "config",
                    "user.name",
                    "Zerikdim Bot",
                ])

                git_command([
                    "git",
                    "config",
                    "user.email",
                    "zerikdim-bot@users.noreply.github.com",
                ])

                git_command([
                    "git",
                    "add",
                    "-f",
                    DB_FILE,
                ])

                check = git_command([
                    "git",
                    "diff",
                    "--cached",
                    "--quiet",
                ])

                if check.returncode == 0:
                    return True

                commit = git_command([
                    "git",
                    "commit",
                    "-m",
                    "Update Zerikdim database",
                ])

                if commit.returncode != 0:
                    logger.error(
                        "Git commit error: %s",
                        commit.stderr,
                    )
                    return False

                branch_result = git_command([
                    "git",
                    "branch",
                    "--show-current",
                ])

                branch = branch_result.stdout.strip() or "main"

                push = git_command([
                    "git",
                    "push",
                    "origin",
                    branch,
                ])

                if push.returncode != 0:
                    logger.error(
                        "Git push error: %s",
                        push.stderr,
                    )
                    return False

                logger.info("Database successfully saved")

                return True

            except Exception as e:
                logger.error(
                    "Database backup error: %s",
                    e,
                )
                return False

        return await asyncio.to_thread(_save)


async def periodic_database_backup():
    await asyncio.sleep(30)

    while True:
        try:
            await save_database()
        except Exception as e:
            logger.error(
                "Periodic database backup error: %s",
                e,
            )

        await asyncio.sleep(60)


# =========================================================
# SUBSCRIPTION
# =========================================================

async def subscribed(bot, user_id):
    if not await sponsor_is_active():
        return True

    try:
        member = await bot.get_chat_member(
            SPONSOR_CHANNEL,
            user_id,
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception as e:
        logger.error(
            "Subscription check error: %s",
            e,
        )

        return False


async def require_subscription(
    update,
    context,
):
    user = update.effective_user

    if user.id == ADMIN_ID:
        return True

    if not await sponsor_is_active():
        return True

    if await subscribed(
        context.bot,
        user.id,
    ):
        return True

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 Homiy kanalga obuna bo'lish",
                url=SPONSOR_URL,
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Tekshirish",
                callback_data="check_sub",
            )
        ],
    ])

    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(
                "🔒 <b>Botdan foydalanish uchun kanalga obuna bo'ling.</b>\n\n"
                f"📢 Kanal: {SPONSOR_CHANNEL}\n\n"
                "Obuna bo'lgach, «Tekshirish» tugmasini bosing.",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(
            "🔒 <b>Botdan foydalanish uchun kanalga obuna bo'ling.</b>\n\n"
            f"📢 Kanal: {SPONSOR_CHANNEL}\n\n"
            "Obuna bo'lgach, «Tekshirish» tugmasini bosing.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    return False


# =========================================================
# MAIN MENU
# =========================================================

def main_menu(is_admin=False):
    keyboard = [
        [
            InlineKeyboardButton(
                "⭐ STARS OLISH",
                callback_data="buy",
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 STARS ISHLASH",
                callback_data="games",
            )
        ],
        [
            InlineKeyboardButton(
                "🎮 O'YINLAR",
                callback_data="games",
            )
        ],
        [
            InlineKeyboardButton(
                "💰 BALANS",
                callback_data="balance",
            ),
            InlineKeyboardButton(
                "🎁 TOPSHIRIQLAR",
                callback_data="tasks",
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="ref",
            ),
            InlineKeyboardButton(
                "💸 YECHIB OLISH",
                callback_data="withdraw",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏆 REYTING",
                callback_data="rating",
            ),
            InlineKeyboardButton(
                "👤 PROFIL",
                callback_data="profile",
            ),
        ],
    ]

    if is_admin:
        keyboard.append([
            InlineKeyboardButton(
                "⚙️ ADMIN PANEL",
                callback_data="admin",
            )
        ])

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    ref = None

    if context.args:
        try:
            ref = int(context.args[0])
        except Exception:
            ref = None

    await add_user(
        user.id,
        user.username,
        ref,
        context.bot,
    )

    await check_sponsor_limit(context.bot)

    if not await require_subscription(
        update,
        context,
    ):
        return

    admin = user.id == ADMIN_ID

    text = (
        "👋 <b>Zerikdim Botga xush kelibsiz!</b>\n\n"
        "⭐ Stars ishlang, topshiriqlar bajaring va "
        "do'stlaringizni taklif qiling.\n\n"
        "👇 Kerakli bo'limni tanlang:"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu(admin),
        parse_mode="HTML",
    )


# =========================================================
# GAMES MENU
# =========================================================

def games_menu():
    keyboard = []

    items = list(GAMES.items())

    for i in range(0, len(items), 2):
        row = []

        for game_id, name in items[i:i + 2]:
            row.append(
                InlineKeyboardButton(
                    name,
                    callback_data=f"game_{game_id}",
                )
            )

        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(
            "🏠 Bosh menyu",
            callback_data="home",
        )
    ])

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# GAME COOLDOWN
# =========================================================

def can_play(context, user_id):
    key = f"game_last_{user_id}"

    last = context.user_data.get(key)

    if last is None:
        return True

    return (
        asyncio.get_event_loop().time() - last
        >= GAME_COOLDOWN
    )


def mark_game(context, user_id):
    context.user_data[
        f"game_last_{user_id}"
    ] = asyncio.get_event_loop().time()


# =========================================================
# START GAME
# =========================================================

async def start_game(
    query,
    context,
    game_id,
):
    user = query.from_user

    if not can_play(
        context,
        user.id,
    ):
        await query.message.reply_text(
            f"⏳ Keyingi o'yinni boshlash uchun "
            f"<b>{GAME_COOLDOWN} soniya</b> kuting.",
            parse_mode="HTML",
        )
        return

    mark_game(
        context,
        user.id,
    )

    context.user_data.pop(
        "game",
        None,
    )

    context.user_data.pop(
        "game_data",
        None,
    )

    context.user_data["game"] = game_id

    # -----------------------------------------------------
    # QUIZ
    # -----------------------------------------------------

    if game_id == "quiz":
        question, options, answer = random.choice(QUIZ)

        context.user_data["game_data"] = {
            "answer": answer,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    option,
                    callback_data=f"choice_{i}",
                )
            ]
            for i, option in enumerate(options)
        ]

        context.user_data["choice_options"] = options

        await query.message.reply_text(
            "🧠 <b>Viktorina</b>\n\n"
            f"{question}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # NUMBER
    # -----------------------------------------------------

    elif game_id == "number":
        number = random.randint(
            1,
            30,
        )

        context.user_data["game_data"] = {
            "answer": number,
            "tries": 0,
        }

        await query.message.reply_text(
            "🔢 <b>Son topish</b>\n\n"
            "1 dan 30 gacha son o'yladim.\n"
            "Sonni yozing.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # CHOICE
    # -----------------------------------------------------

    elif game_id == "choice":
        options = [
            "1️⃣",
            "2️⃣",
            "3️⃣",
            "4️⃣",
        ]

        answer = random.choice(options)

        context.user_data["game_data"] = {
            "answer": answer,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"choiceanswer_{x}",
                )
                for x in options[:2]
            ],
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"choiceanswer_{x}",
                )
                for x in options[2:]
            ],
        ]

        await query.message.reply_text(
            "🎯 <b>Tanlov</b>\n\n"
            "To'g'ri variantni toping.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

        context.user_data["choice_answer"] = answer

    # -----------------------------------------------------
    # LOGIC
    # -----------------------------------------------------

    elif game_id == "logic":
        question, options, answer = random.choice(
            LOGIC_QUESTIONS
        )

        context.user_data["game_data"] = {
            "answer": answer,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    option,
                    callback_data=f"logic_{i}",
                )
            ]
            for i, option in enumerate(options)
        ]

        context.user_data["logic_options"] = options

        await query.message.reply_text(
            "🧩 <b>Mantiqiy savol</b>\n\n"
            f"{question}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # TARGET
    # -----------------------------------------------------

    elif game_id == "target":
        target = random.randint(
            1,
            10,
        )

        context.user_data["game_data"] = {
            "answer": target,
        }

        keyboard = []

        for i in range(1, 11, 2):
            keyboard.append([
                InlineKeyboardButton(
                    str(i),
                    callback_data=f"target_{i}",
                ),
                InlineKeyboardButton(
                    str(i + 1),
                    callback_data=f"target_{i + 1}",
                ),
            ])

        await query.message.reply_text(
            "🎯 <b>Nishon</b>\n\n"
            "1 dan 10 gacha yashirin raqam bor.\n"
            "To'g'ri raqamni toping.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # WORD
    # -----------------------------------------------------

    elif game_id == "word":
        scrambled, correct = random.choice(
            WORDS
        )

        context.user_data["game_data"] = {
            "answer": correct.lower(),
        }

        await query.message.reply_text(
            "🔤 <b>So'z topish</b>\n\n"
            f"Aralashtirilgan so'z: <b>{scrambled}</b>\n\n"
            "To'g'ri so'zni yozing.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # MATH
    # -----------------------------------------------------

    elif game_id == "math":
        a = random.randint(2, 20)
        b = random.randint(2, 20)

        operators = ["+", "-", "*"]
        operator = random.choice(operators)

        if operator == "+":
            answer = a + b
        elif operator == "-":
            answer = a - b
        else:
            answer = a * b

        context.user_data["game_data"] = {
            "answer": answer,
        }

        await query.message.reply_text(
            "➗ <b>Matematika</b>\n\n"
            f"<b>{a} {operator} {b} = ?</b>\n\n"
            "Javobni yozing.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # ATTENTION
    # -----------------------------------------------------

    elif game_id == "attention":
        values = [
            "🔴",
            "🔵",
            "🟢",
            "🟡",
            "🟣",
        ]

        sequence = [
            random.choice(values)
            for _ in range(5)
        ]

        answer = sequence[2]

        context.user_data["game_data"] = {
            "answer": answer,
        }

        await query.message.reply_text(
            "👀 <b>Diqqat</b>\n\n"
            + " ".join(sequence)
            + "\n\n"
            "O'rtadagi belgini yozing.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # COLOR
    # -----------------------------------------------------

    elif game_id == "color":
        emoji, answer = random.choice(
            COLORS
        )

        context.user_data["game_data"] = {
            "answer": answer.lower(),
        }

        options = [
            "Qizil",
            "Yashil",
            "Ko'k",
            "Sariq",
        ]

        random.shuffle(options)

        keyboard = [
            [
                InlineKeyboardButton(
                    option,
                    callback_data=f"color_{i}",
                )
            ]
            for i, option in enumerate(options)
        ]

        context.user_data["color_options"] = options

        await query.message.reply_text(
            "🎨 <b>Rang</b>\n\n"
            f"{emoji}\n\n"
            "Bu qaysi rang?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # CODE
    # -----------------------------------------------------

    elif game_id == "code":
        numbers = [
            random.randint(1, 9)
            for _ in range(4)
        ]

        answer = sum(numbers)

        context.user_data["game_data"] = {
            "answer": answer,
        }

        await query.message.reply_text(
            "🔐 <b>Kod</b>\n\n"
            f"Sonlar: <b>{' + '.join(map(str, numbers))}</b>\n\n"
            "Ularning yig'indisini yozing.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # KNOWLEDGE
    # -----------------------------------------------------

    elif game_id == "knowledge":
        question, options, answer = random.choice(
            KNOWLEDGE
        )

        context.user_data["game_data"] = {
            "answer": answer,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    option,
                    callback_data=f"knowledge_{i}",
                )
            ]
            for i, option in enumerate(options)
        ]

        context.user_data["knowledge_options"] = options

        await query.message.reply_text(
            "📚 <b>Bilim</b>\n\n"
            f"{question}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # SPEED
    # -----------------------------------------------------

    elif game_id == "speed":
        a = random.randint(
            10,
            50,
        )

        b = random.randint(
            2,
            20,
        )

        answer = a + b

        context.user_data["game_data"] = {
            "answer": answer,
        }

        await query.message.reply_text(
            "⚡ <b>Tezlik</b>\n\n"
            f"<b>{a} + {b} = ?</b>\n\n"
            "Javobni tez yozing!",
            parse_mode="HTML",
        )


# =========================================================
# GAME ANSWER
# =========================================================

async def process_game_answer(
    update,
    context,
    text,
):
    user = update.effective_user

    game = context.user_data.get(
        "game"
    )

    data = context.user_data.get(
        "game_data"
    )

    if not game or not data:
        return False

    answer = data.get(
        "answer"
    )

    normalized = text.strip().lower()

    correct = False

    if game in (
        "number",
        "math",
        "code",
        "speed",
    ):
        try:
            user_answer = int(
                normalized
            )
        except Exception:
            await update.message.reply_text(
                "❌ Iltimos, raqam kiriting."
            )
            return True

        if game == "number":
            if user_answer == answer:
                correct = True

            else:
                data["tries"] = data.get(
                    "tries",
                    0,
                ) + 1

                tries = data["tries"]

                if tries >= 7:
                    await game_result(
                        user.id,
                        False,
                    )

                    context.user_data.pop(
                        "game",
                        None,
                    )

                    context.user_data.pop(
                        "game_data",
                        None,
                    )

                    await update.message.reply_text(
                        f"❌ Yutqazdingiz.\n\n"
                        f"To'g'ri javob: <b>{answer}</b>",
                        parse_mode="HTML",
                    )

                    await save_database()

                    return True

                if user_answer < answer:
                    hint = "⬆️ Kattaroq son."
                else:
                    hint = "⬇️ Kichikroq son."

                await update.message.reply_text(
                    f"❌ Noto'g'ri.\n"
                    f"{hint}\n\n"
                    f"Urinish: {tries}/7"
                )

                return True

        else:
            correct = (
                user_answer == answer
            )

    elif game in (
        "word",
        "attention",
    ):
        correct = (
            normalized
            == str(answer).lower()
        )

    if correct:
        reward = random.choice([
            1.0,
            1.2,
            1.5,
            2.0,
        ])

        await change_points(
            user.id,
            reward,
        )

        await game_result(
            user.id,
            True,
        )

        await update.message.reply_text(
            "🎉 <b>To'g'ri!</b>\n\n"
            f"⭐ Siz <b>{reward}</b> Stars yutdingiz!",
            parse_mode="HTML",
        )

    else:
        await game_result(
            user.id,
            False,
        )

        await update.message.reply_text(
            "❌ Noto'g'ri javob."
        )

    context.user_data.pop(
        "game",
        None,
    )

    context.user_data.pop(
        "game_data",
        None,
    )

    await save_database()

    return True


# =========================================================
# MENU CALLBACK
# =========================================================

async def menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    user = query.from_user

    data = query.data

    await add_user(
        user.id,
        user.username,
        None,
        context.bot,
    )

    await check_sponsor_limit(
        context.bot
    )

    # -----------------------------------------------------
    # CHECK SUB
    # -----------------------------------------------------

    if data == "check_sub":
        if await subscribed(
            context.bot,
            user.id,
        ):
            await query.message.reply_text(
                "✅ Obuna tasdiqlandi!\n\n"
                "Endi botdan foydalanishingiz mumkin.",
                reply_markup=main_menu(
                    user.id == ADMIN_ID
                ),
            )
        else:
            await query.message.reply_text(
                "❌ Siz hali kanalga obuna bo'lmagansiz.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📢 Kanalga kirish",
                            url=SPONSOR_URL,
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "✅ Tekshirish",
                            callback_data="check_sub",
                        )
                    ],
                ]),
            )

        return

    # -----------------------------------------------------
    # SUBSCRIPTION
    # -----------------------------------------------------

    if user.id != ADMIN_ID:
        if not await require_subscription(
            update,
            context,
        ):
            return

    # -----------------------------------------------------
    # HOME
    # -----------------------------------------------------

    if data == "home":
        text = (
            "🏠 <b>Asosiy menyu</b>\n\n"
            "👇 Kerakli bo'limni tanlang:"
        )

        await query.message.reply_text(
            text,
            reply_markup=main_menu(
                user.id == ADMIN_ID
            ),
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # BUY
    # -----------------------------------------------------

    if data == "buy":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⭐ Stars sotib olish",
                    url=BUY_STARS_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Bosh menyu",
                    callback_data="home",
                )
            ],
        ])

        await query.message.reply_text(
            "⭐ <b>STARS OLISH</b>\n\n"
            "Stars sotib olish uchun quyidagi tugmani bosing.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    if data == "balance":
        row = get_user(user.id)

        points = row[2] if row else 0

        await query.message.reply_text(
            "💰 <b>Sizning balansingiz</b>\n\n"
            f"⭐ Stars: <b>{points:.2f}</b>",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 Bosh menyu",
                        callback_data="home",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # PROFILE
    # -----------------------------------------------------

    if data == "profile":
        row = get_user(user.id)

        if not row:
            return

        username = row[1] or "yo'q"
        points = row[2]
        games = row[3]
        wins = row[4]
        referrals = row[5]

        await query.message.reply_text(
            "👤 <b>PROFIL</b>\n\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"👤 Username: @{username}\n"
            f"⭐ Stars: <b>{points:.2f}</b>\n"
            f"🎮 O'yinlar: <b>{games}</b>\n"
            f"🏆 G'alabalar: <b>{wins}</b>\n"
            f"👥 Referallar: <b>{referrals}</b>",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 Bosh menyu",
                        callback_data="home",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # REFERRAL
    # -----------------------------------------------------

    if data == "ref":
        bot_info = await context.bot.get_me()

        link = (
            f"https://t.me/{bot_info.username}"
            f"?start={user.id}"
        )

        row = get_user(user.id)

        referrals = row[5] if row else 0

        await query.message.reply_text(
            "👥 <b>REFERAL TIZIMI</b>\n\n"
            f"Har bir taklif qilingan do'st uchun "
            f"<b>{REFERRAL_REWARD}</b> ⭐ beriladi.\n\n"
            f"👥 Sizning referallaringiz: <b>{referrals}</b>\n\n"
            f"🔗 Sizning havolangiz:\n"
            f"<code>{link}</code>",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 Bosh menyu",
                        callback_data="home",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # TASKS
    # -----------------------------------------------------

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
            await query.message.reply_text(
                "🎁 <b>TOPSHIRIQLAR</b>\n\n"
                "Hozircha topshiriqlar mavjud emas.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 Bosh menyu",
                            callback_data="home",
                        )
                    ]
                ]),
                parse_mode="HTML",
            )

            return

        keyboard = []

        for task_id, text, reward, url in tasks:
            keyboard.append([
                InlineKeyboardButton(
                    f"🎁 {text[:30]}",
                    callback_data=f"taskdone_{task_id}",
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "🏠 Bosh menyu",
                callback_data="home",
            )
        ])

        await query.message.reply_text(
            "🎁 <b>TOPSHIRIQLAR</b>\n\n"
            "Topshiriqni tanlang:",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # TASK DONE
    # -----------------------------------------------------

    if data.startswith("taskdone_"):
        try:
            task_id = int(
                data.split("_")[1]
            )
        except Exception:
            return

        con = db()

        cur = con.cursor()

        cur.execute("""
            SELECT text, reward, url
            FROM tasks
            WHERE id = ?
        """, (task_id,))

        task = cur.fetchone()

        if not task:
            con.close()

            await query.message.reply_text(
                "❌ Topshiriq topilmadi."
            )

            return

        text_task, reward, url = task

        cur.execute("""
            SELECT 1
            FROM task_claims
            WHERE user_id = ?
              AND task_id = ?
        """, (
            user.id,
            task_id,
        ))

        claimed = cur.fetchone()

        if claimed:
            con.close()

            await query.message.reply_text(
                "⚠️ Siz bu topshiriq uchun mukofot olgansiz."
            )

            return

        cur.execute("""
            INSERT INTO task_claims
            (user_id, task_id, created_at)
            VALUES (?, ?, ?)
        """, (
            user.id,
            task_id,
            now(),
        ))

        cur.execute("""
            UPDATE users
            SET points = points + ?
            WHERE id = ?
        """, (
            reward,
            user.id,
        ))

        con.commit()
        con.close()

        keyboard = []

        if url:
            keyboard.append([
                InlineKeyboardButton(
                    "📢 Topshiriqni ochish",
                    url=url,
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "🏠 Bosh menyu",
                callback_data="home",
            )
        ])

        await query.message.reply_text(
            "🎉 <b>Topshiriq bajarildi!</b>\n\n"
            f"⭐ Mukofot: <b>{reward}</b> Stars",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )

        await save_database()

        return

    # -----------------------------------------------------
    # RATING
    # -----------------------------------------------------

    if data == "rating":
        con = db()

        cur = con.cursor()

        cur.execute("""
            SELECT id, username, points
            FROM users
            ORDER BY points DESC
            LIMIT 10
        """)

        users = cur.fetchall()

        con.close()

        text = "🏆 <b>REYTING</b>\n\n"

        if not users:
            text += "Hali foydalanuvchilar yo'q."
        else:
            for i, (uid, username, points) in enumerate(
                users,
                start=1,
            ):
                name = (
                    f"@{username}"
                    if username
                    else str(uid)
                )

                text += (
                    f"{i}. {name} — "
                    f"<b>{points:.2f} ⭐</b>\n"
                )

        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 Bosh menyu",
                        callback_data="home",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # WITHDRAW
    # -----------------------------------------------------

    if data == "withdraw":
        row = get_user(user.id)

        points = row[2] if row else 0
        referrals = row[5] if row else 0

        if points < MIN_WITHDRAW:
            await query.message.reply_text(
                "💸 <b>YECHIB OLISH</b>\n\n"
                f"❌ Minimal yechish: <b>{MIN_WITHDRAW:.0f} ⭐</b>\n"
                f"⭐ Sizning balansingiz: <b>{points:.2f} ⭐</b>",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 Bosh menyu",
                            callback_data="home",
                        )
                    ]
                ]),
                parse_mode="HTML",
            )

            return

        if referrals < MIN_REFERRALS:
            await query.message.reply_text(
                "💸 <b>YECHIB OLISH</b>\n\n"
                f"❌ Kamida <b>{MIN_REFERRALS}</b> ta "
                "referal kerak.\n\n"
                f"👥 Sizda: <b>{referrals}</b>",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 Bosh menyu",
                            callback_data="home",
                        )
                    ]
                ]),
                parse_mode="HTML",
            )

            return

        context.user_data[
            "withdraw_amount"
        ] = points

        await query.message.reply_text(
            "💸 <b>Yechib olish so'rovi</b>\n\n"
            f"⭐ Miqdor: <b>{points:.2f} Stars</b>\n\n"
            "Telegram username yoki to'lov uchun kerakli "
            "ma'lumotni yuboring.",
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # GAMES
    # -----------------------------------------------------

    if data == "games":
        await query.message.reply_text(
            "🎮 <b>O'YINLAR</b>\n\n"
            "O'yinni tanlang:",
            reply_markup=games_menu(),
            parse_mode="HTML",
        )

        return

    if data.startswith("game_"):
        game_id = data.replace(
            "game_",
            "",
            1,
        )

        if game_id in GAMES:
            await start_game(
                query,
                context,
                game_id,
            )

        return

    # -----------------------------------------------------
    # QUIZ CHOICE
    # -----------------------------------------------------

    if data.startswith("choice_"):
        try:
            index = int(
                data.split("_")[1]
            )
        except Exception:
            return

        options = context.user_data.get(
            "choice_options",
            [],
        )

        game_data = context.user_data.get(
            "game_data"
        )

        if not game_data or index >= len(options):
            return

        answer = game_data.get(
            "answer"
        )

        selected = options[index]

        if selected == answer:
            reward = 1.5

            await change_points(
                user.id,
                reward,
            )

            await game_result(
                user.id,
                True,
            )

            await query.message.reply_text(
                "🎉 <b>To'g'ri javob!</b>\n\n"
                f"⭐ +{reward} Stars",
                parse_mode="HTML",
            )
        else:
            await game_result(
                user.id,
                False,
            )

            await query.message.reply_text(
                f"❌ Noto'g'ri.\n\n"
                f"To'g'ri javob: <b>{answer}</b>",
                parse_mode="HTML",
            )

        context.user_data.pop(
            "game",
            None,
        )

        context.user_data.pop(
            "game_data",
            None,
        )

        await save_database()

        return

    # -----------------------------------------------------
    # LOGIC
    # -----------------------------------------------------

    if data.startswith("logic_"):
        try:
            index = int(
                data.split("_")[1]
            )
        except Exception:
            return

        options = context.user_data.get(
            "logic_options",
            [],
        )

        game_data = context.user_data.get(
            "game_data"
        )

        if not game_data or index >= len(options):
            return

        selected = options[index]

        answer = game_data.get(
            "answer"
        )

        if selected == answer:
            reward = 1.5

            await change_points(
                user.id,
                reward,
            )

            await game_result(
                user.id,
                True,
            )

            text = (
                "🎉 <b>To'g'ri!</b>\n\n"
                f"⭐ +{reward} Stars"
            )
        else:
            await game_result(
                user.id,
                False,
            )

            text = (
                "❌ Noto'g'ri.\n\n"
                f"To'g'ri javob: <b>{answer}</b>"
            )

        context.user_data.pop(
            "game",
            None,
        )

        context.user_data.pop(
            "game_data",
            None,
        )

        await query.message.reply_text(
            text,
            parse_mode="HTML",
        )

        await save_database()

        return

    # -----------------------------------------------------
    # TARGET
    # -----------------------------------------------------

    if data.startswith("target_"):
        try:
            selected = int(
                data.split("_")[1]
            )
        except Exception:
            return

        game_data = context.user_data.get(
            "game_data"
        )

        if not game_data:
            return

        answer = game_data.get(
            "answer"
        )

        if selected == answer:
            reward = 2.0

            await change_points(
                user.id,
                reward,
            )

            await game_result(
                user.id,
                True,
            )

            text = (
                "🎯 <b>Nishonga tegdingiz!</b>\n\n"
                f"⭐ +{reward} Stars"
            )
        else:
            await game_result(
                user.id,
                False,
            )

            text = (
                "❌ Noto'g'ri.\n\n"
                f"To'g'ri raqam: <b>{answer}</b>"
            )

        context.user_data.pop(
            "game",
            None,
        )

        context.user_data.pop(
            "game_data",
            None,
        )

        await query.message.reply_text(
            text,
            parse_mode="HTML",
        )

        await save_database()

        return

    # -----------------------------------------------------
    # COLOR
    # -----------------------------------------------------

    if data.startswith("color_"):
        try:
            index = int(
                data.split("_")[1]
            )
        except Exception:
            return

        options = context.user_data.get(
            "color_options",
            [],
        )

        game_data = context.user_data.get(
            "game_data"
        )

        if not game_data or index >= len(options):
            return

        selected = options[index]

        answer = game_data.get(
            "answer"
        )

        if selected.lower() == answer.lower():
            reward = 1.2

            await change_points(
                user.id,
                reward,
            )

            await game_result(
                user.id,
                True,
            )

            text = (
                "🎨 <b>To'g'ri!</b>\n\n"
                f"⭐ +{reward} Stars"
            )
        else:
            await game_result(
                user.id,
                False,
            )

            text = (
                "❌ Noto'g'ri.\n\n"
                f"To'g'ri javob: <b>{answer}</b>"
            )

        context.user_data.pop(
            "game",
            None,
        )

        context.user_data.pop(
            "game_data",
            None,
        )

        await query.message.reply_text(
            text,
            parse_mode="HTML",
        )

        await save_database()

        return

    # -----------------------------------------------------
    # KNOWLEDGE
    # -----------------------------------------------------

    if data.startswith("knowledge_"):
        try:
            index = int(
                data.split("_")[1]
            )
        except Exception:
            return

        options = context.user_data.get(
            "knowledge_options",
            [],
        )

        game_data = context.user_data.get(
            "game_data"
        )

        if not game_data or index >= len(options):
            return

        selected = options[index]

        answer = game_data.get(
            "answer"
        )

        if selected == answer:
            reward = 1.5

            await change_points(
                user.id,
                reward,
            )

            await game_result(
                user.id,
                True,
            )

            text = (
                "📚 <b>To'g'ri!</b>\n\n"
                f"⭐ +{reward} Stars"
            )
        else:
            await game_result(
                user.id,
                False,
            )

            text = (
                "❌ Noto'g'ri.\n\n"
                f"To'g'ri javob: <b>{answer}</b>"
            )

        context.user_data.pop(
            "game",
            None,
        )

        context.user_data.pop(
            "game_data",
            None,
        )

        await query.message.reply_text(
            text,
            parse_mode="HTML",
        )

        await save_database()

        return

    # -----------------------------------------------------
    # CHOICE ANSWER
    # -----------------------------------------------------

    if data.startswith("choiceanswer_"):
        selected = data.replace(
            "choiceanswer_",
            "",
            1,
        )

        answer = context.user_data.get(
            "choice_answer"
        )

        if not answer:
            return

        if selected == answer:
            reward = 1.0

            await change_points(
                user.id,
                reward,
            )

            await game_result(
                user.id,
                True,
            )

            text = (
                "🎯 <b>To'g'ri!</b>\n\n"
                f"⭐ +{reward} Stars"
            )
        else:
            await game_result(
                user.id,
                False,
            )

            text = "❌ Noto'g'ri tanlov."

        context.user_data.pop(
            "game",
            None,
        )

        context.user_data.pop(
            "game_data",
            None,
        )

        context.user_data.pop(
            "choice_answer",
            None,
        )

        await query.message.reply_text(
            text,
            parse_mode="HTML",
        )

        await save_database()

        return

    # -----------------------------------------------------
    # ADMIN PANEL
    # -----------------------------------------------------

    if data == "admin":
        if user.id != ADMIN_ID:
            await query.message.reply_text(
                "❌ Siz admin emassiz."
            )
            return

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📊 STATISTIKA",
                    callback_data="admin_stats",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 FOYDALANUVCHILAR",
                    callback_data="admin_users",
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 XABAR YUBORISH",
                    callback_data="admin_broadcast",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎁 TOPSHIRIQ QO'SHISH",
                    callback_data="admin_addtask",
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 TOPSHIRIQLAR",
                    callback_data="admin_tasks",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Bosh menyu",
                    callback_data="home",
                )
            ],
        ])

        await query.message.reply_text(
            "⚙️ <b>ADMIN PANEL</b>\n\n"
            "Kerakli bo'limni tanlang:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # ADMIN STATS
    # -----------------------------------------------------

    if data == "admin_stats":
        if user.id != ADMIN_ID:
            return

        con = db()
        cur = con.cursor()

        cur.execute("""
            SELECT COUNT(*)
            FROM users
        """)
        current_users = cur.fetchone()[0]

        cur.execute("""
            SELECT total_users
            FROM bot_stats
            WHERE id = 1
        """)
        row = cur.fetchone()

        total_since_start = (
            row[0]
            if row
            else current_users
        )

        cur.execute("""
            SELECT COALESCE(SUM(points), 0)
            FROM users
        """)
        total_points = cur.fetchone()[0]

        cur.execute("""
            SELECT COALESCE(SUM(referrals), 0)
            FROM users
        """)
        total_refs = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM withdrawals
            WHERE status = 'pending'
        """)
        pending_withdrawals = cur.fetchone()[0]

        con.close()

        try:
            sponsor_count = (
                await context.bot.get_chat_member_count(
                    SPONSOR_CHANNEL
                )
            )
        except Exception:
            sponsor_count = 0

        active = await sponsor_is_active()

        await query.message.reply_text(
            "📊 <b>BOT STATISTIKASI</b>\n\n"
            f"👥 Hozirgi foydalanuvchilar: "
            f"<b>{format_count(current_users)}</b>\n"
            f"📈 Bot ishlagandan beri: "
            f"<b>{format_count(total_since_start)}</b>\n"
            f"⭐ Jami Stars: <b>{total_points:.2f}</b>\n"
            f"👥 Jami referallar: "
            f"<b>{format_count(total_refs)}</b>\n"
            f"💸 Kutilayotgan yechishlar: "
            f"<b>{pending_withdrawals}</b>\n\n"
            f"📢 Homiy kanal: "
            f"<b>{format_count(sponsor_count)}</b>\n"
            f"🔢 Limit: "
            f"<b>{format_count(SPONSOR_LIMIT)}</b>\n"
            f"📌 Holat: "
            f"<b>{'Faol' if active else 'O‘chirilgan'}</b>",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Admin panel",
                        callback_data="admin",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # ADMIN USERS
    # -----------------------------------------------------

    if data == "admin_users":
        if user.id != ADMIN_ID:
            return

        con = db()
        cur = con.cursor()

        cur.execute("""
            SELECT
                id,
                username,
                points,
                referrals
            FROM users
            ORDER BY id DESC
            LIMIT ?
        """, (PAGE_SIZE,))

        users = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*)
            FROM users
        """)

        total = cur.fetchone()[0]

        con.close()

        text = (
            "👥 <b>FOYDALANUVCHILAR</b>\n\n"
            f"Jami: <b>{format_count(total)}</b>\n\n"
        )

        for uid, username, points, referrals in users:
            name = (
                f"@{username}"
                if username
                else str(uid)
            )

            text += (
                f"🆔 {uid} — {name}\n"
                f"⭐ {points:.2f} | "
                f"👥 {referrals}\n\n"
            )

        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Admin panel",
                        callback_data="admin",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # ADMIN BROADCAST
    # -----------------------------------------------------

    if data == "admin_broadcast":
        if user.id != ADMIN_ID:
            return

        context.user_data[
            "admin_action"
        ] = "broadcast"

        await query.message.reply_text(
            "📢 <b>Xabar yuborish</b>\n\n"
            "Barcha foydalanuvchilarga yubormoqchi "
            "bo'lgan xabaringizni yozing.",
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # ADMIN ADD TASK
    # -----------------------------------------------------

    if data == "admin_addtask":
        if user.id != ADMIN_ID:
            return

        context.user_data[
            "admin_action"
        ] = "addtask"

        await query.message.reply_text(
            "🎁 <b>Topshiriq qo'shish</b>\n\n"
            "Quyidagi formatda yuboring:\n\n"
            "<code>Matn | Mukofot | URL</code>\n\n"
            "Masalan:\n"
            "<code>Kanalga obuna bo'ling | 5 | https://t.me/example</code>",
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # ADMIN TASKS
    # -----------------------------------------------------

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

        tasks = cur.fetchall()

        con.close()

        if not tasks:
            text = (
                "📋 <b>TOPSHIRIQLAR</b>\n\n"
                "Topshiriqlar yo'q."
            )
        else:
            text = "📋 <b>TOPSHIRIQLAR</b>\n\n"

            for task_id, task_text, reward, url in tasks:
                text += (
                    f"#{task_id} — {task_text}\n"
                    f"⭐ {reward} | {url}\n\n"
                )

        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Admin panel",
                        callback_data="admin",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return


# =========================================================
# TEXT ROUTER
# =========================================================

async def text_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    if not user:
        return

    text = update.message.text.strip()

    # -----------------------------------------------------
    # ADMIN ACTIONS
    # -----------------------------------------------------

    if (
        user.id == ADMIN_ID
        and context.user_data.get(
            "admin_action"
        )
    ):

        action = context.user_data.get(
            "admin_action"
        )

        # -----------------------------------------------
        # BROADCAST
        # -----------------------------------------------

        if action == "broadcast":
            context.user_data.pop(
                "admin_action",
                None,
            )

            con = db()

            cur = con.cursor()

            cur.execute("""
                SELECT id
                FROM users
                WHERE blocked = 0
            """)

            users = [
                row[0]
                for row in cur.fetchall()
            ]

            con.close()

            sent = 0
            failed = 0

            for uid in users:
                try:
                    await context.bot.send_message(
                        uid,
                        text,
                    )

                    sent += 1

                    await asyncio.sleep(
                        0.05
                    )

                except Forbidden:
                    failed += 1

                    con = db()

                    con.execute("""
                        UPDATE users
                        SET blocked = 1
                        WHERE id = ?
                    """, (uid,))

                    con.commit()
                    con.close()

                except RetryAfter as e:
                    await asyncio.sleep(
                        e.retry_after
                    )

                    try:
                        await context.bot.send_message(
                            uid,
                            text,
                        )

                        sent += 1

                    except Exception:
                        failed += 1

                except Exception:
                    failed += 1

            await update.message.reply_text(
                "📢 <b>Xabar yuborildi!</b>\n\n"
                f"✅ Yuborildi: <b>{sent}</b>\n"
                f"❌ Xato: <b>{failed}</b>",
                parse_mode="HTML",
            )

            return

        # -----------------------------------------------
        # ADD TASK
        # -----------------------------------------------

        if action == "addtask":
            context.user_data.pop(
                "admin_action",
                None,
            )

            parts = [
                x.strip()
                for x in text.split("|")
            ]

            if len(parts) != 3:
                await update.message.reply_text(
                    "❌ Format noto'g'ri.\n\n"
                    "To'g'ri format:\n"
                    "<code>Matn | Mukofot | URL</code>",
                    parse_mode="HTML",
                )
                return

            task_text = parts[0]

            try:
                reward = float(parts[1])
            except Exception:
                await update.message.reply_text(
                    "❌ Mukofot raqam bo'lishi kerak."
                )
                return

            url = parts[2]

            con = db()

            con.execute("""
                INSERT INTO tasks
                (text, reward, url)
                VALUES (?, ?, ?)
            """, (
                task_text,
                reward,
                url,
            ))

            con.commit()
            con.close()

            await update.message.reply_text(
                "✅ <b>Topshiriq qo'shildi!</b>\n\n"
                f"🎁 {task_text}\n"
                f"⭐ {reward} Stars\n"
                f"🔗 {url}",
                parse_mode="HTML",
            )

            await save_database()

            return

    # -----------------------------------------------------
    # GAME ANSWERS
    # -----------------------------------------------------

    handled = await process_game_answer(
        update,
        context,
        text,
    )

    if handled:
        return

    # -----------------------------------------------------
    # WITHDRAW INFORMATION
    # -----------------------------------------------------

    if context.user_data.get(
        "withdraw_amount"
    ):

        amount = context.user_data.pop(
            "withdraw_amount"
        )

        row = get_user(user.id)

        if not row:
            return

        balance = row[2]

        if balance < MIN_WITHDRAW:
            await update.message.reply_text(
                "❌ Balansingiz yetarli emas."
            )
            return

        con = db()

        cur = con.cursor()

        cur.execute("""
            INSERT INTO withdrawals
            (user_id, amount, status, created_at)
            VALUES (?, ?, 'pending', ?)
        """, (
            user.id,
            amount,
            now(),
        ))

        withdrawal_id = cur.lastrowid

        cur.execute("""
            UPDATE users
            SET points = 0
            WHERE id = ?
        """, (user.id,))

        con.commit()
        con.close()

        await update.message.reply_text(
            "✅ <b>So'rovingiz muvaffaqiyatli qabul qilindi!</b>\n\n"
            f"⭐ Miqdor: <b>{amount:.2f} Stars</b>\n\n"
            "⏳ 24 soat ichida ko'rib chiqilib, "
            "to'lov amalga oshiriladi.",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                ADMIN_ID,
                "💸 <b>Yangi yechish so'rovi!</b>\n\n"
                f"🆔 So'rov: <code>{withdrawal_id}</code>\n"
                f"👤 User ID: <code>{user.id}</code>\n"
                f"👤 Username: @{user.username or 'yoq'}\n"
                f"⭐ Miqdor: <b>{amount:.2f}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ TASDIQLASH",
                            callback_data=f"approve_{withdrawal_id}",
                        ),
                        InlineKeyboardButton(
                            "❌ RAD ETISH",
                            callback_data=f"reject_{withdrawal_id}",
                        ),
                    ]
                ]),
            )
        except Exception:
            pass

        await save_database()

        return


# =========================================================
# APPROVE / REJECT WITHDRAW
# =========================================================

async def handle_withdraw_admin(
    query,
    context,
    action,
    withdrawal_id,
):
    user = query.from_user

    if user.id != ADMIN_ID:
        await query.message.reply_text(
            "❌ Ruxsat yo'q."
        )
        return

    con = db()

    cur = con.cursor()

    cur.execute("""
        SELECT user_id, amount, status
        FROM withdrawals
        WHERE id = ?
    """, (withdrawal_id,))

    row = cur.fetchone()

    if not row:
        con.close()

        await query.message.reply_text(
            "❌ So'rov topilmadi."
        )

        return

    target_user_id, amount, status = row

    if status != "pending":
        con.close()

        await query.message.reply_text(
            "⚠️ Bu so'rov allaqachon ko'rib chiqilgan."
        )

        return

    if action == "approve":
        cur.execute("""
            UPDATE withdrawals
            SET status = 'approved'
            WHERE id = ?
        """, (withdrawal_id,))

        message = (
            "✅ <b>Yechish so'rovingiz tasdiqlandi!</b>\n\n"
            f"⭐ Miqdor: <b>{amount:.2f} Stars</b>"
        )

    else:
        cur.execute("""
            UPDATE withdrawals
            SET status = 'rejected'
            WHERE id = ?
        """, (withdrawal_id,))

        cur.execute("""
            UPDATE users
            SET points = points + ?
            WHERE id = ?
        """, (
            amount,
            target_user_id,
        ))

        message = (
            "❌ <b>Yechish so'rovingiz rad etildi.</b>\n\n"
            f"⭐ {amount:.2f} Stars balansingizga qaytarildi."
        )

    con.commit()
    con.close()

    await query.message.reply_text(
        "✅ So'rov holati yangilandi."
    )

    try:
        await context.bot.send_message(
            target_user_id,
            message,
            parse_mode="HTML",
        )
    except Exception:
        pass

    await save_database()


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context,
):
    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# =========================================================
# POST INIT
# =========================================================

async def post_init(
    application: Application,
):
    init_db()

    await update_bot_user_count(
        application.bot
    )

    await check_sponsor_limit(
        application.bot
    )

    application.create_task(
        periodic_database_backup()
    )

    application.create_task(
        periodic_sponsor_check(
            application.bot
        )
    )

    await save_database()

    try:
        total = await get_total_users()

        logger.info(
            "Bot started. Users: %s",
            total,
        )
    except Exception:
        pass


# =========================================================
# POST SHUTDOWN
# =========================================================

async def post_shutdown(
    application: Application,
):
    try:
        await save_database()
    except Exception as e:
        logger.error(
            "Shutdown save error: %s",
            e,
        )


# =========================================================
# MAIN
# =========================================================

def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi!"
        )

    if not ADMIN_ID:
        logger.warning(
            "ADMIN_ID topilmadi!"
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
            start,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            menu
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_router,
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
