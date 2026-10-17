"""Every message the bot wants to post in the group waits for the GM's approval first
(except the voting itself: #رای posts, tallies, the vote result and the judge's case).

The GM gets a preview with ✅ / ❌ buttons; pictures and animations are kept on the data volume until then."""
import io
import os
import time

from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError

from .common import G, save, store, gm_ids, kb, logger


def enabled(g=None):
    return (g or G()).get("approve_group", True)


def _dir():
    d = os.path.join(os.path.dirname(store.path), "outbox")
    os.makedirs(d, exist_ok=True)
    return d


def pending(g=None):
    return [m for m in (g or G()).setdefault("outbox", []) if m["status"] == "waiting"]


async def _deliver(bot, m):
    """Actually post one message to the group (or channel)."""
    g = G()
    chat = m.get("chat") or g["group_id"]
    if not chat:
        return None
    markup = InlineKeyboardMarkup.de_json(m["markup"], bot) if m.get("markup") else None
    try:
        if m["kind"] == "text":
            return await bot.send_message(chat, m["text"], reply_markup=markup)
        with open(m["file"], "rb") as f:
            data = f.read()
        if m["kind"] == "photo":
            return await bot.send_photo(chat, io.BytesIO(data), caption=m.get("text") or None, reply_markup=markup)
        return await bot.send_animation(chat, animation=io.BytesIO(data), filename=m.get("filename") or "result.gif",
                                        caption=m.get("text") or None, reply_markup=markup)
    except (TelegramError, OSError) as e:
        logger.warning("group post failed: %s", e)
    return None


def _rows(m, n_wait):
    rows = [[("✅ ارسال در گروه", f"g:ob:{m['id']}:1"), ("❌ ارسال نشود", f"g:ob:{m['id']}:0")]]
    if n_wait > 1:
        rows.append([(f"✅ ارسال همه ({n_wait})", "g:oball")])
    return rows


async def post(bot, kind="text", text="", data=None, filename=None, reply_markup=None, chat=None, bypass=False):
    """Queue a group post for the GM (or send it straight away when approval is off or it's voting)."""
    g = G()
    m = {"kind": kind, "text": text or "", "filename": filename, "chat": chat,
         "markup": reply_markup.to_dict() if reply_markup is not None else None}
    if data is not None:
        m["file"] = None
    if bypass or not enabled(g):
        if data is not None:
            m["file"] = os.path.join(_dir(), f"direct-{time.time():.0f}.bin")
            with open(m["file"], "wb") as f:
                f.write(data)
        res = await _deliver(bot, m)
        if m.get("file"):
            try:
                os.remove(m["file"])
            except OSError:
                pass
        return res
    g.setdefault("ob_seq", 0)
    g["ob_seq"] += 1
    m["id"] = f"o{g['ob_seq']}"
    m["status"] = "waiting"
    m["at"] = time.time()
    if data is not None:
        m["file"] = os.path.join(_dir(), m["id"] + ".bin")
        with open(m["file"], "wb") as f:
            f.write(data)
    g.setdefault("outbox", []).append(m)
    g["outbox"] = [x for x in g["outbox"] if x["status"] == "waiting"] + [x for x in g["outbox"] if x["status"] != "waiting"][-50:]
    save()
    n = len(pending(g))
    head = "📨 پیام ربات برای گروه — منتظر تأیید تو:\n\n"
    for uid in gm_ids():
        try:
            if kind == "text":
                await bot.send_message(uid, head + m["text"], reply_markup=kb(_rows(m, n)))
            elif kind == "photo":
                await bot.send_photo(uid, io.BytesIO(data), caption=(head + m["text"])[:1000], reply_markup=kb(_rows(m, n)))
            else:
                await bot.send_animation(uid, animation=io.BytesIO(data), filename=filename or "result.gif",
                                         caption=(head + m["text"])[:1000], reply_markup=kb(_rows(m, n)))
        except TelegramError as e:
            logger.warning("outbox preview failed: %s", e)
    return None


async def decide(bot, mid, yes):
    """GM pressed ✅ or ❌ on a preview. Returns a short status line."""
    g = G()
    m = next((x for x in g.get("outbox", []) if x["id"] == mid), None)
    if not m or m["status"] != "waiting":
        return "این پیام قبلاً بررسی شده."
    m["status"] = "sent" if yes else "dropped"
    save()
    if yes:
        await _deliver(bot, m)
    if m.get("file"):
        try:
            os.remove(m["file"])
        except OSError:
            pass
    return "✅ در گروه ارسال شد." if yes else "❌ ارسال نشد."


async def approve_all(bot):
    n = 0
    for m in list(pending()):
        await decide(bot, m["id"], True)
        n += 1
    return n
