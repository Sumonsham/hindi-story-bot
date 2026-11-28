"""THE KIDS' CARTOON CAST (23 Nov 2026) for the sister bot Sumonsham/hindi-story-bot: every category has its own
recurring characters, the same face in every episode, drawn by the tvtoon engine (no picture service).

  * Gopal Bhar's court: Gopal, Raja Krishnachandra, the minister, the queen, Gopal's wife, the guard, the general,
    the royal physician, the pandit, the moneylender, the sweet-maker, the merchant, the landlord, the farmer, the
    village woman - the same people as the bot's old ready-made characters (PUPPET_CAST);
  * Akbar and Birbal; King Vikram and Betal;
  * the host Lumi Didi with Mithu the parrot; Sumon ("Saheb", classic and modern); Sayan (8) and his family
    (Trisha, Chhanda, Tapati, Ajoy, Priya, Reba);
  * our own series: Bhutu, Tublu and Mini; Rimli and her puppy Bhola; Tukai and his dog Bhulu; Didima, Pupu and
    Tatai; Robot Robi and Jhilik;
  * the gods and the epics: Rama, Sita, Lakshmana, Hanuman, Ravana, Dasharatha, Krishna, Radha, Balarama, Yashoda,
    Arjuna, Bhishma, Yudhishthira, Bhima, Draupadi, Karna, Duryodhana, Kunti, Shiva, Parvati, Ganesha, Kartik,
    Durga, Lakshmi, Saraswati, Narada - respectful, gentle, with their own colours, crowns and halos;
  * animals and birds for Panchatantra / Jataka / animal stories (animals.py), each story's animal keeps its look.

kids_cast(story, category) gives every story character its actor; anyone who is not in the library becomes a new
character (a person, an animal by its species) with its own look for the whole episode."""
import copy
import hashlib
import re

from tvtoon import animals as AM
from tvtoon import characters as CH
from tvtoon import story as STY

KIDS = {}


def _mk(cid, base, name_bn, *, colours=None, hair=None, face=None, body=None, costume=None, acc=None, height=None, age=None,
        category=None, heads=None, head=None, ghost=None, drop=()):
    s = copy.deepcopy(CH.SPECS[base])
    s.update({"name_bn": name_bn, "name_en": cid, "cast": "kids", "sample": False})
    s.pop("ghost", None)
    for k, v in (("colours", colours), ("face", face), ("body", body), ("head", head)):
        if v:
            s[k].update(v)
    if hair:
        s["hair"] = {"style": hair}
    if costume:
        s["costume"].update(costume)
    if acc is not None:
        s["accessories"] = [a for a in s.get("accessories", []) if a not in drop] + [a for a in acc if a not in s.get("accessories", [])]
    for a in drop:
        if a in s.get("accessories", []):
            s["accessories"].remove(a)
        s["face"].pop(a, None)
    if height:
        s["height"] = height
    if heads:
        s["heads"] = heads
    if age is not None:
        s["age"] = age
    if category:
        s["category"] = category
    if ghost:
        s["ghost"] = ghost
    s["face"]["ghost_eyes"] = bool(ghost)
    KIDS[cid] = s
    CH.SPECS[cid] = s
    return s


def _animal(cid, name_bn, species, look="", gender="male", age="adult", colours=None, acc=()):
    s = AM.make_spec(name_bn, species, look, gender, age)
    if colours:
        s["colours"].update(colours)
    s["accessories"] = list(dict.fromkeys(list(s["accessories"]) + list(acc)))
    KIDS[cid] = s
    CH.SPECS[cid] = s
    return s


M, F = "ramu_chowkidar", "parul"          # (bases: a grown man / woman of the library)

# ---------------------------------------------------------------- Gopal Bhar's court (the bot's PUPPET_CAST)
_mk("gopal", "bhattacharya", "গোপাল", colours={"kurta": "#4caf50", "dhoti": "#f4f1e8", "skin": "#c48a62"},
    hair="tiki", acc=["tilak", "shawl"], body={"belly": 0.1}, face={"eye_style": "round", "nose": "round"}, height=0.92)
CH.SPECS["gopal"]["colours"]["shawl"] = "#9a2a2a"
_mk("raja", M, "রাজা", colours={"kurta": "#1e4fa8", "dhoti": "#f2e6c8", "turban": "#f2efe6", "moustache": "#1a1410", "shawl": "#7a1a2a"},
    costume={"type": "kurta_dhoti", "sleeve": "full"}, hair="crop", acc=["turban", "jewel", "plume", "shawl"], height=1.05,
    face={"nose": "long", "eye_style": "almond"})
_mk("mantri", M, "মন্ত্রী", colours={"kurta": "#5a2a8a", "dhoti": "#e8e0f0", "turban": "#e67a1a", "beard": "#3a3028", "moustache": "#3a3028"},
    costume={"type": "kurta_dhoti", "sleeve": "full"}, acc=["turban"], face={"beard": 0.4, "nose": "pointed", "eye_style": "narrow"},
    body={"shoulder": 0.62, "waist": 0.5, "hip": 0.5}, height=1.07, head={"shape": "long", "w": 0.68})
_mk("rani", F, "রানি", colours={"saree": "#c62828", "border": "#e0b030", "blouse": "#e0b030", "crown": "#e0b030"},
    acc=["crown", "sindoor", "bindi", "bangles", "earrings"], height=0.92)
_mk("gopal_bou", F, "গোপালের বউ", colours={"saree": "#f4f1e8", "border": "#c62828", "blouse": "#c62828"},
    acc=["sindoor", "bindi", "bangles"], body={"belly": 0.12}, face={"eye_style": "round", "nose": "button"})
_mk("paharadar", M, "পাহারাদার", colours={"kurta": "#f2efe6", "dhoti": "#f2efe6", "turban": "#c62828", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "half"}, acc=["turban"], height=1.1, body={"shoulder": 0.9})
_mk("senapati", M, "সেনাপতি", colours={"kurta": "#7a1a1a", "dhoti": "#9a9aa4", "turban": "#f08a1a", "beard": "#1a1410", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "half"}, acc=["turban"], face={"beard": 1.0}, height=1.08, body={"shoulder": 0.92, "chest": 0.85})
_mk("rajvaidya", "shibu_dadu", "রাজবৈদ্য", colours={"kurta": "#1a7a6a", "dhoti": "#e8f0ea", "turban": "#2e7d32"},
    acc=["turban", "glasses_round"], body={"belly": 0.15}, height=0.86, drop=("shawl",))
_mk("pandit", "shibu_dadu", "পণ্ডিতমশাই", colours={"kurta": "#f4f1e8", "dhoti": "#f4f1e8", "shawl": "#e8dcc0"},
    hair="tiki", acc=["glasses_round", "tilak", "sacred_thread"], face={"beard": 0.0}, body={"belly": 0.0}, height=0.95)
_mk("mahajan", "shibu_dadu", "মহাজন", colours={"kurta": "#efe6cf", "dhoti": "#f4f1e8", "moustache": "#8a8a84"},
    acc=[], face={"beard": 0.0}, body={"belly": 0.3}, drop=("shawl",))
_mk("moyra", M, "ময়রা", colours={"kurta": "#f8f8f4", "dhoti": "#f8f8f4", "moustache": "#1a1410", "shawl": "#2e7d32"},
    costume={"type": "kurta_dhoti", "sleeve": "none"}, hair="bald_sides", acc=["shawl"], body={"belly": 0.25})
_mk("bonik", M, "বণিক", colours={"kurta": "#c2185b", "dhoti": "#f8e0ec", "turban": "#c2185b", "beard": "#1a1410", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "full"}, acc=["turban", "jewel"], face={"beard": 0.35}, body={"belly": 0.15})
_mk("zamindar", "shibu_dadu", "জমিদার", colours={"kurta": "#efe6cf", "shawl": "#8a8a84", "moustache": "#a8a8a0"},
    face={"beard": 0.0, "nose": "long"}, head={"shape": "long", "w": 0.7}, body={"belly": 0.0, "shoulder": 0.6}, height=1.05)
_mk("chashi", M, "চাষি", colours={"kurta": "#8a5a32", "dhoti": "#f0ead8", "turban": "#c62828", "skin": "#9a6a48", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "half"}, acc=["turban"], body={"shoulder": 0.7, "waist": 0.52}, head={"shape": "oval", "w": 0.72})
_mk("gramer_bou", F, "গ্রামের বউ", colours={"saree": "#f9c02a", "border": "#2e7d32", "blouse": "#2e7d32"},
    acc=["sindoor", "bindi", "bangles"], face={"eye_style": "almond", "nose": "pointed"}, body={"belly": 0.0})

# ---------------------------------------------------------------- Akbar - Birbal, Vikram - Betal
_mk("akbar", M, "আকবর", colours={"kurta": "#e0b030", "dhoti": "#f2e6c8", "turban": "#f2efe6", "beard": "#2a1a10", "moustache": "#2a1a10"},
    costume={"type": "kurta_dhoti", "sleeve": "full"}, acc=["turban", "jewel", "plume"], face={"beard": 0.7}, height=1.04)
_mk("birbal", M, "বীরবল", colours={"kurta": "#f4ead2", "dhoti": "#f4ead2", "turban": "#e67a1a", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "full"}, acc=["turban", "tilak"], face={"eye_style": "round", "nose": "button"}, body={"belly": 0.1})
_mk("vikram", M, "রাজা বিক্রম", colours={"kurta": "#b71c1c", "dhoti": "#f2e6c8", "crown": "#e0b030", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "half"}, acc=["crown"], height=1.08, body={"shoulder": 0.88})
_mk("betal", "shibu_dadu", "বেতাল", colours={"skin": "#c8d2d8", "kurta": "#e8eef0", "dhoti": "#e8eef0", "hair": "#e8e8e0"},
    hair="open_long", face={"beard": 0.0, "iris": "#b0102a", "glow": "#ffe680"}, body={"belly": 0.0, "shoulder": 0.55},
    ghost={"float": 0.08, "alpha": 0.9, "tint": "#e8f4ff"}, drop=("shawl",))

# ---------------------------------------------------------------- the host, Sumon, Sayan's family
CH.SPECS["lumi_didi"].setdefault("cast", "kids")
_animal("mithu", "মিঠু", "parrot", "green parrot", age="child")
_mk("saheb", "abhishek", "সুমন", colours={"kurta": "#7a1a2a", "dhoti": "#f2e6c8", "shawl": "#f2e6c8"},
    costume={"type": "kurta_dhoti", "sleeve": "full"}, acc=["shawl"], face={"eye_style": "round", "nose": "round"}, head={"shape": "oval", "w": 0.8})
_mk("saheb_modern", "abhishek", "সুমন", colours={"shirt": "#1a8a8a", "trousers": "#1e3a6a"}, costume={"sleeve": "half"},
    face={"eye_style": "round", "nose": "round"}, head={"shape": "oval", "w": 0.8})
_mk("sayan_kid", "bappa", "সায়ন", colours={"tshirt": "#1e88e5", "shorts": "#5a4a3a", "hair": "#3a2414"}, hair="side_part",
    face={"eye_style": "round"}, age=8)
_mk("trisha", "riya", "ত্রিশা", colours={"kurta": "#64b5f6", "dhoti": "#f2f2f2"}, acc=["glasses_round"], age=15, height=0.88)
_mk("chhanda", F, "ছন্দা", colours={"saree": "#f9c02a", "border": "#c62828", "blouse": "#c62828"}, acc=["sindoor", "bindi", "bangles"],
    face={"eye_style": "almond"}, body={"belly": 0.0}, age=30)
_mk("tapati", "mokkhoda", "তপতী", colours={"saree": "#7a1a2a", "border": "#f2e6c8", "blouse": "#f2e6c8", "hair": "#6a6a62"},
    hair="bun_black", acc=["sindoor", "bindi", "glasses_round", "bangles"], body={"stoop": 0.0}, age=50, height=0.88)
_mk("ajoy", "shibu_dadu", "অজয়", colours={"kurta": "#f8f8f4", "dhoti": "#f8f8f4", "shawl": "#8a5a32", "moustache": "#a8a8a0"},
    acc=["glasses_round"], face={"beard": 0.0}, body={"belly": 0.35, "stoop": 0.0}, age=62)
_mk("priya", F, "প্রিয়া", colours={"saree": "#43a047", "border": "#f9c02a", "blouse": "#f9c02a"}, acc=["sindoor", "bindi"],
    face={"eye_style": "round", "nose": "pointed"}, age=38)
_mk("reba", "mokkhoda", "রেবা", colours={"saree": "#f8f8f4", "border": "#f8f8f4", "blouse": "#f8f8f4"}, acc=[], age=80, drop=("sindoor", "bindi"))

# ---------------------------------------------------------------- our own series
_animal("bhutu", "ভুতু", "bhutu", "orange scarf", age="child", colours={"scarf": "#ff8a2a"})
_mk("tublu", "bappa", "টুবলু", colours={"tshirt": "#f9c02a", "shorts": "#1e5aa8", "hair": "#120e0c"}, hair="spiky", age=9)
_mk("mini", "mili", "মিনি", colours={"frock": "#f48fb1", "ribbon": "#c62828"}, acc=["glasses_round"], age=8)
_mk("rimli", "kishori", "রিমলি", colours={"frock": "#64b5f6", "ribbon": "#f9c02a"}, age=10)
_animal("bhola", "ভোলা", "dog", "brown and white puppy red collar", age="child", acc=["collar"], colours={"scarf": "#c62828"})
_mk("tukai", "bappa", "টুকাই", colours={"tshirt": "#f57c00", "shorts": "#a89466", "hair": "#120e0c"}, hair="crop", age=10)
_animal("bhulu", "ভুলু", "dog", "golden brown dog blue collar", age="young", acc=["collar"], colours={"body": "#c8963a", "scarf": "#1e5aa8"})
_mk("didima", "mokkhoda", "দিদিমা", colours={"saree": "#f8f8f4", "border": "#c62828", "blouse": "#f8f8f4", "shawl": "#a8845e"},
    acc=["glasses_round", "shawl"], body={"stoop": 0.05}, age=70)
_mk("pupu", "mili", "পুপু", colours={"frock": "#8e44ad"}, hair="bun_black", age=7)
_mk("tatai", "bappa", "তাতাই", colours={"tshirt": "#43a047", "stripe": "#f2f2f2", "shorts": "#2e5a2e"}, hair="curly", age=9)
_animal("robi", "রবি", "robot", "", age="child")
_mk("jhilik", "kishori", "ঝিলিক", colours={"frock": "#f9c02a", "ribbon": "#1e5aa8"}, hair="pigtails", age=10)

# ---------------------------------------------------------------- the gods and the epics (gentle, respectful)
DIV = ["halo"]
_mk("rama", "abhishek", "শ্রীরাম", colours={"skin": "#5a7ab8", "kurta": "#f0a030", "dhoti": "#f9d24a", "crown": "#e0b030", "lip": "#7a3a4a"},
    costume={"type": "kurta_dhoti", "sleeve": "none"}, hair="open_long", acc=DIV + ["mukut", "tilak", "rudraksha"], height=1.06)
_mk("sita", "riya", "সীতা", colours={"kurta": "#c62828", "dhoti": "#c62828", "crown": "#e0b030"}, costume={"type": "saree", "sleeve": "short"},
    acc=DIV + ["crown", "sindoor", "bindi", "bangles", "earrings"])
CH.SPECS["sita"]["colours"].update({"saree": "#c62828", "border": "#e0b030", "blouse": "#e0b030"})
_mk("lakshmana", "abhishek", "লক্ষ্মণ", colours={"kurta": "#e65100", "dhoti": "#f9d24a", "crown": "#e0b030"},
    costume={"type": "kurta_dhoti", "sleeve": "none"}, hair="open_long", acc=["crown", "tilak"], face={"nose": "pointed"}, height=1.02)
_mk("hanuman", "ramu_chowkidar", "হনুমান", colours={"skin": "#d8642a", "kurta": "#c62828", "dhoti": "#c62828", "crown": "#e0b030",
                                                   "muzzle": "#f2c89a", "hair": "#8a3a1a"},
    costume={"type": "kurta_dhoti", "sleeve": "none"}, hair="crop", acc=DIV + ["crown", "vanara"], body={"shoulder": 0.95, "chest": 0.9},
    face={"eye_style": "round", "nose": "broad"}, head={"shape": "round", "w": 0.88})
_mk("ravana", "ramu_chowkidar", "রাবণ", colours={"kurta": "#3a1a4a", "dhoti": "#2a1a3a", "crown": "#e0b030", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "full"}, acc=["mukut"], height=1.15, body={"shoulder": 0.95, "belly": 0.1})
_mk("dasharatha", "shibu_dadu", "রাজা দশরথ", colours={"kurta": "#b71c1c", "dhoti": "#f2e6c8", "crown": "#e0b030"},
    acc=["crown"], drop=("shawl",), body={"stoop": 0.0})
_mk("krishna", "abhishek", "শ্রীকৃষ্ণ", colours={"skin": "#4a6ab0", "kurta": "#f9d24a", "dhoti": "#f9d24a", "crown": "#e0b030", "lip": "#7a3a4a"},
    costume={"type": "kurta_dhoti", "sleeve": "none"}, hair="curly", acc=DIV + ["mukut", "peacock_feather", "rudraksha"], age=16,
    face={"eye_style": "almond", "nose": "button"}, height=0.98)
_mk("radha", "riya", "রাধা", colours={"kurta": "#e91e63", "dhoti": "#e91e63", "crown": "#e0b030"}, costume={"type": "saree", "sleeve": "short"},
    acc=["crown", "bindi", "bangles", "earrings"])
CH.SPECS["radha"]["colours"].update({"saree": "#e91e63", "border": "#e0b030", "blouse": "#f9d24a"})
_mk("balarama", "ramu_chowkidar", "বলরাম", colours={"skin": "#f2d2b0", "kurta": "#1e5aa8", "dhoti": "#1e5aa8", "crown": "#e0b030"},
    costume={"type": "kurta_dhoti", "sleeve": "none"}, acc=["crown"], body={"shoulder": 0.95})
_mk("yashoda", F, "যশোদা মা", colours={"saree": "#f57c00", "border": "#c62828", "blouse": "#c62828"}, acc=["sindoor", "bindi", "bangles"])
_mk("arjuna", "abhishek", "অর্জুন", colours={"kurta": "#f2efe6", "dhoti": "#e0b030", "crown": "#e0b030"}, costume={"type": "kurta_dhoti", "sleeve": "none"},
    hair="open_long", acc=["crown"])
_mk("bhishma", "shibu_dadu", "ভীষ্ম", colours={"kurta": "#f8f8f4", "dhoti": "#f8f8f4", "hair": "#f2f2ec", "beard": "#f2f2ec"},
    hair="open_long", face={"beard": 1.0}, drop=("shawl",), body={"stoop": 0.0}, height=1.06)
_mk("yudhishthira", "ramu_chowkidar", "যুধিষ্ঠির", colours={"kurta": "#f2efe6", "dhoti": "#e0b030", "crown": "#e0b030", "beard": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "half"}, acc=["crown"], face={"beard": 0.3})
_mk("bhima", "ramu_chowkidar", "ভীম", colours={"kurta": "#e65100", "dhoti": "#e65100", "crown": "#e0b030", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "none"}, acc=["crown"], body={"shoulder": 1.05, "chest": 1.0, "belly": 0.12}, height=1.12)
_mk("draupadi", F, "দ্রৌপদী", colours={"saree": "#b71c1c", "border": "#e0b030", "blouse": "#e0b030", "skin": "#a8744e"},
    hair="open_long", acc=["crown", "bindi", "bangles"])
_mk("karna", "abhishek", "কর্ণ", colours={"kurta": "#e0b030", "dhoti": "#b71c1c", "crown": "#e0b030"}, costume={"type": "kurta_dhoti", "sleeve": "half"},
    acc=["crown", "earrings"])
_mk("duryodhana", "ramu_chowkidar", "দুর্যোধন", colours={"kurta": "#4a1a6a", "dhoti": "#e0b030", "crown": "#e0b030", "moustache": "#1a1410"},
    costume={"type": "kurta_dhoti", "sleeve": "full"}, acc=["crown"])
_mk("kunti", "mokkhoda", "কুন্তী", colours={"saree": "#f8f8f4", "border": "#e0b030", "blouse": "#f8f8f4"}, body={"stoop": 0.0}, age=55)
_mk("shiva", "ojha", "মহাদেব", colours={"skin": "#7a9ab8", "kurta": "#f2efe6", "dhoti": "#e8a040", "hair": "#2a1a10"},
    hair="jata", acc=DIV + ["rudraksha"], face={"beard": 0.0, "brow_thick": 1.0}, drop=("tilak",), body={"shoulder": 0.9})
_mk("parvati", F, "মা পার্বতী", colours={"saree": "#c62828", "border": "#e0b030", "blouse": "#e0b030", "crown": "#e0b030"},
    acc=DIV + ["crown", "sindoor", "bindi", "bangles", "earrings"])
_mk("ganesha", "bhattacharya", "গণেশ", colours={"skin": "#e8a8a0", "kurta": "#f9d24a", "dhoti": "#c62828", "crown": "#e0b030"},
    hair="crop", acc=DIV + ["crown", "elephant_head"], body={"belly": 0.35}, height=0.9)
_mk("kartik", "abhishek", "কার্তিক", colours={"kurta": "#f9d24a", "dhoti": "#c62828", "crown": "#e0b030"},
    costume={"type": "kurta_dhoti", "sleeve": "none"}, acc=DIV + ["crown"], age=18)
_mk("durga", F, "মা দুর্গা", colours={"saree": "#c62828", "border": "#e0b030", "blouse": "#e0b030", "crown": "#e0b030"},
    hair="open_long", acc=DIV + ["mukut", "sindoor", "bindi", "bangles", "earrings"], height=0.98)
_mk("lakshmi", F, "মা লক্ষ্মী", colours={"saree": "#f06292", "border": "#e0b030", "blouse": "#e0b030", "crown": "#e0b030"},
    acc=DIV + ["crown", "bindi", "bangles", "earrings"])
_mk("saraswati", F, "মা সরস্বতী", colours={"saree": "#f8f8f4", "border": "#e0b030", "blouse": "#f9d24a", "crown": "#e0b030"},
    acc=DIV + ["crown", "bindi", "earrings"])
_mk("narada", "shibu_dadu", "নারদ মুনি", colours={"kurta": "#f8f8f4", "dhoti": "#f57c00", "hair": "#e8e8e0"}, hair="tiki",
    acc=["tilak", "rudraksha"], drop=("shawl",), face={"beard": 0.6})

# ---------------------------------------------------------------- names in the stories -> our characters
ALIASES = {
    "gopal": ["gopal", "গোপাল", "गोपाल"], "raja": ["raja", "king", "রাজা", "राजा", "maharaj", "মহারাজ", "महाराज", "krishnachandra", "কৃষ্ণচন্দ্র"],
    "mantri": ["mantri", "minister", "মন্ত্রী", "मंत्री"], "rani": ["rani", "queen", "রানি", "রাণী", "रानी"],
    "gopal_bou": ["gopal's wife", "গোপালের বউ", "গোপালের বৌ"], "paharadar": ["guard", "paharadar", "পাহারাদার", "প্রহরী", "पहरेदार"],
    "senapati": ["senapati", "general", "সেনাপতি", "सेनापति"], "rajvaidya": ["rajvaidya", "physician", "বৈদ্য", "वैद्य"],
    "pandit": ["pandit", "পণ্ডিত", "पंडित"], "mahajan": ["mahajan", "moneylender", "মহাজন", "महाजन"], "moyra": ["moyra", "ময়রা", "हलवाई"],
    "bonik": ["bonik", "merchant", "বণিক", "सौदागर", "व्यापारी"], "zamindar": ["zamindar", "জমিদার", "ज़मींदार", "जमींदार"],
    "chashi": ["chashi", "farmer", "চাষি", "চাষী", "किसान"], "gramer_bou": ["village woman", "গ্রামের বউ"],
    "akbar": ["akbar", "আকবর", "अकबर"], "birbal": ["birbal", "বীরবল", "बीरबल"], "vikram": ["vikram", "বিক্রম", "विक्रम"],
    "betal": ["betal", "baital", "বেতাল", "बेताल"], "lumi_didi": ["lumi", "লুমি", "लूमी"], "mithu": ["mithu", "মিঠু", "मिट्ठू"],
    "saheb": ["sumon", "saheb", "সুমন", "सुमन"], "sayan_kid": ["sayan", "সায়ন", "सायन"], "trisha": ["trisha", "ত্রিশা", "तृषा"],
    "chhanda": ["chhanda", "ছন্দা", "छंदा"], "tapati": ["tapati", "তপতী", "तपती"], "ajoy": ["ajoy", "অজয়", "अजय"],
    "priya": ["priya", "প্রিয়া", "प्रिया"], "reba": ["reba", "রেবা", "रेबा"], "bhutu": ["bhutu", "ভুতু", "भूतू"],
    "tublu": ["tublu", "টুবলু", "टुबलू"], "mini": ["mini", "মিনি", "मिनी"], "rimli": ["rimli", "রিমলি", "रिमली"],
    "bhola": ["bhola", "ভোলা", "भोला"], "tukai": ["tukai", "টুকাই", "टुकाई"], "bhulu": ["bhulu", "ভুলু", "भुलू"],
    "didima": ["didima", "দিদিমা", "नानी"], "pupu": ["pupu", "পুপু", "पुपु"], "tatai": ["tatai", "তাতাই", "ताताई"],
    "robi": ["robi", "robot", "রবি", "रवि"], "jhilik": ["jhilik", "ঝিলিক", "झिलिक"],
    "rama": ["rama", "ram", "রাম", "राम", "রামচন্দ্র"], "sita": ["sita", "সীতা", "सीता"], "lakshmana": ["lakshman", "laxman", "লক্ষ্মণ", "लक्ष्मण"],
    "hanuman": ["hanuman", "হনুমান", "हनुमान", "bajrang"], "ravana": ["ravan", "রাবণ", "रावण"], "dasharatha": ["dasharath", "dashrath", "দশরথ", "दशरथ"],
    "krishna": ["krishna", "kanha", "কৃষ্ণ", "कृष्ण", "কানাই", "कान्हा", "গোপাল ঠাকুর"], "radha": ["radha", "রাধা", "राधा"],
    "balarama": ["balaram", "বলরাম", "बलराम"], "yashoda": ["yashoda", "যশোদা", "यशोदा"], "arjuna": ["arjun", "অর্জুন", "अर्जुन"],
    "bhishma": ["bhishma", "ভীষ্ম", "भीष्म"], "yudhishthira": ["yudhishthir", "যুধিষ্ঠির", "युधिष्ठिर"], "bhima": ["bhima", "bheem", "ভীম", "भीम"],
    "draupadi": ["draupadi", "দ্রৌপদী", "द्रौपदी"], "karna": ["karna", "কর্ণ", "कर्ण"], "duryodhana": ["duryodhan", "দুর্যোধন", "दुर्योधन"],
    "kunti": ["kunti", "কুন্তী", "कुंती"], "shiva": ["shiva", "shiv", "mahadev", "শিব", "মহাদেব", "शिव", "महादेव", "bholenath"],
    "parvati": ["parvati", "পার্বতী", "पार्वती", "uma", "উমা"], "ganesha": ["ganesh", "গণেশ", "गणेश"], "kartik": ["kartik", "কার্তিক", "कार्तिक"],
    "durga": ["durga", "দুর্গা", "दुर्गा"], "lakshmi": ["lakshmi", "লক্ষ্মী", "लक्ष्मी"], "saraswati": ["saraswati", "সরস্বতী", "सरस्वती"],
    "narada": ["narad", "নারদ", "नारद"],
}
GOPAL_COURT = ("gopal", "raja", "mantri", "rani", "gopal_bou", "paharadar", "senapati", "rajvaidya", "pandit", "mahajan", "moyra",
               "bonik", "zamindar", "chashi", "gramer_bou")
SERIES_CAST = {"gopal": GOPAL_COURT, "birbal": ("akbar", "birbal"), "betal": ("vikram", "betal")}
EXTRAS = ["chashi", "moyra", "bonik", "gramer_bou", "pandit", "mahajan", "paharadar", "haripada", "nibaran_dadu", "sarala_thakuma",
          "bappa", "mili", "tublu", "mini", "tatai", "pupu", "jhilik", "rimli"]


def _match(name, ids=None):
    n = str(name or "").lower().strip()
    best = None
    for cid, words in ALIASES.items():
        if ids and cid not in ids:
            continue
        for w in words:
            if re.search(r"(?<![a-zঀ-৿ऀ-ॿ])" + re.escape(w.lower()) + r"(?![a-z])", n):
                if best is None or len(w) > best[1]:
                    best = (cid, len(w))
    return best[0] if best else None


GENERIC_ROLES = {"raja", "mantri", "rani", "paharadar", "senapati", "rajvaidya", "pandit", "mahajan", "moyra", "bonik",
                 "zamindar", "chashi", "gramer_bou"}       # Gopal's court: a role word ("king") is NOT Gopal's king elsewhere


def _exact_alias(name, actor):
    n = str(name or "").lower().strip()
    return any(n == w.lower() for w in ALIASES.get(actor, []))


def kids_cast(story, category="", use_library=True, build=True):
    """story character name -> (actor id, name shown) for a kids' story - EXACTLY as the script describes them
    (owner, 24 Nov 2026):
      * our recurring characters (Gopal, Birbal, Krishna, Bhutu, Tukai, Didima, Sumon, Sayan ...) by name - dressed
        the way the script describes them this time (colours, glasses, crown ...), the face stays theirs;
      * 'King Hemanta' is not Gopal's king: a role word only means Gopal's court in the Gopal stories (or when the
        name is just that word);
      * everyone else is the character built for exactly this name and look (the night's library, prep.py) - or is
        built from the script's look right now; animals by their species.
    build=False (the night scout): whoever would be built is marked ("NEW", shown)."""
    out, used = {}, set()
    try:
        from tvtoon import prep as PRP
    except Exception:
        PRP = None
    series = SERIES_CAST.get(category, ())
    for ch in story.get("characters", []) or []:
        name = ch.get("name")
        if not name or str(name).lower() in ("narrator", "কথক", "कथावाचक"):
            continue
        shown = ch.get("name_local") or name
        kind = str(ch.get("kind", "human")).lower()
        look = str(ch.get("look", ""))
        actor = _match(name, series) or _match(name)
        if actor in GENERIC_ROLES and category != "gopal" and not _exact_alias(name, actor) and not _exact_alias(shown, actor):
            actor = None
        if actor and actor in used:
            actor = None
        if actor and look.strip() and PRP is not None and not CH.SPECS.get(actor, {}).get("animal"):
            actor = PRP.dressed(actor, look, ch) or actor     # the recurring face, dressed as the script says
        g_ = "female" if str(ch.get("gender", "male")).lower().startswith("f") else "male"
        sp_ = AM.species_of(f"{name} {look}") if (kind in ("animal", "bird") or AM.species_of(name)
                                                  or (kind != "human" and AM.species_of(look))) else None
        if actor is None and use_library and PRP is not None:   # built for this name at night (prep.py)
            actor = PRP.actor_for(name, "kids", g_ if not sp_ else None, sp_, look) or \
                PRP.actor_for(ch.get("name_local"), "kids", g_ if not sp_ else None, sp_, look)
            if actor and actor in used:
                actor = None
        if actor is None and kind == "robot" and "robi" not in used:
            actor = "robi"
        if actor is None and kind in ("magic friend", "spirit") and not look.strip() and "bhutu" not in used:
            actor = "bhutu"
        if actor is None and not build:
            out[name] = ("NEW", shown)
            continue
        if actor is None and PRP is not None:                 # build it now, from the script's own words
            try:
                actor = PRP.ensure(ch, "kids", species=sp_, story_title=story.get("title", ""))
            except Exception:
                actor = None
        if actor is None and sp_:
            cid = "ka_" + hashlib.sha1(f"{name}|{look}".encode()).hexdigest()[:8]
            if cid not in CH.SPECS:
                CH.SPECS[cid] = AM.make_spec(shown, sp_, look, str(ch.get("gender", "male")), STY._age(ch.get("age")))
            actor = cid
        if actor is None:                                   # (last resort) a new face from the look
            cid = "kp_" + hashlib.sha1(str(name).encode()).hexdigest()[:8]
            if cid not in CH.SPECS:
                CH.new_character(cid, shown, g_, STY._age(ch.get("age")), look, seed=len(used))
            actor = cid
        used.add(actor)
        out[name] = (actor, shown)
    return out


INSIDE_WORDS = ("room", "house", "home", "kitchen", "hall", "court", "darbar", "durbar", "class", "hospital", "office",
                "shop", "inside", "bed", "hut", "ঘর", "বাড়ি", "রান্নাঘর", "সভা", "দরবার", "घर", "कमरा", "दरबार", "सभा", "रसोई")
OUT_PLACES = [  # a kids' place the horror words do not know -> the outdoor place that fits it
    (("heaven", "swarga", "sky", "cloud", "kailash", "himalaya", "cave", "hill", "স্বর্গ", "আকাশ", "কৈলাস", "পাহাড়", "গুহা",
      "स्वर्ग", "आकाश", "कैलाश", "पहाड़", "गुफा"), "mountain"),
    (("lanka", "লঙ্কা", "लंका", "fort", "কেল্লা", "किला"), "palace"),
    (("tree", "banyan", "garden", "farm", "orchard", "mango", "ashram", "vrindavan", "gokul", "mathura", "village", "meadow",
      "গাছ", "বাগান", "আশ্রম", "বৃন্দাবন", "গোকুল", "গ্রাম", "पेड़", "बाग", "आश्रम", "वृंदावन", "गोकुल", "गांव", "गाँव"),
     "village courtyard"),
]


def kids_place(p, prev=None):
    """the place of a kids' story scene, said so the engine finds the right place (never an empty bedroom for 'under
    the big tree'). prev = the place of the scene before: a place that names nothing we know ("In front of the True
    Door") is still THERE (28 Nov 2026: it jumped from the palace corridor to a village courtyard full of villagers)"""
    low = str(p or "").lower()
    if STY.place_of(p, outdoor_guess=False) != "ghar" or any(w in low for w in INSIDE_WORDS) or \
            any(w in low for _k, ws in STY.ROOM_KINDS for w in ws):
        return p                                            # (it names its place: a corridor IS a corridor)
    for words, to in OUT_PLACES:
        if any(w in low for w in words):
            return f"{to}, {p}"
    if any(w in low for w in ("door", "corridor", "stair", "tower", "chamber", "window", "wall", "floor", "দরজা",
                              "সিঁড়ি", "দরজার", "জানলা", "দেয়াল", "दरवाज", "सीढ़ी", "खिड़की")):
        return f"{prev} - {p}" if prev else p              # (a part of a building: inside, the same building)
    if prev:
        return f"{prev} - {p}"
    if STY.place_of(p) != "ghar":
        return p                                            # (the outdoor words: road, field, path ...)
    return f"village courtyard, {p}"


def plan(story, category=""):
    """the tvtoon episode of a kids' story, with the kids' cast"""
    st = copy.deepcopy(story)
    prev = None
    for sc in st.get("scenes", []):                         # the kids' stories say little about time: daytime
        sc["place"] = kids_place(sc.get("place", ""), prev)
        prev = re.sub(r", sunny day$", "", str(sc["place"]))[:120]
        p = str(sc.get("place", ""))
        first_ = " ".join(str(l_.get("text", "")) + " " + str(l_.get("en", "")) for l_ in (sc.get("lines") or [])[:2])
        if not any(w in p.lower() for w in STY.NIGHT + STY.DUSK + ["morning", "noon", "day", "সকাল", "দুপুর"]) \
                and STY.hours_of(first_, "", inherit=-1.0) < 0:     # (26 Nov 2026: "বিকেলবেলা ..." in the lines counts)
            sc["place"] = p + ", sunny day" if p else "a village, sunny day"
    return STY.episode_from_story(st, cast=kids_cast(st, category))


def host_scene(lines, subs, line_wavs, dur, W, H, fps):
    """Lumi Didi (and Mithu on the mango tree) greeting the children / saying goodbye, in the storytelling corner"""
    beats = []
    for k, ln in enumerate(lines):
        if k >= len(subs):
            break
        st, du, nar, tx = subs[k]
        b = {"who": "lumi_didi" if str(ln.get("speaker", "narrator")).lower().startswith("narrat") else "mithu",
             "say": str(ln.get("text", "")).strip() or tx, "at": st, "to": "mithu", "emotion": "happy"}
        if k < len(line_wavs) and line_wavs[k]:
            b["audio"] = line_wavs[k]
        beats.append(b)
        if k == 0:
            beats.append({"who": "lumi_didi", "gesture": "namaste", "sec": 1.8, "at": st, "background": True})
    end = max([s[0] + s[1] for s in subs] or [1.0])
    beats.append({"pause": max(0.3, dur - end), "at": end})
    return {"location": "village_courtyard", "world": {"hours": [[0, 10.5]], "wind": 0.4}, "fps": int(fps), "size": [int(W), int(H)],
            "subtitles": False, "t_start": 0.0,
            "cast": [{"id": "lumi_didi", "x": 1550, "name_bn": "লুমি দিদি"}, {"id": "mithu", "x": 1290, "z": 0.0}],
            "beats": beats}
