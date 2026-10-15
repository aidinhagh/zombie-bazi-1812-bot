"""Telegram glue for the Zombie Bazi 1812 GM bot."""
import datetime
import logging
import os
import random
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from . import actions, board
from .actions import GameError
from .board import SQUARES, CITIES
from .data.items import ITEMS
from .data.locations import LOCATIONS, POWER_PRICES, UNIT_PRICES
from .data.roles import ROLES, SPECIALS, ZOMBIE, HUMAN, role_name
from .engine import resolve_night, loc_of
from .render import render
from .state import Store, new_game, new_player, assign_role, find_player, roster, alive_players, team, log
from .texts import L, bi, btn, act_name, stat_name, unit_name, item_line, role_card, status_text, help_text, GM_HELP

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("zombiebot")
# httpx logs every request URL, and Telegram URLs contain the bot token
for noisy in ("httpx", "httpcore", "apscheduler"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

store = Store()
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Tehran"))
LOCK_HOUR = int(os.environ.get("LOCK_HOUR", "20"))
VOTES_PUBLIC = os.environ.get("VOTES_PUBLIC", "1") == "1"
ENV_GMS = {int(x) for x in os.environ.get("GM_IDS", "").replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}
DICE_WAIT = 3.6  # seconds the Telegram dice animation takes


def G():
    return store.g


def save():
    store.save()


# ---------------- identity & language ----------------

def is_gm(uid):
    return uid in ENV_GMS or uid in G()["gm_ids"]


def pl(uid):
    if uid is None:
        return None
    return G()["players"].get(str(uid))


def acting_uid(uid):
    """A GM using /as plays as another player; everyone else is themselves."""
    if is_gm(uid):
        target = G().get("as", {}).get(str(uid))
        if target and pl(target):
            return int(target)
    return uid


def is_fake(uid):
    p = pl(uid)
    return bool(p and p.get("fake"))


def chat_for(uid):
    """Where messages for this player really go. Fake test players route to the GM playing them."""
    if not is_fake(uid):
        return int(uid)
    for gm, target in G().get("as", {}).items():
        if str(target) == str(uid):
            return int(gm)
    gms = sorted(set(ENV_GMS) | set(G()["gm_ids"]))
    return gms[0] if gms else None


def lang_of(uid):
    p = pl(uid)
    if p:
        return p.get("lang", "fa")
    return G().setdefault("gm_lang", {}).get(str(uid), "fa")


def kb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows if row])


def chunks(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def split_text(text, limit=3800):
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out


# ---------------- sending ----------------

async def dm(bot, uid, fa, en=None, **kw):
    lang = lang_of(uid)
    text = fa if (lang == "fa" or en is None) else en
    chat = chat_for(uid)
    if chat is None:
        return None
    if is_fake(uid):
        text = f"[→ {pl(uid)['name']}] " + text
    try:
        return await bot.send_message(chat, text, **kw)
    except TelegramError as e:
        logger.warning("DM to %s failed: %s", uid, e)


async def group(bot, fa, en, **kw):
    gid = G()["group_id"]
    if not gid:
        return None
    try:
        return await bot.send_message(gid, bi(fa, en), **kw)
    except TelegramError as e:
        logger.warning("group post failed: %s", e)


async def to_gms(bot, text, reply_markup=None):
    parts = split_text(text)
    for uid in set(ENV_GMS) | set(G()["gm_ids"]):
        for i, part in enumerate(parts):
            try:
                await bot.send_message(uid, part, reply_markup=reply_markup if i == len(parts) - 1 else None)
            except TelegramError as e:
                logger.warning("GM DM failed: %s", e)


async def gm_notes(bot, notes):
    """notes: list of (fa, en); each GM gets their own language."""
    if not notes:
        return
    for uid in set(ENV_GMS) | set(G()["gm_ids"]):
        lang = lang_of(uid)
        text = "\n".join("• " + (fa if lang == "fa" else en) for fa, en in notes)
        for part in split_text(text):
            try:
                await bot.send_message(uid, part)
            except TelegramError:
                pass


async def send_outbox(bot, out):
    for msg in out:
        kind = msg[0]
        if kind == "private":
            await dm(bot, msg[1], msg[2], msg[3])
        elif kind == "team":
            for p in alive_players(G()):
                if team(p) == msg[1]:
                    await dm(bot, p["id"], msg[2], msg[3])
        elif kind == "group":
            await group(bot, msg[1], msg[2])
        elif kind == "death":
            await announce_death(bot, pl(msg[1]))
        elif kind == "bomb":
            await post_bomb(bot, msg[1])
        elif kind == "poison":
            await post_poison(bot, msg[1])
        elif kind == "duel":
            await start_duel(bot, msg[1])


async def announce_death(bot, P):
    fa, en = actions.death_announcement(P)
    await group(bot, fa, en)
    await dm(bot, P["id"], "☠️ شما مُردید.", "☠️ You have died.")


async def check_win(bot):
    res = actions.winner_check(G())
    if res:
        await gm_notes(bot, [("🏆 بررسی برد:", "🏆 Win check:")] + res)


# ---------------- player menu ----------------

def main_menu(p, lang):
    g = G()
    rows = [
        [(btn("status", lang), "st"), (btn("move", lang), "mv")],
        [(btn("darts", lang), "dt"), (btn("items", lang), "it")],
        [(btn("shop", lang), "sp"), (btn("units", lang), "un")],
    ]
    if g["phase"] == "night":
        rows.append([(btn("act", lang), "ac")])
    if g["phase"] == "day":
        rows.append([(btn("vote", lang), "vt")])
    if p.get("role") == "clown":
        rows.append([(L(lang, "🎭 جواب جاسوسی امشب", "🎭 Tonight's spy answer"), "cd")])
    if p.get("role") == "godfather":
        rows.append([(L(lang, "🃏 نقش جعلی", "🃏 Fake role"), "fk")])
    rows.append([(btn("lang", lang), "lg")])
    return kb(rows)


def back_row(lang):
    return [(btn("back", lang), "m")]


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    u = update.effective_user
    g = G()
    if is_gm(u.id) and not ctx.args and not g.get("as", {}).get(str(u.id)):
        stale = pl(u.id)
        if stale and not stale.get("role"):
            g["players"].pop(str(u.id), None)   # GM registered before becoming GM; not a player
            save()
        if not pl(u.id):
            await update.message.reply_text(gm_header() + "\n\n/help · " + L(lang_of(u.id), "برای بازی کردن به‌عنوان بازیکن: /start play",
                                                                                    "To join as a player too: /start play"),
                                            reply_markup=gm_panel_kb())
            return
    p = pl(u.id)
    if not p:
        p = new_player(u.id, u.full_name, u.username)
        g["players"][str(u.id)] = p
        save()
        await to_gms(ctx.bot, f"➕ New player: {u.full_name} (@{u.username}) id {u.id}")
        await update.message.reply_text(bi(
            "👋 به زامبی‌بازی ۱۸۱۲ خوش اومدی! ثبت‌نام شدی؛ گاد نقشت رو می‌فرسته.\nبرای انگلیسی /lang",
            "👋 Welcome to Zombie Bazi 1812! You're registered; the GM will send your role.\nFor Persian /lang"))
        return
    lang = p["lang"]
    await update.message.reply_text(status_text(g, p, lang), reply_markup=main_menu(p, lang) if p["role"] else None)


async def cmd_menu(update: Update, ctx):
    if update.effective_chat.type != "private":
        return

    uid = update.effective_user.id
    p = pl(acting_uid(uid))
    if is_gm(uid) and (not p or not p["role"]):
        await update.message.reply_text(gm_header(), reply_markup=gm_panel_kb())
        return
    if not p or not p["role"]:
        await update.message.reply_text(bi("اول /start بزن و منتظر نقش بمون.", "Send /start first and wait for your role."))
        return
    await update.message.reply_text(status_text(G(), p, p["lang"]), reply_markup=main_menu(p, p["lang"]))


async def cmd_lang(update: Update, ctx):
    uid = update.effective_user.id
    p = pl(uid)
    if p:
        p["lang"] = "en" if p["lang"] == "fa" else "fa"
        new = p["lang"]
    else:
        gl = G().setdefault("gm_lang", {})
        new = gl[str(uid)] = "en" if gl.get(str(uid), "fa") == "fa" else "fa"
    save()
    await update.message.reply_text(L(new, "زبان: فارسی", "Language: English"))


async def cmd_help(update: Update, ctx):
    uid = update.effective_user.id
    text = help_text(lang_of(uid))
    if is_gm(uid):
        text += "\n\n" + GM_HELP
    await update.message.reply_text(text)


async def cmd_status(update: Update, ctx):
    p = pl(acting_uid(update.effective_user.id))
    if p:
        await update.message.reply_text(status_text(G(), p, p["lang"]))


# ---------------- callbacks: player side ----------------

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    uid = q.from_user.id
    try:
        if data.startswith("g") and data[:2] in ("ge", "gx", "gw", "gf", "gd") or data in GM_BUTTONS:
            if not is_gm(uid):
                await q.answer("GM only", show_alert=True)
                return
            await q.answer()
            await gm_button(update, ctx, data)
            return
        if data.startswith(("bw:", "an:", "rp:", "ba:", "yk:")):
            await q.answer()
            await shared_button(update, ctx, data)
            return
        await q.answer()
        p = pl(acting_uid(uid))
        if not p or not p.get("role"):
            await q.edit_message_text(bi("نقشی نداری.", "You have no role."))
            return
        await player_button(update, ctx, p, data)
    except GameError as e:
        await q.answer(e.text(lang_of(uid)), show_alert=True)
    except TelegramError as e:
        logger.info("telegram error on button %s: %s", data, e)


async def edit(q, text, rows=None):
    try:
        await q.edit_message_text(text, reply_markup=kb(rows) if rows else None)
    except TelegramError:
        await q.message.reply_text(text, reply_markup=kb(rows) if rows else None)


def alive_targets(p, include_self=False):
    return [x for x in roster(G()) if x["alive"] and x["role"] and (include_self or x["id"] != p["id"])]


def target_rows(prefix, players, lang, back="m"):
    rows = [[(x["name"][:28], f"{prefix}:{x['id']}")] for x in players]
    rows = [sum(pair, []) for pair in chunks(rows, 2)]
    rows.append([(btn("back", lang), back)])
    return rows


async def player_button(update, ctx, p, data):
    q = update.callback_query
    g = G()
    lang = p["lang"]
    parts = data.split(":")
    head = parts[0]

    if head == "m":
        await q.edit_message_text(status_text(g, p, lang), reply_markup=main_menu(p, lang))
        return
    if head == "st":
        await edit(q, status_text(g, p, lang), [back_row(lang)])
        return
    if head == "lg":
        p["lang"] = "en" if lang == "fa" else "fa"
        save()
        lang = p["lang"]
        await q.edit_message_text(status_text(g, p, lang), reply_markup=main_menu(p, lang))
        return

    if not p["alive"] and head not in ("st",):
        await edit(q, L(lang, "شما مرده‌اید.", "You are dead."))
        return

    # ----- movement -----
    if head == "mv":
        if g["phase"] == "lobby":
            raise GameError("بازی هنوز شروع نشده.", "The game hasn't started yet.")
        if g["locked"]:
            extra = L(lang, " (در لندن: /taxi)", " (in London: /taxi)") if p.get("night_pos") == "london" else ""
            raise GameError("نقشه تا فاز بعد قفل است." + extra, "The map is locked until the next phase." + extra)
        if p["moved"]:
            raise GameError("در این فاز حرکت کردی.", "You've already moved this phase.")
        if p["pos"] is None or p["flags"].get("free_move"):
            rows = [[(LOCATIONS[c][lang], f"mt:{c}")] for c in CITIES]
            await edit(q, L(lang, "یک شهر انتخاب کن:", "Pick a city:"), rows + [back_row(lang)])
            return
        if p["move_roll"] is None:
            msg = await ctx.bot.send_dice(chat_for(p["id"]), emoji="🎲")
            p["move_roll"] = msg.dice.value
            save()
            ctx.job_queue.run_once(job_move_options, DICE_WAIT, data=p["id"])
            await edit(q, L(lang, "🎲 تاس ریخته شد…", "🎲 Rolling…"))
            return
        await show_move_options(ctx.bot, p, q)
        return
    if head == "mt":
        dest = parts[1]
        if g["locked"] or p["moved"]:
            raise GameError("الان نمی‌تونی حرکت کنی.", "You can't move now.")
        opts = actions.move_options(g, p, p["move_roll"] or 0)
        if dest not in opts:
            raise GameError("این مقصد در دسترس نیست.", "That destination is out of reach.")
        notes = actions.do_move(g, p, dest, opts[dest])
        save()
        for pid, fa, en in notes:
            await dm(ctx.bot, pid, fa, en)
        if p["hp"] <= 0:
            await gm_notes(ctx.bot, [(f"{p['name']} با عوارض به اچ‌پی {p['hp']} رسید.", f"{p['name']} dropped to {p['hp']} hp from tolls.")])
        await edit(q, L(lang, f"📍 رسیدی به {board.square_name(dest)}", f"📍 You arrived at {board.square_name(dest,'en')}") +
                   ("\nℹ️ " + LOCATIONS[dest]["desc_" + lang] if dest in LOCATIONS else ""), [back_row(lang)])
        return

    # ----- darts -----
    if head == "dt":
        if g["phase"] == "lobby":
            raise GameError("بازی هنوز شروع نشده.", "The game hasn't started yet.")
        rows = []
        if not p["darts"]["money"]:
            rows.append([(L(lang, "🎯 دارت پول", "🎯 Money dart"), "dm")])
        if not p["darts"]["item"]:
            rows.append([(L(lang, f"🎯 دارت آیتم (قدرت {actions.item_power(g, p)})", f"🎯 Item dart (power {actions.item_power(g, p)})"), "di")])
        if not rows:
            raise GameError("دارت‌های این فاز رو انداختی.", "You've thrown this phase's darts.")
        await edit(q, L(lang, "کدوم دارت؟ (دارت پول: ۰ تا ۵ سکه. دارت آیتم: با قدرت N، از حلقه 7−N به داخل برنده‌ای.)",
                        "Which dart? (Money: 0–5 coins. Item: with power N you win on ring 7−N or closer.)"), rows + [back_row(lang)])
        return
    if head in ("dm", "di"):
        kind = "money" if head == "dm" else "item"
        if p["darts"][kind]:
            raise GameError("این دارت رو انداختی.", "Already thrown.")
        msg = await ctx.bot.send_dice(chat_for(p["id"]), emoji="🎯")
        v = msg.dice.value
        if kind == "money":
            coins = actions.money_dart(g, p, v)
            res = (f"🎯 {coins} سکه گرفتی! (کل: {p['coins']})", f"🎯 You won {coins} coins! (total {p['coins']})")
        else:
            power = actions.item_power(g, p)
            it = actions.item_dart(g, p, v)
            if it:
                res = (f"🎯 آیتم گرفتی: {item_line(it,'fa')}", f"🎯 You found: {item_line(it,'en')}")
            else:
                res = (f"🎯 چیزی پیدا نکردی (قدرت {power}، لازم: {max(2, 7-power)}+).", f"🎯 Nothing found (power {power}, needed {max(2, 7-power)}+).")
        save()
        ctx.job_queue.run_once(job_dm, DICE_WAIT, data=(p["id"], *res))
        await edit(q, L(lang, "🎯 پرتاب شد…", "🎯 Thrown…"), [back_row(lang)])
        return

    # ----- shop -----
    if head == "sp":
        await edit(q, *shop_view(p, lang))
        return
    if head == "bp":
        cost = actions.buy_power(g, p, parts[1])
        save()
        await q.answer(L(lang, f"−{cost} سکه", f"−{cost} coins"))
        await edit(q, *shop_view(p, lang))
        return
    if head == "bu":
        cost = actions.buy_unit(g, p, parts[1])
        save()
        await edit(q, *shop_view(p, lang))
        return

    # ----- items -----
    if head == "it":
        if not p["items"]:
            await edit(q, L(lang, "آیتمی نداری.", "You have no items."), [back_row(lang)])
            return
        rows = [[(ITEMS[k][lang][:30], f"iu:{k}")] for k in dict.fromkeys(p["items"])]
        text = "\n".join("• " + item_line(k, lang) for k in p["items"])
        await edit(q, L(lang, "آیتم‌هایت (برای استفاده بزن):\n", "Your items (tap to use):\n") + text, rows + [back_row(lang)])
        return
    if head == "iu":
        actions.use_item(g, p, parts[1])
        save()
        await edit(q, L(lang, f"✅ استفاده شد: {ITEMS[parts[1]]['fa']}", f"✅ Used: {ITEMS[parts[1]]['en']}"), [back_row(lang)])
        return

    # ----- units -----
    if head == "un":
        await edit(q, *units_view(p, lang))
        return
    if head == "up":
        actions.place_unit(g, p, parts[1])
        save()
        await edit(q, L(lang, f"✅ {unit_name(parts[1],'fa')} در {board.square_name(p['pos'])} مستقر شد.",
                        f"✅ {unit_name(parts[1],'en')} placed at {board.square_name(p['pos'],'en')}."), [back_row(lang)])
        return
    if head == "us":
        unit = parts[1]
        kind = "sea" if unit in ("mine", "ship") else "road"
        rids = board.routes_touching(g, p["pos"], kind=kind)
        if not rids:
            raise GameError("مسیر مناسبی به خانه‌ات وصل نیست.", "No suitable route touches your square.")
        rows = [[(board.route_name(g, r, lang) + f" [{board.route_status(g, r)}]", f"ur:{unit}:{r}")] for r in rids]
        await edit(q, L(lang, "کدوم مسیر؟", "Which route?"), rows + [back_row(lang)])
        return
    if head == "ur":
        actions.strike_route(g, p, parts[1], parts[2])
        save()
        await edit(q, L(lang, f"✅ انجام شد: {board.route_name(g, parts[2])} → {board.route_status(g, parts[2])}",
                        f"✅ Done: {board.route_name(g, parts[2], 'en')} → {board.route_status(g, parts[2])}"), [back_row(lang)])
        return
    if head == "ud":
        rows = [[(LOCATIONS[c][lang], f"udt:{c}")] for c in CITIES if c != p["pos"]]
        await edit(q, L(lang, "جاده جدید از اینجا به کجا؟ (گاد تأیید می‌کنه)", "New road from here to where? (the GM approves)"), rows + [back_row(lang)])
        return
    if head == "udt":
        if p["units"].get("shovel", 0) < 1:
            raise GameError("بیل نداری.", "You have no shovel.")
        await to_gms(ctx.bot, f"⛏ {p['name']} wants a new road {p['pos']} → {parts[1]}",
                     reply_markup=kb([[("✅ approve", f"gd:{p['id']}:{p['pos']}:{parts[1]}"), ("❌", f"gd:{p['id']}:0:0")]]))
        await edit(q, L(lang, "درخواست برای گاد فرستاده شد.", "Request sent to the GM."), [back_row(lang)])
        return
    if head == "ub":
        kind = parts[1]
        if p["units"].get(kind + "_balloon", 0) < 1:
            raise GameError("بالن نداری.", "You have no balloon.")
        rows = [[(LOCATIONS[c][lang], f"ubt:{kind}:{c}")] for c in CITIES]
        await edit(q, L(lang, "بالن رو بالای کجا بفرستی؟", "Send the balloon over which place?"), rows + [back_row(lang)])
        return
    if head == "ubt":
        b = actions.launch_balloon(g, p, parts[1], parts[2])
        save()
        await edit(q, L(lang, f"🎈 بالن به سمت {board.square_name(parts[2])} رفت. نتیجه ساعت {LOCK_HOUR}:00.",
                        f"🎈 Balloon sent toward {board.square_name(parts[2],'en')}. Result at {LOCK_HOUR}:00."), [back_row(lang)])
        return

    # ----- clown / godfather settings -----
    if head == "cd" and p["role"] == "clown":
        rows = [[(role_name(r, lang), f"cdr:{r}")] for r in ROLES]
        rows = [sum(x, []) for x in chunks(rows, 2)]
        await edit(q, L(lang, "امشب جاسوسی روی تو چه نشون بده؟", "What should spying on you show tonight?"), rows + [back_row(lang)])
        return
    if head == "cdr" and p["role"] == "clown":
        p["disguise"] = parts[1]
        save()
        await edit(q, L(lang, f"🎭 جاسوسی روی تو: {role_name(parts[1])}", f"🎭 Spying on you shows: {role_name(parts[1],'en')}"), [back_row(lang)])
        return
    if head == "fk" and p["role"] == "godfather":
        rows = [[(role_name(r, lang), f"fkr:{r}")] for r in ROLES if ROLES[r]["team"] == HUMAN]
        rows = [sum(x, []) for x in chunks(rows, 2)]
        await edit(q, L(lang, "نقش جعلی (در مرگ اعلام می‌شه):", "Fake role (read out when you die):"), rows + [back_row(lang)])
        return
    if head == "fkr" and p["role"] == "godfather":
        p["fake_role"] = parts[1]
        save()
        await edit(q, L(lang, f"🃏 نقش جعلی: {role_name(parts[1])}", f"🃏 Fake role: {role_name(parts[1],'en')}"), [back_row(lang)])
        return

    # ----- night acts -----
    if head in ("ac", "a", "t", "tg", "tb", "td", "bl", "bn", "bx", "acx"):
        await act_flow(update, ctx, p, parts)
        return

    # ----- voting -----
    if head == "vt":
        if g["phase"] != "day":
            raise GameError("رأی‌گیری فقط در روز.", "Voting is only during the day.")
        cur = g["votes"].get(str(p["id"]))
        cur_txt = pl(cur)["name"] if cur and pl(cur) else "—"
        rows = target_rows("v", alive_targets(p), lang)
        rows.insert(-1, [(btn("abstain", lang), "v:0")])
        if p["role"] == "judge" and p["charges"].get("cancel_vote") and not g["vote_cancelled"]:
            rows.insert(-1, [(L(lang, "⚖️ لغو رأی‌گیری امروز", "⚖️ Cancel today's vote"), "vc")])
        await edit(q, L(lang, f"به چه کسی رأی می‌دی؟ (فعلی: {cur_txt}، وزن رأیت: {actions.vote_weight(g, p)})",
                        f"Who do you vote for? (current: {cur_txt}, your vote weight: {actions.vote_weight(g, p)})"), rows)
        return
    if head == "v":
        if g["phase"] != "day":
            raise GameError("رأی‌گیری فقط در روز.", "Voting is only during the day.")
        if g["vote_cancelled"]:
            raise GameError("رأی‌گیری امروز لغو شده.", "Today's vote was cancelled.")
        target = None if parts[1] == "0" else parts[1]
        g["votes"][str(p["id"])] = target
        save()
        tname = pl(target)["name"] if target else None
        if VOTES_PUBLIC:
            await group(ctx.bot, f"🗳 {p['name']} → {tname or 'بدون رأی'}", f"🗳 {p['name']} → {tname or 'abstains'}")
        await edit(q, L(lang, f"✅ رأی ثبت شد: {tname or 'بدون رأی'}", f"✅ Vote recorded: {tname or 'abstain'}"), [back_row(lang)])
        return
    if head == "vc" and p["role"] == "judge":
        if not p["charges"].get("cancel_vote") or g["phase"] != "day":
            raise GameError("نمی‌تونی.", "You can't.")
        p["charges"]["cancel_vote"] = 0
        g["vote_cancelled"] = True
        save()
        await group(ctx.bot, "⚖️ قاضی رأی‌گیری امروز را لغو کرد.", "⚖️ The judge has cancelled today's vote.")
        await edit(q, L(lang, "رأی‌گیری لغو شد.", "Vote cancelled."), [back_row(lang)])
        return

    # ----- misc commands' buttons -----
    if head == "tx":
        actions.taxi(g, p, parts[1])
        save()
        await edit(q, L(lang, f"🚕 مخفیانه رفتی به {LOCATIONS[parts[1]]['fa']}", f"🚕 You secretly rode to {LOCATIONS[parts[1]]['en']}"))
        await gm_notes(ctx.bot, [(f"🚕 {p['name']} با تاکسی رفت به {parts[1]}", f"🚕 {p['name']} took the taxi to {parts[1]}")])
        return
    if head == "rv":
        T = pl(parts[1])
        actions.berlin_revive(g, p, T)
        save()
        await group(ctx.bot, f"⚰️→🧍 {T['name']} از قبرستان برلین برگشت!", f"⚰️→🧍 {T['name']} has risen from the Berlin graveyard!")
        await dm(ctx.bot, T["id"], "شما زنده شدید! /menu", "You have been revived! /menu")
        await edit(q, L(lang, f"{T['name']} زنده شد.", f"{T['name']} is revived."))
        return
    if head == "sht":
        await fire_bullet(ctx.bot, p, pl(parts[1]))
        await edit(q, L(lang, "🔫 شلیک شد.", "🔫 Fired."))
        return
    if head == "bet":
        await create_bet(ctx.bot, p, pl(parts[1]), int(parts[2]))
        await edit(q, L(lang, "دعوت فرستاده شد.", "Challenge sent."))
        return
    if head == "bpub":
        b = next((x for x in g["balloons"] if x["id"] == parts[1] and str(x["owner"]) == str(p["id"])), None)
        if b and b["publish"] is None:
            b["publish"] = parts[2] == "1"
            save()
            if b["publish"]:
                await publish_balloon(ctx.bot, b)
        await edit(q, L(lang, "ثبت شد.", "Done."))
        return


async def job_dm(ctx):
    pid, fa, en = ctx.job.data
    p = pl(pid)
    await dm(ctx.bot, pid, fa, en, reply_markup=main_menu(p, p["lang"]) if p else None)


async def job_move_options(ctx):
    p = pl(ctx.job.data)
    if p:
        await show_move_options(ctx.bot, p, None)


async def show_move_options(bot, p, q):
    g = G()
    lang = p["lang"]
    opts = actions.move_options(g, p, p["move_roll"] or 0)
    roll = p["move_roll"]
    plus = p["flags"].get("move_plus", 0)
    head = L(lang, f"🎲 تاس: {roll}" + (f" (+{plus})" if plus else "") + "\nتا این تعداد خانه می‌تونی بری:",
             f"🎲 Roll: {roll}" + (f" (+{plus})" if plus else "") + "\nYou can move up to that many squares:")
    order = sorted(opts, key=lambda s: (SQUARES[s]["kind"] != "city", len(opts[s]), s))
    rows = [[(("🏙 " if SQUARES[s]["kind"] == "city" else "◦ ") + board.square_name(s, lang)[:40], f"mt:{s}")] for s in order]
    if not rows:
        head += L(lang, "\n⛔ هیچ مسیری باز نیست.", "\n⛔ No open route.")
    rows.append(back_row(lang))
    if q:
        await edit(q, head, rows)
    else:
        await dm(bot, p["id"], head, head, reply_markup=kb(rows))


def shop_view(p, lang):
    g = G()
    lines = [L(lang, f"💰 سکه: {p['coins']}", f"💰 Coins: {p['coins']}")]
    rows = []
    if g["phase"] == "night":
        lines.append(L(lang, "قدرت برای امشب (هر بار +۱):", "Power for tonight (+1 each tap):"))
        row = []
        for s, price in POWER_PRICES.items():
            if s == "hp":
                continue
            row.append((f"{stat_name(s, lang)} +1 ({price})", f"bp:{s}"))
        rows += chunks(row, 2)
    rows.append([(L(lang, f"اچ‌پی +۱ دائمی ({POWER_PRICES['hp']})", f"HP +1 permanent ({POWER_PRICES['hp']})"), "bp:hp")])
    shop = LOCATIONS.get(p["pos"], {}).get("shop")
    if shop:
        rows.append([(L(lang, f"خرید {unit_name(shop,'fa')} ({UNIT_PRICES[shop]})", f"Buy {unit_name(shop,'en')} ({UNIT_PRICES[shop]})"), f"bu:{shop}")])
    else:
        lines.append(L(lang, "واحدها فقط در شهر فروشنده‌شون فروخته می‌شن.", "Units are sold only in their shop city."))
    if p["bought"]:
        lines.append(L(lang, "خریده‌شده امشب: ", "Bought tonight: ") + ", ".join(f"{stat_name(k, lang)} +{v}" for k, v in p["bought"].items()))
    rows.append(back_row(lang))
    return "\n".join(lines), rows


def units_view(p, lang):
    rows = []
    u = {k: v for k, v in p["units"].items() if v}
    if not u:
        return L(lang, "واحدی نداری. (کشتی: لندن، بیل: آمستردام، مین: کپنهاگ، بالن جنگی: سن‌پترزبورگ، بالن جاسوسی: مسکو، توپ: کنستانتینوپل)",
                 "You have no units. (Ship: London, Shovel: Amsterdam, Mine: Copenhagen, War balloon: St Petersburg, Spy balloon: Moscow, Cannon: Constantinople)"), [back_row(lang)]
    lines = [", ".join(f"{unit_name(k, lang)}×{v}" for k, v in u.items())]
    if u.get("cannon"):
        rows.append([(L(lang, "توپ: کاشتن اینجا", "Cannon: place here"), "up:cannon"), (L(lang, "توپ: تخریب جاده", "Cannon: destroy road"), "us:cannon")])
    if u.get("ship"):
        rows.append([(L(lang, "کشتی: کاشتن اینجا", "Ship: place here"), "up:ship"), (L(lang, "کشتی: پاک‌سازی مین", "Ship: clear mine"), "us:ship")])
    if u.get("mine"):
        rows.append([(L(lang, "مین: بستن مسیر دریایی", "Mine: block a sea lane"), "us:mine")])
    if u.get("shovel"):
        rows.append([(L(lang, "بیل: تعمیر جاده", "Shovel: repair road"), "us:shovel"), (L(lang, "بیل: جاده جدید", "Shovel: new road"), "ud")])
    if u.get("spy_balloon"):
        rows.append([(L(lang, "🎈 فرستادن بالن جاسوسی", "🎈 Launch spy balloon"), "ub:spy")])
    if u.get("war_balloon"):
        rows.append([(L(lang, "🎈 فرستادن بالن جنگی", "🎈 Launch war balloon"), "ub:war")])
    rows.append(back_row(lang))
    return "\n".join(lines), rows


# ---------------- night acts ----------------

def act_limit(p):
    return 2 if p.get("double_act") else 1


def acts_text(p, lang):
    lst = G()["acts"].get(str(p["id"]), [])
    if not lst:
        return L(lang, "هنوز اکتی ثبت نکردی.", "No act submitted yet.")
    out = []
    for a in lst:
        t = pl(a.get("target"))["name"] if a.get("target") and pl(a.get("target")) else ""
        ex = a.get("extra") or {}
        if a["type"] == "bullets":
            t = ", ".join(pl(x)["name"] for x in ex.get("targets", []) if pl(x))
        out.append(f"• {act_name(a['type'], lang)} {t}")
    return "\n".join(out)


def add_act(p, act):
    g = G()
    if g["phase"] != "night":
        raise GameError("اکت فقط در شب.", "Acts only at night.")
    if g.get("pending"):
        raise GameError("گاد در حال محاسبه شب است.", "The GM is already resolving the night.")
    lst = g["acts"].setdefault(str(p["id"]), [])
    if len(lst) >= act_limit(p):
        raise GameError("به سقف اکت‌هات رسیدی؛ اول پاکشون کن.", "You've reached your act limit; clear first.")
    t = act["type"]
    if t == "attack" and "church" in LOCATIONS.get(loc_of(p) or "", {}).get("flags", []):
        raise GameError("در کلیسا نمی‌تونی حمله کنی.", "You can't attack from the church.")
    need = {"bomb": "bomb", "poison": "poison", "guess": "guess", "cult_check": "cult_check"}.get(t)
    if need and p["charges"].get(need, 0) < 1:
        raise GameError("شارژ این توانایی تموم شده.", "That ability is used up.")
    if t == "convert" and p.get("no_recruit_until", 0) >= g["cycle"]:
        raise GameError("امشب نمی‌تونی عضو بگیری.", "You can't recruit tonight.")
    lst.append(act)
    save()


async def act_flow(update, ctx, p, parts):
    q = update.callback_query
    g = G()
    lang = p["lang"]
    head = parts[0]
    if g["phase"] != "night":
        raise GameError("اکت فقط در شب.", "Acts only at night.")
    if head == "ac":
        types = ["attack", "protect", "defuse", "spy"] + SPECIALS.get(p["role"], [])
        rows = [[(act_name(t, lang), f"a:{t}")] for t in types]
        rows = [sum(x, []) for x in chunks(rows, 2)]
        rows.append([(btn("clear", lang), "acx")])
        rows.append(back_row(lang))
        lim = L(lang, f"سقف اکت امشب: {act_limit(p)}", f"Acts allowed tonight: {act_limit(p)}")
        await edit(q, acts_text(p, lang) + "\n\n" + lim, rows)
        return
    if head == "acx":
        g["acts"].pop(str(p["id"]), None)
        save()
        await edit(q, L(lang, "اکت‌ها پاک شدند.", "Acts cleared."), [[(btn("act", lang), "ac")], back_row(lang)])
        return
    if head == "a":
        t = parts[1]
        if t == "cult_check":
            add_act(p, {"type": t, "target": None, "extra": {}})
            await edit(q, L(lang, "✅ ثبت شد.", "✅ Recorded."), [back_row(lang)])
            return
        if t == "bullets":
            ctx.user_data["bul"] = []
            await edit(q, *bullet_view(p, ctx, lang))
            return
        targets = alive_targets(p, include_self=(t == "protect"))
        await edit(q, L(lang, f"{act_name(t,'fa')} روی چه کسی؟", f"{act_name(t,'en')} on whom?"), target_rows(f"t:{t}", targets, lang, back="ac"))
        return
    if head == "t":
        t, tid = parts[1], parts[2]
        if t == "guess":
            rows = [[(role_name(r, lang), f"tg:{tid}:{r}")] for r in ROLES]
            rows = [sum(x, []) for x in chunks(rows, 2)]
            await edit(q, L(lang, "نقشش چیه؟", "What is their role?"), rows + [[(btn("back", lang), "ac")]])
            return
        if t == "bomb":
            rows = [[(f"🔌 {w}", f"tb:{tid}:{w}") for w in range(1, 5)]]
            await edit(q, L(lang, "کدوم سیم اصلیه؟", "Which wire is the live one?"), rows + [[(btn("back", lang), "ac")]])
            return
        if t == "duel":
            others = [x for x in alive_targets(p, include_self=True) if str(x["id"]) != tid]
            await edit(q, L(lang, "حریف دوم دوئل؟", "Second duellist?"), target_rows(f"td:{tid}", others, lang, back="ac"))
            return
        add_act(p, {"type": t, "target": tid, "extra": {}})
        await edit(q, L(lang, f"✅ ثبت شد: {act_name(t,'fa')} → {pl(tid)['name']}", f"✅ Recorded: {act_name(t,'en')} → {pl(tid)['name']}"), [back_row(lang)])
        return
    if head == "tg":
        add_act(p, {"type": "guess", "target": parts[1], "extra": {"role": parts[2]}})
        await edit(q, L(lang, "✅ حدس ثبت شد.", "✅ Guess recorded."), [back_row(lang)])
        return
    if head == "tb":
        add_act(p, {"type": "bomb", "target": parts[1], "extra": {"wire": int(parts[2])}})
        await edit(q, L(lang, "✅ بمب آماده است.", "✅ Bomb set."), [back_row(lang)])
        return
    if head == "td":
        add_act(p, {"type": "duel", "target": parts[1], "extra": {"target2": parts[2]}})
        await edit(q, L(lang, "✅ دوئل ثبت شد.", "✅ Duel ordered."), [back_row(lang)])
        return
    if head == "bl":
        sel = ctx.user_data.setdefault("bul", [])
        if parts[1] in sel:
            sel.remove(parts[1])
        elif len(sel) < 3:
            sel.append(parts[1])
        await edit(q, *bullet_view(p, ctx, lang))
        return
    if head == "bn":
        sel = ctx.user_data.get("bul", [])
        if not sel:
            raise GameError("هیچ‌کس انتخاب نشده.", "Nobody selected.")
        rows = [[(pl(x)["name"], f"bx:{x}")] for x in sel]
        if p["charges"].get("war_bullet", 0) < 1:
            rows = []
        rows.append([(L(lang, "بدون تیر جنگی", "No war bullet"), "bx:0")])
        await edit(q, L(lang, f"تیر جنگی به کی؟ (باقی‌مانده: {p['charges'].get('war_bullet',0)})",
                        f"War bullet to whom? (left: {p['charges'].get('war_bullet',0)})"), rows)
        return
    if head == "bx":
        sel = ctx.user_data.get("bul", [])
        add_act(p, {"type": "bullets", "target": None, "extra": {"targets": sel, "war": None if parts[1] == "0" else parts[1]}})
        ctx.user_data["bul"] = []
        await edit(q, L(lang, "✅ تیرها ثبت شد.", "✅ Bullets recorded."), [back_row(lang)])
        return


def bullet_view(p, ctx, lang):
    sel = ctx.user_data.get("bul", [])
    rows = [[(("✅ " if str(x["id"]) in sel else "") + x["name"][:26], f"bl:{x['id']}")] for x in alive_targets(p)]
    rows = [sum(x, []) for x in chunks(rows, 2)]
    rows.append([(L(lang, "ادامه ➡️", "Next ➡️"), "bn")])
    rows.append([(btn("back", lang), "ac")])
    return L(lang, "حداکثر ۳ نفر انتخاب کن:", "Pick up to 3 people:"), rows


# ---------------- commands: slots, taxi, shoot, bet ----------------

async def cmd_slots(update: Update, ctx):
    p = pl(acting_uid(update.effective_user.id))
    if not p or not p["alive"] or update.effective_chat.type != "private":
        return
    g = G()
    lang = p["lang"]
    try:
        if g["phase"] != "night" or not g["locked"]:
            raise GameError("ماشین اسلات بعد از قفل نقشه در شب کار می‌کنه.", "The slot machine runs at night after the map lock.")
        msg = await ctx.bot.send_dice(chat_for(p["id"]), emoji="🎰")
        s = actions.slot_pull(g, p, msg.dice.value)
        save()
    except GameError as e:
        await update.message.reply_text(e.text(lang))
        return
    if s["hit"] and s["kind"] == "berlin":
        dead = [x for x in roster(g) if not x["alive"] and x["role"] and not x.get("unrevivable")]
        rows = [[(x["name"], f"rv:{x['id']}")] for x in dead]
        text = L(lang, "🎰 سه‌تای یکسان! یک نفر رو زنده کن:", "🎰 Three of a kind! Revive someone:")
        ctx.job_queue.run_once(job_dm_kb, DICE_WAIT, data=(p["id"], text, rows))
        return
    if s["hit"]:
        res = ("🎰 جک‌پات! امشب همه قدرت‌ها و اچ‌پی +۲۰.", "🎰 Jackpot! All powers and HP +20 tonight.")
    elif s["done"]:
        res = ("🎰 تموم شد، سه‌تای یکسان نیامد." + (" امشب همه قدرت‌ها −۲۰." if s["kind"] == "vienna" else ""),
               "🎰 Out of pulls, no three of a kind." + (" All powers −20 tonight." if s["kind"] == "vienna" else ""))
    else:
        res = (f"🎰 نشد. {s['left']} بار دیگه. /slots", f"🎰 No luck. {s['left']} pulls left. /slots")
    ctx.job_queue.run_once(job_dm, DICE_WAIT, data=(p["id"], *res))


async def job_dm_kb(ctx):
    pid, text, rows = ctx.job.data
    await dm(ctx.bot, pid, text, text, reply_markup=kb(rows))


async def cmd_taxi(update: Update, ctx):
    p = pl(acting_uid(update.effective_user.id))
    if not p or not p["alive"]:
        return
    lang = p["lang"]
    if not G()["locked"] or p.get("night_pos") != "london":
        await update.message.reply_text(L(lang, "تاکسی فقط بعد از قفل نقشه و در لندن.", "The taxi only works after the lock, in London."))
        return
    rows = [[(LOCATIONS[c][lang], f"tx:{c}")] for c in CITIES if c != "london"]
    await update.message.reply_text(L(lang, "🚕 کجا بریم؟ (روی نقشه عمومی همچنان لندن نشون داده می‌شی)",
                                      "🚕 Where to? (the public map still shows you in London)"), reply_markup=kb(rows))


async def cmd_shoot(update: Update, ctx):
    p = pl(acting_uid(update.effective_user.id))
    if not p or not p["alive"]:
        return
    lang = p["lang"]
    if G()["phase"] != "day" or not p["bullets"]:
        await update.message.reply_text(L(lang, "فقط در روز و اگر تیر داشته باشی.", "Only during the day, and only if you hold a bullet."))
        return
    await update.message.reply_text(L(lang, "به کی شلیک کنی؟", "Shoot whom?"), reply_markup=kb(target_rows("sht", alive_targets(p), lang)))


async def fire_bullet(bot, p, T):
    g = G()
    if g["phase"] != "day" or not p["bullets"] or not T or not T["alive"]:
        raise GameError("نمی‌شه شلیک کرد.", "Can't fire.")
    kind = p["bullets"].pop(0)
    save()
    if kind == "war":
        await group(bot, f"💥 {p['name']} به {T['name']} شلیک کرد… تیر جنگی بود!", f"💥 {p['name']} shot {T['name']}… it was a live round!")
        actions.kill(g, T, "bullet")
        # a poison the apothecary handed out fails if they are shot during the day
        if T["role"] == "apothecary":
            for po in g["poisons"]:
                if str(po["by"]) == str(T["id"]) and po["status"] == "pending":
                    po["status"] = "failed"
        save()
        await announce_death(bot, T)
        await check_win(bot)
    else:
        await group(bot, f"🔫 {p['name']} به {T['name']} شلیک کرد… مشقی بود.", f"🔫 {p['name']} shot {T['name']}… just a blank.")


async def cmd_bet(update: Update, ctx):
    p = pl(acting_uid(update.effective_user.id))
    if not p or not p["alive"]:
        return
    lang = p["lang"]
    if p["pos"] != "stockholm":
        await update.message.reply_text(L(lang, "شرط‌بندی فقط در کازینوی استکهلم.", "Bets only in the Stockholm casino."))
        return
    others = [x for x in alive_targets(p) if x["pos"] == "stockholm"]
    if not others:
        await update.message.reply_text(L(lang, "کس دیگه‌ای در کازینو نیست.", "Nobody else is in the casino."))
        return
    rows = [[(f"{x['name'][:18]} · {s}", f"bet:{x['id']}:{s}") for s in (2, 5, 10)] for x in others]
    await update.message.reply_text(L(lang, "سنگ‌کاغذقیچی با شرط (سکه):", "Rock-paper-scissors for coins:"), reply_markup=kb(rows))


async def create_bet(bot, p, T, stake):
    g = G()
    if not T or T["pos"] != "stockholm" or p["pos"] != "stockholm":
        raise GameError("هر دو باید در کازینو باشید.", "Both of you must be in the casino.")
    if p["coins"] < stake:
        raise GameError("سکه کافی نداری.", "Not enough coins.")
    b = {"id": actions.next_id(g, "s"), "a": str(p["id"]), "b": str(T["id"]), "stake": stake, "status": "offered", "picks": {}}
    g["bets"].append(b)
    save()
    await dm(bot, T["id"], f"🎲 {p['name']} تو کازینو {stake} سکه سر سنگ‌کاغذقیچی شرط بسته. قبول؟",
             f"🎲 {p['name']} bets {stake} coins on rock-paper-scissors. Accept?",
             reply_markup=kb([[("✅", f"ba:{b['id']}:1"), ("❌", f"ba:{b['id']}:0")]]))


RPS = {"r": ("✊ سنگ", "✊ Rock"), "p": ("✋ کاغذ", "✋ Paper"), "s": ("✌️ قیچی", "✌️ Scissors")}
BEATS = {"r": "s", "p": "r", "s": "p"}


def rps_rows(kind, gid, lang):
    return [[(L(lang, *RPS[c]), f"rp:{kind}:{gid}:{c}") for c in "rps"]]


async def ask_rps(bot, kind, game, round_no=None):
    for side in ("a", "b"):
        uid = game[side]
        lang = lang_of(uid)
        title = L(lang, f"راند {round_no}: انتخاب کن", f"Round {round_no}: choose") if round_no else L(lang, "انتخاب کن:", "Choose:")
        await dm(bot, uid, title, title, reply_markup=kb(rps_rows(kind, game["id"], lang)))


async def start_duel(bot, du):
    A, B = pl(du["a"]), pl(du["b"])
    await group(bot, f"⚖️ به حکم قاضی، امروز {A['name']} و {B['name']} دوئل می‌کنند (۳ راند، بازنده هر راند −۱۰ اچ‌پی).",
                f"⚖️ By the judge's order, {A['name']} and {B['name']} duel today (3 rounds, each round's loser −10 HP).")
    du["status"] = "live"
    save()
    await ask_rps(bot, "d", du, 1)


# ---------------- shared buttons (bombs, poison, rps, yakuza) ----------------

async def shared_button(update, ctx, data):
    q = update.callback_query
    real = q.from_user.id
    uid = str(acting_uid(real))
    g = G()
    parts = data.split(":")
    lang = lang_of(uid)
    if is_gm(real) and data.startswith(("bw:", "an:", "rp:", "ba:", "yk:")):
        # GM override: a GM may press group buttons for the player they are playing as
        pass
    head = parts[0]

    if head == "bw":  # bomb wire chosen in the group
        bo = next((b for b in g["bombs"] if b["id"] == parts[1]), None)
        if not bo or bo["status"] != "armed":
            return
        if uid != str(bo["target"]):
            await q.answer(L(lang, "این بمب مال تو نیست!", "This isn't your bomb!"), show_alert=True)
            return
        wire = int(parts[2])
        T = pl(bo["target"])
        if wire == bo["wire"]:
            bo["status"] = "defused"
            B = pl(bo["by"])
            if B:
                B["charges"]["bomb"] = 0
            save()
            await q.edit_message_text(bi(f"✂️ {T['name']} سیم {wire} را برید… بمب خنثی شد!", f"✂️ {T['name']} cut wire {wire}… the bomb is defused!"))
            return
        bo["status"] = "exploded"
        victims = [T]
        for x in alive_players(g):
            if x is T or x["role"] == "cultist" or x["pos"] != T["pos"]:
                continue
            if random.random() < 0.8:
                victims.append(x)
        for v in victims:
            actions.kill(g, v, "bomb")
        save()
        await q.edit_message_text(bi(f"💥 {T['name']} سیم {wire} را برید… بوم!", f"💥 {T['name']} cut wire {wire}… BOOM!"))
        for v in victims:
            await announce_death(ctx.bot, v)
        await check_win(ctx.bot)
        return

    if head == "an":  # apothecary antidote decision
        po = next((x for x in g["poisons"] if x["id"] == parts[1]), None)
        if not po or str(po["by"]) != uid or po["status"] != "pending":
            return
        po["antidote"] = parts[2] == "1"
        po["status"] = "cured" if po["antidote"] else "doomed"
        save()
        await q.edit_message_text(L(lang, "تصمیم ثبت شد.", "Decision recorded."))
        if po["antidote"]:
            await group(ctx.bot, f"🧪 {pl(po['target'])['name']} پادزهر گرفت.", f"🧪 {pl(po['target'])['name']} received the antidote.")
        return

    if head == "ba":  # casino bet accept
        b = next((x for x in g["bets"] if x["id"] == parts[1]), None)
        if not b or b["b"] != uid or b["status"] != "offered":
            return
        if parts[2] != "1":
            b["status"] = "declined"
            save()
            await q.edit_message_text(L(lang, "رد شد.", "Declined."))
            await dm(ctx.bot, b["a"], "شرط رد شد.", "Your bet was declined.")
            return
        stake = min(b["stake"], pl(b["a"])["coins"], pl(b["b"])["coins"])
        b["stake"] = stake
        b["status"] = "live"
        save()
        await q.edit_message_text(L(lang, f"شرط {stake} سکه‌ای شروع شد.", f"{stake}-coin bet on."))
        await ask_rps(ctx.bot, "b", b)
        return

    if head == "rp":
        kind, gid, choice = parts[1], parts[2], parts[3]
        pool = g["duels"] if kind == "d" else g["bets"]
        game = next((x for x in pool if x["id"] == gid), None)
        if not game or game["status"] != "live" or uid not in (game["a"], game["b"]):
            return
        if uid in game["picks"]:
            await q.answer(L(lang, "قبلاً انتخاب کردی.", "Already chosen."), show_alert=True)
            return
        game["picks"][uid] = choice
        save()
        await q.edit_message_text(L(lang, f"انتخاب: {L(lang, *RPS[choice])} — منتظر حریف…", f"Chosen: {L(lang, *RPS[choice])} — waiting for opponent…"))
        if len(game["picks"]) < 2:
            return
        ca, cb = game["picks"][game["a"]], game["picks"][game["b"]]
        game["picks"] = {}
        A, B = pl(game["a"]), pl(game["b"])
        if ca == cb:
            save()
            await dm(ctx.bot, game["a"], "مساوی؛ دوباره.", "Draw; again.")
            await dm(ctx.bot, game["b"], "مساوی؛ دوباره.", "Draw; again.")
            await ask_rps(ctx.bot, kind, game, len(game.get("rounds", [])) + 1 if kind == "d" else None)
            return
        win, lose = (A, B) if BEATS[ca] == cb else (B, A)
        if kind == "b":
            amt = min(game["stake"], lose["coins"])
            lose["coins"] -= amt
            win["coins"] += amt
            game["status"] = "done"
            save()
            for x in (A, B):
                await dm(ctx.bot, x["id"], f"🎲 {A['name']} {RPS[ca][0]} / {B['name']} {RPS[cb][0]} → برنده {win['name']} ({amt} سکه)",
                         f"🎲 {A['name']} {RPS[ca][1]} / {B['name']} {RPS[cb][1]} → {win['name']} wins {amt} coins")
            return
        game.setdefault("rounds", []).append(lose["id"])
        lose["hp"] -= 10
        n = len(game["rounds"])
        await group(ctx.bot, f"⚖️ راند {n}: {A['name']} {RPS[ca][0]} / {B['name']} {RPS[cb][0]} → {lose['name']} −۱۰ اچ‌پی",
                    f"⚖️ Round {n}: {A['name']} {RPS[ca][1]} / {B['name']} {RPS[cb][1]} → {lose['name']} −10 HP")
        if lose["hp"] <= 0:
            actions.kill(g, lose, "duel")
            game["status"] = "done"
            save()
            await announce_death(ctx.bot, lose)
            await check_win(ctx.bot)
            return
        if n >= 3:
            game["status"] = "done"
            save()
            await group(ctx.bot, "⚖️ دوئل تمام شد.", "⚖️ The duel is over.")
            return
        save()
        await ask_rps(ctx.bot, "d", game, n + 1)
        return

    if head == "yk":  # yakuza takes someone with them
        Y = pl(uid)
        if not Y or Y["role"] != "yakuza" or not Y.get("flags", {}).get("yakuza_pending"):
            return
        T = pl(parts[1])
        Y["flags"].pop("yakuza_pending", None)
        if T and T["alive"] and T["role"] != "cultist":
            actions.kill(g, T, "yakuza")
            save()
            await q.edit_message_text(L(lang, f"{T['name']} را با خودت بردی.", f"You took {T['name']} with you."))
            await group(ctx.bot, f"🗡 یاکوزا {T['name']} را با خود برد.", f"🗡 The Yakuza took {T['name']} down with them.")
            await announce_death(ctx.bot, T)
            await check_win(ctx.bot)
        else:
            save()


async def post_bomb(bot, bo):
    T = pl(bo["target"])
    gid = G()["group_id"]
    rows = [[(f"✂️ {w}", f"bw:{bo['id']}:{w}") for w in range(1, 5)]]
    text = bi(f"💣 بمب به {T['name']} رسید! {T['name']}، یکی از ۴ سیم را ببر:",
              f"💣 A bomb has reached {T['name']}! {T['name']}, cut one of the 4 wires:")
    if gid:
        await bot.send_message(gid, text, reply_markup=kb(rows))
    else:
        await dm(bot, T["id"], text, text, reply_markup=kb(rows))


async def post_poison(bot, po):
    T = pl(po["target"])
    await group(bot, f"🧪 سم به {T['name']} رسید.", f"🧪 Poison has reached {T['name']}.")
    lang = lang_of(po["by"])
    await dm(bot, po["by"], f"تا شروع شب بعد وقت داری: به {T['name']} پادزهر بدی؟",
             f"Until next night begins: give {T['name']} the antidote?",
             reply_markup=kb([[(L(lang, "✅ پادزهر", "✅ Antidote"), f"an:{po['id']}:1"), (L(lang, "❌ نه", "❌ No"), f"an:{po['id']}:0")]]))


async def resolve_poisons(bot):
    g = G()
    for po in g["poisons"]:
        if po["status"] not in ("pending", "doomed"):
            continue
        T, A = pl(po["target"]), pl(po["by"])
        if A and not A["alive"]:
            po["status"] = "failed"
            continue
        if T and T["alive"]:
            actions.kill(g, T, "poison")
            po["status"] = "killed"
            save()
            await group(bot, f"🧪 سم کار {T['name']} را ساخت.", f"🧪 The poison claims {T['name']}.")
            await announce_death(bot, T)
        else:
            po["status"] = "void"
    save()


async def publish_balloon(bot, b):
    O = pl(b["owner"])
    names = "، ".join(b["result"]) if b["result"] else "هیچ‌کس"
    names_en = ", ".join(b["result"]) if b["result"] else "nobody"
    fa = f"🎈 گزارش بالن جاسوسی {O['name']} بر فراز {board.square_name(b['target'])}: {names}"
    en = f"🎈 {O['name']}'s spy balloon over {board.square_name(b['target'],'en')}: {names_en}"
    target = G()["channel_id"] or G()["group_id"]
    if target:
        await bot.send_message(target, bi(fa, en))


# ---------------- GM ----------------

GM_BUTTONS = {"gday", "gnight", "glock", "gres", "gtal", "gmap", "gpub", "gpl", "gbal", "gwin", "gundo", "gap", "grr", "gacts", "gpanel"}


def gm_panel_kb():
    g = G()
    rows = [
        [("☀️ Day / روز", "gday"), ("🌙 Night / شب", "gnight")],
        [("🔒 Lock map / قفل", "glock"), ("🧮 Resolve night / محاسبه", "gres")],
        [("🗳 Tally / شمارش", "gtal"), ("📜 Acts / اکت‌ها", "gacts")],
        [("🗺 GM map", "gmap"), ("📢 Public map", "gpub")],
        [("👥 Players", "gpl"), ("🎈 Balloons & battles", "gbal")],
        [("🏆 Win check", "gwin"), ("↩️ Undo", "gundo")],
    ]
    return kb(rows)


def gm_header():
    g = G()
    alive = alive_players(g)
    acted = len([pid for pid, a in g["acts"].items() if a])
    return (f"👑 GM panel · phase {g['phase']} {g['cycle']}{' 🔒' if g['locked'] else ''}\n"
            f"alive {len(alive)}/{len([p for p in g['players'].values() if p['role']])} · acts in {acted} · votes {len(g['votes'])}\n"
            f"group {'✅' if g['group_id'] else '❌ /setgroup'} · channel {'✅' if g['channel_id'] else '— (/setchannel)'}")


async def cmd_gm(update: Update, ctx):
    if not is_gm(update.effective_user.id):
        return
    await update.message.reply_text(gm_header(), reply_markup=gm_panel_kb())


def gm_only(fn):
    async def wrap(update: Update, ctx):
        uid = update.effective_user.id
        if not is_gm(uid):
            if not G()["gm_ids"] and not ENV_GMS and fn.__name__ == "cmd_claimgm":
                return await fn(update, ctx)
            return
        try:
            return await fn(update, ctx)
        except GameError as e:
            await update.message.reply_text(e.text(lang_of(uid)))
    wrap.__name__ = fn.__name__
    return wrap


async def cmd_claimgm(update: Update, ctx):
    """First person to send /claimgm becomes GM when GM_IDS isn't set."""
    g = G()
    uid = update.effective_user.id
    if ENV_GMS or g["gm_ids"]:
        if not is_gm(uid):
            return
    if uid not in g["gm_ids"]:
        g["gm_ids"].append(uid)
        save()
    await update.message.reply_text(f"👑 You are GM (id {uid}). /gm")


def who(arg):
    p = find_player(G(), arg)
    if not p:
        raise GameError(f"بازیکن پیدا نشد: {arg}", f"Player not found: {arg}")
    return p


async def gm_button(update, ctx, data):
    q = update.callback_query
    g = G()
    bot = ctx.bot
    uid = q.from_user.id
    lang = lang_of(uid)
    parts = data.split(":")
    head = parts[0]
    if head == "gpanel":
        await q.edit_message_text(gm_header(), reply_markup=gm_panel_kb())
    elif head == "gday":
        await do_phase(bot, "day")
        await q.message.reply_text("☀️ Day started.", reply_markup=gm_panel_kb())
    elif head == "gnight":
        await do_phase(bot, "night")
        await q.message.reply_text("🌙 Night started.", reply_markup=gm_panel_kb())
    elif head == "glock":
        await do_lock(bot)
        await q.message.reply_text("🔒 Locked and posted.")
    elif head in ("gres", "grr"):
        if g["phase"] != "night":
            await q.message.reply_text("Night only.")
            return
        g["pending"] = resolve_night(g)
        save()
        await send_report(bot, q.message.chat_id, lang)
    elif head == "ge":
        res = g.get("pending")
        if not res:
            return
        eid = int(parts[1])
        for e in res["effects"]:
            if e["id"] == eid:
                e["on"] = not e["on"]
        save()
        await q.edit_message_text(effects_text(res, lang), reply_markup=effects_kb(res))
    elif head == "gap":
        res = g.get("pending")
        if not res:
            await q.message.reply_text("Nothing pending.")
            return
        store.backup()
        out = actions.apply_effects(g, res)
        save()
        await send_outbox(bot, out)
        await q.message.reply_text("✅ Applied. Write the story with /story, then ☀️ Day.", reply_markup=gm_panel_kb())
        await check_win(bot)
    elif head == "gacts":
        await q.message.reply_text(acts_overview(lang) or "No acts.")
    elif head == "gtal":
        ranked, notes = actions.tally(g)
        lines = [f"{'❌ CANCELLED · ' if g['vote_cancelled'] else ''}Votes:"]
        for pid, v in ranked:
            lines.append(f"{pl(pid)['name']}: {v:g}")
        lines += [n[1] for n in notes]
        rows = [[(f"☠️ {pl(pid)['name']}", f"gx:{pid}")] for pid, _ in ranked[:6]]
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            judge = next((p for p in alive_players(g) if p["role"] == "judge"), None)
            tied = [pid for pid, v in ranked if v == ranked[0][1]]
            if judge and str(judge["id"]) not in tied:
                lines.append(f"⚖️ Tie — the judge ({judge['name']}) decides.")
        rows.append([("No execution", "gx:0")])
        await q.message.reply_text("\n".join(lines), reply_markup=kb(rows))
    elif head == "gx":
        if parts[1] == "0":
            await group(bot, "امروز کسی اعدام نشد.", "Nobody was executed today.")
            return
        await execute(bot, pl(parts[1]), q.message)
    elif head == "gmap":
        await bot.send_photo(q.message.chat_id, render(g, gm=True, title=f"GM · {g['phase']} {g['cycle']}"))
    elif head == "gpub":
        await post_public_map(bot)
    elif head == "gpl":
        await q.message.reply_text(players_overview(), parse_mode=None)
    elif head == "gbal":
        await balloons_overview(bot, q.message.chat_id)
    elif head == "gw":
        b = next((x for x in g["balloons"] if x["id"] == parts[1]), None)
        if not b or b["result"] != "await_pct":
            return
        hit = actions.apply_war_balloon(g, b, int(parts[2]))
        save()
        await q.edit_message_text(f"💣 {b['target']} −{parts[2]}% applied.")
        await group(bot, f"💣 بالن جنگی {board.square_name(b['target'])} را بمباران کرد: {parts[2]}٪ تخریب.",
                    f"💣 A war balloon bombed {board.square_name(b['target'],'en')}: {parts[2]}% destroyed.")
        for P, loss in hit:
            await dm(bot, P["id"], f"بمباران! {loss} اچ‌پی از دست دادی.", f"Bombing! You lost {loss} HP.")
            if P["hp"] <= 0:
                actions.kill(g, P, "bombing")
                save()
                await announce_death(bot, P)
    elif head == "gf":
        f = next((x for x in g["battles"] if x["id"] == parts[1]), None)
        if not f or f["status"] != "open":
            return
        loser = parts[2]
        f["status"] = "done"
        g["units_on_map"] = [u for u in g["units_on_map"] if u.get("id") != loser]
        for b in g["balloons"]:
            if b["id"] == loser:
                b["result"] = "shot_down"
        save()
        await q.edit_message_text(f"⚔️ Battle at {f['square']}: {loser} destroyed.")
        await group(bot, f"⚔️ نبرد در {board.square_name(f['square'])}: یک واحد نابود شد.",
                    f"⚔️ Battle at {board.square_name(f['square'],'en')}: one unit was destroyed.")
    elif head == "gd":
        P = pl(parts[1])
        if parts[2] == "0":
            await q.edit_message_text("❌ rejected")
            await dm(bot, P["id"], "گاد درخواست جاده را رد کرد.", "The GM rejected your road request.")
            return
        if P["units"].get("shovel", 0) < 1:
            await q.edit_message_text("Player has no shovel left.")
            return
        rid = actions.dig_route(g, parts[2], parts[3], owner=P["id"])
        P["units"]["shovel"] -= 1
        save()
        await q.edit_message_text(f"⛏ New road {rid}: {parts[2]} ↔ {parts[3]}")
        await dm(bot, P["id"], "⛏ جاده جدید ساخته شد.", "⛏ Your new road is built.")
    elif head == "gwin":
        res = actions.winner_check(g)
        await q.message.reply_text("\n".join(r[1] for r in res) or "No win condition met yet.")
    elif head == "gundo":
        ok = store.undo()
        await q.message.reply_text("↩️ Restored the state from before the last apply/execution." if ok else "Nothing to undo.")


def effects_text(res, lang):
    lines = [f"🧮 Night {res['cycle']} — proposed effects (tap a number to switch it off/on, then Apply):"]
    for e in res["effects"]:
        lines.append(f"{'✅' if e['on'] else '❌'} {e['id']}. {e[lang]}")
    if not res["effects"]:
        lines.append("— no effects —")
    return "\n".join(lines)[:4000]


def effects_kb(res):
    btns = [(f"{'✅' if e['on'] else '❌'}{e['id']}", f"ge:{e['id']}") for e in res["effects"]]
    rows = chunks(btns, 5)
    rows.append([("✔️ Apply / اعمال", "gap"), ("🎲 Re-roll", "grr")])
    return kb(rows)


async def send_report(bot, chat_id, lang):
    res = G()["pending"]
    detail = "\n".join((fa if lang == "fa" else en) for fa, en in res["lines"])
    for part in split_text("📜 " + detail):
        await bot.send_message(chat_id, part)
    await bot.send_message(chat_id, effects_text(res, lang), reply_markup=effects_kb(res))


def acts_overview(lang):
    g = G()
    lines = []
    for pid, lst in g["acts"].items():
        P = pl(pid)
        for a in lst:
            t = pl(a.get("target"))["name"] if a.get("target") and pl(a.get("target")) else ""
            lines.append(f"{P['name']} ({role_name(P['role'], lang)}) → {a['type']} {t} {a.get('extra') or ''}")
    missing = [p["name"] for p in alive_players(g) if not g["acts"].get(str(p["id"]))]
    if g["phase"] == "night" and missing:
        lines.append("\nNo act yet: " + ", ".join(missing))
    return "\n".join(lines)


def players_overview():
    g = G()
    lines = []
    for i, p in enumerate(roster(g), start=1):
        role = role_name(p["role"], "en") if p["role"] else "—"
        lines.append(f"{i}. {'☠️' if not p['alive'] else ''}{p['name']} @{p.get('username') or '-'} · {role}"
                     f"{' (cult)' if p['cult'] else ''} · hp {p['hp']} · ¢{p['coins']} · {p['pos'] or '-'}"
                     f"{' · items ' + str(len(p['items'])) if p['items'] else ''}")
    return "\n".join(lines) or "No players yet."


async def balloons_overview(bot, chat_id):
    g = G()
    sent = False
    for b in g["balloons"]:
        if b["kind"] == "war" and b["result"] == "await_pct":
            sent = True
            rows = [[(f"{x}%", f"gw:{b['id']}:{x}") for x in (0, 20, 40)], [(f"{x}%", f"gw:{b['id']}:{x}") for x in (60, 80, 100)]]
            await bot.send_message(chat_id, f"💣 War balloon by {pl(b['owner'])['name']} over {b['target']} — bombing minigame result?",
                                   reply_markup=kb(rows))
    for f in g["battles"]:
        if f["status"] == "open":
            sent = True
            rows = [[(f"{u['kind']} of {pl(u['owner'])['name']}", f"gf:{f['id']}:{u['id']}")] for u in f["units"] if u.get("id")]
            await bot.send_message(chat_id, f"⚔️ Battle at {f['square']} — which unit is destroyed?", reply_markup=kb(rows))
    if not sent:
        await bot.send_message(chat_id, "No pending balloons or battles.")


async def execute(bot, P, msg):
    g = G()
    if not P or not P["alive"]:
        return
    if P["flags"].get("hotel_immune") and g["loc_damage"].get("barcelona", 0) < 100:
        await msg.reply_text(f"{P['name']} is in the hotel and can't be executed.")
        return
    store.backup()
    actions.kill(g, P, "execution")
    save()
    await group(bot, f"⚖️ {P['name']} اعدام شد.", f"⚖️ {P['name']} has been executed.")
    await announce_death(bot, P)
    if P["role"] == "clown" and not P.get("cult_lost_clown"):
        await group(bot, "🤡 دلقک اعدام شد و بازی را برد!", "🤡 The clown was executed and wins!")
    if P["role"] == "yakuza":
        P["flags"]["yakuza_pending"] = True
        save()
        targets = [x for x in alive_players(g) if x["role"] != "cultist"]
        await dm(bot, P["id"], "🗡 یک نفر را با خودت ببر:", "🗡 Take someone down with you:",
                 reply_markup=kb(target_rows("yk", targets, lang_of(P["id"]))[:-1]))
    await check_win(bot)


async def do_phase(bot, phase):
    g = G()
    store.backup()
    if phase == "night":
        await resolve_poisons(bot)
        pending_duels = [d for d in g["duels"] if d["status"] in ("pending", "live")]
        for d in pending_duels:
            d["status"] = "expired"
    actions.start_phase(g, phase)
    save()
    if phase == "night":
        await group(bot, f"🌙 شب {g['cycle']} آغاز شد. تا ساعت {LOCK_HOUR}:00 مکانت رو انتخاب کن؛ اکت‌ها از منو.",
                    f"🌙 Night {g['cycle']} begins. Pick your place before {LOCK_HOUR}:00; acts from the menu.")
    else:
        await group(bot, f"☀️ روز {g['cycle']} آغاز شد. رأی‌گیری از منوی ربات (/menu).",
                    f"☀️ Day {g['cycle']} begins. Vote from the bot menu (/menu).")
    for p in alive_players(g):
        await dm(bot, p["id"], f"{'🌙 شب' if phase == 'night' else '☀️ روز'} شروع شد.", f"{'🌙 Night' if phase == 'night' else '☀️ Day'} has started.",
                 reply_markup=main_menu(p, p["lang"]))


async def do_lock(bot):
    g = G()
    if g["phase"] == "lobby" or g["locked"]:
        return
    summary = actions.lock_map(g)
    save()
    for pid, fa, en in summary["private"]:
        await dm(bot, pid, fa, en)
    # spy balloon results to owners
    for b in g["balloons"]:
        if b["kind"] != "spy" or b["cycle"] != g["cycle"] or b.get("phase") != g["phase"] or b.get("delivered"):
            continue
        b["delivered"] = True
        names = ", ".join(b["result"]) or "—"
        lang = lang_of(b["owner"])
        if b["publish"] is None:
            await dm(bot, b["owner"], f"🎈 بالن جاسوسی بر فراز {board.square_name(b['target'])}: {names}\nمنتشر بشه؟",
                     f"🎈 Spy balloon over {board.square_name(b['target'],'en')}: {names}\nPublish it?",
                     reply_markup=kb([[(L(lang, "📢 انتشار", "📢 Publish"), f"bpub:{b['id']}:1"), (L(lang, "🤫 نگه دار", "🤫 Keep"), f"bpub:{b['id']}:0")]]))
        else:
            await dm(bot, b["owner"], f"🎈 بالن جاسوسی بر فراز {board.square_name(b['target'])}: {names}",
                     f"🎈 Spy balloon over {board.square_name(b['target'],'en')}: {names}")
    save()
    await post_public_map(bot)
    for b in g["balloons"]:
        if b["publish"] and b.get("delivered") and not b.get("published"):
            b["published"] = True
            await publish_balloon(bot, b)
    save()
    notes = list(summary["gm_notes"])
    wb = [b for b in g["balloons"] if b["result"] == "await_pct"]
    fights = [f for f in g["battles"] if f["status"] == "open"]
    if wb or fights:
        notes.append((f"🎈 {len(wb)} بالن جنگی و ⚔️ {len(fights)} نبرد منتظر نتیجه مینی‌گیم: /gm → Balloons",
                      f"🎈 {len(wb)} war balloon(s) and ⚔️ {len(fights)} battle(s) need minigame results: /gm → Balloons"))
    await gm_notes(bot, [("🔒 نقشه قفل شد.", "🔒 Map locked.")] + notes)


async def post_public_map(bot):
    g = G()
    target = g["channel_id"] or g["group_id"]
    if not target:
        return
    title = f"{'Night' if g['phase'] == 'night' else 'Day'} {g['cycle']} · {LOCK_HOUR}:00"
    cap = bi(f"🗺 نقشه {('شب' if g['phase'] == 'night' else 'روز')} {g['cycle']} — واحدها و مسیرها",
             f"🗺 Map, {g['phase']} {g['cycle']} — units and routes")
    try:
        await bot.send_photo(target, render(g, gm=False, title=title), caption=cap)
    except TelegramError as e:
        logger.warning("map post failed: %s", e)


async def job_lock(ctx):
    await do_lock(ctx.bot)


async def job_midnight(ctx):
    g = G()
    if g["phase"] == "lobby":
        return
    nxt = "day" if g["phase"] == "night" else "night"
    await to_gms(ctx.bot, f"🕛 Midnight. Phase is {g['phase']} {g['cycle']}. "
                          f"{'Resolve the night (🧮), apply, post the story, then ☀️ Day.' if nxt == 'day' else 'Tally (🗳), execute, then 🌙 Night.'}",
                 reply_markup=gm_panel_kb())


# ---------------- GM text commands ----------------

@gm_only
async def cmd_setgroup(update: Update, ctx):
    if update.effective_chat.type == "private":
        await update.message.reply_text("Send /setgroup inside the game group.")
        return
    G()["group_id"] = update.effective_chat.id
    save()
    await update.message.reply_text(bi("✅ این گروه، گروه بازی شد.", "✅ This is now the game group."))


@gm_only
async def cmd_setchannel(update: Update, ctx):
    if not ctx.args:
        await update.message.reply_text("Usage: /setchannel -100xxxxxxxxxx (add the bot as channel admin first). /setchannel off to post maps in the group.")
        return
    G()["channel_id"] = None if ctx.args[0] == "off" else int(ctx.args[0])
    save()
    await update.message.reply_text("✅ channel set" if G()["channel_id"] else "✅ maps go to the group")


@gm_only
async def cmd_players(update: Update, ctx):
    for part in split_text(players_overview()):
        await update.message.reply_text(part)


@gm_only
async def cmd_roles(update: Update, ctx):
    await update.message.reply_text("\n".join(f"{k} — {r['fa']} / {r['en']} ({r['team']})" for k, r in ROLES.items()))


@gm_only
async def cmd_assign(update: Update, ctx):
    if len(ctx.args) < 2 or ctx.args[1] not in ROLES:
        await update.message.reply_text("Usage: /assign <who> <role> [fake_role]  (see /roles)")
        return
    p = who(ctx.args[0])
    fake = ctx.args[2] if len(ctx.args) > 2 and ctx.args[2] in ROLES else None
    assign_role(p, ctx.args[1], fake)
    save()
    await update.message.reply_text(f"✅ {p['name']} = {role_name(p['role'],'en')}")
    await dm(ctx.bot, p["id"], role_card(p, "fa"), role_card(p, "en"), reply_markup=main_menu(p, p["lang"]))


@gm_only
async def cmd_unassign(update: Update, ctx):
    p = who(ctx.args[0])
    p["role"] = None
    save()
    await update.message.reply_text(f"✅ {p['name']} has no role")


@gm_only
async def cmd_kick(update: Update, ctx):
    p = who(ctx.args[0])
    G()["players"].pop(str(p["id"]), None)
    save()
    await update.message.reply_text(f"✅ removed {p['name']}")


@gm_only
async def cmd_day(update: Update, ctx):
    await do_phase(ctx.bot, "day")
    await update.message.reply_text("☀️", reply_markup=gm_panel_kb())


@gm_only
async def cmd_night(update: Update, ctx):
    await do_phase(ctx.bot, "night")
    await update.message.reply_text("🌙", reply_markup=gm_panel_kb())


@gm_only
async def cmd_lock(update: Update, ctx):
    await do_lock(ctx.bot)


@gm_only
async def cmd_resolve(update: Update, ctx):
    g = G()
    if g["phase"] != "night":
        await update.message.reply_text("Night only.")
        return
    g["pending"] = resolve_night(g)
    save()
    await send_report(ctx.bot, update.effective_chat.id, lang_of(update.effective_user.id))


@gm_only
async def cmd_tally(update: Update, ctx):
    ranked, notes = actions.tally(G())
    await update.message.reply_text("\n".join(f"{pl(pid)['name']}: {v:g}" for pid, v in ranked) or "No votes.")


@gm_only
async def cmd_execute(update: Update, ctx):
    await execute(ctx.bot, who(ctx.args[0]), update.message)


@gm_only
async def cmd_map(update: Update, ctx):
    g = G()
    await update.message.reply_photo(render(g, gm=True, title=f"GM · {g['phase']} {g['cycle']}"))


@gm_only
async def cmd_publicmap(update: Update, ctx):
    await post_public_map(ctx.bot)


@gm_only
async def cmd_hp(update: Update, ctx):
    p = who(ctx.args[0])
    p["hp"] = int(ctx.args[1])
    save()
    await update.message.reply_text(f"✅ {p['name']} hp {p['hp']}")


@gm_only
async def cmd_coins(update: Update, ctx):
    p = who(ctx.args[0])
    v = ctx.args[1]
    p["coins"] = p["coins"] + int(v) if v[0] in "+-" else int(v)
    save()
    await update.message.reply_text(f"✅ {p['name']} coins {p['coins']}")


@gm_only
async def cmd_pos(update: Update, ctx):
    p = who(ctx.args[0])
    if ctx.args[1] not in SQUARES:
        raise GameError("Unknown square")
    p["pos"] = ctx.args[1]
    if G()["locked"] and G()["phase"] == "night":
        p["night_pos"] = ctx.args[1]
    save()
    await update.message.reply_text(f"✅ {p['name']} at {p['pos']}")


@gm_only
async def cmd_give(update: Update, ctx):
    p = who(ctx.args[0])
    if ctx.args[1] not in ITEMS:
        await update.message.reply_text("Items: " + ", ".join(ITEMS))
        return
    p["items"].append(ctx.args[1])
    save()
    await update.message.reply_text(f"✅ {p['name']} +{ctx.args[1]}")
    await dm(ctx.bot, p["id"], f"🎁 آیتم: {item_line(ctx.args[1],'fa')}", f"🎁 Item: {item_line(ctx.args[1],'en')}")


@gm_only
async def cmd_unit(update: Update, ctx):
    p = who(ctx.args[0])
    if ctx.args[1] not in UNIT_PRICES:
        await update.message.reply_text("Units: " + ", ".join(UNIT_PRICES))
        return
    p["units"][ctx.args[1]] = int(ctx.args[2])
    save()
    await update.message.reply_text(f"✅ {p['name']} {ctx.args[1]}={ctx.args[2]}")


@gm_only
async def cmd_charge(update: Update, ctx):
    p = who(ctx.args[0])
    p["charges"][ctx.args[1]] = int(ctx.args[2])
    save()
    await update.message.reply_text(f"✅ {p['name']} {ctx.args[1]}={ctx.args[2]}")


@gm_only
async def cmd_kill(update: Update, ctx):
    p = who(ctx.args[0])
    store.backup()
    actions.kill(G(), p, "gm")
    save()
    await announce_death(ctx.bot, p)
    await check_win(ctx.bot)


@gm_only
async def cmd_revive(update: Update, ctx):
    p = who(ctx.args[0])
    p["alive"] = True
    if p["hp"] <= 0:
        p["hp"] = ROLES[p["role"]]["hp"] // 2
    save()
    await update.message.reply_text(f"✅ {p['name']} revived (hp {p['hp']})")


@gm_only
async def cmd_cult(update: Update, ctx):
    p = who(ctx.args[0])
    p["cult"] = ctx.args[1] == "on"
    save()
    await update.message.reply_text(f"✅ {p['name']} cult={p['cult']}")


@gm_only
async def cmd_route(update: Update, ctx):
    rid, st = ctx.args[0], ctx.args[1]
    if rid not in board.all_routes(G()) or st not in ("ok", "broken", "mined"):
        await update.message.reply_text("Routes: " + ", ".join(f"{r} {board.route_name(G(), r, 'en')}" for r in board.all_routes(G())))
        return
    G()["route_state"][rid] = st
    save()
    await update.message.reply_text(f"✅ {rid} {st}")


@gm_only
async def cmd_dig(update: Update, ctx):
    kind = ctx.args[2] if len(ctx.args) > 2 else "road"
    rid = actions.dig_route(G(), ctx.args[0], ctx.args[1], kind)
    save()
    await update.message.reply_text(f"✅ new route {rid}")


@gm_only
async def cmd_damage(update: Update, ctx):
    G()["loc_damage"][ctx.args[0]] = int(ctx.args[1])
    save()
    await update.message.reply_text(f"✅ {ctx.args[0]} damage {ctx.args[1]}%")


@gm_only
async def cmd_acts(update: Update, ctx):
    for part in split_text(acts_overview(lang_of(update.effective_user.id)) or "No acts."):
        await update.message.reply_text(part)


@gm_only
async def cmd_actadd(update: Update, ctx):
    p = who(ctx.args[0])
    t = ctx.args[1]
    target = str(who(ctx.args[2])["id"]) if len(ctx.args) > 2 and ctx.args[2] != "-" else None
    extra = {}
    for kv in ctx.args[3:]:
        k, _, v = kv.partition("=")
        if k == "targets":
            extra[k] = [str(who(x)["id"]) for x in v.split(",")]
        elif k in ("war", "target2"):
            extra[k] = str(who(v)["id"])
        elif k == "wire":
            extra[k] = int(v)
        else:
            extra[k] = v
    G()["acts"].setdefault(str(p["id"]), []).append({"type": t, "target": target, "extra": extra})
    save()
    await update.message.reply_text(f"✅ {p['name']}: {t} {target or ''} {extra}")


@gm_only
async def cmd_actclear(update: Update, ctx):
    p = who(ctx.args[0])
    G()["acts"].pop(str(p["id"]), None)
    save()
    await update.message.reply_text(f"✅ cleared {p['name']}")


@gm_only
async def cmd_say(update: Update, ctx):
    text = update.message.text.partition(" ")[2]
    if G()["group_id"] and text:
        await ctx.bot.send_message(G()["group_id"], text)


@gm_only
async def cmd_story(update: Update, ctx):
    text = update.message.text.partition(" ")[2]
    if not text:
        return
    for t in {G()["group_id"], G()["channel_id"]} - {None}:
        await ctx.bot.send_message(t, "📖 " + text)


@gm_only
async def cmd_win(update: Update, ctx):
    res = actions.winner_check(G())
    await update.message.reply_text("\n".join(f"{a}\n{b}" for a, b in res) or "No win condition met yet.")


@gm_only
async def cmd_log(update: Update, ctx):
    lines = [f"[{x['phase']} {x['cycle']}] {x['text']}" for x in G()["log"][-60:]]
    for part in split_text("\n".join(lines) or "empty"):
        await update.message.reply_text(part)


@gm_only
async def cmd_undo(update: Update, ctx):
    await update.message.reply_text("↩️ restored" if store.undo() else "nothing to undo")


@gm_only
async def cmd_reset(update: Update, ctx):
    if ctx.args != ["confirm"]:
        await update.message.reply_text("This wipes the whole game. Send: /reset confirm   (add 'keep' to keep registered players: /reset confirm keep)")
        return
    store.backup()
    old = G()
    g = new_game()
    g["group_id"], g["channel_id"], g["gm_ids"], g["gm_lang"] = old["group_id"], old["channel_id"], old["gm_ids"], old.get("gm_lang", {})
    store.g = g
    save()
    await update.message.reply_text("🧹 New game.")


# ---------------- test mode ----------------

TEST_ROLES = ["godfather", "zombie", "zombie", "zombie_doctor", "undead", "bomber", "yakuza",
              "clown", "cultist", "thief",
              "hero", "priest", "priest", "doctor", "spy", "saboteur", "apothecary", "sniper",
              "cult_hunter", "musketeer", "judge", "doctor", "saboteur", "priest"]


@gm_only
async def cmd_fake(update: Update, ctx):
    """/fake 24 — add fake test players with a full role spread. /fake clear — remove them."""
    g = G()
    if ctx.args and ctx.args[0] == "clear":
        for pid in [k for k, v in g["players"].items() if v.get("fake")]:
            g["players"].pop(pid)
        g.get("as", {}).clear()
        save()
        await update.message.reply_text("🧹 fake players removed")
        return
    n = int(ctx.args[0]) if ctx.args else 24
    roles = TEST_ROLES[:]
    random.shuffle(roles)
    start = min([int(k) for k in g["players"] if int(k) < 0] + [0])
    made = []
    for i in range(n):
        uid = start - 1 - i
        P = new_player(uid, f"Test{abs(uid):02d}", None)
        P["fake"] = True
        P["lang"] = lang_of(update.effective_user.id)
        assign_role(P, roles[i % len(roles)])
        if P["role"] == "godfather":
            P["fake_role"] = "doctor"
        g["players"][str(uid)] = P
        made.append(f"{P['name']}={P['role']}")
    save()
    await update.message.reply_text("🧪 " + ", ".join(made) + "\n\nPlay as one: /as Test01 · back to GM: /as off · random moves/acts/votes for all fakes: /autoplay")


@gm_only
async def cmd_as(update: Update, ctx):
    g = G()
    uid = str(update.effective_user.id)
    if not ctx.args or ctx.args[0] == "off":
        g.setdefault("as", {}).pop(uid, None)
        save()
        await update.message.reply_text("👑 back to GM")
        return
    P = who(ctx.args[0])
    g.setdefault("as", {})[uid] = str(P["id"])
    save()
    await update.message.reply_text(f"🎭 You are now playing as {P['name']} ({role_name(P['role'],'en') if P['role'] else '-'}). "
                                    "Their DMs come to you. /menu", reply_markup=main_menu(P, P["lang"]) if P["role"] else None)


@gm_only
async def cmd_autoplay(update: Update, ctx):
    """Random moves, darts, acts (night) or votes (day) for every fake player who hasn't done them."""
    g = G()
    rng = random.Random()
    done = {"moves": 0, "acts": 0, "votes": 0, "darts": 0}
    fakes = [p for p in alive_players(g) if p.get("fake")]
    for p in fakes:
        if not g["locked"] and not p["moved"]:
            roll = rng.randint(1, 6)
            p["move_roll"] = roll
            opts = actions.move_options(g, p, roll)
            if opts:
                dest = rng.choice(list(opts))
                actions.do_move(g, p, dest, opts[dest])
                done["moves"] += 1
        if not p["darts"]["money"]:
            actions.money_dart(g, p, rng.randint(1, 6))
            actions.item_dart(g, p, rng.randint(1, 6), rng)
            done["darts"] += 1
        others = [x for x in alive_players(g) if x["id"] != p["id"]]
        if g["phase"] == "night" and not g["acts"].get(str(p["id"])) and others:
            t = rng.choice(["attack", "attack", "protect", "defuse", "spy"])
            g["acts"][str(p["id"])] = [{"type": t, "target": str(rng.choice(others)["id"]), "extra": {}}]
            done["acts"] += 1
        if g["phase"] == "day" and str(p["id"]) not in g["votes"] and others:
            g["votes"][str(p["id"])] = str(rng.choice(others)["id"])
            done["votes"] += 1
    save()
    await update.message.reply_text(f"🤖 autoplay: {done}")


async def cmd_whoami(update: Update, ctx):
    await update.message.reply_text(f"id: {update.effective_user.id} · chat: {update.effective_chat.id}")


async def on_error(update, ctx):
    logger.exception("error", exc_info=ctx.error)


def build_app(token):
    app = Application.builder().token(token).build()
    player_cmds = {"start": cmd_start, "menu": cmd_menu, "lang": cmd_lang, "help": cmd_help, "status": cmd_status,
                   "slots": cmd_slots, "taxi": cmd_taxi, "shoot": cmd_shoot, "bet": cmd_bet, "whoami": cmd_whoami}
    gm_cmds = {"gm": cmd_gm, "claimgm": gm_only(cmd_claimgm), "setgroup": cmd_setgroup, "setchannel": cmd_setchannel,
               "players": cmd_players, "roles": cmd_roles, "assign": cmd_assign, "unassign": cmd_unassign, "kick": cmd_kick,
               "day": cmd_day, "night": cmd_night, "lock": cmd_lock, "resolve": cmd_resolve, "tally": cmd_tally,
               "execute": cmd_execute, "map": cmd_map, "publicmap": cmd_publicmap, "hp": cmd_hp, "coins": cmd_coins,
               "pos": cmd_pos, "give": cmd_give, "unit": cmd_unit, "charge": cmd_charge, "kill": cmd_kill,
               "revive": cmd_revive, "cult": cmd_cult, "route": cmd_route, "dig": cmd_dig, "damage": cmd_damage,
               "acts": cmd_acts, "actadd": cmd_actadd, "actclear": cmd_actclear, "say": cmd_say, "story": cmd_story,
               "win": cmd_win, "log": cmd_log, "undo": cmd_undo, "reset": cmd_reset,
               "fake": cmd_fake, "as": cmd_as, "autoplay": cmd_autoplay}
    for name, fn in {**player_cmds, **gm_cmds}.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
    jq = app.job_queue
    jq.run_daily(job_lock, time=datetime.time(LOCK_HOUR, 0, tzinfo=TZ), name="lock")
    jq.run_daily(job_midnight, time=datetime.time(0, 0, tzinfo=TZ), name="midnight")
    return app


def main():
    token = os.environ.get("BOT_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        seen = sorted(k for k in os.environ if "TOKEN" in k.upper() or k in ("GM_IDS", "DATA_DIR"))
        raise SystemExit("BOT_TOKEN is empty or missing. Bot-related variables this process can see: "
                         + (", ".join(repr(k) for k in seen) or "none")
                         + ". On Railway: after adding variables, click 'Deploy' on the staged-changes banner.")
    if ":" not in token:
        raise SystemExit("BOT_TOKEN doesn't look like a BotFather token (it should contain ':').")
    if not ENV_GMS:
        logger.warning("GM_IDS is empty: the first person to send /claimgm becomes GM.")
    build_app(token).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
