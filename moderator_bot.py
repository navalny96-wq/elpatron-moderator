# -*- coding: utf-8 -*-
import os
import re
import logging
from collections import defaultdict
from flask import Flask, request, jsonify

from telegram import Bot, Update
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler
from telegram.error import TelegramError

# ================== НАЛАШТУВАННЯ ==================
BOT_TOKEN = os.getenv("BOT_TOKEN") or "ВСТАВ_СВІЙ_ТОКЕН_ТУТ"
if BOT_TOKEN == "ВСТАВ_СВІЙ_ТОКЕН_ТУТ":
    raise RuntimeError("Задай змінну середовища BOT_TOKEN.")

# Render автоматично підставляє RENDER_EXTERNAL_URL; можна явно задати APP_URL
APP_URL = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL")
if not APP_URL:
    raise RuntimeError("Нема APP_URL/RENDER_EXTERNAL_URL. Додай APP_URL у Render → Environment.")

MAX_WARNINGS = 2

BAD_WORDS = [
    "хуй","пизда","єбать","єбуч","нахуй","гандон","залупа","блядь","сука","шалава","чмо","мразь","гнида",
    "fuck","shit","bitch","asshole","dick","pussy"
]
BANNED_TOPICS = [
    "політика","путін","зеленський","війна","мобілізація","тероризм","насильство"
]

# URL у тексті (навіть без http)
URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)

# Пам’ять попереджень (in-memory)
warnings = defaultdict(int)

# ================== ЛОГУВАННЯ ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("moderator")

# ================== TELEGRAM ==================
bot = Bot(BOT_TOKEN)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# ---- /ping для швидкої перевірки ----
def ping(update, context):
    try:
        context.bot.send_message(update.effective_chat.id, "🏓 Pong!")
    except TelegramError as e:
        log.warning(f"/ping send error: {e}")

# ---- модерація ----
def handle_violation(update, context, reason: str):
    chat_id = update.effective_chat.id
    user = update.message.from_user
    uid = user.id

    # 1) Видаляємо повідомлення
    try:
        update.message.delete()
    except TelegramError as e:
        log.warning(f"delete error: {e}")

    # 2) Рахуємо попередження
    warnings[uid] += 1
    count = warnings[uid]

    # 3) Попередження або бан
    if count < MAX_WARNINGS:
        try:
            context.bot.send_message(chat_id, f"⚠ Попередження {user.first_name or ''}! ({reason}). Наступного разу — бан.")
        except TelegramError as e:
            log.warning(f"warn send error: {e}")
    else:
        try:
            context.bot.ban_chat_member(chat_id, uid)
            context.bot.send_message(chat_id, f"🚫 Користувача {user.first_name or ''} заблоковано ({reason}).")
        except TelegramError as e:
            log.warning(f"ban error: {e}")

def text_filter(update, context):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.lower()
    log.info(f"📩 {msg.from_user.id} @ {msg.chat_id}: {text}")

    # нецензура
    if any(w in text for w in BAD_WORDS):
        handle_violation(update, context, "нецензурна лексика")
        return

    # заборонені теми
    if any(t in text for t in BANNED_TOPICS):
        handle_violation(update, context, "заборонена тема")
        return

    # URL у самому тексті
    if URL_RE.search(text):
        handle_violation(update, context, "посилання")
        return

    # URL як entities (Telegram сам розпізнав)
    if msg.entities:
        for ent in msg.entities:
            if ent.type in ("url", "text_link"):
                handle_violation(update, context, "посилання")
                return

# Реєструємо хендлери
dispatcher.add_handler(CommandHandler("ping", ping))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, text_filter))

# ================== FLASK (webhook) ==================
app = Flask(__name__)

@app.get("/")
def root():
    return "OK", 200

@app.post(f"/{BOT_TOKEN}")
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot)
        dispatcher.process_update(update)
    except Exception as e:
        log.exception(f"update handling error: {e}")
        return jsonify({"ok": False}), 500
    return jsonify({"ok": True})

def set_webhook():
    # знімаємо попередній webhook + чистимо чергу апдейтів
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning(f"delete_webhook warn: {e}")

    url = f"{APP_URL.rstrip('/')}/{BOT_TOKEN}"
    ok = bot.set_webhook(url=url, drop_pending_updates=True, max_connections=40)
    if ok:
        log.info(f"✅ Webhook set: {url}")
    else:
        raise RuntimeError("Не вдалося встановити webhook")

# ================== ВХІДНА ТОЧКА ==================
if __name__ == "__main__":
    set_webhook()
    port = int(os.getenv("PORT", "10000"))
    log.info(f"🌐 Flask listening on {port}")
    app.run(host="0.0.0.0", port=port)
