"use client";

import { useEffect, useMemo, useState } from "react";

type Station = {
  slug: string;
  name: string;
};

type PreviewResponse = {
  station_slug: string;
  generated_at: string;
  daypart: string;
  mood: string;
  preprocessor: {
    source: string;
    diagnostics: Record<string, unknown>;
  };
  final: {
    prompt: string;
    music_caption?: string;
    technical_parameters?: Record<string, string>;
    negative_prompt: string;
    lyrics: string | null;
  };
  generator_payload: Record<string, unknown>;
};

type Props = {
  stations: Station[];
};

type PreviewItem = {
  ts: string;
  stationSlug: string;
  title: string;
  topic: string;
  lyricsSample: string;
};

type BackfillResponse = {
  ok: boolean;
  total_scanned: number;
  total_updated: number;
  stations: Array<{ slug: string; name: string; scanned: number; updated: number }>;
};

export default function GenerationPreview({ stations }: Props) {
  const sorted = useMemo(() => [...stations].sort((a, b) => a.name.localeCompare(b.name)), [stations]);
  const [selectedSlug, setSelectedSlug] = useState(sorted[0]?.slug ?? "");
  const [status, setStatus] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [history, setHistory] = useState<PreviewItem[]>([]);
  const [backfillStatus, setBackfillStatus] = useState("");
  const formatTechnicalParameters = (params?: Record<string, string>) => {
    const order = ["Key", "BPM", "Time Signature", "Duration", "Energy Level", "Structure Density", "Subgenre Tags", "Instrumentation", "Dynamic Arc", "Mix Texture"];
    return order
      .filter((key) => params?.[key])
      .map((key) => `${key}: ${params?.[key]}`)
      .join("\n");
  };

  const loadPreview = async (slug: string) => {
    if (!slug) return;
    setStatus("Generating preview...");
    setPreview(null);
    try {
      const res = await fetch(`/api/stations/${slug}/generation-preview`);
      if (!res.ok) {
        setStatus(`Failed (${res.status})`);
        return;
      }
      const payload = (await res.json()) as PreviewResponse;
      setPreview(payload);
      setStatus(`Preview ready (${payload.daypart}, ${payload.mood})`);
      const diagnostics = payload.preprocessor?.diagnostics || {};
      const title = String((diagnostics as Record<string, unknown>).suggested_title || "").trim() || "(no title)";
      const topic = String((diagnostics as Record<string, unknown>).song_topic || "").trim() || "(no topic)";
      const lyrics = (payload.final?.lyrics || "").trim();
      const firstLines = lyrics.split("\n").filter((x) => x.trim()).slice(0, 3).join(" / ");
      const item: PreviewItem = {
        ts: new Date().toISOString(),
        stationSlug: payload.station_slug,
        title,
        topic,
        lyricsSample: firstLines || "(instrumental / no lyrics)",
      };
      setHistory((prev) => [item, ...prev].slice(0, 5));
    } catch {
      setStatus("Failed (network)");
    }
  };

  const backfillTitles = async (slug: string) => {
    if (!slug) return;
    setBackfillStatus("Backfilling titles...");
    try {
      const res = await fetch("/api/stations/backfill-titles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ station_slugs: [slug], include_disabled: true, limit_per_station: 0 }),
      });
      if (!res.ok) {
        setBackfillStatus(`Backfill failed (${res.status})`);
        return;
      }
      const payload = (await res.json()) as BackfillResponse;
      const stationRow = payload.stations[0];
      if (!stationRow) {
        setBackfillStatus("Backfill complete (no matching station)");
        return;
      }
      setBackfillStatus(`Backfill complete: ${stationRow.updated} updated / ${stationRow.scanned} scanned`);
      void loadPreview(slug);
    } catch {
      setBackfillStatus("Backfill failed (network)");
    }
  };

  useEffect(() => {
    if (selectedSlug) {
      void loadPreview(selectedSlug);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSlug]);

  return (
    <section className="card">
      <h2>Generation Preview</h2>
      <p className="muted">Preview the exact payload sent to ACE-Step before generation.</p>
      <div className="grid" style={{ gap: 10 }}>
        <label>
          Station
          <select value={selectedSlug} onChange={(e) => setSelectedSlug(e.target.value)}>
            {sorted.map((s) => (
              <option key={s.slug} value={s.slug}>
                {s.name} ({s.slug})
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void loadPreview(selectedSlug)} disabled={!selectedSlug}>
          Refresh Preview
        </button>
        <button type="button" onClick={() => void backfillTitles(selectedSlug)} disabled={!selectedSlug}>
          Backfill Existing Titles
        </button>
        <p className="muted">{status}</p>
        <p className="muted">{backfillStatus}</p>

        {preview ? (
          <>
            <div>
              <strong>Music Caption</strong>
              <pre style={{ whiteSpace: "pre-wrap" }}>{preview.final.music_caption || preview.final.prompt}</pre>
            </div>
            <div>
              <strong>Technical Parameters</strong>
              <pre style={{ whiteSpace: "pre-wrap" }}>{formatTechnicalParameters(preview.final.technical_parameters) || "(none)"}</pre>
            </div>
            <div>
              <strong>Full Song Concept</strong>
              <pre style={{ whiteSpace: "pre-wrap" }}>{preview.final.prompt}</pre>
            </div>
            <div>
              <strong>Negative Prompt</strong>
              <pre style={{ whiteSpace: "pre-wrap" }}>{preview.final.negative_prompt}</pre>
            </div>
            <div>
              <strong>Lyrics</strong>
              <pre style={{ whiteSpace: "pre-wrap" }}>{preview.final.lyrics || "(instrumental / no lyrics)"}</pre>
            </div>
            <div>
              <strong>Generator Payload JSON</strong>
              <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(preview.generator_payload, null, 2)}</pre>
            </div>
            <div>
              <strong>Preprocessor</strong>
              <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(preview.preprocessor, null, 2)}</pre>
            </div>
          </>
        ) : null}
        <div>
          <strong>Last 5 Previews</strong>
          {history.length === 0 ? (
            <p className="muted">No preview history yet.</p>
          ) : (
            <ul className="track-list">
              {history.map((h, idx) => (
                <li key={`${h.ts}-${idx}`} className="track-row">
                  <span className="track-title">
                    {h.stationSlug}: {h.title}
                  </span>
                  <span className="track-meta">{h.topic}</span>
                </li>
              ))}
            </ul>
          )}
          {history.length > 0 ? (
            <pre style={{ whiteSpace: "pre-wrap" }}>{history.map((h) => `${h.stationSlug} | ${h.title} | ${h.lyricsSample}`).join("\n")}</pre>
          ) : null}
        </div>
      </div>
    </section>
  );
}
