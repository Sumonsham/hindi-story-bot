"""Growth features shared by both story bots (the same file is used in both repos):

  * a 9:16 teaser (Facebook Reel + YouTube Short) cut from the best part of each video
  * a first comment with a question, so people start talking
  * YouTube playlists per story type, and chapters in the description
  * a small "Like - Share - Follow" badge inside the video
  * learning from likes/comments/views which kinds of stories people enjoy most

Every feature is optional: if something fails (missing permission, daily limit...) it is logged
and skipped - the main video is never stopped because of it.
"""
import datetime as dt
import json
import os
import random
import subprocess
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

GRAPH = "https://graph.facebook.com/v21.0"
YT = "https://www.googleapis.com/youtube/v3"
VW, VH = 720, 1280           # vertical video size for Reels / Shorts


def env(name):
    return (os.getenv(name) or "").strip()


def log(*a):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}... failed:\n{r.stderr[-1500:]}")
    return r.stdout


def _font(path, size):
    try:
        return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        return ImageFont.truetype(path, size)


_CMAPS = {}


def fit_glyphs(text, font_path):
    """Only characters the font can draw: Bengali fonts have no ASCII digits or punctuation, so 1 -> ১,
    ' -> ’, : -> ।, and anything else the font lacks is left out (no empty boxes on the picture)."""
    try:
        if font_path not in _CMAPS:
            from fontTools.ttLib import TTFont
            _CMAPS[font_path] = set(TTFont(font_path).getBestCmap())
        cm = _CMAPS[font_path]
    except Exception:
        return no_tofu(text)
    beng = 0x0995 in cm
    rep = {"'": "’", '"': "’", ":": "।", "|": "।"}
    out = []
    for ch in no_tofu(text):
        if ord(ch) in cm or ch in " \n":
            out.append(ch)
        elif beng and ch.isdigit() and ch.isascii():
            out.append(chr(0x09E6 + int(ch)))
        elif rep.get(ch) and ord(rep[ch]) in cm:
            out.append(rep[ch])
        elif ch in "-,.()#":
            out.append(" " if ch in "-," else "")
    return " ".join("".join(out).split())


def _fit_text(draw, text, path, max_w, start, lines_max=2):
    text = fit_glyphs(text, path)
    """Split text into up to 2 lines and find the biggest font size that fits max_w."""
    words = str(text).split()
    if len(words) >= 2 and lines_max > 1:
        half = len(words) // 2 + len(words) % 2
        lines = [" ".join(words[:half]), " ".join(words[half:])]
    else:
        lines = [str(text)]
    size = start
    while size > 30:
        f = _font(path, size)
        if all(draw.textlength(l, font=f) <= max_w for l in lines):
            return lines, f, size
        size -= 4
    return lines, _font(path, size), size


# ----------------------------------------------------------------- Like / Share / Follow badge
def no_tofu(text):
    """drop emoji and symbols the Bengali/Hindi fonts cannot draw (they would show as empty boxes)"""
    import re as _re
    return _re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d]", "", str(text)).strip()


def make_badge(font_path, text, out, colors=((220, 0, 30), (255, 255, 255))):
    """A rounded pill (PNG with transparency) shown in the top-right corner of the main video."""
    bg, fg = colors
    text = no_tofu(text.replace("•", "|"))          # the Bengali/Hindi font has no bullet or emoji
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    f = _font(font_path, 34)
    tw = int(probe.textlength(text, font=f))
    w, h = tw + 70, 66
    img = Image.new("RGBA", (w + 12, h + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 6 + w, 6 + h], radius=33, fill=bg + (235,), outline=(255, 255, 255, 255), width=3)
    d.ellipse([18, 22, 40, 44], fill=fg + (255,))                       # small "record" dot
    d.text((52, 6 + (h - 44) // 2), text, font=f, fill=fg + (255,))
    img.save(out)
    return out


def badge_filter(total):
    """ffmpeg 'enable' expression: badge visible 6-12 s and in the last 10 s."""
    end = max(14.0, total - 2.0)
    return f"between(t,6,12)+between(t,{max(13.0, total - 10.0):.2f},{end:.2f})"


# ----------------------------------------------------------------- chapters (YouTube)
def fmt_time(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def chapters_text(part_times, names, heading):
    """part_times: start second of every part; names: chapter name of every part.
    YouTube needs: first at 0:00, at least 3 chapters, each at least 10 s long."""
    rows, last = [], None
    for i, (t, n) in enumerate(zip(part_times, names)):
        if last is not None and t - last < 12:
            continue
        if i == 0:
            t = 0.0
        rows.append(f"{fmt_time(t)} {str(n).strip()[:40]}")
        last = t
    if len(rows) > 12:                          # keep it short: every other chapter
        rows = rows[:1] + rows[1:-1][::2] + rows[-1:]
    return (heading + "\n" + "\n".join(rows)) if len(rows) >= 3 else ""


# ----------------------------------------------------------------- teaser (Reel / Short)
def pick_window(segs, part_times, scene_no, max_len=55.0, min_len=25.0):
    """segs: [(start, dur, ...)] of every spoken line in the final video.
    Start at the beginning of the chosen story scene (part index = scene_no, part 0 is the intro)
    and end at the end of a line, before max_len seconds."""
    if not segs:
        return 0.0, max_len
    k = max(1, min(int(scene_no or 1), len(part_times) - 1)) if len(part_times) > 1 else 0
    start = part_times[k] if part_times else segs[0][0]
    start = max(0.0, start - 0.3)
    end = start
    for s, d, *_ in segs:
        if s < start:
            continue
        if s + d - start > max_len:
            break
        end = s + d
    if end - start < min_len:                       # chosen scene too close to the end: use the story start
        start = part_times[1] - 0.3 if len(part_times) > 1 else 0.0
        end = start
        for s, d, *_ in segs:
            if s >= start and s + d - start <= max_len:
                end = s + d
    return start, min(end + 0.7, start + max_len + 0.7)


def make_teaser(video, start, end, out, font_path, hook_text, cta_text, workdir,
                colors=((255, 225, 0), (210, 0, 0)), vertical=False):
    """Vertical 720x1280 teaser: blurred video fills the background, the real video in the middle,
    a big hook text on top and a 'watch the full story' line at the bottom."""
    top_col, band_col = colors
    hook_text, cta_text = no_tofu(hook_text), no_tofu(cta_text)
    ov = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    lines, f, size = _fit_text(d, hook_text, font_path, VW - 70, 78, lines_max=2)
    y = 36
    for l in lines:
        tw = d.textlength(l, font=f)
        d.text(((VW - tw) / 2, y), l, font=f, fill=top_col + (255,), stroke_width=max(5, size // 12),
               stroke_fill=(0, 0, 0, 255))
        y += int(size * 1.3)
    cl, cf, cs = _fit_text(d, cta_text, font_path, VW - 110, 46, lines_max=1)
    tw = d.textlength(cl[0], font=cf)
    by = VH - 185
    d.rounded_rectangle([(VW - tw) / 2 - 30, by - 14, (VW + tw) / 2 + 30, by + cs * 1.35 + 10], radius=26,
                        fill=band_col + (240,), outline=(255, 255, 255, 255), width=3)
    d.text(((VW - tw) / 2, by), cl[0], font=cf, fill=(255, 255, 255, 255))
    png = os.path.join(workdir, "teaser_overlay.png")
    ov.save(png)
    dur = max(5.0, end - start)
    if vertical:                                  # already filmed in 9:16: only the title and the band on top
        _run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", video, "-i", png,
              "-filter_complex", f"[0:v]scale={VW}:{VH}[b];[b][1:v]overlay=0:0,format=yuv420p[v]",
              "-map", "[v]", "-map", "0:a",
              "-af", f"afade=t=in:st=0:d=0.3,afade=t=out:st={max(0.0, dur - 1.2):.2f}:d=1.2",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-r", "25",
              "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", out])
        return out
    # Facebook ranks Reels lower when the real picture is only a thin 16:9 strip in the middle
    # ("content quality: aspect ratio"). So the story picture is shown BIG (about 2/3 of the screen),
    # gently panning left-right so nothing important stays hidden; blurred copy only at the very edges.
    fh = int(VH * 0.64) // 2 * 2                  # height of the big picture
    fw = int(fh * 16 / 9) // 2 * 2
    fy = int(VH * 0.19)
    fc = (f"[0:v]split[a][b];[a]scale=-2:{VH},crop={VW}:{VH},boxblur=22:2,eq=brightness=-0.22[bg];"
          f"[b]scale={fw}:{fh},crop={VW}:{fh}:'({fw}-{VW})/2+({fw}-{VW})*0.22*sin(2*PI*t/14)':0[fg];"
          f"[bg][fg]overlay=0:{fy}[v1];[v1][1:v]overlay=0:0,format=yuv420p[v]")
    _run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", video, "-i", png,
          "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
          "-af", f"afade=t=in:st=0:d=0.3,afade=t=out:st={max(0.0, dur - 1.2):.2f}:d=1.2",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-r", "25",
          "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", out])
    return out


# ----------------------------------------------------------------- Facebook
def fb_post_reel(video, description):
    """Publishes a Facebook Reel on the page. Returns the video id."""
    page, token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    r = requests.post(f"{GRAPH}/{page}/video_reels", data={"upload_phase": "start", "access_token": token},
                      timeout=60).json()
    if "video_id" not in r:
        raise RuntimeError(f"reel start: {str(r)[:300]}")
    vid = r["video_id"]
    with open(video, "rb") as f:
        data = f.read()
    up = requests.post(f"https://rupload.facebook.com/video-upload/v21.0/{vid}",
                       headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))},
                       data=data, timeout=600).json()
    if not up.get("success"):
        raise RuntimeError(f"reel upload: {str(up)[:300]}")
    data = {"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
            "description": description[:2000], "access_token": token}
    at = publish_time()
    if at:                                            # goes live together with the main video
        data.update(video_state="SCHEDULED", scheduled_publish_time=str(int(at.timestamp())))
    fin = requests.post(f"{GRAPH}/{page}/video_reels", data=data, timeout=120).json()
    if not fin.get("success"):
        raise RuntimeError(f"reel finish: {str(fin)[:300]}")
    return vid


def fb_comment(object_id, text):
    """First comment (from the page) under the post. Needs the pages_manage_engagement permission."""
    token = env("FB_PAGE_TOKEN")
    last = None
    for wait in (20, 60, 120):              # the video needs a moment to finish processing
        time.sleep(wait)
        r = requests.post(f"{GRAPH}/{object_id}/comments", data={"message": text, "access_token": token},
                          timeout=60).json()
        if r.get("id"):
            return r["id"]
        last = r
        if (r.get("error") or {}).get("code") in (10, 200):
            break
    raise RuntimeError(str(last)[:300])


def fb_stats(object_id):
    token = env("FB_PAGE_TOKEN")
    r = requests.get(f"{GRAPH}/{object_id}", params={
        "fields": "likes.summary(true).limit(0),comments.summary(true).limit(0)", "access_token": token},
        timeout=30).json()
    if "error" in r:
        return None
    return {"likes": ((r.get("likes") or {}).get("summary") or {}).get("total_count", 0),
            "comments": ((r.get("comments") or {}).get("summary") or {}).get("total_count", 0)}


# ----------------------------------------------------------------- YouTube
def yt_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": env("YT_CLIENT_ID"), "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"), "grant_type": "refresh_token"}, timeout=60)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _yt_err(r):
    try:
        e = r.json().get("error", {})
        reason = (e.get("errors") or [{}])[0].get("reason", "")
    except Exception:
        reason = ""
    if r.status_code == 403 and reason in ("insufficientPermissions", "forbidden", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"):
        return ("needs a new YouTube token with the 'youtube.force-ssl' permission "
                "(see setup steps) - skipped")
    if reason in ("quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded"):
        return "YouTube daily limit reached - skipped"
    return f"HTTP {r.status_code}: {r.text[:200]}"


def yt_add_to_playlist(video_id, playlist_title, lang):
    hdr = yt_token()
    pid = None
    r = requests.get(f"{YT}/playlists", headers=hdr, params={"part": "snippet", "mine": "true", "maxResults": 50},
                     timeout=30)
    if not r.ok:
        raise RuntimeError(_yt_err(r))
    for p in r.json().get("items", []):
        if p["snippet"]["title"].strip() == playlist_title.strip():
            pid = p["id"]
    if not pid:
        r = requests.post(f"{YT}/playlists", headers=hdr, params={"part": "snippet,status"}, json={
            "snippet": {"title": playlist_title[:150], "defaultLanguage": lang},
            "status": {"privacyStatus": "public"}}, timeout=30)
        if not r.ok:
            raise RuntimeError(_yt_err(r))
        pid = r.json()["id"]
        log(f"  new YouTube playlist: {playlist_title}")
    for attempt in range(4):        # a brand-new playlist needs a few seconds before videos can be added
        r = requests.post(f"{YT}/playlistItems", headers=hdr, params={"part": "snippet"}, json={
            "snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}, timeout=30)
        if r.ok or r.status_code not in (409, 500, 503):
            break
        time.sleep(10 * (attempt + 1))
    if not r.ok:
        raise RuntimeError(_yt_err(r))
    return pid


def yt_comment(video_id, text):
    hdr = yt_token()
    r = requests.post(f"{YT}/commentThreads", headers=hdr, params={"part": "snippet"}, json={
        "snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}}, timeout=30)
    if not r.ok:
        raise RuntimeError(_yt_err(r))
    return r.json().get("id")


def yt_stats(ids):
    if not ids:
        return {}
    hdr = yt_token()
    r = requests.get(f"{YT}/videos", headers=hdr, params={"part": "statistics", "id": ",".join(ids[:50])}, timeout=30)
    if not r.ok:
        raise RuntimeError(_yt_err(r))
    out = {}
    for it in r.json().get("items", []):
        s = it.get("statistics", {})
        out[it["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                         "comments": int(s.get("commentCount", 0))}
    return out


def shorts_today(history):
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    return sum(1 for h in history if h.get("yt_short") and str(h.get("date", "")).startswith(today))


# ----------------------------------------------------------------- learning what people like
def refresh_stats(history, max_items=25):
    """Adds/updates likes, comments and views of recent posts (older than 20 hours) in history."""
    now = dt.datetime.now(dt.timezone.utc)
    todo = []
    for h in history[-60:]:
        try:
            t = dt.datetime.fromisoformat(str(h.get("date")))
        except Exception:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        age = (now - t).total_seconds() / 3600
        if age < 20 or age > 24 * 30:
            continue
        st = h.get("stats") or {}
        if st.get("checked") and (now - dt.datetime.fromisoformat(st["checked"])).total_seconds() < 3 * 86400:
            continue
        todo.append(h)
    todo = todo[-max_items:]
    if not todo:
        return
    yt = {}
    ids = [h["youtube"] for h in todo if h.get("youtube")]
    if ids and env("YT_REFRESH_TOKEN"):
        try:
            yt = yt_stats(ids)
        except Exception as e:
            log("  YouTube stats:", str(e)[:150])
    for h in todo:
        st = {"likes": 0, "comments": 0, "views": 0}
        if h.get("facebook") and env("FB_PAGE_TOKEN"):
            try:
                fs = fb_stats(h["facebook"]) or {}
                st["likes"] += fs.get("likes", 0)
                st["comments"] += fs.get("comments", 0)
            except Exception:
                pass
        ys = yt.get(h.get("youtube", ""), {})
        for k in st:
            st[k] += ys.get(k, 0)
        st["checked"] = now.isoformat(timespec="minutes")
        h["stats"] = st
    log(f"  updated likes/comments/views of {len(todo)} older posts")


def score(st):
    return st.get("views", 0) / 50 + st.get("likes", 0) * 2 + st.get("comments", 0) * 4


def weights(history, key, options):
    """Weight for every option: 1.0 = average; options people liked more get up to 3x more often."""
    sums, counts = {}, {}
    for h in history[-90:]:
        st, k = h.get("stats"), h.get(key)
        if st and k in options:
            sums[k] = sums.get(k, 0) + score(st)
            counts[k] = counts.get(k, 0) + 1
    if len(counts) < 2:
        return {o: 1.0 for o in options}
    avg = {k: sums[k] / counts[k] for k in counts}
    mean = sum(avg.values()) / len(avg) or 1.0
    return {o: max(0.5, min(3.0, avg.get(o, mean) / mean)) for o in options}


def weighted_choice(options, w):
    opts = list(options)
    return random.choices(opts, weights=[w.get(o, 1.0) for o in opts], k=1)[0]


# ================================================================= v3: deeper experience
# ----------------------------------------------------------------- YouTube daily limit safety
def yt_extra_ok():
    """Shorts, subtitles and the weekly compilation cost a lot of YouTube 'quota'. They are only
    switched on when this channel has its OWN Google Cloud project (secret YT_EXTRA = 1)."""
    return env("YT_EXTRA") == "1"


# ----------------------------------------------------------------- 3D sound for headphones
def _np():
    import numpy
    return numpy


def spatial_path(name, rnd):
    """Where a sound comes from (degrees: 0 front, +90 right ear, -90 left ear, 180 behind)
    and where it moves to. Returns (start_az, end_az, wetness)."""
    n = str(name).lower()
    side = 1 if rnd.uniform() < 0.5 else -1
    if any(k in n for k in ("footstep", "steps", "walking", "running", "approach", "coming")):
        return side * 150, side * 35, 0.35                 # from behind, coming closer
    if any(k in n for k in ("whisper", "breath", "ghost_whisper", "sigh")):
        return side * 85, side * 85, 0.15                  # right into one ear
    if "ghost_swell" in n or "wind gust" in n:
        return side * 170, -side * 60, 0.45                # sweeps around the head
    if any(k in n for k in ("door", "knock", "creak", "gate", "window", "bang")):
        return side * 60, side * 60, 0.4
    if any(k in n for k in ("scream", "laugh", "howl", "dog", "distant", "far", "cry", "baby")):
        return side * 40, side * 40, 0.6                   # far away, lots of room sound
    if any(k in n for k in ("ghungroo", "anklet", "bell", "bangle", "chain")):
        return side * 120, -side * 120, 0.4                # walks behind you
    if any(k in n for k in ("scare_hit", "thunder", "lightning", "rain", "wind")):
        return 0, 0, 0.3
    a = float(rnd.uniform(-70, 70))
    return a, a, 0.35


def spatialize(mono, az0, az1, sr=44100):
    """Mono -> stereo (L, R) with level + time difference between the ears; sounds behind are
    a bit duller. Moves smoothly from az0 to az1."""
    np = _np()
    from scipy.signal import butter, sosfilt
    n = len(mono)
    if n == 0:
        return mono, mono
    az = np.radians(np.linspace(az0, az1, n))
    pan = np.sin(az)                                      # -1 left .. +1 right
    gl = np.cos((pan + 1) * np.pi / 4)
    gr = np.sin((pan + 1) * np.pi / 4)
    behind = np.clip(-np.cos(az), 0, 1)                   # 0 in front, 1 straight behind
    dull = sosfilt(butter(2, 3500, "lowpass", fs=sr, output="sos"), mono)
    src = mono * (1 - 0.6 * behind) + dull * (0.6 * behind)
    itd = int(abs(np.sin(np.radians((az0 + az1) / 2))) * 0.00066 * sr)   # up to ~0.66 ms
    left, right = src * gl * 1.25, src * gr * 1.25
    if itd:
        if (az0 + az1) / 2 > 0:                           # sound on the right: left ear hears it later
            left = np.concatenate([np.zeros(itd), left[:-itd]])
        else:
            right = np.concatenate([np.zeros(itd), right[:-itd]])
    return left, right


def widen(mono, sr=44100):
    """Background ambience made wide (fills both ears differently)."""
    np = _np()
    from scipy.signal import butter, sosfilt
    hp = sosfilt(butter(2, 300, "highpass", fs=sr, output="sos"), mono)
    side = np.roll(hp, int(0.009 * sr)) - np.roll(hp, int(0.017 * sr))
    return mono + 0.45 * side, mono - 0.45 * side


ROOM_WORDS = [
    ("cave", ("cave", "well", "tunnel", "kuyo", "kuan", "stepwell", "baori", "basement", "cellar", "drain")),
    ("hall", ("haveli", "palace", "bari", "mansion", "corridor", "hall", "temple", "church", "station",
              "hospital", "school", "mill", "theatre", "cinema", "hostel", "factory", "staircase", "bungalow")),
    ("room", ("room", "house", "hut", "kitchen", "bedroom", "flat", "office", "car", "bus", "train", "shop")),
    ("outdoor", ("forest", "jungle", "field", "road", "highway", "river", "village", "garden", "ground",
                 "shamshan", "cremation", "lake", "boat", "beach", "tree", "graveyard", "bridge")),
]
ROOM_SETTINGS = {"cave": (1.6, 0.12, 0.55), "hall": (1.1, 0.05, 0.45), "room": (0.35, 0.0, 0.3),
                 "outdoor": (0.25, 0.0, 0.12)}   # (decay seconds, slap-echo seconds, wet level)


def room_kind(place_text):
    t = str(place_text).lower()
    for kind, words in ROOM_WORDS:
        if any(w in t for w in words):
            return kind
    return "room"


def reverb_stereo(left, right, kind, sr=44100, seed=1):
    """Room sound of the place (made-up impulse response, different for each ear)."""
    np = _np()
    from scipy.signal import fftconvolve
    decay, slap, wet = ROOM_SETTINGS.get(kind, ROOM_SETTINGS["room"])
    rnd = np.random.default_rng(seed)
    m = int(sr * decay * 1.2)
    t = np.arange(m) / sr
    outs = []
    for ch, sig in enumerate((left, right)):
        ir = rnd.standard_normal(m) * np.exp(-6.9 * t / decay)
        if slap:
            k = int(slap * sr) + ch * int(0.013 * sr)
            if k < m:
                ir[k] += 6.0
        ir /= np.sqrt((ir ** 2).sum()) + 1e-9
        r = fftconvolve(sig, ir)[:len(sig)]
        outs.append(sig + r * wet)
    return outs[0], outs[1]


def write_stereo_wav(path, left, right, sr=44100):
    import wave
    np = _np()
    st = np.stack([np.clip(left, -1, 1), np.clip(right, -1, 1)], axis=1)
    with wave.open(path, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((st * 32767).astype(np.int16).tobytes())


# ----------------------------------------------------------------- small picture cards
def headphone_hint(font_path, text, out):
    """'(headphones) Listen with headphones' pill, drawn without emoji fonts."""
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    f = _font(font_path, 38)
    tw = int(probe.textlength(text, font=f))
    w, h = tw + 120, 76
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=38, fill=(0, 0, 0, 190), outline=(255, 255, 255, 220), width=3)
    cx, cy = 52, 40                                        # headphones icon
    d.arc([cx - 24, cy - 26, cx + 24, cy + 22], 180, 360, fill=(255, 255, 255, 255), width=6)
    d.rounded_rectangle([cx - 30, cy - 4, cx - 16, cy + 22], radius=5, fill=(255, 255, 255, 255))
    d.rounded_rectangle([cx + 16, cy - 4, cx + 30, cy + 22], radius=5, fill=(255, 255, 255, 255))
    d.text((96, (h - 48) // 2), text, font=f, fill=(255, 255, 255, 255))
    img.save(out)
    return out


def quiz_cards(base_img, font_path, title, question, options, answer, labels, out_q, out_a, size=(1280, 720)):
    """Quiz screen (question + 3 options) and the answer screen (right option turns green)."""
    W, H = size
    bg = Image.open(base_img).convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(14))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (30, 10, 70)), 0.55)

    def card(show):
        img = bg.copy()
        d = ImageDraw.Draw(img)
        tf = _font(font_path, 64)
        tw = d.textlength(title, font=tf)
        d.rounded_rectangle([(W - tw) / 2 - 30, 26, (W + tw) / 2 + 30, 26 + 96], radius=40, fill=(255, 200, 0))
        d.text(((W - tw) / 2, 34), title, font=tf, fill=(60, 0, 80))
        lines, qf, qs = _fit_text(d, question, font_path, W - 140, 54)
        y = 150
        for l in lines:
            lw = d.textlength(l, font=qf)
            d.text(((W - lw) / 2, y), l, font=qf, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
            y += int(qs * 1.35)
        of = _font(font_path, 46)
        y = max(y + 20, 330)
        for i, opt in enumerate(options[:3]):
            right = show and i == answer
            fill = (40, 170, 70) if right else (255, 255, 255)
            d.rounded_rectangle([170, y, W - 170, y + 96], radius=48, fill=fill, outline=(255, 200, 0), width=5)
            d.ellipse([186, y + 12, 258, y + 84], fill=(255, 200, 0))
            lab = labels[i]
            lw = d.textlength(lab, font=of)
            d.text((222 - lw / 2, y + 16), lab, font=of, fill=(60, 0, 80))
            ol, ofit, _ = _fit_text(d, str(opt), font_path, W - 520, 46, lines_max=1)
            d.text((290, y + 18), ol[0], font=ofit, fill=(255, 255, 255) if right else (40, 20, 70))
            if right:                                    # tick mark
                d.line([(W - 250, y + 50), (W - 225, y + 75), (W - 185, y + 22)], fill=(255, 255, 255), width=10)
            y += 116
        return img
    card(False).save(out_q, quality=93)
    card(True).save(out_a, quality=93)
    return out_q, out_a


def hide_ghost(img_path, ghost_face_path, out, rnd, strength=0.17):
    """Paste the ghost's face very faintly into a dark corner of a picture ('find the ghost')."""
    np = _np()
    base = Image.open(img_path).convert("RGB")
    W, H = base.size
    face = Image.open(ghost_face_path).convert("RGB")
    s = int(H * rnd.uniform(0.22, 0.32))
    face = face.resize((int(s * face.width / face.height), s))
    gray = np.asarray(base.convert("L"), dtype="float32")
    best, pos = 1e9, (0, 0)
    for x in (int(W * 0.04), int(W * 0.5 - face.width / 2), int(W * 0.96 - face.width)):
        for y in (int(H * 0.05), int(H * 0.3)):
            v = gray[y:y + face.height, x:x + face.width].mean()
            if v < best:
                best, pos = v, (x, y)
    region = base.crop((pos[0], pos[1], pos[0] + face.width, pos[1] + face.height))
    a = np.asarray(region, dtype="float32")
    b = np.asarray(face, dtype="float32")
    screen = 255 - (255 - a) * (255 - b) / 255                  # black parts of the face vanish
    hh, ww = a.shape[:2]                                         # soft oval edge: no visible box
    yy, xx = np.mgrid[0:hh, 0:ww]
    r = np.sqrt(((xx - ww / 2) / (ww / 2)) ** 2 + ((yy - hh / 2) / (hh / 2)) ** 2)
    mask = (np.clip(1.0 - r, 0, 1) ** 0.8)[..., None] * strength
    mix = a * (1 - mask) + screen * mask
    base.paste(Image.fromarray(mix.clip(0, 255).astype("uint8")), pos)
    base.save(out, quality=93)
    return out


def announcement_card(base_img, font_path, line1, line2, out, colors=((255, 230, 0), (200, 0, 20))):
    W, H = 1080, 1080
    img = Image.open(base_img).convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s), int(img.height * s)))
    l, t = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(10))
    img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
    d = ImageDraw.Draw(img)
    lines, f, size = _fit_text(d, line1, font_path, W - 120, 120)
    y = 330
    for l1 in lines:
        tw = d.textlength(l1, font=f)
        d.text(((W - tw) / 2, y), l1, font=f, fill=colors[0], stroke_width=max(6, size // 12), stroke_fill=(0, 0, 0))
        y += int(size * 1.3)
    cl, cf, cs = _fit_text(d, line2, font_path, W - 200, 80, lines_max=1)
    tw = d.textlength(cl[0], font=cf)
    y += 40
    d.rounded_rectangle([(W - tw) / 2 - 40, y - 16, (W + tw) / 2 + 40, y + cs * 1.35 + 10], radius=30,
                        fill=colors[1], outline=(255, 255, 255), width=4)
    d.text(((W - tw) / 2, y), cl[0], font=cf, fill=(255, 255, 255))
    img.save(out, quality=92)
    return out


# ----------------------------------------------------------------- festivals
# (start, end, name, cartoon story idea, horror story idea). Month-day rows repeat every year.
FESTIVALS = [
    ("2026-10-18", "2026-10-21", "Durga Puja", "Ma Durga comes home for Durga Puja and blesses a poor village girl", None),
    ("2026-10-25", "2026-10-26", "Kojagari Lakshmi Puja", "Ma Lakshmi visits the house that stays awake on Kojagari Purnima", None),
    ("2026-11-07", "2026-11-07", "Bhoot Chaturdashi", "the fourteen lamps of Bhoot Chaturdashi and the kind ancestor spirits",
     "Bhoot Chaturdashi night: fourteen lamps, fourteen ghosts, and the one lamp that went out"),
    ("2026-11-08", "2026-11-08", "Kali Puja / Diwali", "Ma Kali's blessing and the Diwali lamp for a lonely grandmother",
     "Kali Puja amavasya night at an old cremation-ground temple"),
    ("2027-02-11", "2027-02-11", "Saraswati Puja", "Ma Saraswati blesses a poor student who loves to learn", None),
    ("2027-03-06", "2027-03-06", "Maha Shivaratri", "Lord Shiva and the hunter who kept awake all night on Shivaratri",
     "Shivaratri night at a lonely forest Shiva temple"),
    ("2027-03-10", "2027-03-10", "Sri Ramakrishna's birthday", "Sri Ramakrishna and Ma Kali at Dakshineswar", None),
    ("2027-03-22", "2027-03-22", "Holi / Dol Purnima", "Krishna and Radha play Holi (Dol) in Vrindavan", None),
    ("2027-04-15", "2027-04-15", "Ram Navami", "the birth of Lord Rama in Ayodhya", None),
    ("--10-31", "--10-31", "Halloween", None, "Halloween night party in an old British bungalow"),
    ("--11-14", "--11-14", "Children's Day", "Chacha Nehru's love for children and a school's Children's Day surprise", None),
    ("--12-25", "--12-25", "Christmas", "Christmas gift for the poor shoeshine boy", None),
    ("--01-01", "--01-01", "New Year", "a little girl's New Year promise to be kind every day", None),
    ("--01-12", "--01-12", "Swami Vivekananda's birthday", "young Naren (Swami Vivekananda) and his fearless courage", None),
    ("--01-23", "--01-23", "Netaji Jayanti", "little Subhas and his brave honest heart", None),
    ("--01-26", "--01-26", "Republic Day", "the children who saved the village flag on Republic Day", None),
    ("--04-14", "--04-15", "Poila Baishakh / Nobo Borsho", "Poila Baishakh new year at the village fair", None),
    ("--05-09", "--05-09", "Rabindra Jayanti", "a little boy who loved poems like Rabindranath Tagore", None),
    ("--08-15", "--08-15", "Independence Day", "the little freedom fighter of the village", None),
    ("--09-05", "--09-05", "Teachers' Day", "the teacher who never gave up on the naughtiest student", None),
    ("--10-02", "--10-02", "Gandhi Jayanti", "Bapu's lesson of truth and the honest little boy", None),
]


def festival_today(kind):
    """Story idea for today's festival (kind = 'cartoon' or 'horror'), using India time."""
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    for st, en, name, cartoon, horror in FESTIVALS:
        if st.startswith("--"):
            s = dt.date(now.year, int(st[2:4]), int(st[5:7]))
            e = dt.date(now.year, int(en[2:4]), int(en[5:7]))
        else:
            s, e = dt.date.fromisoformat(st), dt.date.fromisoformat(en)
        idea = cartoon if kind == "cartoon" else horror
        if idea and s <= now <= e:
            return name, idea
    return None


# ----------------------------------------------------------------- viewers vote for the ending
def comment_texts(fb_id=None, yt_id=None):
    texts = []
    if fb_id and env("FB_PAGE_TOKEN"):
        try:
            url, params = f"{GRAPH}/{fb_id}/comments", {"fields": "message", "limit": 100,
                                                        "access_token": env("FB_PAGE_TOKEN")}
            for _ in range(5):
                r = requests.get(url, params=params, timeout=30).json()
                texts += [c.get("message", "") for c in r.get("data", [])]
                nxt = (r.get("paging") or {}).get("next")
                if not nxt:
                    break
                url, params = nxt, None
        except Exception as e:
            log("  Facebook comments:", str(e)[:120])
    if yt_id and env("YT_REFRESH_TOKEN"):
        try:
            hdr = yt_token()
            r = requests.get(f"{YT}/commentThreads", headers=hdr, params={
                "part": "snippet", "videoId": yt_id, "maxResults": 100, "textFormat": "plainText"}, timeout=30)
            if r.ok:
                texts += [i["snippet"]["topLevelComment"]["snippet"].get("textDisplay", "")
                          for i in r.json().get("items", [])]
        except Exception as e:
            log("  YouTube comments:", str(e)[:120])
    return texts


def count_votes(texts):
    """Counts comments that answer 1 or 2 (also Bengali ১/২ and Hindi १/२)."""
    one, two = set("1১१"), set("2২२")
    v1 = v2 = 0
    for t in texts:
        s = str(t).strip()
        digits = [c for c in s if c in one | two]
        if not digits:
            continue
        if digits[0] in one:
            v1 += 1
        else:
            v2 += 1
    return v1, v2


# ----------------------------------------------------------------- English subtitles (YouTube)
def write_srt(segs, translations, path):
    """segs: [(start, dur, is_narrator, text)]; translations: {original text: English}."""
    rows, k = [], 0

    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    for st, du, _, text in segs:
        en = translations.get(str(text).strip())
        if not en:
            continue
        k += 1
        rows.append(f"{k}\n{ts(st)} --> {ts(st + du)}\n{en}\n")
    if k < 3:
        return None
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows))
    return path


def yt_upload_captions(video_id, srt_path, language="en", name="English"):
    hdr = yt_token()
    meta = json.dumps({"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}})
    with open(srt_path, "rb") as f:
        body = f.read()
    boundary = "story-bot-boundary"
    data = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + body + f"\r\n--{boundary}--".encode()
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/captions",
                      params={"part": "snippet", "uploadType": "multipart"},
                      headers={**hdr, "Content-Type": f"multipart/related; boundary={boundary}"}, data=data, timeout=120)
    if not r.ok:
        raise RuntimeError(_yt_err(r))
    return r.json().get("id")


# ----------------------------------------------------------------- "coming soon" post before a video
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TIME_WORDS = {"bn": {8: "সকাল ৮টায়", 13: "দুপুর ১টায়", 19: "সন্ধ্যা ৭টায়", 21: "রাত ৯টায়"},
              "hi": {8: "सुबह 8 बजे", 13: "दोपहर 1 बजे", 19: "शाम 7 बजे", 21: "रात 9 बजे"}}
DAY_WORDS = {"bn": ("আজ", "কাল"), "hi": ("आज", "कल")}


def next_slot(slots, announce_slots, lead_hours=2):
    """Next video time (India time) that should be announced, and when to publish the announcement."""
    now = dt.datetime.now(IST)
    for add in range(0, 3):
        day = (now + dt.timedelta(days=add)).date()
        for h in sorted(slots):
            slot = dt.datetime(day.year, day.month, day.day, h, 0, tzinfo=IST)
            if slot <= now + dt.timedelta(minutes=90):
                continue
            if h not in announce_slots:
                return None
            when = slot - dt.timedelta(hours=lead_hours)
            if when < now + dt.timedelta(minutes=20):
                return None
            return slot, when, (0 if slot.date() == now.date() else 1)
    return None


def fb_schedule_photo(image, message, when):
    page, token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    with open(image, "rb") as f:
        r = requests.post(f"{GRAPH}/{page}/photos", data={
            "message": message, "published": "false", "scheduled_publish_time": str(int(when.timestamp())),
            "access_token": token}, files={"source": ("card.jpg", f, "image/jpeg")}, timeout=120).json()
    if not r.get("id"):
        raise RuntimeError(str(r)[:300])
    return r["id"]


# ----------------------------------------------------------------- weekly compilation
def fb_video_source(video_id):
    r = requests.get(f"{GRAPH}/{video_id}", params={"fields": "source,length,title",
                                                     "access_token": env("FB_PAGE_TOKEN")}, timeout=30).json()
    return r.get("source"), float(r.get("length") or 0)


def download(url, path):
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return path


def normalize_clip(src, dst, w=1280, h=720, fps=25):
    _run(["ffmpeg", "-y", "-i", src, "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
          "-crf", "24", "-maxrate", "3000k", "-bufsize", "6000k", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
          "-ac", "2", dst])
    return dst


def collage(frames, out, size=(1280, 720)):
    W, H = size
    img = Image.new("RGB", (W, H), (0, 0, 0))
    frames = frames[:4] or []
    if not frames:
        img.save(out)
        return out
    cols = 2 if len(frames) > 1 else 1
    rows = 2 if len(frames) > 2 else 1
    cw, ch = W // cols, H // rows
    for i, fp in enumerate(frames[:cols * rows]):
        im = Image.open(fp).convert("RGB")
        s = max(cw / im.width, ch / im.height)
        im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1))
        l, t = (im.width - cw) // 2, (im.height - ch) // 2
        img.paste(im.crop((l, t, l + cw, t + ch)), ((i % cols) * cw, (i // cols) * ch))
    img.save(out, quality=92)
    return out


# ================================================================= v4: community, characters, world
# ----------------------------------------------------------------- notes for the daily report
ISSUES = []           # things that were skipped or failed in this run (sent in the Telegram report)
DONE = []             # things that worked (links)


def note_issue(text):
    ISSUES.append(str(text)[:200])


# ----------------------------------------------------------------- moon (Amavasya)
def new_moon_utc(k):
    """Time of new moon number k (k=0 near 6 Jan 2000), Meeus 'Astronomical Algorithms' ch.49
    with the main correction terms - accurate to a few minutes."""
    import math
    T = k / 1236.85
    jde = (2451550.09766 + 29.530588861 * k + 0.00015437 * T ** 2 - 0.00000015 * T ** 3 + 0.00000000073 * T ** 4)
    E = 1 - 0.002516 * T - 0.0000074 * T ** 2
    r = math.radians
    M = r(2.5534 + 29.10535670 * k - 0.0000014 * T ** 2)
    Mp = r(201.5643 + 385.81693528 * k + 0.0107582 * T ** 2)
    F = r(160.7108 + 390.67050284 * k - 0.0016118 * T ** 2)
    Om = r(124.7746 - 1.56375588 * k + 0.0020672 * T ** 2)
    corr = (-0.40720 * math.sin(Mp) + 0.17241 * E * math.sin(M) + 0.01608 * math.sin(2 * Mp)
            + 0.01039 * math.sin(2 * F) + 0.00739 * E * math.sin(Mp - M) - 0.00514 * E * math.sin(Mp + M)
            + 0.00208 * E * E * math.sin(2 * M) - 0.00111 * math.sin(Mp - 2 * F) - 0.00057 * math.sin(Mp + 2 * F)
            + 0.00056 * E * math.sin(2 * Mp + M) - 0.00042 * math.sin(3 * Mp) + 0.00042 * E * math.sin(M + 2 * F)
            + 0.00038 * E * math.sin(M - 2 * F) - 0.00024 * E * math.sin(2 * Mp - M) - 0.00017 * math.sin(Om))
    jde += corr
    return dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc) + dt.timedelta(days=jde - 2451545.0)


def moon_age_days(when_utc):
    """Days since the last new moon (0 = new moon)."""
    k = int((when_utc - dt.datetime(2000, 1, 6, tzinfo=dt.timezone.utc)).days / 29.530588861)
    for kk in (k + 1, k, k - 1, k - 2):
        nm = new_moon_utc(kk)
        if nm <= when_utc:
            return (when_utc - nm).total_seconds() / 86400.0
    return 15.0


def is_amavasya_night(now=None):
    """True on the Amavasya night: tonight's midnight (India time) falls between 18 hours before
    and 6 hours after the exact new moon (one night per month)."""
    now = now or dt.datetime.now(IST)
    midnight = (now + dt.timedelta(hours=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    mu = midnight.astimezone(dt.timezone.utc)
    k = int((mu - dt.datetime(2000, 1, 6, tzinfo=dt.timezone.utc)).days / 29.530588861)
    for kk in (k - 1, k, k + 1, k + 2):
        hours = (new_moon_utc(kk) - mu).total_seconds() / 3600     # + means new moon after midnight
        if -6 <= hours <= 18:
            return True
    return False


# ----------------------------------------------------------------- today's weather
CITIES = {"bn": ("Kolkata", 22.57, 88.36), "hi": ("Delhi", 28.61, 77.21)}


def weather_now(lang):
    """Short English description of the weather right now (free Open-Meteo, no key). None if unknown."""
    city, lat, lon = CITIES.get(lang, CITIES["bn"])
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "current": "weather_code,temperature_2m,precipitation,is_day",
            "timezone": "Asia/Kolkata"}, timeout=20).json()["current"]
    except Exception:
        return None
    code, temp = int(r.get("weather_code", 0)), float(r.get("temperature_2m", 25))
    if code >= 95:
        w = "a violent thunderstorm with lightning"
    elif code in (61, 63, 65, 80, 81, 82, 66, 67):
        w = "heavy rain"
    elif code in (51, 53, 55, 56, 57):
        w = "drizzle and wet streets"
    elif code in (45, 48):
        w = "thick fog"
    elif temp < 16:
        w = "a cold, misty winter night"
    elif temp > 33:
        w = "a hot, humid, airless night with a power cut"
    else:
        return None
    return f"{w} in and around {city} today (about {round(temp)} C)"


# ----------------------------------------------------------------- viewers' own stories
STORY_TAGS = ("#আমার_গল্প", "#আমারগল্প", "#मेरी_कहानी", "#मेरीकहानी", "#mystory", "#my_story")


def viewer_stories(history, used_ids, max_posts=20):
    """Comments (with the hashtag) where viewers tell their own ghost experience."""
    out = []
    posts = [h for h in history[-max_posts:] if h.get("facebook") or h.get("youtube")]
    token = env("FB_PAGE_TOKEN")
    for h in posts:
        if h.get("facebook") and token:
            try:
                r = requests.get(f"{GRAPH}/{h['facebook']}/comments", params={
                    "fields": "id,message,from{name},like_count", "limit": 100, "access_token": token},
                    timeout=30).json()
                for c in r.get("data", []):
                    out.append({"id": "fb_" + c["id"], "text": c.get("message", ""), "likes": c.get("like_count", 0),
                                "name": ((c.get("from") or {}).get("name") or "").split(" ")[0]})
            except Exception:
                pass
        if h.get("youtube") and env("YT_REFRESH_TOKEN"):
            try:
                r = requests.get(f"{YT}/commentThreads", headers=yt_token(), params={
                    "part": "snippet", "videoId": h["youtube"], "maxResults": 100, "textFormat": "plainText"},
                    timeout=30)
                for it in r.json().get("items", []) if r.ok else []:
                    sn = it["snippet"]["topLevelComment"]["snippet"]
                    name = str(sn.get("authorDisplayName", "")).lstrip("@").split(" ")[0]
                    out.append({"id": "yt_" + it["id"], "text": sn.get("textDisplay", ""),
                                "likes": sn.get("likeCount", 0), "name": name})
            except Exception:
                pass
    good = [c for c in out if c["id"] not in used_ids and len(c["text"]) >= 120
            and any(t in c["text"].lower() for t in STORY_TAGS)]
    good.sort(key=lambda c: (c["likes"], len(c["text"])), reverse=True)
    return good


# ----------------------------------------------------------------- Instagram Reels (from the same page)
def ig_account():
    r = requests.get(f"{GRAPH}/{env('FB_PAGE_ID')}", params={
        "fields": "instagram_business_account", "access_token": env("FB_PAGE_TOKEN")}, timeout=30).json()
    return (r.get("instagram_business_account") or {}).get("id")


def ig_post_reel(video, caption):
    """Publishes the teaser as an Instagram Reel (needs a linked Instagram professional account and the
    instagram_basic + instagram_content_publish permissions in the page token)."""
    ig = ig_account()
    if not ig:
        raise RuntimeError("no Instagram professional account linked to this Facebook page")
    token = env("FB_PAGE_TOKEN")
    c = requests.post(f"{GRAPH}/{ig}/media", data={"media_type": "REELS", "upload_type": "resumable",
                                                   "caption": caption[:2100], "share_to_feed": "true",
                                                   "access_token": token}, timeout=60).json()
    if "id" not in c:
        raise RuntimeError(f"instagram start: {str(c)[:250]}")
    cid = c["id"]
    with open(video, "rb") as f:
        data = f.read()
    up = requests.post(f"https://rupload.facebook.com/ig-api-upload/v21.0/{cid}", headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))}, data=data, timeout=600).json()
    if not up.get("success"):
        raise RuntimeError(f"instagram upload: {str(up)[:250]}")
    for _ in range(40):                       # Instagram needs a little time to process the video
        time.sleep(15)
        st = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code", "access_token": token}, timeout=30).json()
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            raise RuntimeError(f"instagram processing error: {st}")
    pub = requests.post(f"{GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": token},
                        timeout=60).json()
    if "id" not in pub:
        raise RuntimeError(f"instagram publish: {str(pub)[:250]}")
    return pub["id"]


# ----------------------------------------------------------------- Telegram report to your phone
def tg_chat_id(token):
    cid = env("TELEGRAM_CHAT_ID")
    if cid:
        return cid
    try:                                      # no chat id given: use the last person who wrote to the bot
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
        for u in reversed(r.get("result", [])):
            m = u.get("message") or u.get("channel_post") or {}
            if m.get("chat", {}).get("id"):
                return str(m["chat"]["id"])
    except Exception:
        pass
    return None


def telegram(text):
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    cid = tg_chat_id(token)
    if not cid:
        log("  Telegram: send any message to your bot once, so it knows where to write")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={
            "chat_id": cid, "text": text[:4000], "disable_web_page_preview": "true"}, timeout=20).json()
        return bool(r.get("ok"))
    except Exception:
        return False


def report_text(page_name, title, results, history):
    lines = [f"📺 {page_name}", f"🎬 {title}"]
    if results.get("facebook"):
        lines.append(f"Facebook: https://www.facebook.com/{results['facebook']}")
    if results.get("youtube"):
        lines.append(f"YouTube: https://youtu.be/{results['youtube']}")
    extra = [k for k in ("fb_reel", "ig_reel", "yt_short", "coloring") if results.get(k)]
    if extra:
        lines.append("➕ " + ", ".join(extra))
    best = max((h for h in history[-30:] if h.get("stats")), key=lambda h: score(h["stats"]), default=None)
    if best:
        st = best["stats"]
        lines.append(f"🏆 Best recent: {best.get('title', '')[:60]} "
                     f"(👁 {st.get('views', 0)}  👍 {st.get('likes', 0)}  💬 {st.get('comments', 0)})")
    if ISSUES:
        lines.append("⚠️ Skipped / problems:")
        lines += [f"• {i}" for i in ISSUES[:8]]
    else:
        lines.append("✅ Everything worked")
    return "\n".join(lines)


# ----------------------------------------------------------------- kids: English words card
def latin_font():
    import glob as _g
    for pat in ("/usr/share/fonts/**/NotoSans-Bold.ttf", "/usr/share/fonts/**/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/**/LiberationSans-Bold.ttf", "/usr/share/fonts/**/NotoSans-Regular.ttf"):
        f = _g.glob(pat, recursive=True)
        if f:
            return f[0]
    return None


def words_card(base_img, font_path, title, words, out, size=(1280, 720)):
    """words: [(english, meaning)]  ->  big friendly card."""
    W, H = size
    bg = Image.open(base_img).convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(14))
    img = Image.blend(bg, Image.new("RGB", (W, H), (10, 60, 90)), 0.55)
    d = ImageDraw.Draw(img)
    tf = _font(font_path, 58)
    tw = d.textlength(title, font=tf)
    d.rounded_rectangle([(W - tw) / 2 - 30, 30, (W + tw) / 2 + 30, 30 + 90], radius=40, fill=(255, 200, 0))
    d.text(((W - tw) / 2, 38), title, font=tf, fill=(10, 50, 80))
    y = 170
    ef = _font(latin_font() or font_path, 70)      # English letters need an English font (else boxes appear)
    for en, mean in words[:3]:
        d.rounded_rectangle([110, y, W - 110, y + 150], radius=40, fill=(255, 255, 255), outline=(255, 200, 0), width=6)
        d.text((150, y + 30), str(en), font=ef, fill=(220, 40, 90))
        d.text((W / 2 + 20, y + 38), "=", font=_font(latin_font() or font_path, 62), fill=(20, 40, 90))
        ml, mf, _ = _fit_text(d, str(mean), font_path, W / 2 - 190, 62, lines_max=1)
        d.text((W / 2 + 85, y + 38), ml[0], font=mf, fill=(20, 40, 90))
        y += 175
    img.save(out, quality=93)
    return out


def fb_photo(image, message):
    """Publishes a photo post on the page right now."""
    with open(image, "rb") as f:
        r = requests.post(f"{GRAPH}/{env('FB_PAGE_ID')}/photos", data={
            "message": message, "access_token": env("FB_PAGE_TOKEN")},
            files={"source": ("page.jpg", f, "image/jpeg")}, timeout=120).json()
    if not r.get("id"):
        raise RuntimeError(str(r)[:300])
    return r["id"]


def coloring_sheet(raw_path, out, font_path=None, caption=""):
    """Turns a line drawing into a clean printable black-and-white page (A4-like, white margins)."""
    from PIL import ImageOps
    im = Image.open(raw_path).convert("L")
    im = ImageOps.autocontrast(im)
    im = im.point(lambda v: 255 if v > 165 else 0)                 # pure black lines on white
    W, H = 1240, 1754
    page = Image.new("L", (W, H), 255)
    s = min((W - 140) / im.width, (H - 300) / im.height)
    im = im.resize((int(im.width * s), int(im.height * s)))
    page.paste(im, ((W - im.width) // 2, 170))
    d = ImageDraw.Draw(page)
    d.rectangle([30, 30, W - 30, H - 30], outline=0, width=6)
    if font_path and caption:
        f = _font(font_path, 64)
        tw = d.textlength(caption, font=f)
        d.text(((W - tw) / 2, 60), caption, font=f, fill=0)
    page.convert("RGB").save(out, quality=95)
    return out


# ================================================================= v5: viewers take part, and get named
BN_DIGITS, HI_DIGITS = "০১২৩৪৫৬৭৮৯", "०१२३४५६७८९"


def norm_digits(text):
    t = str(text)
    for i in range(10):
        t = t.replace(BN_DIGITS[i], str(i)).replace(HI_DIGITS[i], str(i))
    return t


def first_name(name):
    n = str(name or "").strip().lstrip("@").replace("_", " ").replace(".", " ")
    n = n.split()[0] if n.split() else ""
    return n[:20] if len(n) >= 2 and not n.isdigit() else ""


def post_comments(fb_id=None, yt_id=None):
    """All comments under one post: [{"id", "name", "text", "src"}] (Facebook + YouTube)."""
    out = []
    if fb_id and env("FB_PAGE_TOKEN"):
        try:
            url, params = f"{GRAPH}/{fb_id}/comments", {"fields": "id,message,from{name}", "limit": 100,
                                                        "access_token": env("FB_PAGE_TOKEN")}
            for _ in range(5):
                r = requests.get(url, params=params, timeout=30).json()
                for c in r.get("data", []):
                    out.append({"id": c.get("id"), "name": first_name((c.get("from") or {}).get("name")),
                                "text": c.get("message", ""), "src": "fb"})
                nxt = (r.get("paging") or {}).get("next")
                if not nxt:
                    break
                url, params = nxt, None
        except Exception as e:
            log("  Facebook comments:", str(e)[:120])
    if yt_id and env("YT_REFRESH_TOKEN"):
        try:
            r = requests.get(f"{YT}/commentThreads", headers=yt_token(), params={
                "part": "snippet", "videoId": yt_id, "maxResults": 100, "textFormat": "plainText"}, timeout=30)
            for it in (r.json().get("items", []) if r.ok else []):
                sn = it["snippet"]["topLevelComment"]["snippet"]
                out.append({"id": it["id"], "name": first_name(sn.get("authorDisplayName")),
                            "text": sn.get("textDisplay", ""), "src": "yt"})
        except Exception as e:
            log("  YouTube comments:", str(e)[:120])
    return out


def first_digit(text):
    t = norm_digits(text)
    return next((c for c in t if c.isdigit()), None)


def winners(comments, digit=None, words=(), label=None):
    """People whose comment has the right answer: the right number, the right word, or the right option label."""
    import re as _re
    names, fb_ids, seen = [], [], set()
    for c in comments:
        t = str(c["text"]).strip()
        ok = False
        if digit is not None and first_digit(t) == str(digit):
            ok = True
        if any(w and len(w) >= 2 and w.lower() in t.lower() for w in words):
            ok = True
        if label and _re.match(rf"^\(?{_re.escape(label)}\)?(\s|$|[.,!।)\-:])", t):
            ok = True
        if ok and c["name"] and c["name"].lower() not in seen:
            seen.add(c["name"].lower())
            names.append(c["name"])
            if c["src"] == "fb" and c.get("id"):
                fb_ids.append(c["id"])
    return names, fb_ids


def vote_count(comments):
    """Votes 1 / 2 with the voters' names."""
    v = {"1": [], "2": []}
    for c in comments:
        d = first_digit(c["text"])
        if d in v:
            v[d].append(c)
    return v


def name_list(names, lang, maxn=6):
    names = [n for n in names if n][:50]
    if not names:
        return ""
    shown = names[:maxn]
    joiner = " আর " if lang == "bn" else " और "
    txt = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + joiner + shown[-1]
    more = len(names) - len(shown)
    if more > 0:
        txt += (f" সহ আরও {more} জন" if lang == "bn" else f" और {more} लोग")
    return txt


def reply_to(comment_ids, text, limit=10):
    """Reply (as the page) under people's own comments, so they get a notification."""
    n = 0
    for cid in comment_ids[:limit]:
        try:
            r = requests.post(f"{GRAPH}/{cid}/comments", data={"message": text, "access_token": env("FB_PAGE_TOKEN")},
                              timeout=30).json()
            n += 1 if r.get("id") else 0
        except Exception:
            pass
    return n


def last_post(history, key=None, min_hours=1.5):
    """The previous normal video of this bot (with its answer data)."""
    now = dt.datetime.now(dt.timezone.utc)
    for h in reversed(history[-10:]):
        if h.get("kind") == "compilation" or not (h.get("facebook") or h.get("youtube")):
            continue
        try:
            t = dt.datetime.fromisoformat(str(h.get("date")))
        except Exception:
            continue
        if (now - t.replace(tzinfo=t.tzinfo or dt.timezone.utc)).total_seconds() < min_hours * 3600:
            continue
        if key is None or h.get(key):
            return h
        return None
    return None


# ----------------------------------------------------------------- which time slot is this run for?
def current_slot(triggers, now=None):
    """triggers: [(start_hour, start_minute, post_hour)] in India time, e.g. [(11, 55, 13), (19, 55, 21)].
    A run belongs to the LAST slot that has already started (10 minutes early allowed), so a late
    backup run still knows which slot it is for. Returns e.g. '2026-10-22@13'."""
    now = now or dt.datetime.now(IST)
    best = None
    for add in (0, -1):
        day = (now + dt.timedelta(days=add)).date()
        for h, m, post in triggers:
            start = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=IST) - dt.timedelta(minutes=10)
            if start <= now and (best is None or start > best[0]):
                best = (start, f"{day.isoformat()}@{post}")
    return best[1] if best else None


def slot_done(history, slot):
    return bool(slot) and any(h.get("slot") == slot for h in history[-12:])


# ================================================================= v6: expressive voices (Gemini TTS)
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
TAG_RE = None
TTS_STATE = {"key": 0, "off": False, "bad_models": set()}
NEW_TTS = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
OLD_TTS = ("gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts")


def strip_tags(text):
    """Remove voice tags like <sigh> or <short pause> (for subtitles and the backup voice)."""
    import re as _re
    return _re.sub(r"\s*<[A-Za-z][A-Za-z \-]{1,24}>\s*", " ", str(text)).strip()


TAG_WORDS = {"laugh": "laughs", "laughs": "laughs", "sigh": "sighs", "gasp": "gasps", "sob": "sobs",
             "whisper": "whispers", "whispers": "whispers", "breath": "breathes in", "scream": "screams",
             "cackle": "cackles wickedly", "growl": "growls", "giggle": "giggles", "evil laugh": "laughs wickedly"}


def tts_tags(text):
    """Voice tags for the newest Gemini voices: they understand [sighs] / [laughs] in square brackets and pauses
    as '...'. Our <sigh>-style tags would otherwise be READ OUT ('long pause' spoken aloud!)."""
    import re as _re

    def one(m):
        w = m.group(1).strip().lower()
        if "pause" in w:
            return " ... ... " if "long" in w else " ... "
        return f" [{TAG_WORDS.get(w, w)}] "
    out = _re.sub(r"<\s*([A-Za-z][A-Za-z \-]{1,24})\s*>", one, str(text))
    return _re.sub(r"\s{2,}", " ", out).strip()


def tts_keys():
    keys = [k for k in (env("GEMINI_TTS_KEY" + s) for s in ("", "_2", "_3", "_4", "_5")) if k]
    if env("TTS_PAID") == "1" and env("GEMINI_API_KEY"):
        keys.append(env("GEMINI_API_KEY"))          # your paid key, only if you switched it on
    return keys


def _find_audio(obj):
    """Finds the base64 audio inside any Gemini reply shape."""
    if isinstance(obj, dict):
        if isinstance(obj.get("data"), str) and len(obj["data"]) > 200 and (
                obj.get("type") == "audio" or "audio" in str(obj.get("mime_type", obj.get("mimeType", ""))) or
                obj.get("type") in (None, "")):
            return obj["data"]
        for v in obj.values():
            r = _find_audio(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_audio(v)
            if r:
                return r
    return None


def _429_kind(r):
    import re as _re
    wait = 30.0
    m = _re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', r.text)
    if m:
        wait = float(m.group(1))
    return ("day" if _re.search(r"PerDay|per_day|daily", r.text, _re.I) else "minute"), wait


def tts_gemini(voice_text, voice, style, lang_label, out_wav, sr=44100, max_tries=2):
    """Speaks one line with Gemini's expressive voice model.
    voice_text may hold tags like <sigh>, <laugh>, <gasp>, <short pause>; style = how to perform it.
    Tries the newest models first (3.8 Flash TTS), then older ones; rotates keys when a limit is hit.
    Returns True when out_wav (mono, sr Hz) is ready."""
    if TTS_STATE["off"]:
        return False
    keys = tts_keys()
    if not keys:
        return False
    models = ([env("GEMINI_TTS_MODEL")] if env("GEMINI_TTS_MODEL") else []) + list(NEW_TTS) + list(OLD_TTS)
    plain_len = len(strip_tags(voice_text))
    while TTS_STATE["key"] < len(keys):
        key = keys[TTS_STATE["key"]]
        hdr = {"x-goog-api-key": key, "Content-Type": "application/json"}
        key_dead = False
        for model in models:
            if model in TTS_STATE["bad_models"]:
                continue
            if model in NEW_TTS:
                url = f"{GEMINI_BASE}/interactions"
                body = {"model": model,
                        "input": [{"type": "user_input", "content": [{
                            "type": "text", "text": voice_text,
                            "annotations": [{"type": "speech_metadata", "style": style[:600]}]}]}],
                        "response_format": {"type": "audio"},
                        "generation_config": {"speech_config": [{"voice": voice}]}}
            else:
                url = f"{GEMINI_BASE}/models/{model}:generateContent"
                body = {"contents": [{"parts": [{"text": f"You are a voice actor in a {lang_label} audio drama. "
                                                          f"Perform it like this: {style}. Say only this line:\n"
                                                          f"{strip_tags(voice_text)}"}]}],
                        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
            tries, waits = 0, 0
            while tries < max_tries:
                try:
                    r = requests.post(url, headers=hdr, json=body, timeout=150)
                    if r.status_code in (400, 404) and ("model" in r.text.lower() or "not found" in r.text.lower()
                                                        or "unsupported" in r.text.lower() or r.status_code == 404):
                        TTS_STATE["bad_models"].add(model)      # this model/API is not available here
                        log(f"  voice model {model} not available ({r.status_code}) - trying the next one")
                        break
                    if r.status_code == 429:
                        kind, wait = _429_kind(r)
                        if kind == "minute" and waits < 4:
                            waits += 1
                            if waits == 1:
                                log(f"    per-minute voice limit - waiting {min(wait, 65):.0f}s")
                            time.sleep(min(wait, 65) + 1)
                            continue
                        break                                    # daily limit of this model -> next model
                    if r.status_code in (401, 403):
                        key_dead = True
                        break
                    if not r.ok:
                        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
                    b64 = _find_audio(r.json())
                    if not b64:
                        raise RuntimeError("no audio in reply")
                    import base64 as _b64
                    data = _b64.b64decode(b64)
                    raw = out_wav + ".raw"
                    with open(raw, "wb") as f:
                        f.write(data)
                    inp = ["-i", raw] if data[:4] == b"RIFF" else ["-f", "s16le", "-ar", "24000", "-ac", "1", "-i", raw]
                    _run(["ffmpeg", "-y"] + inp + [
                        "-af", "silenceremove=start_periods=1:start_threshold=-50dB:"
                               "stop_periods=-1:stop_duration=1.2:stop_silence=0.6:stop_threshold=-50dB,"
                               "areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse",
                        "-ac", "1", "-ar", str(sr), out_wav])
                    d = float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "default=nw=1:nk=1", out_wav]).strip() or 0)
                    if d < max(0.4, plain_len / 40) or d > plain_len / 3 + 6:
                        tries += 1                               # cut off or rambling -> ask again
                        continue
                    return True
                except Exception as e:
                    log(f"  voice attempt failed ({model}): {str(e)[:120]}")
                    time.sleep(3)
                    tries += 1
            if key_dead:
                break
        TTS_STATE["key"] += 1
        TTS_STATE["bad_models"] = set()
        if TTS_STATE["key"] < len(keys):
            log(f"  expressive voice: key {TTS_STATE['key']} used up - switching to key {TTS_STATE['key'] + 1}")
    log("  expressive voice: all keys used up for today")
    TTS_STATE["off"] = True
    return False


PRONOUNCE = {
    "bn": "Accent: West Bengal, India - pure standard Kolkata Bengali (cholito bhasha) exactly as spoken by Kolkata "
          "radio actors of Sunday Suspense / Akashvani Kolkata. NOT a Bangladeshi or Dhaka accent, no Bangladeshi "
          "words or intonation. Clear, correct pronunciation of every word - proper Kolkata 'o'/'a' vowels, soft 'sh', "
          "correct conjuncts. Read EVERY word exactly as written - never skip, add or change a word; Bengali names "
          "and places the Bengali way (not anglicised); 'ড়'/'ঢ়', 'য়', chandrabindu and hasanta said correctly. Act "
          "it with real feeling and changing tension, breathing and pauses, like a live radio drama - never flat, "
          "never like reading.",
    "hi": "Speak natural, clear standard Hindi with correct pronunciation, like a professional Hindi radio actor. "
          "Never sound like reading.",
}


# ===================== v7: free voice model that runs on GitHub itself (no limit) =====================
# Indic Parler-TTS by AI4Bharat (IIT Madras) - free, open source (Apache 2.0), made for Indian languages,
# speaks Bangla and Hindi clearly, and follows a written direction: which speaker, how high/low, how fast,
# which emotion. Used when the Gemini voices run out, so the video still sounds human, not robotic.
# Needs only a free Hugging Face read token in the secret HF_TOKEN (model page: accept the terms once).
PARLER_ID = "ai4bharat/indic-parler-tts"
PARLER = {"model": None, "off": False}
PARLER_SPK = {"bn": {"male": ["Arjun", "Tapan", "Arnav"], "female": ["Aditi", "Rashmi", "Riya"]},
              "hi": {"male": ["Rohit", "Aman"], "female": ["Divya", "Rani"]}}
PARLER_EMO = {
    "normal": "a natural, expressive", "calm": "a calm, gentle", "whisper": "a very soft, hushed, frightened",
    "scared": "a fearful, trembling", "shout": "a loud, panicked", "angry": "an angry, sharp", "sad": "a sad, heavy",
    "crying": "a sad, tearful, choked", "eerie": "a slow, eerie, menacing", "happy": "a happy, bright",
    "excited": "an excited, surprised", "laughing": "a happy, laughing", "warm": "a warm, loving",
}
PARLER_AGE = {"child": ("a high-pitched", "fast"), "young": ("a slightly high-pitched", "moderate"),
              "adult": ("a moderate-pitched", "moderate"), "old": ("a low-pitched, slightly shaky", "slow")}


def parler_ok():
    return bool(env("HF_TOKEN")) and env("USE_FREE_MODEL") != "0" and not PARLER["off"]


def parler_cast(chars, lang, narrator_gender="male"):
    """Give every character a different speaker (or the same speaker with a different pitch).
    chars: list of (name, gender, age, is_ghost). Returns name.lower() -> (speaker, pitch words, speed)."""
    spk = PARLER_SPK.get(lang, PARLER_SPK["bn"])
    used = {"male": 1 if narrator_gender == "male" else 0, "female": 1 if narrator_gender == "female" else 0}
    out = {}
    for name, g, age, ghost in chars:
        g = "female" if str(g).startswith("f") else "male"
        pool = spk[g]
        s = pool[used[g] % len(pool)]
        used[g] += 1
        pitch, pace = PARLER_AGE.get(age, PARLER_AGE["adult"])
        if ghost:
            pitch, pace = ("a very low-pitched, raspy" if g == "male" else "a thin, high, breathy"), "slow"
        out[str(name).lower()] = (s, pitch, pace)
    return out


def _parler_load():
    if PARLER["model"] is None:
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer
        torch.set_num_threads(max(1, os.cpu_count() or 2))
        m = ParlerTTSForConditionalGeneration.from_pretrained(PARLER_ID, token=env("HF_TOKEN")).to("cpu")
        tok = AutoTokenizer.from_pretrained(PARLER_ID, token=env("HF_TOKEN"))
        dtok = AutoTokenizer.from_pretrained(m.config.text_encoder._name_or_path)
        PARLER["model"] = (m, tok, dtok)
    return PARLER["model"]


def parler_line(text, spec, emotion, out_wav, sr=44100, extra=""):
    """One line with the free model. spec = (speaker, pitch words, speed). True when done."""
    if not parler_ok():
        return False
    text = strip_tags(text).strip()
    if not text:
        return False
    try:
        import numpy as np
        import soundfile as sf
        import torch
        m, tok, dtok = _parler_load()
        speaker, pitch, pace = spec
        mood = PARLER_EMO.get(str(emotion).lower(), PARLER_EMO["normal"])
        desc = (f"{speaker} speaks in {mood} tone with {pitch} voice at a {pace} pace{extra}. "
                "The recording is very clear and close-up, with no background noise.")
        d = dtok(desc, return_tensors="pt")
        p = tok(text, return_tensors="pt")
        with torch.inference_mode():
            audio = m.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                               prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
        a = audio.cpu().numpy().squeeze().astype("float32")
        if a.size < m.config.sampling_rate * 0.3 or not np.isfinite(a).all():
            return False
        raw = out_wav + ".raw.wav"
        sf.write(raw, a, m.config.sampling_rate)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-ac", "1", "-ar", str(sr),
                        "-af", "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
                               "areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.1,areverse",
                        out_wav], check=True)
        os.remove(raw)
        return os.path.exists(out_wav) and os.path.getsize(out_wav) > 2000
    except Exception as e:
        log(f"  free voice model failed: {str(e)[:200]}")
        PARLER["off"] = True
        return False


# ===================== v7: better story writing + voice acting directions (both bots) =====================
STORY_CRAFT = """
STORY CRAFT (very important - the story must feel rich and alive, not a summary):
- Plan first in your head: a strong opening hook, a clear goal or problem for the main character, 3 rising
  turns that make it harder, an emotional low point, a climax, and a satisfying ending. Plant a small detail
  early (an object, a promise, a sound) that pays off at the end.
- SHOW, don't tell: instead of "she was scared", write her hands shaking, her breath stopping, her heart
  pounding. Every scene has concrete detail of sight, sound, smell, touch or taste.
- Give each character a clear personality and their OWN way of talking (one is brave and teasing, one is
  nervous and stammers, an old person speaks slowly with sayings). Show their inner thoughts and feelings.
- Real, natural dialogue: people interrupt, hesitate ("না... মানে..."), call each other by name, react to
  each other. Mix short and long sentences. Emotions must change through the story (fun, worry, fear, hope,
  sadness, joy) - never flat.
- Every scene must move the story forward; no repeating, no filler, no sudden rushed ending.
- Scenes flow into each other like a film: the end of each scene leads straight into the next (the same moment
  continuing, or a clear bridge of time and place). Never jump to an unrelated moment; details stay consistent.
"""

WRITING_RULES = {
    "bn": """
BENGALI WRITING (it will be read aloud by a voice engine, so pronunciation must come out right):
- Pure, standard Kolkata চলিত বাংলা ONLY (the way a good Kolkata radio storyteller speaks - শুদ্ধ চলিত ভাষা):
  করছিল / গিয়েছিল / তাকাল / বলল / এখানে / ওখানে / কেন / কী. Never সাধু ভাষা (no করিয়াছিল / তাহার / যাইতেছে),
  never Bangladeshi forms (no করসে / গেসে / কইলো / পানি / আসেন না ক্যান), never village dialect - not even
  for village characters; old people may only sound older (slower, with old sayings), still in চলিত বাংলা.
- No Hindi or Urdu words where a Bengali word exists (not 'লেকিন', 'মগর', 'বহুত', 'দরওয়াজা'), no English words
  in the lines (write 'ভূত', 'দরজা', 'আলো', 'টর্চ' only if that is what Kolkata people really say).
- Correct Bengali spelling (বানান) - especially ী/ি, ূ/ু, ণ/ন, শ/ষ/স, য-ফলা, র-ফলা and যুক্তাক্ষর.
  Use proper Bengali punctuation (। , ? ! ...).
- Write numbers in words (তিনটে, সাতাশ, দুশো), never digits. No abbreviations, no emoji, no English letters
  and no Hindi words inside spoken lines; use common Bengali words that everyone understands.
- Names written in Bengali script exactly the same way every time.
""",
    "hi": """
HINDI WRITING (it will be read aloud by a voice engine, so pronunciation must come out right):
- Natural, everyday spoken Hindi in Devanagari, correct spelling and matras, proper punctuation (। , ? !).
- Numbers in words, no digits, no abbreviations, no emoji, no English letters inside spoken lines.
""",
}

VOICE_ACTING = """
VOICE ACTING (every line is performed by a real-sounding AI voice actor, so direct them like a film):
- "delivery": ENGLISH acting direction for THIS line, 6-15 words: pitch (low/high), speed (slow/fast),
  loudness, and the exact feeling - e.g. "slow, low, trembling whisper, holding back tears",
  "fast and breathless, high-pitched with panic", "warm, smiling, gently teasing".
- "voice_text": the SAME words as "text", plus 0-2 sound tags in English angle brackets placed where they
  naturally happen: <sigh> <laugh> <giggle> <gasp> <sob> <whispers> <breath> <short pause> <long pause>
  <scream> <cackle> <growl>. Example: "<gasp> কে... কে ওখানে? <short pause> উত্তর দাও!"
  Use tags only where they truly fit (not on every line). The words must stay exactly the same as "text".
"""


def performed(ln):
    """The words the voice actor speaks: voice_text (with <sigh>-style tags) if its words match the
    subtitle text, otherwise the plain text."""
    import difflib
    t = strip_tags(str(ln.get("text", ""))).strip()
    v = str(ln.get("voice_text") or "").strip()
    if v:
        import re as _re
        a, b = _re.sub(r"[\W_]", "", strip_tags(v)), _re.sub(r"[\W_]", "", t)
        if b and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85:
            return v
    return t


# ===================== v8: faster expressive voices (fewer requests, all keys used together) =====================
# The free Gemini voice keys have small per-minute AND per-day limits. So:
#  1) on a per-minute limit we do not wait - the next key is used at once (each key has its own limit);
#  2) several lines (one or two speakers) are voiced in ONE request, then cut apart at the pauses -
#     about 4x fewer requests per story, so the daily limit covers whole stories.
KEY_COOL, KEY_LAST, KEY_DEAD, DAY_OUT = {}, {}, set(), set()


def _pick_key(model):
    keys = [k for k in tts_keys() if k not in KEY_DEAD and (k, model) not in DAY_OUT]
    if not keys:
        return None
    now = time.time()
    ready = [k for k in keys if KEY_COOL.get(k, 0) <= now]
    if not ready:                                     # every key is cooling down: wait for the first one
        k = min(keys, key=lambda k: KEY_COOL.get(k, 0))
        time.sleep(max(0.0, KEY_COOL.get(k, 0) - now) + 0.5)
        ready = [k]
    k = min(ready, key=lambda k: KEY_LAST.get(k, 0))  # round robin
    KEY_LAST[k] = time.time()
    return k


def gemini_quota_left():
    """True while at least one key can still use at least one voice model today"""
    keys = [k for k in tts_keys() if k not in KEY_DEAD]
    models = [m for m in NEW_TTS + OLD_TTS if m not in TTS_STATE["bad_models"]]
    return any((k, m) not in DAY_OUT for k in keys for m in models)


def _line_until_quota_ends(make, tries=6):
    """A line that failed is tried again (after a short wait) as long as Gemini's daily limit is not over -
    a busy minute or a hiccup never sends the whole video to the slower voices."""
    for i in range(tries):
        if make():
            return True
        if TTS_STATE["off"] or not gemini_quota_left():
            return False
        log(f"    voice line failed but the free limit is not over - trying again ({i + 1})")
        time.sleep(30 + 30 * i)
    return False


def _tts_call(requests_to_try):
    """requests_to_try: [(model, url, body)] in order of preference. Returns raw audio bytes or None."""
    import base64 as _b64
    for model, url, body in requests_to_try:
        if model in TTS_STATE["bad_models"]:
            continue
        for _ in range(14):
            key = _pick_key(model)
            if not key:
                break                                     # this model's daily limit is used up on all keys
            try:
                r = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                  json=body, timeout=180)
            except Exception as e:
                log(f"    voice request failed: {str(e)[:100]}")
                time.sleep(3)
                continue
            if r.status_code == 429:
                kind, wait = _429_kind(r)
                if kind == "day":
                    DAY_OUT.add((key, model))
                else:
                    KEY_COOL[key] = time.time() + min(wait, 65) + 1
                continue
            if r.status_code in (401, 403):
                KEY_DEAD.add(key)
                continue
            if r.status_code in (400, 404):
                low = r.text.lower()
                if r.status_code == 404 or any(w in low for w in ("model", "not found", "unsupported", "invalid")):
                    TTS_STATE["bad_models"].add(model)
                    log(f"    voice model {model}: not usable this way ({r.status_code})")
                    break
            if not r.ok:
                time.sleep(2)
                continue
            try:
                b64 = _find_audio(r.json())
            except Exception:
                b64 = None
            if b64:
                return _b64.b64decode(b64)
    return None


def _audio_file(data, out_wav, sr, trim=True):
    raw = out_wav + ".raw"
    with open(raw, "wb") as f:
        f.write(data)
    inp = ["-i", raw] if data[:4] == b"RIFF" else ["-f", "s16le", "-ar", "24000", "-ac", "1", "-i", raw]
    af = (["-af", "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                  "silenceremove=start_periods=1:start_threshold=-50dB,areverse"] if trim else [])
    _run(["ffmpeg", "-y", "-loglevel", "error"] + inp + af + ["-ac", "1", "-ar", str(sr), out_wav])
    os.remove(raw)
    return float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                       "default=nw=1:nk=1", out_wav]).strip() or 0)


def _single_body(model, text, voice, style, lang_label):
    if model in NEW_TTS:
        return (model, f"{GEMINI_BASE}/interactions",
                {"model": model, "input": [{"type": "user_input", "content": [{
                    "type": "text", "text": tts_tags(text),
                    "annotations": [{"type": "speech_metadata", "speaker": "Speaker1", "style": style[:1500]}]}]}],
                 "response_format": {"type": "audio"},
                 "generation_config": {"speech_config": {"speakers": [
                     {"speaker": "Speaker1", "voice": voice},
                     {"speaker": "Unused", "voice": "Puck" if voice != "Puck" else "Kore"}]}}})
    return (model, f"{GEMINI_BASE}/models/{model}:generateContent",
            {"contents": [{"parts": [{"text": f"You are a voice actor in a {lang_label} audio drama. Perform it like "
                                              f"this: {style}\nSay only these words:\n{strip_tags(text)}"}]}],
             "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                 "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}})


def _multi_bodies(script, notes, speakers, lang_label):
    """speakers: [(label, voice)] (max 2)."""
    out = []
    for model in NEW_TTS:
        out.append((model, f"{GEMINI_BASE}/interactions",
                    {"model": model, "input": [{"type": "user_input", "content": [{
                        "type": "text", "text": script,
                        "annotations": [{"type": "speech_metadata", "style": notes[:1500]}]}]}],
                     "response_format": {"type": "audio"},
                     "generation_config": {"speech_config": [{"speaker": s, "voice": v} for s, v in speakers]}}))
    for model in OLD_TTS:
        out.append((model + "#multi", f"{GEMINI_BASE}/models/{model}:generateContent",
                    {"contents": [{"parts": [{"text": f"{notes}\nPerform this {lang_label} audio drama scene:\n{script}"}]}],
                     "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"multiSpeakerVoiceConfig": {
                         "speakerVoiceConfigs": [{"speaker": s, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}}
                                                 for s, v in speakers]}}}}))
    return out


def _split_at_pauses(wav, plains):
    """Cut one recording of several lines at its pauses. Returns [numpy arrays] or None if unsure."""
    import numpy as np
    from scipy.io import wavfile
    sr, a = wavfile.read(wav)
    a = a.astype("float32")
    n = len(plains)
    if n == 1:
        return [a], sr
    hop = int(sr * 0.02)
    rms = np.array([np.sqrt((a[i:i + hop] ** 2).mean()) for i in range(0, len(a) - hop, hop)])
    if rms.size == 0:
        return None
    quiet = rms < max(rms.max() * 0.04, 1e-6)
    runs, i = [], 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if (j - i) * 0.02 >= 0.25:
                runs.append(((j - i), (i + j) // 2))
            i = j
        else:
            i += 1
    if len(runs) < n - 1:
        return None
    cuts = sorted(c for _, c in sorted(runs, reverse=True)[:n - 1])
    bounds = [0] + [c * hop for c in cuts] + [len(a)]
    segs = [a[bounds[k]:bounds[k + 1]] for k in range(n)]
    total_chars = sum(max(1, len(p)) for p in plains)
    total = len(a) / sr
    for seg, p in zip(segs, plains):                  # each piece must fit its line's length
        want = total * max(1, len(p)) / total_chars
        if not (0.4 * want <= len(seg) / sr <= 2.4 * want + 0.4):
            return None
    return segs, sr


def tts_gemini(voice_text, voice, style, lang_label, out_wav, sr=44100, max_tries=2):
    """One line with the expressive voice (replaces the older version: now rotates keys on per-minute limits)."""
    if TTS_STATE["off"] or not tts_keys():
        return False
    plain_len = len(strip_tags(voice_text))
    for _ in range(max_tries):
        data = _tts_call([_single_body(m, voice_text, voice, style, lang_label)
                          for m in (([env("GEMINI_TTS_MODEL")] if env("GEMINI_TTS_MODEL") else []) +
                                    list(NEW_TTS) + list(OLD_TTS))])
        if data is None:
            TTS_STATE["off"] = True
            log("  expressive voice: free limit used up on all keys")
            return False
        d = _audio_file(data, out_wav, sr)
        if max(0.4, plain_len / 40) <= d <= plain_len / 3 + 6:
            return True
    return False


def tts_gemini_batch(items, lang_label, sr=44100, minutes=45):
    """items (in story order): dict(text, plain, voice, who, feel, spk, out). Voices them in groups of up to
    6 lines with at most 2 speakers per request; any group that cannot be cut cleanly is voiced line by line.
    Returns True only if EVERY line was made (all-or-none keeps each voice the same through the video)."""
    import numpy as np
    from scipy.io import wavfile
    t0 = time.time()
    groups, cur = [], []
    for it in items:
        spk = {x["spk"] for x in cur} | {it["spk"]}
        if cur and (len(spk) > 2 or len(cur) >= 6 or sum(len(x["plain"]) for x in cur) + len(it["plain"]) > 650):
            groups.append(cur)
            cur = []
        cur.append(it)
    if cur:
        groups.append(cur)
    log(f"  {len(items)} lines in {len(groups)} voice requests (keys: {len(tts_keys())})")
    done = 0
    for gi, g in enumerate(groups):
        if TTS_STATE["off"]:
            return False
        el = time.time() - t0
        # slow is fine - Gemini is still the fastest good voice. We only stop when its free limit is really
        # over (TTS_STATE off / a failed line) or after a hard safety cap so the GitHub job is never killed.
        if el > float(env("TTS_MAX_MINUTES") or 180) * 60:
            log("  expressive voices: safety time limit reached")
            return False
        ok = False
        spk = []
        for x in g:
            if x["spk"] not in [s[0] for s in spk]:
                spk.append((x["spk"], x["voice"], x["who"]))
        plains = [x["plain"] for x in g]
        if len(g) > 1:
            if len(spk) == 1:
                text = "\n<long pause>\n".join(x["text"] for x in g)
                style = (f"Character: {spk[0][2]}. Read these {len(g)} lines in order, with a clear long pause "
                         "between lines. Feeling of each line: " +
                         "; ".join(f"line {k + 1}: {x['feel']}" for k, x in enumerate(g)) + ". " + PRONOUNCE.get(
                             g[0].get("lang", "bn"), ""))
                data = _tts_call([_single_body(m, text, spk[0][1], style, lang_label) for m in NEW_TTS + OLD_TTS])
            else:
                labels = {s[0]: f"Speaker{k + 1}" for k, s in enumerate(spk)}
                script = "\n".join(f"{labels[x['spk']]}: {x['text']}" for x in g)
                notes = (" ".join(f"{labels[s[0]]} is {s[2]}." for s in spk) +
                         " Leave a clear pause between lines. Feeling of each line: " +
                         "; ".join(f"line {k + 1}: {x['feel']}" for k, x in enumerate(g)) + ". " +
                         PRONOUNCE.get(g[0].get("lang", "bn"), ""))
                data = _tts_call(_multi_bodies(script, notes, [(labels[s[0]], s[1]) for s in spk], lang_label))
            if data:
                tmp = g[0]["out"] + ".group.wav"
                _audio_file(data, tmp, sr, trim=True)
                cut = _split_at_pauses(tmp, plains)
                os.remove(tmp)
                if cut:
                    segs, rate = cut
                    for x, seg in zip(g, segs):
                        wavfile.write(x["out"] + ".seg.wav", rate, seg.astype(np.int16))
                        _audio_file(open(x["out"] + ".seg.wav", "rb").read(), x["out"], sr, trim=True)
                        os.remove(x["out"] + ".seg.wav")
                    ok = True
        if not ok:                                    # one line per request for this group
            for x in g:
                if not _line_until_quota_ends(lambda: tts_gemini(
                        x["text"], x["voice"],
                        f"Character: {x['who']}. Emotion: {x['feel']}. " + PRONOUNCE.get(x.get("lang", "bn"), ""),
                        lang_label, x["out"], sr)):
                    return False
        done += len(g)
        log(f"  voices: {done}/{len(items)} lines ({(time.time() - t0) / 60:.1f} min)")
    return True


def parler_ok():          # the free on-GitHub model (slow, but no daily limit): used when Gemini's limit is over
    return bool(env("HF_TOKEN")) and env("USE_FREE_MODEL") != "0" and not PARLER["off"]


def ensure_parler():
    """Install the free voice model's tools only on the days they are needed (saves time on normal days)."""
    try:
        import torch, torchaudio  # noqa: F401
        from parler_tts import ParlerTTSForConditionalGeneration  # noqa: F401
        return True
    except Exception:
        pass
    log("  installing the free voice model (a few minutes) ...")
    try:
        pip = [sys.executable, "-m", "pip", "install", "-q"]
        subprocess.run(pip + ["torch==2.5.1", "torchaudio==2.5.1", "--index-url",
                              "https://download.pytorch.org/whl/cpu"], check=True, timeout=1500)
        subprocess.run(pip + ["git+https://github.com/huggingface/parler-tts.git", "soundfile"], check=True,
                       timeout=1500)
        import importlib
        importlib.invalidate_caches()
        from parler_tts import ParlerTTSForConditionalGeneration  # noqa: F401,F811
        return True
    except Exception as e:
        log("  free voice model could not be installed:", str(e)[:200])
        PARLER["off"] = True
        return False


# ===================== v9: correct request shape for the newest voice models (3.8 Flash TTS) =====================
# Each line is its own text block with its own speaker + acting style (per-line feeling!). The newest models
# have their OWN daily limit, separate from the older ones, so using them adds a lot of free capacity.
API_REV = {"Api-Revision": "2026-05-20"}
_SEEN_400 = set()


def _tts_call(requests_to_try):
    """requests_to_try: [(model_key, model, url, body, extra_headers)]. Returns audio bytes or None."""
    import base64 as _b64
    for item in requests_to_try:
        key_name, model, url, body, extra = item if len(item) == 5 else (item[0], item[0], item[1], item[2], {})
        if key_name in TTS_STATE["bad_models"]:
            continue
        for _ in range(14):
            key = _pick_key(model)
            if not key:
                break
            hdr = {"x-goog-api-key": key, "Content-Type": "application/json", **(extra or {})}
            try:
                r = requests.post(url, headers=hdr, json=body, timeout=180)
            except Exception as e:
                log(f"    voice request failed: {str(e)[:100]}")
                time.sleep(3)
                continue
            if r.status_code == 429:
                kind, wait = _429_kind(r)
                if kind == "day":
                    DAY_OUT.add((key, model))
                else:
                    KEY_COOL[key] = time.time() + min(wait, 65) + 1
                continue
            if r.status_code in (401, 403):
                KEY_DEAD.add(key)
                continue
            if r.status_code in (400, 404):
                TTS_STATE["bad_models"].add(key_name)
                if key_name not in _SEEN_400:
                    _SEEN_400.add(key_name)
                    log(f"    voice model {key_name}: {r.status_code} {r.text[:220]}")
                break
            if not r.ok:
                time.sleep(2)
                continue
            try:
                b64 = _find_audio(r.json())
            except Exception:
                b64 = None
            if b64:
                return _b64.b64decode(b64)
    return None


def _requests_for(turns, speakers, lang_label, extra_note=""):
    """turns: [(speaker_label, text_with_<tags>, style)], speakers: [(label, voice)] (1 or 2).
    Returns every way of asking, best first."""
    if lang_label == "Bengali":
        lang_label = "Kolkata (West Bengal, India) Bengali"
    multi = len(speakers) > 1
    out = []
    # Interactions API (docs): input = [{type: user_input, content: [text turns, each with its speaker]}],
    # speech_config = {speakers: [{speaker, voice}]} - every turn names a speaker that is in that list
    sc = {"speakers": [{"speaker": s, "voice": v} for s, v in speakers]}     # (no "mode": the API refuses it)
    if len(sc["speakers"]) == 1:      # the API wants exactly 2 voices listed; the 2nd one simply never speaks
        sc["speakers"].append({"speaker": "Unused", "voice": "Puck" if speakers[0][1] != "Puck" else "Kore"})
    for model in NEW_TTS:
        blocks = [{"type": "text", "text": tts_tags(t) + (" ... ..." if k < len(turns) - 1 else ""),
                   "annotations": [{"type": "speech_metadata", "speaker": s, "style": (st + " " + extra_note)[:900]}]}
                  for k, (s, t, st) in enumerate(turns)]
        out.append((model + "#blocks", model, f"{GEMINI_BASE}/interactions",
                    {"model": model, "input": [{"type": "user_input", "content": blocks}],
                     "response_format": {"type": "audio"}, "generation_config": {"speech_config": sc}}, API_REV))
    for model in OLD_TTS:
        plain = "\n".join((f"{s}: " if multi else "") + strip_tags(t) for s, t, st in turns)
        notes = " ".join(f"Line {k + 1}: {st}." for k, (s, t, st) in enumerate(turns))
        cfg = ({"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
            {"speaker": s, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}} for s, v in speakers]}}
            if multi else {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": speakers[0][1]}}})
        out.append((model + ("#multi" if multi else "#single"), model, f"{GEMINI_BASE}/models/{model}:generateContent",
                    {"contents": [{"parts": [{"text": f"You are voice actors in a {lang_label} audio drama. {extra_note} "
                                                      f"{notes} Leave a clear pause between lines.\n{plain}"}]}],
                     "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": cfg}}, {}))
    return out


def tts_gemini(voice_text, voice, style, lang_label, out_wav, sr=44100, max_tries=2):
    """One line with the expressive voice."""
    if TTS_STATE["off"] or not tts_keys():
        return False
    plain_len = len(strip_tags(voice_text))
    for _ in range(max_tries):
        data = _tts_call(_requests_for([("Speaker1", voice_text, style)], [("Speaker1", voice)], lang_label))
        if data is None:
            TTS_STATE["off"] = True
            log("  expressive voice: free limit used up on all keys")
            return False
        d = _audio_file(data, out_wav, sr)
        if max(0.4, plain_len / 40) <= d <= plain_len / 3 + 6:
            return True
    return False


def tts_gemini_batch(items, lang_label, sr=44100, minutes=45):
    """items (story order): dict(text, plain, voice, who, feel, spk, out, lang). Up to 6 lines and 2 speakers per
    request, each line with its own feeling; cut apart at the pauses. All lines or none."""
    import numpy as np
    from scipy.io import wavfile
    t0 = time.time()
    groups, cur = [], []
    for it in items:
        spk = {x["spk"] for x in cur} | {it["spk"]}
        if cur and (len(spk) > 2 or len(cur) >= 6 or sum(len(x["plain"]) for x in cur) + len(it["plain"]) > 650):
            groups.append(cur)
            cur = []
        cur.append(it)
    if cur:
        groups.append(cur)
    log(f"  {len(items)} lines in {len(groups)} voice requests (keys: {len(tts_keys())})")
    done = 0
    for gi, g in enumerate(groups):
        if TTS_STATE["off"]:
            return False
        el = time.time() - t0
        # slow is fine - Gemini is still the fastest good voice. We only stop when its free limit is really
        # over (TTS_STATE off / a failed line) or after a hard safety cap so the GitHub job is never killed.
        if el > float(env("TTS_MAX_MINUTES") or 180) * 60:
            log("  expressive voices: safety time limit reached")
            return False
        spk = []
        for x in g:
            if x["spk"] not in [s[0] for s in spk]:
                spk.append((x["spk"], x["voice"], x["who"]))
        labels = {s[0]: f"Speaker{k + 1}" for k, s in enumerate(spk)}
        lang = g[0].get("lang", "bn")
        note = " ".join(f"{labels[s[0]]} is {s[2]}." for s in spk) + " " + PRONOUNCE.get(lang, "")
        turns = [(labels[x["spk"]], x["text"], x["feel"]) for x in g]
        ok = False
        if len(g) > 1:
            data = _tts_call(_requests_for(turns, [(labels[s[0]], s[1]) for s in spk], lang_label, note))
            if data:
                tmp = g[0]["out"] + ".group.wav"
                _audio_file(data, tmp, sr, trim=True)
                cut = _split_at_pauses(tmp, [x["plain"] for x in g])
                os.remove(tmp)
                if cut:
                    segs, rate = cut
                    for x, seg in zip(g, segs):
                        wavfile.write(x["out"] + ".seg.wav", rate, seg.astype(np.int16))
                        _audio_file(open(x["out"] + ".seg.wav", "rb").read(), x["out"], sr, trim=True)
                        os.remove(x["out"] + ".seg.wav")
                    ok = True
        if not ok:
            for x in g:
                if not _line_until_quota_ends(lambda: tts_gemini(
                        x["text"], x["voice"], f"{x['who']}. {x['feel']}. " + PRONOUNCE.get(lang, ""),
                        lang_label, x["out"], sr)):
                    return False
        done += len(g)
        log(f"  voices: {done}/{len(items)} lines ({(time.time() - t0) / 60:.1f} min)")
    return True


# ===================== v10: hooks that keep people watching + truly frightening horror =====================
HOOK_RULES = """
KEEP THEM WATCHING (very important - most viewers leave in the first 10 seconds):
- COLD OPEN: the first 1-2 lines jump to the most gripping moment of the story (a scream, a shock, a funny
  disaster, a mystery) - then "but how did it all begin? ..." and the story starts. Never start with a slow
  introduction, never with "once upon a time" alone.
- In the first 20 seconds promise something the listener must wait for ("what was behind that door - you will
  know only at the very end").
- OPEN LOOPS: every 2-3 scenes raise a new question before answering the old one.
- Every scene ends on a small cliffhanger, a surprise or a strong feeling. Change the rhythm often: fast tense
  lines, then a quiet moment, then a shock.
- Around the middle, the narrator speaks directly to the listener once ("what would YOU have done? stay till the end").
- The ending pays off every promise with a twist nobody expects, then ONE line teasing the next story.
"""

HORROR_DREAD = """
MAKE IT GENUINELY TERRIFYING - the listener's heart must pound (but no gore, no blood details, no harm to
children, nothing sexual - the fear must be in the mind):
- REALISTIC FIRST: it must feel like a TRUE incident someone in Bengal really lived through. Real, specific
  places (a railway quarter in Bardhaman, a zamindar bari in Nadia, a hostel in north Kolkata, a pond in a
  Sundarban village), real daily life (load-shedding, a hurricane lamp, the last local train, a night shift,
  a phone with 2% battery), believable ordinary people with names, jobs and families. Exact times ("রাত তখন
  দুটো বেজে সতেরো"), exact small details. No fantasy, no silly monsters - the supernatural enters a very real life.
- STEP-BY-STEP DREAD, every step worse than the last:
  1) something tiny is WRONG (a smell of burnt hair, a second set of footprints, a voice that knows a secret);
  2) it is explained away... then it happens again, closer;
  3) proof it is real - nobody believes the hero, the hero is alone;
  4) the ghost gets personal - it uses the hero's name, a dead relative's voice, things only family knew;
  5) a trap: no escape, the light goes out, the door is locked from OUTSIDE;
  6) the face-to-face moment, described slowly, line by line;
  7) a twist that turns everything upside down, and a last line that keeps people awake.
- Every scene ends on a question or a threat the listener cannot ignore. Never relax the tension for long;
  a short calm moment only to make the next scare hit harder.
- Use the senses and the body: ice-cold breath on the neck, hair standing up, the heartbeat in the ears,
  the throat too dry to scream, a hand that is suddenly holding yours in the dark.
- Fear in the WRITING itself: short broken lines, '...', silence, whispers, counting breaths; long sentences
  only when the dread is slowly growing.
- The ghost has rules, patience and a terrible, believable reason (an old injustice, a broken promise, a
  hidden death) - it is clever and it wants something from THIS person.
- The listener must feel it could happen to THEM tonight, in their own house.
- A big story is fine: if there is too much for one video, it will be told in parts - then every part ends
  on a cliffhanger that makes people desperate for the next part.
- SMOOTH, COMPLETE STORYTELLING - nothing may feel missing or skipped:
  * every scene follows from the one before; when time or place changes, the narrator says so in one line
    ("সেই রাতে আর ঘুম এল না। পরদিন সন্ধ্যায়...");
  * every character is introduced (who they are, why they are there) BEFORE they act or speak;
  * every strange event is shown happening, never jumped over ("suddenly he was in the forest" is NOT allowed -
    show how he got there);
  * every question the story raises is answered by the end (or deliberately left for the next part);
  * the listener always knows where we are, what time it is and who is in the room.
- Before writing, plan the whole plot (beginning - rising dread - trap - face-to-face - twist), then write it
  scene by scene without shortcuts.
"""


# ===================== v10: high-quality, eye-catching thumbnails =====================
HQ_THUMB_MODEL = "@cf/leonardo/lucid-origin"   # sharper, richer pictures (used for the thumbnail only)


def hq_image(prompt, out, seed=0, w=1280, h=720):
    """Thumbnail picture from the higher-quality model on the same free Cloudflare accounts.
    Returns False (and the bot falls back to the normal model) if it is not available or the limit is reached."""
    import base64 as _b64
    if env("HQ_THUMB") == "0":
        return False
    accounts = [(env("CF_ACCOUNT_ID" + s), env("CF_API_TOKEN" + s)) for s in ("", "_2", "_3", "_4")]
    for acc, tok in [a for a in accounts if a[0] and a[1]]:
        try:
            r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{HQ_THUMB_MODEL}",
                              headers={"Authorization": f"Bearer {tok}"},
                              json={"prompt": prompt[:2000], "width": w, "height": h, "steps": 25, "guidance": 4.5,
                                    "seed": int(seed) % 2_000_000_000}, timeout=180)
            if not r.ok:
                log(f"  HQ thumbnail model: {r.status_code} {r.text[:150]}")
                continue
            js = r.json()
            b64 = (js.get("result") or {}).get("image") if isinstance(js, dict) else None
            if not b64:
                continue
            with open(out, "wb") as f:
                f.write(_b64.b64decode(b64))
            Image.open(out).convert("RGB").resize((w, h)).save(out, quality=95)
            log("  thumbnail picture made with the high-quality model")
            return True
        except Exception as e:
            log(f"  HQ thumbnail model failed: {str(e)[:120]}")
    return False


def pop_subject(base_img, out, glow=(255, 255, 255), size=(1280, 720)):
    """YouTube-style 'sticker' look: the main character is cut out, made a little bigger and pushed to the
    front with a bright outline and shadow; the background gets darker and softer. Returns True if done."""
    import numpy as np
    try:
        from rembg import remove, new_session
        W_, H_ = size
        img = Image.open(base_img).convert("RGB").resize((W_, H_))
        m = remove(img, session=new_session("isnet-general-use"), only_mask=True).convert("L").resize((W_, H_))
        a = np.array(m).astype("float32") / 255
        cover = (a > 0.5).mean()
        if cover < 0.04 or cover > 0.6:
            return False
        ys, xs = np.nonzero(a > 0.5)
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max(), ys.max()
        subj = img.copy()
        subj.putalpha(m)
        bw_, bh_ = x1 - x0 + 1, y1 - y0 + 1
        if bh_ > 1.3 * bw_:                          # a full standing figure: keep head + upper body (big face)
            y1 = y0 + int(bh_ * 0.62)
        subj = subj.crop((x0, y0, x1 + 1, y1 + 1))
        sc = (H_ * 1.02) / subj.height                # fill the height - the face must be BIG
        if subj.width * sc > W_ * 0.56:
            sc = (W_ * 0.56) / subj.width
        subj = subj.resize((int(subj.width * sc), int(subj.height * sc)), Image.LANCZOS)
        # background: the old subject painted out, then softer and darker, so the new one pops
        import cv2
        hole = cv2.dilate((a > 0.3).astype("uint8") * 255, np.ones((41, 41), "uint8"))
        small = cv2.inpaint(cv2.resize(np.array(img), (W_ // 2, H_ // 2)), cv2.resize(hole, (W_ // 2, H_ // 2)), 7,
                            cv2.INPAINT_TELEA)
        filled = np.where(hole[..., None] > 0, cv2.resize(small, (W_, H_)), np.array(img))
        bg = Image.fromarray(filled.astype("uint8")).filter(ImageFilter.GaussianBlur(6))
        bg = Image.blend(bg, Image.new("RGB", size, (0, 0, 0)), 0.32)
        canvas = bg.convert("RGBA")
        px = max(int(W_ * 0.46), W_ - subj.width - int(W_ * 0.02))
        py = H_ - subj.height + 8
        al = subj.split()[3]
        # shadow + bright outline
        sh = Image.new("RGBA", subj.size, (0, 0, 0, 0))
        sh.putalpha(al.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.8)))
        canvas.alpha_composite(sh, (px + 14, py + 10))
        ring = al.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(2))
        outline = Image.new("RGBA", subj.size, glow + (0,))
        outline.putalpha(ring)
        halo = Image.new("RGBA", subj.size, glow + (0,))
        halo.putalpha(al.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(16)).point(lambda v: int(v * 0.7)))
        canvas.alpha_composite(halo, (px, py))
        canvas.alpha_composite(outline, (px, py))
        canvas.alpha_composite(subj, (px, py))
        canvas.convert("RGB").save(out, quality=95)
        return True
    except Exception as e:
        log(f"  subject pop-out skipped: {str(e)[:120]}")
        return False


# ===================== v11: make early, publish exactly on time =====================
# The video is made about 3 hours early, uploaded as a SCHEDULED post (Facebook) / scheduled premiere-free
# publish (YouTube publishAt), so it goes live exactly at the slot time even if making it took long.
PUBLISH = {"at": None, "used": False}


def plan_publish(slot):
    """slot like '2026-10-23@13' -> publish at 13:00 India time that day."""
    PUBLISH["at"], PUBLISH["used"] = None, False
    if not slot or env("SCHEDULE_POSTS") == "0":
        return None
    try:
        day, hour = slot.split("@")
        y, m, d = (int(x) for x in day.split("-"))
        PUBLISH["at"] = dt.datetime(y, m, d, int(hour), 0, tzinfo=IST)
        log(f"Will publish at {PUBLISH['at'].strftime('%d %b %H:%M')} India time")
    except Exception:
        PUBLISH["at"] = None
    return PUBLISH["at"]


def publish_time():
    """The planned time if it is still at least 15 minutes away (else: post right now)."""
    at = PUBLISH["at"]
    if at and (at - dt.datetime.now(IST)).total_seconds() >= 15 * 60:
        PUBLISH["used"] = True
        return at
    return None


def voice_minutes(default=45):
    """How long the expressive voices may take: all the spare time before the post time (minus ~40 minutes
    for making and uploading the video), at least 30, at most 120 minutes."""
    at = PUBLISH.get("at")
    if not at:
        return default
    left = (at - dt.datetime.now(IST)).total_seconds() / 60 - 40
    return int(max(30, min(120, left)))


def wait_for_publish():
    """Before comments / replies: wait until the scheduled video is live."""
    at = PUBLISH["at"]
    if not (PUBLISH["used"] and at):
        return
    left = (at - dt.datetime.now(IST)).total_seconds() + 60
    if left > 0:
        log(f"  waiting {left / 60:.0f} min until the video is live, then comments")
        time.sleep(left)


# ===================== v12: poster-style thumbnails (series title + episode name over a cinematic picture) ==========
THUMB_FONTS = {
    "cartoon": "https://raw.githubusercontent.com/google/fonts/main/ofl/balooda2/BalooDa2%5Bwght%5D.ttf",
    "horror": "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifbengali/NotoSerifBengali%5Bwdth,wght%5D.ttf",
}


def thumb_font(style, size, fallback, weight=b"ExtraBold"):
    """Beautiful Bengali display font (downloaded once, free Google Fonts); falls back to the normal font."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work", f"thumbfont_{style}.ttf")
    try:
        if not os.path.exists(path) and not env("MOCK"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            r = requests.get(THUMB_FONTS[style], timeout=60)
            if r.ok and len(r.content) > 50000:
                open(path, "wb").write(r.content)
        if os.path.exists(path):
            f = ImageFont.truetype(path, size)
            try:
                names = f.get_variation_names()
                want = weight if weight in names else (b"Black" if b"Black" in names else names[-1])
                f.set_variation_by_name(want)
            except Exception:
                pass
            return f
    except Exception as e:
        log(f"  thumbnail font: {str(e)[:80]}")
    return ImageFont.truetype(fallback, size)


def _gradient_text(img, xy, text, font, top, bottom, stroke, stroke_w, glow=None, shadow=True, grunge=False):
    """Draws text filled with a vertical colour gradient, dark outline, soft shadow and optional glow."""
    import numpy as np
    W_, H_ = img.size
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=font, fill=255)
    outl = Image.new("L", img.size, 0)
    ImageDraw.Draw(outl).text(xy, text, font=font, fill=255, stroke_width=stroke_w, stroke_fill=255)
    base = img.convert("RGBA")
    if shadow:
        sh = outl.filter(ImageFilter.GaussianBlur(10))
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer.putalpha(sh.point(lambda v: int(v * 0.85)))
        base = Image.alpha_composite(base, layer.transform(img.size, Image.AFFINE, (1, 0, -6, 0, 1, -8)))
    if glow:
        g = outl.filter(ImageFilter.GaussianBlur(18))
        layer = Image.new("RGBA", img.size, glow + (0,))
        layer.putalpha(g.point(lambda v: int(v * 0.9)))
        base = Image.alpha_composite(base, layer)
    st = Image.new("RGBA", img.size, stroke + (0,))
    st.putalpha(outl)
    base = Image.alpha_composite(base, st)
    bbox = mask.getbbox() or (0, 0, W_, H_)
    y0, y1 = bbox[1], max(bbox[3], bbox[1] + 1)
    t = np.clip((np.arange(H_) - y0) / (y1 - y0), 0, 1)[:, None, None]
    grad = (np.array(top)[None, None, :] * (1 - t) + np.array(bottom)[None, None, :] * t)
    grad = np.repeat(grad, W_, axis=1).astype("uint8")
    fill = Image.fromarray(grad, "RGB").convert("RGBA")
    a = mask
    if grunge:                                       # worn, scratched horror letters
        rnd = np.random.default_rng(3)
        noise = (rnd.random((H_ // 3 + 1, W_ // 3 + 1)) > 0.22).astype("uint8") * 255
        noise = Image.fromarray(noise).resize(img.size).filter(ImageFilter.GaussianBlur(0.8))
        a = Image.fromarray((np.array(mask).astype("float32") * np.array(noise).astype("float32") / 255).astype("uint8"))
    fill.putalpha(a)
    return Image.alpha_composite(base, fill).convert("RGB")


def poster_thumbnail(base_img, title, subtitle, out, style, fallback_font, size=(1280, 720)):
    """Poster-style thumbnail like big channels: cinematic picture, darkened upper-left, a big series title
    (gold for cartoons, eerie white + blood red for horror), an ornament line and the episode name."""
    from PIL import ImageEnhance
    W_, H_ = size
    deva = any("\u0900" <= ch <= "\u097f" for ch in f"{title}{subtitle}")   # Hindi: the Bengali display fonts lack it
    tf = (lambda st, sz, fb, w=b"ExtraBold": ImageFont.truetype(fb, sz)) if deva else thumb_font
    img = Image.open(base_img).convert("RGB").resize(size)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Color(img).enhance(1.12)
    img = ImageEnhance.Sharpness(img).enhance(1.4)
    shade = Image.new("L", size, 0)                  # soft darkness behind the words (upper-left)
    d = ImageDraw.Draw(shade)
    for i in range(140):
        r = i / 140
        d.ellipse([-W_ * 0.35 * (1 - r) - 60, -H_ * 0.55 * (1 - r) - 60, W_ * 0.62 * (1 - r) + 40,
                   H_ * 0.78 * (1 - r) + 20], fill=int(200 * r ** 0.8))
    shade = shade.filter(ImageFilter.GaussianBlur(40))
    img = Image.composite(Image.new("RGB", size, (5, 5, 12)), img, shade)
    words = str(title).split()
    probe = ImageDraw.Draw(img)

    def fit(lines_, top=165):
        sz = top
        while sz > 50:
            f_ = tf(style, sz, fallback_font)
            if all(probe.textlength(l, font=f_) <= W_ * 0.52 for l in lines_) and sz * (1.08 * len(lines_) + 0.75) <= H_ * 0.44:
                return sz
            sz -= 5
        return sz
    lines = [title]
    big = fit(lines)
    if big < 100 and len(words) >= 2:                # too long for one big line: two lines
        half = len(words) // 2 + len(words) % 2
        lines = [" ".join(words[:half]), " ".join(words[half:])]
        big = fit(lines)
    f = tf(style, big, fallback_font)
    x0, y = 44, 22
    for i, l in enumerate(lines):
        if style == "horror":
            top, bot = ((245, 245, 240), (170, 170, 165)) if i == 0 else ((235, 50, 40), (120, 0, 0))
            img = _gradient_text(img, (x0, y), l, f, top, bot, (10, 5, 5), max(4, big // 22),
                                 glow=(150, 0, 0) if i else None, grunge=True)
        else:
            img = _gradient_text(img, (x0, y), l, f, (255, 244, 170), (230, 150, 20), (70, 30, 0), max(5, big // 18),
                                 glow=(255, 170, 40))
        y += int(big * 1.08)
    # ornament line
    dr = ImageDraw.Draw(img)
    line_w = int(W_ * 0.42)
    yl = y + int(big * 0.12)
    col = (220, 40, 40) if style == "horror" else (240, 190, 70)
    dr.line([(x0 + 10, yl), (x0 + line_w, yl)], fill=col, width=3)
    cx = x0 + 10 + line_w // 2
    dr.polygon([(cx, yl - 9), (cx + 9, yl), (cx, yl + 9), (cx - 9, yl)], fill=col)
    if subtitle:
        sf = tf(style, max(40, int(big * 0.5)), fallback_font, b"Bold")
        sub_y = yl + 18
        if probe.textlength(subtitle, font=sf) > W_ * 0.5:
            sf = tf(style, max(40, int(big * 0.4)), fallback_font, b"Bold")
        img = _gradient_text(img, (x0 + 8, sub_y), subtitle, sf, (255, 255, 255), (225, 225, 225), (0, 0, 0),
                             max(4, sf.size // 14), glow=(0, 0, 0) if style == "horror" else None)
    img.save(out, quality=95)
    return out


THUMB_PROMPT = {
    "cartoon": ("Use case: thumbnail-art. Cinematic 16:9 YouTube episode thumbnail for an original {series} cartoon "
                "episode. A polished, dramatic yet playful hand-painted 2D cartoon scene in {place}. {hero} is the "
                "clear foreground hero on the RIGHT side of the frame, {hero_action}, large expressive face. {second}, placed in the middle or right, never at the left edge. "
                "Visual story: {moment}. Rich authentic Bengali details, cinematic lighting and depth, warm lamps, "
                "deep reds, gold and teal, lively expressions without caricature. Strong simple composition, faces "
                "large and readable at small thumbnail size, clean dark negative space at the upper-left for a title, no faces in the upper-left third. "
                "No text, no letters, no watermark, no logo, no modern objects, no extra foreground characters, no "
                "distorted faces, no malformed hands."),
    "horror": ("Create a cinematic 16:9 horror thumbnail for an original Bengali folk-horror episode. {hero} in the "
               "foreground, {hero_action}, in {place}. {second} Make it unsettling and ghostly but "
               "non-graphic. Visual story: {moment}. Twisted banyan branches, thick mist, dim oil lamps, cold blue "
               "moonlight contrasted with warm amber lantern glow. Photorealistic cinematic Bengali folk-horror "
               "style, dramatic lighting, rich detail, the faces large enough to read at thumbnail size, clear dark "
               "space at the upper-left for the title, no faces in the upper-left third. No text, no letters, no gore, no violence, no modern objects, "
               "no caricature, no malformed hands, no watermark, no logo."),
}


def poster_prompt(style, ti, cast_describe, series, place):
    """Fill the thumbnail formula with THIS story's people and moment."""
    ti = ti if isinstance(ti, dict) else {}
    hero = ti.get("hero") or ""
    second = ti.get("second") or (ti.get("ghost") if style == "horror" else "") or ""
    hero_desc = cast_describe(hero) or hero or "the main character"
    sec_desc = cast_describe(second) or second
    if style == "horror":
        sec_txt = (f"Show a clearly visible, eerie {sec_desc} {ti.get('second_action') or 'in the background'}, with a "
                   "faint supernatural glow; the hero looks toward it with tense focus.") if sec_desc else ""
    else:
        sec_txt = (f"{sec_desc} {ti.get('second_action') or 'reacts in the middle ground'}, with a few softly "
                   "blurred background figures") if sec_desc else "A few softly blurred background figures"
    pl = ti.get("place") or place or "the story's place"
    if style == "horror" and "night" not in pl.lower():
        pl += " at night"
    return " ".join(THUMB_PROMPT[style].format(series=series or "Bengali", place=pl,
                                      hero=hero_desc, hero_action=ti.get("hero_action") or "with a strong expression",
                                      second=sec_txt, moment=ti.get("moment") or ti.get("action") or "").split())


# ===================== v13: Agnes AI pictures - a backup when the Cloudflare free limit is used up =====================
AGNES = {"off": False, "size": None, "model": None, "fails": 0}
AGNES_URL = "https://apihub.agnes-ai.com/v1/images/generations"
AGNES_MODELS = ("agnes-image-2.1-flash", "agnes-image-2.0-flash")
AGNES_SIZES = ("1280x720", "1024x576", "1344x768", "1024x768", "1024x1024")


def agnes_ok():
    return bool(env("AGNES_API_KEY")) and not AGNES["off"] and env("USE_AGNES") != "0"


def _crop_16x9(data):
    """Any picture -> a 16:9 picture (centre cut), as JPEG bytes."""
    import io
    im = Image.open(io.BytesIO(data)).convert("RGB")
    W_, H_ = im.size
    if abs(W_ / H_ - 16 / 9) > 0.03:
        if W_ / H_ > 16 / 9:
            nw = int(H_ * 16 / 9)
            im = im.crop(((W_ - nw) // 2, 0, (W_ - nw) // 2 + nw, H_))
        else:
            nh = int(W_ * 9 / 16)
            top = max(0, int((H_ - nh) * 0.35))           # keep a little more of the top (faces)
            im = im.crop((0, top, W_, top + nh))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=95)
    return out.getvalue()


def agnes_image(prompt):
    """One 16:9 picture from Agnes AI (free API, own key). Returns JPEG bytes; raises when it can't."""
    import base64 as _b64
    if not agnes_ok():
        raise RuntimeError("Agnes not available")
    hdr = {"Authorization": f"Bearer {env('AGNES_API_KEY')}", "Content-Type": "application/json"}
    models = [AGNES["model"]] if AGNES["model"] else list(AGNES_MODELS)
    sizes = [AGNES["size"]] if AGNES["size"] else list(AGNES_SIZES)
    last = ""
    for model in models:
        for size in sizes:
            for fmt in ("b64_json", "url"):
                try:
                    r = requests.post(AGNES_URL, headers=hdr, timeout=240,
                                      json={"model": model, "prompt": prompt[:3000], "size": size, "n": 1,
                                            "response_format": fmt})
                except Exception as e:
                    last = str(e)[:150]
                    continue
                if r.status_code in (401, 403):
                    AGNES["off"] = True
                    raise RuntimeError(f"Agnes key refused ({r.status_code}): {r.text[:150]}")
                if r.status_code == 429:
                    time.sleep(20)
                    last = f"429 {r.text[:150]}"
                    continue
                if not r.ok:
                    last = f"{r.status_code} {r.text[:200]}"
                    continue
                try:
                    d = (r.json().get("data") or [{}])[0]
                    if d.get("b64_json"):
                        data = _b64.b64decode(d["b64_json"])
                    elif d.get("url"):
                        data = requests.get(d["url"], timeout=120).content
                    else:
                        last = "no picture in reply: " + r.text[:150]
                        continue
                    data = _crop_16x9(data)
                except Exception as e:
                    last = str(e)[:150]
                    continue
                AGNES["model"], AGNES["size"], AGNES["fails"] = model, size, 0
                return data
    AGNES["fails"] += 1
    if AGNES["fails"] >= 4:
        AGNES["off"] = True
        log("  Agnes pictures: stopped for this run (kept failing)")
    raise RuntimeError(f"Agnes picture failed: {last}")


# ===================== v14: Facebook quality checklist - square video + short caption =====================
SQ = 1080        # Facebook ranks 1:1 (or 4:5) videos higher on phones than 16:9


def fb_square(video, thumb, workdir):
    """A 1:1 copy of the 16:9 story video for Facebook: the picture shown big (3/4 of the width, gently panning so
    nothing stays hidden), a blurred copy of the same picture above and below. Also a square thumbnail with the
    WHOLE poster visible. Returns (video, thumb); the originals if anything fails or FB_SQUARE=0."""
    if env("FB_SQUARE") == "0":
        return video, thumb
    try:
        out_v = os.path.join(workdir, "facebook_square.mp4")
        fh = int(SQ * 0.75) // 2 * 2
        fw = int(fh * 16 / 9) // 2 * 2
        fy = (SQ - fh) // 2
        fc = (f"[0:v]split[a][b];[a]scale=-2:{SQ},crop={SQ}:{SQ},boxblur=24:2,eq=brightness=-0.20[bg];"
              f"[b]scale={fw}:{fh},crop={SQ}:{fh}:'({fw}-{SQ})/2+({fw}-{SQ})*0.35*sin(2*PI*t/16)':0[fg];"
              f"[bg][fg]overlay=0:{fy},format=yuv420p[v]")
        _run(["ffmpeg", "-y", "-i", video, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-r", "25", "-c:a", "copy",
              "-movflags", "+faststart", out_v])
        out_t = thumb
        if thumb and os.path.exists(thumb):
            t = Image.open(thumb).convert("RGB")
            bg = t.resize((SQ * t.width // t.height, SQ)).crop(((SQ * t.width // t.height - SQ) // 2, 0,
                                                               (SQ * t.width // t.height + SQ) // 2, SQ))
            from PIL import ImageEnhance
            bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(28))).enhance(0.7)
            fg = t.resize((SQ, SQ * t.height // t.width))
            bg.paste(fg, (0, (SQ - fg.height) // 2))
            out_t = os.path.join(workdir, "thumbnail_square.jpg")
            bg.save(out_t, quality=94)
        log("  Facebook: square 1:1 version made")
        return out_v, out_t
    except Exception as e:
        log("  square Facebook version skipped:", str(e)[:200])
        return video, thumb


def fb_caption(description, limit=390):
    """Facebook likes captions of 10-400 characters. Keeps the title, the AI note and the most important lines,
    shortens the long text, then adds as many hashtags as fit."""
    paras = [p.strip() for p in str(description).split("\n\n") if p.strip()]
    tags = []
    if paras and paras[-1].startswith("#"):
        tags = paras.pop().split()
    if not paras:
        return " ".join(tags)[:limit]
    head, rest = paras[0], paras[1:]
    note = [p for p in rest if "AI" in p and len(p) < 90][:1]
    rest = [p for p in rest if p not in note]
    out = [head[:150]]
    tag_room = min(75, len(" ".join(tags[:5])) + 2) if tags else 0      # keep space for ~5 hashtags
    room = lambda: limit - tag_room - len("\n\n".join(out + note)) - 4
    for p in rest:
        if room() <= 25:
            break
        if len(p) + 2 > min(room(), 190):
            cut = p[:min(room(), 190) - 2]
            for sep in ("।", "?", "!", ".", " "):
                if sep in cut[40:]:
                    cut = cut[:cut.rindex(sep) + 1]
                    break
            p = cut.rstrip() + ("…" if not cut.rstrip().endswith(("।", "?", "!", ".")) else "")
        out.append(p)
    out += note
    text = "\n\n".join(out)
    line = ""
    for t in tags:
        if len(text) + len(line) + len(t) + 3 > limit:
            break
        line += (" " if line else "") + t
    return (text + ("\n\n" + line if line else ""))[:limit]


# ===================== v15: daily riddle picture (from today's video - no new picture needed) =====================
def riddle_card(base_img, font_path, title, question, out):
    """1080x1080 card: a blurred frame of today's video, a big title and the riddle."""
    W = H = 1080
    img = Image.open(base_img).convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s), int(img.height * s)))
    l, t = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(8))
    img = Image.blend(img, Image.new("RGB", (W, H), (10, 10, 40)), 0.55)
    d = ImageDraw.Draw(img)
    tl, tf, ts = _fit_text(d, title, font_path, W - 160, 110, lines_max=1)
    tw = d.textlength(tl[0], font=tf)
    d.text(((W - tw) / 2, 110), tl[0], font=tf, fill=(255, 220, 60), stroke_width=7, stroke_fill=(0, 0, 0))
    words, lines, cur = str(question).split(), [], ""
    f = ImageFont.truetype(font_path, 64)
    for w_ in words:
        if d.textlength((cur + " " + w_).strip(), font=f) > W - 170:
            lines.append(cur)
            cur = w_
        else:
            cur = (cur + " " + w_).strip()
    if cur:
        lines.append(cur)
    size = 64 if len(lines) <= 6 else 50
    f = ImageFont.truetype(font_path, size)
    y = max(300, (H - len(lines) * size * 1.45) / 2 + 60)
    for ln_ in lines[:9]:
        tw = d.textlength(ln_, font=f)
        d.text(((W - tw) / 2, y), ln_, font=f, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
        y += size * 1.45
    img.save(out, quality=92)
    return out


def load_json_loose(text):
    """The story JSON from Gemini. Long answers sometimes have a small mistake (a missing comma, a stray quote,
    a cut-off end) - repair it instead of throwing the whole story away."""
    import re as _re
    t = str(text).strip()
    t = _re.sub(r"^```(?:json)?|```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception as first:
        err = first
    try:
        return json.loads(t, strict=False)          # raw line breaks / tabs inside strings
    except Exception:
        pass
    try:
        try:
            import json_repair                       # pip package json-repair
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "json-repair"], timeout=120)
            import json_repair
        out = json_repair.loads(t)
        if isinstance(out, dict) and out:
            log("  story JSON had a small mistake - repaired")
            return out
    except Exception:
        pass
    # simple repairs: trailing commas, missing commas between } {, ] [, "..." "..."
    u = _re.sub(r",\s*([}\]])", r"\1", t)
    u = _re.sub(r"([}\]\"])\s*\n\s*([{\[\"])", r"\1,\n\2", u)
    try:
        out = json.loads(u, strict=False)
        log("  story JSON had a small mistake - repaired")
        return out
    except Exception:
        raise err


FREEMODEL = {"models": None}


def freemodel_text(prompt, max_tokens=32000):
    """Backup story writer when every Gemini model is busy: FreeModel (OpenAI-style API, small free monthly
    allowance). Needs the GitHub secret FREEMODEL_API_KEY. Returns the answer text or None."""
    key = env("FREEMODEL_API_KEY")
    if not key:
        return None
    base = (env("FREEMODEL_BASE") or "https://freemodel.in/v1").rstrip("/")
    hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if FREEMODEL["models"] is None:
        names = []
        try:
            r = requests.get(f"{base}/models", headers=hdr, timeout=30)
            names = [m.get("id", "") for m in r.json().get("data", [])]
        except Exception as e:
            log("  FreeModel: could not list models:", str(e)[:120])
        # best writers first (large, good at Bengali/Hindi), cheap ones last
        pref = ("sonnet", "gpt-5.5", "gpt-5.4", "opus", "gemini", "gpt-5", "haiku", "mini")
        rank = lambda n: next((i for i, p in enumerate(pref) if p in n.lower()), len(pref))
        names = [n for n in names if n and not any(x in n.lower() for x in ("embed", "tts", "image", "whisper",
                                                                             "codex", "audio"))]
        names = ([env("FREEMODEL_MODEL")] if env("FREEMODEL_MODEL") else []) + sorted(names, key=rank)
        FREEMODEL["models"] = list(dict.fromkeys(names))[:3]
        log("  FreeModel models:", ", ".join(FREEMODEL["models"]) or "none")
    for model in FREEMODEL["models"]:
        try:
            log(f"Writing story with FreeModel {model} (backup) ...")
            r = requests.post(f"{base}/chat/completions", headers=hdr, timeout=420, json={
                "model": model, "max_tokens": max_tokens, "temperature": 1.0,
                "messages": [{"role": "system", "content": "Answer with ONE valid JSON object only - no other text."},
                             {"role": "user", "content": prompt}]})
            if not r.ok:
                log(f"  FreeModel {model}: {r.status_code} {r.text[:150]}")
                continue
            text = r.json()["choices"][0]["message"]["content"]
            if text and "{" in text:
                return text[text.find("{"):text.rfind("}") + 1]
        except Exception as e:
            log(f"  FreeModel {model} failed: {str(e)[:150]}")
    return None


# ----------------------------------------------------------------- subtitles in step with the voice
VOICE_SHAPE = {}      # (text, seconds) -> how far the voice has got (0..1) every 20 ms


def remember_voice(text, a, sr):
    """Called for every spoken line: where in the line the voice really sounds (pauses skipped), so each piece
    of the subtitle comes up exactly when those words are said - not earlier, not later."""
    try:
        import numpy as np
        hop = int(sr * 0.02)
        n = len(a) // hop
        if n < 3:
            return
        rms = np.sqrt(np.mean(np.asarray(a[:n * hop], dtype=np.float64).reshape(n, hop) ** 2, axis=1))
        voiced = (rms > max(0.01, 0.12 * np.percentile(rms, 95))).astype(float)
        cum = np.cumsum(voiced)
        if cum[-1] <= 0:
            return
        VOICE_SHAPE[(str(text), round(len(a) / sr, 2))] = cum / cum[-1]
    except Exception:
        pass


def sub_times(text, dur, chunks):
    """[(start, end)] inside the line for every subtitle piece, from the real voice when we have it."""
    total = sum(len(c) for c in chunks) or 1
    fr, acc = [], 0
    for c in chunks:
        fr.append(acc / total)
        acc += len(c)
    shape = VOICE_SHAPE.get((str(text), round(dur, 2)))
    if shape is None:
        starts = [f * dur for f in fr]
    else:
        import numpy as np
        starts = [float(np.searchsorted(shape, f + 1e-6)) * 0.02 if f > 0 else 0.0 for f in fr]
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] - 0.14 if k + 1 < len(starts) else dur + 0.2   # never two pieces on screen at once
        out.append((max(0.0, s - 0.12), max(s + 0.3, e)))                  # a moment early, like TV subtitles
    return out
