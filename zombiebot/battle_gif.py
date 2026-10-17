"""battle_gif.py — the cannon-duel result for the group: a side view of the field, the last round flies,
the losing gun blows up. Shows unit names and the (random) flags the other players saw — never a player.

make_gif(winner, losers, city_fa, time, weather, seed) -> GIF bytes
  winner: {"name", "flag"} or None (everyone destroyed); losers: [{"name", "flag"}]
"""
import io
import math
import random

from PIL import Image, ImageDraw

from .animator import _load_font, shape, text_kwargs

W, H = 480, 300
FRAMES = 54
T_FIRE, T_HIT = 8, 30

SKIES = {
    "dawn": ((70, 80, 130), (236, 160, 110)), "morning": ((70, 120, 190), (190, 212, 236)),
    "noon": ((50, 105, 180), (200, 222, 242)), "dusk": ((44, 50, 100), (236, 128, 74)),
    "night": ((6, 10, 22), (26, 38, 62)),
}
GREY = {"overcast": .55, "fog": .8, "rain": .7, "snow": .6, "storm": .85}
FLAGS = {
    "fr": [(37, 67, 155), (239, 234, 223), (196, 47, 41)], "ru": [(239, 234, 223), (44, 78, 160), (196, 47, 41)],
    "at": [(27, 27, 27), (232, 196, 58)], "pr": [(27, 27, 27), (239, 234, 223), (27, 27, 27)],
    "es": [(196, 47, 41), (232, 196, 58), (196, 47, 41)], "se": [(44, 94, 160)], "ot": [(196, 47, 41)], "gb": [(29, 52, 116)],
}
VERTICAL = {"fr"}


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(lerp(c1[i], c2[i], t)) for i in range(3))


def draw_flag(d, x, y, kind, wave=0.0):
    w, h = 30, 20
    cols = FLAGS.get(kind, FLAGS["gb"])
    for i, c in enumerate(cols):
        if kind in VERTICAL:
            d.rectangle([x + i * w / len(cols), y, x + (i + 1) * w / len(cols), y + h], fill=c)
        else:
            d.rectangle([x, y + i * h / len(cols), x + w, y + (i + 1) * h / len(cols)], fill=c)
    if kind == "gb":
        d.line([x, y, x + w, y + h], fill=(239, 234, 223), width=4)
        d.line([x + w, y, x, y + h], fill=(239, 234, 223), width=4)
        d.rectangle([x + 12, y, x + 18, y + h], fill=(239, 234, 223))
        d.rectangle([x, y + 7, x + w, y + 13], fill=(239, 234, 223))
        d.rectangle([x + 13.5, y, x + 16.5, y + h], fill=(196, 47, 41))
        d.rectangle([x, y + 8.5, x + w, y + 11.5], fill=(196, 47, 41))
    elif kind == "ot":
        d.ellipse([x + 6, y + 4, x + 18, y + 16], fill=(239, 234, 223))
        d.ellipse([x + 9, y + 4, x + 20, y + 15], fill=(196, 47, 41))
        d.regular_polygon((x + 22, y + 10, 3), 5, fill=(239, 234, 223))
    elif kind == "se":
        d.rectangle([x + 8, y, x + 12, y + h], fill=(232, 196, 58))
        d.rectangle([x, y + 8, x + w, y + 12], fill=(232, 196, 58))


def draw_gun(d, x, ground, facing, kind, wreck=0.0, recoil=0.0):
    """A field gun seen from the side. facing = +1 (to the right) or -1."""
    x -= facing * recoil * 6
    wheel = (60, 42, 26)
    tilt = wreck * 0.6
    # trail
    d.line([x - facing * 26, ground - 2, x, ground - 12], fill=(86, 64, 40), width=6)
    # barrel
    ang = -0.32 + tilt
    bx, by = x + facing * 2, ground - 16
    ex, ey = bx + facing * 34 * math.cos(ang), by + 34 * math.sin(ang)
    d.line([bx, by, ex, ey], fill=(176, 138, 72) if wreck < 1 else (70, 60, 50), width=8)
    # wheel
    d.ellipse([x - 11, ground - 22, x + 11, ground], outline=wheel, width=4)
    for k in range(6):
        a = k * math.pi / 3 + wreck
        d.line([x, ground - 11, x + 10 * math.cos(a), ground - 11 + 10 * math.sin(a)], fill=wheel, width=2)
    # staff and flag
    sx = x - facing * 30
    d.line([sx, ground, sx, ground - 58], fill=(70, 50, 30), width=2)
    if wreck < 1:
        draw_flag(d, sx + (2 if facing > 0 else -32), ground - 58, kind)
    return ex, ey


def label(img, text, cx, y, size=17, color=(240, 232, 214)):
    d = ImageDraw.Draw(img)
    f = _load_font(size)
    t = shape(text)
    kw = text_kwargs()
    w = d.textlength(t, font=f, **kw)
    d.text((cx - w / 2 + 1, y + 1), t, font=f, fill=(0, 0, 0), **kw)
    d.text((cx - w / 2, y), t, font=f, fill=color, **kw)


def make_gif(winner, losers, city_fa="", tod="noon", weather="clear", seed=1):
    rng = random.Random(seed)
    top, low = SKIES.get(tod, SKIES["noon"])
    g = GREY.get(weather, 0)
    top, low = mix(top, (120, 124, 130), g * (0.3 if tod == "night" else 1)), mix(low, (150, 154, 160), g * (0.3 if tod == "night" else 1))
    base = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(base)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=mix(top, low, min(1, y / (H * .7))))
    if tod == "night":
        for _ in range(60):
            x, y = rng.randrange(W), rng.randrange(int(H * .5))
            d.point((x, y), fill=(220, 224, 236))
    # hills
    ground_col = (226, 230, 236) if weather == "snow" else ((58, 70, 40) if tod != "night" else (22, 28, 20))
    far = mix(ground_col, low, .45)
    pts = [(0, H)] + [(x, H * .62 + math.sin(x / 47 + seed) * 14 + math.sin(x / 19) * 4) for x in range(0, W + 8, 8)] + [(W, H)]
    d.polygon(pts, fill=far)
    gy = lambda x: H * .78 + math.sin(x / 63 + seed * .3) * 6
    pts = [(0, H)] + [(x, gy(x)) for x in range(0, W + 8, 8)] + [(W, H)]
    d.polygon(pts, fill=ground_col)

    shooter_x = 80
    targets = losers or []
    tx = [W - 90 - i * 70 for i in range(len(targets))] or [W - 90]
    frames = []
    smoke = []
    precip = [(rng.randrange(W), rng.randrange(H)) for _ in range(90)] if weather in ("rain", "storm", "snow") else []
    for f in range(FRAMES):
        im = base.copy()
        dd = ImageDraw.Draw(im)
        if f in (T_HIT, T_HIT + 1) or (weather == "storm" and f == 14):
            dd.rectangle([0, 0, W, H], fill=None)
            im = Image.blend(im, Image.new("RGB", (W, H), (255, 236, 200)), .35)
            dd = ImageDraw.Draw(im)
        recoil = max(0, 1 - (f - T_FIRE) / 6) if f >= T_FIRE else 0
        if winner:
            mx, my = draw_gun(dd, shooter_x, gy(shooter_x), 1, winner["flag"], recoil=recoil)
            label(im, f"«{winner['name']}»", shooter_x, gy(shooter_x) + 8)
        else:
            mx, my = shooter_x + 30, gy(shooter_x) - 26
        for i, L in enumerate(targets):
            wreck = 0 if f < T_HIT else min(1, (f - T_HIT) / 6)
            draw_gun(dd, tx[i], gy(tx[i]), -1, L["flag"], wreck=wreck)
            label(im, f"«{L['name']}»", tx[i], gy(tx[i]) + 8, color=(255, 200, 180) if f >= T_HIT else (240, 232, 214))
        # muzzle flash and smoke
        if T_FIRE <= f < T_FIRE + 3:
            dd.ellipse([mx - 12, my - 10, mx + 14, my + 10], fill=(255, 210, 120))
        if f == T_FIRE:
            smoke += [[mx + rng.uniform(-4, 8), my + rng.uniform(-4, 4), rng.uniform(6, 10), 0] for _ in range(6)]
        # the round in flight
        if T_FIRE <= f < T_HIT and targets:
            t = (f - T_FIRE) / (T_HIT - T_FIRE)
            ex, ey = tx[0], gy(tx[0]) - 14
            x = lerp(mx, ex, t)
            y = lerp(my, ey, t) - math.sin(t * math.pi) * 90
            dd.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(20, 20, 20))
        # explosions
        if f >= T_HIT:
            k = f - T_HIT
            for i in range(len(targets)):
                cx, cy = tx[i], gy(tx[i]) - 14
                if k < 10:
                    r = 8 + k * 5
                    dd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=mix((255, 230, 140), (200, 70, 30), k / 10))
                if k == 0:
                    smoke += [[cx + rng.uniform(-14, 14), cy + rng.uniform(-10, 4), rng.uniform(8, 16), 0] for _ in range(10)]
                if k > 4 and f % 3 == 0:
                    smoke.append([cx + rng.uniform(-6, 6), cy - 6, rng.uniform(5, 9), 0])
        for s in smoke:
            s[3] += 1
            s[1] -= 0.8
            s[0] += 0.4
            r = s[2] + s[3] * 0.7
            shade = int(min(200, 60 + s[3] * 5))
            dd.ellipse([s[0] - r, s[1] - r, s[0] + r, s[1] + r], fill=(shade, shade, shade))
        smoke = [s for s in smoke if s[3] < 40]
        for (px, py) in precip:
            yy = (py + f * (14 if weather != "snow" else 3)) % H
            if weather == "snow":
                dd.ellipse([px - 1.5, yy - 1.5, px + 1.5, yy + 1.5], fill=(245, 245, 250))
            else:
                dd.line([px, yy, px - 3, yy + 9], fill=(170, 180, 200))
        if weather == "fog":
            im = Image.blend(im, Image.new("RGB", (W, H), (180, 184, 190)), .35)
        # caption
        cap = ImageDraw.Draw(im)
        cap.rectangle([0, 0, W, 34], fill=(18, 22, 30))
        if f < T_HIT + 12:
            label(im, f"نبرد توپخانه · {city_fa}", W / 2, 7, size=16, color=(230, 205, 132))
        else:
            txt = f"«{winner['name']}» پیروز شد" if winner else "همه توپ‌ها منهدم شدند"
            label(im, txt, W / 2, 5, size=19, color=(255, 236, 190))
        frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=96))
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=[80] * (FRAMES - 1) + [2600], loop=0, optimize=True)
    return out.getvalue()
