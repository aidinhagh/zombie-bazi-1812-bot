"""Test players that play by themselves — and use everything in the game, so every feature gets exercised.

A test player the GM is playing as (🕹) is never on autopilot. Taking one over mid-phase undoes what the
autopilot did for them this phase, so the GM can roll, throw darts, act and vote by hand.
"""
import copy
import random

from . import actions, board
from .actions import GameError
from .board import CITIES, SQUARES
from .common import G, save, pl, logger
from .data.items import ITEMS
from .data.locations import LOCATIONS, POWER_PRICES, UNIT_PRICES
from .data.roles import ROLES, SPECIALS
from .engine import flags_at, loc_of
from .state import alive_players, needs_fake_char

rng = random.Random()


def played_ids(g=None):
    g = g or G()
    return {str(v) for v in g.get("as", {}).values()}


def is_auto(p, g=None):
    return bool(p and p.get("fake") and str(p["id"]) not in played_ids(g))


def autopilots(g=None):
    g = g or G()
    return [p for p in alive_players(g) if is_auto(p, g)]


# ---------------- taking a test player over ----------------

def snapshot(g, p):
    p["_auto"] = {"cycle": g["cycle"], "phase": g["phase"], "player": copy.deepcopy({k: v for k, v in p.items() if k != "_auto"}),
                  "balloons": [b["id"] for b in g["balloons"]], "units": [u.get("id") for u in g["units_on_map"]],
                  "routes": dict(g["route_state"]), "extra": len(g.get("extra_routes", []))}


def take_over(g, p):
    """Undo this phase's autopilot moves, darts, purchases, acts and vote so the GM can play them by hand.
    Returns a short note for the GM."""
    snap = p.pop("_auto", None)
    notes = []
    if g["acts"].get(str(p["id"])) and not g.get("pending"):
        g["acts"].pop(str(p["id"]), None)
        notes.append("اکت")
    if g["phase"] == "day" and g["votes"].get(str(p["id"])):
        g["votes"].pop(str(p["id"]), None)
        notes.append("رأی")
    if snap and snap["cycle"] == g["cycle"] and snap["phase"] == g["phase"] and not g["locked"]:
        old = snap["player"]
        for k in ("pos", "coins", "items", "hp", "units", "unit_origin", "charges", "boost", "bought", "darts",
                  "moved", "move_roll", "flags", "bullets", "disguise"):
            if k in old:
                p[k] = old[k]
        g["balloons"] = [b for b in g["balloons"] if b["id"] in snap["balloons"] or str(b["owner"]) != str(p["id"])]
        g["units_on_map"] = [u for u in g["units_on_map"] if u.get("id") in snap["units"] or str(u["owner"]) != str(p["id"])]
        for rid, st in list(g["route_state"].items()):
            if snap["routes"].get(rid, "ok") != st:
                g["route_state"][rid] = snap["routes"].get(rid, "ok")
        notes.append("حرکت، دارت و خریدها")
    save()
    return "، ".join(notes)


# ---------------- one phase of play ----------------

def _try(fn, *a):
    try:
        fn(*a)
        return True
    except (GameError, KeyError, ValueError, IndexError) as e:
        logger.debug("autopilot skipped %s: %s", getattr(fn, "__name__", fn), e)
        return False


def others(g, p, include_self=False):
    return [x for x in alive_players(g) if include_self or x["id"] != p["id"]]


def play_phase(g=None, r=None):
    """Everything an autopilot test player does at the start of a phase. Returns a count summary."""
    g = g or G()
    r = r or rng
    done = {"moves": 0, "acts": 0, "darts": 0, "buys": 0, "items": 0, "balloons": 0, "units": 0}
    for p in autopilots(g):
        snapshot(g, p)
        if not g["locked"] and not p["moved"]:
            p["move_roll"] = r.randint(1, 6)
            opts = actions.move_options(g, p, p["move_roll"])
            if opts:
                dest = r.choice(list(opts))
                actions.do_move(g, p, dest, opts[dest])
                done["moves"] += 1
            if needs_fake_char(p):
                # the fake character wanders like a real one would: along the roads, a die's worth of squares
                if p.get("fake_pos") is None:
                    p["fake_pos"] = r.choice(list(CITIES))
                else:
                    ghost = {**p, "pos": p["fake_pos"], "flags": {}, "last_night_pos": None}
                    fopts = actions.move_options(g, ghost, r.randint(1, 6))
                    if fopts:
                        p["fake_pos"] = r.choice(list(fopts))
        if not p["darts"]["money"]:
            actions.money_dart(g, p, r.randint(1, 6))
            done["darts"] += 1
        if not p["darts"]["item"]:
            actions.item_dart(g, p, r.randint(1, 6), r)
        # items
        if p["items"] and r.random() < 0.5:
            if _try(actions.use_item, g, p, r.choice(p["items"])):
                done["items"] += 1
        # shop: night powers, hp, and the unit sold here
        if g["phase"] == "night" and p["coins"] >= 4 and r.random() < 0.4:
            if _try(actions.buy_power, g, p, r.choice(["attack", "protect", "defuse", "spy", "stealth"])):
                done["buys"] += 1
        shop = LOCATIONS.get(p["pos"], {}).get("shop")
        if shop and p["coins"] >= UNIT_PRICES[shop] and r.random() < 0.7:
            if _try(actions.buy_unit, g, p, shop):
                done["buys"] += 1
        if not g["locked"]:
            done["units"] += use_units(g, p, r)
            done["balloons"] += launch_balloons(g, p, r)
        if g["phase"] == "night":
            done["acts"] += choose_acts(g, p, r)
            if p["role"] == "clown":
                p["disguise"] = r.choice(list(ROLES))
    save()
    return done


def use_units(g, p, r):
    n = 0
    sq = SQUARES.get(p["pos"] or "")
    u = p["units"]
    if u.get("cannon"):
        if sq and sq["kind"] == "node" and not sq["sea"] and r.random() < 0.6:
            n += _try(actions.place_unit, g, p, "cannon")
        elif r.random() < 0.4:
            roads = board.routes_touching(g, p["pos"], kind="road", include_blocked=False) if p["pos"] else []
            if roads:
                n += _try(actions.strike_route, g, p, "cannon", r.choice(roads))
    if u.get("ship"):
        if sq and sq["kind"] == "node" and sq["sea"] and r.random() < 0.6:
            n += _try(actions.place_unit, g, p, "ship")
        else:
            mined = [rid for rid in board.routes_touching(g, p["pos"], kind="sea") if board.route_status(g, rid) == "mined"] if p["pos"] else []
            if mined:
                n += _try(actions.strike_route, g, p, "ship", mined[0])
    if u.get("mine") and p["pos"] and r.random() < 0.6:
        lanes = board.routes_touching(g, p["pos"], kind="sea", include_blocked=False)
        if lanes:
            n += _try(actions.strike_route, g, p, "mine", r.choice(lanes))
    if u.get("shovel") and p["pos"]:
        broken = [rid for rid in board.routes_touching(g, p["pos"], kind="road") if board.route_status(g, rid) == "broken"]
        if broken:
            n += _try(actions.strike_route, g, p, "shovel", broken[0])
    return int(n)


def launch_balloons(g, p, r):
    n = 0
    for kind, chance in (("spy", 0.75), ("war", 0.5)):
        if p["units"].get(kind + "_balloon") and r.random() < chance:
            n += _try(actions.launch_balloon, g, p, kind, r.choice(list(CITIES)))
    return int(n)


def basic_act(g, p, r, as_role=None):
    t = r.choice(["attack", "attack", "protect", "defuse", "spy"])
    tgt = p if t == "protect" and r.random() < 0.3 else r.choice(others(g, p))
    a = {"type": t, "target": str(tgt["id"]), "extra": {}}
    if as_role:
        a["as_role"] = as_role
    return a


def special_act(g, p, r, t, as_role=None):
    """A role-special act with sensible random choices, or None if it can't be done."""
    ch = p["charges"]
    pool = others(g, p)
    if not pool:
        return None
    tgt = r.choice(pool)
    if t in ("bomb", "poison", "guess", "cult_check") and not as_role and ch.get(t, 0) < 1:
        return None
    if t == "guess":
        role = tgt["role"] if r.random() < 0.35 else r.choice(list(ROLES))
        return {"type": t, "target": str(tgt["id"]), "extra": {"role": role}}
    if t == "cult_check":
        return {"type": t, "target": None, "extra": {}}
    if t == "bomb":
        return {"type": t, "target": str(tgt["id"]), "extra": {"wire": r.randint(1, 4)}}
    if t == "bullets":
        picks = [str(x["id"]) for x in r.sample(pool, min(3, len(pool)))]
        war = r.choice(picks) if ch.get("war_bullet", 0) > 0 and r.random() < 0.6 else None
        return {"type": t, "target": None, "extra": {"targets": picks, "war": war}}
    if t == "duel":
        two = r.sample(others(g, p, include_self=True), 2) if len(others(g, p, True)) >= 2 else None
        if not two:
            return None
        return {"type": t, "target": str(two[0]["id"]), "extra": {"target2": str(two[1]["id"])}}
    if t == "convert" and p.get("no_recruit_until", 0) >= g["cycle"]:
        return None
    return {"type": t, "target": str(tgt["id"]), "extra": {}}


def choose_acts(g, p, r):
    if g["acts"].get(str(p["id"])) or g.get("pending"):
        return 0
    acts = []
    specials = SPECIALS.get(p["role"], [])
    if specials and r.random() < 0.65:
        a = special_act(g, p, r, r.choice(specials))
        if a:
            acts.append(a)
            if a["type"] == "steal":
                victim = pl(a["target"])
                vs = SPECIALS.get(victim["role"], [])
                b = special_act(g, p, r, r.choice(vs), as_role=victim["role"]) if vs and r.random() < 0.5 else None
                acts.append(b or basic_act(g, p, r, as_role=victim["role"]))
                if b:
                    b["as_role"] = victim["role"]
    if not acts:
        acts.append(basic_act(g, p, r))
    if p.get("double_act") and "double_act_50" in flags_at(loc_of(p)):
        acts.append(basic_act(g, p, r))
    for a in acts:
        a["dice"] = [r.randint(1, 6), r.randint(1, 6)]   # test players throw their own 2d6 too
    if "church" in flags_at(loc_of(p)):
        acts = [a for a in acts if a["type"] != "attack"] or [{"type": "protect", "target": str(p["id"]), "extra": {}}]
    g["acts"][str(p["id"])] = acts
    return 1


# ---------------- after the 20:00 lock ----------------

def after_lock(g=None, r=None):
    """Slots in Vienna/Berlin, the London taxi and casino bets. Returns notes for the GM."""
    g = g or G()
    r = r or rng
    notes = []
    for p in autopilots(g):
        here = loc_of(p)
        fl = flags_at(here)
        if g["phase"] == "night" and ("vienna_slots" in fl or "berlin_slots" in fl) and not actions.ruined(g, here):
            while not (p.get("slots") or {}).get("done"):
                v = r.choice([1, 22, 43, 64]) if r.random() < 0.15 else r.randint(2, 63)
                s = actions.slot_pull(g, p, v)
            if s["hit"]:
                notes.append(f"🎰 {p['name']} در {LOCATIONS[here]['fa']} سه‌تای یکسان آورد.")
                if s["kind"] == "berlin":
                    dead = [x for x in g["players"].values() if not x["alive"] and x.get("role") and not x.get("unrevivable")]
                    if dead and _try(actions.berlin_revive, g, p, r.choice(dead)):
                        notes.append(f"⚰️→🧍 {p['name']} یک نفر را در برلین زنده کرد.")
        if g["phase"] == "night" and "double_act_50" in fl and p["flags"].get("wagram_roll") is None:
            if actions.wagram_roll(g, p, r.randint(1, 6)):
                notes.append(f"🙏 {p['name']} در خانقاه زوج آورد: امشب دو اکت.")
                g["acts"].get(str(p["id"]), []).append(dict(basic_act(g, p, r), dice=[r.randint(1, 6), r.randint(1, 6)]))
        if g["phase"] == "night" and here == "london" and r.random() < 0.4:
            reach = actions.taxi_targets(g)
            dest = r.choice(reach) if reach else None
            if dest and _try(actions.taxi, g, p, dest):
                notes.append(f"🚕 {p['name']} مخفیانه با تاکسی رفت به {LOCATIONS[dest]['fa']}.")
    casino = [p for p in autopilots(g) if p["pos"] == "stockholm" and p["coins"] > 0] if not actions.ruined(g, "stockholm") else []
    r.shuffle(casino)
    while len(casino) >= 2:
        a, b = casino.pop(), casino.pop()
        stake = min(5, a["coins"], b["coins"])
        win, lose = (a, b) if r.random() < 0.5 else (b, a)
        lose["coins"] -= stake
        win["coins"] += int(stake * actions.intact(g, "stockholm"))
        notes.append(f"🎲 کازینو: {win['name']} از {lose['name']} {stake} سکه برد.")
    save()
    return notes


# ---------------- decisions that come up during play ----------------

async def decide_pending(bot, r=None):
    """Make every decision that is waiting for an autopilot test player. Repeats until nothing is left
    (a duel round can ask for the next round)."""
    from . import events
    r = r or rng
    g = G()
    for _ in range(12):
        acted = False
        autos = {str(p["id"]): p for p in g["players"].values() if is_auto(p, g)}
        try:
            for bo in list(g["bombs"]):
                # wires are cut in the daytime, so the GM sees the bomb arrive first
                if bo["status"] == "armed" and str(bo["target"]) in autos and g["phase"] == "day":
                    await events.cut_wire(bot, bo["target"], bo["id"], r.randint(1, 4))
                    acted = True
            if g["phase"] == "day":
                for po in list(g["poisons"]):
                    if po["status"] == "pending" and str(po["by"]) in autos:
                        await events.antidote(bot, po["by"], po["id"], r.random() < 0.4)
                        acted = True
            for d in list(g["duels"]):
                if d["status"] == "live":
                    for side in (d["a"], d["b"]):
                        if side in autos and side not in d["picks"] and d["status"] == "live":
                            await events.rps_pick(bot, side, "d", d["id"], r.choice("rps"))
                            acted = True
            for b in list(g["bets"]):
                if b["status"] == "offered" and b["b"] in autos:
                    await events.accept_bet(bot, b["b"], b["id"], r.random() < 0.7)
                    acted = True
                elif b["status"] == "live":
                    for side in (b["a"], b["b"]):
                        if side in autos and side not in b["picks"] and b["status"] == "live":
                            await events.rps_pick(bot, side, "b", b["id"], r.choice("rps"))
                            acted = True
            for pid, p in autos.items():
                if p["flags"].get("yakuza_pending"):
                    choices = [x for x in alive_players(g)]
                    if choices:
                        await events.yakuza_take(bot, pid, r.choice(choices)["id"])
                    else:
                        p["flags"].pop("yakuza_pending", None)
                    acted = True
            for b in list(g["balloons"]):
                if str(b["owner"]) in autos and b.get("delivered") and b["publish"] is None:
                    await events.balloon_publish_choice(bot, b["owner"], b["id"], r.random() < 0.5)
                    acted = True
            jd = g.get("judgement")
            if jd and jd["status"] == "waiting" and jd["judge"] in autos:
                if len(jd["cands"]) == 1:
                    J = pl(jd["judge"])
                    what = "null" if events.nullify_left(J) and r.random() < 0.3 else "ok"
                else:
                    what = r.choice(["all", "none", "sel"])
                    jd["sel"] = r.sample(jd["cands"], r.randint(1, len(jd["cands"])))
                await events.judge_press(bot, jd["judge"], what)
                acted = True
        except GameError as e:
            logger.debug("autopilot decision skipped: %s", e)
        if not acted:
            break


async def day_shots(bot, r=None):
    """Test players holding bullets fire some of them during the day."""
    from . import events
    r = r or rng
    g = G()
    for p in autopilots(g):
        while p["bullets"] and r.random() < 0.6:
            targets = others(g, p)
            if not targets:
                break
            try:
                await events.fire_bullet(bot, p, r.choice(targets))
            except GameError:
                break
