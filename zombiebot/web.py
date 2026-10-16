"""The map web app (Telegram Mini App), served by the bot itself.

  GET  /map          the page
  GET  /api/coast    coastline (cached by the browser)
  GET  /api/state    the player's view: map, units, closed routes, where they can go   (needs Telegram initData)
  POST /api/move     move to a square                                                  (needs Telegram initData)

Telegram signs initData with the bot token, so a request can only act for the person who opened the page
(or, for the GM in the test lab, for the player they are playing as).
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

from aiohttp import web

from . import actions, board, mapview
from .actions import GameError
from .board import SQUARES, CITIES, COAST
from .common import G, save, pl, acting_uid, num, phase_label, dm, kb, logger
from .data.locations import LOCATIONS, UNIT_NAMES
from .data.roles import ROLES

HERE = os.path.dirname(__file__)
PAGE = os.path.join(HERE, "webapp", "map.html")        # the 3D campaign map (built by tools/build_map_webapp.py)
PAGE_2D = os.path.join(HERE, "webapp", "map2d.html")   # flat fallback for phones without WebGL
FONT = os.path.join(HERE, "Vazirmatn-Bold.ttf")
_bot = None
_token = None


def webapp_url():
    url = os.environ.get("WEBAPP_URL", "").strip()
    return url or None


# ---------------- auth ----------------

def verify_init_data(init_data, token, max_age=7 * 86400):
    """Telegram Mini App initData check. Returns the user dict, or None."""
    if not init_data or not token:
        return None
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    their_hash = pairs.pop("hash", None)
    if not their_hash:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    ours = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(ours, their_hash):
        return None
    if max_age and time.time() - int(pairs.get("auth_date", "0")) > max_age:
        return None
    try:
        return json.loads(pairs.get("user", "{}"))
    except ValueError:
        return None


def sign_init_data(user, token, auth_date=None):
    """Build valid initData (used by tests)."""
    pairs = {"auth_date": str(auth_date or int(time.time())), "user": json.dumps(user, separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(pairs)


# ---------------- the player's view ----------------

def static_map():
    g = G()
    squares = []
    for sq, s in SQUARES.items():
        item = {"id": sq, "kind": s["kind"], "lat": s["lat"], "lon": s["lon"], "sea": s["sea"],
                "name": board.square_name(sq, "fa"), "short": (LOCATIONS[sq]["place_fa"] if sq in LOCATIONS else sq.lstrip("n"))}
        if sq in CITIES:
            from .data.locations import CITY_SHORT
            item["city"] = CITY_SHORT[sq][0]
            item["desc"] = LOCATIONS[sq]["desc_fa"]
        squares.append(item)
    routes = [{"id": rid, "kind": r["kind"], "seq": board.route_sequence(r), "status": board.route_status(g, rid)}
              for rid, r in board.all_routes(g).items()]
    units = [{"kind": u["kind"], "type": UNIT_NAMES[u["kind"]][0], "name": u.get("name") or "", "square": u["square"]}
             for u in g["units_on_map"]]
    reports = [{"name": b.get("name") or "", "target": b["target"], "seen": b["result"]} for b in mapview.published_balloons(g)]
    return {"squares": squares, "routes": routes, "units": units, "reports": reports, "damage": g["loc_damage"]}


def move_mode(g, p):
    if g["phase"] == "lobby":
        return "lobby", "بازی هنوز شروع نشده."
    if not p["alive"]:
        return "dead", "شما مرده‌اید."
    if g["locked"]:
        return "locked", "نقشه تا فاز بعد قفل است."
    if p["moved"]:
        return "moved", "در این فاز حرکت کرده‌ای."
    if p["pos"] is None:
        return "first", "اولین حرکت: هر شهری که بخواهی."
    if p["flags"].get("free_move"):
        return "free", "نقشه قاچاقچی: بدون تاس به هر شهری برو."
    if p.get("move_roll") is None:
        return "noroll", "اول در ربات تاس بریز (🎲 حرکت)."
    return "roll", f"🎲 تاس: {num(p['move_roll'])} — تا این تعداد خانه می‌توانی بروی."


def state_for(p):
    g = G()
    mode, hint = move_mode(g, p)
    options = []
    if mode in ("first", "free"):
        options = [{"sq": c, "n": i + 1, "path": [c]} for i, c in enumerate(c for c in CITIES if c != p.get("pos") or mode == "first")]
    elif mode == "roll":
        options = [{"sq": s, "n": n, "path": path} for n, s, path in mapview.ordered_choices(g, p)]
    for o in options:
        o["tolls"] = [sq for sq in o["path"] if any(u["square"] == sq and str(u["owner"]) != str(p["id"]) for u in g["units_on_map"])]
    r = ROLES.get(p["role"] or "", {})
    return {
        "me": {"name": p["name"], "role": r.get("fa", ""), "hp": p["hp"], "coins": p["coins"], "pos": p.get("pos"),
               "roll": p.get("move_roll"), "plus": p["flags"].get("move_plus", 0)},
        "phase": phase_label("fa", g), "mode": mode, "hint": hint, "options": options, **static_map(),
    }


def do_web_move(p, dest):
    g = G()
    mode, _ = move_mode(g, p)
    if mode in ("first", "free"):
        if dest not in CITIES:
            raise GameError("فقط شهرها.")
        path = [dest]
    elif mode == "roll":
        opts = actions.move_options(g, p, p["move_roll"] or 0)
        if dest not in opts:
            raise GameError("این مقصد در دسترس نیست.")
        path = opts[dest]
    else:
        raise GameError(move_mode(g, p)[1])
    notes = actions.do_move(g, p, dest, path)
    save()
    return path, notes


# ---------------- HTTP ----------------

def player_from(request, data=None):
    init = request.headers.get("X-Init-Data") or (data or {}).get("init") or request.query.get("init", "")
    user = verify_init_data(init, _token)
    if not user:
        raise web.HTTPUnauthorized(text="لطفاً نقشه را از داخل ربات باز کنید.")
    p = pl(acting_uid(int(user["id"])))
    if not p or not p.get("role"):
        raise web.HTTPForbidden(text="نقشی نداری.")
    return p


async def h_page(request):
    return web.FileResponse(PAGE, headers={"Cache-Control": "no-cache"})


async def h_page2d(request):
    return web.FileResponse(PAGE_2D, headers={"Cache-Control": "no-cache"})


async def h_font(request):
    return web.FileResponse(FONT, headers={"Cache-Control": "public, max-age=604800"})


async def h_coast(request):
    return web.json_response(COAST, headers={"Cache-Control": "public, max-age=86400"})


async def h_state(request):
    p = player_from(request)
    return web.json_response(state_for(p))


async def h_move(request):
    data = await request.json()
    p = player_from(request, data)
    try:
        path, notes = do_web_move(p, str(data.get("dest", "")))
    except GameError as e:
        return web.json_response({"ok": False, "error": e.text("fa")}, status=400)
    if _bot is not None:
        from .player_ui import home_rows
        for pid, fa, _en in notes:
            await dm(_bot, pid, fa)
        info = ("\nℹ️ " + LOCATIONS[p["pos"]]["desc_fa"]) if p["pos"] in LOCATIONS else ""
        await dm(_bot, p["id"], f"📍 رسیدی به {board.square_name(p['pos'])}{info}", reply_markup=kb(home_rows(p)))
    return web.json_response({"ok": True, "path": path, "pos": p["pos"], "name": board.square_name(p["pos"]),
                              "coins": p["coins"], "hp": p["hp"],
                              "tolls": [fa for pid, fa, _ in notes if str(pid) == str(p["id"])]})


async def h_root(request):
    raise web.HTTPFound("/map")


async def h_health(request):
    return web.Response(text="ok")


def make_app():
    app = web.Application()
    app.router.add_get("/", h_root)
    app.router.add_get("/map", h_page)
    app.router.add_get("/map2d", h_page2d)
    app.router.add_get("/font.ttf", h_font)
    app.router.add_get("/api/coast", h_coast)
    app.router.add_get("/api/state", h_state)
    app.router.add_post("/api/move", h_move)
    app.router.add_get("/health", h_health)
    return app


async def start(application):
    """Run the web server next to the bot (Application.post_init)."""
    global _bot, _token
    _bot = application.bot
    _token = application.bot.token
    port = os.environ.get("PORT")
    if not port:
        logger.info("PORT not set: map web app is off")
        return
    runner = web.AppRunner(make_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    logger.info("map web app on port %s (%s)", port, webapp_url() or "WEBAPP_URL not set")
