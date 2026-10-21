"""Entry point: wires commands, buttons, group messages and timers together."""
import datetime
import json
import logging
import os

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, MessageHandler,
                          filters)

from . import actions, board, common, events, gm_ui, player_ui, votes
from .actions import GameError
from .board import SQUARES
from .common import G, save, pl, is_gm, lang_of, playing_as, kb, split_text, to_gms, LOCK_HOUR, TZ, ENV_GMS
from .data.items import ITEMS
from .data.locations import UNIT_PRICES
from .data.roles import ROLES, role_name
from .state import new_player, assign_role, give_characters, needs_fake_char
from .texts import L, bi, role_card, GM_HELP, help_text

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
for noisy in ("httpx", "httpcore", "apscheduler"):   # httpx logs request URLs, which contain the bot token
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger("zombiebot")


# ---------------- private commands ----------------

async def cmd_start(update: Update, ctx):
    if update.effective_chat.type != "private":
        return
    u = update.effective_user
    g = G()
    if is_gm(u.id) and not ctx.args:
        if playing_as(u.id):
            return await player_ui.send_home(ctx.bot, playing_as(u.id))
        stale = pl(u.id)
        if stale and not stale.get("role"):
            g["players"].pop(str(u.id), None)   # registered before becoming GM; not a player
            save()
        if not pl(u.id):
            return await gm_ui.send_control_room(ctx.bot, u.id)
    if str(u.id) in g.get("banned", []):
        return
    p = pl(u.id)
    if not p:
        p = new_player(u.id, u.full_name, u.username)
        g["players"][str(u.id)] = p
        save()
        await to_gms(ctx.bot, f"➕ {u.full_name} (@{u.username or '-'}) ثبت‌نام کرد · آیدی {u.id}",
                     reply_markup=kb([[("🎴 کارت بازیکن", f"g:pl:{u.id}"), ("🚫 اخراج", f"g:kick:{u.id}")]]))
        await update.message.reply_text("👋 به زامبی‌بازی ۱۸۱۲ خوش اومدی! ثبت‌نام شدی؛ گاد نقشت رو می‌فرسته.")
        return
    await player_ui.send_home(ctx.bot, p)


async def cmd_gm(update: Update, ctx):
    if is_gm(update.effective_user.id):
        await gm_ui.send_control_room(ctx.bot, update.effective_user.id)


async def cmd_help(update: Update, ctx):
    uid = update.effective_user.id
    text = help_text(lang_of(uid))
    if is_gm(uid):
        text += "\n\n" + GM_HELP
    await update.message.reply_text(text)


async def cmd_whoami(update: Update, ctx):
    await update.message.reply_text(f"id: {update.effective_user.id} · chat: {update.effective_chat.id}")


# ---------------- group ----------------

async def cmd_setgroup(update: Update, ctx):
    if not is_gm(update.effective_user.id) or update.effective_chat.type == "private":
        return
    G()["group_id"] = update.effective_chat.id
    save()
    await update.message.reply_text(bi("✅ این گروه، گروه بازی شد. رأی: #رای اسم · نتیجه: #رایگیری",
                                       "✅ This is now the game group. Vote: #رای name · results: #رایگیری"))


async def on_my_membership(update: Update, ctx):
    """When a GM adds the bot to a group, that group becomes the game group."""
    cmu = update.my_chat_member
    if not cmu or cmu.chat.type == "private":
        return
    status = cmu.new_chat_member.status
    if status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR) and is_gm(cmu.from_user.id):
        first = G()["group_id"] != cmu.chat.id
        G()["group_id"] = cmu.chat.id
        save()
        if first:
            await ctx.bot.send_message(cmu.chat.id, bi(
                "🗺 زامبی‌بازی ۱۸۱۲ اینجاست.\nرأی در روز: #رای اسم · نتیجه: #رایگیری\nبرای دیدن #رای‌ها، من را ادمین کنید.",
                "🗺 Zombie Bazi 1812 is here.\nDay vote: #رای name · results: #رایگیری\nMake me an admin so I can see the #رای messages."))
            await to_gms(ctx.bot, L(lang_of(cmu.from_user.id), f"✅ گروه «{cmu.chat.title}» گروه بازی شد.",
                                    f"✅ «{cmu.chat.title}» is now the game group."))
    elif status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) and G()["group_id"] == cmu.chat.id:
        G()["group_id"] = None
        save()


# ---------------- buttons ----------------

async def on_button(update: Update, ctx):
    q = update.callback_query
    data = q.data or ""
    try:
        if data.startswith("g:"):
            await gm_ui.on_button(update, ctx, data)
        elif data.startswith("x:"):
            await events.shared_button(update, ctx, data)
        elif data.startswith("p:"):
            await player_ui.on_button(update, ctx, data)
    except GameError as e:
        try:
            await q.answer(e.text(lang_of(q.from_user.id)), show_alert=True)
        except Exception:
            pass
        return
    try:
        await q.answer()
    except Exception:
        pass   # already answered with a message


# ---------------- timers ----------------

async def job_lock(ctx):
    await gm_ui.do_lock(ctx.bot)


async def job_night_window(ctx):
    from .night_window import window, expired
    g = G()
    w = window(g)
    if not w:
        return
    if expired(g, "move_until") and not g["locked"]:
        await gm_ui.do_lock(ctx.bot)
    if expired(g, "acts_until") and not w.get("closed_notified"):
        w["closed_notified"] = True
        save()
        await to_gms(ctx.bot, "⏰ مهلت اکت شب تمدیدشده تمام شد؛ اکنون می‌توانید نتیجه نهایی را محاسبه و تأیید کنید.")


async def job_midnight(ctx):
    g = G()
    if g["phase"] == "lobby":
        return
    if (g.get("legend") or {}).get("auction"):
        await events.legend_close(ctx.bot)      # the legendary auction runs 20:00 → 00:00
    for uid in common.gm_ids():
        lang = lang_of(uid)
        try:
            await ctx.bot.send_message(uid, L(lang, "🕛 نیمه‌شب.\n", "🕛 Midnight.\n") + gm_ui.control_text(uid),
                                       reply_markup=kb(gm_ui.control_rows(uid)))
        except Exception:
            pass


# ---------------- typed GM commands (the panel covers these; kept for speed) ----------------

def gm_cmd(fn):
    async def wrap(update: Update, ctx):
        uid = update.effective_user.id
        if not is_gm(uid):
            return
        try:
            return await fn(update, ctx)
        except GameError as e:
            await update.message.reply_text(e.text(lang_of(uid)))
        except (IndexError, ValueError):
            await update.message.reply_text("⚠️ " + (fn.__doc__ or "bad arguments"))
    wrap.__name__ = fn.__name__
    return wrap


def who(arg):
    return gm_ui.who(arg)


@gm_cmd
async def cmd_setchannel(update, ctx):
    """/setchannel -100xxxxxxxxxx | off"""
    G()["channel_id"] = None if ctx.args[0] == "off" else int(ctx.args[0])
    save()
    await update.message.reply_text("✅")


@gm_cmd
async def cmd_assign(update, ctx):
    """/assign <who> <role> [fake_role]"""
    p = who(ctx.args[0])
    if ctx.args[1] not in ROLES:
        return await update.message.reply_text(", ".join(ROLES))
    assign_role(p, ctx.args[1], ctx.args[2] if len(ctx.args) > 2 and ctx.args[2] in ROLES else None)
    give_characters(G())
    save()
    await update.message.reply_text(f"✅ {p['name']} = {role_name(p['role'])}")
    p["published"] = False
    save()


async def _set_char(update, ctx, field):
    p = who(ctx.args[0])
    name = " ".join(ctx.args[1:]).strip()[:40]
    if not name:
        return await update.message.reply_text("/char اسم‌بازیکن اسم شخصیت")
    if field == "fake_char" and not needs_fake_char(p):
        return await update.message.reply_text("فقط زامبی‌ها و مستقل‌ها شخصیت جعلی دارند.")
    p[field] = name
    save()
    word = "شخصیت" if field == "char" else "شخصیت جعلی"
    await update.message.reply_text(f"✅ {word} {p['name']}: {name}")
    await common.dm(ctx.bot, p["id"], f"🎭 اسم {word} تو در داستان: {name}")


@gm_cmd
async def cmd_char(update, ctx):
    """/char <who> <character name>"""
    await _set_char(update, ctx, "char")


@gm_cmd
async def cmd_fakechar(update, ctx):
    """/fakechar <who> <fake character name>"""
    await _set_char(update, ctx, "fake_char")


@gm_cmd
async def cmd_legend(update, ctx):
    """/legend · /legend spawn [city] · /legend move [city] · /legend close · /legend give <who> <1|2|3>"""
    from . import legendary, events
    from .data.legendary import LEGENDARY
    g = G()
    L = legendary.state(g)
    args = ctx.args
    if not args:
        a, au = L["active"], L["auction"]
        lines = ["🌟 آیتم‌های لجندری:"]
        for i, (k, it) in enumerate(LEGENDARY.items(), 1):
            owner = next((p["name"] for p in g["players"].values() if k in p.get("legend", [])), None)
            where = (f"روی نقشه: {board.square_name(a['where'])}" if a and a["key"] == k else
                     "در مزایده" if au and au["key"] == k else f"مال {owner}" if owner else
                     "هنوز ظاهر نشده" if k not in L["spawned"] else "—")
            lines.append(f"{i}. {it['fa']} ({it['desc_fa']}) · {where}")
        return await update.message.reply_text("\n".join(lines) + "\n\n" + (cmd_legend.__doc__ or ""))
    if args[0] == "spawn":
        a = legendary.spawn_next(g, where=args[1] if len(args) > 1 and args[1] in board.SQUARES else None)
        save()
        if not a:
            return await update.message.reply_text("الان نمی‌شه (یکی روی نقشه یا در مزایده است، یا همه ظاهر شده‌اند).")
        return await update.message.reply_text("✅ " + legendary.spawn_text(a))
    if args[0] == "move":
        want = " ".join(args[1:]).strip()
        where = None
        if want:
            where = want if want in board.SQUARES else next((k for k in board.SQUARES if board.square_name(k) == want), None) or next((k for k in board.SQUARES if board.square_name(k).split(' (')[0] == want), None)
            if not where:
                return await update.message.reply_text("شهر پیدا نشد. اسم یا کد شهر را درست بنویس، یا خالی بگذار تا تصادفی جابه‌جا شود.")
        a = legendary.move_active(g, where)
        save()
        if not a:
            return await update.message.reply_text("الان آیتم لجندری‌ای روی نقشه نیست.")
        return await update.message.reply_text(f"✅ (فقط برای گاد) «{LEGENDARY[a['key']]['fa']}» به {board.square_name(a['where'])} منتقل شد.")
    if args[0] == "close":
        ok = await events.legend_close(ctx.bot)
        return await update.message.reply_text("✅" if ok else "مزایده‌ای باز نیست.")
    if args[0] == "give":
        p = who(args[1])
        key = list(LEGENDARY)[int(args[2]) - 1]
        legendary.give(g, p, key)
        if key not in L["spawned"]:
            L["spawned"].append(key)
        if L["active"] and L["active"]["key"] == key:
            L["active"] = None
        save()
        return await update.message.reply_text(f"✅ {p['name']} ← {LEGENDARY[key]['fa']}")


@gm_cmd
async def cmd_export(update, ctx):
    """/export — the whole game (players, roles, stats, items, map…) as a file"""
    save()
    with open(common.store.path, "rb") as f:
        await ctx.bot.send_document(update.effective_chat.id, f, filename="zombie-bazi-state.json",
                                    caption="💾 کل داده‌های بازی. برای برگرداندن: همین فایل را با کپشن /import بفرست.")


async def on_manual_dice(update, ctx):
    """A 🎲/🎰 sent by hand doesn't count — only the bot's own buttons throw dice for the game."""
    await update.message.reply_text("⚠️ تاس یا اسلاتی که خودت بفرستی حساب نمی‌شود. از دکمه‌های منوی ربات استفاده کن "
                                    "(اسلات کارخانه/قبرستان فقط شب و بعد از ساعت ۸).")


async def on_document(update, ctx):
    """GM sends a game file with the caption /import → it replaces the current game (the old one is backed up)."""
    m = update.message
    if not m or not m.document or not is_gm(update.effective_user.id):
        return
    if not (m.caption or "").strip().startswith("/import"):
        return
    f = await ctx.bot.get_file(m.document.file_id)
    raw = await f.download_as_bytearray()
    try:
        g = json.loads(bytes(raw).decode("utf8"))
        assert isinstance(g, dict) and isinstance(g.get("players"), dict)
    except Exception:
        return await m.reply_text("⚠️ این فایل بازی معتبر نیست.")
    common.store.replace(g)
    await m.reply_text(f"✅ بازی بارگذاری شد: {len(g['players'])} بازیکن. نسخه قبلی در پوشه backups ذخیره شد.")


@gm_cmd
async def cmd_backups(update, ctx):
    """/backups — list saved copies · /backups <n> — restore copy n"""
    d = os.path.join(os.path.dirname(common.store.path), "backups")
    files = sorted((x for x in os.listdir(d) if x.startswith("state-")), reverse=True) if os.path.isdir(d) else []
    if not ctx.args:
        lines = [f"{i}. {x[6:-5]}" for i, x in enumerate(files[:20], 1)] or ["هنوز نسخه‌ای نیست."]
        return await update.message.reply_text("💾 نسخه‌های ذخیره‌شده (هر شروع فاز):\n" + "\n".join(lines) + "\n\nبرگرداندن: /backups شماره")
    name = files[int(ctx.args[0]) - 1]
    with open(os.path.join(d, name), encoding="utf8") as f:
        common.store.replace(json.load(f))
    await update.message.reply_text(f"✅ برگشت به {name[6:-5]}")


@gm_cmd
async def cmd_approve(update, ctx):
    """/approve on|off — group posts wait for your ✅ (on) or go straight out (off)"""
    g = G()
    if ctx.args:
        g["approve_group"] = ctx.args[0].lower() in ("on", "1", "yes", "روشن")
        save()
    await update.message.reply_text("📨 تأیید پیام‌های گروه: " + ("روشن ✅" if g.get("approve_group", True) else "خاموش")
                                    + "\n/approve on · /approve off")


@gm_cmd
async def cmd_hp(update, ctx):
    """/hp <who> <n>"""
    p = who(ctx.args[0])
    p["hp"] = int(ctx.args[1])
    save()
    await update.message.reply_text(f"✅ {p['name']} ❤️ {p['hp']}")


@gm_cmd
async def cmd_coins(update, ctx):
    """/coins <who> <n|+n|-n>"""
    p = who(ctx.args[0])
    v = ctx.args[1]
    p["coins"] = p["coins"] + int(v) if v[0] in "+-" else int(v)
    save()
    await update.message.reply_text(f"✅ {p['name']} 💰 {p['coins']}")


@gm_cmd
async def cmd_pos(update, ctx):
    """/pos <who> <square>  e.g. london or n15"""
    p = who(ctx.args[0])
    if ctx.args[1] not in SQUARES:
        raise GameError("خانه نامعتبر.", "Unknown square.")
    p["pos"] = ctx.args[1]
    if G()["locked"] and G()["phase"] == "night":
        p["night_pos"] = ctx.args[1]
    save()
    await update.message.reply_text(f"✅ {p['name']} 📍 {board.square_name(p['pos'])}")


@gm_cmd
async def cmd_give(update, ctx):
    """/give <who> <item>"""
    p = who(ctx.args[0])
    if ctx.args[1] not in ITEMS:
        return await update.message.reply_text(", ".join(ITEMS))
    p["items"].append(ctx.args[1])
    save()
    await update.message.reply_text(f"✅ {p['name']} +{ctx.args[1]}")


@gm_cmd
async def cmd_unit(update, ctx):
    """/unit <who> <unit> <n>"""
    p = who(ctx.args[0])
    if ctx.args[1] not in UNIT_PRICES:
        return await update.message.reply_text(", ".join(UNIT_PRICES))
    p["units"][ctx.args[1]] = int(ctx.args[2])
    save()
    await update.message.reply_text("✅")


@gm_cmd
async def cmd_charge(update, ctx):
    """/charge <who> <key> <n>"""
    p = who(ctx.args[0])
    p["charges"][ctx.args[1]] = int(ctx.args[2])
    save()
    await update.message.reply_text("✅")


@gm_cmd
async def cmd_route(update, ctx):
    """/route <route_id> ok|broken|mined"""
    g = G()
    if ctx.args[0] not in board.all_routes(g) or ctx.args[1] not in ("ok", "broken", "mined"):
        return await update.message.reply_text("\n".join(f"{r} {board.route_name(g, r, 'en')}" for r in board.all_routes(g)))
    g["route_state"][ctx.args[0]] = ctx.args[1]
    save()
    await update.message.reply_text("✅")


@gm_cmd
async def cmd_dig(update, ctx):
    """/dig <squareA> <squareB> [road|sea]"""
    rid = actions.dig_route(G(), ctx.args[0], ctx.args[1], ctx.args[2] if len(ctx.args) > 2 else "road")
    save()
    await update.message.reply_text(f"✅ {rid}")


@gm_cmd
async def cmd_damage(update, ctx):
    """/damage <city> <percent>"""
    G()["loc_damage"][ctx.args[0]] = int(ctx.args[1])
    save()
    await update.message.reply_text("✅")


@gm_cmd
async def cmd_actadd(update, ctx):
    """/actadd <who> <type> <target|-> [key=value …]"""
    p = who(ctx.args[0])
    target = str(who(ctx.args[2])["id"]) if len(ctx.args) > 2 and ctx.args[2] != "-" else None
    extra = {}
    for kv in ctx.args[3:]:
        k, _, v = kv.partition("=")
        if k == "targets":
            extra[k] = [str(who(x)["id"]) for x in v.split(",")]
        elif k in ("war", "target2"):
            extra[k] = str(who(v)["id"])
        elif k == "wire":
            extra[k] = int(v)
        else:
            extra[k] = v
    G()["acts"].setdefault(str(p["id"]), []).append({"type": ctx.args[1], "target": target, "extra": extra})
    save()
    await update.message.reply_text(f"✅ {p['name']}: {ctx.args[1]}")


@gm_cmd
async def cmd_story(update, ctx):
    """/story <text>"""
    text = update.message.text.partition(" ")[2]
    for t in {G()["group_id"], G()["channel_id"]} - {None}:
        await ctx.bot.send_message(t, "📖 " + text)


@gm_cmd
async def cmd_say(update, ctx):
    """/say <text>"""
    text = update.message.text.partition(" ")[2]
    if G()["group_id"] and text:
        await ctx.bot.send_message(G()["group_id"], text)


@gm_cmd
async def cmd_log(update, ctx):
    lines = [f"[{x['phase']} {x['cycle']}] {x['text']}" for x in G()["log"][-60:]]
    for part in split_text("\n".join(lines) or "empty"):
        await update.message.reply_text(part)


@gm_cmd
async def cmd_undo(update, ctx):
    await update.message.reply_text("↩️" if common.store.undo() else "—")


async def on_error(update, ctx):
    logger.exception("error", exc_info=ctx.error)


async def _post_init(app):
    try:
        if actions.restore_used_units(G()):
            save()
        if actions.fix_self_war_bullets(G()):
            save()
        n = actions.repair_half_applied(G())
        if n:
            save()
            logger.warning("night result was half-applied %sx; undone so the GM can apply it once", n)
    except Exception as e:
        logger.warning("repair check failed: %s", e)
    from . import web
    await web.start(app)
    # dug roads that don't join two cities are removed; the players who may have used them are told
    try:
        g = G()
        try:
            from .events import legend_spawn_next
            if g.get("phase") in ("day", "night"):
                await legend_spawn_next(app.bot)     # an item was taken and nothing new is out yet
        except Exception as e:
            logger.warning("legend spawn at startup failed: %s", e)
        dropped = actions.drop_bad_dug_roads(g)
        if dropped:
            save()
            for name, near in dropped:
                for p in near:
                    await common.dm(app.bot, p["id"], f"⛏ جاده «{name}» نامعتبر بود و حذف شد (جاده فقط بین دو شهر ساخته می‌شود). "
                                                    "اگر از این جاده جابه‌جا شده‌ای، گاد جایت را بررسی می‌کند.")
                await common.gm_notes(app.bot, [(f"⛏ جاده نامعتبر «{name}» حذف شد. بازیکن‌هایی که روی دو سر آن بودند یا از آن رد شدند: "
                                                 + ("، ".join(f"{p['name']} ({board.square_name(p['pos']) if p.get('pos') else '—'})" for p in near) or "هیچ‌کس")
                                                 + " — اگر کسی از این جاده رفته، از کارت بازیکن جابه‌جایش کن.", "")])
    except Exception as e:
        logger.warning("dug road check failed: %s", e)
    # live duels get their current round's buttons again (new attack/defend/trick buttons)
    try:
        g = G()
        for du in g["duels"]:
            if du["status"] == "live" and not du.get("resent_v2"):
                du["resent_v2"] = True
                du["picks"] = {}
                save()
                await events.ask_rps(app.bot, "d", du, len(du.get("rounds", [])) + 1)
    except Exception as e:
        logger.warning("duel resend failed: %s", e)


def build_app(token):
    builder = Application.builder().token(token)
    try:
        from telegram.ext import AIORateLimiter
        # Throttle sends ahead of time, but never retry a flood-control error: PTB's limiter pauses EVERY request
        # while it waits out a RetryAfter, which freezes the whole bot for minutes. A dropped message is logged instead.
        builder = builder.rate_limiter(AIORateLimiter(group_max_rate=15, max_retries=0))
    except Exception:   # the rate-limiter extra isn't installed (tests): run without it
        pass
    # a post waiting for its turn in the group must never hold up everyone else's buttons
    from . import web
    app = builder.concurrent_updates(True).post_init(_post_init).build()
    cmds = {"start": cmd_start, "menu": player_ui.cmd_menu, "gm": cmd_gm, "lang": player_ui.cmd_lang, "help": cmd_help,
            "whoami": cmd_whoami, "setgroup": cmd_setgroup, "setchannel": cmd_setchannel, "nick": gm_ui.cmd_nick,
            "delete": votes.cmd_delete, "assign": cmd_assign, "char": cmd_char, "legend": cmd_legend, "approve": cmd_approve, "export": cmd_export, "backups": cmd_backups, "fakechar": cmd_fakechar, "hp": cmd_hp, "coins": cmd_coins, "pos": cmd_pos,
            "give": cmd_give, "unit": cmd_unit, "charge": cmd_charge, "route": cmd_route, "dig": cmd_dig,
            "damage": cmd_damage, "actadd": cmd_actadd, "story": cmd_story, "say": cmd_say, "log": cmd_log,
            "undo": cmd_undo}
    for name, fn in cmds.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(ChatMemberHandler(on_my_membership, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & filters.ChatType.GROUPS & ~filters.COMMAND,
                                   votes.on_group_text))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, player_ui.on_private_text))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, on_document))
    app.add_handler(MessageHandler(filters.Dice.ALL & filters.ChatType.PRIVATE, on_manual_dice))
    app.add_error_handler(on_error)
    jq = app.job_queue
    jq.run_repeating(job_night_window, interval=10, first=1, name="night-window")
    jq.run_daily(job_lock, time=datetime.time(LOCK_HOUR, 0, tzinfo=TZ), name="lock")
    jq.run_daily(job_midnight, time=datetime.time(0, 0, tzinfo=TZ), name="midnight")
    from . import artillery_bot
    jq.run_repeating(artillery_bot.job_check, interval=60, first=30, name="artillery")
    return app


def main():
    token = os.environ.get("BOT_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        raise SystemExit("BOT_TOKEN is empty or missing. On Railway: after adding variables, apply/deploy the staged changes.")
    banned = [x.strip() for x in os.environ.get("BANNED_IDS", "").split(",") if x.strip()]
    if banned:
        for pid in banned:
            gm_ui.kick(common.G(), pid)
        logger.info("banned ids applied: %s", banned)
    if not ENV_GMS:
        logger.warning("GM_IDS is empty: nobody is GM. Set GM_IDS to your Telegram id (send /whoami to the bot).")
    build_app(token).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
