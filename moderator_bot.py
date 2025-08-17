# -*- coding: utf-8 -*-
import os
import re
import json
import logging
from collections import defaultdict
from flask import Flask, request, jsonify

from telegram import Bot, Update, ChatPermissions
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler
from telegram.error import TelegramError

# ================== КОНФИГ ==================
BOT_TOKEN = "8313713885:AAGvmRipYoCdu2BiVdli2WRNgUxtRDN_OWU"
APP_URL   = "https://elpatron-moderator.onrender.com"
KEEPALIVE_KEY = "v3ryL0ngRand0mKey"

MAX_WARNINGS = 2
STATE_FILE_WARN = "warnings.json"
STATE_FILE_MUTED = "muted.json"

BAD_WORDS = [
    "хуй","пизда","ебать","ёбать","єбать","єбуч","ебуч","ёбуч","нахуй","гондон","залупа","блядь","сука",
    "шалава","чмо","мразь","гнида","ублюдок","падла","сучара","петух","хер",
    "какашка","черкаш","дебіл","дебил","дурак","ідіот","идиот","кретин","тупой","тупица","ніщеброд","нищеброд",
    "мудак","урод","тварь","скотина","козел","козёл","баран","нищебрик","задрот","говнюк","сраний","срака","жопа",
    "пиписька","піся","сиска","дерьмо","говно","шлак","лох","придурок","обморок","випердок",
    "ссыкло","ссыкун","балбес","жалкий","ничтожество","скот","жлоб","хряк","сопляк","чучело",
    "fuck","shit","bitch","asshole","dick","pussy","jerk","idiot","stupid","moron","loser",
    "dumbass","scumbag","weirdo","bastard","retard","nigger"
]
BANNED_TOPICS = [
    "политика","путин","зеленский","война","мобилизация","терроризм","насилие"
]
URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)

warnings = defaultdict(int)
muted_users = defaultdict(set)

# ================== ЗБЕРЕЖЕННЯ/ЗАВАНТАЖЕННЯ ==================
def save_state():
    try:
        with open(STATE_FILE_WARN, "w", encoding="utf-8") as f:
            json.dump({f"{c}:{u}":cnt for (c,u),cnt in warnings.items()}, f)
        with open(STATE_FILE_MUTED, "w", encoding="utf-8") as f:
            json.dump({str(c):list(u) for c,u in muted_users.items()}, f)
    except Exception as e:
        log.warning(f"save_state error: {e}")

def load_state():
    global warnings, muted_users
    try:
        if os.path.exists(STATE_FILE_WARN):
            with open(STATE_FILE_WARN,"r",encoding="utf-8") as f:
                data = json.load(f)
                warnings = defaultdict(int,{tuple(map(int,k.split(":"))):v for k,v in data.items()})
        if os.path.exists(STATE_FILE_MUTED):
            with open(STATE_FILE_MUTED,"r",encoding="utf-8") as f:
                data = json.load(f)
                muted_users = defaultdict(set,{int(k):set(v) for k,v in data.items()})
    except Exception as e:
        log.warning(f"load_state error: {e}")

# ================== ЛОГИ ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("moderator")

# ================== TELEGRAM ==================
bot = Bot(BOT_TOKEN)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

def is_privileged(chat_id, user_id):
    try:
        if user_id == bot.id:
            return True
        m = bot.get_chat_member(chat_id, user_id)
        return m.status in ("creator", "administrator")
    except:
        return False

def is_from_sender_chat(msg):
    return bool(getattr(msg,"sender_chat",None))

def mute_forever(chat_id, user_id):
    perms = ChatPermissions(can_send_messages=False)
    bot.restrict_chat_member(chat_id, user_id, permissions=perms)
    muted_users[chat_id].add(user_id)
    save_state()

def unmute(chat_id, user_id):
    perms = ChatPermissions(can_send_messages=True)
    bot.restrict_chat_member(chat_id, user_id, permissions=perms)
    if user_id in muted_users[chat_id]:
        muted_users[chat_id].remove(user_id)
    save_state()

def delete_for_all(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

# ---- модерація ----
def handle_violation(update, context, reason):
    msg = update.message
    chat_id = msg.chat_id
    user = msg.from_user
    uid = user.id
    if is_privileged(chat_id, uid) or is_from_sender_chat(msg):
        return
    delete_for_all(chat_id, msg.message_id)
    warnings[(chat_id,uid)] += 1
    save_state()
    if warnings[(chat_id,uid)] < MAX_WARNINGS:
        context.bot.send_message(chat_id,f"⚠ Предупреждение {user.first_name}: {reason}.")
    else:
        mute_forever(chat_id, uid)
        context.bot.send_message(chat_id,f"🚫 Пользователь {user.first_name} замьючен навсегда.")

def text_filter(update, context):
    msg = update.message
    chat_id = msg.chat_id
    user = msg.from_user
    if not msg or not user: return
    if is_privileged(chat_id,user.id) or is_from_sender_chat(msg): return
    text = (msg.text or msg.caption or "").lower()
    if any(w in text for w in BAD_WORDS): handle_violation(update,context,"нецензурная лексика"); return
    if any(t in text for t in BANNED_TOPICS): handle_violation(update,context,"запрещённая тема"); return
    if URL_RE.search(text): handle_violation(update,context,"ссылки запрещены"); return
    if msg.entities or msg.caption_entities:
        for ent in (msg.entities or [])+(msg.caption_entities or []):
            if ent.type in ("url","text_link"):
                handle_violation(update,context,"ссылки запрещены"); return

# ---- команди ----
def cmd_ping(update, context): context.bot.send_message(update.effective_chat.id,"🏓 Понг!")
def cmd_banlist(update, context):
    chat_id = update.effective_chat.id
    ids = muted_users.get(chat_id,set())
    context.bot.send_message(chat_id, "📄 Заблокированы:\n"+"\n".join(map(str,ids)) if ids else "Список пуст.")
def cmd_unban(update, context):
    chat_id = update.effective_chat.id
    if update.message.reply_to_message:
        uid = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].isdigit():
        uid=int(context.args[0])
    else: return
    unmute(chat_id, uid)
    context.bot.send_message(chat_id,f"✅ {uid} размьючен.")

dispatcher.add_handler(CommandHandler("ping",cmd_ping))
dispatcher.add_handler(CommandHandler("banlist",cmd_banlist))
dispatcher.add_handler(CommandHandler("unban",cmd_unban,pass_args=True))
dispatcher.add_handler(MessageHandler((Filters.text|Filters.caption)&~Filters.command,text_filter))

# ================== FLASK ==================
app = Flask(__name__)

@app.get("/") 
def root(): return "OK",200
@app.get(f"/keepalive/{KEEPALIVE_KEY}") 
def keepalive(): return "ok",200
@app.post(f"/{BOT_TOKEN}")
def webhook():
    try:
        data=request.get_json(force=True)
        update=Update.de_json(data,bot)
        dispatcher.process_update(update)
    except Exception as e:
        logging.exception(e); return jsonify({"ok":False}),500
    return jsonify({"ok":True})

def set_webhook():
    bot.delete_webhook(drop_pending_updates=True)
    url=f"{APP_URL.rstrip('/')}/{BOT_TOKEN}"
    bot.set_webhook(url=url,drop_pending_updates=True,max_connections=40)

# ================== START ==================
if __name__=="__main__":
    load_state()
    set_webhook()
    port=int(os.getenv("PORT","10000"))
    app.run(host="0.0.0.0",port=port)
