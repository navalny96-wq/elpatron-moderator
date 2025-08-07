# -*- coding: utf-8 -*-
import os
import re
import logging
from collections import defaultdict
from flask import Flask, request, jsonify

from telegram import Bot, Update
from telegram.ext import Dispatcher, MessageHandler, Filters
from telegram.error import TelegramError

# ========= базові налаштування =========
BOT_TOKEN = os.getenv("BOT_TOKEN") or "ВСТАВ_СВІЙ_ТОКЕН_ТУТ"
if BOT_TOKEN == "ВСТАВ_СВІЙ_ТОКЕН_ТУТ":
    raise RuntimeError("Задай BOT_TOKEN у змінних середовища.")

# URL сервісу (Render підставляє RENDER_EXTERNAL_URL автоматично)
APP_URL = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL")
if not APP_URL:
    raise RuntimeError("Нема APP_URL/RENDER_EXTERNAL_URL. Додай APP_URL в Environment на Render.")

BAD_WORDS = [
    "хуй","пизда","єбать","єбуч","нахуй","гандон","залупа","блядь","сука","шалава","чмо","мразь","гнида",
    "fuck","shit","bitch","asshole","dick","pussy"
]
BANNED_TOPICS = [
    "політика","путін","зеленський","війна","мобілізація","тероризм","насильство"
]
URL_PATTERN = re.compile(r"(https?://|www\.)", re.IGNORECASE)
MAX_WARNINGS = 2

warnings = defaultdict(int)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("modbot")

# ========= Telegram обʼєкти =========
bot = Bot(BOT_TOKEN)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# ========= логіка модерації =========
def handle_violation(update, context, reason):
    u = update.message.from_user
    uid = u.id
    chat_id = update.message.chat_id

    warnings[uid] += 1

    # видаляємо повідомлення
    try:
        update.message.delete()
    except TelegramError as e:
        log.warning(f"delete error: {e}")

    if warnings[uid] < MAX_WARNINGS:
        try:
            update.message.reply_text(f"⚠ Попередження! ({reason}). Наступного разу — бан.")
        except TelegramError as e:
            log.warning(f"warn reply error: {e}")
    else:
        try:
            context.bot.kick_chat_member(chat_id, uid)
            update.message.reply_text(f"🚫 Користувача заблоковано ({reason}).")
        except TelegramError as e:
            log.warning(f"ban error: {e}")

def check_message(update, context):
    if not update.message or not update.message.text:
        return
    text = update.message.text.lower()

    if any(w in text for w in BAD_WORDS):
        handle_violation(update, context, "нецензурна лексика"); return
    if any(t in text for t in BANNED_TOPICS):
        handle_violation(update, context, "заборонена тема"); return
    if URL_PATTERN.search(text):
        handle_violation(update, context, "посилання"); return

dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, check_message))

# ========= Flask / Webhook =========
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
    # Перед установкою — чистимо підвішені апдейти
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

if __name__ == "__main__":
    set_webhook()
    port = int(os.getenv("PORT", "10000"))
    log.info(f"🌐 Flask listening on {port}")
    app.run(host="0.0.0.0", port=port)
