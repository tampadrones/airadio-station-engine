import Nav from "@/components/Nav";
import { fetchJson } from "@/lib/api";

type Station = {
  id: number;
  slug: string;
  name: string;
  genre: string;
  personality: string;
  description: string;
  is_enabled: boolean;
};

export default async function Home() {
  const stations = await fetchJson<Station[]>("/stations");
  const visibleStations = stations.filter((s) => s.is_enabled);
  return (
    <main>
      <Nav />
      <h1>AI Radio Stations</h1>
      <div className="grid cards">
        {visibleStations.map((s) => (
          <article className="card" key={s.id}>
            <h2>{s.name}</h2>
            <p>
              <span className="badge">{s.genre}</span> <span className="badge">{s.personality}</span>
            </p>
            <p>{s.description}</p>
            <a href={`/station/${s.slug}`}>Open station</a>
          </article>
        ))}
      </div>
    </main>
  );
}
