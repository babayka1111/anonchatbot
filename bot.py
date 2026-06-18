from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
import sqlite3
from datetime import datetime, timedelta
import os
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8922302493:AAEPirPWaUCZNE4xShfCdGyU0JG3-QrZ3Uc")
MODER_BOT_TOKEN = "8766775527:AAG-qpeP0QcgMY4cJjA8cxPhoa9037FldgQ"
ADMIN_ID = 7421345767
PORT = int(os.environ.get("PORT", 10000))
CHOOSING_GENDER = 0

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

waiting_queue = []
waiting_male = []
waiting_female = []
active_chats = {}
searching_users = set()
chat_history = {}
pending_reports = {}
moder_monitoring = True

def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS bans (user_id INTEGER PRIMARY KEY, reason TEXT, banned_until TEXT, banned_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS referrals (user_id INTEGER, referral_id INTEGER, registered_at TEXT, counted INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS premium (user_id INTEGER PRIMARY KEY, premium_until TEXT, activated_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS genders (user_id INTEGER PRIMARY KEY, gender TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ref_codes (user_id INTEGER PRIMARY KEY, code TEXT)""")
    conn.commit()
    conn.close()

def ban_user(user_id: int, reason: str, days: int = None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    banned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    banned_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days else "forever"
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

def get_gender(user_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT gender FROM genders WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_gender(user_id: int, gender: str):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO genders VALUES (?, ?)", (user_id, gender))
    conn.commit()
    conn.close()

def get_ref_code(user_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT code FROM ref_codes WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        code = str(uuid.uuid4())[:8]
        c.execute("INSERT OR REPLACE INTO ref_codes VALUES (?, ?)", (user_id, code))
        conn.commit()
        conn.close()
        return code
    conn.close()
    return row[0]

def get_referral_count(user_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE user_id = ? AND counted = 1", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def add_referral(user_id: int, referral_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referral_id = ?", (referral_id,))
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO referrals (user_id, referral_id, registered_at) VALUES (?, ?, ?)", 
                  (user_id, referral_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def count_referral(referral_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE referrals SET counted = 1 WHERE referral_id = ? AND counted = 0", (referral_id,))
    c.execute("SELECT user_id FROM referrals WHERE referral_id = ?", (referral_id,))
    row = c.fetchone()
    conn.commit()
    conn.close()
    if row:
        check_premium(row[0])

def check_premium(user_id: int):
    count = get_referral_count(user_id)
    if count >= 10:
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("SELECT premium_until FROM premium WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        now = datetime.now()
        if not row or datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") < now:
            premium_until = (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT OR REPLACE INTO premium VALUES (?, ?, ?)", 
                      (user_id, premium_until, now.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        return True
    return False

def has_premium(user_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT premium_until FROM premium WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    if datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") < datetime.now():
        return False
    return True

def get_premium_info(user_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT premium_until, activated_at FROM premium WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    until = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    activated = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
    now = datetime.now()
    if until < now:
        return None
    remaining = until - now
    passed = now - activated
    return remaining, passed

async def post_init(application: Application):
    await application.bot.set_my_commands([
        ("start", "Главное меню"),
        ("search", "Поиск собеседника"),
        ("next", "Сменить собеседника"),
        ("stop", "Остановить диалог / поиск"),
        ("ref", "Реферальная система"),
        ("prem", "Статус подписки"),
    ])
    init_db()

def main_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🔀 Случайный")]], resize_keyboard=True)

def premium_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🙎‍♀️ Девушку"), KeyboardButton("🔀 Случайный"), KeyboardButton("🙎‍♂️ Парня")]
    ], resize_keyboard=True)

def chat_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("⏹ Стоп"), KeyboardButton("⏭ Следующий")]], resize_keyboard=True)

def gender_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🙎‍♂️ Я парень", callback_data="gender_male"),
         InlineKeyboardButton("🙎‍♀️ Я девушка", callback_data="gender_female")]
    ])

def report_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ Пожаловаться", callback_data="report")]])

def admin_ban_keyboard(user_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⛔ Бан на 1 день", callback_data=f"ban_{user_id}_1")],
        [InlineKeyboardButton("⛔ Бан на 7 дней", callback_data=f"ban_{user_id}_7")],
        [InlineKeyboardButton("⛔ Бан на 30 дней", callback_data=f"ban_{user_id}_30")],
        [InlineKeyboardButton("♾ Вечный бан", callback_data=f"ban_{user_id}_0")],
        [InlineKeyboardButton("✅ Отклонить", callback_data=f"ban_{user_id}_no")],
    ])

async def notify_moderator(context: ContextTypes.DEFAULT_TYPE, user_id: int, partner_id: int, text: str, is_media: bool = False):
    if not moder_monitoring:
        return
    try:
        msg = f"💬 <a href='tg://user?id={user_id}'>{user_id}</a>: {text or '[медиа]'}"
        await context.bot.send_message(ADMIN_ID, msg, parse_mode="HTML")
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return ConversationHandler.END

    # Реферальная логика
    if args:
        ref_code = args[0]
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("SELECT user_id FROM ref_codes WHERE code = ?", (ref_code,))
        row = c.fetchone()
        conn.close()
        if row and row[0] != user_id:
            add_referral(row[0], user_id)

    gender = get_gender(user_id)
    if gender is None:
        await update.message.reply_text(
            "👋 Привет! Это анонимный чат.\n"
            "Общайся вежливо, соблюдай правила поведения.\n\n"
            "Для начала выбери свой пол:",
            reply_markup=gender_keyboard()
        )
        return CHOOSING_GENDER

    if user_id in active_chats:
        await update.message.reply_text("🤖 Вы уже в диалоге.\n/stop — остановить диалог", reply_markup=chat_keyboard())
        return ConversationHandler.END

    if user_id in searching_users:
        await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
        return ConversationHandler.END

    kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
    await update.message.reply_text(
        "👋 Привет! Это анонимный чат.\n"
        "Общайся вежливо, соблюдай правила поведения.\n\n"
        "Нажми кнопку ниже, чтобы начать поиск случайного собеседника.\n\n"
        "/start — перезапуск бота\n"
        "/search — поиск собеседника\n"
        "/next — переключить собеседника\n"
        "/stop — завершить диалог\n"
        "/ref — реферальная система\n"
        "/prem — статус подписки\n\n"
        "После каждого диалога вы можете пожаловаться на собеседника",
        reply_markup=kb
    )
    return ConversationHandler.END

async def gender_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    gender = "male" if query.data == "gender_male" else "female"
    set_gender(user_id, gender)
    kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
    await query.edit_message_text(
        "✅ Пол сохранён!\n\n"
        "👋 Привет! Это анонимный чат.\n"
        "Общайся вежливо, соблюдай правила поведения.\n\n"
        "Нажми кнопку ниже, чтобы начать поиск случайного собеседника.\n\n"
        "/ref — реферальная система\n"
        "/prem — статус подписки",
    )
    await query.message.reply_text("Выбери действие:", reply_markup=kb)
    return ConversationHandler.END

async def ref_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = get_ref_code(user_id)
    link = f"https://t.me/{(await context.bot.get_me()).username}?start={code}"
    count = get_referral_count(user_id)
    has_prem = has_premium(user_id)
    prem_info = get_premium_info(user_id)

    text = (
        "🔗 <b>Реферальная система</b>\n\n"
        "✅ Пригласи 10 друзей, которые <b>реально пообщаются</b> в боте "
        "(найдут собеседника и отправят хотя бы одно сообщение), "
        "и ты получишь доступ к <b>поиску по полу на 7 дней</b>!\n\n"
        f"🔗 Твоя ссылка:\n<code>{link}</code>\n"
        f"📊 Приглашено: {count}/10\n"
    )
    if has_prem:
        remaining, passed = prem_info
        text += (
            f"\n✅ <b>Подписка активна!</b>\n"
            f"⏳ Осталось: {remaining.days} дн. {remaining.seconds // 3600} ч.\n"
            f"🕐 Прошло: {passed.days} дн. {passed.seconds // 3600} ч."
        )
    await update.message.reply_text(text, parse_mode="HTML")

async def prem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prem_info = get_premium_info(user_id)
    if not prem_info:
        await update.message.reply_text(
            "❌ У вас нет активной подписки.\n"
            "Пригласите 10 друзей через /ref чтобы получить доступ к поиску по полу."
        )
        return
    remaining, passed = prem_info
    await update.message.reply_text(
        f"✅ <b>Подписка активна!</b>\n"
        f"⏳ Осталось: {remaining.days} дн. {remaining.seconds // 3600} ч.\n"
        f"🕐 Прошло: {passed.days} дн. {passed.seconds // 3600} ч.",
        parse_mode="HTML"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return

    text = update.message.text

    # Поиск по кнопкам
    if text in ["🔀 Случайный", "🙎‍♀️ Девушку", "🙎‍♂️ Парня"]:
        if user_id in active_chats:
            await update.message.reply_text("🤖 Вы уже в диалоге.\n/stop — остановить диалог", reply_markup=chat_keyboard())
            return
        if user_id in searching_users:
            await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
            return

        if user_id in waiting_queue:
            waiting_queue.remove(user_id)
        if user_id in waiting_male:
            waiting_male.remove(user_id)
        if user_id in waiting_female:
            waiting_female.remove(user_id)

        searching_users.add(user_id)
        target_gender = None
        if text == "🙎‍♀️ Девушку":
            target_gender = "female"
        elif text == "🙎‍♂️ Парня":
            target_gender = "male"

        partner_id = None

        if target_gender == "female":
            if waiting_female:
                partner_id = waiting_female.pop(0)
        elif target_gender == "male":
            if waiting_male:
                partner_id = waiting_male.pop(0)
        else:
            all_waiting = waiting_male + waiting_female + waiting_queue
            if all_waiting:
                partner_id = all_waiting.pop(0)

        if partner_id:
            if partner_id in waiting_male:
                waiting_male.remove(partner_id)
            if partner_id in waiting_female:
                waiting_female.remove(partner_id)
            if partner_id in waiting_queue:
                waiting_queue.remove(partner_id)

            searching_users.discard(partner_id)
            searching_users.discard(user_id)
            active_chats[user_id] = partner_id
            active_chats[partner_id] = user_id
            chat_history[user_id] = []
            chat_history[partner_id] = []
            text_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
            await update.message.reply_text(text_msg, reply_markup=chat_keyboard())
            await context.bot.send_message(partner_id, text_msg, reply_markup=chat_keyboard())
            await notify_moderator(context, user_id, partner_id, "🟢 Диалог начался")
        else:
            if target_gender == "female":
                waiting_female.append(user_id)
            elif target_gender == "male":
                waiting_male.append(user_id)
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
                pending_reports[f"{user_id}_{partner_id}"] = {"messages": combined[-20:], "user1": user_id, "user2": partner_id}
            chat_history.pop(user_id, None)
            chat_history.pop(partner_id, None)

            kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
            await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
            await context.bot.send_message(partner_id, "/search — начать поиск собеседника", reply_markup=kb)

            await update.message.reply_text("🤖 Диалог остановлен", reply_markup=report_keyboard())
            kb2 = premium_keyboard() if has_premium(user_id) else main_keyboard()
            await update.message.reply_text("/search — начать поиск собеседника", reply_markup=kb2)

            await notify_moderator(context, user_id, partner_id, "🔴 Диалог завершён")
        else:
            if user_id in searching_users:
                searching_users.discard(user_id)
                if user_id in waiting_queue: waiting_queue.remove(user_id)
                if user_id in waiting_male: waiting_male.remove(user_id)
                if user_id in waiting_female: waiting_female.remove(user_id)
            kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
            await update.message.reply_text("🤖 Поиск остановлен\n/search — начать поиск собеседника", reply_markup=kb)
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
                pending_reports[f"{user_id}_{partner_id}"] = {"messages": combined[-20:], "user1": user_id, "user2": partner_id}
            chat_history.pop(user_id, None)
            chat_history.pop(partner_id, None)

            kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
            await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
            await context.bot.send_message(partner_id, "/search — начать поиск собеседника", reply_markup=kb)

            await update.message.reply_text("🤖 Собеседник завершил связь", reply_markup=report_keyboard())
            await notify_moderator(context, user_id, partner_id, "🔴 Диалог завершён")
        if user_id in waiting_queue: waiting_queue.remove(user_id)
        if user_id in waiting_male: waiting_male.remove(user_id)
        if user_id in waiting_female: waiting_female.remove(user_id)
        searching_users.add(user_id)
        waiting_queue.append(user_id)
        await update.message.reply_text("🔍 Ищем собеседника...\n🤖 /stop — остановить поиск")
        return

    if user_id not in active_chats:
        kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await update.message.reply_text("🤖 Вы ни с кем не общаетесь\n/search — начать поиск собеседника", reply_markup=kb)
        return

    partner_id = active_chats[user_id]

    # Засчитываем реферала
    count_referral(user_id)

    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append(f"<code>{user_id}</code>: {update.message.text or '[медиа]'}")

    await notify_moderator(context, user_id, partner_id, update.message.text or None)

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
                f"🚩 <b>Жалоба на пользователя</b> <a href='tg://user?id={other_user}'>{other_user}</a>\n\n"
                f"<b>Диалог:</b>\n{msgs}\n\nВыберите действие:",
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
        await query.edit_message_text(f"⛔ Пользователь <a href='tg://user?id={target_id}'>{target_id}</a> забанен ({reason_text}).", parse_mode="HTML")
        try:
            await context.bot.send_message(target_id, f"🚫 Вы заблокированы ({reason_text}) за нарушение правил.")
        except:
            pass
        partner_id = active_chats.pop(target_id, None)
        if partner_id:
            active_chats.pop(partner_id, None)
            kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
            await context.bot.send_message(partner_id, "🤖 Собеседник отключён.", reply_markup=kb)
        if target_id in waiting_queue: waiting_queue.remove(target_id)
        if target_id in waiting_male: waiting_male.remove(target_id)
        if target_id in waiting_female: waiting_female.remove(target_id)
        searching_users.discard(target_id)

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /ban [user_id] [срок]\nПримеры: 1d, 7d, 30d, 1y, forever")
        return
    try:
        target = int(context.args[0])
    except:
        await update.message.reply_text("Неверный ID.")
        return
    duration = context.args[1].lower()
    if duration in ["forever", "0"]:
        days = None
        reason_text = "навсегда"
    elif duration.endswith("d"):
        days = int(duration[:-1])
        reason_text = f"на {days} дн."
    elif duration.endswith("y"):
        days = int(duration[:-1]) * 365
        reason_text = f"на {int(duration[:-1])} год/лет"
    else:
        await update.message.reply_text("Неверный формат.")
        return
    ban_user(target, "Бан от администратора", days)
    await update.message.reply_text(f"⛔ Пользователь <a href='tg://user?id={target}'>{target}</a> забанен ({reason_text}).", parse_mode="HTML")
    try:
        await context.bot.send_message(target, f"🚫 Вы заблокированы ({reason_text}) администратором.")
    except:
        pass
    partner_id = active_chats.pop(target, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
        await context.bot.send_message(partner_id, "🤖 Собеседник отключён.", reply_markup=kb)
    if target in waiting_queue: waiting_queue.remove(target)
    if target in waiting_male: waiting_male.remove(target)
    if target in waiting_female: waiting_female.remove(target)
    searching_users.discard(target)

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
        text += f"<a href='tg://user?id={uid}'>{uid}</a> — {reason} — {until}\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return
    if user_id in active_chats:
        await update.message.reply_text("🤖 Вы уже в диалоге.", reply_markup=chat_keyboard())
        return
    if user_id in searching_users:
        await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
        return
    if user_id in waiting_queue: waiting_queue.remove(user_id)
    if user_id in waiting_male: waiting_male.remove(user_id)
    if user_id in waiting_female: waiting_female.remove(user_id)
    searching_users.add(user_id)
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
            pending_reports[f"{user_id}_{partner_id}"] = {"messages": combined[-20:], "user1": user_id, "user2": partner_id}
        chat_history.pop(user_id, None)
        chat_history.pop(partner_id, None)
        kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
        await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
        await context.bot.send_message(partner_id, "/search — начать поиск собеседника", reply_markup=kb)
        await update.message.reply_text("🤖 Собеседник завершил связь", reply_markup=report_keyboard())
        await notify_moderator(context, user_id, partner_id, "🔴 Диалог завершён")
    if user_id in waiting_queue: waiting_queue.remove(user_id)
    if user_id in waiting_male: waiting_male.remove(user_id)
    if user_id in waiting_female: waiting_female.remove(user_id)
    searching_users.add(user_id)
    waiting_queue.append(user_id)
    await update.message.reply_text("🔍 Ищем собеседника...\n🤖 /stop — остановить поиск")

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = active_chats.pop(user_id, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        if user_id in chat_history and partner_id in chat_history:
            combined = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
            pending_reports[f"{user_id}_{partner_id}"] = {"messages": combined[-20:], "user1": user_id, "user2": partner_id}
        chat_history.pop(user_id, None)
        chat_history.pop(partner_id, None)
        kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
        await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
        await context.bot.send_message(partner_id, "/search — начать поиск собеседника", reply_markup=kb)
        kb2 = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await update.message.reply_text("🤖 Диалог остановлен", reply_markup=report_keyboard())
        await update.message.reply_text("/search — начать поиск собеседника", reply_markup=kb2)
        await notify_moderator(context, user_id, partner_id, "🔴 Диалог завершён")
    elif user_id in searching_users:
        searching_users.discard(user_id)
        if user_id in waiting_queue: waiting_queue.remove(user_id)
        if user_id in waiting_male: waiting_male.remove(user_id)
        if user_id in waiting_female: waiting_female.remove(user_id)
        kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await update.message.reply_text("🤖 Поиск остановлен\n/search — начать поиск собеседника", reply_markup=kb)
    else:
        kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await update.message.reply_text("🤖 Вы ни с кем не общаетесь\n/search — начать поиск собеседника", reply_markup=kb)

def main():
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={CHOOSING_GENDER: [CallbackQueryHandler(gender_callback, pattern="^gender_")]},
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("ref", ref_cmd))
    app.add_handler(CommandHandler("prem", prem_cmd))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("next", next_chat))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("banlist", banlist_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler, pattern="^(report|ban_).*"))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE |
        filters.Sticker.ALL | filters.Document.ALL | filters.VIDEO_NOTE |
        filters.ANIMATION, handle_message
    ))

    print("Основной бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
