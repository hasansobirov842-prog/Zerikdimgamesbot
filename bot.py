import os
import sqlite3
import random
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8679536810
DB = "zerikdim.db"

if not TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")


# ================= DATABASE =================

def connect():
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            points INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER,
            last_daily TEXT DEFAULT '',
            last_seen TEXT DEFAULT ''
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            channel TEXT PRIMARY KEY
        )
    """)
    con.commit()
    return con


def add_user(user):
    con = connect()
    now = datetime.now(timezone.utc).isoformat()

    con.execute("""
        INSERT OR IGNORE INTO users
        (id, username, last_seen)
        VALUES (?, ?, ?)
    """, (user.id, user.username or "", now))

    con.execute("""
        UPDATE users
        SET username=?, last_seen=?
        WHERE id=?
    """, (user.username or "", now, user.id))

    con.commit()
    con.close()


def add_points(user_id, amount):
    con = connect()
    con.execute(
        "UPDATE users SET points=points+? WHERE id=?",
        (amount, user_id)
    )
    con.commit()
    con.close()


# ================= MENU =================

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎮 O‘YINLAR", callback_data="games"),
            InlineKeyboardButton("⭐ BALL", callback_data="balance")
        ],
        [
            InlineKeyboardButton("🎁 DAILY", callback_data="daily"),
            InlineKeyboardButton("👥 DO‘ST TAKLIF", callback_data="ref")
        ],
        [
            InlineKeyboardButton("🏆 REYTING", callback_data="top"),
            InlineKeyboardButton("👤 PROFIL", callback_data="profile")
        ]
    ])


def games_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 DARTS", callback_data="darts"),
            InlineKeyboardButton("🎳 BOWLING", callback_data="bowling")
        ],
        [
            InlineKeyboardButton("🎲 ZAR", callback_data="dice"),
            InlineKeyboardButton("🧠 SAVOL-JAVOB", callback_data="quiz")
        ],
        [
            InlineKeyboardButton("🔢 SON TOP", callback_data="numbers"),
            InlineKeyboardButton("🏝️ OROL", callback_data="island")
        ],
        [
            InlineKeyboardButton("🇺🇳 BAYROQ", callback_data="flag"),
            InlineKeyboardButton("🧩 TOPISHMOQ", callback_data="riddle")
        ],
        [
            InlineKeyboardButton("⚡ TEZKOR", callback_data="quick")
        ],
        [
            InlineKeyboardButton("🏠 MENU", callback_data="menu")
        ]
    ])


# ================= QUESTIONS =================

QUIZZES = [
    ("O‘zbekiston poytaxti qaysi?", ["Toshkent", "Samarqand", "Buxoro", "Andijon"], 0),
    ("Dunyodagi eng katta okean?", ["Atlantika", "Tinch", "Hind", "Shimoliy Muz"], 1),
    ("7 × 8 nechchi?", ["54", "56", "58", "64"], 1),
    ("12 + 19 nechchi?", ["29", "30", "31", "32"], 2),
    ("Eng katta sayyora?", ["Mars", "Yer", "Yupiter", "Venera"], 2),
    ("Suvning kimyoviy formulasi?", ["CO2", "H2O", "O2", "NaCl"], 1),
    ("Bir yilda nechta oy bor?", ["10", "11", "12", "13"], 2),
    ("Eng tez yuguruvchi quruqlik hayvoni?", ["Sher", "Gepard", "Ot", "Bo‘ri"], 1),
    ("2, 4, 6, 8, ?", ["9", "10", "11", "12"], 1),
    ("100 ÷ 5 nechchi?", ["10", "15", "20", "25"], 2),
    ("Yerning tabiiy yo‘ldoshi?", ["Quyosh", "Oy", "Mars", "Venera"], 1),
    ("Odamda nechta ko‘z bor?", ["1", "2", "3", "4"], 1),
    ("5 × 9 nechchi?", ["35", "40", "45", "50"], 2),
    ("Eng katta qit’a?", ["Afrika", "Osiyo", "Yevropa", "Avstraliya"], 1),
    ("1 kilometr necha metr?", ["100", "500", "1000", "1500"], 2),
    ("9 + 6 nechchi?", ["14", "15", "16", "17"], 1),
    ("Qaysi biri juft son?", ["13", "17", "22", "31"], 2),
    ("Haftada nechta kun bor?", ["5", "6", "7", "8"], 2),
    ("Eng katta okean qaysi?", ["Tinch", "Hind", "Atlantika", "Arktika"], 0),
    ("Qaysi sayyora Qizil sayyora deyiladi?", ["Mars", "Yer", "Saturn", "Merkuriy"], 0),
]

RIDDLES = [
    ("Tunda chiqadi, kunduz yo‘qoladi. Bu nima?", ["Oy", "Quyosh", "Bulut", "Yulduz"], 0),
    ("Qanoti bor, lekin uchmaydi. Bu nima?", ["Baliq", "Stol", "Eshik", "Qayiq"], 0),
    ("O‘zi suvda yashaydi, lekin suv ichmaydi.", ["Baliq", "Mushuk", "Ot", "Qush"], 0),
    ("Oyoqsiz yuradi, og‘izsiz gapiradi.", ["Soat", "Radio", "Stol", "Kitob"], 0),
    ("Qishda oq, yozda yashil bo‘lishi mumkin.", ["Daraxt", "Quyosh", "Telefon", "Tosh"], 0),
]

FLAGS = [
    ("🇺🇿", ["O‘zbekiston", "Turkiya", "Qozog‘iston", "Afg‘oniston"], 0),
    ("🇹🇷", ["Turkiya", "Italiya", "Ispaniya", "Fransiya"], 0),
    ("🇺🇸", ["Kanada", "AQSH", "Angliya", "Avstraliya"], 1),
    ("🇬🇧", ["Angliya", "Germaniya", "Belgiya", "Avstriya"], 0),
    ("🇯🇵", ["Xitoy", "Koreya", "Yaponiya", "Tailand"], 2),
    ("🇰🇷", ["Yaponiya", "Koreya", "Xitoy", "Vetnam"], 1),
    ("🇩🇪", ["Belgiya", "Germaniya", "Polsha", "Fransiya"], 1),
    ("🇫🇷", ["Fransiya", "Italiya", "Ispaniya", "Portugaliya"], 0),
    ("🇮🇹", ["Italiya", "Gretsiya", "Ispaniya", "Meksika"], 0),
    ("🇰🇿", ["Qirg‘iziston", "Qozog‘iston", "O‘zbekiston", "Tojikiston"], 1),
]


def make_number_question():
    nums = random.sample(range(1, 100), 4)
    correct = max(nums)
    answers = [str(x) for x in nums]
    return f"🔢 Eng katta sonni top:\n\n{nums}", answers, answers.index(str(correct))


def make_odd_question():
    nums = [
        random.randrange(1, 100, 2),
        random.randrange(2, 100, 2),
        random.randrange(2, 100, 2),
        random.randrange(2, 100, 2)
    ]
    random.shuffle(nums)
    correct = next(x for x in nums if x % 2 == 1)
    answers = [str(x) for x in nums]
    return "🔢 Toq sonni top:\n\n" + str(nums), answers, answers.index(str(correct))


def make_math():
    a = random.randint(2, 30)
    b = random.randint(2, 20)
    op = random.choice(["+", "-", "×"])

    if op == "+":
        correct = a + b
    elif op == "-":
        if b > a:
            a, b = b, a
        correct = a - b
    else:
        correct = a * b

    answers = {correct}
    while len(answers) < 4:
        answers.add(correct + random.randint(-10, 10))

    answers = list(answers)
    random.shuffle(answers)

    return f"🧠 {a} {op} {b} = ?", [str(x) for x in answers], answers.index(str(correct))


# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user)

    if context.args:
        try:
            ref_id = int(context.args[0])

            if ref_id != user.id:
                con = connect()

                old = con.execute(
                    "SELECT referred_by FROM users WHERE id=?",
                    (user.id,)
                ).fetchone()

                ref_exists = con.execute(
                    "SELECT id FROM users WHERE id=?",
                    (ref_id,)
                ).fetchone()

                if old and old[0] is None and ref_exists:
                    con.execute("""
                        UPDATE users
                        SET referred_by=?
                        WHERE id=?
                    """, (ref_id, user.id))

                    con.execute("""
                        UPDATE users
                        SET points=points+3,
                            referrals=referrals+1
                        WHERE id=?
                    """, (ref_id,))

                    con.commit()

                con.close()
        except:
            pass

    await update.message.reply_text(
        "🔥 <b>ZERIKDIM</b>\n\n"
        "🎮 Zerikdingmi? O‘yin o‘yna!\n"
        "⭐ Ball yig‘!\n"
        "🏆 Reytingga chiq!\n"
        "👥 Do‘stlaringni taklif qil!",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# ================= GAMES =================

async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "🎮 <b>O‘YINLAR</b>\n\n"
        "Istagan o‘yinni tanla 👇",
        reply_markup=games_menu(),
        parse_mode="HTML"
    )


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    item = random.choice(QUIZZES)
    question, answers, correct = item

    context.user_data["answer"] = correct
    context.user_data["game"] = "quiz"

    keyboard = []
    for i in range(0, 4, 2):
        keyboard.append([
            InlineKeyboardButton(answers[i], callback_data=f"ans:{i}"),
            InlineKeyboardButton(answers[i + 1], callback_data=f"ans:{i+1}")
        ])

    await q.edit_message_text(
        f"🧠 <b>SAVOL-JAVOB</b>\n\n{question}\n\n"
        "✅ To‘g‘ri javob = ⭐ 1",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def number_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    question, answers, correct = (
        make_number_question()
        if random.choice([True, False])
        else make_odd_question()
    )

    context.user_data["answer"] = correct
    context.user_data["game"] = "numbers"

    keyboard = []
    for i in range(0, 4, 2):
        keyboard.append([
            InlineKeyboardButton(answers[i], callback_data=f"ans:{i}"),
            InlineKeyboardButton(answers[i + 1], callback_data=f"ans:{i+1}")
        ])

    await q.edit_message_text(
        question,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def math_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    question, answers, correct = make_math()

    context.user_data["answer"] = correct
    context.user_data["game"] = "math"

    keyboard = []
    for i in range(0, 4, 2):
        keyboard.append([
            InlineKeyboardButton(answers[i], callback_data=f"ans:{i}"),
            InlineKeyboardButton(answers[i + 1], callback_data=f"ans:{i+1}")
        ])

    await q.edit_message_text(
        question,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def riddle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    question, answers, correct = random.choice(RIDDLES)

    context.user_data["answer"] = correct
    context.user_data["game"] = "riddle"

    keyboard = []
    for i in range(0, 4, 2):
        keyboard.append([
            InlineKeyboardButton(answers[i], callback_data=f"ans:{i}"),
            InlineKeyboardButton(answers[i + 1], callback_data=f"ans:{i+1}")
        ])

    await q.edit_message_text(
        f"🧩 <b>TOPISHMOQ</b>\n\n{question}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def flag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    emoji, answers, correct = random.choice(FLAGS)

    context.user_data["answer"] = correct
    context.user_data["game"] = "flag"

    keyboard = []
    for i in range(0, 4, 2):
        keyboard.append([
            InlineKeyboardButton(answers[i], callback_data=f"ans:{i}"),
            InlineKeyboardButton(answers[i + 1], callback_data=f"ans:{i+1}")
        ])

    await q.edit_message_text(
        f"🇺🇳 <b>BAYROQNI TOP</b>\n\n{emoji}\n\n"
        "Bu qaysi davlat?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def island(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    islands = [
        ("Greenland", "Madagaskar", "Grenlandiya"),
        ("Borneo", "Java", "Borneo"),
        ("Sumatra", "Islandiya", "Sumatra"),
        ("Madagaskar", "Kuba", "Madagaskar")
    ]

    a, b, correct = random.choice(islands)

    answers = [a, b, "Kuba", "Java"]
    answers = list(dict.fromkeys(answers))

    while len(answers) < 4:
        answers.append(random.choice(["Islandiya", "Sitsiliya", "Tasmaniya"]))

    answers = answers[:4]
    random.shuffle(answers)

    context.user_data["answer_text"] = correct
    context.user_data["game"] = "island"

    keyboard = []
    for i in range(0, 4, 2):
        keyboard.append([
            InlineKeyboardButton(answers[i], callback_data=f"text:{answers[i]}"),
            InlineKeyboardButton(answers[i + 1], callback_data=f"text:{answers[i+1]}")
        ])

    await q.edit_message_text(
        "🏝️ <b>QAYSI OROL KATTA?</b>\n\n"
        f"{a} yoki {b}?\n\n"
        "To‘g‘ri javob = ⭐ 1",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


# ================= DICE GAMES =================

async def send_dice_game(update: Update, context: ContextTypes.DEFAULT_TYPE, emoji, name):
    q = update.callback_query
    await q.answer()

    await q.message.reply_text(f"{emoji} <b>{name}</b>\n\nOmad emas, challenge! 🎮",
                               parse_mode="HTML")

    msg = await q.message.reply_dice(emoji=emoji)

    value = msg.dice.value

    if value >= 4:
        add_points(q.from_user.id, 1)
        result = "🎉 Zo‘r! ⭐ +1"
    else:
        result = "😅 Bu safar bo‘lmadi."

    await q.message.reply_text(result)


async def darts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_dice_game(update, context, "🎯", "DARTS")


async def bowling(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_dice_game(update, context, "🎳", "BOWLING")


async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_dice_game(update, context, "🎲", "ZAR")


# ================= ANSWERS =================

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    selected = int(q.data.split(":")[1])
    correct = context.user_data.get("answer")

    con = connect()
    con.execute(
        "UPDATE users SET games=games+1 WHERE id=?",
        (q.from_user.id,)
    )

    if selected == correct:
        con.execute(
            "UPDATE users SET points=points+1,wins=wins+1 WHERE id=?",
            (q.from_user.id,)
        )
        text = "🎉 <b>TO‘G‘RI!</b>\n\n⭐ +1"
    else:
        text = "❌ <b>Noto‘g‘ri!</b>\n\nYana urinib ko‘r 😎"

    con.commit()
    con.close()

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 YANA O‘YNASH", callback_data="games")],
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )


async def text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    selected = q.data.split(":", 1)[1]
    correct = context.user_data.get("answer_text")

    con = connect()
    con.execute(
        "UPDATE users SET games=games+1 WHERE id=?",
        (q.from_user.id,)
    )

    if selected == correct:
        con.execute(
            "UPDATE users SET points=points+1,wins=wins+1 WHERE id=?",
            (q.from_user.id,)
        )
        text = "🎉 <b>TO‘G‘RI!</b>\n⭐ +1"
    else:
        text = f"❌ Noto‘g‘ri!\n\nTo‘g‘ri javob: {correct}"

    con.commit()
    con.close()

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 YANA", callback_data="games")],
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )


# ================= DAILY =================

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    today = datetime.now(timezone.utc).date().isoformat()

    con = connect()
    row = con.execute(
        "SELECT last_daily FROM users WHERE id=?",
        (q.from_user.id,)
    ).fetchone()

    if row and row[0] == today:
        text = "⏳ <b>Daily bonusni bugun olding.</b>\n\nErtaga yana olasan!"
    else:
        con.execute("""
            UPDATE users
            SET points=points+2,last_daily=?
            WHERE id=?
        """, (today, q.from_user.id))
        con.commit()
        text = "🎁 <b>DAILY BONUS!</b>\n\n⭐ +2"

    con.close()

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )


# ================= BALANCE =================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    con = connect()
    row = con.execute(
        "SELECT points,wins,games,referrals FROM users WHERE id=?",
        (q.from_user.id,)
    ).fetchone()
    con.close()

    await q.edit_message_text(
        f"⭐ <b>BALANS</b>\n\n"
        f"⭐ Ball: {row[0]}\n"
        f"🏆 G‘alaba: {row[1]}\n"
        f"🎮 O‘yinlar: {row[2]}\n"
        f"👥 Referral: {row[3]}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )


# ================= REFERRAL =================

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={q.from_user.id}"

    con = connect()
    refs = con.execute(
        "SELECT referrals FROM users WHERE id=?",
        (q.from_user.id,)
    ).fetchone()[0]
    con.close()

    if refs >= 5:
        status = "🔓 5 ta do‘st taklif qilish talabi bajarildi!"
    else:
        status = f"🔒 Yana {5 - refs} ta do‘st kerak."

    await q.edit_message_text(
        "👥 <b>DO‘ST TAKLIF QILISH</b>\n\n"
        "Har bir yangi do‘st uchun ⭐ +3\n\n"
        f"👥 Sizning referral: {refs}/5\n"
        f"{status}\n\n"
        f"🔗 <code>{link}</code>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )


# ================= PROFILE =================

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    con = connect()
    row = con.execute("""
        SELECT username,points,wins,games,referrals
        FROM users WHERE id=?
    """, (q.from_user.id,)).fetchone()
    con.close()

    await q.edit_message_text(
        f"👤 <b>PROFIL</b>\n\n"
        f"Username: @{row[0] or 'user'}\n"
        f"⭐ Ball: {row[1]}\n"
        f"🏆 G‘alaba: {row[2]}\n"
        f"🎮 O‘yinlar: {row[3]}\n"
        f"👥 Do‘stlar: {row[4]}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )


# ================= TOP =================

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    con = connect()
    rows = con.execute("""
        SELECT username,points
        FROM users
        ORDER BY points DESC
        LIMIT 10
    """).fetchall()
    con.close()

    text = "🏆 <b>TOP 10</b>\n\n"

    if not rows:
        text += "Hali hech kim yo‘q."
    else:
        for i, row in enumerate(rows, 1):
            name = row[0] or "user"
            text += f"{i}. @{name} — ⭐ {row[1]}\n"

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )


# ================= SPONSOR =================

async def get_sponsors():
    con = connect()
    rows = con.execute("SELECT channel FROM sponsors").fetchall()
    con.close()
    return [x[0] for x in rows]


async def check_subscription(bot, user_id):
    channels = await get_sponsors()

    for channel in channels:
        try:
            member = await bot.get_chat_member(channel, user_id)

            if member.status in [
                ChatMemberStatus.LEFT,
                ChatMemberStatus.BANNED
            ]:
                return False
        except:
            return False

    return True


# ================= ADMIN =================

def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 STATISTIKA", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("📢 HOMIY QO‘SHISH", callback_data="add_sponsor"),
            InlineKeyboardButton("🗑 HOMIY O‘CHIRISH", callback_data="remove_sponsor")
        ],
        [
            InlineKeyboardButton("📋 HOMIYLAR", callback_data="sponsors")
        ],
        [
            InlineKeyboardButton("🏠 MENU", callback_data="menu")
        ]
    ])


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "👑 <b>ADMIN PANEL</b>",
        reply_markup=admin_menu(),
        parse_mode="HTML"
    )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        return

    con = connect()

    total = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    active = con.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE last_seen >= datetime('now', '-1 day')
    """).fetchone()[0]

    games_count = con.execute(
        "SELECT COALESCE(SUM(games),0) FROM users"
    ).fetchone()[0]

    points = con.execute(
        "SELECT COALESCE(SUM(points),0) FROM users"
    ).fetchone()[0]

    today = datetime.now(timezone.utc).date().isoformat()

    new_today = con.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE substr(last_seen,1,10)=?
    """, (today,)).fetchone()[0]

    con.close()

    await q.edit_message_text(
        f"📊 <b>STATISTIKA</b>\n\n"
        f"👥 Jami foydalanuvchi: {total}\n"
        f"🟢 Aktiv (24 soat): {active}\n"
        f"🆕 Bugun: {new_today}\n"
        f"🎮 Jami o‘yinlar: {games_count}\n"
        f"⭐ Jami ball: {points}",
        reply_markup=admin_menu(),
        parse_mode="HTML"
    )


async def sponsors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        return

    channels = await get_sponsors()

    text = "📋 <b>HOMIY KANALLAR</b>\n\n"

    if not channels:
        text += "Hali kanal qo‘shilmagan."
    else:
        for ch in channels:
            text += f"📢 {ch}\n"

    await q.edit_message_text(
        text,
        reply_markup=admin_menu(),
        parse_mode="HTML"
    )


async def add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        return

    context.user_data["waiting_sponsor_add"] = True

    await q.message.reply_text(
        "📢 Homiy kanal username'ini yubor:\n\n"
        "Masalan: <code>@kanal</code>",
        parse_mode="HTML"
    )


async def remove_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        return

    context.user_data["waiting_sponsor_remove"] = True

    await q.message.reply_text(
        "🗑 O‘chiriladigan kanalni yubor:\n\n"
        "Masalan: <code>@kanal</code>",
        parse_mode="HTML"
    )


async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    text = update.message.text.strip()

    if context.user_data.get("waiting_sponsor_add"):
        channel = text if text.startswith("@") else "@" + text

        con = connect()
        con.execute(
            "INSERT OR IGNORE INTO sponsors(channel) VALUES(?)",
            (channel,)
        )
        con.commit()
        con.close()

        context.user_data["waiting_sponsor_add"] = False

        await update.message.reply_text(
            f"✅ Homiy kanal qo‘shildi: {channel}"
        )
        return

    if context.user_data.get("waiting_sponsor_remove"):
        channel = text if text.startswith("@") else "@" + text

        con = connect()
        con.execute(
            "DELETE FROM sponsors WHERE channel=?",
            (channel,)
        )
        con.commit()
        con.close()

        context.user_data["waiting_sponsor_remove"] = False

        await update.message.reply_text(
            f"✅ Homiy kanal o‘chirildi: {channel}"
        )


# ================= MENU BUTTON =================

async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "🏠 <b>ASOSIY MENU</b>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# ================= MAIN =================

def main():
    connect()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(CallbackQueryHandler(games, "^games$"))
    app.add_handler(CallbackQueryHandler(quiz, "^quiz$"))
    app.add_handler(CallbackQueryHandler(number_game, "^numbers$"))
    app.add_handler(CallbackQueryHandler(math_game, "^math$"))
    app.add_handler(CallbackQueryHandler(riddle, "^riddle$"))
    app.add_handler(CallbackQueryHandler(flag, "^flag$"))
    app.add_handler(CallbackQueryHandler(island, "^island$"))

    app.add_handler(CallbackQueryHandler(darts, "^darts$"))
    app.add_handler(CallbackQueryHandler(bowling, "^bowling$"))
    app.add_handler(CallbackQueryHandler(dice, "^dice$"))

    app.add_handler(CallbackQueryHandler(answer, "^ans:"))
    app.add_handler(CallbackQueryHandler(text_answer, "^text:"))

    app.add_handler(CallbackQueryHandler(balance, "^balance$"))
    app.add_handler(CallbackQueryHandler(daily, "^daily$"))
    app.add_handler(CallbackQueryHandler(referral, "^ref$"))
    app.add_handler(CallbackQueryHandler(profile, "^profile$"))
    app.add_handler(CallbackQueryHandler(top, "^top$"))

    app.add_handler(CallbackQueryHandler(admin_stats, "^admin_stats$"))
    app.add_handler(CallbackQueryHandler(add_sponsor, "^add_sponsor$"))
    app.add_handler(CallbackQueryHandler(remove_sponsor, "^remove_sponsor$"))
    app.add_handler(CallbackQueryHandler(sponsors, "^sponsors$"))

    app.add_handler(CallbackQueryHandler(menu_button, "^menu$"))

    app.add_handler(
        __import__("telegram.ext", fromlist=["MessageHandler"])
        .MessageHandler(
            __import__("telegram.ext", fromlist=["filters"]).filters.TEXT
            & ~__import__("telegram.ext", fromlist=["filters"]).filters.COMMAND,
            admin_text
        )
    )

    print("ZERIKDIM BOT ISHLADI")
    app.run_polling()


if __name__ == "__main__":
    main()
