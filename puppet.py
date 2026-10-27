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
    zips = []                                  # in characters/ or (uploaded there by mistake) next to main.py
    for folder in (CHAR_DIR, HERE):
        if os.path.isdir(folder):
            zips += [os.path.join(folder, z) for z in sorted(os.listdir(folder)) if z.endswith(".zip")]
    for zp in zips:
        name = os.path.basename(zp)[:-4]
        if os.path.exists(os.path.join(CHAR_DIR, name, "rig.json")):
            continue
        try:
            with zipfile.ZipFile(zp) as f:
                names = f.namelist()
                if not any(n.endswith("rig.json") for n in names):
                    continue                   # some other zip, not a character
                os.makedirs(CHAR_DIR, exist_ok=True)
                inner = name + "/"
                dest = CHAR_DIR if all(n.startswith(inner) for n in names) else os.path.join(CHAR_DIR, name)
                f.extractall(dest)
        except Exception as e:
            print("  character pack", name, "could not be opened:", str(e)[:100])


_UNPACKED = []


def available():
    if not _UNPACKED:
        _UNPACKED.append(1)
        _unpack()
    if not os.path.isdir(CHAR_DIR):
        return set()
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


def _act(t):
    for a, rx in ACTS:
        if re.search(rx, t):
            return a
    return None


def act_of(text, emotion=""):
    """'pose. doing || feeling' -> one acting word. A clear gesture (pointing, namaste...) wins, then a strong
    feeling (laughing, shocked...), then anything else, then the line's emotion."""
    t = str(text or "").lower()
    doing, _, feeling = t.partition("||")
    a_do, a_feel = _act(doing), _act(feeling)
    gestures = {"namaste", "bow", "bless", "salute", "block", "point", "wave", "clap", "thumbs_up", "serving",
                "counting", "reading", "medicine", "water_pot", "cooking", "phone", "scold", "hugging_key",
                "showing_off", "boast", "idea"}
    if a_do in gestures:
        return a_do
    return a_feel or a_do or EMO_ACT.get(str(emotion or "").lower().strip())


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
def _win(cx, eye, w, h, top_frac):
    x0 = min(max(0.0, cx - w / 2), CW - w)
    y0 = min(max(0.0, eye - top_frac * h), CH - h)
    return (x0, y0, w, h)


def window(kind, who=None, other=None, portrait=False):
    """a part of the stage the camera sees: (x0, y0, width, height) - 16:9, or 9:16 for the Reels"""
    if portrait:
        if kind == "wide" or not who:
            h = float(CH)
            return _win(CW / 2 if not who else who.x, 0, h * 9 / 16, h, 0)
        h = {"close": 0.62, "closeR": 0.66}.get(kind, 0.86) * CH
        cx = who.x + (0.05 * CW if kind == "closeR" else 0)
        if kind == "two" and other:                     # 9:16 is narrow: stay on the speaker
            cx = who.x + 0.12 * (other.x - who.x)
        # head a little lower than in the 16:9 picture: the Reel's title sits at the top
        return _win(cx, who.floor - who.eye_up, h * 9 / 16, h, {"close": 0.42, "closeR": 0.44}.get(kind, 0.33))
    if kind == "wide" or not who:
        return (0.0, 0.0, float(CW), float(CH))
    a = who
    if kind == "two" and other:
        b = other
        lo = min(a.x - a.half_w, b.x - b.half_w) - 0.07 * CW
        hi = max(a.x + a.half_w, b.x + b.half_w) + 0.07 * CW
        w = min(float(CW), max(0.60 * CW, hi - lo))
        return _win((lo + hi) / 2, min(a.floor - a.eye_up, b.floor - b.eye_up), w, w * 9 / 16, 0.27)
    w, top = {"close": (0.40, 0.40), "closeR": (0.42, 0.42)}.get(kind, (0.54, 0.32))
    cx = a.x + (0.05 * CW if kind == "closeR" else 0)
    return _win(cx, a.floor - a.eye_up, w * CW, w * CW * 9 / 16, top)


STRONG = {"laugh", "angry", "scold", "sad", "worried", "embarrassed", "surprised", "scheme", "idea", "thinking",
          "namaste", "bow", "bless", "salute", "block", "point", "wave", "clap", "thumbs_up", "serving", "counting",
          "reading", "medicine", "boast", "tired", "showing_off", "hugging_key", "water_pot", "cooking", "phone"}
EXIT_RX = re.compile(r"\b(walks? (out|away|off)|leaves?|leaving|goes (out|away|home)|exits?|runs? (away|off)|"
                     r"storms? out|hurr\w* (out|away|off))\b")
FACE_FIX = {"mantri": {"08_three_quarter_left": 1}, "rani": {"08_three_quarter_left": -1},
            "lumi_didi": {"10_three_quarter_left": -1}}


def turned(c, d, talk):
    """a pose of this character looking to the viewer's left (d=-1) or right (d=1)"""
    best = None
    for p, pe in c.P.items():
        f = pe.get("facing", FACE_FIX.get(c.id, {}).get(p))
        if f != d or (talk and not c.can_talk(p)):
            continue
        if best is None or ("blink" in pe and "blink" not in c.P[best]):
            best = p
    return best


class Line:
    pass


def plan_shots(lines, by, main, host, portrait=False):
    """TV editing: wide to open, then the speaker / two-shots of speaker and listener, close-ups on big
    feelings, a reaction shot of the listener in long speeches, wide again when people walk"""
    cuts, prev = [], None
    for k, ln in enumerate(lines):
        t0 = 0.0 if k == 0 else max(0.0, ln["start"] - 0.12)
        sp, ad = by.get(ln.get("speaker")), by.get(ln.get("to"))
        dur = ln["end"] - ln["start"]
        if host:
            shot = ("closeR", host.id) if ln.get("speaker") == "mithu" else ("medium", host.id)
        elif ln.get("walk") and not portrait:
            shot = ("wide",)
        elif ln.get("walk") and portrait:
            shot = ("follow", ln["walk"])
        elif k == 0 and len(main) > 1 and not portrait:
            shot = ("wide",)
        elif not sp:
            shot = ("wide",) if not portrait else ("medium", (main[0] if main else None) and main[0].id)
        elif str(ln.get("emotion", "")).lower() in ("angry", "shout", "surprised", "shocked", "scared") and \
                dur > 1.0 and prev != ("close", sp.id):
            shot = ("close", sp.id)
        elif ad and not portrait and prev and prev[0] in ("medium", "close") and prev[1] in (sp.id, ad.id):
            shot = ("two", sp.id, ad.id)
        elif k % 6 == 5 and not portrait and len(main) > 2:
            shot = ("wide",)
        else:
            shot = ("medium", sp.id)
        if shot != prev:
            cuts.append((t0, shot))
            prev = shot
        if ln.get("walk_end") and not host:            # after somebody walked in: on the speaker
            arrive = ln["walk_end"] + 0.4
            if sp and ln["end"] - arrive > 1.2:
                prev = ("medium", sp.id)
                cuts.append((arrive, prev))
        if sp and ad and dur > 6.0 and not host:        # the listener's face in the middle of a long speech
            r0 = ln["start"] + dur * 0.55
            cuts.append((r0, ("medium", ad.id)))
            cuts.append((r0 + 1.7, prev))
    out = []
    for t, shot in sorted(cuts, key=lambda c: c[0]):
        if shot[0] == "follow":
            out.append((t, shot, "follow"))
            continue
        who = by.get(shot[1]) if len(shot) > 1 else None
        oth = by.get(shot[2]) if len(shot) > 2 else None
        out.append((t, window(shot[0], who, oth, portrait), shot[0]))
    return out or [(0.0, window("wide", portrait=portrait), "wide")]


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
            x0, y0, w, h = win
            v = self.bg.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + w, y0 + h))
            blur = {"close": 2.2, "closeR": 2.2, "medium": 1.2}.get(kind, 0)
            if blur:                                         # shallow depth of field, like a film camera
                v = v.filter(ImageFilter.GaussianBlur(blur))
            if len(self._views) > 24:
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
def _sign(v):
    return 1 if v > 0 else -1


def _ffmpeg_out(path, W, H, FPS, total, audio=None):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-"]
    if audio:
        cmd += ["-i", audio, "-t", f"{total:.2f}"]
    cmd += ["-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, total - 0.4):.2f}:d=0.4,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "3500k", "-bufsize", "7000k"]
    cmd += (["-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"] if audio else ["-an"]) + [path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def render_scene(spec, timings, wavs, audio, out, W=1280, H=720, FPS=25, log=print, portrait_out=None):
    """spec: {bg, place, cast: [ids left->right], lines: [{speaker, to, emotion, people: {id: text}}],
              host: None | {"fly_in": bool}}
    timings: (start, dur) of every spoken line; wavs: the voice file of every line; audio: the mixed scene sound.
    Writes out (16:9 video + sound) and, if asked, portrait_out (9:16 picture for the Reels).
    Returns the length in seconds."""
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
        lines.append(dict(ln, start=st, end=st + du, wav=wavs[k] if k < len(wavs) else None,
                          people=dict(ln.get("people") or {})))
    av = available()

    # ---- who stands where (the Raja on his throne in the middle of the court, the others at both sides)
    cast = ["lumi_didi"] if host else [c for c in spec.get("cast", []) if c in av][:6]
    court = bool(COURT_RX.search(place)) and not host
    seated = {}
    for cid in cast:
        texts = " ".join(str(ln["people"].get(cid, "")) for ln in lines).lower()
        c = char(cid)
        can_sit = bool(c.pose("throne_relaxed") or c.pose("seated"))
        sit = len(SIT_RX.findall(texts)) + (3 if (cid == "raja" and court) else 0)
        seated[cid] = can_sit and sit > len(STAND_RX.findall(texts))
    xs = {}
    if host:
        xs["lumi_didi"] = 0.43
    elif court and "raja" in cast and seated.get("raja"):
        others = [c for c in cast if c != "raja"][:5]
        half = (len(others) + 1) // 2
        left, right = others[:half], others[half:]
        lp = {1: [.27], 2: [.13, .29], 3: [.07, .19, .31]}.get(len(left), [])
        rp = {1: [.73], 2: [.71, .87], 3: [.69, .81, .93]}.get(len(right), [])
        xs.update(zip(left, lp))
        xs.update(zip(right, rp))
        xs["raja"] = 0.5
    else:
        n = len(cast)
        sl = {1: [.5], 2: [.31, .69], 3: [.19, .5, .81], 4: [.13, .38, .62, .87], 5: [.1, .3, .5, .7, .9],
              6: [.08, .25, .42, .58, .75, .92]}.get(n, [])
        xs.update(zip(cast, sl))
    actors = sorted((Actor(cid, xs[cid] * CW, seated[cid], rnd) for cid in cast if cid in xs), key=lambda a: a.x)
    by = {a.id: a for a in actors}
    extras = []
    if court:                                   # the court is never empty: courtiers at the sides, a guard
        for cid, sx, sit, fl, dp in (("sabhasad_1", .045, True, 150, .70), ("sabhasad_2", .955, True, 150, .70),
                                     ("paharadar", .615, False, 235, .56)):
            if cid in av and cid not in by:
                e = Actor(cid, sx * CW, sit, rnd, depth=dp, floor=FLOOR - fl)
                if e.base_pose():
                    extras.append(e)

    def speaking_in(cid, j):
        return lines[j].get("speaker") == cid or cid in lines[j]["people"]

    # ---- people walking in and out (with real steps, from / to the side they face)
    ev = {a.id: {} for a in actors}
    for k, ln in enumerate(lines):
        for cid, txt in ln["people"].items():
            a = by.get(cid)
            if not a or a.seated or not a.c.rig.get("walk_cycle"):
                continue
            low = str(txt).lower()
            d = a.c.rig.get("walk_dir", "R")
            speed = 0.80 * HB * a.c.rig.get("rel_h", 1)
            if WALK_RX.search(low) and "enter" not in ev[cid] and not any(speaking_in(cid, j) for j in range(k)):
                x_from = -0.12 * CW if d == "R" else 1.12 * CW
                t0 = max(0.0, ln["start"] - 0.5)
                t1 = t0 + abs(a.x - x_from) / speed
                ev[cid]["enter"] = (t0, t1, x_from)
                ln["walk"], ln["walk_end"] = cid, t1
            elif EXIT_RX.search(low) and "exit" not in ev[cid] and \
                    not any(speaking_in(cid, j) for j in range(k + 1, len(lines))):
                x_to = 1.12 * CW if d == "R" else -0.12 * CW
                t0 = (ln["end"] - 0.1) if ln.get("speaker") == cid else ln["start"] + 0.4
                ev[cid]["exit"] = (t0, t0 + abs(a.x - x_to) / speed, x_to)
                ln["walk"] = cid

    def where(a, t):
        """(visible, x, walking frame or None)"""
        e = ev.get(a.id, {})
        if "enter" in e:
            t0, t1, x0 = e["enter"]
            if t < t0:
                return False, a.x, None
            if t < t1:
                u = t - t0
                return True, x0 + (a.x - x0) * u / (t1 - t0), a.c.rig["walk_cycle"][int(u * 7) % len(a.c.rig["walk_cycle"])]
        if "exit" in e:
            t0, t1, x1 = e["exit"]
            if t >= t1:
                return False, a.x, None
            if t >= t0:
                u = t - t0
                cyc = a.c.rig["walk_cycle"]
                return True, a.x + (x1 - a.x) * u / (t1 - t0), cyc[int(u * 7) % len(cyc)]
        return True, a.x, None

    # ---- who talks to whom, and how everybody looks (speaker turns to the listener, listeners to the speaker)
    for k, ln in enumerate(lines):
        sp = by.get(ln.get("speaker"))
        to = by.get(ln.get("to"))
        if sp and (not to or to is sp):
            prev = by.get(lines[k - 1].get("speaker")) if k else None
            near = sorted([a for a in actors if a is not sp], key=lambda a: abs(a.x - sp.x))
            to = prev if prev and prev is not sp else (near[0] if near else None)
        ln["to"] = to.id if to else None
        ln["lp"] = {}
        for a in actors:
            txt = ln["people"].get(a.id, "")
            if a is sp:
                act = act_of(txt, ln.get("emotion"))
                if a.seated:
                    p1, p2 = a.pose_for(act, True), None
                elif act in STRONG:
                    p1, p2 = a.pose_for(act, True), a.pose_for(None, True)
                else:
                    tq = turned(a.c, _sign(to.x - a.x), True) if to else None
                    p1, p2 = (tq, a.pose_for(None, True)) if tq else (a.pose_for(None, True), None)
                ln["sp"] = (p1, p2)
            else:
                act = act_of(txt)
                if act in STRONG:
                    ln["lp"][a.id] = a.pose_for(act, False)
                elif a.seated:
                    ln["lp"][a.id] = a.pose_for(None, False)
                elif sp:
                    ln["lp"][a.id] = turned(a.c, _sign(sp.x - a.x), False) or a.pose_for(None, False)
        if ln.get("wav") and (sp or (host and ln.get("speaker") == "mithu")):
            try:
                ln["vis"], ln["jaw"] = visemes(ln["wav"], FPS)
            except Exception as e:
                log("  lip-sync skipped:", str(e)[:100])

    mithu_actor = Actor("mithu", 0, False, rnd) if host and "mithu" in av else None
    fly = (0.3, 2.3) if host and host.get("fly_in") else None
    main = [a for a in actors]
    hosta = by.get("lumi_didi") if host else None
    cams = [(W, H, plan_shots(lines, by, main, hosta, False), _ffmpeg_out(out, W, H, FPS, total, audio))]
    if portrait_out:
        PW, PH = 720, 1280
        cams.append((PW, PH, plan_shots(lines, by, main, hosta, True), _ffmpeg_out(portrait_out, PW, PH, FPS, total)))
    held = {a.id: a.base_pose() for a in actors}
    alt = {}
    nfr = max(1, int(round(total * FPS)))
    try:
        idx = [0] * len(cams)
        for f in range(nfr):
            t = f / FPS
            ci = max([k for k, ln in enumerate(lines) if ln["start"] - 0.12 <= t] or [0])
            cur = lines[ci] if lines else None
            todo = []                                     # (actor, pose, mouth, blink, x, walking)
            for a in actors:
                vis_, x, wf = where(a, t)
                if not vis_:
                    continue
                if wf:
                    todo.append((a, wf, None, 0, x, True))
                    continue
                pose, mouth = held[a.id], None
                if cur and cur.get("speaker") == a.id and t < cur["end"] + 0.2 and "sp" in cur:
                    p1, p2 = cur["sp"]
                    u = t - cur["start"]
                    talk = a.pose_for(None, True)
                    if not a.c.can_talk(p1):                    # a big laugh: show it, then talk
                        pose = p1 if u < min(1.3, 0.4 * (cur["end"] - cur["start"])) else (p2 or talk)
                    else:
                        vis = cur.get("vis")
                        i = int(u * FPS)
                        key = id(cur)
                        p_now, since = alt.get(key, (p1, 0.0))
                        if vis and p2 and a.c.can_talk(p2):     # long speeches: change pose at the pauses
                            quiet = 0 <= i < len(vis) and all(v == "closed" for v in vis[max(0, i - 6):i + 1])
                            if quiet and u - since > 2.6 and cur["end"] - t > 1.5:
                                p_now, since = (p2 if p_now == p1 else p1), u
                        alt[key] = (p_now, since)
                        pose = p_now
                    if a.c.can_talk(pose):
                        vis = cur.get("vis")
                        i = int(u * FPS)
                        sh = vis[i] if vis and 0 <= i < len(vis) and t < cur["end"] else "closed"
                        mouth = mouth_style(sh, cur.get("emotion"))
                elif cur and a.id in cur["lp"]:
                    pose = cur["lp"][a.id]
                    held[a.id] = pose
                elif a.c.short.get("talk") == pose or (pose and a.c.can_talk(pose) and "three_quarter" not in pose
                                                      and pose == a.pose_for(None, True)):
                    pose = a.base_pose()
                    held[a.id] = pose
                todo.append((a, pose, mouth, a.blink_at(t), x, False))
            for n_, (CWo, CHo, shots, proc) in enumerate(cams):
                while idx[n_] + 1 < len(shots) and shots[idx[n_] + 1][0] <= t:
                    idx[n_] += 1
                _, win, kind = shots[idx[n_]]
                if kind == "follow":                       # the Reel camera walks along with the walker
                    w_ = next((x for (a, p, m, b, x, wk) in todo if wk and a.id == win[1]), None)
                    a_ = by.get(win[1])
                    if w_ is None or a_ is None:
                        win = window("wide", portrait=True)
                    else:
                        tmp = type("P", (), dict(x=round(w_ / 6) * 6, floor=a_.floor, eye_up=a_.eye_up, half_w=a_.half_w))
                        win = window("medium", tmp, None, True)
                    kind = "medium"
                so = CWo / win[2]
                frame = stage.view(win, kind, CWo, CHo).copy()
                for e in extras:
                    draw_actor(frame, stage, win, so, e, e.base_pose(), None, e.blink_at(t), e.x, e.floor)
                for a, pose, mouth, bl, x, wk in sorted(todo, key=lambda z: z[5]):   # walkers in front
                    draw_actor(frame, stage, win, so, a, pose, mouth, bl, x, a.floor)
                    if mithu_actor and a.id == "lumi_didi":
                        draw_mithu(frame, stage, win, so, a, pose, mithu_actor, t, fly, cur, lines, FPS)
                proc.stdin.write(frame.tobytes())
    finally:
        for _, _, _, proc in cams:
            proc.stdin.close()
            proc.wait()
    if any(proc.returncode != 0 for *_, proc in cams):
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
