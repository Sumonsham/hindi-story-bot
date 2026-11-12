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
import re
import shutil
import subprocess
import sys
import math
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
    text = fit_glyphs(text.replace("•", "|"), font_path)   # only signs the Bengali/Hindi font can draw
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
def pick_window(segs, part_times, scene_no, max_len=None, min_len=None):
    """segs: [(start, dur, ...)] of every spoken line in the final video.
    Start at the beginning of the chosen story scene (part index = scene_no, part 0 is the intro)
    and end at the end of a line, before max_len seconds. Reels are 25-30 seconds (Meta, 8 Nov 2026: shorter
    Reels are watched to the end, so Facebook shows them to more people)."""
    max_len = float(max_len or env("REEL_SECONDS") or 30)
    min_len = float(min_len or min(18.0, max_len * 0.6))
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
                colors=((255, 225, 0), (210, 0, 0)), vertical=False, tagline=""):
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
    if tagline:                                   # the story's tag line under the title
        tl, tf_, ts = _fit_text(d, no_tofu(tagline), font_path, VW - 90, 44, lines_max=2)
        y += 4
        for l in tl:
            tw = d.textlength(l, font=tf_)
            d.text(((VW - tw) / 2, y), l, font=tf_, fill=(255, 255, 255, 255), stroke_width=max(3, ts // 12),
                   stroke_fill=(0, 0, 0, 255))
            y += int(ts * 1.3)
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
def fb_post_reel(video, description, at=None):
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
    at = at or publish_time()
    if at:                                            # goes live together with the main video (or at its own time)
        data.update(video_state="SCHEDULED", scheduled_publish_time=str(int(at.timestamp())))
    fin = requests.post(f"{GRAPH}/{page}/video_reels", data=data, timeout=120).json()
    if not fin.get("success"):
        raise RuntimeError(f"reel finish: {str(fin)[:300]}")
    return vid


def fb_post_story(video):
    """Shares the teaser (vertical, under 60 s) to the page's Facebook Story - followers see it at the top of their
    feed for 24 hours and tap through to the full story. Returns the story's post id."""
    page, token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    if env("FB_STORY") == "0" or not (page and token):
        return None
    r = requests.post(f"{GRAPH}/{page}/video_stories", data={"upload_phase": "start", "access_token": token},
                      timeout=60).json()
    if "video_id" not in r:
        raise RuntimeError(f"story start: {str(r)[:300]}")
    vid = r["video_id"]
    with open(video, "rb") as f:
        data = f.read()
    up = requests.post(r.get("upload_url") or f"https://rupload.facebook.com/video-upload/v21.0/{vid}",
                       headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))},
                       data=data, timeout=600).json()
    if not up.get("success"):
        raise RuntimeError(f"story upload: {str(up)[:300]}")
    fin = requests.post(f"{GRAPH}/{page}/video_stories", data={"upload_phase": "finish", "video_id": vid,
                                                                 "access_token": token}, timeout=120).json()
    if not fin.get("success"):
        raise RuntimeError(f"story finish: {str(fin)[:300]}")
    return fin.get("post_id") or vid


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


def fb_video_insights(video_id):
    """How the video was really watched on Facebook: views (3 s+), average seconds watched, its length and the
    share watched (retention). Needs the page token's insights permission - silently empty without it."""
    token = env("FB_PAGE_TOKEN")
    out = {}
    r = requests.get(f"{GRAPH}/{video_id}/video_insights", timeout=30, params={
        "metric": "total_video_views,total_video_avg_time_watched,total_video_complete_views",
        "access_token": token}).json()
    for d in r.get("data", []) or []:
        v = ((d.get("values") or [{}])[0]).get("value")
        if isinstance(v, (int, float)):
            out[{"total_video_views": "fb_views", "total_video_avg_time_watched": "avg_watch_ms",
                 "total_video_complete_views": "complete_views"}.get(d.get("name"), d.get("name"))] = v
    ln = requests.get(f"{GRAPH}/{video_id}", params={"fields": "length", "access_token": token}, timeout=30).json()
    if ln.get("length"):
        out["length_s"] = round(float(ln["length"]))
        if out.get("avg_watch_ms"):
            out["watched_pct"] = round(100 * out["avg_watch_ms"] / 1000 / max(1, out["length_s"]), 1)
    return out


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
        if h.get("facebook") and env("FB_PAGE_TOKEN"):
            try:
                st.update(fb_video_insights(h["facebook"]))
            except Exception:
                pass
        ys = yt.get(h.get("youtube", ""), {})
        for k in ("likes", "comments", "views"):
            st[k] += ys.get(k, 0)
        if h.get("youtube") and env("YT_REFRESH_TOKEN") and env("YT_ANALYTICS") != "0":
            try:
                st.update(yt_retention(h["youtube"]))
            except Exception:
                pass
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


def fb_add_captions(video_id, segs, lang, translations=None):
    """Closed captions (CC) on the Facebook video: the story language, plus English when we have it - viewers
    can switch them on, and Facebook understands the video better. Needs no extra permission."""
    token = env("FB_PAGE_TOKEN")
    if not (video_id and token and segs) or env("FB_CC") == "0":
        return 0

    def ts(x):
        ms = int(round(max(0.0, x) * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    done = 0
    sets = [({"bn": "bn_IN", "hi": "hi_IN"}.get(lang, "en_US"), lambda t: strip_tags(t))]
    if translations:
        sets.append(("en_US", lambda t: translations.get(str(t).strip(), "")))
    for loc, conv in sets:
        rows, k = [], 0
        for st, du, _, text in segs:
            t = str(conv(text) or "").strip()
            if t:
                k += 1
                rows.append(f"{k}\n{ts(st)} --> {ts(st + du)}\n{t}\n")
        if k < 3:
            continue
        name = f"captions.{loc}.srt"
        try:
            r = requests.post(f"{GRAPH}/{video_id}/captions", timeout=120,
                              data={"access_token": token, "default_locale": "none" if done else loc},
                              files={"captions_file": (name, "\n".join(rows).encode("utf-8"), "text/plain")}).json()
            if r.get("success") or r.get("id"):
                done += 1
            else:
                log(f"  Facebook captions ({loc}): {str(r)[:200]}")
        except Exception as e:
            log(f"  Facebook captions ({loc}) failed: {str(e)[:150]}")
    if done:
        log(f"  closed captions added on Facebook ({done} language{'s' if done > 1 else ''})")
    return done


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
TIME_WORDS = {"bn": {8: "সকালে", 13: "দুপুরে", 19: "সন্ধ্যায়", 21: "রাতে", 14: "দুপুরে", 20: "রাতে", 10: "সকালে"},
              "hi": {8: "सुबह", 13: "दोपहर", 19: "शाम", 21: "रात", 14: "दोपहर", 20: "रात", 10: "सुबह"}}
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
    A run belongs to the LAST slot that has already started (up to 90 minutes early allowed), so a late
    backup run still knows which slot it is for. Returns e.g. '2026-10-22@13'."""
    now = now or dt.datetime.now(IST)
    best = None
    for add in (0, -1):
        day = (now + dt.timedelta(days=add)).date()
        for h, m, post in triggers:
            start = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=IST) - \
                dt.timedelta(minutes=int(env("EARLY_MINUTES") or 90))   # a start up to 1.5 h early still counts
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


AUTHOR_NOTE_RX = r"\s*(?:\([^()]{0,60}\)|\[[^\[\]]{0,60}\]|\{[^{}]{0,60}\}|（[^（）]{0,60}）)\s*"
STAGE_WORDS_RX = (r"(?i)\b(?:whisper(?:s|ing)?|sigh(?:s|ing)?|gasp(?:s|ing)?|laugh(?:s|ing)?|cr(?:ies|ying)|sob(?:s|bing)?|"
                  r"pause[sd]?|softly|slowly|angrily|loudly|quietly|sadly|nervously|shouting|screams?|smiling|"
                  r"long pause|short pause|beat|silence)\b[:,.]?")


def speakable(text):
    """What a voice may read: never the writer's notes in brackets - '(ফিসফিস করে)', '(whispering)',
    '[door creaks]' - nor loose English stage words inside a Bengali / Hindi line. Our own <sigh>-style voice
    tags are kept (they become real sighs, not words)."""
    import re as _re
    t = str(text or "")
    t = _re.sub(AUTHOR_NOTE_RX, " ", t)
    if _re.search(r"[\u0980-\u09FF\u0900-\u097F]", t):        # an Indian-language line: no English stage words
        parts = _re.split(r"(<[^<>]{1,30}>)", t)
        t = "".join(p if p.startswith("<") else _re.sub(STAGE_WORDS_RX, " ", p) for p in parts)
    return _re.sub(r"\s{2,}", " ", t).strip(" ,")


def strip_tags(text):
    """Remove voice tags like <sigh> or <short pause>, and the writer's notes in brackets (for subtitles and the
    backup voice)."""
    import re as _re
    return _re.sub(r"\s*<[A-Za-z][A-Za-z \-]{1,24}>\s*", " ", speakable(text)).strip()


TAG_WORDS = {"laugh": "laughs", "laughs": "laughs", "sigh": "sighs", "gasp": "gasps", "sob": "sobs",
             "whisper": "whispers", "whispers": "whispers", "breath": "breathes in", "scream": "screams",
             "cackle": "cackles wickedly", "growl": "growls", "giggle": "giggles", "evil laugh": "laughs wickedly"}


def tts_tags(text):
    """Voice tags for the newest Gemini voices: they understand [sighs] / [laughs] in square brackets and pauses
    as '...'. Our <sigh>-style tags would otherwise be READ OUT ('long pause' spoken aloud!)."""
    text = speakable(text)                    # never read the writer's notes in brackets aloud
    import re as _re

    def one(m):
        w = m.group(1).strip().lower()
        if "pause" in w:
            return " ... ... " if "long" in w else " ... "
        return f" [{TAG_WORDS.get(w, w)}] "
    out = _re.sub(r"<\s*([A-Za-z][A-Za-z \-]{1,24})\s*>", one, str(text))
    return _re.sub(r"\s{2,}", " ", out).strip()


_TEXT_MODELS = []


def text_models(key):
    """The Gemini writing models this key can use RIGHT NOW (Google retires old names - 'gemini-2.5-flash'
    answered 404 on 8 Nov 2026), newest first; the '-latest' names always point to a live model."""
    if not _TEXT_MODELS:
        names = []
        try:
            r = requests.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": key}, params={"pageSize": 200},
                             timeout=30)
            for mo in r.json().get("models", []):
                n = mo.get("name", "").replace("models/", "")
                if ("generateContent" in mo.get("supportedGenerationMethods", []) and "flash" in n
                        and not any(x in n for x in ("image", "tts", "audio", "live", "embed", "exp"))):
                    names.append(n)
        except Exception:
            pass

        def ver(n):
            nums = re.findall(r"\d+(?:\.\d+)?", n)
            return (float(nums[0]) if nums else 0, "lite" not in n, "preview" not in n)
        for n in ["gemini-flash-latest"] + sorted(names, key=ver, reverse=True) + ["gemini-flash-lite-latest"]:
            if n not in _TEXT_MODELS:
                _TEXT_MODELS.append(n)
    return list(_TEXT_MODELS)


def helper_models(key):
    """(13 Nov 2026) the LIGHT models first, for the small helper jobs (trends, replies, translations, picking a
    thumbnail, the voice notes ...): the strong models' small free daily limit is kept for WRITING THE STORIES - the
    night run found every strong model 'used up for today' and the story came out short and weak."""
    allm = text_models(key)
    lite = [m for m in allm if "lite" in m]
    rest = [m for m in allm if "lite" not in m]
    return (lite[:3] + rest[-2:]) if lite else allm


def tts_keys():
    # ONE free key only (Google's free limit is meant per person / project - using extra keys to get round it
    # breaks Google's rules and can get the accounts blocked)
    keys = [k for k in (env("GEMINI_TTS_KEY"),) if k]
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
          "never like reading. Say these words exactly: শাঁকচুন্নি = 'shaank-chun-ni' (long nasal 'aan', double "
          "'nn' - never 'shak-chuni'), ব্রহ্মদৈত্য = 'brom-ho-doi-tto', পেত্নি = 'pet-ni', মামদো = 'mam-do', "
          "স্কন্ধকাটা = 'skon-dho-ka-ta', নিশি = 'ni-shi', একানড়ে = 'e-ka-no-re', গেছোভূত = 'ge-chho-bhut', "
          "তান্ত্রিক = 'tan-trik', শ্মশান = 'shoshan' (the 'm' is silent), ব্রাহ্মণ = 'bram-hon', লক্ষ্মী = 'lokkhi', "
          "আত্মা = 'atta', পদ্ম = 'poddo', বিশ্বাস = 'bish-shash', ঘটনা = 'gho-tona' (the inherent vowel is 'o').",
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


def protobuf_shim():
    """Some newer helper files (made with protobuf 5) import google.protobuf.runtime_version, which the older
    protobuf on the runner (needed by mediapipe) does not have -> 'cannot import name runtime_version' and the
    free voice failed. The check it does is only a version check, so a tiny stand-in is enough."""
    try:
        from google.protobuf import runtime_version  # noqa: F401
        return
    except Exception:
        pass
    try:
        import types
        import google.protobuf as _gp
        mod = types.ModuleType("google.protobuf.runtime_version")

        class Domain:
            PUBLIC = 0
            GOOGLE_INTERNAL = 1
        mod.Domain = Domain
        mod.ValidateProtobufRuntimeVersion = lambda *a, **k: None
        sys.modules["google.protobuf.runtime_version"] = mod
        _gp.runtime_version = mod
        log("  (protobuf: added the small runtime_version stand-in for the free voice model)")
    except Exception as e:
        log("  protobuf stand-in failed:", str(e)[:100])


def _parler_load():
    protobuf_shim()
    if PARLER["model"] is None:
        import warnings
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")   # no pages of model settings in the log
        warnings.filterwarnings("ignore")
        try:
            import transformers
            transformers.logging.set_verbosity_error()
        except Exception:
            pass
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer
        torch.set_num_threads(max(1, os.cpu_count() or 2))
        m = ParlerTTSForConditionalGeneration.from_pretrained(PARLER_ID, token=env("HF_TOKEN")).to("cpu")
        tok = AutoTokenizer.from_pretrained(PARLER_ID, token=env("HF_TOKEN"))
        dtok = AutoTokenizer.from_pretrained(m.config.text_encoder._name_or_path)
        PARLER["model"] = (m, tok, dtok)
    return PARLER["model"]


def machine_room():
    """' (memory free 9.1 GB, disk free 21 GB)' - written next to every scene in the log, so if GitHub's computer
    ever runs out of room again we see it coming (8 Nov 2026: 'the hosted runner lost communication')."""
    try:
        mem = {}
        for ln in open("/proc/meminfo"):
            k, v = ln.split(":", 1)
            mem[k] = int(v.split()[0])
        free_gb = (mem.get("MemAvailable", 0) + mem.get("SwapFree", 0)) / 1048576
        disk_gb = shutil.disk_usage(os.path.expanduser("~")).free / 1e9
        return f" (memory free {free_gb:.1f} GB, disk free {disk_gb:.0f} GB)"
    except Exception:
        return ""


def parler_unload():
    """The free voice model needs ~4 GB of memory; once every line is voiced it is closed, so the heavy video
    work after it (pictures, 19 clips, the final film) never runs out of memory."""
    if PARLER["model"] is not None:
        PARLER["model"] = None
        import gc
        gc.collect()
        log("  free voice model closed - memory freed for the video")


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
KEY_COOL, KEY_LAST, KEY_DEAD, DAY_OUT, HITS = {}, {}, set(), set(), {}


MODEL_LAST = {}


def _pick_key(model):
    keys = [k for k in tts_keys() if k not in KEY_DEAD and (k, model) not in DAY_OUT]
    if not keys:
        return None
    # the free voice models allow only 3 requests a minute each: keep a steady gap instead of hitting the
    # limit (every refused request is wasted time and also counts against the day)
    gap = 60.0 / max(1.0, float(env("TTS_RPM") or 3)) + 0.5
    wait = MODEL_LAST.get(model, 0) + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    MODEL_LAST[model] = time.time()
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
                HITS[model] = HITS.get(model, 0) + 1
                if kind == "day" or HITS[model] >= 3:     # 3 refusals in a row: its limit is over for today
                    DAY_OUT.add((key, model))
                    break
                KEY_COOL[key] = time.time() + min(wait, 65) + 1
                continue
            HITS[model] = 0
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
    try:
        return float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                           "default=nw=1:nk=1", out_wav]).strip() or 0)
    except (ValueError, RuntimeError):
        return 0.0                                    # an empty / broken piece: the caller treats it as missing


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
        if max(0.4, plain_len / 40) <= d <= plain_len / 4 + 4:     # far longer = something extra was said
            return True
        log(f"    single line: {d:.1f} s for {plain_len} letters - not used")
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
        # ONE character per request: a cut that lands a little off can then never put one person's words into
        # another person's voice
        if cur and (len(spk) > int(env("TTS_SPEAKERS_PER_REQUEST") or 1) or len(cur) >= int(env("TTS_BATCH_LINES") or 24)
                    or sum(len(x["plain"]) for x in cur) + len(it["plain"]) > int(env("TTS_BATCH_CHARS") or 1900)):
            groups.append(cur)
            cur = []
        cur.append(it)
    if cur:
        groups.append(cur)
    log(f"  {len(items)} lines in {len(groups)} voice requests (keys: {len(tts_keys())})")
    done = 0
    gi = -1
    while gi + 1 < len(groups):
        gi += 1
        g = groups[gi]
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
    protobuf_shim()
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
                HITS[model] = HITS.get(model, 0) + 1
                if kind == "day" or HITS[model] >= 3:     # 3 refusals in a row: its limit is over for today
                    DAY_OUT.add((key, model))
                    break
                KEY_COOL[key] = time.time() + min(wait, 65) + 1
                continue
            HITS[model] = 0
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


SHORT_ACCENT = {"Kolkata (West Bengal, India) Bengali": "Standard Kolkata Bengali accent, every word exactly as written",
                "Bengali": "Standard Kolkata Bengali accent, every word exactly as written",
                "Hindi": "Natural Hindi, every word exactly as written"}


def _calm(text):
    """A line inside a multi-line recording: its own dramatic pauses ('...', '…', '—') become short comma pauses.
    Only the pause BETWEEN two lines stays long - that is where the recording is cut, so a cut can never land
    inside a sentence (a long '...' in the middle of a line was taken for the end of the line, and the rest of
    the sentence went missing or into the next line). The scene itself adds the dramatic silences back."""
    t = re.sub(r"\s*(?:\.\s*){2,}|\s*…+\s*|\s+[—–]\s+", ", ", str(text))
    t = re.sub(r"[।.]\s+(?=\S)", ", ", t.strip())       # a sentence end INSIDE the line: a short pause only
    t = re.sub(r"(,\s*){2,}", ", ", t)
    t = re.sub(r"^[,\s]+", "", t)
    return re.sub(r"[,\s]+$", "", t) + ("" if re.search(r"[।!?.]$", t.strip()) else "।")


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
        # the long accent / speaker note goes with the FIRST line only (it holds for the whole recording) - repeated
        # on all 16 lines it used up the 10,000-tokens-a-minute limit of the free voice models
        # ONLY the story's own words are in the text the model speaks; how to say it goes in a SHORT style note
        # (long English notes were sometimes read out loud in English in the middle of a Bengali story)
        many = len(turns) > 1
        blocks = [{"type": "text", "text": (_calm(tts_tags(t)) if many else tts_tags(t))
                   + (" ... ... ..." if k < len(turns) - 1 else ""),
                   "annotations": [{"type": "speech_metadata", "speaker": s, "style": (
                       str(st).split(" Accent:")[0][:200]
                       + ((" " + str(extra_note).split(" Accent:")[0][:200] + " " + SHORT_ACCENT.get(lang_label, ""))
                          if k == 0 else ""))[:500]}]}
                  for k, (s, t, st) in enumerate(turns)]
        out.append((model + "#blocks", model, f"{GEMINI_BASE}/interactions",
                    {"model": model, "input": [{"type": "user_input", "content": blocks}],
                     "response_format": {"type": "audio"}, "generation_config": {"speech_config": sc}}, API_REV))
    for model in OLD_TTS:
        plain = "\n".join((f"{s}: " if multi else "") + (_calm(strip_tags(t)) + " ... ... ..." if len(turns) > 1
                                                           else strip_tags(t)) for s, t, st in turns)
        cfg = ({"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
            {"speaker": s, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}} for s, v in speakers]}}
            if multi else {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": speakers[0][1]}}})
        # the older models speak EVERYTHING in the prompt: one short lead-in ending in a colon, then only the lines
        out.append((model + ("#multi" if multi else "#single"), model, f"{GEMINI_BASE}/models/{model}:generateContent",
                    {"contents": [{"parts": [{"text": f"Read aloud slowly in {lang_label}, as a radio drama, with a "
                                                      f"pause after every line:\n{plain}"}]}],
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
            try:
                twice = _said_twice(out_wav, [voice_text])
            except Exception:
                twice = ""
            if not twice:
                return True
            log(f"    one line: Gemini said something twice ({twice}) - asked again")
    if os.path.exists(out_wav):
        os.remove(out_wav)
    return False


MARK_STATS = [0, 0]             # recordings cut by their marker words / by their pauses (this run)
TTS_PLAN = {"pieces": 20, "chars": 1700}     # how full one voice request is made (main.py sets it from the day's limit)


def tts_groups(items):
    """How the lines are sent: ONE speaker per request, as full as TTS_PLAN allows, and a LINE is never split over
    two requests (10 Nov 2026). Google's free limit is 10 requests a day for each voice model - about 36 in all - for
    two stories and two teasers: with small requests of 12 sentences one story alone needed 14-16 requests, so the
    second half of the cast always fell back to the Chirp voice. Fuller requests need 8-10."""
    max_n = int(env("TTS_BATCH_LINES") or TTS_PLAN["pieces"])
    max_c = int(env("TTS_BATCH_CHARS") or TTS_PLAN["chars"])
    lines, last = [], object()
    for it in items:                                  # the sentences of one line stay together
        key = (it.get("line") or it["out"], it["spk"])
        if key != last:
            lines.append([])
            last = key
        lines[-1].append(it)
    groups, cur = [], []
    for ln in lines:
        n_c = sum(len(x["plain"]) for x in ln)
        if cur and (cur[0]["spk"] != ln[0]["spk"] or len(cur) + len(ln) > max_n
                    or sum(len(x["plain"]) for x in cur) + n_c > max_c):
            groups.append(cur)
            cur = []
        cur = cur + ln
    if cur:
        groups.append(cur)
    return groups


def _align_split(wav, plains):
    """Cuts one recording of several lines exactly in the silences BETWEEN the lines: every silence is a
    candidate, and the cuts are the ones that best match where each line should end (by its length), in order.
    Returns None when it is not sure (then the lines are asked for again in smaller groups)."""
    import numpy as np
    from scipy.io import wavfile
    sr, a = wavfile.read(wav)
    a = a.astype("float32")
    n = len(plains)
    if n == 1:
        return [a], sr
    hop = int(sr * 0.02)
    rms = np.array([np.sqrt((a[i:i + hop] ** 2).mean()) for i in range(0, len(a) - hop, hop)])
    if rms.size < 10:
        return None
    quiet = rms < max(np.percentile(rms, 95) * 0.03, 1e-6)     # real silence only - a whisper is still speech
    cand, i = [], 0                                   # (centre frame, length in frames)
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if (j - i) * 0.02 >= 0.2 and i > 0 and j < len(quiet):
                cand.append(((i + j) // 2, j - i))
            i = j
        else:
            i += 1
    if len(cand) < n - 1:
        return None
    tot = sum(max(1, len(p)) for p in plains)
    exp, acc = [], 0
    for p in plains[:-1]:
        acc += max(1, len(p))
        exp.append(len(rms) * acc / tot)
    total = len(a) / sr

    def pieces(cuts):
        bounds = [0] + [c * hop for c in cuts] + [len(a)]
        segs = [a[bounds[k]:bounds[k + 1]] for k in range(n)]
        for seg, p in zip(segs, plains):              # every piece must fit its own line's length
            want = total * max(1, len(p)) / tot
            lo, hi = (0.55, 1.75) if len(p) >= 30 else (0.33, 2.6)   # a long line with a sentence missing = too short
            if not (lo * want <= len(seg) / sr <= hi * want + 0.6):
                return None
        return segs
    # FIRST CHOICE: the pauses BETWEEN lines are the longest silences of the recording (inside a line there are only
    # short comma pauses) - when the n-1 longest silences stand clearly apart from all the others, they are the cuts
    by_len = sorted(range(len(cand)), key=lambda c: -cand[c][1])
    if len(cand) == n - 1 or cand[by_len[n - 2]][1] >= 1.45 * cand[by_len[n - 1]][1]:
        segs = pieces(sorted(cand[c][0] for c in by_len[:n - 1]))
        if segs:
            return segs, sr
    # else dynamic programming: pick n-1 silences in order, close to the expected ends, longer silences preferred
    C, K = len(cand), n - 1
    INF = float("inf")
    cost = [[INF] * C for _ in range(K)]
    back = [[-1] * C for _ in range(K)]
    for c in range(C):
        cost[0][c] = abs(cand[c][0] - exp[0]) - 12 * cand[c][1]
    for k in range(1, K):
        best, bi = INF, -1
        for c in range(C):
            if c > 0 and cost[k - 1][c - 1] < best:
                best, bi = cost[k - 1][c - 1], c - 1
            if bi >= 0:
                cost[k][c] = best + abs(cand[c][0] - exp[k]) - 12 * cand[c][1]
                back[k][c] = bi
    c = min(range(C), key=lambda x: cost[K - 1][x])
    if cost[K - 1][c] == INF:
        return None
    picks = [c]
    for k in range(K - 1, 0, -1):
        c = back[k][c]
        picks.append(c)
    segs = pieces([cand[c][0] for c in reversed(picks)])
    return (segs, sr) if segs else None


def _pause_note(wav, n):
    """Why a recording of n sentences could not be cut - for the log: how many clear pauses Gemini made and how
    long the deciding ones are."""
    try:
        import numpy as np
        from scipy.io import wavfile
        sr, a = wavfile.read(wav)
        a = a.astype("float32")
        hop = int(sr * 0.02)
        rms = np.array([np.sqrt((a[i:i + hop] ** 2).mean()) for i in range(0, len(a) - hop, hop)])
        quiet = rms < max(np.percentile(rms, 95) * 0.03, 1e-6)
        runs, i = [], 0
        while i < len(quiet):
            if quiet[i]:
                j = i
                while j < len(quiet) and quiet[j]:
                    j += 1
                if (j - i) * 0.02 >= 0.2 and i > 0 and j < len(quiet):
                    runs.append((j - i) * 0.02)
                i = j
            else:
                i += 1
        runs.sort(reverse=True)
        if len(runs) < n - 1:
            return f"only {len(runs)} pauses for {n} sentences"
        if len(runs) == n - 1:
            return f"{len(runs)} pauses as needed, but a piece did not fit its sentence's length"
        return (f"{len(runs)} pauses for {n} sentences; the {n - 1}th longest {runs[n - 2]:.2f} s, the next "
                f"{runs[n - 1]:.2f} s - too alike or a piece did not fit")
    except Exception:
        return "?"


def _mel_feats(a, sr):
    """speech features every 10 ms: 20 MFCCs without the loudness term (what is said and how it sounds, not how
    loud), normalised over the speech of this recording only (silence would squash the differences)"""
    import numpy as np
    win, hop = int(sr * 0.025), int(sr * 0.01)
    if len(a) < win * 4:
        return None
    nfft = 1
    while nfft < win:
        nfft *= 2
    idx = np.arange(win)[None, :] + hop * np.arange((len(a) - win) // hop + 1)[:, None]
    frames = a[idx] * np.hanning(win)[None, :]
    spec = np.abs(np.fft.rfft(frames, n=nfft)) ** 2
    mel = lambda f: 2595 * np.log10(1 + f / 700.0)
    imel = lambda m: 700 * (10 ** (m / 2595.0) - 1)
    pts = imel(np.linspace(mel(60), mel(min(7600, sr / 2 - 200)), 42))
    bins = np.floor((nfft + 1) * pts / sr).astype(int)
    fb = np.zeros((40, nfft // 2 + 1))
    for k in range(40):
        l, c, r = bins[k], bins[k + 1], bins[k + 2]
        if c > l:
            fb[k, l:c] = (np.arange(l, c) - l) / (c - l)
        if r > c:
            fb[k, c:r] = (r - np.arange(c, r)) / (r - c)
    p = spec @ fb.T
    p = np.log(np.maximum(p, p.max() * 1e-8))
    n = np.arange(40)
    dct = np.cos(np.pi / 40 * (n[None, :] + 0.5) * np.arange(1, 21)[:, None])      # c1..c20 (no c0 = loudness)
    m = p @ dct.T
    loud = p.mean(axis=1)
    sp = loud > np.percentile(loud, 35)               # the speech frames
    mu, sd = m[sp].mean(axis=0), m[sp].std(axis=0) + 1e-6
    return (m - mu) / sd


def _dtw(A, B):
    """average frame distance along the best time-warped path (within a band of 35% of the length) - one numpy
    step per frame: D[i, j] = S[j] + min over k <= j of (T[k] - S[k])"""
    import numpy as np
    n, m = len(A), len(B)
    if not n or not m:
        return float("inf")
    band = max(abs(n - m) + 2, int(0.35 * max(n, m)))
    prev = np.full(m + 1, np.inf)
    prev[0] = 0.0
    for i in range(1, n + 1):
        jc = int(round(i * m / n))
        lo, hi = max(1, jc - band), min(m, jc + band)
        cur = np.full(m + 1, np.inf)
        c = np.sqrt(((B[lo - 1:hi] - A[i - 1]) ** 2).sum(axis=1))
        T = c + np.minimum(prev[lo - 1:hi], prev[lo:hi + 1])
        S = np.cumsum(c)
        cur[lo:hi + 1] = S + np.minimum.accumulate(T - S)
        prev = cur
    return float(prev[m] / (n + m))


TWICE_AT = [None]               # (start, end, start, end) in seconds of the two copies _said_twice heard


def _said_twice(wav, plains):
    """Gemini sometimes says a sentence TWICE in one recording (9 Nov 2026: 'many lines are said twice').
    The text has no such repeat, so two stretches of speech that sound the same = a repeat -> do not use it.
    Returns a short note when a repeat is heard, else ''."""
    import numpy as np
    from scipy.io import wavfile
    from difflib import SequenceMatcher
    TWICE_AT[0] = None
    keys = [re.sub(r"[^\wঀ-৿ऀ-ॿ]", "", strip_tags(p)) for p in plains]
    for x in range(len(keys)):                        # the story itself repeats something here: nothing to check
        for y in range(x + 1, len(keys)):
            if keys[x] and keys[y] and SequenceMatcher(None, keys[x], keys[y]).ratio() >= 0.6:
                return ""
    words = re.sub(r"[^\wঀ-৿ऀ-ॿ]+", " ", " ".join(strip_tags(p) for p in plains)).split()
    grams = [" ".join(words[k:k + 2]) for k in range(len(words) - 1)]
    if any(len(g_) >= 10 and grams.count(g_) > 1 for g_ in grams):
        return ""                                     # ('ওরে পল্টু, ওরে পল্টু' - the words themselves come twice)
    sr, a = wavfile.read(wav)
    a = a.astype("float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    if sr != 16000:                                   # 16 kHz is plenty to hear what is said (with a proper
        from math import gcd                          # low-pass - a plain resample made the two copies differ)
        from scipy.signal import resample_poly
        g_ = gcd(int(sr), 16000)
        a = resample_poly(a, 16000 // g_, int(sr) // g_).astype("float32")
        sr = 16000
    hop = int(sr * 0.02)
    rms = np.array([np.sqrt((a[i:i + hop] ** 2).mean()) for i in range(0, len(a) - hop, hop)])
    if rms.size < 50:
        return ""
    quiet = rms < max(np.percentile(rms, 95) * 0.05, 1e-6)
    marks, i = [0], 0                                 # pauses of 0.2 s or more split the speech
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if j - i >= 10:
                marks += [i, j]
            i = j
        else:
            i += 1
    marks.append(len(quiet))
    chunks = [(marks[k] * hop, marks[k + 1] * hop) for k in range(0, len(marks) - 1, 2)
              if (marks[k + 1] - marks[k]) * 0.02 >= 1.3]
    if len(chunks) < 3:
        return ""
    F = _mel_feats(a, sr)
    if F is None:
        return ""
    fr = lambda s: int(s / (sr * 0.01))
    feats = [F[fr(s):max(fr(s) + 5, fr(e))] for s, e in chunks]
    pairs = []
    for x in range(len(chunks)):
        for y in range(x + 1, min(len(chunks), x + 5)):
            dx, dy = chunks[x][1] - chunks[x][0], chunks[y][1] - chunks[y][0]
            if 0.7 <= dx / dy <= 1.43:
                pairs.append((x, y, _dtw(feats[x], feats[y])))
    if len(pairs) < 4:
        return ""
    med = float(np.median([p[2] for p in pairs]))
    x, y, d = min(pairs, key=lambda p: p[2])
    if d < float(env("REPEAT_LIKENESS") or 0.75) * med:      # (two different sentences: 0.95+; a repeat: ~0.5)
        TWICE_AT[0] = (chunks[x][0] / sr, chunks[x][1] / sr, chunks[y][0] / sr, chunks[y][1] / sr)
        return f"{(chunks[x][1] - chunks[x][0]) / sr:.1f} s of speech heard twice (likeness {d / med:.2f})"
    return ""


def _soft_split(wav, plains):
    """When the clean pause-cut is unsure: cut near where each line SHOULD end (by its length), at the quietest
    moment close to that point - never a new request (the free limit is only ~10 requests a day per model)."""
    import numpy as np
    from scipy.io import wavfile
    sr, a = wavfile.read(wav)
    a = a.astype("float32")
    n = len(plains)
    if n == 1 or len(a) < sr:
        return [a] + [a[:0]] * (n - 1), sr
    hop = int(sr * 0.02)
    rms = np.array([np.sqrt((a[i:i + hop] ** 2).mean()) for i in range(0, len(a) - hop, hop)])
    tot = sum(max(1, len(p)) for p in plains)
    cuts, acc, prev = [], 0, 0
    for p in plains[:-1]:
        acc += max(1, len(p))
        want = int(len(rms) * acc / tot)
        w = max(5, int(len(rms) * 0.06))
        lo, hi = max(prev + 5, want - w), min(len(rms) - 5, want + w)
        c = want if hi <= lo else lo + int(np.argmin(rms[lo:hi]))
        cuts.append(c)
        prev = c
    bounds = [0] + [c * hop for c in cuts] + [len(a)]
    return [a[bounds[k]:bounds[k + 1]] for k in range(n)], sr


TTS_USED = [0]                  # voice requests sent in this run (each one counts against the day)
SPK_RATE = {}                   # seconds per letter of every voice, learned from its clean recordings


def _align_lines(wav, plains, keys=None, partial=True):
    """Cuts one recording of several pieces exactly in the silences BETWEEN them: every silence is a candidate, and
    the cuts are the ones that best match where each piece should end (by its length), in order.
    keys: the line each piece belongs to - the sentences of one line are joined again afterwards, so only the cuts
    BETWEEN two lines must be exact and a line is checked as a whole (10 Nov 2026: checking every single sentence
    made the bot throw away good recordings and ask again and again - 17 requests for one storyteller).
    partial=True: when the recording cannot be cut cleanly as a whole, the lines at its start and its end that ARE
    certain are kept - returns (pieces, rate, ok) and only the pieces with ok=False are asked for again.
    Returns None when nothing is certain."""
    import numpy as np
    from scipy.io import wavfile
    sr, a = wavfile.read(wav)
    a = a.astype("float32")
    n = len(plains)
    keys = list(keys) if keys and len(keys) == n else list(range(n))
    if n == 1:
        return ([a], sr, [True]) if partial else ([a], sr)
    hop = int(sr * 0.02)
    rms = np.array([np.sqrt((a[i:i + hop] ** 2).mean()) for i in range(0, len(a) - hop, hop)])
    if rms.size < 10:
        return None
    p95 = max(float(np.percentile(rms, 95)), 1e-6)
    soft = rms < p95 * 0.25                           # a breath is soft - speech is not

    def pauses(frac):
        """(cut frame, length) of every pause; a short soft breath INSIDE a pause belongs to it (a storyteller
        often breathes in the pause between two sentences - that split one long pause into two short ones)"""
        quiet = rms < p95 * frac
        runs, i = [], 0
        while i < len(quiet):
            if quiet[i]:
                j = i
                while j < len(quiet) and quiet[j]:
                    j += 1
                runs.append([i, j])
                i = j
            else:
                i += 1
        merged = []
        for r in runs:
            if merged and r[0] - merged[-1][1] <= 15 and soft[merged[-1][1]:r[0]].all():
                merged[-1][1] = r[1]
                merged[-1][2].append(r)
            else:
                merged.append([r[0], r[1], [r]])
        out = []
        for st_, en_, parts in merged:
            if (en_ - st_) * 0.02 >= 0.2 and st_ > 0 and en_ < len(quiet):
                big = max(parts, key=lambda p: p[1] - p[0])    # cut in the quietest (longest silent) part
                out.append(((big[0] + big[1]) // 2, en_ - st_))
        return out
    cand = []
    for frac in (0.03, 0.06, 0.10):                   # real silence first; a pause with a soft breath only if needed
        cand = pauses(frac)
        if len(cand) >= n - 1:
            break
    if len(cand) < n - 1:
        return None
    tot = sum(max(1, len(p)) for p in plains)
    exp, acc = [], 0
    for p in plains[:-1]:
        acc += max(1, len(p))
        exp.append(len(rms) * acc / tot)
    total = len(a) / sr
    lines, s0 = [], 0                                 # (first piece, last piece + 1) of every line
    for k in range(1, n + 1):
        if k == n or keys[k] != keys[k - 1]:
            lines.append((s0, k))
            s0 = k

    sil = {cf: ln for cf, ln in cand}

    def sure(cuts, k):
        """cut k is certain when its pause clearly stands out in its own neighbourhood (from the middle of the
        piece before it to the middle of the piece after it): the longest there, 1.4x longer than any other"""
        lo = (([0] + list(cuts))[k] + cuts[k]) // 2
        hi = (cuts[k] + (list(cuts) + [len(rms)])[k + 1]) // 2
        others = [ln for cf, ln in cand if lo <= cf <= hi and cf != cuts[k]]
        return not others or sil[cuts[k]] >= 1.4 * max(others)

    def check(cuts):
        bounds = [0] + [c * hop for c in cuts] + [len(a)]
        segs = [a[bounds[k]:bounds[k + 1]] for k in range(n)]
        fit = []
        for seg, p in zip(segs, plains):              # every piece must fit its own sentence's length
            want = total * max(1, len(p)) / tot
            lo, hi = (0.55, 1.75) if len(p) >= 30 else (0.33, 2.6)   # a long line with a sentence missing = too short
            fit.append(lo * want <= len(seg) / sr <= hi * want + 0.6)
        ok = [False] * n
        for s, e in lines:                            # a line is certain when all its sentences fit AND so do the
            good = (all(fit[s:e]) and (s == 0 or fit[s - 1]) and (e == n or fit[e]))   # pieces on both sides
            for k in range(s, e):
                ok[k] = good
        return segs, ok

    def result(segs, ok):
        if all(ok):
            return (segs, sr, ok) if partial else (segs, sr)
        return None
    # FIRST CHOICE: the pauses BETWEEN pieces are the longest silences of the recording (inside a piece there are only
    # short comma pauses) - when the n-1 longest silences stand clearly apart from all the others, they are the cuts
    by_len = sorted(range(len(cand)), key=lambda c: -cand[c][1])
    if len(cand) == n - 1 or cand[by_len[n - 2]][1] >= 1.45 * cand[by_len[n - 1]][1]:
        r = result(*check(sorted(cand[c][0] for c in by_len[:n - 1])))
        if r:
            return r
    # else dynamic programming: pick n-1 silences in order, close to the expected ends, longer silences preferred
    C, K = len(cand), n - 1
    INF = float("inf")
    cost = [[INF] * C for _ in range(K)]
    back = [[-1] * C for _ in range(K)]
    for c in range(C):
        cost[0][c] = abs(cand[c][0] - exp[0]) - 12 * cand[c][1]
    for k in range(1, K):
        best, bi = INF, -1
        for c in range(C):
            if c > 0 and cost[k - 1][c - 1] < best:
                best, bi = cost[k - 1][c - 1], c - 1
            if bi >= 0:
                cost[k][c] = best + abs(cand[c][0] - exp[k]) - 12 * cand[c][1]
                back[k][c] = bi
    c = min(range(C), key=lambda x: cost[K - 1][x])
    if cost[K - 1][c] == INF:
        return None
    picks = [c]
    for k in range(K - 1, 0, -1):
        c = back[k][c]
        picks.append(c)
    segs, ok = check([cand[c][0] for c in reversed(picks)])
    if all(ok) or not partial:
        return result(segs, ok)
    # PARTIAL: every line that is certain (its own length right, both its ends in a clear pause) is kept; only the
    # others are asked for again
    return (segs, sr, ok) if any(ok) else None


def _voiced(seg, rate, thr):
    """seconds of real speech in a piece (its pauses do not count) - what a text needs is far steadier than its
    length with pauses"""
    import numpy as np
    hop = max(1, int(rate * 0.02))
    if len(seg) < hop * 2:
        return 0.0
    n = len(seg) // hop
    rms = np.sqrt((seg[:n * hop].astype("float32").reshape(n, hop) ** 2).mean(axis=1))
    return float((rms >= thr).sum()) * 0.02


def _tight(seg, rate, thr, over=0.9, keep=0.75):
    """only the VERY long pauses inside a line are shortened (to 0.75 s). 11 Nov 2026: with every pause cut down to
    0.26 s the grave storyteller sounded hurried and a 20-minute story became a 13-minute video - on the real
    recordings half of the time is his pauses."""
    import numpy as np
    hop = max(1, int(rate * 0.02))
    n = len(seg) // hop
    if n < 10:
        return seg
    rms = np.sqrt((seg[:n * hop].astype("float32").reshape(n, hop) ** 2).mean(axis=1))
    quiet = rms < thr
    out, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            ln = (j - i) * 0.02
            if ln > over and i > 0 and j < n:
                h = int(keep / 2 / 0.02)
                out.append(seg[i * hop:(i + h) * hop])
                out.append(seg[(j - h) * hop:j * hop])
            else:
                out.append(seg[i * hop:j * hop])
            i = j
        else:
            j = i
            while j < n and not quiet[j]:
                j += 1
            out.append(seg[i * hop:j * hop])
            i = j
    out.append(seg[n * hop:])
    return np.concatenate(out)


# ===================== v71: a MARKER WORD in another voice between the lines =====================
# 10 Nov 2026, the first real run of the line-keeping voicer: in every recording about a third of the lines had an
# uncertain end (the pauses Gemini makes between lines are simply not reliable), each of them cost another request,
# and the night's share was gone after two characters. So the line ends are no longer GUESSED from pauses: between two
# lines a second speaker with a clearly different voice (a woman for a man's lines, a man for a woman's) says one short
# word. Where that other voice is heard is found by its pitch - the lines lie exactly between the markers. The count
# must fit exactly (lines - 1), else the old way with the pauses is used for that recording.
MARK_TEXT = {"bn": "আচ্ছা।", "hi": "अच्छा।"}
MARK_STYLE = "one short flat word, quiet, no feeling"


def _marker_voice(voice):
    return "Charon" if voice in CHIRP_VOICES[:14] else "Leda"      # (the first 14 names are the women's voices)


def _f0_frames(a, sr):
    """the pitch (Hz) of every 20 ms of a recording, 0 where no clear voice is heard; returns (pitch, samples/frame)"""
    import numpy as np
    a = np.asarray(a, dtype="float32")
    if sr != 16000:
        from math import gcd
        from scipy.signal import resample_poly
        g_ = gcd(16000, int(sr))
        x = resample_poly(a, 16000 // g_, int(sr) // g_).astype("float32")
    else:
        x = a
    n, hop = 640, 320
    if len(x) < n * 3:
        return np.zeros(0), sr * 0.02
    idx = np.arange(n)[None, :] + hop * np.arange((len(x) - n) // hop + 1)[:, None]
    out = np.zeros(len(idx))
    win = np.hanning(n).astype("float32")
    lo, hi = 16000 // 420, 16000 // 70
    wac = np.fft.irfft(np.abs(np.fft.rfft(win, 2048)) ** 2)[:n]
    wac = (wac / wac[0])[lo:hi]                       # (what the window alone does to a perfect tone)
    energy = np.zeros(len(idx))
    for s in range(0, len(idx), 3000):
        fr = x[idx[s:s + 3000]]
        fr = (fr - fr.mean(axis=1, keepdims=True)) * win
        sp = np.fft.rfft(fr, 2048, axis=1)
        ac = np.fft.irfft(sp.real ** 2 + sp.imag ** 2, axis=1)[:, :n]
        e = ac[:, 0] + 1e-9
        seg = ac[:, lo:hi] / e[:, None] / wac[None, :]
        # the SHORTEST period that repeats nearly as well as the best one (else a high voice is often read an
        # octave too low: twice its period repeats just as well)
        top = seg.max(axis=1)
        peak = np.zeros_like(seg, dtype=bool)
        peak[:, 1:-1] = (seg[:, 1:-1] > seg[:, :-2]) & (seg[:, 1:-1] >= seg[:, 2:])
        good = peak & (seg >= 0.85 * top[:, None])
        k = np.where(good.any(axis=1), good.argmax(axis=1), seg.argmax(axis=1))
        st = seg[np.arange(len(seg)), k]
        f = 16000.0 / (k + lo)
        f[st < 0.42] = 0
        out[s:s + 3000] = f
        energy[s:s + 3000] = e
    out[energy < np.percentile(energy, 95) * 0.004] = 0          # (too soft to be a voice)
    return out, sr * 0.02


def _marker_split(a, sr, lchars, high, thr):
    """Where each line lies in a recording with a marker word between the lines: [(start, end)] in samples, or None
    when the markers cannot be counted with certainty. high: the marker voice is higher than the line's voice."""
    import numpy as np
    n = len(lchars)
    f0, step = _f0_frames(a, sr)
    if n < 2 or f0.size < 50:
        return None, "too short"
    voiced = f0 > 0
    if voiced.sum() < 30:
        return None, "no voice found"
    main = float(np.median(f0[voiced]))
    like = voiced & ((f0 >= main * 1.3) if high else (f0 <= main * 0.77))
    runs, i = [], 0                                   # stretches in the other voice (a gap of 0.18 s = one word still)
    while i < len(like):
        if like[i]:
            j, last = i, i
            while j < len(like) and (like[j] or (j - last <= 9 and not (voiced[j] and not like[j]))):
                if like[j]:
                    last = j
                j += 1
            runs.append((i, last + 1))
            i = last + 1
        else:
            i += 1
    # a whole word in the other voice (one high syllable of a shout is too short to be the marker)
    cand = [(s, e) for s, e in runs if 0.26 <= (e - s) * 0.02 <= 1.7 and like[s:e].sum() >= 9]
    if not cand:
        return None, "no marker word was heard"
    if len(cand) > n - 1:                             # a shout of the speaker can sound high too: the markers are all
        if len(cand) - (n - 1) > max(2, n // 4):      # the same word - keep those most alike in length and pitch
            return None, f"{len(cand)} marker-like sounds for {n} lines"
        dur = np.array([e - s for s, e in cand], dtype=float)
        pit = np.array([np.median(f0[s:e][like[s:e]]) for s, e in cand])
        score = np.abs(dur - np.median(dur)) / max(1.0, np.median(dur)) + np.abs(pit - np.median(pit)) / np.median(pit)
        keep = sorted(np.argsort(score)[:n - 1])
        cand = [cand[k] for k in keep]
    dur = np.array([e - s for s, e in cand], dtype=float)         # the SAME word in the SAME voice every time
    pit = np.array([np.median(f0[s:e][like[s:e]]) for s, e in cand])
    if len(cand) >= 3 and ((np.abs(pit / np.median(pit) - 1) > 0.2).any() or (dur > np.median(dur) * 2.2).any()
                           or (dur < np.median(dur) * 0.45).any()):
        return None, "the marker words are not alike"
    hop = int(sr * 0.02)
    rms = np.array([np.sqrt((a[i:i + hop].astype("float32") ** 2).mean()) for i in range(0, max(1, len(a) - hop), hop)])
    quiet = rms < thr
    F = len(rms)

    def edge(fr, d):                                  # from a marker outwards to the nearest quiet moment (<= 0.5 s)
        for k in range(26):
            p_ = fr + d * k
            if 0 <= p_ < F and quiet[p_]:
                return p_
        return min(max(fr + d * 2, 0), F - 1)
    segs, start = [], 0                               # the stretches between the marker words
    for s, e in cand:
        segs.append((start, edge(s - 1, -1)))
        start = edge(e, 1)
    segs.append((start, F))
    m = len(segs)
    speech = np.array([float((~quiet[s:e]).sum()) * 0.02 for s, e in segs])
    rate = speech.sum() / max(1, sum(lchars))
    csum = np.concatenate([[0], np.cumsum(lchars)]) * rate
    fits = lambda sp, want: max(0.5, want) * 0.4 - 0.4 <= sp <= max(0.5, want) * 2.3 + 1.0
    # which lines lie in which stretch: all in order, every stretch at least one line (a marker Gemini left out
    # = two lines in one stretch) - the split whose lengths fit the words best
    INF = float("inf")
    cost = [[INF] * (n + 1) for _ in range(m + 1)]
    back = [[0] * (n + 1) for _ in range(m + 1)]
    cost[0][0] = 0.0
    for j in range(1, m + 1):
        for k in range(j, n - (m - j) + 1):
            for i in range(j - 1, k):
                if cost[j - 1][i] == INF:
                    continue
                want = csum[k] - csum[i]
                c_ = cost[j - 1][i] + abs(speech[j - 1] - want) / max(0.5, want)
                if c_ < cost[j][k]:
                    cost[j][k], back[j][k] = c_, i
    if cost[m][n] == INF:
        return None, "the marker words do not fit the lines"
    out, k = [None] * n, n
    for j in range(m, 0, -1):
        i = back[j][k]
        if k - i == 1 and fits(speech[j - 1], csum[k] - csum[i]) and speech[j - 1] >= 0.2:
            out[i] = (int(segs[j - 1][0] * hop), int(min(len(a), segs[j - 1][1] * hop)))   # ONE line between two markers
        k = i
    sure = sum(1 for x in out if x)
    if not sure:
        return None, "no line lies clearly between two marker words"
    return out, ("" if sure == n else f"{len(cand)} marker words for {n} lines")


SPK_VOICED = {}                 # seconds of speech per letter of every voice (pauses not counted)


CUT_HOW = [""]                  # how the last recording was cut: "count" (as many clear pauses as line ends) / "length"
SUSPECT = []                    # (how far off, line file) - lines whose length does not fit their words (maybe cut wrong)
TTS_SPARE = [0]                 # requests of today's share that are free for asking a recording again
SAMPLE = {"dir": None, "max": 16}   # a few raw recordings + their text are kept, to tune the cutting on REAL sound


def _best_cut(wav, plains):
    """ALWAYS cuts one recording of several lines into its lines (11 Nov 2026: every rule that threw a recording
    away for an uncertain line end cost the day's few free requests - in the end no story was in the Gemini voice).
    The cuts are placed in pauses, where the SPEECH TIME before each cut fits the letters of its line best (how long
    words take to say is steady; how long the pauses are is not), and long pauses are preferred. Returns (pieces, rate)."""
    import numpy as np
    from scipy.io import wavfile
    sr, a = wavfile.read(wav)
    a = a.astype("float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    n = len(plains)
    CUT_HOW[0] = "one"
    if n <= 1:
        return [a], sr
    hop = int(sr * 0.02)
    F = max(1, (len(a) - hop) // hop)
    rms = np.sqrt((a[:F * hop].reshape(F, hop) ** 2).mean(axis=1))
    p95 = max(float(np.percentile(rms, 95)), 1e-6)
    quiet = rms < p95 * 0.05
    cumv = np.concatenate([[0.0], np.cumsum(~quiet) * 0.02])          # speech seconds before every frame
    V = float(cumv[-1])
    tot = float(sum(max(1, len(p)) for p in plains))
    exp = [V * max(1, len(p)) / tot for p in plains]
    cand, i = [], 0                                    # (cut frame, pause seconds)
    while i < F:
        if quiet[i]:
            j = i
            while j < F and quiet[j]:
                j += 1
            if (j - i) * 0.02 >= 0.14 and i > 0 and j < F:
                cand.append(((i + j) // 2, (j - i) * 0.02))
            i = j
        else:
            i += 1
    by_len = sorted(cand, key=lambda c: -c[1])
    if len(cand) == n - 1 or (len(cand) >= n and by_len[n - 2][1] >= 1.35 * by_len[n - 1][1] and by_len[n - 2][1] >= 0.3):
        cuts = sorted(c for c, _l in by_len[:n - 1])     # exactly as many clear pauses as line ends: they are the ends
        b = [0] + [c * hop for c in cuts] + [len(a)]
        CUT_HOW[0] = "count"
        return [a[b[k]:b[k + 1]] for k in range(n)], sr
    CUT_HOW[0] = f"length ({len(cand)} pauses for {n - 1} ends)"
    if len(cand) < n - 1:                              # too few real pauses: the softest moments count as well
        sm = np.convolve(rms, np.ones(5) / 5, mode="same")
        have = {c for c, _l in cand}
        for f in range(8, F - 8):
            if sm[f] < p95 * 0.3 and sm[f] == sm[f - 7:f + 8].min() and not any(abs(f - c) < 8 for c in have):
                cand.append((f, 0.0))
                have.add(f)
        cand.sort()
    if len(cand) < n - 1:                              # nothing to hold on to: by the length of the words alone
        cuts, acc = [], 0.0
        for e in exp[:-1]:
            acc += e
            cuts.append(int(np.searchsorted(cumv, acc)))
    else:
        C, K = len(cand), n - 1
        pos = [cumv[c] for c, _l in cand]
        bonus = [0.8 * min(l, 1.3) for _c, l in cand]
        w = [1.0 / (0.5 + e ** 0.5) for e in exp]
        INF = float("inf")
        cost = [[INF] * C for _ in range(K)]
        back = [[-1] * C for _ in range(K)]
        for c in range(C - (K - 1)):
            cost[0][c] = abs(pos[c] - exp[0]) * w[0] - bonus[c]
        for k in range(1, K):
            for c in range(k, C - (K - 1 - k)):
                best, bi = INF, -1
                for p in range(k - 1, c):
                    if cost[k - 1][p] == INF:
                        continue
                    v = cost[k - 1][p] + abs(pos[c] - pos[p] - exp[k]) * w[k]
                    if v < best:
                        best, bi = v, p
                if bi >= 0:
                    cost[k][c] = best - bonus[c]
                    back[k][c] = bi
        last = min(range(C), key=lambda c: cost[K - 1][c] + abs(V - pos[c] - exp[K]) * w[K])
        picks = [last]
        for k in range(K - 1, 0, -1):
            picks.append(back[k][picks[-1]])
        cuts = [cand[c][0] for c in reversed(picks)]
    b = [0] + [c * hop for c in cuts] + [len(a)]
    return [a[b[k]:b[k + 1]] for k in range(n)], sr


# ===================== v73: line ends from an ALIGNMENT with a machine reading (tuned on real recordings) ============
_ESPK = {}

def _espeak_lib():
    if "lib" in _ESPK:
        return _ESPK["lib"]
    import ctypes
    import numpy as np
    try:
        import espeakng_loader
    except ImportError:                               # (not in the workflow's package list: fetched once, a few seconds)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "espeakng-loader"], capture_output=True, timeout=240)
        import espeakng_loader
    lib = ctypes.CDLL(espeakng_loader.get_library_path())
    CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
    buf = []
    def cb(wav, n, events):
        if wav and n > 0:
            buf.append(np.ctypeslib.as_array(wav, shape=(n,)).copy())
        return 0
    _ESPK["cb"] = CB(cb)                                  # (kept alive)
    _ESPK["buf"] = buf
    lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    sr = lib.espeak_Initialize(1, 0, os.path.dirname(espeakng_loader.get_data_path()).encode(), 0)   # 1 = retrieval
    if sr <= 0:
        sr = lib.espeak_Initialize(1, 0, espeakng_loader.get_data_path().encode(), 0)
    lib.espeak_SetSynthCallback(_ESPK["cb"])
    lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
                                 ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.c_void_p]
    _ESPK["lib"], _ESPK["sr"] = lib, sr
    return lib

def _espeak_say(text, lang="bn", rate=None):
    import numpy as np
    lib = _espeak_lib()
    if rate and _ESPK.get("rate") != rate:
        lib.espeak_SetParameter(1, int(rate), 0)       # 1 = espeakRATE (words a minute)
        _ESPK["rate"] = rate
    if _ESPK.get("lang") != lang:
        if lib.espeak_SetVoiceByName(lang.encode()) != 0:
            raise RuntimeError(f"espeak has no voice '{lang}'")
        _ESPK["lang"] = lang
    del _ESPK["buf"][:]
    b = text.encode("utf-8")
    lib.espeak_Synth(b, len(b) + 1, 0, 0, 0, 1, None, None)        # 1 = the text is UTF-8
    lib.espeak_Synchronize()
    a = np.concatenate(_ESPK["buf"]) if _ESPK["buf"] else np.zeros(0, dtype=np.int16)
    return a, _ESPK["sr"]


def _al_feats(a, sr, ncep=6, delta=False, smooth=7):
    """a few smoothed MFCC every 20 ms of the SPEECH frames only (normalised) + each kept frame's time in seconds.
    (Few and smoothed: tuned on real recordings - two different machine readings then agree on 92% of the sentence
    ends; with 12 sharp ones only on 50%.)"""
    import numpy as np
    from math import gcd
    from scipy.signal import resample_poly
    a = np.asarray(a, dtype="float32")
    if sr != 16000:
        g = gcd(16000, int(sr)); a = resample_poly(a, 16000 // g, int(sr) // g).astype("float32")
    a = np.append(a[0], a[1:] - 0.97 * a[:-1])
    win, hop, nfft = 400, 160, 512
    n = (len(a) - win) // hop + 1
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(a[idx] * np.hamming(win)[None, :], nfft)) ** 2
    mel = lambda f: 2595 * np.log10(1 + f / 700.0)
    imel = lambda m: 700 * (10 ** (m / 2595.0) - 1)
    pts = imel(np.linspace(mel(80), mel(7600), 28)); bins = np.floor((nfft + 1) * pts / 16000).astype(int)
    fb = np.zeros((26, nfft // 2 + 1))
    for k in range(26):
        l, c, r = bins[k], bins[k + 1], bins[k + 2]
        if c > l: fb[k, l:c] = (np.arange(l, c) - l) / (c - l)
        if r > c: fb[k, c:r] = (r - np.arange(c, r)) / (r - c)
    lm = np.log(spec @ fb.T + 1e-6)
    e = lm.mean(axis=1)
    k_ = np.arange(26)[None, :]
    dct = np.cos(np.pi * np.arange(1, ncep + 1)[:, None] * (2 * k_ + 1) / 52)
    mf = lm @ dct.T
    en = np.log(spec.sum(axis=1) + 1e-6)
    speech = en > np.percentile(en, 95) - 4.6          # within ~1/100 of the loud frames' energy
    mf = mf[::2]; speech = speech[::2]; t = (np.arange(n) * hop / 16000.0)[::2]
    keep = np.where(speech)[0]
    x = mf[keep]
    x = (x - x.mean(axis=0)) / (x.std(axis=0) + 1e-6)
    if smooth:
        ker = np.ones(smooth) / smooth
        x = np.stack([np.convolve(x[:, j], ker, mode="same") for j in range(x.shape[1])], axis=1)
    if not delta:
        return x.astype("float32"), t[keep]
    d = np.zeros_like(x); d[1:-1] = (x[2:] - x[:-2]) / 2
    return np.hstack([x, d]).astype("float32"), t[keep]

def _al_dtw(A, B):
    """best monotonic path between A (reference) and B (recording); returns for every A frame its last B frame"""
    import numpy as np
    n, m = len(A), len(B)
    D = np.full((n + 1, m + 1), np.inf, dtype="float32"); D[0, 0] = 0
    BT = np.zeros((n + 1, m + 1), dtype="int8")
    B2 = (B * B).sum(axis=1)
    for i in range(1, n + 1):
        c = np.sqrt(np.maximum(0, (A[i - 1] ** 2).sum() + B2 - 2 * B @ A[i - 1]))
        diag = D[i - 1, :-1]; up = D[i - 1, 1:]
        best = np.minimum(diag, up); bt = np.where(diag <= up, 0, 1)        # 0 diag, 1 up (ref advances, audio stays)
        row = np.empty(m + 1, dtype="float32"); row[0] = np.inf
        # left moves (audio advances, ref stays): running minimum
        v = best + c
        acc = np.empty(m, dtype="float32"); btr = bt.copy()
        run = np.inf
        # vectorised left-chain: D[i,j] = c[j] + min(best[j], D[i,j-1])
        cs = np.cumsum(c)
        g = best - np.concatenate([[0], cs[:-1]])
        gm = np.minimum.accumulate(g)
        acc = c + np.concatenate([[0], cs[:-1]]) + gm - 0  # = c[j] + cs[j-1] + min_k<=j (best[k] - cs[k-1])
        left = gm < g - 1e-9
        btr[left] = 2
        row[1:] = acc
        D[i] = row; BT[i, 1:] = btr
    i, j = n, m
    last = np.zeros(n, dtype=int)
    seen = set()
    while i > 0 and j > 0:
        if i - 1 not in seen:
            last[i - 1] = j - 1; seen.add(i - 1)
        b = BT[i, j]
        if b == 0: i -= 1; j -= 1
        elif b == 1: i -= 1
        else: j -= 1
    return last, float(D[n, m]) / (n + m)


def _cut_plan(a, sr, plains, lang="bn", use_ref=True):
    """Where the sentences of one recording end, and which stretches hold speech that is NOT in the text.
    Found three ways together (tuned on real Gemini recordings, 11 Nov 2026 - its pauses alone say nothing: it
    pauses after nearly every phrase, half of a recording is silence): (1) the recording is ALIGNED with a plain
    machine reading of the same words (espeak-ng, three speeds); (2) the speech time of every sentence must fit its
    letters; (3) a cut lies in a pause, long pauses first. A sentence with far more speech than its words need
    (said twice, or the style note read out in English) keeps only the stretch that fits the reading best.
    Returns dict(cuts=[seconds, n-1], drop=[(start, end) seconds], info=text)."""
    import numpy as np
    n = len(plains)
    hop = int(sr * 0.02)
    F = max(1, (len(a) - hop) // hop)
    rms = np.sqrt((a[:F * hop].reshape(F, hop) ** 2).mean(axis=1))
    quiet = rms < max(float(np.percentile(rms, 95)) * 0.05, 1e-6)
    pauses, i = [], 0
    while i < F:
        if quiet[i]:
            j = i
            while j < F and quiet[j]:
                j += 1
            if (j - i) * 0.02 >= 0.12 and i > 0 and j < F:
                pauses.append((i, j))
            i = j
        else:
            i += 1
    letters = np.array([max(1, len(p)) for p in plains], dtype=float)
    speech_mask = ~quiet
    ref_t = spread = None
    drop = []
    info = []
    if use_ref and n > 1:
        try:
            GA, gt = _al_feats(a, sr)
            allr, refs = [], []
            for rate in (130, 165, 200):
                ref, ends = [], []
                for p in plains:
                    w, rsr = _espeak_say(p, lang, rate=rate)
                    ref.append(w.astype("float32"))
                    ends.append(sum(len(x) for x in ref) / rsr)
                RA, rt = _al_feats(np.concatenate(ref), rsr)
                last, _c = _al_dtw(RA, GA)
                allr.append([float(gt[last[max(0, np.searchsorted(rt, c) - 1)]]) for c in ends[:-1]])
                refs.append((RA, rt, ends))
            arr = np.array(allr)
            ref_t, spread = np.median(arr, axis=0), arr.max(axis=0) - arr.min(axis=0)
            # --- speech that is not in the text: a sentence whose stretch holds far more speech than its words need
            cum = np.concatenate([[0.0], np.cumsum(speech_mask) * 0.02])
            at = lambda t: cum[min(F, max(0, int(round(t / 0.02))))]
            edges = [0.0] + list(ref_t) + [F * 0.02]
            sp = np.array([at(edges[k + 1]) - at(edges[k]) for k in range(n)])
            rate_ = float(np.median(sp / letters))
            RA, rt, ends = refs[1]
            for k in range(n):
                need = letters[k] * rate_
                if not (sp[k] > need * 1.75 and sp[k] - need >= 2.5):
                    continue
                f0, f1 = int(edges[k] / 0.02), int(edges[k + 1] / 0.02)
                inner = [(max(f0, s), min(f1, e)) for s, e in pauses if e > f0 and s < f1]
                bounds = [f0] + [(s + e) // 2 for s, e in inner if s > f0 and e < f1] + [f1]
                chunks = [(bounds[q], bounds[q + 1]) for q in range(len(bounds) - 1)
                          if speech_mask[bounds[q]:bounds[q + 1]].sum() * 0.02 >= 0.15]
                if len(chunks) < 2:
                    continue
                r0 = 0 if k == 0 else np.searchsorted(rt, ends[k - 1])
                r1 = np.searchsorted(rt, ends[k])
                R = RA[r0:r1]
                best = None
                for x in range(len(chunks)):
                    for y in range(x, len(chunks)):
                        s_, e_ = chunks[x][0], chunks[y][1]
                        spw = speech_mask[s_:e_].sum() * 0.02
                        if not (need * 0.55 <= spw <= need * 1.45):
                            continue
                        g0, g1 = np.searchsorted(gt, s_ * 0.02), np.searchsorted(gt, e_ * 0.02)
                        if g1 - g0 < 8 or len(R) < 8:
                            continue
                        _l, c_ = _al_dtw(R, GA[g0:g1])
                        if best is None or c_ < best[0]:
                            best = (c_, s_, e_)
                if best:
                    _c, s_, e_ = best
                    for cs, ce in chunks:
                        if ce <= s_ or cs >= e_:
                            drop.append((cs * 0.02, ce * 0.02))
                    info.append(f"sentence {k + 1}: {sp[k]:.1f} s of speech for words that need {need:.1f} s - "
                                f"{sum(e - s for s, e in drop if f0 * 0.02 <= s < f1 * 0.02):.1f} s left out")
        except Exception as ex:
            info.append(f"no machine reading ({str(ex)[:60]})")
            ref_t = None
    # --- the cuts: pauses whose speech time fits the letters, near where the machine reading says, long pauses first
    keepf = speech_mask.copy()
    for s, e in drop:
        keepf[int(s / 0.02):int(e / 0.02)] = False
    cum = np.concatenate([[0.0], np.cumsum(keepf) * 0.02])
    V = float(cum[-1])
    exp = V * letters / letters.sum()
    cand = [((s + e) // 2, (e - s) * 0.02) for s, e in pauses if not any(ds <= (s + e) / 2 * 0.02 <= de for ds, de in drop)]
    if len(cand) < n - 1:
        cuts = [float(np.searchsorted(cum, acc) * 0.02) for acc in np.cumsum(exp)[:-1]]
        return dict(cuts=cuts, drop=drop, info="; ".join(info + ["too few pauses - cut by length"]))
    C, K = len(cand), n - 1
    pos = np.array([cum[c] for c, _l in cand])
    tm = np.array([c * 0.02 for c, _l in cand])
    bonus = np.array([0.8 * min(l, 1.3) for _c, l in cand])
    w = 1.0 / (0.5 + np.sqrt(exp))
    INF = 1e18
    cost = np.full((K, C), INF)
    back = np.zeros((K, C), dtype=int)
    refc = (lambda k: 0.45 * np.minimum(np.abs(tm - ref_t[k]), 4.0) / (1.0 + 0.5 * spread[k])) if ref_t is not None else (lambda k: 0.0)
    cost[0] = np.abs(pos - exp[0]) * w[0] - bonus + refc(0)
    for k in range(1, K):
        for c in range(k, C - (K - 1 - k)):
            v = cost[k - 1][k - 1:c] + np.abs(pos[c] - pos[k - 1:c] - exp[k]) * w[k]
            j = int(np.argmin(v))
            cost[k][c] = v[j] - bonus[c] + (refc(k)[c] if ref_t is not None else 0.0)
            back[k][c] = j + k - 1
    fin = cost[K - 1] + np.abs(V - pos - exp[K]) * w[K]
    c = int(np.argmin(fin[K - 1:])) + K - 1
    picks = [c]
    for k in range(K - 1, 0, -1):
        picks.append(int(back[k][picks[-1]]))
    cuts = [float(tm[c]) for c in reversed(picks)]
    return dict(cuts=cuts, drop=drop, info="; ".join(info))


def _short_feel(feel):
    """'naturally, a deep, heavy ... (380 letters) ...; feeling: eerie' -> 'eerie'; 'terrified, breathing fast, voice
    trembling, low, tense voice' -> 'terrified, breathing fast'"""
    f = str(feel or "")
    if "feeling:" in f:
        f = f.rsplit("feeling:", 1)[1]
    f = re.split(r"[;:.]", f.strip())[0]
    f = ", ".join(x.strip() for x in f.split(",")[:2] if x.strip())
    return (f[:48] or "naturally")


def _keep_sample(tmp, g, got):
    """saves this raw recording (small .ogg) and its lines - only the first few, see SAMPLE"""
    d = SAMPLE.get("dir")
    if not d or len({x["line"] for x in g}) < 3:
        return
    try:
        os.makedirs(d, exist_ok=True)
        have = [f for f in os.listdir(d) if f.endswith(".ogg")]
        if len(have) >= int(SAMPLE.get("max") or 8):
            return
        name = f"s_{dt.datetime.now().strftime('%m%d_%H%M%S')}_{len(have)}"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-ac", "1", "-ar", "24000", "-c:a", "libopus",
              "-b:a", "24k", os.path.join(d, name + ".ogg")])
        lines = list(dict.fromkeys(x["line"] for x in g))
        _js(os.path.join(d, name + ".json"), {
            "voice": g[0]["voice"], "who": g[0]["who"], "seconds": round(got, 1), "plan": dict(TTS_PLAN),
            "pieces": [{"line": lines.index(x["line"]), "plain": x["plain"], "text": x["text"], "feel": x["feel"]}
                       for x in g]})
    except Exception as ex:
        log(f"    voice sample not kept: {str(ex)[:80]}")


def tts_gemini_batch(items, lang_label, sr=44100, minutes=45, max_requests=None):
    """items: dict(text, plain, voice, who, feel, spk, out, lang[, line]) - the sentences of the lines ("line" = the
    voice file of the whole line). One request per group, and EVERY recording is used (11 Nov 2026): Google gives only
    ~36 free requests a day, and each rule that threw a recording away because a line end was 'not certain' cost so
    many of them that in the end whole stories fell back to the Chirp voice. Only a recording that is clearly broken
    (far too long / short, or something heard twice) is asked for ONCE more, and only while spare requests are left.
    Lines whose length does not fit their words go to SUSPECT - they are made again one by one afterwards if the
    day's share still has room. Returns True when every line is done."""
    import numpy as np
    from scipy.io import wavfile
    t0 = time.time()
    for x in items:
        x.setdefault("line", x["out"])
    groups = tts_groups(items)
    n_lines = len({x["line"] for x in items})
    log(f"  {n_lines} lines ({len(items)} sentences) in {len(groups)} voice requests")
    done_lines, retried = set(), set()
    room = lambda n: max_requests is None or TTS_USED[0] + n <= max_requests
    gi = -1
    while gi + 1 < len(groups):
        gi += 1
        g = groups[gi]
        if TTS_STATE["off"] or not gemini_quota_left():
            log("  expressive voices: today's free limit is over")
            return False
        if not room(1):
            log("  expressive voices: today's planned share is used")
            return False
        if time.time() - t0 > float(env("TTS_MAX_MINUTES") or 75) * 60:
            log("  expressive voices: safety time limit reached")
            return False
        x0 = g[0]
        lang = x0.get("lang", "bn")
        note = f"Speaker1 is {x0['who']}. " + PRONOUNCE.get(lang, "")
        data = None
        for attempt in range(2):                      # one quiet retry for a busy server, never more
            TTS_USED[0] += 1
            if len(g) > 1:
                # the long description of the voice goes with the FIRST sentence only; every other sentence gets just
                # its feeling in 2-6 words (11 Nov 2026, measured on real recordings: the storyteller's 380-letter
                # note on every sentence was sometimes READ OUT in English - 6-8 s of extra speech in the story)
                data = _tts_call(_requests_for([("Speaker1", x["text"], x["feel"] if k == 0 else _short_feel(x["feel"]))
                                                for k, x in enumerate(g)], [("Speaker1", x0["voice"])], lang_label, note))
            else:
                data = _tts_call([_single_body(mm, x0["text"], x0["voice"], f"{x0['who']}. {x0['feel']}. "
                                               + PRONOUNCE.get(lang, ""), lang_label) for mm in NEW_TTS + OLD_TTS])
            if data or not gemini_quota_left() or not room(1):
                break
            time.sleep(45)
        if not data:
            log("  expressive voices: no answer (limit over or server busy) - the rest gets the backup voice")
            return False
        tmp = x0["out"] + ".group.wav"
        got = _audio_file(data, tmp, sr, trim=True)
        plains = [x["plain"] for x in g]
        keys = [x["line"] for x in g]
        lines = list(dict.fromkeys(keys))
        chars = sum(len(p) for p in plains)
        vk = f"{x0['voice']}|{x0['who']}"
        gid = x0["out"]
        can_retry = gid not in retried and TTS_SPARE[0] > 0 and room(1)
        expect = chars / 8.0 + 1.0 * (len(g) - 1)
        missing = bool(SPK_RATE.get(vk)) and chars >= 120 and got < chars * SPK_RATE[vk] * 0.6
        broken = missing or got > expect * 2.0 + 4 or got < expect * 0.33
        twice = ""                                    # (something said twice is CUT OUT now, see _cut_plan)
        try:
            _keep_sample(tmp, g, got)
        except Exception:
            pass
        if (broken or twice) and can_retry:           # clearly not what was asked: once more (a spare request)
            retried.add(gid)
            TTS_SPARE[0] -= 1
            os.remove(tmp)
            groups.insert(gi + 1, g)
            log(f"  voices: a recording of {got:.0f} s for ~{expect:.0f} s of words"
                + (f" - {twice}" if twice else "") + " - asked once more")
            continue
        if got < max(0.5, expect * 0.2):              # (nearly) nothing was said: these lines stay open
            os.remove(tmp)
            log(f"  voices: an empty recording ({got:.1f} s) - {len(lines)} lines stay open")
            continue
        rate, allv = wavfile.read(tmp)
        allv = allv.astype("float32")
        if allv.ndim > 1:
            allv = allv.mean(axis=1)
        os.remove(tmp)
        hop = int(rate * 0.02)
        fr = np.array([np.sqrt((allv[i:i + hop] ** 2).mean()) for i in range(0, max(1, len(allv) - hop), hop)])
        thr = max(float(np.percentile(fr, 95)) * 0.05, 1e-6) if fr.size else 1e-6
        how = "one"
        if len(g) > 1:
            try:
                plan = _cut_plan(allv, rate, plains, lang, use_ref=env("TTS_ALIGN") != "0")
            except Exception as ex:
                log(f"    alignment failed ({str(ex)[:80]}) - cut by the length of the words")
                plan = _cut_plan(allv, rate, plains, lang, use_ref=False)
            how = "reading" if "no machine reading" not in plan["info"] and env("TTS_ALIGN") != "0" else "length"
            if plan["drop"]:
                log(f"  voices: speech that is not in the story left out - {plan['info'][:260]}")
            ends = [int(c * rate) for c in plan["cuts"]] + [len(allv)]
            starts = [0] + ends[:-1]
            segs = []
            for ln in lines:                          # a line = from its first sentence's start to its last one's end,
                idx = [k for k, kk in enumerate(keys) if kk == ln]     # without the stretches that were left out
                s_, e_ = starts[idx[0]], ends[idx[-1]]
                parts_, pos_ = [], s_
                for ds, de in sorted(plan["drop"]):
                    ds, de = int(ds * rate), int(de * rate)
                    if de <= s_ or ds >= e_:
                        continue
                    parts_.append(allv[pos_:max(pos_, ds)])
                    pos_ = max(pos_, de)
                parts_.append(allv[pos_:e_])
                segs.append(np.concatenate(parts_) if parts_ else allv[s_:e_])
        else:
            segs = [allv]
        lchars = [sum(len(plains[k]) for k, kk in enumerate(keys) if kk == ln) for ln in lines]
        voiced = [_voiced(s_, rate, thr) for s_ in segs]
        good = 0
        for k, ln in enumerate(lines):
            if len(segs[k]) < rate * 0.15:
                continue
            try:
                seg = _tight(segs[k], rate, thr)
                wavfile.write(ln + ".seg.wav", rate, np.clip(seg, -32768, 32767).astype(np.int16))
                if _audio_file(open(ln + ".seg.wav", "rb").read(), ln, sr, trim=True) < 0.2 and os.path.exists(ln):
                    os.remove(ln)                       # (almost) silent: this line is made alone afterwards
                else:
                    good += 1
                    done_lines.add(ln)
            except Exception as ex:
                log(f"    one line could not be used ({str(ex)[:80]})")
                if os.path.exists(ln):
                    os.remove(ln)
            finally:
                if os.path.exists(ln + ".seg.wav"):
                    os.remove(ln + ".seg.wav")
        # how long a text takes to SAY is fairly steady for one voice: a line far off may hold a sentence of its
        # neighbour (or something said twice) - noted, and made again alone later if requests are left
        rates = [v / c for v, c in zip(voiced, lchars) if c >= 25 and v > 0]
        ref = float(np.median(rates)) if len(rates) >= 3 else SPK_VOICED.get(vk)
        odd = 0
        if ref and len(lines) > 1:
            for k, ln in enumerate(lines):
                if lchars[k] >= 20 and voiced[k] > 0:
                    r_ = voiced[k] / (lchars[k] * ref)
                    if (r_ > 1.45 and voiced[k] - lchars[k] * ref >= 1.0) or r_ < 0.62:
                        SUSPECT.append((abs(math.log(r_)) + (0.15 if how == "length" else 0), ln))
                        odd += 1
            SPK_VOICED[vk] = ref if vk not in SPK_VOICED else SPK_VOICED[vk] * 0.6 + ref * 0.4
        if chars >= 60 and not broken:
            r_ = got / chars
            SPK_RATE[vk] = r_ if vk not in SPK_RATE else SPK_RATE[vk] * 0.6 + r_ * 0.4
        CUT_STATS[0 if how in ("reading", "one") else 1] += 1
        log(f"  voices: {len(done_lines)}/{n_lines} lines ({(time.time() - t0) / 60:.1f} min, {TTS_USED[0]} requests; "
            f"cut by {how}" + (f", {odd} line(s) to check" if odd else "") + ")")
    return len(done_lines) == n_lines


CUT_STATS = [0, 0]              # recordings cut by the count of their pauses / by the length of the words


# ===================== v57: Google Cloud "Chirp 3 HD" - the backup voice when Gemini's free day is used up =====================
# The 30 Chirp 3 HD Bengali voices carry the SAME names as the Gemini voices (Charon, Kore, Puck ...), so a character
# keeps (nearly) the same voice. 1 million letters a month are free; the bot stops itself at CHIRP_MONTH_CAP.
# One line per request: nothing has to be cut apart, so no word can go missing.
CHIRP_VOICES = ("Achernar", "Aoede", "Autonoe", "Callirrhoe", "Despina", "Erinome", "Gacrux", "Kore", "Laomedeia",
                "Leda", "Pulcherrima", "Sulafat", "Vindemiatrix", "Zephyr", "Achird", "Algenib", "Algieba",
                "Alnilam", "Charon", "Enceladus", "Fenrir", "Iapetus", "Orus", "Puck", "Rasalgethi", "Sadachbia",
                "Sadaltager", "Schedar", "Umbriel", "Zubenelgenubi")
CHIRP_STATE = {"off": False, "rate_ok": True}


def _month():
    return dt.datetime.now(IST).strftime("%Y-%m")


def chirp_used(path):
    d = _jl(path, {}) if path else {}
    c = (d.get("chirp") or {}) if isinstance(d, dict) else {}
    return int(c.get("chars", 0)) if c.get("month") == _month() else 0


def chirp_left(path):
    return max(0, int(env("CHIRP_MONTH_CAP") or 900000) - chirp_used(path))


def chirp_ok(path):
    return bool(env("GOOGLE_TTS_KEY")) and env("CHIRP") != "0" and not CHIRP_STATE["off"] and chirp_left(path) > 2000


def _chirp_add(path, n):
    d = _jl(path, {})
    d = d if isinstance(d, dict) else {}
    used = chirp_used(path)
    d["chirp"] = {"month": _month(), "chars": used + int(n)}
    _js(path, d)


def chirp_tts(text, voice, out_wav, sr, usage_path, lang="bn"):
    """One line in the Chirp 3 HD voice of the same name. Returns True when the line is ready."""
    import base64 as _b64
    if not chirp_ok(usage_path):
        return False
    text = re.sub(r"\s{2,}", " ", strip_tags(str(text))).strip()
    if not text:
        return False
    if len(text) > chirp_left(usage_path):
        CHIRP_STATE["off"] = True
        log("  Chirp voice: this month's free share is used up")
        return False
    name = voice if voice in CHIRP_VOICES else "Charon"
    code = {"bn": "bn-IN", "hi": "hi-IN"}.get(lang, "bn-IN")
    body = {"input": {"text": text[:1500]},
            "voice": {"languageCode": code, "name": f"{code}-Chirp3-HD-{name}"},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}}
    if CHIRP_STATE["rate_ok"]:
        body["audioConfig"]["speakingRate"] = float(env("CHIRP_RATE") or 0.9)   # a grave, unhurried telling
    for attempt in range(3):
        try:
            r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                              params={"key": env("GOOGLE_TTS_KEY")}, json=body, timeout=90)
        except Exception as e:
            log(f"  Chirp voice: {str(e)[:100]}")
            time.sleep(5)
            continue
        if r.status_code == 400 and "speakingRate" in body["audioConfig"]:
            CHIRP_STATE["rate_ok"] = False            # this voice type does not take a speed: plain speed then
            body["audioConfig"].pop("speakingRate", None)
            continue
        if r.status_code == 429:
            time.sleep(20)
            continue
        if r.status_code in (401, 403):
            log(f"  Chirp voice refused ({r.status_code}): {r.text[:200]} - check GOOGLE_TTS_KEY / billing on the project")
            CHIRP_STATE["off"] = True
            note("Chirp গলা কাজ করছে না - GOOGLE_TTS_KEY বা bhut project-এর billing দেখুন")
            return False
        if not r.ok:
            log(f"  Chirp voice: {r.status_code} {r.text[:150]}")
            time.sleep(5)
            continue
        audio = r.json().get("audioContent")
        if not audio:
            return False
        _chirp_add(usage_path, len(text))
        return _audio_file(_b64.b64decode(audio), out_wav, sr, trim=True) > 0.2
    return False


def _pacific_day():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=8)).date().isoformat()


def seconds_until_reset():
    """Seconds until Google's free limits start again (midnight in California)."""
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=8)
    nxt = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (nxt - now).total_seconds()


def tts_budget_left(path):
    """Google's free voice limit is counted per day (it starts again at midnight in California = about 1:30 PM
    India time): how many requests are still free today, from what this bot used (assets/tts_usage.json)."""
    d = _jl(path, {})
    used = int(d.get("used", 0)) if d.get("day") == _pacific_day() else 0
    return max(0, int(env("TTS_DAY_BUDGET") or 36) - used)


def tts_budget_use(path):
    d = _jl(path, {})
    used = int(d.get("used", 0)) if d.get("day") == _pacific_day() else 0
    if not isinstance(d, dict):
        d = {}
    d.update({"day": _pacific_day(), "used": used + TTS_USED[0]})    # other saved keys (the story length) stay
    _js(path, d)
    TTS_USED[0] = 0


# ===================== v10: hooks that keep people watching + truly frightening horror =====================
HOOK_RULES = """
KEEP THEM WATCHING (very important - most viewers leave in the first 10 seconds):
- COLD OPEN: the first 1-2 lines jump to the most gripping moment of the story (a scream, a shock, a funny
  disaster, a mystery) - then "but how did it all begin? ..." and the story starts. Never start with a slow
  introduction, never with "once upon a time" alone.
- THE VIDEO STARTS DIRECTLY WITH SCENE 1 (the title comes after it): its very first line is max 10 words, spoken
  by a character, and grabs instantly - a shout, a shock, a funny disaster, a mystery ('আরে! আমার ঘুড়িটা আকাশে
  উধাও!'), with a sound effect. Never begin with a calm description or 'once upon a time'.
- SCENE 1 is the SHORTEST scene (about 15-25 seconds: 4-6 lines, each max 12 words). No explaining, no slow
  description, no names-and-background: the tension rises line by line and the scene STOPS on a cliffhanger (a
  scream, a knock, a face at the window, an unanswered question) - the title cuts in exactly there.
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
    accounts = [(env("CF_ACCOUNT_ID"), env("CF_API_TOKEN"))]
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
    left = (at - dt.datetime.now(IST)).total_seconds() / 60 - float(env("VOICE_RESERVE") or 40)
    return int(max(30, min(float(env("VOICE_MAX") or 120), left)))


PENDING = []          # comments that can only be posted once the scheduled video is live


def wait_for_publish():
    """Is the video live? GitHub minutes are precious (2,000 free a month), so we no longer sit and wait for
    hours: if the video goes live later, its comments are kept and the NEXT run posts them (flush_pending).
    Returns True when the comments can be posted now."""
    at = PUBLISH["at"]
    if not (PUBLISH["used"] and at):
        return True
    left = (at - dt.datetime.now(IST)).total_seconds() + 60
    if left <= 0:
        return True
    # public repositories: GitHub minutes are free, so we wait (up to 4 hours) and comment the moment it is live.
    # Secret WAIT_FOR_LIVE = 0 (e.g. for a private repository): don't wait, the next run posts the comments.
    if left <= 300 or (env("WAIT_FOR_LIVE") != "0" and left <= 4 * 3600):
        log(f"  waiting {left / 60:.0f} min until the video is live, then comments")
        time.sleep(left)
        return True
    log(f"  the video goes live in {left / 60:.0f} min - its comments will be posted by the next run")
    return False


def comment_when_live(object_id, text, live):
    if live:
        return fb_comment(object_id, text)
    PENDING.append({"id": str(object_id), "text": text})
    return None


def flush_pending(history):
    """Start of every run: post the comments of earlier videos that have gone live since.
    Returns True if anything changed (then the caller saves the history at once)."""
    changed = False
    for h in history[-8:]:
        todo = h.get("pending_comments") or []
        if not todo:
            continue
        left = []
        for c in todo:
            try:
                fb_comment(c["id"], c["text"])
                log("  earlier video's comment posted")
            except Exception as e:
                log("  earlier comment not posted:", str(e)[:120])
                if c.get("tries", 0) < 2:
                    left.append(dict(c, tries=c.get("tries", 0) + 1))
        h["pending_comments"] = left
        changed = True
    return changed


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


# ===================== v49: the horror poster in the channel's own style (the reference the owner chose) ===========
# LEFT: a stack of words - a small white place word on a red brush stroke, a huge worn YELLOW name, a white
# connecting line, two dripping BLOOD-RED / white words, and at the bottom a red brush banner with yellow words
# ("সত্য ঘটনা অবলম্বনে"). RIGHT / BEHIND: the haunted place at night, a full moon, fog, the ghost on the right and
# a giant ghost face looming in the sky. Only the words and the picture change from story to story.
POSTER_FONTS = {
    "brush": "https://raw.githubusercontent.com/google/fonts/main/ofl/galada/Galada-Regular.ttf",
    "bold": "https://raw.githubusercontent.com/google/fonts/main/ofl/atma/Atma-Bold.ttf",
}


def _poster_font(kind, size, fallback):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work", f"poster_{kind}.ttf")
    try:
        if not os.path.exists(path) and env("MOCK") != "1":
            os.makedirs(os.path.dirname(path), exist_ok=True)
            r = requests.get(POSTER_FONTS[kind], timeout=60)
            if r.ok and len(r.content) > 50000:
                open(path, "wb").write(r.content)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    except Exception as e:
        log(f"  poster font: {str(e)[:80]}")
    return ImageFont.truetype(fallback, size)


def _brush_band(img, box, color=(196, 18, 24), seed=1, tails=True):
    """A rough red brush stroke behind words (ragged edges, darker streaks, tapering tails)."""
    import numpy as np
    rnd = np.random.default_rng(seed)
    x0, y0, x1, y1 = box
    h = y1 - y0
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for k in range(7):                                # several overlapping strokes = a painted look
        jy = rnd.integers(-h // 8, h // 8 + 1)
        pts_top = [(x, y0 + jy + rnd.integers(-h // 7, h // 7 + 1)) for x in range(x0, x1 + 1, 18)]
        pts_bot = [(x, y1 + jy + rnd.integers(-h // 7, h // 7 + 1)) for x in range(x1, x0 - 1, -18)]
        a = int(150 + 105 * (k == 0))
        c = tuple(max(0, v - int(rnd.integers(0, 40))) for v in color)
        d.polygon(pts_top + pts_bot, fill=c + (a,))
    if tails:                                         # a few thin dry-brush tails out of both ends
        for side in (-1, 1):
            xs = x0 if side < 0 else x1
            for t in range(2):
                yy = y0 + h * (0.35 + 0.3 * t)
                ln = int(h * (0.5 + 0.4 * rnd.random()))
                d.polygon([(xs, yy - h * 0.07), (xs + side * ln, yy + side * h * 0.03), (xs, yy + h * 0.07)],
                          fill=color + (150,))
    streak = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(streak)
    for _ in range(40):                               # dry-brush streaks
        yy = int(rnd.integers(y0, y1))
        sd.line([(int(rnd.integers(x0, x1)), yy), (int(rnd.integers(x0, x1)), yy)], fill=90, width=2)
    dark = Image.new("RGBA", img.size, (60, 0, 0, 0))
    dark.putalpha(Image.fromarray((np.array(streak) * (np.array(layer)[:, :, 3] > 0)).astype("uint8")))
    base = Image.alpha_composite(img.convert("RGBA"), layer)
    return Image.alpha_composite(base, dark).convert("RGB")


def _drip_text(img, xy, text, font, fill, stroke=(10, 0, 0), stroke_w=6, drips=True, white_top=False, seed=3):
    """Words that bleed: dark outline, shadow, worn fill, and blood drips running down from the letters."""
    import numpy as np
    rnd = np.random.default_rng(seed)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=font, fill=255)
    m = np.array(mask)
    dr = Image.new("L", img.size, 0)
    if drips:
        ys, xs = np.nonzero(m > 128)
        if xs.size:
            d = ImageDraw.Draw(dr)
            cols = rnd.choice(np.unique(xs), size=min(16, np.unique(xs).size), replace=False)
            for cx in cols:
                bottom = int(ys[xs == cx].max())
                ln = int(rnd.integers(font.size // 8, font.size // 2 + 1))
                wdt = int(rnd.integers(max(3, font.size // 30), max(5, font.size // 14) + 1))
                d.rectangle([cx - wdt // 2, bottom - 4, cx + wdt // 2, bottom + ln], fill=255)
                d.ellipse([cx - wdt, bottom + ln - wdt, cx + wdt, bottom + ln + wdt], fill=255)
    full = Image.fromarray(np.maximum(m, np.array(dr)))
    outl = full.filter(ImageFilter.MaxFilter(stroke_w * 2 + 1)) if stroke_w else full
    base = img.convert("RGBA")
    sh = outl.filter(ImageFilter.GaussianBlur(9))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    layer.putalpha(sh.point(lambda v: int(v * 0.8)))
    base = Image.alpha_composite(base, layer.transform(img.size, Image.AFFINE, (1, 0, -5, 0, 1, -7)))
    st = Image.new("RGBA", img.size, stroke + (0,))
    st.putalpha(outl)
    base = Image.alpha_composite(base, st)
    W_, H_ = img.size
    bbox = full.getbbox() or (0, 0, W_, H_)
    if white_top:                                     # white letters that turn blood red towards the bottom
        t = np.clip((np.arange(H_) - bbox[1]) / max(1, bbox[3] - bbox[1]), 0, 1)[:, None, None]
        top_c, bot_c = np.array((250, 250, 250)), np.array(fill)
        grad = (top_c * (1 - t ** 1.1) + bot_c * t ** 1.1)[:, :, :] * np.ones((1, W_, 1))
        col = Image.fromarray(grad.astype("uint8"), "RGB").convert("RGBA")
    else:
        col = Image.new("RGBA", img.size, fill + (255,))
    # a light worn-paint texture (fine specks, never holes you can see from afar)
    noise = 1.0 - (rnd.random((H_, W_)) > 0.93).astype("float32") * 0.45
    noise = np.array(Image.fromarray((noise * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.6))).astype("float32")
    col.putalpha(Image.fromarray((np.array(full).astype("float32") * noise / 255).astype("uint8")))
    return Image.alpha_composite(base, col).convert("RGB")


def _fit_size(text, kind, fallback, max_w, start, low=30):
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    sz = start
    while sz > low:
        if probe.textlength(text, font=_poster_font(kind, sz, fallback)) <= max_w:
            return sz
        sz -= 4
    return low


def horror_poster(base_img, words, banner, out, fallback_font, portrait=False):
    """words: dict(top, main, mid, hook1, hook2) - the poster's word stack. banner: the bottom line."""
    from PIL import ImageEnhance
    W_, H_ = (1080, 1920) if portrait else (1280, 720)
    src = Image.open(base_img).convert("RGB")
    if portrait:                                      # the 16:9 picture, cut to its right / middle part
        s = H_ / src.height
        big = src.resize((int(src.width * s), H_))
        x = max(0, min(big.width - W_, int(big.width * 0.62) - W_ // 2))
        img = big.crop((x, 0, x + W_, H_))
    else:
        img = src.resize((W_, H_))
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.1)
    blue = Image.new("RGB", img.size, (10, 30, 70))   # the cold blue night of the reference
    img = Image.blend(img, blue, 0.18)
    shade = Image.new("L", img.size, 0)               # darkness where the words go
    d = ImageDraw.Draw(shade)
    if portrait:
        for i in range(120):
            d.rectangle([0, 0, W_, int(H_ * 0.52 * (1 - i / 120))], fill=int(170 * i / 120))
        d.rectangle([0, int(H_ * 0.86), W_, H_], fill=150)
    else:
        for i in range(120):
            d.rectangle([0, 0, int(W_ * 0.62 * (1 - i / 120)), H_], fill=int(185 * i / 120))
    shade = shade.filter(ImageFilter.GaussianBlur(35))
    img = Image.composite(Image.new("RGB", img.size, (4, 6, 14)), img, shade)

    col_w = int(W_ * (0.86 if portrait else 0.52))
    x0 = int(W_ * (0.07 if portrait else 0.035))
    scale = 1.75 if portrait else 1.0
    y = int(H_ * 0.03) + 14
    top, main, mid = str(words.get("top", "")).strip(), str(words.get("main", "")).strip(), str(words.get("mid", "")).strip()
    h1, h2 = str(words.get("hook1", "")).strip(), str(words.get("hook2", "")).strip()
    probe = ImageDraw.Draw(img)
    if top:                                           # 1) small white place word on a red brush stroke
        sz = _fit_size(top, "bold", fallback_font, col_w * 0.7, int(58 * scale))
        f = _poster_font("bold", sz, fallback_font)
        tw = probe.textlength(top, font=f)
        img = _brush_band(img, (x0 + 10, y + int(sz * 0.25), x0 + int(tw) + 50, y + int(sz * 1.25)), seed=11)
        img = _drip_text(img, (x0 + 30, y), top, f, (255, 255, 255), stroke_w=3, drips=False, seed=12)
        y += int(sz * 1.25)
    if main:                                          # 2) the huge worn yellow name
        sz = _fit_size(main, "brush", fallback_font, col_w, int(170 * scale))
        f = _poster_font("brush", sz, fallback_font)
        img = _drip_text(img, (x0, y - int(sz * 0.02)), main, f, (255, 214, 0), stroke_w=7, drips=False, seed=13)
        y += int(sz * 1.08)
    if mid:                                           # 3) white connecting words
        sz = _fit_size(mid, "bold", fallback_font, col_w * 0.9, int(62 * scale))
        f = _poster_font("bold", sz, fallback_font)
        img = _drip_text(img, (x0 + 30, y), mid, f, (255, 255, 255), stroke_w=4, drips=False, seed=14)
        y += int(sz * 1.2)
    for k, hw in enumerate((h1, h2)):                 # 4) the dripping blood words
        if not hw:
            continue
        sz = _fit_size(hw, "brush", fallback_font, col_w, int(130 * scale))
        f = _poster_font("brush", sz, fallback_font)
        img = _drip_text(img, (x0 + (0 if k == 0 else int(col_w * 0.12)), y - int(sz * 0.2)), hw, f,
                         (229, 16, 20), stroke_w=6, drips=True, white_top=(k == 1), seed=20 + k)
        y += int(sz * 0.92)
    if banner:                                        # 5) the bottom brush banner with yellow words
        sz = _fit_size(banner, "bold", fallback_font, (W_ * 0.8 if portrait else W_ * 0.5), int(60 * scale))
        f = _poster_font("bold", sz, fallback_font)
        tw = probe.textlength(banner, font=f)
        bx = (W_ - tw) // 2 if portrait else x0 + int(col_w * 0.08)
        by = H_ - int(sz * 1.6)
        img = _brush_band(img, (int(bx) - 30, by + int(sz * 0.12), int(bx + tw) + 30, by + int(sz * 1.25)), seed=31)
        img = _drip_text(img, (bx, by), banner, f, (255, 220, 0), stroke_w=4, drips=False, seed=32)
    img.save(out, quality=95)
    return out


# ===================== v55: YOUR thumbnail formulas (7 Nov 2026) =====================
# The picture is made from your prompt (subject, place, light, mood, composition). The Bengali title is NOT drawn
# by the picture model (it cannot spell Bengali) - the bot writes it itself with a real Bengali font, in your
# colours and effects, so it is always correctly spelled and readable on a phone.
USER_THUMB = {
    "h_cinematic": (
        "Ultra-realistic cinematic supernatural horror movie poster image, 16:9 landscape. {subject}: a highly "
        "detailed, frightening supernatural entity with terrifying facial details and realistic textures, visually "
        "dominant, on the RIGHT side of the frame. Behind it {place}: abandoned buildings, dark shadows, thick fog, "
        "eerie lighting and a dramatic, mysterious background. {moment} Strong contrast, dramatic cinematic lighting, "
        "extremely suspenseful atmosphere, professional Indian horror movie poster quality, designed to attract "
        "clicks on mobile screens. The LEFT 45% of the frame is darker and simpler - fog and shadow only, no face "
        "there (space for a big title). Frightening but not gory, no blood. No text, no letters, no words, no "
        "watermark, no logo."),
    "h_closeup": (
        "Visually shocking, high-impact horror movie poster image, 16:9 landscape. An intense close-up of {subject}: "
        "an extremely terrifying and mysterious supernatural face or haunted figure, on the RIGHT half of the frame, "
        "staring straight at the viewer. Deep black background, dark crimson red lighting, cold blue highlights, "
        "cinematic smoke, realistic textures and dramatic shadows - the viewer feels something horrifying is about "
        "to happen. {moment} Clean composition, not overcrowded. The LEFT 45% is deep black smoke only (space for a "
        "big title). Emotionally powerful, impossible to ignore, not gory, no blood. No text, no letters, no words, "
        "no watermark, no logo."),
    "h_real": (
        "Premium photorealistic paranormal mystery image, horror documentary poster aesthetic, 16:9 landscape. A "
        "believable haunted location: {place}, at night - cinematic night photography, realistic fog, moonlight, "
        "abandoned surroundings, mysterious silhouettes and an unsettling atmosphere. A mysterious ghostly presence "
        "({subject}) hidden somewhere in the scene - half-seen in a window, a doorway or between the trees - so the "
        "viewer immediately wonders what happened at this place. {moment} The place and the presence fill the "
        "MIDDLE and RIGHT; the LEFT 40% is darker sky and fog (space for a big title). Dramatic, professional, "
        "highly clickable, no gore. No text, no letters, no words, no watermark, no logo."),
    "c_3d": (
        "Stunning, colorful, high-quality 3D animated cartoon movie poster image, premium animated film quality, "
        "16:9 landscape. {subject}: expressive cartoon characters with beautiful facial expressions, exaggerated "
        "emotions and appealing poses, {moment}, in {place} - a magical, playful environment with vibrant colors, "
        "beautiful lighting and cinematic depth. The main characters are LARGE and expressive on the RIGHT side; "
        "the LEFT 45% is a simple, softly blurred bright background (space for a big title). Bright and attractive "
        "for children and family audiences. No horror, no ghosts, no scary elements, no text, no letters, no "
        "words, no watermark, no logo."),
    "c_funny": (
        "Extremely engaging, funny 3D animated comedy movie poster image, 16:9 landscape. A hilarious animated "
        "moment: {subject}, {moment}, in {place}. Funny cartoon characters with exaggerated facial expressions, big "
        "expressive eyes, humorous body language and entertaining poses, LARGE on the RIGHT side - the viewer is "
        "curious about the funny situation. Vibrant colorful background, bright lighting, rich 3D textures, "
        "professional animated comedy film look, energetic and entertaining. The LEFT 45% is a simple, bright, "
        "softly blurred background (space for a big title). No horror, no ghosts, no frightening visuals, no text, "
        "no letters, no words, no watermark, no logo."),
    "c_adventure": (
        "Premium cinematic 3D cartoon adventure movie poster image, big-budget animated film look, 16:9 landscape. "
        "Charming animated characters exploring an amazing world: {subject}, {moment}, in {place} - adventure, "
        "surprise, discovery or action. Beautiful vibrant colors, a magical environment, cinematic lighting, "
        "detailed 3D characters with expressive faces and a visually stunning background. The characters are LARGE "
        "on the RIGHT; the LEFT 45% is open, simpler sky or landscape (space for a big title). Instantly attractive "
        "to children and family audiences, no dark frightening atmosphere, no horror, no ghosts, no text, no "
        "letters, no words, no watermark, no logo."),
}
HORROR_THUMB_KIND = {"sotti": "h_real", "jayga": "h_real", "shohor": "h_closeup", "rohoshyo": "h_closeup",
                     "karna": "h_closeup"}             # every other kind: h_cinematic
CARTOON_THUMB_KIND = {**{c: "c_funny" for c in ("gopal", "birbal", "funny", "witty", "para", "school")},
                      **{c: "c_adventure" for c in ("adventure", "fairy", "detective", "betal", "folk", "lok")}}


CTR_HORROR = (" CLICK-WORTHY ON A PHONE: one single strong focal point (the ghost's face, a glowing lantern, an eerie "
              "silhouette in a lit doorway), uncluttered; bright rim light and high contrast with ONE vivid colour "
              "accent (crimson red, sickly green or cold blue glow) - never a muddy, all-dark picture.")
CTR_CARTOON = (" CLICK-WORTHY ON A PHONE: one single clear focal point (the main character's big expressive face), "
               "uncluttered, very bright and high contrast.")


def thumb_kind(bot, category, true_story=False):
    if env("THUMB_KIND") in USER_THUMB:
        return env("THUMB_KIND")
    if bot == "horror":
        return "h_real" if true_story else HORROR_THUMB_KIND.get(str(category or ""), "h_cinematic")
    return CARTOON_THUMB_KIND.get(str(category or ""), "c_3d")


def user_thumb_prompt(kind, subject, place, moment=""):
    """Your formula, filled with THIS story's subject, place and moment (picture only, no words)."""
    mo = str(moment or "").strip()
    if mo and kind.startswith("h_"):
        mo = f"The moment: {mo}."
    tmpl = USER_THUMB[kind]
    mm = re.search(r"(,\s*|\.?\s+)[Nn]o text, no letters", tmpl)
    if mm:                                            # the click-worthy clause goes just before 'No text ...'
        tmpl = (tmpl[:mm.start()] + "." + (CTR_HORROR if kind.startswith("h_") else CTR_CARTOON)
                + " No text, no letters" + tmpl[mm.end():])
    look = ""
    try:
        kk_ = "horror" if kind.startswith("h_") else "cartoon"
        st_ = (trend_style_get(kk_, env("LANGUAGE")) if env("LANGUAGE") else
               (trend_style_get(kk_, "bn") or trend_style_get(kk_, "hi")))
        if st_.get("thumb_style"):
            look = " This week's most clicked look (style only): " + st_["thumb_style"].replace("text", "lettering")[:400]
            look = re.sub(r"(?i)[^.]*\blettering\b[^.]*\.?", "", look)     # (the words are added by the bot)
    except Exception:
        look = ""
    try:                                              # v77: the growth monitor saw few clicks -> a stronger picture
        if (coach_load(os.path.join(_here_assets(), "coach.json")).get("rules") or {}).get("ctr_low"):
            look += (" Make it hit harder on a small phone screen: an extreme close-up of the most frightening face or "
                     "eyes, very high contrast, one bold glowing colour against deep black, nothing small or busy.")
    except Exception:
        pass
    tmpl = tmpl + look.replace("{", "(").replace("}", ")")
    return " ".join(tmpl.format(subject=str(subject or "the ghost").strip(),
                                            place=str(place or "a haunted old place").strip(),
                                            moment=mo or ("a fun, surprising moment" if kind.startswith("c_") else ""))
                    .split())[:1990]


TITLE_FONTS = {   # massive Bengali display fonts (Google Fonts, free): file, weight, width
    "horror": ("https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifbengali/NotoSerifBengali%5Bwdth,wght%5D.ttf",
               "title_horror.ttf", 900, 87.5),
    "real": ("https://raw.githubusercontent.com/google/fonts/main/ofl/anekbangla/AnekBangla%5Bwdth,wght%5D.ttf",
             "title_real.ttf", 800, 100),
    "cartoon": ("https://raw.githubusercontent.com/google/fonts/main/ofl/balooda2/BalooDa2%5Bwght%5D.ttf",
                "title_cartoon.ttf", 800, None),
}


def _title_font(style, size, fallback):
    url, name, wght, wdth = TITLE_FONTS[style]
    path = os.path.join(os.path.expanduser("~"), ".cache", "bot_fonts", name)    # kept for the whole run
    try:
        if not os.path.exists(path) and env("MOCK") != "1":
            os.makedirs(os.path.dirname(path), exist_ok=True)
            r = requests.get(url, timeout=60)
            if r.ok and len(r.content) > 100000:
                open(path, "wb").write(r.content)
        if os.path.exists(path):
            f = _font(path, size)
            try:                                      # variable font: the heaviest weight
                axes = f.get_variation_axes()
                vals = []
                for ax in axes:
                    nm = str(ax.get("name", b"")).lower()
                    if "weight" in nm or "wght" in nm:
                        vals.append(max(ax["minimum"], min(ax["maximum"], wght)))
                    elif ("width" in nm or "wdth" in nm) and wdth:
                        vals.append(max(ax["minimum"], min(ax["maximum"], wdth)))
                    else:
                        vals.append(ax.get("default", ax["minimum"]))
                if vals:
                    f.set_variation_by_axes(vals)
            except Exception:
                pass
            return f, path
    except Exception as e:
        log(f"  title font: {str(e)[:80]}")
    return _font(fallback, size), fallback


def _title_lines(text, n):
    w = text.split()
    if n <= 1 or len(w) <= 1:
        return [text]
    best, bs = [text], 1e9
    import itertools
    for cuts in itertools.combinations(range(1, len(w)), min(n, len(w)) - 1):
        parts = [" ".join(w[a:b]) for a, b in zip((0,) + cuts, cuts + (len(w),))]
        s = max(len(x) for x in parts)
        if s < bs:
            best, bs = parts, s
    return best


def _fx_line(img, xy, text, font, top, bottom, stroke, sw, depth, ext, glow, glow_r):
    """One title line: soft glow, 3D depth, thick outline and a top-to-bottom colour gradient."""
    x, y = xy
    W_, H_ = img.size
    mask = Image.new("L", (W_, H_), 0)
    ImageDraw.Draw(mask).text((x, y), text, font=font, fill=255)
    out = img.convert("RGBA")
    if glow:
        gm = Image.new("L", (W_, H_), 0)
        ImageDraw.Draw(gm).text((x, y), text, font=font, fill=255, stroke_width=sw + glow_r // 3, stroke_fill=255)
        gm = gm.filter(ImageFilter.GaussianBlur(glow_r))
        out = Image.composite(Image.new("RGBA", (W_, H_), glow + (255,)), out, gm.point(lambda v: int(v * 0.85)))
    d = ImageDraw.Draw(out)
    for i in range(depth, 0, -1):                     # the 3D depth: darker copies, down and to the right
        d.text((x + i * 0.6, y + i), text, font=font, fill=ext + (255,), stroke_width=sw, stroke_fill=ext + (255,))
    d.text((x, y), text, font=font, fill=stroke + (255,), stroke_width=sw, stroke_fill=stroke + (255,))
    bb = mask.getbbox() or (0, 0, W_, H_)
    grad = Image.new("RGBA", (W_, H_), top + (255,))
    gd = ImageDraw.Draw(grad)
    for yy in range(bb[1], bb[3] + 1):
        t = (yy - bb[1]) / max(1, bb[3] - bb[1])
        gd.line([(0, yy), (W_, yy)], fill=tuple(int(top[k] + (bottom[k] - top[k]) * t) for k in range(3)) + (255,))
    out = Image.composite(grad, out, mask)
    return out.convert("RGB")


def title_poster(base_img, title, out, kind, small="", portrait=False, fallback_font=None):
    """Your thumbnail: the picture + ONLY the Bengali title, huge, on the side away from the ghost / characters
    (blood-red and glowing white for horror, yellow-white or blood-red for a real incident, bright colourful 3D
    letters with a thick white outline for cartoons). small = an optional little line (part number / true story)."""
    from PIL import ImageEnhance
    W_, H_ = (1080, 1920) if portrait else (1280, 720)
    src = Image.open(base_img).convert("RGB")
    if portrait:
        s = H_ / src.height
        big = src.resize((int(src.width * s), H_))
        x = max(0, min(big.width - W_, int(big.width * 0.62) - W_ // 2))
        img = big.crop((x, 0, x + W_, H_))
    else:
        img = src.resize((W_, H_))
    horror = kind.startswith("h_")
    # BRIGHT AND CLEAR (YouTube's advice, 8 Nov 2026: 'horror thumbnails fail when they are too dark'): a dark
    # picture is lifted, then more contrast, colour and sharpness - the picture must read on a small phone
    from PIL import ImageStat
    lum = ImageStat.Stat(img.convert("L")).mean[0]
    if lum < 100:
        import math
        g = max(0.55, min(1.0, math.log(108 / 255) / math.log(max(lum, 8) / 255)))
        img = img.point(lambda v: int(255 * ((v / 255) ** g)))
    img = ImageEnhance.Contrast(img).enhance(1.2 if horror else 1.08)
    img = ImageEnhance.Color(img).enhance(1.22 if horror else 1.15)
    img = ImageEnhance.Sharpness(img).enhance(1.4)
    if horror:                                        # a soft shadow only right behind the words
        shade = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(shade)
        if portrait:
            for i in range(100):
                d.rectangle([0, 0, W_, int(H_ * 0.46 * (1 - i / 100))], fill=int(140 * i / 100))
        else:
            for i in range(100):
                d.rectangle([0, 0, int(W_ * 0.54 * (1 - i / 100)), H_], fill=int(140 * i / 100))
        shade = shade.filter(ImageFilter.GaussianBlur(40))
        img = Image.composite(Image.new("RGB", img.size, (3, 3, 8)), img, shade)
    style = "real" if kind == "h_real" else ("horror" if horror else "cartoon")
    hindi = bool(re.search(r"[\u0900-\u097F]", str(title))) and fallback_font

    def tf(sz):                                       # Hindi titles: the Hindi font (the display fonts are Bengali)
        return (_font(fallback_font, sz), fallback_font) if hindi else _title_font(style, sz, fallback_font)
    probe_font, fpath = tf(100)
    raw = re.sub(r"#\s*[0-9০-৯]*", " ", re.sub(r"\s*\|.*$", "", str(title))).strip()
    text = re.sub(r"\s{2,}", " ", fit_glyphs(raw, fpath)).strip()
    letters = lambda s: len(re.sub(r"[\W_]", "", s))
    if letters(text) < 0.7 * letters(no_tofu(raw)):      # this font cannot write this title - never draw boxes
        raise RuntimeError("the title font cannot write this title")
    col_w = int(W_ * (0.9 if portrait else 0.5))
    max_h = int(H_ * (0.42 if portrait else 0.74))
    probe = ImageDraw.Draw(img)
    best = None
    def block_h(lines, f, size):                      # real height, with the signs above and below the letters
        sw_, dp_ = max(4, size // (9 if style == "cartoon" else 12)), max(3, size // (13 if style == "cartoon" else 16))
        return sum(f.getbbox(l)[3] - f.getbbox(l)[1] + 2 * sw_ + dp_ for l in lines) + int(size * 0.06) * (len(lines) - 1)
    for n in (1, 2, 3):
        lines = _title_lines(text, n)
        size = int(300 if portrait else 230)
        while size >= 40:
            f, _p = tf(size)
            widths = [probe.textlength(l, font=f) for l in lines]
            if max(widths) <= col_w and block_h(lines, f, size) + (int(size * 0.5) if small else 0) <= max_h:
                break
            size -= 6
        if not best or size > best[1] * 1.08:         # fewer lines unless more lines make the letters clearly bigger
            best = (lines, size)
    lines, size = best
    f, _p = tf(size)
    sw = max(4, size // (9 if style == "cartoon" else 12))
    depth = max(3, size // (13 if style == "cartoon" else 16))
    if horror:
        # high contrast on a phone: glowing white letters with a blood-red outline, and blood-red letters with a
        # white outline (red on black alone was hard to read)
        looks = ([((255, 255, 255), (232, 232, 226), (175, 0, 0), (45, 0, 0), (255, 30, 30)),   # glowing white
                  ((255, 46, 46), (175, 0, 0), (255, 255, 255), (60, 0, 0), (0, 0, 0))]       # blood red
                 if style == "horror" else
                 [((255, 246, 140), (255, 205, 0), (0, 0, 0), (60, 30, 0), (255, 40, 40)),      # bright yellow
                  ((255, 46, 46), (175, 0, 0), (255, 255, 255), (60, 0, 0), (0, 0, 0))])        # blood red
    else:
        looks = [((255, 235, 60), (255, 140, 0), (255, 255, 255), (120, 40, 0), (0, 0, 0)),
                 ((255, 110, 190), (215, 25, 120), (255, 255, 255), (100, 0, 60), (0, 0, 0)),
                 ((90, 220, 255), (0, 120, 235), (255, 255, 255), (0, 40, 110), (0, 0, 0)),
                 ((150, 240, 80), (40, 170, 40), (255, 255, 255), (0, 70, 0), (0, 0, 0))]
    total = block_h(lines, f, size) + (int(size * 0.5) if small else 0)
    top_y = int(H_ * 0.06) if portrait else max(int(H_ * 0.05), (H_ - total) // 2)
    x0 = int(W_ * (0.05 if portrait else 0.04))
    y = top_y
    for k, ln in enumerate(lines):
        top, bot, stroke, ext, glow = looks[k % len(looks)]
        tw = probe.textlength(ln, font=f)
        bb = f.getbbox(ln)
        x = (W_ - tw) / 2 if portrait else x0 + max(0, (col_w - tw) / 2)
        ty = y - bb[1] + sw                           # the line's highest sign starts exactly at y
        img = _fx_line(img, (x, ty), ln, f, top, bot, stroke, sw, depth, ext, glow,
                       max(8, size // 7) if horror else max(6, size // 10))
        y = ty + bb[3] + sw + depth + int(size * 0.06)  # below its lowest sign (e.g. the ra-phala of ট্র)
    if small:                                         # the little line under the title
        sf, _p2 = tf(max(28, int(size * 0.34)))
        st = fit_glyphs(small, _p2)
        tw = probe.textlength(st, font=sf)
        x = (W_ - tw) / 2 if portrait else x0 + max(0, (col_w - tw) / 2)
        pad = int(sf.size * 0.35)
        dd = ImageDraw.Draw(img)
        sb = sf.getbbox(st)
        y += pad // 2
        dd.rounded_rectangle([x - pad, y, x + tw + pad, y + (sb[3] - sb[1]) + 2 * pad], radius=pad,
                             fill=(160, 0, 0) if horror else (255, 255, 255))
        dd.text((x, y + pad - sb[1]), st, font=sf, fill=(255, 255, 255) if horror else (200, 20, 90))
    img.save(out, quality=95)
    return out


def thumb_words(story, title):
    """2-4 big words for the thumbnail that ADD to the title (YouTube: 'thumbnail text should complement - not
    repeat - the title'): the story's own thumbnail_text, else the first words of the title."""
    from difflib import SequenceMatcher
    t = re.sub(r"\s*\|.*$", "", str(title)).strip()
    w = re.sub(r"\s{2,}", " ", no_tofu(str(story.get("thumbnail_text") or ""))).strip(" -|")
    k = lambda s: re.sub(r"[^\wঀ-৿ऀ-ॿ]", "", s)
    if 1 <= len(w.split()) <= 5 and len(w) <= 34 and SequenceMatcher(None, k(w), k(t)).ratio() < 0.6:
        return w
    return t.split(":", 1)[1].strip() if ":" in t else t      # (no good words: the story's own title)


SEARCH_WORDS = {   # what people really type in YouTube search (first lines of every description)
    "horror": {"bn": ["ভূতের গল্প", "ভৌতিক গল্প", "Bengali Horror Audio Story", "রহস্য রোমাঞ্চ", "Bhuter Golpo"],
               "hi": ["भूतिया कहानी", "डरावनी कहानी", "Hindi Horror Story", "Bhoot Ki Kahani"]},
    "cartoon": {"bn": ["বাংলা কার্টুন", "রূপকথার গল্প", "Bangla Cartoon Golpo", "বাচ্চাদের গল্প", "নীতিকথার গল্প"],
                "hi": ["हिंदी कार्टून", "बच्चों की कहानी", "Hindi Cartoon Story", "Moral Stories Hindi"]},
}


def search_head(kind, lang, synopsis, seo=()):
    """The first 2-3 lines of a YouTube description: a short summary, then the search words."""
    s = re.split(r"(?<=[।.!?])\s+", str(synopsis or "").strip())
    head = " ".join(s[:3]).strip()[:320]
    words = []
    for w in list(SEARCH_WORDS.get(kind, {}).get(lang, [])) + [str(x) for x in seo or []]:
        if w and w.lower() not in [x.lower() for x in words]:
            words.append(w)
    return (head + "\n" if head else "") + "🔎 " + " · ".join(words[:8])


LOCALIZE = {}


def yt_localizations(title, description, lang, key):
    """The same video's title and a short summary in English and Hindi (or Bengali) for YouTube: people who
    search in those languages see it in their own language - the video itself stays the same."""
    if env("YT_LOCALIZE") == "0" or env("MOCK") == "1" or not key:
        return {}
    base = re.sub(r"\s*#Shorts\s*$", "", str(title)).strip()
    ck = re.sub(r"\s*\|.*$", "", base).strip()            # the story's title: the video and its Shorts share it
    if ck in LOCALIZE:
        return LOCALIZE[ck]
    names = {"en": "English", "hi": "Hindi", "bn": "Bengali"}
    targets = [x for x in ("en", "hi", "bn") if x != lang][:2]
    summary = re.split(r"\n\s*\n", str(description).strip())
    summary = next((p for p in summary if len(p) > 40 and not p.startswith(("🔎", "http", "#"))), summary[0] if summary else "")
    prompt = (f"A {names.get(lang, lang)} horror/story video on YouTube. Translate its title and summary for viewers "
              f"who speak {' and '.join(names[x] for x in targets)}: natural, gripping, easy to find in search, keep "
              "the emojis, no quotes, title at most 90 characters, summary at most 3 sentences.\n"
              f"TITLE: {base}\nSUMMARY: {summary[:700]}\n"
              "Answer ONLY JSON: {" + ", ".join(f'"{x}": {{"title": "", "summary": ""}}' for x in targets) + "}")
    out = {}
    for model in helper_models(key)[:4]:
        try:
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}},
                              timeout=90)
            if not r.ok:
                continue
            js = load_json_loose(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            for x in targets:
                v = js.get(x) or {}
                t = re.sub(r"[<>]", "", str(v.get("title") or "")).strip()[:100]
                sm = re.sub(r"[<>]", "", str(v.get("summary") or "")).strip()
                if t:
                    out[x] = {"title": t, "description": ((sm + "\n\n") if sm else "") + str(description)[:4500]}
            if out:
                break
        except Exception:
            continue
    LOCALIZE[ck] = out
    if out:
        log(f"  YouTube title also in {', '.join(out)}: " + " | ".join(v['title'][:40] for v in out.values()))
    return out


def shorts_localizations(loc, description):
    """The same translations for the story's Short (title + #Shorts)."""
    return {x: {"title": (v["title"][:88] + " #Shorts"), "description": str(description)[:4800]}
            for x, v in (loc or {}).items()}


def poster_words(title, place, ghost, lang, key=None, models=None):
    """The poster's word stack for THIS story, e.g. {'top': 'দুর্গাপুরের', 'main': 'চিত্রালয়', 'mid': 'সিনেমা হলের',
    'hook1': 'অভিশপ্ত', 'hook2': 'ছায়ামূর্তি'} - asked from Gemini, else cut from the title."""
    import re as _re
    t0 = _re.sub(r"\s*\|.*$", "", str(title))
    t0 = t0.split(":", 1)[1] if ":" in t0 else t0          # 'ভৈরব ঠাকুরের কেস #2: ...' -> only the story's own name
    clean = _re.sub(r"[^\w\s\u0980-\u09FF\u0900-\u097F'-]", " ", t0).strip()
    if key and models and env("MOCK") != "1":
        prompt = (f"A {'Bengali' if lang == 'bn' else 'Hindi'} horror video is called: {clean}. Place: {place}. "
                  f"Ghost: {ghost}. Write the words of its YouTube poster, in {'Bengali' if lang == 'bn' else 'Hindi'} "
                  "only, like this example: {\"top\": \"দুর্গাপুরের\", \"main\": \"চিত্রালয়\", \"mid\": \"সিনেমা হলের\", "
                  "\"hook1\": \"অভিশপ্ত\", \"hook2\": \"ছায়ামূর্তি\"} - top = 1 word (the town / village, ending "
                  "in -er), main = 1 word (the haunted place's own name or the key thing), mid = 2 words (what kind of "
                  "place), hook1 + hook2 = one word each (a frightening adjective + the ghost). Answer ONLY that JSON.")
        for mdl in models[:4]:
            try:
                r = requests.post(f"{GEMINI_BASE}/models/{mdl}:generateContent", headers={"x-goog-api-key": key},
                                  json={"contents": [{"parts": [{"text": prompt}]}],
                                        "generationConfig": {"temperature": 0.6, "responseMimeType": "application/json"}},
                                  timeout=90)
                if r.ok:
                    w = load_json_loose(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                    if isinstance(w, dict) and w.get("main") and w.get("hook2"):
                        return {k: str(w.get(k, ""))[:22] for k in ("top", "main", "mid", "hook1", "hook2")}
            except Exception:
                continue
    ws = clean.split()                                # no answer: the title itself, cut into the stack
    if len(ws) <= 2:
        return {"main": ws[0] if ws else clean, "hook2": ws[1] if len(ws) > 1 else ""}
    n = len(ws)
    if ws[0].endswith(("ের", "র")) and n >= 4:       # 'দুর্গাপুরের চিত্রালয় ... অভিশপ্ত ছায়ামূর্তি'
        return {"top": ws[0], "main": ws[1], "mid": " ".join(ws[2:n - 2]), "hook1": ws[-2], "hook2": ws[-1]}
    head = ws[:n - 2]                                 # the last two words drip, the rest is the big name
    return {"top": "", "main": " ".join(head[:2]), "mid": " ".join(head[2:]), "hook1": ws[-2], "hook2": ws[-1]}


THUMB_PROMPT = {
    "cartoon": ("Use case: thumbnail-art. Cinematic 16:9 YouTube episode thumbnail for an original {series} cartoon "
                "episode. A polished, dramatic yet playful hand-painted 2D cartoon scene in {place}. {hero} is the "
                "clear foreground hero on the RIGHT side of the frame, {hero_action}, large expressive face. {second}, placed in the middle or right, never at the left edge. "
                "Visual story: {moment}. Rich authentic Bengali details, cinematic lighting and depth, warm lamps, "
                "deep reds, gold and teal, lively expressions without caricature. Strong simple composition, faces "
                "large and readable at small thumbnail size, clean dark negative space at the upper-left for a title, no faces in the upper-left third. "
                "No text, no letters, no watermark, no logo, no modern objects, no extra foreground characters, no "
                "distorted faces, no malformed hands."),
    "horror_poster": ("Cinematic 16:9 horror movie poster art, photorealistic, deep cold-blue night with a full moon and "
                      "thick fog. In the MIDDLE and RIGHT: {place}, clearly visible, old, stained and haunted, a few "
                      "warm lights. On the RIGHT side, large in the foreground, {second} - a terrifying pale ghost with "
                      "long tangled black hair and glowing white eyes looking straight at the viewer. Above, in the dark "
                      "sky at the top centre, a GIANT faint ghostly face with pale glowing eyes looming over the place. "
                      "Bare twisted branches at the edges. The whole LEFT HALF is darker and empty (space for big "
                      "title words). High contrast, rich detail, eerie but not gory. No text, no letters, no watermark, "
                      "no logo."),
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
    if style == "horror" and env("POSTER_STYLE") != "old":
        return " ".join(THUMB_PROMPT["horror_poster"].format(place=pl, second=sec_desc or "the ghost").split())
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
    note = [p for p in rest if p.startswith("🔁")][:1] + note      # "share + follow" always stays
    rest = [p for p in rest if p not in note]
    out = [head[:150]]
    tags = tags[:5]                     # Facebook: fewer than 6 hashtags = better quality signal
    tag_room = min(75, len(" ".join(tags)) + 2) if tags else 0          # keep space for the 5 hashtags
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


# ----------------------------------------------------------------- talking with the fans
def reply_fans(history, lang, max_n=5):
    """Each run: answer the first few NEW comments under our recent videos - warm, short, personal replies (like
    a real creator), so people feel heard and come back. Never more than max_n replies per run."""
    token, page_id, key = env("FB_PAGE_TOKEN"), env("FB_PAGE_ID"), env("GEMINI_API_KEY")
    if not (token and key) or env("REPLY_FANS") == "0":
        return False
    now = dt.datetime.now(dt.timezone.utc)
    todo = []
    for h in reversed(history[-6:]):
        if not h.get("facebook") or not h.get("date"):
            continue
        try:
            age = (now - dt.datetime.fromisoformat(h["date"])).total_seconds() / 3600
        except Exception:
            continue
        if not 1 <= age <= 48:
            continue
        try:
            r = requests.get(f"{GRAPH}/{h['facebook']}/comments", timeout=30, params={
                "fields": "id,message,from{id,name},comment_count", "limit": 50, "order": "chronological",
                "access_token": token}).json()
        except Exception:
            continue
        done = set(h.get("replied") or [])
        for c in r.get("data", []):
            frm = c.get("from") or {}
            msg = str(c.get("message", "")).strip()
            if (c.get("id") in done or frm.get("id") == page_id or c.get("comment_count") or len(msg) < 2
                    or len(todo) >= max_n):
                continue
            todo.append((h, c["id"], first_name(frm.get("name")), msg[:300], str(h.get("title", ""))[:80]))
    if not todo:
        return False
    lang = todo[0][0].get("lang") or lang            # the language of the video they commented on
    lang_name = "Bengali (pure Kolkata cholit bhasha)" if lang == "bn" else "Hindi"
    ask = ("You run a popular story page. Write a short, warm, natural reply (max 18 words, 0-1 emoji) to each "
           f"viewer comment in {lang_name}, like a real friendly creator: thank them by first name, answer their "
           "question if they asked one (never spoil a twist), invite them to the next story. No links, no hashtags. "
           "Return ONLY a JSON list of strings in the same order.\n" +
           "\n".join(f"{k + 1}. [{t}] {n}: {m}" for k, (h, cid, n, m, t) in enumerate(todo)))
    try:
        replies = None
        for model in helper_models(key)[:3]:
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                              json={"contents": [{"parts": [{"text": ask}]}],
                                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8}},
                              timeout=90)
            if r.ok:
                replies = load_json_loose(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                break
        if replies is None:
            raise RuntimeError("no model answered")
    except Exception as e:
        log("  fan replies skipped:", str(e)[:120])
        return False
    n = 0
    for (h, cid, name, msg, t), text in zip(todo, replies if isinstance(replies, list) else []):
        text = str(text).strip()
        if not text:
            continue
        try:
            rr = requests.post(f"{GRAPH}/{cid}/comments", data={"message": text, "access_token": token},
                               timeout=30).json()
            if rr.get("id"):
                n += 1
        except Exception:
            pass
        h.setdefault("replied", []).append(cid)
    log(f"  replied to {n} viewer comments")
    return True


# ----------------------------------------------------------------- series that continue on their category's day
def series_all(path):
    """{category: state} of the unfinished stories. Older files (one series, no category) are read too."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, dict) and data.get("created"):                   # old format: a single series
        return {str(data.get("category") or data.get("special") or "default"): data}
    return {k: v for k, v in (data or {}).items() if isinstance(v, dict) and v.get("created")}


def series_get(path, key, ready_only=True, max_days=21):
    """the unfinished story of this category - only if it was NOT started today (the next part comes on the
    category's next day) and is not too old"""
    st = series_all(path).get(str(key))
    if not st:
        return None
    try:
        made = dt.datetime.fromisoformat(st.get("updated") or st["created"])
        if (dt.datetime.now(dt.timezone.utc) - made).days > max_days:
            return None
        if ready_only and made.astimezone(IST).date() >= dt.datetime.now(IST).date():
            return None
    except Exception:
        return None
    return st


def series_put(path, key, state):
    data = series_all(path)
    if state is None:
        data.pop(str(key), None)
    else:
        state["updated"] = dt.datetime.now(dt.timezone.utc).isoformat()
        data[str(key)] = state
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


# ----------------------------------------------------------------- what people are watching this week
# ----------------------------------------------------------------- what is REALLY trending on YouTube (v75)
TREND_QUERIES = {
    ("horror", "bn"): ["ভূতের গল্প", "bhuter golpo", "ভৌতিক গল্প", "bhuter golpo sotti ghotona", "horror story bangla",
                       "তান্ত্রিকের গল্প", "গ্রামের ভূতের গল্প"],
    ("horror", "hi"): ["bhoot ki kahani", "भूत की कहानी", "horror story hindi", "sacchi bhutiya kahani",
                       "tantrik ki kahani", "gaon ki bhutiya kahani"],
    ("cartoon", "bn"): ["বাংলা কার্টুন গল্প", "bangla cartoon golpo", "thakurmar jhuli golpo", "gopal bhar cartoon",
                        "rupkothar golpo", "bangla moral story cartoon"],
    ("cartoon", "hi"): ["hindi kahaniya cartoon", "moral stories hindi", "panchatantra ki kahaniyan",
                        "jadui kahani", "hindi cartoon story", "pari ki kahani"],
}
# (13 Nov 2026) EVERY story's own category is searched on YouTube - what is most watched THIS WEEK in exactly that kind
CAT_QUERIES = {
    ("horror", "gram"): {"bn": ["গ্রামের ভূতের গল্প", "gramer bhuter golpo", "গ্রাম বাংলার ভৌতিক গল্প", "bhuter golpo gram"],
                         "hi": ["gaon ki bhutiya kahani", "गाँव की भूतिया कहानी", "village horror story hindi"]},
    ("horror", "shohor"): {"bn": ["শহরের ভূতের গল্প", "kolkata bhuter golpo", "ফ্ল্যাটের ভূতের গল্প", "hostel bhuter golpo"],
                           "hi": ["shahar ki bhutiya kahani", "flat horror story hindi", "hostel horror story hindi"]},
    ("horror", "jayga"): {"bn": ["ভূতুড়ে জায়গার গল্প", "haunted place bengali story", "পোড়ো বাড়ির ভূতের গল্প", "রাজবাড়ির ভূতের গল্প"],
                          "hi": ["haunted place story hindi", "bhutiya haveli ki kahani", "भूतिया जगह की कहानी"]},
    ("horror", "sotti"): {"bn": ["সত্যি ভূতের ঘটনা", "sotti bhuter ghotona", "real horror story bangla", "সত্য ঘটনা অবলম্বনে ভূতের গল্প"],
                          "hi": ["sacchi bhutiya ghatna", "real horror story hindi", "सच्ची भूतिया घटना"]},
    ("horror", "rohoshyo"): {"bn": ["রহস্য ভৌতিক গল্প", "tantrik goenda golpo", "অলৌকিক রহস্য গল্প", "bhuter goenda golpo"],
                             "hi": ["rahasya horror story hindi", "tantrik jasoos kahani", "रहस्यमयी भूतिया कहानी"]},
    ("horror", "karna"): {"bn": ["পিশাচের গল্প", "পিশাচিনীর গল্প", "pishach golpo", "তন্ত্র মন্ত্র ভৌতিক গল্প"],
                          "hi": ["pishachini ki kahani", "पिशाच की कहानी", "tantra mantra horror story"]},
    ("horror", "tantrik"): {"bn": ["তান্ত্রিকের গল্প", "tantrik golpo", "শ্মশানের তান্ত্রিক গল্প", "তন্ত্র সাধনার গল্প"],
                            "hi": ["tantrik ki kahani", "तांत्रिक की कहानी", "shamshan tantrik story"]},
    ("cartoon", "gopal"): {"bn": ["গোপাল ভাঁড়ের গল্প", "gopal bhar cartoon"], "hi": ["gopal bhar cartoon hindi"]},
    ("cartoon", "birbal"): {"bn": ["আকবর বীরবলের গল্প", "akbar birbal bangla"], "hi": ["akbar birbal ki kahani", "अकबर बीरबल"]},
    ("cartoon", "betal"): {"bn": ["বিক্রম বেতালের গল্প", "vikram betal bangla"], "hi": ["vikram betal ki kahani", "विक्रम बेताल"]},
    ("cartoon", "panchatantra"): {"bn": ["পঞ্চতন্ত্রের গল্প", "panchatantra bangla cartoon"], "hi": ["panchatantra ki kahaniyan", "पंचतंत्र की कहानियाँ"]},
    ("cartoon", "jataka"): {"bn": ["জাতকের গল্প", "jataka golpo"], "hi": ["jataka kathayen", "जातक कथाएँ"]},
    ("cartoon", "fairy"): {"bn": ["রূপকথার গল্প", "rupkothar golpo cartoon", "ঠাকুরমার ঝুলি"], "hi": ["pari ki kahani", "परी की कहानी", "jadui kahani"]},
    ("cartoon", "moral"): {"bn": ["নীতি কথার গল্প", "bangla moral story cartoon"], "hi": ["moral stories hindi", "शिक्षाप्रद कहानियाँ"]},
    ("cartoon", "animal"): {"bn": ["পশু পাখির গল্প কার্টুন", "bangla animal cartoon golpo"], "hi": ["janwaron ki kahani", "जानवरों की कहानी"]},
    ("cartoon", "nature"): {"bn": ["প্রকৃতির গল্প কার্টুন", "bangla cartoon golpo"], "hi": ["prakriti ki kahani cartoon", "hindi cartoon story"]},
    ("cartoon", "folk"): {"bn": ["লোককথা বাংলা কার্টুন", "bangla lok kotha"], "hi": ["lok katha hindi", "लोक कथा"]},
    ("cartoon", "lok"): {"bn": ["লোককথা বাংলা কার্টুন"], "hi": ["lok katha hindi"]},
    ("cartoon", "detective"): {"bn": ["গোয়েন্দা গল্প কার্টুন", "bangla detective cartoon"], "hi": ["jasoos kahani cartoon", "जासूसी कहानी"]},
    ("cartoon", "adventure"): {"bn": ["অভিযানের গল্প কার্টুন", "bangla adventure cartoon"], "hi": ["adventure kahani cartoon", "साहसिक कहानी"]},
    ("cartoon", "para"): {"bn": ["পাড়ার গল্প কার্টুন", "bangla cartoon golpo"], "hi": ["mohalla kahani cartoon", "hindi cartoon story"]},
    ("cartoon", "funny"): {"bn": ["মজার কার্টুন গল্প", "bangla funny cartoon"], "hi": ["funny cartoon hindi kahani", "मज़ेदार कहानी"]},
    ("cartoon", "witty"): {"bn": ["বুদ্ধির গল্প কার্টুন", "buddhir golpo"], "hi": ["buddhi ki kahani", "चतुराई की कहानी"]},
    ("cartoon", "bedtime"): {"bn": ["ঘুমপাড়ানি গল্প", "bedtime story bangla"], "hi": ["sone ki kahani", "bedtime story hindi"]},
    ("cartoon", "school"): {"bn": ["স্কুলের গল্প কার্টুন", "school cartoon bangla"], "hi": ["school ki kahani cartoon"]},
    ("cartoon", "life"): {"bn": ["জীবনের গল্প কার্টুন", "bangla jiboner golpo"], "hi": ["zindagi ki kahani cartoon", "emotional kahani hindi"]},
    ("cartoon", "rhyme"): {"bn": ["বাংলা ছড়া কার্টুন", "bangla chora"], "hi": ["hindi rhymes cartoon", "बाल गीत"]},
}


def cat_queries(kind, lang, cat):
    q = (CAT_QUERIES.get((kind, cat)) or {}).get(lang) or []
    return q or TREND_QUERIES.get((kind, lang), [])


# other people's published stories / shows: we take only the TOPIC of a trend, never these stories
TREND_SKIP = re.compile(r"(?i)sunday\s*suspense|mirchi|goppo\s*mirchi|সানডে\s*সাসপেন্স|মির্চি|golpo\s*kotha|"
                        r"scary\s*mamma|bhoot\.?com|aahat|ssshhh|#?shorts?\b.*?\bmovie|full\s*movie|song|গান")


def _views_num(s):
    """'1.2M views' / '12,345 views' / '3.4K' -> number"""
    m = re.search(r"([\d.,]+)\s*([KkMmBb]|lakh|crore)?", str(s or ""))
    if not m:
        return 0
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return 0
    mul = {"k": 1e3, "m": 1e6, "b": 1e9, "lakh": 1e5, "crore": 1e7}.get((m.group(2) or "").lower(), 1)
    return int(n * mul)


def parse_yt_results(html):
    """Titles, views and age of the videos on a YouTube search page (its ytInitialData). [] if the page changed."""
    out = []
    i = html.find("ytInitialData")
    if i < 0:
        return out
    j = html.find("{", i)
    k = html.find("};", j)
    try:
        data = json.loads(html[j:k + 1])
    except Exception:
        return out

    def walk(x):
        if isinstance(x, dict):
            vr = x.get("videoRenderer")
            if isinstance(vr, dict):
                yield vr
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v)
    for vr in walk(data):
        try:
            title = "".join(r.get("text", "") for r in vr["title"]["runs"])
        except Exception:
            title = str((vr.get("title") or {}).get("simpleText", ""))
        vc = vr.get("viewCountText") or {}
        views = _views_num(vc.get("simpleText") or "".join(r.get("text", "") for r in vc.get("runs") or []))
        age = str((vr.get("publishedTimeText") or {}).get("simpleText", ""))
        if title and vr.get("videoId"):
            out.append({"id": vr["videoId"], "title": title.strip()[:150], "views": views, "age": age})
    return out


def yt_trending(kind, lang, max_n=15, queries=None):
    """The most watched videos of THIS WEEK on YouTube for our kind of video (YouTube's own search, sorted by
    views, uploaded this week) - real titles and real view counts, no API quota used. [] if YouTube says no."""
    seen, out = set(), []
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.8"}
    for q in (queries or TREND_QUERIES.get((kind, lang), []))[:6]:
        try:
            r = requests.get("https://www.youtube.com/results", headers=hdr, cookies={"CONSENT": "YES+1"}, timeout=25,
                             params={"search_query": q, "sp": "CAMSAggD", "hl": "en", "gl": "IN"})  # this week, by views
            rows = parse_yt_results(r.text) if r.ok else []
        except Exception as e:
            log(f"  YouTube trend search '{q}' failed: {str(e)[:80]}")
            rows = []
        for v in rows:
            if v["id"] in seen or TREND_SKIP.search(v["title"]):
                continue
            seen.add(v["id"])
            out.append(v)
        time.sleep(1.5)
    out.sort(key=lambda v: -v["views"])
    if out:
        log(f"  YouTube this week ({kind}): " + " | ".join(f"{v['title'][:50]} ({v['views']:,})" for v in out[:4]))
    return out[:max_n]


TREND_STYLE = {}          # kind_lang -> the week's style (titles, thumbnails, tags) of the most watched videos


def yt_video_meta(vid):
    """The public facts of one YouTube video page: its tags (keywords) and the hashtags in its description."""
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.8"}
    r = requests.get("https://www.youtube.com/watch", params={"v": vid, "hl": "en", "gl": "IN"}, headers=hdr,
                     cookies={"CONSENT": "YES+1"}, timeout=25)
    html = r.text if r.ok else ""
    tags, desc = [], ""
    m = re.search(r'"keywords":(\[[^\]]*\])', html)
    if m:
        try:
            tags = [str(x) for x in json.loads(m.group(1))][:30]
        except Exception:
            tags = []
    m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', html)
    if m:
        try:
            desc = json.loads('"' + m.group(1) + '"')
        except Exception:
            desc = m.group(1)
    return {"tags": tags, "hashtags": re.findall(r"#[^\s#,.!?।]+", desc)[:15]}


def trend_style(kind, lang, cache_dir, real):
    """Once a day: HOW this week's most watched videos look - their titles, thumbnails, tags and hashtags - so our
    own title, thumbnail, tags and hashtags follow the same winning style (never a copy of anyone's picture/title)."""
    key = env("GEMINI_API_KEY")
    if not real or env("TREND_STYLE") == "0":
        return {}
    import base64 as _b64
    from collections import Counter
    tag_n, hash_n = Counter(), Counter()
    for v in real[:6]:
        try:
            meta = yt_video_meta(v["id"])
        except Exception:
            continue
        for x in meta["tags"]:
            if not TREND_SKIP.search(x):
                tag_n[x.strip().lower()] += 1
        for x in meta["hashtags"]:
            if not TREND_SKIP.search(x):
                hash_n[x.strip()] += 1
        time.sleep(1.0)
    style = {"tags": [x for x, _n in tag_n.most_common(15)], "hashtags": [x for x, _n in hash_n.most_common(10)]}
    parts = [{"text": (
        f"These are this week's most watched YouTube videos in India for {kind} stories in "
        f"{'Bengali' if lang == 'bn' else 'Hindi'} (titles with views), and below the thumbnails of the top ones:\n"
        + "\n".join(f"- {v['title']} ({v['views']:,} views)" for v in real[:10]) +
        "\n\nDescribe the WINNING STYLE only (we make our own original videos; never copy a title, a person, a "
        "picture or a channel). Answer ONLY JSON: {\"title_style\": \"2-3 English sentences: how these titles are "
        "built - length, words that pull clicks, use of '|', emoji, numbers, 'সত্য ঘটনা' etc.\", \"thumb_style\": "
        "\"2-3 English sentences: what the thumbnails show - colours, light, faces / expressions, the ghost, the "
        "composition, how big the text is and its colour\", \"thumb_text_style\": \"one English sentence: how "
        "many words of text on the thumbnail and what kind\"}")}]
    for v in real[:4]:
        try:
            im = requests.get(f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg", timeout=20)
            if im.ok and len(im.content) > 3000:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": _b64.b64encode(im.content).decode()}})
        except Exception:
            pass
    for model in (helper_models(key)[:4] if key else []):
        try:
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                              json={"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.3}},
                              timeout=120)
            if not r.ok:
                continue
            text = "\n".join(p_.get("text", "") for p_ in r.json()["candidates"][0]["content"]["parts"])
            got = load_json_loose(text[text.find("{"):text.rfind("}") + 1]) if "{" in text else {}
            if isinstance(got, dict) and got.get("title_style"):
                style.update({k_: str(got.get(k_, ""))[:500] for k_ in ("title_style", "thumb_style", "thumb_text_style")})
                break
        except Exception as e:
            log(f"  trend style ({model}) failed: {str(e)[:100]}")
    if style.get("title_style") or style.get("tags"):
        log(f"  this week's winning style ({kind}): tags {', '.join(style['tags'][:6])} | "
            f"{str(style.get('thumb_style', ''))[:120]}")
    return style


def trend_style_get(kind, lang, cache_dir=None):
    """the saved style of the last 3 days (also in a later run that only posts)"""
    k = f"{kind}_{lang}"
    if k in TREND_STYLE:
        return TREND_STYLE[k]
    st = {}
    try:
        with open(os.path.join(cache_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"),
                               "trends.json"), encoding="utf-8") as f:
            d = json.load(f).get(k) or {}
        age = (dt.datetime.now(IST).date() - dt.date.fromisoformat(d.get("date", "2000-01-01"))).days
        if age <= 3:
            st = d.get("style") or {}
    except Exception:
        st = {}
    TREND_STYLE[k] = st
    return st


def trend_style_rule(kind, lang, cache_dir=None):
    """the writer's rule: our title and thumbnail words in the style of this week's most watched videos"""
    st = trend_style_get(kind, lang, cache_dir)
    if not st.get("title_style"):
        return ""
    return ("\nTITLE AND THUMBNAIL TEXT IN THIS WEEK'S WINNING STYLE (measured on the most watched videos of our "
            f"kind on YouTube this week - follow the STYLE, never copy a title): titles - {st['title_style']} "
            f"Thumbnail text - {st.get('thumb_text_style', '')}\n")


def trending_topics(kind, lang, cache_dir, cat=None):
    """Once a day: what Bengali / Indian viewers are watching NOW in this kind of video on YouTube and Facebook
    (found with Google Search) - so our stories ride the trend. Cached for the day in cache_dir/trends.json.
    Returns a short list of English topic lines ([] if unknown)."""
    key = env("GEMINI_API_KEY")
    if not key or env("TRENDS") == "0":
        return []
    today = dt.datetime.now(IST).date().isoformat()
    path = os.path.join(cache_dir, "trends.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    k = f"{kind}_{lang}" + (f"_{cat}" if cat and CAT_QUERIES.get((kind, cat)) else "")
    queries = cat_queries(kind, lang, cat) if cat else None
    old = data.get(k) or {}
    if old.get("date") == today and (old.get("topics") or int(old.get("tries") or 0) >= 2):
        return old.get("topics", [])
    what = ("Bengali / Hindi horror audio stories (bhuter golpo, bhoot ki kahani, Sunday-suspense style radio "
            "dramas, true ghost experiences)" if kind == "horror" else
            "Bengali / Hindi children's cartoon and moral stories (Gopal Bhar, Thakurmar Jhuli, Panchatantra, "
            "kids' animated stories)")
    prompt = (f"Search YouTube and Facebook trends of the last 7 days in India for {what} in "
              f"{'Bengali' if lang == 'bn' else 'Hindi'}. Which topics, characters, settings and story types are getting "
              "the most views and comments right now? Answer ONLY JSON: {\"topics\": [6 short English lines, each a "
              "concrete story topic idea that rides one of these trends (no channel names, no copyrighted characters "
              "except folk / public-domain ones)], \"hashtags\": [10 hashtags these viewers really use now, Bengali/"
              "Hindi and English, each starting with #], \"keywords\": [8 exact phrases people type in YouTube search "
              "for this, in the story language and in English letters]}")
    topics, tags_, kws = [], [], []
    real = []
    if old.get("date") == today and old.get("real"):
        real = old["real"]                            # (searched once today already - not again)
    else:
        try:
            real = yt_trending(kind, lang, queries=queries) if env("YT_TRENDS") != "0" else []
        except Exception as e:
            log("  YouTube trend list failed:", str(e)[:100])
    auto = []
    if not real:
        try:
            auto = yt_autocomplete((queries or TREND_QUERIES.get((kind, lang), []))[:4], lang)
        except Exception:
            auto = []
    if real or auto:
        # (11 Nov 2026) the REAL list: what is most watched on YouTube this week -> our own new stories on those topics
        seen_ = ("\n".join(f"- {v['title']} ({v['views']:,} views, {v['age']})" for v in real) if real else
                 "People are typing these in YouTube search right now:\n" + "\n".join(f"- {a_}" for a_ in auto))
        prompt = (f"These are the most watched {what} on YouTube in India THIS WEEK:\n{seen_}\n\n"
                  "Find what they have in common: the kind of place, the fear / the hook, the kind of people, the "
                  "situation. Then give NEW story ideas for OUR channel that ride exactly these trends. RULES: never "
                  "retell or copy any of these videos' stories, characters or titles - only the TOPIC (a new, original "
                  "story); nothing from Sunday Suspense, Mirchi or any published author's story; no channel names; no "
                  "copyrighted characters (only folk / public-domain ones). Answer ONLY JSON: {\"topics\": [6 short "
                  "English lines, each one concrete ORIGINAL story idea with its place, its people and its hook, most "
                  "trending first], \"hashtags\": [10 hashtags these viewers really use, Bengali/Hindi and English, "
                  "each starting with #], \"keywords\": [8 exact phrases people type in YouTube search for this, in "
                  "the story language and in English letters]}")
    for model in helper_models(key)[:4]:
        try:
            body_ = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.6}}
            if not (real or auto):
                body_["tools"] = [{"google_search": {}}]
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                              json=body_, timeout=120)
            if not r.ok:
                log(f"  trends: {model} answered {r.status_code} ({'busy / limit reached' if r.status_code in (429, 503) else r.text[:80]})")
                continue
            text = "\n".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
            got = load_json_loose(text[text.find("{"):text.rfind("}") + 1]) if "{" in text else {}
            if isinstance(got, list):
                got = {"topics": got}
            topics = [str(x)[:160] for x in (got.get("topics") or []) if str(x).strip()][:6]
            tags_ = [("#" + str(x).strip().lstrip("#").replace(" ", "")) for x in (got.get("hashtags") or [])
                     if str(x).strip()][:10]
            kws = [str(x).strip()[:60] for x in (got.get("keywords") or []) if str(x).strip()][:8]
            if topics:
                break
        except Exception as e:
            log(f"  trends ({model}) failed: {str(e)[:100]}")
    if not topics and real:
        # (13 Nov 2026: Gemini was busy at night and the YouTube list was thrown away) - without Gemini: the topics
        # of the most watched titles themselves, as ORIGINAL new stories on the same topic
        for v in real[:6]:
            head = re.split(r"\s*(?:\|\||\||#|-{2,})\s*", v["title"])[0].strip()
            head = re.sub(r"(?i)\b(?:bhuter cartoon|cartoon|horror thriller|bengali horror|full|episode \d+|ep \d+)\b", "",
                          head).strip(" -:|")
            if len(head) >= 4:
                topics.append(f"an ORIGINAL new story on the same topic as this week's much-watched video '{head}' "
                              "(only the topic - our own place, people, events and twist)")
        if topics:
            log("  trends: Gemini busy - the topics are taken from the most watched titles themselves")
    if not topics:                            # not remembered - the next run today tries again (twice at most)
        log("  trends: nothing found this time - today's story is written without them")
        data[k] = {"date": today, "topics": [], "real": real[:15],
                   "tries": (int(old.get("tries") or 0) + 1) if old.get("date") == today else 1}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        return []
    style = {}
    try:
        style = trend_style(kind, lang, cache_dir, real)
    except Exception as e:
        log("  trend style skipped:", str(e)[:100])
    if style.get("hashtags"):                 # the hashtags those videos REALLY use come first
        tags_ = (style["hashtags"] + [h_ for h_ in tags_ if h_.lower() not in [x.lower() for x in style["hashtags"]]])[:12]
    TREND_STYLE[k] = style
    if k != f"{kind}_{lang}":                 # (the posting run reads the newest hashtags / style under the kind)
        data[f"{kind}_{lang}"] = {"date": today, "topics": topics, "hashtags": tags_, "keywords": kws, "style": style,
                                  "real": real[:15], "from_cat": cat}
    data[k] = {"date": today, "topics": topics, "hashtags": tags_, "keywords": kws, "style": style, "real": real[:15],
               "youtube_top": [f"{v['title']} ({v['views']:,})" for v in real[:10]], "from": "youtube" if real else
               ("search" if auto else "google")}
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    if topics:
        log("Trending now:", " | ".join(t[:60] for t in topics[:3]))
    return topics



def trend_extras(kind, lang, cache_dir):
    """today's trending hashtags and search phrases (saved by trending_topics): (hashtags, keywords)"""
    try:
        with open(os.path.join(cache_dir, "trends.json"), encoding="utf-8") as f:
            d = json.load(f).get(f"{kind}_{lang}") or {}
        if (dt.datetime.now(IST).date() - dt.date.fromisoformat(d.get("date", "2000-01-01"))).days <= 2:
            return d.get("hashtags") or [], d.get("keywords") or []    # (stories are written the night before)
    except Exception:
        pass
    return [], []


def yt_autocomplete(seeds, lang):
    """What people really type in YouTube search (YouTube's own suggestions) - for tags and titles."""
    out = []
    for q in seeds[:4]:
        try:
            r = requests.get("https://suggestqueries.google.com/complete/search", timeout=15,
                             params={"client": "firefox", "ds": "yt", "q": q, "hl": lang})
            for s in (r.json()[1] if r.ok else [])[:6]:
                if s not in out:
                    out.append(s)
        except Exception:
            pass
    return out[:15]


def seo_pack(kind, lang, cache_dir, seeds):
    """search words for this video: today's trending phrases + YouTube's own search suggestions"""
    tags_, kws = trend_extras(kind, lang, cache_dir)
    kws = list(kws) + list(trend_style_get(kind, lang, cache_dir).get("tags") or [])[:10]
    auto = yt_autocomplete(seeds, lang) if env("SEO") != "0" else []
    words = []
    for w in kws + auto:
        w = str(w).strip()
        if w and w.lower() not in [x.lower() for x in words]:
            words.append(w)
    if words:
        log("  search words:", " | ".join(words[:6]))
    return tags_, words[:15]


# ----------------------------------------------------------------- learning from our own numbers + comments
def learn_lessons(history, kind, lang, cache_dir):
    """Every 2 days: compare our best and weakest videos (views, how long people watched, likes, comments) and read
    the viewers' comments, then write short lessons for the next stories and what the viewers ask for.
    Saved in cache_dir/lessons.json. Returns dict(lessons=[...], requests=[...], titles=[...])."""
    path = os.path.join(cache_dir, "lessons.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    k = f"{kind}_{lang}"
    old = data.get(k) or {}
    try:
        if old and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(old["made"])).days < 2:
            return old
    except Exception:
        pass
    key = env("GEMINI_API_KEY")
    rows = []
    for h in history[-40:]:
        st = h.get("stats") or {}
        if h.get("lang") != lang or not st:
            continue
        rows.append({"title": str(h.get("title", ""))[:80], "category": h.get("category") or h.get("special") or "",
                     "format": str(h.get("format", ""))[:60], "slot": h.get("slot"), "views": st.get("views", 0),
                     "fb_views": st.get("fb_views"), "watched_pct": st.get("watched_pct"), "likes": st.get("likes"),
                     "comments": st.get("comments"), "yt_watched_pct": st.get("yt_avg_pct"),
                     "yt_most_leave_at_pct": st.get("yt_drop_at"), "title_b": h.get("title_b"),
                     "title_test": (h.get("title_test") or {}).get("result")})
        tl = h.get("timeline") or {}                  # v68: the CHAPTER where most viewers left (not just a %)
        if st.get("yt_drop_at") is not None and tl.get("len") and tl.get("parts"):
            try:
                sec = float(tl["len"]) * float(st["yt_drop_at"]) / 100
                lab = next((l_ for t_, l_ in reversed(tl["parts"]) if t_ <= sec), None)
                if lab:
                    rows[-1]["most_leave_in_chapter"] = f"{lab} ({int(sec // 60)}:{int(sec % 60):02d})"
            except (TypeError, ValueError):
                pass
    if not key or len(rows) < 5:
        return old
    comments = []
    for h in history[-8:]:
        try:
            comments += [c for c in comment_texts(h.get("facebook"), h.get("youtube")) if len(c) > 3][:25]
        except Exception:
            pass
    prompt = (f"You analyse a {kind} video page (Facebook + YouTube, {'Bengali' if lang == 'bn' else 'Hindi'}). "
              "Here are our recent videos with their numbers (watched_pct / yt_watched_pct = average share of the video "
              "watched; yt_most_leave_at_pct = where in the video most viewers leave, most_leave_in_chapter = the chapter "
              "they left in - make such chapters tighter and more gripping; title_test swapped = the first "
              "title got few views and title_b replaced it):\n"
              + json.dumps(rows, ensure_ascii=False) + "\nAnd recent viewer comments:\n"
              + json.dumps(comments[:120], ensure_ascii=False)[:6000]
              + "\nCompare the best and the weakest videos. Answer ONLY JSON (ENGLISH): {\"lessons\": [5 short, "
                "concrete lessons for writing the NEXT stories (openings, length, kinds of story, characters, endings) "
                "that the numbers really support], \"titles\": [3 lessons about titles / hooks that got more clicks], "
                "\"requests\": [up to 6 concrete things viewers asked for in the comments: a ghost, a place, a "
                "character, a kind of story]}. Be honest - if the numbers are too few to tell, say less.")
    for model in helper_models(key)[:4]:
        try:
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}},
                              timeout=120)
            if not r.ok:
                log(f"  lessons: {model} answered {r.status_code}")
                continue
            got = load_json_loose(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            new = {"made": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                   "lessons": [str(x)[:200] for x in got.get("lessons") or []][:5],
                   "titles": [str(x)[:200] for x in got.get("titles") or []][:3],
                   "requests": [str(x)[:160] for x in got.get("requests") or []][:6]}
            data[k] = new
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            log("Learned from our numbers:", " | ".join(x[:70] for x in new["lessons"][:2]))
            return new
        except Exception as e:
            log(f"  lessons ({model}) failed: {str(e)[:100]}")
    return old


def lessons_rule(les):
    """the lessons as words for the story writer"""
    if not les or not (les.get("lessons") or les.get("requests") or les.get("titles")):
        return ""
    out = "\nLEARNED FROM OUR OWN VIEWERS' NUMBERS AND COMMENTS (follow these):\n"
    out += "".join(f"- {x}\n" for x in les.get("lessons") or [])
    out += "".join(f"- title: {x}\n" for x in les.get("titles") or [])
    if les.get("requests"):
        out += ("- Our viewers asked for: " + " | ".join(les["requests"]) +
                " - if one fits today's kind of story, give it to them.\n")
    return out



# ----------------------------------------------------------------- YouTube: how long people watch, title test
YTA = "https://youtubeanalytics.googleapis.com/v2/reports"


def yt_retention(video_id):
    """YouTube Analytics (needs the yt-analytics.readonly permission): average % and seconds watched, and where in
    the video most viewers leave (yt_drop_at = % of the video)."""
    hdr = yt_token()
    today = dt.date.today().isoformat()
    out = {}
    r = requests.get(YTA, headers=hdr, timeout=30, params={
        "ids": "channel==MINE", "startDate": "2020-01-01", "endDate": today, "filters": f"video=={video_id}",
        "metrics": "views,averageViewDuration,averageViewPercentage"})
    if r.ok and r.json().get("rows"):
        v, avg_s, avg_p = r.json()["rows"][0][:3]
        out.update(yt_views=v, yt_avg_s=round(avg_s), yt_avg_pct=round(avg_p, 1))
    r = requests.get(YTA, headers=hdr, timeout=30, params={
        "ids": "channel==MINE", "startDate": "2020-01-01", "endDate": today, "filters": f"video=={video_id}",
        "dimensions": "elapsedVideoTimeRatio", "metrics": "audienceWatchRatio"})
    rows = r.json().get("rows") if r.ok else None
    if rows and len(rows) > 5:
        drops = [(rows[i][0], rows[i - 1][1] - rows[i][1]) for i in range(1, len(rows))]
        at, size = max(drops[1:], key=lambda x: x[1])     # (not the first second - everyone drops there)
        out["yt_drop_at"] = round(at * 100)
    return out


def yt_set_thumbnail(video_id, path):
    hdr = yt_token()
    with open(path, "rb") as f:
        t = requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
                          headers={**hdr, "Content-Type": "image/jpeg"}, data=f, timeout=120)
    if not t.ok:
        raise RuntimeError(_yt_err(t))
    return True


def keep_thumb_b(thumb_dir, video_id, path):
    """Keeps the video's SECOND thumbnail (same picture, other words, mirrored) for a few days: if the video gets
    few views, it replaces the first one. Old ones are deleted, so the repo stays small."""
    if not (video_id and path and os.path.exists(path)):
        return None
    os.makedirs(thumb_dir, exist_ok=True)
    now = time.time()
    idx_path = os.path.join(thumb_dir, "kept.json")   # when each one was kept (a file's own date is no help:
    idx = _jl(idx_path, {})                            # every GitHub run makes all files 'new' - none ever got old)
    idx = idx if isinstance(idx, dict) else {}
    for f in os.listdir(thumb_dir):
        if not f.endswith(".jpg"):
            continue
        vid = f[:-4]
        try:
            if now - float(idx.setdefault(vid, now)) > 6 * 86400:
                os.remove(os.path.join(thumb_dir, f))
                idx.pop(vid, None)
        except (OSError, TypeError, ValueError):
            pass
    out = os.path.join(thumb_dir, f"{video_id}.jpg")
    Image.open(path).convert("RGB").save(out, quality=86)
    idx[str(video_id)] = now
    _js(idx_path, {k: v for k, v in idx.items() if os.path.exists(os.path.join(thumb_dir, f"{k}.jpg"))})
    return out


def yt_title_test(history, max_checks=6, thumb_dir=None):
    """A day after a video goes up: if it gets clearly fewer views than our usual videos, its second title
    (made at writing time) and its second thumbnail replace the first ones - once. Which one wins is kept in
    history (and the story writer learns from it)."""
    if not env("YT_REFRESH_TOKEN") or env("TITLE_TEST") == "0":
        return False
    now = dt.datetime.now(dt.timezone.utc)
    seen = sorted((h.get("stats") or {}).get("views", 0) for h in history[-30:] if (h.get("stats") or {}).get("views"))
    if len(seen) < 5:
        return False
    median = seen[len(seen) // 2]
    changed = False
    for h in history[-12:]:
        tb = os.path.join(thumb_dir, f"{h.get('youtube')}.jpg") if thumb_dir and h.get("youtube") else ""
        tb = tb if tb and os.path.exists(tb) else ""
        if not h.get("youtube") or not (h.get("title_b") or tb) or h.get("title_test"):
            continue
        try:
            age = (now - dt.datetime.fromisoformat(str(h["date"]))).total_seconds() / 3600
        except Exception:
            continue
        if not 24 <= age <= 96:
            continue
        hdr = yt_token()
        r = requests.get(f"{YT}/videos", headers=hdr, timeout=30,
                         params={"part": "snippet,statistics", "id": h["youtube"]})
        items = r.json().get("items") if r.ok else None
        if not items:
            continue
        views = int(items[0]["statistics"].get("viewCount", 0))
        if views >= median * 0.6:
            h["title_test"] = {"result": "kept", "views": views}
            changed = True
            continue
        sn = items[0]["snippet"]
        thumb_ok = False
        if tb:
            try:
                thumb_ok = yt_set_thumbnail(h["youtube"], tb)
                log(f"  YouTube thumbnail test: a weak video ({views} views, usual {median}) got its second thumbnail")
            except Exception as e:
                log("  second thumbnail not set:", str(e)[:120])
        if not h.get("title_b"):
            h["title_test"] = {"result": "thumb_swapped" if thumb_ok else "failed", "views_before": views,
                               "at": now.isoformat(timespec="minutes")}
            changed = True
            continue
        new = {"id": h["youtube"], "snippet": {"title": str(h["title_b"])[:100], "description": sn.get("description", ""),
                                                "categoryId": sn.get("categoryId", "24"), "tags": sn.get("tags", []),
                                                "defaultLanguage": sn.get("defaultLanguage"),
                                                "defaultAudioLanguage": sn.get("defaultAudioLanguage")}}
        new["snippet"] = {k: v for k, v in new["snippet"].items() if v}
        u = requests.put(f"{YT}/videos", headers={**hdr, "Content-Type": "application/json"}, params={"part": "snippet"},
                         data=json.dumps(new), timeout=30)
        if u.ok:
            h["title_test"] = {"result": "swapped", "views_before": views, "at": now.isoformat(timespec="minutes"),
                               "thumb": thumb_ok}
            log(f"  YouTube title test: '{sn.get('title', '')[:40]}' had {views} views (usual {median}) - "
                f"now '{str(h['title_b'])[:40]}'")
        else:
            h["title_test"] = {"result": "failed", "why": _yt_err(u)[:120]}
        changed = True
        max_checks -= 1
        if max_checks <= 0:
            break
    return changed


# ----------------------------------------------------------------- Facebook: a second Reel, a daily question
def fb_question_post(history, kind, lang, page_name="", photo=None, link=""):
    """Once a day a short question on the page (people answer -> Facebook shows the page to more people).
    Once a week (Wednesday) for horror: 'Spot the ghost' - a picture of the newest story with its ghost hidden
    in it (Meta's advice, 8 Nov 2026: keeps the followers taking part)."""
    page, token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    if not (page and token) or env("FB_QUESTION") == "0":
        return None
    today = dt.datetime.now(IST).date().isoformat()
    if any(h.get("question_post") == today for h in history[-8:]):
        return None
    qs = {("horror", "bn"): ["আপনার জীবনের সবচেয়ে ভয়ের রাত কোনটা? কমেন্টে লিখুন - সেরা অভিজ্ঞতা গল্প হয়ে আসবে 👻",
                             "ছোটবেলায় ঠাকুমা-দিদিমার কাছে কোন ভূতের গল্প শুনেছিলেন? 🕯️",
                             "কোন ভূতের গল্প শুনতে চান? শাঁকচুন্নি, ব্রহ্মদৈত্য, নিশির ডাক, না অন্য কিছু? কমেন্টে লিখুন",
                             "রাতে একা থাকলে কোন শব্দে সবচেয়ে ভয় লাগে? 🕯️",
                             "আপনার গ্রামে বা পাড়ায় কোন ভুতুড়ে জায়গার গল্প শোনা যায়? কমেন্টে বলুন",
                             "আজকের গল্পে সবচেয়ে ভয়ের মুহূর্ত কোনটা ছিল? 👇",
                             "কখনো এমন কিছু দেখেছেন বা শুনেছেন, যার কোনো ব্যাখ্যা পাননি? 👀"],
          ("horror", "hi"): ["आपकी ज़िंदगी की सबसे डरावनी रात कौन सी थी? कमेंट में लिखिए 👻",
                             "बचपन में दादी-नानी से कौन सी भूतिया कहानी सुनी थी? 🕯️",
                             "कौन सी भूतिया कहानी सुनना चाहते हैं? कमेंट में लिखिए",
                             "रात में अकेले हों तो किस आवाज़ से सबसे ज़्यादा डर लगता है? 🕯️",
                             "कभी कुछ ऐसा देखा या सुना जिसकी कोई वजह नहीं मिली? 👀"],
          ("cartoon", "bn"): ["আপনার ছোটবেলার সবচেয়ে প্রিয় গল্প কোনটা? কমেন্টে লিখুন 📚",
                              "গোপাল ভাঁড়ের কোন গল্পটা আবার দেখতে চান? 😄",
                              "বাচ্চারা কোন গল্প শুনতে সবচেয়ে ভালোবাসে - রূপকথা, পশুপাখি, না গোয়েন্দা? 👇",
                              "আজকের গল্প থেকে কী শিখলেন? কমেন্টে লিখুন ✨",
                              "ঠাকুমার কাছে শোনা কোন গল্প আজও মনে আছে? 🌙"],
          ("cartoon", "hi"): ["आपके बचपन की सबसे पसंदीदा कहानी कौन सी है? कमेंट में लिखिए 📚",
                              "बच्चे कौन सी कहानी सबसे ज़्यादा पसंद करते हैं - परी, जानवर या जासूसी? 👇",
                              "आज की कहानी से क्या सीखा? कमेंट में लिखिए ✨",
                              "दादी-नानी से सुनी कौन सी कहानी आज भी याद है? 🌙"]}.get((kind, lang)) or []
    if not qs:
        return None
    if (kind == "horror" and photo and os.path.exists(photo) and env("SPOT_GHOST") != "0"
            and dt.datetime.now(IST).weekday() == int(env("SPOT_GHOST_DAY") or 2)):
        cap = ({"bn": "👻 খুঁজে দেখুন তো: এই ছবির কোথাও একটা ভূত লুকিয়ে আছে। কোথায় দেখলেন? 👀",
                "hi": "👻 ढूँढिए: इस तस्वीर में कहीं एक भूत छिपा है। कहाँ दिखा? 👀"}.get(lang, "")
               + (f"\n\n{'পুরো গল্প' if lang == 'bn' else 'पूरी कहानी'}: {link}" if link else ""))
        try:
            fb_photo(photo, cap)
            log("  weekly 'spot the ghost' picture posted on Facebook")
            return today
        except Exception as e:
            log("  'spot the ghost' skipped:", str(e)[:150])
    msg = qs[dt.datetime.now(IST).timetuple().tm_yday % len(qs)]
    r = requests.post(f"{GRAPH}/{page}/feed", data={"message": msg, "access_token": token}, timeout=30).json()
    if r.get("id"):
        log("  daily question posted on Facebook")
        return today
    log("  daily question skipped:", str(r)[:160])
    return None


# ===================== v28: YOUR OWN stories sent on Telegram (horror + cartoon) =====================
TRUE_LABEL = {"bn": "সত্য ঘটনা অবলম্বনে", "hi": "सच्ची घटना पर आधारित"}
CARTOON_WORDS = ("কার্টুন", "cartoon", "कार्टून")
FICTION_WORDS = ("কাল্পনিক", "kalponik", "काल्पनिक")


def _jl(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _js(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# Stories sent on Telegram BEFORE this moment are never made into videos (your wish of 7 Nov 2026): only the
# stories you send from now on. (A different start can be set with the CREATOR_SINCE variable.)
CREATOR_SINCE = "2026-11-07T11:30:00+05:30"


def _creator_since():
    s = env("CREATOR_SINCE") or CREATOR_SINCE
    try:
        return s, dt.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return CREATOR_SINCE, dt.datetime.fromisoformat(CREATOR_SINCE).timestamp()


BOT_NAME = {"horror": "ভূতের bot", "cartoon": "কার্টুন bot"}
CMD_WORDS = {"status": ("অবস্থা", "/status", "status", "/অবস্থা", "খবর"),
             "pause": ("বন্ধ", "/pause", "pause", "/বন্ধ"),
             "resume": ("চালু", "/resume", "resume", "/চালু"),
             "skip": ("বাদ", "/skip", "skip", "/বাদ"),
             "help": ("সাহায্য", "/help", "help", "/start", "কমান্ড")}


def _command(text):
    """'অবস্থা', 'বন্ধ ভূত ২ দিন', 'চালু', 'বাদ কার্টুন ১' ... -> (name, target, number) or None"""
    t = norm_digits(str(text or "").strip().lower()).rstrip("?।!.। ")
    for name, words in CMD_WORDS.items():
        for w in words:
            if t == w or t.startswith(w + " ") or t.startswith(w + "\n"):
                rest = t[len(w):]
                target = ("horror" if any(x in rest for x in ("ভূত", "ভুত", "horror", "হরর")) else
                          "cartoon" if any(x in rest for x in ("কার্টুন", "cartoon", "কার্টূন")) else "all")
                num = re.search(r"\d+", rest)
                return name, target, int(num.group()) if num else None
    return None


def bot_paused(path):
    """True while YOU paused this bot from Telegram ('বন্ধ'); the pause ends by itself on its date, or with 'চালু'."""
    d = _jl(path, {})
    return bot_paused_data(d) if isinstance(d, dict) else False


def _run_commands(data, cmds, kind, status):
    """Your Telegram commands, answered at this bot's next run (both bots read the same chat)."""
    me = BOT_NAME.get(kind, kind)
    for name, target, num in cmds:
        mine = target in ("all", kind)
        if name == "help":
            if kind == "horror":                      # one answer is enough
                telegram("🤖 Telegram থেকে bot চালানোর কথা (উত্তর আসে bot-এর পরের run-এ):\n"
                         "• অবস্থা - দুটো bot-এর খবর, লাইনে কোন গল্প\n"
                         "• বন্ধ / বন্ধ ভূত / বন্ধ কার্টুন - post বন্ধ (যেমন: বন্ধ ভূত ৩ দিন)\n"
                         "• চালু / চালু ভূত / চালু কার্টুন - আবার চালু\n"
                         "• বাদ ভূত ১ / বাদ কার্টুন ২ - লাইনের সেই গল্প বাদ")
        elif name == "status" and mine:
            q = data.get("queue") or []
            lines = [f"📋 {me}:"]
            if bot_paused_data(data):
                u = data["paused"].get("until")
                lines.append("⏸️ এখন বন্ধ" + ("" if u == "forever" else f" ({str(u)[:10]} পর্যন্ত)") + " - 'চালু' লিখলে চলবে")
            else:
                lines.append("▶️ চালু আছে")
            try:
                lines += [str(x) for x in (status() if status else [])]
            except Exception as e:
                lines.append(f"(খবর আনা গেল না: {str(e)[:60]})")
            pre = "ভূত" if kind == "horror" else "কার্টুন"
            lines.append(f"লাইনে আপনার গল্প: {bn_num(len(q))}টা" + ("" if not q else ":"))
            lines += [f"  {pre}-{bn_num(i + 1)}: {_short(s.get('text', ''), 45)}…" for i, s in enumerate(q[:8])]
            telegram("\n".join(lines))
        elif name == "pause" and mine:
            until = "forever"
            if num:
                until = (dt.datetime.now(IST) + dt.timedelta(days=min(num, 60))).isoformat(timespec="minutes")
            data["paused"] = {"until": until, "since": dt.datetime.now(IST).isoformat(timespec="minutes")}
            telegram(f"⏸️ {me} বন্ধ" + ("" if until == "forever" else f" {bn_num(min(num, 60))} দিনের জন্য") +
                     " - কোনো নতুন ভিডিও যাবে না। আবার চালাতে লিখুন: চালু")
        elif name == "resume" and mine:
            was = bool(data.pop("paused", None))
            telegram(f"▶️ {me} চালু" + ("" if was else " (বন্ধ ছিল না)") + " - পরের সময় থেকে আবার ভিডিও যাবে।")
        elif name == "skip":
            q = data.get("queue") or []
            if target == "all":
                if kind == "horror":
                    telegram("কোন গল্প বাদ দেবেন? লিখুন যেমন: বাদ ভূত ১  বা  বাদ কার্টুন ১ ('অবস্থা' লিখলে নম্বর দেখবেন)")
            elif mine:
                if num and 1 <= num <= len(q):
                    s = q.pop(num - 1)
                    data["used"] = (data.get("used") or [])[-49:] + [{"id": s.get("id"), "skipped": True}]
                    telegram(f"🗑️ {me}: লাইনের {bn_num(num)} নম্বর গল্প বাদ দিলাম ({_short(s.get('text', ''), 40)}…)। "
                             f"লাইনে বাকি: {bn_num(len(q))}টা")
                else:
                    telegram(f"{me}: লাইনে {bn_num(num) if num else '?'} নম্বর গল্প নেই (লাইনে আছে {bn_num(len(q))}টা)।")


def bn_num(n):
    return str(n).translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))


def _short(text, n):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:n]


def bot_paused_data(data):
    p = data.get("paused")
    if not p:
        return False
    u = p.get("until")
    if u and u != "forever":
        try:
            return dt.datetime.now(IST) < dt.datetime.fromisoformat(u)
        except ValueError:
            return False
    return True


def creator_inbox(path, kind="horror", status=None):
    """Stories YOU paste to the Telegram bot (one or more messages sent within 20 minutes = one story).
    Only YOUR chat (TELEGRAM_CHAT_ID) is read. A story that starts with the word 'কার্টুন' goes to the cartoon
    bot, every other story to the horror bot. Starting with 'কাল্পনিক' = no 'based on true events' label.
    Only stories sent AFTER CREATOR_SINCE count - the older ones are dropped once and never made."""
    data = _jl(path, {"queue": [], "seen": []})
    if not isinstance(data, dict):
        data = {"queue": [], "seen": []}
    since_txt, since = _creator_since()
    if data.get("fresh_from") != since_txt:          # ONE clean start: every older story leaves the line
        q = data.get("queue") or []
        keep = [s for s in q if int(s.get("date") or 0) >= since]
        data["queue"], data["seen"], data["fresh_from"] = keep, [], since_txt
        _js(path, data)
        log(f"  your Telegram stories: {len(q) - len(keep)} older stories removed - only stories sent from now on "
            "will be made")
    tok, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if env("MOCK") == "1" or not tok:
        return data
    if not chat:
        log("  your Telegram stories: add the TELEGRAM_CHAT_ID secret first (only your own chat is accepted)")
        return data
    try:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates",
                         params={"allowed_updates": json.dumps(TG_UPDATES)}, timeout=30).json()
    except Exception as e:
        log("  your Telegram stories: could not read -", str(e)[:100])
        return data
    try:                                             # v76: our fan channel + viewers' voice stories
        tg_scan(r.get("result", []), os.path.dirname(os.path.abspath(path)), chat, kind)
    except Exception as e:
        log("  Telegram channel / viewer voices skipped:", str(e)[:100])
    seen, msgs, cmds = set(data.get("seen") or []), [], []
    for u in r.get("result", []):
        uid = u.get("update_id")
        if uid in seen:
            continue
        seen.add(uid)
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat):
            continue                                  # never anyone else's messages
        t = str(msg.get("text") or "").strip()
        if int(msg.get("date") or 0) < since:
            continue                                  # sent before the clean start: never made
        if len(t) < 150 and _command(t):              # a command: অবস্থা / বন্ধ / চালু / বাদ
            cmds.append((int(msg.get("date") or 0), _command(t)))
        elif len(t) >= 150:                           # a story (short messages are just chat)
            msgs.append((int(msg.get("date") or 0), uid, t))
    groups = []
    starts = lambda t: any(t[:40].lower().startswith(w) for w in CARTOON_WORDS + FICTION_WORDS)
    for d, uid, t in sorted(msgs):
        # a message that starts with 'কার্টুন' / 'কাল্পনিক' always begins a NEW story; other messages sent within
        # 20 minutes are the next pieces of the same long story (Telegram cuts long texts)
        if groups and d - groups[-1]["last"] <= 1200 and not starts(t):
            groups[-1]["text"] += "\n" + t
            groups[-1]["last"] = d
        else:
            groups.append({"id": uid, "text": t, "last": d, "date": d})
    had = {s.get("id") for s in data.get("queue") or []} | {s.get("id") for s in data.get("used") or []}
    for g in groups:
        if g["id"] in had:
            continue                                  # already in the line or already made
        text = g["text"].strip()
        head = text[:40].lower()
        is_cartoon = any(head.startswith(w) for w in CARTOON_WORDS)
        if is_cartoon != (kind == "cartoon"):
            continue                                  # the other bot's story
        for w in CARTOON_WORDS:
            if text.lower().startswith(w):
                text = text[len(w):].lstrip(" :-—\n")
        true = True
        for w in FICTION_WORDS:
            if text.lower().startswith(w):
                text, true = text[len(w):].lstrip(" :-—\n"), False
        data.setdefault("queue", []).append({"id": g["id"], "text": text[:15000], "true": true, "date": g["date"],
                                             "got": dt.datetime.now(IST).isoformat(timespec="minutes")})
        when = ("দুপুর ২টোর ভিডিও হবে (দিনে একটা করে)" if kind == "horror" else
                "সকাল ৮টা বা সন্ধ্যা ৭টার ভিডিও হবে (একবারে একটা করে)")
        telegram(f"✅ আপনার {'কার্টুন ' if kind == 'cartoon' else 'ভূতের '}গল্পটা পেয়েছি ({len(text)} অক্ষর)। "
                 f"এই গল্প দিয়েই পরের ফাঁকা {when}"
                 + (" - 'সত্য ঘটনা অবলম্বনে' লেখা থাকবে।" if true else " (কাল্পনিক গল্প হিসেবে)।")
                 + f" লাইনে আছে: {bn_num(len(data['queue']))}টা গল্প।")
        log(f"Your own story received on Telegram ({len(text)} characters)")
    if cmds:
        try:
            _run_commands(data, [c for _d, c in sorted(cmds)], kind, status)
        except Exception as e:
            log("  Telegram commands failed:", str(e)[:120])
    data["seen"] = sorted(seen)[-400:]
    _js(path, data)
    return data


def take_creator_story(path, kind="horror"):
    if env("MY_STORIES") == "0":
        return None
    data = creator_inbox(path, kind)
    if not data.get("queue"):
        return None
    s = data["queue"].pop(0)
    data["used"] = (data.get("used") or [])[-49:] + [{"id": s["id"], "used": dt.datetime.now(IST).isoformat(
        timespec="minutes")}]
    _js(path, data)
    return s


def mark_true_story(story, lang):
    """'Based on true events' on the title, the thumbnail, the teasers and in the narrator's words."""
    lab = TRUE_LABEL.get(lang, TRUE_LABEL["bn"])
    old = str(story.get("tagline") or "").strip()
    story["true_label"] = True
    story["tagline"] = lab + (f" · {old}" if old and len(old) <= 26 and lab not in old else "")
    story["thumbnail_text"] = story.get("thumbnail_text") or lab


def true_title(title, lang):
    lab = TRUE_LABEL.get(lang, TRUE_LABEL["bn"])
    return title if lab in title else f"{title} | {lab}"[:100]


# ===================== v51: the same loudness as big channels (-14 LUFS, true peak -1.5 dB) =====================
def normalize_loudness(wav, target=-14.0):
    """Two-pass, LINEAR loudness correction: the whole sound track is made exactly as loud as YouTube / Facebook
    expect, without squashing the quiet moments (the silence before a scare stays a silence)."""
    if env("LOUDNORM") == "0" or env("MOCK") == "1":
        return wav
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", wav, "-af",
                            f"loudnorm=I={target}:TP=-1.5:LRA=20:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=900)
        js = r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1]
        mv = json.loads(js)
        out = wav.replace(".wav", "_ln.wav")
        flt = (f"loudnorm=I={target}:TP=-1.5:LRA=20:measured_I={mv['input_i']}:measured_TP={mv['input_tp']}:"
               f"measured_LRA={mv['input_lra']}:measured_thresh={mv['input_thresh']}:offset={mv['target_offset']}:"
               "linear=true")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-af", flt, "-ar", "44100", "-c:a",
                        "pcm_s16le", out], check=True, timeout=900)
        os.replace(out, wav)
        log(f"  loudness: {float(mv['input_i']):.1f} -> {target:.0f} LUFS")
    except Exception as e:
        log("  loudness step skipped:", str(e)[:120])
    return wav


# ===================== v51: a short daily report on Telegram (no need to open the logs) =====================
DAY_NOTES = []          # things worth telling the owner from this run (backups used etc.)


def note(text):
    if text not in DAY_NOTES:
        DAY_NOTES.append(text)


def explain_error(text):
    """A problem in plain Bengali, with what to do."""
    t = str(text or "")
    tl = t.lower()
    rules = [
        (("error validating access token", "session has expired", "has expired", "code\': 190", '"code": 190',
          "fb_page_token", "invalid oauth access token"),
         "Facebook token-এর মেয়াদ শেষ বা বাতিল - নতুন Page token বানিয়ে GitHub Secret FB_PAGE_TOKEN বদলান "
         "(Facebook_Token_Renewal.pdf-এর ধাপ)"),
        (("invalid_grant", "token has been expired or revoked"),
         "YouTube-এর অনুমতি বাতিল হয়ে গেছে - নতুন YT_REFRESH_TOKEN বানাতে হবে"),
        (("quotaexceeded", "uploadlimitexceeded", "dailylimitexceeded", "youtube daily limit"),
         "YouTube-এর আজকের limit শেষ - কাল নিজে ঠিক হয়ে যাবে"),
        (("secret ", "is missing"), "একটা GitHub Secret নেই: " + t[:120]),
        (("resource_exhausted", "429", "rate limit", "quota"),
         "Gemini / Google-এর আজকের limit শেষ - কাল আবার নিজে চলবে"),
        (("neuron", "4006", "cloudflare"), "Cloudflare-এর আজকের ছবির limit শেষ - কাল নিজে ঠিক হবে"),
        (("no space left",), "GitHub-এর কম্পিউটারে জায়গা শেষ - পরের run-এ নিজে ঠিক হওয়ার কথা"),
        (("posting failed everywhere",), "Facebook আর YouTube দুটোতেই post হয়নি - কারণ আগের message-এ লেখা আছে"),
        (("timed out", "timeout", "connectionerror", "connection reset", "max retries", "503", "502", "500 server"),
         "ইন্টারনেট বা সার্ভারের সাময়িক সমস্যা - পরের run-এ নিজে ঠিক হয়ে যেতে পারে"),
        (("no chapter written", "could not write", "story too short", "no story"),
         "গল্প লেখা যায়নি (Gemini ব্যস্ত বা limit শেষ) - পরের run-এ আবার চেষ্টা হবে"),
    ]
    for keys, why in rules:
        if all(k in tl for k in keys) if keys == ("secret ", "is missing") else any(k in tl for k in keys):
            return why
    return "অজানা সমস্যা: " + re.sub(r"\s+", " ", t)[:160]


def fail_note(here, text, bot_label):
    """Written when the run stops with an error: the GitHub step 'tell me on Telegram' sends it in Bengali."""
    try:
        with open(os.path.join(here, "fail_reason.txt"), "w", encoding="utf-8") as f:
            f.write(explain_error(text))
    except Exception:
        pass


def alert_post_errors(results, bot_label, title=""):
    """The video went to one place but not the other: tell YOU now, with the reason (no log reading needed)."""
    bad = [(k.split("_")[0], v) for k, v in (results or {}).items() if k.endswith("_error") and v]
    if not bad or env("MOCK") == "1":
        return
    names = {"facebook": "Facebook", "youtube": "YouTube"}
    telegram(f"⚠️ {bot_label}: '{str(title)[:50]}' " + "; ".join(
        f"{names.get(w, w)}-এ যায়নি - {explain_error(v)}" for w, v in bad))


def best_kinds(history, label_of=None, days=30):
    """Which kinds of story our viewers watch most (last 30 days) - for the daily report."""
    now = dt.datetime.now(dt.timezone.utc)
    sums, counts = {}, {}
    for h in history[-120:]:
        st, k = h.get("stats") or {}, h.get("category") or h.get("special")
        try:
            age = (now - dt.datetime.fromisoformat(str(h.get("date")))).days
        except Exception:
            continue
        if not k or not st or age > days:
            continue
        sums[k] = sums.get(k, 0) + score(st)
        counts[k] = counts.get(k, 0) + 1
    rows = sorted(((sums[k] / counts[k], k) for k in counts if counts[k] >= 2), reverse=True)
    if len(rows) < 2:
        return ""
    name = (lambda k: (label_of or {}).get(k, k))
    return ("সবচেয়ে বেশি দেখা হচ্ছে (৩০ দিন): " + ", ".join(name(k) for _s, k in rows[:3])
            + " | সবচেয়ে কম: " + name(rows[-1][1]))


def daily_report(history, bot_label, extra=""):
    """After the day's last video: what went out today, how the last days' videos are doing, anything unusual."""
    import re
    if env("MOCK") == "1" or env("DAILY_REPORT") == "0" or not env("TELEGRAM_BOT_TOKEN"):
        return
    today = dt.datetime.now(IST).date()
    rows, olds = [], []
    for h in history[-40:]:
        try:
            t = dt.datetime.fromisoformat(str(h.get("date"))).astimezone(IST)
        except Exception:
            continue
        name = re.sub(r"\s*\|.*$", "", str(h.get("title", "")))[:60]
        if t.date() == today and h.get("kind") not in ("compilation",):
            links = " ".join(x for x in (f"YT youtu.be/{h['youtube']}" if h.get("youtube") else "",
                                         "FB ✓" if h.get("facebook") else "") if x)
            rows.append(f"• {name} {links}".strip())
        elif 1 <= (today - t.date()).days <= 3 and h.get("stats"):
            st = h["stats"]
            olds.append((st.get("views", 0), f"• {name}: 👁 {st.get('views', 0)} · 👍 {st.get('likes', 0)} · "
                                                f"💬 {st.get('comments', 0)}"))
    olds = [r for _v, r in sorted(olds, reverse=True)[:5]]
    msg = (f"📊 {bot_label} - আজকের হিসেব ({today.strftime('%d %b')})\n\n"
           + ("আজ যা গেছে:\n" + "\n".join(rows) if rows else "আজ কোনো ভিডিও যায়নি ⚠️")
           + ("\n\nগত ৩ দিনের ভিডিও:\n" + "\n".join(olds) if olds else "")
           + (f"\n\n{extra}" if extra else "")
           + ("\n\nলক্ষ্য করুন:\n" + "\n".join(f"• {n}" for n in DAY_NOTES) if DAY_NOTES else "\n\nসব ঠিকঠাক চলেছে ✅"))
    if telegram(msg):
        log("Daily report sent on Telegram")


# =====================================================================================================================
# v76 (12 Nov 2026): growth - YouTube replies, milestones, Telegram fan channel + viewers' voice stories, Facebook
# photo-story countdown, the story as text, story web pages + podcast feed, YouTube Live, old-video shorts
# =====================================================================================================================
TG_UPDATES = ["message", "channel_post", "my_chat_member"]   # (Telegram remembers this list - every reader asks the same)
BN_DIG = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def _here_assets():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


# ----------------------------------------------------------------- 1) answers under the YouTube comments
_MY_YT = {}


def yt_my_channel():
    if "id" not in _MY_YT:
        try:
            r = requests.get(f"{YT}/channels", headers=yt_token(), params={"part": "id,statistics", "mine": "true"},
                             timeout=30).json()
            it = (r.get("items") or [{}])[0]
            _MY_YT.update(id=it.get("id", ""), stats=it.get("statistics") or {})
        except Exception:
            _MY_YT.update(id="", stats={})
    return _MY_YT


def yt_reply_fans(history, lang, kind="horror", max_n=5):
    """Each run: a short, warm reply under the first few NEW YouTube comments of our last 2 days' videos (YouTube
    shows a video to more people when its comments get answers). Never more than max_n a run, never twice."""
    key = env("GEMINI_API_KEY")
    if not (env("YT_REFRESH_TOKEN") and key) or env("REPLY_FANS") == "0" or env("YT_REPLIES") == "0":
        return False
    me = yt_my_channel().get("id")
    now = dt.datetime.now(dt.timezone.utc)
    todo = []
    for h in reversed(history[-8:]):
        if not h.get("youtube") or not h.get("date") or len(todo) >= max_n:
            continue
        try:
            age = (now - dt.datetime.fromisoformat(h["date"])).total_seconds() / 3600
        except Exception:
            continue
        if not 1 <= age <= 60:
            continue
        try:
            r = requests.get(f"{YT}/commentThreads", headers=yt_token(), timeout=30, params={
                "part": "snippet", "videoId": h["youtube"], "maxResults": 50, "order": "time",
                "textFormat": "plainText"})
            items = r.json().get("items", []) if r.ok else []
        except Exception:
            continue
        done = set(h.get("yt_replied") or [])
        for it in items:
            sn = it["snippet"]["topLevelComment"]["snippet"]
            msg = str(sn.get("textDisplay", "")).strip()
            if (it["id"] in done or it["snippet"].get("totalReplyCount") or len(msg) < 2 or len(todo) >= max_n
                    or (sn.get("authorChannelId") or {}).get("value") == me):
                continue
            name = str(sn.get("authorDisplayName", "")).lstrip("@").split(" ")[0][:20]
            todo.append((h, it["id"], name, msg[:300], str(h.get("title", ""))[:80]))
    if not todo:
        return False
    lang = todo[0][0].get("lang") or lang
    lang_name = "Bengali (pure Kolkata cholit bhasha)" if lang == "bn" else "Hindi"
    who = ("the grave, warm storyteller of a horror-story channel" if kind == "horror" else
           "the friendly storyteller of a children's story channel")
    ask = (f"You are {who}. Write a short, warm, natural reply (max 18 words, 0-1 emoji) to each viewer comment in "
           f"{lang_name}: thank them by name, answer a question if there is one (never spoil a twist), mention the "
           "next story if it fits. No links, no hashtags, never ask for likes, shares or subscriptions. Return ONLY "
           "a JSON list of strings in the same order.\n"
           + "\n".join(f"{k + 1}. [{t}] {n}: {m}" for k, (h, cid, n, m, t) in enumerate(todo)))
    replies = []
    for model in helper_models(key)[:4]:
        try:
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                              json={"contents": [{"parts": [{"text": ask}]}],
                                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8}},
                              timeout=90)
            if r.ok:
                replies = load_json_loose(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                if isinstance(replies, list) and replies:
                    break
        except Exception:
            continue
    n = 0
    for (h, cid, name, msg, t), text in zip(todo, replies if isinstance(replies, list) else []):
        text = str(text).strip()
        if not text:
            continue
        try:
            rr = requests.post(f"{YT}/comments", headers=yt_token(), params={"part": "snippet"}, timeout=30,
                               json={"snippet": {"parentId": cid, "textOriginal": text[:500]}})
            n += bool(rr.ok)
        except Exception:
            pass
        h["yt_replied"] = (list(h.get("yt_replied") or []) + [cid])[-200:]
    log(f"  replied to {n} YouTube comments")
    return n > 0


# ----------------------------------------------------------------- 5) milestones (subscribers / followers)
MILESTONES = [100, 250, 500, 1000, 2000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000]


def channel_counts():
    out = {}
    if env("YT_REFRESH_TOKEN"):
        try:
            out["yt"] = int(yt_my_channel().get("stats", {}).get("subscriberCount") or 0)
        except Exception:
            pass
    if env("FB_PAGE_TOKEN") and env("FB_PAGE_ID"):
        try:
            r = requests.get(f"{GRAPH}/{env('FB_PAGE_ID')}", timeout=30, params={
                "fields": "followers_count,fan_count", "access_token": env("FB_PAGE_TOKEN")}).json()
            out["fb"] = int(r.get("followers_count") or r.get("fan_count") or 0)
        except Exception:
            pass
    return out


def milestone_check(path):
    """Once a day: a NEW milestone passed? -> dict(platform, n) to celebrate (the first check only remembers)."""
    data = _jl(path, {})
    data = data if isinstance(data, dict) else {}
    today = dt.datetime.now(IST).date().isoformat()
    if data.get("checked") == today or env("MILESTONES") == "0":
        return None
    data["checked"] = today
    got = None
    for pf, n in channel_counts().items():
        passed = max([m for m in MILESTONES if m <= n] or [0])
        last = data.get(pf)
        if last is None:
            data[pf] = passed                         # first time: what is already reached is not news
        elif passed > int(last):
            data[pf] = passed
            got = got or {"platform": pf, "n": passed, "count": n}
        data[f"{pf}_now"] = n
    if got:
        data["pending"] = got
    _js(path, data)
    return got


def milestone_take(path):
    """the milestone the next story's storyteller thanks the viewers for (once)"""
    data = _jl(path, {})
    if not isinstance(data, dict) or not data.get("pending"):
        return None
    got = data.pop("pending")
    _js(path, data)
    return got


def milestone_card(bg, n, platform, lang, out, font_path):
    word = ({"yt": "সাবস্ক্রাইবার", "fb": "ফলোয়ার"} if lang == "bn" else {"yt": "सब्सक्राइबर", "fb": "फ़ॉलोअर"})[platform]
    num = str(n).translate(BN_DIG) if lang == "bn" else f"{n:,}"
    lines = (["ধন্যবাদ!", f"{num} জন {word}", "আপনারাই আমাদের পরিবার 🕯️"] if lang == "bn" else
             ["धन्यवाद!", f"{num} {word}", "आप ही हमारा परिवार हैं 🕯️"])
    return text_card(bg, lines, out, font_path)


def latin_font():
    for p in ("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return p
    return ""


def text_card(bg, lines, out, font_path, size=(1280, 720), sizes=None):
    """a dark picture with big centred lines of text (Bengali / Hindi shaped correctly)"""
    W, H = size
    try:
        im = Image.open(bg).convert("RGB")
        s = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1))
        l, t = (im.width - W) // 2, (im.height - H) // 2
        im = im.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(3))
    except Exception:
        im = Image.new("RGB", (W, H), (10, 8, 14))
    im = Image.blend(im, Image.new("RGB", (W, H), (0, 0, 0)), 0.55)
    d = ImageDraw.Draw(im)
    sizes = sizes or [int(H * 0.13)] + [int(H * 0.085)] * (len(lines) - 1)
    sizes = (list(sizes) + [sizes[-1]] * len(lines))[:len(lines)]
    # a line in English letters only (viewers' names) gets a font WITH English letters - the Bengali font has none
    paths = [latin_font() if (re.search(r"[A-Za-z]", str(x)) and not re.search(r"[\u0900-\u09FF]", str(x))
                               and latin_font()) else font_path for x in lines]
    fonts = [_font(pp, sz) for pp, sz in zip(paths, sizes)]
    shown = [fit_glyphs(str(x), pp) for x, pp in zip(lines, paths)]
    hs = [f.getbbox(x or " ")[3] - f.getbbox(x or " ")[1] for f, x in zip(fonts, shown)]
    y = (H - sum(hs) - 30 * (len(lines) - 1)) // 2
    for k, (f, x, h) in enumerate(zip(fonts, shown, hs)):
        while d.textlength(x, font=f) > W * 0.9 and f.size > 20:
            f = _font(paths[k], f.size - 4)
        w = d.textlength(x, font=f)
        d.text(((W - w) / 2, y), x, font=f, fill=(255, 214, 90) if k == 0 else (245, 245, 245),
               stroke_width=4, stroke_fill=(0, 0, 0))
        y += h + 30
    im.save(out, quality=92)
    return out


# ----------------------------------------------------------------- 6) Telegram fan channel  +  11) viewers' voice
def tg_get(path_dir):
    return _jl(os.path.join(path_dir, "tg_channel.json"), {}) or {}


def tg_scan(updates, path_dir, owner_chat, kind="horror"):
    """From Telegram's updates: (a) the channel the bot was made admin of = our fan channel; (b) VOICE messages
    that viewers sent to the bot (their own ghost experience) - horror only. Nothing else of anyone is kept."""
    ch = tg_get(path_dir)
    changed = False
    for u in updates:
        mcm = u.get("my_chat_member") or {}
        chat = mcm.get("chat") or {}
        ttl = str(chat.get("title", "")).lower()
        is_cartoon_ch = any(w in ttl for w in ("কার্টুন", "cartoon", "kids", "বাচ্চা", "ছোটদের", "बच्चों", "कार्टून",
                                                 "রূপকথা", "kahani", "story time"))
        if chat.get("type") == "channel" and is_cartoon_ch == (kind == "cartoon"):   # (each bot its own channel)
            status = (mcm.get("new_chat_member") or {}).get("status")
            if status == "administrator" and str(ch.get("id")) != str(chat.get("id")):
                ch = {"id": chat.get("id"), "title": chat.get("title", ""), "username": chat.get("username", ""),
                      "queue": ch.get("queue") or []}
                changed = True
                telegram(f"✅ {'কার্টুন' if kind == 'cartoon' else 'ভূতের'} bot-এর ফ্যান চ্যানেল পেয়েছি: "
                         f"{chat.get('title', '')}। এখন থেকে প্রতিটা নতুন গল্পের খবর এই চ্যানেলে যাবে।")
            elif status in ("left", "kicked") and str(ch.get("id")) == str(chat.get("id")):
                ch, changed = {}, True
    if changed:
        _js(os.path.join(path_dir, "tg_channel.json"), ch)
    if kind != "horror" or env("VIEWER_VOICE") == "0":
        return
    vpath = os.path.join(path_dir, "viewer_voice.json")
    vv = _jl(vpath, {"raw": [], "stories": [], "seen": []})
    seen = set(vv.get("seen") or [])
    added = 0
    for u in updates:
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        voice = msg.get("voice") or msg.get("audio")
        if not voice or chat.get("type") != "private" or str(chat.get("id")) == str(owner_chat):
            continue
        if u.get("update_id") in seen:
            continue
        seen.add(u.get("update_id"))
        if int(voice.get("duration") or 0) < 20 or int(voice.get("file_size") or 0) > 19_000_000:
            tg_send(chat.get("id"), "🙏 ধন্যবাদ! কমপক্ষে আধ মিনিট ধরে আপনার আসল ভৌতিক অভিজ্ঞতাটা গলায় বলে পাঠান - "
                                    "সেটা নিয়েই আমাদের 'সত্যি ঘটনা' গল্প হবে।")
            continue
        frm = msg.get("from") or {}
        vv.setdefault("raw", []).append({"file_id": voice["file_id"], "chat": chat.get("id"), "date": msg.get("date"),
                                         "name": str(frm.get("first_name") or "")[:20], "uid": u.get("update_id"),
                                         "mime": voice.get("mime_type") or "audio/ogg"})
        added += 1
    vv["seen"] = sorted(seen)[-500:]
    if added or vv.get("raw"):
        _js(vpath, vv)


def tg_send(chat_id, text, photo=None):
    tok = env("TELEGRAM_BOT_TOKEN")
    if not tok or not chat_id or env("MOCK") == "1":
        return False
    try:
        if photo and os.path.exists(photo):
            with open(photo, "rb") as f:
                r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", timeout=60,
                                  data={"chat_id": chat_id, "caption": text[:1024]}, files={"photo": f})
        else:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=30,
                              data={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": "false"})
        return r.ok
    except Exception:
        return False


_TG_ME = {}


def tg_bot_link():
    tok = env("TELEGRAM_BOT_TOKEN")
    if not tok or env("MOCK") == "1":
        return ""
    if "u" not in _TG_ME:
        try:
            _TG_ME["u"] = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=20).json()["result"]["username"]
        except Exception:
            _TG_ME["u"] = ""
    return f"https://t.me/{_TG_ME['u']}" if _TG_ME["u"] else ""


def tg_channel_link(path_dir):
    u = tg_get(path_dir).get("username")
    return f"https://t.me/{u}" if u else ""


def tg_channel_post(path_dir, text, photo=None, at=None):
    """our fan channel: now (photo + text), or queued for a later time (sent by the first run after it)"""
    ch = tg_get(path_dir)
    if not ch.get("id") or env("TG_CHANNEL") == "0":
        return False
    if at and at > dt.datetime.now(dt.timezone.utc):
        ch.setdefault("queue", []).append({"at": at.isoformat(), "text": text})
        _js(os.path.join(path_dir, "tg_channel.json"), ch)
        return True
    return tg_send(ch["id"], text, photo)


def tg_channel_flush(path_dir):
    ch = tg_get(path_dir)
    if not ch.get("id") or not ch.get("queue"):
        return False
    now = dt.datetime.now(dt.timezone.utc)
    keep, sent = [], 0
    for q in ch["queue"]:
        try:
            due = dt.datetime.fromisoformat(q["at"]) <= now
        except Exception:
            due = True
        if due:
            sent += tg_send(ch["id"], q["text"])
        else:
            keep.append(q)
    ch["queue"] = keep[-20:]
    _js(os.path.join(path_dir, "tg_channel.json"), ch)
    if sent:
        log(f"  fan channel: {sent} message(s) sent")
    return sent > 0


def viewer_voice_process(path_dir, max_n=2):
    """Viewers' voice messages -> written experiences (Gemini listens and writes them down in Bengali). Only real
    ghost experiences are kept; the viewer gets a thank-you on Telegram."""
    vpath = os.path.join(path_dir, "viewer_voice.json")
    vv = _jl(vpath, {"raw": [], "stories": [], "seen": []})
    tok, key = env("TELEGRAM_BOT_TOKEN"), env("GEMINI_API_KEY")
    if not vv.get("raw") or not tok or not key:
        return 0
    import base64 as _b64
    done = 0
    rest = []
    for it in vv["raw"]:
        if done >= max_n:
            rest.append(it)
            continue
        try:
            fp = requests.get(f"https://api.telegram.org/bot{tok}/getFile", params={"file_id": it["file_id"]},
                              timeout=30).json()["result"]["file_path"]
            audio = requests.get(f"https://api.telegram.org/file/bot{tok}/{fp}", timeout=120).content
            ask = ("This is a voice message from a viewer of our Bengali horror-story channel. 1) Write down exactly "
                   "what they say, in Bengali script. 2) Decide: is it a real personal ghost / paranormal experience "
                   "(not a joke, not a request, not abuse)? Leave out any phone number, full address or full names "
                   "of private people. Answer ONLY JSON: {\"text\": \"...\", \"is_experience\": true/false}")
            got = {}
            for model in helper_models(key)[:4]:
                r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                                  json={"contents": [{"parts": [{"text": ask}, {"inline_data": {
                                      "mime_type": it.get("mime") or "audio/ogg",
                                      "data": _b64.b64encode(audio).decode()}}]}],
                                      "generationConfig": {"responseMimeType": "application/json"}}, timeout=180)
                if r.ok:
                    got = load_json_loose(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                    if isinstance(got, dict) and got.get("text"):
                        break
            text = str((got or {}).get("text") or "").strip()
            if got and got.get("is_experience") and len(text) >= 120:
                vv.setdefault("stories", []).append({"id": f"tg_{it['uid']}", "chat": it["chat"], "name": it["name"],
                                                     "text": text[:3000], "date": it["date"]})
                tg_send(it["chat"], "🙏 আপনার অভিজ্ঞতাটা পেয়েছি, অনেক ধন্যবাদ! এটা নিয়ে আমাদের 'সত্যি ঘটনা' গল্প হবে "
                                    "- আপনার নাম থাকবে (ঠিকানা বা ফোন নম্বর কখনো নয়)। গল্প বেরোলে এখানেই জানাব।")
                log(f"  a viewer's voice story received ({len(text)} letters)")
            else:
                tg_send(it["chat"], "🙏 ধন্যবাদ! আপনার নিজের জীবনের কোনো ভৌতিক অভিজ্ঞতা থাকলে সেটা গলায় বলে পাঠান - "
                                    "সেটা নিয়েই গল্প হবে।")
            done += 1
        except Exception as e:
            log("  viewer voice message skipped:", str(e)[:100])
            if int(time.time()) - int(it.get("date") or 0) < 86400:
                rest.append(it)                       # (Telegram keeps the file for a while: try again next run)
    vv["raw"] = rest
    _js(vpath, vv)
    return done


def viewer_voice_stories(path_dir, used_ids):
    vv = _jl(os.path.join(path_dir, "viewer_voice.json"), {})
    return [dict(s, likes=10 ** 6) for s in (vv.get("stories") or []) if s.get("id") not in used_ids]


def viewer_voice_done(path_dir, sid, links):
    vv = _jl(os.path.join(path_dir, "viewer_voice.json"), {})
    for s in vv.get("stories") or []:
        if s.get("id") == sid:
            tg_send(s.get("chat"), "👻 আপনার পাঠানো অভিজ্ঞতা নিয়ে গল্প বেরিয়েছে! " + " ".join(links))


# ----------------------------------------------------------------- 10) Facebook photo story (countdown)
def fb_photo_story(image):
    page, token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    if env("FB_STORY") == "0" or not (page and token):
        return None
    with open(image, "rb") as f:
        r = requests.post(f"{GRAPH}/{page}/photos", data={"published": "false", "access_token": token},
                          files={"source": ("story.jpg", f, "image/jpeg")}, timeout=120).json()
    if not r.get("id"):
        raise RuntimeError(f"story photo: {str(r)[:200]}")
    fin = requests.post(f"{GRAPH}/{page}/photo_stories", data={"photo_id": r["id"], "access_token": token},
                        timeout=60).json()
    if not fin.get("success") and not fin.get("post_id"):
        raise RuntimeError(f"photo story: {str(fin)[:200]}")
    return fin.get("post_id") or r["id"]


def story_card_vertical(bg, lines, out, font_path):
    return text_card(bg, lines, out, font_path, size=(1080, 1920), sizes=[130, 96, 72, 72][:len(lines)])


# ----------------------------------------------------------------- 7) the story as text  +  3) web page
def story_text(story, names=None, frac=1.0, max_chars=None):
    """the story as readable prose: the storyteller's lines as paragraphs, people's words with their name"""
    names = names or {}
    out, total = [], 0
    lines = [ln for sc in story.get("scenes") or [] for ln in (sc.get("lines") or []) if str(ln.get("text", "")).strip()]
    stop = max(1, int(len(lines) * frac))
    for ln in lines[:stop]:
        t = strip_tags(str(ln["text"])).strip()
        sp = str(ln.get("speaker", "narrator"))
        if not sp.lower().startswith("narrat"):
            nm = names.get(sp.lower()) or sp
            t = f"{nm}: “{t}”"
        out.append(t)
        total += len(t)
        if max_chars and total >= max_chars:
            break
    return "\n\n".join(out)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def story_page(docs, slug, title, text, yt_id, fb_id, base, lang="bn", date=""):
    """docs/golpo/<slug>.html - the whole story to READ (Google finds it) with the video on top; + the list
    page and sitemap.xml"""
    gdir = os.path.join(docs, "golpo")
    os.makedirs(gdir, exist_ok=True)
    url = (base or "") + f"golpo/{slug}.html"
    desc = re.sub(r"\s+", " ", text)[:155]
    vid = (f'<iframe src="https://www.youtube.com/embed/{yt_id}" title="{_esc(title)}" allowfullscreen loading="lazy">'
           f'</iframe>' if yt_id else
           (f'<p><a href="https://www.facebook.com/{fb_id}">▶ ভিডিওতে শুনুন</a></p>' if fb_id else ""))
    img = f"https://i.ytimg.com/vi/{yt_id}/hqdefault.jpg" if yt_id else ""
    body = "".join(f"<p>{_esc(p)}</p>" for p in text.split("\n\n") if p.strip())
    ld = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": title[:110],
                     "inLanguage": lang, "datePublished": date, "image": img or None, "url": url,
                     "author": {"@type": "Organization", "name": env("PAGE_NAME_BN") or "Daily Horror Story"}},
                    ensure_ascii=False)
    page = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(title)} | ভূতের গল্প</title>
<meta name="description" content="{_esc(desc)}"><link rel="canonical" href="{_esc(url)}">
<meta property="og:title" content="{_esc(title)}"><meta property="og:description" content="{_esc(desc)}">
{f'<meta property="og:image" content="{img}">' if img else ''}<script type="application/ld+json">{ld}</script>
<style>body{{background:#0d0b10;color:#e8e2d6;font:18px/1.9 "Noto Serif Bengali",serif;margin:0}}
main{{max-width:760px;margin:auto;padding:18px}}h1{{color:#ffcf4a;line-height:1.4}}a{{color:#ffcf4a}}
iframe{{width:100%;aspect-ratio:16/9;border:0;border-radius:10px}}p{{margin:0 0 1em}}</style></head><body><main>
<p><a href="index.html">← সব গল্প</a> · <a href="../">ভূতের মানচিত্র</a></p><h1>{_esc(title)}</h1>{vid}
<article>{body}</article><p><a href="index.html">← আরও ভূতের গল্প পড়ুন</a></p></main></body></html>"""
    with open(os.path.join(gdir, f"{slug}.html"), "w", encoding="utf-8") as f:
        f.write(page)
    lst_p = os.path.join(gdir, "list.json")
    lst = [x for x in (_jl(lst_p, []) or []) if x.get("slug") != slug]
    lst.append({"slug": slug, "title": title, "date": date, "yt": yt_id})
    _js(lst_p, lst)
    rows = "".join(f'<li><a href="{_esc(x["slug"])}.html">{_esc(x["title"])}</a> <small>{_esc(x.get("date", ""))}</small></li>'
                   for x in reversed(lst))
    with open(os.path.join(gdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>সব ভূতের গল্প - পড়ুন ও শুনুন</title>
<meta name="description" content="বাংলা ভূতের গল্প, সত্যি ঘটনা আর রহস্য - প্রতিদিন নতুন গল্প, পড়ুন আর ভিডিওতে শুনুন।">
<style>body{{background:#0d0b10;color:#e8e2d6;font:18px/1.8 sans-serif;margin:0}}main{{max-width:760px;margin:auto;padding:18px}}
a{{color:#ffcf4a}}li{{margin:.5em 0}}</style></head><body><main><h1>👻 সব ভূতের গল্প</h1>
<p><a href="../">ভূতের মানচিত্র</a></p><ul>{rows}</ul></main></body></html>""")
    if base:
        urls = [base, base + "golpo/index.html"] + [base + f"golpo/{x['slug']}.html" for x in lst]
        with open(os.path.join(docs, "sitemap.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                    + "".join(f"<url><loc>{_esc(u)}</loc></url>\n" for u in urls) + "</urlset>\n")
    return url


# ----------------------------------------------------------------- 4) podcast (Spotify / Apple) feed
def gh_release_upload(path, name, tag="podcast"):
    """an audio file into the repo's 'podcast' release (no size burden on the repo); returns its public link"""
    tok, repo = env("GITHUB_TOKEN"), env("GITHUB_REPOSITORY")
    if not (tok and repo):
        return ""
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers=hdr, timeout=30)
    if r.status_code == 404:
        r = requests.post(f"https://api.github.com/repos/{repo}/releases", headers=hdr, timeout=30,
                          json={"tag_name": tag, "name": "Podcast audio", "body": "Audio of the stories (podcast feed)."})
    rel = r.json()
    if not rel.get("id"):
        raise RuntimeError(f"release: {str(rel)[:200]}")
    for a in rel.get("assets") or []:
        if a.get("name") == name:
            return a.get("browser_download_url", "")
    with open(path, "rb") as f:
        up = requests.post(f"https://uploads.github.com/repos/{repo}/releases/{rel['id']}/assets",
                           params={"name": name}, data=f, timeout=600,
                           headers={**hdr, "Content-Type": "audio/mpeg"})
    if not up.ok:
        raise RuntimeError(f"upload: {up.text[:200]}")
    return up.json().get("browser_download_url", "")


def podcast_feed(docs, base, ep, show_title, cover_src=None, lang="bn"):
    """adds one episode to docs/podcast.xml (an RSS feed Spotify and Apple Podcasts read by themselves)"""
    p_ = os.path.join(docs, "podcast.json")
    eps = [e for e in (_jl(p_, []) or []) if e.get("guid") != ep["guid"]] + [ep]
    eps = eps[-300:]
    _js(p_, eps)
    cover = os.path.join(docs, "podcast_cover.jpg")
    if cover_src and not os.path.exists(cover):
        try:
            im = Image.open(cover_src).convert("RGB")
            s = min(im.width, im.height)
            im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2)) \
              .resize((1400, 1400)).save(cover, quality=90)
        except Exception:
            pass
    email = env("PODCAST_EMAIL")
    items = "".join(
        f"<item><title>{_esc(e['title'])}</title><description>{_esc(e.get('desc', ''))}</description>"
        f"<enclosure url=\"{_esc(e['url'])}\" length=\"{int(e.get('bytes', 0))}\" type=\"audio/mpeg\"/>"
        f"<guid isPermaLink=\"false\">{_esc(e['guid'])}</guid><pubDate>{e['date']}</pubDate>"
        f"<itunes:duration>{int(e.get('secs', 0))}</itunes:duration><itunes:explicit>false</itunes:explicit></item>\n"
        for e in reversed(eps))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
<channel><title>{_esc(show_title)}</title><link>{_esc(base)}</link><language>{lang}</language>
<atom:link href="{_esc(base)}podcast.xml" rel="self" type="application/rss+xml"/>
<description>প্রতিদিন নতুন বাংলা ভূতের গল্প - রেডিও নাটকের মতো, রাতের অন্ধকারে শোনার জন্য।</description>
<itunes:author>{_esc(show_title)}</itunes:author><itunes:explicit>false</itunes:explicit>
<itunes:category text="Fiction"><itunes:category text="Drama"/></itunes:category>
<itunes:image href="{_esc(base)}podcast_cover.jpg"/>
{f'<itunes:owner><itunes:name>{_esc(show_title)}</itunes:name><itunes:email>{_esc(email)}</itunes:email></itunes:owner>' if email else ''}
{items}</channel></rss>
"""
    with open(os.path.join(docs, "podcast.xml"), "w", encoding="utf-8") as f:
        f.write(xml)
    return base + "podcast.xml"


# ----------------------------------------------------------------- 8) the scariest moment of an old video
def scariest_window(video, length=45.0, skip_start=90.0, skip_end=60.0):
    """start second of the `length`-second piece around the loudest sudden moment (a scare) of a video"""
    import numpy as _np_
    wav = video + ".env.wav"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vn", "-ac", "1", "-ar", "8000", wav])
    try:
        import wave
        with wave.open(wav) as w:
            a = _np_.frombuffer(w.readframes(w.getnframes()), dtype=_np_.int16).astype(_np_.float32)
    finally:
        if os.path.exists(wav):
            os.remove(wav)
    hop = 4000                                         # 0.5 s
    n = len(a) // hop
    if n < 10:
        return 0.0
    rms = _np_.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-9)
    base = _np_.convolve(rms, _np_.ones(20) / 20, mode="same")          # the 10 s around
    jump = rms / (base + 1e-6)
    total = n * 0.5
    lo, hi = int(skip_start / 0.5), int(max(skip_start + length, total - skip_end) / 0.5)
    if hi - lo < 4:
        return max(0.0, min(total - length, skip_start))
    k = lo + int(_np_.argmax(jump[lo:hi]))
    return float(max(0.0, min(total - length, k * 0.5 - length * 0.75)))


# ----------------------------------------------------------------- 2) YouTube Live
def yt_live_create(title, description, thumb=None):
    """a public live broadcast that starts by itself when our stream arrives: (broadcast id, rtmp url, chat id)"""
    hdr = yt_token()
    start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    b = requests.post(f"{YT}/liveBroadcasts", headers=hdr, params={"part": "snippet,status,contentDetails"},
                      timeout=60, json={
                          "snippet": {"title": title[:100], "description": description[:4900], "scheduledStartTime": start},
                          "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
                          "contentDetails": {"enableAutoStart": True, "enableAutoStop": True, "enableDvr": True,
                                             "latencyPreference": "normal"}})
    if not b.ok:
        raise RuntimeError(f"broadcast: {b.text[:400]}")
    b = b.json()
    s = requests.post(f"{YT}/liveStreams", headers=hdr, params={"part": "snippet,cdn"}, timeout=60, json={
        "snippet": {"title": "bot stream"},
        "cdn": {"ingestionType": "rtmp", "resolution": "720p", "frameRate": "30fps"}})
    if not s.ok:
        raise RuntimeError(f"stream: {s.text[:300]}")
    s = s.json()
    bd = requests.post(f"{YT}/liveBroadcasts/bind", headers=hdr, timeout=60,
                       params={"id": b["id"], "part": "id,contentDetails", "streamId": s["id"]})
    if not bd.ok:
        raise RuntimeError(f"bind: {bd.text[:300]}")
    if thumb:
        try:
            yt_set_thumbnail(b["id"], thumb)
        except Exception:
            pass
    ing = s["cdn"]["ingestionInfo"]
    return b["id"], f"{ing['ingestionAddress']}/{ing['streamName']}", (b.get("snippet") or {}).get("liveChatId")


def yt_live_chat(chat_id, page_token=None):
    """new live-chat messages: ([(author, text)], next page token)"""
    p = {"liveChatId": chat_id, "part": "snippet,authorDetails", "maxResults": 200}
    if page_token:
        p["pageToken"] = page_token
    r = requests.get(f"{YT}/liveChat/messages", headers=yt_token(), params=p, timeout=30)
    if not r.ok:
        return [], page_token
    j = r.json()
    me = yt_my_channel().get("id")
    out = [(str((m.get("authorDetails") or {}).get("displayName", "")).lstrip("@")[:24],
            str((m.get("snippet") or {}).get("displayMessage", ""))[:200])
           for m in j.get("items", []) if (m.get("authorDetails") or {}).get("channelId") != me]
    return out, j.get("nextPageToken") or page_token


def yt_live_say(chat_id, text):
    try:
        return requests.post(f"{YT}/liveChat/messages", headers=yt_token(), params={"part": "snippet"}, timeout=30,
                             json={"snippet": {"liveChatId": chat_id, "type": "textMessageEvent",
                                               "textMessageDetails": {"messageText": text[:190]}}}).ok
    except Exception:
        return False


def live_clip(src, dst, w=1280, h=720, fps=25):
    """every piece of the live programme in exactly the same format (so they play one after another without a
    break) with a key picture every 2 seconds, as YouTube Live wants"""
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf",
          f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "3000k", "-bufsize", "6000k",
          "-g", str(fps * 2), "-keyint_min", str(fps * 2), "-sc_threshold", "0",
          "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", dst])
    return dst


def live_card(img, secs, dst):
    tmp = dst + ".raw.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img, "-f", "lavfi", "-i",
          "anullsrc=channel_layout=stereo:sample_rate=44100", "-t", f"{secs:.1f}", "-c:v", "libx264",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", tmp])
    live_clip(tmp, dst)
    os.remove(tmp)
    return dst


# =====================================================================================================================
# v77 (12 Nov 2026): the bot's own health check, the safety check before every upload, the first-30-seconds learning
# and the daily growth monitor that changes what it can by itself and tells you only what it cannot
# =====================================================================================================================
def _ok_get(url, **k):
    try:
        r = requests.get(url, timeout=30, **k)
        return r.ok, r
    except Exception as e:
        return False, e


def health_check(kind="horror"):
    """every key the bot needs: valid now? about to run out? -> list of (level, Bengali text). Never shows a key."""
    out = []
    tok, page = env("FB_PAGE_TOKEN"), env("FB_PAGE_ID")
    if tok:
        ok, r = _ok_get(f"{GRAPH}/debug_token", params={"input_token": tok, "access_token": tok})
        d = (r.json().get("data") or {}) if ok else {}
        if not ok or not d.get("is_valid", False):
            out.append(("bad", "Facebook-এর চাবি (FB_PAGE_TOKEN) আর কাজ করছে না - Facebook-এ পোস্ট বন্ধ হয়ে যাবে। নতুন page token বানিয়ে GitHub Secrets-এ বদলে দিন।"))
        else:
            for k_, what in (("expires_at", "Facebook-এর চাবি"), ("data_access_expires_at", "Facebook-এর ডেটা দেখার অনুমতি")):
                ts = int(d.get(k_) or 0)
                if ts:
                    days = (ts - time.time()) / 86400
                    if days < 10:
                        out.append(("warn", f"{what} আর {max(0, int(days))} দিনে শেষ হবে - তার আগে নতুন page token বানিয়ে GitHub Secrets-এ বদলে দিন।"))
            if page and str(d.get("profile_id") or page) != str(page) and d.get("type") == "PAGE":
                out.append(("warn", "Facebook-এর চাবিটা অন্য কোনো Page-এর মনে হচ্ছে - FB_PAGE_ID আর token মিলিয়ে দেখুন।"))
    else:
        out.append(("warn", "FB_PAGE_TOKEN নেই - Facebook-এ কিছু যাবে না।"))
    if env("YT_REFRESH_TOKEN"):
        try:
            hdr = yt_token()
            at = hdr.get("Authorization", "").replace("Bearer ", "")
            ok, r = _ok_get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": at})
            scope = r.json().get("scope", "") if ok else ""
            if scope:
                if "youtube.force-ssl" not in scope and "auth/youtube " not in scope + " ":
                    out.append(("warn", "YouTube-এর অনুমতিতে কমেন্টের উত্তর / লাইভ নেই (youtube.force-ssl) - YouTube token নতুন করে বানাতে হবে।"))
                if "yt-analytics" not in scope:
                    out.append(("info", "YouTube Analytics-এর অনুমতি নেই - কতক্ষণ দেখা হলো, প্রথম ৩০ সেকেন্ড শেখা যাবে না।"))
        except Exception as e:
            out.append(("bad", "YouTube-এর চাবি (YT_REFRESH_TOKEN) কাজ করছে না - YouTube-এ upload বন্ধ হয়ে যাবে। "
                               f"({str(e)[:80]})"))
    for name in ("GEMINI_API_KEY", "GEMINI_TTS_KEY"):
        key = env(name)
        if not key:
            if name == "GEMINI_API_KEY" or kind == "horror":
                out.append(("bad" if name == "GEMINI_API_KEY" else "warn", f"{name} নেই।"))
            continue
        ok, r = _ok_get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": key}, params={"pageSize": 1})
        if not ok:
            out.append(("bad", f"Gemini-র চাবি {name} কাজ করছে না ({getattr(r, 'status_code', '?')}) - "
                               + ("গল্প লেখা বন্ধ হবে।" if name == "GEMINI_API_KEY" else "Gemini গলা বন্ধ হবে, Chirp গলা নেবে।")))
    if env("TELEGRAM_BOT_TOKEN"):
        ok, _r = _ok_get(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/getMe")
        if not ok:
            out.append(("warn", "Telegram bot-এর চাবি কাজ করছে না।"))
    return out


# ----------------------------------------------------------------- 4) safety check before every upload
RISKY = [   # (pattern, replacement) - words that make YouTube / Facebook hide a video, or count as misleading
    (r"(?i)\b(?:100\s*%\s*real|real\s+ghost\s+caught|caught\s+on\s+camera|proof\s+of\s+ghost|not\s+fake)\b", ""),
    (r"(?i)\b(?:suicide|self[\s-]?harm|kill\s+yourself)\b", ""),
    (r"(?i)\b(?:sex|sexy|nude|naked|porn\w*|18\+)\b", ""),
    (r"(?i)\b(?:gore|gory|beheaded|dismember\w*|bloodbath)\b", ""),
    (r"(আত্মহত্যা|আত্মহনন|নগ্ন|উলঙ্গ|যৌন|ধর্ষণ)", ""),
    (r"(आत्महत्या|नग्न|यौन|बलात्कार)", ""),
    (r"(?i)\b(?:like\s+and\s+share|share\s+(?:this|kore|koro)|tag\s+\w+\s+friends?|comment\s+1\s+or\s+2)\b", ""),
]


def safety_check(title, description, tags, kind="horror"):
    """Before every upload: the title / description / tags are made safe for YouTube and Facebook - no words that get
    a video limited, no misleading 'real ghost caught' claims, no engagement bait, YouTube's limits kept (title 100,
    description 5000, tags 500 letters, max 15 hashtags, no < >). Returns (title, description, tags, notes)."""
    notes = []

    def clean(s, what):
        s0 = str(s or "")
        for pat, rep_ in RISKY:
            if re.search(pat, s0):
                notes.append(f"{what}: '{re.search(pat, s0).group(0)}' সরানো হলো")
                s0 = re.sub(pat, rep_, s0)
        s0 = s0.replace("<", "‹").replace(">", "›")
        return re.sub(r"[ \t]{2,}", " ", s0).strip(" |-–:")
    title = clean(title, "title")
    if len(title) > 100:
        title = title[:100].rsplit(" ", 1)[0]
        notes.append("title ১০০ অক্ষরে ছোট করা হলো")
    if kind == "horror" and re.search(r"(?i)\b(?:kids?|children|bacchon|ছোটদের|বাচ্চাদের)\b", title):
        notes.append("horror-এর title-এ 'ছোটদের' ধরনের শব্দ ছিল - সরানো হলো (YouTube ভুল করে 'kids' ভাবতে পারে)")
        title = re.sub(r"(?i)\b(?:kids?|children|bacchon|ছোটদের|বাচ্চাদের)\b", "", title).strip()
    description = clean(description, "description")
    tags_in_desc = re.findall(r"#\S+", description)
    if len(tags_in_desc) > 15:                       # (more than 60 - YouTube ignores ALL of them; keep it tidy)
        for h_ in tags_in_desc[15:]:
            description = description.replace(" " + h_, "", 1).replace(h_, "", 1)
        notes.append(f"hashtag {len(tags_in_desc)} থেকে ১৫-তে নামানো হলো")
    if len(description) > 4900:
        description = description[:4900]
        notes.append("description ছোট করা হলো")
    out, total = [], 0
    for t_ in tags or []:
        t_ = clean(t_, "tag").replace(",", " ").strip()
        if not t_ or t_.lower() in [x.lower() for x in out]:
            continue
        if len(t_) > 100 or total + len(t_) + 3 > 480:
            continue
        out.append(t_)
        total += len(t_) + 3
    return title, description, out, notes


def thumb_safe(path, limit=1_900_000):
    """YouTube refuses thumbnails over 2 MB: such a picture is saved again smaller"""
    try:
        if path and os.path.exists(path) and os.path.getsize(path) > limit:
            im = Image.open(path).convert("RGB")
            for size in (None, (1920, 1080), (1280, 720)):
                if size and im.width > size[0]:
                    im = im.resize(size)
                for q in (90, 80, 70, 60, 50):
                    im.save(path, "JPEG", quality=q)
                    if os.path.getsize(path) <= limit:
                        return True
            return True
    except Exception:
        pass
    return False


# ----------------------------------------------------------------- 3) the first 30 seconds
def yt_keep30(video_id, length_s):
    """the share of viewers still watching after 30 seconds (YouTube Analytics retention curve)"""
    if not length_s or length_s < 60:
        return None
    r = requests.get(YTA, headers=yt_token(), timeout=30, params={
        "ids": "channel==MINE", "startDate": "2020-01-01", "endDate": dt.date.today().isoformat(),
        "filters": f"video=={video_id}", "dimensions": "elapsedVideoTimeRatio", "metrics": "audienceWatchRatio"})
    rows = r.json().get("rows") if r.ok else None
    if not rows:
        return None
    want = 30.0 / float(length_s)
    best = min(rows, key=lambda x: abs(float(x[0]) - want))
    return round(float(best[1]) * 100, 1)


def yt_ctr(video_ids, days=28):
    """thumbnail click rate (%) of these videos (YouTube Analytics) -> {id: ctr}"""
    out = {}
    if not video_ids:
        return out
    end = dt.date.today()
    r = requests.get(YTA, headers=yt_token(), timeout=30, params={
        "ids": "channel==MINE", "startDate": (end - dt.timedelta(days=days)).isoformat(), "endDate": end.isoformat(),
        "dimensions": "video", "filters": "video==" + ",".join(video_ids[:50]),
        "metrics": "videoThumbnailImpressions,videoThumbnailImpressionsClickRate"})
    for row in (r.json().get("rows") or []) if r.ok else []:
        if row[1] and row[1] >= 100:                 # (too few impressions say nothing)
            out[row[0]] = round(float(row[2]), 2)
    return out


OPENINGS = {
    "flash": ("FLASH HOOK: the very first line is the most frightening sound or line from LATER in this story, heard "
              "for a moment and not explained; then the narrator clearly begins the story from its real start."),
    "question": ("QUESTION HOOK: the narrator's very first line asks the listener a chilling, personal question "
                 "about the fear of this story (\"আপনি কি কখনো মাঝরাতে ...?\"); then the story clearly begins from its "
                 "real start."),
    "place": ("PLACE-AND-TIME HOOK: the first line names the exact year, place and time of night in one vivid, "
              "real-sounding sentence with one strange detail (\"১৯৮৭ সালের শ্রাবণ, পুরুলিয়ার এক রেলস্টেশন, রাত পৌনে "
              "দুটো - আর প্ল্যাটফর্মে একটাই আলো জ্বলছিল...\"); then the story goes on from there."),
}


def pick_opening(coach):
    """the opening style for the next story: each style is tried twice first, then the one that keeps the most
    viewers past 30 seconds is used most (and the others sometimes, so the bot keeps learning)"""
    st = (coach or {}).get("openings") or {}
    tried = {k: [x for x in (st.get(k) or []) if x is not None] for k in OPENINGS}
    for k in OPENINGS:
        if len(tried[k]) < 2:
            return k
    best = max(OPENINGS, key=lambda k: sum(tried[k][-8:]) / len(tried[k][-8:]))
    return best if random.random() < 0.7 else random.choice([k for k in OPENINGS if k != best])


def coach_load(path):
    d = _jl(path, {})
    return d if isinstance(d, dict) else {}


def growth_monitor(history, path, kind="horror", lang="bn", len_of=None):
    """ONCE A DAY: the numbers of the channel and page, what is going well and badly - and what the bot changes by
    itself because of it. Returns (coach data, Bengali message lines, fixes the bot applied)."""
    coach = coach_load(path)
    today = dt.datetime.now(IST).date().isoformat()
    if coach.get("day") == today:
        return coach, None, None                     # (already done today)
    coach["day"] = today
    lines, did, todo = [], [], []
    # ---- the keys (health check)
    try:
        hc = health_check(kind)
    except Exception as e:
        hc = [("info", f"চাবি পরীক্ষা হয়নি: {str(e)[:60]}")]
    bad = [t for lv, t in hc if lv in ("bad", "warn")]
    # ---- numbers: subscribers / followers, day by day
    counts = channel_counts()
    series = coach.setdefault("counts", {})
    series[today] = counts
    for k_ in sorted(series)[:-60]:
        series.pop(k_, None)
    days = sorted(series)
    def delta(pf, n_days):
        old = next((series[d].get(pf) for d in reversed(days[:-1]) if
                    (dt.date.fromisoformat(today) - dt.date.fromisoformat(d)).days >= n_days and series[d].get(pf) is not None), None)
        return None if old is None or counts.get(pf) is None else counts[pf] - old
    for pf, name, word in (("yt", "YouTube", "subscriber"), ("fb", "Facebook", "follower")):
        if counts.get(pf) is not None:
            d1, d7 = delta(pf, 1), delta(pf, 7)
            lines.append(f"{'▶️' if pf == 'yt' else '📘'} {name}: {counts[pf]} {word}"
                         + (f" ({d1:+d} আজ" if d1 is not None else "") + (f", {d7:+d} এই সপ্তাহে)" if d7 is not None else (")" if d1 is not None else "")))
    # ---- the last 7 days' videos
    now = dt.datetime.now(dt.timezone.utc)
    week = []
    for h in history:
        if h.get("kind") or not h.get("youtube"):
            continue
        try:
            age = (now - dt.datetime.fromisoformat(str(h["date"]))).days
        except Exception:
            continue
        if age <= 14:
            week.append(h)
    # first 30 seconds (needs YouTube Analytics; videos older than 2 days have data)
    op = coach.setdefault("openings", {})
    if env("YT_REFRESH_TOKEN") and env("YT_ANALYTICS") != "0":
        for h in week:
            if h.get("keep30") is not None or not h.get("opening"):
                continue
            try:
                if (now - dt.datetime.fromisoformat(str(h["date"]))).days < 2:
                    continue
                ln = (len_of(h) if len_of else None) or (h.get("timeline") or {}).get("len")
                k30 = yt_keep30(h["youtube"], ln)
            except Exception:
                k30 = None
            if k30 is not None:
                h["keep30"] = k30
                op.setdefault(h["opening"], []).append(k30)
                op[h["opening"]] = op[h["opening"]][-12:]
        if any(op.values()):
            avg_ = {k: sum(v) / len(v) for k, v in op.items() if v}
            best = max(avg_, key=avg_.get)
            lines.append("⏱️ ৩০ সেকেন্ড পরেও দেখছেন: " + " | ".join(
                f"{ {'flash': 'ভয়ের ঝলক', 'question': 'প্রশ্ন', 'place': 'জায়গা-সময়'}.get(k, k)} {v:.0f}%"
                for k, v in sorted(avg_.items(), key=lambda x: -x[1])))
            if len(op.get(best, [])) >= 2:
                did.append(f"গল্পের শুরু বেশিরভাগ সময় '{ {'flash': 'ভয়ের ঝলক', 'question': 'প্রশ্ন', 'place': 'জায়গা-সময়'}.get(best, best)}' ধাঁচে হবে - এতে সবচেয়ে বেশি লোক থেকে যাচ্ছেন")
    # thumbnail click rate -> stronger thumbnails / titles when it is low
    rules = coach.setdefault("rules", {})
    try:
        ctr = yt_ctr([h["youtube"] for h in week]) if env("YT_ANALYTICS") != "0" else {}
    except Exception:
        ctr = {}
    if ctr:
        avg_ctr = sum(ctr.values()) / len(ctr)
        lines.append(f"🖼️ thumbnail-এ ক্লিক: গড় {avg_ctr:.1f}% (ভালো: ৪-১০%)")
        if avg_ctr < 3.5:
            rules["ctr_low"] = True
            did.append("thumbnail-এ ক্লিক কম - এখন থেকে মুখ আরও কাছে, রং আরও উজ্জ্বল, লেখা আরও বড় আর title-এ আরও কৌতূহল")
        elif avg_ctr > 6:
            rules.pop("ctr_low", None)
    # how much of the video people watch -> a faster start when it is low
    pct = [float((h.get("stats") or {}).get("yt_avg_pct")) for h in week if (h.get("stats") or {}).get("yt_avg_pct") is not None]
    if pct:
        a_ = sum(pct) / len(pct)
        lines.append(f"📺 গড়ে ভিডিওর {a_:.0f}% দেখা হচ্ছে")
        if a_ < 25:
            rules["fast_start"] = True
            did.append("লোকে তাড়াতাড়ি চলে যাচ্ছেন - প্রথম ভয় এখন গল্পের আরও আগে আসবে, শুরুর বর্ণনা ছোট হবে")
        elif a_ > 40:
            rules.pop("fast_start", None)
    drops = [int((h.get("stats") or {}).get("yt_drop_at")) for h in week if (h.get("stats") or {}).get("yt_drop_at") is not None]
    if len(drops) >= 3:
        lines.append(f"📉 বেশিরভাগ লোক চলে যান ভিডিওর ~{sorted(drops)[len(drops) // 2]}%-এ")
    # best / weakest of the week
    sc = sorted([h for h in week if h.get("stats")], key=lambda h: score(h["stats"]), reverse=True)
    if sc:
        lines.append(f"🏆 সেরা: {re.sub(r'[|].*$', '', str(sc[0].get('title', '')))[:50].strip()} "
                     f"(👁 {sc[0]['stats'].get('views', 0)})")
    # what only YOU can do
    todo += bad
    if counts.get("yt", 0) and counts["yt"] < 50 and kind == "horror":
        pass
    coach["last_report"] = {"lines": lines, "did": did, "todo": todo}
    _js(path, coach)
    return coach, lines, did


def coach_rule(coach, kind="horror"):
    """the bot's own corrections for the next story (from the growth monitor)"""
    r = (coach or {}).get("rules") or {}
    out = ""
    if r.get("ctr_low"):
        out += ("\nCLICKS ARE LOW THIS WEEK: make the title a sharper curiosity gap (a concrete strange detail + an open "
                "question, never a lie or a spoiler) and the thumbnail_text 2-4 huge, punchy words.\n")
    if r.get("fast_start") and kind == "horror":
        out += ("\nVIEWERS LEAVE EARLY THIS WEEK: the first real fright comes within the first 90 seconds of the story; "
                "keep the opening description short - but the beginning must still be clear (who, where, why).\n")
    return out
