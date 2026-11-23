# tvtoon - Bengali TV cartoon production system

`tvtoon` turns structured scene instructions into finished 2D cartoon video. It is separate from the daily horror bot: no production code imports it, and nothing in it publishes anything.

## Why the characters are drawn in code
Every character is a **layered vector puppet**. Each part is built from the character's locked identity sheet (`characters.py`): head, front and back hair, eyes, brows, nose, mouth, neck, torso, each arm in three parts with a five-finger hand, each leg in three parts, and the clothes.

This means:
- the character looks exactly the same in every frame;
- every joint bends without gaps, because the joints are drawn round and every hidden part exists;
- no AI mistakes such as three hands or a cut armpit;
- no Cloudflare and no image API: zero cost, unlimited renders.

## Pipeline (`production.py`, each stage has its own status and error)
| Stage | What happens |
|---|---|
| Design | the identity spec |
| Identity lock | the identity sheet |
| Asset generation | poses, face / eye / brow / mouth sheet, transparent PNG layers, SVG, JSON rig |
| Asset validation | `qa.py`, see below |
| Human approval | `approvals.json`, owner only |
| Rigging | the JSON rig exists |
| Animation test | the test clip |
| Lip-sync test | a voiced line |
| Scene integration | the 6-character scene |
| Rendering | the clips are rendered |
| Final export | blocked until approved |

## Modules
| File | What it does |
|---|---|
| `characters.py` | 12 original characters, 2 per category. The 6 samples are fully designed; the other 6 are briefs that wait for approval. |
| `puppet.py`, `rig.py`, `geom.py` | layered vector puppet; bones with parent-child transforms, pivots, FK and two-bone IK; hand shapes with 5 fingers |
| `face.py` | 7 eye states, 5 brows, 9 visemes (X, A, E, U, O, MBP, FV, LTD, WIDE), 8 expressions |
| `animator.py` | automatic performance; see the list below |
| `lipsync.py` | Bengali lip-sync; see the method below |
| `voices.py` | one voice per character (female voices for women and girls), cached per line |
| `scene.py` | scene JSON → timeline → performances → camera shots (wide / two-shot / close / follow, hard cuts) → subtitles → MP4; see the details below |
| `qa.py` | automatic validation; see the list below |
| `sheets.py` | identity, pose and face sheets; layer export |

**Automatic performance (`animator.py`).** These run on every frame without any keyframes:
- blinking at natural intervals, and eye darts;
- breathing and weight shifting;
- head motion and turning towards whoever is speaking;
- spring-driven hair and cloth;
- talk beats, gestures and listener reactions;
- walking, running, sitting and standing.

**Bengali lip-sync (`lipsync.py`).** This is a practical 9-viseme approximation, not phoneme recognition:
1. The Bengali text is split into syllables (aksharas).
2. Each syllable is mapped to consonant and vowel visemes.
3. The syllables are timed on the real audio: speech chunks are found, and every vowel is snapped to a loudness peak.

**Scene engine (`scene.py`).**
- Frame sizes: 1920×1080 or 1080×1920.
- Frame rates: 24 or 30 fps.
- An interrupted job resumes: it renders in chunks and keeps the chunks that are already finished.

**Validation (`qa.py`).** It checks:
- that the identity sheet is complete and the character really differs from every other one;
- 2 arms, 2 legs, 2 hands and 2 feet, with 5 fingers per hand shape;
- that every eye, brow, mouth and expression state looks different from the others;
- the measured proportions;
- the exported layers: transparent RGBA PNGs of one size, plus the SVG and JSON.

## Run
```
python -m tvtoon.production sample work/tvtoon_sample    # the sample pack (resumes)
python -m tvtoon.production status                       # dashboard
python -m pytest -q tests/test_tvtoon.py
```
On GitHub, use Actions → "TV Cartoon Sample Pack (6 characters)". It uses only the free voice key `GEMINI_TTS_KEY`.

## Scene instructions
```json
{"location": "village_courtyard", "aspect": "16:9", "fps": 24,
 "cast": [{"id": "lumi_didi", "x": 900}, {"id": "bappa", "x": 1500}],
 "beats": [{"who": "lumi_didi", "say": "বাপ্পা, তুমি কোথায় যাচ্ছ?", "to": "bappa"},
           {"who": "bappa", "say": "আমি মাঠে খেলতে যাচ্ছি।", "to": "lumi_didi", "emotion": "happy"},
           {"who": "bappa", "walk_to": 2600, "gait": "run"}]}
```
Other beats: `sit`, `stand`, `gesture` (wave, point, namaste, clap, shrug, explain, scared, think, hips), `emotion`, `face`, `pause`, `with_prev`, `shot`.

## Approval
Only the owner edits `tvtoon/approvals.json`, writing `USER_APPROVED` or `REJECTED` per character. The code only reads that file. An unapproved character is never production-ready. After the six samples are approved, the remaining six (`characters.PENDING`) are designed to the same standard.

## Known limits (honest)
- **Turns:** the three-quarter views are head turns. A true side view and a back view are not drawn yet (marked MISSING).
- **Locations:** only one location exists so far (village courtyard).
- **Voices:** in a run without the free voice key, female and child lines stay silent with subtitles. Only the men have existing recordings.
- **Lip-sync:** it is not perfect Bengali phoneme recognition.

## Engine v2: real movement (23 Nov 2026)
| File | What it does |
|---|---|
| `world.py` | animated, layered village; each layer has its own parallax factor, listed below |
| `animator.py` | character acting; see the list below |
| `scene.py` | camera v2 and story-driven shots; see the list below |
| `qa_motion.py` | measured on rendered frames; see the list below |

**Layers in `world.py`** (parallax factor in brackets; 1 is the ground the characters stand on, above 1 is in front of them):
- sky (0), with the time of day: day → golden hour → dusk → night, sun, moon and stars;
- clouds (0.06), drifting at different speeds;
- hills (0.18);
- birds (0.30), flapping;
- tree line (0.42);
- far palms (0.62);
- huts (0.85), with lamp glow and flicker at dusk, and cooking smoke;
- near palms and bananas (0.92), whose fronds move in a wind field with gusts and per-plant phase;
- fence (0.96);
- ground (1.0), with a pond and moving ripples;
- foreground grass and bushes (1.22), in front of the characters.

It also draws falling leaves, rain in three depths, fog, and shadows that lean with the sun.

**Character acting (`animator.py`):**
- head turns are springs, with overshoot and settle;
- gestures run pose-to-pose with anticipation, overshoot and follow-through (`gesture_weight`);
- listeners tilt their head toward the speaker and nod, and react after a delay;
- when a character points, the head and eyes follow the hand;
- the body acts the emotion:
  - surprise: a squash, then a jump with stretch;
  - laugh: the shoulders shake;
  - sad and crying: the shoulders drop, with sobs and tears;
  - fear: trembling and a lean back;
  - anger: a lean in, with fists;
- the face can be asymmetric (one brow higher), and the cheeks lift when smiling;
- every character blinks on its own clock.

**Camera (`scene.py`):**
- Shot types:
  - establishing pan;
  - wide;
  - full;
  - medium;
  - close-up;
  - extreme close-up;
  - over-the-shoulder;
  - two-shot;
  - reaction;
  - tracking, with lag and room to walk into.
- Shots change by hard cuts, or by eased camera moves (`"trans": "ease"`). There are never dissolves.
- Close shots soften the background (depth of field).
- Characters stand at different depths (`"z"` in the cast): farther ones are smaller and higher up.
- Shots are chosen automatically from the story:
  - the first exchange is a two-shot;
  - after that, the camera alternates between the speaker and an over-the-shoulder shot;
  - strong emotion gets a close-up, followed by a reaction shot of the listener;
  - a walk gets a tracking shot.
- Any beat can override the choice with `"shot"`.

**Motion checks (`qa_motion.py`).** It checks, from the rendered frames:
- that the background moves while huts and the ground stay put;
- the parallax order;
- character motion, with independent blinks;
- that the mouth shapes change while speaking;
- that open mouths fall inside the voice;
- the video itself: resolution, fps, length, no black frames, no dissolves, and jumps only at planned cuts.

**Voices.** Set with `TVTOON_VOICE=chirp|gemini|recorded`. The owner's rule (23 Nov 2026): every test uses Chirp 3 HD only (`GOOGLE_TTS_KEY`); the normal story mode uses the Gemini voice (`GEMINI_TTS_KEY`), which is also the default when `TVTOON_VOICE` is not set. On GitHub, `what = story_test` is the Chirp test and `what = story_episode` is the normal story mode with Gemini.

**Run.** `python -m tvtoon.production v2test <out>`.

**Limits of v2 (honest):**
- No true side view or back view: turns are three-quarter head and body turns, and "turning around" is a flip of direction.
- Chirp has no children's voices: children use the young male or female Chirp voice, pitched up by 12 %.
- Doors do not open yet.
- Only one location so far.

## Horror cast, places and vehicles (23 Nov 2026)
**Horror cast: 14 characters** (`characters.CAST_HORROR`), all passing `qa.validate`:
- **4 ghosts** (they float, glow, are see-through, and their feet fade): পেত্নী, শাঁকচুন্নি, ব্রহ্মদৈত্য, মেছো ভূত.
- **10 people:** ওঝা, শিবু দাদু, অভিষেক, রিয়া, পারুল বৌদি, মোক্ষদা ঠাকুমা, ভট্টাচার্য মশাই, রামু চৌকিদার, সায়ন, কিশোরী.

New hair styles: open_long, tiki, jata, crop, curly, bun_black. New details: beard, tilak, sindoor, sacred thread, rudraksha, shawl, torn clothes, glowing ghost eyes.

**8 places** (`locations.py`):

| Place | What moves |
|---|---|
| village courtyard | the original village layers |
| cremation ground | pyre with fire, sparks and smoke; owl; river with the moon's reflection |
| zamindar house | a lamp that flickers and goes out; bats |
| bamboo grove | three depths of swaying bamboo; mist; fireflies; moonbeams |
| pond ghat | ripples; lotus leaves; a lantern |
| railway station | trains on the track layer; the signal; lamps with moths; a Bengali name board |
| village road | paddy fields; poles and wires; a tea stall with steam |
| Kolkata street | tram lines and wires; windows that light up |

**7 vehicles** (`vehicles.py`): bus, tram, train, auto, toto, cycle and motorbike.
- Wheels turn with the distance travelled.
- They accelerate, cruise and brake.
- Headlights and windows light up at night, and exhaust comes out.
- A tram's pole sometimes sparks.

**Scene beats:**
- `{"vehicle": id, "drive_to": x, "sec": s}` drives a vehicle.
- `{"who": c, "ride": id, "seat": k}` and `{"who": c, "get_off": true}` put a character on a vehicle and take them off.
- `{"narrate": text}` adds a voice-over (narrator voice: Algenib).

**Episodes:** `production.render_episode()` joins scenes with a fade through black, so two scenes never mix. The test episode is "রাতের শর্টকাট": `python -m tvtoon.production horror <out>`.

**Limits:**
- Riders and drivers are drawn three-quarter on side-view vehicles. This is a cartoon convention, not true side views.
- (Fixed later the same day: bus and tram passengers now show in the windows, see below.)
- No doors open.

## Story to episode: automatic (23 Nov 2026)
`story.py` turns one of the bot's own stories (`assets/today_scripts.json`: its characters and its scenes with lines) into an episode. Nothing is invented: only what the story says is shown.

How it builds the episode:
- **Casting:** each story character gets an actor from the horror cast, chosen by ghost or human, gender and age. Each actor is used once. The story's own name is shown in the subtitles.
- **Place:** each scene gets a location from its place text, out of 9 places (the 8 above plus a room). The room has a window, a curtain moving in the wind, a door that opens, a lantern that can go out, and a ceiling fan.
- **Time and weather:** the time of day comes from the place text: day, dusk or night. Rain and fog come from its words too.
- **Dialogue:** lines become dialogue addressed to the right listener. Narrator lines become a voice-over. The story's emotions are mapped to the engine's acting.
- **Ghosts:** a ghost floats in. In a room, the door opens first.
- **Vehicles:** trains come into stations, trams cross Kolkata streets, totos pass on village roads.

Run it locally with `python -m tvtoon.production story latest <out>`. On GitHub, use the workflow with `what = story_episode`, `story_key` and `max_scenes`.

The episode spec is saved as JSON, so a wrong automatic choice can be edited by hand.

**Limits:** see the next section for travel scenes.

## True side view, rides and travel (23 Nov 2026)
Real TV animation and cinema show walking, cycling and two people talking face to face from the side. `profile.py` draws every character (all 20, from the same identity spec: proportions, colours, hair, costume, face details) in a **true side view**.

**The side view:**
- **Head in profile:** forehead, brow ridge, the character's own nose shape, lips, chin, jaw and ear; one eye with blinks, looks and lid states; the brow states; the visemes in profile, so the jaw really drops.
- **Walk and run:**
  - the four walk poses: contact, down, passing and up;
  - planted feet, tested for no sliding;
  - heel strike and toe-off;
  - knees bend forward;
  - the arms swing opposite the legs;
  - hip bob and a forward lean;
  - long hair, the braid and the saree's pallu trail behind.
- **Sitting sideways:** thighs forward, knees bent and feet on the floor (benches, seats).
- **Cycling:** hips on the saddle and feet on the turning pedals (IK on the real crank angle); hands on the handlebar and the body leaning forward.
- **Bike, auto and toto:** the driver holds the bars; passengers sit with their hands on their laps, on up to two passenger seats.
- **Looking back** (`{"who": c, "look_back": sec}`): the head turns over the shoulder while the body stays.
- **Gestures in profile:** explain, point, wave, scared, namaste, think, hands on hips and shrug.

**When the side view is used** (automatic). The turn goes through the three-quarter view (a spring), so there is no jump:
- walking and running;
- riding (from the first frame);
- sitting with `"side": true` (toward the partner), `"left"` or `"right"`;
- looking back;
- talking with `"view": "side"` in the cast, or `"talk_view": "side"` for the whole scene.

Ordinary conversations stay three-quarter, but turned clearly toward the partner, with the eyes on them.

**Inside vehicles** (`interiors.py`):
- **Places:** `train_inside` (train compartment), `bus_inside` and `tram_inside`.
- **Outside the windows:** three depths pass by, village or city, by day or night; at night, lights from outside sweep across the carriage.
- **The carriage itself:**
  - it sways and bumps (the rails' da-dum, bus bumps, the tram's clack), and the camera shares the motion;
  - fans turn and straps swing;
  - tube lights hum and can fail (`"flicker": [[t0, t1]]`), which is the horror moment;
  - inside, the carriage's own lamps light the people.

**Seen from outside:**
- Bus and tram passengers show in the windows: head and shoulders behind the glass, in profile.
- Auto and toto passengers sit IN the vehicle: its back is drawn behind them and its lower panel and wheels in front of their legs.
- A drive can run under the dialogue for the whole scene: `{"vehicle": id, "drive_to": x, "sec": "end", "background": true}`.

**Story to episode:**
- "compartment", "on the train", "inside the bus", "on the tram" and their Bengali words become the interiors, with the speakers facing each other.
- "auto", "toto" and "rickshaw" become a ride on the road.
- A ghost in a carriage makes the lights fail.
- A night story stays night: a scene whose place text names no time keeps the previous scene's time, and the first scene takes it from the story's title and logline.

**Travel test:** "রাতের যাত্রা" (`python -m tvtoon.production travel <out>`) shows:
- walking and looking back on a village road at dusk;
- a toto at night with three people in it;
- a cycle ride;
- a night bus with faces in the windows;
- talking face to face inside the bus;
- a Kolkata tram at dusk;
- a night train compartment where the lights fail.

**Fixes after the owner's review (23 Nov 2026):**
- Wheels and pedals turned backwards. They now turn forward, and this is tested for both directions.
- A cycle now fits its rider: a child gets a smaller cycle, so the feet really reach the pedals at the bottom of the stroke.
- Passengers seemed to sit in the air. Every side-sitting passenger now sits on a real seat drawn under them: a cushion, a seat box down to the floor and a high padded backrest behind the back, as in a compartment seen from the aisle. The long bench along the wall was removed.
- A rider who gets on at the start of a scene is on the vehicle from the first frame.

**Limits (honest):**
- There is no back view: a character walks to the left or right, never straight away into the depth.
- Turning goes front → three-quarter → side; there is no drawn in-between turn pose.
- Hands in the side view are simple mitten shapes.

## A ghost in disguise that changes (23 Nov 2026)
In many stories the ghost is not there at first, or it comes as an ordinary girl or man and only later shows its ghost form.

**How the bot's story drives it:** the story's `ghost_reveal` (`{name: scene number}`) says where the listeners learn the truth.
- **Before that scene:** the ghost comes in its disguise:
  - **female ghosts:** পেত্নী and শাঁকচুন্নি each have a designed ordinary-woman look (`characters.DISGUISE`): the same face and build, with living colours, tidy hair, ordinary eyes and no glow;
  - **male ghosts:** they are played by a human actor of their age, whose ghost form is that same man as a ghost (`<actor>__ghost`): the dead person himself.
- **In the reveal scene:** the disguise falls before the ghost's last line, or after its only line.
- **After that:** the ghost appears in its ghost form.

**The change** (`{"who": id, "transform": true}`, cast entry `"disguise": true`), about 1.8 seconds:
1. The eyes go wide, the head is thrown back, and a cold wind throws the hair about.
2. The light pulses dark; carriage lights fail and a lantern goes out.
3. The two forms flash in turn.
4. A cold flash, then a red vignette, as the ghost appears.
5. The ghost rises off the ground.

The camera pushes in close, then cuts wide. Everyone else is struck with fear. The voice stays the character's own.

**Test:** "অচেনা মেয়েটি" (`python -m tvtoon.production reveal <out>`, or `what = reveal_episode` on GitHub).

**Approval:** on 23 Nov 2026 at 15:30 IST, the owner wrote "USER_APPROVED" in chat. On his instruction, `approvals.json` now marks all 20 characters USER_APPROVED, each with a note saying so. The program itself still never writes approvals.

## Production: the horror story as a cartoon (23 Nov 2026)
The owner decided that from now on the horror story comes out as a cartoon. `horror-story.yml` sets `ANIM_MODE=tvtoon` by default; the repo variable `TVTOON_OFF = 1` goes back to the old pictures.

`tvtoon/bot.py` replaces only the pictures. Everything else is made by `main.py` as before: the story, the voices (Gemini), the sound, subtitles, thumbnail, the 9:16 version and the uploads.
- Every scene, and the cold-open hook, becomes a cartoon scene.
- Every line is placed at the exact time it is heard (`"at"`), with the bot's own clean line recording for the lip-sync.
- A ghost's change is finished before the line that follows it.
- The clips are encoded exactly like `main.py`'s own clips.
- `main.py`'s other uses of a scene picture (the title card, teasers) get a still of the cartoon scene, so no picture service is needed for the scenes.
- If a scene fails, `main.py` makes it the classic way.

Approval: the owner gave a standing approval in chat on 23 Nov 2026, so `approvals.json` has `"_all": USER_APPROVED`, which also covers new characters, disguises and ghost forms.

Speed: about 2.3 seconds of rendering per second of video on 2 cores at 1280×720, so a 15-minute story takes about 35 minutes. The run's time limit is 6 hours.

## Places change with the story (23 Nov 2026)
The owner saw every indoor scene come out as the same bedroom. `rooms.py` now gives 11 kinds of room plus the boat, and `story.place_of` and `story.room_kind` choose them from the place text:

| Kind | Example place text |
|---|---|
| bedroom | an old room, a quarter room |
| kitchen | clay stove with embers and smoke |
| hall | a palace or zamindar hall, with pillars, arches, a chequered floor, portraits and a chandelier |
| hospital | a ward with a flickering tube light |
| office / study | a desk, a table lamp and a bookshelf |
| studio | a radio or recording room |
| corridor | swinging bulbs |
| shed / store | light through the planks, tools |
| flat | a Kolkata flat with the city outside |
| hold | inside a boat; it rocks |
| palki | inside a palanquin; it sways |
| boat | on the river: waves, mangroves, the canopy, a swinging lantern, a storm, a palanquin on the deck |

**Other rules:**
- Within one story, the same kind of room keeps the same look.
- No rain falls inside a room.
- Inside a palanquin or a boat's hold, the people sit.
- "radio station" and "police station" are rooms, not railway stations; a railway cutting or track is a road.
- A speaker's name written in English letters is drawn with a Latin font, not as empty boxes.

## The Cartoon Studio: your story in, a finished episode out (23 Nov 2026)
`tvtoon/studio.py` is a real multi-agent pipeline on this engine. Each agent has its own job, reads only earlier agents' files and writes only its own. Each one checks its own output and has its own error handling.

The Production Manager (agent 01):
- runs the agents in dependency order;
- keeps one shared state, `episode_state.json`, the single source of truth: each agent's status, tries, time, inputs and outputs, and every error;
- retries a failed agent a limited number of times;
- resumes from the last successful checkpoint: an agent whose inputs did not change is not run again, so no voice, picture or render is paid for twice;
- sends Quality Control's failures back to the agent responsible, except the voices, which are never recorded twice.

| # | Agent | Reads | Writes |
|---|---|---|---|
| 02 | Story Analyst | story.txt | analysis.json: genre, mood, audience, people, places, times, weather, emotions |
| 03 | Scriptwriter | story, analysis | screenplay.json, screenplay.md. A script is kept line for line; prose becomes narration plus speech |
| 04 | Character Director | screenplay | casting.json: a library actor per role (gender, age, human or ghost), or a new supporting character saved in assets/characters, plus the registry |
| 05 | Location Designer | screenplay | locations.json: place, room, hour, light, weather, season |
| 06 | Background Artist | locations | assets/backgrounds/*.jpg, props.json |
| 07 | Storyboard Director | screenplay, casting, locations | scene_breakdown.json: placement, sitting and riding, shots, transitions; every line checked |
| 08 | Voice Director | breakdown, casting | audio/*.wav and voice_map.json: one voice per character, each line recorded once |
| 09 | Animation Director | breakdown | acting.json: entrances, gestures from the words |
| 10 | Environment Director | breakdown, locations | environment.json: wind, rain, fog; a rainy day is grey |
| 11 | Cinematographer | composed specs | scenes/*.mp4: camera, lip-sync, subtitles |
| 08b | Sound Designer | scenes, locations | scenes/*_mix.mp4: the place's ambience and music by mood |
| 11b | Editor | mixed scenes | final_episode.mp4: title card, fades or cuts, end card |
| 12 | Quality Control | everything | qc_report.md / .json; see the checks below |

Quality Control checks: character consistency, scene and background correctness, dialogue completeness, voices, lip-sync, resolution, fps, duration, audio, file integrity, black frames, and that the picture keeps moving.

**Run.**
- Locally: `python -m tvtoon.studio story.txt [out] --voice gemini|chirp|none [--portrait] [--max-scenes N]`.
- On GitHub: upload a `.txt` into `studio/inbox/` and the "Cartoon Studio" workflow starts by itself. The episode folder comes as an artifact.

**Voices and pictures.**
- Voices: the normal mode uses Gemini; `test` uses Chirp only.
- Gemini also helps the analyst and the scriptwriter when `GEMINI_API_KEY` is set (at most two calls to the free lite model). Without it, rules do the work offline.
- No picture service is used.

**New places:** market, temple, mountain, seaside and school (`outdoors.py`), and a classroom room kind.

**Casting:** the bot's own daily story uses the same casting rule. A role that no library actor suits gets a new character instead of a wrong one.

## The story moves the characters (actions.py, 23 Nov 2026)
Every line is read (Bengali, Hindi, English; the writer's `action`, the storyboard's `image.people` and the English
translation too) for what the body does: walk in, leave, run, run away, chase, come closer, fly (birds), sit, stand
up, jump, play, dance, fall, hide, look back, bow, namaste, wave, point, point up, clap, laugh, cry, think, shrug,
afraid, angry, bless, give, nod, shake the head; orders said to the listener ("sit down", "come here", "stand up").
Spoken words are not narration: "I will run" does not make anyone run. Whoever the story brings IN waits off screen
and walks / runs in at that line. bot.py puts the movements on the bot's own sound times.

## People face each other; the cinematic look
Talking people turn deep three-quarter to each other and stay turned between their lines. `look`: horror (cool
shadows, warm lamps, deep vignette, grain, bloom), kids (bright, warm, soft), film, flat (the plain TV cartoon);
repo variable TVTOON_LOOK. A slow hand-held drift on the camera.

## The place is alive (life.py)
By day: passers-by, children playing catch, shoppers at the market stalls, devotees at the temple. At night and in
horror after dusk: nobody. Extras are new faces, smaller and farther back, and never take the camera.

## Night character assets (prep.py) - both bots
Mode `assets` (horror 4 AM, cartoon 2 AM) does only this: the STORY SCOUT reads each written story and lists every
character the library lacks (no fitting actor, or a role the actor does not show: sadhu, priest, police, doctor,
king, queen, sahib) with a full brief; the CHARACTER ASSET BUILDER makes each one from the brief (base costume,
colours of each garment, hair, beard, glasses, role marks, height, build, skin), keeps the design most unlike every
existing face, checks it in front and side view, and saves it in `assets/tvtoon_library.json`. At video time the
casting (story.cast_story, kids.kids_cast) takes these first, by name (same gender / species).

## A voice that repeats itself (voicecheck.py)
Every recorded line is compared with itself; a stretch said again (twice, three times) is cut out with a cross-fade,
unless the words themselves repeat.

## The kids' cartoon bot (kids.py, kidsbot.py) - Sumonsham/hindi-story-bot
67 recurring characters (Gopal's court, Akbar-Birbal, Vikram-Betal, Lumi Didi + Mithu, Sumon, Sayan's family, Bhutu,
Tublu, Mini, Rimli + Bhola, Tukai + Bhulu, Didima, Pupu, Tatai, Robi, Jhilik, the gods and the epics) + 24 animal
species (animals.py) for Panchatantra / Jataka; aliases in Bengali, Hindi and English. ANIM_MODE=tvtoon in
daily-story.yml; every story scene, the hook and Lumi Didi's parts are cartoon scenes (plus a 9:16 render for
Facebook / Reels); quiz / lesson / word cards stay pictures.
