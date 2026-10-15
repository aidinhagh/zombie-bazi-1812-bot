"""Drive the real Telegram handlers through whole games, offline."""
import random

from tests.harness import World, run, GM
from zombiebot import actions

GROUP = -500


async def setup_game(w, roles):
    """Register players 1..n via /start, set the group, assign roles."""
    await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
    assert w.g["group_id"] == GROUP
    for i, role in enumerate(roles, start=1):
        await w.cmd(i, "start")
        await w.cmd(GM, "assign", str(i), role)
    assert all(p["role"] for p in w.g["players"].values())


def P(w, i):
    return w.g["players"][str(i)]


async def place(w, i, city):
    """First move: free choice of city through the menu."""
    await w.press(i, "mv")
    await w.press(i, f"mt:{city}")
    assert P(w, i)["pos"] == city, (i, city, P(w, i)["pos"])


def test_full_cycle_through_menus():
    async def go():
        w = World(seed=3)
        await setup_game(w, ["zombie", "yakuza", "doctor", "spy", "hero", "clown"])
        # role cards went out with menus
        assert w.last_to(1) and "mv" in w.last_to(1).buttons()
        await w.press(GM, "gnight")
        assert any("شب 1" in m.text for m in w.sent if m.chat_id == GROUP)
        for i, c in zip(range(1, 7), ["paris", "berlin", "amsterdam", "milan", "warsaw", "wagram"]):
            await place(w, i, c)
        # darts
        await w.press(3, "dt")
        await w.press(3, "dm")
        await w.press(3, "di")
        assert P(w, 3)["darts"] == {"money": True, "item": True}
        # second throw refused
        ans = await w.press(3, "dm")
        assert ans and ans[-1]
        # buy power at night
        coins = P(w, 3)["coins"]
        await w.press(3, "bp:protect")
        assert P(w, 3)["coins"] == coins - 2 and P(w, 3)["boost"]["protect"] == 1
        # acts via menus
        await w.press(1, "ac")
        await w.press(1, "a:attack")
        await w.press(1, "t:attack:3")
        await w.press(2, "a:attack")
        await w.press(2, "t:attack:3")
        await w.press(3, "a:protect")
        await w.press(3, "t:protect:3")
        await w.press(4, "a:spy")
        await w.press(4, "t:spy:1")
        await w.press(6, "cd")
        await w.press(6, "cdr:hero")
        assert len(w.g["acts"]) == 4
        # act limit
        ans = await w.press(1, "t:attack:4")
        assert len(w.g["acts"]["1"]) == 1
        # lock: map posted to group
        await w.press(GM, "glock")
        assert w.g["locked"]
        assert any(m.photo for m in w.sent if m.chat_id == GROUP)
        ans = await w.press(1, "mv")
        assert ans[-1]  # locked
        # resolve + apply
        await w.press(GM, "gres")
        assert w.g["pending"] and w.g["pending"]["effects"]
        report = w.last_to(GM)
        assert "gap" in report.buttons()
        first = w.g["pending"]["effects"][0]["id"]
        await w.press(GM, f"ge:{first}", message=report)
        assert not w.g["pending"]["effects"][0]["on"]
        await w.press(GM, f"ge:{first}", message=report)
        await w.press(GM, "gap")
        assert w.g["pending"] is None and w.g["acts"] == {}
        assert any("Your spy result" in t or "نتیجه جاسوسی" in t for t in w.texts_to(4))
        # day: votes and execution
        await w.press(GM, "gday")
        for voter in (1, 2, 3, 4):
            await w.press(voter, "vt")
            await w.press(voter, "v:6")
        await w.press(5, "v:0")
        ranked, _ = actions.tally(w.g)
        assert ranked[0][0] == "6"
        await w.press(GM, "gtal")
        await w.press(GM, "gx:6")
        assert not P(w, 6)["alive"]
        assert any("دلقک" in m.text and "برد" in m.text for m in w.sent if m.chat_id == GROUP)
        await w.cmd(GM, "map")
        await w.cmd(GM, "players")
        await w.cmd(GM, "log")
    run(go())


def test_specials_bomb_poison_duel_bullets_yakuza():
    async def go():
        w = World(seed=5)
        await setup_game(w, ["bomber", "apothecary", "judge", "musketeer", "yakuza", "doctor", "spy", "cultist"])
        await w.press(GM, "gnight")
        for i, c in zip(range(1, 9), ["paris", "berlin", "milan", "vienna", "warsaw", "moscow", "london", "stockholm"]):
            await place(w, i, c)
        await w.press(1, "a:bomb"); await w.press(1, "t:bomb:6"); await w.press(1, "tb:6:3")
        await w.press(2, "a:poison"); await w.press(2, "t:poison:7")
        await w.press(3, "a:duel"); await w.press(3, "t:duel:5"); await w.press(3, "td:5:6")
        await w.press(4, "a:bullets"); await w.press(4, "bl:6"); await w.press(4, "bl:7"); await w.press(4, "bn"); await w.press(4, "bx:6")
        await w.press(8, "a:convert"); await w.press(8, "t:convert:6")
        assert set(w.g["acts"]) == {"1", "2", "3", "4", "8"}
        await w.press(GM, "gres")
        await w.press(GM, "gap")
        # bomb posted in the group with wire buttons; only the target may cut
        bomb_msg = next(m for m in reversed(w.sent) if m.chat_id == GROUP and any(b.startswith("bw:") for b in m.buttons()))
        bid = w.g["bombs"][0]["id"]
        await w.press(7, f"bw:{bid}:1", message=bomb_msg)
        assert w.g["bombs"][0]["status"] == "armed"
        await w.press(6, f"bw:{bid}:1", message=bomb_msg)   # wrong wire (correct is 3)
        assert w.g["bombs"][0]["status"] == "exploded" and not P(w, 6)["alive"]
        assert P(w, 1)["charges"]["bomb"] == 1           # explosion doesn't use the bomb up
        # poison announced; apothecary declines antidote
        assert w.g["poisons"] and w.g["poisons"][0]["status"] == "pending"
        await w.press(2, f"an:{w.g['poisons'][0]['id']}:0")
        # duel between 5 and 6 — 6 is dead now, but the duel was already created
        await w.press(GM, "gday")
        # bullets: 6 is dead; 7 got a practice bullet
        assert P(w, 7)["bullets"] == ["practice"]
        await w.cmd(7, "shoot")
        await w.press(7, "sht:3")
        assert P(w, 3)["alive"]
        # yakuza executed → takes someone, not the cultist
        await w.press(GM, "gx:5")
        assert P(w, 5)["flags"].get("yakuza_pending")
        await w.press(5, "yk:8")    # cultist: refused
        assert P(w, 8)["alive"]
        P(w, 5)["flags"]["yakuza_pending"] = True
        await w.press(5, "yk:4")
        assert not P(w, 4)["alive"]
        # next night: poison kills
        await w.press(GM, "gnight")
        assert not P(w, 7)["alive"] and w.g["poisons"][0]["status"] == "killed"
    run(go())


def test_duel_rounds():
    async def go():
        w = World(seed=7)
        await setup_game(w, ["judge", "doctor", "spy"])
        await w.press(GM, "gnight")
        for i, c in zip(range(1, 4), ["paris", "berlin", "milan"]):
            await place(w, i, c)
        await w.press(1, "a:duel"); await w.press(1, "t:duel:2"); await w.press(1, "td:2:3")
        await w.press(GM, "gres"); await w.press(GM, "gap")
        du = w.g["duels"][0]
        assert du["status"] == "live"
        hp2, hp3 = P(w, 2)["hp"], P(w, 3)["hp"]
        await w.press(2, f"rp:d:{du['id']}:r"); await w.press(3, f"rp:d:{du['id']}:r")    # draw
        assert len(du.get("rounds", [])) == 0
        for _ in range(3):
            await w.press(2, f"rp:d:{du['id']}:p"); await w.press(3, f"rp:d:{du['id']}:r")
        assert du["status"] == "done" and P(w, 3)["hp"] == hp3 - 30 and P(w, 2)["hp"] == hp2
        # outsider can't press
        await w.press(1, f"rp:d:{du['id']}:r")
    run(go())


def test_locations_units_balloons_taxi_slots_bet():
    async def go():
        w = World(seed=11)
        await setup_game(w, ["hero", "spy", "zombie_doctor", "doctor", "zombie", "thief"])
        await w.press(GM, "gnight")
        for i, c in zip(range(1, 7), ["london", "berlin", "vienna", "stockholm", "stockholm", "constantinople"]):
            await place(w, i, c)
        # shop units only in their city
        P(w, 1)["coins"] = 50
        await w.press(1, "bu:ship")
        assert P(w, 1)["units"]["ship"] == 1
        ans = await w.press(1, "bu:cannon")
        assert ans[-1] and "cannon" not in P(w, 1)["units"]
        # spy balloon (spy's starting one is always published)
        await w.press(2, "un"); await w.press(2, "ub:spy"); await w.press(2, "ubt:spy:stockholm")
        # zombie doctor's starting balloon is private
        await w.press(3, "ub:spy"); await w.press(3, "ubt:spy:london")
        # hero's war balloon
        await w.press(1, "ub:war"); await w.press(1, "ubt:war:constantinople")
        # casino bet
        await w.cmd(4, "bet")
        await w.press(4, "bet:5:5")
        b = w.g["bets"][0]
        await w.press(5, f"ba:{b['id']}:1")
        c4, c5 = P(w, 4)["coins"], P(w, 5)["coins"]
        await w.press(4, f"rp:b:{b['id']}:s"); await w.press(5, f"rp:b:{b['id']}:p")
        assert P(w, 4)["coins"] == c4 + 5 and P(w, 5)["coins"] == c5 - 5
        # lock
        await w.press(GM, "glock")
        spyb = [x for x in w.g["balloons"] if x["kind"] == "spy"]
        assert spyb[0]["result"] == [P(w, 4)["name"], P(w, 5)["name"]] or set(spyb[0]["result"]) == {P(w, 4)["name"], P(w, 5)["name"]}
        assert spyb[0].get("published") and not spyb[1].get("published")
        assert any("spy balloon" in t.lower() or "بالن جاسوسی" in t for t in w.texts_to(GROUP))
        # war balloon → GM picks %
        await w.press(GM, "gbal")
        wb = next(x for x in w.g["balloons"] if x["kind"] == "war")
        hp6 = P(w, 6)["hp"]
        await w.press(GM, f"gw:{wb['id']}:50")
        assert w.g["loc_damage"]["constantinople"] == 50 and P(w, 6)["hp"] == hp6 - 5
        # taxi out of London after lock
        await w.cmd(1, "taxi")
        await w.press(1, "tx:warsaw")
        assert P(w, 1)["night_pos"] == "warsaw" and P(w, 1)["public_pos"] == "london"
        # Vienna slots: force a jackpot (64)
        w.forced_dice = [10, 64]
        await w.cmd(3, "slots")
        await w.cmd(3, "slots")
        assert P(w, 3)["slots"]["hit"]
        from zombiebot.engine import night_stats
        s, hp = night_stats(w.g, P(w, 3))
        assert s["attack"] == 21 and hp == 20
        await w.cmd(3, "slots")   # used up → refused, no crash
    run(go())


def test_berlin_revive_and_cannon_toll():
    async def go():
        w = World(seed=13)
        await setup_game(w, ["doctor", "spy", "zombie", "hero"])
        await w.press(GM, "gnight")
        for i, c in zip(range(1, 5), ["berlin", "constantinople", "paris", "amsterdam"]):
            await place(w, i, c)
        await w.cmd(GM, "kill", "4")
        await w.press(GM, "glock")
        w.forced_dice = [22]
        await w.cmd(1, "slots")
        m = w.last_to(1)
        assert "rv:4" in m.buttons()
        await w.press(1, "rv:4")
        assert P(w, 4)["alive"] and w.g["revived_by_team"]["human"]
        # cannon bought and placed on a road square, then someone pays the toll
        await w.press(GM, "gres"); await w.press(GM, "gap"); await w.press(GM, "gday")
        P(w, 2)["coins"] = 20
        await w.press(2, "bu:cannon")
        await w.cmd(GM, "pos", "2", "n25")
        await w.press(2, "up:cannon")
        assert w.g["units_on_map"][0]["square"] == "n25"
        P(w, 3)["pos"] = "wagram"
        w.forced_dice = [2]
        await w.press(3, "mv")
        m = w.last_to(3)
        assert "mt:n25" in m.buttons()
        coins3 = P(w, 3)["coins"]
        await w.press(3, "mt:n25")
        assert P(w, 3)["coins"] == coins3 - 10 and P(w, 2)["coins"] == 20 - 6 + 10
    run(go())


def test_fake_players_impersonation_and_autoplay():
    async def go():
        w = World(seed=17)
        await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
        await w.cmd(GM, "fake", "24")
        fakes = [p for p in w.g["players"].values() if p.get("fake")]
        assert len(fakes) == 24
        await w.press(GM, "gnight")
        await w.cmd(GM, "as", "Test01")
        await w.cmd(GM, "menu")
        await w.press(GM, "mv")
        assert any(m.chat_id == GM and m.text.startswith("[→ Test01]") or ("Test01" in m.text) for m in w.sent)
        await w.cmd(GM, "as", "off")
        await w.cmd(GM, "autoplay")
        assert len(w.g["acts"]) >= 20
        await w.press(GM, "glock")
        await w.press(GM, "gres")
        await w.press(GM, "gap")
        await w.press(GM, "gday")
        await w.cmd(GM, "autoplay")
        await w.press(GM, "gtal")
        await w.cmd(GM, "fake", "clear")
        assert not any(p.get("fake") for p in w.g["players"].values())
    run(go())


def test_fuzz_random_buttons():
    """Mash random buttons as every fake player for several full cycles. Only GameError-type refusals are allowed."""
    async def go(seed):
        w = World(seed=seed)
        rng = random.Random(seed)
        await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
        await w.cmd(GM, "fake", "24")
        for cycle in range(4):
            for phase in ("gnight", "gday"):
                await w.press(GM, phase)
                players = [p for p in w.g["players"].values() if p["alive"]]
                for p in players:
                    await w.cmd(GM, "as", str(p["id"]) if False else p["name"])
                    await w.cmd(GM, "menu")
                    for _ in range(12):
                        m = w.last_to(GM)
                        if not m or not m.buttons():
                            await w.cmd(GM, "menu")
                            m = w.last_to(GM)
                        if not m:
                            break
                        data = rng.choice(m.buttons())
                        if data.startswith("g"):
                            continue
                        await w.press(GM, data, message=m)
                    for c in ("slots", "taxi", "shoot", "bet", "status"):
                        if rng.random() < 0.2:
                            await w.cmd(GM, c)
                await w.cmd(GM, "as", "off")
                await w.cmd(GM, "autoplay")
                if rng.random() < 0.5:
                    await w.press(GM, "glock")
                await w.press(GM, "gbal")
                for m in list(w.sent[-10:]):
                    for d in m.buttons():
                        if d.startswith(("gw:", "gf:")):
                            await w.press(GM, d, message=m)
                            break
                if phase == "gnight":
                    await w.press(GM, "gres")
                    await w.press(GM, "gap")
                else:
                    ranked, _ = actions.tally(w.g)
                    if ranked:
                        await w.press(GM, f"gx:{ranked[0][0]}")
                # group buttons (bombs, rps, antidotes) pressed by whoever
                for m in list(w.sent[-40:]):
                    for d in m.buttons():
                        if d.startswith(("bw:", "rp:", "an:", "ba:", "yk:")) and rng.random() < 0.5:
                            await w.press(GM, d, message=m)
                await w.cmd(GM, "win")
                await w.cmd(GM, "map")
        await w.press(GM, "gpl")
    for seed in range(6):
        run(go(seed))


def test_battle_and_bought_balloon_publish_choice():
    async def go():
        w = World(seed=19)
        await setup_game(w, ["doctor", "spy", "hero", "zombie"])
        await w.press(GM, "gnight")
        for i, c in zip(range(1, 5), ["london", "moscow", "paris", "berlin"]):
            await place(w, i, c)
        # two ships from different owners on the same sea square → battle
        for i in (1, 3):
            P(w, i)["units"]["ship"] = 1
            await w.cmd(GM, "pos", str(i), "n17")
            await w.press(i, "up:ship")
        # a bought spy balloon asks its owner whether to publish
        P(w, 2)["coins"] = 20
        await w.press(2, "bu:spy_balloon")
        await w.press(2, "ubt:spy:paris")
        await w.press(GM, "glock")
        assert w.g["battles"] and w.g["battles"][0]["status"] == "open"
        ask = w.last_to(2)
        bid = next(x for x in w.g["balloons"])["id"]
        assert f"bpub:{bid}:1" in ask.buttons()
        await w.press(2, f"bpub:{bid}:1")
        assert any("بالن جاسوسی" in t for t in w.texts_to(GROUP))
        await w.press(GM, "gbal")
        m = w.last_to(GM)
        loser = next(d for d in m.buttons() if d.startswith("gf:"))
        await w.press(GM, loser, message=m)
        assert len(w.g["units_on_map"]) == 1 and w.g["battles"][0]["status"] == "done"
        # a taxi rider still gets hit where they spent the night
        await w.cmd(GM, "pos", "4", "london")
        P(w, 4)["night_pos"] = "london"
        P(w, 4)["units"]["war_balloon"] = 0
    run(go())
