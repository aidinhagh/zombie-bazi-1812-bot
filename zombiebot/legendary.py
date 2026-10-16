"""Legendary items: spawn, pick-up at the 20:00 lock, and the sealed-bid auction when several people are there."""
import random

from . import board
from .board import CITIES
from .data.legendary import LEGENDARY
from .state import alive_players, log

BID_STEPS = (0, 1, 2, 3, 5, 8, 10, 15, 20, 30, 50)


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


def spawn_text(a):
    it = LEGENDARY[a["key"]]
    return (f"🌟 آیتم لجندری «{it['fa']}» در {board.square_name(a['where'])} ظاهر شد!\n{it['desc_fa']}\n"
            "هر کس ساعت ۸ آنجا باشد آن را برمی‌دارد؛ اگر چند نفر باشند، بینشان مزایده می‌شود.")


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
    L["auction"] = {"key": a["key"], "where": a["where"], "bidders": [str(p["id"]) for p in here], "bids": {}}
    L["active"] = None
    return "auction", here


def bid_options(p):
    return [b for b in BID_STEPS if b <= p["coins"]] + ([p["coins"]] if p["coins"] not in BID_STEPS else [])


def place_bid(g, p, amount):
    from .actions import GameError
    au = state(g)["auction"]
    if not au or str(p["id"]) not in au["bidders"]:
        raise GameError("مزایده‌ای برای تو باز نیست.")
    if str(p["id"]) in au["bids"]:
        raise GameError("پیشنهادت رو قبلاً دادی.")
    if amount < 0 or amount > p["coins"]:
        raise GameError("این‌قدر سکه نداری.")
    au["bids"][str(p["id"])] = amount
    return all(b in au["bids"] or not g["players"][b]["alive"] for b in au["bidders"])


def close_auction(g, rng=random):
    """Highest bid wins and pays; a tie is settled by lot. Missing bids count as 0. Returns (winner, bid, tied)."""
    L = state(g)
    au = L["auction"]
    if not au:
        return None, 0, []
    alive = [b for b in au["bidders"] if g["players"][b]["alive"]]
    if not alive:
        L["auction"] = None
        L["active"] = {"key": au["key"], "where": au["where"], "cycle": g["cycle"]}   # nobody left: it stays there
        return None, 0, []
    best = max(au["bids"].get(b, 0) for b in alive)
    tied = [b for b in alive if au["bids"].get(b, 0) == best]
    win = g["players"][rng.choice(tied)]
    win["coins"] -= min(best, win["coins"])
    give(g, win, au["key"])
    L["auction"] = None
    return win, best, tied if len(tied) > 1 else []
