"""Day votes, ported from the ZombieVote bot.

  #رای <name>   in the group — vote for someone (Persian, English, nickname or reply)
  #رایگیری      in the group — the running tally

One vote per player per day: the first one counts. A vote for someone the hotel
protects is struck by lightning and doesn't count (and doesn't use up the vote);
if the hotel has been bombed, those votes count by the destroyed percentage.
"""
import asyncio
import io
import re
import time
from collections import OrderedDict

from telegram import MessageEntity
from telegram.error import RetryAfter, TelegramError

from . import actions, matching
from .animator import make_gif
from .common import G, save, pl, is_gm, acting_uid, lang_of, num, logger, group
from .matching import Candidate, best_match
from .state import alive_players, roster
from .texts import L, bi

TALLY = re.compile(r"#\s*(?:رای|رأی|راي)[\s‌_]*گیری", re.UNICODE)
TRIGGER = re.compile(r"#\s*(?:رای|رأی|راي)(?![؀-ۿ‌])[\s_:.\-،]*(.*)", re.UNICODE)
MAX_CHARS = 24
MAX_MESSAGE_AGE = 120.0
TALLY_COOLDOWN = 15.0
MEDALS = ["🥇", "🥈", "🥉"]

_gif_cache = OrderedDict()
_photo_cache = {}
_render_slots = asyncio.Semaphore(2)
_seen = OrderedDict()
_last_tally = {}


# ---------------- matching ----------------

def candidates(include_dead=True):
    """Every player with a role, under their name, @username and GM-given nicknames."""
    out = []
    for p in G()["players"].values():
        if not p.get("role") or (not include_dead and not p["alive"]):
            continue
        out.append(Candidate(int(p["id"]), p["name"], "", p.get("username") or "", 0))
        for nick in p.get("nicks", []):
            out.append(Candidate(int(p["id"]), nick, "", "", 0))
    return out


def find(query):
    """(player, score) for a written name, or (None, score)."""
    cand, score = best_match(query, candidates())
    return (pl(cand.user_id) if cand else None), score


def extract_word(text):
    m = TRIGGER.search(text)
    if not m:
        return None
    tail = m.group(1).split("\n")[0]
    tail = re.sub(r"#\S+", " ", tail)
    return re.sub(r"\s+", " ", tail).strip()[:MAX_CHARS].strip()


def is_stale(message):
    if getattr(message, "edit_date", None) is not None:
        return True
    if getattr(message, "forward_origin", None) is not None:
        return True
    if getattr(message, "date", None) is not None and time.time() - message.date.timestamp() > MAX_MESSAGE_AGE:
        return True
    key = (message.chat_id, message.message_id)
    if key in _seen:
        return True
    _seen[key] = time.time()
    if len(_seen) > 400:
        _seen.popitem(last=False)
    return False


# ---------------- recording ----------------

def hotel_pct():
    return G()["loc_damage"].get("barcelona", 0)


def cast(voter, target):
    """Record a vote. Returns (status, extra):
    ok | lightning | already (extra = earlier target) | dead_voter | dead_target | not_day | cancelled | self"""
    g = G()
    if g["phase"] != "day":
        return "not_day", None
    if g.get("vote_cancelled"):
        return "cancelled", None
    if not voter["alive"]:
        return "dead_voter", None
    if not target["alive"]:
        return "dead_target", None
    prev = g["votes"].get(str(voter["id"]))
    if prev:
        return "already", pl(prev)
    if target["flags"].get("hotel_immune") and hotel_pct() == 0:
        g.setdefault("vote_log", []).append({"voter": str(voter["id"]), "target": str(target["id"]), "counted": False,
                                             "why": "hotel", "cycle": g["cycle"], "t": time.time()})
        save()
        return "lightning", None
    g["votes"][str(voter["id"])] = str(target["id"])
    g.setdefault("vote_log", []).append({"voter": str(voter["id"]), "target": str(target["id"]), "counted": True,
                                         "cycle": g["cycle"], "t": time.time()})
    save()
    return "ok", None


def caption_for(status, voter, target, extra):
    w = actions.vote_weight(G(), voter)
    if status == "ok":
        wf = f" (وزن {num(w)})" if w != 1 else ""
        we = f" (weight {w})" if w != 1 else ""
        note_fa = note_en = ""
        if target["flags"].get("hotel_immune"):
            note_fa = f"\n🏨 در هتل — {num(hotel_pct())}٪ حساب می‌شود"
            note_en = f"\n🏨 in the hotel — counts {hotel_pct()}%"
        return bi(f"«{target['name']}» — رأی {voter['name']} ثبت شد ✅{wf}{note_fa}",
                  f"«{target['name']}» — {voter['name']}'s vote is recorded ✅{we}{note_en}")
    if status == "lightning":
        return bi(f"⚡️ رأی {voter['name']} به «{target['name']}» صاعقه زد و باطل شد — او در هتل است.",
                  f"⚡️ {voter['name']}'s vote for «{target['name']}» was struck by lightning — they're in the hotel.")
    if status == "already":
        return bi(f"«{target['name']}» — ولی رأی امروز {voter['name']} به «{extra['name']}» ثبت شده و این یکی شمرده نشد ⛔️",
                  f"«{target['name']}» — but {voter['name']} already voted for «{extra['name']}» today; this one doesn't count ⛔️")
    return None


REFUSALS = {
    "not_day": ("رأی‌گیری فقط در روز است. 🌙", "Voting happens only during the day. 🌙"),
    "cancelled": ("قاضی رأی‌گیری امروز را لغو کرده. ⚖️", "The judge cancelled today's vote. ⚖️"),
    "dead_voter": ("مرده‌ها رأی نمی‌دهند. ⚰️", "The dead don't vote. ⚰️"),
}


# ---------------- GIF ----------------

async def fetch_photo(bot, uid):
    p = pl(uid)
    if not p or p.get("fake"):
        return None
    if uid in _photo_cache and time.time() - _photo_cache[uid][0] < 6 * 3600:
        return _photo_cache[uid][1]
    data = None
    try:
        photos = await bot.get_user_profile_photos(int(uid), limit=1)
        if photos.total_count and photos.photos:
            f = await bot.get_file(photos.photos[0][-1].file_id)
            data = bytes(await f.download_as_bytearray())
    except Exception as e:
        logger.info("avatar for %s unavailable: %s", uid, e)
    _photo_cache[uid] = (time.time(), data)
    return data


async def render_gif(label, photo_key, photo, lightning):
    key = f"{label}|{photo_key}|{int(lightning)}"
    if key in _gif_cache:
        _gif_cache.move_to_end(key)
        return _gif_cache[key]
    async with _render_slots:
        data = await asyncio.to_thread(make_gif, label, None, photo, lightning)
    _gif_cache[key] = data
    if len(_gif_cache) > 40:
        _gif_cache.popitem(last=False)
    return data


_file_ids = {}   # rendered GIF -> Telegram file_id, so each animation is uploaded once


async def announce(bot, chat_id, status, voter, target, extra, reply_to=None, gif=True, header=""):
    """Post the vote result as ONE message: the sand-and-blood GIF (or lightning) with a caption, or a text line.
    Group sends are limited (~20 a minute), so a vote never costs more than one message."""
    caption = caption_for(status, voter, target, extra)
    if caption is None:
        return
    caption = header + caption
    if not gif:
        await bot.send_message(chat_id, "🗳 " + caption, reply_to_message_id=reply_to)
        return
    photo = await fetch_photo(bot, target["id"])
    key = f"{target['name'][:MAX_CHARS]}|{target['id'] if photo else '-'}|{int(status == 'lightning')}"
    if key in _file_ids:
        await bot.send_animation(chat_id, animation=_file_ids[key], caption=caption, reply_to_message_id=reply_to)
        return
    data = await render_gif(target["name"][:MAX_CHARS], str(target["id"]) if photo else "-", photo, status == "lightning")
    msg = await bot.send_animation(chat_id, animation=io.BytesIO(data), filename="vote.gif", caption=caption,
                                   reply_to_message_id=reply_to)
    anim = getattr(msg, "animation", None) or getattr(msg, "document", None)
    if getattr(anim, "file_id", None):
        _file_ids[key] = anim.file_id


# ---------------- group handler ----------------

async def on_group_text(update, ctx):
    message = update.effective_message
    if not message or not message.from_user:
        return
    text = message.text or message.caption or ""
    if not (TALLY.search(text) or TRIGGER.search(text)):
        return
    if is_stale(message):
        return
    g = G()
    if g["group_id"] and message.chat_id != g["group_id"]:
        return
    if TALLY.search(text):
        now = time.monotonic()
        if now - _last_tally.get(message.chat_id, 0) < TALLY_COOLDOWN:
            return
        _last_tally[message.chat_id] = now
        await message.reply_text(tally_text("fa") + "\n\n" + tally_text("en", short=True))
        return
    real = message.from_user.id
    voter = pl(acting_uid(real))
    if not voter or not voter.get("role"):
        if not is_gm(real):
            await message.reply_text(bi("فقط بازیکن‌ها رأی می‌دهند.", "Only players can vote."))
        else:
            await message.reply_text(bi("گاد رأی نمی‌دهد. برای تست، از آزمایشگاه به‌جای یک بازیکن بازی کن.",
                                        "The GM doesn't vote. To test, play as someone from the test lab."))
        return
    target, score = None, 0
    for ent in message.entities or []:
        if ent.type == MessageEntity.TEXT_MENTION and ent.user and pl(ent.user.id):
            target = pl(ent.user.id)
    query = extract_word(text)
    if not target and query:
        target, score = find(query)
    if not target and message.reply_to_message and message.reply_to_message.from_user:
        target = pl(message.reply_to_message.from_user.id)
    if not target:
        await message.reply_text(bi(f"«{query}» را بین بازیکن‌ها پیدا نکردم. 🤔", f"Couldn't find «{query}» among the players. 🤔"))
        return
    status, extra = cast(voter, target)
    if status in REFUSALS:
        await message.reply_text(bi(*REFUSALS[status]))
        return
    if status == "dead_target":
        await message.reply_text(bi(f"«{target['name']}» از بازی خارج شده. ⚰️", f"«{target['name']}» is out of the game. ⚰️"))
        return
    try:
        await announce(ctx.bot, message.chat_id, status, voter, target, extra, reply_to=message.message_id)
    except Exception:
        logger.exception("vote animation failed")
        await message.reply_text(caption_for(status, voter, target, extra))


async def vote_from_menu(bot, voter, target, gif=True):
    """A vote cast from the private menu (or by a test player) is posted in the group like a #رای message —
    as a single message. If Telegram says to slow down, the vote still counts; only the post is skipped."""
    status, extra = cast(voter, target)
    gid = G()["group_id"]
    if status in ("ok", "lightning", "already") and gid:
        header = f"{voter['name']}: #رای {target['name']}\n"
        try:
            await announce(bot, gid, status, voter, target, extra, gif=gif, header=header)
        except RetryAfter as e:
            logger.warning("group flood control (%ss): vote by %s counted but not posted", e.retry_after, voter["name"])
        except TelegramError:
            logger.exception("vote post failed")
    return status, extra


# ---------------- tally ----------------

def tally_text(lang, short=False):
    g = G()
    ranked, notes = actions.tally(g)
    voters = [v for v, t in g["votes"].items() if t and pl(v) and pl(v)["alive"]]
    alive = [p for p in alive_players(g)]
    if g.get("vote_cancelled"):
        head = L(lang, "⚖️ رأی‌گیری امروز لغو شده.", "⚖️ Today's vote was cancelled.")
    else:
        head = L(lang, f"🗳 نتیجه رأی‌گیری روز {num(g['cycle'])}", f"🗳 Day {g['cycle']} vote")
    if not ranked:
        return head + "\n" + L(lang, "هنوز رأیی ثبت نشده.", "No votes yet.")
    lines = [head, ""]
    for i, (pid, v) in enumerate(ranked[:10]):
        rank = MEDALS[i] if i < 3 else f"{num(i + 1, lang)}."
        votes_word = L(lang, "رأی", "votes")
        lines.append(f"{rank} {pl(pid)['name']} — {num(round(v, 2), lang)} {votes_word}")
    if short:
        return "\n".join(lines)
    lines.append("")
    lines.append(L(lang, f"{num(len(voters))} از {num(len(alive))} نفر رأی داده‌اند.",
                   f"{len(voters)} of {len(alive)} have voted."))
    lines += [n[0 if lang == "fa" else 1] for n in notes]
    return "\n".join(lines)


def not_voted():
    g = G()
    return [p for p in alive_players(g) if not g["votes"].get(str(p["id"]))]


def delete_votes(voter_id=None, target_id=None, everything=False):
    g = G()
    n = 0
    for v, t in list(g["votes"].items()):
        if everything or (voter_id and v == str(voter_id)) or (target_id and t == str(target_id)):
            g["votes"].pop(v)
            n += 1
    save()
    return n


async def cmd_delete(update, ctx):
    """/delete <name> | /delete all | /delete as a reply — GM only, like the ZombieVote bot."""
    message = update.effective_message
    if not is_gm(message.from_user.id):
        return
    q = " ".join(ctx.args or [])
    if q.lower() in ("all", "همه"):
        n = delete_votes(everything=True)
        await message.reply_text(bi(f"همه {num(n)} رأی امروز پاک شد. 🧹", f"All {n} votes today were cleared. 🧹"))
        return
    if message.reply_to_message and not q:
        p = pl(acting_uid(message.reply_to_message.from_user.id))
        n = delete_votes(voter_id=p["id"]) if p else 0
        await message.reply_text(bi(f"رأی {p['name'] if p else '?'} حذف شد ({num(n)}) — می‌تواند دوباره رأی بدهد. ✅",
                                    f"{p['name'] if p else '?'}'s vote removed ({n}) — they can vote again. ✅"))
        return
    if not q:
        await message.reply_text("/delete <name> — votes FOR someone\n/delete (reply) — someone's OWN vote\n/delete all")
        return
    target, _ = find(q)
    if not target:
        await message.reply_text(bi(f"«{q}» پیدا نشد.", f"«{q}» not found."))
        return
    n = delete_votes(target_id=target["id"])
    await message.reply_text(bi(f"{num(n)} رأی داده‌شده به «{target['name']}» حذف شد. 🗑", f"{n} votes for «{target['name']}» removed. 🗑"))
