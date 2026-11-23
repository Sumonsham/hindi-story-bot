"""TRUE SIDE VIEW (profile) of every tvtoon character (23 Nov 2026).

The front / three-quarter puppet (puppet.py) cannot walk or ride convincingly: real TV animation and cinema show a
walk, a run, a cycle ride and two people talking face to face FROM THE SIDE. This module draws the same character
(its own proportions, colours, hair style, costume, face details from characters.py) in profile:

  * head in profile: forehead, brow ridge, the character's own nose shape sticking out, lips, chin, jaw, ear; one eye
    (blinks, looks, lid states), brow states, profile mouth shapes from the same visemes (the jaw really drops);
  * walk and run: contact - down - passing - up, planted feet (no sliding), heel strike and toe-off, knees bending
    forward, opposite arm swing, hip bob, lean; hanging hair and saree trail;
  * sitting in profile: thighs forward, knees bent, feet on the floor (benches, seats);
  * cycling: hips on the saddle, feet on the turning pedals (IK), hands on the handlebar, body leaning forward;
  * riding bike / auto / toto: hands on the bars, feet on pegs / the floor; passengers sit with hands on the thighs;
  * looking back over the shoulder (the head turns round, the body keeps going);
  * gestures in profile: explain, point, wave, scared, namaste, think, hands on hips, shrug.

Coordinates: character units of puppet.proportions, feet on y = 0, facing +x (the scene mirrors for facing left).
The animator puts st['side'] = {'d': +1/-1, 'mode': 'stand'|'walk'|'sit'|'pedal'|'ride', ...}."""
import math

import cairo

from tvtoon import geom as G
from tvtoon.puppet import BROWS, HEAD_SHAPES, LINE, VISEMES

D = math.radians


def _pt(p, ang, ln):
    """the end of a bone of length ln starting at p, angle from straight down, positive = forward (+x)"""
    return (p[0] + math.sin(ang) * ln, p[1] + math.cos(ang) * ln)


def _ang(a, b):
    return math.atan2(b[0] - a[0], b[1] - a[1])


def ik(a, b, l1, l2, pref):
    """two-bone IK in the plane: (middle joint, end) for a chain a -> b; the middle joint bends toward pref"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    dd = math.hypot(dx, dy)
    d = max(1e-6, min(l1 + l2 - 1e-3, dd))
    ux, uy = (dx / dd, dy / dd) if dd > 1e-6 else (0.0, 1.0)
    al = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, l1 * l1 - al * al))
    s = 1.0 if (-uy * pref[0] + ux * pref[1]) >= 0 else -1.0
    mid = (a[0] + ux * al - s * uy * h, a[1] + uy * al + s * ux * h)
    return mid, (a[0] + ux * d, a[1] + uy * d)


def _limb(ctx, p0, p1, r0, r1):
    ln = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    ctx.save()
    ctx.translate(*p0)
    ctx.rotate(math.atan2(-(p1[0] - p0[0]), p1[1] - p0[1]))
    G.capsule(ctx, max(ln, 1e-3), r0, r1)
    ctx.restore()


def _group(ctx, parts, lw):
    """outline every part of a group first, then fill them: the parts of one limb join without seams"""
    for path, _col, _det in parts:
        ctx.new_path()
        path()
        ctx.set_source_rgb(*LINE)
        ctx.set_line_width(lw * 2.0)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()
    for path, col, det in parts:
        ctx.new_path()
        path()
        ctx.set_source_rgb(*col)
        ctx.fill()
        if det:
            det()


def _female(spec):
    return "female" in str(spec.get("category", "")) or spec["costume"]["type"] in ("saree", "frock") or \
        bool(spec["face"].get("lashes"))


# ------------------------------------------------------------------------------------------------- the pose

GESTURE_SIDE = {   # name -> near arm (upper, forearm) angles, far arm or None, hand shape
    "explain": ((D(28), D(95)), None, "open"),
    "point": ((D(80), D(88)), None, "point"),
    "point_up": ((D(140), D(160)), None, "point"),
    "wave": ((D(150), D(175)), None, "open"),
    "raise_hand": ((D(150), D(170)), None, "open"),
    "scared": ((D(30), D(140)), (D(25), D(135)), "open"),
    "namaste": ((D(18), D(125)), (D(14), D(125)), "open"),
    "clap": ((D(25), D(105)), (D(20), D(105)), "open"),
    "think": ((D(15), D(160)), None, "fist"),
    "hips": ((D(-28), D(40)), (D(-28), D(40)), "fist"),
    "shrug": ((D(8), D(75)), (D(8), D(75)), "open"),
    "belly_laugh": ((D(10), D(70)), (D(10), D(70)), "open"),
}


def solve(pp, st):
    """all joint positions of the side pose (character units, facing +x)"""
    P, spec = pp.P, pp.spec
    sd = st["side"]
    mode = sd.get("mode", "stand")
    leg, th, sh, fh, H = P["leg"], P["thigh"], P["shin"], P["foot_h"], P["H"]
    fl = P["head_h"] * 0.46 * spec["body"].get("foot", 1.0)
    stoop = P.get("stoop", 0.0)
    t = sd.get("t", 0.0)
    J = {"fl": fl}
    lean = D(2) + D(stoop * 60)
    hip = (0.0, -leg * 0.985)
    ankles, fang = {}, {}
    arm = {"near": (D(4) + D(1.2) * math.sin(t * 1.7), D(12)), "far": (D(-4), D(8))}
    hands = {"near": "relax", "far": "relax"}
    hand_t = {}
    pref_knee = (1.0, 0.0)
    if mode == "walk":
        wk = sd["walk"]
        S, duty, run = wk["S"], wk["duty"], wk["run"]
        ph = wk["phase"]
        lean = D(13 if run else 4) + D(stoop * 60)
        bob = (math.cos(4 * math.pi * (ph - duty / 2)) * 0.013 * H) if not run else \
            (-0.03 * H * abs(math.cos(2 * math.pi * ph)))
        hip = (0.0, -leg * (0.955 if not run else 0.93) - bob)
        for side, off in (("near", 0.0), ("far", 0.5)):
            q = (ph + off) % 1.0
            if q < duty:                                     # stance: the foot is planted (moves back with the body)
                u = q / duty
                fx = -(q - duty / 2) * S
                lift = 0.0
                a_ = D(16) * max(0.0, 1 - u / 0.14) if u < 0.14 else (-D(38) * ((u - 0.68) / 0.32) if u > 0.68 else 0.0)
            else:                                            # swing: the foot arcs forward
                u = (q - duty) / (1 - duty)
                fx = -duty / 2 * S + (u * u * (3 - 2 * u)) * duty * S
                lift = math.sin(math.pi * u) * H * (0.045 if not run else 0.1)
                a_ = -D(25) * (1 - u) + D(14) * u
            ay = -fh - lift
            if a_ < 0:                                       # toe-off: the heel rises, the foot turns on the toe
                ay -= fl * 0.62 * math.sin(-a_)
            ankles[side] = (fx, ay)
            fang[side] = a_
        A = D(30 if run else 20)
        c_ = math.cos(2 * math.pi * ph)
        arm["near"] = (-A * c_, D(80 if run else 14) + D(18) * max(0.0, -c_))
        arm["far"] = (A * c_, D(80 if run else 14) + D(18) * max(0.0, c_))
        if run:
            hands = {"near": "fist", "far": "fist"}
    elif mode == "sit":
        a, seat = sd.get("sit", (1.0, leg * 0.6))
        hip = (-0.06 * leg * a, -(leg * 0.985 + (seat - leg * 0.985) * a))
        for side, off in (("near", 0.0), ("far", -0.05 * leg)):
            ankles[side] = (off + (th * 0.95) * a + 0.02 * leg * (1 - a), -fh)
            fang[side] = 0.0
        lean = D(3) + D(stoop * 60) + D(22) * math.sin(math.pi * min(1.0, a))
        if a > 0.6:                                          # hands rest on the thighs
            k_ = _pt(hip, D(88), th)
            hand_t["near"] = (hip[0] + (k_[0] - hip[0]) * 0.72, hip[1] - P["leg_r"] * 1.2)
            hand_t["far"] = (hip[0] + (k_[0] - hip[0]) * 0.62, hip[1] - P["leg_r"] * 1.0)
    elif mode in ("pedal", "ride"):
        r = sd["rig"]
        hip = r["hip"]
        lean = D(sd.get("lean", 18))
        fp = r.get("feet") or [(hip[0] + th * 0.9, -fh)] * 2
        for side, p in zip(("near", "far"), fp):
            if mode == "pedal":                              # the ball of the foot on the pedal
                ankles[side] = (p[0] - fl * 0.25, p[1] - fh * 0.9)
                fang[side] = D(10) * math.sin(sd.get("crank", 0.0) + (0 if side == "near" else math.pi))
            else:
                ankles[side] = (p[0] - fl * 0.3, p[1] - fh)
                fang[side] = 0.0
        pref_knee = (1.0, -0.4)
        if r.get("bars") is not None:
            hand_t["near"] = hand_t["far"] = r["bars"]
            hands = {"near": "fist", "far": "fist"}
        else:
            k_ = _pt(hip, D(85), th)
            hand_t["near"] = (hip[0] + (k_[0] - hip[0]) * 0.7, hip[1] - P["leg_r"] * 1.2)
            hand_t["far"] = (hip[0] + (k_[0] - hip[0]) * 0.6, hip[1] - P["leg_r"])
    else:                                                    # standing
        ankles = {"near": (0.035 * leg, -fh), "far": (-0.035 * leg, -fh)}
        fang = {"near": 0.0, "far": 0.0}
        br = math.sin(2 * math.pi * t / 3.6)
        hip = (0.0, -leg * 0.985 + 0.002 * H * br)
    lean += sd.get("lean_add", 0.0)
    # ---- emotion body (side): fear leans back, anger leans in, sadness drops
    emo = sd.get("emotion", "neutral")
    lean += {"scared": -D(7), "angry": D(6), "sad": D(5), "crying": D(6), "laughing": D(3) * abs(math.sin(t * 22))}.get(emo, 0.0)
    if emo == "scared":
        hip = (hip[0] + 0.004 * H * math.sin(t * 56), hip[1])
    # ---- legs (IK, knees forward)
    for side in ("near", "far"):
        k, a2 = ik(hip, ankles[side], th, sh, pref_knee)
        J["knee_" + side], J["ankle_" + side] = k, a2
        J["fang_" + side] = fang[side]
    # ---- the spine
    LT = P["pelvis_up"] + P["torso"]
    u = (math.sin(lean), -math.cos(lean))
    n = (math.cos(lean), math.sin(lean))
    J.update(hip=hip, u=u, n=n, LT=LT, lean=lean)
    cd = P["chest"] * 1.15
    J["cd"] = cd

    def on_spine(s, k):
        return (hip[0] + u[0] * s * LT + n[0] * k, hip[1] + u[1] * s * LT + n[1] * k)

    J["on_spine"] = on_spine
    shoulder = on_spine(1.0 - P["shoulder_drop"] / LT * 0.7, 0.04 * cd)
    J["shoulder"] = shoulder
    neck0 = on_spine(0.97, 0.14 * cd)
    hang = lean * 0.35 + D(stoop * 45) + sd.get("nod", 0.0)
    if mode == "walk":
        hang -= lean * 0.5                                   # the head stays level while the body leans
    J["neck0"] = neck0
    J["neck1"] = (neck0[0] + math.sin(hang) * P["neck"] * 1.05, neck0[1] - math.cos(hang) * P["neck"] * 1.05)
    J["hang"] = hang
    # ---- arms: FK angles (relative to the body) or IK to a hand target
    g = sd.get("gesture")
    if g and g[0] in GESTURE_SIDE and mode in ("stand", "sit"):
        nr, fr, shp = GESTURE_SIDE[g[0]]
        w = max(0.0, min(1.0, g[1]))
        if g[0] == "explain":
            nr = (nr[0] + D(6) * math.sin(t * 5.0), nr[1] + D(10) * math.sin(t * 3.1))
        if g[0] == "wave":
            nr = (nr[0], nr[1] + D(18) * math.sin(t * 9.0))
        arm["near"] = (arm["near"][0] * (1 - w) + nr[0] * w, arm["near"][1] * (1 - w) + nr[1] * w)
        if fr:
            arm["far"] = (arm["far"][0] * (1 - w) + fr[0] * w, arm["far"][1] * (1 - w) + fr[1] * w)
        if w > 0.5:
            hands["near"] = shp
            if fr:
                hands["far"] = shp
        hand_t = {k: v for k, v in hand_t.items() if not (k == "near" or (fr and k == "far"))} if w > 0.3 else hand_t
    la = lean if mode != "walk" else lean * 0.4
    for side in ("near", "far"):
        sp_ = (shoulder[0] - (0.0 if side == "near" else 0.04 * cd), shoulder[1] + (0.0 if side == "near" else 0.01 * P["H"]))
        if side in hand_t:
            e, w_ = ik(sp_, hand_t[side], P["uarm"], P["farm"] + P["hand"] * 0.35, (-0.35, 1.0))
            J["elbow_" + side], J["wrist_" + side] = e, _toward(e, w_, P["farm"])
        else:
            ua, fa = arm[side]
            e = _pt(sp_, ua + la * 0.2, P["uarm"])
            J["elbow_" + side], J["wrist_" + side] = e, _pt(e, fa + la * 0.2, P["farm"])
        J["sh_" + side] = sp_
        J["hand_" + side] = hands[side]
    return J


def _toward(a, b, ln):
    d = math.hypot(b[0] - a[0], b[1] - a[1])
    if d < 1e-6:
        return b
    return (a[0] + (b[0] - a[0]) / d * ln, a[1] + (b[1] - a[1]) / d * ln)


# ------------------------------------------------------------------------------------------------- drawing

def top_colour(spec):
    typ = spec["costume"]["type"]
    k = {"shirt_trousers": "shirt", "tshirt_shorts": "tshirt", "kurta_dhoti": "kurta", "saree": "blouse", "frock": "frock"}[typ]
    return G.rgb(spec["colours"][k])


def draw(pp, ctx, st, x, y, scale):
    """draw the character in profile with its feet at ground y; facing st['side']['d']"""
    spec, P = pp.spec, pp.P
    sd = st["side"]
    d = 1.0 if sd.get("d", 1) >= 0 else -1.0
    J = solve(pp, st)
    col = {k: G.rgb(v) for k, v in spec["colours"].items()}
    skin = col["skin"]
    typ = spec["costume"]["type"]
    top = top_colour(spec)
    lw = P["lw"]
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(scale * d, scale)
    far_k = 0.80
    _arm(ctx, pp, J, "far", col, top, far_k, lw)
    _leg(ctx, pp, J, "far", col, far_k, lw)
    _hair_hanging(ctx, pp, J, st, col, lw)
    _leg(ctx, pp, J, "near", col, 1.0, lw)
    if typ in ("saree", "frock"):
        _skirt(ctx, pp, J, st, col, lw)
    _torso(ctx, pp, J, st, col, top, lw)
    _head(ctx, pp, J, st, col, lw)
    _over_cloth(ctx, pp, J, st, col, lw)
    _arm(ctx, pp, J, "near", col, top, 1.0, lw)
    ctx.restore()
    return J


def _sh(c, k):
    return G.shade(c, k) if k < 1 else c


def _leg(ctx, pp, J, side, col, k, lw):
    P, spec = pp.P, pp.spec
    typ = spec["costume"]["type"]
    hip, kn, an = J["hip"], J["knee_" + side], J["ankle_" + side]
    r = P["leg_r"]
    skin = _sh(col["skin"], k)
    parts = []
    if typ == "shirt_trousers":
        c = _sh(col["trousers"], k)
        parts += [(lambda: _limb(ctx, hip, kn, r * 1.25, r * 1.05), c, None),
                  (lambda: _limb(ctx, kn, an, r * 1.05, r * 0.85), c, None)]
    elif typ == "kurta_dhoti":
        c = _sh(col["dhoti"], k)
        mid = (kn[0] + (an[0] - kn[0]) * 0.78, kn[1] + (an[1] - kn[1]) * 0.78)
        parts += [(lambda: _limb(ctx, kn, an, r * 0.8, r * 0.62), skin, None),
                  (lambda: _limb(ctx, hip, kn, r * 1.55, r * 1.35), c, None),
                  (lambda: _limb(ctx, kn, mid, r * 1.35, r * 1.2), c, None)]
    elif typ == "tshirt_shorts":
        c = _sh(col["shorts"], k)
        mid = (hip[0] + (kn[0] - hip[0]) * 0.72, hip[1] + (kn[1] - hip[1]) * 0.72)
        parts += [(lambda: _limb(ctx, hip, kn, r * 1.0, r * 0.85), skin, None),
                  (lambda: _limb(ctx, kn, an, r * 0.85, r * 0.65), skin, None),
                  (lambda: _limb(ctx, hip, mid, r * 1.35, r * 1.25), c, None)]
    else:                                                    # saree / frock: legs (mostly under the skirt)
        parts += [(lambda: _limb(ctx, hip, kn, r * 1.0, r * 0.85), skin, None),
                  (lambda: _limb(ctx, kn, an, r * 0.85, r * 0.62), skin, None)]
    parts.append((lambda: _foot(ctx, pp, J, side), _sh(col.get("shoe", (0.3, 0.2, 0.15)) if spec["body"].get("shoe") == "shoe"
                                                         else col["skin"], k),
                  (lambda: _sandal(ctx, pp, J, side, col, k)) if spec["body"].get("shoe") == "sandal" else None))
    _group(ctx, parts, lw)


def _foot_pts(pp, J, side):
    P = pp.P
    an, a = J["ankle_" + side], J["fang_" + side]
    fl, fh = J["fl"], P["foot_h"]
    c, s = math.cos(-a), math.sin(-a)

    def R(px, py):
        return (an[0] + px * c - py * s, an[1] + px * s + py * c)

    return [R(-fl * 0.22, -fh * 0.3), R(-fl * 0.25, fh * 0.75), R(fl * 0.2, fh * 1.0), R(fl * 0.78, fh * 0.95),
            R(fl * 0.8, fh * 0.45), R(fl * 0.45, -fh * 0.05), R(fl * 0.1, -fh * 0.5)]


def _foot(ctx, pp, J, side):
    G.smooth(ctx, _foot_pts(pp, J, side), tension=0.45)


def _sandal(ctx, pp, J, side, col, k):
    pts = _foot_pts(pp, J, side)
    c = _sh(col.get("shoe", (0.35, 0.22, 0.14)), k)
    G.line(ctx, [pts[1], pts[2], pts[3]], pp.P["foot_h"] * 0.35, c)
    G.line(ctx, [pts[5], ((pts[2][0] + pts[3][0]) / 2, (pts[2][1] + pts[3][1]) / 2)], pp.P["lw"] * 1.6, c)


def _hand(ctx, P, wrist, ang, shape):
    hl = P["hand"] * 0.8
    ctx.save()
    ctx.translate(*wrist)
    ctx.rotate(-ang)
    if shape == "fist":
        G.ellipse(ctx, hl * 0.06, hl * 0.32, hl * 0.3, hl * 0.3)
    elif shape == "point":
        G.ellipse(ctx, hl * 0.02, hl * 0.28, hl * 0.26, hl * 0.3)
        G.ellipse(ctx, hl * 0.02, hl * 0.72, hl * 0.08, hl * 0.3)
    else:
        G.ellipse(ctx, 0.0, hl * 0.45, hl * 0.24, hl * 0.48)
        G.ellipse(ctx, hl * 0.2, hl * 0.3, hl * 0.09, hl * 0.22, ang=-0.5)
    ctx.restore()


def _arm(ctx, pp, J, side, col, top, k, lw):
    P, spec = pp.P, pp.spec
    s_, e, w = J["sh_" + side], J["elbow_" + side], J["wrist_" + side]
    r = P["arm_r"]
    skin = _sh(col["skin"], k)
    topc = _sh(top, k)
    sleeve = spec["costume"].get("sleeve", "short")
    fa = _ang(e, w)
    parts = [(lambda: _limb(ctx, s_, e, r * 1.1, r * 0.95), skin, None),
             (lambda: _limb(ctx, e, w, r * 0.95, r * 0.8), skin, None),
             (lambda: _hand(ctx, P, w, fa, J["hand_" + side]), skin, None)]
    if sleeve == "full":
        parts += [(lambda: _limb(ctx, s_, e, r * 1.3, r * 1.15), topc, None),
                  (lambda: _limb(ctx, e, _toward(e, w, P["farm"] * 0.9), r * 1.15, r * 1.0), topc, None)]
    elif sleeve == "half":
        parts.append((lambda: _limb(ctx, s_, e, r * 1.3, r * 1.2), topc, None))
    elif sleeve in ("short", "puff"):
        m = _toward(s_, e, P["uarm"] * 0.5)
        parts.append((lambda: _limb(ctx, s_, m, r * (1.6 if sleeve == "puff" else 1.3), r * (1.5 if sleeve == "puff" else 1.2)),
                      topc, None))
    if "bangles" in spec.get("accessories", []) and sleeve != "full":
        b0 = _toward(e, w, P["farm"] * 0.86)

        def bang():
            G.line(ctx, [(b0[0] - r, b0[1]), (b0[0] + r, b0[1])], P["lw"] * 2.2, G.rgb("#d32f2f"), smooth_it=False)
        parts[1] = (parts[1][0], parts[1][1], bang)
    _group(ctx, parts, lw)


def _torso_pts(pp, J, st):
    P, spec = pp.P, pp.spec
    f = J["on_spine"]
    cd = J["cd"]
    wd = P["waist"] * 1.1 + P["belly"] * P["head_h"] * 1.6
    hd = P["hip"] * 1.2
    bust = 0.12 * P["head_h"] if _female(spec) and spec.get("age", 30) >= 14 else 0.0
    hump = P.get("stoop", 0.0) * P["head_h"] * 1.2
    return [f(-0.02, -0.55 * hd), f(0.45, -0.48 * wd), f(0.8, -0.5 * cd - hump), f(0.98, -0.36 * cd),
            f(1.0, 0.18 * cd), f(0.84, 0.5 * cd + bust), f(0.55, 0.5 * wd + P["belly"] * P["head_h"] * 0.8),
            f(0.12, 0.55 * hd), f(-0.06, 0.42 * hd), f(-0.1, -0.3 * hd)]


def _torso(ctx, pp, J, st, col, top, lw):
    P, spec = pp.P, pp.spec
    typ = spec["costume"]["type"]
    pts = _torso_pts(pp, J, st)
    f = J["on_spine"]
    neck0, neck1 = J["neck0"], J["neck1"]
    skin = col["skin"]
    acc = spec.get("accessories", [])
    nr = P["head_w"] * 0.13

    def body_path():
        G.smooth(ctx, pts, tension=0.5)

    def details():
        ctx.save()
        ctx.new_path()
        body_path()
        ctx.clip()
        cd = J["cd"]
        if typ == "saree":                                   # the saree over the lower body
            ctx.new_path()
            G.smooth(ctx, [f(0.42, -cd * 2), f(0.5, cd * 2), f(-0.4, cd * 2), f(-0.4, -cd * 2)], tension=0.1)
            ctx.set_source_rgb(*col["saree"])
            ctx.fill()
        elif typ == "shirt_trousers":                         # trousers up to the belt
            ctx.new_path()
            G.smooth(ctx, [f(0.17, -cd * 2), f(0.17, cd * 2), f(-0.4, cd * 2), f(-0.4, -cd * 2)], tension=0.05)
            ctx.set_source_rgb(*col["trousers"])
            ctx.fill()
            G.line(ctx, [f(0.18, -cd), f(0.18, cd)], P["lw"] * 3.0, G.shade(col["trousers"], 0.55), smooth_it=False)
            for k_ in (0.35, 0.55, 0.75):
                p = f(k_, J["cd"] * 0.5)
                ctx.new_path()
                ctx.arc(p[0] - P["lw"] * 2.5, p[1], P["lw"] * 0.9, 0, 2 * math.pi)
                ctx.set_source_rgb(0.95, 0.95, 0.9)
                ctx.fill()
        elif typ == "tshirt_shorts" and "stripe" in col:
            G.line(ctx, [f(0.55, -cd), f(0.55, cd)], P["head_h"] * 0.07, col["stripe"], smooth_it=False)
        if "sacred_thread" in acc:
            G.line(ctx, [f(0.98, -0.2 * cd), f(0.55, 0.0), f(0.2, 0.5 * cd)], P["lw"] * 0.9, (0.96, 0.94, 0.86))
        if "torn" in acc:
            for k_ in (0.3, 0.62):
                p = f(k_, 0.1 * cd)
                G.line(ctx, [p, (p[0] + 6, p[1] + 14), (p[0] - 4, p[1] + 24)], P["lw"], LINE, smooth_it=False)
        # the side shadow (back edge)
        ctx.restore()
        ctx.save()
        ctx.new_path()
        body_path()
        ctx.clip()
        ctx.new_path()
        G.smooth(ctx, [(p[0] - P["head_h"] * 0.13, p[1]) for p in pts], tension=0.5)
        ctx.rectangle(-5000, -5000, 10000, 10000)
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.set_source_rgba(0, 0, 0, 0.10)
        ctx.fill()
        ctx.restore()

    parts = [(lambda: _limb(ctx, neck0, neck1, nr, nr * 0.95), skin, None), (body_path, top, details)]
    if typ == "kurta_dhoti":                                  # the kurta hangs to mid-thigh
        kn = J["knee_near"]
        hip = J["hip"]
        hd = P["hip"] * 1.2
        hem_y = hip[1] + P["thigh"] * 0.45
        front = max(hip[0] + hd * 0.6, hip[0] + (kn[0] - hip[0]) * 0.55 + P["leg_r"] * 1.6)
        kp = [f(0.3, -0.5 * hd), f(0.3, 0.56 * hd), (front, hem_y - P["leg_r"] * 0.4), (front - P["leg_r"] * 0.2, hem_y + P["leg_r"] * 0.5),
              (hip[0] - hd * 0.66, hem_y + P["leg_r"] * 0.5), (hip[0] - hd * 0.62, hip[1])]
        if J.get("sit_like") or kn[1] < hip[1] + P["thigh"] * 0.6:   # seated: the kurta lies over the thigh
            kp = [f(0.3, -0.5 * hd), f(0.3, 0.56 * hd), (hip[0] + (kn[0] - hip[0]) * 0.6, kn[1] - P["leg_r"] * 1.5),
                  (hip[0] + (kn[0] - hip[0]) * 0.62, kn[1] + P["leg_r"] * 0.9), (hip[0] - hd * 0.6, hip[1] + P["leg_r"] * 1.2)]

        def kurta():
            G.smooth(ctx, kp, tension=0.25)
        parts.insert(1, (kurta, top, None))
    if "rudraksha" in acc:
        def beads():
            for i in range(7):
                p = f(0.97 - 0.035 * i, J["cd"] * (0.15 + 0.06 * i))
                ctx.new_path()
                ctx.arc(p[0], p[1], P["lw"] * 1.4, 0, 2 * math.pi)
                ctx.set_source_rgb(0.42, 0.2, 0.1)
                ctx.fill()
        parts.append((lambda: None, top, beads))
    _group(ctx, [p for p in parts if p[0] is not None], lw)


def _skirt(ctx, pp, J, st, col, lw):
    """saree (to the ankles) or frock (to the knees), following the legs"""
    P, spec = pp.P, pp.spec
    typ = spec["costume"]["type"]
    hip, f = J["hip"], J["on_spine"]
    hd = P["hip"] * 1.25
    r = P["leg_r"]
    kn = [J["knee_near"], J["knee_far"]]
    an = [J["ankle_near"], J["ankle_far"]]
    seated = min(k[1] for k in kn) < hip[1] + P["thigh"] * 0.55
    c = col["saree" if typ == "saree" else "frock"]
    if seated:
        k = max(kn, key=lambda p: p[0])
        a = max(an, key=lambda p: p[0])
        hem = a[1] - P["foot_h"] * 1.2 if typ == "saree" else k[1] + P["shin"] * 0.25
        pts = [f(0.42, -0.5 * hd), f(0.42, 0.52 * hd), (k[0] - r * 0.5, k[1] - r * 1.6), (k[0] + r * 1.4, k[1] - r * 0.2),
               (k[0] + r * 1.5, hem), (a[0] - r * 1.8, hem), (k[0] - r * 1.6, k[1] + r * 1.8), (hip[0] - hd * 0.58, hip[1] + r * 1.1)]
        hem_pts = [pts[4], pts[5]]
    else:
        front_k = max(kn, key=lambda p: p[0])
        back_k = min(kn, key=lambda p: p[0])
        if typ == "saree":
            hy = max(a_[1] for a_ in an) - P["foot_h"] * 1.0
            fx = max(a_[0] for a_ in an) + r * 1.7
            bx = min(a_[0] for a_ in an) - r * 1.7
        else:
            hy = max(k_[1] for k_ in kn) + P["shin"] * 0.12
            fx = front_k[0] + r * 2.6
            bx = back_k[0] - r * 2.6
        sway = st.get("cloth", 0.0) * r * 1.2 - (r * 1.2 if st["side"].get("mode") == "walk" else 0.0)
        pts = [f(0.42, -0.5 * hd), f(0.42, 0.55 * hd), (front_k[0] + r * 1.5, front_k[1]), (fx, hy - r * 0.4),
               (fx - r * 0.3, hy), (bx + sway, hy), (bx + sway * 0.6, hy - r * 0.6), (back_k[0] - r * 1.5 + sway * 0.4, back_k[1]),
               (hip[0] - hd * 0.62, hip[1] + r * 0.5)]
        hem_pts = [pts[4], pts[5]]

    def path():
        G.smooth(ctx, pts, tension=0.35)

    def det():
        ctx.save()
        ctx.new_path()
        path()
        ctx.clip()
        if typ == "saree":                                    # pleats and the border at the hem
            for i in range(3):
                u = 0.35 + 0.18 * i
                p0 = f(0.38, (0.3 - 0.2 * i) * hd)
                p1 = (hem_pts[0][0] + (hem_pts[1][0] - hem_pts[0][0]) * u, hem_pts[0][1])
                G.line(ctx, [p0, p1], P["lw"] * 0.8, G.shade(c, 0.72), smooth_it=False)
            ctx.new_path()
            ctx.move_to(hem_pts[0][0] + r * 3, hem_pts[0][1] + r * 2)
            ctx.line_to(hem_pts[1][0] - r * 3, hem_pts[1][1] + r * 2)
            ctx.line_to(hem_pts[1][0] - r * 3, hem_pts[1][1] - r * 0.75)
            ctx.line_to(hem_pts[0][0] + r * 3, hem_pts[0][1] - r * 0.75)
            ctx.close_path()
            ctx.set_source_rgb(*col.get("border", G.shade(c, 0.6)))
            ctx.fill()
        elif "trim" in col:
            ctx.new_path()
            ctx.rectangle(hem_pts[1][0] - r * 3, hem_pts[0][1] - r * 0.6, hem_pts[0][0] - hem_pts[1][0] + r * 6, r)
            ctx.set_source_rgb(*col["trim"])
            ctx.fill()
        ctx.restore()

    _group(ctx, [(path, c, det)], lw)


def _over_cloth(ctx, pp, J, st, col, lw):
    """the saree's pallu over the shoulder and down the back; a shawl"""
    P, spec = pp.P, pp.spec
    f = J["on_spine"]
    cd = J["cd"]
    trail = (P["head_h"] * 0.25 if st["side"].get("mode") == "walk" else 0.0) + st.get("cloth", 0.0) * P["head_h"] * 0.15
    if spec["costume"]["type"] == "saree":
        pts = [f(0.42, 0.45 * cd), f(0.86, 0.42 * cd), f(1.02, 0.05 * cd), f(0.98, -0.5 * cd), f(0.6, -0.62 * cd - trail * 0.4),
               f(0.28, -0.72 * cd - trail), f(0.3, -0.42 * cd), f(0.78, -0.25 * cd), f(0.62, 0.3 * cd)]

        def det():
            G.line(ctx, [f(0.28, -0.72 * cd - trail), f(0.6, -0.62 * cd - trail * 0.4), f(0.98, -0.5 * cd)], P["head_h"] * 0.06,
                   col.get("border", G.shade(col["saree"], 0.6)))
        _group(ctx, [(lambda: G.smooth(ctx, pts, tension=0.4), col["saree"], det)], lw)
    if "shawl" in spec.get("accessories", []):
        pts = [f(0.55, 0.52 * cd), f(0.92, 0.48 * cd), f(1.04, 0.0), f(0.96, -0.58 * cd), f(0.5, -0.66 * cd - trail),
               f(0.45, -0.3 * cd), f(0.8, 0.1 * cd)]
        _group(ctx, [(lambda: G.smooth(ctx, pts, tension=0.4), col.get("shawl", G.rgb("#7a5230")), None)], lw)


# ------------------------------------------------------------------------------------------------- head

NOSES = {   # (x, y) points after the nose root, in (head depth, head height) units
    "button": [(0.52, -0.39), (0.535, -0.355), (0.47, -0.325)],
    "round": [(0.53, -0.41), (0.555, -0.36), (0.5, -0.315), (0.465, -0.32)],
    "long": [(0.6, -0.355), (0.565, -0.32), (0.47, -0.305)],
    "pointed": [(0.585, -0.365), (0.545, -0.335), (0.47, -0.315)],
    "broad": [(0.53, -0.41), (0.56, -0.355), (0.53, -0.315), (0.465, -0.31)],
}


def _head_frame(ctx, J, pp, back):
    """local head frame: origin under the skull at the neck, +x = the face's front, y up negative"""
    n1 = J["neck1"]
    ctx.translate(n1[0], n1[1])
    ctx.rotate(J["hang"])
    if back:
        ctx.scale(-1, 1)


def head_profile(pp, face):
    P, spec = pp.P, pp.spec
    Dp, hh = P["head_w"] * 1.12, P["head_h"]
    s = HEAD_SHAPES[spec["head"]["shape"]]
    jaw = s["jaw"]
    chin = s["chin"]
    vis = face.get("mouth", "X")
    wf, oh, rnd, *_ = VISEMES.get(vis, VISEMES["X"])
    op = (oh * 0.11 + face.get("jaw", 0.0) * 0.05) * hh
    fwd = 0.025 if rnd else 0.0
    ox = 0.06 * Dp                                           # the skull sits a little in front of the neck

    def p(xd, yh, drop=0.0, fx=0.0):
        return (ox + (xd + fx) * Dp, yh * hh + drop)

    nose = NOSES.get(spec["face"].get("nose", "button"), NOSES["button"])
    nk = spec["face"].get("nose_size", 1.0)
    root = (0.445, -0.5)
    nose_pts = [p(root[0] + (x_ - root[0]) * nk, root[1] + (y_ - root[1]) * nk) for x_, y_ in nose]
    upper = [p(-0.24, -0.04), p(-0.44, -0.36), p(-0.49, -0.6), p(-0.4, -0.86), p(-0.12, -1.0), p(0.2, -0.96), p(0.38, -0.82),
             p(0.455, -0.64), p(0.43, -0.56), p(*root)] + nose_pts + [p(0.45, -0.27), p(0.465 + fwd, -0.215)]
    lower = [p(0.455 + fwd, -0.14, op), p(0.41 + 0.04 * (1 - chin), -0.05, op), p(0.28 + 0.06 * chin, 0.005, op),
             p(0.06, -0.04 + 0.03 * (1 - jaw), op * 0.6), p(-0.14 - 0.06 * (jaw - 0.6), -0.16, op * 0.2)]
    mouth = {"upper": p(0.465 + fwd, -0.215), "corner": p(0.37 + fwd * 0.5, -0.19 - face.get("smile", 0.0) * 0.03, op * 0.45),
             "lower": p(0.455 + fwd, -0.14, op), "open": op, "round": rnd, "vis": vis}
    return upper + lower, mouth, (Dp, hh, ox)


def _head(ctx, pp, J, st, col, lw):
    P, spec = pp.P, pp.spec
    face = st.get("face", {})
    back = st["side"].get("head_back", 0.0) > 0.5
    skin = col["skin"]
    outline, mouth, (Dp, hh, ox) = head_profile(pp, face)
    f = spec["face"]
    acc = spec.get("accessories", [])
    ctx.save()
    _head_frame(ctx, J, pp, back)

    def ear():
        ek = spec["head"].get("ear", 1.0)
        G.ellipse(ctx, ox - 0.08 * Dp, -0.46 * hh, 0.085 * hh * ek, 0.13 * hh * ek, ang=-0.15)

    def ear_det():
        ek = spec["head"].get("ear", 1.0)
        G.line(ctx, [(ox - 0.06 * Dp, -0.53 * hh), (ox - 0.1 * Dp, -0.47 * hh), (ox - 0.07 * Dp, -0.4 * hh)], lw * 0.8,
               G.shade(skin, 0.6))
        if "earrings" in acc:
            ctx.new_path()
            ctx.arc(ox - 0.08 * Dp, -0.33 * hh + 0.13 * hh * (ek - 1), hh * 0.03, 0, 2 * math.pi)
            ctx.set_source_rgb(0.95, 0.75, 0.2)
            ctx.fill()

    _hair_back_cap(ctx, pp, st, col, lw, Dp, hh, ox)

    def skull():
        G.smooth(ctx, outline, tension=0.42)

    def face_det():
        _face_side(ctx, pp, face, col, Dp, hh, ox, mouth, outline)

    _group(ctx, [(skull, skin, face_det)], lw)
    _group(ctx, [(ear, skin, ear_det)], lw * 0.8)
    _hair_cap(ctx, pp, st, col, lw, Dp, hh, ox)
    _headwear_side(ctx, pp, st, col, lw, Dp, hh, ox)
    if "sindoor" in acc:
        G.line(ctx, [(ox + 0.12 * Dp, -1.0 * hh), (ox + 0.3 * Dp, -0.92 * hh)], hh * 0.025, G.rgb("#c62828"))
    ctx.restore()


def _face_side(ctx, pp, face, col, Dp, hh, ox, mouth, outline):
    P, spec = pp.P, pp.spec
    f = spec["face"]
    lw = P["lw"]
    skin = col["skin"]
    acc = spec.get("accessories", [])
    # ---- the mouth: an open wedge between the lips, the corner pulled back
    up, cor, lo = mouth["upper"], mouth["corner"], mouth["lower"]
    if mouth["open"] > hh * 0.012 and mouth["vis"] not in ("MBP",):
        ctx.new_path()
        ctx.move_to(up[0] + lw, up[1] + lw * 0.5)
        ctx.curve_to(up[0] - 0.03 * Dp, up[1] + lw, cor[0] + 0.02 * Dp, cor[1] - lw, cor[0], cor[1])
        ctx.curve_to(cor[0] + 0.03 * Dp, lo[1] - lw, lo[0] - 0.02 * Dp, lo[1], lo[0] + lw, lo[1] - lw * 0.5)
        ctx.close_path()
        ctx.set_source_rgb(0.35, 0.08, 0.10)
        ctx.fill_preserve()
        ctx.save()
        ctx.clip()
        if mouth["vis"] in ("A", "E", "FV", "LTD", "WIDE"):
            ctx.new_path()
            ctx.rectangle(cor[0], up[1] - hh, Dp, hh + mouth["open"] * 0.32 + lw)
            ctx.set_source_rgb(0.98, 0.97, 0.93)
            ctx.fill()
        ctx.restore()
        G.line(ctx, [up, cor, lo], lw * 1.0, LINE)
    else:
        G.line(ctx, [(up[0] - 0.005 * Dp, (up[1] + lo[1]) / 2), cor], lw * (1.4 if mouth["vis"] == "MBP" else 1.1), LINE)
        if face.get("smile", 0.0) > 0.35:
            G.line(ctx, [(cor[0] - 0.01 * Dp, cor[1] - 0.03 * hh), (cor[0] - 0.035 * Dp, cor[1] + 0.01 * hh)], lw * 0.8, LINE)
    # ---- cheek, blush, beard, moustache, wrinkles
    if f.get("blush") or face.get("cheek", 0) > 0.3:
        ctx.new_path()
        G.ellipse(ctx, ox + 0.2 * Dp, -0.33 * hh, 0.1 * Dp, 0.05 * hh)
        ctx.set_source_rgba(0.95, 0.45, 0.45, 0.25 + 0.2 * face.get("cheek", 0))
        ctx.fill()
    if f.get("beard"):
        bc = col.get("beard", col["hair"])
        ctx.new_path()
        G.smooth(ctx, [(ox - 0.12 * Dp, -0.36 * hh), (ox + 0.2 * Dp, -0.24 * hh), (ox + 0.38 * Dp, -0.27 * hh),
                       (lo[0] + 0.01 * Dp, lo[1] + 0.02 * hh), (ox + 0.42 * Dp, 0.1 * hh * f["beard"] + mouth["open"]),
                       (ox + 0.15 * Dp, 0.12 * hh * f["beard"] + mouth["open"]), (ox - 0.14 * Dp, -0.12 * hh)], tension=0.4)
        ctx.set_source_rgb(*bc)
        ctx.fill_preserve()
        ctx.set_source_rgb(*LINE)
        ctx.set_line_width(lw * 1.2)
        ctx.stroke()
    if f.get("beard") or "moustache" in col:
        mc = col.get("moustache", col.get("beard", col["hair"]))
        G.line(ctx, [(ox + 0.3 * Dp, -0.235 * hh), (ox + 0.42 * Dp, -0.26 * hh), (ox + 0.47 * Dp, -0.235 * hh)], hh * 0.035, mc)
    if f.get("wrinkles"):
        G.line(ctx, [(ox + 0.18 * Dp, -0.5 * hh), (ox + 0.14 * Dp, -0.47 * hh)], lw * 0.7, G.shade(skin, 0.6))
        G.line(ctx, [(ox + 0.42 * Dp, -0.31 * hh), (ox + 0.36 * Dp, -0.22 * hh)], lw * 0.7, G.shade(skin, 0.62))
    # ---- the eye
    ex, ey = ox + 0.31 * Dp, -hh * f.get("eye_y", 0.5)
    er = hh * f.get("eye_size", 0.075) * 1.05
    lid = max(0.0, min(1.0, face.get("lid", 1.0)))
    wide = face.get("wide", 0.0)
    squint = face.get("squint", 0.0)
    eh = er * (1.0 + 0.25 * wide)
    if face.get("happy_closed"):
        G.line(ctx, [(ex - er * 0.7, ey + eh * 0.15), (ex, ey - eh * 0.45), (ex + er * 0.55, ey + eh * 0.1)], lw * 1.3, LINE)
    elif lid < 0.14:
        G.line(ctx, [(ex - er * 0.75, ey), (ex - er * 0.05, ey + eh * 0.32), (ex + er * 0.6, ey + eh * 0.05)], lw * 1.3, LINE)
    else:
        top = ey - eh * (1.6 * lid - 0.75)
        bot = ey + eh * (0.72 - 0.3 * squint)
        wpts = [(ex - er * 0.75, ey), (ex - er * 0.15, min(top, ey) - eh * 0.1), (ex + er * 0.45, ey - eh * 0.25), (ex + er * 0.62, ey + eh * 0.05),
                (ex + er * 0.25, bot), (ex - er * 0.35, bot - eh * 0.1)]
        ctx.save()
        ctx.new_path()
        G.smooth(ctx, wpts, tension=0.45)
        ctx.set_source_rgb(0.99, 0.99, 0.97)
        ctx.fill_preserve()
        ctx.clip()
        lx, ly = face.get("look", (0.0, 0.0))
        ix = ex + er * (0.22 + 0.12 * max(-1.0, min(1.0, lx)))
        iy = ey + ly * eh * 0.3 + eh * 0.05
        ir = eh * 0.72 * (0.8 if wide > 0.5 else 1.0)
        ctx.new_path()
        G.ellipse(ctx, ix, iy, ir * 0.48, ir)
        ctx.set_source_rgb(*G.rgb(f.get("iris", "#4a2c1a")))
        ctx.fill()
        ctx.new_path()
        if f.get("ghost_eyes"):
            G.ellipse(ctx, ix + ir * 0.06, iy, ir * 0.22, ir * 0.46)
            ctx.set_source_rgb(*G.rgb(f.get("glow", "#fff6c0")))
        else:
            G.ellipse(ctx, ix + ir * 0.06, iy, ir * 0.26, ir * 0.5)
            ctx.set_source_rgb(0.06, 0.04, 0.03)
        ctx.fill()
        ctx.new_path()
        ctx.arc(ix + ir * 0.18, iy - ir * 0.35, ir * 0.16, 0, 2 * math.pi)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        if lid < 0.99:
            ctx.new_path()
            ctx.rectangle(ex - er * 2, ey - eh * 3, er * 4, top - (ey - eh * 3))
            ctx.set_source_rgb(*G.shade(skin, 0.92))
            ctx.fill()
        ctx.restore()
        G.line(ctx, [(ex - er * 0.8, ey + eh * 0.02), (ex - er * 0.15, min(top, ey) - eh * 0.12), (ex + er * 0.45, ey - eh * 0.27),
                     (ex + er * 0.68, ey + eh * 0.05)], lw * 1.35, LINE)
        if f.get("lashes"):
            for k_ in (0.0, 0.4):
                G.line(ctx, [(ex + er * (0.45 - k_ * 0.5), ey - eh * (0.27 + k_ * 0.1)),
                             (ex + er * (0.78 - k_ * 0.5), ey - eh * (0.62 + k_ * 0.25))], lw * 0.9, LINE)
    if face.get("tears", 0) > 0:
        tt = face.get("tear_t", 0.0)
        for k_ in range(2):
            u = (tt * 0.8 + k_ * 0.5) % 1.0
            ctx.new_path()
            G.ellipse(ctx, ex + er * 0.2, ey + eh + u * hh * 0.3, hh * 0.018, hh * 0.03)
            ctx.set_source_rgba(0.6, 0.8, 1.0, 0.85 * (1 - u))
            ctx.fill()
    # ---- the brow (its front end is the inner end)
    b = face.get("brow", "normal")
    raise_, din, dout, curve = BROWS[b] if isinstance(b, str) else b
    u_ = hh * 0.10
    by = -hh * f.get("brow_y", 0.66) - raise_ * u_
    inner = (ex + er * 0.75, by + din * u_)
    outer = (ex - er * 0.95, by + dout * u_ + er * 0.15)
    mid = (ex - er * 0.1, by - curve * er * 0.3 + (din + dout) * u_ * 0.3)
    G.line(ctx, [outer, mid, inner], hh * 0.028 * f.get("brow_thick", 1.0), G.rgb(f.get("brow_col", spec["colours"].get("hair", "#2a1a10"))))
    # ---- marks on the forehead
    if "tilak" in acc or "tilak" in col:
        G.line(ctx, [(ox + 0.4 * Dp, -0.84 * hh), (ox + 0.43 * Dp, -0.72 * hh)], hh * 0.03, col.get("tilak", G.rgb("#e02020")))
    if "bindi" in acc:
        ctx.new_path()
        ctx.arc(ox + 0.43 * Dp, -0.66 * hh, hh * 0.022, 0, 2 * math.pi)
        ctx.set_source_rgb(0.8, 0.1, 0.15)
        ctx.fill()


def _headwear_side(ctx, pp, st, col, lw, Dp, hh, ox):
    """turban, crown / mukut (with Krishna's feather) and Ganesha's trunk in the side view"""
    acc = pp.spec.get("accessories", [])
    cols = pp.spec["colours"]
    if "turban" in acc:
        tc = G.rgb(cols.get("turban", "#f2efe6"))
        pts = [(ox + 0.4 * Dp, -0.78 * hh), (ox + 0.42 * Dp, -1.05 * hh), (ox + 0.1 * Dp, -1.3 * hh), (ox - 0.42 * Dp, -1.22 * hh),
               (ox - 0.6 * Dp, -0.9 * hh), (ox - 0.52 * Dp, -0.66 * hh)]
        _group(ctx, [(lambda: G.smooth(ctx, pts, tension=0.4), tc,
                      lambda: [G.line(ctx, [(ox - 0.5 * Dp, (-0.75 - 0.13 * k) * hh), (ox + 0.38 * Dp, (-0.85 - 0.12 * k) * hh)], lw * 0.9,
                                      G.shade(tc, 0.7)) for k in range(3)])], lw)
        if "plume" in acc:
            sw = math.sin(st["side"].get("t", 0.0) * 2.0) * 0.04 * Dp
            G.line(ctx, [(ox + 0.25 * Dp, -1.15 * hh), (ox + 0.1 * Dp + sw, -1.45 * hh), (ox - 0.15 * Dp + sw * 2, -1.6 * hh)], lw * 3, (0.98, 0.98, 0.96))
    if "crown" in acc or "mukut" in acc:
        cc = G.rgb(cols.get("crown", "#e0b030"))
        tall = 0.55 if "mukut" in acc else 0.35
        pts = [(ox + 0.36 * Dp, -0.82 * hh), (ox + 0.38 * Dp, -(0.95 + tall * 0.7) * hh), (ox + 0.15 * Dp, -(0.95 + tall) * hh),
               (ox - 0.05 * Dp, -(0.95 + tall * 0.6) * hh), (ox - 0.25 * Dp, -(0.95 + tall * 0.85) * hh), (ox - 0.48 * Dp, -(0.95 + tall * 0.5) * hh),
               (ox - 0.5 * Dp, -0.8 * hh)]

        def det():
            ctx.new_path()
            G.ellipse(ctx, ox + 0.18 * Dp, -1.0 * hh, 0.06 * Dp, 0.05 * hh)
            ctx.set_source_rgb(0.78, 0.16, 0.16)
            ctx.fill()
            if "peacock_feather" in acc:
                ctx.new_path()
                G.ellipse(ctx, ox - 0.2 * Dp, -(1.3 + tall) * hh, 0.12 * Dp, 0.14 * hh, ang=-0.3)
                ctx.set_source_rgb(*G.rgb("#2a9a6a"))
                ctx.fill()
        ctx.new_path()
        _group(ctx, [(lambda: (ctx.move_to(*pts[0]), [ctx.line_to(*p) for p in pts[1:]], ctx.close_path()), cc, det)], lw)
    if "elephant_head" in acc:
        sw = math.sin(st["side"].get("t", 0.0) * 1.3) * 0.05 * Dp
        trunk = [(ox + 0.45 * Dp, -0.45 * hh), (ox + 0.62 * Dp, -0.2 * hh), (ox + 0.6 * Dp + sw, 0.15 * hh), (ox + 0.72 * Dp + sw, 0.32 * hh)]
        G.line(ctx, trunk, 0.22 * Dp + lw * 2, LINE)
        G.line(ctx, trunk, 0.22 * Dp, col["skin"])
        _group(ctx, [(lambda: G.ellipse(ctx, ox - 0.15 * Dp, -0.5 * hh, 0.32 * Dp, 0.42 * hh), G.shade(col["skin"], 0.9), None)], lw)


# ------------------------------------------------------------------------------------------------- hair

def _cap_pts(Dp, hh, ox, k=1.0, nape=-0.3, front=0.36, fy=-0.8):
    def p(x, y):
        return (ox + x * Dp * k, y * hh * (1 + (k - 1) * 0.6))
    return [p(front, fy), p(0.3, -0.96), p(0.04, -1.07), p(-0.33, -1.0), p(-0.53, -0.8), p(-0.56, -0.55), p(-0.47, nape),
            p(-0.3, nape + 0.03), p(-0.2, -0.38), p(-0.16, -0.6), p(0.05, -0.72), p(0.26, -0.76)]


def _hair_back_cap(ctx, pp, st, col, lw, Dp, hh, ox):
    """hair parts behind the skull (buns, the tuft of a tiki)"""
    spec = pp.spec
    style = spec["hair"]["style"]
    hc = col["hair"]
    sx = st.get("hair", (0.0, 0.0))[0]
    if style in ("bun_black", "bun_white"):
        _group(ctx, [(lambda: G.ellipse(ctx, ox - 0.6 * Dp, -0.66 * hh, 0.2 * Dp, 0.17 * hh), hc,
                      lambda: G.line(ctx, [(ox - 0.68 * Dp, -0.74 * hh), (ox - 0.52 * Dp, -0.6 * hh)], lw * 0.8, G.shade(hc, 0.6)))], lw)
    elif style == "tiki":
        tip = (ox - 0.55 * Dp + sx * Dp * 0.1, -0.85 * hh)
        _group(ctx, [(lambda: G.smooth(ctx, [(ox - 0.3 * Dp, -1.04 * hh), (ox - 0.22 * Dp, -0.98 * hh), tip, (ox - 0.36 * Dp, -0.96 * hh)],
                                       tension=0.4), hc, None)], lw)
    elif style == "jata":
        _group(ctx, [(lambda: G.ellipse(ctx, ox - 0.16 * Dp, -1.1 * hh, 0.4 * Dp, 0.2 * hh), hc,
                      lambda: [G.line(ctx, [(ox + (-0.4 + 0.2 * i) * Dp, -1.2 * hh), (ox + (-0.33 + 0.2 * i) * Dp, -1.0 * hh)], lw,
                                      G.shade(hc, 0.6)) for i in range(4)])], lw)


def _hair_cap(ctx, pp, st, col, lw, Dp, hh, ox):
    spec = pp.spec
    style = spec["hair"]["style"]
    hc = col["hair"]
    skin = col["skin"]
    parts = []
    if style == "bald_sides":
        pts = [(ox - 0.1 * Dp, -0.64 * hh), (ox - 0.4 * Dp, -0.7 * hh), (ox - 0.54 * Dp, -0.52 * hh), (ox - 0.46 * Dp, -0.3 * hh),
               (ox - 0.26 * Dp, -0.27 * hh), (ox - 0.16 * Dp, -0.4 * hh)]
        parts.append((lambda: G.smooth(ctx, pts, tension=0.4), hc, None))
    elif style == "tiki":
        pts = _cap_pts(Dp, hh, ox, 1.0)
        parts.append((lambda: G.smooth(ctx, pts, tension=0.45), G.shade(skin, 0.86), None))
    else:
        k = {"curly": 1.08, "spiky": 1.04, "open_long": 1.06, "jata": 1.08}.get(style, 1.03)
        nape = {"crop": -0.36, "side_part": -0.34, "spiky": -0.34}.get(style, -0.3)
        pts = _cap_pts(Dp, hh, ox, k, nape=nape, front=0.38 if style in ("open_long",) else 0.36,
                       fy=-0.76 if style in ("open_long", "side_part") else -0.8)

        def det():
            if style == "spiky":
                for i in range(4):
                    x0 = ox + (0.25 - 0.22 * i) * Dp
                    G.line(ctx, [(x0, -1.0 * hh), (x0 - 0.12 * Dp, -1.16 * hh), (x0 - 0.14 * Dp, -0.98 * hh)], lw * 0.9, G.shade(hc, 0.7),
                           smooth_it=False)
            elif style == "curly":
                for i in range(6):
                    a = math.pi * (0.1 + 0.15 * i)
                    ctx.new_path()
                    ctx.arc(ox - 0.08 * Dp + math.cos(a) * 0.42 * Dp, -0.62 * hh - math.sin(a) * 0.38 * hh, hh * 0.05, 0, 2 * math.pi)
                    ctx.set_source_rgb(*G.shade(hc, 0.7))
                    ctx.set_line_width(lw * 0.7)
                    ctx.stroke()
            else:
                G.line(ctx, [(ox + 0.3 * Dp, -0.9 * hh), (ox - 0.05 * Dp, -0.96 * hh), (ox - 0.4 * Dp, -0.8 * hh)], lw * 0.7,
                       G.shade(hc, 0.65) if sum(hc) < 2.4 else G.shade(hc, 0.8))
        parts.append((lambda: G.smooth(ctx, pts, tension=0.45), hc, det))
    _group(ctx, parts, lw)


def _hair_hanging(ctx, pp, J, st, col, lw):
    """long hair down the back (braid, pigtail, open hair, jata locks): hangs in the WORLD's vertical and trails in
    the walk; drawn behind the body"""
    P, spec = pp.P, pp.spec
    style = spec["hair"]["style"]
    if style not in ("braid_long", "pigtails", "open_long", "jata"):
        return
    hh, Dp = P["head_h"], P["head_w"] * 1.12
    hc = col["hair"]
    n1 = J["neck1"]
    ang = J["hang"]
    back = st["side"].get("head_back", 0.0) > 0.5
    bx = -1.0 if not back else 1.0
    c, s = math.cos(ang), math.sin(ang)

    def hp(x, y):                                             # head frame -> character units
        x = x * bx
        return (n1[0] + x * c - y * s, n1[1] + x * s + y * c)

    sx, sy = st.get("hair", (0.0, 0.0))
    trail = (0.35 if st["side"].get("mode") == "walk" else 0.0) * hh + sx * hh * 0.25
    walk_run = st["side"].get("mode") == "walk" and st["side"].get("walk", {}).get("run")
    if walk_run:
        trail *= 1.8
    if style == "braid_long" or style == "pigtails":
        top = hp(0.5 * Dp, -0.5 * hh)
        L = hh * (1.7 if style == "braid_long" else 0.75)
        n = 7 if style == "braid_long" else 4
        segs = []
        for i in range(n):
            u = (i + 0.5) / n
            segs.append((top[0] - trail * u * u - 0.05 * hh * u, top[1] + L * u))
        parts = []
        for i, p in enumerate(segs):
            rr = hh * (0.1 - 0.035 * i / n)
            parts.append(((lambda p=p, rr=rr: G.ellipse(ctx, p[0], p[1], rr * 0.85, rr * 1.15)), hc, None))
        end = segs[-1]
        if "ribbon" in col:
            parts.append(((lambda: G.ellipse(ctx, end[0], end[1] + hh * 0.12, hh * 0.07, hh * 0.05)), col["ribbon"], None))
        _group(ctx, parts, lw)
    elif style == "open_long":
        L = hh * 2.2
        tr = trail
        pts = [hp(0.35 * Dp, -1.02 * hh), hp(0.58 * Dp, -0.6 * hh)]
        base = pts[-1]
        for i in range(1, 6):
            u = i / 5
            pts.append((base[0] - tr * u * u - hh * 0.12 * u + math.sin(u * 7 + st["side"].get("t", 0) * 2) * hh * 0.03,
                        base[1] + L * u))
        far = hp(-0.05 * Dp, -0.2 * hh)
        pts += [(far[0] - tr * 0.6 + hh * 0.18, far[1] + L * 0.9), (far[0] + hh * 0.08, far[1] + L * 0.35), hp(0.0, -0.5 * hh)]
        _group(ctx, [(lambda: G.smooth(ctx, pts, tension=0.4), hc, None)], lw)
    elif style == "jata":
        parts = []
        for k_ in range(3):
            top = hp((0.42 + 0.05 * k_) * Dp, (-0.9 + 0.2 * k_) * hh)
            bot = (top[0] - trail * 0.5 - hh * 0.05 * k_, top[1] + hh * (1.1 - 0.15 * k_))
            parts.append(((lambda a=top, b=bot: _limb(ctx, a, b, hh * 0.09, hh * 0.06)), hc, None))
        _group(ctx, parts, lw)
