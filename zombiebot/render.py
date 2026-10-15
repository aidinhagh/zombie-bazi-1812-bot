"""Draw the board as a PNG: coasts, routes, squares, units and (GM version) player positions."""
import io
import math

from PIL import Image, ImageDraw, ImageFont

from . import board
from .board import SQUARES, CITIES, COAST

LON0, LON1, LAT0, LAT1 = -11.5, 41.5, 37.0, 62.4
K = math.cos(math.radians(50))
W = 1800
H = int(W * (LAT1 - LAT0) / ((LON1 - LON0) * K))

SEA, LAND, INK = (166, 190, 186), (239, 228, 200), (58, 40, 22)
ROAD, SEALANE, RED = (150, 100, 52), (40, 75, 140), (170, 30, 30)


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


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


def render(g, gm=False, title=None):
    img = Image.new("RGB", (W, H), SEA)
    d = ImageDraw.Draw(img)
    for ring in COAST:
        pts = [xy(lo, la) for lo, la in ring]
        if len(pts) > 2:
            d.polygon(pts, fill=LAND, outline=(120, 90, 60))
    f_city, f_node, f_small, f_title = font(26), font(15), font(18), font(34)

    for rid, r in board.all_routes(g).items():
        seq = board.route_sequence(r)
        status = board.route_status(g, rid)
        for a, b in zip(seq, seq[1:]):
            pa, pb = sq_xy(a), sq_xy(b)
            if r["kind"] == "sea":
                dashed(d, pa, pb, RED if status == "mined" else SEALANE, 4)
            else:
                if status == "broken":
                    dashed(d, pa, pb, RED, 6, 6, 10)
                else:
                    d.line([pa, pb], fill=ROAD, width=6)
        if status != "ok":
            mid = sq_xy(seq[len(seq) // 2]) if len(seq) > 2 else ((sq_xy(seq[0])[0] + sq_xy(seq[-1])[0]) / 2, (sq_xy(seq[0])[1] + sq_xy(seq[-1])[1]) / 2)
            mx, my = mid
            d.line([(mx - 14, my - 14), (mx + 14, my + 14)], fill=RED, width=6)
            d.line([(mx + 14, my - 14), (mx - 14, my + 14)], fill=RED, width=6)

    for sq, s in SQUARES.items():
        x, y = sq_xy(sq)
        if s["kind"] == "node":
            d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=(201, 162, 74), outline=INK, width=2)
            d.text((x, y), sq.lstrip("n"), fill=INK, font=f_node, anchor="mm")
    for cid, c in CITIES.items():
        x, y = xy(c["lon"], c["lat"])
        d.ellipse([x - 12, y - 12, x + 12, y + 12], fill=INK, outline=(255, 255, 255), width=3)
        dmg = g["loc_damage"].get(cid, 0)
        label = c["name"] + (f"  -{dmg}%" if dmg else "")
        if cid == "vienna":
            d.text((x - 10, y + 16), label, fill=RED if dmg else INK, font=f_city, anchor="rt", stroke_width=4, stroke_fill=LAND)
        elif cid == "wagram":
            d.text((x + 10, y - 16), label, fill=RED if dmg else INK, font=f_city, anchor="ls", stroke_width=4, stroke_fill=LAND)
        else:
            d.text((x, y - 18), label, fill=RED if dmg else INK, font=f_city, anchor="ms", stroke_width=4, stroke_fill=LAND)

    for u in g["units_on_map"]:
        x, y = sq_xy(u["square"])
        x += 18
        if u["kind"] == "cannon":
            d.rectangle([x, y - 26, x + 22, y - 4], fill=(30, 30, 30))
            d.text((x + 11, y - 15), "C", fill="white", font=f_small, anchor="mm")
        else:
            d.polygon([(x, y - 22), (x + 26, y - 22), (x + 20, y - 6), (x + 6, y - 6)], fill=SEALANE)
            d.text((x + 13, y - 15), "S", fill="white", font=f_small, anchor="mm")
        if gm:
            o = g["players"].get(str(u["owner"]))
            if o:
                d.text((x + 28, y - 15), o["name"][:12], fill=INK, font=f_small, anchor="lm")

    if gm:
        at = {}
        for p in g["players"].values():
            if p["alive"] and p.get("pos"):
                at.setdefault(p["pos"], []).append(p["name"][:14])
        for sq, names in at.items():
            x, y = sq_xy(sq)
            for i, n in enumerate(names):
                d.text((x + 16, y + 8 + i * 20), n, fill=(120, 20, 20), font=f_small, anchor="lt", stroke_width=3, stroke_fill=LAND)

    if title:
        d.rectangle([0, 0, W, 52], fill=(21, 51, 42))
        d.text((20, 26), title, fill=(230, 205, 132), font=f_title, anchor="lm")
    d.rectangle([2, 2, W - 3, H - 3], outline=INK, width=4)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf
