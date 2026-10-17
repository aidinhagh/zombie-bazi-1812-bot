"""Telegram side of the cannon duels: tell the players, run the 2-hour turns, post the result."""
import asyncio
import time

from . import artillery, autopilot, battle_gif, outbox
from .common import G, save, pl, dm, gm_notes, kb, num, logger


def battle_url(b):
    from .web import webapp_url
    base = webapp_url()
    if not base:
        return None
    root = base.rsplit("/map", 1)[0] if "/map" in base else base.rstrip("/")
    return f"{root}/battle?b={b['id']}"


def open_rows(b, label="⚔️ باز کردن میدان نبرد"):
    url = battle_url(b)
    return [[(label, "webapp:" + url)]] if url else None


def hours_left(sec):
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    return f"{num(h)} ساعت و {num(m)} دقیقه" if h else f"{num(m)} دقیقه"


def owners(b):
    return sorted({u["owner"] for u in b["units"]})


async def tell(bot, b, owner, text, button=True):
    rows = open_rows(b) if button else None
    await dm(bot, owner, text, reply_markup=kb(rows) if rows else None)


async def announce_new(bot, fresh):
    """Right after the map is final: everyone with a cannon in a battle hears about it (unit names only)."""
    g = G()
    for b in fresh:
        for owner in owners(b):
            mine = [u for u in b["units"] if u["owner"] == owner]
            others = [u for u in b["units"] if u["owner"] != owner]
            text = (f"⚔️ توپ {'، '.join('«' + u['name'] + '»' for u in mine)} تو در {artillery.city_fa(b)} "
                    f"با {'، '.join('«' + u['name'] + '»' for u in others)} روبه‌رو شد!\n"
                    f"نبرد نوبتی است تا ساعت ۸ فردا؛ هر توپ در نوبتش ۲ ساعت وقت دارد شلیک کند، وگرنه نوبت به بعدی می‌رسد.\n"
                    f"آب‌وهوا: {artillery.WEATHER_FA[b['weather']]} · توپی که اچ‌پی‌اش تمام شود از بازی حذف می‌شود.")
            await tell(bot, b, owner, text)
        names = "، ".join(f"«{u['name']}» ({(g['players'].get(u['owner']) or {}).get('name', '?')})" for u in b["units"])
        await gm_notes(bot, [(f"⚔️ نبرد توپخانه در {artillery.city_fa(b)}: {names}", "")])
        await drive(bot, b)


async def notify_turn(bot, b):
    u = artillery.unit(b, b["turn"])
    if not u or b["status"] != "live":
        return
    left = max(0, b["deadline"] - time.time())
    await tell(bot, b, u["owner"], f"🎯 نوبت توپ «{u['name']}» است! {hours_left(left)} وقت داری شلیک کنی.", button=True)


async def drive(bot, b):
    """Let test players' cannons fire on their own; stop at a real player's turn (and tell them) or at the end."""
    g = G()
    for _ in range(50):
        if b["status"] != "live":
            break
        u = artillery.unit(b, b["turn"])
        owner = g["players"].get(u["owner"])
        if not (owner and autopilot.is_auto(owner, g)):
            break
        killed = artillery.auto_shot(g, b)
        save()
        await after_shot(bot, b, killed, notify=False)
    save()
    if b["status"] == "live":
        await notify_turn(bot, b)
    else:
        await finished(bot, b)


async def after_shot(bot, b, killed, notify=True):
    for u in killed:
        await tell(bot, b, u["owner"], f"💥 توپ «{u['name']}» تو منهدم شد و از بازی بیرون رفت.", button=False)
    if b["status"] != "live":
        if notify:
            await finished(bot, b)
        return
    if notify:
        await drive(bot, b)


async def finished(bot, b):
    g = G()
    if b.get("announced"):
        return
    b["announced"] = True
    save()
    text = artillery.result_text(g, b)
    for owner in owners(b):
        await tell(bot, b, owner, "⚔️ نبرد توپخانه تمام شد: " + text, button=True)
    real = {u["id"]: (g["players"].get(u["owner"]) or {}).get("name", "?") for u in b["units"]}
    await gm_notes(bot, [(f"⚔️ نتیجه نبرد در {artillery.city_fa(b)}: {text} (" +
                          "، ".join(f"«{u['name']}»={real[u['id']]}" for u in b["units"]) + ")", "")])
    if b["status"] in ("won", "wiped"):
        win = artillery.unit(b, b["winner"]) if b.get("winner") else None
        losers = [{"name": u["name"], "flag": u["disp"]} for u in b["units"] if not u["alive"]]
        try:
            gif = await asyncio.to_thread(battle_gif.make_gif, {"name": win["name"], "flag": win["disp"]} if win else None,
                                          losers, artillery.city_fa(b), artillery.time_of_day(b["city"]), b["weather"], b["seed"])
        except Exception as e:     # never let a drawing problem stop the game
            logger.warning("battle gif failed: %s", e)
            gif = None
        caption = f"⚔️ نبرد توپخانه در {artillery.city_fa(b)}: {text}"
        if gif:
            await outbox.post(bot, "animation", caption, data=gif, filename="battle.gif")
        else:
            await outbox.post(bot, "text", caption)


async def end_all(bot):
    """At the next 20:00 lock the battles that are still going end without a winner."""
    g = G()
    for b in artillery.live(g):
        artillery.sync_units(g, b)
        artillery.finish(g, b, "draw" if len(artillery.alive_units(b)) > 1 else "won")
        save()
        await finished(bot, b)


async def check(bot, now=None):
    """Every minute: cannons that left the map, turns that ran out, battles that ran out."""
    g = G()
    now = time.time() if now is None else now
    for b in list(artillery.live(g)):
        gone = artillery.sync_units(g, b)
        if gone and len(artillery.alive_units(b)) <= 1:
            artillery.finish(g, b, "won" if artillery.alive_units(b) else "wiped", now)
            save()
            await finished(bot, b)
            continue
        if gone and artillery.unit(b, b["turn"]) and not artillery.unit(b, b["turn"])["alive"]:
            artillery.advance(b, now=now)
            save()
            await drive(bot, b)
            continue
        if now >= b["ends"]:
            artillery.finish(g, b, "draw", now)
            save()
            await finished(bot, b)
            continue
        if now >= b["deadline"]:
            u = artillery.timeout(g, b, now=now)
            save()
            if u:
                await tell(bot, b, u["owner"], f"⌛ وقت نوبت توپ «{u['name']}» تمام شد؛ نوبت به توپ بعدی رسید.", button=False)
            await drive(bot, b)


async def job_check(ctx):
    try:
        await check(ctx.bot)
    except Exception as e:
        logger.warning("artillery check failed: %s", e)
