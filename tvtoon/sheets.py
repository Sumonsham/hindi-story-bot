"""character sheets: identity, full-body poses, expressions, eyes + brows, mouths; transparent PNG layers, SVG, JSON"""
import json
import math
import os

import cairo
import numpy as np

from tvtoon import animator as AN
from tvtoon import characters as CH
from tvtoon import face as FACE
from tvtoon import geom as G
from tvtoon import puppet as PP

BG = (0.965, 0.955, 0.93)


class _Stub:
    """a one-character 'scene' for still poses"""

    def __init__(self, pf):
        self.perf = {pf.cid: pf}
        self.wind = 0.0

    def x_of(self, cid, t):
        return None

    def current_speaker(self, t):
        return None


POSES = [  # name, emotion, gesture, turn, mouth
    ("front_relaxed", "neutral", None, 0.0, None), ("front_talking", "neutral", "explain", 0.0, "A"),
    ("front_smiling", "happy", None, 0.0, None), ("front_laughing", "laughing", "belly_laugh", 0.0, None),
    ("front_sad", "sad", None, 0.0, None), ("front_angry", "angry", "hips", 0.0, None),
    ("front_surprised", "surprised", "shrug", 0.0, None), ("front_scared", "scared", "scared", 0.0, None),
    ("namaste", "happy", "namaste", 0.0, None), ("waving", "happy", "wave", 0.0, None),
    ("pointing", "neutral", "point", 0.0, None), ("clapping", "happy", "clap", 0.0, None),
    ("three_quarter_left", "neutral", None, -0.45, None), ("three_quarter_right", "neutral", None, 0.45, None),
    ("side_view", None, None, None, None), ("back_view", None, None, None, None),
]
MISSING_POSES = {"side_view": "a true profile needs its own drawn parts (profile head, one eye, profile body) - planned",
                 "back_view": "needs a back-of-head hair part and costume back - planned"}


def still_state(cid, pp, emotion="neutral", gesture=None, turn=0.0, mouth=None, t=1.3):
    pf = AN.Perf(cid, pp, 0.0)
    pf.blinks = []
    pf.darts = [(0.0, (0.0, 0.0))]
    if emotion:
        pf.emotions.append((0.0, 99.0, emotion))
    if gesture:
        pf.gestures.append((0.0, 99.0, gesture, None, None))
    pf.facing.append((0.0, turn))
    pf.turn_s = turn
    st, _x = pf.state(t, _Stub(pf))
    if mouth:
        st["face"]["mouth"] = mouth
    st["hair"] = (0.0, 0.0)
    st["cloth"] = 0.0
    return st


def draw_still(ctx, pp, st, x, ground, scale):
    pp.draw(ctx, st, x, ground, scale, solver=AN.solve_legs)


def _label(ctx, txt, x, y, size=22, col=(0.15, 0.1, 0.08), center=True):
    ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    ext = ctx.text_extents(txt)
    ctx.move_to(x - ext.width / 2 if center else x, y)
    ctx.set_source_rgb(*col)
    ctx.show_text(txt)


def _bengali(png_path, items, font_path):
    """write Bengali labels with Pillow + raqm (cairo's toy text cannot shape Bengali)"""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(png_path).convert("RGB")
    d = ImageDraw.Draw(im)
    for txt, x, y, size in items:
        f = ImageFont.truetype(font_path, size, layout_engine=ImageFont.Layout.RAQM)
        w = d.textlength(txt, font=f)
        d.text((x - w / 2, y), txt, font=f, fill=(40, 25, 18))
    im.save(png_path)


FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "NotoSansBengali-Bold.ttf")


def pose_sheet(cid, out):
    spec = CH.get(cid)
    pp = PP.Puppet(spec)
    H = pp.P["H"]
    sc = 520.0 / 1000.0
    cw, chh = 300, int(1000 * sc * 1.0 + 140)
    cols = 8
    rows = (len(POSES) + cols - 1) // cols
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, cols * cw, rows * chh + 70)
    ctx = cairo.Context(surf)
    ctx.set_source_rgb(*BG)
    ctx.paint()
    _label(ctx, f"{spec['name_en']} - full-body poses (vector puppet, not approved)", cols * cw / 2, 46, 30)
    for i, (name, emo, ges, turn, mouth) in enumerate(POSES):
        cx = (i % cols) * cw + cw / 2
        top = 70 + (i // cols) * chh
        ground = top + chh - 70
        if name in MISSING_POSES:
            ctx.set_source_rgb(0.9, 0.86, 0.84)
            ctx.rectangle(cx - cw / 2 + 10, top + 10, cw - 20, chh - 40)
            ctx.fill()
            _label(ctx, "MISSING", cx, top + chh / 2, 30, (0.75, 0.1, 0.1))
            _label(ctx, "(planned)", cx, top + chh / 2 + 34, 18, (0.4, 0.3, 0.3))
        else:
            st = still_state(cid, pp, emo, ges, turn, mouth)
            ctx.save()
            draw_still(ctx, pp, st, cx, ground, sc)
            ctx.restore()
        _label(ctx, name.replace("_", " "), cx, top + chh - 24, 18)
    surf.write_to_png(out)
    return out


def face_sheet(cid, out):
    """expressions + 7 eyes + 5 brows + 9 mouths, heads only"""
    spec = CH.get(cid)
    pp = PP.Puppet(spec)
    P = pp.P
    sc = 210.0 / P["head_h"]
    rows_ = [("EXPRESSIONS", [("expr", e) for e in ["neutral", "happy", "laughing", "sad", "angry", "surprised", "scared", "thinking"]]),
             ("EYES (7)", [("eye", e) for e in FACE.EYES]),
             ("BROWS (5)", [("brow", b) for b in FACE.BROW_STATES]),
             ("MOUTHS / VISEMES (9)", [("mouth", m) for m in FACE.MOUTHS])]
    cw, chh = 270, 330
    cols = 9
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, cols * cw + 40, len(rows_) * (chh + 50) + 120)
    ctx = cairo.Context(surf)
    ctx.set_source_rgb(*BG)
    ctx.paint()
    _label(ctx, f"{spec['name_en']} - face sheet", (cols * cw) / 2, 50, 32)
    labels = []
    for r, (title, items) in enumerate(rows_):
        y0 = 80 + r * (chh + 50)
        _label(ctx, title, 30, y0 + 30, 22, center=False)
        for i, (k, v) in enumerate(items):
            cx = 20 + i * cw + cw / 2
            if k == "expr":
                fc = FACE.expression(v)
            elif k == "eye":
                fc = dict(FACE.expression("neutral"), **FACE.EYES[v])
            elif k == "brow":
                fc = dict(FACE.expression("neutral"), brow=v)
            else:
                fc = dict(FACE.expression("neutral"), mouth=v, smile=0.1)
            st = {"face": fc, "rot": {}, "len": {}}
            ground = y0 + 50 + P["H"] * sc - P["head_h"] * sc * 0.0 + 10
            ctx.save()
            ctx.rectangle(cx - cw / 2 + 6, y0 + 40, cw - 12, chh - 30)
            ctx.clip()
            pp.draw(ctx, st, cx, ground - (P["H"] - P["head_h"] - P["neck"]) * sc * 0.0, sc, only={"head", "hair_front", "hair_back", "body"})
            ctx.restore()
            _label(ctx, v.replace("_", " "), cx, y0 + chh + 34, 18)
            if k == "mouth":
                labels.append((FACE.MOUTH_NAMES_BN[v], cx, y0 + chh + 38, 20))
    surf.write_to_png(out)
    if labels and os.path.exists(FONT):
        _bengali(out, labels, FONT)
    return out


def identity_sheet(cid, out):
    spec = CH.get(cid)
    pp = PP.Puppet(spec)
    P = pp.P
    W_, H_ = 1800, 1100
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W_, H_)
    ctx = cairo.Context(surf)
    ctx.set_source_rgb(*BG)
    ctx.paint()
    sc = 820.0 / 1000.0
    ground = 1000
    for x, turn in ((300, 0.0), (650, 0.45), (1000, -0.45)):
        st = still_state(cid, pp, "neutral", None, turn)
        ctx.save()
        draw_still(ctx, pp, st, x, ground, sc)
        ctx.restore()
    hh = P["head_h"] * sc                                   # the heads-tall ruler
    for k in range(int(math.ceil(spec["heads"])) + 1):
        y = ground - k * hh
        G.line(ctx, [(90, y), (130, y)], 2, (0.5, 0.2, 0.2), smooth_it=False)
        _label(ctx, str(k), 70, y + 6, 16)
    G.line(ctx, [(110, ground), (110, ground - spec["heads"] * hh)], 2, (0.5, 0.2, 0.2), smooth_it=False)
    _label(ctx, f"{spec['heads']} heads", 110, ground + 40, 18)
    x0 = 1250
    _label(ctx, spec["name_en"], x0 + 240, 90, 40)
    lines = [f"category: {spec['category'].replace('_', ' ')}   age: {spec['age']}",
             f"head: {spec['head']['shape']}   eyes: {spec['face'].get('eye_style')}   nose: {spec['face'].get('nose')}",
             f"hair: {spec['hair']['style'].replace('_', ' ')}   costume: {spec['costume']['type'].replace('_', ' ')}",
             f"height: {spec['height']:.2f} (adult man = 1.00)", f"voice: {spec['voice']}"]
    for i, l in enumerate(lines):
        _label(ctx, l, x0 - 20, 200 + i * 34, 17, center=False)
    words = spec["personality"].split(" ")
    cur, yy = "", 400
    _label(ctx, "personality:", x0 - 20, yy, 18, center=False)
    yy += 30
    for w in words:
        if len(cur + " " + w) > 44:
            _label(ctx, cur, x0 - 20, yy, 17, center=False)
            yy += 26
            cur = w
        else:
            cur = (cur + " " + w).strip()
    _label(ctx, cur, x0 - 20, yy, 17, center=False)
    yy += 60
    _label(ctx, "palette:", x0 - 20, yy, 18, center=False)
    yy += 14
    for i, (k, v) in enumerate(spec["colours"].items()):
        cx, cy = x0 - 20 + (i % 4) * 130, yy + (i // 4) * 90
        ctx.rectangle(cx, cy, 60, 50)
        ctx.set_source_rgb(*G.rgb(v))
        ctx.fill_preserve()
        ctx.set_source_rgb(0.2, 0.15, 0.1)
        ctx.set_line_width(2)
        ctx.stroke()
        _label(ctx, k, cx + 30, cy + 72, 14)
    _label(ctx, "LOCKED IDENTITY - only the owner approves (tvtoon/approvals.json)", W_ / 2, H_ - 30, 20, (0.6, 0.15, 0.1))
    surf.write_to_png(out)
    _bengali(out, [(spec["name_bn"], x0 + 240, 112, 44)], FONT)
    return out


def export_layers(cid, out_dir):
    """transparent PNG per layer group (rest pose), a full transparent PNG, an SVG of the character and the JSON rig
    configuration"""
    spec = CH.get(cid)
    pp = PP.Puppet(spec)
    P = pp.P
    os.makedirs(out_dir, exist_ok=True)
    sc = 1.0
    W_, H_ = int(P["H"] * 0.9 + 200), int(P["H"] + 160)
    st = still_state(cid, pp)
    files = {}
    names = [g for g, _ in pp.groups(st)]
    for g in names + ["FULL"]:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W_, H_)
        ctx = cairo.Context(surf)
        draw_still(ctx, pp, st, W_ / 2, H_ - 60, sc) if g == "FULL" else pp.draw(ctx, st, W_ / 2, H_ - 60, sc, only={g},
                                                                              solver=AN.solve_legs)
        f = os.path.join(out_dir, f"{cid}_{g}.png")
        surf.write_to_png(f)
        files[g] = f
    svg = os.path.join(out_dir, f"{cid}.svg")
    s2 = cairo.SVGSurface(svg, W_, H_)
    c2 = cairo.Context(s2)
    draw_still(c2, pp, st, W_ / 2, H_ - 60, sc)
    s2.finish()
    files["svg"] = svg
    cfg = {"id": cid, "spec": spec, "proportions": P,
           "bones": {b: {"parent": v[0], "offset": v[1], "length": v[2], "rest_deg": round(math.degrees(v[3]), 2)}
                     for b, v in pp.sk.bones.items()},
           "layers": names, "hand_shapes": list(PP.HANDS), "eyes": list(FACE.EYES), "brows": FACE.BROW_STATES,
           "mouths": FACE.MOUTHS, "expressions": list(FACE.EXPRESSIONS)}
    jf = os.path.join(out_dir, f"{cid}_rig.json")
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    files["json"] = jf
    return files
