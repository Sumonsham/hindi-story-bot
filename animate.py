"""Free cut-out animation for AI pictures: finds the face (eyes + mouth) with MediaPipe,
makes the eyes blink and the mouth move with the voice, cuts the character out of the picture
so it can breathe, bounce, jump or 'walk' across the background."""
import math

import cv2
import numpy as np

_FM = None


def _face_mesh():
    global _FM
    if _FM is None:
        import mediapipe as mp
        _FM = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=3, refine_landmarks=True,
                                              min_detection_confidence=0.2)
    return _FM


def find_faces(rgb):
    """rgb: HxWx3 uint8. Returns a list of faces: dict(eyes=[...], mouth=(cx, cy, width))."""
    H, W = rgb.shape[:2]
    try:
        r = _face_mesh().process(rgb)
    except Exception:
        return []
    out = []
    img = rgb.astype(np.float32)
    for lm in r.multi_face_landmarks or []:
        P = lambda i: (lm.landmark[i].x * W, lm.landmark[i].y * H)
        eyes = []
        for e in ([P(33), P(133), P(468)], [P(362), P(263), P(473)]):
            m = _eye_mask(img, e)
            if m is not None:
                eyes.append(_eye_parts(img, m))
        (lx, ly), (rx, ry) = P(61), P(291)
        mw = math.hypot(rx - lx, ry - ly)
        pts = [P(i) for i in (61, 291, 0, 13, 14, 17)]
        mx, my = float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))
        if mw > 6:
            face = {"eyes": eyes, "mouth": (mx, my, mw), "open": None, "nose_y": P(2)[1]}
            _find_mouth(img, face)
            out.append(face)
    return out


def _find_mouth(img, face):
    """Find the REAL mouth drawn in the picture. If it is already open (dark inside / teeth), remember its box -
    then the picture's own mouth is stretched open and closed (looks natural). If it is a closed smile line,
    find that line so a mouth opening is drawn exactly on it."""
    H, W = img.shape[:2]
    mx, my, mw = face["mouth"]
    x0, x1 = int(max(0, mx - 1.0 * mw)), int(min(W, mx + 1.0 * mw))
    y0, y1 = int(max(0, my - 0.7 * mw, face.get("nose_y", 0) + 0.12 * mw)), int(min(H, my + 0.7 * mw))  # below the nose
    reg = img[y0:y1, x0:x1]
    if reg.size == 0:
        return
    lum = reg.mean(2)
    skin = float(np.median(lum))
    r, g, b = reg[..., 0], reg[..., 1], reg[..., 2]
    inside = (lum < 0.55 * skin) | ((r > g * 1.35) & (lum < 0.8 * skin))      # dark mouth / red-pink tongue
    n, lab, st, cen = cv2.connectedComponentsWithStats(inside.astype(np.uint8))
    best, bd = None, 1e9
    for i in range(1, n):
        if st[i, 4] < 0.03 * mw * mw:
            continue
        ccx, ccy = cen[i]
        d = math.hypot(ccx + x0 - mx, ccy + y0 - my)
        if d < bd and d < 0.9 * mw:
            best, bd = i, d
    fill = st[best, 4] / max(1, st[best, 2] * st[best, 3]) if best is not None else 0
    face["_fill"] = fill
    thick = st[best, 4] / max(1, st[best, 2]) if best is not None else 0     # average height of the dark part
    if best is not None and st[best, 2] > 0.3 * mw and thick > 0.15 * mw:   # an OPEN mouth (not a thin smile line)
        bx, by, bw, bh = st[best, :4]
        face["open"] = (x0 + bx, y0 + by, x0 + bx + bw, y0 + by + bh)
        face["mouth"] = (x0 + bx + bw / 2, y0 + by, max(mw, bw))
        return
    # a closed smile line: keep the middle of the mouth, sit exactly on the darkest point of the line there
    col = img[int(max(0, my - 0.25 * mw)):int(min(H, my + 0.25 * mw)), int(min(W - 1, mx))].mean(1)
    if col.size:
        face["mouth"] = (mx, int(max(0, my - 0.25 * mw)) + int(np.argmin(col)), mw)


def _eye_mask(img, e):
    H, W = img.shape[:2]
    (x1, y1), (x2, y2), (ix, iy) = e
    w = max(8.0, math.hypot(x2 - x1, y2 - y1))
    if not (0 <= ix < W and 0 <= iy < H):
        return None
    yy, xx = np.mgrid[0:H, 0:W]
    win = ((xx - ix) / (0.95 * w)) ** 2 + ((yy - iy) / (0.62 * w)) ** 2 < 1
    lum = img.mean(2)
    sat = img.max(2) - img.min(2)
    m = ((((lum > 165) & (sat < 95)) | (lum < 125)) & win).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab = cv2.connectedComponents(m)
    k = lab[int(iy), int(ix)]
    if k == 0:
        return None
    m = (lab == k).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros((H, W), np.uint8)
    cv2.drawContours(out, [cv2.convexHull(max(cnts, key=cv2.contourArea))], -1, 255, -1)
    out = cv2.dilate(out, np.ones((5, 5), np.uint8))
    area = out.sum() / 255
    if area < 0.4 * w * w or area > 4 * w * w:
        return None
    return out


def _eye_parts(img, m):
    ys, xs = np.nonzero(m)
    X = np.arange(xs.min(), xs.max() + 1)
    top = np.array([ys[xs == x].min() if (xs == x).any() else ys.min() for x in X], np.float32)
    bot = np.array([ys[xs == x].max() if (xs == x).any() else ys.max() for x in X], np.float32)
    k = np.ones(7) / 7
    top = np.convolve(np.pad(top, 3, mode="edge"), k, "valid")
    bot = np.convolve(np.pad(bot, 3, mode="edge"), k, "valid")
    skin = cv2.inpaint(img.astype(np.uint8), cv2.dilate(m, np.ones((7, 7), np.uint8)), 7, cv2.INPAINT_TELEA)
    skin = cv2.GaussianBlur(skin.astype(np.float32), (0, 0), 2.5)
    feather = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), 1.5)
    y0, y1 = int(max(0, ys.min() - 4)), int(ys.max() + 6)
    x0, x1 = int(X[0]), int(X[-1]) + 1
    d = {"X": X, "top": top, "bot": bot, "box": (x0, y0, x1, y1),
         "skin": skin[y0:y1, x0:x1], "feather": feather[y0:y1, x0:x1]}
    # the iris (dark part) separately, so the eyes can look around
    reg = img[y0:y1, x0:x1]
    mm = m[y0:y1, x0:x1] > 0
    lum = reg.mean(2)
    n, lab, st, cen = cv2.connectedComponentsWithStats(((lum < 90) & mm).astype(np.uint8))
    if n > 1:
        k = 1 + int(np.argmax(st[1:, 4]))
        pcx, pcy = cen[k]
        r = min(math.sqrt(st[k, 4] / math.pi) * 1.3,           # dark pupil -> iris with its coloured ring
                0.45 * min(reg.shape[0], reg.shape[1]))
        yy_, xx_ = np.mgrid[0:reg.shape[0], 0:reg.shape[1]]
        disk = ((xx_ - pcx) ** 2 + (yy_ - pcy) ** 2) < r * r
        sat = reg.max(2) - reg.min(2)
        core = cv2.erode(mm.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0     # stay inside the lash line
        wm = ((lum > 185) & (sat < 80) & core).astype(np.uint8)
        ball = np.zeros_like(wm)
        pts = cv2.findNonZero(wm | (disk & core).astype(np.uint8))
        if pts is not None:
            cv2.drawContours(ball, [cv2.convexHull(pts)], -1, 1, -1)   # the eyeball (white + iris), no lashes
        ball = cv2.erode(ball, np.ones((3, 3), np.uint8)) > 0
        ia = cv2.GaussianBlur((disk & ball).astype(np.float32), (0, 0), 1.0)
        mm = ball
        whites = reg[mm & (lum > 185)]
        sclera = np.median(whites, 0) if len(whites) > 10 else np.array([236, 236, 236], np.float32)
        inner = mm.astype(np.float32)
        dist = cv2.distanceTransform(mm.astype(np.uint8), cv2.DIST_L2, 3)
        shade = (0.62 + 0.33 * np.clip(dist / 5.0, 0, 1))[..., None]      # eyelid shadow near the edge
        d.update(iris=reg.copy(), iris_a=ia, blank=reg * (1 - ia[..., None]) + sclera * shade * ia[..., None],
                 inner=cv2.GaussianBlur(inner, (0, 0), 1.2), ew=float(x1 - x0), eh=float(y1 - y0))
    return d


MOUTH_SHAPES = {   # half width, opening depth (x mouth width)
    "a": (0.30, 0.38), "e": (0.36, 0.20), "i": (0.38, 0.13), "o": (0.21, 0.32), "u": (0.15, 0.24), "m": (0.0, 0.0)}


def draw_face(frame, faces, blink, mouth, shape="a", gaze=(0.0, 0.0)):
    """frame: float32 RGB (changed copy returned). blink 0..1 (1 = closed), mouth 0..1 (1 = wide open),
    shape = mouth shape for the sound being spoken (a/e/i/o/u/m), gaze = where the eyes look (-1..1, -1..1)."""
    out = frame.copy()
    for f in faces:
        if abs(gaze[0]) + abs(gaze[1]) > 0.02:
            for e in f["eyes"]:
                if "iris" not in e:
                    continue
                x0, y0, x1, y1 = e["box"]
                Mt = np.float32([[1, 0, gaze[0] * e["ew"] * 0.08], [0, 1, gaze[1] * e["eh"] * 0.06]])
                hgt, wid = e["iris_a"].shape
                ir = cv2.warpAffine(e["iris"], Mt, (wid, hgt), borderMode=cv2.BORDER_REPLICATE)
                ia = cv2.warpAffine(e["iris_a"], Mt, (wid, hgt)) * e["inner"]
                reg = e["blank"] * (1 - ia[..., None]) + ir * ia[..., None]
                ea = (np.maximum(e["iris_a"], ia) * e["inner"])[..., None]   # only where the iris was / goes
                out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - ea) + reg * ea
        if blink > 0.02:
            for e in f["eyes"]:
                x0, y0, x1, y1 = e["box"]
                if y1 > out.shape[0] or x1 > out.shape[1]:
                    continue
                X = e["X"] - x0
                edge = e["top"] + (e["bot"] - e["top"] + 3) * blink - y0
                yy = np.arange(y1 - y0, dtype=np.float32)[:, None]
                E = np.full(x1 - x0, -1.0, np.float32); E[X] = edge
                T = np.zeros(x1 - x0, np.float32); T[X] = e["top"] - y0
                B = np.ones(x1 - x0, np.float32); B[X] = e["bot"] - y0
                lid = e["feather"] * np.clip(E[None, :] - yy + 0.5, 0, 1)
                shade = 1.0 - 0.12 * np.clip((yy - T[None, :]) / np.maximum(1, B - T)[None, :], 0, 1)
                reg = out[y0:y1, x0:x1]
                out[y0:y1, x0:x1] = reg * (1 - lid[..., None]) + e["skin"] * shade[..., None] * lid[..., None]
                if blink > 0.3:
                    pts = np.stack([e["X"], edge + y0], 1).astype(np.int32).reshape(-1, 1, 2)
                    sub = np.clip(out[y0:y1, x0:x1], 0, 255).astype(np.uint8).copy()
                    cv2.polylines(sub, [pts - np.array([x0, y0])], False, (50, 30, 28), 3, cv2.LINE_AA)
                    out[y0:y1, x0:x1] = sub
        hw, dp = MOUTH_SHAPES.get(shape, MOUTH_SHAPES["a"])
        if f.get("open"):
            out = _warp_open_mouth(out, f, mouth if dp > 0 else 0.0, shape)
            continue
        if mouth > 0.05 and dp > 0:
            cx, cy, mw = f["mouth"]
            half, h = mw * hw, mw * dp * mouth
            round_ = shape in ("o", "u")
            teeth = shape in ("a", "e", "i") and h > 4
            for x in range(int(cx - half), int(cx + half) + 1):
                u = (x - cx) / half
                depth = h * math.sqrt(max(0.0, 1 - u * u))
                y0 = int(cy) - 1
                yb = int(y0 + depth)
                if yb <= y0 or not (0 <= x < out.shape[1]) or yb + 2 >= out.shape[0]:
                    continue
                if round_:                                  # round lips: opening sits a bit lower, centred
                    y0 = int(cy - depth * 0.25)
                    yb = int(cy + depth * 0.75)
                col = np.linspace(0, 1, yb - y0)[:, None]
                tongue = np.clip((col - 0.55) / 0.3, 0, 1) * (mouth > 0.35)
                px = np.array([62, 14, 24]) * (1 - tongue) + np.array([195, 85, 95]) * tongue
                if teeth:
                    px[:max(1, int((yb - y0) * 0.24))] = (238, 236, 230)
                out[y0:yb, x] = px
                out[yb:yb + 2, x] = (225, 120, 120)
    return out


def _warp_open_mouth(out, f, mouth, shape):
    """Open / close the picture's own mouth: only the lower lip moves (the upper lip, nose and cheeks
    stay still), inside a small area around the mouth."""
    bx0, by0, bx1, by1 = f["open"]
    bw, bh = bx1 - bx0, by1 - by0
    s = 0.65 + 0.7 * float(mouth)                       # 0.65 = nearly closed, 1.35 = wide open
    sx = 0.85 if shape in ("o", "u") else 1.0
    if shape in ("e", "i"):
        s = min(s, 0.85)
    H, W = out.shape[:2]
    mx0, mx1 = int(max(0, bx0 - 0.12 * bw)), int(min(W, bx1 + 0.12 * bw))
    my0, my1 = int(max(0, by0 + 0.15 * bh)), int(min(H, by1 + 0.9 * bh))
    if mx1 - mx0 < 4 or my1 - my0 < 4:
        return out
    yy, xx = np.mgrid[my0:my1, mx0:mx1].astype(np.float32)
    cxm = (bx0 + bx1) / 2
    wx = np.clip((0.5 * bw + 0.12 * bw - np.abs(xx - cxm)) / (0.25 * bw + 1), 0, 1)
    wy = np.clip((yy - my0) / (0.15 * bh + 1), 0, 1) * np.clip((my1 - yy) / (0.6 * bh + 1), 0, 1)
    w = wx * wy
    piv = by0 + 0.3 * bh
    map_y = yy + w * (np.minimum(piv + (yy - piv) / s, my1 - 1) - yy)
    map_x = xx + w * ((cxm + (xx - cxm) / sx) - xx)
    out[my0:my1, mx0:mx1] = cv2.remap(out, map_x.astype(np.float32), map_y.astype(np.float32), cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_REFLECT)
    return out


def cutout(rgb, session=None):
    """-> (background with the hole filled, character alpha 0..1). None if no clear character."""
    from PIL import Image
    from rembg import remove, new_session
    session = session or new_session("isnet-general-use")
    H, W = rgb.shape[:2]
    alpha = np.array(remove(Image.fromarray(rgb), session=session, only_mask=True).convert("L").resize((W, H)))
    part = (alpha > 128).mean()
    if part < 0.02 or part > 0.7:
        return None
    hole = cv2.dilate((alpha > 40).astype(np.uint8) * 255, np.ones((31, 31), np.uint8))
    small = cv2.inpaint(cv2.resize(rgb, (W // 2, H // 2)), cv2.resize(hole, (W // 2, H // 2)), 9, cv2.INPAINT_TELEA)
    bg = cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    bg = np.where(hole[..., None] > 0, cv2.GaussianBlur(bg, (0, 0), 4), rgb.astype(np.float32))
    return bg, cv2.GaussianBlur(alpha.astype(np.float32) / 255, (0, 0), 1.2)


def place(dst, fg, a, dx, dy, scale=1.0, angle=0.0, pivot=None):
    """Paste a cut-out character onto dst, moved by (dx, dy), scaled/rotated around pivot (its feet)."""
    H, W = dst.shape[:2]
    px, py = pivot or (W / 2, H)
    M = cv2.getRotationMatrix2D((float(px), float(py)), float(angle), float(scale))
    M[0, 2] += dx
    M[1, 2] += dy
    f = cv2.warpAffine(fg, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
    al = cv2.warpAffine(a, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)[..., None]
    return dst * (1 - al) + f * al


def voice_envelope(wav_path, fps):
    """Loudness of the voice per video frame, 0..1 - drives the mouth."""
    from scipy.io import wavfile
    sr, a = wavfile.read(wav_path)
    a = a.astype(np.float32)
    if a.ndim > 1:
        a = a.mean(1)
    hop = int(sr / fps)
    env = np.array([np.sqrt((a[i:i + hop] ** 2).mean()) if i + hop <= len(a) else 0 for i in range(0, len(a), hop)])
    if env.max() > 0:
        env = env / np.percentile(env[env > 0], 95)
    env = np.clip((env - 0.12) / 0.7, 0, 1)
    # syllable feel: open-close instead of staying open
    wob = 0.65 + 0.35 * np.abs(np.sin(np.arange(len(env)) * math.pi * 5.5 / fps))
    return np.clip(env * wob, 0, 1)


# ---------- lip sync: which mouth shape for which sound (Bengali + Hindi letters)
_V = {}
for ch in "আা": _V[ch] = "a"
for ch in "ইঈিীএঐেৈइईिीएऐेै": _V[ch] = "i" if ch in "ইঈিীइईिी" else "e"
for ch in "উঊুূউঊুূ": _V[ch] = "u"
for ch in "ওঔোৌঅओऔोौ": _V[ch] = "o"
for ch in "आा": _V[ch] = "a"
for ch in "अ": _V[ch] = "a"
_LABIAL = set("পফবভমपफबभम")
_CONS_BN = set(chr(c) for c in range(0x0995, 0x09B9 + 1)) | set("ড়ঢ়য়")
_CONS_HI = set(chr(c) for c in range(0x0915, 0x0939 + 1))
_SYL = {}


def syllables(text):
    """Text -> list of (mouth shape, starts with lips closed?) per syllable; ' ' = short pause."""
    if text in _SYL:
        return _SYL[text]
    out, i, t = [], 0, str(text)
    while i < len(t):
        ch = t[i]
        if ch in _CONS_BN or ch in _CONS_HI:
            nxt = t[i + 1] if i + 1 < len(t) else ""
            lab = ch in _LABIAL
            if nxt in ("্", "्"):                      # joined letters: no vowel here
                i += 2
                continue
            if nxt in _V:
                out.append((_V[nxt], lab))
                i += 2
                continue
            out.append(("o" if ch in _CONS_BN else "a", lab))   # Bengali inherent vowel sounds like 'o'
        elif ch in _V:
            out.append((_V[ch], False))
        elif ch in ",।!?." and out and out[-1][0] != " ":
            out.append((" ", False))
        i += 1
    _SYL[text] = out or [("a", False)]
    return _SYL[text]


def viseme_at(text, t, dur):
    """Mouth shape at time t (seconds) inside a line of length dur: a/e/i/o/u, or 'm' = lips closed."""
    syl = syllables(text)
    u = max(0.0, min(0.999, t / max(0.2, dur * 0.94)))
    pos = u * len(syl)
    v, lab = syl[int(pos)]
    if v == " " or (lab and pos - int(pos) < 0.35):
        return "m"
    return v
