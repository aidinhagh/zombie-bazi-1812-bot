"""Shared state, identity and sending helpers for every Telegram module."""
import datetime
import logging
import os
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from .state import Store
from .texts import L, bi

logger = logging.getLogger("zombiebot")

TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Tehran"))
LOCK_HOUR = int(os.environ.get("LOCK_HOUR", "20"))
ENV_GMS = {int(x) for x in os.environ.get("GM_IDS", "").replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}
DICE_WAIT = 3.6  # seconds the Telegram dice animation takes

store = Store()


def G():
    return store.g


def save():
    store.save()


# ---------------- identity ----------------

def is_gm(uid):
    return uid is not None and (int(uid) in ENV_GMS or int(uid) in G()["gm_ids"])


def gm_ids():
    return sorted(set(ENV_GMS) | set(G()["gm_ids"]))


def pl(uid):
    if uid is None:
        return None
    return G()["players"].get(str(uid))


def playing_as(gm_uid):
    """The player a GM is currently controlling in the test lab, or None."""
    target = G().get("as", {}).get(str(gm_uid))
    return pl(target) if target else None


def acting_uid(uid):
    p = playing_as(uid) if is_gm(uid) else None
    return int(p["id"]) if p else uid


def is_fake(uid):
    p = pl(uid)
    return bool(p and p.get("fake"))


def chat_for(uid):
    """Where a player's private messages really go. Test players route to the GM playing them."""
    if not is_fake(uid):
        return int(uid)
    for gm, target in G().get("as", {}).items():
        if str(target) == str(uid):
            return int(gm)
    return None   # a test player nobody is playing: stay silent


def lang_of(uid):
    return "fa"   # Persian only


def name_of(uid):
    p = pl(uid)
    return p["name"] if p else str(uid)


# ---------------- keyboards & text ----------------

def _button(t, d):
    if d.startswith("webapp:"):
        from telegram import WebAppInfo
        return InlineKeyboardButton(t, web_app=WebAppInfo(d[len("webapp:"):]))
    return InlineKeyboardButton(t, callback_data=d)


def kb(rows):
    """Rows of (text, callback_data). callback_data "webapp:<url>" makes a Mini App button."""
    return InlineKeyboardMarkup([[_button(t, d) for t, d in row] for row in rows if row])


def chunks(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def grid(buttons, per_row=2):
    return chunks(buttons, per_row)


def split_text(text, limit=3800):
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            out.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out or ["—"]


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def num(n, lang="fa"):
    s = f"{n:g}" if isinstance(n, float) else str(n)
    return s.translate(_FA_DIGITS) if lang == "fa" else s


def now():
    return datetime.datetime.now(TZ)


def lock_eta(lang):
    """'until 20:00 (3h 10m)' for the current day."""
    n = now()
    lock = n.replace(hour=LOCK_HOUR, minute=0, second=0, microsecond=0)
    if n >= lock:
        return L(lang, f"ساعت {num(LOCK_HOUR)}:۰۰ گذشته", f"past {LOCK_HOUR}:00")
    mins = int((lock - n).total_seconds() // 60)
    h, m = divmod(mins, 60)
    return L(lang, f"تا ساعت {num(LOCK_HOUR)}:۰۰ ({num(h)} ساعت و {num(m)} دقیقه)", f"until {LOCK_HOUR}:00 ({h}h {m}m)")


def phase_label(lang, g=None):
    g = g or G()
    names = {"lobby": ("پیش از بازی", "Before the game"), "day": ("روز", "Day"), "night": ("شب", "Night")}
    fa, en = names[g["phase"]]
    if g["phase"] == "lobby":
        return L(lang, fa, en)
    return L(lang, f"{fa} {num(g['cycle'])}", f"{en} {g['cycle']}")


# ---------------- sending ----------------

def banner(uid):
    """Shown on top of a test player's messages so the GM always knows who they are."""
    p = pl(uid)
    if p and p.get("fake"):
        return L(lang_of(uid), f"🕹 به‌جای {p['name']}\n", f"🕹 as {p['name']}\n")
    return ""


async def dm(bot, uid, fa, en=None, **kw):
    text = fa
    chat = chat_for(uid)
    if chat is None:
        return None
    try:
        return await bot.send_message(chat, banner(uid) + text, **kw)
    except TelegramError as e:
        logger.warning("DM to %s failed: %s", uid, e)


async def dm_photo(bot, uid, photo, caption=None, **kw):
    chat = chat_for(uid)
    if chat is None:
        return None
    try:
        return await bot.send_photo(chat, photo, caption=caption, **kw)
    except TelegramError as e:
        logger.warning("photo to %s failed: %s", uid, e)


async def group(bot, fa, en, bypass=False, **kw):
    """Post in the game group. Unless it's part of the voting (bypass=True), it waits for the GM's approval."""
    gid = G()["group_id"]
    if not gid:
        return None
    from . import outbox
    return await outbox.post(bot, "text", bi(fa, en), reply_markup=kw.get("reply_markup"), bypass=bypass)


async def to_gms(bot, text, reply_markup=None):
    parts = split_text(text)
    for uid in gm_ids():
        for i, part in enumerate(parts):
            try:
                await bot.send_message(uid, part, reply_markup=reply_markup if i == len(parts) - 1 else None)
            except TelegramError as e:
                logger.warning("GM DM failed: %s", e)


async def gm_notes(bot, notes):
    """notes: list of (fa, en); each GM gets their own language."""
    if not notes:
        return
    for uid in gm_ids():
        lang = lang_of(uid)
        text = "\n".join("• " + (fa if lang == "fa" else en) for fa, en in notes)
        for part in split_text(text):
            try:
                await bot.send_message(uid, part)
            except TelegramError:
                pass


async def edit_or_send(q, text, rows=None):
    """Edit the menu message in place; if that's impossible (e.g. it's a photo), send a new one."""
    markup = kb(rows) if rows else None
    try:
        await q.edit_message_text(text, reply_markup=markup)
    except TelegramError as e:
        if "not modified" in str(e).lower():
            return
        await q.message.reply_text(text, reply_markup=markup)
