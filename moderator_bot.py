import os, re, threading
from flask import Flask
from telegram.ext import Updater, MessageHandler, Filters
from telegram import ChatPermissions
import re
from collections import defaultdict

BOT_TOKEN = os.getenv("BOT_TOKEN")

BAD_WORDS = [
    "хуй", "пизда", "єбать", "єбуч", "нахуй", "гандон", "залупа", "блядь", "сука", "шалава", "чмо", "мразь", "гнида",
    "fuck", "shit", "bitch", "asshole", "faggot", "dick", "pussy", "nigger", "retard",
    "хер", "даун", "ублюдок", "педик", "петух", "долбоеб", "мудак", "ганджа", "маріхуана", "травка"
]

BANNED_TOPICS = [
    "війна", "військо", "політика", "путін", "зеленський",
    "бомба", "мобілізація", "вторгнення", "рашка", "кацапи", "агресія",
    "нацист", "расизм", "тероризм", "смерть", "вбивство", "стрілянина"
]

URL_PATTERN = r"(https?://|www\.|[a-zA-Z0-9-]+\.(com|net|ua|org|ru|by|kz|pl|info|biz|io|gg|t\.me|me|ly))"

user_violations = defaultdict(int)
MAX_WARNINGS = 2

def moderate(update, context):
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    user_id = user.id
    chat_id = update.message.chat_id
    message = update.message.text.lower()

    violation = False

    if any(word in message for word in BAD_WORDS + BANNED_TOPICS):
        violation = True

    if re.search(URL_PATTERN, message):
        violation = True

    if violation:
        context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
        user_violations[user_id] += 1

        if user_violations[user_id] >= MAX_WARNINGS:
            try:
                context.bot.kick_chat_member(chat_id=chat_id, user_id=user_id)
                context.bot.send_message(chat_id=chat_id, text=f"🚫 Користувач {user.full_name} забанений за порушення правил.")
            except Exception as e:
                print(f"❗ Помилка бану (можливо, адмін): {e}")
        else:
            context.bot.send_message(chat_id=chat_id, text=f"⚠️ Попередження {user.full_name}: порушення правил ({user_violations[user_id]}/{MAX_WARNINGS})")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), moderate))
    print("✅ Бот-модератор запущено з Render")
    updater.start_polling()
    updater.idle()

# --- запускач бота у окремому потоці ---
def run_bot():
    updater = Updater(BOT_TOKEN, use_context=True)
    # прибираємо можливий webhook і старі апдейти (інакше конфлікт)
    updater.bot.delete_webhook(drop_pending_updates=True)

    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, moderate))

    print("✅ Telegram-бот запущено (polling)…")
    updater.start_polling(clean=True)
    updater.idle()

# --- крихітний веб-сервер для Render health-check ---
app = Flask(__name__)

@app.get("/")
def ok():
    return "OK", 200

if __name__ == "__main__":
    # бот у фоні
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()

    # Render очікує, що сервіс слухає PORT
    port = int(os.getenv("PORT", "10000"))
    print(f"🌐 Health server on port {port}")
    app.run(host="0.0.0.0", port=port)
