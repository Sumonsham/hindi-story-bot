"""cairo drawing helpers: smooth closed curves, tapered capsules, colours"""
import math

import cairo


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def shade(c, f):
    """darker (f<1) or lighter (f>1) version of a colour"""
    if isinstance(c, str):
        c = rgb(c)
    if f <= 1:
        return tuple(max(0.0, x * f) for x in c)
    return tuple(min(1.0, x + (1 - x) * (f - 1)) for x in c)


def smooth(ctx, pts, closed=True, tension=0.5):
    """Catmull-Rom spline through the points as cubic beziers (the cartoon 'smooth curve')"""
    n = len(pts)
    if n < 2:
        return
    ctx.move_to(*pts[0])
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0 = pts[(i - 1) % n] if (closed or i > 0) else pts[i]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if (closed or i + 2 < n) else p2
        k = tension / 3.0 * 2
        c1 = (p1[0] + (p2[0] - p0[0]) * k / 2, p1[1] + (p2[1] - p0[1]) * k / 2)
        c2 = (p2[0] - (p3[0] - p1[0]) * k / 2, p2[1] - (p3[1] - p1[1]) * k / 2)
        ctx.curve_to(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])
    if closed:
        ctx.close_path()


def capsule(ctx, length, r0, r1, bulge=0.0):
    """a limb segment along +y from (0,0) to (0,length): round ends of radius r0 and r1 (joints overlap: no gaps)"""
    pts = []
    for i in range(9):                                     # the top cap
        a = math.pi + math.pi * i / 8
        pts.append((r0 * math.cos(a), r0 * math.sin(a)))
    mid = length * 0.45
    pts.insert(0, (-r0 - bulge, 0))
    rm = (r0 + r1) / 2 + bulge
    side_r = [(rm, mid)]
    for i in range(9):                                     # the bottom cap
        a = math.pi * i / 8
        side_r.append((r1 * math.cos(a), length + r1 * math.sin(a)))
    ctx.move_to(-r0, 0)
    ctx.arc(0, 0, r0, math.pi, 2 * math.pi)
    ctx.curve_to(r0, length * 0.3, rm, length * 0.55, r1, length)
    ctx.arc(0, length, r1, 0, math.pi)
    ctx.curve_to(-rm, length * 0.55, -r0, length * 0.3, -r0, 0)
    ctx.close_path()


def ellipse(ctx, cx, cy, rx, ry, ang=0.0):
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(ang)
    ctx.scale(max(rx, 1e-3), max(ry, 1e-3))
    ctx.new_sub_path()
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()


def line(ctx, pts, w, col, cap=cairo.LINE_CAP_ROUND, smooth_it=True):
    ctx.save()
    ctx.new_path()
    if smooth_it and len(pts) > 2:
        smooth(ctx, pts, closed=False)
    else:
        ctx.move_to(*pts[0])
        for p in pts[1:]:
            ctx.line_to(*p)
    ctx.set_source_rgb(*col)
    ctx.set_line_width(w)
    ctx.set_line_cap(cap)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()
    ctx.restore()


def lerp(a, b, t):
    return a + (b - a) * t


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)
