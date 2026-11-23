"""the layered vector puppet: builds every part of a character from its identity spec and draws a pose.

Drawing = groups in z order. Inside a group the outlines of all parts are stroked first and the fills drawn after,
so the parts of one limb (upper arm, forearm, hand / thigh, shin, foot) join WITHOUT seams or gaps, while separate
groups (an arm in front of the body) keep their outline. Facial features are separate layers on the head."""
import math

import cairo

from tvtoon import geom as G
from tvtoon import rig as R

LINE = (0.16, 0.10, 0.08)


# ----------------------------------------------------------------------------------------------- proportions

def proportions(spec):
    H = 1000.0 * spec["height"]
    hh = H / spec["heads"]
    b = spec["body"]
    neck = H * b.get("neck", 0.035)
    leg = H * b.get("leg", 0.46)
    pelvis_up = H * 0.06
    torso = H - leg - pelvis_up - neck - hh
    foot_h = H * 0.028
    thigh = (leg - foot_h) * 0.52
    shin = (leg - foot_h) - thigh
    arm = b.get("arm", 0.42) * H
    return {"H": H, "head_h": hh, "head_w": hh * spec["head"]["w"], "neck": neck, "leg": leg, "pelvis_up": pelvis_up,
            "torso": torso, "foot_h": foot_h, "thigh": thigh, "shin": shin,
            "uarm": arm * 0.43, "farm": arm * 0.37, "hand": arm * 0.24,
            "shoulder": hh * b["shoulder"], "shoulder_drop": torso * 0.13, "hip": hh * b["hip"],
            "waist": hh * b["waist"], "chest": hh * b.get("chest", b["shoulder"] * 0.95),
            "arm_r": hh * b.get("arm_r", 0.1), "leg_r": hh * b.get("leg_r", 0.13), "belly": b.get("belly", 0.0),
            "stoop": b.get("stoop", 0.0), "lw": H * 0.0055 * spec.get("line_scale", 1.0)}


class Part:
    def __init__(self, bone, sil, paint=None, outline=True):
        self.bone, self.sil, self.paint, self.outline = bone, sil, paint, outline


class Ctx:
    """everything a part needs while it is drawn"""

    def __init__(self, spec, P, sk, W, st, ctx):
        self.spec, self.P, self.sk, self.W, self.st, self.ctx = spec, P, sk, W, st, ctx
        self.col = {k: G.rgb(v) for k, v in spec["colours"].items()}
        self.body_turn = st.get("turn", 0.0)
        self.turn = st.get("head_turn", self.body_turn)

    def local(self, bone, wx, wy):
        m = cairo.Matrix(*self.W[bone])
        m.invert()
        return m.transform_point(wx, wy)


def fill(ctx, col, keep=True):
    ctx.set_source_rgb(*col)
    ctx.fill_preserve() if keep else ctx.fill()


def stroke(ctx, col, w):
    ctx.set_source_rgb(*col)
    ctx.set_line_width(w)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()


def shadow_side(ctx, sil, col, dx, dy):
    """the one controlled shadow tone: the silhouette's own shape, offset, clipped inside it"""
    ctx.save()
    sil(ctx)
    ctx.clip()
    ctx.translate(dx, dy)
    ctx.new_path()
    sil(ctx)
    ctx.translate(-dx, -dy)
    ctx.rectangle(-5000, -5000, 10000, 10000)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.set_source_rgb(*col)
    ctx.fill()
    ctx.restore()


# ----------------------------------------------------------------------------------------------- head & face

HEAD_SHAPES = {   # x as a fraction of half head width, at y fractions of head height up from the chin
    "round": dict(top=1.0, crown=0.80, temple=0.99, cheek=1.0, jaw=0.88, chin=0.50),
    "oval": dict(top=1.0, crown=0.74, temple=0.95, cheek=0.96, jaw=0.74, chin=0.36),
    "egg": dict(top=1.0, crown=0.80, temple=1.0, cheek=0.93, jaw=0.64, chin=0.30),
    "square": dict(top=1.0, crown=0.82, temple=0.97, cheek=0.99, jaw=0.94, chin=0.62),
    "heart": dict(top=1.0, crown=0.80, temple=1.0, cheek=0.92, jaw=0.58, chin=0.16),
    "long": dict(top=1.0, crown=0.70, temple=0.90, cheek=0.92, jaw=0.78, chin=0.40),
    "pear": dict(top=1.0, crown=0.66, temple=0.86, cheek=1.0, jaw=1.0, chin=0.62),
}


def head_points(P, spec, turn):
    hw, hh = P["head_w"] / 2, P["head_h"]
    s = HEAD_SHAPES[spec["head"]["shape"]]
    k = 1.0 - 0.06 * abs(turn)                          # a turned head is a little narrower
    sh = turn * hw * 0.06
    R_ = [(s["crown"], -0.94), (s["temple"], -0.70), (s["cheek"], -0.44), (s["jaw"], -0.18), (s["chin"], -0.04)]
    right = [(sh + x * hw * k, y * hh) for x, y in R_]
    left = [(sh - x * hw * k, y * hh) for x, y in reversed(R_)]
    return [(sh, -s["top"] * hh)] + right + [(sh, 0.0)] + left


def feature_layout(P, spec, turn):
    hw, hh = P["head_w"] / 2, P["head_h"]
    f = spec["face"]
    fx = turn * hw * 0.27
    ey = -hh * f.get("eye_y", 0.50)
    sp = hw * f.get("eye_spacing", 0.42)
    near = 1.0 - 0.28 * max(0.0, -turn)                 # the eye on the far side gets narrower
    far = 1.0 - 0.28 * max(0.0, turn)
    return {"fx": fx, "eyes": [(fx - sp * (1 - 0.1 * turn), ey, -1, near if turn < 0 else far if turn > 0 else 1.0),
                               (fx + sp * (1 + 0.1 * turn), ey, 1, near if turn > 0 else far if turn < 0 else 1.0)],
            "nose": (turn * hw * 0.38, -hh * f.get("nose_y", 0.33)), "mouth": (turn * hw * 0.30, -hh * f.get("mouth_y", 0.17)),
            "brow_y": -hh * f.get("brow_y", 0.66)}


def draw_eye(ctx, c, P, spec, face, cx, cy, side, squash):
    hh = P["head_h"]
    f = spec["face"]
    er = hh * f.get("eye_size", 0.075)
    style = f.get("eye_style", "almond")
    ew = er * (1.32 if style == "almond" else 1.0 if style == "round" else 1.5 if style == "narrow" else 1.15) * squash
    eh = er * (0.9 if style == "almond" else 1.12 if style == "round" else 0.62 if style == "narrow" else 1.25)
    lid = max(0.0, min(1.0, face.get("lid", 1.0)))
    wide = face.get("wide", 0.0)
    eh *= 1.0 + 0.25 * wide
    squint = face.get("squint", 0.0)
    lw = P["lw"]
    if face.get("happy_closed"):                       # laughing / delighted: ^ arcs
        G.line(ctx, [(cx - ew, cy + eh * 0.2), (cx, cy - eh * 0.55), (cx + ew, cy + eh * 0.2)], lw * 1.3, LINE)
        return
    if lid < 0.14:                                     # closed (blink): a soft downward lid curve
        G.line(ctx, [(cx - ew, cy), (cx, cy + eh * 0.35), (cx + ew, cy)], lw * 1.3, LINE)
        if f.get("lashes"):
            G.line(ctx, [(cx + side * ew * 0.9, cy + eh * 0.05), (cx + side * ew * 1.25, cy + eh * 0.25)], lw, LINE)
        return
    top = cy - eh * (2 * lid - 1)                       # upper lid height
    bot = cy + eh * (1.0 - 0.55 * squint)
    ctx.save()
    ctx.new_path()
    G.smooth(ctx, [(cx - ew, cy), (cx - ew * 0.55, min(top, cy) - eh * 0.25 * lid), (cx + ew * 0.55, min(top, cy) - eh * 0.25 * lid),
                   (cx + ew, cy), (cx + ew * 0.5, bot), (cx - ew * 0.5, bot)])
    fill(ctx, (0.99, 0.99, 0.97))
    ctx.clip()
    lx, ly = face.get("look", (0.0, 0.0))
    ix, iy = cx + lx * ew * 0.42, cy + ly * eh * 0.35 + eh * 0.05
    ir = eh * 0.86 * (1.05 if style == "round" else 1.0) * (1.0 + 0.08 * f.get("child", 0))
    if wide > 0.5:
        ir *= 0.8
    ctx.new_path()
    G.ellipse(ctx, ix, iy, ir * 0.92 * squash, ir)
    fill(ctx, G.rgb(f.get("iris", "#4a2c1a")), keep=False)
    ctx.new_path()
    if f.get("ghost_eyes"):                             # a ghost: a glowing pupil instead of a dark one
        G.ellipse(ctx, ix, iy, ir * 0.40 * squash, ir * 0.44)
        fill(ctx, G.rgb(f.get("glow", "#fff6c0")), keep=False)
    else:
        G.ellipse(ctx, ix, iy, ir * 0.48 * squash, ir * 0.52)
        fill(ctx, (0.06, 0.04, 0.03), keep=False)
    ctx.new_path()
    G.ellipse(ctx, ix + ir * 0.32, iy - ir * 0.35, ir * 0.24, ir * 0.24)
    fill(ctx, (1, 1, 1), keep=False)
    if lid < 0.99:                                     # the eyelid (skin) over the top of the eye
        ctx.new_path()
        ctx.rectangle(cx - ew * 1.5, cy - eh * 3, ew * 3, top - (cy - eh * 3))
        fill(ctx, G.shade(spec["colours"]["skin"], 0.92), keep=False)
    ctx.restore()
    ctx.new_path()                                      # the outline: a strong upper lid, a light lower lid
    G.smooth(ctx, [(cx - ew * 1.04, cy + eh * 0.05), (cx - ew * 0.55, min(top, cy) - eh * 0.25 * lid),
                   (cx + ew * 0.55, min(top, cy) - eh * 0.25 * lid), (cx + ew * 1.06, cy)], closed=False)
    stroke(ctx, LINE, lw * 1.35)
    G.line(ctx, [(cx - ew * 0.75, bot - eh * 0.12), (cx, bot + eh * 0.02), (cx + ew * 0.75, bot - eh * 0.12)], lw * 0.6,
           G.shade(spec["colours"]["skin"], 0.62))
    if f.get("lashes"):
        for k_ in (0.0, 0.35):
            G.line(ctx, [(cx + side * ew * (0.95 - k_ * 0.4), cy - eh * (0.2 + k_)),
                         (cx + side * ew * (1.3 - k_ * 0.4), cy - eh * (0.55 + k_ * 1.2))], lw * 0.9, LINE)


BROWS = {  # raise (up +), inner end dy (down +), outer end dy, curve
    "normal": (0.0, 0.0, 0.0, 1.0), "happy": (0.12, -0.05, 0.05, 1.3), "angry": (-0.05, 0.38, -0.12, 0.4),
    "sad": (0.08, -0.32, 0.18, 0.6), "surprised": (0.45, -0.05, 0.05, 1.5), "scared": (0.3, -0.35, 0.12, 0.8),
}


def draw_brow(ctx, P, spec, face, cx, by, side, squash):
    hh = P["head_h"]
    f = spec["face"]
    er = hh * f.get("eye_size", 0.075)
    b = face.get("brow", "normal")
    raise_, din, dout, curve = BROWS[b] if isinstance(b, str) else b
    u = hh * 0.10
    y0 = by - raise_ * u - face.get("brow_asym", 0.0) * side * u * 0.6      # one brow higher (asymmetric acting)
    w = er * 1.45 * squash
    inner = (cx - side * w * 0.8, y0 + din * u)
    mid = (cx + side * w * 0.05, y0 - curve * er * 0.32 + (din + dout) * u * 0.3)
    outer = (cx + side * w * 0.95, y0 + dout * u + er * 0.15)
    th = hh * 0.028 * f.get("brow_thick", 1.0)
    G.line(ctx, [inner, mid, outer], th, G.rgb(f.get("brow_col", spec["colours"].get("hair", "#2a1a10"))))


def draw_nose(ctx, P, spec, nx, ny, turn):
    hh, lw = P["head_h"], P["lw"]
    st = spec["face"].get("nose", "button")
    sz = hh * spec["face"].get("nose_size", 1.0)
    skin = G.rgb(spec["colours"]["skin"])
    d = 1 if turn >= 0 else -1
    if st == "button":
        G.line(ctx, [(nx - 0.045 * sz, ny - 0.02 * sz), (nx, ny + 0.015 * sz), (nx + 0.045 * sz, ny - 0.02 * sz)], lw * 1.1, LINE)
    elif st == "round":
        ctx.new_path()
        G.ellipse(ctx, nx, ny - 0.02 * sz, 0.07 * sz, 0.058 * sz)
        fill(ctx, G.shade(skin, 0.9))
        stroke(ctx, LINE, lw)
    elif st == "long":
        G.line(ctx, [(nx - d * 0.01 * sz, ny - 0.16 * sz), (nx + d * 0.03 * sz, ny - 0.03 * sz), (nx + d * 0.01 * sz, ny + 0.01 * sz),
                     (nx - d * 0.04 * sz, ny)], lw * 1.1, LINE)
    elif st == "pointed":
        G.line(ctx, [(nx + d * 0.005 * sz, ny - 0.11 * sz), (nx + d * 0.035 * sz, ny), (nx - d * 0.025 * sz, ny + 0.005 * sz)],
               lw * 1.1, LINE, smooth_it=False)
    elif st == "broad":
        G.line(ctx, [(nx - 0.06 * sz, ny - 0.03 * sz), (nx - 0.035 * sz, ny + 0.012 * sz), (nx, ny + 0.02 * sz),
                     (nx + 0.035 * sz, ny + 0.012 * sz), (nx + 0.06 * sz, ny - 0.03 * sz)], lw * 1.1, LINE)
        G.line(ctx, [(nx - 0.02 * sz, ny - 0.12 * sz), (nx - 0.03 * sz, ny - 0.06 * sz)], lw * 0.7, G.shade(LINE, 1.8))


# mouth visemes: (width factor, open height, round, teeth top, teeth bottom, tongue)
VISEMES = {
    "X": (1.0, 0.0, False, False, False, False),     # closed / rest
    "A": (0.92, 0.58, False, True, False, True),     # a / aa
    "E": (1.05, 0.30, False, True, True, False),     # e / ee / i
    "U": (0.46, 0.36, True, False, False, False),    # u / oo
    "O": (0.62, 0.56, True, False, False, True),     # o
    "MBP": (0.95, 0.0, False, False, False, False),  # m b p: pressed lips
    "FV": (0.85, 0.16, False, True, False, False),   # f v: upper teeth on the lower lip
    "LTD": (0.85, 0.32, False, True, False, True),   # l t d n s r: open, tongue up
    "WIDE": (1.18, 0.82, False, True, False, True),  # laughing / shouting
}


def draw_mouth(ctx, P, spec, face, mx, my, turn):
    hh, lw = P["head_h"], P["lw"]
    vis = face.get("mouth", "X")
    wf, oh, rnd, tt, tb, tongue = VISEMES.get(vis, VISEMES["X"])
    smile = face.get("smile", 0.0)
    mw = hh * 0.26 * spec["face"].get("mouth_w", 1.0) * wf * (1 - 0.15 * abs(turn))
    oh = oh * mw * 0.75 + face.get("jaw", 0.0) * mw * 0.3
    cl = (mx - mw / 2, my - smile * mw * 0.22)
    cr = (mx + mw / 2, my - smile * mw * 0.22)
    lip = G.rgb(spec["colours"].get("lip", "#a8544a"))
    if oh < 1.0:                                       # closed: one line, the smile in its curve
        dip = mw * 0.10 * smile
        pts = [cl, (mx - mw * 0.25, my + dip * 0.6), (mx, my + dip), (mx + mw * 0.25, my + dip * 0.6), cr]
        G.line(ctx, pts, lw * (1.5 if vis == "MBP" else 1.2), LINE)
        if vis == "MBP":
            G.line(ctx, [(mx - mw * 0.25, my + lw * 2.2), (mx, my + lw * 2.8), (mx + mw * 0.25, my + lw * 2.2)], lw * 0.7, G.shade(lip, 0.9))
        if smile > 0.35:                               # dimples at the corners
            for c_, s_ in ((cl, -1), (cr, 1)):
                G.line(ctx, [(c_[0] + s_ * mw * 0.02, c_[1] - mw * 0.05), (c_[0] + s_ * mw * 0.06, c_[1] + mw * 0.02)], lw * 0.8, LINE)
        return
    ctx.save()
    ctx.new_path()
    if rnd:
        G.ellipse(ctx, mx, my + oh * 0.25, mw / 2, oh / 2 + mw * 0.05)
    else:
        top = my - oh * 0.18 - smile * mw * 0.05
        bot = my + oh * 0.82 - smile * mw * 0.12
        G.smooth(ctx, [cl, (mx - mw * 0.3, top), (mx + mw * 0.3, top), cr, (mx + mw * 0.28, bot), (mx - mw * 0.28, bot)])
    fill(ctx, (0.35, 0.08, 0.10))
    ctx.clip()
    if tt:
        ctx.new_path()
        ctx.rectangle(mx - mw, my - oh, mw * 2, oh * (0.42 if vis != "FV" else 0.9))
        fill(ctx, (0.98, 0.97, 0.93), keep=False)
    if tb:
        ctx.new_path()
        ctx.rectangle(mx - mw, my + oh * 0.62, mw * 2, oh)
        fill(ctx, (0.98, 0.97, 0.93), keep=False)
    if tongue:
        ctx.new_path()
        G.ellipse(ctx, mx, my + oh * (0.85 if vis != "LTD" else 0.55), mw * 0.32, oh * 0.38)
        fill(ctx, (0.85, 0.38, 0.42), keep=False)
    ctx.restore()
    ctx.new_path()
    if rnd:
        G.ellipse(ctx, mx, my + oh * 0.25, mw / 2, oh / 2 + mw * 0.05)
    else:
        G.smooth(ctx, [cl, (mx - mw * 0.3, top), (mx + mw * 0.3, top), cr, (mx + mw * 0.28, bot), (mx - mw * 0.28, bot)])
    stroke(ctx, LINE, lw * 1.2)


def head_part(spec, P):
    def sil(ctx, C):
        ctx.new_path()
        G.smooth(ctx, head_points(P, spec, C.turn))
        hw, hh = P["head_w"] / 2, P["head_h"]
        e = spec["head"].get("ear", 1.0)
        for s in (-1, 1):                                # the ears
            vis = 1.0 - 0.6 * max(0.0, s * C.turn)          # the far ear hides behind the head as it turns
            if vis < 0.45:
                continue
            ex = C.turn * hw * 0.06 + s * hw * (0.94 - 0.3 * max(0.0, -s * C.turn)) * (1 - 0.06 * abs(C.turn))
            G.ellipse(ctx, ex, -hh * 0.45, hw * 0.16 * e * vis, hh * 0.12 * e)

    def paint(ctx, C):
        hw, hh = P["head_w"] / 2, P["head_h"]
        skin = C.col["skin"]
        ctx.new_path()
        G.smooth(ctx, head_points(P, spec, C.turn))
        shadow_side(ctx, lambda c: G.smooth(c, head_points(P, spec, C.turn)), G.shade(skin, 0.88),
                    -hw * 0.12 - C.turn * hw * 0.1, hh * 0.04)
        e = spec["head"].get("ear", 1.0)
        for s in (-1, 1):
            vis = 1.0 - 0.6 * max(0.0, s * C.turn)
            if vis < 0.45:
                continue
            ex = C.turn * hw * 0.06 + s * hw * (0.94 - 0.3 * max(0.0, -s * C.turn)) * (1 - 0.06 * abs(C.turn))
            G.line(ctx, [(ex - s * hw * 0.02, -hh * 0.52), (ex + s * hw * 0.05, -hh * 0.46), (ex - s * hw * 0.01, -hh * 0.39)],
                   P["lw"] * 0.7, G.shade(skin, 0.6))
            if "earrings" in spec.get("accessories", []):
                ctx.new_path()
                G.ellipse(ctx, ex, -hh * 0.31, hw * 0.05, hw * 0.05)
                fill(ctx, G.rgb("#e6b422"))
                stroke(ctx, LINE, P["lw"] * 0.6)
        draw_face(ctx, C)
    return Part("head", sil, paint)


def draw_face(ctx, C):
    spec, P, st = C.spec, C.P, C.st
    face = st.get("face", {})
    L = feature_layout(P, spec, C.turn)
    hh, hw = P["head_h"], P["head_w"] / 2
    f = spec["face"]
    if f.get("blush") or face.get("blush"):
        for ex, ey, s, sq in L["eyes"]:
            ctx.new_path()
            G.ellipse(ctx, ex + s * hw * 0.12, ey + hh * 0.16, hw * 0.16 * sq, hh * 0.05)
            ctx.set_source_rgba(0.95, 0.45, 0.45, 0.30 + 0.25 * face.get("blush", 0))
            ctx.fill()
    if f.get("wrinkles"):
        lw = P["lw"] * 0.6
        wc = G.shade(spec["colours"]["skin"], 0.62)
        for k in (0, 1):
            y = -hh * (0.80 + 0.055 * k)
            G.line(ctx, [(L["fx"] - hw * 0.28, y + hh * 0.01), (L["fx"], y - hh * 0.008), (L["fx"] + hw * 0.28, y + hh * 0.01)], lw, wc)
        nx, ny = L["nose"]
        mx, my = L["mouth"]
        for s in (-1, 1):
            G.line(ctx, [(nx + s * hw * 0.2, ny - hh * 0.02), (mx + s * hw * 0.3, my - hh * 0.01), (mx + s * hw * 0.33, my + hh * 0.05)], lw, wc)
        for ex, ey, s, sq in L["eyes"]:
            G.line(ctx, [(ex + s * hw * 0.25 * sq, ey - hh * 0.01), (ex + s * hw * 0.33 * sq, ey + hh * 0.02)], lw, wc)
    for ex, ey, s, sq in L["eyes"]:
        draw_eye(ctx, None, P, spec, face, ex, ey, s, sq)
        draw_brow(ctx, P, spec, face, ex, L["brow_y"], s, sq)
    nx, ny = L["nose"]
    draw_nose(ctx, P, spec, nx, ny, C.turn)
    mx, my = L["mouth"]
    draw_mouth(ctx, P, spec, face, mx, my, C.turn)
    mo = spec["face"].get("moustache")
    if mo:
        col = G.rgb(spec["colours"].get("moustache", spec["colours"]["hair"]))
        w = hw * (0.42 if mo == "thick" else 0.5)
        yy = my - hh * 0.072 + face.get("jaw", 0) * hh * 0.01
        ctx.new_path()
        G.smooth(ctx, [(mx, yy - hh * 0.035), (mx + w * 0.5, yy - hh * 0.04), (mx + w, yy + hh * 0.02), (mx + w * 0.55, yy + hh * 0.025),
                       (mx, yy + hh * 0.005), (mx - w * 0.55, yy + hh * 0.025), (mx - w, yy + hh * 0.02), (mx - w * 0.5, yy - hh * 0.04)])
        fill(ctx, col)
        stroke(ctx, LINE, P["lw"] * 0.9)
    if face.get("cheek", 0) > 0.05:                         # cheeks lift with a smile / laugh
        for ex, ey, s, sq in L["eyes"]:
            G.line(ctx, [(ex - s * hw * 0.05, ey + hh * 0.105), (ex + s * hw * 0.12 * sq, ey + hh * 0.085 - hh * 0.02 * face["cheek"]),
                         (ex + s * hw * 0.24 * sq, ey + hh * 0.10)], P["lw"] * 0.7, G.shade(spec["colours"]["skin"], 0.7))
    if face.get("tears", 0) > 0:                            # crying: tears run down from the eyes
        a = face["tears"]
        for k, (ex, ey, s, sq) in enumerate(L["eyes"]):
            u = (face.get("tear_t", 0.0) * 0.9 + k * 0.4) % 1.0
            ty = ey + hh * 0.06 + u * hh * 0.28
            ctx.new_path()
            ctx.move_to(ex + s * hw * 0.1, ey + hh * 0.05)
            ctx.curve_to(ex + s * hw * 0.13, ey + hh * 0.12, ex + s * hw * 0.12, ty - hh * 0.03, ex + s * hw * 0.11, ty)
            ctx.set_source_rgba(0.55, 0.8, 1.0, 0.85 * a)
            ctx.set_line_width(P["lw"] * 1.4)
            ctx.stroke()
            ctx.new_path()
            G.ellipse(ctx, ex + s * hw * 0.11, ty + hh * 0.012, hw * 0.035, hh * 0.022)
            ctx.set_source_rgba(0.55, 0.8, 1.0, 0.9 * a)
            ctx.fill()
    if "vanara" in spec.get("accessories", []):           # Hanuman's vanara face: a pale muzzle round nose and mouth
        mx_, my_ = L["mouth"]
        ctx.new_path()
        G.ellipse(ctx, (L["nose"][0] + mx_) / 2, (L["nose"][1] + my_) / 2 + hh * 0.03, hw * 0.55, hh * 0.2)
        fill(ctx, G.rgb(spec["colours"].get("muzzle", "#f0c89a")))
        stroke(ctx, LINE, P["lw"] * 0.9)
    draw_nose(ctx, P, spec, L["nose"][0], L["nose"][1], C.turn)
    if f.get("beard"):                                   # a beard round the chin (white for old men)
        bcol = G.rgb(spec["colours"].get("beard", spec["colours"]["hair"]))
        ctx.new_path()
        G.smooth(ctx, [(mx - hw * 0.62, my - hh * 0.06), (mx - hw * 0.4, my + hh * 0.03), (mx, my + hh * 0.06),
                       (mx + hw * 0.4, my + hh * 0.03), (mx + hw * 0.62, my - hh * 0.06), (mx + hw * 0.55, my + hh * 0.12),
                       (mx + hw * 0.2, my + hh * (0.26 + 0.1 * f["beard"])), (mx - hw * 0.2, my + hh * (0.26 + 0.1 * f["beard"])),
                       (mx - hw * 0.55, my + hh * 0.12)])
        fill(ctx, bcol)
        stroke(ctx, LINE, P["lw"] * 0.8)
    draw_mouth(ctx, P, spec, face, mx, my, C.turn)
    if "tilak" in spec.get("accessories", []):            # a red / sandal tilak on the forehead
        G.line(ctx, [(L["fx"], L["brow_y"] - hh * 0.02), (L["fx"], L["brow_y"] - hh * 0.16)], P["lw"] * 1.6,
               G.rgb(spec["colours"].get("tilak", "#c8102e")))
    if "sindoor" in spec.get("accessories", []):          # sindoor in the parting
        G.line(ctx, [(L["fx"], -hh * 1.0), (L["fx"], -hh * 0.9)], P["lw"] * 1.8, G.rgb("#d0021b"))
    if "bindi" in spec.get("accessories", []):
        ctx.new_path()
        G.ellipse(ctx, L["fx"], L["brow_y"] + hh * 0.01, hw * 0.045, hw * 0.045)
        fill(ctx, G.rgb("#c8102e"), keep=False)
    if "glasses_round" in spec.get("accessories", []):
        er = hh * f.get("eye_size", 0.075)
        for ex, ey, s, sq in L["eyes"]:
            ctx.new_path()
            G.ellipse(ctx, ex, ey, er * 1.75 * sq, er * 1.55)
            ctx.set_source_rgba(0.85, 0.92, 1.0, 0.18)
            ctx.fill_preserve()
            stroke(ctx, G.rgb("#3a2a1a"), P["lw"] * 1.0)
        (x1, y1, _, s1), (x2, y2, _, s2) = L["eyes"]
        G.line(ctx, [(x1 + er * 1.75 * s1, y1), ((x1 + x2) / 2, y1 - er * 0.3), (x2 - er * 1.75 * s2, y2)], P["lw"], G.rgb("#3a2a1a"))


# ----------------------------------------------------------------------------------------------- hair

def hair_parts(spec, P):
    """(back parts, front parts): drawn behind the head / over it; st['hair'] = (sway_x, sway_y) in head units"""
    style = spec["hair"]["style"]
    hw, hh = P["head_w"] / 2, P["head_h"]
    col = G.rgb(spec["colours"]["hair"])

    def sw(C):
        return C.st.get("hair", (0.0, 0.0))

    def cap(C, k_top=1.06, k_side=1.04, low=0.58, sides=0.0):
        t = C.turn
        sh = t * hw * 0.1
        return [(sh - hw * k_side, -hh * low), (sh - hw * 0.98, -hh * 0.86), (sh - hw * 0.6, -hh * k_top),
                (sh + hw * 0.3, -hh * (k_top + 0.02)), (sh + hw * 0.95, -hh * 0.88), (sh + hw * k_side, -hh * low),
                (sh + hw * 0.88, -hh * (low + 0.06 + sides)), (sh, -hh * 0.82), (sh - hw * 0.88, -hh * (low + 0.06 + sides))]

    back, front = [], []
    if style == "side_part":
        def f_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            ctx.new_path()
            G.smooth(ctx, [(t - hw * 1.03, -hh * 0.55), (t - hw * 1.02, -hh * 0.82), (t - hw * 0.7, -hh * 1.05), (t + hw * 0.1, -hh * 1.12),
                           (t + hw * 0.8, -hh * 1.02), (t + hw * 1.05, -hh * 0.78), (t + hw * 1.02, -hh * 0.55),
                           (t + hw * 0.9, -hh * 0.62), (t + hw * 0.75, -hh * 0.80), (t + hw * 0.1 + sx * hw * 0.08, -hh * 0.78 + sy * hh * 0.02),
                           (t - hw * 0.45 + sx * hw * 0.12, -hh * 0.72), (t - hw * 0.8, -hh * 0.66), (t - hw * 0.92, -hh * 0.5)])

        def f_paint(ctx, C):
            t = C.turn * hw * 0.1
            G.line(ctx, [(t - hw * 0.35, -hh * 1.06), (t - hw * 0.1, -hh * 0.92), (t + hw * 0.3, -hh * 0.84)], P["lw"] * 0.8, G.shade(col, 1.5))
            G.line(ctx, [(t + hw * 0.2, -hh * 1.08), (t + hw * 0.6, -hh * 0.95)], P["lw"] * 0.7, G.shade(col, 1.5))
        front.append(Part("head", f_sil, f_paint))
    elif style == "braid_long":
        def b_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            ctx.new_path()
            G.smooth(ctx, [(t - hw * 1.12, -hh * 0.6), (t - hw * 1.1, -hh * 0.95), (t, -hh * 1.12), (t + hw * 1.1, -hh * 0.95),
                           (t + hw * 1.14, -hh * 0.55), (t + hw * 1.0, -hh * 0.2), (t - hw * 1.0, -hh * 0.2)])
            # the long braid behind the back, swaying from its root
            n = 7
            for i in range(n):
                u = i / (n - 1)
                bx = t + hw * 0.35 + sx * hw * 0.9 * u * u
                by = -hh * 0.15 + u * hh * 2.0 + sy * hh * 0.1 * u
                G.ellipse(ctx, bx, by, hw * (0.30 - 0.12 * u), hh * 0.17)

        def b_paint(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            bx = t + hw * 0.35 + sx * hw * 0.9
            by = -hh * 0.15 + hh * 2.0
            ctx.new_path()
            G.ellipse(ctx, bx, by - hh * 0.08, hw * 0.2, hh * 0.06)
            fill(ctx, G.rgb(spec["colours"].get("ribbon", "#c8102e")))
            stroke(ctx, LINE, P["lw"] * 0.7)
        back.append(Part("head", b_sil, b_paint))

        def f_sil(ctx, C):
            t = C.turn * hw * 0.1
            ctx.new_path()
            G.smooth(ctx, [(t - hw * 1.08, -hh * 0.42), (t - hw * 1.08, -hh * 0.85), (t - hw * 0.5, -hh * 1.1), (t + hw * 0.5, -hh * 1.1),
                           (t + hw * 1.08, -hh * 0.85), (t + hw * 1.08, -hh * 0.42), (t + hw * 0.92, -hh * 0.55), (t + hw * 0.75, -hh * 0.8),
                           (t + hw * 0.06, -hh * 0.93), (t - hw * 0.06, -hh * 0.93), (t - hw * 0.75, -hh * 0.8), (t - hw * 0.92, -hh * 0.55)])

        def f_paint(ctx, C):
            t = C.turn * hw * 0.1
            G.line(ctx, [(t, -hh * 1.1), (t, -hh * 0.94)], P["lw"] * 1.1, G.shade(col, 0.6))   # the centre parting
            ctx.new_path()                                   # sindoor-free: a simple hair shine
            G.line(ctx, [(t - hw * 0.6, -hh * 0.98), (t - hw * 0.3, -hh * 1.05)], P["lw"] * 0.8, G.shade(col, 1.6))
        front.append(Part("head", f_sil, f_paint))
    elif style == "bald_sides":
        def f_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.06
            ctx.new_path()
            for s in (-1, 1):
                if s * C.turn > 0.55:
                    continue
                x0 = t + s * hw * 0.90
                G.smooth(ctx, [(x0 - s * hw * 0.04, -hh * 0.74), (x0 + s * hw * 0.10 + sx * hw * 0.05, -hh * 0.73),
                               (x0 + s * hw * 0.16 + sx * hw * 0.08, -hh * 0.64 + sy * hh * 0.02), (x0 + s * hw * 0.12, -hh * 0.57),
                               (x0 + s * hw * 0.02, -hh * 0.60), (x0 - s * hw * 0.06, -hh * 0.66)])

        front.append(Part("head", f_sil, None))
    elif style == "bun_white":
        def b_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            ctx.new_path()
            G.ellipse(ctx, t - C.turn * hw * 0.4 + sx * hw * 0.05, -hh * 1.0 + sy * hh * 0.02, hw * 0.48, hh * 0.24)
            G.smooth(ctx, [(t - hw * 1.08, -hh * 0.5), (t - hw * 1.08, -hh * 0.9), (t, -hh * 1.08), (t + hw * 1.08, -hh * 0.9),
                           (t + hw * 1.08, -hh * 0.5), (t + hw * 0.9, -hh * 0.4), (t - hw * 0.9, -hh * 0.4)])

        def b_paint(ctx, C):
            t = C.turn * hw * 0.1
            G.line(ctx, [(t - C.turn * hw * 0.4 - hw * 0.3, -hh * 1.02), (t - C.turn * hw * 0.4 + hw * 0.3, -hh * 0.96)],
                   P["lw"] * 0.7, G.shade(col, 0.75))
        back.append(Part("head", b_sil, b_paint))

        def f_sil(ctx, C):
            t = C.turn * hw * 0.1
            ctx.new_path()
            G.smooth(ctx, [(t - hw * 1.05, -hh * 0.5), (t - hw * 1.04, -hh * 0.85), (t - hw * 0.5, -hh * 1.06), (t + hw * 0.5, -hh * 1.06),
                           (t + hw * 1.04, -hh * 0.85), (t + hw * 1.05, -hh * 0.5), (t + hw * 0.94, -hh * 0.58), (t + hw * 0.78, -hh * 0.9),
                           (t, -hh * 0.99), (t - hw * 0.78, -hh * 0.9), (t - hw * 0.94, -hh * 0.58)])

        def f_paint(ctx, C):
            t = C.turn * hw * 0.1
            G.line(ctx, [(t, -hh * 1.06), (t, -hh * 0.91)], P["lw"] * 0.9, G.shade(col, 0.7))
            for s in (-1, 1):
                G.line(ctx, [(t + s * hw * 0.2, -hh * 1.0), (t + s * hw * 0.65, -hh * 0.88), (t + s * hw * 0.9, -hh * 0.66)],
                       P["lw"] * 0.6, G.shade(col, 0.75))
        front.append(Part("head", f_sil, f_paint))
    elif style == "spiky":
        def f_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            pts = [(t - hw * 1.05, -hh * 0.55), (t - hw * 1.0, -hh * 0.85)]
            n = 6
            for i in range(n):
                u = i / (n - 1)
                x = t - hw * 0.95 + u * hw * 1.9
                y = -hh * (1.02 + 0.06 * math.sin(math.pi * u))
                tip = (x + hw * 0.10 + sx * hw * 0.18 * (0.5 + u), y - hh * 0.11 + sy * hh * 0.04)
                pts += [(x, y), tip]
            pts += [(t + hw * 1.0, -hh * 0.85), (t + hw * 1.05, -hh * 0.55), (t + hw * 0.88, -hh * 0.66), (t + hw * 0.5, -hh * 0.78),
                    (t + hw * 0.1 + sx * hw * 0.1, -hh * 0.72), (t - hw * 0.25, -hh * 0.8), (t - hw * 0.6, -hh * 0.74), (t - hw * 0.9, -hh * 0.62)]
            ctx.new_path()
            G.smooth(ctx, pts, tension=0.25)

        def f_paint(ctx, C):
            t = C.turn * hw * 0.1
            G.line(ctx, [(t - hw * 0.4, -hh * 1.0), (t - hw * 0.1, -hh * 0.9)], P["lw"] * 0.8, G.shade(col, 1.6))
        front.append(Part("head", f_sil, f_paint))
    elif style == "pigtails":
        def b_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            ctx.new_path()
            G.smooth(ctx, [(t - hw * 1.1, -hh * 0.5), (t - hw * 1.1, -hh * 0.9), (t, -hh * 1.1), (t + hw * 1.1, -hh * 0.9),
                           (t + hw * 1.1, -hh * 0.5), (t, -hh * 0.4)])
            for s in (-1, 1):                               # the two pigtails swing from above the ears
                x0 = t + s * hw * 1.05
                tip = (x0 + s * hw * 0.55 + sx * hw * 0.5, -hh * 0.05 + sy * hh * 0.08)
                G.smooth(ctx, [(x0 - s * hw * 0.1, -hh * 0.72), (x0 + s * hw * 0.3, -hh * 0.62), (tip[0] + s * hw * 0.08, tip[1]),
                               (tip[0] - s * hw * 0.1, tip[1] + hh * 0.05), (x0 + s * hw * 0.05, -hh * 0.4)])

        def b_paint(ctx, C):
            sx, _ = sw(C)
            t = C.turn * hw * 0.1
            for s in (-1, 1):
                x0 = t + s * hw * 1.12
                ctx.new_path()
                for k in (-1, 1):
                    G.ellipse(ctx, x0 + k * hw * 0.12, -hh * 0.68, hw * 0.13, hh * 0.06, ang=k * 0.5)
                fill(ctx, G.rgb(spec["colours"].get("ribbon", "#d62839")))
                stroke(ctx, LINE, P["lw"] * 0.7)
        back.append(Part("head", b_sil, b_paint))

        def f_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            pts = [(t - hw * 1.06, -hh * 0.5), (t - hw * 1.05, -hh * 0.86), (t - hw * 0.5, -hh * 1.08), (t + hw * 0.5, -hh * 1.08),
                   (t + hw * 1.05, -hh * 0.86), (t + hw * 1.06, -hh * 0.5), (t + hw * 0.9, -hh * 0.62)]
            for i in range(5):                               # the fringe
                u = 1 - i / 4
                x = t - hw * 0.85 + u * hw * 1.7
                pts += [(x, -hh * (0.73 - 0.03 * math.sin(i * 1.7)) + sy * hh * 0.01), (x - hw * 0.2, -hh * 0.82)]
            pts += [(t - hw * 0.9, -hh * 0.62)]
            ctx.new_path()
            G.smooth(ctx, pts, tension=0.3)

        front.append(Part("head", f_sil, None))
    elif style == "open_long":                          # long loose hair (a ghost's): down to the waist, swaying
        def b_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            ctx.new_path()
            pts = [(t - hw * 1.15, -hh * 0.6), (t - hw * 1.12, -hh * 0.95), (t, -hh * 1.14), (t + hw * 1.12, -hh * 0.95),
                   (t + hw * 1.15, -hh * 0.6)]
            n = 7
            for i in range(n):                              # the ragged ends, each strand lock swinging a little later
                u = i / (n - 1)
                x = t + hw * (1.25 - 2.5 * u)
                lag = 0.6 + 0.4 * math.sin(i * 1.7)
                pts.append((x + sx * hw * 1.1 * lag, hh * (1.75 + 0.18 * math.sin(i * 2.3)) + sy * hh * 0.15))
                pts.append((x - hw * 0.18 + sx * hw * 0.9 * lag, hh * 1.45))
            pts += [(t - hw * 1.3, hh * 0.9), (t - hw * 1.2, -hh * 0.1)]
            G.smooth(ctx, pts, tension=0.35)

        def b_paint(ctx, C):
            sx, _ = sw(C)
            t = C.turn * hw * 0.1
            for k in (-0.6, 0.0, 0.6):
                G.line(ctx, [(t + k * hw, -hh * 0.6), (t + k * hw * 1.2 + sx * hw * 0.5, hh * 0.5),
                             (t + k * hw * 1.3 + sx * hw * 0.9, hh * 1.4)], P["lw"] * 0.6, G.shade(col, 1.5))
        back.append(Part("head", b_sil, b_paint))

        def f_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            ctx.new_path()
            for s_ in (-1, 1):                              # two curtains of hair over the sides of the face
                G.smooth(ctx, [(t + s_ * hw * 0.05, -hh * 1.12), (t + s_ * hw * 1.12, -hh * 0.95), (t + s_ * hw * 1.16, -hh * 0.4),
                               (t + s_ * hw * 1.1 + sx * hw * 0.2, hh * 0.35), (t + s_ * hw * 0.78 + sx * hw * 0.25, hh * 0.45),
                               (t + s_ * hw * 0.74, -hh * 0.2), (t + s_ * hw * 0.62, -hh * 0.72), (t + s_ * hw * 0.2, -hh * 0.96)],
                         tension=0.4)
        front.append(Part("head", f_sil, None))
    elif style in ("tiki", "shaved"):                   # shaven head; a tiki tuft at the back of the crown
        if style == "tiki":
            def b_sil(ctx, C):
                sx, sy = sw(C)
                t = C.turn * hw * 0.1
                ctx.new_path()
                G.smooth(ctx, [(t + hw * 0.05, -hh * 1.02), (t + hw * 0.25, -hh * 1.06), (t + hw * 0.5 + sx * hw * 0.4, -hh * 0.8),
                               (t + hw * 0.62 + sx * hw * 0.7, -hh * 0.55 + sy * hh * 0.05), (t + hw * 0.45 + sx * hw * 0.5, -hh * 0.62),
                               (t + hw * 0.3, -hh * 0.86)], tension=0.35)
            back.append(Part("head", b_sil, None))

        def f_paint_only(ctx, C):
            t = C.turn * hw * 0.1
            ctx.new_path()
            G.smooth(ctx, cap(C, 1.0, 1.0, 0.6))
            ctx.set_source_rgba(*col, 0.25)                  # a shadow of stubble
            ctx.fill()

        def f_sil(ctx, C):
            ctx.new_path()
            ctx.rectangle(0, 0, 0.01, 0.01)
        front.append(Part("head", f_sil, f_paint_only, outline=False))
    elif style == "jata":                               # a tantrik's matted locks: a tall knot and locks on the back
        def b_sil(ctx, C):
            sx, sy = sw(C)
            t = C.turn * hw * 0.1
            ctx.new_path()
            G.smooth(ctx, [(t - hw * 1.12, -hh * 0.55), (t - hw * 1.1, -hh * 0.95), (t, -hh * 1.1), (t + hw * 1.1, -hh * 0.95),
                           (t + hw * 1.12, -hh * 0.55), (t + hw * 1.25 + sx * hw * 0.4, hh * 0.55), (t + hw * 0.9 + sx * hw * 0.3, hh * 0.6),
                           (t, hh * 0.1), (t - hw * 0.9 + sx * hw * 0.3, hh * 0.6), (t - hw * 1.25 + sx * hw * 0.4, hh * 0.55)])
            G.ellipse(ctx, t + sx * hw * 0.06, -hh * 1.22, hw * 0.42, hh * 0.24)     # the knot on top

        def b_paint(ctx, C):
            t = C.turn * hw * 0.1
            for k in (-0.2, 0.15):
                G.line(ctx, [(t - hw * 0.35, -hh * (1.22 + k)), (t + hw * 0.35, -hh * (1.2 + k))], P["lw"] * 0.7, G.shade(col, 0.6))
        back.append(Part("head", b_sil, b_paint))

        def f_sil(ctx, C):
            ctx.new_path()
            G.smooth(ctx, cap(C, 1.08, 1.06, 0.5, 0.05))
        front.append(Part("head", f_sil, None))
    elif style in ("crop", "curly", "bun_black"):
        def f_sil(ctx, C):
            sx, sy = sw(C)
            ctx.new_path()
            if style == "curly":
                t = C.turn * hw * 0.1
                for i in range(9):
                    a = math.pi + i * math.pi / 8
                    G.ellipse(ctx, t + math.cos(a) * hw * 0.92, -hh * 0.72 + math.sin(a) * hh * 0.34, hw * 0.26, hh * 0.15)
            else:
                G.smooth(ctx, cap(C, 1.05 if style == "crop" else 1.07, 1.03, 0.6 if style == "crop" else 0.5))
            if style == "bun_black":
                t = C.turn * hw * 0.1
                G.ellipse(ctx, t - C.turn * hw * 0.4 + sx * hw * 0.04, -hh * 1.02, hw * 0.45, hh * 0.22)
        front.append(Part("head", f_sil, None))
    headwear(spec, P, back, front)
    return back, front


def headwear(spec, P, back, front):
    """turbans and crowns for kings, ministers and guards; the gods' crown (mukut), peacock feather and halo;
    Ganesha's elephant ears and trunk. Colours: 'turban', 'crown' (default gold)."""
    acc = spec.get("accessories", [])
    hw, hh = P["head_w"] / 2, P["head_h"]
    cols = spec["colours"]

    def T(C):
        return C.turn * hw * 0.1

    if "halo" in acc:                                     # a soft golden halo behind the head (no outline)
        def h_sil(ctx, C):
            ctx.arc(T(C), -hh * 0.62, hh * 0.95, 0, 2 * math.pi)

        def h_paint(ctx, C):
            ctx.new_path()
            g = cairo.RadialGradient(T(C), -hh * 0.62, hh * 0.3, T(C), -hh * 0.62, hh * 0.95)
            g.add_color_stop_rgba(0, 1.0, 0.9, 0.5, 0.0)
            g.add_color_stop_rgba(0.75, 1.0, 0.85, 0.35, 0.55)
            g.add_color_stop_rgba(1, 1.0, 0.85, 0.35, 0.0)
            ctx.set_source(g)
            ctx.arc(T(C), -hh * 0.62, hh * 0.95, 0, 2 * math.pi)
            ctx.fill()
        back.insert(0, Part("head", lambda ctx, C: None, h_paint, outline=False))
    if "elephant_head" in acc:                            # Ganesha: big ears behind, the trunk in front
        def e_sil(ctx, C):
            for s_ in (-1, 1):
                G.ellipse(ctx, T(C) + s_ * hw * 1.25, -hh * 0.55, hw * 0.7, hh * 0.5, ang=s_ * 0.2)

        def e_paint(ctx, C):
            ctx.new_path()
            e_sil(ctx, C)                       # (the base fill was the part's default colour)
            fill(ctx, G.shade(cols["skin"], 0.9), keep=False)
        back.append(Part("head", e_sil, e_paint))

        def tr_sil(ctx, C):
            sw_ = math.sin(C.st.get("t", 0.0) * 1.3) * hw * 0.12 + C.turn * hw * 0.3
            G.smooth(ctx, [(T(C) - hw * 0.22, -hh * 0.45), (T(C) + hw * 0.22, -hh * 0.45), (T(C) + hw * 0.18 + sw_, -hh * 0.05),
                           (T(C) + hw * 0.45 + sw_, hh * 0.18), (T(C) + hw * 0.32 + sw_, hh * 0.25), (T(C) + sw_ * 0.5, hh * 0.02),
                           (T(C) - hw * 0.18, -hh * 0.2)], tension=0.4)

        def tr_paint(ctx, C):
            ctx.new_path()
            tr_sil(ctx, C)                       # (the base fill was the part's default colour)
            fill(ctx, G.rgb(cols["skin"]), keep=False)
            G.line(ctx, [(T(C) + hw * 0.3, -hh * 0.3), (T(C) + hw * 0.55, -hh * 0.18)], P["lw"] * 3, (0.97, 0.95, 0.88))
        front.append(Part("head", tr_sil, tr_paint))
    if "turban" in acc:
        tc = G.rgb(cols.get("turban", "#f2efe6"))

        def t_sil(ctx, C):
            t = T(C)
            G.smooth(ctx, [(t - hw * 1.08, -hh * 0.72), (t - hw * 1.12, -hh * 1.0), (t - hw * 0.6, -hh * 1.3), (t + hw * 0.4, -hh * 1.32),
                           (t + hw * 1.1, -hh * 1.05), (t + hw * 1.06, -hh * 0.72), (t, -hh * 0.8)], tension=0.4)

        def t_paint(ctx, C):
            t = T(C)
            ctx.new_path()
            t_sil(ctx, C)                       # (the base fill was the part's default colour)
            fill(ctx, tc, keep=False)
            for k in range(3):
                G.line(ctx, [(t - hw * 1.0, -hh * (0.8 + 0.12 * k)), (t, -hh * (0.92 + 0.14 * k)), (t + hw * 1.0, -hh * (0.82 + 0.12 * k))],
                       P["lw"] * 0.9, G.shade(tc, 0.7))
            if "jewel" in acc or "plume" in acc:
                ctx.new_path()
                G.ellipse(ctx, t + C.turn * hw * 0.25, -hh * 1.0, hw * 0.12, hh * 0.08)
                fill(ctx, G.rgb("#c62828"))
                stroke(ctx, LINE, P["lw"] * 0.7)
            if "plume" in acc:
                sw_ = math.sin(C.st.get("t", 0.0) * 2.0) * hw * 0.08
                G.line(ctx, [(t + C.turn * hw * 0.25, -hh * 1.08), (t + hw * 0.1 + sw_, -hh * 1.35), (t + hw * 0.35 + sw_ * 2, -hh * 1.55)],
                       P["lw"] * 3.2, (0.98, 0.98, 0.96))
        front.append(Part("head", t_sil, t_paint))
    if "crown" in acc or "mukut" in acc:
        cc = G.rgb(cols.get("crown", "#e0b030"))
        tall = 0.55 if "mukut" in acc else 0.35

        def c_sil(ctx, C):
            t = T(C)
            pts = [(t - hw * 0.9, -hh * 0.82), (t - hw * 0.95, -hh * (0.95 + tall * 0.6))]
            for k in range(5):
                x = t - hw * 0.7 + k * hw * 0.35
                pts += [(x, -hh * (0.95 + tall * (1.0 if k == 2 else 0.75))), (x + hw * 0.17, -hh * (0.95 + tall * 0.45))]
            pts += [(t + hw * 0.95, -hh * (0.95 + tall * 0.6)), (t + hw * 0.9, -hh * 0.82)]
            ctx.move_to(*pts[0])
            for p in pts[1:]:
                ctx.line_to(*p)
            ctx.close_path()

        def c_paint(ctx, C):
            t = T(C)
            ctx.new_path()
            c_sil(ctx, C)                       # (the base fill was the part's default colour)
            fill(ctx, cc, keep=False)
            G.line(ctx, [(t - hw * 0.9, -hh * 0.9), (t + hw * 0.9, -hh * 0.9)], P["lw"] * 2.5, G.shade(cc, 0.7))
            for k, c in ((-1, "#c62828"), (0, "#1e88e5"), (1, "#2e7d32")):
                ctx.new_path()
                G.ellipse(ctx, t + k * hw * 0.45, -hh * 1.0, hw * 0.09, hh * 0.06)
                fill(ctx, G.rgb(c))
                stroke(ctx, LINE, P["lw"] * 0.6)
            if "peacock_feather" in acc:                  # Krishna's peacock feather
                sw_ = math.sin(C.st.get("t", 0.0) * 1.7) * hw * 0.06
                G.line(ctx, [(t + hw * 0.3, -hh * (1.0 + tall)), (t + hw * 0.5 + sw_, -hh * (1.25 + tall))], P["lw"] * 1.5, G.rgb("#2a6a3a"))
                ctx.new_path()
                G.ellipse(ctx, t + hw * 0.55 + sw_, -hh * (1.32 + tall), hw * 0.16, hh * 0.13, ang=0.4)
                fill(ctx, G.rgb("#2a9a6a"))
                stroke(ctx, LINE, P["lw"] * 0.6)
                ctx.new_path()
                G.ellipse(ctx, t + hw * 0.56 + sw_, -hh * (1.32 + tall), hw * 0.07, hh * 0.06)
                fill(ctx, G.rgb("#1a3a9a"), keep=False)
        front.append(Part("head", c_sil, c_paint))


# ----------------------------------------------------------------------------------------------- body

def torso_pts(P, spec, C, hem):
    T = P["torso"]
    k = 1.0 - 0.10 * abs(C.body_turn)
    sh, ch, wa, hp = P["shoulder"] * k, P["chest"] * k, P["waist"] * k, P["hip"] * k
    belly = P["belly"]
    nw = P["head_w"] * 0.17
    right = [(hp * 1.0, hem), (wa * (1 + belly), -0.18 * T), (wa * (1 + belly * 0.5), -0.42 * T), (ch, -0.66 * T),
             (sh, -T * 0.85), (sh * 0.86, -T * 0.96), (sh * 0.55, -T * 1.01), (nw * 1.3, -T * 1.03)]
    left = [(-x, y) for x, y in reversed(right)]
    return right + [(0, -T * 1.0)] + left


def body_parts(spec, P):
    """the body group: lower garment, skirt, torso (with costume details), neck"""
    cos = spec["costume"]
    typ = cos["type"]
    T, H = P["torso"], P["H"]
    parts = []
    lw = P["lw"]

    # neck
    def neck_sil(ctx, C):
        ctx.new_path()
        ctx.save()
        ctx.scale(1, -1)
        G.capsule(ctx, P["neck"] * 1.6 + P["head_w"] * 0.1, P["head_w"] * 0.15, P["head_w"] * 0.14)
        ctx.restore()

    def neck_paint(ctx, C):
        ctx.save()
        ctx.new_path()
        ctx.save()
        ctx.scale(1, -1)
        G.capsule(ctx, P["neck"] * 1.6 + P["head_w"] * 0.1, P["head_w"] * 0.15, P["head_w"] * 0.14)
        ctx.restore()
        ctx.clip()
        ctx.new_path()
        ctx.rectangle(-P["head_w"], -P["neck"] * 1.6, P["head_w"] * 2, P["neck"] * 0.9)
        fill(ctx, G.shade(C.col["skin"], 0.85), keep=False)
        ctx.restore()
    neck = Part("neck", neck_sil, neck_paint)

    # lower garment over the hips (covers the thigh tops)
    if typ in ("shirt_trousers", "tshirt_shorts", "kurta_dhoti"):
        gcol = "trousers" if typ == "shirt_trousers" else "shorts" if typ == "tshirt_shorts" else "dhoti"

        def pel_sil(ctx, C):
            hp = P["hip"] * (1 - 0.1 * abs(C.body_turn))
            ctx.new_path()
            G.smooth(ctx, [(-hp * 0.97, -P["pelvis_up"] * 1.2), (hp * 0.97, -P["pelvis_up"] * 1.2), (hp * 0.99, H * 0.03),
                           (hp * 0.45, H * 0.055), (0, H * 0.045), (-hp * 0.45, H * 0.055), (-hp * 0.99, H * 0.03)], tension=0.15)

        def pel_paint(ctx, C):
            G.line(ctx, [(0, -P["pelvis_up"] * 0.6), (0, H * 0.04)], lw * 0.7, G.shade(C.col[gcol], 0.6))
        parts.append(Part("root", pel_sil, pel_paint))

    if typ in ("saree", "frock"):
        def skirt_pts(C):
            fa = C.local("root", *C.sk.joint(C.W, "foot_a", 0.5))
            fb = C.local("root", *C.sk.joint(C.W, "foot_b", 0.5))
            sway = C.st.get("cloth", 0.0) * P["hip"] * 0.25
            if typ == "saree":
                hem_y = max(fa[1], fb[1]) - P["foot_h"] * 0.6
                lo = min(fa[0], fb[0]) - P["hip"] * 0.55
                hi = max(fa[0], fb[0]) + P["hip"] * 0.55
                top = -P["pelvis_up"] * 1.3
                return [(-P["waist"] * 1.02, top), (P["waist"] * 1.02, top), (P["hip"] * 1.12, H * 0.05),
                        (hi + sway, hem_y - H * 0.02), (hi + sway * 1.2, hem_y), ((lo + hi) / 2 + sway, hem_y + H * 0.008),
                        (lo + sway * 1.2, hem_y), (lo + sway, hem_y - H * 0.02), (-P["hip"] * 1.12, H * 0.05)]
            knee = C.local("root", *C.sk.joint(C.W, "shin_a", 0.0))[1]
            hem_y = knee + P["shin"] * 0.08
            w = P["hip"] * 1.75
            return [(-P["waist"], -P["pelvis_up"] * 1.25), (P["waist"], -P["pelvis_up"] * 1.25),
                    (w * 0.8 + sway, hem_y - H * 0.04), (w + sway * 1.2, hem_y), (w * 0.35 + sway, hem_y + H * 0.012),
                    (-w * 0.35 + sway, hem_y + H * 0.012), (-w + sway * 1.2, hem_y), (-w * 0.8 + sway, hem_y - H * 0.04)]

        def sk_sil(ctx, C):
            ctx.new_path()
            G.smooth(ctx, skirt_pts(C), tension=0.35)

        def sk_paint(ctx, C):
            pts = skirt_pts(C)
            main = C.col["saree" if typ == "saree" else "frock"]
            shadow_side(ctx, lambda c: G.smooth(c, skirt_pts(C), tension=0.35), G.shade(main, 0.85), -P["hip"] * 0.25, 0)
            hem = [pts[5], pts[4], pts[3]] if typ == "saree" else [pts[6], pts[5], pts[4], pts[3]]
            if typ == "saree":                             # the border along the hem and the pleats
                ctx.save()
                ctx.new_path()
                G.smooth(ctx, pts, tension=0.35)
                ctx.clip()
                hy = pts[5][1]
                ctx.new_path()
                ctx.rectangle(-5000, hy - H * 0.045, 10000, H * 0.2)
                fill(ctx, C.col["border"], keep=False)
                G.line(ctx, [(-5000, hy - H * 0.045), (5000, hy - H * 0.045)], lw * 0.7, G.shade(C.col["border"], 0.6))
                G.line(ctx, [(-5000, hy - H * 0.028), (5000, hy - H * 0.028)], lw * 0.5, G.rgb("#f2c14e"))
                for k in (-1, 0, 1):
                    x0 = P["waist"] * 0.2 + k * P["hip"] * 0.18
                    G.line(ctx, [(x0, H * 0.06), (x0 + k * P["hip"] * 0.15 + C.st.get("cloth", 0) * P["hip"] * 0.1, hy - H * 0.05)],
                           lw * 0.6, G.shade(main, 0.65))
                ctx.restore()
            else:
                G.line(ctx, [(-P["hip"] * 0.4, H * 0.02), (-P["hip"] * 0.7, pts[3][1] - H * 0.03)], lw * 0.6, G.shade(main, 0.7))
                G.line(ctx, [(P["hip"] * 0.4, H * 0.02), (P["hip"] * 0.7, pts[3][1] - H * 0.03)], lw * 0.6, G.shade(main, 0.7))
                ctx.save()
                ctx.new_path()
                G.smooth(ctx, pts, tension=0.35)
                ctx.clip()
                ctx.new_path()
                ctx.rectangle(-5000, pts[4][1] - H * 0.03, 10000, H * 0.2)
                fill(ctx, C.col.get("trim", (1, 1, 1)), keep=False)
                ctx.restore()
        parts.append(Part("root", sk_sil, sk_paint))

    hem = {"shirt_trousers": P["pelvis_up"] * 0.55, "tshirt_shorts": P["pelvis_up"] * 0.5, "kurta_dhoti": P["pelvis_up"] + H * 0.17,
           "saree": (-P["torso"] * 0.24 if not spec["face"].get("wrinkles") else P["pelvis_up"] * 0.3), "frock": P["pelvis_up"] * 0.15}[typ]
    top_col = {"shirt_trousers": "shirt", "tshirt_shorts": "tshirt", "kurta_dhoti": "kurta", "saree": "blouse",
               "frock": "frock"}[typ]

    def t_pts(C):
        pts = torso_pts(P, spec, C, hem)
        if typ == "kurta_dhoti":                       # the kurta flares to the knees
            pts[0] = (pts[0][0] * 1.18, pts[0][1])
            pts[-1] = (pts[-1][0] * 1.18, pts[-1][1])
        return pts

    def t_sil(ctx, C):
        ctx.new_path()
        G.smooth(ctx, t_pts(C), tension=0.45)
        if typ == "saree" and not spec["face"].get("wrinkles"):   # a small bare midriff (young women only)
            ctx.new_sub_path()
            G.smooth(ctx, [(-P["waist"] * 0.98, -T * 0.24), (P["waist"] * 0.98, -T * 0.24), (P["waist"] * 1.02, -T * 0.06),
                           (-P["waist"] * 1.02, -T * 0.06)], tension=0.2)

    def t_paint(ctx, C):
        main = C.col[top_col]
        if typ == "saree" and not spec["face"].get("wrinkles"):
            ctx.new_path()
            G.smooth(ctx, [(-P["waist"] * 0.98, -T * 0.24), (P["waist"] * 0.98, -T * 0.24), (P["waist"] * 1.02, -T * 0.06),
                           (-P["waist"] * 1.02, -T * 0.06)], tension=0.2)
            fill(ctx, C.col["skin"], keep=False)
            ctx.new_path()
            G.smooth(ctx, t_pts(C), tension=0.45)
            fill(ctx, main, keep=False)
        shadow_side(ctx, lambda c: G.smooth(c, t_pts(C), tension=0.45), G.shade(main, 0.84), -P["shoulder"] * 0.18, 0)
        nw = P["head_w"] * 0.17
        if typ in ("shirt_trousers", "kurta_dhoti"):     # collar / placket / pocket / buttons
            G.line(ctx, [(-nw * 1.6, -T * 1.0), (0, -T * 0.82), (nw * 1.6, -T * 1.0)], lw * 0.9, LINE, smooth_it=False)
            if typ == "shirt_trousers":
                for s in (-1, 1):                          # a shirt collar: two points down from the neck
                    ctx.new_path()
                    ctx.move_to(s * nw * 0.2, -T * 1.0)
                    ctx.line_to(s * nw * 1.7, -T * 1.04)
                    ctx.line_to(s * nw * 1.45, -T * 0.90)
                    ctx.line_to(s * nw * 0.15, -T * 0.86)
                    ctx.close_path()
                    fill(ctx, G.shade(main, 1.18))
                    stroke(ctx, LINE, lw * 0.8)
                G.line(ctx, [(0, -T * 0.84), (0, hem - H * 0.01)], lw * 0.7, G.shade(main, 0.6))
                for k in range(4):
                    ctx.new_path()
                    G.ellipse(ctx, nw * 0.25, -T * (0.76 - 0.2 * k), lw * 0.9, lw * 0.9)
                    fill(ctx, (0.95, 0.95, 0.9))
                    stroke(ctx, LINE, lw * 0.4)
                ctx.new_path()
                ctx.rectangle(P["chest"] * 0.25, -T * 0.72, P["chest"] * 0.38, T * 0.13)
                stroke(ctx, G.shade(main, 0.6), lw * 0.7)
            else:
                G.line(ctx, [(0, -T * 0.82), (0, -T * 0.45)], lw * 0.7, G.shade(main, 0.7))
                for k in range(3):
                    ctx.new_path()
                    G.ellipse(ctx, nw * 0.2, -T * (0.76 - 0.12 * k), lw * 0.8, lw * 0.8)
                    fill(ctx, G.rgb("#c9a227"), keep=False)
        if typ == "tshirt_shorts":
            G.line(ctx, [(-nw * 1.7, -T * 1.0), (0, -T * 0.9), (nw * 1.7, -T * 1.0)], lw * 0.9, LINE)
            ctx.save()
            ctx.new_path()
            G.smooth(ctx, t_pts(C), tension=0.45)
            ctx.clip()
            ctx.new_path()
            ctx.rectangle(-5000, -T * 0.55, 10000, T * 0.12)
            fill(ctx, C.col.get("stripe", (1, 1, 1)), keep=False)
            ctx.restore()
        if typ == "frock":
            for s in (-1, 1):                              # the round white collar
                ctx.new_path()
                G.ellipse(ctx, s * nw * 1.5, -T * 0.93, nw * 1.7, T * 0.09, ang=-s * 0.3)
                fill(ctx, C.col.get("trim", (1, 1, 1)))
                stroke(ctx, LINE, lw * 0.8)
            for k in range(3):
                ctx.new_path()
                G.ellipse(ctx, 0, -T * (0.72 - 0.16 * k), lw, lw)
                fill(ctx, C.col.get("trim", (1, 1, 1)))
                stroke(ctx, LINE, lw * 0.4)
        if typ == "saree":                                 # the pallu: a band from the right hip over the left shoulder
            sh = P["shoulder"]

            def band(c):
                G.smooth(c, [(sh * 0.95, -T * 0.08), (sh * 0.6, H * 0.01), (-sh * 0.05, -T * 0.6), (-sh * 1.05, -T * 1.02),
                             (-sh * 0.62, -T * 1.07), (sh * 0.25, -T * 0.66)], tension=0.4)
            ctx.new_path()
            band(ctx)
            fill(ctx, C.col["saree"])
            stroke(ctx, LINE, lw * 0.9)
            ctx.save()
            ctx.new_path()
            band(ctx)
            ctx.clip()
            G.line(ctx, [(sh * 1.05, -T * 0.13), (sh * 0.3, -T * 0.69), (-sh * 0.6, -T * 1.1)], H * 0.022, C.col["border"])
            G.line(ctx, [(sh * 0.5, -T * 0.22), (-sh * 0.4, -T * 0.86)], lw * 0.6, G.shade(C.col["saree"], 0.7))
            ctx.restore()
        acc = spec.get("accessories", [])
        sh = P["shoulder"]
        if "sacred_thread" in acc:                          # the poite: a thin thread over the left shoulder
            G.line(ctx, [(-sh * 0.7, -T * 0.98), (0, -T * 0.55), (sh * 0.72, -T * 0.05)], lw * 0.9, (0.97, 0.95, 0.86))
        if "rudraksha" in acc:                              # a string of rudraksha beads round the neck
            for i in range(11):
                a = math.pi * (0.15 + 0.7 * i / 10)
                bx, by = math.cos(a) * sh * 0.42, -T * 1.0 + math.sin(a) * T * 0.36
                ctx.new_path()
                G.ellipse(ctx, bx, by, lw * 1.6, lw * 1.6)
                fill(ctx, G.rgb("#5a2e1a"))
                stroke(ctx, LINE, lw * 0.4)
        if "shawl" in acc:                                  # a shawl over both shoulders
            ctx.new_path()
            G.smooth(ctx, [(-sh * 1.05, -T * 0.95), (-sh * 0.5, -T * 1.06), (sh * 0.5, -T * 1.06), (sh * 1.05, -T * 0.95),
                           (sh * 0.9, -T * 0.45), (sh * 0.5, -T * 0.78), (-sh * 0.5, -T * 0.78), (-sh * 0.9, -T * 0.45)], tension=0.35)
            fill(ctx, C.col.get("shawl", G.rgb("#7a5230")))
            stroke(ctx, LINE, lw * 0.9)
        if "torn" in acc:                                   # rags: a few tears and patches
            for k in range(3):
                x_ = (-0.4 + 0.4 * k) * sh
                G.line(ctx, [(x_, -T * (0.2 + 0.2 * k)), (x_ + sh * 0.08, -T * (0.12 + 0.2 * k)), (x_ - sh * 0.05, -T * (0.05 + 0.2 * k))],
                       lw * 0.8, G.shade(main, 0.6))
    parts.append(Part("spine", t_sil, t_paint))
    return neck, parts


def back_cloth(spec, P):
    """saree pallu hanging behind the shoulder (drawn behind everything)"""
    if spec["costume"]["type"] != "saree":
        return []
    T, H = P["torso"], P["H"]

    def sil(ctx, C):
        sw_ = C.st.get("cloth", 0.0) * P["hip"] * 0.4
        sh = P["shoulder"]
        ctx.new_path()
        G.smooth(ctx, [(-sh * 1.08, -T * 1.0), (-sh * 0.6, -T * 1.02), (-sh * 0.55 + sw_, -T * 0.1), (-sh * 0.9 + sw_ * 1.4, T * 0.35),
                       (-sh * 1.45 + sw_ * 1.5, T * 0.38), (-sh * 1.3 + sw_, -T * 0.3)], tension=0.4)

    def paint(ctx, C):
        ctx.save()
        sil(ctx, C)
        ctx.clip()
        sw_ = C.st.get("cloth", 0.0) * P["hip"] * 0.4
        ctx.new_path()
        ctx.rectangle(-5000, T * 0.26 + sw_ * 0.1, 10000, H)
        fill(ctx, C.col["border"], keep=False)
        ctx.restore()
    return [Part("spine", sil, paint)]


# ----------------------------------------------------------------------------------------------- limbs

HANDS = {   # finger lists: (angle deg from the hand axis, length factor, curl 0..1); thumb first. 5 entries = 5 fingers
    "relax": [(-48, 0.55, 0.3), (-10, 0.78, 0.35), (0, 0.85, 0.35), (9, 0.80, 0.35), (18, 0.66, 0.35)],
    "open": [(-62, 0.62, 0.0), (-20, 0.85, 0.0), (-6, 0.95, 0.0), (8, 0.9, 0.0), (22, 0.72, 0.0)],
    "point": [(-55, 0.5, 0.6), (0, 1.0, 0.0), (8, 0.55, 1.0), (14, 0.5, 1.0), (20, 0.45, 1.0)],
    "fist": [(-40, 0.48, 0.7), (-8, 0.5, 1.0), (0, 0.5, 1.0), (8, 0.5, 1.0), (16, 0.45, 1.0)],
    "flat": [(-25, 0.5, 0.0), (-3, 0.9, 0.0), (0, 0.95, 0.0), (3, 0.9, 0.0), (6, 0.75, 0.0)],
}


def hand_shape(ctx, P, shape, inner):
    """a hand on its bone (+y toward the fingertips). inner = +1/-1: the side of the thumb"""
    L = P["hand"]
    pw = P["arm_r"] * 1.05
    palm_l = L * 0.48
    fr = P["arm_r"] * 0.30
    ctx.new_path()
    G.ellipse(ctx, 0, palm_l * 0.55, pw, palm_l * 0.62)
    for i, (a, ln, curl) in enumerate(HANDS[shape]):
        base_x = inner * pw * 0.75 if i == 0 else (-pw * 0.62 + (i - 1) * pw * 0.41) * -inner
        base_y = palm_l * (0.45 if i == 0 else 0.95)
        ang = math.radians(a) * inner
        flen = L * 0.52 * ln * (1 - 0.55 * curl)
        ex, ey = base_x - math.sin(ang) * flen, base_y + math.cos(ang) * flen
        ctx.new_sub_path()
        ctx.save()
        ctx.translate(base_x, base_y)
        ctx.rotate(ang)
        G.capsule(ctx, flen, fr * (1.15 if i == 0 else 1.0), fr * 0.92)
        ctx.restore()


def hand_detail(ctx, P, shape, inner, skin, lw):
    """what makes a cartoon hand read as a HAND (23 Nov 2026): a soft shade on the palm's outer edge, the lines
    between the fingers, the thumb's crease, knuckles on a fist, light nails on open fingertips"""
    L = P["hand"]
    pw = P["arm_r"] * 1.05
    palm_l = L * 0.48
    dark = G.shade(skin, 0.58)
    ctx.save()                                            # the palm's outer edge in shade (light from the thumb side)
    ctx.new_path()
    G.ellipse(ctx, -inner * pw * 0.45, palm_l * 0.6, pw * 0.55, palm_l * 0.55)
    ctx.set_source_rgba(*G.shade(skin, 0.8), 0.55)
    ctx.fill()
    ctx.restore()
    geo = []
    for i, (a, ln, curl) in enumerate(HANDS[shape]):
        bx = inner * pw * 0.75 if i == 0 else (-pw * 0.62 + (i - 1) * pw * 0.41) * -inner
        by = palm_l * (0.45 if i == 0 else 0.95)
        ang = math.radians(a) * inner
        geo.append((bx, by, ang, L * 0.52 * ln * (1 - 0.55 * curl), curl))
    if shape == "fist":                                   # knuckles
        for i in range(1, 5):
            bx, by, ang, fl, _c = geo[i]
            ctx.new_path()
            ctx.arc(bx, by + fl * 0.55, pw * 0.16, 0.15 * math.pi, 0.85 * math.pi)
            ctx.set_source_rgb(*dark)
            ctx.set_line_width(lw * 0.5)
            ctx.stroke()
    else:
        for i in range(1, 4):                             # the gaps between the fingers
            b1, b2 = geo[i], geo[i + 1]
            if b1[4] > 0.8 and b2[4] > 0.8:
                continue
            mx, my = (b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2 - palm_l * 0.05
            ang = (b1[2] + b2[2]) / 2
            ln_ = min(b1[3], b2[3]) * 0.8
            G.line(ctx, [(mx, my), (mx - math.sin(ang) * ln_, my + math.cos(ang) * ln_)], lw * 0.5, dark, smooth_it=False)
        if shape in ("open", "flat", "point"):            # light nails on the fingertips
            for i, (bx, by, ang, fl, curl) in enumerate(geo):
                if curl > 0.5:
                    continue
                tx, ty = bx - math.sin(ang) * fl * 0.88, by + math.cos(ang) * fl * 0.88
                ctx.new_path()
                G.ellipse(ctx, tx, ty, pw * 0.09, pw * 0.11, ang=ang)
                ctx.set_source_rgba(1.0, 0.93, 0.88, 0.85)
                ctx.fill()
    bx, by, ang, fl, _c = geo[0]                          # the thumb's crease
    G.line(ctx, [(bx * 0.55, by + palm_l * 0.05), (bx * 0.85, by + palm_l * 0.35)], lw * 0.55, dark, smooth_it=False)


def arm_parts(spec, P, side):
    """one arm group: upper arm, forearm, hand (+ sleeves). side 'a' (screen-left) or 'b'"""
    cos = spec["costume"]
    sleeve = cos.get("sleeve", "short")            # none / short / half / full / puff
    scol = {"shirt_trousers": "shirt", "tshirt_shorts": "tshirt", "kurta_dhoti": "kurta", "saree": "blouse",
            "frock": "frock"}[cos["type"]]
    r = P["arm_r"]
    inner = 1 if side == "a" else -1
    lw = P["lw"]

    def ua_sil(ctx, C):
        ctx.new_path()
        G.capsule(ctx, P["uarm"], r * 1.12, r * 0.95)
        if sleeve == "puff":
            G.ellipse(ctx, 0, P["uarm"] * 0.12, r * 1.6, P["uarm"] * 0.25)

    def ua_paint(ctx, C):
        skin = C.col["skin"]
        if sleeve in ("none",):
            shadow_side(ctx, lambda c: G.capsule(c, P["uarm"], r * 1.12, r * 0.95), G.shade(skin, 0.86), inner * r * 0.45, 0)
            return
        cover = {"short": 0.55, "half": 0.92, "full": 1.2, "puff": 0.0}[sleeve]
        col = C.col[scol]
        if sleeve == "puff":
            ctx.new_path()
            G.capsule(ctx, P["uarm"], r * 1.12, r * 0.95)
            fill(ctx, skin, keep=False)
            ctx.new_path()
            G.ellipse(ctx, 0, P["uarm"] * 0.12, r * 1.6, P["uarm"] * 0.25)
            fill(ctx, col)
            stroke(ctx, LINE, lw * 0.8)
            return
        ctx.save()
        ctx.new_path()
        G.capsule(ctx, P["uarm"], r * 1.12, r * 0.95)
        ctx.clip()
        ctx.new_path()
        ctx.rectangle(-r * 3, -r * 3, r * 6, r * 3 + P["uarm"] * cover)
        fill(ctx, col, keep=False)
        ctx.new_path()
        ctx.rectangle(-r * 3 if inner > 0 else r * 0.45, -r * 3, r * 2.55, P["uarm"] + r * 4)
        ctx.set_source_rgba(0, 0, 0, 0.12)
        ctx.fill()
        ctx.restore()
        if cover < 1.0:
            G.line(ctx, [(-r * 1.15, P["uarm"] * cover), (0, P["uarm"] * cover + r * 0.15), (r * 1.15, P["uarm"] * cover)], lw * 0.9, LINE)

    def fa_sil(ctx, C):
        ctx.new_path()
        G.capsule(ctx, P["farm"], r * 0.95, r * 0.78)

    def fa_paint(ctx, C):
        skin = C.col["skin"]
        if sleeve == "full":
            ctx.save()
            ctx.new_path()
            G.capsule(ctx, P["farm"], r * 0.95, r * 0.78)
            ctx.clip()
            ctx.new_path()
            ctx.rectangle(-r * 3, -r * 3, r * 6, r * 3 + P["farm"] * 0.92)
            fill(ctx, C.col[scol], keep=False)
            ctx.restore()
            G.line(ctx, [(-r * 0.95, P["farm"] * 0.92), (r * 0.95, P["farm"] * 0.92)], lw * 0.9, LINE)
        else:
            shadow_side(ctx, lambda c: G.capsule(c, P["farm"], r * 0.95, r * 0.78), G.shade(skin, 0.86), inner * r * 0.4, 0)
        if "bangles" in spec.get("accessories", []):
            for k in (0, 1):
                y = P["farm"] * (0.8 + 0.08 * k)
                G.line(ctx, [(-r * 0.82, y), (0, y + r * 0.12), (r * 0.82, y)], lw * 1.4, G.rgb("#c8102e" if k else "#f2f2f2"))

    def h_sil(ctx, C):
        shp = C.st.get("hands", {}).get(side, "relax")
        hand_shape(ctx, P, shp, inner * C.st.get("hand_flip", {}).get(side, 1))

    def h_paint(ctx, C):
        shp = C.st.get("hands", {}).get(side, "relax")
        hand_detail(ctx, P, shp, inner * C.st.get("hand_flip", {}).get(side, 1), C.col["skin"], lw)
    return [Part("uarm_" + side, ua_sil, ua_paint), Part("farm_" + side, fa_sil, fa_paint), Part("hand_" + side, h_sil, h_paint)]


def leg_parts(spec, P, side):
    cos = spec["costume"]
    typ = cos["type"]
    r = P["leg_r"]
    lw = P["lw"]
    inner = 1 if side == "a" else -1
    hidden = typ == "saree"                        # legs under a saree: only the feet show
    gcol = {"shirt_trousers": "trousers", "tshirt_shorts": "shorts", "kurta_dhoti": "dhoti"}.get(typ)
    parts = []
    if not hidden:
        def th_sil(ctx, C):
            ctx.new_path()
            G.capsule(ctx, P["thigh"] * C.st.get("len", {}).get("thigh_" + side, 1.0), r * 1.1, r * 0.92)

        def th_paint(ctx, C):
            ln = P["thigh"] * C.st.get("len", {}).get("thigh_" + side, 1.0)
            if typ == "frock":
                return
            col = C.col[gcol] if gcol else C.col["skin"]
            ctx.save()
            ctx.new_path()
            G.capsule(ctx, ln, r * 1.1, r * 0.92)
            ctx.clip()
            if typ == "tshirt_shorts":
                ctx.new_path()
                ctx.rectangle(-r * 3, -r * 3, r * 6, r * 3 + ln * 0.62)
                fill(ctx, col, keep=False)
            else:
                ctx.new_path()
                ctx.rectangle(-r * 3, -r * 3, r * 6, ln + r * 6)
                fill(ctx, col, keep=False)
            ctx.new_path()
            ctx.rectangle(-r * 3 if inner < 0 else r * 0.4, -r * 3, r * 2.6, ln + r * 6)
            ctx.set_source_rgba(0, 0, 0, 0.10)
            ctx.fill()
            ctx.restore()
            if typ == "tshirt_shorts":
                G.line(ctx, [(-r * 1.1, ln * 0.62), (r * 1.1, ln * 0.62)], lw * 0.9, LINE)
        parts.append(Part("thigh_" + side, th_sil, th_paint))

        def sh_sil(ctx, C):
            ctx.new_path()
            wide = 1.25 if typ == "kurta_dhoti" else 1.0
            G.capsule(ctx, P["shin"], r * 0.92 * wide, r * 0.72 * (1.15 if typ == "shirt_trousers" else 1.0))

        def sh_paint(ctx, C):
            if gcol and typ != "tshirt_shorts":
                ctx.save()
                wide = 1.25 if typ == "kurta_dhoti" else 1.0
                ctx.new_path()
                G.capsule(ctx, P["shin"], r * 0.92 * wide, r * 0.72 * (1.15 if typ == "shirt_trousers" else 1.0))
                ctx.clip()
                cover = 0.97 if typ == "shirt_trousers" else 0.70
                ctx.new_path()
                ctx.rectangle(-r * 3, -r * 3, r * 6, r * 3 + P["shin"] * cover)
                fill(ctx, C.col[gcol], keep=False)
                ctx.new_path()
                ctx.rectangle(-r * 3 if inner < 0 else r * 0.35, -r * 3, r * 2.6, P["shin"] * 2)
                ctx.set_source_rgba(0, 0, 0, 0.10)
                ctx.fill()
                ctx.restore()
                G.line(ctx, [(-r * 1.15, P["shin"] * cover), (r * 1.15, P["shin"] * cover)], lw * 0.9, LINE)
                if typ == "kurta_dhoti":
                    G.line(ctx, [(r * 0.2, P["shin"] * 0.1), (-r * 0.3, P["shin"] * 0.6)], lw * 0.6, G.shade(C.col[gcol], 0.7))
        parts.append(Part("shin_" + side, sh_sil, sh_paint))

    def f_pts(C):
        fl = P["H"] * 0.075 * spec["body"].get("foot", 1.0)
        fh = P["foot_h"] * 1.4
        d = C.st.get("face_dir", 0.0)                 # walking direction: the foot turns into profile
        if abs(d) > 0.25:
            s = 1 if d > 0 else -1
            return [(-s * fl * 0.25, -fh * 0.4), (s * fl * 0.35, -fh * 0.2), (s * fl * 0.78, fh * 0.35), (s * fl * 0.75, fh * 0.75),
                    (-s * fl * 0.3, fh * 0.75), (-s * fl * 0.38, fh * 0.2)]
        w = fl * 0.42
        return [(-w * 0.55, -fh * 0.3), (w * 0.55, -fh * 0.3), (w * 0.62 - inner * w * 0.15, fh * 0.5),
                (w * 0.45 - inner * w * 0.2, fh * 0.8), (-w * 0.45 - inner * w * 0.2, fh * 0.8), (-w * 0.62 - inner * w * 0.15, fh * 0.5)]

    def f_sil(ctx, C):
        ctx.new_path()
        G.smooth(ctx, f_pts(C), tension=0.45)

    def f_paint(ctx, C):
        shoe = spec["body"].get("shoe", "sandal")
        pts = f_pts(C)
        if shoe == "sandal":
            ctx.save()
            ctx.new_path()
            G.smooth(ctx, pts, tension=0.45)
            ctx.clip()
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ctx.new_path()
            ctx.rectangle(min(xs) - 5, max(ys) - P["foot_h"] * 0.35, max(xs) - min(xs) + 10, P["foot_h"])
            fill(ctx, C.col.get("shoe", G.rgb("#5a3a22")), keep=False)
            ctx.new_path()
            ctx.rectangle(min(xs) - 5, (min(ys) + max(ys)) / 2 - P["foot_h"] * 0.12, max(xs) - min(xs) + 10, P["foot_h"] * 0.32)
            fill(ctx, C.col.get("shoe", G.rgb("#5a3a22")), keep=False)
            ctx.restore()
        elif shoe == "shoe":
            ctx.new_path()
            G.smooth(ctx, pts, tension=0.45)
            fill(ctx, C.col.get("shoe", G.rgb("#3a2a22")), keep=False)
    parts.append(Part("foot_" + side, f_sil, f_paint))
    return parts


# ----------------------------------------------------------------------------------------------- puppet

class Puppet:
    def __init__(self, spec):
        self.spec = spec
        self.P = proportions(spec)
        self.sk = R.Skeleton(self.P)
        self.head = head_part(spec, self.P)
        self.hair_back, self.hair_front = hair_parts(spec, self.P)
        self.neck, self.body = body_parts(spec, self.P)
        self.back_cloth = back_cloth(spec, self.P)
        self.arms = {s: arm_parts(spec, self.P, s) for s in ("a", "b")}
        self.legs = {s: leg_parts(spec, self.P, s) for s in ("a", "b")}

    def groups(self, st):
        turn = st.get("turn", 0.0)
        near = "a" if turn > 0.2 else "b" if turn < -0.2 else None
        far = None if near is None else ("b" if near == "a" else "a")
        over = st.get("arms_over_head", set())
        g = [("back_cloth", self.back_cloth), ("hair_back", self.hair_back)]
        front_arms = st.get("front_arms", set())
        if far and far not in front_arms:
            g.append(("arm_" + far, self.arms[far]))
            g += [("leg_" + far, self.legs[far]), ("leg_" + near, self.legs[near])]
        else:
            g += [("leg_a", self.legs["a"]), ("leg_b", self.legs["b"])]
        g.append(("body", [self.neck] + self.body))
        for s in (["a", "b"] if not far else [near] + ([far] if far in front_arms else [])):
            if s not in over:
                g.append(("arm_" + s, self.arms[s]))
        g.append(("head", [self.head]))
        g.append(("hair_front", self.hair_front))
        for s in over:
            g.append(("arm_" + s, self.arms[s]))
        return g

    def draw(self, ctx, st, x, y, scale=1.0, flip=1.0, only=None, solver=None):
        """draw the character with its feet at ground y=y. st = the pose/face state. Returns the world matrices."""
        P = self.P
        if st.get("side") and not only:                 # the TRUE SIDE VIEW (walk, ride, sit sideways, talk face to face)
            from tvtoon import profile as PR
            return PR.draw(self, ctx, st, x, y, scale)
        W = self.sk.solve(st, x, y - P["leg"] * scale, scale)
        if solver is not None:
            W = solver(self, st, W, x, y, scale)
        C = Ctx(self.spec, P, self.sk, W, st, ctx)
        lw = P["lw"]
        m0 = ctx.get_matrix()                           # the camera
        for name, parts in self.groups(st):
            if only and name not in only:
                continue
            for p in parts:                         # pass 1: the outline of the whole group
                if not p.outline:
                    continue
                ctx.save()
                ctx.set_matrix(W[p.bone].multiply(m0))
                p.sil(ctx, C)
                ctx.set_source_rgb(*LINE)
                ctx.set_line_width(lw * 2.0)
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                ctx.stroke()
                ctx.restore()
            for p in parts:                         # pass 2: fills and details
                ctx.save()
                ctx.set_matrix(W[p.bone].multiply(m0))
                p.sil(ctx, C)
                base = self._base(name, p)
                ctx.set_source_rgb(*C.col.get(base, G.rgb("#ff00ff")) if isinstance(base, str) else base)
                ctx.fill()
                if p.paint:
                    p.paint(ctx, C)
                ctx.restore()
        return W

    def _base(self, gname, p):
        typ = self.spec["costume"]["type"]
        if gname in ("hair_back", "hair_front"):
            return "hair"
        if gname == "back_cloth":
            return "saree"
        b = p.bone
        if b in ("head", "neck") or b.startswith("hand") or b.startswith("farm"):
            return "skin"
        if b.startswith("uarm"):
            return "skin"
        if b.startswith("foot"):
            return "skin"
        if b.startswith("thigh") or b.startswith("shin"):
            return {"shirt_trousers": "trousers", "kurta_dhoti": "skin", "tshirt_shorts": "skin"}.get(typ, "skin")
        if b == "root":
            return {"shirt_trousers": "trousers", "tshirt_shorts": "shorts", "kurta_dhoti": "dhoti", "saree": "saree",
                    "frock": "frock"}[typ]
        if b == "spine":
            return {"shirt_trousers": "shirt", "tshirt_shorts": "tshirt", "kurta_dhoti": "kurta", "saree": "blouse",
                    "frock": "frock"}[typ]
        return "skin"


def make(spec):
    """a puppet for any character: people (Puppet) or animals, birds and magic friends (animals.Animal)"""
    if spec.get("animal"):
        from tvtoon import animals as AM
        return AM.Animal(spec)
    return Puppet(spec)
