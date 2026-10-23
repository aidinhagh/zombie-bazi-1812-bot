"""Everything that changes the game state, kept separate from Telegram so it can be tested."""
import random

from . import board
from .board import SQUARES, CITIES
from .data.items import ITEMS, RARITY_WEIGHT
from .data.locations import LOCATIONS, POWER_PRICES, UNIT_PRICES, TOLL, COINS_PER_HP, BANK_COINS
from .data.roles import ROLES, ZOMBIE, HUMAN, INDEP, role_name
from .engine import loc_of, flags_at
from .state import alive_players, log, next_id, team, give_characters, needs_fake_char, char_of

SLOT_TRIPLES = {1, 22, 43, 64}   # Telegram 🎰 values that show three of a kind


class GameError(Exception):
    def __init__(self, fa, en=None):
        super().__init__(en or fa)
        self.fa, self.en = fa, en or fa

    def text(self, lang):
        return self.fa if lang == "fa" else self.en


# ---------------- movement ----------------

def move_options(g, p, roll):
    """Return {square: path} the player can reach with this roll."""
    if p["pos"] is None:
        return {sq: [sq] for sq in SQUARES}       # first move: anywhere on the map, cities or empty squares, no dice
    if p["flags"].get("free_move"):
        return {c: [c] for c in CITIES if c != p["pos"]}
    steps = max(1, roll + p["flags"].get("move_plus", 0) - p["flags"].get("move_minus", 0))
    opts = board.reachable(g, p["pos"], steps)
    if g["phase"] == "night" and p.get("last_night_pos"):
        opts.pop(p["last_night_pos"], None)
    return opts


def do_move(g, p, dest, path):
    """Move along path, paying tolls. Returns list of (pid, fa, en) notices.

    Piracy: a cannon or ship planted on a route charges everyone who travels along that route — they don't
    have to stop on its square; passing any part of the route is enough (once per unit per move)."""
    notes = []
    start = p["pos"]
    if start is not None:
        notes += _tolls(g, p, [start] + list(path))
    p.setdefault("flags", {})["passed"] = list(path)   # squares crossed this phase (a unit can be planted on any of them)
    p.setdefault("move_history", []).append({"cycle": g["cycle"], "phase": g["phase"], "start": start, "dest": dest, "path": list(path), "routes": routes_used(g, [start] + list(path)) if start else []})
    p["pos"] = dest
    if g["phase"] == "night":
        p["night_pos"] = dest
    p["moved"] = True
    p["flags"].pop("move_plus", None)
    p["flags"].pop("move_minus", None)
    p["flags"].pop("free_move", None)
    log(g, f"{p['name']} → {dest}")
    return notes


def routes_used(g, squares):
    """Route ids travelled by a sequence of squares."""
    adj = board.adjacency(g, include_blocked=True)
    used = []
    for a, b in zip(squares, squares[1:]):
        for nb, rid in adj.get(a, []):
            if nb == b and rid not in used:
                used.append(rid)
    return used


def unit_label(u):
    from .data.locations import UNIT_NAMES
    return f"{UNIT_NAMES[u['kind']][0]} «{u.get('name') or '?'}»"


def _tolls(g, p, squares):
    out = []
    used = set(routes_used(g, squares))
    for u in g["units_on_map"]:
        if str(u["owner"]) == str(p["id"]) or u["kind"] not in ("cannon", "ship"):
            continue
        sq = SQUARES.get(u["square"])
        if not sq or (sq["route"] not in used and u["square"] not in squares[1:]):
            continue
        owner = g["players"].get(str(u["owner"]))
        if not owner or not owner["alive"]:
            continue
        if p["flags"].pop("toll_free", None):
            out.append((p["id"], f"جواز عبورت عوارض {unit_label(u)} رو پوشش داد.", ""))
            continue
        paid = min(p["coins"], TOLL)
        p["coins"] -= paid
        owner["coins"] += paid
        short = TOLL - paid
        hp_loss = -(-short // COINS_PER_HP) if short else 0
        p["hp"] -= hp_loss
        where = board.route_name(g, sq["route"])
        out.append((p["id"], f"🏴‍☠️ از مسیر {where} گذشتی و {unit_label(u)} عوارض گرفت: {paid} سکه" + (f" و {hp_loss} اچ‌پی" if hp_loss else ""), ""))
        out.append((owner["id"], f"🏴‍☠️ {p['name']} از مسیر {where} گذشت؛ {unit_label(u)} برایت {paid} سکه گرفت" + (f" (و {hp_loss} اچ‌پی از او کم شد)" if hp_loss else "") + ".", ""))
    return out


def damage(g, sq):
    return g["loc_damage"].get(sq, 0) if sq else 0


def ruined(g, sq):
    """100% destroyed: no positive effect at all, and its shop, radio, taxi, casino, slots… are closed."""
    return damage(g, sq) >= 100


def intact(g, sq):
    """The share of a place still standing, 0..1."""
    return (100 - min(100, damage(g, sq))) / 100


def _km(a, b):
    import math
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def taxi_targets(g):
    """Cities the London taxi can reach. Its radius shrinks with London's damage: at 0% any city,
    at 50% half the distance to the farthest city, at 100% no taxi at all."""
    if ruined(g, "london"):
        return []
    lon = CITIES["london"]
    far = max(_km(lon, c) for cid, c in CITIES.items() if cid != "london")
    radius = far * intact(g, "london")
    return [cid for cid, c in CITIES.items() if cid != "london" and _km(lon, c) <= radius + 1e-6]


def taxi(g, p, dest):
    if not g["locked"] or p.get("night_pos") != "london":
        raise GameError("تاکسی فقط بعد از قفل نقشه و وقتی در لندن هستی کار می‌کنه.",
                        "The taxi works only after the map lock while you're in London.")
    if ruined(g, "london"):
        raise GameError("لندن کاملاً ویران شده؛ تاکسی کار نمی‌کند.")
    if dest not in CITIES:
        raise GameError("مقصد نامعتبر.", "Invalid destination.")
    if dest not in taxi_targets(g):
        raise GameError(f"لندن {damage(g, 'london')}٪ ویران است و تاکسی تا آنجا نمی‌رود.")
    if p["flags"].get("taxi_used"):
        raise GameError("امشب یک بار تاکسی گرفتی.", "You already took the taxi tonight.")
    p["pos"] = p["night_pos"] = dest
    p["flags"]["taxi_used"] = True
    log(g, f"{p['name']} taxi → {dest} (secret)")


# ---------------- darts and slots ----------------

def loc_mod(g, sq, key):
    if sq not in LOCATIONS:
        return 0
    v = LOCATIONS[sq]["mods"].get(key, 0)
    if v > 0:
        v = v * (100 - g["loc_damage"].get(sq, 0)) // 100
    return v


def money_dart(g, p, value):
    coins = max(0, value - 1)
    if "money_plus2" in flags_at(p["pos"]):
        coins += 2 * (100 - g["loc_damage"].get(p["pos"], 0)) // 100
    coins += p["flags"].pop("money_dart", 0)
    p["coins"] += coins
    p["darts"]["money"] = True
    return coins


def item_power(g, p):
    return ROLES[p["role"]]["item"] + loc_mod(g, p["pos"], "item") + p["flags"].get("item_dart", 0)


def item_dart(g, p, value, rng=random):
    power = item_power(g, p)
    p["flags"].pop("item_dart", None)
    p["darts"]["item"] = True
    if value >= 7 - power and value > 1:
        keys = list(ITEMS)
        it = rng.choices(keys, weights=[RARITY_WEIGHT[ITEMS[k]["rarity"]] for k in keys])[0]
        p["items"].append(it)
        return it
    return None


def slot_pull(g, p, value):
    """Record one 🎰 pull. Returns state dict."""
    loc = p["pos"] if not g["locked"] else loc_of(p)
    fl = flags_at(loc)
    if "vienna_slots" in fl:
        limit, kind = 3, "vienna"
    elif "berlin_slots" in fl:
        limit, kind = 5, "berlin"
    else:
        raise GameError("اینجا ماشین اسلات نیست.", "There's no slot machine here.")
    if ruined(g, loc):
        raise GameError("این مکان کاملاً ویران شده و ماشین اسلات کار نمی‌کند.")
    s = p.get("slots") or {"kind": kind, "tries": 0, "hit": False, "done": False}
    if s["done"]:
        raise GameError("سهم امشبت از اسلات تموم شده.", "You've used tonight's slot pulls.")
    s["tries"] += 1
    if value in SLOT_TRIPLES:
        s["hit"] = True
        s["done"] = True
    elif s["tries"] >= limit:
        s["done"] = True
    s["left"] = limit - s["tries"]
    p["slots"] = s
    if kind == "vienna" and s["done"] and not s.get("applied"):
        # the factory's result is permanent (it stays after death and revival, and stacks with later visits)
        s["applied"] = True
        if s["hit"]:
            bonus = 20 * (100 - g["loc_damage"].get(loc, 0)) // 100
            p["perm"] = p.get("perm", 0) + bonus
            p["hp"] += bonus
            s["change"] = bonus
        else:
            p["perm"] = p.get("perm", 0) - 20
            s["change"] = -20
    return s


def berlin_revive(g, p, target):
    t = team(p)
    if g["revived_by_team"].get(t):
        raise GameError("تیم شما قبلاً یک نفر را زنده کرده.", "Your team has already revived someone.")
    if target["alive"] or target.get("unrevivable"):
        raise GameError("این بازیکن قابل احیا نیست.", "This player can't be revived.")
    if ruined(g, "berlin"):
        raise GameError("قبرستان برلین کاملاً ویران شده.")
    if not (p.get("slots") or {}).get("hit") or (p["slots"].get("kind") != "berlin"):
        raise GameError("اول باید در قبرستان سه‌تای یکسان بیاری.", "You need a three of a kind in the graveyard first.")
    target["alive"] = True
    target["hp"] = max(target["hp"], ROLES[target["role"]]["hp"] // 2)
    g["revived_by_team"][t] = True
    p["slots"]["hit"] = False
    log(g, f"{p['name']} revived {target['name']}")


# ---------------- shop ----------------

def buy_power(g, p, stat, n=1):
    if stat not in POWER_PRICES:
        raise GameError("قدرت نامعتبر.", "Unknown power.")
    cost = POWER_PRICES[stat] * n
    if p["coins"] < cost:
        raise GameError(f"سکه کافی نداری ({cost} لازمه).", f"Not enough coins ({cost} needed).")
    p["coins"] -= cost
    if stat == "hp":
        p["hp"] += n
    else:                                    # bought powers are permanent
        ps = p.setdefault("perm_stats", {})
        ps[stat] = ps.get(stat, 0) + n
    return cost


def buy_unit(g, p, unit):
    shop = LOCATIONS.get(p["pos"], {}).get("shop")
    if shop != unit:
        raise GameError("این آیتم اینجا فروخته نمی‌شه.", "That isn't sold here.")
    if ruined(g, p["pos"]):
        raise GameError("این شهر کاملاً ویران شده و فروشگاهش بسته است.")
    cost = UNIT_PRICES[unit]
    if p["coins"] < cost:
        raise GameError(f"سکه کافی نداری ({cost} لازمه).", f"Not enough coins ({cost} needed).")
    p["coins"] -= cost
    p["units"][unit] = p["units"].get(unit, 0) + 1
    p.setdefault("unit_origin", {})[unit] = "bought"
    return cost


TONIGHT_FLAGS = ("armor", "revenge", "reflect", "last_stand", "spy_mask", "defuse_immune", "extra_act")
UNTIL_USED_FLAGS = ("bullet_vest", "bomb_safe", "poison_safe", "pardon")
DAY_FLAGS = ("vote_guard", "muted")


def item_needs_target(item_key):
    return bool(ITEMS[item_key]["effect"].get("target"))


def use_item(g, p, item_key, target=None):
    """Use an item. Returns a Persian line saying what happened (shown to the player)."""
    if item_key not in p["items"]:
        raise GameError("این آیتم رو نداری.", "You don't have that item.")
    if not p["alive"]:
        raise GameError("مرده‌ها آیتم استفاده نمی‌کنند.")
    it = ITEMS[item_key]
    e = it["effect"]
    t = e["type"]
    T = None
    if e.get("target"):
        T = g["players"].get(str(target)) if target is not None else None
        if not T or not T["alive"]:
            raise GameError("اول یک بازیکن زنده رو انتخاب کن.", "Pick a living player first.")
    msg = f"✅ {it['fa']}: {it['desc_fa']}"
    if t == "boost":
        for k, v in e["stats"].items():
            p["boost"][k] = p["boost"].get(k, 0) + v
        p["hp"] += e.get("hp", 0)
        msg += " — روی اکت‌های شب حساب می‌شه."
    elif t == "heal":
        p["hp"] += e["hp"]
        msg += f" — اچ‌پی الان: {p['hp']}"
    elif t == "coins":
        p["coins"] += e["n"]
        msg += f" — سکه‌ها الان: {p['coins']}"
    elif t in ("move_plus", "money_dart", "item_dart", "vote_plus", "armor", "vote_guard"):
        p["flags"][t] = p["flags"].get(t, 0) + e["n"]
    elif t in ("revenge", "reflect"):
        p["flags"][t] = max(p["flags"].get(t, 0), e["pct"])
    elif t == "reroll":
        if not p["moved"] and p.get("move_roll"):
            p["move_roll"] = None
        else:
            raise GameError("فقط بعد از ریختن تاس و قبل از حرکت.", "Only after rolling and before moving.")
    elif t in ("free_move", "toll_free", "hide", "ignore_neg", "last_stand", "spy_mask", "defuse_immune",
               "extra_act") + UNTIL_USED_FLAGS:
        p["flags"][t] = True
    elif t == "extra_dart":
        if not p["darts"].get(e["kind"]):
            raise GameError("هنوز دارت این فازت رو ننداختی؛ اول اونو بنداز.", "Throw this phase's dart first.")
        p["darts"][e["kind"]] = False
        msg += " — از «🎯 دارت» بندازش."
    elif t == "unit":
        p["units"][e["unit"]] = p["units"].get(e["unit"], 0) + 1
        p.setdefault("unit_origin", {})[e["unit"]] = "bought"
        msg += " — در «🎒 کوله» ازش استفاده کن."
    elif t == "mute":
        T["flags"]["muted"] = True
        msg = f"✅ {it['fa']}: امروز رأی {T['name']} صفر حساب می‌شه."
    elif t == "slow":
        T["flags"]["move_minus"] = T["flags"].get("move_minus", 0) + e["n"]
        msg = f"✅ {it['fa']}: تاس حرکت بعدی {T['name']} {e['n']} تا کم می‌شه."
    elif t == "pickpocket":
        n = min(e["n"], T["coins"])
        T["coins"] -= n
        p["coins"] += n
        msg = f"✅ {it['fa']}: {n} سکه از {T['name']} برداشتی."
    elif t == "trace":
        where = board.square_name(T["pos"]) if T.get("pos") else "هنوز روی نقشه نیست"
        msg = f"🕵️ {it['fa']}: {T['name']} الان اینجاست: {where}"
    elif t == "reveal":
        from .engine import spy_view
        msg = f"📁 {it['fa']}: رنگ {T['name']}: {spy_view(g, T, False, 'fa')}"
    p["items"].remove(item_key)
    log(g, f"{p['name']} used {item_key}" + (f" on {T['name']}" if T else ""))
    return msg


def active_effects(p):
    """Short Persian lines for the item effects a player has waiting."""
    f, out = p["flags"], []
    names = {"attack": "حمله", "protect": "محافظت", "defuse": "خنثی", "spy": "جاسوسی", "stealth": "مخفی‌کاری", "all": "همه قدرت‌ها"}
    for k, v in p.get("boost", {}).items():
        out.append(f"{names.get(k, k)} {v:+d} امشب")
    if p.get("perm"):
        out.append(f"همه قدرت‌ها {p['perm']:+d} (دائمی، کارخانه)")
    for k, v in (p.get("perm_stats") or {}).items():
        out.append(f"{names.get(k, k)} {v:+d} (خریده‌شده، دائمی)")
    if p.get("legend"):
        from .data.legendary import LEGENDARY
        for k in p["legend"]:
            if k in LEGENDARY:
                out.append(f"🌟 {LEGENDARY[k]['fa']}: {LEGENDARY[k]['desc_fa']}")
    labels = {"move_plus": "حرکت بعدی +{}", "move_minus": "حرکت بعدی −{}", "money_dart": "دارت پول بعدی +{}",
              "item_dart": "دارت آیتم بعدی +{}", "vote_plus": "رأی بعدی +{}", "armor": "زره امشب {}",
              "vote_guard": "رأی‌های علیه تو امروز −{}", "revenge": "انتقام امشب {}٪", "reflect": "بازتاب حمله امشب {}٪"}
    for k, fmt in labels.items():
        if f.get(k):
            out.append(fmt.format(f[k]))
    simple = {"free_move": "حرکت آزاد", "toll_free": "بدون عوارض", "hide": "پنهان از بالن امشب",
              "ignore_neg": "منفی‌های مکان امشب نه", "last_stand": "اراده آهنین امشب", "spy_mask": "نقاب امشب",
              "defuse_immune": "خنثی‌ناپذیر امشب", "extra_act": "یک اکت اضافه امشب", "bullet_vest": "جلیقه ضدگلوله",
              "bomb_safe": "ایمن از بمب", "poison_safe": "ایمن از سم", "pardon": "عفو از اعدام", "muted": "رأیت امروز صفر است"}
    for k, v in simple.items():
        if f.get(k):
            out.append(v)
    return out


# ---------------- units on the board ----------------

def place_spots(g, p, unit):
    """Placeable nodes: current/passed squares, plus neighbors of the current city."""
    cands = [p["pos"]] + [x for x in p["flags"].get("passed", []) if x != p["pos"]]
    if p['pos'] in board.CITIES:
        cands += [sq for sq, _ in board.adjacency(g, include_blocked=True).get(p['pos'], [])]
    want_sea = unit == "ship"
    return [x for x in dict.fromkeys(cands) if x in SQUARES and SQUARES[x]["kind"] == "node" and SQUARES[x]["sea"] == want_sea]


def place_unit(g, p, unit, where=None, name=None):
    if g["locked"]:
        raise GameError("نقشه قفل شده؛ تا فاز بعد صبر کن.", "The map is locked until the next phase.")
    if p["units"].get(unit, 0) < 1:
        raise GameError("این واحد رو نداری.", "You don't have that unit.")
    sq = SQUARES.get(where or p["pos"])
    if not sq or sq["kind"] != "node":
        raise GameError("فقط روی خانه خالی (بین شهرها) می‌شه کاشت.", "You can only place it on an empty square between cities.")
    if unit == "cannon" and sq["sea"]:
        raise GameError("توپ جنگی فقط روی مسیر زمینی.", "Cannons go on land routes only.")
    if unit == "ship" and not sq["sea"]:
        raise GameError("کشتی فقط روی مسیر دریایی.", "Ships go on sea routes only.")
    if (where or p['pos']) not in place_spots(g, p, unit):
        raise GameError("فقط خانه فعلی، مسیر طی‌شده در همین فاز، یا خانه متصل به شهری که در آن هستی.",
                        "Place on your current square, this phase's path, or a node directly next to your city.")
    spot = where or p["pos"]
    if any(u["square"] == spot and u["kind"] == unit and str(u["owner"]) == str(p["id"]) for u in g["units_on_map"]):
        raise GameError("قبلاً اینجا گذاشتی.", "You already have one here.")
    p["units"][unit] -= 1
    u = {"id": next_id(g, "u"), "kind": unit, "owner": p["id"], "square": spot, "name": name or random_unit_name()}
    g["units_on_map"].append(u)
    return u


UNIT_NAME_POOL = ["عقاب", "طوفان", "شاهین", "آذرخش", "ققنوس", "پلنگ", "توفان", "سیمرغ", "شبح", "رعد", "گرگ", "تندر",
                  "اژدها", "کلاغ", "نهنگ", "صخره", "شمشیر", "سپیده", "شب‌تاب", "سایه"]


def random_unit_name():
    return random.choice(UNIT_NAME_POOL) + " " + str(random.randint(2, 99))


def rename(g, p, kind, oid, name):
    """Name a planted unit or a launched balloon (only its owner can)."""
    name = " ".join(str(name).split())[:24]
    if not name:
        raise GameError("اسم خالی است.", "")
    pool = g["balloons"] if kind == "balloon" else g["units_on_map"]
    obj = next((x for x in pool if x["id"] == oid and str(x["owner"]) == str(p["id"])), None)
    if not obj:
        raise GameError("پیدا نشد.", "")
    obj["name"] = name
    return obj


def strike_route(g, p, unit, rid):
    """cannon: break a land route; mine: mine a sea route; ship: clear a mine; shovel: repair a road."""
    rmap = board.all_routes(g)
    if rid not in rmap or rid not in board.routes_touching(g, p["pos"]):
        raise GameError("این مسیر به خانه تو وصل نیست.", "That route doesn't touch your square.")
    r, status = rmap[rid], board.route_status(g, rid)
    if p["units"].get(unit, 0) < 1:
        raise GameError("این واحد رو نداری.", "You don't have that unit.")
    if unit == "cannon":
        owned = p["units"].get("cannon", 0) + sum(1 for u in g["units_on_map"] if u["kind"] == "cannon" and str(u["owner"]) == str(p["id"]))
        if p.get("cannon_strikes", 0) >= owned:
            raise GameError("هر توپ فقط یک بار می‌تواند جاده خراب کند.", "Each cannon can break a road only once.")
    used = p["flags"].setdefault("unit_used", {})
    if used.get(unit, 0) >= p["units"][unit]:      # units are kept: each one can be used once a phase
        raise GameError("این واحد را در همین فاز استفاده کردی؛ فاز بعد دوباره.", "Already used this phase.")
    if unit == "cannon":
        if r["kind"] != "road" or status != "ok":
            raise GameError("فقط مسیر زمینی سالم.", "Only an intact land route.")
        g["route_state"][rid] = "broken"
        p["cannon_strikes"] = p.get("cannon_strikes", 0) + 1
    elif unit == "mine":
        if r["kind"] != "sea" or status != "ok":
            raise GameError("فقط مسیر دریایی سالم.", "Only an open sea route.")
        g["route_state"][rid] = "mined"
    elif unit == "ship":
        if status != "mined":
            raise GameError("این مسیر مین ندارد.", "That route isn't mined.")
        g["route_state"][rid] = "ok"
    elif unit == "shovel":
        if r["kind"] != "road" or status != "broken":
            raise GameError("فقط جاده خراب را می‌شه تعمیر کرد.", "Only a broken road can be repaired.")
        g["route_state"][rid] = "ok"
        p["units"]["shovel"] -= 1                  # a shovel is used up
    if unit != "shovel":
        used[unit] = used.get(unit, 0) + 1
    log(g, f"{p['name']} {unit} on {rid}")


def dig_route(g, a, b, kind="road", owner=None):
    """GM adds a shovel-made route between two squares."""
    if a not in CITIES or b not in CITIES:
        raise GameError("جاده جدید فقط از یک شهر به شهر دیگر ساخته می‌شود.", "New roads join two cities.")
    rid = next_id(g, "x")
    g["extra_routes"].append({"id": rid, "from": a, "to": b, "kind": kind, "nodes": [], "km": 0, "owner": owner})
    return rid


def launch_balloon(g, p, kind, target):
    key = kind + "_balloon"
    if p["units"].get(key, 0) < 1:
        raise GameError("بالن نداری.", "You have no balloon.")
    if target not in SQUARES:
        raise GameError("مکان نامعتبر.", "Unknown place.")
    if kind == "war":
        last = p.get("war_cycle")
        if last is not None and g["cycle"] - last < 2:
            raise GameError("بالن جنگی یک شب استراحت لازم دارد؛ شب بعد دوباره می‌توانی بفرستی.",
                            "The war balloon needs a night's rest.")
        p["war_cycle"] = g["cycle"]
    origin = p.get("unit_origin", {}).get(key, "bought")
    flying = [x for x in g["balloons"] if str(x["owner"]) == str(p["id"]) and x["kind"] == kind
              and x["cycle"] == g["cycle"] and x.get("phase") == g["phase"]]
    if len(flying) >= p["units"][key]:          # balloons come back: each flies once a phase
        raise GameError("بالنت در همین فاز پرواز کرده؛ فاز بعد دوباره می‌توانی بفرستی.", "Your balloon already flew this phase.")
    old = [x for x in g["balloons"] if str(x["owner"]) == str(p["id"]) and x["kind"] == kind and x.get("name")]
    b = {"id": next_id(g, "b"), "kind": kind, "owner": p["id"], "target": target, "origin": origin,
         "cycle": g["cycle"], "phase": g["phase"], "result": None, "publish": None, "pct": None, "name": old[-1]["name"] if old else random_unit_name()}
    if kind == "spy":
        if p["role"] == "spy" and origin == "start":
            b["publish"] = True
        elif p["role"] == "zombie_doctor" and origin == "start":
            b["publish"] = False
    if kind == "war" and g["locked"]:
        b["result"] = "await_pct"           # after 20:00 the raid can be flown straight away
    if kind == "spy" and g["locked"]:
        b["result"] = balloon_sees(g, target)   # after 20:00 a spy balloon reports straight away
    g["balloons"].append(b)
    return b


# ---------------- 20:00 lock ----------------

def lock_map(g, rng=random):
    """Freeze positions, run lock-time location rules, resolve balloons, detect battles.
    Returns a summary dict used for the public map post and GM notes."""
    relock = g.pop("relock_positions_only", False)
    settled = g.pop("relock_settled_positions", {}) if relock else {}
    g["locked"] = True
    night = g["phase"] == "night"
    gm_notes, private = [], []
    give_characters(g, rng)
    for p in alive_players(g):
        p["public_pos"] = p["pos"]
        if needs_fake_char(p):
            if p.get("fake_pos") is None:   # never placed: the bot puts the fake character somewhere
                p["fake_pos"] = rng.choice(list(board.SQUARES))
                private.append((p["id"], f"🎭 شخصیت جعلی‌ات «{p['fake_char']}» را جایی نگذاشته بودی؛ ربات او را در {board.square_name(p['fake_pos'])} گذاشت.",
                                "Your fake character was placed for you."))
            p["fake_public_pos"] = p["fake_pos"]
        if not night:
            continue
        p["night_pos"] = p["pos"]
        if relock and settled.get(str(p["id"]), p["pos"]) == p["pos"]:
            continue  # Unchanged locations already settled; never charge/pay twice.
        loc = p["pos"]
        if loc is None:
            gm_notes.append((f"{p['name']} جایی روی نقشه انتخاب نکرده.", f"{p['name']} has no position."))
            continue
        if loc == p.get("last_night_pos"):
            gm_notes.append((f"{p['name']} دو شب پشت سر هم در {board.square_name(loc)} است!",
                             f"{p['name']} is in {board.square_name(loc,'en')} two nights in a row!"))
        fl = flags_at(loc)
        dmg = g["loc_damage"].get(loc, 0)
        if "hotel" in fl and dmg < 100:
            before = p["hp"]
            p["hp"] = p["hp"] // 2 - 10 if p["hp"] > 20 else p["hp"] - 10
            p["flags"]["hotel_immune"] = True
            private.append((p["id"], f"هتل: اچ‌پی {before}→{p['hp']}، فردا اعدام نمی‌شی.",
                            f"Hotel: hp {before}→{p['hp']}; you can't be executed tomorrow."))
            if p["hp"] <= 0:
                gm_notes.append((f"{p['name']} با هزینه هتل به اچ‌پی {p['hp']} رسید.", f"{p['name']} hit {p['hp']} hp from the hotel cost."))
        if "bank" in fl and dmg < 100 and loc == p.get('last_night_pos'):
            private.append((p['id'], '🏦 دو شب پشت سر هم در بانک مانده‌ای؛ امشب نه سکه بانک می‌گیری و نه اچ‌پی‌ات نصف حساب می‌شود.',
                            'Consecutive bank nights: no bank coins and no temporary HP penalty tonight.'))
        if "bank" in fl and dmg < 100 and loc != p.get('last_night_pos'):
            coins = BANK_COINS * (100 - dmg) // 100
            p["coins"] += coins
            private.append((p["id"], f"بانک: {coins} سکه گرفتی؛ امشب اچ‌پی‌ات نصف حساب می‌شه.",
                            f"Bank: you got {coins} coins; your hp counts as half tonight."))
        if "double_act_50" in fl and dmg < 100:
            p["double_act"] = False
            p["flags"]["wagram_roll"] = None    # the player throws a die: even = two acts tonight
            private.append((p["id"], LOCATIONS['wagram']['desc_fa'], LOCATIONS['wagram']['desc_en']))
        if "vote_plus" in fl:
            # Paris: +1 vote, minus the destroyed share (20% destroyed → +0.8)
            p["flags"]["vote_mod"] = round(p["flags"].get("vote_mod", 0) + intact(g, loc), 2)
        if "vote_minus" in fl:
            p["flags"]["vote_mod"] = p["flags"].get("vote_mod", 0) - 1
        if ("vienna_slots" in fl or "berlin_slots" in fl) and not ruined(g, loc):
            private.append((p["id"], "ماشین اسلات منتظرته: /slots", "The slot machine awaits: /slots"))
        if "taxi" in fl and not ruined(g, loc):
            private.append((p["id"], "می‌تونی امشب مخفیانه با تاکسی جابه‌جا بشی: /taxi", "You may secretly take a taxi tonight: /taxi"))
        if "radio" in fl and not ruined(g, loc):
            gm_notes.append((f"{p['name']} به رادیو دسترسی دارد.", f"{p['name']} has radio access."))
        if "casino" in fl and not ruined(g, loc):
            private.append((p["id"], "در کازینو هستی: با /bet شرط ببند.", "You're in the casino: challenge someone with /bet."))

    # balloons launched this phase
    for b in g["balloons"]:
        if b["result"] is not None or b["cycle"] != g["cycle"] or b.get("phase") != g["phase"]:
            continue
        if b["kind"] == "spy":
            seen = balloon_sees(g, b["target"])
            b["result"] = seen
        else:
            b["result"] = "await_pct"
    # battles: two ships / two cannons on one square, or a unit under a balloon
    by_sq = {}
    for u in g["units_on_map"]:
        by_sq.setdefault(u["square"], []).append(u)
    for b in g["balloons"]:
        if b["cycle"] == g["cycle"] and b.get("phase") == g["phase"]:
            by_sq.setdefault(b["target"], []).append({"id": b["id"], "kind": b["kind"] + "_balloon", "owner": b["owner"], "square": b["target"]})
    for sq, lst in by_sq.items():
        kinds = [x["kind"] for x in lst]
        owners = {str(x["owner"]) for x in lst}
        # two cannons on one square fight their own duel (artillery.py); the GM settles the rest
        fight = (kinds.count("ship") >= 2 or
                 (any(k in ("ship", "cannon") for k in kinds) and any(k.endswith("balloon") for k in kinds)))
        existing = any(f.get("cycle") == g["cycle"] and f.get("square") == sq
                       and {u["id"] for u in f.get("units", [])} == {u["id"] for u in lst} for f in g["battles"])
        if fight and len(owners) >= 2 and not existing:
            g["battles"].append({"id": next_id(g, "f"), "square": sq, "units": lst, "status": "open", "cycle": g["cycle"]})
    return {"gm_notes": gm_notes, "private": private}


def repair_places(g):
    """Each new night, a damaged place rebuilds 25% — unless it was bombed in the cycle just gone."""
    hit = g.setdefault("loc_hit", {})
    for sq, pct in list(g["loc_damage"].items()):
        if pct and hit.get(sq, -9) < g["cycle"]:
            g["loc_damage"][sq] = max(0, pct - 25)


def apply_war_balloon(g, b, pct):
    """GM enters how much of the place the bombing destroyed."""
    pct = max(0, min(100, int(pct)))
    sq = b["target"]
    g["loc_damage"][sq] = min(100, g["loc_damage"].get(sq, 0) + pct)
    g.setdefault("loc_hit", {})[sq] = g["cycle"]       # no repair the night after an attack
    b["pct"] = pct
    b["result"] = "done"
    hit = []
    for p in alive_players(g):
        if (loc_of(p) if g["phase"] == "night" else p["pos"]) == sq:
            loss = 10 * pct // 100
            p["hp"] -= loss
            hit.append((p, loss))
    return hit


# ---------------- applying a resolved night ----------------

def apply_effects(g, result):
    """Apply the GM-approved effects. Returns an outbox of messages for the bot to send."""
    out = []   # ("group", fa, en) | ("private", pid, fa, en) | ("bomb", bomb) | ("duel", duel) | ("poison", poison) | ("team", team, fa, en)
    cyc = g["cycle"]
    for e in result["effects"]:
        if not e.get("on"):
            continue
        t = e["t"]
        P = g["players"].get(str(e.get("pid"))) if e.get("pid") is not None else None
        if t == "death" and P and P["alive"]:
            kill(g, P, e.get("cause"), unrevivable=e.get("unrevivable", False))
            out.append(("death", P["id"]))
        elif t == "damage" and P:
            P["hp"] -= e["amount"]
        elif t == "convert" and P:
            P["cult"] = True
            if P["role"] == "clown":
                P["cult_lost_clown"] = True
                C = g["players"].get(str(e["by"]))
                if C:
                    C["no_recruit_until"] = cyc + 1
            out.append(("private", P["id"], "شما عضو فرقه شدید! هدفتان حالا ماندن در ۳ نفر آخر است.",
                        "You have joined the cult! Your goal is now to be among the last 3 alive."))
            out.append(("private", e["by"], f"{P['name']} عضو فرقه شد.", f"{P['name']} joined the cult."))
        elif t == "lose_item" and P:
            if e["item"] in P["items"]:
                P["items"].remove(e["item"])
                T = g["players"].get(str(e["to"]))
                if T:
                    T["items"].append(e["item"])
        elif t == "stolen_role":
            out.append(("private", P["id"], "🦹 نقشت دزدیده شد؛ امشب اکتت انجام نشد.", ""))
        elif t == "charge" and P:
            P["charges"][e["key"]] = max(0, P["charges"].get(e["key"], 0) + e["delta"])
        elif t == "poison" and P:
            po = {"id": next_id(g, "p"), "target": P["id"], "by": e["by"], "cycle": cyc, "status": "pending"}
            g["poisons"].append(po)
            out.append(("poison", po))
        elif t == "bomb" and P:
            bo = {"id": next_id(g, "k"), "target": P["id"], "by": e["by"], "wire": e["wire"], "status": "armed", "cycle": cyc,
                  "where": e.get("where") or loc_of(P)}
            g["bombs"].append(bo)
            out.append(("bomb", bo))
        elif t == "bullet" and P:
            P["bullets"].append(e["kind"])
            out.append(("private", P["id"], "یک تیر به تو رسید (نوعش معلوم نیست). در روز با /shoot شلیک کن.",
                        "You received a bullet (type unknown). Fire it during the day with /shoot."))
        elif t == "duel":
            du = {"id": next_id(g, "d"), "a": e["a"], "b": e["b"], "status": "pending", "rounds": [], "picks": {}}
            g["duels"].append(du)
            out.append(("duel", du))
        elif t == "private":
            if e.get("to_team"):
                out.append(("team", e["to_team"], e["fa"], e["en"]))
            else:
                out.append(("private", e["pid"], e["fa"], e["en"]))
    end_night(g)
    return out


def restore_used_units(g):
    """Units used to be spent when used; now they're kept. Give back the balloons people already flew (once)."""
    if g.get("units_restored_v1"):
        return 0
    g["units_restored_v1"] = True
    n = 0
    for b in g["balloons"]:
        P = g["players"].get(str(b["owner"]))
        if not P:
            continue
        key = b["kind"] + "_balloon"
        launched = len([x for x in g["balloons"] if str(x["owner"]) == str(P["id"]) and x["kind"] == b["kind"]])
        if P["units"].get(key, 0) < launched:
            n += launched - P["units"].get(key, 0)
            P["units"][key] = launched
    return n


def fix_self_war_bullets(g):
    """A musketeer can't hold his own war bullet (only he hands bullets out): turn it back into a charge."""
    n = 0
    for P in g["players"].values():
        if P.get("role") == "musketeer" and "war" in P.get("bullets", []):
            P["bullets"] = [b for b in P["bullets"] if b != "war"]
            n += 1
    return n


def drop_bad_dug_roads(g):
    """Remove dug roads that start from a square between cities (e.g. one dug across a mined sea lane).
    Returns [(route_name, [players who were on its ends])]."""
    out = []
    keep = []
    for r in g.get("extra_routes", []):
        if r["from"] in CITIES and r["to"] in CITIES:
            keep.append(r)
            continue
        name = board.route_name(g, r["id"])
        ends = {r["from"], r["to"]}
        near = [p for p in alive_players(g) if p.get("pos") in ends or ends & set(p["flags"].get("passed", []))
                or p.get("night_pos") in ends]
        g["route_state"].pop(r["id"], None)
        out.append((name, near))
    g["extra_routes"] = keep
    return out


def repair_half_applied(g):
    """Undo a night result that was applied but crashed before finishing (the GM can then apply it once).
    Counts how many times the damage went in, from the 'before' hp written in each damage line."""
    import re
    res = g.get("pending")
    if not res or g.get("applied_cycle") == g["cycle"]:
        return 0
    times = 0
    for e in res["effects"]:
        if e.get("on") and e["t"] == "damage" and e.get("amount"):
            m = re.search(r"\((\d+)→", e["fa"])
            P = g["players"].get(str(e.get("pid")))
            if m and P:
                times = max(times, round((int(m.group(1)) - P["hp"]) / e["amount"]))
    if times <= 0:
        return 0
    cyc = g["cycle"]
    for e in res["effects"]:
        if not e.get("on"):
            continue
        P = g["players"].get(str(e.get("pid"))) if e.get("pid") is not None else None
        t = e["t"]
        if t == "damage" and P:
            P["hp"] += e["amount"] * times
        elif t == "charge" and P:
            P["charges"][e["key"]] = P["charges"].get(e["key"], 0) - e["delta"] * times
        elif t == "bullet" and P:
            for _ in range(times):
                if e["kind"] in P["bullets"]:
                    P["bullets"].reverse(); P["bullets"].remove(e["kind"]); P["bullets"].reverse()
        elif t == "death" and P and not P["alive"] and P.get("death_cycle") == cyc:
            P["alive"] = True
        elif t == "lose_item" and P:
            T = g["players"].get(str(e["to"]))
            if T and e["item"] in T["items"] and e["item"] not in P["items"]:
                T["items"].remove(e["item"]); P["items"].append(e["item"])
    g["poisons"] = [x for x in g["poisons"] if not (x.get("cycle") == cyc and x["status"] == "pending")]
    g["bombs"] = [x for x in g["bombs"] if not (x.get("cycle") == cyc and x["status"] == "armed")]
    pairs = {(e["a"], e["b"]) for e in res["effects"] if e.get("on") and e["t"] == "duel"}
    g["duels"] = [x for x in g["duels"] if not (x["status"] == "pending" and (x["a"], x["b"]) in pairs)]
    log(g, f"repaired a half-applied night result (applied {times}x)")
    return times


def kill(g, P, cause=None, unrevivable=False):
    P["alive"] = False
    P["death_cycle"] = g["cycle"]
    P["unrevivable"] = P.get("unrevivable") or unrevivable
    g["units_on_map"] = [u for u in g["units_on_map"] if str(u["owner"]) != str(P["id"])]
    log(g, f"{P['name']} died ({cause})")


def death_announcement(P):
    """Player, character and role together. The godfather is read out with his fake character and fake role."""
    if P["role"] == "godfather":
        shown = P.get("fake_role") or P["role"]
        char = P.get("fake_char") or char_of(P)
    else:
        shown, char = P["role"], char_of(P)
    return (f"☠️ {P['name']} مُرد.\n🎭 شخصیت: {char}\n🎴 نقش: {role_name(shown)}",
            f"☠️ {P['name']} has died. Character: {char}. Role: {role_name(shown,'en')}")


def balloon_sees(g, sq):
    """What a spy balloon over a square reports: the story characters standing there — the real ones
    (unless hidden) and any fake characters placed there — alphabetically, so nobody can tell which is fake.
    The map itself is never public: only places with a balloon over them are reported."""
    seen = [char_of(p) for p in alive_players(g) if p["pos"] == sq and not p["flags"].get("hide")]
    seen += [p["fake_char"] for p in alive_players(g)
             if needs_fake_char(p) and p.get("fake_char") and p.get("fake_pos") == sq]
    return sorted(seen)


def set_fake_pos(g, p, sq):
    if not needs_fake_char(p):
        raise GameError("تو شخصیت جعلی نداری.", "You have no fake character.")
    if g["locked"]:
        raise GameError("نقشه تا فاز بعد قفل است.", "The map is locked until the next phase.")
    if sq not in board.SQUARES:
        raise GameError("این خانه روی نقشه نیست.", "Not a square.")
    p["fake_pos"] = sq


def end_night(g):
    for p in g["players"].values():
        for k, v in (p.get("bought") or {}).items():    # purchases made before powers became permanent
            ps = p.setdefault("perm_stats", {})
            ps[k] = ps.get(k, 0) + v
        p["boost"] = {}
        p["bought"] = {}
        for k in ("ignore_neg", "hide", "taxi_used") + TONIGHT_FLAGS:
            p["flags"].pop(k, None)
        p["slots"] = None
        p["double_act"] = False
        if p["alive"] and p.get("night_pos"):
            p["last_night_pos"] = p["night_pos"]
    g["acts"] = {}
    g["pending"] = None


# ---------------- phases ----------------

def start_phase(g, phase):
    g.pop("relock_positions_only", None)
    g.pop("relock_settled_positions", None)
    g["phase"] = phase
    give_characters(g)
    if phase == "night":
        repair_places(g)
    g["locked"] = False
    if phase == "night":
        g["cycle"] += 1
        g["acts"] = {}
        for p in g["players"].values():
            p["night_pos"] = None
    else:
        g["votes"] = {}
        g["vote_cancelled"] = False
    for p in g["players"].values():
        p["moved"] = False
        p["move_roll"] = None
        p["flags"].pop("passed", None)
        p["flags"].pop("unit_used", None)
        p["flags"].pop("wagram_roll", None)
        p["double_act"] = False
        p["darts"] = {"money": False, "item": False}
        if phase == "night":
            for k in DAY_FLAGS:
                p["flags"].pop(k, None)
            p["flags"].pop("hotel_immune", None)
            p["flags"].pop("vote_mod", None)
            if g["votes"].get(str(p["id"])):
                p["flags"].pop("vote_plus", None)


# ---------------- voting ----------------

def vote_weight(g, p):
    if p["flags"].get("muted"):
        return 0
    w = 1 + p["flags"].get("vote_mod", 0) + p["flags"].get("vote_plus", 0)
    return max(0, w)


def tally(g):
    """Returns (sorted [(pid, weighted_votes)], notes)."""
    totals = {}
    notes = []
    for voter, target in g["votes"].items():
        V = g["players"].get(voter)
        if not V or not V["alive"] or target is None:
            continue
        totals[target] = totals.get(target, 0) + vote_weight(g, V)
    for tid in list(totals):
        T = g["players"][tid]
        if T["flags"].get("vote_guard"):
            totals[tid] = max(0, totals[tid] - T["flags"]["vote_guard"])
            notes.append((f"{T['name']} آیتم دفاع در رأی‌گیری دارد (−{T['flags']['vote_guard']}).", ""))
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    return ranked, notes


def winner_check(g):
    alive = alive_players(g)
    n = len(alive)
    humans = [p for p in alive if team(p) == HUMAN and not p["cult"]]
    zombies = [p for p in alive if team(p) == ZOMBIE and not p["cult"]]
    indeps = [p for p in alive if team(p) == INDEP or p["cult"]]
    res = []
    if n <= 3:
        for role in ("clown", "thief"):
            for p in alive:
                if p["role"] == role and not p["cult"] and not p.get("cult_lost_clown"):
                    res.append((f"{role_name(role)} در ۳ نفر آخر است.", f"{role_name(role,'en')} is in the final 3."))
        if any(p["role"] == "cultist" or p["cult"] for p in alive):
            res.append(("فرقه در ۳ نفر آخر است.", "The cult is in the final 3."))
    if n <= 4 and any(p["role"] == "clown" and not p.get("cult_lost_clown") for p in alive):
        res.append(("دلقک در ۴ نفر آخر است → برد دلقک.", "The clown is in the final 4 → clown wins."))
    if not zombies and not indeps and humans:
        res.append(("همه زامبی‌ها و مستقل‌ها حذف شدند → برد انسان‌ها.", "All zombies and independents are gone → humans win."))
    if not indeps and zombies and len(zombies) >= len(humans):
        res.append(("زامبی‌ها برابر/بیشتر از انسان‌ها → برد زامبی‌ها.", "Zombies equal or outnumber humans → zombies win."))
    return res


def validate_wagram_roll(g, p):
    """Validate before asking Telegram to animate a die."""
    if g["phase"] != "night" or not g["locked"] or "double_act_50" not in flags_at(loc_of(p)):
        raise GameError("این تاس فقط شب و بعد از قفل نقشه در خانقاه است.", "")
    if p["flags"].get("wagram_roll") is not None:
        raise GameError("تاس خانقاه را ریخته‌ای.", "")


def wagram_roll(g, p, value):
    """The monastery die: an even number gives two acts tonight."""
    validate_wagram_roll(g, p)
    p["flags"]["wagram_roll"] = int(value)
    p["double_act"] = int(value) % 2 == 0
    return p["double_act"]
