# -*- coding: utf-8 -*-
import os
import re
import threading
import logging
from collections import defaultdict

from flask import Flask
from telegram.ext import Updater, MessageHandler, Filters
from telegram import ChatPermissions

# ------------------------- Налаштування -------------------------

# Токен беремо з env
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN or not BOT_TOKEN.strip():
    raise RuntimeError("BOT_TOKEN не заданий у змінних середовища")

# Дозволені чати (якщо порожньо — працюємо всюди)
# приклад змінної на Render: ALLOWED_CHAT_IDS=-1002101234567,-1002227654321
_raw = (os.getenv("ALLOWED_CHAT_IDS") or "").replace(" ", "")
ALLOWED_CHAT_IDS = {int(x) for x in _raw.split(",") if x} if _raw else set()

# Список лайки/образи + теми, які чистимо
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

# Повна заборона посилань (включно з t.me, bit.ly, домени тощо)
URL_PATTERN = re.compile(r"(https?://|www\.|[a-zA-Z0-9-]+\.(com|net|ua|org|ru|by|kz|pl|info|biz|io|gg|me|ly|t\.me))")

# Скільки попереджень до бана
MAX_WARNINGS = 2

# Лічильник порушень по зв’язці (chat_id, user_id)
violations = defaultdict(int)

# Логи
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("moderator")

# ------------------------- Логіка модерації -------------------------

def is_admin(bot, chat_id: int, user_id: int) -> bool:
    """Перевірити, чи користувач адміністратор/власник (боти не можуть банити адмінів)."""
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        log.warning(f"get_chat_member error: {e}")
        return False

def moderate(update, context):
    if not update.message or not update.message.from_user:
        return
    if not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user
    user_id = user.id
    text = update.message.text.lower()

    # Якщо задано список чатов — працюємо лише в них
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        return

    has_violation = False
    if any(w in text for w in BAD_WORDS) or any(t in text for t in BANNED_TOPICS):
        has_violation = True
    if URL_PATTERN.search(text):
        has_violation = True

    if not has_violation:
        return

    # Прагнемо видалити порушення
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    except Exception as e:
        log.warning(f"delete_message error: {e}")

    key = (chat_id, user_id)
    violations[key] += 1
    count = violations[key]

    # Якщо порушник — адмін, не банимо, лише повідомляємо
    if is_admin(context.bot, chat_id, user_id):
        try:
            context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Порушення від адміністратора {user.full_name}. Бот не має права банити адмінів."
            )
        except Exception as e:
            log.warning(f"send_message (admin notice) error: {e}")
        return

    # Бан після MAX_WARNINGS
    if count >= MAX_WARNINGS:
        try:
            context.bot.kick_chat_member(chat_id=chat_id, user_id=user_id)
            context.bot.send_message(
                chat_id=chat_id,
                text=f"⛔ Користувач {user.full_name} забанений за порушення правил."
            )
        except Exception as e:
            log.warning(f"kick_chat_member error: {e}")
    else:
        try:
            context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Попередження {user.full_name}: порушення правил ({count}/{MAX_WARNINGS})"
            )
        except Exception as e:
            log.warning(f"send_message (warn) error: {e}")

# ------------------------- Запуск бота + Healthcheck -------------------------

def run_bot():
    updater = Updater(BOT_TOKEN, use_context=True)

    # Прибираємо можливий webhook і старі апдейти (важливо при міграціях/конфліктах)
    try:
        updater.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning(f"delete_webhook error: {e}")

    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, moderate))

    log.info("✅ Telegram-бот запущено (polling)…")
    updater.start_polling(clean=True)
    updater.idle()

# Невеличкий Flask-сервер, щоб Render бачив відкритий порт
app = Flask(__name__)

@app.get("/")
def ok():
    return "OK", 200

if __name__ == "__main__":
    # Стартуємо бота у фоні
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()

    # Слухаємо порт, який Render передає у змінній PORT
    port = int(os.getenv("PORT", "10000"))
    log.info(f"🌐 Health server on port {port}")
    app.run(host="0.0.0.0", port=port)
