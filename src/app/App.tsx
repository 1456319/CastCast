import { useRootScanner } from "./hooks/useRootScanner";
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
  ShieldAlert,
} from "lucide-react";

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
  const {
    streamState,
    streamInfo,
    metrics,
    scanLog,
    hasRoot,
    requestRootAccess,
    startScan,
    reset
  } = useRootScanner();

  const [showDetails, setShowDetails] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const is4k = streamInfo ? streamInfo.width >= 3840 : false;

  const liveBuffer = metrics.bufferHealth;
  const liveNetwork = metrics.networkSpeed;

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
        className="relative w-full max-w-sm bg-[#07090d] rounded-[2.5rem] overflow-hidden flex flex-col"
        style={{
          boxShadow:
            "0 0 0 1px rgba(0,232,122,0.08), 0 0 80px rgba(0,232,122,0.04), 0 32px 64px rgba(0,0,0,0.8)",
          minHeight: 780,
          maxHeight: 850
        }}
      >
        {/* Notch bar */}
        <div className="flex items-center justify-between px-6 pt-4 pb-2 shrink-0">
          <span className="text-[10px] font-mono text-muted-foreground">9:41</span>
          <div className="w-20 h-5 rounded-full bg-black flex items-center justify-center mx-auto">
            <div className="w-2.5 h-2.5 rounded-full bg-[#0e1420]" />
          </div>
          <div className="flex items-center gap-1">
            <Wifi size={10} className="text-muted-foreground" />
            <span className="text-[10px] font-mono text-muted-foreground">LTE</span>
          </div>
        </div>

        <div className="px-5 pb-8 flex flex-col gap-4 flex-1 overflow-y-auto scrollbar-none">
          {/* Header */}
          <div className="flex items-center justify-between mt-1 shrink-0">
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

          {/* Root status banner (if denied) */}
          <AnimatePresence>
            {streamState === "root_denied" && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 flex items-start gap-3"
                >
                  <ShieldAlert size={16} className="text-red-400 mt-0.5 shrink-0" />
                  <div className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-red-400">Root Access Denied</span>
                    <span className="text-[10px] text-red-400/80 leading-relaxed">
                      The daemon requires root permissions to hook into media.extractor. Please grant access in Magisk/KernelSU.
                    </span>
                  </div>
                </motion.div>
            )}
          </AnimatePresence>

          {/* Main resolution display */}
          <div className="relative bg-[#0e1420] rounded-xl border border-border overflow-hidden shrink-0">
            {streamState === "scanning" && <ScanLine />}

            <div className="p-5 flex flex-col items-center gap-3">
              {/* Status indicator */}
              <div className="flex items-center gap-2">
                <div className="relative flex items-center justify-center w-2.5 h-2.5">
                  <div
                    className={`w-2 h-2 rounded-full transition-colors duration-500 ${
                      streamState === "active"
                        ? "bg-[#00e87a]"
                        : streamState === "scanning" || streamState === "requesting_root"
                        ? "bg-amber-400"
                        : streamState === "root_denied" || streamState === "error"
                        ? "bg-red-500"
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
                  {streamState === "idle" || streamState === "root_denied"
                    ? "No active stream"
                    : streamState === "requesting_root"
                    ? "Waiting for SU..."
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
                  ) : streamState === "scanning" || streamState === "requesting_root" ? (
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
                        {streamState === "requesting_root" ? "Waiting for SU prompt..." : "Analyzing codec pipeline..."}
                      </span>
                    </motion.div>
                  ) : (
                    <motion.div
                      key="idle"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="flex flex-col items-center gap-3 py-4"
                    >
                      <Activity size={32} className="text-muted-foreground/20" />
                      <span className="text-xs text-muted-foreground/50 max-w-[200px] leading-relaxed">
                        Ready to intercept MediaCodec API buffers via root.
                      </span>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>

          {/* Quick stats grid */}
          <AnimatePresence>
            {streamState === "active" && streamInfo && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ delay: 0.15 }}
                className="grid grid-cols-2 gap-2 shrink-0"
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
                className="bg-[#0e1420] rounded-xl border border-border px-4 py-3 flex flex-col gap-2 shrink-0"
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
                className="bg-[#0e1420] rounded-xl border border-border overflow-hidden shrink-0"
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
                className="bg-black rounded-xl border border-[#00e87a]/10 overflow-hidden shrink-0"
              >
                <div className="px-3 py-2 border-b border-[#00e87a]/8 flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-[#00e87a] animate-pulse" />
                  <span className="text-[9px] font-mono text-[#00e87a]/60 uppercase tracking-widest">
                    Root IPC log
                  </span>
                </div>
                <div
                  ref={logRef}
                  className="px-3 py-2 max-h-36 overflow-y-auto space-y-0.5 scrollbar-none"
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

          <div className="flex-1" />

          {/* CTA buttons */}
          <div className="flex gap-2 mt-auto shrink-0 pb-2">
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
            ) : streamState === "idle" || streamState === "root_denied" ? (
              <button
                onClick={requestRootAccess}
                className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl text-sm font-bold transition-all duration-200"
                style={{
                  background: "linear-gradient(135deg, #00e87a 0%, #00c965 100%)",
                  color: "#020a04",
                  boxShadow: "0 4px 24px rgba(0,232,122,0.25)",
                }}
              >
                {hasRoot ? <Activity size={16} /> : <ShieldAlert size={16} />}
                {hasRoot ? "Scan Active Stream" : "Grant Root & Scan"}
              </button>
            ) : (
                <button
                    disabled
                    className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl text-sm font-bold transition-all duration-200 opacity-50 cursor-not-allowed"
                    style={{
                      background: "rgba(0,232,122,0.08)",
                      color: "#00e87a",
                    }}
                >
                    <RefreshCw size={14} className="animate-spin" />
                    {streamState === "requesting_root" ? "Requesting access..." : "Scanning stream..."}
                </button>
            )}
          </div>

          <p className="text-center text-[9px] font-mono text-muted-foreground/40 mt-1 shrink-0">
            Pixel 10 XL Pro · Android 16 · MediaCodec API
          </p>
        </div>
      </div>
    </div>
  );
}