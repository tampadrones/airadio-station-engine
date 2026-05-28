from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Any


_GENERIC_FORBIDDEN = [
    "city lights",
    "we own the night",
    "never give up",
    "rise above",
    "feel alive",
    "in the moment",
    "through the noise",
    "signal stays strong",
    "right here right now",
    "no pause no fade",
]

_GENERIC_TOPIC_PHRASES = {
    "high energy",
    "low energy",
    "medium energy",
}

_GENERIC_TOPIC_TOKENS = {
    "baseline",
    "rise",
    "peak",
    "release",
    "momentum",
    "track",
    "song",
    "radio",
    "station",
    "energy",
}

_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "for",
    "with",
    "high",
    "low",
    "medium",
    "energy",
    "baseline",
    "rise",
    "peak",
    "release",
    "momentum",
    "track",
    "song",
    "radio",
    "station",
}

_TITLE_GENERIC_NOUNS = {
    "doorway",
    "night",
    "nights",
    "club",
    "late",
    "underground",
    "moment",
    "choice",
    "feeling",
    "story",
    "truth",
    "chance",
    "comfort",
}

_BASE_NARRATORS = [
    "first-person narrator trying to leave without being seen",
    "ex-friend who still remembers the exact route",
    "night-shift worker counting minutes by small sounds",
    "tour driver hearing the same argument through the wall",
    "back-row witness who knows why the room went quiet",
    "older sibling hiding panic behind practical advice",
    "runaway romantic narrating from the passenger seat",
    "club security guard recognizing an old name",
    "studio engineer who kept the mistake on tape",
    "bartender reading the ending before anyone says it",
    "burned-out performer talking to the exit sign",
    "commuter carrying a message they should delete",
    "neighbor listening through rain and thin drywall",
    "rookie hustler learning which praise is a trap",
    "former believer sorting faith from habit",
    "last-call regular who finally tells the real version",
    "younger self addressed like a difficult witness",
    "roadie patching cables while a promise breaks nearby",
    "late caller leaving one clean confession",
    "driver narrating the mile after the wrong turn",
    "person in the mirror rehearsing a different answer",
    "friend who stayed sober enough to remember",
    "housemate packing quietly during an argument",
    "stranger at the counter drawn into a private crisis",
    "singer returning to the town that learned their old name",
    "producer watching ambition change the room",
    "kid from the back block refusing the easy celebration",
    "ex-lover translating silence into evidence",
    "caretaker folding laundry beside a ringing phone",
    "door person stamping wrists like tiny verdicts",
    "anonymous rider missing stops on purpose",
    "witness in the green room after the applause cuts out",
]

_BASE_SETTINGS = [
    "coin laundry during a power flicker",
    "hospital vending machine alcove",
    "all-night pharmacy aisle",
    "closed mall fountain with dry coins",
    "subway stairs under a leaking sign",
    "hotel ice machine hallway",
    "county fair parking field after rain",
    "back porch with a loose screen door",
    "school gym after the lights click off",
    "underpass where the mural is half painted over",
    "airport smoking curb with dead phones",
    "freight elevator stuck between floors",
    "empty chapel beside a highway service road",
    "record store basement during inventory",
    "laundromat window facing traffic",
    "night bus with blue security bulbs",
    "rooftop stairwell behind a locked fire door",
    "warehouse office with one fan running",
    "motel pool drained for the season",
    "train platform with a broken arrivals board",
    "corner booth at a karaoke bar",
    "parking garage level painted in orange arrows",
    "pier arcade after the machines go dark",
    "community center kitchen after a wedding",
    "pawn shop counter under buzzing glass",
    "bus depot locker room",
    "empty terminal gate with rain on the glass",
    "rehearsal room smelling like old amplifiers",
    "delivery van outside a sleeping apartment block",
    "green room with a cracked mirror",
    "loading dock under sodium lights",
    "gas station car wash after closing",
    "studio couch covered in cable shadows",
    "taxi stand beside a shuttered flower stall",
    "high-school football field at midnight",
    "rooftop smoke area above a festival alley",
    "neon bathroom with marker on the mirror",
    "sunrise parking lot after the last set",
    "backstage tunnel between crowd noise and silence",
    "corner store freezer aisle",
    "empty garage with tire marks and phone echo",
    "storm highway rest stop",
    "broken green room behind a metal venue",
    "static-filled apartment with rain in the speaker",
    "elevator reflection between two bad floors",
    "glass skybridge over morning traffic",
    "ferry terminal bench before the first horn",
    "wristband table after the festival gates close",
]

_BASE_CONFLICTS = [
    "someone misses the last exit because an apology sounds like surrender",
    "two people pretend not to notice the packed bag by the door",
    "the room changes after a name appears on the phone",
    "a promise survives only if the narrator stops performing calm",
    "the narrator hides the proof inside a joke nobody laughs at",
    "one borrowed car turns a private argument into a deadline",
    "the safest plan would betray the person who trusted them",
    "every witness remembers a different version of the same minute",
    "money arrives with a condition that ruins the celebration",
    "a small lie has become the only thing holding the night together",
    "the old escape route now leads straight back to the problem",
    "the person who left the message is already in the room",
    "pride keeps asking for volume when the truth needs detail",
    "the narrator must choose between being believed and being kind",
    "the crowd wants a victory lap while the real loss waits outside",
    "an old nickname turns confidence into a trapdoor",
    "the evidence is ordinary enough that nobody else understands it",
    "forgiveness would cost more than leaving",
    "leaving would prove the accusation partly right",
    "the first honest sentence makes the practical plan impossible",
    "the person with the keys refuses to be the villain",
    "a replayed voicemail makes the room pick sides",
    "the narrator recognizes the warning because they caused it once",
    "the job offer, the apology, and the train all arrive together",
    "every easy answer sounds like a line from someone else's song",
    "a debt gets called in during the only peaceful hour",
    "the performance can continue only if nobody says the real subject",
    "the wrong person knows the right secret",
    "the shortcut home passes the place they promised to avoid",
    "a public win exposes a private compromise",
    "the narrator wants proof, then hates what proof requires",
    "a locked door protects them from the conversation they need",
    "the mirror version is braver than the person in the room",
    "the last quiet minute is interrupted by an old consequence",
    "the person they came to rescue has already chosen the fire",
    "the night keeps rewarding the behavior they are trying to quit",
    "a harmless favor becomes a test of loyalty",
    "the narrator hears love in the worst possible timing",
    "the plan depends on someone staying gone",
    "the chorus has to admit what the verses keep dodging",
    "a rumor becomes useful before it becomes true",
    "the exit is visible, but walking through it changes the narrator's name",
    "the city offers a clean start with dirty fingerprints on it",
    "the apology works only if nobody asks what happened next",
    "the win feels real until the person missing from it is named",
    "a quiet room asks for honesty louder than a crowd could",
]

_BASE_EMOTIONAL_TURNS = [
    "defiance softens into a request for one honest answer",
    "shame becomes useful information",
    "panic narrows into a clean instruction",
    "nostalgia turns suspect when the details sharpen",
    "anger becomes grief with better posture",
    "relief arrives before the problem is solved",
    "bravado drops into a private apology",
    "wanting to be right becomes wanting to be free",
    "fear changes from weather into a map",
    "loneliness becomes a standard the narrator refuses to lower",
    "the joke breaks and leaves the hurt visible",
    "temptation loses glamour when the bill is named",
    "confidence becomes care for someone still watching",
    "resentment becomes a boundary instead of a weapon",
    "the memory stops glowing and starts testifying",
    "the narrator mistakes calm for numbness until the hook corrects it",
    "escape fantasy becomes an address they can actually reach",
    "regret turns into a practical errand",
    "envy becomes admiration with teeth",
    "suspicion becomes mercy without becoming denial",
    "a private victory reveals its cost",
    "the hardest truth becomes the least dramatic sentence",
    "the body relaxes before the mind gives permission",
    "the old wound becomes a weather report, not a prophecy",
    "certainty cracks into a better question",
    "a fake smile gives way to exact language",
    "hope stops sounding innocent and starts sounding earned",
    "the narrator trades being impressive for being clear",
    "the silence changes from punishment into proof",
    "desire becomes discipline for one chorus",
]

_BASE_HOOK_CONCEPTS = [
    "the hook should feel like a receipt found in the wrong coat",
    "the hook repeats a changed address until it sounds like freedom",
    "the hook turns one ordinary object into the witness",
    "the chorus should feel like the elevator doors refusing to open",
    "the hook lands as a sentence the narrator can finally say twice",
    "the chorus makes the room answer back",
    "the hook uses a missed departure as the emotional downbeat",
    "the chorus treats the title like evidence, not a slogan",
    "the hook is a calm instruction over a dangerous pulse",
    "the chorus circles one image, then flips its meaning in the last line",
    "the hook should feel like headlights finding the hidden damage",
    "the chorus names the cost without explaining the whole case",
    "the hook turns restraint into the loudest move",
    "the chorus makes a private object sound public",
    "the hook starts as denial and ends as a dare",
    "the chorus should feel like the phone lighting up at the worst second",
    "the hook repeats what the narrator cannot afford to forget",
    "the chorus uses a place name as an emotional verdict",
    "the hook feels like a door code remembered too late",
    "the chorus makes the listener feel the choice before understanding it",
    "the hook turns a small superstition into a vow",
    "the chorus should hit like the first clear breath outside",
    "the hook keeps one phrase almost identical, then changes the subject",
    "the chorus sounds like a secret surviving daylight",
    "the hook makes the title an instruction to the body",
    "the chorus should feel handwritten on the back of a wristband",
    "the hook treats silence as the line everyone can sing",
    "the chorus turns a wrong turn into a ritual",
    "the hook should sound like glass vibrating in the next room",
    "the chorus makes the consequence feel chosen",
]

_BASE_CHORUS_STRATEGIES = [
    "open with a short fragment, then answer it with a concrete image",
    "repeat the title only at the end of the chorus",
    "let each chorus change one verb while keeping the image stable",
    "make the first line physical and the last line emotional",
    "use call-and-response between denial and admission",
    "start small in chorus one and make the final chorus public",
    "keep the melody phrase simple enough for a crowd, but avoid slogans",
    "make the chorus a scene change rather than a summary",
    "use the same object as proof in each chorus",
    "turn the pre-chorus question into the chorus answer",
    "make the second chorus contradict the first in one word",
    "hold the title until the final beat of the section",
    "let the hook phrase survive while the narrator's stance changes",
    "build the chorus around a command the narrator gives themselves",
    "use one sensory detail as the refrain anchor",
    "make the chorus sound like the consequence arriving",
    "leave one line unfinished until the final chorus completes it",
    "contrast a quiet first half with a blunt last line",
    "repeat a place image, then reveal why it matters",
    "make the chorus carry action instead of explanation",
    "avoid abstract triumph; let the concrete scene do the lift",
    "use a repeated question that becomes an answer",
    "put the strongest title phrase after the emotional turn",
    "make the final chorus change tense from wanting to doing",
    "let background voices echo only the object, not the moral",
]

_BASE_IMAGERY_BANK = [
    "blue exit lights",
    "paper wristband",
    "parking lot glass",
    "receipt ink",
    "rain on plexiglass",
    "elevator numbers",
    "marker on mirror",
    "coin return",
    "wet asphalt",
    "phone glow",
    "loose screen door",
    "static in the wall",
    "white vending hum",
    "cold coffee",
    "broken arrivals board",
    "orange garage arrows",
    "stamped wrist",
    "cable shadows",
    "service road dust",
    "neon soap",
    "torn setlist",
    "hotel ice",
    "bus depot tile",
    "headlight rain",
    "amp buzz",
    "security glass",
    "blacktop steam",
    "turnstile click",
    "lighter flare",
    "window condensation",
    "plastic roses",
    "ferry horn",
    "green room mirror",
    "train brake sparks",
    "roof gravel",
    "locker key",
    "dashboard dust",
    "stairwell smoke",
    "last-call lemon",
    "wrist stamp ink",
    "static apartment",
]

_ANGLE_TEMPLATES = {
    "action_first": [
        "someone misses the last exit because {topic} finally sounds like a warning",
        "two people leave the celebration early when {topic} stops feeling harmless",
        "the narrator hides the evidence of {topic} inside one practical errand",
        "a borrowed set of keys makes {topic} impossible to keep theoretical",
        "someone walks back into the room just as {topic} changes sides",
        "the driver keeps circling until {topic} becomes a decision, not a mood",
        "a late arrival forces {topic} into the open before anyone is ready",
        "the narrator returns the favor that made {topic} dangerous",
    ],
    "memory_first": [
        "the memory of {topic} starts with a sound nobody else noticed",
        "years later, {topic} is still tied to one fluorescent room",
        "an old message turns {topic} into a scene the narrator has to replay honestly",
        "the narrator remembers {topic} by the object left behind",
        "what looked like {topic} in the past becomes a different accusation tonight",
        "a childhood version of {topic} interrupts the adult plan",
        "the first version of {topic} was kinder, which is the problem",
        "the narrator misremembers {topic} until the chorus corrects the record",
    ],
    "metaphor_first": [
        "blue exit lights flicker over {topic} until escape looks borrowed",
        "static in the wall makes {topic} feel like a message from the next room",
        "a paper wristband turns {topic} into proof that daylight can ruin",
        "rain glass bends {topic} into something almost forgivable",
        "elevator numbers climb while {topic} stays stuck on the same floor",
        "a broken arrivals board gives {topic} the shape of a delayed confession",
        "neon soap and mirror ink make {topic} feel temporary but visible",
        "parking lot steam lifts {topic} into view for one chorus",
    ],
    "consequence_first": [
        "the room changes after {topic} names the person everyone avoided",
        "a promise survives only if {topic} loses its audience",
        "the win collapses when {topic} asks who paid for it",
        "the easiest future disappears once {topic} becomes specific",
        "nobody can go back to joking after {topic} moves into the room",
        "the chorus should feel like the bill for {topic} arriving early",
        "the narrator pays for {topic} by telling the smaller truth first",
        "what follows {topic} is quieter than revenge and harder to sing",
    ],
    "fragment": [
        "after the wristband, after the wrong door: {topic} with nowhere to hide",
        "one light left on, one bag by the wall, {topic} in plain view",
        "no grand speech, just {topic} under cheap glass and rain",
        "wrong floor, dead phone, {topic} waiting in the reflection",
        "a cold engine, a warm lie, {topic} almost out of time",
        "paper stamp sunrise: {topic} becomes the thing nobody washes off",
        "static on platform four, then {topic} says the quiet part",
        "blue exit lights, locked teeth, {topic} finally named",
    ],
}


def _ascii(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    text = normalized.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    return "".join(ch for ch in text if 32 <= ord(ch) <= 126)


def _clean_topic(value: str) -> str:
    raw = _ascii(value).lower()
    for phrase in _GENERIC_TOPIC_PHRASES:
        raw = re.sub(rf"\b{re.escape(phrase)}\b", " ", raw)
    words = re.findall(r"[a-z0-9']+", raw)
    stop = {"a", "an", "and", "or", "the", "for", "with", "music"} | _GENERIC_TOPIC_TOKENS
    kept = [w for w in words if w not in stop]
    return " ".join(kept[:7]) or "turning point"


def _recent_briefs(recent_generations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in recent_generations or []:
        if not isinstance(item, dict):
            continue
        brief = item.get("song_brief")
        if not isinstance(brief, dict):
            diagnostics = item.get("diagnostics", {})
            if isinstance(diagnostics, dict):
                brief = diagnostics.get("song_brief")
            if not isinstance(brief, dict):
                pre = item.get("preprocessor", {})
                diagnostics = pre.get("diagnostics", {}) if isinstance(pre, dict) else {}
                brief = diagnostics.get("song_brief") if isinstance(diagnostics, dict) else None
        if isinstance(brief, dict):
            out.append(brief)
    return out


def _used_values(recent_generations: list[dict[str, Any]] | None, field: str) -> set[str]:
    return {_ascii(brief.get(field, "")).lower() for brief in _recent_briefs(recent_generations) if _ascii(brief.get(field, ""))}


def _recent_weight_map(recent_generations: list[dict[str, Any]] | None, field: str) -> dict[str, int]:
    weights: dict[str, int] = {}
    for idx, brief in enumerate(_recent_briefs(recent_generations)):
        value = _ascii(brief.get(field, "")).lower()
        if not value:
            continue
        weights[value] = weights.get(value, 0) + max(8, 80 - (idx * 18))
    return weights


def _phrase_key(value: str) -> str:
    words = [
        w
        for w in re.findall(r"[a-z0-9']+", _ascii(value).lower())
        if w not in _TITLE_STOPWORDS and len(w) > 2
    ]
    return " ".join(words[:5])


def _genre_key(genre: str) -> str:
    g = (genre or "").lower()
    if "trap" in g or "rap" in g or "hip-hop" in g:
        return "trap"
    if any(token in g for token in ["edm", "trance", "house", "techno", "dance"]):
        return "edm"
    if any(token in g for token in ["ambient", "downtempo", "drone"]):
        return "ambient"
    if "synthwave" in g or "synthpop" in g:
        return "synthwave"
    if "lofi" in g or "lo-fi" in g or "chillhop" in g:
        return "lofi"
    if any(token in g for token in ["nu-metal", "numetal", "industrial", "deftones", "nine inch nails"]):
        return "nu_metal"
    if "rock" in g or "metal" in g or "punk" in g:
        return "rock"
    return "general"


def _pools(genre: str) -> dict[str, list[str]]:
    key = _genre_key(genre)
    common = {
        "angle": [template for templates in _ANGLE_TEMPLATES.values() for template in templates],
        "narrator": _BASE_NARRATORS,
        "setting": _BASE_SETTINGS,
        "conflict": _BASE_CONFLICTS,
        "emotional_turn": _BASE_EMOTIONAL_TURNS,
        "hook_concept": _BASE_HOOK_CONCEPTS,
        "chorus_strategy": _BASE_CHORUS_STRATEGIES,
        "imagery_bank": _BASE_IMAGERY_BANK,
    }
    genre_pools = {
        "edm": {
            "narrator": [
                "festival runner carrying news through crowd noise",
                "backstage wristband checker watching two worlds collide",
                "sunrise driver leaving the afterparty sober",
                "lighting tech seeing the breakdown before the drop",
            ],
            "setting": [
                "festival gate with torn wristbands underfoot",
                "backstage tunnel shaking from the main stage",
                "train platform still glowing after the last shuttle",
                "rooftop smoke area above a neon crowd",
                "neon bathroom with bass rattling the mirror",
                "sunrise parking lot full of idling rideshares",
                "VIP stairwell behind a curtain of fog",
                "empty merch tent after the encore",
            ],
            "conflict": [
                "euphoria keeps trying to outrun the conversation waiting after the set",
                "the drop arrives before the apology can",
                "a borrowed wristband gives the narrator access to the wrong truth",
                "the crowd moves as one while two people split apart",
                "the sunrise makes last night's promise sound legally binding",
            ],
            "emotional_turn": [
                "release turns into recognition under the last strobe",
                "ecstasy becomes accountability when the lights come up",
                "the build drops into stillness instead of escape",
            ],
            "hook_concept": [
                "the hook should feel like the bass cutting out for the confession",
                "the chorus turns the wristband into a clock",
                "the hook makes the crowd chant the thing the narrator avoided",
            ],
            "imagery_bank": [
                "paper wristband",
                "blue exit lights",
                "fog machine breath",
                "train platform static",
                "sunrise asphalt",
                "neon bathroom tile",
                "security stamp",
                "dropped earplug",
            ],
        },
        "trap": {
            "narrator": [
                "locked-in artist ignoring the couch talk",
                "driver watching traffic lights count pressure",
                "corner-store regular clocking fake loyalty",
                "studio friend who hears the ambition change",
            ],
            "setting": [
                "elevator with scratched brass doors",
                "corner store under a silent security camera",
                "studio couch beneath a dead wall clock",
                "traffic light on an empty arterial",
                "empty garage with oil shine on concrete",
                "locked-in studio after midnight",
                "rainy block outside a closed store",
                "dashboard glow near the last exit",
            ],
            "conflict": [
                "focus is threatened by debt, doubt, and fake loyalty",
                "one impulsive move could waste the whole run",
                "the room wants celebration before the work is finished",
                "every compliment arrives with a hidden invoice",
                "the narrator has to keep quiet long enough to win clean",
            ],
            "hook_concept": [
                "the hook lands like a decision made under pressure",
                "the hook turns restraint into the flex",
                "the hook repeats the move that changes the odds",
                "the chorus makes patience sound expensive",
            ],
            "imagery_bank": ["phone light", "wet pavement", "dashboard glow", "coded route", "quiet win", "locked door", "elevator chrome", "garage echo"],
        },
        "synthwave": {
            "setting": [
                "rain-slick overpass under violet signs",
                "empty arcade glowing after close",
                "chrome dashboard on an expressway loop",
                "video store return slot in blue rain",
                "glass skybridge above taillight rivers",
                "motel balcony facing a pink horizon",
            ],
            "conflict": [
                "the past keeps calling while the road demands a choice",
                "the message arrives after the exit is already missed",
                "speed hides the truth until the chorus names it",
                "the beautiful route is also the one that proves the lie",
            ],
            "hook_concept": [
                "the hook is the turn signal before the emotional crash",
                "the hook repeats the message the narrator cannot ignore",
                "the hook makes the escape feel romantic and dangerous",
            ],
            "imagery_bank": ["neon", "chrome", "arcade glass", "tail lights", "cassette hiss", "blue rain", "pink horizon", "video static"],
        },
        "ambient": {
            "narrator": [
                "half-awake observer measuring distance through reflections",
                "isolated tenant hearing static gather into meaning",
                "traveler waiting where announcements become weather",
                "quiet witness tracing a thought across glass",
            ],
            "setting": [
                "empty terminal with muted announcements",
                "rain glass beside a closed information desk",
                "elevator reflection stretching under fluorescent hum",
                "static-filled apartment before morning",
                "parking structure stairwell with no footsteps",
                "airport corridor where every gate is sleeping",
            ],
            "conflict": [
                "nothing dramatic happens, which makes the old fear easier to hear",
                "the narrator cannot tell whether the signal is memory or warning",
                "a reflection lags behind the person trying to leave",
                "silence keeps rearranging the meaning of one sentence",
            ],
            "emotional_turn": [
                "dread thins into attention",
                "absence becomes a shape the narrator can carry",
                "stillness stops feeling empty and starts feeling exact",
            ],
            "hook_concept": [
                "the hook should feel like a phrase appearing in condensation",
                "the chorus lets the room tone sing the missing answer",
                "the hook turns a reflection into a second narrator",
            ],
            "imagery_bank": ["empty terminal", "rain glass", "elevator reflection", "static apartment", "muted announcement", "fluorescent hum"],
        },
        "lofi": {
            "setting": ["desk lamp beside a rain-streaked window", "kitchen table before sunrise", "empty apartment with a humming laptop", "shared hallway where shoes dry by the heater"],
            "conflict": ["old thoughts keep circling until one detail breaks the loop", "the narrator wants peace but keeps rereading the evidence", "silence makes the unfinished conversation louder", "a small routine keeps proving what changed"],
            "hook_concept": ["the hook stays intimate and repeats a private object", "the hook resolves the thought without making it grand", "the hook lets one small image carry the feeling"],
            "imagery_bank": ["cup steam", "notebook margin", "window rain", "lamp hum", "soft dust", "morning edge"],
        },
        "nu_metal": {
            "setting": ["sealed hallway under a red exit sign", "fluorescent room with shaking glass", "concrete stairwell full of wire hum", "loading bay behind a locked venue"],
            "conflict": ["the exit keeps resetting every time the narrator reaches it", "the body remembers damage the mind tries to deny", "control tightens whenever the narrator names the truth", "the room rewards silence until the hook breaks it"],
            "hook_concept": ["the hook is a shouted command to break the loop", "the hook repeats the lock image until it cracks", "the hook turns panic into a physical release"],
            "imagery_bank": ["glass", "wire", "rust", "red light", "static", "breath", "fracture"],
        },
        "rock": {
            "setting": ["wide road under a hard storm front", "backstage hallway before the final set", "cracked asphalt outside a motel sign", "motel room with rain in the air conditioner", "loading dock behind a blown-out venue", "broken green room under one bare bulb"],
            "conflict": ["pride wants to run but the truth demands volume", "the narrator must choose between escape and repair", "the past catches up at full speed", "the loudest person in the room is scared of the quiet fact"],
            "hook_concept": ["the hook opens like a physical release", "the hook turns the title into a shouted vow", "the hook makes the consequence feel worth the burn"],
            "imagery_bank": ["thunder", "headlights", "smoke", "scar", "steel", "open road"],
        },
        "general": {
            "setting": ["late bus stop under weak streetlight", "small apartment during a weather shift", "empty diner booth after closing"],
            "conflict": ["one honest sentence could change the relationship", "the narrator has to act while the window is still open", "familiar comfort and exact truth ask for different futures"],
            "hook_concept": ["the hook repeats the choice in plain language", "the hook turns a concrete object into the title image", "the hook resolves the conflict without explaining it"],
            "imagery_bank": ["doorway", "weather", "hands", "receipt", "window", "last call"],
        },
    }
    selected = genre_pools.get(key, genre_pools["general"])
    out: dict[str, list[str]] = {}
    for field, base in common.items():
        combined = [*selected.get(field, []), *base]
        out[field] = list(dict.fromkeys(_ascii(item) for item in combined if _ascii(item)))
    out["angle_styles"] = list(_ANGLE_TEMPLATES.keys())
    return out


def _weighted_pick(
    options: list[str],
    *,
    label: str,
    seed: str,
    recent_generations: list[dict[str, Any]] | None,
    field: str,
    avoid: set[str] | None = None,
) -> str:
    if not options:
        return ""
    avoid = avoid or set()
    weights = _recent_weight_map(recent_generations, field)
    phrase_weights = {_phrase_key(value): weight for value, weight in weights.items() if _phrase_key(value)}
    digest = hashlib.sha1(f"{seed}|{label}|weighted|{len(options)}".encode("utf-8")).digest()
    start = digest[0] % len(options)
    ordered = options[start:] + options[:start]
    if digest[1] % 2:
        ordered = list(reversed(ordered))

    scored: list[tuple[int, int, str]] = []
    for order, item in enumerate(ordered):
        normalized = _ascii(item).lower()
        phrase = _phrase_key(item)
        penalty = weights.get(normalized, 0) + phrase_weights.get(phrase, 0)
        if normalized in avoid:
            penalty += 1_000
        jitter = hashlib.sha1(f"{seed}|{label}|{normalized}".encode("utf-8")).digest()[0]
        scored.append((penalty, jitter + order, item))
    return min(scored, key=lambda row: (row[0], row[1]))[2]


def _angle_templates_for_style(style: str) -> list[str]:
    return _ANGLE_TEMPLATES.get(style, []) or [template for templates in _ANGLE_TEMPLATES.values() for template in templates]


def _format_angle(template: str, topic: str) -> str:
    text = template.format(topic=topic)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_case(words: list[str]) -> str:
    small = {"on", "in", "at", "by", "for", "the"}
    return " ".join(word if idx and word in small else word.title() for idx, word in enumerate(words))


def _title_seed(
    topic: str,
    hook_concept: str,
    imagery_bank: list[str],
    setting: str,
    conflict: str,
    seed: str,
    recent_generations: list[dict[str, Any]] | None,
) -> str:
    digest = hashlib.sha1(f"{seed}|title".encode("utf-8")).digest()
    topic_words = {w for w in re.findall(r"[a-z0-9']+", topic.lower()) if w not in _TITLE_STOPWORDS}
    image_words = [
        w
        for image in imagery_bank
        for w in re.findall(r"[a-z0-9']+", str(image).lower())
        if w not in _TITLE_STOPWORDS and w not in _TITLE_GENERIC_NOUNS and len(w) > 2
    ]
    source_text = f"{setting} {conflict} {hook_concept}"
    source_words = [
        w
        for w in re.findall(r"[a-z0-9']+", source_text.lower())
        if w not in _TITLE_STOPWORDS
        and w not in _TITLE_GENERIC_NOUNS
        and w not in topic_words
        and len(w) > 2
    ]
    word_pool = list(dict.fromkeys([*image_words, *source_words]))
    if len(word_pool) < 4:
        word_pool.extend(["static", "platform", "wristband", "sunrise", "exit", "glass", "signal"])
    word_pool = list(dict.fromkeys(word_pool))

    colors = [w for w in word_pool if w in {"blue", "orange", "white", "green", "violet", "pink", "red"}] or ["blue", "white", "green"]
    places = [w for w in word_pool if w in {"platform", "garage", "terminal", "stairwell", "roof", "dock", "arcade", "mirror", "elevator"}] or ["platform", "stairwell", "terminal"]
    objects = [w for w in word_pool if w in {"wristband", "stamp", "receipt", "glass", "key", "setlist", "voicemail", "mirror", "static", "lighter"}] or word_pool[:5]
    times = [w for w in word_pool if w in {"sunrise", "morning", "midnight", "daylight"}] or ["sunrise", "midnight"]
    through_targets = [w for w in word_pool if w in {"neon", "rain", "static", "morning", "daylight", "fog", "smoke"}] or ["neon", "rain", "static"]
    numbers = ["4", "7", "12", "3"]

    def pick(items: list[str], offset: int) -> str:
        return items[digest[offset % len(digest)] % len(items)]

    candidates = [
        ["after", "the", pick(objects, 1)],
        [pick(colors, 2), pick(places, 3), "lights"],
        ["static", "on", pick(places, 4), pick(numbers, 5)],
        ["last", "train", "through", pick(through_targets, 6)],
        [pick(objects, 7), "stamp", pick(times, 8)],
        [pick(colors, 9), "exit", "lights"],
        [pick(objects, 10), "under", "glass"],
        ["platform", pick(numbers, 11), pick(times, 12)],
        ["after", pick(objects, 13), pick(times, 14)],
        [pick(colors, 15), pick(objects, 16), "sunrise"],
    ]

    recent_titles = [_ascii(brief.get("title_seed", "")).lower() for brief in _recent_briefs(recent_generations)]
    recent_prefixes = {title.split()[0] for title in recent_titles if title.split()}
    raw_topic = " ".join(sorted(topic_words))
    ordered = candidates[digest[0] % len(candidates) :] + candidates[: digest[0] % len(candidates)]
    for words in ordered:
        words = [w for w in words if w and (w not in _TITLE_STOPWORDS or w in {"after", "the", "on", "through", "under"})]
        content_words = [w for w in words if w not in {"after", "the", "on", "through", "under"}]
        if len(set(content_words)) != len(content_words):
            continue
        title = _ascii(_title_case(words[:6])).strip()
        lowered = title.lower()
        prefix = lowered.split()[0] if lowered.split() else ""
        if not title or lowered in recent_titles or prefix in recent_prefixes:
            continue
        if raw_topic and lowered.replace(" the ", " ") == raw_topic:
            continue
        return title
    fallback = _ascii(_title_case(["blue", "exit", "lights"]))
    return fallback if fallback.lower() not in recent_titles else "Paper Stamp Sunrise"


def build_song_brief(
    *,
    topic: str,
    genre: str,
    mood: str,
    daypart: str,
    station_profile: dict,
    recent_generations: list,
    voice_profile: dict | None = None,
    salt: str = "",
) -> dict:
    raw_topic = _ascii(topic)
    clean_topic = _clean_topic(topic)
    runtime_salt = salt or datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    voice_id = str((voice_profile or {}).get("id", ""))
    hints = "|".join(str(x) for x in (station_profile or {}).get("taste_hints", [])[:4])
    seed = f"{clean_topic}|{genre}|{mood}|{daypart}|{voice_id}|{hints}|{runtime_salt}"
    pools = _pools(genre)

    narrator = _weighted_pick(
        pools["narrator"],
        label="narrator",
        seed=seed,
        recent_generations=recent_generations,
        field="narrator",
        avoid=_used_values(recent_generations, "narrator"),
    )
    setting = _weighted_pick(
        pools["setting"],
        label="setting",
        seed=seed,
        recent_generations=recent_generations,
        field="setting",
        avoid=_used_values(recent_generations, "setting"),
    )
    conflict = _weighted_pick(
        pools["conflict"],
        label="conflict",
        seed=seed,
        recent_generations=recent_generations,
        field="conflict",
        avoid=_used_values(recent_generations, "conflict"),
    )
    hook_concept = _weighted_pick(
        pools["hook_concept"],
        label="hook",
        seed=seed,
        recent_generations=recent_generations,
        field="hook_concept",
        avoid=_used_values(recent_generations, "hook_concept"),
    )
    structure_mode = _weighted_pick(
        pools["angle_styles"],
        label="angle-style",
        seed=seed,
        recent_generations=recent_generations,
        field="structure_mode",
        avoid=_used_values(recent_generations, "structure_mode"),
    )
    angle_template = _weighted_pick(
        _angle_templates_for_style(structure_mode),
        label=f"angle-{structure_mode}",
        seed=seed,
        recent_generations=recent_generations,
        field="angle_template",
        avoid=_used_values(recent_generations, "angle_template"),
    )
    angle = _format_angle(angle_template, clean_topic)
    emotional_turn = _weighted_pick(
        pools["emotional_turn"],
        label="turn",
        seed=seed,
        recent_generations=recent_generations,
        field="emotional_turn",
        avoid=_used_values(recent_generations, "emotional_turn"),
    )
    chorus_strategy = _weighted_pick(
        pools["chorus_strategy"],
        label="chorus",
        seed=seed,
        recent_generations=recent_generations,
        field="chorus_strategy",
        avoid=_used_values(recent_generations, "chorus_strategy"),
    )

    imagery = list(dict.fromkeys(_ascii(x) for x in pools["imagery_bank"] if _ascii(x)))
    digest = hashlib.sha1(f"{seed}|imagery".encode("utf-8")).digest()
    if imagery:
        start = digest[0] % len(imagery)
        imagery = (imagery[start:] + imagery[:start])[:6]

    forbidden = list(_GENERIC_FORBIDDEN)
    for brief in _recent_briefs(recent_generations):
        hook = _ascii(brief.get("hook_concept", "")).lower()
        if hook:
            forbidden.append(hook[:80])

    out = {
        "raw_topic": raw_topic,
        "topic": clean_topic,
        "angle": angle,
        "narrator": narrator,
        "setting": setting,
        "conflict": conflict,
        "emotional_turn": emotional_turn,
        "hook_concept": hook_concept,
        "chorus_strategy": chorus_strategy,
        "imagery_bank": imagery,
        "forbidden_phrases": list(dict.fromkeys(_ascii(x).lower() for x in forbidden if _ascii(x))),
        "title_seed": _title_seed(clean_topic, hook_concept, imagery or ["signal"], setting, conflict, seed, recent_generations),
        "structure_mode": structure_mode,
        "angle_template": angle_template,
    }
    return {key: ([ _ascii(x) for x in value ] if isinstance(value, list) else _ascii(value)) for key, value in out.items()}
