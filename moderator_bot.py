import os
import re
from collections import defaultdict
from flask import Flask
from telegram.ext import Updater, MessageHandler, Filters

# ===== Налаштування =====
BOT_TOKEN = os.getenv("BOT_TOKEN") or "ВСТАВ_СВІЙ_ТОКЕН_ТУТ"

BAD_WORDS = [
    "хуй","пизда","єбать","єбуч","нахуй","гандон","залупа","блядь","сука",
    "fuck","shit","bitch","asshole","dick","pussy"
]

BANNED_TOPICS = [
    "політика","путін","зеленський","війна","мобілізація"
]

URL_PATTERN = re.compile(r"(https?://|www\.)", re.IGNORECASE)
warnings = defaultdict(int)

# ===== Flask сервер =====
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Bot is running", 200

# ===== Логіка перевірки повідомлень =====
def check_message(update, context):
    text = update.message.text.lower()

    if any(word in text for word in BAD_WORDS):
        handle_violation(update, context, "нецензурна лексика")
        return
    if any(topic in text for topic in BANNED_TOPICS):
        handle_violation(update, context, "заборонена тема")
        return
    if URL_PATTERN.search(text):
        handle_violation(update, context, "посилання")
        return

def handle_violation(update, context, reason):
    user_id = update.message.from_user.id
    warnings[user_id] += 1

    try:
        update.message.delete()
    except:
        pass

    if warnings[user_id] == 1:
        update.message.reply_text(f"⚠ Попередження! ({reason}). Наступного разу — бан.")
    elif warnings[user_id] >= 2:
        try:
            context.bot.kick_chat_member(update.message.chat_id, user_id)
            update.message.reply_text(f"🚫 Користувача заблоковано ({reason}).")
        except:
            update.message.reply_text("❌ Не вдалося забанити користувача.")

# ===== Запуск бота =====
def run_bot():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, check_message))

    # Очищаємо старі підключення вебхука
    updater.bot.delete_webhook(drop_pending_updates=True)

    print("✅ Telegram-бот запущено (polling)…")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    # Стартуємо бота і Flask в одному процесі
    import threading
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
