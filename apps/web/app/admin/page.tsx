import Nav from "@/components/Nav";
import ReprofileStations from "@/components/ReprofileStations";
import StationCreator from "@/components/StationCreator";
import GenerationPreview from "@/components/GenerationPreview";
import StationSettingsEditor from "@/components/StationSettingsEditor";
import StorageManager from "@/components/StorageManager";
import { fetchJson } from "@/lib/api";

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

export default async function AdminPage({ searchParams }: { searchParams?: Promise<{ q?: string }> }) {
  const sp = (await searchParams) || {};
  const q = sp.q || "";
  const stations = await fetchJson<Station[]>("/stations");
  const playback = await fetchJson<Array<Record<string, unknown>>>("/stats/playback");
  const logs = await fetchJson<Array<Record<string, unknown>>>(`/logs?limit=200`);
  const filtered = q ? logs.filter((l) => JSON.stringify(l).toLowerCase().includes(q.toLowerCase())) : logs;

  return (
    <main>
      <Nav />
      <h1>Admin Console</h1>
      <StationCreator />
      <StationSettingsEditor stations={stations} />
      <StorageManager stations={stations.map((s) => ({ slug: s.slug, name: s.name }))} />
      <GenerationPreview stations={stations} />
      <ReprofileStations />
      <h2>Replay Status</h2>
      <table className="table" style={{ marginBottom: 16 }}>
        <thead>
          <tr>
            <th>Station</th>
            <th>Replay Active</th>
            <th>Reason</th>
            <th>Now Playing</th>
          </tr>
        </thead>
        <tbody>
          {playback.map((row, idx) => (
            <tr key={idx}>
              <td>{String(row.station_slug ?? "")}</td>
              <td>{row.replay_active ? "yes" : "no"}</td>
              <td>{String(row.replay_reason ?? "none")}</td>
              <td>{String(row.now_playing ?? "")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form method="get" style={{ marginBottom: 16 }}>
        <input name="q" defaultValue={q} placeholder="Search logs" style={{ width: 320, padding: 8 }} />
        <button type="submit" style={{ marginLeft: 8, padding: 8 }}>Search</button>
      </form>
      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Severity</th>
            <th>Service</th>
            <th>Type</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((ev, idx) => (
            <tr key={idx}>
              <td>{String(ev.timestamp)}</td>
              <td>{String(ev.severity)}</td>
              <td>{String(ev.service)}</td>
              <td>{String(ev.event_type)}</td>
              <td>{String(ev.message)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
