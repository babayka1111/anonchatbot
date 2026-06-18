async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    banned, reason = is_banned(user_id)
    if banned:
        await update.message.reply_text(f"🚫 Вы заблокированы ({reason}).")
        return

    # Проверяем выбран ли пол
    gender = get_gender(user_id)
    if gender is None:
        await update.message.reply_text(
            "⚠️ Сначала выбери свой пол с помощью /start",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🙎‍♂️ Я парень", callback_data="gender_male"),
                InlineKeyboardButton("🙎‍♀️ Я девушка", callback_data="gender_female")
            ]])
        )
        return

    text = update.message.text

    if text in ["🔀 Случайный", "🙎‍♀️ Девушку", "🙎‍♂️ Парня"]:
        if user_id in active_chats:
            await update.message.reply_text("🤖 Вы уже в диалоге.\n/stop — остановить диалог", reply_markup=chat_keyboard())
            return
        if user_id in searching_users:
            await update.message.reply_text("🤖 Вы уже ищете собеседника\n/stop — остановить поиск")
            return

        if user_id in waiting_queue: waiting_queue.remove(user_id)
        if user_id in waiting_male: waiting_male.remove(user_id)
        if user_id in waiting_female: waiting_female.remove(user_id)

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
            if partner_id in waiting_male: waiting_male.remove(partner_id)
            if partner_id in waiting_female: waiting_female.remove(partner_id)
            if partner_id in waiting_queue: waiting_queue.remove(partner_id)

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
