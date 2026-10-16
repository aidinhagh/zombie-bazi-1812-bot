"""guillotine.py — the vote animation: a name on a banner in the lunette, the blade drops and cuts it in two.

make_gif(word, seed=None, photo=None, lightning=False) -> GIF bytes  (same signature as the old sand animator)
With lightning=True the bolt strikes the guillotine, the blade jams halfway and the name survives (a void vote).
Pure Pillow; Persian text shaped with the animator's helpers.
"""
import io
import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .animator import _load_font, shape, text_kwargs

W, H = 420, 520
FPS = 20
TOTAL = 64
T_DROP = 18          # rope released
T_HIT = 24           # blade reaches the lunette
T_SPLIT = 25

SKY_TOP, SKY_LOW = (34, 18, 26), (128, 52, 36)
WOOD, WOOD_DARK, WOOD_HI = (104, 64, 34), (62, 36, 18), (150, 98, 56)
STEEL, STEEL_HI, STEEL_DARK = (176, 182, 188), (232, 236, 240), (96, 102, 110)
PARCH, INK = (236, 222, 186), (40, 22, 12)
BLOOD, BLOOD_DARK = (160, 14, 18), (96, 6, 10)

POST_L, POST_R = 118, 302         # inner edges of the posts
POST_W = 22
TOP_Y = 58
LUNETTE_Y = 330
BLADE_H = 70
BANNER = (POST_L + 6, LUNETTE_Y - 34, POST_R - 6, LUNETTE_Y + 30)


def lerp(a, b, t):
    return a + (b - a) * t


def ease_in(t):
    return t * t * t


def build_backdrop(rng, photo):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = min(1, y / (H * .72))
        d.line([(0, y), (W, y)], fill=tuple(int(lerp(SKY_TOP[i], SKY_LOW[i], t)) for i in range(3)))
    if photo:
        try:
            ph = Image.open(io.BytesIO(photo)).convert("L").resize((W, W))
            ph = ph.filter(ImageFilter.GaussianBlur(2)).convert("RGB")
            tint = Image.new("RGB", ph.size, (150, 70, 50))
            ph = Image.blend(ph, tint, .55)
            mask = Image.new("L", ph.size, 0)
            ImageDraw.Draw(mask).ellipse([30, 30, W - 30, W - 30], fill=70)
            mask = mask.filter(ImageFilter.GaussianBlur(40))
            img.paste(ph, (0, 10), mask)
        except Exception:
            pass
    # setting sun and smoke
    sun = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sun).ellipse([W * .62, H * .30, W * .62 + 120, H * .30 + 120], fill=120)
    img = Image.composite(Image.new("RGB", (W, H), (226, 120, 60)), img, sun.filter(ImageFilter.GaussianBlur(26)))
    d = ImageDraw.Draw(img)
    # rooftops of Paris
    x = 0
    while x < W:
        w = rng.randint(30, 70)
        h = rng.randint(40, 110)
        d.rectangle([x, H * .70 - h, x + w, H * .78], fill=(30, 16, 20))
        if rng.random() < .5:
            d.polygon([(x, H * .70 - h), (x + w / 2, H * .70 - h - 22), (x + w, H * .70 - h)], fill=(30, 16, 20))
        x += w
    # scaffold platform and crowd
    d.rectangle([0, H * .78, W, H], fill=(24, 14, 12))
    d.rectangle([60, 410, W - 60, 432], fill=WOOD_DARK)
    for i in range(14):
        cx = rng.randint(-10, W + 10)
        r = rng.randint(14, 22)
        d.ellipse([cx - r, 448 - r, cx + r, 448 + r], fill=(14, 8, 8))
        d.rectangle([cx - r - 6, 448, cx + r + 6, H], fill=(14, 8, 8))
    return img


def draw_frame_structure(d):
    # posts with grooves, crossbar, base
    for x in (POST_L - POST_W, POST_R):
        d.rectangle([x, TOP_Y, x + POST_W, 412], fill=WOOD, outline=WOOD_DARK, width=2)
        d.line([(x + POST_W // 2, TOP_Y + 6), (x + POST_W // 2, 404)], fill=WOOD_DARK, width=2)
        d.line([(x + 4, TOP_Y + 4), (x + 4, 408)], fill=WOOD_HI, width=1)
    d.rectangle([POST_L - POST_W - 16, TOP_Y - 18, POST_R + POST_W + 16, TOP_Y + 4], fill=WOOD, outline=WOOD_DARK, width=2)
    d.rectangle([POST_L - POST_W - 24, TOP_Y - 26, POST_R + POST_W + 24, TOP_Y - 18], fill=WOOD_DARK)
    # lunette board
    d.rectangle([POST_L, LUNETTE_Y + 30, POST_R, LUNETTE_Y + 52], fill=WOOD, outline=WOOD_DARK, width=2)
    # basket
    d.pieslice([170, 380, 250, 430], 0, 180, fill=(92, 62, 30), outline=WOOD_DARK)


def draw_blade(d, y):
    """The blade's top edge at y; the cutting edge slants."""
    x0, x1 = POST_L + 2, POST_R - 2
    d.rectangle([x0, y - 40, x1, y], fill=(70, 70, 76))                              # weight
    d.polygon([(x0, y), (x1, y), (x1, y + BLADE_H - 34), (x0, y + BLADE_H)], fill=STEEL)
    d.polygon([(x0, y + BLADE_H - 12), (x1, y + BLADE_H - 46), (x1, y + BLADE_H - 34), (x0, y + BLADE_H)], fill=STEEL_HI)
    d.line([(x0, y), (x1, y)], fill=STEEL_DARK, width=2)
    # rope up to the crossbar
    d.line([((x0 + x1) / 2, TOP_Y + 4), ((x0 + x1) / 2, y - 40)], fill=(190, 160, 110), width=3)


def banner_image(word):
    bw, bh = BANNER[2] - BANNER[0], BANNER[3] - BANNER[1]
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, bw - 1, bh - 1], fill=PARCH + (255,), outline=INK + (255,), width=3)
    d.rectangle([5, 5, bw - 6, bh - 6], outline=(150, 110, 70, 255), width=1)
    text = shape(word)
    for size in range(44, 12, -1):
        f = _load_font(size)
        box = f.getbbox(text, **text_kwargs())
        if box[2] - box[0] <= bw - 24 and box[3] - box[1] <= bh - 12:
            break
    d.text((bw / 2, bh / 2), text, font=f, fill=INK + (255,), anchor="mm", **text_kwargs())
    return img


def draw_lightning(d, rng, power):
    x = rng.randint(POST_L + 30, POST_R - 30)
    y = 0
    pts = [(x, y)]
    while y < TOP_Y + 90:
        y += rng.randint(14, 26)
        x += rng.randint(-22, 22)
        pts.append((x, y))
    d.line(pts, fill=(255, 255, 220), width=int(6 * power) + 1)
    d.line(pts, fill=(170, 200, 255), width=2)


def render_frames(word, seed=None, photo=None, lightning=False):
    rng = random.Random(seed if seed is not None else hash(word) & 0xffff)
    back = build_backdrop(rng, photo)
    banner = banner_image(word)
    bw, bh = banner.size
    cut_x = bw // 2
    left, right = banner.crop((0, 0, cut_x, bh)), banner.crop((cut_x, 0, bw, bh))
    drops = [(rng.uniform(-1.6, 1.6), rng.uniform(-3, 0), rng.randint(3, 7)) for _ in range(26)]
    blade_top_rest = TOP_Y + 48
    blade_hit = LUNETTE_Y - BLADE_H + 32
    jam = (blade_top_rest + blade_hit) / 2
    frames = []
    for f in range(TOTAL):
        img = back.copy()
        d = ImageDraw.Draw(img)
        draw_frame_structure(d)
        shake = 0
        if f < T_DROP:
            by = blade_top_rest + math.sin(f * .5) * 1.5
        elif f < T_HIT:
            t = (f - T_DROP) / (T_HIT - T_DROP)
            by = lerp(blade_top_rest, jam if lightning else blade_hit, ease_in(t) if not lightning else t)
        else:
            by = jam if lightning else blade_hit
            if not lightning and f < T_HIT + 4:
                shake = (T_HIT + 4 - f) * 2
        cut = not lightning and f >= T_SPLIT
        if not cut:
            img.paste(banner, (BANNER[0] + shake, BANNER[1]), banner)
        else:
            t = (f - T_SPLIT) / (TOTAL - T_SPLIT)
            fall = 420 * t * t + 40 * t
            for half, sign, x0 in ((left, -1, BANNER[0]), (right, 1, BANNER[0] + cut_x)):
                rot = half.rotate(sign * -min(70, 140 * t), expand=True, resample=Image.BICUBIC)
                img.paste(rot, (int(x0 + sign * 60 * t - (rot.width - half.width) / 2), int(BANNER[1] + fall)), rot)
            # blood
            for k, (vx, vy, r) in enumerate(drops):
                tt = (f - T_SPLIT) / 10
                if tt <= 0:
                    continue
                x = W / 2 + vx * 40 * tt
                y = LUNETTE_Y + 10 + (vy * 30 * tt + 60 * tt * tt)
                if y < 440:
                    d.ellipse([x - r, y - r, x + r, y + r], fill=BLOOD if k % 3 else BLOOD_DARK)
            pool = min(1, (f - T_SPLIT) / 24)
            d.ellipse([W / 2 - 90 * pool, 404, W / 2 + 90 * pool, 404 + 14 * pool], fill=BLOOD_DARK)
            d.rectangle([BANNER[0] + cut_x - 2, LUNETTE_Y - 6, BANNER[0] + cut_x + 2, LUNETTE_Y + 30], fill=BLOOD)
        draw_blade(d, by)
        if lightning and T_HIT - 4 <= f <= T_HIT + 8:
            draw_lightning(d, rng, 1 - abs(f - T_HIT) / 10)
        if f == T_HIT or (lightning and f in (T_HIT, T_HIT + 3)):
            flash = Image.new("RGB", (W, H), (255, 245, 220) if not lightning else (220, 230, 255))
            img = Image.blend(img, flash, .55)
        frames.append(img)
    return frames


def make_gif(word, seed=None, photo=None, lightning=False):
    frames = render_frames(word, seed, photo, lightning)
    master = frames[T_SPLIT + 6].convert("P", palette=Image.ADAPTIVE, colors=120)
    pal = [fr.quantize(palette=master, dither=Image.Dither.NONE) for fr in frames]
    durations = [int(1000 / FPS)] * len(pal)
    durations[-1] = 1600
    buf = io.BytesIO()
    pal[0].save(buf, format="GIF", save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True, disposal=1)
    return buf.getvalue()


if __name__ == "__main__":
    import sys
    word = sys.argv[1] if len(sys.argv) > 1 else "مریم"
    fr = render_frames(word, 3)
    fr[10].save("g_before.png")
    fr[T_SPLIT + 10].save("g_after.png")
    open("guillotine.gif", "wb").write(make_gif(word, 3))
    open("guillotine_lightning.gif", "wb").write(make_gif(word, 3, lightning=True))
