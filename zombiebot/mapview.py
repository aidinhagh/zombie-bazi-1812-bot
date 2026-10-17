"""Maps are always shown twice: a picture, and the same information as a list."""
from telegram.error import TelegramError

from . import actions, board
from .board import SQUARES, CITIES
from .common import G, kb, chunks, dm, dm_photo, lang_of, num, phase_label, logger
from .data.locations import LOCATIONS, UNIT_NAMES
from .render import render


def webapp_url():
    from .web import webapp_url as w
    return w()

from .state import alive_players
from .texts import L


def sq_name(sq, lang):
    return board.square_name(sq, lang)


def ordered_choices(g, p):
    """Movement choices in a stable order: cities first, then nearer squares. Returns [(n, square, path)]."""
    opts = actions.move_options(g, p, p.get("move_roll") or 0)
    order = sorted(opts, key=lambda s: (SQUARES[s]["kind"] != "city", len(opts[s]), s))
    return [(i + 1, s, opts[s]) for i, s in enumerate(order)]


def route_lines(g, lang):
    out = []
    for rid, st in sorted(g["route_state"].items()):
        if st == "ok":
            continue
        word = {"broken": ("خراب", "broken"), "mined": ("مین‌گذاری", "mined")}[st]
        out.append(f"⛔ {board.route_name(g, rid, lang)}: {L(lang, *word)}")
    for r in g.get("extra_routes", []):
        out.append(L(lang, f"⛏ جاده جدید: {board.route_name(g, r['id'], lang)}", f"⛏ new road: {board.route_name(g, r['id'], lang)}"))
    return out


def published_balloons(g):
    """Spy-balloon reports made public in the current cycle (shown on the public map)."""
    return [b for b in g["balloons"] if b["kind"] == "spy" and b.get("published") and b["cycle"] == g["cycle"]
            and isinstance(b.get("result"), list)]


def unit_lines(g, lang, owners=False):
    out = []
    for u in g["units_on_map"]:
        nm = L(lang, *UNIT_NAMES[u["kind"]])
        who = f" — {g['players'][str(u['owner'])]['name']}" if owners and str(u["owner"]) in g["players"] else ""
        out.append(f"{'💣' if u['kind'] == 'cannon' else '⛵'} {nm} «{u.get('name') or '?'}»: {sq_name(u['square'], lang)}{who}")
    for b in published_balloons(g):
        seen = "، ".join(b["result"]) if b["result"] else "هیچ‌کس"
        out.append(f"🎈 بالن «{b.get('name') or '?'}» بر فراز {sq_name(b['target'], lang)}: {seen}")
    for city, pct in sorted(g["loc_damage"].items()):
        if pct:
            out.append(L(lang, f"🔥 {LOCATIONS[city]['fa']}: {num(pct)}٪ تخریب", f"🔥 {LOCATIONS[city]['en']}: {pct}% destroyed"))
    return out


def public_list(g, lang):
    lines = [L(lang, f"🗺 نقشه — {phase_label(lang, g)}", f"🗺 Map — {phase_label(lang, g)}")]
    units = unit_lines(g, lang)
    routes = route_lines(g, lang)
    lines.append("")
    lines.append(L(lang, "واحدها و خرابی‌ها:", "Units and damage:"))
    lines += units or [L(lang, "— هیچ", "— none")]
    lines.append("")
    lines.append(L(lang, "مسیرهای بسته:", "Closed routes:"))
    lines += routes or [L(lang, "— همه باز", "— all open")]
    return "\n".join(lines)


def positions(g, gm=True, chars=False):
    at = {}
    for p in alive_players(g):
        sq = p.get("pos")
        if sq:
            label = p["name"]
            if chars and p.get("char"):
                label += f" ({p['char']})"
            if gm and p.get("night_pos") and p["night_pos"] != sq:
                label += "*"
            at.setdefault(sq, []).append(label)
        if chars and p.get("fake_char") and p.get("fake_pos"):
            at.setdefault(p["fake_pos"], []).append(f"🃏{p['fake_char']} (جعلیِ {p['name']})")
    return at


def gm_list(g, lang):
    at = positions(g, chars=True)
    lines = [L(lang, f"🗺 همه جای بازیکن‌ها — {phase_label(lang, g)}", f"🗺 Where everyone is — {phase_label(lang, g)}"), ""]
    for c in CITIES:
        if c in at:
            lines.append(f"🏙 {LOCATIONS[c][lang]}: {'، '.join(at[c]) if lang == 'fa' else ', '.join(at[c])}")
    nodes = [s for s in at if s not in CITIES]
    for s in sorted(nodes):
        lines.append(f"◦ {sq_name(s, lang)}: {', '.join(at[s])}")
    nowhere = [p["name"] for p in alive_players(g) if not p.get("pos")]
    if nowhere:
        lines.append(L(lang, f"❔ هنوز روی نقشه نیستند: {'، '.join(nowhere)}", f"❔ Not on the map yet: {', '.join(nowhere)}"))
    extra = unit_lines(g, lang, owners=True) + route_lines(g, lang)
    if extra:
        lines += [""] + extra
    return "\n".join(lines)


def player_list(g, p, lang):
    lines = []
    here = p.get("pos")
    if here:
        lines.append(L(lang, f"📍 تو اینجایی: {sq_name(here, lang)}", f"📍 You are at: {sq_name(here, lang)}"))
        if here in LOCATIONS:
            lines.append("ℹ️ " + LOCATIONS[here]["desc_" + lang])
        nbrs = sorted({n for n, _ in board.adjacency(g).get(here, [])}, key=lambda s: (s not in CITIES, s))
        if nbrs:
            lines.append(L(lang, "همسایه‌ها: ", "Next squares: ") + " · ".join(sq_name(s, lang) for s in nbrs))
    else:
        lines.append(L(lang, "هنوز روی نقشه نیستی — از «حرکت» یک شهر انتخاب کن.", "You're not on the map yet — pick a city from Move."))
    lines.append("")
    lines.append(public_list(g, lang))
    return "\n".join(lines)


async def send_photo_and_list(bot, chat_or_uid, photo, text, to_player=True, reply_markup=None):
    try:
        if to_player:
            await dm_photo(bot, chat_or_uid, photo)
            await dm(bot, chat_or_uid, text, text, reply_markup=reply_markup)
        else:
            await bot.send_photo(chat_or_uid, photo)
            await bot.send_message(chat_or_uid, text, reply_markup=reply_markup)
    except TelegramError as e:
        logger.warning("map send failed: %s", e)


async def send_player_map(bot, p, reply_markup=None):
    g = G()
    lang = lang_of(p["id"])
    pic = render(g, title=f"{p['name']} · {phase_label('fa', g)}", you=p.get("pos"))
    await send_photo_and_list(bot, p["id"], pic, player_list(g, p, lang), reply_markup=reply_markup)


async def send_gm_map(bot, chat_id, lang):
    g = G()
    pic = render(g, gm=True, title=f"نقشه گاد · {phase_label('fa', g)}", names=positions(g))
    await send_photo_and_list(bot, chat_id, pic, gm_list(g, lang), to_player=False)


async def post_public_map(bot):
    g = G()
    target = g["channel_id"] or g["group_id"]
    if not target:
        return
    pic = render(g, title=f"نقشه {phase_label('fa', g)}", reports=published_balloons(g))
    text = public_list(g, "fa")
    from . import outbox
    await outbox.post(bot, "photo", "", data=pic.read(), chat=target)
    await outbox.post(bot, "text", text, chat=target)


async def send_move_map(bot, p):
    """After a roll: the map with every reachable square numbered, the same numbers as a list, and number buttons."""
    g = G()
    lang = lang_of(p["id"])
    choices = ordered_choices(g, p)
    roll = p.get("move_roll")
    plus = p["flags"].get("move_plus", 0)
    head = L(lang, f"🎲 تاس: {num(roll)}" + (f" (+{num(plus)})" if plus else "") + " — تا این تعداد خانه می‌تونی بری.",
             f"🎲 Roll: {roll}" + (f" (+{plus})" if plus else "") + " — move up to that many squares.")
    if not choices:
        await dm(bot, p["id"], head + L(lang, "\n⛔ هیچ مسیری باز نیست.", "\n⛔ No open route."), None)
        return
    lines = [head, L(lang, "شماره مقصد رو بزن:", "Tap the number of your destination:"), ""]
    for n, s, path in choices:
        steps = len(path)
        lines.append(f"{num(n, lang)}. {'🏙' if s in CITIES else '◦'} {sq_name(s, lang)} · {num(steps, lang)} {L(lang, 'خانه', 'sq')}")
    buttons = [(f"{num(n, lang)} {sq_name(s, lang)[:18]}", f"p:go:{s}") for n, s, _ in choices]
    rows = chunks(buttons, 2) + [[(L(lang, "↩️ منو", "↩️ Menu"), "p:home")]]
    url = webapp_url()
    if url:
        # the interactive map: tap a numbered square, watch the token walk there
        rows.insert(0, [("🗺 باز کردن نقشه و انتخاب مقصد", "webapp:" + url)])
        text = head + "\n\nنقشه را باز کن و روی یکی از شماره‌ها بزن — یا از دکمه‌های زیر انتخاب کن."
        await dm(bot, p["id"], text, reply_markup=kb(rows))
        return
    pic = render(g, title=f"{p['name']} · تاس {num(roll)}", highlight={s: n for n, s, _ in choices}, you=p.get("pos"))
    text = "\n".join(lines)
    await dm_photo(bot, p["id"], pic)
    await dm(bot, p["id"], text, text, reply_markup=kb(rows))


async def send_city_pick(bot, p, title_fa, title_en, prefix, first=False, only=None, nodes_cb=None, back_cb="p:home"):
    """First placement / free move / taxi: the cities, numbered on the map and in the list."""
    g = G()
    lang = lang_of(p["id"])
    url = webapp_url()
    if url and prefix == "p:go":
        cities = [c for c in CITIES if c != p.get("pos")] if p.get("pos") else list(CITIES)
        rows = [[("🗺 باز کردن نقشه و انتخاب شهر", "webapp:" + url)]]
        rows += chunks([(LOCATIONS[c]["fa"][:20], f"{prefix}:{c}") for c in cities], 2)
        if first:
            rows.append([("◦ خانه‌های خالی بین شهرها", "p:nodes")])
        rows.append([("↩️ منو", "p:home")])
        await dm(bot, p["id"], title_fa + "\nنقشه را باز کن — یا از دکمه‌ها انتخاب کن.", reply_markup=kb(rows))
        return
    cities = [c for c in CITIES if c != p.get("pos") or prefix != "p:go"]
    if only is not None:
        cities = [c for c in cities if c in only]
    pic = render(g, title=f"{p['name']}", highlight={c: i + 1 for i, c in enumerate(cities)}, you=p.get("pos"))
    lines = [L(lang, title_fa, title_en), ""] + [f"{num(i + 1, lang)}. {LOCATIONS[c][lang]}" for i, c in enumerate(cities)]
    buttons = [(f"{num(i + 1, lang)} {LOCATIONS[c][lang][:20]}", f"{prefix}:{c}") for i, c in enumerate(cities)]
    nb = nodes_cb or ("p:nodes" if first else None)
    rows = chunks(buttons, 2) + ([[("◦ خانه‌های خالی بین شهرها", nb)]] if nb else []) + [[(L(lang, "↩️ بازگشت", "↩️ Back"), back_cb)]]
    await dm_photo(bot, p["id"], pic)
    text = "\n".join(lines)
    await dm(bot, p["id"], text, text, reply_markup=kb(rows))
