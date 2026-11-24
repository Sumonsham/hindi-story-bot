"""scene engine: structured scene instructions -> timeline -> automatic performances -> camera shots -> video.

Scene (JSON / dict):
  {"location": "village_courtyard", "aspect": "16:9" | "9:16", "fps": 24 | 30, "subtitles": true,
   "cast": [{"id": "lumi_didi", "x": 1200}, {"id": "bappa", "x": 1700}],
   "beats": [
     {"who": "lumi_didi", "say": "বাপ্পা, তুমি কোথায় যাচ্ছ?", "audio": "line1.wav", "to": "bappa"},
     {"who": "bappa", "say": "...", "audio": "line2.wav", "emotion": "happy"},
     {"who": "bappa", "walk_to": 2400, "gait": "run"},
     {"who": "nibaran_dadu", "sit": true, "seat_h": 250}, {"who": "nibaran_dadu", "stand": true},
     {"who": "mili", "gesture": "wave", "sec": 2}, {"who": "mili", "emotion": "surprised", "sec": 1.5},
     {"pause": 1.0}, ...  ("with_prev": true starts a beat together with the one before)
   ]}
"""
import hashlib
import json
import math
import os
import subprocess

import cairo

LINE_ = (0.16, 0.10, 0.08)
VH_SIZE_CYCLE = 1.85
import numpy as np

from tvtoon import animator as AN
from tvtoon import backgrounds as BG
from tvtoon import characters as CH
from tvtoon import lipsync as LS
from tvtoon import puppet as PP
from tvtoon import geom as G

CX0_DEFAULT = 1600.0
SCALE = 0.62                       # world px per character unit (an adult man is 620 px tall in the world)
AUDIO_SR = 24000

EMO_WORDS = {
    "scared": ["ভয়", "ভূত", "বাঁচাও", "সর্বনাশ", "অন্ধকার", "কে ওখানে"],
    "angry": ["রাগ", "চুপ", "বেরো", "কতবার বলেছি", "দুষ্টু"],
    "sad": ["দুঃখ", "কাঁদ", "হারিয়ে", "মন খারাপ", "আহা রে"],
    "laughing": ["হা হা", "হাহা", "হি হি"],
    "happy": ["বাহ", "দারুণ", "খুশি", "মজা", "ভালো", "চমৎকার", "সুন্দর"],
    "surprised": ["সত্যি", "কী!", "অবাক", "ওমা", "তাই নাকি"],
}


def classify(text):
    for emo, words in EMO_WORDS.items():
        if any(w in text for w in words):
            return emo
    if text.strip().endswith("!"):
        return "surprised"
    return "neutral"


def audio_len(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


class Scene:
    def __init__(self, spec):
        from tvtoon import life as LF                      # the place's own people (life.py)
        try:
            lc, lb = LF.plan(spec)
        except Exception:
            lc, lb = [], []
        if lc:
            spec = dict(spec, cast=list(spec["cast"]) + lc, beats=list(spec["beats"]) + lb)
        self.life = [c["id"] for c in lc]
        self.spec = spec
        self.fps = int(spec.get("fps", 24))
        self.aspect = spec.get("aspect", "16:9")
        self.W, self.H = (1920, 1080) if self.aspect == "16:9" else (1080, 1920)
        if spec.get("size"):
            self.W, self.H = spec["size"]
        self.wind = float(spec.get("wind", 0.4))
        self.perf, self.puppets, self.order = {}, {}, []
        self.depth = {}
        for c in spec["cast"]:
            if c.get("spec") and c["id"] not in CH.SPECS:          # a character made for this story (it travels with it)
                CH.SPECS[c["id"]] = c["spec"]
            disguised = bool(c.get("disguise")) and CH.get(c["id"]).get("ghost") is not None
            human_id = (c["id"][: -len("__ghost")] if c["id"].endswith("__ghost") else c["id"] + "__human")
            pp = PP.make(CH.get(human_id if disguised else c["id"]))
            self.puppets[c["id"]] = pp
            pf = AN.Perf(c["id"], pp, float(c["x"]))
            if disguised:                                      # the ghost comes as an ordinary person first
                pf.forms = (pp, PP.make(CH.get(c["id"])))
            self.depth[c["id"]] = float(c.get("z", 0.0))       # 0 = front row, 1 = far back (smaller, higher)
            if c.get("name_bn"):
                self.names = getattr(self, "names", {})
                self.names[c["id"]] = c["name_bn"]              # the story's own name for this actor
            pf.scale = self.cscale(c["id"])
            pf.scene = self
            pf.side_talk = c.get("view", spec.get("talk_view")) == "side"   # talk face to face in profile
            if c.get("facing") in ("left", "right"):                         # standing in profile from the start
                pf.facing_side = -1.0 if c["facing"] == "left" else 1.0
            self.perf[c["id"]] = pf
            if c.get("extra"):
                pf.extra = True                                # a passer-by: never speaks, never takes the camera
                continue
            self.order.append(c["id"])
        from tvtoon import locations as LC
        from tvtoon import vehicles as VH
        loc = spec.get("location", "village_courtyard")
        self.world = LC.make(loc, spec.get("world")) if loc in LC.LOCATIONS else None
        self.vehicles = {}
        for v in spec.get("vehicles", []):
            veh = VH.Vehicle(v["id"], v["kind"], v["x"], z=v.get("z", 0.0), colour=v.get("colour"), cars=v.get("cars", 1),
                             lane=v.get("lane"))
            veh.facing = float(v.get("facing", 1.0))
            self.vehicles[v["id"]] = veh
        if self.world is not None and hasattr(self.world, "draw_trains"):
            self.world.train_hook = self._draw_track_vehicles
        for pf in self.perf.values():
            pf.rides = []
        self.lines, self.props, self.shots = [], [], []
        self.transforms = []
        self.log = []
        self.duration = self._plan()

    # -------------------------------------------------------------- planning
    STRONG = ("surprised", "scared", "angry", "laughing", "crying")
    REACT = {"surprised": "surprised", "scared": "scared", "angry": "scared", "laughing": "happy", "crying": "sad",
             "sad": "sad", "happy": "happy"}

    def _plan(self):
        """beats -> performances + AUTOMATIC shots (story-driven camera). A beat's "shot" overrides the choice:
        a type ("establish", "wide", "full", "medium", "close", "ecu", "ots", "two", "reaction", "track") or a dict."""
        t = float(self.spec.get("t_start", 0.5))
        prev = (t, t)
        auto = []                      # (t0, t1, shot) chosen by the story rules
        n_line = 0
        to_end = []
        for bi, b in enumerate(self.spec["beats"]):
            t0 = float(b["at"]) if "at" in b else (prev[0] if b.get("with_prev") else t)   # 'at': an exact time
            who = b.get("who")
            pf = self.perf.get(who)
            shot = None
            if "pause" in b:
                t1 = t0 + float(b["pause"])
                if bi == 0:
                    shot = {"type": "establish"}               # open the scene on the place
                elif bi == len(self.spec["beats"]) - 1:
                    shot = {"type": "wide", "trans": "ease", "move": "pull", "ease": 2.0}
                else:
                    shot = {"type": "wide"}
            elif "say" in b:
                text = b["say"]
                emo = b.get("emotion") or classify(text)
                aud = b.get("audio")
                how = "given"
                if not (aud and os.path.exists(aud)):
                    from tvtoon import voices as VO
                    aud, how = VO.line(who, text, emo, log=lambda *a: None)
                if aud and os.path.exists(aud):
                    dur = audio_len(aud)
                    ev, info = LS.align(aud, text)
                    loud, hop = LS.loudness_track(aud)
                else:                                          # no audio: an honest silent beat (no mouth movement)
                    dur = max(1.5, 0.19 * len(LS.syllables(text)))
                    ev, info, loud, hop = [(0.0, "X")], {"method": "NO AUDIO - mouth stays closed"}, np.zeros(1), 0.01
                t1 = t0 + dur
                to = b.get("to")
                pf.speech.append((t0, t1, ev, loud, hop, emo, to))
                if emo != "neutral":
                    pf.emotions.append((t0, t1 + 0.6, emo))
                if b.get("gesture"):
                    pf.gestures.append((t0, t1, b["gesture"], b.get("side"), None))
                self.lines.append({"t0": t0, "t1": t1, "who": who, "text": text, "audio": aud, "voice": how, "emotion": emo,
                                   "lipsync": info, "to": to})
                # camera: the first exchange in a two-shot (eased in from the establishing shot), then shot /
                # reverse shot over the listener's shoulder, a close-up on strong emotion
                if n_line == 0 and to:
                    shot = {"type": "two", "to": to, "trans": "ease"}
                elif emo in self.STRONG:
                    shot = {"type": "close", "move": "push"}
                elif to and n_line % 2 == 1:
                    shot = {"type": "ots", "to": to}
                else:
                    shot = {"type": "medium", "to": to}
                n_line += 1
                tail = 0.35
                if to in self.perf and emo in self.STRONG and not b.get("no_reaction"):
                    # a REACTION: the listener answers the emotion with his whole face and body, in close-up
                    self.perf[to].emotions.append((t1 - 0.2, t1 + 1.3, self.REACT.get(emo, "surprised")))
                    auto.append((t1, t1 + 1.1, {"type": "reaction", "who": to}))
                    tail = 1.1
                t1 += tail
            elif "narrate" in b:                               # a voice-over: no one on screen speaks
                from tvtoon import voices as VO
                text = b["narrate"]
                if b.get("audio") and os.path.exists(b["audio"]):     # the bot's own recorded line
                    aud, how = b["audio"], "given"
                else:
                    aud, how = VO.line("narrator", text, b.get("emotion", "neutral"), log=lambda *a: None)
                dur = audio_len(aud) if aud and os.path.exists(aud) else max(1.5, 0.19 * len(LS.syllables(text)))
                t1 = t0 + dur
                self.lines.append({"t0": t0, "t1": t1, "who": "narrator", "narrator": True, "text": text, "audio": aud,
                                   "voice": how, "emotion": "neutral", "lipsync": {"method": "voice-over"}, "to": None})
                t1 += 0.3
                shot = b.get("shot_type") and {"type": b["shot_type"]}
            elif "drive_to" in b:                              # a vehicle drives (accelerate, cruise, brake)
                v = self.vehicles[b["vehicle"]]
                x0 = v.x_at(t0)
                t1 = t0 + (4.0 if b.get("sec") == "end" else float(b.get("sec", 4.0)))
                v.moves.append((t0, t1, x0, float(b["drive_to"])))
                shot = {"type": "track", "who": b["vehicle"]}
                who = b["vehicle"]
            elif "ride" in b:                                  # get on: the rider sits on the vehicle's seat
                pf.rides.append([0.0 if t0 <= 0.5 else t0, 1e9, b["ride"], int(b.get("seat", 0))])   # on it from frame 1
                v = self.vehicles[b["ride"]]
                if v.kind == "cycle" and int(b.get("seat", 0)) == 0:   # a cycle that fits the rider (a child gets a small one)
                    P_ = pf.pp.P                               # so the feet really reach the pedals at the bottom
                    need = (0.95 * (P_["thigh"] + P_["shin"]) + P_["foot_h"]) * self.cscale(who)
                    v.kmul = max(0.6, min(1.15, need / (243.6 * VH_SIZE_CYCLE * self.vscale(b["ride"]))))
                t1 = t0 + float(b.get("sec", 0.3))
            elif b.get("get_off"):
                for r_ in pf.rides:
                    if r_[1] > 1e8:
                        r_[1] = t0
                        pf.x0 = self.vehicle_seat_x(r_[2], r_[3], t0, who)
                        pf.moves = [m for m in pf.moves if m[1] <= t0]
                t1 = t0 + float(b.get("sec", 0.3))
            elif "walk_to" in b:
                x0 = pf.x_at(t0)
                x1 = float(b["walk_to"])
                gait = b.get("gait", "walk")
                P = pf.pp.P
                speed = (P["leg"] * 0.85 / 1.05 if gait == "walk" else P["leg"] * 1.25 / 0.62) * self.cscale(who)
                t1 = t0 + abs(x1 - x0) / speed
                pf.moves.append((t0, t1, x0, x1, gait))
                shot = {"type": "track"}
                t1 += 0.2
            elif b.get("sit"):
                seat_h = pf.pp.P["foot_h"] + pf.pp.P["shin"] + pf.pp.P["thigh"] * 0.34
                x = pf.x_at(t0)
                sc_ = self.cscale(who)
                if not b.get("prop", True) and b.get("side", b.get("facing")):   # a real seat under a side sitter
                    self.props.append({"type": "side_seat", "behind": who, "h": seat_h})
                if b.get("prop", True):                        # a mora; inside a vehicle the bench is the seat
                    self.props.append({"type": "mora", "x": x, "h": seat_h * sc_, "w": pf.pp.P["hip"] * 2.6 * sc_, "t0": 0.0,
                                       "t1": 1e9, "behind": who})
                already = b.get("already")                     # sitting from the start (no sitting-down move)
                t1 = t0 + (0.0 if already else 1.0)
                side = b.get("side", b.get("facing"))                # sitting in profile (benches, seats facing each other)
                side = (-1.0 if side == "left" else 1.0 if side == "right" else 0.0) if side else None   # True: toward the partner
                pf.sits.append([t0 - 1.0 if already else t0 + 0.9, 1e9, seat_h, side])
                shot = {"type": "full"}
            elif b.get("transform") and getattr(pf, "forms", None):   # the disguise falls: the ghost shows itself
                t1 = t0 + float(b.get("sec", 1.8))
                pf.transform = (t0, t1)
                self.transforms.append((t0, t1, who))
                for o in self.order:                           # everyone else is struck with fear
                    if o != who:
                        self.perf[o].emotions.append((t0 + 1.1, t0 + 3.6, "scared"))
                if self.world is not None and hasattr(self.world, "flicker"):
                    self.world.flicker.append([t0 + 0.25, t0 + 1.05])          # the carriage lights fail
                if self.world is not None and hasattr(self.world, "lamp_off"):
                    self.world.lamp_off = min(self.world.lamp_off, t0 + 0.6)    # the lantern goes out
                shot = {"type": "close", "move": "push"}
                auto.append((t0 + 1.25, t0 + 2.6, {"type": "wide", "who": who}))   # then: the whole horror
            elif "act" in b:                                   # a body action from the story (jump, dance, nod, bow...)
                t1 = t0 + float(b.get("sec", {"jump": 0.65, "dance": 2.9, "nod": 0.9, "shake": 0.9, "bow": 1.4,
                                               "fall": 1.6}.get(b["act"], 1.0)))
                pf.acts.append((t0, t1, b["act"]))
                shot = {"type": "full" if b["act"] in ("jump", "dance", "fall", "bow") else "medium"}
            elif "look_back" in b:                             # turn and look back over the shoulder
                t1 = t0 + float(b["look_back"])
                pf.lookbacks.append((t0, t1))
                shot = {"type": "medium"}
            elif b.get("stand"):
                for s_ in pf.sits:
                    if s_[1] > 1e8:
                        s_[1] = t0
                t1 = t0 + 1.0
                shot = {"type": "full"}
            elif "gesture" in b:
                t1 = t0 + float(b.get("sec", 2.0))
                pf.gestures.append((t0, t1, b["gesture"], b.get("side"), None))
                shot = {"type": "medium"}
            elif "emotion" in b:
                t1 = t0 + float(b.get("sec", 1.5))
                pf.emotions.append((t0, t1, b["emotion"]))
                shot = {"type": "close" if b["emotion"] in self.STRONG else "medium"}
            elif "face" in b:
                t1 = t0 + float(b.get("sec", 1.5))
                pf.facing.append((t0, float(b["face"])))
            else:
                t1 = t0
            if b.get("life"):                                  # the place's own people never take the camera
                shot = None
                b = dict(b, shot=None)
            if b.get("shot"):                                  # manual override
                shot = b["shot"] if isinstance(b["shot"], dict) else {"type": b["shot"]}
            if shot and not (b.get("with_prev") and not b.get("shot")):
                shot = dict(shot)
                shot.setdefault("who", who)
                auto.append((t0, t1, shot))
            prev = (t0, t1)
            if b.get("background"):                            # runs under the following beats (a drive during the talk)
                if b.get("sec") == "end" and "drive_to" in b:
                    to_end.append(b["vehicle"])
                continue
            t = max(t, t1)
        for vid in to_end:                                     # the drive lasts the whole scene
            v = self.vehicles[vid]
            t0_, _t1, xa, xb = v.moves[-1]
            v.moves[-1] = (t0_, max(t, t0_ + 2.0) + 1.0, xa, xb)
        auto.sort(key=lambda r: r[0])
        for t0, t1, sh in auto:
            sh.update(t0=t0, t1=t1)
            self.shots.append(sh)
        return t + 0.6

    # -------------------------------------------------------------- queries used by the performances
    def x_of(self, cid, t):
        return self.perf[cid].x_at(t) if cid in self.perf else None

    def current_speaker(self, t):
        for ln in self.lines:
            if ln["t0"] <= t < ln["t1"] and not ln.get("narrator"):
                return ln["who"]
        return None

    # -------------------------------------------------------------- vehicles and riders
    def vehicle_seat_x(self, vid, k, t, cid=None):
        v = self.vehicles[vid]
        dx, _h = v.seat(k)
        return v.x_at(t) + dx * v.direction(t) * self.vscale(vid)

    def vscale(self, vid):
        return SCALE * (1.0 - 0.22 * self.vehicles[vid].z)

    def vgy(self, vid):
        return BG.GROUND - 95.0 * self.vehicles[vid].z

    def riding(self, cid, t):
        for r_ in self.perf[cid].rides:
            if r_[0] <= t < r_[1]:
                return r_
        return None

    def _draw_vehicle(self, ctx, vid, t, matrix=None, gy=None, scale=None, part="all"):
        v = self.vehicles[vid]
        night = 0.0
        if self.world is not None:
            from tvtoon import world as WD
            night = max(0.0, min(1.0, (0.25 - WD.tod_palette(self.world.hour(t))[3]) / 0.5))
        ctx.save()
        if matrix is not None:
            ctx.set_matrix(matrix)
        v.draw(ctx, v.x_at(t), self.vgy(vid) if gy is None else gy, self.vscale(vid) if scale is None else scale, t, night,
               part=part)
        ctx.restore()

    def _draw_track_vehicles(self, ctx, W, H, cam, t, m, y):
        for vid, v in self.vehicles.items():
            if v.lane == "tracks":                        # the train fits under the platform shed (~420 px tall)
                self._draw_vehicle(ctx, vid, t, matrix=m, gy=y, scale=410.0 / v.height())

    # -------------------------------------------------------------- depth
    def cscale(self, cid):
        return SCALE * (1.0 - 0.22 * self.depth.get(cid, 0.0))

    def gy(self, cid):
        return BG.GROUND - 95.0 * self.depth.get(cid, 0.0)

    def gy_eff(self, cid):
        """the ground line the camera frames by: for a seated rider / sitter the body sits higher or lower than a
        standing one, so the 'ground' is moved so that the head is framed where it really is"""
        hh = getattr(self.perf[cid], "hip_h", None)
        if hh is None:
            return self.gy(cid)
        return self.gy(cid) - (hh - self.puppets[cid].P["leg"] * self.cscale(cid))

    def height(self, cid):
        return self.puppets[cid].P["H"] * self.cscale(cid)

    # -------------------------------------------------------------- camera (v2)
    def _smooth_x(self, cid, t, lag=0.35):
        """a tracking camera trails the subject a little and never jerks (average of the recent path)"""
        n = 7
        return sum(self.perf[cid].x_at(t - lag * k / (n - 1)) for k in range(n)) / n

    def framing(self, shot, t):
        """(cx, cy, zoom) for a shot type at time t. Composition: the subject's eyes on the upper third, looking
        room in front of the face, feet on the ground line for full shots."""
        portrait = self.H > self.W
        typ = shot.get("type", "wide")
        if shot.get("who") in self.vehicles:                   # following a vehicle
            vid = shot["who"]
            v = self.vehicles[vid]
            vx = sum(v.x_at(t - 0.35 * k / 6) for k in range(7)) / 7
            vx += 0.18 * self.W / max(0.3, self.H / 1080.0) * max(-1.0, min(1.0, v.speed(t) / 600.0)) * 0.5
            hv = max(v.height() * self.vscale(vid), max(self.height(c) for c in self.order) if self.order else 0)
            z = self.H / (hv * 1.7) if not portrait else self.W / 900.0
            if v.lane == "tracks" and self.world is not None:
                z = self.H / 1080.0 * 1.05
            return vx, self.vgy(vid) - (0.30 if portrait else 0.40) * self.H / z, z
        if not self.order:
            return CX0_DEFAULT, BG.GROUND - 0.4 * self.H, self.H / 1080.0
        who = shot.get("who") if shot.get("who") in self.perf else (self.current_speaker(t) or self.order[0])
        to = shot.get("to") if shot.get("to") in self.perf else None
        sx = self.perf[who].x_at(t)
        h, gy = self.height(who), self.gy_eff(who)
        look = 0.0
        if to:
            look = 1.0 if self.perf[to].x_at(t) > sx else -1.0
        u = (t - shot.get("t0", 0.0)) / max(0.5, shot.get("t1", t + 1) - shot.get("t0", 0.0))
        u = max(0.0, min(1.0, u))
        if typ in ("establish", "wide"):
            xs = [self.perf[c].x_at(t) for c in self.order]
            lo, hi = min(xs) - 330, max(xs) + 330
            tall = max(self.height(c) for c in self.order)
            z = min(self.H * 0.62 / tall, self.W / max(1.0, hi - lo))
            z = max(z, 0.55 * self.H / 1080.0)
            cx = (lo + hi) / 2
            if typ == "establish":                           # the village first: a slow pan onto the people
                z *= 0.82
                cx = cx - 520 * (1 - G.ease(u))
            if portrait:
                z = self.W / 1000.0 if len(xs) > 2 else self.W / 800.0
                cy = BG.GROUND - 0.30 * self.H / z
            else:
                cy = BG.GROUND - 0.40 * self.H / z
            if shot.get("move") == "pull":
                z *= 1.06 - 0.06 * G.ease(u)
            return cx, cy, z
        if typ == "track":
            cx = self._smooth_x(who, t)
            # room to walk into, from the walker's recent speed (continuous: no jump when he stops)
            v_ = (self.perf[who].x_at(t) - self.perf[who].x_at(t - 0.6)) / 130.0
            cx += 160 * max(-1.0, min(1.0, v_)) * self.cscale(who) / SCALE
            # frame for a taller character near him too - with a soft fall-off, so the zoom never jumps
            hh_ = h
            for c in self.order:
                d_ = abs(self.perf[c].x_at(t) - sx)
                w_ = max(0.0, min(1.0, (900.0 - d_) / 400.0))
                hh_ = max(hh_, h + (self.height(c) - h) * w_)
            z = self.H / (hh_ * 1.6) if not portrait else self.W / 760.0
            return cx, gy - (0.30 if portrait else 0.40) * self.H / z, z
        if typ in ("two", "ots") and to:
            ox = self.perf[to].x_at(t)
            tall = max(h, self.height(to))
            if typ == "two":
                cx = (sx + ox) / 2
                span = abs(sx - ox) + 520
                z = min(self.W / span, self.H / (tall * 1.55)) if not portrait else self.W / (span * 0.75)
                return cx, min(gy, self.gy_eff(to)) - (0.30 if portrait else 0.40) * self.H / z, z
            # over the shoulder: the listener's shoulder fills one edge (foreground), the speaker sits on the
            # opposite third, framed from the waist up
            z = self.H / (tall * 0.95) if not portrait else self.W / 650.0
            vw = self.W / z
            cx = sx - look * vw * 0.12 + (ox - sx) * 0.15
            cy = gy - h * 0.66
            return cx, cy, z
        if typ == "full":
            z = self.H * 0.66 / h if not portrait else self.W / 760.0
            return sx + look * 60, gy - (0.30 if portrait else 0.42) * self.H / z, z
        if typ in ("ecu", "close", "reaction", "medium") and self.puppets[who].spec.get("animal"):
            # an animal: its head is not on top of a body like a person's - frame the whole animal, close
            z = self.H / (h * (1.45 if typ == "medium" else 1.2)) if not portrait else self.W / max(300.0, h * 1.3)
            if shot.get("move") == "push":
                z *= 1.0 + 0.06 * G.ease(u)
            return sx + look * 40, gy - h * 0.52, min(z, self.H / max(520.0, h * 2.2))
        if typ == "ecu":                                      # extreme close-up: the eyes
            hh = self.puppets[who].P["head_h"] * self.cscale(who)
            z = self.H / (hh * 1.2)
            return sx, gy - h + hh * 0.42, z
        if typ in ("close", "reaction"):                      # head and shoulders, looking room in front
            hh = self.puppets[who].P["head_h"] * self.cscale(who)
            z = self.H / (hh * 2.6) if not portrait else self.W / (hh * 2.4)
            vw = self.W / z
            cx = sx + look * vw * 0.10
            cy = gy - h + hh * 0.95
            if shot.get("move") == "push":
                z *= 1.0 + 0.07 * G.ease(u)
            return cx, cy, z
        # medium: from the knees / waist up
        z = self.H / (h * 0.78) if not portrait else self.W / 620.0
        vw = self.W / z
        return sx + look * vw * 0.12, gy - h * 0.62, z

    def shot_at(self, t):
        cur = None
        for s_ in self.shots:
            if s_["t0"] <= t:
                cur = s_
        return cur

    def camera(self, t):
        """(centre x, centre y, zoom) in world px. Hard cuts between shots, or an eased camera move when the shot
        asks for it ('trans': 'ease'); never a dissolve."""
        idx = None
        for i, s_ in enumerate(self.shots):
            if s_["t0"] <= t:
                idx = i
        if idx is None:
            cx, cy, z = self.framing({"type": "wide"}, t)
        else:
            shot = self.shots[idx]
            cx, cy, z = self.framing(shot, t)
            ed = shot.get("ease", 0.9)
            if shot.get("trans") == "ease" and idx > 0 and t - shot["t0"] < ed:
                p0 = self.framing(self.shots[idx - 1], shot["t0"])
                k = G.ease((t - shot["t0"]) / ed)
                cx, cy = p0[0] + (cx - p0[0]) * k, p0[1] + (cy - p0[1]) * k
                z = math.exp(math.log(p0[2]) + (math.log(z) - math.log(p0[2])) * k)
        look = self.look()
        if look != "flat" and idx is not None:             # CINEMATIC: a camera operator's hand - a slow, tiny drift
            amp = (0.006 if look == "horror" else 0.0035) * self.W / z
            typ = self.shots[idx].get("type")
            if typ not in ("track",):
                k_ = 0.45 if typ in ("establish", "wide") else 1.0
                cx += k_ * amp * (math.sin(t * 0.61 + 1.3) + 0.45 * math.sin(t * 1.37))
                cy += k_ * amp * 0.6 * (math.sin(t * 0.47) + 0.4 * math.sin(t * 1.91 + 0.7))
        if self.world is not None and hasattr(self.world, "shake"):   # the camera rides with the carriage
            sx_, sy_ = self.world.shake(t)
            cx, cy = cx + sx_ / max(0.3, z) * 0.6, cy + sy_ / max(0.3, z) * 0.6
        vw, vh = self.W / z, self.H / z
        cx = min(max(cx, vw / 2 - 700), BG.WORLD_W + 700 - vw / 2)
        # a tall (portrait) view is higher than the world picture: the sky and the ground are extended with flat
        # colour, so the camera keeps the people in the lower-middle of the frame instead of at the very bottom
        cy = min(max(cy, vh / 2 - 400), BG.WORLD_H + 150 - vh / 2) if vh < BG.WORLD_H else min(cy, BG.WORLD_H + vh * 0.12 - vh / 2)
        return cx, cy, z

    # -------------------------------------------------------------- render
    def render_frame(self, t, bg=None, subtitles=None):
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, self.W, self.H)
        ctx = cairo.Context(surf)
        cam = self.camera(t)
        cx, cy, z = cam
        m = cairo.Matrix()
        m.translate(self.W / 2, self.H / 2)
        m.scale(z, z)
        m.translate(-cx, -cy)
        if self.world is not None:
            self.world.draw_back(ctx, self.W, self.H, cam, t)
            sh = self.shot_at(t)
            blur = {"close": 3.0, "reaction": 3.0, "ecu": 4.5, "ots": 2.0, "medium": 1.2}.get(sh.get("type") if sh else "", 0)
            if blur:                                           # depth of field: the background softens in close shots
                import cv2
                surf.flush()
                arr = np.ndarray((self.H, surf.get_stride() // 4, 4), np.uint8, surf.get_data())
                k = blur * self.H / 1080.0
                arr[:, : self.W] = cv2.GaussianBlur(arr[:, : self.W], (0, 0), k)
                surf.mark_dirty()
            ctx.set_matrix(m)
            ctx.set_source_rgb(*G.rgb("#c9a172"))               # ground below the world picture (portrait)
            ctx.rectangle(-5000, BG.WORLD_H + 190, 15000, 5000)
            ctx.fill()
        else:
            ctx.set_matrix(m)
            ctx.set_source_rgb(0.56, 0.79, 0.94)
            ctx.rectangle(-5000, -5000, 15000, 5000 + 10)
            ctx.fill()
            ctx.set_source_surface(bg, 0, 0)
            ctx.paint()
        sun = self.world.sun_dx(t) if self.world is not None else 0.0
        items = [(self.depth[c], 1, i, c) for i, c in enumerate(self.order)]
        sh_ = self.shot_at(t)
        if self.life and (sh_ or {}).get("type") not in ("close", "ecu", "reaction", "ots"):
            # passers-by inside the picture (not in the close shots: the face is the picture there)
            vw_ = self.W / cam[2]
            for i, c in enumerate(self.life):
                if abs(self.perf[c].x_at(t) - cam[0]) < vw_ / 2 + 400:
                    items.append((self.depth[c], 1, 100 + i, c))
        items += [(v.z, 0, i, vid) for i, (vid, v) in enumerate(self.vehicles.items()) if v.lane != "tracks"]
        items.sort(key=lambda r: (-r[0], r[1], r[2]))            # far first; at one depth the vehicle, then people
        props = {pr["behind"]: pr for pr in self.props}
        for _z, kind, _i, cid in items:
            if kind == 0:
                v = self.vehicles[cid]
                inside = [c for c in self.order if (self.riding(c, t) or [0, 0, None])[2] == cid]
                if v.kind in ("auto", "toto") and inside:     # people sit IN it: back, passengers, front
                    self._draw_vehicle(ctx, cid, t)
                    for c in inside:
                        self._draw_person(ctx, c, t, sun)
                    self._draw_vehicle(ctx, cid, t, part="front")
                elif v.kind in ("bus", "tram") and inside:     # faces in the windows
                    self._draw_vehicle(ctx, cid, t)
                    sc_v = self.vscale(cid)
                    rects = v.window_rects(v.x_at(t), self.vgy(cid), sc_v, t)
                    ctx.save()
                    ctx.new_path()
                    for (rx, ry, rw, rh) in rects:
                        ctx.rectangle(rx, ry, rw, rh)
                    ctx.clip()
                    wy = min(r_[1] for r_ in rects)
                    wh = rects[0][3]
                    for c in inside:                           # seated so the head and shoulders fill the window
                        P_ = self.puppets[c].P
                        sit_h = (P_["foot_h"] + P_["shin"] + P_["thigh"] * 0.34 + P_["pelvis_up"] + P_["torso"] + P_["neck"]
                                 + P_["head_h"] * 1.05) * self.cscale(c)
                        lift = self.gy(c) - (wy + 0.12 * wh) - sit_h
                        self._draw_person(ctx, c, t, sun, lift=lift, shadow=False)
                    ctx.restore()
                    ctx.save()                                 # the glass over them
                    for (rx, ry, rw, rh) in rects:
                        ctx.rectangle(rx, ry, rw, rh)
                    ctx.set_source_rgba(0.75, 0.85, 0.95, 0.18)
                    ctx.fill()
                    ctx.restore()
                else:
                    self._draw_vehicle(ctx, cid, t)
                continue
            pf = self.perf[cid]
            st, x = pf.state(t, self)
            sc_, gy = self.cscale(cid), self.gy(cid)
            rd = self.riding(cid, t)
            if rd:
                v = self.vehicles[rd[2]]
                if not v.open_ride() or v.kind in ("auto", "toto"):
                    continue                                   # drawn with the vehicle (in it / in its windows)
            self._draw_person(ctx, cid, t, sun, st=st, x=x)
        if self.world is not None:
            self.world.draw_front(ctx, self.W, self.H, cam, t)
        for t0_, t1_, who_ in self.transforms:                 # the screen at the moment of the change
            k = t - t0_
            if 0.0 <= k <= 1.6:
                ctx.save()
                ctx.identity_matrix()
                if 0.25 <= k < 1.0:                            # the light pulses darker
                    ctx.set_source_rgba(0.0, 0.0, 0.05, 0.35 * abs(math.sin(k * 22)))
                    ctx.paint()
                if 0.95 <= k < 1.2:                            # a cold flash as the ghost appears
                    ctx.set_source_rgba(0.85, 0.92, 1.0, 0.6 * (1 - abs(k - 1.05) / 0.15))
                    ctx.paint()
                if 1.0 <= k <= 1.6:                            # a red vignette
                    g = cairo.RadialGradient(self.W / 2, self.H / 2, self.H * 0.3, self.W / 2, self.H / 2, self.H * 0.9)
                    g.add_color_stop_rgba(0, 0.5, 0, 0, 0)
                    g.add_color_stop_rgba(1, 0.5, 0, 0, 0.45 * (1 - (k - 1.0) / 0.6))
                    ctx.set_source(g)
                    ctx.paint()
                ctx.restore()
        buf = np.ndarray((self.H, self.W, 4), np.uint8, surf.get_data()).copy()
        img = buf[:, :, :3]
        if self.look() != "flat":
            img = self._grade(np.ascontiguousarray(img), t)
        if subtitles:
            img = subtitles(img, t)
        return img

    # -------------------------------------------------------------- the cinematic look (owner, 23 Nov 2026)
    def look(self):
        """horror = film look (cool shadows, warm light, deep vignette, grain); kids = bright, warm, soft; flat = the
        plain TV cartoon. TVTOON_LOOK overrides the scene's own choice."""
        lk = (os.environ.get("TVTOON_LOOK") or self.spec.get("look") or "cinematic").strip().lower()
        return {"cinematic": "horror" if self.spec.get("horror") else "film"}.get(lk, lk)

    def _grade_setup(self, look):
        import cv2
        W, H = self.W, self.H
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        strength = {"horror": 0.3, "film": 0.18, "kids": 0.07}.get(look, 0.18)      # (owner 24 Nov: brighter videos)
        vig = 1.0 - strength * np.clip((r - 0.35) / 0.65, 0, 1) ** 1.7
        self._vig = cv2.merge([(vig * 255).astype(np.uint8)] * 3)
        rng = np.random.default_rng(7)
        self._grain = [(rng.normal(128, 40, (H // 2, W // 2)).clip(0, 255).astype(np.uint8)) for _ in range(6)]
        self._grain = [cv2.merge([cv2.resize(g, (W, H), interpolation=cv2.INTER_LINEAR)] * 3) for g in self._grain]
        self._luts = {}

    def _lut(self, look, hour):
        """a film curve per channel for the time of day: a soft S-curve, warm light, cool shadows (teal / amber)"""
        key = (look, round(hour * 2) / 2)
        if key in self._luts:
            return self._luts[key]
        x = np.arange(256, dtype=np.float32) / 255.0
        night = hour >= 19.5 or hour < 5.0
        dusk = 16.5 <= hour < 19.5 or 5.0 <= hour < 7.0
        s_amt = {"horror": 0.14, "film": 0.1, "kids": 0.05}.get(look, 0.1)
        # brighter (owner, 24 Nov 2026): the picture is exposed up (more at night, so the faces are always seen);
        # TVTOON_BRIGHT scales it (1.0 = this, 1.2 = still brighter, 0.8 = darker)
        try:
            bk = float(os.environ.get("TVTOON_BRIGHT") or 1.0)
        except ValueError:
            bk = 1.0
        gain = 1.0 + bk * ({"horror": 0.16, "film": 0.12, "kids": 0.12}.get(look, 0.1) + (0.22 if night else 0.0))
        xe = 1.0 - (1.0 - x) ** gain                                         # lifts darks and mids, keeps whites
        curve = xe + s_amt * (xe - 0.5) * (1 - np.abs(2 * xe - 1)) * 1.6      # contrast around the middle
        sh = np.clip(1 - x * 2.2, 0, 1)                                    # how much a value is a shadow
        hi = np.clip(x * 2.0 - 1.0, 0, 1)                                  # ... a highlight
        if look == "horror":
            warm = (0.05, 0.015, -0.04) if not night else (0.02, 0.0, -0.02)
            cool = (-0.05, 0.0, 0.06) if night else (-0.03, 0.005, 0.035)
            lift = 0.0
        elif look == "kids":
            warm, cool, lift = (0.035, 0.02, -0.01), (0.0, 0.01, 0.025), 0.02
        else:
            warm, cool, lift = ((0.06, 0.02, -0.035) if dusk else (0.03, 0.012, -0.015)), (-0.02, 0.0, 0.03), 0.01
        chans = []
        for c in range(3):                                 # the frame is B, G, R (cairo): the tuples above are R, G, B
            v = curve + warm[2 - c] * hi + cool[2 - c] * sh * (0.6 if look == "horror" else 1.0) + lift * (1 - x)
            chans.append((np.clip(v, 0, 1) * 255).astype(np.uint8))
        lut = np.dstack(chans).reshape(1, 256, 3)
        self._luts[key] = lut
        return lut

    def _grade(self, img, t):
        import cv2
        look = self.look()
        if not hasattr(self, "_vig"):
            self._grade_setup(look)
        hour = self.world.hour(t) if self.world is not None else 12.0
        out = cv2.LUT(img, self._lut(look, hour))
        # bloom: light spills from the lamps, the windows, the sun - the brightest parts, blurred, added back
        small = cv2.resize(out, (self.W // 4, self.H // 4), interpolation=cv2.INTER_AREA)
        thr = 200 if look != "horror" else 185
        bright = cv2.subtract(small, (thr, thr, thr, 0))
        bright = cv2.GaussianBlur(bright, (0, 0), 6)
        bright = cv2.resize(bright, (self.W, self.H), interpolation=cv2.INTER_LINEAR)
        out = cv2.addWeighted(out, 1.0, bright, {"horror": 0.9, "film": 0.7, "kids": 0.5}.get(look, 0.6), 0)
        out = cv2.multiply(out, self._vig, scale=1 / 255.0)                # the lens vignette
        if look in ("horror", "film"):                                     # a fine film grain, alive every frame
            g = self._grain[int(t * 24) % len(self._grain)]
            a = 0.035 if look == "horror" else 0.02
            out = cv2.addWeighted(out, 1.0, g, a, -a * 128)
        return out

    def _draw_person(self, ctx, cid, t, sun, st=None, x=None, lift=0.0, shadow=True):
        if True:
            pf = self.perf[cid]
            if st is None:
                st, x = pf.state(t, self)
            sc_, gy = self.cscale(cid), self.gy(cid) - lift
            props = {pr["behind"]: pr for pr in self.props}
            ghost = pf.pp.spec.get("ghost")
            if ghost:
                ctx.push_group()
            if cid in props and props[cid]["type"] == "mora":
                pr = props[cid]
                BG.mora(ctx, pr["x"], gy, pr["h"], pr["w"])
            if cid in props and props[cid]["type"] == "side_seat" and st.get("side", {}).get("mode") == "sit":
                self._side_seat(ctx, cid, x, gy, sc_, st["side"]["d"])
            if not ghost and shadow:
                self._shadow(ctx, x, pf.pp.P["H"] * sc_, gy, sun)
            ctx.save()
            if st.get("float_y"):                              # a ghost floating, a child jumping
                ctx.translate(0, -st.get("float_y", 0.0))
            q = st.get("squash", 0.0)
            if q:                                              # squash and stretch from the feet, volume kept
                ctx.translate(x, gy)
                ctx.scale(1.0 / math.sqrt(1.0 + q), 1.0 + q)
                ctx.translate(-x, -gy)
            pf.pp.draw(ctx, st, x, gy, sc_, solver=AN.solve_legs)
            ctx.restore()
            if ghost:                                          # a ghost: see-through, glowing, its feet fade away
                pat = ctx.pop_group()
                h_ = pf.pp.P["H"] * sc_
                lift = st.get("float_y", 0.0)
                ctx.save()
                tint = G.rgb(ghost.get("tint", "#dfefff"))
                rg = cairo.RadialGradient(x, gy - h_ * 0.55 - lift, 10, x, gy - h_ * 0.55 - lift, h_ * 0.75)
                rg.add_color_stop_rgba(0, *tint, 0.28)
                rg.add_color_stop_rgba(1, *tint, 0.0)
                ctx.set_source(rg)
                ctx.arc(x, gy - h_ * 0.55 - lift, h_ * 0.75, 0, 2 * math.pi)
                ctx.fill()
                ctx.set_source(pat)
                mg = cairo.LinearGradient(0, gy - lift - h_ * 0.35, 0, gy - lift + h_ * 0.02)
                a_ = float(ghost.get("alpha", 0.88)) * (0.9 + 0.1 * math.sin(t * 2.3))
                mg.add_color_stop_rgba(0, 0, 0, 0, a_)
                mg.add_color_stop_rgba(1, 0, 0, 0, 0.0)
                m0_ = ctx.get_matrix()
                ctx.mask(mg)
                ctx.restore()

    def _side_seat(self, ctx, cid, x, gy, sc_, d):
        """a seat seen from the side under a passenger: cushion and seat box to the floor, the backrest behind the
        back (the passenger really sits on something)"""
        P = self.puppets[cid].P
        col = G.rgb(getattr(self.world, "SEAT", "#7a5a3a")) if self.world is not None else G.rgb("#7a5a3a")
        frame = G.rgb("#3a3a3a" if getattr(self.world, "KIND", "") != "tram" else "#5a3a1e")
        seat_y = gy - (P["foot_h"] + P["shin"] + P["thigh"] * 0.34) * sc_
        back = x - d * (0.06 * P["leg"] + P["hip"] * 0.75) * sc_      # just behind the passenger's back
        front = x + d * P["thigh"] * 0.78 * sc_
        th = P["thigh"] * 0.16 * sc_
        top_back = seat_y - (P["pelvis_up"] + P["torso"] * 1.08) * sc_   # a high, padded backrest (train / bus seat)
        ctx.save()
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        lo, hi = min(back, front), max(back, front)
        ctx.new_path()                                         # the seat box (darker) and its legs
        ctx.rectangle(lo + 0.08 * (hi - lo), seat_y + th, (hi - lo) * 0.84, gy - seat_y - th - 0.02 * P["H"] * sc_)
        ctx.set_source_rgb(*G.shade(col, 0.55))
        ctx.fill_preserve()
        ctx.set_source_rgb(*LINE_)
        ctx.set_line_width(3)
        ctx.stroke()
        for xx in (lo + 0.12 * (hi - lo), hi - 0.12 * (hi - lo)):
            ctx.new_path()
            ctx.rectangle(xx - 6, gy - 0.03 * P["H"] * sc_, 12, 0.03 * P["H"] * sc_)
            ctx.set_source_rgb(*frame)
            ctx.fill()
        bw = P["hip"] * 0.5 * sc_                              # the backrest, its padding toward the passenger
        bx0 = back - bw if d > 0 else back
        ctx.new_path()
        r_ = bw * 0.45
        ctx.move_to(bx0, seat_y + th)
        ctx.line_to(bx0, top_back + r_)
        ctx.arc(bx0 + r_, top_back + r_, r_, math.pi, 1.5 * math.pi)
        ctx.line_to(bx0 + bw - r_, top_back)
        ctx.arc(bx0 + bw - r_, top_back + r_, r_, 1.5 * math.pi, 2 * math.pi)
        ctx.line_to(bx0 + bw, seat_y + th)
        ctx.close_path()
        ctx.set_source_rgb(*col)
        ctx.fill_preserve()
        ctx.set_source_rgb(*LINE_)
        ctx.stroke()
        ctx.new_path()                                         # the cushion
        ctx.rectangle(lo, seat_y - th * 0.15, hi - lo, th * 1.15)
        ctx.set_source_rgb(*G.shade(col, 1.15))
        ctx.fill_preserve()
        ctx.set_source_rgb(*LINE_)
        ctx.stroke()
        ctx.new_path()                                         # the frame bar under the cushion
        ctx.rectangle(lo, seat_y + th, hi - lo, th * 0.35)
        ctx.set_source_rgb(*frame)
        ctx.fill()
        ctx.restore()

    def _shadow(self, ctx, x, h, gy=None, sun=0.0):
        gy = BG.GROUND if gy is None else gy
        ctx.save()
        ctx.translate(x + sun * h * 0.25, gy)                  # the shadow leans away from the low sun
        ctx.scale(1 + sun * 0.8, 0.16)
        ctx.arc(0, 0, h * 0.2, 0, 2 * math.pi)
        ctx.restore()
        ctx.set_source_rgba(0, 0, 0, 0.16)
        ctx.fill()

    def audio_track(self, path):
        n = int((self.duration + 0.5) * AUDIO_SR)
        mix = np.zeros(n, np.float32)
        for ln in self.lines:
            if not ln["audio"]:
                continue
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", ln["audio"], "-ac", "1", "-ar", str(AUDIO_SR), "-f", "f32le", "-"],
                                 capture_output=True, check=True).stdout
            a = np.frombuffer(raw, np.float32)
            i = int(ln["t0"] * AUDIO_SR)
            mix[i:i + len(a)] += a[: max(0, n - i)]
        mix = np.clip(mix, -1, 1)
        pcm = (mix * 32767).astype(np.int16).tobytes()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(AUDIO_SR), "-ac", "1", "-i", "-", path], input=pcm,
                       check=True)
        return path


def subtitle_maker(scene, font_path, size_frac=0.045):
    from PIL import Image, ImageDraw, ImageFont
    cache = {}
    try:
        from fontTools.ttLib import TTFont
        cmap = set(TTFont(font_path).getBestCmap().keys())
    except Exception:
        cmap = None
    font = ImageFont.truetype(font_path, int(scene.H * size_frac) if scene.W > scene.H else int(scene.W * 0.06),
                              layout_engine=ImageFont.Layout.RAQM)

    def pages_for(ln):
        """a long line is shown in pages of two rows, each page for its share of the spoken time"""
        name = "কথক" if ln.get("narrator") else (getattr(scene, "names", {}).get(ln["who"]) or CH.get(ln["who"])["name_bn"])
        txt = ln["text"]
        if cmap is not None:                               # characters the Bengali font cannot draw become spaces
            txt = "".join(c if (ord(c) in cmap or c == " ") else " " for c in txt)
            txt = " ".join(txt.split())
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        words, rows, cur = txt.split(" "), [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if probe.textlength(test, font=font) > scene.W * 0.86 and cur:
                rows.append(cur)
                cur = w
            else:
                cur = test
        rows.append(cur)
        groups = [rows[i:i + 2] for i in range(0, len(rows), 2)] or [[""]]
        nf = font.font_variant(size=int(font.size * 0.78))
        if cmap is not None and any(ord(ch) not in cmap and not ch.isspace() for ch in name):   # a name in English letters
            latin = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                      "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf") if os.path.exists(f)), None)
            nf = ImageFont.truetype(latin, nf.size) if latin else ImageFont.load_default(size=nf.size)
        out = []
        for g in groups:
            im = Image.new("RGBA", (scene.W, int(scene.H * 0.24)), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            y = 4
            nw = d.textlength(name, font=nf)                 # the speaker's name, in yellow, above
            d.text(((scene.W - nw) / 2, y), name, font=nf, fill=(255, 214, 80, 255), stroke_width=3, stroke_fill=(20, 12, 8, 255))
            y += int(nf.size * 1.3)
            for l_ in g:
                tw = d.textlength(l_, font=font)
                d.text(((scene.W - tw) / 2, y), l_, font=font, fill=(255, 255, 255, 255), stroke_width=4,
                       stroke_fill=(20, 12, 8, 255))
                y += int(font.size * 1.35)
            out.append((sum(len(x) for x in g) + 1, np.array(im)))
        return out

    def apply(img, t):
        ln = next((l for l in scene.lines if l["t0"] <= t < l["t1"] + 0.2), None)
        if not ln:
            return img
        key = (ln["t0"], ln["text"])
        if key not in cache:
            cache[key] = pages_for(ln)
        pages = cache[key]
        total = sum(n for n, _ in pages)
        u = max(0.0, min(0.999, (t - ln["t0"]) / max(0.1, ln["t1"] - ln["t0"]))) * total
        ov = pages[-1][1]
        for n, im_ in pages:
            if u < n:
                ov = im_
                break
            u -= n
        h = ov.shape[0]
        y0 = img.shape[0] - h - int(scene.H * 0.03)
        a = ov[:, :, 3:4] / 255.0
        region = img[y0:y0 + h]
        region[:] = (region * (1 - a) + ov[:, :, 2::-1] * a).astype(np.uint8)
        return img
    return apply


def render(spec, out_path, work_dir=None, log=print, chunk_sec=10.0):
    """render a scene to MP4 (H.264 + AAC). Rendering goes in chunks saved to work_dir, so an interrupted job resumes
    where it stopped (finished chunks with the same scene hash are reused)."""
    sc = Scene(spec)
    work_dir = work_dir or os.path.splitext(out_path)[0] + "_work"
    os.makedirs(work_dir, exist_ok=True)
    h = hashlib.sha1(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    bg = None if sc.world is not None else BG.LOCATIONS[spec.get("location", "village_courtyard")]()
    font = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "NotoSansBengali-Bold.ttf")
    subs = subtitle_maker(sc, font) if spec.get("subtitles", True) and os.path.exists(font) else None
    n = int(round(sc.duration * sc.fps))
    per = int(chunk_sec * sc.fps)
    files = []
    status = {"scene_hash": h, "frames": n, "chunks": [], "duration": sc.duration}
    for k in range(0, n, per):
        cf = os.path.join(work_dir, f"chunk_{h}_{k // per:04d}.mp4")
        files.append(cf)
        if os.path.exists(cf) and os.path.getsize(cf) > 1000:
            status["chunks"].append({"file": cf, "reused": True})
            # the performances are stateful (springs): run the skipped frames quickly without drawing
            for f in range(k, min(n, k + per)):
                for cid in sc.order:
                    sc.perf[cid].state(f / sc.fps, sc)
            continue
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{sc.W}x{sc.H}",
                              "-r", str(sc.fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                              "-pix_fmt", "yuv420p", cf + ".part.mp4"], stdin=subprocess.PIPE)
        for f in range(k, min(n, k + per)):
            p.stdin.write(sc.render_frame(f / sc.fps, bg, subs).tobytes())
        p.stdin.close()
        p.wait()
        os.replace(cf + ".part.mp4", cf)
        status["chunks"].append({"file": cf, "reused": False})
        log(f"  chunk {k // per + 1}/{(n + per - 1) // per} done")
    lst = os.path.join(work_dir, f"list_{h}.txt")
    with open(lst, "w") as f:
        for cf in files:
            f.write(f"file '{os.path.abspath(cf)}'\n")
    aud = sc.audio_track(os.path.join(work_dir, f"audio_{h}.wav"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", aud, "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "128k", "-shortest", "-movflags", "+faststart", out_path], check=True)
    status["out"] = out_path
    status["lines"] = [{k_: v for k_, v in ln.items() if k_ != "audio"} for ln in sc.lines]
    with open(os.path.splitext(out_path)[0] + "_status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1, default=float)
    return status, sc
