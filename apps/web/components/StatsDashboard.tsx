"use client";

import { useEffect, useState } from "react";

type Props = {
  initialOverview: Record<string, string | number>;
  initialStations: Array<Record<string, string | number | null>>;
  initialGeneration: Record<string, unknown>;
  initialStorage: Record<string, unknown>;
  initialListeners: Record<string, unknown>;
  initialPlayback: Array<Record<string, unknown>>;
  initialReuse: Record<string, unknown>;
  initialLastUpdated: string;
};

const REFRESH_MS = 10_000;

export default function StatsDashboard({
  initialOverview,
  initialStations,
  initialGeneration,
  initialStorage,
  initialListeners,
  initialPlayback,
  initialReuse,
  initialLastUpdated,
}: Props) {
  const [overview, setOverview] = useState(initialOverview);
  const [stations, setStations] = useState(initialStations);
  const [generation, setGeneration] = useState(initialGeneration);
  const [storage, setStorage] = useState(initialStorage);
  const [listeners, setListeners] = useState(initialListeners);
  const [playback, setPlayback] = useState(initialPlayback);
  const [reuse, setReuse] = useState(initialReuse);
  const [lastUpdated, setLastUpdated] = useState(initialLastUpdated);
  const [resetStatus, setResetStatus] = useState<string>("");
  const generatorQueueSize =
    typeof generation.generator_queue_size === "number" ? generation.generator_queue_size : null;
  const generatorQueueHealth =
    typeof generation.generator_queue_health === "string" ? generation.generator_queue_health : "unavailable";

  const formatBytesWithGbMb = (value: unknown): string => {
    const num = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(num) || num < 0) return String(value);
    const gb = num / 1_000_000_000;
    const mb = num / 1_000_000;
    return `${gb.toFixed(2)} GB (${mb.toFixed(2)} MB)`;
  };

  const renderOverviewValue = (key: string, value: string | number): string => {
    if (key.endsWith("_bytes") || key === "hot_storage_usage") return formatBytesWithGbMb(value);
    return String(value);
  };

  const refreshStats = async () => {
    const [o, s, g, st, l, p, r] = await Promise.all([
      fetch("/api/stats/overview", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/stats/stations", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/stats/generation", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/stats/storage", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/stats/listeners", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/stats/playback", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/stats/reuse", { cache: "no-store" }).then((r) => r.json()),
    ]);
    setOverview(o);
    setStations(s);
    setGeneration(g);
    setStorage(st);
    setListeners(l);
    setPlayback(p);
    setReuse(r);
    setLastUpdated(new Date().toISOString());
  };

  useEffect(() => {
    const tick = async () => {
      try {
        await refreshStats();
      } catch {
        // Keep prior values on transient errors.
      }
    };

    const id = window.setInterval(tick, REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  const handleResetFailedToday = async () => {
    setResetStatus("Resetting...");
    try {
      const res = await fetch("/api/stats/generation/reset-failed-today", { method: "POST" });
      if (!res.ok) {
        setResetStatus(`Reset failed (${res.status})`);
        return;
      }
      const payload = await res.json();
      setResetStatus(`Reset complete: ${String(payload.deleted ?? 0)} failed event(s) removed for today.`);
      await refreshStats();
    } catch {
      setResetStatus("Reset failed (network)");
    }
  };

  return (
    <>
      <p className="muted">Live refresh every 10s. Last updated: {lastUpdated}</p>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="muted" style={{ marginBottom: 6 }}>
          Generator queue
        </div>
        <div className="stat">{generatorQueueSize ?? "Unavailable"}</div>
        <div className="muted">
          Server health: {generatorQueueHealth}
          {generatorQueueSize !== null ? " | queued jobs waiting on ACE-Step" : ""}
        </div>
      </div>
      <div className="grid cards">
        {Object.entries(overview).map(([k, v]) => (
          <div key={k} className="card">
            <div>{k.replaceAll("_", " ")}</div>
            <div className="stat">{renderOverviewValue(k, v)}</div>
          </div>
        ))}
      </div>

      <h2>Stations</h2>
      <table className="table">
        <thead>
          <tr>
            <th>Station</th>
            <th>Status</th>
            <th>Queue</th>
            <th>Ready</th>
            <th>Buffer (min)</th>
            <th>Generating</th>
            <th>Mood</th>
          </tr>
        </thead>
        <tbody>
          {stations.map((s, idx) => (
            <tr key={idx}>
              <td>{String(s.station_name)}</td>
              <td>{String(s.current_status)}</td>
              <td>
                {String(s.queue_depth)}/{String(s.target_queue_depth)}
              </td>
              <td>{String(s.ready_tracks)}</td>
              <td>{String(s.buffer_minutes_remaining)}</td>
              <td>{s.generation_in_progress ? `yes (${String(s.generation_jobs ?? 0)})` : "no"}</td>
              <td>{String(s.mood)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Generation</h2>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <button type="button" onClick={handleResetFailedToday}>
          Reset Failed Generations Today
        </button>
        <span className="muted">{resetStatus}</span>
      </div>
      <pre className="card">{JSON.stringify(generation, null, 2)}</pre>
      <h2>Storage</h2>
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Generated Music Cap</div>
        <div>
          Used: {formatBytesWithGbMb(storage.generated_storage_used_bytes)} / Cap: {String(storage.generated_storage_cap_gb)} GB
        </div>
        <div>
          Over cap: {storage.generated_storage_over_cap ? "yes" : "no"} | Overage: {formatBytesWithGbMb(storage.generated_storage_overage_bytes)}
        </div>
      </div>
      <pre className="card">{JSON.stringify(storage, null, 2)}</pre>
      <h2>Listeners</h2>
      <pre className="card">{JSON.stringify(listeners, null, 2)}</pre>
      <h2>Playback</h2>
      <pre className="card">{JSON.stringify(playback, null, 2)}</pre>
      <h2>Reuse</h2>
      <pre className="card">{JSON.stringify(reuse, null, 2)}</pre>
    </>
  );
}
