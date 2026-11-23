"""CHARACTER IDENTITY SHEETS (locked): 12 original characters, 2 per category. The first of each category is the
SAMPLE PACK; the second waits for the owner's approval of the samples (same standard, same engine).

Every character differs in head shape, face structure, eyes, nose, hairstyle, body proportions, costume, palette and
personality - never 'the same body in other clothes'."""
import copy
import random

CATEGORIES = ["adult_male", "adult_female", "elderly_male", "elderly_female", "boy", "girl"]
HORROR_CATEGORIES = CATEGORIES + ["ghost"]

SPECS = {
    # ---------------------------------------------------------------- sample pack
    "haripada": {
        "name_bn": "হরিপদ", "name_en": "Haripada", "category": "adult_male", "sample": True, "age": 42,
        "personality": "a kind, slightly nervous village shopkeeper; talks with his hands, worries a lot, laughs loudly",
        "voice": "deep male, warm", "height": 1.0, "heads": 4.9,
        "head": {"shape": "oval", "w": 0.80, "ear": 1.05},
        "face": {"eye_style": "almond", "eye_size": 0.072, "eye_spacing": 0.42, "iris": "#3b2414", "nose": "broad",
                 "nose_size": 1.0, "mouth_w": 1.0, "moustache": "thick", "brow_thick": 1.25, "mouth_y": 0.15},
        "hair": {"style": "side_part"},
        "body": {"shoulder": 0.8, "chest": 0.76, "waist": 0.66, "hip": 0.62, "belly": 0.12, "arm_r": 0.105,
                 "leg_r": 0.14, "leg": 0.45, "arm": 0.42, "shoe": "sandal"},
        "costume": {"type": "shirt_trousers", "sleeve": "half"},
        "colours": {"skin": "#c98b5e", "hair": "#1d1512", "shirt": "#6fa8dc", "trousers": "#6b5b4b", "shoe": "#4a3020",
                    "lip": "#9a5a48"},
        "accessories": [],
    },
    "lumi_didi": {
        "name_bn": "লুমি দিদি", "name_en": "Lumi Didi", "category": "adult_female", "sample": True, "age": 24,
        "personality": "a bright, caring young teacher; quick to smile, firm when the children misbehave",
        "voice": "clear young female", "height": 0.93, "heads": 5.1,
        "head": {"shape": "heart", "w": 0.78, "ear": 0.9},
        "face": {"eye_style": "almond", "eye_size": 0.085, "eye_spacing": 0.43, "iris": "#2a1a10", "nose": "pointed",
                 "nose_size": 0.85, "mouth_w": 0.9, "lashes": True, "brow_thick": 0.8, "blush": True},
        "hair": {"style": "braid_long"},
        "body": {"shoulder": 0.62, "chest": 0.6, "waist": 0.46, "hip": 0.66, "arm_r": 0.085, "leg_r": 0.11, "leg": 0.47,
                 "arm": 0.41, "shoe": "sandal", "foot": 0.85},
        "costume": {"type": "saree", "sleeve": "short"},
        "colours": {"skin": "#d9a07a", "hair": "#14100e", "saree": "#2e8b57", "border": "#c8102e", "blouse": "#f2c14e",
                    "shoe": "#7a3b2e", "lip": "#b5505a", "ribbon": "#c8102e"},
        "accessories": ["bindi", "earrings", "bangles"],
    },
    "nibaran_dadu": {
        "name_bn": "নিবারণ দাদু", "name_en": "Nibaran Dadu", "category": "elderly_male", "sample": True, "age": 74,
        "personality": "a wise, teasing grandfather and story-teller; slow, gentle, loves riddles",
        "voice": "old male, slightly husky", "height": 0.94, "heads": 4.8,
        "head": {"shape": "long", "w": 0.74, "ear": 1.2},
        "face": {"eye_style": "narrow", "eye_size": 0.068, "eye_spacing": 0.42, "iris": "#3a2a1a", "nose": "long",
                 "nose_size": 1.15, "mouth_w": 0.95, "moustache": "bushy", "brow_thick": 1.1, "brow_col": "#efefef",
                 "wrinkles": True, "eye_y": 0.52},
        "hair": {"style": "bald_sides"},
        "body": {"shoulder": 0.7, "chest": 0.64, "waist": 0.56, "hip": 0.56, "arm_r": 0.09, "leg_r": 0.11, "leg": 0.44,
                 "arm": 0.42, "stoop": 0.08, "shoe": "sandal"},
        "costume": {"type": "kurta_dhoti", "sleeve": "full"},
        "colours": {"skin": "#b97f57", "hair": "#dcdcd6", "moustache": "#f4f4f2", "kurta": "#f4efe2", "dhoti": "#fbf8ef",
                    "shoe": "#5a3a22", "lip": "#8a5040"},
        "accessories": ["glasses_round"],
    },
    "sarala_thakuma": {
        "name_bn": "সরলা ঠাকুমা", "name_en": "Sarala Thakuma", "category": "elderly_female", "sample": True, "age": 70,
        "personality": "a warm, chubby grandmother; feeds everyone, scolds lovingly, laughs with her whole body",
        "voice": "old female, soft", "height": 0.84, "heads": 4.4,
        "head": {"shape": "round", "w": 0.88, "ear": 0.95},
        "face": {"eye_style": "round", "eye_size": 0.07, "eye_spacing": 0.40, "iris": "#3a2614", "nose": "round",
                 "nose_size": 0.95, "mouth_w": 0.95, "brow_thick": 0.8, "brow_col": "#d9d6d0", "wrinkles": True,
                 "blush": True, "lashes": False},
        "hair": {"style": "bun_white"},
        "body": {"shoulder": 0.74, "chest": 0.78, "waist": 0.76, "hip": 0.8, "belly": 0.08, "arm_r": 0.11, "leg_r": 0.13,
                 "leg": 0.43, "arm": 0.40, "stoop": 0.05, "shoe": "sandal", "foot": 0.85},
        "costume": {"type": "saree", "sleeve": "short"},
        "colours": {"skin": "#c99572", "hair": "#ecebe8", "saree": "#f8f6f0", "border": "#2f7d4a", "blouse": "#f8f6f0",
                    "shoe": "#5a3a22", "lip": "#9a5a50"},
        "accessories": ["bangles"],
    },
    "bappa": {
        "name_bn": "বাপ্পা", "name_en": "Bappa", "category": "boy", "sample": True, "age": 9,
        "personality": "a naughty, curious boy who loves football and mangoes; brave in daylight, scared at night",
        "voice": "boy", "height": 0.62, "heads": 3.3,
        "head": {"shape": "round", "w": 0.94, "ear": 1.1},
        "face": {"eye_style": "big", "eye_size": 0.10, "eye_spacing": 0.42, "iris": "#3a2412", "nose": "button",
                 "nose_size": 0.8, "mouth_w": 0.95, "brow_thick": 1.0, "eye_y": 0.46, "child": 1, "mouth_y": 0.18},
        "hair": {"style": "spiky"},
        "body": {"shoulder": 0.62, "chest": 0.6, "waist": 0.56, "hip": 0.56, "arm_r": 0.085, "leg_r": 0.10, "leg": 0.38,
                 "arm": 0.40, "neck": 0.025, "shoe": "sandal", "foot": 1.1},
        "costume": {"type": "tshirt_shorts", "sleeve": "short"},
        "colours": {"skin": "#c58a5c", "hair": "#16110e", "tshirt": "#d64045", "stripe": "#f4f1de", "shorts": "#3d5a80",
                    "shoe": "#333344", "lip": "#9a5040"},
        "accessories": [],
    },
    "mili": {
        "name_bn": "মিলি", "name_en": "Mili", "category": "girl", "sample": True, "age": 8,
        "personality": "a clever, chatty girl who asks 'why?' about everything; Bappa's best friend and rival",
        "voice": "girl", "height": 0.60, "heads": 3.2,
        "head": {"shape": "egg", "w": 0.92, "ear": 0.95},
        "face": {"eye_style": "big", "eye_size": 0.105, "eye_spacing": 0.43, "iris": "#2a1a0e", "nose": "button",
                 "nose_size": 0.7, "mouth_w": 0.85, "lashes": True, "brow_thick": 0.75, "eye_y": 0.46, "child": 1,
                 "blush": True},
        "hair": {"style": "pigtails"},
        "body": {"shoulder": 0.58, "chest": 0.56, "waist": 0.52, "hip": 0.54, "arm_r": 0.08, "leg_r": 0.095, "leg": 0.39,
                 "arm": 0.40, "neck": 0.025, "shoe": "shoe", "foot": 1.0},
        "costume": {"type": "frock", "sleeve": "puff"},
        "colours": {"skin": "#d39a70", "hair": "#18120e", "frock": "#f5b700", "trim": "#fffaf0", "shoe": "#8b2e2e",
                    "lip": "#b5505a", "ribbon": "#d62839"},
        "accessories": [],
    },
}

# ---------------------------------------------------------------- the second character of each category (pending)
PENDING = {
    "gopal_kaku": ("adult_male", "গোপাল কাকু", "Gopal Kaku", "tall, thin postman with a pointed nose, side-burns, khaki shirt",
                   {"heads": 5.8, "head": {"shape": "long", "w": 0.70}, "hair": {"style": "side_part"}}),
    "malati": ("adult_female", "মালতী", "Malati", "plump cheerful fish-seller, round face, red-bordered yellow saree, big bun",
               {"heads": 5.0, "head": {"shape": "round", "w": 0.9}, "hair": {"style": "bun_white"}}),
    "haran_kaka": ("elderly_male", "হারান কাকা", "Haran Kaka", "short grumpy farmer, square head, grey stubble, gamchha",
                   {"heads": 4.9, "head": {"shape": "square", "w": 0.86}, "hair": {"style": "bald_sides"}}),
    "annapurna_pishi": ("elderly_female", "অন্নপূর্ণা পিসি", "Annapurna Pishi", "tall strict aunt, long face, spectacles, purple saree",
                        {"heads": 5.4, "head": {"shape": "long", "w": 0.74}, "hair": {"style": "bun_white"}}),
    "titu": ("boy", "টিটু", "Titu", "small shy boy with round glasses, bowl haircut, green shirt",
             {"heads": 3.5, "head": {"shape": "egg", "w": 0.95}, "hair": {"style": "spiky"}}),
    "piu": ("girl", "পিউ", "Piu", "tiny energetic girl with a short bob and a red frock, missing front tooth",
            {"heads": 3.4, "head": {"shape": "heart", "w": 0.95}, "hair": {"style": "pigtails"}}),
}


# ---------------------------------------------------------------- HORROR CAST (the horror channel; 23 Nov 2026)
# 4 folk ghosts (they float, their feet fade, their eyes glow) and 10 people of the stories. Same engine, same rules:
# every one is different in head, face, hair, body, costume and palette. Not approved until the owner says so.
CAST_HORROR = ["petni", "shakchunni", "brahmadaitya", "mechho_bhoot", "ojha", "shibu_dadu", "abhishek", "riya", "parul",
               "mokkhoda", "bhattacharya", "ramu_chowkidar", "sayan", "kishori"]


def _ghost(float_=0.07, alpha=0.88, tint="#d8ecff"):
    return {"float": float_, "alpha": alpha, "tint": tint}


SPECS.update({
    "petni": {
        "name_bn": "পেত্নী", "name_en": "Petni", "category": "ghost", "age": 0, "cast": "horror",
        "personality": "a sad, angry woman's ghost of the old tamarind tree; laughs a long thin laugh, never touches the ground",
        "voice": "thin, echoing female", "height": 0.98, "heads": 5.6, "ghost": _ghost(0.09, 0.86, "#dfefff"),
        "head": {"shape": "long", "w": 0.70, "ear": 0.8},
        "face": {"eye_style": "narrow", "eye_size": 0.085, "eye_spacing": 0.42, "iris": "#b0102a", "nose": "pointed",
                 "nose_size": 0.8, "mouth_w": 0.9, "brow_thick": 0.7, "ghost_eyes": True, "glow": "#ffe680"},
        "hair": {"style": "open_long"},
        "body": {"shoulder": 0.58, "chest": 0.55, "waist": 0.42, "hip": 0.6, "arm_r": 0.07, "leg_r": 0.09, "leg": 0.5,
                 "arm": 0.46, "shoe": "sandal", "foot": 0.8},
        "costume": {"type": "saree", "sleeve": "none"},
        "colours": {"skin": "#b9c3c9", "hair": "#0c0c10", "saree": "#f2f2ee", "border": "#e8e8e2", "blouse": "#e6e6e0",
                    "shoe": "#9aa3a8", "lip": "#6e2a35"},
        "accessories": [],
    },
    "shakchunni": {
        "name_bn": "শাঁকচুন্নি", "name_en": "Shakchunni", "category": "ghost", "age": 0, "cast": "horror",
        "personality": "the ghost of a married woman: wears shell bangles and sindoor, wants to take a living wife's place",
        "voice": "sweet, then hissing female", "height": 0.92, "heads": 5.0, "ghost": _ghost(0.06, 0.9, "#e6f5e6"),
        "head": {"shape": "egg", "w": 0.80, "ear": 0.9},
        "face": {"eye_style": "almond", "eye_size": 0.09, "eye_spacing": 0.44, "iris": "#1a3a1a", "nose": "button",
                 "nose_size": 0.85, "mouth_w": 1.0, "lashes": True, "brow_thick": 0.8, "ghost_eyes": True, "glow": "#c8ff9a"},
        "hair": {"style": "open_long"},
        "body": {"shoulder": 0.64, "chest": 0.64, "waist": 0.55, "hip": 0.7, "arm_r": 0.08, "leg_r": 0.1, "leg": 0.45,
                 "arm": 0.42, "shoe": "sandal", "foot": 0.8},
        "costume": {"type": "saree", "sleeve": "short"},
        "colours": {"skin": "#a9bba3", "hair": "#2a1e14", "saree": "#f4f1e6", "border": "#c8102e", "blouse": "#c8102e",
                    "shoe": "#8a9a86", "lip": "#7a2a2a"},
        "accessories": ["bangles", "sindoor", "bindi"],
    },
    "brahmadaitya": {
        "name_bn": "ব্রহ্মদৈত্য", "name_en": "Brahmadaitya", "category": "ghost", "age": 0, "cast": "horror",
        "personality": "the ghost of a learned brahmin in the bel tree; stern, proud, sometimes helps the good",
        "voice": "deep, booming male", "height": 1.12, "heads": 5.4, "ghost": _ghost(0.08, 0.9, "#fff2d8"),
        "head": {"shape": "long", "w": 0.74, "ear": 1.15},
        "face": {"eye_style": "narrow", "eye_size": 0.07, "eye_spacing": 0.42, "iris": "#3a2a10", "nose": "long",
                 "nose_size": 1.2, "mouth_w": 1.0, "brow_thick": 1.4, "brow_col": "#f0f0ea", "wrinkles": True,
                 "ghost_eyes": True, "glow": "#ffd866", "beard": 0.8},
        "hair": {"style": "tiki"},
        "body": {"shoulder": 0.78, "chest": 0.74, "waist": 0.62, "hip": 0.6, "arm_r": 0.09, "leg_r": 0.12, "leg": 0.46,
                 "arm": 0.44, "shoe": "sandal"},
        "costume": {"type": "kurta_dhoti", "sleeve": "none"},
        "colours": {"skin": "#d8c9b0", "hair": "#e8e8e0", "beard": "#f2f2ec", "kurta": "#efe6cf", "dhoti": "#f8f3e2",
                    "shoe": "#a8987c", "lip": "#7a5a4a", "tilak": "#e8e0c0"},
        "accessories": ["sacred_thread", "tilak"],
    },
    "mechho_bhoot": {
        "name_bn": "মেছো ভূত", "name_en": "Mechho Bhoot", "category": "ghost", "age": 0, "cast": "horror",
        "personality": "a skinny, greedy fish-loving ghost of the pond; follows fishermen home and begs 'machh de!'",
        "voice": "nasal, whiny male", "height": 0.86, "heads": 3.9, "ghost": _ghost(0.05, 0.9, "#d6f0ea"),
        "head": {"shape": "pear", "w": 0.86, "ear": 1.4},
        "face": {"eye_style": "big", "eye_size": 0.12, "eye_spacing": 0.44, "iris": "#203a30", "nose": "button",
                 "nose_size": 1.1, "mouth_w": 1.25, "brow_thick": 0.6, "ghost_eyes": True, "glow": "#aaffee"},
        "hair": {"style": "spiky"},
        "body": {"shoulder": 0.62, "chest": 0.5, "waist": 0.42, "hip": 0.5, "belly": 0.15, "arm_r": 0.06, "leg_r": 0.07,
                 "leg": 0.44, "arm": 0.48, "shoe": "sandal", "foot": 1.25},
        "costume": {"type": "tshirt_shorts", "sleeve": "none"},
        "colours": {"skin": "#7f9a96", "hair": "#18221f", "tshirt": "#7a8a6a", "stripe": "#5e6e50", "shorts": "#4e5a48",
                    "shoe": "#6f8a86", "lip": "#3a4a46"},
        "accessories": ["torn"],
    },
    "ojha": {
        "name_bn": "ওঝা গণপতি", "name_en": "Ojha Ganapati", "category": "elderly_male", "age": 66, "cast": "horror",
        "personality": "the village exorcist; fierce eyes, red cloth, matted hair; brave against ghosts, kind to the scared",
        "voice": "old male, commanding", "height": 0.96, "heads": 4.7,
        "head": {"shape": "square", "w": 0.84, "ear": 1.05},
        "face": {"eye_style": "round", "eye_size": 0.08, "eye_spacing": 0.43, "iris": "#3a1a0a", "nose": "broad",
                 "nose_size": 1.15, "mouth_w": 1.0, "brow_thick": 1.6, "brow_col": "#2a2420", "wrinkles": True, "beard": 1.0},
        "hair": {"style": "jata"},
        "body": {"shoulder": 0.82, "chest": 0.78, "waist": 0.7, "hip": 0.66, "arm_r": 0.1, "leg_r": 0.12, "leg": 0.44,
                 "arm": 0.43, "shoe": "sandal"},
        "costume": {"type": "kurta_dhoti", "sleeve": "half"},
        "colours": {"skin": "#9a6a48", "hair": "#2e2620", "beard": "#3a322c", "kurta": "#b3202a", "dhoti": "#c8402a",
                    "shoe": "#4a2e1e", "lip": "#6a3a2a", "tilak": "#e02020"},
        "accessories": ["rudraksha", "tilak"],
    },
    "shibu_dadu": {
        "name_bn": "শিবু দাদু", "name_en": "Shibu Dadu", "category": "elderly_male", "age": 80, "cast": "horror",
        "personality": "the old story-teller of the haunted tales; wrapped in a shawl, whispers, then shouts the scary part",
        "voice": "very old male, husky", "height": 0.88, "heads": 4.5,
        "head": {"shape": "oval", "w": 0.8, "ear": 1.25},
        "face": {"eye_style": "narrow", "eye_size": 0.066, "eye_spacing": 0.41, "iris": "#3a2a1a", "nose": "long",
                 "nose_size": 1.1, "mouth_w": 0.95, "brow_thick": 1.2, "brow_col": "#f4f4f0", "wrinkles": True,
                 "beard": 0.6, "eye_y": 0.52},
        "hair": {"style": "bald_sides"},
        "body": {"shoulder": 0.68, "chest": 0.62, "waist": 0.56, "hip": 0.56, "arm_r": 0.085, "leg_r": 0.1, "leg": 0.42,
                 "arm": 0.42, "stoop": 0.12, "shoe": "sandal"},
        "costume": {"type": "kurta_dhoti", "sleeve": "full"},
        "colours": {"skin": "#a87a58", "hair": "#efefea", "beard": "#f6f6f2", "kurta": "#e8dcc4", "dhoti": "#f3ecd9",
                    "shoe": "#4a3020", "lip": "#7a4a3a", "shawl": "#6b4a32"},
        "accessories": ["shawl"],
    },
    "abhishek": {
        "name_bn": "অভিষেক", "name_en": "Abhishek", "category": "adult_male", "age": 28, "cast": "horror",
        "personality": "a confident young man from Kolkata who laughs at ghost stories - until the night on the shortcut",
        "voice": "young male, confident", "height": 1.03, "heads": 5.3,
        "head": {"shape": "oval", "w": 0.76, "ear": 0.95},
        "face": {"eye_style": "almond", "eye_size": 0.074, "eye_spacing": 0.42, "iris": "#2a1a10", "nose": "pointed",
                 "nose_size": 0.95, "mouth_w": 1.0, "brow_thick": 1.1, "mouth_y": 0.15},
        "hair": {"style": "crop"},
        "body": {"shoulder": 0.78, "chest": 0.7, "waist": 0.58, "hip": 0.56, "arm_r": 0.095, "leg_r": 0.12, "leg": 0.47,
                 "arm": 0.43, "shoe": "shoe"},
        "costume": {"type": "shirt_trousers", "sleeve": "full"},
        "colours": {"skin": "#c48a62", "hair": "#120e0c", "shirt": "#2f3e5c", "trousers": "#3c4f6e", "shoe": "#2a2a2a",
                    "lip": "#9a5a48"},
        "accessories": [],
    },
    "riya": {
        "name_bn": "রিয়া", "name_en": "Riya", "category": "adult_female", "age": 22, "cast": "horror",
        "personality": "a sharp college student who does not believe in ghosts; wants proof, records everything",
        "voice": "young female, quick", "height": 0.92, "heads": 5.3,
        "head": {"shape": "egg", "w": 0.76, "ear": 0.85},
        "face": {"eye_style": "almond", "eye_size": 0.088, "eye_spacing": 0.43, "iris": "#2a160c", "nose": "button",
                 "nose_size": 0.8, "mouth_w": 0.9, "lashes": True, "brow_thick": 0.85},
        "hair": {"style": "braid_long"},
        "body": {"shoulder": 0.6, "chest": 0.58, "waist": 0.46, "hip": 0.6, "arm_r": 0.08, "leg_r": 0.1, "leg": 0.48,
                 "arm": 0.41, "shoe": "shoe", "foot": 0.85},
        "costume": {"type": "kurta_dhoti", "sleeve": "full"},
        "colours": {"skin": "#d6a07a", "hair": "#16100c", "kurta": "#c2185b", "dhoti": "#f3e5ab", "shoe": "#5a2a2a",
                    "lip": "#b0505a", "ribbon": "#f3e5ab"},
        "accessories": ["earrings"],
    },
    "parul": {
        "name_bn": "পারুল বৌদি", "name_en": "Parul Boudi", "category": "adult_female", "age": 34, "cast": "horror",
        "personality": "a village wife, practical and brave; lights the evening lamp, hears the knock at midnight",
        "voice": "adult female, warm", "height": 0.9, "heads": 5.0,
        "head": {"shape": "round", "w": 0.84, "ear": 0.9},
        "face": {"eye_style": "round", "eye_size": 0.082, "eye_spacing": 0.43, "iris": "#2a160c", "nose": "round",
                 "nose_size": 0.9, "mouth_w": 0.95, "lashes": True, "brow_thick": 0.85, "blush": True},
        "hair": {"style": "bun_black"},
        "body": {"shoulder": 0.66, "chest": 0.68, "waist": 0.6, "hip": 0.72, "belly": 0.05, "arm_r": 0.09, "leg_r": 0.11,
                 "leg": 0.45, "arm": 0.41, "shoe": "sandal", "foot": 0.85},
        "costume": {"type": "saree", "sleeve": "short"},
        "colours": {"skin": "#c98e66", "hair": "#120e0c", "saree": "#e65100", "border": "#5d1f8a", "blouse": "#5d1f8a",
                    "shoe": "#6a3a2a", "lip": "#a0404a"},
        "accessories": ["sindoor", "bindi", "bangles", "earrings"],
    },
    "mokkhoda": {
        "name_bn": "মোক্ষদা ঠাকুমা", "name_en": "Mokkhoda Thakuma", "category": "elderly_female", "age": 78, "cast": "horror",
        "personality": "a widow grandmother who has seen everything; murmurs prayers, knows which tree not to sit under",
        "voice": "very old female, trembling", "height": 0.8, "heads": 4.3,
        "head": {"shape": "pear", "w": 0.82, "ear": 1.0},
        "face": {"eye_style": "narrow", "eye_size": 0.064, "eye_spacing": 0.4, "iris": "#3a2a1a", "nose": "long",
                 "nose_size": 1.0, "mouth_w": 0.85, "brow_thick": 0.7, "brow_col": "#e8e6e0", "wrinkles": True},
        "hair": {"style": "bun_white"},
        "body": {"shoulder": 0.62, "chest": 0.6, "waist": 0.58, "hip": 0.62, "arm_r": 0.08, "leg_r": 0.1, "leg": 0.42,
                 "arm": 0.42, "stoop": 0.16, "shoe": "sandal", "foot": 0.85},
        "costume": {"type": "saree", "sleeve": "none"},
        "colours": {"skin": "#b98a68", "hair": "#f0efec", "saree": "#fbfaf6", "border": "#fbfaf6", "blouse": "#fbfaf6",
                    "shoe": "#5a3a22", "lip": "#8a5a50"},
        "accessories": [],
    },
    "bhattacharya": {
        "name_bn": "ভট্টাচার্য মশাই", "name_en": "Bhattacharya Moshai", "category": "adult_male", "age": 55, "cast": "horror",
        "personality": "the village priest; round, nervous, recites mantras very fast when frightened",
        "voice": "middle-aged male, nasal", "height": 0.95, "heads": 4.4,
        "head": {"shape": "round", "w": 0.92, "ear": 1.1},
        "face": {"eye_style": "round", "eye_size": 0.072, "eye_spacing": 0.42, "iris": "#3a2410", "nose": "round",
                 "nose_size": 1.1, "mouth_w": 1.05, "brow_thick": 1.0, "blush": True},
        "hair": {"style": "tiki"},
        "body": {"shoulder": 0.84, "chest": 0.86, "waist": 0.88, "hip": 0.78, "belly": 0.2, "arm_r": 0.11, "leg_r": 0.13,
                 "leg": 0.42, "arm": 0.4, "shoe": "sandal"},
        "costume": {"type": "kurta_dhoti", "sleeve": "half"},
        "colours": {"skin": "#d09a70", "hair": "#2a2018", "kurta": "#f6a623", "dhoti": "#fff3d6", "shoe": "#6a4020",
                    "lip": "#a05a48", "tilak": "#f0e0b0"},
        "accessories": ["sacred_thread", "tilak"],
    },
    "ramu_chowkidar": {
        "name_bn": "রামু চৌকিদার", "name_en": "Ramu Chowkidar", "category": "adult_male", "age": 45, "cast": "horror",
        "personality": "the night watchman with a lantern and a whistle; brave voice, shaking knees",
        "voice": "adult male, loud", "height": 1.0, "heads": 5.0,
        "head": {"shape": "square", "w": 0.82, "ear": 1.1},
        "face": {"eye_style": "round", "eye_size": 0.07, "eye_spacing": 0.43, "iris": "#2a1a0a", "nose": "long",
                 "nose_size": 1.1, "mouth_w": 1.05, "moustache": "thick", "brow_thick": 1.3},
        "hair": {"style": "crop"},
        "body": {"shoulder": 0.84, "chest": 0.78, "waist": 0.7, "hip": 0.64, "arm_r": 0.11, "leg_r": 0.13, "leg": 0.45,
                 "arm": 0.43, "shoe": "shoe"},
        "costume": {"type": "shirt_trousers", "sleeve": "half"},
        "colours": {"skin": "#8a5e40", "hair": "#141010", "shirt": "#8d7b4e", "trousers": "#6e6040", "shoe": "#2a2018",
                    "lip": "#6a3a2a"},
        "accessories": [],
    },
    "sayan": {
        "name_bn": "সায়ন", "name_en": "Sayan", "category": "boy", "age": 15, "cast": "horror",
        "personality": "Abhishek's younger cousin; believes every ghost story, sees things first, freezes with fear",
        "voice": "teenage boy", "height": 0.8, "heads": 4.2,
        "head": {"shape": "egg", "w": 0.86, "ear": 1.0},
        "face": {"eye_style": "big", "eye_size": 0.095, "eye_spacing": 0.43, "iris": "#2a160c", "nose": "button",
                 "nose_size": 0.85, "mouth_w": 0.95, "brow_thick": 0.95, "child": 0.5},
        "hair": {"style": "curly"},
        "body": {"shoulder": 0.64, "chest": 0.6, "waist": 0.54, "hip": 0.54, "arm_r": 0.08, "leg_r": 0.1, "leg": 0.45,
                 "arm": 0.42, "shoe": "shoe"},
        "costume": {"type": "tshirt_shorts", "sleeve": "short"},
        "colours": {"skin": "#c08460", "hair": "#14100c", "tshirt": "#2e7d32", "stripe": "#c5e1a5", "shorts": "#5d4037",
                    "shoe": "#333333", "lip": "#9a5040"},
        "accessories": [],
    },
    "kishori": {
        "name_bn": "কিশোরী", "name_en": "Kishori", "category": "girl", "age": 12, "cast": "horror",
        "personality": "the ojha's young helper; quiet, watchful, braver than the grown-ups",
        "voice": "young girl", "height": 0.7, "heads": 3.8,
        "head": {"shape": "heart", "w": 0.88, "ear": 0.9},
        "face": {"eye_style": "big", "eye_size": 0.1, "eye_spacing": 0.44, "iris": "#24140a", "nose": "button",
                 "nose_size": 0.75, "mouth_w": 0.85, "lashes": True, "brow_thick": 0.8, "child": 1, "blush": True},
        "hair": {"style": "braid_long"},
        "body": {"shoulder": 0.58, "chest": 0.56, "waist": 0.5, "hip": 0.54, "arm_r": 0.075, "leg_r": 0.09, "leg": 0.42,
                 "arm": 0.41, "shoe": "sandal", "foot": 0.9},
        "costume": {"type": "frock", "sleeve": "short"},
        "colours": {"skin": "#bf8862", "hair": "#120c08", "frock": "#5e35b1", "trim": "#ffd54f", "shoe": "#5a2a2a",
                    "lip": "#a0505a", "ribbon": "#ffd54f"},
        "accessories": ["bindi"],
    },
})


def horror_cast():
    return list(CAST_HORROR)


# A GHOST IN DISGUISE (23 Nov 2026): in many stories the ghost first appears as an ordinary girl / woman / man and
# only later turns into its ghost form. The disguise keeps the ghost's own face, height and build (so the audience
# can recognise her after the change) but has living colours, ordinary eyes, tidy hair and no float or glow.
DISGUISE = {
    "petni": {"colours": {"skin": "#d9a07a", "hair": "#120e0c", "saree": "#8e1b3a", "border": "#e6b422", "blouse": "#e6b422",
                          "lip": "#b04a50", "shoe": "#6a3a2a", "ribbon": "#e6b422"},
              "hair": {"style": "braid_long"}, "face": {"iris": "#2a160c", "lashes": True, "blush": True},
              "accessories": ["bindi", "bangles", "earrings"]},
    "shakchunni": {"colours": {"skin": "#d4a07c", "hair": "#120e0c", "lip": "#a8444a", "shoe": "#6a3a2a"},
                   "hair": {"style": "bun_black"}, "face": {"iris": "#2a160c", "lashes": True, "blush": True},
                   "accessories": ["sindoor", "bangles", "earrings"]},
    "brahmadaitya": {"colours": {"skin": "#c99a6e", "hair": "#3a3028", "beard": "#4a4038", "kurta": "#e8dcc0", "dhoti": "#f3ead2",
                                 "tilak": "#e65a1e", "lip": "#7a4a3a", "shoe": "#6a4a2e"},
                     "face": {"iris": "#2a160c"}},
    "mechho_bhoot": {"colours": {"skin": "#9a6a48", "hair": "#141010", "tshirt": "#3f6fa0", "stripe": "#f2f2f2", "shorts": "#3a3a3a",
                                 "lip": "#6a3a2a", "shoe": "#3a2a20"},
                     "face": {"iris": "#2a160c"}},
}


def human_form(cid):
    """the ghost's ordinary-person disguise (same face and body, living colours, no ghost effects)"""
    s = copy.deepcopy(SPECS[cid])
    d = DISGUISE.get(cid, {})
    s.pop("ghost", None)
    s["face"]["ghost_eyes"] = False
    s["face"].pop("glow", None)
    s["face"].update(d.get("face", {}))
    s["colours"].update(d.get("colours", {}))
    if "hair" in d:
        s["hair"] = dict(d["hair"])
    if "accessories" in d:
        s["accessories"] = [a for a in s.get("accessories", []) if a != "torn"] + \
            [a for a in d["accessories"] if a not in s.get("accessories", [])]
    else:
        s["accessories"] = [a for a in s.get("accessories", []) if a != "torn"]
    s["disguise_of"] = cid
    return s


def _mix(c1, c2, u):
    a = [int(c1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{int(round(x + (y - x) * u)):02x}" for x, y in zip(a, b))


def ghost_form(cid):
    """an ordinary person as the ghost they really are (the dead person of the story): the same face and body, pale
    blue-grey skin, glowing red eyes, faded clothes in rags, see-through, floating, feet fading"""
    s = copy.deepcopy(SPECS[cid])
    s["ghost"] = {"float": 0.07, "alpha": 0.85, "tint": "#dfefff"}
    for k, v in list(s["colours"].items()):
        if k == "skin":
            s["colours"][k] = _mix(v, "#b9c3c9", 0.75)
        elif k == "lip":
            s["colours"][k] = "#4a3a44"
        elif k != "hair":
            s["colours"][k] = _mix(v, "#eef0ee", 0.55)
    s["face"].update({"ghost_eyes": True, "iris": "#b0102a", "glow": "#ffe680"})
    s["accessories"] = [a for a in s.get("accessories", []) if a not in ("bindi", "sindoor")] + ["torn"]
    s["category"] = "ghost"
    s["ghost_of"] = cid
    return s


def get(cid):
    if cid.endswith("__ghost"):
        return ghost_form(cid[: -len("__ghost")])
    if cid.endswith("__human"):
        return human_form(cid[: -len("__human")])
    if cid not in SPECS:                                   # the kids' cast (kids.py) registers itself when imported,
        try:                                               # the characters made at night (prep.py) are in the library
            from tvtoon import kids  # noqa: F401
            from tvtoon import prep
            prep.load_library()
        except Exception:
            pass
    return copy.deepcopy(SPECS[cid])


def samples():
    return [c for c, s in SPECS.items() if s.get("sample") and s.get("cast") != "horror"]


# ------------------------------------------------------------------ the library: profiles, new characters (23 Nov 2026)
def profile(cid):
    """(kind, gender, age group) of a character, for casting"""
    s = get(cid)
    if s.get("animal"):
        return "animal", s.get("gender", "male"), "adult"
    cat = str(s.get("category", ""))
    kind = "ghost" if s.get("ghost") is not None or cat == "ghost" else "human"
    female = "female" in cat or cat == "girl" or s["costume"]["type"] in ("saree", "frock") or bool(s["face"].get("lashes"))
    a = s.get("age") or 30
    grp = "child" if a < 13 else "young" if a < 25 else "adult" if a < 58 else "old"
    if cat in ("boy", "girl"):
        grp = "child" if a < 13 else "young"
    return kind, "female" if female else "male", grp


def library():
    """every approved library character (the horror cast first, then the samples)"""
    return list(dict.fromkeys(horror_cast() + [c for c in SPECS if SPECS[c].get("sample") or SPECS[c].get("cast") == "horror"]))


BASES = {("male", "child"): "bappa", ("male", "young"): "sayan", ("male", "adult"): "ramu_chowkidar", ("male", "old"): "shibu_dadu",
         ("female", "child"): "kishori", ("female", "young"): "riya", ("female", "adult"): "parul", ("female", "old"): "mokkhoda"}
SKINS = ["#c48a62", "#a87452", "#d9a07a", "#b98060", "#8e5e40", "#cf9a72"]
CLOTH = ["#2f3e5c", "#7a2a22", "#2e6a3a", "#5a3a7a", "#a8862a", "#1f5f7a", "#8a4a2a", "#3a3a3a", "#c0603a", "#6a6a2a"]
HAIR_M = ["side_part", "crop", "curly", "spiky"]
HAIR_F = ["braid_long", "bun_black"]


def new_character(cid, name_bn, gender="male", age="adult", look="", seed=0, avoid=(), base=None):
    """a NEW supporting character with its own identity, made from the library's design rules (same drawing style,
    proportions of a real age group), different face, hair, skin and clothes. It is registered for this run (SPECS)
    and returned so the episode can save it in its own asset library."""
    rnd = random.Random(seed)
    base = base if base in SPECS else BASES.get((gender, age), "ramu_chowkidar")
    s = copy.deepcopy(SPECS[base])
    lk = str(look or "").lower()
    s.update({"name_bn": name_bn, "name_en": cid, "cast": "episode", "sample": False})
    s.pop("ghost", None)
    s["head"]["shape"] = rnd.choice(["round", "oval", "egg", "square", "long", "heart"])
    s["head"]["w"] = round(s["head"]["w"] * rnd.uniform(0.92, 1.08), 3)
    s["height"] = round(s["height"] * rnd.uniform(0.95, 1.05), 3)
    f = s["face"]
    f["eye_style"] = rnd.choice(["almond", "round", "narrow"])
    f["nose"] = rnd.choice(["button", "round", "long", "pointed", "broad"])
    f["nose_size"] = round(rnd.uniform(0.85, 1.15), 2)
    f["eye_size"] = round(f.get("eye_size", 0.075) * rnd.uniform(0.92, 1.1), 3)
    f.pop("ghost_eyes", None)
    s["colours"]["skin"] = rnd.choice(SKINS)
    if age == "old":
        s["colours"]["hair"] = rnd.choice(["#d8d8d0", "#a8a8a0", "#e8e8e0"])
    else:
        s["colours"]["hair"] = rnd.choice(["#120e0c", "#1e1410", "#2a1a10"])
    if gender == "male" and age != "old":
        s["hair"] = {"style": rnd.choice(HAIR_M)}
    elif gender == "female" and age != "old":
        s["hair"] = {"style": rnd.choice(HAIR_F if age != "child" else ["braid_long", "pigtails"])}
    for k in list(s["colours"]):
        if k in ("shirt", "trousers", "kurta", "dhoti", "saree", "blouse", "tshirt", "shorts", "frock", "border"):
            s["colours"][k] = rnd.choice(CLOTH)
    if any(w in lk for w in ("glasses", "spectacle", "চশমা")):
        s.setdefault("accessories", []).append("glasses_round")
    if gender == "male" and any(w in lk for w in ("beard", "দাড়ি")):
        f["beard"] = 1.0
        s["colours"].setdefault("beard", s["colours"]["hair"])
    if gender == "male" and any(w in lk for w in ("moustache", "mustache", "গোঁফ")):
        s["colours"]["moustache"] = s["colours"]["hair"]
    if any(w in lk for w in ("white", "সাদা")):
        for k in ("shirt", "kurta", "saree", "dhoti"):
            if k in s["colours"]:
                s["colours"][k] = "#f2f0e8"
    SPECS[cid] = s
    return s


def register(cid, spec):
    """put a saved episode character back into the library for this run"""
    SPECS[cid] = copy.deepcopy(spec)
