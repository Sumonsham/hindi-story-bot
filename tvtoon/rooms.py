"""MANY KINDS OF ROOM, AND THE BOAT (23 Nov 2026). The owner saw that every indoor scene was the same bedroom: "it
must change with the story". A story's place text now chooses one of these, and each changes again with the time of
day, the weather and the text itself (wall colour, which side the window is, a lit or a dead lamp):

  bedroom   the old village / quarter bedroom: cot with a mosquito net, shelf, hurricane lantern, ceiling fan
  kitchen   clay stove (chula) with glowing embers and smoke, pots and pans on a shelf, sacks, a small window
  hall      a palace / zamindar hall: pillars, arches, chequered floor, portraits, a chandelier with flickering candles
  hospital  a ward: green walls, iron beds with white sheets, a drip stand, a humming tube light that flickers
  office    a study / office: desk, chair, a table lamp's pool of light, a tall bookshelf, files, a wall clock
  studio    a radio / recording room: a desk with a microphone, a console with blinking lights, an on-air lamp
  corridor  a long passage: doors one after another, bare bulbs hanging and swinging, one of them flickering
  shed      a tool shed / store: plank walls with light through the gaps, tools on hooks, sacks, cobwebs
  flat      a Kolkata flat: plain painted walls, sofa, television, a framed picture, the city's windows outside
  hold      inside a boat: curved planks, low beams, water sloshing on the floor, a swinging lantern; it rocks
  palki     inside a palanquin: wooden slats close around, stripes of light moving, a curtain swaying; it sways
  boat      ON a country boat on a big river: waves in three depths, the far bank's mangroves, the bamboo canopy,
            a swinging lantern, rain and lightning in a storm; the deck rocks and the camera rocks with it

Every room keeps the bedroom's living parts where they fit (the door that can open, the lamp that can die, the
curtain in the wind) so a story's horror moments work in any room."""
import math
import random
import zlib

import cairo

from tvtoon import geom as G
from tvtoon import world as WD
from tvtoon.locations import GharRoom, _glow
from tvtoon.world import WORLD_H, _fill, _stroke

WALLS = {   # kind -> wall colours to choose from (by the place text)
    "bedroom": ["#b9a98a", "#a9b4a0", "#c2a98e", "#9fb0b8"],
    "kitchen": ["#a08a6a", "#9a8064", "#a89878"],
    "hall": ["#9a8a70", "#8a7e6e", "#a39070"],
    "hospital": ["#9fbfa8", "#a8c0c0", "#b0c4a8"],
    "office": ["#b8a88a", "#a89c86", "#9aa49a"],
    "studio": ["#5a5a66", "#4e5662", "#5e5650"],
    "corridor": ["#a89c80", "#9aa49a", "#b0a48a"],
    "shed": ["#6a5438", "#5e4a32", "#72583a"],
    "flat": ["#d8d0c0", "#c8d0d4", "#d4c4b0", "#c0c8b8"],
    "hold": ["#5a4026", "#4e3820", "#62462a"],
    "palki": ["#6a2a1e", "#5a3a22", "#7a3020"],
    "classroom": ["#c8c09a", "#b8c4a8", "#d0c4a0"],
}
FLOORS = {"bedroom": "#6e5a44", "kitchen": "#6a5640", "hall": None, "hospital": "#8a8e88", "office": "#6a5038",
          "studio": "#3a3a40", "corridor": "#7a7466", "shed": "#4e3e2a", "flat": "#9a8a72", "hold": "#3e2c1a",
          "palki": "#4a2a18", "classroom": "#7a6a52"}


def _rect(ctx, x, y, w, h, col, lw=2.5):
    ctx.new_path()
    ctx.rectangle(x, y, w, h)
    _fill(ctx, col)
    _stroke(ctx, lw)


class Room(GharRoom):
    """an interior chosen by spec['kind'] (see the module text)"""

    def __init__(self, spec=None):
        spec = dict(spec or {})
        super().__init__(spec)
        self.kind = spec.get("kind", "bedroom")
        seed = zlib.crc32(str(spec.get("text", self.kind)).encode()) % 1000
        self.rng = random.Random(seed)
        self.wall = spec.get("wall") or self.rng.choice(WALLS.get(self.kind, WALLS["bedroom"]))
        if self.rng.random() < 0.5 and self.kind not in ("corridor", "palki", "hold"):   # window / door swap sides
            self.win, self.door = (2200, 330, 360, 330), (500, 230, 300, 630)
        if self.kind == "kitchen":
            self.win = (self.win[0], 380, 260, 200)
        if self.kind in ("hall",):
            self.win = (self.win[0] - 40, 170, 360, 520)
        self.fan = spec.get("fan", self.kind in ("bedroom", "office", "hospital", "flat", "classroom"))
        self.lamp_x = {"bedroom": 1700, "kitchen": 1600, "office": 1320, "studio": 1450, "shed": 2600, "hold": 1600}.get(self.kind, 1700)

    # ------------------------------------------------------------------ motion (a boat, a palanquin rock)
    def shake(self, t):
        if self.kind == "hold":
            return 3.0 * math.sin(2 * math.pi * t / 3.1), 6.0 * math.sin(2 * math.pi * t / 2.3)
        if self.kind == "palki":                     # carried: the bearers' steps
            return 4.0 * math.sin(2 * math.pi * t / 1.6), 5.0 * abs(math.sin(2 * math.pi * t / 0.8))
        return 0.0, 0.0

    # ------------------------------------------------------------------ the still parts
    def static_layer(self, name, ctx):
        if name != "room":
            return False
        if self.kind == "bedroom":
            return super().static_layer(name, ctx)
        k = self.kind
        wx, wy, ww, wh = self.win
        dx, dy, dw, dh = self.door
        holes = [] if k in ("corridor", "palki", "hold", "studio") else [self.win]
        if k not in ("palki", "hold"):
            holes.append(self.door)
        ctx.new_path()
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.rectangle(-1000, -400, 5400, 1260)
        for h_ in holes:
            ctx.rectangle(*h_)
        g = cairo.LinearGradient(0, -400, 0, 860)
        g.add_color_stop_rgb(0, *G.shade(self.wall, 0.72))
        g.add_color_stop_rgb(1, *G.rgb(self.wall))
        ctx.set_source(g)
        ctx.fill()
        ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
        if k in ("hospital", "corridor", "kitchen"):             # a darker lower wall (dado)
            ctx.new_path()
            ctx.rectangle(-1000, 600, 5400, 260)
            for h_ in holes:
                if h_[1] + h_[3] > 600:
                    ctx.rectangle(h_[0] + h_[2], 600, -h_[2], 260)
            ctx.set_source_rgba(*G.shade(self.wall, 0.72), 1.0)
            ctx.fill()
            G.line(ctx, [(-1000, 600), (4400, 600)], 4, G.shade(self.wall, 0.55), smooth_it=False)
        if k in ("shed", "hold", "palki"):                        # planks / slats
            step = 70 if k != "palki" else 110
            for x in range(-1000, 4400, step):
                G.line(ctx, [(x, -400), (x + (12 if k == "hold" else 0), 860)], 3, G.shade(self.wall, 0.6), smooth_it=False)
        if k == "studio":                                         # acoustic panels
            for x in range(-1000, 4400, 260):
                for y in range(-300, 600, 260):
                    _rect(ctx, x + 12, y + 12, 236, 236, G.shade(self.wall, 1.12), 1.5)
        for k2 in range(6):                                       # damp / age marks
            r = random.Random(k2 + 70 + len(self.wall))
            ctx.new_path()
            G.ellipse(ctx, r.uniform(-500, 3800), r.uniform(0, 700), r.uniform(70, 190), r.uniform(40, 110))
            ctx.set_source_rgba(0.25, 0.2, 0.15, 0.14 if k not in ("flat", "studio", "hospital") else 0.05)
            ctx.fill()
        for x0, y0, w0, h0 in holes:                               # frames
            ctx.new_path()
            ctx.rectangle(x0 - 14, y0 - 14, w0 + 28, h0 + 28)
            ctx.rectangle(x0, y0, w0, h0)
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            _fill(ctx, "#5a3a22" if k not in ("flat", "hospital", "office") else "#e8e4dc")
            _stroke(ctx, 3)
            ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
        if self.win in holes and k not in ("flat",):
            for kk in range(1, 4):
                G.line(ctx, [(wx + ww * kk / 4, wy), (wx + ww * kk / 4, wy + wh)], 6, G.rgb("#3a2a1a"), smooth_it=False)
        # the floor
        ctx.new_path()
        ctx.rectangle(-1000, 860, 5400, WORLD_H + 200)
        if k == "hall":                                           # chequered marble
            _fill(ctx, "#e8e4d8", keep=False)
            for i, x in enumerate(range(-1000, 4400, 120)):
                for j, y in enumerate(range(860, WORLD_H + 200, 60)):
                    if (i + j) % 2:
                        ctx.new_path()
                        ctx.rectangle(x, y, 120, 60)
                        _fill(ctx, "#2a2a2e", keep=False)
        else:
            _fill(ctx, FLOORS.get(k, "#6e5a44"), keep=False)
            if k in ("hospital", "corridor", "flat", "studio"):
                for x in range(-1000, 4400, 160):
                    G.line(ctx, [(x, 860), (x - 60, WORLD_H + 200)], 2, (0.3, 0.3, 0.3), smooth_it=False)
            if k in ("hold", "shed", "office"):
                for y in range(880, WORLD_H + 200, 40):
                    G.line(ctx, [(-1000, y), (4400, y)], 2, (0.2, 0.14, 0.08), smooth_it=False)
        G.line(ctx, [(-1000, 860), (4400, 860)], 5, G.rgb("#3a2a1a"), smooth_it=False)
        getattr(self, "_furnish_" + k, lambda c: None)(ctx)
        return True

    # furniture per kind (behind the people; the people stand in front at y ~960)
    def _furnish_kitchen(self, ctx):
        cx = self.lamp_x
        ctx.new_path()                                            # the clay stove (chula)
        G.smooth(ctx, [(cx - 170, 860), (cx - 150, 720), (cx + 150, 720), (cx + 170, 860)], tension=0.2)
        _fill(ctx, "#8a5a3a")
        _stroke(ctx, 3)
        ctx.new_path()
        G.ellipse(ctx, cx, 800, 60, 42)
        _fill(ctx, "#1a0e08", keep=False)
        _rect(ctx, cx - 90, 690, 180, 34, "#3a3a3a")              # an iron wok on it
        _rect(ctx, 820, 470, 520, 18, "#5a3a22")                  # the pot shelf
        for i in range(6):
            ctx.new_path()
            G.ellipse(ctx, 860 + i * 85, 440, 34, 30)
            _fill(ctx, ["#b0703a", "#8a8a8a", "#c08040"][i % 3])
            _stroke(ctx, 2)
        for i in range(3):                                        # sacks of rice
            ctx.new_path()
            G.smooth(ctx, [(-200 + i * 150, 860), (-210 + i * 150, 740), (-140 + i * 150, 700), (-80 + i * 150, 740), (-90 + i * 150, 860)])
            _fill(ctx, "#c8b48a")
            _stroke(ctx, 2)

    def _furnish_hall(self, ctx):
        for px in (-520, 820, 2420, 3700):                        # pillars and arches
            _rect(ctx, px, -400, 150, 1260, G.shade(self.wall, 1.15), 3)
            _rect(ctx, px - 25, 780, 200, 80, G.shade(self.wall, 0.85), 3)
            _rect(ctx, px - 25, 40, 200, 50, G.shade(self.wall, 0.85), 3)
        for a, b in ((-370, 820), (970, 2420), (2570, 3700)):
            ctx.new_path()
            ctx.arc((a + b) / 2, 90, (b - a) / 2, math.pi, 2 * math.pi)
            _stroke(ctx, 10, G.shade(self.wall, 0.8))
        for i, x in enumerate((1250, 1850)):                      # ancestors' portraits
            _rect(ctx, x, 260, 230, 300, "#7a5a1a", 4)
            _rect(ctx, x + 20, 280, 190, 260, ["#3a3028", "#2e2a30"][i], 2)
            ctx.new_path()
            G.ellipse(ctx, x + 115, 370, 50, 62)
            _fill(ctx, "#8a6a50", keep=False)
            ctx.new_path()
            G.ellipse(ctx, x + 115, 500, 90, 60)
            _fill(ctx, "#2a2222", keep=False)

    def _furnish_hospital(self, ctx):
        for bx in (-350, 2650, 3450):                             # iron beds with white sheets
            G.line(ctx, [(bx, 860), (bx, 640)], 8, G.rgb("#6a7074"), smooth_it=False)
            G.line(ctx, [(bx + 520, 860), (bx + 520, 700)], 8, G.rgb("#6a7074"), smooth_it=False)
            _rect(ctx, bx, 720, 520, 60, "#f2f2ee", 2.5)
            ctx.new_path()
            G.ellipse(ctx, bx + 80, 712, 70, 22)
            _fill(ctx, "#ffffff")
            _stroke(ctx, 2)
        G.line(ctx, [(2500, 860), (2500, 420)], 6, G.rgb("#8a8e90"), smooth_it=False)   # the drip stand
        G.line(ctx, [(2440, 420), (2560, 420)], 6, G.rgb("#8a8e90"), smooth_it=False)
        ctx.new_path()
        G.ellipse(ctx, 2545, 470, 26, 42)
        ctx.set_source_rgba(0.85, 0.92, 0.95, 0.85)
        ctx.fill_preserve()
        _stroke(ctx, 2)

    def _furnish_office(self, ctx):
        x = self.lamp_x
        _rect(ctx, x - 300, 700, 600, 30, "#5a3a22", 3)           # the desk
        _rect(ctx, x - 280, 730, 160, 130, "#4a2e1a", 2)
        _rect(ctx, x + 120, 730, 160, 130, "#4a2e1a", 2)
        for i in range(4):                                        # files
            _rect(ctx, x - 240 + i * 26, 640 - i * 4, 22, 60 + i * 4, ["#c8b060", "#8a3a2a", "#3a5a7a"][i % 3], 1.5)
        _rect(ctx, 2500, 220, 420, 640, "#5a3a22", 3)             # a tall bookshelf
        for j in range(4):
            G.line(ctx, [(2500, 360 + j * 130), (2920, 360 + j * 130)], 5, G.rgb("#3a2414"), smooth_it=False)
            for i in range(10):
                _rect(ctx, 2515 + i * 40, 260 + j * 130, 32, 96 - (i % 3) * 10, ["#7a2a22", "#2a4a5a", "#5a5a2a", "#3a2a4a"][(i + j) % 4], 1)
        ctx.new_path()                                            # the wall clock
        ctx.arc(1050, 200, 70, 0, 2 * math.pi)
        _fill(ctx, "#f0ece0")
        _stroke(ctx, 4)
        G.line(ctx, [(1050, 200), (1050, 150)], 4, (0.1, 0.1, 0.1), smooth_it=False)
        G.line(ctx, [(1050, 200), (1090, 215)], 4, (0.1, 0.1, 0.1), smooth_it=False)

    def _furnish_studio(self, ctx):
        x = self.lamp_x
        _rect(ctx, x - 380, 690, 760, 36, "#2a2a30", 3)           # desk
        _rect(ctx, x - 340, 600, 380, 90, "#3a3a44", 2.5)         # the console
        G.line(ctx, [(x + 160, 690), (x + 160, 560), (x + 110, 520)], 6, G.rgb("#202020"))   # the microphone stand
        ctx.new_path()
        G.ellipse(ctx, x + 100, 505, 34, 46)
        _fill(ctx, "#3a3a3a")
        _stroke(ctx, 2.5)
        _rect(ctx, 2600, 120, 260, 90, "#3a1010", 3)              # the on-air lamp box (lit in draw_mid)

    def _furnish_corridor(self, ctx):
        for dxx in range(-900, 4400, 700):                        # doors one after another
            _rect(ctx, dxx, 300, 240, 560, "#5a3a22", 3)
            ctx.new_path()
            ctx.arc(dxx + 205, 600, 9, 0, 2 * math.pi)
            _fill(ctx, "#b8962a", keep=False)

    def _furnish_shed(self, ctx):
        for i, x in enumerate(range(-600, 3800, 520)):            # tools on hooks
            if i % 2:
                G.line(ctx, [(x, 300), (x + 20, 640)], 8, G.rgb("#6a4a2a"), smooth_it=False)       # a spade
                ctx.new_path()
                ctx.rectangle(x + 2, 640, 50, 90)
                _fill(ctx, "#5a5a5a")
                _stroke(ctx, 2)
            else:
                ctx.new_path()                                    # a sickle
                ctx.arc(x, 420, 70, math.pi * 1.1, math.pi * 1.9)
                _stroke(ctx, 9, (0.4, 0.4, 0.42))
                G.line(ctx, [(x + 66, 400), (x + 80, 500)], 8, G.rgb("#6a4a2a"), smooth_it=False)
        for i in range(3):
            ctx.new_path()
            G.smooth(ctx, [(2900 + i * 150, 860), (2890 + i * 150, 740), (2960 + i * 150, 700), (3020 + i * 150, 740), (3010 + i * 150, 860)])
            _fill(ctx, "#a89466")
            _stroke(ctx, 2)
        for cx, cy, s in ((-900, -350, 1), (4300, -350, -1)):     # cobwebs in the corners
            for r in (80, 160, 240):
                ctx.new_path()
                ctx.arc(cx, cy, r, 0 if s > 0 else math.pi / 2, math.pi / 2 if s > 0 else math.pi)
                ctx.set_source_rgba(0.85, 0.85, 0.85, 0.4)
                ctx.set_line_width(1.5)
                ctx.stroke()

    def _furnish_flat(self, ctx):
        _rect(ctx, 2550, 700, 640, 160, "#6a4a5a", 3)             # the sofa
        _rect(ctx, 2550, 600, 640, 110, "#7a5a6a", 3)
        _rect(ctx, 600 if self.door[0] > 1000 else 2600, 520, 300, 190, "#1a1a1e", 4)   # the television
        _rect(ctx, 1300, 280, 260, 180, "#8a6a3a", 4)             # a framed picture
        _rect(ctx, 1320, 300, 220, 140, "#9ab0c0", 1.5)

    def _furnish_hold(self, ctx):
        for bx in range(-900, 4400, 500):                         # ribs of the hull
            ctx.new_path()
            ctx.move_to(bx, -400)
            ctx.curve_to(bx + 60, 200, bx + 80, 600, bx + 20, 860)
            _stroke(ctx, 16, G.shade(self.wall, 0.55))
        _rect(ctx, 2800, 700, 300, 160, "#4a3a22", 2.5)           # a crate

    def _furnish_classroom(self, ctx):
        bx = 1150 if self.door[0] > 1000 else 1700
        _rect(ctx, bx, 230, 900, 380, "#1e3a2a", 8)               # the blackboard, with chalk marks
        for i in range(4):
            G.line(ctx, [(bx + 60, 300 + i * 70), (bx + 380 + (i * 97) % 300, 300 + i * 70)], 4, (0.9, 0.9, 0.88), smooth_it=False)
        _rect(ctx, bx + 300, 700, 360, 30, "#6a4428", 3)          # the teacher's table
        for x in range(-900, 4400, 520):                          # rows of benches
            if bx - 200 < x < bx + 1000:
                continue
            _rect(ctx, x, 760, 420, 26, "#7a5030", 2.5)
            _rect(ctx, x + 20, 786, 20, 74, "#5a3a22", 1.5)
            _rect(ctx, x + 380, 786, 20, 74, "#5a3a22", 1.5)

    def _furnish_palki(self, ctx):
        _rect(ctx, -1000, 760, 5400, 100, "#8a2a2a", 3)           # the cushion seat

    # ------------------------------------------------------------------ the living parts
    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        if self.kind == "bedroom":
            return super().draw_mid(ctx, W, H, cam, t, top, bot, sun_h)
        k = self.kind
        m = self.layer_matrix(W, H, cam, 1.0)
        dx, dy, dw, dh = self.door
        night = max(0.0, min(1.0, -sun_h / 0.35)) if sun_h < 0.2 else 0.0
        if k == "flat":                                           # the city outside the window
            ctx.save()
            ctx.set_matrix(self.layer_matrix(W, H, cam, 0.5))
            r = random.Random(3)
            for i in range(14):
                x, hgt = 300 + i * 140, r.uniform(250, 520)
                ctx.new_path()
                ctx.rectangle(x, 860 - hgt, 120, hgt)
                _fill(ctx, "#1a2030" if night > 0.3 else "#8a96a8", keep=False)
                for wy_ in range(int(860 - hgt) + 20, 840, 50):
                    if r.random() < (0.5 if night > 0.3 else 0.15):
                        ctx.new_path()
                        ctx.rectangle(x + 20 + r.choice((0, 50)), wy_, 26, 22)
                        _fill(ctx, "#ffd97a" if night > 0.3 else "#c0d0e0", keep=False)
            ctx.restore()
        elif k not in ("corridor", "palki", "hold", "studio"):    # trees outside
            ctx.save()
            ctx.set_matrix(self.layer_matrix(W, H, cam, 0.5))
            for i in range(5):
                x = 400 + i * 300
                sw = 12 * math.sin(t * 1.2 + i) * (0.4 + self.wind(t, x))
                ctx.new_path()
                G.ellipse(ctx, x + sw, 560, 140, 110)
                _fill(ctx, "#13201a" if night > 0.3 else "#4a7a3a", keep=False)
            ctx.restore()
        if k not in ("palki", "hold"):
            ctx.save()
            ctx.set_matrix(m)
            ctx.new_path()
            ctx.rectangle(dx, dy, dw, dh)
            _fill(ctx, "#07080c", keep=False)
            ctx.restore()
        self._blit(ctx, "room", W, H, cam)
        ctx.save()
        ctx.set_matrix(m)
        ctx.new_path()                                            # ceiling
        ctx.rectangle(-2000, -3000, 7000, 3001)
        _fill(ctx, G.shade(self.wall, 0.6), keep=False)
        if k in ("shed", "hold", "kitchen", "palki"):
            for bx in range(-1000, 4400, 380):
                _rect(ctx, bx, -3000, 44, 2960, "#3a2814", 1)
        dead = t > self.lamp_off + 0.6
        flick = 0.8 + 0.2 * math.sin(t * 13) * math.sin(t * 5.1)
        if self.lamp_off - 0.8 < t <= self.lamp_off + 0.6:
            flick *= max(0.0, 0.5 + 0.5 * math.sin(t * 40)) * max(0.0, (self.lamp_off + 0.6 - t) / 1.4)
        if dead:
            flick = 0.0
        # ---- the lights of each kind
        if k == "kitchen":                                        # embers and smoke
            cx = self.lamp_x
            e = 0.7 + 0.3 * math.sin(t * 7) * math.sin(t * 2.3)
            _glow(ctx, cx, 800, 420 * e, "#ff7a2a", 0.4)
            ctx.new_path()
            G.ellipse(ctx, cx, 805, 44, 26)
            ctx.set_source_rgba(1.0, 0.45, 0.1, 0.8 * e)
            ctx.fill()
            for i in range(5):
                u = (t * 0.25 + i / 5) % 1.0
                ctx.new_path()
                G.ellipse(ctx, cx + 40 * math.sin(u * 6 + i), 660 - u * 620, 40 + 80 * u, 30 + 50 * u)
                ctx.set_source_rgba(0.75, 0.75, 0.75, 0.25 * (1 - u))
                ctx.fill()
        elif k == "hall":                                         # the chandelier, candles flickering
            cx = 1700
            G.line(ctx, [(cx, -400), (cx, 60)], 5, G.rgb("#6a5a2a"), smooth_it=False)
            ctx.new_path()
            G.ellipse(ctx, cx, 80, 220, 34)
            _fill(ctx, "#a8862a")
            _stroke(ctx, 3)
            for i in range(7):
                x = cx - 190 + i * 63
                f_ = flick * (0.85 + 0.15 * math.sin(t * 11 + i))
                if f_ > 0.05:
                    _glow(ctx, x, 30, 160 * f_, "#ffc860", 0.35)
                    ctx.new_path()
                    G.ellipse(ctx, x, 30, 8, 16)
                    ctx.set_source_rgba(1, 0.85, 0.4, f_)
                    ctx.fill()
            if flick > 0.05:
                _glow(ctx, cx, 200, 1200 * flick, "#ffb347", 0.18)
        elif k in ("hospital", "corridor", "studio", "flat", "office"):
            if k in ("hospital",):                                # the tube light hums and flickers
                on = flick * (1.0 if int(t * 7.3) % 23 else 0.2)
                _rect(ctx, 1450, 120, 420, 26, (0.9 * on + 0.1, 0.95 * on + 0.05, 1.0 * on), 2)
                if on > 0.1:
                    _glow(ctx, 1660, 140, 1300 * on, "#e8f4ff", 0.22)
            if k == "corridor":                                   # bare bulbs that swing; one flickers
                for i, x in enumerate(range(-600, 4400, 900)):
                    a = 0.12 * math.sin(t * 1.3 + i)
                    bx, by = x + math.sin(a) * 300, 300 * math.cos(a) - 50
                    G.line(ctx, [(x, -400), (bx, by)], 3, G.rgb("#202020"), smooth_it=False)
                    on = flick * (1.0 if i != 2 else (0.5 + 0.5 * math.sin(t * 31)) ** 4)
                    ctx.new_path()
                    G.ellipse(ctx, bx, by + 20, 20, 26)
                    ctx.set_source_rgba(1, 0.9, 0.6, 0.3 + 0.7 * on)
                    ctx.fill()
                    if on > 0.05:
                        _glow(ctx, bx, by + 20, 650 * on, "#ffd88a", 0.28)
            if k in ("office", "studio"):                         # the table lamp
                x = self.lamp_x + (200 if k == "office" else -250)
                G.line(ctx, [(x, 700), (x, 600), (x + 40, 560)], 6, G.rgb("#2a2a2a"))
                ctx.new_path()
                ctx.move_to(x + 10, 560)
                ctx.line_to(x + 110, 560)
                ctx.line_to(x + 80, 500)
                ctx.line_to(x + 30, 500)
                ctx.close_path()
                _fill(ctx, "#2e6a3a" if k == "office" else "#6a2a2a")
                _stroke(ctx, 2)
                if flick > 0.05:
                    _glow(ctx, x + 60, 640, 600 * flick, "#ffd27a", 0.4)
            if k == "studio":                                     # the on-air lamp and the console lights
                on = 0.7 + 0.3 * math.sin(t * 3)
                _rect(ctx, 2620, 135, 220, 60, (0.9 * on, 0.1, 0.1), 2)
                for i in range(12):
                    c_ = (0.2, 0.9, 0.3) if (int(t * 4) + i * 7) % 5 else (0.95, 0.7, 0.1)
                    ctx.new_path()
                    ctx.arc(self.lamp_x - 320 + i * 30, 640, 7, 0, 2 * math.pi)
                    _fill(ctx, c_, keep=False)
            if k == "flat":                                       # the ceiling light
                on = flick
                _rect(ctx, 1500, -40, 380, 24, (0.95 * on + 0.05, 0.95 * on + 0.05, 0.9 * on + 0.05), 2)
                if on > 0.1:
                    _glow(ctx, 1690, 0, 1400 * on, "#fff4d8", 0.2)
                tv = 0.5 + 0.5 * math.sin(t * 9) * math.sin(t * 2.1)
                tvx = 600 if self.door[0] > 1000 else 2600
                _rect(ctx, tvx + 15, 535, 270, 160, (0.25 + 0.3 * tv, 0.3 + 0.35 * tv, 0.4 + 0.4 * tv), 1)
        elif k in ("shed", "hold"):                               # light through the gaps / the swinging lantern
            if k == "shed":
                for i, x in enumerate(range(-1000, 4400, 140)):
                    a = 0.12 + 0.06 * math.sin(t * 0.7 + i)
                    ctx.new_path()
                    ctx.move_to(x, -400)
                    ctx.line_to(x + 18, -400)
                    ctx.line_to(x + 400, 960)
                    ctx.line_to(x + 340, 960)
                    ctx.close_path()
                    ctx.set_source_rgba(0.9, 0.9, 0.8, a * (1 - night * 0.7))
                    ctx.fill()
            ang = 0.35 * math.sin(2 * math.pi * t / 2.6)
            px, py = self.lamp_x, -60
            lx, ly = px + math.sin(ang) * 380, py + math.cos(ang) * 380
            G.line(ctx, [(px, py), (lx, ly - 46)], 4, G.rgb("#3a3a3a"), smooth_it=False)
            if flick > 0.05:
                _glow(ctx, lx, ly, 800 * flick, "#ffb347", 0.32)
            ctx.new_path()
            G.ellipse(ctx, lx, ly, 30, 44)
            ctx.set_source_rgba(1, 0.85, 0.45, 0.3 + 0.6 * flick)
            ctx.fill_preserve()
            _stroke(ctx, 2.5)
            if k == "hold":                                       # water sloshing on the floor
                for i in range(3):
                    y = 900 + i * 18
                    pts = [(x, y + 8 * math.sin(x * 0.01 + t * 2.4 + i)) for x in range(-1000, 4401, 100)]
                    G.line(ctx, pts, 4, (0.3, 0.4, 0.45), smooth_it=False)
        elif k == "palki":                                        # stripes of light moving with the sway
            for i, x in enumerate(range(-1000, 4400, 110)):
                off = 30 * math.sin(2 * math.pi * t / 1.6)
                ctx.new_path()
                ctx.rectangle(x + 40 + off, -400, 14, 1260)
                ctx.set_source_rgba(0.95, 0.9, 0.75, 0.25 + 0.1 * math.sin(t * 3 + i))
                ctx.fill()
            for side, x0 in ((0, 600), (1, 2400)):                # the front curtain swaying
                sw = 40 * math.sin(t * 1.9 + side)
                ctx.new_path()
                ctx.move_to(x0, -200)
                ctx.line_to(x0 + 600, -200)
                ctx.curve_to(x0 + 600 + sw, 200, x0 + 560 + sw, 500, x0 + 600 + sw * 1.5, 760)
                ctx.line_to(x0 + sw * 1.5, 760)
                ctx.close_path()
                ctx.set_source_rgba(0.75, 0.15, 0.12, 0.85)
                ctx.fill()
        if k not in ("palki", "hold", "corridor", "studio"):     # the curtain at the window
            wx, wy, ww, wh = self.win
            w = self.wind(t, wx)
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
                ctx.set_source_rgba(0.92, 0.9, 0.82, 0.5)
                ctx.fill()
        if k not in ("palki", "hold"):                            # the door: closed, or swinging open
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
            _fill(ctx, "#6b4226" if k not in ("hospital", "flat", "office") else "#d8d0c0")
            _stroke(ctx, 3)
            ctx.new_path()
            ctx.arc(dx + pw * 0.85, dy + dh * 0.52, 10, 0, 2 * math.pi)
            _fill(ctx, "#c9a227", keep=False)
        if self.fan:
            fx, fy = 1500 if self.lamp_x > 1600 else 2000, -60
            G.line(ctx, [(fx, -400), (fx, fy)], 8, G.rgb("#3a3a3a"), smooth_it=False)
            ang = t * 4.0
            for i in range(3):
                a_ = ang + i * 2 * math.pi / 3
                ex, ey = fx + math.cos(a_) * 420, fy + math.sin(a_) * 40
                ctx.new_path()
                ctx.move_to(fx, fy - 6)
                ctx.line_to(ex, ey - 12)
                ctx.line_to(ex, ey + 12)
                ctx.line_to(fx, fy + 6)
                ctx.close_path()
                _fill(ctx, "#5a5a52")
                _stroke(ctx, 2)
        ctx.restore()


class Boat(WD.World):
    """ON a country boat on a big river (Sundarbans / the Ganga): the deck the people stand on, the bamboo canopy,
    the river in three depths, the far bank's mangroves, a lantern on a hook; in a storm: rain, lightning, big waves.
    The deck rocks, and the camera rocks with it."""
    LAYERS = dict(WD.World.LAYERS, bank=0.3, river=0.6, deck=1.0)

    def __init__(self, spec=None):
        spec = dict(spec or {})
        spec.setdefault("hours", [[0, 22.0]])
        super().__init__(spec)
        self.storm = float(spec.get("storm", 0.0))
        self.palki = bool(spec.get("palki", False))
        self.lamp_off = float(spec.get("lamp_off_at", 1e9))

    def shake(self, t):
        s = 1.0 + 1.5 * self.storm
        return 3.0 * s * math.sin(2 * math.pi * t / 3.4), 7.0 * s * math.sin(2 * math.pi * t / 2.6)

    def static_layer(self, name, ctx):
        if name == "deck":
            ctx.new_path()                                        # the deck planks (where the people stand)
            ctx.rectangle(-1000, 880, 5400, WORLD_H + 200)
            _fill(ctx, "#6a4a2a", keep=False)
            for y in range(890, WORLD_H + 200, 34):
                G.line(ctx, [(-1000, y), (4400, y)], 2, (0.25, 0.16, 0.08), smooth_it=False)
            ctx.new_path()                                        # the gunwale (side of the boat)
            ctx.rectangle(-1000, 840, 5400, 46)
            _fill(ctx, "#4a3018")
            _stroke(ctx, 3)
            for bx in (300, 2900):                                # bamboo posts of the canopy
                _rect(ctx, bx, 220, 30, 640, "#a88a4a", 2)
            if self.palki:                                        # the bridal palanquin on the deck
                _rect(ctx, 1950, 560, 520, 300, "#8a2a1e", 3)
                ctx.new_path()
                ctx.move_to(1930, 560)
                ctx.curve_to(2050, 470, 2370, 470, 2490, 560)
                _fill(ctx, "#a8862a")
                _stroke(ctx, 3)
                G.line(ctx, [(1700, 600), (2720, 600)], 14, G.rgb("#5a3a1a"), smooth_it=False)
                for i in range(4):
                    _rect(ctx, 2000 + i * 110, 600, 80, 200, "#5a1a12", 1.5)
            return True
        return False

    def draw_mid(self, ctx, W, H, cam, t, top, bot, sun_h):
        night = max(0.0, min(1.0, -sun_h / 0.35)) if sun_h < 0.2 else 0.0
        ctx.save()                                                # the far bank: mangroves
        ctx.set_matrix(self.layer_matrix(W, H, cam, self.LAYERS["bank"]))
        pts = [(x, 560 - 40 * abs(math.sin(x * 0.004)) - 20 * math.sin(x * 0.013)) for x in range(-1000, 4401, 120)]
        ctx.new_path()
        G.smooth(ctx, [(-1000, 640)] + pts + [(4400, 640)], tension=0.4)
        _fill(ctx, "#0e1a14" if night > 0.3 else "#3e6a3a", keep=False)
        ctx.restore()
        for depth, (y0, amp, sp, col) in enumerate(((600, 6, 0.6, "#1e3040"), (680, 12, 1.0, "#24384a"), (780, 22, 1.6, "#2c4458"))):
            ctx.save()                                            # the river, three depths of waves
            ctx.set_matrix(self.layer_matrix(W, H, cam, 0.45 + 0.2 * depth))
            a = amp * (1 + 2.0 * self.storm)
            pts = [(x, y0 + a * math.sin(x * 0.006 * (depth + 1) + t * sp * (1 + self.storm))) for x in range(-1000, 4401, 60)]
            ctx.new_path()
            G.smooth(ctx, [(-1000, 1300)] + pts + [(4400, 1300)], tension=0.4)
            c = G.rgb(col) if night > 0.3 else G.shade(col, 1.6)
            _fill(ctx, c, keep=False)
            for x, y in pts[::3]:
                G.line(ctx, [(x - 30, y + 4), (x + 30, y + 4)], 2, G.shade(c, 1.4), smooth_it=False)
            ctx.restore()
        self._blit(ctx, "deck", W, H, cam)
        ctx.save()
        ctx.set_matrix(self.layer_matrix(W, H, cam, 1.0))
        ctx.new_path()                                            # the bamboo / straw canopy (chhoi)
        ctx.move_to(200, 240)
        ctx.curve_to(900, -60, 2400, -60, 3100, 240)
        ctx.line_to(3100, 270)
        ctx.curve_to(2400, -20, 900, -20, 200, 270)
        ctx.close_path()
        _fill(ctx, "#8a6a3a")
        _stroke(ctx, 3)
        for i in range(12):
            x = 300 + i * 240
            G.line(ctx, [(x, 230 - 180 * math.sin(math.pi * (x - 200) / 2900)), (x + 10, 255 - 160 * math.sin(math.pi * (x - 200) / 2900))],
                   2, (0.35, 0.25, 0.12), smooth_it=False)
        ang = 0.3 * math.sin(2 * math.pi * t / 2.6) * (1 + self.storm)      # the lantern swings on its hook
        px, py = 1650, 90
        lx, ly = px + math.sin(ang) * 220, py + math.cos(ang) * 220
        G.line(ctx, [(px, py), (lx, ly - 40)], 4, G.rgb("#3a3a3a"), smooth_it=False)
        on = 0.0 if t > self.lamp_off + 0.4 else (0.8 + 0.2 * math.sin(t * 13) * math.sin(t * 4.7))
        if on > 0.05:
            _glow(ctx, lx, ly, 900 * on, "#ffb347", 0.3)
        ctx.new_path()
        G.ellipse(ctx, lx, ly, 28, 40)
        ctx.set_source_rgba(1, 0.85, 0.45, 0.3 + 0.6 * on)
        ctx.fill_preserve()
        _stroke(ctx, 2.5)
        ctx.restore()
        if self.storm > 0 and int(t * 10) % 53 in (0, 1):         # lightning
            ctx.save()
            ctx.identity_matrix()
            ctx.set_source_rgba(0.85, 0.9, 1.0, 0.45)
            ctx.paint()
            ctx.restore()

    def draw_fore(self, ctx, W, H, cam, t):
        pass


ROOM_NAMES_BN = {"bedroom": "শোবার ঘর", "kitchen": "রান্নাঘর", "hall": "রাজবাড়ির দরবার", "hospital": "হাসপাতালের ওয়ার্ড",
                 "office": "অফিসঘর", "studio": "রেডিওর ঘর", "corridor": "লম্বা বারান্দা-পথ", "shed": "গুদামঘর",
                 "flat": "কলকাতার ফ্ল্যাট", "hold": "নৌকার খোল", "palki": "পালকির ভেতর",
                 "classroom": "ক্লাসঘর"}
