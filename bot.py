import os
import sqlite3
import random
import asyncio
import logging
from datetime import datetime, timezone, timedelta
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
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "8679536810"))
except Exception:
    ADMIN_ID = 8679536810
DB_FILE = "zerikdim.db"
REFERRAL_REWARD = 9.0
GAME_REWARD = 0.02
TASK_REWARD = 5.0
MIN_WITHDRAW = 200.0
MIN_REFERRALS = 20
GAME_COOLDOWN = 30
PAGE_SIZE = 10
# =========================================================
# DOIMIY MAJBURIY HOMIY
# =========================================================
SPONSOR_CHANNEL = "@premyumstarstekin"
SPONSOR_URL = "https://t.me/premyumstarstekin"
BUY_STARS_URL = "https://t.me/premyumstarstekin/933"
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
# =========================================================
# DATABASE
# =========================================================
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn
def ensure_column(conn, table, column, definition):
    columns = [
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    ]
    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
def init_db():
    conn = db()
    conn.execute("""
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
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            reward REAL DEFAULT 5,
            url TEXT,
            channel TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_claims (
            user_id INTEGER,
            task_id INTEGER,
            created_at TEXT,
            PRIMARY KEY(user_id, task_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_stats (
            id INTEGER PRIMARY KEY,
            started_at TEXT,
            total_users INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sponsor_settings (
            id INTEGER PRIMARY KEY,
            active INTEGER DEFAULT 1,
            disabled_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            channel TEXT PRIMARY KEY,
            url TEXT
        )
    """)
    ensure_column(conn, "users", "username", "TEXT")
    ensure_column(conn, "users", "points", "REAL DEFAULT 0")
    ensure_column(conn, "users", "games", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "wins", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "referrals", "INTEGER DEFAULT 0")
    ensure_column(conn, "users", "referred_by", "INTEGER")
    ensure_column(conn, "users", "last_seen", "TEXT")
    ensure_column(conn, "users", "blocked", "INTEGER DEFAULT 0")
    ensure_column(
        conn,
        "users",
        "referral_rewarded",
        "INTEGER DEFAULT 0"
    )
    if conn.execute(
        "SELECT 1 FROM bot_stats WHERE id=1"
    ).fetchone() is None:
        conn.execute(
            """
            INSERT INTO bot_stats
            (id, started_at, total_users)
            VALUES (?, ?, ?)
            """,
            (
                1,
                datetime.now(timezone.utc).isoformat(),
                0,
            ),
        )
    if conn.execute(
        "SELECT 1 FROM sponsor_settings WHERE id=1"
    ).fetchone() is None:
        conn.execute(
            """
            INSERT INTO sponsor_settings
            (id, active, disabled_at)
            VALUES (1, 1, NULL)
            """
        )
    # =====================================================
    # FAQAT BIR DOIMIY HOMIY
    # =====================================================
    conn.execute(
        "DELETE FROM sponsors WHERE channel != ?",
        (SPONSOR_CHANNEL,)
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO sponsors(channel, url)
        VALUES (?, ?)
        """,
        (SPONSOR_CHANNEL, SPONSOR_URL),
    )
    # Har doim ON
    conn.execute(
        """
        UPDATE sponsor_settings
        SET active=1, disabled_at=NULL
        WHERE id=1
        """
    )
    conn.commit()
    conn.close()
# =========================================================
# UMUMIY FUNKSIYALAR
# =========================================================
def now_iso():
    return datetime.now(timezone.utc).isoformat()
def normalize_channel(channel):
    channel = (channel or "").strip()
    if not channel:
        return ""
    if channel.startswith("https://t.me/"):
        channel = channel.replace(
            "https://t.me/",
            "@",
            1
        )
    if not channel.startswith("@"):
        channel = "@" + channel
    return channel
def channel_url(channel):
    channel = normalize_channel(channel)
    if channel.startswith("@"):
        return "https://t.me/" + channel[1:]
    return channel
def get_total_users():
    conn = db()
    row = conn.execute(
        "SELECT total_users FROM bot_stats WHERE id=1"
    ).fetchone()
    conn.close()
    if not row:
        return 0
    return int(row["total_users"] or 0)
def sponsor_active():
    # DOIMIY HOMIY
    return True
def add_user(user_id, username):
    conn = db()
    existing = conn.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    is_new = existing is None
    if is_new:
        conn.execute(
            """
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
            VALUES (?, ?, 0, 0, 0, 0, NULL, ?, 0, 0)
            """,
            (
                user_id,
                username or "",
                now_iso(),
            ),
        )
        conn.execute(
            """
            UPDATE bot_stats
            SET total_users = total_users + 1
            WHERE id=1
            """
        )
    else:
        conn.execute(
            """
            UPDATE users
            SET username=?,
                last_seen=?,
                blocked=0
            WHERE id=?
            """,
            (
                username or "",
                now_iso(),
                user_id,
            ),
        )
    conn.commit()
    total = conn.execute(
        "SELECT total_users FROM bot_stats WHERE id=1"
    ).fetchone()["total_users"]
    conn.close()
    return is_new, int(total)
def get_user(user_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    return row
def add_points(user_id, amount):
    conn = db()
    conn.execute(
        """
        UPDATE users
        SET points = points + ?
        WHERE id=?
        """,
        (
            float(amount),
            user_id,
        ),
    )
    conn.commit()
    conn.close()
def get_points(user_id):
    row = get_user(user_id)
    if not row:
        return 0.0
    return float(row["points"] or 0)
def get_sponsors():
    conn = db()
    rows = conn.execute(
        """
        SELECT channel, url
        FROM sponsors
        ORDER BY channel
        """
    ).fetchall()
    conn.close()
    return rows
# =========================================================
# HOMIY TEKSHIRISH
# =========================================================
async def is_subscribed(bot, user_id, channel):
    try:
        member = await bot.get_chat_member(
            chat_id=channel,
            user_id=user_id,
        )
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except TelegramError as e:
        logger.warning(
            "Sponsor tekshirish xatosi %s: %s",
            channel,
            e,
        )
        return False
async def check_all_sponsors(bot, user_id):
    sponsors = get_sponsors()
    if not sponsors:
        return False
    for sponsor in sponsors:
        ok = await is_subscribed(
            bot,
            user_id,
            sponsor["channel"],
        )
        if not ok:
            return False
    return True
def sponsor_keyboard():
    buttons = [
        [
            InlineKeyboardButton(
                "📢 KANALGA OBUNA BO‘LISH",
                url=SPONSOR_URL,
            )
        ],
        [
            InlineKeyboardButton(
                "✅ TASDIQLASH",
                callback_data="check_sponsors",
            )
        ],
    ]
    return InlineKeyboardMarkup(buttons)
async def show_sponsor_required(update):
    text = (
        "🔒 <b>BOTDAN FOYDALANISH UCHUN OBUNA BO‘LING</b>\n\n"
        "📢 Avval quyidagi kanalga obuna bo‘ling:\n\n"
        "⭐ @premyumstarstekin\n\n"
        "Obuna bo‘lgach, "
        "<b>✅ TASDIQLASH</b> tugmasini bosing."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=sponsor_keyboard(),
        )
    else:
        await update.effective_message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=sponsor_keyboard(),
        )
# =========================================================
# ASOSIY MENU
# =========================================================
def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                "⭐ STARS OLISH",
                "🎯 STARS ISHLASH",
            ],
            [
                "🎮 O‘YINLAR",
                "💰 BALANS",
            ],
            [
                "🎁 TOPSHIRIQLAR",
                "👥 REFERAL",
            ],
            [
                "💸 YECHIB OLISH",
                "⭐ STARS SOTIB OLISH",
            ],
            [
                "🏆 REYTING",
                "👤 PROFIL",
            ],
        ],
        resize_keyboard=True,
    )
# =========================================================
# START
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new, total = add_user(
        user.id,
        user.username,
    )
    # Referal
    if is_new and context.args:
        arg = context.args[0]
        try:
            referrer_id = int(arg)
        except Exception:
            referrer_id = 0
        if (
            referrer_id
            and referrer_id != user.id
            and get_user(referrer_id)
        ):
            conn = db()
            conn.execute(
                """
                UPDATE users
                SET referred_by=?
                WHERE id=? AND referred_by IS NULL
                """,
                (
                    referrer_id,
                    user.id,
                ),
            )
            conn.execute(
                """
                UPDATE users
                SET referrals=referrals+1,
                    points=points+?
                WHERE id=?
                """,
                (
                    REFERRAL_REWARD,
                    referrer_id,
                ),
            )
            conn.commit()
            conn.close()
    # MAJBURIY HOMIY
    ok = await check_all_sponsors(
        context.bot,
        user.id,
    )
    if not ok:
        await show_sponsor_required(update)
        return
    await update.message.reply_text(
        "🎉 <b>TEKIN STARS BOT</b>\n\n"
        "Xush kelibsiz! ⭐\n\n"
        "Botdan foydalanishingiz mumkin.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )
# =========================================================
# STARS OLISH
# =========================================================
async def stars_get(update, context):
    text = (
        "⭐ <b>STARS OLISH</b>\n\n"
        "Topshiriqlar va referallar orqali Stars ishlashingiz mumkin.\n\n"
        f"💰 Balansingiz: "
        f"<b>{get_points(update.effective_user.id):.2f} ⭐</b>"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 TOPSHIRIQLAR",
                callback_data="tasks",
            )
        ],
        [
            InlineKeyboardButton(
                "👥 REFERAL",
                callback_data="referral",
            )
        ],
    ])
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
# =========================================================
# STARS ISHLASH
# =========================================================
async def stars_work(update, context):
    await update.message.reply_text(
        "🎯 <b>STARS ISHLASH</b>\n\n"
        "⭐ O‘yinlarda qatnashing\n"
        "🎁 Topshiriqlarni bajaring\n"
        "👥 Do‘stlaringizni taklif qiling\n\n"
        f"Har bir g‘alaba: <b>+{GAME_REWARD} ⭐</b>",
        parse_mode="HTML",
    )
# =========================================================
# TOPSHIRIQLAR
# =========================================================
async def tasks_menu(update, context):
    user_id = update.effective_user.id
    conn = db()
    rows = conn.execute(
        """
        SELECT *
        FROM tasks
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    if not rows:
        await update.effective_message.reply_text(
            "🎁 Hozircha topshiriqlar mavjud emas."
        )
        return
    buttons = []
    for task in rows:
        conn = db()
        claimed = conn.execute(
            """
            SELECT 1
            FROM task_claims
            WHERE user_id=? AND task_id=?
            """,
            (
                user_id,
                task["id"],
            ),
        ).fetchone()
        conn.close()
        if claimed:
            buttons.append([
                InlineKeyboardButton(
                    f"✅ {task['text']} (+{task['reward']} ⭐)",
                    callback_data=f"task_done:{task['id']}",
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    f"🎁 {task['text']} (+{task['reward']} ⭐)",
                    callback_data=f"task:{task['id']}",
                )
            ])
    await update.effective_message.reply_text(
        "🎁 <b>TOPSHIRIQLAR</b>\n\n"
        "Topshiriqni bajaring va tasdiqlang.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
async def task_open(update, context, task_id):
    query = update.callback_query
    user_id = query.from_user.id
    conn = db()
    task = conn.execute(
        "SELECT * FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    claimed = conn.execute(
        """
        SELECT 1
        FROM task_claims
        WHERE user_id=? AND task_id=?
        """,
        (
            user_id,
            task_id,
        ),
    ).fetchone()
    conn.close()
    if not task:
        await query.answer(
            "Topshiriq topilmadi.",
            show_alert=True,
        )
        return
    if claimed:
        await query.answer(
            "Bu topshiriq allaqachon olingan.",
            show_alert=True,
        )
        return
    keyboard = []
    if task["url"]:
        keyboard.append([
            InlineKeyboardButton(
                "🔗 TOPSHIRIQNI BAJARISH",
                url=task["url"],
            )
        ])
    keyboard.append([
        InlineKeyboardButton(
            "✅ BAJARDIM",
            callback_data=f"claim_task:{task_id}",
        )
    ])
    await query.edit_message_text(
        f"🎁 <b>{task['text']}</b>\n\n"
        f"💰 Mukofot: <b>+{task['reward']} ⭐</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
async def claim_task(update, context, task_id):
    query = update.callback_query
    user_id = query.from_user.id
    conn = db()
    task = conn.execute(
        "SELECT * FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    if not task:
        conn.close()
        await query.answer(
            "Topshiriq topilmadi.",
            show_alert=True,
        )
        return
    try:
        conn.execute(
            """
            INSERT INTO task_claims
            (user_id, task_id, created_at)
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                task_id,
                now_iso(),
            ),
        )
        conn.execute(
            """
            UPDATE users
            SET points=points+?
            WHERE id=?
            """,
            (
                float(task["reward"]),
                user_id,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        await query.answer(
            "Bu topshiriqni oldin bajargansiz.",
            show_alert=True,
        )
        return
    conn.close()
    await query.answer(
        f"+{task['reward']} ⭐ qo‘shildi!",
        show_alert=True,
    )
    await query.edit_message_text(
        "✅ <b>Topshiriq qabul qilindi!</b>\n\n"
        f"⭐ +{task['reward']} Stars qo‘shildi.",
        parse_mode="HTML",
    )
# =========================================================
# REFERAL
# =========================================================
async def referral(update, context):
    user_id = update.effective_user.id
    me = await context.bot.get_me()
    user = get_user(user_id)
    referrals = int(user["referrals"] or 0)
    link = f"https://t.me/{me.username}?start={user_id}"
    text = (
        "👥 <b>REFERAL TIZIMI</b>\n\n"
        f"👤 Referallaringiz: <b>{referrals}</b>\n"
        f"🎁 Har bir referal: <b>+{REFERRAL_REWARD} ⭐</b>\n\n"
        f"🔗 Sizning linkingiz:\n"
        f"<code>{link}</code>"
    )
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
    )
# =========================================================
# BALANS
# =========================================================
async def balance(update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        return
    await update.message.reply_text(
        "💰 <b>BALANS</b>\n\n"
        f"⭐ Stars: <b>{float(user['points'] or 0):.2f}</b>\n"
        f"🎮 O‘yinlar: <b>{user['games']}</b>\n"
        f"🏆 G‘alabalar: <b>{user['wins']}</b>\n"
        f"👥 Referallar: <b>{user['referrals']}</b>",
        parse_mode="HTML",
    )
# =========================================================
# PROFIL
# =========================================================
async def profile(update, context):
    user = get_user(update.effective_user.id)
    if not user:
        return
    username = (
        f"@{user['username']}"
        if user["username"]
        else "Username yo‘q"
    )
    await update.message.reply_text(
        "👤 <b>PROFIL</b>\n\n"
        f"🆔 ID: <code>{user['id']}</code>\n"
        f"👤 Username: {username}\n"
        f"⭐ Stars: <b>{float(user['points'] or 0):.2f}</b>\n"
        f"🎮 O‘yinlar: <b>{user['games']}</b>\n"
        f"🏆 G‘alabalar: <b>{user['wins']}</b>\n"
        f"👥 Referallar: <b>{user['referrals']}</b>",
        parse_mode="HTML",
    )
# =========================================================
# O'YINLAR
# =========================================================
def game_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔢 SON TOPISH",
                callback_data="game_number",
            ),
            InlineKeyboardButton(
                "🧠 MANTIQ",
                callback_data="game_logic",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎯 TANLOV",
                callback_data="game_choice",
            ),
            InlineKeyboardButton(
                "➕ MATEMATIKA",
                callback_data="game_math",
            ),
        ],
        [
            InlineKeyboardButton(
                "📝 SO‘Z",
                callback_data="game_word",
            ),
            InlineKeyboardButton(
                "⚡ TEZLIK",
                callback_data="game_speed",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎨 RANG",
                callback_data="game_color",
            ),
            InlineKeyboardButton(
                "🔐 KOD",
                callback_data="game_code",
            ),
        ],
        [
            InlineKeyboardButton(
                "🧠 BILIM",
                callback_data="game_knowledge",
            ),
            InlineKeyboardButton(
                "👀 DIQQAT",
                callback_data="game_attention",
            ),
        ],
    ])
async def games(update, context):
    await update.effective_message.reply_text(
        "🎮 <b>O‘YINLAR</b>\n\n"
        f"🏆 G‘alaba uchun: <b>+{GAME_REWARD} ⭐</b>\n"
        f"⏱ Cooldown: <b>{GAME_COOLDOWN} soniya</b>",
        parse_mode="HTML",
        reply_markup=game_keyboard(),
    )
def can_play(user_id):
    return f"cooldown_{user_id}"
async def start_game(update, context, game_type):
    query = update.callback_query
    user_id = query.from_user.id
    key = can_play(user_id)
    if context.user_data.get(key):
        await query.answer(
            "⏳ Biroz kuting.",
            show_alert=True,
        )
        return
    context.user_data[key] = True
    async def reset():
        await asyncio.sleep(GAME_COOLDOWN)
        context.user_data.pop(key, None)
    asyncio.create_task(reset())
    if game_type == "number":
        answer = random.randint(1, 5)
        context.user_data["game"] = {
            "type": "number",
            "answer": answer,
        }
        buttons = [[
            InlineKeyboardButton(
                str(i),
                callback_data=f"guess_number:{i}",
            )
            for i in range(1, 6)
        ]]
        await query.edit_message_text(
            "🔢 <b>SON TOPISH</b>\n\n"
            "1 dan 5 gacha bo‘lgan sonni toping.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return
    if game_type == "choice":
        answer = random.choice(["A", "B", "C"])
        context.user_data["game"] = {
            "type": "choice",
            "answer": answer,
        }
        await query.edit_message_text(
            "🎯 <b>TANLOV</b>\n\n"
            "To‘g‘ri variantni tanlang.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("A", callback_data="choice:A"),
                    InlineKeyboardButton("B", callback_data="choice:B"),
                    InlineKeyboardButton("C", callback_data="choice:C"),
                ]
            ]),
        )
        return
    if game_type == "math":
        a = random.randint(2, 15)
        b = random.randint(2, 15)
        answer = a + b
        context.user_data["game"] = {
            "type": "math",
            "answer": answer,
        }
        options = {answer}
        while len(options) < 4:
            options.add(answer + random.randint(-5, 5))
        buttons = [[
            InlineKeyboardButton(
                str(x),
                callback_data=f"math:{x}",
            )
            for x in random.sample(list(options), 4)
        ]]
        await query.edit_message_text(
            f"➕ <b>MATEMATIKA</b>\n\n"
            f"<b>{a} + {b} = ?</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return
    if game_type == "logic":
        answer = "24"
        context.user_data["game"] = {
            "type": "logic",
            "answer": answer,
        }
        await query.edit_message_text(
            "🧠 <b>MANTIQ</b>\n\n"
            "2, 4, 8, 16, ?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("20", callback_data="logic:20"),
                    InlineKeyboardButton("24", callback_data="logic:24"),
                    InlineKeyboardButton("32", callback_data="logic:32"),
                    InlineKeyboardButton("36", callback_data="logic:36"),
                ]
            ]),
        )
        return
    if game_type == "word":
        answer = "BOT"
        context.user_data["game"] = {
            "type": "word",
            "answer": answer,
        }
        await query.edit_message_text(
            "📝 <b>SO‘Z TOPISH</b>\n\n"
            "B _ T\n\n"
            "Qaysi so‘z?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("BOT", callback_data="word:BOT"),
                    InlineKeyboardButton("BAT", callback_data="word:BAT"),
                    InlineKeyboardButton("BIT", callback_data="word:BIT"),
                ]
            ]),
        )
        return
    if game_type == "color":
        answer = "🔵"
        context.user_data["game"] = {
            "type": "color",
            "answer": answer,
        }
        await query.edit_message_text(
            "🎨 <b>RANG</b>\n\n"
            "Ko‘k rangni toping.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔴", callback_data="color:🔴"),
                    InlineKeyboardButton("🔵", callback_data="color:🔵"),
                    InlineKeyboardButton("🟢", callback_data="color:🟢"),
                ]
            ]),
        )
        return
    if game_type == "code":
        answer = "739"
        context.user_data["game"] = {
            "type": "code",
            "answer": answer,
        }
        await query.edit_message_text(
            "🔐 <b>KOD</b>\n\n"
            "To‘g‘ri kodni tanlang.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("739", callback_data="code:739"),
                    InlineKeyboardButton("427", callback_data="code:427"),
                    InlineKeyboardButton("915", callback_data="code:915"),
                ]
            ]),
        )
        return
    if game_type == "knowledge":
        answer = "Toshkent"
        context.user_data["game"] = {
            "type": "knowledge",
            "answer": answer,
        }
        await query.edit_message_text(
            "🧠 <b>BILIM</b>\n\n"
            "O‘zbekiston poytaxti qaysi shahar?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "Samarqand",
                        callback_data="knowledge:Samarqand",
                    ),
                    InlineKeyboardButton(
                        "Toshkent",
                        callback_data="knowledge:Toshkent",
                    ),
                    InlineKeyboardButton(
                        "Buxoro",
                        callback_data="knowledge:Buxoro",
                    ),
                ]
            ]),
        )
        return
    if game_type == "attention":
        answer = "⭐"
        context.user_data["game"] = {
            "type": "attention",
            "answer": answer,
        }
        await query.edit_message_text(
            "👀 <b>DIQQAT</b>\n\n"
            "⭐ belgini toping.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("❤️", callback_data="attention:❤️"),
                    InlineKeyboardButton("⭐", callback_data="attention:⭐"),
                    InlineKeyboardButton("🔥", callback_data="attention:🔥"),
                ]
            ]),
        )
        return
    if game_type == "speed":
        answer = "GO"
        context.user_data["game"] = {
            "type": "speed",
            "answer": answer,
        }
        await query.edit_message_text(
            "⚡ <b>TEZLIK</b>\n\n"
            "GO tugmasini bosing!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "GO ⚡",
                        callback_data="speed:GO",
                    )
                ]
            ]),
        )
async def game_answer(update, context, answer):
    query = update.callback_query
    game = context.user_data.get("game")
    if not game:
        await query.answer(
            "O‘yin tugagan.",
            show_alert=True,
        )
        return
    correct = str(game["answer"]) == str(answer)
    conn = db()
    conn.execute(
        """
        UPDATE users
        SET games=games+1
        WHERE id=?
        """,
        (query.from_user.id,),
    )
    if correct:
        conn.execute(
            """
            UPDATE users
            SET wins=wins+1,
                points=points+?
            WHERE id=?
            """,
            (
                GAME_REWARD,
                query.from_user.id,
            ),
        )
    conn.commit()
    conn.close()
    context.user_data.pop("game", None)
    if correct:
        await query.answer(
            f"🎉 To‘g‘ri! +{GAME_REWARD} ⭐",
            show_alert=True,
        )
        await query.edit_message_text(
            "🎉 <b>TO‘G‘RI!</b>\n\n"
            f"⭐ Sizga <b>+{GAME_REWARD}</b> qo‘shildi.",
            parse_mode="HTML",
        )
    else:
        await query.answer(
            "❌ Noto‘g‘ri!",
            show_alert=True,
        )
        await query.edit_message_text(
            "❌ <b>Noto‘g‘ri javob.</b>\n\n"
            "Keyingi safar omad!",
            parse_mode="HTML",
        )
# =========================================================
# YECHIB OLISH
# =========================================================
async def withdraw(update, context):
    user = get_user(update.effective_user.id)
    if not user:
        return
    points = float(user["points"] or 0)
    referrals = int(user["referrals"] or 0)
    if points < MIN_WITHDRAW:
        await update.message.reply_text(
            "💸 <b>YECHIB OLISH</b>\n\n"
            f"Minimal: <b>{MIN_WITHDRAW} ⭐</b>\n"
            f"Sizda: <b>{points:.2f} ⭐</b>",
            parse_mode="HTML",
        )
        return
    if referrals < MIN_REFERRALS:
        await update.message.reply_text(
            "💸 <b>YECHIB OLISH</b>\n\n"
            f"Minimal referal: <b>{MIN_REFERRALS}</b>\n"
            f"Sizda: <b>{referrals}</b>",
            parse_mode="HTML",
        )
        return
    conn = db()
    pending = conn.execute(
        """
        SELECT id
        FROM withdrawals
        WHERE user_id=? AND status='pending'
        """,
        (update.effective_user.id,),
    ).fetchone()
    conn.close()
    if pending:
        await update.message.reply_text(
            "⏳ Sizda allaqachon pending so‘rov bor.",
            parse_mode="HTML",
        )
        return
    context.user_data["withdraw_amount"] = True
    await update.message.reply_text(
        "💸 <b>YECHIB OLISH</b>\n\n"
        f"Balans: <b>{points:.2f} ⭐</b>\n"
        f"Minimal: <b>{MIN_WITHDRAW} ⭐</b>\n\n"
        "Qancha Stars yechmoqchisiz?\n"
        "Masalan: <code>200</code>",
        parse_mode="HTML",
    )
async def process_withdraw_amount(update, context):
    if not context.user_data.get("withdraw_amount"):
        return
    try:
        amount = float(
            update.message.text.replace(",", ".").strip()
        )
    except Exception:
        await update.message.reply_text(
            "❌ Miqdorni raqamda kiriting."
        )
        return
    user_id = update.effective_user.id
    user = get_user(user_id)
    context.user_data.pop("withdraw_amount", None)
    if not user:
        return
    points = float(user["points"] or 0)
    referrals = int(user["referrals"] or 0)
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
    if referrals < MIN_REFERRALS:
        await update.message.reply_text(
            f"❌ Kamida {MIN_REFERRALS} ta referal kerak."
        )
        return
    conn = db()
    pending = conn.execute(
        """
        SELECT id
        FROM withdrawals
        WHERE user_id=? AND status='pending'
        """,
        (user_id,),
    ).fetchone()
    if pending:
        conn.close()
        await update.message.reply_text(
            "⏳ Sizda pending so‘rov mavjud."
        )
        return
    conn.execute(
        """
        UPDATE users
        SET points=points-?
        WHERE id=?
        """,
        (
            amount,
            user_id,
        ),
    )
    cursor = conn.execute(
        """
        INSERT INTO withdrawals
        (user_id, amount, status, created_at)
        VALUES (?, ?, 'pending', ?)
        """,
        (
            user_id,
            amount,
            now_iso(),
        ),
    )
    withdrawal_id = cursor.lastrowid
    conn.commit()
    conn.close()
    await update.message.reply_text(
        "✅ <b>So‘rov yuborildi!</b>\n\n"
        f"⭐ Miqdor: <b>{amount:.2f}</b>\n"
        "⏳ Holat: <b>Pending</b>",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            ADMIN_ID,
            "💸 <b>YANGI YECHISH SO‘ROVI</b>\n\n"
            f"🆔 User: <code>{user_id}</code>\n"
            f"⭐ Miqdor: <b>{amount:.2f}</b>\n"
            f"📌 ID: <code>{withdrawal_id}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ TASDIQLASH",
                        callback_data=f"approve_withdraw:{withdrawal_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ RAD ETISH",
                        callback_data=f"reject_withdraw:{withdrawal_id}",
                    ),
                ]
            ]),
        )
    except Exception as e:
        logger.error(
            "Admin xabari xatosi: %s",
            e,
        )
# =========================================================
# REYTING
# =========================================================
async def rating(update, context):
    conn = db()
    rows = conn.execute(
        """
        SELECT username, points
        FROM users
        WHERE blocked=0
        ORDER BY points DESC
        LIMIT 10
        """
    ).fetchall()
    conn.close()
    text = "🏆 <b>REYTING</b>\n\n"
    if not rows:
        text += "Hozircha foydalanuvchilar yo‘q."
    else:
        for i, row in enumerate(rows, 1):
            username = (
                "@" + row["username"]
                if row["username"]
                else "Noma'lum"
            )
            text += (
                f"{i}. {username} — "
                f"<b>{float(row['points'] or 0):.2f} ⭐</b>\n"
            )
    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )
# =========================================================
# STARS SOTIB OLISH
# =========================================================
async def buy_stars(update, context):
    await update.message.reply_text(
        "⭐ <b>STARS SOTIB OLISH</b>\n\n"
        "Telegram Stars sotib olish uchun tugmani bosing.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⭐ STARS SOTIB OLISH",
                    url=BUY_STARS_URL,
                )
            ]
        ]),
    )
# =========================================================
# CALLBACKLAR
# =========================================================
async def callbacks(update, context):
    query = update.callback_query
    data = query.data or ""
    await query.answer()
    user_id = query.from_user.id
    # -----------------------------------------------------
    # HOMIY TASDIQLASH
    # -----------------------------------------------------
    if data == "check_sponsors":
        ok = await check_all_sponsors(
            context.bot,
            user_id,
        )
        if not ok:
            await query.answer(
                "❌ Avval kanalga obuna bo‘ling!",
                show_alert=True,
            )
            return
        await query.edit_message_text(
            "✅ <b>OBUNA TASDIQLANDI!</b>\n\n"
            "Botdan foydalanishingiz mumkin.",
            parse_mode="HTML",
        )
        await query.message.reply_text(
            "🏠 <b>TEKIN STARS BOT</b>\n\n"
            "Xush kelibsiz!",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return
    # -----------------------------------------------------
    # ODDIY CALLBACKLAR
    # -----------------------------------------------------
    if data == "tasks":
        await tasks_menu(update, context)
        return
    if data.startswith("task:"):
        task_id = int(data.split(":")[1])
        await task_open(update, context, task_id)
        return
    if data.startswith("claim_task:"):
        task_id = int(data.split(":")[1])
        await claim_task(update, context, task_id)
        return
    if data == "referral":
        await referral(update, context)
        return
    if data.startswith("game_"):
        game_type = data.replace("game_", "", 1)
        await start_game(update, context, game_type)
        return
    if data.startswith("guess_number:"):
        answer = data.split(":", 1)[1]
        await game_answer(update, context, answer)
        return
    if ":" in data:
        game_type, answer = data.split(":", 1)
        if game_type in (
            "choice",
            "math",
            "logic",
            "word",
            "color",
            "code",
            "knowledge",
            "attention",
            "speed",
        ):
            await game_answer(
                update,
                context,
                answer,
            )
            return
    if data.startswith("approve_withdraw:"):
        await approve_withdraw(
            update,
            context,
            int(data.split(":")[1]),
        )
        return
    if data.startswith("reject_withdraw:"):
        await reject_withdraw(
            update,
            context,
            int(data.split(":")[1]),
        )
        return
    if data.startswith("admin_"):
        await admin_callback(update, context)
        return
# =========================================================
# ADMIN PANEL
# =========================================================
def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 STATISTIKA",
                callback_data="admin_stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 HOMIY",
                callback_data="admin_sponsors",
            ),
            InlineKeyboardButton(
                "🎁 TOPSHIRIQLAR",
                callback_data="admin_tasks",
            ),
        ],
        [
            InlineKeyboardButton(
                "📣 REKLAMA",
                callback_data="admin_broadcast",
            ),
        ],
        [
            InlineKeyboardButton(
                "💸 YECHISHLAR",
                callback_data="admin_withdrawals",
            ),
        ],
    ])
async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "❌ Ruxsat yo‘q."
        )
        return
    await update.message.reply_text(
        "👑 <b>ADMIN PANEL</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )
async def admin_callback(update, context):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer(
            "❌ Ruxsat yo‘q.",
            show_alert=True,
        )
        return
    data = query.data
    # -----------------------------------------------------
    # STATISTIKA
    # -----------------------------------------------------
    if data == "admin_stats":
        conn = db()
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM users"
        ).fetchone()["c"]
        active = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM users
            WHERE last_seen >= ?
            """,
            (
                (
                    datetime.now(timezone.utc)
                    - timedelta(days=1)
                ).isoformat(),
            ),
        ).fetchone()["c"]
        points = conn.execute(
            "SELECT SUM(points) AS s FROM users"
        ).fetchone()["s"] or 0
        conn.close()
        await query.edit_message_text(
            "📊 <b>STATISTIKA</b>\n\n"
            f"👥 Jami foydalanuvchilar: <b>{total}</b>\n"
            f"🟢 24 soatlik aktiv: <b>{active}</b>\n"
            f"⭐ Jami balans: <b>{float(points):.2f}</b>\n"
            "📢 Homiylik: <b>DOIMIY ON</b>\n"
            f"📢 Kanal: <b>{SPONSOR_CHANNEL}</b>",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )
        return
    # -----------------------------------------------------
    # HOMIY
    # -----------------------------------------------------
    if data == "admin_sponsors":
        await query.edit_message_text(
            "📢 <b>DOIMIY HOMIY</b>\n\n"
            f"📢 Kanal: <b>{SPONSOR_CHANNEL}</b>\n"
            f"🔗 {SPONSOR_URL}\n\n"
            "🔒 Bu kanal majburiy obuna sifatida "
            "doim turadi.\n\n"
            "❌ 100 ta odamdan keyin o‘chmaydi.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="admin_back",
                    )
                ]
            ]),
        )
        return
    # -----------------------------------------------------
    # TOPSHIRIQLAR
    # -----------------------------------------------------
    if data == "admin_tasks":
        conn = db()
        tasks = conn.execute(
            "SELECT * FROM tasks ORDER BY id DESC"
        ).fetchall()
        conn.close()
        text = "🎁 <b>TOPSHIRIQLAR</b>\n\n"
        if not tasks:
            text += "Topshiriqlar yo‘q."
        else:
            for task in tasks:
                text += (
                    f"#{task['id']} — {task['text']}\n"
                    f"⭐ {task['reward']}\n\n"
                )
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "➕ TOPSHIRIQ QO‘SHISH",
                        callback_data="admin_add_task",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 ORQAGA",
                        callback_data="admin_back",
                    )
                ],
            ]),
        )
        return
    # -----------------------------------------------------
    # REKLAMA
    # -----------------------------------------------------
    if data == "admin_broadcast":
        context.user_data["admin_broadcast"] = True
        await query.edit_message_text(
            "📣 <b>REKLAMA / XABAR YUBORISH</b>\n\n"
            "Endi yubormoqchi bo‘lgan xabaringizni shu botga yuboring.\n\n"
            "✅ Matn\n"
            "✅ Rasm\n"
            "✅ Video\n"
            "✅ Hujjat\n"
            "✅ Sticker\n"
            "✅ Boshqa Telegram xabarlari\n\n"
            "Bot uni foydalanuvchilarga yuboradi.",
            parse_mode="HTML",
        )
        return
    # -----------------------------------------------------
    # YECHISHLAR
    # -----------------------------------------------------
    if data == "admin_withdrawals":
        conn = db()
        rows = conn.execute(
            """
            SELECT *
            FROM withdrawals
            WHERE status='pending'
            ORDER BY id DESC
            LIMIT 10
            """
        ).fetchall()
        conn.close()
        text = "💸 <b>PENDING YECHISHLAR</b>\n\n"
        if not rows:
            text += "Pending so‘rovlar yo‘q."
        else:
            for row in rows:
                text += (
                    f"#{row['id']} | "
                    f"ID: <code>{row['user_id']}</code> | "
                    f"{row['amount']} ⭐\n"
                )
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )
        return
    # -----------------------------------------------------
    # TOPSHIRIQ QO‘SHISH
    # -----------------------------------------------------
    if data == "admin_add_task":
        context.user_data["admin_add_task"] = True
        await query.edit_message_text(
            "➕ <b>TOPSHIRIQ QO‘SHISH</b>\n\n"
            "Format:\n"
            "<code>Matn | mukofot | link</code>\n\n"
            "Masalan:\n"
            "<code>Kanalga obuna bo‘ling | 5 | https://t.me/kanal</code>",
            parse_mode="HTML",
        )
        return
    if data == "admin_back":
        await query.edit_message_text(
            "👑 <b>ADMIN PANEL</b>",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )
        return
# =========================================================
# ADMIN MATN / MEDIA QABUL QILISH
# =========================================================
async def admin_text_handler(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    # -----------------------------------------------------
    # HOMIY QO‘SHISH
    # DOIMIY HOMIYNI O‘ZGARTIRISHGA YO‘L QO‘YMAYMIZ
    # -----------------------------------------------------
    if context.user_data.get("admin_add_sponsor"):
        context.user_data.pop(
            "admin_add_sponsor",
            None,
        )
        await update.effective_message.reply_text(
            "📢 Bu botda doimiy homiy:\n\n"
            f"{SPONSOR_CHANNEL}\n\n"
            "Uni o‘zgartirish kerak emas."
        )
        return
    # -----------------------------------------------------
    # REKLAMA / BROADCAST
    # -----------------------------------------------------
    if context.user_data.get("admin_broadcast"):
        context.user_data.pop(
            "admin_broadcast",
            None,
        )
        conn = db()
        users = conn.execute(
            """
            SELECT id
            FROM users
            WHERE blocked=0
            """
        ).fetchall()
        conn.close()
        sent = 0
        failed = 0
        for row in users:
            user_id = row["id"]
            try:
                # Xabarni aynan Telegramdagi ko‘rinishida
                # foydalanuvchiga COPY qilamiz.
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.effective_message.message_id,
                )
                sent += 1
                # Telegram flood limitini hurmat qilamiz.
                await asyncio.sleep(0.05)
            except Forbidden:
                failed += 1
                conn = db()
                conn.execute(
                    """
                    UPDATE users
                    SET blocked=1
                    WHERE id=?
                    """,
                    (user_id,),
                )
                conn.commit()
                conn.close()
            except RetryAfter as e:
                try:
                    await asyncio.sleep(
                        float(e.retry_after) + 1
                    )
                    await context.bot.copy_message(
                        chat_id=user_id,
                        from_chat_id=update.effective_chat.id,
                        message_id=update.effective_message.message_id,
                    )
                    sent += 1
                except Exception:
                    failed += 1
            except TelegramError:
                failed += 1
            except Exception:
                failed += 1
        await update.effective_message.reply_text(
            "📣 <b>REKLAMA YAKUNLANDI</b>\n\n"
            f"✅ Yuborildi: <b>{sent}</b>\n"
            f"❌ Yuborilmadi: <b>{failed}</b>",
            parse_mode="HTML",
        )
        return
    # -----------------------------------------------------
    # TOPSHIRIQ QO‘SHISH
    # -----------------------------------------------------
    if context.user_data.get("admin_add_task"):
        context.user_data.pop(
            "admin_add_task",
            None,
        )
        if not update.message or not update.message.text:
            await update.effective_message.reply_text(
                "❌ Topshiriqni matn ko‘rinishida yuboring."
            )
            return
        text = update.message.text.strip()
        parts = [x.strip() for x in text.split("|")]
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ Format noto‘g‘ri.\n\n"
                "Matn | mukofot | link"
            )
            return
        task_text = parts[0]
        try:
            reward = float(parts[1])
        except Exception:
            await update.message.reply_text(
                "❌ Mukofot raqam bo‘lishi kerak."
            )
            return
        url = parts[2]
        conn = db()
        conn.execute(
            """
            INSERT INTO tasks
            (text, reward, url, channel)
            VALUES (?, ?, ?, ?)
            """,
            (
                task_text,
                reward,
                url,
                "",
            ),
        )
        conn.commit()
        conn.close()
        await update.message.reply_text(
            "✅ Topshiriq qo‘shildi."
        )
        return
# =========================================================
# WITHDRAW ADMIN
# =========================================================
async def approve_withdraw(update, context, withdrawal_id):
    query = update.callback_query
    conn = db()
    row = conn.execute(
        """
        SELECT *
        FROM withdrawals
        WHERE id=?
        """,
        (withdrawal_id,),
    ).fetchone()
    if not row:
        conn.close()
        await query.answer(
            "So‘rov topilmadi.",
            show_alert=True,
        )
        return
    if row["status"] != "pending":
        conn.close()
        await query.answer(
            "Bu so‘rov allaqachon ishlangan.",
            show_alert=True,
        )
        return
    conn.execute(
        """
        UPDATE withdrawals
        SET status='approved',
            processed_at=?
        WHERE id=?
        """,
        (
            now_iso(),
            withdrawal_id,
        ),
    )
    conn.commit()
    conn.close()
    await query.answer(
        "Tasdiqlandi.",
        show_alert=True,
    )
    await query.edit_message_text(
        "✅ <b>YECHISH TASDIQLANDI</b>\n\n"
        f"🆔 User: <code>{row['user_id']}</code>\n"
        f"⭐ Miqdor: <b>{row['amount']}</b>",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            row["user_id"],
            "✅ <b>Yechish so‘rovingiz tasdiqlandi!</b>\n\n"
            f"⭐ Miqdor: <b>{row['amount']}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass
async def reject_withdraw(update, context, withdrawal_id):
    query = update.callback_query
    conn = db()
    row = conn.execute(
        """
        SELECT *
        FROM withdrawals
        WHERE id=?
        """,
        (withdrawal_id,),
    ).fetchone()
    if not row:
        conn.close()
        await query.answer(
            "So‘rov topilmadi.",
            show_alert=True,
        )
        return
    if row["status"] != "pending":
        conn.close()
        await query.answer(
            "Bu so‘rov allaqachon ishlangan.",
            show_alert=True,
        )
        return
    conn.execute(
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
    conn.execute(
        """
        UPDATE withdrawals
        SET status='rejected',
            processed_at=?
        WHERE id=?
        """,
        (
            now_iso(),
            withdrawal_id,
        ),
    )
    conn.commit()
    conn.close()
    await query.answer(
        "Rad etildi.",
        show_alert=True,
    )
    await query.edit_message_text(
        "❌ <b>YECHISH RAD ETILDI</b>\n\n"
        f"🆔 User: <code>{row['user_id']}</code>\n"
        f"⭐ Miqdor: <b>{row['amount']}</b>\n\n"
        "Balans qaytarildi.",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            row["user_id"],
            "❌ <b>Yechish so‘rovingiz rad etildi.</b>\n\n"
            f"⭐ {row['amount']} Stars balansingizga qaytarildi.",
            parse_mode="HTML",
        )
    except Exception:
        pass
# =========================================================
# MATN / UMUMIY HANDLER
# =========================================================
async def text_handler(update, context):
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    # -----------------------------------------------------
    # ADMIN REJIMLARI
    # -----------------------------------------------------
    if user_id == ADMIN_ID:
        if any(
            context.user_data.get(x)
            for x in (
                "admin_add_sponsor",
                "admin_remove_sponsor",
                "admin_add_task",
                "admin_broadcast",
            )
        ):
            await admin_text_handler(
                update,
                context,
            )
            return
    # -----------------------------------------------------
    # WITHDRAW INPUT
    # -----------------------------------------------------
    if context.user_data.get("withdraw_amount"):
        if update.message and update.message.text:
            await process_withdraw_amount(
                update,
                context,
            )
        return
    # -----------------------------------------------------
    # HOMIY TEKSHIRISH
    # -----------------------------------------------------
    ok = await check_all_sponsors(
        context.bot,
        user_id,
    )
    if not ok:
        await show_sponsor_required(update)
        return
    # Media bo‘lsa oddiy menyu sifatida ishlatmaymiz.
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    # -----------------------------------------------------
    # MENU
    # -----------------------------------------------------
    if text == "⭐ STARS OLISH":
        await stars_get(update, context)
    elif text == "🎯 STARS ISHLASH":
        await stars_work(update, context)
    elif text == "🎮 O‘YINLAR":
        await games(update, context)
    elif text == "💰 BALANS":
        await balance(update, context)
    elif text == "🎁 TOPSHIRIQLAR":
        await tasks_menu(update, context)
    elif text == "👥 REFERAL":
        await referral(update, context)
    elif text == "💸 YECHIB OLISH":
        await withdraw(update, context)
    elif text == "⭐ STARS SOTIB OLISH":
        await buy_stars(update, context)
    elif text == "🏆 REYTING":
        await rating(update, context)
    elif text == "👤 PROFIL":
        await profile(update, context)
# =========================================================
# ERROR HANDLER
# =========================================================
async def error_handler(update, context):
    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )
# =========================================================
# MAIN
# =========================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN GitHub Secrets ichida topilmadi."
        )
    init_db()
    application = (
        Application.builder()
        .token(BOT_TOKEN)
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
            "admin",
            admin_command,
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            callbacks,
        )
    )
    # TEXT + MEDIA:
    # Admin reklamasiga rasm/video/hujjat/sticker ham tushadi.
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            text_handler,
        )
    )
    application.add_error_handler(
        error_handler
    )
    logger.info(
        "TEKIN STARS BOT ishga tushdi."
    )
    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )
if __name__ == "__main__":
    main()
