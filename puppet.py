"""TV-style cut-out cartoon scenes (like the Gopal Bhar TV series): the ready-made characters in characters/<id>/
are placed on an empty background picture of the place and acted out line by line -
- every character always looks the same (the same drawings in every video)
- the speaker's mouth follows his own voice (lip-sync from the sound), everybody blinks now and then
- the pose changes with the feeling of the line (talk, laugh, angry, surprised, namaste, thinking ...)
- people walk in from the side, with real walking steps (speed matched to the steps - no sliding feet)
- TV camera work: a wide shot to show the place, then medium / close / two-shots with hard cuts between lines
- nothing ever shakes or rotates; chairs and thrones never move; the head stays in place when the pose changes
Everything heavy was prepared in advance (cut-outs, face measurements, mouth and blink pieces), so making a
scene is only pasting pictures - fast enough for the free GitHub runner."""
import json
import math
import os
import random
import re
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
CHAR_DIR = os.path.join(HERE, "characters")
CW, CH = 1920, 1080              # the stage; the camera looks at a part of it
FLOOR = 1018                     # where the feet stand
HB = 600                         # height of a normal grown-up (Gopal = 1.0) on the stage
VSR = 16000


# ------------------------------------------------------------------ characters
class Character:
    def __init__(self, cid):
        self.dir = os.path.join(CHAR_DIR, cid)
        self.rig = json.load(open(os.path.join(self.dir, "rig.json")))
        self.id = cid
        self.ext = self.rig.get("ext", "png")
        self.P = self.rig["poses"]
        self.scale = HB * self.rig.get("rel_h", 1.0) / self.rig.get("store_h", 1000)   # stage px per stored px
        self._img, self._cache = {}, {}
        self.short = {}
        for k in self.P:
            s = k.split("_", 1)[1] if k[:2].isdigit() else k
            self.short.setdefault(s, k)
            if s.startswith("front_"):
                self.short.setdefault(s[6:], k)

    def pose(self, name):
        return self.short.get(name) or (name if name in self.P else None)

    def can_talk(self, pose):
        return bool(self.rig.get("talk")) and "mouth" in self.P.get(pose, {})

    def _load(self, rel, mode="RGBA"):
        if rel not in self._img:
            p = os.path.join(self.dir, f"{rel}.{self.ext}")
            self._img[rel] = Image.open(p).convert(mode) if os.path.exists(p) else None
        return self._img[rel]

    def frame(self, pose, mouth=None, blink=0):
        pe = self.P[pose]
        if mouth is not None and not self.can_talk(pose):
            mouth = None
        if "blink" not in pe:
            blink = 0
        key = (pose, mouth, blink)
        if key in self._cache:
            return self._cache[key]
        im = self._load(f"poses/{pose}").copy()
        if blink:
            b = self._load(f"patch/{pose}_blink{blink}")
            if b is not None:
                im.alpha_composite(b, tuple(int(v) for v in pe["blink"]))
        if mouth is not None:
            al = im.getchannel("A")
            x0 = y0 = 0
            if pe.get("mouth_patch"):
                mp = self._load(f"patch/{pose}_mouth", "RGB")
                x0, y0 = (int(v) for v in pe["mouth_patch"])
                im.paste(mp, (x0, y0))
                im.putalpha(al)
            t = self._load(f"mouths/{mouth}")
            if t is not None:
                cx, cy, mw, mh = pe["mouth"]
                im.alpha_composite(t, (int(round(cx - t.width / 2)), int(round(cy - mh / 2))))
            if pe.get("over") and pe.get("mouth_patch"):
                ov = self._load(f"patch/{pose}_over")
                if ov is not None:
                    im.alpha_composite(ov, (x0, y0))
            im.putalpha(al)
        if len(self._cache) > 200:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = im
        return im


_CHARS = {}


def _unpack():
    """characters can be uploaded as one zip per character (GitHub's website takes max 100 files at a time):
    characters/gopal.zip -> characters/gopal/..."""
    import zipfile
    for z in sorted(os.listdir(CHAR_DIR)):
        if z.endswith(".zip") and not os.path.exists(os.path.join(CHAR_DIR, z[:-4], "rig.json")):
            try:
                with zipfile.ZipFile(os.path.join(CHAR_DIR, z)) as f:
                    names = f.namelist()
                    inner = z[:-4] + "/"
                    dest = CHAR_DIR if all(n.startswith(inner) for n in names) else os.path.join(CHAR_DIR, z[:-4])
                    f.extractall(dest)
            except Exception as e:
                print("  character pack", z, "could not be opened:", str(e)[:100])


_UNPACKED = []


def available():
    if not os.path.isdir(CHAR_DIR):
        return set()
    if not _UNPACKED:
        _UNPACKED.append(1)
        _unpack()
    return {d for d in os.listdir(CHAR_DIR) if os.path.exists(os.path.join(CHAR_DIR, d, "rig.json"))}


def char(cid):
    if cid not in _CHARS:
        _CHARS[cid] = Character(cid)
    return _CHARS[cid]


# ------------------------------------------------------------------ who is who
RIG_NAMES = [   # words in a story character's name / look -> character pack
    ("gopal_bou", r"gopal'?s? ?(wife|bou)|wife of gopal|gopal ?bou"),
    ("gopal", r"\bgopal"),
    ("rani", r"\brani\b|queen"),
    ("raja", r"\braja\b|\bking\b|krishnachandra|maharaj"),
    ("mantri", r"mantri|minister|dewan"),
    ("senapati", r"senapati|general|commander|army chief"),
    ("rajvaidya", r"vaid|kabiraj|doctor|physician|healer"),
    ("paharadar", r"pahara|guard|sentry|darwan|soldier|sepoy"),
    ("mahajan", r"mahajan|moneylender|money-lender|money lender"),
    ("moyra", r"moyra|moira|sweet ?(maker|seller|shop)|halwai"),
    ("zamindar", r"zamindar|jamidar|landlord|miser"),
    ("pandit", r"pandit|priest|purohit|scholar|brahmin|teacher|guru"),
    ("bonik", r"bonik|banik|merchant|trader|shopkeeper|dokandar|seller|vendor"),
    ("chashi", r"chashi|farmer|peasant|villager|cowherd|man from the village"),
    ("gramer_bou", r"village (wife|woman|lady)|gramer bou|woman|housewife"),
    ("saheb", r"\bsaheb"),
    ("sabhasad_1", r"courtier|sabhasad"),
]


def rig_for(name, look="", allowed=None):
    s = f"{name}".lower()
    allowed = available() if allowed is None else allowed
    for cid, rx in RIG_NAMES:
        if re.search(rx, s) and cid in allowed:
            return cid
    s = f"{name} {look}".lower()
    for cid, rx in RIG_NAMES:
        if re.search(rx, s) and cid in allowed:
            return cid
    return None


# ------------------------------------------------------------------ feelings -> poses
ACTS = [
    ("laugh", r"laugh|giggl|chuckl|guffaw|in splits"),
    ("scold", r"scold|wag(s|ging)? (a|her|his) finger"),
    ("angry", r"angr|furious|rage|fuming|glar|stern|annoy|irritat|cross\b"),
    ("worried", r"worr|anxious|nervous|tense|uneasy"),
    ("sad", r"\bsad|cry|tear|upset|sorrow|weep|gloom|disappoint|helpless"),
    ("embarrassed", r"embarrass|asham|sheepish|red-faced|humiliat"),
    ("surprised", r"surpris|shock|amaz|astonish|gasp|wide-eyed|stunn|startl|scared|afraid|fright|jaw drop|baffl"),
    ("scheme", r"schem|\bsly|plott|jealous|smirk|cunning|rubs? (his )?hands"),
    ("idea", r"\bidea|finger raised|rais(es|ing) (a|one|his|an) (index )?finger|eureka|clever smile|mischiev|twinkl"),
    ("thinking", r"think|ponder|chin|wonder|puzzl|curious|confus|scratch"),
    ("namaste", r"namaste|namaskar|pranam|folded hands|join(s|ed|ing)? (his |her |their )?hands|greet"),
    ("bow", r"\bbow"),
    ("bless", r"bless|raises? (his )?(right )?(palm|hand) in"),
    ("salute", r"salut"),
    ("block", r"block|bars? the|stop(s|ping)? (him|her|them)|spear across"),
    ("point", r"point"),
    ("wave", r"\bwav"),
    ("clap", r"\bclap"),
    ("thumbs_up", r"thumbs"),
    ("serving", r"serv|offer(s|ing)? (a |the )?(plate|sweet)|plate of"),
    ("counting", r"count|coins|ledger|accounts? book"),
    ("reading", r"\bread|book|scroll|manuscript|palm-leaf"),
    ("medicine", r"medicine|potion|herb|mortar"),
    ("boast", r"boast|brag|proud|puff(s|ed|ing)? (out )?(his )?chest|swagger"),
    ("tired", r"tired|exhaust|wip(e|es|ing) (his |the )?(brow|sweat)|sweat"),
    ("showing_off", r"show(s|ing)? off|display(s|ing)|silk|his wares"),
    ("hugging_key", r"hug(s|ging)? (a |the |his )?(key|money|chest)|clutch"),
    ("water_pot", r"water pot|pot|kolshi|pitcher"),
    ("cooking", r"cook|ladle|stir"),
    ("phone", r"phone"),
    ("listening", r"listen|attentive|nods"),
    ("happy", r"smil|happy|cheer|grin|delight|pleased|joy"),
]
EMO_ACT = {"laughing": "laugh", "laugh": "laugh", "angry": "angry", "shout": "angry", "sad": "sad",
           "scared": "surprised", "surprised": "surprised", "shocked": "surprised", "excited": "happy",
           "happy": "happy", "thinking": "thinking", "curious": "thinking", "worried": "worried"}
FALLBACK = {"scold": ["scold", "angry"], "worried": ["worried", "sad"], "embarrassed": ["embarrassed", "sad"],
            "scheme": ["scheme", "thinking"], "idea": ["idea", "point", "thinking"], "bless": ["bless", "namaste"],
            "bow": ["bow", "namaste"], "salute": ["salute", "namaste"], "clap": ["clap", "laugh"],
            "wave": ["wave", "namaste"], "thumbs_up": ["thumbs_up", "point"], "boast": ["boast", "showing_off"],
            "showing_off": ["showing_off", "boast"], "happy": ["relaxed"], "listening": ["listening", "relaxed"],
            "block": ["block", "salute"]}
WALK_RX = re.compile(r"\b(walk\w*|enter\w*|arriv\w*|comes? in|coming in|came in|approach\w*|hurr\w*|runs? in|"
                     r"rushes in|march\w*|stroll\w*|steps in|strides in)\b")
SIT_RX = re.compile(r"\b(sit\w*|seated|sat|throne|cushion)\b")
STAND_RX = re.compile(r"\b(stand\w*|stood|walks?|walking)\b")
COURT_RX = re.compile(r"\bcourt\b|royal court|darbar|durbar|throne|palace hall|royal hall|assembly")
NIGHT_RX = re.compile(r"\bnight|midnight|moonlit|moonlight|dark room|lantern|candle|starry")
DUSK_RX = re.compile(r"sunset|dusk|evening")


def act_of(text, emotion=""):
    t = str(text or "").lower()
    for a, rx in ACTS:
        if re.search(rx, t):
            return a
    return EMO_ACT.get(str(emotion or "").lower().strip())


class Actor:
    """One character on the stage for one scene."""

    def __init__(self, cid, x, seated, rnd, depth=1.0, floor=FLOOR):
        self.c = char(cid)
        self.id, self.x, self.seated, self.depth, self.floor = cid, x, seated, depth, floor
        self.scale = self.c.scale * depth
        nxt, self.blinks = rnd.uniform(0.4, 2.5), []
        while nxt < 4000:
            self.blinks.append(nxt)
            nxt += rnd.uniform(2.6, 5.2)
        ref = self.base_pose()
        pe = self.c.P[ref]
        e = pe.get("eyes")
        fy = pe["foot"][1]
        self.eye_up = ((fy - (e[0][1] + e[1][1]) / 2) if e else 0.82 * fy) * self.scale   # eyes above the feet
        self.half_w = 0.30 * pe["w"] * self.scale

    def pose_for(self, act, talking=False):
        c = self.c
        if self.seated:
            if c.pose("throne_relaxed"):
                if act == "laugh":
                    return c.pose("throne_laugh") or c.pose("throne_relaxed")
                return c.pose("throne_talk") if talking else c.pose("throne_relaxed")
            return c.pose("seated") or c.pose("sitting")
        for a in FALLBACK.get(act, [act]) if act else []:
            p = c.pose(a)
            if p:
                return p
        return c.pose("talk") if talking else c.pose("relaxed")

    def base_pose(self):
        return self.pose_for(None)

    def blink_at(self, t):
        for b in self.blinks:
            if b > t:
                break
            u = t - b
            if u < 0.04:
                return 1
            if u < 0.12:
                return 2
            if u < 0.16:
                return 1
        return 0


# ------------------------------------------------------------------ lip-sync from the voice
def _read(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(VSR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def visemes(path, fps):
    """the mouth shape for every video frame, from the sound itself: loudness opens the jaw, bright hissing
    sounds show teeth, dark round sounds make a round mouth, silence closes the lips; smoothed, no flicker"""
    a = _read(path)
    hop = VSR // fps
    n = max(1, len(a) // hop)
    win = np.hanning(hop * 2)
    freqs = np.fft.rfftfreq(hop * 2, 1 / VSR)
    rms, cen, low = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        seg = a[max(0, i * hop - hop // 2): i * hop + hop + hop // 2]
        if len(seg) < hop * 2:
            seg = np.pad(seg, (0, hop * 2 - len(seg)))
        sp = np.abs(np.fft.rfft(seg * win)) + 1e-9
        rms[i] = np.sqrt(np.mean(seg ** 2))
        cen[i] = (sp * freqs).sum() / sp.sum()
        low[i] = sp[(freqs > 150) & (freqs < 700)].sum() / sp[(freqs > 150) & (freqs < 4000)].sum()
    lv = rms / (np.percentile(rms[rms > 0], 95) + 1e-9) if (rms > 0).any() else rms
    jaw = np.zeros(n)
    for i in range(n):
        prev = jaw[i - 1] if i else 0
        jaw[i] = prev + (lv[i] - prev) * (0.75 if lv[i] > prev else 0.45)
    out = []
    for i in range(n):
        j = jaw[i]
        if j < 0.09:
            m = "closed"
        elif cen[i] > 2600 and j < 0.7:
            m = "ee"
        elif low[i] > 0.72 and j < 0.8:
            m = "u"
        elif j < 0.38:
            m = "small"
        elif j < 0.88:
            m = "open"
        else:
            m = "wide"
        out.append(m)
    for i in range(1, n):
        if {out[i - 1], out[i]} == {"closed", "wide"}:
            out[i] = "small"
    i = 0
    while i < n - 1:
        if out[i + 1] != out[i] and (i == 0 or out[i - 1] != out[i]):
            out[i + 1] = out[i]
            i += 2
        else:
            i += 1
    return out, jaw


def mouth_style(shape, emotion):
    e = str(emotion or "").lower()
    if shape == "closed" and e in ("happy", "excited", "laughing", "laugh", "proud"):
        return "smile"
    if shape == "closed" and e in ("sad", "crying"):
        return "sad"
    if shape == "wide" and e in ("angry", "shout"):
        return "shout"
    return shape


# ------------------------------------------------------------------ the camera
def window(kind, actors, who, others=()):
    """a 16:9 part of the stage: (x0, y0, width)"""
    if kind == "wide" or not who:
        return (0.0, 0.0, float(CW))
    a = who[0]
    if kind == "two" and others:
        b = others[0]
        lo = min(a.x - a.half_w, b.x - b.half_w) - 0.07 * CW
        hi = max(a.x + a.half_w, b.x + b.half_w) + 0.07 * CW
        w = min(float(CW), max(0.60 * CW, hi - lo))
        cx = (lo + hi) / 2
        eye = min(a.floor - a.eye_up, b.floor - b.eye_up)
        top_frac = 0.27
    elif kind == "close":
        w, cx, eye, top_frac = 0.40 * CW, a.x, a.floor - a.eye_up, 0.40
    elif kind == "closeR":                  # a little to the right: Lumi Didi and Mithu on her shoulder
        w, cx, eye, top_frac = 0.42 * CW, a.x + 0.05 * CW, a.floor - a.eye_up, 0.42
    else:                                   # medium
        w, cx, eye, top_frac = 0.54 * CW, a.x, a.floor - a.eye_up, 0.32
    h = w * 9 / 16
    x0 = min(max(0.0, cx - w / 2), CW - w)
    y0 = min(max(0.0, eye - top_frac * h), CH - h)
    return (x0, y0, w)


def plan_camera(lines, actors, total):
    """one shot per line (cut a moment before the voice starts), wide to open the scene,
    a reaction shot of the listener in the middle of long speeches"""
    by = {a.id: a for a in actors}
    main = [a for a in actors if a.depth == 1.0]
    cuts = []
    prev = None
    host = by.get("lumi_didi") if len(main) == 1 and main[0].id == "lumi_didi" else None
    for k, ln in enumerate(lines):
        t0 = 0.0 if k == 0 else max(0.0, ln["start"] - 0.12)
        sp = by.get(ln.get("speaker"))
        if host:                                   # Lumi Didi + Mithu on her shoulder
            if ln.get("speaker") == "mithu":
                shot = ("closeR", "lumi_didi")
            else:
                shot = ("medium", "lumi_didi") if k == 0 or prev != ("medium", "lumi_didi") else ("close", "lumi_didi")
                if k == 0:
                    shot = ("medium", "lumi_didi")
            if shot != prev:
                cuts.append((t0, shot))
                prev = shot
            continue
        dur = ln["end"] - ln["start"]
        listeners = sorted([a for a in main if a is not sp], key=lambda a: abs(a.x - sp.x)) if sp else []
        if k == 0 and len(main) > 1:
            shot = ("wide",)
        elif ln.get("walk"):
            shot = ("wide",)
        elif not sp:
            shot = ("wide",) if prev != ("wide",) or len(main) < 2 else ("two", main[0].id, main[-1].id)
        elif len(main) == 1:
            shot = ("close", sp.id) if prev == ("medium", sp.id) and dur > 2.5 else ("medium", sp.id)
        elif str(ln.get("emotion", "")).lower() in ("angry", "shout", "surprised", "shocked", "scared") and dur > 1.0 \
                and prev != ("close", sp.id):
            shot = ("close", sp.id)
        elif prev and prev[0] in ("medium", "close") and prev[1] == sp.id:
            shot = ("two", sp.id, listeners[0].id)
        elif k % 5 == 4:
            shot = ("wide",)
        else:
            shot = ("medium", sp.id)
        if shot != prev:
            cuts.append((t0, shot))
            prev = shot
        if ln.get("walk"):                         # after the walk-in, go closer for the rest of the line
            arrive = ln["walk_end"] + 0.4
            if sp and ln["end"] - arrive > 1.2:
                shot = ("medium", sp.id)
                cuts.append((arrive, shot))
                prev = shot
        if sp and listeners and dur > 6.5:          # reaction shot of the listener
            r0 = ln["start"] + dur * 0.55
            cuts.append((r0, ("medium", listeners[0].id)))
            cuts.append((r0 + 1.7, prev))
    out = []
    for t, shot in cuts:
        who = [by[i] for i in shot[1:2] if i in by]
        oth = [by[i] for i in shot[2:3] if i in by]
        out.append((t, window(shot[0], actors, who, oth), shot[0]))
    return out or [(0.0, (0.0, 0.0, float(CW)), "wide")]


# ------------------------------------------------------------------ drawing
_SHADOW = {}


def shadow_sprite(w, h):
    key = (w, h)
    if key not in _SHADOW:
        pad = max(4, h)
        m = Image.new("L", (w + pad * 2, h + pad * 2), 0)
        ImageDraw.Draw(m).ellipse((pad, pad, pad + w, pad + h), fill=95)
        _SHADOW[key] = m.filter(ImageFilter.GaussianBlur(max(2, h / 2.5)))
    return _SHADOW[key]


class Stage:
    def __init__(self, bg_path, tint=None):
        bg = Image.open(bg_path).convert("RGB")
        # fill the stage (cover), keep the lower part (the floor) in view
        s = max(CW / bg.width, CH / bg.height)
        bg = bg.resize((math.ceil(bg.width * s), math.ceil(bg.height * s)), Image.LANCZOS)
        x0 = (bg.width - CW) // 2
        y0 = bg.height - CH
        self.bg = bg.crop((x0, y0, x0 + CW, y0 + CH))
        self.tint = tint
        self._views = {}
        self._sprites = {}

    def view(self, win, kind, W, H):
        if win not in self._views:
            x0, y0, w = win
            h = w * 9 / 16
            v = self.bg.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + w, y0 + h))
            blur = {"close": 2.2, "closeR": 2.2, "medium": 1.2}.get(kind, 0)
            if blur:                                         # shallow depth of field, like a film camera
                v = v.filter(ImageFilter.GaussianBlur(blur))
            if len(self._views) > 12:
                self._views.pop(next(iter(self._views)))
            self._views[win] = v
        return self._views[win]

    def sprite(self, actor, pose, mouth, blink, s, flip=False):
        key = (actor.id, pose, mouth, blink, round(s, 4), flip)
        if key not in self._sprites:
            im = actor.c.frame(pose, mouth, blink)
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
            if flip:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            if self.tint:
                r, g, b, a = im.split()
                r = r.point(lambda v: int(v * self.tint[0]))
                g = g.point(lambda v: int(v * self.tint[1]))
                b = b.point(lambda v: int(v * self.tint[2]))
                im = Image.merge("RGBA", (r, g, b, a))
            if len(self._sprites) > 400:
                self._sprites.pop(next(iter(self._sprites)))
            self._sprites[key] = im
        return self._sprites[key]


def draw_actor(frame, stage, win, so, actor, pose, mouth, blink, x, floor, shadow=True, flip=False, zoom=1.0):
    pe = actor.c.P[pose]
    s = actor.scale * so * zoom
    im = stage.sprite(actor, pose, mouth, blink, s, flip)
    fx, fy = pe["foot"]
    if flip:
        fx = pe["w"] - fx
    X = (x - win[0]) * so
    Y = (floor - win[1]) * so
    if shadow:
        sw = max(8, int(pe["w"] * s * 0.62))
        sh = shadow_sprite(sw, max(4, int(sw * 0.13)))
        frame.paste((25, 20, 15), (int(X - sh.width / 2), int(Y - sh.height / 2 - 2)), sh)
    frame.paste(im, (int(round(X - fx * s)), int(round(Y - fy * s))), im)


# ------------------------------------------------------------------ one scene
def render_scene(spec, timings, wavs, audio, out, W=1280, H=720, FPS=25, log=print):
    """spec: {bg, place, cast: [ids left->right], lines: [{speaker, emotion, people: {id: text}}],
              host: None | {"fly_in": bool}}
    timings: (start, dur) of every spoken line; wavs: the voice file of every line; audio: the mixed scene sound.
    Writes out (video + sound) and returns its length in seconds."""
    rnd = random.Random(hash(out) & 0xffff)
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                  "default=nw=1:nk=1", audio], capture_output=True, text=True).stdout.strip())
    place = str(spec.get("place", "")).lower()
    tint = (0.70, 0.75, 0.95) if NIGHT_RX.search(place) else (1.0, 0.93, 0.85) if DUSK_RX.search(place) else None
    stage = Stage(spec["bg"], tint)
    host = spec.get("host")
    lines = []
    for k, ln in enumerate(spec.get("lines", [])):
        if k >= len(timings):
            break
        st, du = timings[k]
        lines.append(dict(ln, start=st, end=st + du, wav=wavs[k] if k < len(wavs) else None))

    # ---- who stands where
    cast = [c for c in spec.get("cast", []) if c in available()][:5]
    if host:
        cast = ["lumi_didi"]
    n = len(cast)
    slots = {1: [.5], 2: [.31, .69], 3: [.19, .5, .81], 4: [.13, .38, .62, .87], 5: [.1, .3, .5, .7, .9]}.get(n, [])
    if host:
        slots = [.43]
    court = bool(COURT_RX.search(place))
    actors = []
    for cid, sx in zip(cast, slots):
        texts = " ".join(str(ln.get("people", {}).get(cid, "")) for ln in lines).lower()
        c = char(cid)
        can_sit = bool(c.pose("throne_relaxed") or c.pose("seated"))
        sit = len(SIT_RX.findall(texts)) + (2 if (cid == "raja" and court) else 0)
        stand = len(STAND_RX.findall(texts))
        actors.append(Actor(cid, sx * CW, can_sit and sit > stand, rnd))
    extras = []
    if court and not host and n <= 2 and not any(c.startswith("sabhasad") for c in cast):
        for cid, sx in (("sabhasad_1", .075), ("sabhasad_2", .925)):
            if cid in available() and char(cid).pose("sitting"):
                a = Actor(cid, sx * CW, True, rnd, depth=0.70, floor=FLOOR - 150)
                extras.append(a)
    by = {a.id: a for a in actors}

    # ---- walk-ins (from the side the walking pictures face away from)
    walks = {}
    for k, ln in enumerate(lines):
        for cid, txt in (ln.get("people") or {}).items():
            a = by.get(cid)
            if not a or a.seated or cid in walks or len(walks) >= 2 or not a.c.rig.get("walk_cycle"):
                continue
            seen_before = any(cid in (lines[j].get("people") or {}) for j in range(k))
            if WALK_RX.search(str(txt).lower()) and not seen_before:
                d = a.c.rig.get("walk_dir", "R")
                x_from = -0.12 * CW if d == "R" else 1.12 * CW
                cyc = a.c.rig["walk_cycle"]
                speed = 0.80 * HB * a.c.rig.get("rel_h", 1)          # stage px per second, matched to the steps
                t0 = max(0.0, ln["start"] - 0.5)
                t1 = t0 + abs(a.x - x_from) / speed
                walks[cid] = (t0, t1, x_from, cyc, d)
                ln["walk"], ln["walk_end"] = True, t1

    # ---- what everybody does, line by line
    for ln in lines:
        ln["acts"] = {cid: act_of(txt) for cid, txt in (ln.get("people") or {}).items()}
        sp = ln.get("speaker")
        if sp in by:
            ln["acts"][sp] = act_of((ln.get("people") or {}).get(sp, ""), ln.get("emotion")) or "talk"
        if ln.get("wav") and (sp in by or (host and sp == "mithu")):
            try:
                ln["vis"], ln["jaw"] = visemes(ln["wav"], FPS)
            except Exception as e:
                log("  lip-sync skipped:", str(e)[:100])

    # Mithu on Lumi's shoulder
    mithu = char("mithu") if host and "mithu" in available() else None
    mithu_actor = Actor("mithu", 0, False, rnd) if mithu else None
    fly = (0.3, 2.3) if host and host.get("fly_in") else None

    cuts = plan_camera(lines, actors, total)
    nfr = int(math.ceil(total * FPS))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", audio, "-t", f"{total:.2f}",
           "-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, total - 0.4):.2f}:d=0.4,format=yuv420p",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "3500k", "-bufsize", "7000k",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    state = {a.id: a.base_pose() for a in actors}
    alt = {}
    try:
        ci = 0
        for f in range(nfr):
            t = f / FPS
            while ci + 1 < len(cuts) and cuts[ci + 1][0] <= t:
                ci += 1
            _, win, kind = cuts[ci]
            so = W / win[2]
            frame = stage.view(win, kind, W, H).copy()
            cur = next((ln for ln in lines if ln["start"] - 0.12 <= t < ln["end"] + 0.3), None)
            # extras at the back first
            for a in extras:
                draw_actor(frame, stage, win, so, a, a.base_pose(), None, a.blink_at(t), a.x, a.floor)
            walkers = []
            for a in actors:
                if a.id in walks:
                    t0, t1, x_from, cyc, d = walks[a.id]
                    if t < t0:
                        continue
                    if t < t1:
                        walkers.append((a, t0, t1, x_from, cyc, d))
                        continue
                    if t < t1 + 0.35:                        # turning to the others
                        tq = a.c.pose("three_quarter_right" if d == "R" else "three_quarter_left")
                        if tq:
                            draw_actor(frame, stage, win, so, a, tq, None, 0, a.x, a.floor)
                            continue
                pose, mouth = state[a.id], None
                if cur:
                    act = cur["acts"].get(a.id)
                    talking = cur.get("speaker") == a.id and cur["start"] <= t < cur["end"] + 0.25
                    if talking:
                        p_act = a.pose_for(act if act not in ("talk", "happy") else None, True)
                        p_talk = a.pose_for(None, True)
                        u = t - cur["start"]
                        if not a.c.can_talk(p_act):               # e.g. a big laugh: show it, then talk
                            pose = p_act if u < min(1.3, 0.4 * (cur["end"] - cur["start"])) else p_talk
                        else:
                            pose = p_act
                        # long speeches: change between two talking poses at the pauses
                        vis = cur.get("vis")
                        i = int(u * FPS)
                        if vis and a.c.can_talk(pose):
                            key = id(cur)
                            if key not in alt:
                                alt[key] = (pose, 0.0)
                            p_now, since = alt[key]
                            quiet = 0 <= i < len(vis) and all(v == "closed" for v in vis[max(0, i - 6):i + 1])
                            if quiet and u - since > 2.6 and cur["end"] - t > 1.5:
                                other = a.pose_for(None, False) if p_now == pose else pose
                                if a.c.can_talk(other):
                                    p_now, since = other, u
                                    alt[key] = (p_now, since)
                            pose = p_now
                            sh = vis[i] if 0 <= i < len(vis) else "closed"
                            mouth = mouth_style(sh, cur.get("emotion"))
                    elif act is not None:
                        pose = a.pose_for(act, False)
                    else:
                        pose = state[a.id]
                        if a.c.short.get("talk") == pose:
                            pose = a.base_pose()
                    if not talking:
                        state[a.id] = pose if pose != a.pose_for(None, True) or a.seated else a.base_pose()
                draw_actor(frame, stage, win, so, a, pose, mouth, a.blink_at(t), a.x, a.floor)
                if mithu_actor and a.id == "lumi_didi":
                    draw_mithu(frame, stage, win, so, a, pose, mithu_actor, t, fly, cur, lines, FPS)
            for a, t0, t1, x_from, cyc, d in walkers:            # walking people in front of everybody
                u = t - t0
                x = x_from + (a.x - x_from) * (u / (t1 - t0))
                fr = cyc[int(u * 7) % len(cyc)]
                draw_actor(frame, stage, win, so, a, fr, None, 0, x, a.floor)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("puppet render failed")
    return total


def draw_mithu(frame, stage, win, so, lumi, lumi_pose, m, t, fly, cur, lines, FPS):
    """Mithu flies in and lands on Lumi Didi's shoulder; afterwards he sits there and chirps his lines"""
    pe = lumi.c.P[lumi_pose]
    perch = pe.get("perch") or lumi.c.P[lumi.c.pose("relaxed")].get("perch")
    if not perch:
        return
    fx, fy = pe["foot"]
    px = lumi.x + (perch[0] - fx) * lumi.scale
    py = lumi.floor + (perch[1] - fy) * lumi.scale + 4            # claws a little into the shoulder
    if fly and t < fly[0]:
        return
    if fly and t < fly[1]:
        k = (t - fly[0]) / (fly[1] - fly[0])
        k = k * k * (3 - 2 * k)
        frs = [p for p in ("fly_1", "fly_2", "fly_3", "fly_4") if p in m.c.P]
        half = 0.5 * m.c.P[frs[0]]["w"] * m.scale * 0.8
        tx, ty = px + half * 0.75, py - 0.04 * HB          # he never flies across her face; lands from the side
        sx, sy = CW * 1.08, CH * 0.05
        x = sx + (tx - sx) * k
        y = sy + (ty - sy) * k - 120 * math.sin(math.pi * k)
        fr = frs[int(t * 12) % len(frs)]
        draw_actor(frame, stage, win, so, m, fr, None, 0, x, y, shadow=False, flip=True, zoom=0.8)
        return
    pose = m.c.pose("relaxed")
    if cur and cur.get("speaker") == "mithu" and cur["start"] <= t < cur["end"]:
        jaw = cur.get("jaw")
        i = int((t - cur["start"]) * FPS)
        loud = jaw is not None and 0 <= i < len(jaw) and jaw[i] > 0.25
        emo = str(cur.get("emotion", "")).lower()
        if loud:
            pose = m.c.pose("laugh") if emo.startswith("laugh") else m.c.pose("talk")
    draw_actor(frame, stage, win, so, m, pose, None, 0, px, py, shadow=False)


# ------------------------------------------------------------------ poster (thumbnail picture)
def poster(bg, hero, second, out, W=1280, H=720):
    """the hero big in front on the right, the second character smaller on the left - on the scene's set.
    hero / second: (character id, what he does / feels)"""
    stage = Stage(bg)
    frame = stage.bg.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.6))
    so = W / CW
    rnd = random.Random(1)

    def put(cid, text, x, height_frac, foot_below):
        a = Actor(cid, x, False, rnd)
        act = act_of(text) or "happy"
        pose = a.pose_for(act if act not in ("happy",) else "relaxed", False)
        for p in (pose, a.c.pose("surprised"), a.c.pose("relaxed")):     # a face that can be seen
            if p and a.c.P[p].get("eyes"):
                pose = p
                break
        pe = a.c.P[pose]
        zoom = height_frac * CH / (pe["h"] * a.scale)
        draw_actor(frame, stage, (0, 0, CW), so, a, pose, None, 0, x, CH + foot_below * CH, shadow=False, zoom=zoom)

    if second:
        put(second[0], second[1], 0.30 * CW, 1.05, 0.22)
    put(hero[0], hero[1], 0.68 * CW, 1.45, 0.52)
    frame.save(out, quality=93)
    return out
