"""Draw the board as a PNG: coasts, routes, squares, units, and optionally
numbered reachable squares (for moving) or everyone's position (for the GM)."""
import io
import math
import os
import re

from PIL import Image, ImageDraw, ImageFont

from . import board
from .board import SQUARES, CITIES, COAST
from .animator import shape, text_kwargs

LON0, LON1, LAT0, LAT1 = -11.5, 41.5, 37.0, 62.4
K = math.cos(math.radians(50))
W = 1800
H = int(W * (LAT1 - LAT0) / ((LON1 - LON0) * K))

SEA, LAND, INK = (166, 190, 186), (239, 228, 200), (58, 40, 22)
ROAD, SEALANE, RED = (150, 100, 52), (40, 75, 140), (170, 30, 30)
PICK, YOU = (200, 30, 40), (30, 110, 60)
FONT_PATH = os.path.join(os.path.dirname(__file__), "Vazirmatn-Bold.ttf")
_PERSIAN = re.compile(r"[؀-ۿ]")
_fonts = {}


def font(size):
    """Vazirmatn covers Latin and Persian; fall back to Pillow's default."""
    if size not in _fonts:
        try:
            _fonts[size] = ImageFont.truetype(FONT_PATH, size)
        except OSError:
            try:
                _fonts[size] = ImageFont.load_default(size=size)
            except TypeError:
                _fonts[size] = ImageFont.load_default()
    return _fonts[size]


def text(d, xy, s, f, **kw):
    if _PERSIAN.search(s):
        kw = {**kw, **text_kwargs()}
        s = shape(s)
    d.text(xy, s, font=f, **kw)


def xy(lon, lat):
    return ((lon - LON0) / (LON1 - LON0) * W, (LAT1 - lat) / (LAT1 - LAT0) * H)


def sq_xy(sq):
    s = SQUARES[sq]
    return xy(s["lon"], s["lat"])


def dashed(d, a, b, fill, width, dash=12, gap=8):
    (x1, y1), (x2, y2) = a, b
    L = math.hypot(x2 - x1, y2 - y1) or 1
    n = int(L // (dash + gap)) + 1
    for i in range(n):
        s = i * (dash + gap) / L
        e = min(1, (i * (dash + gap) + dash) / L)
        d.line([(x1 + (x2 - x1) * s, y1 + (y2 - y1) * s), (x1 + (x2 - x1) * e, y1 + (y2 - y1) * e)], fill=fill, width=width)


def render(g, gm=False, title=None, highlight=None, you=None, names=None, reports=None):
    """highlight: {square: number} drawn as big numbered pins (movement choices).
    you: the viewer's square. names: {square: [names]} written next to squares (GM view)."""
    img = Image.new("RGB", (W, H), SEA)
    d = ImageDraw.Draw(img)
    for ring in COAST:
        pts = [xy(lo, la) for lo, la in ring]
        if len(pts) > 2:
            d.polygon(pts, fill=LAND, outline=(120, 90, 60))
    f_city, f_node, f_small, f_title, f_pin = font(26), font(15), font(19), font(34), font(24)

    for rid, r in board.all_routes(g).items():
        seq = board.route_sequence(r)
        status = board.route_status(g, rid)
        for a, b in zip(seq, seq[1:]):
            pa, pb = sq_xy(a), sq_xy(b)
            if r["kind"] == "sea":
                dashed(d, pa, pb, RED if status == "mined" else SEALANE, 4)
            elif status == "broken":
                dashed(d, pa, pb, RED, 6, 6, 10)
            else:
                d.line([pa, pb], fill=ROAD, width=6)
        if status != "ok":
            if len(seq) > 2:
                mx, my = sq_xy(seq[len(seq) // 2])
            else:
                (ax, ay), (bx, by) = sq_xy(seq[0]), sq_xy(seq[-1])
                mx, my = (ax + bx) / 2, (ay + by) / 2
            d.line([(mx - 14, my - 14), (mx + 14, my + 14)], fill=RED, width=6)
            d.line([(mx + 14, my - 14), (mx - 14, my + 14)], fill=RED, width=6)

    for sq, s in SQUARES.items():
        x, y = sq_xy(sq)
        if s["kind"] == "node":
            d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=(201, 162, 74), outline=INK, width=2)
            text(d, (x, y), sq.lstrip("n"), f_node, fill=INK, anchor="mm")
    for cid, c in CITIES.items():
        x, y = xy(c["lon"], c["lat"])
        d.ellipse([x - 12, y - 12, x + 12, y + 12], fill=INK, outline=(255, 255, 255), width=3)
        dmg = g["loc_damage"].get(cid, 0)
        from .data.locations import CITY_SHORT
        label = CITY_SHORT[cid][0] + (f" ({dmg}٪ ویران)" if dmg else "")
        col = RED if dmg else INK
        if cid == "vienna":
            text(d, (x - 10, y + 16), label, f_city, fill=col, anchor="rt", stroke_width=4, stroke_fill=LAND)
        elif cid == "wagram":
            text(d, (x + 10, y - 16), label, f_city, fill=col, anchor="ls", stroke_width=4, stroke_fill=LAND)
        else:
            text(d, (x, y - 18), label, f_city, fill=col, anchor="ms", stroke_width=4, stroke_fill=LAND)

    for u in g["units_on_map"]:
        x, y = sq_xy(u["square"])
        x += 18
        if u["kind"] == "cannon":
            d.rectangle([x, y - 26, x + 22, y - 4], fill=(30, 30, 30))
            text(d, (x + 11, y - 15), "C", f_small, fill="white", anchor="mm")
        else:
            d.polygon([(x, y - 22), (x + 26, y - 22), (x + 20, y - 6), (x + 6, y - 6)], fill=SEALANE)
            text(d, (x + 13, y - 15), "S", f_small, fill="white", anchor="mm")
        label = u.get("name") or ""
        if gm:
            o = g["players"].get(str(u["owner"]))
            if o:
                label = f"{label} ({o['name'][:10]})"
        if label:
            text(d, (x + 28, y - 15), label[:26], f_small, fill=INK, anchor="lm", stroke_width=3, stroke_fill=LAND)

    for sq, ns in (names or {}).items():
        x, y = sq_xy(sq)
        for i, n in enumerate(ns[:8]):
            text(d, (x + 16, y + 8 + i * 22), n[:16], f_small, fill=(120, 20, 20), anchor="lt", stroke_width=3, stroke_fill=LAND)

    for b in reports or []:
        if b["target"] not in SQUARES:
            continue
        x, y = sq_xy(b["target"])
        seen = "، ".join(b["result"]) if b["result"] else "هیچ‌کس"
        lines = [f"🎈 {b.get('name') or ''}", seen]
        bx, by = x - 10, y + 30
        tw = max(d.textlength(shape(l), font=f_small) for l in lines) + 20
        d.rounded_rectangle([bx - tw / 2, by, bx + tw / 2, by + 52], radius=8, fill=(246, 238, 214), outline=(40, 75, 140), width=3)
        d.line([(x, y + 8), (bx, by)], fill=(40, 75, 140), width=3)
        text(d, (bx, by + 15), lines[0], f_small, fill=(40, 75, 140), anchor="mm")
        text(d, (bx, by + 37), lines[1][:40], f_small, fill=INK, anchor="mm")

    if you and you in SQUARES:
        x, y = sq_xy(you)
        d.ellipse([x - 24, y - 24, x + 24, y + 24], outline=YOU, width=6)

    for sq, n in (highlight or {}).items():
        x, y = sq_xy(sq)
        r = 20
        cx, cy = x + 26, y + 24
        d.line([(x, y), (cx, cy)], fill=PICK, width=5)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PICK, outline="white", width=3)
        text(d, (cx, cy), str(n), f_pin, fill="white", anchor="mm")

    if title:
        d.rectangle([0, 0, W, 52], fill=(21, 51, 42))
        text(d, (20, 26), title, f_title, fill=(230, 205, 132), anchor="lm")
    d.rectangle([2, 2, W - 3, H - 3], outline=INK, width=4)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf
