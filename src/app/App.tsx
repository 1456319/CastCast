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
  RefreshCw,
  Search,
  Square,
  Subtitles,
  Wifi,
  Trash2,
  Volume2,
  VolumeX,
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
import { TERMUX_MANUAL_COMMAND, launchTermuxDaemon } from "./lib/termux-daemon";

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
  const [selected, setSelected] = useState<LibraryItem | null>(null);
  const [report, setReport] = useState<Preflight | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [showDebugLogs, setShowDebugLogs] = useState(false);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [host, setHost] = useState("192.168.1.50");
  const [notice, setNotice] = useState<string | null>(null);
  const [launchMessage, setLaunchMessage] = useState<string | null>(null);

  const logRef = useRef<HTMLDivElement>(null);

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
      setNotice(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const launchDaemon = () =>
    run("launch-daemon", async () => {
      setLaunchMessage("Sending Termux RUN_COMMAND intent…");
      const result = await launchTermuxDaemon();
      setLaunchMessage(
        `Root configured Termux and sent launch request. Waiting for ${DAEMON_BASE}. Audit log: ${result.auditLog ?? "Download/Chromecast/.castcast/audit.log"}. ${result.note ?? ""}`.trim(),
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
    });

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
      const result = await daemon.cast(selected.path, allowUnsafe);
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
          <div className="flex items-center gap-2 font-mono text-emerald-500/60">
            <Wifi className="h-3.5 w-3.5" />
            {status?.media_server.lan_ip}:{status?.media_server.port}
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
              <button
                onClick={requestSubtitles}
                disabled={!cast.source_path || busy === "subtitles" || cast.has_text_tracks}
                className={`flex items-center gap-1.5 rounded border px-4 py-2 hover:bg-emerald-500/10 disabled:opacity-40 ${
                  cast.has_text_tracks
                    ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-100"
                    : "border-emerald-500/25"
                }`}
                title={cast.has_text_tracks ? "English subtitles are attached to this cast" : "Download English subtitles from OpenSubtitles"}
              >
                {busy === "subtitles" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Subtitles className="h-3.5 w-3.5" />}
                {cast.has_text_tracks ? "subtitles on" : "subtitles"}
              </button>
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
            <span className="text-emerald-500/50 uppercase tracking-wider">Queue</span>
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
              {library.map((item) => (
                <div
                  key={item.path}
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
              report && <PreflightPanel report={report} />
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
                >
                  convert
                </button>
              )}
            </div>
          </section>
        )}

        {/* log */}
        <section className="rounded border border-emerald-500/20 bg-black/60 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-emerald-500/50 uppercase tracking-wider">daemon log</span>
            <button
              onClick={() => setShowDebugLogs((value) => !value)}
              className="rounded border border-emerald-500/25 px-2 py-1 text-xs text-emerald-400/70 hover:bg-emerald-500/10"
            >
              {showDebugLogs ? "hide debug" : "show debug"}
            </button>
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
    </div>
  );
}
