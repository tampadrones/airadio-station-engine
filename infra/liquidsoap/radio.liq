settings.log.stdout := true
settings.log.level := 3
settings.server.telnet := true
settings.server.telnet.bind_addr := "0.0.0.0"
settings.server.telnet.port := 1234
settings.server.socket := true
settings.server.socket.path := "/var/lib/ai-radio/playback/liquidsoap.sock"
settings.init.allow_root := true

root = "/var/lib/ai-radio"

def mk_station(slug)
  station_root = root ^ "/playback/stations/" ^ slug
  queue_file = station_root ^ "/queue.m3u"
  fallback_file = station_root ^ "/fallback.m3u"
  hls_dir = root ^ "/hls/" ^ slug

  primary = playlist(reload_mode="watch", mode="normal", queue_file)
  reserve = playlist(reload_mode="watch", mode="normal", fallback_file)
  src = fallback(track_sensitive=false, [primary, reserve, blank()])

  def skip_current(_) =
    source.skip(primary)
    source.skip(reserve)
    "Done!"
  end
  server.register(namespace=slug,
                  usage="skip",
                  description="Skip the current song.",
                  "skip", skip_current)

  output.file.hls(
    playlist="index.m3u8",
    temp_dir=hls_dir,
    hls_dir,
    [("audio", %ffmpeg(format="mpegts", %audio(codec="aac", b="128k", samplerate=44100, channels=2)))],
    src
  )
end

%include "/var/lib/ai-radio/playback/liquidsoap_stations.liq"
