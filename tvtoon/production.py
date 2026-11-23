"""production pipeline: Character Design -> Identity Lock -> Asset Generation -> Asset Validation -> Human Approval ->
Rigging -> Animation Testing -> Lip-sync Testing -> Scene Integration -> Rendering -> Final Export.

    python -m tvtoon.production sample [out_dir]     # the 6-category sample pack (resumes: finished files are kept)
    python -m tvtoon.production status               # the dashboard as text

Every stage has its own status and error. 'Human Approval' is read from tvtoon/approvals.json, which ONLY the owner
edits; nothing here ever writes an approval. Unapproved characters never go into the production library."""
import json
import os
import sys
import time
import traceback

from tvtoon import characters as CH

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APPROVALS = os.path.join(HERE, "approvals.json")
STAGES = ["design", "identity_lock", "asset_generation", "asset_validation", "human_approval", "rigging",
          "animation_test", "lipsync_test", "scene_integration", "rendering", "final_export"]

# lines with a matching recorded voice in this repo (men); the other lines get their voice from Gemini on GitHub
TEST_LINES = {
    "haripada": ("কেউ ব্রেক কষেনি?", "surprised"),
    "lumi_didi": ("বাপ্পা, তুমি কোথায় যাচ্ছ?", "neutral"),
    "nibaran_dadu": ("চুপ কিশোরী!", "angry"),
    "sarala_thakuma": ("আয় মা, একটু বোস আমার কাছে।", "happy"),
    "bappa": ("আমি মাঠে খেলতে যাচ্ছি।", "happy"),
    "mili": ("দিদি, আমিও যাব!", "happy"),
}


def approvals():
    try:
        return json.load(open(APPROVALS, encoding="utf-8"))
    except Exception:
        return {}


def approved(cid):
    ap = approvals()
    a = ap.get(cid.split("__")[0])
    st = a.get("status") if isinstance(a, dict) else a
    if st == "REJECTED":
        return False
    if st == "USER_APPROVED":
        return True
    allv = ap.get("_all")                                    # the owner's standing approval (23 Nov 2026)
    return (allv.get("status") if isinstance(allv, dict) else allv) == "USER_APPROVED"


def _need(path, force=False):
    return force or not (os.path.exists(path) and os.path.getsize(path) > 0)


def test_clip_spec(cid, size=(1920, 1080)):
    """one character: blink + breathing, the four emotions in close-up, a line of dialogue, waving, explaining,
    a walk away and back (hair and clothes swing), children also run"""
    spec = CH.get(cid)
    kid = spec["category"] in ("boy", "girl")
    text, emo = TEST_LINES[cid]
    beats = [{"pause": 1.6, "shot": "wide"},
             {"who": cid, "emotion": "happy", "sec": 1.6, "shot": "close"},
             {"who": cid, "emotion": "sad", "sec": 1.6, "shot": "close"},
             {"who": cid, "emotion": "angry", "sec": 1.6, "shot": "close"},
             {"who": cid, "emotion": "surprised", "sec": 1.6, "shot": "close"},
             {"who": cid, "say": text, "emotion": emo},
             {"who": cid, "gesture": "wave", "sec": 2.2, "shot": "wide"},
             {"who": cid, "gesture": "explain_both", "sec": 1.8, "shot": "wide"},
             {"who": cid, "walk_to": 2150, "gait": "walk"},
             {"who": cid, "walk_to": 1450, "gait": "run" if kid else "walk"},
             {"who": cid, "emotion": "laughing", "sec": 1.8, "shot": "close"},
             {"pause": 0.8, "shot": "wide"}]
    return {"location": "village_courtyard", "fps": 24, "size": list(size), "subtitles": True,
            "cast": [{"id": cid, "x": 1450}], "beats": beats}


def sample_scene_spec(aspect="16:9"):
    """all six sample characters in one courtyard: dialogue, turn-taking, reactions, a run, sitting down"""
    return {"location": "village_courtyard", "fps": 24, "aspect": aspect, "subtitles": True,
            "cast": [{"id": "lumi_didi", "x": 900}, {"id": "haripada", "x": 1220}, {"id": "bappa", "x": 1500},
                     {"id": "mili", "x": 1700}, {"id": "nibaran_dadu", "x": 1980}, {"id": "sarala_thakuma", "x": 2280}],
            "beats": [{"pause": 1.4, "shot": "wide"},
                      {"who": "lumi_didi", "say": "বাপ্পা, তুমি কোথায় যাচ্ছ?", "to": "bappa"},
                      {"who": "bappa", "say": "আমি মাঠে খেলতে যাচ্ছি।", "to": "lumi_didi", "emotion": "happy"},
                      {"who": "mili", "say": "দিদি, আমিও যাব!", "to": "lumi_didi", "emotion": "happy"},
                      {"who": "haripada", "say": "কেউ ব্রেক কষেনি?", "to": "nibaran_dadu", "emotion": "surprised"},
                      {"who": "nibaran_dadu", "say": "চুপ কিশোরী!", "to": "haripada", "emotion": "angry"},
                      {"who": "sarala_thakuma", "emotion": "laughing", "sec": 1.6, "shot": "close"},
                      {"who": "nibaran_dadu", "sit": True},
                      {"who": "bappa", "walk_to": 2700, "gait": "run"},
                      {"who": "mili", "gesture": "wave", "sec": 2.0, "with_prev": True},
                      {"who": "sarala_thakuma", "say": "আয় মা, একটু বোস আমার কাছে।", "to": "mili", "emotion": "happy"},
                      {"who": "haripada", "gesture": "shrug", "sec": 1.6, "shot": "wide"},
                      {"pause": 1.0, "shot": "wide"}]}


def build_sample(out=None, log=print, force=False, render_scene=True):
    from tvtoon import qa as QA
    from tvtoon import scene as SC
    from tvtoon import sheets as SH
    from tvtoon import voices as VO
    out = out or os.path.join(ROOT, "work", "tvtoon_sample")
    os.makedirs(out, exist_ok=True)
    stp = os.path.join(out, "status.json")
    status = json.load(open(stp, encoding="utf-8")) if os.path.exists(stp) and not force else {}
    status.setdefault("characters", {})

    def save():
        status["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(stp, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=1, default=float)

    def stage(cid, name, fn):
        row = status["characters"].setdefault(cid, {"stages": {}})["stages"]
        try:
            r = fn()
            row[name] = {"status": "DONE" if r is not False else "FAILED"}
            return r
        except Exception as e:                                         # one failure never stops the pack
            row[name] = {"status": "ERROR", "error": f"{type(e).__name__}: {str(e)[:300]}"}
            log(f"  {cid} {name}: ERROR {e}")
            traceback.print_exc()
            return None
        finally:
            save()

    for cid in CH.samples():
        d = os.path.join(out, cid)
        os.makedirs(d, exist_ok=True)
        log(f"== {cid}")
        stage(cid, "design", lambda: CH.get(cid))
        stage(cid, "identity_lock", lambda: SH.identity_sheet(cid, os.path.join(d, "identity_sheet.png"))
              if _need(os.path.join(d, "identity_sheet.png"), force) else True)

        def assets():
            if _need(os.path.join(d, "poses.png"), force):
                SH.pose_sheet(cid, os.path.join(d, "poses.png"))
            if _need(os.path.join(d, "face_sheet.png"), force):
                SH.face_sheet(cid, os.path.join(d, "face_sheet.png"))
            if _need(os.path.join(d, "layers", f"{cid}_rig.json"), force):
                SH.export_layers(cid, os.path.join(d, "layers"))
            return True
        stage(cid, "asset_generation", assets)
        q = stage(cid, "asset_validation", lambda: QA.validate(cid, os.path.join(d, "layers")))
        if q is not None:
            status["characters"][cid]["qa"] = q
            status["characters"][cid]["stages"]["asset_validation"]["status"] = "PASS" if q["pass"] else "FAIL"
        status["characters"][cid]["stages"]["human_approval"] = {
            "status": "USER_APPROVED" if approved(cid) else "WAITING_FOR_OWNER"}
        stage(cid, "rigging", lambda: os.path.exists(os.path.join(d, "layers", f"{cid}_rig.json")))
        clip = os.path.join(d, f"{cid}_test_clip.mp4")

        def anim():
            if _need(clip, force):
                st, sc = SC.render(test_clip_spec(cid), clip, work_dir=os.path.join(out, "_work", cid), log=log)
            else:
                st = json.load(open(os.path.splitext(clip)[0] + "_status.json", encoding="utf-8"))
            status["characters"][cid]["test_clip"] = {"file": clip, "seconds": round(st["duration"], 2),
                                                       "lines": st.get("lines")}
            return True
        stage(cid, "animation_test", anim)
        ln = (status["characters"][cid].get("test_clip") or {}).get("lines") or []
        voiced = [x for x in ln if x.get("voice") and not str(x["voice"]).startswith("NO VOICE")]
        status["characters"][cid]["stages"]["lipsync_test"] = {
            "status": "DONE" if voiced else "NOT_TESTED",
            "detail": (voiced[0].get("lipsync") if voiced else
                       "no voice for this character in this run (female / child voices come from the free Gemini "
                       "voice on GitHub)"), "voice": (voiced[0].get("voice") if voiced else None)}
        save()
    if render_scene:
        for asp, nm in (("16:9", "sample_scene_16x9.mp4"), ("9:16", "sample_scene_9x16.mp4")):
            f = os.path.join(out, nm)
            try:
                if _need(f, force):
                    st, sc = SC.render(sample_scene_spec(asp), f, work_dir=os.path.join(out, "_work", "scene_" + asp.replace(":", "x")),
                                       log=log)
                status.setdefault("scene", {})[asp] = {"file": f, "status": "DONE"}
            except Exception as e:
                status.setdefault("scene", {})[asp] = {"file": f, "status": "ERROR", "error": str(e)[:300]}
                traceback.print_exc()
            save()
        for cid in CH.samples():
            status["characters"][cid]["stages"]["scene_integration"] = {
                "status": status.get("scene", {}).get("16:9", {}).get("status", "NOT_TESTED")}
            status["characters"][cid]["stages"]["rendering"] = {"status": "DONE" if os.path.exists(
                os.path.join(out, cid, f"{cid}_test_clip.mp4")) else "NOT_DONE"}
            status["characters"][cid]["stages"]["final_export"] = {
                "status": "BLOCKED - waits for the owner's approval" if not approved(cid) else "READY"}
    for cid in CH.samples():                                           # lip-sync demonstrations (voiced lines)
        try:
            r = lipsync_demo(cid, os.path.join(out, "lipsync"), log=log)
        except Exception as e:
            r = {"character": cid, "status": "ERROR", "error": str(e)[:300]}
        status.setdefault("lipsync_demo", {})[cid] = r
        save()
    status["voices"] = VO.report()
    status["pending_characters"] = {k: {"category": v[0], "name_bn": v[1], "status": "WAITING - designed after the "
                                        "owner approves the samples"} for k, v in CH.PENDING.items()}
    save()
    dashboard(status, os.path.join(out, "dashboard.json"))
    return status


def v2_test_spec(aspect="16:9"):
    """ENGINE V2 TEST (30-45 s): animated village (clouds, wind, birds, smoke, pond, foreground grass, the light
    sinking toward dusk), an entrance with a tracking camera, a two-person conversation in Bengali with real voices,
    shot / reverse shot, close-up reactions, gestures, characters at different depths listening and reacting, a
    child running out of the scene, a laugh, an eased pull-out to the wide shot."""
    return {"location": "village_courtyard", "fps": 24, "aspect": aspect, "subtitles": True,
            "world": {"wind": 0.55, "hours": [[0.0, 16.2], [24.0, 17.4], [42.0, 18.7]], "seed": 3},
            "cast": [{"id": "haripada", "x": 250}, {"id": "nibaran_dadu", "x": 1560},
                     {"id": "sarala_thakuma", "x": 930, "z": 0.75}, {"id": "lumi_didi", "x": 2260, "z": 0.6},
                     {"id": "mili", "x": 2470, "z": 0.45}, {"id": "bappa", "x": 2080, "z": 0.3}],
            "beats": [{"pause": 3.2},
                      {"who": "nibaran_dadu", "sit": True, "with_prev": True},
                      {"who": "haripada", "walk_to": 1180},
                      {"who": "haripada", "say": "কেউ ব্রেক কষেনি?", "to": "nibaran_dadu", "emotion": "surprised"},
                      {"who": "nibaran_dadu", "say": "চুপ কিশোরী!", "to": "haripada", "emotion": "angry"},
                      {"who": "nibaran_dadu", "say": "একটি টু শব্দ কোরো না।", "to": "haripada", "gesture": "explain"},
                      {"who": "haripada", "emotion": "scared", "sec": 1.4, "shot": "ecu"},
                      {"who": "nibaran_dadu", "say": "ওঁর নাম মুখে আনলে উনি টের পেয়ে যান।", "to": "haripada",
                       "gesture": "point_up"},
                      {"who": "haripada", "say": "আমার দিকে তাকা!", "to": "nibaran_dadu", "emotion": "scared"},
                      {"who": "nibaran_dadu", "say": "বোকামি কোরো না কিশোরী!", "to": "haripada", "emotion": "angry",
                       "no_reaction": True},
                      {"who": "sarala_thakuma", "emotion": "laughing", "sec": 1.8, "shot": "medium"},
                      {"who": "bappa", "walk_to": 3550, "gait": "run"},
                      {"who": "mili", "gesture": "wave", "sec": 2.0, "with_prev": True},
                      {"who": "lumi_didi", "emotion": "crying", "sec": 2.0, "shot": "close"},
                      {"who": "haripada", "gesture": "shrug", "sec": 1.6, "shot": "two"},
                      {"pause": 2.4}]}


# ---------------------------------------------------------------------------------------------- episodes
def render_episode(ep, out_path, work_dir=None, log=print):
    """an episode = several scenes (each its own location, cast, vehicles, time of day), joined by a fade through
    black (the two scenes are never mixed: the first goes fully dark before the next appears) or a hard cut"""
    import subprocess
    from tvtoon import scene as SC
    work_dir = work_dir or os.path.splitext(out_path)[0] + "_work"
    os.makedirs(work_dir, exist_ok=True)
    clips, durs, report = [], [], {"scenes": []}
    for i, sc_spec in enumerate(ep["scenes"]):
        f = os.path.join(work_dir, f"scene_{i + 1:02d}_{sc_spec.get('location', 'x')}.mp4")
        st, sc = SC.render(sc_spec, f, work_dir=os.path.join(work_dir, f"_s{i + 1:02d}"), log=log)
        clips.append(f)
        durs.append(st["duration"])
        report["scenes"].append({"file": f, "location": sc_spec.get("location"), "seconds": round(st["duration"], 2),
                                 "lines": [{k: x.get(k) for k in ("who", "text", "voice")} for x in sc.lines]})
        log(f"  scene {i + 1}/{len(ep['scenes'])} ({sc_spec.get('location')}) {st['duration']:.1f}s")
    fd = float(ep.get("fade", 0.6))
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    vf, af, off = [], [], 0.0
    vl, al = "[0:v]", "[0:a]"
    for i in range(1, len(clips)):
        off += durs[i - 1] - fd
        vf.append(f"{vl}[{i}:v]xfade=transition=fadeblack:duration={fd}:offset={off:.3f}[v{i}]")
        af.append(f"{al}[{i}:a]acrossfade=d={fd}[a{i}]")
        vl, al = f"[v{i}]", f"[a{i}]"
    if len(clips) == 1:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clips[0], "-c", "copy", out_path], check=True)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex", ";".join(vf + af), "-map", vl, "-map", al,
                                                                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                                                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                                                                   "-movflags", "+faststart", out_path], check=True)
    report["out"] = out_path
    report["seconds"] = round(sum(durs) - fd * (len(durs) - 1), 2)
    with open(os.path.splitext(out_path)[0] + "_episode.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=float)
    return report


def horror_episode_spec(aspect="16:9"):
    """'রাতের শর্টকাট' - a test horror episode across 7 locations with the horror cast, vehicles and ghosts"""
    base = {"fps": 24, "aspect": aspect, "subtitles": True}
    S = []
    S.append(dict(base, location="city_street", world={"hours": [[0, 18.0], [9, 18.5]], "wind": 0.3},
                  cast=[{"id": "abhishek", "x": 900, "z": 0.95}],
                  vehicles=[{"id": "tram", "kind": "tram", "x": -1400, "z": 0.45}, {"id": "bus", "kind": "bus", "x": 4600, "z": 0.2,
                                                                                    "facing": -1},
                            {"id": "auto", "kind": "auto", "x": -900, "z": 0.05}, {"id": "toto", "kind": "toto", "x": 4300, "z": 0.1}],
                  beats=[{"pause": 2.0}, {"vehicle": "tram", "drive_to": 4600, "sec": 10.0, "with_prev": True},
                         {"vehicle": "bus", "drive_to": -1600, "sec": 6.0, "with_prev": True, "shot": "wide"},
                         {"who": "abhishek", "walk_to": 1700},
                         {"vehicle": "auto", "drive_to": 4400, "sec": 3.5, "with_prev": True},
                         {"vehicle": "toto", "drive_to": -800, "sec": 5.0, "with_prev": True},
                         {"pause": 1.0}]))
    S.append(dict(base, location="station", world={"hours": [[0, 20.5]], "signal": [[0, "red"], [7.0, "green"]]},
                  cast=[{"id": "ramu_chowkidar", "x": 1250, "z": 0.1}, {"id": "abhishek", "x": 1750, "z": 0.0}],
                  vehicles=[{"id": "train", "kind": "train", "x": -5200, "cars": 3, "lane": "tracks"}],
                  beats=[{"pause": 0.6}, {"vehicle": "train", "drive_to": 1600, "sec": 5.5},
                         {"who": "ramu_chowkidar", "gesture": "point", "sec": 1.8, "shot": "medium"},
                         {"who": "abhishek", "emotion": "happy", "sec": 1.2, "shot": "close"},
                         {"vehicle": "train", "drive_to": 9000, "sec": 6.0}, {"pause": 0.6}]))
    S.append(dict(base, location="village_road", world={"hours": [[0, 17.6], [12, 18.3]], "wind": 0.5},
                  cast=[{"id": "abhishek", "x": 1200, "z": 0.05}, {"id": "sayan", "x": 1500, "z": 0.05},
                        {"id": "bhattacharya", "x": -400, "z": 0.25}],
                  vehicles=[{"id": "bike", "kind": "bike", "x": 1350, "z": 0.05}, {"id": "cycle", "kind": "cycle", "x": -400, "z": 0.25}],
                  beats=[{"pause": 1.0},
                         {"who": "bhattacharya", "ride": "cycle"},
                         {"vehicle": "cycle", "drive_to": 4200, "sec": 7.0, "with_prev": True, "shot": "wide"},
                         {"who": "abhishek", "say": "চল সায়ন, হেলমেটের স্ট্র্যাপটা বেঁধে নে ঝটপট।", "to": "sayan"},
                         {"who": "sayan", "emotion": "scared", "sec": 1.4},
                         {"who": "abhishek", "ride": "bike", "seat": 0}, {"who": "sayan", "ride": "bike", "seat": 1, "with_prev": True},
                         {"vehicle": "bike", "drive_to": 4600, "sec": 4.0}]))
    S.append(dict(base, location="bansh_bon", world={"hours": [[0, 21.0]], "wind": 0.6},
                  cast=[{"id": "abhishek", "x": -600, "z": 0.05}, {"id": "sayan", "x": -600, "z": 0.05},
                        {"id": "petni", "x": 2250, "z": 0.45}],
                  vehicles=[{"id": "bike", "kind": "bike", "x": -700, "z": 0.05}],
                  beats=[{"who": "abhishek", "ride": "bike", "seat": 0}, {"who": "sayan", "ride": "bike", "seat": 1, "with_prev": True},
                         {"vehicle": "bike", "drive_to": 1450, "sec": 4.0},
                         {"who": "abhishek", "get_off": True}, {"who": "sayan", "get_off": True, "with_prev": True},
                         {"who": "petni", "emotion": "laughing", "sec": 1.8, "shot": "close"},
                         {"who": "abhishek", "say": "কেউ ব্রেক কষেনি?", "to": "sayan", "emotion": "surprised"},
                         {"who": "sayan", "emotion": "scared", "sec": 1.2, "shot": "ecu"},
                         {"who": "abhishek", "say": "আমার দিকে তাকা!", "to": "sayan", "emotion": "scared"},
                         {"who": "petni", "walk_to": 1900, "with_prev": False}, {"pause": 0.8}]))
    S.append(dict(base, location="shmashan", world={"hours": [[0, 21.5]], "wind": 0.45},
                  cast=[{"id": "ojha", "x": 1500, "z": 0.0}, {"id": "kishori", "x": 1180, "z": 0.05},
                        {"id": "shakchunni", "x": 2500, "z": 0.6}, {"id": "brahmadaitya", "x": 800, "z": 0.7}],
                  beats=[{"pause": 1.6},
                         {"who": "ojha", "say": "চুপ কিশোরী!", "to": "kishori", "emotion": "angry"},
                         {"who": "ojha", "say": "একটি টু শব্দ কোরো না।", "to": "kishori"},
                         {"who": "shakchunni", "emotion": "angry", "sec": 1.4, "shot": "medium"},
                         {"who": "ojha", "say": "ওঁর নাম মুখে আনলে উনি টের পেয়ে যান।", "to": "kishori", "gesture": "point_up"},
                         {"who": "kishori", "emotion": "scared", "sec": 1.2, "shot": "close"},
                         {"who": "ojha", "say": "বোকামি কোরো না কিশোরী!", "to": "kishori", "emotion": "angry", "no_reaction": True},
                         {"narrate": "এক পলকে সব শান্ত।", "shot_type": "wide"}, {"pause": 0.6}]))
    S.append(dict(base, location="pukur_ghat", world={"hours": [[0, 20.8]]},
                  cast=[{"id": "riya", "x": 1300, "z": 0.0}, {"id": "mechho_bhoot", "x": 1800, "z": 0.3}],
                  beats=[{"pause": 1.4}, {"who": "mechho_bhoot", "walk_to": 1600},
                         {"who": "riya", "emotion": "surprised", "sec": 1.4, "shot": "close"},
                         {"who": "mechho_bhoot", "emotion": "happy", "sec": 1.2, "shot": "medium"}, {"pause": 0.6}]))
    S.append(dict(base, location="zamindar_bari", world={"hours": [[0, 21.8]], "lamp_off_at": 4.2},
                  cast=[{"id": "parul", "x": 1350, "z": 0.0}, {"id": "mokkhoda", "x": 1700, "z": 0.1}],
                  beats=[{"pause": 1.0},
                         {"narrate": "একটা দীর্ঘশ্বাসের শব্দে কুটিরের প্রদীপটা দপ করে নিভে গেল।", "shot_type": "wide"},
                         {"who": "parul", "emotion": "scared", "sec": 1.4, "shot": "close"},
                         {"who": "mokkhoda", "emotion": "crying", "sec": 1.6, "shot": "close"}, {"pause": 1.4}]))
    return {"title": "রাতের শর্টকাট", "fade": 0.6, "scenes": S}


def travel_episode_spec(aspect="16:9"):
    """'রাতের যাত্রা' - the travel test (23 Nov 2026): side-view walking and looking back, a toto ride at night with
    the passengers sitting in it, a cycle ride, faces in the windows of a night bus, talking face to face inside the
    bus, a Kolkata tram at dusk and a night train compartment whose lights fail."""
    S = lambda **k: dict({"fps": 24, "aspect": aspect, "subtitles": True}, **k)
    return {"title": "রাতের যাত্রা", "fade": 0.6, "scenes": [
        S(location="village_road", world={"hours": [[0, 18.4]], "wind": 0.6},
          cast=[{"id": "abhishek", "x": 700}, {"id": "riya", "x": 2300, "facing": "left"}],
          beats=[{"pause": 1.2}, {"who": "abhishek", "walk_to": 1850},
                 {"who": "abhishek", "say": "রিয়া, সন্ধে হয়ে এল। শেষ টোটোটা এখনই আসবে।", "to": "riya"},
                 {"who": "riya", "look_back": 1.8},
                 {"who": "riya", "say": "পেছনে কে যেন দাঁড়িয়ে ছিল... এখন আর নেই।", "to": "abhishek", "emotion": "scared"},
                 {"pause": 0.8}]),
        S(location="village_road", world={"hours": [[0, 21.5]], "wind": 0.5},
          cast=[{"id": "ramu_chowkidar", "x": -600, "name_bn": "টোটোওয়ালা"}, {"id": "abhishek", "x": -600}, {"id": "riya", "x": -600}],
          vehicles=[{"id": "toto", "kind": "toto", "x": -600}],
          beats=[{"who": "ramu_chowkidar", "ride": "toto", "seat": 0}, {"who": "abhishek", "ride": "toto", "seat": 1, "with_prev": True},
                 {"who": "riya", "ride": "toto", "seat": 2, "with_prev": True},
                 {"vehicle": "toto", "drive_to": 3700, "sec": "end", "background": True, "shot": {"type": "track", "who": "toto"}},
                 {"pause": 2.5},
                 {"who": "ramu_chowkidar", "say": "এই রাস্তায় রাতে কেউ আসে না, বাবু।", "to": "abhishek"},
                 {"who": "abhishek", "say": "কেন? কী আছে এখানে?", "to": "ramu_chowkidar", "emotion": "surprised"},
                 {"pause": 1.5, "shot": {"type": "track", "who": "toto"}}]),
        S(location="village_road", world={"hours": [[0, 21.0]], "wind": 0.4},
          cast=[{"id": "sayan", "x": -500}], vehicles=[{"id": "cyc", "kind": "cycle", "x": -500}],
          beats=[{"who": "sayan", "ride": "cyc"}, {"vehicle": "cyc", "drive_to": 3600, "sec": 7.0, "shot": {"type": "track", "who": "cyc"}},
                 {"narrate": "সেই রাতে সায়ন সাইকেলে বাড়ি ফিরছিল।", "with_prev": True}]),
        S(location="city_street", world={"hours": [[0, 20.5]]},
          cast=[{"id": "parul", "x": 0}, {"id": "sayan", "x": 0}], vehicles=[{"id": "bus", "kind": "bus", "x": -1500}],
          beats=[{"who": "parul", "ride": "bus", "seat": 1}, {"who": "sayan", "ride": "bus", "seat": 3, "with_prev": True},
                 {"vehicle": "bus", "drive_to": 4800, "sec": 8.0, "shot": {"type": "track", "who": "bus"}}]),
        S(location="bus_inside", world={"hours": [[0, 20.5]], "outside": "city"},
          cast=[{"id": "parul", "x": 1250}, {"id": "sayan", "x": 1950}],
          beats=[{"who": "parul", "sit": True, "prop": False, "already": True, "side": True},
                 {"who": "sayan", "sit": True, "prop": False, "already": True, "side": True, "with_prev": True},
                 {"pause": 1.0},
                 {"who": "parul", "say": "সামনের স্টপে নামব। জানলার বাইরে দেখো তো।", "to": "sayan"},
                 {"who": "sayan", "look_back": 1.8},
                 {"who": "sayan", "say": "একটা সাদা শাড়ি... বাসের পেছনে দৌড়চ্ছে!", "to": "parul", "emotion": "scared"},
                 {"pause": 0.8}]),
        S(location="tram_inside", world={"hours": [[0, 18.3]]},
          cast=[{"id": "bhattacharya", "x": 1250}, {"id": "mokkhoda", "x": 1950}],
          beats=[{"who": "bhattacharya", "sit": True, "prop": False, "already": True, "side": True},
                 {"who": "mokkhoda", "sit": True, "prop": False, "already": True, "side": True, "with_prev": True},
                 {"pause": 1.0},
                 {"who": "bhattacharya", "say": "কলকাতার ট্রাম, কত পুরনো স্মৃতি।", "to": "mokkhoda", "emotion": "happy"},
                 {"who": "mokkhoda", "say": "সন্ধে নামছে, তাড়াতাড়ি বাড়ি চলো।", "to": "bhattacharya"},
                 {"pause": 0.8}]),
        S(location="train_inside", world={"hours": [[0, 22.5]], "flicker": [[6.5, 8.0]]},
          cast=[{"id": "abhishek", "x": 1250}, {"id": "petni", "x": 1950, "name_bn": "অচেনা মহিলা"}],
          beats=[{"who": "abhishek", "sit": True, "prop": False, "already": True, "side": True},
                 {"who": "petni", "sit": True, "prop": False, "already": True, "side": True, "with_prev": True},
                 {"pause": 1.2},
                 {"who": "abhishek", "say": "আপনি কোন স্টেশনে নামবেন?", "to": "petni"},
                 {"who": "petni", "say": "যেখানে তুমি নামবে... সেখানেই।", "to": "abhishek", "emotion": "angry"},
                 {"pause": 2.0, "shot": "wide"},
                 {"who": "abhishek", "emotion": "scared", "sec": 1.8}]),
    ]}


def reveal_episode_spec(aspect="16:9"):
    """'অচেনা মেয়েটি' - the ghost-reveal test (23 Nov 2026): the ghost first comes as an ordinary young woman, sits in
    the train opposite the hero, and in front of him the disguise falls: the lights fail, the two forms flash in
    turn, a cold flash, and the petni rises off her seat; he is struck with fear."""
    S = lambda **k: dict({"fps": 24, "aspect": aspect, "subtitles": True}, **k)
    return {"title": "অচেনা মেয়েটি", "fade": 0.6, "scenes": [
        S(location="station", world={"hours": [[0, 21.5]]},
          cast=[{"id": "abhishek", "x": 1250}, {"id": "petni", "x": 1950, "disguise": True, "name_bn": "অচেনা মেয়েটি", "facing": "left"}],
          vehicles=[{"id": "train", "kind": "train", "x": -5200, "cars": 3, "lane": "tracks"}],
          beats=[{"pause": 1.2}, {"vehicle": "train", "drive_to": 1600, "sec": 5.0, "with_prev": True},
                 {"who": "petni", "say": "দাদা, এই ট্রেনটা কি নিশিপুর যাবে?", "to": "abhishek"},
                 {"who": "abhishek", "say": "হ্যাঁ, আমিও ওখানেই যাচ্ছি। চলুন।", "to": "petni", "emotion": "happy"},
                 {"pause": 0.8}]),
        S(location="train_inside", world={"hours": [[0, 22.0]]},
          cast=[{"id": "abhishek", "x": 1250}, {"id": "petni", "x": 1950, "disguise": True, "name_bn": "অচেনা মেয়েটি"}],
          beats=[{"who": "abhishek", "sit": True, "prop": False, "already": True, "side": True},
                 {"who": "petni", "sit": True, "prop": False, "already": True, "side": True, "with_prev": True},
                 {"pause": 1.2},
                 {"who": "abhishek", "say": "নিশিপুরে আপনার কে থাকে?", "to": "petni"},
                 {"who": "petni", "say": "কেউ না... কুড়ি বছর আগে এই ট্রেনেই তো আমি...", "to": "abhishek", "emotion": "sad"},
                 {"who": "petni", "transform": True},
                 {"who": "petni", "say": "আর বাড়ি ফিরতে পারিনি!", "to": "abhishek", "emotion": "angry"},
                 {"pause": 1.5, "shot": "wide"}]),
    ]}


def lipsync_demo(cid, out_dir, log=print):
    """a close-up of one spoken line + a strip: every mouth change with its time (from the REAL audio)"""
    import cairo
    import numpy as np
    from tvtoon import lipsync as LS
    from tvtoon import puppet as PP
    from tvtoon import scene as SC
    from tvtoon import sheets as SH
    from tvtoon import voices as VO
    text, emo = TEST_LINES[cid]
    wav, how = VO.line(cid, text, emo, log=log)
    if not wav:
        return {"character": cid, "status": "NOT_TESTED", "why": how}
    os.makedirs(out_dir, exist_ok=True)
    ev, info = LS.align(wav, text)
    pp = PP.Puppet(CH.get(cid))
    sc_ = 150.0 / pp.P["head_h"]
    n = len(ev)
    cw, chh = 150, 210
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, max(1, n) * cw + 20, chh + 90)
    ctx = cairo.Context(surf)
    ctx.set_source_rgb(0.97, 0.95, 0.91)
    ctx.paint()
    for i, (t, v) in enumerate(ev):
        st = SH.still_state(cid, pp, mouth=v)
        ctx.save()
        ctx.rectangle(10 + i * cw, 10, cw - 6, chh)
        ctx.clip()
        SH.draw_still(ctx, pp, st, 10 + i * cw + cw / 2, 22 + pp.P["H"] * sc_, sc_)
        ctx.restore()
        SH._label(ctx, f"{t:.2f}s", 10 + i * cw + cw / 2, chh + 40, 18)
        SH._label(ctx, v, 10 + i * cw + cw / 2, chh + 68, 20, (0.6, 0.15, 0.1))
    strip = os.path.join(out_dir, f"{cid}_lipsync_strip.png")
    surf.write_to_png(strip)
    clip = os.path.join(out_dir, f"{cid}_lipsync_closeup.mp4")
    spec = {"location": "village_courtyard", "fps": 24, "size": [1920, 1080], "subtitles": True,
            "cast": [{"id": cid, "x": 1450}],
            "beats": [{"pause": 0.6, "shot": "close"}, {"who": cid, "say": text, "emotion": emo, "shot": "close"},
                      {"pause": 0.8, "shot": "close"}]}
    SC.render(spec, clip, work_dir=os.path.join(out_dir, "_work_" + cid), log=lambda *a: None)
    return {"character": cid, "status": "DONE", "voice": how, "alignment": info, "mouth_changes": len(ev),
            "visemes_used": sorted(set(v for _t, v in ev)), "strip": strip, "clip": clip}


def dashboard(status, path=None):
    rows = []
    for cid, r in status.get("characters", {}).items():
        st = r.get("stages", {})
        done = sum(1 for s in STAGES if str(st.get(s, {}).get("status", "")).startswith(("DONE", "PASS", "USER_APPROVED")))
        spec = CH.get(cid)
        rows.append({"id": cid, "name_bn": spec["name_bn"], "category": spec["category"],
                     "asset_completion_pct": round(100 * done / len(STAGES)),
                     "validation": st.get("asset_validation", {}).get("status"),
                     "approval": st.get("human_approval", {}).get("status"),
                     "rigging": st.get("rigging", {}).get("status"),
                     "animation_test": st.get("animation_test", {}).get("status"),
                     "lipsync_test": st.get("lipsync_test", {}).get("status"),
                     "production_ready": approved(cid) and st.get("asset_validation", {}).get("status") == "PASS"})
    for cid, r in status.get("pending_characters", {}).items():
        rows.append({"id": cid, "name_bn": r["name_bn"], "category": r["category"], "asset_completion_pct": 0,
                     "approval": "NOT_STARTED", "production_ready": False})
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    return rows


def v2_test(out=None, log=print, portrait=True):
    """render the engine-v2 test story (16:9, and 9:16) and measure it (tvtoon/qa_motion.py)"""
    from tvtoon import qa_motion as Q
    from tvtoon import scene as SC
    from tvtoon import voices as VO
    from tvtoon import world as WD
    out = out or os.path.join(ROOT, "work", "tvtoon_v2_test")
    os.makedirs(out, exist_ok=True)
    rep = {"voice_engine": VO.engine(), "files": {}, "qa": {}}
    v = os.path.join(out, "tv_cartoon_v2_test_16x9.mp4")
    st, sc = SC.render(v2_test_spec("16:9"), v, work_dir=os.path.join(out, "_work_16x9"), log=log)
    rep["files"]["video_16x9"] = v
    rep["lines"] = [{k: x.get(k) for k in ("who", "text", "voice", "emotion")} for x in sc.lines]
    if portrait:
        v9 = os.path.join(out, "tv_cartoon_v2_test_9x16.mp4")
        SC.render(v2_test_spec("9:16"), v9, work_dir=os.path.join(out, "_work_9x16"), log=log)
        rep["files"]["video_9x16"] = v9
    w = WD.World(v2_test_spec()["world"])
    rep["qa"]["background_motion"] = Q.background_motion(w)
    rep["qa"]["parallax"] = Q.parallax(w)
    rep["qa"]["character_motion"] = Q.character_motion(SC.Scene(v2_test_spec()))
    rep["qa"]["facial"] = Q.facial(SC.Scene(v2_test_spec()))
    rep["qa"]["lipsync_timing"] = Q.lipsync_timing(SC.Scene(v2_test_spec()))
    rep["qa"]["video"] = Q.video(v, SC.Scene(v2_test_spec()))
    rep["pass"] = all(r.get("pass") for r in rep["qa"].values())
    with open(os.path.join(out, "v2_test_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=float)
    log(f"v2 test: {'PASS' if rep['pass'] else 'see report'} - voices: {rep['voice_engine']}")
    return rep


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "v2test":
        v2_test(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "story":                                     # one of the bot's own stories -> an animated episode
        from tvtoon import story as STY
        key = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "latest" else None
        o = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, "work", "tvtoon_story")
        lim = int(os.environ.get("TVTOON_MAX_SCENES", "0") or 0) or None
        k, st = STY.latest_story(key=key)
        ep = STY.episode_from_story(st, max_scenes=lim)
        os.makedirs(o, exist_ok=True)
        with open(os.path.join(o, "episode_spec.json"), "w", encoding="utf-8") as f:
            json.dump(ep, f, ensure_ascii=False, indent=1)
        print("story", k, st.get("title"), "scenes", len(ep["scenes"]))
        render_episode(ep, os.path.join(o, "story_episode_16x9.mp4"))
    elif cmd == "travel":                                    # side views: walking, rides, inside train / bus / tram
        o = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "work", "tvtoon_travel")
        os.makedirs(o, exist_ok=True)
        render_episode(travel_episode_spec(), os.path.join(o, "travel_episode_16x9.mp4"))
    elif cmd == "reveal":                                    # a ghost in disguise shows itself
        o = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "work", "tvtoon_reveal")
        os.makedirs(o, exist_ok=True)
        render_episode(reveal_episode_spec(), os.path.join(o, "reveal_episode_16x9.mp4"))
    elif cmd == "horror":
        o = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "work", "tvtoon_horror")
        os.makedirs(o, exist_ok=True)
        render_episode(horror_episode_spec(), os.path.join(o, "horror_episode_16x9.mp4"))
    elif cmd == "sample":
        build_sample(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        p = os.path.join(ROOT, "work", "tvtoon_sample", "status.json")
        st = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        for r in dashboard(st):
            print(r)
