# -*- coding: utf-8 -*-
import os
import re
import threading
import logging
from collections import defaultdict

from flask import Flask
from telegram.ext import Updater, MessageHandler, Filters
from telegram import ChatPermissions

# ------------------------- Конфіг -------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN or not BOT_TOKEN.strip():
    raise RuntimeError("BOT_TOKEN не заданий у змінних середовища")

BAD_WORDS = [
    "хуй","пизда","єбать","єбуч","нахуй","гандон","залупа","блядь","сука","шалава","чмо","мразь","гнида",
    "fuck","shit","bitch","asshole","faggot","dick","pussy","nigger","retard",
    "хер","даун","ублюдок","педик","петух","долбоеб","мудак","ганджа","маріхуана","травка"
]
BANNED_TOPICS = [
    "війна","військо","політика","путін","зеленський",
    "бомба","мобілізація","вторгнення","рашка","кацапи","агресія",
    "нацист","расизм","тероризм","смерть","вбивство","стрілянина"
]
URL_PATTERN = re.compile(r"(https?://|www\.|[a-zA-Z0-9-]+\.(com|net|ua|org|ru|by|kz|pl|info|biz|io|gg|me|ly|t\.me))")

MAX_WARNINGS = 2
violations = defaultdict(int)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("moderator")

# ------------------------- Логіка -------------------------

def is_admin(bot, chat_id: int, user_id: int) -> bool:
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        log.warning(f"get_chat_member error: {e}")
        return False

def moderate(update, context):
    if not update.message or not update.message.from_user or not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user
    text = update.message.text.lower()

    # обмеження чатів (опційно)
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        return

    has_violation = False
    if any(w in text for w in BAD_WORDS) or any(t in text for t in BANNED_TOPICS):
        has_violation = True
    if URL_PATTERN.search(text):
        has_violation = True

    if not has_violation:
        return

    # видаляємо повідомлення
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    except Exception as e:
        log.warning(f"delete_message error: {e}")

    key = (chat_id, user.id)
    violations[key] += 1
    count = violations[key]

    # адмінів не банимо
    if is_admin(context.bot, chat_id, user.id):
        try:
            context.bot.send_message(chat_id=chat_id,
                                     text=f"⚠️ Порушення від адміністратора {user.full_name}. "
                                          f"Бот не має права банити адмінів.")
        except Exception as e:
            log.warning(f"send_message(admin notice) error: {e}")
        return

    if count >= MAX_WARNINGS:
        try:
            context.bot.kick_chat_member(chat_id=chat_id, user_id=user.id)
            context.bot.send_message(chat_id=chat_id,
                                     text=f"⛔ Користувач {user.full_name} забанений за порушення правил.")
        except Exception as e:
            log.warning(f"kick_chat_member error: {e}")
    else:
        try:
            context.bot.send_message(chat_id=chat_id,
                                     text=f"⚠️ Попередження {user.full_name}: порушення правил "
                                          f"({count}/{MAX_WARNINGS})")
        except Exception as e:
            log.warning(f"send_message(warn) error: {e}")

# ------------------------- Health-check (Flask) -------------------------

app = Flask(__name__)

@app.get("/")
def ok():
    return "OK", 200

def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    log.info(f"🌐 Health server on port {port}")
    # debug=False (за замовчуванням), щоб не плодити додаткові потоки
    app.run(host="0.0.0.0", port=port)

# ------------------------- Запуск -------------------------

if __name__ == "__main__":
    # 1) запускаємо Flask у фоні
    threading.Thread(target=run_health_server, daemon=True).start()

    # 2) бот у головному потоці (щоб працювали сигнали всередині idle)
    updater = Updater(BOT_TOKEN, use_context=True)

    # чистимо можливий webhook та підвішені апдейти, щоб не було Conflict
    try:
        updater.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning(f"delete_webhook error: {e}")

    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, moderate))

    log.info("✅ Telegram-бот запущено (polling)…")
    # старт без deprecated параметра
    updater.start_polling(drop_pending_updates=True)
    updater.idle()
