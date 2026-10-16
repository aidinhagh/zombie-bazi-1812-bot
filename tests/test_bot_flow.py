"""Whole games through the real Telegram handlers, offline: menus, group votes, the control room and the test lab."""
import random

from tests.harness import World, run, GM, GROUP
from zombiebot import actions

NAMES = {1: ("مریم", "maryam"), 2: ("علی", "ali"), 3: ("سارا", "sara"), 4: ("رضا", "reza"), 5: ("نگار", "negar"),
         6: ("کیان", "kian"), 7: ("لیلا", "leila"), 8: ("امیر", "amir")}


def P(w, i):
    return w.g["players"][str(i)]


async def setup(w, roles):
    """Players 1..n register with /start; the GM gives roles from their player cards."""
    await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
    for i, role in enumerate(roles, start=1):
        name, user = NAMES[i]
        await w.cmd(i, "start", user=w.user(i, name, user))
        await w.press(GM, f"g:sr:{i}:{role}")
    assert all(p["role"] for p in w.g["players"].values())


async def place(w, i, city):
    await w.press(i, "p:move")
    m = w.last_to(i)
    assert f"p:go:{city}" in m.buttons()
    await w.press(i, f"p:go:{city}")
    assert P(w, i)["pos"] == city


async def next_step(w):
    await w.press(GM, "g:next")


def test_control_room_walks_the_whole_cycle():
    async def go():
        w = World(seed=3)
        await w.cmd(GM, "start")
        room = w.last_to(GM)
        assert "g:next" in room.buttons() and "Players" in room.text or "بازیکنان" in room.text
        await setup(w, ["zombie", "yakuza", "doctor", "spy", "hero", "clown"])
        await next_step(w)                                  # start night 1
        assert w.g["phase"] == "night" and w.g["cycle"] == 1
        assert any("شب ۱" in m.text for m in w.sent if m.chat_id == GROUP)
        for i, c in zip(range(1, 7), ["paris", "berlin", "amsterdam", "milan", "warsaw", "wagram"]):
            await place(w, i, c)
        # darts and shop
        await w.press(3, "p:darts")
        await w.press(3, "p:dm")
        await w.press(3, "p:di")
        assert P(w, 3)["darts"] == {"money": True, "item": True}
        coins = P(w, 3)["coins"]
        await w.press(3, "p:bp:protect")
        assert P(w, 3)["coins"] == coins - 2
        # acts
        for i, t, tgt in [(1, "attack", 3), (2, "attack", 3), (3, "protect", 3), (4, "spy", 1)]:
            await w.press(i, "p:act")
            await w.press(i, f"p:a:{t}")
            await w.press(i, f"p:t:{t}:{tgt}")
        assert len(w.g["acts"]) == 4
        home = (await w.press(4, "p:home"), w.last_to(4))[1]
        assert "1/1" in home.text or "۱/۱" in home.text
        # lock: public map is a picture plus a list
        await next_step(w)
        assert w.g["locked"]
        grp = [m for m in w.sent if m.chat_id == GROUP]
        assert any(m.photo for m in grp) and any("Closed routes" in m.text for m in grp)
        # resolve, toggle one effect off and on, apply
        await next_step(w)
        assert w.g["pending"]
        res = w.last_to(GM)
        assert "g:apply" in res.buttons()
        eid = w.g["pending"]["effects"][0]["id"]
        await w.press(GM, f"g:ef:{eid}", message=res)
        assert not w.g["pending"]["effects"][0]["on"]
        await w.press(GM, f"g:ef:{eid}", message=res)
        await w.press(GM, "g:apply")
        assert w.g["applied_cycle"] == 1
        assert any("Your spy result" in t or "نتیجه جاسوسی" in t for t in w.texts_to(4))
        # day: votes in the group
        await next_step(w)
        assert w.g["phase"] == "day"
        await w.say(1, "#رای نگار")
        await w.say(2, "#رای negar")
        await w.say(3, "#رای kian")
        await w.say(4, "#رای کیان")
        assert w.g["votes"] == {"1": "5", "2": "5", "3": "6", "4": "6"}
        anims = [m for m in w.sent if m.chat_id == GROUP and m.animation]
        assert len(anims) == 4 and "✅" in anims[0].text
        # second vote doesn't count
        await w.say(1, "#رای کیان")
        assert w.g["votes"]["1"] == "5"
        assert "⛔" in [m for m in w.sent if m.chat_id == GROUP and m.animation][-1].text
        # menu vote posts in the group too
        await w.press(5, "p:vote")
        await w.press(5, "p:v:6")
        assert w.g["votes"]["5"] == "6"
        assert any("نگار: #رای کیان" in t for t in w.texts_to(GROUP))
        # tally
        await w.say(6, "#رایگیری")
        assert any("🥇" in t for t in w.texts_to(GROUP))
        # close the vote and execute the clown (kian)
        await next_step(w)
        assert "g:ex:6" in w.last_to(GM).buttons()
        await w.press(GM, "g:ex:6")
        await w.press(GM, "g:exy:6")
        assert not P(w, 6)["alive"]
        assert any("دلقک" in t and "برد" in t for t in w.texts_to(GROUP))
        await next_step(w)
        assert w.g["phase"] == "night" and w.g["cycle"] == 2
        # GM map is a picture plus a list
        await w.press(GM, "g:map")
        gm_msgs = [m for m in w.sent if m.chat_id == GM]
        assert any(m.photo for m in gm_msgs) and any("مریم" in m.text and "🏙" in m.text for m in gm_msgs)
    run(go())


def test_movement_map_numbers_match_buttons():
    async def go():
        w = World(seed=4)
        await setup(w, ["doctor", "spy"])
        await next_step(w)
        await place(w, 1, "paris")
        await next_step(w); await next_step(w); await w.press(GM, "g:apply"); await next_step(w)   # → day 1
        w.forced_dice = [3]
        await w.press(1, "p:move")
        pic = [m for m in w.sent if m.chat_id == 1 and m.photo][-1]
        menu = w.last_to(1)
        dests = [b for b in menu.buttons() if b.startswith("p:go:")]
        assert pic and len(dests) == len(actions.move_options(w.g, P(w, 1), 3))
        assert "1." in menu.text or "۱." in menu.text
        await w.press(1, dests[0])
        assert P(w, 1)["pos"] == dests[0].split(":")[2]
        # one move per phase
        ans = await w.press(1, "p:move")
        assert ans and ans[-1]
    run(go())


def test_vote_rules_matching_hotel_dead_and_delete():
    async def go():
        w = World(seed=5)
        await setup(w, ["doctor", "spy", "hero", "zombie", "priest"])
        await next_step(w)
        for i, c in zip(range(1, 6), ["paris", "berlin", "barcelona", "milan", "warsaw"]):
            await place(w, i, c)
        await next_step(w)          # lock: sara (3) is in the hotel
        assert P(w, 3)["flags"].get("hotel_immune")
        await next_step(w); await w.press(GM, "g:apply"); await next_step(w)   # day 1
        # nickname
        await w.cmd(GM, "nick", "رضا", "رضی‌جون")
        await w.say(1, "#رای رضی‌جون")
        assert w.g["votes"]["1"] == "4"
        # hotel: lightning, vote not used up
        await w.say(2, "#رای سارا")
        assert "2" not in w.g["votes"]
        assert "⚡" in [m for m in w.sent if m.chat_id == GROUP and m.animation][-1].text
        await w.say(2, "#رای Reza")
        assert w.g["votes"]["2"] == "4"
        # a reply counts as naming the person
        target_msg = w.sent[-1]
        target_msg.from_user = w.user(5, "نگار", "negar")
        await w.say(3, "#رای", reply_to=target_msg)
        assert w.g["votes"]["3"] == "5"
        # strangers and the dead
        await w.say(77, "#رای مریم")
        assert "77" not in w.g["votes"]
        actions.kill(w.g, P(w, 5), "test")
        await w.say(5, "#رای مریم")
        assert any("مرده" in t for t in w.texts_to(GROUP))
        await w.say(4, "#رای zzzz")
        assert any("پیدا نکردم" in t for t in w.texts_to(GROUP))
        # GM deletes a vote by reply and by name
        voter_msg = w.sent[-1]
        voter_msg.from_user = w.user(1, "مریم", "maryam")
        await w.cmd(GM, "delete", chat_type="supergroup", chat_id=GROUP)
        await w.cmd(GM, "delete", "رضا", chat_type="supergroup", chat_id=GROUP)
        assert "1" not in w.g["votes"] and "2" not in w.g["votes"]
        # vote screen: remove one vote via buttons
        await w.say(1, "#رای سارا")   # lightning again (still in hotel)
        await w.say(1, "#رای علی")
        await w.press(GM, "g:votes")
        await w.press(GM, "g:vdel")
        await w.press(GM, "g:vd:1")
        assert "1" not in w.g["votes"]
    run(go())


def test_real_gif_renders_in_persian():
    async def go():
        w = World(seed=6, real_gifs=True)
        await setup(w, ["doctor", "spy"])
        w.g["phase"], w.g["cycle"] = "day", 1
        await w.say(1, "#رای سارا")   # no such player → no GIF
        await w.say(1, "#رای ali")
        anim = [m for m in w.sent if m.animation]
        assert anim and "علی" in anim[-1].text
    run(go())


def test_specials_bomb_poison_duel_bullets_yakuza():
    async def go():
        w = World(seed=5)
        await setup(w, ["bomber", "apothecary", "judge", "musketeer", "yakuza", "doctor", "spy", "cultist"])
        await next_step(w)
        for i, c in zip(range(1, 9), ["paris", "berlin", "milan", "vienna", "warsaw", "moscow", "london", "stockholm"]):
            await place(w, i, c)
        for seq in (["p:a:bomb", "p:t:bomb:6", "p:tb:6:3"], ["p:a:poison", "p:t:poison:7"], ["p:a:duel", "p:t:duel:5", "p:td:5:6"]):
            who = {"p:a:bomb": 1, "p:a:poison": 2, "p:a:duel": 3}[seq[0]]
            for d in seq:
                await w.press(who, d)
        for d in ["p:a:bullets", "p:bl:6", "p:bl:7", "p:bn", "p:bx:6"]:
            await w.press(4, d)
        await w.press(8, "p:a:convert"); await w.press(8, "p:t:convert:6")
        assert set(w.g["acts"]) == {"1", "2", "3", "4", "8"}
        await next_step(w); await next_step(w); await w.press(GM, "g:apply")
        bomb_msg = next(m for m in reversed(w.sent) if m.chat_id == GROUP and any(b.startswith("x:bw:") for b in m.buttons()))
        bid = w.g["bombs"][0]["id"]
        await w.press(7, f"x:bw:{bid}:1", message=bomb_msg)
        assert w.g["bombs"][0]["status"] == "armed"
        await w.press(6, f"x:bw:{bid}:1", message=bomb_msg)
        assert w.g["bombs"][0]["status"] == "exploded" and not P(w, 6)["alive"]
        await w.press(2, f"x:an:{w.g['poisons'][0]['id']}:0")
        await next_step(w)        # day
        assert P(w, 7)["bullets"] == ["practice"]
        await w.press(7, "p:shoot")
        await w.press(7, "p:sh:3")
        assert P(w, 3)["alive"]
        await w.press(GM, "g:votes")
        await w.press(GM, "g:exy:5")
        assert P(w, 5)["flags"].get("yakuza_pending")
        await w.press(5, "x:yk:8")      # the cultist can't be taken
        assert P(w, 8)["alive"]
        P(w, 5)["flags"]["yakuza_pending"] = True
        await w.press(5, "x:yk:4")
        assert not P(w, 4)["alive"]
        await next_step(w)        # next night: the poison kills
        assert not P(w, 7)["alive"] and w.g["poisons"][0]["status"] == "killed"
    run(go())


def test_duel_rounds():
    async def go():
        w = World(seed=7)
        await setup(w, ["judge", "doctor", "spy"])
        await next_step(w)
        for i, c in zip(range(1, 4), ["paris", "berlin", "milan"]):
            await place(w, i, c)
        for d in ["p:a:duel", "p:t:duel:2", "p:td:2:3"]:
            await w.press(1, d)
        await next_step(w); await next_step(w); await w.press(GM, "g:apply")
        du = w.g["duels"][0]
        hp2, hp3 = P(w, 2)["hp"], P(w, 3)["hp"]
        await w.press(2, f"x:rp:d:{du['id']}:r"); await w.press(3, f"x:rp:d:{du['id']}:r")
        for _ in range(3):
            await w.press(2, f"x:rp:d:{du['id']}:p"); await w.press(3, f"x:rp:d:{du['id']}:r")
        assert du["status"] == "done" and P(w, 3)["hp"] == hp3 - 30 and P(w, 2)["hp"] == hp2
    run(go())


def test_places_units_balloons_taxi_slots_bet():
    async def go():
        w = World(seed=11)
        await setup(w, ["hero", "spy", "zombie_doctor", "doctor", "zombie", "thief"])
        await next_step(w)
        for i, c in zip(range(1, 7), ["london", "berlin", "vienna", "stockholm", "stockholm", "constantinople"]):
            await place(w, i, c)
        P(w, 1)["coins"] = 50
        await w.press(1, "p:bu:ship")
        assert P(w, 1)["units"]["ship"] == 1
        await w.press(2, "p:bag"); await w.press(2, "p:ub:spy"); await w.press(2, "p:ubt:spy:stockholm")
        await w.press(3, "p:ub:spy"); await w.press(3, "p:ubt:spy:london")
        await w.press(1, "p:ub:war"); await w.press(1, "p:ubt:war:constantinople")
        await w.press(4, "p:bet"); await w.press(4, "p:bt:5:5")
        b = w.g["bets"][0]
        await w.press(5, f"x:ba:{b['id']}:1")
        c4, c5 = P(w, 4)["coins"], P(w, 5)["coins"]
        await w.press(4, f"x:rp:b:{b['id']}:s"); await w.press(5, f"x:rp:b:{b['id']}:p")
        assert P(w, 4)["coins"] == c4 + 5 and P(w, 5)["coins"] == c5 - 5
        await next_step(w)        # lock
        spyb = [x for x in w.g["balloons"] if x["kind"] == "spy"]
        assert spyb[0].get("published") and not spyb[1].get("published")
        await w.press(GM, "g:bal")
        wb = next(x for x in w.g["balloons"] if x["kind"] == "war")
        hp6 = P(w, 6)["hp"]
        await w.press(GM, f"g:wb:{wb['id']}:50")
        assert w.g["loc_damage"]["constantinople"] == 50 and P(w, 6)["hp"] == hp6 - 5
        home = (await w.press(1, "p:home"), w.last_to(1))[1]
        assert "p:taxi" in home.buttons()
        await w.press(1, "p:taxi"); await w.press(1, "p:tx:warsaw")
        assert P(w, 1)["night_pos"] == "warsaw" and P(w, 1)["public_pos"] == "london"
        w.forced_dice = [10, 64]
        await w.press(3, "p:slots"); await w.press(3, "p:slots")
        assert P(w, 3)["slots"]["hit"]
        ans = await w.press(3, "p:slots")
        assert ans and ans[-1]
    run(go())


def test_berlin_revive_and_cannon_toll():
    async def go():
        w = World(seed=13)
        await setup(w, ["doctor", "spy", "zombie", "hero"])
        await next_step(w)
        for i, c in zip(range(1, 5), ["berlin", "constantinople", "paris", "amsterdam"]):
            await place(w, i, c)
        await w.press(GM, "g:kill:4")
        await next_step(w)
        w.forced_dice = [22]
        await w.press(1, "p:slots")
        assert "p:rv:4" in w.last_to(1).buttons()
        await w.press(1, "p:rv:4")
        assert P(w, 4)["alive"]
        await next_step(w); await w.press(GM, "g:apply"); await next_step(w)
        P(w, 2)["coins"] = 20
        await w.press(2, "p:bu:cannon")
        await w.cmd(GM, "pos", "علی", "n25")
        await w.press(2, "p:up:cannon")
        P(w, 3)["pos"] = "wagram"
        w.forced_dice = [2]
        await w.press(3, "p:move")
        assert "p:go:n25" in w.last_to(3).buttons()
        coins3 = P(w, 3)["coins"]
        await w.press(3, "p:go:n25")
        assert P(w, 3)["coins"] == coins3 - 10 and P(w, 2)["coins"] == 20 - 6 + 10
    run(go())


def test_test_lab_fast_game_with_group_votes():
    async def go():
        w = World(seed=17)
        await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
        await w.press(GM, "g:lab")
        await w.press(GM, "g:mk")
        fakes = [p for p in w.g["players"].values() if p.get("fake")]
        assert len(fakes) == 24 and {p["name"] for p in fakes} >= {"مریم", "علی", "سارا"}
        assert w.g["phase"] == "night" and w.g["test_mode"]
        # test players already moved and acted — no waiting
        assert len(w.g["acts"]) >= 20 and all(p["moved"] for p in fakes)
        # play as مریم: her menu comes to the GM with a banner
        maryam = w.player("مریم")
        await w.press(GM, "g:aslist")
        await w.press(GM, f"g:as:{maryam['id']}")
        assert "مریم" in w.last_to(GM).text and "🕹" in w.last_to(GM).text
        await w.press(GM, "p:act")
        assert "p:a:attack" in w.last_to(GM).buttons()
        await w.press(GM, "g:asoff")
        # lock, resolve, apply, day
        await next_step(w); await next_step(w); await w.press(GM, "g:apply")
        await next_step(w)
        assert w.g["phase"] == "day"
        # the test players voted in the group with #رای, then the tally was posted
        group_texts = w.texts_to(GROUP)
        assert sum(1 for t in group_texts if ": #رای " in t) >= 15
        assert any(t.startswith("#رایگیری") and "🥇" in t for t in group_texts)
        assert len(w.g["votes"]) >= 15
        await next_step(w)
        assert any(b.startswith("g:ex:") for b in w.last_to(GM).buttons())
    run(go())


def test_test_lab_auto_run_reaches_next_night():
    async def go():
        w = World(seed=19)
        await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
        await w.press(GM, "g:mk")
        await w.press(GM, "g:ff")
        assert w.g["phase"] == "night" and w.g["cycle"] == 2
        assert sum(1 for p in w.g["players"].values() if not p["alive"]) >= 1
        assert any("اعدام" in t or "اعدام نشد" in t for t in w.texts_to(GROUP))
        await w.press(GM, "g:ff")
        assert w.g["cycle"] == 3
    run(go())


def test_gm_who_registered_early_gets_the_control_room():
    async def go():
        w = World(seed=23)
        from zombiebot.state import new_player
        w.g["players"][str(GM)] = new_player(GM, "Boss")
        await w.cmd(GM, "start")
        assert str(GM) not in w.g["players"]
        assert "g:next" in w.last_to(GM).buttons()
        await w.cmd(GM, "menu")
        assert "g:next" in w.last_to(GM).buttons()
    run(go())


def test_bot_added_to_group_registers_it():
    async def go():
        w = World(seed=29)
        from types import SimpleNamespace
        from zombiebot import bot as B
        cmu = SimpleNamespace(chat=SimpleNamespace(id=-777, type="supergroup", title="Zombie"),
                              new_chat_member=SimpleNamespace(status="administrator"), from_user=w.user(GM))
        await B.on_my_membership(SimpleNamespace(my_chat_member=cmu), w.ctx(GM))
        assert w.g["group_id"] == -777 and any("#رای" in t for t in w.texts_to(-777))
    run(go())


def test_fuzz_random_buttons_through_fast_games():
    """Play as every test player in turn and mash random buttons through several fast cycles; group votes included."""
    async def go(seed):
        w = World(seed=seed)
        rng = random.Random(seed)
        await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
        await w.press(GM, "g:mk")
        for _cycle in range(3):
            for _phase in range(2):
                for p in [x for x in w.g["players"].values() if x["alive"] and x.get("fake")][:12]:
                    await w.press(GM, f"g:as:{p['id']}")
                    for _ in range(10):
                        m = w.last_to(GM)
                        btns = [b for b in (m.buttons() if m else []) if not b.startswith("g:")]
                        if not btns:
                            await w.press(GM, "p:home")
                            continue
                        await w.press(GM, rng.choice(btns), message=m)
                    if w.g["phase"] == "day" and rng.random() < 0.5:
                        target = rng.choice([x for x in w.g["players"].values() if x.get("fake")])
                        await w.say(GM, "#رای " + rng.choice([target["name"], target["username"], "کسی"]))
                await w.press(GM, "g:asoff")
                for m in list(w.sent[-60:]):
                    for d in m.buttons():
                        if d.startswith("x:") and rng.random() < 0.4:
                            await w.press(GM, d, message=m)
                await w.press(GM, "g:bal")
                m = w.last_to(GM)
                for d in m.buttons():
                    if d.startswith(("g:wb:", "g:bf:")):
                        await w.press(GM, d, message=m)
                        break
                for screen in ("g:players:0", "g:acts", "g:votes", "g:lab", "g:setup", "g:home"):
                    await w.press(GM, screen)
                await next_step(w)
                if w.g.get("pending"):
                    await w.press(GM, "g:apply")
                    await next_step(w)
                if w.g["phase"] == "day" and w.g.get("closed_cycle") != w.g["cycle"]:
                    await next_step(w)
                    m = w.last_to(GM)
                    ex = [d for d in m.buttons() if d.startswith("g:ex:")]
                    await w.press(GM, ex[0].replace("g:ex:", "g:exy:") if ex else "g:noex")
                    await next_step(w)
        await w.press(GM, "g:map")
    for seed in range(4):
        run(go(seed))
