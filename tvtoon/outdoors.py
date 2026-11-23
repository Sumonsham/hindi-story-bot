"""MORE OUTDOOR WORLDS (23 Nov 2026), so every story gets its own place, not a village by default:

  market    a bazaar: striped awnings, stalls full of goods, bunting that flutters, bulbs that glow at night,
            far shoppers moving, baskets of vegetables in front
  temple    a temple courtyard: the curved tower (shikhara) with its flag in the wind, steps, a swinging bell,
            rows of diyas flickering at dusk / night, incense smoke, a big banyan swaying
  mountain  the hills (Darjeeling / Dooars): far snowy peaks, pine-covered ridges swaying, fog drifting in bands,
            a winding road with a stone parapet
  seaside   the sea (Digha / Puri): the horizon, waves rolling in with foam running up the sand and back, palms,
            a fishing boat far out
  school    a village / town school: the building with its verandah and windows, the flag on its pole, a tree,
            the hanging school bell

Each has its own parallax layers and moves by itself (wind, water, fire, fog, people far away). Time of day and
weather come from the base world (sky, sun / moon, rain, fog, tint)."""
import math
import random

from tvtoon import geom as G
from tvtoon import world as WD
from tvtoon.locations import _glow
from tvtoon.world import GROUND, WORLD_H, _fill, _stroke


def _rect(ctx, x, y, w, h, col, lw=2.5):
    ctx.new_path()
    ctx.rectangle(x, y, w, h)
    _fill(ctx, col)
    _stroke(ctx, lw)


class Outdoor(WD.World):
    def __init__(self, spec=None):
        spec = dict(spec or {})
        super().__init__(spec)
        self.kind = spec.get("kind", "market")
        self.r = random.Random(11)

    def _night(self, sun_h):
        return max(0.0, min(1.0, -sun_h / 0.35)) if sun_h < 0.2 else 0.0

    def _ground(self, ctx, col, col2):
        ctx.new_path()
        ctx.rectangle(-1000, 800, 5400, WORLD_H + 200)
        g = G.rgb(col)
        _fill(ctx, g, keep=False)
        for i in range(60):
            x = (i * 97) % 5400 - 1000
            y = 820 + (i * 53) % 300
            G.line(ctx, [(x, y), (x + 40, y + 2)], 2, G.rgb(col2), smooth_it=False)

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        getattr(self, "_" + self.kind)(ctx, W, H, cam, t, self._night(sun_h))

    def draw_fore(self, ctx, W, H, cam, t):
        """the village's grass and bushes in front only where they belong (mountain); elsewhere nothing"""
        if self.kind == "mountain":
            super().draw_fore(ctx, W, H, cam, t)

    # ------------------------------------------------------------------ market
    def _market(self, ctx, W, H, cam, t, night):
        ctx.save()                                                 # far shoppers (silhouettes) drifting
        ctx.set_matrix(self.layer_matrix(W, H, cam, 0.6))
        for i in range(18):
            x = (i * 300 + t * (30 if i % 2 else -24)) % 5400 - 1000
            ctx.new_path()
            G.ellipse(ctx, x, 640, 20, 24)
            G.ellipse(ctx, x, 700, 26, 52)
            _fill(ctx, (0.25, 0.22, 0.22) if night < 0.5 else (0.45, 0.4, 0.38), keep=False)
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.0))
        self._ground(ctx, "#8a7a64", "#6a5a48")
        cols = ["#c62828", "#1565c0", "#2e7d32", "#f9a825", "#6a1b9a"]
        for i, x in enumerate(range(-900, 4400, 620)):           # the stalls
            _rect(ctx, x, 420, 520, 380, "#6a4a2a", 3)
            for j in range(3):                                     # shelves of goods
                G.line(ctx, [(x + 20, 520 + j * 90), (x + 500, 520 + j * 90)], 5, G.rgb("#3a2614"), smooth_it=False)
                for k in range(8):
                    _rect(ctx, x + 30 + k * 58, 470 + j * 90, 44, 48, G.shade(cols[(i + j + k) % 5], 0.8 + 0.2 * ((k + j) % 2)), 1.5)
            for k in range(6):                                     # the striped awning, it lifts in the wind
                w = self.wind(t, x) * 12 * math.sin(t * 2 + i)
                ctx.new_path()
                ctx.move_to(x - 30 + k * 97, 400)
                ctx.line_to(x - 30 + (k + 1) * 97, 400)
                ctx.line_to(x - 30 + (k + 1) * 97, 460 + w)
                ctx.line_to(x - 30 + k * 97, 460 + w)
                ctx.close_path()
                _fill(ctx, cols[i % 5] if k % 2 else "#f2efe6", keep=False)
            if night > 0.2:                                        # a bare bulb over each stall
                f_ = 0.85 + 0.15 * math.sin(t * 9 + i)
                _glow(ctx, x + 260, 470, 420, "#ffd27a", 0.4 * night * f_)
                ctx.new_path()
                G.ellipse(ctx, x + 260, 472, 12, 16)
                ctx.set_source_rgba(1, 0.92, 0.6, 1)
                ctx.fill()
        pts = [(x, 330 + 30 * math.sin((x + 1000) / 5400 * math.pi * 4)) for x in range(-1000, 4401, 100)]
        G.line(ctx, pts, 3, (0.2, 0.2, 0.2))                       # bunting
        for i, (x, y) in enumerate(pts[:-1]):
            sw = 10 * math.sin(t * 4 + i)
            ctx.new_path()
            ctx.move_to(x, y)
            ctx.line_to(x + 60, y + 4)
            ctx.line_to(x + 30 + sw, y + 60)
            ctx.close_path()
            _fill(ctx, cols[i % 5], keep=False)
        ctx.restore()

    # ------------------------------------------------------------------ temple
    def _temple(self, ctx, W, H, cam, t, night):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 0.8))
        x0 = 1300                                                  # the curved tower
        ctx.new_path()
        ctx.move_to(x0, 700)
        ctx.curve_to(x0 + 30, 300, x0 + 200, 80, x0 + 300, 40)
        ctx.curve_to(x0 + 400, 80, x0 + 570, 300, x0 + 600, 700)
        ctx.close_path()
        _fill(ctx, "#c8784a")
        _stroke(ctx, 4)
        for k in range(6):
            G.line(ctx, [(x0 + 40 + k * 20, 640 - k * 90), (x0 + 560 - k * 20, 640 - k * 90)], 3, G.rgb("#8a4a2a"), smooth_it=False)
        G.line(ctx, [(x0 + 300, 40), (x0 + 300, -120)], 5, G.rgb("#5a3a1a"), smooth_it=False)
        w = self.wind(t, x0)
        ctx.new_path()                                             # the flag in the wind
        ctx.move_to(x0 + 300, -120)
        ctx.curve_to(x0 + 360, -110 + 10 * math.sin(t * 5), x0 + 420, -90 - 10 * math.sin(t * 5 + 1), x0 + 300 + 160 * (0.6 + w), -70)
        ctx.line_to(x0 + 300, -50)
        ctx.close_path()
        _fill(ctx, "#e65100", keep=False)
        _rect(ctx, x0 - 120, 700, 840, 110, "#b06a40", 3)          # the base and the door
        ctx.new_path()
        ctx.move_to(x0 + 230, 810)
        ctx.line_to(x0 + 230, 740)
        ctx.arc(x0 + 300, 740, 70, math.pi, 2 * math.pi)
        ctx.line_to(x0 + 370, 810)
        ctx.close_path()
        _fill(ctx, "#2a1a10", keep=False)
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 0.55))         # the banyan tree behind
        for k in range(6):
            sw = 10 * math.sin(t * 1.1 + k) * (0.4 + self.wind(t, 300))
            ctx.new_path()
            G.ellipse(ctx, -100 + k * 120 + sw, 380 + (k % 2) * 60, 220, 150)
            _fill(ctx, "#1e3a22" if night > 0.4 else "#3e6e3a", keep=False)
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.0))
        self._ground(ctx, "#b8a48a", "#9a8668")
        for k in range(3):                                         # the steps
            _rect(ctx, 900 - k * 60, 810 + k * 30, 1500 + k * 120, 30, "#d8cbb0", 2)
        G.line(ctx, [(2500, 380), (2500, 520)], 4, G.rgb("#3a3a3a"), smooth_it=False)
        a = 0.25 * math.sin(t * 2.2)                               # the bell swings
        bx, by = 2500 + math.sin(a) * 140, 520 + math.cos(a) * 30
        ctx.new_path()
        ctx.move_to(bx - 36, by + 60)
        ctx.curve_to(bx - 30, by - 10, bx + 30, by - 10, bx + 36, by + 60)
        ctx.close_path()
        _fill(ctx, "#c9a227")
        _stroke(ctx, 2.5)
        if night > 0.1 or True:                                    # rows of diyas
            for i in range(14):
                x = 700 + i * 140
                f_ = 0.7 + 0.3 * math.sin(t * 11 + i * 1.7)
                _glow(ctx, x, 800, 120, "#ffb347", (0.25 + 0.45 * night) * f_)
                ctx.new_path()
                G.ellipse(ctx, x, 812, 18, 7)
                _fill(ctx, "#8a4a2a", keep=False)
                ctx.new_path()
                G.ellipse(ctx, x, 798, 5, 10 * f_)
                ctx.set_source_rgba(1, 0.8, 0.3, 0.95)
                ctx.fill()
        for i in range(4):                                         # incense smoke
            u = (t * 0.2 + i / 4) % 1.0
            ctx.new_path()
            G.ellipse(ctx, 3000 + 30 * math.sin(u * 8), 760 - u * 400, 12 + 40 * u, 18 + 30 * u)
            ctx.set_source_rgba(0.85, 0.85, 0.85, 0.3 * (1 - u))
            ctx.fill()
        ctx.restore()

    # ------------------------------------------------------------------ mountain
    def _mountain(self, ctx, W, H, cam, t, night):
        for p, base, amp, col, snow in ((0.1, 520, 260, "#8aa0b8", True), (0.35, 650, 160, "#3e6a54", False),
                                        (0.6, 760, 90, "#2e5440", False)):
            ctx.save()
            ctx.set_matrix(self.layer_matrix(W, H, cam, p))
            pts = [(x, base - amp * abs(math.sin(x * 0.0021 + p * 7)) - amp * 0.3 * math.sin(x * 0.007)) for x in range(-1000, 4401, 80)]
            ctx.new_path()
            G.smooth(ctx, [(-1000, 1100)] + pts + [(4400, 1100)], tension=0.35)
            _fill(ctx, G.shade(col, 0.5) if night > 0.4 else col, keep=False)
            if snow:
                for x, y in pts:
                    if y < base - amp * 0.75:
                        ctx.new_path()
                        G.ellipse(ctx, x, y + 14, 50, 18)
                        _fill(ctx, "#eef2f6" if night < 0.4 else "#9aa4b0", keep=False)
            else:                                                  # pines swaying
                for i, (x, y) in enumerate(pts[::2]):
                    sw = 6 * math.sin(t * 1.3 + i) * (0.4 + self.wind(t, x))
                    ctx.new_path()
                    ctx.move_to(x - 26, y + 30)
                    ctx.line_to(x + sw, y - 70)
                    ctx.line_to(x + 26, y + 30)
                    ctx.close_path()
                    _fill(ctx, G.shade(col, 0.7), keep=False)
            ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.0))
        self._ground(ctx, "#6a6a62", "#4e4e48")                    # the road and its stone parapet
        for x in range(-1000, 4400, 160):
            _rect(ctx, x, 740, 120, 60, "#9a9488", 2)
        ctx.restore()
        ctx.save()                                                 # fog bands drifting
        ctx.identity_matrix()
        for i in range(3):
            y = H * (0.45 + 0.12 * i)
            x = (t * (20 + 10 * i) + i * 400) % (W + 800) - 400
            ctx.new_path()
            G.ellipse(ctx, x, y, W * 0.5, H * 0.06)
            ctx.set_source_rgba(0.85, 0.88, 0.9, 0.22)
            ctx.fill()
        ctx.restore()

    # ------------------------------------------------------------------ seaside
    def _seaside(self, ctx, W, H, cam, t, night):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 0.15))
        ctx.new_path()
        ctx.rectangle(-1000, 560, 5400, 600)
        _fill(ctx, "#1a2e44" if night > 0.4 else "#2a7ab0", keep=False)
        bx = 1600 + 200 * math.sin(t * 0.1)                        # a fishing boat far out
        ctx.new_path()
        ctx.move_to(bx - 60, 560)
        ctx.line_to(bx + 60, 560)
        ctx.line_to(bx + 40, 578)
        ctx.line_to(bx - 40, 578)
        ctx.close_path()
        _fill(ctx, "#2a1a10", keep=False)
        G.line(ctx, [(bx, 560), (bx, 500)], 3, (0.2, 0.15, 0.1), smooth_it=False)
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.0))
        ctx.new_path()                                             # the sand
        ctx.rectangle(-1000, 760, 5400, WORLD_H + 200)
        _fill(ctx, "#9a8a6a" if night > 0.4 else "#e6d3a3", keep=False)
        for i in range(3):                                         # waves rolling in, foam running up and back
            u = (t * 0.18 + i / 3) % 1.0
            y = 640 + u * 150
            pts = [(x, y + 10 * math.sin(x * 0.01 + t * 1.5 + i)) for x in range(-1000, 4401, 80)]
            ctx.new_path()
            G.smooth(ctx, [(-1000, 600)] + pts + [(4400, 600)], tension=0.4)
            ctx.set_source_rgba(*(G.rgb("#24486a") if night > 0.4 else G.rgb("#3a8ac0")), 0.8 * (1 - u))
            ctx.fill()
            G.line(ctx, pts, 6, (0.95, 0.97, 1.0), smooth_it=False)
        for i, x in enumerate((-600, 3500)):                       # palms
            sw = 20 * math.sin(t * 1.0 + i) * (0.5 + self.wind(t, x))
            WD.palm(ctx, x, 800, 520, self.wind(t, x), t, x) if hasattr(WD, "palm") else None
        ctx.restore()

    # ------------------------------------------------------------------ school
    def _school(self, ctx, W, H, cam, t, night):
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 0.8))
        _rect(ctx, 200, 360, 2600, 440, "#e0c890", 4)              # the building
        _rect(ctx, 150, 330, 2700, 40, "#b84a2a", 3)
        for i in range(8):                                         # windows / doors on the verandah
            x = 300 + i * 310
            _rect(ctx, x, 470, 180, 210 if i % 3 else 330, "#4a3a22" if night < 0.4 else "#1a140c", 3)
            if night > 0.3 and i % 3 == 1:
                _glow(ctx, x + 90, 560, 200, "#ffd27a", 0.3)
        for x in range(260, 2800, 310):                             # verandah pillars
            _rect(ctx, x, 380, 26, 420, "#f2e6c8", 2)
        ctx.restore()
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.0))
        self._ground(ctx, "#b89a6a", "#9a7e52")
        G.line(ctx, [(3300, 860), (3300, 160)], 8, G.rgb("#7a7a7a"), smooth_it=False)   # the flag waves
        for k in range(3):
            pts = [(3300 + x, 180 + k * 50 + 10 * math.sin(t * 4 + x * 0.02)) for x in range(0, 300, 30)]
            ctx.new_path()
            ctx.move_to(*pts[0])
            for p in pts[1:]:
                ctx.line_to(*p)
            for p in reversed(pts):
                ctx.line_to(p[0], p[1] + 50)
            ctx.close_path()
            _fill(ctx, ["#ff9933", "#ffffff", "#138808"][k], keep=False)
        ctx.new_path()
        ctx.arc(3450, 230, 18, 0, 2 * math.pi)
        _stroke(ctx, 3, (0.0, 0.0, 0.5))
        a = 0.2 * math.sin(t * 1.7)                                 # the school bell (a brass plate)
        G.line(ctx, [(-400, 300), (-400 + math.sin(a) * 120, 300 + math.cos(a) * 120)], 3, (0.2, 0.2, 0.2), smooth_it=False)
        ctx.new_path()
        G.ellipse(ctx, -400 + math.sin(a) * 140, 300 + math.cos(a) * 140, 50, 12)
        _fill(ctx, "#c9a227")
        _stroke(ctx, 2)
        ctx.restore()


KINDS = ("market", "temple", "mountain", "seaside", "school")
NAMES_BN = {"market": "বাজার", "temple": "মন্দির চত্বর", "mountain": "পাহাড়", "seaside": "সমুদ্রের ধার", "school": "স্কুল"}


def register(locations, names_bn):
    for k in KINDS:
        locations[k] = (lambda kind: (lambda spec=None: Outdoor(dict(spec or {}, kind=kind))))(k)
        names_bn[k] = NAMES_BN[k]
