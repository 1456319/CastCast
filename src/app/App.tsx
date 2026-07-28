import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Wifi,
  Shield,
  Activity,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Zap,
  Lock,
} from "lucide-react";

type StreamState = "idle" | "scanning" | "active" | "error";

interface StreamInfo {
  width: number;
  height: number;
  fps: number;
  hdr: string;
  codec: string;
  bitrate: number;
  widevineLevel: string;
  drm: string;
  container: string;
  colorSpace: string;
  audioCodec: string;
  audioChannels: string;
  bufferHealth: number;
  networkSpeed: number;
}

const STREAM_PRESETS: StreamInfo[] = [
  {
    width: 3840,
    height: 2160,
    fps: 23.976,
    hdr: "Dolby Vision",
    codec: "H.265 / HEVC",
    bitrate: 15.8,
    widevineLevel: "L1",
    drm: "Widevine CDM",
    container: "CMAF/fMP4",
    colorSpace: "BT.2020 / PQ",
    audioCodec: "Dolby Atmos (E-AC3)",
    audioChannels: "7.1",
    bufferHealth: 94,
    networkSpeed: 42.3,
  },
  {
    width: 1920,
    height: 1080,
    fps: 23.976,
    hdr: "SDR",
    codec: "H.264 / AVC",
    bitrate: 6.2,
    widevineLevel: "L1",
    drm: "Widevine CDM",
    container: "CMAF/fMP4",
    colorSpace: "BT.709",
    audioCodec: "AAC-LC",
    audioChannels: "5.1",
    bufferHealth: 78,
    networkSpeed: 18.6,
  },
];

function useAnimatedNumber(target: number, active: boolean, decimals = 0) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!active) { setValue(0); return; }
    const start = performance.now();
    const duration = 900;
    const from = 0;
    const raf = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - t, 3);
      setValue(from + (target - from) * ease);
      if (t < 1) requestAnimationFrame(raf);
    };
    requestAnimationFrame(raf);
  }, [target, active]);
  return value.toFixed(decimals);
}

function PulseRing({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <span className="absolute inset-0 rounded-full">
      <span className="absolute inset-0 rounded-full animate-ping bg-[#00e87a]/20" />
    </span>
  );
}

function ResolutionBadge({ width, height }: { width: number; height: number }) {
  const is4k = width >= 3840 && height >= 2160;
  const is1080p = width >= 1920 && height >= 1080;
  const label = is4k ? "4K UHD" : is1080p ? "Full HD" : "HD";
  const color = is4k
    ? "text-[#00e87a] border-[#00e87a]/40 bg-[#00e87a]/8"
    : is1080p
    ? "text-amber-400 border-amber-400/40 bg-amber-400/8"
    : "text-red-400 border-red-400/40 bg-red-400/8";

  return (
    <span
      className={`font-mono text-[10px] font-bold tracking-widest border px-2 py-0.5 rounded ${color}`}
    >
      {label}
    </span>
  );
}

function ScanLine() {
  return (
    <div className="absolute inset-0 overflow-hidden rounded-xl pointer-events-none">
      <motion.div
        className="absolute left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#00e87a]/60 to-transparent"
        initial={{ top: "0%" }}
        animate={{ top: "100%" }}
        transition={{ duration: 2.4, repeat: Infinity, ease: "linear" }}
      />
    </div>
  );
}

function StatRow({
  label,
  value,
  accent,
  mono = true,
}: {
  label: string;
  value: string;
  accent?: boolean;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[#00e87a]/6 last:border-b-0">
      <span className="text-xs text-muted-foreground tracking-wide uppercase font-medium" style={{ fontFamily: "Exo 2, sans-serif" }}>
        {label}
      </span>
      <span
        className={`text-xs ${accent ? "text-[#00e87a]" : "text-foreground"} ${mono ? "font-mono" : ""} font-medium`}
      >
        {value}
      </span>
    </div>
  );
}

function SegmentBar({ value, max = 100, color = "#00e87a" }: { value: number; max?: number; color?: string }) {
  const pct = Math.min((value / max) * 100, 100);
  const segs = 20;
  const filled = Math.round((pct / 100) * segs);
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: segs }).map((_, i) => (
        <div
          key={i}
          className="h-1.5 flex-1 rounded-[1px] transition-all duration-300"
          style={{
            background: i < filled ? color : "rgba(255,255,255,0.06)",
          }}
        />
      ))}
    </div>
  );
}

export default function App() {
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [streamInfo, setStreamInfo] = useState<StreamInfo | null>(null);
  const [scanLog, setScanLog] = useState<string[]>([]);
  const [showDetails, setShowDetails] = useState(false);
  const [presetIdx, setPresetIdx] = useState(0);
  const [tick, setTick] = useState(0);
  const logRef = useRef<HTMLDivElement>(null);

  const is4k = streamInfo ? streamInfo.width >= 3840 : false;

  useEffect(() => {
    if (streamState !== "active") return;
    const id = setInterval(() => setTick((t) => t + 1), 2000);
    return () => clearInterval(id);
  }, [streamState]);

  const liveBuffer = streamInfo
    ? Math.max(60, Math.min(100, streamInfo.bufferHealth + (Math.random() * 6 - 3)))
    : 0;
  const liveNetwork = streamInfo
    ? Math.max(5, streamInfo.networkSpeed + (Math.random() * 4 - 2))
    : 0;

  function appendLog(msg: string) {
    const ts = new Date().toISOString().slice(11, 23);
    setScanLog((prev) => [...prev.slice(-40), `[${ts}] ${msg}`]);
  }

  function startScan() {
    const preset = STREAM_PRESETS[presetIdx];
    setStreamState("scanning");
    setStreamInfo(null);
    setScanLog([]);

    const steps = [
      { delay: 200, msg: "Attaching to media.extractor via root IPC..." },
      { delay: 500, msg: "Enumerating MediaCodec pipeline..." },
      { delay: 900, msg: `DRM session detected: ${preset.drm}` },
      { delay: 1200, msg: `Widevine security level: ${preset.widevineLevel}` },
      { delay: 1500, msg: `Video track: ${preset.codec}` },
      { delay: 1800, msg: `Decoded resolution: ${preset.width}×${preset.height}` },
      { delay: 2000, msg: `Frame rate: ${preset.fps} fps` },
      { delay: 2200, msg: `HDR metadata: ${preset.hdr}` },
      { delay: 2500, msg: `Bitrate: ${preset.bitrate} Mbps` },
      { delay: 2800, msg: "Stream analysis complete." },
    ];

    steps.forEach(({ delay, msg }) => {
      setTimeout(() => appendLog(msg), delay);
    });

    setTimeout(() => {
      setStreamInfo(preset);
      setStreamState("active");
    }, 3000);
  }

  function reset() {
    setStreamState("idle");
    setStreamInfo(null);
    setScanLog([]);
    setShowDetails(false);
  }

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [scanLog]);

  const animW = useAnimatedNumber(streamInfo?.width ?? 0, streamState === "active");
  const animH = useAnimatedNumber(streamInfo?.height ?? 0, streamState === "active");

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center bg-[#07090d] p-4"
      style={{ fontFamily: "Exo 2, sans-serif" }}
    >
      {/* Phone shell */}
      <div
        className="relative w-full max-w-sm bg-[#07090d] rounded-[2.5rem] overflow-hidden"
        style={{
          boxShadow:
            "0 0 0 1px rgba(0,232,122,0.08), 0 0 80px rgba(0,232,122,0.04), 0 32px 64px rgba(0,0,0,0.8)",
          minHeight: 780,
        }}
      >
        {/* Notch bar */}
        <div className="flex items-center justify-between px-6 pt-4 pb-2">
          <span className="text-[10px] font-mono text-muted-foreground">9:41</span>
          <div className="w-20 h-5 rounded-full bg-black flex items-center justify-center mx-auto">
            <div className="w-2.5 h-2.5 rounded-full bg-[#0e1420]" />
          </div>
          <div className="flex items-center gap-1">
            <Wifi size={10} className="text-muted-foreground" />
            <span className="text-[10px] font-mono text-muted-foreground">LTE</span>
          </div>
        </div>

        <div className="px-5 pb-8 flex flex-col gap-4">
          {/* Header */}
          <div className="flex items-center justify-between mt-1">
            <div>
              <h1
                className="text-lg font-bold text-foreground leading-tight tracking-tight"
                style={{ fontFamily: "Exo 2, sans-serif" }}
              >
                Stream Inspector
              </h1>
              <p className="text-[10px] text-muted-foreground font-mono tracking-widest uppercase mt-0.5">
                Root · MediaCodec
              </p>
            </div>
            <div className="flex items-center gap-1.5 bg-[#00e87a]/10 border border-[#00e87a]/25 rounded-full px-2.5 py-1">
              <Lock size={9} className="text-[#00e87a]" />
              <span className="text-[9px] font-mono font-bold text-[#00e87a] tracking-wider">ROOT</span>
            </div>
          </div>

          {/* Preset selector */}
          {streamState === "idle" && (
            <div className="flex gap-2">
              {STREAM_PRESETS.map((p, i) => (
                <button
                  key={i}
                  onClick={() => setPresetIdx(i)}
                  className={`flex-1 py-2 px-3 rounded-lg border text-xs font-mono transition-all duration-200 ${
                    presetIdx === i
                      ? "bg-[#00e87a]/10 border-[#00e87a]/40 text-[#00e87a]"
                      : "bg-[#0e1420] border-border text-muted-foreground hover:border-[#00e87a]/20"
                  }`}
                >
                  {p.width}×{p.height}
                </button>
              ))}
            </div>
          )}

          {/* Main resolution display */}
          <div className="relative bg-[#0e1420] rounded-xl border border-border overflow-hidden">
            {streamState === "scanning" && <ScanLine />}

            <div className="p-5 flex flex-col items-center gap-3">
              {/* Status indicator */}
              <div className="flex items-center gap-2">
                <div className="relative flex items-center justify-center w-2.5 h-2.5">
                  <div
                    className={`w-2 h-2 rounded-full transition-colors duration-500 ${
                      streamState === "active"
                        ? "bg-[#00e87a]"
                        : streamState === "scanning"
                        ? "bg-amber-400"
                        : "bg-[#1e293b]"
                    }`}
                  />
                  {streamState === "active" && (
                    <span className="absolute inset-0">
                      <span className="absolute inset-0 rounded-full animate-ping bg-[#00e87a]/40" />
                    </span>
                  )}
                </div>
                <span className="text-[10px] font-mono tracking-widest uppercase text-muted-foreground">
                  {streamState === "idle"
                    ? "No active stream"
                    : streamState === "scanning"
                    ? "Scanning..."
                    : "Stream detected"}
                </span>
              </div>

              {/* Resolution readout */}
              <div className="text-center">
                <AnimatePresence mode="wait">
                  {streamState === "active" && streamInfo ? (
                    <motion.div
                      key="res"
                      initial={{ opacity: 0, scale: 0.85 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.85 }}
                      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                      className="flex flex-col items-center gap-2"
                    >
                      <span
                        className="text-5xl font-bold leading-none tracking-tighter"
                        style={{
                          fontFamily: "JetBrains Mono, monospace",
                          color: is4k ? "#00e87a" : "#f59e0b",
                          textShadow: is4k
                            ? "0 0 40px rgba(0,232,122,0.4)"
                            : "0 0 40px rgba(245,158,11,0.4)",
                        }}
                      >
                        {animW}
                        <span className="text-2xl text-muted-foreground mx-1">×</span>
                        {animH}
                      </span>
                      <ResolutionBadge width={streamInfo.width} height={streamInfo.height} />
                    </motion.div>
                  ) : streamState === "scanning" ? (
                    <motion.div
                      key="scanning"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="flex flex-col items-center gap-3 py-2"
                    >
                      <div className="flex gap-1.5">
                        {[0, 1, 2, 3].map((i) => (
                          <motion.div
                            key={i}
                            className="w-1.5 h-6 rounded-full bg-[#00e87a]/30"
                            animate={{ scaleY: [0.3, 1, 0.3] }}
                            transition={{
                              duration: 0.8,
                              repeat: Infinity,
                              delay: i * 0.15,
                            }}
                          />
                        ))}
                      </div>
                      <span className="text-xs font-mono text-muted-foreground">
                        Analyzing codec pipeline...
                      </span>
                    </motion.div>
                  ) : (
                    <motion.div
                      key="idle"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="flex flex-col items-center gap-1 py-4"
                    >
                      <span
                        className="text-5xl font-bold text-[#1e293b]"
                        style={{ fontFamily: "JetBrains Mono, monospace" }}
                      >
                        ----
                      </span>
                      <span className="text-xs text-muted-foreground font-mono">
                        Tap scan to detect stream
                      </span>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* 4K verdict banner */}
              <AnimatePresence>
                {streamState === "active" && streamInfo && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 8 }}
                    transition={{ delay: 0.3, duration: 0.35 }}
                    className={`w-full rounded-lg px-4 py-2.5 flex items-center gap-3 ${
                      is4k
                        ? "bg-[#00e87a]/8 border border-[#00e87a]/20"
                        : "bg-amber-400/8 border border-amber-400/20"
                    }`}
                  >
                    {is4k ? (
                      <CheckCircle2 size={16} className="text-[#00e87a] shrink-0" />
                    ) : (
                      <AlertTriangle size={16} className="text-amber-400 shrink-0" />
                    )}
                    <div className="flex flex-col">
                      <span
                        className={`text-xs font-bold ${is4k ? "text-[#00e87a]" : "text-amber-400"}`}
                        style={{ fontFamily: "Exo 2, sans-serif" }}
                      >
                        {is4k ? "Confirmed 4K playback" : "Not playing in 4K"}
                      </span>
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {is4k
                          ? `${streamInfo.hdr} · Widevine ${streamInfo.widevineLevel} · ${streamInfo.bitrate} Mbps`
                          : `Actual: ${streamInfo.width}×${streamInfo.height} — check title availability`}
                      </span>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>

          {/* Widevine + DRM status */}
          <AnimatePresence>
            {streamState === "active" && streamInfo && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ delay: 0.15 }}
                className="grid grid-cols-2 gap-2"
              >
                {[
                  {
                    icon: Shield,
                    label: "Widevine",
                    value: streamInfo.widevineLevel,
                    ok: streamInfo.widevineLevel === "L1",
                  },
                  {
                    icon: Zap,
                    label: "HDR",
                    value: streamInfo.hdr,
                    ok: streamInfo.hdr !== "SDR",
                  },
                  {
                    icon: Activity,
                    label: "Bitrate",
                    value: `${streamInfo.bitrate} Mb/s`,
                    ok: streamInfo.bitrate > 10,
                  },
                  {
                    icon: Wifi,
                    label: "Codec",
                    value: streamInfo.codec.split(" / ")[1] ?? streamInfo.codec,
                    ok: true,
                  },
                ].map(({ icon: Icon, label, value, ok }) => (
                  <div
                    key={label}
                    className="bg-[#0e1420] rounded-lg border border-border p-3 flex flex-col gap-1.5"
                  >
                    <div className="flex items-center justify-between">
                      <Icon size={11} className="text-muted-foreground" />
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${ok ? "bg-[#00e87a]" : "bg-amber-400"}`}
                      />
                    </div>
                    <span className="text-[9px] uppercase tracking-widest text-muted-foreground font-medium">
                      {label}
                    </span>
                    <span className="text-xs font-mono font-bold text-foreground leading-tight">
                      {value}
                    </span>
                  </div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Buffer health */}
          <AnimatePresence>
            {streamState === "active" && streamInfo && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ delay: 0.25 }}
                className="bg-[#0e1420] rounded-xl border border-border px-4 py-3 flex flex-col gap-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
                    Buffer Health
                  </span>
                  <span className="text-[10px] font-mono text-[#00e87a]">
                    {liveBuffer.toFixed(0)}%
                  </span>
                </div>
                <SegmentBar value={liveBuffer} />
                <div className="flex items-center justify-between mt-0.5">
                  <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
                    Network
                  </span>
                  <span className="text-[10px] font-mono text-foreground">
                    {liveNetwork.toFixed(1)} Mbps
                  </span>
                </div>
                <SegmentBar
                  value={liveNetwork}
                  max={60}
                  color={liveNetwork > 25 ? "#00e87a" : liveNetwork > 10 ? "#f59e0b" : "#ef4444"}
                />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Extended details */}
          <AnimatePresence>
            {streamState === "active" && streamInfo && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ delay: 0.3 }}
                className="bg-[#0e1420] rounded-xl border border-border overflow-hidden"
              >
                <button
                  onClick={() => setShowDetails((d) => !d)}
                  className="w-full flex items-center justify-between px-4 py-3 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                >
                  <span className="uppercase tracking-widest text-[10px]">Full stream details</span>
                  {showDetails ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>
                <AnimatePresence>
                  {showDetails && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.25 }}
                      className="overflow-hidden"
                    >
                      <div className="px-4 pb-4 flex flex-col">
                        <StatRow label="Resolution" value={`${streamInfo.width}×${streamInfo.height}`} accent />
                        <StatRow label="Frame Rate" value={`${streamInfo.fps} fps`} />
                        <StatRow label="Video Codec" value={streamInfo.codec} />
                        <StatRow label="Container" value={streamInfo.container} />
                        <StatRow label="Color Space" value={streamInfo.colorSpace} />
                        <StatRow label="HDR Format" value={streamInfo.hdr} accent={streamInfo.hdr !== "SDR"} />
                        <StatRow label="Peak Bitrate" value={`${streamInfo.bitrate} Mbps`} />
                        <StatRow label="Audio Codec" value={streamInfo.audioCodec} />
                        <StatRow label="Audio Ch." value={streamInfo.audioChannels} />
                        <StatRow label="DRM System" value={streamInfo.drm} />
                        <StatRow label="Widevine SL" value={`Level ${streamInfo.widevineLevel}`} accent={streamInfo.widevineLevel === "L1"} />
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Scan log */}
          <AnimatePresence>
            {scanLog.length > 0 && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="bg-black rounded-xl border border-[#00e87a]/10 overflow-hidden"
              >
                <div className="px-3 py-2 border-b border-[#00e87a]/8 flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-[#00e87a] animate-pulse" />
                  <span className="text-[9px] font-mono text-[#00e87a]/60 uppercase tracking-widest">
                    Root IPC log
                  </span>
                </div>
                <div
                  ref={logRef}
                  className="px-3 py-2 max-h-28 overflow-y-auto space-y-0.5 scrollbar-none"
                >
                  {scanLog.map((line, i) => (
                    <p key={i} className="text-[9px] font-mono text-[#00e87a]/70 leading-relaxed">
                      {line}
                    </p>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* CTA buttons */}
          <div className="flex gap-2 mt-1">
            {streamState === "active" || streamState === "error" ? (
              <>
                <button
                  onClick={reset}
                  className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-[#0e1420] border border-border text-xs font-semibold text-muted-foreground hover:text-foreground hover:border-[#00e87a]/20 transition-all"
                >
                  <XCircle size={13} />
                  Reset
                </button>
                <button
                  onClick={startScan}
                  className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-[#00e87a]/10 border border-[#00e87a]/30 text-xs font-semibold text-[#00e87a] hover:bg-[#00e87a]/15 transition-all"
                >
                  <RefreshCw size={13} />
                  Re-scan
                </button>
              </>
            ) : (
              <button
                onClick={startScan}
                disabled={streamState === "scanning"}
                className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl text-sm font-bold transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  background:
                    streamState === "scanning"
                      ? "rgba(0,232,122,0.08)"
                      : "linear-gradient(135deg, #00e87a 0%, #00c965 100%)",
                  color: streamState === "scanning" ? "#00e87a" : "#020a04",
                  boxShadow:
                    streamState === "scanning" ? "none" : "0 4px 24px rgba(0,232,122,0.25)",
                }}
              >
                {streamState === "scanning" ? (
                  <>
                    <RefreshCw size={14} className="animate-spin" />
                    Scanning stream...
                  </>
                ) : (
                  <>
                    <Activity size={14} />
                    Scan Active Stream
                  </>
                )}
              </button>
            )}
          </div>

          <p className="text-center text-[9px] font-mono text-muted-foreground/40 mt-1">
            Pixel 10 XL Pro · Android 16 · MediaCodec API
          </p>
        </div>
      </div>
    </div>
  );
}
