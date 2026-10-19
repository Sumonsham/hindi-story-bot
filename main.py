#!/usr/bin/env python3
"""
Hindi Cartoon Story Bot
-----------------------
Every run makes ONE brand-new, original Hindi cartoon story video and posts it
to a Facebook Page:

  1. Google Gemini (free)            -> story, title, description, hashtags
  2. Cloudflare Workers AI (free)    -> cartoon pictures for every scene
  3. Microsoft Edge Hindi voice      -> voiceover (gTTS as backup)
  4. FFmpeg                          -> video with zoom/pan, subtitles, music
  5. Pillow                          -> thumbnail
  6. Facebook Graph API              -> upload to the Page

Settings come from environment variables (GitHub "Secrets"):
  GEMINI_API_KEY, CF_ACCOUNT_ID, CF_API_TOKEN, FB_PAGE_ID, FB_PAGE_TOKEN
Optional:
  VOICE (default hi-IN-SwaraNeural; male: hi-IN-MadhurNeural)
  PAGE_NAME (said at the end of every video)
  GEMINI_MODEL (force a model), DRY_RUN=1 (don't post), MOCK=1 (offline test)
"""
import asyncio
import base64
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import datetime as dt

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ----------------------------------------------------------------- settings
W, H, FPS = 1280, 720, 25
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
HISTORY = os.path.join(HERE, "history.json")
MUSIC_DIR = os.path.join(HERE, "music")

MOCK = os.getenv("MOCK") == "1"
DRY_RUN = MOCK or os.getenv("DRY_RUN") == "1"
VOICE = (os.getenv("VOICE") or "").strip() or "hi-IN-SwaraNeural"
PAGE_NAME = os.getenv("PAGE_NAME", "").strip()

CATEGORIES = {
    "moral": [
        "honesty", "greed and its result", "kindness to others", "hard work",
        "true friendship", "patience", "sharing", "respecting elders",
        "telling lies", "helping the weak", "pride and humility", "saving water",
        "obeying parents", "courage", "gratitude",
    ],
    "animal": [
        "jungle animals", "a clever fox", "a brave little rabbit", "an elephant family",
        "birds in a big tree", "a lazy lion", "a monkey and a crocodile", "farm animals",
        "a thirsty crow", "ants and a grasshopper", "a peacock and a crow",
        "sea creatures", "a lost puppy", "a wise owl",
    ],
    "funny": [
        "a forgetful village man", "a silly king and a clever minister",
        "a greedy shopkeeper tricked", "a lazy servant", "a talking parrot",
        "a funny school day", "a mix-up at a wedding", "a clumsy thief",
        "a boastful wrestler", "a naughty goat", "a magical cooking pot gone wrong",
    ],
}
CATEGORY_HINDI = {"moral": "नैतिक कहानी", "animal": "जानवरों की कहानी", "funny": "मज़ेदार कहानी"}

ART_STYLE = ("colorful 2D cartoon illustration for kids, Indian village or jungle setting, "
             "bright cheerful colors, soft lighting, clean outlines, cute characters, "
             "storybook animation style, wide shot, subject in the center, no text, no letters")


def log(*a):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd[:3])}...\n{r.stderr[-2000:]}")
    return r.stdout


def need_env(name):
    v = os.getenv(name, "").strip()
    if not v:
        sys.exit(f"ERROR: secret {name} is missing. Add it in GitHub > Settings > Secrets > Actions.")
    return v


# ----------------------------------------------------------------- history
def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(items):
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(items[-150:], f, ensure_ascii=False, indent=1)


def pick_category(history):
    # rotate so the 3 daily posts are usually different kinds of stories
    recent = [h.get("category") for h in history[-2:]]
    options = [c for c in CATEGORIES if c not in recent] or list(CATEGORIES)
    cat = random.choice(options)
    return cat, random.choice(CATEGORIES[cat])


# ----------------------------------------------------------------- 1. story (Gemini)
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def gemini_models(key):
    """Models to try, best first. Model names change over time, so we ask Google."""
    tries = []
    if os.getenv("GEMINI_MODEL"):
        tries.append(os.getenv("GEMINI_MODEL"))
    tries.append("gemini-flash-latest")
    try:
        r = requests.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": key},
                         params={"pageSize": 200}, timeout=30)
        names = []
        for m in r.json().get("models", []):
            n = m.get("name", "").replace("models/", "")
            if ("generateContent" in m.get("supportedGenerationMethods", [])
                    and "flash" in n and not any(x in n for x in
                                                 ("image", "tts", "audio", "live", "embed", "exp"))):
                names.append(n)

        def ver(n):
            nums = re.findall(r"\d+(?:\.\d+)?", n)
            return (float(nums[0]) if nums else 0, "lite" not in n, "preview" not in n)
        tries += sorted(names, key=ver, reverse=True)
    except Exception as e:
        log("Could not list Gemini models:", e)
    tries += ["gemini-2.5-flash", "gemini-2.0-flash"]
    seen, out = set(), []
    for t in tries:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def make_story(category, theme, history):
    if MOCK:
        return mock_story()
    key = need_env("GEMINI_API_KEY")
    old_titles = [h["title"] for h in history[-60:]]
    prompt = f"""
You are a top Hindi children's storyteller for a Facebook cartoon story page.
Write ONE brand-new, ORIGINAL Hindi story (Devanagari script, simple everyday Hindi that kids
and families understand). Type: {category} story. Theme: {theme}.
Do NOT retell famous copyrighted stories or use known cartoon characters. Invent new names.
Must be different from these earlier stories: {json.dumps(old_titles, ensure_ascii=False)}

Story rules:
- 9 to 11 scenes. Each scene's narration is 2-4 short spoken sentences (35-60 Hindi words).
- Strong hook in scene 1, a problem, a twist, and a happy or funny ending.
- Warm storyteller tone, some dialogue. Suitable for children. No violence or scary content.
- Total spoken length about 3 minutes.
- 2 to 4 main characters only, each with a clearly different look. Every picture must show
  exactly what that scene's narration says (same characters, same objects, same action).

Return ONLY JSON with exactly these keys:
{{
 "title": "catchy Hindi title (max 60 characters) with 1 emoji",
 "thumbnail_text": "2-4 big punchy Hindi words for the thumbnail",
 "description": "3-4 line engaging Hindi description that makes people want to watch, ending with a question to the viewer",
 "hashtags": ["10 to 14 popular hashtags mixing Hindi and English, e.g. #HindiKahani #MoralStories #CartoonStory"],
 "setting": "ENGLISH description of the ONE main place where the story happens (landscape, buildings, plants, colors, time of day). Reused in every picture",
 "characters": [{{"name": "the character's Hindi name written in English letters", "look": "ENGLISH, very specific, never-changing look: species/age, body size, exact colors of fur/skin/hair, clothes with exact colors, one special accessory. 20-35 words"}}],
 "thumbnail_image": {{"characters": ["names shown"], "action": "ENGLISH: the most exciting, emotional moment, big expressive faces"}},
 "scenes": [{{"narration": "Hindi narration", "characters": ["names of the characters VISIBLE in this picture, exactly as in the characters list"], "action": "ENGLISH: exactly what the narration of THIS scene describes happening: who does what, poses, facial expressions, important objects", "place": "ENGLISH: where in the setting, plus anything new in this scene"}}],
 "moral": "one short Hindi line: the lesson (or the joke's punchline for funny stories)"
}}
"""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"},
    }
    last_err = None
    for model in gemini_models(key):
        for attempt in range(2):
            try:
                log(f"Writing story with {model} ...")
                r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent",
                                  headers={"x-goog-api-key": key}, json=body, timeout=180)
                if r.status_code in (404, 400):
                    raise LookupError(r.text[:300])
                if r.status_code == 429:
                    raise RuntimeError("rate limit: " + r.text[:200])
                r.raise_for_status()
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
                story = json.loads(text)
                assert story.get("title") and len(story.get("scenes", [])) >= 5
                return story
            except LookupError as e:
                last_err = e
                break  # model not available -> next model
            except Exception as e:
                last_err = e
                log("  retrying:", str(e)[:200])
                time.sleep(20)
    raise RuntimeError(f"Gemini failed: {last_err}")


# ----------------------------------------------------------------- 2. pictures (Cloudflare)
# Main model draws straight in 16:9 and can copy characters from a reference picture,
# so every scene shows the SAME characters. The older model is only a backup.
CF_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
CF_BACKUP = "@cf/black-forest-labs/flux-1-schnell"


def ascii_text(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\x20-\x7E]", " ", str(s))).strip()


def fit(img, w=W, h=H):
    """Show the WHOLE picture in a w x h frame (nothing cut). Empty sides get a soft
    blurred copy of the picture, like TV news does with phone videos."""
    img = img.convert("RGB")
    if abs(img.width / img.height - w / h) < 0.03:
        return img.resize((w, h), Image.LANCZOS)
    s = max(w / img.width, h / img.height)
    bg = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    l, t = (bg.width - w) // 2, (bg.height - h) // 2
    bg = bg.crop((l, t, l + w, t + h)).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (w, h), (0, 0, 0)), 0.25)
    s = min(w / img.width, h / img.height)
    fg = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return bg


class Cast:
    """Fixed character descriptions + one reference picture shared by every scene."""

    def __init__(self, story):
        self.setting = ascii_text(story.get("setting", ""))
        self.chars = {}
        for c in story.get("characters", []) or []:
            if isinstance(c, dict) and c.get("name"):
                self.chars[ascii_text(c["name"]).lower()] = (ascii_text(c["name"]), ascii_text(c.get("look", "")))
        self.ref = None  # path of the character sheet (small jpg)

    def pick(self, names):
        out = []
        for n in names or []:
            k = ascii_text(n).lower()
            hit = self.chars.get(k) or next((v for kk, v in self.chars.items() if k and (k in kk or kk in k)), None)
            if hit and hit not in out:
                out.append(hit)
        return out or list(self.chars.values())

    def describe(self, chosen):
        return " ".join(f"{name}: {look}." for name, look in chosen)

    def scene_prompt(self, action, place, names, use_ref):
        # also add anyone the action mentions by name, so nobody is left out of the picture
        low = ascii_text(action).lower()
        names = list(names or []) + [n for n, _ in self.chars.values() if n.lower() in low]
        chosen = self.pick(names)
        who = self.describe(chosen)
        p = (f"{ART_STYLE}. Setting: {self.setting}. {ascii_text(place)}. "
             f"Characters in this picture (draw ONLY these, each exactly as described): {who} "
             f"What is happening: {ascii_text(action)}.")
        if use_ref:
            p = ("Image 0 is the character reference sheet. Draw the same characters with exactly the same "
                 "faces, body shapes, colors and clothes as in image 0, but in a brand-new full scene "
                 "with a complete background (not a reference sheet, no white background). " + p)
        return p


def cf_request(model, prompt, ref_path=None, w=1280, h=720, seed=None):
    acct, token = need_env("CF_ACCOUNT_ID"), need_env("CF_API_TOKEN")
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


def make_character_sheet(cast, path, seed):
    """One picture with all main characters standing side by side. Used as reference."""
    if MOCK:
        return mock_image("sheet", path, seed)
    prompt = (f"{ART_STYLE}. Character reference sheet: all main characters standing side by side, "
              f"full body, facing the viewer, plain light background, evenly lit. "
              f"{cast.describe(list(cast.chars.values()))}")
    for attempt in range(3):
        try:
            data = cf_request(CF_MODEL, prompt, w=1024, h=576, seed=seed)
            with open(path + ".raw", "wb") as f:
                f.write(data)
            im = Image.open(path + ".raw").convert("RGB")
            im.thumbnail((508, 508))          # model wants reference images under 512x512
            im.save(path, quality=92)
            cast.ref = path
            return True
        except Exception as e:
            log(f"  character sheet attempt {attempt + 1} failed: {str(e)[:300]}")
            time.sleep(6 * (attempt + 1))
    return False


def make_image(cast, action, place, names, path, seed):
    if MOCK:
        return mock_image(action, path, seed)
    tries = []
    if cast.ref:
        tries.append((CF_MODEL, cast.scene_prompt(action, place, names, True), cast.ref))
    tries.append((CF_MODEL, cast.scene_prompt(action, place, names, False), None))
    tries.append((CF_BACKUP, cast.scene_prompt(action, place, names, False)[:1500], None))
    for attempt, (model, prompt, ref) in enumerate(tries):
        try:
            save_picture(cf_request(model, prompt, ref, seed=seed), path)
            return True
        except Exception as e:
            log(f"  picture attempt {attempt + 1} ({model.split('/')[-1]}) failed: {str(e)[:300]}")
            time.sleep(6 * (attempt + 1))
    return False


# ----------------------------------------------------------------- 3. voice
async def _edge(text, out):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate="-4%").save(out)


def make_voice(text, out):
    if MOCK:
        return mock_voice(text, out)
    for attempt in range(3):
        try:
            asyncio.run(_edge(text, out))
            if os.path.getsize(out) > 1000:
                return
        except Exception as e:
            log(f"  edge voice attempt {attempt + 1} failed: {str(e)[:150]}")
            time.sleep(5)
    log("  using backup voice (gTTS)")
    from gtts import gTTS
    gTTS(text, lang="hi").save(out)


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", path]).strip())


# ----------------------------------------------------------------- fonts
def find_font():
    cands = [os.getenv("FONT_PATH", "")]
    cands += glob.glob("/usr/share/fonts/**/NotoSansDevanagari-Bold.ttf", recursive=True)
    cands += glob.glob(os.path.join(HERE, "fonts", "*.ttf"))
    cands += glob.glob("/usr/share/fonts/**/NotoSansDevanagari*.tt*", recursive=True)
    cands += glob.glob("/usr/share/fonts/**/*Lohit*Devanagari*.ttf", recursive=True)
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit("ERROR: Hindi font not found (install fonts-noto-core).")


FONT = None


def font(size):
    return ImageFont.truetype(FONT, size, layout_engine=ImageFont.Layout.RAQM)


# ----------------------------------------------------------------- 4. thumbnail
def make_thumbnail(base_img, text, out, label):
    img = Image.open(base_img).convert("RGB").resize((W, H))
    # darken bottom for readability
    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    for y in range(H // 2, H):
        d.line([(0, y), (W, y)], fill=int(190 * (y - H / 2) / (H / 2)))
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, shade)
    draw = ImageDraw.Draw(img)

    text = text.strip()
    words = text.split()
    lines = [text] if len(words) <= 2 else [" ".join(words[:len(words) // 2 + len(words) % 2]),
                                              " ".join(words[len(words) // 2 + len(words) % 2:])]
    size = 150
    while size > 50:
        f = font(size)
        if all(draw.textlength(l, font=f) <= W - 90 for l in lines) and size * 1.25 * len(lines) <= H * 0.55:
            break
        size -= 6
    f = font(size)
    lh = int(size * 1.25)
    y = H - 40 - lh * len(lines)
    colors = [(255, 230, 0), (255, 255, 255)]
    for i, l in enumerate(lines):
        x = (W - draw.textlength(l, font=f)) / 2
        draw.text((x, y + i * lh), l, font=f, fill=colors[i % 2],
                  stroke_width=max(6, size // 14), stroke_fill=(0, 0, 0))
    # small red tag
    lf = font(38)
    tw = draw.textlength(label, font=lf)
    draw.rounded_rectangle([28, 26, 28 + tw + 40, 26 + 66], radius=14, fill=(220, 20, 40))
    draw.text((48, 30), label, font=lf, fill=(255, 255, 255))
    img.save(out, quality=92)


# ----------------------------------------------------------------- 5. video
def ass_time(t):
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def split_subs(text, max_len=46):
    parts = [p.strip() for p in re.split(r"(?<=[।!?,\.])\s+", text) if p.strip()]
    out = []
    for p in parts:
        words, cur = p.split(), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_len:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            out.append(cur)
    return out


def write_ass(segments, path):
    """segments: list of (start, dur, text)"""
    family = "Noto Sans Devanagari"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{family},54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,38,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for start, dur, text in segments:
        chunks = split_subs(text)
        total = sum(len(c) for c in chunks) or 1
        t = start
        for c in chunks:
            d = dur * len(c) / total
            lines.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t + d)},Default,,0,0,0,,{c}")
            t += d
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n")


def scene_clip_simple(img, audio, out, idx):
    dur = duration(audio) + 0.7
    frames = int(dur * FPS) + 1
    # alternate between slow zoom-in, zoom-out and gentle pans so it feels animated
    z_in = "min(1+0.0005*on,1.07)"
    z_out = "max(1.07-0.0005*on,1)"
    moves = [
        (z_in, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        ("1.06", f"(iw-iw/zoom)*on/{frames}", "ih/2-(ih/zoom/2)"),
        (z_out, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        ("1.06", f"(iw-iw/zoom)*(1-on/{frames})", "ih/2-(ih/zoom/2)"),
    ]
    z, x, y = moves[idx % len(moves)]
    vf = (f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur - 0.4:.2f}:d=0.4,format=yuv420p")
    run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", audio, "-vf", vf,
         "-af", "apad", "-t", f"{dur:.2f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", out])
    return dur


# ----------------------------------------------------------------- 5a. free "2.5D" animation
# The character is cut out of the picture (rembg, a free cartoon cut-out model), the hole
# behind it is painted over, and then background and character move separately:
# slow camera drift on the background, the character floats/breathes in front of it,
# plus soft floating light specks. Falls back to the simple zoom if anything goes wrong.
_REMBG = None


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
    """Returns (background RGB uint8, foreground RGBA uint8) or None if no clear character."""
    import numpy as np
    import cv2
    from rembg import remove
    pic = Image.open(img_path).convert("RGB").resize((W, H))
    alpha = np.array(remove(pic, session=cutout_session(), only_mask=True).convert("L").resize((W, H)))
    cover_part = (alpha > 128).mean()
    if cover_part < 0.03 or cover_part > 0.60:      # nothing found, or "everything" is foreground
        return None
    rgb = np.array(pic)
    hole = cv2.dilate((alpha > 40).astype("uint8") * 255, np.ones((25, 25), "uint8"))
    small = cv2.inpaint(cv2.resize(rgb, (W // 2, H // 2)), cv2.resize(hole, (W // 2, H // 2)), 9,
                        cv2.INPAINT_TELEA)
    bg = cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC)
    bg = np.where(hole[..., None] > 0, cv2.GaussianBlur(bg, (0, 0), 3), rgb)  # keep real pixels away from the hole
    fg = np.dstack([rgb, cv2.GaussianBlur(alpha, (0, 0), 1.2)])
    return bg, fg


def scene_clip(img, audio, out, idx):
    if os.getenv("SIMPLE_MOTION") == "1" or MOCK and os.getenv("TEST_ANIM") != "1":
        return scene_clip_simple(img, audio, out, idx)
    try:
        return scene_clip_animated(img, audio, out, idx)
    except Exception as e:
        log(f"  animation skipped for this scene ({str(e)[:150]}) - using simple motion")
        return scene_clip_simple(img, audio, out, idx)


def scene_clip_animated(img, audio, out, idx):
    import math
    import numpy as np
    import cv2
    layers = split_layers(img)
    if layers is None:
        raise RuntimeError("no character found to animate")
    bg, fg = layers
    dur = duration(audio) + 0.7
    n = int(dur * FPS) + 1
    rnd = random.Random(idx * 101 + 7)
    direction = 1 if idx % 2 == 0 else -1
    # floating light specks
    specks = [(rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(1.5, 4.0), rnd.uniform(6, 22),
               rnd.uniform(0, 6.28)) for _ in range(26)]
    fg_rgb = fg[..., :3].astype("float32")
    fg_a = fg[..., 3].astype("float32") / 255.0
    ys, xs = np.nonzero(fg_a > 0.5)
    cx, cy = float(xs.mean()), float(ys.max())              # character's feet = pivot for "breathing"
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", audio, "-af", "apad", "-t", f"{dur:.2f}",
         "-vf", f"fade=t=in:st=0:d=0.35,fade=t=out:st={dur - 0.35:.2f}:d=0.35,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", out],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    bg_bgr = cv2.cvtColor(bg, cv2.COLOR_RGB2BGR)
    fg_bgr = cv2.cvtColor(fg_rgb.astype("uint8"), cv2.COLOR_RGB2BGR).astype("float32")
    try:
        for f in range(n):
            t = f / max(n - 1, 1)                        # 0 -> 1 over the scene
            ease = 0.5 - 0.5 * math.cos(math.pi * t)
            sec = f / FPS
            # background: slow zoom + drift (camera)
            bz = 1.03 + 0.03 * ease
            bdx = direction * (ease - 0.5) * 30
            Mb = cv2.getRotationMatrix2D((W / 2, H / 2), 0, bz)
            Mb[0, 2] += bdx
            frame = cv2.warpAffine(bg_bgr, Mb, (W, H), borderMode=cv2.BORDER_REFLECT)
            # character: moves more than background (depth), gentle bob + breathing
            fz = 1.03 + 0.045 * ease + 0.008 * math.sin(sec * 2.4)
            fdx = direction * (ease - 0.5) * 55
            fdy = -4.0 * abs(math.sin(sec * 1.7))
            Mf = cv2.getRotationMatrix2D((cx, cy), 0.6 * math.sin(sec * 1.3), fz)
            Mf[0, 2] += fdx + (W / 2 - cx) * (bz - 1)
            Mf[1, 2] += fdy
            fgw = cv2.warpAffine(fg_bgr, Mf, (W, H))
            aw = cv2.warpAffine(fg_a, Mf, (W, H))[..., None]
            frame = (frame.astype("float32") * (1 - aw) + fgw * aw)
            # soft light specks floating upward
            glow = np.zeros((H, W), "float32")
            for (x0, y0, r, speed, ph) in specks:
                x = (x0 + 12 * math.sin(sec * 0.8 + ph)) % W
                y = (y0 - speed * sec) % H
                cv2.circle(glow, (int(x), int(y)), int(r), 0.5 + 0.5 * math.sin(sec * 2 + ph), -1, cv2.LINE_AA)
            glow = cv2.GaussianBlur(glow, (0, 0), 2.2)[..., None]
            frame = frame + glow * np.array([200, 240, 255], "float32") * 0.55
            ffmpeg.stdin.write(np.clip(frame, 0, 255).astype("uint8").tobytes())
        ffmpeg.stdin.close()
    except Exception:
        ffmpeg.kill()
        raise
    if ffmpeg.wait() != 0:
        raise RuntimeError(ffmpeg.stderr.read().decode()[-500:])
    return dur


def build_video(parts, out):
    """parts: list of (image, narration_text). Returns final mp4 path."""
    clips, segs, t = [], [], 0.0
    for i, (img, text) in enumerate(parts):
        a = os.path.join(WORK, f"voice_{i:02d}.mp3")
        log(f"Voice + clip {i + 1}/{len(parts)}")
        make_voice(text, a)
        c = os.path.join(WORK, f"clip_{i:02d}.mp4")
        d = scene_clip(img, a, c, i)
        segs.append((t + 0.15, d - 0.6, text))
        clips.append(c)
        t += d
    lst = os.path.join(WORK, "clips.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.basename(c)}'\n" for c in clips)
    joined = os.path.join(WORK, "joined.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])

    subs = os.path.join(WORK, "subs.ass")
    write_ass(segs, subs)
    fontdir = os.path.dirname(FONT)
    vf = f"ass=subs.ass:fontsdir={fontdir}:shaping=complex"
    music = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.mp3")) + glob.glob(os.path.join(MUSIC_DIR, "*.m4a")))
    cmd = ["ffmpeg", "-y", "-i", "joined.mp4"]
    if music:
        cmd += ["-stream_loop", "-1", "-i", random.choice(music),
                "-filter_complex",
                f"[0:v]{vf}[v];[1:a]volume=0.10[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", os.path.abspath(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=WORK)
    if r.returncode != 0:
        raise RuntimeError("final render failed:\n" + r.stderr[-2000:])
    return out


# ----------------------------------------------------------------- 6. Facebook
def post_to_facebook(video, thumb, title, description):
    page, token = need_env("FB_PAGE_ID"), need_env("FB_PAGE_TOKEN")
    url = f"https://graph-video.facebook.com/{page}/videos"
    for attempt in range(3):
        try:
            with open(video, "rb") as v, open(thumb, "rb") as th:
                r = requests.post(url, data={"access_token": token, "title": title,
                                             "description": description, "published": "true"},
                                  files={"source": ("story.mp4", v, "video/mp4"),
                                         "thumb": ("thumb.jpg", th, "image/jpeg")},
                                  timeout=900)
            js = r.json()
            if r.ok and js.get("id"):
                return js["id"]
            err = js.get("error", {})
            msg = err.get("message", r.text[:300])
            if err.get("code") in (190, 200, 10, 100):  # token / permission problems: don't retry
                raise SystemExit(f"Facebook refused the post: {msg}\n"
                                 "-> Check FB_PAGE_ID and FB_PAGE_TOKEN (see setup guide step 4).")
            raise RuntimeError(msg)
        except SystemExit:
            raise
        except Exception as e:
            log(f"  upload attempt {attempt + 1} failed: {str(e)[:200]}")
            time.sleep(30)
    raise RuntimeError("Facebook upload failed 3 times")


# ----------------------------------------------------------------- main
def main():
    global FONT
    FONT = find_font()
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    history = load_history()
    cat, theme = pick_category(history)
    log(f"Story type: {cat} / {theme}")

    story = make_story(cat, theme, history)
    title = story["title"].strip()[:95]
    log("Title:", title)
    with open(os.path.join(WORK, "story.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=1)

    cast = Cast(story)
    seed = random.randint(1, 1_000_000)   # same seed for every picture = steadier look
    scenes = story["scenes"][:12]
    log("Characters:", "; ".join(n for n, _ in cast.chars.values()))

    # one reference picture of all characters, reused for every scene
    log("Character sheet")
    if not make_character_sheet(cast, os.path.join(WORK, "characters.jpg"), seed):
        log("  no character sheet - pictures will use text descriptions only")

    # pictures
    imgs, last_ok = [], None
    for i, s in enumerate(scenes):
        p = os.path.join(WORK, f"scene_{i:02d}.jpg")
        log(f"Picture {i + 1}/{len(scenes)}")
        if make_image(cast, s.get("action") or s.get("image", ""), s.get("place", ""),
                      s.get("characters"), p, seed):
            last_ok = p
        elif last_ok:
            shutil.copy(last_ok, p)  # reuse previous picture rather than fail
        else:
            p = None
        imgs.append(p)
    first_ok = next((p for p in imgs if p), None)
    if not first_ok:
        raise RuntimeError("No pictures could be made (check CF_ACCOUNT_ID / CF_API_TOKEN).")
    imgs = [p or first_ok for p in imgs]

    thumb_base = os.path.join(WORK, "thumb_base.jpg")
    ti = story.get("thumbnail_image") or {}
    if isinstance(ti, str):
        ti = {"action": ti}
    if not make_image(cast, (ti.get("action") or scenes[0].get("action", "")) +
                      ", dramatic, very expressive faces, characters large and close to the camera",
                      "", ti.get("characters"), thumb_base, seed):
        shutil.copy(first_ok, thumb_base)
    thumb = os.path.join(WORK, "thumbnail.jpg")
    make_thumbnail(thumb_base, story.get("thumbnail_text") or title, thumb, CATEGORY_HINDI[cat])

    # narration: intro + scenes + outro
    clean_title = re.sub(r"[^\w\sऀ-ॿ,।!?-]", "", title).strip()
    moral = story.get("moral", "").strip()
    outro = (f"तो बच्चों, इस कहानी से हमें यह सीख मिलती है: {moral} " if cat != "funny" and moral
             else (moral + " " if moral else ""))
    outro += ("कहानी अच्छी लगी तो लाइक कीजिए, शेयर कीजिए, और ऐसी ही कहानियों के लिए "
              + (f"{PAGE_NAME} " if PAGE_NAME else "हमारे पेज ") + "को फॉलो ज़रूर कीजिए!")
    parts = [(thumb_base, f"आज की कहानी है, {clean_title}।")]
    parts += [(img, s["narration"]) for img, s in zip(imgs, scenes)]
    parts += [(imgs[-1], outro)]

    video = os.path.join(WORK, "final.mp4")
    build_video(parts, video)
    log(f"Video ready: {duration(video):.0f} seconds")

    tags = " ".join(t if t.startswith("#") else "#" + t.replace(" ", "")
                    for t in story.get("hashtags", [])[:15])
    description = f"{title}\n\n{story.get('description', '').strip()}\n\n"
    if moral:
        description += f"✨ {moral}\n\n"
    description += tags

    if DRY_RUN:
        log("DRY RUN - not posting. Files are in the 'work' folder.")
        post_id = "dry-run"
    else:
        log("Uploading to Facebook ...")
        post_id = post_to_facebook(video, thumb, title, description)
        log("Posted! Facebook video id:", post_id)

    history.append({"date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                    "category": cat, "title": title, "post_id": post_id})
    if not MOCK:
        save_history(history)


# ----------------------------------------------------------------- offline test helpers
def mock_story():
    return {
        "title": "लालची बंदर और जादुई आम 🥭",
        "thumbnail_text": "लालची बंदर का सबक",
        "description": "एक बंदर को मिला जादुई आम का पेड़! लेकिन उसकी लालच ने क्या कर दिया?\nपूरी कहानी देखिए। आप होते तो क्या करते?",
        "hashtags": ["#HindiKahani", "#MoralStories", "#CartoonStory", "#बच्चोंकीकहानी"],
        "setting": "green jungle by a river",
        "characters": [{"name": "Chiku", "look": "a small brown monkey with a red cap"}],
        "thumbnail_image": {"characters": ["Chiku"], "action": "monkey holding a golden mango"},
        "scenes": [
            {"narration": "एक घने जंगल में चीकू नाम का एक छोटा सा बंदर रहता था। वह बहुत चंचल था, लेकिन थोड़ा लालची भी था।", "characters": ["Chiku"], "action": "monkey in jungle", "place": "tree"},
            {"narration": "एक दिन उसे नदी किनारे एक चमकता हुआ आम का पेड़ मिला। पेड़ बोला, रोज़ सिर्फ़ एक आम तोड़ना!", "characters": ["Chiku"], "action": "golden tree", "place": "river"},
            {"narration": "चीकू ने सोचा, एक क्यों? मैं तो सारे आम तोड़ लूँगा! और फिर क्या हुआ, सुनिए।", "characters": ["Chiku"], "action": "monkey thinking", "place": "tree"},
        ],
        "moral": "लालच बुरी बला है, जितना मिले उसमें खुश रहना चाहिए।",
    }


def mock_image(desc, path, seed):
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    c1 = [rnd.randint(40, 200) for _ in range(3)]
    for y in range(H):
        d.line([(0, y), (W, y)], fill=tuple(int(c * (0.6 + 0.6 * y / H)) for c in c1))
    for _ in range(12):
        x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.randint(30, 140)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(rnd.randint(80, 255) for _ in range(3)))
    img.filter(ImageFilter.GaussianBlur(2)).save(path, quality=90)
    return True


def mock_voice(text, out):
    secs = max(2.5, len(text) / 14)
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=330:duration={secs:.1f}",
         "-af", "volume=0.15", "-ar", "44100", out])


if __name__ == "__main__":
    main()
