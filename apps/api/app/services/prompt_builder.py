from __future__ import annotations

import hashlib

from app.services.voice_profiles import format_voice_directive


def summarize_recent_tracks(items: list[dict]) -> str:
    if not items:
        return "No recent track history, establish station identity cleanly."
    parts = []
    for it in items[:3]:
        parts.append(
            f"{it.get('title','Untitled')} (energy={it.get('energy_score','n/a')}, bpm={it.get('bpm','n/a')}, texture={','.join(it.get('tags',[]))})"
        )
    return "; ".join(parts)


def _format_duration_clock(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def format_duration_clock(seconds: int) -> str:
    return _format_duration_clock(seconds)


def _genre_directives(genre: str) -> tuple[str, str]:
    g = (genre or "").lower()
    if any(token in g for token in ["rock", "hair", "glam", "arena", "hard rock", "metal"]):
        return (
            "Hard genre boundary: 80s arena/hair rock only. Prioritize distorted electric guitar riffs, live acoustic drums, "
            "electric bass groove, big chorus hooks, occasional guitar solo, and analog-era production.",
            "no trap hats, no 808 sub drops, no lofi vinyl haze, no synthwave arps, no ambient pads-only wash, no EDM risers, no hip-hop cadence",
        )
    if "synthwave" in g:
        return (
            "Hard genre boundary: synthwave only. Prioritize analog synth leads, retro drum machine groove, neon cinematic harmony, and 80s textures.",
            "no trap drums, no boom-bap hip-hop, no lofi tape wobble as primary texture, no acoustic folk strumming",
        )
    if any(token in g for token in ["lo-fi", "lofi", "chillhop"]):
        return (
            "Hard genre boundary: lo-fi/chill instrumental only. Prioritize warm chords, soft drums, low-intensity melodic movement, and restrained dynamics.",
            "no arena-rock vocals, no aggressive EDM drops, no trap banger cadence, no high-energy festival synth leads",
        )
    if "trap" in g:
        return (
            "Hard genre boundary: trap only. Prioritize modern trap drum programming, sub-driven low-end, minimal melodic motifs, and tight rhythmic pocket.",
            "no classic-rock guitar anthems, no synthwave nostalgia lead stacks, no lofi jazz harmony focus",
        )
    return (
        "Hard genre boundary: stay strictly inside the requested genre identity and instrumentation.",
        "avoid cross-genre drift into trap, synthwave, lofi, ambient-only textures, and unrelated production tropes",
    )


def _primary_topic(profile: dict, mood: str) -> str:
    topics = profile.get("topic_ideas", [])
    if isinstance(topics, list):
        for t in topics:
            text = str(t).strip()
            if text:
                return text
    return f"{mood} momentum"


def _influence_reference(profile: dict, personality: str, genre: str) -> str:
    tastes = profile.get("taste_hints", [])
    if isinstance(tastes, list):
        items = [str(x).strip() for x in tastes if str(x).strip()]
        if items:
            return ", ".join(items[:2])
    if personality.strip():
        return personality.strip()
    return genre


def _energy_level(profile: dict) -> str:
    score = int(profile.get("energy_variability", 30))
    if score <= 33:
        return "low-burn energy"
    if score <= 66:
        return "driving medium energy"
    return "high-octane energy"


def _technical_energy_level(profile: dict) -> str:
    score = int(profile.get("energy_variability", 30))
    if score <= 25:
        return "Low"
    if score <= 55:
        return "Medium"
    if score <= 85:
        return "High"
    return "Extreme"


def _structure_density(profile: dict, lyrics_mode: str) -> str:
    cohesion = int(profile.get("cohesion_spectrum", 80))
    discovery = int(profile.get("discovery_depth", 20))
    vocal_ratio = int(profile.get("vocal_ratio", 40))
    score = (cohesion * 0.35) + (discovery * 0.35) + (vocal_ratio * 0.3)
    if lyrics_mode == "instrumental_only":
        score -= 12
    if score < 38:
        return "Sparse"
    if score < 72:
        return "Balanced"
    return "Dense"


def _instrumentation_hint(genre: str) -> str:
    g = (genre or "").lower()
    if any(token in g for token in ["rock", "hair", "glam", "arena", "hard rock", "metal"]):
        return "distorted electric guitars, live drums, electric bass, singable chorus stack"
    if "synthwave" in g:
        return "analog synth leads, retro drum machines, pulsing bass arps, cinematic pads"
    if any(token in g for token in ["lo-fi", "lofi", "chillhop"]):
        return "dusty keys, soft drums, mellow bass, tape-warm textures"
    if "trap" in g:
        return "808 bass, crisp hats, sparse melodic motifs, punchy drums"
    return "genre-authentic instrumentation with clear hooks and radio-ready arrangement"


def _subgenre_tags(genre: str) -> str:
    g = (genre or "").lower()
    if "synthwave" in g:
        return "synthwave, retrowave, cinematic electronic"
    if "trap" in g or "rap" in g:
        return "trap, melodic rap, modern hip-hop"
    if "lo-fi" in g or "lofi" in g or "chillhop" in g:
        return "lo-fi, chillhop, downtempo"
    if "metal" in g:
        return "alternative metal, hard rock, heavy rock"
    if "rock" in g:
        return "rock, arena rock, alternative rock"
    if "trance" in g:
        return "trance, progressive trance, electronic"
    if "drum and bass" in g or "dnb" in g:
        return "drum and bass, liquid dnb, electronic"
    return genre or "contemporary"


def _dynamic_arc(mood: str, lyrics_mode: str) -> str:
    mood_key = str(mood).lower()
    if mood_key == "peak":
        return "direct intro -> high-pressure verse -> explosive chorus -> brief breakdown -> final surge"
    if mood_key == "release":
        return "soft intro -> open verse -> warm chorus -> spacious bridge -> fading outro"
    if mood_key == "rise":
        return "atmospheric intro -> tension build -> lift chorus -> focused bridge -> final rise"
    if lyrics_mode == "instrumental_only":
        return "motif intro -> layered build -> central hook -> textural break -> resolved outro"
    return "clear intro -> verse lift -> chorus payoff -> bridge contrast -> final chorus"


def _mix_texture(genre: str, profile: dict) -> str:
    g = (genre or "").lower()
    discovery = int(profile.get("discovery_depth", 20))
    if "synthwave" in g:
        return "glossy, wide stereo, neon ambience with tight low-end"
    if "trap" in g or "rap" in g:
        return "deep sub-forward, crisp transient detail, dark vocal space"
    if "lo-fi" in g or "lofi" in g:
        return "warm, dusty, close-mic texture with softened highs"
    if "rock" in g or "metal" in g:
        return "compressed guitars, punchy drums, wide chorus impact"
    if discovery >= 60:
        return "modern, detailed, high-contrast with controlled experimental edges"
    return "clean, balanced, broadcast-ready stereo image"


def _hook_direction(profile: dict) -> str:
    lyrics_mode = str(profile.get("lyrics_mode", "mixed"))
    if lyrics_mode == "instrumental_only":
        return "instrumental motif-led hook with memorable topline substitute"
    if lyrics_mode == "vocal_forward":
        return "big vocal hook with immediate singalong chorus payoff"
    return "balanced vocal/instrumental hook with strong repeat value"


def _production_style(profile: dict) -> str:
    cohesion = int(profile.get("cohesion_spectrum", 80))
    discovery = int(profile.get("discovery_depth", 20))
    if cohesion >= 75 and discovery <= 35:
        return "polished mainstream mix, tight arrangement discipline, broadcast-ready finish"
    if discovery >= 60:
        return "modern exploratory production with controlled risk and clear mix translation"
    return "clean radio mix with contemporary polish and moderate experimentation"


def build_music_caption_formula(
    *,
    genre: str,
    personality: str,
    mood: str,
    daypart: str,
    station_profile: dict | None = None,
    topic: str | None = None,
    voice_profile: dict | None = None,
    song_brief: dict | None = None,
) -> str:
    profile = station_profile or {}
    brief = song_brief if isinstance(song_brief, dict) else {}
    topic_value = str(brief.get("topic") or topic or _primary_topic(profile, mood)).strip()
    influence = _influence_reference(profile, personality, genre)
    energy = _energy_level(profile)
    texture = _mix_texture(genre, profile)
    hook = _hook_direction(profile)
    voice = format_voice_directive(voice_profile)
    vocal_style = f"{voice} {hook}".strip() if voice else hook
    setting = str(brief.get("setting") or f"{daypart} city-radio atmosphere")
    story = str(brief.get("hook_concept") or f"{topic_value} theme")
    rhythm = _rhythm_pace_for_genre(genre, daypart)

    # Required creative formula:
    # genre/style, influence/artist comparison, mood/energy, sonic texture,
    # theme/story, setting/visual imagery, vocal style, rhythm/pace.
    return (
        f"{genre}, {influence} inspired, {mood} mood with {energy}, "
        f"{texture}, {topic_value} theme with {story}, {setting}, {vocal_style}, {rhythm}"
    )


def _rhythm_pace_for_genre(genre: str, daypart: str) -> str:
    g = (genre or "").lower()
    if "trap" in g or "rap" in g:
        return "halftime trap pulse with tight syncopation"
    if "synthwave" in g:
        return "steady mid-tempo four-on-the-floor pulse"
    if "lo-fi" in g or "lofi" in g or "chillhop" in g:
        return "relaxed head-nod groove with soft swing"
    if "rock" in g or "metal" in g:
        return "driving live-band pace with strong downbeats"
    if "drum and bass" in g or "dnb" in g:
        return "fast breakbeat pace with rolling bass movement"
    if daypart in {"late_night", "night"}:
        return "measured late-night pulse with controlled momentum"
    return "radio-ready mid-tempo pulse"


def _technical_bpm(genre: str, daypart: str, profile: dict) -> int:
    g = (genre or "").lower()
    if "trap" in g or "rap" in g:
        lo, hi = 132, 156
    elif "synthwave" in g:
        lo, hi = 96, 122
    elif "lo-fi" in g or "lofi" in g or "chillhop" in g:
        lo, hi = 72, 96
    elif "rock" in g or "metal" in g:
        lo, hi = 108, 150
    elif "drum and bass" in g or "dnb" in g:
        lo, hi = 160, 176
    elif "trance" in g:
        lo, hi = 126, 140
    elif daypart in {"late_night", "night"}:
        lo, hi = 82, 112
    else:
        lo, hi = 92, 132
    energy = int(profile.get("energy_variability", 30))
    return int(round(lo + ((hi - lo) * max(0, min(100, energy)) / 100)))


def _technical_key(genre: str, mood: str, topic: str) -> str:
    g = (genre or "").lower()
    bright = str(mood).lower() in {"rise", "peak"}
    if "trap" in g or "rap" in g:
        pool = ["F Minor", "D Minor", "G Minor", "A Minor", "C Minor"]
    elif "synthwave" in g:
        pool = ["D Major", "A Minor", "E Minor", "G Major", "B Minor"]
    elif "lo-fi" in g or "lofi" in g:
        pool = ["C Major", "A Minor", "D Minor", "F Major", "E Minor"]
    elif "rock" in g or "metal" in g:
        pool = ["E Minor", "A Minor", "D Minor", "G Major", "B Minor"]
    else:
        pool = ["D Minor", "A Minor", "C Major", "G Major", "F# Minor"]
    if bright:
        pool = [k for k in pool if "Major" in k] + [k for k in pool if "Minor" in k]
    digest = hashlib.sha1(f"{genre}|{mood}|{topic}".encode("utf-8")).digest()
    return pool[digest[0] % len(pool)]


def build_technical_parameters(
    *,
    genre: str,
    mood: str,
    daypart: str,
    station_profile: dict | None = None,
    duration_sec: int | None = None,
    topic: str | None = None,
) -> dict[str, str]:
    profile = station_profile or {}
    lyrics_mode = str(profile.get("lyrics_mode", "mixed"))
    seconds = int(duration_sec if duration_sec is not None else profile.get("target_duration_sec", 320))
    topic_value = (topic or _primary_topic(profile, mood)).strip()
    return {
        "Key": _technical_key(genre, mood, topic_value),
        "BPM": str(_technical_bpm(genre, daypart, profile)),
        "Time Signature": "4/4",
        "Duration": _format_duration_clock(seconds),
        "Energy Level": _technical_energy_level(profile),
        "Structure Density": _structure_density(profile, lyrics_mode),
        "Subgenre Tags": _subgenre_tags(genre),
        "Instrumentation": _instrumentation_hint(genre),
        "Dynamic Arc": _dynamic_arc(mood, lyrics_mode),
        "Mix Texture": _mix_texture(genre, profile),
    }


def format_technical_parameters(params: dict[str, str]) -> str:
    required = ["Key", "BPM", "Time Signature", "Duration", "Energy Level", "Structure Density"]
    optional = ["Subgenre Tags", "Instrumentation", "Dynamic Arc", "Mix Texture"]
    lines = [f"{field}: {params[field]}" for field in required if params.get(field)]
    lines.extend(f"{field}: {params[field]}" for field in optional if params.get(field))
    return "\n".join(lines)


def format_song_brief(song_brief: dict | None) -> str:
    if not isinstance(song_brief, dict) or not song_brief:
        return ""
    fields = [
        ("Topic", "topic"),
        ("Angle", "angle"),
        ("Narrator", "narrator"),
        ("Setting", "setting"),
        ("Conflict", "conflict"),
        ("Emotional Turn", "emotional_turn"),
        ("Hook Concept", "hook_concept"),
        ("Chorus Strategy", "chorus_strategy"),
        ("Imagery Bank", "imagery_bank"),
        ("Forbidden Phrases", "forbidden_phrases"),
        ("Title Seed", "title_seed"),
    ]
    lines: list[str] = []
    for label, key in fields:
        value = song_brief.get(key)
        if isinstance(value, list):
            text = ", ".join(str(x).strip() for x in value if str(x).strip())
        else:
            text = str(value or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def build_song_concept_prompt(
    *,
    music_caption: str,
    technical_parameters: dict[str, str],
    lyrics: str | None = None,
    song_brief: dict | None = None,
    voice_profile: dict | None = None,
) -> str:
    brief_text = format_song_brief(song_brief)
    voice_text = format_voice_directive(voice_profile)
    brief_section = f"\n\nSONG BRIEF:\n{brief_text}" if brief_text else ""
    voice_section = f"\n\nVOICE DIRECTIVE:\n{voice_text}" if voice_text else ""
    return (
        "1) MUSIC CAPTION:\n"
        f"{music_caption}\n\n"
        "2) TECHNICAL PARAMETERS:\n"
        f"{format_technical_parameters(technical_parameters)}"
        f"{brief_section}"
        f"{voice_section}\n\n"
        "3) LYRICS:\n"
        f"{lyrics or ''}"
    ).strip()


def build_negative_prompt(*, genre: str, station_profile: dict | None = None, voice_profile: dict | None = None) -> str:
    _, exclusion = _genre_directives(genre)
    profile = station_profile or {}
    lyrics_mode = str(profile.get("lyrics_mode", "mixed"))
    lyric_constraint = "no vocals" if lyrics_mode == "instrumental_only" else "no mumble/incoherent topline"
    voice_terms = []
    if lyrics_mode != "instrumental_only" and isinstance(voice_profile, dict):
        voice_terms = [str(x).strip() for x in voice_profile.get("negative_prompt_terms", []) if str(x).strip()]
    voice_line = f"; {'; '.join(voice_terms)}" if voice_terms else ""
    return f"avoid obvious loops; {exclusion}; {lyric_constraint}{voice_line}; avoid clipping and silence"


def build_prompt(
    *,
    genre: str,
    personality: str,
    daypart: str,
    daypart_bias: str,
    mood: str,
    recent_tracks: list[dict],
    anti_repetition_notes: str,
    station_profile: dict | None = None,
    voice_profile: dict | None = None,
    song_brief: dict | None = None,
) -> str:
    profile = station_profile or {}
    cohesion = int(profile.get("cohesion_spectrum", 80))
    discovery = int(profile.get("discovery_depth", 20))
    lyrics_mode = str(profile.get("lyrics_mode", "mixed"))
    genre_mode = str(profile.get("genre_mode", "single_genre"))
    tastes = profile.get("taste_hints", [])
    topics = profile.get("topic_ideas", [])
    taste_line = ", ".join(tastes[:5]) if isinstance(tastes, list) and tastes else "none"
    topic_line = ", ".join(topics[:5]) if isinstance(topics, list) and topics else "none"
    vocal_instruction = {
        "instrumental_only": "Instrumental only. No vocals or sung hooks.",
        "mixed": "Balanced vocal/instrumental presence.",
        "vocal_forward": "Strong vocal-forward arrangement with clear topline.",
    }.get(lyrics_mode, "Balanced vocal/instrumental presence.")
    voice_directive = ""
    if lyrics_mode != "instrumental_only":
        voice_directive = format_voice_directive(voice_profile)
    boundary_instruction, _ = _genre_directives(genre)
    clean_lyrics = bool(profile.get("clean_lyrics_only", True))
    clean_line = "Lyrics must be clean/radio-safe language." if clean_lyrics else "Lyrics may include mature themes if musically appropriate."
    recent_summary = summarize_recent_tracks(recent_tracks)
    duration_sec = int(profile.get("target_duration_sec", 320))
    duration_clock = _format_duration_clock(duration_sec)
    brief_line = ""
    if isinstance(song_brief, dict) and song_brief:
        brief_line = (
            f"Song brief topic: {song_brief.get('topic', '')}. "
            f"Narrator: {song_brief.get('narrator', '')}. "
            f"Setting: {song_brief.get('setting', '')}. "
            f"Conflict: {song_brief.get('conflict', '')}. "
            f"Emotional turn: {song_brief.get('emotional_turn', '')}. "
            f"Hook concept: {song_brief.get('hook_concept', '')}. "
            f"Chorus strategy: {song_brief.get('chorus_strategy', '')}. "
        )
    formula_caption = build_music_caption_formula(
        genre=genre,
        personality=personality,
        mood=mood,
        daypart=daypart,
        station_profile=profile,
        voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
        song_brief=song_brief,
    )
    technical_parameters = build_technical_parameters(
        genre=genre,
        mood=mood,
        daypart=daypart,
        station_profile=profile,
        duration_sec=duration_sec,
    )
    return (
        f"1) MUSIC CAPTION: {formula_caption}. "
        f"2) TECHNICAL PARAMETERS: {format_technical_parameters(technical_parameters).replace(chr(10), '; ')}. "
        "3) LYRICS: enforce [INTRO], [VERSE 1], optional [PRE-CHORUS], [CHORUS], "
        "[VERSE 2], optional [PRE-CHORUS], [CHORUS], [BRIDGE], [FINAL CHORUS], [OUTRO]. "
        f"Generate a full, radio-ready {genre} track around {duration_clock}. "
        f"Station personality: {personality}. "
        f"Current daypart: {daypart} with bias: {daypart_bias}. "
        f"Mood arc state: {mood}. "
        f"Genre handling: {genre_mode}. "
        f"{boundary_instruction} "
        f"Cohesion target: {cohesion}/100. Discovery target: {discovery}/100. "
        f"User taste hints: {taste_line}. "
        f"Song topic ideas for upcoming vocal content: {topic_line}. "
        f"{vocal_instruction} "
        f"{voice_directive + ' ' if voice_directive else ''}"
        f"{brief_line}"
        "Translate the chosen topic into a concrete song premise with specific imagery, conflict, and setting; avoid generic momentum or city-light filler. "
        f"{clean_line} "
        f"Recent context: {recent_summary}. "
        f"Anti-repetition constraints: {anti_repetition_notes}. "
        "Output should feel broadcast-ready, musically coherent, and distinct from recent songs."
    )
