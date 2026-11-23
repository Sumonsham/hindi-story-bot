"""VEHICLES (side view, flat TV-cartoon style): bus, train, tram, auto-rickshaw, toto (e-rickshaw), cycle, motorbike.

Every vehicle is drawn by code at any size; wheels turn by the distance driven (no sliding), the body bounces a
little with speed, exhaust puffs come out of engines, headlights and windows glow at night. A vehicle moves with an
eased start and stop (it accelerates, cruises, brakes). Riders sit on the seats it reports (cycle / bike / auto /
toto driver); passengers inside buses, trams and trains are hidden while inside.

World units: the ground plane of the characters (an adult man is ~620 px tall at scale 1)."""
import math

import cairo

from tvtoon import geom as G

LINE = (0.16, 0.10, 0.08)


def _f(ctx, c, keep=True):
    ctx.set_source_rgb(*(G.rgb(c) if isinstance(c, str) else c))
    ctx.fill_preserve() if keep else ctx.fill()


def _s(ctx, w=4, col=LINE):
    ctx.set_source_rgb(*col)
    ctx.set_line_width(w)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def _rr(ctx, x, y, w, h, r):
    ctx.new_path()
    ctx.move_to(x + r, y)
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.close_path()


def wheel(ctx, cx, cy, r, ang, spokes=0, tyre="#202020", rim="#9a9a9a"):
    ctx.new_path()
    ctx.arc(cx, cy, r, 0, 2 * math.pi)
    _f(ctx, tyre)
    _s(ctx, 3)
    ctx.new_path()
    ctx.arc(cx, cy, r * (0.82 if spokes else 0.55), 0, 2 * math.pi)
    _f(ctx, "#cfcfcf" if spokes else rim, keep=False) if not spokes else None
    if spokes:
        ctx.new_path()
        ctx.arc(cx, cy, r * 0.84, 0, 2 * math.pi)
        ctx.set_source_rgb(0.85, 0.85, 0.85)
        ctx.set_line_width(2)
        ctx.stroke()
        for k in range(spokes):
            a = ang + k * 2 * math.pi / spokes
            G.line(ctx, [(cx, cy), (cx + math.cos(a) * r * 0.84, cy + math.sin(a) * r * 0.84)], 1.6, (0.75, 0.75, 0.75),
                   smooth_it=False)
    else:
        for k in range(5):                                   # wheel nuts show the turning
            a = ang + k * 2 * math.pi / 5
            ctx.new_path()
            ctx.arc(cx + math.cos(a) * r * 0.32, cy + math.sin(a) * r * 0.32, r * 0.07, 0, 2 * math.pi)
            _f(ctx, "#555555", keep=False)
    ctx.new_path()
    ctx.arc(cx, cy, r * 0.12, 0, 2 * math.pi)
    _f(ctx, "#444444", keep=False)


def _lights(ctx, x, y, d, on, length=520):
    if on <= 0:
        return
    ctx.save()
    g = cairo.LinearGradient(x, y, x + d * length, y)
    g.add_color_stop_rgba(0, 1, 0.95, 0.7, 0.55 * on)
    g.add_color_stop_rgba(1, 1, 0.95, 0.7, 0.0)
    ctx.set_source(g)
    ctx.move_to(x, y - 12)
    ctx.line_to(x + d * length, y - 90)
    ctx.line_to(x + d * length, y + 120)
    ctx.line_to(x, y + 12)
    ctx.close_path()
    ctx.fill()
    ctx.restore()


# size factor: the drawings are made small; k brings each to its real size next to the people
# (a bicycle is about as long as a man is tall, an auto a little taller than a man, a bus about 1.5x his height)
SIZE_K = {"bus": 1.9, "tram": 1.9, "train": 1.9, "auto": 1.55, "toto": 1.55, "cycle": 1.85, "bike": 1.75}

SPEC = {   # length, height, wheel radius, wheel x positions (fraction from the back), colour
    "bus": {"L": 1900, "H": 760, "r": 95, "wx": (0.18, 0.80), "col": "#d84315", "col2": "#fbc02d"},
    "tram": {"L": 1700, "H": 700, "r": 70, "wx": (0.15, 0.30, 0.70, 0.85), "col": "#1565c0", "col2": "#f5f5f0"},
    "train": {"L": 2300, "H": 720, "r": 70, "wx": (0.12, 0.24, 0.76, 0.88), "col": "#8d2a1e", "col2": "#f0c040"},
    "auto": {"L": 640, "H": 560, "r": 60, "wx": (0.2, 0.88), "col": "#2e7d32", "col2": "#fdd835"},
    "toto": {"L": 760, "H": 600, "r": 62, "wx": (0.18, 0.86), "col": "#00897b", "col2": "#eceff1"},
    "cycle": {"L": 520, "H": 300, "r": 95, "wx": (0.18, 0.82), "col": "#1a237e"},
    "bike": {"L": 640, "H": 360, "r": 100, "wx": (0.16, 0.84), "col": "#b71c1c"},
}


class Vehicle:
    def __init__(self, vid, kind, x, z=0.0, colour=None, cars=1, lane=None):
        self.id, self.kind = vid, kind
        self.sp = dict(SPEC[kind])
        if colour:
            self.sp["col"] = colour
        self.x0, self.z = float(x), float(z)
        self.cars = int(cars) if kind == "train" else 1
        self.lane = lane                                     # "tracks": drawn on the station's track layer
        self.moves = []                                      # (t0, t1, xa, xb)

    def x_at(self, t):
        x = self.x0
        for t0, t1, xa, xb in self.moves:
            if t >= t1:
                x = xb
            elif t >= t0:
                u = (t - t0) / max(1e-6, t1 - t0)
                # accelerate (first 25 %), cruise, brake (last 25 %): a smooth S-curve in distance
                e = u * u * (3 - 2 * u) if (t1 - t0) < 2.5 else _trapezoid(u, 0.25)
                return xa + (xb - xa) * e
        return x

    def speed(self, t):
        return (self.x_at(t + 0.02) - self.x_at(t - 0.02)) / 0.04

    def direction(self, t):
        for t0, t1, xa, xb in self.moves:
            if t0 - 0.5 <= t <= t1 + 0.5:
                return 1.0 if xb >= xa else -1.0
        return getattr(self, "facing", 1.0)

    @property
    def k(self):
        return SIZE_K.get(self.kind, 1.0) * getattr(self, "kmul", 1.0)

    def length(self):
        return self.sp["L"] * self.k * (self.cars if self.kind == "train" else 1)

    def height(self):
        return self.sp["H"] * self.k

    def seat(self, k=0):
        """(dx from the vehicle's centre in its forward direction, seat height above the ground) in world px at scale 1"""
        L, H = self.sp["L"] * self.k, self.sp["H"] * self.k
        if self.kind in ("bus", "tram"):                    # passengers sit behind the windows, one per window
            Lr = self.sp["L"]
            step, first = (230, 60 + 95) if self.kind == "bus" else (205, 50 + 80)
            return ((-Lr / 2 + first + step * min(k, 6)) * self.k, 0.0)
        return {"cycle": [(-0.13 * L, 0.64 * H)], "bike": [(0.02 * L, 0.6 * H), (-0.22 * L, 0.64 * H)],
                "auto": [(0.22 * L, 0.3 * H), (-0.2 * L, 0.3 * H), (-0.32 * L, 0.3 * H)],
                "toto": [(0.28 * L, 0.3 * H), (-0.08 * L, 0.3 * H), (-0.26 * L, 0.3 * H)]
                }.get(self.kind, [(0.0, 0.0)])[min(k, 2 if self.kind in ("auto", "toto") else 1)]

    def rig_world(self, k, t, x, gy, scale):
        """where a rider's body goes, in world coordinates: hip (on the saddle / seat), feet (pedals, pegs, the floor),
        hands (the handlebar; None for passengers), whether the feet pedal, the crank angle, the lean"""
        L, H, r = self.sp["L"], self.sp["H"], self.sp["r"]
        x0 = -L / 2
        d = self.direction(t)
        kk = scale * self.k
        yb = gy - self.bob(t) * 0.3 * self.k

        def w(p):
            return (x + d * p[0] * kk, yb + p[1] * kk)

        k = min(k, 2 if self.kind in ("auto", "toto") else 1)
        if self.kind == "cycle":
            crank = (x0 + 0.45 * L, -r)
            ca = self.crank_angle(t, scale)
            pedals = [(crank[0] + math.cos(ca) * 40 * s_, crank[1] + math.sin(ca) * 40 * s_) for s_ in (1, -1)]
            return {"hip": w((x0 + 0.37 * L, -r - 200)), "feet": [w(p) for p in pedals], "bars": w((x0 + 0.74 * L - 58, -r - 244)),
                    "pedal": True, "crank": ca, "lean": 24}
        if self.kind == "bike":
            if k == 0:
                return {"hip": w((x0 + 0.33 * L, -r - 178)), "feet": [w((x0 + 0.5 * L, -r - 40))] * 2,
                        "bars": w((x0 + 0.68 * L, -r - 278)), "lean": 16}
            return {"hip": w((x0 + 0.14 * L, -r - 182)), "feet": [w((x0 + 0.3 * L, -r - 45))] * 2, "bars": None, "lean": 4}
        if self.kind == "auto":
            if k == 0:
                return {"hip": w((x0 + 0.7 * L, -0.33 * H)), "feet": [w((x0 + 0.9 * L, -r * 0.8))] * 2,
                        "bars": w((x0 + 0.86 * L, -0.6 * H)), "lean": 12}
            hx = x0 + (0.3 if k == 1 else 0.18) * L
            return {"hip": w((hx, -0.4 * H)), "feet": [w((hx + 0.22 * L, -r * 0.8))] * 2, "bars": None, "lean": 2}
        if self.kind == "toto":
            if k == 0:
                return {"hip": w((x0 + 0.76 * L, -0.33 * H)), "feet": [w((x0 + 0.95 * L, -0.15 * H))] * 2,
                        "bars": w((x0 + 0.9 * L, -0.57 * H)), "lean": 12}
            hx = x0 + (0.42 if k == 1 else 0.24) * L
            return {"hip": w((hx, -0.4 * H)), "feet": [w((hx + 0.2 * L, -0.15 * H))] * 2, "bars": None, "lean": 2}
        return {"hip": w((0.0, -0.3 * H)), "feet": [w((0.2 * L, 0.0))] * 2, "bars": None, "lean": 2}

    def crank_angle(self, t, scale):
        dist = self.x_at(t) / (scale * self.k) if scale else 0.0
        return dist / self.sp["r"] * self.direction(t) * 1.2

    def open_ride(self):
        return self.kind in ("cycle", "bike", "auto", "toto")

    def bob(self, t):
        v = abs(self.speed(t))
        return min(1.0, v / 400.0) * 4 * math.sin(t * 17 + sum(map(ord, self.id)) % 7)

    def draw(self, ctx, x, gy, scale, t, night=0.0, part="all"):
        """part: 'all', or for vehicles people sit IN (auto, toto): 'back' (behind the passengers) and 'front' (the
        lower body and wheels in front of their legs)"""
        d = self.direction(t)
        v = abs(self.speed(t))
        dist = self.x_at(t) / (scale * self.k) if scale else 0.0
        ctx.save()
        ctx.translate(x, gy)
        ctx.scale(scale * self.k * d, scale * self.k)
        ctx.translate(0, -self.bob(t) / max(scale, 1e-3) * 0.3)
        ang = dist / self.sp["r"] * d                        # forward: the top of the wheel moves the way it goes
        if part == "front":
            self._front(ctx, t, ang, v, night)
        else:
            getattr(self, "_" + self.kind)(ctx, t, ang, v, night)
        ctx.restore()

    def _front(self, ctx, t, ang, v, night):
        """the parts in front of seated passengers (auto / toto): lower body panel, the stripe, the wheels"""
        L, H, r = self.sp["L"], self.sp["H"], self.sp["r"]
        x0 = -L / 2
        if self.kind == "auto":
            ctx.new_path()
            G.smooth(ctx, [(x0, -r * 0.8), (x0, -H * 0.44), (x0 + L * 0.95, -H * 0.44), (x0 + L, -H * 0.4), (x0 + L, -r * 0.8)],
                     tension=0.15)
            _f(ctx, self.sp["col"])
            _s(ctx, 4)
            ctx.new_path()
            ctx.rectangle(x0, -H * 0.4, L, H * 0.12)
            _f(ctx, self.sp["col2"], keep=False)
            G.line(ctx, [(x0 + L * 0.8, -H * 0.98), (x0 + L * 0.86, -H * 0.44)], 6, G.shade(self.sp["col"], 0.6), smooth_it=False)
        else:
            ctx.new_path()
            ctx.rectangle(x0, -H * 0.42, L * 0.75, H * 0.3)
            _f(ctx, self.sp["col2"])
            _s(ctx, 3)
            ctx.new_path()
            G.smooth(ctx, [(x0 + L * 0.75, -H * 0.12), (x0 + L * 0.75, -H * 0.5), (x0 + L * 0.92, -H * 0.55), (x0 + L, -H * 0.2)],
                     tension=0.3)
            _f(ctx, self.sp["col"])
            _s(ctx, 3)
        self._wheels(ctx, ang)

    def window_rects(self, x, gy, scale, t):
        """the passenger windows of a bus / tram in world coordinates (x, y, w, h)"""
        L, H = self.sp["L"], self.sp["H"]
        x0 = -L / 2
        loc = {"bus": [(x0 + 60 + i * 230, -H * 0.88, 190, H * 0.34) for i in range(7)],
               "tram": [(x0 + 50 + i * 205, -H * 0.86, 160, H * 0.32) for i in range(8)]}.get(self.kind, [])
        d = self.direction(t)
        k = scale * self.k
        yb = gy - self.bob(t) * 0.3 * self.k
        out = []
        for lx, ly, w, h in loc:
            a, b = x + d * lx * k, x + d * (lx + w) * k
            out.append((min(a, b), yb + ly * k, abs(b - a), h * k))
        return out

    # ------------------------------------------------------------------ the drawings (facing +x, ground y = 0)
    def _wheels(self, ctx, ang, spokes=0, xs=None, dx=0.0):
        L, r = self.sp["L"], self.sp["r"]
        for f in (xs or self.sp["wx"]):
            wheel(ctx, dx - L / 2 + f * L, -r, r, ang, spokes)

    def _exhaust(self, ctx, x, y, t, v):
        for k in range(4):
            u = (t * (0.8 + v / 600.0) + k / 4.0) % 1.0
            ctx.new_path()
            G.ellipse(ctx, x - u * 160, y - u * 60, 14 + 30 * u, 10 + 20 * u)
            ctx.set_source_rgba(0.6, 0.6, 0.62, 0.45 * (1 - u))
            ctx.fill()

    def _bus(self, ctx, t, ang, v, night):
        L, H, r = self.sp["L"], self.sp["H"], self.sp["r"]
        x0 = -L / 2
        _rr(ctx, x0, -H, L, H - r * 0.6, 40)
        _f(ctx, self.sp["col"])
        _s(ctx, 5)
        ctx.new_path()
        ctx.rectangle(x0, -H * 0.42, L, H * 0.1)
        _f(ctx, self.sp["col2"], keep=False)
        for i in range(7):                                    # windows (glow at night)
            wx = x0 + 60 + i * 230
            _rr(ctx, wx, -H * 0.88, 190, H * 0.34, 14)
            _f(ctx, (0.55 + 0.4 * night, 0.7 + 0.15 * night, 0.85 - 0.4 * night))
            _s(ctx, 3)
        _rr(ctx, x0 + L - 170, -H * 0.88, 140, H * 0.72, 14)  # the door / driver
        _f(ctx, "#33393f")
        _s(ctx, 3)
        ctx.new_path()
        ctx.rectangle(x0 + L - 40, -H * 0.3, 30, 40)
        _f(ctx, "#fff3b0" if night > 0.2 else "#f0f0f0")
        _s(ctx, 2)
        _lights(ctx, x0 + L, -H * 0.27, 1, night, 700)
        self._wheels(ctx, ang)
        self._exhaust(ctx, x0 - 10, -r * 0.6, t, v)

    def _tram(self, ctx, t, ang, v, night):
        L, H, r = self.sp["L"], self.sp["H"], self.sp["r"]
        x0 = -L / 2
        _rr(ctx, x0, -H, L, H - r * 0.9, 26)
        _f(ctx, self.sp["col2"])
        _s(ctx, 5)
        ctx.new_path()
        ctx.rectangle(x0, -H * 0.4, L, H * 0.28)
        _f(ctx, self.sp["col"], keep=False)
        for i in range(8):
            wx = x0 + 50 + i * 205
            _rr(ctx, wx, -H * 0.86, 160, H * 0.32, 10)
            _f(ctx, (0.6 + 0.35 * night, 0.72 + 0.15 * night, 0.85 - 0.4 * night))
            _s(ctx, 3)
        # the trolley pole up to the overhead wire, springing a little
        G.line(ctx, [(x0 + L * 0.35, -H), (x0 + L * 0.55, -H - 560 + 6 * math.sin(t * 9))], 6, (0.2, 0.2, 0.2), smooth_it=False)
        ctx.new_path()
        ctx.arc(x0 + L * 0.55, -H - 560 + 6 * math.sin(t * 9), 10, 0, 2 * math.pi)
        _f(ctx, "#ffcc33" if v > 20 and int(t * 12) % 7 == 0 else "#333333", keep=False)   # a spark now and then
        _lights(ctx, x0 + L, -H * 0.3, 1, night, 600)
        self._wheels(ctx, ang)

    def _train(self, ctx, t, ang, v, night):
        L, H, r = self.sp["L"], self.sp["H"], self.sp["r"]
        for c in range(self.cars):                           # the locomotive leads, the coaches follow
            cx0 = L * (self.cars / 2.0) - L * (c + 1)
            loco = c == 0
            _rr(ctx, cx0 + 20, -H, L - 40, H - r * 0.9, 30 if loco else 16)
            _f(ctx, self.sp["col"] if loco else "#2e5e8e")
            _s(ctx, 5)
            ctx.new_path()
            ctx.rectangle(cx0 + 20, -H * 0.42, L - 40, H * 0.08)
            _f(ctx, self.sp["col2"], keep=False)
            if loco:
                _rr(ctx, cx0 + L - 330, -H * 0.86, 230, H * 0.32, 12)
                _f(ctx, "#a8c8e0")
                _s(ctx, 3)
                G.line(ctx, [(cx0 + L * 0.4, -H), (cx0 + L * 0.5, -H - 90), (cx0 + L * 0.6, -H)], 5, (0.2, 0.2, 0.2), smooth_it=False)
                _lights(ctx, cx0 + L - 20, -H * 0.3, 1, max(night, 0.4), 900)
            else:
                for i in range(9):
                    wx = cx0 + 70 + i * 240
                    _rr(ctx, wx, -H * 0.84, 150, H * 0.26, 8)
                    _f(ctx, (0.55 + 0.4 * night, 0.68 + 0.2 * night, 0.82 - 0.4 * night))
                    _s(ctx, 3)
                    for k in range(3):                       # window bars
                        G.line(ctx, [(wx + 38 * (k + 1), -H * 0.84), (wx + 38 * (k + 1), -H * 0.58)], 2, (0.25, 0.25, 0.25),
                               smooth_it=False)
            for f in self.sp["wx"]:
                wheel(ctx, cx0 + f * L, -r, r, ang)
            if c < self.cars - 1:
                G.line(ctx, [(cx0 + 20, -r * 1.6), (cx0 - 20, -r * 1.6)], 10, (0.2, 0.2, 0.2), smooth_it=False)

    def _auto(self, ctx, t, ang, v, night):
        L, H, r = self.sp["L"], self.sp["H"], self.sp["r"]
        x0 = -L / 2
        ctx.new_path()                                       # body: rounded nose, open sides, canvas roof
        G.smooth(ctx, [(x0, -r * 0.8), (x0, -H * 0.55), (x0 + L * 0.1, -H * 0.95), (x0 + L * 0.8, -H * 0.98), (x0 + L, -H * 0.6),
                       (x0 + L, -r * 0.8)], tension=0.25)
        _f(ctx, self.sp["col"])
        _s(ctx, 4)
        ctx.new_path()
        ctx.rectangle(x0 + L * 0.12, -H * 0.86, L * 0.62, H * 0.42)
        _f(ctx, "#20262a" if night < 0.3 else "#3a3220", keep=False)
        ctx.new_path()
        ctx.rectangle(x0, -H * 0.4, L, H * 0.12)
        _f(ctx, self.sp["col2"], keep=False)
        ctx.new_path()
        ctx.arc(x0 + L - 18, -H * 0.36, 14, 0, 2 * math.pi)
        _f(ctx, "#fff3b0", keep=False)
        _lights(ctx, x0 + L, -H * 0.36, 1, night, 450)
        self._wheels(ctx, ang)
        self._exhaust(ctx, x0, -r * 0.7, t, v)

    def _toto(self, ctx, t, ang, v, night):
        L, H, r = self.sp["L"], self.sp["H"], self.sp["r"]
        x0 = -L / 2
        ctx.new_path()                                       # the canopy on thin posts, open sides
        ctx.rectangle(x0 + 20, -H, L - 40, 40)
        _f(ctx, self.sp["col"])
        _s(ctx, 3)
        for fx in (0.08, 0.5, 0.92):
            G.line(ctx, [(x0 + fx * L, -H + 40), (x0 + fx * L, -H * 0.4)], 5, (0.3, 0.3, 0.3), smooth_it=False)
        ctx.new_path()
        ctx.rectangle(x0, -H * 0.42, L * 0.75, H * 0.3)
        _f(ctx, self.sp["col2"])
        _s(ctx, 3)
        ctx.new_path()                                       # the front with the handlebar
        G.smooth(ctx, [(x0 + L * 0.75, -H * 0.12), (x0 + L * 0.75, -H * 0.5), (x0 + L * 0.92, -H * 0.55), (x0 + L, -H * 0.2)],
                 tension=0.3)
        _f(ctx, self.sp["col"])
        _s(ctx, 3)
        _lights(ctx, x0 + L, -H * 0.4, 1, night, 400)
        self._wheels(ctx, ang)

    def _cycle(self, ctx, t, ang, v, night):
        L, r = self.sp["L"], self.sp["r"]
        x0 = -L / 2
        rb, ff = (x0 + 0.18 * L, -r), (x0 + 0.82 * L, -r)
        wheel(ctx, rb[0], rb[1], r, ang, spokes=12)
        wheel(ctx, ff[0], ff[1], r, ang, spokes=12)
        col = G.rgb(self.sp["col"])
        crank = (x0 + 0.45 * L, -r)
        seat = (x0 + 0.38 * L, -r - 175)
        head = (x0 + 0.74 * L, -r - 190)
        for a, b in ((rb, crank), (crank, seat), (seat, rb), (crank, head), (seat, (head[0] - 30, head[1] + 10)), (head, ff)):
            G.line(ctx, [a, b], 9, col, smooth_it=False)
        G.line(ctx, [head, (head[0] - 10, head[1] - 50), (head[0] - 60, head[1] - 56)], 7, (0.2, 0.2, 0.2), smooth_it=False)
        ctx.new_path()
        G.ellipse(ctx, seat[0], seat[1] - 10, 42, 12)
        _f(ctx, "#222222", keep=False)
        ca = ang * 1.2                                       # the pedals go round (= crank_angle)
        for s_ in (1, -1):
            px, py = crank[0] + math.cos(ca) * 40 * s_, crank[1] + math.sin(ca) * 40 * s_
            G.line(ctx, [crank, (px, py)], 6, (0.3, 0.3, 0.3), smooth_it=False)
            G.line(ctx, [(px - 16, py), (px + 16, py)], 7, (0.15, 0.15, 0.15), smooth_it=False)
        self.pedal = ca

    def _bike(self, ctx, t, ang, v, night):
        L, H, r = self.sp["L"], self.sp["H"], self.sp["r"]
        x0 = -L / 2
        ctx.new_path()                                       # tank, seat, engine
        G.smooth(ctx, [(x0 + 0.25 * L, -r - 120), (x0 + 0.5 * L, -r - 200), (x0 + 0.72 * L, -r - 190), (x0 + 0.7 * L, -r - 90),
                       (x0 + 0.3 * L, -r - 70)], tension=0.3)
        _f(ctx, self.sp["col"])
        _s(ctx, 4)
        _rr(ctx, x0 + 0.1 * L, -r - 175, 0.4 * L, 40, 18)
        _f(ctx, "#1e1e1e")
        _s(ctx, 3)
        ctx.new_path()
        ctx.rectangle(x0 + 0.38 * L, -r - 80, 0.22 * L, 80)
        _f(ctx, "#5a5a5a")
        _s(ctx, 3)
        G.line(ctx, [(x0 + 0.72 * L, -r - 190), (x0 + 0.84 * L, -r)], 10, (0.6, 0.6, 0.62), smooth_it=False)
        G.line(ctx, [(x0 + 0.7 * L, -r - 200), (x0 + 0.78 * L, -r - 270), (x0 + 0.68 * L, -r - 280)], 7, (0.15, 0.15, 0.15),
               smooth_it=False)
        ctx.new_path()
        ctx.arc(x0 + 0.8 * L, -r - 215, 22, 0, 2 * math.pi)
        _f(ctx, "#fff3b0" if night > 0.2 else "#e0e0e0")
        _s(ctx, 2)
        _lights(ctx, x0 + 0.8 * L, -r - 215, 1, night, 650)
        G.line(ctx, [(x0 + 0.2 * L, -r - 40), (x0 - 0.05 * L, -r - 30)], 9, (0.5, 0.5, 0.5), smooth_it=False)
        self._wheels(ctx, ang, spokes=8)
        self._exhaust(ctx, x0 - 0.05 * L, -r - 30, t, v)


def _trapezoid(u, a):
    """distance share for accelerate (a) - cruise - brake (a) with continuous speed"""
    vmax = 1.0 / (1.0 - a)
    if u < a:
        return 0.5 * vmax * u * u / a
    if u > 1 - a:
        w = 1 - u
        return 1 - 0.5 * vmax * w * w / a
    return 0.5 * vmax * a + vmax * (u - a)
