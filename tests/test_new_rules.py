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
        assert "دزدیده" in lines
        # the borrowed attack used the sniper's attack stat (15), not the thief's (2)
        ls = lines.split("\n")
        i = next(k for k, l in enumerate(ls) if "قرضی" in l and "حمله" in l)
        assert "حمله 15" in ls[i + 1]             # the sniper's attack stat, not the thief's 2
        power = int(ls[i + 1].split("=")[1].split()[0])
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
            assert st["mode"] == "first" and len(st["options"]) == 43 and st["me"]["name"] == "مریم"
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


# ---------------- round 3: Oct 16 afternoon ----------------

def test_player_throws_their_own_act_dice():
    async def go():
        w = World(seed=60)
        await setup(w, ["zombie", "doctor"])
        await next_step(w)
        await place(w, 1, "berlin"); await place(w, 2, "milan")
        await w.press(1, "p:a:attack"); await w.press(1, "p:t:attack:2")
        m = w.last_to(1)
        assert "p:dice:0" in m.buttons()
        w.forced_dice = [6, 5]
        await w.press(1, "p:dice:0", message=m)
        assert w.g["acts"]["1"][0]["dice"] == [6, 5]
        ans = await w.press(1, "p:dice:0")
        assert ans and ans[-1]                       # only once
        res = resolve_night(w.g)
        line = next(fa for fa, _ in res["lines"] if "⚔️ حمله ·" in fa)
        assert "تاس 6+5" in line and "= 25" in line   # 14 attack + 11
    run(go())


def test_every_act_can_target_yourself():
    async def go():
        w = World(seed=61)
        await setup(w, ["spy", "doctor"])
        await next_step(w)
        await place(w, 1, "berlin")
        for t in ("attack", "defuse", "spy", "protect"):
            await w.press(1, f"p:a:{t}")
            assert f"p:t:{t}:1" in w.last_to(1).buttons(), t
    run(go())


def test_monastery_two_acts_only_on_an_even_die_and_only_there():
    async def go():
        w = World(seed=62)
        await setup(w, ["doctor", "spy", "zombie"])
        await next_step(w)
        await place(w, 1, "wagram"); await place(w, 2, "berlin"); await place(w, 3, "milan")
        await next_step(w)                           # lock
        assert not P(w, 1)["double_act"]
        home = (await w.press(1, "p:home"), w.last_to(1))[1]
        assert "p:wroll" in home.buttons()
        w.forced_dice = [4]
        await w.press(1, "p:wroll")
        assert P(w, 1)["double_act"]
        await w.press(1, "p:a:spy"); await w.press(1, "p:t:spy:2")
        await w.press(1, "p:a:protect"); await w.press(1, "p:t:protect:1")
        assert len(w.g["acts"]["1"]) == 2
        ans = await w.press(1, "p:wroll")
        assert ans and ans[-1]
        # outside the monastery a leftover flag gives nothing
        P(w, 2)["double_act"] = True
        await w.press(2, "p:a:spy"); await w.press(2, "p:t:spy:1")
        ans = await w.press(2, "p:a:protect")
        await w.press(2, "p:t:protect:2")
        assert len(w.g["acts"]["2"]) == 1
    run(go())
    async def odd():
        w = World(seed=63)
        await setup(w, ["doctor", "spy"])
        await next_step(w)
        await place(w, 1, "wagram"); await place(w, 2, "berlin")
        await next_step(w)
        w.forced_dice = [3]
        await w.press(1, "p:wroll")
        assert not P(w, 1)["double_act"]
    run(odd())


def test_piracy_charges_anyone_passing_along_the_route():
    async def go():
        w = World(seed=64)
        await setup(w, ["doctor", "spy", "zombie"])
        await next_step(w)
        await place(w, 1, "paris"); await place(w, 2, "milan"); await place(w, 3, "berlin")
        await to_day(w)
        # علی (2) walks Milan → n21 (Paris–Milan road) and plants a cannon there, naming it
        P(w, 2)["units"]["cannon"] = 1
        w.forced_dice = [1]
        await w.press(2, "p:move"); await w.press(2, "p:go:n21")
        await w.press(2, "p:up:cannon")
        assert w.g["units_on_map"][0]["square"] == "n21"
        assert P(w, 2)["flags"]["naming"]
        from types import SimpleNamespace
        from zombiebot import player_ui
        msg = SimpleNamespace(text="شیر جاده", reply_text=lambda *a, **k: w.bot.send_message(2, *a, **k))
        await player_ui.on_private_text(SimpleNamespace(effective_chat=SimpleNamespace(type="private"), message=msg,
                                                        effective_user=w.user(2)), w.ctx(2))
        assert w.g["units_on_map"][0]["name"] == "شیر جاده"
        # next phase: مریم (1) goes Paris → Milan along that road: she pays without stopping on n21
        await next_step(w); await w.press(GM, "g:vclose") if w.g["phase"] == "day" else None
        await next_step(w)
        coins1, coins2 = P(w, 1)["coins"], P(w, 2)["coins"]
        w.forced_dice = [2]
        await w.press(1, "p:move"); await w.press(1, "p:go:milan")
        assert P(w, 1)["coins"] == max(0, coins1 - 10) and P(w, 2)["coins"] == coins2 + min(10, coins1)
        assert any("شیر جاده" in t for t in w.texts_to(1))
        assert not any("علی" in t for t in w.texts_to(1) if "عوارض" in t)   # the owner stays anonymous
    run(go())


def test_planting_on_a_square_you_passed():
    async def go():
        w = World(seed=65)
        await setup(w, ["doctor", "spy"])
        await next_step(w)
        await place(w, 1, "paris"); await place(w, 2, "berlin")
        await to_day(w)
        P(w, 1)["units"]["cannon"] = 1
        w.forced_dice = [2]
        await w.press(1, "p:move"); await w.press(1, "p:go:milan")     # Paris → n21 → Milan
        await w.press(1, "p:up:cannon")
        assert w.g["units_on_map"][0]["square"] == "n21"
    run(go())


def test_spy_balloon_report_is_anonymous_named_and_on_the_map():
    async def go():
        w = World(seed=66)
        await setup(w, ["spy", "doctor"])
        await next_step(w)
        await place(w, 1, "paris"); await place(w, 2, "berlin")
        await w.press(1, "p:bag"); await w.press(1, "p:ub:spy"); await w.press(1, "p:ubt:spy:berlin")
        b = w.g["balloons"][0]
        from zombiebot import actions as A
        A.rename(w.g, P(w, 1), "balloon", b["id"], "چشم آسمان")
        await next_step(w)      # lock → the spy's balloon is always public
        report = [t for t in w.texts_to(GROUP) if "گزارش بالن" in t]
        assert report and "چشم آسمان" in report[0] and "مریم" not in report[0] and "علی" in report[0]
        st = web.static_map()
        assert st["reports"] and st["reports"][0]["name"] == "چشم آسمان"
        from zombiebot import mapview
        assert any("چشم آسمان" in l for l in mapview.unit_lines(w.g, "fa"))
    run(go())


def test_bomb_is_used_up_and_blasts_where_the_night_was_spent():
    async def go():
        w = World(seed=67)
        await setup(w, ["bomber", "doctor", "spy", "zombie"])
        await next_step(w)
        for i, c in zip(range(1, 5), ["paris", "berlin", "berlin", "milan"]):
            await place(w, i, c)
        await w.press(1, "p:a:bomb"); await w.press(1, "p:t:bomb:2"); await w.press(1, "p:tb:2:3")
        await next_step(w); await next_step(w); await w.press(GM, "g:apply")
        assert P(w, 1)["charges"]["bomb"] == 0
        assert w.g["bombs"][0]["where"] == "berlin"
        await next_step(w)      # day: سارا (3) walks away from Berlin before the wire is cut
        await place_any(w, 3)
        import random as R
        R.seed(1)
        bomb_msg = next(m for m in reversed(w.sent) if m.chat_id == GROUP and any(b.startswith("x:bw:") for b in m.buttons()))
        await w.press(2, f"x:bw:{w.g['bombs'][0]['id']}:1", message=bomb_msg)
        assert not P(w, 2)["alive"]
        assert P(w, 4)["alive"]          # was in Milan that night
        # the next night the bomber has no bomb left
        await w.press(GM, "g:vclose"); await next_step(w)
        await w.press(1, "p:act")
        await w.press(1, "p:a:bomb"); ans = await w.press(1, "p:t:bomb:4"); ans += await w.press(1, "p:tb:4:1")
        assert not any(a["type"] == "bomb" for a in w.g["acts"].get("1", []))
    run(go())


async def place_any(w, i):
    await w.press(i, "p:move")
    m = w.last_to(i)
    b = next(x for x in m.buttons() if x.startswith("p:go:"))
    await w.press(i, b)


def test_guillotine_gif_renders():
    from zombiebot import guillotine
    data = guillotine.make_gif("مریم", 1)
    assert data[:3] == b"GIF" and len(data) > 20000
    assert guillotine.make_gif("Ali", 1, lightning=True)[:3] == b"GIF"
    from zombiebot import votes
    assert votes.make_gif.__module__.endswith("guillotine") or "GIF89a-test" in str(votes.make_gif(""))



def test_detailed_night_report_is_sent_with_the_results():
    async def go():
        w = World(seed=70)
        await setup(w, ["zombie", "doctor", "saboteur"])
        await next_step(w)
        for i, c in zip(range(1, 4), ["berlin", "milan", "moscow"]):
            await place(w, i, c)
        await w.press(1, "p:a:attack"); await w.press(1, "p:t:attack:2")
        await w.press(2, "p:a:protect"); await w.press(2, "p:t:protect:2")
        await w.press(3, "p:a:defuse"); await w.press(3, "p:t:defuse:1")
        await next_step(w); n = len(w.sent); await next_step(w)
        report = "\n".join(m.text for m in w.sent[n:] if m.chat_id == GM)
        assert "📋 گزارش کامل شب" in report and "🧯 خنثی" in report and "🛡 محافظت" in report
        assert "تاس" in report and "حمله ۱۴" in report and ("خنثی شد" in report or "ضعیف شد" in report)
        assert "سپر" in report
        assert "g:apply" in w.last_to(GM).buttons()
    run(go())


def test_yakuza_takes_someone_after_any_day_death():
    async def go():
        w = World(seed=71)
        await setup(w, ["yakuza", "musketeer", "doctor", "cultist"])
        await next_step(w)
        for i, c in zip(range(1, 5), ["berlin", "milan", "moscow", "warsaw"]):
            await place(w, i, c)
        P(w, 3)["bullets"] = ["war"]
        await to_day(w)
        await w.press(3, "p:shoot"); await w.press(3, "p:sh:1")      # war bullet kills the yakuza by day
        assert not P(w, 1)["alive"] and P(w, 1)["flags"].get("yakuza_pending")
        assert "x:yk:4" in w.last_to(1).buttons()                     # the cultist can be picked…
        await w.press(1, "x:yk:4")
        assert P(w, 4)["alive"]                                       # …and nothing happens
        assert any("اتفاقی نیفتاد" in t for t in w.texts_to(GROUP))
    run(go())


def test_never_two_special_acts_even_with_the_monastery():
    async def go():
        w = World(seed=72)
        await setup(w, ["apothecary", "doctor", "spy"])
        await next_step(w)
        await place(w, 1, "wagram"); await place(w, 2, "berlin"); await place(w, 3, "milan")
        await next_step(w)
        w.forced_dice = [6]
        await w.press(1, "p:wroll")
        await w.press(1, "p:a:poison"); await w.press(1, "p:t:poison:2")
        ans = await w.press(1, "p:t:poison:3")
        assert ans and "ویژه" in ans[-1] and len(w.g["acts"]["1"]) == 1
        await w.press(1, "p:a:spy"); await w.press(1, "p:t:spy:3")
        assert len(w.g["acts"]["1"]) == 2
    run(go())


def test_first_move_can_be_any_square():
    async def go():
        w = World(seed=73)
        await setup(w, ["doctor", "spy"])
        await next_step(w)
        await w.press(1, "p:move")
        assert "p:nodes" in w.last_to(1).buttons()
        await w.press(1, "p:nodes")
        assert "p:go:n21" in w.last_to(1).buttons()
        await w.press(1, "p:go:n21")
        assert P(w, 1)["pos"] == "n21"
    run(go())
