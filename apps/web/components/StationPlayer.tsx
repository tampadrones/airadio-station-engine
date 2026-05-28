"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Hls from "hls.js";

type NowPlayingResponse = {
  listeners?: number;
  generation_in_progress?: boolean;
  generation_jobs?: number;
  track?: {
    id?: number | null;
    title?: string | null;
    duration_sec?: number | null;
    feedback?: {
      likes?: number;
      dislikes?: number;
      user_vote?: "up" | "down" | null;
    } | null;
  } | null;
};

type SkipCurrentResponse = {
  ok?: boolean;
  next_track?: {
    id?: number | null;
    title?: string | null;
    duration_sec?: number | null;
  } | null;
};

type Props = {
  stationSlug: string;
  streamUrl: string;
  initialGenerationInProgress: boolean;
  initialGenerationJobs: number;
  initialNowPlayingTitle?: string | null;
  initialNowPlayingTrackId?: number | null;
};

const HEARTBEAT_MS = 20_000;
const POLL_MS = 10_000;

function createSessionId(): string {
  if (typeof window === "undefined") {
    return `srv-${Date.now()}`;
  }
  const cryptoObj = window.crypto as Crypto | undefined;
  if (cryptoObj && typeof cryptoObj.randomUUID === "function") {
    return cryptoObj.randomUUID();
  }
  if (cryptoObj && typeof cryptoObj.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    cryptoObj.getRandomValues(bytes);
    return `sid-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
  }
  return `sid-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function StationPlayer({
  stationSlug,
  streamUrl,
  initialGenerationInProgress,
  initialGenerationJobs,
  initialNowPlayingTitle,
  initialNowPlayingTrackId,
}: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [playing, setPlaying] = useState(false);
  const [listeners, setListeners] = useState(0);
  const [generationInProgress, setGenerationInProgress] = useState(initialGenerationInProgress);
  const [generationJobs, setGenerationJobs] = useState(initialGenerationJobs);
  const [nowPlayingTitle, setNowPlayingTitle] = useState<string>(initialNowPlayingTitle?.trim() || "Loading...");
  const [nowPlayingTrackId, setNowPlayingTrackId] = useState<number | null>(initialNowPlayingTrackId ?? null);
  const [likes, setLikes] = useState(0);
  const [dislikes, setDislikes] = useState(0);
  const [userVote, setUserVote] = useState<"up" | "down" | null>(null);
  const lastRebufferAtRef = useRef(0);

  const sessionId = useMemo(() => {
    if (typeof window === "undefined") return "server";
    const key = "ai_radio_listener_session_id";
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const created = createSessionId();
    window.localStorage.setItem(key, created);
    return created;
  }, []);

  const sendHeartbeat = async (isPlaying: boolean) => {
    try {
      const res = await fetch("/api/listeners/heartbeat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          station_slug: stationSlug,
          session_id: sessionId,
          playing: isPlaying,
        }),
      });
      if (res.ok) {
        const payload = (await res.json()) as { current_listeners?: number };
        if (typeof payload.current_listeners === "number") {
          setListeners(payload.current_listeners);
        }
      }
    } catch {
      // Network drops are expected during listener churn.
    }
  };

  const sendListenerEvent = async (eventType: "stream_error" | "rebuffer" | "skip" | "completion") => {
    try {
      await fetch("/api/listeners/event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          station_slug: stationSlug,
          session_id: sessionId,
          event_type: eventType,
        }),
      });
    } catch {
      // Listener event collection should be best-effort.
    }
  };

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const isHls = /\.m3u8(?:$|\?)/i.test(streamUrl);
    const canPlayNativeHls = audio.canPlayType("application/vnd.apple.mpegurl") !== "";

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    if (isHls && !canPlayNativeHls && Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: false,
      });
      hlsRef.current = hls;
      hls.loadSource(streamUrl);
      hls.attachMedia(audio);
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data?.fatal) {
          void sendListenerEvent("stream_error");
        }
      });
    } else {
      audio.src = streamUrl;
    }

    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      if (audio) {
        audio.removeAttribute("src");
        audio.load();
      }
    };
  }, [streamUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void refreshNowPlaying();
    const id = window.setInterval(() => {
      void refreshNowPlaying();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [nowPlayingTitle, sessionId, stationSlug]);

  const sendTrackFeedback = async (vote: "up" | "down") => {
    if (!nowPlayingTrackId) return;
    try {
      const res = await fetch(`/api/stations/${stationSlug}/tracks/${nowPlayingTrackId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          vote,
          source: "web_player",
        }),
      });
      if (!res.ok) return;
      const payload = (await res.json()) as {
        feedback?: { likes?: number; dislikes?: number; user_vote?: "up" | "down" | null };
      };
      setLikes(Number(payload.feedback?.likes || 0));
      setDislikes(Number(payload.feedback?.dislikes || 0));
      setUserVote(payload.feedback?.user_vote === "up" || payload.feedback?.user_vote === "down" ? payload.feedback.user_vote : null);
    } catch {
      // Feedback should be best-effort and never interrupt playback.
    }
  };

  const refreshNowPlaying = async () => {
    try {
      const params = new URLSearchParams();
      params.set("session_id", sessionId);
      const res = await fetch(`/api/stations/${stationSlug}/now-playing?${params.toString()}`, { cache: "no-store" });
      if (!res.ok) return;
      const payload = (await res.json()) as NowPlayingResponse;
      if (typeof payload.listeners === "number") setListeners(payload.listeners);
      if (typeof payload.generation_in_progress === "boolean") setGenerationInProgress(payload.generation_in_progress);
      if (typeof payload.generation_jobs === "number") setGenerationJobs(payload.generation_jobs);
      const title = payload.track?.title;
      const tid = payload.track?.id;
      setNowPlayingTrackId(typeof tid === "number" ? tid : null);
      const fb = payload.track?.feedback;
      setLikes(Number(fb?.likes || 0));
      setDislikes(Number(fb?.dislikes || 0));
      setUserVote(fb?.user_vote === "up" || fb?.user_vote === "down" ? fb.user_vote : null);
      if (typeof title === "string" && title.trim()) {
        setNowPlayingTitle(title.trim());
      } else if (!nowPlayingTitle || nowPlayingTitle === "Loading..." || nowPlayingTitle === "Skipping...") {
        setNowPlayingTitle("Awaiting next track...");
      }
    } catch {
      // Poll failure should not interrupt playback.
    }
  };

  const skipCurrentTrack = async () => {
    if (!nowPlayingTrackId) return;
    try {
      const res = await fetch(`/api/stations/${stationSlug}/skip-current`, { method: "POST" });
      if (!res.ok) return;
      const payload = (await res.json()) as SkipCurrentResponse;
      void sendListenerEvent("skip");
      const nextId = payload.next_track?.id;
      const nextTitle = payload.next_track?.title?.trim();
      if (typeof nextId === "number") {
        setNowPlayingTrackId(nextId);
      } else {
        setNowPlayingTrackId(null);
      }
      if (nextTitle) {
        setNowPlayingTitle(nextTitle);
      } else {
        setNowPlayingTitle("Skipping...");
      }
      setLikes(0);
      setDislikes(0);
      setUserVote(null);
      for (const delayMs of [1500, 4000, 9000]) {
        window.setTimeout(() => {
          void refreshNowPlaying();
        }, delayMs);
      }
    } catch {
      // Ignore transient skip errors.
    }
  };

  useEffect(() => {
    if (!playing) return;
    sendHeartbeat(true);
    const id = window.setInterval(() => {
      sendHeartbeat(true);
    }, HEARTBEAT_MS);
    return () => window.clearInterval(id);
  }, [playing]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      if (typeof navigator !== "undefined" && "sendBeacon" in navigator) {
        const blob = new Blob(
          [
            JSON.stringify({
              station_slug: stationSlug,
              session_id: sessionId,
              playing: false,
            }),
          ],
          { type: "application/json" }
        );
        navigator.sendBeacon("/api/listeners/heartbeat", blob);
      }
    };
  }, [sessionId, stationSlug]);

  return (
    <div className="card">
      <h3>Live stream</h3>
      {generationInProgress ? (
        <p className="badge badge-live">Generating new song ({generationJobs})</p>
      ) : (
        <p className="badge">Generator idle</p>
      )}
      <p className="badge"><strong>Now Playing:</strong> {nowPlayingTitle}</p>
      <div className="feedback-row">
        <button
          type="button"
          className="feedback-btn"
          onClick={() => {
            void skipCurrentTrack();
          }}
          disabled={!nowPlayingTrackId}
          title="Skip current song"
        >
          Skip Current
        </button>
        <button
          type="button"
          className={`feedback-btn ${userVote === "up" ? "is-active" : ""}`}
          onClick={() => {
            void sendTrackFeedback("up");
          }}
          disabled={!nowPlayingTrackId}
          aria-label="Like current song"
          title="Like this song"
        >
          👍 <span>{likes}</span>
        </button>
        <button
          type="button"
          className={`feedback-btn ${userVote === "down" ? "is-active is-negative" : "is-negative"}`}
          onClick={() => {
            void sendTrackFeedback("down");
          }}
          disabled={!nowPlayingTrackId}
          aria-label="Dislike current song"
          title="Dislike this song"
        >
          👎 <span>{dislikes}</span>
        </button>
      </div>
      <p className="badge">Listeners now: {listeners}</p>
      <audio
        ref={audioRef}
        controls
        preload="none"
        style={{ width: "100%" }}
        onPlay={() => {
          setPlaying(true);
          void sendHeartbeat(true);
        }}
        onPause={() => {
          setPlaying(false);
          void sendHeartbeat(false);
        }}
        onEnded={() => {
          setPlaying(false);
          void sendListenerEvent("completion");
          void sendHeartbeat(false);
        }}
        onWaiting={() => {
          const now = Date.now();
          if (now - lastRebufferAtRef.current < 15000) return;
          lastRebufferAtRef.current = now;
          void sendListenerEvent("rebuffer");
        }}
        onError={() => {
          void sendListenerEvent("stream_error");
        }}
      />
      <p>Stream endpoint: {streamUrl}</p>
    </div>
  );
}
