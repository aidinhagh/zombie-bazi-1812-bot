"""Bilingual text helpers. Private messages follow the player's language; group posts carry both."""
from .data.roles import ROLES, SPECIALS, role_name
from .data.items import ITEMS
from .data.locations import LOCATIONS, UNIT_NAMES, POWER_PRICES, UNIT_PRICES
from . import board


def L(lang, fa, en):
    return fa if lang == "fa" else en


def bi(fa, en):
    return f"{fa}\n\n{en}"


BTN = {
    "status": ("📋 وضعیت", "📋 Status"),
    "move": ("🎲 حرکت", "🎲 Move"),
    "darts": ("🎯 دارت", "🎯 Darts"),
    "act": ("🌙 اکت شب", "🌙 Night act"),
    "shop": ("🛒 فروشگاه", "🛒 Shop"),
    "items": ("🎒 آیتم‌ها", "🎒 Items"),
    "units": ("⚓ واحدها و بالن", "⚓ Units & balloons"),
    "vote": ("🗳 رأی", "🗳 Vote"),
    "lang": ("🌐 English", "🌐 فارسی"),
    "back": ("↩️ بازگشت", "↩️ Back"),
    "clear": ("🗑 پاک کردن اکت‌ها", "🗑 Clear my acts"),
    "abstain": ("✋ رأی نمی‌دم", "✋ Abstain"),
}

ACT_NAMES = {
    "attack": ("⚔️ حمله", "⚔️ Attack"),
    "protect": ("🛡 محافظت", "🛡 Protect"),
    "defuse": ("🧯 خنثی", "🧯 Defuse"),
    "spy": ("🔍 جاسوسی", "🔍 Spy"),
    "guess": ("🎭 حدس نقش (حمله قطعی)", "🎭 Guess role (certain kill)"),
    "cult_check": ("🕯 استعلام فرقه", "🕯 Cult check"),
    "bomb": ("💣 دادن بمب", "💣 Plant bomb"),
    "convert": ("🕯 فرقه کردن", "🕯 Convert"),
    "steal": ("🦹 دزدیدن نقش", "🦹 Steal role"),
    "poison": ("🧪 دادن سم", "🧪 Poison"),
    "bullets": ("🔫 دادن تیر", "🔫 Hand out bullets"),
    "duel": ("⚖️ تعیین دوئل", "⚖️ Order a duel"),
}

STAT_NAMES = {
    "attack": ("حمله", "Attack"), "protect": ("محافظت", "Protect"), "defuse": ("خنثی", "Defuse"),
    "spy": ("جاسوسی", "Spy"), "stealth": ("مخفی‌کاری", "Stealth"), "hp": ("اچ‌پی", "HP"), "item": ("آیتم", "Item"),
}


def btn(key, lang):
    return L(lang, *BTN[key])


def act_name(t, lang):
    return L(lang, *ACT_NAMES.get(t, (t, t)))


def stat_name(s, lang):
    return L(lang, *STAT_NAMES.get(s, (s, s)))


def unit_name(u, lang):
    return L(lang, *UNIT_NAMES[u])


def item_line(k, lang):
    it = ITEMS[k]
    return f"{it[lang]} — {it['desc_' + lang]}"


def role_card(p, lang):
    r = ROLES[p["role"]]
    team = {"zombie": ("زامبی", "Zombie"), "human": ("انسان", "Human"), "independent": ("مستقل", "Independent")}[r["team"]]
    lines = [
        L(lang, f"🎴 نقش شما: {r['fa']}", f"🎴 Your role: {r['en']}"),
        L(lang, f"تیم: {team[0]}", f"Team: {team[1]}"),
        "",
        " | ".join(f"{stat_name(s, lang)} {r[s]}" for s in ("attack", "protect", "defuse", "spy", "stealth", "hp", "item")),
    ]
    sp = SPECIALS.get(p["role"], [])
    if sp:
        lines.append(L(lang, "اکت‌های ویژه: ", "Special acts: ") + "، ".join(act_name(s, lang) for s in sp))
    if p["units"]:
        lines.append(L(lang, "شروع با: ", "Starting with: ") + ", ".join(f"{unit_name(u, lang)}×{n}" for u, n in p["units"].items() if n))
    if p["role"] == "godfather" and p.get("fake_role"):
        lines.append(L(lang, f"نقش جعلی: {role_name(p['fake_role'])}", f"Fake role: {role_name(p['fake_role'], 'en')}"))
    lines.append("")
    lines.append(L(lang, "منو: /menu", "Menu: /menu"))
    return "\n".join(lines)


def status_text(g, p, lang):
    if not p.get("role"):
        return L(lang, "ثبت‌نام شدی؛ منتظر نقش از گاد باش.", "You're registered; wait for the GM to give you a role.")
    r = ROLES[p["role"]]
    pos = board.square_name(p["pos"], lang) if p["pos"] else L(lang, "هنوز روی نقشه نیستی", "not on the map yet")
    lines = [
        f"{'💀' if not p['alive'] else '🧍'} {p['name']} — {r[lang]}" + (L(lang, " (فرقه)", " (cult)") if p["cult"] else ""),
        L(lang, f"اچ‌پی: {p['hp']}   سکه: {p['coins']}", f"HP: {p['hp']}   Coins: {p['coins']}"),
        L(lang, f"مکان: {pos}", f"Position: {pos}"),
    ]
    if p["pos"] in LOCATIONS:
        lines.append("ℹ️ " + LOCATIONS[p["pos"]]["desc_" + lang])
    if p["boost"]:
        lines.append(L(lang, "تقویت امشب: ", "Tonight's boosts: ") + ", ".join(f"{stat_name(k, lang) if k != 'all' else L(lang,'همه','all')} {v:+d}" for k, v in p["boost"].items()))
    if p["items"]:
        lines.append(L(lang, "آیتم‌ها: ", "Items: ") + ", ".join(ITEMS[i][lang] for i in p["items"]))
    units = {u: n for u, n in p["units"].items() if n}
    if units:
        lines.append(L(lang, "واحدها: ", "Units: ") + ", ".join(f"{unit_name(u, lang)}×{n}" for u, n in units.items()))
    ch = {k: v for k, v in p["charges"].items() if v}
    if ch:
        lines.append(L(lang, "شارژها: ", "Charges: ") + ", ".join(f"{k}×{v}" for k, v in ch.items()))
    if p["bullets"]:
        lines.append(L(lang, f"تیر در دست: {len(p['bullets'])} (/shoot)", f"Bullets held: {len(p['bullets'])} (/shoot)"))
    phase = {"lobby": ("لابی", "lobby"), "day": ("روز", "day"), "night": ("شب", "night")}[g["phase"]]
    lines.append(L(lang, f"فاز: {phase[0]} {g['cycle']}" + (" 🔒" if g["locked"] else ""),
                   f"Phase: {phase[1]} {g['cycle']}" + (" 🔒" if g["locked"] else "")))
    return "\n".join(lines)


def help_text(lang):
    return L(lang,
             "دستورها:\n/menu منوی بازی\n/status وضعیت\n/slots ماشین اسلات (وین/برلین)\n/taxi تاکسی لندن\n/shoot شلیک تیر در روز\n/bet شرط‌بندی در کازینو\n/lang تغییر زبان",
             "Commands:\n/menu game menu\n/status your status\n/slots slot machine (Vienna/Berlin)\n/taxi London taxi\n/shoot fire a bullet by day\n/bet casino bet\n/lang switch language")


GM_HELP = """GM commands / دستورهای گاد

Setup: /setgroup (send inside the group) · /setchannel <chat_id> · /players · /roles
/assign <who> <role> [fake_role] · /unassign <who> · /kick <who>

Phases: /gm (panel) · /day · /night · /lock · /resolve · /tally · /execute <who> · /map · /publicmap

Edits: /hp <who> <n> · /coins <who> <n> · /pos <who> <square> · /give <who> <item>
/unit <who> <unit> <n> · /charge <who> <key> <n> · /kill <who> · /revive <who>
/cult <who> on|off · /route <route_id> ok|broken|mined · /dig <sqA> <sqB> [road|sea]
/damage <city> <pct> · /acts · /actadd <who> <type> <target> [k=v] · /actclear <who>

Testing: /fake 24 · /fake clear · /as <who> · /as off · /autoplay

Posting: /say <text> (group) · /story <text> (group + channel) · /win · /log · /undo · /reset

<who> = roster number, @username or name. Square ids: city ids (london, paris, …) or node ids (n15 …).
"""
