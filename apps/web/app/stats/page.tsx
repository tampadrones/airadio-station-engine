import Nav from "@/components/Nav";
import StatsDashboard from "@/components/StatsDashboard";
import { fetchJson } from "@/lib/api";

export default async function StatsPage() {
  const overview = await fetchJson<Record<string, string | number>>("/stats/overview");
  const stations = await fetchJson<Array<Record<string, string | number | null>>>("/stats/stations");
  const generation = await fetchJson<Record<string, unknown>>("/stats/generation");
  const storage = await fetchJson<Record<string, unknown>>("/stats/storage");
  const listeners = await fetchJson<Record<string, unknown>>("/stats/listeners");
  const playback = await fetchJson<Array<Record<string, unknown>>>("/stats/playback");
  const reuse = await fetchJson<Record<string, unknown>>("/stats/reuse");
  const initialLastUpdated = new Date().toISOString();

  return (
    <main>
      <Nav />
      <h1>Stats / Ops</h1>
      <StatsDashboard
        initialOverview={overview}
        initialStations={stations}
        initialGeneration={generation}
        initialStorage={storage}
        initialListeners={listeners}
        initialPlayback={playback}
        initialReuse={reuse}
        initialLastUpdated={initialLastUpdated}
      />
    </main>
  );
}
