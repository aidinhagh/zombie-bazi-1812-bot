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
from .state import roster, needs_fake_char
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
        lim = act_limit(p)
        why = []
        if any(a["type"] == "steal" for a in g["acts"].get(str(p["id"]), [])):
            why.append("دزدی + اکت قرضی")
        if p.get("double_act") and "double_act_50" in flags_at(loc_of(p)):
            why.append("زوج خانقاه")
        if p["flags"].get("extra_act"):
            why.append("قهوه سیاه")
        parts.append(f"{'✅' if n >= lim else '⬜'} اکت {num(n, lang)} از {num(lim, lang)}" + (f" ({'، '.join(why)})" if why else ""))
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
    if p.get("char"):
        lines.insert(1, f"🎭 {p['char']}")
    if p.get("fake_char") and p["alive"]:
        lines.append(f"🃏 جعلی: {p['fake_char']} · 📍 {board.square_name(p['fake_pos']) if p.get('fake_pos') else 'جایی نگذاشتی'}")
    if p.get("night_pos") and g["locked"] and p["night_pos"] != p["pos"]:
        lines.append(L(lang, f"🌙 جای امشب: {board.square_name(p['night_pos'])}", f"🌙 Tonight's place: {board.square_name(p['night_pos'], 'en')}"))
    if g["phase"] != "lobby":
        lock = L(lang, "🔒 نقشه قفل است" if g["locked"] else f"🔓 نقشه باز {lock_eta(lang)}",
                 "🔒 map locked" if g["locked"] else f"🔓 map open {lock_eta(lang)}")
        lines.append(f"{'🌙' if g['phase'] == 'night' else '☀️'} {phase_label(lang, g)} · {lock}")
    from .night_window import window
    if window(g):
        lines.append("⏰ فقط امشب: مکان تا ۲۳:۰۰؛ اکت تا ۰۱:۰۰ روز بعد، به وقت تهران.")
    if p["alive"]:
        lines.append("")
        lines.append(checklist(g, p, lang))
    else:
        lines.append(L(lang, "\nشما مرده‌اید. ⚰️", "\nYou are dead. ⚰️"))
    return "\n".join(lines)


def dice_rows(p):
    """Keep outstanding dice reachable even after the original confirmation is gone."""
    g = G()
    from .night_window import expired
    if (g["phase"] != "night" or not p.get("alive")
            or g.get("applied_cycle") == g["cycle"] or expired(g, "acts_until")):
        return []
    rows = []
    if (g["locked"] and "double_act_50" in flags_at(loc_of(p))
            and p["flags"].get("wagram_roll") is None):
        rows.append([("🎲 تاس خانقاه — شانس اکت دوم", "p:wroll")])
    rows += [[(f"🎲🎲 ریختن ۲ تاس برای «{act_name(a['type'], p['lang'])}»", f"p:dice:{i}")]
             for i, a in enumerate(g["acts"].get(str(p["id"]), [])) if not a.get("dice") and not a.get("dice_total")]
    return rows


def home_rows(p):
    g = G()
    lang = p["lang"]
    if not p.get("role"):
        return [[(L(lang, "🔄 تازه کن", ""), "p:home")]]
    if not p["alive"]:
        rows = [[(L(lang, "🎴 نقش من", "🎴 My role"), "p:role")]]
        if p.get("fake"):
            rows.append([(L(lang, "👑 برگشت به اتاق فرمان", "👑 Back to the control room"), "g:asoff")])
        return rows
    rows = []
    waiting = events.pending_for(p)
    if waiting:
        rows.append([(f"⏳ کارهای منتظر تو ({num(len(waiting))})", "p:pend")])
    rows.append([(L(lang, "🎲 حرکت", "🎲 Move"), "p:move"), (L(lang, "🎯 دارت", "🎯 Darts"), "p:darts")])
    if g["phase"] == "night":
        rows.append([(L(lang, "🌙 اکت شب", "🌙 Night act"), "p:act"), (L(lang, "🛒 خرید", "🛒 Shop"), "p:shop")])
    elif g["phase"] == "day":
        rows.append([(L(lang, "🛒 خرید", "🛒 Shop"), "p:shop")])
        if p['role'] == 'apothecary':
            rows.append([("🧪 پادزهر — اکت روز", "p:antidotes")])
    else:
        rows.append([(L(lang, "🛒 خرید", "🛒 Shop"), "p:shop")])
    bag = "🎒 کوله و آیتم‌ها" + (f" ({num(len(p['items']))})" if p["items"] else "")
    rows.append([(bag, "p:bag"), (L(lang, "🗺 نقشه", "🗺 Map"), "p:map")])
    extra = []
    here = loc_of(p) if g["locked"] else p["pos"]
    if (g["phase"] == "night" and g["locked"] and p.get("night_pos") == "london" and not p["flags"].get("taxi_used")
            and not actions.ruined(g, "london")):
        extra.append((L(lang, "🚕 تاکسی", "🚕 Taxi"), "p:taxi"))
    if g["phase"] == "night" and g["locked"] and set(flags_at(here)) & {"vienna_slots", "berlin_slots"} and not (p.get("slots") or {}).get("done"):
        extra.append((L(lang, "🎰 اسلات", "🎰 Slots"), "p:slots"))
    if g["phase"] == "day" and p["bullets"]:
        extra.append((L(lang, f"🔫 شلیک ({num(len(p['bullets']))})", f"🔫 Shoot ({len(p['bullets'])})"), "p:shoot"))
    if p["pos"] == "stockholm" and not actions.ruined(g, "stockholm"):
        extra.append((L(lang, "🎲 شرط کازینو", "🎲 Casino bet"), "p:bet"))
    if p["role"] == "clown":
        extra.append((L(lang, "🎭 جواب جاسوسی", "🎭 Spy answer"), "p:cd"))
    if p["role"] == "godfather":
        extra.append((L(lang, "🃏 نقش جعلی", "🃏 Fake role"), "p:fk"))
    if needs_fake_char(p):
        extra.append(("👤 شخصیت جعلی", "p:fc"))
    rows += dice_rows(p)
    rows += chunks(extra, 2)
    rows.append([(L(lang, "🎴 نقش من", "🎴 My role"), "p:role")])
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
    data = ctx.job.data
    if isinstance(data, dict):
        p = pl(data["player_id"])
        g = G()
        if (not p or p.get("moved") or g.get("locked")
                or (g["cycle"], g["phase"]) != (data["cycle"], data["phase"])):
            return
        from .night_window import expired
        if expired(g, "move_until"):
            return
        await mapview.send_move_map(ctx.bot, p, destination=data["chat_id"])
    else:  # Compatibility with an already queued job.
        p = pl(data)
        if p:
            await mapview.send_move_map(ctx.bot, p)


async def job_result(ctx):
    pid, fa, en, *destination = ctx.job.data
    p = pl(pid)
    if p:
        await dm(ctx.bot, pid, fa, en, reply_markup=kb(home_rows(p)), destination=destination[0] if destination else None)


async def job_result_rows(ctx):
    pid, fa, en, rows, *destination = ctx.job.data
    await dm(ctx.bot, pid, fa, en, reply_markup=kb(rows), destination=destination[0] if destination else None)


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
    from .night_window import check_actions, expired
    # An old night-act button should still lead the apothecary to their day decision.
    if head == 'act' and g['phase'] == 'day' and p.get('role') == 'apothecary':
        head = 'antidotes'
    if head in ("act", "a", "t", "tg", "tb", "td", "bl", "bn", "bx", "acx", "dice", "wroll"):
        check_actions(g)
    if head in ("move", "roll", "dest", "go", "mv", "nodes", "fc", "fcn", "fcg") and expired(g, "move_until"):
        raise GameError("مهلت جابه‌جایی امشب تمام شده است.")

    if head == "home":
        return await send_home(bot, p, q)
    if head == "lang":
        p["lang"] = "en" if lang == "fa" else "fa"
        save()
        return await send_home(bot, p, q)
    if head == "role":
        return await edit_or_send(q, role_card(p, lang), [back(lang)])
    if head == 'antidotes':
        if not p['alive']:
            raise GameError('شما مرده‌اید.')
        poisons = events.antidote_decisions(p)
        lines = ['🧪 پادزهر — تصمیم روز عطار',
                 'تا شروع شب بعد می‌توانی بین دادن و ندادن پادزهر جابه‌جا شوی؛ شارژ سم برای این تصمیم لازم نیست.']
        rows = []
        for po in poisons:
            target = pl(po['target'])['name']
            choice = ('پادزهر می‌دهی' if po.get('antidote') else 'پادزهر نمی‌دهی') if 'antidote' in po else 'هنوز انتخاب نکردی'
            lines.append(f'• {target}: {choice}')
            rows += [[(f"✅ پادزهر به {target}", f"x:an:{po['id']}:1"),
                      (f"❌ پادزهر نده به {target}", f"x:an:{po['id']}:0")]]
        if not poisons:
            lines.append('الان تصمیم پادزهر بازی نداری؛ فقط سمِ ثبت و اعمال‌شده روی بازیکن زنده، تا شروع شب بعد قابل تغییر است.')
        return await edit_or_send(q, '\n\n'.join(lines), rows + [back(lang)])
    if head == "pend":
        waiting = events.pending_for(p)
        if not waiting:
            return await send_home(bot, p, q)
        label, rows = waiting[0]
        more = f"\n\n(+{num(len(waiting) - 1)} کار دیگر بعد از این)" if len(waiting) > 1 else ""
        return await edit_or_send(q, label + more, rows + [back(lang)])
    if head == "map":
        await q.answer()
        rows = [back(lang)]
        if mapview.webapp_url():
            rows.insert(0, [("🗺 نقشه تعاملی", "webapp:" + mapview.webapp_url())])
        return await mapview.send_player_map(bot, p, reply_markup=kb(rows))
    if not p["alive"]:
        raise GameError("شما مرده‌اید.", "You are dead.")

    # ----- fake character (zombies and independents) -----
    if head in ("fc", "fcn", "fcg"):
        if not needs_fake_char(p):
            raise GameError("تو شخصیت جعلی نداری.", "You have no fake character.")
        if head == "fc":
            if g["locked"]:
                raise GameError("نقشه تا فاز بعد قفل است.", "The map is locked until the next phase.")
            where = board.square_name(p["fake_pos"]) if p.get("fake_pos") else "هنوز جایی نیست"
            title = (f"👤 شخصیت جعلی تو: «{p['fake_char']}» · الان: {where}\n"
                     f"تا ساعت {num(LOCK_HOUR)}:۰۰ هر جای نقشه که بخواهی بگذارش. اگر بالن جاسوسی بالای آن مکان برود، این شخصیت هم در گزارش بالن دیده می‌شود."
                     "\n(یادت باشد آدم‌ها دو شب پشت سر هم یک جا نمی‌مانند و با تاس جابه‌جا می‌شوند.)")
            return await mapview.send_city_pick(bot, p, title, "", "p:fcg", nodes_cb="p:fcn")
        if head == "fcn":
            from .board import SQUARES
            nodes = sorted((x for x in SQUARES if SQUARES[x]["kind"] == "node"), key=lambda x: int(x.lstrip("n")))
            rows = chunks([(board.square_name(x)[:30], f"p:fcg:{x}") for x in nodes], 2)
            return await edit_or_send(q, "◦ شخصیت جعلی را کدام خانه بگذارم؟", rows + [back(lang, "p:fc")])
        actions.set_fake_pos(g, p, args[0])
        save()
        return await edit_or_send(q, f"👤 «{p['fake_char']}» رفت به {board.square_name(args[0])}.", [back(lang)])

    # ----- movement -----
    if head == "nodes":
        if p["pos"] is not None or g["locked"]:
            raise GameError("فقط برای اولین حرکت.")
        from .board import SQUARES
        nodes = sorted((x for x in SQUARES if SQUARES[x]["kind"] == "node"), key=lambda x: int(x.lstrip("n")))
        rows = chunks([(board.square_name(x)[:30], f"p:go:{x}") for x in nodes], 2)
        return await edit_or_send(q, "◦ خانه‌های خالی بین شهرها:", rows + [back(lang, "p:move")])
    if head == "move":
        if g["phase"] == "lobby":
            raise GameError("بازی هنوز شروع نشده.", "The game hasn't started yet.")
        if g["locked"]:
            raise GameError("نقشه تا فاز بعد قفل است.", "The map is locked until the next phase.")
        if p["moved"]:
            raise GameError("در این فاز حرکت کردی.", "You've already moved this phase.")
        if p["pos"] is None:
            return await mapview.send_city_pick(bot, p, "📍 اولین حرکت: هر جای نقشه، بدون تاس — یک شهر، یا «خانه‌های خالی» را بزن.",
                                                "", "p:go", first=True, destination=q.message.chat_id)
        if p["flags"].get("free_move"):
            return await mapview.send_city_pick(bot, p, "🗺 نقشه قاچاقچی: بدون تاس به هر شهری برو.", "🗺 Smuggler's chart: go to any city, no dice.", "p:go", destination=q.message.chat_id)
        if p["move_roll"] is None:
            msg = await bot.send_dice(q.message.chat_id, emoji="🎲")
            p["move_roll"] = msg.dice.value
            save()
            ctx.job_queue.run_once(job_after_roll, DICE_WAIT, data={"player_id": p["id"], "chat_id": q.message.chat_id, "cycle": g["cycle"], "phase": g["phase"]})
            return
        return await mapview.send_move_map(bot, p, destination=q.message.chat_id)
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
        ctx.job_queue.run_once(job_result, DICE_WAIT, data=(p["id"], *res, q.message.chat_id))
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
        unit = args[0]
        actions.buy_unit(g, p, unit)
        save()
        use = unit_use_rows(p, unit)
        text = f"✅ {unit_name(unit, 'fa')} خریدی. 💰 {num(p['coins'])} سکه مانده.\n" + UNIT_HELP[unit]
        return await edit_or_send(q, text, use + [[("🛒 فروشگاه", "p:shop"), ("🎒 کوله", "p:bag")], back(lang)])

    # ----- bag: items and units -----
    if head == "bag":
        return await edit_or_send(q, *bag_view(p, lang))
    if head == "rn":
        pool = g["balloons"] if args[0] == "balloon" else g["units_on_map"]
        obj = next((x for x in pool if x["id"] == args[1] and str(x["owner"]) == str(p["id"])), None)
        if not obj:
            raise GameError("پیدا نشد.")
        return await ask_name(q, p, args[0], obj, "✏️ تغییر اسم")
    if head == "iu":
        key = args[0]
        if key not in p["items"]:
            raise GameError("این آیتم رو نداری.", "You don't have that item.")
        if actions.item_needs_target(key):
            people = [x for x in alive_others(p, include_self=False)]
            return await edit_or_send(q, f"✨ {ITEMS[key]['fa']} — {ITEMS[key]['desc_fa']}\nروی کی استفاده‌اش کنی؟",
                                      people_rows(f"p:it:{key}", people, lang, back_to="p:bag"))
        msg = actions.use_item(g, p, key)
        save()
        if ITEMS[key]["effect"]["type"] == "reroll":
            msg += "\nتاس دوباره: «🎲 حرکت» رو بزن."
        text, rows = bag_view(p, lang)
        return await edit_or_send(q, msg + "\n\n" + text, rows)
    if head == "it":
        msg = actions.use_item(g, p, args[0], target=args[1])
        save()
        text, rows = bag_view(p, lang)
        return await edit_or_send(q, msg + "\n\n" + text, rows)
    if head == "up":
        unit = args[0]
        spots = actions.place_spots(g, p, unit) if len(args) < 2 else [args[1]]
        if not spots:
            raise GameError("باید روی یک خانه خالی " + ("دریایی" if unit == "ship" else "زمینی") +
                            " باشی یا در همین فاز از آن رد شده باشی.")
        if len(spots) > 1:
            rows = [[(board.square_name(x)[:40], f"p:up:{unit}:{x}")] for x in spots]
            return await edit_or_send(q, f"{unit_name(unit, 'fa')} را کجا بکارم؟ (جایی که هستی یا از آن رد شدی)", rows + [back(lang, "p:bag")])
        u = actions.place_unit(g, p, unit, spots[0])
        return await ask_name(q, p, "unit", u, f"✅ {unit_name(unit, 'fa')} در {board.square_name(spots[0])} مستقر شد.")
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
        if p["pos"] not in CITIES:
            raise GameError("جاده جدید را فقط از داخل یک شهر می‌شود کند.")
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
        b = actions.launch_balloon(g, p, args[0], args[1])
        if b["kind"] == "spy" and isinstance(b["result"], list):
            await ask_name(q, p, "balloon", b, f"🎈 بالن جاسوسی بالای {LOCATIONS[args[1]]['fa']} رفت و همین حالا گزارش می‌دهد.")
            await events.deliver_spy_now(bot, b)
            return
        if b["result"] == "await_pct":
            await ask_name(q, p, "balloon", b, f"🎈 بالن جنگی به سمت {LOCATIONS[args[1]]['fa']} رفت. همین حالا می‌توانی بمباران کنی.")
            await events.invite_war_balloons(bot)
            return
        return await ask_name(q, p, "balloon", b, f"🎈 بالن به سمت {LOCATIONS[args[1]]['fa']} رفت. نتیجه ساعت {num(LOCK_HOUR)}:۰۰.")

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

    if head == "dice":
        lst = g["acts"].get(str(p["id"]), [])
        i = int(args[0])
        if i >= len(lst) or lst[i].get("dice") or lst[i].get("dice_total"):
            raise GameError("تاس این اکت ریخته شده.")
        from .night_window import check_actions
        check_actions(g)
        pool = p.setdefault("night_dice", {"cycle": g["cycle"], "list": []})
        if pool.get("cycle") != g["cycle"]:
            pool.update({"cycle": g["cycle"], "list": []})
        k = sum(1 for a in lst if a.get("dice"))
        if k < len(pool["list"]):          # already thrown tonight: clearing the act doesn't give a new throw
            lst[i]["dice"] = list(pool["list"][k])
            save()
            d = lst[i]["dice"]
            return await edit_or_send(q, f"🎲 تاس این شب را قبلاً ریختی: {num(d[0])} + {num(d[1])} = {num(d[0] + d[1])} — همان حساب شد "
                                         f"برای «{act_name(lst[i]['type'], lang)}».", [[("🌙 اکت‌ها", "p:act")], back(lang)])
        d1 = await bot.send_dice(q.message.chat_id, emoji="🎲")
        d2 = await bot.send_dice(q.message.chat_id, emoji="🎲")
        lst[i]["dice"] = [d1.dice.value, d2.dice.value]
        pool["list"].append(lst[i]["dice"])
        save()
        text = (f"🎲 {num(d1.dice.value)} + {num(d2.dice.value)} = {num(d1.dice.value + d2.dice.value)} "
                f"برای «{act_name(lst[i]['type'], lang)}» ثبت شد.")
        ctx.job_queue.run_once(job_result_rows, DICE_WAIT, data=(p["id"], text, text, [[("🌙 اکت‌ها", "p:act")], back(lang)], q.message.chat_id))
        return
    if head == "wroll":
        actions.validate_wagram_roll(g, p)
        msg = await bot.send_dice(q.message.chat_id, emoji="🎲")
        two = actions.wagram_roll(g, p, msg.dice.value)
        save()
        text = (f"🎲 {num(msg.dice.value)} — " + ("زوج! امشب دو اکت داری. 🙏" if two else "فرد؛ امشب یک اکت."))
        ctx.job_queue.run_once(job_result, DICE_WAIT, data=(p["id"], text, text, q.message.chat_id))
        return
    if head == "nm":
        p["flags"].pop("naming", None)
        save()
        return await edit_or_send(q, "✅ اسم تصادفی ماند.", [back(lang)])

    # ----- night acts -----
    if head in ("act", "a", "t", "tg", "tb", "td", "bl", "bn", "bx", "acx"):
        return await act_flow(update, ctx, p, head, args)

    # ----- voting -----
    if head in ("vote", "v"):
        raise GameError("رأی فقط در گروه: بنویس #رای اسم", "Vote in the group: #رای name")
    # ----- place specials -----
    if head == "taxi":
        if not g["locked"] or p.get("night_pos") != "london":
            raise GameError("تاکسی فقط بعد از قفل نقشه و در لندن.", "The taxi only works after the lock, in London.")
        reach = actions.taxi_targets(g)
        if not reach:
            raise GameError("لندن کاملاً ویران شده؛ تاکسی کار نمی‌کند.")
        dmg = actions.damage(g, "london")
        note = f"\n🔥 لندن {num(dmg)}٪ ویران است؛ تاکسی فقط تا شعاع کمتری می‌رود." if dmg else ""
        return await mapview.send_city_pick(bot, p, "🚕 کجا بریم؟ (روی نقشه عمومی همچنان لندن نشون داده می‌شی)" + note,
                                            "", "p:tx", only=reach)
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
                                                                 "🎰 Three of a kind! Revive someone:", rows, chat_id))
        return
    if s["hit"]:
        res = (f"🎰 جک‌پات! همه قدرت‌ها و اچ‌پی +{num(s.get('change', 20))} — برای همیشه (حتی بعد از مرگ و زنده شدن).",
               "🎰 Jackpot! All powers and HP up — permanently.")
    elif s["done"]:
        vienna = s["kind"] == "vienna"
        res = ("🎰 تموم شد، سه‌تای یکسان نیامد." + (" همه قدرت‌ها −۲۰ برای همیشه (حتی بعد از مرگ و زنده شدن)." if vienna else ""),
               "🎰 Out of pulls, no three of a kind." + (" All powers −20 permanently." if vienna else ""))
    else:
        res = (f"🎰 نشد. {num(s['left'])} بار دیگه.", f"🎰 No luck. {s['left']} pulls left.")
    ctx.job_queue.run_once(job_result, DICE_WAIT, data=(p["id"], *res, chat_id))


def shop_view(p, lang):
    g = G()
    lines = [L(lang, f"🛒 خرید · 💰 {num(p['coins'])} سکه", f"🛒 Shop · 💰 {p['coins']} coins")]
    rows = []
    lines.append("قدرت‌ها دائمی‌اند (تا آخر بازی، هر بار +۱). عدد داخل پرانتز = قیمت.")
    btns = [(f"{stat_name(s, lang)} +1 دائمی ({num(price, lang)})", f"p:bp:{s}") for s, price in POWER_PRICES.items() if s != "hp"]
    rows += chunks(btns, 2)
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
    g_ = G()
    mine_b = [b for b in g_["balloons"] if str(b["owner"]) == str(p["id"]) and b["result"] in (None, "await_pct")]
    mine_u = [u for u in g_["units_on_map"] if str(u["owner"]) == str(p["id"])]
    if mine_b or mine_u:
        lines.append("\n📍 در راه / روی نقشه:")
        for b in mine_b:
            st = "منتظر بمباران (بعد از ساعت ۸)" if b["result"] is None else "آماده بمباران — مینی‌گیم را باز کن"
            lines.append(f"🎈 {'بالن جنگی' if b['kind'] == 'war' else 'بالن جاسوسی'} «{b.get('name') or '?'}» → {board.square_name(b['target'])} · {st}")
            rows.append([(f"✏️ اسم «{(b.get('name') or '?')[:14]}»", f"p:rn:balloon:{b['id']}")])
            if b["kind"] == "war" and b["result"] == "await_pct":
                from .events import balloon_url
                url = balloon_url(b)
                if url:
                    rows.append([("🎈 پرواز و بمباران", "webapp:" + url)])
        for u in mine_u:
            lines.append(f"{'💣' if u['kind'] == 'cannon' else '⛵'} «{u.get('name') or '?'}» · {board.square_name(u['square'])}")
            rows.append([(f"✏️ اسم «{(u.get('name') or '?')[:14]}»", f"p:rn:unit:{u['id']}")])
    eff = actions.active_effects(p)
    if eff:
        lines.append("\n⏳ اثرهای فعال: " + " · ".join(eff))
    if not p["items"]:
        lines.append("\nآیتمی نداری. آیتم با «🎯 دارت ← دارت آیتم» به دست می‌آید.")
    u = {k: v for k, v in p["units"].items() if v}
    if u:
        lines.append(L(lang, "\nواحدها: ", "\nUnits: ") + ", ".join(f"{unit_name(k, lang)}×{num(v, lang)}" for k, v in u.items()))
        if u.get("cannon"):
            rows.append([("💣 توپ: کاشتن (همین‌جا یا مسیرم)", "p:up:cannon"), (L(lang, "💣 توپ: خراب کردن جاده", "💣 Cannon: destroy road"), "p:us:cannon")])
        if u.get("ship"):
            rows.append([("⛵ کشتی: کاشتن (همین‌جا یا مسیرم)", "p:up:ship"), (L(lang, "⛵ کشتی: پاک کردن مین", "⛵ Ship: clear mine"), "p:us:ship")])
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

BASIC_ACTS = ("attack", "protect", "defuse", "spy")


def act_limit(p):
    base = 2 if (p.get("double_act") and "double_act_50" in flags_at(loc_of(p))) else 1
    if any(a["type"] == "steal" for a in G()["acts"].get(str(p["id"]), [])):
        base += 1   # the borrowed act
    if p["flags"].get("extra_act"):
        base += 1   # black coffee
    return base


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
        tag = f" (به‌جای {role_name(a['as_role'])})" if a.get("as_role") else ""
        dice = (f" · 🎲 {num(a['dice'][0])}+{num(a['dice'][1])}" if a.get("dice") else
                f" · 🎲 جمع {num(a['dice_total'])} (گاد)" if a.get("dice_total") else " · 🎲 تاس نریخته")
        out.append(f"• {act_name(a['type'], lang)}{tag} → {t}{dice}")
    return "\n".join(out)


def add_act(p, act):
    g = G()
    if g["phase"] != "night":
        raise GameError("اکت فقط در شب.", "Acts only at night.")
    from .night_window import check_actions
    check_actions(g)
    lst = g["acts"].setdefault(str(p["id"]), [])
    if len(lst) >= act_limit(p):
        raise GameError("به سقف اکت‌هات رسیدی؛ اول پاکشون کن.", "You've reached your act limit; clear first.")
    t = act["type"]
    if t == "attack" and "church" in LOCATIONS.get(loc_of(p) or "", {}).get("flags", []):
        raise GameError("در کلیسا نمی‌تونی حمله کنی.", "You can't attack from the church.")
    borrow = p["flags"].get("borrow")
    if borrow and t != "steal":
        act["as_role"] = borrow
        p["flags"].pop("borrow", None)
        p["flags"].pop("borrow_from", None)
    if t not in BASIC_ACTS and not act.get("as_role") and any(a["type"] not in BASIC_ACTS and not a.get("as_role") for a in lst):
        raise GameError("در یک شب فقط یک اکت ویژه می‌شود؛ اکت دوم خانقاه باید حمله، محافظت، خنثی یا جاسوسی باشد.")
    need = {"bomb": "bomb", "poison": "poison", "guess": "guess", "cult_check": "cult_check"}.get(t)
    if need and not act.get("as_role") and p["charges"].get(need, 0) < 1:
        raise GameError("شارژ این توانایی تموم شده.", "That ability is used up.")
    if t == "convert" and p.get("no_recruit_until", 0) >= g["cycle"]:
        raise GameError("امشب نمی‌تونی عضو بگیری.", "You can't recruit tonight.")
    lst.append(act)
    save()


async def act_done(q, p, lang):
    lst = G()["acts"].get(str(p["id"]), [])
    rows = dice_rows(p)
    note = "\n\n🎲 حالا تاس‌های اکتت را بریز: قدرت اکت = جمع ۲ تاس + استت تو. (اگر نریزی، ربات موقع محاسبه می‌ریزد.)" if rows else ""
    await edit_or_send(q, "✅ " + acts_text(p, lang) + note, rows + [[("🌙 اکت‌ها", "p:act")], back(lang)])


async def act_flow(update, ctx, p, head, args):
    q = update.callback_query
    g = G()
    lang = p["lang"]
    if g["phase"] != "night":
        raise GameError("اکت فقط در شب.", "Acts only at night.")
    if head == "act":
        borrow = p["flags"].get("borrow")
        if borrow:
            types = ["attack", "protect", "defuse", "spy"] + [t for t in SPECIALS.get(borrow, []) if t != "steal"]
            rows = chunks([(act_name(t, lang), f"p:a:{t}") for t in types], 2)
            victim = p["flags"].get("borrow_from", "")
            warn = "\n⚠️ او جاسوس است — دزدی از جاسوس یعنی مرگ دزد!" if borrow == "spy" else ""
            text = (f"🦹 دزدی ثبت شد. نقش {victim}: {role_name(borrow)}{warn}\n\n"
                    f"حالا به‌جای {role_name(borrow)} یک اکت انتخاب کن.\n"
                    f"این اکت با استت‌های {role_name(borrow)} انجام می‌شود (و فقط همین اکت قابل خنثی شدن است).")
            return await edit_or_send(q, text, dice_rows(p) + rows + [[("🗑 لغو دزدی", "p:acx")], back(lang)])
        types = ["attack", "protect", "defuse", "spy"] + SPECIALS.get(p["role"], [])
        rows = chunks([(act_name(t, lang), f"p:a:{t}") for t in types], 2)
        if g["acts"].get(str(p["id"])):
            rows.append([(L(lang, "🗑 پاک کردن اکت‌ها", "🗑 Clear my acts"), "p:acx")])
        lim = L(lang, f"\n\nامشب {num(act_limit(p))} اکت داری. قدرت هر اکت = ۲ تاس + استت تو.",
                f"\n\nYou have {act_limit(p)} act(s) tonight. Power = 2 dice + your stat.")
        return await edit_or_send(q, acts_text(p, lang) + lim, dice_rows(p) + rows + [back(lang)])
    if head == "acx":
        g["acts"].pop(str(p["id"]), None)
        p["flags"].pop("borrow", None)
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
                                  people_rows(f"p:t:{t}", alive_others(p, include_self=True), lang, "p:act"))
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
        if t == "steal":
            T = pl(tid)
            if T["pos"] == "wagram":
                raise GameError("او در خانقاه است؛ از کسی که در خانقاه است نمی‌شود دزدید.")
            add_act(p, {"type": "steal", "target": tid, "extra": {}})
            p["flags"]["borrow"] = T["role"]
            p["flags"]["borrow_from"] = T["name"]
            save()
            return await act_flow(update, ctx, p, "act", [])
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
        rows = [[(pl(x)["name"], f"p:bx:{x}")] for x in sel if str(x) != str(p["id"])] if p["charges"].get("war_bullet", 0) > 0 else []
        rows.append([(L(lang, "بدون تیر جنگی", "No war bullet"), "p:bx:0")])
        return await edit_or_send(q, L(lang, f"تیر جنگی به کی؟ (باقی‌مانده: {num(p['charges'].get('war_bullet', 0))})",
                                       f"War bullet to whom? (left: {p['charges'].get('war_bullet', 0)})"), rows)
    if head == "bx":
        sel = ctx.user_data.get("bul", [])
        if args[0] != "0" and str(args[0]) == str(p["id"]):
            raise GameError("تیر جنگی را نمی‌توانی به خودت بدهی.")
        add_act(p, {"type": "bullets", "target": None, "extra": {"targets": sel, "war": None if args[0] == "0" else args[0]}})
        ctx.user_data["bul"] = []
        return await act_done(q, p, lang)


def bullet_view(p, ctx, lang):
    sel = ctx.user_data.get("bul", [])
    btns = [(("✅ " if str(x["id"]) in sel else "") + x["name"][:22], f"p:bl:{x['id']}") for x in alive_others(p, include_self=True)]
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


UNIT_HELP = {
    "spy_balloon": "🎈 بالن جاسوسی: یک شهر انتخاب کن؛ ساعت ۲۰ می‌گوید چه کسانی آنجا هستند.",
    "war_balloon": "🎈 بالن جنگی: یک شهر انتخاب کن؛ ساعت ۲۰ بمباران می‌شود (درصد تخریب با مینی‌گیم).",
    "cannon": "💣 توپ: روی یک خانه زمینی بین شهرها بکار (عوارض می‌گیرد) یا یک جاده متصل را خراب کن.",
    "ship": "⛵ کشتی: روی یک خانه دریایی بکار (عوارض می‌گیرد) یا مین یک مسیر دریایی را پاک کن.",
    "mine": "🌊 مین: یک مسیر دریایی متصل به خانه‌ات را ببند.",
    "shovel": "⛏ بیل: جاده خراب را تعمیر کن یا جاده جدید بساز.",
}


def unit_use_rows(p, unit):
    """The buttons that use a unit right away (shown after buying, and in the bag)."""
    if unit in ("spy_balloon", "war_balloon"):
        kind = unit.split("_")[0]
        return chunks([(LOCATIONS[c]["fa"][:22], f"p:ubt:{kind}:{c}") for c in CITIES], 2)
    if unit == "cannon":
        return [[("💣 کاشتن (همین‌جا یا مسیرم)", "p:up:cannon"), ("💣 خراب کردن جاده", "p:us:cannon")]]
    if unit == "ship":
        return [[("⛵ کاشتن (همین‌جا یا مسیرم)", "p:up:ship"), ("⛵ پاک کردن مین", "p:us:ship")]]
    if unit == "mine":
        return [[("🌊 بستن مسیر دریایی", "p:us:mine")]]
    if unit == "shovel":
        return [[("⛏ تعمیر جاده", "p:us:shovel"), ("⛏ جاده جدید", "p:ud")]]
    return []


async def ask_name(q, p, kind, obj, done_text):
    """Units and balloons are known by the name their owner gives them — never by the owner's name."""
    p["flags"]["naming"] = {"kind": kind, "id": obj["id"]}
    save()
    what = "بالن" if kind == "balloon" else unit_name(obj["kind"], "fa")
    text = (done_text + f"\n\n✍️ یک اسم برای این {what} بنویس و همین‌جا بفرست (تا ۲۴ حرف).\n"
            f"همه آن را با این اسم می‌بینند، نه با اسم تو. اسم فعلی: «{obj['name']}»")
    await edit_or_send(q, text, [[("🎲 همین اسم بماند", "p:nm:keep")], back("fa")])


async def on_private_text(update, ctx):
    """A player typing a name for a unit or balloon they just placed or launched."""
    if update.effective_chat.type != "private" or not update.message or not update.message.text:
        return
    from .gm_ui import on_gm_text
    if await on_gm_text(update, ctx):
        return
    p = pl(acting_uid(update.effective_user.id))
    if not p:
        return
    naming = p["flags"].get("naming")
    if not naming:
        return
    try:
        obj = actions.rename(G(), p, naming["kind"], naming["id"], update.message.text)
    except GameError as e:
        await update.message.reply_text(e.text("fa"))
        return
    p["flags"].pop("naming", None)
    save()
    await update.message.reply_text(f"✅ اسمش شد «{obj['name']}».", reply_markup=kb(home_rows(p)))
