"""THE PLACE IS ALIVE (owner, 23 Nov 2026: "rastai chele ra khela korbe, paas diye manush perube, bazaar er jemon
onek manush jinis kene" - children play in the street, people walk past, the market is full of people buying).

Behind the story's own characters, a scene gets the people who belong to that place and that hour, drawn smaller
and farther back (they never speak, never take the camera, never stand in front of the story):

  village / street / road / courtyard by day  -> people walking past (both ways, now and then), children playing
                                                 catch (running, jumping, coming back), a woman with a pot
  market                                      -> shoppers at the stalls pointing, asking, paying; people with bags
  temple                                      -> devotees with folded hands, bowing; someone walking up
  school                                      -> children running and jumping in the yard
  station / seaside / pond ghat by day        -> a few people walking past
  night, or a horror scene after dusk         -> nobody (the loneliness is part of the fear), at most one far walker
  indoors, vehicles, boats                    -> nobody

Every extra is its own new face (characters.new_character), never one of the story's actors. scene.py adds them
(spec "life": false switches it off)."""
import random

from tvtoon import characters as CH

OUTSIDE_BUSY = {"village_courtyard", "village_road", "city_street", "market", "temple", "school", "station", "seaside",
                "pukur_ghat"}


def _hour(spec):
    try:
        return float((spec.get("world") or {}).get("hours", [[0, 11.0]])[0][1])
    except Exception:
        return 11.0


def _extra(cid, gender, age, seed):
    if cid not in CH.SPECS:
        CH.new_character(cid, "", gender, age, "", seed=seed)
        CH.SPECS[cid]["extra"] = True
    return cid


def plan(spec, length=600.0):
    """(cast entries, beats) of the place's own people for this scene"""
    loc = spec.get("location", "")
    if spec.get("life") is False or loc not in OUTSIDE_BUSY:
        return [], []
    h = _hour(spec)
    horror = spec.get("look") == "horror" or spec.get("horror")
    night = h >= 19.0 or h < 5.5
    if night and (horror or loc not in ("city_street", "station", "market")):
        return [], []
    world = spec.get("world") or {}
    if world.get("rain") or world.get("storm"):
        return [], []
    rnd = random.Random(f"{loc}|{world.get('text', '')}|{len(spec.get('cast', []))}|{h}")
    taken = {c["id"] for c in spec.get("cast", [])}
    cast, beats = [], []
    n = 0

    story_x = [float(c.get("x", 1600)) for c in spec.get("cast", [])]

    def person(gender, age, z, x):
        nonlocal n
        n += 1
        z = min(1.0, z + 0.22)                              # well behind the story's people
        for _k in range(6):                                 # never standing right behind / beside them
            if all(abs(x - sx) > 330 for sx in story_x):
                break
            x += 380 if x >= 1600 else -380
        cid = _extra(f"life_{loc}_{n}_{rnd.randint(0, 999)}", gender, age, rnd.randint(0, 99999))
        if cid in taken:
            return None
        cast.append({"id": cid, "x": round(x), "z": z, "extra": True})
        return cid

    def walker(z, gender, age, start=0.0, gap=(4, 12)):
        """walks across the whole place, waits off screen, comes back the other way"""
        left = rnd.random() < 0.5
        x0, x1 = (-1400, 4600) if left else (4600, -1400)
        cid = person(gender, age, z, x0)
        if not cid:
            return
        t = start
        while t < length:
            beats.append({"who": cid, "walk_to": x1, "at": round(t, 2), "background": True, "life": True})
            t += 6000 / 115.0 + rnd.uniform(*gap)              # (about 115 world px a second, then a pause)
            x0, x1 = x1, x0

    def players(z, cx, kids=2):
        """children playing catch round a spot: run, turn, jump, run back"""
        ids = [person(rnd.choice(["male", "female"]), "child", z, cx + k * 160) for k in range(kids)]
        ids = [i for i in ids if i]
        for k, cid in enumerate(ids):
            t = 0.6 * k
            here = cx + k * 160
            while t < length:
                there = cx + rnd.choice([-1, 1]) * rnd.uniform(260, 520)
                beats.append({"who": cid, "walk_to": round(there), "gait": "run", "at": round(t, 2), "background": True,
                              "life": True})
                t += abs(there - here) / 330.0 + 0.2
                if rnd.random() < 0.45:
                    beats.append({"who": cid, "act": "jump", "at": round(t, 2), "background": True, "life": True})
                    t += 0.7
                if rnd.random() < 0.3:
                    beats.append({"who": cid, "gesture": "clap", "sec": 1.2, "at": round(t, 2), "background": True, "life": True})
                    t += 1.3
                here = there

    def standing(z, x, gestures, gender, age, every=(3.5, 7.0), face=None):
        cid = person(gender, age, z, x)
        if not cid:
            return
        if face is not None:
            beats.append({"who": cid, "face": face, "sec": 0.1, "at": 0.0, "background": True, "life": True})
        t = rnd.uniform(0.5, 3.0)
        while t < length:
            g = rnd.choice(gestures)
            if g in ("bow", "nod"):
                beats.append({"who": cid, "act": g, "at": round(t, 2), "background": True, "life": True})
            else:
                beats.append({"who": cid, "gesture": g, "sec": 2.2, "at": round(t, 2), "background": True, "life": True})
            t += rnd.uniform(*every)

    if loc == "market":                                     # shoppers at the stalls, people with their bags
        for k, x in enumerate((620, 1250, 2050, 2650)):
            standing(0.62 + 0.08 * (k % 2), x + rnd.uniform(-60, 60), ["point", "explain", "explain_both", "nod", "shrug"],
                     rnd.choice(["male", "female"]), rnd.choice(["adult", "adult", "old"]), face=rnd.choice([-0.5, 0.5]))
        walker(0.82, "female", "adult", start=1.0)
        walker(0.74, "male", "adult", start=9.0)
    elif loc == "temple":
        standing(0.7, 1150, ["namaste", "bow", "namaste"], "female", "old", every=(4, 8), face=0.0)
        standing(0.75, 2100, ["namaste", "bow"], "male", "adult", every=(5, 9), face=0.0)
        walker(0.85, "male", "old", start=4.0, gap=(10, 20))
    elif loc == "school":
        players(0.72, 900, 2)
        players(0.8, 2300, 2)
    elif loc in ("village_courtyard", "village_road", "city_street"):
        walker(0.8, rnd.choice(["male", "female"]), "adult", start=rnd.uniform(1, 4))
        if not night:
            walker(0.68, rnd.choice(["male", "female"]), rnd.choice(["adult", "old"]), start=rnd.uniform(12, 20))
            if not horror or h < 16.5:
                players(0.76, rnd.choice([700, 2500]), 2)
    else:                                                   # station, seaside, the pond ghat
        if not night:
            walker(0.8, rnd.choice(["male", "female"]), "adult", start=rnd.uniform(2, 8), gap=(8, 16))
    return cast, beats
