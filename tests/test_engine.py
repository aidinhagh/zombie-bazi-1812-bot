import random

import pytest

from zombiebot import actions, board
from zombiebot.engine import resolve_night, night_stats
from zombiebot.state import new_game, new_player, assign_role


class FixedRng(random.Random):
    """randint always returns 3 (2d6 = 6); random() 0.0."""
    def randint(self, a, b):
        return 3

    def random(self):
        return 0.0


def make(roles):
    g = new_game()
    g["phase"] = "night"
    g["cycle"] = 1
    for i, (role, pos) in enumerate(roles, start=1):
        p = new_player(i, f"P{i}")
        assign_role(p, role)
        p["pos"] = p["night_pos"] = pos
        g["players"][str(i)] = p
    return g


def act(g, pid, typ, target=None, **extra):
    g["acts"].setdefault(str(pid), []).append({"type": typ, "target": target, "extra": extra})


def effects(res, t):
    return [e for e in res["effects"] if e["t"] == t]


def test_attack_damage_and_kill():
    g = make([("zombie", "n15"), ("doctor", "n17")])
    act(g, 1, "attack", 2)       # 14 + 6 = 20 vs hp 38
    res = resolve_night(g, FixedRng())
    d = effects(res, "damage")
    assert d and d[0]["amount"] == 20
    g["players"]["2"]["hp"] = 15
    res = resolve_night(g, FixedRng())
    assert effects(res, "death")[0]["pid"] == "2"


def test_protect_absorbs():
    g = make([("zombie", "n15"), ("doctor", "n17"), ("spy", "n19")])
    act(g, 1, "attack", 3)      # 20
    act(g, 2, "protect", 3)     # 15 + 6 = 21
    res = resolve_night(g, FixedRng())
    assert not effects(res, "damage") and not effects(res, "death")


def test_lone_zombie_vs_hero_dies():
    g = make([("zombie", "n15"), ("hero", "n17")])
    act(g, 1, "attack", 2)
    res = resolve_night(g, FixedRng())
    deaths = effects(res, "death")
    assert [e["pid"] for e in deaths] == ["1"]


def test_two_zombies_hurt_hero():
    g = make([("zombie", "n15"), ("yakuza", "n17"), ("hero", "n19")])
    act(g, 1, "attack", 3)
    act(g, 2, "attack", 3)   # 20 + 19 = 39 >= 39
    res = resolve_night(g, FixedRng())
    assert [e["pid"] for e in effects(res, "death")] == ["3"]


def test_priest_halves_lone_zombie():
    g = make([("zombie", "n15"), ("priest", "n17")])
    act(g, 1, "attack", 2)
    res = resolve_night(g, FixedRng())
    assert effects(res, "damage")[0]["amount"] == 10


def test_sniper_shooting_human_dies():
    g = make([("sniper", "n15"), ("doctor", "n17")])
    act(g, 1, "attack", 2)
    res = resolve_night(g, FixedRng())
    assert [e["pid"] for e in effects(res, "death")] == ["1"]
    assert not effects(res, "damage")


def test_defuse_cancels_and_weakens():
    g = make([("zombie", "n15"), ("saboteur", "n17"), ("doctor", "n19")])
    act(g, 1, "attack", 3)   # 20
    act(g, 2, "defuse", 1)   # 21 -> cancels
    res = resolve_night(g, FixedRng())
    assert not effects(res, "damage")
    g["acts"] = {}
    act(g, 1, "attack", 3)
    act(g, 3, "defuse", 1)   # doctor defuse 1+6 = 7 -> attack 13
    res = resolve_night(g, FixedRng())
    assert effects(res, "damage")[0]["amount"] == 13


def test_church_blocks_attack_and_damage():
    g = make([("zombie", "warsaw"), ("doctor", "n17"), ("zombie", "n19"), ("spy", "warsaw")])
    act(g, 1, "attack", 2)
    act(g, 3, "attack", 4)
    res = resolve_night(g, FixedRng())
    assert not effects(res, "damage") and not effects(res, "death")


def test_location_mods():
    g = make([("zombie", "birmingham"), ("doctor", "warsaw")])
    s, hp = night_stats(g, g["players"]["1"])
    assert s["attack"] == 22 and s["protect"] == -2 and hp == -4
    s, hp = night_stats(g, g["players"]["2"])
    assert s["protect"] == 9
    g["loc_damage"]["birmingham"] = 50
    s, _ = night_stats(g, g["players"]["1"])
    assert s["attack"] == 18


def test_hotel_halves():
    g = make([("hero", "barcelona")])
    s, _ = night_stats(g, g["players"]["1"])
    assert s["attack"] == 7 and s["stealth"] == 14


def test_thief_steals_and_spy_kills_thief():
    g = make([("thief", "n15"), ("zombie", "n17"), ("doctor", "n19"), ("spy", "n21")])
    g["players"]["2"]["items"] = ["flint"]
    act(g, 1, "steal", 2)
    act(g, 2, "attack", 3)
    res = resolve_night(g, FixedRng())
    assert not effects(res, "damage")
    assert effects(res, "lose_item")[0]["item"] == "flint"
    g["acts"] = {}
    act(g, 1, "steal", 4)
    res = resolve_night(g, FixedRng())
    assert effects(res, "death")[0]["pid"] == "1"


def test_spy_colors_and_roles():
    g = make([("spy", "n15"), ("zombie", "n17"), ("doctor", "n19"), ("godfather", "n21"), ("clown", "n23")])
    g["players"]["5"]["disguise"] = "zombie"
    for i in ("1", "3"):
        g["players"][i]["boost"] = {"spy": 30}     # spying must beat plain stealth
    act(g, 1, "spy", 2)
    act(g, 3, "spy", 4)
    act(g, 3, "spy", 5)
    res = resolve_night(g, FixedRng())
    priv = [e["en"] for e in effects(res, "private")]
    assert any("Zombie" in t for t in priv)
    assert any("P4: white" in t for t in priv)
    assert any("P5: black" in t for t in priv)


def test_godfather_guess():
    g = make([("godfather", "n15"), ("doctor", "n17")])
    act(g, 1, "guess", 2, role="doctor")
    res = resolve_night(g, FixedRng())
    d = effects(res, "death")[0]
    assert d["pid"] == "2" and d["unrevivable"]


def test_cult_convert_rules():
    g = make([("cultist", "n15"), ("doctor", "n17"), ("hero", "n19"), ("spy", "n21")])
    act(g, 1, "convert", 2)   # 32+6 vs 31+6
    res = resolve_night(g, FixedRng())
    assert effects(res, "convert")
    g["acts"] = {}
    act(g, 1, "convert", 3)
    assert not effects(resolve_night(g, FixedRng()), "convert")
    g["acts"] = {}
    act(g, 1, "convert", 4)
    assert effects(resolve_night(g, FixedRng()), "death")[0]["pid"] == "1"


def test_independent_safe_in_wagram():
    g = make([("zombie", "n15"), ("yakuza", "n17"), ("clown", "wagram")])
    g["players"]["3"]["hp"] = 5
    act(g, 1, "attack", 3)
    res = resolve_night(g, FixedRng())
    assert not effects(res, "death") and not effects(res, "damage")   # undamaged monastery: attacks don't reach them


def test_musketeer_defused_gives_practice():
    g = make([("musketeer", "n15"), ("doctor", "n17"), ("undead", "n19")])
    g["players"]["1"]["boost"] = {"stealth": -20}   # special acts use 2d6 + stealth
    act(g, 1, "bullets", None, targets=["2"], war="2")
    act(g, 3, "defuse", 1)
    res = resolve_night(g, FixedRng())
    assert [e["kind"] for e in effects(res, "bullet")] == ["practice"]


def test_apply_and_movement():
    g = make([("zombie", "london"), ("doctor", "paris")])
    res = resolve_night(g, FixedRng())
    actions.apply_effects(g, res)
    actions.start_phase(g, "day")
    p = g["players"]["1"]
    opts = actions.move_options(g, p, 2)
    assert "birmingham" in opts and "n15" in opts and "amsterdam" in opts
    # break the London–Birmingham road with a cannon
    g["route_state"]["p13"] = "broken"
    assert "birmingham" not in actions.move_options(g, p, 2)


def test_toll():
    g = make([("zombie", "london"), ("doctor", "n15")])
    owner = g["players"]["2"]
    owner["units"]["cannon"] = 1
    actions.place_unit(g, owner, "cannon")
    mover = g["players"]["1"]
    mover["coins"] = 4
    opts = actions.move_options(g, mover, 2)
    actions.do_move(g, mover, "birmingham", opts["birmingham"])
    assert mover["coins"] == 0 and owner["coins"] == 14 and mover["hp"] == 38 - 2


def test_darts():
    g = make([("doctor", "constantinople")])
    p = g["players"]["1"]
    assert actions.money_dart(g, p, 6) == 7
    assert actions.item_dart(g, p, 3) is not None   # item 3 +1 = 4 -> wins on 3+
    p["pos"] = "n15"
    assert actions.item_dart(g, p, 3) is None       # power 3 -> needs 4+
    assert actions.item_dart(g, p, 1) is None


def test_vote_weights():
    g = make([("doctor", "paris"), ("spy", "stpetersburg"), ("hero", "barcelona")])
    actions.lock_map(g)
    actions.start_phase(g, "day")
    g["votes"] = {"1": "3", "2": "3"}
    ranked, _ = actions.tally(g)
    assert ranked[0] == ("3", 2)   # hotel only protects against execution, not votes
    g["players"]["3"]["flags"].pop("hotel_immune")
    ranked, _ = actions.tally(g)
    assert ranked[0] == ("3", 2)   # paris 2 + petersburg 0


def test_spy_fails_against_higher_stealth():
    g = make([("spy", "n15"), ("zombie", "n17")])
    act(g, 1, "spy", 2)               # 15 + 6 = 21 vs stealth 30
    res = resolve_night(g, FixedRng())
    assert any("شکست" in e["fa"] for e in effects(res, "private"))


def test_musketeer_cannot_war_bullet_himself():
    g = make([("musketeer", "n15"), ("doctor", "n17")])
    g["players"]["1"]["boost"] = {"stealth": -20}
    act(g, 1, "bullets", None, targets=["1", "2"], war="1")
    res = resolve_night(g, FixedRng())
    assert [e["kind"] for e in effects(res, "bullet") if e["pid"] == "1"] == ["practice"]


def test_bad_dug_road_is_removed_and_cannon_breaks_once():
    g = make([("doctor", "copenhagen"), ("zombie", "n15")])
    g["extra_routes"].append({"id": "x1", "from": "n37", "to": "copenhagen", "kind": "road", "nodes": [], "km": 0, "owner": 1})
    dropped = actions.drop_bad_dug_roads(g)
    assert dropped and g["extra_routes"] == [] and dropped[0][1][0]["id"] == 1
    with pytest.raises(actions.GameError):
        actions.dig_route(g, "n37", "copenhagen")
    Z = g["players"]["2"]
    Z["units"]["cannon"] = 1
    rid = board.routes_touching(g, "n15", kind="road")[0]
    g["phase"] = "day"
    actions.strike_route(g, Z, "cannon", rid)
    actions.start_phase(g, "night")
    g["route_state"][rid] = "ok"
    with pytest.raises(actions.GameError):
        actions.strike_route(g, Z, "cannon", rid)
