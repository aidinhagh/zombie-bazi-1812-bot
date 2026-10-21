"""Legendary items: spawn, pick-up at the 20:00 lock, and the sealed-bid auction when several people are there."""
import random

from . import board
from .board import CITIES
from .data.legendary import LEGENDARY
from .state import alive_players, log



def state(g):
    return g.setdefault("legend", {"spawned": [], "active": None, "auction": None})


def spawn_next(g, where=None, rng=random):
    """Put the next legendary item on the map (one at a time). Returns the active dict or None."""
    L = state(g)
    if L["active"] or L["auction"]:
        return None
    left = [k for k in LEGENDARY if k not in L["spawned"]]
    if not left:
        return None
    from .actions import ruined
    cities = [c for c in CITIES if not ruined(g, c)] or list(CITIES)
    key = left[0]
    L["spawned"].append(key)
    L["active"] = {"key": key, "where": where or rng.choice(cities), "cycle": g["cycle"]}
    log(g, f"legendary {key} spawned at {L['active']['where']}")
    return L["active"]


def move_active(g, where=None, rng=random):
    """GM: move the legendary item that is on the map to another city (random if none given)."""
    L = state(g)
    a = L["active"]
    if not a:
        return None
    if where is not None and where not in CITIES:
        from .actions import GameError
        raise GameError("آیتم لجندری فقط در شهر قرار می‌گیرد.")
    if not where:
        from .actions import ruined
        cities = [c for c in CITIES if c != a["where"] and not ruined(g, c)] or [c for c in CITIES if c != a["where"]]
        where = rng.choice(cities)
    a["where"] = where
    log(g, f"legendary {a['key']} moved to {where}")
    return a


def spawn_text(a):
    it = LEGENDARY[a["key"]]
    return (f"🌟 (فقط برای گاد) آیتم لجندری «{it['fa']}» مخفیانه در {board.square_name(a['where'])} ظاهر شد.\n{it['desc_fa']}\n"
            "هر کس ساعت ۸ آنجا باشد آن را برمی‌دارد؛ اگر چند نفر باشند، مزایده مخفی. به کسی اعلام نمی‌شود.")


def give(g, p, key):
    it = LEGENDARY[key]
    p.setdefault("legend", []).append(key)
    p["hp"] += it.get("hp", 0)
    log(g, f"{p['name']} got legendary {key}")


def at_lock(g, rng=random):
    """Called when the map locks. Returns ("none"|"taken"|"auction", info)."""
    L = state(g)
    a = L["active"]
    if not a or L["auction"]:
        return "none", None
    here = [p for p in alive_players(g) if p.get("pos") == a["where"]]
    if not here:
        return "none", None
    if len(here) == 1:
        give(g, here[0], a["key"])
        L["active"] = None
        return "taken", here[0]
    L["auction"] = {"key": a["key"], "where": a["where"], "bidders": [str(p["id"]) for p in here],
                    "high": 0, "leader": None, "out": []}
    L["active"] = None
    return "auction", here


def active_bidders(g, au):
    return [b for b in au["bidders"] if b not in au["out"] and g["players"][b]["alive"]]


def bid_options(p, au):
    """Raises above the current highest bid that this player can afford."""
    hi = au["high"]
    opts = sorted({hi + d for d in (1, 2, 5, 10, 20)} | {p["coins"]})
    return [x for x in opts if hi < x <= p["coins"]]


def _finished(g, au):
    act = active_bidders(g, au)
    return (au["leader"] and act == [au["leader"]]) or not act


def place_bid(g, p, amount):
    """Open, anonymous auction: everyone sees only the current highest bid. Returns True when it's over."""
    from .actions import GameError
    au = state(g)["auction"]
    pid = str(p["id"])
    if not au or pid not in au["bidders"] or pid in au["out"]:
        raise GameError("مزایده‌ای برای تو باز نیست.")
    if pid == au["leader"]:
        raise GameError("الان بالاترین پیشنهاد مال خودته.")
    if amount <= au["high"]:
        raise GameError(f"باید بیشتر از {au['high']} سکه پیشنهاد بدی.")
    if amount > p["coins"]:
        raise GameError("این‌قدر سکه نداری.")
    au["high"], au["leader"] = amount, pid
    return _finished(g, au)


def pass_bid(g, p):
    from .actions import GameError
    au = state(g)["auction"]
    pid = str(p["id"])
    if not au or pid not in au["bidders"] or pid in au["out"]:
        raise GameError("مزایده‌ای برای تو باز نیست.")
    if pid == au["leader"]:
        raise GameError("بالاترین پیشنهاد مال توست؛ نمی‌تونی کنار بکشی.")
    au["out"].append(pid)
    return _finished(g, au)


def close_auction(g, rng=random):
    """The highest bidder wins and pays. If nobody bid, the item stays where it is. Returns (winner, bid)."""
    L = state(g)
    au = L["auction"]
    if not au:
        return None, 0
    L["auction"] = None
    win = g["players"].get(au["leader"]) if au["leader"] else None
    if not win or not win["alive"]:
        L["active"] = {"key": au["key"], "where": au["where"], "cycle": g["cycle"]}
        return None, 0
    win["coins"] -= min(au["high"], win["coins"])
    give(g, win, au["key"])
    return win, au["high"]
