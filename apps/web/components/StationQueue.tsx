"use client";

import { useEffect, useMemo, useState } from "react";

type StationTrack = {
  id: number;
  title: string;
  status: string;
  duration_sec: number | null;
  created_at?: string | null;
  aired_at?: string | null;
  download_url?: string | null;
  feedback?: {
    likes?: number;
    dislikes?: number;
    user_vote?: "up" | "down" | null;
  } | null;
};

type StationDetailResponse = {
  recent_tracks: StationTrack[];
};

type Props = {
  stationSlug: string;
  initialTracks: StationTrack[];
};

const POLL_MS = 10_000;

function getSessionId(): string {
  if (typeof window === "undefined") return "server";
  const key = "ai_radio_listener_session_id";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const created = `sid-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  window.localStorage.setItem(key, created);
  return created;
}

function formatClock(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatPlayedAgo(airedAt?: string | null): string {
  if (!airedAt) return "just now";
  const then = new Date(airedAt).getTime();
  if (Number.isNaN(then)) return "recently";
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  const min = Math.floor(diffSec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  return `${hr}h ago`;
}

export default function StationQueue({ stationSlug, initialTracks }: Props) {
  const [tracks, setTracks] = useState<StationTrack[]>(initialTracks || []);
  const [sessionId, setSessionId] = useState<string>("server");

  useEffect(() => {
    setSessionId(getSessionId());
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const params = new URLSearchParams();
        if (sessionId && sessionId !== "server") params.set("session_id", sessionId);
        const res = await fetch(`/api/stations/${stationSlug}?${params.toString()}`, { cache: "no-store" });
        if (!res.ok) return;
        const payload = (await res.json()) as StationDetailResponse;
        if (!cancelled && Array.isArray(payload.recent_tracks)) {
          setTracks(payload.recent_tracks);
        }
      } catch {
        // Best-effort polling; keep current queue on transient failures.
      }
    };

    poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [sessionId, stationSlug]);

  const voteTrack = async (trackId: number, vote: "up" | "down") => {
    if (!sessionId || sessionId === "server") return;
    try {
      const res = await fetch(`/api/stations/${stationSlug}/tracks/${trackId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, vote, source: "web_queue" }),
      });
      if (!res.ok) return;
      const payload = (await res.json()) as {
        feedback?: { likes?: number; dislikes?: number; user_vote?: "up" | "down" | null };
      };
      setTracks((prev) =>
        prev.map((t) =>
          t.id === trackId
            ? {
                ...t,
                feedback: payload.feedback || t.feedback || null,
              }
            : t
        )
      );
    } catch {
      // Ignore transient feedback errors.
    }
  };

  const upNext = useMemo(
    () =>
      [...tracks]
        .filter((t) => t.status === "ready" || t.status === "queued")
        .sort((a, b) => {
          const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
          const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
          return aTime - bTime;
        })
        .slice(0, 5),
    [tracks]
  );
  const recentlyPlayed = useMemo(
    () =>
      [...tracks]
        .filter((t) => t.status === "aired")
        .sort((a, b) => {
          const aTime = a.aired_at ? new Date(a.aired_at).getTime() : 0;
          const bTime = b.aired_at ? new Date(b.aired_at).getTime() : 0;
          return bTime - aTime;
        })
        .slice(0, 5),
    [tracks]
  );

  return (
    <div className="grid">
      <section className="card">
        <h3>Station Cue List</h3>
        {upNext.length === 0 ? (
          <p className="muted">Queue is refreshing...</p>
        ) : (
          <ol className="track-list track-list-small">
            {upNext.map((t, idx) => (
              <li key={t.id} className="track-row">
                <span className="track-pos">{idx + 1}</span>
                <span className="track-title">{t.title}</span>
                {t.download_url ? (
                  <a href={t.download_url} className="track-meta" style={{ marginRight: 10 }}>
                    Download
                  </a>
                ) : null}
                <button
                  type="button"
                  className={`feedback-btn compact ${t.feedback?.user_vote === "up" ? "is-active" : ""}`}
                  onClick={() => {
                    void voteTrack(t.id, "up");
                  }}
                  title="Like this song"
                >
                  👍 {Number(t.feedback?.likes || 0)}
                </button>
                <button
                  type="button"
                  className={`feedback-btn compact is-negative ${t.feedback?.user_vote === "down" ? "is-active" : ""}`}
                  onClick={() => {
                    void voteTrack(t.id, "down");
                  }}
                  title="Dislike this song"
                >
                  👎 {Number(t.feedback?.dislikes || 0)}
                </button>
                <span className="track-meta">{formatClock(t.duration_sec)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
      <section className="card">
        <h3>Recently Played</h3>
        {recentlyPlayed.length === 0 ? (
          <p className="muted">No aired tracks yet for this session.</p>
        ) : (
          <ul className="track-list track-list-small">
            {recentlyPlayed.map((t) => (
              <li key={t.id} className="track-row">
                <span className="track-title">{t.title}</span>
                {t.download_url ? (
                  <a href={t.download_url} className="track-meta" style={{ marginRight: 10 }}>
                    Download
                  </a>
                ) : null}
                <button
                  type="button"
                  className={`feedback-btn compact ${t.feedback?.user_vote === "up" ? "is-active" : ""}`}
                  onClick={() => {
                    void voteTrack(t.id, "up");
                  }}
                  title="Like this song"
                >
                  👍 {Number(t.feedback?.likes || 0)}
                </button>
                <button
                  type="button"
                  className={`feedback-btn compact is-negative ${t.feedback?.user_vote === "down" ? "is-active" : ""}`}
                  onClick={() => {
                    void voteTrack(t.id, "down");
                  }}
                  title="Dislike this song"
                >
                  👎 {Number(t.feedback?.dislikes || 0)}
                </button>
                <span className="track-meta">{formatPlayedAgo(t.aired_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
