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


def find(name, bot=None, gender=None, species=None):
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
            return cid, rec.get("kind", "human")
    return None


def actor_for(name, bot=None, gender=None, species=None):
    hit = find(name, bot, gender, species)
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
            return K.kids_cast({"characters": chars}, self.category, use_library=False)
        from tvtoon import story as STY
        reveal = {}
        for n_, v_ in (story.get("ghost_reveal") or {}).items():
            reveal[n_] = v_
        return STY.cast_story(chars, reveal, use_library=False)

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
            if find(name, self.bot):
                row["in_library"] = True
                row["actor"] = actor_for(name, self.bot)
                continue
            role = None
            if actor and not actor.split("__")[0].startswith(("ep_", "kp_", "ka_")):
                role = role_missing(ch.get("look", ""), CH.get(actor.split("__")[0])) if not CH.get(actor.split("__")[0]).get("animal") else None
                if not role:
                    row["in_library"] = True               # an existing character plays it well
                    continue
                row["why"] = f"the story's '{role}' is not shown by {actor}"
            from tvtoon import animals as AM
            species = AM.species_of(f"{name} {ch.get('look', '')}") if (kind in ("animal", "bird") or self.bot == "kids") else None
            if kind in ("animal", "bird") and not species:
                species = "parrot" if kind == "bird" else "dog"
            brief = {"name": name, "name_local": ch.get("name_local") or name,
                     "gender": "female" if str(ch.get("gender", "male")).lower().startswith("f") else "male",
                     "age": ch.get("age"), "kind": "animal" if species else ("ghost" if any(w in kind for w in GHOST_KINDS) else "human"),
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
         "pajama": "dhoti", "dhoti": "dhoti", "lungi": "dhoti", "salwar": "dhoti", "shorts": "shorts", "border": "border",
         "ধুতি": "dhoti", "লুঙ্গি": "dhoti", "প্যান্ট": "trousers", "পাড়": "border", "धोती": "dhoti", "पैंट": "trousers"}
SADHU = ("sadhu", "sanyasi", "monk", "hermit", "tantrik", "tantric", "saint", "fakir", "সাধু", "সন্ন্যাসী", "তান্ত্রিক",
         "फकीर", "साधु", "संन्यासी", "तांत्रिक")
PRIEST = ("priest", "pandit", "purohit", "brahmin", "পুরোহিত", "পণ্ডিত", "ব্রাহ্মণ", "पुजारी", "पंडित", "ब्राह्मण")
SHIRT_WORDS = ("shirt", "trousers", "pant", "jeans", "uniform", "coat", "suit", "jacket", "police", "officer", "doctor",
               "inspector", "babu", "clerk", "teacher", "master", "driver", "জামা", "শার্ট", "প্যান্ট", "পুলিশ", "ডাক্তার",
               "शर्ट", "पैंट", "पुलिस", "डॉक्टर")
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
            if any(w in look for w in KURTA_WORDS):
                return {"old": "nibaran_dadu", "adult": "bhattacharya", "young": "sayan", "child": "bappa"}[age] \
                    if age != "young" else "sayan"
            if any(w in look for w in SHIRT_WORDS) and age in ("adult", "young"):
                return "ramu_chowkidar" if age == "adult" else "abhishek"
        else:
            if any(w in look for w in ("saree", "sari", "শাড়ি", "साड़ी")) and age in ("adult", "old", "young"):
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

    def _apply_look(self, s, b, look):
        cols = s["colours"]
        words = re.findall(r"[\w\-ঀ-৿ऀ-ॿ]+", look)
        for i, w in enumerate(words):                    # "<colour> <garment>" -> that garment in that colour
            col = COLOURS.get(w)
            if not col:
                continue
            for nxt in words[i + 1:i + 3]:
                key = UPPER.get(nxt) or LOWER.get(nxt)
                if key:
                    if key in cols or key in ("shirt", "kurta", "tshirt", "frock", "saree"):
                        tgt = key if key in cols else next((k for k in ("shirt", "kurta", "tshirt", "frock", "saree") if k in cols), None)
                        if tgt:
                            cols[tgt] = col
                    elif key == "trousers" and "dhoti" in cols:
                        cols["dhoti"] = col
                    elif key == "dhoti" and "trousers" in cols:
                        cols["trousers"] = col
                    break
                if nxt in ("hair", "চুল", "बाल"):
                    cols["hair"] = col if col not in ("#c62828", "#2e7d32", "#1e5aa8") else cols["hair"]
                    break
        acc = s.setdefault("accessories", [])
        has = lambda *ws: any(w in look for w in ws)
        if has("grey hair", "gray hair", "white hair", "silver hair", "পাকা চুল", "सफेद बाल"):
            cols["hair"] = "#c8c8c0"
        if has("bald", "টাক", "गंजा"):
            s["hair"] = {"style": "bald_sides"}
        elif has("curly", "কোঁকড়া", "घुंघराले"):
            s["hair"] = {"style": "curly"}
        elif b["gender"] == "female" and has("open hair", "loose hair", "long hair", "এলো চুল", "খোলা চুল", "खुले बाल"):
            s["hair"] = {"style": "open_long"}
        elif b["gender"] == "female" and has("bun", "খোঁপা", "जूड़ा"):
            s["hair"] = {"style": "bun_black" if self._age(b) != "old" else "bun_white"}
        elif has("braid", "plait", "বেণি", "चोटी"):
            s["hair"] = {"style": "braid_long" if b["gender"] == "female" else s["hair"]["style"]}
        if has(*SADHU):
            s["hair"] = {"style": "jata"}
            for a in ("rudraksha", "tilak"):
                if a not in acc:
                    acc.append(a)
            cols["kurta"] = cols.get("kurta") and COLOURS["saffron"] or cols.get("kurta")
            if "dhoti" in cols:
                cols["dhoti"] = COLOURS["saffron"]
            s["face"]["beard"] = 1.0
            cols.setdefault("beard", cols["hair"])
        if has(*PRIEST):
            for a in ("tilak", "sacred_thread"):
                if a not in acc:
                    acc.append(a)
        if has("glasses", "spectacle", "চশমা", "चश्मा") and "glasses_round" not in acc:
            acc.append("glasses_round")
        if b["gender"] == "male" and has("beard", "দাড়ি", "दाढ़ी"):
            s["face"]["beard"] = max(0.6, s["face"].get("beard", 0) or 0)
            cols.setdefault("beard", cols["hair"])
        if b["gender"] == "male" and has("moustache", "mustache", "গোঁফ", "मूंछ"):
            cols["moustache"] = cols["hair"]
        if has("turban", "pagri", "pagdi", "পাগড়ি", "पगड़ी") and "turban" not in acc:
            acc.append("turban")
        if has("shawl", "chador", "চাদর", "शॉल") and "shawl" not in acc:
            acc.append("shawl")
        if b["gender"] == "female" and has("sindoor", "সিঁদুর", "सिंदूर", "married", "বিবাহিত", "विवाहित"):
            for a in ("sindoor", "bindi"):
                if a not in acc:
                    acc.append(a)
        if b["gender"] == "female" and has("bangle", "চুড়ি", "चूड़ी") and "bangles" not in acc:
            acc.append("bangles")
        # the roles (so that the role reads at once, as the scout asked)
        if has("police", "constable", "daroga", "inspector", "khaki", "পুলিশ", "দারোগা", "पुलिस", "दरोगा") and "shirt" in cols:
            if cols["shirt"] not in COLOURS.values() or not has("shirt", "coat", "uniform") or has("khaki"):
                cols["shirt"] = COLOURS["khaki"]
            cols["trousers"] = COLOURS["khaki"]
        if has("doctor", "ডাক্তার", "डॉक्टर") and "shirt" in cols and not has("blue coat", "black coat"):
            cols["shirt"] = COLOURS["white"]
        if has("sahib", "british", "englishman", "memsahib", "সাহেব", "अंग्रेज"):
            cols["skin"] = "#f2d2b0"
            cols["hair"] = "#8a5a32" if self._age(b) != "old" else "#d8d8d0"
        if has("king", "raja", "maharaja", "zamindar", "রাজা", "জমিদার", "राजा", "ज़मींदार", "जमींदार") and b["gender"] == "male":
            for a in ("turban", "shawl"):
                if a not in acc:
                    acc.append(a)
            cols.setdefault("turban", COLOURS["cream"])
        if has("queen", "rani", "রানি", "রাণী", "रानी") and b["gender"] == "female" and "crown" not in acc:
            acc.append("crown")
        if has("tall", "লম্বা", "लंबा", "लंबी"):
            s["height"] = round(s["height"] * 1.08, 3)
        if has("short ", "বেঁটে", "नाटा", "छोटे कद"):
            s["height"] = round(s["height"] * 0.92, 3)
        if has("fat", "plump", "pot-belly", "potbelly", "stout", "মোটা", "ভুঁড়ি", "मोटा", "मोटी"):
            s["body"]["belly"] = max(0.25, s["body"].get("belly", 0) or 0)
        if has("thin", "lean", "skinny", "রোগা", "পাতলা", "दुबला", "पतला"):
            s["body"]["belly"] = 0.0
            s["body"]["shoulder"] = round(s["body"].get("shoulder", 0.7) * 0.9, 3)
        if has("dark skin", "dark-skinned", "কালো রং", "শ্যামলা", "सांवला", "सांवली"):
            s["colours"]["skin"] = "#8e5e40"
        if has("fair", "ফর্সা", "गोरा", "गोरी"):
            s["colours"]["skin"] = "#e0aa82"
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
            cid = f"lib_{self.bot[:1]}_{slug}_{hashlib.sha1((b['name'] + b.get('story', '')).encode()).hexdigest()[:5]}"
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
