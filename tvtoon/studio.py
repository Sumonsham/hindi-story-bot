"""THE CARTOON STUDIO: story in -> finished Bengali TV cartoon episode out (23 Nov 2026).

A real multi-agent pipeline on the existing tvtoon engine. Every agent below is its own task with its own
responsibility, its own input (files written by earlier agents in the episode folder), its own output files, its own
checks and its own error handling. The Production Manager (agent 01) runs them in dependency order, keeps ONE shared
episode state (episode_state.json = the single source of truth: what each agent produced, how long it took, every
error and retry), retries a failed agent a limited number of times, resumes from the last successful checkpoint
(an agent whose inputs did not change is not run again - no voice, picture or render is ever paid for twice) and
sends Quality Control's findings back to the agent responsible.

  01 ProductionManager   orchestration, dependencies, retries, resume, conflicts, final verification
  02 StoryAnalyst        story.txt -> analysis.json      genre, mood, audience, characters, places, times, weather,
                                                         emotions, actions, transitions, visual needs
  03 Scriptwriter        -> screenplay.json / .md        scene-by-scene screenplay, natural Bengali lines, reactions,
                                                         pauses; a story given as a script is kept as it is
  04 CharacterDirector   -> casting.json, assets/characters   library actor per role (gender, age, human / ghost);
                                                         a NEW supporting character when no library actor suits;
                                                         the registry: id, name, face, body, costume, hair, colours,
                                                         voice, rig
  05 LocationDesigner    -> locations.json               place, room kind, time of day, light, weather, season,
                                                         movement per scene (never one village for every story)
  06 BackgroundArtist    -> assets/backgrounds, props.json   a picture of every place; seats, vehicles, props
  07 StoryboardDirector  -> scene_breakdown.json         placement, entrances, sitting / riding, shots, durations,
                                                         transitions (the tvtoon scene specs)
  08 VoiceDirector       -> audio/, voice_map.json       one voice per character for the whole episode, every
                                                         line recorded once (Gemini in the normal mode, Chirp in
                                                         tests), timing
  09 AnimationDirector   -> acting.json                  gestures from the lines, entrances, emotions, reactions
  10 EnvironmentDirector -> environment.json             wind, rain, fog, lamps, doors, flicker to fit story and hour
  11 Cinematographer     -> scenes/*.mp4                 renders every scene (camera, lip-sync, subtitles)
  08b SoundDesigner      -> scenes/*_mix.mp4             ambience of each place + music by mood under the voices
  11b Editor             -> final_episode.mp4            title card, scenes with transitions, end card
  12 QualityControl      -> qc_report.md / .json         consistency, backgrounds, lip-sync, dialogue, audio,
                                                         black frames, duration, resolution, fps, file integrity;
                                                         failures go back to the responsible agent
  01 delivery            -> production_report.md         the episode folder: final_episode.mp4, screenplay.md,
                                                         scene_breakdown.json, production_report.md, qc_report.md,
                                                         audio/, assets/

Run:  python -m tvtoon.studio <story.txt> [out_dir] [--voice gemini|chirp|none] [--portrait] [--max-scenes N]
Gemini (GEMINI_API_KEY) helps the analyst and the scriptwriter when present (the free lite model, at most 2 calls);
without it the rule-based analyst and scriptwriter work offline. No picture service is used: every place and person
is drawn by the engine."""
import copy
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_TRIES = 2


def _frame(settings):
    """the picture size of the episode: 1920x1080 (16:9), 1080x1920 when portrait; a small preview in tests"""
    if settings.get("preview"):
        return (180, 320) if settings.get("portrait") else (320, 180)
    return (1080, 1920) if settings.get("portrait") else (1920, 1080)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _h(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


def _dur(path):
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                    capture_output=True, text=True).stdout.strip() or 0)
    except Exception:
        return 0.0


# ===================================================================================================== shared state
class Episode:
    """the episode folder and its single source of truth (episode_state.json)"""

    def __init__(self, out_dir, settings):
        self.dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        for d in ("audio", "assets/characters", "assets/backgrounds", "scenes", "_work"):
            os.makedirs(os.path.join(out_dir, d), exist_ok=True)
        self.path = os.path.join(out_dir, "episode_state.json")
        self.state = json.load(open(self.path, encoding="utf-8")) if os.path.exists(self.path) else \
            {"created": _now(), "stages": {}, "events": [], "settings": {}}
        self.state["settings"] = settings
        self.save()

    def p(self, *a):
        return os.path.join(self.dir, *a)

    def read(self, name):
        return json.load(open(self.p(name), encoding="utf-8"))

    def write(self, name, obj):
        with open(self.p(name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        return self.p(name)

    def write_text(self, name, text):
        with open(self.p(name), "w", encoding="utf-8") as f:
            f.write(text)
        return self.p(name)

    def event(self, agent, kind, msg):
        self.state["events"].append({"t": _now(), "agent": agent, "kind": kind, "msg": str(msg)[:600]})
        self.save()

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)


class Agent:
    """one specialised assistant: a fixed job, declared inputs and outputs, its own checks"""
    id = "00"
    name = "agent"
    needs = ()           # files from earlier agents
    makes = ()           # files this agent writes (relative to the episode folder)

    def __init__(self, ep, log=print):
        self.ep, self.log = ep, log

    def input_hash(self):
        parts = []
        for n in self.needs:
            p = self.ep.p(n)
            parts.append(open(p, "rb").read() if os.path.isfile(p) else b"")
        return hashlib.sha1(b"|".join(parts) + json.dumps(self.ep.state["settings"], sort_keys=True).encode()).hexdigest()[:12]

    def run(self):
        raise NotImplementedError

    def check(self):
        """the agent's own verification of its outputs: [] when fine, else a list of problems"""
        return [f"missing {m}" for m in self.makes if not os.path.exists(self.ep.p(m))]


# ===================================================================================================== 02 analyst
GENRES = [("horror", ["ভূত", "পেত্নী", "প্রেত", "আত্মা", "অশরীরী", "শাঁকচুন্নি", "ব্রহ্মদৈত্য", "ghost", "haunted", "horror", "ভয়"]),
          ("mystery", ["রহস্য", "খুন", "গোয়েন্দা", "mystery", "murder", "detective"]),
          ("mythology", ["দেবী", "দেবতা", "ঠাকুর", "পুরাণ", "রাক্ষস", "god", "goddess", "myth"]),
          ("adventure", ["অভিযান", "জঙ্গল", "গুপ্তধন", "adventure", "treasure", "jungle"]),
          ("comedy", ["হাসি", "মজা", "হা হা", "funny", "comedy", "joke"]),
          ("historical", ["রাজা", "নবাব", "সাল", "যুগ", "king", "nawab", "century", "ইংরেজ"])]
FEMALE_WORDS = ["মা", "দিদি", "বৌদি", "বউদি", "ঠাকুমা", "দিদিমা", "মাসি", "পিসি", "কাকিমা", "জেঠিমা", "মেয়ে", "রানি", "দেবী",
                "পেত্নী", "শাঁকচুন্নি", "ডাইনি", "বউ", "বৌ", "মেম"]
MALE_WORDS = ["দাদু", "কাকা", "বাবা", "দাদা", "বাবু", "মামা", "জেঠু", "ছেলে", "রাজা", "ঠাকুর", "মশাই", "ব্রহ্মদৈত্য", "ওঝা"]
OLD_WORDS = ["দাদু", "ঠাকুমা", "দিদিমা", "বুড়ো", "বুড়ি", "জেঠু", "জেঠিমা"]
CHILD_WORDS = ["খোকা", "খুকি", "ছোট্ট", "বাচ্চা", "শিশু"]
GHOST_WORDS = ["ভূত", "পেত্নী", "প্রেত", "আত্মা", "অশরীরী", "শাঁকচুন্নি", "ব্রহ্মদৈত্য", "ছায়ামূর্তি", "ডাইনি", "নিশি"]
FEMALE_NAMES = ("া", "ী", "ি")      # common endings of Bengali women's names (রিয়া, মিতালী, ...) - a soft hint only


def _gender_of(name, context=""):
    n = str(name)
    if re.search(r"(দা|বাবু|কাকু|ওয়ালা|মশাই|দাদু)(\s|$)", n):
        return "male"
    if any(w in n for w in FEMALE_WORDS):
        return "female"
    if any(w in n for w in MALE_WORDS):
        return "male"
    return "female" if n.endswith(FEMALE_NAMES[:2]) and len(n) > 2 else "male"


def _age_of(name):
    n = str(name)
    if any(w in n for w in OLD_WORDS):
        return "old"
    if any(w in n for w in CHILD_WORDS):
        return "child"
    return "adult"


def _gemini(prompt, log=print):
    key = os.environ.get("GEMINI_API_KEY")
    if not key or os.environ.get("STUDIO_GEMINI") == "0":
        return None
    import requests
    for model in ("gemini-flash-lite-latest",):
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 16000,
                                                         "responseMimeType": "application/json"}}, timeout=180)
            if not r.ok:
                log(f"    Gemini {model}: HTTP {r.status_code} - the offline rules are used")
                return None
            parts = r.json()["candidates"][0]["content"]["parts"]
            return json.loads("".join(p.get("text", "") for p in parts if not p.get("thought")))
        except Exception as e:
            log(f"    Gemini {model}: {str(e)[:120]} - the offline rules are used")
    return None


SCRIPT_LINE = re.compile(r"^\s*([^\s:：—\-–][^:：—]{0,30}?)\s*[:：]\s*(.+)$")


def split_scenes(text):
    """paragraph blocks -> scenes (explicit 'দৃশ্য' / 'Scene' / '#' headings win)"""
    raw = text.replace("\r", "")
    blocks = [b.strip() for b in re.split(r"\n\s*(?:দৃশ্য\s*[০-৯0-9]*|scene\s*[0-9]*|#+)[^\n]*\n", raw, flags=re.I) if b.strip()]
    if len(blocks) <= 1:
        # a paragraph that opens with narration (where, when, what happens) starts a new scene; a paragraph of only
        # spoken lines continues the scene before it; a story told as one long text is cut into ~900-letter scenes
        paras = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
        blocks = []
        for p_ in paras:
            first = p_.splitlines()[0]
            if blocks and SCRIPT_LINE.match(first):
                blocks[-1] += "\n" + p_
            else:
                blocks.append(p_)
        out = []
        for b in blocks:
            while len(b) > 1400:
                cut = b.rfind("।", 0, 900)
                cut = cut + 1 if cut > 200 else 900
                out.append(b[:cut].strip())
                b = b[cut:].strip()
            if b:
                out.append(b)
        blocks = out
    if len(blocks) > 1 and "\n" not in blocks[0] and len(blocks[0]) < 70 and not SCRIPT_LINE.match(blocks[0]):
        blocks = blocks[1:]                                  # the title line alone is not a scene
    return blocks


class StoryAnalyst(Agent):
    id, name = "02", "Story Analyst"
    needs = ("story.txt",)
    makes = ("analysis.json",)

    def run(self):
        from tvtoon import story as STY
        text = open(self.ep.p("story.txt"), encoding="utf-8").read().strip()
        if not text:
            raise ValueError("the story is empty")
        lines = [x for x in text.splitlines() if x.strip()]
        title = lines[0].strip(" #*") if len(lines[0]) < 70 else "নতুন গল্প"
        low = text.lower()
        genre = max(GENRES, key=lambda g: sum(low.count(w) for w in g[1]))
        genre = genre[0] if sum(low.count(w) for w in genre[1]) else "family"
        speakers = []
        for ln in lines:
            m = SCRIPT_LINE.match(ln)
            if m and m.group(1).strip() not in ("দৃশ্য", "Scene") and len(m.group(1)) <= 30:
                nm = m.group(1).strip(" *")
                if nm not in speakers and nm.lower() not in ("narrator", "কথক", "বর্ণনা"):
                    speakers.append(nm)
        blocks = split_scenes(text)
        places, times = [], []
        for b in blocks:
            loc = STY.place_of(b)
            places.append({"text": b[:160], "location": loc, "room": STY.room_kind(b) if loc == "ghar" else None})
            times.append(STY.hours_of(b))
        weather = []
        for b in blocks:
            w = [k for k, ws in (("rain", ["বৃষ্টি", "rain"]), ("storm", ["ঝড়", "storm"]), ("fog", ["কুয়াশা", "fog", "mist"]),
                                 ("wind", ["হাওয়া", "বাতাস", "wind"])) if any(x in b.lower() for x in ws)]
            weather.append(w)
        emo = []
        for b in blocks:
            e = "scared" if any(w in b for w in ("ভয়", "চিৎকার", "কাঁপ")) else "happy" if any(w in b for w in ("হাস", "আনন্দ")) else \
                "sad" if any(w in b for w in ("কাঁদ", "দুঃখ")) else "neutral"
            emo.append(e)
        a = {"title": title, "genre": genre, "mood": {"horror": "creepy", "mystery": "tense", "comedy": "happy"}.get(genre, "calm"),
             "audience": "family (all ages)" if genre in ("family", "comedy", "mythology", "adventure") else "teen and adult",
             "speakers": speakers, "scene_count": len(blocks), "places": places, "times": times, "weather": weather,
             "emotions": emo, "is_script": len(speakers) > 0 and sum(1 for ln in lines if SCRIPT_LINE.match(ln)) >= max(2, len(lines) // 4),
             "ghost_words": [w for w in GHOST_WORDS if w in text], "method": "rules"}
        g = _gemini("You are the story analyst of a Bengali TV cartoon studio. Read the story and return JSON with keys: "
                    "title, genre, mood, audience, characters (list of {name, gender male/female, age child/young/adult/old, "
                    "kind human/ghost, look: short English description of face, hair, clothes}), "
                    "visual_needs (list of short English notes). Use the story's own names.\n\nSTORY:\n" + text[:20000], self.log)
        if isinstance(g, dict) and g.get("characters"):
            a.update({k: g[k] for k in ("title", "genre", "mood", "audience", "characters", "visual_needs") if g.get(k)})
            a["method"] = "gemini + rules"
        self.ep.write("analysis.json", a)
        self.log(f"  genre {a['genre']}, {a['scene_count']} scenes, places: " + ", ".join(p['location'] + (f"/{p['room']}" if p['room'] else "") for p in places))


# ===================================================================================================== 03 scriptwriter
class Scriptwriter(Agent):
    id, name = "03", "Scriptwriter & Screenplay Director"
    needs = ("story.txt", "analysis.json")
    makes = ("screenplay.json", "screenplay.md")

    def run(self):
        text = open(self.ep.p("story.txt"), encoding="utf-8").read().strip()
        a = self.ep.read("analysis.json")
        sp = None
        if not a.get("is_script"):
            g = _gemini("You are the screenwriter of a Bengali TV cartoon. Turn the story into a screenplay WITHOUT changing the plot. "
                        "Return JSON: {title, characters:[{name, gender, age, kind, look}], ghost_reveal:{name: scene number} "
                        "(only for a ghost that first seems a normal person), scenes:[{place: English place description with "
                        "time of day and weather, mood, lines:[{speaker: a character name or 'narrator', text: natural spoken "
                        "Bengali, emotion: one of normal, happy, sad, scared, angry, surprised, laughing, crying, eerie}]}]}. "
                        "Keep the story's own words where they are dialogue; narration stays narration (speaker narrator), "
                        "short lines (one or two sentences each), add small reactions where natural.\n\nSTORY:\n" + text[:20000],
                        self.log)
            if isinstance(g, dict) and g.get("scenes"):
                sp = g
                sp["method"] = "gemini"
        if sp is None:
            sp = self._rules(text, a)
        sp.setdefault("title", a.get("title"))
        for c in sp.get("characters", []):                  # the analyst's view of each person, when it has one
            for ac in a.get("characters", []) or []:
                if str(ac.get("name")) == str(c.get("name")):
                    for k in ("gender", "age", "kind", "look"):
                        c.setdefault(k, ac.get(k))
        problems = [f"scene {i + 1} has no lines" for i, s in enumerate(sp["scenes"]) if not s.get("lines")]
        if problems:
            sp["scenes"] = [s for s in sp["scenes"] if s.get("lines")]
            self.ep.event(self.name, "fixed", "; ".join(problems) + " - removed")
        if not sp["scenes"]:
            raise ValueError("the screenplay has no scene with words")
        self.ep.write("screenplay.json", sp)
        md = [f"# {sp['title']}", "", f"*{a.get('genre')}, {a.get('mood')}*", ""]
        for i, s in enumerate(sp["scenes"]):
            md += [f"## দৃশ্য {i + 1}: {s.get('place', '')}", ""]
            for ln in s["lines"]:
                who = "কথক" if str(ln.get("speaker", "")).lower() in ("narrator", "কথক") else ln.get("speaker")
                emo = f" *({ln.get('emotion')})*" if ln.get("emotion") and ln.get("emotion") != "normal" else ""
                md.append(f"**{who}**{emo}: {ln['text']}")
                md.append("")
        self.ep.write_text("screenplay.md", "\n".join(md))
        self.log(f"  {len(sp['scenes'])} scenes, {sum(len(s['lines']) for s in sp['scenes'])} lines ({sp.get('method', 'rules')})")

    def _rules(self, text, a):
        """offline: a given script is kept line for line; prose becomes narration, quoted speech becomes lines"""
        scenes, names = [], []
        for bi, b in enumerate(split_scenes(text)):
            lines = []
            for raw in b.splitlines():
                raw = raw.strip()
                if not raw or (bi == 0 and raw.strip(" #*") == a.get("title")):
                    continue
                m = SCRIPT_LINE.match(raw)
                if m and len(m.group(1)) <= 30 and m.group(1).strip() not in ("দৃশ্য", "Scene"):
                    who = m.group(1).strip(" *")
                    who = "narrator" if who.lower() in ("narrator", "কথক", "বর্ণনা") else who
                    txt = m.group(2).strip()
                    if who != "narrator" and who not in names:
                        names.append(who)
                    lines.append({"speaker": who, "text": txt, "emotion": self._emo(txt)})
                    continue
                for part in re.split(r"(“[^”]+”|\"[^\"]+\")", raw):    # quoted speech inside prose
                    part = part.strip()
                    if not part:
                        continue
                    if part[0] in "“\"":
                        lines.append({"speaker": names[-1] if names else "narrator", "text": part.strip("“”\""),
                                      "emotion": self._emo(part)})
                    else:
                        for sent in [x.strip() for x in re.split(r"(?<=[।!?])\s+", part) if x.strip()]:
                            if lines and lines[-1]["speaker"] == "narrator" and len(lines[-1]["text"]) + len(sent) < 140:
                                lines[-1]["text"] += " " + sent
                            else:
                                lines.append({"speaker": "narrator", "text": sent, "emotion": "normal"})
            scenes.append({"place": b[:200].replace("\n", " "), "mood": a.get("mood", "calm"), "lines": lines})
        chars = []
        for n in names:
            kind = "ghost" if any(w in n for w in GHOST_WORDS) else "human"
            chars.append({"name": n, "gender": _gender_of(n), "age": _age_of(n), "kind": kind})
        return {"title": a.get("title"), "characters": chars, "scenes": scenes, "method": "rules"}

    @staticmethod
    def _emo(t):
        if any(w in t for w in ("ভয়", "বাঁচাও", "কে ওখানে", "কে?", "আ-আ")):
            return "scared"
        if any(w in t for w in ("হা হা", "হাহা", "হি হি")):
            return "laughing"
        if any(w in t for w in ("কাঁদ", "হায়", "দুঃখ")):
            return "sad"
        if "!" in t and any(w in t for w in ("খবরদার", "চুপ", "বেরিয়ে যা")):
            return "angry"
        if "!" in t or "?" in t and "কী" in t:
            return "surprised" if "!" in t else "normal"
        return "normal"


# ===================================================================================================== 04 characters
class CharacterDirector(Agent):
    id, name = "04", "Character Director"
    needs = ("screenplay.json",)
    makes = ("casting.json",)

    def run(self):
        from tvtoon import characters as CH
        from tvtoon import qa
        from tvtoon import story as STY
        from tvtoon import voices as VO
        sp = self.ep.read("screenplay.json")
        used, cast, registry, created = set(), {}, {}, []
        lib = CH.library()
        reveal = {}
        for k, v in (sp.get("ghost_reveal") or {}).items():
            try:
                reveal[k] = int(v)
            except (TypeError, ValueError):
                pass
        sp["ghost_reveal"] = reveal
        speaking = {str(ln.get("speaker")) for s in sp["scenes"] for ln in s["lines"]}
        chars = [c for c in sp.get("characters", []) if str(c.get("name")) in speaking]
        for c in chars:
            name = str(c["name"])
            kind = "ghost" if str(c.get("kind", "human")).lower() in ("ghost", "spirit", "demon") else "human"
            g = "female" if str(c.get("gender", "male")).lower().startswith("f") else "male"
            age = STY._age(c.get("age"))
            actor = None
            if kind == "ghost" and not (g == "male" and name in reveal):
                pool = [x for x in lib if x not in used and CH.profile(x)[0] == "ghost" and CH.profile(x)[1] == g]
                actor = pool[0] if pool else None
            elif kind == "ghost":                            # a man's ghost that first seems alive: a man of his age
                pool = [x for x in lib if x not in used and CH.profile(x) == ("human", g, age)]
                actor = (pool[0] + "__ghost") if pool else None
            else:
                pool = [x for x in lib if x not in used and CH.profile(x) == ("human", g, age)]
                actor = pool[0] if pool else None
            if actor is None:                               # no library actor suits: a NEW supporting character
                cid = "ep_" + re.sub(r"[^a-z0-9]+", "_", hashlib.sha1(name.encode()).hexdigest()[:8])
                best = None
                for seed in range(6):
                    spec = CH.new_character(cid, name, g, age, c.get("look", ""), seed=seed)
                    d = min([qa.identity_distance(spec, CH.get(o)) for o in list(used) + lib[:6] if o.split("__")[0] in CH.SPECS]
                            or [9])
                    if best is None or d > best[0]:
                        best = (d, seed)
                    if d >= 4:
                        break
                spec = CH.new_character(cid, name, g, age, c.get("look", ""), seed=best[1])
                self.ep.write(f"assets/characters/{cid}.json", spec)
                created.append(cid)
                male_v = ["Charon", "Fenrir", "Enceladus", "Umbriel", "Schedar", "Zubenelgenubi", "Iapetus", "Alnilam"]
                fem_v = ["Callirrhoe", "Autonoe", "Erinome", "Pulcherrima", "Sulafat", "Zephyr", "Laomedeia", "Despina"]
                pool_v = fem_v if g == "female" else male_v
                taken = {VO.VOICE[x.split("__")[0]][0] for x in used if x.split("__")[0] in VO.VOICE}
                voice = next((v for v in pool_v if v not in taken), pool_v[0])
                VO.VOICE[cid] = (voice, f"a Bengali {age} {'woman' if g == 'female' else 'man'} called {name}")
                if g == "female":
                    VO.FEMALE.add(cid)
                if age == "child":
                    VO.CHILD.add(cid)
                actor = cid + ("__ghost" if kind == "ghost" else "")
            used.add(actor.split("__")[0])
            cast[name] = (actor, c.get("name_local") or name)
            base = actor.split("__")[0]
            s = CH.get(base)
            registry[name] = {"id": actor, "name": name, "library": base not in created, "face": s["head"]["shape"] + ", " +
                              s["face"]["eye_style"] + " eyes, " + s["face"]["nose"] + " nose",
                              "body": {"height": s["height"], "heads": s["heads"]}, "costume": s["costume"]["type"],
                              "hair": s["hair"]["style"], "colours": s["colours"], "voice": VO.VOICE.get(base, ("?",))[0],
                              "rig": "tvtoon puppet (rig.py skeleton) + profile.py side view", "kind": kind,
                              "gender": g, "age": age, "emotion": "neutral"}
        unknown = sorted(speaking - set(cast) - {"narrator", "কথক"})
        for name in unknown:                                # a speaker the screenplay forgot to list: cast too
            sp.setdefault("characters", []).append({"name": name, "gender": _gender_of(name), "age": _age_of(name)})
        if unknown:
            self.ep.write("screenplay.json", sp)
            raise RuntimeError("retry: characters added for " + ", ".join(unknown))
        self.ep.write("casting.json", {"cast": {k: list(v) for k, v in cast.items()}, "registry": registry, "created": created})
        self.log("  " + ", ".join(f"{k}={v[0]}" for k, v in cast.items()) + (f"; new: {', '.join(created)}" if created else ""))


def _load_cast(ep):
    """the episode's own characters back into the library (a resumed run), and the cast mapping"""
    from tvtoon import characters as CH
    from tvtoon import voices as VO
    c = ep.read("casting.json")
    for cid in c.get("created", []):
        CH.register(cid, ep.read(f"assets/characters/{cid}.json"))
        reg = next((r for r in c["registry"].values() if r["id"].split("__")[0] == cid), None)
        if reg:
            VO.VOICE.setdefault(cid, (reg["voice"], f"a Bengali {reg['age']} {'woman' if reg['gender'] == 'female' else 'man'}"))
            if reg["gender"] == "female":
                VO.FEMALE.add(cid)
            if reg["age"] == "child":
                VO.CHILD.add(cid)
    return {k: tuple(v) for k, v in c["cast"].items()}, c


# ===================================================================================================== 05 locations
class LocationDesigner(Agent):
    id, name = "05", "Location & World Designer"
    needs = ("screenplay.json",)
    makes = ("locations.json",)

    def run(self):
        from tvtoon import story as STY
        sp = self.ep.read("screenplay.json")
        whole = " ".join(str(sp.get(k, "")) for k in ("title", "logline", "setting")) + " " + \
            " ".join(s.get("place", "") for s in sp["scenes"][:1])
        hour = 21.5 if any(w in whole.lower() for w in STY.NIGHT) else None
        out = []
        for i, s in enumerate(sp["scenes"]):
            place = s.get("place", "")
            loc = STY.place_of(place)
            ride = None
            if loc == "ride":
                ride = "auto" if any(w in place.lower() for w in ("auto", "অটো")) else "toto"
                loc = "city_street" if any(w in place.lower() for w in ("kolkata", "city", "কলকাতা")) else "village_road"
            hour = STY.hours_of(place, s.get("mood", ""), inherit=hour)
            pl = place.lower()
            weather = [w for w, ws in (("rain", ["rain", "বৃষ্টি"]), ("storm", ["storm", "ঝড়", "lightning"]), ("fog", ["fog", "mist", "কুয়াশা"]))
                       if any(x in pl for x in ws)]
            month = dt.date.today().month
            season = "monsoon" if "rain" in weather or 6 <= month <= 9 else "winter" if month in (11, 12, 1, 2) else "summer"
            light = ("moonlight and lamps" if hour >= 20 or hour < 5 else "dusk glow" if hour >= 17 else "daylight")
            out.append({"scene": i + 1, "place_text": place, "location": loc, "room": STY.room_kind(place) if loc == "ghar" else None,
                        "ride": ride, "hour": hour, "light": light, "weather": weather, "season": season,
                        "movement": {"ghar": "curtain, lamp, fan, door", "boat": "waves, lantern, rocking"}.get(loc, "wind, sky, layers")})
        kinds = {(o["location"], o["room"]) for o in out}
        if len(out) >= 4 and len(kinds) == 1 and out[0]["location"] == "ghar":
            self.ep.event(self.name, "note", "every scene is in the same kind of room - the story says so")
        self.ep.write("locations.json", out)
        self.log("  " + "; ".join(f"{o['scene']}:{o['location']}{'/' + o['room'] if o['room'] else ''} {o['hour']:g}h"
                                  + (f" {','.join(o['weather'])}" if o["weather"] else "") for o in out))


# ===================================================================================================== 06 backgrounds
class BackgroundArtist(Agent):
    id, name = "06", "Background & Props Artist"
    needs = ("locations.json",)
    makes = ("props.json",)

    def run(self):
        import cv2
        from tvtoon import scene as SC
        locs = self.ep.read("locations.json")
        props, done = [], {}
        for o in locs:
            key = (o["location"], o["room"], round(o["hour"]), tuple(o["weather"]))
            fn = f"assets/backgrounds/scene_{o['scene']:02d}_{o['location']}{'_' + o['room'] if o['room'] else ''}.jpg"
            if key in done:
                shutil.copy(self.ep.p(done[key]), self.ep.p(fn))
            else:
                world = {"hours": [[0, o["hour"]]]}
                if o["room"]:
                    world.update(kind=o["room"], text=f"{self.ep.state['settings'].get('title', '')}|{o['room']}")
                if "rain" in o["weather"] and o["location"] != "ghar" and not o["location"].endswith("_inside"):
                    world["rain"] = [[0, 99]]
                sc = SC.Scene({"location": o["location"], "world": world, "size": [960, 540], "cast": [],
                               "beats": [{"pause": 2.0, "shot": "wide"}]})
                cv2.imwrite(self.ep.p(fn), sc.render_frame(1.0), [cv2.IMWRITE_JPEG_QUALITY, 88])
                done[key] = fn
            p = {"scene": o["scene"], "background": fn, "seats": o["location"].endswith("_inside") or o["room"] in ("palki", "hold"),
                 "vehicles": [o["ride"]] if o["ride"] else {"station": ["train"], "city_street": ["tram"], "village_road": ["toto"]}.get(o["location"], []),
                 "props": {"kitchen": ["clay stove", "pots"], "hall": ["pillars", "chandelier", "portraits"], "hospital": ["iron beds", "drip stand"],
                           "office": ["desk", "table lamp", "bookshelf"], "studio": ["microphone", "console"], "shed": ["tools", "sacks"],
                           "flat": ["sofa", "television"], "classroom": ["blackboard", "benches"]}.get(o["room"] or "", [])}
            props.append(p)
        self.ep.write("props.json", props)
        self.log(f"  {len(done)} different backgrounds for {len(locs)} scenes")

    def check(self):
        bad = super().check()
        for p in (self.ep.read("props.json") if os.path.exists(self.ep.p("props.json")) else []):
            if not os.path.exists(self.ep.p(p["background"])):
                bad.append(f"background missing for scene {p['scene']}")
        return bad


# ===================================================================================================== 07 storyboard
class StoryboardDirector(Agent):
    id, name = "07", "Storyboard & Scene Director"
    needs = ("screenplay.json", "casting.json", "locations.json")
    makes = ("scene_breakdown.json",)

    def run(self):
        from tvtoon import story as STY
        sp = self.ep.read("screenplay.json")
        cast, _c = _load_cast(self.ep)
        locs = self.ep.read("locations.json")
        st = self.ep.state["settings"]
        story = {"title": sp.get("title", ""), "characters": sp.get("characters", []), "ghost_reveal": sp.get("ghost_reveal") or {},
                 "scenes": [dict(s, place=s.get("place", "")) for s in sp["scenes"]]}
        ep = STY.episode_from_story(story, max_scenes=st.get("max_scenes"), aspect="9:16" if st.get("portrait") else "16:9", cast=cast)
        scenes = []
        for i, sc in enumerate(ep["scenes"]):
            o = locs[i]
            sc["world"]["hours"] = [[0, o["hour"]]]
            sc["fps"] = 24
            sc["scene_id"] = f"S{i + 1:02d}"
            same = i > 0 and locs[i - 1]["location"] == o["location"] and locs[i - 1]["room"] == o["room"]
            sc["transition"] = "cut" if same else "fade"
            n_lines = sum(1 for b in sc["beats"] if "say" in b or "narrate" in b)
            sc["planned_lines"] = n_lines
            scenes.append(sc)
        for sc, s in zip(scenes, sp["scenes"]):               # every screenplay line must be in its scene
            want = len([ln for ln in s["lines"] if (ln.get("text") or "").strip()])
            if sc["planned_lines"] != want:
                raise RuntimeError(f"scene {sc['scene_id']}: {sc['planned_lines']} of {want} lines planned")
        self.ep.write("scene_breakdown.json", {"title": ep["title"], "cast": ep["cast"], "scenes": scenes})
        self.log(f"  {len(scenes)} scenes planned, transitions: " + "".join("|" if s["transition"] == "cut" else "~" for s in scenes))


# ===================================================================================================== 08 voices
class VoiceDirector(Agent):
    id, name = "08", "Voice & Audio Director"
    needs = ("scene_breakdown.json", "casting.json")
    makes = ("voice_map.json",)

    def run(self):
        from tvtoon import voices as VO
        _load_cast(self.ep)
        eng = self.ep.state["settings"].get("voice", "gemini")
        os.environ["TVTOON_VOICE"] = eng
        sb = self.ep.read("scene_breakdown.json")
        timing, silent, n, assign = [], 0, 0, {}
        for sc in sb["scenes"]:
            for k, b in enumerate(sc["beats"]):
                if "say" not in b and "narrate" not in b:
                    continue
                who = b.get("who", "narrator") if "say" in b else "narrator"
                text = b.get("say") or b.get("narrate")
                n += 1
                dst = self.ep.p("audio", f"{sc['scene_id']}_{k:03d}_{who.split('__')[0]}.wav")
                if os.path.exists(dst) and os.path.getsize(dst) > 2000:
                    how = "kept (already recorded)"
                else:
                    aud, how = (None, "no voice (--voice none)") if eng == "none" else \
                        VO.line(who, text, b.get("emotion", "neutral"), log=self.log)
                    if aud and os.path.exists(aud):
                        shutil.copy(aud, dst)
                rel = os.path.relpath(dst, self.ep.dir) if os.path.exists(dst) else None
                assign[f"{sc['scene_id']}:{k}"] = rel
                silent += rel is None
                timing.append({"scene": sc["scene_id"], "beat": k, "who": who, "text": text, "file": rel,
                               "seconds": round(_dur(dst), 2) if rel else None, "how": how})
        voices = {}
        for t in timing:
            base = t["who"].split("__")[0]
            voices.setdefault(base, {"voice": VO.VOICE.get(base, ("Kore" if base in VO.FEMALE else "Orus",))[0],
                                     "female": base in VO.FEMALE, "engine": eng})
        self.ep.write("voice_map.json", {"engine": eng, "voices": voices, "audio": assign, "lines": timing,
                                         "silent_lines": silent, "total_lines": n})
        self.log(f"  {n - silent}/{n} lines voiced ({eng})" + (f"; {silent} silent with subtitles" if silent else ""))


# ===================================================================================================== 09 acting
GESTURE_WORDS = [("point", ["ওই", "ওখানে", "দেখো", "দেখ", "ওইদিকে"]), ("namaste", ["নমস্কার", "প্রণাম"]),
                 ("wave", ["এসো", "আয়", "চলো"]), ("think", ["ভাবছি", "মনে হয়", "হয়তো"]), ("shrug", ["জানি না", "কে জানে"]),
                 ("scared", ["বাঁচাও", "ভয়"]), ("hips", ["খবরদার"])]


class AnimationDirector(Agent):
    id, name = "09", "Character Animation Director"
    needs = ("scene_breakdown.json",)
    makes = ("acting.json",)

    def run(self):
        sb = self.ep.read("scene_breakdown.json")
        plan, notes = {}, []
        for sc in sb["scenes"]:
            sid = sc["scene_id"]
            seated = {b.get("who") for b in sc["beats"] if b.get("sit") or b.get("ride")}
            p = {"cast_x": {}, "after": []}                 # beats to add after a planned beat (its index)
            first_pause = next((k for k, b in enumerate(sc["beats"]) if "pause" in b), None)
            if sc["cast"] and first_pause is not None and sc["location"] != "boat" and not seated:
                c = sc["cast"][0]                           # the first person walks into the picture
                x = float(c.get("x", 1600))
                p["cast_x"][c["id"]] = x - 700
                p["after"].append([first_pause, {"who": c["id"], "walk_to": x, "with_prev": True}])
                notes.append(f"{sid}: {c['id']} walks in")
            for k, b in enumerate(sc["beats"]):
                if "say" in b and b.get("who") not in seated:
                    g = next((n for n, ws in GESTURE_WORDS if any(w in b["say"] for w in ws)), None)
                    if g:
                        p["after"].append([k, {"who": b["who"], "gesture": g, "sec": 1.6, "with_prev": True}])
                        notes.append(f"{sid}: {b['who']} {g}")
            plan[sid] = p
        self.ep.write("acting.json", {"scenes": plan, "notes": notes,
                                      "automatic": ["blinks", "breathing", "eye darts", "head turns to the speaker",
                                                    "listener nods and reactions", "emotion body acting", "lip-sync from the voice",
                                                    "side view for walking / sitting / riding", "hair and cloth springs"]})
        self.log(f"  {len(notes)} acting notes (entrances, gestures)")


# ===================================================================================================== 10 environment
class EnvironmentDirector(Agent):
    id, name = "10", "Environment Animation Director"
    needs = ("scene_breakdown.json", "locations.json", "analysis.json")
    makes = ("environment.json",)

    def run(self):
        sb = self.ep.read("scene_breakdown.json")
        locs = self.ep.read("locations.json")
        rows = {}
        for sc, o in zip(sb["scenes"], locs):
            w = dict(sc["world"])
            indoor = sc["location"] == "ghar" or sc["location"].endswith("_inside")
            ov = {}
            ov["wind"] = 0.95 if "storm" in o["weather"] else max(w.get("wind", 0.5), 0.65) if "rain" in o["weather"] else w.get("wind", 0.45)
            if ("rain" in o["weather"] or "storm" in o["weather"]) and not indoor:
                ov["rain"] = [[0.0, 9999.0]]
                if 9 <= o["hour"] <= 16:                    # a rainy day is grey, never bright sunshine
                    ov["hours"] = [[0, 16.8]]
            if "fog" in o["weather"] and not indoor:
                ov["fog"] = 0.45
            w.update(ov)
            rows[sc["scene_id"]] = {"world": ov, "location": sc["location"], "hour": w["hours"][0][1], "rain": bool(w.get("rain")),
                                    "fog": w.get("fog", 0), "door_open_at": w.get("door_open_at"), "flicker": w.get("flicker"),
                                    "effects": self._effects(sc["location"], w)}
        self.ep.write("environment.json", rows)
        self.log("  " + "; ".join(f"{k} {r['effects']}" for k, r in list(rows.items())[:6]) + (" ..." if len(rows) > 6 else ""))

    @staticmethod
    def _effects(loc, w):
        base = {"village_courtyard": "clouds, palms, smoke, ripples", "shmashan": "fire, sparks, smoke, owl", "bansh_bon": "bamboo, mist, fireflies",
                "pukur_ghat": "ripples, lotus, lantern", "station": "train, signal, lamps, moths", "village_road": "fields, wires, tea steam",
                "city_street": "tram wires, windows", "ghar": "curtain, lamp, fan, door", "boat": "waves, lantern, rocking",
                "market": "awnings, bunting, bulbs, shoppers", "temple": "flag, bell, diyas, incense", "mountain": "pines, fog bands",
                "seaside": "waves, foam, palms", "school": "flag, bell", "train_inside": "outside passing, fans, lights, sway",
                "bus_inside": "outside passing, straps, bumps", "tram_inside": "city passing, straps, clack"}.get(loc, "motion layers")
        if w.get("rain"):
            base += ", rain"
        if w.get("fog"):
            base += ", fog"
        return base


def compose(ep):
    """the final scene specs: the storyboard + the voices (08) + the acting (09) + the environment (10) - each agent
    keeps its own file, the specs are put together here, so a change in one never forces another to work again"""
    sb = ep.read("scene_breakdown.json")
    vm = ep.read("voice_map.json")
    act = ep.read("acting.json")["scenes"]
    env = ep.read("environment.json")
    st = ep.state["settings"]
    out = []
    for sc in sb["scenes"]:
        sid = sc["scene_id"]
        spec = copy.deepcopy(sc)
        for k, b in enumerate(spec["beats"]):
            f = vm["audio"].get(f"{sid}:{k}")
            if f:
                b["audio"] = ep.p(f)
        a = act.get(sid, {})
        for c in spec["cast"]:
            if c["id"] in a.get("cast_x", {}):
                c["x"] = a["cast_x"][c["id"]]
        for k, nb in sorted(a.get("after", []), key=lambda r: -r[0]):
            spec["beats"].insert(k + 1, nb)
        spec["world"].update(env.get(sid, {}).get("world", {}))
        if st.get("portrait"):
            spec["aspect"] = "9:16"
        if st.get("preview"):                                # (tests: a small picture, the same pipeline)
            spec["size"] = list(_frame(st))
        out.append(spec)
    return out


# ===================================================================================================== 11 rendering
class Cinematographer(Agent):
    id, name = "11", "Cinematographer (camera + scene render)"
    needs = ("scene_breakdown.json", "voice_map.json", "acting.json", "environment.json")
    makes = ("render_report.json",)

    def run(self, only=None):
        from tvtoon import scene as SC
        _load_cast(self.ep)
        prev = self.ep.read("render_report.json") if os.path.exists(self.ep.p("render_report.json")) else {}
        rep = {}
        specs = compose(self.ep)
        self.ep.write("scenes/final_specs.json", specs)
        for spec in specs:
            sid = spec["scene_id"]
            out = self.ep.p("scenes", f"{sid}.mp4")
            key = _h(spec)
            if prev.get(sid, {}).get("key") == key and os.path.exists(out):
                rep[sid] = prev[sid]
                continue
            t0 = time.time()
            for attempt in range(MAX_TRIES):
                try:
                    st, scn = SC.render(spec, out, work_dir=self.ep.p("_work", sid), log=lambda *a: None)
                    rep[sid] = {"key": key, "file": os.path.relpath(out, self.ep.dir), "seconds": round(st["duration"], 2),
                                "render_s": round(time.time() - t0, 1), "lines": len(scn.lines),
                                "shots": sorted({s_["type"] for s_ in scn.shots}), "tries": attempt + 1}
                    break
                except Exception as e:
                    self.ep.event(self.name, "error", f"{sid} try {attempt + 1}: {str(e)[:300]}")
                    if attempt + 1 == MAX_TRIES:
                        rep[sid] = {"key": None, "error": str(e)[:300]}
            self.log(f"  {sid} {spec['location']}: " + (f"{rep[sid]['seconds']:.1f}s, shots {', '.join(rep[sid]['shots'])}"
                                                        if rep[sid].get("file") else "FAILED"))
        self.ep.write("render_report.json", rep)
        bad = [k for k, v in rep.items() if not v.get("file")]
        if bad:
            raise RuntimeError("scenes not rendered: " + ", ".join(bad))


# ===================================================================================================== 08b sound
def _ambience(loc, room, weather, hour, n, sr, seed=1):
    """the sound of a place, made from noise and tones (no sound files are needed)"""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    noise = rng.standard_normal(n).astype(np.float32)

    def lp(x, k):
        y = np.convolve(x, np.ones(k) / k, mode="same")
        return y / (np.abs(y).max() + 1e-6)

    out = np.zeros(n, np.float32)
    night = hour >= 19 or hour < 5
    if loc in ("boat", "pukur_ghat", "seaside") or room == "hold":
        out += 0.5 * lp(noise, 400) * (0.6 + 0.4 * np.sin(2 * np.pi * t / 5.0))          # water swells
    if loc in ("village_courtyard", "bansh_bon", "village_road", "shmashan", "temple", "school", "mountain") and night:
        chirp = (np.sin(2 * np.pi * 4200 * t) * (np.sin(2 * np.pi * 9 * t) > 0.6) * (np.sin(2 * np.pi * 0.3 * t) > 0)).astype(np.float32)
        out += 0.08 * chirp                                                                   # crickets
    if loc in ("city_street", "market", "station"):
        out += 0.35 * lp(noise, 60)                                                           # crowd / traffic murmur
        out += 0.15 * np.sin(2 * np.pi * 55 * t).astype(np.float32)
    if loc in ("train_inside",):
        out += 0.6 * lp(noise, 200) * (0.7 + 0.3 * (np.mod(t, 0.47) < 0.06))                 # rails' rhythm
    if loc in ("bus_inside", "tram_inside"):
        out += 0.45 * lp(noise, 150)
    if room == "kitchen" or loc == "shmashan":
        out += 0.12 * (rng.random(n) < 0.0008).astype(np.float32) * rng.standard_normal(n).astype(np.float32) * 8   # crackle
    if loc == "temple":
        for k in range(int(n / sr / 6) + 1):                                                  # a bell now and then
            i = int((k * 6 + 2) * sr)
            if i < n:
                m = min(n - i, int(2.5 * sr))
                tt = np.arange(m) / sr
                out[i:i + m] += 0.3 * np.sin(2 * np.pi * 880 * tt) * np.exp(-tt * 2)
    if "rain" in weather or "storm" in weather:
        out += 0.5 * lp(noise, 8)
    if "storm" in weather or loc == "mountain":
        out += 0.4 * lp(noise, 2000) * (0.5 + 0.5 * np.sin(2 * np.pi * t / 7.0))             # wind
    if not out.any():
        out += 0.12 * lp(noise, 800)                                                          # room tone
    return out / (np.abs(out).max() + 1e-6)


def _music(mood, n, sr):
    t = np.arange(n) / sr
    if mood in ("creepy", "scare", "eerie", "tense", "horror"):
        m = np.sin(2 * np.pi * 55 * t) + 0.6 * np.sin(2 * np.pi * 58.3 * t) + 0.3 * np.sin(2 * np.pi * 110 * t + np.sin(t * 0.5))
    elif mood in ("happy", "comedy"):
        m = sum(np.sin(2 * np.pi * f * t) * (np.mod(t * 2 + i * 0.25, 1.0) < 0.15) for i, f in enumerate((523, 659, 784, 659)))
    else:
        m = np.sin(2 * np.pi * 220 * t) * 0.5 + np.sin(2 * np.pi * 277 * t) * 0.4 + np.sin(2 * np.pi * 330 * t) * 0.3
    m = m * (0.6 + 0.4 * np.sin(2 * np.pi * t / 11.0))
    return (m / (np.abs(m).max() + 1e-6)).astype(np.float32)


class SoundDesigner(Agent):
    id, name = "08b", "Sound Designer (Voice & Audio Director, second task)"
    needs = ("render_report.json", "locations.json", "analysis.json")
    makes = ("sound_report.json",)

    def run(self):
        locs = self.ep.read("locations.json")
        rr = self.ep.read("render_report.json")
        a = self.ep.read("analysis.json")
        sb = self.ep.read("scene_breakdown.json")
        sr = 44100
        rep = {}
        for sc, o in zip(sb["scenes"], locs):
            sid = sc["scene_id"]
            src = self.ep.p(rr[sid]["file"])
            out = self.ep.p("scenes", f"{sid}_mix.mp4")
            d = _dur(src)
            n = int(d * sr)
            amb = _ambience(sc["location"], o["room"], o["weather"], o["hour"], n, sr, seed=int(sid[1:]))
            mus = _music(a.get("mood", "calm") if sc.get("transition") else "calm", n, sr)
            bed = 0.22 * amb + 0.10 * mus
            fade = np.minimum(1.0, np.minimum(np.arange(n) / (0.8 * sr), (n - np.arange(n)) / (0.8 * sr)))
            bed = (bed * fade).astype(np.float32)
            bw = self.ep.p("_work", f"{sid}_bed.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", bw],
                           input=bed.tobytes(), check=True)
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-i", bw, "-filter_complex",
                                "[0:a]volume=1.0[v];[1:a]volume=1.0[b];[v][b]amix=inputs=2:duration=first:normalize=0[a]",
                                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(sr), "-ac", "2", out],
                               capture_output=True, text=True)
            if r.returncode != 0:
                self.ep.event(self.name, "error", f"{sid}: {r.stderr[-300:]} - the scene keeps its voices only")
                shutil.copy(src, out)
            rep[sid] = {"file": os.path.relpath(out, self.ep.dir), "ambience": self._names(sc["location"], o),
                        "music": a.get("mood", "calm")}
        self.ep.write("sound_report.json", rep)
        self.log(f"  ambience + music under {len(rep)} scenes")

    @staticmethod
    def _names(loc, o):
        n = []
        if loc in ("boat", "pukur_ghat", "seaside") or o["room"] == "hold":
            n.append("water")
        if o["weather"]:
            n += o["weather"]
        if o["hour"] >= 19 or o["hour"] < 5:
            n.append("night")
        return ", ".join(n) or "room tone"


# ===================================================================================================== 11b editor
class Editor(Agent):
    id, name = "11b", "Video Editor (episode assembly)"
    needs = ("sound_report.json", "scene_breakdown.json")
    makes = ("final_episode.mp4",)

    def run(self):
        from PIL import Image, ImageDraw, ImageFont
        sb = self.ep.read("scene_breakdown.json")
        snd = self.ep.read("sound_report.json")
        W, H = _frame(self.ep.state["settings"])
        portrait = H > W
        font = os.path.join(ROOT, "fonts", "NotoSansBengali-Bold.ttf")
        cards = []
        from PIL import ImageEnhance, ImageFilter
        props = self.ep.read("props.json") if os.path.exists(self.ep.p("props.json")) else []
        for name, text, sub in (("title", sb["title"], "একটি বাংলা কার্টুন"), ("end", "সমাপ্ত", sb["title"])):
            bgp = self.ep.p(props[0 if name == "title" else -1]["background"]) if props else None
            if bgp and os.path.exists(bgp):                 # the story's own place, dimmed, behind the title
                img = Image.open(bgp).convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(6))
                img = ImageEnhance.Brightness(img).enhance(0.55)
            else:
                img = Image.new("RGB", (W, H), (40, 34, 52))
            d = ImageDraw.Draw(img)
            f1 = ImageFont.truetype(font, int(H * (0.07 if not portrait else 0.04)), layout_engine=ImageFont.Layout.RAQM) \
                if os.path.exists(font) else ImageFont.load_default()
            f2 = f1.font_variant(size=int(f1.size * 0.45)) if hasattr(f1, "font_variant") else f1
            for txt, ff, y, col in ((text, f1, H * 0.42, (255, 214, 80)), (sub, f2, H * 0.56, (230, 230, 230))):
                tw = d.textlength(txt, font=ff)
                d.text(((W - tw) / 2, y), txt, font=ff, fill=col, stroke_width=4, stroke_fill=(0, 0, 0))
            png = self.ep.p("_work", f"{name}.png")
            img.save(png)
            mp4 = self.ep.p("_work", f"{name}.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", png, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                            "-t", "3", "-vf", "fade=t=in:st=0:d=0.6,fade=t=out:st=2.4:d=0.6,format=yuv420p", "-r", "24",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-shortest", mp4],
                           check=True)
            cards.append(mp4)
        clips = [cards[0]] + [self.ep.p(snd[s["scene_id"]]["file"]) for s in sb["scenes"]] + [cards[1]]
        norm = []
        for i, c in enumerate(clips):                          # the same size, fps and sound for every piece
            o = self.ep.p("_work", f"part_{i:02d}.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", c, "-vf", f"scale={W}:{H},format=yuv420p", "-r", "24",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                            "-ac", "2", o], check=True)
            norm.append(o)
        durs = [_dur(c) for c in norm]
        inputs = []
        for c in norm:
            inputs += ["-i", c]
        vf, af, off = [], [], 0.0
        vl, al = "[0:v]", "[0:a]"
        for i in range(1, len(norm)):
            cut = 1 < i < len(norm) - 1 and sb["scenes"][i - 1].get("transition") == "cut"   # into scene i-1
            fd = 0.04 if cut else 0.6
            off += durs[i - 1] - fd
            vf.append(f"{vl}[{i}:v]xfade=transition=fadeblack:duration={fd}:offset={off:.3f}[v{i}]")
            af.append(f"{al}[{i}:a]acrossfade=d={fd}[a{i}]")
            vl, al = f"[v{i}]", f"[a{i}]"
        out = self.ep.p("final_episode.mp4")
        r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex", ";".join(vf + af), "-map", vl, "-map", al,
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
                            "-movflags", "+faststart", out], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("assembly failed: " + r.stderr[-500:])
        self.log(f"  final episode {_dur(out):.1f}s ({W}x{H}, 24 fps)")


# ===================================================================================================== 12 QC
class QualityControl(Agent):
    id, name = "12", "Quality Control & Delivery Manager"
    needs = ("final_episode.mp4", "scene_breakdown.json", "casting.json", "voice_map.json", "render_report.json", "locations.json")
    makes = ("qc_report.json", "qc_report.md")

    def run(self):
        sb = self.ep.read("scene_breakdown.json")
        cast = self.ep.read("casting.json")
        vm = self.ep.read("voice_map.json")
        rr = self.ep.read("render_report.json")
        locs = self.ep.read("locations.json")
        st = self.ep.state["settings"]
        checks, back = [], []

        def add(name, ok, detail, agent=None):
            checks.append({"check": name, "pass": bool(ok), "detail": detail, "owner": agent})
            if not ok and agent:
                back.append(agent)

        roles = {}
        for sc in sb["scenes"]:                                  # character consistency: one actor per role
            for c in sc["cast"]:
                roles.setdefault(c.get("name_bn") or c["id"], set()).add(c["id"].split("__")[0])
        add("character consistency", all(len(v) == 1 for v in roles.values()), {k: sorted(v) for k, v in roles.items()}, "04")
        add("scene consistency (every scene has a place and a time)", all(s.get("location") and s["world"].get("hours") for s in sb["scenes"]),
            len(sb["scenes"]), "07")
        add("background correctness (scene place = designed place)",
            all(s["location"] == o["location"] for s, o in zip(sb["scenes"], locs)), [s["location"] for s in sb["scenes"]], "05")
        add("dialogue completeness", all(rr[s["scene_id"]].get("lines", 0) >= s["planned_lines"] for s in sb["scenes"]),
            {s["scene_id"]: [rr[s["scene_id"]].get("lines"), s["planned_lines"]] for s in sb["scenes"]}, "07")
        voiced = vm["total_lines"] - vm["silent_lines"]
        add("voices", vm["silent_lines"] == 0 or st.get("voice") == "none",
            f"{voiced}/{vm['total_lines']} lines voiced ({vm['engine']})", "08")
        lip = []
        try:                                                     # lip-sync measured on the first voiced scene
            from tvtoon import qa_motion as Q
            from tvtoon import scene as SC
            _load_cast(self.ep)
            for spec in compose(self.ep):
                if any(b.get("audio") for b in spec["beats"]):
                    r = Q.lipsync_timing(SC.Scene(dict(spec, size=[320, 180])))
                    lip.append({"scene": spec["scene_id"], "pass": r["pass"], "lines": r["lines"][:4]})
                    break
        except Exception as e:
            lip.append({"error": str(e)[:200]})
        add("lip-sync timing", all(x.get("pass") for x in lip) if lip and not lip[0].get("error") else True,
            lip or "no voiced line to measure", "08")
        final = self.ep.p("final_episode.mp4")
        pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", final],
                                       capture_output=True, text=True).stdout or "{}")
        v = next((s for s in pr.get("streams", []) if s.get("codec_type") == "video"), {})
        a = next((s for s in pr.get("streams", []) if s.get("codec_type") == "audio"), {})
        W, H = _frame(st)
        add("resolution", (v.get("width"), v.get("height")) == (W, H), f"{v.get('width')}x{v.get('height')}", "11b")
        fps = eval(v.get("r_frame_rate", "0/1")) if v else 0
        add("frame rate", abs(fps - 24) < 0.01, fps, "11b")
        total = float(pr.get("format", {}).get("duration", 0))
        want = sum(rr[s["scene_id"]]["seconds"] for s in sb["scenes"]) + 6.0
        add("video duration", abs(total - want) < 3.0 + 0.7 * len(sb["scenes"]), f"{total:.1f}s (planned {want:.1f}s)", "11b")
        add("audio stream", bool(a) and a.get("sample_rate") in ("44100", "48000"), a.get("codec_name"), "11b")
        dec = subprocess.run(["ffmpeg", "-v", "error", "-i", final, "-f", "null", "-"], capture_output=True, text=True)
        add("file integrity (decodes without error)", dec.returncode == 0 and not dec.stderr.strip(), dec.stderr[-200:] or "ok", "11b")
        blk = subprocess.run(["ffmpeg", "-i", final, "-vf", "blackdetect=d=1.2:pix_th=0.06", "-an", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        spans = [m for m in re.findall(r"black_duration:([0-9.]+)", blk)]
        add("no long black frames (only the planned fades)", all(float(x) < 2.5 for x in spans), spans or "none", "11")
        sig = subprocess.run(["ffmpeg", "-v", "error", "-i", final, "-vf", "fps=1,scale=64:36,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True).stdout
        fr = np.frombuffer(sig, np.uint8).reshape(-1, 36 * 64).astype(int) if sig else np.zeros((1, 1))
        moving = float(np.mean(np.abs(np.diff(fr, axis=0)).mean(axis=1) > 0.25)) if len(fr) > 2 else 0.0
        add("not a slideshow (the picture keeps moving)", moving > 0.5, f"{moving * 100:.0f}% of seconds change", "11")
        ok = all(c["pass"] for c in checks)
        rep = {"pass": ok, "checks": checks, "send_back_to": sorted(set(back)), "file": "final_episode.mp4", "seconds": round(total, 1)}
        self.ep.write("qc_report.json", rep)
        md = ["# Quality control report", "", f"Result: **{'PASS' if ok else 'FAIL'}**", "", "| Check | Result | Detail | Owner |", "|---|---|---|---|"]
        for c in checks:
            md.append(f"| {c['check']} | {'pass' if c['pass'] else 'FAIL'} | {str(c['detail'])[:160].replace('|', '/')} | {c['owner'] or ''} |")
        self.ep.write_text("qc_report.md", "\n".join(md) + "\n")
        self.log("  QC " + ("PASS" if ok else "FAIL: " + ", ".join(c["check"] for c in checks if not c["pass"])))


# ===================================================================================================== 01 manager
PIPELINE = [StoryAnalyst, Scriptwriter, CharacterDirector, LocationDesigner, BackgroundArtist, StoryboardDirector, VoiceDirector,
            AnimationDirector, EnvironmentDirector, Cinematographer, SoundDesigner, Editor, QualityControl]
OWNER = {"02": StoryAnalyst, "03": Scriptwriter, "04": CharacterDirector, "05": LocationDesigner, "06": BackgroundArtist,
         "07": StoryboardDirector, "08": VoiceDirector, "09": AnimationDirector, "10": EnvironmentDirector, "11": Cinematographer,
         "08b": SoundDesigner, "11b": Editor}


class ProductionManager:
    id, name = "01", "Chief Production Manager"

    def __init__(self, story_text, out_dir, voice="gemini", portrait=False, max_scenes=None, log=print, preview=False):
        self.log = log
        first = next((x.strip(" #*") for x in story_text.splitlines() if x.strip()), "গল্প")
        settings = {"voice": voice, "portrait": bool(portrait), "max_scenes": max_scenes, "title": first[:70], "preview": bool(preview),
                    "size": "1080x1920" if portrait else "1920x1080", "fps": 24}
        self.ep = Episode(out_dir, settings)
        p = self.ep.p("story.txt")
        if not os.path.exists(p) or open(p, encoding="utf-8").read() != story_text:
            with open(p, "w", encoding="utf-8") as f:
                f.write(story_text)

    def _stage(self, cls, force=False):
        ag = cls(self.ep, self.log)
        stt = self.ep.state["stages"].setdefault(ag.id, {"agent": ag.name})
        h = ag.input_hash()
        if not force and stt.get("status") == "done" and stt.get("input") == h and not ag.check():
            self.log(f"[{ag.id}] {ag.name}: kept (its inputs did not change)")
            return True
        for attempt in range(1, MAX_TRIES + 2):
            self.log(f"[{ag.id}] {ag.name}" + (f" (try {attempt})" if attempt > 1 else ""))
            t0 = time.time()
            stt.update(status="running", started=_now(), tries=attempt)
            self.ep.save()
            try:
                ag.run()
                problems = ag.check()
                if problems:
                    raise RuntimeError("; ".join(problems))
                stt.update(status="done", ended=_now(), seconds=round(time.time() - t0, 1), input=ag.input_hash(),
                           outputs=list(ag.makes), error=None)
                self.ep.save()
                return True
            except Exception as e:
                stt.update(status="failed", error=str(e)[:500])
                self.ep.event(ag.name, "error", f"try {attempt}: {e}\n{traceback.format_exc()[-600:]}")
                self.log(f"   ! {ag.name}: {str(e)[:200]}")
                if not str(e).startswith("retry") and attempt >= MAX_TRIES:
                    break
        return False

    def run(self):
        t0 = time.time()
        ok = True
        for cls in PIPELINE:
            if not self._stage(cls):
                ok = False
                self.log(f"[01] stopped: {cls.name} failed after {MAX_TRIES} tries - see episode_state.json")
                break
        for round_ in range(2):                              # QC sends work back to the agents responsible
            if not ok or not os.path.exists(self.ep.p("qc_report.json")):
                break
            qc = self.ep.read("qc_report.json")
            if qc["pass"]:
                break
            owners = [o for o in qc.get("send_back_to", []) if o in OWNER and o != "08"]   # (no voice is paid for twice)
            if not owners:
                break
            first = min(PIPELINE.index(OWNER[o]) for o in owners)
            self.log(f"[01] QC sent work back to agents {', '.join(owners)} - rerunning from {PIPELINE[first].name}")
            for cls in PIPELINE[first:]:
                if not self._stage(cls, force=True):
                    ok = False
                    break
        self.deliver(ok, time.time() - t0)
        return ok

    def deliver(self, ok, seconds):
        ep = self.ep
        qc = ep.read("qc_report.json") if os.path.exists(ep.p("qc_report.json")) else {"pass": False, "checks": []}
        final = ep.p("final_episode.mp4")
        md = [f"# Production report: {ep.state['settings'].get('title')}", "", f"Finished: {_now()} - {seconds / 60:.1f} minutes", "",
              f"**Result: {'DELIVERED' if ok and os.path.exists(final) else 'NOT DELIVERED'}**, QC: {'PASS' if qc.get('pass') else 'FAIL'}", "",
              "## Agents", "", "| # | Agent | Status | Tries | Seconds | Outputs | Error |", "|---|---|---|---|---|---|---|"]
        for cls in PIPELINE:
            s = ep.state["stages"].get(cls.id, {})
            md.append(f"| {cls.id} | {cls.name} | {s.get('status', 'not run')} | {s.get('tries', '')} | {s.get('seconds', '')} | "
                      f"{', '.join(s.get('outputs') or [])} | {(s.get('error') or '')[:120].replace('|', '/')} |")
        try:
            a = ep.read("analysis.json")
            c = ep.read("casting.json")
            md += ["", "## The story", "", f"Genre {a.get('genre')}, mood {a.get('mood')}, audience {a.get('audience')}.", "",
                   "## Cast", ""] + [f"- {k}: `{v['id']}` ({'library' if v['library'] else 'NEW for this episode'}), voice {v['voice']}"
                                     for k, v in c["registry"].items()]
            locs = ep.read("locations.json")
            md += ["", "## Places", ""] + [f"- scene {o['scene']}: {o['location']}{' / ' + o['room'] if o['room'] else ''}, "
                                            f"{o['hour']:g}h, {o['light']}{', ' + ', '.join(o['weather']) if o['weather'] else ''}" for o in locs]
            vm = ep.read("voice_map.json")
            md += ["", "## Voices", "", f"Engine {vm['engine']}: {vm['total_lines'] - vm['silent_lines']}/{vm['total_lines']} lines voiced."]
        except Exception:
            pass
        md += ["", "## Errors and retries", ""] + ([f"- {e['t']} {e['agent']}: {e['msg'][:200]}" for e in ep.state["events"] if e["kind"] == "error"]
                                                   or ["- none"])
        md += ["", "## Files", "", "- final_episode.mp4", "- screenplay.md, screenplay.json", "- scene_breakdown.json", "- qc_report.md",
               "- audio/ (every line)", "- assets/characters (new characters), assets/backgrounds (every place)", "- episode_state.json"]
        ep.write_text("production_report.md", "\n".join(md) + "\n")
        ep.state["delivered"] = bool(ok and os.path.exists(final))
        ep.save()
        self.log(f"[01] {'DELIVERED' if ep.state['delivered'] else 'NOT DELIVERED'}: {final if os.path.exists(final) else '(no final video)'}")


def produce(story_text, out_dir, voice="gemini", portrait=False, max_scenes=None, log=print, preview=False):
    return ProductionManager(story_text, out_dir, voice, portrait, max_scenes, log, preview).run()


def _next_episode_dir(base):
    os.makedirs(base, exist_ok=True)
    n = 1 + max([int(m.group(1)) for d in os.listdir(base) for m in [re.match(r"episode_(\d+)$", d)] if m] or [0])
    return os.path.join(base, f"episode_{n:03d}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    opts = {"voice": os.environ.get("TVTOON_VOICE") or "gemini", "portrait": False, "max_scenes": None}
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--voice":
            opts["voice"] = args[i + 1]
            i += 1
        elif a == "--portrait":
            opts["portrait"] = True
        elif a == "--max-scenes":
            opts["max_scenes"] = int(args[i + 1]) or None
            i += 1
        else:
            pos.append(a)
        i += 1
    text = open(pos[0], encoding="utf-8").read()
    out = pos[1] if len(pos) > 1 else _next_episode_dir(os.path.join(ROOT, "output"))
    sys.exit(0 if produce(text, out, **opts) else 2)
