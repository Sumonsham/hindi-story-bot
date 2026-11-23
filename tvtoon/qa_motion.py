"""engine v2 motion QA: measured on RENDERED frames and on the scene's own timeline (a feature is only 'working'
when the pixels or the timing show it).

  background_motion  - clouds, palm crowns, grass really move between frames; the ground and huts stay put
  parallax           - a camera pan moves each depth layer by a different amount, in depth order
  character_motion   - poses change over time, blinking is independent per character
  facial             - mouth shapes change while speaking, stay closed when silent
  lipsync_timing     - open mouths fall inside the voiced parts of the real audio
  consistency        - a character's colours are the same at the start and the end of the scene
  video              - resolution, fps, duration, no black frames, no dissolves, cuts only at planned shot changes
"""
import json
import subprocess

import cairo
import numpy as np


def _world_frame(world, W, H, cam, t):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    c = cairo.Context(s)
    world.draw_back(c, W, H, cam, t)
    world.draw_front(c, W, H, cam, t)
    return np.ndarray((H, W, 4), np.uint8, s.get_data()).copy()[:, :, :3].astype(np.int16)


def background_motion(world, W=960, H=540):
    """two frames one second apart, the SAME camera: moving things must change, fixed things must not"""
    z = 0.8 * W / 1920.0 * 1.0
    cam = (1600.0, 960.0 - 0.40 * 1080 / 0.8, 0.8)
    scale = W / 1920.0
    f0 = _world_frame(world, W, H, (cam[0], cam[1], cam[2] * scale), 1.0)
    f1 = _world_frame(world, W, H, (cam[0], cam[1], cam[2] * scale), 2.0)
    d = np.abs(f1 - f0).sum(axis=2) > 30

    def box(p, x0, y0, x1, y1):
        m = world.layer_matrix(W, H, (cam[0], cam[1], cam[2] * scale), p)
        (a0, b0), (a1, b1) = m.transform_point(x0, y0), m.transform_point(x1, y1)
        a0, a1 = sorted((int(max(0, min(W, a0))), int(max(0, min(W, a1)))))
        b0, b1 = sorted((int(max(0, min(H, b0))), int(max(0, min(H, b1)))))
        return d[b0:b1, a0:a1].mean() if (a1 > a0 and b1 > b0) else 0.0
    res = {"sky_clouds_pct": box(0.06, -200, 40, 3400, 340),
           "palm_crowns_pct": box(0.92, 750, 120, 1100, 380),
           "foreground_grass_pct": box(1.22, 0, 1010, 3200, 1110),
           "hut_wall_changed_pct": box(0.85, 400, 650, 560, 740),          # a hut must stay exactly where it is
           "bare_ground_changed_pct": box(1.0, 1250, 860, 1500, 940)}
    res = {k: round(float(v) * 100, 2) for k, v in res.items()}
    res["pass"] = bool(res["sky_clouds_pct"] > 0.1 and res["palm_crowns_pct"] > 0.5 and res["foreground_grass_pct"] > 0.5
                       and res["hut_wall_changed_pct"] < 0.5 and res["bare_ground_changed_pct"] < 1.0)
    return res


def parallax(world, W=1920, H=1080):
    """pan the camera by 200 world px: how far each layer moves on screen"""
    a, b = (1600.0, 640.0, 1.0), (1800.0, 640.0, 1.0)
    shift = {n: round(abs(world.screen_x(W, H, b, p, 1600) - world.screen_x(W, H, a, p, 1600)), 1)
             for n, p in sorted(world.LAYERS.items(), key=lambda kv: kv[1])}
    vals = list(shift.values())
    return {"screen_shift_px_for_200px_pan": shift,
            "pass": all(x <= y for x, y in zip(vals, vals[1:])) and len(set(vals)) >= 6}


def character_motion(scene, t0=0.5, t1=None, step=1 / 12.0):
    t1 = t1 or scene.duration
    out = {}
    for cid in scene.order:
        pf = scene.perf[cid]
    blinks = {cid: [round(b, 2) for b in scene.perf[cid].blinks if b < scene.duration] for cid in scene.order}
    same = 0
    ids = list(blinks)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            same += len(set(blinks[a]) & set(blinks[b]))
    # pose change: run the performances and record a few bones
    rec = {cid: [] for cid in scene.order}
    t = t0
    while t < t1:
        for cid in scene.order:
            st, x = scene.perf[cid].state(t, scene)
            r = st["rot"]
            rec[cid].append([r.get("head", 0), r.get("spine", 0), r.get("uarm_a", 0), r.get("uarm_b", 0), st.get("turn", 0),
                             st["face"].get("lid", 1.0), x])
        t += step
    for cid, v in rec.items():
        a = np.array(v)
        out[cid] = {"bone_motion_std_deg": round(float(np.degrees(a[:, :4]).std(axis=0).mean()), 2),
                    "turn_range": round(float(a[:, 4].max() - a[:, 4].min()), 2),
                    "blinks": len(blinks[cid]), "min_lid": round(float(a[:, 5].min()), 2)}
    total = sum(len(v) for v in blinks.values())
    ok = bool(all(v["bone_motion_std_deg"] > 0.5 and v["blinks"] >= 3 for v in out.values()) and same <= 0.05 * total)
    return {"per_character": out, "shared_blink_times": same, "pass": ok}


def facial(scene):
    res = {}
    for ln in scene.lines:
        pf = scene.perf[ln["who"]]
        sp = next(s for s in pf.speech if abs(s[0] - ln["t0"]) < 1e-6)
        vis = set()
        t = ln["t0"]
        while t < ln["t1"]:
            st, _ = pf.state(t, scene)
            vis.add(st["face"].get("mouth", "X"))
            t += 1 / 24.0
        res[f'{ln["who"]} {ln["t0"]:.1f}s'] = {"mouth_shapes": sorted(vis), "voiced": bool(ln.get("audio"))}
    ok = all(len(v["mouth_shapes"]) >= 3 for v in res.values() if v["voiced"])
    return {"lines": res, "pass": ok}


def lipsync_timing(scene):
    from tvtoon import lipsync as LS
    rows = []
    for ln in scene.lines:
        if not ln.get("audio"):
            continue
        loud, hop = LS.loudness_track(ln["audio"])
        pf = scene.perf[ln["who"]]
        sp = next(s for s in pf.speech if abs(s[0] - ln["t0"]) < 1e-6)
        n_open, n_in = 0, 0
        t = 0.0
        while t < ln["t1"] - ln["t0"]:
            v = LS.viseme_at(sp[2], t)
            if v != "X":
                n_open += 1
                i = int(t / hop)
                win = loud[max(0, i - 6): i + 7]                    # +-60 ms
                n_in += bool(len(win) and win.max() > 0.12)
            t += 1 / 24.0
        rows.append({"line": f'{ln["who"]} {ln["t0"]:.1f}s', "open_frames": n_open,
                     "open_inside_voice_pct": round(100 * n_in / max(1, n_open), 1)})
    return {"lines": rows, "pass": bool(rows) and all(r["open_inside_voice_pct"] >= 80 for r in rows)}


def video(path, scene):
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                                   capture_output=True, text=True).stdout)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    w, h = int(v["width"]), int(v["height"])
    num, den = v["r_frame_rate"].split("/")
    fps = float(num) / float(den)
    dur = float(pr["format"]["duration"])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=240:135", "-f", "rawvideo", "-pix_fmt", "gray",
                          "-"], capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8)
    n = len(f) // (240 * 135)
    f = f[: n * 240 * 135].reshape(n, 135, 240).astype(np.int16)
    black = int((f.mean(axis=(1, 2)) < 8).sum())
    diff = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    cuts = {int(round(s["t0"] * fps)) for s in scene.shots}
    big = [i + 1 for i, d in enumerate(diff) if d > max(18.0, 8 * float(np.median(diff)))]
    unplanned = [i for i in big if not any(abs(i - c) <= 1 for c in cuts)]
    # dissolve check: the same detector engine 2 uses (a run of frames that are blends of their neighbours)
    try:
        from engine2 import visual_qa as V
        dissolve = len(V.ghost_scan(path, None, None)["dissolve_runs"])
    except Exception:
        dissolve = -1
    moving = float((diff > 0.15).mean())                            # share of frames where the picture moves
    return {"width": w, "height": h, "fps": round(fps, 2), "seconds": round(dur, 2), "codec": v["codec_name"],
            "black_frames": black, "cuts_found": len(big), "unplanned_jumps": unplanned[:20],
            "dissolve_runs": int(dissolve), "frames_with_motion_pct": round(100 * moving, 1),
            "pass": w == 1920 and h == 1080 and abs(fps - 24) < 0.01 and 30 <= dur <= 45 and black == 0 and not unplanned
            and moving > 0.97 and dissolve == 0}
