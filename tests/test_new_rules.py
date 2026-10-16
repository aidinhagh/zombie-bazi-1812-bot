"""The October 16 changes: thief's borrowed act, the judge, takeover, autopilot features, kicking, the map web app."""
import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from tests.harness import World, run, GM, GROUP
from tests.test_bot_flow import setup, place, next_step, P
from zombiebot import actions, autopilot, web, events
from zombiebot.engine import resolve_night


def test_everything_is_persian():
    async def go():
        w = World(seed=40)
        await setup(w, ["doctor", "spy"])
        await next_step(w)
        await place(w, 1, "paris")
        latin = [m.text for m in w.sent if any(word in m.text for word in ("Welcome", "Night ", "Day ", "Your role", "Tonight"))]
        assert not latin, latin[:3]
        home = (await w.press(1, "p:home"), w.last_to(1))[1]
        assert "p:lang" not in home.buttons()
    run(go())


def test_thief_sees_role_at_once_and_acts_as_them():
    async def go():
        w = World(seed=41)
        await setup(w, ["thief", "sniper", "doctor", "zombie"])
        await next_step(w)
        for i, c in zip(range(1, 5), ["milan", "berlin", "amsterdam", "moscow"]):
            await place(w, i, c)
        await w.press(1, "p:act")
        await w.press(1, "p:a:steal")
        await w.press(1, "p:t:steal:2")
        # the role is revealed right away and the menu now offers the sniper's acts
        assert any("اسنایپر" in t and "نقش" in t for t in w.texts_to(1))
        menu = w.last_to(1)
        assert "به‌جای" in menu.text and "p:a:attack" in menu.buttons()
        await w.press(1, "p:a:attack")
        await w.press(1, "p:t:attack:4")
        acts = w.g["acts"]["1"]
        assert [a["type"] for a in acts] == ["steal", "attack"] and acts[1]["as_role"] == "sniper"
        # the sniper planned to shoot the zombie; that act is cancelled by the theft
        await w.press(2, "p:a:attack"); await w.press(2, "p:t:attack:4")
        res = resolve_night(w.g)
        lines = "\n".join(fa for fa, _ in res["lines"])
        assert "stolen" in lines
        # the borrowed attack used the sniper's attack stat (15), not the thief's (2)
        borrowed = next(l for l in lines.split("\n") if "attack" in l and P(w, 1)["name"] in l.split("→")[0])
        power = int(borrowed.split("قدرت")[1].split()[0])
        assert power >= 15 + 2
    run(go())


def test_thief_cannot_steal_from_monastery():
    async def go():
        w = World(seed=42)
        await setup(w, ["thief", "doctor"])
        await next_step(w)
        await place(w, 1, "paris"); await place(w, 2, "wagram")
        await w.press(1, "p:a:steal")
        ans = await w.press(1, "p:t:steal:2")
        assert ans and "خانقاه" in ans[-1] and "1" not in w.g["acts"]
    run(go())


async def to_day(w):
    await next_step(w); await next_step(w); await w.press(GM, "g:apply"); await next_step(w)


def test_judge_nullifies_once():
    async def go():
        w = World(seed=43)
        await setup(w, ["judge", "doctor", "spy", "zombie"])
        await next_step(w)
        for i, c in zip(range(1, 5), ["amsterdam", "berlin", "milan", "moscow"]):
            await place(w, i, c)
        await to_day(w)
        for v in (1, 2, 3):
            await w.say(v, "#رای رضا")
        await next_step(w)
        await w.press(GM, "g:vclose")
        jd = w.g["judgement"]
        assert jd["status"] == "waiting" and jd["cands"] == ["4"]
        assert any("قاضی" in t and "۲ ساعت" in t for t in w.texts_to(GROUP))
        judge_msg = w.last_to(1)
        assert "x:jd:null" in judge_msg.buttons()
        await w.press(1, "x:jd:null", message=judge_msg)
        assert P(w, 4)["alive"] and w.g["closed_cycle"] == 1
        assert P(w, 1)["charges"]["nullify"] == 0
        # next day: no nullify left — only "execute"
        await next_step(w)
        for i, c in zip(range(1, 5), ["berlin", "amsterdam", "moscow", "milan"]):
            await w.press(i, "p:move")
            m = w.last_to(i)
            go_btn = next(b for b in m.buttons() if b.startswith("p:go:"))
            await w.press(i, go_btn)
        await to_day(w)
        for v in (1, 2, 3):
            await w.say(v, "#رای رضا")
        await next_step(w)
        await w.press(GM, "g:vclose")
        assert "x:jd:null" not in w.last_to(1).buttons()
        await w.press(1, "x:jd:ok")
        assert not P(w, 4)["alive"]
    run(go())


def test_judge_picks_among_tied_and_default_when_silent():
    async def go():
        w = World(seed=44)
        await setup(w, ["judge", "doctor", "spy", "zombie", "priest"])
        await next_step(w)
        for i, c in zip(range(1, 6), ["amsterdam", "berlin", "milan", "moscow", "warsaw"]):
            await place(w, i, c)
        await to_day(w)
        await w.say(1, "#رای رضا"); await w.say(2, "#رای رضا")
        await w.say(3, "#رای نگار"); await w.say(4, "#رای نگار")
        await next_step(w)
        await w.press(GM, "g:vclose")
        assert sorted(w.g["judgement"]["cands"]) == ["4", "5"]
        # the judge picks only negar
        await w.press(1, "x:jt:5")
        await w.press(1, "x:jd:sel")
        assert not P(w, 5)["alive"] and P(w, 4)["alive"]
        assert P(w, 1)["charges"]["nullify"] == 1        # choosing among a tie doesn't use the nullify
    run(go())


def test_tie_without_judge_executes_everyone_tied():
    async def go():
        w = World(seed=45)
        await setup(w, ["doctor", "spy", "zombie", "priest"])
        await next_step(w)
        for i, c in zip(range(1, 5), ["amsterdam", "berlin", "milan", "moscow"]):
            await place(w, i, c)
        await to_day(w)
        await w.say(1, "#رای سارا"); await w.say(2, "#رای رضا")
        await w.press(GM, "g:vclose")
        assert not P(w, 3)["alive"] and not P(w, 4)["alive"]
        # voting is closed now
        await w.say(1, "#رای علی")
        assert "1" in w.g["votes"] and w.g["votes"]["1"] == "3"
    run(go())


def test_judge_on_the_gallows_has_no_say_and_timeout_runs_default():
    async def go():
        w = World(seed=46)
        await setup(w, ["judge", "doctor", "spy", "zombie"])
        await next_step(w)
        for i, c in zip(range(1, 5), ["amsterdam", "berlin", "milan", "moscow"]):
            await place(w, i, c)
        await to_day(w)
        await w.say(2, "#رای مریم"); await w.say(3, "#رای مریم")
        await w.press(GM, "g:vclose")
        assert not P(w, 1)["alive"] and not w.g.get("judgement")
    run(go())
    async def go2():
        w = World(seed=47)
        await setup(w, ["judge", "doctor", "spy", "zombie"])
        await next_step(w)
        for i, c in zip(range(1, 5), ["amsterdam", "berlin", "milan", "moscow"]):
            await place(w, i, c)
        await to_day(w)
        await w.say(2, "#رای رضا")
        await w.press(GM, "g:vclose")
        assert w.g["judgement"]["status"] == "waiting"
        from types import SimpleNamespace
        ctx = w.ctx(0); ctx.job = SimpleNamespace(data=w.g["cycle"])
        await events.job_judge_timeout(ctx)
        assert not P(w, 4)["alive"] and any("وقت قاضی" in t for t in w.texts_to(GROUP))
    run(go2())


def test_apothecary_decides_by_day_from_the_menu():
    async def go():
        w = World(seed=48)
        await setup(w, ["apothecary", "doctor", "spy"])
        await next_step(w)
        for i, c in zip(range(1, 4), ["paris", "berlin", "milan"]):
            await place(w, i, c)
        await w.press(1, "p:a:poison"); await w.press(1, "p:t:poison:2")
        await next_step(w); await next_step(w); await w.press(GM, "g:apply")
        await next_step(w)    # day
        home = (await w.press(1, "p:home"), w.last_to(1))[1]
        assert "p:pend" in home.buttons()
        await w.press(1, "p:pend")
        m = w.last_to(1)
        an = next(b for b in m.buttons() if b.startswith("x:an:") and b.endswith(":1"))
        await w.press(1, an, message=m)
        assert w.g["poisons"][0]["status"] == "cured"
        await w.press(GM, "g:vclose"); await next_step(w)
        assert P(w, 2)["alive"]
    run(go())


def test_buying_a_spy_balloon_offers_to_launch_it_right_away():
    async def go():
        w = World(seed=49)
        await setup(w, ["doctor", "spy"])
        await next_step(w)
        await place(w, 1, "moscow"); await place(w, 2, "paris")
        P(w, 1)["coins"] = 20
        await w.press(1, "p:shop")
        await w.press(1, "p:bu:spy_balloon")
        m = w.last_to(1)
        assert "p:ubt:spy:paris" in m.buttons()
        await w.press(1, "p:ubt:spy:paris", message=m)
        await next_step(w)     # lock → result
        b = w.g["balloons"][0]
        assert b["result"] == [P(w, 2)["name"]]
        assert any("📢" in str(x.buttons()) or "منتشر" in x.text for x in w.sent if x.chat_id == 1)
    run(go())


def test_kick_bans_from_the_bot():
    async def go():
        w = World(seed=50)
        await w.cmd(8902100988, "start", user=w.user(8902100988, "Gustav Ivanova", None))
        assert "8902100988" in w.g["players"]
        assert any("g:kick:8902100988" in m.buttons() for m in w.sent if m.chat_id == GM)
        await w.press(GM, "g:kick:8902100988")
        await w.press(GM, "g:kicky:8902100988")
        assert "8902100988" not in w.g["players"]
        await w.cmd(8902100988, "start", user=w.user(8902100988, "Gustav Ivanova", None))
        assert "8902100988" not in w.g["players"]
    run(go())


def test_take_over_undoes_autopilot_so_you_can_roll_and_throw():
    async def go():
        w = World(seed=51)
        await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
        await w.press(GM, "g:mk")
        m = w.player("مریم")
        assert m["moved"] and m["darts"]["money"]
        start = m["_auto"]["player"]["pos"]
        await w.press(GM, f"g:as:{m['id']}")
        m = w.player("مریم")
        assert not m["moved"] and m["darts"] == {"money": False, "item": False} and m["pos"] == start
        assert str(m["id"]) not in w.g["acts"]
        # now the GM rolls and moves as مریم
        await w.press(GM, "p:move")
        menu = w.last_to(GM)
        dest = next(b for b in menu.buttons() if b.startswith("p:go:"))
        await w.press(GM, dest)
        assert w.player("مریم")["moved"]
        await w.press(GM, "p:dm")
        assert w.player("مریم")["darts"]["money"]
        await w.press(GM, "p:a:spy"); await w.press(GM, f"p:t:spy:{w.player('علی')['id']}")
        assert w.g["acts"][str(m["id"])][0]["type"] == "spy"
    run(go())


def test_autopilot_uses_balloons_units_items_and_specials():
    async def go():
        w = World(seed=52)
        await w.cmd(GM, "setgroup", chat_type="group", chat_id=GROUP)
        await w.press(GM, "g:mk")
        seen = {"balloons": 0, "units": 0, "specials": set(), "slots": 0, "routes": 0}
        for _ in range(4):
            acts = [a for lst in w.g["acts"].values() for a in lst]
            seen["specials"] |= {a["type"] for a in acts}
            await w.press(GM, "g:ff")
            if w.g["phase"] != "night":
                await w.press(GM, "g:jdef")
                await next_step(w)
            seen["balloons"] = len(w.g["balloons"])
            seen["units"] = max(seen["units"], len(w.g["units_on_map"]) + sum(sum(p["units"].values()) for p in w.g["players"].values()))
            seen["routes"] += sum(1 for v in w.g["route_state"].values() if v != "ok")
        assert seen["balloons"] >= 2, seen
        assert {"steal", "bomb", "poison", "bullets", "guess", "convert", "duel"} & seen["specials"], seen
        assert len(seen["specials"] - {"attack", "protect", "defuse", "spy"}) >= 3, seen
    run(go())


def test_web_app_auth_state_and_move():
    async def go():
        w = World(seed=53)
        await setup(w, ["doctor", "spy"])
        await next_step(w)
        await place(w, 2, "berlin")
        web._token = "123:TEST"
        good = web.sign_init_data({"id": 1, "first_name": "m"}, "123:TEST")
        assert web.verify_init_data(good, "123:TEST")["id"] == 1
        assert web.verify_init_data(good.replace("hash=", "hash=0"), "123:TEST") is None
        assert web.verify_init_data(web.sign_init_data({"id": 1}, "999:OTHER"), "123:TEST") is None
        client = TestClient(TestServer(web.make_app()))
        await client.start_server()
        try:
            r = await client.get("/api/state")
            assert r.status == 401
            r = await client.get("/api/state", headers={"X-Init-Data": good})
            st = await r.json()
            assert st["mode"] == "first" and len(st["options"]) == 15 and st["me"]["name"] == "مریم"
            r = await client.post("/api/move", json={"dest": "paris"}, headers={"X-Init-Data": good})
            assert (await r.json())["ok"] and P(w, 1)["pos"] == "paris"
            r = await client.post("/api/move", json={"dest": "moscow"}, headers={"X-Init-Data": good})
            assert r.status == 400 and "حرکت" in (await r.json())["error"]
            # the GM playing as a test player moves that player
            gm = web.sign_init_data({"id": GM}, "123:TEST")
            w.g.setdefault("as", {})[str(GM)] = "2"
            st = await (await client.get("/api/state", headers={"X-Init-Data": gm})).json()
            assert st["me"]["name"] == "علی" and st["mode"] == "moved"
            page = await client.get("/map")
            assert page.status == 200 and "Telegram.WebApp" in await page.text()
        finally:
            await client.close()
    run(go())


def test_roll_offers_the_web_app_when_configured(monkeypatch):
    monkeypatch.setenv("WEBAPP_URL", "https://example.up.railway.app/map")
    async def go():
        w = World(seed=54)
        await setup(w, ["doctor", "spy"])
        await next_step(w)
        await place(w, 1, "paris")
        await to_day(w)
        await w.press(1, "p:move")
        m = w.last_to(1)
        assert m.buttons()[0] == "webapp:https://example.up.railway.app/map"
        assert any(b.startswith("p:go:") for b in m.buttons())
    run(go())
