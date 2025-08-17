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

# Скільки попереджень до пермам’юта
MAX_WARNINGS = 2

# ===== Нецензурна/образлива лексика, лайтові образи (укр/рус/eng) =====
BAD_WORDS = [
    # RU/UA hard
    "хуй","пизда","ебать","ёбать","єбать","єбуч","ебуч","ёбуч","нахуй","гондон","залупа","блядь","сука",
    "шалава","чмо","мразь","гнида","ублюдок","падла","сучара","петух","хер",
    # RU/UA mild insults / slang
    "какашка","черкаш","дебіл","дебил","дурак","ідіот","идиот","кретин","тупой","тупица","ніщеброд","нищеброд",
    "мудак","урод","тварь","скотина","козел","козёл","баран","нищебрик","задрот","говнюк","сраний","срака","жопа",
    "пиписька","піся","сиска","дерьмо","говно","шлак","лох","придурок","придурок","обморок","випердок","випердок",
    # EN
    "fuck","shit","bitch","asshole","dick","pussy","jerk","idiot","stupid","moron","loser",
    "dumbass","scumbag","weirdo","bastard","retard","nigger", # (образливі — щоб фільтрувати)
]

# Заборонені теми (залишив як було, за потреби розшириш)
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

def is_from_sender_chat(msg) -> bool:
    """
    Повідомлення від імені чату/каналу/анонімного адміна.
    У такому випадку НЕ модерувати взагалі.
    """
    try:
        return bool(getattr(msg, "sender_chat", None))
    except Exception:
        return False

def require_admin(func):
    """Команда тільки для адмінів/власника."""
    def wrapper(update, context):
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        # дозволяємо з приватного теж, але перевіряємо, що юзер — адмін у цій групі
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
    if update.message and update.message.reply_to_message:
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
    msg = update.message
    if not msg:
        return
    chat_id = msg.chat_id

    # 0) Якщо від імені чату/каналу — не чіпаємо взагалі
    if is_from_sender_chat(msg):
        return

    user = msg.from_user
    if not user:
        return
    uid = user.id

    # 1) Імунітет для адмінів/власника/бота
    if is_privileged(chat_id, uid):
        return

    # 2) Видалити повідомлення
    try:
        msg.delete()
    except TelegramError as e:
        log.warning(f"delete error: {e}")

    # 3) Попередження/мьют
    warnings[(chat_id, uid)] += 1
    count = warnings[(chat_id, uid)]

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

    text = msg.text.lower().strip()
    chat_id = msg.chat_id
    user_id = msg.from_user.id if msg.from_user else None

    log.info(f"📩 {user_id} @ {chat_id}: {text}")

    # 0) Якщо від імені чату/каналу — не модерувати взагалі
    if is_from_sender_chat(msg):
        return

    # 1) Пропускаємо адмінів/власника/бота
    if user_id and is_privileged(chat_id, user_id):
        return

    # 2) Нецензурщина / образи
    if any(w in text for w in BAD_WORDS):
        handle_violation(update, context, "нецензурная/оскорбительная лексика")
        return

    # 3) Заборонені теми
    if any(t in text for t in BANNED_TOPICS):
        handle_violation(update, context, "запрещённая тема")
        return

    # 4) Посилання в тексті
    if URL_RE.search(text):
        handle_violation(update, context, "ссылки запрещены")
        return

    # 5) Посилання як entities
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
        logging.exception(f"update handling error: {e}")
        return jsonify({"ok": False}), 500
    return jsonify({"ok": True})

def set_webhook():
    # зняти старий вебхук і почистити чергу
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"delete_webhook warn: {e}")

    url = f"{APP_URL.rstrip('/')}/{BOT_TOKEN}"
    ok = bot.set_webhook(url=url, drop_pending_updates=True, max_connections=40)
    if ok:
        logging.info(f"✅ Webhook set: {url}")
    else:
        raise RuntimeError("Не удалось установить webhook")

# ================== START ==================
if __name__ == "__main__":
    set_webhook()
    port = int(os.getenv("PORT", "10000"))
    logging.info(f"🌐 Flask listening on {port}")
    app.run(host="0.0.0.0", port=port)
