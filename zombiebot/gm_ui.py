"""The GM's control room: one screen with the next step, and sub-screens that always lead back."""
import random

from telegram.error import TelegramError

from . import actions, autopilot, board, events, mapview, votes
from .actions import GameError
from .board import CITIES, SQUARES
from .common import (G, save, store, pl, kb, chunks, dm, group, to_gms, gm_notes, lang_of, num, phase_label,
                     lock_eta, edit_or_send, is_gm, playing_as, logger, LOCK_HOUR, split_text, gm_ids)
from .data.items import ITEMS
from .data.locations import LOCATIONS
from .data.roles import ROLES, role_name
from .engine import resolve_night
from .state import new_game, new_player, assign_role, alive_players, roster, find_player, give_characters, needs_fake_char, char_of
from .texts import L, bi, role_card

PAGE = 8

# ---------------- test players ----------------

TEST_PEOPLE = [("مریم", "maryam"), ("علی", "ali"), ("سارا", "sara"), ("رضا", "reza"), ("نگار", "negar"), ("کیان", "kian"),
               ("لیلا", "leila"), ("امیر", "amir"), ("شیرین", "shirin"), ("بهرام", "bahram"), ("پریسا", "parisa"),
               ("داریوش", "dariush"), ("نازنین", "nazanin"), ("سیاوش", "siavash"), ("مهسا", "mahsa"), ("کاوه", "kaveh"),
               ("یاسمن", "yasaman"), ("آرش", "arash"), ("ترانه", "taraneh"), ("فرهاد", "farhad"), ("گلناز", "golnaz"),
               ("بابک", "babak"), ("رویا", "roya"), ("جمشید", "jamshid")]
TEST_ROLES = ["godfather", "zombie", "zombie", "zombie_doctor", "undead", "bomber", "yakuza",
              "clown", "cultist", "thief",
              "hero", "priest", "priest", "doctor", "spy", "saboteur", "apothecary", "sniper",
              "cult_hunter", "musketeer", "judge", "doctor", "saboteur", "priest"]
VOTE_GAP = 5.0   # seconds between test players' group votes: Telegram allows ~20 group messages a minute,
                 # and flooding it freezes the bot for minutes


def test_players(g=None):
    g = g or G()
    return [p for p in g["players"].values() if p.get("fake")]


def autopilots(g=None):
    return autopilot.autopilots(g)


def make_test_game(gm_uid):
    """24 named test players with a full role spread, each in a random city."""
    g = G()
    for pid in [k for k, v in g["players"].items() if v.get("fake")]:
        g["players"].pop(pid)
    g.setdefault("as", {}).pop(str(gm_uid), None)
    roles = TEST_ROLES[:]
    random.shuffle(roles)
    cities = list(CITIES)
    for i, ((name, user), role) in enumerate(zip(TEST_PEOPLE, roles)):
        uid = -(i + 1)
        P = new_player(uid, name, user)
        P["fake"] = True
        P["lang"] = lang_of(gm_uid)
        assign_role(P, role)
        if role == "godfather":
            P["fake_role"] = "doctor"
        P["pos"] = random.choice(cities)
        g["players"][str(uid)] = P
    give_characters(g)
    for P in g["players"].values():
        if P.get("fake") and needs_fake_char(P):
            P["fake_pos"] = random.choice(cities)
    g["test_mode"] = True
    save()


def autoplay_actions():
    """Everything the autopilot test players do at the start of a phase (moves, darts, shop, items, units,
    balloons, acts). Votes are posted separately, one by one."""
    return autopilot.play_phase()


def schedule_test_votes(job_queue, then=None):
    """Each autopilot test player votes in the group, one every few seconds; the tally follows."""
    g = G()
    voters = [p for p in autopilots(g) if not g["votes"].get(str(p["id"]))]
    random.shuffle(voters)
    for i, p in enumerate(voters):
        job_queue.run_once(job_test_vote, 2 + i * VOTE_GAP, data=p["id"])
    job_queue.run_once(job_post_tally, 3 + len(voters) * VOTE_GAP, data=then)
    return len(voters)


async def job_test_vote(ctx):
    g = G()
    p = pl(ctx.job.data)
    if not p or not p["alive"] or g["phase"] != "day" or g["votes"].get(str(p["id"])) or not autopilot.is_auto(p):
        return
    if g.get("closed_cycle") == g["cycle"] or (g.get("judgement") or {}).get("cycle") == g["cycle"]:
        return
    others = sorted((x for x in alive_players(g) if x["id"] != p["id"]), key=lambda x: str(x["id"]))
    if not others:
        return
    # the whole table leans towards the same few people each day, so a test day has a clear leader
    random.Random(g["cycle"]).shuffle(others)
    weights = [10, 6, 3] + [1] * max(0, len(others) - 3)
    for _ in range(3):
        target = random.choices(others, weights=weights[:len(others)])[0]
        status, _extra = await votes.vote_from_menu(ctx.bot, p, target, gif=g.get("test_gifs", True))
        if status != "lightning":   # struck by lightning: the vote didn't count, so pick someone else
            break


async def job_post_tally(ctx):
    g = G()
    if g["phase"] == "day" and g["group_id"]:
        await ctx.bot.send_message(g["group_id"], "#رایگیری\n\n" + votes.tally_text())
    if ctx.job.data:
        await ctx.job.data(ctx)


# ---------------- phases ----------------

async def do_phase(bot, phase, job_queue=None):
    g = G()
    store.backup()
    if phase == "night":
        await events.resolve_poisons(bot)
        for d in g["duels"]:
            if d["status"] in ("pending", "live"):
                d["status"] = "expired"
    actions.start_phase(g, phase)
    save()
    if phase == "night":
        await group(bot, f"🌙 شب {num(g['cycle'])} آغاز شد. تا ساعت {num(LOCK_HOUR)}:۰۰ مکانت رو انتخاب کن؛ اکت‌ها از منوی ربات.",
                    f"🌙 Night {g['cycle']} begins. Pick your place before {LOCK_HOUR}:00; acts from the bot menu.")
    else:
        await group(bot, f"☀️ روز {num(g['cycle'])} آغاز شد. رأی بدهید: #رای اسم  ·  نتیجه: #رایگیری",
                    f"☀️ Day {g['cycle']} begins. Vote with: #رای name  ·  results: #رایگیری")
    from .player_ui import home_rows, home_text
    for p in alive_players(g):
        await dm(bot, p["id"], home_text(p), home_text(p), reply_markup=kb(home_rows(p)))
    if g.get("test_mode"):
        done = autoplay_actions()
        notes = [(f"🤖 بازیکن‌های تست: {num(done['moves'])} حرکت، {num(done['acts'])} اکت، {num(done['buys'])} خرید، "
                  f"{num(done['items'])} آیتم، {num(done['balloons'])} بالن، {num(done['units'])} کار با واحدها.", "")]
        if phase == "day":
            await autopilot.day_shots(bot)
        await autopilot.decide_pending(bot)
        if phase == "day" and job_queue is not None and g["group_id"]:
            n = schedule_test_votes(job_queue)
            notes.append((f"🗳 {num(n)} بازیکن تست در گروه رأی می‌دهند (حدود {num(int(n * VOTE_GAP))} ثانیه)، بعد نتیجه اعلام می‌شود.",
                          f"🗳 {n} test players are voting in the group (about {int(n * VOTE_GAP)}s), then the results are posted."))
        await gm_notes(bot, notes)


async def do_lock(bot):
    g = G()
    if g["phase"] == "lobby" or g["locked"]:
        return
    summary = actions.lock_map(g)
    save()
    for pid, fa, en in summary["private"]:
        await dm(bot, pid, fa, en)
    for b in g["balloons"]:
        if b["kind"] != "spy" or b["cycle"] != g["cycle"] or b.get("phase") != g["phase"] or b.get("delivered"):
            continue
        b["delivered"] = True
        names = ", ".join(b["result"]) or "—"
        lang = lang_of(b["owner"])
        text_fa = f"🎈 بالن جاسوسی بر فراز {board.square_name(b['target'])}: {names}"
        text_en = f"🎈 Spy balloon over {board.square_name(b['target'], 'en')}: {names}"
        if b["publish"] is None:
            await dm(bot, b["owner"], text_fa + "\nمنتشر بشه؟", text_en + "\nPublish it?",
                     reply_markup=kb([[(L(lang, "📢 انتشار", "📢 Publish"), f"x:pub:{b['id']}:1"), (L(lang, "🤫 نگه دار", "🤫 Keep"), f"x:pub:{b['id']}:0")]]))
        else:
            await dm(bot, b["owner"], text_fa, text_en)
    save()
    await mapview.post_public_map(bot)
    for b in g["balloons"]:
        if b["publish"] and b.get("delivered") and not b.get("published"):
            b["published"] = True
            await events.publish_balloon(bot, b)
    save()
    notes = list(summary["gm_notes"])
    if g.get("test_mode"):
        notes += [(n, "") for n in autopilot.after_lock()]
        await autopilot.decide_pending(bot)
    wb = [b for b in g["balloons"] if b["result"] == "await_pct"]
    fights = [f for f in g["battles"] if f["status"] == "open"]
    if wb or fights:
        notes.append((f"🎈 {num(len(wb))} بالن جنگی و ⚔️ {num(len(fights))} نبرد منتظر نتیجه‌اند: اتاق فرمان ← بالن و نبرد",
                      f"🎈 {len(wb)} war balloon(s) and ⚔️ {len(fights)} battle(s) need results: control room → Balloons"))
    await gm_notes(bot, [("🔒 نقشه قفل شد و نقشه عمومی منتشر شد.", "🔒 Map locked and the public map posted.")] + notes)


# ---------------- the next step ----------------

def next_step(g):
    """(action, label_fa, label_en, hint_fa, hint_en)"""
    with_role = [p for p in g["players"].values() if p.get("role")]
    if g["phase"] == "lobby":
        if not with_role:
            return ("players", "👥 اول بازیکن‌ها و نقش‌ها", "👥 Players and roles first",
                    "هنوز کسی نقش ندارد. بازیکن‌ها /start بزنند و از «بازیکنان» نقش بده — یا از «آزمایشگاه» یک بازی تست بساز.",
                    "Nobody has a role yet. Players send /start and you give roles under Players — or build a test game in the Test lab.")
        return ("night", "🌙 شروع شب ۱", "🌙 Start night 1", "همه آماده‌اند؟ شب اول شروع می‌شود.", "Everyone ready? This starts night 1.")
    c = g["cycle"]
    if g["phase"] == "night":
        if g.get("pending"):
            return ("results", "📜 بررسی و اعمال نتایج شب", "📜 Review and apply the night",
                    "نتایج محاسبه شده؛ ببین، اگر لازم است چیزی را خاموش کن، بعد اعمال کن.", "Results are ready: check them, switch off anything, then apply.")
        if g.get("applied_cycle") == c:
            return ("day", f"☀️ شروع روز {num(c)}", f"☀️ Start day {c}", "شب تمام شد. داستان را با /story بنویس و روز را شروع کن.",
                    "The night is done. Post the story with /story, then start the day.")
        if not g["locked"]:
            return ("lock", "🔒 قفل نقشه (همین الان)", "🔒 Lock the map now",
                    f"نقشه خودکار {lock_eta('fa')} قفل می‌شود؛ یا همین الان قفلش کن.", f"The map locks automatically {lock_eta('en')}, or lock it now.")
        return ("resolve", "🧮 محاسبه شب", "🧮 Resolve the night", "نقشه قفل است. وقتی اکت‌ها رسید، شب را محاسبه کن.",
                "The map is locked. When the acts are in, resolve the night.")
    jd = g.get("judgement") or {}
    if jd.get("cycle") == c and jd.get("status") == "waiting" and g.get("closed_cycle") != c:
        return ("votes", "⚖️ منتظر حکم قاضی", "", f"پرونده دست قاضی ({pl(jd['judge'])['name']}) است. می‌توانی منتظر بمانی یا حکم پیش‌فرض را اجرا کنی.", "")
    if g.get("closed_cycle") == c:
        return ("night", f"🌙 شروع شب {num(c + 1)}", f"🌙 Start night {c + 1}", "رأی‌گیری بسته شد. شب بعد را شروع کن.", "Voting is closed. Start the next night.")
    return ("votes", "🗳 بستن رأی‌گیری", "", "رأی‌ها را ببین؛ با بستن رأی‌گیری نتیجه واقعی اعلام می‌شود و پرونده به قاضی می‌رود "
            "(اگر قاضی نباشد: نفر اول اعدام می‌شود و در تساوی همه).", "")


def control_text(uid):
    g = G()
    lang = lang_of(uid)
    alive = alive_players(g)
    total = [p for p in g["players"].values() if p.get("role")]
    lines = [L(lang, f"👑 اتاق فرمان — {phase_label('fa', g)}", f"👑 Control room — {phase_label('en', g)}")]
    if g.get("test_mode"):
        lines[0] += L(lang, "  🧪 حالت تست سریع", "  🧪 fast test mode")
    if g["phase"] != "lobby":
        lines.append(L(lang, "🔒 نقشه قفل است" if g["locked"] else f"🔓 نقشه باز {lock_eta('fa')}",
                       "🔒 map locked" if g["locked"] else f"🔓 map open {lock_eta('en')}"))
    lines.append(L(lang, f"👥 زنده {num(len(alive))} از {num(len(total))} · ثبت‌نام {num(len(g['players']))}",
                   f"👥 alive {len(alive)} of {len(total)} · registered {len(g['players'])}"))
    if g["phase"] == "night":
        moved = sum(1 for p in alive if p["moved"])
        acted = sum(1 for p in alive if g["acts"].get(str(p["id"])))
        lines.append(L(lang, f"🎲 حرکت کرده {num(moved)} · 🌙 اکت داده {num(acted)} از {num(len(alive))}",
                       f"🎲 moved {moved} · 🌙 acted {acted} of {len(alive)}"))
    elif g["phase"] == "day":
        voted = sum(1 for p in alive if g["votes"].get(str(p["id"])))
        lines.append(L(lang, f"🗳 رأی داده {num(voted)} از {num(len(alive))}", f"🗳 voted {voted} of {len(alive)}"))
    wb = [b for b in g["balloons"] if b["result"] == "await_pct"]
    fights = [f for f in g["battles"] if f["status"] == "open"]
    if wb or fights:
        lines.append(L(lang, f"🎈 منتظر نتیجه: {num(len(wb))} بالن جنگی · {num(len(fights))} نبرد",
                       f"🎈 waiting: {len(wb)} war balloon(s) · {len(fights)} battle(s)"))
    if not g["group_id"]:
        lines.append(L(lang, "⚠️ گروه بازی تنظیم نشده (تنظیمات).", "⚠️ No game group yet (Setup)."))
    me = playing_as(uid)
    if me:
        lines.append(L(lang, f"🕹 الان به‌جای {me['name']} بازی می‌کنی.", f"🕹 You're playing as {me['name']}."))
    action, lfa, len_, hfa, hen = next_step(g)
    lines += ["", L(lang, "➡️ قدم بعدی: ", "➡️ Next step: ") + L(lang, lfa, len_), L(lang, hfa, hen)]
    return "\n".join(lines)


def control_rows(uid):
    g = G()
    lang = lang_of(uid)
    action, lfa, len_, _, _ = next_step(g)
    rows = [[("➡️ " + L(lang, lfa, len_), "g:next")],
            [(L(lang, "👥 بازیکنان", "👥 Players"), "g:players:0"), (L(lang, "🗺 نقشه", "🗺 Map"), "g:map")],
            [(L(lang, "🌙 اکت‌ها", "🌙 Acts"), "g:acts"), (L(lang, "🗳 رأی‌ها", "🗳 Votes"), "g:votes")],
            [(L(lang, "🎈 بالن و نبرد", "🎈 Balloons & battles"), "g:bal"), (L(lang, "🧪 آزمایشگاه", "🧪 Test lab"), "g:lab")],
            [(L(lang, "⚙️ تنظیمات", "⚙️ Setup"), "g:setup"), (L(lang, "🔄 تازه کن", "🔄 Refresh"), "g:home")]]
    if g.get("test_mode") and g["phase"] != "lobby":
        rows.insert(1, [(L(lang, "⏩ اجرای خودکار تا شب بعد", "⏩ Auto-run to the next night"), "g:ff")])
    if playing_as(uid):
        rows.insert(1, [(L(lang, f"🕹 منوی {playing_as(uid)['name']}", f"🕹 {playing_as(uid)['name']}'s menu"), "p:home"),
                        (L(lang, "👑 برگشت به گاد", "👑 Back to GM"), "g:asoff")])
    return rows


async def send_control_room(bot, uid, q=None):
    if q:
        await edit_or_send(q, control_text(uid), control_rows(uid))
    else:
        await bot.send_message(uid, control_text(uid), reply_markup=kb(control_rows(uid)))


def home_btn(lang):
    return [(L(lang, "👑 اتاق فرمان", "👑 Control room"), "g:home")]


# ---------------- screens ----------------

def player_label(p, lang):
    icon = "☠️" if not p["alive"] else ("🧪" if p.get("fake") else "🧍")
    role = role_name(p["role"], lang) if p.get("role") else L(lang, "بدون نقش", "no role")
    char = f" · 🎭{p['char']}" if p.get("char") else ""
    return f"{icon} {p['name']} · {role}{char} · ❤️{num(p['hp'], lang)}"


def players_screen(lang, page):
    people = roster(G())
    pages = max(1, (len(people) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = people[page * PAGE:(page + 1) * PAGE]
    no_role = sum(1 for p in people if not p.get("role"))
    text = L(lang, f"👥 بازیکنان ({num(len(people))}) — روی هر کس بزن تا کارتش باز شود.",
             f"👥 Players ({len(people)}) — tap someone to open their card.")
    if no_role:
        text += L(lang, f"\n⚠️ {num(no_role)} نفر هنوز نقش ندارند.", f"\n⚠️ {no_role} without a role.")
    if not people:
        text += L(lang, "\nهنوز کسی نیست. بازیکن‌ها باید به ربات /start بزنند.", "\nNobody yet. Players need to send /start to the bot.")
    rows = [[(player_label(p, lang)[:40], f"g:pl:{p['id']}")] for p in chunk]
    nav = []
    if page > 0:
        nav.append(("◀️", f"g:players:{page - 1}"))
    if pages > 1:
        nav.append((f"{num(page + 1, lang)}/{num(pages, lang)}", f"g:players:{page}"))
    if page < pages - 1:
        nav.append(("▶️", f"g:players:{page + 1}"))
    rows.append(nav)
    if no_role:
        rows.append([(L(lang, "🎲 نقش تصادفی برای بی‌نقش‌ها", "🎲 Random roles for the rest"), "g:rnd")])
    rows.append(home_btn(lang))
    return text, rows


def player_card(p, lang):
    g = G()
    lines = [player_label(p, lang), f"💰 {num(p['coins'], lang)} · 📍 {board.square_name(p['pos'], lang) if p['pos'] else '—'}"]
    if p.get("username"):
        lines.append(f"@{p['username']}")
    if p.get("char"):
        lines.append(f"🎭 شخصیت: {p['char']}")
    if p.get("fake_char"):
        lines.append(f"🃏 شخصیت جعلی: {p['fake_char']} · 📍 {board.square_name(p['fake_pos']) if p.get('fake_pos') else '—'}")
    if p.get("role") == "godfather":
        lines.append(f"🃏 نقش جعلی: {role_name(p['fake_role']) if p.get('fake_role') else '—'}")
    if p.get("nicks"):
        lines.append(L(lang, "لقب‌ها: ", "Nicknames: ") + ", ".join(p["nicks"]))
    if p["cult"]:
        lines.append(L(lang, "🕯 عضو فرقه", "🕯 cult member"))
    if p["items"]:
        lines.append(L(lang, "آیتم‌ها: ", "Items: ") + ", ".join(ITEMS[i][lang] for i in p["items"]))
    u = {k: v for k, v in p["units"].items() if v}
    if u:
        lines.append(L(lang, "واحدها: ", "Units: ") + ", ".join(f"{k}×{v}" for k, v in u.items()))
    acts = g["acts"].get(str(p["id"]), [])
    if acts:
        lines.append(L(lang, "اکت امشب: ", "Tonight's act: ") + ", ".join(
            f"{a['type']}→{pl(a['target'])['name'] if a.get('target') and pl(a['target']) else '-'}" for a in acts))
    v = g["votes"].get(str(p["id"]))
    if v and pl(v):
        lines.append(L(lang, f"رأی امروز: {pl(v)['name']}", f"Today's vote: {pl(v)['name']}"))
    pid = p["id"]
    rows = [
        [(L(lang, "🎴 نقش", "🎴 Role"), f"g:role:{pid}"), (L(lang, "📍 جابه‌جا کن", "📍 Move"), f"g:mv:{pid}")],
        [("❤️ −5", f"g:hp:{pid}:-5"), ("❤️ +5", f"g:hp:{pid}:5"), ("💰 −5", f"g:co:{pid}:-5"), ("💰 +5", f"g:co:{pid}:5")],
        [(L(lang, "🎁 دادن آیتم", "🎁 Give item"), f"g:give:{pid}"),
         (L(lang, "🕯 فرقه ✓/✗", "🕯 Cult ✓/✗"), f"g:cult:{pid}")],
        [(L(lang, "☠️ کشتن", "☠️ Kill"), f"g:kill:{pid}") if p["alive"] else (L(lang, "🧍 زنده کردن", "🧍 Revive"), f"g:rev:{pid}"),
         (L(lang, "🕹 بازی به‌جای او", "🕹 Play as them"), f"g:as:{pid}")],
        [("🎭 اسم شخصیت", f"g:chn:{pid}:char")] + ([("🃏 اسم شخصیت جعلی", f"g:chn:{pid}:fake_char")] if needs_fake_char(p) else []),
        [("🚫 اخراج از ربات", f"g:kick:{pid}")],
    ]
    if g["acts"].get(str(pid)):
        rows.append([(L(lang, "🗑 پاک کردن اکتش", "🗑 Clear their act"), f"g:actclr:{pid}")])
    if v:
        rows.append([(L(lang, "🗑 پاک کردن رأیش", "🗑 Remove their vote"), f"g:vd:{pid}")])
    rows.append([(L(lang, "↩️ لیست بازیکنان", "↩️ Players"), "g:players:0")] + home_btn(lang))
    lines.append(L(lang, "\nلقب برای #رای: /nick اسم لقب", "\nNickname for #رای: /nick name nickname"))
    return "\n".join(lines), rows


def acts_screen(lang):
    g = G()
    alive = alive_players(g)
    lines = [L(lang, f"🌙 اکت‌های {phase_label('fa', g)}", f"🌙 Acts — {phase_label('en', g)}"), ""]
    for p in alive:
        for a in g["acts"].get(str(p["id"]), []):
            t = pl(a.get("target"))["name"] if a.get("target") and pl(a.get("target")) else ""
            extra = a.get("extra") or {}
            if a["type"] == "bullets":
                t = ", ".join(pl(x)["name"] for x in extra.get("targets", []) if pl(x))
            lines.append(f"• {p['name']} ({role_name(p['role'], lang)}) → {a['type']} {t}")
    missing = [p["name"] for p in alive if not g["acts"].get(str(p["id"]))]
    if g["phase"] != "night":
        lines.append(L(lang, "اکت‌ها فقط در شب.", "Acts happen at night."))
    elif missing:
        lines += ["", L(lang, f"⬜ هنوز اکت نداده‌اند ({num(len(missing))}): ", f"⬜ No act yet ({len(missing)}): ") + "، ".join(missing)]
    rows = []
    if g["phase"] == "night" and not g.get("pending") and g.get("applied_cycle") != g["cycle"]:
        rows.append([(L(lang, "🧮 محاسبه شب", "🧮 Resolve the night"), "g:resolve")])
    rows.append(home_btn(lang))
    return "\n".join(lines), rows


def results_text(res, lang):
    lines = [f"📜 نتیجه شب {num(res['cycle'])} — هنوز اعمال نشده.",
             "(جزئیات هر اکت در گزارش بالا.) روی شماره هر مورد بزن تا خاموش/روشن شود، بعد «اعمال».", ""]
    for e in res["effects"]:
        lines.append(f"{'✅' if e['on'] else '❌'} {num(e['id'], lang)}. {e[lang]}")
    if not res["effects"]:
        lines.append(L(lang, "— اتفاقی نیفتاد —", "— nothing happened —"))
    return "\n".join(lines)[:4000]


def results_rows(res, lang):
    btns = [(f"{'✅' if e['on'] else '❌'}{num(e['id'], lang)}", f"g:ef:{e['id']}") for e in res["effects"]]
    rows = chunks(btns, 5)
    rows.append([(L(lang, "✔️ اعمال و اعلام", "✔️ Apply and announce"), "g:apply")])
    rows.append([(L(lang, "🎲 تاس دوباره", "🎲 Re-roll"), "g:resolve"), ("📋 گزارش کامل دوباره", "g:details")])
    rows.append(home_btn(lang))
    return rows


def votes_screen(lang):
    g = G()
    text = votes.tally_text()
    rows = []
    jd = g.get("judgement") or {}
    closed = g.get("closed_cycle") == g["cycle"]
    if g["phase"] == "day" and not closed and jd.get("cycle") == g["cycle"] and jd.get("status") == "waiting":
        names = "، ".join(pl(c)["name"] for c in jd["cands"])
        text = (events.final_results_text() + f"\n\n⚖️ منتظر حکم قاضی ({pl(jd['judge'])['name']}) درباره: {names}\n"
                "حکم پیش‌فرض: یک نفر → اعدام، تساوی → همه اعدام.")
        rows.append([("⚖️ اجرای حکم پیش‌فرض همین الان", "g:jdef")])
        rows.append([("🕊 هیچ‌کس اعدام نشود (حکم گاد)", "g:noex")])
    elif g["phase"] == "day" and not closed:
        missing = votes.not_voted()
        if missing:
            text += f"\n\n⬜ هنوز رأی نداده‌اند ({num(len(missing))}): " + "، ".join(p["name"] for p in missing)
        cands = events.gallows()
        if cands:
            J = events.judge_for(cands)
            names = "، ".join(pl(c)["name"] for c in cands)
            text += f"\n\nبا قوانین فعلی بالای دار: {names}\n" + (
                f"⚖️ قاضی ({J['name']}) تصمیم می‌گیرد ({num(events.JUDGE_HOURS)} ساعت)." if J else
                ("قاضی نداریم → " + ("همه اعدام می‌شوند." if len(cands) > 1 else "اعدام می‌شود.")))
        rows.append([("🔒 بستن رأی‌گیری و اعلام نتیجه", "g:vclose")])
        if g["votes"]:
            rows.append([("🗑 حذف یک رأی", "g:vdel"), ("🧹 پاک کردن همه", "g:vclr")])
        if g["group_id"]:
            rows.append([("📢 اعلام رأی‌های تا این لحظه در گروه", "g:vpost")])
    elif closed:
        text = events.final_results_text() + "\n\n✅ رأی‌گیری امروز تمام شده."
    rows.append(home_btn(lang))
    return text, rows


def balloons_screen(lang):
    g = G()
    lines = [L(lang, "🎈 بالن‌ها و نبردها", "🎈 Balloons & battles"), ""]
    rows = []
    for b in g["balloons"]:
        if b["kind"] == "war" and b["result"] == "await_pct":
            lines.append(L(lang, f"💣 بالن جنگی {pl(b['owner'])['name']} بر فراز {board.square_name(b['target'])}: درصد تخریب در مینی‌گیم؟",
                           f"💣 {pl(b['owner'])['name']}'s war balloon over {board.square_name(b['target'], 'en')}: % destroyed in the minigame?"))
            rows.append([(f"{num(x, lang)}٪" if lang == "fa" else f"{x}%", f"g:wb:{b['id']}:{x}") for x in (0, 20, 40, 60, 80, 100)])
    for f in g["battles"]:
        if f["status"] == "open":
            lines.append(L(lang, f"⚔️ نبرد در {board.square_name(f['square'])} — کدام نابود شد؟", f"⚔️ Battle at {board.square_name(f['square'], 'en')} — which one is destroyed?"))
            rows.append([(f"{u['kind']} · {pl(u['owner'])['name']}"[:30], f"g:bf:{f['id']}:{u['id']}") for u in f["units"] if u.get("id")])
    if len(lines) == 2:
        lines.append(L(lang, "چیزی منتظر نیست.", "Nothing waiting."))
    return "\n".join(lines), rows + [home_btn(lang)]


def lab_screen(uid):
    g = G()
    lang = lang_of(uid)
    fakes = test_players(g)
    lines = [L(lang, "🧪 آزمایشگاه — بازی تست سریع", "🧪 Test lab — fast test game"), ""]
    lines.append(L(lang,
                   "«ساخت بازی تست» ۲۴ بازیکن با اسم واقعی و همه نقش‌ها می‌سازد و شب ۱ را شروع می‌کند.\n"
                   "در حالت تست، بازیکن‌های تست به‌محض شروع شب حرکت و اکت می‌کنند و به‌محض شروع روز در گروه با #رای رأی می‌دهند؛ بعد نتیجه اعلام می‌شود.\n"
                   "با «بازی به‌جای…» خودت یکی از آن‌ها می‌شوی (او دیگر خودکار بازی نمی‌کند).",
                   "“Build test game” makes 24 named players covering every role and starts night 1.\n"
                   "In test mode the test players move and act as soon as a night starts, and vote in the group with #رای as soon as a day starts; then the tally is posted.\n"
                   "“Play as…” makes you one of them (they stop playing on their own)."))
    lines.append("")
    lines.append(L(lang, f"بازیکن تست: {num(len(fakes))} · حالت تست: {'روشن' if g.get('test_mode') else 'خاموش'} · GIF رأی تست: {'روشن' if g.get('test_gifs', True) else 'خاموش'}",
                   f"Test players: {len(fakes)} · test mode: {'on' if g.get('test_mode') else 'off'} · test vote GIFs: {'on' if g.get('test_gifs', True) else 'off'}"))
    if not g["group_id"]:
        lines.append(L(lang, "⚠️ اول ربات را به گروه اضافه کن تا رأی‌ها آنجا دیده شوند.", "⚠️ Add the bot to a group first so the votes show up there."))
    me = playing_as(uid)
    if me:
        lines.append(L(lang, f"🕹 الان به‌جای {me['name']} ({role_name(me['role'], 'fa')}) بازی می‌کنی.", f"🕹 Playing as {me['name']} ({role_name(me['role'], 'en')})."))
    rows = [[(L(lang, "🧪 ساخت بازی تست (۲۴ نفر)", "🧪 Build test game (24 players)"), "g:mk")]]
    if fakes:
        rows.append([(L(lang, "🕹 بازی به‌جای…", "🕹 Play as…"), "g:aslist"), (L(lang, "🤖 همه بازی کنند", "🤖 Everyone plays"), "g:auto")])
        rows.append([(L(lang, f"🎞 GIF رأی تست: {'روشن' if g.get('test_gifs', True) else 'خاموش'}", f"🎞 Test vote GIFs: {'on' if g.get('test_gifs', True) else 'off'}"), "g:gif"),
                     (L(lang, "🗑 حذف بازیکن‌های تست", "🗑 Remove test players"), "g:rmfake")])
    if me:
        rows.append([(L(lang, f"🕹 منوی {me['name']}", f"🕹 {me['name']}'s menu"), "p:home"), (L(lang, "👑 برگشت به گاد", "👑 Back to GM"), "g:asoff")])
    rows.append(home_btn(lang))
    return "\n".join(lines), rows


def setup_screen(uid):
    g = G()
    lang = lang_of(uid)
    lines = [L(lang, "⚙️ تنظیمات", "⚙️ Setup"), ""]
    lines.append(L(lang, f"گروه بازی: {'✅ ' + str(g['group_id']) if g['group_id'] else '❌ ربات را به گروه اضافه کن (خودکار ثبت می‌شود) یا در گروه /setgroup بزن.'}",
                   f"Game group: {'✅ ' + str(g['group_id']) if g['group_id'] else '❌ add the bot to a group (registers automatically) or send /setgroup there.'}"))
    lines.append(L(lang, f"کانال نقشه: {g['channel_id'] or '— (نقشه‌ها در گروه)'} · تغییر: /setchannel -100…",
                   f"Map channel: {g['channel_id'] or '— (maps go to the group)'} · change: /setchannel -100…"))
    lines.append(L(lang, "ربات باید در گروه ادمین باشد تا #رای را ببیند.", "The bot must be a group admin to see #رای messages."))
    lines.append(L(lang, f"قفل خودکار نقشه: ساعت {num(LOCK_HOUR)}:۰۰ تهران", f"Automatic map lock: {LOCK_HOUR}:00 Tehran"))
    rows = [[(L(lang, "☀️ رفتن به روز", "☀️ Force day"), "g:fday"), (L(lang, "🌙 رفتن به شب", "🌙 Force night"), "g:fnight")],
            [(L(lang, "↩️ برگرداندن آخرین تغییر", "↩️ Undo the last change"), "g:undo")],
            [(L(lang, "♻️ بازی جدید (پاک کردن همه)", "♻️ New game (wipe everything)"), "g:reset")],
            home_btn(lang)]
    return "\n".join(lines), rows


# ---------------- the dispatcher for g:* buttons ----------------

async def on_button(update, ctx, data):
    q = update.callback_query
    uid = q.from_user.id
    if not is_gm(uid):
        await q.answer("GM only", show_alert=True)
        return
    parts = data.split(":")[1:]
    head, args = parts[0], parts[1:]
    await handle(update, ctx, uid, head, args)


async def handle(update, ctx, uid, head, args):
    q = update.callback_query
    g = G()
    lang = lang_of(uid)
    bot = ctx.bot
    jq = ctx.job_queue

    if head == "home":
        return await send_control_room(bot, uid, q)
    if head == "lang":
        gl = g.setdefault("gm_lang", {})
        gl[str(uid)] = "en" if lang == "fa" else "fa"
        save()
        return await send_control_room(bot, uid, q)
    if head == "next":
        action = next_step(g)[0]
        if action == "players":
            return await edit_or_send(q, *players_screen(lang, 0))
        if action == "night":
            await do_phase(bot, "night", jq)
        elif action == "day":
            await do_phase(bot, "day", jq)
        elif action == "lock":
            await do_lock(bot)
        elif action == "resolve":
            return await resolve(bot, q, lang)
        elif action == "results":
            return await send_results(bot, q, lang)
        elif action == "votes":
            return await edit_or_send(q, *votes_screen(lang))
        return await send_control_room(bot, uid, q)

    # ----- players -----
    if head == "players":
        return await edit_or_send(q, *players_screen(lang, int(args[0]) if args else 0))
    if head in ("pl", "role", "sr", "mv", "pos", "hp", "co", "give", "gi", "cult", "kill", "rev", "actclr"):
        P = pl(args[0])
        if not P:
            raise GameError("بازیکن پیدا نشد.", "Player not found.")
        if head == "role":
            rows = chunks([(role_name(r, lang), f"g:sr:{P['id']}:{r}") for r in ROLES], 3)
            return await edit_or_send(q, L(lang, f"نقش {P['name']}:", f"Role for {P['name']}:"), rows + [[(L(lang, "↩️ کارت", "↩️ Card"), f"g:pl:{P['id']}")]])
        if head == "sr":
            assign_role(P, args[1])
            give_characters(g)
            save()
            await dm(bot, P["id"], role_card(P, "fa"), role_card(P, "en"))
        elif head == "mv":
            rows = chunks([(LOCATIONS[c][lang][:20], f"g:pos:{P['id']}:{c}") for c in CITIES], 2)
            return await edit_or_send(q, L(lang, f"{P['name']} را کجا بگذارم؟ (برای خانه‌های بین شهرها: /pos اسم n15)",
                                           f"Where should {P['name']} go? (for squares between cities: /pos name n15)"),
                                      rows + [[(L(lang, "↩️ کارت", "↩️ Card"), f"g:pl:{P['id']}")]])
        elif head == "pos":
            P["pos"] = args[1]
            if g["locked"] and g["phase"] == "night":
                P["night_pos"] = args[1]
        elif head == "hp":
            P["hp"] += int(args[1])
        elif head == "co":
            P["coins"] = max(0, P["coins"] + int(args[1]))
        elif head == "give":
            rows = chunks([(ITEMS[k][lang][:22], f"g:gi:{P['id']}:{k}") for k in ITEMS], 2)
            return await edit_or_send(q, L(lang, f"به {P['name']} چه آیتمی بدهم؟", f"Which item for {P['name']}?"),
                                      rows + [[(L(lang, "↩️ کارت", "↩️ Card"), f"g:pl:{P['id']}")]])
        elif head == "gi":
            P["items"].append(args[1])
            await dm(bot, P["id"], f"🎁 آیتم از گاد: {ITEMS[args[1]]['fa']}", f"🎁 Item from the GM: {ITEMS[args[1]]['en']}")
        elif head == "cult":
            P["cult"] = not P["cult"]
        elif head == "kill":
            store.backup()
            actions.kill(g, P, "gm")
            save()
            await events.announce_death(bot, P)
            await events.check_win(bot)
        elif head == "rev":
            P["alive"] = True
            if P["hp"] <= 0:
                P["hp"] = ROLES[P["role"]]["hp"] // 2
        elif head == "actclr":
            g["acts"].pop(str(P["id"]), None)
        save()
        return await edit_or_send(q, *player_card(P, lang))
    if head in ("chn", "chr", "chx"):
        P = pl(args[0])
        if not P:
            raise GameError("بازیکن پیدا نشد.", "Player not found.")
        field = args[1]
        word = "شخصیت" if field == "char" else "شخصیت جعلی"
        if head == "chn":
            g.setdefault("gm_input", {})[str(uid)] = {"pid": str(P["id"]), "field": field}
            save()
            return await edit_or_send(q, f"✏️ اسم {word} {P['name']} را بفرست (الان: {P.get(field) or '—'}).",
                                      [[("🎲 یک اسم تصادفی", f"g:chr:{P['id']}:{field}")], [("↩️ کارت", f"g:chx:{P['id']}:{field}")]])
        g.get("gm_input", {}).pop(str(uid), None)
        if head == "chr":
            P[field] = None
            give_characters(g)
            await dm(bot, P["id"], f"🎭 گاد اسم {word} تو را عوض کرد: {P.get(field)}")
        save()
        return await edit_or_send(q, *player_card(P, lang))
    if head == "kick":
        P = pl(args[0])
        if not P:
            return await edit_or_send(q, *players_screen(lang, 0))
        return await edit_or_send(q, f"🚫 {P['name']} از ربات اخراج شود؟ دیگر نمی‌تواند ثبت‌نام کند.",
                                  [[("بله، اخراج", f"g:kicky:{P['id']}"), ("↩️ نه", f"g:pl:{P['id']}")]])
    if head == "kicky":
        kick(g, args[0])
        return await edit_or_send(q, *players_screen(lang, 0))
    if head == "rnd":
        roles = TEST_ROLES[:]
        random.shuffle(roles)
        for P in [p for p in roster(g) if not p.get("role")]:
            assign_role(P, roles.pop() if roles else "doctor")
            give_characters(g)
            await dm(bot, P["id"], role_card(P, "fa"), role_card(P, "en"))
        save()
        return await edit_or_send(q, *players_screen(lang, 0))

    # ----- play as -----
    if head == "as":
        P = pl(args[0])
        g.setdefault("as", {})[str(uid)] = str(P["id"])
        undone = autopilot.take_over(g, P) if P.get("fake") else ""
        save()
        if undone:
            await bot.send_message(q.message.chat_id, f"🕹 کارهای خودکار این فاز {P['name']} برگردانده شد ({undone}) — حالا خودت بازی کن.")
        from .player_ui import send_home
        await q.answer(L(lang, f"🕹 حالا {P['name']} هستی", f"🕹 You are now {P['name']}"))
        return await send_home(bot, P, q)
    if head == "asoff":
        g.setdefault("as", {}).pop(str(uid), None)
        save()
        return await send_control_room(bot, uid, q)
    if head == "aslist":
        people = [p for p in roster(g) if p.get("role")]
        rows = chunks([(player_label(p, lang)[:30], f"g:as:{p['id']}") for p in people], 2)
        return await edit_or_send(q, L(lang, "به‌جای چه کسی بازی کنی؟", "Play as whom?"), rows + [[(L(lang, "↩️ آزمایشگاه", "↩️ Test lab"), "g:lab")]])

    # ----- map -----
    if head == "map":
        await q.answer()
        await mapview.send_gm_map(bot, q.message.chat_id, lang)
        return await bot.send_message(q.message.chat_id, L(lang, "نقشه عمومی هم منتشر شود؟", "Post the public map too?"),
                                      reply_markup=kb([[(L(lang, "📢 انتشار نقشه عمومی", "📢 Post public map"), "g:pubmap")], home_btn(lang)]))
    if head == "pubmap":
        await mapview.post_public_map(bot)
        return await edit_or_send(q, L(lang, "📢 منتشر شد.", "📢 Posted."), [home_btn(lang)])

    # ----- acts and results -----
    if head == "acts":
        return await edit_or_send(q, *acts_screen(lang))
    if head == "resolve":
        return await resolve(bot, q, lang)
    if head == "ef":
        res = g.get("pending")
        if not res:
            return await send_control_room(bot, uid, q)
        for e in res["effects"]:
            if e["id"] == int(args[0]):
                e["on"] = not e["on"]
        save()
        return await edit_or_send(q, results_text(res, lang), results_rows(res, lang))
    if head == "details":
        res = g.get("pending")
        if res:
            for part in split_text("📋 " + report_text(res)):
                await bot.send_message(q.message.chat_id, part)
        return
    if head == "apply":
        res = g.get("pending")
        if not res:
            return await send_control_room(bot, uid, q)
        store.backup()
        out = actions.apply_effects(g, res)
        g["applied_cycle"] = g["cycle"]
        save()
        await events.send_outbox(bot, out)
        await events.check_win(bot)
        return await send_control_room(bot, uid, q)

    # ----- votes -----
    if head == "votes":
        return await edit_or_send(q, *votes_screen(lang))
    if head == "ex":
        P = pl(args[0])
        return await edit_or_send(q, L(lang, f"مطمئنی {P['name']} اعدام شود؟", f"Execute {P['name']}?"),
                                  [[(L(lang, "☠️ بله، اعدام", "☠️ Yes, execute"), f"g:exy:{P['id']}"), (L(lang, "↩️ نه", "↩️ No"), "g:votes")]])
    if head == "exy":
        err = await events.execute(bot, pl(args[0]))
        if err:
            raise GameError(err)
        g["closed_cycle"] = g["cycle"]
        save()
        return await send_control_room(bot, uid, q)
    if head == "vclose":
        if g["phase"] != "day" or g.get("closed_cycle") == g["cycle"]:
            raise GameError("رأی‌گیری باز نیست.")
        await events.close_vote(bot, jq)
        return await send_control_room(bot, uid, q)
    if head == "jdef":
        jd = g.get("judgement") or {}
        if jd.get("status") == "waiting":
            await events.judge_default(bot, "⚖️ حکم پیش‌فرض اجرا شد.")
        return await send_control_room(bot, uid, q)
    if head == "noex":
        if (g.get("judgement") or {}).get("status") == "waiting":
            g["judgement"]["status"] = "done"
        await group(bot, "🕊 امروز کسی اعدام نشد.", "🕊 Nobody was executed today.")
        g["closed_cycle"] = g["cycle"]
        save()
        return await send_control_room(bot, uid, q)
    if head == "vdel":
        voters = [pl(v) for v in g["votes"] if pl(v)]
        rows = chunks([(f"{p['name']} → {pl(g['votes'][str(p['id'])])['name']}"[:30], f"g:vd:{p['id']}") for p in voters], 2)
        return await edit_or_send(q, L(lang, "رأی چه کسی حذف شود؟ (می‌تواند دوباره رأی بدهد)", "Whose vote should go? (they can vote again)"),
                                  rows + [[(L(lang, "↩️ رأی‌ها", "↩️ Votes"), "g:votes")]])
    if head == "vd":
        votes.delete_votes(voter_id=args[0])
        return await edit_or_send(q, *votes_screen(lang))
    if head == "vclr":
        votes.delete_votes(everything=True)
        return await edit_or_send(q, *votes_screen(lang))
    if head == "vpost":
        await bot.send_message(g["group_id"], votes.tally_text())
        return await q.answer(L(lang, "📢 اعلام شد", "📢 Posted"))

    # ----- balloons & battles -----
    if head == "bal":
        return await edit_or_send(q, *balloons_screen(lang))
    if head == "wb":
        b = next((x for x in g["balloons"] if x["id"] == args[0]), None)
        if b and b["result"] == "await_pct":
            hit = actions.apply_war_balloon(g, b, int(args[1]))
            save()
            await group(bot, f"💣 بالن جنگی {board.square_name(b['target'])} را بمباران کرد: {num(int(args[1]))}٪ تخریب.",
                        f"💣 A war balloon bombed {board.square_name(b['target'], 'en')}: {args[1]}% destroyed.")
            for P, loss in hit:
                await dm(bot, P["id"], f"بمباران! {num(loss)} اچ‌پی از دست دادی.", f"Bombing! You lost {loss} HP.")
                if P["hp"] <= 0:
                    actions.kill(g, P, "bombing")
                    save()
                    await events.announce_death(bot, P)
        return await edit_or_send(q, *balloons_screen(lang))
    if head == "bf":
        f = next((x for x in g["battles"] if x["id"] == args[0]), None)
        if f and f["status"] == "open":
            f["status"] = "done"
            g["units_on_map"] = [u for u in g["units_on_map"] if u.get("id") != args[1]]
            for b in g["balloons"]:
                if b["id"] == args[1]:
                    b["result"] = "shot_down"
            save()
            await group(bot, f"⚔️ نبرد در {board.square_name(f['square'])}: یک واحد نابود شد.",
                        f"⚔️ Battle at {board.square_name(f['square'], 'en')}: one unit was destroyed.")
        return await edit_or_send(q, *balloons_screen(lang))
    if head == "dig":
        P = pl(args[0])
        if args[1] == "0":
            await dm(bot, P["id"], "گاد درخواست جاده را رد کرد.", "The GM rejected your road request.")
            return await edit_or_send(q, "❌")
        if P["units"].get("shovel", 0) < 1:
            raise GameError("بیل ندارد.", "No shovel left.")
        rid = actions.dig_route(g, args[1], args[2], owner=P["id"])
        P["units"]["shovel"] -= 1
        save()
        await dm(bot, P["id"], "⛏ جاده جدید ساخته شد.", "⛏ Your new road is built.")
        return await edit_or_send(q, f"⛏ {rid}: {args[1]} ↔ {args[2]}")

    # ----- test lab -----
    if head == "lab":
        return await edit_or_send(q, *lab_screen(uid))
    if head == "mk":
        if g["phase"] != "lobby":
            store.backup()
            old = g
            fresh = new_game()
            for k in ("group_id", "channel_id", "gm_ids", "gm_lang", "test_gifs"):
                if k in old:
                    fresh[k] = old[k]
            fresh["players"] = {k: v for k, v in old["players"].items() if not v.get("fake")}
            for p in fresh["players"].values():
                p["role"] = None
            store.g = fresh
            save()
        make_test_game(uid)
        await do_phase(bot, "night", jq)
        return await edit_or_send(q, *lab_screen(uid))
    if head == "auto":
        done = autoplay_actions()
        n = 0
        if g["phase"] == "day" and g["group_id"]:
            n = schedule_test_votes(jq)
        await q.answer(L(lang, f"🤖 {num(done['moves'])} حرکت، {num(done['acts'])} اکت، {num(n)} رأی", f"🤖 {done['moves']} moves, {done['acts']} acts, {n} votes"))
        return await edit_or_send(q, *lab_screen(uid))
    if head == "gif":
        g["test_gifs"] = not g.get("test_gifs", True)
        save()
        return await edit_or_send(q, *lab_screen(uid))
    if head == "rmfake":
        for pid in [k for k, v in g["players"].items() if v.get("fake")]:
            g["players"].pop(pid)
        g.get("as", {}).clear()
        g["test_mode"] = False
        save()
        return await edit_or_send(q, *lab_screen(uid))
    if head == "ff":
        await q.answer(L(lang, "⏩ اجرای خودکار شروع شد", "⏩ Auto-run started"))
        jq.run_once(job_fast_forward, 0.5, data=uid)
        return

    # ----- setup -----
    if head == "setup":
        return await edit_or_send(q, *setup_screen(uid))
    if head == "fday":
        await do_phase(bot, "day", jq)
        return await send_control_room(bot, uid, q)
    if head == "fnight":
        await do_phase(bot, "night", jq)
        return await send_control_room(bot, uid, q)
    if head == "undo":
        ok = store.undo()
        await q.answer(L(lang, "↩️ برگشت" if ok else "چیزی برای برگرداندن نیست", "↩️ Restored" if ok else "Nothing to undo"), show_alert=True)
        return await send_control_room(bot, uid, q)
    if head == "reset":
        return await edit_or_send(q, L(lang, "♻️ همه‌چیز پاک شود؟ (گروه و کانال می‌مانند)", "♻️ Wipe everything? (group and channel are kept)"),
                                  [[(L(lang, "بله، بازی جدید", "Yes, new game"), "g:resety"), (L(lang, "↩️ نه", "↩️ No"), "g:setup")]])
    if head == "resety":
        store.backup()
        old = g
        fresh = new_game()
        for k in ("group_id", "channel_id", "gm_ids", "gm_lang"):
            if k in old:
                fresh[k] = old[k]
        store.g = fresh
        save()
        return await send_control_room(bot, uid, q)


async def resolve(bot, q, lang):
    g = G()
    if g["phase"] != "night":
        raise GameError("فقط در شب.", "Night only.")
    g["pending"] = resolve_night(g)
    save()
    await send_results(bot, q, lang)


def report_text(res):
    return "\n".join(fa for fa, _ in res["lines"]).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


async def send_results(bot, q, lang):
    """The full act-by-act report (as many messages as it needs), then the effects with their on/off buttons."""
    res = G()["pending"]
    parts = split_text(f"📋 گزارش کامل شب {num(res['cycle'])}\n\n" + report_text(res))
    await edit_or_send(q, parts[0])
    for part in parts[1:]:
        await bot.send_message(q.message.chat_id, part)
    await bot.send_message(q.message.chat_id, results_text(res, lang), reply_markup=kb(results_rows(res, lang)))


# ---------------- fast forward (test mode) ----------------

async def job_fast_forward(ctx):
    """Run the rest of the cycle by itself: lock → resolve → apply → day → test votes → execute the leader → next night."""
    bot, uid = ctx.bot, ctx.job.data
    g = G()
    lang = lang_of(uid)
    if g["phase"] == "night":
        if not g["locked"]:
            await do_lock(bot)
        if not g.get("pending") and g.get("applied_cycle") != g["cycle"]:
            g["pending"] = resolve_night(g)
            save()
        if g.get("pending"):
            res = g["pending"]
            for part in split_text(f"📋 گزارش کامل شب {num(res['cycle'])}\n\n" + report_text(res)):
                await bot.send_message(uid, part)
            await bot.send_message(uid, results_text(res, lang))
            out = actions.apply_effects(g, res)
            g["applied_cycle"] = g["cycle"]
            save()
            await events.send_outbox(bot, out)
            await events.check_win(bot)
        await do_phase(bot, "day", None)
    if G()["phase"] == "day":
        n = 0
        if G()["group_id"]:
            n = schedule_test_votes(ctx.job_queue, then=finish_day_and_night)
        if not n:
            await finish_day_and_night(ctx)
        else:
            await bot.send_message(uid, L(lang, f"⏳ {num(n)} رأی در گروه… بعد اعدام و شب بعد.", f"⏳ {n} votes in the group… then the execution and the next night."))


async def finish_day_and_night(ctx):
    g = G()
    bot = ctx.bot
    if g["phase"] != "day" or g.get("closed_cycle") == g["cycle"]:
        return
    await events.close_vote(bot, ctx.job_queue)
    if g.get("closed_cycle") != g["cycle"]:
        # the judge is a real person (or you, playing as them): wait for their decision
        jd = g.get("judgement") or {}
        await gm_notes(bot, [(f"⏸ اجرای خودکار منتظر حکم قاضی ({pl(jd['judge'])['name']}) است. بعد از حکم، ⏩ را دوباره بزن.", "")])
        return
    await do_phase(bot, "night", ctx.job_queue)
    for uid in gm_ids():
        try:
            await bot.send_message(uid, control_text(uid), reply_markup=kb(control_rows(uid)))
        except TelegramError:
            pass


# ---------------- typed GM commands (still handy) ----------------

def who(arg):
    p = find_player(G(), arg)
    if not p:
        raise GameError(f"بازیکن پیدا نشد: {arg}", f"Player not found: {arg}")
    return p


async def cmd_nick(update, ctx):
    """/nick <who> <nickname> — another name #رای should recognise."""
    if not is_gm(update.effective_user.id):
        return
    if len(ctx.args or []) < 2:
        await update.message.reply_text("/nick <who> <nickname>")
        return
    try:
        P = who(ctx.args[0])
    except GameError as e:
        await update.message.reply_text(e.text(lang_of(update.effective_user.id)))
        return
    nick = " ".join(ctx.args[1:])
    P.setdefault("nicks", []).append(nick)
    save()
    await update.message.reply_text(f"✅ {P['name']} ← {nick}")


def kick(g, pid):
    """Remove someone from the game for good: they can't /start again."""
    pid = str(pid)
    g["players"].pop(pid, None)
    g["acts"].pop(pid, None)
    g["votes"].pop(pid, None)
    g.setdefault("banned", [])
    if pid not in g["banned"]:
        g["banned"].append(pid)
    for k, v in list(g.get("as", {}).items()):
        if v == pid:
            g["as"].pop(k)
    save()


async def on_gm_text(update, ctx):
    """The GM typing a character name after tapping «اسم شخصیت» on a player card. Returns True if handled."""
    uid = update.effective_user.id
    g = G()
    want = g.get("gm_input", {}).get(str(uid))
    if not want or not is_gm(uid):
        return False
    P = pl(want["pid"])
    g["gm_input"].pop(str(uid), None)
    name = " ".join(update.message.text.split())[:40]
    if not P or not name:
        save()
        return True
    taken = [x for x in g["players"].values() if x is not P and name in (x.get("char"), x.get("fake_char"))]
    if taken:
        await update.message.reply_text(f"⚠️ این اسم مال {taken[0]['name']} است؛ اسم دیگری بفرست.")
        g["gm_input"][str(uid)] = want
        save()
        return True
    P[want["field"]] = name
    save()
    word = "شخصیت" if want["field"] == "char" else "شخصیت جعلی"
    await dm(ctx.bot, P["id"], f"🎭 اسم {word} تو در داستان: {name}")
    lang = lang_of(uid)
    text, rows = player_card(P, lang)
    await update.message.reply_text(f"✅ {word} {P['name']}: {name}\n\n" + text, reply_markup=kb(rows))
    return True
