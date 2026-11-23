"""Bengali lip-sync: a practical 9-viseme approximation, timed on the REAL audio.

1. Text -> Bengali syllables (akshara: consonant cluster + vowel sign / inherent vowel) -> (consonant viseme, vowel
   viseme) per syllable. The inherent vowel is spoken as 'ô' (O) except at the end of a word.
2. Audio -> speech chunks (split at pauses) and syllable nuclei (loudness peaks of the voice band).
3. Alignment: text phrases (split at punctuation) are given to speech chunks by syllable share; inside a chunk the
   syllables are spread over its time and each vowel is SNAPPED to the nearest loudness peak (timing correction).
4. Without text: vowels are guessed from the spectrum (F1/F2 bands) - language independent.

This is NOT phoneme recognition. It is how TV cartoons do it: a handful of mouth shapes on the voice's rhythm."""
import math
import subprocess

import numpy as np

SR = 16000
HOP = 0.01

LABIAL = set("পবভম")
FV = set("ফ")
TEETH = set("চছজঝযশষসয়")
TONGUE = set("তথদধনটঠডঢণলরড়ঢ়ৎংকখগঘঙহ")
CONS = LABIAL | FV | TEETH | TONGUE | set("ঞ")
VOWEL_SIGN = {"া": "A", "ি": "E", "ী": "E", "ু": "U", "ূ": "U", "ৃ": "E", "ে": "E", "ৈ": "E", "ো": "O", "ৌ": "O"}
VOWEL_IND = {"অ": "O", "আ": "A", "ই": "E", "ঈ": "E", "উ": "U", "ঊ": "U", "ঋ": "E", "এ": "E", "ঐ": "E", "ও": "O", "ঔ": "O"}
HASANTA = "্"
PAUSE_CHARS = set("।,;:!?—–-…")


def cons_vis(c):
    if c in LABIAL:
        return "MBP"
    if c in FV:
        return "FV"
    if c in TEETH:
        return "E"
    return "LTD"


def _from_devanagari(text):
    """Hindi: the Devanagari letters map one to one onto the Bengali ones (both follow the same old Indian order,
    0x80 apart), so the same syllable rules work; Hindi's inherent vowel is 'a' (A), not the Bengali 'o'"""
    out = []
    for ch in text:
        o = ord(ch)
        if 0x0900 <= o <= 0x097F and ch not in "।॥":
            if ch == "व":
                out.append("ভ")                               # (v / w is a lip sound)
            else:
                out.append(chr(o + 0x80))
        else:
            out.append(ch)
    return "".join(out)


def syllables(text):
    """[(onset_viseme or None, vowel_viseme or None, phrase_break_after)]"""
    hindi = any(0x0900 <= ord(c) <= 0x097F for c in text)
    if hindi:
        text = _from_devanagari(text)
    out = []
    words = text.replace("\n", " ").split(" ")
    for w in words:
        if not w:
            continue
        i, n = 0, len(w)
        word_syl = []
        while i < n:
            ch = w[i]
            if ch in PAUSE_CHARS or ch == ".":
                if word_syl:
                    word_syl[-1] = (word_syl[-1][0], word_syl[-1][1], True)
                elif out:
                    out[-1] = (out[-1][0], out[-1][1], True)
                i += 1
                continue
            if ch in VOWEL_IND:
                word_syl.append((None, VOWEL_IND[ch], False))
                i += 1
                continue
            if ch in CONS:
                onset = cons_vis(ch)
                i += 1
                yafala = False
                while i + 1 < n and w[i] == HASANTA and w[i + 1] in CONS:   # a conjunct cluster
                    if w[i + 1] == "য":
                        yafala = True
                    i += 2
                if i < n and w[i] == "়":
                    i += 1
                if i < n and w[i] in VOWEL_SIGN:
                    v = VOWEL_SIGN[w[i]]
                    if yafala and w[i] == "া":
                        v = "A"
                    word_syl.append((onset, v, False))
                    i += 1
                elif i < n and w[i] == HASANTA:
                    word_syl.append((onset, None, False))
                    i += 1
                else:
                    word_syl.append((onset, "A" if hindi else "O", False))   # the inherent vowel
                while i < n and w[i] in "ঁংঃ":
                    i += 1
                continue
            i += 1
        if word_syl and word_syl[-1][1] == ("A" if hindi else "O") and len(word_syl) > 1 and word_syl[-1][0] is not None:
            on, _v, br = word_syl[-1]                               # word-final inherent vowel is silent
            word_syl[-1] = (on, None, br)
        out += word_syl
    return out


def load_audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def features(a):
    hop = int(SR * HOP)
    win = hop * 3
    n = max(1, (len(a) - win) // hop)
    hann = np.hanning(win).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(a, win)[::hop][:n] * hann
    spec = np.abs(np.fft.rfft(frames, axis=1))
    fr = np.fft.rfftfreq(win, 1 / SR)
    band = lambda lo, hi: spec[:, (fr >= lo) & (fr < hi)].sum(axis=1)
    voice = band(250, 3500)
    f1 = band(300, 900)
    f2 = band(1200, 2800)
    hi = band(4000, 7900)
    loud = np.log10(voice + 1e-6)
    k = 5
    sm = np.convolve(loud, np.ones(k) / k, mode="same")
    return {"loud": sm, "f1": f1, "f2": f2, "hi": hi, "voice": voice, "n": n}


def speech_chunks(F, min_pause=0.22):
    L = F["loud"]
    lo, hi = np.percentile(L, 10), np.percentile(L, 95)
    thr = lo + 0.35 * (hi - lo)
    on = L > thr
    chunks, i, n = [], 0, len(L)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            chunks.append([i, j])
            i = j
        else:
            i += 1
    merged = []
    for c in chunks:                                  # join gaps shorter than a real pause
        if merged and (c[0] - merged[-1][1]) * HOP < min_pause:
            merged[-1][1] = c[1]
        else:
            merged.append(c)
    return [(a * HOP, b * HOP) for a, b in merged if (b - a) * HOP > 0.08], thr


def nuclei(F, thr):
    L = F["loud"]
    pk = []
    for i in range(2, len(L) - 2):
        if L[i] > thr and L[i] >= L[i - 1] and L[i] >= L[i + 1] and L[i] >= L[i - 2] and L[i] >= L[i + 2]:
            if pk and (i - pk[-1]) * HOP < 0.09:
                if L[i] > L[pk[-1]]:
                    pk[-1] = i
                continue
            pk.append(i)
    return [p * HOP for p in pk]


def spectral_vowel(F, t):
    i = min(F["n"] - 1, max(0, int(t / HOP)))
    f1, f2 = F["f1"][i], F["f2"][i]
    r = f2 / (f1 + 1e-6)
    if r > 0.9:
        return "E"
    if r < 0.25:
        return "U" if F["loud"][i] < np.percentile(F["loud"], 70) else "O"
    return "A"


def align(audio_path, text=None, offset=0.0):
    """viseme events [(t, viseme)] on the audio's own clock (+ offset). Ends with 'X'."""
    a = load_audio(audio_path)
    dur = len(a) / SR
    F = features(a)
    chunks, thr = speech_chunks(F)
    peaks = nuclei(F, thr)
    ev = [(0.0, "X")]
    if not chunks:
        return [(offset, "X")], {"duration": dur, "chunks": 0}
    if not text:
        for p in peaks:
            ev.append((p - 0.05, "LTD"))
            ev.append((p, spectral_vowel(F, p)))
        for c0, c1 in chunks:
            ev.append((c1, "X"))
        ev.sort()
        return [(t + offset, v) for t, v in ev], {"duration": dur, "chunks": len(chunks), "method": "audio-only"}
    syl = syllables(text)
    phrases, cur = [], []
    for s in syl:
        cur.append(s)
        if s[2]:
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)
    # phrases -> chunks by share: walk both lists keeping cumulative proportions
    tot_s = sum(len(p) for p in phrases)
    tot_t = sum(c1 - c0 for c0, c1 in chunks)
    groups = [[] for _ in chunks]
    acc = 0
    for ph in phrases:
        mid = (acc + len(ph) / 2) / max(1, tot_s)
        acc += len(ph)
        tt, k = 0.0, 0
        for k, (c0, c1) in enumerate(chunks):
            tt += c1 - c0
            if tt / tot_t >= mid - 1e-9:
                break
        groups[k] += ph
    snaps = 0
    for (c0, c1), g in zip(chunks, groups):
        if not g:
            continue
        pk = [p for p in peaks if c0 - 0.03 <= p <= c1 + 0.03]
        n = len(g)
        for j, (on, vw, _br) in enumerate(g):
            tv = c0 + (j + 0.55) * (c1 - c0) / n
            if pk:                                         # timing correction: snap to the nearest voice peak
                q = min(pk, key=lambda p: abs(p - tv))
                if abs(q - tv) < 0.6 * (c1 - c0) / n:
                    tv = q
                    snaps += 1
            if on:
                ev.append((tv - 0.07, on))
            if vw:
                ev.append((tv, vw))
            elif on:
                ev.append((tv + 0.02, on))
        ev.append((c1, "X"))
    ev.sort()
    clean = []
    for t, v in ev:                                        # monotonic, at least 2 frames (1/12 s) per shape
        if clean and t - clean[-1][0] < 1 / 12.0:
            if v == "X" and clean[-1][1] != "X":
                continue
            clean[-1] = (clean[-1][0], v)
            continue
        clean.append((t, v))
    return [(max(0.0, t - 1 / 24.0) + offset, v) for t, v in clean], \
        {"duration": dur, "chunks": len(chunks), "syllables": len(syl), "peaks": len(peaks), "snapped": snaps,
         "method": "bengali-text + audio-timing"}


def viseme_at(events, t):
    v = "X"
    for tt, vv in events:
        if tt > t:
            break
        v = vv
    return v


def loudness_track(audio_path):
    a = load_audio(audio_path)
    F = features(a)
    L = F["loud"]
    lo, hi = np.percentile(L, 10), np.percentile(L, 98)
    return np.clip((L - lo) / max(1e-6, hi - lo), 0, 1), HOP
