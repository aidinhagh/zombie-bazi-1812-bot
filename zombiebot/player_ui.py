"""The player's private menu: one home screen with a checklist, and sub-screens that always lead back."""
from . import actions, board, events, mapview, votes
from .actions import GameError
from .board import CITIES
from .common import (G, save, pl, kb, chunks, dm, lang_of, num, phase_label, lock_eta, edit_or_send,
                     acting_uid, banner, gm_notes, to_gms, DICE_WAIT, LOCK_HOUR)
from .data.items import ITEMS
from .data.locations import LOCATIONS, POWER_PRICES, UNIT_PRICES
from .data.roles import ROLES, SPECIALS, HUMAN, role_name
from .engine import loc_of, flags_at
from .state import roster
from .texts import L, act_name, stat_name, unit_name, item_line, role_card


# ---------------- home ----------------

def checklist(g, p, lang):
    if g["phase"] == "lobby":
        return L(lang, "⏳ بازی هنوز شروع نشده.", "⏳ The game hasn't started yet.")
    darts = int(p["darts"]["money"]) + int(p["darts"]["item"])
    moved = "✅" if p["moved"] else ("🔒" if g["locked"] else "⬜")
    parts = [f"{moved} {L(lang, 'حرکت', 'move')}", f"{'✅' if darts == 2 else '🎯'} {L(lang, 'دارت', 'darts')} {num(darts, lang)}/{num(2, lang)}"]
    if g["phase"] == "night":
        n = len(g["acts"].get(str(p["id"]), []))
        lim = 2 if p.get("double_act") else 1
        parts.append(f"{'✅' if n >= lim else '⬜'} {L(lang, 'اکت', 'act')} {num(n, lang)}/{num(lim, lang)}")
    else:
        voted = g["votes"].get(str(p["id"]))
        parts.append(f"{'✅' if voted else '⬜'} {L(lang, 'رأی', 'vote')}" + (f" → {pl(voted)['name']}" if voted and pl(voted) else ""))
    title = L(lang, "کارهای امشب: " if g["phase"] == "night" else "کارهای امروز: ", "Tonight: " if g["phase"] == "night" else "Today: ")
    return title + "  ".join(parts)


def home_text(p):
    g = G()
    lang = p["lang"]
    if not p.get("role"):
        return L(lang, "ثبت‌نام شدی؛ منتظر نقش از گاد باش.", "You're registered; wait for the GM to give you a role.")
    r = ROLES[p["role"]]
    lines = [
        f"{'💀' if not p['alive'] else '🧍'} {p['name']} — {r[lang]}" + (L(lang, " · فرقه", " · cult") if p["cult"] else ""),
        f"❤️ {num(p['hp'], lang)}   💰 {num(p['coins'], lang)}",
        f"📍 {board.square_name(p['pos'], lang) if p['pos'] else L(lang, 'هنوز روی نقشه نیستی', 'not on the map yet')}",
    ]
    if p.get("night_pos") and g["locked"] and p["night_pos"] != p["pos"]:
        lines.append(L(lang, f"🌙 جای امشب: {board.square_name(p['night_pos'])}", f"🌙 Tonight's place: {board.square_name(p['night_pos'], 'en')}"))
    if g["phase"] != "lobby":
        lock = L(lang, "🔒 نقشه قفل است" if g["locked"] else f"🔓 نقشه باز {lock_eta(lang)}",
                 "🔒 map locked" if g["locked"] else f"🔓 map open {lock_eta(lang)}")
        lines.append(f"{'🌙' if g['phase'] == 'night' else '☀️'} {phase_label(lang, g)} · {lock}")
    if p["alive"]:
        lines.append("")
        lines.append(checklist(g, p, lang))
    else:
        lines.append(L(lang, "\nشما مرده‌اید. ⚰️", "\nYou are dead. ⚰️"))
    return "\n".join(lines)


def home_rows(p):
    g = G()
    lang = p["lang"]
    if not p.get("role"):
        return [[(L(lang, "🌐 English", "🌐 فارسی"), "p:lang")]]
    if not p["alive"]:
        rows = [[(L(lang, "🎴 نقش من", "🎴 My role"), "p:role"), (L(lang, "🌐 English", "🌐 فارسی"), "p:lang")]]
        if p.get("fake"):
            rows.append([(L(lang, "👑 برگشت به اتاق فرمان", "👑 Back to the control room"), "g:asoff")])
        return rows
    rows = [[(L(lang, "🎲 حرکت", "🎲 Move"), "p:move"), (L(lang, "🎯 دارت", "🎯 Darts"), "p:darts")]]
    if g["phase"] == "night":
        rows.append([(L(lang, "🌙 اکت شب", "🌙 Night act"), "p:act"), (L(lang, "🛒 خرید", "🛒 Shop"), "p:shop")])
    elif g["phase"] == "day":
        rows.append([(L(lang, "🗳 رأی", "🗳 Vote"), "p:vote"), (L(lang, "🛒 خرید", "🛒 Shop"), "p:shop")])
    else:
        rows.append([(L(lang, "🛒 خرید", "🛒 Shop"), "p:shop")])
    rows.append([(L(lang, "🎒 کوله", "🎒 Bag"), "p:bag"), (L(lang, "🗺 نقشه", "🗺 Map"), "p:map")])
    extra = []
    here = loc_of(p) if g["locked"] else p["pos"]
    if g["phase"] == "night" and g["locked"] and p.get("night_pos") == "london" and not p["flags"].get("taxi_used"):
        extra.append((L(lang, "🚕 تاکسی", "🚕 Taxi"), "p:taxi"))
    if g["phase"] == "night" and g["locked"] and set(flags_at(here)) & {"vienna_slots", "berlin_slots"} and not (p.get("slots") or {}).get("done"):
        extra.append((L(lang, "🎰 اسلات", "🎰 Slots"), "p:slots"))
    if g["phase"] == "day" and p["bullets"]:
        extra.append((L(lang, f"🔫 شلیک ({num(len(p['bullets']))})", f"🔫 Shoot ({len(p['bullets'])})"), "p:shoot"))
    if p["pos"] == "stockholm":
        extra.append((L(lang, "🎲 شرط کازینو", "🎲 Casino bet"), "p:bet"))
    if p["role"] == "clown":
        extra.append((L(lang, "🎭 جواب جاسوسی", "🎭 Spy answer"), "p:cd"))
    if p["role"] == "godfather":
        extra.append((L(lang, "🃏 نقش جعلی", "🃏 Fake role"), "p:fk"))
    rows += chunks(extra, 2)
    rows.append([(L(lang, "🎴 نقش من", "🎴 My role"), "p:role"), (L(lang, "🌐 English", "🌐 فارسی"), "p:lang")])
    if p.get("fake"):
        rows.append([(L(lang, "👑 برگشت به اتاق فرمان", "👑 Back to the control room"), "g:asoff")])
    return rows


async def send_home(bot, p, q=None):
    text = banner(p["id"]) + home_text(p)
    if q:
        await edit_or_send(q, text, home_rows(p))
    else:
        await dm(bot, p["id"], home_text(p), home_text(p), reply_markup=kb(home_rows(p)))


def back(lang, to="p:home"):
    return [(L(lang, "↩️ بازگشت", "↩️ Back"), to)]


def people_rows(prefix, people, lang, back_to="p:home"):
    buttons = [(x["name"][:24], f"{prefix}:{x['id']}") for x in people]
    return chunks(buttons, 2) + [back(lang, back_to)]


def alive_others(p, include_self=False):
    return [x for x in roster(G()) if x["alive"] and x["role"] and (include_self or x["id"] != p["id"])]


# ---------------- jobs (after a dice animation) ----------------

async def job_after_roll(ctx):
    p = pl(ctx.job.data)
    if p:
        await mapview.send_move_map(ctx.bot, p)


async def job_result(ctx):
    pid, fa, en = ctx.job.data
    p = pl(pid)
    if p:
        await dm(ctx.bot, pid, fa, en, reply_markup=kb(home_rows(p)))


async def job_result_rows(ctx):
    pid, fa, en, rows = ctx.job.data
    await dm(ctx.bot, pid, fa, en, reply_markup=kb(rows))


# ---------------- the dispatcher for p:* buttons ----------------

async def on_button(update, ctx, data):
    q = update.callback_query
    p = pl(acting_uid(q.from_user.id))
    if not p or not p.get("role"):
        await edit_or_send(q, L(lang_of(q.from_user.id), "نقشی نداری. منتظر گاد باش.", "You have no role yet. Wait for the GM."))
        return
    parts = data.split(":")[1:]
    head, args = parts[0], parts[1:]
    await handle(update, ctx, p, head, args)


async def handle(update, ctx, p, head, args):
    q = update.callback_query
    g = G()
    lang = p["lang"]
    bot = ctx.bot

    if head == "home":
        return await send_home(bot, p, q)
    if head == "lang":
        p["lang"] = "en" if lang == "fa" else "fa"
        save()
        return await send_home(bot, p, q)
    if head == "role":
        return await edit_or_send(q, role_card(p, lang), [back(lang)])
    if head == "map":
        await q.answer()
        return await mapview.send_player_map(bot, p, reply_markup=kb([back(lang)]))
    if not p["alive"]:
        raise GameError("شما مرده‌اید.", "You are dead.")

    # ----- movement -----
    if head == "move":
        if g["phase"] == "lobby":
            raise GameError("بازی هنوز شروع نشده.", "The game hasn't started yet.")
        if g["locked"]:
            raise GameError("نقشه تا فاز بعد قفل است.", "The map is locked until the next phase.")
        if p["moved"]:
            raise GameError("در این فاز حرکت کردی.", "You've already moved this phase.")
        if p["pos"] is None:
            return await mapview.send_city_pick(bot, p, "📍 اولین حرکت: هر شهری که بخوای.", "📍 First move: any city you like.", "p:go")
        if p["flags"].get("free_move"):
            return await mapview.send_city_pick(bot, p, "🗺 نقشه قاچاقچی: بدون تاس به هر شهری برو.", "🗺 Smuggler's chart: go to any city, no dice.", "p:go")
        if p["move_roll"] is None:
            msg = await bot.send_dice(q.message.chat_id, emoji="🎲")
            p["move_roll"] = msg.dice.value
            save()
            ctx.job_queue.run_once(job_after_roll, DICE_WAIT, data=p["id"])
            return
        return await mapview.send_move_map(bot, p)
    if head == "go":
        dest = args[0]
        if g["locked"] or p["moved"]:
            raise GameError("الان نمی‌تونی حرکت کنی.", "You can't move now.")
        opts = actions.move_options(g, p, p["move_roll"] or 0)
        if dest not in opts:
            raise GameError("این مقصد در دسترس نیست.", "That destination is out of reach.")
        notes = actions.do_move(g, p, dest, opts[dest])
        save()
        for pid, fa, en in notes:
            await dm(bot, pid, fa, en)
        if p["hp"] <= 0:
            await gm_notes(bot, [(f"{p['name']} با عوارض به اچ‌پی {p['hp']} رسید.", f"{p['name']} dropped to {p['hp']} hp from tolls.")])
        info = ("\nℹ️ " + LOCATIONS[dest]["desc_" + lang]) if dest in LOCATIONS else ""
        await edit_or_send(q, L(lang, f"📍 رسیدی به {board.square_name(dest)}", f"📍 You arrived at {board.square_name(dest, 'en')}") + info,
                           [back(lang)])
        return

    # ----- darts -----
    if head == "darts":
        if g["phase"] == "lobby":
            raise GameError("بازی هنوز شروع نشده.", "The game hasn't started yet.")
        rows = []
        if not p["darts"]["money"]:
            rows.append([(L(lang, "💰 دارت پول (۰ تا ۵ سکه)", "💰 Money dart (0–5 coins)"), "p:dm")])
        if not p["darts"]["item"]:
            pw = actions.item_power(g, p)
            rows.append([(L(lang, f"🎁 دارت آیتم (قدرت {num(pw)})", f"🎁 Item dart (power {pw})"), "p:di")])
        if not rows:
            raise GameError("دارت‌های این فاز رو انداختی.", "You've thrown this phase's darts.")
        pw = actions.item_power(g, p)
        need = max(2, 7 - pw)
        text = L(lang, f"هر فاز دو دارت داری.\nدارت آیتم: با قدرت {num(pw)} باید حلقه {num(need)} یا داخل‌تر رو بزنی (۱ = بیرون، ۶ = وسط).",
                 f"Two darts each phase.\nItem dart: with power {pw} you need ring {need} or closer (1 = miss, 6 = bullseye).")
        return await edit_or_send(q, text, rows + [back(lang)])
    if head in ("dm", "di"):
        kind = "money" if head == "dm" else "item"
        if p["darts"][kind]:
            raise GameError("این دارت رو انداختی.", "Already thrown.")
        msg = await bot.send_dice(q.message.chat_id, emoji="🎯")
        v = msg.dice.value
        if kind == "money":
            coins = actions.money_dart(g, p, v)
            res = (f"🎯 {num(coins)} سکه گرفتی! (کل: {num(p['coins'])})", f"🎯 You won {coins} coins! (total {p['coins']})")
        else:
            power = actions.item_power(g, p)
            it = actions.item_dart(g, p, v)
            res = ((f"🎯 آیتم گرفتی: {item_line(it, 'fa')}", f"🎯 You found: {item_line(it, 'en')}") if it else
                   (f"🎯 چیزی پیدا نکردی (لازم بود {num(max(2, 7 - power))} یا بیشتر).", f"🎯 Nothing found (needed {max(2, 7 - power)}+)."))
        save()
        ctx.job_queue.run_once(job_result, DICE_WAIT, data=(p["id"], *res))
        return

    # ----- shop -----
    if head == "shop":
        return await edit_or_send(q, *shop_view(p, lang))
    if head == "bp":
        cost = actions.buy_power(g, p, args[0])
        save()
        await q.answer(L(lang, f"−{num(cost)} سکه", f"−{cost} coins"))
        return await edit_or_send(q, *shop_view(p, lang))
    if head == "bu":
        actions.buy_unit(g, p, args[0])
        save()
        return await edit_or_send(q, *shop_view(p, lang))

    # ----- bag: items and units -----
    if head == "bag":
        return await edit_or_send(q, *bag_view(p, lang))
    if head == "iu":
        actions.use_item(g, p, args[0])
        save()
        await q.answer(L(lang, f"✅ {ITEMS[args[0]]['fa']}", f"✅ {ITEMS[args[0]]['en']}"))
        if ITEMS[args[0]]["effect"]["type"] == "reroll":
            return await edit_or_send(q, L(lang, "تاس دوباره: «حرکت» رو بزن.", "Reroll ready: tap Move."), [back(lang)])
        return await edit_or_send(q, *bag_view(p, lang))
    if head == "up":
        actions.place_unit(g, p, args[0])
        save()
        return await edit_or_send(q, L(lang, f"✅ {unit_name(args[0], 'fa')} در {board.square_name(p['pos'])} مستقر شد.",
                                       f"✅ {unit_name(args[0], 'en')} placed at {board.square_name(p['pos'], 'en')}."), [back(lang, "p:bag")])
    if head == "us":
        unit = args[0]
        kind = "sea" if unit in ("mine", "ship") else "road"
        rids = board.routes_touching(g, p["pos"], kind=kind)
        if not rids:
            raise GameError("مسیر مناسبی به خانه‌ات وصل نیست.", "No suitable route touches your square.")
        st = {"ok": ("باز", "open"), "broken": ("خراب", "broken"), "mined": ("مین", "mined")}
        rows = [[(f"{board.route_name(g, r, lang)} · {L(lang, *st[board.route_status(g, r)])}", f"p:ur:{unit}:{r}")] for r in rids]
        return await edit_or_send(q, L(lang, "کدوم مسیر؟", "Which route?"), rows + [back(lang, "p:bag")])
    if head == "ur":
        actions.strike_route(g, p, args[0], args[1])
        save()
        return await edit_or_send(q, L(lang, f"✅ انجام شد: {board.route_name(g, args[1])}", f"✅ Done: {board.route_name(g, args[1], 'en')}"),
                                  [back(lang, "p:bag")])
    if head == "ud":
        if p["units"].get("shovel", 0) < 1:
            raise GameError("بیل نداری.", "You have no shovel.")
        rows = [[(LOCATIONS[c][lang], f"p:udt:{c}")] for c in CITIES if c != p["pos"]]
        return await edit_or_send(q, L(lang, "جاده جدید از اینجا به کجا؟ (گاد تأیید می‌کنه)", "New road from here to where? (the GM approves)"),
                                  rows + [back(lang, "p:bag")])
    if head == "udt":
        if p["units"].get("shovel", 0) < 1:
            raise GameError("بیل نداری.", "You have no shovel.")
        await to_gms(bot, f"⛏ {p['name']}: {board.square_name(p['pos'])} → {LOCATIONS[args[0]]['fa']}",
                     reply_markup=kb([[("✅", f"g:dig:{p['id']}:{p['pos']}:{args[0]}"), ("❌", f"g:dig:{p['id']}:0:0")]]))
        return await edit_or_send(q, L(lang, "درخواست برای گاد فرستاده شد.", "Request sent to the GM."), [back(lang)])
    if head == "ub":
        kind = args[0]
        if p["units"].get(kind + "_balloon", 0) < 1:
            raise GameError("بالن نداری.", "You have no balloon.")
        rows = chunks([(LOCATIONS[c][lang][:22], f"p:ubt:{kind}:{c}") for c in CITIES], 2)
        return await edit_or_send(q, L(lang, f"بالن رو بالای کجا بفرستی؟ نتیجه ساعت {num(LOCK_HOUR)}:۰۰.",
                                       f"Send the balloon over which place? Result at {LOCK_HOUR}:00."), rows + [back(lang, "p:bag")])
    if head == "ubt":
        actions.launch_balloon(g, p, args[0], args[1])
        save()
        return await edit_or_send(q, L(lang, f"🎈 بالن به سمت {LOCATIONS[args[1]]['fa']} رفت.", f"🎈 Balloon sent toward {LOCATIONS[args[1]]['en']}."),
                                  [back(lang)])

    # ----- clown / godfather settings -----
    if head == "cd" and p["role"] == "clown":
        rows = chunks([(role_name(r, lang), f"p:cdr:{r}") for r in ROLES], 3)
        cur = role_name(p["disguise"], lang) if p.get("disguise") else L(lang, "نقش واقعی", "real role")
        return await edit_or_send(q, L(lang, f"جاسوسی روی تو چه نشون بده؟ (الان: {cur})", f"What should spying on you show? (now: {cur})"),
                                  rows + [back(lang)])
    if head == "cdr" and p["role"] == "clown":
        p["disguise"] = args[0]
        save()
        return await send_home(bot, p, q)
    if head == "fk" and p["role"] == "godfather":
        rows = chunks([(role_name(r, lang), f"p:fkr:{r}") for r in ROLES if ROLES[r]["team"] == HUMAN], 3)
        cur = role_name(p["fake_role"], lang) if p.get("fake_role") else "—"
        return await edit_or_send(q, L(lang, f"نقش جعلی (در مرگ اعلام می‌شه). الان: {cur}", f"Fake role (read out when you die). Now: {cur}"),
                                  rows + [back(lang)])
    if head == "fkr" and p["role"] == "godfather":
        p["fake_role"] = args[0]
        save()
        return await send_home(bot, p, q)

    # ----- night acts -----
    if head in ("act", "a", "t", "tg", "tb", "td", "bl", "bn", "bx", "acx"):
        return await act_flow(update, ctx, p, head, args)

    # ----- voting -----
    if head == "vote":
        if g["phase"] != "day":
            raise GameError("رأی‌گیری فقط در روز.", "Voting is only during the day.")
        cur = g["votes"].get(str(p["id"]))
        if cur:
            text = L(lang, f"رأی امروزت به {pl(cur)['name']} ثبت شده. (فقط اولین رأی هر روز حساب می‌شه)",
                     f"Your vote today is for {pl(cur)['name']}. (Only the first vote each day counts.)")
            rows = [back(lang)]
        else:
            text = L(lang, f"به کی رأی می‌دی؟ وزن رأیت: {num(actions.vote_weight(g, p))}\nمی‌تونی تو گروه هم بنویسی: #رای اسم",
                     f"Who do you vote for? Your vote weight: {actions.vote_weight(g, p)}\nYou can also write in the group: #رای name")
            rows = people_rows("p:v", alive_others(p), lang)
        if p["role"] == "judge" and p["charges"].get("cancel_vote") and not g["vote_cancelled"]:
            rows.insert(-1, [(L(lang, "⚖️ لغو رأی‌گیری امروز", "⚖️ Cancel today's vote"), "p:vc")])
        return await edit_or_send(q, text, rows)
    if head == "v":
        T = pl(args[0])
        status, extra = await votes.vote_from_menu(bot, p, T)
        msgs = {"ok": ("✅ رأی ثبت شد و در گروه اعلام شد.", "✅ Vote recorded and announced in the group."),
                "lightning": ("⚡️ صاعقه! او در هتل است؛ رأیت شمرده نشد ولی می‌تونی دوباره رأی بدی.",
                              "⚡️ Lightning! They're in the hotel; your vote didn't count, but you can vote again."),
                "already": ("امروز قبلاً رأی دادی.", "You already voted today.")}
        fa, en = msgs.get(status, votes.REFUSALS.get(status, ("نشد.", "Couldn't vote.")))
        return await edit_or_send(q, L(lang, fa, en), [back(lang)])
    if head == "vc" and p["role"] == "judge":
        if not p["charges"].get("cancel_vote") or g["phase"] != "day":
            raise GameError("نمی‌تونی.", "You can't.")
        p["charges"]["cancel_vote"] = 0
        g["vote_cancelled"] = True
        save()
        await events.group(bot, "⚖️ قاضی رأی‌گیری امروز را لغو کرد.", "⚖️ The judge has cancelled today's vote.")
        return await send_home(bot, p, q)

    # ----- place specials -----
    if head == "taxi":
        if not g["locked"] or p.get("night_pos") != "london":
            raise GameError("تاکسی فقط بعد از قفل نقشه و در لندن.", "The taxi only works after the lock, in London.")
        return await mapview.send_city_pick(bot, p, "🚕 کجا بریم؟ (روی نقشه عمومی همچنان لندن نشون داده می‌شی)",
                                            "🚕 Where to? (the public map still shows you in London)", "p:tx")
    if head == "tx":
        actions.taxi(g, p, args[0])
        save()
        await gm_notes(bot, [(f"🚕 {p['name']} با تاکسی رفت به {args[0]}", f"🚕 {p['name']} took the taxi to {args[0]}")])
        return await edit_or_send(q, L(lang, f"🚕 مخفیانه رفتی به {LOCATIONS[args[0]]['fa']}", f"🚕 You secretly rode to {LOCATIONS[args[0]]['en']}"),
                                  [back(lang)])
    if head == "slots":
        return await pull_slot(bot, ctx, p, q.message.chat_id)
    if head == "rv":
        T = pl(args[0])
        actions.berlin_revive(g, p, T)
        save()
        await events.group(bot, f"⚰️→🧍 {T['name']} از قبرستان برلین برگشت!", f"⚰️→🧍 {T['name']} has risen from the Berlin graveyard!")
        await dm(bot, T["id"], "شما زنده شدید!", "You have been revived!")
        return await edit_or_send(q, L(lang, f"{T['name']} زنده شد.", f"{T['name']} is revived."), [back(lang)])
    if head == "shoot":
        if g["phase"] != "day" or not p["bullets"]:
            raise GameError("فقط در روز و اگر تیر داشته باشی.", "Only during the day, and only if you hold a bullet.")
        return await edit_or_send(q, L(lang, "به کی شلیک کنی؟ (نوع تیر رو نمی‌دونی)", "Shoot whom? (you don't know the bullet type)"),
                                  people_rows("p:sh", alive_others(p), lang))
    if head == "sh":
        await events.fire_bullet(bot, p, pl(args[0]))
        return await send_home(bot, p, q)
    if head == "bet":
        if p["pos"] != "stockholm":
            raise GameError("شرط‌بندی فقط در کازینوی استکهلم.", "Bets only in the Stockholm casino.")
        others = [x for x in alive_others(p) if x["pos"] == "stockholm"]
        if not others:
            raise GameError("کس دیگه‌ای در کازینو نیست.", "Nobody else is in the casino.")
        rows = [[(f"{x['name'][:14]} · {num(s, lang)}", f"p:bt:{x['id']}:{s}") for s in (2, 5, 10)] for x in others]
        return await edit_or_send(q, L(lang, "سنگ‌کاغذقیچی با شرط (سکه):", "Rock-paper-scissors for coins:"), rows + [back(lang)])
    if head == "bt":
        await events.create_bet(bot, p, pl(args[0]), int(args[1]))
        return await edit_or_send(q, L(lang, "دعوت فرستاده شد.", "Challenge sent."), [back(lang)])


async def pull_slot(bot, ctx, p, chat_id):
    g = G()
    if g["phase"] != "night" or not g["locked"]:
        raise GameError("ماشین اسلات بعد از قفل نقشه در شب کار می‌کنه.", "The slot machine runs at night after the map lock.")
    if not set(flags_at(loc_of(p))) & {"vienna_slots", "berlin_slots"}:
        raise GameError("اینجا ماشین اسلات نیست.", "There's no slot machine here.")
    if (p.get("slots") or {}).get("done"):
        raise GameError("سهم امشبت از اسلات تموم شده.", "You've used tonight's slot pulls.")
    msg = await bot.send_dice(chat_id, emoji="🎰")
    s = actions.slot_pull(g, p, msg.dice.value)
    save()
    lang = p["lang"]
    if s["hit"] and s["kind"] == "berlin":
        dead = [x for x in roster(g) if not x["alive"] and x["role"] and not x.get("unrevivable")]
        rows = [[(x["name"], f"p:rv:{x['id']}")] for x in dead] or [back(lang)]
        ctx.job_queue.run_once(job_result_rows, DICE_WAIT, data=(p["id"], "🎰 سه‌تای یکسان! یک نفر رو زنده کن:",
                                                                 "🎰 Three of a kind! Revive someone:", rows))
        return
    if s["hit"]:
        res = ("🎰 جک‌پات! امشب همه قدرت‌ها و اچ‌پی +۲۰.", "🎰 Jackpot! All powers and HP +20 tonight.")
    elif s["done"]:
        vienna = s["kind"] == "vienna"
        res = ("🎰 تموم شد، سه‌تای یکسان نیامد." + (" امشب همه قدرت‌ها −۲۰." if vienna else ""),
               "🎰 Out of pulls, no three of a kind." + (" All powers −20 tonight." if vienna else ""))
    else:
        res = (f"🎰 نشد. {num(s['left'])} بار دیگه.", f"🎰 No luck. {s['left']} pulls left.")
    ctx.job_queue.run_once(job_result, DICE_WAIT, data=(p["id"], *res))


def shop_view(p, lang):
    g = G()
    lines = [L(lang, f"🛒 خرید · 💰 {num(p['coins'])} سکه", f"🛒 Shop · 💰 {p['coins']} coins")]
    rows = []
    if g["phase"] == "night":
        lines.append(L(lang, "قدرت برای همین شب (هر بار +۱). عدد داخل پرانتز = قیمت.", "Power for tonight (+1 each tap). Price in brackets."))
        btns = [(f"{stat_name(s, lang)} +1 ({num(price, lang)})", f"p:bp:{s}") for s, price in POWER_PRICES.items() if s != "hp"]
        rows += chunks(btns, 2)
    else:
        lines.append(L(lang, "قدرت شبانه رو فقط شب می‌شه خرید.", "Night powers are sold only at night."))
    rows.append([(L(lang, f"❤️ اچ‌پی +۱ دائمی ({num(POWER_PRICES['hp'])})", f"❤️ HP +1 permanent ({POWER_PRICES['hp']})"), "p:bp:hp")])
    shop = LOCATIONS.get(p["pos"], {}).get("shop")
    if shop:
        rows.append([(L(lang, f"🏪 {unit_name(shop, 'fa')} ({num(UNIT_PRICES[shop])})", f"🏪 {unit_name(shop, 'en')} ({UNIT_PRICES[shop]})"), f"p:bu:{shop}")])
    else:
        lines.append(L(lang, "\nفروشگاه‌ها: کشتی لندن · بیل آمستردام · مین کپنهاگ · بالن جنگی سن‌پترزبورگ · بالن جاسوسی مسکو · توپ کنستانتینوپل",
                       "\nShops: ship London · shovel Amsterdam · mine Copenhagen · war balloon St Petersburg · spy balloon Moscow · cannon Constantinople"))
    if p["bought"]:
        lines.append(L(lang, "امشب خریدی: ", "Bought tonight: ") + ", ".join(f"{stat_name(k, lang)} +{num(v, lang)}" for k, v in p["bought"].items()))
    return "\n".join(lines), rows + [back(lang)]


def bag_view(p, lang):
    lines = [L(lang, "🎒 کوله", "🎒 Bag")]
    rows = []
    if p["items"]:
        lines.append(L(lang, "\nآیتم‌ها (برای استفاده بزن):", "\nItems (tap to use):"))
        for k in p["items"]:
            lines.append("• " + item_line(k, lang))
        rows += chunks([(f"✨ {ITEMS[k][lang][:22]}", f"p:iu:{k}") for k in dict.fromkeys(p["items"])], 2)
    u = {k: v for k, v in p["units"].items() if v}
    if u:
        lines.append(L(lang, "\nواحدها: ", "\nUnits: ") + ", ".join(f"{unit_name(k, lang)}×{num(v, lang)}" for k, v in u.items()))
        if u.get("cannon"):
            rows.append([(L(lang, "💣 توپ: کاشتن اینجا", "💣 Cannon: place here"), "p:up:cannon"), (L(lang, "💣 توپ: خراب کردن جاده", "💣 Cannon: destroy road"), "p:us:cannon")])
        if u.get("ship"):
            rows.append([(L(lang, "⛵ کشتی: کاشتن اینجا", "⛵ Ship: place here"), "p:up:ship"), (L(lang, "⛵ کشتی: پاک کردن مین", "⛵ Ship: clear mine"), "p:us:ship")])
        if u.get("mine"):
            rows.append([(L(lang, "🌊 مین: بستن مسیر دریایی", "🌊 Mine: block a sea lane"), "p:us:mine")])
        if u.get("shovel"):
            rows.append([(L(lang, "⛏ بیل: تعمیر جاده", "⛏ Shovel: repair road"), "p:us:shovel"), (L(lang, "⛏ بیل: جاده جدید", "⛏ Shovel: new road"), "p:ud")])
        if u.get("spy_balloon"):
            rows.append([(L(lang, "🎈 فرستادن بالن جاسوسی", "🎈 Launch spy balloon"), "p:ub:spy")])
        if u.get("war_balloon"):
            rows.append([(L(lang, "🎈 فرستادن بالن جنگی", "🎈 Launch war balloon"), "p:ub:war")])
    ch = {k: v for k, v in p["charges"].items() if v}
    if ch:
        names = {"bomb": ("بمب", "bomb"), "poison": ("سم", "poison"), "war_bullet": ("تیر جنگی", "war bullet"),
                 "guess": ("حدس نقش", "role guess"), "cult_check": ("استعلام فرقه", "cult check"), "cancel_vote": ("لغو رأی", "vote cancel")}
        lines.append(L(lang, "\nتوانایی‌های باقی‌مانده: ", "\nAbilities left: ") +
                     ", ".join(f"{L(lang, *names.get(k, (k, k)))}×{num(v, lang)}" for k, v in ch.items()))
    if p["bullets"]:
        lines.append(L(lang, f"\n🔫 تیر در دست: {num(len(p['bullets']))}", f"\n🔫 Bullets held: {len(p['bullets'])}"))
    if len(lines) == 1:
        lines.append(L(lang, "خالیه. با دارت آیتم پیدا کن یا از فروشگاه شهرها بخر.", "Empty. Find items with the item dart or buy units in shop cities."))
    return "\n".join(lines), rows + [back(lang)]


# ---------------- night acts ----------------

def act_limit(p):
    return 2 if p.get("double_act") else 1


def acts_text(p, lang):
    lst = G()["acts"].get(str(p["id"]), [])
    if not lst:
        return L(lang, "هنوز اکتی ثبت نکردی.", "No act submitted yet.")
    out = [L(lang, "اکت‌های ثبت‌شده:", "Your acts:")]
    for a in lst:
        t = pl(a.get("target"))["name"] if a.get("target") and pl(a.get("target")) else ""
        ex = a.get("extra") or {}
        if a["type"] == "bullets":
            t = ", ".join(pl(x)["name"] for x in ex.get("targets", []) if pl(x))
        if a["type"] == "duel" and ex.get("target2") and pl(ex["target2"]):
            t += " ⚔️ " + pl(ex["target2"])["name"]
        out.append(f"• {act_name(a['type'], lang)} → {t}")
    return "\n".join(out)


def add_act(p, act):
    g = G()
    if g["phase"] != "night":
        raise GameError("اکت فقط در شب.", "Acts only at night.")
    if g.get("pending"):
        raise GameError("گاد در حال محاسبه شب است.", "The GM is already resolving the night.")
    lst = g["acts"].setdefault(str(p["id"]), [])
    if len(lst) >= act_limit(p):
        raise GameError("به سقف اکت‌هات رسیدی؛ اول پاکشون کن.", "You've reached your act limit; clear first.")
    t = act["type"]
    if t == "attack" and "church" in LOCATIONS.get(loc_of(p) or "", {}).get("flags", []):
        raise GameError("در کلیسا نمی‌تونی حمله کنی.", "You can't attack from the church.")
    need = {"bomb": "bomb", "poison": "poison", "guess": "guess", "cult_check": "cult_check"}.get(t)
    if need and p["charges"].get(need, 0) < 1:
        raise GameError("شارژ این توانایی تموم شده.", "That ability is used up.")
    if t == "convert" and p.get("no_recruit_until", 0) >= g["cycle"]:
        raise GameError("امشب نمی‌تونی عضو بگیری.", "You can't recruit tonight.")
    lst.append(act)
    save()


async def act_done(q, p, lang):
    await edit_or_send(q, "✅ " + acts_text(p, lang), [back(lang, "p:act"), back(lang)])


async def act_flow(update, ctx, p, head, args):
    q = update.callback_query
    g = G()
    lang = p["lang"]
    if g["phase"] != "night":
        raise GameError("اکت فقط در شب.", "Acts only at night.")
    if head == "act":
        types = ["attack", "protect", "defuse", "spy"] + SPECIALS.get(p["role"], [])
        rows = chunks([(act_name(t, lang), f"p:a:{t}") for t in types], 2)
        if g["acts"].get(str(p["id"])):
            rows.append([(L(lang, "🗑 پاک کردن اکت‌ها", "🗑 Clear my acts"), "p:acx")])
        lim = L(lang, f"\n\nامشب {num(act_limit(p))} اکت داری. قدرت هر اکت = ۲ تاس + استت تو.",
                f"\n\nYou have {act_limit(p)} act(s) tonight. Power = 2 dice + your stat.")
        return await edit_or_send(q, acts_text(p, lang) + lim, rows + [back(lang)])
    if head == "acx":
        g["acts"].pop(str(p["id"]), None)
        save()
        return await act_flow(update, ctx, p, "act", [])
    if head == "a":
        t = args[0]
        if t == "cult_check":
            add_act(p, {"type": t, "target": None, "extra": {}})
            return await act_done(q, p, lang)
        if t == "bullets":
            ctx.user_data["bul"] = []
            return await edit_or_send(q, *bullet_view(p, ctx, lang))
        return await edit_or_send(q, L(lang, f"{act_name(t, 'fa')} روی چه کسی؟", f"{act_name(t, 'en')} on whom?"),
                                  people_rows(f"p:t:{t}", alive_others(p, include_self=(t == "protect")), lang, "p:act"))
    if head == "t":
        t, tid = args[0], args[1]
        if t == "guess":
            rows = chunks([(role_name(r, lang), f"p:tg:{tid}:{r}") for r in ROLES], 3)
            return await edit_or_send(q, L(lang, f"نقش {pl(tid)['name']} چیه؟", f"What is {pl(tid)['name']}'s role?"), rows + [back(lang, "p:act")])
        if t == "bomb":
            rows = [[(f"🔌 {num(w, lang)}", f"p:tb:{tid}:{w}") for w in range(1, 5)]]
            return await edit_or_send(q, L(lang, "کدوم سیم اصلیه؟ (اگه درست ببره، بمب خنثی می‌شه)", "Which wire is live? (if they cut it, the bomb is defused)"),
                                      rows + [back(lang, "p:act")])
        if t == "duel":
            others = [x for x in alive_others(p, include_self=True) if str(x["id"]) != tid]
            return await edit_or_send(q, L(lang, "حریف دوم دوئل؟", "Second duellist?"), people_rows(f"p:td:{tid}", others, lang, "p:act"))
        add_act(p, {"type": t, "target": tid, "extra": {}})
        return await act_done(q, p, lang)
    if head == "tg":
        add_act(p, {"type": "guess", "target": args[0], "extra": {"role": args[1]}})
        return await act_done(q, p, lang)
    if head == "tb":
        add_act(p, {"type": "bomb", "target": args[0], "extra": {"wire": int(args[1])}})
        return await act_done(q, p, lang)
    if head == "td":
        add_act(p, {"type": "duel", "target": args[0], "extra": {"target2": args[1]}})
        return await act_done(q, p, lang)
    if head == "bl":
        sel = ctx.user_data.setdefault("bul", [])
        if args[0] in sel:
            sel.remove(args[0])
        elif len(sel) < 3:
            sel.append(args[0])
        return await edit_or_send(q, *bullet_view(p, ctx, lang))
    if head == "bn":
        sel = ctx.user_data.get("bul", [])
        if not sel:
            raise GameError("هیچ‌کس انتخاب نشده.", "Nobody selected.")
        rows = [[(pl(x)["name"], f"p:bx:{x}")] for x in sel] if p["charges"].get("war_bullet", 0) > 0 else []
        rows.append([(L(lang, "بدون تیر جنگی", "No war bullet"), "p:bx:0")])
        return await edit_or_send(q, L(lang, f"تیر جنگی به کی؟ (باقی‌مانده: {num(p['charges'].get('war_bullet', 0))})",
                                       f"War bullet to whom? (left: {p['charges'].get('war_bullet', 0)})"), rows)
    if head == "bx":
        sel = ctx.user_data.get("bul", [])
        add_act(p, {"type": "bullets", "target": None, "extra": {"targets": sel, "war": None if args[0] == "0" else args[0]}})
        ctx.user_data["bul"] = []
        return await act_done(q, p, lang)


def bullet_view(p, ctx, lang):
    sel = ctx.user_data.get("bul", [])
    btns = [(("✅ " if str(x["id"]) in sel else "") + x["name"][:22], f"p:bl:{x['id']}") for x in alive_others(p)]
    rows = chunks(btns, 2) + [[(L(lang, "ادامه ➡️", "Next ➡️"), "p:bn")], back(lang, "p:act")]
    return L(lang, "حداکثر ۳ نفر انتخاب کن:", "Pick up to 3 people:"), rows


# ---------------- commands ----------------

async def cmd_menu(update, ctx):
    from .gm_ui import send_control_room
    from .common import is_gm
    if update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    p = pl(acting_uid(uid))
    if is_gm(uid) and (not p or not p.get("role")):
        return await send_control_room(ctx.bot, uid)
    if not p:
        await update.message.reply_text(L(lang_of(uid), "اول /start بزن.", "Send /start first."))
        return
    await send_home(ctx.bot, p)


async def cmd_lang(update, ctx):
    from .common import is_gm
    uid = update.effective_user.id
    p = pl(acting_uid(uid))
    if p and not (is_gm(uid) and not playing_as_any(uid)):
        p["lang"] = "en" if p["lang"] == "fa" else "fa"
        new = p["lang"]
    else:
        gl = G().setdefault("gm_lang", {})
        new = gl[str(uid)] = "en" if gl.get(str(uid), "fa") == "fa" else "fa"
    save()
    await update.message.reply_text(L(new, "زبان: فارسی", "Language: English"))


def playing_as_any(uid):
    from .common import playing_as
    return playing_as(uid) is not None
