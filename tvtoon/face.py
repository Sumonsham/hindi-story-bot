"""facial assets as states: 7 eye states, 5 brow states, 9 mouth visemes, expressions built from them"""

EYES = {   # name -> face fields
    "open": {"lid": 1.0, "look": (0.0, 0.0)},
    "half": {"lid": 0.5, "look": (0.0, 0.1)},
    "closed": {"lid": 0.0},
    "look_left": {"lid": 1.0, "look": (-1.0, 0.0)},
    "look_right": {"lid": 1.0, "look": (1.0, 0.0)},
    "look_up": {"lid": 1.0, "look": (0.0, -1.0)},
    "look_down": {"lid": 0.75, "look": (0.0, 1.0)},
}
BROW_STATES = ["normal", "happy", "angry", "sad", "surprised"]
MOUTHS = ["X", "A", "E", "U", "O", "MBP", "FV", "LTD", "WIDE"]
MOUTH_NAMES_BN = {"X": "বন্ধ", "A": "আ", "E": "ই এ", "U": "উ", "O": "ও", "MBP": "ম ব প", "FV": "ফ ভ", "LTD": "ল ত দ",
                  "WIDE": "হাসি"}

EXPRESSIONS = {   # base face per emotion (mouth X = when not speaking)
    "neutral": {"brow": "normal", "smile": 0.15, "lid": 1.0},
    "happy": {"brow": "happy", "smile": 0.8, "squint": 0.35, "lid": 1.0, "cheek": 0.6},
    "laughing": {"brow": "happy", "smile": 1.0, "happy_closed": True, "mouth": "WIDE", "cheek": 1.0},
    "sad": {"brow": "sad", "smile": -0.6, "lid": 0.7, "look": (0.0, 0.6)},
    "angry": {"brow": "angry", "smile": -0.45, "lid": 0.8, "squint": 0.2},
    "surprised": {"brow": "surprised", "smile": 0.0, "wide": 1.0, "mouth": "O"},
    "scared": {"brow": "scared", "smile": -0.4, "wide": 0.8, "mouth": "E"},
    "thinking": {"brow": ("normal"), "smile": 0.0, "look": (0.6, -0.7), "lid": 0.85},
    "crying": {"brow": "sad", "smile": -0.9, "lid": 0.35, "squint": 0.4, "tears": 1.0, "mouth": "WIDE", "look": (0.0, 0.6)},
}


def expression(name, speaking=False):
    e = dict(EXPRESSIONS.get(name, EXPRESSIONS["neutral"]))
    if speaking:
        e.pop("mouth", None)
        e.pop("happy_closed", None)
    return e
