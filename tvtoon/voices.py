"""character voices: a matching voice for every character, cached per line (no line is spoken twice).

The voice ENGINE is chosen explicitly (TVTOON_VOICE, see engine()): Chirp 3 HD only, Gemini only, or the bot's
existing recordings only - never a silent mix. Without a voice the line is returned as None and the scene shows it
honestly as a silent subtitle (no fake mouth movement).
Women and girls always get FEMALE voices, men and boys male ones."""
import hashlib
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "work", "tvtoon_voices")

# Gemini voice + how to perform, per character (female voices for women and girls)
VOICE = {
    "haripada": ("Orus", "a kind, slightly nervous Bengali village shopkeeper in his forties, warm male voice"),
    "gopal_kaku": ("Charon", "a tall thin village postman in his forties, dry humorous male voice"),
    "lumi_didi": ("Kore", "a bright caring young Bengali woman teacher of twenty-four, clear young female voice"),
    "malati": ("Aoede", "a plump cheerful Bengali fish-seller woman, loud happy female voice"),
    "nibaran_dadu": ("Sadaltager", "a very old Bengali grandfather in his seventies, slightly shaky male voice"),
    "haran_kaka": ("Algenib", "a grumpy old Bengali farmer, gravelly old male voice"),
    "sarala_thakuma": ("Gacrux", "a gentle Bengali grandmother of seventy, soft old female voice"),
    "annapurna_pishi": ("Vindemiatrix", "a strict old Bengali aunt, firm old female voice"),
    "bappa": ("Puck", "a cheeky nine-year-old Bengali BOY, high young boy's voice"),
    "titu": ("Puck", "a shy eight-year-old Bengali BOY with round glasses, soft high boy's voice"),
    "mili": ("Leda", "a sweet eight-year-old Bengali GIRL, high young girl's voice"),
    "piu": ("Laomedeia", "a tiny energetic six-year-old Bengali GIRL, very high excited girl's voice"),
    "narrator": ("Algenib", "the storyteller of a Bengali horror tale: a deep, grave, low male voice, slow, telling it at night"),
    # horror cast (women and girls: female voices)
    "petni": ("Achernar", "a thin, echoing, sad female ghost voice"), "shakchunni": ("Despina", "a sweet then hissing female ghost"),
    "brahmadaitya": ("Rasalgethi", "a deep booming old male ghost"), "mechho_bhoot": ("Puck", "a nasal whiny male ghost"),
    "ojha": ("Sadaltager", "a commanding old exorcist, deep male"), "shibu_dadu": ("Algieba", "a very old husky male storyteller"),
    "abhishek": ("Orus", "a confident young man from Kolkata"), "riya": ("Kore", "a sharp young college girl"),
    "parul": ("Aoede", "a warm brave village wife"), "mokkhoda": ("Gacrux", "a trembling very old grandmother"),
    "bhattacharya": ("Iapetus", "a nervous round priest, nasal male"), "ramu_chowkidar": ("Alnilam", "a loud night watchman"),
    "sayan": ("Puck", "a scared fifteen-year-old boy"), "kishori": ("Leda", "a quiet brave twelve-year-old girl"),
}
FEMALE = {"lumi_didi", "malati", "sarala_thakuma", "annapurna_pishi", "mili", "piu", "petni", "shakchunni", "riya", "parul",
          "mokkhoda", "kishori"}

# existing recordings of the bot (text -> file, start, end): only voices that fit the character (male)
RECORDED = {
    ("haripada", "কেউ ব্রেক কষেনি?"): ("s_1112_032431_15.ogg", 0.0, 1.75),
    ("nibaran_dadu", "চুপ কিশোরী!"): ("s_1111_093655_7.ogg", 0.0, 1.45),
    ("nibaran_dadu", "একটি টু শব্দ কোরো না।"): ("s_1111_093655_7.ogg", 3.0, 5.05),
    ("nibaran_dadu", "ওঁর নাম মুখে আনলে উনি টের পেয়ে যান।"): ("s_1111_093655_7.ogg", 6.35, 9.45),
    ("nibaran_dadu", "বোকামি কোরো না কিশোরী!"): ("s_1111_093655_7.ogg", 10.5, 12.15),
    ("haripada", "আমার দিকে তাকা!"): ("s_1112_032431_15.ogg", 16.6, 18.2),
    # horror cast: the bot's own recordings of its stories (Orus = Abhishek, Sadaltager = the ojha, Algenib = narrator)
    ("abhishek", "চল সায়ন, হেলমেটের স্ট্র্যাপটা বেঁধে নে ঝটপট।"): ("s_1112_032409_14.ogg", 0.0, 3.3),
    ("abhishek", "কেউ ব্রেক কষেনি?"): ("s_1112_032431_15.ogg", 0.0, 1.75),
    ("abhishek", "আমার দিকে তাকা!"): ("s_1112_032431_15.ogg", 16.6, 18.2),
    ("ojha", "চুপ কিশোরী!"): ("s_1111_093655_7.ogg", 0.0, 1.45),
    ("ojha", "একটি টু শব্দ কোরো না।"): ("s_1111_093655_7.ogg", 3.0, 5.05),
    ("ojha", "ওঁর নাম মুখে আনলে উনি টের পেয়ে যান।"): ("s_1111_093655_7.ogg", 6.35, 9.45),
    ("ojha", "বোকামি কোরো না কিশোরী!"): ("s_1111_093655_7.ogg", 10.5, 12.15),
    ("narrator", "একটা দীর্ঘশ্বাসের শব্দে কুটিরের প্রদীপটা দপ করে নিভে গেল।"): ("s_1111_093422_1.ogg", 0.0, 4.95),
    ("narrator", "এক পলকে সব শান্ত।"): ("s_1111_093422_1.ogg", 5.45, 7.9),
}


CHILD = {"bappa", "titu", "mili", "piu", "kishori"}


def engine():
    """TVTOON_VOICE = chirp | gemini | recorded | none.
    chirp    -> ONLY Google Chirp 3 HD (GOOGLE_TTS_KEY, the free monthly share, the bot's own cap); nothing else is used,
                not even the bot's old recordings (they were made with Gemini)
    gemini   -> the free Gemini voice (GEMINI_TTS_KEY)
    recorded -> only the bot's existing recordings (offline test)
    default (the normal story mode): gemini when GEMINI_TTS_KEY is set, else recorded. The owner's rule (23 Nov 2026):
    TESTS use ONLY Chirp (the test workflow sets TVTOON_VOICE=chirp); the normal story mode uses the Gemini voice."""
    e = (os.environ.get("TVTOON_VOICE") or "").strip().lower()
    if e in ("chirp", "gemini", "recorded", "none"):
        return e
    return "gemini" if os.environ.get("GEMINI_TTS_KEY") else "recorded"


def _key(cid, text, eng):
    return hashlib.sha1(f"{eng}|{cid}|{text}".encode("utf-8")).hexdigest()[:16]


def line(cid, text, emotion="neutral", log=print):
    """-> (wav path or None, how)"""
    cid = cid.split("__")[0]                                   # a ghost in its human disguise keeps its own voice
    eng = engine()
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f"{cid}_{eng}_{_key(cid, text, eng)}.wav")
    if os.path.exists(out) and os.path.getsize(out) > 2000:
        return out, f"cached ({eng})"
    voice, who = VOICE.get(cid, ("Kore" if cid in FEMALE else "Orus", "a Bengali speaker"))
    if eng == "recorded":
        rec = RECORDED.get((cid, text))
        src = os.path.join(ROOT, "assets", "voice_samples", rec[0]) if rec else None
        if src and os.path.exists(src):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(rec[1]), "-t", str(rec[2] - rec[1]), "-i", src,
                            "-ac", "1", "-ar", "24000", out], check=True)
            return out, "existing recording (bot's own voice)"
        return None, "NO VOICE (no recording of this line here) - silent subtitle"
    if eng == "chirp":
        if not os.environ.get("GOOGLE_TTS_KEY"):
            return None, "NO VOICE (Chirp key GOOGLE_TTS_KEY not set) - silent subtitle"
        try:
            import extras
            raw = out + ".chirp.wav"
            usage = os.path.join(ROOT, "assets", "tts_usage.json")
            if extras.chirp_tts(text, voice, raw, 24000, usage, "bn"):
                f = float(os.environ.get("TVTOON_CHILD_PITCH", "1.12")) if cid in CHILD else 1.0
                af = (f"asetrate=24000*{f:.3f},aresample=24000,atempo={1 / f:.3f}" if f != 1.0 else "anull")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-af", af, "-ac", "1", "-ar", "24000", out], check=True)
                os.remove(raw)
                return out, f"chirp {voice}" + (" (child: pitch raised)" if cid in CHILD else "")
            return None, "NO VOICE (Chirp refused or the monthly share is used up) - silent subtitle"
        except Exception as e:
            log(f"  Chirp voice for {cid} failed: {str(e)[:120]}")
            return None, "NO VOICE (Chirp error) - silent subtitle"
    if eng == "gemini" and os.environ.get("GEMINI_TTS_KEY"):
        try:
            import extras
            style = f"{who}. Speak Bengali naturally, emotion: {emotion}. Like a Bengali TV cartoon, clear and lively."
            if extras.tts_gemini(text, voice, style, "Bengali", out, sr=24000, max_tries=1):
                return out, f"gemini voice {voice}"
        except Exception as e:
            log(f"  voice for {cid} failed: {str(e)[:120]}")
    return None, f"NO VOICE ({eng}) - silent subtitle"


def report():
    return {"engine": engine(), "voices": {c: {"voice": v[0], "female": c in FEMALE} for c, v in VOICE.items()},
            "rule": "women and girls always get female voices (the same names are female in Chirp 3 HD and Gemini)",
            "keys": "chirp: GOOGLE_TTS_KEY; gemini: GEMINI_TTS_KEY"}
