"""Text helpers. The game runs in Persian only; the (fa, en) pairs are kept so English can come back later."""
from .data.roles import ROLES, SPECIALS, role_name
from .data.items import ITEMS
from .data.locations import LOCATIONS, UNIT_NAMES, POWER_PRICES, UNIT_PRICES
from . import board


def L(lang, fa, en):
    return fa


def bi(fa, en):
    return fa


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


def character_lines(p):
    """The story character (shown on the map and in the death announcement) and, for non-humans, the fake one."""
    out = []
    if p.get("char"):
        out.append(f"🎭 شخصیت تو در داستان: {p['char']}")
    if p.get("fake_char"):
        where = board.square_name(p["fake_pos"]) if p.get("fake_pos") else "هنوز جایی نگذاشتی"
        out.append(f"🃏 شخصیت جعلی: {p['fake_char']} · 📍 {where}")
        if p.get("role") == "godfather":
            out.append("وقتی بمیری، این شخصیت جعلی و نقش جعلی‌ات اعلام می‌شود.")
        else:
            out.append("این اسم هیچ‌جا اعلام نمی‌شود؛ فقط اگر بالن جاسوسی بالای جایی برود که گذاشته‌ایش، در گزارش بالن دیده می‌شود (دکمه «👤 شخصیت جعلی»).")
    return out


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
    lines += [""] + character_lines(p)
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
             "/menu منوی بازی (همه‌چیز از همین‌جا)\n/lang تغییر زبان\nدر گروه: #رای اسم برای رأی · #رایگیری برای نتیجه",
             "/menu the game menu (everything is there)\n/lang switch language\nIn the group: #رای name to vote · #رایگیری for the tally")


GM_HELP = """👑 /gm — the control room. Everything is in there.

Typed shortcuts if you want them:
/assign <who> <role> · /char <who> <name> · /fakechar <who> <name> · /nick <who> <nickname> · /pos <who> <square> · /hp <who> <n> · /coins <who> <n|+n|-n>
/give <who> <item> · /unit <who> <unit> <n> · /charge <who> <key> <n> · /route <id> ok|broken|mined
/dig <sqA> <sqB> · /damage <city> <pct> · /actadd <who> <type> <target> · /story <text> · /say <text>
/delete <name> | /delete all | reply + /delete (in the group: remove votes) · /setchannel -100… · /log · /undo
<who> = name, @username or roster number.
"""
