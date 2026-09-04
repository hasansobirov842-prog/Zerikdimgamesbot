import os
import random
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
DB = "zerikdim.db"

if not TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")

GAMES = [
    ("7 + 8 = ?", ["15", "16", "17", "18"], 0),
    ("12 × 2 = ?", ["22", "24", "26", "28"], 1),
    ("50 − 17 = ?", ["33", "34", "35", "37"], 0),
    ("9 × 5 = ?", ["40", "45", "50", "55"], 1),
    ("100 ÷ 4 = ?", ["20", "25", "30", "40"], 1),
    ("2, 4, 6, 8, ?", ["9", "10", "11", "12"], 1),
    ("5, 10, 15, 20, ?", ["22", "24", "25", "30"], 2),
    ("Qaysi biri juft?", ["13", "21", "35", "42"], 3),
]

def db():
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT,
            stars INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            refs INTEGER DEFAULT 0
        )
    """)
    con.commit()
    return con

def user_add(u):
    con = db()
    con.execute(
        "INSERT OR IGNORE INTO users(id, username) VALUES(?,?)",
        (u.id, u.username or "")
    )
    con.commit()
    con.close()

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 O‘YIN", callback_data="play")],
        [
            InlineKeyboardButton("⭐ BALANS", callback_data="balance"),
            InlineKeyboardButton("🎁 DAILY", callback_data="daily")
        ],
        [InlineKeyboardButton("👥 DO‘ST TAKLIF", callback_data="ref")],
        [InlineKeyboardButton("🏆 REYTING", callback_data="top")],
        [InlineKeyboardButton("👤 PROFIL", callback_data="profile")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user_add(u)

    if context.args:
        try:
            ref = int(context.args[0])
            if ref != u.id:
                con = db()
                exists = con.execute(
                    "SELECT id FROM users WHERE id=?",
                    (ref,)
                ).fetchone()
                if exists:
                    con.execute(
                        "UPDATE users SET stars=stars+3, refs=refs+1 WHERE id=?",
                        (ref,)
                    )
                    con.commit()
                con.close()
        except:
            pass

    await update.message.reply_text(
        "🔥 <b>ZERIKDIM</b>\n\n"
        "🎮 O‘yin o‘yna\n"
        "⭐ Stars yig‘\n"
        "👥 Do‘st taklif qil\n"
        "🏆 Reytingda ko‘taril!",
        reply_markup=menu(),
        parse_mode="HTML"
    )

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    question, answers, correct = random.choice(GAMES)
    context.user_data["correct"] = correct

    keys = [
        [
            InlineKeyboardButton(answers[0], callback_data="a0"),
            InlineKeyboardButton(answers[1], callback_data="a1")
        ],
        [
            InlineKeyboardButton(answers[2], callback_data="a2"),
            InlineKeyboardButton(answers[3], callback_data="a3")
        ]
    ]

    await q.edit_message_text(
        f"🎮 <b>MISSIYA</b>\n\n{question}\n\n"
        "To‘g‘ri javob: ⭐ +5",
        reply_markup=InlineKeyboardMarkup(keys),
        parse_mode="HTML"
    )

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    selected = int(q.data[1:])
    correct = context.user_data.get("correct")

    if selected == correct:
        con = db()
        con.execute(
            "UPDATE users SET stars=stars+5,wins=wins+1 WHERE id=?",
            (q.from_user.id,)
        )
        con.commit()
        con.close()

        text = "🎉 <b>TO‘G‘RI!</b>\n\n⭐ +5"
    else:
        text = "❌ <b>Noto‘g‘ri!</b>\n\nYana urinib ko‘r!"

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 YANA", callback_data="play")],
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    con = db()
    row = con.execute(
        "SELECT stars,wins,refs FROM users WHERE id=?",
        (q.from_user.id,)
    ).fetchone()
    con.close()

    await q.edit_message_text(
        f"⭐ <b>BALANS</b>\n\n"
        f"⭐ Stars: {row[0]}\n"
        f"🏆 G‘alaba: {row[1]}\n"
        f"👥 Referral: {row[2]}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    con = db()
    con.execute(
        "UPDATE users SET stars=stars+5 WHERE id=?",
        (q.from_user.id,)
    )
    con.commit()
    con.close()

    await q.edit_message_text(
        "🎁 <b>DAILY BONUS</b>\n\n⭐ +5",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )

async def ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={q.from_user.id}"

    await q.edit_message_text(
        "👥 <b>DO‘ST TAKLIF QIL</b>\n\n"
        "Har bir yangi do‘st uchun ⭐ +3\n\n"
        f"🔗 <code>{link}</code>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    con = db()
    rows = con.execute(
        "SELECT username,stars FROM users ORDER BY stars DESC LIMIT 10"
    ).fetchall()
    con.close()

    text = "🏆 <b>TOP 10</b>\n\n"

    for i, (username, stars) in enumerate(rows, 1):
        text += f"{i}. @{username or 'user'} — ⭐ {stars}\n"

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    con = db()
    row = con.execute(
        "SELECT stars,wins,refs FROM users WHERE id=?",
        (q.from_user.id,)
    ).fetchone()
    con.close()

    await q.edit_message_text(
        f"👤 <b>PROFIL</b>\n\n"
        f"⭐ {row[0]}\n"
        f"🏆 {row[1]} g‘alaba\n"
        f"👥 {row[2]} referral",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 MENU", callback_data="menu")]
        ]),
        parse_mode="HTML"
    )

async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🏠 <b>ASOSIY MENYU</b>",
        reply_markup=menu(),
        parse_mode="HTML"
    )

def main():
    db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(play, "^play$"))
    app.add_handler(CallbackQueryHandler(answer, "^a[0-3]$"))
    app.add_handler(CallbackQueryHandler(balance, "^balance$"))
    app.add_handler(CallbackQueryHandler(daily, "^daily$"))
    app.add_handler(CallbackQueryHandler(ref, "^ref$"))
    app.add_handler(CallbackQueryHandler(top, "^top$"))
    app.add_handler(CallbackQueryHandler(profile, "^profile$"))
    app.add_handler(CallbackQueryHandler(menu_button, "^menu$"))

    app.run_polling()

if __name__ == "__main__":
    main()
