"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type Station = {
  slug: string;
  name: string;
  genre: string;
  personality: string;
  description: string;
  is_enabled: boolean;
  station_profile: Record<string, unknown>;
  target_queue_depth: number;
  min_ready_tracks: number;
};

type Props = {
  stations: Station[];
};

type FormState = {
  name: string;
  genre: string;
  personality: string;
  description: string;
  isEnabled: boolean;
  targetQueueDepth: number;
  minReadyTracks: number;
  genreMode: string;
  lyricsMode: string;
  moodSeed: string;
  cleanLyricsOnly: boolean;
  cohesion: number;
  discovery: number;
  moodVolatility: number;
  energyVariability: number;
  vocalRatio: number;
  targetDurationSec: number;
  durationJitterSec: number;
  durationMinSec: number;
  durationMaxSec: number;
  tasteHints: string;
  topicIdeas: string;
};

function Help({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (rootRef.current?.contains(target)) return;
      setOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
    };
  }, [open]);

  return (
    <span ref={rootRef} style={{ position: "relative", display: "inline-flex", marginLeft: 6 }}>
      <button
        type="button"
        aria-label="Show setting help"
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 18,
          height: 18,
          borderRadius: 999,
          border: "1px solid #666",
          fontSize: 12,
          cursor: "pointer",
          background: "transparent",
          color: "inherit",
          padding: 0,
          lineHeight: 1,
        }}
      >
        ?
      </button>
      {open ? (
        <span
          role="tooltip"
          style={{
            position: "absolute",
            top: 22,
            left: 22,
            zIndex: 20,
            minWidth: 240,
            maxWidth: 360,
            padding: "8px 10px",
            borderRadius: 8,
            border: "1px solid #444",
            background: "#121212",
            color: "#f5f5f5",
            fontSize: 12,
            lineHeight: 1.4,
            boxShadow: "0 6px 20px rgba(0,0,0,0.35)",
          }}
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}

function toForm(st: Station): FormState {
  const p = st.station_profile || {};
  const taste = Array.isArray(p.taste_hints) ? p.taste_hints : [];
  const topics = Array.isArray(p.topic_ideas) ? p.topic_ideas : [];
  return {
    name: st.name,
    genre: st.genre,
    personality: st.personality,
    description: st.description,
    isEnabled: !!st.is_enabled,
    targetQueueDepth: Number(st.target_queue_depth || 5),
    minReadyTracks: Number(st.min_ready_tracks || 3),
    genreMode: String(p.genre_mode || "single_genre"),
    lyricsMode: String(p.lyrics_mode || "mixed"),
    moodSeed: String(p.mood_seed || "baseline"),
    cleanLyricsOnly: Boolean(p.clean_lyrics_only ?? true),
    cohesion: Number(p.cohesion_spectrum ?? 80),
    discovery: Number(p.discovery_depth ?? 20),
    moodVolatility: Number(p.mood_volatility ?? 30),
    energyVariability: Number(p.energy_variability ?? 30),
    vocalRatio: Number(p.vocal_ratio ?? 40),
    targetDurationSec: Number(p.target_duration_sec ?? 320),
    durationJitterSec: Number(p.duration_jitter_sec ?? 12),
    durationMinSec: Number(p.duration_min_sec ?? 320),
    durationMaxSec: Number(p.duration_max_sec ?? 320),
    tasteHints: taste.map((x) => String(x)).join(", "),
    topicIdeas: topics.map((x) => String(x)).join(", "),
  };
}

export default function StationSettingsEditor({ stations }: Props) {
  const router = useRouter();
  const sorted = useMemo(() => [...stations].sort((a, b) => a.name.localeCompare(b.name)), [stations]);
  const [selectedSlug, setSelectedSlug] = useState(sorted[0]?.slug ?? "");
  const [status, setStatus] = useState("");
  const [form, setForm] = useState<FormState>(() => (sorted[0] ? toForm(sorted[0]) : toForm({
    slug: "",
    name: "",
    genre: "",
    personality: "",
    description: "",
    is_enabled: true,
    station_profile: {},
    target_queue_depth: 5,
    min_ready_tracks: 3,
  })));

  const selected = sorted.find((s) => s.slug === selectedSlug);

  const onSelect = (slug: string) => {
    setSelectedSlug(slug);
    const st = sorted.find((s) => s.slug === slug);
    if (st) setForm(toForm(st));
  };

  const save = async () => {
    if (!selectedSlug) return;
    setStatus("Saving...");
    try {
      const res = await fetch(`/api/stations/${selectedSlug}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          genre: form.genre,
          personality: form.personality,
          description: form.description,
          is_enabled: form.isEnabled,
          target_queue_depth: form.targetQueueDepth,
          min_ready_tracks: form.minReadyTracks,
          genre_mode: form.genreMode,
          lyrics_mode: form.lyricsMode,
          mood_seed: form.moodSeed,
          clean_lyrics_only: form.cleanLyricsOnly,
          cohesion_spectrum: form.cohesion,
          discovery_depth: form.discovery,
          mood_volatility: form.moodVolatility,
          energy_variability: form.energyVariability,
          vocal_ratio: form.vocalRatio,
          target_duration_sec: form.targetDurationSec,
          duration_jitter_sec: form.durationJitterSec,
          duration_min_sec: form.durationMinSec,
          duration_max_sec: form.durationMaxSec,
          taste_hints: form.tasteHints
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          topic_ideas: form.topicIdeas
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
      setStatus("Saved");
      router.refresh();
    } catch {
      setStatus("Failed (network)");
    }
  };

  if (!selected) {
    return (
      <section className="card">
        <h2>Station Settings</h2>
        <p className="muted">No stations available.</p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>Station Settings</h2>
      <p className="muted">Edit each station profile and save immediately.</p>
      <div className="grid" style={{ gap: 10 }}>
        <label>
          Station
          <select value={selectedSlug} onChange={(e) => onSelect(e.target.value)}>
            {sorted.map((s) => (
              <option key={s.slug} value={s.slug}>
                {s.name} ({s.slug})
              </option>
            ))}
          </select>
        </label>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Name" />
        <input value={form.genre} onChange={(e) => setForm({ ...form, genre: e.target.value })} placeholder="Genre" />
        <input value={form.personality} onChange={(e) => setForm({ ...form, personality: e.target.value })} placeholder="Personality" />
        <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Description" rows={3} />
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={form.isEnabled} onChange={(e) => setForm({ ...form, isEnabled: e.target.checked })} />
          Enabled
        </label>
        <label>
          Target Queue Depth
          <input type="number" min={1} max={100} value={form.targetQueueDepth} onChange={(e) => setForm({ ...form, targetQueueDepth: Number(e.target.value) })} />
        </label>
        <label>
          Min Ready Tracks
          <input type="number" min={0} max={50} value={form.minReadyTracks} onChange={(e) => setForm({ ...form, minReadyTracks: Number(e.target.value) })} />
        </label>
        <div>
          Genre mode
          <Help text="Single Genre keeps strict style boundaries. Genre Blend allows controlled crossover. Open Format allows widest style drift." />
          <label style={{ display: "block" }}>
          <select value={form.genreMode} onChange={(e) => setForm({ ...form, genreMode: e.target.value })}>
            <option value="single_genre">Single Genre</option>
            <option value="genre_blend">Genre Blend</option>
            <option value="open_format">Open Format</option>
          </select>
          </label>
        </div>
        <div>
          Lyrics mode
          <Help text="Instrumental only disables lyrics. Mixed allows both instrumental and vocal. Vocal forward prioritizes sung/topline content." />
          <label style={{ display: "block" }}>
          <select value={form.lyricsMode} onChange={(e) => setForm({ ...form, lyricsMode: e.target.value })}>
            <option value="instrumental_only">Instrumental only</option>
            <option value="mixed">Mixed</option>
            <option value="vocal_forward">Vocal forward</option>
          </select>
          </label>
        </div>
        <div>
          Mood preset
          <Help text="Sets the overall vibe for newly generated songs and lyrics. Pick the tone you want this station to feel like most of the time." />
          <label style={{ display: "block" }}>
          <select value={form.moodSeed} onChange={(e) => setForm({ ...form, moodSeed: e.target.value })}>
            <option value="baseline">Steady / Neutral</option>
            <option value="rise">Building / Motivated</option>
            <option value="peak">Intense / Hype</option>
            <option value="release">Cooldown / Reflective</option>
          </select>
          </label>
          <p className="muted">Example: `GG` usually fits `Building` or `Intense`; an `80s rock` station can live in `Steady` with occasional `Intense`.</p>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={form.cleanLyricsOnly} onChange={(e) => setForm({ ...form, cleanLyricsOnly: e.target.checked })} />
          Clean lyrics only
        </label>
        <div>
          Cohesion: {form.cohesion}
          <Help text="Lower values increase variation between songs. Higher values keep songs stylistically consistent with station identity." />
          <label style={{ display: "block" }}>
          <input type="range" min={0} max={100} value={form.cohesion} onChange={(e) => setForm({ ...form, cohesion: Number(e.target.value) })} />
          </label>
        </div>
        <div>
          Discovery: {form.discovery}
          <Help text="Lower values stay close to known station sound. Higher values explore newer textures/arrangements within constraints." />
          <label style={{ display: "block" }}>
          <input type="range" min={0} max={100} value={form.discovery} onChange={(e) => setForm({ ...form, discovery: Number(e.target.value) })} />
          </label>
        </div>
        <div>
          Mood Volatility: {form.moodVolatility}
          <Help text="Lower values keep emotional tone stable. Higher values allow faster mood swings between tracks." />
          <label style={{ display: "block" }}>
          <input type="range" min={0} max={100} value={form.moodVolatility} onChange={(e) => setForm({ ...form, moodVolatility: Number(e.target.value) })} />
          </label>
        </div>
        <div>
          Energy Variability: {form.energyVariability}
          <Help text="Lower values keep loudness/intensity stable. Higher values permit bigger jumps from mellow to intense songs." />
          <label style={{ display: "block" }}>
          <input type="range" min={0} max={100} value={form.energyVariability} onChange={(e) => setForm({ ...form, energyVariability: Number(e.target.value) })} />
          </label>
        </div>
        <div>
          Vocal Ratio: {form.vocalRatio}
          <Help text="Lower values bias toward instrumental tracks. Higher values bias toward vocal tracks." />
          <label style={{ display: "block" }}>
          <input type="range" min={0} max={100} value={form.vocalRatio} onChange={(e) => setForm({ ...form, vocalRatio: Number(e.target.value) })} />
          </label>
        </div>
        <div>
          Target Song Length: {form.targetDurationSec}s
          <Help text="Target duration used for generation. The engine still applies controlled variation around this value." />
          <label style={{ display: "block" }}>
          <input type="range" min={150} max={320} value={form.targetDurationSec} onChange={(e) => setForm({ ...form, targetDurationSec: Number(e.target.value) })} />
          </label>
        </div>
        <div>
          Length Variability: +/-{form.durationJitterSec}s
          <Help text="How far generated tracks may drift from the target song length." />
          <label style={{ display: "block" }}>
          <input type="range" min={0} max={45} value={form.durationJitterSec} onChange={(e) => setForm({ ...form, durationJitterSec: Number(e.target.value) })} />
          </label>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <label>
            Min Length (s)
            <input type="number" min={120} max={320} value={form.durationMinSec} onChange={(e) => setForm({ ...form, durationMinSec: Number(e.target.value) })} />
          </label>
          <label>
            Max Length (s)
            <input type="number" min={120} max={320} value={form.durationMaxSec} onChange={(e) => setForm({ ...form, durationMaxSec: Number(e.target.value) })} />
          </label>
        </div>
        <div>
          Taste hints
          <Help text="Comma-separated sonic guidance keywords. Influences arrangement, instrumentation, and production direction." />
          <label style={{ display: "block" }}>
          <input value={form.tasteHints} onChange={(e) => setForm({ ...form, tasteHints: e.target.value })} placeholder="Taste hints (comma-separated)" />
          </label>
        </div>
        <div>
          Topic ideas
          <Help text="Comma-separated lyrical/topic ideas for upcoming generated tracks. Lower count keeps themes focused; higher count broadens themes." />
          <label style={{ display: "block" }}>
          <input value={form.topicIdeas} onChange={(e) => setForm({ ...form, topicIdeas: e.target.value })} placeholder="Topic ideas (comma-separated)" />
          </label>
        </div>
        <button type="button" onClick={save}>
          Save Station Settings
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
