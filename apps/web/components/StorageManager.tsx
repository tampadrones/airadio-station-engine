"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

type Station = {
  slug: string;
  name: string;
};

type Props = {
  stations: Station[];
};

function formatBytesGbMb(value: unknown): string {
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num) || num < 0) return String(value);
  return `${(num / 1_000_000_000).toFixed(2)} GB (${(num / 1_000_000).toFixed(2)} MB)`;
}

export default function StorageManager({ stations }: Props) {
  const router = useRouter();
  const sorted = useMemo(() => [...stations].sort((a, b) => a.name.localeCompare(b.name)), [stations]);
  const [stationSlug, setStationSlug] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const runPurge = async (includeActive: boolean) => {
    setBusy(true);
    setStatus("Running purge...");
    try {
      const res = await fetch("/api/admin/storage/purge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          station_slug: stationSlug || null,
          include_active: includeActive,
        }),
      });
      if (!res.ok) {
        setStatus(`Failed (${res.status})`);
        setBusy(false);
        return;
      }
      const payload = (await res.json()) as Record<string, unknown>;
      setStatus(
        `Done: tracks=${String(payload.tracks_deleted ?? 0)}, assets=${String(payload.audio_assets_deleted ?? 0)}, freed=${formatBytesGbMb(payload.freed_bytes_estimate ?? 0)}`
      );
      router.refresh();
    } catch {
      setStatus("Failed (network)");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>Storage Manager</h2>
      <p className="muted">Manage generated audio files by station or globally.</p>
      <div className="grid" style={{ gap: 10 }}>
        <label>
          Scope
          <select value={stationSlug} onChange={(e) => setStationSlug(e.target.value)}>
            <option value="">All stations</option>
            {sorted.map((s) => (
              <option key={s.slug} value={s.slug}>
                {s.name} ({s.slug})
              </option>
            ))}
          </select>
        </label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" disabled={busy} onClick={() => void runPurge(false)}>
            Delete Aired/Failed Files
          </button>
          <button type="button" disabled={busy} onClick={() => void runPurge(true)}>
            Reset Tracks (Include Ready/Queued)
          </button>
        </div>
        <p className="muted">{status}</p>
      </div>
    </section>
  );
}
