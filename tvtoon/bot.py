"""THE HORROR BOT'S CARTOON (ANIM_MODE=tvtoon - the production default from 23 Nov 2026, the owner's decision:
"from now on the horror story comes out as a cartoon").

main.py makes the story, its voices (Gemini, with Chirp only as the approved fallback), the sound, subtitles,
thumbnail and uploads exactly as before. This module only replaces the PICTURES: every story scene (and the cold-open
hook) becomes a tvtoon cartoon scene, timed to the bot's own recorded lines:

  * the place, time of day, weather, cast, vehicles, seats, ghost disguise / reveal come from story.episode_from_story;
  * every spoken line is placed at the exact time it is heard in the bot's scene sound ('at'), with the bot's own
    clean line recording for the lip-sync - no voice is generated here, nothing is spoken twice;
  * a ghost's change happens just before the line that follows it in the story, so it is finished when it speaks;
  * the clip is encoded exactly like main.py's other clips (size, fps, codec, sound) so everything joins as before.

If anything fails for a scene, main.py makes that scene the classic way (nothing is lost)."""
import copy
import os
import subprocess

from tvtoon import characters as CH
from tvtoon import story as STY

_STATE = {}


def plan(story):
    """the episode plan of the whole story (cached for this run)"""
    key = (story.get("title"), len(story.get("scenes") or []))
    if _STATE.get("key") != key:
        _STATE["key"] = key
        _STATE["ep"] = STY.episode_from_story(story)      # (the characters made at night come from the library)
    return _STATE["ep"]


def _names(ep):
    """story speaker name (lower case) -> actor id"""
    return {str(k).lower(): v["actor"] for k, v in ep.get("cast", {}).items()}


def _setup_beats(base):
    """the beats of a scene that are not lines: sitting, riding, driving (all from the start, under the lines)"""
    out = []
    for b in base.get("beats", []):
        if "say" in b or "narrate" in b or "pause" in b or b.get("transform") or b.get("from_story"):
            continue                                       # (the story's own actions are placed on the line times)
        b = dict(b)
        b.pop("with_prev", None)
        b["at"] = 0.0
        if "drive_to" in b:
            b["background"] = True
        out.append(b)
    return out


def _transform_anchor(base):
    """{actor: ('before' | 'after', line text)} for the ghost's change in this story scene"""
    out = {}
    bs = base.get("beats", [])
    for i, b in enumerate(bs):
        if not b.get("transform"):
            continue
        nxt = next((x for x in bs[i + 1:] if x.get("say") and x.get("who") == b["who"]), None)
        prv = next((x for x in reversed(bs[:i]) if x.get("say") and x.get("who") == b["who"]), None)
        out[b["who"]] = ("before", nxt["say"]) if nxt else ("after", prv["say"]) if prv else ("before", None)
    return out


def part_spec(ep, si, lines, subs, line_wavs, dur, W, H, fps):
    """the tvtoon scene for one part of the bot's video. lines = the part's spoken lines (dicts with speaker, text,
    emotion), subs = [(start, length, is_narrator, text)] from the bot's scene sound, line_wavs = the clean line
    recordings, dur = the part's sound length"""
    base = ep["scenes"][max(0, min(si, len(ep["scenes"]) - 1))]
    spec = {"location": base["location"], "world": copy.deepcopy(base.get("world", {})), "cast": copy.deepcopy(base["cast"]),
            "vehicles": copy.deepcopy(base.get("vehicles", [])), "fps": int(fps), "size": [int(W), int(H)],
            "subtitles": False, "t_start": 0.0, "look": os.environ.get("TVTOON_LOOK") or ep.get("look") or "horror"}
    names = _names(ep)
    ids = {c["id"] for c in spec["cast"]}
    anchors = _transform_anchor(base)
    texts = [str(ln.get("text", "")).strip() for ln in lines]
    for actor, (mode, txt) in list(anchors.items()):          # a hook taken from after the change: already a ghost
        if txt in texts:
            continue
        order = [str(b.get("say", "")) for b in base.get("beats", []) if b.get("say")]
        pos_t = order.index(txt) if txt in order else -1
        first = next((order.index(x) for x in texts if x in order), None)
        if first is not None and pos_t >= 0 and (first > pos_t or (first == pos_t and mode == "after")):
            for c in spec["cast"]:
                if c["id"] == actor:
                    c.pop("disguise", None)
        anchors.pop(actor)
    beats = _setup_beats(base)
    from tvtoon import actions as AC                       # the story moves the characters, on the bot's line times
    dr = AC.Director(spec["cast"], AC.name_map(ep.get("cast", {})),
                     fixed=[b["who"] for b in beats if b.get("sit") or b.get("ride")],
                     still=base.get("location") == "boat" or (base.get("world", {}).get("kind") in ("palki", "hold")))
    dr.prepare(lines[:len(subs)], lambda ln_: (lambda a_: a_ if a_ in ids else None)(names.get(str(ln_.get("speaker", "")).lower())))
    changed = set()
    last = None
    end = 0.0
    for k, ln in enumerate(lines):
        if k >= len(subs):
            break
        st, du, nar, tx = subs[k]
        text = str(ln.get("text", "")).strip()
        actor = names.get(str(ln.get("speaker", "")).lower())
        wav = line_wavs[k] if k < len(line_wavs) and line_wavs[k] and os.path.exists(line_wavs[k]) else None
        for a, (mode, txt) in anchors.items():                 # the change, finished before this line
            if a not in changed and mode == "before" and txt == text:
                beats.append({"who": a, "transform": True, "at": max(0.0, st - 1.9), "background": True})
                changed.add(a)
        raw = str(ln.get("emotion") or "").lower()
        if actor in ids and not nar:
            spec_a = CH.get(actor)
            disguised = any(c["id"] == actor and c.get("disguise") for c in spec["cast"]) and actor not in changed
            is_ghost = spec_a.get("ghost") is not None and not disguised
            emo = (STY.GHOST_EMO.get(raw) if is_ghost else None) or STY.EMO.get(raw)
            to = last if last and last != actor else next((c["id"] for c in spec["cast"] if c["id"] != actor), None)
            b = {"who": actor, "say": text or tx, "to": to, "at": st}
            if wav:
                b["audio"] = wav
            items, g_, e_ = dr.line(ln, actor, to)
            emo = emo or (None if is_ghost else e_)
            if emo:
                b["emotion"] = emo
            if g_:
                b["gesture"] = g_
            beats.append(b)
            beats += AC.timed(items, st, du)
            last = actor
        else:
            b = {"narrate": text or tx, "at": st, "shot_type": "wide"}
            if wav:
                b["audio"] = wav
            beats.append(b)
            items, _g, _e = dr.line(ln, None)
            beats += AC.timed(items, st, du)
        end = max(end, st + du)
        for a, (mode, txt) in anchors.items():                 # ... or right after its only line
            if a not in changed and mode == "after" and txt == text:
                beats.append({"who": a, "transform": True, "at": st + du + 0.1, "background": True})
                changed.add(a)
    beats.append({"pause": max(0.3, dur - end), "at": end})
    spec["beats"] = beats
    return spec


def render_part(spec, audio, out, W, H, fps, sr, work_dir, log=print):
    """render the cartoon scene and encode it exactly like main.py's clips (the bot's own scene sound)"""
    from tvtoon import scene as SC
    raw = os.path.join(work_dir, os.path.basename(out).replace(".mp4", "_tvtoon.mp4"))
    _st, sc = SC.render(spec, raw, work_dir=os.path.join(work_dir, "_tvtoon_" + os.path.basename(out).replace(".mp4", "")),
                        log=lambda *a: None)
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio],
                             capture_output=True, text=True).stdout.strip() or 0)
    fol = None
    if os.environ.get("TVTOON_FOLEY") != "0":            # the footsteps, the door, the falls - exactly on the picture
        try:
            fol = sc.foley_wav(raw.replace(".mp4", "_foley.wav"), sr)
        except Exception:
            fol = None
    if fol:
        aud_in = ["-i", audio, "-i", fol, "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:normalize=0[a]",
                  "-map", "0:v", "-map", "[a]"]
    else:
        aud_in = ["-i", audio, "-map", "0:v", "-map", "1:a"]
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw] + aud_in +
                       ["-t", f"{d:.2f}", "-vf", f"scale={W}:{H},tpad=stop_mode=clone:stop_duration=30,format=yuv420p",
                        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "3500k",
                        "-bufsize", "7000k", "-c:a", "aac", "-b:a", "160k", "-ar", str(sr), "-ac", "2", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-600:])
    return d


def still(ep, si, out_jpg, W, H):
    """one picture of a story scene (its place, people, time of day) - used where main.py needs a picture of the
    scene (the title card, the hook's backup, teasers), so no picture service is needed for the scenes"""
    import cv2
    from tvtoon import scene as SC
    base = ep["scenes"][max(0, min(si, len(ep["scenes"]) - 1))]
    spec = {"location": base["location"], "world": copy.deepcopy(base.get("world", {})), "cast": copy.deepcopy(base["cast"]),
            "vehicles": copy.deepcopy(base.get("vehicles", [])), "size": [int(W), int(H)], "fps": 24, "subtitles": False,
            "look": os.environ.get("TVTOON_LOOK") or ep.get("look") or "horror",
            "beats": [dict(b, at=0.0) for b in _setup_beats(base)] + [{"pause": 2.5, "at": 0.0, "shot": "wide"}]}
    sc = SC.Scene(spec)
    t = 1.6
    f = 0.0
    while f < t:                                               # let the springs settle (turns, seats)
        for c in sc.order:
            sc.perf[c].state(f, sc)
        f += 1 / 24.0
    cv2.imwrite(out_jpg, sc.render_frame(t), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out_jpg
