"""automatic performance: every frame of a character is computed from a few high-level tracks (where to stand / walk,
sit, speak, emotion, gesture, look-at) plus automatic layers (blink, eye darts, breathing, weight shift, head motion,
hair and cloth springs, talk beats, listener reactions). No frame-by-frame animation is needed."""
import math
import random
import zlib

from tvtoon import face as FACE
from tvtoon import geom as G
from tvtoon import lipsync as LS
from tvtoon import rig as R

D = math.radians

# arm gestures: (upper arm, forearm, hand) as OUTWARD angles in degrees (0 = straight down, + = raised out to the
# side, - = across the body), hand shape; or 'ik' with a target in torso units (x: + = outward, y: + = down)
GESTURES = {
    "rest": {"a": (11, 4, 4, "relax")},
    "explain": {"a": (24, 78, 100, "open")},
    "explain_both": {"a": (24, 78, 100, "open"), "b": (24, 78, 100, "open")},
    "point": {"a": (78, 84, 88, "point")},
    "point_up": {"a": (150, 168, 170, "point")},
    "wave": {"a": (120, 165, 170, "open"), "osc": ("a", "farm", 22, 2.2)},
    "raise_hand": {"a": (140, 168, 172, "open")},
    "shrug": {"a": (38, 112, 128, "open"), "b": (38, 112, 128, "open")},
    "namaste": {"a": ("ik", -0.02, 0.38, -178, "flat"), "b": ("ik", -0.02, 0.38, -178, "flat")},
    "clap": {"a": ("ik", -0.02, 0.45, -175, "flat"), "b": ("ik", -0.02, 0.45, -175, "flat"), "clap": 3.0},
    "hips": {"a": ("ik", 0.92, 0.95, 60, "fist"), "b": ("ik", 0.92, 0.95, 60, "fist")},
    "scared": {"a": ("ik", 0.95, -0.12, -165, "open"), "b": ("ik", 0.95, -0.12, -165, "open"), "over": True},
    "think": {"a": ("ik", 0.1, -0.14, -170, "fist"), "over": True},
    "belly_laugh": {"a": ("ik", 0.55, 0.92, -110, "open"), "b": ("ik", 0.55, 0.92, -110, "open")},
}


def gesture_weight(since, until, t_in=0.42, t_out=0.3):
    """pose-to-pose with ANTICIPATION (the arm first dips the other way), an OVERSHOOT past the pose and a settle
    (follow-through); a softer ease out. Can be < 0 or > 1 on purpose."""
    if since < 0 or until < 0:
        return 0.0
    w_in = 1.0
    if since < t_in:
        u = since / t_in
        if u < 0.18:
            w_in = -0.12 * math.sin(math.pi * u / 0.18)
        else:
            v = (u - 0.18) / 0.82
            c1 = 1.70158 * 0.6
            w_in = 1 + (c1 + 1) * (v - 1) ** 3 + c1 * (v - 1) ** 2          # ease-out-back
    w_out = G.ease(until / t_out)
    if w_in < 0:
        return w_in * w_out
    return w_in if w_out >= 1.0 else min(w_in, w_out)


def arm_angles(g):
    """outward degrees -> local rotations to add to the rest pose, for side a and side b"""
    out = {}
    for side in ("a", "b"):
        spec = g.get(side)
        if spec is None or spec[0] == "ik":
            continue
        ua, fa, ha, shape = spec
        s = 1 if side == "a" else -1
        rest_u, rest_f = 11, -7
        out[side] = ({"uarm_" + side: s * D(ua - rest_u), "farm_" + side: s * D((fa - ua) - rest_f),
                      "hand_" + side: s * D(ha - fa)}, shape)
    return out


class Perf:
    """one character's performance in a scene"""

    def __init__(self, cid, puppet, x, seed=0):
        self.cid, self.pp, self.x0 = cid, puppet, x
        self.moves = []      # (t0, t1, x0, x1, gait)
        self.sits = []       # (t0, t1, seat_y_world_units_above_ground)
        self.speech = []     # (t0, t1, events, loudness, hop, emotion, to)
        self.emotions = []   # (t0, t1, emotion)
        self.gestures = []   # (t0, t1, name, side, target_x)
        self.looks = []      # (t0, t1, target_x or None)
        self.facing = []     # (t0, turn)
        self.lookbacks = []  # (t0, t1): looking back over the shoulder
        self.acts = []       # (t0, t1, kind): jump / dance / nod / shake / bow / fall (actions.py, from the story)
        self.side_talk = False
        self.facing_side = None
        self.rng = random.Random(zlib.crc32(cid.encode()) % 1000 + seed)   # stable: every character blinks on its own clock
        self.blinks = self._blinks(600.0)
        self.darts = self._darts(600.0)
        self.hair = [0.0, 0.0, 0.0, 0.0]   # x, y, vx, vy
        self.cloth = [0.0, 0.0]
        self.prev_head = None
        self.prev_x = None
        self.last_t = None

    # ----------------------------------------------------------------- automatic schedules
    def _blinks(self, T):
        out, t = [], self.rng.uniform(0.5, 2.0)
        while t < T:
            out.append(t)
            if self.rng.random() < 0.18:
                out.append(t + 0.32)                  # a double blink now and then
            t += self.rng.uniform(2.2, 5.0)
        return out

    def _darts(self, T):
        out, t = [], 0.0
        while t < T:
            out.append((t, (self.rng.uniform(-0.45, 0.45), self.rng.uniform(-0.25, 0.25))))
            t += self.rng.uniform(0.8, 2.6)
        return out

    # ----------------------------------------------------------------- queries
    def x_at(self, t):
        sc = getattr(self, "scene", None)
        if sc is not None:                                     # on a vehicle: where its seat is
            for r_ in getattr(self, "rides", []):
                if r_[0] <= t < r_[1]:
                    return sc.vehicle_seat_x(r_[2], r_[3], t, self.cid)
        x = self.x0
        for t0, t1, xa, xb, gait in self.moves:
            if t >= t1:
                x = xb
            elif t >= t0:
                return xa + (xb - xa) * (t - t0) / max(1e-6, t1 - t0)
        return x

    def moving(self, t):
        for m in self.moves:
            if m[0] <= t < m[1]:
                return m
        return None

    def speaking(self, t):
        for s in self.speech:
            if s[0] <= t < s[1]:
                return s
        return None

    def emotion(self, t):
        e = "neutral"
        for t0, t1, em in self.emotions:
            if t0 <= t < t1:
                e = em
        return e

    def gesture(self, t):
        for g in self.gestures:
            if g[0] <= t < g[1]:
                return g
        return None

    def sit_amount(self, t):
        for s_ in self.sits:
            t0, t1, seat = s_[:3]
            if t0 - 0.9 <= t < t1 + 0.9:
                a = G.ease((t - (t0 - 0.9)) / 0.9) if t < t0 else 1.0 if t < t1 else 1 - G.ease((t - t1) / 0.9)
                return a, seat
        return 0.0, None

    def sit_side(self, t):
        for s_ in self.sits:
            if s_[0] - 0.9 <= t < s_[1] + 0.9 and len(s_) > 3:
                return s_[3]
        return None

    def lookback(self, t):
        for t0, t1 in self.lookbacks:
            if t0 <= t < t1:
                return min(G.ease((t - t0) / 0.3), G.ease((t1 - t) / 0.3))
        return 0.0

    def side_want(self, t, scene, x, tgt, mv, ride):
        """the facing (+1 / -1) when the TRUE SIDE VIEW is wanted (walking, riding, sitting sideways, talking face to
        face, looking back), else None"""
        if mv:
            return 1.0 if mv[3] > mv[2] else -1.0
        if ride:
            v = scene.vehicles[ride[2]]
            return v.direction(t)
        if tgt is None:                                     # nobody speaks: toward the nearest other person
            others = [scene.x_of(c, t) for c in scene.order if c != self.cid] if hasattr(scene, "order") else []
            if others:
                tgt = min(others, key=lambda o: abs(o - x))
        towards = (1.0 if tgt > x else -1.0) if tgt is not None else None
        ss = self.sit_side(t)
        if ss is not None and self.sit_amount(t)[0] > 0:
            return ss if ss else (towards or 1.0)
        if self.side_talk and towards is not None:
            return towards
        if self.lookback(t) > 0 or self.facing_side:
            return towards or self.facing_side or (1.0 if getattr(self, "turn_s", 0.0) >= 0 else -1.0)
        return None

    # ----------------------------------------------------------------- the frame
    def state(self, t, scene):
        """the puppet state for time t + the character's world x"""
        forms = getattr(self, "forms", None)
        tf = getattr(self, "transform", None)
        changing = 0.0
        if forms:                                              # a ghost in disguise: which form is seen now
            if tf and t >= tf[0] + 1.0:
                self.pp = forms[1]
            elif tf and t >= tf[0] + 0.45:                     # the two forms flash in turn (TV horror change)
                self.pp = forms[int((t - tf[0]) * 14) % 2]
            else:
                self.pp = forms[0]
            if tf and tf[0] <= t < tf[0] + 1.0:
                changing = (t - tf[0]) / 1.0
        P = self.pp.P
        dt = 1 / 24.0 if self.last_t is None else max(1e-3, t - self.last_t)
        self.last_t = t
        x = self.x_at(t)
        ride = scene.riding(self.cid, t) if hasattr(scene, "riding") else None
        if ride:
            x = scene.vehicle_seat_x(ride[2], ride[3], t, self.cid)
        st = {"rot": {}, "len": {}, "hands": {"a": "relax", "b": "relax"}, "face": {}, "turn": 0.0, "t": t}
        rot = st["rot"]
        # ---- facing: toward who I speak to / listen to, else the camera
        sp = self.speaking(t)
        turn = 0.0
        tgt = None
        if sp and sp[6] is not None:
            tgt = scene.x_of(sp[6], t)
        elif not getattr(self, "extra", False):
            other = scene.current_speaker(t)
            if other and other != self.cid:
                tgt = scene.x_of(other, t)
        for t0, t1, lx in self.looks:
            if t0 <= t < t1:
                tgt = lx
        linger = False
        if tgt is None and getattr(self, "last_tgt", None) and t - self.last_tgt[1] < 7.0:
            # between the lines people still stand turned to the one they were talking with (not to the camera)
            ox_ = scene.x_of(self.last_tgt[0], t) if self.last_tgt[0] else None
            if ox_ is not None and abs(ox_ - x) < 1100:
                tgt = ox_
                linger = True
        elif tgt is not None:
            who_ = sp[6] if sp and sp[6] is not None else scene.current_speaker(t)
            self.last_tgt = (who_, t)
        if tgt is not None and abs(tgt - x) > 5:                # turned to each other, like people really talk:
            near = abs(tgt - x) < 900                         # a deep three-quarter (body and head) toward the partner
            turn = (0.5 if linger else 0.72 if near else 0.55) * (1 if tgt > x else -1)
        mv = self.moving(t)
        if mv:
            turn = 0.6 if mv[3] > mv[2] else -0.6
        for t0, tv in self.facing:
            if t >= t0:
                turn = tv
        want = self.side_want(t, scene, x, tgt, mv, ride)
        if want is not None:
            turn = want                                         # turning to the side view (through the 3/4 view)
        # the turn is a SPRING (eyes go first, the head follows with a small overshoot and settles: follow-through)
        if not hasattr(self, "turn_s"):
            self.turn_s = turn
        if not hasattr(self, "turn_v"):
            self.turn_v = 0.0
        for _i in range(2):
            h_ = dt / 2
            self.turn_v += (55.0 * (turn - self.turn_s) - 9.5 * self.turn_v) * h_
            self.turn_s += self.turn_v * h_
        st["turn"] = max(-0.8, min(0.8, self.turn_s))
        side_d = (1.0 if self.turn_s > 0 else -1.0) if abs(self.turn_s) > 0.86 else None
        if ride and want is not None:                          # on a seat from the first frame: no turning on the saddle
            self.turn_s, self.turn_v, side_d = want, 0.0, want
        st["head_turn"] = st["turn"]
        # ---- breathing, weight shift, idle head
        br = math.sin(2 * math.pi * t / 3.6 + self.rng.random() * 0.0)
        rot["spine"] = D(0.6) * br + D(P.get("stoop", 0) * 40)
        sway = math.sin(2 * math.pi * t / 7.3 + len(self.cid))
        root_dx = sway * P["H"] * 0.004
        root_dy = 0.0
        rot["head"] = D(1.8) * math.sin(2 * math.pi * t / 4.1 + 1.3) + D(-P.get("stoop", 0) * 30)
        rot["neck"] = D(0.8) * math.sin(2 * math.pi * t / 5.7)
        for s in ("a", "b"):
            sgn = 1 if s == "a" else -1
            rot["uarm_" + s] = sgn * D(1.2) * br
        # ---- emotion and face
        emo = self.emotion(t)
        speaking = sp is not None
        fc = FACE.expression(emo, speaking=speaking)
        # ---- speech: visemes from the real audio + talk beats on the loud syllables
        if sp:
            t0 = sp[0]
            v = LS.viseme_at(sp[2], t - t0)
            fc["mouth"] = v
            loud, hop = sp[3], sp[4]
            i = int((t - t0) / hop)
            lv = float(loud[min(len(loud) - 1, max(0, i))]) if len(loud) else 0.0
            rot["head"] += D(3.2) * (lv - 0.5) * math.sin(2 * math.pi * (t - t0) * 0.9) + D(2.0) * lv
            fc["jaw"] = 0.25 * lv if v not in ("X", "MBP") else 0.0
        # ---- reactions of a listener
        other = scene.current_speaker(t)
        if not speaking and other and other != self.cid:
            oe = scene.perf[other].emotion(t - 0.35)
            if oe in ("surprised", "scared", "happy", "laughing", "sad", "angry") and emo == "neutral":
                fc = FACE.expression({"laughing": "happy", "angry": "sad"}.get(oe, oe))
                fc["mouth"] = "X"
                fc.pop("happy_closed", None)
            rot["head"] += D(2.5) * math.sin(2 * math.pi * t / 2.3) * 0.5      # listening nods
            if tgt is not None:                                                # and the head tilts toward the speaker
                rot["head"] += D(4.5) * (1 if tgt > x else -1)
        # ---- blink + eye darts
        if not fc.get("happy_closed"):
            lid = fc.get("lid", 1.0)
            for b in self.blinks:
                if b <= t < b + 0.16:
                    u = (t - b) / 0.16
                    lid = min(lid, abs(1 - 2 * u) ** 0.8)
                    break
                if b > t:
                    break
            fc["lid"] = lid
            if "look" not in fc:
                look = (0.0, 0.0)
                for td, lk in self.darts:
                    if td > t:
                        break
                    look = lk
                if tgt is not None:
                    look = (0.75 if tgt > x else -0.75, look[1] * 0.3)
                fc["look"] = look
        if changing > 0:                                       # the change: eyes wide, mouth open, the head thrown back
            fc.update({"wide": 1.0, "brow": "angry", "lid": 1.0, "look": (0.0, -0.4)})
            if not sp:
                fc["mouth"] = "A" if changing < 0.6 else "WIDE"
            rot["head"] = rot.get("head", 0.0) - D(10) * math.sin(math.pi * changing)
            rot["spine"] = rot.get("spine", 0.0) - D(6) * math.sin(math.pi * changing)
        st["face"] = fc
        # ---- the body acts the emotion (with anticipation / squash-and-stretch on the strong ones)
        act = emo
        if act == "neutral" and not speaking and other and other != self.cid:
            act = {"laughing": "happy", "angry": "sad"}.get(scene.perf[other].emotion(t - 0.35), "neutral")
        onset = next((t0_ for t0_, t1_, e_ in self.emotions if t0_ <= t < t1_ and e_ == act), t - 9.0)
        root_dx, root_dy = self._emotion_body(st, act, t, t - onset, P, root_dx, root_dy)
        fc["tear_t"] = t
        # ---- gestures (explicit or automatic talk gestures)
        g = self.gesture(t)
        gname = g[2] if g else None
        if gname is None and sp:
            u = (t - sp[0])
            gname = "explain" if (int(u / 2.4) % 2 == 0) else "rest"
            if sp[5] in ("surprised", "scared"):
                gname = "scared" if sp[5] == "scared" else "raise_hand"
            if sp[5] == "laughing":
                gname = "belly_laugh"
            if sp[5] == "angry":
                gname = "point"
        if gname is None and emo == "scared":
            gname = "scared"
        if gname is None and emo == "laughing":
            gname = "belly_laugh"
        if gname and gname != "rest":
            gd = GESTURES[gname]
            side = (g[3] if g and g[3] else None) or ("a" if st["turn"] < 0 else "b") if len([k for k in gd if k in ("a", "b")]) == 1 else None
            ga = dict(gd)
            if side == "b" and "a" in gd:                          # one-arm gestures use the arm on the chosen side
                ga = {k: v for k, v in gd.items() if k not in ("a", "b")}
                ga["b"] = gd["a"]
                if "osc" in gd:
                    ga["osc"] = ("b",) + gd["osc"][1:]
            # blend in / out over 0.25 s
            g0 = g[0] if g else sp[0] if sp else t
            g1 = g[1] if g else sp[1] if sp else t + 1
            w = gesture_weight(t - g0, g1 - t)
            self._apply_gesture(st, ga, w, t, P)
            st["_g"] = (gname, w)
            if gname in ("point", "point_up"):                     # the head and eyes follow the pointing hand
                arm_side = next(k for k in ga if k in ("a", "b"))
                dirx = -1.0 if arm_side == "a" else 1.0
                st["face"]["look"] = (0.9 * dirx, -0.4 if gname == "point_up" else 0.0)
                st["turn"] = st["head_turn"] = max(-0.8, min(0.8, st["turn"] * 0.4 + 0.45 * dirx * max(0.0, min(1.0, w))))
            st["front_arms"] = {k for k in ga if k in ("a", "b")}
        # ---- walking / running
        if mv:
            self._walk(st, t, mv, P)
            root_dx = 0.0
        # ---- riding a vehicle: seated on its seat, facing the way it goes, hands on the handlebar
        if ride:
            v = scene.vehicles[ride[2]]
            d = v.direction(t)
            _dx, seat_px = v.seat(ride[3])
            seat_u = seat_px * scene.vscale(ride[2]) / max(1e-6, getattr(self, "scale", 1.0))
            st["turn"] = st["head_turn"] = 0.55 * d
            st["face_dir"] = d
            self._sit(st, 1.0, seat_u, P)
            st["root"] = (st["root"][0], st["root"][1] - (seat_u - (P["foot_h"] + P["shin"] + P["thigh"] * 0.34)))
            if v.kind in ("cycle", "bike") and ride[3] == 0:
                for s_, sg in (("a", 1), ("b", -1)):
                    st["rot"]["uarm_" + s_] = -d * D(38) + sg * D(4)
                    st["rot"]["farm_" + s_] = -d * D(30)
                    st["hands"][s_] = "fist"
                if v.kind == "cycle":                          # the legs pedal with the cranks
                    ph = getattr(v, "pedal", 0.0)
                    for s_, sg in (("a", 1), ("b", -1)):
                        st["rot"]["thigh_" + s_] = st["rot"].get("thigh_" + s_, 0) + D(14) * math.sin(ph + (0 if sg > 0 else math.pi))
            sa = 0.0
        else:
            sa, seat = self.sit_amount(t)
        if ride:
            pass
        elif sa > 0:
            self._sit(st, sa, seat, P)
        else:
            st.setdefault("root", (root_dx, root_dy))
        # ---- hair and cloth springs (follow the head's real motion)
        hx = x + math.sin(rot.get("head", 0)) * P["head_h"] * 0.5
        if self.prev_head is not None:
            acc = (hx - self.prev_head) / dt
            k, c = 60.0, 7.0
            wind = scene.wind * math.sin(2 * math.pi * t * 0.7 + len(self.cid)) * 0.6
            self.hair[2] += (-k * self.hair[0] - c * self.hair[2] - acc * 0.004 + wind) * dt
            self.hair[0] += self.hair[2] * dt
            self.hair[3] += (-k * self.hair[1] - c * self.hair[3]) * dt
            self.hair[1] += self.hair[3] * dt
            self.cloth[1] += (-40 * self.cloth[0] - 6 * self.cloth[1] - acc * 0.002 + wind * 0.5) * dt
            self.cloth[0] += self.cloth[1] * dt
        self.prev_head = hx
        st["hair"] = (max(-1.2, min(1.2, self.hair[0] * 6)), max(-1.0, min(1.0, self.hair[1] * 6)))
        if tf and tf[0] + 0.2 <= t < tf[0] + 2.5:              # a cold wind of the change throws the hair about
            st["hair"] = (st["hair"][0] + 0.9 * math.sin(t * 13.0), st["hair"][1] - 0.4)
        st["cloth"] = max(-1.0, min(1.0, self.cloth[0] * 5))
        if side_d is not None:
            self._side(st, t, scene, x, side_d, mv, ride, emo, P)
        self._acts(st, t, P)
        gh = self.pp.spec.get("ghost")
        if gh:                                                     # a ghost floats and drifts up and down
            sc_ = getattr(self, "scale", 1.0)
            rise = 1.0
            if tf and t < tf[0] + 1.6:                        # after the change the ghost rises off the ground
                rise = max(0.0, min(1.0, (t - tf[0] - 1.0) / 0.6))
            st["float_y"] = rise * (gh.get("float", 0.07) * P["H"] * sc_ + 0.02 * P["H"] * sc_ * math.sin(2 * math.pi * t / 2.7))
            st["hair"] = (st["hair"][0] + 0.25 * math.sin(t * 1.3), st["hair"][1])
        return st, x

    # ----------------------------------------------------------------- pieces
    def _acts(self, st, t, P):
        """the body actions the STORY asks for (actions.py): a jump (anticipation squash, flight, landing squash), a
        dance (hops, swaying hips, clapping arms), a nod / a head shake, a bow (pranam), a fall (and getting up)"""
        sc_ = getattr(self, "scale", 1.0)
        rot = st["rot"]
        for a0, a1, kind in self.acts:
            if not (a0 <= t < a1):
                continue
            u = t - a0
            if kind in ("jump", "dance"):
                per = 0.62 if kind == "jump" else 0.48
                ph = (u % per) / per
                hgt = (0.16 if kind == "jump" else 0.06) * P["H"] * sc_
                if ph < 0.2:                                   # anticipation: crouch
                    st["squash"] = st.get("squash", 0.0) - 0.08 * math.sin(math.pi * ph / 0.2)
                elif ph < 0.82:                                # in the air (stretched going up)
                    v = (ph - 0.2) / 0.62
                    st["float_y"] = st.get("float_y", 0.0) + hgt * 4 * v * (1 - v)
                    st["squash"] = st.get("squash", 0.0) + 0.06 * (1 - v)
                else:                                          # landing squash
                    st["squash"] = st.get("squash", 0.0) - 0.06 * math.sin(math.pi * (ph - 0.82) / 0.18)
                if kind == "dance":
                    rot["spine"] = rot.get("spine", 0.0) + D(9) * math.sin(2 * math.pi * u / (2 * per))
                    rot["head"] = rot.get("head", 0.0) - D(6) * math.sin(2 * math.pi * u / (2 * per))
                    if "walk" not in st:
                        st["turn"] = max(-0.8, min(0.8, 0.5 * math.sin(2 * math.pi * u / (4 * per))))
                st["face"]["mouth"] = st["face"].get("mouth") or "SMILE"
            elif kind == "nod":
                rot["head"] = rot.get("head", 0.0) + D(9) * max(0.0, math.sin(2 * math.pi * u / 0.45)) * min(1.0, (a1 - t) / 0.3)
            elif kind == "shake":
                st["head_turn"] = max(-0.8, min(0.8, st.get("head_turn", st["turn"]) + 0.45 * math.sin(2 * math.pi * u / 0.42)))
            elif kind == "bow":                                # bend forward from the waist and come back
                w = math.sin(math.pi * min(1.0, u / max(0.3, a1 - a0)))
                rot["spine"] = rot.get("spine", 0.0) + D(28) * w
                rot["head"] = rot.get("head", 0.0) + D(14) * w
            elif kind == "fall":                               # a tumble: down on the bottom, then up again
                w = math.sin(math.pi * min(1.0, u / max(0.4, a1 - a0)))
                st["squash"] = st.get("squash", 0.0) - 0.12 * w
                rot["spine"] = rot.get("spine", 0.0) - D(16) * w
                st["face"]["wide"] = 1.0

    def _side(self, st, t, scene, x, d, mv, ride, emo, P):
        """the TRUE SIDE VIEW state (drawn by profile.py)"""
        sc = getattr(self, "scale", 1.0)
        sd = {"d": d, "t": t, "mode": "stand", "emotion": emo, "gesture": st.get("_g"),
              "head_back": self.lookback(t), "nod": st["rot"].get("head", 0.0) * 0.6 * d}
        if mv and "walk" in st:
            sd["mode"], sd["walk"] = "walk", st["walk"]
        elif ride:
            v = scene.vehicles[ride[2]]
            if v.kind in ("bus", "tram", "train"):
                sd["mode"], sd["sit"] = "sit", (1.0, P["foot_h"] + P["shin"] + P["thigh"] * 0.34)
            else:
                gy = scene.gy(self.cid)
                rg = v.rig_world(ride[3], t, v.x_at(t), scene.vgy(ride[2]), scene.vscale(ride[2]))
                loc = lambda p: ((p[0] - x) / (sc * d), (p[1] - gy) / sc)
                sd["rig"] = {"hip": loc(rg["hip"]), "feet": [loc(p) for p in rg["feet"]],
                             "bars": loc(rg["bars"]) if rg.get("bars") else None}
                sd["mode"] = "pedal" if rg.get("pedal") else "ride"
                sd["crank"] = rg.get("crank", 0.0)
                sd["lean"] = rg.get("lean", 12)
        else:
            sa, seat = self.sit_amount(t)
            if sa > 0:
                sd["mode"], sd["sit"] = "sit", (sa, seat)
        st["side"] = sd
        if sd["mode"] == "ride":                               # how high the hips are (the camera frames a seated rider)
            self.hip_h = -sd["rig"]["hip"][1] * sc
        elif sd["mode"] == "sit":
            self.hip_h = sd["sit"][1] * sc * sd["sit"][0] + P["leg"] * sc * (1 - sd["sit"][0])
        else:
            self.hip_h = None

    def _emotion_body(self, st, emo, t, since, P, dx, dy):
        """body acting per emotion. since = seconds since the emotion started (for the onset reaction)"""
        rot = st["rot"]
        Hh = P["H"]
        if emo == "surprised":
            # anticipation (a squash down) -> a jump with stretch -> settle (squash and stretch, 0.6 s)
            if since < 0.6:
                u = since / 0.6
                st["squash"] = -0.07 * math.sin(math.pi * u / 0.25) if u < 0.25 else 0.06 * math.sin(math.pi * (u - 0.25) / 0.75) * (1 - u)
                dy -= (0.03 * Hh * math.sin(math.pi * (u - 0.25) / 0.5)) if 0.25 <= u < 0.75 else 0.0
            rot["spine"] = rot.get("spine", 0) - D(3)
            st["face"]["brow_asym"] = 0.25
        elif emo == "laughing":
            b = abs(math.sin(2 * math.pi * 3.6 * t))
            dy += -0.006 * Hh * b                                   # the shoulders shake with laughter
            rot["spine"] = rot.get("spine", 0) - D(4) + D(2.5) * b
            rot["head"] = rot.get("head", 0) + D(3) * math.sin(2 * math.pi * 1.8 * t)
            st["squash"] = 0.015 * b
        elif emo in ("sad", "crying"):
            rot["spine"] = rot.get("spine", 0) + D(5)               # shoulders and head drop
            rot["head"] = rot.get("head", 0) + D(5) * (1 if math.sin(t * 0.7) > 0 else -1) * 0.4
            for s_, sg in (("a", 1), ("b", -1)):
                rot["uarm_" + s_] = rot.get("uarm_" + s_, 0) - sg * D(3)
            dy += 0.006 * Hh
            if emo == "crying":
                dy += 0.004 * Hh * math.sin(2 * math.pi * 2.6 * t) ** 2      # sobs
        elif emo == "scared":
            dx += 0.0035 * Hh * math.sin(2 * math.pi * 9.0 * t)     # trembling
            rot["spine"] = rot.get("spine", 0) - D(6)                # leaning back
            if since < 0.4:
                st["squash"] = -0.05 * math.sin(math.pi * since / 0.4)
            st["face"]["brow_asym"] = -0.2
        elif emo == "angry":
            rot["spine"] = rot.get("spine", 0) + D(5)                # leaning in
            st["hands"]["a"] = st["hands"]["b"] = "fist"
            st["face"]["brow_asym"] = 0.15
        elif emo == "happy":
            dy -= 0.003 * Hh * abs(math.sin(2 * math.pi * 1.1 * t))  # a little bounce
        return dx, dy

    def _apply_gesture(self, st, gd, w, t, P):
        rot = st["rot"]
        for side, (r_, shape) in arm_angles(gd).items():
            for b, v in r_.items():
                rot[b] = rot.get(b, 0.0) * (1 - w) + v * w
            if w > 0.5:
                st["hands"][side] = shape
        if "osc" in gd:
            side, part, amp, hz = gd["osc"]
            s = 1 if side == "a" else -1
            rot[part + "_" + side] = rot.get(part + "_" + side, 0) + s * D(amp) * math.sin(2 * math.pi * hz * t) * w
        iks = {s: v for s, v in gd.items() if s in ("a", "b") and v[0] == "ik"}
        if iks:
            st.setdefault("ik_arms", {})
            for side, (_k, tx, ty, ha, shape) in iks.items():
                if "clap" in gd:
                    ph = abs(math.sin(math.pi * gd["clap"] * t))
                    tx = tx + 0.25 * ph
                st["ik_arms"][side] = (tx, ty, ha, shape, max(0.0, min(1.0, w)))
                if w > 0.5:
                    st["hands"][side] = shape
            if gd.get("over") and w > 0.3:
                st["arms_over_head"] = set(iks)

    def _walk(self, st, t, mv, P):
        t0, t1, xa, xb, gait = mv
        run = gait == "run"
        d = 1.0 if xb > xa else -1.0
        dist = abs(self.x_at(t) - xa) / getattr(self, "scale", 1.0)
        S = P["leg"] * (1.25 if run else 0.85)                 # cycle length (two steps) in character units
        duty = 0.36 if run else 0.62
        phase = dist / S
        st["face_dir"] = d
        st["walk"] = {"phase": phase, "S": S, "duty": duty, "d": d, "run": run, "x_from": xa}
        bob = (math.cos(4 * math.pi * phase) * 0.012 if not run else -abs(math.sin(2 * math.pi * phase)) * 0.03) * P["H"]
        st["root"] = (0.0, bob)
        rot = st["rot"]
        rot["spine"] = rot.get("spine", 0) + d * D(10 if run else 3)
        sw = D(32 if run else 20) * math.sin(2 * math.pi * phase)
        for s, k in (("a", 1), ("b", -1)):
            sg = 1 if s == "a" else -1
            rot["uarm_" + s] = sg * (k * sw * d * sg) + rot.get("uarm_" + s, 0) * 0.3
            rot["farm_" + s] = sg * D(-60 if run else -12) - (D(10) * max(0, k * math.sin(2 * math.pi * phase)) * sg)
            st["hands"][s] = "fist" if run else "relax"

    def _sit(self, st, a, seat, P):
        """front-view sitting on a seat the scene draws: the thighs point at the camera (foreshortened), the shins
        stay upright, the hips go down onto the seat, the knees part a little, the body leans forward while sitting
        down and straightens."""
        f = 1.0 - 0.66 * a
        st["sit"] = (a, seat)
        st["len"]["thigh_a"] = st["len"]["thigh_b"] = f
        drop = P["thigh"] * (1 - f)
        st["root"] = (0.0, drop)
        for s_, sg in (("a", 1), ("b", -1)):
            st["rot"]["thigh_" + s_] = sg * D(9) * a
            st["rot"]["shin_" + s_] = -sg * D(9) * a
            st["rot"]["foot_" + s_] = 0.0
        st["rot"]["spine"] = st["rot"].get("spine", 0) + D(7) * math.sin(math.pi * min(1.0, a))


def solve_legs(pp, st, W, x, ground_y, scale, t_world=None):
    """IK for the feet: walking (planted feet, swing arcs) or sitting (feet stay, knees forward). Modifies st['rot']
    and returns the new world matrices."""
    P = pp.P
    sk = pp.sk
    wk = st.get("walk")
    sit = None
    if not wk and not st.get("ik_arms"):
        return W
    rot = st["rot"]
    if wk or sit:
        root_ang = R.world_angle(W["root"])
        for side in ("a", "b"):
            hip = W["thigh_" + side].transform_point(0, 0)
            hip_lx = sk.bones["thigh_" + side][1][0]
            ankle_y = ground_y - P["foot_h"] * scale
            if wk:
                off = 0.0 if side == "a" else 0.5
                q = (wk["phase"] + off) % 1.0
                S, duty, d = wk["S"], wk["duty"], wk["d"]
                if q < duty:
                    fx = -(q - duty / 2) * S
                    lift = 0.0
                else:
                    u = (q - duty) / (1 - duty)
                    fx = -duty / 2 * S + G.ease(u) * duty * S * (1 / duty) * duty
                    fx = -duty / 2 * S + (u * u * (3 - 2 * u)) * duty * S
                    lift = math.sin(math.pi * u) * P["H"] * (0.05 if not wk["run"] else 0.08)
                tx = x + (hip_lx * (1 - 0.45 * abs(st["turn"])) + d * fx) * scale
                ty = ankle_y - lift * scale
                knee = d
            else:
                a, seat = sit
                tx = x + hip_lx * 1.15 * scale
                ty = ankle_y
                knee = 1 if side == "b" else -1
                st["len"]["thigh_" + side] = 1.0 - 0.62 * a
            l1 = P["thigh"] * st["len"].get("thigh_" + side, 1.0) * scale
            l2 = P["shin"] * scale
            up, low = R.two_bone_ik(hip, (tx, ty), l1, l2, knee_x=knee if wk else knee * 0.0001)
            rest_t = sk.bones["thigh_" + side][3]
            rot["thigh_" + side] = up - root_ang - rest_t
            rot["shin_" + side] = low - up
            rot["foot_" + side] = -low + root_ang * 0
    W = sk.solve(st, x, ground_y - P["leg"] * scale, scale)
    if st.get("ik_arms"):
        sp_ang = R.world_angle(W["spine"])
        T = P["torso"]
        for side, (tx, ty, ha, shape, w) in st["ik_arms"].items():
            sgn = -1 if side == "a" else 1
            sh = W["uarm_" + side].transform_point(0, 0)
            tgt = W["spine"].transform_point(sgn * tx * P["shoulder"], -T + ty * T)
            up, low = R.two_bone_ik(sh, tgt, P["uarm"] * scale, P["farm"] * scale, knee_x=sgn)
            cur_u = rot.get("uarm_" + side, 0.0)
            cur_f = rot.get("farm_" + side, 0.0)
            rest_u = sk.bones["uarm_" + side][3]
            rest_f = sk.bones["farm_" + side][3]
            new_u = up - sp_ang - rest_u
            new_f = low - up - rest_f
            rot["uarm_" + side] = cur_u * (1 - w) + new_u * w
            rot["farm_" + side] = cur_f * (1 - w) + new_f * w
            hand_w = -sgn * D(ha)
            rot["hand_" + side] = (hand_w - low) * w
        W = sk.solve(st, x, ground_y - P["leg"] * scale, scale)
    return W
