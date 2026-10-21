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


def _fit_text(draw, text, path, max_w, start, lines_max=2):
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
def make_badge(font_path, text, out, colors=((220, 0, 30), (255, 255, 255))):
    """A rounded pill (PNG with transparency) shown in the top-right corner of the main video."""
    bg, fg = colors
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
                colors=((255, 225, 0), (210, 0, 0))):
    """Vertical 720x1280 teaser: blurred video fills the background, the real video in the middle,
    a big hook text on top and a 'watch the full story' line at the bottom."""
    top_col, band_col = colors
    ov = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    lines, f, size = _fit_text(d, hook_text, font_path, VW - 70, 86)
    y = 150
    for l in lines:
        tw = d.textlength(l, font=f)
        d.text(((VW - tw) / 2, y), l, font=f, fill=top_col + (255,), stroke_width=max(5, size // 12),
               stroke_fill=(0, 0, 0, 255))
        y += int(size * 1.3)
    cl, cf, cs = _fit_text(d, cta_text, font_path, VW - 110, 46, lines_max=1)
    tw = d.textlength(cl[0], font=cf)
    by = VH - 260
    d.rounded_rectangle([(VW - tw) / 2 - 30, by - 14, (VW + tw) / 2 + 30, by + cs * 1.35 + 10], radius=26,
                        fill=band_col + (240,), outline=(255, 255, 255, 255), width=3)
    d.text(((VW - tw) / 2, by), cl[0], font=cf, fill=(255, 255, 255, 255))
    png = os.path.join(workdir, "teaser_overlay.png")
    ov.save(png)
    dur = max(5.0, end - start)
    fc = (f"[0:v]split[a][b];[a]scale=-2:{VH},crop={VW}:{VH},boxblur=22:2,eq=brightness=-0.18[bg];"
          f"[b]scale={VW}:-2[fg];[bg][fg]overlay=0:(H-h)/2[v1];[v1][1:v]overlay=0:0,format=yuv420p[v]")
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
    fin = requests.post(f"{GRAPH}/{page}/video_reels", data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": description[:2000], "access_token": token}, timeout=120).json()
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
    r = requests.post(f"{YT}/playlistItems", headers=hdr, params={"part": "snippet"}, json={
        "snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}, timeout=30)
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
