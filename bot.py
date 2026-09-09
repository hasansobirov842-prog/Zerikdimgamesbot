import os
import sqlite3
import random
import logging
import asyncio
import shutil
import subprocess

from datetime import datetime, timezone, timedelta

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


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB = "zerikdim.db"
DB_BACKUP = "zerikdim.db.backup"

BACKUP_INTERVAL = 60

backup_lock = asyncio.Lock()

# FAQAT 2 TA HOMIY KANAL
SPONSORS = [
    "@premyumstarstekin",
]

# Stars sotib olish
BUY_STARS = "https://t.me/premyumstarstekin/933"

# Bot short description
BOT_SHORT_DESCRIPTION = "@bookmeet"

REFERRAL_REWARD = 9.0
GAME_REWARD = 0.1
TASK_REWARD = 5.0

MIN_WITHDRAW = 50.0
MIN_REFERRALS = 20

USERS_PER_PAGE = 10


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE
# ============================================================

def connect():
    con = sqlite3.connect(
        DB,
        timeout=30
    )

    con.row_factory = sqlite3.Row

    con.execute(
        "PRAGMA busy_timeout=30000"
    )

    return con


def now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def database_is_valid(path):

    if not os.path.exists(path):
        return False

    if os.path.getsize(path) == 0:
        return False

    try:

        con = sqlite3.connect(
            path,
            timeout=10
        )

        result = con.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        con.close()

        return result == "ok"

    except Exception:

        return False


def restore_backup_if_needed():

    if database_is_valid(DB):
        return

    if not database_is_valid(DB_BACKUP):
        return

    tmp = DB + ".restore.tmp"

    try:

        shutil.copy2(
            DB_BACKUP,
            tmp
        )

        os.replace(
            tmp,
            DB
        )

        logger.warning(
            "Asosiy DB backupdan tiklandi."
        )

    except Exception as e:

        logger.error(
            "DB restore xatosi: %s",
            e
        )

        try:

            if os.path.exists(tmp):
                os.remove(tmp)

        except Exception:
            pass


def normalize_sponsors_and_tasks(con):

    cur = con.cursor()

    # Eski homiylarni tozalaymiz.
    cur.execute(
        "DELETE FROM sponsors"
    )

    # Faqat 2 ta kerakli homiy.
    for channel in SPONSORS:

        cur.execute(
            """
            INSERT OR IGNORE INTO sponsors(channel)
            VALUES(?)
            """,
            (channel,)
        )

    # Eski topshiriqlarni tozalaymiz.
    cur.execute(
        "DELETE FROM tasks"
    )

    # Faqat 2 ta topshiriq.
    for channel in SPONSORS:

        cur.execute(
            """
            INSERT INTO tasks(
                channel,
                reward
            )
            VALUES(?,?)
            """,
            (
                channel,
                TASK_REWARD
            )
        )


def init_db():

    restore_backup_if_needed()

    con = connect()
    cur = con.cursor()

    cur.execute(
        """
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
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sponsors (
            channel TEXT PRIMARY KEY
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT UNIQUE,
            reward REAL DEFAULT 5
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_claims (
            user_id INTEGER,
            task_id INTEGER,
            claimed_at TEXT,
            PRIMARY KEY(user_id, task_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_stats (
            id INTEGER PRIMARY KEY CHECK(id=1),
            started_at TEXT,
            total_users INTEGER DEFAULT 0
        )
        """
    )

    current_users = cur.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    row = cur.execute(
        """
        SELECT total_users
        FROM bot_stats
        WHERE id=1
        """
    ).fetchone()

    if row is None:

        cur.execute(
            """
            INSERT INTO bot_stats(
                id,
                started_at,
                total_users
            )
            VALUES(1,?,?)
            """,
            (
                now(),
                current_users
            )
        )

    elif current_users > int(
        row[0] or 0
    ):

        cur.execute(
            """
            UPDATE bot_stats
            SET total_users=?
            WHERE id=1
            """,
            (current_users,)
        )

    # Faqat 2 sponsor va 2 task.
    normalize_sponsors_and_tasks(
        con
    )

    con.commit()
    con.close()


def get_total_users():

    con = connect()

    row = con.execute(
        """
        SELECT total_users
        FROM bot_stats
        WHERE id=1
        """
    ).fetchone()

    con.close()

    if row and row[0] is not None:
        return int(row[0])

    con = connect()

    total = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    con.close()

    return int(total)


async def update_profile_user_count(bot):

    try:

        await bot.set_my_short_description(
            short_description=BOT_SHORT_DESCRIPTION
        )

    except TelegramError as e:

        logger.error(
            "Bot short description xatosi: %s",
            e
        )

    except Exception as e:

        logger.error(
            "Profil xatosi: %s",
            e
        )


# ============================================================
# DATABASE BACKUP
# ============================================================

async def save_database():

    async with backup_lock:

        try:

            def make_snapshot():

                if not database_is_valid(DB):
                    return False

                source = sqlite3.connect(
                    DB,
                    timeout=30
                )

                target_tmp = DB_BACKUP + ".tmp"

                target = sqlite3.connect(
                    target_tmp,
                    timeout=30
                )

                try:

                    source.backup(
                        target
                    )

                    target.commit()

                finally:

                    target.close()
                    source.close()

                os.replace(
                    target_tmp,
                    DB_BACKUP
                )

                return True

            ok = await asyncio.to_thread(
                make_snapshot
            )

            if not ok:
                return False

            def git_backup():

                try:

                    inside = subprocess.run(
                        [
                            "git",
                            "rev-parse",
                            "--is-inside-work-tree"
                        ],
                        capture_output=True,
                        text=True
                    )

                    if inside.returncode != 0:

                        logger.error(
                            "Git repository topilmadi."
                        )

                        return False

                    subprocess.run(
                        [
                            "git",
                            "config",
                            "user.name",
                            "Zerikdim Bot"
                        ],
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

                    add = subprocess.run(
                        [
                            "git",
                            "add",
                            "-f",
                            DB,
                            DB_BACKUP
                        ],
                        capture_output=True,
                        text=True
                    )

                    if add.returncode != 0:

                        logger.error(
                            "git add xatosi: %s",
                            add.stderr.strip()
                        )

                        return False

                    diff = subprocess.run(
                        [
                            "git",
                            "diff",
                            "--cached",
                            "--quiet",
                            "--",
                            DB,
                            DB_BACKUP
                        ],
                        capture_output=True
                    )

                    if diff.returncode == 0:
                        return True

                    commit = subprocess.run(
                        [
                            "git",
                            "commit",
                            "-m",
                            "Zerikdim DB backup"
                        ],
                        capture_output=True,
                        text=True
                    )

                    if commit.returncode != 0:

                        logger.error(
                            "git commit xatosi: %s",
                            commit.stderr.strip()
                        )

                        return False

                    branch = os.getenv(
                        "GITHUB_REF_NAME",
                        ""
                    ).strip()

                    if not branch:

                        b = subprocess.run(
                            [
                                "git",
                                "branch",
                                "--show-current"
                            ],
                            capture_output=True,
                            text=True
                        )

                        branch = (
                            b.stdout.strip()
                            or "main"
                        )

                    push = subprocess.run(
                        [
                            "git",
                            "push",
                            "origin",
                            f"HEAD:{branch}"
                        ],
                        capture_output=True,
                        text=True
                    )

                    if push.returncode != 0:

                        logger.error(
                            "GitHub push xatosi: %s",
                            (
                                push.stderr
                                or push.stdout
                            ).strip()
                        )

                        return False

                    logger.info(
                        "DB GitHubga saqlandi."
                    )

                    return True

                except Exception as e:

                    logger.error(
                        "GitHub backup xatosi: %s",
                        e
                    )

                    return False

            return await asyncio.to_thread(
                git_backup
            )

        except Exception as e:

            logger.error(
                "Database backup xatosi: %s",
                e
            )

            return False


async def backup_loop():

    while True:

        try:

            await asyncio.sleep(
                BACKUP_INTERVAL
            )

            await save_database()

        except asyncio.CancelledError:

            return

        except Exception as e:

            logger.error(
                "Backup loop xatosi: %s",
                e
            )


# ============================================================
# USERS
# ============================================================

def add_user(
    user,
    referrer=None
):

    con = connect()
    cur = con.cursor()

    old = cur.execute(
        """
        SELECT id
        FROM users
        WHERE id=?
        """,
        (user.id,)
    ).fetchone()

    if old:

        cur.execute(
            """
            UPDATE users
            SET username=?,
                last_seen=?,
                blocked=0
            WHERE id=?
            """,
            (
                user.username,
                now(),
                user.id
            )
        )

        con.commit()
        con.close()

        return False

    valid_ref = None

    if referrer and referrer != user.id:

        exists = cur.execute(
            """
            SELECT id
            FROM users
            WHERE id=?
            """,
            (referrer,)
        ).fetchone()

        if exists:
            valid_ref = referrer

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
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            user.id,
            user.username,
            0,
            0,
            0,
            0,
            valid_ref,
            now(),
            0,
            0
        )
    )

    cur.execute(
        """
        UPDATE bot_stats
        SET total_users=total_users+1
        WHERE id=1
        """
    )

    con.commit()
    con.close()

    return True


def touch(user):

    con = connect()

    con.execute(
        """
        UPDATE users
        SET username=?,
            last_seen=?,
            blocked=0
        WHERE id=?
        """,
        (
            user.username,
            now(),
            user.id
        )
    )

    con.commit()
    con.close()


def get_user(user_id):

    con = connect()

    row = con.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (user_id,)
    ).fetchone()

    con.close()

    return row


def add_points(
    user_id,
    amount
):

    con = connect()

    con.execute(
        """
        UPDATE users
        SET points=points+?
        WHERE id=?
        """,
        (
            amount,
            user_id
        )
    )

    con.commit()
    con.close()


def reward_referral(user_id):

    con = connect()

    row = con.execute(
        """
        SELECT referred_by,
               referral_rewarded
        FROM users
        WHERE id=?
        """,
        (user_id,)
    ).fetchone()

    if not row:

        con.close()
        return

    referrer = row["referred_by"]
    rewarded = row["referral_rewarded"]

    if referrer and not rewarded:

        con.execute(
            """
            UPDATE users
            SET points=points+?,
                referral_rewarded=1
            WHERE id=?
            """,
            (
                REFERRAL_REWARD,
                referrer
            )
        )

        con.execute(
            """
            UPDATE users
            SET referrals=referrals+1
            WHERE id=?
            """,
            (referrer,)
        )

        con.commit()

    con.close()


# ============================================================
# SPONSOR
# ============================================================

async def subscribed(
    user_id,
    context
):

    if user_id == ADMIN_ID:
        return True

    for channel in SPONSORS:

        try:

            member = await context.bot.get_chat_member(
                channel,
                user_id
            )

            ok = member.status in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER
            )

            if not ok:
                return False

        except Exception:

            return False

    return True


def subscription_message():

    text = (
        "💎 <b>PREMIUM BONUS</b>\n\n"
        "⭐ Botdan foydalanish uchun "
        "quyidagi 2 ta kanalga obuna bo‘ling.\n\n"
        "💎 <b>1-KANAL</b>\n"
        "💎 <b>2-KANAL</b>\n\n"
        "🔥 Ikkala kanalga obuna bo‘lgach, "
        "<b>OBUNANI TEKSHIRISH</b> tugmasini bosing.\n\n"
        "✨ <i>Premium imkoniyatlar sizni kutmoqda!</i>"
    )

    keyboard = [

        [
            InlineKeyboardButton(
                "💎 1-KANALGA OBUNA",
                url="https://t.me/premyumstarstekin"
            )
        ],

        [
            InlineKeyboardButton(
                "🎮 2-KANALGA OBUNA",
                url="https://t.me/PubgPPSavdoChat1"
            )
        ],

        [
            InlineKeyboardButton(
                "✅ OBUNANI TEKSHIRISH",
                callback_data="check_sub"
            )
        ]

    ]

    return (
        text,
        InlineKeyboardMarkup(keyboard)
    )


async def require_sub(
    update,
    context
):

    user = update.effective_user

    if user.id == ADMIN_ID:
        return True

    if await subscribed(
        user.id,
        context
    ):
        return True

    text, markup = subscription_message()

    if update.callback_query:

        try:

            await update.callback_query.message.edit_text(
                text,
                reply_markup=markup,
                parse_mode="HTML"
            )

        except TelegramError:
            pass

    elif update.message:

        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML"
        )

    return False


# ============================================================
# HOME
# ============================================================

def home_markup(user_id):

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
                callback_data="stars_work"
            )
        ],

        [
            InlineKeyboardButton(
                "🎮 O‘YINLAR",
                callback_data="games"
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
                callback_data="top"
            )
        ],

        [
            InlineKeyboardButton(
                "👤 PROFIL",
                callback_data="profile"
            )
        ]

    ]

    if user_id == ADMIN_ID:

        rows.append([
            InlineKeyboardButton(
                "⚙️ ADMIN PANEL",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(rows)


async def home(
    update,
    context
):

    user = update.effective_user

    text = (
        "💎 <b>ZERIKDIM GAMES</b>\n\n"
        "⭐ Stars ishlang va balansingizni "
        "boshqaring.\n\n"
        "👇 Kerakli bo‘limni tanlang:"
    )

    if update.callback_query:

        await update.callback_query.message.edit_text(
            text,
            reply_markup=home_markup(
                user.id
            ),
            parse_mode="HTML"
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=home_markup(
                user.id
            ),
            parse_mode="HTML"
        )


# ============================================================
# BALANCE
# ============================================================

async def balance(
    update,
    context
):

    user = update.effective_user

    row = get_user(
        user.id
    )

    points = float(
        row["points"]
        if row
        else 0
    )

    text = (
        "💰 <b>BALANS</b>\n\n"
        f"⭐ Stars: <b>{points:g}</b>\n\n"
        "🎯 O‘yinlarda yutib Stars yig‘ing."
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎯 STARS ISHLASH",
                    callback_data="stars_work"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 ORQAGA",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# ============================================================
# PROFILE
# ============================================================

async def profile(
    update,
    context
):

    user = update.effective_user

    row = get_user(
        user.id
    )

    if not row:
        return

    text = (
        "👤 <b>PROFIL</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Username: "
        f"@{user.username if user.username else 'yo‘q'}\n\n"
        f"⭐ Stars: <b>{float(row['points']):g}</b>\n"
        f"🎮 O‘yinlar: <b>{row['games']}</b>\n"
        f"🏆 G‘alabalar: <b>{row['wins']}</b>\n"
        f"👥 Referallar: <b>{row['referrals']}</b>"
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 ORQAGA",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# ============================================================
# REFERRAL
# ============================================================

async def referral(
    update,
    context
):

    user = update.effective_user

    row = get_user(
        user.id
    )

    referrals = (
        row["referrals"]
        if row
        else 0
    )

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{user.id}"
    )

    text = (
        "👥 <b>REFERAL</b>\n\n"
        f"👤 Taklif qilganlaringiz: "
        f"<b>{referrals}</b>\n"
        f"⭐ Har bir faol referral: "
        f"<b>+{REFERRAL_REWARD:g} ⭐</b>\n\n"
        "🔗 Sizning referral havolangiz:\n"
        f"<code>{link}</code>"
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📤 ULASHISH",
                    switch_inline_query=link
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 ORQAGA",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# ============================================================
# TOP
# ============================================================

async def top(
    update,
    context
):

    con = connect()

    rows = con.execute(
        """
        SELECT username,
               points,
               wins
        FROM users
        ORDER BY points DESC
        LIMIT 10
        """
    ).fetchall()

    con.close()

    text = (
        "🏆 <b>TOP REYTING</b>\n\n"
    )

    if not rows:

        text += "Hozircha ma’lumot yo‘q."

    else:

        for i, row in enumerate(
            rows,
            start=1
        ):

            name = (
                f"@{row['username']}"
                if row["username"]
                else "Noma’lum"
            )

            text += (
                f"{i}. {name} — "
                f"⭐ {float(row['points']):g}\n"
            )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 ORQAGA",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# ============================================================
# STARS WORK
# ============================================================

def stars_work_markup():

    rows = [

        [
            InlineKeyboardButton(
                "🎯 DARTS",
                callback_data="casino_dice"
            ),
            InlineKeyboardButton(
                "🎲 ZAR",
                callback_data="casino_coin"
            )
        ],

        [
            InlineKeyboardButton(
                "🎯 NISHON",
                callback_data="casino_target"
            ),
            InlineKeyboardButton(
                "🃏 KARTA",
                callback_data="casino_card"
            )
        ],

        [
            InlineKeyboardButton(
                "🎰 SLOT",
                callback_data="casino_slot"
            ),
            InlineKeyboardButton(
                "🎡 OMAD",
                callback_data="casino_wheel"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 ORQAGA",
                callback_data="home"
            )
        ]

    ]

    return InlineKeyboardMarkup(rows)


async def stars_work(
    update,
    context
):

    text = (
        "🎯 <b>STARS ISHLASH</b>\n\n"
        "⭐ O‘yin tanlang.\n"
        f"🎁 G‘alaba: <b>+{GAME_REWARD:g} ⭐</b>\n\n"
        "⚠️ Harakatlar orasida vaqt cheklovi bor."
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=stars_work_markup(),
        parse_mode="HTML"
    )


async def stars_work_game(
    update,
    context,
    data
):

    user = update.effective_user

    last = context.user_data.get(
        "stars_work_last"
    )

    if last:

        elapsed = (
            datetime.now(timezone.utc)
            - last
        ).total_seconds()

        if elapsed < 30:

            remain = int(
                30 - elapsed
            )

            await update.callback_query.answer(
                f"⏳ {remain} soniya kuting.",
                show_alert=True
            )

            return

    context.user_data[
        "stars_work_last"
    ] = datetime.now(timezone.utc)

    row = get_user(
        user.id
    )

    if not row:
        return

    con = connect()

    con.execute(
        """
        UPDATE users
        SET games=games+1
        WHERE id=?
        """,
        (user.id,)
    )

    con.commit()
    con.close()

    if data == "casino_dice":

        msg = await context.bot.send_dice(
            chat_id=user.id,
            emoji="🎯"
        )

        value = msg.dice.value

        if value >= 4:

            add_points(
                user.id,
                GAME_REWARD
            )

            con = connect()

            con.execute(
                """
                UPDATE users
                SET wins=wins+1
                WHERE id=?
                """,
                (user.id,)
            )

            con.commit()
            con.close()

            result = (
                "🎯 <b>G‘ALABA!</b>\n\n"
                f"⭐ +{GAME_REWARD:g}"
            )

        else:

            result = (
                "🎯 <b>Yutqazdingiz.</b>\n\n"
                "Yana urinib ko‘ring."
            )

        await context.bot.send_message(
            user.id,
            result,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎯 YANA O‘YNASH",
                        callback_data=data
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="stars_work"
                    )
                ]
            ])
        )

        return

    if data == "casino_coin":

        value = random.choice(
            ["🟢", "🔴"]
        )

        win = value == "🟢"

        if win:

            add_points(
                user.id,
                GAME_REWARD
            )

            con = connect()

            con.execute(
                """
                UPDATE users
                SET wins=wins+1
                WHERE id=?
                """,
                (user.id,)
            )

            con.commit()
            con.close()

            result = (
                f"🎲 Natija: {value}\n\n"
                "🏆 <b>G‘ALABA!</b>\n"
                f"⭐ +{GAME_REWARD:g}"
            )

        else:

            result = (
                f"🎲 Natija: {value}\n\n"
                "❌ Yutqazdingiz."
            )

        await context.bot.send_message(
            user.id,
            result,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎲 YANA",
                        callback_data=data
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="stars_work"
                    )
                ]
            ])
        )

        return

    choices = {

        "casino_target": [
            "🎯",
            "❌",
            "❌"
        ],

        "casino_card": [
            "🃏",
            "❌",
            "❌"
        ],

        "casino_slot": [
            "🎰",
            "❌",
            "❌"
        ],

        "casino_wheel": [
            "⭐",
            "❌",
            "❌"
        ]

    }

    options = choices.get(
        data,
        ["⭐", "❌", "❌"]
    )

    selected = random.choice(
        options
    )

    if selected == options[0]:

        add_points(
            user.id,
            GAME_REWARD
        )

        con = connect()

        con.execute(
            """
            UPDATE users
            SET wins=wins+1
            WHERE id=?
            """,
            (user.id,)
        )

        con.commit()
        con.close()

        result = (
            f"🎮 Natija: {selected}\n\n"
            "🏆 <b>G‘ALABA!</b>\n"
            f"⭐ +{GAME_REWARD:g}"
        )

    else:

        result = (
            f"🎮 Natija: {selected}\n\n"
            "❌ Yutqazdingiz."
        )

    await context.bot.send_message(
        user.id,
        result,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 YANA O‘YNASH",
                    callback_data=data
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 ORQAGA",
                    callback_data="stars_work"
                )
            ]
        ])
    )


# ============================================================
# GAMES
# ============================================================

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


def games_markup():

    rows = []

    for name, code in GAMES:

        rows.append([
            InlineKeyboardButton(
                name,
                callback_data=f"game_{code}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "🔙 ORQAGA",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(rows)


async def games(
    update,
    context
):

    await update.callback_query.message.edit_text(
        "🎮 <b>O‘YINLAR</b>\n\n"
        "⭐ O‘ynang va Stars yig‘ing.\n\n"
        "👇 O‘yinni tanlang:",
        reply_markup=games_markup(),
        parse_mode="HTML"
    )


def question_data(code):

    if code == "quiz":

        items = [

            (
                "O‘zbekiston poytaxti qaysi?",
                [
                    "Toshkent",
                    "Samarqand",
                    "Buxoro"
                ],
                0
            ),

            (
                "1 haftada necha kun bor?",
                [
                    "5",
                    "7",
                    "9"
                ],
                1
            ),

            (
                "2 + 2 nechchi?",
                [
                    "3",
                    "4",
                    "5"
                ],
                1
            ),

            (
                "Yerning tabiiy yo‘ldoshi nima?",
                [
                    "Oy",
                    "Quyosh",
                    "Mars"
                ],
                0
            ),

            (
                "Bir yilda necha oy bor?",
                [
                    "10",
                    "11",
                    "12"
                ],
                2
            )

        ]

        return random.choice(items)

    if code == "logic":

        items = [

            (
                "2, 4, 6, 8, ?",
                [
                    "9",
                    "10",
                    "12"
                ],
                1
            ),

            (
                "5, 10, 15, ?",
                [
                    "18",
                    "20",
                    "25"
                ],
                1
            ),

            (
                "1, 4, 9, 16, ?",
                [
                    "20",
                    "24",
                    "25"
                ],
                2
            )

        ]

        return random.choice(items)

    if code == "knowledge":

        items = [

            (
                "Quyosh nima?",
                [
                    "Yulduz",
                    "Sayyora",
                    "Oy"
                ],
                0
            ),

            (
                "Suvning formulasi?",
                [
                    "CO2",
                    "H2O",
                    "O2"
                ],
                1
            ),

            (
                "Eng katta okean?",
                [
                    "Atlantika",
                    "Hind",
                    "Tinch"
                ],
                2
            )

        ]

        return random.choice(items)

    return None


async def start_game(
    update,
    context,
    code
):

    user = update.effective_user

    last = context.user_data.get(
        "game_last"
    )

    if last:

        elapsed = (
            datetime.now(timezone.utc)
            - last
        ).total_seconds()

        if elapsed < 30:

            remain = int(
                30 - elapsed
            )

            await update.callback_query.answer(
                f"⏳ {remain} soniya kuting.",
                show_alert=True
            )

            return

    context.user_data[
        "game_last"
    ] = datetime.now(timezone.utc)

    if code in (
        "quiz",
        "logic",
        "knowledge"
    ):

        data = question_data(
            code
        )

        if not data:
            return

        question, answers, correct = data

        context.user_data[
            "game_answer"
        ] = correct

        context.user_data[
            "game_type"
        ] = code

        keyboard = []

        for i, answer in enumerate(
            answers
        ):

            keyboard.append([
                InlineKeyboardButton(
                    answer,
                    callback_data=f"answer_{i}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "🔙 ORQAGA",
                callback_data="games"
            )
        ])

        await update.callback_query.message.edit_text(
            f"🧠 <b>{question}</b>\n\n"
            "Javobni tanlang:",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML"
        )

        return

    if code == "number":

        number = random.randint(
            1,
            5
        )

        context.user_data[
            "number_answer"
        ] = number

        await update.callback_query.message.edit_text(
            "🔢 <b>SONNI TOP</b>\n\n"
            "1 dan 5 gacha son o‘yladim.\n"
            "Javobingizni raqam qilib yuboring.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="games"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    if code == "choice":

        values = [
            "A",
            "B",
            "C"
        ]

        correct = random.choice(
            values
        )

        context.user_data[
            "choice_answer"
        ] = correct

        await update.callback_query.message.edit_text(
            "⚡ <b>TEZ TANLA</b>\n\n"
            "To‘g‘ri variantni tanlang:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🅰️ A",
                        callback_data="choice_A"
                    ),
                    InlineKeyboardButton(
                        "🅱️ B",
                        callback_data="choice_B"
                    ),
                    InlineKeyboardButton(
                        "©️ C",
                        callback_data="choice_C"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="games"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    if code == "target":

        correct = random.randint(
            1,
            3
        )

        context.user_data[
            "target_answer"
        ] = correct

        await update.callback_query.message.edit_text(
            "🎯 <b>NISHON</b>\n\n"
            "Qaysi nishon yashirilgan?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎯 1",
                        callback_data="target_1"
                    ),
                    InlineKeyboardButton(
                        "🎯 2",
                        callback_data="target_2"
                    ),
                    InlineKeyboardButton(
                        "🎯 3",
                        callback_data="target_3"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="games"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    if code == "word":

        words = [
            "kitob",
            "maktab",
            "telegram",
            "stars",
            "o‘yin"
        ]

        word = random.choice(
            words
        )

        context.user_data[
            "word_answer"
        ] = word

        await update.callback_query.message.edit_text(
            "🔤 <b>SO‘ZNI TOP</b>\n\n"
            "Quyidagi so‘zni aynan yozing:\n\n"
            f"👉 <b>{word}</b>",
            parse_mode="HTML"
        )

        return

    if code == "math":

        a = random.randint(
            2,
            15
        )

        b = random.randint(
            2,
            15
        )

        context.user_data[
            "math_answer"
        ] = a + b

        await update.callback_query.message.edit_text(
            "🧮 <b>HISOBLA</b>\n\n"
            f"{a} + {b} = ?\n\n"
            "Javobni yuboring:",
            parse_mode="HTML"
        )

        return

    if code == "attention":

        values = list(
            range(1, 10)
        )

        special = random.choice(
            values
        )

        random.shuffle(
            values
        )

        context.user_data[
            "attention_answer"
        ] = special

        text = (
            "👀 <b>DIQQAT</b>\n\n"
            "Quyidagi raqamlardan maxsus "
            "raqamni toping:\n\n"
            + " ".join(
                map(str, values)
            )
        )

        await update.callback_query.message.edit_text(
            text,
            parse_mode="HTML"
        )

        return

    if code == "color":

        colors = [
            "🔴 QIZIL",
            "🟢 YASHIL",
            "🔵 KO‘K",
            "🟡 SARIQ"
        ]

        correct = random.choice(
            colors
        )

        context.user_data[
            "color_answer"
        ] = correct

        shuffled = colors[:]

        random.shuffle(
            shuffled
        )

        keyboard = []

        for color in shuffled:

            keyboard.append([
                InlineKeyboardButton(
                    color,
                    callback_data=(
                        "color_"
                        + str(
                            colors.index(color)
                        )
                    )
                )
            ])

        await update.callback_query.message.edit_text(
            "🎨 <b>RANGNI TOP</b>\n\n"
            f"Toping: <b>{correct}</b>",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML"
        )

        return

    if code == "code":

        digits = "".join(
            random.choices(
                "123456789",
                k=3
            )
        )

        context.user_data[
            "code_answer"
        ] = digits

        await update.callback_query.message.edit_text(
            "🔐 <b>KODNI TOP</b>\n\n"
            f"Kod: <code>{digits}</code>\n\n"
            "Kodni qayta yuboring:",
            parse_mode="HTML"
        )

        return

    if code == "speed":

        a = random.randint(
            10,
            50
        )

        b = random.randint(
            10,
            50
        )

        context.user_data[
            "speed_answer"
        ] = a - b

        await update.callback_query.message.edit_text(
            "⏱ <b>TEZLIK</b>\n\n"
            f"{a} - {b} = ?",
            parse_mode="HTML"
        )

        return


# ============================================================
# GAME ANSWERS
# ============================================================

async def process_game_answer(
    update,
    context
):

    user = update.effective_user

    text = update.message.text.strip()

    answer = None
    correct = None

    game_type = context.user_data.get(
        "game_type"
    )

    if game_type in (
        "quiz",
        "logic",
        "knowledge"
    ):
        return False

    if "number_answer" in context.user_data:

        try:

            answer = int(text)

        except ValueError:

            await update.message.reply_text(
                "❌ Raqam yuboring."
            )

            return True

        correct = context.user_data.pop(
            "number_answer"
        )

    elif "word_answer" in context.user_data:

        answer = text.lower()

        correct = context.user_data.pop(
            "word_answer"
        ).lower()

    elif "math_answer" in context.user_data:

        try:

            answer = int(text)

        except ValueError:

            await update.message.reply_text(
                "❌ Raqam yuboring."
            )

            return True

        correct = context.user_data.pop(
            "math_answer"
        )

    elif "code_answer" in context.user_data:

        answer = text

        correct = context.user_data.pop(
            "code_answer"
        )

    elif "speed_answer" in context.user_data:

        try:

            answer = int(text)

        except ValueError:

            await update.message.reply_text(
                "❌ Raqam yuboring."
            )

            return True

        correct = context.user_data.pop(
            "speed_answer"
        )

    else:

        return False

    con = connect()

    con.execute(
        """
        UPDATE users
        SET games=games+1
        WHERE id=?
        """,
        (user.id,)
    )

    con.commit()
    con.close()

    if answer == correct:

        add_points(
            user.id,
            GAME_REWARD
        )

        con = connect()

        con.execute(
            """
            UPDATE users
            SET wins=wins+1
            WHERE id=?
            """,
            (user.id,)
        )

        con.commit()
        con.close()

        await update.message.reply_text(
            "🏆 <b>TO‘G‘RI!</b>\n\n"
            f"⭐ +{GAME_REWARD:g}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎮 O‘YINLAR",
                        callback_data="games"
                    )
                ]
            ])
        )

    else:

        await update.message.reply_text(
            "❌ <b>NOTO‘G‘RI!</b>\n\n"
            f"To‘g‘ri javob: "
            f"<b>{correct}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎮 O‘YINLAR",
                        callback_data="games"
                    )
                ]
            ])
        )

    return True


# ============================================================
# TASKS
# ============================================================

def get_tasks():

    con = connect()

    rows = con.execute(
        """
        SELECT id,
               channel,
               reward
        FROM tasks
        ORDER BY id
        """
    ).fetchall()

    con.close()

    return rows


async def tasks(
    update,
    context
):

    rows = get_tasks()

    text = (
        "🎁 <b>TOPSHIRIQLAR</b>\n\n"
        "Kanalga obuna bo‘ling va mukofot oling.\n\n"
    )

    keyboard = []

    for i, row in enumerate(
        rows,
        start=1
    ):

        channel = row["channel"]

        keyboard.append([
            InlineKeyboardButton(
                f"💎 {i}- KANALGA OBUNA",
                url=(
                    "https://t.me/"
                    + channel.lstrip("@")
                )
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                f"✅ {i}- TEKSHIRISH",
                callback_data=(
                    f"claimtask:{row['id']}"
                )
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 ORQAGA",
            callback_data="home"
        )
    ])

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
        parse_mode="HTML"
    )


async def claim_task(
    update,
    context,
    task_id
):

    user = update.effective_user

    con = connect()

    task = con.execute(
        """
        SELECT id,
               channel,
               reward
        FROM tasks
        WHERE id=?
        """,
        (task_id,)
    ).fetchone()

    if not task:

        con.close()

        await update.callback_query.answer(
            "❌ Topshiriq topilmadi.",
            show_alert=True
        )

        return

    claimed = con.execute(
        """
        SELECT 1
        FROM task_claims
        WHERE user_id=?
          AND task_id=?
        """,
        (
            user.id,
            task_id
        )
    ).fetchone()

    if claimed:

        con.close()

        await update.callback_query.answer(
            "⚠️ Bu topshiriq allaqachon olingan.",
            show_alert=True
        )

        return

    con.close()

    try:

        member = await context.bot.get_chat_member(
            task["channel"],
            user.id
        )

        ok = member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        )

    except Exception:

        ok = False

    if not ok:

        await update.callback_query.answer(
            "❌ Avval kanalga obuna bo‘ling.",
            show_alert=True
        )

        return

    con = connect()

    con.execute(
        """
        INSERT INTO task_claims(
            user_id,
            task_id,
            claimed_at
        )
        VALUES(?,?,?)
        """,
        (
            user.id,
            task_id,
            now()
        )
    )

    con.execute(
        """
        UPDATE users
        SET points=points+?
        WHERE id=?
        """,
        (
            task["reward"],
            user.id
        )
    )

    con.commit()
    con.close()

    await update.callback_query.answer(
        f"🎉 +{float(task['reward']):g} ⭐ qo‘shildi!",
        show_alert=True
    )

    await tasks(
        update,
        context
    )


# ============================================================
# WITHDRAW
# ============================================================

async def withdraw(
    update,
    context
):

    user = update.effective_user

    row = get_user(
        user.id
    )

    points = float(
        row["points"]
        if row
        else 0
    )

    referrals = int(
        row["referrals"]
        if row
        else 0
    )

    if points < MIN_WITHDRAW:

        await update.callback_query.message.edit_text(
            "💸 <b>YECHIB OLISH</b>\n\n"
            f"⭐ Minimal balans: "
            f"<b>{MIN_WITHDRAW:g}</b>\n"
            f"💰 Sizda: <b>{points:g}</b> ⭐\n\n"
            "Avval Stars yig‘ing.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    if referrals < MIN_REFERRALS:

        await update.callback_query.message.edit_text(
            "💸 <b>YECHIB OLISH</b>\n\n"
            f"👥 Minimal referral: "
            f"<b>{MIN_REFERRALS}</b>\n"
            f"👤 Sizda: <b>{referrals}</b>\n\n"
            "Referral sonini to‘ldiring.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "👥 REFERAL",
                        callback_data="ref"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    context.user_data[
        "withdraw_mode"
    ] = True

    await update.callback_query.message.edit_text(
        "💸 <b>YECHIB OLISH</b>\n\n"
        "Qancha ⭐ yechmoqchi ekaningizni "
        "raqamda yuboring.\n\n"
        f"Minimal: <b>{MIN_WITHDRAW:g} ⭐</b>\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML"
    )


async def process_withdraw(
    update,
    context
):

    if not context.user_data.get(
        "withdraw_mode"
    ):
        return False

    user = update.effective_user

    try:

        amount = float(
            update.message.text.strip()
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Faqat raqam yuboring."
        )

        return True

    row = get_user(
        user.id
    )

    if not row:
        return True

    balance_value = float(
        row["points"]
    )

    referrals = int(
        row["referrals"]
    )

    if amount < MIN_WITHDRAW:

        await update.message.reply_text(
            f"❌ Minimal yechish: "
            f"{MIN_WITHDRAW:g} ⭐"
        )

        return True

    if amount > balance_value:

        await update.message.reply_text(
            "❌ Balansingiz yetarli emas."
        )

        return True

    if referrals < MIN_REFERRALS:

        await update.message.reply_text(
            f"❌ Kamida {MIN_REFERRALS} ta referral kerak."
        )

        return True

    con = connect()

    con.execute(
        """
        UPDATE users
        SET points=points-?
        WHERE id=?
        """,
        (
            amount,
            user.id
        )
    )

    cur = con.execute(
        """
        INSERT INTO withdrawals(
            user_id,
            username,
            amount,
            status,
            created_at
        )
        VALUES(?,?,?,?,?)
        """,
        (
            user.id,
            user.username,
            amount,
            "pending",
            now()
        )
    )

    withdrawal_id = cur.lastrowid

    con.commit()
    con.close()

    context.user_data.pop(
        "withdraw_mode",
        None
    )

    await update.message.reply_text(
        "✅ <b>So‘rovingiz muvaffaqiyatli qabul qilindi!</b>\n\n"
        f"⭐ Miqdor: <b>{amount:g}</b>\n"
        f"🆔 So‘rov: <code>#{withdrawal_id}</code>\n\n"
        "⏳ 24 soat ichida ko‘rib chiqiladi.",
        parse_mode="HTML"
    )

    try:

        await context.bot.send_message(
            ADMIN_ID,
            "💸 <b>YANGI YECHISH SO‘ROVI</b>\n\n"
            f"🆔 So‘rov: <code>#{withdrawal_id}</code>\n"
            f"👤 User: <code>{user.id}</code>\n"
            f"👤 Username: @{user.username or 'yo‘q'}\n"
            f"⭐ Miqdor: <b>{amount:g}</b>",
            parse_mode="HTML"
        )

    except Exception:
        pass

    return True


# ============================================================
# ADMIN
# ============================================================

def admin_markup():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📊 STATISTIKA",
                callback_data="astats"
            )
        ],

        [
            InlineKeyboardButton(
                "👥 FOYDALANUVCHILAR",
                callback_data="users:0"
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
                "🎁 TOPSHIRIQLAR",
                callback_data="taskadmin"
            )
        ],

        [
            InlineKeyboardButton(
                "📢 HOMIY KANALLAR",
                callback_data="sponsorinfo"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 ORQAGA",
                callback_data="home"
            )
        ]

    ])


async def admin(
    update,
    context
):

    user = update.effective_user

    if user.id != ADMIN_ID:

        await update.callback_query.answer(
            "❌ Ruxsat yo‘q!",
            show_alert=True
        )

        return

    await update.callback_query.message.edit_text(
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        "👑 Faqat admin uchun.",
        reply_markup=admin_markup(),
        parse_mode="HTML"
    )


async def admin_stats(
    update,
    context
):

    user = update.effective_user

    if user.id != ADMIN_ID:

        await update.callback_query.answer(
            "❌ Ruxsat yo‘q!",
            show_alert=True
        )

        return

    con = connect()

    total = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    active = con.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE last_seen >= ?
        """,
        (
            (
                datetime.now(timezone.utc)
                - timedelta(days=1)
            ).isoformat(),
        )
    ).fetchone()[0]

    pending = con.execute(
        """
        SELECT COUNT(*)
        FROM withdrawals
        WHERE status='pending'
        """
    ).fetchone()[0]

    con.close()

    all_time = get_total_users()

    text = (
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Hozirgi foydalanuvchilar: <b>{total}</b>\n"
        f"📈 Umumiy foydalanuvchilar: <b>{all_time}</b>\n"
        f"🟢 24 soat faol: <b>{active}</b>\n"
        f"💸 Kutilayotgan yechishlar: <b>{pending}</b>"
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 YANGILASH",
                    callback_data="astats"
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


async def users_page(
    update,
    context,
    page=0
):

    user = update.effective_user

    if user.id != ADMIN_ID:

        await update.callback_query.answer(
            "❌ Ruxsat yo‘q!",
            show_alert=True
        )

        return

    offset = page * USERS_PER_PAGE

    con = connect()

    rows = con.execute(
        """
        SELECT id,
               username,
               points
        FROM users
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (
            USERS_PER_PAGE,
            offset
        )
    ).fetchall()

    total = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    con.close()

    text = (
        "👥 <b>FOYDALANUVCHILAR</b>\n\n"
        f"Jami: <b>{total}</b>\n\n"
    )

    if not rows:

        text += "Foydalanuvchilar yo‘q."

    else:

        for row in rows:

            name = (
                f"@{row['username']}"
                if row["username"]
                else "no_username"
            )

            text += (
                f"🆔 <code>{row['id']}</code>\n"
                f"👤 {name}\n"
                f"⭐ {float(row['points']):g}\n\n"
            )

    buttons = []

    if page > 0:

        buttons.append(
            InlineKeyboardButton(
                "⬅️",
                callback_data=f"users:{page-1}"
            )
        )

    if offset + USERS_PER_PAGE < total:

        buttons.append(
            InlineKeyboardButton(
                "➡️",
                callback_data=f"users:{page+1}"
            )
        )

    keyboard = []

    if buttons:
        keyboard.append(buttons)

    keyboard.append([
        InlineKeyboardButton(
            "🔙 ADMIN",
            callback_data="admin"
        )
    ])

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
        parse_mode="HTML"
    )


# ============================================================
# BROADCAST
# ============================================================

async def broadcast_start(
    update,
    context
):

    user = update.effective_user

    if user.id != ADMIN_ID:

        await update.callback_query.answer(
            "❌ Ruxsat yo‘q!",
            show_alert=True
        )

        return

    context.user_data[
        "broadcast_mode"
    ] = True

    await update.callback_query.message.edit_text(
        "📢 <b>XABAR YUBORISH</b>\n\n"
        "Barcha bot foydalanuvchilariga yubormoqchi "
        "bo‘lgan xabaringizni yuboring.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML"
    )


async def do_broadcast(
    update,
    context
):

    if not context.user_data.get(
        "broadcast_mode"
    ):
        return False

    user = update.effective_user

    if user.id != ADMIN_ID:
        return False

    message = update.message

    con = connect()

    rows = con.execute(
        "SELECT id FROM users"
    ).fetchall()

    con.close()

    success = 0
    failed = 0

    for row in rows:

        try:

            await context.bot.copy_message(
                chat_id=row["id"],
                from_chat_id=message.chat_id,
                message_id=message.message_id
            )

            success += 1

        except RetryAfter as e:

            await asyncio.sleep(
                float(e.retry_after)
            )

            try:

                await context.bot.copy_message(
                    chat_id=row["id"],
                    from_chat_id=message.chat_id,
                    message_id=message.message_id
                )

                success += 1

            except Exception:

                failed += 1

        except Forbidden:

            failed += 1

            con = connect()

            con.execute(
                """
                UPDATE users
                SET blocked=1
                WHERE id=?
                """,
                (row["id"],)
            )

            con.commit()
            con.close()

        except Exception:

            failed += 1

        await asyncio.sleep(
            0.03
        )

    context.user_data.pop(
        "broadcast_mode",
        None
    )

    await update.message.reply_text(
        "📢 <b>YUBORISH TUGADI</b>\n\n"
        f"✅ Yetkazildi: <b>{success}</b>\n"
        f"❌ Yetkazilmadi: <b>{failed}</b>",
        parse_mode="HTML"
    )

    return True


# ============================================================
# TASK ADMIN
# ============================================================

async def task_admin(
    update,
    context
):

    user = update.effective_user

    if user.id != ADMIN_ID:

        await update.callback_query.answer(
            "❌ Ruxsat yo‘q!",
            show_alert=True
        )

        return

    rows = get_tasks()

    text = (
        "🎁 <b>TOPSHIRIQLAR ADMIN</b>\n\n"
    )

    if not rows:

        text += "Topshiriqlar yo‘q."

    else:

        for row in rows:

            text += (
                f"🆔 {row['id']} | "
                f"{row['channel']} | "
                f"+{float(row['reward']):g} ⭐\n"
            )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 ADMIN",
                    callback_data="admin"
                )
            ]
        ]),
        parse_mode="HTML"
    )


async def sponsor_info(
    update,
    context
):

    user = update.effective_user

    if user.id != ADMIN_ID:

        await update.callback_query.answer(
            "❌ Ruxsat yo‘q!",
            show_alert=True
        )

        return

    text = (
        "📢 <b>HOMIY KANALLAR</b>\n\n"
        "💎 1. @premyumstarstekin\n"
        "🎮 2. @PubgPPSavdoChat1\n\n"
        "🔒 Faqat shu 2 ta kanal ishlatiladi.\n"
        "⚠️ Bot ikkala kanalga obunani tekshiradi."
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 ADMIN",
                    callback_data="admin"
                )
            ]
        ]),
        parse_mode="HTML"
    )


# ============================================================
# ADMIN TEXT
# ============================================================

async def admin_text(
    update,
    context
):

    user = update.effective_user

    if user.id != ADMIN_ID:
        return False

    if await do_broadcast(
        update,
        context
    ):
        return True

    return False


# ============================================================
# CALLBACK
# ============================================================

async def callback(
    update,
    context
):

    q = update.callback_query

    user = update.effective_user

    data = q.data

    # --------------------------------------------------------
    # CHECK SUB
    # --------------------------------------------------------

    if data == "check_sub":

        if await subscribed(
            user.id,
            context
        ):

            await q.answer(
                "✅ Obuna tasdiqlandi!",
                show_alert=True
            )

            try:

                await q.message.edit_text(
                    "✅ <b>Obuna tasdiqlandi!</b>\n\n"
                    "🎉 Botdan foydalanishingiz mumkin.",
                    parse_mode="HTML"
                )

            except TelegramError:
                pass

            await asyncio.sleep(
                0.5
            )

            await home(
                update,
                context
            )

        else:

            await q.answer(
                "❌ Ikkala kanalga ham obuna bo‘ling.",
                show_alert=True
            )

        return

    # --------------------------------------------------------
    # SUBSCRIPTION
    # --------------------------------------------------------

    if not await require_sub(
        update,
        context
    ):
        return

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    if data == "home":

        await q.answer()

        await home(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # BALANCE
    # --------------------------------------------------------

    if data == "balance":

        await q.answer()

        await balance(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # PROFILE
    # --------------------------------------------------------

    if data == "profile":

        await q.answer()

        await profile(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # REF
    # --------------------------------------------------------

    if data == "ref":

        await q.answer()

        await referral(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # TOP
    # --------------------------------------------------------

    if data == "top":

        await q.answer()

        await top(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # WITHDRAW
    # --------------------------------------------------------

    if data == "withdraw":

        await q.answer()

        await withdraw(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if data == "buy":

        await q.answer()

        await q.message.edit_text(
            "⭐ <b>STARS OLISH</b>\n\n"
            "👇 Stars olish uchun kerakli "
            "paketni tanlang:\n\n"
            "⭐ 50\n"
            "⭐ 100\n"
            "⭐ 200\n"
            "⭐ 500\n"
            "⭐ 1000\n"
            "⭐ 2000\n"
            "⭐ 5000\n\n"
            "✏️ Boshqa miqdor uchun admin "
            "bilan bog‘laning.",
            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "⭐ 50",
                        callback_data="buy:50"
                    ),
                    InlineKeyboardButton(
                        "⭐ 100",
                        callback_data="buy:100"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⭐ 200",
                        callback_data="buy:200"
                    ),
                    InlineKeyboardButton(
                        "⭐ 500",
                        callback_data="buy:500"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⭐ 1000",
                        callback_data="buy:1000"
                    ),
                    InlineKeyboardButton(
                        "⭐ 2000",
                        callback_data="buy:2000"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⭐ 5000",
                        callback_data="buy:5000"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "✏️ BOSHQA MIQDOR",
                        callback_data="buy_custom"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="home"
                    )
                ]

            ]),
            parse_mode="HTML"
        )

        return

    # --------------------------------------------------------
    # BUY AMOUNT
    # --------------------------------------------------------

    if data.startswith("buy:"):

        await q.answer()

        amount = data.split(
            ":",
            1
        )[1]

        await q.message.edit_text(
            f"⭐ <b>{amount} STARS</b>\n\n"
            "Telegram Stars orqali xarid qilish "
            "uchun quyidagi tugmani bosing.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⭐ STARS OLISH",
                        url=BUY_STARS
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="buy"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    # --------------------------------------------------------
    # CUSTOM BUY
    # --------------------------------------------------------

    if data == "buy_custom":

        await q.answer(
            "✏️ Boshqa miqdor uchun admin bilan bog‘laning.",
            show_alert=True
        )

        return

    # --------------------------------------------------------
    # STARS WORK
    # --------------------------------------------------------

    if data == "stars_work":

        await q.answer()

        await stars_work(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # STARS WORK GAMES
    # --------------------------------------------------------

    if data in (
        "casino_dice",
        "casino_coin",
        "casino_target",
        "casino_card",
        "casino_slot",
        "casino_wheel"
    ):

        await q.answer()

        await stars_work_game(
            update,
            context,
            data
        )

        return

    # --------------------------------------------------------
    # GAMES
    # --------------------------------------------------------

    if data == "games":

        await q.answer()

        await games(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # START GAME
    # --------------------------------------------------------

    if data.startswith("game_"):

        await q.answer()

        code = data.replace(
            "game_",
            "",
            1
        )

        await start_game(
            update,
            context,
            code
        )

        return

    # --------------------------------------------------------
    # QUIZ ANSWER
    # --------------------------------------------------------

    if data.startswith("answer_"):

        await q.answer()

        try:

            selected = int(
                data.split("_")[1]
            )

        except Exception:

            return

        correct = context.user_data.pop(
            "game_answer",
            None
        )

        context.user_data.pop(
            "game_type",
            None
        )

        if correct is None:
            return

        con = connect()

        con.execute(
            """
            UPDATE users
            SET games=games+1
            WHERE id=?
            """,
            (user.id,)
        )

        con.commit()
        con.close()

        if selected == correct:

            add_points(
                user.id,
                GAME_REWARD
            )

            con = connect()

            con.execute(
                """
                UPDATE users
                SET wins=wins+1
                WHERE id=?
                """,
                (user.id,)
            )

            con.commit()
            con.close()

            result = (
                "🏆 <b>TO‘G‘RI JAVOB!</b>\n\n"
                f"⭐ +{GAME_REWARD:g}"
            )

        else:

            result = (
                "❌ <b>NOTO‘G‘RI JAVOB!</b>\n\n"
                "Yana urinib ko‘ring."
            )

        await q.message.edit_text(
            result,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎮 O‘YINLAR",
                        callback_data="games"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 BOSH MENU",
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="HTML"
        )

        return

    # --------------------------------------------------------
    # CHOICE
    # --------------------------------------------------------

    if data.startswith("choice_"):

        await q.answer()

        selected = data.split(
            "_",
            1
        )[1]

        correct = context.user_data.pop(
            "choice_answer",
            None
        )

        if not correct:
            return

        con = connect()

        con.execute(
            """
            UPDATE users
            SET games=games+1
            WHERE id=?
            """,
            (user.id,)
        )

        con.commit()
        con.close()

        if selected == correct:

            add_points(
                user.id,
                GAME_REWARD
            )

            con = connect()

            con.execute(
                """
                UPDATE users
                SET wins=wins+1
                WHERE id=?
                """,
                (user.id,)
            )

            con.commit()
            con.close()

            text = (
                "⚡ <b>TO‘G‘RI!</b>\n\n"
                f"⭐ +{GAME_REWARD:g}"
            )

        else:

            text = (
                "⚡ <b>NOTO‘G‘RI!</b>\n\n"
                f"To‘g‘ri javob: {correct}"
            )

        await q.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⚡ YANA",
                        callback_data="game_choice"
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

        return

    # --------------------------------------------------------
    # TARGET
    # --------------------------------------------------------

    if data.startswith("target_"):

        await q.answer()

        try:

            selected = int(
                data.split("_")[1]
            )

        except Exception:

            return

        correct = context.user_data.pop(
            "target_answer",
            None
        )

        if correct is None:
            return

        con = connect()

        con.execute(
            """
            UPDATE users
            SET games=games+1
            WHERE id=?
            """,
            (user.id,)
        )

        con.commit()
        con.close()

        if selected == correct:

            add_points(
                user.id,
                GAME_REWARD
            )

            con = connect()

            con.execute(
                """
                UPDATE users
                SET wins=wins+1
                WHERE id=?
                """,
                (user.id,)
            )

            con.commit()
            con.close()

            text = (
                "🎯 <b>NISHON TOPILDI!</b>\n\n"
                f"⭐ +{GAME_REWARD:g}"
            )

        else:

            text = (
                "🎯 <b>NISHON TOPILMADI.</b>\n\n"
                f"To‘g‘ri nishon: {correct}"
            )

        await q.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎯 YANA",
                        callback_data="game_target"
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

        return

    # --------------------------------------------------------
    # COLOR
    # --------------------------------------------------------

    if data.startswith("color_"):

        await q.answer()

        try:

            selected = int(
                data.split("_")[1]
            )

        except Exception:

            return

        correct_text = context.user_data.pop(
            "color_answer",
            None
        )

        colors = [
            "🔴 QIZIL",
            "🟢 YASHIL",
            "🔵 KO‘K",
            "🟡 SARIQ"
        ]

        if correct_text is None:
            return

        correct = colors.index(
            correct_text
        )

        con = connect()

        con.execute(
            """
            UPDATE users
            SET games=games+1
            WHERE id=?
            """,
            (user.id,)
        )

        con.commit()
        con.close()

        if selected == correct:

            add_points(
                user.id,
                GAME_REWARD
            )

            con = connect()

            con.execute(
                """
                UPDATE users
                SET wins=wins+1
                WHERE id=?
                """,
                (user.id,)
            )

            con.commit()
            con.close()

            text = (
                "🎨 <b>TO‘G‘RI RANG!</b>\n\n"
                f"⭐ +{GAME_REWARD:g}"
            )

        else:

            text = (
                "🎨 <b>NOTO‘G‘RI!</b>\n\n"
                f"To‘g‘ri rang: {correct_text}"
            )

        await q.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎨 YANA",
                        callback_data="game_color"
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

        return

    # --------------------------------------------------------
    # TASK CLAIM
    # --------------------------------------------------------

    if data.startswith("claimtask:"):

        await q.answer()

        try:

            task_id = int(
                data.split(":")[1]
            )

        except Exception:

            await q.answer(
                "❌ Xato.",
                show_alert=True
            )

            return

        await claim_task(
            update,
            context,
            task_id
        )

        return

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if data == "admin":

        if user.id != ADMIN_ID:

            await q.answer(
                "❌ Ruxsat yo‘q!",
                show_alert=True
            )

            return

        await q.answer()

        await admin(
            update,
            context
        )

        return

    if data == "astats":

        if user.id != ADMIN_ID:

            await q.answer(
                "❌ Ruxsat yo‘q!",
                show_alert=True
            )

            return

        await q.answer()

        await admin_stats(
            update,
            context
        )

        return

    if data.startswith("users:"):

        if user.id != ADMIN_ID:

            await q.answer(
                "❌ Ruxsat yo‘q!",
                show_alert=True
            )

            return

        await q.answer()

        try:

            page = int(
                data.split(":")[1]
            )

        except Exception:

            page = 0

        await users_page(
            update,
            context,
            page
        )

        return

    if data == "broadcast":

        if user.id != ADMIN_ID:

            await q.answer(
                "❌ Ruxsat yo‘q!",
                show_alert=True
            )

            return

        await q.answer()

        await broadcast_start(
            update,
            context
        )

        return

    if data == "taskadmin":

        if user.id != ADMIN_ID:

            await q.answer(
                "❌ Ruxsat yo‘q!",
                show_alert=True
            )

            return

        await q.answer()

        await task_admin(
            update,
            context
        )

        return

    if data == "sponsorinfo":

        if user.id != ADMIN_ID:

            await q.answer(
                "❌ Ruxsat yo‘q!",
                show_alert=True
            )

            return

        await q.answer()

        await sponsor_info(
            update,
            context
        )

        return

    await q.answer(
        "❌ Noma’lum tugma.",
        show_alert=True
    )


# ============================================================
# START
# ============================================================

async def start(
    update,
    context
):

    user = update.effective_user

    referrer = None

    if context.args:

        arg = context.args[0]

        if arg.startswith("ref_"):

            try:

                referrer = int(
                    arg.replace(
                        "ref_",
                        ""
                    )
                )

            except ValueError:

                referrer = None

    created = await asyncio.to_thread(
        add_user,
        user,
        referrer
    )

    touch(user)

    if created:

        await update_profile_user_count(
            context.bot
        )

        await save_database()

    if not await subscribed(
        user.id,
        context
    ):

        text, markup = subscription_message()

        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML"
        )

        return

    reward_referral(
        user.id
    )

    await home(
        update,
        context
    )


# ============================================================
# USER ID
# ============================================================

async def my_id(
    update,
    context
):

    await update.message.reply_text(
        "🆔 Sizning Telegram ID: "
        f"<code>{update.effective_user.id}</code>",
        parse_mode="HTML"
    )


# ============================================================
# MESSAGE ROUTER
# ============================================================

async def message_handler(
    update,
    context
):

    user = update.effective_user

    if not user:
        return

    touch(user)

    # ADMIN MESSAGE
    if user.id == ADMIN_ID:

        handled = await admin_text(
            update,
            context
        )

        if handled:
            return

    # GAME ANSWER
    handled = await process_game_answer(
        update,
        context
    )

    if handled:
        return

    # WITHDRAW
    handled = await process_withdraw(
        update,
        context
    )

    if handled:
        return

    # SUBSCRIPTION
    if not await require_sub(
        update,
        context
    ):
        return

    await update.message.reply_text(
        "👇 Menyudan foydalaning:",
        reply_markup=home_markup(
            user.id
        )
    )


# ============================================================
# CANCEL
# ============================================================

async def cancel(
    update,
    context
):

    if update.effective_user.id == ADMIN_ID:

        context.user_data.clear()

        await update.message.reply_text(
            "❌ Bekor qilindi."
        )


# ============================================================
# POST INIT
# ============================================================

async def post_init(app):

    await update_profile_user_count(
        app.bot
    )

    app.bot_data[
        "backup_task"
    ] = asyncio.create_task(
        backup_loop()
    )

    await save_database()


# ============================================================
# POST SHUTDOWN
# ============================================================

async def post_shutdown(app):

    task = app.bot_data.get(
        "backup_task"
    )

    if task:

        task.cancel()

        try:

            await task

        except asyncio.CancelledError:
            pass

    await save_database()


# ============================================================
# MAIN
# ============================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN topilmadi! "
            "GitHub Secrets/Variables ga "
            "BOT_TOKEN qo‘ying."
        )

    if not ADMIN_ID:

        raise RuntimeError(
            "ADMIN_ID topilmadi! "
            "GitHub Secrets/Variables ga "
            "ADMIN_ID qo‘ying."
        )

    init_db()

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "cancel",
            cancel
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            my_id
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            callback
        )
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            message_handler
        )
    )

    logger.info(
        "ZERIKDIM BOT ISHLADI"
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
