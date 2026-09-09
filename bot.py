
import os
import sqlite3
import logging
import random
import asyncio
import subprocess
from datetime import datetime, timezone

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

# ==========================================================
# SOZLAMALAR
# ==========================================================

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "zerikdim.db"

SPONSOR_CHANNEL = "@SALIKH_PUBG"
SPONSOR_URL = "https://t.me/SALIKH_PUBG"
SPONSOR_LIMIT = 750

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
    level=logging.INFO,
)

log = logging.getLogger("zerikdim")

save_lock = asyncio.Lock()


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

QUIZ = [
    (
        "O‘zbekiston Konstitutsiyasi qaysi yilda qabul qilingan?",
        ["1991", "1992", "1993", "1994"],
        1,
    ),
    (
        "1 dan 20 gacha bo‘lgan sonlar yig‘indisi nechaga teng?",
        ["190", "200", "210", "220"],
        2,
    ),
    (
        "Yer Quyosh atrofini taxminan necha kunda aylanadi?",
        ["180", "265", "365", "400"],
        2,
    ),
    (
        "Agar 3 ta qalam 15 000 so‘m bo‘lsa, 7 ta qalam qancha?",
        ["25 000", "30 000", "35 000", "40 000"],
        2,
    ),
    (
        "Eng katta okean qaysi?",
        ["Atlantika", "Hind", "Tinch", "Shimoliy Muz"],
        2,
    ),
    (
        "2^5 nechaga teng?",
        ["16", "24", "32", "64"],
        2,
    ),
    (
        "1 kilometr necha metr?",
        ["100", "500", "1000", "1500"],
        2,
    ),
    (
        "12 × 8 − 17 nechaga teng?",
        ["69", "79", "89", "97"],
        1,
    ),
]

LOGIC_QUESTIONS = [
    (
        "Ketma-ketlikni davom ettir: 2, 6, 12, 20, 30, ?",
        ["36", "40", "42", "44"],
        2,
    ),
    (
        "5, 10, 20, 40, ?",
        ["60", "70", "80", "90"],
        2,
    ),
    (
        "1, 4, 9, 16, 25, ?",
        ["30", "32", "36", "49"],
        2,
    ),
    (
        "100, 90, 81, 73, ?",
        ["64", "66", "67", "68"],
        1,
    ),
    (
        "3, 9, 27, 81, ?",
        ["162", "243", "324", "729"],
        1,
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
        0,
    ),
    (
        "Suvning kimyoviy formulasi?",
        ["CO2", "H2O", "O2", "NaCl"],
        1,
    ),
    (
        "Python dasturlash tilining belgisi ko‘proq nima bilan bog‘liq?",
        ["Ilon", "Qush", "Sher", "Baliq"],
        0,
    ),
    (
        "Bir sutkada nechta soat bor?",
        ["12", "18", "24", "48"],
        2,
    ),
]


# ==========================================================
# YORDAMCHI
# ==========================================================

def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def format_count(number):
    return f"{int(number):,}".replace(",", " ")


def normalize_channel(channel):
    channel = str(channel or "").strip()

    if not channel:
        return ""

    channel = channel.replace("https://t.me/", "")
    channel = channel.replace("http://t.me/", "")
    channel = channel.split("/")[0]
    channel = channel.strip()

    if not channel.startswith("@"):
        channel = "@" + channel

    return channel


def channel_url(channel):
    channel = normalize_channel(channel)
    return f"https://t.me/{channel.lstrip('@')}"


# ==========================================================
# DATABASE
# ==========================================================

def ensure_column(cur, table, column, definition):
    cur.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cur.fetchall()}

    if column not in columns:
        cur.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
        log.info(
            "Migration: %s.%s qo‘shildi",
            table,
            column,
        )


def init_db():
    con = db()
    cur = con.cursor()

    # ------------------------------------------------------
    # USERS
    # ------------------------------------------------------

    cur.execute(
        """
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
        """
    )

    user_migrations = {
        "username": "TEXT",
        "points": "REAL DEFAULT 0",
        "games": "INTEGER DEFAULT 0",
        "wins": "INTEGER DEFAULT 0",
        "referrals": "INTEGER DEFAULT 0",
        "referred_by": "INTEGER",
        "last_seen": "TEXT",
        "blocked": "INTEGER DEFAULT 0",
        "referral_rewarded": "INTEGER DEFAULT 0",
    }

    for column, definition in user_migrations.items():
        try:
            ensure_column(
                cur,
                "users",
                column,
                definition,
            )
        except Exception as e:
            log.error(
                "users.%s migration: %s",
                column,
                e,
            )

    # ------------------------------------------------------
    # WITHDRAWALS
    # ------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """
    )

    withdrawal_migrations = {
        "user_id": "INTEGER",
        "username": "TEXT",
        "amount": "REAL",
        "status": "TEXT DEFAULT 'pending'",
        "created_at": "TEXT",
    }

    for column, definition in withdrawal_migrations.items():
        try:
            ensure_column(
                cur,
                "withdrawals",
                column,
                definition,
            )
        except Exception as e:
            log.error(
                "withdrawals.%s migration: %s",
                column,
                e,
            )

    # ------------------------------------------------------
    # TASKS
    # ------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            reward REAL DEFAULT 5,
            url TEXT,
            channel TEXT
        )
        """
    )

    ensure_column(
        cur,
        "tasks",
        "text",
        "TEXT",
    )

    ensure_column(
        cur,
        "tasks",
        "reward",
        "REAL DEFAULT 5",
    )

    ensure_column(
        cur,
        "tasks",
        "url",
        "TEXT",
    )

    ensure_column(
        cur,
        "tasks",
        "channel",
        "TEXT",
    )

    # Eski url -> channel
    cur.execute(
        "PRAGMA table_info(tasks)"
    )

    task_columns = {
        row[1]
        for row in cur.fetchall()
    }

    if "url" in task_columns and "channel" in task_columns:

        rows = cur.execute(
            """
            SELECT id, url, channel
            FROM tasks
            WHERE channel IS NULL
               OR TRIM(channel)=''
            """
        ).fetchall()

        for row in rows:

            url = row["url"]

            if not url:
                continue

            channel = normalize_channel(url)

            if channel:
                cur.execute(
                    """
                    UPDATE tasks
                    SET channel=?
                    WHERE id=?
                    """,
                    (
                        channel,
                        row["id"],
                    ),
                )

    # ------------------------------------------------------
    # TASK CLAIMS
    # ------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_claims(
            user_id INTEGER,
            task_id INTEGER,
            created_at TEXT,
            claimed_at TEXT,
            PRIMARY KEY(user_id, task_id)
        )
        """
    )

    ensure_column(
        cur,
        "task_claims",
        "created_at",
        "TEXT",
    )

    ensure_column(
        cur,
        "task_claims",
        "claimed_at",
        "TEXT",
    )

    # ------------------------------------------------------
    # BOT STATS
    # ------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_stats(
            id INTEGER PRIMARY KEY CHECK(id=1),
            started_at TEXT,
            total_users INTEGER DEFAULT 0
        )
        """
    )

    # ------------------------------------------------------
    # SPONSOR SETTINGS
    # ------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sponsor_settings(
            id INTEGER PRIMARY KEY CHECK(id=1),
            active INTEGER DEFAULT 1,
            disabled_at TEXT
        )
        """
    )

    cur.execute(
        """
        SELECT id
        FROM sponsor_settings
        WHERE id=1
        """
    )

    if not cur.fetchone():

        cur.execute(
            """
            INSERT INTO sponsor_settings
            (id, active, disabled_at)
            VALUES(1,1,NULL)
            """
        )

    # ------------------------------------------------------
    # SPONSORS
    # ------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sponsors(
            channel TEXT PRIMARY KEY,
            url TEXT
        )
        """
    )

    ensure_column(
        cur,
        "sponsors",
        "url",
        "TEXT",
    )

    cur.execute(
        """
        INSERT OR IGNORE INTO sponsors(channel,url)
        VALUES(?,?)
        """,
        (
            SPONSOR_CHANNEL,
            SPONSOR_URL,
        ),
    )

    # ------------------------------------------------------
    # STATS
    # ------------------------------------------------------

    current_users = cur.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    stats = cur.execute(
        """
        SELECT total_users
        FROM bot_stats
        WHERE id=1
        """
    ).fetchone()

    if not stats:

        cur.execute(
            """
            INSERT INTO bot_stats
            (id,started_at,total_users)
            VALUES(1,?,?)
            """,
            (
                now(),
                current_users,
            ),
        )

    else:

        old_total = int(stats["total_users"] or 0)

        if current_users > old_total:

            cur.execute(
                """
                UPDATE bot_stats
                SET total_users=?
                WHERE id=1
                """,
                (
                    current_users,
                ),
            )

    # ------------------------------------------------------
    # DEFAULT TASK
    # ------------------------------------------------------

    cur.execute(
        """
        SELECT id
        FROM tasks
        WHERE channel=?
        LIMIT 1
        """,
        (
            SPONSOR_CHANNEL,
        ),
    )

    if not cur.fetchone():

        cur.execute(
            """
            INSERT INTO tasks
            (text,reward,url,channel)
            VALUES(?,?,?,?)
            """,
            (
                "Homiy kanalga obuna bo‘ling",
                TASK_REWARD,
                SPONSOR_URL,
                SPONSOR_CHANNEL,
            ),
        )

    con.commit()
    con.close()

    log.info(
        "✅ DATABASE TAYYOR. USERLAR: %s",
        current_users,
    )


# ==========================================================
# USER
# ==========================================================

def add_user_sync(
    user_id,
    username=None,
    ref=None,
):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,),
    )

    exists = cur.fetchone()

    created = False

    if not exists:

        created = True

        valid_ref = (
            ref
            if ref and ref != user_id
            else None
        )

        cur.execute(
            """
            INSERT INTO users(
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
            VALUES(
                ?,
                ?,
                0,
                0,
                0,
                0,
                ?,
                ?,
                0,
                0
            )
            """,
            (
                user_id,
                username,
                valid_ref,
                now(),
            ),
        )

        cur.execute(
            """
            UPDATE bot_stats
            SET total_users=total_users+1
            WHERE id=1
            """
        )

        # Referral reward
        if valid_ref:

            ref_exists = cur.execute(
                "SELECT id FROM users WHERE id=?",
                (valid_ref,),
            ).fetchone()

            if ref_exists:

                cur.execute(
                    """
                    UPDATE users
                    SET points=points+?,
                        referrals=referrals+1
                    WHERE id=?
                    """,
                    (
                        REFERRAL_REWARD,
                        valid_ref,
                    ),
                )

                cur.execute(
                    """
                    UPDATE users
                    SET referral_rewarded=1
                    WHERE id=?
                    """,
                    (
                        user_id,
                    ),
                )

    else:

        cur.execute(
            """
            UPDATE users
            SET username=?,
                last_seen=?,
                blocked=0
            WHERE id=?
            """,
            (
                username,
                now(),
                user_id,
            ),
        )

    con.commit()
    con.close()

    return created


async def add_user(
    user_id,
    username=None,
    ref=None,
):
    return await asyncio.to_thread(
        add_user_sync,
        user_id,
        username,
        ref,
    )


def get_user(user_id):

    con = db()

    row = con.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (
            user_id,
        ),
    ).fetchone()

    con.close()

    return row


def change_points_sync(
    user_id,
    amount,
):
    con = db()

    con.execute(
        """
        UPDATE users
        SET points=MAX(0,points+?)
        WHERE id=?
        """,
        (
            amount,
            user_id,
        ),
    )

    con.commit()
    con.close()


async def change_points(
    user_id,
    amount,
):
    await asyncio.to_thread(
        change_points_sync,
        user_id,
        amount,
    )


def game_result_sync(
    user_id,
    won,
):
    con = db()

    con.execute(
        """
        UPDATE users
        SET games=games+1,
            wins=wins+?
        WHERE id=?
        """,
        (
            1 if won else 0,
            user_id,
        ),
    )

    con.commit()
    con.close()


async def game_result(
    user_id,
    won,
):
    await asyncio.to_thread(
        game_result_sync,
        user_id,
        won,
    )


# ==========================================================
# USER COUNT
# ==========================================================

def get_total_users_sync():

    con = db()

    row = con.execute(
        """
        SELECT total_users
        FROM bot_stats
        WHERE id=1
        """
    ).fetchone()

    if row:
        total = int(row["total_users"] or 0)
    else:
        total = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

    con.close()

    return total


async def get_total_users():
    return await asyncio.to_thread(
        get_total_users_sync
    )


async def update_bot_user_count(bot):

    try:

        await bot.set_my_short_description(
            short_description=(
                "⭐ Stars ishlang va o‘yinlarda qatnashing!"
            )
        )

    except TelegramError as e:

        log.error(
            "Bot description error: %s",
            e,
        )


# ==========================================================
# SPONSOR DATABASE
# ==========================================================

def get_sponsors():

    con = db()

    rows = con.execute(
        """
        SELECT channel,url
        FROM sponsors
        ORDER BY channel
        """
    ).fetchall()

    con.close()

    return rows


def add_sponsor(channel):

    channel = normalize_channel(channel)

    if not channel:
        return False

    url = channel_url(channel)

    con = db()

    try:

        con.execute(
            """
            INSERT INTO sponsors(channel,url)
            VALUES(?,?)
            """,
            (
                channel,
                url,
            ),
        )

        con.commit()
        result = True

    except sqlite3.IntegrityError:

        result = False

    con.close()

    return result


def delete_sponsor(channel):

    channel = normalize_channel(channel)

    if channel == normalize_channel(SPONSOR_CHANNEL):
        return False

    con = db()

    cur = con.cursor()

    cur.execute(
        """
        DELETE FROM sponsors
        WHERE channel=?
        """,
        (
            channel,
        ),
    )

    deleted = cur.rowcount > 0

    con.commit()
    con.close()

    return deleted


# ==========================================================
# HOMIY HOLATI
# ==========================================================

def sponsor_is_active_sync():

    con = db()

    row = con.execute(
        """
        SELECT active
        FROM sponsor_settings
        WHERE id=1
        """
    ).fetchone()

    con.close()

    if not row:
        return True

    return bool(row["active"])


async def sponsor_is_active():

    return await asyncio.to_thread(
        sponsor_is_active_sync
    )


def disable_sponsor_sync():

    con = db()

    con.execute(
        """
        UPDATE sponsor_settings
        SET active=0,
            disabled_at=?
        WHERE id=1
        """,
        (
            now(),
        ),
    )

    con.commit()
    con.close()


async def disable_sponsor():

    await asyncio.to_thread(
        disable_sponsor_sync
    )

    log.info(
        "✅ HOMIY MAJBURIY OBUNASI O‘CHIRILDI"
    )


async def check_sponsor_limit(bot):

    try:

        if not await sponsor_is_active():
            return

        count = await bot.get_chat_member_count(
            SPONSOR_CHANNEL
        )

        log.info(
            "Homiya: %s / %s",
            count,
            SPONSOR_LIMIT,
        )

        if count >= SPONSOR_LIMIT:

            await disable_sponsor()

            if ADMIN_ID:

                try:

                    await bot.send_message(
                        ADMIN_ID,
                        (
                            "🎉 <b>HOMIY LIMITIGA YETDI!</b>\n\n"
                            f"📢 {SPONSOR_CHANNEL}\n"
                            f"👥 A'zolar: <b>{format_count(count)}</b>\n"
                            f"🎯 Limit: <b>{SPONSOR_LIMIT}</b>\n\n"
                            "✅ Majburiy obuna o‘chirildi."
                        ),
                        parse_mode="HTML",
                    )

                except TelegramError:
                    pass

    except TelegramError as e:

        log.error(
            "Sponsor limit error: %s",
            e,
        )


async def periodic_sponsor_check(bot):

    await asyncio.sleep(10)

    while True:

        try:

            await check_sponsor_limit(bot)

            await asyncio.sleep(60)

        except asyncio.CancelledError:

            break

        except Exception as e:

            log.error(
                "Sponsor periodic error: %s",
                e,
            )

            await asyncio.sleep(60)


# ==========================================================
# MAJBURIY OBUNA
# ==========================================================

async def subscribed(
    bot,
    user_id,
):

    if not await sponsor_is_active():
        return True

    sponsors = get_sponsors()

    if not sponsors:
        return True

    for sponsor in sponsors:

        channel = sponsor["channel"]

        try:

            member = await bot.get_chat_member(
                channel,
                user_id,
            )

            if member.status not in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            ):
                return False

        except TelegramError as e:

            log.error(
                "Obuna tekshirish xatosi %s: %s",
                channel,
                e,
            )

            return False

    return True


async def require_subscription(
    update,
    context,
):

    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        return True

    if not await sponsor_is_active():
        return True

    if await subscribed(
        context.bot,
        user_id,
    ):
        return True

    sponsors = get_sponsors()

    keyboard = []

    for sponsor in sponsors:

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📢 {sponsor['channel']}",
                    url=sponsor["url"],
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "✅ Tekshirish",
                callback_data="check_sub",
            )
        ]
    )

    text = (
        "🔒 <b>Botdan foydalanish uchun "
        "homiy kanallarga obuna bo‘ling.</b>\n\n"
        "Obuna bo‘lgach «Tekshirish» tugmasini bosing."
    )

    if update.callback_query:

        await update.callback_query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif update.message:

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    return False


# ==========================================================
# MAIN MENU
# ==========================================================

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
                "🎮 O‘YINLAR",
                callback_data="other_games",
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

        keyboard.append(
            [
                InlineKeyboardButton(
                    "⚙️ ADMIN PANEL",
                    callback_data="admin",
                )
            ]
        )

    return InlineKeyboardMarkup(keyboard)


# ==========================================================
# START
# ==========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

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
        ref,
    )

    await check_sponsor_limit(
        context.bot
    )

    if not await require_subscription(
        update,
        context,
    ):
        return

    admin = user.id == ADMIN_ID

    if admin:

        total_users = await get_total_users()

        text = (
            "👋 <b>Zerikdim Botga xush kelibsiz!</b>\n\n"
            "⭐ Stars ishlang, topshiriqlar bajaring "
            "va do‘stlaringizni taklif qiling.\n\n"
            f"👥 Jami foydalanuvchilar: "
            f"<b>{format_count(total_users)}</b>\n\n"
            "👇 Kerakli bo‘limni tanlang:"
        )

    else:

        text = (
            "👋 <b>Zerikdim Botga xush kelibsiz!</b>\n\n"
            "⭐ Stars ishlang, topshiriqlar bajaring "
            "va do‘stlaringizni taklif qiling.\n\n"
            "👇 Kerakli bo‘limni tanlang:"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(admin),
    )


# ==========================================================
# GAMES MENU
# ==========================================================

def games_menu():

    keyboard = []

    for i in range(0, len(GAMES), 2):

        row = []

        name1, code1 = GAMES[i]

        row.append(
            InlineKeyboardButton(
                name1,
                callback_data=f"game_{code1}",
            )
        )

        if i + 1 < len(GAMES):

            name2, code2 = GAMES[i + 1]

            row.append(
                InlineKeyboardButton(
                    name2,
                    callback_data=f"game_{code2}",
                )
            )

        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ Bosh menyu",
                callback_data="home",
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


# ==========================================================
# GAME COOLDOWN
# ==========================================================

def can_play(context, user_id):

    key = f"game_last_{user_id}"

    last = context.user_data.get(key)

    if last is None:
        return True, 0

    elapsed = (
        asyncio.get_event_loop().time()
        - last
    )

    if elapsed < GAME_COOLDOWN:

        return (
            False,
            int(GAME_COOLDOWN - elapsed),
        )

    return True, 0


def mark_game(context, user_id):

    context.user_data[
        f"game_last_{user_id}"
    ] = asyncio.get_event_loop().time()


# ==========================================================
# START GAME
# ==========================================================

async def start_game(
    update,
    context,
    game,
):

    user_id = update.effective_user.id

    allowed, wait = can_play(
        context,
        user_id,
    )

    if not allowed:

        await update.callback_query.message.reply_text(
            f"⏳ Keyingi o‘yinga "
            f"<b>{wait} soniya</b> qoldi.",
            parse_mode="HTML",
        )

        return

    mark_game(
        context,
        user_id,
    )

    q = update.callback_query

    # ------------------------------------------------------
    # QUIZ
    # ------------------------------------------------------

    if game == "quiz":

        question, answers, correct = random.choice(
            QUIZ
        )

        context.user_data["game"] = {
            "type": "quiz",
            "correct": correct,
            "reward": 1.0,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    answer,
                    callback_data=f"answer_{i}",
                )
            ]
            for i, answer in enumerate(answers)
        ]

        await q.message.reply_text(
            "🧠 <b>Qiyin savol</b>\n\n"
            f"{question}\n\n"
            "To‘g‘ri javobni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
            "reward": 1.5,
        }

        await q.message.reply_text(
            "🔢 <b>Sonni toping</b>\n\n"
            "Men 1 dan 100 gacha son o‘yladim.\n"
            "7 ta urinish bor.",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # CHOICE
    # ------------------------------------------------------

    if game == "choice":

        options = ["A", "B", "C", "D", "E"]

        correct = random.choice(options)

        context.user_data["game"] = {
            "type": "choice",
            "correct": correct,
            "reward": 1.0,
        }

        random.shuffle(options)

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"choice_{x}",
                )
                for x in options[:3]
            ],
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"choice_{x}",
                )
                for x in options[3:]
            ],
        ]

        await q.message.reply_text(
            "⚡ <b>Tez tanla</b>\n\n"
            "5 ta variantdan to‘g‘ri javobni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
            "reward": 1.5,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"logic_{i}",
                )
            ]
            for i, x in enumerate(answers)
        ]

        await q.message.reply_text(
            "🧩 <b>Mantiqiy masala</b>\n\n"
            f"{question}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
            "reward": 1.0,
        }

        nums = list(range(1, 10))
        keyboard = []

        for i in range(0, 9, 3):

            keyboard.append(
                [
                    InlineKeyboardButton(
                        str(x),
                        callback_data=f"target_{x}",
                    )
                    for x in nums[i:i + 3]
                ]
            )

        await q.message.reply_text(
            "🎯 <b>Nishon</b>\n\n"
            "Yashirin raqamni toping:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return

    # ------------------------------------------------------
    # WORD
    # ------------------------------------------------------

    if game == "word":

        _, correct_word = random.choice(WORDS)

        letters = list(correct_word)
        random.shuffle(letters)

        scrambled = "".join(letters)

        context.user_data["game"] = {
            "type": "word",
            "correct_word": correct_word.lower(),
            "reward": 1.3,
        }

        await q.message.reply_text(
            "🔤 <b>So‘zni toping</b>\n\n"
            f"🔀 <code>{scrambled}</code>\n\n"
            "So‘zni yozib yuboring.",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # MATH
    # ------------------------------------------------------

    if game == "math":

        a = random.randint(15, 80)
        b = random.randint(5, 40)
        c = random.randint(2, 9)

        mode = random.randint(1, 3)

        if mode == 1:

            answer = a + b * c
            text = f"{a} + {b} × {c}"

        elif mode == 2:

            answer = a * c - b
            text = f"{a} × {c} − {b}"

        else:

            answer = a * b + c
            text = f"{a} × {b} + {c}"

        context.user_data["game"] = {
            "type": "math",
            "correct": answer,
            "reward": 1.7,
        }

        await q.message.reply_text(
            "🧮 <b>Hisoblang</b>\n\n"
            f"❓ {text} = ?",
            parse_mode="HTML",
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
            "reward": 1.2,
        }

        keyboard = []

        for i in range(0, 9, 3):

            keyboard.append(
                [
                    InlineKeyboardButton(
                        str(x),
                        callback_data=f"attention_{x}",
                    )
                    for x in nums[i:i + 3]
                ]
            )

        await q.message.reply_text(
            "👀 <b>Diqqat!</b>\n\n"
            "Yashirin raqamni toping.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return

    # ------------------------------------------------------
    # COLOR
    # ------------------------------------------------------

    if game == "color":

        correct_text, correct_value = random.choice(
            COLORS
        )

        options = [
            x[1]
            for x in COLORS
        ]

        random.shuffle(options)

        context.user_data["game"] = {
            "type": "color",
            "correct": correct_value,
            "reward": 1.2,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"color_{x}",
                )
                for x in options[:2]
            ],
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"color_{x}",
                )
                for x in options[2:]
            ],
        ]

        await q.message.reply_text(
            "🎨 <b>Rangni toping</b>\n\n"
            f"{correct_text}\n\n"
            "Mos nomni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return

    # ------------------------------------------------------
    # CODE
    # ------------------------------------------------------

    if game == "code":

        digits = random.sample(
            range(10),
            4,
        )

        code = "".join(
            str(x)
            for x in digits
        )

        context.user_data["game"] = {
            "type": "code",
            "correct": code,
            "reward": 2.0,
        }

        await q.message.reply_text(
            "🔐 <b>Kodni toping</b>\n\n"
            "4 xonali kod yashirildi.\n"
            f"Raqamlar yig‘indisi: <b>{sum(digits)}</b>\n\n"
            "Kodni yozing.",
            parse_mode="HTML",
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
            "reward": 1.3,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"knowledge_{i}",
                )
            ]
            for i, x in enumerate(answers)
        ]

        await q.message.reply_text(
            "📚 <b>Bilim savoli</b>\n\n"
            f"{question}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return

    # ------------------------------------------------------
    # SPEED
    # ------------------------------------------------------

    if game == "speed":

        a = random.randint(10, 30)
        b = random.randint(5, 20)

        context.user_data["game"] = {
            "type": "speed",
            "correct": a + b,
            "reward": 2.0,
        }

        await q.message.reply_text(
            "⏱ <b>TEZLIK TESTI</b>\n\n"
            f"⚡ {a} + {b} = ?",
            parse_mode="HTML",
        )


# ==========================================================
# GAME TEXT ANSWER
# ==========================================================

async def process_game_answer(
    update,
    context,
):

    user_id = update.effective_user.id

    game = context.user_data.get("game")

    if not game:
        return

    if not update.message or not update.message.text:
        return

    answer = update.message.text.strip()

    game_type = game.get("type")

    correct = False

    # NUMBER
    if game_type == "number":

        try:
            value = int(answer)
        except ValueError:

            await update.message.reply_text(
                "❌ Faqat raqam yuboring."
            )
            return

        game["tries"] += 1

        if value == game["number"]:

            correct = True

        elif game["tries"] >= 7:

            await game_result(
                user_id,
                False,
            )

            context.user_data.pop(
                "game",
                None,
            )

            await update.message.reply_text(
                f"❌ Yutqazdingiz.\n"
                f"🔐 To‘g‘ri son: {game['number']}"
            )

            return

        else:

            hint = (
                "⬆️ Kattaroq son."
                if value < game["number"]
                else "⬇️ Kichikroq son."
            )

            await update.message.reply_text(
                f"{hint}\n"
                f"🎯 Qolgan urinish: "
                f"{7 - game['tries']}"
            )

            return

    # WORD
    elif game_type == "word":

        correct = (
            answer.lower()
            == game["correct_word"]
        )

    # MATH/CODE/SPEED
    elif game_type in (
        "math",
        "code",
        "speed",
    ):

        correct = (
            answer
            == str(game["correct"])
        )

    if correct:

        reward = float(
            game.get(
                "reward",
                GAME_REWARD,
            )
        )

        await change_points(
            user_id,
            reward,
        )

        await game_result(
            user_id,
            True,
        )

        context.user_data.pop(
            "game",
            None,
        )

        await update.message.reply_text(
            "🎉 <b>TO‘G‘RI!</b>\n\n"
            f"⭐ +{reward:g} Stars",
            parse_mode="HTML",
        )

    else:

        await game_result(
            user_id,
            False,
        )

        context.user_data.pop(
            "game",
            None,
        )

        await update.message.reply_text(
            "❌ <b>Noto‘g‘ri javob.</b>",
            parse_mode="HTML",
        )


# ==========================================================
# WITHDRAW
# ==========================================================

async def withdraw_request(
    update,
    context,
):

    user = update.effective_user

    row = get_user(user.id)

    if not row:
        return

    points = float(row["points"] or 0)
    referrals = int(row["referrals"] or 0)

    if points < MIN_WITHDRAW:

        await update.message.reply_text(
            f"💸 Yechish uchun ⭐ <b>{MIN_WITHDRAW:g}</b> kerak.\n\n"
            f"Sizda: ⭐ <b>{points:.2f}</b>",
            parse_mode="HTML",
        )

        return

    if referrals < MIN_REFERRALS:

        await update.message.reply_text(
            f"👥 Kamida <b>{MIN_REFERRALS}</b> referral kerak.\n\n"
            f"Sizda: <b>{referrals}</b>",
            parse_mode="HTML",
        )

        return

    con = db()

    pending = con.execute(
        """
        SELECT id
        FROM withdrawals
        WHERE user_id=?
        AND status='pending'
        """,
        (user.id,),
    ).fetchone()

    if pending:

        con.close()

        await update.message.reply_text(
            "⏳ Sizda allaqachon kutayotgan so‘rov bor."
        )

        return

    cur = con.cursor()

    cur.execute(
        """
        UPDATE users
        SET points=points-?
        WHERE id=?
        AND points>=?
        """,
        (
            MIN_WITHDRAW,
            user.id,
            MIN_WITHDRAW,
        ),
    )

    if cur.rowcount == 0:

        con.close()

        await update.message.reply_text(
            "❌ Balans yetarli emas."
        )

        return

    cur.execute(
        """
        INSERT INTO withdrawals
        (user_id,username,amount,status,created_at)
        VALUES(?,?,?,'pending',?)
        """,
        (
            user.id,
            user.username,
            MIN_WITHDRAW,
            now(),
        ),
    )

    withdrawal_id = cur.lastrowid

    con.commit()
    con.close()

    await update.message.reply_text(
        "✅ <b>Yechish so‘rovingiz muvaffaqiyatli "
        "qabul qilindi!</b>\n\n"
        f"💰 Miqdor: ⭐ <b>{MIN_WITHDRAW:g}</b>\n"
        "⏳ 24 soat ichida ko‘rib chiqiladi.",
        parse_mode="HTML",
    )

    if ADMIN_ID:

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Tasdiqlash",
                        callback_data=f"approve_{withdrawal_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ Rad etish",
                        callback_data=f"reject_{withdrawal_id}",
                    ),
                ]
            ]
        )

        try:

            await context.bot.send_message(
                ADMIN_ID,
                "💸 <b>YANGI YECHISH SO‘ROVI</b>\n\n"
                f"🆔 User: <code>{user.id}</code>\n"
                f"👤 @{user.username or 'yo‘q'}\n"
                f"⭐ Miqdor: <b>{MIN_WITHDRAW:g}</b>\n"
                f"📄 So‘rov: <b>#{withdrawal_id}</b>",
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except TelegramError as e:

            log.error(
                "Admin notification: %s",
                e,
            )


# ==========================================================
# CALLBACK
# ==========================================================

async def menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    q = update.callback_query

    await q.answer()

    user = q.from_user
    data = q.data

    await add_user(
        user.id,
        user.username,
    )

    # ------------------------------------------------------
    # CHECK SUB
    # ------------------------------------------------------

    if data == "check_sub":

        if await subscribed(
            context.bot,
            user.id,
        ):

            await q.message.reply_text(
                "✅ <b>Obuna tasdiqlandi!</b>",
                parse_mode="HTML",
                reply_markup=main_menu(
                    user.id == ADMIN_ID
                ),
            )

        else:

            await q.message.reply_text(
                "❌ Hali homiy kanalga obuna bo‘lmagansiz."
            )

        return

    # ------------------------------------------------------
    # ADMIN BYPASS
    # ------------------------------------------------------

    if user.id != ADMIN_ID:

        if not await require_subscription(
            update,
            context,
        ):
            return

    # ------------------------------------------------------
    # HOME
    # ------------------------------------------------------

    if data == "home":

        await q.message.reply_text(
            "🏠 <b>ASOSIY MENYU</b>\n\n"
            "👇 Bo‘limni tanlang:",
            parse_mode="HTML",
            reply_markup=main_menu(
                user.id == ADMIN_ID
            ),
        )

        return

    # ------------------------------------------------------
    # BUY
    # ------------------------------------------------------

    if data == "buy":

        keyboard = [
            [
                InlineKeyboardButton(
                    "⭐ 50 Stars",
                    callback_data="buy_50",
                ),
                InlineKeyboardButton(
                    "⭐ 100 Stars",
                    callback_data="buy_100",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⭐ 200 Stars",
                    callback_data="buy_200",
                ),
                InlineKeyboardButton(
                    "⭐ 500 Stars",
                    callback_data="buy_500",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⭐ 1000 Stars",
                    callback_data="buy_1000",
                ),
                InlineKeyboardButton(
                    "⭐ 2000 Stars",
                    callback_data="buy_2000",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⭐ 5000 Stars",
                    callback_data="buy_5000",
                )
            ],
            [
                InlineKeyboardButton(
                    "💳 Sotib olish",
                    url=BUY_STARS_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Orqaga",
                    callback_data="home",
                )
            ],
        ]

        await q.message.reply_text(
            "⭐ <b>STARS OLISH</b>\n\n"
            "Kerakli paketni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return

    if data.startswith("buy_"):

        amount = data.replace(
            "buy_",
            "",
        )

        await q.message.reply_text(
            f"⭐ <b>{amount} Stars</b>\n\n"
            "Sotib olish:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💳 Sotib olish",
                            url=BUY_STARS_URL,
                        )
                    ]
                ]
            ),
        )

        return

    # ------------------------------------------------------
    # BALANCE
    # ------------------------------------------------------

    if data == "balance":

        row = get_user(user.id)

        points = float(row["points"] or 0)
        refs = int(row["referrals"] or 0)

        await q.message.reply_text(
            "💰 <b>BALANS</b>\n\n"
            f"⭐ Stars: <b>{points:.2f}</b>\n"
            f"👥 Referallar: <b>{refs}</b>",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # PROFILE
    # ------------------------------------------------------

    if data == "profile":

        row = get_user(user.id)

        await q.message.reply_text(
            "👤 <b>PROFIL</b>\n\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"👤 Username: @{user.username or 'yo‘q'}\n"
            f"⭐ Stars: <b>{float(row['points'] or 0):.2f}</b>\n"
            f"🎮 O‘yinlar: <b>{row['games']}</b>\n"
            f"🏆 G‘alabalar: <b>{row['wins']}</b>\n"
            f"👥 Referallar: <b>{row['referrals']}</b>",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # REF
    # ------------------------------------------------------

    if data == "ref":

        bot_info = await context.bot.get_me()

        link = (
            f"https://t.me/{bot_info.username}"
            f"?start={user.id}"
        )

        row = get_user(user.id)

        await q.message.reply_text(
            "👥 <b>REFERAL TIZIMI</b>\n\n"
            f"Har bir referral: ⭐ <b>{REFERRAL_REWARD:g}</b>\n"
            f"Sizning referral: <b>{row['referrals']}</b>\n\n"
            "🔗 Havolangiz:\n"
            f"<code>{link}</code>",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # TASKS
    # ------------------------------------------------------

    if data == "tasks":

        con = db()

        rows = con.execute(
            """
            SELECT id,text,reward,url
            FROM tasks
            ORDER BY id DESC
            """
        ).fetchall()

        con.close()

        if not rows:

            await q.message.reply_text(
                "🎁 Hozircha topshiriqlar yo‘q."
            )

            return

        for row in rows:

            url = row["url"]

            if not url and row["text"]:
                url = channel_url(row["text"])

            keyboard = [
                [
                    InlineKeyboardButton(
                        "📲 Topshiriq",
                        url=url,
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"✅ Bajardim (+{float(row['reward'] or 0):g} ⭐)",
                        callback_data=f"taskdone_{row['id']}",
                    )
                ],
            ]

            await q.message.reply_text(
                f"🎁 <b>Topshiriq #{row['id']}</b>\n\n"
                f"{row['text']}\n\n"
                f"💰 ⭐ <b>{float(row['reward'] or 0):g}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        return

    # ------------------------------------------------------
    # TASK DONE
    # ------------------------------------------------------

    if data.startswith("taskdone_"):

        try:
            task_id = int(
                data.replace(
                    "taskdone_",
                    "",
                )
            )
        except ValueError:
            return

        con = db()

        task = con.execute(
            """
            SELECT reward,channel
            FROM tasks
            WHERE id=?
            """,
            (task_id,),
        ).fetchone()

        if not task:

            con.close()

            await q.message.reply_text(
                "❌ Topshiriq topilmadi."
            )

            return

        already = con.execute(
            """
            SELECT 1
            FROM task_claims
            WHERE user_id=?
            AND task_id=?
            """,
            (
                user.id,
                task_id,
            ),
        ).fetchone()

        if already:

            con.close()

            await q.message.reply_text(
                "⚠️ Bu topshiriq uchun Stars olgansiz."
            )

            return

        # Agar task kanal bo‘lsa obunani tekshiramiz
        channel = task["channel"]

        if channel:

            try:

                member = await context.bot.get_chat_member(
                    channel,
                    user.id,
                )

                if member.status not in (
                    ChatMemberStatus.MEMBER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.OWNER,
                ):

                    con.close()

                    await q.message.reply_text(
                        "❌ Avval topshiriq kanaliga obuna bo‘ling."
                    )

                    return

            except TelegramError:

                pass

        reward = float(
            task["reward"] or 0
        )

        con.execute(
            """
            INSERT INTO task_claims
            (user_id,task_id,created_at,claimed_at)
            VALUES(?,?,?,?)
            """,
            (
                user.id,
                task_id,
                now(),
                now(),
            ),
        )

        con.execute(
            """
            UPDATE users
            SET points=points+?
            WHERE id=?
            """,
            (
                reward,
                user.id,
            ),
        )

        con.commit()
        con.close()

        await q.message.reply_text(
            f"🎉 Topshiriq qabul qilindi!\n\n"
            f"⭐ +{reward:g} Stars",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # RATING
    # ------------------------------------------------------

    if data == "rating":

        con = db()

        rows = con.execute(
            """
            SELECT username,points
            FROM users
            ORDER BY points DESC
            LIMIT 10
            """
        ).fetchall()

        con.close()

        text = "🏆 <b>TOP 10 REYTING</b>\n\n"

        for i, row in enumerate(
            rows,
            1,
        ):

            name = (
                f"@{row['username']}"
                if row["username"]
                else "Foydalanuvchi"
            )

            text += (
                f"{i}. {name} — "
                f"⭐ {float(row['points'] or 0):.2f}\n"
            )

        await q.message.reply_text(
            text,
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # WITHDRAW
    # ------------------------------------------------------

    if data == "withdraw":

        row = get_user(user.id)

        points = float(row["points"] or 0)
        referrals = int(row["referrals"] or 0)

        if points < MIN_WITHDRAW:

            await q.message.reply_text(
                f"💸 Kamida ⭐ <b>{MIN_WITHDRAW:g}</b> kerak.\n"
                f"Sizda: ⭐ <b>{points:.2f}</b>",
                parse_mode="HTML",
            )

            return

        if referrals < MIN_REFERRALS:

            await q.message.reply_text(
                f"👥 Kamida <b>{MIN_REFERRALS}</b> referral kerak.\n"
                f"Sizda: <b>{referrals}</b>",
                parse_mode="HTML",
            )

            return

        con = db()

        pending = con.execute(
            """
            SELECT id
            FROM withdrawals
            WHERE user_id=?
            AND status='pending'
            """,
            (user.id,),
        ).fetchone()

        con.close()

        if pending:

            await q.message.reply_text(
                "⏳ Sizda kutayotgan so‘rov bor."
            )

            return

        con = db()

        cur = con.cursor()

        cur.execute(
            """
            UPDATE users
            SET points=points-?
            WHERE id=?
            AND points>=?
            """,
            (
                MIN_WITHDRAW,
                user.id,
                MIN_WITHDRAW,
            ),
        )

        if cur.rowcount == 0:

            con.close()

            await q.message.reply_text(
                "❌ Balans yetarli emas."
            )

            return

        cur.execute(
            """
            INSERT INTO withdrawals
            (user_id,username,amount,status,created_at)
            VALUES(?,?,?,'pending',?)
            """,
            (
                user.id,
                user.username,
                MIN_WITHDRAW,
                now(),
            ),
        )

        withdrawal_id = cur.lastrowid

        con.commit()
        con.close()

        await q.message.reply_text(
            "✅ <b>Yechish so‘rovingiz muvaffaqiyatli "
            "qabul qilindi!</b>\n\n"
            f"💰 Miqdor: ⭐ <b>{MIN_WITHDRAW:g}</b>\n"
            "⏳ 24 soat ichida ko‘rib chiqiladi.",
            parse_mode="HTML",
        )

        if ADMIN_ID:

            try:

                await context.bot.send_message(
                    ADMIN_ID,
                    "💸 <b>YANGI SO‘ROV</b>\n\n"
                    f"🆔 <code>{user.id}</code>\n"
                    f"👤 @{user.username or 'yo‘q'}\n"
                    f"⭐ {MIN_WITHDRAW:g}\n"
                    f"📄 #{withdrawal_id}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "✅ Tasdiqlash",
                                    callback_data=f"approve_{withdrawal_id}",
                                ),
                                InlineKeyboardButton(
                                    "❌ Rad etish",
                                    callback_data=f"reject_{withdrawal_id}",
                                ),
                            ]
                        ]
                    ),
                )

            except TelegramError:
                pass

        return

    # ------------------------------------------------------
    # APPROVE
    # ------------------------------------------------------

    if data.startswith("approve_"):

        if user.id != ADMIN_ID:
            return

        try:
            withdrawal_id = int(
                data.replace(
                    "approve_",
                    "",
                )
            )
        except ValueError:
            return

        con = db()

        row = con.execute(
            """
            SELECT user_id,amount,status
            FROM withdrawals
            WHERE id=?
            """,
            (withdrawal_id,),
        ).fetchone()

        if not row:

            con.close()

            await q.message.reply_text(
                "❌ So‘rov topilmadi."
            )

            return

        if row["status"] != "pending":

            con.close()

            await q.message.reply_text(
                "⚠️ So‘rov allaqachon ko‘rilgan."
            )

            return

        con.execute(
            """
            UPDATE withdrawals
            SET status='approved'
            WHERE id=?
            """,
            (withdrawal_id,),
        )

        con.commit()
        con.close()

        await q.message.reply_text(
            f"✅ #{withdrawal_id} tasdiqlandi."
        )

        try:

            await context.bot.send_message(
                row["user_id"],
                "🎉 <b>Yechish so‘rovingiz tasdiqlandi!</b>\n\n"
                f"⭐ Miqdor: <b>{float(row['amount']):g}</b>",
                parse_mode="HTML",
            )

        except TelegramError:
            pass

        return

    # ------------------------------------------------------
    # REJECT
    # ------------------------------------------------------

    if data.startswith("reject_"):

        if user.id != ADMIN_ID:
            return

        try:
            withdrawal_id = int(
                data.replace(
                    "reject_",
                    "",
                )
            )
        except ValueError:
            return

        con = db()

        row = con.execute(
            """
            SELECT user_id,amount,status
            FROM withdrawals
            WHERE id=?
            """,
            (withdrawal_id,),
        ).fetchone()

        if not row:

            con.close()

            await q.message.reply_text(
                "❌ So‘rov topilmadi."
            )

            return

        if row["status"] != "pending":

            con.close()

            await q.message.reply_text(
                "⚠️ So‘rov allaqachon ko‘rilgan."
            )

            return

        con.execute(
            """
            UPDATE withdrawals
            SET status='rejected'
            WHERE id=?
            """,
            (withdrawal_id,),
        )

        con.execute(
            """
            UPDATE users
            SET points=points+?
            WHERE id=?
            """,
            (
                row["amount"],
                row["user_id"],
            ),
        )

        con.commit()
        con.close()

        await q.message.reply_text(
            f"❌ #{withdrawal_id} rad etildi.\n"
            f"⭐ {float(row['amount']):g} balansga qaytarildi."
        )

        try:

            await context.bot.send_message(
                row["user_id"],
                "❌ <b>Yechish so‘rovingiz rad etildi.</b>\n\n"
                f"⭐ {float(row['amount']):g} Stars balansga qaytarildi.",
                parse_mode="HTML",
            )

        except TelegramError:
            pass

        return

    # ------------------------------------------------------
    # GAMES
    # ------------------------------------------------------

    if data == "games":

        await q.message.reply_text(
            "🎯 <b>STARS ISHLASH</b>\n\n"
            "Har bir o‘yin orasida cooldown mavjud.",
            parse_mode="HTML",
            reply_markup=games_menu(),
        )

        return

    if data.startswith("game_"):

        game = data.replace(
            "game_",
            "",
        )

        if game not in [
            x[1]
            for x in GAMES
        ]:
            return

        await start_game(
            update,
            context,
            game,
        )

        return

    # ------------------------------------------------------
    # GAME CALLBACKS
    # ------------------------------------------------------

    if data.startswith(
        (
            "answer_",
            "logic_",
            "target_",
            "attention_",
            "color_",
            "knowledge_",
            "choice_",
        )
    ):

        game = context.user_data.get("game")

        if not game:
            return

        prefix = data.split("_", 1)[0]
        value = data.split("_", 1)[1]

        try:
            selected = int(value)
        except ValueError:
            selected = value

        correct = False

        if prefix in (
            "answer",
            "logic",
            "knowledge",
        ):

            correct = (
                selected
                == game["correct"]
            )

        else:

            correct = (
                selected
                == game["correct"]
            )

        if correct:

            reward = float(
                game.get(
                    "reward",
                    GAME_REWARD,
                )
            )

            await change_points(
                user.id,
                reward,
            )

            await game_result(
                user.id,
                True,
            )

            await q.message.reply_text(
                f"🎉 <b>TO‘G‘RI!</b>\n"
                f"⭐ +{reward:g} Stars",
                parse_mode="HTML",
            )

        else:

            await game_result(
                user.id,
                False,
            )

            await q.message.reply_text(
                "❌ Noto‘g‘ri javob."
            )

        context.user_data.pop(
            "game",
            None,
        )

        return

    # ------------------------------------------------------
    # OTHER GAMES
    # ------------------------------------------------------

    if data == "other_games":

        await q.message.reply_text(
            "🎮 <b>O‘YINLAR</b>\n\n"
            "Bu bo‘lim keyingi versiyalarda kengaytiriladi.",
            parse_mode="HTML",
        )

        return

    # ======================================================
    # ADMIN PANEL
    # ======================================================

    if data == "admin":

        if user.id != ADMIN_ID:
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    "📊 STATISTIKA",
                    callback_data="admin_stats",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 USERLAR",
                    callback_data="admin_users",
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 BROADCAST",
                    callback_data="admin_broadcast",
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ TOPSHIRIQ",
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
                    "📢 HOMIY QO‘SHISH",
                    callback_data="admin_addsponsor",
                ),
                InlineKeyboardButton(
                    "🗑 HOMIY O‘CHIRISH",
                    callback_data="admin_delsponsor",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📢 HOMIYLAR",
                    callback_data="admin_sponsors",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Bosh menyu",
                    callback_data="home",
                )
            ],
        ]

        await q.message.reply_text(
            "⚙️ <b>ADMIN PANEL</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return

    # ------------------------------------------------------
    # ADMIN STATS
    # ------------------------------------------------------

    if data == "admin_stats":

        if user.id != ADMIN_ID:
            return

        con = db()

        users_count = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        total_points = con.execute(
            "SELECT COALESCE(SUM(points),0) FROM users"
        ).fetchone()[0]

        referrals = con.execute(
            "SELECT COALESCE(SUM(referrals),0) FROM users"
        ).fetchone()[0]

        pending = con.execute(
            """
            SELECT COUNT(*)
            FROM withdrawals
            WHERE status='pending'
            """
        ).fetchone()[0]

        total = con.execute(
            """
            SELECT total_users
            FROM bot_stats
            WHERE id=1
            """
        ).fetchone()

        con.close()

        await q.message.reply_text(
            "📊 <b>BOT STATISTIKASI</b>\n\n"
            f"👥 Hozirgi userlar: <b>{format_count(users_count)}</b>\n"
            f"📈 Jami userlar: <b>{format_count(total['total_users'] if total else users_count)}</b>\n"
            f"⭐ Jami Stars: <b>{float(total_points or 0):.2f}</b>\n"
            f"👥 Referallar: <b>{referrals}</b>\n"
            f"💸 Kutilayotgan yechish: <b>{pending}</b>",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # ADMIN USERS
    # ------------------------------------------------------

    if data == "admin_users":

        if user.id != ADMIN_ID:
            return

        total = await get_total_users()

        await q.message.reply_text(
            f"👥 <b>Jami foydalanuvchilar:</b>\n\n"
            f"<b>{format_count(total)} ta</b>",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # BROADCAST
    # ------------------------------------------------------

    if data == "admin_broadcast":

        if user.id != ADMIN_ID:
            return

        context.user_data[
            "admin_action"
        ] = "broadcast"

        await q.message.reply_text(
            "📢 Xabar matnini yuboring:"
        )

        return

    # ------------------------------------------------------
    # ADD TASK
    # ------------------------------------------------------

    if data == "admin_addtask":

        if user.id != ADMIN_ID:
            return

        context.user_data[
            "admin_action"
        ] = "add_task"

        await q.message.reply_text(
            "➕ <b>TOPSHIRIQ QO‘SHISH</b>\n\n"
            "<code>MATN | REWARD | URL</code>\n\n"
            "Masalan:\n"
            "<code>Kanalga obuna bo‘ling | 5 | https://t.me/example</code>",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # ADMIN TASKS
    # ------------------------------------------------------

    if data == "admin_tasks":

        if user.id != ADMIN_ID:
            return

        con = db()

        rows = con.execute(
            """
            SELECT id,text,reward,url
            FROM tasks
            ORDER BY id DESC
            """
        ).fetchall()

        con.close()

        if not rows:

            await q.message.reply_text(
                "📋 Topshiriqlar yo‘q."
            )

            return

        text = "📋 <b>TOPSHIRIQLAR</b>\n\n"

        for row in rows:

            text += (
                f"#{row['id']} — {row['text']}\n"
                f"⭐ {float(row['reward'] or 0):g}\n"
                f"{row['url'] or '-'}\n\n"
            )

        await q.message.reply_text(
            text,
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # ADD SPONSOR
    # ------------------------------------------------------

    if data == "admin_addsponsor":

        if user.id != ADMIN_ID:
            return

        context.user_data[
            "admin_action"
        ] = "add_sponsor"

        await q.message.reply_text(
            "📢 <b>HOMIY KANAL QO‘SHISH</b>\n\n"
            "Kanal username yoki linkini yuboring.\n\n"
            "Masalan:\n"
            "<code>@kanal</code>\n"
            "yoki\n"
            "<code>https://t.me/kanal</code>",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # DELETE SPONSOR
    # ------------------------------------------------------

    if data == "admin_delsponsor":

        if user.id != ADMIN_ID:
            return

        context.user_data[
            "admin_action"
        ] = "delete_sponsor"

        await q.message.reply_text(
            "🗑 <b>HOMIY KANAL O‘CHIRISH</b>\n\n"
            "O‘chirmoqchi bo‘lgan kanalni yuboring.",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # SPONSORS LIST
    # ------------------------------------------------------

    if data == "admin_sponsors":

        if user.id != ADMIN_ID:
            return

        sponsors = get_sponsors()

        text = "📢 <b>HOMIY KANALLAR</b>\n\n"

        for i, sponsor in enumerate(
            sponsors,
            1,
        ):

            text += (
                f"{i}. {sponsor['channel']}\n"
                f"🔗 {sponsor['url']}\n\n"
            )

        await q.message.reply_text(
            text,
            parse_mode="HTML",
        )

        return


# ==========================================================
# ADMIN MESSAGE
# ==========================================================

async def admin_message(
    update,
    context,
):

    user = update.effective_user

    if not user or user.id != ADMIN_ID:
        return

    if not update.message:
        return

    action = context.user_data.get(
        "admin_action"
    )

    if not action:
        return

    # ------------------------------------------------------
    # ADD SPONSOR
    # ------------------------------------------------------

    if action == "add_sponsor":

        channel = normalize_channel(
            update.message.text
        )

        if not channel:

            await update.message.reply_text(
                "❌ Kanal noto‘g‘ri."
            )

            return

        try:

            member_count = await context.bot.get_chat_member_count(
                channel
            )

        except TelegramError:

            member_count = None

        if add_sponsor(channel):

            context.user_data.pop(
                "admin_action",
                None,
            )

            await update.message.reply_text(
                "✅ <b>HOMIY KANAL QO‘SHILDI!</b>\n\n"
                f"📢 {channel}\n"
                f"🔗 {channel_url(channel)}\n\n"
                "Endi foydalanuvchilardan shu kanalga "
                "ham obuna bo‘lish talab qilinadi.",
                parse_mode="HTML",
            )

            if member_count is not None:

                await update.message.reply_text(
                    f"👥 Kanal a'zolari: "
                    f"<b>{format_count(member_count)}</b>",
                    parse_mode="HTML",
                )

        else:

            await update.message.reply_text(
                "⚠️ Bu kanal allaqachon homiylar ro‘yxatida."
            )

        return

    # ------------------------------------------------------
    # DELETE SPONSOR
    # ------------------------------------------------------

    if action == "delete_sponsor":

        channel = normalize_channel(
            update.message.text
        )

        if channel == normalize_channel(
            SPONSOR_CHANNEL
        ):

            await update.message.reply_text(
                "❌ Asosiy homiy kanalni o‘chirib bo‘lmaydi."
            )

            return

        if delete_sponsor(channel):

            context.user_data.pop(
                "admin_action",
                None,
            )

            await update.message.reply_text(
                f"✅ {channel} homiylar ro‘yxatidan o‘chirildi."
            )

        else:

            await update.message.reply_text(
                "❌ Bunday homiy kanal topilmadi."
            )

        return

    # ------------------------------------------------------
    # BROADCAST
    # ------------------------------------------------------

    if action == "broadcast":

        text = update.message.text

        if not text:

            await update.message.reply_text(
                "❌ Matn yuboring."
            )

            return

        con = db()

        users = con.execute(
            """
            SELECT id
            FROM users
            WHERE blocked=0
            """
        ).fetchall()

        con.close()

        sent = 0
        blocked = 0

        await update.message.reply_text(
            f"📢 {len(users)} ta userga yuborilmoqda..."
        )

        for row in users:

            user_id = row["id"]

            try:

                await context.bot.send_message(
                    user_id,
                    text,
                )

                sent += 1

                await asyncio.sleep(0.04)

            except Forbidden:

                blocked += 1

                con = db()

                con.execute(
                    """
                    UPDATE users
                    SET blocked=1
                    WHERE id=?
                    """,
                    (user_id,),
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
            None,
        )

        await update.message.reply_text(
            "✅ <b>Broadcast tugadi.</b>\n\n"
            f"📨 Yuborildi: <b>{sent}</b>\n"
            f"🚫 Bloklaganlar: <b>{blocked}</b>",
            parse_mode="HTML",
        )

        return

    # ------------------------------------------------------
    # ADD TASK
    # ------------------------------------------------------

    if action == "add_task":

        try:

            parts = [
                x.strip()
                for x in update.message.text.split("|")
            ]

            if len(parts) != 3:
                raise ValueError

            task_text = parts[0]
            reward = float(parts[1])
            url = parts[2]

            if not task_text or not url:
                raise ValueError

        except (
            ValueError,
            AttributeError,
        ):

            await update.message.reply_text(
                "❌ Format noto‘g‘ri.\n\n"
                "<code>MATN | REWARD | URL</code>",
                parse_mode="HTML",
            )

            return

        channel = normalize_channel(url)

        con = db()

        cur = con.cursor()

        cur.execute(
            """
            INSERT INTO tasks
            (text,reward,url,channel)
            VALUES(?,?,?,?)
            """,
            (
                task_text,
                reward,
                url,
                channel,
            ),
        )

        task_id = cur.lastrowid

        con.commit()
        con.close()

        context.user_data.pop(
            "admin_action",
            None,
        )

        await update.message.reply_text(
            f"✅ Topshiriq #{task_id} qo‘shildi.\n\n"
            f"🎁 {task_text}\n"
            f"⭐ {reward:g}\n"
            f"🔗 {url}",
            parse_mode="HTML",
        )

        return


# ==========================================================
# TEXT ROUTER
# ==========================================================

async def text_router(
    update,
    context,
):

    # Admin action birinchi tekshiriladi
    action = context.user_data.get(
        "admin_action"
    )

    if action:

        await admin_message(
            update,
            context,
        )

        return

    game = context.user_data.get(
        "game"
    )

    if game:

        await process_game_answer(
            update,
            context,
        )

        return


# ==========================================================
# COMMAND / WITHDRAW TEXT
# ==========================================================

async def cancel(
    update,
    context,
):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Amal bekor qilindi."
    )


async def bot_id(
    update,
    context,
):

    await update.message.reply_text(
        f"🆔 Sizning ID: <code>{update.effective_user.id}</code>",
        parse_mode="HTML",
    )


# ==========================================================
# ERROR
# ==========================================================

async def error_handler(
    update,
    context,
):

    log.error(
        "Exception while handling update: %s",
        context.error,
        exc_info=True,
    )


# ==========================================================
# POST INIT
# ==========================================================

async def post_init(
    application,
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

    log.info(
        "===================================="
    )

    log.info(
        "✅ ZERIKDIM BOT ISHLADI"
    )

    log.info(
        "===================================="
    )


# ==========================================================
# GITHUB DATABASE BACKUP
# ==========================================================

def git_command(
    command,
    timeout=60,
):

    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def save_database():

    async with save_lock:

        def _save():

            try:

                if not os.path.exists(DB_FILE):

                    return False

                con = sqlite3.connect(
                    DB_FILE,
                    timeout=30,
                )

                try:
                    con.execute(
                        "PRAGMA wal_checkpoint(FULL)"
                    )
                except Exception:
                    pass

                con.close()

                git_command(
                    [
                        "git",
                        "config",
                        "user.name",
                        "Zerikdim Bot",
                    ]
                )

                git_command(
                    [
                        "git",
                        "config",
                        "user.email",
                        "zerikdim-bot@users.noreply.github.com",
                    ]
                )

                r = git_command(
                    [
                        "git",
                        "add",
                        "-f",
                        DB_FILE,
                    ]
                )

                if r.returncode != 0:

                    log.error(
                        "git add: %s",
                        r.stderr,
                    )

                    return False

                r = git_command(
                    [
                        "git",
                        "diff",
                        "--cached",
                        "--quiet",
                    ]
                )

                if r.returncode == 0:

                    return True

                r = git_command(
                    [
                        "git",
                        "commit",
                        "-m",
                        "Update Zerikdim database",
                    ]
                )

                if r.returncode != 0:

                    log.error(
                        "git commit: %s",
                        r.stderr,
                    )

                    return False

                r = git_command(
                    [
                        "git",
                        "push",
                        "origin",
                        "HEAD:main",
                    ]
                )

                if r.returncode != 0:

                    log.error(
                        "git push: %s",
                        r.stderr,
                    )

                    return False

                log.info(
                    "✅ DATABASE GITHUBGA SAQLANDI"
                )

                return True

            except Exception as e:

                log.error(
                    "Database save error: %s",
                    e,
                    exc_info=True,
                )

                return False

        return await asyncio.to_thread(
            _save
        )


async def periodic_database_backup():

    await asyncio.sleep(30)

    while True:

        try:

            await save_database()

            await asyncio.sleep(60)

        except asyncio.CancelledError:

            break

        except Exception as e:

            log.error(
                "Backup error: %s",
                e,
            )

            await asyncio.sleep(60)


# ==========================================================
# POST SHUTDOWN
# ==========================================================

async def post_shutdown(
    application,
):

    try:

        await save_database()

    except Exception as e:

        log.error(
            "Shutdown backup: %s",
            e,
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
            "ADMIN_ID sozlanmagan!"
        )

    init_db()

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
        CommandHandler(
            "cancel",
            cancel,
        )
    )

    application.add_handler(
        CommandHandler(
            "id",
            bot_id,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            menu,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    application.add_error_handler(
        error_handler
    )

    log.info(
        "🚀 Polling ishga tushmoqda..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
