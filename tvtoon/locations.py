"""MORE ANIMATED LOCATIONS (23 Nov 2026) for the horror channel and everyday stories. Every location is a layered
World (tvtoon/world.py): its own parallax depths, its own wind-driven and living details, day or night by 'hours'.

  shmashan       cremation ground by the river: burning pyre (flames, sparks, smoke, glow), banyan with swinging
                 roots, an owl that blinks, the river with the moon's reflection
  zamindar_bari  the old zamindar house: broken windows, one lamp that flickers (and can go out), bats, creepers
  bansh_bon      bamboo grove: three depths of swaying bamboo, drifting mist, fireflies, moonbeams, a dirt path
  pukur_ghat     pond steps: water with ripples and the moon's reflection, floating lotus leaves, a lantern
  station        railway platform: shed, lamps with moths, a name board, a signal that changes, the tracks
  village_road   a road through the fields: paddy waving, electric poles and wires, a tea stall with steam
  city_street    an old Kolkata street: tram lines and overhead wires, houses with balconies and lit windows, shops
"""
import math
import random

import cairo

from tvtoon import geom as G
from tvtoon import world as WD
from tvtoon.world import GROUND, WORLD_H, _fill, _mix, _stroke

DARK = (0.10, 0.08, 0.07)


def _rgba(ctx, c, a):
    ctx.set_source_rgba(*(G.rgb(c) if isinstance(c, str) else c), a)


def _glow(ctx, x, y, r, col, a):
    g = cairo.RadialGradient(x, y, 1, x, y, r)
    c = G.rgb(col) if isinstance(col, str) else col
    g.add_color_stop_rgba(0, *c, a)
    g.add_color_stop_rgba(1, *c, 0.0)
    ctx.set_source(g)
    ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.fill()


def banyan(ctx, x, y, h, wind, t, dark=False):
    """a big banyan / peepal: a twisted trunk, a heavy crown that breathes in the wind, aerial roots that swing"""
    trunk = "#4a3a2c" if dark else "#6b5038"
    leaf = ("#1f3a24", "#27462c") if dark else ("#3e7d3a", "#4c8f42")
    ctx.new_path()
    G.smooth(ctx, [(x - 90, y), (x - 60, y - h * 0.3), (x - 70, y - h * 0.55), (x - 20, y - h * 0.7), (x + 30, y - h * 0.7),
                   (x + 60, y - h * 0.52), (x + 50, y - h * 0.3), (x + 95, y)], tension=0.4)
    _fill(ctx, trunk)
    _stroke(ctx, 3.5)
    for k in range(9):                                       # aerial roots hanging from the branches
        rx = x - 380 + k * 95
        sway = (8 + 14 * wind) * math.sin(t * 1.3 + k * 0.9)
        G.line(ctx, [(rx, y - h * 0.78), (rx + sway * 0.5, y - h * 0.45), (rx + sway, y - h * (0.12 + 0.05 * (k % 3)))], 3,
               G.rgb(trunk))
    r = random.Random(int(x))
    clumps = []
    for ring, (rad, n) in enumerate(((430, 12), (280, 9), (120, 5))):   # the crown: a dome of overlapping clumps
        for k in range(n):
            a = math.pi * (1.05 + 0.9 * k / max(1, n - 1)) if ring < 2 else 2 * math.pi * k / n
            clumps.append((x + math.cos(a) * rad + r.uniform(-30, 30), y - h * 0.78 + math.sin(a) * rad * 0.55 + r.uniform(-20, 20),
                           r.uniform(110, 160), ring * 10 + k))
    for cx, cy, rr, k in clumps:
        cx += (4 + 9 * wind) * math.sin(t * 1.1 + k * 0.7)
        cy += 3 * math.sin(t * 1.4 + k)
        ctx.new_path()
        G.ellipse(ctx, cx, cy, rr, rr * 0.72)
        _fill(ctx, leaf[k % 2])
        _stroke(ctx, 3)


class Shmashan(WD.World):
    LAYERS = dict(WD.World.LAYERS, far_bank=0.25, river=0.55, banyan=0.85, ruin=0.9, pyre=1.0)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 21.0]])
        spec.setdefault("fog", 0.25)
        super().__init__(spec)
        self.pyre_x = float(spec.get("pyre_x", 1950))
        r = random.Random(11)
        self.sparks = [(r.uniform(0, 3), r.uniform(-30, 30), r.uniform(0.6, 1.4)) for _ in range(26)]

    def static_layer(self, name, ctx):
        if name == "ground":
            ctx.new_path()
            ctx.rectangle(-1000, 700, 5400, WORLD_H + 200)
            g = cairo.LinearGradient(0, 700, 0, WORLD_H)
            g.add_color_stop_rgb(0, *G.rgb("#5a4a3a"))
            g.add_color_stop_rgb(1, *G.rgb("#3e3228"))
            ctx.set_source(g)
            ctx.fill()
            r = random.Random(5)
            for _ in range(40):                              # ash and burnt patches
                ctx.new_path()
                G.ellipse(ctx, r.uniform(-800, 4000), r.uniform(800, 1060), r.uniform(30, 90), r.uniform(6, 14))
                _rgba(ctx, "#2a2420", 0.45)
                ctx.fill()
            return True
        if name == "ruin":                                   # a broken shrine wall
            for i, (bx, bw, bh) in enumerate(((420, 300, 230), (760, 120, 150))):
                ctx.new_path()
                ctx.move_to(bx, 760)
                ctx.line_to(bx, 760 - bh)
                ctx.line_to(bx + bw * 0.4, 760 - bh - 20)
                ctx.line_to(bx + bw * 0.55, 760 - bh + 30)
                ctx.line_to(bx + bw, 760 - bh + 10)
                ctx.line_to(bx + bw, 760)
                ctx.close_path()
                _fill(ctx, "#6e5a4a")
                _stroke(ctx, 3)
                for row in range(int(bh / 26)):
                    G.line(ctx, [(bx, 760 - row * 26), (bx + bw, 760 - row * 26)], 1.5, G.rgb("#54443a"), smooth_it=False)
            return True
        return False

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["far_bank"]))
        ctx.new_path()
        G.smooth(ctx, [(-1000, 640)] + [(x, 600 + 25 * math.sin(x / 150.0)) for x in range(-1000, 4400, 160)]
                 + [(4400, 640), (4400, 680), (-1000, 680)], tension=0.4)
        _fill(ctx, _mix(G.rgb("#1c2a24"), top, 0.3), keep=False)
        ctx.restore()
        ctx.save()                                           # the river, the moon's broken reflection
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["river"]))
        ctx.new_path()
        ctx.rectangle(-1000, 650, 5400, 90)
        g = cairo.LinearGradient(0, 650, 0, 740)
        g.add_color_stop_rgb(0, *_mix(top, (0.1, 0.15, 0.2), 0.4))
        g.add_color_stop_rgb(1, 0.06, 0.08, 0.12)
        ctx.set_source(g)
        ctx.fill()
        for k in range(14):
            yy = 660 + k * 6
            w_ = 60 - k * 2 + 25 * math.sin(t * 2.0 + k)
            ctx.new_path()
            G.ellipse(ctx, 900 + 10 * math.sin(t * 1.3 + k * 0.7), yy, max(8, w_), 2.2)
            _rgba(ctx, "#fff7d6", 0.55 - k * 0.03)
            ctx.fill()
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["banyan"]))
        banyan(ctx, 2550, 760, 620, self.wind(t, 2550), t, dark=True)
        ox, oy = 2330, 760 - 620 * 0.72                       # the owl on a branch: it blinks and turns its head
        ctx.new_path()
        G.ellipse(ctx, ox, oy, 30, 40)
        _fill(ctx, "#6b5a48")
        _stroke(ctx, 2.5)
        blink = (t % 4.1) < 0.15
        look = 6 * math.sin(t * 0.5)
        for s in (-1, 1):
            ctx.new_path()
            G.ellipse(ctx, ox + s * 12 + look, oy - 10, 9, 2 if blink else 9)
            _fill(ctx, "#ffd23a", keep=False)
        ctx.restore()
        self._blit(ctx, "ruin", W, H, cam)
        self._blit(ctx, "ground", W, H, cam)
        self._pyre(ctx, W, H, cam, t)

    def _pyre(self, ctx, W, H, cam, t):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["pyre"]))
        x, y = self.pyre_x, 930
        fl = 0.85 + 0.15 * math.sin(t * 13) * math.sin(t * 7.1)
        _glow(ctx, x, y - 80, 520 * fl, "#ff8a2a", 0.35)
        for i in range(4):                                   # the stacked logs
            ctx.new_path()
            ctx.rectangle(x - 160 + (i % 2) * 20, y - 22 * (i + 1), 320, 20)
            _fill(ctx, "#5a3a22" if i % 2 else "#6e4a2a")
            _stroke(ctx, 2.5)
        for k in range(9):                                   # flames: each tongue licks up on its own rhythm
            fx = x - 130 + k * 32
            hgt = 90 + 70 * abs(math.sin(t * (5 + k * 0.7) + k * 1.3))
            lean = 20 * math.sin(t * 2.3 + k) + 30 * self.wind(t, fx)
            ctx.new_path()
            ctx.move_to(fx - 22, y - 88)
            ctx.curve_to(fx - 26, y - 88 - hgt * 0.4, fx + lean * 0.5 - 8, y - 88 - hgt * 0.8, fx + lean, y - 88 - hgt)
            ctx.curve_to(fx + lean * 0.4 + 10, y - 88 - hgt * 0.7, fx + 26, y - 88 - hgt * 0.35, fx + 22, y - 88)
            ctx.close_path()
            _fill(ctx, "#ff7a1a" if k % 2 else "#ffb020", keep=True)
            ctx.set_source_rgba(0.6, 0.2, 0.05, 1)
            ctx.set_line_width(2)
            ctx.stroke()
            ctx.new_path()
            G.ellipse(ctx, fx + lean * 0.3, y - 100 - hgt * 0.25, 9, hgt * 0.22)
            _fill(ctx, "#fff0a0", keep=False)
        for t0, dx, sp in self.sparks:                       # sparks rising and drifting
            u = ((t * 0.5 * sp + t0) % 1.6) / 1.6
            sx = x + dx * 3 + u * 160 * self.wind(t, x) + 20 * math.sin(u * 9 + t0)
            sy = y - 120 - u * 520
            ctx.new_path()
            ctx.arc(sx, sy, 3.2 * (1 - u) + 0.8, 0, 2 * math.pi)
            ctx.set_source_rgba(1, 0.75, 0.3, 0.9 * (1 - u))
            ctx.fill()
        for k in range(7):                                   # smoke
            u = ((t * 0.18 + k / 7.0) % 1.0)
            ctx.new_path()
            G.ellipse(ctx, x + u * 260 * (0.4 + self.wind(t, x)) + 25 * math.sin(u * 5 + t), y - 260 - u * 520, 50 + u * 120, 40 + u * 90)
            ctx.set_source_rgba(0.45, 0.42, 0.4, 0.35 * (1 - u))
            ctx.fill()
        ctx.restore()

    def draw_fore(self, ctx, W, H, cam, t):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["foreground"]))
        yb = GROUND + 150
        for x, s in self.grass:                               # dry, dark grass
            w = self.wind(t, x)
            for k in range(4):
                bend = (6 + 14 * w) * math.sin(t * 2.0 + x * 0.02 + k) * s
                bx = x + k * 14
                G.line(ctx, [(bx, yb), (bx + bend * 0.4, yb - 50 * s), (bx + bend, yb - (80 + k * 10) * s)], 4, G.rgb("#3a3020"))
        ctx.restore()

    def light(self, x, t):
        """warm light from the pyre on nearby characters: (r, g, b, a)"""
        d = abs(x - self.pyre_x)
        a = max(0.0, 1 - d / 900.0) * 0.22 * (0.85 + 0.15 * math.sin(t * 13))
        return (1.0, 0.55, 0.2, a)


class ZamindarBari(WD.World):
    LAYERS = dict(WD.World.LAYERS, house=0.86, bats=0.4, pillar=1.2)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 21.5]])
        spec.setdefault("fog", 0.2)
        super().__init__(spec)
        self.lamp_off = float(spec.get("lamp_off_at", 1e9))
        r = random.Random(17)
        self.bats = [(r.uniform(0, 10), r.uniform(150, 420), r.uniform(0.7, 1.3)) for _ in range(6)]

    def static_layer(self, name, ctx):
        if name == "house":
            x0, w, top = 600, 2000, 300
            ctx.new_path()
            ctx.rectangle(x0, top, w, 760 - top)
            _fill(ctx, "#8a7a68")
            _stroke(ctx, 4)
            ctx.new_path()                                   # the broken parapet
            pts = [(x0 - 30, top)]
            for i in range(21):
                pts.append((x0 - 30 + i * (w + 60) / 20, top - (40 if i % 3 else 12)))
            pts += [(x0 + w + 30, top), (x0 + w + 30, top + 30), (x0 - 30, top + 30)]
            G.smooth(ctx, pts, tension=0.05)
            _fill(ctx, "#7a6a58")
            _stroke(ctx, 3)
            for i in range(9):                               # columns and arched windows
                cx = x0 + 110 + i * 220
                ctx.new_path()
                ctx.rectangle(cx - 22, top + 30, 44, 760 - top - 30)
                _fill(ctx, "#a2927e")
                _stroke(ctx, 3)
                if i < 8:
                    wx = cx + 110
                    for row, wy in enumerate((top + 90, top + 290)):
                        ctx.new_path()
                        ctx.move_to(wx - 50, wy + 130)
                        ctx.line_to(wx - 50, wy + 40)
                        ctx.arc(wx, wy + 40, 50, math.pi, 2 * math.pi)
                        ctx.line_to(wx + 50, wy + 130)
                        ctx.close_path()
                        _fill(ctx, "#1a1612")
                        _stroke(ctx, 3)
                        if (i + row) % 3 == 0:               # broken shutters
                            G.line(ctx, [(wx - 50, wy + 60), (wx - 5, wy + 120)], 5, G.rgb("#5a4632"), smooth_it=False)
            for k in range(14):                              # cracks and creepers
                r = random.Random(k)
                x = r.uniform(x0, x0 + w)
                G.line(ctx, [(x, top + r.uniform(40, 300)), (x + r.uniform(-30, 30), top + r.uniform(300, 420)),
                             (x + r.uniform(-50, 50), 760)], 2, G.rgb("#5e5040"))
            for k in range(6):
                x = x0 + 100 + k * 340
                G.line(ctx, [(x, top), (x + 30, top + 140), (x - 10, top + 260), (x + 20, top + 380)], 6, G.rgb("#2e4a2a"))
            return True
        if name == "ground":
            ctx.new_path()
            ctx.rectangle(-1000, 740, 5400, WORLD_H + 200)
            _fill(ctx, "#6a5e50", keep=False)
            for i in range(-1000, 4400, 120):                # cracked courtyard tiles
                G.line(ctx, [(i, 760), (i - 60, WORLD_H)], 2, G.rgb("#544a3e"), smooth_it=False)
            for j in range(800, WORLD_H, 60):
                G.line(ctx, [(-1000, j), (4400, j)], 2, G.rgb("#544a3e"), smooth_it=False)
            return True
        return False

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        ctx.save()                                           # bats: jerky, fluttering flight
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["bats"]))
        for t0, y, sp in self.bats:
            u = ((t * 0.08 * sp + t0 / 10) % 1.0)
            x = -400 + u * 4200
            by = y + 40 * math.sin(t * 3 * sp + t0) + 15 * math.sin(t * 11 + t0)
            f = math.sin(t * 18 * sp + t0)
            ctx.new_path()
            ctx.move_to(x - 26, by - 12 * f)
            ctx.line_to(x - 12, by - 2)
            ctx.line_to(x - 6, by - 8)
            ctx.line_to(x, by)
            ctx.line_to(x + 6, by - 8)
            ctx.line_to(x + 12, by - 2)
            ctx.line_to(x + 26, by - 12 * f)
            ctx.line_to(x, by + 8)
            ctx.close_path()
            _fill(ctx, "#141014", keep=False)
        ctx.restore()
        self._blit(ctx, "house", W, H, cam)
        ctx.save()                                           # the one lit window: flicker, then dark at lamp_off
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["house"]))
        wx, wy = 600 + 110 + 3 * 220 + 110, 300 + 290 + 70
        if t < self.lamp_off + 0.6:
            fl = 0.75 + 0.25 * math.sin(t * 15) * math.sin(t * 6.3)
            if self.lamp_off - 0.8 < t < self.lamp_off + 0.6:   # it gutters before it dies
                fl *= max(0.0, 0.5 + 0.5 * math.sin(t * 40)) * max(0.0, (self.lamp_off + 0.6 - t) / 1.4)
            ctx.new_path()
            ctx.rectangle(wx - 48, wy - 25, 96, 85)
            ctx.set_source_rgba(1.0, 0.75, 0.3, 0.85 * fl)
            ctx.fill()
            _glow(ctx, wx, wy + 20, 260, "#ffb040", 0.35 * fl)
        ctx.restore()
        self._blit(ctx, "ground", W, H, cam)

    def draw_fore(self, ctx, W, H, cam, t):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["pillar"]))
        ctx.new_path()                                       # a broken pillar stump and weeds in front
        ctx.rectangle(260, 760, 120, 380)
        _fill(ctx, "#4a4036")
        _stroke(ctx, 3)
        for k in range(6):
            x = 200 + k * 40
            sw = 10 * math.sin(t * 2 + k)
            G.line(ctx, [(x, 1140), (x + sw * 0.4, 1080), (x + sw, 1030 - k * 6)], 5, G.rgb("#223a22"))
        ctx.restore()


class BanshBon(WD.World):
    LAYERS = dict(WD.World.LAYERS, bamboo_far=0.5, bamboo_mid=0.75, bamboo_near=0.92, path=1.0, bamboo_front=1.3)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 21.0]])
        spec.setdefault("fog", 0.35)
        super().__init__(spec)
        r = random.Random(23)
        self.stalks = {k: [(x + r.uniform(-40, 40), r.uniform(0.8, 1.2)) for x in range(-1000, 4400, sp)]
                       for k, sp in (("bamboo_far", 70), ("bamboo_mid", 110), ("bamboo_near", 190), ("bamboo_front", 600))}
        self.flies = [(r.uniform(-500, 3700), r.uniform(450, 900), r.uniform(0, 6)) for _ in range(40)]

    def _bamboo(self, ctx, x, h, wind, t, col, lw, base=760):
        lean = (14 + 40 * wind) * math.sin(2 * math.pi * t / (3.2 + (x % 7) * 0.2) + x * 0.01)
        n = 8
        pts = [(x + lean * (k / n) ** 2, base - h * k / n) for k in range(n + 1)]
        G.line(ctx, pts, lw, col)
        for k in range(1, n):                                # the nodes
            px, py = pts[k]
            G.line(ctx, [(px - lw * 0.7, py), (px + lw * 0.7, py)], 2.5, G.shade(col, 0.6), smooth_it=False)
        tx, ty = pts[-1]
        for k in range(5):                                   # leaves at the top
            a = -math.pi / 2 + (k - 2) * 0.55 + 0.2 * math.sin(t * 2 + k + x)
            ctx.new_path()
            G.ellipse(ctx, tx + math.cos(a) * 40, ty + math.sin(a) * 30 + 20, 42, 8, a)
            _fill(ctx, G.shade(col, 0.9), keep=False)

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        cols = {"bamboo_far": _mix(G.rgb("#2e4a32"), top, 0.45), "bamboo_mid": G.rgb("#3a5e34"), "bamboo_near": G.rgb("#4a7a3a")}
        for name in ("bamboo_far", "bamboo_mid", "bamboo_near"):
            ctx.save()
            ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS[name]))
            for x, s in self.stalks[name]:
                self._bamboo(ctx, x, 700 * s, self.wind(t, x), t, cols[name], {"bamboo_far": 10, "bamboo_mid": 16, "bamboo_near": 24}[name])
            ctx.restore()
        ctx.save()                                           # moonbeams through the grove
        ctx.set_matrix(self.layer_matrix(W, H, cam, 0.8))
        for k in range(4):
            x = 300 + k * 900
            ctx.new_path()
            ctx.move_to(x, 0)
            ctx.line_to(x + 160, 0)
            ctx.line_to(x + 420, 960)
            ctx.line_to(x + 200, 960)
            ctx.close_path()
            ctx.set_source_rgba(0.75, 0.85, 1.0, 0.07 + 0.03 * math.sin(t * 0.7 + k))
            ctx.fill()
        ctx.restore()
        ctx.save()                                           # the dirt path
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["path"]))
        ctx.new_path()
        ctx.rectangle(-1000, 740, 5400, WORLD_H + 200)
        g = cairo.LinearGradient(0, 740, 0, WORLD_H)
        g.add_color_stop_rgb(0, *G.rgb("#4a4030"))
        g.add_color_stop_rgb(1, *G.rgb("#5e503a"))
        ctx.set_source(g)
        ctx.fill()
        for k in range(30):
            r = random.Random(k)
            ctx.new_path()
            G.ellipse(ctx, r.uniform(-900, 4300), r.uniform(780, 1060), r.uniform(20, 60), 4)
            _rgba(ctx, "#2e2a20", 0.5)
            ctx.fill()
        ctx.restore()

    def draw_fore(self, ctx, W, H, cam, t):
        zoom = cam[2] / max(1e-6, H / 1080.0)
        if zoom < 1.45:                                       # (28 Nov 2026: in a close-up a stalk crossed the face)
            ctx.save()
            ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["bamboo_front"]))
            ctx.push_group()
            for x, s in self.stalks["bamboo_front"]:          # big dark stalks right in front
                self._bamboo(ctx, x, 1300, self.wind(t, x), t, G.rgb("#1e2e1a"), 46, base=1260)
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(max(0.0, min(1.0, (1.45 - zoom) / 0.35)))
            ctx.restore()
        ctx.save()                                           # drifting mist and blinking fireflies
        ctx.set_matrix(self.layer_matrix(W, H, cam, 0.95))
        for k in range(6):
            x = ((t * (14 + k * 4) + k * 700) % 5200) - 1000
            ctx.new_path()
            G.ellipse(ctx, x, 820 + k * 30, 520, 50)
            ctx.set_source_rgba(0.82, 0.88, 0.95, 0.12)
            ctx.fill()
        for x, y, ph in self.flies:
            on = max(0.0, math.sin(t * 2.2 + ph * 3))
            fx = x + 40 * math.sin(t * 0.6 + ph)
            fy = y + 25 * math.sin(t * 0.9 + ph * 2)
            if on > 0.05:
                _glow(ctx, fx, fy, 14, "#d9ff6a", 0.8 * on)
        ctx.restore()


class PukurGhat(WD.World):
    LAYERS = dict(WD.World.LAYERS, far_bank=0.3, pond=0.7, banyan=0.85, steps=1.0)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 20.5]])
        spec.setdefault("fog", 0.15)
        super().__init__(spec)

    def static_layer(self, name, ctx):
        if name == "steps":
            ctx.new_path()
            ctx.rectangle(-1000, 860, 5400, WORLD_H + 200)
            _fill(ctx, "#5c544a", keep=False)
            for i in range(5):                               # the ghat steps going down to the water (behind)
                y = 860 - i * 22
                ctx.new_path()
                ctx.rectangle(700 + i * 40, y - 22, 1600 - i * 80, 22)
                _fill(ctx, "#8a8070" if i % 2 else "#7a7062")
                _stroke(ctx, 2)
            for sx in (640, 2340):                           # the side walls
                ctx.new_path()
                ctx.rectangle(sx, 700, 60, 200)
                _fill(ctx, "#6e665a")
                _stroke(ctx, 3)
            return True
        return False

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["far_bank"]))
        ctx.new_path()
        G.smooth(ctx, [(-1000, 640)] + [(x, 590 + 30 * math.sin(x / 210.0)) for x in range(-1000, 4400, 180)]
                 + [(4400, 640), (4400, 700), (-1000, 700)], tension=0.4)
        _fill(ctx, _mix(G.rgb("#1e3326"), top, 0.3), keep=False)
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["pond"]))
        ctx.new_path()
        ctx.rectangle(-1000, 660, 5400, 200)
        g = cairo.LinearGradient(0, 660, 0, 860)
        g.add_color_stop_rgb(0, *_mix(top, (0.08, 0.14, 0.16), 0.5))
        g.add_color_stop_rgb(1, 0.05, 0.08, 0.1)
        ctx.set_source(g)
        ctx.fill()
        for k in range(10):                                  # the moon's reflection, broken by ripples
            ctx.new_path()
            G.ellipse(ctx, 1000 + 12 * math.sin(t * 1.7 + k), 680 + k * 12, max(6, 50 - k * 3 + 18 * math.sin(t * 2.2 + k)), 2.6)
            _rgba(ctx, "#fff8dc", 0.5 - k * 0.04)
            ctx.fill()
        for k in range(6):                                   # lotus leaves bobbing on the water
            lx, ly = 400 + k * 450, 760 + (k % 3) * 25
            ctx.new_path()
            G.ellipse(ctx, lx + 6 * math.sin(t * 0.8 + k), ly + 3 * math.sin(t * 1.1 + k), 60, 14)
            _fill(ctx, "#2f5a34")
            _stroke(ctx, 2)
        for k in range(5):                                   # rings spreading out
            u = (t * 0.3 + k / 5.0) % 1.0
            ctx.new_path()
            G.ellipse(ctx, 1500 + k * 180, 800, 20 + 160 * u, 4 + 20 * u)
            ctx.set_source_rgba(0.8, 0.9, 1.0, 0.35 * (1 - u))
            ctx.set_line_width(2)
            ctx.stroke()
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["banyan"]))
        banyan(ctx, 2900, 720, 560, self.wind(t, 2900), t, dark=True)
        ctx.restore()
        self._blit(ctx, "steps", W, H, cam)
        ctx.save()                                           # a lantern on the step
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.0))
        lx, ly = 1400, 840
        fl = 0.8 + 0.2 * math.sin(t * 12) * math.sin(t * 4.7)
        _glow(ctx, lx, ly - 40, 300 * fl, "#ffb347", 0.35)
        ctx.new_path()
        ctx.rectangle(lx - 18, ly - 70, 36, 60)
        ctx.set_source_rgba(1.0, 0.8, 0.4, 0.9 * fl)
        ctx.fill_preserve()
        _stroke(ctx, 3)
        ctx.restore()

    def draw_fore(self, ctx, W, H, cam, t):
        pass


class Station(WD.World):
    LAYERS = dict(WD.World.LAYERS, town=0.35, tracks=0.92, shed=0.97, platform=1.0)
    TRACK_P, TRACK_Y = 0.92, 790                             # trains run on this layer

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 20.5]])
        super().__init__(spec)
        self.name_bn = spec.get("station_name", "নিশিপুর")
        self.signal = spec.get("signal", [[0, "red"]])
        self._board = None

    def _name_board(self):
        if self._board is None:
            from PIL import Image, ImageDraw, ImageFont
            import numpy as np
            import os
            font = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "NotoSansBengali-Bold.ttf")
            im = Image.new("RGBA", (520, 120), (240, 200, 40, 255))
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, 519, 119], outline=(30, 20, 10, 255), width=6)
            try:
                f = ImageFont.truetype(font, 74, layout_engine=ImageFont.Layout.RAQM)
                w = d.textlength(self.name_bn, font=f)
                d.text(((520 - w) / 2, 2), self.name_bn, font=f, fill=(20, 15, 10, 255))
            except Exception:
                pass
            a = np.array(im)
            bgra = np.ascontiguousarray(a[:, :, [2, 1, 0, 3]])
            self._board = (cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()), cairo.FORMAT_ARGB32, 520, 120), bgra)
        return self._board[0]

    def static_layer(self, name, ctx):
        if name == "town":
            r = random.Random(3)
            for i in range(-1000, 4400, 150):
                h = r.uniform(80, 220)
                ctx.new_path()
                ctx.rectangle(i, 650 - h, 140, h + 60)
                _fill(ctx, "#2a2e3a", keep=False)
            return True
        if name == "tracks":
            ctx.new_path()
            ctx.rectangle(-1000, 700, 5400, 140)
            _fill(ctx, "#4a4440", keep=False)
            for i in range(-1000, 4400, 50):                 # sleepers and two rails
                ctx.new_path()
                ctx.rectangle(i, 770, 26, 34)
                _fill(ctx, "#3a2c20", keep=False)
            for y in (776, 798):
                G.line(ctx, [(-1000, y), (4400, y)], 5, G.rgb("#9a9a9a"), smooth_it=False)
            return True
        if name == "shed":
            for i in range(-800, 4400, 520):                 # pillars and the long shed roof (behind the people)
                ctx.new_path()
                ctx.rectangle(i, 380, 28, 480)
                _fill(ctx, "#3d5a6c")
                _stroke(ctx, 2.5)
            ctx.new_path()
            ctx.move_to(-1000, 360)
            ctx.line_to(4400, 360)
            ctx.line_to(4400, 400)
            ctx.line_to(-1000, 400)
            ctx.close_path()
            _fill(ctx, "#5a3a2a")
            _stroke(ctx, 3)
            for i in range(-1000, 4400, 80):
                G.line(ctx, [(i, 360), (i + 40, 330)], 3, G.rgb("#6a4a36"), smooth_it=False)
            ctx.new_path()                                   # a bench
            ctx.rectangle(2400, 800, 260, 18)
            _fill(ctx, "#7a5030")
            _stroke(ctx, 2.5)
            for lx in (2420, 2640):
                ctx.new_path()
                ctx.rectangle(lx - 6, 818, 12, 60)
                _fill(ctx, "#3a2a1a")
            return True
        if name == "platform":
            ctx.new_path()
            ctx.rectangle(-1000, 840, 5400, WORLD_H + 200)
            _fill(ctx, "#8e8a80", keep=False)
            ctx.new_path()
            ctx.rectangle(-1000, 840, 5400, 18)
            _fill(ctx, "#e8d24a", keep=False)                # the yellow edge line
            for i in range(-1000, 4400, 90):
                G.line(ctx, [(i, 860), (i - 40, WORLD_H)], 1.5, G.rgb("#7a766e"), smooth_it=False)
            return True
        return False

    def signal_at(self, t):
        c = self.signal[0][1]
        for t0, col in self.signal:
            if t >= t0:
                c = col
        return c

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        self._blit(ctx, "town", W, H, cam)
        ctx.save()                                           # lit windows of the town
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["town"]))
        r = random.Random(9)
        for _ in range(60):
            x, y = r.uniform(-1000, 4400), r.uniform(460, 640)
            on = math.sin(t * 0.2 + x) > -0.6
            if on:
                ctx.new_path()
                ctx.rectangle(x, y, 14, 18)
                ctx.set_source_rgba(1.0, 0.85, 0.45, 0.8)
                ctx.fill()
        ctx.restore()
        self._blit(ctx, "tracks", W, H, cam)
        self.draw_trains(ctx, W, H, cam, t)
        self._blit(ctx, "shed", W, H, cam)
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["shed"]))
        ctx.set_source_surface(self._name_board(), 1500, 420)
        ctx.paint()
        G.line(ctx, [(1540, 420), (1540, 380)], 4, G.rgb("#333333"), smooth_it=False)
        G.line(ctx, [(1980, 420), (1980, 380)], 4, G.rgb("#333333"), smooth_it=False)
        sx = 3300                                            # the signal post
        ctx.new_path()
        ctx.rectangle(sx, 420, 16, 440)
        _fill(ctx, "#2a2a2a", keep=False)
        ctx.new_path()
        ctx.rectangle(sx - 20, 400, 56, 110)
        _fill(ctx, "#111111", keep=False)
        sig = self.signal_at(t)
        for k, col in enumerate(("red", "green")):
            on = col == sig
            cx_, cy_ = sx + 8, 430 + k * 50
            if on:
                _glow(ctx, cx_, cy_, 70, "#ff3030" if col == "red" else "#40ff70", 0.5)
            ctx.new_path()
            ctx.arc(cx_, cy_, 16, 0, 2 * math.pi)
            ctx.set_source_rgb(*((1, 0.2, 0.2) if col == "red" else (0.3, 1, 0.45)) if on else (0.2, 0.2, 0.2))
            ctx.fill()
        for i, lx in enumerate(range(-500, 4400, 700)):      # platform lamps with moths
            ctx.new_path()
            ctx.rectangle(lx, 500, 10, 360)
            _fill(ctx, "#2e2e2e", keep=False)
            fl = 0.9 + 0.1 * math.sin(t * 9 + i)
            _glow(ctx, lx + 5, 500, 240 * fl, "#ffe9a0", 0.4)
            ctx.new_path()
            G.ellipse(ctx, lx + 5, 500, 24, 14)
            _fill(ctx, "#fff4c0", keep=False)
            for k in range(3):
                mx = lx + 5 + 40 * math.sin(t * (3 + k) + k * 2)
                my = 500 + 30 * math.sin(t * (4 + k) + k)
                ctx.new_path()
                ctx.arc(mx, my, 3, 0, 2 * math.pi)
                ctx.set_source_rgba(0.95, 0.9, 0.8, 0.9)
                ctx.fill()
        ctx.restore()
        self._blit(ctx, "platform", W, H, cam)

    def draw_trains(self, ctx, W, H, cam, t):
        """trains are drawn by the scene (vehicles with lane='tracks'); hook kept for the layer order"""
        hook = getattr(self, "train_hook", None)
        if hook:
            hook(ctx, W, H, cam, t, self.layer_matrix(W, H, cam, self.TRACK_P), self.TRACK_Y)

    def draw_fore(self, ctx, W, H, cam, t):
        pass


class VillageRoad(WD.World):
    LAYERS = dict(WD.World.LAYERS, paddy=0.5, poles=0.9, stall=0.88, road=1.0)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 17.3]])
        super().__init__(spec)

    def static_layer(self, name, ctx):
        if name == "road":
            ctx.new_path()
            ctx.rectangle(-1000, 740, 5400, WORLD_H + 200)
            _fill(ctx, "#8a7a5a", keep=False)                 # the earth verge
            ctx.new_path()
            ctx.rectangle(-1000, 860, 5400, 160)
            _fill(ctx, "#4a4a50", keep=False)                 # the tarmac
            for i in range(-1000, 4400, 160):
                ctx.new_path()
                ctx.rectangle(i, 936, 80, 8)
                _fill(ctx, "#e8e2c8", keep=False)
            return True
        if name == "stall":                                  # a tea stall
            x = 1150
            ctx.new_path()
            ctx.rectangle(x, 560, 380, 200)
            _fill(ctx, "#a0703a")
            _stroke(ctx, 3)
            ctx.new_path()
            ctx.move_to(x - 40, 560)
            ctx.line_to(x + 420, 560)
            ctx.line_to(x + 380, 500)
            ctx.line_to(x, 500)
            ctx.close_path()
            _fill(ctx, "#4a7a9a")
            _stroke(ctx, 3)
            ctx.new_path()
            ctx.rectangle(x + 40, 640, 300, 30)
            _fill(ctx, "#6a4a2a")
            _stroke(ctx, 2)
            ctx.new_path()
            G.ellipse(ctx, x + 120, 625, 30, 22)
            _fill(ctx, "#b0b0b0")
            _stroke(ctx, 2)
            return True
        return False

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        ctx.save()                                           # paddy fields waving
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["paddy"]))
        ctx.new_path()
        ctx.rectangle(-1000, 640, 5400, 120)
        _fill(ctx, "#6fa33a", keep=False)
        for x in range(-1000, 4400, 26):
            w = self.wind(t, x)
            b = (6 + 12 * w) * math.sin(t * 2.2 - x * 0.012)
            G.line(ctx, [(x, 760), (x + b * 0.5, 720), (x + b, 690)], 3, G.rgb("#8cc04a"))
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["near_plants"]))
        for x, h in ((-300, 480), (700, 520), (2300, 500), (3400, 470)):
            WD.palm(ctx, x, 760, h, self.wind(t, x), t, x)
        ctx.restore()
        self._blit(ctx, "stall", W, H, cam)
        ctx.save()                                           # tea steam
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["stall"]))
        for k in range(5):
            u = (t * 0.4 + k / 5.0) % 1.0
            ctx.new_path()
            G.ellipse(ctx, 1270 + 20 * math.sin(u * 6 + t), 590 - u * 140, 10 + u * 22, 8 + u * 16)
            ctx.set_source_rgba(1, 1, 1, 0.45 * (1 - u))
            ctx.fill()
        ctx.restore()
        ctx.save()                                           # electric poles and sagging wires that sway
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["poles"]))
        xs = list(range(-900, 4400, 700))
        for x in xs:
            ctx.new_path()
            ctx.rectangle(x, 360, 14, 420)
            _fill(ctx, "#5a5a5a", keep=False)
            G.line(ctx, [(x - 40, 380), (x + 54, 380)], 6, G.rgb("#4a4a4a"), smooth_it=False)
        for a, b in zip(xs, xs[1:]):
            for dy in (-30, 30):
                sag = 40 + 6 * math.sin(t * 1.5 + a)
                G.line(ctx, [(a + 7 + dy, 380), ((a + b) / 2 + 7, 380 + sag), (b + 7 + dy, 380)], 2, G.rgb("#222222"))
        ctx.restore()
        self._blit(ctx, "road", W, H, cam)


class CityStreet(WD.World):
    LAYERS = dict(WD.World.LAYERS, far_city=0.3, houses=0.82, wires=0.95, street=1.0)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 18.2]])
        super().__init__(spec)

    def static_layer(self, name, ctx):
        if name == "houses":
            r = random.Random(31)
            x = -1000
            pal = ["#c97b5a", "#e0b25a", "#9fb4a0", "#d68c8c", "#b9a27a", "#a8b8c8"]
            while x < 4400:
                w = r.uniform(300, 460)
                h = r.uniform(380, 560)
                ctx.new_path()
                ctx.rectangle(x, 780 - h, w, h)
                _fill(ctx, pal[int(x) % len(pal)] if False else r.choice(pal))
                _stroke(ctx, 3)
                for row in range(int(h / 130)):              # balconies with railings, green shutters
                    by = 780 - h + 60 + row * 130
                    ctx.new_path()
                    ctx.rectangle(x + 30, by, w - 60, 70)
                    _fill(ctx, "#3a5a40", keep=False)
                    G.line(ctx, [(x + 20, by + 70), (x + w - 20, by + 70)], 5, G.rgb("#2a2a2a"), smooth_it=False)
                    for k in range(int((w - 40) / 22)):
                        G.line(ctx, [(x + 24 + k * 22, by + 70), (x + 24 + k * 22, by + 100)], 2, G.rgb("#2a2a2a"), smooth_it=False)
                ctx.new_path()                                # a shop at street level
                ctx.rectangle(x + 20, 690, w - 40, 90)
                _fill(ctx, "#2a2420")
                _stroke(ctx, 2)
                ctx.new_path()
                ctx.rectangle(x + 20, 660, w - 40, 30)
                _fill(ctx, r.choice(["#c62828", "#1565c0", "#2e7d32", "#f9a825"]))
                _stroke(ctx, 2)
                x += w + r.uniform(0, 20)
            return True
        if name == "street":
            ctx.new_path()
            ctx.rectangle(-1000, 780, 5400, WORLD_H + 200)
            _fill(ctx, "#8a8478", keep=False)                 # pavement
            ctx.new_path()
            ctx.rectangle(-1000, 850, 5400, 200)
            _fill(ctx, "#4c4a48", keep=False)                 # the road
            for y in (930, 975):                             # tram lines set into the road
                G.line(ctx, [(-1000, y), (4400, y)], 4, G.rgb("#b8b8b8"), smooth_it=False)
            return True
        return False

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["far_city"]))
        r = random.Random(4)
        for i in range(-1000, 4400, 120):
            h = r.uniform(120, 300)
            ctx.new_path()
            ctx.rectangle(i, 640 - h, 110, h + 80)
            _fill(ctx, _mix(G.rgb("#4a4e5a"), top, 0.4), keep=False)
        ctx.restore()
        self._blit(ctx, "houses", W, H, cam)
        ctx.save()                                           # windows light up as evening comes
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["houses"]))
        dusk = max(0.0, min(1.0, (0.3 - sun_h) / 0.4))
        if dusk > 0:
            r = random.Random(8)
            for _ in range(70):
                x, y = r.uniform(-1000, 4400), r.uniform(300, 640)
                if r.random() < 0.6:
                    ctx.new_path()
                    ctx.rectangle(x, y, 26, 34)
                    ctx.set_source_rgba(1.0, 0.85, 0.45, 0.75 * dusk)
                    ctx.fill()
        ctx.restore()
        ctx.save()                                           # tram wires and posts
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["wires"]))
        for x in range(-900, 4400, 600):
            ctx.new_path()
            ctx.rectangle(x, 300, 12, 560)
            _fill(ctx, "#3a3a3a", keep=False)
            _glow(ctx, x + 6, 320, 160, "#ffe9a0", 0.35 * max(0.0, min(1.0, (0.3 - self._sun(t)) / 0.4)))
        for y in (330, 360):
            G.line(ctx, [(-1000, y), (4400, y + 4 * math.sin(t))], 2.5, G.rgb("#202020"), smooth_it=False)
        ctx.restore()
        self._blit(ctx, "street", W, H, cam)

    def _sun(self, t):
        return WD.tod_palette(self.hour(t))[3]

    def draw_fore(self, ctx, W, H, cam, t):
        pass


class GharRoom(WD.World):
    """inside a house at night: a window with the moon and a curtain moving in the wind, a door that can open
    (door_open_at: t, it swings open slowly and a cold light falls in), a hurricane lantern that flickers,
    a ceiling fan turning, a cot, a shelf. Most horror stories happen in rooms like this."""
    LAYERS = dict(WD.World.LAYERS, room=1.0, fan=1.0)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 21.5]])
        super().__init__(spec)
        self.door_t = float(spec.get("door_open_at", 1e9))
        self.lamp_off = float(spec.get("lamp_off_at", 1e9))
        self.fan = bool(spec.get("fan", True))
        self.wall = spec.get("wall", "#b9a98a")
        self.win = (700, 330, 360, 330)                      # x, y, w, h of the window
        self.door = (2150, 230, 300, 630)

    def static_layer(self, name, ctx):
        if name == "room":
            wx, wy, ww, wh = self.win
            dx, dy, dw, dh = self.door
            ctx.new_path()                                   # the wall with two openings (window and door)
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            ctx.rectangle(-1000, -400, 5400, 1260)
            ctx.rectangle(wx, wy, ww, wh)
            ctx.rectangle(dx, dy, dw, dh)
            g = cairo.LinearGradient(0, -400, 0, 860)
            g.add_color_stop_rgb(0, *G.shade(self.wall, 0.75))
            g.add_color_stop_rgb(1, *G.rgb(self.wall))
            ctx.set_source(g)
            ctx.fill()
            ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
            ctx.new_path()                                   # damp patches and cracks
            for k in range(7):
                r = random.Random(k + 40)
                ctx.new_path()
                G.ellipse(ctx, r.uniform(-500, 3800), r.uniform(0, 700), r.uniform(80, 200), r.uniform(40, 120))
                ctx.set_source_rgba(0.35, 0.3, 0.22, 0.18)
                ctx.fill()
            for x0, y0, w0, h0 in (self.win, self.door):     # wooden frames
                ctx.new_path()
                ctx.rectangle(x0 - 14, y0 - 14, w0 + 28, h0 + 28)
                ctx.rectangle(x0, y0, w0, h0)
                ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
                _fill(ctx, "#5a3a22")
                _stroke(ctx, 3)
                ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
            for k in range(1, 4):                            # window bars
                G.line(ctx, [(wx + ww * k / 4, wy), (wx + ww * k / 4, wy + wh)], 6, G.rgb("#3a2a1a"), smooth_it=False)
            ctx.new_path()                                   # the floor
            ctx.rectangle(-1000, 860, 5400, WORLD_H + 200)
            _fill(ctx, "#6e5a44", keep=False)
            G.line(ctx, [(-1000, 860), (4400, 860)], 5, G.rgb("#4a3a2a"), smooth_it=False)
            ctx.new_path()                                   # a wooden cot with a mosquito net folded up
            ctx.rectangle(-300, 740, 760, 60)
            _fill(ctx, "#7a5030")
            _stroke(ctx, 3)
            for lx in (-290, 440):
                ctx.new_path()
                ctx.rectangle(lx, 800, 22, 100)
                _fill(ctx, "#5a3a22")
                _stroke(ctx, 2)
                G.line(ctx, [(lx + 11, 740), (lx + 11, 420)], 5, G.rgb("#5a3a22"), smooth_it=False)
            ctx.new_path()
            ctx.rectangle(-280, 700, 720, 50)
            _fill(ctx, "#e8e0d0")
            _stroke(ctx, 2)
            ctx.new_path()                                   # a shelf with books and a clock
            ctx.rectangle(1300, 420, 420, 22)
            _fill(ctx, "#5a3a22")
            _stroke(ctx, 2)
            for k in range(7):
                ctx.new_path()
                ctx.rectangle(1320 + k * 34, 340 + (k % 3) * 10, 28, 80 - (k % 3) * 10)
                _fill(ctx, ["#8a3a2a", "#2a5a6a", "#6a6a2a"][k % 3])
                _stroke(ctx, 1.5)
            ctx.new_path()                                   # a table for the lantern
            ctx.rectangle(1550, 700, 300, 26)
            _fill(ctx, "#6a4428")
            _stroke(ctx, 2.5)
            for lx in (1565, 1815):
                ctx.new_path()
                ctx.rectangle(lx, 726, 20, 134)
                _fill(ctx, "#4a2e1a", keep=False)
            return True
        return False

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        # (the sky, moon, clouds and stars from the base world show through the window)
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 0.5))      # trees outside the window, swaying
        for k in range(5):
            x = 400 + k * 220
            sw = 12 * math.sin(t * 1.2 + k) * (0.4 + self.wind(t, x))
            ctx.new_path()
            G.ellipse(ctx, x + sw, 560, 140, 110)
            _fill(ctx, "#13201a", keep=False)
        ctx.restore()
        dx, dy, dw, dh = self.door
        m = self.layer_matrix(W, H, cam, 1.0)
        ctx.save()
        ctx.set_matrix(m)
        ctx.new_path()                                       # outside the door: darkness
        ctx.rectangle(dx, dy, dw, dh)
        _fill(ctx, "#07080c", keep=False)
        ctx.restore()
        self._blit(ctx, "room", W, H, cam)
        ctx.save()
        ctx.set_matrix(m)
        ctx.new_path()                                       # the upper wall and the ceiling beams above
        ctx.rectangle(-2000, -3000, 7000, 3001)
        _fill(ctx, G.shade(self.wall, 0.72), keep=False)
        for bx in range(-1000, 4400, 420):
            ctx.new_path()
            ctx.rectangle(bx, -3000, 40, 2960)
            _fill(ctx, "#4a3420", keep=False)
        wx, wy, ww, wh = self.win
        w = self.wind(t, wx)                                 # the curtain blows in the wind
        for side in (0, 1):
            x0 = wx + (ww * 0.5 if side else 0)
            bil = (20 + 50 * w) * (0.5 + 0.5 * math.sin(t * 1.7 + side))
            ctx.new_path()
            ctx.move_to(x0, wy)
            ctx.line_to(x0 + ww * 0.5, wy)
            ctx.curve_to(x0 + ww * 0.45 + bil * 0.3, wy + wh * 0.4, x0 + ww * 0.5 + bil, wy + wh * 0.7, x0 + ww * 0.42 + bil, wy + wh)
            ctx.line_to(x0 + ww * 0.08 + bil * 0.6, wy + wh)
            ctx.curve_to(x0 + bil * 0.4, wy + wh * 0.6, x0 + bil * 0.2, wy + wh * 0.3, x0, wy)
            ctx.close_path()
            ctx.set_source_rgba(0.92, 0.9, 0.82, 0.55)
            ctx.fill_preserve()
            ctx.set_source_rgba(0.3, 0.28, 0.24, 0.8)
            ctx.set_line_width(2)
            ctx.stroke()
        # the door: closed, or swinging open (the panel narrows as it turns) and cold light falls in
        a = max(0.0, min(1.0, (t - self.door_t) / 2.5))
        a = a * a * (3 - 2 * a)
        pw = dw * (1.0 - 0.82 * a)
        if a > 0:
            g = cairo.LinearGradient(dx, 0, dx + dw + 600, 0)
            g.add_color_stop_rgba(0, 0.7, 0.8, 1.0, 0.25 * a)
            g.add_color_stop_rgba(1, 0.7, 0.8, 1.0, 0.0)
            ctx.set_source(g)
            ctx.move_to(dx + pw, dy + dh)
            ctx.line_to(dx + dw, dy + dh)
            ctx.line_to(dx + dw + 600 * a, 1080)
            ctx.line_to(dx + pw - 200 * a, 1080)
            ctx.close_path()
            ctx.fill()
        ctx.new_path()
        ctx.move_to(dx, dy)
        ctx.line_to(dx + pw, dy + 18 * a)
        ctx.line_to(dx + pw, dy + dh - 18 * a)
        ctx.line_to(dx, dy + dh)
        ctx.close_path()
        _fill(ctx, "#6b4226")
        _stroke(ctx, 3)
        for k in range(3):
            G.line(ctx, [(dx + pw * 0.15, dy + 60 + k * 200), (dx + pw * 0.85, dy + 60 + k * 200 + 18 * a)], 3,
                   G.rgb("#4a2e1a"), smooth_it=False)
        ctx.new_path()
        ctx.arc(dx + pw * 0.85, dy + dh * 0.52, 10, 0, 2 * math.pi)
        _fill(ctx, "#c9a227", keep=False)
        # the hurricane lantern on the table: flickers, can die out
        lx, ly = 1700, 690
        if t < self.lamp_off + 0.6:
            fl = 0.8 + 0.2 * math.sin(t * 13) * math.sin(t * 5.1)
            if self.lamp_off - 0.8 < t:
                fl *= max(0.0, 0.5 + 0.5 * math.sin(t * 40)) * max(0.0, (self.lamp_off + 0.6 - t) / 1.4)
            _glow(ctx, lx, ly - 50, 700 * fl, "#ffb347", 0.32)
            ctx.new_path()
            G.ellipse(ctx, lx, ly - 50, 26, 40)
            ctx.set_source_rgba(1.0, 0.85, 0.45, 0.9 * fl)
            ctx.fill()
        ctx.new_path()
        ctx.rectangle(lx - 34, ly - 10, 68, 14)
        _fill(ctx, "#8a6a3a")
        _stroke(ctx, 2)
        ctx.new_path()
        G.ellipse(ctx, lx, ly - 50, 32, 46)
        ctx.set_source_rgba(0.9, 0.95, 1.0, 0.25)
        ctx.fill_preserve()
        _stroke(ctx, 2.5)
        G.line(ctx, [(lx - 30, ly - 96), (lx, ly - 130), (lx + 30, ly - 96)], 3, G.rgb("#5a4a2a"))
        if self.fan:                                         # the ceiling fan turns (slowly, it is old)
            fx, fy = 1500, -60
            G.line(ctx, [(fx, -400), (fx, fy)], 8, G.rgb("#3a3a3a"), smooth_it=False)
            ang = t * 4.0
            for k in range(3):
                a_ = ang + k * 2 * math.pi / 3
                ex, ey = fx + math.cos(a_) * 420, fy + math.sin(a_) * 40
                ctx.new_path()
                ctx.move_to(fx, fy - 6)
                ctx.line_to(ex, ey - 12)
                ctx.line_to(ex, ey + 12)
                ctx.line_to(fx, fy + 6)
                ctx.close_path()
                _fill(ctx, "#5a5a52")
                _stroke(ctx, 2)
            ctx.new_path()
            G.ellipse(ctx, fx, fy, 50, 22)
            _fill(ctx, "#4a4a44")
            _stroke(ctx, 2)
        ctx.restore()

    def draw_fore(self, ctx, W, H, cam, t):
        pass


LOCATIONS = {"village_courtyard": WD.World, "shmashan": Shmashan, "zamindar_bari": ZamindarBari, "bansh_bon": BanshBon,
             "pukur_ghat": PukurGhat, "station": Station, "village_road": VillageRoad, "city_street": CityStreet, "ghar": GharRoom}
NAMES_BN = {"village_courtyard": "গ্রামের উঠোন", "shmashan": "শ্মশান", "zamindar_bari": "পুরনো জমিদারবাড়ি", "bansh_bon": "বাঁশবন",
            "pukur_ghat": "পুকুরঘাট", "station": "রেলস্টেশন", "village_road": "গ্রামের রাস্তা", "city_street": "কলকাতার রাস্তা", "ghar": "ঘরের ভেতর"}


def make(name, spec=None):
    return LOCATIONS[name](spec)


def _register_interiors():
    from tvtoon import interiors as IN
    from tvtoon import rooms as RM
    LOCATIONS.update(IN.INTERIORS)
    NAMES_BN.update(IN.NAMES_BN)
    LOCATIONS["ghar"] = RM.Room                     # every kind of room (spec 'kind'); the default is the bedroom
    LOCATIONS["boat"] = RM.Boat
    NAMES_BN["boat"] = "নদীতে নৌকা"
    from tvtoon import outdoors as OD
    OD.register(LOCATIONS, NAMES_BN)                # market, temple, mountain, seaside, school


_register_interiors()
