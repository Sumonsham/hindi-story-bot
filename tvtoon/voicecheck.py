"""A VOICE THAT SAYS THE LINE TWICE (owner, 23 Nov 2026: "duto bot ei kokhono kokhono ek line dubar, 3 bar bolche").

The story text is already checked so that no sentence is said twice (main.py no_line_twice). What still happens:
the voice model itself loops - it reads the line and then reads it (or its end) again, sometimes three times.
Every recorded line is checked here before it goes into the video:

  * the recording is compared with itself (its sound pattern frame by frame, at every delay from 0.8 s up): a long
    stretch that comes back the same a little later is a repeat;
  * a repeat is cut out (all repeats, if it said it three times) with a short cross-fade - unless the text itself
    repeats those words ("তফাত যাও! তফাত যাও!"), and the length is still normal for the text;
  * a recording that is far too long for its text, with no clear repeat inside, is reported (the bot can make it
    again).

fix_repeats(audio, sr, text) -> (audio, note); note is '' when nothing was wrong."""
import re

import numpy as np


def _features(a, sr, hop_s=0.02, win_s=0.04, bands=24):
    hop, win = int(sr * hop_s), int(sr * win_s)
    n = max(0, (len(a) - win) // hop)
    if n < 10:
        return None, None, hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    fr = a[idx] * np.hanning(win)[None, :]
    spec = np.abs(np.fft.rfft(fr, axis=1)) + 1e-9
    edges = np.unique(np.geomspace(2, spec.shape[1] - 1, bands + 1).astype(int))
    f = np.stack([spec[:, edges[i]:edges[i + 1]].mean(axis=1) for i in range(len(edges) - 1)], axis=1)
    f = np.log(f)
    energy = f.mean(axis=1)
    f = f - f.mean(axis=1, keepdims=True)
    f /= np.linalg.norm(f, axis=1, keepdims=True) + 1e-9
    voiced = energy > (np.percentile(energy, 90) - 2.3)
    return f, voiced, hop


def _text_repeats(text):
    """the words themselves repeat (on purpose): 'go away! go away!'"""
    w = re.findall(r"[\wঀ-৿ऀ-ॿ]+", str(text or "").lower())
    grams = [" ".join(w[i:i + 2]) for i in range(len(w) - 1)]
    return len(grams) != len(set(grams)) or len(w) != len(set(w)) and len(w) <= 6


def expected_seconds(text):
    try:
        from tvtoon import lipsync as LS
        n = len(LS.syllables(str(text)))
    except Exception:
        n = len(re.findall(r"[ঀ-৿ऀ-ॿA-Za-z]", str(text))) / 2.2
    return max(0.8, n * 0.19)


def find_repeat(a, sr, min_s=0.8, thr=0.86):
    """(start of the first copy, delay, length) in samples of the longest repeat, or None"""
    f, voiced, hop = _features(np.asarray(a, dtype=np.float64), sr)
    if f is None:
        return None
    n = len(f)
    if np.mean(np.sum(f[1:] * f[:-1], axis=1)) > 0.97:
        return None                                        # a steady tone, not speech (nothing to compare)
    min_run = int(min_s / 0.02)
    best = None
    for lag in range(int(0.8 / 0.02), n - min_run):
        sim = np.sum(f[:-lag] * f[lag:], axis=1)
        ok = (sim > thr) & voiced[:-lag] & voiced[lag:]
        if ok.sum() < min_run:
            continue
        # the longest run (gaps of up to 3 frames allowed: a breath)
        run, start, gap, b_run, b_start = 0, 0, 0, 0, 0
        for i, v in enumerate(ok):
            if v:
                if run == 0:
                    start = i
                run += 1 + gap
                gap = 0
            elif run:
                gap += 1
                if gap > 3:
                    if run > b_run:
                        b_run, b_start = run, start
                    run, gap = 0, 0
        if run > b_run:
            b_run, b_start = run, start
        if b_run >= min_run and b_run >= 0.55 * lag and (best is None or b_run > best[2]):
            best = (b_start, lag, b_run)
    if not best:
        return None
    s0, lag, r = best
    return s0 * hop, lag * hop, r * hop


def fix_repeats(a, sr, text, max_cuts=3):
    a = np.asarray(a, dtype=np.float64)
    if len(a) < sr * 2:
        return a, ""
    exp = expected_seconds(text)
    notes = []
    for _k in range(max_cuts):
        dur = len(a) / sr
        rep = find_repeat(a, sr)
        if not rep:
            break
        s0, lag, r = rep
        if _text_repeats(text) and dur < exp * 1.9:
            break                                          # the words really repeat - the voice is right
        if dur < exp * 1.3 and r < 0.9 * lag:
            break                                          # not longer than its words need: no cut (be careful)
        cut0, cut1 = s0 + lag, min(len(a), s0 + lag + max(r, lag))
        if cut1 - cut0 < sr * 0.5:
            break
        fade = int(sr * 0.04)
        head, tail = a[:cut0], a[cut1:]
        if len(head) > fade and len(tail) > fade:
            ramp = np.linspace(0, 1, fade)
            mid = head[-fade:] * (1 - ramp) + tail[:fade] * ramp
            a = np.concatenate([head[:-fade], mid, tail[fade:]])
        else:
            a = np.concatenate([head, tail])
        notes.append(f"{(cut1 - cut0) / sr:.1f} s said again")
    dur = len(a) / sr
    if not notes and dur > exp * 3.2 and dur > 6:
        notes.append(f"too long for its words ({dur:.1f} s for ~{exp:.1f} s)")
    return a, "; ".join(notes)
