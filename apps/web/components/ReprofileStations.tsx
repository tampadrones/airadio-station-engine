"use client";

import { useState } from "react";

export default function ReprofileStations() {
  const [cohesion, setCohesion] = useState(85);
  const [lyricsMode, setLyricsMode] = useState("mixed");
  const [dryRun, setDryRun] = useState(true);
  const [status, setStatus] = useState("");

  const run = async () => {
    setStatus("Running...");
    try {
      const res = await fetch("/api/stations/reprofile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dry_run: dryRun,
          include_inferred_taste_hints: true,
          cohesion_spectrum: cohesion,
          lyrics_mode: lyricsMode,
        }),
      });
      if (!res.ok) {
        const details = await readErrorDetails(res);
        setStatus(`Failed (${res.status}): ${details}`);
        return;
      }
      const body = (await res.json()) as { updated_count?: number; items?: Array<{ changed?: boolean }> };
      const changed = (body.items || []).filter((x) => x.changed).length;
      setStatus(`${dryRun ? "Dry run" : "Applied"}: ${changed} changed, ${body.updated_count ?? 0} updated`);
    } catch {
      setStatus("Failed (network)");
    }
  };

  return (
    <section className="card">
      <h2>Reprofile Existing Stations</h2>
      <p className="muted">Bulk-refresh station profiles from current station identity and updated defaults.</p>
      <div className="grid" style={{ gap: 10 }}>
        <label>
          Flow / Cohesion: {cohesion}
          <input type="range" min={0} max={100} value={cohesion} onChange={(e) => setCohesion(Number(e.target.value))} />
        </label>
        <label>
          Lyrics mode
          <select value={lyricsMode} onChange={(e) => setLyricsMode(e.target.value)}>
            <option value="instrumental_only">Instrumental only</option>
            <option value="mixed">Mixed</option>
            <option value="vocal_forward">Vocal forward</option>
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          Dry run (preview only)
        </label>
        <button type="button" onClick={run}>
          Run Reprofile
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
