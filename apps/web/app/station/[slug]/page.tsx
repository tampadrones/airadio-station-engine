import Nav from "@/components/Nav";
import StationPlayer from "@/components/StationPlayer";
import StationQueue from "@/components/StationQueue";
import { fetchJson } from "@/lib/api";

type DetailResponse = {
  station: {
    name: string;
    genre: string;
    personality: string;
    description: string;
  };
  recent_tracks: Array<{
    id: number;
    title: string;
    status: string;
    duration_sec: number | null;
    aired_at?: string | null;
    download_url?: string | null;
  }>;
  stream_url: string;
  generation_in_progress: boolean;
  generation_jobs: number;
};

type NowPlayingResponse = {
  track?: {
    id?: number | null;
    title?: string | null;
  } | null;
};

export default async function StationPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [data, nowPlaying] = await Promise.all([
    fetchJson<DetailResponse>(`/stations/${slug}`),
    fetchJson<NowPlayingResponse>(`/stations/${slug}/now-playing`),
  ]);
  const streamUrl = data.stream_url;

  return (
    <main>
      <Nav />
      <h1>{data.station.name}</h1>
      <p>
        <span className="badge">{data.station.genre}</span> <span className="badge">{data.station.personality}</span>
      </p>
      <p>{data.station.description}</p>
      <StationPlayer
        stationSlug={slug}
        streamUrl={streamUrl}
        initialGenerationInProgress={data.generation_in_progress}
        initialGenerationJobs={data.generation_jobs}
        initialNowPlayingTitle={nowPlaying.track?.title || null}
        initialNowPlayingTrackId={typeof nowPlaying.track?.id === "number" ? nowPlaying.track.id : null}
      />
      <StationQueue stationSlug={slug} initialTracks={data.recent_tracks} />
    </main>
  );
}
