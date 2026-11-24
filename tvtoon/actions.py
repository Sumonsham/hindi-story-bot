"""THE STORY MOVES THE CHARACTERS (owner, 23 Nov 2026: "golpe jemon bolbe sei onujayi jeno obossoi movement hoi
character er" - whatever the story says, the character must do it).

Every line of the story (and its English helpers: the writer's "action", the storyboard's image prompt, the English
translation, the sound list) is read for what the body does, in Bengali, Hindi and English:

  walk in / come in / arrive        -> the character walks into the picture (from off screen the first time)
  go away / leave / go home         -> walks out of the picture (and walks back in when it speaks again)
  run / rush / run away / flee      -> runs (the run cycle), to the other one or out of the picture
  chase                             -> the chased one runs off, the chaser runs after it
  come closer / walk up to          -> walks up to the one it is talking to
  fly (birds)                       -> flies (a bird's fast move is flight)
  sit / stand up                    -> sits down on a seat that appears under it / gets up
  jump / play / dance / fall / bow  -> a real jump (squash, flight, landing), hops and swaying, a tumble, a pranam
  look back / turn round            -> looks back over the shoulder
  wave, namaste / pray, point, point up (sky), clap / shabash, laugh, cry, think / hmm, shrug / don't know,
  afraid / help!, angry / shout, bless / raise the hand, give / show, nod / yes, shake the head / no no
                                    -> that gesture and that face, while the line is spoken
  "sit down" / "come here" / "stand up" said TO someone -> that one sits / comes / stands

Speech is not narration: a character who SAYS "I will run" does not run - in spoken lines only gestures, faces and
orders to the listener count; movements come from narration and from the writer's own action notes.

Each found action is a beat at its time ("before" the line, "during" it, or "after" it); bot.py puts them on the
bot's own sound times, story.py in the scene's order."""
import re

from tvtoon import characters as CH

B = r"(?<![ঀ-৿ऀ-ॿA-Za-z])"

# (action, words). The order matters: the more exact phrase first.
CUES = [
    ("run_away", ["ran away", "run away", "runs away", "running away", "fled", "flee", "escaped", "bolted", "পালিয়ে", "পালাল",
                  "পালালো", "পালাতে", "ছুটে পালা", "भाग गया", "भाग गई", "भाग गए", "भाग निकल", "भाग खड़", "भाग जा"]),
    ("chase", ["chased", "chases", "chasing", "chase", "তাড়া কর", "তাড়া করল", "পিছু নিল", "পিছু ধাওয়া", "पीछा", "खदेड़"]),
    ("leave", ["went away", "goes away", "walked away", "walks away", "walked off", "walks off", "went off", "went out",
               "goes out", "went home", "left the", "leaves the", "left for", "departed", "চলে গেল", "চলে গেলেন", "চলে যায়",
               "চলে গেলো", "বেরিয়ে গেল", "বেরিয়ে গেলেন", "বেরিয়ে পড়ল", "ফিরে গেল", "ফিরে গেলেন", "বিদায় নিল", "বিদায় নিলেন",
               "चला गया", "चली गई", "चले गए", "निकल गया", "निकल गई", "निकल गए", "चल दिया", "चल दी", "चल दिए", "लौट गया",
               "लौट गई", "विदा ली"]),
    ("enter", ["came in", "comes in", "walked in", "walks in", "came into", "entered", "enters", "arrived", "arrives",
               "came to", "comes to", "appeared", "appears", "came out", "এল", "এলো", "এলেন", "এসে", "এসেছ", "ঢুকল", "ঢুকলেন",
               "ঢুকে", "হাজির", "উপস্থিত হল", "আসেন", "आया", "आई", "आए", "आ गया", "आ गई", "पहुँच", "पहुंच", "प्रवेश",
               "हाज़िर", "हाजिर"]),
    ("run", ["ran", "runs", "running", "rushed", "rushes", "dashed", "raced", "sprint", "hurried", "দৌড়", "ছুটে", "ছুটল",
             "ছুটলো", "ছুট", "दौड़", "भागा", "भागी", "भागते", "भागने"]),
    ("fly", ["flew", "flies", "flying", "fly", "উড়ে", "উড়ল", "উড়তে", "उड़", "उड़ते", "उड़ा"]),
    ("approach", ["steps closer", "stepped closer", "stepping closer", "moves closer", "leans closer", "leaned closer",
                  "came closer", "comes closer", "came near", "went up to", "goes up to", "walked up", "walks up",
                  "approached", "approaches", "moved closer", "stepped forward", "এগিয়ে এল", "এগিয়ে গেল", "এগিয়ে", "কাছে এল",
                  "কাছে গেল", "কাছে এসে", "पास आया", "पास आई", "पास गया", "पास गई", "पास आकर", "आगे बढ़"]),
    ("walk", ["walked", "walks", "walking", "strolled", "stepped", "হাঁট", "পায়চারি", "टहल", "चलते हुए", "चलने लगा",
              "चलने लगी"]),
    ("stand", ["stood up", "stands up", "got up", "gets up", "rose to", "উঠে দাঁড়া", "উঠে পড়", "দাঁড়িয়ে পড়", "খাড়া",
               "खड़ा हो", "खड़ी हो", "खड़े हो", "उठ खड़", "उठ कर", "उठकर"]),
    ("sit", ["sat", "sits", "sit down", "sitting", "seated", "বসল", "বসলেন", "বসলো", "বসে", "বসেন", "বসেছ", "बैठ"]),
    ("dance", ["danc", "নাচ", "নেচে", "নাচল", "नाच", "झूम"]),
    ("jump", ["jump", "leapt", "leaped", "leap", "hopped", "hops", "bounced", "played", "playing", "লাফ", "খেলা", "খেলছ",
              "খেলতে", "খেলল", "খেলে", "कूद", "उछल", "छलांग", "खेल"]),
    ("fall", ["fell", "falls down", "tripped", "slipped", "tumbled", "পড়ে গেল", "পড়ে গেলেন", "হোঁচট", "পিছলে", "गिर",
              "फिसल", "लड़खड़"]),
    ("hide", ["hid", "hide", "hiding", "লুকি", "লুকোল", "লুকাল", "छिप", "छुप"]),
    ("step_back", ["steps back", "stepped back", "stepping back", "backs away", "backed away", "backing away", "recoil",
                   "recoils", "recoiled", "shrinks back", "jumps back", "পিছিয়ে", "পিছু হট", "পিছনে সরে", "पीछे हट"]),
    ("grab", ["grabs", "grabbed", "grabbing", "clutches", "clutched", "seizes", "seized", "catches hold", "জাপটে", "চেপে ধর",
              "আঁকড়ে", "হাত ধরে", "हाथ पकड़", "पकड़ लिया", "जकड़"]),
    ("cover", ["covers his nose", "covers his mouth", "covers her mouth", "covers her nose", "covers his face",
               "covers her face", "covered his", "covered her", "handkerchief", "নাক চেপে", "মুখ চেপে", "মুখ ঢেকে",
               "नाक दबा", "मुँह दबा", "मुंह ढ"]),
    ("hold", ["holding a lantern", "holding his lantern", "holding the lantern", "holding her lantern", "holds the lantern",
              "holds his lantern", "holds torch", "holds the torch", "holds his torch", "holding a torch", "holding his torch",
              "holding the lamp", "holding a lamp", "holds the lamp", "holds up", "with a lantern", "with his lantern",
              "with a torch", "with a small lantern", "লণ্ঠন হাতে", "টর্চ হাতে", "হ্যারিকেন হাতে", "প্রদীপ হাতে",
              "लालटेन लिए", "टॉर्च लिए"]),
    ("look_back", ["looks around", "looked around", "looking around", "glances around", "glanced around", "peers", "peered",
                   "peering", "চারদিকে তাকা", "চারপাশে তাকা", "এদিক-ওদিক", "এদিক ওদিক", "इधर-उधर",
                   "looked back", "looks back", "look back", "turned around", "turned round", "turns around", "glanced back",
                   "পিছন ফিরে", "পেছন ফিরে", "ঘুরে তাকা", "ফিরে তাকা", "पीछे मुड़", "मुड़कर", "पलटकर", "पीछे देख"]),
    ("bow", ["bowed", "bows", "touched his feet", "touched her feet", "touched the feet", "প্রণাম কর", "মাথা নত", "পায়ে হাত",
             "চরণ", "चरण स्पर्श", "पैर छू", "सिर झुका", "प्रणाम किया"]),
    ("namaste", ["namaste", "namaskar", "folded hands", "folded his hands", "folded her hands", "joined hands", "prayed",
                 "praying", "pray", "pranam", "নমস্কার", "নমস্তে", "প্রণাম", "হাত জোড়", "প্রার্থনা", "পুজো", "পূজা",
                 "জয় শ্রী", "নমো", "नमस्ते", "नमस्कार", "प्रणाम", "हाथ जोड़", "प्रार्थना", "पूजा", "जय श्री", "हर हर महादेव"]),
    ("wave", ["waved", "waves", "wave", "goodbye", "bye", "hello", "called out", "calls out", "tata", "হাত নাড়", "টাটা",
              "ডাকল", "ডাকলেন", "ডাকছে", "হ্যালো", "हाथ हिला", "टाटा", "अलविदा", "पुकार", "आवाज़ दी", "आवाज दी", "हैलो"]),
    ("point_up", ["pointed up", "points up", "the sky", "looked up", "আকাশ", "উপরে", "ওপরে", "आसमान", "ऊपर"]),
    ("point", ["point", "pointing", "look there", "over there", "see that", "showed", "shows", "দেখাল",
               "দেখালেন", "আঙুল", "ওই দেখ", "ওই যে", "ওদিকে", "ওইখানে", "দেখো", "দ্যাখ", "इशारा", "देखो", "वो देखो",
               "वह देखो", "उधर", "दिखाया", "दिखाई"]),
    ("clap", ["clap", "applau", "bravo", "হাততালি", "তালি", "শাবাশ", "বাহ বাহ", "ताली", "शाबाश", "वाह वाह"]),
    ("laugh", ["laugh", "giggl", "chuckl", "ha ha", "haha", "hee hee", "হাসল", "হাসলেন", "হাসতে", "হাসছ", "হেসে", "হা হা",
               "হি হি", "হো হো", "हँस", "हंसने", "हंसते", "हंसी", "हंसा", "हा हा", "ही ही"]),
    ("cry", ["cried", "cries", "crying", "wept", "weep", "sobbed", "in tears", "কাঁদ", "কেঁদে", "কান্না", "চোখে জল", "रो पड़",
             "रोने", "रोते", "रोया", "रोई", "आँसू", "आंसू"]),
    ("scared", ["scream", "screams", "screamed", "shriek", "frozen", "froze", "horrified", "in horror", "trembling",
                "আর্তনাদ", "আঁতকে", "শিউরে", "afraid", "scared", "frightened", "terrified", "trembl", "shiver", "help!", "save me", "ভয়", "বাঁচাও", "কাঁপ",
                "डर", "बचाओ", "काँप", "कांप"]),
    ("angry", ["angry", "angrily", "shouted", "yelled", "furious", "scolded", "roared", "রেগে", "রাগ", "ধমক", "চেঁচিয়ে",
               "চিৎকার", "গর্জ", "गुस्से", "गुस्सा", "क्रोध", "चिल्ला", "डांट", "डाँट", "दहाड़", "गरज"]),
    ("surprised", ["surprised", "shocked", "amazed", "astonished", "what!", "অবাক", "চমকে", "আশ্চর্য", "ওমা", "হায় হায়",
                   "हैरान", "चौंक", "आश्चर्य", "अरे!"]),
    ("think", ["adjusts his spectacles", "adjusted his spectacles", "adjusts his glasses", "rubs his chin", "চশমা ঠিক",
               "thought", "thinks", "wondered", "thinking", "hmm", "let me think", "ভাবল", "ভাবলেন", "ভাবতে", "ভেবে",
               "ভাবছি", "চিন্তা", "হুম", "सोच", "विचार", "हम्म"]),
    ("shrug", ["shrugged", "shrugs", "don't know", "no idea", "জানি না", "কী জানি", "কে জানে", "पता नहीं",
               "मालूम नहीं", "कंधे उचका"]),
    ("bless", ["blessed", "blesses", "bless you", "raised his hand", "raised her hand", "আশীর্বাদ", "হাত তুল", "কল্যাণ হোক",
               "आशीर्वाद", "हाथ उठा", "सुखी रहो", "जीते रहो"]),
    ("give", ["gave", "gives", "handed", "offered", "gift", "দিল", "দিলেন", "দিলো", "উপহার", "তুলে দিল", "दिया", "दे दिया",
              "थमा", "भेंट", "तोहफ़ा", "तोहफा"]),
    ("eat", ["ate", "eats", "eating", "drank", "drinks", "gobbl", "খাচ্ছ", "খেয়ে", "খেলো", "খায়", "খেলেন", "খাওয়া",
             "खाया", "खाने", "खा रहा", "खा रही", "पिया"]),
    ("nod", ["nodded", "nods", "agreed", "yes", "okay", "মাথা নাড়", "মাথা নেড়ে", "সায় দিল", "হ্যাঁ", "ঠিক আছে",
             "सिर हिला", "हाँ", "हां", "ठीक है", "सहमत"]),
    ("shake", ["shook his head", "shook her head", "refused", "no no", "never!", "না না", "কক্ষনো না", "কখনো না", "নাহ",
               "नहीं नहीं", "कभी नहीं", "मना कर"]),
    ("proud", ["proudly", "boasted", "boast", "গর্ব", "অহংকার", "বড়াই", "घमंड", "गर्व", "शेखी"]),
]
# orders SPOKEN to the listener
ORDERS = [
    ("sit", ["sit down", "please sit", "take a seat", "বসো", "বসুন", "বস ", "বসে পড়ো", "बैठो", "बैठिए", "बैठ जाओ"]),
    ("approach", ["come here", "come closer", "এদিকে এসো", "কাছে এসো", "এদিকে আয়", "কাছে আয়", "এখানে এসো", "इधर आओ",
                  "यहाँ आओ", "पास आओ"]),
    ("stand", ["stand up", "get up", "উঠে দাঁড়াও", "ওঠো", "উঠে পড়ো", "खड़े हो जाओ", "उठो"]),
]
MOVES = {"run_away", "chase", "leave", "enter", "run", "fly", "approach", "walk", "stand", "sit", "hide", "step_back", "grab"}
ACTS = {"dance": "dance", "jump": "jump", "fall": "fall", "bow": "bow", "nod": "nod", "shake": "shake"}
GESTURE = {"namaste": "namaste", "wave": "wave", "point_up": "point_up", "point": "point", "clap": "clap",
           "laugh": "belly_laugh", "cry": None, "scared": "scared", "angry": "hips", "surprised": "raise_hand",
           "think": "think", "shrug": "shrug", "bless": "raise_hand", "give": "explain", "eat": "think", "proud": "hips",
           "bow": "namaste", "grab": "reach", "cover": "cover_mouth", "hold": "hold_lamp"}
EMOTION = {"laugh": "laughing", "cry": "crying", "scared": "scared", "angry": "angry", "surprised": "surprised",
           "dance": "happy", "jump": "happy", "clap": "happy", "fall": "surprised", "hide": "scared", "run_away": "scared", "step_back": "scared",
           "proud": "happy"}
NEG = re.compile(r"^.{0,10}?(না(?![ঀ-৿])|নেই|নি(?![ঀ-৿])|मत|नहीं|न |don't|do not|not |never|no need)", re.I)
NEG_BEFORE = re.compile(r"(don't|do not|not|never|no|मत|न)\s+\S*\s*$", re.I)
SAFE_IN_SPEECH = (set(GESTURE) | {"nod", "shake"}) - {"scared", "angry", "cry", "surprised"}   # (the line's own emotion says those)
ONLY_ONCE = {"enter"}
STEMS = {"danc", "trembl", "applau", "giggl", "chuckl", "gobbl", "shiver", "sprint", "jump", "clap", "laugh", "bless"}


def _w(w):
    """a word as a pattern: Bengali / Hindi from the start of a word (any ending); English as a whole word with
    its usual endings (so "ran" is not "range")"""
    if re.fullmatch(r"[a-z' ]+[a-z]", w):
        tail = r"[a-z]*" if w in STEMS else r"(?:s|es|ed|d|ing)?(?![a-z])"
        return B + re.escape(w) + tail
    return B + re.escape(w)


_RX = [(a, re.compile("|".join(_w(w) for w in sorted(ws, key=len, reverse=True)), re.I)) for a, ws in CUES]
_ORX = [(a, re.compile("|".join(_w(w) for w in ws), re.I)) for a, ws in ORDERS]
_HOSPITAL = re.compile(B + r"হাসপাতাল")


def cues(text, speech=False):
    """the actions a text names, in the order they are named: [(action, position)]"""
    text = str(text or "")
    if not text.strip():
        return []
    found, taken = [], []
    for act, rx in _RX:
        if speech and act not in SAFE_IN_SPEECH:
            continue
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue                                    # a longer, earlier cue already has these words
            if act in EMOTION and act not in ("dance", "jump", "clap") and (NEG.match(text[m.end():]) or NEG_BEFORE.search(text[:m.start()])):
                continue                                    # "don't be afraid", "ভয় নেই" - not a fearful face
            if act == "laugh" and _HOSPITAL.match(text, m.start()):
                continue
            taken.append((m.start(), m.end()))
            found.append((act, m.start()))
            break
    found.sort(key=lambda r: r[1])
    seen, out = set(), []
    for a, p in found:
        if a not in seen:
            seen.add(a)
            out.append((a, p))
    return out


def orders(text):
    """orders spoken to the listener ("sit down", "come here", "get out")"""
    return [a for a, rx in _ORX if rx.search(str(text or ""))]


class Director:
    """one scene (or one part of the bot's video): where everyone is, who sits, who has gone; turns the story's
    words into beats"""

    def __init__(self, cast_spec, names, fixed=(), still=False):
        for c in cast_spec:                                 # (an earlier director moved its entrance off screen)
            if "home_x" in c:
                c["x"] = c["home_x"]
        self.x = {c["id"]: float(c.get("x", 1600)) for c in cast_spec}
        self.home = dict(self.x)
        self.cast = {c["id"]: c for c in cast_spec}
        self.fixed = set(fixed)          # sitting in a vehicle / riding: gestures only
        self.still = still               # a scene where no one can walk about (a boat, a palki)
        self.sitting, self.gone, self.spoken, self.moved, self.entered = set(), set(), set(), set(), set()
        self.names = []                  # (regex, actor), longest names first
        for nm, actor in sorted(names.items(), key=lambda r: -len(r[0])):
            nm = str(nm).strip()
            if len(nm) >= 2 and actor in self.x:
                self.names.append((re.compile(B + re.escape(nm.lower()) + r"(?![a-z])", re.I), actor))
        self.log = []

    # -------------------------------------------------------------- helpers
    def animal(self, a):
        return bool(CH.get(a).get("animal"))

    def bird(self, a):
        sp = (CH.get(a).get("animal") or {}).get("species", "")
        return sp in ("crow", "parrot", "sparrow", "owl", "peacock")

    def partner(self, a, to=None):
        if to and to in self.x and to != a and to not in self.gone:
            return to
        others = [o for o in self.x if o != a and o not in self.gone]
        return min(others, key=lambda o: abs(self.x[o] - self.x[a])) if others else None

    def who_in(self, text):
        """the characters a sentence names, in the order named"""
        hits = []
        low = str(text or "").lower()
        for rx, actor in self.names:
            m = rx.search(low)
            if m and actor not in [h[1] for h in hits]:
                hits.append((m.start(), actor))
        hits.sort()
        return [a for _, a in hits]

    def _side_of(self, a):
        return -1.0 if self.home.get(a, 1600) < 1600 else 1.0

    # -------------------------------------------------------------- the moves
    def _walk(self, a, x1, gait="walk"):
        x1 = max(-1300.0, min(4500.0, x1))
        self.x[a] = x1
        self.moved.add(a)
        return {"who": a, "walk_to": round(x1), "gait": gait}

    def _move(self, a, act, other=None):
        """[(when, beat)] for one movement of actor a"""
        out = []
        if a in self.fixed or (self.still and act not in ("stand", "sit")):
            return out
        animal = self.animal(a)
        if act in ("sit", "stand") and animal:
            return out
        if act == "fly" and not self.bird(a):
            return out
        if a in self.sitting and act not in ("sit", "stand"):
            out.append(("before", {"who": a, "stand": True}))
            self.sitting.discard(a)
        o = other if other in self.x and other != a else self.partner(a)
        if a in self.gone and act in ("leave", "run_away", "hide"):
            return out                                      # it has gone already
        if a in self.gone:        # back into the picture first
            self.gone.discard(a)
            x = self.home[a] if o is None or abs(self.home[a] - self.x[o]) > 240 else self.x[o] - 320 * self._side_of(o)
            out.append(("before", dict(self._walk(a, x, "run" if act in ("run", "chase") else "walk"), enter=True)))
            if act in ("enter", "approach", "walk", "run"):
                return out
        if act == "enter":
            if a not in self.spoken and a not in self.moved and a not in self.entered:
                side = self._side_of(a)
                self.cast[a]["home_x"] = round(self.home[a])
                self.cast[a]["x"] = round(max(-1300, min(4500, self.home[a] + side * 1900)))  # off screen, then in
                self.entered.add(a)
                self.x[a] = self.cast[a]["x"]
                out.append(("before", self._walk(a, self.home[a])))
            elif o is not None and abs(self.x[a] - self.x[o]) > 420:
                out.append(("before", self._walk(a, self.x[o] - 320 * (1 if self.x[o] > self.x[a] else -1))))
        elif act in ("leave", "run_away", "hide"):
            away = (1.0 if o is None or self.x[a] >= self.x[o] else -1.0)
            if getattr(self, "_dir", None) is not None:      # "both ran off": the same way, together
                away = self._dir
            self._dir = away
            if act == "hide":
                out.append(("after", self._walk(a, self.x[a] + away * 520, "run")))
            else:
                out.append(("after", self._walk(a, self.x[a] + away * 2000, "run" if act == "run_away" else "walk")))
                self.gone.add(a)
        elif act == "chase":
            if o is not None:
                away = 1.0 if self.x[o] >= self.x[a] else -1.0
                if o not in self.fixed and not (o in self.sitting):
                    out.append(("before", self._walk(o, self.x[o] + away * 2000, "run")))
                    self.gone.add(o)
                out.append(("before", dict(self._walk(a, self.x[a] + away * 2200, "run"), delay=0.5)))
                self.gone.add(a)
        elif act in ("run", "fly"):
            if o is not None:
                d = self.x[o] - self.x[a]
                if abs(d) > 420:
                    out.append(("before", self._walk(a, self.x[o] - 300 * (1 if d > 0 else -1), "run")))
                else:                                       # already close: runs round to the other side
                    out.append(("before", self._walk(a, self.x[o] + 320 * (1 if d > 0 else -1), "run")))
            else:
                out.append(("before", self._walk(a, self.x[a] + (-1 if self.x[a] > 1600 else 1) * 900, "run")))
        elif act in ("approach", "walk"):
            if o is not None:
                d = self.x[o] - self.x[a]
                if abs(d) > 400:
                    out.append(("before", self._walk(a, self.x[o] - 300 * (1 if d > 0 else -1))))
                elif act == "walk":                         # a few steps (pacing about) and back
                    out.append(("before", self._walk(a, self.x[a] - 260 * (1 if d > 0 else -1))))
            else:
                out.append(("before", self._walk(a, self.x[a] + (1 if self.x[a] < 1600 else -1) * 420)))
        elif act == "step_back":                            # a quick step or two back, away from the other one
            away = 1.0 if o is None or self.x[a] >= self.x[o] else -1.0
            out.append(("during", self._walk(a, self.x[a] + away * 190, "walk")))
        elif act == "grab":                                 # goes right up to the other one (the hand: 'reach')
            if o is not None and abs(self.x[o] - self.x[a]) > 230:
                d = self.x[o] - self.x[a]
                out.append(("before", self._walk(a, self.x[o] - 200 * (1 if d > 0 else -1), "run")))
        elif act == "sit" and a not in self.sitting:
            out.append(("before", {"who": a, "sit": True}))
            self.sitting.add(a)
        elif act == "stand" and a in self.sitting:
            out.append(("before", {"who": a, "stand": True}))
            self.sitting.discard(a)
        return out

    # -------------------------------------------------------------- one line
    def prepare(self, lines, speaker_of):
        """read the scene once ahead: whoever COMES IN (before speaking) is not in the picture at the start - it
        waits off screen and walks (or runs) in when the story says so"""
        spoke = set()
        for ln in lines:
            sp = speaker_of(ln)
            plan = self.plan_of(ln, sp, None)
            for a, acts in plan.items():
                if a in self.x and a not in spoke and a not in self.fixed and not self.still and "enter" in acts \
                        and a not in self.gone:
                    self.gone.add(a)
                    self.entered.add(a)
                    side = self._side_of(a)
                    self.cast[a]["home_x"] = round(self.home[a])
                    self.cast[a]["x"] = round(max(-1300, min(4500, self.home[a] + side * 1900)))
                    self.x[a] = self.cast[a]["x"]
            if sp:
                spoke.add(sp)
        self.spoken = set()

    def plan_of(self, ln, speaker=None, to=None):
        """actor -> [actions] for one story line (and "_chase", "_orders")"""
        text = str(ln.get("text", "") or "")
        en = str(ln.get("en", "") or "")
        act_note = ln.get("action") or ""
        if isinstance(act_note, (list, tuple)):
            act_note = ", ".join(str(x) for x in act_note)
        pic = ln.get("image") if isinstance(ln.get("image"), dict) else {}
        prompt = str(pic.get("prompt", "") or (ln.get("image") if isinstance(ln.get("image"), str) else ""))
        sounds = " ".join(str(s.get("sound", "")) for s in (ln.get("sfx") or []) if isinstance(s, dict))
        plan = {}                                        # actor -> [actions]

        def add(a, acts):
            for x in acts:
                plan.setdefault(a, [])
                if x not in plan[a]:
                    plan[a].append(x)

        def attribute(src, default, speech):
            """split into clauses; each clause's actions go to the character it names (or the default one)"""
            for cl in re.split(r"[.;!?।]|,\s+(?:and|while|then|আর|তারপর|और|फिर)\s+|\s+(?:while|then|and then|তারপর|फिर)\s+", src):
                if not cl.strip():
                    continue
                who = self.who_in(cl) if not speech else []
                acts = [a for a, _ in cues(cl, speech=speech)]
                if not acts:
                    continue
                if who and any(a in ("chase",) for a in acts) and len(who) >= 2:
                    add(who[0], ["chase"])
                    plan.setdefault("_chase", who[1])
                    acts = [a for a in acts if a != "chase"]
                for w in (who or ([default] if default else [])):
                    if w is None:
                        continue
                    if re.search(r"(?:সবাই|সকলে|দুজনে|দু'জনে|দুজন|both|দুই বন্ধু|दोनों|everyone|all of them|सब|सभी)", cl, re.I) and not who:
                        for o in self.x:
                            if o not in self.gone:
                                add(o, acts)
                    else:
                        add(w, acts)
                if not who and not default and re.search(r"(?:সবাই|সকলে|দুজনে|দু'জনে|দুজন|both|দুই বন্ধু|दोनों|everyone|all of them|they|सब|सभी)", cl, re.I):
                    for o in self.x:
                        if o not in self.gone:
                            add(o, acts)

        people = [p for p in (pic.get("people") or []) if isinstance(p, dict)]

        def from_people():
            """the storyboard's own list: who is in the frame, their pose, what each one is doing"""
            for p in people:
                who = self.who_in(str(p.get("name", ""))) or ([speaker] if speaker and str(p.get("name", "")).lower() in
                                                             ("", "speaker") else [])
                if not who:
                    continue
                acts = [a for a, _ in cues(str(p.get("doing", "")))] + [a for a, _ in cues(str(p.get("pose", "")))]
                add(who[0], acts)

        def named_only(src):
            """a picture description: only what it says a NAMED character does (no guessing)"""
            for cl in re.split(r"[.;!?।]|,\s+", src):
                who = self.who_in(cl)
                if who:
                    add(who[0], [a for a, _ in cues(cl)])

        if speaker:
            attribute(text + " । " + en, speaker, speech=True)
            if act_note:
                attribute(act_note, speaker, speech=False)
            elif people:
                from_people()
            elif prompt:
                named_only(prompt)
            if "clap" in sounds.lower():
                add(speaker, ["clap"])
            if "laugh" in sounds.lower():
                add(speaker, ["laugh"])
            for o_act in orders(text + " " + en):
                lis = self.partner(speaker, to)
                if lis:
                    plan.setdefault("_orders", []).append((lis, o_act))
        else:
            attribute(text + " । " + en, None, speech=False)
            if act_note:
                attribute(act_note, None, speech=False)
            elif people and not plan:
                from_people()
            elif prompt and not plan:
                named_only(prompt)
        for a in list(plan):                            # "ran off" = run away; "walked out" = leave
            if a.startswith("_"):
                continue
            acts_ = plan[a]
            if "leave" in acts_ and ({"run", "fly"} & set(acts_)):
                plan[a] = ["run_away" if x == "leave" else x for x in acts_ if x not in ("run", "fly")]
            elif "run_away" in acts_:                    # "দৌড়ে পালাল" = one long run away, not a short run
                plan[a] = [x for x in acts_ if x not in ("walk", "approach", "enter", "run", "leave")]
            elif "leave" in acts_:
                plan[a] = [x for x in acts_ if x not in ("walk", "approach", "enter")]
            if "scared" in plan[a] and "angry" in plan[a]:   # "ভয়ে চিৎকার" is fear, not anger
                plan[a] = [x for x in plan[a] if x != "angry"]
        for a in list(plan):                            # the moves first, then the jumps / gestures / faces
            if not a.startswith("_"):
                plan[a].sort(key=lambda x: 0 if x in MOVES else 1)
        return plan

    def line(self, ln, speaker=None, to=None):
        """the beats a story line asks for: [(when, beat)], plus (gesture, emotion) for the speaker's say beat.
        speaker = the actor who speaks the line (None: narration)"""
        plan = self.plan_of(ln, speaker, to)
        self._dir = None
        out, gest, emo = [], None, None
        chase_target = plan.pop("_chase", None)
        orders_ = plan.pop("_orders", [])
        for a, acts in plan.items():
            if a not in self.x:
                continue
            moved, felt = False, False
            for x in acts:
                if x in MOVES:
                    if moved:
                        continue
                    bs = self._move(a, x, chase_target if x == "chase" else (to if a == speaker else None))
                    if bs:
                        moved = True
                        out += bs
                        self.log.append(f"{a}: {x}")
                elif x in ACTS and a not in self.fixed and not (x in ("jump", "dance", "fall") and (a in self.sitting or self.still)):
                    k = ACTS[x] if not (self.animal(a) and x == "bow") else "nod"
                    out.append(("during" if k in ("nod", "shake") else "before", {"who": a, "act": k}))
                    self.log.append(f"{a}: {x}")
                if x == "look_back" and a not in self.fixed:   # (was named but never acted before 24 Nov 2026)
                    out.append(("during", {"who": a, "look_back": 1.7}))
                    self.log.append(f"{a}: look_back")
                if x in GESTURE and GESTURE[x]:
                    if a == speaker:
                        gest = gest or GESTURE[x]
                    else:
                        out.append(("during", {"who": a, "gesture": GESTURE[x], "sec": 2.0}))
                    self.log.append(f"{a}: {x}")
                if x in EMOTION:
                    if a == speaker:
                        emo = emo or EMOTION[x]
                    elif not felt:
                        out.append(("during", {"who": a, "emotion": EMOTION[x], "sec": 2.4}))
                    felt = True
                    if x == "cry":
                        self.log.append(f"{a}: cry")
        for lis, o_act in orders_:                       # the listener does what it was told, after the line
            for when, b in self._move(lis, o_act):
                out.append(("after", b))
                self.log.append(f"{lis}: {o_act} (told)")
        if speaker:
            self.spoken.add(speaker)
            if speaker in self.gone:                     # it speaks: it comes back into the picture first
                out = self._move(speaker, "enter") + out
        return out, gest, emo


def name_map(cast, extra=None):
    """names in the story text -> actor: the story's own names, the names shown, the kids' aliases"""
    names = {}
    for story_name, v in (cast or {}).items():
        actor, shown = (v["actor"], v.get("shown")) if isinstance(v, dict) else (v[0], v[1])
        for n in (story_name, shown, CH.get(actor).get("name_bn"), CH.get(actor).get("name_en")):
            if n and str(n).lower() not in ("narrator",):
                names[str(n)] = actor
                first = str(n).split()[0]
                if len(first) >= 3 and first.lower() not in ("the", "raja", "rani", "mr", "mrs", "sri", "shri", "শ্রী", "श्री"):
                    names.setdefault(first, actor)
        try:
            from tvtoon import kids as K
            for w in K.ALIASES.get(actor, []):
                names.setdefault(w, actor)
        except Exception:
            pass
    names.update(extra or {})
    return names


def timed(items, st, du):
    """[(when, beat)] -> beats on the bot's sound times: before the line (a moment ahead), during it, after it"""
    out, nxt = [], {}
    for when, b in items:
        b = dict(b)
        delay = float(b.pop("delay", 0.0))
        who = b.get("who")
        if when == "before":
            at = max(0.0, st - (3.0 if b.pop("enter", False) else 0.5)) + nxt.get(who, 0.0)   # (walking in takes a while)
            nxt[who] = nxt.get(who, 0.0) + (1.0 if (b.get("stand") or b.get("sit")) else 0.4)
        elif when == "during":
            at = st + 0.15
        else:
            at = st + max(0.3, du)
        b["at"] = round(at + delay, 3)
        b["background"] = True
        b["from_story"] = True
        out.append(b)
    return out


def in_order(items, say_beat):
    """[(when, beat)] -> beats in the scene's order around the say / narrate beat (what a narration tells happens
    WHILE it is told)"""
    if "narrate" in say_beat:
        items = [("during" if w == "before" else w, b) for w, b in items]
    pre = [dict(b) for w, b in items if w == "before"]
    dur = [dict(b, with_prev=True) for w, b in items if w == "during"]
    post = [dict(b) for w, b in items if w == "after"]
    for b in pre + post + dur:
        b.pop("delay", None)
        b.pop("enter", None)
        b["from_story"] = True
    return pre + [say_beat] + dur + post
