import os
import sqlite3
import random
import logging
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

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB = "zerikdim.db"

# =========================
# SOZLAMALAR
# =========================

SPONSOR = "@premyumstarstekin"

REFERRAL_REWARD = 9.0
GAME_REWARD = 0.1
TASK_REWARD = 5.0

MIN_WITHDRAW = 50.0
MIN_REFERRALS = 20

BUY_STARS = "https://t.me/premyumstarstekin/933"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =========================
# DATABASE
# =========================

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    con = connect()
    cur = con.cursor()

    cur.execute("""
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sponsors (
        channel TEXT PRIMARY KEY
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT UNIQUE,
        reward REAL DEFAULT 5
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_claims (
        user_id INTEGER,
        task_id INTEGER,
        claimed_at TEXT,
        PRIMARY KEY(user_id, task_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
    """)

    cur.execute(
        "INSERT OR IGNORE INTO sponsors(channel) VALUES(?)",
        (SPONSOR,)
    )

    cur.execute(
        "INSERT OR IGNORE INTO tasks(channel,reward) VALUES(?,?)",
        (SPONSOR, TASK_REWARD)
    )

    con.commit()
    con.close()


def add_user(user, referrer=None):
    con = connect()
    cur = con.cursor()

    old = cur.execute(
        "SELECT id FROM users WHERE id=?",
        (user.id,)
    ).fetchone()

    if old:
        cur.execute("""
        UPDATE users
        SET username=?, last_seen=?, blocked=0
        WHERE id=?
        """, (user.username, now(), user.id))

        con.commit()
        con.close()
        return

    valid_ref = None

    if referrer and referrer != user.id:
        exists = cur.execute(
            "SELECT id FROM users WHERE id=?",
            (referrer,)
        ).fetchone()

        if exists:
            valid_ref = referrer

    cur.execute("""
    INSERT INTO users
    (id,username,points,games,wins,referrals,
     referred_by,last_seen,blocked,referral_rewarded)
    VALUES(?,?,0,0,0,0,?,?,0,0)
    """, (
        user.id,
        user.username,
        valid_ref,
        now()
    ))

    con.commit()
    con.close()


def touch(user):
    con = connect()
    con.execute("""
    UPDATE users
    SET username=?, last_seen=?, blocked=0
    WHERE id=?
    """, (user.username, now(), user.id))
    con.commit()
    con.close()


def get_user(user_id):
    con = connect()
    row = con.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    con.close()
    return row


def add_points(user_id, amount):
    con = connect()
    con.execute("""
    UPDATE users
    SET points=ROUND(COALESCE(points,0)+?,1)
    WHERE id=?
    """, (amount, user_id))
    con.commit()
    con.close()


def game_result(user_id, win):
    con = connect()

    if win:
        con.execute("""
        UPDATE users
        SET games=games+1,
            wins=wins+1,
            points=ROUND(COALESCE(points,0)+?,1)
        WHERE id=?
        """, (GAME_REWARD, user_id))
    else:
        con.execute("""
        UPDATE users
        SET games=games+1
        WHERE id=?
        """, (user_id,))

    con.commit()
    con.close()


# =========================
# REFERRAL
# =========================

def reward_referral(user_id):
    con = connect()
    cur = con.cursor()

    row = cur.execute("""
    SELECT referred_by, referral_rewarded
    FROM users
    WHERE id=?
    """, (user_id,)).fetchone()

    if not row:
        con.close()
        return False

    ref = row["referred_by"]

    if not ref or row["referral_rewarded"]:
        con.close()
        return False

    cur.execute("""
    UPDATE users
    SET points=ROUND(points+?,1),
        referrals=referrals+1
    WHERE id=?
    """, (REFERRAL_REWARD, ref))

    cur.execute("""
    UPDATE users
    SET referral_rewarded=1
    WHERE id=?
    """, (user_id,))

    con.commit()
    con.close()

    return True


# =========================
# SPONSOR
# =========================

def sponsors():
    con = connect()
    rows = con.execute(
        "SELECT channel FROM sponsors ORDER BY channel"
    ).fetchall()
    con.close()
    return [r["channel"] for r in rows]


def normalize(channel):
    channel = channel.strip()

    if channel.startswith("https://t.me/"):
        channel = "@" + channel.rstrip("/").split("/")[-1]

    if not channel.startswith("@"):
        channel = "@" + channel

    return channel


def add_sponsor(channel):
    channel = normalize(channel)

    con = connect()
    con.execute(
        "INSERT OR IGNORE INTO sponsors(channel) VALUES(?)",
        (channel,)
    )
    con.commit()
    con.close()


def delete_sponsor(channel):
    channel = normalize(channel)

    if channel == SPONSOR:
        return False

    con = connect()
    cur = con.cursor()

    cur.execute(
        "DELETE FROM sponsors WHERE channel=?",
        (channel,)
    )

    ok = cur.rowcount > 0

    con.commit()
    con.close()

    return ok


async def subscribed(user_id, context):
    if user_id == ADMIN_ID:
        return True

    for channel in sponsors():
        try:
            member = await context.bot.get_chat_member(
                channel,
                user_id
            )

            if member.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.KICKED
            ):
                return False

        except TelegramError:
            return False

    return True


async def require_sub(update, context):
    user = update.effective_user

    if await subscribed(user.id, context):
        reward_referral(user.id)
        return True

    buttons = []

    for channel in sponsors():
        buttons.append([
            InlineKeyboardButton(
                f"📢 {channel}",
                url=f"https://t.me/{channel.replace('@','')}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✅ TEKSHIRISH",
            callback_data="check_sub"
        )
    ])

    text = (
        "🔒 <b>Avval kanalga obuna bo‘ling!</b>\n\n"
        "📢 Kanalga kiring va obuna bo‘ling.\n"
        "Keyin <b>✅ TEKSHIRISH</b> tugmasini bosing."
    )

    markup = InlineKeyboardMarkup(buttons)

    if update.callback_query:
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

    return False


# =========================
# SHART BAJAR
# =========================

def task_list(user_id):
    con = connect()

    rows = con.execute("""
    SELECT
        tasks.id,
        tasks.channel,
        tasks.reward,
        CASE
            WHEN task_claims.user_id IS NULL THEN 0
            ELSE 1
        END AS claimed
    FROM tasks
    LEFT JOIN task_claims
      ON task_claims.task_id=tasks.id
     AND task_claims.user_id=?
    ORDER BY tasks.id
    """, (user_id,)).fetchall()

    con.close()

    return rows


def task_menu(user_id):
    buttons = []

    for row in task_list(user_id):
        if row["claimed"]:
            buttons.append([
                InlineKeyboardButton(
                    f"✅ {row['channel']} | OLINDI",
                    callback_data="noop"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    f"📢 {row['channel']} +{row['reward']:g}⭐",
                    url=f"https://t.me/{row['channel'].replace('@','')}"
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    "✅ TEKSHIRISH",
                    callback_data=f"task:{row['id']}"
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 ORQAGA",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(buttons)


async def show_tasks(update, context):
    user = update.effective_user

    text = (
        "🎯 <b>SHART BAJAR</b>\n\n"
        "📢 Kanalga obuna bo‘ling va mukofot oling.\n"
        f"🎁 Har bir kanal: +{TASK_REWARD:g} ⭐\n\n"
        "👇 Shartni bajaring:"
    )

    if update.callback_query:
        await update.callback_query.message.edit_text(
            text,
            reply_markup=task_menu(user.id),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=task_menu(user.id),
            parse_mode="HTML"
        )


async def check_task(update, context, task_id):
    user = update.effective_user

    con = connect()

    task = con.execute(
        "SELECT * FROM tasks WHERE id=?",
        (task_id,)
    ).fetchone()

    if not task:
        con.close()
        await update.callback_query.answer(
            "❌ Shart topilmadi!",
            show_alert=True
        )
        return

    already = con.execute("""
    SELECT 1 FROM task_claims
    WHERE user_id=? AND task_id=?
    """, (user.id, task_id)).fetchone()

    if already:
        con.close()
        await update.callback_query.answer(
            "✅ Bu mukofotni oldingiz!",
            show_alert=True
        )
        return

    channel = task["channel"]

    try:
        member = await context.bot.get_chat_member(
            channel,
            user.id
        )

        if member.status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED
        ):
            con.close()

            await update.callback_query.answer(
                "❌ Avval kanalga obuna bo‘ling!",
                show_alert=True
            )
            return

    except TelegramError:
        con.close()

        await update.callback_query.answer(
            "❌ Tekshirishda xatolik. Bot kanalga admin qilinganini tekshiring.",
            show_alert=True
        )
        return

    con.execute("""
    INSERT INTO task_claims(user_id,task_id,claimed_at)
    VALUES(?,?,?)
    """, (user.id, task_id, now()))

    con.execute("""
    UPDATE users
    SET points=ROUND(points+?,1)
    WHERE id=?
    """, (task["reward"], user.id))

    con.commit()
    con.close()

    await update.callback_query.answer(
        f"🎉 +{task['reward']:g} ⭐ olindingiz!",
        show_alert=True
    )

    await show_tasks(update, context)


# =========================
# MENUS
# =========================

def home_markup(user_id):
    buttons = [
        [
            InlineKeyboardButton(
                "🔥 QZU O‘YIN",
                callback_data="games"
            ),
            InlineKeyboardButton(
                "⭐ BALL",
                callback_data="balance"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 SHART BAJAR",
                callback_data="tasks"
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
                callback_data="buy"
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
    ]

    if user_id == ADMIN_ID:
        buttons.append([
            InlineKeyboardButton(
                "⚙️ ADMIN PANEL",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(buttons)


async def home(update, context):
    user = update.effective_user

    text = (
        "🎉 <b>Bu yerda zerikmaysiz!</b>\n\n"
        "🎮 O‘yin o‘ynang.\n"
        f"⭐ Har bir g‘alaba: +{GAME_REWARD:.1f} ⭐\n"
        f"👥 Referral: +{REFERRAL_REWARD:g} ⭐\n"
        f"🎯 Shart: +{TASK_REWARD:g} ⭐\n\n"
        "👇 Tanlang:"
    )

    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text,
                reply_markup=home_markup(user.id),
                parse_mode="HTML"
            )
        except TelegramError:
            await update.callback_query.message.reply_text(
                text,
                reply_markup=home_markup(user.id),
                parse_mode="HTML"
            )
    else:
        await update.message.reply_text(
            text,
            reply_markup=home_markup(user.id),
            parse_mode="HTML"
        )


# =========================
# 100+ O‘YIN
# =========================

GAMES = [
    "🎯 Dart", "🎳 Bowling", "🎲 Zar", "🧠 Savol-javob",
    "🔢 Son top", "🏝️ Orol", "🇺🇳 Bayroq", "🧩 Topishmoq",
    "⚡ Tezkor", "💣 Mina", "🧠 Xotira", "🔥 Streak",
    "👆 Tezkor bos", "🃏 Karta", "🎯 Nishon", "🪙 Omad tangasi",
    "😀 Emoji topishmoq", "🏎️ Poyga", "👹 Boss Battle",
    "🕵️ Mafia", "🔎 Detektiv", "🎭 Yashirin rol",
    "🤥 Kim yolg‘onchi?", "🕶️ Maxfiy agent", "⚔️ Jamoa battle",
    "🎡 Omad g‘ildiragi",
]

# Add many different generated game titles.
EXTRA_GAMES = [
    "Rangni top", "Juft yoki toq", "Kattasini top", "Kichigini top",
    "To‘g‘ri yo‘l", "Sirli quti", "Kod buzish", "Raqamlar zanjiri",
    "Belgini top", "So‘zni top", "Harf ovchisi", "Tez hisob",
    "Matematika duel", "Mantiq testi", "Pattern top", "Ortiqchasini top",
    "Qaysi biri?", "Chap yoki o‘ng", "Yuqori yoki past",
    "Issiq yoki sovuq", "Yashirin son", "Sirli raqam",
    "Xazina qidiruv", "Qochish xonasi", "Labirint", "Robot duel",
    "Kosmik jang", "Sayyora top", "Meteor", "Raketam",
    "Super tezlik", "Refleks", "Ko‘z ilg‘amas", "Bir xilni top",
    "Farqni top", "Xotira kartasi", "Emoji juftlik",
    "So‘z zanjiri", "Harf zanjiri", "Raqam zanjiri 2",
    "Mini viktorina", "Geografiya", "Tarix savoli", "Fan savoli",
    "Hayvonni top", "Mevani top", "Taomni top", "Sportni top",
    "Filmni top", "Kasbni top", "Shaharni top", "Davlatni top",
    "Poyga 2", "Poyga 3", "Duel", "Super duel",
    "Boss 2", "Boss 3", "Nishon 2", "Nishon 3",
    "Zar duel", "Karta duel", "Quti tanla", "3 eshik",
    "5 eshik", "7 eshik", "Sirli xona", "Maxfiy kod",
    "Agent testi", "Detektiv 2", "Detektiv 3", "Mafia 2",
    "Mafia 3", "Yolg‘onchi 2", "Yolg‘onchi 3", "Rol top",
    "Kim tez?", "Kim aqlli?", "Kim omadli?", "Aql jang",
    "Mantiq jang", "Raqam jang", "Emoji jang", "Harf jang",
    "Tezkor duel", "Refleks duel", "Xotira duel", "Pattern duel",
    "Rang duel", "Kod duel", "Topishmoq duel", "Savol duel",
    "Final duel", "Champion", "Master", "Legend",
    "Ultra quiz", "Mega puzzle", "Super puzzle", "Brain test",
    "Quick brain", "Lucky choice", "Secret choice", "Hidden box",
    "Treasure", "Magic door", "Mystery", "Impossible choice",
]

GAMES.extend(EXTRA_GAMES)

# 100+ bo‘lishini kafolatlash
while len(GAMES) < 120:
    GAMES.append(f"🎮 Mini o‘yin #{len(GAMES)+1}")


def games_menu(page=0):
    per_page = 10
    start = page * per_page
    items = GAMES[start:start + per_page]

    buttons = []

    for i, name in enumerate(items, start=start):
        buttons.append([
            InlineKeyboardButton(
                name,
                callback_data=f"play:{i}"
            )
        ])

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️",
                callback_data=f"games:{page-1}"
            )
        )

    if start + per_page < len(GAMES):
        nav.append(
            InlineKeyboardButton(
                "➡️",
                callback_data=f"games:{page+1}"
            )
        )

    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(
            "🔙 ORQAGA",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(buttons)


async def show_games(update, context, page=0):
    text = (
        "🔥 <b>TOP O‘YINLAR</b>\n\n"
        f"🎮 Jami o‘yinlar: <b>{len(GAMES)}+</b>\n"
        f"⭐ G‘alaba: <b>+{GAME_REWARD:.1f} ⭐</b>\n\n"
        "👇 O‘yin tanlang:"
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=games_menu(page),
        parse_mode="HTML"
    )


# =========================
# O‘YINLAR
# =========================

async def play_game(update, context, index):
    user = update.effective_user

    name = GAMES[index]

    # Random challenge.
    kind = random.randint(1, 8)

    if kind == 1:
        number = random.randint(1, 5)

        context.user_data["game"] = {
            "type": "number",
            "answer": number,
        }

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(str(i), callback_data=f"ansnum:{i}")
                for i in range(1, 6)
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ])

        text = (
            f"🎮 <b>{name}</b>\n\n"
            "🔢 1 dan 5 gacha son o‘yladim.\n"
            "Toping:"
        )

    elif kind == 2:
        answer = random.choice(["🔴", "🟢", "🔵", "🟡"])

        context.user_data["game"] = {
            "type": "emoji",
            "answer": answer,
        }

        choices = ["🔴", "🟢", "🔵", "🟡"]
        random.shuffle(choices)

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"ansem:{x}"
                )
                for x in choices
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ])

        text = (
            f"🎮 <b>{name}</b>\n\n"
            "🎨 Men yashirin rang tanladim.\n"
            "Qaysi biri?"
        )

    elif kind == 3:
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        answer = a + b

        context.user_data["game"] = {
            "type": "math",
            "answer": answer,
        }

        choices = {answer}

        while len(choices) < 4:
            choices.add(max(0, answer + random.randint(-5, 5)))

        choices = list(choices)
        random.shuffle(choices)

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    str(x),
                    callback_data=f"ansmath:{x}"
                )
                for x in choices
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ])

        text = (
            f"🎮 <b>{name}</b>\n\n"
            f"🧮 <b>{a} + {b} = ?</b>"
        )

    elif kind == 4:
        answer = random.choice(["⬅️", "➡️"])

        context.user_data["game"] = {
            "type": "direction",
            "answer": answer,
        }

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️",
                    callback_data="ansdir:⬅️"
                ),
                InlineKeyboardButton(
                    "➡️",
                    callback_data="ansdir:➡️"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ])

        text = (
            f"🎮 <b>{name}</b>\n\n"
            "🧭 To‘g‘ri yo‘nalishni tanlang!"
        )

    elif kind == 5:
        answer = random.randint(1, 9)

        context.user_data["game"] = {
            "type": "quick",
            "answer": answer,
        }

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    str(i),
                    callback_data=f"ansquick:{i}"
                )
                for i in range(1, 10)
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ])

        text = (
            f"🎮 <b>{name}</b>\n\n"
            f"⚡ <b>{answer}</b> ni toping!"
        )

    elif kind == 6:
        answer = random.choice(["A", "B", "C"])

        context.user_data["game"] = {
            "type": "door",
            "answer": answer,
        }

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🚪 A",
                    callback_data="ansdoor:A"
                ),
                InlineKeyboardButton(
                    "🚪 B",
                    callback_data="ansdoor:B"
                ),
                InlineKeyboardButton(
                    "🚪 C",
                    callback_data="ansdoor:C"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ])

        text = (
            f"🎮 <b>{name}</b>\n\n"
            "🚪 3 ta eshikdan birida xazina bor.\n"
            "Tanlang!"
        )

    elif kind == 7:
        answer = random.choice(["🐱", "🐶", "🦊", "🐼"])

        context.user_data["game"] = {
            "type": "animal",
            "answer": answer,
        }

        choices = ["🐱", "🐶", "🦊", "🐼"]

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"ansanimal:{x}"
                )
                for x in choices
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ])

        text = (
            f"🎮 <b>{name}</b>\n\n"
            "🐾 Yashirin hayvonni toping!"
        )

    else:
        answer = random.choice(["⭐", "🔥", "💎", "🎁"])

        context.user_data["game"] = {
            "type": "choice",
            "answer": answer,
        }

        choices = ["⭐", "🔥", "💎", "🎁"]

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    x,
                    callback_data=f"anschoice:{x}"
                )
                for x in choices
            ],
            [
                InlineKeyboardButton(
                    "🔙 O‘YINLAR",
                    callback_data="games"
                )
            ]
        ])

        text = (
            f"🎮 <b>{name}</b>\n\n"
            "✨ Omadli belgini toping!"
        )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=markup,
        parse_mode="HTML"
    )


async def answer_game(update, context, answer):
    game = context.user_data.get("game")

    if not game:
        await update.callback_query.answer(
            "❌ O‘yin tugagan!",
            show_alert=True
        )
        return

    correct = str(answer) == str(game["answer"])

    game_result(
        update.effective_user.id,
        correct
    )

    context.user_data.pop("game", None)

    if correct:
        text = (
            "🎉 <b>TO‘G‘RI!</b>\n\n"
            f"⭐ Sizga +{GAME_REWARD:.1f} ⭐ berildi!"
        )
    else:
        text = (
            "😅 <b>Noto‘g‘ri!</b>\n\n"
            f"To‘g‘ri javob: <b>{game['answer']}</b>\n"
            "🔄 Yana urinib ko‘ring."
        )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎮 YANA O‘YNASH",
                callback_data="games"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 MENU",
                callback_data="home"
            )
        ]
    ])

    await update.callback_query.message.edit_text(
        text,
        reply_markup=markup,
        parse_mode="HTML"
    )


# =========================
# PROFIL / BALANS
# =========================

async def profile(update, context):
    u = get_user(update.effective_user.id)

    text = (
        "👤 <b>PROFIL</b>\n\n"
        f"🆔 ID: <code>{u['id']}</code>\n"
        f"👤 Username: @{u['username'] or 'yo‘q'}\n"
        f"⭐ Ball: <b>{u['points']:.1f}</b>\n"
        f"🎮 O‘yinlar: <b>{u['games']}</b>\n"
        f"🏆 G‘alabalar: <b>{u['wins']}</b>\n"
        f"👥 Referral: <b>{u['referrals']}</b>"
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 ORQAGA", callback_data="home")]
        ]),
        parse_mode="HTML"
    )


async def balance(update, context):
    u = get_user(update.effective_user.id)

    await update.callback_query.message.edit_text(
        f"⭐ <b>BALANS</b>\n\n"
        f"💰 Sizda: <b>{u['points']:.1f} ⭐</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 YECHISH", callback_data="withdraw")],
            [InlineKeyboardButton("🔙 ORQAGA", callback_data="home")]
        ]),
        parse_mode="HTML"
    )


# =========================
# REFERRAL
# =========================

async def referral(update, context):
    user = update.effective_user

    me = await context.bot.get_me()

    link = f"https://t.me/{me.username}?start=ref_{user.id}"

    u = get_user(user.id)

    text = (
        "👥 <b>DO‘ST TAKLIF</b>\n\n"
        f"🎁 Har bir tasdiqlangan referral: <b>+{REFERRAL_REWARD:g} ⭐</b>\n"
        f"👥 Sizning referral: <b>{u['referrals']}</b>\n\n"
        "🔗 Sizning linkingiz:\n"
        f"<code>{link}</code>\n\n"
        "⚠️ Mukofot faqat yangi foydalanuvchi kanal shartini bajargandan "
        "keyin beriladi."
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


# =========================
# RATING
# =========================

async def top(update, context):
    con = connect()

    rows = con.execute("""
    SELECT username, points, wins
    FROM users
    ORDER BY points DESC
    LIMIT 10
    """).fetchall()

    con.close()

    text = "🏆 <b>TOP 10</b>\n\n"

    if not rows:
        text += "Hali foydalanuvchilar yo‘q."
    else:
        for i, row in enumerate(rows, 1):
            name = "@" + row["username"] if row["username"] else "User"
            text += (
                f"{i}. {name} — "
                f"<b>{row['points']:.1f} ⭐</b> "
                f"({row['wins']} yutuq)\n"
            )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 ORQAGA", callback_data="home")]
        ]),
        parse_mode="HTML"
    )


# =========================
# WITHDRAW
# =========================

async def withdraw(update, context):
    u = get_user(update.effective_user.id)

    if u["referrals"] < MIN_REFERRALS:
        text = (
            "💸 <b>STARS YECHISH</b>\n\n"
            f"👥 Kerakli tasdiqlangan referral: <b>{MIN_REFERRALS}</b>\n"
            f"👥 Sizda: <b>{u['referrals']}</b>\n\n"
            "Avval ko‘proq do‘st taklif qiling."
        )

    elif u["points"] < MIN_WITHDRAW:
        text = (
            "💸 <b>STARS YECHISH</b>\n\n"
            f"⭐ Minimal balans: <b>{MIN_WITHDRAW:g} ⭐</b>\n"
            f"⭐ Sizda: <b>{u['points']:.1f} ⭐</b>"
        )

    else:
        context.user_data["withdraw"] = True

        text = (
            "💸 <b>STARS YECHISH</b>\n\n"
            f"⭐ Balansingiz: <b>{u['points']:.1f} ⭐</b>\n\n"
            "Qancha ⭐ yechmoqchisiz?\n"
            "Masalan: <code>50</code>"
        )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 ORQAGA", callback_data="home")]
        ]),
        parse_mode="HTML"
    )


async def process_withdraw(update, context):
    if not context.user_data.get("withdraw"):
        return False

    try:
        amount = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Faqat son yozing. Masalan: 50")
        return True

    user_id = update.effective_user.id
    u = get_user(user_id)

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimal yechish: {MIN_WITHDRAW:g} ⭐"
        )
        return True

    if amount > u["points"]:
        await update.message.reply_text("❌ Balansingiz yetarli emas.")
        return True

    if u["referrals"] < MIN_REFERRALS:
        await update.message.reply_text(
            f"❌ Sizda kamida {MIN_REFERRALS} ta tasdiqlangan referral bo‘lishi kerak."
        )
        return True

    con = connect()

    # Reserve/deduct the amount immediately so it cannot be withdrawn twice.
    cur = con.cursor()

    cur.execute("""
    UPDATE users
    SET points=ROUND(points-?,1)
    WHERE id=? AND points>=?
    """, (amount, user_id, amount))

    if cur.rowcount != 1:
        con.close()
        await update.message.reply_text("❌ Balans o‘zgardi. Qaytadan urinib ko‘ring.")
        return True

    cur.execute("""
    INSERT INTO withdrawals(user_id,username,amount,status,created_at)
    VALUES(?,?,?,'pending',?)
    """, (
        user_id,
        update.effective_user.username,
        amount,
        now()
    ))

    request_id = cur.lastrowid

    con.commit()
    con.close()

    context.user_data.pop("withdraw", None)

    await update.message.reply_text(
        "✅ <b>So‘rov qabul qilindi!</b>\n\n"
        f"🆔 So‘rov: #{request_id}\n"
        f"⭐ Miqdor: <b>{amount:g} ⭐</b>\n"
        "⏳ Admin tekshiradi.",
        parse_mode="HTML"
    )

    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"💸 <b>YANGI YECHISH SO‘ROVI</b>\n\n"
            f"🆔 #{request_id}\n"
            f"👤 @{update.effective_user.username or 'yo‘q'}\n"
            f"ID: <code>{user_id}</code>\n"
            f"⭐ Miqdor: <b>{amount:g}</b>",
            parse_mode="HTML"
        )
    except TelegramError:
        pass

    return True


# =========================
# ADMIN
# =========================

def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 STATISTIKA",
                callback_data="astats"
            ),
            InlineKeyboardButton(
                "👥 USERLAR",
                callback_data="users:0"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 BROADCAST",
                callback_data="broadcast"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ SHART QO‘SHISH",
                callback_data="addtask"
            ),
            InlineKeyboardButton(
                "➖ SHART O‘CHIRISH",
                callback_data="deltask"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 SHARTLAR",
                callback_data="taskadmin"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ HOMIY QO‘SHISH",
                callback_data="addsponsor"
            ),
            InlineKeyboardButton(
                "➖ HOMIY O‘CHIRISH",
                callback_data="delsponsor"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 ORQAGA",
                callback_data="home"
            )
        ]
    ])


async def admin(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.callback_query.answer(
            "❌ Ruxsat yo‘q!",
            show_alert=True
        )
        return

    await update.callback_query.message.edit_text(
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        "Kerakli bo‘limni tanlang:",
        reply_markup=admin_menu(),
        parse_mode="HTML"
    )


async def admin_stats(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    con = connect()

    total = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    blocked = con.execute(
        "SELECT COUNT(*) FROM users WHERE blocked=1"
    ).fetchone()[0]

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=30)
    ).isoformat()

    active = con.execute("""
    SELECT COUNT(*) FROM users
    WHERE blocked=0 AND last_seen>=?
    """, (cutoff,)).fetchone()[0]

    inactive = max(0, total - blocked - active)

    games = con.execute(
        "SELECT COALESCE(SUM(games),0) FROM users"
    ).fetchone()[0]

    wins = con.execute(
        "SELECT COALESCE(SUM(wins),0) FROM users"
    ).fetchone()[0]

    points = con.execute(
        "SELECT COALESCE(SUM(points),0) FROM users"
    ).fetchone()[0]

    con.close()

    text = (
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Jami user: <b>{total}</b>\n"
        f"🟢 Aktiv: <b>{active}</b>\n"
        f"⚪ Noaktiv: <b>{inactive}</b>\n"
        f"🚫 Bloklagan: <b>{blocked}</b>\n\n"
        f"🎮 O‘yinlar: <b>{games}</b>\n"
        f"🏆 G‘alabalar: <b>{wins}</b>\n"
        f"⭐ Jami ball: <b>{points:.1f}</b>"
    )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 ADMIN", callback_data="admin")]
        ]),
        parse_mode="HTML"
    )


async def users_page(update, context, page):
    if update.effective_user.id != ADMIN_ID:
        return

    con = connect()

    total = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    offset = page * USERS_PER_PAGE

    rows = con.execute("""
    SELECT id,username,points,referrals,games,
           last_seen,blocked
    FROM users
    ORDER BY id DESC
    LIMIT ? OFFSET ?
    """, (USERS_PER_PAGE, offset)).fetchall()

    con.close()

    text = (
        f"👥 <b>BARCHA USERLAR</b>\n"
        f"📄 Sahifa: {page+1}\n\n"
    )

    for r in rows:
        if r["blocked"]:
            status = "🚫 BLOCK"
        else:
            try:
                seen = datetime.fromisoformat(
                    r["last_seen"]
                )

                if (
                    datetime.now(timezone.utc) - seen
                ) <= timedelta(days=30):
                    status = "🟢 AKTIV"
                else:
                    status = "⚪ NOAKTIV"

            except Exception:
                status = "⚪ NOAKTIV"

        name = f"@{r['username']}" if r["username"] else "username yo‘q"

        text += (
            f"{status} | {name}\n"
            f"🆔 <code>{r['id']}</code> | "
            f"⭐ {r['points']:.1f} | "
            f"👥 {r['referrals']}\n"
        )

    buttons = []

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️",
                callback_data=f"users:{page-1}"
            )
        )

    if offset + USERS_PER_PAGE < total:
        nav.append(
            InlineKeyboardButton(
                "➡️",
                callback_data=f"users:{page+1}"
            )
        )

    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(
            "🔙 ADMIN",
            callback_data="admin"
        )
    ])

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )


# =========================
# TASK ADMIN
# =========================

async def task_admin(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    rows = task_list(ADMIN_ID)

    text = "📋 <b>SHARTLAR</b>\n\n"

    for r in rows:
        text += (
            f"#{r['id']} {r['channel']} — "
            f"+{r['reward']:g} ⭐\n"
        )

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 ADMIN", callback_data="admin")]
        ]),
        parse_mode="HTML"
    )


# =========================
# BROADCAST
# =========================

async def broadcast_start(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["broadcast"] = True

    await update.callback_query.message.edit_text(
        "📢 <b>BROADCAST</b>\n\n"
        "Yubormoqchi bo‘lgan xabaringizni yuboring.\n"
        "Matn, rasm, video yoki boshqa Telegram xabari bo‘lishi mumkin.\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML"
    )


async def broadcast_message(update, context):
    if update.effective_user.id != ADMIN_ID:
        return False

    if not context.user_data.get("broadcast"):
        return False

    con = connect()
    rows = con.execute(
        "SELECT id FROM users WHERE blocked=0"
    ).fetchall()
    con.close()

    sent = 0
    failed = 0
    blocked = 0

    for row in rows:
        uid = row["id"]

        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
            sent += 1

        except Forbidden:
            blocked += 1
            mark_blocked(uid)

        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)

            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id,
                )
                sent += 1
            except TelegramError:
                failed += 1

        except TelegramError:
            failed += 1

    context.user_data.pop("broadcast", None)

    await update.message.reply_text(
        "📢 <b>BROADCAST YAKUNLANDI</b>\n\n"
        f"✅ Yuborildi: <b>{sent}</b>\n"
        f"❌ Xato: <b>{failed}</b>\n"
        f"🚫 Bloklagan: <b>{blocked}</b>",
        parse_mode="HTML"
    )

    return True


# =========================
# TEXT INPUT FOR ADMIN
# =========================

async def admin_text(update, context):
    if update.effective_user.id != ADMIN_ID:
        return False

    if context.user_data.get("broadcast"):
        return await broadcast_message(update, context)

    mode = context.user_data.get("admin_mode")

    if mode == "addtask":
        channel = normalize(update.message.text)

        con = connect()
        try:
            con.execute(
                "INSERT OR IGNORE INTO tasks(channel,reward) VALUES(?,?)",
                (channel, TASK_REWARD)
            )
            con.commit()
        finally:
            con.close()

        context.user_data.pop("admin_mode", None)

        await update.message.reply_text(
            f"✅ Shart qo‘shildi: {channel}\n"
            f"🎁 Mukofot: +{TASK_REWARD:g} ⭐"
        )
        return True

    if mode == "deltask":
        channel = normalize(update.message.text)

        if channel == SPONSOR:
            await update.message.reply_text(
                "❌ Asosiy @premyumstarstekin shartini o‘chirib bo‘lmaydi."
            )
            return True

        con = connect()
        con.execute(
            "DELETE FROM tasks WHERE channel=?",
            (channel,)
        )
        con.commit()
        con.close()

        context.user_data.pop("admin_mode", None)

        await update.message.reply_text(
            f"✅ Shart o‘chirildi: {channel}"
        )
        return True

    if mode == "addsponsor":
        channel = normalize(update.message.text)
        add_sponsor(channel)

        context.user_data.pop("admin_mode", None)

        await update.message.reply_text(
            f"✅ Homiy kanal qo‘shildi: {channel}\n\n"
            "⚠️ Bot kanalga admin qilingan bo‘lishi kerak."
        )
        return True

    if mode == "delsponsor":
        channel = normalize(update.message.text)

        if delete_sponsor(channel):
            await update.message.reply_text(
                f"✅ Homiy o‘chirildi: {channel}"
            )
        else:
            await update.message.reply_text(
                "❌ Bu kanalni o‘chirib bo‘lmaydi yoki topilmadi."
            )

        context.user_data.pop("admin_mode", None)
        return True

    return False


# =========================
# CALLBACK
# =========================

async def callback(update, context):
    q = update.callback_query
    await q.answer()

    user = update.effective_user
    touch(user)

    data = q.data

    if data == "noop":
        return

    if data == "home":
        await home(update, context)
        return

    if data == "check_sub":
        if await subscribed(user.id, context):
            reward_referral(user.id)

            await q.message.edit_text(
                "✅ <b>Obuna tasdiqlandi!</b>\n\n"
                "🎉 Endi botdan foydalanishingiz mumkin.",
                reply_markup=home_markup(user.id),
                parse_mode="HTML"
            )
        else:
            await q.answer(
                "❌ Hali kanalga obuna bo‘lmagansiz!",
                show_alert=True
            )
        return

    if data == "tasks":
        await show_tasks(update, context)
        return

    if data.startswith("task:"):
        if not await subscribed(user.id, context):
            await require_sub(update, context)
            return

        task_id = int(data.split(":")[1])
        await check_task(update, context, task_id)
        return

    # Barcha asosiy bo‘limlar subscription talab qiladi.
    if data not in ("admin", "astats", "users:0") and data.startswith(
        ("games", "play:", "ans", "balance", "profile", "ref", "withdraw", "top", "buy")
    ):
        if not await require_sub(update, context):
            return

    if data == "games":
        await show_games(update, context, 0)
        return

    if data.startswith("games:"):
        page = int(data.split(":")[1])
        await show_games(update, context, page)
        return

    if data.startswith("play:"):
        await play_game(
            update,
            context,
            int(data.split(":")[1])
        )
        return

    if data.startswith("ansnum:"):
        await answer_game(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("ansem:"):
        await answer_game(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("ansmath:"):
        await answer_game(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("ansdir:"):
        await answer_game(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("ansquick:"):
        await answer_game(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("ansdoor:"):
        await answer_game(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("ansanimal:"):
        await answer_game(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data.startswith("anschoice:"):
        await answer_game(
            update,
            context,
            data.split(":", 1)[1]
        )
        return

    if data == "balance":
        await balance(update, context)
        return

    if data == "profile":
        await profile(update, context)
        return

    if data == "ref":
        await referral(update, context)
        return

    if data == "top":
        await top(update, context)
        return

    if data == "withdraw":
        await withdraw(update, context)
        return

    if data == "buy":
        await q.message.edit_text(
            "⭐ <b>STARS OLISH</b>\n\n"
            "👇 Stars olish uchun tugmani bosing:",
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
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="HTML"
        )
        return

    # ADMIN
    if data == "admin":
        await admin(update, context)
        return

    if data == "astats":
        await admin_stats(update, context)
        return

    if data.startswith("users:"):
        page = int(data.split(":")[1])
        await users_page(update, context, page)
        return

    if data == "broadcast":
        await broadcast_start(update, context)
        return

    if data == "addtask":
        context.user_data["admin_mode"] = "addtask"

        await q.message.edit_text(
            "➕ <b>SHART QO‘SHISH</b>\n\n"
            "Kanal username yuboring.\n"
            "Masalan: <code>@mychannel</code>\n\n"
            f"🎁 Mukofot avtomatik: +{TASK_REWARD:g} ⭐",
            parse_mode="HTML"
        )
        return

    if data == "deltask":
        context.user_data["admin_mode"] = "deltask"

        await q.message.edit_text(
            "➖ <b>SHART O‘CHIRISH</b>\n\n"
            "O‘chirmoqchi bo‘lgan kanalni yuboring.",
            parse_mode="HTML"
        )
        return

    if data == "taskadmin":
        await task_admin(update, context)
        return

    if data == "addsponsor":
        context.user_data["admin_mode"] = "addsponsor"

        await q.message.edit_text(
            "➕ <b>HOMIY KANAL QO‘SHISH</b>\n\n"
            "Masalan: <code>@kanal</code>\n\n"
            "⚠️ Bot kanalga admin qilingan bo‘lishi kerak.",
            parse_mode="HTML"
        )
        return

    if data == "delsponsor":
        context.user_data["admin_mode"] = "delsponsor"

        await q.message.edit_text(
            "➖ <b>HOMIY KANAL O‘CHIRISH</b>\n\n"
            "Kanal username yuboring.",
            parse_mode="HTML"
        )
        return


# =========================
# START
# =========================

async def start(update, context):
    user = update.effective_user

    referrer = None

    if context.args:
        arg = context.args[0]

        if arg.startswith("ref_"):
            try:
                referrer = int(arg.replace("ref_", ""))
            except ValueError:
                referrer = None

    add_user(user, referrer)
    touch(user)

    if not await subscribed(user.id, context):
        text, markup = subscription_message()

        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="HTML"
        )
        return

    reward_referral(user.id)

    await home(update, context)


# =========================
# MESSAGE ROUTER
# =========================

async def message_handler(update, context):
    user = update.effective_user

    if not user:
        return

    touch(user)

    if user.id == ADMIN_ID:
        handled = await admin_text(update, context)

        if handled:
            return

    handled = await process_withdraw(update, context)

    if handled:
        return

    if not await require_sub(update, context):
        return

    await update.message.reply_text(
        "👇 Menyudan foydalaning:",
        reply_markup=home_markup(user.id)
    )


async def cancel(update, context):
    if update.effective_user.id == ADMIN_ID:
        context.user_data.clear()
        await update.message.reply_text("❌ Bekor qilindi.")


# =========================
# MAIN
# =========================

def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi! GitHub Secrets/Variables ga BOT_TOKEN qo‘ying."
        )

    if not ADMIN_ID:
        raise RuntimeError(
            "ADMIN_ID topilmadi! GitHub Secrets/Variables ga ADMIN_ID qo‘ying."
        )

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(
        CallbackQueryHandler(callback)
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            message_handler
        )
    )

    logger.info("ZERIKDIM BOT ISHLADI")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
