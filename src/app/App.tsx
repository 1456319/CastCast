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
  Wifi,
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
  const [selected, setSelected] = useState<LibraryItem | null>(null);
  const [report, setReport] = useState<Preflight | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [host, setHost] = useState("192.168.1.50");
  const [notice, setNotice] = useState<string | null>(null);

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

  const loadLibrary = () =>
    run("library", async () => {
      const { items } = await daemon.library(false);
      setLibrary(items);
    });

  const select = (item: LibraryItem) =>
    run("preflight", async () => {
      setSelected(item);
      setReport(null);
      setReport(await daemon.preflight(item.path));
    });

  const doCast = (allowUnsafe = false) =>
    selected &&
    run("cast", async () => {
      const result = await daemon.cast(selected.path, allowUnsafe);
      if (result.error) setNotice(result.error);
      if (result.converting) setNotice("Conversion started — cast again when it finishes.");
      setReport((prev) => ({ ...(prev || {}), ...result } as Preflight));
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
          <pre className="overflow-x-auto rounded border border-emerald-500/25 bg-black/60 p-3 font-mono text-emerald-300/80">
{`pkg install python ffmpeg
termux-setup-storage
python -m castcast serve`}
          </pre>
          <div className="font-mono text-emerald-500/50">expecting: {DAEMON_BASE}</div>
          <button
            onClick={refreshStatus}
            className="rounded border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-emerald-300 hover:bg-emerald-500/20"
          >
            retry
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
            <div className="mb-2 h-1 overflow-hidden rounded bg-emerald-500/15">
              <div
                className="h-full bg-emerald-400 transition-all"
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
                onClick={() => run("stop", daemon.stop)}
                className="flex items-center gap-1.5 rounded border border-emerald-500/25 px-4 py-2 hover:bg-emerald-500/10"
              >
                <Square className="h-3.5 w-3.5" /> stop
              </button>
            </div>
          </section>
        )}

        {/* conversion progress */}
        {remux && remux.state === "running" && (
          <section className="rounded border border-amber-500/30 bg-amber-500/5 p-3">
            <div className="mb-2 flex items-center gap-2 text-amber-300">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {remux.description}
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
            <span className="text-emerald-500/50 uppercase tracking-wider">library</span>
            <button
              onClick={loadLibrary}
              className="flex items-center gap-1.5 text-emerald-400/70 hover:text-emerald-300"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${busy === "library" ? "animate-spin" : ""}`} />
              scan
            </button>
          </div>

          {library.length === 0 ? (
            <div className="py-4 text-center text-emerald-500/40">
              no files loaded — tap scan
            </div>
          ) : (
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {library.map((item) => (
                <button
                  key={item.path}
                  onClick={() => select(item)}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-emerald-500/10 ${
                    selected?.path === item.path ? "bg-emerald-500/15" : ""
                  }`}
                >
                  <FileVideo className="h-3.5 w-3.5 shrink-0 text-emerald-500/50" />
                  <span className="min-w-0 flex-1 truncate text-emerald-200">{item.rel}</span>
                  <span className="shrink-0 font-mono text-emerald-500/40">
                    {formatBytes(item.size_bytes)}
                  </span>
                </button>
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
          <div className="mb-2 text-emerald-500/50 uppercase tracking-wider">daemon log</div>
          <div
            ref={logRef}
            className="max-h-48 space-y-0.5 overflow-y-auto font-mono"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {logs.length === 0 ? (
              <div className="text-emerald-500/30">waiting for events…</div>
            ) : (
              logs.map((line) => (
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
