"""locations drawn in the same flat TV-cartoon style (vector, cached once per scene), and props (seats)"""
import math
import random

import cairo

from tvtoon import geom as G

LINE = (0.16, 0.10, 0.08)
WORLD_W, WORLD_H, GROUND = 3200, 1080, 960


def _stroke(ctx, w=4):
    ctx.set_source_rgb(*LINE)
    ctx.set_line_width(w)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def _fill(ctx, c, keep=True):
    ctx.set_source_rgb(*G.rgb(c) if isinstance(c, str) else c)
    ctx.fill_preserve() if keep else ctx.fill()


def palm(ctx, x, y, h, rnd):
    ctx.new_path()
    ctx.move_to(x - 10, y)
    ctx.curve_to(x - 6, y - h * 0.5, x + 18, y - h * 0.8, x + 14, y - h)
    ctx.line_to(x + 30, y - h)
    ctx.curve_to(x + 30, y - h * 0.8, x + 12, y - h * 0.5, x + 12, y)
    ctx.close_path()
    _fill(ctx, "#8a6a4a")
    _stroke(ctx, 3)
    cx, cy = x + 22, y - h
    for k in range(9):
        a = -math.pi + k * math.pi / 8 + rnd.uniform(-0.1, 0.1)
        L = h * 0.33
        ctx.new_path()
        ctx.move_to(cx, cy)
        ctx.curve_to(cx + math.cos(a) * L * 0.5, cy + math.sin(a) * L * 0.5 - 40, cx + math.cos(a) * L, cy + math.sin(a) * L * 0.4,
                     cx + math.cos(a) * L * 1.05, cy + math.sin(a) * L * 0.6 + 30)
        ctx.curve_to(cx + math.cos(a) * L * 0.8, cy + math.sin(a) * L * 0.5, cx + math.cos(a) * L * 0.4, cy + math.sin(a) * L * 0.3 - 10,
                     cx, cy + 8)
        _fill(ctx, "#3f8f3a" if k % 2 else "#357a32")
        _stroke(ctx, 2.5)


def banana(ctx, x, y, h):
    ctx.new_path()
    ctx.rectangle(x - 9, y - h * 0.6, 18, h * 0.6)
    _fill(ctx, "#7c9a3a")
    _stroke(ctx, 3)
    for k, a in enumerate((-2.4, -1.9, -1.2, -0.7)):
        ctx.new_path()
        L = h * 0.55
        ctx.move_to(x, y - h * 0.6)
        ex, ey = x + math.cos(a) * L, y - h * 0.6 + math.sin(a) * L
        ctx.curve_to(x + math.cos(a) * L * 0.3 - 30, ey - 20, ex - 20, ey - 30, ex, ey)
        ctx.curve_to(ex + 25, ey + 25, x + math.cos(a) * L * 0.3 + 30, ey + 40, x, y - h * 0.55)
        _fill(ctx, "#5aa845" if k % 2 else "#4c9a3c")
        _stroke(ctx, 2.5)


def hut(ctx, x, y, w, h):
    ctx.new_path()                                          # mud walls
    ctx.rectangle(x, y - h, w, h)
    _fill(ctx, "#c98f5a")
    _stroke(ctx)
    ctx.new_path()
    ctx.rectangle(x, y - h * 0.18, w, h * 0.18)
    _fill(ctx, "#a8703f")
    _stroke(ctx, 3)
    ctx.new_path()                                          # the door
    ctx.rectangle(x + w * 0.42, y - h * 0.72, w * 0.18, h * 0.72)
    _fill(ctx, "#5b3a22")
    _stroke(ctx)
    ctx.new_path()                                          # a window
    ctx.rectangle(x + w * 0.12, y - h * 0.62, w * 0.16, h * 0.2)
    _fill(ctx, "#2f2118")
    _stroke(ctx, 3)
    for k in range(1, 4):
        G.line(ctx, [(x + w * (0.12 + 0.04 * k), y - h * 0.62), (x + w * (0.12 + 0.04 * k), y - h * 0.42)], 3, (0.55, 0.38, 0.2), smooth_it=False)
    ctx.new_path()                                          # the thatched roof (do-chala)
    G.smooth(ctx, [(x - w * 0.12, y - h * 0.92), (x + w * 0.5, y - h * 1.75), (x + w * 1.12, y - h * 0.92),
                   (x + w * 0.5, y - h * 1.02)], tension=0.25)
    _fill(ctx, "#d9b45a")
    _stroke(ctx)
    for k in range(14):
        u = k / 13
        G.line(ctx, [(x - w * 0.1 + u * w * 1.2, y - h * 0.95), (x + w * 0.5 + (u - 0.5) * w * 0.15, y - h * 1.65)], 2, (0.7, 0.55, 0.25), smooth_it=False)


def tulsi(ctx, x, y):
    ctx.new_path()
    ctx.move_to(x - 55, y)
    ctx.line_to(x - 45, y - 120)
    ctx.line_to(x + 45, y - 120)
    ctx.line_to(x + 55, y)
    ctx.close_path()
    _fill(ctx, "#e6d3b3")
    _stroke(ctx)
    ctx.new_path()
    ctx.rectangle(x - 60, y - 135, 120, 18)
    _fill(ctx, "#d9c3a0")
    _stroke(ctx, 3)
    for k in range(7):
        a = -math.pi / 2 + (k - 3) * 0.35
        ctx.new_path()
        G.ellipse(ctx, x + math.cos(a) * 40, y - 150 + math.sin(a) * 40, 22, 12, a)
        _fill(ctx, "#3f7d2f")
        _stroke(ctx, 2)


def pot(ctx, x, y, r):
    ctx.new_path()
    G.ellipse(ctx, x, y - r, r, r * 0.9)
    _fill(ctx, "#b5562f")
    _stroke(ctx, 3)
    ctx.new_path()
    ctx.rectangle(x - r * 0.45, y - r * 2.05, r * 0.9, r * 0.3)
    _fill(ctx, "#a24a28")
    _stroke(ctx, 3)


def village_courtyard(seed=3):
    rnd = random.Random(seed)
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, WORLD_W, WORLD_H)
    ctx = cairo.Context(surf)
    g = cairo.LinearGradient(0, 0, 0, GROUND)
    g.add_color_stop_rgb(0, *G.rgb("#8ec9f0"))
    g.add_color_stop_rgb(1, *G.rgb("#d8eef7"))
    ctx.set_source(g)
    ctx.paint()
    for cx, cy, r in ((420, 160, 60), (1500, 120, 75), (2600, 190, 55)):    # clouds
        ctx.new_path()
        for dx, dy, rr in ((-1, 0, 0.8), (0, -0.4, 1.0), (1, 0, 0.85), (0.4, 0.2, 0.9), (-0.5, 0.2, 0.9)):
            G.ellipse(ctx, cx + dx * r, cy + dy * r, r * rr * 1.1, r * rr * 0.75)
        _fill(ctx, "#ffffff", keep=False)
    ctx.new_path()                                          # far tree line
    pts = [(0, 640)]
    for i in range(33):
        pts.append((i * 100, 560 + rnd.uniform(-40, 30)))
    pts += [(WORLD_W, 640)]
    G.smooth(ctx, pts + [(WORLD_W, 700), (0, 700)], tension=0.4)
    _fill(ctx, "#6fae5c", keep=False)
    for x in (180, 900, 1900, 2950):
        palm(ctx, x, 700, 470 + rnd.uniform(-40, 40), rnd)
    ctx.new_path()                                          # courtyard ground
    ctx.rectangle(0, 690, WORLD_W, WORLD_H - 690)
    gg = cairo.LinearGradient(0, 690, 0, WORLD_H)
    gg.add_color_stop_rgb(0, *G.rgb("#d9b98c"))
    gg.add_color_stop_rgb(1, *G.rgb("#c9a172"))
    ctx.set_source(gg)
    ctx.fill()
    hut(ctx, 380, 760, 620, 330)
    hut(ctx, 2300, 740, 520, 290)
    banana(ctx, 1200, 760, 330)
    banana(ctx, 2140, 750, 280)
    tulsi(ctx, 1640, 790)
    pot(ctx, 1090, 790, 26)
    pot(ctx, 1040, 795, 20)
    ctx.new_path()                                          # a bamboo fence at the back
    for i in range(0, WORLD_W, 46):
        if 360 < i < 1020 or 2280 < i < 2840:
            continue
        ctx.rectangle(i, 650, 14, 110)
    _fill(ctx, "#c2a265")
    _stroke(ctx, 2)
    for k in range(60):                                     # ground texture
        x, y = rnd.uniform(0, WORLD_W), rnd.uniform(800, WORLD_H)
        G.line(ctx, [(x, y), (x + rnd.uniform(15, 40), y + rnd.uniform(-2, 2))], 2, G.rgb("#b8905f"), smooth_it=False)
    return surf


LOCATIONS = {"village_courtyard": village_courtyard}


def mora(ctx, x, ground, seat_h, w):
    """a Bengali cane stool (mora): hourglass body, round seat"""
    top = ground - seat_h
    ctx.new_path()
    ctx.move_to(x - w * 0.5, top)
    ctx.curve_to(x - w * 0.22, top + seat_h * 0.45, x - w * 0.22, top + seat_h * 0.55, x - w * 0.5, ground)
    ctx.line_to(x + w * 0.5, ground)
    ctx.curve_to(x + w * 0.22, top + seat_h * 0.55, x + w * 0.22, top + seat_h * 0.45, x + w * 0.5, top)
    ctx.close_path()
    _fill(ctx, "#c99a5b")
    _stroke(ctx, 3)
    for k in range(-3, 4):
        G.line(ctx, [(x + k * w * 0.13, top), (x + k * w * 0.05, top + seat_h * 0.5), (x + k * w * 0.13, ground)], 1.6,
               G.rgb("#9b7038"))
    ctx.new_path()
    G.ellipse(ctx, x, top, w * 0.52, w * 0.12)
    _fill(ctx, "#d8ae6e")
    _stroke(ctx, 3)
    ctx.new_path()
    G.ellipse(ctx, x, ground, w * 0.6, w * 0.06)
    ctx.set_source_rgba(0, 0, 0, 0.18)
    ctx.fill()
