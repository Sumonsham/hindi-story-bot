"""ANIMALS, BIRDS AND MAGIC FRIENDS for the kids' cartoons (23 Nov 2026): Panchatantra, Jataka, animal stories,
Mithu the parrot, Bhola the puppy, Bhulu the dog, Robot Robi, Bhutu the little friendly ghost.

Every animal is a code-drawn puppet in the same flat TV-cartoon style as the people, with the same interface as
puppet.Puppet (spec, P, draw), so the scene engine, the animator, the camera and the lip-sync work for them unchanged:

  * a walk / trot cycle from the animator's walk phase (diagonal legs together, the body bobs, no sliding), birds hop
    or fly (wings flap), the robot rolls on wheels, Bhutu floats;
  * the mouth / beak opens with the visemes of the real voice; blinks, eye looks, brows for emotions;
  * breathing, a tail that wags on a spring, ears that twitch now and then;
  * side view facing the way they look (+x / -x), turning with the animator.

Species are a table of shapes (body, head, snout or beak, ears, tail, legs, markings), colours come from the
character's spec, and small things from its look (a cap, a scarf, a collar, glasses)."""
import math

import cairo

from tvtoon import geom as G
from tvtoon.puppet import LINE, VISEMES, proportions

D = math.radians

# species -> shape table (lengths in character units; H = height to the top of the head)
SPECIES = {
    #            H     body_l body_h leg   head  snout ears       tail      kind
    "monkey":   (560,  200,  170,  210,  95,  0.35, "round",   "curl",   "upright"),
    "rabbit":   (380,  200,  150,  70,   80,  0.25, "long",    "puff",   "hop"),
    "mouse":    (170,  120,  80,   30,   45,  0.5,  "round",   "thin",   "quad"),
    "cat":      (330,  250,  120,  110,  70,  0.3,  "pointed", "long",   "quad"),
    "dog":      (450,  300,  150,  150,  85,  0.6,  "flop",    "wag",    "quad"),
    "fox":      (420,  320,  130,  140,  80,  0.8,  "pointed", "bushy",  "quad"),
    "lion":     (880,  560,  260,  300,  150, 0.5,  "round",   "tuft",   "quad"),
    "tiger":    (840,  580,  250,  290,  140, 0.5,  "round",   "long",   "quad"),
    "bear":     (1000, 360,  330,  330,  150, 0.45, "round",   "puff",   "upright"),
    "deer":     (900,  420,  200,  420,  95,  0.7,  "pointed", "puff",   "quad"),
    "cow":      (950,  640,  330,  380,  150, 0.55, "horn",    "tuft",   "quad"),
    "goat":     (650,  420,  220,  250,  100, 0.6,  "horn",    "puff",   "quad"),
    "horse":    (1250, 700,  330,  560,  150, 0.9,  "pointed", "bushy",  "quad"),
    "elephant": (1450, 900,  600,  520,  330, 0.0,  "flap",    "thin",   "quad"),
    "crocodile": (300, 900,  170,  70,   110, 1.6,  "none",    "croc",   "low"),
    "tortoise": (260,  360,  190,  60,   70,  0.3,  "none",    "short",  "shell"),
    "frog":     (220,  200,  150,  60,   90,  0.1,  "none",    "none",   "frog"),
    "crow":     (260,  150,  110,  70,   65,  0.0,  "none",    "feather", "bird"),
    "parrot":   (270,  140,  120,  60,   70,  0.0,  "none",    "long_feather", "bird"),
    "sparrow":  (170,  110,  80,   45,   48,  0.0,  "none",    "feather", "bird"),
    "owl":      (340,  170,  220,  50,   110, 0.0,  "tuft_ear", "feather", "bird"),
    "peacock":  (720,  220,  160,  220,  60,  0.0,  "crest",   "fan",    "bird"),
    "robot":    (700,  300,  320,  90,   200, 0.0,  "antenna", "none",   "robot"),
    "bhutu":    (450,  260,  300,  0,    0,   0.0,  "none",    "wisp",   "ghost"),
}
DEFAULT_COLOURS = {
    "monkey": ("#8a5a32", "#e8c49a"), "rabbit": ("#f2f0ea", "#f6c6c8"), "mouse": ("#9a9a9a", "#f0c8c8"), "cat": ("#e89a3a", "#f6e2c8"),
    "dog": ("#c08a4a", "#f2e2c8"), "fox": ("#e0702a", "#f8f0e0"), "lion": ("#e0aa4a", "#f2d29a"), "tiger": ("#f08a2a", "#f8f0e0"),
    "bear": ("#6a4a2e", "#a8845e"), "deer": ("#b8783a", "#f2e2c8"), "cow": ("#f2f0ea", "#e8b8b0"), "goat": ("#e8e2d2", "#d8c8b0"),
    "horse": ("#8a5a32", "#5a3a22"), "elephant": ("#9a9aa4", "#c8a8b0"), "crocodile": ("#4a8a3a", "#c8d88a"),
    "tortoise": ("#7a8a3a", "#a8783a"), "frog": ("#5ab84a", "#d8f0a0"), "crow": ("#2a2a32", "#4a4a56"), "parrot": ("#3ab84a", "#e8d84a"),
    "sparrow": ("#a8783a", "#f0e0c8"), "owl": ("#8a6a4a", "#f0dcb8"), "peacock": ("#1a5ab8", "#2a9a6a"), "robot": ("#f2f4f8", "#7ac8f0"),
    "bhutu": ("#f8faff", "#ffd6e0")}


def _f(ctx, col, keep=True):
    ctx.set_source_rgb(*(G.rgb(col) if isinstance(col, str) else col))
    ctx.fill_preserve() if keep else ctx.fill()


def _s(ctx, w):
    ctx.set_source_rgb(*LINE)
    ctx.set_line_width(w)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def _shape(ctx, fn, col, lw):
    ctx.new_path()
    fn()
    _f(ctx, col)
    _s(ctx, lw * 2.0)


def _limb(ctx, a, b, r0, r1):
    ln = math.hypot(b[0] - a[0], b[1] - a[1])
    ctx.save()
    ctx.translate(*a)
    ctx.rotate(math.atan2(-(b[0] - a[0]), b[1] - a[1]))
    G.capsule(ctx, max(1e-3, ln), r0, r1)
    ctx.restore()


class Animal:
    """an animal / bird / magic friend with the puppet interface (spec, P, draw)"""

    def __init__(self, spec):
        self.spec = spec
        a = spec["animal"]
        self.sp = a["species"]
        H, bl, bh, leg, head, snout, ears, tail, kind = SPECIES[self.sp]
        k = float(a.get("size", 1.0))
        self.k = k
        self.dims = dict(H=H * k, bl=bl * k, bh=bh * k, leg=leg * k, head=head * k, snout=snout, ears=ears, tail=tail, kind=kind)
        tmpl = {"height": max(0.15, H * k / 1000.0), "heads": 3.0, "head": {"shape": "round", "w": 0.9},
                "body": {"shoulder": 0.6, "waist": 0.5, "hip": 0.6, "leg": 0.3 if kind != "upright" else 0.4, "arm": 0.35}}
        self.P = proportions(tmpl)
        self.P.update(H=H * k, head_h=max(head * k, 0.18 * H * k), head_w=head * k, lw=max(2.0, 4.2 * (H * k / 600) ** 0.5),
                      leg=max(leg * k, 0.12 * H * k))
        c0, c1 = DEFAULT_COLOURS[self.sp]
        self.col = {"body": G.rgb(spec.get("colours", {}).get("body", c0)), "belly": G.rgb(spec.get("colours", {}).get("belly", c1)),
                    "accent": G.rgb(spec.get("colours", {}).get("accent", "#3a2a1a"))}

    # ------------------------------------------------------------------ the frame
    def draw(self, ctx, st, x, y, scale=1.0, flip=1.0, only=None, solver=None):
        sd = st.get("side") or {}
        d = sd.get("d") if sd else (1.0 if st.get("turn", 0.0) >= 0 else -1.0)
        d = 1.0 if (d or 1.0) >= 0 else -1.0
        face = st.get("face", {})
        t = sd.get("t", st.get("t", 0.0)) or 0.0
        wk = st.get("walk") or (sd.get("walk") if sd else None)
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(scale * d, scale)
        lw = self.P["lw"]
        kind = self.dims["kind"]
        getattr(self, "_" + kind)(ctx, face, wk, t, lw, st)
        ctx.restore()
        return None

    # ------------------------------------------------------------------ face parts
    def _eye(self, ctx, x, y, r, face, lw, glow=False):
        lid = max(0.0, min(1.0, face.get("lid", 1.0)))
        if face.get("happy_closed") or lid < 0.15:
            G.line(ctx, [(x - r, y), (x, y + r * 0.4 if lid < 0.15 else y - r * 0.5), (x + r, y)], lw * 1.2, LINE)
            return
        ctx.new_path()
        G.ellipse(ctx, x, y, r, r * 1.1)
        _f(ctx, "#ffffff")
        _s(ctx, lw)
        lx, ly = face.get("look", (0.0, 0.0))
        ctx.new_path()
        G.ellipse(ctx, x + r * 0.35 * (0.5 + 0.5 * max(-1, min(1, lx))), y + ly * r * 0.3, r * 0.5, r * 0.6)
        _f(ctx, "#ffe680" if glow else "#1a120c", keep=False)
        ctx.new_path()
        ctx.arc(x + r * 0.5, y - r * 0.3, r * 0.18, 0, 2 * math.pi)
        _f(ctx, "#ffffff", keep=False)
        if lid < 0.99:
            ctx.new_path()
            ctx.rectangle(x - r * 1.2, y - r * 1.3, r * 2.4, r * 2.4 * (1 - lid) * 0.55)
            _f(ctx, self.col["body"], keep=False)
        b = face.get("brow", "normal")
        if b in ("angry", "sad", "surprised", "scared"):
            dy = {"angry": (0.25, -0.15), "sad": (-0.15, 0.2), "surprised": (-0.5, -0.5), "scared": (-0.3, -0.1)}[b]
            G.line(ctx, [(x - r * 0.9, y - r * 1.35 + dy[1] * r), (x + r * 0.9, y - r * 1.35 + dy[0] * r)], lw * 1.3, LINE)

    def _open(self, face):
        vis = face.get("mouth", "X")
        return VISEMES.get(vis, VISEMES["X"])[1] + face.get("jaw", 0.0) * 0.4

    def _accessories(self, ctx, hx, hy, hr, lw):
        acc = self.spec.get("accessories", [])
        if "cap" in acc:
            ctx.new_path()
            ctx.arc(hx, hy - hr * 0.55, hr * 0.7, math.pi, 2 * math.pi)
            ctx.close_path()
            _f(ctx, self.spec.get("colours", {}).get("cap", "#d32f2f"))
            _s(ctx, lw * 1.6)
            G.line(ctx, [(hx, hy - hr * 0.6), (hx + hr * 0.9, hy - hr * 0.55)], lw * 3, G.rgb(self.spec.get("colours", {}).get("cap", "#d32f2f")))
        if "glasses" in acc:
            for ex in (hx + hr * 0.15, hx + hr * 0.6):
                ctx.new_path()
                ctx.arc(ex, hy - hr * 0.15, hr * 0.22, 0, 2 * math.pi)
                _s(ctx, lw)
        if "scarf" in acc or "collar" in acc:
            c = self.spec.get("colours", {}).get("scarf", "#e91e63" if "scarf" in acc else "#1e5aa8")
            ctx.new_path()
            G.ellipse(ctx, hx - hr * 0.3, hy + hr * 0.85, hr * 0.7, hr * (0.22 if "scarf" in acc else 0.14))
            _f(ctx, c)
            _s(ctx, lw * 1.4)

    # ------------------------------------------------------------------ four legs
    def _legs4(self, ctx, wk, t, lw, bx0, bx1, by, leg, r, far):
        ph = wk["phase"] if wk else 0.0
        amp = D(28) if wk else D(0)
        pts = []
        for i, (lx, off) in enumerate(((bx1, 0.0), (bx0, 0.5), (bx1 - 20 * self.k, 0.5), (bx0 + 20 * self.k, 0.0))):
            a = amp * math.sin(2 * math.pi * (ph + off))
            lift = max(0.0, math.sin(2 * math.pi * (ph + off))) * leg * 0.18 if wk else 0.0
            knee = (lx + math.sin(a) * leg * 0.5, by + leg * 0.5 - lift * 0.5)
            foot = (lx + math.sin(a) * leg, -lift)
            pts.append((lx, knee, foot, i >= 2))
        for lx, knee, foot, is_far in sorted(pts, key=lambda p: not p[3]):
            if is_far != far:
                continue
            col = G.shade(self.col["body"], 0.8) if is_far else self.col["body"]
            _shape(ctx, lambda: (_limb(ctx, (lx, by), knee, r, r * 0.85), _limb(ctx, knee, foot, r * 0.85, r * 0.75)), col, lw)

    def _tail(self, ctx, x, y, lw, t, kind, wag):
        sw = math.sin(t * (8 if wag else 2.2)) * (0.6 if wag else 0.25)
        col = self.col["body"]
        if kind == "none":
            return
        if kind in ("puff", "short"):
            _shape(ctx, lambda: G.ellipse(ctx, x - 12 * self.k, y, 26 * self.k, 22 * self.k), self.col["belly"] if self.sp == "rabbit" else col, lw)
            return
        L = {"curl": 260, "thin": 160, "long": 220, "wag": 140, "bushy": 200, "tuft": 260, "croc": 0, "wisp": 120}.get(kind, 150) * self.k
        pts = [(x - L * u, y - L * 0.6 * u * (1 - u) * (2 if kind == "curl" else 1) + math.sin(u * 3 + t * 3) * L * 0.08 * sw * 3)
               for u in (0, 0.25, 0.5, 0.75, 1.0)]
        if kind == "curl":
            pts[-1] = (pts[-1][0] + L * 0.15, pts[-1][1] - L * 0.3)
        if kind == "bushy":
            _shape(ctx, lambda: G.smooth(ctx, [pts[0], (pts[2][0], pts[2][1] - 40 * self.k), (pts[4][0], pts[4][1] - 10 * self.k),
                                                (pts[3][0], pts[3][1] + 30 * self.k)], tension=0.4), col, lw)
            ctx.new_path()
            G.ellipse(ctx, pts[4][0] + 10 * self.k, pts[4][1] - 5 * self.k, 30 * self.k, 22 * self.k)
            _f(ctx, "#f8f0e0" if self.sp == "fox" else col)
            _s(ctx, lw * 1.5)
            return
        G.line(ctx, pts, max(lw * 2, 18 * self.k if kind != "thin" else 8 * self.k), LINE)
        G.line(ctx, pts, max(lw, (18 * self.k if kind != "thin" else 8 * self.k) - lw * 2), col)
        if kind == "tuft":
            _shape(ctx, lambda: G.ellipse(ctx, pts[-1][0], pts[-1][1], 26 * self.k, 18 * self.k), self.col["accent"] if self.sp == "lion" else G.shade(col, 0.6), lw)

    # ------------------------------------------------------------------ kinds
    def _quad(self, ctx, face, wk, t, lw, st):
        dm = self.dims
        bl, bh, leg = dm["bl"], dm["bh"], dm["leg"]
        bob = (math.sin(4 * math.pi * wk["phase"]) * bh * 0.04) if wk else bh * 0.015 * math.sin(t * 2.2)
        by = -leg - bh * 0.45 + bob
        r = max(10 * self.k, bh * (0.15 if self.sp not in ("elephant", "cow", "horse") else 0.16))
        self._legs4(ctx, wk, t, lw, -bl * 0.32, bl * 0.32, by + bh * 0.2, leg, r, far=True)
        self._tail(ctx, -bl * 0.48, by - bh * 0.1, lw, t, dm["tail"], self.sp == "dog")
        body = self.col["body"]
        _shape(ctx, lambda: G.ellipse(ctx, 0, by, bl * 0.52, bh * 0.5), body, lw)
        ctx.save()
        ctx.new_path()
        G.ellipse(ctx, 0, by, bl * 0.52, bh * 0.5)
        ctx.clip()
        ctx.new_path()
        G.ellipse(ctx, bl * 0.05, by + bh * 0.35, bl * 0.4, bh * 0.25)
        _f(ctx, self.col["belly"], keep=False)
        if self.sp == "tiger":                                    # stripes
            for i in range(7):
                xx = -bl * 0.4 + i * bl * 0.13
                G.line(ctx, [(xx, by - bh * 0.5), (xx + 12 * self.k, by - bh * 0.1), (xx - 6 * self.k, by + bh * 0.15)], 10 * self.k, (0.12, 0.08, 0.06))
        if self.sp in ("deer", "cow"):                            # spots / patches
            for i in range(5):
                ctx.new_path()
                G.ellipse(ctx, -bl * 0.35 + i * bl * 0.17, by - bh * 0.1 + (i % 2) * bh * 0.15, 18 * self.k + (30 * self.k if self.sp == "cow" else 0),
                          14 * self.k + (24 * self.k if self.sp == "cow" else 0))
                _f(ctx, "#f2e8d0" if self.sp == "deer" else "#3a2a22", keep=False)
        ctx.restore()
        self._legs4(ctx, wk, t, lw, -bl * 0.32, bl * 0.32, by + bh * 0.2, leg, r, far=False)
        # the head
        hr = dm["head"]
        nod = math.sin(t * 1.7) * hr * 0.03 + (math.sin(4 * math.pi * wk["phase"]) * hr * 0.05 if wk else 0.0)
        hx, hy = bl * 0.5 + hr * 0.35, by - bh * 0.45 - hr * 0.35 + nod
        if self.sp == "elephant":
            hx, hy = bl * 0.48, by - bh * 0.15
        if self.sp == "horse":
            hx, hy = bl * 0.62, by - bh * 0.95
            _shape(ctx, lambda: G.smooth(ctx, [(bl * 0.3, by - bh * 0.3), (bl * 0.45, by - bh * 0.9), (bl * 0.62, by - bh * 1.05),
                                                (bl * 0.7, by - bh * 0.7), (bl * 0.5, by - bh * 0.1)], tension=0.4), body, lw)
            G.line(ctx, [(bl * 0.35, by - bh * 0.4), (bl * 0.5, by - bh * 0.95), (bl * 0.6, by - bh * 1.1)], 22 * self.k, self.col["accent"])
        if self.sp == "deer":
            G.line(ctx, [(bl * 0.4, by - bh * 0.2), (hx - hr * 0.2, hy + hr * 0.3)], hr * 0.7, LINE)
            G.line(ctx, [(bl * 0.4, by - bh * 0.2), (hx - hr * 0.2, hy + hr * 0.3)], hr * 0.7 - lw * 2, body)
        self._head(ctx, hx, hy, hr, face, lw, t)

    def _head(self, ctx, hx, hy, hr, face, lw, t):
        dm = self.dims
        body = self.col["body"]
        ears = dm["ears"]
        tw = math.sin(t * 0.9) > 0.97                            # an ear twitch now and then
        if ears == "flap":                                       # the elephant's big ear
            _shape(ctx, lambda: G.ellipse(ctx, hx - hr * 0.55, hy - hr * 0.05, hr * 0.6, hr * 0.8, ang=0.2 * math.sin(t * 1.5)),
                   G.shade(body, 0.92), lw)
        if self.sp == "lion":                                    # the mane
            ctx.new_path()
            for i in range(14):
                a = i / 14 * 2 * math.pi
                G.ellipse(ctx, hx - hr * 0.1 + math.cos(a) * hr * 0.95, hy + math.sin(a) * hr * 0.95, hr * 0.4, hr * 0.4)
            _f(ctx, self.col["accent"] if self.spec.get("colours", {}).get("accent") else "#a8641e")
            _s(ctx, lw)
        if ears in ("pointed", "round", "long", "flop", "horn"):
            for k, s_ in ((1, 0.8), (0, 1.0)):
                ex = hx - hr * (0.35 - 0.3 * k)
                col = G.shade(body, s_)
                if ears == "pointed":
                    _shape(ctx, lambda: (ctx.move_to(ex - hr * 0.25, hy - hr * 0.6), ctx.line_to(ex + (0.05 if tw else 0) * hr, hy - hr * 1.35),
                                         ctx.line_to(ex + hr * 0.25, hy - hr * 0.7), ctx.close_path()), col, lw)
                elif ears == "round":
                    _shape(ctx, lambda: G.ellipse(ctx, ex, hy - hr * 0.8, hr * 0.3, hr * 0.3), col, lw)
                elif ears == "long":
                    _shape(ctx, lambda: G.ellipse(ctx, ex - hr * 0.1, hy - hr * 1.3, hr * 0.22, hr * 0.75, ang=-0.15 - (0.2 if tw else 0) - 0.15 * k),
                           col, lw)
                elif ears == "flop":
                    _shape(ctx, lambda: G.ellipse(ctx, ex - hr * 0.35, hy - hr * 0.2, hr * 0.22, hr * 0.5, ang=0.4), G.shade(col, 0.75), lw)
                elif ears == "horn":
                    G.line(ctx, [(ex, hy - hr * 0.7), (ex - hr * 0.25, hy - hr * 1.2), (ex - hr * 0.1, hy - hr * 1.45)], hr * 0.16, (0.85, 0.8, 0.65))
        # the skull
        _shape(ctx, lambda: G.ellipse(ctx, hx, hy, hr, hr * 0.92), body, lw)
        op = self._open(face)
        sn = dm["snout"]
        if self.sp == "elephant":                                # the trunk swings and curls
            sw = math.sin(t * 1.4) * hr * 0.15
            pts = [(hx + hr * 0.6, hy + hr * 0.1), (hx + hr * 1.0, hy + hr * 0.6), (hx + hr * 0.95 + sw, hy + hr * 1.3),
                   (hx + hr * 1.15 + sw, hy + hr * 1.6)]
            G.line(ctx, pts, hr * 0.42 + lw * 2, LINE)
            G.line(ctx, pts, hr * 0.42, body)
            G.line(ctx, [(hx + hr * 0.55, hy + hr * 0.45), (hx + hr * 0.9, hy + hr * 0.75)], hr * 0.1, (0.96, 0.94, 0.88))
            mx, my = hx + hr * 0.45, hy + hr * 0.55
            if op > 0.1:
                ctx.new_path()
                G.ellipse(ctx, mx, my, hr * 0.12, hr * 0.12 * (0.4 + op))
                _f(ctx, "#5a1a1a", keep=False)
        elif sn > 0:                                             # the snout, with a mouth that opens
            sl = hr * (0.4 + sn * 0.5)
            jaw = op * hr * 0.35
            if self.sp == "crocodile":
                jaw = op * hr * 0.6
            ctx.new_path()
            ctx.move_to(hx + hr * 0.4, hy + hr * 0.15)
            ctx.line_to(hx + hr * 0.4 + sl, hy + hr * 0.28 + jaw * 0.3)
            ctx.line_to(hx + hr * 0.4 + sl * 0.92, hy + hr * 0.42 + jaw)
            ctx.line_to(hx + hr * 0.3, hy + hr * 0.5 + jaw * 0.5)
            ctx.close_path()
            _f(ctx, "#6a1a20")
            _s(ctx, lw)
            _shape(ctx, lambda: G.smooth(ctx, [(hx + hr * 0.2, hy - hr * 0.25), (hx + hr * 0.4 + sl, hy - hr * 0.05), (hx + hr * 0.42 + sl, hy + hr * 0.25),
                                                (hx + hr * 0.3, hy + hr * 0.3)], tension=0.35), self.col["belly"] if self.sp in ("monkey", "bear", "dog", "lion", "tiger", "cat") else body, lw)
            _shape(ctx, lambda: G.smooth(ctx, [(hx + hr * 0.3, hy + hr * 0.42 + jaw * 0.5), (hx + hr * 0.4 + sl * 0.92, hy + hr * 0.42 + jaw),
                                                (hx + hr * 0.4 + sl * 0.85, hy + hr * 0.56 + jaw), (hx + hr * 0.2, hy + hr * 0.6 + jaw * 0.4)],
                                       tension=0.35), self.col["belly"] if self.sp != "crocodile" else body, lw)
            if self.sp == "crocodile":
                for i in range(6):
                    tx = hx + hr * 0.5 + i * sl * 0.13
                    G.line(ctx, [(tx, hy + hr * 0.27), (tx + 6 * self.k, hy + hr * 0.37)], lw * 1.4, (0.98, 0.98, 0.95), smooth_it=False)
            ctx.new_path()                                       # the nose
            G.ellipse(ctx, hx + hr * 0.4 + sl, hy - hr * 0.02, hr * 0.12, hr * 0.09)
            _f(ctx, "#2a1a14", keep=False)
        eye_y = hy - hr * 0.2
        self._eye(ctx, hx + hr * 0.35, eye_y, hr * (0.22 if self.sp not in ("elephant",) else 0.13), face, lw)
        if face.get("cheek", 0) > 0.3 or face.get("smile", 0) > 0.5:
            ctx.new_path()
            G.ellipse(ctx, hx + hr * 0.25, hy + hr * 0.25, hr * 0.15, hr * 0.08)
            ctx.set_source_rgba(1.0, 0.5, 0.55, 0.5)
            ctx.fill()
        self._accessories(ctx, hx, hy, hr, lw)

    def _upright(self, ctx, face, wk, t, lw, st):
        """monkey / bear: a cartoon animal standing on two legs, with arms (gestures follow the talk)"""
        dm = self.dims
        bh, leg, hr = dm["bh"], dm["leg"], dm["head"]
        ph = wk["phase"] if wk else 0.0
        bob = (math.cos(4 * math.pi * ph) * bh * 0.04) if wk else bh * 0.012 * math.sin(t * 2.0)
        leg = leg * 0.7                                        # (cartoon animals on two legs: short legs)
        hip = (0.0, -leg + bob)
        body, belly = self.col["body"], self.col["belly"]
        r = bh * 0.17
        sw = D(25) * math.sin(2 * math.pi * ph) if wk else 0.0
        for k, s_ in ((1, 0.8), (0, 1.0)):                      # legs: far first
            a = sw * (1 if k else -1)
            foot = (hip[0] + math.sin(a) * leg + 10 * self.k, 0.0 - (max(0, math.sin(2 * math.pi * ph + k * math.pi)) * leg * 0.15 if wk else 0))
            _shape(ctx, lambda: _limb(ctx, hip, foot, r, r * 0.9), G.shade(body, s_), lw)
            _shape(ctx, lambda: G.ellipse(ctx, foot[0] + r * 0.6, foot[1] - r * 0.3, r * 1.0, r * 0.5), G.shade(belly, s_), lw)
        self._tail(ctx, -bh * 0.35, hip[1] - bh * 0.1, lw, t, dm["tail"], False)
        top = (hip[0] + bh * 0.05, hip[1] - bh)
        talk = self._open(face) > 0.05
        gest = math.sin(t * 4) * D(25) if talk else 0.0
        far_arm = (top[0] - bh * 0.1, top[1] + bh * 0.25)
        _shape(ctx, lambda: _limb(ctx, far_arm, (far_arm[0] + bh * 0.25, far_arm[1] + bh * 0.55), r * 0.8, r * 0.7), G.shade(body, 0.8), lw)
        _shape(ctx, lambda: G.ellipse(ctx, hip[0], hip[1] - bh * 0.5, bh * 0.42, bh * 0.55), body, lw)
        _shape(ctx, lambda: G.ellipse(ctx, hip[0] + bh * 0.12, hip[1] - bh * 0.45, bh * 0.25, bh * 0.38), belly, lw * 0.6)
        near = (top[0] + bh * 0.05, top[1] + bh * 0.25)
        a = D(30) + gest
        hand = (near[0] + math.sin(a) * bh * 0.6, near[1] + math.cos(a) * bh * 0.6)
        self._head(ctx, top[0] + hr * 0.25, top[1] - hr * 0.55, hr, face, lw, t)
        _shape(ctx, lambda: (_limb(ctx, near, hand, r * 0.8, r * 0.7), G.ellipse(ctx, hand[0], hand[1], r * 0.75, r * 0.7)), body, lw)

    def _hop(self, ctx, face, wk, t, lw, st):
        """rabbit: sits upright, hops when it moves"""
        dm = self.dims
        bh, bl, hr = dm["bh"], dm["bl"], dm["head"]
        ph = wk["phase"] if wk else 0.0
        jump = abs(math.sin(math.pi * 2 * ph)) * bh * 0.6 if wk else 0.0
        body, belly = self.col["body"], self.col["belly"]
        ctx.save()
        ctx.translate(0, -jump)
        self._tail(ctx, -bl * 0.4, -bh * 0.3, lw, t, "puff", False)
        _shape(ctx, lambda: G.ellipse(ctx, -bl * 0.25, -bh * 0.3, bl * 0.25, bh * 0.28), G.shade(body, 0.95), lw)   # haunch
        _shape(ctx, lambda: G.ellipse(ctx, 0, -bh * 0.55, bl * 0.32, bh * 0.5), body, lw)
        _shape(ctx, lambda: G.ellipse(ctx, bl * 0.08, -bh * 0.45, bl * 0.18, bh * 0.32), belly, lw * 0.6)
        _shape(ctx, lambda: G.ellipse(ctx, bl * 0.1, -bh * 0.05, bl * 0.2, bh * 0.07), body, lw)               # front paws
        _shape(ctx, lambda: G.ellipse(ctx, -bl * 0.25, -bh * 0.02, bl * 0.25, bh * 0.07), body, lw)            # back foot
        self._head(ctx, bl * 0.15, -bh * 1.05, hr, face, lw, t)
        ctx.restore()

    def _low(self, ctx, face, wk, t, lw, st):
        """crocodile: long and low, a swinging tail, the long jaw opens wide"""
        dm = self.dims
        bl, bh, hr = dm["bl"], dm["bh"], dm["head"]
        ph = wk["phase"] if wk else 0.0
        body = self.col["body"]
        sw = math.sin(t * 1.5 + ph * 6) * bh * 0.3
        tail = [(-bl * 0.35, -bh * 0.5), (-bl * 0.6, -bh * 0.4 + sw * 0.3), (-bl * 0.8, -bh * 0.3 + sw), (-bl * 0.95, -bh * 0.25 + sw * 1.4)]
        G.line(ctx, tail, bh * 0.45 + lw * 2, LINE)
        G.line(ctx, tail, bh * 0.45, body)
        for lx, off in ((bl * 0.25, 0), (-bl * 0.25, 0.5)):
            a = D(30) * math.sin(2 * math.pi * (ph + off)) if wk else 0
            _shape(ctx, lambda: _limb(ctx, (lx, -bh * 0.45), (lx + math.sin(a) * 60 * self.k, 0), 20 * self.k, 18 * self.k), G.shade(body, 0.85), lw)
        _shape(ctx, lambda: G.ellipse(ctx, 0, -bh * 0.55, bl * 0.42, bh * 0.45), body, lw)
        for i in range(7):                                       # scutes on the back
            ctx.new_path()
            G.ellipse(ctx, -bl * 0.35 + i * bl * 0.11, -bh * 0.98, 16 * self.k, 10 * self.k)
            _f(ctx, G.shade(body, 0.7), keep=False)
        self._head(ctx, bl * 0.42, -bh * 0.75, hr, face, lw, t)

    def _shell(self, ctx, face, wk, t, lw, st):
        """tortoise: a dome shell with a pattern, small legs, a head that peeks out slowly"""
        dm = self.dims
        bl, bh, hr = dm["bl"], dm["bh"], dm["head"]
        ph = wk["phase"] if wk else 0.0
        for lx, off in ((bl * 0.28, 0), (-bl * 0.28, 0.5)):
            a = D(20) * math.sin(2 * math.pi * (ph + off)) if wk else 0
            _shape(ctx, lambda: _limb(ctx, (lx, -bh * 0.3), (lx + math.sin(a) * 30 * self.k, 0), 22 * self.k, 20 * self.k), self.col["body"], lw)
        out = 0.85 + 0.15 * math.sin(t * 0.7)
        self._head(ctx, bl * 0.42 * out + hr * 0.3, -bh * 0.45, hr, face, lw, t)
        _shape(ctx, lambda: (ctx.move_to(-bl * 0.5, -bh * 0.25), ctx.curve_to(-bl * 0.45, -bh * 1.2, bl * 0.45, -bh * 1.2, bl * 0.5, -bh * 0.25),
                             ctx.close_path()), self.col["belly"], lw)
        for i in range(3):
            ctx.new_path()
            G.ellipse(ctx, -bl * 0.25 + i * bl * 0.25, -bh * 0.6, bl * 0.1, bh * 0.16)
            _f(ctx, G.shade(self.col["belly"], 0.7), keep=False)

    def _frog(self, ctx, face, wk, t, lw, st):
        dm = self.dims
        bl, bh, hr = dm["bl"], dm["bh"], dm["head"]
        jump = abs(math.sin(math.pi * 2 * (wk["phase"] if wk else 0))) * bh * 0.8 if wk else 0.0
        ctx.save()
        ctx.translate(0, -jump)
        body = self.col["body"]
        _shape(ctx, lambda: G.ellipse(ctx, -bl * 0.2, -bh * 0.15, bl * 0.35, bh * 0.15), G.shade(body, 0.85), lw)
        _shape(ctx, lambda: G.ellipse(ctx, 0, -bh * 0.45, bl * 0.4, bh * 0.42), body, lw)
        _shape(ctx, lambda: G.ellipse(ctx, bl * 0.1, -bh * 0.35, bl * 0.28, bh * 0.25), self.col["belly"], lw * 0.6)
        throat = 1 + 0.15 * math.sin(t * 6) + self._open(face) * 0.3
        _shape(ctx, lambda: G.ellipse(ctx, bl * 0.25, -bh * 0.38, bl * 0.14 * throat, bh * 0.12 * throat), self.col["belly"], lw)
        for ex in (bl * 0.05, bl * 0.28):
            _shape(ctx, lambda: G.ellipse(ctx, ex, -bh * 0.85, hr * 0.32, hr * 0.32), body, lw)
            self._eye(ctx, ex + hr * 0.05, -bh * 0.86, hr * 0.2, face, lw)
        op = self._open(face)
        G.line(ctx, [(bl * 0.0, -bh * 0.6), (bl * 0.2, -bh * (0.58 - op * 0.08)), (bl * 0.38, -bh * 0.62)], lw * 1.3, LINE)
        ctx.restore()

    def _bird(self, ctx, face, wk, t, lw, st):
        """crow / parrot / sparrow / owl / peacock: hop on the ground or fly (when the walk is fast), wings flap,
        the beak opens with the voice"""
        dm = self.dims
        bl, bh, leg, hr = dm["bl"], dm["bh"], dm["leg"], dm["head"]
        ph = wk["phase"] if wk else 0.0
        flying = bool(wk) and self.sp not in ("peacock",)
        lift = (bh * 1.6 + math.sin(t * 3) * bh * 0.2) if flying else (abs(math.sin(2 * math.pi * ph)) * bh * 0.3 if wk else 0.0)
        body, belly = self.col["body"], self.col["belly"]
        ctx.save()
        ctx.translate(0, -lift)
        if self.sp == "peacock":                                 # the fan of the tail, it opens and shimmers
            fan = 0.7 + 0.3 * math.sin(t * 0.6)
            for i in range(11):
                a = math.pi * (0.55 + 0.9 * i / 10) * 0.5 + math.pi * 0.3
                ex, ey = -bl * 0.2 - math.cos(a) * bh * 3.2 * fan, -leg - bh * 0.5 - math.sin(a) * bh * 3.0 * fan
                G.line(ctx, [(-bl * 0.2, -leg - bh * 0.5), (ex, ey)], 8 * self.k, G.rgb("#2a7a4a"))
                ctx.new_path()
                G.ellipse(ctx, ex, ey, 26 * self.k, 32 * self.k)
                _f(ctx, "#2a9a6a")
                _s(ctx, lw)
                ctx.new_path()
                G.ellipse(ctx, ex, ey, 10 * self.k, 13 * self.k)
                _f(ctx, "#1a3a9a", keep=False)
        if not flying:
            for k in (0, 1):
                fx = (bl * 0.05 if k else -bl * 0.1) + (math.sin(2 * math.pi * ph + k * math.pi) * leg * 0.3 if wk else 0)
                G.line(ctx, [(fx, -leg), (fx, 0), (fx + leg * 0.35, 0)], 4 * self.k + lw, (0.85, 0.6, 0.2) if self.sp != "crow" else (0.25, 0.25, 0.25))
        tl = {"long_feather": 1.6, "feather": 0.8, "fan": 0.0}.get(dm["tail"], 0.8)
        if tl:
            _shape(ctx, lambda: (ctx.move_to(-bl * 0.35, -leg - bh * 0.4), ctx.line_to(-bl * (0.35 + tl * 0.6), -leg - bh * (0.1 - 0.2 * tl)),
                                 ctx.line_to(-bl * (0.3 + tl * 0.6), -leg - bh * (0.05 - 0.2 * tl)), ctx.line_to(-bl * 0.25, -leg - bh * 0.2),
                                 ctx.close_path()), G.shade(body, 0.8) if self.sp != "parrot" else G.rgb("#1a7ab8"), lw)
        _shape(ctx, lambda: G.ellipse(ctx, 0, -leg - bh * 0.5, bl * 0.48, bh * 0.5, ang=-0.25), body, lw)
        _shape(ctx, lambda: G.ellipse(ctx, bl * 0.12, -leg - bh * 0.4, bl * 0.28, bh * 0.33, ang=-0.25), belly, lw * 0.6)
        flap = math.sin(t * (18 if flying else 3)) * (D(55) if flying else D(4))
        ctx.save()                                               # the wing
        ctx.translate(-bl * 0.05, -leg - bh * 0.62)
        ctx.rotate(-flap - D(10))
        _shape(ctx, lambda: G.smooth(ctx, [(0, 0), (-bl * 0.55, -bh * 0.05), (-bl * 0.7, bh * 0.15), (-bl * 0.2, bh * 0.3)], tension=0.4),
               G.shade(body, 0.85) if self.sp != "parrot" else G.rgb("#2a9a3a"), lw)
        ctx.restore()
        hx, hy = bl * 0.38, -leg - bh * 0.95 - hr * 0.25
        if self.sp == "owl":
            hx, hy = bl * 0.05, -leg - bh * 0.95
        if self.sp == "peacock":                                 # the long neck
            G.line(ctx, [(bl * 0.25, -leg - bh * 0.7), (bl * 0.35, -leg - bh * 1.4), (bl * 0.38, -leg - bh * 1.9)], 34 * self.k + lw * 2, LINE)
            G.line(ctx, [(bl * 0.25, -leg - bh * 0.7), (bl * 0.35, -leg - bh * 1.4), (bl * 0.38, -leg - bh * 1.9)], 34 * self.k, body)
            hx, hy = bl * 0.4, -leg - bh * 2.0
            for i in range(3):
                G.line(ctx, [(hx, hy - hr * 0.8), (hx - hr * 0.3 + i * hr * 0.3, hy - hr * 1.6)], 3 * self.k, G.rgb("#1a3a9a"))
        _shape(ctx, lambda: G.ellipse(ctx, hx, hy, hr, hr), body, lw)
        if self.sp == "parrot":
            ctx.new_path()
            G.ellipse(ctx, hx + hr * 0.1, hy + hr * 0.3, hr * 0.7, hr * 0.5)
            _f(ctx, "#e8d84a", keep=False)
        op = self._open(face)
        beak_c = "#e84a2a" if self.sp == "parrot" else ("#f0a830" if self.sp != "crow" else "#3a3a3a")
        bk = hr * (0.8 if self.sp == "parrot" else 0.6)
        _shape(ctx, lambda: (ctx.move_to(hx + hr * 0.75, hy - hr * 0.25), ctx.curve_to(hx + hr * 0.95 + bk, hy - hr * 0.3,
                                                                                          hx + hr * 0.85 + bk, hy + hr * 0.15,
                                                                                          hx + hr * 0.75 + bk * 0.8, hy + hr * (0.15 if self.sp == "parrot" else 0.0)),
                             ctx.line_to(hx + hr * 0.8, hy), ctx.close_path()), beak_c, lw)
        _shape(ctx, lambda: (ctx.move_to(hx + hr * 0.8, hy + hr * 0.05), ctx.line_to(hx + hr * 0.75 + bk * 0.7, hy + hr * (0.1 + op * 0.5)),
                             ctx.line_to(hx + hr * 0.75, hy + hr * 0.3), ctx.close_path()), G.shade(beak_c, 0.8), lw)
        if self.sp == "owl":
            for ex in (hx - hr * 0.35, hx + hr * 0.35):
                self._eye(ctx, ex, hy - hr * 0.1, hr * 0.33, face, lw)
            for s_ in (-1, 1):
                _shape(ctx, lambda: (ctx.move_to(hx + s_ * hr * 0.4, hy - hr * 0.75), ctx.line_to(hx + s_ * hr * 0.75, hy - hr * 1.35),
                                     ctx.line_to(hx + s_ * hr * 0.85, hy - hr * 0.6), ctx.close_path()), body, lw)
        else:
            self._eye(ctx, hx + hr * 0.3, hy - hr * 0.2, hr * 0.28, face, lw)
        self._accessories(ctx, hx, hy, hr, lw)
        ctx.restore()

    def _robot(self, ctx, face, wk, t, lw, st):
        """Robot Robi: a round body on wheels, a screen face with LED eyes and a mouth bar, an antenna light"""
        dm = self.dims
        bh, bl, hr, leg = dm["bh"], dm["bl"], dm["head"], dm["leg"]
        roll = (wk["phase"] * 2 * math.pi * 2) if wk else 0.0
        for wx in (-bl * 0.28, bl * 0.28):
            ctx.new_path()
            ctx.arc(wx, -leg * 0.5, leg * 0.5, 0, 2 * math.pi)
            _f(ctx, "#3a3a44")
            _s(ctx, lw * 1.5)
            G.line(ctx, [(wx, -leg * 0.5), (wx + math.cos(roll) * leg * 0.4, -leg * 0.5 + math.sin(roll) * leg * 0.4)], lw * 2, (0.8, 0.8, 0.85))
        bob = math.sin(t * 3) * 4 * self.k
        _shape(ctx, lambda: self._rr(ctx, -bl * 0.5, -leg - bh + bob, bl, bh, 40 * self.k), self.col["body"], lw)
        self._rr(ctx, -bl * 0.3, -leg - bh * 0.7 + bob, bl * 0.6, bh * 0.3, 16 * self.k)
        _f(ctx, self.col["belly"])
        _s(ctx, lw)
        hy = -leg - bh - hr * 0.55 + bob
        _shape(ctx, lambda: self._rr(ctx, -hr * 0.75, hy - hr * 0.5, hr * 1.5, hr, 30 * self.k), self.col["body"], lw)
        _shape(ctx, lambda: self._rr(ctx, -hr * 0.6, hy - hr * 0.38, hr * 1.25, hr * 0.76, 22 * self.k), "#1a2a3a", lw)
        lid = max(0.15, face.get("lid", 1.0))
        for ex in (-hr * 0.15, hr * 0.35):
            ctx.new_path()
            G.ellipse(ctx, ex, hy - hr * 0.08, hr * 0.13, hr * 0.17 * lid)
            _f(ctx, "#5ad0ff", keep=False)
        op = self._open(face)
        ctx.new_path()
        ctx.rectangle(-hr * 0.05, hy + hr * 0.16, hr * 0.4, hr * (0.04 + 0.16 * op))
        _f(ctx, "#5ad0ff", keep=False)
        G.line(ctx, [(0, hy - hr * 0.5), (hr * 0.1, hy - hr * 0.95)], lw * 1.5, LINE)
        ctx.new_path()
        ctx.arc(hr * 0.1, hy - hr * 0.98, hr * 0.09, 0, 2 * math.pi)
        _f(ctx, (1.0, 0.2, 0.2) if int(t * 2) % 2 else (0.5, 0.1, 0.1), keep=False)

    @staticmethod
    def _rr(ctx, x, y, w, h, r):
        ctx.new_path()
        ctx.move_to(x + r, y)
        ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        ctx.close_path()

    def _ghost(self, ctx, face, wk, t, lw, st):
        """Bhutu: a tiny round friendly ghost, never scary - floats, bobs, a little wisp of a tail, rosy cheeks"""
        dm = self.dims
        bh, bl = dm["bh"], dm["bl"]
        fy = -bh * 0.35 - math.sin(t * 2.2) * bh * 0.08
        sw = math.sin(t * 2.0) * bl * 0.1
        body = self.col["body"]
        ctx.new_path()
        ctx.move_to(-bl * 0.45, fy - bh * 0.5)
        ctx.curve_to(-bl * 0.45, fy - bh * 1.3, bl * 0.45, fy - bh * 1.3, bl * 0.45, fy - bh * 0.5)
        ctx.curve_to(bl * 0.45, fy - bh * 0.1, bl * 0.1 + sw, fy, -bl * 0.25 + sw * 2, fy + bh * 0.15)
        ctx.curve_to(-bl * 0.2, fy - bh * 0.1, -bl * 0.45, fy - bh * 0.2, -bl * 0.45, fy - bh * 0.5)
        ctx.close_path()
        ctx.save()
        g = cairo.RadialGradient(0, fy - bh * 0.6, 10, 0, fy - bh * 0.6, bh)
        g.add_color_stop_rgba(0, 1, 1, 1, 0.5)
        g.add_color_stop_rgba(1, 0.85, 0.92, 1, 0.0)
        ctx.set_source(g)
        ctx.fill_preserve()
        ctx.restore()
        _f(ctx, body)
        _s(ctx, lw * 1.6)
        for ex in (bl * 0.0, bl * 0.25):
            self._eye(ctx, ex, fy - bh * 0.72, bl * 0.08, face, lw)
        op = self._open(face)
        ctx.new_path()
        ctx.arc(bl * 0.15, fy - bh * 0.52, bl * (0.06 + 0.05 * op), 0, math.pi)
        _f(ctx, "#6a1a20")
        _s(ctx, lw)
        for cx in (-bl * 0.05, bl * 0.33):
            ctx.new_path()
            G.ellipse(ctx, cx, fy - bh * 0.58, bl * 0.05, bl * 0.03)
            _f(ctx, self.col["belly"], keep=False)
        ctx.new_path()                                           # the orange scarf, round its "neck"
        G.ellipse(ctx, bl * 0.02, fy - bh * 0.3, bl * 0.4, bh * 0.045)
        _f(ctx, self.spec.get("colours", {}).get("scarf", "#ff8a2a"))
        _s(ctx, lw)


def is_animal(spec):
    return isinstance(spec, dict) and bool(spec.get("animal"))


SPECIES_WORDS = [  # words in a name / look -> species (English, Bengali, Hindi)
    ("monkey", ["monkey", "বাঁদর", "বানর", "हनुमान-", "बंदर", "वानर"]), ("rabbit", ["rabbit", "hare", "খরগোশ", "খরগোস", "खरगोश"]),
    ("mouse", ["mouse", "rat", "ইঁদুর", "चूहा", "चुहिया"]), ("cat", ["cat", "kitten", "বিড়াল", "বেড়াল", "बिल्ली"]),
    ("dog", ["dog", "puppy", "কুকুর", "कुत्ता", "पिल्ला"]), ("fox", ["fox", "jackal", "শেয়াল", "শিয়াল", "लोमड़ी", "सियार", "गीदड़"]),
    ("lion", ["lion", "সিংহ", "शेर", "सिंह"]), ("tiger", ["tiger", "বাঘ", "बाघ"]), ("bear", ["bear", "ভালুক", "भालू"]),
    ("deer", ["deer", "হরিণ", "हिरण", "हिरन"]), ("cow", ["cow", "bull", "ox", "গরু", "ষাঁড়", "गाय", "बैल"]),
    ("goat", ["goat", "ছাগল", "बकरी", "बकरा"]), ("horse", ["horse", "ঘোড়া", "घोड़ा"]), ("elephant", ["elephant", "হাতি", "हाथी"]),
    ("crocodile", ["crocodile", "কুমির", "मगरमच्छ", "मगर"]), ("tortoise", ["tortoise", "turtle", "কচ্ছপ", "কাছিম", "कछुआ"]),
    ("frog", ["frog", "ব্যাঙ", "मेंढक"]), ("crow", ["crow", "কাক", "कौआ", "कौवा"]), ("parrot", ["parrot", "টিয়া", "তোতা", "तोता", "मिट्ठू"]),
    ("sparrow", ["sparrow", "চড়ুই", "गौरैया", "चिड़िया"]), ("owl", ["owl", "পেঁচা", "उल्लू"]), ("peacock", ["peacock", "ময়ূর", "मोर"]),
    ("robot", ["robot", "রোবট", "रोबोट"]), ("bhutu", ["bhutu", "ভুতু", "भूतू", "friendly ghost"])]


def species_of(text):
    t = str(text or "").lower()
    for sp, words in SPECIES_WORDS:
        if any(w in t for w in words):
            return sp
    return None


def make_spec(name_bn, species, look="", gender="male", age="adult"):
    """an animal character's spec from its species and look (colour words, a cap, a scarf, a collar, glasses)"""
    lk = str(look or "").lower()
    cols = {}
    for word, c in (("brown", "#8a5a32"), ("white", "#f2f0ea"), ("grey", "#9a9aa4"), ("gray", "#9a9aa4"), ("black", "#2a2a32"),
                    ("golden", "#e0aa4a"), ("orange", "#f08a2a"), ("green", "#3ab84a"), ("red", "#c62828"), ("blue", "#1e5aa8")):
        if word in lk and species not in ("parrot", "peacock"):
            cols["body"] = c
            break
    acc = [a for a, ws in (("cap", ["cap", "hat", "টুপি"]), ("scarf", ["scarf", "muffler"]), ("collar", ["collar"]),
                           ("glasses", ["glasses", "spectacles", "চশমা"])) if any(w in lk for w in ws)]
    for word, c in (("red cap", "#d32f2f"), ("blue cap", "#1e5aa8"), ("yellow cap", "#f9c02a")):
        if word in lk:
            cols["cap"] = c
    for word, c in (("pink scarf", "#e91e63"), ("red collar", "#c62828"), ("blue collar", "#1e5aa8"), ("orange scarf", "#ff8a2a")):
        if word in lk:
            cols["scarf"] = c
    size = {"child": 0.75, "young": 0.9, "old": 1.0}.get(age, 1.0)
    return {"name_bn": name_bn, "category": "animal", "cast": "kids", "age": 8 if age == "child" else 30,
            "animal": {"species": species, "size": size}, "colours": cols, "accessories": acc,
            "gender": gender, "look": look}
