"""Things that happen in front of everyone: deaths, bombs, poison, duels, bets, shots, executions."""
import random

from . import actions, board
from .actions import GameError
from .common import (G, save, pl, dm, group, gm_notes, kb, lang_of, acting_uid, name_of)
from .data.roles import role_name
from .state import alive_players, team
from .texts import L, bi

RPS = {"r": ("✊ سنگ", "✊ Rock"), "p": ("✋ کاغذ", "✋ Paper"), "s": ("✌️ قیچی", "✌️ Scissors")}
BEATS = {"r": "s", "p": "r", "s": "p"}


async def announce_death(bot, P):
    fa, en = actions.death_announcement(P)
    await group(bot, fa, en)
    await dm(bot, P["id"], "☠️ شما مُردید.", "☠️ You have died.")


async def check_win(bot):
    res = actions.winner_check(G())
    if res:
        await gm_notes(bot, [("🏆 بررسی برد:", "🏆 Win check:")] + res)


async def send_outbox(bot, out):
    for msg in out:
        kind = msg[0]
        if kind == "private":
            await dm(bot, msg[1], msg[2], msg[3])
        elif kind == "team":
            for p in alive_players(G()):
                if team(p) == msg[1]:
                    await dm(bot, p["id"], msg[2], msg[3])
        elif kind == "group":
            await group(bot, msg[1], msg[2])
        elif kind == "death":
            await announce_death(bot, pl(msg[1]))
        elif kind == "bomb":
            await post_bomb(bot, msg[1])
        elif kind == "poison":
            await post_poison(bot, msg[1])
        elif kind == "duel":
            await start_duel(bot, msg[1])


# ---------------- bomb ----------------

async def post_bomb(bot, bo):
    T = pl(bo["target"])
    rows = [[(f"✂️ {w}", f"x:bw:{bo['id']}:{w}") for w in range(1, 5)]]
    text = bi(f"💣 بمب به {T['name']} رسید! {T['name']}، یکی از ۴ سیم را ببر:",
              f"💣 A bomb has reached {T['name']}! {T['name']}, cut one of the 4 wires:")
    gid = G()["group_id"]
    if gid:
        await bot.send_message(gid, text, reply_markup=kb(rows))
    else:
        await dm(bot, T["id"], text, text, reply_markup=kb(rows))


async def cut_wire(bot, q, uid, bomb_id, wire):
    g = G()
    bo = next((b for b in g["bombs"] if b["id"] == bomb_id), None)
    if not bo or bo["status"] != "armed":
        return
    lang = lang_of(uid)
    if str(uid) != str(bo["target"]):
        await q.answer(L(lang, "این بمب مال تو نیست!", "This isn't your bomb!"), show_alert=True)
        return
    T = pl(bo["target"])
    if wire == bo["wire"]:
        bo["status"] = "defused"
        B = pl(bo["by"])
        if B:
            B["charges"]["bomb"] = 0
        save()
        await q.edit_message_text(bi(f"✂️ {T['name']} سیم {wire} را برید… بمب خنثی شد!", f"✂️ {T['name']} cut wire {wire}… the bomb is defused!"))
        return
    bo["status"] = "exploded"
    victims = [T]
    for x in alive_players(g):
        if x is T or x["role"] == "cultist" or x["pos"] != T["pos"]:
            continue
        if random.random() < 0.8:
            victims.append(x)
    for v in victims:
        actions.kill(g, v, "bomb")
    save()
    await q.edit_message_text(bi(f"💥 {T['name']} سیم {wire} را برید… بوم!", f"💥 {T['name']} cut wire {wire}… BOOM!"))
    for v in victims:
        await announce_death(bot, v)
    await check_win(bot)


# ---------------- poison ----------------

async def post_poison(bot, po):
    T = pl(po["target"])
    await group(bot, f"🧪 سم به {T['name']} رسید.", f"🧪 Poison has reached {T['name']}.")
    lang = lang_of(po["by"])
    await dm(bot, po["by"], f"تا شروع شب بعد وقت داری: به {T['name']} پادزهر بدی؟",
             f"Until next night begins: give {T['name']} the antidote?",
             reply_markup=kb([[(L(lang, "✅ پادزهر", "✅ Antidote"), f"x:an:{po['id']}:1"),
                               (L(lang, "❌ نه", "❌ No"), f"x:an:{po['id']}:0")]]))


async def antidote(bot, q, uid, pid, yes):
    po = next((x for x in G()["poisons"] if x["id"] == pid), None)
    if not po or str(po["by"]) != str(uid) or po["status"] != "pending":
        return
    po["antidote"] = yes
    po["status"] = "cured" if yes else "doomed"
    save()
    await q.edit_message_text(L(lang_of(uid), "تصمیم ثبت شد.", "Decision recorded."))
    if yes:
        await group(bot, f"🧪 {name_of(po['target'])} پادزهر گرفت.", f"🧪 {name_of(po['target'])} received the antidote.")


async def resolve_poisons(bot):
    g = G()
    for po in g["poisons"]:
        if po["status"] not in ("pending", "doomed"):
            continue
        T, A = pl(po["target"]), pl(po["by"])
        if A and not A["alive"]:
            po["status"] = "failed"
            continue
        if T and T["alive"]:
            actions.kill(g, T, "poison")
            po["status"] = "killed"
            save()
            await group(bot, f"🧪 سم کار {T['name']} را ساخت.", f"🧪 The poison claims {T['name']}.")
            await announce_death(bot, T)
        else:
            po["status"] = "void"
    save()


# ---------------- rock-paper-scissors: judge duels and casino bets ----------------

def rps_rows(kind, gid, lang):
    return [[(L(lang, *RPS[c]), f"x:rp:{kind}:{gid}:{c}") for c in "rps"]]


async def ask_rps(bot, kind, game, round_no=None):
    for side in ("a", "b"):
        uid = game[side]
        lang = lang_of(uid)
        title = L(lang, f"راند {round_no}: انتخاب کن", f"Round {round_no}: choose") if round_no else L(lang, "انتخاب کن:", "Choose:")
        await dm(bot, uid, title, title, reply_markup=kb(rps_rows(kind, game["id"], lang)))


async def start_duel(bot, du):
    A, B = pl(du["a"]), pl(du["b"])
    await group(bot, f"⚖️ به حکم قاضی، امروز {A['name']} و {B['name']} دوئل می‌کنند (۳ راند، بازنده هر راند −۱۰ اچ‌پی).",
                f"⚖️ By the judge's order, {A['name']} and {B['name']} duel today (3 rounds, each round's loser −10 HP).")
    du["status"] = "live"
    save()
    await ask_rps(bot, "d", du, 1)


async def create_bet(bot, p, T, stake):
    g = G()
    if not T or T["pos"] != "stockholm" or p["pos"] != "stockholm":
        raise GameError("هر دو باید در کازینو باشید.", "Both of you must be in the casino.")
    if p["coins"] < stake:
        raise GameError("سکه کافی نداری.", "Not enough coins.")
    b = {"id": actions.next_id(g, "s"), "a": str(p["id"]), "b": str(T["id"]), "stake": stake, "status": "offered", "picks": {}}
    g["bets"].append(b)
    save()
    lang = lang_of(T["id"])
    await dm(bot, T["id"], f"🎲 {p['name']} تو کازینو {stake} سکه سر سنگ‌کاغذقیچی شرط بسته. قبول؟",
             f"🎲 {p['name']} bets {stake} coins on rock-paper-scissors. Accept?",
             reply_markup=kb([[(L(lang, "✅ قبول", "✅ Accept"), f"x:ba:{b['id']}:1"), (L(lang, "❌ نه", "❌ No"), f"x:ba:{b['id']}:0")]]))


async def accept_bet(bot, q, uid, bid, yes):
    b = next((x for x in G()["bets"] if x["id"] == bid), None)
    lang = lang_of(uid)
    if not b or b["b"] != str(uid) or b["status"] != "offered":
        return
    if not yes:
        b["status"] = "declined"
        save()
        await q.edit_message_text(L(lang, "رد شد.", "Declined."))
        await dm(bot, b["a"], "شرط رد شد.", "Your bet was declined.")
        return
    b["stake"] = min(b["stake"], pl(b["a"])["coins"], pl(b["b"])["coins"])
    b["status"] = "live"
    save()
    await q.edit_message_text(L(lang, f"شرط {b['stake']} سکه‌ای شروع شد.", f"{b['stake']}-coin bet on."))
    await ask_rps(bot, "b", b)


async def rps_pick(bot, q, uid, kind, gid, choice):
    g = G()
    uid = str(uid)
    lang = lang_of(uid)
    pool = g["duels"] if kind == "d" else g["bets"]
    game = next((x for x in pool if x["id"] == gid), None)
    if not game or game["status"] != "live" or uid not in (game["a"], game["b"]):
        return
    if uid in game["picks"]:
        await q.answer(L(lang, "قبلاً انتخاب کردی.", "Already chosen."), show_alert=True)
        return
    game["picks"][uid] = choice
    save()
    await q.edit_message_text(L(lang, f"انتخاب: {L(lang, *RPS[choice])} — منتظر حریف…", f"Chosen: {L(lang, *RPS[choice])} — waiting for opponent…"))
    if len(game["picks"]) < 2:
        return
    ca, cb = game["picks"][game["a"]], game["picks"][game["b"]]
    game["picks"] = {}
    A, B = pl(game["a"]), pl(game["b"])
    if ca == cb:
        save()
        for x in (A, B):
            await dm(bot, x["id"], "مساوی؛ دوباره.", "Draw; again.")
        await ask_rps(bot, kind, game, len(game.get("rounds", [])) + 1 if kind == "d" else None)
        return
    win, lose = (A, B) if BEATS[ca] == cb else (B, A)
    if kind == "b":
        amt = min(game["stake"], lose["coins"])
        lose["coins"] -= amt
        win["coins"] += amt
        game["status"] = "done"
        save()
        for x in (A, B):
            await dm(bot, x["id"], f"🎲 {A['name']} {RPS[ca][0]} / {B['name']} {RPS[cb][0]} → برنده {win['name']} ({amt} سکه)",
                     f"🎲 {A['name']} {RPS[ca][1]} / {B['name']} {RPS[cb][1]} → {win['name']} wins {amt} coins")
        return
    game.setdefault("rounds", []).append(lose["id"])
    lose["hp"] -= 10
    n = len(game["rounds"])
    await group(bot, f"⚖️ راند {n}: {A['name']} {RPS[ca][0]} / {B['name']} {RPS[cb][0]} → {lose['name']} −۱۰ اچ‌پی",
                f"⚖️ Round {n}: {A['name']} {RPS[ca][1]} / {B['name']} {RPS[cb][1]} → {lose['name']} −10 HP")
    if lose["hp"] <= 0:
        actions.kill(g, lose, "duel")
        game["status"] = "done"
        save()
        await announce_death(bot, lose)
        await check_win(bot)
        return
    if n >= 3:
        game["status"] = "done"
        save()
        await group(bot, "⚖️ دوئل تمام شد.", "⚖️ The duel is over.")
        return
    save()
    await ask_rps(bot, "d", game, n + 1)


# ---------------- shots, executions, yakuza ----------------

async def fire_bullet(bot, p, T):
    g = G()
    if g["phase"] != "day" or not p["bullets"] or not T or not T["alive"]:
        raise GameError("نمی‌شه شلیک کرد.", "Can't fire.")
    kind = p["bullets"].pop(0)
    save()
    if kind == "war":
        await group(bot, f"💥 {p['name']} به {T['name']} شلیک کرد… تیر جنگی بود!", f"💥 {p['name']} shot {T['name']}… it was a live round!")
        actions.kill(g, T, "bullet")
        if T["role"] == "apothecary":   # a poison already handed out fails if the apothecary is shot by day
            for po in g["poisons"]:
                if str(po["by"]) == str(T["id"]) and po["status"] == "pending":
                    po["status"] = "failed"
        save()
        await announce_death(bot, T)
        await check_win(bot)
    else:
        await group(bot, f"🔫 {p['name']} به {T['name']} شلیک کرد… مشقی بود.", f"🔫 {p['name']} shot {T['name']}… just a blank.")


async def execute(bot, P):
    """Returns an error text (fa, en) or None."""
    g = G()
    if not P or not P["alive"]:
        return ("این بازیکن زنده نیست.", "That player isn't alive.")
    if P["flags"].get("hotel_immune") and g["loc_damage"].get("barcelona", 0) < 100:
        return (f"{P['name']} در هتل است و اعدام نمی‌شود.", f"{P['name']} is in the hotel and can't be executed.")
    store_backup()
    actions.kill(g, P, "execution")
    g["executed_cycle"] = g["cycle"]
    save()
    await group(bot, f"⚖️ {P['name']} اعدام شد.", f"⚖️ {P['name']} has been executed.")
    await announce_death(bot, P)
    if P["role"] == "clown" and not P.get("cult_lost_clown"):
        await group(bot, "🤡 دلقک اعدام شد و بازی را برد!", "🤡 The clown was executed and wins!")
    if P["role"] == "yakuza":
        P["flags"]["yakuza_pending"] = True
        save()
        lang = lang_of(P["id"])
        targets = [x for x in alive_players(g) if x["role"] != "cultist"]
        rows = [[(x["name"][:28], f"x:yk:{x['id']}")] for x in targets]
        await dm(bot, P["id"], "🗡 یک نفر را با خودت ببر:", "🗡 Take someone down with you:", reply_markup=kb(rows))
    await check_win(bot)
    return None


async def yakuza_take(bot, q, uid, target_id):
    g = G()
    Y = pl(uid)
    if not Y or Y["role"] != "yakuza" or not Y["flags"].get("yakuza_pending"):
        return
    T = pl(target_id)
    Y["flags"].pop("yakuza_pending", None)
    if T and T["alive"] and T["role"] != "cultist":
        actions.kill(g, T, "yakuza")
        save()
        await q.edit_message_text(L(lang_of(uid), f"{T['name']} را با خودت بردی.", f"You took {T['name']} with you."))
        await group(bot, f"🗡 یاکوزا {T['name']} را با خود برد.", f"🗡 The Yakuza took {T['name']} down with them.")
        await announce_death(bot, T)
        await check_win(bot)
    else:
        save()


def store_backup():
    from .common import store
    store.backup()


async def publish_balloon(bot, b):
    O = pl(b["owner"])
    names = "، ".join(b["result"]) if b["result"] else "هیچ‌کس"
    names_en = ", ".join(b["result"]) if b["result"] else "nobody"
    fa = f"🎈 گزارش بالن جاسوسی {O['name']} بر فراز {board.square_name(b['target'])}: {names}"
    en = f"🎈 {O['name']}'s spy balloon over {board.square_name(b['target'], 'en')}: {names_en}"
    target = G()["channel_id"] or G()["group_id"]
    if target:
        await bot.send_message(target, bi(fa, en))


async def balloon_publish_choice(bot, q, uid, bid, yes):
    b = next((x for x in G()["balloons"] if x["id"] == bid and str(x["owner"]) == str(uid)), None)
    if b and b["publish"] is None:
        b["publish"] = yes
        save()
        if yes:
            b["published"] = True
            save()
            await publish_balloon(bot, b)
    await q.edit_message_text(L(lang_of(uid), "ثبت شد.", "Done."))


async def shared_button(update, ctx, data):
    """x:* buttons — pressed in the group or by the person they're addressed to."""
    q = update.callback_query
    uid = acting_uid(q.from_user.id)
    parts = data.split(":")[1:]
    head = parts[0]
    bot = ctx.bot
    if head == "bw":
        await cut_wire(bot, q, uid, parts[1], int(parts[2]))
    elif head == "an":
        await antidote(bot, q, uid, parts[1], parts[2] == "1")
    elif head == "ba":
        await accept_bet(bot, q, uid, parts[1], parts[2] == "1")
    elif head == "rp":
        await rps_pick(bot, q, uid, parts[1], parts[2], parts[3])
    elif head == "yk":
        await yakuza_take(bot, q, uid, parts[1])
    elif head == "pub":
        await balloon_publish_choice(bot, q, uid, parts[1], parts[2] == "1")
