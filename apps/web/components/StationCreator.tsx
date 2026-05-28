"use client";

import { useState } from "react";

type Props = {
  onCreated?: () => void;
};

export default function StationCreator({ onCreated }: Props) {
  const [name, setName] = useState("");
  const [genre, setGenre] = useState("");
  const [personality, setPersonality] = useState("Custom Host");
  const [cohesion, setCohesion] = useState(80);
  const [discovery, setDiscovery] = useState(20);
  const [lyricsMode, setLyricsMode] = useState("mixed");
  const [moodSeed, setMoodSeed] = useState("baseline");
  const [tasteHints, setTasteHints] = useState("");
  const [topicIdeas, setTopicIdeas] = useState("");
  const [status, setStatus] = useState<string>("");

  const submit = async () => {
    setStatus("Creating...");
    try {
      const res = await fetch("/api/stations/create-from-taste", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          genre,
          personality,
          cohesion_spectrum: cohesion,
          discovery_depth: discovery,
          lyrics_mode: lyricsMode,
          mood: moodSeed,
          taste_hints: tasteHints
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          topic_ideas: topicIdeas
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
        }),
      });
      if (!res.ok) {
        const details = await readErrorDetails(res);
        setStatus(`Failed (${res.status}): ${details}`);
        return;
      }
      const payload = (await res.json()) as { slug?: string };
      setStatus(`Created: ${payload.slug ?? "station"}`);
      setName("");
      setGenre("");
      setMoodSeed("baseline");
      setTasteHints("");
      setTopicIdeas("");
      onCreated?.();
    } catch {
      setStatus("Failed (network)");
    }
  };

  return (
    <section className="card">
      <h2>Create Custom Station</h2>
      <p className="muted">Default preset is Cohesive Radio. Tune vibe, flow, discovery, and lyric behavior up front.</p>
      <div className="grid" style={{ gap: 10 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Station name" />
        <input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="Genre (e.g. alt-rock, cloud rap)" />
        <input value={personality} onChange={(e) => setPersonality(e.target.value)} placeholder="Personality" />
        <label>
          Mood / Vibe
          <select value={moodSeed} onChange={(e) => setMoodSeed(e.target.value)}>
            <option value="baseline">Baseline (steady)</option>
            <option value="rise">Rise (build up)</option>
            <option value="peak">Peak (high intensity)</option>
            <option value="release">Release (cool down)</option>
          </select>
        </label>
        <label>
          Flow / Cohesion: {cohesion}
          <input type="range" min={0} max={100} value={cohesion} onChange={(e) => setCohesion(Number(e.target.value))} />
        </label>
        <label>
          Discovery / Exploratory: {discovery}
          <input type="range" min={0} max={100} value={discovery} onChange={(e) => setDiscovery(Number(e.target.value))} />
        </label>
        <label>
          Lyrics mode
          <select value={lyricsMode} onChange={(e) => setLyricsMode(e.target.value)}>
            <option value="instrumental_only">Instrumental only</option>
            <option value="mixed">Mixed</option>
            <option value="vocal_forward">Vocal forward</option>
          </select>
        </label>
        <label>
          Taste Hints
          <textarea
            value={tasteHints}
            onChange={(e) => setTasteHints(e.target.value)}
            placeholder="Comma-separated style hints (e.g. gritty, neon, cinematic, heavy 808s)"
            rows={2}
          />
        </label>
        <label>
          Topic Ideas
          <textarea
            value={topicIdeas}
            onChange={(e) => setTopicIdeas(e.target.value)}
            placeholder="Comma-separated lyric topics (e.g. boss fights, leveling up, late night grind)"
            rows={2}
          />
        </label>
        <button type="button" onClick={submit} disabled={!name || !genre}>
          Create Station
        </button>
        <p className="muted">{status}</p>
      </div>
    </section>
  );
}

async function readErrorDetails(res: Response): Promise<string> {
  try {
    const text = await res.text();
    if (!text) return "No response body";
    try {
      const parsed = JSON.parse(text) as { detail?: unknown; message?: unknown };
      const msg = parsed.detail ?? parsed.message;
      if (typeof msg === "string" && msg.trim()) return msg.trim();
      return text.slice(0, 240);
    } catch {
      return text.replace(/\s+/g, " ").slice(0, 240);
    }
  } catch {
    return "Unable to read error body";
  }
}
