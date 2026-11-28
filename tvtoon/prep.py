"""THE NIGHT CHARACTER-ASSET STUDIO (owner, 23 Nov 2026): "vor 4 tai je run cholbe setai sudhu golpo onujayi jodi
kono new character pai seta toiri korbe only. setar jonno jeno ekta assistant toiri korbe ... se golpo pore notun
kon character, element, notun kichu jodi pai jeta asset e nei setar details r ekta agent ke debe, se oi details
onujayi character asset toiri korbe ... ei gulo duto bot ei thakbe."

After the night's stories are written (horror: 2 AM, cartoon: 11 PM) a run of its own (horror: 4 AM, cartoon: 2 AM,
mode = assets) does ONLY this, with two agents that each have their own job, input, output and error handling:

  1. STORY SCOUT (StoryScout)        input : the written story (+ which bot it is for)
                                     output: scout_report - every character and element of the story, and which of
                                             them the asset library does NOT have yet, each with a full brief (name,
                                             gender, age, ghost / human / animal + species, the story's own words about
                                             the look, clothes and colours, what the character does in the story)
                                     errors: a character it cannot read is reported (not guessed silently)
  2. CHARACTER ASSET BUILDER         input : the scout's briefs
     (AssetBuilder)                  output: a NEW permanent character for every brief - its own face, body, hair,
                                             clothes and colours taken from the brief (several designs are tried and
                                             the one most unlike every existing character is kept), drawn in front and
                                             side view and checked; saved in assets/tvtoon_library.json under the
                                             story's names, with a picture sheet
                                     errors: a design that fails its check is made again (up to 4 times); if it
                                             still fails, the brief is reported and the story run casts that role as
                                             before

Nothing else happens at night: no voice, no animation, no post. When the story's video is made, its characters are
taken from the library (characters.get / story.cast_story / kids.kids_cast look there first), so everyone looks
exactly as built at night - and the same name in a later story (a series) is the same person again.

Elements (places, vehicles, palki, boat, rooms ...) the engine draws itself; the scout lists every one the story
needs and says which place it is drawn as, and names any it has no drawing for (sent on Telegram) - it never
pretends to have one."""
import copy
import datetime as dt
import hashlib
import json
import os
import re
import time

from tvtoon import characters as CH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_FILE = os.path.join(ROOT, "assets", "tvtoon_library.json")
REPORT_DIR = os.path.join(ROOT, "assets", "tvtoon_prep")
_LOADED = {"mtime": None}


# ===================================================================================================== the library
def _read_lib():
    try:
        with open(LIB_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"characters": {}}
    except Exception:
        return {"characters": {}}


def load_library(force=False):
    """put every character built at night into this run's cast (once per run, again when the file changed)"""
    try:
        mt = os.path.getmtime(LIB_FILE)
    except OSError:
        return {}
    if not force and _LOADED["mtime"] == mt:
        return _LOADED.get("lib", {})
    lib = _read_lib()
    for cid, rec in (lib.get("characters") or {}).items():
        if isinstance(rec, dict) and isinstance(rec.get("spec"), dict):
            CH.SPECS[cid] = copy.deepcopy(rec["spec"])
    _LOADED.update(mtime=mt, lib=lib)
    return lib


def _norm(name):
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _look_words(t):
    return {w for w in re.findall(r"[a-z\u0980-\u09ff\u0900-\u097f]{3,}", str(t or "").lower())
            if w not in ("with", "and", "the", "his", "her", "a", "about", "bengali", "indian", "cartoon", "style")}


def same_look(a, b):
    """two descriptions of the same person? (no description on one side: yes)"""
    wa, wb = _look_words(a), _look_words(b)
    if not wa or not wb:
        return True
    return len(wa & wb) / max(1, min(len(wa), len(wb))) >= 0.3


def find(name, bot=None, gender=None, species=None, look=None):
    """the library character built for this story name (None if there is none) -> (actor id, kind). A different
    person with the same name (other gender, other animal) is not taken."""
    lib = load_library()
    n = _norm(name)
    if not n:
        return None
    for cid, rec in (lib.get("characters") or {}).items():
        if bot and rec.get("bot") not in (None, bot):
            continue
        if n in [_norm(x) for x in rec.get("names", [])]:
            b = rec.get("brief") or {}
            if gender and b.get("gender") and b["gender"] != gender:
                continue
            if species and rec.get("species") and rec["species"] != species:
                continue
            if look and not same_look(look, b.get("look")):
                continue                                    # another person with the same name
            return cid, rec.get("kind", "human")
    return None


def actor_for(name, bot=None, gender=None, species=None, look=None):
    hit = find(name, bot, gender, species, look)
    if not hit:
        return None
    cid, kind = hit
    return cid + "__ghost" if kind == "ghost" else cid


# ===================================================================================================== agent 1
GHOST_KINDS = ("ghost", "spirit", "demon", "entity", "bhoot", "petni", "ভূত", "প্রেত", "भूत")


# a role the story's words name -> what the cast actor must already have to play it (else a NEW character is made)
ROLE_TRAITS = [
    (("sadhu", "sanyasi", "monk", "hermit", "tantrik", "tantric", "fakir", "সাধু", "সন্ন্যাসী", "তান্ত্রিক", "साधु", "तांत्रिक"),
     lambda s: s.get("hair", {}).get("style") == "jata" or "rudraksha" in s.get("accessories", [])),
    (("priest", "purohit", "pandit", "পুরোহিত", "পণ্ডিত", "पुजारी", "पंडित"),
     lambda s: "tilak" in s.get("accessories", []) or "sacred_thread" in s.get("accessories", []) or "tilak" in s["colours"]),
    (("police", "constable", "daroga", "inspector", "uniform", "khaki", "পুলিশ", "দারোগা", "पुलिस", "दरोगा", "वर्दी"),
     lambda s: s["colours"].get("shirt", "").lower() in ("#a89466", "#8a7a4a", "#b8a06a")),
    (("doctor", "white coat", "ডাক্তার", "डॉक्टर"), lambda s: s["colours"].get("shirt", "").lower() in ("#f2f0e8", "#f8f8f4")),
    (("king", "raja", "maharaja", "zamindar", "রাজা", "জমিদার", "राजा", "ज़मींदार", "जमींदार"),
     lambda s: bool({"turban", "crown", "mukut", "shawl"} & set(s.get("accessories", [])))),
    (("queen", "rani", "রানি", "রাণী", "रानी"), lambda s: "crown" in s.get("accessories", [])),
    (("sahib", "british", "englishman", "memsahib", "সাহেব", "মেমসাহেব", "अंग्रेज"),
     lambda s: s["colours"].get("skin", "").lower() in ("#f2d2b0", "#f0c8a8", "#e8c0a0")),
]


def role_missing(look, spec):
    """the look names a role (sadhu, police, king...) that this actor does not show"""
    low = f" {str(look or '').lower()} "
    for words, has in ROLE_TRAITS:
        if any(w in low for w in words):
            try:
                if not has(spec):
                    return words[0]
            except Exception:
                return words[0]
    return None


class StoryScout:
    """reads the story; finds every character and element the asset library does not have; writes the briefs"""
    name = "Story Scout"

    def __init__(self, bot="horror", category="", log=print):
        self.bot, self.category, self.log = bot, category, log

    def _doing(self, story, name):
        """what the character does in the story (its own lines and the storyboard's notes about it)"""
        out = []
        for sc in story.get("scenes") or []:
            for ln in sc.get("lines") or []:
                pic = ln.get("image") if isinstance(ln.get("image"), dict) else {}
                for p in pic.get("people") or []:
                    if isinstance(p, dict) and _norm(p.get("name")) == _norm(name):
                        out.append(" ".join(str(p.get(k, "")) for k in ("pose", "doing", "feeling")).strip())
                if _norm(ln.get("speaker")) == _norm(name) and ln.get("action"):
                    out.append(str(ln["action"]))
        return [x for x in dict.fromkeys(out) if x][:6]

    def _cast(self, story):
        """the bot's own casting, done as at video time but WITHOUT the night library: whoever lands on a
        one-story face ('ep_' / 'kp_' / 'ka_') has no character asset yet"""
        chars = [c for c in story.get("characters") or [] if isinstance(c, dict)]
        if self.bot == "kids":
            from tvtoon import kids as K
            return K.kids_cast({"characters": chars, "title": story.get("title", "")}, self.category, build=False)
        from tvtoon import story as STY
        reveal = {}
        for n_, v_ in (story.get("ghost_reveal") or {}).items():
            reveal[n_] = v_
        return STY.cast_story(chars, reveal, build=False)

    def run(self, story):
        report = {"agent": self.name, "title": story.get("title", ""), "bot": self.bot, "characters": [], "new": [],
                  "elements": [], "missing_elements": [], "problems": []}
        try:
            cast = self._cast(story)
        except Exception as e:
            report["problems"].append(f"casting could not be read: {str(e)[:200]}")
            cast = {}
        for ch in story.get("characters") or []:
            if not isinstance(ch, dict) or not ch.get("name"):
                continue
            name = ch["name"]
            if _norm(name) in ("narrator", "কথক", "कथावाचक"):
                continue
            actor = (cast.get(name) or (None,))[0]
            kind = str(ch.get("kind", "human")).lower()
            row = {"name": name, "actor": actor}
            report["characters"].append(row)
            if actor != "NEW":
                row["in_library"] = True                   # a recurring / already built character plays it
                continue
            from tvtoon import animals as AM
            species = AM.species_of(f"{name} {ch.get('look', '')}") if (kind in ("animal", "bird") or self.bot == "kids") else None
            if kind in ("animal", "bird") and not species:
                species = "parrot" if kind == "bird" else "dog"
            brief = {"name": name, "name_local": ch.get("name_local") or name,
                     "gender": "female" if str(ch.get("gender", "male")).lower().startswith("f") else "male",
                     "age": ch.get("age"), "kind": "animal" if species else (
                "human" if _solid_demon(kind, str(ch.get("look", "") or "")) else "ghost" if any(w in kind for w in GHOST_KINDS)
                else "human"),
                     "species": species, "look": str(ch.get("look", "") or ""), "doing": self._doing(story, name),
                     "story": story.get("title", "")}
            for k in ("clothes", "costume", "dress", "appearance", "description"):
                if ch.get(k):
                    brief["look"] += " " + str(ch[k])
            report["new"].append(brief)
        from tvtoon import story as STY
        from tvtoon import kids as K
        for i, sc in enumerate(story.get("scenes") or []):
            place = str(sc.get("place", ""))
            p2 = K.kids_place(place) if self.bot == "kids" else place
            loc = STY.place_of(p2)
            el = {"scene": i + 1, "place": place, "drawn_as": loc}
            if loc == "ghar":
                el["room"] = STY.room_kind(p2)
            low = p2.lower()
            if loc == "ghar" and el["room"] == "bedroom" and not any(w in low for w in ("bed", "room", "ঘর", "कमरा", "home", "house")):
                el["nearest"] = True                     # no drawing of its own: the closest place is used
                report["missing_elements"].append(place)
            report["elements"].append(el)
        self.log(f"  [Story Scout] {len(report['characters'])} characters, {len(report['new'])} NEW "
                 f"({', '.join(b['name'] for b in report['new']) or 'none'}); {len(report['elements'])} places"
                 + (f"; no own drawing for: {', '.join(report['missing_elements'][:4])}" if report["missing_elements"] else ""))
        return report


# ===================================================================================================== agent 2
COLOURS = {"red": "#c62828", "maroon": "#7a1a2a", "crimson": "#a01a2a", "blue": "#1e5aa8", "navy": "#1e2a5a",
           "sky": "#64b5f6", "green": "#2e7d32", "olive": "#6a6a2a", "yellow": "#f9c02a", "saffron": "#f08a1a",
           "orange": "#f57c00", "white": "#f2f0e8", "black": "#2a2a2a", "grey": "#8a8a84", "gray": "#8a8a84",
           "brown": "#8a5a32", "khaki": "#a89466", "pink": "#f48fb1", "purple": "#6a3a8a", "violet": "#7a4aa8",
           "golden": "#e0b030", "gold": "#e0b030", "cream": "#efe6cf", "beige": "#d9c8a4", "teal": "#1a8a8a",
           "লাল": "#c62828", "নীল": "#1e5aa8", "সবুজ": "#2e7d32", "হলুদ": "#f9c02a", "গেরুয়া": "#f08a1a",
           "সাদা": "#f2f0e8", "কালো": "#2a2a2a", "ধূসর": "#8a8a84", "বাদামি": "#8a5a32", "খাকি": "#a89466",
           "গোলাপি": "#f48fb1", "বেগুনি": "#6a3a8a", "সোনালি": "#e0b030", "লাল": "#c62828",
           "लाल": "#c62828", "नीला": "#1e5aa8", "नीली": "#1e5aa8", "हरा": "#2e7d32", "हरी": "#2e7d32", "पीला": "#f9c02a",
           "पीली": "#f9c02a", "केसरिया": "#f08a1a", "सफेद": "#f2f0e8", "सफ़ेद": "#f2f0e8", "काला": "#2a2a2a",
           "काली": "#2a2a2a", "भूरा": "#8a5a32", "गुलाबी": "#f48fb1"}
UPPER = {"shirt": "shirt", "kurta": "kurta", "panjabi": "kurta", "punjabi": "kurta", "fatua": "kurta", "robe": "kurta",
         "uniform": "shirt", "coat": "shirt", "jacket": "shirt", "blouse": "blouse", "saree": "saree", "sari": "saree",
         "frock": "frock", "dress": "frock", "t-shirt": "tshirt", "tshirt": "tshirt", "top": "tshirt", "kameez": "kurta",
         "kurti": "kurta", "জামা": "shirt", "শার্ট": "shirt", "পাঞ্জাবি": "kurta", "শাড়ি": "saree", "ফ্রক": "frock",
         "কুর্তা": "kurta", "कुर्ता": "kurta", "कमीज": "shirt", "साड़ी": "saree", "शर्ट": "shirt", "फ्रॉक": "frock"}
LOWER = {"trousers": "trousers", "pant": "trousers", "pants": "trousers", "jeans": "trousers", "pyjama": "dhoti",
         "pajama": "dhoti", "pyjamas": "dhoti", "pajamas": "dhoti", "cargo": "trousers", "dhoti": "dhoti", "lungi": "dhoti", "salwar": "dhoti", "shorts": "shorts", "border": "border",
         "ধুতি": "dhoti", "লুঙ্গি": "dhoti", "প্যান্ট": "trousers", "পাড়": "border", "धोती": "dhoti", "पैंट": "trousers"}
SADHU = ("sadhu", "sanyasi", "monk", "hermit", "tantrik", "tantric", "saint", "fakir", "সাধু", "সন্ন্যাসী", "তান্ত্রিক",
         "फकीर", "साधु", "संन्यासी", "तांत्रिक")
PRIEST = ("priest", "pandit", "purohit", "brahmin", "পুরোহিত", "পণ্ডিত", "ব্রাহ্মণ", "पुजारी", "पंडित", "ब्राह्मण")
SHIRT_WORDS = ("shirt", "trousers", "pant", "jeans", "uniform", "coat", "suit", "jacket", "police", "officer", "doctor",
               "inspector", "babu", "clerk", "teacher", "master", "driver", "জামা", "শার্ট", "প্যান্ট", "পুলিশ", "ডাক্তার",
               "शर्ट", "पैंट", "पुलिस", "डॉक्टर")
DEMON = ("demon", "sorcerer", "wizard", "witch", "monster", "rakshas", "rakshasa", "daitya", "asura", "shadow-like",
         "evil spirit", "দানব", "রাক্ষস", "জাদুকর", "ডাইনি", "দৈত্য", "दानव", "राक्षस", "जादूगर", "डायन", "दैत्य")
ROYAL_F = ("princess", "queen", "rani", "rajkumari", "gown", "lehenga", "ghagra", "royal dress", "silk dress", "রাজকন্যা",
           "রানি", "राजकुमारी", "रानी", "लहंगा")
KURTA_WORDS = ("dhoti", "kurta", "panjabi", "punjabi", "fatua", "lungi", "robe", "ধুতি", "পাঞ্জাবি", "লুঙ্গি", "धोती", "कुर्ता") \
    + SADHU + PRIEST


class AssetBuilder:
    """makes a NEW permanent character from every brief - original (unlike every existing face), true to the
    story's words, drawn and checked in front and side view"""
    name = "Character Asset Builder"
    TRIES = 4

    def __init__(self, bot="horror", log=print):
        self.bot, self.log = bot, log

    # -------------------------------------------------------------- the brief -> a design
    def _base(self, b, look):
        g, age = b["gender"], self._age(b)
        if g == "male":
            if any(w in look for w in KURTA_WORDS + ("robe", "king", "raja", "prince", "emperor") + DEMON):
                return {"old": "nibaran_dadu", "adult": "bhattacharya", "young": "sayan", "child": "bappa"}[age] \
                    if age != "young" else "sayan"
            if any(w in look for w in ("t-shirt", "tshirt", "t shirt", "টি-শার্ট", "टी-शर्ट")) and age in ("young", "child"):
                return "sayan" if age == "young" else "bappa"
            if any(w in look for w in SHIRT_WORDS) and age in ("adult", "young"):
                return "ramu_chowkidar" if age == "adult" else "abhishek"
        else:
            if any(w in look for w in ("saree", "sari", "শাড়ি", "साड़ी") + ROYAL_F + DEMON) and age in ("adult", "old", "young"):
                return "mokkhoda" if age == "old" else "parul"
            if any(w in look for w in ("salwar", "kurti", "kameez", "kurta", "সালোয়ার", "सलवार")) and age in ("young", "adult"):
                return "riya"
            if age == "child":
                return "kishori" if any(w in look for w in ("braid", "plait", "বেণি", "चोटी")) else "mili"
        return None

    @staticmethod
    def _age(b):
        from tvtoon import story as STY
        return STY._age(b.get("age"))

    def _apply_look(self, s, b, look, dress_only=False):
        """the script's words -> the design. dress_only (a recurring character): only what is WORN changes"""
        cols = s["colours"]
        words = re.findall(r"[\w\u0980-\u09ff\u0900-\u097f]+(?:-shirt)?", look.replace("light-", "").replace("dark-", "dark ")
                           .replace("t shirt", "t-shirt"))
        upper = next((k for k in ("shirt", "kurta", "tshirt", "frock", "saree") if k in cols), None)
        lower = next((k for k in ("trousers", "dhoti", "shorts") if k in cols), None)
        firsts, done = [], set()
        second = {"saree": "border", "kurta": "dhoti" if "dhoti" in cols else None, "frock": "trim" if "trim" in cols else None,
                  "tshirt": "stripe" if "stripe" in cols else None}

        def put(key, col):
            if key in done:                              # "pink AND gold": the second colour is the trim / border
                k2 = second.get(key) or ("blouse" if "blouse" in cols else None)
                if k2 and k2 not in done:
                    cols[k2] = col
                    done.add(k2)
                return
            cols[key] = col
            done.add(key)
        for i, w in enumerate(words):                    # "<colour> <garment>" -> that garment in that colour
            col = COLOURS.get(w)
            if not col:
                continue
            firsts.append(col)
            for nxt in words[i + 1:i + 5]:
                if nxt in COLOURS or nxt in ("and", "with", "or", "polo", "cotton", "silk", "royal", "striped", "check",
                                             "long", "short", "simple", "old", "new", "plain", "thin", "big", "small"):
                    if nxt == "silk" and upper and words[i + 1:i + 5][-1:] and not any(
                            UPPER.get(x) or LOWER.get(x) for x in words[i + 1:i + 5]):
                        put(upper, col)
                        break
                    continue
                key = UPPER.get(nxt) or LOWER.get(nxt)
                if key in ("blouse", "border") and key in cols:
                    put(key, col)
                    break
                if key and key in UPPER.values() and upper:
                    put(upper, col)
                    break
                if key and lower:
                    put(lower, col)
                    break
                if nxt in ("robe", "robes", "gown", "dress", "clothes", "outfit", "উর্দি", "पोशाक", "জামাকাপড়"):
                    if upper:
                        put(upper, col)
                    if lower and nxt in ("robe", "robes", "gown", "dress") and lower not in done:
                        put(lower, col)
                    break
                if nxt in ("hair", "চুল", "बाल") and not dress_only:
                    cols["hair"] = col if col not in ("#c62828", "#2e7d32", "#1e5aa8") else cols["hair"]
                    break
                if nxt in ("moustache", "mustache", "beard", "গোঁফ", "দাড়ি", "मूंछ", "दाढ़ी") and not dress_only:
                    cols["moustache" if nxt in ("moustache", "mustache", "গোঁফ", "मूंछ") else "beard"] = col
                    if nxt in ("beard", "দাড়ি", "दाढ़ी"):
                        s["face"]["beard"] = max(0.6, s["face"].get("beard", 0) or 0)
                    break
                if nxt in ("eyes", "eye", "চোখ", "आंखें", "आँखें") and not dress_only:
                    s["face"]["iris"] = col
                    if "glow" in look:
                        s["face"]["glow"] = "#ffe680" if col != COLOURS["red"] else "#ff6a5a"
                    break
        acc = s.setdefault("accessories", [])
        has = lambda *ws: any(w in look for w in ws)

        def add(*names):
            for a in names:
                if a not in acc:
                    acc.append(a)
        if has("glasses", "spectacle", "চশমা", "चश्मा"):
            add("glasses_round")
        if has("turban", "pagri", "pagdi", "পাগড়ি", "पगड़ी"):
            add("turban")
        if has("crown", "tiara", "mukut", "diadem", "মুকুট", "टियारा", "मुकुट", "ताज"):
            add("crown")
            if "turban" in acc and not has("turban", "pagri", "পাগড়ি", "पगड़ी"):
                acc.remove("turban")
        if has("shawl", "chador", "চাদর", "शॉल"):
            add("shawl")
        if has("full sleeve", "long sleeve", "robe", "robes", "gown", "coat") and s.get("costume"):
            s["costume"]["sleeve"] = "full"
        if dress_only:
            return s
        for a, words_ in (("glasses_round", ("glasses", "spectacle", "চশমা", "चश्मा")), ("tilak", ("tilak", "তিলক", "तिलक") + PRIEST + SADHU),
                          ("sacred_thread", PRIEST), ("sindoor", ("sindoor", "সিঁদুর", "सिंदूर", "married", "wife", "বিবাহিত",
                                                                  "বউ", "विवाहित", "mother", "মা ", "माँ")), ("shawl", ("shawl", "chador", "চাদর", "शॉल", "king", "raja", "zamindar"))):
            if a in acc and not has(*words_):
                acc.remove(a)
        if "tilak" in cols and not has("tilak", "তিলক", "तिलक", *PRIEST, *SADHU):
            cols.pop("tilak", None)
        if has("grey hair", "gray hair", "white hair", "silver hair", "পাকা চুল", "सफेद बाल"):
            cols["hair"] = "#c8c8c0"
        if has("bald", "টাক", "गंजा"):
            s["hair"] = {"style": "bald_sides"}
        elif has("curly", "কোঁকড়া", "घुंघराले"):
            s["hair"] = {"style": "curly"}
        elif b["gender"] == "female" and has("open hair", "loose hair", "long hair", "long dark hair", "এলো চুল", "খোলা চুল",
                                              "खुले बाल", "लंबे बाल"):
            s["hair"] = {"style": "open_long"}
        elif b["gender"] == "female" and has("bun", "খোঁপা", "जूड़ा"):
            s["hair"] = {"style": "bun_black" if self._age(b) != "old" else "bun_white"}
        elif has("braid", "plait", "বেণি", "चोटी"):
            s["hair"] = {"style": "braid_long" if b["gender"] == "female" else s["hair"]["style"]}
        elif b["gender"] == "female" and has("bob", "short hair"):
            s["hair"] = {"style": "bun_black"}
        if has(*SADHU):
            s["hair"] = {"style": "jata"}
            add("rudraksha", "tilak")
            for k in ("kurta", "dhoti"):
                if k in cols:
                    cols[k] = COLOURS["saffron"]
            s["face"]["beard"] = 1.0
            cols.setdefault("beard", cols["hair"])
        if has(*PRIEST):
            add("tilak", "sacred_thread")
        if b["gender"] == "male" and has("beard", "দাড়ি", "दाढ़ी"):
            s["face"]["beard"] = max(0.6, s["face"].get("beard", 0) or 0)
            cols.setdefault("beard", cols["hair"])
        if b["gender"] == "male" and has("moustache", "mustache", "গোঁফ", "मूंछ"):
            cols.setdefault("moustache", cols["hair"])
            if has("white moustache", "white mustache", "grey moustache", "gray moustache"):
                cols["moustache"] = "#e8e8e0"
        if b["gender"] == "female" and has("sindoor", "সিঁদুর", "सिंदूर", "married", "বিবাহিত", "विवाहित"):
            add("sindoor", "bindi")
        if b["gender"] == "female" and has("bangle", "চুড়ি", "चूड़ी", "jewel", "gold", "royal"):
            add("bangles", "earrings")
        if has("police", "constable", "daroga", "inspector", "khaki", "পুলিশ", "দারোগা", "पुलिस", "दरोगा") and "shirt" in cols:
            cols["shirt"] = COLOURS["khaki"]
            cols["trousers"] = COLOURS["khaki"]
        if has("doctor", "ডাক্তার", "डॉक्टर") and "shirt" in cols and not has("blue coat", "black coat"):
            cols["shirt"] = COLOURS["white"]
        if has("sahib", "british", "englishman", "memsahib", "সাহেব", "अंग्रेज"):
            cols["skin"] = "#f2d2b0"
            cols["hair"] = "#8a5a32" if self._age(b) != "old" else "#d8d8d0"
        if has("king", "raja", "maharaja", "emperor", "zamindar", "রাজা", "জমিদার", "राजा", "ज़मींदार", "जमींदार") and b["gender"] == "male":
            add("shawl", "jewel")
            if "crown" not in acc:
                add("turban")
                cols.setdefault("turban", COLOURS["cream"])
            cols.setdefault("shawl", COLOURS["maroon"])
            if s.get("costume"):
                s["costume"]["sleeve"] = "full"
        if has("queen", "rani", "princess", "rajkumari", "রানি", "রাণী", "রাজকন্যা", "রাজকুমারী", "रानी", "राजकुमारी") \
                and b["gender"] == "female":
            add("crown", "earrings", "bangles", "bindi")
            if "border" in cols and not has("border"):
                cols["border"] = COLOURS["golden"]
            if "blouse" in cols and len(firsts) >= 2:
                cols["blouse"] = firsts[1]
        if has("prince", "rajkumar", "রাজকুমার", "राजकुमार") and b["gender"] == "male":
            add("crown", "jewel")
        if has(*DEMON):                                   # a demon / sorcerer / witch: dark, glowing eyes, floats
            cols["skin"] = "#5a4a6a" if not has("green") else "#4a6a4a"
            for k in ("kurta", "dhoti", "shirt", "trousers", "saree", "blouse", "border", "frock"):
                if k in cols and cols[k] not in firsts:
                    cols[k] = "#2a1a3a"
            s["face"]["iris"] = COLOURS["red"] if not has("yellow eyes", "green eyes") else s["face"].get("iris")
            s["face"]["glow"] = "#ff6a5a"
            s["face"]["ghost_eyes"] = True
            if s.get("costume"):
                s["costume"]["sleeve"] = "full"
            if has("shadow", "misty", "float", "smoke", "ghost", "spirit", "ছায়া", "भूत", "छाया"):
                s["ghost"] = {"float": 0.06, "alpha": 0.93, "tint": "#c8b0ff"}
        if has("huge", "giant", "enormous", "massive", "বিশাল", "দৈত্যাকার", "विशाल") or has(*SOLID_DEMON[:10]):
            s["height"] = round(s["height"] * 1.2, 3)       # a rakshasa / giant towers over the others
        if has("tall", "লম্বা", "लंबा", "लंबी"):
            s["height"] = round(s["height"] * 1.08, 3)
        if has("short ", "বেঁটে", "नाटा", "छोटे कद"):
            s["height"] = round(s["height"] * 0.92, 3)
        if has("fat", "plump", "pot-belly", "potbelly", "stout", "chubby", "মোটা", "ভুঁড়ি", "मोटा", "मोटी"):
            s["body"]["belly"] = max(0.25, s["body"].get("belly", 0) or 0)
        if has("thin", "lean", "skinny", "slim", "রোগা", "পাতলা", "दुबला", "पतला"):
            s["body"]["belly"] = 0.0
            s["body"]["shoulder"] = round(s["body"].get("shoulder", 0.7) * 0.9, 3)
        if has("dark skin", "dark-skinned", "কালো রং", "শ্যামলা", "सांवला", "सांवली") or re.search(r"dark(?:\s+\w+)?\s+skin", look):
            cols["skin"] = "#8e5e40"
        if has("hunch", "stoop", "bent back", "কুঁজো", "कुबड़"):
            s["body"]["stoop"] = max(0.12, s["body"].get("stoop", 0) or 0)
        if has("towel", "gamchha", "gamcha", "গামছা", "गमछा") and "shawl" not in acc:
            acc.append("shawl")
            cols["shawl"] = "#d8c8a0" if not has("red towel", "red gamchha") else COLOURS["red"]
        if has("lungi", "লুঙ্গি", "लुंगी") and s.get("costume", {}).get("type") == "kurta_dhoti" and not has("kurta", "shirt", "vest"):
            s["costume"]["sleeve"] = "none"
        if has("fair", "ফর্সা", "गोरा", "गोरी") and not has(*DEMON):
            cols["skin"] = "#e0aa82"
        if has("wheat", "wheatish"):
            cols["skin"] = "#c48a62"
        return s

    def _distance(self, spec, cid):
        from tvtoon import qa
        others = [o for o, so in CH.SPECS.items() if o != cid and not so.get("extra") and not so.get("animal")
                  and so.get("costume")]
        return min([qa.identity_distance(spec, CH.get(o)) for o in others] or [99])

    def _check(self, cid):
        """draw it in front and side view; a body must really be drawn in both"""
        import cairo
        import numpy as np
        from tvtoon import puppet as PP
        pp = PP.make(CH.get(cid))
        out = []
        for side in (None, {"d": 1.0, "t": 0.0, "mode": "stand", "emotion": "neutral", "gesture": None, "head_back": 0.0,
                            "nod": 0.0}):
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 700)
            ctx = cairo.Context(surf)
            st = {"rot": {}, "len": {}, "hands": {"a": "relax", "b": "relax"}, "face": {}, "turn": 0.0, "t": 0.0}
            if side and not CH.get(cid).get("animal"):
                st["side"] = side
                st["turn"] = 0.8
            pp.draw(ctx, st, 200, 680, 0.55)
            a = np.ndarray((700, 400, 4), np.uint8, surf.get_data())[:, :, 3]
            out.append(int((a > 0).sum()))
        return all(n > 6000 for n in out), out

    def build(self, briefs, story_key=""):
        from tvtoon import animals as AM
        lib = _read_lib()
        lib.setdefault("characters", {})
        made, failed = [], []
        for b in briefs:
            look = f" {b.get('look', '')} {' '.join(b.get('doing') or [])} ".lower()
            slug = re.sub(r"[^a-z0-9]+", "_", str(b["name"]).lower()).strip("_")[:16] or "x"
            cid = f"lib_{self.bot[:1]}_{slug}_{hashlib.sha1((b['name'] + '|' + b.get('look', '')).encode()).hexdigest()[:5]}"
            best = None
            for k in range(self.TRIES):
                try:
                    if b["kind"] == "animal":
                        s = AM.make_spec(b["name_local"], b.get("species") or "dog", b.get("look", ""), b["gender"], self._age(b))
                        CH.SPECS[cid] = s
                    else:
                        s = CH.new_character(cid, b["name_local"], b["gender"], self._age(b), b.get("look", ""),
                                             seed=int(hashlib.sha1(f"{cid}{k}".encode()).hexdigest()[:6], 16),
                                             base=self._base(b, look))
                        s = self._apply_look(s, b, look)
                        CH.SPECS[cid] = s
                    ok, px = self._check(cid)
                    dist = self._distance(s, cid) if b["kind"] != "animal" else 99
                    if ok and (best is None or dist > best[0]):
                        best = (dist, copy.deepcopy(s), px)
                    if ok and dist >= 5:                 # original enough
                        break
                except Exception as e:
                    self.log(f"  [Asset Builder] {b['name']}: design {k + 1} failed ({str(e)[:120]})")
            if best is None:
                CH.SPECS.pop(cid, None)
                failed.append(b["name"])
                continue
            spec = best[1]
            spec["cast"] = "story_lib"
            spec["sample"] = False
            CH.SPECS[cid] = spec
            lib["characters"][cid] = {"spec": spec, "names": list(dict.fromkeys([b["name"], b["name_local"]])),
                                      "kind": b["kind"], "bot": self.bot, "species": b.get("species"),
                                      "brief": {k: b.get(k) for k in ("look", "doing", "gender", "age", "kind")},
                                      "story": b.get("story", ""), "key": story_key,
                                      "made": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                                      "check": {"front_side_pixels": best[2], "unlike_others": best[0]}}
            made.append(cid)
            self.log(f"  [Asset Builder] {b['name']} -> {cid} ({b['kind']}"
                     + (f", {b.get('species')}" if b.get("species") else "") + f", differs from every other face in {best[0]} features)")
        if made:
            os.makedirs(os.path.dirname(LIB_FILE), exist_ok=True)
            with open(LIB_FILE, "w", encoding="utf-8") as f:
                json.dump(lib, f, ensure_ascii=False, indent=1)
            load_library(force=True)
        return made, failed

    def sheet(self, cids, path):
        """a picture of the new characters, front and side, for the run's artifact"""
        import cv2
        import numpy as np
        from tvtoon import scene as SC
        if not cids:
            return None
        rows = []
        cast = [{"id": c, "x": 220 + k * 380} for k, c in enumerate(cids[:8])]
        for row in (cast, [dict(c, facing="right") for c in cast]):
            sp = {"location": "village_courtyard", "life": False, "size": [max(640, 380 * len(cast) + 80), 460], "look": "flat",
                  "world": {"hours": [[0, 11.0]]}, "cast": row, "beats": [{"pause": 2, "shot": "wide"}]}
            rows.append(SC.Scene(sp).render_frame(1.0))
        cv2.imwrite(path, np.vstack(rows))
        return path


# ===================================================================================================== the night run
def make_assets(story, key, bot="horror", category="", hours=5.0, log=print):
    """the 4 AM (horror) / 2 AM (cartoon) job for one story: the scout reads it, the builder makes what is new"""
    start = time.time()
    log(f"=== CHARACTER ASSETS for {key}: '{story.get('title', '')}' ===")
    scout = StoryScout(bot, category, log=log)
    report = scout.run(story)
    built, failed = [], []
    if report["new"] and time.time() - start < hours * 3600:
        builder = AssetBuilder(bot, log=log)
        built, failed = builder.build(report["new"], story_key=key)
        try:
            os.makedirs(REPORT_DIR, exist_ok=True)
            builder.sheet(built, os.path.join(REPORT_DIR, f"{key.replace(':', '')}_new_characters.jpg"))
        except Exception as e:
            log(f"  sheet skipped: {str(e)[:120]}")
    report.update(built=built, failed=failed, minutes=round((time.time() - start) / 60.0, 1),
                  made=dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"))
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{key.replace(':', '')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    log(f"  {len(built)} new character(s) made, {len(failed)} failed, {report['minutes']} min")
    return path, report


def cleanup(keep_days=4):
    """old night reports and pictures are removed (the characters stay in the library for ever)"""
    if not os.path.isdir(REPORT_DIR):
        return []
    gone = []
    cut = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
    for fn in os.listdir(REPORT_DIR):
        if fn[:10] < cut and fn[:4].isdigit():
            os.remove(os.path.join(REPORT_DIR, fn))
            gone.append(fn)
    return gone


# ===================================================================================================== at video time
SOLID_DEMON = ("rakshas", "rakshasa", "rakshasi", "asura", "daitya", "danav", "monster", "giant", "demoness", "ogre",
               "রাক্ষস", "রাক্ষসী", "অসুর", "দৈত্য", "দানব", "राक्षस", "राक्षसी", "असुर", "दैत्य", "दानव")


def _solid_demon(kind, look):
    """(28 Nov 2026: Tadaka the demoness came as a pale see-through ghost) a rakshasa / asura / monster of a
    mythology or fairy tale is a SOLID, big, dark-skinned character with glowing eyes - not a ghost; only a
    spirit / ghost / shadow floats see-through"""
    t = f"{kind} {look}".lower()
    if any(w in t for w in ("ghost", "spirit", "shadow-like", "shadowy", "misty", "ভূত", "প্রেত", "भूत")):
        return False
    return any(w in t for w in SOLID_DEMON) or kind.strip() == "demon"


def brief_of(ch, bot, species=None, story_title=""):
    kind = str(ch.get("kind", "human")).lower()
    look = str(ch.get("look", "") or "")
    for k in ("clothes", "costume", "dress", "appearance", "description"):
        if ch.get(k):
            look += " " + str(ch[k])
    return {"name": ch["name"], "name_local": ch.get("name_local") or ch["name"],
            "gender": "female" if str(ch.get("gender", "male")).lower().startswith("f") else "male",
            "age": ch.get("age"), "kind": "animal" if species else (
                "human" if _solid_demon(kind, look) else "ghost" if any(w in kind for w in GHOST_KINDS) else "human"),
            "species": species, "look": look, "doing": [], "story": story_title}


def ensure(ch, bot, species=None, story_title="", log=lambda *a: None):
    """the character built for exactly this name and look: from the library, or built right now (and kept)"""
    b = brief_of(ch, bot, species, story_title)
    hit = actor_for(b["name"], bot, b["gender"] if not species else None, species, b["look"])
    if hit:
        return hit
    made, _failed = AssetBuilder(bot, log=log).build([b])
    if not made:
        return None
    return made[0] + "__ghost" if b["kind"] == "ghost" else made[0]


def dressed(actor, look, ch=None):
    """a recurring character (same face, same body) wearing what the script describes this time - colours of each
    garment, glasses, crown, shawl ... - so 'Sayan in a pink polo shirt' is Sayan in a pink polo shirt"""
    base = CH.SPECS.get(actor)
    if not base or not str(look or "").strip():
        return actor
    vid = f"{actor}_v{hashlib.sha1(str(look).encode()).hexdigest()[:6]}"
    if vid in CH.SPECS:
        return vid
    s = copy.deepcopy(base)
    b = {"gender": "female" if (ch or {}).get("gender", s.get("gender", "")).lower().startswith("f") or
         CH.profile(actor)[1] == "female" else "male", "age": (ch or {}).get("age") or s.get("age")}
    keep = {k: copy.deepcopy(s[k]) for k in ("head", "face") if k in s}
    s = AssetBuilder("kids", log=lambda *a: None)._apply_look(s, b, f" {str(look).lower()} ", dress_only=True)
    s.update(keep)                                          # (the face is never changed)
    CH.SPECS[vid] = s
    return vid
