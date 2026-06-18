from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import sqlite3
from datetime import datetime, timedelta
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8922302493:AAEPirPWaUCZNE4xShfCdGyU0JG3-QrZ3Uc")
ADMIN_ID = 7421345767
PORT = int(os.environ.get("PORT", 10000))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

waiting_queue = []
active_chats = {}
searching_users = set()
chat_history = {}
pending_reports = {}

def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bans (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            banned_until TEXT,
            banned_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def ban_user(user_id: int, reason: str, days: int = None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    banned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if days:
        banned_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        banned_until = "forever"
    c.execute("INSERT OR REPLACE INTO bans VALUES (?, ?, ?, ?)", (user_id, reason, banned_until, banned_at))
    conn.commit()
    conn.close()

def unban_user(user_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_banned(user_id: int) -> tuple:
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT reason, banned_until FROM bans WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False, None
    reason, banned_until = row
    if banned_until == "forever":
        return True, "навсегда"
    if datetime.strptime(banned_until, "%Y-%m-%d %H:%M:%S") < datetime.now():
        unban_user(user_id)
        return False, None
    return True, f"до {banned_until}"

async def post_init(application: Application):
    await application.bot.set_my_commands([
        ("start", "Главное меню"),
        ("search", "Поиск собеседника"),
        ("next", "Сменить собеседника"),
        ("stop", "Остановить диалог / поиск"),
    ])
    init_db()

def main_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔀 Случайный")]],
        resize_keyboard=True
    )

def chat_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⏹ Стоп"), KeyboardButton("⏭ Следующий")]],
        resize_keyboard=True
    )

def report_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Пожаловаться", callback_data="report")]
    ])

def admin_ban_keyboard(user_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⛔ Бан на 1 день", callback_data=f"ban_{user_id}_1")],
        [InlineKeyboardButton("⛔ Бан на 7 дней", callback_data=f"ban_{user_id}_7")],
        [InlineKeyboardButton("⛔ Бан на 30 дней", callback_data=f"ban_{user_id}_30")],
        [InlineKeyboardButton("♾ Вечный бан", callback_data=f"ban_{user_id}_0")],
        [InlineKeyboardButton("✅ Отклонить", callback_data=f"ban_{user_id}_no")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}). Обратитесь к администратору.")
        return

    if user_id in active_chats:
        await update.message.reply_text("🤖 Вы уже в диалоге.\n/stop — остановить диалог", reply_markup=chat_keyboard())
        return

    if user_id in searching_users:
        await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
        return

    await update.message.reply_text(
        "👋 Привет! Это анонимный чат.\n\n"
        "Нажми кнопку ниже, чтобы начать поиск случайного собеседника.",
        reply_markup=main_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return

    text = update.message.text

    if text == "🔀 Случайный":
        if user_id in active_chats:
            await update.message.reply_text("🤖 Вы уже в диалоге.\n/stop — остановить диалог", reply_markup=chat_keyboard())
            return
        if user_id in searching_users:
            await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
            return
        if user_id in waiting_queue:
            waiting_queue.remove(user_id)
        searching_users.add(user_id)
        if waiting_queue:
            partner_id = waiting_queue.pop(0)
            searching_users.discard(partner_id)
            active_chats[user_id] = partner_id
            active_chats[partner_id] = user_id
            searching_users.discard(user_id)
            chat_history[user_id] = []
            chat_history[partner_id] = []
            text_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
            await update.message.reply_text(text_msg, reply_markup=chat_keyboard())
            await context.bot.send_message(partner_id, text_msg, reply_markup=chat_keyboard())
        else:
            waiting_queue.append(user_id)
            await update.message.reply_text("🔍 Поиск собеседника...\n🤖 /stop — остановить поиск")
        return

    if text == "⏹ Стоп":
        partner_id = active_chats.pop(user_id, None)
        if partner_id:
            active_chats.pop(partner_id, None)
            if user_id in chat_history and partner_id in chat_history:
                combined = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
                report_id = f"{user_id}_{partner_id}"
                pending_reports[report_id] = {
                    "messages": combined[-20:],
                    "user1": user_id,
                    "user2": partner_id
                }
            chat_history.pop(user_id, None)
            chat_history.pop(partner_id, None)
            await context.bot.send_message(
                partner_id,
                "🤖 Собеседник завершил связь",
                reply_markup=report_keyboard()
            )
            await update.message.reply_text(
                "🤖 Диалог остановлен",
                reply_markup=report_keyboard()
            )
        else:
            if user_id in searching_users:
                searching_users.discard(user_id)
                if user_id in waiting_queue:
                    waiting_queue.remove(user_id)
                await update.message.reply_text(
                    "🤖 Поиск остановлен\n/search — начать поиск собеседника",
                    reply_markup=main_keyboard()
                )
            else:
                await update.message.reply_text(
                    "🤖 Вы ни с кем не общаетесь\n/search — начать поиск собеседника",
                    reply_markup=main_keyboard()
                )
        return

    if text == "⏭ Следующий":
        if user_id in searching_users and user_id not in active_chats:
            await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
            return
        partner_id = active_chats.pop(user_id, None)
        if partner_id:
            active_chats.pop(partner_id, None)
            if user_id in chat_history and partner_id in chat_history:
                combined = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
                report_id = f"{user_id}_{partner_id}"
                pending_reports[report_id] = {
                    "messages": combined[-20:],
                    "user1": user_id,
                    "user2": partner_id
                }
            chat_history.pop(user_id, None)
            chat_history.pop(partner_id, None)
            await context.bot.send_message(
                partner_id,
                "🤖 Собеседник завершил связь",
                reply_markup=report_keyboard()
            )
            await update.message.reply_text(
                "🤖 Собеседник завершил связь",
                reply_markup=report_keyboard()
            )
        if user_id in waiting_queue:
            waiting_queue.remove(user_id)
        searching_users.add(user_id)
        if waiting_queue:
            new_partner = waiting_queue.pop(0)
            searching_users.discard(new_partner)
            active_chats[user_id] = new_partner
            active_chats[new_partner] = user_id
            searching_users.discard(user_id)
            chat_history[user_id] = []
            chat_history[new_partner] = []
            text_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
            await update.message.reply_text(text_msg, reply_markup=chat_keyboard())
            await context.bot.send_message(new_partner, text_msg, reply_markup=chat_keyboard())
        else:
            waiting_queue.append(user_id)
            await update.message.reply_text("🔍 Ищем собеседника...\n🤖 /stop — остановить поиск")
        return

    if user_id not in active_chats:
        await update.message.reply_text(
            "🤖 Вы ни с кем не общаетесь\n/search — начать поиск собеседника",
            reply_markup=main_keyboard()
        )
        return

    partner_id = active_chats[user_id]

    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append(f"<code>{user_id}</code>: {update.message.text or '[медиа]'}")

    if update.message.sticker:
        await context.bot.send_sticker(partner_id, update.message.sticker.file_id)
    elif update.message.photo:
        await context.bot.send_photo(partner_id, update.message.photo[-1].file_id, caption=update.message.caption)
    elif update.message.video:
        await context.bot.send_video(partner_id, update.message.video.file_id, caption=update.message.caption)
    elif update.message.voice:
        await context.bot.send_voice(partner_id, update.message.voice.file_id)
    elif update.message.video_note:
        await context.bot.send_video_note(partner_id, update.message.video_note.file_id)
    elif update.message.document:
        await context.bot.send_document(partner_id, update.message.document.file_id, caption=update.message.caption)
    elif update.message.animation:
        await context.bot.send_animation(partner_id, update.message.animation.file_id, caption=update.message.caption)
    elif update.message.text:
        await context.bot.send_message(partner_id, update.message.text)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "report":
        found = None
        for rid, info in pending_reports.items():
            if user_id == info["user1"] or user_id == info["user2"]:
                found = rid
                break
        if found:
            info = pending_reports.pop(found)
            other_user = info["user2"] if user_id == info["user1"] else info["user1"]
            msgs = "\n".join(info["messages"][-15:]) if info["messages"] else "Нет сообщений"

            await context.bot.send_message(
                ADMIN_ID,
                f"🚩 <b>Жалоба на пользователя</b> <code>{other_user}</code>\n\n"
                f"<b>Диалог:</b>\n{msgs}\n\n"
                f"Выберите действие:",
                parse_mode="HTML",
                reply_markup=admin_ban_keyboard(other_user)
            )
            await query.edit_message_text("✅ Жалоба отправлена администратору. Спасибо!")
        else:
            await query.edit_message_text("⚠️ Не удалось найти диалог для жалобы.")

    elif data.startswith("ban_"):
        if user_id != ADMIN_ID:
            await query.edit_message_text("⛔ Только администратор может это делать.")
            return
        parts = data.split("_")
        target_id = int(parts[1])
        action = parts[2]

        if action == "no":
            await query.edit_message_text("✅ Жалоба отклонена.")
            return

        days_map = {"1": 1, "7": 7, "30": 30, "0": None}
        days = days_map.get(action)

        ban_user(target_id, "Жалоба от пользователя", days)
        reason_text = f"на {days} дн." if days else "навсегда"
        await query.edit_message_text(f"⛔ Пользователь <code>{target_id}</code> забанен ({reason_text}).", parse_mode="HTML")

        try:
            await context.bot.send_message(target_id, f"🚫 Вы заблокированы ({reason_text}) за нарушение правил.")
        except:
            pass

        partner_id = active_chats.pop(target_id, None)
        if partner_id:
            active_chats.pop(partner_id, None)
            await context.bot.send_message(partner_id, "🤖 Собеседник отключён.")
        if target_id in waiting_queue:
            waiting_queue.remove(target_id)
        searching_users.discard(target_id)

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Использование: /unban [user_id]")
        return
    try:
        target = int(context.args[0])
        unban_user(target)
        await update.message.reply_text(f"✅ Пользователь {target} разбанен.")
    except:
        await update.message.reply_text("Неверный ID.")

async def banlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id, reason, banned_until FROM bans")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Список банов пуст.")
        return
    text = "📋 <b>Забаненные:</b>\n\n"
    for uid, reason, until in rows:
        text += f"<code>{uid}</code> — {reason} — {until}\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return
    if user_id in active_chats:
        await update.message.reply_text("🤖 Вы уже в диалоге.\n/stop — остановить диалог", reply_markup=chat_keyboard())
        return
    if user_id in searching_users:
        await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
        return
    if user_id in waiting_queue:
        waiting_queue.remove(user_id)
    searching_users.add(user_id)
    if waiting_queue:
        partner_id = waiting_queue.pop(0)
        searching_users.discard(partner_id)
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        searching_users.discard(user_id)
        chat_history[user_id] = []
        chat_history[partner_id] = []
        text_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
        await update.message.reply_text(text_msg, reply_markup=chat_keyboard())
        await context.bot.send_message(partner_id, text_msg, reply_markup=chat_keyboard())
    else:
        waiting_queue.append(user_id)
        await update.message.reply_text("🔍 Ждём собеседника...\n🤖 /stop — остановить поиск")

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return
    if user_id in searching_users and user_id not in active_chats:
        await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
        return
    partner_id = active_chats.pop(user_id, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        if user_id in chat_history and partner_id in chat_history:
            combined = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
            report_id = f"{user_id}_{partner_id}"
            pending_reports[report_id] = {"messages": combined[-20:], "user1": user_id, "user2": partner_id}
        chat_history.pop(user_id, None)
        chat_history.pop(partner_id, None)
        await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
        await update.message.reply_text("🤖 Собеседник завершил связь", reply_markup=report_keyboard())
    if user_id in waiting_queue:
        waiting_queue.remove(user_id)
    searching_users.add(user_id)
    if waiting_queue:
        new_partner = waiting_queue.pop(0)
        searching_users.discard(new_partner)
        active_chats[user_id] = new_partner
        active_chats[new_partner] = user_id
        searching_users.discard(user_id)
        chat_history[user_id] = []
        chat_history[new_partner] = []
        text_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
        await update.message.reply_text(text_msg, reply_markup=chat_keyboard())
        await context.bot.send_message(new_partner, text_msg, reply_markup=chat_keyboard())
    else:
        waiting_queue.append(user_id)
        await update.message.reply_text("🔍 Ищем собеседника...\n🤖 /stop — остановить поиск")

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = active_chats.pop(user_id, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        if user_id in chat_history and partner_id in chat_history:
            combined = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
            report_id = f"{user_id}_{partner_id}"
            pending_reports[report_id] = {"messages": combined[-20:], "user1": user_id, "user2": partner_id}
        chat_history.pop(user_id, None)
        chat_history.pop(partner_id, None)
        await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
        await update.message.reply_text("🤖 Диалог остановлен", reply_markup=report_keyboard())
    elif user_id in searching_users:
        searching_users.discard(user_id)
        if user_id in waiting_queue:
            waiting_queue.remove(user_id)
        await update.message.reply_text("🤖 Поиск остановлен\n/search — начать поиск собеседника", reply_markup=main_keyboard())
    else:
        await update.message.reply_text("🤖 Вы ни с кем не общаетесь\n/search — начать поиск собеседника", reply_markup=main_keyboard())

    app = def main():
    # Запускаем веб-сервер для UptimeRobot в отдельном потоке
    threading.Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("next", next_chat))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("banlist", banlist_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler, pattern="^(report|ban_).*"))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE |
        filters.Sticker.ALL | filters.Document.ALL | filters.VIDEO_NOTE |
        filters.ANIMATION,
        handle_message
    ))

    print("Бот запущен...")
    app.run_polling()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("next", next_chat))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("banlist", banlist_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler, pattern="^(report|ban_).*"))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE |
        filters.Sticker.ALL | filters.Document.ALL | filters.VIDEO_NOTE |
        filters.ANIMATION,
        handle_message
    ))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
