"""DEMO ONLY (posts nothing): makes a ~22 second test video showing the free cut-out animation
with real AI pictures and a real voice:
  1) 'puppet walk'  - the character slides in with a walking bounce
  2) 'two-picture walk' - two AI pictures (left foot / right foot) swapped while moving
  3) talking - mouth moves with the voice, eyes blink, happy jump at the end
Output: work/demo_walk.mp4 (download it from the run page, 'Artifacts')."""
import math
import os
import shutil
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import animate
import extras
import main as M

W, H, FPS = M.W, M.H, 25
os.makedirs(M.WORK, exist_ok=True)
J = lambda n: os.path.join(M.WORK, n)
LOG = M.log

story = {"setting": "a sunny Bengal village road with mud houses, banana trees, a pond and blue sky, morning light",
         "characters": [{"name": "Gopal", "gender": "male", "age": "adult", "kind": "human",
                         "look": "round cheerful plump Bengali man, clean-shaven round face, big bright eyes, small "
                                 "tuft of hair (tiki) on a bald head, white dhoti, short yellow kurta, red gamchha "
                                 "scarf on shoulder, barefoot"}]}
cast = M.Cast(story)
seed = 4242
M.make_cast_sheet(cast, J("sheet.jpg"), seed)

shots = {
    "bg": ("Empty village road, nobody in the picture, wide shot", "the village road", []),
    "walkA": ("Gopal walking from left to right, full body side view, LEFT leg stepping forward, arms swinging, "
              "big smile, plain light background", "plain light studio background", ["Gopal"]),
    "walkB": ("Gopal walking from left to right, full body side view, RIGHT leg stepping forward, arms swinging, "
              "big smile, plain light background", "plain light studio background", ["Gopal"]),
    "stand": ("Gopal standing and facing the camera, full body, happy smile, telling a joke, one hand raised",
              "on the village road", ["Gopal"]),
}
for k, (action, place, names) in shots.items():
    LOG(f"picture: {k}")
    if not M.make_image(cast, action, place, names, J(k + ".jpg"), seed):
        raise SystemExit(f"could not make picture {k}")


def load(k):
    return np.array(Image.open(J(k + ".jpg")).convert("RGB").resize((W, H)))


bg = load("bg").astype(np.float32)
sess = None
from rembg import new_session
sess = new_session("isnet-general-use")
cut = {}
for k in ("walkA", "walkB", "stand"):
    rgb = load(k)
    r = animate.cutout(rgb, sess)
    if r is None:
        raise SystemExit(f"no clear character in {k}")
    _, a = r
    ys, xs = np.nonzero(a > 0.5)
    box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    cut[k] = {"rgb": rgb.astype(np.float32), "a": a, "box": box,
              "faces": animate.find_faces(rgb) if k == "stand" else []}
LOG(f"faces found on the standing picture: {len(cut['stand']['faces'])}")

# ---- the voice (expressive Gemini voice if a key is there, otherwise Microsoft)
line = "আরে আরে, আমি গোপাল! আজ তোমাদের এমন একটা মজার গল্প শোনাব, হাসতে হাসতে পেট ফেটে যাবে!"
wav = J("voice.wav")
ok = extras.tts_gemini(f"<laugh> {line}", "Puck",
                       "Character: Gopal, a witty, cheerful, plump village jester. Emotion: playful, laughing. "
                       + extras.PRONOUNCE["bn"], "Bengali", wav, M.SR)
if not ok:
    M.tts_line(line, ("bn-IN-BashkarNeural", "+0%", "+0Hz", False), "bn", wav, "happy")
vdur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                             "default=nw=1:nk=1", wav], capture_output=True, text=True).stdout.strip() or 5)

T1, T2 = 6.0, 12.0
DUR = T2 + vdur + 2.0
env = animate.voice_envelope(wav, FPS)
font = ImageFont.truetype(M.find_font("bn"), 38)


def label(frame, text):
    im = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    tw = d.textlength(text, font=font)
    d.rounded_rectangle([30, 24, 30 + tw + 40, 24 + 64], radius=30, fill=(255, 200, 0))
    d.text((50, 26), text, font=font, fill=(40, 20, 70))
    return np.array(im)


def scale_for(k, target_h=470):
    x0, y0, x1, y1 = cut[k]["box"]
    return target_h / max(1, (y1 - y0))


ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                       "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-itsoffset", str(T2), "-i", wav,
                       "-t", f"{DUR:.2f}", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", J("demo_walk.mp4")], stdin=subprocess.PIPE)
ground = H - 40
for f in range(int(DUR * FPS)):
    t = f / FPS
    frame = bg.copy()
    if t < T2:
        two = t >= T1
        u = (t - (T1 if two else 0)) / (T2 - T1)
        k = ("walkA" if int(t * 4) % 2 == 0 else "walkB") if two else "walkA"
        c = cut[k]
        x0, y0, x1, y1 = c["box"]
        s = scale_for(k)
        step = abs(math.sin(t * math.pi * 2.0))                     # two steps a second
        bounce = (0 if two else 14) * step
        tilt = 0 if two else 3 * math.sin(t * math.pi * 2.0)
        cx = -150 + (W + 50) * min(1, u * 1.1)
        dx = cx - (x0 + x1) / 2
        dy = ground - y1 - bounce
        frame = animate.place(frame, c["rgb"], c["a"], dx, dy, s, tilt, ((x0 + x1) / 2, y1))
        frame = label(frame, "দুই ছবির হাঁটা পরীক্ষা" if two else "পুতুলের মতো হাঁটা")
    else:
        c = cut["stand"]
        x0, y0, x1, y1 = c["box"]
        s = scale_for("stand", 520)
        tv = t - T2
        fi = int(tv * FPS)
        m = float(env[fi]) if fi < len(env) else 0.0
        blink = 0.0
        for bt in (0.8, 3.1, 5.4, 7.6):
            if 0 <= tv - bt < 0.2:
                blink = math.sin(math.pi * (tv - bt) / 0.2)
        pic = animate.draw_face(c["rgb"], c["faces"], blink, m)
        breath = math.sin(tv * 2 * math.pi / 3.0)
        jump = max(0.0, math.sin((tv - vdur) * math.pi / 0.6)) * 60 if vdur <= tv <= vdur + 0.6 else 0
        dx = W / 2 - (x0 + x1) / 2
        dy = ground - y1 - 4 * m - 2 * breath - jump
        frame = animate.place(frame, pic, c["a"], dx, dy, s * (1 + 0.006 * breath), 1.5 * math.sin(tv * 1.4),
                              ((x0 + x1) / 2, y1))
        frame = label(frame, "কথা বলা  চোখের পলক  লাফ")
    ff.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
ff.stdin.close()
ff.wait()
for k in ("bg", "walkA", "walkB", "stand"):
    shutil.copy(J(k + ".jpg"), J("pic_" + k + ".jpg"))
LOG("DEMO READY: work/demo_walk.mp4")
