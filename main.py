#!/usr/bin/env python3
"""
Cartoon Story Bot (Hindi + Bengali, alternating)
-----------------------
Every run makes ONE brand-new, original Hindi or Bengali kids' cartoon story video and posts it to
a Facebook Page:

  1. Google Gemini          -> story with dialogue, title, description, hashtags
  2. Cloudflare Workers AI  -> cartoon pictures, a new picture for every line, same characters
  3. Microsoft Edge voices  -> sweet narrator + a different voice for every character (gTTS backup)
  4. Sound engine           -> real sound effects from freesound.org (CC0) timed to the story,
                               nature ambience and soft cheerful music
  5. FFmpeg + OpenCV        -> moving picture layers, close-ups, subtitles
  6. Facebook Graph API

Secrets: GEMINI_API_KEY, CF_ACCOUNT_ID, CF_API_TOKEN, FB_PAGE_ID, FB_PAGE_TOKEN
Optional: PAGE_NAME, FREESOUND_API_KEY, MAX_IMAGES, DRY_RUN=1, MOCK=1
"""
import asyncio
import base64
import datetime as dt
import glob
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import wave

import requests
import extras
try:
    import puppet                    # TV-style cut-out cartoon with our ready-made characters
except Exception:                     # (never stops the bot - the old way still works)
    puppet = None
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ----------------------------------------------------------------- settings
W, H, FPS, SR = 1280, 720, 25, 44100
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
HISTORY = os.path.join(HERE, "history.json")
SFX_DIR = os.path.join(HERE, "sfx")          # optional: your own sounds, e.g. sfx/rain.mp3

MOCK = os.getenv("MOCK") == "1"
DRY_RUN = MOCK or os.getenv("DRY_RUN") == "1"

LANGS = {
    "hi": {
        "name": "Hindi", "script": "Devanagari",
        "font_family": "Noto Sans Devanagari", "font_glob": "NotoSansDevanagari",
        "male": ["hi-IN-MadhurNeural"], "female": ["hi-IN-SwaraNeural"],
        "narrator": ("hi-IN-SwaraNeural", "-4%", "+2Hz"), "gtts": "hi",
        "intro": "नमस्ते प्यारे बच्चों! मैं हूँ आपकी लूमी दीदी। आज की कहानी है... {title}।",
        "outro": "कहानी अच्छी लगी तो लाइक कीजिए, शेयर कीजिए, और ऐसी ही प्यारी कहानियों के लिए {page} को फॉलो ज़रूर कीजिए!",
        "page_default": "हमारे पेज",
        "share_cta": "🔁 कहानी पसंद आई? दोस्तों और बच्चों को शेयर करें और पेज फ़ॉलो करें - रोज़ नई मज़ेदार कहानी!",
        "ai_note": "🎨 यह कहानी और तस्वीरें AI की मदद से बनाई गई हैं।",
        "moral_intro": "तो बच्चों, इस कहानी से हमें यह सीख मिलती है:",
        "labels": {"moral": "नैतिक कहानी", "animal": "जानवरों की कहानी", "funny": "मज़ेदार कहानी",
                   "folk": "दादी माँ की कहानी", "panchatantra": "पंचतंत्र की कहानी", "life": "जीवन की सीख",
                   "witty": "चतुराई की कहानी", "fairy": "परी की कहानी", "adventure": "साहसिक कहानी",
                   "festival": "त्योहार की कहानी", "bedtime": "सोने से पहले की कहानी", "school": "स्कूल की कहानी",
                   "nature": "प्रकृति की कहानी", "divine": "भगवान की लीला", "gopal": "गोपाल भांड की कहानी",
                   "birbal": "अकबर-बीरबल", "betal": "विक्रम-बेताल", "jataka": "जातक कथा", "para": "मोहल्ले की कहानी",
                   "detective": "जासूसी कहानी", "lok": "लोककथा", "ramayan": "रामायण", "mahabharat": "महाभारत",
                   "gita": "गीता ज्ञान", "rhyme": "कविता कहानी"},
        "series_titles": {"gopal": "गोपाल भांड", "folk": "दादी माँ की कहानी", "panchatantra": "पंचतंत्र",
                          "divine": "भगवान की लीला", "birbal": "अकबर-बीरबल", "betal": "विक्रम-बेताल",
                          "ramayan": "रामायण", "mahabharat": "महाभारत", "gita": "गीता ज्ञान"},
        "part": "भाग {n}", "episode": "{name} भाग {n}",
        "outro_part1": "कहानी का अगला भाग कल शाम 7 बजे... मिस मत कीजिए, अभी {page} को फॉलो कीजिए!",
        "vote_line": "अब आपकी बारी! कल शाम की कहानी कौन सी हो? {o1} चाहिए तो कमेंट में 1 लिखिए, {o2} चाहिए तो 2 लिखिए!",
        "vote_thanks": "आज की कहानी आपने ही वोट देकर चुनी थी। धन्यवाद!",
        "viewer_chars": "आज की कहानी के कुछ किरदारों के नाम हमारे दर्शक {names} के नाम से हैं। धन्यवाद!",
        "reel_comment": "🎬 पूरी कहानी यहाँ देखें 👉 {link}",
        "riddle_title": "आज की पहेली", "riddle_msg": "🧩 आज की पहेली:\n\n{q}\n\nजवाब कमेंट में लिखिए! सही जवाब कल बताएँगे 😉",
        "riddle_prev": "✅ कल की पहेली का जवाब: {a}",
        "example_tags": "#HindiKahani #MoralStories #CartoonStory",
        "badge": "लाइक • शेयर • फॉलो", "ch_intro": "शुरुआत", "ch_end": "सीख", "chapters": "⏱️ अध्याय",
        "cta": "पूरी कहानी देखने के लिए कमेंट का लिंक दबाइए 👇", "playlist_tail": "Hindi Kids Stories", "full_link": "पूरी कहानी देखें:",
        "quiz_title": "क्विज़ टाइम!", "quiz_labels": ["क", "ख", "ग"],
        "quiz_intro": "अब एक छोटा सा सवाल, बच्चों!", "quiz_count": "सोचो... तीन... दो... एक...",
        "quiz_answer": "सही जवाब है... {lab}: {ans}! क्या तुमने सही बताया? कमेंट में लिखो!",
        "ann1": "नई प्यारी कहानी", "ann_msg": "🧸 {when} आ रही है लूमी दीदी की नई कहानी! बच्चों को ज़रूर दिखाइए 🔔",
        "comp_title": "{m} मिनट की प्यारी कहानियाँ 🧸 | हफ्ते की {n} कहानियाँ एक साथ", "comp_thumb": "{m} मिनट की कहानियाँ",
        "how_to_join": "बच्चों, क्विज़ का जवाब कमेंट में लिखो, जैसे क, ख या ग। जिनका जवाब सही होगा, उनका नाम अगली कहानी में लूमी दीदी बोलेगी! और रंग भरा हुआ चित्र कमेंट में भेजना मत भूलना।",
        "shout_line": "पिछली कहानी के क्विज़ का सही जवाब दिया था {names} ने। शाबाश! तालियाँ!",
        "join_comment": "👇 कैसे हिस्सा लें:\n✅ क्विज़ का जवाब कमेंट में लिखिए (क / ख / ग) - सही जवाब देने वालों का नाम अगली कहानी में!\n🖍️ रंग भरा चित्र फोटो खींचकर कमेंट में भेजिए\n🔔 फॉलो कीजिए ताकि रोज़ की कहानी मिस न हो",
        "shout_comment": "🏆 पिछली कहानी के क्विज़ के सही जवाब: {names} - शाबाश!",
        "congrats_reply": "🏆 शाबाश! आपका जवाब सही था, आज की कहानी में लूमी दीदी ने आपका नाम लिया है 👉 {link}",
        "words_title": "आज के 3 अंग्रेज़ी शब्द", "words_line": "अब सीखते हैं आज की कहानी के तीन अंग्रेज़ी शब्द! {items}",
        "word_item": "{en} मतलब {m}।", "color_title": "रंग भरो!",
        "color_msg": "🖍️ आज का रंग भरने वाला पन्ना! प्रिंट कीजिए, बच्चों से रंग भरवाइए और फोटो कमेंट में भेजिए 🌈 सबसे सुंदर चित्र अगली कहानी में दिखाएँगे!",
    },
    "bn": {
        "name": "Bengali", "script": "Bengali",
        "font_family": "Noto Sans Bengali", "font_glob": "NotoSansBengali",
        "male": ["bn-IN-BashkarNeural", "bn-IN-BashkarNeural"],
        "female": ["bn-IN-TanishaaNeural", "bn-IN-TanishaaNeural"],
        "narrator": ("bn-IN-TanishaaNeural", "-4%", "+2Hz"), "gtts": "bn",
        "intro": "নমস্কার বন্ধুরা! আমি লুমি দিদি। আজকের গল্প... {title}।",
        "outro": "গল্পটা ভালো লাগলে লাইক করুন, শেয়ার করুন, আর এমন আরও মিষ্টি গল্পের জন্য {page} ফলো করতে ভুলবেন না!",
        "page_default": "আমাদের পেজ",
        "share_cta": "🔁 গল্পটা ভালো লাগলে বন্ধুদের শেয়ার করুন আর পেজটা ফলো করুন - রোজ নতুন মজার গল্প!",
        "ai_note": "🎨 এই গল্প ও ছবি AI-এর সাহায্যে তৈরি।",
        "moral_intro": "তাহলে বন্ধুরা, এই গল্প থেকে আমরা শিখলাম:",
        "labels": {"moral": "নীতিকথার গল্প", "animal": "পশুপাখির গল্প", "funny": "মজার গল্প",
                   "folk": "ঠাকুমার ঝুলি", "panchatantra": "পঞ্চতন্ত্রের গল্প", "life": "জীবনের শিক্ষা",
                   "witty": "বুদ্ধির গল্প", "fairy": "পরীর গল্প", "adventure": "অ্যাডভেঞ্চারের গল্প",
                   "festival": "উৎসবের গল্প", "bedtime": "ঘুমপাড়ানি গল্প", "school": "স্কুলের গল্প",
                   "nature": "প্রকৃতির গল্প", "divine": "ঠাকুরের লীলা", "gopal": "গোপাল ভাঁড়ের গল্প",
                   "birbal": "আকবর-বীরবল", "betal": "বিক্রম-বেতাল", "jataka": "জাতকের গল্প", "para": "পাড়ার মজার গল্প",
                   "detective": "গোয়েন্দা গল্প", "lok": "বাংলার লোককথা", "ramayan": "রামায়ণ", "mahabharat": "মহাভারত",
                   "gita": "গীতার জ্ঞান", "rhyme": "ছড়ার গল্প"},
        "series_titles": {"gopal": "গোপাল ভাঁড়", "folk": "ঠাকুমার ঝুলি", "panchatantra": "পঞ্চতন্ত্র",
                          "divine": "ঠাকুরের লীলা", "birbal": "আকবর-বীরবল", "betal": "বিক্রম-বেতাল",
                          "jataka": "জাতকের গল্প", "para": "পাড়ার মজা", "detective": "ঝন্টু-মিনির রহস্য",
                          "lok": "বাংলার লোককথা", "ramayan": "রামায়ণ", "mahabharat": "মহাভারত", "gita": "গীতার জ্ঞান",
                          "rhyme": "ছড়ার দেশে"},
        "part": "পর্ব {n}", "episode": "{name} পর্ব {n}",
        "outro_part1": "গল্পের পরের পর্ব আসছে কাল সন্ধ্যা ৭টায়... মিস করতে না চাইলে এখনই {page} ফলো করে রাখুন!",
        "vote_line": "এবার আপনার পালা! কাল সন্ধ্যার গল্প কোনটা হবে? {o1} শুনতে চাইলে কমেন্টে লিখুন ১, আর {o2} শুনতে চাইলে লিখুন ২। বেশি ভোট যেটা পাবে, সেটাই আসবে!",
        "vote_thanks": "আজকের গল্পটা আপনারাই ভোট দিয়ে বেছে নিয়েছিলেন। ধন্যবাদ বন্ধুরা!",
        "viewer_chars": "আজকের গল্পের কয়েকটা চরিত্রের নাম এসেছে আমাদের দর্শক বন্ধু {names}-এর নাম থেকে। ধন্যবাদ!",
        "reel_comment": "🎬 পুরো গল্পটা এখানে দেখুন 👉 {link}",
        "riddle_title": "আজকের ধাঁধা", "riddle_msg": "🧩 আজকের ধাঁধা:\n\n{q}\n\nউত্তর কমেন্টে লিখুন! ঠিক উত্তর জানাব কাল 😉",
        "riddle_prev": "✅ গতকালের ধাঁধার উত্তর: {a}",
        "example_tags": "#বাংলাগল্প #RupkotharGolpo #CartoonStory",
        "badge": "লাইক • শেয়ার • ফলো", "ch_intro": "শুরু", "ch_end": "শিক্ষা", "chapters": "⏱️ অধ্যায়",
        "cta": "পুরো গল্প দেখতে কমেন্টের লিংকে ক্লিক করুন 👇", "playlist_tail": "Bangla Kids Stories", "full_link": "পুরো গল্প দেখুন:",
        "quiz_title": "কুইজ টাইম!", "quiz_labels": ["ক", "খ", "গ"],
        "quiz_intro": "এবার একটা ছোট্ট প্রশ্ন, বন্ধুরা!", "quiz_count": "ভাবুন... তিন... দুই... এক...",
        "quiz_answer": "ঠিক উত্তর হলো... {lab}: {ans}! আপনি কি ঠিক বলেছিলেন? কমেন্টে লিখুন!",
        "ann1": "নতুন মিষ্টি গল্প", "ann_msg": "🎬 {when} আসছে লুমি দিদির নতুন গল্প! পরিবারের সবাইকে নিয়ে দেখুন 🔔",
        "comp_title": "{m} মিনিটের সেরা গল্প 🎬 | সপ্তাহের {n}টি গল্প একসাথে", "comp_thumb": "{m} মিনিটের গল্প",
        "how_to_join": "বন্ধুরা, কুইজের উত্তর কমেন্টে লিখুন, যেমন ক, খ বা গ। ঠিক উত্তরদাতাদের নাম পরের গল্পে বলব! আর কমেন্টে নিজের নামটা লিখে রাখুন, পরের কোনো গল্পে আপনার নামেই একটা চরিত্র আসতে পারে!",
        "shout_line": "আগের গল্পের কুইজে ঠিক উত্তর দিয়েছিল {names}। দারুণ! হাততালি!",
        "join_comment": "👇 কীভাবে অংশ নেবেন:\n✅ কুইজের উত্তর কমেন্টে লিখুন (ক / খ / গ) - ঠিক উত্তরদাতাদের নাম পরের গল্পে!\n🗳️ ভোট থাকলে ১ বা ২ লিখুন - পরের গল্প আপনারাই বাছবেন\n🙋 কমেন্টে নিজের নাম লিখুন - পরের গল্পে আপনার নামে চরিত্র আসতে পারে\n📅 রোজ দুপুর ১টা: সোম গোপাল ভাঁড় • মঙ্গল ঠাকুমার ঝুলি • বুধ আকবর-বীরবল • বৃহস্পতি রামায়ণ • শুক্র বিক্রম-বেতাল • শনি মহাভারত • রবি গীতার জ্ঞান\n🔔 ফলো করুন, রোজের গল্প যেন মিস না হয়",
        "shout_comment": "🏆 আগের গল্পের কুইজে ঠিক উত্তর: {names} - দারুণ!",
        "congrats_reply": "🏆 দারুণ! আপনার উত্তর ঠিক ছিল, আজকের গল্পে লুমি দিদি আপনার নাম বলেছে 👉 {link}",
        "words_title": "আজকের ৩টে ইংরেজি শব্দ", "words_line": "এবার শিখি আজকের গল্পের তিনটে ইংরেজি শব্দ! {items}",
        "word_item": "{en} মানে {m}।", "color_title": "রং করো!",
        "color_msg": "🖍️ আজকের রং করার পাতা! প্রিন্ট করুন, ছোটদের দিয়ে রং করান আর ছবি তুলে কমেন্টে দিন 🌈",
    },
}

CATEGORIES = {
    # devotional stories of the gods and their devotees (Puranas, bhakti legends - ancient, public domain)
    "divine": ["little Krishna the butter thief (Makhan Chor) and Mother Yashoda",
               "Yashoda sees the whole universe in baby Krishna's mouth", "Krishna lifts Govardhan hill to save Vrindavan",
               "Krishna and his poor friend Sudama's handful of rice", "Krishna calms the serpent Kaliya in the Yamuna",
               "Meera Bai's love for Krishna", "Lord Shiva becomes Neelkanth to save the world from poison",
               "Shiva protects the child devotee Markandeya", "the hunter Kannappa's devotion to Shiva",
               "Shiva brings the river Ganga down to earth", "Ma Kali comes as a little girl to help Ramprasad mend his fence",
               "Sri Ramakrishna and Ma Kali at Dakshineswar", "Lord Jagannath eats Karma Bai's morning khichdi",
               "the devotee Salabega and Lord Jagannath's chariot", "King Indradyumna and the making of Jagannath",
               "Ganesha goes around his parents to win the race", "Ganesha and Kubera's grand feast",
               "Ganesha writes the Mahabharata with his broken tusk", "baby Hanuman tries to eat the sun",
               "Hanuman carries the Sanjeevani mountain", "Shabari's sweet berries for Lord Rama",
               "the little squirrel who helped build Rama's bridge", "young Prahlad's faith in Lord Vishnu",
               "child Dhruva's prayer becomes the pole star", "Ma Durga comes home for Durga Puja",
               "Ma Lakshmi visits the house that stays awake on Kojagari Purnima",
               "Ma Saraswati blesses a poor student", "Behula's devotion and Ma Manasa",
               "Chaitanya Mahaprabhu's kirtan in Nabadwip", "Lord Vishnu as Vamana and King Bali"],
    # clever-wit folk anecdotes (centuries-old, public domain) - retold in our own words
    # Gopal Bhar of Krishnanagar - centuries-old Bengali folk anecdotes (public domain), told in our own words
    "gopal": ["the king's impossible challenge: bring milk from a bull", "Gopal outsmarts a greedy moneylender",
              "Gopal counts all the crows of Krishnanagar", "how many stars are in the sky? Gopal's clever answer",
              "Gopal and the jealous courtiers' trap", "Gopal sells 'magic' sweets to a boastful merchant",
              "Gopal teaches the miser zamindar to share", "the king's elephant that would not eat",
              "Gopal wins the riddle contest against a proud visiting pandit", "Gopal finds the middle of the earth",
              "Gopal saves a poor farmer's land", "the hot rasgulla eating race at court",
              "Gopal and the king's lost golden ring", "Gopal cures the king's laziness",
              "Gopal and the 'talking' parrot that told the truth", "Gopal's wife and the missing fish curry",
              "Gopal and the king's dream of a golden mango tree", "Gopal turns the king's punishment into a reward"],
    "witty": ["Birbal and the emperor's tricky question", "Birbal finds the real thief with sticks",
              "Tenali Raman and the boastful scholar", "Tenali Raman saves the royal garden",
              "a clever village girl solves the minister's riddle", "the wise judge and two mothers"],
    "fairy": ["a little fairy who lost her wings", "the fairy of the lotus pond grants three wishes",
              "a magic paintbrush that makes drawings real", "the moon fairy visits a poor girl",
              "a rainbow bridge to the land of clouds", "the star that fell into a village garden",
              "a talking tree that grants wishes only to kind children", "the fairy queen's lost crown"],
    "adventure": ["two friends find a secret cave map", "a brave girl crosses the river to bring medicine",
                  "the lost elephant calf and the search party", "a kite that flies to a strange island",
                  "the treasure hidden under the old banyan tree", "a little boat's journey down the Ganga",
                  "lost in the Sundarbans with a friendly tiger cub", "the mountain goat who climbed the highest peak"],
    "festival": ["Durga Puja and the little drummer boy", "a Diwali lamp for the lonely grandmother",
                 "Holi colours and a sad friend", "Eid sweets shared with the whole street",
                 "Christmas gift for the poor shoeshine boy", "Raksha Bandhan and the brother far away",
                 "Poila Baishakh new year at the village fair", "Makar Sankranti kite festival friendship"],
    "bedtime": ["a sleepy little owl who could not sleep at night", "the moon tells a story to a child",
                "a teddy bear's night adventure", "the cloud that wanted to be a pillow",
                "counting stars with grandfather", "the lullaby of the river"],
    "school": ["the new student who could not speak the language", "a lost tiffin box mystery",
               "the class monitor learns fairness", "a sports day race where helping wins",
               "a homework copied and the honest confession", "the school garden project"],
    "nature": ["the last tree in the city", "a sparrow family and the plastic bag", "the river that got sick",
               "saving rainwater in the village", "a bee teaches why flowers matter", "the honest woodcutter and the forest"],
    # old Bengali/Indian fairy tales (Thakurmar Jhuli style - public domain folk tales, retold in our own words)
    "folk": ["a brave prince and the demon (rakkhosh) kingdom", "Lalkamal and Neelkamal, two brother princes",
             "the magic birds Byangoma and Byangomi who give advice", "the flying horse Pakkhiraj",
             "seven brothers turned into champa flowers and their sister", "Kiranmala, the brave princess",
             "a poor farmer's son and the sleeping princess", "a magic golden stick and silver stick",
             "the clever youngest daughter-in-law", "a kind girl and the witch of the forest",
             "the king's lost ring and the honest fisherman", "a talking golden fish in the village pond",
             "the giant's garden and the little shepherd", "a magic pitcher that never empties"],
    # Panchatantra / Jataka / Hitopadesha fables (ancient, public domain, retold in our own words)
    "panchatantra": ["the monkey and the crocodile", "the clever rabbit and the proud lion",
                     "the blue jackal", "the talkative tortoise and the two geese", "the crows and the cobra",
                     "the brahmin and the three thieves", "the mice that saved the elephants",
                     "the lion, the mouse and the net", "the foolish lion and the jackal's cave",
                     "the four friends: deer, crow, mouse and tortoise", "the heron and the crab",
                     "the monkey king who saved his tribe (Jataka)", "the golden swan (Jataka)",
                     "the loyal mongoose", "the greedy cat who judged two birds"],
    # everyday stories about people that teach a life lesson
    "life": ["a boy who wasted food learns where rice comes from", "a girl who helps a lonely old neighbour",
             "the honest rickshaw puller who returns a lost bag", "a child too busy with the mobile phone",
             "respecting the school teacher", "a piggy bank and the value of saving money",
             "a rich boy and a poor boy become best friends", "telling the truth to mother after breaking a vase",
             "keeping the village clean", "sharing lunch with a new classmate",
             "a father's quiet sacrifice", "a grandmother's lesson about patience",
             "a boy who made fun of others learns kindness", "never giving up after failing an exam",
             "thanking the farmer, the postman and the sweeper"],
    "moral": ["honesty", "greed and its result", "kindness to others", "hard work", "true friendship", "patience",
              "sharing", "respecting elders", "telling lies", "helping the weak", "pride and humility",
              "saving water", "obeying parents", "courage", "gratitude"],
    "animal": ["jungle animals", "a clever fox", "a brave little rabbit", "an elephant family", "birds in a big tree",
               "a lazy lion", "a monkey and a crocodile", "farm animals", "a thirsty crow", "ants and a grasshopper",
               "a peacock and a crow", "sea creatures", "a lost puppy", "a wise owl"],
    "funny": ["a forgetful village man", "a silly king and a clever minister", "a greedy shopkeeper tricked",
              "a lazy servant", "a talking parrot", "a funny school day", "a mix-up at a wedding", "a clumsy thief",
              "a boastful wrestler", "a naughty goat", "a magical cooking pot gone wrong"],
}

# ---- v15: stories for ALL ages ----
CATEGORIES.update({
    # Akbar-Birbal: centuries-old folk anecdotes (public domain), retold in our own words
    "birbal": ["Birbal and the line that became shorter without touching it", "Birbal counts the crows of Agra",
               "Birbal's khichdi that cooked far from the fire", "who is the biggest fool? Birbal's list",
               "Birbal and the mango tree's real owner", "Birbal finds the thief with magic sticks",
               "the emperor's question: what is the best weapon?", "Birbal and the well that was sold, not its water",
               "Birbal brings the emperor 'nothing' as a gift", "Birbal and the jealous courtier's trap",
               "Birbal's answer: how many bangles in your wife's hand?", "Birbal and the donkey's wisdom"],
    # Vikram-Betal (Baital Pachisi, ancient, public domain): every tale ends with Betal's riddle
    "betal": ["the three suitors who brought the princess back to life", "the switched heads of husband and brother",
              "the most sensitive of three queens", "the four brothers who made a lion alive",
              "the thief who laughed and then cried", "who is the real father of the child?",
              "the generous merchant and the sacrifice", "the king's servant who gave everything"],
    "jataka": ["the golden goose that gave one feather at a time", "the monkey bridge: the monkey king saves his tribe",
               "the quail who led his flock to freedom", "the elephant who saved travellers in the desert",
               "the honest woodcutter's choice", "the parrot who would not leave the burning tree",
               "the deer king who offered himself", "the tortoise who could not keep quiet"],
    # our own recurring Bengali para (neighbourhood) family comedy - original characters
    "para": ["Bhombol-da's new bicycle and the whole para chasing it", "the cricket match on the para field",
             "Dadu's lost glasses that were on his head", "the power cut during the big football final",
             "Mashima's secret pickle recipe goes missing", "the para Durga Puja committee's crazy meeting",
             "the new neighbour who says he is a famous singer", "the family wedding where everyone got the date wrong",
             "the morning walk club and the runaway goat", "Kaku's mobile phone that only talks in English"],
    # our own detective duo Jhontu and Mini - original characters, small clever mysteries
    "detective": ["the missing rosogolla from the sweet shop", "the mystery of the midnight bell in the old school",
                  "who took Thakuma's gold locket?", "the footprints that walked backwards",
                  "the secret of the locked attic", "the vanished prize cup of the para club",
                  "the parrot that spoke the thief's name", "the coded letter in the library book"],
    # folk tales from the districts of Bengal (public domain), retold in our own words
    "lok": ["Purulia's Chhau dancer and the forest spirit", "the Bankura terracotta horse that came alive",
            "Coochbehar's clever potter", "the boatman of the Padma and the river goddess's test",
            "Bishnupur's music and the proud king", "the honey collector of Sundarbans and Bonbibi",
            "the Teesta and the shepherd girl", "the weaver of Shantipur's magic sari"],
    # original rhyme-stories (ছড়া) told in verse
    "rhyme": ["the cat who wanted to go to the fair", "the rain that came to a village wedding",
              "the moon who came down to eat pithe", "the clever little ant and the big elephant",
              "the river's song to the sea", "Dadu's umbrella that flew away"],
})
CATEGORIES["life"] += ["an old father waiting at the railway station", "a mother's torn sari and her son's first salary",
                       "the rickshaw puller who paid his daughter's college fees", "two old friends meet after fifty years",
                       "the teacher who never forgot a poor student", "a grandmother's last letter"]
# ---- the great epics and the Gita: told IN ORDER, one episode each week (faithful to the scriptures)
EPIC = {
    "ramayan": ["Ratnakar the robber becomes the sage Valmiki and the first verse is born",
                "King Dasharatha's yajna and the birth of Rama, Lakshmana, Bharata and Shatrughna",
                "Sage Vishwamitra takes young Rama and Lakshmana to protect the yajna (Tadaka is defeated)",
                "Rama frees Ahalya from the curse", "Rama breaks Shiva's bow and marries Sita in Mithila",
                "Queen Kaikeyi asks for her two boons", "Rama, Sita and Lakshmana leave Ayodhya for the forest",
                "Guhak the boatman washes Rama's feet and takes them across the Ganga",
                "Bharata brings Rama's sandals (paduka) back to rule Ayodhya", "life in the Panchavati forest",
                "Surpanakha comes to Panchavati", "the golden deer (Maricha)",
                "Ravana carries Sita away and brave Jatayu fights for her", "Shabari's sweet berries for Rama",
                "Rama meets Hanuman and Sugriva", "Hanuman's great leap across the ocean",
                "Hanuman meets Sita in the Ashoka garden with Rama's ring", "Hanuman's burning tail and Lanka",
                "Vibhishana comes to Rama", "the bridge to Lanka (Ram Setu) and the little squirrel",
                "Angad's foot in Ravana's court", "Lakshmana falls and Hanuman brings the Sanjeevani mountain",
                "Kumbhakarna wakes up", "Rama's Akal Bodhan - the untimely worship of Ma Durga (Krittivasi Ramayan)",
                "Rama's victory over Ravana", "Sita's agni pariksha", "the return to Ayodhya - the first Diwali lamps",
                "Rama's coronation and Ram Rajya"],
    "mahabharat": ["Devavrata's terrible vow - he becomes Bhishma", "the birth of the Pandavas and the Kauravas",
                   "Guru Drona's test - Arjuna sees only the bird's eye", "Ekalavya's devotion to his guru",
                   "Karna comes to the tournament", "the house of lac (Lakshagriha) and the escape",
                   "Bhima saves the village from Bakasura", "Draupadi's swayamvar - Arjuna hits the fish's eye",
                   "Indraprastha and Maya's wonderful palace", "the Rajasuya yajna",
                   "the game of dice", "Krishna protects Draupadi's honour",
                   "the Akshaya Patra and Sage Durvasa's visit", "the Yaksha's questions to Yudhishthira",
                   "the secret year in King Virata's palace", "Krishna's peace mission and his universal form in the court",
                   "Kunti meets Karna", "Arjuna chooses Krishna, Duryodhana chooses the army",
                   "Krishna's Gita on the battlefield of Kurukshetra", "Bhishma on the bed of arrows",
                   "brave Abhimanyu and the Chakravyuha", "Karna gives away his armour and earrings",
                   "the end of the war and Yudhishthira's crowning", "the last journey of the Pandavas and the faithful dog"],
    "gita": ["Chapter 1 - Arjuna's sorrow on the battlefield", "Chapter 2 - the soul never dies; do your duty without "
             "worrying about the result (2.47)", "Chapter 3 - Karma Yoga: selfless work",
             "Chapter 4 - whenever dharma declines, I come (4.7-4.8)", "Chapter 5 - working without attachment",
             "Chapter 6 - the restless mind and meditation", "Chapter 7 - knowing God in everything",
             "Chapter 8 - remembering God at every moment", "Chapter 9 - a leaf, a flower, a fruit or water offered "
             "with love (9.26)", "Chapter 10 - God's glories in the world", "Chapter 11 - the universal form (Vishwarupa)",
             "Chapter 12 - the qualities of a true devotee", "Chapter 13 - the body and the knower of the body",
             "Chapter 14 - the three gunas", "Chapter 15 - the eternal tree", "Chapter 16 - divine and demonic qualities",
             "Chapter 17 - three kinds of faith", "Chapter 18 - surrender to Me (18.66)"],
}
MYTH = ("ramayan", "mahabharat", "gita")
MYTH_STYLE = ("majestic, reverent, high quality 2D Indian devotional animation still for all ages, rich traditional "
              "Indian painting colours (gold, saffron, deep blue, red), divine soft golden light, graceful dignified "
              "faces, traditional iconography, cinematic composition, no text, no letters, no watermark")
MYTH_LOOKS = {
    "rama": "Lord Rama: divine young prince with a calm, compassionate face, soft dark-blue (shyam) complexion, long black "
            "hair, tall golden crown (mukut), tilak on the forehead, yellow silk dhoti and saffron-gold angavastram, "
            "gold ornaments, holding a great bow (Kodanda) with a quiver on his back, soft golden halo",
    "sita": "Mother Sita: graceful young princess with a gentle serene face, long black braid with flowers, red-and-gold "
            "silk sari, gold jewellery, red sindoor, soft divine glow",
    "lakshmana": "Lakshmana: loyal young prince, fair complexion, golden crown, saffron dhoti, bow and quiver, alert "
                 "devoted expression",
    "hanuman": "Lord Hanuman: mighty, devoted vanara with a reddish-orange face and body, golden crown, red dhoti, "
               "golden gada (mace) on his shoulder, long tail, eyes full of devotion, folded hands when near Rama",
    "ravana": "Ravana: proud ten-headed king of Lanka, ten golden crowns, dark royal robes with gold, thick moustache, "
              "fierce but not gory",
    "dasharatha": "King Dasharatha: elderly kind king, white beard, golden crown, royal red robes",
    "krishna": "Lord Krishna: divine young man with blue skin, peacock feather in a golden crown, yellow silk dhoti "
               "(pitambar), flower garland (vaijayanti), gentle smile, gold ornaments, soft golden halo",
    "arjuna": "Arjuna: brave warrior prince, fair complexion, golden crown, white-and-gold armour, the Gandiva bow",
    "bhishma": "Bhishma: very old dignified warrior, long white hair and beard, white robes, calm strong eyes",
    "yudhishthira": "Yudhishthira: calm righteous king, short beard, golden crown, white and gold royal robes",
    "bhima": "Bhima: huge strong warrior, broad chest, golden crown, orange dhoti, a big gada (mace)",
    "draupadi": "Draupadi: dignified queen with dark complexion and bright eyes, long open black hair, red and gold sari",
    "karna": "Karna: noble warrior with shining golden armour (kavacha) and golden earrings (kundala), fair face, bow",
    "duryodhana": "Duryodhana: proud prince, thick moustache, dark purple and gold robes, golden crown, mace",
    "kunti": "Mother Kunti: graceful elderly queen, white sari with a thin gold border, kind sad eyes",
}
MYTH_ALIASES = {"ram": "rama", "sri ram": "rama", "shri ram": "rama", "lakshman": "lakshmana", "laxman": "lakshmana",
                "hanuman": "hanuman", "ravan": "ravana", "dasharath": "dasharatha", "dashrath": "dasharatha",
                "arjun": "arjuna", "bhishma": "bhishma", "yudhishthir": "yudhishthira", "bheem": "bhima",
                "bhim": "bhima", "duryodhan": "duryodhana", "sri krishna": "krishna", "shri krishna": "krishna"}
# the weekly routine: the 1 PM story of each day is always this series (Mon=0 ... Sun=6)
DAY_SPECIAL = {0: "gopal", 1: "folk", 2: "birbal", 3: "ramayan", 4: "betal", 5: "mahabharat", 6: "gita"}
SERIES_CATS = ("adventure", "detective", "folk", "para")      # big stories told in 2-3 parts at 7 PM
NEXT_PART = os.path.join(HERE, "next_part.json")

SOUND_TAGS = ["wind", "rain", "thunder", "crickets", "birds", "water", "footsteps", "creak", "knock",
              "boing", "whoosh", "pop", "bell", "splash"]
MOODS = ["happy", "calm", "funny", "adventure", "sad"]
EMOTIONS = ["normal", "happy", "excited", "laughing", "sad", "crying", "scared", "angry", "whisper", "calm", "proud"]

ART_STYLE = ("high quality 2D cartoon animation still for all ages (family animated film), Indian storybook world, bright cheerful colors, "
             "soft lighting, clean outlines, cute expressive characters with big eyes, Pixar-like charm, "
             "no text, no letters, no watermark")


def log(*a):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)
    msg = " ".join(str(x) for x in a)
    if any(k in msg for k in ("skipped", "FAILED", "STOPPED", "failed")):
        extras.note_issue(msg.strip())


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd[:3])}...\n{r.stderr[-2000:]}")
    return r.stdout


def env(name):
    return (os.getenv(name) or "").strip()


def need_env(name):
    v = env(name)
    if not v:
        sys.exit(f"ERROR: secret {name} is missing. Add it in GitHub > Settings > Secrets > Actions.")
    return v


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", path]).strip())


def ascii_text(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\x20-\x7E]", " ", str(s))).strip()


# ----------------------------------------------------------------- history
def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# cron-job.org starts each video about 1 hour before it should be online (India time):
# (start hour, start minute, the hour the video should be out)
TRIGGERS = [(10, 0, 13), (16, 0, 19)]   # two videos a day: start 3 hours early, publish at 1 PM and 7 PM
SLOT = None


def recently_posted(history, hours):
    """True if a video was posted in the last few hours (so a backup run must not post a second one)."""
    for h in history[-3:]:
        if h.get("kind") == "compilation":
            continue
        try:
            t = dt.datetime.fromisoformat(str(h.get("date", "")))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
            if dt.datetime.now(dt.timezone.utc) - t < dt.timedelta(hours=hours):
                return True
        except Exception:
            pass
    return False


def save_history(items):
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(items[-200:], f, ensure_ascii=False, indent=1)


def pick_language(history):
    """One language per page/channel (default Bengali) - a mixed-language channel splits its audience.
    Set the secret CHANNEL_LANG to "hi" for Hindi; "both" brings back one Hindi, one Bengali."""
    forced = env("LANGUAGE").lower()
    if forced in LANGS:
        return forced
    chan = (env("CHANNEL_LANG") or "bn").lower()
    if chan in LANGS:
        return chan
    last = history[-1].get("lang", "hi") if history else "bn"
    return "bn" if last == "hi" else "hi"


DIVINE_FESTIVALS = {"Durga Puja", "Kojagari Lakshmi Puja", "Kali Puja / Diwali", "Saraswati Puja", "Maha Shivaratri",
                    "Sri Ramakrishna's birthday", "Holi / Dol Purnima", "Ram Navami", "Bhoot Chaturdashi"}
MASCOT = os.path.join(HERE, "assets", "lumi_mithu.jpg")
MASCOT_PROMPT = ("Lumi Didi, a warm friendly young Indian storyteller woman in high quality 2D cartoon style, big kind "
                 "sparkling eyes, gentle smile, long black braid with a small yellow flower, sky-blue saree with a "
                 "golden border, small star-shaped bindi, holding an open glowing storybook in one hand and waving "
                 "hello with the other, a small cheeky bright-green parrot with a red beak (Mithu) sitting on her "
                 "shoulder, sitting on a cozy colorful cushion, soft magical sparkles, bright cheerful "
                 "storybook background, Pixar-like charm, no text, no letters, no watermark")


MITHU = {"name": "Mithu", "gender": "male", "age": "child", "kind": "animal", "host": True,
         "look": "a small cheeky bright-green parrot with a red beak and a tiny yellow cap"}


def ensure_mascot():
    """Our host 'Lumi Didi' - made once, saved in the repo, the same in every video."""
    if os.path.exists(MASCOT):
        return MASCOT
    if MOCK:
        os.makedirs(os.path.dirname(MASCOT), exist_ok=True)
        return mock_image(MASCOT, 7) and MASCOT
    try:
        os.makedirs(os.path.dirname(MASCOT), exist_ok=True)
        save_picture(cf_request(CF_MODEL, MASCOT_PROMPT, seed=2024), MASCOT)
        log("Lumi Didi picture created (saved for all future videos)")
        return MASCOT
    except Exception as e:
        log("  Lumi Didi picture not made now:", str(e)[:150])
        return None


def pick_theme(history):
    """Rotate story types so posts in a day are usually different kinds."""
    recent = [h.get("category") for h in history[-2:]]
    options = [c for c in CATEGORIES if c not in recent] or list(CATEGORIES)
    cat = extras.weighted_choice(options, extras.weights(history, "category", options))
    return cat, random.choice(CATEGORIES[cat])


# ----------------------------------------------------------------- 1. story (Gemini)
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def gemini_models(key):
    tries = [env("GEMINI_MODEL")] if env("GEMINI_MODEL") else []
    tries.append("gemini-flash-latest")
    try:
        r = requests.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": key},
                         params={"pageSize": 200}, timeout=30)
        names = []
        for m in r.json().get("models", []):
            n = m.get("name", "").replace("models/", "")
            if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n
                    and not any(x in n for x in ("image", "tts", "audio", "live", "embed", "exp"))):
                names.append(n)

        def ver(n):
            nums = re.findall(r"\d+(?:\.\d+)?", n)
            return (float(nums[0]) if nums else 0, "lite" not in n, "preview" not in n)
        tries += sorted(names, key=ver, reverse=True)
    except Exception as e:
        log("Could not list Gemini models:", e)
    tries += ["gemini-2.5-flash"]
    out = []
    for t in tries:
        if t and t not in out:
            out.append(t)
    return out


# ---- SAHEB: the channel's own hero, in (almost) every story. Never inside the scriptures (Ramayan, Mahabharat,
# divine leelas) - those stay faithful; in the Gita he is the person in the modern-life example.
SAHEB_FACE = ("friendly calm clever Bengali young man about 32, soft oval face with slightly full cheeks, gentle "
              "confident smile, brown eyes behind rectangular black-framed glasses, thick straight black eyebrows, "
              "short thick black hair brushed forward with a soft fringe, clean-shaven (no moustache, no beard), "
              "wheat-brown skin")
SAHEB_CLASSIC = SAHEB_FACE + ", maroon kurta with small gold buttons, cream dhoti, cream shawl with a thin gold " \
                             "border over the left shoulder, small brown cloth shoulder bag, brown nagra shoes"
SAHEB_MODERN = SAHEB_FACE + ", teal half-sleeve shirt, dark-blue jeans, brown belt, black wristwatch, white sneakers"
SAHEB_MODERN_CATS = ("para", "detective", "school", "life", "festival", "adventure", "nature", "bedtime", "gita")
SAHEB_ROLE = {
    "gopal": "Gopal's young friend from the village (NEVER in the royal court): Gopal meets him on the village lane, at "
             "the market or the riverside; they talk the problem over, Saheb asks the questions the viewers would "
             "ask, sometimes shows the way or gives a small hint, and is amazed by Gopal's wit (Gopal stays the hero)",
    "birbal": "a young scholar from Bengal visiting Emperor Akbar's court who becomes Birbal's admiring helper "
              "(Birbal stays the hero)",
    "witty": "a clever young man who helps the hero and sees through the trick",
    "betal": "a brave young traveller inside Betal's tale (or someone Vikram meets on the way)",
    "folk": "a brave, kind young villager who helps the hero or heroine on the journey",
    "fairy": "a kind young man from the village who helps the little hero or heroine",
    "lok": "a curious young traveller from Kolkata who hears or sees this district's tale",
    "funny": "the sensible young man in the middle of the comedy who tries to calm everyone down",
    "para": "the friendly young neighbour Saheb-da whom the whole para trusts",
    "detective": "Jhontu and Mini's friendly elder cousin Saheb-da who helps them get around - but the KIDS solve "
                 "the case, never Saheb",
    "school": "a kind young teacher or a visiting elder brother at the school",
    "life": "a kind young man of the family or the neighbourhood",
    "festival": "a cheerful young man of the family who joins the festival",
    "adventure": "the kids' brave elder cousin who joins the adventure (the kids are still the heroes)",
    "nature": "a young nature lover who helps the children understand",
    "bedtime": "the gentle elder brother who tucks the child in",
    "gita": "the young man in the modern-life example who learns the Gita's lesson",
}
SAHEB_SKIP = ("ramayan", "mahabharat", "divine")


def saheb_rule(category):
    if env("SAHEB") == "0" or category in SAHEB_SKIP:
        return ""
    look = SAHEB_MODERN if category in SAHEB_MODERN_CATS else SAHEB_CLASSIC
    role = SAHEB_ROLE.get(category, "if the story has human characters, he plays a kind, helpful human in it "
                                    "(a traveller, farmer, woodcutter or villager - he never harms animals); if it "
                                    "is only animals, he is the young man who finds them at the end and says the "
                                    "lesson")
    return ("\nOUR OWN HERO: include SAHEB in this story - name \"Saheb\" (in Bengali 'সাহেব', Hindi 'साहेब'), "
            "gender male, age adult, kind human, EXACTLY this look every time: \"" + look + "\". His role: " + role +
            ". Give him 2-5 natural lines; he is warm, curious and funny, never rude. Put him in the characters "
            "list with this exact look.\n")


# ----------------------------------------------------------------- TV-style cartoon with our own characters
# The ready-made characters live in characters/<id>/ (made once, same in every video). A series uses them when
# its characters are there; every scene whose people are all available is acted out like a TV cartoon
# (lip-sync, blinks, poses, walk-ins, camera cuts) on an empty background "set" - otherwise the old way.
PUPPET_SERIES = {"gopal"}
PUPPET_CAST = {   # id -> (name to use in the story, gender, age, look)
    "gopal": ("Gopal", "male", "adult", "round, plump, cheerful Bengali man, clean-shaven round face, big bright eyes, "
              "small black tuft of hair (tiki) on a fully shaved head, a sandalwood tilak line on the forehead, short "
              "leaf-green kurta with a small white collar, white dhoti, maroon-and-white checked gamchha on the left "
              "shoulder, barefoot"),
    "raja": ("Raja", "male", "adult", "tall dignified kind king about 50, neat black moustache with curled tips, "
             "cream-white turban with a red ruby and a white feather plume, royal-blue silk robe with a gold border, "
             "maroon shawl over one shoulder, pearl necklace, gold embroidered shoes"),
    "mantri": ("Mantri", "male", "adult", "tall very thin jealous royal minister, long narrow face, thin pointed "
               "moustache and small pointed beard, grey streaks in his hair, small orange turban, purple robe with a "
               "silver border"),
    "rani": ("Rani", "female", "adult", "kind graceful queen, hair in a neat bun, small gold tiara, sindoor, red "
             "bindi, red Banarasi saree with a gold border, gold jewellery"),
    "gopal_bou": ("Gopal's wife", "female", "adult", "plump cheerful Bengali village wife, hair in a bun, sindoor, red "
                  "bindi, white saree with a red border, red and white bangles, a bunch of keys tucked at the waist"),
    "saheb": ("Saheb", "male", "adult", SAHEB_CLASSIC),
    "paharadar": ("Palace guard", "male", "adult", "tall broad palace guard, big curled black moustache, small red "
                  "turban, brown leather vest over a white kurta, red waist sash, white dhoti, a long spear"),
    "senapati": ("Senapati", "male", "adult", "proud boastful army chief, thick black beard, huge upturned moustache, "
                 "tall saffron turban, silver-grey chest armour over a dark red tunic, a curved sword at the belt"),
    "rajvaidya": ("Rajvaidya", "male", "old", "short round fussy royal physician, neat white beard, small round "
                  "spectacles, small green turban, long teal-green robe, a cloth medicine bag, a brass bowl"),
    "pandit": ("Pandit", "male", "old", "thin proud Brahmin scholar, small round spectacles, shaved head with a small "
               "white tiki, thin white moustache, white dhoti, cream shawl, a palm-leaf manuscript"),
    "mahajan": ("Mahajan", "male", "old", "greedy pot-bellied village moneylender, bald head with grey sides, thin "
                "curled moustache, cream kurta with a brown waistcoat, white dhoti, red account book under his arm"),
    "moyra": ("Moyra", "male", "adult", "cheerful round Bengali sweet-maker, black moustache, white cloth band on a bald "
              "head, white vest, white dhoti, green checked gamchha on the shoulder"),
    "bonik": ("Bonik", "male", "adult", "rich boastful merchant, curled black moustache and short beard, big magenta "
              "turban, long magenta-pink jama with gold embroidery, gold waist sash, gold chain"),
    "zamindar": ("Zamindar", "male", "old", "tall skinny miser landlord, long sour face, thin grey moustache, old grey "
                 "shawl wrapped tightly, patched cream kurta, white dhoti, a big iron key on a string round his neck"),
    "chashi": ("Chashi", "male", "adult", "thin honest village farmer, sun-darkened skin, thin moustache, short brown "
               "kurta, knee-length off-white dhoti, red gamchha tied on his head, barefoot"),
    "gramer_bou": ("Village woman", "female", "adult", "slim kind village woman, hair in a bun, sindoor, small red "
                   "bindi, yellow cotton saree with a green border, brass water pot on her hip, barefoot"),
}
SETS = {   # the same set looks the same in every episode (made once, saved in assets/sets/)
    "court": "the grand royal court hall of an 18th-century Bengali king: carved white-and-gold pillars, red and gold "
             "drapes, brass lamps, a red carpet on a marble floor, a raised EMPTY platform at the back (no throne)",
    "palace_garden": "the royal palace garden: marble path, a fountain, flower beds, mango trees, palace walls behind",
    "gopal_home": "the earthen courtyard of a poor Bengali village mud hut (kancha bari): brown mud walls, a thick "
                  "thatched straw roof, a small low wooden door, a tulsi plant on a little mud platform, clay pots "
                  "and a broom by the wall, a bamboo fence, banana trees behind, soft morning light",
    "village_path": "a Bengali village lane: mud path, banana and coconut trees, thatched mud houses, a pond at the side",
    "market": "a village market street with EMPTY stalls: baskets of vegetables, sacks of rice, cloth awnings",
    "sweet_shop": "the front of an old Bengali sweet shop: wooden counter with big trays of rasgullas and sandesh, "
                  "glass jars, a big brass pan, a cloth awning",
    "riverside": "a river ghat with stone steps, a big banyan tree, a small boat tied at the bank, afternoon light",
    "farm": "green rice fields with a mud path, a haystack, a small hut and palm trees, sunny",
    "rich_house": "inside a rich old Bengali house: a big iron money chest, wooden cupboards, a carpet, arched window",
    "temple": "a village temple courtyard: terracotta temple, a bell, marigold garlands, stone floor",
    "forest": "a forest clearing with big trees, bushes and beams of sunlight",
    "room": "a simple room in a village house: mud walls, a wooden cot at the side, a window, a lantern, a clay pot",
    "night_village": "a Bengali village lane at night: moonlight, a lantern hanging at a hut door, stars",
    "host": "a cheerful storytelling corner in a Bengali village courtyard: a big mango tree, a thatched hut, marigold "
            "flowers in clay pots, soft clouds, bright morning sun",
}
SET_DIR = os.path.join(HERE, "assets", "sets")
SET_VER = {"gopal_home": 2}      # a new number = that set is painted again (once) with its new description
SET_RULE = ("EMPTY place, nobody in the picture: no people, no animals, no throne, no chairs in the middle. "
            "Eye-level wide view, the floor or ground clearly visible in the lower third, open space in front. "
            "Detailed 2D cartoon background painting like an Indian TV cartoon series, bright soft colours, "
            "no text, no letters, no watermark")


def puppet_ready(category=None):
    """the character packs this video can use (empty = the old way)"""
    if puppet is None or env("PUPPET") == "0":
        return set()
    av = puppet.available()
    if category is not None and (category not in PUPPET_SERIES or "gopal" not in av):
        return set()
    return av


def puppet_rules(category):
    av = puppet_ready(category)
    if not av:
        return ""
    people = [{"name": n, "gender": g, "age": a, "kind": "human", "look": lk, "rig": cid}
              for cid, (n, g, a, lk) in PUPPET_CAST.items() if cid in av]
    return ("\nANIMATED CAST (very important - this story is animated with our ready-made cartoon characters): use "
            "ONLY characters from this list, with EXACTLY these names, genders, ages and looks, and copy the key "
            "\"rig\" into each of them in the characters list: " + json.dumps(people, ensure_ascii=False) +
            ". Nobody else may appear or speak (no crowds, no children, no animals on screen - they may only be "
            "talked about). Up to 5 of them in one scene. Every scene gets the key \"set\": the place where it "
            "happens, one of " + json.dumps([k for k in SETS if k != "host"]) + ".\n"
            "WRITE IT LIKE AN EPISODE OF THE GOPAL BHAR TV CARTOON SERIES (a real film script, not a summary):\n"
            "- NO NARRATOR inside the story: Lumi Didi introduces it before and says the lesson after (added "
            "automatically). Every line is spoken by a character; what happens is shown through what they say and "
            "do. 10-14 scenes, 6-12 short lines each, quick back-and-forth dialogue full of emotion, comic timing, "
            "expressions and reactions.\n"
            "- The places change like a TV episode: the royal court ('court'), Gopal's poor mud hut with his wife "
            "('gopal_home'), village lanes ('village_path'), the market, the sweet shop, the riverside... Gopal "
            "walks between places: a short scene of him walking home on the village lane, talking (to himself, or "
            "with Saheb who joins him).\n"
            "- THE COURT is full and alive: the Raja sits on his throne; courtiers sit at the sides and a guard "
            "stands (they are drawn automatically). The Raja ASKS FOR OPINIONS: Mantri, Senapati, Pandit and "
            "Rajvaidya each give their own (proud, wrong or funny) opinion in their own style, they argue a little, "
            "the Mantri schemes against Gopal - then Gopal's clever answer wins and the Raja laughs and rewards him.\n"
            "- SAHEB is NEVER in the royal court: he is Gopal's friend in the village. Gopal meets him standing on "
            "the village lane (or the market / riverside); they talk the problem over, Saheb asks the questions the "
            "viewers would ask, sometimes he shows the way or gives a small hint - Gopal always finds the answer.\n"
            "- Gopal's wife at home: real, funny husband-and-wife talk (she scolds, worries, laughs).\n"
            "- In EVERY line: \"to\" = the name of the character the speaker talks to (the speaker turns to them, "
            "they look back); and image.people lists EVERY character who is in that scene with their REACTION to "
            "this line in 'feeling'/'doing' (listening, nodding, laughing, shocked, angry, worried, scheming, "
            "thinking, embarrassed...). Nobody vanishes: a character stays in the scene until you write 'walks "
            "out'; somebody arriving 'walks in'.\n"
            "- Acting words the animation understands: standing / sitting (only the Raja on his throne and the Rani) "
            "/ walks in / walks out, and talking, laughing, angry, sad, surprised, worried, thinking, idea (one finger "
            "raised), namaste, bowing, pointing, scheming (Mantri), embarrassed, blessing (Raja), salute (guard), "
            "scolding (Gopal's wife).\n")


def get_set(key, place, seed):
    """the background picture for a scene: a fixed set (made once and kept) or this story's own place"""
    key = re.sub(r"[^a-z_]", "", str(key or "").lower())
    if key in SETS:
        path, desc, sd = os.path.join(SET_DIR, f"{key}_{SET_VER.get(key, 1)}.jpg"), SETS[key], \
            7000 + sorted(SETS).index(key) + 100 * SET_VER.get(key, 1)
        if os.path.exists(path):
            return path
    else:
        path, desc, sd = os.path.join(WORK, f"set_{abs(hash(place)) % 10 ** 8}.jpg"), ascii_text(place), seed
        if os.path.exists(path):
            return path
        if not desc.strip():
            return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if MOCK:
        test = os.path.join(env("MOCK_SETS") or "-", f"{key}.png")
        if os.path.exists(test):
            fit(Image.open(test), 1920, 1080).save(path, quality=93)
            return path
        return path if mock_image(path, sd) else None
    for model, size in ((CF_MODEL, (1536, 864)), (CF_MODEL, (PIC_W, PIC_H)), (CF_BACKUP, (PIC_W, PIC_H))):
        try:
            data = cf_request(model, f"{desc}. {SET_RULE}. Style: {ART_STYLE}", w=size[0], h=size[1], seed=sd)
            with open(path + ".raw", "wb") as f:
                f.write(data)
            fit(Image.open(path + ".raw"), 1920, 1080).save(path, quality=93)
            os.remove(path + ".raw")
            log(f"  background set '{key or place[:40]}' made" + (" (kept for all future videos)" if key in SETS else ""))
            return path
        except Exception as e:
            log(f"  set picture attempt failed ({model.split('/')[-1]} {size[0]}x{size[1]}): {str(e)[:150]}")
    return None


class RigMap:
    """story character names -> character packs"""

    def __init__(self, story, av):
        self.av, self.m = av, {}
        for c in story.get("characters", []):
            rid = re.sub(r"[^a-z_0-9]", "", str(c.get("rig") or "").lower())
            if rid not in av:
                rid = puppet.rig_for(c.get("name", ""), c.get("look", ""), av)
            if rid and c.get("name"):
                self.m[ascii_text(c["name"]).lower().strip()] = rid

    def __call__(self, name):
        k = ascii_text(str(name or "")).lower().strip()
        if not k or k.startswith("narrat"):
            return None
        if k in self.m:
            return self.m[k]
        for kk, v in self.m.items():
            if kk and (kk in k or k in kk):
                return v
        return puppet.rig_for(k, "", self.av)


def puppet_scene(s, rig):
    """which characters stand where in this scene - or None if somebody in it has no ready-made character"""
    names, where = [], {}
    for n in s.get("characters") or []:
        names.append(n)
    for ln in s.get("lines") or []:
        sp = str(ln.get("speaker", ""))
        if sp and not sp.lower().startswith("narrat"):
            names.append(sp)
        pic = ln.get("image") if isinstance(ln.get("image"), dict) else {}
        for x in pic.get("people") or []:
            if isinstance(x, dict) and x.get("name"):
                names.append(x["name"])
                w = str(x.get("where", "")).lower()
                pos = 0 if "left" in w else 2 if "right" in w else 1
                where.setdefault(str(x["name"]), []).append(pos)
    order = []
    for n in names:
        r = rig(n)
        if not r:
            return None
        if r not in order:
            order.append(r)
    if not order or len(order) > 5:
        return None
    score = {}
    for n, ps in where.items():
        r = rig(n)
        if r:
            score.setdefault(r, []).extend(ps)
    first = {r: k for k, r in enumerate(order)}
    order.sort(key=lambda r: (sum(score.get(r, [1])) / len(score.get(r, [1])), first[r]))
    return {"cast": order, "set": s.get("set"), "place": s.get("place", "")}


def puppet_lines(sp, pz):
    """the spoken lines of a part, in the renderer's words"""
    rig = pz.get("rig")
    out = []
    for ln in sp["lines"]:
        if not str(ln.get("text", "")).strip():
            continue
        name = str(ln.get("speaker", "narrator"))
        if pz.get("host"):
            who = "mithu" if name.lower().startswith("mithu") else "lumi_didi"
        else:
            who = rig(name) if rig else None
        pic = ln.get("image") if isinstance(ln.get("image"), dict) else {}
        people = {}
        for x in pic.get("people") or []:
            if isinstance(x, dict) and x.get("name") and rig:
                r = rig(x["name"])
                if r:
                    people[r] = f"{x.get('pose', '')}. {x.get('doing', '')} || {x.get('feeling', '')}"
        to = rig(ln.get("to")) if rig and ln.get("to") else None
        out.append({"speaker": who, "to": to, "emotion": ln.get("emotion", ""), "people": people})
    return out


def host_puppet(fly_in):
    av = puppet_ready()
    if env("PUPPET_HOST") == "0" or not {"lumi_didi", "mithu"} <= av:
        return None
    bg = get_set("host", "", 0)
    return {"host": {"fly_in": fly_in}, "bg": bg, "place": "village courtyard"} if bg else None


def make_story(lang, theme, history, extra_rules="", part=0, prev=None, total=2):
    if MOCK:
        return mock_story(lang)
    key = need_env("GEMINI_API_KEY")
    category, idea = theme
    L = LANGS[lang]
    old_titles = [h["title"] for h in history[-60:] if h.get("lang", "hi") == lang]
    kind_rules = {
        "folk": "This is a classic Indian/Bengali fairy tale in the style of Thakurmar Jhuli (grandmother's tales): "
                "kings, princes, princesses, rakkhosh/demons, magic birds, flying horses, a village and a palace. "
                "Retell the public-domain folk tale idea in your OWN words with new dialogue, vivid scenes and a "
                "small fresh twist. Keep the magic gentle and child friendly (the demon is defeated by cleverness, "
                "not violence).",
        "panchatantra": "This is a Panchatantra / Jataka / Hitopadesha fable (ancient, public domain). Retell it in "
                        "your OWN words with lively new dialogue, fun character voices and a fresh small twist, "
                        "keeping the classic lesson.",
        "divine": "This is a devotional story (leela) of the gods and their devotees from the Puranas and bhakti "
                  "tradition. Tell it faithfully and with deep respect and devotion - do NOT change the meaning of "
                  "the traditional story or add silly jokes about the gods. Warm, loving, child friendly; show the "
                  "god's love for the devotee and end with the devotional lesson (faith, love, humility, kindness). "
                  "If the original has fights or demons, tell those parts gently, without violence or fear. "
                  "In every picture and character 'look', show the gods in their traditional, beautiful, auspicious "
                  "form (e.g. Krishna: blue skin, peacock feather, yellow dhoti, flute; Shiva: calm, blue throat, "
                  "crescent moon, Ganga in his hair; Ma Kali: gentle loving mother form, no weapons, no heads; "
                  "Jagannath: the traditional big round eyes and dark face) with a soft divine golden glow.",
        "gopal": "This is a Gopal Bhar story: the witty, kind-hearted jester at the 18th-century court of Raja "
                 "Krishnachandra of Krishnanagar, Bengal (a centuries-old folk character - retell the anecdote idea "
                 "in your OWN words with new dialogue and a fresh twist). Clean, clever, laugh-out-loud humour; "
                 "Gopal wins with wit, never by being mean; the poor and the honest are never mocked; the king "
                 "laughs and rewards him in the end. Use EXACTLY these two characters (same names and looks every "
                 "time) plus 1-2 others if needed: {\"name\": \"Gopal\", \"gender\": \"male\", \"age\": \"adult\", "
                 "\"kind\": \"human\", \"look\": \"round, plump, cheerful Bengali man, clean-shaven round face, big "
                 "bright eyes, small black tuft of hair (tiki) on a fully shaved head, a sandalwood tilak line on the "
                 "forehead, short leaf-green kurta with a small white collar, white dhoti, maroon-and-white checked "
                 "gamchha on the left shoulder, barefoot\"} and {\"name\": \"Raja\", \"gender\": \"male\", "
                 "\"age\": \"adult\", \"kind\": \"human\", \"look\": \"tall dignified kind king about 50, neat black moustache with curled tips, cream-white turban with a red ruby and a "
                 "white feather plume, royal-blue silk robe with a gold border, maroon shawl over one shoulder, pearl "
                 "necklace, gold embroidered shoes\"}. "
                 "If the story needs them, use EXACTLY these looks too: {\"name\": \"Mantri\", \"gender\": \"male\", "
                 "\"age\": \"adult\", \"kind\": \"human\", \"look\": \"tall very thin jealous royal minister, long "
                 "narrow face, thin pointed moustache and small pointed beard, grey streaks in his hair, small "
                 "orange turban, purple robe with a silver border\"}, {\"name\": \"Rani\", \"gender\": \"female\", "
                 "\"age\": \"adult\", \"kind\": \"human\", \"look\": \"kind graceful queen, hair in a neat bun, "
                 "small gold tiara, sindoor, red bindi, red Banarasi saree with a gold border, gold jewellery\"}, "
                 "{\"name\": \"Gopal's wife\", \"gender\": \"female\", \"age\": \"adult\", \"kind\": \"human\", "
                 "\"look\": \"plump cheerful Bengali village wife, hair in a bun, sindoor, red bindi, white saree "
                 "with a red border, red and white bangles, a bunch of keys tucked at the waist\"}. "
                 "Not the TV cartoon design - our own look as described. Gopal walks into the court or the village "
                 "2-3 times (write 'walks in' for him in that line's people).",
        "life": "This is a heart-touching everyday story about real people (children, parents, grandparents, "
                "teachers, neighbours) in an Indian town or village. Realistic situations families relate to. "
                "It must teach a clear life lesson and touch the heart so deeply that grown-ups feel a lump in "
                "the throat and want to share it.",
        "birbal": "This is an Akbar-Birbal story (centuries-old folk anecdote, public domain) - retell it in your OWN "
                  "words with new dialogue and a fresh twist. Clean, clever humour for all ages; Birbal wins with "
                  "wit, the emperor laughs and rewards him. Use EXACTLY these looks: {\"name\": \"Birbal\", "
                  "\"gender\": \"male\", \"age\": \"adult\", \"kind\": \"human\", \"look\": \"slim witty "
                  "Mughal-court minister, neat short black beard, sharp smiling eyes, white turban with a small red "
                  "plume, long cream jama with gold buttons, red sash\"} and {\"name\": \"Akbar\", \"gender\": "
                  "\"male\", \"age\": \"adult\", \"kind\": \"human\", \"look\": \"grand Mughal emperor, full "
                  "black moustache, jewelled golden turban with a feather, rich green and gold royal robe, pearl "
                  "necklaces\"}.",
        "betal": "This is a Vikram-Betal tale (Baital Pachisi, ancient, public domain), retold in your OWN words. "
                 "Frame: brave King Vikramaditya carries the ghost Betal on his shoulder through a dark cremation "
                 "forest; Betal tells a story and at the end asks a clever riddle. Betal is spooky-funny, not "
                 "frightening. Do NOT give the king's answer: Betal asks the VIEWERS to comment the answer, and "
                 "says the answer will come next time. Looks: King Vikram - tall brave king, short black beard, "
                 "golden crown, red royal robe, sword at the waist; Betal - a pale, thin, mischievous ghost with "
                 "long white hair, glowing eyes, hanging upside down or sitting on Vikram's shoulder.",
        "jataka": "This is a Jataka tale (ancient Buddhist fable, public domain), retold in your OWN words with lively "
                  "dialogue; the wise animal or person shows compassion and courage; a clear lesson for all ages.",
        "para": "This is our own Bengali para (neighbourhood) comedy - original characters, warm family humour for "
                "all ages, everyday Kolkata/town life. Recurring characters (use the ones who fit, same looks every "
                "time): Bhombol-da (plump cheerful young man, curly hair, red t-shirt and lungi), Dadu (thin old "
                "grandfather, round glasses, white dhoti-kurta, walking stick), Mashima (plump kind aunt, red-bordered "
                "white sari, big bindi), Kaku (bald middle-aged uncle, moustache, checked shirt, always on his phone). "
                "Gentle comedy of misunderstandings, never mocking anyone's body, religion or caste.",
        "detective": "This is a case of our own young detective duo JHONTU (sharp 12-year-old boy, messy hair, round "
                     "glasses, blue striped t-shirt, magnifying glass) and MINI (brave 11-year-old girl, two plaits, "
                     "yellow frock, notebook and pencil). A small clever mystery in a Bengal town: real clues shown "
                     "early, two suspects, a fair twist; viewers can guess. Nobody is hurt; the culprit is forgiven.",
        "lok": "This is a folk tale from the districts of Bengal (public domain), retold in your OWN words with local "
               "colour - the place, the crafts, the songs, the food of that district.",
        "rhyme": "Tell this story in rhyming {lang} verse (ছড়া style, like old Bengali rhymes): every line rhymes "
                 "with the next, a bouncy rhythm, funny and sweet, easy to sing along. Dialogue lines also rhyme.",
        "ramayan": "This is an episode of the RAMAYANA, told IN ORDER as a weekly series. Follow the Valmiki Ramayana "
                   "and Krittivas Ojha's Bengali Ramayana faithfully - do NOT invent events, do NOT change who did what, "
                   "keep every name and relationship correct. Lord Rama, Mother Sita and Lord Hanuman are shown with "
                   "deep devotion, dignity and glory (bhakti) - never as jokes, never silly, never cute caricatures. "
                   "Battles are shown with grandeur but no blood or gore. Make it gripping and emotional like a great "
                   "film; end with the spiritual lesson of this episode and one line that makes viewers wait for next "
                   "week's episode.",
        "mahabharat": "This is an episode of the MAHABHARATA, told IN ORDER as a weekly series. Follow Vyasa's Mahabharata "
                      "and Kashiram Das's Bengali Mahabharata faithfully - do NOT invent events, do NOT change who did "
                      "what, keep every name and relationship correct. Lord Krishna is shown with deep devotion, dignity "
                      "and divine glory - never as a joke. Battles have grandeur but no blood or gore. Gripping, "
                      "emotional, with the dharma lesson of this episode, ending with a line that makes viewers wait "
                      "for next week.",
        "gita": "This is an episode of GITA GYAN - one chapter of the Srimad Bhagavad Gita, in order. Frame: on the "
                "chariot at Kurukshetra, Lord Krishna (the charioteer) teaches Arjuna. Explain the chapter's main "
                "teaching faithfully and simply; quote ONLY a famous verse you are certain of (Sanskrit, with its "
                "chapter and verse number) and explain its meaning in simple {lang}; never invent verses. Then show "
                "the same teaching in a short, touching modern Bengali family example (a student before an exam, a "
                "father who lost his job...). Deep reverence for Lord Krishna; uplifting and practical for all ages.",
    }.get(category, "Do NOT retell famous copyrighted stories or use known cartoon characters. Invent new names.")
    kind_rules = kind_rules.replace("{lang}", L["name"])
    if part == 1:
        kind_rules += ("\nSERIES: this is PART 1 of a bigger story told in parts on following days. Introduce the "
                       "people and the world, build curiosity and STOP at an exciting cliffhanger (unresolved). Add "
                       "JSON keys: \"total_parts\": 2 or 3 (3 only if the plot is truly big), \"summary\" (ENGLISH, "
                       "5-8 sentences: everything that happened so far) and \"part2_plan\" (ENGLISH, 4-6 sentences: how "
                       "the next part continues).\n")
    elif part >= 2 and prev:
        kind_rules += (f"\nSERIES: this is PART {part} of {total}. Title of part 1: {prev.get('title')}. What happened so far: "
                       f"{prev.get('summary')} Planned continuation: {prev.get('part2_plan')} Use EXACTLY these characters "
                       f"(same names, same looks): {json.dumps(prev.get('characters'), ensure_ascii=False)} and this "
                       f"setting: {prev.get('setting')}. Begin with a short recap by the narrator (2-3 lines). ")
        kind_rules += ("This is a MIDDLE part: a new surprise, and STOP again at a bigger cliffhanger. Add JSON keys "
                       "\"summary\" (ENGLISH, everything so far) and \"part2_plan\" (ENGLISH, how the next part goes).\n"
                       if part < total else "This is the FINAL part: a satisfying, surprising ending that answers "
                       "everything.\n")
    if category in MYTH:
        kind_rules += (" Use these EXACT looks for the holy and epic characters who appear (same every time): "
                       + "; ".join(MYTH_LOOKS.values()) + ". Use 'Rama', 'Sita', 'Krishna', 'Arjuna' etc. as names.")
    kind_rules += saheb_rule(category)
    kind_rules += puppet_rules(category)
    prompt = f"""
You are India's best {L['name']} storyteller for a family cartoon story page that people of ALL AGES watch -
children, teenagers, parents and grandparents.
Write ONE {L['name']} story ({L['script']} script, natural everyday {L['name']} that the whole family
understands). Type: {category} story. Theme: {idea}.
{kind_rules}{extra_rules}
Never use modern copyrighted characters (no Disney, Chhota Bheem, Motu Patlu etc.).
Must be different from these earlier stories: {json.dumps(old_titles, ensure_ascii=False)}
Our channel host is "Lumi Didi", a warm storyteller; the narrator speaks like her (friendly, to the whole family).

Story rules:
- LENGTH: 14 to 18 scenes, 5-6 minutes when spoken - at least 750 spoken words in total. Never rush the
  ending; the story must feel complete. The FIRST line must hook in 5 seconds (a surprise, a question
  or a funny moment). Then a problem, rising curiosity, a twist, and a happy, funny or touching ending.
- Make it emotional and memorable so families want to share it: smart humour grown-ups also laugh at, a warm
  heart, real feelings, a clear lesson.
- Clean family entertainment for all ages: no vulgarity, no graphic violence, nothing that frightens small children.
- 2 to 4 characters (people or animals) plus a narrator, with real, lively dialogue between characters.
- Each scene has 4 to 7 lines. The narrator describes; characters speak only their own words.
  Narrator lines 20-45 words, dialogue lines 4-20 words.
- SMOOTH, COMPLETE STORYTELLING: every scene follows from the one before; when time or place changes the narrator
  says so; every character is introduced before acting; nothing is skipped or jumped over; every question is
  answered (unless it is deliberately left for the next part).
- Think like a cartoon film director: every line gets its own PICTURE that shows exactly what that line says
  (who, doing what, where). The picture must match the words - if the line says the crow drops a stone in the
  pot, the picture shows the crow dropping a stone in the pot.
  When a character arrives somewhere, say it in that line's picture prompt, e.g. "Gopal walks in from the left"
  (the video then shows them walking in). Do this 2-4 times in the story, at natural moments.
- PICTURES MUST BE AUTHENTIC AND LOGICAL, frame by frame, like a real film storyboard. For every line imagine the
  exact frame: who is in it (count them), where each one is, the BODY POSITION of each (lying / sitting /
  standing / kneeling / walking / running / bending), what their HANDS are doing, where they LOOK, and the
  FEELING on each face. Follow real life: a mother putting her child to sleep = the child LIES in bed under a
  blanket with eyes closed, the mother SITS on the edge of the bed beside him, gently patting his head with a
  loving smile, a small lamp glowing. Never add people who are not in the line, never show the same character
  twice, a child never holds another child unless the story says so, sizes and ages stay true (a child is small,
  an adult is tall), animals look like the real animal. Day/night and the place must match the story.
- SOUND DESIGN like a children's audio drama: when a line mentions an action or a thing that makes a sound
  (door, footsteps, birds, splash, laughing, a bell, wind, an elephant trumpeting, a cuckoo, clapping),
  put that real sound in the line's "sfx" with the right timing. 0-2 sfx per line, only real story events.
- Give every line an emotion so the voice acts it.
{extras.STORY_CRAFT}{extras.HOOK_RULES}{extras.WRITING_RULES.get(lang, "")}{extras.VOICE_ACTING}
Return ONLY JSON with exactly these keys:
{{
 "title": "catchy {L['name']} title (max 60 characters) with 1 emoji",
 "thumbnail_text": "2-4 BIG {L['name']} words that make people curious to click - a surprising question, a funny shock or a promise (e.g. 'লোভের শাস্তি?', 'বোকা সিংহ!', 'শেষে কী হল?') - never just the title",
 "description": "3-4 line engaging {L['name']} description, ending with a question to the viewer",
 "hashtags": ["10 to 14 popular hashtags mixing {L['name']} and English, e.g. {L['example_tags']}"],
 "setting": "ENGLISH: the ONE main place of the story (landscape, buildings, plants, colors, time of day). Reused in every picture",
 "characters": [{{"name": "name in English letters", "gender": "male or female",
                  "age": "child, young, adult or old", "kind": "human or animal",
                  "look": "ENGLISH, very specific never-changing look: species/age, body size, exact colors of fur/skin/hair, clothes with exact colors, one special accessory. 20-35 words"}}],
 "source": "ENGLISH: e.g. 'Inspired by Panchatantra' / 'Inspired by Thakurmar Jhuli' / 'From the Bhagavata Purana' / 'Original story'",
 "episode_name": "2-3 word {L['name']} episode name for the thumbnail, catchy and exact (e.g. 'রাজার ধাঁধা', 'নদীর গান', 'লোভী শেয়াল')",
 "thumbnail_image": {{"hero": "the main character's name (big in the foreground, right side)", "hero_action": "ENGLISH: the hero's pose, hand gesture and very expressive face at the story's most exciting moment, e.g. 'raising one finger with a clever smile as he answers the riddle'", "second": "the second most important character's name (or '' if none)", "second_action": "ENGLISH: how the second character reacts in the middle ground, e.g. 'the king sits on his ornate throne, astonished, hand on chin'", "place": "ENGLISH: the exact place with rich authentic details and light", "moment": "ENGLISH: one sentence - the visual story of the thumbnail (what just happened)"}},
 "scenes": [{{
    "characters": ["names VISIBLE in the picture"],
    "action": "ENGLISH: what happens in this scene",
    "place": "ENGLISH: where in the setting + light",
    "mood": "one of {MOODS}",
    "ambience": ["1-2 ENGLISH background sounds that fit this place, e.g. 'birds chirping in forest', 'village morning roosters', 'river stream', 'gentle wind in trees', 'busy village market'"],
    "lines": [{{"speaker": "narrator or a character name", "text": "{L['name']} text",
                "en": "the same line translated to natural English (for subtitles)",
                "emotion": "one of {EMOTIONS}",
                "delivery": "ENGLISH acting direction for the voice (pitch, speed, loudness, feeling)",
                "voice_text": "same words as text, with 0-2 sound tags like <giggle> or <gasp> where they fit",
                "sfx": [{{"sound": "ENGLISH short name of what HAPPENS in this line, e.g. 'wooden door opens', 'small footsteps running on grass', 'water splash', 'children laughing', 'elephant trumpet', 'crow cawing', 'clapping'",
                          "when": "before (sound first, then the line), during, or after (line first, then the sound)"}}],
                "image": {{"prompt": "ENGLISH storyboard frame for THIS line, 35-60 words, like a cartoon film still: the exact moment of this line - who does what to whom, WHERE (which part of the setting, objects around), camera (close-up / medium / wide / over-the-shoulder / top view), time of day and light, the mood. Only things that can be SEEN",
                           "people": [{{"name": "a character name exactly as in characters", "pose": "lying / sitting / standing / kneeling / walking / running / bending / sleeping ...", "doing": "exactly what the body and HANDS do, e.g. 'gently patting the boy's head with her right hand'", "where": "left / middle / right of the frame, and on what (on the bed, on the boat, under the tree)", "feeling": "facial expression and emotion, e.g. 'loving tired smile', 'eyes closed, peaceful'"}}],
                           "characters": ["names VISIBLE in this picture, in order from LEFT to RIGHT as they stand; [] if only a place or object is shown"]}}}}]
 }}],
 "moral": "one short {L['name']} line: the lesson (or the punchline for funny stories)",
 "ending_line": "one short sweet {L['name']} closing line from the narrator",
 "comment_question": "one short friendly {L['name']} question to viewers that makes them comment (e.g. 'तुम होते तो क्या करते?'), with 1 emoji",
 "teaser_scene": "number: the scene (1 = first) where the most fun/exciting 50 seconds START - used for the Reel/Short teaser",
 "mithu_intro": "Mithu the cheeky parrot (Lumi Didi's friend) says ONE short funny {L['name']} line at the start, about today's story (max 15 words)",
 "mithu_outro": "Mithu's ONE short funny {L['name']} goodbye line (max 15 words)",
 "english_words": [{{"en": "3 simple English words from this story (e.g. Crow, Water, Stone)", "meaning": "meaning in {L['name']}"}}],
 "riddle": {{"q": "one short fun {L['name']} riddle (dhadha) for the whole family, NOT about this story, max 25 words", "a": "its short answer"}},
 "quiz": {{"question": "one easy {L['name']} question for viewers about THIS story (max 12 words)",
           "options": ["3 short {L['name']} answers (2-4 words each), only one correct"], "answer": "0, 1 or 2: index of the correct option"}}
}}
Every scene object also has "chapter": "2-4 word {L['name']} chapter name for YouTube chapters".
"""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json",
                                 "maxOutputTokens": 60000}}
    last_err = None
    best, min_words = None, int(env("MIN_WORDS") or 650)       # ~650+ spoken words = 5+ minutes
    models = gemini_models(key)
    waits = [0, 90, 180, 300, 300, 420]           # Google's servers are sometimes busy for a while: be patient
    for round_no, wait in enumerate(waits):
        if wait and round_no <= 2:                # Gemini busy: try the backup writer before waiting
            try:
                text = extras.freemodel_text(body["contents"][0]["parts"][0]["text"])
                if text:
                    story = extras.load_json_loose(text)
                    assert story.get("title") and len(story.get("scenes", [])) >= 6
                    assert all(s.get("lines") for s in story["scenes"])
                    words = sum(len(str(ln.get("text", "")).split()) for sc in story["scenes"] for ln in sc["lines"])
                    log(f"  backup story: {len(story['scenes'])} scenes, {words} spoken words")
                    if words >= min_words * 0.8:
                        return story
                    if not best or words > best[0]:
                        best = (words, story)
            except Exception as e:
                log("  backup writer failed:", (str(e) or type(e).__name__)[:150])
        if wait:
            log(f"All Gemini models busy - waiting {wait} s (round {round_no + 1}/{len(waits)})")
            time.sleep(wait)
        for model in list(models):
            try:
                log(f"Writing story with {model} ...")
                r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent",
                                  headers={"x-goog-api-key": key}, json=body, timeout=300)
                if r.status_code in (404, 400):
                    raise LookupError(r.text[:300])
                if r.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"busy ({r.status_code})")
                r.raise_for_status()
                cand = r.json()["candidates"][0]
                text = cand["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
                story = extras.load_json_loose(text)     # small JSON mistakes are repaired, not thrown away
                assert story.get("title") and len(story.get("scenes", [])) >= 6
                assert all(s.get("lines") for s in story["scenes"])
                words = sum(len(str(ln.get("text", "")).split()) for sc in story["scenes"] for ln in sc["lines"])
                log(f"  story: {len(story['scenes'])} scenes, {words} spoken words")
                if not best or words > best[0]:
                    best = (words, story)
                if words < min_words:
                    body["contents"][0]["parts"][0]["text"] = prompt + (
                        f"\n\nIMPORTANT: your last story had only {words} spoken words - far too short. "
                        f"Write at least {min_words + 150} spoken words: more scenes and more lines per scene.")
                    raise ValueError("story too short - asking for a longer one")
                return story
            except LookupError as e:
                last_err = e
                models.remove(model)
            except Exception as e:
                last_err = e
                log("  trying next model:", (str(e) or type(e).__name__)[:200])
                time.sleep(5)
    if best:
        log(f"  using the longest story written ({best[0]} words)")
        return best[1]
    raise RuntimeError(f"Gemini failed: {last_err}")


# ----------------------------------------------------------------- 2. pictures (Cloudflare)
CF_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
CF_BACKUP = "@cf/black-forest-labs/flux-1-schnell"


def fit(img, w=W, h=H):
    """Whole picture in a w x h frame, nothing cut; empty sides filled with a dark blurred copy."""
    img = img.convert("RGB")
    if abs(img.width / img.height - w / h) < 0.03:
        return img.resize((w, h), Image.LANCZOS)
    s = max(w / img.width, h / img.height)
    bg = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    l, t = (bg.width - w) // 2, (bg.height - h) // 2
    bg = bg.crop((l, t, l + w, t + h)).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (w, h), (0, 0, 0)), 0.45)
    s = min(w / img.width, h / img.height)
    fg = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return bg


class Cast:
    def __init__(self, story):
        self.setting = ascii_text(story.get("setting", ""))
        self.chars = {}        # key -> dict(name, look, gender, age, kind)
        for c in story.get("characters", []) or []:
            if isinstance(c, dict) and c.get("name"):
                k = ascii_text(c["name"]).lower()
                self.chars[k] = {"name": ascii_text(c["name"]), "look": ascii_text(c.get("look", "")),
                                 "gender": str(c.get("gender", "male")).lower(),
                                 "age": str(c.get("age", "adult")).lower(),
                                 "kind": str(c.get("kind", "human")).lower()}
        self.ref = None

    def find(self, name):
        k = ascii_text(name).lower()
        if not k:
            return None
        return self.chars.get(k) or next((v for kk, v in self.chars.items() if k in kk or kk in k), None)

    def pick(self, names):
        out = []
        for n in names or []:
            c = self.find(n)
            if c and c not in out:
                out.append(c)
        return out or list(self.chars.values())

    def describe(self, chosen):
        return " ".join(f"{c['name']}: {c['look']}." for c in chosen)

    def scene_prompt(self, action, place, names, use_ref):
        """Picture prompt. The exact moment of the story comes FIRST (the picture model follows the start
        of the prompt most), then who is in it, then the place, then the art style."""
        low = ascii_text(action).lower()
        empty = isinstance(names, list) and not names           # [] = a shot with nobody in it
        names = list(names or []) + [c["name"] for c in self.chars.values() if c["name"].lower() in low]
        chosen = []
        for n in names:
            c = self.find(n)
            if c and c not in chosen:
                chosen.append(c)
        if not chosen and not empty:
            chosen = [c for c in self.chars.values() if not c.get("host")]
        who = (f"Characters in the picture (ONLY these, each exactly as described): {self.describe(chosen)} "
               if chosen else "No people in this picture, only the place and the objects described. ")
        if len(chosen) >= 2:                  # fixed positions so the video knows whose mouth to move
            spots = ["on the LEFT", "in the MIDDLE", "on the RIGHT"] if len(chosen) == 3 else ["on the LEFT", "on the RIGHT"]
            who += ("Places in the frame, a little apart, each keeping the pose described above, faces visible: " +
                    ", ".join(f"{c['name']} {spots[min(k, len(spots) - 1)]}" for k, c in enumerate(chosen[:3])) + ". ")
        p = (f"{ascii_text(action)}. {who}"
             f"Location: {ascii_text(place)}. {self.setting}. Style: {ART_STYLE}.")
        if use_ref and chosen:
            p = ("Use image 0 ONLY for how the characters look (same faces, hair, body, clothes). Do NOT copy their "
                 "poses or positions from image 0. Draw this NEW scene with a full background, each character in the "
                 "exact pose and action written here: " + p)
        return p


CF_QUOTA_OUT = False
PIC_W, PIC_H = 1024, 576        # 16:9; scaled up to 1280x720 for the video


def cf_accounts():
    """All Cloudflare accounts given: CF_ACCOUNT_ID/CF_API_TOKEN, then ..._2, ..._3 (each has its own free limit)."""
    out = []
    for suf in ("", "_2", "_3", "_4"):
        a, t = env("CF_ACCOUNT_ID" + suf), env("CF_API_TOKEN" + suf)
        if a and t:
            out.append((a, t))
    if not out:
        need_env("CF_ACCOUNT_ID")
    return out


CF_ACTIVE = 0


AGNES_SAID = False


def cf_request(model, prompt, ref_path=None, w=PIC_W, h=PIC_H, seed=None):
    """A picture: Cloudflare first (account 1, then 2); when their free daily limit is used up,
    the free Agnes AI pictures (if AGNES_API_KEY is set)."""
    global AGNES_SAID
    if not CF_QUOTA_OUT:
        try:
            return _cf_request_all(model, prompt, ref_path, w, h, seed)
        except RuntimeError:
            if not CF_QUOTA_OUT:
                raise
    if extras.agnes_ok():
        if not AGNES_SAID:
            log("  Cloudflare limit used up - making the rest of the pictures with Agnes AI")
            AGNES_SAID = True
        if "exact pose and action written here: " in prompt:          # no reference picture on Agnes
            prompt = prompt.split("exact pose and action written here: ", 1)[1]
        return extras.agnes_image(prompt)
    raise RuntimeError("all Cloudflare accounts used up their daily free allocation (4006)")


def _cf_request_all(model, prompt, ref_path=None, w=PIC_W, h=PIC_H, seed=None):
    """Ask Cloudflare for a picture. When one account's free daily limit is used up,
    move on to the next account automatically."""
    global CF_ACTIVE, CF_QUOTA_OUT
    accounts = cf_accounts()
    while CF_ACTIVE < len(accounts):
        try:
            return _cf_request_one(accounts[CF_ACTIVE], model, prompt, ref_path, w, h, seed)
        except RuntimeError as e:
            if any(k in str(e).lower() for k in ("4006", "daily free allocation", "neurons")):
                CF_ACTIVE += 1
                if CF_ACTIVE < len(accounts):
                    log(f"  Cloudflare account {CF_ACTIVE} free limit used up - switching to account {CF_ACTIVE + 1}")
                    continue
                CF_QUOTA_OUT = True
            raise
    CF_QUOTA_OUT = True
    raise RuntimeError("all Cloudflare accounts used up their daily free allocation (4006)")


def _cf_request_one(account, model, prompt, ref_path, w, h, seed):
    acct, token = account
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    hdr = {"Authorization": f"Bearer {token}"}
    if model == CF_MODEL:
        fields = {"prompt": (None, prompt[:2000]), "width": (None, str(w)), "height": (None, str(h))}
        if seed is not None:
            fields["seed"] = (None, str(seed))
        if ref_path:
            fields["input_image_0"] = ("ref.jpg", open(ref_path, "rb"), "image/jpeg")
        r = requests.post(url, headers=hdr, files=fields, timeout=150)
    else:
        r = requests.post(url, headers=hdr, json={"prompt": prompt[:2000], "steps": 6}, timeout=150)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    js = r.json()
    img = (js.get("result") or {}).get("image") or js.get("image")
    if not img:
        raise RuntimeError("no image in reply: " + r.text[:200])
    return base64.b64decode(img)


def save_picture(data, path):
    with open(path + ".raw", "wb") as f:
        f.write(data)
    fit(Image.open(path + ".raw")).save(path, quality=93)


def make_cast_sheet(cast, path, seed):
    if MOCK:
        return mock_image(path, seed)
    humans = [c for c in cast.chars.values()]
    prompt = (f"{ART_STYLE}. Cast reference photo: all these people standing side by side, full body, "
              f"facing the camera, neutral grey studio background, even soft light. {cast.describe(humans)}")
    for attempt in range(3):
        try:
            data = cf_request(CF_MODEL, prompt, w=1024, h=576, seed=seed)
            with open(path + ".raw", "wb") as f:
                f.write(data)
            im = Image.open(path + ".raw").convert("RGB")
            im.thumbnail((508, 508))
            im.save(path, quality=92)
            cast.ref = path
            return True
        except Exception as e:
            log(f"  cast sheet attempt {attempt + 1} failed: {str(e)[:200]}")
            if CF_QUOTA_OUT:
                return False
            time.sleep(6 * (attempt + 1))
    return False


def make_image(cast, action, place, names, path, seed):
    global CF_QUOTA_OUT
    if MOCK:
        return mock_image(path, seed)
    if CF_QUOTA_OUT and not extras.agnes_ok():
        return False
    tries = []
    if cast.ref:
        tries.append((CF_MODEL, cast.scene_prompt(action, place, names, True), cast.ref))
    tries.append((CF_MODEL, cast.scene_prompt(action, place, names, False), None))
    tries.append((CF_BACKUP, cast.scene_prompt(action, place, names, False)[:1500], None))
    soft = False
    for attempt, (model, prompt, ref) in enumerate(tries):
        try:
            if soft:
                prompt = soften(prompt)
            save_picture(cf_request(model, prompt, ref, seed=seed), path)
            return True
        except Exception as e:
            if "flagged" in str(e).lower() or "3030" in str(e):
                soft = True                       # safety filter: next try uses gentler words
            if any(k in str(e).lower() for k in ("allocation", "4006", "quota", "neurons")) and not extras.agnes_ok():
                CF_QUOTA_OUT = True               # free daily limit used up: reuse earlier pictures
                log("  Cloudflare daily free limit reached - reusing earlier pictures with new camera moves")
                return False
            log(f"  picture attempt {attempt + 1} ({model.split('/')[-1]}) failed: {str(e)[:200]}")
            time.sleep(6 * (attempt + 1))
    return False


SOFT_WORDS = {
    "corpse": "still figure", "dead body": "figure lying still", "dead": "lifeless-looking", "blood": "red paint",
    "bloody": "stained", "kill": "chase", "killed": "gone", "murder": "mystery", "knife": "old key",
    "skull": "old stone", "demon": "shadowy figure", "possessed": "strange-eyed", "hanging": "standing",
    "terrified": "worried", "screaming": "calling out", "horror movie": "mystery movie", "ghost": "pale figure",
    "witch": "old woman", "grave": "old stone", "coffin": "old wooden box", "attack": "approach",
}


def soften(prompt):
    out = prompt
    for k, v in SOFT_WORDS.items():
        out = re.sub(rf"\b{k}\b", v, out, flags=re.I)
    return out.replace("eerie but not gory", "mysterious, suspenseful, family friendly")


# ----------------------------------------------------------------- 3. voices
# Voice "set" for every kind of character: (pitch change in Hz, speed change in %)
AGE_VOICE = {"child": (30, 8), "young": (10, 4), "adult": (0, 0), "old": (-16, -14)}


def age_group(a):
    a = str(a).lower()
    if any(k in a for k in ("child", "kid", "boy", "girl", "baby")):
        return "child"
    if any(k in a for k in ("young", "teen", "youth")):
        return "young"
    if any(k in a for k in ("old", "elder", "aged", "grand")):
        return "old"
    return "adult"


class Voices:
    """Gives every character their own voice: different speaker, pitch and speed.
    Ghosts get a deep, echoing voice."""

    def __init__(self, lang, cast):
        self.L = LANGS[lang]
        self.map = {}
        used = {"male": 0, "female": 0}
        dup = {}
        nar_voice = self.L["narrator"][0]
        for c in cast.chars.values():
            g = "female" if c["gender"].startswith("f") else "male"
            ag = age_group(c["age"])
            pool = [v for v in self.L[g] if v != nar_voice] or self.L[g]
            voice = pool[used[g] % len(pool)]
            used[g] += 1
            k = (voice, ag)
            n = dup.get(k, 0)                 # same voice + same age twice -> nudge pitch
            dup[k] = n + 1
            pitch, rate = AGE_VOICE[ag]
            pitch += [0, -8, 8, -14, 14][n % 5]
            if voice == nar_voice and ag in ("adult", "young"):
                pitch += 9                     # keep characters clearly different from the narrator
            ghost = False
            if ghost:
                rate -= 10
            self.map[c["name"].lower()] = (voice, f"{rate:+d}%", f"{pitch:+d}Hz", ghost)
        # expressive Gemini voices: never the same voice for two characters
        self.gemini_map, taken = {"mithu": MITHU_GEMINI[0]}, {NARRATOR_GEMINI[0], MITHU_GEMINI[0]}
        for c in cast.chars.values():
            if c["name"].lower() == "mithu":
                continue
            g = "female" if c["gender"].startswith("f") else "male"
            ag = age_group(c["age"])
            pool = GEMINI_POOL[(g, ag)] + [v for k, vs in GEMINI_POOL.items() if k[0] == g for v in vs]
            self.gemini_map[c["name"].lower()] = next((v for v in pool if v not in taken), pool[0])
            taken.add(self.gemini_map[c["name"].lower()])
        # free voice model (Indic Parler-TTS)
        self.parler_map = extras.parler_cast(
            [(c["name"], c["gender"], age_group(c["age"]), False) for c in cast.chars.values()
             if c["name"].lower() != "mithu"], lang, "female")
        spk = extras.PARLER_SPK.get(lang, extras.PARLER_SPK["bn"])
        self.parler_map["mithu"] = (spk["male"][-1], "a very high-pitched, squeaky, playful", "fast")
        self.cast = cast

    def for_speaker(self, speaker):
        s = ascii_text(speaker).lower()
        if not s or s.startswith("narrat"):
            v, r, p = self.L["narrator"]
            return v, r, p, False
        c = self.cast.find(s)
        if c:
            return self.map[c["name"].lower()]
        v, r, p = self.L["narrator"]
        return v, r, p, False


# ---------- expressive voices (Gemini, free keys) - real human acting instead of a robotic voice
NARRATOR_GEMINI = ("Sulafat", "Lumi Didi, a warm, loving young Indian woman telling a story to small children - "
                              "lively, smiling, full of feeling, changing her voice with the story like a real storyteller")
MITHU_GEMINI = ("Puck", "Mithu, a cheeky, funny little green parrot - a bright, squeaky, playful cartoon voice, "
                        "always excited and giggly")
GEMINI_POOL = {
    ("male", "child"): ["Achird", "Puck"], ("male", "young"): ["Fenrir", "Zubenelgenubi", "Sadachbia"],
    ("male", "adult"): ["Orus", "Iapetus", "Alnilam", "Schedar", "Umbriel"],
    ("male", "old"): ["Algenib", "Rasalgethi", "Sadaltager"],
    ("female", "child"): ["Leda", "Laomedeia"], ("female", "young"): ["Zephyr", "Aoede", "Despina"],
    ("female", "adult"): ["Kore", "Callirrhoe", "Erinome", "Achernar"],
    ("female", "old"): ["Gacrux", "Pulcherrima", "Autonoe"],
}
AGE_WORDS = {"child": "a small child of about seven, with a sweet, innocent child's voice",
             "young": "a young person in their early twenties", "adult": "an adult of about forty",
             "old": "a very old, kind grandparent in their late seventies, with a slow, slightly shaky voice"}
EMOTION_WORDS = {
    "normal": "naturally, with feeling", "calm": "calmly and gently", "whisper": "in a soft whisper",
    "scared": "worried and a little scared", "angry": "angrily, sharply", "sad": "sadly, slowly, with a heavy heart",
    "crying": "while crying and sobbing", "happy": "happily, smiling", "excited": "very excitedly",
    "laughing": "laughing", "proud": "proudly",
}
GEMINI_CACHE = {}
GEMINI_READY = False


def gemini_persona(voices, speaker):
    s = ascii_text(speaker).lower()
    c = voices.cast.find(s) if s and not s.startswith("narrat") else None
    if not c:
        return NARRATOR_GEMINI
    if c["name"].lower() == "mithu":
        return MITHU_GEMINI
    g = "female" if c["gender"].startswith("f") else "male"
    ag = age_group(c["age"])
    voice = voices.gemini_map.get(c["name"].lower(), GEMINI_POOL[(g, ag)][0])
    what = "a cute talking animal in a cartoon" if c.get("kind") == "animal" else ("a girl" if g == "female" and ag == "child" else
           "a boy" if ag == "child" else "a woman" if g == "female" else "a man")
    return voice, f"{c['name']}, {what}: {AGE_WORDS[ag]}. A lively cartoon character with real, warm human feelings"


def parler_persona(voices, speaker, lang):
    s = ascii_text(speaker).lower()
    c = voices.cast.find(s) if s and not s.startswith("narrat") else None
    if not c:   # Lumi Didi
        return (extras.PARLER_SPK.get(lang, extras.PARLER_SPK["bn"])["female"][0], "a warm, moderate-pitched", "moderate")
    return voices.parler_map.get(c["name"].lower(), ("Aditi", "a moderate-pitched", "moderate"))


def gemini_line(text, persona, emotion, lang, out_wav, delivery=""):
    if MOCK or extras.TTS_STATE["off"]:
        return False
    voice, who = persona
    how = EMOTION_WORDS.get(str(emotion).lower(), "naturally, with feeling")
    style = (f"Character: {who}. Emotion: {how}. " + (f"Delivery: {delivery}. " if delivery else "") +
             "This is a children's cartoon story: expressive, clear, never flat or robotic. " + extras.PRONOUNCE[lang])
    return extras.tts_gemini(text, voice, style, LANGS[lang]["name"], out_wav, SR)


def _voice_all(todo, make, label, max_minutes):
    global GEMINI_READY
    t0 = time.time()
    for k, (i, j, ln) in enumerate(todo):
        if time.time() - t0 > max_minutes * 60:
            log(f"  {label} too slow today")
            break
        p = os.path.join(WORK, f"g_{i:02d}_{j:02d}.wav")
        if not make(ln, p):
            log(f"  {label} stopped at line {k + 1}/{len(todo)}")
            break
        GEMINI_CACHE[(i, j)] = p
        if k == 0 or (k + 1) % 5 == 0:
            log(f"  {label}: {k + 1}/{len(todo)} lines done ({(time.time() - t0) / 60:.1f} min)")
        if k >= 2 and (time.time() - t0) / (k + 1) * len(todo) > max_minutes * 60:
            log(f"  {label} too slow to finish the whole video today")
            break
    else:
        GEMINI_READY = True
        log(f"  all {len(todo)} lines voiced by {label} in {(time.time() - t0) / 60:.1f} min")
        return True
    GEMINI_CACHE.clear()
    return False


def prepare_voices(parts_lines, voices, lang):
    """Voice the WHOLE video before it is made, all lines or none (so a voice never changes mid-video):
    1) Gemini expressive voices (free keys)  2) free voice model on GitHub (Indic Parler-TTS)
    3) otherwise Microsoft voices."""
    if MOCK:
        return False
    todo = [(i, j, ln) for i, lines in enumerate(parts_lines) for j, ln in enumerate(lines or [])
            if str(ln.get("text", "")).strip()]
    global GEMINI_READY

    def gemini_all():
        if not extras.tts_keys():
            return False
        log(f"Expressive voices for all {len(todo)} lines")
        items = []
        for (i, j, ln) in todo:
            voice, who = gemini_persona(voices, ln.get("speaker", "narrator"))
            feel = f"{EMOTION_WORDS.get(str(ln.get('emotion', 'normal')).lower(), 'naturally')}" + (
                f", {ln.get('delivery')}" if ln.get("delivery") else "")
            items.append({"text": extras.performed(ln), "plain": extras.strip_tags(str(ln["text"])), "voice": voice,
                          "who": who + ". This is a children's cartoon story: expressive, never flat or robotic",
                          "feel": feel, "spk": voice, "out": os.path.join(WORK, f"g_{i:02d}_{j:02d}.wav"),
                          "lang": lang})
        if extras.tts_gemini_batch(items, LANGS[lang]["name"], SR, extras.voice_minutes(45)):
            for (i, j, ln), it in zip(todo, items):
                GEMINI_CACHE[(i, j)] = it["out"]
            log("  all lines voiced by Gemini")
            return True
        GEMINI_CACHE.clear()
        return False

    def free_all():
        if not (extras.parler_ok() and extras.ensure_parler()):
            log("  free voice model not available (check the HF_TOKEN secret)")
            return False
        log(f"Free voice model for all {len(todo)} lines")
        return _voice_all(todo, lambda ln, p: extras.parler_line(str(ln["text"]), parler_persona(voices, ln.get("speaker", "narrator"), lang),
                                                                 ln.get("emotion", "normal"), p, SR),
                          "free voice model", int(env("FREE_VOICE_MINUTES") or 200))

    # cartoons: the free voice model first (the Gemini voice limit is kept for the horror stories);
    # Gemini only as a backup if the free model fails. USE_GEMINI_VOICE=1 puts Gemini first again.
    order = (gemini_all, free_all) if env("USE_GEMINI_VOICE") == "1" else (free_all, gemini_all)
    for engine in order:
        if engine():
            GEMINI_READY = True
            return True
    extras.TTS_STATE["off"] = True
    if env("ALLOW_MICROSOFT") == "1":
        log("  using Microsoft voices for the whole video")
        return False
    no_voice_stop()


def no_voice_stop():
    """No good voice today (Gemini limit over, free model failed): no robotic Microsoft voice - skip this video."""
    log("STOPPED: no expressive voice available today (Gemini free limit used up and the free voice model "
        "failed). Nothing was posted - the next run will try again. (Microsoft voices are switched off.)")
    extras.telegram("⚠️ Little Lumi: today's voices could not be made (Gemini limit over, free voice model failed) "
                    "- this video was skipped. The next run will try again.")
    sys.exit(0)


async def _edge(text, voice, rate, pitch, out, volume="+0%"):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume).save(out)


# how each emotion changes the voice: (speed %, pitch Hz, volume %, extra sound filter)
EMOTION_VOICE = {
    "normal": (0, 0, 0, ""),
    "calm": (-6, -2, -5, ""),
    "happy": (4, 6, 5, ""),
    "excited": (12, 12, 10, ""),
    "laughing": (8, 10, 5, ""),
    "proud": (-2, 2, 10, ""),
    "whisper": (-10, -6, -35, "highpass=f=180"),
    "scared": (12, 12, 5, ""),
    "angry": (5, -6, 20, ""),
    "sad": (-14, -10, -10, ""),
    "crying": (-10, 6, -5, ""),
}


def _add(a, b, unit):
    return f"{int(str(a).rstrip(unit).replace('+', '') or 0) + b:+d}{unit}"


def tts_line(text, voice_spec, gtts_lang, out_wav, emotion="normal"):
    """Speak one line -> mono 44.1k wav, acted with the given emotion. Returns seconds."""
    if MOCK and env("MOCK_VOICES"):              # test run: real recorded voices instead of beeps
        clips = sorted(glob.glob(os.path.join(env("MOCK_VOICES"), "*.wav")))
        shutil.copy(clips[abs(hash(text)) % len(clips)], out_wav)
        return duration(out_wav)
    if MOCK:
        secs = max(1.2, len(text) / 15)
        freq = 180 + (abs(hash(voice_spec[0] + voice_spec[2])) % 200)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={secs:.2f}",
             "-af", "volume=0.25", "-ar", str(SR), "-ac", "1", out_wav])
        return secs
    voice, rate, pitch, ghost = voice_spec
    er, ep, ev, efx = EMOTION_VOICE.get(str(emotion).lower(), EMOTION_VOICE["normal"])
    rate, pitch = _add(rate, er, "%"), _add(pitch, ep, "Hz")
    volume = f"{ev:+d}%"
    mp3 = out_wav + ".mp3"
    # clean text: symbols/emoji can make the voice service return nothing
    text = re.sub(r"[\u2026]", "...", text)
    text = re.sub(r"[^\w\s\u0900-\u097F\u0980-\u09FF.,!?;:'\"\-()\u0964\u0965]", " ", text)
    text = re.sub(r"\s+", " ", text).strip() or "..."
    ok = False
    # Microsoft's free voice sometimes returns "No audio was received" for some pitch/speed
    # settings (seen with hi-IN-Madhur). So: ask with full settings once; if that fails, ask with
    # plain settings and change pitch/speed ourselves afterwards (sounds the same, never fails).
    def _num(x):
        try:
            return int(str(x).rstrip("%Hz").replace("+", "") or 0)
        except ValueError:
            return 0
    post_pitch, post_tempo = 1.0, 1.0
    tries = [(rate, pitch, volume, False), (rate, "+0Hz", volume, True), ("+0%", "+0Hz", "+0%", True),
             ("+0%", "+0Hz", "+0%", True)]
    for attempt, (r_, p_, v_, manual) in enumerate(tries):
        try:
            asyncio.run(_edge(text, voice, r_, p_, mp3, v_))
            ok = os.path.exists(mp3) and os.path.getsize(mp3) > 800
            if ok:
                if manual:
                    post_pitch = max(0.85, min(1.22, 1 + _num(pitch) / 150))
                    if r_ == "+0%":
                        post_tempo = max(0.7, min(1.4, 1 + _num(rate) / 100))
                break
        except Exception as e:
            log(f"  voice attempt {attempt + 1} failed ({voice}): {str(e)[:80]}")
            time.sleep(2 + 3 * attempt)
    af = "aresample=44100"
    if ok and (post_pitch != 1.0 or post_tempo != 1.0):
        af = (f"asetrate=44100*{post_pitch:.3f},aresample=44100,"
              f"atempo={max(0.5, min(2.0, post_tempo / post_pitch)):.3f}")
    if not ok:
        # backup (Google) has only one voice -> change its pitch so characters still differ
        from gtts import gTTS
        gTTS(text, lang=gtts_lang).save(mp3)
        hz = int(pitch.replace("Hz", "")) if pitch.replace("Hz", "").lstrip("+-").isdigit() else 0
        male = voice in LANGS["hi"]["male"] + LANGS["bn"]["male"]
        f = max(0.72, min(1.3, (0.80 if male else 1.0) * (1 + hz / 160)))
        af = f"asetrate=44100*{f:.3f},aresample=44100,atempo={min(2.0, max(0.5, 1 / f)):.3f}"
    if efx:
        af += "," + efx
    if ghost:
        # Scary ghost voice, three layers mixed together:
        #  1. a very deep, slow, trembling copy of the voice
        #  2. a thin, high, airy "whisper" copy that follows a moment later
        #  3. a low growl (the deep voice, much lower again, quiet)
        # then a long cold echo, like a voice from an empty hall.
        g = (f"[0:a]{af},asplit=3[a][b][c];"
             "[a]asetrate=44100*0.78,aresample=44100,atempo=1.15,vibrato=f=4.5:d=0.35[deep];"
             "[b]asetrate=44100*1.08,aresample=44100,atempo=0.83,highpass=f=1800,volume=0.45,adelay=70[air];"
             "[c]asetrate=44100*0.62,aresample=44100,atempo=1.445,lowpass=f=700,volume=0.55,adelay=20[growl];"
             "[deep][air][growl]amix=inputs=3:normalize=0,"
             "aecho=0.8:0.8:120|260:0.3|0.15,lowpass=f=7000,"
             "dynaudnorm=f=150:g=7,volume=1.1[out]")
        run(["ffmpeg", "-y", "-i", mp3, "-filter_complex", g, "-map", "[out]", "-ac", "1", "-ar", str(SR), out_wav])
        return duration(out_wav)
    run(["ffmpeg", "-y", "-i", mp3, "-af", af, "-ac", "1", "-ar", str(SR), out_wav])
    return duration(out_wav)


# ----------------------------------------------------------------- 4. sound engine (no copyright)
def _np():
    import numpy as np
    return np


def _filt(x, kind, freq, order=2):
    from scipy.signal import butter, sosfilt
    sos = butter(order, freq, btype=kind, fs=SR, output="sos")
    return sosfilt(sos, x)


def _env_decay(n, secs):
    np = _np()
    return np.exp(-np.arange(n) / (SR * secs))


def _noise(n, rnd):
    np = _np()
    return rnd.standard_normal(n)


def _brown(n, rnd):
    np = _np()
    b = np.cumsum(rnd.standard_normal(n))
    b = _filt(b, "highpass", 20, 1)
    return b / (np.abs(b).max() + 1e-9)


def _smooth_lfo(n, rnd, speed=0.25):
    """Slowly wandering 0..1 curve."""
    np = _np()
    k = max(4, int(n / SR * speed * 4) + 4)
    pts = rnd.uniform(0, 1, k)
    return np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)


def _place(track, sound, at):
    i = int(at * SR)
    if i >= len(track):
        return
    j = min(len(track), i + len(sound))
    track[i:j] += sound[:j - i]


def _user_sfx(tag, n):
    """Use your own file sfx/<tag>.mp3 (or .wav) if you add one."""
    np = _np()
    for ext in ("mp3", "wav", "ogg", "m4a"):
        p = os.path.join(SFX_DIR, f"{tag}.{ext}")
        if os.path.exists(p):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", p, "-t", f"{n / SR:.2f}",
                                  "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True).stdout
            a = np.frombuffer(raw, dtype=np.float32).astype("float64")
            out = np.zeros(n)
            out[:len(a)] = a[:n]
            return out * 0.8
    return None


def synth(tag, n, rnd):
    np = _np()
    user = _user_sfx(tag, n)
    if user is not None:
        return user
    t = np.arange(n) / SR
    out = np.zeros(n)
    if tag == "wind":
        b = _filt(_brown(n, rnd), "bandpass", [150, 900])
        out = b / (np.abs(b).max() + 1e-9) * (0.25 + 0.75 * _smooth_lfo(n, rnd, 0.3)) * 0.55
    elif tag == "rain":
        w = _filt(_noise(n, rnd), "bandpass", [1200, 9000]) * 0.08
        drops = np.zeros(n)
        for _ in range(int(n / SR * 25)):
            k = rnd.integers(0, n)
            drops[k] = rnd.uniform(0.2, 1)
        drops = _filt(drops, "highpass", 2500) * 0.6
        out = (w + drops) * (0.8 + 0.2 * _smooth_lfo(n, rnd))
    elif tag == "thunder":
        for _ in range(max(1, int(n / SR / 12))):
            m = int(SR * rnd.uniform(3, 5))
            th = _filt(_brown(m, rnd), "lowpass", 220) * _env_decay(m, rnd.uniform(0.8, 1.6))
            th[:int(SR * 0.05)] *= np.linspace(0, 1, int(SR * 0.05))
            _place(out, th * 1.4, rnd.uniform(0.3, max(0.4, n / SR - 4)))
    elif tag == "crickets":
        chirp = np.sin(2 * np.pi * 4600 * t[:int(SR * 0.035)]) * np.hanning(int(SR * 0.035))
        x = 0.0
        while x < n / SR:
            for k in range(3):
                _place(out, chirp * 0.07, x + k * 0.06)
            x += rnd.uniform(0.6, 1.1)
    elif tag == "owl":
        def hoot(f, d):
            m = int(SR * d)
            tt = np.arange(m) / SR
            return np.sin(2 * np.pi * (f + 8 * np.sin(2 * np.pi * 6 * tt)) * tt) * np.hanning(m)
        x = rnd.uniform(0.5, 2)
        while x < n / SR - 2:
            _place(out, hoot(380, 0.35) * 0.18, x)
            _place(out, hoot(360, 0.6) * 0.18, x + 0.5)
            x += rnd.uniform(5, 9)
        out = out + _filt(out, "lowpass", 2000) * 0.3
    elif tag == "heartbeat":
        def thump(d):
            m = int(SR * d)
            tt = np.arange(m) / SR
            return np.sin(2 * np.pi * 52 * tt) * _env_decay(m, 0.06)
        x, period = 0.2, 0.95
        while x < n / SR:
            _place(out, thump(0.25) * 0.9, x)
            _place(out, thump(0.25) * 0.6, x + 0.22)
            x += period
            period = max(0.55, period - 0.01)    # speeds up = more tension
    elif tag == "footsteps":
        x = rnd.uniform(0.3, 1)
        while x < n / SR - 0.3:
            m = int(SR * 0.18)
            st = _filt(_noise(m, rnd), "bandpass", [80, 700]) * _env_decay(m, 0.03)
            _place(out, st * 0.6, x)
            x += rnd.uniform(0.55, 0.75)
    elif tag == "creak":
        for _ in range(max(1, int(n / SR / 8))):
            m = int(SR * rnd.uniform(1.2, 2.2))
            tt = np.arange(m) / SR
            f = 170 + 160 * np.sin(np.pi * tt / tt[-1]) + 15 * rnd.standard_normal(m).cumsum() / np.sqrt(m)
            ph = 2 * np.pi * np.cumsum(f) / SR
            saw = (ph / np.pi % 2) - 1
            cr = _filt(saw * (0.5 + 0.5 * (rnd.uniform(0, 1, m) > 0.3)), "bandpass", [300, 2500])
            _place(out, cr * np.hanning(m) * 0.35, rnd.uniform(0.2, max(0.3, n / SR - 2.5)))
    elif tag == "whisper":
        w = _filt(_noise(n, rnd), "bandpass", [1800, 6000])
        syl = (_smooth_lfo(n, rnd, 3.0) > 0.55).astype(float)
        syl = _filt(syl, "lowpass", 12, 1)
        out = w * syl * 0.16 * (0.3 + 0.7 * _smooth_lfo(n, rnd, 0.2))
    elif tag == "clock":
        x = 0.0
        tick = _filt(_noise(int(SR * 0.012), rnd), "highpass", 3000) * np.hanning(int(SR * 0.012))
        while x < n / SR:
            _place(out, tick * 0.35, x)
            x += 1.0
    elif tag == "howl":
        x = rnd.uniform(0.5, 1.5)
        while x < n / SR - 3:
            m = int(SR * 2.6)
            tt = np.arange(m) / SR
            f = 420 + 300 * np.sin(np.pi * tt / tt[-1]) ** 0.7 + 10 * np.sin(2 * np.pi * 5 * tt)
            hw = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.hanning(m)
            hw = hw + 0.5 * np.concatenate([np.zeros(int(SR * 0.25)), hw[:-int(SR * 0.25)]])
            _place(out, hw * 0.12, x)
            x += rnd.uniform(9, 15)
    elif tag == "drip":
        x = rnd.uniform(0.2, 1)
        while x < n / SR:
            m = int(SR * 0.12)
            tt = np.arange(m) / SR
            d = np.sin(2 * np.pi * (1800 - 6000 * tt) * tt) * _env_decay(m, 0.025)
            _place(out, d * 0.3, x)
            x += rnd.uniform(1.2, 3.0)
    elif tag == "knock":
        x = rnd.uniform(0.5, 2)
        for k in range(3):
            m = int(SR * 0.15)
            kn = _filt(_noise(m, rnd), "bandpass", [100, 900]) * _env_decay(m, 0.02)
            _place(out, kn * 1.1, x + k * 0.38)
    elif tag == "birds":
        x = rnd.uniform(0.1, 0.8)
        while x < n / SR - 0.5:
            m = int(SR * rnd.uniform(0.08, 0.18))
            tt = np.arange(m) / SR
            f0 = rnd.uniform(2500, 4200)
            ch = np.sin(2 * np.pi * (f0 + 1500 * np.sin(np.pi * tt / tt[-1])) * tt) * np.hanning(m)
            for r in range(int(rnd.integers(1, 4))):
                _place(out, ch * 0.08, x + r * 0.12)
            x += rnd.uniform(0.6, 2.2)
    elif tag == "water":
        w = _filt(_noise(n, rnd), "bandpass", [400, 3000])
        out = w * (0.5 + 0.5 * _smooth_lfo(n, rnd, 2.0)) * 0.08
    elif tag == "boing":
        m = int(SR * 0.6)
        tt = np.arange(m) / SR
        out[:m] += np.sin(2 * np.pi * (180 + 250 * np.exp(-tt * 6) * np.cos(2 * np.pi * 9 * tt)) * tt) * np.exp(-tt * 5) * 0.6
    elif tag == "whoosh":
        m = int(SR * 0.7)
        w = _filt(_noise(m, rnd), "bandpass", [500, 4000]) * np.hanning(m)
        out[:m] += w * 0.35
    elif tag == "pop":
        m = int(SR * 0.08)
        tt = np.arange(m) / SR
        out[:m] += np.sin(2 * np.pi * (900 - 5000 * tt) * tt) * np.exp(-tt * 60) * 0.7
    elif tag == "bell":
        m = int(SR * 2.0)
        tt = np.arange(m) / SR
        out[:m] += sum(np.sin(2 * np.pi * 880 * r * tt) / r for r in (1, 2.4, 3.9)) * np.exp(-tt * 2.2) * 0.25
    elif tag == "splash":
        m = int(SR * 0.9)
        w = _filt(_noise(m, rnd), "bandpass", [300, 6000]) * np.exp(-np.arange(m) / (SR * 0.25))
        out[:m] += w * 0.5
    elif tag == "scare_hit":
        m = int(SR * 2.5)
        tt = np.arange(m) / SR
        boom = np.sin(2 * np.pi * (60 - 20 * tt) * tt) * _env_decay(m, 0.6)
        stab = _filt(_noise(m, rnd), "bandpass", [2000, 7000]) * _env_decay(m, 0.25) * 0.4
        _place(out, (boom + stab) * 0.9, 0.05)
    return out


SFX_KEYWORDS = [  # words in a sound name -> built-in sound used when no real recording is available
    (("bird", "chirp", "crow", "cuckoo", "sparrow", "parrot", "rooster", "peacock"), "birds"),
    (("river", "stream", "pond", "flowing"), "water"),
    (("splash", "jump into water", "fell in water"), "splash"),
    (("bounce", "boing", "spring", "jump"), "boing"),
    (("whoosh", "swish", "fly", "zoom", "swing"), "whoosh"),
    (("pop", "bubble", "click"), "pop"),
    (("bell", "temple", "ring", "chime"), "bell"),
    (("door", "creak", "hinge", "gate", "floorboard", "chair"), "creak"),
    (("knock", "bang on", "tap"), "knock"),
    (("step", "walk", "footstep", "running"), "footsteps"),
    (("thunder", "lightning", "storm"), "thunder"),
    (("rain", "drizzle", "monsoon"), "rain"),
    (("wind", "breeze", "gust"), "wind"),
    (("heart",), "heartbeat"),
    (("clock", "tick"), "clock"),
    (("owl",), "owl"),
    (("howl", "dog", "wolf", "jackal"), "howl"),
    (("drip", "drop", "tap water"), "drip"),
    (("whisper", "murmur"), "whisper"),
    (("cricket", "insect", "night", "field"), "crickets"),
    (("crash", "bang", "boom", "thud", "fall"), "knock"),
]
_SFX_CACHE = {}


def _keyword_tag(name):
    low = str(name).lower()
    for words, tag in SFX_KEYWORDS:
        if any(w in low for w in words):
            return tag
    return None


def _decode(path, max_sec):
    np = _np()
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-t", f"{max_sec:.2f}", "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32).astype("float64")
    peak = np.abs(a).max() if len(a) else 0
    return a / peak * 0.8 if peak > 0 else a


def freesound(query, loop):
    """Real recorded sound from freesound.org (only Creative-Commons-0 = free for any use)."""
    key = env("FREESOUND_API_KEY")
    if not key or MOCK:
        return None
    ck = (query.lower(), loop)
    if ck in _SFX_CACHE:
        return _SFX_CACHE[ck]
    path = None
    try:
        dur = "[20 TO 600]" if loop else "[0.3 TO 10]"
        words = re.sub(r"[^a-z ]", " ", query.lower()).split()
        stop = {"a", "an", "the", "on", "of", "in", "at", "slowly", "suddenly", "old", "far", "away", "three", "two"}
        core = [w for w in words if w not in stop]
        pairs = [" ".join(core[i:i + 2]) for i in range(len(core) - 1)]
        tries = [" ".join(words), " ".join(core)] + pairs + core[:2]
        res = []
        for q in dict.fromkeys(t for t in tries if t):
            r = requests.get("https://freesound.org/apiv2/search/", timeout=30, params={
                "query": q, "token": key, "fields": "id,name,duration,previews,avg_rating,num_downloads",
                "filter": f'license:"Creative Commons 0" duration:{dur}', "sort": "score", "page_size": 8})
            res = r.json().get("results", []) if r.ok else []
            if res:
                # among the most relevant, prefer well-liked, much-used recordings (better quality)
                res = sorted(res[:5], key=lambda x: (x.get("avg_rating") or 0) * 10 + min(x.get("num_downloads") or 0, 5000) / 500,
                             reverse=True)
                break
        if res:
            pick = res[0]
            url = pick["previews"].get("preview-hq-mp3") or pick["previews"].get("preview-lq-mp3")
            path = os.path.join(WORK, f"fs_{pick['id']}.mp3")
            if not os.path.exists(path):
                with open(path, "wb") as f:
                    f.write(requests.get(url, timeout=60).content)
            log(f"    sound: '{query}' -> freesound #{pick['id']} {pick['name'][:40]}")
    except Exception as e:
        log(f"    freesound error for '{query}': {str(e)[:100]}")
        path = None
    _SFX_CACHE[ck] = path
    return path


def get_oneshot(name, rnd, max_sec=4.0):
    """A single sound effect (door creak, scream...). Real recording if possible, else built-in."""
    np = _np()
    p = freesound(name, loop=False)
    if p:
        a = _decode(p, max_sec)
        if len(a) > SR * 0.2:
            fade = min(len(a) // 4, int(SR * 0.3))
            a[-fade:] *= np.linspace(1, 0, fade)
            return a
    tag = _keyword_tag(name)
    if not tag:
        return None
    a = synth(tag, int(SR * max_sec), rnd)
    nz = np.nonzero(np.abs(a) > 0.02)[0]
    if len(nz) == 0:
        return None
    a = a[max(0, nz[0] - int(SR * 0.05)):]
    end = nz[-1] - nz[0] + int(SR * 0.4)
    return a[:max(int(SR * 0.3), end)] / (np.abs(a).max() + 1e-9) * 0.8


def get_ambience(name, n, rnd):
    """A background sound for the whole scene (rain, crickets...), looped to n samples."""
    np = _np()
    p = freesound(name, loop=True)
    if p:
        a = _decode(p, 120)
        if len(a) > SR * 3:
            reps = int(np.ceil(n / len(a))) + 1
            a = np.tile(a, reps)[:n]
            fade = min(n // 6, int(SR * 1.5))
            a[:fade] *= np.linspace(0, 1, fade)
            a[-fade:] *= np.linspace(1, 0, fade)
            return a * 0.6
    tag = _keyword_tag(name)
    if tag and tag != "scare_hit":
        return synth(tag, n, rnd)
    return None


def drone(n, rnd, mood):
    """Soft, cheerful background music: warm chords + a gentle music-box melody (made here, no copyright)."""
    np = _np()
    t = np.arange(n) / SR
    root = rnd.choice([261.63, 293.66, 329.63, 349.23])         # C, D, E, F
    if mood == "sad":
        prog = [(0, 3, 7), (-4, 0, 3), (-2, 2, 5), (-5, -1, 2)]   # minor, slow
        tempo = 70
    else:
        prog = [(0, 4, 7), (5, 9, 12), (-3, 0, 4), (7, 11, 14)]   # I - IV - vi - V
        tempo = {"funny": 118, "adventure": 112, "happy": 104}.get(mood, 90)
    beat = 60 / tempo
    bar = beat * 4
    out = np.zeros(n)
    # warm pad chords
    for k in range(int(t[-1] / bar) + 1 if n else 0):
        chord = prog[k % len(prog)]
        a0, a1 = int(k * bar * SR), min(n, int((k + 1) * bar * SR))
        if a0 >= n:
            break
        tt = t[a0:a1] - t[a0]
        env = np.minimum(1, tt / 0.4) * np.minimum(1, (bar - tt) / 0.4)
        for semi in chord:
            f = root / 2 * 2 ** (semi / 12)
            out[a0:a1] += 0.06 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt))
    # music-box melody on the beat (pentatonic, so it always sounds sweet)
    scale = [0, 2, 4, 7, 9, 12, 14, 16]
    step = beat / (2 if mood in ("funny", "adventure") else 1)
    note_len = int(SR * min(0.9, step * 1.6))
    nt = np.arange(note_len) / SR
    pos, prev = 0.0, 4
    while pos < t[-1] if n else False:
        if rnd.uniform() < 0.8:
            prev = int(np.clip(prev + rnd.choice([-2, -1, 1, 2]), 0, len(scale) - 1))
            f = root * 2 ** (scale[prev] / 12)
            note = (np.sin(2 * np.pi * f * nt) + 0.25 * np.sin(2 * np.pi * 3 * f * nt)) * np.exp(-nt * 4.5)
            _place(out, note * 0.05, pos)
        pos += step
    fade = min(n // 4, int(SR * 1.5))
    if fade:
        out[:fade] *= np.linspace(0, 1, fade)
        out[-fade:] *= np.linspace(1, 0, fade)
    return out * (0.8 if mood == "calm" else 1.0)


def read_wav(path):
    np = _np()
    with wave.open(path) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype("float64") / 32768
    return a


def write_wav(path, a):
    np = _np()
    a = np.clip(a, -1, 1)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((a * 32767).astype(np.int16).tobytes())


LINE_WAVS = {}


def make_scene_audio(lines, voices, lang, idx, sounds, mood, out_wav, ambience=None):
    """Like a radio drama: every line is spoken with its own voice + emotion, and each sound
    effect is placed exactly where the story says it happens (before / during / after the line).
    Ambience (rain, crickets...) and music run underneath and get quieter while people talk.
    Returns (seconds, [(start, dur, speaker_is_narrator, text)])."""
    np = _np()
    rnd = np.random.default_rng(1000 + idx)
    gap, lead, tail = 0.35, 0.5, 1.0
    pieces, subs, cues, silences, t = [], [], [], [], lead
    LINE_WAVS[idx] = []
    for j, ln in enumerate(lines):
        text = str(ln.get("text", "")).strip()
        if not text:
            continue
        sfx = [x for x in (ln.get("sfx") or []) if isinstance(x, dict) and x.get("sound")]
        before = [x for x in sfx if str(x.get("when", "")).startswith("before")]
        during = [x for x in sfx if str(x.get("when", "")).startswith("during")]
        after = [x for x in sfx if str(x.get("when", "")).startswith("after")]
        # sounds that happen first, e.g. "the door creaked..." -> creak, then the words
        for x in before[:2]:
            snd = get_oneshot(x["sound"], rnd)
            if snd is not None:
                cues.append((t, snd, 0.85))
                t += min(len(snd) / SR, 2.2) * 0.75 + 0.15
        if ln.get("jump_scare"):
            # classic jump scare: everything goes almost silent, then a sudden hit
            silences.append((max(0.0, t - 0.9), t))
            cues.append((t, synth("scare_hit", int(SR * 2.5), rnd), 1.0))
            t += 0.45
        spec = voices.for_speaker(ln.get("speaker", "narrator"))
        p = os.path.join(WORK, f"v_{idx:02d}_{j:02d}.wav")
        if (idx, j) in GEMINI_CACHE:
            shutil.copy(GEMINI_CACHE[(idx, j)], p)
        else:
            tts_line(extras.strip_tags(text), spec, LANGS[lang]["gtts"], p, ln.get("emotion", "normal"))
        a = read_wav(p)
        pk = np.abs(a).max()
        if pk > 0:                                    # every voice equally clear; whispers softer
            emo = str(ln.get("emotion", "normal")).lower()
            a = a / pk * {"whisper": 0.6, "shout": 0.97, "angry": 0.93}.get(emo, 0.88)
        if spec[3]:                                   # ghost speaking: cold swell + whispers
            m = int(SR * 1.2)
            swell = _filt(_noise(m, rnd), "bandpass", [300, 3000]) * np.linspace(0, 1, m) ** 2 * 0.35
            cues.append((max(0.0, t - 1.1), swell, 1.0))
            cues.append((t, synth("whisper", len(a) + int(SR * 0.8), rnd) * 1.4, 0.8))
        pieces.append((t, a))
        sp = ascii_text(ln.get("speaker", "")).lower()
        is_nar = (not sp) or sp.startswith("narrat") or voices.cast.find(sp) is None
        subs.append((t, len(a) / SR, is_nar, text))
        extras.remember_voice(text, a, SR)
        LINE_WAVS[idx].append(p)                     # the voice alone - the cartoon's lip-sync listens to it
        for x in during[:2]:
            snd = get_oneshot(x["sound"], rnd, max_sec=min(6.0, len(a) / SR + 1))
            if snd is not None:
                cues.append((t + 0.25, snd, 0.55))
        t += len(a) / SR + gap
        for x in after[:2]:
            snd = get_oneshot(x["sound"], rnd)
            if snd is not None:
                cues.append((t - gap + 0.1, snd, 0.85))
                t += min(len(snd) / SR, 2.0) * 0.7
    total = t - gap + tail
    total = math.ceil(total * FPS - 1e-6) / FPS   # a whole number of video frames: picture and sound never drift
    n = int(total * SR)

    voice = np.zeros(n)
    for start, a in pieces:
        _place(voice, a, start)

    # background: music + place ambience (from the story) + any old-style tags
    bed = drone(n, rnd, mood)
    for name in (ambience or [])[:2]:
        amb = get_ambience(str(name), n, rnd)
        if amb is not None:
            bed += amb * 0.5
    for tag in (sounds or [])[:3]:
        if tag in SOUND_TAGS and tag != "scare_hit":
            bed += synth(tag, n, rnd) * 0.5

    fx = np.zeros(n)
    for start, snd, vol in cues:
        _place(fx, snd * vol, start)

    # quieter background while someone talks; near silence before a jump scare
    talk = np.zeros(n)
    for start, a in pieces:
        talk[int(start * SR):int(start * SR) + len(a)] = 1
    talk = np.clip(_filt(talk, "lowpass", 3, 1), 0, 1)
    quiet = np.ones(n)
    for s0, s1 in silences:
        quiet[int(s0 * SR):int(s1 * SR)] = 0.08
    quiet = _filt(quiet, "lowpass", 6, 1)
    mix = voice * 0.95 + bed * (1 - 0.6 * talk) * quiet + fx * (1 - 0.3 * talk)
    peak = np.abs(mix).max()
    if peak > 0.98:
        mix *= 0.98 / peak
    write_wav(out_wav, mix)
    return total, subs


# ----------------------------------------------------------------- fonts
def find_font(lang):
    g = LANGS[lang]["font_glob"]
    cands = [env(f"FONT_PATH_{lang.upper()}")]
    cands += glob.glob(f"/usr/share/fonts/**/{g}-Bold.ttf", recursive=True)
    cands += glob.glob(os.path.join(HERE, "fonts", f"{g}*.ttf"))
    cands += glob.glob(f"/usr/share/fonts/**/{g}*.tt*", recursive=True)
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit(f"ERROR: font for {lang} not found (install fonts-noto-core).")


FONT = None


def font(size):
    from PIL import features                 # Bengali/Hindi shaping needs Raqm; without it, still never crash
    eng = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    return ImageFont.truetype(FONT, size, layout_engine=eng)


# ----------------------------------------------------------------- 5. thumbnail
def make_thumbnail(base_img, text, out, label):
    """Professional kids-channel thumbnail: bright punchy picture with the character big on the right,
    huge 2-line text on the left (yellow + white on a colour banner) with thick outline and glow,
    a story-type tag and a bright frame."""
    from PIL import ImageEnhance
    img = Image.open(base_img).convert("RGB").resize((W, H))
    img = ImageEnhance.Color(img).enhance(1.35)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Sharpness(img).enhance(1.6)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    # soft colour fade on the left so the words stand out
    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    for x in range(int(W * 0.6)):
        d.line([(x, 0), (x, H)], fill=int(175 * (1 - x / (W * 0.6)) ** 1.4))
    img = Image.composite(Image.new("RGB", (W, H), (40, 10, 90)), img, shade)

    words = text.strip().split()
    if len(words) >= 2:
        half = len(words) // 2 + len(words) % 2
        lines = [" ".join(words[:half]), " ".join(words[half:])]
    else:
        lines = [text.strip()]
    box_w = int(W * 0.6)
    probe = ImageDraw.Draw(img)
    size = 170
    while size > 56:
        f = font(size)
        if all(probe.textlength(l, font=f) <= box_w - 70 for l in lines) and size * 1.35 * len(lines) <= H * 0.68:
            break
        size -= 6
    f = font(size)
    lh = int(size * 1.38)
    y0 = int((H - lh * len(lines)) / 2) + 20
    x0 = 46

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))                      # white glow behind the words
    gd = ImageDraw.Draw(glow)
    for i, l in enumerate(lines):
        gd.text((x0, y0 + i * lh), l, font=f, fill=(255, 255, 255, 230), stroke_width=size // 6,
                stroke_fill=(255, 255, 255, 230))
    glow = glow.filter(ImageFilter.GaussianBlur(16))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    draw = ImageDraw.Draw(img)
    banner = (255, 70, 120)
    for i, l in enumerate(lines):
        y = y0 + i * lh
        if i == len(lines) - 1 and len(lines) > 1:                     # last line on a pink banner
            tw = draw.textlength(l, font=f)
            draw.rounded_rectangle([x0 - 18, y - size * 0.02, x0 + tw + 18, y + size * 1.22], radius=22, fill=banner,
                                   outline=(255, 255, 255), width=5)
            draw.text((x0, y), l, font=f, fill=(255, 255, 255), stroke_width=max(5, size // 18), stroke_fill=(90, 0, 40))
        else:
            draw.text((x0, y), l, font=f, fill=(255, 225, 0), stroke_width=max(8, size // 10), stroke_fill=(20, 0, 60))

    lf = font(40)                                                        # story-type tag
    tw = draw.textlength(label, font=lf)
    draw.rounded_rectangle([30, 26, 30 + tw + 44, 26 + 72], radius=36, fill=(255, 200, 0), outline=(255, 255, 255), width=4)
    draw.text((52, 30), label, font=lf, fill=(60, 0, 80))
    draw.rectangle([0, 0, W - 1, H - 1], outline=(255, 200, 0), width=12)  # bright frame
    img.save(out, quality=94)


# ----------------------------------------------------------------- 6. video
_REMBG = None
_LOOK = {}


def cutout_session():
    global _REMBG
    if _REMBG is None:
        from rembg import new_session
        try:
            _REMBG = new_session("isnet-general-use")
        except Exception as e:
            log("  cut-out model unavailable, using small model:", str(e)[:120])
            _REMBG = new_session("u2netp")
    return _REMBG


def split_layers(img_path):
    np = _np()
    import cv2
    from rembg import remove
    pic = Image.open(img_path).convert("RGB").resize((W, H))
    alpha = np.array(remove(pic, session=cutout_session(), only_mask=True).convert("L").resize((W, H)))
    part = (alpha > 128).mean()
    if part < 0.03 or part > 0.60:
        return None
    rgb = np.array(pic)
    hole = cv2.dilate((alpha > 40).astype("uint8") * 255, np.ones((25, 25), "uint8"))
    small = cv2.inpaint(cv2.resize(rgb, (W // 2, H // 2)), cv2.resize(hole, (W // 2, H // 2)), 9,
                        cv2.INPAINT_TELEA)
    bg = cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC)
    bg = np.where(hole[..., None] > 0, cv2.GaussianBlur(bg, (0, 0), 3), rgb)
    return bg, np.dstack([rgb, cv2.GaussianBlur(alpha, (0, 0), 1.2)])


def horror_look():
    """Pre-made vignette, film grain and fog textures (made once, reused every frame)."""
    if _LOOK:
        return _LOOK
    np = _np()
    import cv2
    rnd = np.random.default_rng(7)
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    _LOOK["vignette"] = np.clip(1.15 - 0.55 * r ** 1.6, 0.25, 1)[..., None].astype("float32")
    _LOOK["grain"] = [cv2.GaussianBlur((rnd.standard_normal((H, W)) * 4.5).astype("float32"), (0, 0), 0.8)[..., None]
                      for _ in range(6)]   # soft grain: looks like film, keeps the file small
    fog = cv2.resize(rnd.uniform(0, 1, (12, 24)).astype("float32"), (W * 2, H), interpolation=cv2.INTER_CUBIC)
    fog = cv2.GaussianBlur(fog, (0, 0), 25)
    _LOOK["fog"] = np.clip((fog - fog.min()) / (fog.max() - fog.min() + 1e-6), 0, 1)
    return _LOOK


def grade(frame_f32, f, sec, mood, rnd_flicker):
    """Bright, clean cartoon look: a touch more colour and a very soft vignette."""
    np = _np()
    look = horror_look()
    gray = frame_f32.mean(axis=2, keepdims=True)
    frame = gray + (frame_f32 - gray) * 1.08                    # slightly richer colours
    frame *= 0.88 + 0.12 * look["vignette"]
    return frame


_LAYER_CACHE = {}


def _layers_for(img):
    """Background + cut-out foreground for one picture (cached, pictures repeat)."""
    np = _np()
    import cv2
    if img in _LAYER_CACHE:
        return _LAYER_CACHE[img]
    layers = None
    try:
        layers = split_layers(img)
    except Exception as e:
        log(f"  cut-out failed: {str(e)[:100]}")
    d = {}
    if layers is not None:
        bg, fg = layers
        d["fg_a"] = fg[..., 3].astype("float32") / 255.0
        d["fg"] = cv2.cvtColor(fg[..., :3], cv2.COLOR_RGB2BGR).astype("float32")
        d["fg_rgb"] = fg[..., :3].astype("float32")
        ys_, xs_ = np.nonzero(d["fg_a"] > 0.5)
        bw_, bh_ = xs_.max() - xs_.min() + 1, ys_.max() - ys_.min() + 1
        # only a standing, full-body figure may walk (never someone sitting on a chair or a cushion)
        d["can_walk"] = bool(bh_ > 1.15 * bw_ and ys_.max() > 0.82 * H and bh_ > 0.45 * H)
        d["foot"], d["fig_h"] = (float(xs_.mean()), float(ys_.max())), float(bh_)
        # separate characters (if they do not touch): each can move on its own
        d["parts"] = []
        nl, lab_, st_, _c = cv2.connectedComponentsWithStats((d["fg_a"] > 0.5).astype("uint8"))
        big = [i for i in range(1, nl) if st_[i, 4] > 0.015 * W * H]
        if 2 <= len(big) <= 4:
            owner = {}                                # small loose bits (a hand, a tail) belong to the nearest character
            for i in range(1, nl):
                if i not in big:
                    owner[i] = min(big, key=lambda b: (_c[b][0] - _c[i][0]) ** 2 + (_c[b][1] - _c[i][1]) ** 2)
            for i in sorted(big, key=lambda i: st_[i, 0]):
                mine = [i] + [q for q, o in owner.items() if o == i]
                m_ = cv2.dilate(np.isin(lab_, mine).astype("uint8"), np.ones((9, 9), "uint8")).astype("float32")
                d["parts"].append({"a": d["fg_a"] * cv2.GaussianBlur(m_, (0, 0), 2), "lab": i})
                lab_[np.isin(lab_, mine)] = i
            d["part_lab"] = lab_
        d["faces"] = []
        if env("FACE_ANIM") != "0":
            try:                                      # eyes + mouth for blinking and talking
                import animate
                d["faces"] = sorted(animate.find_faces(np.ascontiguousarray(fg[..., :3])),
                                    key=lambda f_: f_["mouth"][0])           # left -> right
            except Exception as e:
                log(f"  face animation skipped: {str(e)[:100]}")
        for f_ in d["faces"]:                         # which separate character each face belongs to
            f_["part"] = None
            if d["parts"]:
                lb = d["part_lab"][int(min(H - 1, f_["mouth"][1])), int(min(W - 1, f_["mouth"][0]))]
                f_["part"] = next((j for j, pt in enumerate(d["parts"]) if pt["lab"] == lb), None)
        ys, xs = np.nonzero(d["fg_a"] > 0.5)
        d["cx"], d["cy"] = float(xs.mean()), float(ys.max())
        d["head"] = float(ys.min() + 0.28 * (ys.max() - ys.min()))
    else:
        bg = np.array(Image.open(img).convert("RGB").resize((W, H)))
        d["cx"], d["cy"], d["head"] = W / 2, H / 2, H * 0.42
    d["bg"] = cv2.cvtColor(bg, cv2.COLOR_RGB2BGR)
    _LAYER_CACHE[img] = d
    return d


def plan_shots(segments, total):
    """segments: [(image, start_sec)] -> [(image, start, end, close_up)].
    Long shots are split into a wide part and a close-up part so the screen keeps changing."""
    segs = []
    for k, (img, st) in enumerate(segments):
        en = segments[k + 1][1] if k + 1 < len(segments) else total
        if segs and segs[-1][0] == img:                       # same picture twice in a row -> one shot
            segs[-1] = (img, segs[-1][1], en, False)
        else:
            segs.append((img, st, en, False))
    out = []
    for i, (img, st, en, _) in enumerate(segs):
        d = en - st
        parts = 1 if d < 8 else (2 if d < 15 else 3)
        for p in range(parts):
            out.append((img, st + d * p / parts, st + d * (p + 1) / parts, p % 2 == 1))
    return out


def scene_clip_animated(segments, audio, out, idx, mood, talk=None, walks=None):
    """talk: [(start, end, silent, emotion, text, who)] - when characters speak (mouth moves in sync with the words).
    who = (left-to-right position of the speaker among the people in the picture, how many people) or None."""
    np = _np()
    import cv2
    dur = duration(audio)
    talk = talk or []
    try:
        import animate
        voice_env = animate.voice_envelope(audio, FPS)
    except Exception:
        animate, voice_env = None, None
    brnd = np.random.default_rng(idx + 900)
    blinks, bt = [], brnd.uniform(0.8, 2.5)
    while bt < dur:                                # a blink every 2.5-5 seconds ...
        blinks.append(bt)
        bt += brnd.uniform(2.5, 5.0)
    blinks += [tl[0] + 0.05 for tl in talk]        # ... and when someone starts to speak
    looks, lt = [], 0.0                            # small natural eye movements
    while lt < dur:
        looks.append((lt, brnd.uniform(-0.35, 0.35), brnd.uniform(-0.2, 0.2)))
        lt += brnd.uniform(1.2, 3.0)
    gaze_all = {}
    walks = walks or {}
    first_start = {}
    for (im_, st_, en_, cl_) in plan_shots(segments, dur):
        first_start.setdefault(im_, (st_, en_, cl_))
    sparks = np.c_[brnd.uniform(0, W, 28), brnd.uniform(0, H, 28), brnd.uniform(1.5, 3.5, 28),
                   brnd.uniform(8, 22, 28), brnd.uniform(0, 6.28, 28)]
    n = max(1, int(round(dur * FPS)))
    shots = plan_shots(segments, dur)
    rnd = np.random.default_rng(idx + 50)
    flicker = (rnd.uniform(0, 1, 400) > 0.93).astype("float32") * rnd.uniform(0.4, 1, 400)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", audio, "-t", f"{dur:.2f}",
         "-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, dur - 0.4):.2f}:d=0.4,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k",
         "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2", out],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    XF = 8                                                  # cross-fade frames between shots
    prev_last, cur_k, frame_in_shot = None, -1, 0
    try:
        for f in range(n):
            sec = f / FPS
            k = next((i for i, s in enumerate(shots) if s[1] <= sec < s[2]), len(shots) - 1)
            img, st, en, close = shots[k]
            if k != cur_k:
                cur_k, frame_in_shot = k, 0
            L = _layers_for(img)
            t = min(1.0, max(0.0, (sec - st) / max(en - st, 0.1)))
            ease = 0.5 - 0.5 * math.cos(math.pi * t)
            direction = 1 if (idx + k) % 2 == 0 else -1
            shake = 0.0
            pass
            if close:                                       # slow push towards the face
                fx, fy = L["cx"], L["head"]
                bz = 1.32 + 0.08 * ease
            else:                                           # wide shot, gentle drift
                fx, fy = W / 2, H / 2
                bz = 1.04 + 0.06 * ease
            Mb = cv2.getRotationMatrix2D((fx, fy), 0, bz)
            Mb[0, 2] += (W / 2 - fx) * (bz - 1) / bz * (1 if close else 0) + direction * (ease - 0.5) * 22 + shake
            Mb[1, 2] += (H / 2 - fy) * (bz - 1) / bz * (1 if close else 0) + shake * 0.6
            bg_src = _clean_bg(WALK_BG[img]) if img in WALK_BG and L.get("can_walk") else L["bg"]
            frame = cv2.warpAffine(bg_src, Mb, (W, H), borderMode=cv2.BORDER_REFLECT).astype("float32")
            if "fg" in L:
                mouth, emo, shape, speaking, who = 0.0, "", "a", False, None
                for (ta, tb, nar, em, tx, wh) in talk:
                    if ta <= sec < tb:
                        emo = str(em or "").lower()
                        if not nar and voice_env is not None and f < len(voice_env):
                            mouth, speaking, who = float(voice_env[f]), True, wh
                            if animate is not None:
                                shape = animate.viseme_at(tx, sec - ta, tb - ta)
                                if shape == "m":
                                    mouth = 0.0
                        break
                hop = tremble = 0.0
                if emo in ("excited", "laughing", "happy", "proud"):
                    hop = abs(math.sin(sec * math.pi * 2.6)) * (7 if emo != "proud" else 3)
                elif emo in ("scared",):
                    tremble = math.sin(sec * 55) * 1.6
                elif emo in ("sad", "crying"):
                    hop = -3.0
                # walking in: two pictures (left foot / right foot) swapped while the character comes in
                # from the side, then it stops and talks; puppet bounce if there is no second picture
                wdx = wb = wt = 0.0
                LL, align = L, None
                if (img in walks and L.get("can_walk") and first_start.get(img, (None,))[0] == st and not close
                        and "lumi_mithu" not in str(img)):
                    T = min(2.6, max(0.9, (en - st) * 0.55))
                    u_ = (sec - st) / T
                    if u_ < 1:
                        e_ = 1 - (1 - u_) ** 2
                        wdx = walks[img] * (1 - e_) * W * 0.62
                        pair = WALK_PAIRS.get(img)
                        LB = _layers_for(pair) if pair else None
                        if LB is not None and LB.get("can_walk"):
                            wb = 3 * abs(math.sin((sec - st) * math.pi * 4.0))
                            if int((sec - st) * 4) % 2 == 1:            # the other foot
                                LL = LB
                                sc = L["fig_h"] / max(1.0, LB["fig_h"])
                                (ax_, ay_), (bx_, by_) = L["foot"], LB["foot"]
                                align = np.float32([[sc, 0, ax_ - sc * bx_], [0, sc, ay_ - sc * by_]])
                        else:
                            wb = 14 * abs(math.sin((sec - st) * math.pi * 2.0)) * (1 - 0.5 * u_)
                            wt = 3.0 * math.sin((sec - st) * math.pi * 2.0) * (1 - u_)
                faces_ = LL.get("faces") or []
                # whose mouth moves: the speaker's face, matched by left-to-right position in the picture
                spk = spk_part = None
                parts_ = LL.get("parts") or []
                if speaking:
                    if who and who[0] is not None and parts_ and len(parts_) == who[1]:
                        spk_part = who[0]                                # the speaker's own cut-out
                        spk = next((q for q, fc in enumerate(faces_) if fc.get("part") == spk_part), None)
                    elif who and who[0] is not None and len(faces_) == who[1]:
                        spk = who[0]
                        spk_part = faces_[spk].get("part")
                    elif len(faces_) == 1 and (not who or who[1] <= 1):
                        spk, spk_part = 0, faces_[0].get("part")
                src = LL["fg"]
                if animate is not None and faces_:
                    pic = LL["fg_rgb"]
                    for fi, fc in enumerate(faces_):
                        # each face blinks at its own moments
                        bl = 0.0
                        for b0 in blinks:
                            b1 = b0 + 0.9 * fi
                            if 0 <= sec - b1 < 0.2:
                                bl = math.sin(math.pi * (sec - b1) / 0.2)
                        # eyes: the speaker looks at us, the others look at the speaker
                        lx, ly = 0.0, 0.0
                        for (t0_, gx_, gy_) in looks:
                            if t0_ <= sec + 0.4 * fi:
                                lx, ly = gx_, gy_
                        if spk is not None and fi != spk:
                            lx = 0.7 if faces_[spk]["mouth"][0] > fc["mouth"][0] else -0.7
                            ly = 0.0
                        elif spk is None and not speaking:
                            lx += 0.45 if fc["mouth"][0] < W / 2 else -0.45
                        if emo in ("sad", "crying"):
                            ly = 0.6
                        elif emo == "scared":
                            lx = 0.6 * math.sin(sec * 9 + fi)
                        g_ = gaze_all.setdefault(fi, [0.0, 0.0])
                        g_[0] += (lx - g_[0]) * 0.35
                        g_[1] += (ly - g_[1]) * 0.35
                        lips = mouth if (fi == spk and env("LIP_SYNC") == "1") else 0.0    # lip sync off by default
                        pic = animate.draw_face(pic, [fc], bl, lips, shape, tuple(g_))
                    src = cv2.cvtColor(np.clip(pic, 0, 255).astype("float32"), cv2.COLOR_RGB2BGR)
                fz = bz * (1.0 + 0.03 * ease) + 0.004 * math.sin(sec * 1.6)
                Mf = cv2.getRotationMatrix2D((fx, fy), 0.3 * math.sin(sec * 0.9) + wt, fz)
                Mf[0, 2] = Mb[0, 2] + direction * (ease - 0.5) * 26 - (fz - bz) * fx + wdx
                Mf[1, 2] = Mb[1, 2] - 2.0 * math.sin(sec * 1.1) - (fz - bz) * fy - wb
                if align is not None:                               # put picture B's feet where A's are
                    Mf = (np.vstack([Mf, [0, 0, 1]]) @ np.vstack([align, [0, 0, 1]]))[:2].astype("float64")
                if parts_ and align is None and not wdx:
                    # every character moves on its own: the speaker bounces with the words and the feeling,
                    # the others just breathe gently (each at its own pace)
                    rest = np.clip(LL["fg_a"] - sum(pt["a"] for pt in parts_), 0, 1)
                    layers_ = [(rest, 0.0, 0.0)]
                    for j, pt in enumerate(parts_):
                        if spk_part is not None and j == spk_part:
                            layers_.append((pt["a"], tremble, -hop - 3.0 * mouth))
                        else:
                            layers_.append((pt["a"], 0.0, -1.6 * math.sin(sec * (1.2 + 0.25 * j) + 1.7 * j)))
                    for (a_, ddx, ddy) in layers_:
                        M2 = Mf.copy()
                        M2[0, 2] += ddx
                        M2[1, 2] += ddy
                        fgw = cv2.warpAffine(src, M2, (W, H))
                        aw = cv2.warpAffine(a_, M2, (W, H))[..., None]
                        frame = frame * (1 - aw) + fgw * aw
                else:
                    Mf[0, 2] += tremble
                    Mf[1, 2] += -hop - 3.0 * mouth
                    fgw = cv2.warpAffine(src, Mf, (W, H))
                    aw = cv2.warpAffine(LL["fg_a"], Mf, (W, H))[..., None]
                    frame = frame * (1 - aw) + fgw * aw
            if mood in ("happy", "funny") and env("SPARKLES") != "0":   # a few soft floating sparkles
                glow = np.zeros((H, W), "float32")
                for x_, y_, r_, sp_, ph_ in sparks:
                    cv2.circle(glow, (int(x_ + 10 * math.sin(sec * 0.8 + ph_)), int((y_ - sp_ * sec) % H)), int(r_),
                               float(0.5 + 0.5 * math.sin(sec * 4 + ph_)), -1)
                frame = frame + cv2.GaussianBlur(glow, (0, 0), 3)[..., None] * np.array([160, 230, 255], "float32") * 0.55
            frame = grade(frame, f, sec, mood, flicker)
            if prev_last is not None and k > 0 and frame_in_shot < XF:
                a_ = (frame_in_shot + 1) / (XF + 1)
                frame = prev_last * (1 - a_) + frame * a_
            frame_in_shot += 1
            if f + 1 < n:
                nk = next((i for i, s in enumerate(shots) if s[1] <= (f + 1) / FPS < s[2]), len(shots) - 1)
                if nk != k:
                    prev_last = frame.copy()
            ff.stdin.write(np.clip(frame, 0, 255).astype("uint8").tobytes())
        ff.stdin.close()
    except Exception:
        ff.kill()
        raise
    if ff.wait() != 0:
        raise RuntimeError(ff.stderr.read().decode()[-500:])
    return dur


def scene_clip_simple(segments, audio, out, idx, mood):
    """Backup: each picture as its own slow zoom, joined, with the scene sound."""
    dur = duration(audio)
    shots = plan_shots(segments, dur)
    parts = []
    for k, (img, st, en, close) in enumerate(shots):
        d = max(0.2, en - st)
        frames = int(d * FPS) + 1
        z = f"min(1.25+0.0006*on,1.35)" if close else ("min(1+0.0005*on,1.07)" if k % 2 == 0 else "max(1.07-0.0005*on,1)")
        p = os.path.join(WORK, f"seg_{idx:02d}_{k:02d}.mp4")
        run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-t", f"{d:.3f}", "-vf",
             f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
             f"eq=saturation=1.08,format=yuv420p",
             "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", p])
        parts.append(p)
    lst = os.path.join(WORK, f"seg_{idx:02d}.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.basename(x)}'\n" for x in parts)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", audio, "-t", f"{dur:.2f}",
         "-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, dur - 0.4):.2f}:d=0.4,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k",
         "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2", out])
    return dur


WALK_PAIRS = {}       # walking picture A (left foot) -> picture B (right foot)
WALK_BG = {}          # walking picture A -> the same place with nobody in it (the character walks over it)
_BG_CACHE = {}


def _clean_bg(path):
    if path not in _BG_CACHE:
        import cv2
        _BG_CACHE[path] = cv2.cvtColor(_np().array(Image.open(path).convert("RGB").resize((W, H))), cv2.COLOR_RGB2BGR)
    return _BG_CACHE[path]
WALK_RE = re.compile(r"\b(walk|walks|walking|walked|enter|enters|entering|arriv\w*|comes|coming|came|runs|running|"
                     r"ran|approach\w*|hurr\w*|marches|marching|strolls|strolling|steps in|wanders)\b")


def scene_clip(segments, audio, out, idx, mood, talk=None, walks=None):
    if env("SIMPLE_MOTION") == "1" or (MOCK and env("TEST_ANIM") != "1"):
        return scene_clip_simple(segments, audio, out, idx, mood)
    try:
        return scene_clip_animated(segments, audio, out, idx, mood, talk, walks)
    except Exception as e:
        log(f"  animation skipped ({str(e)[:150]}) - simple motion")
        return scene_clip_simple(segments, audio, out, idx, mood)


def ass_time(t):
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def split_subs(text, max_len=44):
    parts = [p.strip() for p in re.split(r"(?<=[।!?,\.])\s+", text) if p.strip()]
    out = []
    for p in parts:
        cur = ""
        for w in p.split():
            if cur and len(cur) + 1 + len(w) > max_len:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            out.append(cur)
    return out


def write_ass(segments, path, family, size=None):
    """segments: (start, dur, is_narrator, text). Narration white, dialogue yellow.
    size=(720, 1280): 9:16 Reel subtitles (bigger margin: above the 'watch the full story' band)."""
    pw, ph = size or (W, H)
    fs, mv = (46, 250) if size else (52, 38)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Nar,{family},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,{mv},1
Style: Talk,{family},{fs + 2},&H0000E6FF,&H0000E6FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for start, dur, is_nar, text in segments:
        chunks = split_subs(text, 26 if size else 44)
        for c, (s0, s1) in zip(chunks, extras.sub_times(text, dur, chunks)):   # in step with the real voice
            rows.append(f"Dialogue: 0,{ass_time(start + s0)},{ass_time(start + s1)},"
                        f"{'Nar' if is_nar else 'Talk'},,0,0,0,,{c}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(rows) + "\n")


TIMELINE = ([], [])          # (start second of every part, every spoken line) of the last video
PORTRAIT_CLIPS = {}          # part number -> the cartoon scene filmed in 9:16 (for the Reels)
BADGE_COLORS = ((255, 60, 120), (255, 255, 255))


HOOK_TEXT = [""]             # big words on screen in the first seconds (the thumbnail's hook)


def hook_png(text, path):
    """the hook in big words at the top for the first seconds - most people watch the feed WITHOUT sound"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if text:
        d = ImageDraw.Draw(img)
        rows, f, sz = extras._fit_text(d, text, FONT, W - 120, 78, lines_max=2)
        band = int(len(rows) * sz * 1.35 + 40)
        for y in range(band):
            d.line([(0, y), (W, y)], fill=(0, 0, 0, int(160 * (1 - y / band) ** 0.6)))
        y = 20
        for r in rows:
            tw = d.textlength(r, font=f)
            d.text(((W - tw) / 2, y), r, font=f, fill=(255, 230, 0, 255), stroke_width=max(4, sz // 12),
                   stroke_fill=(200, 30, 90, 255))
            y += int(sz * 1.35)
    img.save(path)
    return path


def build_video(scene_parts, lang, out):
    """scene_parts: list of dict(image, lines, sounds, mood). Returns mp4 path."""
    global TIMELINE
    clips, segs, t, wavs, part_times = [], [], 0.0, [], []
    voices = scene_parts[0]["voices"]
    GEMINI_CACHE.clear()
    prepare_voices([sp["lines"] for sp in scene_parts], voices, lang)
    for i, sp in enumerate(scene_parts):
        log(f"Voices + sound + clip {i + 1}/{len(scene_parts)}")
        part_times.append(t)
        a = os.path.join(WORK, f"audio_{i:02d}.wav")
        wavs.append(a)
        d, subs = make_scene_audio(sp["lines"], voices, lang, i, sp.get("sounds"), sp.get("mood", "creepy"), a,
                                   sp.get("ambience"))
        c = os.path.join(WORK, f"clip_{i:02d}.mp4")
        shots = sp.get("shots") or []
        segments = []
        for k, (st, du, nar, tx) in enumerate(subs):        # picture changes when the next line starts
            img = shots[k] if k < len(shots) and shots[k] else sp["image"]
            segments.append((img, 0.0 if k == 0 else max(0.0, st - 0.2)))
        if not segments:
            segments = [(sp["image"], 0.0)]
        spoken = [ln for ln in sp["lines"] if str(ln.get("text", "")).strip()]
        host_part = "lumi_mithu" in str(sp.get("image", ""))      # Lumi Didi's own picture: she is the narrator
        talk = []
        for k, (st, du, nar, tx) in enumerate(subs):
            ln = spoken[k] if k < len(spoken) else {}
            is_lumi = str(ln.get("speaker", "narrator")).lower().startswith("narrat")
            silent = (not is_lumi) if host_part else nar          # True = no mouth movement for this line
            who = None
            if not silent and not host_part:
                pic_ = ln.get("image") if isinstance(ln.get("image"), dict) else {}
                people = [n for n in (pic_.get("characters") or [])
                          if (voices.cast.find(n) or {}).get("kind", "human") != "animal"]
                spk_c = voices.cast.find(str(ln.get("speaker", "")))
                idx_ = next((q for q, n in enumerate(people) if spk_c and voices.cast.find(n) is spk_c), None)
                who = (idx_, len(people))
            talk.append((st, st + du, silent, ln.get("emotion", ""), tx, who))
        walks = {}
        for k, ln in enumerate(spoken):          # a line whose picture shows someone walking / coming in
            img_k = shots[k] if k < len(shots) and shots[k] else None
            pr = ln.get("image") if isinstance(ln.get("image"), dict) else {}
            words = f"{pr.get('prompt', '')} {ln.get('en', '')}".lower()
            if img_k and img_k not in walks and WALK_RE.search(words):
                walks[img_k] = 1 if re.search(r"from (the )?right|to the left", words) else -1
        d = None
        pz = sp.get("puppet")
        if pz and pz.get("bg"):                  # TV-style cartoon with our own characters
            try:
                spec = dict(pz, lines=puppet_lines(sp, pz))
                pv = os.path.join(WORK, f"clip_{i:02d}_v.mp4")      # the same scene in 9:16 for the Reels
                d = puppet.render_scene(spec, [(st, du) for st, du, _, _ in subs], LINE_WAVS.get(i, []), a, c,
                                        W=W, H=H, FPS=FPS, log=log, portrait_out=pv)
                PORTRAIT_CLIPS[i] = pv
            except Exception as e:
                log(f"  cartoon scene failed ({str(e)[:200]}) - pictures instead")
                d = None
        if d is None:
            d = scene_clip(segments, a, c, i, sp.get("mood", "creepy"), talk, walks)
        segs += [(t + s, du, nar, tx) for s, du, nar, tx in subs]
        clips.append(c)
        t += d
    lst = os.path.join(WORK, "clips.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.basename(c)}'\n" for c in clips)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", os.path.join(WORK, "joined.mp4")])
    alst = os.path.join(WORK, "audio.txt")
    with open(alst, "w") as f:
        f.writelines(f"file '{os.path.basename(a)}'\n" for a in wavs)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", alst, "-c", "pcm_s16le", os.path.join(WORK, "full.wav")])
    write_ass(segs, os.path.join(WORK, "subs.ass"), LANGS[lang]["font_family"])
    vf = f"ass=subs.ass:fontsdir={os.path.dirname(FONT)}:shaping=complex,tpad=stop_mode=clone:stop_duration=3"
    total = duration(os.path.join(WORK, "full.wav"))
    TIMELINE = (part_times, segs, clips, total)
    try:                                   # small "Like - Share - Follow" pill, top right, at the start and the end
        extras.make_badge(FONT, LANGS[lang]["badge"], os.path.join(WORK, "badge.png"), BADGE_COLORS)
        hook_png(HOOK_TEXT[0], os.path.join(WORK, "hook.png"))      # big words for people watching without sound
        pic = ["-i", "badge.png", "-i", "hook.png", "-filter_complex",
               f"[0:v]{vf}[b];[b][2:v]overlay=W-w-24:22:enable='{extras.badge_filter(total)}'[c];"
               f"[c][3:v]overlay=0:0:enable='between(t,0,4.5)'[v]", "-map", "[v]"]
    except Exception as e:
        log("  badge skipped:", str(e)[:120])
        pic = ["-vf", vf, "-map", "0:v"]
    r = subprocess.run(["ffmpeg", "-y", "-i", "joined.mp4", "-i", "full.wav"] + pic + ["-map", "1:a",
                        "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart",
                        os.path.abspath(out)], capture_output=True, text=True, cwd=WORK)
    if r.returncode != 0:
        raise RuntimeError("final render failed:\n" + r.stderr[-2000:])
    return out


# ----------------------------------------------------------------- 7. posting
def _fb_json(r):
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f"Facebook replied HTTP {r.status_code}: {r.text[:200]!r}")


def fb_when():
    at = extras.publish_time()
    if at:
        log(f"  Facebook: scheduled for {at.strftime('%H:%M')} India time")
        return {"published": "false", "scheduled_publish_time": str(int(at.timestamp()))}
    return {"published": "true"}


FB_LANG = ["bn"]


def portrait_thumb(thumb):
    """9:16 thumbnail: the whole poster in the middle, a blurred copy behind"""
    from PIL import ImageEnhance, ImageFilter
    VW, VH = 1080, 1920
    t = Image.open(thumb).convert("RGB")
    s = max(VW / t.width, VH / t.height)
    bg = t.resize((int(t.width * s) + 1, int(t.height * s) + 1))
    bg = bg.crop(((bg.width - VW) // 2, (bg.height - VH) // 2, (bg.width - VW) // 2 + VW, (bg.height - VH) // 2 + VH))
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(30))).enhance(0.6)
    fg = t.resize((VW, VW * t.height // t.width))
    bg.paste(fg, (0, (VH - fg.height) // 2))
    out = os.path.join(WORK, "thumbnail_9x16.jpg")
    bg.save(out, quality=93)
    return out


def post_to_facebook(video, thumb, title, description):
    """Uploads in pieces (resumable), so big videos don't fail half-way."""
    pv = None
    if env("FB_PORTRAIT") != "0" and len(TIMELINE) >= 4 and PORTRAIT_CLIPS:
        try:                                          # 9:16 - fills the whole phone screen
            res = portrait_source(0, TIMELINE[3], FB_LANG[0])
            if res and os.path.exists(res[0]):
                pv = os.path.join(WORK, "facebook_9x16.mp4")
                shutil.copy(res[0], pv)
                log("  Facebook: 9:16 version made")
        except Exception as e:
            log("  9:16 version failed - square instead:", str(e)[:160])
            pv = None
    if pv:
        video = pv
        try:
            thumb = portrait_thumb(thumb) if thumb and os.path.exists(thumb) else thumb
        except Exception as e:
            log("  9:16 thumbnail skipped:", str(e)[:120])
    else:
        video, thumb = extras.fb_square(video, thumb, WORK)   # 1:1 ranks better on phones
    description = extras.fb_caption(description)               # Facebook likes 10-400 characters
    page, token = need_env("FB_PAGE_ID"), need_env("FB_PAGE_TOKEN")
    url = f"https://graph-video.facebook.com/v21.0/{page}/videos"
    size = os.path.getsize(video)
    log(f"  video size: {size / 1e6:.0f} MB")
    for attempt in range(3):
        try:
            js = _fb_json(requests.post(url, data={"access_token": token, "upload_phase": "start",
                                                   "file_size": str(size)}, timeout=120))
            if "error" in js:
                err = js["error"]
                if err.get("code") in (190, 200, 10, 100):
                    raise PermissionError(f"Facebook refused: {err.get('message')} -> check FB_PAGE_ID / FB_PAGE_TOKEN")
                raise RuntimeError(err.get("message"))
            sid, start, end = js["upload_session_id"], int(js["start_offset"]), int(js["end_offset"])
            with open(video, "rb") as f:
                while start < end:
                    f.seek(start)
                    chunk = f.read(end - start)
                    for t in range(4):
                        try:
                            jr = _fb_json(requests.post(url, data={"access_token": token, "upload_phase": "transfer",
                                                                   "upload_session_id": sid, "start_offset": str(start)},
                                                        files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")},
                                                        timeout=600))
                            if "error" in jr:
                                raise RuntimeError(jr["error"].get("message"))
                            break
                        except Exception as e:
                            if t == 3:
                                raise
                            log(f"    piece retry: {str(e)[:120]}")
                            time.sleep(10)
                    start, end = int(jr["start_offset"]), int(jr["end_offset"])
                    log(f"    uploaded {start / 1e6:.0f}/{size / 1e6:.0f} MB")
            with open(thumb, "rb") as th:
                jf = _fb_json(requests.post(url, data={"access_token": token, "upload_phase": "finish",
                                                       "upload_session_id": sid, "title": title,
                                                       "description": description, **fb_when()},
                                            files={"thumb": ("thumb.jpg", th, "image/jpeg")}, timeout=300))
            if jf.get("success") or jf.get("id"):
                return js.get("video_id") or jf.get("id") or sid
            raise RuntimeError(str(jf)[:300])
        except PermissionError:
            raise
        except Exception as e:
            log(f"  Facebook upload attempt {attempt + 1} failed: {str(e)[:250]}")
            time.sleep(30)
    raise RuntimeError("Facebook upload failed 3 times")


def youtube_ready():
    return all(env(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def post_to_youtube(video, thumb, title, description, tags, lang):
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": env("YT_CLIENT_ID"), "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"), "grant_type": "refresh_token"}, timeout=60)
    if not r.ok:
        raise PermissionError("YouTube login failed (check YT_ secrets): " + r.text[:300])
    hdr = {"Authorization": f"Bearer {r.json()['access_token']}"}
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": [t.lstrip("#") for t in tags][:15], "categoryId": "1",   # Film & Animation
                    "defaultLanguage": lang, "defaultAudioLanguage": lang},
        "status": {"privacyStatus": env("YT_PRIVACY") or "public", "selfDeclaredMadeForKids": env("YT_MADE_FOR_KIDS") == "1",   # children's cartoons must be marked "made for kids"
                   "containsSyntheticMedia": True},
    }
    at = extras.publish_time()
    if at and not env("YT_PRIVACY"):                  # private until the planned time, then public by itself
        meta["status"]["privacyStatus"] = "private"
        meta["status"]["publishAt"] = at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log(f"  YouTube: scheduled for {at.strftime('%H:%M')} India time")
    size = os.path.getsize(video)
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      headers={**hdr, "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                      data=json.dumps(meta), timeout=60)
    if not r.ok:
        raise RuntimeError("YouTube start failed: " + r.text[:400])
    with open(video, "rb") as f:
        up = requests.put(r.headers["Location"], headers={**hdr, "Content-Type": "video/mp4"}, data=f, timeout=1800)
    if not up.ok:
        raise RuntimeError("YouTube upload failed: " + up.text[:400])
    vid = up.json()["id"]
    if not thumb:
        return vid
    try:
        with open(thumb, "rb") as f:
            t = requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                              headers={**hdr, "Content-Type": "image/jpeg"}, data=f, timeout=120)
        if not t.ok:
            log("  YouTube thumbnail not set (channel may need phone verification):", t.text[:150])
    except Exception as e:
        log("  YouTube thumbnail error:", e)
    return vid


# ----------------------------------------------------------------- voice demo
DEMO_LINES = {
    "hi": {"narrator": "मैं इस कहानी का सूत्रधार हूँ।", "man": "मैं एक आदमी हूँ, मेरी आवाज़ ऐसी है।",
           "woman": "मैं एक औरत हूँ, मेरी आवाज़ ऐसी है।", "young man": "मैं एक नौजवान लड़का हूँ।",
           "young woman": "मैं एक नौजवान लड़की हूँ।", "old man": "मैं एक बूढ़ा आदमी हूँ।",
           "old woman": "मैं एक बूढ़ी औरत हूँ।", "boy": "मैं एक छोटा बच्चा हूँ।", "girl": "मैं एक छोटी बच्ची हूँ।",
           "ghost": "मैं... इस हवेली की आत्मा हूँ..."},
    "bn": {"narrator": "আমি এই গল্পের কথক।", "man": "আমি একজন পুরুষ, আমার গলা এরকম।",
           "woman": "আমি একজন মহিলা, আমার গলা এরকম।", "young man": "আমি একজন যুবক।",
           "young woman": "আমি একজন যুবতী।", "old man": "আমি একজন বুড়ো মানুষ।", "old woman": "আমি একজন বুড়ি।",
           "boy": "আমি একটা ছোট ছেলে।", "girl": "আমি একটা ছোট মেয়ে।", "ghost": "আমি... এই বাড়ির আত্মা..."},
}
DEMO_CAST = [("man", "male", "adult", "human"), ("woman", "female", "adult", "human"),
             ("young man", "male", "young", "human"), ("young woman", "female", "young", "human"),
             ("old man", "male", "old", "human"), ("old woman", "female", "old", "human"),
             ("boy", "male", "child", "human"), ("girl", "female", "child", "human"),
             ("ghost", "female", "old", "ghost")]


def voice_demo():
    """Makes work/voice_demo_hi.mp3 and work/voice_demo_bn.mp3 - every voice type says one line."""
    np = _np()
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    for lang in ("hi", "bn"):
        cast = Cast({"characters": [{"name": n, "gender": g, "age": a, "kind": k, "look": ""}
                                    for n, g, a, k in DEMO_CAST]})
        voices = Voices(lang, cast)
        lines = [{"speaker": "narrator", "text": DEMO_LINES[lang]["narrator"]}]
        lines += [{"speaker": n, "text": DEMO_LINES[lang][n]} for n, *_ in DEMO_CAST]
        out = os.path.join(WORK, f"voice_demo_{lang}.wav")
        make_scene_audio(lines, voices, lang, 0, ["wind"], "creepy", out)
        run(["ffmpeg", "-y", "-i", out, "-b:a", "160k", out.replace(".wav", ".mp3")])
        for n, *_ in DEMO_CAST:
            log(f"  {lang} {n:12s} -> {voices.map[n.lower()]}")
    log("Voice demo ready: download 'horror-video' from this run's page (Artifacts).")


# ----------------------------------------------------------------- main
def load_next_part(ready_only=True):
    """A big story told in parts: part 1 today 7 PM, part 2 tomorrow 7 PM, part 3 the day after."""
    try:
        with open(NEXT_PART, encoding="utf-8") as f:
            nxt = json.load(f)
        made = dt.datetime.fromisoformat(nxt["created"])
        if (dt.datetime.now(dt.timezone.utc) - made).total_seconds() < 5 * 86400:
            if ready_only and made.astimezone(extras.IST).date() >= dt.datetime.now(extras.IST).date():
                return None
            return nxt
    except Exception:
        pass
    return None


def viewer_names(history, n=2):
    """First names of real viewers who commented recently (they asked to appear in a story)."""
    if MOCK:
        return []
    used = {x for h in history[-15:] for x in (h.get("viewer_names") or [])}
    page = (env("PAGE_NAME_BN") + " " + env("PAGE_NAME_HI") + " Little Lumi").lower()
    names = []
    for h in reversed(history[-4:]):
        if not h.get("facebook"):
            continue
        try:
            for c in extras.post_comments(h.get("facebook")):
                first = str(c.get("name") or "").strip().split(" ")[0]
                first = re.sub(r"[^A-Za-z\u0980-\u09FF\u0900-\u097F]", "", first)
                if 2 <= len(first) <= 14 and first.lower() not in page and first not in used and first not in names:
                    names.append(first)
        except Exception:
            pass
    random.shuffle(names)
    return names[:n]


def vote_winner(history):
    """Yesterday's 1 PM video asked viewers to choose this evening's story (comment 1 or 2)."""
    for h in reversed(history[-6:]):
        v = h.get("vote")
        if not v or h.get("vote_used") or not h.get("facebook"):
            continue
        try:
            t = dt.datetime.fromisoformat(str(h.get("date")))
            if (dt.datetime.now(dt.timezone.utc) - t.replace(tzinfo=t.tzinfo or dt.timezone.utc)).total_seconds() > 36 * 3600:
                return None, None
        except Exception:
            return None, None
        try:
            vc = extras.vote_count(extras.post_comments(h.get("facebook"), h.get("youtube")))
            v1, v2 = len(vc["1"]), len(vc["2"])
        except Exception:
            v1 = v2 = 0
        win = 0 if v1 >= v2 else 1
        log(f"Viewers' vote for this story: 1 = {v1}, 2 = {v2}")
        h["vote_used"] = True
        return tuple(v["ideas"][win]), (v1 + v2)
    return None, None


def main():
    global FONT
    pass
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    history = load_history()
    if not MOCK and not DRY_RUN:
        try:
            changed = extras.flush_pending(history)    # comments of earlier videos that are live now
            changed = extras.reply_fans(history, env("LANGUAGE") or "bn") or changed   # answer the fans
            if changed:
                save_history(history)
        except Exception as e:
            log("  earlier comments skipped:", str(e)[:120])
    global SLOT
    SLOT = None if env("MODE") in ("amavasya", "compilation") else extras.current_slot(TRIGGERS)
    extras.plan_publish(SLOT)
    if env("MODE") == "compilation":
        return make_compilation(history)
    # automatic runs (GitHub's clock or the cron-job.org clock) must not post twice for one time slot
    if (env("EVENT") == "schedule" or env("MODE") == "auto") and (extras.slot_done(history, SLOT) or recently_posted(history, hours=2)):
        log("A video for this time slot was already posted - this backup run has nothing to do.")
        return
    if not MOCK:
        try:
            extras.refresh_stats(history)            # learn which kinds of stories people liked
        except Exception as e:
            log("  stats skipped:", str(e)[:150])
    lang = pick_language(history)
    L = LANGS[lang]
    FONT = find_font(lang)
    shout_names, shout_ids = [], []
    lastp = extras.last_post(history, key="quiz")
    if lastp and not MOCK and lastp.get("facebook"):
        try:
            qa = lastp["quiz"]
            shout_names, shout_ids = extras.winners(extras.post_comments(lastp.get("facebook")),
                                                    words=(qa.get("text", ""),), label=qa.get("label"))
            log(f"Right quiz answers last time: {len(shout_names)}")
        except Exception as e:
            log("  quiz-answer check skipped:", str(e)[:120])
    theme = pick_theme(history)
    festival = None
    fest = extras.festival_today("cartoon")
    if fest and not any(h.get("festival") == fest[0] and h.get("date") and
                        (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(h["date"])).total_seconds() < 20 * 3600
                        for h in history[-4:]):
        festival = fest[0]
        theme = ("divine" if fest[0] in DIVINE_FESTIVALS else "festival", fest[1])
        log(f"Festival special: {festival}")
    # ---- the weekly routine, the 7 PM serial, the viewers' vote (a festival always comes first)
    global ART_STYLE
    slot_hour = int(str(SLOT).split("@")[1]) if SLOT and "@" in str(SLOT) else None
    weekday = dt.datetime.now(extras.IST).weekday()
    part, total, prev, episode, voted = 0, 2, None, None, None
    prev_ready = load_next_part()
    series_waiting = prev_ready is None and load_next_part(ready_only=False) is not None
    if not festival and env("ROUTINE") != "0":
        if slot_hour == 13:                          # the day's fixed series
            cat = DAY_SPECIAL[weekday]
            if env("GOPAL_DAILY") != "0" and puppet_ready("gopal"):
                cat = "gopal"                        # every noon: the Gopal Bhar TV cartoon (while it is our only
                                                     # animated series; the other days' specials come back later)
            if cat in EPIC:
                episode = 1 + sum(1 for h in history if h.get("category") == cat)
                theme = (cat, EPIC[cat][(episode - 1) % len(EPIC[cat])])
            else:
                theme = (cat, random.choice(CATEGORIES[cat]))
            log(f"Weekly routine: {cat}" + (f" episode {episode}" if episode else ""))
        elif slot_hour == 19 and prev_ready:         # next part of the serial
            prev = prev_ready
            part = int(prev.get("done", 1)) + 1
            total = max(part, int(prev.get("total", 2)))
            theme = (prev["category"], prev["idea"])
        elif slot_hour == 19:                        # the viewers' choice from yesterday's 1 PM vote, or a serial
            win, n_votes = vote_winner(history)
            if win:
                theme, voted = win, n_votes
                log(f"This story was chosen by the viewers: {win[1]}")
            elif not series_waiting and random.random() < float(env("SERIES_CHANCE") or 0.4):
                cat = random.choice(SERIES_CATS)
                theme, part = (cat, random.choice(CATEGORIES[cat])), 1
    if env("FORCE_CATEGORY") in CATEGORIES:          # manual run: this kind of story
        theme = (env("FORCE_CATEGORY"), random.choice(CATEGORIES[env("FORCE_CATEGORY")]))
    category = theme[0]
    if category in MYTH:
        ART_STYLE = MYTH_STYLE                       # reverent devotional look for the epics and the Gita
    log(f"Language: {L['name']} | Story type: {theme[0]} / {theme[1]}" + (f" | SERIES part {part}" if part else ""))

    extra = ""
    wx = extras.weather_now(lang) if not MOCK else None
    if wx and any(k in wx for k in ("rain", "drizzle", "thunder", "fog", "cold")) and category not in ("divine", "panchatantra"):
        extra = f"\nTODAY'S WEATHER: {wx}. If it fits, let the story happen in this weather (cosy, not scary).\n"
        log("Weather:", wx)
    vnames = viewer_names(history) if (category not in MYTH and part < 2 and env("VIEWER_NAMES") != "0"
                                       and not puppet_ready(category)) else []
    if vnames:
        extra += (f"\nOUR VIEWERS IN THE STORY: give 1-2 friendly side characters these first names of real viewers "
                  f"(kind, positive roles only): {', '.join(vnames)}.\n")
        log("Viewer names in the story:", ", ".join(vnames))
    vote_ideas = None
    if slot_hour == 13 and env("VOTE") != "0":      # viewers choose tomorrow evening's story
        free = [c for c in CATEGORIES if c not in DAY_SPECIAL.values() and c not in ("moral", "animal")]
        c1, c2 = random.sample(free, 2)
        vote_ideas = [[c1, random.choice(CATEGORIES[c1])], [c2, random.choice(CATEGORIES[c2])]]
        extra += (f"\nAlso add the JSON key \"vote_labels\": two short catchy {L['name']} labels (2-5 words each) for "
                  f"these two story ideas for tomorrow: 1) {vote_ideas[0][1]} 2) {vote_ideas[1][1]}.\n")
    story = make_story(lang, theme, history, extra_rules=extra, part=part, prev=prev, total=total)
    if part == 1:
        try:
            total = min(3, max(2, int(str(story.get("total_parts") or 2)[:1])))
        except ValueError:
            total = 2
    continues = bool(part) and part < total
    series_id = (prev or {}).get("series_id") if part >= 2 else (
        dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes") if part == 1 else None)
    if part >= 2:                                    # same people and place as part 1
        story["characters"], story["setting"] = prev["characters"], prev["setting"]
    if category in MYTH:                             # the holy characters always look the same, as tradition shows
        for c in story.get("characters", []):
            k = MYTH_ALIASES.get(str(c.get("name", "")).lower().strip(), str(c.get("name", "")).lower().strip())
            if k in MYTH_LOOKS:
                c["look"] = MYTH_LOOKS[k]
        story["mithu_intro"] = story["mithu_outro"] = ""   # no parrot jokes in the holy stories
    title = story["title"].strip()[:85]
    if episode:
        title = f"{L['episode'].format(name=L['series_titles'].get(category, ''), n=episode)}: {title}"[:95]
    if part:
        title = f"{title} | {L['part'].format(n=part)}"[:95]
    log("Title:", title)
    with open(os.path.join(WORK, "story.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=1)

    cast = Cast(story)
    voices = Voices(lang, cast)
    for c in cast.chars.values():
        log(f"  {c['name']} ({c['gender']}, {c['age']}, {c['kind']}) -> voice {voices.map[c['name'].lower()][:3]}")
    seed = random.randint(1, 1_000_000)
    scenes = story["scenes"][:24]          # never cut the story short

    pup = puppet_ready(category)
    rig = RigMap(story, pup) if pup else None
    pups = [puppet_scene(s, rig) if rig else None for s in scenes]
    for p in pups:
        if p:
            p["rig"] = rig
    if pup:
        log(f"Our own cartoon characters act {sum(1 for p in pups if p)} of {len(scenes)} scenes")
    log("Cast reference picture")
    if pups and all(pups):
        log("  not needed - every scene uses our ready-made characters")
    elif not make_cast_sheet(cast, os.path.join(WORK, "cast.jpg"), seed):
        log("  no cast picture - using text descriptions only")
    cast.chars["mithu"] = dict(MITHU)
    voices = Voices(lang, cast)

    # one picture per spoken line (a new "camera shot" every few seconds), within the free budget
    budget = int(env("MAX_IMAGES") or 30)          # 3 videos a day must fit the free picture limit
    scene_lines = [[ln for ln in (s.get("lines") or []) if str(ln.get("text", "")).strip()] for s in scenes]
    total_lines = sum(len(x) for x in scene_lines) or 1
    imgs, shots_per_scene, last_ok, count = [], [], None, 0
    for i, (s, lines) in enumerate(zip(scenes, scene_lines)):
        pz = pups[i]
        if pz:                                       # TV-style scene: only an empty set picture is needed
            bg = get_set(pz.get("set"), pz.get("place") or s.get("place", ""), seed)
            if bg:
                pz["bg"] = bg
                shots_per_scene.append([bg] * max(1, len(lines)))
                imgs.append(bg)
                last_ok = bg
                continue
            pups[i] = None
        want = max(1, min(len(lines), round(len(lines) * budget / total_lines))) if lines else 1
        groups = [lines[round(g * len(lines) / want):round((g + 1) * len(lines) / want)] for g in range(want)] or [[]]
        scene_shots = []
        for g, grp in enumerate(groups):
            count += 1
            p = os.path.join(WORK, f"shot_{i:02d}_{g:02d}.jpg")
            first = grp[0] if grp else {}
            pic = first.get("image") if isinstance(first.get("image"), dict) else {}
            action = pic.get("prompt") or first.get("shot") or s.get("action", "")
            names = pic.get("characters") if isinstance(pic.get("characters"), list) else s.get("characters")
            people = [x for x in (pic.get("people") or []) if isinstance(x, dict) and x.get("name")]
            if people:                                   # exact poses first: the picture model follows them best
                side_ = lambda x: (0 if "left" in str(x.get("where", "")).lower() else
                                   2 if "right" in str(x.get("where", "")).lower() else 1)
                people = sorted(people, key=side_)       # left -> right, same order as the positions below
                n_ = len(people)
                desc = "; ".join(
                    f"{x['name']} is {x.get('pose', '')} {x.get('where', '')}, {x.get('doing', '')}, face: {x.get('feeling', '')}"
                    for x in people[:4])
                action = (f"EXACTLY {n_} {'character' if n_ == 1 else 'characters'} in the picture, no one else, nobody "
                          f"appears twice. {desc}. {action}")
                names = [x["name"] for x in people]
                pic["characters"] = names                 # used later to know who stands where
            log(f"Picture {count} (scene {i + 1}, shot {g + 1}/{len(groups)})")
            walking = bool(WALK_RE.search(f"{action} {first.get('en', '')}".lower())) and len(WALK_PAIRS) < int(
                env("MAX_WALKS") or 2)
            if walking:
                action = (f"{action}. Full body, side view, walking, mid-stride with the LEFT leg forward and the "
                          "right arm forward, feet visible")
            if make_image(cast, action, s.get("place", ""), names, p, seed):
                last_ok = p
                if walking:                              # the same moment with the other foot forward
                    pb = p.replace(".jpg", "_b.jpg")
                    act_b = action.replace("LEFT leg forward and the right arm", "RIGHT leg forward and the left arm")
                    log("  second walking picture (other foot)")
                    if make_image(cast, act_b, s.get("place", ""), names, pb, seed):
                        WALK_PAIRS[p] = pb
                        pg = p.replace(".jpg", "_bg.jpg")
                        log("  empty background for the walk")
                        if make_image(cast, f"{s.get('place', '')}. Empty place, nobody in the picture, wide shot",
                                      s.get("place", ""), [], pg, seed):
                            WALK_BG[p] = pg
            elif scene_shots:
                p = scene_shots[-1]                      # reuse; the camera move makes it look different
            elif last_ok:
                p = last_ok
            else:
                p = None
            scene_shots += [p] * max(1, len(grp))
        shots_per_scene.append(scene_shots)
        imgs.append(next((x for x in scene_shots if x), None))
    first_ok = next((p for p in imgs if p), None)
    if not first_ok:
        if CF_QUOTA_OUT:
            extras.telegram("⚠️ Little Lumi: today's free picture limit is used up - this video was skipped. "
                            "It resets at 5:30 AM India time.")
            log("STOPPED: today's free Cloudflare picture limit is used up on every account. "
                "Nothing was posted. It resets every day at 5:30 AM India time; the next run will work.")
            sys.exit(0)
        raise RuntimeError("No pictures could be made (check CF_ACCOUNT_ID / CF_API_TOKEN).")
    imgs = [p or first_ok for p in imgs]
    shots_per_scene = [[x or imgs[i] for x in sh] for i, sh in enumerate(shots_per_scene)]

    thumb_base = os.path.join(WORK, "thumb_base.jpg")
    ti = story.get("thumbnail_image") or {}
    if isinstance(ti, str):
        ti = {"action": ti}
    # poster-style thumbnail: the formula stays the same, only the people and the moment change
    hero = ti.get("hero") or (ti.get("characters") or [""])[0]
    second = ti.get("second") or ((ti.get("characters") or ["", ""])[1:2] or [""])[0]
    describe = lambda n: (f"{cast.find(n)['name']} ({cast.find(n)['look']})" if n and cast.find(n) else n)
    series_en = {"gopal": "Gopal Bhar", "divine": "Bengali devotional", "folk": "Thakurmar Jhuli fairy-tale",
                 "panchatantra": "Panchatantra fable", "birbal": "Akbar-Birbal", "betal": "Vikram-Betal",
                 "ramayan": "Ramayana (reverent devotional)", "mahabharat": "Mahabharata (reverent devotional)",
                 "gita": "Bhagavad Gita (reverent devotional)", "detective": "family detective",
                 "para": "Bengali family comedy"}.get(category, "Bengali family story")
    t_prompt = extras.poster_prompt("cartoon", {**ti, "hero": hero, "second": second}, describe, series_en,
                                    cast.setting)
    poster_done = False
    if rig and rig(hero):                            # poster from our own characters: they look exactly like the video
        try:
            r1, r2 = rig(hero), (rig(second) if second else None)
            bgs = [p["bg"] for p in pups if p and p.get("bg") and r1 in p["cast"]] or \
                  [p["bg"] for p in pups if p and p.get("bg")]
            if bgs:
                puppet.poster(bgs[0], (r1, f"{ti.get('hero_action', '')} {ti.get('moment', '')}"),
                              (r2, ti.get("second_action", "")) if r2 and r2 != r1 else None, thumb_base)
                poster_done = True
        except Exception as e:
            log("  cartoon poster skipped:", str(e)[:150])
    if not poster_done and not extras.hq_image(t_prompt, thumb_base, seed):
        if not make_image(cast, t_prompt, "", [n for n in (hero, second) if n], thumb_base, seed):
            shutil.copy(first_ok, thumb_base)
    thumb = os.path.join(WORK, "thumbnail.jpg")
    series_bn = L.get("series_titles", {}).get(category)
    big = series_bn or str(story.get("thumbnail_text") or title).strip()
    sub = str(story.get("episode_name") or (story.get("thumbnail_text") if series_bn else "") or "").strip()
    try:
        extras.poster_thumbnail(thumb_base, big, sub, thumb, "cartoon", FONT)
    except Exception as e:
        log("  poster thumbnail failed, simple one:", str(e)[:120])
        make_thumbnail(thumb_base, story.get("thumbnail_text") or title, thumb, L["labels"][category])

    clean_title = re.sub(r"[^\w\sऀ-ॿঀ-৿,।!?-]", "", title).strip()
    page = env(f"PAGE_NAME_{lang.upper()}") or env("PAGE_NAME") or L["page_default"]
    host = ensure_mascot() or thumb_base
    intro = [{"speaker": "narrator", "text": L["intro"].format(title=clean_title)}]
    if str(story.get("mithu_intro", "")).strip():
        intro.append({"speaker": "Mithu", "emotion": "excited", "text": str(story["mithu_intro"]).strip()})
    parts = [{"image": host, "lines": intro, "host_part": True,
              "sounds": ["birds"], "mood": "happy", "voices": voices}]
    for img, s, sh, pz in zip(imgs, scenes, shots_per_scene, pups):
        parts.append({"image": img, "shots": sh, "lines": s.get("lines", []), "sounds": s.get("sounds", []), "puppet": pz,
                      "ambience": s.get("ambience", []), "mood": s.get("mood", "happy"), "voices": voices})
    end_lines = []
    moral = str(story.get("moral", "")).strip()
    if moral:
        end_lines.append({"speaker": "narrator", "emotion": "calm",
                          "text": (f"{L['moral_intro']} {moral}" if category != "funny" else moral)})
    elif story.get("ending_line"):
        end_lines.append({"speaker": "narrator", "text": story["ending_line"]})
    end_img = host if host != thumb_base else (shots_per_scene[-1][-1] if shots_per_scene[-1] else imgs[-1])
    if end_lines:                                   # Lumi Didi tells the lesson, then the quiz, then goodbye
        parts.append({"image": end_img, "lines": end_lines, "sounds": ["birds"], "mood": "happy", "voices": voices,
                      "host_part": end_img == host})
        end_lines = []
    quiz = story.get("quiz") if isinstance(story.get("quiz"), dict) else {}
    qopts = [str(o).strip() for o in (quiz.get("options") or []) if str(o).strip()][:3]
    try:
        qans = int(str(quiz.get("answer", 0)).strip()[0])
    except Exception:
        qans = 0
    quiz_saved = None
    if quiz.get("question") and len(qopts) == 3 and 0 <= qans < 3:
        quiz_saved = {"label": L["quiz_labels"][qans], "text": qopts[qans]}
        try:
            labs = L["quiz_labels"]
            qimg, aimg = extras.quiz_cards(shots_per_scene[-1][-1] if shots_per_scene[-1] else imgs[-1], FONT,
                                           L["quiz_title"], str(quiz["question"]), qopts, qans, labs,
                                           os.path.join(WORK, "quiz_q.jpg"), os.path.join(WORK, "quiz_a.jpg"))
            read = " ".join(f"{labs[i]}, {o}." for i, o in enumerate(qopts))
            parts.append({"image": qimg, "shots": [qimg, qimg, aimg], "mood": "happy", "voices": voices,
                          "sounds": [], "lines": [
                              {"speaker": "narrator", "emotion": "excited", "text": f"{L['quiz_intro']} {quiz['question']} {read}"},
                              {"speaker": "narrator", "emotion": "calm", "text": L["quiz_count"]},
                              {"speaker": "narrator", "emotion": "happy",
                               "text": L["quiz_answer"].format(lab=labs[qans], ans=qopts[qans])}]})
        except Exception as e:
            log("  quiz skipped:", str(e)[:150])
    words = [(str(w.get("en", "")).strip(), str(w.get("meaning", "")).strip()) for w in (story.get("english_words") or [])
             if isinstance(w, dict) and w.get("en") and w.get("meaning")][:3]
    if len(words) == 3:
        try:
            wimg = extras.words_card(end_img, FONT, L["words_title"], words, os.path.join(WORK, "words.jpg"))
            items = " ".join(L["word_item"].format(en=e, m=m) for e, m in words)
            parts.append({"image": wimg, "mood": "happy", "voices": voices, "sounds": [],
                          "lines": [{"speaker": "narrator", "emotion": "happy", "text": L["words_line"].format(items=items)}]})
        except Exception as e:
            log("  English words skipped:", str(e)[:150])
    if shout_names:
        end_lines.append({"speaker": "narrator", "emotion": "happy",
                          "text": L["shout_line"].format(names=extras.name_list(shout_names, lang))})
    if vnames:
        end_lines.append({"speaker": "narrator", "emotion": "happy",
                          "text": L["viewer_chars"].format(names=extras.name_list(vnames, lang))})
    if voted:
        end_lines.append({"speaker": "narrator", "emotion": "happy", "text": L["vote_thanks"]})
    vote_saved = None
    vl = [str(x).strip() for x in (story.get("vote_labels") or []) if str(x).strip()][:2]
    if vote_ideas and len(vl) == 2:
        vote_saved = {"ideas": vote_ideas, "labels": vl}
        end_lines.append({"speaker": "narrator", "emotion": "excited", "text": L["vote_line"].format(o1=vl[0], o2=vl[1])})
    end_lines.append({"speaker": "narrator", "emotion": "happy", "text": L["how_to_join"]})
    if str(story.get("mithu_outro", "")).strip():
        end_lines.append({"speaker": "Mithu", "emotion": "laughing", "text": str(story["mithu_outro"]).strip()})
    end_lines.append({"speaker": "narrator", "text": (L["outro_part1"] if continues else L["outro"]).format(page=page)})
    parts.append({"image": end_img, "lines": end_lines, "sounds": ["birds"], "mood": "happy", "voices": voices,
                      "host_part": end_img == host})

    # COLD OPEN: people decide in 3 seconds - start INSIDE the story (its first, funniest/most gripping scene),
    # then Lumi Didi greets and says the title, then the rest of the story
    cold = env("COLD_OPEN") != "0" and len(parts) > 2 and not parts[1].get("host_part") and parts[0].get("host_part")
    if cold:
        parts[0], parts[1] = parts[1], parts[0]
    first_host = True
    for k, p in enumerate(parts):                # Lumi Didi + Mithu (he flies in and sits on her shoulder)
        if p.get("host_part"):
            p["puppet"] = host_puppet(first_host)
            first_host = False
    HOOK_TEXT[0] = str(story.get("thumbnail_text") or "").strip()
    video = os.path.join(WORK, "final.mp4")
    build_video(parts, lang, video)
    log(f"Video ready: {duration(video):.0f} seconds")

    tags = [t if t.startswith("#") else "#" + t.replace(" ", "") for t in story.get("hashtags", [])[:15]]
    source = ascii_text(story.get("source", ""))
    description = (f"{title}\n\n{story.get('description', '').strip()}\n\n" + (f"✨ {moral}\n\n" if moral else "")
                   + (f"📖 {source}\n\n" if source else "") + f"{L['share_cta']}\n\n"
                   + f"{L['ai_note']}\n\n{' '.join(tags)}")
    part_times, segs = TIMELINE[0], TIMELINE[1]
    _lab = [sc.get("chapter") or f"{k + 1}" for k, sc in enumerate(scenes)]
    _lab = [_lab[0], L["ch_intro"]] + _lab[1:] if cold else [L["ch_intro"]] + _lab
    chap = extras.chapters_text(part_times, _lab + [L["ch_end"]], L["chapters"])
    yt_description = description.replace(L["ai_note"], (f"{chap}\n\n" if chap else "") + L["ai_note"])

    results = {}
    if DRY_RUN:
        log("DRY RUN - not posting. Files are in the 'work' folder.")
    else:
        try:
            FB_LANG[0] = lang
            results["facebook"] = post_to_facebook(video, thumb, title, description)
            log("Posted to Facebook:", results["facebook"])
        except Exception as e:
            log("FACEBOOK FAILED:", e)
            results["facebook_error"] = str(e)[:200]
        if youtube_ready():
            try:
                results["youtube"] = post_to_youtube(video, thumb, title, yt_description, tags, lang)
                log("Posted to YouTube:", results["youtube"])
            except Exception as e:
                log("YOUTUBE FAILED:", e)
                results["youtube_error"] = str(e)[:200]
        else:
            log("YouTube secrets not set - skipping YouTube")
        if not results.get("facebook") and not results.get("youtube"):
            raise SystemExit("Posting failed everywhere - see messages above.")

    first = [str(story.get("comment_question", "")).strip()]
    if shout_names:
        first.append(L["shout_comment"].format(names=extras.name_list(shout_names, lang, 10)))
    first.append(L["join_comment"])
    story["comment_question"] = "\n\n".join(x for x in first if x)
    results.update(grow(video, story, title, lang, L, category, tags, results, history, page))
    if shout_ids and results.get("facebook") and not DRY_RUN:
        n = extras.reply_to(shout_ids, L["congrats_reply"].format(link=f"https://www.facebook.com/{results['facebook']}"))
        log(f"  congratulated {n} children/parents under their comments")

    history.append({"date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "lang": lang, "slot": SLOT,
                    "pending_comments": list(extras.PENDING),
                    "category": category, "idea": theme[1], "episode": episode, "part": part, "continues": continues,
                    "series_id": series_id, "title": title, "festival": festival, "vote": vote_saved,
                    "viewer_names": vnames, "quiz": quiz_saved, **results})
    if not MOCK:
        save_history(history)
        if continues:
            with open(NEXT_PART, "w", encoding="utf-8") as f:
                json.dump({"created": dt.datetime.now(dt.timezone.utc).isoformat(), "category": category,
                           "idea": theme[1], "title": (prev or {}).get("title") or story["title"], "done": part,
                           "total": total, "series_id": series_id, "summary": story.get("summary", ""),
                           "part2_plan": story.get("part2_plan", ""), "characters": story.get("characters"),
                           "setting": story.get("setting", "")}, f, ensure_ascii=False, indent=1)
            log(f"Series: part {part + 1} of {total} comes tomorrow at 7 PM")
        elif part >= 2 and os.path.exists(NEXT_PART):
            os.remove(NEXT_PART)
    extras.telegram(extras.report_text(env(f"PAGE_NAME_{lang.upper()}") or "Little Lumi Stories", title, results, history))


def make_compilation(history):
    """Sunday special: this week's stories (one language) joined into one long video with chapters."""
    global FONT
    now = dt.datetime.now(dt.timezone.utc)
    week = []
    for h in history[-40:]:
        try:
            t = dt.datetime.fromisoformat(str(h.get("date")))
        except Exception:
            continue
        if (now - t.replace(tzinfo=t.tzinfo or dt.timezone.utc)).days <= 7 and h.get("facebook") \
                and h.get("kind") != "compilation":
            week.append(h)
    langs = [h.get("lang") for h in week]
    lang = env("LANGUAGE") if env("LANGUAGE") in LANGS else (max(set(langs), key=langs.count) if langs else "bn")
    items = [h for h in week if h.get("lang") == lang][-12:]
    if len(items) < 3:
        log(f"Weekly compilation: only {len(items)} stories this week - skipped")
        return
    L = LANGS[lang]
    FONT = find_font(lang)
    clips, chapters, frames, t = [], [], [], 0.0
    for k, h in enumerate(items):
        try:
            src, _ = extras.fb_video_source(h["facebook"])
            if not src:
                raise RuntimeError("no video link")
            raw = extras.download(src, os.path.join(WORK, f"raw_{k}.mp4"))
            c = extras.normalize_clip(raw, os.path.join(WORK, f"c_{k:02d}.mp4"))
            os.remove(raw)
            d = duration(c)
            fr = os.path.join(WORK, f"fr_{k}.jpg")
            run(["ffmpeg", "-y", "-ss", f"{min(40, d / 3):.1f}", "-i", c, "-frames:v", "1", fr])
            frames.append(fr)
            chapters.append((t, h.get("title", f"{k + 1}")))
            clips.append(c)
            t += d
            log(f"  added: {h.get('title', '')[:50]} ({d / 60:.1f} min)")
        except Exception as e:
            log(f"  skipped one story: {str(e)[:150]}")
    if len(clips) < 3:
        log("Weekly compilation: not enough videos could be downloaded - skipped")
        return
    lst = os.path.join(WORK, "comp.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.basename(c)}'\n" for c in clips)
    video = os.path.join(WORK, "final.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", video])
    minutes = int(round(t / 60))
    title = L["comp_title"].format(m=minutes, n=len(clips))[:95]
    base = extras.collage(frames, os.path.join(WORK, "thumb_base.jpg"))
    thumb = os.path.join(WORK, "thumbnail.jpg")
    make_thumbnail(base, L["comp_thumb"].format(m=minutes), thumb, L["labels"]["bedtime"])
    chap = L["chapters"] + "\n" + "\n".join(f"{extras.fmt_time(s)} {n[:60]}" for s, n in chapters)
    tags = ["#KidsStories", "#MoralStories", "#BedtimeStories", "#StoryCompilation"]
    description = f"{title}\n\n{chap}\n\n{L['ai_note']}\n\n{' '.join(tags)}"
    log(f"Compilation ready: {minutes} minutes, {len(clips)} stories")
    results = {}
    if not DRY_RUN:
        try:
            FB_LANG[0] = lang
            results["facebook"] = post_to_facebook(video, thumb, title, description)
            log("Posted compilation to Facebook:", results["facebook"])
        except Exception as e:
            log("FACEBOOK FAILED:", e)
        if youtube_ready() and extras.yt_extra_ok():
            try:
                results["youtube"] = post_to_youtube(video, thumb, title, description, tags, lang)
                log("Posted compilation to YouTube:", results["youtube"])
                extras.yt_add_to_playlist(results["youtube"], f"{L['labels']['bedtime']} | {L['playlist_tail']}", lang)
            except Exception as e:
                log("YouTube compilation skipped:", str(e)[:200])
        history.append({"date": now.isoformat(timespec="minutes"), "lang": lang, "kind": "compilation",
                        "title": title, **results})
        save_history(history)


def _run_in(cmd, cwd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd[:3])}...\n{r.stderr[-1500:]}")


def portrait_source(st, en, lang):
    """A 9:16 video of the teaser's part of the story: the cartoon scenes come from their own 9:16 camera,
    any other part (quiz card...) is fitted in. With the voices and 9:16 subtitles. Returns (path, start)."""
    if len(TIMELINE) < 4 or not PORTRAIT_CLIPS:
        return None
    part_times, segs, clips, total = TIMELINE
    ends = list(part_times[1:]) + [total]
    use = [i for i in range(len(part_times)) if ends[i] > st and part_times[i] < en]
    if not use or not any(i in PORTRAIT_CLIPS and os.path.exists(PORTRAIT_CLIPS[i]) for i in use):
        return None
    parts = []
    for i in use:
        p = PORTRAIT_CLIPS.get(i)
        if not (p and os.path.exists(p)):
            p = os.path.join(WORK, f"clip_{i:02d}_vf.mp4")
            run(["ffmpeg", "-y", "-i", clips[i], "-an", "-filter_complex",
                 "[0:v]split[a][b];[a]scale=-2:1280,crop=720:1280,boxblur=20:2,eq=brightness=-0.2[bg];"
                 "[b]scale=720:-2[fg];[bg][fg]overlay=0:(H-h)/2,format=yuv420p",
                 "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", p])
        parts.append(p)
    lst = os.path.join(WORK, "portrait.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.basename(p)}'\n" for p in parts)
    off = part_times[use[0]]
    dur = ends[use[-1]] - off
    ass = os.path.join(WORK, "subs_v.ass")
    write_ass([(s - off, d, n, tx) for s, d, n, tx in segs if off <= s < off + dur], ass,
              LANGS[lang]["font_family"], size=(720, 1280))
    out = os.path.join(WORK, "portrait.mp4")
    _run_in(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-ss", f"{off:.2f}", "-t", f"{dur:.2f}",
         "-i", os.path.join(WORK, "full.wav"), "-map", "0:v", "-map", "1:a", "-t", f"{dur:.2f}",
         "-vf", f"ass=subs_v.ass:fontsdir={os.path.dirname(FONT)}:shaping=complex,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k", out],
        cwd=WORK)
    return out, off


def grow(video, story, title, lang, L, category, tags, results, history, page):
    """Extra reach after the main post: Reel + Short teaser, first comment, playlist. Never stops the run.
    (Kids videos on YouTube have comments switched off by YouTube, so the question goes only to Facebook.)"""
    out = {}
    part_times, segs = TIMELINE[0], TIMELINE[1]
    teaser = os.path.join(WORK, "teaser.mp4")
    try:
        st, en = extras.pick_window(segs, part_times, story.get("teaser_scene") or 2)
        src = None
        try:
            src = portrait_source(st, en, lang)          # the cartoon itself filmed in 9:16 (looks native on phones)
        except Exception as e:
            log("  9:16 teaser picture not made, using the wide one:", str(e)[:150])
        if src:
            path, off = src
            extras.make_teaser(path, st - off, en - off, teaser, FONT, story.get("thumbnail_text") or title,
                               L["cta"], WORK, colors=((255, 225, 0), (255, 60, 120)), vertical=True)
        else:
            extras.make_teaser(video, st, en, teaser, FONT, story.get("thumbnail_text") or title, L["cta"], WORK,
                               colors=((255, 225, 0), (255, 60, 120)))
        log(f"Teaser ready ({en - st:.0f} s, from {st:.0f} s)")
    except Exception as e:
        log("  teaser skipped:", str(e)[:200])
        teaser = None
    if DRY_RUN:
        return out
    question = str(story.get("comment_question", "")).strip()
    short_desc = f"{title}\n{L['full_link']} {page}\n{' '.join(tags[:6])}"
    if teaser and env("FB_REELS") != "0":
        try:
            out["fb_reel"] = extras.fb_post_reel(teaser, short_desc)
            log("Posted Facebook Reel:", out["fb_reel"])
        except Exception as e:
            log("  Facebook Reel skipped:", str(e)[:200])
        try:                                     # the teaser on the page Story too (24 h, top of the feed)
            out["fb_story"] = extras.fb_post_story(teaser)
            if out["fb_story"]:
                log("Shared to Facebook Story:", out["fb_story"])
        except Exception as e:
            log("  Facebook Story skipped:", str(e)[:200])
    if teaser and env("INSTAGRAM") == "1":           # only if you switch Instagram on (secret INSTAGRAM = 1)
        try:
            out["ig_reel"] = extras.ig_post_reel(teaser, short_desc)
            log("Posted Instagram Reel:", out["ig_reel"])
        except Exception as e:
            log("  Instagram Reel skipped:", str(e)[:200])
    today = dt.datetime.now(extras.IST).date()
    done_today = any(h.get("coloring") and dt.datetime.fromisoformat(h["date"]).astimezone(extras.IST).date() == today
                     for h in history[-4:] if h.get("date"))
    if results.get("facebook") and env("COLORING") != "0" and not done_today and not CF_QUOTA_OUT:
        try:                                          # printable colouring page of today's main character
            main_c = next((c for c in story.get("characters", []) if c.get("look")), {})
            raw = os.path.join(WORK, "color_raw.jpg")
            prompt = ("black and white coloring book page for small children, clean thick black outlines only, no "
                      "shading, no grey, no colour, pure white background, simple cute shapes, full body: "
                      f"{ascii_text(main_c.get('look', ''))} {ascii_text(main_c.get('name', ''))}, happy pose, "
                      "a few simple background elements")
            with open(raw, "wb") as f:                # keep it portrait (no 16:9 frame)
                f.write(cf_request(CF_MODEL, prompt, w=768, h=1024, seed=random.randint(1, 99999)))
            page_img = extras.coloring_sheet(raw, os.path.join(WORK, "coloring.jpg"), FONT, L["color_title"])
            out["coloring"] = extras.fb_photo(page_img, f"{L['color_msg']}\n\n🎬 {title}")
            log("Posted colouring page:", out["coloring"])
        except Exception as e:
            log("  colouring page skipped:", str(e)[:200])
    if results.get("youtube"):
        try:
            extras.yt_add_to_playlist(results["youtube"], f"{L['labels'][category]} | {L['playlist_tail']}", lang)
            log("  added to YouTube playlist")
        except Exception as e:
            log("  playlist skipped:", str(e)[:200])
        if (teaser and extras.yt_extra_ok() and env("YT_SHORTS") != "0"
                and extras.shorts_today(history) < int(env("YT_SHORTS_PER_DAY") or 2)):
            try:
                desc = f"{title}\n{L['full_link']} https://youtu.be/{results['youtube']}\n{' '.join(tags[:6])}"
                out["yt_short"] = post_to_youtube(teaser, None, f"{title[:80]} #Shorts", desc, tags, lang)
                log("Posted YouTube Short:", out["yt_short"])
            except Exception as e:
                log("  YouTube Short skipped:", str(e)[:200])
    if results.get("facebook"):
        try:                                          # closed captions (CC) on the Facebook video
            extras.fb_add_captions(results["facebook"], segs, lang,
                                   {str(ln.get("text", "")).strip(): str(ln.get("en", "")).strip()
                                    for sc in story.get("scenes", []) for ln in sc.get("lines", []) if ln.get("en")})
        except Exception as e:
            log("  Facebook captions skipped:", str(e)[:160])
    if results.get("youtube") and extras.yt_extra_ok():
        try:                                          # English subtitles: more families can follow
            tr = {str(ln.get("text", "")).strip(): str(ln.get("en", "")).strip()
                  for sc in story.get("scenes", []) for ln in sc.get("lines", []) if ln.get("en")}
            srt = extras.write_srt(segs, tr, os.path.join(WORK, "subs_en.srt"))
            if srt:
                extras.yt_upload_captions(results["youtube"], srt)
                log("  English subtitles added on YouTube")
        except Exception as e:
            log("  subtitles skipped:", str(e)[:160])
    if results.get("facebook") and env("ANNOUNCE") != "0":
        try:                                          # "coming soon" post 2 hours before the evening video
            nxt = extras.next_slot([13, 19], [19])
            if nxt:
                slot, when, day = nxt
                words = f"{extras.DAY_WORDS[lang][day]} {extras.TIME_WORDS[lang][slot.hour]}"
                card = extras.announcement_card(ensure_mascot() or os.path.join(WORK, "thumb_base.jpg"), FONT,
                                                L["ann1"], words, os.path.join(WORK, "announce.jpg"),
                                                colors=((255, 225, 0), (255, 60, 120)))
                extras.fb_schedule_photo(card, L["ann_msg"].format(when=words), when)
                log(f"  'coming soon' post scheduled for {when.strftime('%d %b %H:%M')} India time")
        except Exception as e:
            log("  announcement skipped:", str(e)[:160])
    live = extras.wait_for_publish()
    if question and results.get("facebook"):
        try:
            extras.comment_when_live(results["facebook"], question, live)
            log("  first comment posted on Facebook")
        except Exception as e:
            log("  Facebook comment skipped (needs pages_manage_engagement):", str(e)[:160])
    # the 1-minute Reel / Short: its first comment links to the full story
    if out.get("fb_reel") and results.get("facebook"):
        try:
            extras.comment_when_live(out["fb_reel"], L["reel_comment"].format(
                link=f"https://www.facebook.com/{results['facebook']}"), live)
            log("  Reel comment with the full-story link posted")
        except Exception as e:
            log("  Reel comment skipped:", str(e)[:160])
    if out.get("yt_short") and results.get("youtube") and env("YT_MADE_FOR_KIDS") != "1":
        try:
            extras.yt_comment(out["yt_short"], L["reel_comment"].format(link=f"https://youtu.be/{results['youtube']}"))
            log("  Short comment with the full-story link posted")
        except Exception as e:
            log("  Short comment skipped:", str(e)[:160])
    # one riddle picture a day (made from today's video - no new AI picture)
    rd = story.get("riddle") if isinstance(story.get("riddle"), dict) else {}
    riddle_today = any(h.get("riddle_post") and dt.datetime.fromisoformat(h["date"]).astimezone(extras.IST).date() == today
                       for h in history[-5:] if h.get("date"))
    if rd.get("q") and rd.get("a") and results.get("facebook") and not riddle_today and env("RIDDLE") != "0":
        try:
            frame = os.path.join(WORK, "riddle_frame.jpg")
            run(["ffmpeg", "-y", "-ss", "40", "-i", video, "-frames:v", "1", frame])
            card = extras.riddle_card(frame, FONT, L["riddle_title"], str(rd["q"]), os.path.join(WORK, "riddle.jpg"))
            last = next((h for h in reversed(history) if h.get("riddle_post") and h.get("riddle")), None)
            msg = L["riddle_msg"].format(q=str(rd["q"]).strip())
            if last:
                msg = L["riddle_prev"].format(a=last["riddle"].get("a", "")) + "\n\n" + msg
            out["riddle_post"] = extras.fb_photo(card, msg)
            out["riddle"] = {"q": str(rd["q"]), "a": str(rd["a"])}
            log("Posted today's riddle:", out["riddle_post"])
        except Exception as e:
            log("  riddle post skipped:", str(e)[:160])
    return out


# ----------------------------------------------------------------- offline test helpers
def mock_story(lang):
    if env("MOCK_STORY"):                          # test run with a story from a file
        with open(env("MOCK_STORY"), encoding="utf-8") as f:
            return json.load(f)
    return {
        "title": "लालची बंदर और जादुई आम 🥭", "thumbnail_text": "लालची बंदर का सबक",
        "description": "एक बंदर को मिला जादुई आम का पेड़!\nआप होते तो क्या करते?",
        "hashtags": ["#HindiKahani", "#MoralStories"], "setting": "green jungle by a river, sunny morning",
        "characters": [{"name": "Chiku", "gender": "male", "age": "child", "kind": "animal", "look": "small brown monkey, red cap"},
                       {"name": "Meenu", "gender": "female", "age": "young", "kind": "animal", "look": "white rabbit, pink scarf"},
                       {"name": "Dadi", "gender": "female", "age": "old", "kind": "animal", "look": "old grey elephant, glasses"}],
        "thumbnail_image": {"characters": ["Chiku"], "action": "monkey holding a golden mango"},
        "scenes": [
            {"characters": ["Chiku", "Meenu"], "action": "play", "place": "river bank", "mood": "happy",
             "ambience": ["birds chirping in forest", "river stream"], "lines": [
                {"speaker": "narrator", "text": "एक घने जंगल में चीकू नाम का एक छोटा सा बंदर रहता था।", "emotion": "happy",
                 "sfx": [{"sound": "monkey chattering", "when": "after"}], "shot": "monkey on a tree"},
                {"speaker": "Meenu", "text": "चीकू! चलो नदी में खेलते हैं!", "emotion": "excited",
                 "sfx": [{"sound": "small footsteps running on grass", "when": "during"}], "shot": "rabbit running"},
                {"speaker": "Chiku", "text": "हाँ हाँ, मैं आ रहा हूँ!", "emotion": "laughing",
                 "sfx": [{"sound": "water splash", "when": "after"}], "shot": "monkey jumps in river"}]},
            {"characters": ["Dadi"], "action": "advice", "place": "big tree", "mood": "calm",
             "ambience": ["gentle wind in trees"], "lines": [
                {"speaker": "Dadi", "text": "बच्चों, लालच बुरी बला है।", "emotion": "calm", "sfx": [], "shot": "elephant smiling"}]},
        ],
        "moral": "लालच बुरी बला है।"}


def mock_image(path, seed):
    rnd = random.Random(seed + hash(path) % 1000)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=(20 + y // 30, 25 + y // 25, 40 + y // 18))
    d.rectangle([700, 260, 1100, 640], fill=(50, 45, 40), outline=(10, 10, 10), width=6)
    d.ellipse([rnd.randint(380, 520), 300, 600, 420], fill=(200, 200, 190), outline=(0, 0, 0), width=5)
    d.rectangle([420, 410, 580, 660], fill=(220, 220, 215), outline=(0, 0, 0), width=5)
    img.save(path, quality=90)
    return True


if __name__ == "__main__":
    main()
