"""Cannon duels (Counter-Battery), the GM's approval of group posts, and voting only in the group."""
import time

from aiohttp.test_utils import TestClient, TestServer

from tests.harness import World, run, GM, GROUP
from tests.test_bot_flow import setup, place, next_step, P
from zombiebot import artillery, artillery_bot, gm_ui, outbox, web, battle_gif


def cannon(w, owner, square, name):
    u = {"id": f"u{owner}{name}", "kind": "cannon", "owner": owner, "square": square, "name": name}
    w.g["units_on_map"].append(u)
    return u


async def battle_world(monkeypatch, roles=("zombie", "doctor", "clown"), names=("عقاب", "طوفان")):
    monkeypatch.setenv("WEBAPP_URL", "https://example.up.railway.app/map")
    w = World(seed=91)
    await setup(w, list(roles))
    await next_step(w)                                   # night 1
    for i, c in zip(range(1, len(roles) + 1), ["paris", "berlin", "milan", "moscow"]):
        await place(w, i, c)
    for i, n in enumerate(names, start=1):
        cannon(w, i, "n15", n)
    await gm_ui.do_lock(w.bot)                           # 20:00 → the cannons on n15 start fighting
    return w


def test_two_cannons_on_one_square_start_a_secret_turn_based_duel(monkeypatch):
    async def go():
        w = await battle_world(monkeypatch)
        bs = artillery.battles(w.g)
        assert len(bs) == 1
        b = bs[0]
        assert b["status"] == "live" and {u["name"] for u in b["units"]} == {"عقاب", "طوفان"}
        assert b["city"] in ("london", "birmingham")         # n15 lies on the London–Birmingham road
        assert b["weather"] in artillery.WIND
        assert b["deadline"] - b["created"] == artillery.TURN_SECONDS
        # both owners are told, with only unit names and a button that opens the battle
        for i, mine, other in ((1, "عقاب", "طوفان"), (2, "طوفان", "عقاب")):
            msg = [m for m in w.sent if m.chat_id == i and "روبه‌رو شد" in m.text][-1]
            assert mine in msg.text and other in msg.text
            assert P(w, 3 - i)["name"] not in msg.text
            assert msg.buttons()[0].startswith("webapp:https://example.up.railway.app/battle?b=")
        # whose turn it is gets a nudge
        turn_owner = artillery.unit(b, b["turn"])["owner"]
        assert any("نوبت توپ" in m.text for m in w.sent if str(m.chat_id) == turn_owner)
        # what each player sees: own flag by team, the others random, no player names anywhere
        v1 = artillery.view(w.g, b, P(w, 1))
        me = next(u for u in v1["units"] if u["mine"])
        assert me["flag"] == "fr"                             # zombies fly the French flag
        v2 = artillery.view(w.g, b, P(w, 2))
        assert next(u for u in v2["units"] if u["mine"])["flag"] == "gb"   # humans the British
        assert "owner" not in str(v1) and P(w, 2)["name"] not in str(v1)
        assert v1["time"] in artillery.TIME_FA
    run(go())


def test_firing_through_the_web_app_destroys_the_cannon_and_posts_the_result(monkeypatch):
    async def go():
        w = await battle_world(monkeypatch)
        w.g["approve_group"] = True                     # the result waits for the GM
        b = artillery.battles(w.g)[0]
        shooter = artillery.unit(b, b["turn"])
        target = next(u for u in b["units"] if u is not shooter)
        web._token = "123:TEST"
        web._bot = w.bot
        client = TestClient(TestServer(web.make_app()))
        await client.start_server()
        try:
            other = web.sign_init_data({"id": int(target["owner"])}, "123:TEST")
            mine = web.sign_init_data({"id": int(shooter["owner"])}, "123:TEST")
            r = await client.get("/api/battle?b=" + b["id"], headers={"X-Init-Data": other})
            st = await r.json()
            assert st["my_turn"] is False and len(st["units"]) == 2
            # not your turn
            r = await client.post("/api/battle/shot", json={"b": b["id"], "unit": target["id"], "hp": {}}, headers={"X-Init-Data": other})
            assert r.status == 400
            # a miss: the turn passes, the wind changes
            wind = dict(b["wind"])
            r = await client.post("/api/battle/shot", json={"b": b["id"], "unit": shooter["id"], "target": target["id"], "ammo": "shell",
                                                            "trail": [[0, 1, 2], [3, 4, 5]], "craters": [[1, 2, 4.2, 1.9, 1.1]],
                                                            "hp": {target["id"]: 100}}, headers={"X-Init-Data": mine})
            st = await r.json()
            assert r.status == 200 and st["status"] == "live" and b["turn"] == target["id"] and b["wind"] != wind
            assert shooter["shells"] == 3 and st["shots"][0]["craters"]
            assert any("نوبت توپ" in m.text for m in w.sent if str(m.chat_id) == target["owner"])
            # the other cannon hits back and destroys it
            r = await client.post("/api/battle/shot", json={"b": b["id"], "unit": target["id"], "target": shooter["id"],
                                                            "hp": {shooter["id"]: 0, target["id"]: 100}}, headers={"X-Init-Data": other})
            st = await r.json()
            assert st["status"] == "won" and st["won"] is True
            assert b["winner"] == target["id"]
            assert shooter["id"] not in {u["id"] for u in w.g["units_on_map"]}     # out of the game
            assert any("منهدم شد" in m.text for m in w.sent if str(m.chat_id) == shooter["owner"])
            # nothing in the group yet: the GM sees the animation first
            assert not [m for m in w.sent if m.chat_id == GROUP and m.animation]
            waiting = outbox.pending(w.g)
            assert waiting and waiting[-1]["kind"] == "animation"
            assert any(m.animation and str(m.chat_id) == str(GM) for m in w.sent)
            await w.press(GM, f"g:ob:{waiting[-1]['id']}:1")
            anim = [m for m in w.sent if m.chat_id == GROUP and m.animation]
            assert anim and target["name"] in anim[-1].text and P(w, 1)["name"] not in anim[-1].text
            page = await client.get("/battle")
            assert page.status == 200 and "netBoot" in await page.text()
        finally:
            await client.close()
            web._bot = None
    run(go())


def test_turn_runs_out_after_two_hours_and_battle_ends_at_the_next_lock(monkeypatch):
    async def go():
        w = await battle_world(monkeypatch)
        b = artillery.battles(w.g)[0]
        first = b["turn"]
        await artillery_bot.check(w.bot, now=b["deadline"] + 1)
        assert b["turn"] != first and b["status"] == "live"
        assert any("وقت نوبت" in m.text for m in w.sent if str(m.chat_id) == artillery.unit(b, first)["owner"])
        # the next 20:00 lock ends it without a winner; both cannons stay
        await w.press(GM, "g:next")      # results
        await w.press(GM, "g:apply")
        await w.press(GM, "g:next")      # day
        await gm_ui.do_lock(w.bot)
        assert b["status"] == "draw" and len([u for u in w.g["units_on_map"] if u["kind"] == "cannon"]) == 2
        assert len(artillery.battles(w.g)) == 2                # and they meet again for another day
    run(go())


def test_three_cannons_all_fight_and_test_players_fire_by_themselves(monkeypatch):
    async def go():
        monkeypatch.setenv("WEBAPP_URL", "https://example.up.railway.app/map")
        w = World(seed=92)
        await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
        await w.press(GM, "g:mk")
        await w.press(GM, "g:next")
        fakes = [p for p in w.g["players"].values() if p.get("fake") and p["alive"]][:3]
        w.g["units_on_map"] = []
        for p in fakes:
            cannon(w, p["id"], "n21", "توپ" + str(-p["id"]))
        fresh = artillery.start_battles(w.g)
        await artillery_bot.announce_new(w.bot, fresh)
        b = fresh[0]
        assert len(b["units"]) == 3
        assert b["status"] in ("won", "wiped") or b["shots"]          # the test players fired on their own
        for _ in range(30):
            if b["status"] != "live":
                break
            await artillery_bot.check(w.bot, now=b["deadline"] + 1)
        assert b["shots"]
    run(go())


def test_battle_gif_draws():
    data = battle_gif.make_gif({"name": "عقاب", "flag": "ot"}, [{"name": "طوفان", "flag": "pr"}], "لندن", "night", "snow", 3)
    assert data[:3] == b"GIF" and len(data) > 10000


def test_group_posts_wait_for_the_gm_but_votes_go_straight_out():
    async def go():
        w = World(seed=93)
        await setup(w, ["doctor", "spy", "zombie"])
        w.g["approve_group"] = True
        await next_step(w)                                  # night 1 announcement → waits
        assert not any("شب ۱" in t for t in w.texts_to(GROUP))
        assert any("منتظر تأیید" in t and "شب ۱" in t for t in w.texts_to(GM))
        await w.press(GM, "g:obls")
        assert "g:oball" in w.last_to(GM).buttons()
        await w.press(GM, "g:oball")
        assert any("شب ۱" in t for t in w.texts_to(GROUP))
        # a dropped message never reaches the group
        from zombiebot.common import group
        await group(w.bot, "پیام آزمایشی", None)
        m = outbox.pending(w.g)[-1]
        await w.press(GM, f"g:ob:{m['id']}:0")
        assert not any("پیام آزمایشی" in t for t in w.texts_to(GROUP))
        # votes are not held back
        w.g["phase"], w.g["cycle"] = "day", 1
        await w.say(1, "#رای " + P(w, 2)["name"])
        assert [m for m in w.sent if m.chat_id == GROUP and m.animation]
        # and nobody can vote in the bot's private chat
        ans = await w.press(1, "p:vote")
        assert any("گروه" in (a or "") for a in ans)
    run(go())


def test_legendary_auction_closes_at_midnight():
    async def go():
        from zombiebot import legendary, bot as B
        w = World(seed=94)
        await setup(w, ["doctor", "zombie"])
        w.g["phase"], w.g["cycle"] = "day", 1
        legendary.spawn_next(w.g, where="paris")
        for i in (1, 2):
            P(w, i)["pos"] = "paris"
            P(w, i)["coins"] = 20
        await gm_ui.do_lock(w.bot)
        L = legendary.state(w.g)
        assert L["auction"]
        await w.press(1, "x:lb:3")
        assert L["auction"]["high"] == 3
        class Ctx:
            bot = w.bot
        await B.job_midnight(Ctx())
        assert not L["auction"] and "fouche_cipher" in P(w, 1)["legend"] and P(w, 1)["coins"] == 17
    run(go())
