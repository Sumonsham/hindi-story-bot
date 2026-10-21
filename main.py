#!/usr/bin/env python3
"""
Cartoon Story Bot (Hindi + Bengali, alternating)
-----------------------
Every run makes ONE brand-new, original Hindi or Bengali kids' cartoon story video and posts it to
a Facebook Page:

  1. Google Gemini          -> story with dialogue, title, description, hashtags
  2. Cloudflare Workers AI  -> cartoon pictures, a new picture for every line, same characters
  3. Microsoft Edge voices  -> sweet narrator + a different voice for every character (gTTS backup)
  4. Sound engine           -> real sound effects from freesound.org (CC0) timed to the story,
                               nature ambience and soft cheerful music
  5. FFmpeg + OpenCV        -> moving picture layers, close-ups, subtitles
  6. Facebook Graph API

Secrets: GEMINI_API_KEY, CF_ACCOUNT_ID, CF_API_TOKEN, FB_PAGE_ID, FB_PAGE_TOKEN
Optional: PAGE_NAME, FREESOUND_API_KEY, MAX_IMAGES, DRY_RUN=1, MOCK=1
"""
import asyncio
import base64
import datetime as dt
import glob
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import wave

import requests
import extras
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ----------------------------------------------------------------- settings
W, H, FPS, SR = 1280, 720, 25, 44100
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
HISTORY = os.path.join(HERE, "history.json")
SFX_DIR = os.path.join(HERE, "sfx")          # optional: your own sounds, e.g. sfx/rain.mp3

MOCK = os.getenv("MOCK") == "1"
DRY_RUN = MOCK or os.getenv("DRY_RUN") == "1"

LANGS = {
    "hi": {
        "name": "Hindi", "script": "Devanagari",
        "font_family": "Noto Sans Devanagari", "font_glob": "NotoSansDevanagari",
        "male": ["hi-IN-MadhurNeural"], "female": ["hi-IN-SwaraNeural"],
        "narrator": ("hi-IN-SwaraNeural", "-4%", "+2Hz"), "gtts": "hi",
        "intro": "नमस्ते प्यारे बच्चों! मैं हूँ आपकी लूमी दीदी। आज की कहानी है... {title}।",
        "outro": "कहानी अच्छी लगी तो लाइक कीजिए, शेयर कीजिए, और ऐसी ही प्यारी कहानियों के लिए {page} को फॉलो ज़रूर कीजिए!",
        "page_default": "हमारे पेज",
        "ai_note": "🎨 यह कहानी और तस्वीरें AI की मदद से बनाई गई हैं।",
        "moral_intro": "तो बच्चों, इस कहानी से हमें यह सीख मिलती है:",
        "labels": {"moral": "नैतिक कहानी", "animal": "जानवरों की कहानी", "funny": "मज़ेदार कहानी",
                   "folk": "दादी माँ की कहानी", "panchatantra": "पंचतंत्र की कहानी", "life": "जीवन की सीख",
                   "witty": "चतुराई की कहानी", "fairy": "परी की कहानी", "adventure": "साहसिक कहानी",
                   "festival": "त्योहार की कहानी", "bedtime": "सोने से पहले की कहानी", "school": "स्कूल की कहानी",
                   "nature": "प्रकृति की कहानी", "divine": "भगवान की लीला"},
        "example_tags": "#HindiKahani #MoralStories #CartoonStory",
        "badge": "लाइक • शेयर • फॉलो", "ch_intro": "शुरुआत", "ch_end": "सीख", "chapters": "⏱️ अध्याय",
        "cta": "पूरी कहानी हमारे पेज पर 👉", "playlist_tail": "Hindi Kids Stories", "full_link": "पूरी कहानी देखें:",
        "quiz_title": "क्विज़ टाइम!", "quiz_labels": ["क", "ख", "ग"],
        "quiz_intro": "अब एक छोटा सा सवाल, बच्चों!", "quiz_count": "सोचो... तीन... दो... एक...",
        "quiz_answer": "सही जवाब है... {lab}: {ans}! क्या तुमने सही बताया? कमेंट में लिखो!",
        "ann1": "नई प्यारी कहानी", "ann_msg": "🧸 {when} आ रही है लूमी दीदी की नई कहानी! बच्चों को ज़रूर दिखाइए 🔔",
        "comp_title": "{m} मिनट की प्यारी कहानियाँ 🧸 | हफ्ते की {n} कहानियाँ एक साथ", "comp_thumb": "{m} मिनट की कहानियाँ",
        "how_to_join": "बच्चों, क्विज़ का जवाब कमेंट में लिखो, जैसे क, ख या ग। जिनका जवाब सही होगा, उनका नाम अगली कहानी में लूमी दीदी बोलेगी! और रंग भरा हुआ चित्र कमेंट में भेजना मत भूलना।",
        "shout_line": "पिछली कहानी के क्विज़ का सही जवाब दिया था {names} ने। शाबाश! तालियाँ!",
        "join_comment": "👇 कैसे हिस्सा लें:\n✅ क्विज़ का जवाब कमेंट में लिखिए (क / ख / ग) - सही जवाब देने वालों का नाम अगली कहानी में!\n🖍️ रंग भरा चित्र फोटो खींचकर कमेंट में भेजिए\n🔔 फॉलो कीजिए ताकि रोज़ की कहानी मिस न हो",
        "shout_comment": "🏆 पिछली कहानी के क्विज़ के सही जवाब: {names} - शाबाश!",
        "congrats_reply": "🏆 शाबाश! आपका जवाब सही था, आज की कहानी में लूमी दीदी ने आपका नाम लिया है 👉 {link}",
        "words_title": "आज के 3 अंग्रेज़ी शब्द", "words_line": "अब सीखते हैं आज की कहानी के तीन अंग्रेज़ी शब्द! {items}",
        "word_item": "{en} मतलब {m}।", "color_title": "रंग भरो!",
        "color_msg": "🖍️ आज का रंग भरने वाला पन्ना! प्रिंट कीजिए, बच्चों से रंग भरवाइए और फोटो कमेंट में भेजिए 🌈 सबसे सुंदर चित्र अगली कहानी में दिखाएँगे!",
    },
    "bn": {
        "name": "Bengali", "script": "Bengali",
        "font_family": "Noto Sans Bengali", "font_glob": "NotoSansBengali",
        "male": ["bn-IN-BashkarNeural", "bn-BD-PradeepNeural"],
        "female": ["bn-BD-NabanitaNeural", "bn-IN-TanishaaNeural"],
        "narrator": ("bn-IN-TanishaaNeural", "-4%", "+2Hz"), "gtts": "bn",
        "intro": "নমস্কার ছোট্ট বন্ধুরা! আমি তোমাদের লুমি দিদি। আজকের গল্প... {title}।",
        "outro": "গল্পটা ভালো লাগলে লাইক করুন, শেয়ার করুন, আর এমন আরও মিষ্টি গল্পের জন্য {page} ফলো করতে ভুলবেন না!",
        "page_default": "আমাদের পেজ",
        "ai_note": "🎨 এই গল্প ও ছবি AI-এর সাহায্যে তৈরি।",
        "moral_intro": "তাহলে ছোট্ট বন্ধুরা, এই গল্প থেকে আমরা শিখলাম:",
        "labels": {"moral": "নীতিকথার গল্প", "animal": "পশুপাখির গল্প", "funny": "মজার গল্প",
                   "folk": "ঠাকুমার ঝুলি", "panchatantra": "পঞ্চতন্ত্রের গল্প", "life": "জীবনের শিক্ষা",
                   "witty": "বুদ্ধির গল্প", "fairy": "পরীর গল্প", "adventure": "অ্যাডভেঞ্চারের গল্প",
                   "festival": "উৎসবের গল্প", "bedtime": "ঘুমপাড়ানি গল্প", "school": "স্কুলের গল্প",
                   "nature": "প্রকৃতির গল্প", "divine": "ঠাকুরের লীলা"},
        "example_tags": "#বাংলাগল্প #RupkotharGolpo #CartoonStory",
        "badge": "লাইক • শেয়ার • ফলো", "ch_intro": "শুরু", "ch_end": "শিক্ষা", "chapters": "⏱️ অধ্যায়",
        "cta": "পুরো গল্প আমাদের পেজে 👉", "playlist_tail": "Bangla Kids Stories", "full_link": "পুরো গল্প দেখুন:",
        "quiz_title": "কুইজ টাইম!", "quiz_labels": ["ক", "খ", "গ"],
        "quiz_intro": "এবার একটা ছোট্ট প্রশ্ন, বন্ধুরা!", "quiz_count": "ভাবো... তিন... দুই... এক...",
        "quiz_answer": "ঠিক উত্তর হলো... {lab}: {ans}! তুমি কি ঠিক বলেছিলে? কমেন্টে লেখো!",
        "ann1": "নতুন মিষ্টি গল্প", "ann_msg": "🧸 {when} আসছে লুমি দিদির নতুন গল্প! ছোটদের দেখাতে ভুলবেন না 🔔",
        "comp_title": "{m} মিনিটের মিষ্টি গল্প 🧸 | সপ্তাহের {n}টি গল্প একসাথে", "comp_thumb": "{m} মিনিটের গল্প",
        "how_to_join": "বন্ধুরা, কুইজের উত্তর কমেন্টে লেখো, যেমন ক, খ বা গ। যাদের উত্তর ঠিক হবে, পরের গল্পে লুমি দিদি তাদের নাম বলবে! আর রং করা ছবি কমেন্টে পাঠাতে ভুলো না।",
        "shout_line": "আগের গল্পের কুইজে ঠিক উত্তর দিয়েছিল {names}। দারুণ! হাততালি!",
        "join_comment": "👇 কীভাবে অংশ নেবেন:\n✅ কুইজের উত্তর কমেন্টে লিখুন (ক / খ / গ) - ঠিক উত্তরদাতাদের নাম পরের গল্পে!\n🖍️ রং করা ছবি তুলে কমেন্টে পাঠান\n🔔 ফলো করুন, রোজের গল্প যেন মিস না হয়",
        "shout_comment": "🏆 আগের গল্পের কুইজে ঠিক উত্তর: {names} - দারুণ!",
        "congrats_reply": "🏆 দারুণ! তোমার উত্তর ঠিক ছিল, আজকের গল্পে লুমি দিদি তোমার নাম বলেছে 👉 {link}",
        "words_title": "আজকের ৩টে ইংরেজি শব্দ", "words_line": "এবার শিখি আজকের গল্পের তিনটে ইংরেজি শব্দ! {items}",
        "word_item": "{en} মানে {m}।", "color_title": "রং করো!",
        "color_msg": "🖍️ আজকের রং করার পাতা! প্রিন্ট করুন, ছোটদের দিয়ে রং করান আর ছবি তুলে কমেন্টে দিন 🌈",
    },
}

CATEGORIES = {
    # devotional stories of the gods and their devotees (Puranas, bhakti legends - ancient, public domain)
    "divine": ["little Krishna the butter thief (Makhan Chor) and Mother Yashoda",
               "Yashoda sees the whole universe in baby Krishna's mouth", "Krishna lifts Govardhan hill to save Vrindavan",
               "Krishna and his poor friend Sudama's handful of rice", "Krishna calms the serpent Kaliya in the Yamuna",
               "Meera Bai's love for Krishna", "Lord Shiva becomes Neelkanth to save the world from poison",
               "Shiva protects the child devotee Markandeya", "the hunter Kannappa's devotion to Shiva",
               "Shiva brings the river Ganga down to earth", "Ma Kali comes as a little girl to help Ramprasad mend his fence",
               "Sri Ramakrishna and Ma Kali at Dakshineswar", "Lord Jagannath eats Karma Bai's morning khichdi",
               "the devotee Salabega and Lord Jagannath's chariot", "King Indradyumna and the making of Jagannath",
               "Ganesha goes around his parents to win the race", "Ganesha and Kubera's grand feast",
               "Ganesha writes the Mahabharata with his broken tusk", "baby Hanuman tries to eat the sun",
               "Hanuman carries the Sanjeevani mountain", "Shabari's sweet berries for Lord Rama",
               "the little squirrel who helped build Rama's bridge", "young Prahlad's faith in Lord Vishnu",
               "child Dhruva's prayer becomes the pole star", "Ma Durga comes home for Durga Puja",
               "Ma Lakshmi visits the house that stays awake on Kojagari Purnima",
               "Ma Saraswati blesses a poor student", "Behula's devotion and Ma Manasa",
               "Chaitanya Mahaprabhu's kirtan in Nabadwip", "Lord Vishnu as Vamana and King Bali"],
    # clever-wit folk anecdotes (centuries-old, public domain) - retold in our own words
    "witty": ["Gopal Bhar and the king's impossible challenge", "Gopal Bhar outsmarts a greedy moneylender",
              "Birbal and the emperor's tricky question", "Birbal finds the real thief with sticks",
              "Tenali Raman and the boastful scholar", "Tenali Raman saves the royal garden",
              "a clever village girl solves the minister's riddle", "the wise judge and two mothers"],
    "fairy": ["a little fairy who lost her wings", "the fairy of the lotus pond grants three wishes",
              "a magic paintbrush that makes drawings real", "the moon fairy visits a poor girl",
              "a rainbow bridge to the land of clouds", "the star that fell into a village garden",
              "a talking tree that grants wishes only to kind children", "the fairy queen's lost crown"],
    "adventure": ["two friends find a secret cave map", "a brave girl crosses the river to bring medicine",
                  "the lost elephant calf and the search party", "a kite that flies to a strange island",
                  "the treasure hidden under the old banyan tree", "a little boat's journey down the Ganga",
                  "lost in the Sundarbans with a friendly tiger cub", "the mountain goat who climbed the highest peak"],
    "festival": ["Durga Puja and the little drummer boy", "a Diwali lamp for the lonely grandmother",
                 "Holi colours and a sad friend", "Eid sweets shared with the whole street",
                 "Christmas gift for the poor shoeshine boy", "Raksha Bandhan and the brother far away",
                 "Poila Baishakh new year at the village fair", "Makar Sankranti kite festival friendship"],
    "bedtime": ["a sleepy little owl who could not sleep at night", "the moon tells a story to a child",
                "a teddy bear's night adventure", "the cloud that wanted to be a pillow",
                "counting stars with grandfather", "the lullaby of the river"],
    "school": ["the new student who could not speak the language", "a lost tiffin box mystery",
               "the class monitor learns fairness", "a sports day race where helping wins",
               "a homework copied and the honest confession", "the school garden project"],
    "nature": ["the last tree in the city", "a sparrow family and the plastic bag", "the river that got sick",
               "saving rainwater in the village", "a bee teaches why flowers matter", "the honest woodcutter and the forest"],
    # old Bengali/Indian fairy tales (Thakurmar Jhuli style - public domain folk tales, retold in our own words)
    "folk": ["a brave prince and the demon (rakkhosh) kingdom", "Lalkamal and Neelkamal, two brother princes",
             "the magic birds Byangoma and Byangomi who give advice", "the flying horse Pakkhiraj",
             "seven brothers turned into champa flowers and their sister", "Kiranmala, the brave princess",
             "a poor farmer's son and the sleeping princess", "a magic golden stick and silver stick",
             "the clever youngest daughter-in-law", "a kind girl and the witch of the forest",
             "the king's lost ring and the honest fisherman", "a talking golden fish in the village pond",
             "the giant's garden and the little shepherd", "a magic pitcher that never empties"],
    # Panchatantra / Jataka / Hitopadesha fables (ancient, public domain, retold in our own words)
    "panchatantra": ["the monkey and the crocodile", "the clever rabbit and the proud lion",
                     "the blue jackal", "the talkative tortoise and the two geese", "the crows and the cobra",
                     "the brahmin and the three thieves", "the mice that saved the elephants",
                     "the lion, the mouse and the net", "the foolish lion and the jackal's cave",
                     "the four friends: deer, crow, mouse and tortoise", "the heron and the crab",
                     "the monkey king who saved his tribe (Jataka)", "the golden swan (Jataka)",
                     "the loyal mongoose", "the greedy cat who judged two birds"],
    # everyday stories about people that teach a life lesson
    "life": ["a boy who wasted food learns where rice comes from", "a girl who helps a lonely old neighbour",
             "the honest rickshaw puller who returns a lost bag", "a child too busy with the mobile phone",
             "respecting the school teacher", "a piggy bank and the value of saving money",
             "a rich boy and a poor boy become best friends", "telling the truth to mother after breaking a vase",
             "keeping the village clean", "sharing lunch with a new classmate",
             "a father's quiet sacrifice", "a grandmother's lesson about patience",
             "a boy who made fun of others learns kindness", "never giving up after failing an exam",
             "thanking the farmer, the postman and the sweeper"],
    "moral": ["honesty", "greed and its result", "kindness to others", "hard work", "true friendship", "patience",
              "sharing", "respecting elders", "telling lies", "helping the weak", "pride and humility",
              "saving water", "obeying parents", "courage", "gratitude"],
    "animal": ["jungle animals", "a clever fox", "a brave little rabbit", "an elephant family", "birds in a big tree",
               "a lazy lion", "a monkey and a crocodile", "farm animals", "a thirsty crow", "ants and a grasshopper",
               "a peacock and a crow", "sea creatures", "a lost puppy", "a wise owl"],
    "funny": ["a forgetful village man", "a silly king and a clever minister", "a greedy shopkeeper tricked",
              "a lazy servant", "a talking parrot", "a funny school day", "a mix-up at a wedding", "a clumsy thief",
              "a boastful wrestler", "a naughty goat", "a magical cooking pot gone wrong"],
}

SOUND_TAGS = ["wind", "rain", "thunder", "crickets", "birds", "water", "footsteps", "creak", "knock",
              "boing", "whoosh", "pop", "bell", "splash"]
MOODS = ["happy", "calm", "funny", "adventure", "sad"]
EMOTIONS = ["normal", "happy", "excited", "laughing", "sad", "crying", "scared", "angry", "whisper", "calm", "proud"]

ART_STYLE = ("high quality 2D cartoon animation still for kids, Indian storybook world, bright cheerful colors, "
             "soft lighting, clean outlines, cute expressive characters with big eyes, Pixar-like charm, "
             "no text, no letters, no watermark")


def log(*a):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)
    msg = " ".join(str(x) for x in a)
    if any(k in msg for k in ("skipped", "FAILED", "STOPPED", "failed")):
        extras.note_issue(msg.strip())


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd[:3])}...\n{r.stderr[-2000:]}")
    return r.stdout


def env(name):
    return (os.getenv(name) or "").strip()


def need_env(name):
    v = env(name)
    if not v:
        sys.exit(f"ERROR: secret {name} is missing. Add it in GitHub > Settings > Secrets > Actions.")
    return v


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", path]).strip())


def ascii_text(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\x20-\x7E]", " ", str(s))).strip()


# ----------------------------------------------------------------- history
def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# cron-job.org starts each video about 1 hour before it should be online (India time):
# (start hour, start minute, the hour the video should be out)
TRIGGERS = [(6, 55, 8), (11, 55, 13), (17, 55, 19)]
SLOT = None


def recently_posted(history, hours):
    """True if a video was posted in the last few hours (so a backup run must not post a second one)."""
    for h in history[-3:]:
        if h.get("kind") == "compilation":
            continue
        try:
            t = dt.datetime.fromisoformat(str(h.get("date", "")))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
            if dt.datetime.now(dt.timezone.utc) - t < dt.timedelta(hours=hours):
                return True
        except Exception:
            pass
    return False


def save_history(items):
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(items[-200:], f, ensure_ascii=False, indent=1)


def pick_language(history):
    """One video Hindi, the next Bengali, and so on."""
    forced = env("LANGUAGE").lower()
    if forced in LANGS:
        return forced
    last = history[-1].get("lang", "hi") if history else "bn"
    return "bn" if last == "hi" else "hi"


DIVINE_FESTIVALS = {"Durga Puja", "Kojagari Lakshmi Puja", "Kali Puja / Diwali", "Saraswati Puja", "Maha Shivaratri",
                    "Sri Ramakrishna's birthday", "Holi / Dol Purnima", "Ram Navami", "Bhoot Chaturdashi"}
MASCOT = os.path.join(HERE, "assets", "lumi_mithu.jpg")
MASCOT_PROMPT = ("Lumi Didi, a warm friendly young Indian storyteller woman in high quality 2D cartoon style, big kind "
                 "sparkling eyes, gentle smile, long black braid with a small yellow flower, sky-blue saree with a "
                 "golden border, small star-shaped bindi, holding an open glowing storybook in one hand and waving "
                 "hello with the other, a small cheeky bright-green parrot with a red beak (Mithu) sitting on her "
                 "shoulder, sitting on a cozy colorful cushion, soft magical sparkles, bright cheerful "
                 "storybook background, Pixar-like charm, no text, no letters, no watermark")


MITHU = {"name": "Mithu", "gender": "male", "age": "child", "kind": "animal", "host": True,
         "look": "a small cheeky bright-green parrot with a red beak and a tiny yellow cap"}


def ensure_mascot():
    """Our host 'Lumi Didi' - made once, saved in the repo, the same in every video."""
    if os.path.exists(MASCOT):
        return MASCOT
    if MOCK:
        os.makedirs(os.path.dirname(MASCOT), exist_ok=True)
        return mock_image(MASCOT, 7) and MASCOT
    try:
        os.makedirs(os.path.dirname(MASCOT), exist_ok=True)
        save_picture(cf_request(CF_MODEL, MASCOT_PROMPT, seed=2024), MASCOT)
        log("Lumi Didi picture created (saved for all future videos)")
        return MASCOT
    except Exception as e:
        log("  Lumi Didi picture not made now:", str(e)[:150])
        return None


def pick_theme(history):
    """Rotate story types so posts in a day are usually different kinds."""
    recent = [h.get("category") for h in history[-2:]]
    options = [c for c in CATEGORIES if c not in recent] or list(CATEGORIES)
    cat = extras.weighted_choice(options, extras.weights(history, "category", options))
    return cat, random.choice(CATEGORIES[cat])


# ----------------------------------------------------------------- 1. story (Gemini)
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def gemini_models(key):
    tries = [env("GEMINI_MODEL")] if env("GEMINI_MODEL") else []
    tries.append("gemini-flash-latest")
    try:
        r = requests.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": key},
                         params={"pageSize": 200}, timeout=30)
        names = []
        for m in r.json().get("models", []):
            n = m.get("name", "").replace("models/", "")
            if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n
                    and not any(x in n for x in ("image", "tts", "audio", "live", "embed", "exp"))):
                names.append(n)

        def ver(n):
            nums = re.findall(r"\d+(?:\.\d+)?", n)
            return (float(nums[0]) if nums else 0, "lite" not in n, "preview" not in n)
        tries += sorted(names, key=ver, reverse=True)
    except Exception as e:
        log("Could not list Gemini models:", e)
    tries += ["gemini-2.5-flash"]
    out = []
    for t in tries:
        if t and t not in out:
            out.append(t)
    return out


def make_story(lang, theme, history, extra_rules=""):
    if MOCK:
        return mock_story(lang)
    key = need_env("GEMINI_API_KEY")
    category, idea = theme
    L = LANGS[lang]
    old_titles = [h["title"] for h in history[-60:] if h.get("lang", "hi") == lang]
    kind_rules = {
        "folk": "This is a classic Indian/Bengali fairy tale in the style of Thakurmar Jhuli (grandmother's tales): "
                "kings, princes, princesses, rakkhosh/demons, magic birds, flying horses, a village and a palace. "
                "Retell the public-domain folk tale idea in your OWN words with new dialogue, vivid scenes and a "
                "small fresh twist. Keep the magic gentle and child friendly (the demon is defeated by cleverness, "
                "not violence).",
        "panchatantra": "This is a Panchatantra / Jataka / Hitopadesha fable (ancient, public domain). Retell it in "
                        "your OWN words with lively new dialogue, fun character voices and a fresh small twist, "
                        "keeping the classic lesson.",
        "divine": "This is a devotional story (leela) of the gods and their devotees from the Puranas and bhakti "
                  "tradition. Tell it faithfully and with deep respect and devotion - do NOT change the meaning of "
                  "the traditional story or add silly jokes about the gods. Warm, loving, child friendly; show the "
                  "god's love for the devotee and end with the devotional lesson (faith, love, humility, kindness). "
                  "If the original has fights or demons, tell those parts gently, without violence or fear. "
                  "In every picture and character 'look', show the gods in their traditional, beautiful, auspicious "
                  "form (e.g. Krishna: blue skin, peacock feather, yellow dhoti, flute; Shiva: calm, blue throat, "
                  "crescent moon, Ganga in his hair; Ma Kali: gentle loving mother form, no weapons, no heads; "
                  "Jagannath: the traditional big round eyes and dark face) with a soft divine golden glow.",
        "life": "This is a heart-touching everyday story about real people (children, parents, grandparents, "
                "teachers, neighbours) in an Indian town or village. Realistic situations families relate to. "
                "It must teach a clear life lesson and gently touch the heart.",
    }.get(category, "Do NOT retell famous copyrighted stories or use known cartoon characters. Invent new names.")
    prompt = f"""
You are India's best {L['name']} children's storyteller, writing for a cartoon story video page.
Write ONE {L['name']} story ({L['script']} script, simple sweet everyday {L['name']} that kids and
families understand). Type: {category} story. Theme: {idea}.
{kind_rules}{extra_rules}
Never use modern copyrighted characters (no Disney, Chhota Bheem, Motu Patlu etc.).
Must be different from these earlier stories: {json.dumps(old_titles, ensure_ascii=False)}
Our channel host is "Lumi Didi", a warm storyteller; the narrator speaks like her (friendly, to the children).

Story rules:
- LENGTH: 14 to 18 scenes, 5-6 minutes when spoken - at least 750 spoken words in total. Never rush the
  ending; the story must feel complete. The FIRST line must hook in 5 seconds (a surprise, a question
  or a funny moment). Then a problem, rising curiosity, a twist, and a happy, funny or touching ending.
- Make it emotional and memorable so families want to share it: cute humour, a warm heart, a clear lesson.
- Warm and cheerful, suitable for small children. No violence, nothing scary.
- 2 to 4 characters (people or animals) plus a narrator, with real, lively dialogue between characters.
- Each scene has 4 to 7 lines. The narrator describes; characters speak only their own words.
  Narrator lines 20-45 words, dialogue lines 4-20 words.
- Think like a cartoon film director: every line gets its own PICTURE that shows exactly what that line says
  (who, doing what, where). The picture must match the words - if the line says the crow drops a stone in the
  pot, the picture shows the crow dropping a stone in the pot.
- SOUND DESIGN like a children's audio drama: when a line mentions an action or a thing that makes a sound
  (door, footsteps, birds, splash, laughing, a bell, wind, an elephant trumpeting, a cuckoo, clapping),
  put that real sound in the line's "sfx" with the right timing. 0-2 sfx per line, only real story events.
- Give every line an emotion so the voice acts it.
{extras.STORY_CRAFT}{extras.WRITING_RULES.get(lang, "")}{extras.VOICE_ACTING}
Return ONLY JSON with exactly these keys:
{{
 "title": "catchy {L['name']} title (max 60 characters) with 1 emoji",
 "thumbnail_text": "2-4 BIG {L['name']} words that make people curious to click (a question or surprise, e.g. 'लालच का फल?', 'বোকা সিংহ!')",
 "description": "3-4 line engaging {L['name']} description, ending with a question to the viewer",
 "hashtags": ["10 to 14 popular hashtags mixing {L['name']} and English, e.g. {L['example_tags']}"],
 "setting": "ENGLISH: the ONE main place of the story (landscape, buildings, plants, colors, time of day). Reused in every picture",
 "characters": [{{"name": "name in English letters", "gender": "male or female",
                  "age": "child, young, adult or old", "kind": "human or animal",
                  "look": "ENGLISH, very specific never-changing look: species/age, body size, exact colors of fur/skin/hair, clothes with exact colors, one special accessory. 20-35 words"}}],
 "source": "ENGLISH: e.g. 'Inspired by Panchatantra' / 'Inspired by Thakurmar Jhuli' / 'From the Bhagavata Purana' / 'Original story'",
 "thumbnail_image": {{"characters": ["1-2 main names"], "action": "ENGLISH: the most surprising or emotional moment of the story, the main character with a BIG expressive face (shocked, laughing, crying) close to the camera"}},
 "scenes": [{{
    "characters": ["names VISIBLE in the picture"],
    "action": "ENGLISH: what happens in this scene",
    "place": "ENGLISH: where in the setting + light",
    "mood": "one of {MOODS}",
    "ambience": ["1-2 ENGLISH background sounds that fit this place, e.g. 'birds chirping in forest', 'village morning roosters', 'river stream', 'gentle wind in trees', 'busy village market'"],
    "lines": [{{"speaker": "narrator or a character name", "text": "{L['name']} text",
                "en": "the same line translated to natural English (for subtitles)",
                "emotion": "one of {EMOTIONS}",
                "delivery": "ENGLISH acting direction for the voice (pitch, speed, loudness, feeling)",
                "voice_text": "same words as text, with 0-2 sound tags like <giggle> or <gasp> where they fit",
                "sfx": [{{"sound": "ENGLISH short name of what HAPPENS in this line, e.g. 'wooden door opens', 'small footsteps running on grass', 'water splash', 'children laughing', 'elephant trumpet', 'crow cawing', 'clapping'",
                          "when": "before (sound first, then the line), during, or after (line first, then the sound)"}}],
                "image": {{"prompt": "ENGLISH picture prompt for THIS line, 30-50 words, like a cartoon film still: WHO is in frame and their exact action, pose and facial expression matching the words of this line, WHERE (which part of the setting), camera (close-up / medium / wide / low angle), light, important objects. Only things that can be SEEN",
                           "characters": ["names VISIBLE in this picture; [] if only a place or object is shown"]}}}}]
 }}],
 "moral": "one short {L['name']} line: the lesson (or the punchline for funny stories)",
 "ending_line": "one short sweet {L['name']} closing line from the narrator",
 "comment_question": "one short friendly {L['name']} question to viewers that makes them comment (e.g. 'तुम होते तो क्या करते?'), with 1 emoji",
 "teaser_scene": "number: the scene (1 = first) where the most fun/exciting 50 seconds START - used for the Reel/Short teaser",
 "mithu_intro": "Mithu the cheeky parrot (Lumi Didi's friend) says ONE short funny {L['name']} line at the start, about today's story (max 15 words)",
 "mithu_outro": "Mithu's ONE short funny {L['name']} goodbye line (max 15 words)",
 "english_words": [{{"en": "3 simple English words from this story (e.g. Crow, Water, Stone)", "meaning": "meaning in {L['name']}"}}],
 "quiz": {{"question": "one easy {L['name']} question for children about THIS story (max 12 words)",
           "options": ["3 short {L['name']} answers (2-4 words each), only one correct"], "answer": "0, 1 or 2: index of the correct option"}}
}}
Every scene object also has "chapter": "2-4 word {L['name']} chapter name for YouTube chapters".
"""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json",
                                 "maxOutputTokens": 60000}}
    last_err = None
    best, min_words = None, int(env("MIN_WORDS") or 650)       # ~650+ spoken words = 5+ minutes
    models = gemini_models(key)
    for round_no in range(3):
        if round_no:
            log(f"All Gemini models busy - waiting {90 * round_no} s")
            time.sleep(90 * round_no)
        for model in list(models):
            try:
                log(f"Writing story with {model} ...")
                r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent",
                                  headers={"x-goog-api-key": key}, json=body, timeout=300)
                if r.status_code in (404, 400):
                    raise LookupError(r.text[:300])
                if r.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"busy ({r.status_code})")
                r.raise_for_status()
                cand = r.json()["candidates"][0]
                text = cand["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
                story = json.loads(text)
                assert story.get("title") and len(story.get("scenes", [])) >= 6
                assert all(s.get("lines") for s in story["scenes"])
                words = sum(len(str(ln.get("text", "")).split()) for sc in story["scenes"] for ln in sc["lines"])
                log(f"  story: {len(story['scenes'])} scenes, {words} spoken words")
                if not best or words > best[0]:
                    best = (words, story)
                if words < min_words:
                    body["contents"][0]["parts"][0]["text"] = prompt + (
                        f"\n\nIMPORTANT: your last story had only {words} spoken words - far too short. "
                        f"Write at least {min_words + 150} spoken words: more scenes and more lines per scene.")
                    raise ValueError("story too short - asking for a longer one")
                return story
            except LookupError as e:
                last_err = e
                models.remove(model)
            except Exception as e:
                last_err = e
                log("  trying next model:", str(e)[:200])
                time.sleep(5)
    if best:
        log(f"  using the longest story written ({best[0]} words)")
        return best[1]
    raise RuntimeError(f"Gemini failed: {last_err}")


# ----------------------------------------------------------------- 2. pictures (Cloudflare)
CF_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
CF_BACKUP = "@cf/black-forest-labs/flux-1-schnell"


def fit(img, w=W, h=H):
    """Whole picture in a w x h frame, nothing cut; empty sides filled with a dark blurred copy."""
    img = img.convert("RGB")
    if abs(img.width / img.height - w / h) < 0.03:
        return img.resize((w, h), Image.LANCZOS)
    s = max(w / img.width, h / img.height)
    bg = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    l, t = (bg.width - w) // 2, (bg.height - h) // 2
    bg = bg.crop((l, t, l + w, t + h)).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (w, h), (0, 0, 0)), 0.45)
    s = min(w / img.width, h / img.height)
    fg = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return bg


class Cast:
    def __init__(self, story):
        self.setting = ascii_text(story.get("setting", ""))
        self.chars = {}        # key -> dict(name, look, gender, age, kind)
        for c in story.get("characters", []) or []:
            if isinstance(c, dict) and c.get("name"):
                k = ascii_text(c["name"]).lower()
                self.chars[k] = {"name": ascii_text(c["name"]), "look": ascii_text(c.get("look", "")),
                                 "gender": str(c.get("gender", "male")).lower(),
                                 "age": str(c.get("age", "adult")).lower(),
                                 "kind": str(c.get("kind", "human")).lower()}
        self.ref = None

    def find(self, name):
        k = ascii_text(name).lower()
        if not k:
            return None
        return self.chars.get(k) or next((v for kk, v in self.chars.items() if k in kk or kk in k), None)

    def pick(self, names):
        out = []
        for n in names or []:
            c = self.find(n)
            if c and c not in out:
                out.append(c)
        return out or list(self.chars.values())

    def describe(self, chosen):
        return " ".join(f"{c['name']}: {c['look']}." for c in chosen)

    def scene_prompt(self, action, place, names, use_ref):
        """Picture prompt. The exact moment of the story comes FIRST (the picture model follows the start
        of the prompt most), then who is in it, then the place, then the art style."""
        low = ascii_text(action).lower()
        empty = isinstance(names, list) and not names           # [] = a shot with nobody in it
        names = list(names or []) + [c["name"] for c in self.chars.values() if c["name"].lower() in low]
        chosen = []
        for n in names:
            c = self.find(n)
            if c and c not in chosen:
                chosen.append(c)
        if not chosen and not empty:
            chosen = [c for c in self.chars.values() if not c.get("host")]
        who = (f"Characters in the picture (ONLY these, each exactly as described): {self.describe(chosen)} "
               if chosen else "No people in this picture, only the place and the objects described. ")
        p = (f"{ascii_text(action)}. {who}"
             f"Location: {ascii_text(place)}. {self.setting}. Style: {ART_STYLE}.")
        if use_ref and chosen:
            p = ("Same characters as in image 0 (same faces, hair, body and clothes), now acting out this NEW "
                 "scene with a full background - not standing in a row, not a reference sheet: " + p)
        return p


CF_QUOTA_OUT = False
PIC_W, PIC_H = 1024, 576        # 16:9; scaled up to 1280x720 for the video


def cf_accounts():
    """All Cloudflare accounts given: CF_ACCOUNT_ID/CF_API_TOKEN, then ..._2, ..._3 (each has its own free limit)."""
    out = []
    for suf in ("", "_2", "_3", "_4"):
        a, t = env("CF_ACCOUNT_ID" + suf), env("CF_API_TOKEN" + suf)
        if a and t:
            out.append((a, t))
    if not out:
        need_env("CF_ACCOUNT_ID")
    return out


CF_ACTIVE = 0


def cf_request(model, prompt, ref_path=None, w=PIC_W, h=PIC_H, seed=None):
    """Ask Cloudflare for a picture. When one account's free daily limit is used up,
    move on to the next account automatically."""
    global CF_ACTIVE, CF_QUOTA_OUT
    accounts = cf_accounts()
    while CF_ACTIVE < len(accounts):
        try:
            return _cf_request_one(accounts[CF_ACTIVE], model, prompt, ref_path, w, h, seed)
        except RuntimeError as e:
            if any(k in str(e).lower() for k in ("4006", "daily free allocation", "neurons")):
                CF_ACTIVE += 1
                if CF_ACTIVE < len(accounts):
                    log(f"  Cloudflare account {CF_ACTIVE} free limit used up - switching to account {CF_ACTIVE + 1}")
                    continue
                CF_QUOTA_OUT = True
            raise
    CF_QUOTA_OUT = True
    raise RuntimeError("all Cloudflare accounts used up their daily free allocation (4006)")


def _cf_request_one(account, model, prompt, ref_path, w, h, seed):
    acct, token = account
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    hdr = {"Authorization": f"Bearer {token}"}
    if model == CF_MODEL:
        fields = {"prompt": (None, prompt[:2000]), "width": (None, str(w)), "height": (None, str(h))}
        if seed is not None:
            fields["seed"] = (None, str(seed))
        if ref_path:
            fields["input_image_0"] = ("ref.jpg", open(ref_path, "rb"), "image/jpeg")
        r = requests.post(url, headers=hdr, files=fields, timeout=150)
    else:
        r = requests.post(url, headers=hdr, json={"prompt": prompt[:2000], "steps": 6}, timeout=150)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    js = r.json()
    img = (js.get("result") or {}).get("image") or js.get("image")
    if not img:
        raise RuntimeError("no image in reply: " + r.text[:200])
    return base64.b64decode(img)


def save_picture(data, path):
    with open(path + ".raw", "wb") as f:
        f.write(data)
    fit(Image.open(path + ".raw")).save(path, quality=93)


def make_cast_sheet(cast, path, seed):
    if MOCK:
        return mock_image(path, seed)
    humans = [c for c in cast.chars.values()]
    prompt = (f"{ART_STYLE}. Cast reference photo: all these people standing side by side, full body, "
              f"facing the camera, neutral grey studio background, even soft light. {cast.describe(humans)}")
    for attempt in range(3):
        try:
            data = cf_request(CF_MODEL, prompt, w=1024, h=576, seed=seed)
            with open(path + ".raw", "wb") as f:
                f.write(data)
            im = Image.open(path + ".raw").convert("RGB")
            im.thumbnail((508, 508))
            im.save(path, quality=92)
            cast.ref = path
            return True
        except Exception as e:
            log(f"  cast sheet attempt {attempt + 1} failed: {str(e)[:200]}")
            if CF_QUOTA_OUT:
                return False
            time.sleep(6 * (attempt + 1))
    return False


def make_image(cast, action, place, names, path, seed):
    global CF_QUOTA_OUT
    if MOCK:
        return mock_image(path, seed)
    if CF_QUOTA_OUT:
        return False
    tries = []
    if cast.ref:
        tries.append((CF_MODEL, cast.scene_prompt(action, place, names, True), cast.ref))
    tries.append((CF_MODEL, cast.scene_prompt(action, place, names, False), None))
    tries.append((CF_BACKUP, cast.scene_prompt(action, place, names, False)[:1500], None))
    soft = False
    for attempt, (model, prompt, ref) in enumerate(tries):
        try:
            if soft:
                prompt = soften(prompt)
            save_picture(cf_request(model, prompt, ref, seed=seed), path)
            return True
        except Exception as e:
            if "flagged" in str(e).lower() or "3030" in str(e):
                soft = True                       # safety filter: next try uses gentler words
            if any(k in str(e).lower() for k in ("allocation", "4006", "quota", "neurons")):
                CF_QUOTA_OUT = True               # free daily limit used up: reuse earlier pictures
                log("  Cloudflare daily free limit reached - reusing earlier pictures with new camera moves")
                return False
            log(f"  picture attempt {attempt + 1} ({model.split('/')[-1]}) failed: {str(e)[:200]}")
            time.sleep(6 * (attempt + 1))
    return False


SOFT_WORDS = {
    "corpse": "still figure", "dead body": "figure lying still", "dead": "lifeless-looking", "blood": "red paint",
    "bloody": "stained", "kill": "chase", "killed": "gone", "murder": "mystery", "knife": "old key",
    "skull": "old stone", "demon": "shadowy figure", "possessed": "strange-eyed", "hanging": "standing",
    "terrified": "worried", "screaming": "calling out", "horror movie": "mystery movie", "ghost": "pale figure",
    "witch": "old woman", "grave": "old stone", "coffin": "old wooden box", "attack": "approach",
}


def soften(prompt):
    out = prompt
    for k, v in SOFT_WORDS.items():
        out = re.sub(rf"\b{k}\b", v, out, flags=re.I)
    return out.replace("eerie but not gory", "mysterious, suspenseful, family friendly")


# ----------------------------------------------------------------- 3. voices
# Voice "set" for every kind of character: (pitch change in Hz, speed change in %)
AGE_VOICE = {"child": (30, 8), "young": (10, 4), "adult": (0, 0), "old": (-16, -14)}


def age_group(a):
    a = str(a).lower()
    if any(k in a for k in ("child", "kid", "boy", "girl", "baby")):
        return "child"
    if any(k in a for k in ("young", "teen", "youth")):
        return "young"
    if any(k in a for k in ("old", "elder", "aged", "grand")):
        return "old"
    return "adult"


class Voices:
    """Gives every character their own voice: different speaker, pitch and speed.
    Ghosts get a deep, echoing voice."""

    def __init__(self, lang, cast):
        self.L = LANGS[lang]
        self.map = {}
        used = {"male": 0, "female": 0}
        dup = {}
        nar_voice = self.L["narrator"][0]
        for c in cast.chars.values():
            g = "female" if c["gender"].startswith("f") else "male"
            ag = age_group(c["age"])
            pool = [v for v in self.L[g] if v != nar_voice] or self.L[g]
            voice = pool[used[g] % len(pool)]
            used[g] += 1
            k = (voice, ag)
            n = dup.get(k, 0)                 # same voice + same age twice -> nudge pitch
            dup[k] = n + 1
            pitch, rate = AGE_VOICE[ag]
            pitch += [0, -8, 8, -14, 14][n % 5]
            if voice == nar_voice and ag in ("adult", "young"):
                pitch += 9                     # keep characters clearly different from the narrator
            ghost = False
            if ghost:
                rate -= 10
            self.map[c["name"].lower()] = (voice, f"{rate:+d}%", f"{pitch:+d}Hz", ghost)
        # expressive Gemini voices: never the same voice for two characters
        self.gemini_map, taken = {"mithu": MITHU_GEMINI[0]}, {NARRATOR_GEMINI[0], MITHU_GEMINI[0]}
        for c in cast.chars.values():
            if c["name"].lower() == "mithu":
                continue
            g = "female" if c["gender"].startswith("f") else "male"
            ag = age_group(c["age"])
            pool = GEMINI_POOL[(g, ag)] + [v for k, vs in GEMINI_POOL.items() if k[0] == g for v in vs]
            self.gemini_map[c["name"].lower()] = next((v for v in pool if v not in taken), pool[0])
            taken.add(self.gemini_map[c["name"].lower()])
        # free voice model (Indic Parler-TTS)
        self.parler_map = extras.parler_cast(
            [(c["name"], c["gender"], age_group(c["age"]), False) for c in cast.chars.values()
             if c["name"].lower() != "mithu"], lang, "female")
        spk = extras.PARLER_SPK.get(lang, extras.PARLER_SPK["bn"])
        self.parler_map["mithu"] = (spk["male"][-1], "a very high-pitched, squeaky, playful", "fast")
        self.cast = cast

    def for_speaker(self, speaker):
        s = ascii_text(speaker).lower()
        if not s or s.startswith("narrat"):
            v, r, p = self.L["narrator"]
            return v, r, p, False
        c = self.cast.find(s)
        if c:
            return self.map[c["name"].lower()]
        v, r, p = self.L["narrator"]
        return v, r, p, False


# ---------- expressive voices (Gemini, free keys) - real human acting instead of a robotic voice
NARRATOR_GEMINI = ("Sulafat", "Lumi Didi, a warm, loving young Indian woman telling a story to small children - "
                              "lively, smiling, full of feeling, changing her voice with the story like a real storyteller")
MITHU_GEMINI = ("Puck", "Mithu, a cheeky, funny little green parrot - a bright, squeaky, playful cartoon voice, "
                        "always excited and giggly")
GEMINI_POOL = {
    ("male", "child"): ["Achird", "Puck"], ("male", "young"): ["Fenrir", "Zubenelgenubi", "Sadachbia"],
    ("male", "adult"): ["Orus", "Iapetus", "Alnilam", "Schedar", "Umbriel"],
    ("male", "old"): ["Algenib", "Rasalgethi", "Sadaltager"],
    ("female", "child"): ["Leda", "Laomedeia"], ("female", "young"): ["Zephyr", "Aoede", "Despina"],
    ("female", "adult"): ["Kore", "Callirrhoe", "Erinome", "Achernar"],
    ("female", "old"): ["Gacrux", "Pulcherrima", "Autonoe"],
}
AGE_WORDS = {"child": "a small child of about seven, with a sweet, innocent child's voice",
             "young": "a young person in their early twenties", "adult": "an adult of about forty",
             "old": "a very old, kind grandparent in their late seventies, with a slow, slightly shaky voice"}
EMOTION_WORDS = {
    "normal": "naturally, with feeling", "calm": "calmly and gently", "whisper": "in a soft whisper",
    "scared": "worried and a little scared", "angry": "angrily, sharply", "sad": "sadly, slowly, with a heavy heart",
    "crying": "while crying and sobbing", "happy": "happily, smiling", "excited": "very excitedly",
    "laughing": "laughing", "proud": "proudly",
}
GEMINI_CACHE = {}
GEMINI_READY = False


def gemini_persona(voices, speaker):
    s = ascii_text(speaker).lower()
    c = voices.cast.find(s) if s and not s.startswith("narrat") else None
    if not c:
        return NARRATOR_GEMINI
    if c["name"].lower() == "mithu":
        return MITHU_GEMINI
    g = "female" if c["gender"].startswith("f") else "male"
    ag = age_group(c["age"])
    voice = voices.gemini_map.get(c["name"].lower(), GEMINI_POOL[(g, ag)][0])
    what = "a cute talking animal in a cartoon" if c.get("kind") == "animal" else ("a girl" if g == "female" and ag == "child" else
           "a boy" if ag == "child" else "a woman" if g == "female" else "a man")
    return voice, f"{c['name']}, {what}: {AGE_WORDS[ag]}. A lively cartoon character with real, warm human feelings"


def parler_persona(voices, speaker, lang):
    s = ascii_text(speaker).lower()
    c = voices.cast.find(s) if s and not s.startswith("narrat") else None
    if not c:   # Lumi Didi
        return (extras.PARLER_SPK.get(lang, extras.PARLER_SPK["bn"])["female"][0], "a warm, moderate-pitched", "moderate")
    return voices.parler_map.get(c["name"].lower(), ("Aditi", "a moderate-pitched", "moderate"))


def gemini_line(text, persona, emotion, lang, out_wav, delivery=""):
    if MOCK or env("USE_GEMINI_VOICE") == "0" or extras.TTS_STATE["off"]:
        return False
    voice, who = persona
    how = EMOTION_WORDS.get(str(emotion).lower(), "naturally, with feeling")
    style = (f"Character: {who}. Emotion: {how}. " + (f"Delivery: {delivery}. " if delivery else "") +
             "This is a children's cartoon story: expressive, clear, never flat or robotic. " + extras.PRONOUNCE[lang])
    return extras.tts_gemini(text, voice, style, LANGS[lang]["name"], out_wav, SR)


def _voice_all(todo, make, label, max_minutes):
    global GEMINI_READY
    t0 = time.time()
    for k, (i, j, ln) in enumerate(todo):
        if time.time() - t0 > max_minutes * 60:
            log(f"  {label} too slow today")
            break
        p = os.path.join(WORK, f"g_{i:02d}_{j:02d}.wav")
        if not make(ln, p):
            log(f"  {label} stopped at line {k + 1}/{len(todo)}")
            break
        GEMINI_CACHE[(i, j)] = p
    else:
        GEMINI_READY = True
        log(f"  all {len(todo)} lines voiced by {label} in {(time.time() - t0) / 60:.1f} min")
        return True
    GEMINI_CACHE.clear()
    return False


def prepare_voices(parts_lines, voices, lang):
    """Voice the WHOLE video before it is made, all lines or none (so a voice never changes mid-video):
    1) Gemini expressive voices (free keys)  2) free voice model on GitHub (Indic Parler-TTS)
    3) otherwise Microsoft voices."""
    if MOCK:
        return False
    todo = [(i, j, ln) for i, lines in enumerate(parts_lines) for j, ln in enumerate(lines or [])
            if str(ln.get("text", "")).strip()]
    if extras.tts_keys() and env("USE_GEMINI_VOICE") != "0":
        log(f"Expressive voices for all {len(todo)} lines (keys: {len(extras.tts_keys())})")
        if _voice_all(todo, lambda ln, p: gemini_line(extras.performed(ln), gemini_persona(voices, ln.get("speaker", "narrator")),
                                                      ln.get("emotion", "normal"), lang, p, str(ln.get("delivery", ""))),
                      "Gemini voices", 45):
            return True
    extras.TTS_STATE["off"] = True
    if extras.parler_ok():
        log(f"Free voice model for all {len(todo)} lines")
        if _voice_all(todo, lambda ln, p: extras.parler_line(str(ln["text"]), parler_persona(voices, ln.get("speaker", "narrator"), lang),
                                                             ln.get("emotion", "normal"), p, SR),
                      "free voice model", int(env("FREE_VOICE_MINUTES") or 50)):
            return True
    log("  using Microsoft voices for the whole video")
    return False


async def _edge(text, voice, rate, pitch, out, volume="+0%"):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume).save(out)


# how each emotion changes the voice: (speed %, pitch Hz, volume %, extra sound filter)
EMOTION_VOICE = {
    "normal": (0, 0, 0, ""),
    "calm": (-6, -2, -5, ""),
    "happy": (4, 6, 5, ""),
    "excited": (12, 12, 10, ""),
    "laughing": (8, 10, 5, ""),
    "proud": (-2, 2, 10, ""),
    "whisper": (-10, -6, -35, "highpass=f=180"),
    "scared": (12, 12, 5, ""),
    "angry": (5, -6, 20, ""),
    "sad": (-14, -10, -10, ""),
    "crying": (-10, 6, -5, ""),
}


def _add(a, b, unit):
    return f"{int(str(a).rstrip(unit).replace('+', '') or 0) + b:+d}{unit}"


def tts_line(text, voice_spec, gtts_lang, out_wav, emotion="normal"):
    """Speak one line -> mono 44.1k wav, acted with the given emotion. Returns seconds."""
    if MOCK:
        secs = max(1.2, len(text) / 15)
        freq = 180 + (abs(hash(voice_spec[0] + voice_spec[2])) % 200)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={secs:.2f}",
             "-af", "volume=0.25", "-ar", str(SR), "-ac", "1", out_wav])
        return secs
    voice, rate, pitch, ghost = voice_spec
    er, ep, ev, efx = EMOTION_VOICE.get(str(emotion).lower(), EMOTION_VOICE["normal"])
    rate, pitch = _add(rate, er, "%"), _add(pitch, ep, "Hz")
    volume = f"{ev:+d}%"
    mp3 = out_wav + ".mp3"
    # clean text: symbols/emoji can make the voice service return nothing
    text = re.sub(r"[\u2026]", "...", text)
    text = re.sub(r"[^\w\s\u0900-\u097F\u0980-\u09FF.,!?;:'\"\-()\u0964\u0965]", " ", text)
    text = re.sub(r"\s+", " ", text).strip() or "..."
    ok = False
    # Microsoft's free voice sometimes returns "No audio was received" for some pitch/speed
    # settings (seen with hi-IN-Madhur). So: ask with full settings once; if that fails, ask with
    # plain settings and change pitch/speed ourselves afterwards (sounds the same, never fails).
    def _num(x):
        try:
            return int(str(x).rstrip("%Hz").replace("+", "") or 0)
        except ValueError:
            return 0
    post_pitch, post_tempo = 1.0, 1.0
    tries = [(rate, pitch, volume, False), (rate, "+0Hz", volume, True), ("+0%", "+0Hz", "+0%", True),
             ("+0%", "+0Hz", "+0%", True)]
    for attempt, (r_, p_, v_, manual) in enumerate(tries):
        try:
            asyncio.run(_edge(text, voice, r_, p_, mp3, v_))
            ok = os.path.exists(mp3) and os.path.getsize(mp3) > 800
            if ok:
                if manual:
                    post_pitch = max(0.85, min(1.22, 1 + _num(pitch) / 150))
                    if r_ == "+0%":
                        post_tempo = max(0.7, min(1.4, 1 + _num(rate) / 100))
                break
        except Exception as e:
            log(f"  voice attempt {attempt + 1} failed ({voice}): {str(e)[:80]}")
            time.sleep(2 + 3 * attempt)
    af = "aresample=44100"
    if ok and (post_pitch != 1.0 or post_tempo != 1.0):
        af = (f"asetrate=44100*{post_pitch:.3f},aresample=44100,"
              f"atempo={max(0.5, min(2.0, post_tempo / post_pitch)):.3f}")
    if not ok:
        # backup (Google) has only one voice -> change its pitch so characters still differ
        from gtts import gTTS
        gTTS(text, lang=gtts_lang).save(mp3)
        hz = int(pitch.replace("Hz", "")) if pitch.replace("Hz", "").lstrip("+-").isdigit() else 0
        male = voice in LANGS["hi"]["male"] + LANGS["bn"]["male"]
        f = max(0.72, min(1.3, (0.80 if male else 1.0) * (1 + hz / 160)))
        af = f"asetrate=44100*{f:.3f},aresample=44100,atempo={min(2.0, max(0.5, 1 / f)):.3f}"
    if efx:
        af += "," + efx
    if ghost:
        # Scary ghost voice, three layers mixed together:
        #  1. a very deep, slow, trembling copy of the voice
        #  2. a thin, high, airy "whisper" copy that follows a moment later
        #  3. a low growl (the deep voice, much lower again, quiet)
        # then a long cold echo, like a voice from an empty hall.
        g = (f"[0:a]{af},asplit=3[a][b][c];"
             "[a]asetrate=44100*0.78,aresample=44100,atempo=1.15,vibrato=f=4.5:d=0.35[deep];"
             "[b]asetrate=44100*1.08,aresample=44100,atempo=0.83,highpass=f=1800,volume=0.45,adelay=70[air];"
             "[c]asetrate=44100*0.62,aresample=44100,atempo=1.445,lowpass=f=700,volume=0.55,adelay=20[growl];"
             "[deep][air][growl]amix=inputs=3:normalize=0,"
             "aecho=0.8:0.8:120|260:0.3|0.15,lowpass=f=7000,"
             "dynaudnorm=f=150:g=7,volume=1.1[out]")
        run(["ffmpeg", "-y", "-i", mp3, "-filter_complex", g, "-map", "[out]", "-ac", "1", "-ar", str(SR), out_wav])
        return duration(out_wav)
    run(["ffmpeg", "-y", "-i", mp3, "-af", af, "-ac", "1", "-ar", str(SR), out_wav])
    return duration(out_wav)


# ----------------------------------------------------------------- 4. sound engine (no copyright)
def _np():
    import numpy as np
    return np


def _filt(x, kind, freq, order=2):
    from scipy.signal import butter, sosfilt
    sos = butter(order, freq, btype=kind, fs=SR, output="sos")
    return sosfilt(sos, x)


def _env_decay(n, secs):
    np = _np()
    return np.exp(-np.arange(n) / (SR * secs))


def _noise(n, rnd):
    np = _np()
    return rnd.standard_normal(n)


def _brown(n, rnd):
    np = _np()
    b = np.cumsum(rnd.standard_normal(n))
    b = _filt(b, "highpass", 20, 1)
    return b / (np.abs(b).max() + 1e-9)


def _smooth_lfo(n, rnd, speed=0.25):
    """Slowly wandering 0..1 curve."""
    np = _np()
    k = max(4, int(n / SR * speed * 4) + 4)
    pts = rnd.uniform(0, 1, k)
    return np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)


def _place(track, sound, at):
    i = int(at * SR)
    if i >= len(track):
        return
    j = min(len(track), i + len(sound))
    track[i:j] += sound[:j - i]


def _user_sfx(tag, n):
    """Use your own file sfx/<tag>.mp3 (or .wav) if you add one."""
    np = _np()
    for ext in ("mp3", "wav", "ogg", "m4a"):
        p = os.path.join(SFX_DIR, f"{tag}.{ext}")
        if os.path.exists(p):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", p, "-t", f"{n / SR:.2f}",
                                  "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True).stdout
            a = np.frombuffer(raw, dtype=np.float32).astype("float64")
            out = np.zeros(n)
            out[:len(a)] = a[:n]
            return out * 0.8
    return None


def synth(tag, n, rnd):
    np = _np()
    user = _user_sfx(tag, n)
    if user is not None:
        return user
    t = np.arange(n) / SR
    out = np.zeros(n)
    if tag == "wind":
        b = _filt(_brown(n, rnd), "bandpass", [150, 900])
        out = b / (np.abs(b).max() + 1e-9) * (0.25 + 0.75 * _smooth_lfo(n, rnd, 0.3)) * 0.55
    elif tag == "rain":
        w = _filt(_noise(n, rnd), "bandpass", [1200, 9000]) * 0.08
        drops = np.zeros(n)
        for _ in range(int(n / SR * 25)):
            k = rnd.integers(0, n)
            drops[k] = rnd.uniform(0.2, 1)
        drops = _filt(drops, "highpass", 2500) * 0.6
        out = (w + drops) * (0.8 + 0.2 * _smooth_lfo(n, rnd))
    elif tag == "thunder":
        for _ in range(max(1, int(n / SR / 12))):
            m = int(SR * rnd.uniform(3, 5))
            th = _filt(_brown(m, rnd), "lowpass", 220) * _env_decay(m, rnd.uniform(0.8, 1.6))
            th[:int(SR * 0.05)] *= np.linspace(0, 1, int(SR * 0.05))
            _place(out, th * 1.4, rnd.uniform(0.3, max(0.4, n / SR - 4)))
    elif tag == "crickets":
        chirp = np.sin(2 * np.pi * 4600 * t[:int(SR * 0.035)]) * np.hanning(int(SR * 0.035))
        x = 0.0
        while x < n / SR:
            for k in range(3):
                _place(out, chirp * 0.07, x + k * 0.06)
            x += rnd.uniform(0.6, 1.1)
    elif tag == "owl":
        def hoot(f, d):
            m = int(SR * d)
            tt = np.arange(m) / SR
            return np.sin(2 * np.pi * (f + 8 * np.sin(2 * np.pi * 6 * tt)) * tt) * np.hanning(m)
        x = rnd.uniform(0.5, 2)
        while x < n / SR - 2:
            _place(out, hoot(380, 0.35) * 0.18, x)
            _place(out, hoot(360, 0.6) * 0.18, x + 0.5)
            x += rnd.uniform(5, 9)
        out = out + _filt(out, "lowpass", 2000) * 0.3
    elif tag == "heartbeat":
        def thump(d):
            m = int(SR * d)
            tt = np.arange(m) / SR
            return np.sin(2 * np.pi * 52 * tt) * _env_decay(m, 0.06)
        x, period = 0.2, 0.95
        while x < n / SR:
            _place(out, thump(0.25) * 0.9, x)
            _place(out, thump(0.25) * 0.6, x + 0.22)
            x += period
            period = max(0.55, period - 0.01)    # speeds up = more tension
    elif tag == "footsteps":
        x = rnd.uniform(0.3, 1)
        while x < n / SR - 0.3:
            m = int(SR * 0.18)
            st = _filt(_noise(m, rnd), "bandpass", [80, 700]) * _env_decay(m, 0.03)
            _place(out, st * 0.6, x)
            x += rnd.uniform(0.55, 0.75)
    elif tag == "creak":
        for _ in range(max(1, int(n / SR / 8))):
            m = int(SR * rnd.uniform(1.2, 2.2))
            tt = np.arange(m) / SR
            f = 170 + 160 * np.sin(np.pi * tt / tt[-1]) + 15 * rnd.standard_normal(m).cumsum() / np.sqrt(m)
            ph = 2 * np.pi * np.cumsum(f) / SR
            saw = (ph / np.pi % 2) - 1
            cr = _filt(saw * (0.5 + 0.5 * (rnd.uniform(0, 1, m) > 0.3)), "bandpass", [300, 2500])
            _place(out, cr * np.hanning(m) * 0.35, rnd.uniform(0.2, max(0.3, n / SR - 2.5)))
    elif tag == "whisper":
        w = _filt(_noise(n, rnd), "bandpass", [1800, 6000])
        syl = (_smooth_lfo(n, rnd, 3.0) > 0.55).astype(float)
        syl = _filt(syl, "lowpass", 12, 1)
        out = w * syl * 0.16 * (0.3 + 0.7 * _smooth_lfo(n, rnd, 0.2))
    elif tag == "clock":
        x = 0.0
        tick = _filt(_noise(int(SR * 0.012), rnd), "highpass", 3000) * np.hanning(int(SR * 0.012))
        while x < n / SR:
            _place(out, tick * 0.35, x)
            x += 1.0
    elif tag == "howl":
        x = rnd.uniform(0.5, 1.5)
        while x < n / SR - 3:
            m = int(SR * 2.6)
            tt = np.arange(m) / SR
            f = 420 + 300 * np.sin(np.pi * tt / tt[-1]) ** 0.7 + 10 * np.sin(2 * np.pi * 5 * tt)
            hw = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.hanning(m)
            hw = hw + 0.5 * np.concatenate([np.zeros(int(SR * 0.25)), hw[:-int(SR * 0.25)]])
            _place(out, hw * 0.12, x)
            x += rnd.uniform(9, 15)
    elif tag == "drip":
        x = rnd.uniform(0.2, 1)
        while x < n / SR:
            m = int(SR * 0.12)
            tt = np.arange(m) / SR
            d = np.sin(2 * np.pi * (1800 - 6000 * tt) * tt) * _env_decay(m, 0.025)
            _place(out, d * 0.3, x)
            x += rnd.uniform(1.2, 3.0)
    elif tag == "knock":
        x = rnd.uniform(0.5, 2)
        for k in range(3):
            m = int(SR * 0.15)
            kn = _filt(_noise(m, rnd), "bandpass", [100, 900]) * _env_decay(m, 0.02)
            _place(out, kn * 1.1, x + k * 0.38)
    elif tag == "birds":
        x = rnd.uniform(0.1, 0.8)
        while x < n / SR - 0.5:
            m = int(SR * rnd.uniform(0.08, 0.18))
            tt = np.arange(m) / SR
            f0 = rnd.uniform(2500, 4200)
            ch = np.sin(2 * np.pi * (f0 + 1500 * np.sin(np.pi * tt / tt[-1])) * tt) * np.hanning(m)
            for r in range(int(rnd.integers(1, 4))):
                _place(out, ch * 0.08, x + r * 0.12)
            x += rnd.uniform(0.6, 2.2)
    elif tag == "water":
        w = _filt(_noise(n, rnd), "bandpass", [400, 3000])
        out = w * (0.5 + 0.5 * _smooth_lfo(n, rnd, 2.0)) * 0.08
    elif tag == "boing":
        m = int(SR * 0.6)
        tt = np.arange(m) / SR
        out[:m] += np.sin(2 * np.pi * (180 + 250 * np.exp(-tt * 6) * np.cos(2 * np.pi * 9 * tt)) * tt) * np.exp(-tt * 5) * 0.6
    elif tag == "whoosh":
        m = int(SR * 0.7)
        w = _filt(_noise(m, rnd), "bandpass", [500, 4000]) * np.hanning(m)
        out[:m] += w * 0.35
    elif tag == "pop":
        m = int(SR * 0.08)
        tt = np.arange(m) / SR
        out[:m] += np.sin(2 * np.pi * (900 - 5000 * tt) * tt) * np.exp(-tt * 60) * 0.7
    elif tag == "bell":
        m = int(SR * 2.0)
        tt = np.arange(m) / SR
        out[:m] += sum(np.sin(2 * np.pi * 880 * r * tt) / r for r in (1, 2.4, 3.9)) * np.exp(-tt * 2.2) * 0.25
    elif tag == "splash":
        m = int(SR * 0.9)
        w = _filt(_noise(m, rnd), "bandpass", [300, 6000]) * np.exp(-np.arange(m) / (SR * 0.25))
        out[:m] += w * 0.5
    elif tag == "scare_hit":
        m = int(SR * 2.5)
        tt = np.arange(m) / SR
        boom = np.sin(2 * np.pi * (60 - 20 * tt) * tt) * _env_decay(m, 0.6)
        stab = _filt(_noise(m, rnd), "bandpass", [2000, 7000]) * _env_decay(m, 0.25) * 0.4
        _place(out, (boom + stab) * 0.9, 0.05)
    return out


SFX_KEYWORDS = [  # words in a sound name -> built-in sound used when no real recording is available
    (("bird", "chirp", "crow", "cuckoo", "sparrow", "parrot", "rooster", "peacock"), "birds"),
    (("river", "stream", "pond", "flowing"), "water"),
    (("splash", "jump into water", "fell in water"), "splash"),
    (("bounce", "boing", "spring", "jump"), "boing"),
    (("whoosh", "swish", "fly", "zoom", "swing"), "whoosh"),
    (("pop", "bubble", "click"), "pop"),
    (("bell", "temple", "ring", "chime"), "bell"),
    (("door", "creak", "hinge", "gate", "floorboard", "chair"), "creak"),
    (("knock", "bang on", "tap"), "knock"),
    (("step", "walk", "footstep", "running"), "footsteps"),
    (("thunder", "lightning", "storm"), "thunder"),
    (("rain", "drizzle", "monsoon"), "rain"),
    (("wind", "breeze", "gust"), "wind"),
    (("heart",), "heartbeat"),
    (("clock", "tick"), "clock"),
    (("owl",), "owl"),
    (("howl", "dog", "wolf", "jackal"), "howl"),
    (("drip", "drop", "tap water"), "drip"),
    (("whisper", "murmur"), "whisper"),
    (("cricket", "insect", "night", "field"), "crickets"),
    (("crash", "bang", "boom", "thud", "fall"), "knock"),
]
_SFX_CACHE = {}


def _keyword_tag(name):
    low = str(name).lower()
    for words, tag in SFX_KEYWORDS:
        if any(w in low for w in words):
            return tag
    return None


def _decode(path, max_sec):
    np = _np()
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-t", f"{max_sec:.2f}", "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32).astype("float64")
    peak = np.abs(a).max() if len(a) else 0
    return a / peak * 0.8 if peak > 0 else a


def freesound(query, loop):
    """Real recorded sound from freesound.org (only Creative-Commons-0 = free for any use)."""
    key = env("FREESOUND_API_KEY")
    if not key or MOCK:
        return None
    ck = (query.lower(), loop)
    if ck in _SFX_CACHE:
        return _SFX_CACHE[ck]
    path = None
    try:
        dur = "[20 TO 600]" if loop else "[0.3 TO 10]"
        words = re.sub(r"[^a-z ]", " ", query.lower()).split()
        stop = {"a", "an", "the", "on", "of", "in", "at", "slowly", "suddenly", "old", "far", "away", "three", "two"}
        core = [w for w in words if w not in stop]
        pairs = [" ".join(core[i:i + 2]) for i in range(len(core) - 1)]
        tries = [" ".join(words), " ".join(core)] + pairs + core[:2]
        res = []
        for q in dict.fromkeys(t for t in tries if t):
            r = requests.get("https://freesound.org/apiv2/search/", timeout=30, params={
                "query": q, "token": key, "fields": "id,name,duration,previews,avg_rating,num_downloads",
                "filter": f'license:"Creative Commons 0" duration:{dur}', "sort": "score", "page_size": 8})
            res = r.json().get("results", []) if r.ok else []
            if res:
                # among the most relevant, prefer well-liked, much-used recordings (better quality)
                res = sorted(res[:5], key=lambda x: (x.get("avg_rating") or 0) * 10 + min(x.get("num_downloads") or 0, 5000) / 500,
                             reverse=True)
                break
        if res:
            pick = res[0]
            url = pick["previews"].get("preview-hq-mp3") or pick["previews"].get("preview-lq-mp3")
            path = os.path.join(WORK, f"fs_{pick['id']}.mp3")
            if not os.path.exists(path):
                with open(path, "wb") as f:
                    f.write(requests.get(url, timeout=60).content)
            log(f"    sound: '{query}' -> freesound #{pick['id']} {pick['name'][:40]}")
    except Exception as e:
        log(f"    freesound error for '{query}': {str(e)[:100]}")
        path = None
    _SFX_CACHE[ck] = path
    return path


def get_oneshot(name, rnd, max_sec=4.0):
    """A single sound effect (door creak, scream...). Real recording if possible, else built-in."""
    np = _np()
    p = freesound(name, loop=False)
    if p:
        a = _decode(p, max_sec)
        if len(a) > SR * 0.2:
            fade = min(len(a) // 4, int(SR * 0.3))
            a[-fade:] *= np.linspace(1, 0, fade)
            return a
    tag = _keyword_tag(name)
    if not tag:
        return None
    a = synth(tag, int(SR * max_sec), rnd)
    nz = np.nonzero(np.abs(a) > 0.02)[0]
    if len(nz) == 0:
        return None
    a = a[max(0, nz[0] - int(SR * 0.05)):]
    end = nz[-1] - nz[0] + int(SR * 0.4)
    return a[:max(int(SR * 0.3), end)] / (np.abs(a).max() + 1e-9) * 0.8


def get_ambience(name, n, rnd):
    """A background sound for the whole scene (rain, crickets...), looped to n samples."""
    np = _np()
    p = freesound(name, loop=True)
    if p:
        a = _decode(p, 120)
        if len(a) > SR * 3:
            reps = int(np.ceil(n / len(a))) + 1
            a = np.tile(a, reps)[:n]
            fade = min(n // 6, int(SR * 1.5))
            a[:fade] *= np.linspace(0, 1, fade)
            a[-fade:] *= np.linspace(1, 0, fade)
            return a * 0.6
    tag = _keyword_tag(name)
    if tag and tag != "scare_hit":
        return synth(tag, n, rnd)
    return None


def drone(n, rnd, mood):
    """Soft, cheerful background music: warm chords + a gentle music-box melody (made here, no copyright)."""
    np = _np()
    t = np.arange(n) / SR
    root = rnd.choice([261.63, 293.66, 329.63, 349.23])         # C, D, E, F
    if mood == "sad":
        prog = [(0, 3, 7), (-4, 0, 3), (-2, 2, 5), (-5, -1, 2)]   # minor, slow
        tempo = 70
    else:
        prog = [(0, 4, 7), (5, 9, 12), (-3, 0, 4), (7, 11, 14)]   # I - IV - vi - V
        tempo = {"funny": 118, "adventure": 112, "happy": 104}.get(mood, 90)
    beat = 60 / tempo
    bar = beat * 4
    out = np.zeros(n)
    # warm pad chords
    for k in range(int(t[-1] / bar) + 1 if n else 0):
        chord = prog[k % len(prog)]
        a0, a1 = int(k * bar * SR), min(n, int((k + 1) * bar * SR))
        if a0 >= n:
            break
        tt = t[a0:a1] - t[a0]
        env = np.minimum(1, tt / 0.4) * np.minimum(1, (bar - tt) / 0.4)
        for semi in chord:
            f = root / 2 * 2 ** (semi / 12)
            out[a0:a1] += 0.06 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt))
    # music-box melody on the beat (pentatonic, so it always sounds sweet)
    scale = [0, 2, 4, 7, 9, 12, 14, 16]
    step = beat / (2 if mood in ("funny", "adventure") else 1)
    note_len = int(SR * min(0.9, step * 1.6))
    nt = np.arange(note_len) / SR
    pos, prev = 0.0, 4
    while pos < t[-1] if n else False:
        if rnd.uniform() < 0.8:
            prev = int(np.clip(prev + rnd.choice([-2, -1, 1, 2]), 0, len(scale) - 1))
            f = root * 2 ** (scale[prev] / 12)
            note = (np.sin(2 * np.pi * f * nt) + 0.25 * np.sin(2 * np.pi * 3 * f * nt)) * np.exp(-nt * 4.5)
            _place(out, note * 0.05, pos)
        pos += step
    fade = min(n // 4, int(SR * 1.5))
    if fade:
        out[:fade] *= np.linspace(0, 1, fade)
        out[-fade:] *= np.linspace(1, 0, fade)
    return out * (0.8 if mood == "calm" else 1.0)


def read_wav(path):
    np = _np()
    with wave.open(path) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype("float64") / 32768
    return a


def write_wav(path, a):
    np = _np()
    a = np.clip(a, -1, 1)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((a * 32767).astype(np.int16).tobytes())


def make_scene_audio(lines, voices, lang, idx, sounds, mood, out_wav, ambience=None):
    """Like a radio drama: every line is spoken with its own voice + emotion, and each sound
    effect is placed exactly where the story says it happens (before / during / after the line).
    Ambience (rain, crickets...) and music run underneath and get quieter while people talk.
    Returns (seconds, [(start, dur, speaker_is_narrator, text)])."""
    np = _np()
    rnd = np.random.default_rng(1000 + idx)
    gap, lead, tail = 0.35, 0.5, 1.0
    pieces, subs, cues, silences, t = [], [], [], [], lead
    for j, ln in enumerate(lines):
        text = str(ln.get("text", "")).strip()
        if not text:
            continue
        sfx = [x for x in (ln.get("sfx") or []) if isinstance(x, dict) and x.get("sound")]
        before = [x for x in sfx if str(x.get("when", "")).startswith("before")]
        during = [x for x in sfx if str(x.get("when", "")).startswith("during")]
        after = [x for x in sfx if str(x.get("when", "")).startswith("after")]
        # sounds that happen first, e.g. "the door creaked..." -> creak, then the words
        for x in before[:2]:
            snd = get_oneshot(x["sound"], rnd)
            if snd is not None:
                cues.append((t, snd, 0.85))
                t += min(len(snd) / SR, 2.2) * 0.75 + 0.15
        if ln.get("jump_scare"):
            # classic jump scare: everything goes almost silent, then a sudden hit
            silences.append((max(0.0, t - 0.9), t))
            cues.append((t, synth("scare_hit", int(SR * 2.5), rnd), 1.0))
            t += 0.45
        spec = voices.for_speaker(ln.get("speaker", "narrator"))
        p = os.path.join(WORK, f"v_{idx:02d}_{j:02d}.wav")
        if (idx, j) in GEMINI_CACHE:
            shutil.copy(GEMINI_CACHE[(idx, j)], p)
        else:
            tts_line(extras.strip_tags(text), spec, LANGS[lang]["gtts"], p, ln.get("emotion", "normal"))
        a = read_wav(p)
        pk = np.abs(a).max()
        if pk > 0:                                    # every voice equally clear; whispers softer
            emo = str(ln.get("emotion", "normal")).lower()
            a = a / pk * {"whisper": 0.6, "shout": 0.97, "angry": 0.93}.get(emo, 0.88)
        if spec[3]:                                   # ghost speaking: cold swell + whispers
            m = int(SR * 1.2)
            swell = _filt(_noise(m, rnd), "bandpass", [300, 3000]) * np.linspace(0, 1, m) ** 2 * 0.35
            cues.append((max(0.0, t - 1.1), swell, 1.0))
            cues.append((t, synth("whisper", len(a) + int(SR * 0.8), rnd) * 1.4, 0.8))
        pieces.append((t, a))
        sp = ascii_text(ln.get("speaker", "")).lower()
        is_nar = (not sp) or sp.startswith("narrat") or voices.cast.find(sp) is None
        subs.append((t, len(a) / SR, is_nar, text))
        for x in during[:2]:
            snd = get_oneshot(x["sound"], rnd, max_sec=min(6.0, len(a) / SR + 1))
            if snd is not None:
                cues.append((t + 0.25, snd, 0.55))
        t += len(a) / SR + gap
        for x in after[:2]:
            snd = get_oneshot(x["sound"], rnd)
            if snd is not None:
                cues.append((t - gap + 0.1, snd, 0.85))
                t += min(len(snd) / SR, 2.0) * 0.7
    total = t - gap + tail
    n = int(total * SR)

    voice = np.zeros(n)
    for start, a in pieces:
        _place(voice, a, start)

    # background: music + place ambience (from the story) + any old-style tags
    bed = drone(n, rnd, mood)
    for name in (ambience or [])[:2]:
        amb = get_ambience(str(name), n, rnd)
        if amb is not None:
            bed += amb * 0.5
    for tag in (sounds or [])[:3]:
        if tag in SOUND_TAGS and tag != "scare_hit":
            bed += synth(tag, n, rnd) * 0.5

    fx = np.zeros(n)
    for start, snd, vol in cues:
        _place(fx, snd * vol, start)

    # quieter background while someone talks; near silence before a jump scare
    talk = np.zeros(n)
    for start, a in pieces:
        talk[int(start * SR):int(start * SR) + len(a)] = 1
    talk = np.clip(_filt(talk, "lowpass", 3, 1), 0, 1)
    quiet = np.ones(n)
    for s0, s1 in silences:
        quiet[int(s0 * SR):int(s1 * SR)] = 0.08
    quiet = _filt(quiet, "lowpass", 6, 1)
    mix = voice * 0.95 + bed * (1 - 0.6 * talk) * quiet + fx * (1 - 0.3 * talk)
    peak = np.abs(mix).max()
    if peak > 0.98:
        mix *= 0.98 / peak
    write_wav(out_wav, mix)
    return total, subs


# ----------------------------------------------------------------- fonts
def find_font(lang):
    g = LANGS[lang]["font_glob"]
    cands = [env(f"FONT_PATH_{lang.upper()}")]
    cands += glob.glob(f"/usr/share/fonts/**/{g}-Bold.ttf", recursive=True)
    cands += glob.glob(os.path.join(HERE, "fonts", f"{g}*.ttf"))
    cands += glob.glob(f"/usr/share/fonts/**/{g}*.tt*", recursive=True)
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit(f"ERROR: font for {lang} not found (install fonts-noto-core).")


FONT = None


def font(size):
    return ImageFont.truetype(FONT, size, layout_engine=ImageFont.Layout.RAQM)


# ----------------------------------------------------------------- 5. thumbnail
def make_thumbnail(base_img, text, out, label):
    """Professional kids-channel thumbnail: bright punchy picture with the character big on the right,
    huge 2-line text on the left (yellow + white on a colour banner) with thick outline and glow,
    a story-type tag and a bright frame."""
    from PIL import ImageEnhance
    img = Image.open(base_img).convert("RGB").resize((W, H))
    img = ImageEnhance.Color(img).enhance(1.35)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Sharpness(img).enhance(1.6)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    # soft colour fade on the left so the words stand out
    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    for x in range(int(W * 0.6)):
        d.line([(x, 0), (x, H)], fill=int(175 * (1 - x / (W * 0.6)) ** 1.4))
    img = Image.composite(Image.new("RGB", (W, H), (40, 10, 90)), img, shade)

    words = text.strip().split()
    if len(words) >= 2:
        half = len(words) // 2 + len(words) % 2
        lines = [" ".join(words[:half]), " ".join(words[half:])]
    else:
        lines = [text.strip()]
    box_w = int(W * 0.6)
    probe = ImageDraw.Draw(img)
    size = 170
    while size > 56:
        f = font(size)
        if all(probe.textlength(l, font=f) <= box_w - 70 for l in lines) and size * 1.35 * len(lines) <= H * 0.68:
            break
        size -= 6
    f = font(size)
    lh = int(size * 1.38)
    y0 = int((H - lh * len(lines)) / 2) + 20
    x0 = 46

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))                      # white glow behind the words
    gd = ImageDraw.Draw(glow)
    for i, l in enumerate(lines):
        gd.text((x0, y0 + i * lh), l, font=f, fill=(255, 255, 255, 230), stroke_width=size // 6,
                stroke_fill=(255, 255, 255, 230))
    glow = glow.filter(ImageFilter.GaussianBlur(16))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    draw = ImageDraw.Draw(img)
    banner = (255, 70, 120)
    for i, l in enumerate(lines):
        y = y0 + i * lh
        if i == len(lines) - 1 and len(lines) > 1:                     # last line on a pink banner
            tw = draw.textlength(l, font=f)
            draw.rounded_rectangle([x0 - 18, y - size * 0.02, x0 + tw + 18, y + size * 1.22], radius=22, fill=banner,
                                   outline=(255, 255, 255), width=5)
            draw.text((x0, y), l, font=f, fill=(255, 255, 255), stroke_width=max(5, size // 18), stroke_fill=(90, 0, 40))
        else:
            draw.text((x0, y), l, font=f, fill=(255, 225, 0), stroke_width=max(8, size // 10), stroke_fill=(20, 0, 60))

    lf = font(40)                                                        # story-type tag
    tw = draw.textlength(label, font=lf)
    draw.rounded_rectangle([30, 26, 30 + tw + 44, 26 + 72], radius=36, fill=(255, 200, 0), outline=(255, 255, 255), width=4)
    draw.text((52, 30), label, font=lf, fill=(60, 0, 80))
    draw.rectangle([0, 0, W - 1, H - 1], outline=(255, 200, 0), width=12)  # bright frame
    img.save(out, quality=94)


# ----------------------------------------------------------------- 6. video
_REMBG = None
_LOOK = {}


def cutout_session():
    global _REMBG
    if _REMBG is None:
        from rembg import new_session
        try:
            _REMBG = new_session("isnet-general-use")
        except Exception as e:
            log("  cut-out model unavailable, using small model:", str(e)[:120])
            _REMBG = new_session("u2netp")
    return _REMBG


def split_layers(img_path):
    np = _np()
    import cv2
    from rembg import remove
    pic = Image.open(img_path).convert("RGB").resize((W, H))
    alpha = np.array(remove(pic, session=cutout_session(), only_mask=True).convert("L").resize((W, H)))
    part = (alpha > 128).mean()
    if part < 0.03 or part > 0.60:
        return None
    rgb = np.array(pic)
    hole = cv2.dilate((alpha > 40).astype("uint8") * 255, np.ones((25, 25), "uint8"))
    small = cv2.inpaint(cv2.resize(rgb, (W // 2, H // 2)), cv2.resize(hole, (W // 2, H // 2)), 9,
                        cv2.INPAINT_TELEA)
    bg = cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC)
    bg = np.where(hole[..., None] > 0, cv2.GaussianBlur(bg, (0, 0), 3), rgb)
    return bg, np.dstack([rgb, cv2.GaussianBlur(alpha, (0, 0), 1.2)])


def horror_look():
    """Pre-made vignette, film grain and fog textures (made once, reused every frame)."""
    if _LOOK:
        return _LOOK
    np = _np()
    import cv2
    rnd = np.random.default_rng(7)
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    _LOOK["vignette"] = np.clip(1.15 - 0.55 * r ** 1.6, 0.25, 1)[..., None].astype("float32")
    _LOOK["grain"] = [cv2.GaussianBlur((rnd.standard_normal((H, W)) * 4.5).astype("float32"), (0, 0), 0.8)[..., None]
                      for _ in range(6)]   # soft grain: looks like film, keeps the file small
    fog = cv2.resize(rnd.uniform(0, 1, (12, 24)).astype("float32"), (W * 2, H), interpolation=cv2.INTER_CUBIC)
    fog = cv2.GaussianBlur(fog, (0, 0), 25)
    _LOOK["fog"] = np.clip((fog - fog.min()) / (fog.max() - fog.min() + 1e-6), 0, 1)
    return _LOOK


def grade(frame_f32, f, sec, mood, rnd_flicker):
    """Bright, clean cartoon look: a touch more colour and a very soft vignette."""
    np = _np()
    look = horror_look()
    gray = frame_f32.mean(axis=2, keepdims=True)
    frame = gray + (frame_f32 - gray) * 1.08                    # slightly richer colours
    frame *= 0.88 + 0.12 * look["vignette"]
    return frame


_LAYER_CACHE = {}


def _layers_for(img):
    """Background + cut-out foreground for one picture (cached, pictures repeat)."""
    np = _np()
    import cv2
    if img in _LAYER_CACHE:
        return _LAYER_CACHE[img]
    layers = None
    try:
        layers = split_layers(img)
    except Exception as e:
        log(f"  cut-out failed: {str(e)[:100]}")
    d = {}
    if layers is not None:
        bg, fg = layers
        d["fg_a"] = fg[..., 3].astype("float32") / 255.0
        d["fg"] = cv2.cvtColor(fg[..., :3], cv2.COLOR_RGB2BGR).astype("float32")
        ys, xs = np.nonzero(d["fg_a"] > 0.5)
        d["cx"], d["cy"] = float(xs.mean()), float(ys.max())
        d["head"] = float(ys.min() + 0.28 * (ys.max() - ys.min()))
    else:
        bg = np.array(Image.open(img).convert("RGB").resize((W, H)))
        d["cx"], d["cy"], d["head"] = W / 2, H / 2, H * 0.42
    d["bg"] = cv2.cvtColor(bg, cv2.COLOR_RGB2BGR)
    _LAYER_CACHE[img] = d
    return d


def plan_shots(segments, total):
    """segments: [(image, start_sec)] -> [(image, start, end, close_up)].
    Long shots are split into a wide part and a close-up part so the screen keeps changing."""
    segs = []
    for k, (img, st) in enumerate(segments):
        en = segments[k + 1][1] if k + 1 < len(segments) else total
        if segs and segs[-1][0] == img:                       # same picture twice in a row -> one shot
            segs[-1] = (img, segs[-1][1], en, False)
        else:
            segs.append((img, st, en, False))
    out = []
    for i, (img, st, en, _) in enumerate(segs):
        d = en - st
        parts = 1 if d < 8 else (2 if d < 15 else 3)
        for p in range(parts):
            out.append((img, st + d * p / parts, st + d * (p + 1) / parts, p % 2 == 1))
    return out


def scene_clip_animated(segments, audio, out, idx, mood):
    np = _np()
    import cv2
    dur = duration(audio)
    n = int(dur * FPS) + 1
    shots = plan_shots(segments, dur)
    rnd = np.random.default_rng(idx + 50)
    flicker = (rnd.uniform(0, 1, 400) > 0.93).astype("float32") * rnd.uniform(0.4, 1, 400)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", audio, "-t", f"{dur:.2f}",
         "-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, dur - 0.4):.2f}:d=0.4,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k",
         "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2", out],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    XF = 8                                                  # cross-fade frames between shots
    prev_last, cur_k, frame_in_shot = None, -1, 0
    try:
        for f in range(n):
            sec = f / FPS
            k = next((i for i, s in enumerate(shots) if s[1] <= sec < s[2]), len(shots) - 1)
            img, st, en, close = shots[k]
            if k != cur_k:
                cur_k, frame_in_shot = k, 0
            L = _layers_for(img)
            t = min(1.0, max(0.0, (sec - st) / max(en - st, 0.1)))
            ease = 0.5 - 0.5 * math.cos(math.pi * t)
            direction = 1 if (idx + k) % 2 == 0 else -1
            shake = 0.0
            pass
            if close:                                       # slow push towards the face
                fx, fy = L["cx"], L["head"]
                bz = 1.32 + 0.08 * ease
            else:                                           # wide shot, gentle drift
                fx, fy = W / 2, H / 2
                bz = 1.04 + 0.06 * ease
            Mb = cv2.getRotationMatrix2D((fx, fy), 0, bz)
            Mb[0, 2] += (W / 2 - fx) * (bz - 1) / bz * (1 if close else 0) + direction * (ease - 0.5) * 22 + shake
            Mb[1, 2] += (H / 2 - fy) * (bz - 1) / bz * (1 if close else 0) + shake * 0.6
            frame = cv2.warpAffine(L["bg"], Mb, (W, H), borderMode=cv2.BORDER_REFLECT).astype("float32")
            if "fg" in L:
                fz = bz * (1.0 + 0.03 * ease) + 0.004 * math.sin(sec * 1.6)
                Mf = cv2.getRotationMatrix2D((fx, fy), 0.3 * math.sin(sec * 0.9), fz)
                Mf[0, 2] = Mb[0, 2] + direction * (ease - 0.5) * 26 - (fz - bz) * fx
                Mf[1, 2] = Mb[1, 2] - 2.0 * math.sin(sec * 1.1) - (fz - bz) * fy
                fgw = cv2.warpAffine(L["fg"], Mf, (W, H))
                aw = cv2.warpAffine(L["fg_a"], Mf, (W, H))[..., None]
                frame = frame * (1 - aw) + fgw * aw
            frame = grade(frame, f, sec, mood, flicker)
            if prev_last is not None and k > 0 and frame_in_shot < XF:
                a_ = (frame_in_shot + 1) / (XF + 1)
                frame = prev_last * (1 - a_) + frame * a_
            frame_in_shot += 1
            if f + 1 < n:
                nk = next((i for i, s in enumerate(shots) if s[1] <= (f + 1) / FPS < s[2]), len(shots) - 1)
                if nk != k:
                    prev_last = frame.copy()
            ff.stdin.write(np.clip(frame, 0, 255).astype("uint8").tobytes())
        ff.stdin.close()
    except Exception:
        ff.kill()
        raise
    if ff.wait() != 0:
        raise RuntimeError(ff.stderr.read().decode()[-500:])
    return dur


def scene_clip_simple(segments, audio, out, idx, mood):
    """Backup: each picture as its own slow zoom, joined, with the scene sound."""
    dur = duration(audio)
    shots = plan_shots(segments, dur)
    parts = []
    for k, (img, st, en, close) in enumerate(shots):
        d = max(0.2, en - st)
        frames = int(d * FPS) + 1
        z = f"min(1.25+0.0006*on,1.35)" if close else ("min(1+0.0005*on,1.07)" if k % 2 == 0 else "max(1.07-0.0005*on,1)")
        p = os.path.join(WORK, f"seg_{idx:02d}_{k:02d}.mp4")
        run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-t", f"{d:.3f}", "-vf",
             f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
             f"eq=saturation=1.08,format=yuv420p",
             "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", p])
        parts.append(p)
    lst = os.path.join(WORK, f"seg_{idx:02d}.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.basename(x)}'\n" for x in parts)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", audio, "-t", f"{dur:.2f}",
         "-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, dur - 0.4):.2f}:d=0.4,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k",
         "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2", out])
    return dur


def scene_clip(segments, audio, out, idx, mood):
    if env("SIMPLE_MOTION") == "1" or (MOCK and env("TEST_ANIM") != "1"):
        return scene_clip_simple(segments, audio, out, idx, mood)
    try:
        return scene_clip_animated(segments, audio, out, idx, mood)
    except Exception as e:
        log(f"  animation skipped ({str(e)[:150]}) - simple motion")
        return scene_clip_simple(segments, audio, out, idx, mood)


def ass_time(t):
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def split_subs(text, max_len=44):
    parts = [p.strip() for p in re.split(r"(?<=[।!?,\.])\s+", text) if p.strip()]
    out = []
    for p in parts:
        cur = ""
        for w in p.split():
            if cur and len(cur) + 1 + len(w) > max_len:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            out.append(cur)
    return out


def write_ass(segments, path, family):
    """segments: (start, dur, is_narrator, text). Narration white, dialogue yellow."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Nar,{family},52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,38,1
Style: Talk,{family},54,&H0000E6FF,&H0000E6FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,38,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for start, dur, is_nar, text in segments:
        chunks = split_subs(text)
        total = sum(len(c) for c in chunks) or 1
        t = start
        for c in chunks:
            d = dur * len(c) / total
            rows.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t + d)},{'Nar' if is_nar else 'Talk'},,0,0,0,,{c}")
            t += d
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(rows) + "\n")


TIMELINE = ([], [])          # (start second of every part, every spoken line) of the last video
BADGE_COLORS = ((255, 60, 120), (255, 255, 255))


def build_video(scene_parts, lang, out):
    """scene_parts: list of dict(image, lines, sounds, mood). Returns mp4 path."""
    global TIMELINE
    clips, segs, t, wavs, part_times = [], [], 0.0, [], []
    voices = scene_parts[0]["voices"]
    GEMINI_CACHE.clear()
    prepare_voices([sp["lines"] for sp in scene_parts], voices, lang)
    for i, sp in enumerate(scene_parts):
        log(f"Voices + sound + clip {i + 1}/{len(scene_parts)}")
        part_times.append(t)
        a = os.path.join(WORK, f"audio_{i:02d}.wav")
        wavs.append(a)
        d, subs = make_scene_audio(sp["lines"], voices, lang, i, sp.get("sounds"), sp.get("mood", "creepy"), a,
                                   sp.get("ambience"))
        c = os.path.join(WORK, f"clip_{i:02d}.mp4")
        shots = sp.get("shots") or []
        segments = []
        for k, (st, du, nar, tx) in enumerate(subs):        # picture changes when the next line starts
            img = shots[k] if k < len(shots) and shots[k] else sp["image"]
            segments.append((img, 0.0 if k == 0 else max(0.0, st - 0.2)))
        if not segments:
            segments = [(sp["image"], 0.0)]
        d = scene_clip(segments, a, c, i, sp.get("mood", "creepy"))
        segs += [(t + s, du, nar, tx) for s, du, nar, tx in subs]
        clips.append(c)
        t += d
    lst = os.path.join(WORK, "clips.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.basename(c)}'\n" for c in clips)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", os.path.join(WORK, "joined.mp4")])
    alst = os.path.join(WORK, "audio.txt")
    with open(alst, "w") as f:
        f.writelines(f"file '{os.path.basename(a)}'\n" for a in wavs)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", alst, "-c", "pcm_s16le", os.path.join(WORK, "full.wav")])
    write_ass(segs, os.path.join(WORK, "subs.ass"), LANGS[lang]["font_family"])
    vf = f"ass=subs.ass:fontsdir={os.path.dirname(FONT)}:shaping=complex,tpad=stop_mode=clone:stop_duration=3"
    total = duration(os.path.join(WORK, "full.wav"))
    TIMELINE = (part_times, segs)
    try:                                   # small "Like - Share - Follow" pill, top right, at the start and the end
        extras.make_badge(FONT, LANGS[lang]["badge"], os.path.join(WORK, "badge.png"), BADGE_COLORS)
        pic = ["-i", "badge.png", "-filter_complex",
               f"[0:v]{vf}[b];[b][2:v]overlay=W-w-24:22:enable='{extras.badge_filter(total)}'[v]", "-map", "[v]"]
    except Exception as e:
        log("  badge skipped:", str(e)[:120])
        pic = ["-vf", vf, "-map", "0:v"]
    r = subprocess.run(["ffmpeg", "-y", "-i", "joined.mp4", "-i", "full.wav"] + pic + ["-map", "1:a",
                        "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart",
                        os.path.abspath(out)], capture_output=True, text=True, cwd=WORK)
    if r.returncode != 0:
        raise RuntimeError("final render failed:\n" + r.stderr[-2000:])
    return out


# ----------------------------------------------------------------- 7. posting
def _fb_json(r):
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f"Facebook replied HTTP {r.status_code}: {r.text[:200]!r}")


def post_to_facebook(video, thumb, title, description):
    """Uploads in pieces (resumable), so big videos don't fail half-way."""
    page, token = need_env("FB_PAGE_ID"), need_env("FB_PAGE_TOKEN")
    url = f"https://graph-video.facebook.com/v21.0/{page}/videos"
    size = os.path.getsize(video)
    log(f"  video size: {size / 1e6:.0f} MB")
    for attempt in range(3):
        try:
            js = _fb_json(requests.post(url, data={"access_token": token, "upload_phase": "start",
                                                   "file_size": str(size)}, timeout=120))
            if "error" in js:
                err = js["error"]
                if err.get("code") in (190, 200, 10, 100):
                    raise PermissionError(f"Facebook refused: {err.get('message')} -> check FB_PAGE_ID / FB_PAGE_TOKEN")
                raise RuntimeError(err.get("message"))
            sid, start, end = js["upload_session_id"], int(js["start_offset"]), int(js["end_offset"])
            with open(video, "rb") as f:
                while start < end:
                    f.seek(start)
                    chunk = f.read(end - start)
                    for t in range(4):
                        try:
                            jr = _fb_json(requests.post(url, data={"access_token": token, "upload_phase": "transfer",
                                                                   "upload_session_id": sid, "start_offset": str(start)},
                                                        files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")},
                                                        timeout=600))
                            if "error" in jr:
                                raise RuntimeError(jr["error"].get("message"))
                            break
                        except Exception as e:
                            if t == 3:
                                raise
                            log(f"    piece retry: {str(e)[:120]}")
                            time.sleep(10)
                    start, end = int(jr["start_offset"]), int(jr["end_offset"])
                    log(f"    uploaded {start / 1e6:.0f}/{size / 1e6:.0f} MB")
            with open(thumb, "rb") as th:
                jf = _fb_json(requests.post(url, data={"access_token": token, "upload_phase": "finish",
                                                       "upload_session_id": sid, "title": title,
                                                       "description": description, "published": "true"},
                                            files={"thumb": ("thumb.jpg", th, "image/jpeg")}, timeout=300))
            if jf.get("success") or jf.get("id"):
                return js.get("video_id") or jf.get("id") or sid
            raise RuntimeError(str(jf)[:300])
        except PermissionError:
            raise
        except Exception as e:
            log(f"  Facebook upload attempt {attempt + 1} failed: {str(e)[:250]}")
            time.sleep(30)
    raise RuntimeError("Facebook upload failed 3 times")


def youtube_ready():
    return all(env(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def post_to_youtube(video, thumb, title, description, tags, lang):
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": env("YT_CLIENT_ID"), "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"), "grant_type": "refresh_token"}, timeout=60)
    if not r.ok:
        raise PermissionError("YouTube login failed (check YT_ secrets): " + r.text[:300])
    hdr = {"Authorization": f"Bearer {r.json()['access_token']}"}
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": [t.lstrip("#") for t in tags][:15], "categoryId": "1",   # Film & Animation
                    "defaultLanguage": lang, "defaultAudioLanguage": lang},
        "status": {"privacyStatus": env("YT_PRIVACY") or "public", "selfDeclaredMadeForKids": env("YT_MADE_FOR_KIDS") != "0",   # children's cartoons must be marked "made for kids"
                   "containsSyntheticMedia": True},
    }
    size = os.path.getsize(video)
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      headers={**hdr, "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                      data=json.dumps(meta), timeout=60)
    if not r.ok:
        raise RuntimeError("YouTube start failed: " + r.text[:400])
    with open(video, "rb") as f:
        up = requests.put(r.headers["Location"], headers={**hdr, "Content-Type": "video/mp4"}, data=f, timeout=1800)
    if not up.ok:
        raise RuntimeError("YouTube upload failed: " + up.text[:400])
    vid = up.json()["id"]
    if not thumb:
        return vid
    try:
        with open(thumb, "rb") as f:
            t = requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                              headers={**hdr, "Content-Type": "image/jpeg"}, data=f, timeout=120)
        if not t.ok:
            log("  YouTube thumbnail not set (channel may need phone verification):", t.text[:150])
    except Exception as e:
        log("  YouTube thumbnail error:", e)
    return vid


# ----------------------------------------------------------------- voice demo
DEMO_LINES = {
    "hi": {"narrator": "मैं इस कहानी का सूत्रधार हूँ।", "man": "मैं एक आदमी हूँ, मेरी आवाज़ ऐसी है।",
           "woman": "मैं एक औरत हूँ, मेरी आवाज़ ऐसी है।", "young man": "मैं एक नौजवान लड़का हूँ।",
           "young woman": "मैं एक नौजवान लड़की हूँ।", "old man": "मैं एक बूढ़ा आदमी हूँ।",
           "old woman": "मैं एक बूढ़ी औरत हूँ।", "boy": "मैं एक छोटा बच्चा हूँ।", "girl": "मैं एक छोटी बच्ची हूँ।",
           "ghost": "मैं... इस हवेली की आत्मा हूँ..."},
    "bn": {"narrator": "আমি এই গল্পের কথক।", "man": "আমি একজন পুরুষ, আমার গলা এরকম।",
           "woman": "আমি একজন মহিলা, আমার গলা এরকম।", "young man": "আমি একজন যুবক।",
           "young woman": "আমি একজন যুবতী।", "old man": "আমি একজন বুড়ো মানুষ।", "old woman": "আমি একজন বুড়ি।",
           "boy": "আমি একটা ছোট ছেলে।", "girl": "আমি একটা ছোট মেয়ে।", "ghost": "আমি... এই বাড়ির আত্মা..."},
}
DEMO_CAST = [("man", "male", "adult", "human"), ("woman", "female", "adult", "human"),
             ("young man", "male", "young", "human"), ("young woman", "female", "young", "human"),
             ("old man", "male", "old", "human"), ("old woman", "female", "old", "human"),
             ("boy", "male", "child", "human"), ("girl", "female", "child", "human"),
             ("ghost", "female", "old", "ghost")]


def voice_demo():
    """Makes work/voice_demo_hi.mp3 and work/voice_demo_bn.mp3 - every voice type says one line."""
    np = _np()
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    for lang in ("hi", "bn"):
        cast = Cast({"characters": [{"name": n, "gender": g, "age": a, "kind": k, "look": ""}
                                    for n, g, a, k in DEMO_CAST]})
        voices = Voices(lang, cast)
        lines = [{"speaker": "narrator", "text": DEMO_LINES[lang]["narrator"]}]
        lines += [{"speaker": n, "text": DEMO_LINES[lang][n]} for n, *_ in DEMO_CAST]
        out = os.path.join(WORK, f"voice_demo_{lang}.wav")
        make_scene_audio(lines, voices, lang, 0, ["wind"], "creepy", out)
        run(["ffmpeg", "-y", "-i", out, "-b:a", "160k", out.replace(".wav", ".mp3")])
        for n, *_ in DEMO_CAST:
            log(f"  {lang} {n:12s} -> {voices.map[n.lower()]}")
    log("Voice demo ready: download 'horror-video' from this run's page (Artifacts).")


# ----------------------------------------------------------------- main
def main():
    global FONT
    pass
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    history = load_history()
    global SLOT
    SLOT = None if env("MODE") in ("amavasya", "compilation") else extras.current_slot(TRIGGERS)
    if env("MODE") == "compilation":
        return make_compilation(history)
    # automatic runs (GitHub's clock or the cron-job.org clock) must not post twice for one time slot
    if (env("EVENT") == "schedule" or env("MODE") == "auto") and (extras.slot_done(history, SLOT) or recently_posted(history, hours=2)):
        log("A video for this time slot was already posted - this backup run has nothing to do.")
        return
    if not MOCK:
        try:
            extras.refresh_stats(history)            # learn which kinds of stories people liked
        except Exception as e:
            log("  stats skipped:", str(e)[:150])
    lang = pick_language(history)
    L = LANGS[lang]
    FONT = find_font(lang)
    shout_names, shout_ids = [], []
    lastp = extras.last_post(history, key="quiz")
    if lastp and not MOCK and lastp.get("facebook"):
        try:
            qa = lastp["quiz"]
            shout_names, shout_ids = extras.winners(extras.post_comments(lastp.get("facebook")),
                                                    words=(qa.get("text", ""),), label=qa.get("label"))
            log(f"Right quiz answers last time: {len(shout_names)}")
        except Exception as e:
            log("  quiz-answer check skipped:", str(e)[:120])
    theme = pick_theme(history)
    festival = None
    fest = extras.festival_today("cartoon")
    if fest and not any(h.get("festival") == fest[0] and h.get("date") and
                        (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(h["date"])).total_seconds() < 20 * 3600
                        for h in history[-4:]):
        festival = fest[0]
        theme = ("divine" if fest[0] in DIVINE_FESTIVALS else "festival", fest[1])
        log(f"Festival special: {festival}")
    category = theme[0]
    log(f"Language: {L['name']} | Story type: {theme[0]} / {theme[1]}")

    extra = ""
    wx = extras.weather_now(lang) if not MOCK else None
    if wx and any(k in wx for k in ("rain", "drizzle", "thunder", "fog", "cold")) and category not in ("divine", "panchatantra"):
        extra = f"\nTODAY'S WEATHER: {wx}. If it fits, let the story happen in this weather (cosy, not scary).\n"
        log("Weather:", wx)
    story = make_story(lang, theme, history, extra_rules=extra)
    title = story["title"].strip()[:95]
    log("Title:", title)
    with open(os.path.join(WORK, "story.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=1)

    cast = Cast(story)
    voices = Voices(lang, cast)
    for c in cast.chars.values():
        log(f"  {c['name']} ({c['gender']}, {c['age']}, {c['kind']}) -> voice {voices.map[c['name'].lower()][:3]}")
    seed = random.randint(1, 1_000_000)
    scenes = story["scenes"][:24]          # never cut the story short

    log("Cast reference picture")
    if not make_cast_sheet(cast, os.path.join(WORK, "cast.jpg"), seed):
        log("  no cast picture - using text descriptions only")
    cast.chars["mithu"] = dict(MITHU)
    voices = Voices(lang, cast)

    # one picture per spoken line (a new "camera shot" every few seconds), within the free budget
    budget = int(env("MAX_IMAGES") or 30)          # 3 videos a day must fit the free picture limit
    scene_lines = [[ln for ln in (s.get("lines") or []) if str(ln.get("text", "")).strip()] for s in scenes]
    total_lines = sum(len(x) for x in scene_lines) or 1
    imgs, shots_per_scene, last_ok, count = [], [], None, 0
    for i, (s, lines) in enumerate(zip(scenes, scene_lines)):
        want = max(1, min(len(lines), round(len(lines) * budget / total_lines))) if lines else 1
        groups = [lines[round(g * len(lines) / want):round((g + 1) * len(lines) / want)] for g in range(want)] or [[]]
        scene_shots = []
        for g, grp in enumerate(groups):
            count += 1
            p = os.path.join(WORK, f"shot_{i:02d}_{g:02d}.jpg")
            first = grp[0] if grp else {}
            pic = first.get("image") if isinstance(first.get("image"), dict) else {}
            action = pic.get("prompt") or first.get("shot") or s.get("action", "")
            names = pic.get("characters") if isinstance(pic.get("characters"), list) else s.get("characters")
            log(f"Picture {count} (scene {i + 1}, shot {g + 1}/{len(groups)})")
            if make_image(cast, action, s.get("place", ""), names, p, seed):
                last_ok = p
            elif scene_shots:
                p = scene_shots[-1]                      # reuse; the camera move makes it look different
            elif last_ok:
                p = last_ok
            else:
                p = None
            scene_shots += [p] * max(1, len(grp))
        shots_per_scene.append(scene_shots)
        imgs.append(next((x for x in scene_shots if x), None))
    first_ok = next((p for p in imgs if p), None)
    if not first_ok:
        if CF_QUOTA_OUT:
            extras.telegram("⚠️ Little Lumi: today's free picture limit is used up - this video was skipped. "
                            "It resets at 5:30 AM India time.")
            log("STOPPED: today's free Cloudflare picture limit is used up on every account. "
                "Nothing was posted. It resets every day at 5:30 AM India time; the next run will work. "
                "(Tip: add a 2nd free Cloudflare account as CF_ACCOUNT_ID_2 / CF_API_TOKEN_2.)")
            sys.exit(0)
        raise RuntimeError("No pictures could be made (check CF_ACCOUNT_ID / CF_API_TOKEN).")
    imgs = [p or first_ok for p in imgs]
    shots_per_scene = [[x or imgs[i] for x in sh] for i, sh in enumerate(shots_per_scene)]

    thumb_base = os.path.join(WORK, "thumb_base.jpg")
    ti = story.get("thumbnail_image") or {}
    if isinstance(ti, str):
        ti = {"action": ti}
    if not make_image(cast, (ti.get("action") or scenes[-1].get("action", "")) +
                      ". Viral YouTube kids thumbnail: the main character very big and close to the camera on the "
                      "RIGHT half, huge expressive face (shocked, laughing or teary eyes), simple bright soft "
                      "background on the LEFT half, vivid saturated colors, strong rim light, very sharp",
                      "", ti.get("characters"), thumb_base, seed):
        shutil.copy(first_ok, thumb_base)
    thumb = os.path.join(WORK, "thumbnail.jpg")
    make_thumbnail(thumb_base, story.get("thumbnail_text") or title, thumb, L["labels"][category])

    clean_title = re.sub(r"[^\w\sऀ-ॿঀ-৿,।!?-]", "", title).strip()
    page = env(f"PAGE_NAME_{lang.upper()}") or env("PAGE_NAME") or L["page_default"]
    host = ensure_mascot() or thumb_base
    intro = [{"speaker": "narrator", "text": L["intro"].format(title=clean_title)}]
    if str(story.get("mithu_intro", "")).strip():
        intro.append({"speaker": "Mithu", "emotion": "excited", "text": str(story["mithu_intro"]).strip()})
    parts = [{"image": host, "lines": intro,
              "sounds": ["birds"], "mood": "happy", "voices": voices}]
    for img, s, sh in zip(imgs, scenes, shots_per_scene):
        parts.append({"image": img, "shots": sh, "lines": s.get("lines", []), "sounds": s.get("sounds", []),
                      "ambience": s.get("ambience", []), "mood": s.get("mood", "happy"), "voices": voices})
    end_lines = []
    moral = str(story.get("moral", "")).strip()
    if moral:
        end_lines.append({"speaker": "narrator", "emotion": "calm",
                          "text": (f"{L['moral_intro']} {moral}" if category != "funny" else moral)})
    elif story.get("ending_line"):
        end_lines.append({"speaker": "narrator", "text": story["ending_line"]})
    end_img = host if host != thumb_base else (shots_per_scene[-1][-1] if shots_per_scene[-1] else imgs[-1])
    if end_lines:                                   # Lumi Didi tells the lesson, then the quiz, then goodbye
        parts.append({"image": end_img, "lines": end_lines, "sounds": ["birds"], "mood": "happy", "voices": voices})
        end_lines = []
    quiz = story.get("quiz") if isinstance(story.get("quiz"), dict) else {}
    qopts = [str(o).strip() for o in (quiz.get("options") or []) if str(o).strip()][:3]
    try:
        qans = int(str(quiz.get("answer", 0)).strip()[0])
    except Exception:
        qans = 0
    quiz_saved = None
    if quiz.get("question") and len(qopts) == 3 and 0 <= qans < 3:
        quiz_saved = {"label": L["quiz_labels"][qans], "text": qopts[qans]}
        try:
            labs = L["quiz_labels"]
            qimg, aimg = extras.quiz_cards(shots_per_scene[-1][-1] if shots_per_scene[-1] else imgs[-1], FONT,
                                           L["quiz_title"], str(quiz["question"]), qopts, qans, labs,
                                           os.path.join(WORK, "quiz_q.jpg"), os.path.join(WORK, "quiz_a.jpg"))
            read = " ".join(f"{labs[i]}, {o}." for i, o in enumerate(qopts))
            parts.append({"image": qimg, "shots": [qimg, qimg, aimg], "mood": "happy", "voices": voices,
                          "sounds": [], "lines": [
                              {"speaker": "narrator", "emotion": "excited", "text": f"{L['quiz_intro']} {quiz['question']} {read}"},
                              {"speaker": "narrator", "emotion": "calm", "text": L["quiz_count"]},
                              {"speaker": "narrator", "emotion": "happy",
                               "text": L["quiz_answer"].format(lab=labs[qans], ans=qopts[qans])}]})
        except Exception as e:
            log("  quiz skipped:", str(e)[:150])
    words = [(str(w.get("en", "")).strip(), str(w.get("meaning", "")).strip()) for w in (story.get("english_words") or [])
             if isinstance(w, dict) and w.get("en") and w.get("meaning")][:3]
    if len(words) == 3:
        try:
            wimg = extras.words_card(end_img, FONT, L["words_title"], words, os.path.join(WORK, "words.jpg"))
            items = " ".join(L["word_item"].format(en=e, m=m) for e, m in words)
            parts.append({"image": wimg, "mood": "happy", "voices": voices, "sounds": [],
                          "lines": [{"speaker": "narrator", "emotion": "happy", "text": L["words_line"].format(items=items)}]})
        except Exception as e:
            log("  English words skipped:", str(e)[:150])
    if shout_names:
        end_lines.append({"speaker": "narrator", "emotion": "happy",
                          "text": L["shout_line"].format(names=extras.name_list(shout_names, lang))})
    end_lines.append({"speaker": "narrator", "emotion": "happy", "text": L["how_to_join"]})
    if str(story.get("mithu_outro", "")).strip():
        end_lines.append({"speaker": "Mithu", "emotion": "laughing", "text": str(story["mithu_outro"]).strip()})
    end_lines.append({"speaker": "narrator", "text": L["outro"].format(page=page)})
    parts.append({"image": end_img, "lines": end_lines, "sounds": ["birds"], "mood": "happy", "voices": voices})

    video = os.path.join(WORK, "final.mp4")
    build_video(parts, lang, video)
    log(f"Video ready: {duration(video):.0f} seconds")

    tags = [t if t.startswith("#") else "#" + t.replace(" ", "") for t in story.get("hashtags", [])[:15]]
    source = ascii_text(story.get("source", ""))
    description = (f"{title}\n\n{story.get('description', '').strip()}\n\n" + (f"✨ {moral}\n\n" if moral else "")
                   + (f"📖 {source}\n" if source else "") + f"{L['ai_note']}\n\n{' '.join(tags)}")
    part_times, segs = TIMELINE
    chap = extras.chapters_text(part_times, [L["ch_intro"]] + [sc.get("chapter") or f"{k + 1}" for k, sc in
                                                                 enumerate(scenes)] + [L["ch_end"]], L["chapters"])
    yt_description = description.replace(L["ai_note"], (f"{chap}\n\n" if chap else "") + L["ai_note"])

    results = {}
    if DRY_RUN:
        log("DRY RUN - not posting. Files are in the 'work' folder.")
    else:
        try:
            results["facebook"] = post_to_facebook(video, thumb, title, description)
            log("Posted to Facebook:", results["facebook"])
        except Exception as e:
            log("FACEBOOK FAILED:", e)
            results["facebook_error"] = str(e)[:200]
        if youtube_ready():
            try:
                results["youtube"] = post_to_youtube(video, thumb, title, yt_description, tags, lang)
                log("Posted to YouTube:", results["youtube"])
            except Exception as e:
                log("YOUTUBE FAILED:", e)
                results["youtube_error"] = str(e)[:200]
        else:
            log("YouTube secrets not set - skipping YouTube")
        if not results.get("facebook") and not results.get("youtube"):
            raise SystemExit("Posting failed everywhere - see messages above.")

    first = [str(story.get("comment_question", "")).strip()]
    if shout_names:
        first.append(L["shout_comment"].format(names=extras.name_list(shout_names, lang, 10)))
    first.append(L["join_comment"])
    story["comment_question"] = "\n\n".join(x for x in first if x)
    results.update(grow(video, story, title, lang, L, category, tags, results, history, page))
    if shout_ids and results.get("facebook") and not DRY_RUN:
        n = extras.reply_to(shout_ids, L["congrats_reply"].format(link=f"https://www.facebook.com/{results['facebook']}"))
        log(f"  congratulated {n} children/parents under their comments")

    history.append({"date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "lang": lang, "slot": SLOT,
                    "category": category, "title": title, "festival": festival,
                    "quiz": quiz_saved, **results})
    if not MOCK:
        save_history(history)
    extras.telegram(extras.report_text(env(f"PAGE_NAME_{lang.upper()}") or "Little Lumi Stories", title, results, history))


def make_compilation(history):
    """Sunday special: this week's stories (one language) joined into one long video with chapters."""
    global FONT
    now = dt.datetime.now(dt.timezone.utc)
    week = []
    for h in history[-40:]:
        try:
            t = dt.datetime.fromisoformat(str(h.get("date")))
        except Exception:
            continue
        if (now - t.replace(tzinfo=t.tzinfo or dt.timezone.utc)).days <= 7 and h.get("facebook") \
                and h.get("kind") != "compilation":
            week.append(h)
    langs = [h.get("lang") for h in week]
    lang = env("LANGUAGE") if env("LANGUAGE") in LANGS else (max(set(langs), key=langs.count) if langs else "bn")
    items = [h for h in week if h.get("lang") == lang][-12:]
    if len(items) < 3:
        log(f"Weekly compilation: only {len(items)} stories this week - skipped")
        return
    L = LANGS[lang]
    FONT = find_font(lang)
    clips, chapters, frames, t = [], [], [], 0.0
    for k, h in enumerate(items):
        try:
            src, _ = extras.fb_video_source(h["facebook"])
            if not src:
                raise RuntimeError("no video link")
            raw = extras.download(src, os.path.join(WORK, f"raw_{k}.mp4"))
            c = extras.normalize_clip(raw, os.path.join(WORK, f"c_{k:02d}.mp4"))
            os.remove(raw)
            d = duration(c)
            fr = os.path.join(WORK, f"fr_{k}.jpg")
            run(["ffmpeg", "-y", "-ss", f"{min(40, d / 3):.1f}", "-i", c, "-frames:v", "1", fr])
            frames.append(fr)
            chapters.append((t, h.get("title", f"{k + 1}")))
            clips.append(c)
            t += d
            log(f"  added: {h.get('title', '')[:50]} ({d / 60:.1f} min)")
        except Exception as e:
            log(f"  skipped one story: {str(e)[:150]}")
    if len(clips) < 3:
        log("Weekly compilation: not enough videos could be downloaded - skipped")
        return
    lst = os.path.join(WORK, "comp.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.basename(c)}'\n" for c in clips)
    video = os.path.join(WORK, "final.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", video])
    minutes = int(round(t / 60))
    title = L["comp_title"].format(m=minutes, n=len(clips))[:95]
    base = extras.collage(frames, os.path.join(WORK, "thumb_base.jpg"))
    thumb = os.path.join(WORK, "thumbnail.jpg")
    make_thumbnail(base, L["comp_thumb"].format(m=minutes), thumb, L["labels"]["bedtime"])
    chap = L["chapters"] + "\n" + "\n".join(f"{extras.fmt_time(s)} {n[:60]}" for s, n in chapters)
    tags = ["#KidsStories", "#MoralStories", "#BedtimeStories", "#StoryCompilation"]
    description = f"{title}\n\n{chap}\n\n{L['ai_note']}\n\n{' '.join(tags)}"
    log(f"Compilation ready: {minutes} minutes, {len(clips)} stories")
    results = {}
    if not DRY_RUN:
        try:
            results["facebook"] = post_to_facebook(video, thumb, title, description)
            log("Posted compilation to Facebook:", results["facebook"])
        except Exception as e:
            log("FACEBOOK FAILED:", e)
        if youtube_ready() and extras.yt_extra_ok():
            try:
                results["youtube"] = post_to_youtube(video, thumb, title, description, tags, lang)
                log("Posted compilation to YouTube:", results["youtube"])
                extras.yt_add_to_playlist(results["youtube"], f"{L['labels']['bedtime']} | {L['playlist_tail']}", lang)
            except Exception as e:
                log("YouTube compilation skipped:", str(e)[:200])
        history.append({"date": now.isoformat(timespec="minutes"), "lang": lang, "kind": "compilation",
                        "title": title, **results})
        save_history(history)


def grow(video, story, title, lang, L, category, tags, results, history, page):
    """Extra reach after the main post: Reel + Short teaser, first comment, playlist. Never stops the run.
    (Kids videos on YouTube have comments switched off by YouTube, so the question goes only to Facebook.)"""
    out = {}
    part_times, segs = TIMELINE
    teaser = os.path.join(WORK, "teaser.mp4")
    try:
        st, en = extras.pick_window(segs, part_times, story.get("teaser_scene") or 2)
        extras.make_teaser(video, st, en, teaser, FONT, story.get("thumbnail_text") or title, L["cta"], WORK,
                           colors=((255, 225, 0), (255, 60, 120)))
        log(f"Teaser ready ({en - st:.0f} s, from {st:.0f} s)")
    except Exception as e:
        log("  teaser skipped:", str(e)[:200])
        teaser = None
    if DRY_RUN:
        return out
    question = str(story.get("comment_question", "")).strip()
    short_desc = f"{title}\n{L['full_link']} {page}\n{' '.join(tags[:6])}"
    if teaser and env("FB_REELS") != "0":
        try:
            out["fb_reel"] = extras.fb_post_reel(teaser, short_desc)
            log("Posted Facebook Reel:", out["fb_reel"])
        except Exception as e:
            log("  Facebook Reel skipped:", str(e)[:200])
    if teaser and env("INSTAGRAM") == "1":           # only if you switch Instagram on (secret INSTAGRAM = 1)
        try:
            out["ig_reel"] = extras.ig_post_reel(teaser, short_desc)
            log("Posted Instagram Reel:", out["ig_reel"])
        except Exception as e:
            log("  Instagram Reel skipped:", str(e)[:200])
    today = dt.datetime.now(extras.IST).date()
    done_today = any(h.get("coloring") and dt.datetime.fromisoformat(h["date"]).astimezone(extras.IST).date() == today
                     for h in history[-4:] if h.get("date"))
    if results.get("facebook") and env("COLORING") != "0" and not done_today and not CF_QUOTA_OUT:
        try:                                          # printable colouring page of today's main character
            main_c = next((c for c in story.get("characters", []) if c.get("look")), {})
            raw = os.path.join(WORK, "color_raw.jpg")
            prompt = ("black and white coloring book page for small children, clean thick black outlines only, no "
                      "shading, no grey, no colour, pure white background, simple cute shapes, full body: "
                      f"{ascii_text(main_c.get('look', ''))} {ascii_text(main_c.get('name', ''))}, happy pose, "
                      "a few simple background elements")
            with open(raw, "wb") as f:                # keep it portrait (no 16:9 frame)
                f.write(cf_request(CF_MODEL, prompt, w=768, h=1024, seed=random.randint(1, 99999)))
            page_img = extras.coloring_sheet(raw, os.path.join(WORK, "coloring.jpg"), FONT, L["color_title"])
            out["coloring"] = extras.fb_photo(page_img, f"{L['color_msg']}\n\n🎬 {title}")
            log("Posted colouring page:", out["coloring"])
        except Exception as e:
            log("  colouring page skipped:", str(e)[:200])
    if results.get("youtube"):
        try:
            extras.yt_add_to_playlist(results["youtube"], f"{L['labels'][category]} | {L['playlist_tail']}", lang)
            log("  added to YouTube playlist")
        except Exception as e:
            log("  playlist skipped:", str(e)[:200])
        if (teaser and extras.yt_extra_ok() and env("YT_SHORTS") != "0"
                and extras.shorts_today(history) < int(env("YT_SHORTS_PER_DAY") or 2)):
            try:
                desc = f"{title}\n{L['full_link']} https://youtu.be/{results['youtube']}\n{' '.join(tags[:6])}"
                out["yt_short"] = post_to_youtube(teaser, None, f"{title[:80]} #Shorts", desc, tags, lang)
                log("Posted YouTube Short:", out["yt_short"])
            except Exception as e:
                log("  YouTube Short skipped:", str(e)[:200])
    if results.get("youtube") and extras.yt_extra_ok():
        try:                                          # English subtitles: more families can follow
            tr = {str(ln.get("text", "")).strip(): str(ln.get("en", "")).strip()
                  for sc in story.get("scenes", []) for ln in sc.get("lines", []) if ln.get("en")}
            srt = extras.write_srt(segs, tr, os.path.join(WORK, "subs_en.srt"))
            if srt:
                extras.yt_upload_captions(results["youtube"], srt)
                log("  English subtitles added on YouTube")
        except Exception as e:
            log("  subtitles skipped:", str(e)[:160])
    if results.get("facebook") and env("ANNOUNCE") != "0":
        try:                                          # "coming soon" post 2 hours before the evening video
            nxt = extras.next_slot([8, 13, 19], [19])
            if nxt:
                slot, when, day = nxt
                words = f"{extras.DAY_WORDS[lang][day]} {extras.TIME_WORDS[lang][slot.hour]}"
                card = extras.announcement_card(ensure_mascot() or os.path.join(WORK, "thumb_base.jpg"), FONT,
                                                L["ann1"], words, os.path.join(WORK, "announce.jpg"),
                                                colors=((255, 225, 0), (255, 60, 120)))
                extras.fb_schedule_photo(card, L["ann_msg"].format(when=words), when)
                log(f"  'coming soon' post scheduled for {when.strftime('%d %b %H:%M')} India time")
        except Exception as e:
            log("  announcement skipped:", str(e)[:160])
    if question and results.get("facebook"):
        try:
            extras.fb_comment(results["facebook"], question)
            log("  first comment posted on Facebook")
        except Exception as e:
            log("  Facebook comment skipped (needs pages_manage_engagement):", str(e)[:160])
    return out


# ----------------------------------------------------------------- offline test helpers
def mock_story(lang):
    return {
        "title": "लालची बंदर और जादुई आम 🥭", "thumbnail_text": "लालची बंदर का सबक",
        "description": "एक बंदर को मिला जादुई आम का पेड़!\nआप होते तो क्या करते?",
        "hashtags": ["#HindiKahani", "#MoralStories"], "setting": "green jungle by a river, sunny morning",
        "characters": [{"name": "Chiku", "gender": "male", "age": "child", "kind": "animal", "look": "small brown monkey, red cap"},
                       {"name": "Meenu", "gender": "female", "age": "young", "kind": "animal", "look": "white rabbit, pink scarf"},
                       {"name": "Dadi", "gender": "female", "age": "old", "kind": "animal", "look": "old grey elephant, glasses"}],
        "thumbnail_image": {"characters": ["Chiku"], "action": "monkey holding a golden mango"},
        "scenes": [
            {"characters": ["Chiku", "Meenu"], "action": "play", "place": "river bank", "mood": "happy",
             "ambience": ["birds chirping in forest", "river stream"], "lines": [
                {"speaker": "narrator", "text": "एक घने जंगल में चीकू नाम का एक छोटा सा बंदर रहता था।", "emotion": "happy",
                 "sfx": [{"sound": "monkey chattering", "when": "after"}], "shot": "monkey on a tree"},
                {"speaker": "Meenu", "text": "चीकू! चलो नदी में खेलते हैं!", "emotion": "excited",
                 "sfx": [{"sound": "small footsteps running on grass", "when": "during"}], "shot": "rabbit running"},
                {"speaker": "Chiku", "text": "हाँ हाँ, मैं आ रहा हूँ!", "emotion": "laughing",
                 "sfx": [{"sound": "water splash", "when": "after"}], "shot": "monkey jumps in river"}]},
            {"characters": ["Dadi"], "action": "advice", "place": "big tree", "mood": "calm",
             "ambience": ["gentle wind in trees"], "lines": [
                {"speaker": "Dadi", "text": "बच्चों, लालच बुरी बला है।", "emotion": "calm", "sfx": [], "shot": "elephant smiling"}]},
        ],
        "moral": "लालच बुरी बला है।"}


def mock_image(path, seed):
    rnd = random.Random(seed + hash(path) % 1000)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=(20 + y // 30, 25 + y // 25, 40 + y // 18))
    d.rectangle([700, 260, 1100, 640], fill=(50, 45, 40), outline=(10, 10, 10), width=6)
    d.ellipse([rnd.randint(380, 520), 300, 600, 420], fill=(200, 200, 190), outline=(0, 0, 0), width=5)
    d.rectangle([420, 410, 580, 660], fill=(220, 220, 215), outline=(0, 0, 0), width=5)
    img.save(path, quality=90)
    return True


if __name__ == "__main__":
    main()
