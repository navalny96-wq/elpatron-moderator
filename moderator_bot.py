# -*- coding: utf-8 -*-
import os
import re
import logging
from collections import defaultdict
from flask import Flask, request, jsonify

from telegram import Bot, Update, ChatPermissions
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler
from telegram.error import TelegramError

# ================== КОНФИГ (вшито під твій сервіс) ==================
BOT_TOKEN = "8313713885:AAGvmRipYoCdu2BiVdli2WRNgUxtRDN_OWU"
APP_URL   = "https://elpatron-moderator.onrender.com"  # твій домен Render
KEEPALIVE_KEY = "v3ryL0ngRand0mKey"                    # ключ для пінгу

# Попередження → перманентний мьют
MAX_WARNINGS = 2

# Нецензурна лексика / стоп-теми (можеш доповнювати)
BAD_WORDS = [
    "хуй","пизда","ебать","ёбать","ебуч","ёбуч","нахуй","гондон","залупа","блядь","сука",
    "шалава","чмо","мразь","гнида",
    "fuck","shit","bitch","asshole","dick","pussy","nigger","retard"
]
BANNED_TOPICS = [
    "политика","путин","зеленский","война","мобилизация","терроризм","насилие"
]

# Лінки (навіть без http)
URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)

# Пам’ять: попередження та м’юти на рівні чату
warnings = defaultdict(int)        # ключ: (chat_id, user_id) -> кількість попереджень
muted_users = defaultdict(set)     # ключ: chat_id -> set(user_id)

# ================== ЛОГИ ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("moderator")

# ================== TELEGRAM ==================
bot = Bot(BOT_TOKEN)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# ---- корисні утиліти ----
def is_privileged(chat_id: int, user_id: int) -> bool:
    """Не чіпаємо власника/адмінів/самого бота."""
    try:
        if user_id == bot.id:
            return True
        m = bot.get_chat_member(chat_id, user_id)
        return m.status in ("creator", "administrator")
    except TelegramError as e:
        log.warning(f"is_privileged error: {e}")
        return False

def require_admin(func):
    """Команда тільки для адмінів/власника."""
    def wrapper(update, context):
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if not is_privileged(chat_id, user_id):
            return
        return func(update, context)
    return wrapper

def mute_forever(chat_id: int, user_id: int):
    """Перманентний мьют (без строку)."""
    perms = ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
    )
    bot.restrict_chat_member(chat_id, user_id, permissions=perms)
    muted_users[chat_id].add(user_id)

def unmute(chat_id: int, user_id: int):
    """Зняти мьют (повернути можливість писати)."""
    perms = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
    )
    bot.restrict_chat_member(chat_id, user_id, permissions=perms)
    if user_id in muted_users[chat_id]:
        muted_users[chat_id].remove(user_id)

# ---- команди ----
def cmd_ping(update, context):
    try:
        context.bot.send_message(update.effective_chat.id, "🏓 Понг!")
    except TelegramError as e:
        log.warning(f"/ping send error: {e}")

@require_admin
def cmd_banlist(update, context):
    chat_id = update.effective_chat.id
    lst = muted_users[chat_id]
    if not lst:
        context.bot.send_message(chat_id, "📄 Список заблокированных пуст.")
        return
    ids = "\n".join(str(uid) for uid in lst)
    context.bot.send_message(chat_id, f"📄 Заблокированы (мьют):\n{ids}")

@require_admin
def cmd_unban(update, context):
    chat_id = update.effective_chat.id
    target_id = None

    # /unban у відповіді на повідомлення
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id

    # або /unban <user_id>
    if not target_id and context.args:
        arg = context.args[0]
        if arg.isdigit():
            target_id = int(arg)

    if not target_id:
        context.bot.send_message(chat_id, "ℹ️ Укажите пользователя: ответом на его сообщение или /unban <user_id>.")
        return

    if is_privileged(chat_id, target_id):
        context.bot.send_message(chat_id, "ℹ️ Администраторов и владельца не блокируем/разблокируем — у них свои права.")
        return

    try:
        unmute(chat_id, target_id)
        context.bot.send_message(chat_id, f"✅ Блокировка снята с пользователя {target_id}.")
    except TelegramError as e:
        log.warning(f"unban error: {e}")
        context.bot.send_message(chat_id, "❌ Не удалось снять блокировку.")

# ---- модерація ----
def handle_violation(update, context, reason: str):
    chat_id = update.effective_chat.id
    user = update.message.from_user
    uid = user.id

    # Імунітет для адмінів/власника/бота
    if is_privileged(chat_id, uid):
        return

    # 1) Видалити повідомлення
    try:
        update.message.delete()
    except TelegramError as e:
        log.warning(f"delete error: {e}")

    # 2) Попередження
    warnings[(chat_id, uid)] += 1
    count = warnings[(chat_id, uid)]

    # 3) Попередження або пермамьют
    if count < MAX_WARNINGS:
        try:
            context.bot.send_message(
                chat_id,
                f"⚠ Предупреждение {user.first_name or ''}! ({reason}). Следующее нарушение — блокировка."
            )
        except TelegramError as e:
            log.warning(f"warn send error: {e}")
    else:
        try:
            mute_forever(chat_id, uid)
            context.bot.send_message(
                chat_id,
                f"🚫 Пользователь {user.first_name or ''} заблокирован: писать сообщения запрещено."
            )
        except TelegramError as e:
            log.warning(f"mute error: {e}")
            context.bot.send_message(chat_id, "❌ Не удалось применить блокировку.")

def text_filter(update, context):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.lower()
    chat_id = msg.chat_id
    user_id = msg.from_user.id

    log.info(f"📩 {user_id} @ {chat_id}: {text}")

    # пропускаємо адмінів/власника/бота
    if is_privileged(chat_id, user_id):
        return

    # нецензурщина
    if any(w in text for w in BAD_WORDS):
        handle_violation(update, context, "нецензурная лексика")
        return

    # заборонені теми
    if any(t in text for t in BANNED_TOPICS):
        handle_violation(update, context, "запрещённая тема")
        return

    # посилання в тексті
    if URL_RE.search(text):
        handle_violation(update, context, "ссылки запрещены")
        return

    # посилання-entities
    if msg.entities:
        for ent in msg.entities:
            if ent.type in ("url", "text_link"):
                handle_violation(update, context, "ссылки запрещены")
                return

# реєстрація хендлерів
dispatcher.add_handler(CommandHandler("ping",    cmd_ping))
dispatcher.add_handler(CommandHandler("banlist", cmd_banlist))
dispatcher.add_handler(CommandHandler("unban",   cmd_unban, pass_args=True))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, text_filter))

# ================== FLASK (webhook) ==================
app = Flask(__name__)

@app.get("/")
def root():
    return "OK", 200

# keepalive (опційно, якщо хочеш пінгувати, щоб не засинав)
@app.get(f"/keepalive/{KEEPALIVE_KEY}")
def keepalive():
    return "ok", 200

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
    # зняти старий вебхук і почистити чергу
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning(f"delete_webhook warn: {e}")

    url = f"{APP_URL.rstrip('/')}/{BOT_TOKEN}"
    ok = bot.set_webhook(url=url, drop_pending_updates=True, max_connections=40)
    if ok:
        log.info(f"✅ Webhook set: {url}")
    else:
        raise RuntimeError("Не удалось установить webhook")

# ================== START ==================
if __name__ == "__main__":
    set_webhook()
    port = int(os.getenv("PORT", "10000"))
    log.info(f"🌐 Flask listening on {port}")
    app.run(host="0.0.0.0", port=port)
