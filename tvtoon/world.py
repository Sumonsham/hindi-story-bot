"""ANIMATED LAYERED WORLD (engine v2, 23 Nov 2026): a village drawn as separate depth layers, each with its own parallax
factor and its own motion. The camera is independent of the background animation.

Depth layers (p = parallax factor: 0 = fixed to the screen, 1 = the ground plane where the characters stand,
> 1 = foreground in front of the characters):
  sky (p 0: gradient by time of day, sun / moon, stars)  -> clouds (p 0.06, drifting at different speeds)
  -> far hills (0.18) -> birds (0.3, flapping, crossing) -> distant tree line (0.42, slow sway)
  -> far palms (0.62) -> huts (0.85, lamp glow + flicker at dusk, cooking smoke) -> near palms / bananas (0.92,
  wind-driven fronds) -> fence (0.96) -> ground, pond with moving water, props (1.0)
  [characters]  -> foreground grass and bushes (1.22, swaying) -> falling leaves -> rain / fog -> light of the hour.

Wind: one wind field (a base + slow gusts) moves every plant with a phase that depends on its position, so trees
do not swing in step. Every layer keeps its objects at fixed positions and proportions between frames."""
import math
import random

import cairo

from tvtoon import geom as G

LINE = (0.16, 0.10, 0.08)
WORLD_W, WORLD_H, GROUND = 3200, 1080, 960
CX0, CY0 = WORLD_W / 2.0, WORLD_H / 2.0           # where all layers line up


def _stroke(ctx, w=4, col=LINE):
    ctx.set_source_rgb(*col)
    ctx.set_line_width(w)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def _fill(ctx, c, keep=True):
    ctx.set_source_rgb(*(G.rgb(c) if isinstance(c, str) else c))
    ctx.fill_preserve() if keep else ctx.fill()


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


# time of day -> palette (hour of the day)
TOD = [  # hour, sky top, sky bottom, light tint (r,g,b,alpha), sun height 0..1
    (12.0, "#7cc3f0", "#d6eef8", (1.0, 1.0, 1.0, 0.0), 1.0),
    (16.0, "#86c2ea", "#f3e6c8", (1.0, 0.93, 0.80, 0.08), 0.55),
    (17.6, "#e8a36a", "#fbd38d", (1.0, 0.72, 0.45, 0.20), 0.18),
    (18.6, "#4a4f8c", "#e88f6a", (0.55, 0.45, 0.75, 0.30), -0.05),
    (20.0, "#0e1636", "#2b3566", (0.20, 0.25, 0.50, 0.50), -0.4),
]


def tod_palette(hour):
    if hour <= TOD[0][0]:
        k = TOD[0]
        return G.rgb(k[1]), G.rgb(k[2]), k[3], k[4]
    for a, b in zip(TOD, TOD[1:]):
        if a[0] <= hour <= b[0]:
            u = (hour - a[0]) / (b[0] - a[0])
            tint = tuple(a[3][i] + (b[3][i] - a[3][i]) * u for i in range(4))
            return _mix(G.rgb(a[1]), G.rgb(b[1]), u), _mix(G.rgb(a[2]), G.rgb(b[2]), u), tint, a[4] + (b[4] - a[4]) * u
    k = TOD[-1]
    return G.rgb(k[1]), G.rgb(k[2]), k[3], k[4]


class World:
    """village_courtyard, animated. spec keys: seed, wind (0..1), hours [[t, hour], ...], rain [[t0, t1]], fog 0..1"""

    LAYERS = {"sky": 0.0, "clouds": 0.06, "hills": 0.18, "birds": 0.30, "treeline": 0.42, "far_palms": 0.62,
              "huts": 0.85, "near_plants": 0.92, "fence": 0.96, "ground": 1.0, "foreground": 1.22}

    def __init__(self, spec=None):
        spec = spec or {}
        self.rnd = random.Random(spec.get("seed", 3))
        self.wind_base = float(spec.get("wind", 0.45))
        self.hours = spec.get("hours") or [[0.0, 15.5]]
        self.rain = spec.get("rain") or []
        self.fog = float(spec.get("fog", 0.0))
        self.lightning = float(spec.get("lightning", 0.0))
        r = self.rnd
        self.clouds = [(r.uniform(-600, 3800), r.uniform(70, 300), r.uniform(45, 90), r.uniform(5, 16)) for _ in range(9)]
        self.hill_pts = [(x, 600 - 120 * math.sin(x / 520.0 + 0.7) - 50 * math.sin(x / 190.0) + r.uniform(-8, 8))
                         for x in range(-900, 4200, 120)]
        self.tree_pts = [(x, 640 + r.uniform(-45, 25)) for x in range(-900, 4200, 90)]
        self.far_palms = [(x + r.uniform(-60, 60), r.uniform(230, 300)) for x in range(-500, 3900, 420)]
        self.near = [("palm", 180, 470), ("palm", 900, 500), ("banana", 1200, 330), ("palm", 1900, 455),
                     ("banana", 2140, 280), ("palm", 2950, 480), ("banana", -150, 300), ("palm", 3500, 460)]
        self.huts = [(380, 760, 620, 330), (2300, 740, 520, 290), (-700, 750, 520, 300), (3450, 750, 560, 300)]
        self.grass = [(x + r.uniform(-30, 30), r.uniform(0.7, 1.3)) for x in range(-900, 4200, 150)]
        self.bushes = [(x, r.uniform(0.8, 1.2)) for x in (-200, 700, 1650, 2550, 3400)]
        self.birds = [(r.uniform(0, 40), r.uniform(-1, 1) > 0, r.uniform(150, 330), r.uniform(70, 120)) for _ in range(4)]
        self.leaves = [(r.uniform(-400, 3600), r.uniform(0, 50), r.uniform(0.6, 1.4)) for _ in range(10)]
        self.pond = (2700, 1000, 300, 46)
        self.ground_tex = [(r.uniform(-800, 4000), r.uniform(800, 1075), r.uniform(15, 40)) for _ in range(110)]
        self.stars = [(r.uniform(0, 1), r.uniform(0, 0.55), r.uniform(0.6, 1.6)) for _ in range(80)]
        self._cache = {}

    # ------------------------------------------------------------------ time, wind, light
    def hour(self, t):
        h = self.hours
        if t <= h[0][0]:
            return h[0][1]
        for a, b in zip(h, h[1:]):
            if a[0] <= t <= b[0]:
                return a[1] + (b[1] - a[1]) * G.ease((t - a[0]) / max(1e-6, b[0] - a[0]))
        return h[-1][1]

    def wind(self, t, x=0.0):
        """wind strength at time t and place x: a base + slow gusts travelling across the village"""
        g = 0.55 * math.sin(2 * math.pi * (t / 7.3 - x / 2600.0)) + 0.3 * math.sin(2 * math.pi * (t / 3.1 - x / 900.0) + 1.7)
        return self.wind_base * (1.0 + 0.6 * g)

    def raining(self, t):
        a = 0.0
        for t0, t1 in self.rain:
            if t0 - 1.5 <= t <= t1 + 1.5:
                a = max(a, min(1.0, (t - t0 + 1.5) / 1.5, (t1 + 1.5 - t) / 1.5))
        return a

    def sun_dx(self, t):
        """the sun's side offset for contact shadows (shadows move as the sun sinks)"""
        _a, _b, _tint, sh = tod_palette(self.hour(t))
        return (1.0 - max(-0.2, sh)) * 0.35

    # ------------------------------------------------------------------ camera per layer
    @staticmethod
    def layer_matrix(W, H, cam, p):
        cx, cy, z = cam
        zb = H / 1080.0                                   # the output size (not a zoom)
        zp = zb * (z / zb) ** p                           # far layers zoom less, the foreground more
        m = cairo.Matrix()
        m.translate(W / 2.0, H / 2.0)
        m.scale(zp, zp)
        m.translate(-(CX0 + (cx - CX0) * p), -(CY0 + (cy - CY0) * p))
        return m

    def screen_x(self, W, H, cam, p, x):
        """where a point x of layer p lands on screen (used by the parallax test)"""
        return self.layer_matrix(W, H, cam, p).transform_point(x, GROUND)[0]

    # ------------------------------------------------------------------ static layers, drawn once
    def _static(self, name, W):
        key = name
        if key in self._cache:
            return self._cache[key]
        x0, w = -1000, 5400
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, WORLD_H + 200)
        ctx = cairo.Context(surf)
        ctx.translate(-x0, 0)
        if self.static_layer(name, ctx):
            pass
        elif name == "hills":
            ctx.new_path()
            G.smooth(ctx, [(-1000, 760)] + self.hill_pts + [(4400, 760), (4400, 900), (-1000, 900)], tension=0.45)
            _fill(ctx, "#8fbf8a", keep=False)
        elif name == "ground":
            ctx.new_path()
            ctx.rectangle(-1000, 690, 5400, WORLD_H - 690 + 200)
            gg = cairo.LinearGradient(0, 690, 0, WORLD_H)
            gg.add_color_stop_rgb(0, *G.rgb("#d9b98c"))
            gg.add_color_stop_rgb(1, *G.rgb("#c9a172"))
            ctx.set_source(gg)
            ctx.fill()
            for x, y, L in self.ground_tex:
                G.line(ctx, [(x, y), (x + L, y + 1)], 2, G.rgb("#b8905f"), smooth_it=False)
            tulsi(ctx, 1640, 790)
            pot(ctx, 1090, 790, 26)
            pot(ctx, 1040, 795, 20)
        elif name == "fence":
            ctx.new_path()
            for i in range(-1000, 4400, 46):
                if any(hx - 20 < i < hx + w_ + 20 for hx, _y, w_, _h in self.huts):
                    continue
                ctx.rectangle(i, 650, 14, 110)
            _fill(ctx, "#c2a265")
            _stroke(ctx, 2)
            G.line(ctx, [(-1000, 690), (4400, 690)], 5, G.rgb("#a8884f"), smooth_it=False)
        elif name == "huts":
            for hx, hy, hw, hh in self.huts:
                hut(ctx, hx, hy, hw, hh)
        self._cache[key] = (surf, x0)
        return self._cache[key]

    def static_layer(self, name, ctx):
        """subclasses draw their own static layers here (return True when drawn)"""
        return False

    def _blit(self, ctx, name, W, H, cam, p=None):
        surf, x0 = self._static(name, W)
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS[name] if p is None else p))
        ctx.set_source_surface(surf, x0, 0)
        ctx.get_source().set_filter(cairo.FILTER_GOOD)
        ctx.paint()
        ctx.restore()

    # ------------------------------------------------------------------ drawing
    def draw_back(self, ctx, W, H, cam, t):
        """everything behind the characters. Leaves ctx in screen space."""
        top, bot, tint, sun_h = tod_palette(self.hour(t))
        ctx.save()
        ctx.identity_matrix()
        g = cairo.LinearGradient(0, 0, 0, H)
        g.add_color_stop_rgb(0, *top)
        g.add_color_stop_rgb(0.75, *bot)
        g.add_color_stop_rgb(1, *bot)
        ctx.set_source(g)
        ctx.paint()
        night = max(0.0, min(1.0, -sun_h / 0.35))
        if night > 0:                                           # stars come out
            for sx, sy, r in self.stars:
                ctx.new_path()
                ctx.arc(sx * W, sy * H, r * (W / 1920), 0, 2 * math.pi)
                tw = 0.6 + 0.4 * math.sin(t * 3 + sx * 40)
                ctx.set_source_rgba(1, 1, 0.9, night * tw)
                ctx.fill()
        sy = H * (0.62 - 0.5 * max(-0.4, min(1.0, sun_h)))      # the sun sinks; the moon rises at night
        if sun_h > -0.1:                                        # the sun's glow spreads over the sky (warmer when low)
            gl = cairo.RadialGradient(W * 0.78, sy, H * 0.04, W * 0.78, sy, H * 0.55)
            warm = (1.0, 0.95, 0.75) if sun_h > 0.3 else (1.0, 0.72, 0.42)
            gl.add_color_stop_rgba(0, *warm, 0.55 if sun_h > 0.3 else 0.7)
            gl.add_color_stop_rgba(0.35, *warm, 0.18)
            gl.add_color_stop_rgba(1, *warm, 0.0)
            ctx.set_source(gl)
            ctx.paint()
        ctx.new_path()
        if sun_h > -0.1:
            ctx.arc(W * 0.78, sy, H * 0.05, 0, 2 * math.pi)
            ctx.set_source_rgba(1.0, 0.93 if sun_h > 0.3 else 0.7, 0.55 if sun_h > 0.3 else 0.35, 0.95)
        else:
            ctx.arc(W * 0.2, H * 0.16, H * 0.04, 0, 2 * math.pi)
            ctx.set_source_rgba(0.98, 0.96, 0.85, night)
        ctx.fill()
        ctx.restore()
        # clouds: each drifts at its own speed; they wrap round the wide world
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["clouds"]))
        ccol = _mix((1, 1, 1), bot, 0.25) if sun_h > 0 else _mix((0.5, 0.52, 0.65), top, 0.4)
        for cx, cy, r, sp in self.clouds:
            x = (cx + sp * t * (0.6 + self.wind_base)) % 4800 - 900
            ctx.new_path()
            for dx, dy, rr in ((-1, 0, 0.8), (0, -0.4, 1.0), (1, 0, 0.85), (0.4, 0.2, 0.9), (-0.5, 0.2, 0.9)):
                G.ellipse(ctx, x + dx * r, cy + dy * r, r * rr * 1.1, r * rr * 0.75)
            ctx.set_source_rgba(*ccol, 0.95)
            ctx.fill()
        ctx.restore()
        self._blit(ctx, "hills", W, H, cam)
        haze = 0.12 + 0.5 * max(0.0, min(1.0, -sun_h / 0.35))      # distance haze, much stronger at night
        ctx.save()
        ctx.identity_matrix()
        ctx.set_source_rgba(*top, haze)
        ctx.paint()
        ctx.restore()
        # birds cross the sky now and then, flapping
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["birds"]))
        for t0, right, y, sp in self.birds:
            period = 26.0
            u = ((t - t0) % period) / period
            if u > 0.7:
                continue
            x = -300 + u / 0.7 * 3800 if right else 3500 - u / 0.7 * 3800
            for k in range(3):
                bx, by = x - (k * 38 if right else -k * 38), y + k * 14 + math.sin(t * 2 + k) * 6
                f = math.sin(2 * math.pi * (t * 3.2 + k * 0.3))
                ctx.new_path()
                ctx.move_to(bx - 16, by - 8 * f)
                ctx.curve_to(bx - 8, by - 10 * f - 2, bx - 3, by - 2, bx, by)
                ctx.curve_to(bx + 3, by - 2, bx + 8, by - 10 * f - 2, bx + 16, by - 8 * f)
                ctx.set_source_rgb(0.18, 0.16, 0.18)
                ctx.set_line_width(3)
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.stroke()
        ctx.restore()
        self.draw_mid(ctx, W, H, cam, t, top, bot, sun_h)

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        """the location's own layers between the hills and the characters (the village by default)"""
        # distant tree line: a soft sway of the crowns
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["treeline"]))
        pts = [(x + 6 * self.wind(t, x) * math.sin(t * 1.3 + x * 0.01), y) for x, y in self.tree_pts]
        ctx.new_path()
        G.smooth(ctx, [(-1000, 760)] + pts + [(4400, 760), (4400, 800), (-1000, 800)], tension=0.4)
        _fill(ctx, "#6fae5c", keep=False)
        ctx.restore()
        # far palms (small, slow sway)
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["far_palms"]))
        for x, h in self.far_palms:
            palm(ctx, x, 700, h, self.wind(t, x) * 0.6, t, x, lw=1.6)
        ctx.restore()
        self._blit(ctx, "huts", W, H, cam)
        # lamps in the hut windows at dusk (with flicker) and cooking smoke
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["huts"]))
        dusk = max(0.0, min(1.0, (0.25 - sun_h) / 0.35))
        for i, (hx, hy, hw, hh) in enumerate(self.huts):
            if dusk > 0:
                fl = 0.85 + 0.15 * math.sin(t * 17 + i * 3) * math.sin(t * 5.3 + i)
                wx, wy = hx + hw * 0.2, hy - hh * 0.52
                rg = cairo.RadialGradient(wx, wy, 2, wx, wy, hw * 0.35)
                rg.add_color_stop_rgba(0, 1.0, 0.8, 0.35, 0.75 * dusk * fl)
                rg.add_color_stop_rgba(1, 1.0, 0.6, 0.2, 0.0)
                ctx.set_source(rg)
                ctx.paint()
            sx0, sy0 = hx + hw * 0.85, hy - hh * 1.2              # smoke rising, bent by the wind
            for k in range(6):
                u = ((t * 0.35 + k / 6.0) % 1.0)
                ctx.new_path()
                G.ellipse(ctx, sx0 + u * 120 * (0.5 + self.wind(t, sx0)) + math.sin(u * 6 + t) * 10, sy0 - u * 260,
                          16 + u * 40, 12 + u * 30)
                ctx.set_source_rgba(0.85, 0.85, 0.85, 0.32 * (1 - u))
                ctx.fill()
        ctx.restore()
        # near palms and bananas: wind-driven fronds
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["near_plants"]))
        for kind, x, h in self.near:
            if kind == "palm":
                palm(ctx, x, 700, h, self.wind(t, x), t, x)
            else:
                banana(ctx, x, 760, h, self.wind(t, x), t, x)
        ctx.restore()
        self._blit(ctx, "fence", W, H, cam)
        self._blit(ctx, "ground", W, H, cam)
        # the pond: moving ripples and a shimmer of light
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["ground"]))
        px, py, prx, pry = self.pond
        ctx.new_path()
        G.ellipse(ctx, px, py, prx, pry)
        g = cairo.LinearGradient(0, py - pry, 0, py + pry)
        g.add_color_stop_rgb(0, *_mix(G.rgb("#5aa3c9"), top, 0.3))
        g.add_color_stop_rgb(1, *G.rgb("#3b7fa6"))
        ctx.set_source(g)
        ctx.fill_preserve()
        _stroke(ctx, 3, (0.35, 0.27, 0.18))
        ctx.save()
        ctx.new_path()
        G.ellipse(ctx, px, py, prx - 4, pry - 3)
        ctx.clip()
        for k in range(7):
            u = (t * 0.25 + k / 7.0) % 1.0
            ctx.new_path()
            G.ellipse(ctx, px - prx * 0.5 + (k * 97) % (prx), py - pry * 0.3 + (k * 13) % (pry), 20 + 70 * u, 4 + 12 * u)
            ctx.set_source_rgba(1, 1, 1, 0.45 * (1 - u))
            ctx.set_line_width(2)
            ctx.stroke()
        ctx.restore()
        ctx.restore()

    def draw_front(self, ctx, W, H, cam, t):
        """in front of the characters: grass, bushes, falling leaves, rain, fog, the light of the hour"""
        top, bot, tint, sun_h = tod_palette(self.hour(t))
        self.draw_fore(ctx, W, H, cam, t)
        self.draw_weather(ctx, W, H, cam, t, tint)

    def draw_fore(self, ctx, W, H, cam, t):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["foreground"]))
        yb = GROUND + 150
        for x, s in self.grass:
            w = self.wind(t, x)
            for k in range(5):
                bend = (8 + 16 * w) * math.sin(t * 2.4 + x * 0.02 + k) * s
                bx = x + k * 12
                ctx.new_path()
                ctx.move_to(bx - 5, yb)
                ctx.curve_to(bx - 3, yb - 40 * s, bx + bend * 0.5, yb - 70 * s, bx + bend, yb - (85 + k * 9) * s)
                ctx.curve_to(bx + bend * 0.4 + 4, yb - 60 * s, bx + 4, yb - 30 * s, bx + 5, yb)
                ctx.close_path()
                _fill(ctx, "#4f9a3e" if k % 2 else "#5fae4b")
                _stroke(ctx, 2)
        for x, s in self.bushes:
            w = self.wind(t, x)
            ctx.new_path()
            for k in range(5):
                a = math.pi + k * math.pi / 4
                dx = math.sin(t * 1.7 + k + x * 0.01) * 5 * w
                G.ellipse(ctx, x + math.cos(a) * 80 * s + dx, yb - 40 * s + math.sin(a) * 50 * s, 60 * s, 46 * s)
            _fill(ctx, "#3f8a37")
            _stroke(ctx, 3)
        ctx.restore()
        # falling leaves drift with the wind (only in the ground plane)
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.08))
        for x0, t0, s in self.leaves:
            period = 9.0 / s
            u = ((t - t0) % period) / period
            x = x0 + u * 400 * (0.5 + self.wind(t, x0)) + math.sin(u * 12 + x0) * 40
            y = 380 + u * 640
            ctx.save()
            ctx.translate(x, y)
            ctx.rotate(math.sin(u * 9 + x0) * 1.2)
            ctx.new_path()
            G.ellipse(ctx, 0, 0, 11 * s, 5 * s)
            _fill(ctx, "#8db53a" if int(x0) % 2 else "#c9a33a")
            _stroke(ctx, 1.5)
            ctx.restore()
        ctx.restore()

    def draw_weather(self, ctx, W, H, cam, t, tint):
        ctx.save()
        ctx.identity_matrix()
        rn = self.raining(t)
        if rn > 0:                                              # rain: three depths, faster and bigger in front
            r = random.Random(7)
            for depth, n, L, sp in ((0.4, 160, 18, 700), (0.7, 120, 30, 1100), (1.0, 70, 46, 1600)):
                ctx.set_line_width(1.2 + depth * 1.6)
                ctx.set_source_rgba(0.8, 0.85, 0.95, 0.35 * rn * depth + 0.1)
                for i in range(n):
                    x = (r.uniform(0, W) + t * 90 * depth) % W
                    y = (r.uniform(0, H) + t * sp) % (H + 60) - 30
                    ctx.move_to(x, y)
                    ctx.line_to(x - 6 * depth, y + L)
                ctx.stroke()
            ctx.set_source_rgba(0.35, 0.4, 0.5, 0.25 * rn)
            ctx.paint()
        if self.fog > 0:
            g = cairo.LinearGradient(0, H * 0.3, 0, H)
            g.add_color_stop_rgba(0, 0.9, 0.92, 0.95, 0.0)
            g.add_color_stop_rgba(1, 0.9, 0.92, 0.95, self.fog * 0.45)
            ctx.set_source(g)
            ctx.paint()
            # (24 Nov 2026) the fog MOVES: soft banks drifting across at three depths, each at its own speed
            r = random.Random(11)
            for depth, n, sp in ((0.5, 5, 14.0), (0.75, 4, 26.0), (1.0, 3, 42.0)):
                for i in range(n):
                    w_ = W * r.uniform(0.35, 0.6) * depth
                    x = (r.uniform(0, W + w_) + t * sp * (1 if i % 2 else 0.7)) % (W + 2 * w_) - w_
                    y = H * (0.55 + 0.38 * depth) + 18 * math.sin(t * 0.4 + i)
                    hh = H * 0.16 * depth
                    rg = cairo.RadialGradient(x, y, 0, x, y, w_ * 0.5)
                    a_ = self.fog * 0.32 * depth * (0.75 + 0.25 * math.sin(t * 0.3 + i * 1.7))
                    rg.add_color_stop_rgba(0, 0.9, 0.92, 0.95, a_)
                    rg.add_color_stop_rgba(1, 0.9, 0.92, 0.95, 0.0)
                    ctx.save()
                    ctx.translate(x, y)
                    ctx.scale(1.0, hh / max(1.0, w_ * 0.5))
                    ctx.translate(-x, -y)
                    ctx.set_source(rg)
                    ctx.arc(x, y, w_ * 0.5, 0, 2 * math.pi)
                    ctx.fill()
                    ctx.restore()
        light = float(getattr(self, "lightning", 0.0) or 0.0)
        if light > 0:                                           # a storm: lightning flashes now and then
            k = t % 9.3
            fl = (0.55 if k < 0.08 else 0.0) + (0.35 if 0.2 < k < 0.27 else 0.0)
            if fl > 0:
                ctx.set_source_rgba(0.85, 0.9, 1.0, fl * light)
                ctx.paint()
        if tint[3] > 0:                                         # the light of the hour over everything
            ctx.set_source_rgba(*tint)
            ctx.set_operator(cairo.OPERATOR_MULTIPLY)
            ctx.paint()
            ctx.set_operator(cairo.OPERATOR_OVER)
        ctx.restore()


# ---------------------------------------------------------------------- the drawn objects (animated by wind)
def palm(ctx, x, y, h, wind=0.4, t=0.0, seed_x=0.0, lw=3.0):
    """a coconut palm: the trunk bends a little and every frond swings with its own phase"""
    lean = (6 + 18 * wind) * math.sin(2 * math.pi * t / 4.7 + seed_x * 0.013)
    ctx.new_path()
    ctx.move_to(x - 10, y)
    ctx.curve_to(x - 6, y - h * 0.5, x + 18 + lean * 0.4, y - h * 0.8, x + 14 + lean, y - h)
    ctx.line_to(x + 30 + lean, y - h)
    ctx.curve_to(x + 30 + lean * 0.4, y - h * 0.8, x + 12, y - h * 0.5, x + 12, y)
    ctx.close_path()
    _fill(ctx, "#8a6a4a")
    _stroke(ctx, lw)
    cx, cy = x + 22 + lean, y - h
    for k in range(9):
        sw = (0.05 + 0.13 * wind) * math.sin(2 * math.pi * t / (2.3 + 0.17 * k) + k * 1.1 + seed_x * 0.01)
        a = -math.pi + k * math.pi / 8 + sw
        L = h * 0.33
        droop = 30 + 12 * math.sin(t * 2.1 + k)
        ctx.new_path()
        ctx.move_to(cx, cy)
        ctx.curve_to(cx + math.cos(a) * L * 0.5, cy + math.sin(a) * L * 0.5 - 40, cx + math.cos(a) * L,
                     cy + math.sin(a) * L * 0.4, cx + math.cos(a) * L * 1.05, cy + math.sin(a) * L * 0.6 + droop)
        ctx.curve_to(cx + math.cos(a) * L * 0.8, cy + math.sin(a) * L * 0.5, cx + math.cos(a) * L * 0.4,
                     cy + math.sin(a) * L * 0.3 - 10, cx, cy + 8)
        _fill(ctx, "#3f8f3a" if k % 2 else "#357a32")
        _stroke(ctx, lw * 0.8)


def banana(ctx, x, y, h, wind=0.4, t=0.0, seed_x=0.0):
    ctx.new_path()
    ctx.rectangle(x - 9, y - h * 0.6, 18, h * 0.6)
    _fill(ctx, "#7c9a3a")
    _stroke(ctx, 3)
    for k, a0 in enumerate((-2.4, -1.9, -1.2, -0.7)):
        a = a0 + (0.04 + 0.12 * wind) * math.sin(2 * math.pi * t / (1.9 + 0.3 * k) + k + seed_x * 0.02)
        ctx.new_path()
        L = h * 0.55
        ctx.move_to(x, y - h * 0.6)
        ex, ey = x + math.cos(a) * L, y - h * 0.6 + math.sin(a) * L
        ctx.curve_to(x + math.cos(a) * L * 0.3 - 30, ey - 20, ex - 20, ey - 30, ex, ey)
        ctx.curve_to(ex + 25, ey + 25, x + math.cos(a) * L * 0.3 + 30, ey + 40, x, y - h * 0.55)
        _fill(ctx, "#5aa845" if k % 2 else "#4c9a3c")
        _stroke(ctx, 2.5)


def hut(ctx, x, y, w, h):
    from tvtoon import backgrounds as BG
    BG.hut(ctx, x, y, w, h)


def tulsi(ctx, x, y):
    from tvtoon import backgrounds as BG
    BG.tulsi(ctx, x, y)


def pot(ctx, x, y, r):
    from tvtoon import backgrounds as BG
    BG.pot(ctx, x, y, r)
