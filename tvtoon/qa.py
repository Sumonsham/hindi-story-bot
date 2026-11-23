"""automatic asset validation for every character. A pass here is TECHNICAL only - never an approval.

Checks: identity spec complete; character really different from every other one; limbs (2 arms, 2 legs, 2 hands,
2 feet) and 5 fingers per hand shape; 7 eye states, 5 brows, 9 mouths, expressions - each one really looks
different (no duplicates); measured proportions = the identity sheet; exported layers are valid transparent PNGs of
one size, SVG and JSON present and readable; nothing missing or corrupted."""
import hashlib
import json
import os

import cairo
import numpy as np

from tvtoon import characters as CH
from tvtoon import face as FACE
from tvtoon import puppet as PP
from tvtoon import sheets as SH

REQUIRED = ["name_bn", "name_en", "category", "age", "personality", "voice", "height", "heads", "head", "face", "hair",
            "body", "costume", "colours"]
LIMB_BONES = ["uarm_a", "farm_a", "hand_a", "uarm_b", "farm_b", "hand_b", "thigh_a", "shin_a", "foot_a", "thigh_b",
              "shin_b", "foot_b", "head", "neck", "spine", "root"]


def _render(cid, pp, st, size=420):
    P = pp.P
    sc = size / (P["H"] * 1.15)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surf)
    SH.draw_still(ctx, pp, st, size / 2, size - 20, sc)
    a = np.ndarray((size, size, 4), np.uint8, surf.get_data()).copy()
    return a


def _face_crop(cid, pp, **kw):
    a = _render(cid, pp, SH.still_state(cid, pp, **kw), 600)
    al = a[..., 3] > 0
    ys = np.where(al.any(axis=1))[0]
    top = ys.min()
    head = int(pp.P["head_h"] * 600 / (pp.P["H"] * 1.15) * 1.7) + 4     # the whole head (tall hair knots too)
    return a[top: top + head]


def _sig(a):
    return hashlib.md5(a.tobytes()).hexdigest()


def identity_distance(a, b):
    """how many identity features differ between two specs"""
    feats = [("head", "shape"), ("face", "eye_style"), ("face", "nose"), ("hair", "style"), ("costume", "type")]
    n = sum(1 for k, f in feats if a.get(k, {}).get(f) != b.get(k, {}).get(f))
    n += abs(a["heads"] - b["heads"]) > 0.25
    n += abs(a["height"] - b["height"]) > 0.04
    ca, cb = a["colours"], b["colours"]
    main = [k for k in ca if k in cb and k not in ("skin", "hair", "lip", "shoe")]
    n += any(ca[k] != cb[k] for k in main) or set(ca) != set(cb)
    return n


def validate(cid, layer_dir=None):
    spec = CH.get(cid)
    res = {"character": cid, "checks": {}, "problems": [], "approved": False,
           "note": "technical validation only - the owner approves in tvtoon/approvals.json"}
    c = res["checks"]
    miss = [k for k in REQUIRED if k not in spec]
    c["spec_complete"] = not miss
    if miss:
        res["problems"].append(f"identity sheet is missing: {miss}")
    # different from every other designed character
    # (within its own cast: the horror cast, the kids' cast; passers-by and one-story faces are not compared)
    grp = spec.get("cast")
    dists = {o: identity_distance(spec, CH.get(o)) for o, so in list(CH.SPECS.items())
             if o != cid and not so.get("extra") and so.get("cast") == grp and not so.get("animal")}
    c["min_identity_distance"] = min(dists.values()) if dists else None
    if dists and min(dists.values()) < 4:
        res["problems"].append(f"too similar to {min(dists, key=dists.get)} ({min(dists.values())} features differ)")
    pp = PP.Puppet(spec)
    bones = set(pp.sk.bones)
    missing_b = [b for b in LIMB_BONES if b not in bones]
    c["limbs"] = {"arms": sum(b in bones for b in ("uarm_a", "uarm_b")), "legs": sum(b in bones for b in ("thigh_a", "thigh_b")),
                  "hands": sum(b in bones for b in ("hand_a", "hand_b")), "feet": sum(b in bones for b in ("foot_a", "foot_b"))}
    if missing_b or any(v != 2 for v in c["limbs"].values()):
        res["problems"].append(f"limbs wrong: {c['limbs']} missing bones {missing_b}")
    c["fingers_per_hand_shape"] = {k: len(v) for k, v in PP.HANDS.items()}
    if any(len(v) != 5 for v in PP.HANDS.values()):
        res["problems"].append("a hand shape does not have 5 fingers")
    # facial assets: every state must exist AND look different
    sigs = {}
    for e in FACE.EYES:
        st = SH.still_state(cid, pp)
        st["face"].update(FACE.EYES[e])
        if e == "closed":
            st["face"]["lid"] = 0.0
        a = _render(cid, pp, st, 600)
        sigs.setdefault("eyes", {})[e] = _sig(a)
    for m in FACE.MOUTHS:
        sigs.setdefault("mouths", {})[m] = _sig(_face_crop(cid, pp, mouth=m))
    for ex in FACE.EXPRESSIONS:
        sigs.setdefault("expressions", {})[ex] = _sig(_face_crop(cid, pp, emotion=ex))
    for b in FACE.BROW_STATES:
        st = SH.still_state(cid, pp)
        st["face"]["brow"] = b
        sigs.setdefault("brows", {})[b] = _sig(_render(cid, pp, st, 600))
    for g, d in sigs.items():
        c[f"{g}_count"] = len(d)
        c[f"{g}_distinct"] = len(set(d.values()))
        if len(set(d.values())) < len(d):
            dup = [k for k, v in d.items() if list(d.values()).count(v) > 1]
            res["problems"].append(f"{g}: some states look identical: {dup}")
    need = {"eyes": 7, "brows": 5, "mouths": 9, "expressions": 7}
    for g, n in need.items():
        if c.get(f"{g}_count", 0) < n:
            res["problems"].append(f"{g}: {c.get(f'{g}_count', 0)} of {n}")
    # proportions measured on the drawing
    a = _render(cid, pp, SH.still_state(cid, pp), 800)
    al = a[..., 3] > 0
    ys = np.where(al.any(axis=1))[0]
    body = ys.max() - ys.min()
    sc = 800 / (pp.P["H"] * 1.15)
    c["drawn_height_vs_spec_pct"] = round(100 * (body / sc - pp.P["H"]) / pp.P["H"], 1)
    if abs(c["drawn_height_vs_spec_pct"]) > 12:
        res["problems"].append(f"drawn height differs from the identity sheet by {c['drawn_height_vs_spec_pct']} %")
    # exported layers
    if layer_dir:
        files = [f for f in os.listdir(layer_dir) if f.startswith(cid)] if os.path.isdir(layer_dir) else []
        pngs = [f for f in files if f.endswith(".png")]
        sizes, bad, opaque = set(), [], []
        import cv2
        for f in pngs:
            im = cv2.imread(os.path.join(layer_dir, f), cv2.IMREAD_UNCHANGED)
            if im is None or im.ndim != 3 or im.shape[2] != 4:
                bad.append(f)
                continue
            sizes.add(im.shape[:2])
            if (im[..., 3] == 255).all():
                opaque.append(f)
        c["layer_pngs"] = len(pngs)
        c["layer_sizes"] = [list(s) for s in sizes]
        has = {k: any(f.endswith(k) for f in files) for k in (".svg", "_rig.json", "_FULL.png")}
        c["exports_present"] = has
        if bad:
            res["problems"].append(f"corrupted / not RGBA: {bad}")
        if opaque:
            res["problems"].append(f"no transparent background: {opaque}")
        if len(sizes) > 1:
            res["problems"].append("layers have different sizes")
        if not all(has.values()):
            res["problems"].append(f"missing exports: {[k for k, v in has.items() if not v]}")
        try:
            json.load(open(os.path.join(layer_dir, f"{cid}_rig.json"), encoding="utf-8"))
        except Exception:
            res["problems"].append("rig JSON unreadable")
    res["pass"] = not res["problems"]
    return res
