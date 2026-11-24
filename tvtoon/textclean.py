"""ENGLISH WORDS IN A BENGALI / HINDI LINE (owner, 24 Nov 2026: "majhe majhe kotha english bolche keno?").

Sometimes the story writer puts its stage direction INSIDE the spoken words, e.g.
    "smiles warmly while opening her bag of stories" নিঝুম রাতের আঁধারে ...
and the voice reads it out in English (and the subtitle shows it). Before anything is voiced, every line of a
Bengali / Hindi story is cleaned here:

  * a quoted or bracketed English note ("...", (...), [...], *...*) is taken OUT of the words and kept as the
    line's "action" (so the cartoon still acts it, and nobody says it);
  * a run of 3 or more English words in a Bengali / Hindi line (a direction, not a name) is taken out the same
    way;
  * single English words people really say ("ok", "sorry", "thank you", "police", a name) stay;
  * the voice's own sound tags (<sigh>, <gasp>, <evil laugh>) stay - they become real sounds, not words.

clean_story(story) -> how many lines were cleaned."""
import re

INDIC = re.compile(r"[ঀ-৿ऀ-ॿ]")
QUOTED = re.compile(r"""^\s*(?:["“”'‘’*]+|\(|\[)\s*([A-Za-z][^"“”‘’*\)\]ঀ-৿ऀ-ॿ]{2,200}?)\s*(?:["“”'‘’*]+|\)|\])\s*[:\-–—,.]?\s*""")
ANY_NOTE = re.compile(r"""(?:["“”*]|\(|\[)\s*([A-Za-z][A-Za-z ,.'’\-]{3,200}?)\s*(?:["“”*]|\)|\])""")
EN_RUN = re.compile(r"(?<![<\w])((?:[A-Za-z][A-Za-z'’\-]*[\s,]+){2,}[A-Za-z][A-Za-z'’\-]*)(?![^<]*>)")


SAID = {"thank", "thanks", "you", "very", "much", "good", "morning", "night", "evening", "happy", "birthday", "sorry",
        "ok", "okay", "please", "excuse", "me", "hello", "hi", "bye", "yes", "no", "sir", "madam", "miss", "mister",
        "mr", "mrs", "welcome", "oh", "my", "god", "wow", "super", "great", "hurray", "hurrah"}


def _direction(words):
    """English words that are a stage direction (not something people really say)"""
    ws = [w.lower().strip(".,!?'’") for w in words]
    return len(ws) >= 3 and not all(w in SAID for w in ws)


def clean_text(text):
    """(spoken words, removed English note or '')"""
    t = str(text or "")
    if not INDIC.search(t):
        return t, ""                                   # an English line (or empty): not ours to change
    notes = []
    m = QUOTED.match(t)
    if m:
        notes.append(m.group(1).strip())
        t = t[m.end():]
    for m in list(ANY_NOTE.finditer(t)):
        notes.append(m.group(1).strip())
    t = ANY_NOTE.sub(" ", t)
    for m in list(EN_RUN.finditer(t)):
        if _direction(m.group(1).split()):
            notes.append(m.group(1).strip(" ,"))
    t = EN_RUN.sub(lambda m: " " if _direction(m.group(1).split()) else m.group(0), t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,;:-–—")
    return t, "; ".join(n for n in notes if n)


def clean_story(story):
    n = 0
    for sc in (story or {}).get("scenes") or []:
        for ln in sc.get("lines") or []:
            if not isinstance(ln, dict):
                continue
            new, note = clean_text(ln.get("text", ""))
            if note and new:
                ln["text"] = new
                if ln.get("voice_text"):
                    vt, _n = clean_text(ln["voice_text"])
                    ln["voice_text"] = vt or new
                if not ln.get("action"):
                    ln["action"] = note                # the cartoon still acts it
                n += 1
    return n
