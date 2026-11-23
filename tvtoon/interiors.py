"""INSIDE A MOVING VEHICLE (23 Nov 2026): a train compartment, a bus and a Kolkata tram, seen from inside.

Cinematic rules used here:
  * the world outside the windows really passes by - three depths at three speeds (far fields / skyline slow,
    trees / houses quicker, poles and lamp posts flashing past); at night: darkness, a few far lights, the light of
    poles and platforms sweeping across the compartment;
  * the carriage moves: a sway, the rhythm of the rails (train), bumps (bus), the clack of the tram; the camera
    shares this motion (World.shake);
  * the inside lives: fans turn, hanging straps swing with the motion, tube lights hum and can flicker or go out
    (spec 'flicker': [[t0, t1], ...] - the horror moment);
  * passengers sit on the benches against the window wall (the scene's 'sit' beat with 'prop': false).
"""
import math
import random

import cairo

from tvtoon import geom as G
from tvtoon import world as WD
from tvtoon.locations import _glow
from tvtoon.world import GROUND, WORLD_H, _fill, _mix, _stroke


class RideInterior(WD.World):
    KIND = "train"
    SPEED = 900.0
    WIN = dict(y0=330, y1=600, w=330, step=520, x0=-800)
    WALL = "#7fa7a0"
    SEAT = "#2f5f8a"
    SEAT_TOP = 770

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 21.5]])
        super().__init__(spec)
        self.speed = float(spec.get("speed", self.SPEED))
        self.outside = spec.get("outside", "village")
        self.flicker = spec.get("flicker", [])
        r = random.Random(7)
        self.far_lights = [(r.uniform(0, 6000), r.uniform(430, 560)) for _ in range(18)]

    # ------------------------------------------------------------------ motion of the carriage (the camera shares it)
    def shake(self, t):
        if self.KIND == "train":
            bump = math.exp(-((t % 0.47) / 0.05) ** 2) * 4.0          # da-dum ... da-dum of the rail joints
            return 1.5 * math.sin(2 * math.pi * 0.7 * t), 2.2 * math.sin(2 * math.pi * 1.3 * t) + bump
        if self.KIND == "bus":
            b = 7.0 * math.exp(-((t % 2.3) / 0.12) ** 2) + 4.0 * math.exp(-(((t + 1.1) % 3.1) / 0.1) ** 2)
            return 2.5 * math.sin(2 * math.pi * 0.45 * t), 3.0 * math.sin(2 * math.pi * 1.9 * t) + b
        clack = math.exp(-((t % 0.8) / 0.06) ** 2) * 2.5
        return 1.0 * math.sin(2 * math.pi * 0.5 * t), 1.6 * math.sin(2 * math.pi * 1.1 * t) + clack

    def dark(self, t):
        """0 = lights on, 1 = lights out (flicker windows)"""
        for t0, t1 in self.flicker:
            if t0 <= t <= t1:
                u = (t - t0) / max(0.1, t1 - t0)
                return 1.0 if 0.25 < u < 0.8 else (0.5 + 0.5 * math.sin(t * 55)) ** 2
        return 0.0

    def windows(self):
        w = self.WIN
        return [(x, w["y0"], w["w"], w["y1"] - w["y0"]) for x in range(w["x0"], 4400, w["step"])]

    # ------------------------------------------------------------------ the world outside, passing
    def _outside(self, ctx, W, H, cam, t, top, sun_h):
        night = max(0.0, min(1.0, -sun_h / 0.35))
        layers = [(0.12, "far"), (0.45, "mid"), (1.6, "near")]
        for p, kind in layers:
            ctx.save()
            m = self.layer_matrix(W, H, cam, min(1.0, p))
            ctx.set_matrix(m)
            off = self.speed * t * p
            if kind == "far":
                if self.outside == "city":
                    for i in range(-2, 40):
                        x = i * 160 - (off % 160)
                        h = 120 + (i * 37 % 90)
                        ctx.new_path()
                        ctx.rectangle(x, 600 - h, 150, h + 40)
                        _fill(ctx, _mix(G.rgb("#3a4050"), top, 0.35), keep=False)
                        if night > 0.2 and i % 2:
                            ctx.new_path()
                            ctx.rectangle(x + 40, 600 - h + 30, 14, 18)
                            ctx.set_source_rgba(1, 0.85, 0.45, 0.8 * night)
                            ctx.fill()
                else:
                    ctx.new_path()
                    pts = [(x - (off % 600), 560 + 25 * math.sin((x + (off // 600) * 600) / 180.0)) for x in range(-1200, 5000, 120)]
                    G.smooth(ctx, [(-1200, 640)] + pts + [(5000, 640)], tension=0.4)
                    _fill(ctx, _mix(G.rgb("#5f8f52"), top, 0.25 + 0.6 * night), keep=False)
                    for lx, ly in self.far_lights:                  # far village lights at night
                        if night > 0.3:
                            x = (lx - off * 0.6) % 6000 - 1000
                            _glow(ctx, x, ly, 14, "#ffd27a", 0.8 * night)
            elif kind == "mid":
                period = 700 if self.outside != "city" else 420
                for i in range(-2, 12):
                    x = i * period - (off % period)
                    if self.outside == "city":
                        ctx.new_path()
                        ctx.rectangle(x, 380, period - 30, 300)
                        _fill(ctx, ["#b98a6a", "#c9a85a", "#8fa3a0"][i % 3] if night < 0.5 else "#2a2e38", keep=False)
                        for k in range(3):
                            ctx.new_path()
                            ctx.rectangle(x + 30 + k * 120, 420, 60, 70)
                            if night > 0.3 and (i + k) % 2:
                                ctx.set_source_rgba(1, 0.85, 0.45, 0.85)
                            else:
                                ctx.set_source_rgb(0.2, 0.22, 0.25)
                            ctx.fill()
                    else:
                        col = _mix(G.rgb("#2f6a30"), (0.03, 0.05, 0.08), night * 0.85)
                        ctx.new_path()
                        ctx.rectangle(x + 100, 470, 18, 160)
                        _fill(ctx, _mix(G.rgb("#5a4030"), (0.04, 0.04, 0.05), night * 0.85), keep=False)
                        ctx.new_path()
                        G.ellipse(ctx, x + 110, 450, 120, 80)
                        _fill(ctx, col, keep=False)
                        ctx.new_path()
                        G.ellipse(ctx, x + 400, 520, 70, 50)
                        _fill(ctx, col, keep=False)
            else:                                                     # poles / lamp posts flashing past
                period = 900
                for i in range(-2, 10):
                    x = i * period - (off % period)
                    ctx.new_path()
                    ctx.rectangle(x, 250, 26, 500)
                    _fill(ctx, (0.08, 0.08, 0.09) if night > 0.3 else (0.35, 0.33, 0.3), keep=False)
                    if night > 0.3 and self.outside == "city":
                        _glow(ctx, x + 13, 260, 120, "#ffe9a0", 0.6 * night)
            ctx.restore()

    # ------------------------------------------------------------------ the inside
    def static_layer(self, name, ctx):
        if name != "shell":
            return False
        ctx.new_path()
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.rectangle(-1000, -200, 5400, 1062)
        for x, y, w, h in self.windows():
            ctx.rectangle(x, y, w, h)
        g = cairo.LinearGradient(0, -200, 0, 860)
        g.add_color_stop_rgb(0, *G.shade(self.WALL, 0.7))
        g.add_color_stop_rgb(1, *G.rgb(self.WALL))
        ctx.set_source(g)
        ctx.fill()
        ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
        for x, y, w, h in self.windows():                           # frames and bars
            ctx.new_path()
            ctx.rectangle(x, y, w, h)
            _stroke(ctx, 6, (0.2, 0.18, 0.16))
            if self.KIND == "train":
                for k in range(1, 5):
                    G.line(ctx, [(x, y + h * k / 5), (x + w, y + h * k / 5)], 4, (0.55, 0.57, 0.58), smooth_it=False)
            else:
                G.line(ctx, [(x, y + h * 0.5), (x + w, y + h * 0.5)], 5, (0.5, 0.5, 0.5), smooth_it=False)
        if self.KIND == "train":                                     # the luggage rack
            ctx.new_path()
            ctx.rectangle(-1000, 230, 5400, 16)
            _fill(ctx, "#8a8a86", keep=False)
            for x in range(-1000, 4400, 40):
                G.line(ctx, [(x, 246), (x, 280)], 2, (0.55, 0.55, 0.52), smooth_it=False)
            G.line(ctx, [(-1000, 280), (4400, 280)], 4, (0.55, 0.55, 0.52), smooth_it=False)
        ctx.new_path()                                               # the panelled wall under the windows
        ctx.rectangle(-1000, 640, 5400, 860 - 640)
        _fill(ctx, G.shade(self.WALL, 0.78))
        _stroke(ctx, 3)
        for x in range(-1000, 4400, 260 if self.KIND != "tram" else 120):
            G.line(ctx, [(x, 640), (x, 860)], 3, G.shade(self.WALL, 0.6), smooth_it=False)
        G.line(ctx, [(-1000, 700), (4400, 700)], 4, G.shade(self.WALL, 0.6), smooth_it=False)
        # (the seats themselves are drawn per passenger by the scene: a seat that faces the way the passenger sits,
        #  with its backrest behind the passenger's back - compartments seen from the aisle)
        ctx.new_path()                                               # the floor
        ctx.rectangle(-1000, 860, 5400, WORLD_H + 200)
        _fill(ctx, "#5a5650" if self.KIND != "tram" else "#6a5034", keep=False)
        for x in range(-1000, 4400, 140):
            G.line(ctx, [(x, 860), (x - 90, WORLD_H + 200)], 2, (0.3, 0.28, 0.25), smooth_it=False)
        return True

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        self._outside(ctx, W, H, cam, t, top, sun_h)
        self._blit(ctx, "shell", W, H, cam, p=1.0)
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.0))
        ctx.new_path()                                               # the ceiling
        ctx.rectangle(-2000, -3000, 7000, 3001)
        _fill(ctx, G.shade(self.WALL, 0.55), keep=False)
        dk = self.dark(t)
        for i, x in enumerate(range(-600, 4400, 900)):               # tube lights
            ctx.new_path()
            ctx.rectangle(x, -120, 260, 22)
            on = (1.0 - dk) * (0.93 + 0.07 * math.sin(t * 50 + i))
            ctx.set_source_rgba(0.95, 0.98, 1.0, 0.3 + 0.7 * on)
            ctx.fill()
            if on > 0.2:
                _glow(ctx, x + 130, -100, 520, "#eaf4ff", 0.22 * on)
        if self.KIND == "train":                                      # caged ceiling fans
            for i, x in enumerate(range(-150, 4400, 900)):
                ctx.new_path()
                ctx.arc(x, -40, 70, 0, 2 * math.pi)
                _stroke(ctx, 3, (0.3, 0.3, 0.3))
                a = t * (9.0 if dk < 0.5 else 2.0) + i
                for k in range(3):
                    b = a + k * 2 * math.pi / 3
                    G.line(ctx, [(x, -40), (x + math.cos(b) * 62, -40 + math.sin(b) * 62)], 9, (0.4, 0.42, 0.44), smooth_it=False)
        else:                                                         # a rail with hanging straps that swing
            G.line(ctx, [(-1000, 120), (4400, 120)], 8, (0.65, 0.65, 0.62), smooth_it=False)
            sx, sy = self.shake(t)
            for i, x in enumerate(range(-900, 4400, 180)):
                ang = 0.18 * math.sin(2 * math.pi * 0.9 * t + i * 0.4) + 0.02 * sy
                ex, ey = x + math.sin(ang) * 120, 120 + math.cos(ang) * 120
                G.line(ctx, [(x, 120), (ex, ey)], 5, (0.25, 0.2, 0.16), smooth_it=False)
                ctx.new_path()
                ctx.arc(ex, ey + 20, 22, 0, 2 * math.pi)
                _stroke(ctx, 7, (0.25, 0.2, 0.16))
        ctx.restore()

    def draw_weather(self, ctx, W, H, cam, t, tint):
        """inside, the carriage's own lamps light the people: the night tint of the hour is only a trace (the windows
        are dark by themselves); when the lamps fail the blackout in draw_fore takes over"""
        r, g, b, a = tint
        super().draw_weather(ctx, W, H, cam, t, (r, g, b, a * 0.22))

    def draw_fore(self, ctx, W, H, cam, t):
        night = max(0.0, min(1.0, -WD.tod_palette(self.hour(t))[3] / 0.35))
        ctx.save()
        ctx.identity_matrix()
        if night > 0.2:                                               # lights outside sweep across the inside
            period = 2.6 if self.outside != "city" else 1.4
            u = (t % period) / period
            x = W * (1.3 - 1.8 * u)
            g = cairo.LinearGradient(x - W * 0.15, 0, x + W * 0.15, 0)
            g.add_color_stop_rgba(0, 1, 0.9, 0.7, 0.0)
            g.add_color_stop_rgba(0.5, 1, 0.9, 0.7, 0.16 * night)
            g.add_color_stop_rgba(1, 1, 0.9, 0.7, 0.0)
            ctx.set_source(g)
            ctx.paint()
        dk = self.dark(t)
        if dk > 0:                                                    # the lights go out: almost black
            ctx.set_source_rgba(0.0, 0.0, 0.03, 0.82 * dk)
            ctx.paint()
        ctx.restore()


class TrainInside(RideInterior):
    KIND, SPEED, WALL, SEAT, SEAT_TOP = "train", 950.0, "#7fa7a0", "#2f5f8a", 770
    WIN = dict(y0=330, y1=600, w=330, step=520, x0=-800)


class BusInside(RideInterior):
    KIND, SPEED, WALL, SEAT, SEAT_TOP = "bus", 520.0, "#c9b48a", "#8a2a2a", 770
    WIN = dict(y0=290, y1=610, w=420, step=520, x0=-800)


class TramInside(RideInterior):
    KIND, SPEED, WALL, SEAT, SEAT_TOP = "tram", 300.0, "#9aa88a", "#8a6a3a", 770
    WIN = dict(y0=300, y1=600, w=300, step=400, x0=-800)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("outside", "city")
        super().__init__(spec)


INTERIORS = {"train_inside": TrainInside, "bus_inside": BusInside, "tram_inside": TramInside}
NAMES_BN = {"train_inside": "ট্রেনের কামরা", "bus_inside": "বাসের ভেতর", "tram_inside": "ট্রামের ভেতর"}
