"""Cannon duels — the Counter-Battery minigame.

Two or more cannons planted on the same square when the map locks at 20:00 fight each other, whatever their
owners' teams. The battle runs from that lock to the next one (20:00 the next day). It is turn based: each cannon
in turn has 2 hours to fire from the Mini App; if it doesn't, the turn passes on. A cannon whose hp reaches 0 is
destroyed and leaves the game. When one cannon is left it has won; the result goes to the group (after the GM's
approval) as an animation. If the time runs out first, the battle simply ends and the cannons stay.

Players only ever see unit names. Your own cannon flies your team's flag (humans: Britain, zombies: France,
independents: the Ottomans); every other cannon shows a random flag so nobody can tell whose it is.
"""
import math
import random
import time

from . import board
from .board import CITIES, SQUARES
from .data.locations import LOCATIONS
from .state import log, next_id, team

TURN_SECONDS = 2 * 3600
BATTLE_SECONDS = 24 * 3600
TEAM_FLAG = {"human": "gb", "zombie": "fr", "independent": "ot"}
DISPLAY_FLAGS = ["gb", "fr", "ot", "pr", "ru", "at", "es", "se"]

# same weather tables as the game page (Counter-Battery)
CLIMATE_OF = {"london": "temperate", "paris": "temperate", "birmingham": "temperate", "amsterdam": "temperate",
              "barcelona": "med", "milan": "med", "vienna": "temperate", "wagram": "temperate", "berlin": "temperate",
              "warsaw": "north", "copenhagen": "north", "stockholm": "north", "stpetersburg": "north", "moscow": "russia",
              "constantinople": "med"}
CLIMATE = {
    "temperate": {"clear": 3, "overcast": 3, "fog": 1.5, "rain": 2, "snow": 1, "storm": 1},
    "north": {"clear": 2, "overcast": 3, "fog": 1, "rain": 1.5, "snow": 2.5, "storm": 1},
    "russia": {"clear": 1.5, "overcast": 2, "fog": 1, "rain": 1, "snow": 5, "storm": 0.7},
    "med": {"clear": 5, "overcast": 2, "fog": 0.5, "rain": 1.5, "snow": 0, "storm": 1},
}
WIND = {"clear": (0.4, 3.2), "overcast": (1, 4.2), "fog": (0, 1.6), "rain": (2, 5.5), "snow": (1, 4), "storm": (4, 7.5)}
WEATHER_FA = {"clear": "صاف", "overcast": "ابری", "fog": "مه", "rain": "باران", "snow": "برف", "storm": "طوفان"}
TIME_FA = {"dawn": "سپیده‌دم", "morning": "صبح", "noon": "ظهر", "dusk": "غروب", "night": "شب"}


def battles(g):
    return g.setdefault("artillery", [])


def live(g):
    return [b for b in battles(g) if b["status"] == "live"]


def find(g, bid):
    return next((b for b in battles(g) if b["id"] == bid), None)


def city_for(sq, rng=random):
    """The city whose look the battlefield takes: the square itself, or one of the two cities its road joins."""
    if sq in CITIES:
        return sq
    s = SQUARES.get(sq) or {}
    r = board.ROUTES.get(s.get("route"))
    ends = [c for c in ((r or {}).get("from"), (r or {}).get("to")) if c in CITIES]
    if ends:
        return rng.choice(ends)
    # fall back to the nearest city
    lon, lat = s.get("lon", 10), s.get("lat", 50)
    return min(CITIES, key=lambda c: (CITIES[c]["lon"] - lon) ** 2 + (CITIES[c]["lat"] - lat) ** 2)


def time_of_day(city, now=None):
    """The real time of day in that city right now (local solar time from its longitude)."""
    now = time.time() if now is None else now
    h = (now / 3600.0 + CITIES[city]["lon"] / 15.0) % 24
    if 5 <= h < 7.5:
        return "dawn"
    if 7.5 <= h < 11.5:
        return "morning"
    if 11.5 <= h < 16.5:
        return "noon"
    if 16.5 <= h < 19.5:
        return "dusk"
    return "night"


def roll_weather(city, rng=random):
    wts = CLIMATE[CLIMATE_OF.get(city, "temperate")]
    keys = list(wts)
    return rng.choices(keys, weights=[wts[k] for k in keys])[0]


def new_wind(b, rng=random, prev=None):
    lo, hi = WIND[b["weather"]]
    if prev is None:
        a, m = rng.random() * 2 * math.pi, lo + rng.random() * (hi - lo)
        x, z = math.cos(a) * m, math.sin(a) * m
    else:
        x, z = prev["x"] + (rng.random() - 0.5) * 2.2, prev["z"] + (rng.random() - 0.5) * 2.2
        m = math.hypot(x, z) or 0.001
        t = min(max(m, lo), hi) / m
        x, z = x * t, z * t
    return {"x": round(x, 3), "z": round(z, 3)}


def unit_flag(g, owner):
    p = g["players"].get(str(owner))
    return TEAM_FLAG.get(team(p) if p else None, "gb")


def start_battles(g, rng=random, now=None):
    """At the 20:00 lock: every square holding two or more cannons becomes a battle. Returns the new battles."""
    now = time.time() if now is None else now
    by_sq = {}
    for u in g["units_on_map"]:
        if u["kind"] == "cannon":
            by_sq.setdefault(u["square"], []).append(u)
    fresh = []
    for sq, lst in by_sq.items():
        if len(lst) < 2:
            continue
        city = city_for(sq, rng)
        units = [{"id": u["id"], "owner": str(u["owner"]), "name": u.get("name") or "توپ", "flag": unit_flag(g, u["owner"]),
                  "disp": rng.choice(DISPLAY_FLAGS), "hp": 100, "shells": 4, "alive": True} for u in lst]
        rng.shuffle(units)
        b = {"id": next_id(g, "a"), "square": sq, "city": city, "weather": roll_weather(city, rng),
             "seed": rng.randrange(1, 2 ** 31), "units": units, "turn": units[0]["id"], "status": "live",
             "created": now, "ends": now + BATTLE_SECONDS, "deadline": now + TURN_SECONDS, "shots": [],
             "skips": 0, "winner": None, "cycle": g["cycle"]}
        b["wind"] = new_wind(b, rng)
        battles(g).append(b)
        fresh.append(b)
        log(g, f"artillery battle {b['id']} at {sq}: " + ", ".join(u["name"] for u in units))
    return fresh


def alive_units(b):
    return [u for u in b["units"] if u["alive"]]


def unit(b, uid):
    return next((u for u in b["units"] if u["id"] == uid), None)


def advance(b, rng=random, now=None):
    """Pass the turn to the next cannon still standing."""
    now = time.time() if now is None else now
    order = [u["id"] for u in b["units"]]
    i = order.index(b["turn"]) if b["turn"] in order else -1
    for k in range(1, len(order) + 1):
        u = b["units"][(i + k) % len(order)]
        if u["alive"]:
            b["turn"] = u["id"]
            break
    b["deadline"] = min(now + TURN_SECONDS, b["ends"])
    b["wind"] = new_wind(b, rng, b["wind"])


def sync_units(g, b):
    """A cannon that vanished from the map (its owner died, the GM removed it) is out of the battle."""
    on_map = {u["id"] for u in g["units_on_map"]}
    gone = []
    for u in b["units"]:
        if u["alive"] and u["id"] not in on_map:
            u["alive"] = False
            gone.append(u)
    return gone


def finish(g, b, status="won", now=None):
    b["status"] = status
    b["finished"] = time.time() if now is None else now
    left = alive_units(b)
    b["winner"] = left[0]["id"] if status == "won" and len(left) == 1 else None
    dead = {u["id"] for u in b["units"] if not u["alive"]}
    g["units_on_map"] = [u for u in g["units_on_map"] if u["id"] not in dead]
    return b


def record_shot(g, b, p, data, now=None):
    """The shooter's phone reports a shot. Returns the list of cannons it destroyed."""
    from .actions import GameError
    now = time.time() if now is None else now
    if b["status"] != "live":
        raise GameError("این نبرد تمام شده.")
    me = unit(b, str(data.get("unit")))
    if not me or me["id"] != b["turn"] or me["owner"] != str(p["id"]) or not me["alive"]:
        raise GameError("الان نوبت توپ تو نیست.")
    if now > b["deadline"]:
        raise GameError("وقت این نوبت تمام شده بود.")
    ammo = "shell" if data.get("ammo") == "shell" and me["shells"] > 0 else "shot"
    if ammo == "shell":
        me["shells"] -= 1
    before = {u["id"]: u["hp"] for u in b["units"]}
    hp = data.get("hp") or {}
    killed = []
    for u in b["units"]:
        if not u["alive"] or u["id"] not in hp:
            continue
        try:
            v = int(round(float(hp[u["id"]])))
        except (TypeError, ValueError):
            continue
        u["hp"] = max(0, min(u["hp"], v))          # a shot can only take hp away
        if u["hp"] <= 0:
            u["alive"] = False
            killed.append(u)

    def nums(lst, n, cap):
        out = []
        for row in (lst or [])[:cap]:
            try:
                out.append([round(float(x), 2) for x in row][:n])
            except (TypeError, ValueError):
                pass
        return out
    trail = nums(data.get("trail"), 3, 2000)
    if len(trail) > 400:                            # keep it light: every k-th point plus the last
        k = len(trail) // 400 + 1
        trail = trail[::k] + [trail[-1]]
    shot = {"by": me["id"], "target": str(data.get("target") or ""), "ammo": ammo, "at": now,
            "elev": float(data.get("elev") or 0), "trav": float(data.get("trav") or 0), "charge": float(data.get("charge") or 0),
            "kind": str(data.get("kind") or "")[:10], "craters": nums(data.get("craters"), 5, 30), "trail": trail,
            "before": before, "after": {u["id"]: u["hp"] for u in b["units"]}}
    b["shots"].append(shot)
    b["skips"] = 0
    if len(alive_units(b)) <= 1:
        finish(g, b, "won" if alive_units(b) else "wiped", now)
    else:
        advance(b, now=now)
    return killed


def auto_shot(g, b, rng=random, now=None):
    """A test player's cannon fires (no phone): a rough hit-or-miss with a sensible damage."""
    now = time.time() if now is None else now
    me = unit(b, b["turn"])
    foes = [u for u in alive_units(b) if u["id"] != me["id"]]
    t = rng.choice(foes)
    hp = {}
    roll = rng.random()
    if roll < 0.35:
        hp[t["id"]] = t["hp"] - 40                   # direct hit
    elif roll < 0.6:
        hp[t["id"]] = t["hp"] - rng.randint(5, 20)   # near miss
    owner = g["players"].get(me["owner"]) or {"id": me["owner"]}
    return record_shot(g, b, owner, {"unit": me["id"], "target": t["id"], "hp": hp, "kind": "auto",
                                     "ammo": "shot", "trail": [], "craters": []}, now=now)


def timeout(g, b, now=None):
    """The current cannon didn't fire within its 2 hours: the turn passes. Returns the unit that lost its turn."""
    me = unit(b, b["turn"])
    b["skips"] = b.get("skips", 0) + 1
    advance(b, now=now)
    return me


# ---------------- what a player sees ----------------

def city_fa(b):
    from .data.locations import CITY_SHORT
    from .common import num
    place = CITY_SHORT.get(b["city"], (b["city"],))[0]
    if b["square"] == b["city"]:
        return place
    s = SQUARES.get(b["square"]) or {}
    r = board.ROUTES.get(s.get("route")) or {}
    road = "–".join(CITY_SHORT.get(c, (c,))[0] for c in (r.get("from"), r.get("to")) if c)
    return f"جاده {road}، خانه {num(b['square'].lstrip('n'))} · نزدیک {place}"


def result_text(g, b):
    names = {u["id"]: u["name"] for u in b["units"]}
    if b["status"] == "won":
        lost = [f"«{u['name']}»" for u in b["units"] if not u["alive"]]
        return f"توپ «{names[b['winner']]}» پیروز شد؛ {'، '.join(lost)} منهدم شد."
    if b["status"] == "wiped":
        return "همه توپ‌ها منهدم شدند."
    if b["status"] == "draw":
        return "وقت نبرد تمام شد؛ توپ‌های باقی‌مانده سر جایشان ماندند."
    return ""


def view(g, b, p=None, now=None):
    """The battle as one player sees it: their own cannon with its real flag, every other one with a random flag,
    and never a player's name."""
    now = time.time() if now is None else now
    pid = str(p["id"]) if p else None
    mine = {u["id"] for u in b["units"] if u["owner"] == pid}
    turn_u = unit(b, b["turn"])
    out = {
        "id": b["id"], "city": b["city"], "city_fa": city_fa(b), "weather": b["weather"], "time": time_of_day(b["city"], now),
        "seed": b["seed"], "status": b["status"], "turn": b["turn"], "wind": b["wind"],
        "my_turn": bool(b["status"] == "live" and b["turn"] in mine and turn_u and turn_u["alive"]),
        "deadline_in": max(0, int(b["deadline"] - now)) if b["status"] == "live" else 0,
        "ends_in": max(0, int(b["ends"] - now)) if b["status"] == "live" else 0,
        "units": [{"id": u["id"], "name": u["name"], "mine": u["id"] in mine, "flag": u["flag"] if u["id"] in mine else u["disp"],
                   "hp": u["hp"], "shells": u["shells"] if u["id"] in mine else 0, "alive": u["alive"]} for u in b["units"]],
        "shots": [{k: s[k] for k in ("by", "target", "ammo", "kind", "craters", "trail", "elev", "trav", "before")} for s in b["shots"]],
        "result": result_text(g, b),
    }
    if b["status"] != "live":
        out["won"] = bool(b.get("winner") in mine)
        out["lost"] = bool(mine and all(not unit(b, m)["alive"] for m in mine))
    return out


def battles_of(g, p):
    pid = str(p["id"])
    return [b for b in battles(g) if any(u["owner"] == pid for u in b["units"])]
