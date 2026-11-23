"""THE KIDS' CARTOON BOT (Sumonsham/hindi-story-bot) ON THE SAME ENGINE (owner, 23 Nov 2026: "same system e cartoon
bot er jonno same engine bebohar kore ... sara din e 3 te hobe ... onek rokom catagory ... sob rokom character").

The bot keeps everything it does: its 3 videos a day, every category and series, the story writer, the voices
(LINE_WAVS), sound, subtitles, quiz / lesson / English-word cards, thumbnail, Facebook and YouTube. Only the story
PICTURES become this TV cartoon:

  * every story scene -> a tvtoon scene with the kids' recurring cast (kids.py: Gopal's court, Akbar-Birbal,
    Vikram-Betal, the gods, Bhutu, Tukai, Robi... and animals for Panchatantra / Jataka), its place and time of day,
    the people who live there (life.py), and every movement the story asks for (actions.py) - on the bot's own
    line times, with the bot's own clean line recordings for the lip-sync;
  * the hook at the start -> the same, from its scene;
  * Lumi Didi's parts (greeting, lesson, goodbye) -> Lumi Didi and Mithu in the storytelling courtyard;
  * a scene that fails is made the bot's old way (nothing is lost)."""
import os

from tvtoon import bot as BT
from tvtoon import kids as K

_STATE = {}


def plan(story, category=""):
    key = (story.get("title"), len(story.get("scenes") or []), category)
    if _STATE.get("key") != key:
        _STATE["key"] = key
        ep = K.plan(story, category)                    # (the characters made at night come from the library)
        ep["look"] = os.environ.get("TVTOON_LOOK") or "kids"
        _STATE["ep"] = ep
    return _STATE["ep"]


def part_spec(ep, si, lines, subs, line_wavs, dur, W, H, fps):
    os.environ.setdefault("TVTOON_VOICE", "none")         # only the bot's own recordings: no second voice is ever made
    spec = BT.part_spec(ep, si, lines, subs, line_wavs, dur, W, H, fps)
    spec["look"] = ep.get("look", "kids")
    return spec


def host_spec(lines, subs, line_wavs, dur, W, H, fps):
    os.environ.setdefault("TVTOON_VOICE", "none")
    spec = K.host_scene(lines, subs, line_wavs, dur, W, H, fps)
    spec["look"] = os.environ.get("TVTOON_LOOK") or "kids"
    spec["life"] = False
    return spec


render_part = BT.render_part


still = BT.still
