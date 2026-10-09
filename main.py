"""
╔══════════════════════════════════════════════════════════╗
║   ✦ MDX-MAIL TELEGRAM BOT  v5.3 (INLINE BUTTONS)      ║
║   Only .xyz domains | Inline start menu                 ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import re
import logging
from typing import Optional, List, Tuple

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────

BOT_TOKEN     = "8740338998:AAHuWO26h_lO-_1a9ha6JV-Bu2zk5l_BYzU"
ADMIN_ID      = 7776377629
CHANNEL_USER  = "@ImranEarningZone1"
POLL_INTERVAL = 5
SITE_URL      = "https://tm-mail.com"
GET_MESSAGES  = "https://tm-mail.com/get_messages"
MAX_BODY      = 3800
MAX_RETRIES   = 5

# ──────────────────────────────────────────────
#  LOGGING
# ──────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  SESSION STORE
# ──────────────────────────────────────────────

class UserSession:
    def __init__(self):
        self.http:        Optional[aiohttp.ClientSession] = None
        self.email:       str  = ""
        self.token:       str  = ""
        self.xsrf:        str  = ""
        self.seen:        set  = set()
        self.watching:    bool = False
        self.name:        str  = ""
        self.chat_id:     int  = 0
        self.email_count: int  = 0

sessions:          dict[int, UserSession] = {}
pending_admin_msg: dict[int, bool]        = {}

# ──────────────────────────────────────────────
#  BROWSER HEADERS
# ──────────────────────────────────────────────

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 16; A001T) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.7922.199 Mobile Safari/537.36"
    ),
    "Accept":            "application/json, text/plain, */*",
    "Origin":            SITE_URL,
    "Referer":           SITE_URL + "/",
    "x-requested-with":  "mark.via.gz",
    "sec-fetch-site":    "same-origin",
    "sec-fetch-mode":    "cors",
    "sec-fetch-dest":    "empty",
    "accept-language":   "en-GB,en-US;q=0.9,en;q=0.8",
}

# ──────────────────────────────────────────────
#  UI HELPERS
# ──────────────────────────────────────────────

PARSE = "HTML"

def _b(t: str)   -> str: return f"<b>{t}</b>"
def _i(t: str)   -> str: return f"<i>{t}</i>"
def _c(t: str)   -> str: return f"<code>{t}</code>"
def _pre(t: str) -> str: return f"<pre>{t}</pre>"

def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

DIV  = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
DIV2 = "━━━━━━━━━━━━━━━━━━━━━━"

def header(title: str) -> str:
    return f"{_b('✦ MDX-MAIL')}  {_i(title)}\n{DIV}"

# ──────────────────────────────────────────────
#  START MENU KEYBOARD  ← inline buttons
# ──────────────────────────────────────────────

def start_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📬  New Email",         callback_data=f"menu_new|{uid}"),
            InlineKeyboardButton("📧  Show Email",        callback_data=f"menu_email|{uid}"),
        ],
        [
            InlineKeyboardButton("📩  Get Mail",          callback_data=f"menu_getmail|{uid}"),
            InlineKeyboardButton("⏹   Stop",              callback_data=f"menu_stop|{uid}"),
        ],
        [
            InlineKeyboardButton("🗑   Delete Session",   callback_data=f"menu_delete|{uid}"),
            InlineKeyboardButton("💬  Talk to Admin",     callback_data=f"menu_admin|{uid}"),
        ],
    ])

# ──────────────────────────────────────────────
#  AFTER-EMAIL KEYBOARD
# ──────────────────────────────────────────────

def main_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📬  Get Mail",          callback_data=f"getmail|{uid}"),
            InlineKeyboardButton("🔄  New Email",         callback_data=f"new|{uid}"),
        ],
        [
            InlineKeyboardButton("💬  Talk to Admin",     callback_data=f"talkadmin|{uid}"),
        ],
    ])

# ──────────────────────────────────────────────
#  CHANNEL JOIN CHECK
# ──────────────────────────────────────────────

async def is_member(bot, uid: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USER, user_id=uid)
        return member.status not in ("left", "kicked", "banned")
    except TelegramError:
        return False

def join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢  Channel Join Karo", url=f"https://t.me/{CHANNEL_USER.lstrip('@')}")],
        [InlineKeyboardButton("✅  Join Ho Gaya",      callback_data="check_join")],
    ])

async def send_join_prompt(target):
    await target.reply_text(
        f"{header('Join Required')} 🔒\n\n"
        f"  Bot use karne ke liye pehle channel join karo:\n\n"
        f"  📢  {_c(CHANNEL_USER)}\n\n"
        f"  Join karne ke baad {_b('✅ Join Ho Gaya')} button dabao.\n\n"
        f"{DIV2}",
        reply_markup=join_keyboard(),
        parse_mode=PARSE,
    )

# ──────────────────────────────────────────────
#  HTML → CLEAN TEXT + LINK EXTRACT
# ──────────────────────────────────────────────

def strip_html(raw: str) -> Tuple[str, List[Tuple[str, str]]]:
    if not raw:
        return "", []

    raw = re.sub(r"<style[^>]*>.*?</style>",   "", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<head[^>]*>.*?</head>",     "", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"@[\w-]+\s*\([^)]*\)\s*\{[^}]*\}", "", raw, flags=re.DOTALL)
    raw = re.sub(r"@[\w-]+[^{]*\{[^}]*\}",           "", raw, flags=re.DOTALL)

    links = []

    def extract_anchor(m):
        href = m.group(1).strip()
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        href = href.replace("&amp;", "&").replace("&quot;", '"')
        if href and not href.startswith("mailto:"):
            links.append((text, href))
        if text and text.lower() not in href.lower():
            return f"{text}\n{href}"
        return href

    raw = re.sub(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        extract_anchor,
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )

    raw = re.sub(r"<br\s*/?>",  "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<p[^>]*>",   "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<tr[^>]*>",  "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<td[^>]*>",  "  ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<div[^>]*>", "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", "", raw)

    raw = (raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
              .replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"'))

    raw = re.sub(r"\n{3,}", "\n\n", raw)
    lines = [l for l in raw.splitlines() if l.strip()]
    clean_text = "\n".join(lines).strip()
    return clean_text, links

# ──────────────────────────────────────────────
#  DOMAIN FILTER
# ──────────────────────────────────────────────

def is_valid_domain(email: str) -> bool:
    return email.lower().endswith(".xyz")

# ──────────────────────────────────────────────
#  API FUNCTIONS
# ──────────────────────────────────────────────

async def _new_http() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(
        ssl=True, limit=10, ttl_dns_cache=300, enable_cleanup_closed=True,
    )
    return aiohttp.ClientSession(
        connector=connector,
        cookie_jar=aiohttp.CookieJar(),
        headers=BASE_HEADERS,
        timeout=aiohttp.ClientTimeout(total=20, connect=10),
    )

async def create_session_and_email(uid: int) -> bool:
    sess = sessions.get(uid)
    if not sess:
        return False
    if sess.http and not sess.http.closed:
        await sess.http.close()
    sess.http = await _new_http()

    for attempt in range(MAX_RETRIES):
        try:
            async with sess.http.get(SITE_URL) as r:
                r.raise_for_status()
            xsrf = ""
            for cookie in sess.http.cookie_jar:
                if cookie.key == "XSRF-TOKEN":
                    xsrf = cookie.value
                    break
            sess.xsrf = xsrf
            extra = {"content-type": "application/json"}
            if xsrf:
                extra["x-xsrf-token"] = xsrf
            async with sess.http.post(GET_MESSAGES, json={"_token": xsrf}, headers=extra) as r:
                data = await r.json(content_type=None)
                if data.get("status"):
                    email = data.get("mailbox", "")
                    if is_valid_domain(email):
                        sess.email = email
                        sess.token = data.get("email_token", "")
                        sess.email_count += 1
                        return True
                    else:
                        log.info(f"[{uid}] Rejected domain: {email} (attempt {attempt+1})")
                        await sess.http.close()
                        sess.http = await _new_http()
                        continue
        except Exception as e:
            log.error(f"[{uid}] create_session error: {e}")
            return False
    log.error(f"[{uid}] Could not get .xyz domain after {MAX_RETRIES} attempts.")
    return False

async def fetch_messages(uid: int) -> list:
    sess = sessions.get(uid)
    if not sess or not sess.http:
        return []
    try:
        extra = {"content-type": "application/json"}
        if sess.xsrf:
            extra["x-xsrf-token"] = sess.xsrf
        async with sess.http.post(GET_MESSAGES, json={"_token": sess.xsrf}, headers=extra) as r:
            data = await r.json(content_type=None)
            for cookie in sess.http.cookie_jar:
                if cookie.key == "XSRF-TOKEN":
                    sess.xsrf = cookie.value
                    break
            if data.get("status"):
                sess.email = data.get("mailbox", sess.email)
                return data.get("messages", [])
        return []
    except Exception as e:
        log.warning(f"[{uid}] fetch error: {e}")
        return []

# ──────────────────────────────────────────────
#  SEND FULL MAIL
# ──────────────────────────────────────────────

async def _send_full_mail(mail: dict, target=None, bot=None, chat_id: int = None):
    content = mail.get("content") or mail.get("html") or mail.get("body") or ""
    clean_text, links = strip_html(str(content))

    sender  = esc(str(mail.get("from_email") or mail.get("from") or "Unknown"))
    subject = esc(str(mail.get("subject") or "(No Subject)"))
    time_   = esc(str(mail.get("receivedAt") or ""))

    hdr = (
        f"{header('New Mail')} 📬\n\n"
        f"👤  {_i('From')}     {_c(sender)}\n"
        f"📌  {_i('Subject')}  {_c(subject)}"
    )
    if time_:
        hdr += f"\n🕐  {_i('Time')}    {_c(time_)}"
    hdr += f"\n\n{DIV2}\n\n"

    body_text = esc(clean_text[:MAX_BODY])
    full = hdr + body_text

    login_link = None
    login_text = ""
    for text, url in links:
        if "claude.ai" in url.lower() or "anthropic.com" in url.lower():
            if any(k in url.lower() for k in ("login", "signin", "auth")):
                login_link = url; login_text = text; break
    if not login_link:
        for text, url in links:
            if "sign in" in text.lower() and "claude" in text.lower():
                login_link = url; login_text = text; break
    if not login_link:
        for text, url in links:
            if "claude.ai" in url.lower():
                login_link = url; login_text = text; break
    if not login_link:
        for text, url in links:
            if url.startswith("https://"):
                login_link = url; login_text = text; break

    log.info(f"Found login link: {login_link}")

    keyboard = []
    if login_link:
        keyboard.append([InlineKeyboardButton("🔐 Click to Login to Claude", url=login_link)])
    added = 0
    for text, url in links:
        if url != login_link and url.startswith("https://") and added < 2:
            keyboard.append([InlineKeyboardButton(f"🔗 {text[:20]}", url=url)])
            added += 1
    keyboard.append([InlineKeyboardButton("📬 Get More Mails",  callback_data="getmail_again")])
    keyboard.append([InlineKeyboardButton("🔄 New Email",       callback_data="new_email_again")])

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    async def _send(text, markup=None):
        if bot and chat_id:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=PARSE, reply_markup=markup)
        else:
            await target.reply_text(text, parse_mode=PARSE, reply_markup=markup)

    if len(full) <= 4096:
        await _send(full, reply_markup)
    else:
        await _send(hdr)
        for i in range(0, len(body_text), 4000):
            await _send(body_text[i:i+4000])
        if reply_markup:
            await _send("👇 Click below to login:", reply_markup)

# ──────────────────────────────────────────────
#  POLL LOOP
# ──────────────────────────────────────────────

async def _poll_loop(uid: int, chat_id: int, bot):
    log.info(f"[{uid}] poll loop started")
    while uid in sessions and sessions[uid].watching:
        try:
            mails = await fetch_messages(uid)
            for mail in mails:
                mail_id = str(mail.get("id", ""))
                if not mail_id or mail_id in sessions[uid].seen:
                    continue
                sessions[uid].seen.add(mail_id)
                await _send_full_mail(mail, bot=bot, chat_id=chat_id)
                log.info(f"[{uid}] sent full mail: {mail_id}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning(f"[{uid}] poll error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
    log.info(f"[{uid}] poll loop ended")

# ──────────────────────────────────────────────
#  SHARED: generate new email (reused in many places)
# ──────────────────────────────────────────────

async def _do_new_email(uid: int, user, edit_fn, reply_fn):
    """
    edit_fn(text, markup)  — for editing an existing message
    reply_fn(text, markup) — for sending a new message
    """
    if uid in sessions:
        sessions[uid].watching = False
        if sessions[uid].http and not sessions[uid].http.closed:
            await sessions[uid].http.close()
        prev_count = sessions[uid].email_count
    else:
        prev_count = 0

    sessions[uid]             = UserSession()
    sessions[uid].name        = user.full_name or str(uid)
    sessions[uid].chat_id     = 0          # set by caller after
    sessions[uid].email_count = prev_count

    ok = await create_session_and_email(uid)
    if ok and sessions[uid].email:
        text   = (
            f"{header('Email Ready')} ✅\n\n"
            f"  📧  {_c(esc(sessions[uid].email))}\n\n"
            f"  {_i('Tap karke copy karo, fir kahi use karo.')}\n\n"
            f"{DIV2}"
        )
        markup = main_keyboard(uid)
    else:
        text   = (
            f"{header('Error')} ❌\n\n"
            f"  Email generate nahi hua.\n"
            f"  Thodi der baad dobara try karo."
        )
        markup = None

    await edit_fn(text, markup)

# ──────────────────────────────────────────────
#  COMMAND HANDLERS
# ──────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = update.effective_user

    if not await is_member(ctx.bot, uid):
        await send_join_prompt(update.message)
        return

    if uid not in sessions:
        sessions[uid] = UserSession()
    sessions[uid].name    = user.full_name or str(uid)
    sessions[uid].chat_id = update.effective_chat.id

    await update.message.reply_text(
        f"{header('Disposable Email')}\n\n"
        f"  Koi bhi button dabao shuru karne ke liye 👇\n\n"
        f"{DIV2}",
        reply_markup=start_keyboard(uid),
        parse_mode=PARSE,
    )


async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = update.effective_user

    if not await is_member(ctx.bot, uid):
        await send_join_prompt(update.message)
        return

    msg = await update.message.reply_text(
        f"{header('Generating...')}\n\n⏳  {_i('Naya email aa raha hai...')}",
        parse_mode=PARSE,
    )

    async def edit(text, markup):
        await msg.edit_text(text, reply_markup=markup, parse_mode=PARSE)

    sessions.setdefault(uid, UserSession()).chat_id = update.effective_chat.id
    await _do_new_email(uid, user, edit, edit)
    sessions[uid].chat_id = update.effective_chat.id


async def cmd_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_member(ctx.bot, uid):
        await send_join_prompt(update.message)
        return
    if uid not in sessions or not sessions[uid].email:
        await update.message.reply_text(
            f"{header('No Session')} ❌\n\nPehle {_c('/new')} se email banao.",
            parse_mode=PARSE,
        )
        return
    await update.message.reply_text(
        f"{header('Current Email')}\n\n"
        f"  📧  {_c(esc(sessions[uid].email))}\n\n"
        f"{DIV2}",
        reply_markup=main_keyboard(uid),
        parse_mode=PARSE,
    )


async def cmd_getmail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_member(ctx.bot, uid):
        await send_join_prompt(update.message)
        return
    if uid not in sessions or not sessions[uid].email:
        await update.message.reply_text(
            f"{header('No Session')} ❌\n\nPehle {_c('/new')} se email banao.",
            parse_mode=PARSE,
        )
        return
    if sessions[uid].watching:
        await update.message.reply_text(
            f"{header('Already Active')} 👁\n\n{_i('Mail monitoring pehle se chal rahi hai.')}",
            parse_mode=PARSE,
        )
        return
    await update.message.reply_text(
        f"{header('Get Mail')} ⏳\n\n"
        f"  {_i('Thoda der wait kare...')}\n"
        f"  {_i('Jab mail aayega, main turant dikha dunga.')}\n\n"
        f"{DIV2}",
        parse_mode=PARSE,
    )
    sessions[uid].watching = True
    ctx.application.create_task(
        _poll_loop(uid, update.effective_chat.id, ctx.application.bot)
    )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in sessions and sessions[uid].watching:
        sessions[uid].watching = False
        await update.message.reply_text(
            f"{header('Stopped')} ⏹\n\n{_i('Mail monitoring band ho gayi.')}",
            parse_mode=PARSE,
        )
    else:
        await update.message.reply_text(
            f"{header('Not Active')} ℹ️\n\n{_i('Monitoring chal nahi rahi thi.')}",
            parse_mode=PARSE,
        )


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in sessions:
        await update.message.reply_text(
            f"{header('No Session')} ❌\n\n{_i('Koi active session nahi.')}",
            parse_mode=PARSE,
        )
        return
    sessions[uid].watching = False
    if sessions[uid].http and not sessions[uid].http.closed:
        await sessions[uid].http.close()
    del sessions[uid]
    await update.message.reply_text(
        f"{header('Deleted')} 🗑\n\n"
        f"  Session delete ho gaya.\n"
        f"  {_c('/new')} se naya banao.",
        parse_mode=PARSE,
    )


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_member(ctx.bot, uid):
        await send_join_prompt(update.message)
        return
    pending_admin_msg[uid] = True
    await update.message.reply_text(
        f"{header('Talk to Admin')} 💬\n\n"
        f"  {_i('Apna message type karo, admin tak pahuncha dunga.')}\n\n"
        f"  {_c('Cancel: /cancel')}",
        parse_mode=PARSE,
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pending_admin_msg.pop(uid, None)
    await update.message.reply_text(
        f"{header('Cancelled')} ✖️\n\n{_i('Message cancel ho gaya.')}",
        parse_mode=PARSE,
    )


async def cmd_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not sessions:
        await update.message.reply_text(
            f"{header('Users')} 👥\n\n{_i('Abhi koi active user nahi.')}",
            parse_mode=PARSE,
        )
        return
    lines = [f"{header('Active Users')} 👥\n"]
    for uid, sess in sessions.items():
        status = "📬 watching" if sess.watching else "💤 idle"
        email  = _c(esc(sess.email)) if sess.email else _i("no email")
        lines.append(
            f"  {_b(esc(sess.name or str(uid)))}\n"
            f"  🆔  {_c(str(uid))}\n"
            f"  📧  {email}\n"
            f"  ⚡  {status}\n"
            f"  {DIV}"
        )
    lines.append(f"\n  Total: {_b(str(len(sessions)))} users")
    await update.message.reply_text("\n".join(lines), parse_mode=PARSE)


async def cmd_usermail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not sessions:
        await update.message.reply_text(
            f"{header('User Mails')} 📋\n\n{_i('Abhi koi user nahi hai.')}",
            parse_mode=PARSE,
        )
        return
    lines = [f"{header('User Mail Report')} 📋\n"]
    for idx, (uid, sess) in enumerate(sessions.items(), start=1):
        name   = esc(sess.name or str(uid))
        email  = _c(esc(sess.email)) if sess.email else _i("— koi email nahi —")
        count  = _b(str(sess.email_count))
        status = "📬 watching" if sess.watching else "💤 idle"
        lines.append(
            f"  {_b(f'#{idx}')}  {_b(name)}\n"
            f"  🆔  {_c(str(uid))}\n"
            f"  📧  {email}\n"
            f"  🔢  Generated: {count} email(s)\n"
            f"  ⚡  {status}\n"
            f"  {DIV}"
        )
    total_emails = sum(s.email_count for s in sessions.values())
    lines.append(
        f"\n{DIV2}\n"
        f"  👥  Total users   : {_b(str(len(sessions)))}\n"
        f"  📨  Total emails  : {_b(str(total_emails))}"
    )
    text = "\n".join(lines)
    if len(text) <= 4096:
        await update.message.reply_text(text, parse_mode=PARSE)
    else:
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i+4000], parse_mode=PARSE)


async def cmd_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            f"{header('Usage')} ℹ️\n\n{_c('/reply <user_id> <message>')}",
            parse_mode=PARSE,
        )
        return
    try:
        target_uid = int(args[0])
    except ValueError:
        await update.message.reply_text(
            f"{header('Error')} ❌\n\nInvalid user ID: {_c(esc(args[0]))}",
            parse_mode=PARSE,
        )
        return
    msg_text = " ".join(args[1:])
    sess     = sessions.get(target_uid)
    chat_id  = sess.chat_id if sess and sess.chat_id else target_uid
    try:
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=f"{header('Admin Reply')} 💬\n\n{esc(msg_text)}\n\n{DIV2}\n  {_i('— Admin')}",
            parse_mode=PARSE,
        )
        await update.message.reply_text(
            f"{header('Sent')} ✅\n\n{_i('Reply bhej diya user')} {_c(str(target_uid))} {_i('ko.')}",
            parse_mode=PARSE,
        )
    except TelegramError as e:
        await update.message.reply_text(
            f"{header('Failed')} ❌\n\n{_c(esc(str(e)))}",
            parse_mode=PARSE,
        )

# ──────────────────────────────────────────────
#  MESSAGE HANDLER
# ──────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = update.effective_user
    text = update.message.text or ""

    if pending_admin_msg.get(uid):
        pending_admin_msg.pop(uid)
        name = esc(user.full_name or str(uid))
        try:
            await ctx.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"{header('User Message')} 📩\n\n"
                    f"👤  {_b(name)}\n"
                    f"🆔  {_c(str(uid))}\n\n"
                    f"{DIV2}\n\n"
                    f"{esc(text)}\n\n"
                    f"{DIV2}\n"
                    f"  Reply karo: {_c(f'/reply {uid} <message>')}"
                ),
                parse_mode=PARSE,
            )
            await update.message.reply_text(
                f"{header('Message Sent')} ✅\n\n"
                f"  {_i('Tera message admin ko bhej diya.')}\n"
                f"  {_i('Jald hi reply milega!')}",
                parse_mode=PARSE,
            )
        except TelegramError as e:
            await update.message.reply_text(
                f"{header('Error')} ❌\n\n{_c(esc(str(e)))}",
                parse_mode=PARSE,
            )

# ──────────────────────────────────────────────
#  CALLBACK HANDLER
# ──────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split("|")
    action = parts[0]
    uid    = update.effective_user.id
    user   = update.effective_user

    # ── channel join check ──
    if action == "check_join":
        if await is_member(ctx.bot, uid):
            if uid not in sessions:
                sessions[uid] = UserSession()
            sessions[uid].name    = user.full_name or str(uid)
            sessions[uid].chat_id = update.effective_chat.id
            await query.edit_message_text(
                f"{header('Welcome')} 🎉\n\n"
                f"  {_i('Channel join ho gaya!')}\n\n"
                f"  Koi bhi button dabao 👇\n\n"
                f"{DIV2}",
                reply_markup=start_keyboard(uid),
                parse_mode=PARSE,
            )
        else:
            await query.answer("❌ Abhi join nahi kiya! Pehle join karo.", show_alert=True)
        return

    # ── START MENU BUTTONS ──────────────────────

    if action == "menu_new":
        uid2 = int(parts[1]) if len(parts) >= 2 else uid
        await query.edit_message_text(
            f"{header('Generating...')}\n\n⏳  {_i('Naya email aa raha hai...')}",
            parse_mode=PARSE,
        )
        sessions.setdefault(uid2, UserSession()).chat_id = update.effective_chat.id

        async def edit(text, markup):
            await query.edit_message_text(text, reply_markup=markup, parse_mode=PARSE)

        await _do_new_email(uid2, user, edit, edit)
        sessions[uid2].chat_id = update.effective_chat.id
        return

    if action == "menu_email":
        uid2 = int(parts[1]) if len(parts) >= 2 else uid
        if uid2 not in sessions or not sessions[uid2].email:
            await query.answer("❗ Pehle New Email banao.", show_alert=True)
            return
        await query.edit_message_text(
            f"{header('Current Email')}\n\n"
            f"  📧  {_c(esc(sessions[uid2].email))}\n\n"
            f"{DIV2}",
            reply_markup=main_keyboard(uid2),
            parse_mode=PARSE,
        )
        return

    if action == "menu_getmail":
        uid2 = int(parts[1]) if len(parts) >= 2 else uid
        if uid2 not in sessions or not sessions[uid2].email:
            await query.answer("❗ Pehle New Email banao.", show_alert=True)
            return
        if sessions[uid2].watching:
            await query.answer("📬 Pehle se chal rahi hai!", show_alert=True)
            return
        await query.edit_message_text(
            f"{header('Get Mail')} ⏳\n\n"
            f"  {_i('Thoda der wait kare...')}\n"
            f"  {_i('Jab mail aayega, main turant dikha dunga.')}\n\n"
            f"{DIV2}",
            parse_mode=PARSE,
        )
        sessions[uid2].watching = True
        ctx.application.create_task(
            _poll_loop(uid2, update.effective_chat.id, ctx.application.bot)
        )
        return

    if action == "menu_stop":
        uid2 = int(parts[1]) if len(parts) >= 2 else uid
        if uid2 in sessions and sessions[uid2].watching:
            sessions[uid2].watching = False
            await query.edit_message_text(
                f"{header('Stopped')} ⏹\n\n{_i('Mail monitoring band ho gayi.')}\n\n{DIV2}",
                reply_markup=start_keyboard(uid2),
                parse_mode=PARSE,
            )
        else:
            await query.answer("ℹ️ Monitoring chal nahi rahi thi.", show_alert=True)
        return

    if action == "menu_delete":
        uid2 = int(parts[1]) if len(parts) >= 2 else uid
        if uid2 in sessions:
            sessions[uid2].watching = False
            if sessions[uid2].http and not sessions[uid2].http.closed:
                await sessions[uid2].http.close()
            del sessions[uid2]
        await query.edit_message_text(
            f"{header('Deleted')} 🗑\n\n"
            f"  Session delete ho gaya.\n"
            f"  Naya banane ke liye {_b('New Email')} dabao.\n\n"
            f"{DIV2}",
            reply_markup=start_keyboard(uid2),
            parse_mode=PARSE,
        )
        return

    if action == "menu_admin":
        uid2 = int(parts[1]) if len(parts) >= 2 else uid
        pending_admin_msg[uid2] = True
        await query.edit_message_text(
            f"{header('Talk to Admin')} 💬\n\n"
            f"  {_i('Apna message type karo, admin tak pahuncha dunga.')}\n\n"
            f"  {_c('Cancel: /cancel')}",
            parse_mode=PARSE,
        )
        return

    # ── AFTER-EMAIL KEYBOARD BUTTONS ────────────

    if action == "getmail" and len(parts) >= 2:
        uid2 = int(parts[1])
        if uid2 not in sessions:
            await query.edit_message_text(
                f"{header('Session Expired')} ❌\n\n{_c('/new')} se banao.",
                parse_mode=PARSE,
            )
            return
        if sessions[uid2].watching:
            await query.answer("📬 Pehle se chal rahi hai!", show_alert=True)
            return
        await query.edit_message_text(
            f"{header('Get Mail')} ⏳\n\n"
            f"  {_i('Thoda der wait kare...')}\n"
            f"  {_i('Jab mail aayega, main turant dikha dunga.')}\n\n"
            f"{DIV2}",
            parse_mode=PARSE,
        )
        sessions[uid2].watching = True
        ctx.application.create_task(
            _poll_loop(uid2, update.effective_chat.id, ctx.application.bot)
        )
        return

    if action == "new" and len(parts) >= 2:
        uid2 = int(parts[1])
        await query.edit_message_text(
            f"{header('Generating...')}\n\n⏳  {_i('Naya email aa raha hai...')}",
            parse_mode=PARSE,
        )
        sessions.setdefault(uid2, UserSession()).chat_id = update.effective_chat.id

        async def edit(text, markup):
            await query.edit_message_text(text, reply_markup=markup, parse_mode=PARSE)

        await _do_new_email(uid2, user, edit, edit)
        sessions[uid2].chat_id = update.effective_chat.id
        return

    if action == "talkadmin" and len(parts) >= 2:
        uid2 = int(parts[1])
        pending_admin_msg[uid2] = True
        await query.edit_message_text(
            f"{header('Talk to Admin')} 💬\n\n"
            f"  {_i('Apna message type karo, admin tak pahuncha dunga.')}\n\n"
            f"  {_c('Cancel: /cancel')}",
            parse_mode=PARSE,
        )
        return

    if action == "getmail_again":
        if uid not in sessions or not sessions[uid].email:
            await query.edit_message_text(
                f"{header('No Session')} ❌\n\nPehle {_c('/new')} se email banao.",
                parse_mode=PARSE,
            )
            return
        if sessions[uid].watching:
            await query.answer("📬 Pehle se chal rahi hai!", show_alert=True)
            return
        await query.edit_message_text(
            f"{header('Get Mail')} ⏳\n\n"
            f"  {_i('Thoda der wait kare...')}\n"
            f"  {_i('Jab mail aayega, main turant dikha dunga.')}\n\n"
            f"{DIV2}",
            parse_mode=PARSE,
        )
        sessions[uid].watching = True
        ctx.application.create_task(
            _poll_loop(uid, update.effective_chat.id, ctx.application.bot)
        )
        return

    if action == "new_email_again":
        sessions.setdefault(uid, UserSession()).chat_id = update.effective_chat.id
        await query.edit_message_text(
            f"{header('Generating...')}\n\n⏳  {_i('Naya email aa raha hai...')}",
            parse_mode=PARSE,
        )

        async def edit(text, markup):
            await query.edit_message_text(text, reply_markup=markup, parse_mode=PARSE)

        await _do_new_email(uid, user, edit, edit)
        sessions[uid].chat_id = update.effective_chat.id
        return

# ──────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────

def main():
    print(
        "\n╔══════════════════════════════════════════╗\n"
        "║  ✦ MDX-MAIL BOT  v5.3  (INLINE MENU)   ║\n"
        "╚══════════════════════════════════════════╝\n"
    )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(20)
        .write_timeout(20)
        .pool_timeout(10)
        .build()
    )

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("new",      cmd_new))
    app.add_handler(CommandHandler("email",    cmd_email))
    app.add_handler(CommandHandler("getmail",  cmd_getmail))
    app.add_handler(CommandHandler("stop",     cmd_stop))
    app.add_handler(CommandHandler("delete",   cmd_delete))
    app.add_handler(CommandHandler("admin",    cmd_admin))
    app.add_handler(CommandHandler("cancel",   cmd_cancel))
    app.add_handler(CommandHandler("users",    cmd_users))
    app.add_handler(CommandHandler("reply",    cmd_reply))
    app.add_handler(CommandHandler("usermail", cmd_usermail))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🤖 Bot chal raha hai!  Ctrl+C se band karo.\n")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
