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
        cx, cy = (P(0)[0] + P(13)[0]) / 2, (P(0)[1] + P(13)[1]) / 2
        lum = img.mean(2)
        y0 = int(max(0, cy - 8))
        col = lum[y0:int(cy) + 8, int(min(W - 1, cx))]
        if col.size:
            cy = y0 + int(np.argmin(col))                 # sit exactly on the smile line
        if mw > 6:
            out.append({"eyes": eyes, "mouth": (cx, cy, mw)})
    return out


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
    m = ((((lum > 190) & (sat < 80)) | (lum < 125)) & win).astype(np.uint8) * 255
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
    return {"X": X, "top": top, "bot": bot, "box": (x0, y0, x1, y1),
            "skin": skin[y0:y1, x0:x1], "feather": feather[y0:y1, x0:x1]}


def draw_face(frame, faces, blink, mouth):
    """frame: float32 RGB (changed copy returned). blink 0..1 (1 = closed), mouth 0..1 (1 = wide open)."""
    out = frame.copy()
    for f in faces:
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
        if mouth > 0.05:
            cx, cy, mw = f["mouth"]
            half, h = mw * 0.30, mw * 0.36 * mouth
            for x in range(int(cx - half), int(cx + half) + 1):
                u = (x - cx) / half
                depth = h * math.sqrt(max(0.0, 1 - u * u))
                y0 = int(cy) - 1
                yb = int(y0 + depth)
                if yb <= y0 or not (0 <= x < out.shape[1]) or yb + 2 >= out.shape[0]:
                    continue
                col = np.linspace(0, 1, yb - y0)[:, None]
                tongue = np.clip((col - 0.55) / 0.3, 0, 1) * (mouth > 0.35)
                out[y0:yb, x] = np.array([62, 14, 24]) * (1 - tongue) + np.array([195, 85, 95]) * tongue
                out[yb:yb + 2, x] = (225, 120, 120)
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
