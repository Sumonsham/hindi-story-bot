"""PAINTED STORY BACKGROUNDS for the tvtoon cartoon (owner, 26 Nov 2026: "the 2.5D video animation I made for the
horror bot - use it for the cartoon story bot's video animation, logically").

The owner's 2.5D package (cartoon25d.py / HYBRID_25D_BG) puts an illustrated, story-matched background behind the
LIVE tvtoon characters: the characters stay our own rigged, acting, lip-synced puppets (never a still picture moved
by the camera), and only the set behind them is a painting of the story's own place. This module is the shared,
bot-independent part of that:

  * prompt(...)      - one picture request for an EMPTY set of this scene: the story's place, the time of day, the
                       weather, its objects; eye-level, wide, the ground across the lower part (where the feet
                       stand), and NOBODY in it (the people are the animated characters). Two looks: "kids" (a
                       bright, friendly picture-book cartoon - the cartoon bot) and "horror" (the owner's dark 2.5D
                       horror style - the horror bot);
  * strip(img)       - the painting as the wide world strip the scene camera moves over WITHOUT stretching it (the
                       old way squeezed a 16:9 picture to 2.7:1): scaled to the height, the missing width added as a
                       soft mirrored continuation at both ends;
  * ground_colour()  - the colour of the painting's ground, for the strip below it (a dark band looked wrong in a
                       bright children's picture);
  * usable(img)      - a quick technical check of a painting (not empty / black / washed out / one flat colour);
  * key(...)         - the same place in one story gets the SAME painting (continuity), a new place a new one.

Nothing here calls a picture service: the bot's own main.py does that with its own account (one key per bot)."""
import hashlib
import re

import numpy as np

KIDS_STYLE = ("bright cheerful children's picture-book cartoon background painting, Indian Bengali setting, soft "
              "clean outlines, warm friendly colours, gentle sunlight, simple readable shapes, flat ground, "
              "family friendly, no text, no letters, no watermark")
HORROR_STYLE = ("2.5D dark Bengali horror cartoon background illustration, crisp ink outlines, painted depth, cold "
                "blue shadows with warm lamp light, eerie but not gory, no text, no letters, no watermark")

_DAY = [(8, "early morning, soft golden light"), (12, "bright morning sunlight"), (15, "sunny midday"),
        (17.5, "warm late afternoon light"), (19, "orange sunset sky"), (20.5, "blue evening dusk with lit lamps"),
        (24, "night, moonlight, lamps glowing")]   # (the period up to that hour)
_WEATHER = [(("rain", "বৃষ্টি", "বর্ষা", "बारिश", "storm", "ঝড়"), "rainy weather, wet ground, grey clouds"),
            (("fog", "mist", "কুয়াশা", "धुंध"), "light morning mist"),
            (("winter", "শীত", "सर्दी"), "winter, soft haze"),
            (("festival", "puja", "পুজো", "মেলা", "उत्सव", "मेला"), "festival decorations, paper lanterns, flags")]
INDOOR = ("ghar", "train_inside", "bus_inside", "tram_inside")


def time_words(hour):
    try:
        h = float(hour)
    except (TypeError, ValueError):
        return "daylight"
    h = h % 24
    if h < 5:
        return "night, moonlight, lamps glowing"
    for until, words in _DAY:
        if h < until:
            return words
    return "night"


def weather_words(text):
    t = str(text or "").lower()
    return ", ".join(w for keys, w in _WEATHER if any(k in t for k in keys))


PEOPLE = re.compile(r"\b(?:king|queen|prince|princess|minister|ministers|courtier|courtiers|people|person|persons|"
                    r"man|men|woman|women|boy|boys|girl|girls|child|children|kids|crowd|villagers?|guards?|soldiers?|"
                    r"family|friends?|he|she|they|sitting|standing|walking|playing|talking|"
                    r"dancing|working|selling|buying|shopkeepers?|vendors?|farmers?|students?|teachers?|"
                    r"animals?|dog|cat|cow|goat|bird|birds|monkey|elephant|tiger|lion)\b", re.I)


def scrub_people(text):
    """'royal court with king on throne and ministers sitting around' -> 'royal court'; the people of a scene are
    our animated characters, a painted person would stand still in the picture"""
    text = re.sub(r"(?:\b[\w]+\s+and\s+)?\b[\w]+['’]s\b", "", str(text or ""))     # "Tatai and Pupu's bedroom"
    pieces = re.split(r",|;|\bwith\b|\bwhere\b|\bwhile\b|\band\b|\bas\b", text, flags=re.I)
    keep = [p.strip() for p in pieces if p.strip() and not PEOPLE.search(p)]
    out = ", ".join(keep) if keep else re.sub(PEOPLE, "", str(text or ""))
    return re.sub(r"\s{2,}", " ", out).strip(" ,.")


def prompt(place, setting="", props=(), hour=12.0, look="kids", location="", room="", extra=""):
    """the request for an EMPTY painted set (no people) of one scene"""
    style = KIDS_STYLE if look == "kids" else HORROR_STYLE
    inside = location in INDOOR
    where = scrub_people(str(place or "").strip().rstrip("."))
    setting = scrub_people(setting)
    if room and inside:
        where = f"{where} (inside: a {room})" if where else f"inside a {room}"
    objs = ", ".join(str(p) for p in (props or []) if str(p).strip())[:220]
    frame = ("interior seen from the doorway at eye level, the back wall facing us, the floor filling the lower third"
             if inside else "wide panoramic landscape at eye level, the ground or path running across the lower third")
    parts = [f"EMPTY SET, no people, no persons, no children, no animals, no faces, no figures: {where}",
             str(setting or "").strip()[:200], f"objects: {objs}" if objs else "", time_words(hour),
             weather_words(f"{place} {setting} {extra}"), frame, f"Style: {style}"]
    return ". ".join(p for p in parts if p)[:1400]


_STOP = {"the", "a", "an", "of", "in", "on", "at", "under", "near", "to", "by", "from", "edge", "grand", "big", "small",
         "old", "new", "dark", "bright", "sunny", "night", "evening", "morning", "dusk", "dawn", "busy", "clean",
         "spotless", "modest", "filled", "light", "lit", "lighting", "up", "fading", "clear", "shady", "lined", "room"}


def words(place):
    return {w for w in re.findall(r"[a-z]{3,}|[ঀ-৿]{2,}|[ऀ-ॿ]{2,}", scrub_people(place).lower()) if w not in _STOP}


def same_place(a, b):
    """two place texts of one story that name the same set ('royal court' / 'grand royal court room')"""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    small, big = sorted((wa, wb), key=len)
    return small <= big or len(wa & wb) / len(wa | wb) >= 0.5


def key(place, location="", room="", hour=12.0, story=""):
    """one painting per distinct place (and time of day) of one story"""
    p = re.sub(r"[^\wঀ-৿ऀ-ॿ]+|[।॥]", " ", str(place or "").lower()).strip()
    tod = "night" if (float(hour or 12) % 24) >= 19.5 or (float(hour or 12) % 24) < 5 else \
        "dusk" if (float(hour or 12) % 24) >= 17.5 else "day"
    return hashlib.sha1(f"{story}|{location}|{room}|{p[:80]}|{tod}".encode()).hexdigest()[:12]


def usable(img):
    """a painting worth using (a PIL image): not tiny, not black / white / one flat colour"""
    try:
        a = np.asarray(img.convert("RGB").resize((96, 54)), dtype=np.float32)
    except Exception:
        return False, "not a picture"
    if img.size[0] < 256 or img.size[1] < 144:
        return False, "too small"
    m, s = float(a.mean()), float(a.std())
    if m < 18:
        return False, "almost black"
    if m > 245:
        return False, "almost white"
    if s < 12:
        return False, "one flat colour"
    return True, "ok"


def strip(img, out_w, out_h):
    """the painting as a world strip of out_w x out_h WITHOUT distortion (a PIL RGB image)"""
    from PIL import Image, ImageFilter
    img = img.convert("RGB")
    w, h = img.size
    sc = out_h / float(h)
    nw = max(1, int(round(w * sc)))
    base = img.resize((nw, out_h), Image.LANCZOS)
    if nw >= out_w:                                     # wide enough: the middle of it
        x0 = (nw - out_w) // 2
        return base.crop((x0, 0, x0 + out_w, out_h))
    canvas = Image.new("RGB", (out_w, out_h))
    x0 = (out_w - nw) // 2
    canvas.paste(base, (x0, 0))
    mir = base.transpose(Image.FLIP_LEFT_RIGHT)
    soft = mir.filter(ImageFilter.GaussianBlur(3))      # the continuation a little softer: it reads as 'further away'
    x = x0
    while x > 0:                                         # mirrored copies outwards: the edges always meet seamlessly
        x -= nw
        canvas.paste(soft if ((x0 - x) // nw) % 2 else base, (x, 0))
    x = x0 + nw
    k = 1
    while x < out_w:
        canvas.paste(soft if k % 2 else base, (x, 0))
        x += nw
        k += 1
    return canvas


def ground_colour(img):
    """the mean colour of the painting's lowest band (0..1 floats)"""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    band = a[int(a.shape[0] * 0.92):, :, :]
    c = band.reshape(-1, 3).mean(axis=0) / 255.0 if band.size else np.array([0.07, 0.07, 0.09])
    return float(c[0]), float(c[1]), float(c[2])
