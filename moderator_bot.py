# -*- coding: utf-8 -*-
import os
import re
import threading
from collections import defaultdict
from flask import Flask
from telegram.ext import Updater, MessageHandler, Filters

# ===== Налаштування =====
BOT_TOKEN = os.getenv("BOT_TOKEN") or "ВСТАВ_СВІЙ_ТОКЕН_ТУТ"

BAD_WORDS = [
    "хуй","пизда","єбать","єбуч","нахуй","гандон","залупа","блядь","сука","шалава","чмо","мразь","гнида",
    "fuck","shit","bitch","asshole","dick","pussy"
]
BANNED_TOPICS = [
    "політика","путін","зеленський","війна","мобілізація","тероризм","насильство"
]
URL_PATTERN = re.compile(r"(https?://|www\.)", re.IGNORECASE)

warnings = defaultdict(int)

# ===== Flask для health-check (Render) =====
app = Flask(__name__)

@app.route("/")
def index():
    return "OK", 200

def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

# ===== Логіка модерації =====
def handle_violation(update, context, reason):
    user_id = update.message.from_user.id
    warnings[user_id] += 1

    # Видаляємо повідомлення
    try:
        update.message.delete()
    except Exception as e:
        print("delete error:", e)

    if warnings[user_id] == 1:
        try:
            update.message.reply_text(f"⚠ Попередження! ({reason}). Наступного разу — бан.")
        except Exception as e:
            print("warn reply error:", e)
    else:
        # Бан після 2+ порушень
        try:
            context.bot.kick_chat_member(update.message.chat_id, user_id)
            update.message.reply_text(f"🚫 Користувача заблоковано ({reason}).")
        except Exception as e:
            print("ban error:", e)

def check_message(update, context):
    if not update.message or not update.message.text:
        return
    text = update.message.text.lower()

    if any(word in text for word in BAD_WORDS):
        handle_violation(update, context, "нецензурна лексика"); return
    if any(topic in text for topic in BANNED_TOPICS):
        handle_violation(update, context, "заборонена тема"); return
    if URL_PATTERN.search(text):
        handle_violation(update, context, "посилання"); return

# ===== Запуск =====
if __name__ == "__main__":
    # 1) Health-сервер у фоні (щоб Web Service на Render був «живий»)
    threading.Thread(target=run_health_server, daemon=True).start()

    # 2) Бот у ГОЛОВНОМУ потоці (щоб працювали сигнали всередині idle)
    updater = Updater(BOT_TOKEN, use_context=True)

    # КРИТИЧНО: прибираємо будь-який можливий вебхук і підвішені апдейти
    try:
        updater.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print("delete_webhook error:", e)

    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, check_message))

    print("✅ Telegram-бот запущено (polling)…")
    # Використовуємо сучасний параметр: drop_pending_updates=True
    updater.start_polling(drop_pending_updates=True)
    updater.idle()
