from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes, PreCheckoutQueryHandler
import sqlite3
from datetime import datetime, timedelta
import os
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import random
import asyncio

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 7421345767
PORT = int(os.environ.get("PORT", 10000))
CHOOSING_GENDER = 0
REFERRALS_NEEDED = 5

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

waiting_users = {}
active_chats = {}
chat_history = {}
pending_reports = {}
expired_notified = set()
message_map = {}

PREMIUM_PRICES = {
    "1day": {"stars": 15, "days": 1, "title": "1 день"},
    "7days": {"stars": 50, "days": 7, "title": "7 дней"},
    "30days": {"stars": 200, "days": 30, "title": "30 дней"},
}

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

def reset_referrals(user_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE referrals SET counted = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def count_referral(referral_id: int, context=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE referrals SET counted = 1 WHERE referral_id = ? AND counted = 0", (referral_id,))
    c.execute("SELECT user_id FROM referrals WHERE referral_id = ?", (referral_id,))
    row = c.fetchone()
    conn.commit()
    conn.close()
    if row:
        check_premium(row[0], context)
        if context:
            try:
                context.bot.send_message(
                    row[0],
                    f"🎉 Ваш реферал начал общаться! ({get_referral_count(row[0])}/{REFERRALS_NEEDED})"
                )
            except:
                pass

def check_premium(user_id: int, context=None):
    count = get_referral_count(user_id)
    if count >= REFERRALS_NEEDED:
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("SELECT premium_until FROM premium WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        now = datetime.now()
        
        if row and datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") > now:
            current_until = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            new_until = current_until + timedelta(days=7)
            was_active = True
        else:
            new_until = now + timedelta(days=7)
            was_active = False
        
        premium_until = new_until.strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT OR REPLACE INTO premium VALUES (?, ?, ?)", 
                  (user_id, premium_until, now.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        
        reset_referrals(user_id)
        expired_notified.discard(user_id)
        
        if context:
            try:
                if was_active:
                    context.bot.send_message(
                        user_id,
                        "🎉 5 рефералов! Ваш Premium продлён на 7 дней!\nСчётчик рефералов сброшен. Пригласите ещё 5 чтобы продлить снова."
                    )
                else:
                    context.bot.send_message(
                        user_id,
                        "🎉 Поздравляем! Вы получили Premium на 7 дней!\nНапишите /start для обновления клавиатуры"
                    )
            except:
                pass
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

def get_premium_info(user_id: int, context=None):
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
        reset_referrals(user_id)
        if user_id not in expired_notified and context:
            expired_notified.add(user_id)
            try:
                context.bot.send_message(
                    user_id,
                    "⏰ Ваш Premium истёк. Счётчик рефералов сброшен.\nПригласите 5 друзей чтобы получить Premium снова!"
                )
            except:
                pass
        return None
    remaining = until - now
    passed = now - activated
    return remaining, passed

def give_premium(user_id: int, days: int = 7):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT premium_until FROM premium WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    now = datetime.now()
    
    if row and datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") > now:
        current_until = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        new_until = current_until + timedelta(days=days)
        was_active = True
    else:
        new_until = now + timedelta(days=days)
        was_active = False
    
    premium_until = new_until.strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR REPLACE INTO premium VALUES (?, ?, ?)", 
              (user_id, premium_until, now.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    expired_notified.discard(user_id)
    return was_active

def take_premium(user_id: int):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM premium WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def find_partner(user_id: int, target_gender: str | None, my_gender: str | None = None):
    candidates = []
    for uid, data in waiting_users.items():
        if uid == user_id:
            continue
        if target_gender:
            if data["gender"] == target_gender:
                candidates.append(uid)
        else:
            if data["target"] is None:
                candidates.append(uid)
            else:
                if my_gender and data["target"] == my_gender:
                    candidates.append(uid)
    if candidates:
        partner_id = random.choice(candidates)
        return partner_id
    return None

async def post_init(application: Application):
    await application.bot.set_my_commands([
        ("start", "Главное меню"),
        ("search", "Поиск собеседника"),
        ("next", "Сменить собеседника"),
        ("stop", "Остановить диалог / поиск"),
        ("ref", "Реферальная система"),
        ("prem", "Premium-подписка"),
        ("settings", "Изменить параметры"),
    ])
    init_db()

def main_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🔀 Случайный")]], resize_keyboard=True)

def premium_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🙎‍♀️"), KeyboardButton("🔀 Случайный"), KeyboardButton("🙎‍♂️")]
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

def admin_ban_keyboard(user_id: int, report_id: str = ""):
    keyboard = [
        [InlineKeyboardButton("⛔ Бан на 1 день", callback_data=f"ban_{user_id}_1")],
        [InlineKeyboardButton("⛔ Бан на 7 дней", callback_data=f"ban_{user_id}_7")],
        [InlineKeyboardButton("⛔ Бан на 30 дней", callback_data=f"ban_{user_id}_30")],
        [InlineKeyboardButton("♾ Вечный бан", callback_data=f"ban_{user_id}_0")],
        [InlineKeyboardButton("✅ Отклонить", callback_data=f"ban_{user_id}_no")],
    ]
    if report_id:
        keyboard.append([InlineKeyboardButton("📋 Весь диалог", callback_data=f"fulldialog_{report_id}")])
    return InlineKeyboardMarkup(keyboard)

def premium_menu_keyboard():
    keyboard = []
    for key, data in PREMIUM_PRICES.items():
        keyboard.append([InlineKeyboardButton(
            f"⭐ {data['stars']} — {data['title']}",
            callback_data=f"buy_{key}"
        )])
    return InlineKeyboardMarkup(keyboard)

async def cancel_gender_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("Выбор пола отменён.")
    
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
        "/prem — Premium-подписка\n"
        "/settings — изменить параметры\n\n"
        "После каждого диалога вы можете пожаловаться на собеседника",
        reply_markup=kb
    )
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return ConversationHandler.END

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
            "👋 Привет! Это анонимный чат.\nОбщайся вежливо, соблюдай правила поведения.\n\nДля начала выбери свой пол:",
            reply_markup=gender_keyboard()
        )
        return CHOOSING_GENDER

    if user_id in active_chats:
        await update.message.reply_text("🤖 Вы уже в диалоге.\n/stop — остановить диалог", reply_markup=chat_keyboard())
        return ConversationHandler.END

    if user_id in waiting_users:
        await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
        return ConversationHandler.END

    if not has_premium(user_id):
        get_premium_info(user_id, context)

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
        "/prem — Premium-подписка\n"
        "/settings — изменить параметры\n\n"
        "После каждого диалога вы можете пожаловаться на собеседника",
        reply_markup=kb
    )
    return ConversationHandler.END

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выбери свой пол:", reply_markup=gender_keyboard())
    return CHOOSING_GENDER

async def gender_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    gender = "male" if query.data == "gender_male" else "female"
    set_gender(user_id, gender)
    kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
    await query.edit_message_text("✅ Пол сохранён!")
    await query.message.reply_text(
        "👋 Привет! Это анонимный чат.\n"
        "Общайся вежливо, соблюдай правила поведения.\n\n"
        "Нажми кнопку ниже, чтобы начать поиск случайного собеседника.\n\n"
        "/start — перезапуск бота\n"
        "/search — поиск собеседника\n"
        "/next — переключить собеседника\n"
        "/stop — завершить диалог\n"
        "/ref — реферальная система\n"
        "/prem — Premium-подписка\n"
        "/settings — изменить параметры\n\n"
        "После каждого диалога вы можете пожаловаться на собеседника",
        reply_markup=kb
    )
    return ConversationHandler.END

async def ref_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = get_ref_code(user_id)
    link = f"https://t.me/{(await context.bot.get_me()).username}?start={code}"
    count = get_referral_count(user_id)
    has_prem = has_premium(user_id)
    prem_info = get_premium_info(user_id, context)
    text = (
        "🔗 <b>Реферальная система</b>\n\n"
        f"✅ Пригласи {REFERRALS_NEEDED} друзей, которые <b>реально пообщаются</b> в боте, "
        "и получи доступ к <b>поиску по полу на 7 дней</b>!\n\n"
        f"🔗 Твоя ссылка:\n<code>{link}</code>\n"
        f"📊 Приглашено: {count}/{REFERRALS_NEEDED}\n"
    )
    if has_prem and prem_info:
        remaining, passed = prem_info
        text += (
            f"\n✅ <b>Подписка активна!</b>\n"
            f"⏳ Осталось: {remaining.days} дн. {remaining.seconds // 3600} ч.\n"
            f"🕐 Прошло: {passed.days} дн. {passed.seconds // 3600} ч."
        )
    await update.message.reply_text(text, parse_mode="HTML")

async def prem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prem_info = get_premium_info(user_id, context)
    count = get_referral_count(user_id)
    has_prem = has_premium(user_id)
    
    if has_prem and prem_info:
        remaining, passed = prem_info
        text = (
            "💎 <b>Premium-подписка</b>\n\n"
            f"✅ <b>Подписка активна!</b>\n"
            f"⏳ Осталось: {remaining.days} дн. {remaining.seconds // 3600} ч.\n"
            f"🕐 Прошло: {passed.days} дн. {passed.seconds // 3600} ч.\n\n"
            "<b>Продлить Premium:</b>"
        )
    else:
        text = (
            "💎 <b>Premium-подписка</b>\n\n"
            "С Premium вы можете искать собеседника по полу!\n\n"
            "<b>Купить Premium:</b>"
        )
    
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=premium_menu_keyboard())
    
    ref_text = (
        f"🆓 <b>Бесплатно:</b>\n"
        f"Пригласите {REFERRALS_NEEDED} друзей через /ref и получите 7 дней Premium\n"
        f"📊 Ваш прогресс: {count}/{REFERRALS_NEEDED}"
    )
    await update.message.reply_text(ref_text, parse_mode="HTML")

async def giveprem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("/giveprem [user_id] [дни]\nПример: /giveprem 123456 7")
        return
    try:
        target = int(context.args[0])
    except:
        await update.message.reply_text("Неверный ID.")
        return
    days = int(context.args[1]) if len(context.args) > 1 else 7
    was_active = give_premium(target, days)
    await update.message.reply_text(f"✅ Premium выдан пользователю <code>{target}</code> на {days} дн.", parse_mode="HTML")
    try:
        if was_active:
            await context.bot.send_message(target, f"🎉 Администратор продлил ваш Premium на {days} дн.\nНапишите /start для обновления клавиатуры")
        else:
            await context.bot.send_message(target, f"🎉 Администратор выдал вам Premium на {days} дн.\nНапишите /start для обновления клавиатуры")
    except:
        pass

async def takeprem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("/takeprem [user_id]")
        return
    try:
        target = int(context.args[0])
    except:
        await update.message.reply_text("Неверный ID.")
        return
    take_premium(target)
    await update.message.reply_text(f"❌ Premium забран у пользователя <code>{target}</code>.", parse_mode="HTML")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM genders")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM premium WHERE premium_until > ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
    premium_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM bans WHERE banned_until = 'forever' OR banned_until > ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
    banned_count = c.fetchone()[0]
    
    conn.close()
    
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💎 Premium-пользователей: {premium_users}\n"
        f"🔍 В поиске сейчас: {len(waiting_users)}\n"
        f"💬 В диалоге сейчас: {len(active_chats) // 2}\n"
        f"🚫 Забанено: {banned_count}"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /broadcast [текст сообщения]")
        return
    
    text = " ".join(context.args)
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM genders")
    users = c.fetchall()
    conn.close()
    
    sent = 0
    failed = 0
    
    await update.message.reply_text(f"📢 Начинаю рассылку на {len(users)} пользователей...")
    
    for (user_id,) in users:
        try:
            await context.bot.send_message(user_id, f"📢 {text}")
            sent += 1
            await asyncio.sleep(0.3)
        except:
            failed += 1
    
    await update.message.reply_text(f"✅ Рассылка завершена.\nОтправлено: {sent}\nНе доставлено: {failed}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return

    text = update.message.text

    if text in ["🔀 Случайный", "🙎‍♀️", "🙎‍♂️"]:
        gender = get_gender(user_id)
        if gender is None:
            await update.message.reply_text(
                "⚠️ Сначала выбери свой пол:",
                reply_markup=gender_keyboard()
            )
            return

        if not has_premium(user_id):
            get_premium_info(user_id, context)

        if user_id in active_chats:
            await update.message.reply_text("🤖 Вы уже в диалоге.\n/stop — остановить диалог", reply_markup=chat_keyboard())
            return
        if user_id in waiting_users:
            await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
            return

        target_gender = None
        if text == "🙎‍♀️":
            target_gender = "female"
        elif text == "🙎‍♂️":
            target_gender = "male"

        partner_id = find_partner(user_id, target_gender, gender)
        partner_target = None
        if partner_id and partner_id in waiting_users:
            partner_target = waiting_users[partner_id].get("target")
            del waiting_users[partner_id]

        if partner_id:
            active_chats[user_id] = partner_id
            active_chats[partner_id] = user_id
            chat_history[user_id] = []
            chat_history[partner_id] = []

            if target_gender == "female":
                my_msg = "🔎🤖 Найдена девушка!\n\nПриятного общения!\n/stop — остановить диалог"
            elif target_gender == "male":
                my_msg = "🔎🤖 Найден парень!\n\nПриятного общения!\n/stop — остановить диалог"
            else:
                my_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"

            if partner_target == "female":
                partner_msg = "🔎🤖 Найдена девушка!\n\nПриятного общения!\n/stop — остановить диалог"
            elif partner_target == "male":
                partner_msg = "🔎🤖 Найден парень!\n\nПриятного общения!\n/stop — остановить диалог"
            else:
                partner_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"

            await update.message.reply_text(my_msg, reply_markup=chat_keyboard())
            await context.bot.send_message(partner_id, partner_msg, reply_markup=chat_keyboard())
        else:
            waiting_users[user_id] = {"gender": gender, "target": target_gender}
            if target_gender:
                search_text = "девушку" if target_gender == "female" else "парня"
                await update.message.reply_text(f"🔍 Ищем {search_text}...\n🤖 /stop — остановить поиск")
            else:
                await update.message.reply_text("🔍 Поиск собеседника...\n🤖 /stop — остановить поиск")
        return

    if text == "⏹ Стоп":
        partner_id = active_chats.pop(user_id, None)
        if partner_id:
            active_chats.pop(partner_id, None)
            if user_id in chat_history and partner_id in chat_history:
                combined_raw = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
                combined_raw.sort(key=lambda x: x[0])
                combined = [msg for _, msg in combined_raw]
                pending_reports[f"{user_id}_{partner_id}"] = {"messages": combined, "user1": user_id, "user2": partner_id}
            chat_history.pop(user_id, None)
            chat_history.pop(partner_id, None)
            kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
            await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
            await context.bot.send_message(partner_id, "/search — начать поиск собеседника", reply_markup=kb)
            await update.message.reply_text("🤖 Диалог остановлен", reply_markup=report_keyboard())
            kb2 = premium_keyboard() if has_premium(user_id) else main_keyboard()
            await update.message.reply_text("/search — начать поиск собеседника", reply_markup=kb2)
        else:
            if user_id in waiting_users:
                del waiting_users[user_id]
            kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
            await update.message.reply_text("🤖 Поиск остановлен\n/search — начать поиск собеседника", reply_markup=kb)
        return

    if text == "⏭ Следующий":
        gender = get_gender(user_id)
        if gender is None:
            await update.message.reply_text(
                "⚠️ Сначала выбери свой пол:",
                reply_markup=gender_keyboard()
            )
            return

        if user_id in waiting_users and user_id not in active_chats:
            await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
            return
        
        old_data = waiting_users.get(user_id, {})
        old_target = old_data.get("target") if isinstance(old_data, dict) else None
        
        partner_id = active_chats.pop(user_id, None)
        if partner_id:
            active_chats.pop(partner_id, None)
            if user_id in chat_history and partner_id in chat_history:
                combined_raw = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
                combined_raw.sort(key=lambda x: x[0])
                combined = [msg for _, msg in combined_raw]
                pending_reports[f"{user_id}_{partner_id}"] = {"messages": combined, "user1": user_id, "user2": partner_id}
            chat_history.pop(user_id, None)
            chat_history.pop(partner_id, None)
            kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
            await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
            await context.bot.send_message(partner_id, "/search — начать поиск собеседника", reply_markup=kb)
            await update.message.reply_text("🤖 Собеседник завершил связь", reply_markup=report_keyboard())
        
        partner_id = find_partner(user_id, old_target, gender)
        partner_target = None
        if partner_id and partner_id in waiting_users:
            partner_target = waiting_users[partner_id].get("target")
            del waiting_users[partner_id]
        
        if partner_id:
            active_chats[user_id] = partner_id
            active_chats[partner_id] = user_id
            chat_history[user_id] = []
            chat_history[partner_id] = []
            
            if old_target == "female":
                my_msg = "🔎🤖 Найдена девушка!\n\nПриятного общения!\n/stop — остановить диалог"
            elif old_target == "male":
                my_msg = "🔎🤖 Найден парень!\n\nПриятного общения!\n/stop — остановить диалог"
            else:
                my_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
            
            if partner_target == "female":
                partner_msg = "🔎🤖 Найдена девушка!\n\nПриятного общения!\n/stop — остановить диалог"
            elif partner_target == "male":
                partner_msg = "🔎🤖 Найден парень!\n\nПриятного общения!\n/stop — остановить диалог"
            else:
                partner_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
            
            await update.message.reply_text(my_msg, reply_markup=chat_keyboard())
            await context.bot.send_message(partner_id, partner_msg, reply_markup=chat_keyboard())
        else:
            waiting_users[user_id] = {"gender": gender, "target": old_target}
            if old_target:
                search_text = "девушку" if old_target == "female" else "парня"
                await update.message.reply_text(f"🔍 Ищем {search_text}...\n🤖 /stop — остановить поиск")
            else:
                await update.message.reply_text("🔍 Ищем собеседника...\n🤖 /stop — остановить поиск")
        return

    if user_id not in active_chats:
        kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await update.message.reply_text("🤖 Вы ни с кем не общаетесь\n/search — начать поиск собеседника", reply_markup=kb)
        return

    partner_id = active_chats[user_id]
    count_referral(user_id, context)

    if user_id not in chat_history:
        chat_history[user_id] = []

    # Сохраняем в историю с временной меткой
    timestamp = datetime.now().strftime("%H:%M:%S")
    if update.message.sticker:
        chat_history[user_id].append((timestamp, f"<code>{user_id}</code>: [стикер]"))
    elif update.message.photo:
        chat_history[user_id].append((timestamp, f"<code>{user_id}</code>: [фото]"))
    elif update.message.video:
        chat_history[user_id].append((timestamp, f"<code>{user_id}</code>: [видео]"))
    elif update.message.voice:
        chat_history[user_id].append((timestamp, f"<code>{user_id}</code>: [голосовое]"))
    elif update.message.video_note:
        chat_history[user_id].append((timestamp, f"<code>{user_id}</code>: [кружок]"))
    elif update.message.document:
        chat_history[user_id].append((timestamp, f"<code>{user_id}</code>: [документ]"))
    elif update.message.animation:
        chat_history[user_id].append((timestamp, f"<code>{user_id}</code>: [гифка]"))
    elif update.message.text:
        chat_history[user_id].append((timestamp, f"<code>{user_id}</code>: {update.message.text}"))

    # Определяем ID сообщения для reply
    reply_to_message_id = None
    if update.message.reply_to_message:
        # Ищем в мапе сообщение партнёра, соответствующее цитируемому сообщению
        # Ключ: (отправитель_цитируемого, message_id_цитируемого)
        # Мы ищем: message_map[(user_id, цитируемый_message_id)] -> message_id_у_партнёра
        reply_to_message_id = message_map.get((user_id, update.message.reply_to_message.message_id))

    # Отправляем сообщение партнёру
    sent_msg = None
    if update.message.sticker:
        sent_msg = await context.bot.send_sticker(partner_id, update.message.sticker.file_id, reply_to_message_id=reply_to_message_id)
    elif update.message.photo:
        sent_msg = await context.bot.send_photo(partner_id, update.message.photo[-1].file_id, caption=update.message.caption, reply_to_message_id=reply_to_message_id)
    elif update.message.video:
        sent_msg = await context.bot.send_video(partner_id, update.message.video.file_id, caption=update.message.caption, reply_to_message_id=reply_to_message_id)
    elif update.message.voice:
        sent_msg = await context.bot.send_voice(partner_id, update.message.voice.file_id, reply_to_message_id=reply_to_message_id)
    elif update.message.video_note:
        sent_msg = await context.bot.send_video_note(partner_id, update.message.video_note.file_id, reply_to_message_id=reply_to_message_id)
    elif update.message.document:
        sent_msg = await context.bot.send_document(partner_id, update.message.document.file_id, caption=update.message.caption, reply_to_message_id=reply_to_message_id)
    elif update.message.animation:
        sent_msg = await context.bot.send_animation(partner_id, update.message.animation.file_id, caption=update.message.caption, reply_to_message_id=reply_to_message_id)
    elif update.message.text:
        sent_msg = await context.bot.send_message(partner_id, update.message.text, reply_to_message_id=reply_to_message_id)

    # Сохраняем связку: (отправитель, message_id_отправителя) -> message_id_получателя
    # Это нужно чтобы когда отправитель ответит на своё же сообщение, мы знали какой message_id у партнёра
    if sent_msg:
        message_map[(user_id, update.message.message_id)] = sent_msg.message_id

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("buy_"):
        key = data.replace("buy_", "")
        if key in PREMIUM_PRICES:
            price_data = PREMIUM_PRICES[key]
            await context.bot.send_invoice(
                chat_id=user_id,
                title="Premium-подписка",
                description=f"Доступ к поиску по полу на {price_data['title']}",
                payload=f"premium_{key}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(f"Premium {price_data['title']}", price_data['stars'])],
                start_parameter="premium"
            )
        return

    if data.startswith("fulldialog_"):
        if user_id != ADMIN_ID:
            await query.edit_message_text("⛔ Только администратор может это делать.")
            return
        report_id = data.replace("fulldialog_", "")
        if report_id in pending_reports:
            info = pending_reports[report_id]
            msgs = info["messages"]
            text = f"📋 <b>Полный диалог:</b>\n\n"
            full_text = text + "\n".join(msgs) if msgs else text + "Нет сообщений"
            if len(full_text) > 4000:
                for i in range(0, len(full_text), 4000):
                    await context.bot.send_message(ADMIN_ID, full_text[i:i+4000], parse_mode="HTML")
            else:
                await context.bot.send_message(ADMIN_ID, full_text, parse_mode="HTML")
            await query.edit_message_text("✅ Полный диалог отправлен.")
        else:
            await query.edit_message_text("⚠️ Диалог уже не доступен.")
        return

    if data in ["gender_male", "gender_female"]:
        gender = "male" if data == "gender_male" else "female"
        set_gender(user_id, gender)
        kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await query.edit_message_text("✅ Пол сохранён!")
        await query.message.reply_text(
            "👋 Привет! Это анонимный чат.\n"
            "Общайся вежливо, соблюдай правила поведения.\n\n"
            "Нажми кнопку ниже, чтобы начать поиск случайного собеседника.\n\n"
            "/start — перезапуск бота\n"
            "/search — поиск собеседника\n"
            "/next — переключить собеседника\n"
            "/stop — завершить диалог\n"
            "/ref — реферальная система\n"
            "/prem — Premium-подписка\n"
            "/settings — изменить параметры\n\n"
            "После каждого диалога вы можете пожаловаться на собеседника",
            reply_markup=kb
        )
        return

    if data == "report":
        found = None
        for rid, info in pending_reports.items():
            if user_id == info["user1"] or user_id == info["user2"]:
                found = rid
                break
        if found:
            info = pending_reports[found]
            other_user = info["user2"] if user_id == info["user1"] else info["user1"]
            msgs = info["messages"]
            msg_text = "\n".join(msgs[-20:]) if msgs else "Нет сообщений"
            await context.bot.send_message(
                ADMIN_ID,
                f"🚩 <b>Жалоба на пользователя</b> <code>{other_user}</code>\n\n"
                f"<b>Диалог (последние 20 сообщений):</b>\n{msg_text}\n\n"
                f"Выберите действие:",
                parse_mode="HTML",
                reply_markup=admin_ban_keyboard(other_user, found)
            )
            await query.edit_message_text("✅ Жалоба отправлена администратору. Спасибо!")
        else:
            await query.edit_message_text("⚠️ Не удалось найти диалог для жалобы.")
        return

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
            kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
            await context.bot.send_message(partner_id, "🤖 Собеседник отключён.", reply_markup=kb)
        if target_id in waiting_users:
            del waiting_users[target_id]
        return

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    
    if payload.startswith("premium_"):
        key = payload.replace("premium_", "")
        if key in PREMIUM_PRICES:
            days = PREMIUM_PRICES[key]["days"]
            was_active = give_premium(user_id, days)
            if was_active:
                await update.message.reply_text(
                    f"✅ Оплата прошла! Premium продлён на {days} дн.\n"
                    "Напишите /start для обновления клавиатуры."
                )
            else:
                await update.message.reply_text(
                    f"✅ Оплата прошла! Premium активен на {PREMIUM_PRICES[key]['title']}.\n"
                    "Напишите /start для обновления клавиатуры."
                )

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
        await update.message.reply_text("Неверный формат. Примеры: 1d, 7d, 30d, 1y, forever")
        return
    ban_user(target, "Бан от администратора", days)
    await update.message.reply_text(f"⛔ Пользователь <code>{target}</code> забанен ({reason_text}).", parse_mode="HTML")
    try:
        await context.bot.send_message(target, f"🚫 Вы заблокированы ({reason_text}) администратором.")
    except:
        pass
    partner_id = active_chats.pop(target, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
        await context.bot.send_message(partner_id, "🤖 Собеседник отключён.", reply_markup=kb)
    if target in waiting_users:
        del waiting_users[target]

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
        try:
            await context.bot.send_message(target, "✅ Вы были разблокированы администратором. Можете снова пользоваться ботом.")
        except:
            pass
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
        await update.message.reply_text("🤖 Вы уже в диалоге.", reply_markup=chat_keyboard())
        return
    if user_id in waiting_users:
        await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
        return
    gender = get_gender(user_id)
    if gender is None:
        await update.message.reply_text(
            "⚠️ Сначала выбери свой пол:",
            reply_markup=gender_keyboard()
        )
        return
    if not has_premium(user_id):
        get_premium_info(user_id, context)
    partner_id = find_partner(user_id, None, gender)
    if partner_id:
        if partner_id in waiting_users:
            del waiting_users[partner_id]
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        chat_history[user_id] = []
        chat_history[partner_id] = []
        text_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
        await update.message.reply_text(text_msg, reply_markup=chat_keyboard())
        await context.bot.send_message(partner_id, text_msg, reply_markup=chat_keyboard())
    else:
        waiting_users[user_id] = {"gender": gender, "target": None}
        await update.message.reply_text("🔍 Ждём собеседника...\n🤖 /stop — остановить поиск")

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return
    if user_id in waiting_users and user_id not in active_chats:
        await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
        return
    gender = get_gender(user_id)
    if gender is None:
        await update.message.reply_text(
            "⚠️ Сначала выбери свой пол:",
            reply_markup=gender_keyboard()
        )
        return
    partner_id = active_chats.pop(user_id, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        if user_id in chat_history and partner_id in chat_history:
            combined_raw = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
            combined_raw.sort(key=lambda x: x[0])
            combined = [msg for _, msg in combined_raw]
            pending_reports[f"{user_id}_{partner_id}"] = {"messages": combined, "user1": user_id, "user2": partner_id}
        chat_history.pop(user_id, None)
        chat_history.pop(partner_id, None)
        kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
        await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
        await context.bot.send_message(partner_id, "/search — начать поиск собеседника", reply_markup=kb)
        await update.message.reply_text("🤖 Собеседник завершил связь", reply_markup=report_keyboard())
    partner_id = find_partner(user_id, None, gender)
    if partner_id:
        if partner_id in waiting_users:
            del waiting_users[partner_id]
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        chat_history[user_id] = []
        chat_history[partner_id] = []
        text_msg = "🔎🤖 Нашли кое-кого для тебя!\n\nПриятного общения!\n/stop — остановить диалог"
        await update.message.reply_text(text_msg, reply_markup=chat_keyboard())
        await context.bot.send_message(partner_id, text_msg, reply_markup=chat_keyboard())
    else:
        waiting_users[user_id] = {"gender": gender, "target": None}
        await update.message.reply_text("🔍 Ищем собеседника...\n🤖 /stop — остановить поиск")

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = active_chats.pop(user_id, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        if user_id in chat_history and partner_id in chat_history:
            combined_raw = chat_history.get(user_id, []) + chat_history.get(partner_id, [])
            combined_raw.sort(key=lambda x: x[0])
            combined = [msg for _, msg in combined_raw]
            pending_reports[f"{user_id}_{partner_id}"] = {"messages": combined, "user1": user_id, "user2": partner_id}
        chat_history.pop(user_id, None)
        chat_history.pop(partner_id, None)
        kb = premium_keyboard() if has_premium(partner_id) else main_keyboard()
        await context.bot.send_message(partner_id, "🤖 Собеседник завершил связь", reply_markup=report_keyboard())
        await context.bot.send_message(partner_id, "/search — начать поиск собеседника", reply_markup=kb)
        kb2 = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await update.message.reply_text("🤖 Диалог остановлен", reply_markup=report_keyboard())
        await update.message.reply_text("/search — начать поиск собеседника", reply_markup=kb2)
    elif user_id in waiting_users:
        del waiting_users[user_id]
        kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await update.message.reply_text("🤖 Поиск остановлен\n/search — начать поиск собеседника", reply_markup=kb)
    else:
        kb = premium_keyboard() if has_premium(user_id) else main_keyboard()
        await update.message.reply_text("🤖 Вы ни с кем не общаетесь\n/search — начать поиск собеседника", reply_markup=kb)

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    start_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_GENDER: [CallbackQueryHandler(gender_callback, pattern="^gender_")],
        },
        fallbacks=[],
    )

    settings_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("settings", settings_cmd)],
        states={
            CHOOSING_GENDER: [CallbackQueryHandler(gender_callback, pattern="^gender_")],
        },
        fallbacks=[
            CommandHandler("start", cancel_gender_selection),
            CommandHandler("search", cancel_gender_selection),
            CommandHandler("next", cancel_gender_selection),
            CommandHandler("stop", cancel_gender_selection),
            CommandHandler("ref", cancel_gender_selection),
            CommandHandler("prem", cancel_gender_selection),
            CommandHandler("settings", cancel_gender_selection),
            MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_gender_selection),
        ],
    )

    app.add_handler(start_conv_handler)
    app.add_handler(settings_conv_handler)
    app.add_handler(CommandHandler("ref", ref_cmd))
    app.add_handler(CommandHandler("prem", prem_cmd))
    app.add_handler(CommandHandler("giveprem", giveprem_cmd))
    app.add_handler(CommandHandler("takeprem", takeprem_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("next", next_chat))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("banlist", banlist_cmd))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(CallbackQueryHandler(callback_handler, pattern="^(buy_|fulldialog_|report|ban_|gender_).*"))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE |
        filters.Sticker.ALL | filters.Document.ALL | filters.VIDEO_NOTE |
        filters.ANIMATION, handle_message
    ))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
