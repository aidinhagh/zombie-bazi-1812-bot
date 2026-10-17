"""Things that happen in front of everyone: deaths, bombs, poison, duels, bets, shots, executions, the judge.

Every decision here works with or without a button press (q=None), so a test player on autopilot can make it too.
"""
import random
import time

from telegram.error import TelegramError

from . import legendary, actions, board
from .actions import GameError
from .common import G, save, store, pl, dm, group, gm_notes, kb, chunks, acting_uid, name_of, num, logger
from .data.roles import role_name
from .data.legendary import LEGENDARY
from .state import alive_players, team

RPS = {"r": "✊ سنگ", "p": "✋ کاغذ", "s": "✌️ قیچی"}
BEATS = {"r": "s", "p": "r", "s": "p"}
JUDGE_HOURS = 2


async def say_to(q, text):
    """Replace the pressed message's text (when there was a press)."""
    if q is None:
        return
    try:
        await q.edit_message_text(text)
    except TelegramError:
        pass


async def announce_death(bot, P):
    fa, _ = actions.death_announcement(P)
    await group(bot, fa, None)
    await dm(bot, P["id"], "☠️ شما مُردید.")


async def check_win(bot):
    res = actions.winner_check(G())
    if res:
        await gm_notes(bot, [("🏆 بررسی برد:", "")] + res)


async def send_outbox(bot, out):
    for msg in out:
        kind = msg[0]
        if kind == "private":
            await dm(bot, msg[1], msg[2])
        elif kind == "team":
            for p in alive_players(G()):
                if team(p) == msg[1]:
                    await dm(bot, p["id"], msg[2])
        elif kind == "group":
            await group(bot, msg[1], None)
        elif kind == "death":
            await announce_death(bot, pl(msg[1]))
        elif kind == "bomb":
            await post_bomb(bot, msg[1])
        elif kind == "poison":
            await post_poison(bot, msg[1])
        elif kind == "duel":
            await start_duel(bot, msg[1])
    from . import autopilot
    await autopilot.decide_pending(bot)


# ---------------- bomb ----------------

async def post_bomb(bot, bo):
    T = pl(bo["target"])
    rows = [[(f"✂️ {num(w)}", f"x:bw:{bo['id']}:{w}") for w in range(1, 5)]]
    text = f"💣 بمب به {T['name']} رسید! {T['name']}، یکی از ۴ سیم را ببر:"
    gid = G()["group_id"]
    if gid:
        await group(bot, text, None, reply_markup=kb(rows))
    else:
        await dm(bot, T["id"], text, reply_markup=kb(rows))


async def cut_wire(bot, uid, bomb_id, wire, q=None):
    g = G()
    bo = next((b for b in g["bombs"] if b["id"] == bomb_id), None)
    if not bo or bo["status"] != "armed":
        return
    if str(uid) != str(bo["target"]):
        raise GameError("این بمب مال تو نیست!")
    T = pl(bo["target"])
    if wire == bo["wire"]:
        bo["status"] = "defused"
        save()
        text = f"✂️ {T['name']} سیم {num(wire)} را برید… بمب خنثی شد!"
        await (say_to(q, text) if q else group(bot, text, None))
        return
    bo["status"] = "exploded"
    # the blast hits where the bomb reached them: everyone who spent that night in the same place, 80% each
    where = bo.get("where") or T.get("last_night_pos") or T["pos"]
    victims = [T]
    near = [x for x in alive_players(g) if x is not T and x["role"] != "cultist"
            and (x.get("last_night_pos") or x["pos"]) == where]
    for x in near:
        if random.random() < 0.8:
            victims.append(x)
    saved = [v for v in victims if v["flags"].pop("bomb_safe", None)]   # wet blanket
    victims = [v for v in victims if v not in saved]
    for v in victims:
        actions.kill(g, v, "bomb")
    save()
    others = [v["name"] for v in victims if v is not T]
    text = f"💥 {T['name']} سیم {num(wire)} را برید… بوم!" + (f"\nموج انفجار {'، '.join(others)} را هم گرفت." if others else "")
    if saved:
        text += f"\n🧯 {'، '.join(v['name'] for v in saved)} با پتوی خیس جان سالم به در برد."
    await (say_to(q, text) if q else group(bot, text, None))
    for v in victims:
        await announce_death(bot, v)
        if g["phase"] == "day":
            await yakuza_last_act(bot, v)
    await check_win(bot)


# ---------------- poison ----------------

async def post_poison(bot, po):
    T = pl(po["target"])
    await group(bot, f"🧪 سم به {T['name']} رسید.", None)
    await dm(bot, po["by"], f"🧪 سم به {T['name']} رسید. در طول روز تصمیم بگیر: پادزهر بدهی یا نه؟ (از منو هم می‌شود)",
             reply_markup=kb(antidote_rows(po)))


def antidote_rows(po):
    return [[("✅ پادزهر بده", f"x:an:{po['id']}:1"), ("❌ نه", f"x:an:{po['id']}:0")]]


async def antidote(bot, uid, pid, yes, q=None):
    g = G()
    po = next((x for x in g["poisons"] if x["id"] == pid), None)
    if not po or str(po["by"]) != str(uid) or po["status"] != "pending":
        raise GameError("این تصمیم دیگر باز نیست.")
    po["antidote"] = yes
    po["status"] = "cured" if yes else "doomed"
    save()
    await say_to(q, "✅ تصمیم ثبت شد: " + ("پادزهر داده شد." if yes else "پادزهر داده نشد."))
    if yes:
        await group(bot, f"🧪 {name_of(po['target'])} پادزهر گرفت.", None)


async def resolve_poisons(bot):
    """At the start of the night: anyone still poisoned without an antidote dies."""
    g = G()
    for po in g["poisons"]:
        if po["status"] not in ("pending", "doomed"):
            continue
        T, A = pl(po["target"]), pl(po["by"])
        if A and not A["alive"]:
            po["status"] = "failed"
            continue
        if T and T["alive"] and T["flags"].pop("poison_safe", None):
            po["status"] = "cured"
            save()
            await group(bot, f"🧪 سم به {T['name']} رسیده بود، ولی تریاق نجاتش داد.", None)
            continue
        if T and T["alive"]:
            actions.kill(g, T, "poison")
            po["status"] = "killed"
            save()
            await group(bot, f"🧪 سم کار {T['name']} را ساخت.", None)
            await announce_death(bot, T)
            await yakuza_last_act(bot, T)
        else:
            po["status"] = "void"
    save()


# ---------------- rock-paper-scissors: judge duels and casino bets ----------------

def rps_rows(kind, gid):
    return [[(RPS[c], f"x:rp:{kind}:{gid}:{c}") for c in "rps"]]


async def ask_rps(bot, kind, game, round_no=None):
    title = f"⚖️ دوئل — راند {num(round_no)}: انتخاب کن" if round_no else "🎲 شرط کازینو — انتخاب کن:"
    for side in ("a", "b"):
        await dm(bot, game[side], title, reply_markup=kb(rps_rows(kind, game["id"])))


async def start_duel(bot, du):
    A, B = pl(du["a"]), pl(du["b"])
    await group(bot, f"⚖️ به حکم قاضی، امروز {A['name']} و {B['name']} دوئل می‌کنند (۳ راند، بازنده هر راند −۱۰ اچ‌پی).", None)
    du["status"] = "live"
    save()
    await ask_rps(bot, "d", du, 1)


async def create_bet(bot, p, T, stake):
    g = G()
    if not T or T["pos"] != "stockholm" or p["pos"] != "stockholm":
        raise GameError("هر دو باید در کازینو باشید.")
    if actions.ruined(g, "stockholm"):
        raise GameError("کازینو کاملاً ویران شده و بسته است.")
    if p["coins"] < stake:
        raise GameError("سکه کافی نداری.")
    b = {"id": actions.next_id(g, "s"), "a": str(p["id"]), "b": str(T["id"]), "stake": stake, "status": "offered", "picks": {}}
    g["bets"].append(b)
    save()
    await dm(bot, T["id"], f"🎲 {p['name']} در کازینو سر {num(stake)} سکه سنگ‌کاغذقیچی شرط بسته. قبول؟", reply_markup=kb(bet_rows(b)))
    from . import autopilot
    await autopilot.decide_pending(bot)


def bet_rows(b):
    return [[("✅ قبول", f"x:ba:{b['id']}:1"), ("❌ نه", f"x:ba:{b['id']}:0")]]


async def accept_bet(bot, uid, bid, yes, q=None):
    b = next((x for x in G()["bets"] if x["id"] == bid), None)
    if not b or b["b"] != str(uid) or b["status"] != "offered":
        raise GameError("این شرط دیگر باز نیست.")
    if not yes:
        b["status"] = "declined"
        save()
        await say_to(q, "رد شد.")
        await dm(bot, b["a"], "شرطت رد شد.")
        return
    b["stake"] = min(b["stake"], pl(b["a"])["coins"], pl(b["b"])["coins"])
    b["status"] = "live"
    save()
    await say_to(q, f"شرط {num(b['stake'])} سکه‌ای شروع شد.")
    await ask_rps(bot, "b", b)


async def rps_pick(bot, uid, kind, gid, choice, q=None):
    g = G()
    uid = str(uid)
    pool = g["duels"] if kind == "d" else g["bets"]
    game = next((x for x in pool if x["id"] == gid), None)
    if not game or game["status"] != "live" or uid not in (game["a"], game["b"]):
        raise GameError("این بازی دیگر باز نیست.")
    if uid in game["picks"]:
        raise GameError("قبلاً انتخاب کردی.")
    game["picks"][uid] = choice
    save()
    await say_to(q, f"انتخاب: {RPS[choice]} — منتظر حریف…")
    if len(game["picks"]) < 2:
        return
    ca, cb = game["picks"][game["a"]], game["picks"][game["b"]]
    game["picks"] = {}
    A, B = pl(game["a"]), pl(game["b"])
    if ca == cb:
        save()
        for x in (A, B):
            await dm(bot, x["id"], "مساوی؛ دوباره.")
        await ask_rps(bot, kind, game, len(game.get("rounds", [])) + 1 if kind == "d" else None)
        return
    win, lose = (A, B) if BEATS[ca] == cb else (B, A)
    if kind == "b":
        amt = min(game["stake"], lose["coins"])
        lose["coins"] -= amt
        payout = int(amt * actions.intact(g, "stockholm"))   # a damaged casino pays out less; the house keeps the rest
        win["coins"] += payout
        if payout != amt:
            amt = f"{payout} (از {amt}؛ کازینو {actions.damage(g, 'stockholm')}٪ ویران)"
        game["status"] = "done"
        save()
        for x in (A, B):
            await dm(bot, x["id"], f"🎲 {A['name']} {RPS[ca]} / {B['name']} {RPS[cb]} → برنده {win['name']} ({num(amt) if isinstance(amt, int) else amt} سکه)")
        return
    game.setdefault("rounds", []).append(lose["id"])
    lose["hp"] -= 10
    n = len(game["rounds"])
    await group(bot, f"⚖️ راند {num(n)}: {A['name']} {RPS[ca]} / {B['name']} {RPS[cb]} → {lose['name']} −۱۰ اچ‌پی", None)
    if lose["hp"] <= 0:
        actions.kill(g, lose, "duel")
        game["status"] = "done"
        save()
        await announce_death(bot, lose)
        await yakuza_last_act(bot, lose)
        await check_win(bot)
        return
    if n >= 3:
        game["status"] = "done"
        save()
        await group(bot, "⚖️ دوئل تمام شد.", None)
        return
    save()
    await ask_rps(bot, "d", game, n + 1)


# ---------------- shots ----------------

async def fire_bullet(bot, p, T):
    g = G()
    if g["phase"] != "day" or not p["bullets"] or not T or not T["alive"]:
        raise GameError("نمی‌شه شلیک کرد.")
    kind = p["bullets"].pop(0)
    save()
    if kind == "war" and T["flags"].pop("bullet_vest", None):
        save()
        await group(bot, f"💥 {p['name']} به {T['name']} شلیک کرد… تیر جنگی بود، ولی جلیقه ابریشمی نجاتش داد!", None)
    elif kind == "war":
        await group(bot, f"💥 {p['name']} به {T['name']} شلیک کرد… تیر جنگی بود!", None)
        actions.kill(g, T, "bullet")
        if T["role"] == "apothecary":   # a poison already handed out fails if the apothecary is shot by day
            for po in g["poisons"]:
                if str(po["by"]) == str(T["id"]) and po["status"] == "pending":
                    po["status"] = "failed"
        save()
        await announce_death(bot, T)
        await yakuza_last_act(bot, T)
        await check_win(bot)
    else:
        await group(bot, f"🔫 {p['name']} به {T['name']} شلیک کرد… مشقی بود.", None)


# ---------------- executions and the judge ----------------

async def execute(bot, P):
    """Returns an error text or None."""
    g = G()
    if not P or not P["alive"]:
        return "این بازیکن زنده نیست."
    if P["flags"].get("hotel_immune") and g["loc_damage"].get("barcelona", 0) == 0:
        await group(bot, f"🏨 {P['name']} در هتل است و اعدام نمی‌شود.", None)
        return f"{P['name']} در هتل است و اعدام نمی‌شود."
    if P["flags"].pop("pardon", None):
        save()
        await group(bot, f"📜 {P['name']} فرمان عفو امپراتور را نشان داد؛ اعدامش لغو شد.", None)
        return f"{P['name']} فرمان عفو داشت و اعدام نشد."
    actions.kill(g, P, "execution")
    save()
    await group(bot, f"⚖️ {P['name']} اعدام شد.", None)
    await announce_death(bot, P)
    if P["role"] == "clown" and not P.get("cult_lost_clown"):
        await group(bot, "🤡 دلقک اعدام شد و بازی را برد!", None)
    await yakuza_last_act(bot, P)
    await check_win(bot)
    return None


def yakuza_rows():
    targets = alive_players(G())
    return [[(x["name"][:28], f"x:yk:{x['id']}")] for x in targets]


async def yakuza_last_act(bot, P):
    """A yakuza who dies during the day (war bullet, poison, execution, duel, bomb) takes one player with them.
    Choosing the cultist does nothing."""
    if not P or P["role"] != "yakuza" or P["flags"].get("yakuza_done"):
        return
    P["flags"]["yakuza_pending"] = True
    save()
    await group(bot, f"🗡 یاکوزا افتاد… ولی پیش از مرگ یک نفر را نشانه می‌گیرد.", None)
    await dm(bot, P["id"], "🗡 پیش از مرگ، یک نفر را با خودت ببر:", reply_markup=kb(yakuza_rows()))
    from . import autopilot
    await autopilot.decide_pending(bot)


async def yakuza_take(bot, uid, target_id, q=None):
    g = G()
    Y = pl(uid)
    if not Y or Y["role"] != "yakuza" or not Y["flags"].get("yakuza_pending"):
        raise GameError("این تصمیم دیگر باز نیست.")
    T = pl(target_id)
    if not T or not T["alive"]:
        raise GameError("این نفر زنده نیست.")
    Y["flags"].pop("yakuza_pending", None)
    Y["flags"]["yakuza_done"] = True
    if T["role"] == "cultist" and not T.get("cult_lost_clown"):
        save()
        await say_to(q, f"{T['name']} را نشانه گرفتی… ولی چیزی نشد.")
        await group(bot, f"🗡 یاکوزا {T['name']} را نشانه گرفت… ولی اتفاقی نیفتاد.", None)
        return
    actions.kill(g, T, "yakuza")
    save()
    await say_to(q, f"{T['name']} را با خودت بردی.")
    await group(bot, f"🗡 یاکوزا {T['name']} را با خود برد.", None)
    await announce_death(bot, T)
    await check_win(bot)


def final_results_text():
    """The real result, with every vote weight and rule applied — shown only when voting closes."""
    g = G()
    ranked, _notes = actions.tally(g)
    lines = [f"🗳 نتیجه نهایی رأی‌گیری روز {num(g['cycle'])}", ""]
    if not ranked:
        lines.append("هیچ رأیی ثبت نشد.")
    for i, (pid, v) in enumerate(ranked[:10]):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{num(i + 1)}."
        lines.append(f"{medal} {pl(pid)['name']} — {num(round(v, 2))} رأی")
    return "\n".join(lines)


def gallows():
    """Who the vote puts on the gallows: everyone tied for the most votes."""
    ranked, _ = actions.tally(G())
    ranked = [(pid, v) for pid, v in ranked if v > 0]
    if not ranked:
        return []
    top = ranked[0][1]
    return [pid for pid, v in ranked if v == top]


def judge_for(cands):
    """The living judge — unless the judge is on the gallows, in which case they have no say."""
    j = next((p for p in alive_players(G()) if p["role"] == "judge"), None)
    if j and str(j["id"]) not in cands:
        return j
    return None


def nullify_left(J):
    return J["charges"].get("nullify", J["charges"].get("cancel_vote", 0))


def judge_text(jd):
    names = "، ".join(pl(c)["name"] for c in jd["cands"])
    left = max(0, int((jd["deadline"] - time.time()) // 60))
    if len(jd["cands"]) == 1:
        return (f"⚖️ قاضی، رأی‌گیری تمام شد: {names} باید اعدام شود.\n"
                f"می‌توانی اعدام را تأیید کنی یا لغو (لغو فقط یک‌بار در کل بازی).\n⏳ {num(left // 60)} ساعت و {num(left % 60)} دقیقه وقت داری.")
    sel = "، ".join(pl(c)["name"] for c in jd.get("sel", [])) or "هیچ‌کس"
    return (f"⚖️ قاضی، رأی‌ها مساوی شد: {names}\n"
            f"تو تصمیم می‌گیری چه کسی اعدام شود: یک نفر، چند نفر، همه یا هیچ‌کس.\n"
            f"انتخاب فعلی: {sel}\n⏳ {num(left // 60)} ساعت و {num(left % 60)} دقیقه وقت داری.")


def judge_rows(jd):
    J = pl(jd["judge"])
    if len(jd["cands"]) == 1:
        rows = [[("☠️ اعدام اجرا شود", "x:jd:ok")]]
        if nullify_left(J):
            rows.append([("🚫 لغو اعدام (یک‌بار در بازی)", "x:jd:null")])
        return rows
    sel = jd.get("sel", [])
    rows = [[(("✅ " if c in sel else "⬜ ") + pl(c)["name"], f"x:jt:{c}")] for c in jd["cands"]]
    rows.append([(f"☠️ اعدام انتخاب‌شده‌ها ({num(len(sel))})", "x:jd:sel")])
    rows.append([("همه اعدام شوند", "x:jd:all"), ("هیچ‌کس اعدام نشود", "x:jd:none")])
    return rows


async def close_vote(bot, job_queue=None):
    """GM closes the day's vote: reveal the real result, then the judge decides — or, with no judge,
    one top name is executed and a tie executes everyone tied."""
    g = G()
    store.backup()
    await group(bot, final_results_text(), None, bypass=True)
    cands = gallows()
    if not cands:
        await group(bot, "🕊 امروز کسی اعدام نمی‌شود.", None, bypass=True)
        return await close_day(bot)
    J = judge_for(cands)
    if not J:
        return await carry_out(bot, cands, "")
    g["judgement"] = {"cycle": g["cycle"], "cands": cands, "judge": str(J["id"]), "sel": [],
                      "deadline": time.time() + JUDGE_HOURS * 3600, "status": "waiting"}
    save()
    names = "، ".join(pl(c)["name"] for c in cands)
    await group(bot, f"⚖️ پرونده {names} به قاضی سپرده شد. قاضی {num(JUDGE_HOURS)} ساعت وقت دارد.", None, bypass=True)
    await dm(bot, J["id"], judge_text(g["judgement"]), reply_markup=kb(judge_rows(g["judgement"])))
    if job_queue is not None:
        job_queue.run_once(job_judge_timeout, JUDGE_HOURS * 3600, data=g["cycle"])
    from . import autopilot
    await autopilot.decide_pending(bot)


async def judge_press(bot, uid, what, q=None):
    g = G()
    jd = g.get("judgement")
    if not jd or jd["status"] != "waiting" or str(uid) != jd["judge"]:
        raise GameError("تصمیمی منتظر تو نیست.")
    J = pl(uid)
    if what.startswith("t:"):
        c = what[2:]
        sel = jd.setdefault("sel", [])
        sel.remove(c) if c in sel else sel.append(c)
        save()
        if q:
            await q.edit_message_text(judge_text(jd), reply_markup=kb(judge_rows(jd)))
        return
    cands = jd["cands"]
    if what == "ok":
        chosen, note = cands, "قاضی اعدام را تأیید کرد."
    elif what == "null":
        if len(cands) != 1 or not nullify_left(J):
            raise GameError("لغو اعدام دیگر در دسترس نیست.")
        J["charges"]["nullify"] = 0
        J["charges"].pop("cancel_vote", None)
        chosen, note = [], "⚖️ قاضی اعدام امروز را لغو کرد."
    elif what == "all":
        chosen, note = cands, "قاضی حکم داد همه اعدام شوند."
    elif what == "none":
        chosen, note = [], "⚖️ قاضی حکم داد هیچ‌کس اعدام نشود."
    else:
        chosen = [c for c in cands if c in jd.get("sel", [])]
        note = "قاضی تصمیمش را گرفت." if chosen else "⚖️ قاضی حکم داد هیچ‌کس اعدام نشود."
    jd["status"] = "done"
    save()
    await say_to(q, "⚖️ حکم ثبت شد.")
    await carry_out(bot, chosen, note)


async def carry_out(bot, chosen, note):
    if note:
        await group(bot, note, None, bypass=True)
    if not chosen:
        if not note:
            await group(bot, "🕊 امروز کسی اعدام نشد.", None, bypass=True)
    for c in chosen:
        await execute(bot, pl(c))
    await close_day(bot)


async def close_day(bot):
    g = G()
    g["closed_cycle"] = g["cycle"]
    save()
    await gm_notes(bot, [("✅ رأی‌گیری امروز تمام شد. قدم بعدی: شروع شب.", "")])


async def job_judge_timeout(ctx):
    g = G()
    jd = g.get("judgement")
    if not jd or jd["status"] != "waiting" or jd["cycle"] != ctx.job.data or g["phase"] != "day":
        return
    await judge_default(ctx.bot, "⏳ وقت قاضی تمام شد و حکم پیش‌فرض اجرا می‌شود.")


async def judge_default(bot, note):
    """No decision: a single name is executed; a tie executes everyone tied."""
    jd = G()["judgement"]
    jd["status"] = "done"
    save()
    await carry_out(bot, jd["cands"], note)


# ---------------- spy balloons ----------------

async def publish_balloon(bot, b):
    names = "، ".join(b["result"]) if b["result"] else "هیچ‌کس"
    text = f"🎈 گزارش بالن جاسوسی «{b.get('name') or '?'}» بر فراز {board.square_name(b['target'])}: {names}"
    target = G()["channel_id"] or G()["group_id"]
    if target:
        from . import outbox
        await outbox.post(bot, "text", text, chat=target)


async def balloon_publish_choice(bot, uid, bid, yes, q=None):
    b = next((x for x in G()["balloons"] if x["id"] == bid and str(x["owner"]) == str(uid)), None)
    if not b or b["publish"] is not None:
        raise GameError("این تصمیم دیگر باز نیست.")
    b["publish"] = yes
    save()
    if yes:
        b["published"] = True
        save()
        await publish_balloon(bot, b)
    await say_to(q, "✅ ثبت شد.")


def balloon_rows(b):
    return [[("📢 انتشار", f"x:pub:{b['id']}:1"), ("🤫 نگه دار", f"x:pub:{b['id']}:0")]]


# ---------------- what is waiting for a player ----------------

def pending_for(p):
    """Decisions waiting for this player: [(label, rows)] — shown on their home screen so nothing gets lost."""
    g = G()
    pid = str(p["id"])
    out = []
    if g["phase"] == "day":
        for po in g["poisons"]:
            if str(po["by"]) == pid and po["status"] == "pending":
                out.append((f"🧪 پادزهر برای {name_of(po['target'])}؟", antidote_rows(po)))
    for d in g["duels"]:
        if d["status"] == "live" and pid in (d["a"], d["b"]) and pid not in d["picks"]:
            out.append(("⚖️ حرکت دوئل", rps_rows("d", d["id"])))
    for b in g["bets"]:
        if b["status"] == "offered" and b["b"] == pid:
            out.append((f"🎲 شرط {name_of(b['a'])} ({num(b['stake'])} سکه)", bet_rows(b)))
        elif b["status"] == "live" and pid in (b["a"], b["b"]) and pid not in b["picks"]:
            out.append(("🎲 حرکت شرط", rps_rows("b", b["id"])))
    if p["flags"].get("yakuza_pending"):
        out.append(("🗡 چه کسی را با خودت می‌بری؟", yakuza_rows()))
    au = legendary.state(g)["auction"]
    if au and pid in legendary.active_bidders(g, au):
        out.append((legend_bid_text(g, au, p), legend_bid_rows(g, au, p)))
    jd = g.get("judgement")
    if jd and jd["status"] == "waiting" and jd["judge"] == pid:
        out.append((judge_text(jd), judge_rows(jd)))
    for b in g["balloons"]:
        if str(b["owner"]) == pid and b.get("delivered") and b["publish"] is None:
            out.append((f"🎈 گزارش بالن بر فراز {board.square_name(b['target'])} منتشر شود؟", balloon_rows(b)))
    for bo in g["bombs"]:
        if bo["status"] == "armed" and str(bo["target"]) == pid:
            out.append(("💣 یک سیم را ببر:", [[(f"✂️ {num(w)}", f"x:bw:{bo['id']}:{w}") for w in range(1, 5)]]))
    return out


# ---------------- x:* buttons ----------------

async def shared_button(update, ctx, data):
    """Pressed in the group or by the person they're addressed to (or the GM playing as them)."""
    q = update.callback_query
    uid = acting_uid(q.from_user.id)
    parts = data.split(":")[1:]
    head = parts[0]
    bot = ctx.bot
    if head == "bw":
        await cut_wire(bot, uid, parts[1], int(parts[2]), q)
    elif head == "an":
        await antidote(bot, uid, parts[1], parts[2] == "1", q)
    elif head == "ba":
        await accept_bet(bot, uid, parts[1], parts[2] == "1", q)
    elif head == "rp":
        await rps_pick(bot, uid, parts[1], parts[2], parts[3], q)
    elif head == "yk":
        await yakuza_take(bot, uid, parts[1], q)
    elif head == "pub":
        await balloon_publish_choice(bot, uid, parts[1], parts[2] == "1", q)
    elif head == "jt":
        await judge_press(bot, uid, "t:" + parts[1], q)
    elif head == "jd":
        await judge_press(bot, uid, parts[1], q)
    elif head == "lb":
        await legend_bid(bot, uid, int(parts[1]), q)
    elif head == "lp":
        await legend_pass(bot, uid, q)
    from . import autopilot
    await autopilot.decide_pending(bot)


# ---------------- legendary items (everything secret: only the GM and the people involved are told) ----------------

def legend_bid_text(g, au, p):
    it = LEGENDARY[au["key"]]
    lead = "\n✅ الان بالاترین پیشنهاد مال توست." if au["leader"] == str(p["id"]) else ""
    high = f"{num(au['high'])} سکه" if au["leader"] else "هنوز پیشنهادی نیست"
    return (f"🌟 مزایده مخفی آیتم لجندری «{it['fa']}» ({it['desc_fa']}).\n"
            f"کسی نمی‌فهمد چه کسانی در مزایده‌اند یا چه کسی پیشنهاد داده؛ فقط بالاترین پیشنهاد را می‌بینی.\n"
            f"⏰ مزایده ساعت ۰۰:۰۰ بسته می‌شود؛ بالاترین پیشنهاد در آن لحظه برنده است.\n"
            f"📈 بالاترین پیشنهاد: {high}{lead}\n💰 سکه‌های تو: {num(p['coins'])}")


def legend_bid_rows(g, au, p):
    if au["leader"] == str(p["id"]):
        return [[("🔄 تازه کن", "p:pend")]]
    rows = chunks([(f"⬆️ {num(b)} سکه", f"x:lb:{b}") for b in legendary.bid_options(p, au)], 3)
    return rows + [[("🙅 کنار می‌کشم", "x:lp:0")]]


async def legend_tell_bidders(bot, g, au, skip=None):
    for b in legendary.active_bidders(g, au):
        if b != skip:
            P = pl(b)
            await dm(bot, P["id"], legend_bid_text(g, au, P), reply_markup=kb(legend_bid_rows(g, au, P)))


async def legend_after_lock(bot):
    """At the lock: hand the legendary item to the one person standing on it, or open the secret auction."""
    g = G()
    kind, info = legendary.at_lock(g)
    save()
    if kind == "taken":
        it = LEGENDARY[info["legend"][-1]]
        await dm(bot, info["id"], f"🌟 آیتم لجندری «{it['fa']}» را پیدا کردی! {it['desc_fa']}\n(به کسی اعلام نمی‌شود.)")
        await gm_notes(bot, [(f"🌟 {info['name']} آیتم لجندری «{it['fa']}» را برداشت.", "")])
    elif kind == "auction":
        au = legendary.state(g)["auction"]
        await legend_tell_bidders(bot, g, au)
        await gm_notes(bot, [(f"🌟 مزایده مخفی لجندری «{LEGENDARY[au['key']]['fa']}» بین {'، '.join(p['name'] for p in info)}. "
                              "ساعت ۰۰:۰۰ (یا وقتی همه جز نفر اول کنار بکشند) تمام می‌شود؛ یا خودت ببند: /legend close", "")])


async def legend_bid(bot, uid, amount, q=None):
    g = G()
    p = pl(uid)
    done = legendary.place_bid(g, p, amount)
    save()
    au = legendary.state(g)["auction"]
    await gm_notes(bot, [(f"🌟 مزایده: {p['name']} {num(amount)} سکه پیشنهاد داد.", "")])
    if q:
        await say_to(q, legend_bid_text(g, au, p))
    if done:
        await legend_close(bot)
    else:
        await legend_tell_bidders(bot, g, au, skip=str(p["id"]))


async def legend_pass(bot, uid, q=None):
    g = G()
    p = pl(uid)
    done = legendary.pass_bid(g, p)
    save()
    au = legendary.state(g)["auction"]
    await gm_notes(bot, [(f"🌟 مزایده: {p['name']} کنار کشید.", "")])
    if q:
        await say_to(q, "🙅 از مزایده کنار کشیدی.")
    if done:
        await legend_close(bot)


async def legend_close(bot):
    g = G()
    au = legendary.state(g)["auction"]
    if not au:
        return False
    it = LEGENDARY[au["key"]]
    bidders = list(au["bidders"])
    win, best = legendary.close_auction(g)
    save()
    if not win:
        for b in bidders:
            await dm(bot, pl(b)["id"], f"🌟 مزایده «{it['fa']}» بدون برنده تمام شد.")
        await gm_notes(bot, [("🌟 مزایده بدون پیشنهاد ماند؛ آیتم سر جایش می‌ماند.", "")])
        return True
    await dm(bot, win["id"], f"🌟 مزایده را با {num(best)} سکه بردی! «{it['fa']}» مال تو شد. {it['desc_fa']}")
    for b in bidders:
        if b != str(win["id"]):
            await dm(bot, pl(b)["id"], f"🌟 مزایده «{it['fa']}» تمام شد و تو نبردی.")
    await gm_notes(bot, [(f"🌟 {win['name']} «{it['fa']}» را با {num(best)} سکه برد.", "")])
    return True
