// EDITING OF THIS FILE MAY CAUSE CATASTROPHIC APP DESYCHRONIZATION. Reference the directory at at ~/docs/synchronization_map.md to determine what other files must be adjusted in order to ensure absolute synchronization is maintained. This is to ensure that the APK, termux daemon, and chromecast portions of the app are always in synchronous, deterministic states.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Cast,
  CircleAlert,
  FileVideo,
  Link2,
  Link2Off,
  Loader2,
  Pause,
  Play,
  Power,
  RefreshCw,
  Search,
  Square,
  Subtitles,
  Wifi,
  Trash2,
  Volume2,
  VolumeX,
  Gamepad2,
  FastForward,
  Rewind,
} from "lucide-react";
import {
  DAEMON_BASE,
  daemon,
  formatBytes,
  formatDuration,
  subscribe,
  type LibraryItem,
  type LogLine,
  type Preflight,
  type Status,
} from "./lib/daemon";
import { PreflightPanel } from "./components/preflight-panel";
import { TERMUX_MANUAL_COMMAND, launchTermuxDaemon, getSharedUrl } from "./lib/termux-daemon";
import { DiscoveryBrowser } from "./lib/discovery-browser";
import {
  Drawer,
  DrawerContent,
  DrawerTrigger,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription
} from "./components/ui/drawer";

const LIVE_STATES = new Set(["playing", "buffering", "paused", "loading"]);

const STATE_TONE: Record<string, string> = {
  playing: "text-emerald-400",
  buffering: "text-amber-400",
  paused: "text-emerald-300/70",
  loading: "text-amber-400",
  connected: "text-emerald-400/70",
  ready: "text-emerald-400/70",
  connecting: "text-amber-400",
  disconnected: "text-emerald-500/40",
  load_failed: "text-rose-400",
  dead: "text-rose-400",
};

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [library, setLibrary] = useState<LibraryItem[]>([]);
  const [trashItems, setTrashItems] = useState<LibraryItem[]>([]);
  const [amazonQueue, setAmazonQueue] = useState<any[]>([]);
  const [maxVerbosityLogs, setMaxVerbosityLogs] = useState<string | null>(null);
  const [selected, setSelected] = useState<LibraryItem | null>(null);
  const [report, setReport] = useState<Preflight | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [showDebugLogs, setShowDebugLogs] = useState(false);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [host, setHost] = useState("192.168.1.50");
  const [notice, setNotice] = useState<string | null>(null);
  const [launchMessage, setLaunchMessage] = useState<string | null>(null);
  const [missingDep, setMissingDep] = useState<string | null>(null);
  const [selectedAudioId, setSelectedAudioId] = useState<number | null>(null);
  const [selectedSubtitleId, setSelectedSubtitleId] = useState<number | null>(null);

  const logRef = useRef<HTMLDivElement>(null);

  const [anomaly, setAnomaly] = useState<any | null>(null);

  const statusRef = useRef<Status | null>(null);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await daemon.status());
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  // Live stream from the daemon, plus a slow poll as a safety net.
  useEffect(() => {
    refreshStatus();
    const unsubscribe = subscribe({
      onOpen: () => setOnline(true),
      onError: () => setOnline(false),
      onStatus: (s) => {
        setStatus(s);
        setOnline(true);
      },
      onLog: (line) => setLogs((prev) => [...prev.slice(-300), line]),
      onState: refreshStatus,
      onRemux: refreshStatus,
      onMedia: (media) =>
        setStatus((prev) => (prev ? { ...prev, cast: { ...prev.cast, ...media } } : prev)),
      onTelemetryAnomaly: (data) => setAnomaly(data),
      onAmazonQueue: (data) => setAmazonQueue((data as any).items || []),
    });
    const timer = window.setInterval(refreshStatus, 5000);
    return () => {
      unsubscribe();
      window.clearInterval(timer);
    };
  }, [refreshStatus]);

  // Smooth the position clock between MEDIA_STATUS messages.
  useEffect(() => {
    if (status?.cast?.state !== "playing") return;
    const timer = window.setInterval(() => {
      setStatus((prev) =>
        prev && prev.cast.state === "playing"
          ? { ...prev, cast: { ...prev.cast, position: prev.cast.position + 1 } }
          : prev,
      );
    }, 1000);
    return () => window.clearInterval(timer);
  }, [status?.cast?.state]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [logs]);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setNotice(null);
    try {
      await fn();
      await refreshStatus();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const match = msg.match(/No such file or directory: '([^']+)'/);
      if (match) {
        setMissingDep(match[1]);
        setNotice(`'${match[1]}' is not installed. Install it?`);
      } else {
        setNotice(msg);
      }
    } finally {
      setBusy(null);
    }
  };

  const checkSharedUrl = useCallback(async () => {
    try {
      const result = await getSharedUrl();
      if (result.url) {
        const urlStr = result.url as string;
        const isAmazon = urlStr.includes("amazon.com") || urlStr.includes("gti=");
        const isPlaying = statusRef.current?.cast?.state && statusRef.current.cast.state !== "idle" && statusRef.current.cast.state !== "IDLE" && statusRef.current.cast.state !== "unknown" && statusRef.current.cast.state !== "dead" && statusRef.current.cast.state !== "disconnected";
        
        if (isAmazon && isPlaying) {
          setNotice(`Adding Amazon video to queue...`);
          try {
            await daemon.addAmazonQueue(urlStr);
            setNotice(`Added to Amazon Queue.`);
            await loadLibrary();
          } catch (err) {
            setNotice(`Failed to add to queue: ${err}`);
          }
        } else {
          setNotice(`Extracting streams, please wait...`);
          try {
            await daemon.cast(urlStr, true);
            setNotice(`Success! Sending stream to TV...`);
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            const match = msg.match(/No such file or directory: '([^']+)'/);
            if (match) {
              setMissingDep(match[1]);
              setNotice(`'${match[1]}' is not installed. Install it?`);
            } else {
              setNotice(msg);
            }
          }
        }
      }
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    checkSharedUrl();
    const handleVis = () => { if (document.visibilityState === "visible") checkSharedUrl(); };
    document.addEventListener("visibilitychange", handleVis);
    return () => document.removeEventListener("visibilitychange", handleVis);
  }, [checkSharedUrl]);

  useEffect(() => {
    const handle = DiscoveryBrowser.addListener("onStreamDetected", async (event) => {
      console.log("Stream detected from WebView!", event);
      try {
        await daemon.interceptDiscovery(event);
      } catch (err) {
        console.error("Failed to bridge interception to daemon", err);
      }
    });
    return () => { handle.then(h => h.remove()); };
  }, []);

  const launchDaemon = () =>
    run("launch-daemon", async () => {
      setLaunchMessage("Sending Termux RUN_COMMAND intent…");
      const result = await launchTermuxDaemon();
      setLaunchMessage(
        `Root configured Termux and sent launch request. Waiting for ${DAEMON_BASE}. Audit log: ${result.auditLog ?? "/storage/emulated/0/Download/VideoQualityCheckerApp/Chromecast/.castcast/audit.log"}. ${result.note ?? ""}`.trim(),
      );
      await new Promise((resolve) => window.setTimeout(resolve, 2500));
      await refreshStatus();
    });

  const loadLibrary = () =>
    run("library", async () => {
      const libRes = await daemon.library(false);
      if ((libRes as any).error) throw new Error((libRes as any).error);
      setLibrary(libRes.items || []);

      const trashRes = await daemon.getTrash();
      if ((trashRes as any).error) throw new Error((trashRes as any).error);
      setTrashItems(trashRes.items || []);

      try {
        const amzRes = await daemon.getAmazonQueue();
        setAmazonQueue(amzRes.items || []);
      } catch (e) {
        setAmazonQueue([]);
      }
    });

  const handleDragStart = (e: React.DragEvent, index: number, type: 'library' | 'amazon') => {
    e.dataTransfer.setData("text/plain", JSON.stringify({ index, type }));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = async (e: React.DragEvent, dropIndex: number, type: 'library' | 'amazon') => {
    e.preventDefault();
    const dataStr = e.dataTransfer.getData("text/plain");
    if (!dataStr) return;
    try {
      const data = JSON.parse(dataStr);
      if (data.type !== type) return;
      if (data.index === dropIndex) return;

      if (type === 'library') {
        const newItems = [...library];
        const [moved] = newItems.splice(data.index, 1);
        newItems.splice(dropIndex, 0, moved);
        setLibrary(newItems);
        // daemon.reorderLibrary(newItems).catch(console.error);
      } else {
        const newItems = [...amazonQueue];
        const [moved] = newItems.splice(data.index, 1);
        newItems.splice(dropIndex, 0, moved);
        setAmazonQueue(newItems);
        try {
          await daemon.reorderAmazonQueue(newItems);
        } catch (err) {
          console.error(err);
        } finally {
          const amzRes = await daemon.getAmazonQueue();
          setAmazonQueue(amzRes.items || []);
        }
      }
    } catch (err) {
      console.error(err);
    }
  };

  const trashFile = (path: string, e: React.MouseEvent) => {
    e.stopPropagation();
    run("trash", async () => {
      await daemon.trash(path);
      await loadLibrary();
    });
  };

  const deleteFile = (path: string, e: React.MouseEvent) => {
    e.stopPropagation();
    run("delete", async () => {
      await daemon.delete(path);
      await loadLibrary();
    });
  };

  const emptyTrash = () =>
    run("empty-trash", async () => {
      for (const item of trashItems) {
        const result = await daemon.delete(item.path);
        if (result.error) throw new Error(`${item.rel}: ${result.error}`);
      }
      await loadLibrary();
      setNotice("Trash emptied permanently.");
    });

  const select = (item: LibraryItem) =>
    run("preflight", async () => {
      setSelected(item);
      setSelectedAudioId(null);
      setSelectedSubtitleId(null);
      setReport(null);
      setReport(await daemon.preflight(item.path));
    });

  const markLoading = (name: string, path: string) =>
    setStatus((prev) =>
      prev
        ? {
            ...prev,
            cast: {
              ...prev.cast,
              state: "loading",
              title: name,
              source_path: path,
            },
          }
        : prev,
    );

  const doCast = (allowUnsafe = false) =>
    selected &&
    run("cast", async () => {
      const result = await daemon.cast(selected.path, allowUnsafe, selectedAudioId, selectedSubtitleId);
      if (result.error) setNotice(result.error);
      if (result.converting) setNotice("Conversion started — cast again when it finishes.");
      if (result.casting) markLoading(selected.name, selected.path);
      setReport((prev) => ({ ...(prev || {}), ...result } as Preflight));
    });


  const castQueue = () =>
    run("queue", async () => {
      if (!library.length) throw new Error("Scan the queue before casting it.");
      const selectedIndex = selected ? library.findIndex((item) => item.path === selected.path) : -1;
      const ordered = selectedIndex >= 0
        ? [...library.slice(selectedIndex), ...library.slice(0, selectedIndex)]
        : library;
      const result = await daemon.queue(ordered.map((item) => item.path));
      if (result.error) throw new Error(result.error);
      const first = ordered[0];
      markLoading(first.name, first.path);
      setNotice(`Queued ${result.queued ?? 0} item(s); ${result.preparing ?? 0} preparing, ${result.skipped ?? 0} skipped.`);
    });

  const requestSubtitles = () =>
    cast?.source_path &&
    run("subtitles", async () => {
      const result = await daemon.requestOpenSubtitles(cast.source_path, "eng");
      if (result.error) setNotice(result.error);
      else setNotice("English subtitles loaded from OpenSubtitles.");
    });

  const cast = status?.cast;
  const live = cast ? LIVE_STATES.has(cast.state) : false;
  const remux = status?.remux;

  // ---- daemon offline ------------------------------------------------
  if (!online) {
    return (
      <div className="min-h-screen bg-[#050807] p-6 text-emerald-300" style={{ fontFamily: "'Exo 2', sans-serif" }}>
        <div className="mx-auto max-w-md space-y-4 pt-16">
          <div className="flex items-center gap-2 text-emerald-400">
            <CircleAlert className="h-5 w-5" />
            <span>daemon unreachable</span>
          </div>
          <p className="text-emerald-500/70">
            This UI is a face for the <span className="font-mono">castcast</span> daemon. A browser
            cannot speak CASTv2 itself — the protocol needs a raw TLS socket — so the daemon does all
            the device work and this talks to it over localhost.
          </p>
          <button
            type="button"
            onClick={launchDaemon}
            disabled={busy === "launch-daemon"}
            className="block w-full rounded border border-emerald-500/50 bg-emerald-500/20 px-4 py-3 text-center font-bold tracking-wide text-emerald-100 shadow-lg hover:bg-emerald-500/30 disabled:cursor-wait disabled:opacity-60"
          >
            {busy === "launch-daemon" ? "Launching Termux…" : "Launch Daemon (Termux)"}
          </button>
          <div className="font-mono text-emerald-500/50">expecting: {DAEMON_BASE}</div>
          {(launchMessage || notice) && (
            <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-300">
              {notice ?? launchMessage}
            </div>
          )}
          <div className="rounded border border-emerald-500/20 bg-black/40 p-3 text-xs text-emerald-500/70">
            <div className="mb-1 text-emerald-400/80">Manual fallback command:</div>
            <code className="break-words font-mono">{TERMUX_MANUAL_COMMAND}</code>
          </div>
          <button
            onClick={() => run("retry", refreshStatus)}
            disabled={busy === "retry"}
            className="rounded border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-emerald-300 hover:bg-emerald-500/20 disabled:cursor-wait disabled:opacity-60"
          >
            {busy === "retry" ? "checking…" : "retry"}
          </button>
        </div>
      </div>
    );
  }

  // ---- main ----------------------------------------------------------
  return (
    <div
      className="min-h-screen bg-[#050807] text-emerald-300"
      style={{ fontFamily: "'Exo 2', sans-serif" }}
    >
      <div className="mx-auto max-w-2xl space-y-4 p-4 pb-24">
        {/* header */}
        <header className="flex items-center justify-between border-b border-emerald-500/20 pb-3">
          <div className="flex items-center gap-2">
            <Cast className="h-5 w-5 text-emerald-400" />
            <span className="tracking-wide">castcast</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                const url = prompt("Enter a URL to discover (e.g. https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8):", "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8");
                if (url) DiscoveryBrowser.open({ url });
              }}
              className="rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300 hover:bg-emerald-500/20"
            >
              Discovery Mode
            </button>
            <div className="flex items-center gap-2 font-mono text-emerald-500/60">
              <Wifi className="h-3.5 w-3.5" />
              {status?.media_server.lan_ip}:{status?.media_server.port}
            </div>
          </div>
        </header>

        {notice && (
          <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 text-amber-300">
            {notice}
          </div>
        )}

        {!status?.tools.ffprobe && (
          <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 text-amber-300">
            ffprobe not found — pre-flight checks are disabled, so unsupported files will fail
            silently on the device. <span className="font-mono">pkg install ffmpeg</span>
          </div>
        )}

        {status && !status.tools.yt_dlp && (
          <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 text-amber-300">
            yt-dlp not found — YouTube sharing is disabled. Run <span className="font-mono">pip install yt-dlp</span> in Termux.
          </div>
        )}

        {missingDep && (
          <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 flex items-center justify-between text-amber-300">
            <div>Open Termux and run: <span className="font-mono">pip install {missingDep}</span></div>
            <button
              onClick={() => {
                setMissingDep(null);
                setNotice(null);
                checkSharedUrl();
              }}
              className="rounded border border-amber-500/40 bg-amber-500/10 px-4 py-1 hover:bg-amber-500/20"
            >
              Done
            </button>
          </div>
        )}

        {/* connection */}
        <section className="rounded border border-emerald-500/20 bg-black/40 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-emerald-500/50 uppercase tracking-wider">device</span>
            <span className={`font-mono ${STATE_TONE[cast?.state ?? ""] ?? "text-emerald-500/50"}`}>
              {cast?.state ?? "unknown"}
            </span>
          </div>

          {status?.device ? (
            <div className="flex items-center justify-between">
              <div>
                <div className="text-emerald-200">{status.device.friendly_name}</div>
                <div className="font-mono text-emerald-500/50">
                  {status.device.host}
                  {cast && cast.reconnects > 0 && ` · ${cast.reconnects} reconnect(s)`}
                  {cast && cast.stream_stalls > 0 && ` · ${cast.stream_stalls} stall(s)`}
                </div>
              </div>
              <button
                onClick={() => run("disconnect", daemon.disconnect)}
                className="flex items-center gap-1.5 rounded border border-emerald-500/30 px-3 py-1.5 hover:bg-emerald-500/10"
              >
                <Link2Off className="h-3.5 w-3.5" /> disconnect
              </button>
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                value={host}
                onChange={(event) => setHost(event.target.value)}
                placeholder="192.168.1.50"
                className="min-w-0 flex-1 rounded border border-emerald-500/25 bg-black/50 px-3 py-1.5 font-mono text-emerald-200 outline-none focus:border-emerald-500/60"
              />
              <button
                onClick={() => run("connect", () => daemon.connect(host))}
                disabled={busy === "connect"}
                className="flex items-center gap-1.5 rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 hover:bg-emerald-500/20 disabled:opacity-50"
              >
                {busy === "connect" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Link2 className="h-3.5 w-3.5" />
                )}
                connect
              </button>
              <button
                onClick={() =>
                  run("discover", async () => {
                    const { devices } = await daemon.devices();
                    if (devices.length) setHost(devices[0].host);
                    else setNotice("No devices found — mDNS is often blocked. Enter the IP directly.");
                  })
                }
                className="rounded border border-emerald-500/25 px-3 py-1.5 hover:bg-emerald-500/10"
              >
                <Search className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </section>

        {/* transport */}
        {live && cast && (
          <section className="rounded border border-emerald-500/25 bg-black/40 p-3">
            <div className="mb-2 truncate text-emerald-200">{cast.title || "untitled"}</div>
            <div
              className="mb-2 h-2 overflow-hidden rounded bg-emerald-500/15 cursor-pointer"
              onClick={(e) => {
                if (!cast || !cast.duration) return;
                const rect = e.currentTarget.getBoundingClientRect();
                const percent = (e.clientX - rect.left) / rect.width;
                run("seek", () => daemon.seek(percent * cast.duration!));
              }}
            >
              <div
                className="h-full bg-emerald-400 transition-all pointer-events-none"
                style={{
                  width: `${cast.duration ? Math.min((cast.position / cast.duration) * 100, 100) : 0}%`,
                }}
              />
            </div>
            <div className="mb-3 flex justify-between font-mono text-emerald-500/60">
              <span>{formatDuration(cast.position)}</span>
              <span>{formatDuration(cast.duration)}</span>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() =>
                  run("toggle", cast.state === "paused" ? daemon.play : daemon.pause)
                }
                className="flex flex-1 items-center justify-center gap-1.5 rounded border border-emerald-500/40 bg-emerald-500/10 py-2 hover:bg-emerald-500/20"
              >
                {cast.state === "paused" ? (
                  <><Play className="h-4 w-4" /> play</>
                ) : (
                  <><Pause className="h-4 w-4" /> pause</>
                )}
              </button>
              {(() => {
                const hasEmbeddedSubs = (cast.active_track_ids?.length || 0) > 0;
                const isSubtitlesOn = cast.has_text_tracks || hasEmbeddedSubs;
                const isYouTube = cast.source_path?.includes("/youtube/") ?? false;
                const tooltipTitle = cast.has_text_tracks
                  ? "External English subtitles are attached to this cast"
                  : hasEmbeddedSubs
                  ? "Embedded subtitles are active"
                  : isYouTube
                  ? "No subtitles embedded by yt-dlp"
                  : "Download English subtitles from OpenSubtitles";

                return (
                  <button
                    onClick={requestSubtitles}
                    disabled={!cast.source_path || busy === "subtitles" || isSubtitlesOn || isYouTube}
                    className={`flex items-center gap-1.5 rounded border px-4 py-2 hover:bg-emerald-500/10 disabled:opacity-40 ${
                      isSubtitlesOn
                        ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-100"
                        : "border-emerald-500/25"
                    }`}
                    title={tooltipTitle}
                  >
                    {busy === "subtitles" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Subtitles className="h-3.5 w-3.5" />}
                    {isSubtitlesOn ? "subtitles on" : "subtitles"}
                  </button>
                );
              })()}
              <button
                onClick={() => run("stop", daemon.stop)}
                className="flex items-center gap-1.5 rounded border border-emerald-500/25 px-4 py-2 hover:bg-emerald-500/10"
              >
                <Square className="h-3.5 w-3.5" /> stop
              </button>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <button
                onClick={() => run("mute", () => daemon.mute(!cast.muted))}
                className="text-emerald-400 hover:text-emerald-300"
              >
                {cast.muted ? <VolumeX className="h-5 w-5" /> : <Volume2 className="h-5 w-5" />}
              </button>
              <input
                type="range"
                min="0"
                max="100"
                value={(cast.volume ?? 1) * 100}
                onChange={(e) => run("volume", () => daemon.volume(parseInt(e.target.value) / 100))}
                className="flex-1 accent-emerald-500"
              />
            </div>
          </section>
        )}

        {/* conversion progress */}
        {remux && remux.state === "running" && (
          <section className="rounded border border-amber-500/30 bg-amber-500/5 p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2 text-amber-300">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {remux.description}
              </div>
              <button
                onClick={() => run("cancel", daemon.cancelPrepare)}
                className="rounded border border-amber-500/30 px-2 py-1 text-xs text-amber-400 hover:bg-amber-500/20"
              >
                Cancel
              </button>
            </div>
            <div className="h-1 overflow-hidden rounded bg-amber-500/20">
              <div className="h-full bg-amber-400" style={{ width: `${remux.progress * 100}%` }} />
            </div>
            <div className="mt-1 text-right font-mono text-amber-400/70">
              {(remux.progress * 100).toFixed(1)}%
            </div>
          </section>
        )}

        {/* library */}
        <section className="rounded border border-emerald-500/20 bg-black/40 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-emerald-500/50 uppercase tracking-wider">Queue - Local, YouTube</span>
            <div className="flex items-center gap-2">
              <button
                onClick={castQueue}
                disabled={!status?.device || !library.length || busy === "queue"}
                className="flex items-center gap-1.5 rounded border border-emerald-500/30 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-40"
              >
                {busy === "queue" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Cast className="h-3.5 w-3.5" />}
                cast queue
              </button>
              <button
                onClick={loadLibrary}
                className="flex items-center gap-1.5 text-emerald-400/70 hover:text-emerald-300"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${busy === "library" ? "animate-spin" : ""}`} />
                scan
              </button>
            </div>
          </div>

          {library.length === 0 ? (
            <div className="py-4 text-center text-emerald-500/40">
              no files loaded — tap scan
            </div>
          ) : (
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {library.map((item, idx) => (
                <div
                  key={item.path}
                  draggable={true}
                  onDragStart={(e) => handleDragStart(e, idx, 'library')}
                  onDragOver={handleDragOver}
                  onDrop={(e) => handleDrop(e, idx, 'library')}
                  onClick={() => select(item)}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left cursor-pointer hover:bg-emerald-500/10 ${
                    selected?.path === item.path ? "bg-emerald-500/15" : ""
                  }`}
                >
                  <FileVideo className="h-3.5 w-3.5 shrink-0 text-emerald-500/50" />
                  <span className="min-w-0 flex-1 truncate text-emerald-200">{item.rel}</span>
                  <span className="shrink-0 font-mono text-emerald-500/40">
                    {formatBytes(item.size_bytes)}
                  </span>
                  <button
                    onClick={(e) => trashFile(item.path, e)}
                    className="flex items-center gap-1.5 rounded border border-emerald-500/30 px-2 py-1 text-xs hover:bg-emerald-500/20"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Trash (Watched)
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Amazon Queue */}
        <section className="rounded border border-emerald-500/20 bg-black/40 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-emerald-500/50 uppercase tracking-wider">Queue - Amazon</span>
          </div>

          {amazonQueue.length === 0 ? (
            <div className="py-4 text-center text-emerald-500/40">
              amazon queue is empty
            </div>
          ) : (
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {amazonQueue.map((item, idx) => (
                <div
                  key={item.url || idx}
                  draggable={true}
                  onDragStart={(e) => handleDragStart(e, idx, 'amazon')}
                  onDragOver={handleDragOver}
                  onDrop={(e) => handleDrop(e, idx, 'amazon')}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left cursor-pointer hover:bg-emerald-500/10`}
                  onClick={() => {
                     // Optionally cast the amazon url
                     daemon.cast(item.url, true).catch(e => setNotice(String(e)));
                  }}
                >
                  <FileVideo className="h-3.5 w-3.5 shrink-0 text-emerald-500/50" />
                  <span className="min-w-0 flex-1 truncate text-emerald-200">{item.title || item.url}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Trash */}
        <section className="rounded border border-emerald-500/20 bg-black/40 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-emerald-500/50 uppercase tracking-wider">Trash</span>
            <button
              onClick={emptyTrash}
              disabled={!trashItems.length || busy === "empty-trash"}
              className="flex items-center gap-1.5 rounded border border-rose-500/30 px-2 py-1 text-xs text-rose-400 hover:bg-rose-500/20 disabled:opacity-40"
            >
              {busy === "empty-trash" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              empty trash
            </button>
          </div>

          {trashItems.length === 0 ? (
            <div className="py-4 text-center text-emerald-500/40">
              trash is empty
            </div>
          ) : (
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {trashItems.map((item) => (
                <div
                  key={item.path}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left bg-emerald-500/5"
                >
                  <FileVideo className="h-3.5 w-3.5 shrink-0 text-emerald-500/50" />
                  <span className="min-w-0 flex-1 truncate text-emerald-200 line-through opacity-70">{item.rel}</span>
                  <span className="shrink-0 font-mono text-emerald-500/40">
                    {formatBytes(item.size_bytes)}
                  </span>
                  <button
                    onClick={(e) => deleteFile(item.path, e)}
                    className="flex items-center gap-1.5 rounded border border-rose-500/30 px-2 py-1 text-xs text-rose-400 hover:bg-rose-500/20"
                  >
                    Permanently Delete
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* pre-flight */}
        {selected && (
          <section className="space-y-3">
            <div className="text-emerald-500/50 uppercase tracking-wider">pre-flight</div>
            {busy === "preflight" && !report ? (
              <div className="flex items-center gap-2 py-4 text-emerald-500/50">
                <Loader2 className="h-4 w-4 animate-spin" /> probing…
              </div>
            ) : (
              report && <PreflightPanel
                report={report}
                selectedAudioId={selectedAudioId}
                setSelectedAudioId={setSelectedAudioId}
                selectedSubtitleId={selectedSubtitleId}
                setSelectedSubtitleId={setSelectedSubtitleId}
              />
            )}

            <div className="flex gap-2">
              <button
                onClick={() => doCast(false)}
                disabled={!status?.device || busy === "cast"}
                className="flex flex-1 items-center justify-center gap-2 rounded border border-emerald-500/40 bg-emerald-500/10 py-2.5 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
              >
                {busy === "cast" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Cast className="h-4 w-4" />
                )}
                cast
              </button>
              {report?.plan && (
                <button
                  onClick={() =>
                    selected && run("prepare", () => daemon.prepare(selected.path))
                  }
                  disabled={remux?.state === "running"}
                  className="rounded border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-amber-300 hover:bg-amber-500/20 disabled:opacity-40"
                  title={report.plan.description}
                >
                  convert
                </button>
              )}
              {report?.remaster_plan && (
                <button
                  onClick={() =>
                    selected && run("remaster", () => daemon.remaster(selected.path))
                  }
                  disabled={remux?.state === "running"}
                  className="rounded border border-blue-500/40 bg-blue-500/10 px-4 py-2.5 text-blue-300 hover:bg-blue-500/20 disabled:opacity-40 font-bold tracking-wide"
                  title={report.remaster_plan.description}
                >
                  4K Remaster
                </button>
              )}
            </div>
          </section>
        )}

        {/* log */}
        <section className="rounded border border-emerald-500/20 bg-black/60 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-emerald-500/50 uppercase tracking-wider">daemon log</span>
            <div className="flex gap-2">
              <button
                onClick={async () => {
                  try {
                    const text = await daemon.getDiagnosticsLogs();
                    setMaxVerbosityLogs(text);
                  } catch (e) {
                    setNotice("Failed to fetch diagnostics logs");
                  }
                }}
                className="rounded border border-blue-500/30 px-2 py-1 text-xs text-blue-400/70 hover:bg-blue-500/10"
              >
                Maximum Verbosity
              </button>
              <button
                onClick={() => setShowDebugLogs((value) => !value)}
                className="rounded border border-emerald-500/25 px-2 py-1 text-xs text-emerald-400/70 hover:bg-emerald-500/10"
              >
                {showDebugLogs ? "hide debug" : "show debug"}
              </button>
              <button
                onClick={() => {
                  daemon.shutdown().catch(() => {});
                  setOnline(false);
                }}
                className="flex items-center gap-1.5 rounded border border-rose-500/30 px-2 py-1 text-xs text-rose-400 hover:bg-rose-500/10"
              >
                <Power className="h-3 w-3" /> kill server
              </button>
            </div>
          </div>
          <div
            ref={logRef}
            className="max-h-48 space-y-0.5 overflow-y-auto font-mono"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {logs.length === 0 ? (
              <div className="text-emerald-500/30">waiting for events…</div>
            ) : (
              logs.filter((line) => showDebugLogs || line.level !== "debug").map((line) => (
                <div
                  key={line.seq}
                  className={
                    line.level === "warn"
                      ? "text-amber-400/80"
                      : line.level === "debug"
                        ? "text-emerald-500/35"
                        : "text-emerald-400/70"
                  }
                >
                  <span className="text-emerald-500/30">
                    {new Date(line.ts * 1000).toLocaleTimeString([], { hour12: false })}{" "}
                  </span>
                  {line.message}
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {/* Floating Remote FAB */}
      {live && cast && (
        <Drawer>
          <DrawerTrigger asChild>
            <button className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500 text-[#050807] shadow-[0_0_15px_rgba(16,185,129,0.3)] transition-transform hover:scale-105 active:scale-95">
              <Gamepad2 className="h-6 w-6" />
            </button>
          </DrawerTrigger>
          <DrawerContent className="border-emerald-500/20 bg-[#0a100d] text-emerald-300 font-sans">
            <DrawerHeader>
              <DrawerTitle className="text-emerald-400">Remote Control</DrawerTitle>
              <DrawerDescription className="truncate text-emerald-500/60">
                {cast.title || "Now Playing"}
              </DrawerDescription>
            </DrawerHeader>
            <div className="p-6 pt-0 space-y-8">
              {/* Media Progress */}
              <div className="space-y-3">
                <div
                  className="h-3 overflow-hidden rounded-full bg-emerald-500/15 cursor-pointer"
                  onClick={(e) => {
                    if (!cast || !cast.duration) return;
                    const rect = e.currentTarget.getBoundingClientRect();
                    const percent = (e.clientX - rect.left) / rect.width;
                    run("seek", () => daemon.seek(percent * cast.duration!));
                  }}
                >
                  <div
                    className="h-full bg-emerald-400 transition-all pointer-events-none"
                    style={{
                      width: `${cast.duration ? Math.min((cast.position / cast.duration) * 100, 100) : 0}%`,
                    }}
                  />
                </div>
                <div className="flex justify-between font-mono text-sm text-emerald-500/60">
                  <span>{formatDuration(cast.position)}</span>
                  <span>{formatDuration(cast.duration)}</span>
                </div>
              </div>

              {/* Transport Controls */}
              <div className="flex items-center justify-center gap-8">
                <button
                  onClick={() => run("seek-back", () => daemon.seek(Math.max(0, cast.position - 10)))}
                  className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 active:scale-95"
                >
                  <Rewind className="h-6 w-6" />
                </button>

                <button
                  onClick={() => run("toggle", cast.state === "paused" ? daemon.play : daemon.pause)}
                  className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-500 text-[#050807] hover:bg-emerald-400 active:scale-95"
                >
                  {cast.state === "paused" ? (
                    <Play className="h-10 w-10 ml-1" />
                  ) : (
                    <Pause className="h-10 w-10" />
                  )}
                </button>

                <button
                  onClick={() => run("seek-forward", () => daemon.seek(Math.min(cast.duration || 0, cast.position + 10)))}
                  className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 active:scale-95"
                >
                  <FastForward className="h-6 w-6" />
                </button>
              </div>

              {/* Volume & Stop */}
              <div className="flex items-center gap-4 pb-4">
                <button
                  onClick={() => run("mute", () => daemon.mute(!cast.muted))}
                  className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 active:scale-95"
                >
                  {cast.muted ? <VolumeX className="h-5 w-5" /> : <Volume2 className="h-5 w-5" />}
                </button>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={(cast.volume ?? 1) * 100}
                  onChange={(e) => run("volume", () => daemon.volume(parseInt(e.target.value) / 100))}
                  className="flex-1 accent-emerald-500"
                />
                <button
                  onClick={() => run("stop", daemon.stop)}
                  className="flex h-10 w-10 items-center justify-center rounded-full border border-rose-500/30 text-rose-400 hover:bg-rose-500/10 active:scale-95"
                >
                  <Square className="h-4 w-4" />
                </button>
              </div>
            </div>
          </DrawerContent>
        </Drawer>
      )}

      {/* Gamified Telemetry Modal */}
      {anomaly && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-amber-500/50 bg-[#0a100d] p-6 shadow-[0_0_30px_rgba(245,158,11,0.15)]">
            <div className="mb-4 flex items-center gap-3 text-amber-400">
              <CircleAlert className="h-8 w-8" />
              <h2 className="text-xl font-bold tracking-wide">Rare Anomaly Discovered!</h2>
            </div>
            <div className="mb-6 space-y-3 text-sm text-emerald-100/80">
              <p>
                You've stumbled upon a highly complex streaming architecture at <span className="font-mono text-amber-300">{anomaly.domain}</span> that our engine hasn't seen before.
              </p>
              <p>
                We have captured a diagnostic signature. Would you like to submit this to the developers and get credited as a Contributor?
              </p>
            </div>
            <div className="flex flex-col gap-3">
              <button
                onClick={() => {
                  const issueTitle = encodeURIComponent(`Anomaly Report: ${anomaly.domain}`);
                  const issueBody = encodeURIComponent(`I encountered an anomaly while casting.\n\n\`\`\`json\n${JSON.stringify(anomaly, null, 2)}\n\`\`\`\n\n_Submitted via CastCast Telemetry Engine_`);
                  window.open(`https://github.com/1456319/openchromecast/issues/new?title=${issueTitle}&body=${issueBody}`, "_blank");
                  setAnomaly(null);
                }}
                className="rounded-lg border border-amber-500/50 bg-amber-500/20 py-3 font-bold text-amber-300 transition-colors hover:bg-amber-500/30"
              >
                Submit & Claim Credit
              </button>
              <button
                onClick={() => setAnomaly(null)}
                className="rounded-lg border border-emerald-500/20 px-4 py-3 text-emerald-500/60 hover:bg-emerald-500/10"
              >
                Ignore
              </button>
            </div>
          </div>
        </div>
      )}

      {maxVerbosityLogs !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-4xl max-h-[90vh] flex flex-col rounded-xl border border-blue-500/50 bg-[#0a100d] p-6 shadow-[0_0_30px_rgba(59,130,246,0.15)]">
            <div className="mb-4 flex items-center justify-between text-blue-400">
              <h2 className="text-xl font-bold tracking-wide">Maximum Verbosity Diagnostics</h2>
              <button
                onClick={() => setMaxVerbosityLogs(null)}
                className="text-blue-500/60 hover:text-blue-400"
              >
                Close
              </button>
            </div>
            <div className="flex-1 overflow-auto rounded bg-black/60 p-4 font-mono text-sm text-blue-300/80">
              <pre className="whitespace-pre-wrap">{maxVerbosityLogs}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
