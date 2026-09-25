import { AlertTriangle, CheckCircle2, Info, Terminal, XCircle } from "lucide-react";
import type { Preflight } from "../lib/daemon";
import { formatDuration } from "../lib/daemon";

const SEVERITY = {
  fatal: { Icon: XCircle, tone: "text-rose-400", border: "border-rose-500/30", bg: "bg-rose-500/5" },
  warning: { Icon: AlertTriangle, tone: "text-amber-400", border: "border-amber-500/30", bg: "bg-amber-500/5" },
  info: { Icon: Info, tone: "text-emerald-400/70", border: "border-emerald-500/20", bg: "bg-emerald-500/5" },
} as const;

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-emerald-500/40 uppercase tracking-wider">{label}</div>
      <div className="text-emerald-200 font-mono">{value}</div>
    </div>
  );
}

export function PreflightPanel({
  report,
  selectedAudioId,
  setSelectedAudioId,
  selectedSubtitleId,
  setSelectedSubtitleId,
}: {
  report: Preflight;
  selectedAudioId?: number | null;
  setSelectedAudioId?: (id: number | null) => void;
  selectedSubtitleId?: number | null;
  setSelectedSubtitleId?: (id: number | null) => void;
}) {
  if (report.tools_missing) {
    return (
      <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 text-amber-300">
        {report.warning}
      </div>
    );
  }
  if (report.error) {
    return (
      <div className="rounded border border-rose-500/30 bg-rose-500/5 p-3 text-rose-300 font-mono">
        {report.error}
      </div>
    );
  }

  const { media, verdict, plan } = report;
  if (!media || !verdict) return null;

  const video = media.video[0];
  const audio = media.audio[0];
  const clean = verdict.castable && !verdict.needs_processing;

  const renderTrackOption = (t: any) => {
    const lang = (t.language || "und").toLowerCase();
    const isTarget = lang === "eng" || lang === "jpn" || lang === "en" || lang === "ja";
    const label = `${t.index}: ${t.codec} ${lang}`;
    if (isTarget) return <option key={t.index} value={t.index} className="font-bold bg-emerald-900/50">{label} ★</option>;
    return <option key={t.index} value={t.index} className="bg-black">{label}</option>;
  };

  return (
    <div className="space-y-3">
      {/* verdict banner */}
      <div
        className={`rounded border p-3 ${
          clean
            ? "border-emerald-500/40 bg-emerald-500/10"
            : "border-amber-500/40 bg-amber-500/10"
        }`}
      >
        <div className="flex items-start gap-2">
          {clean ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          )}
          <div className="min-w-0">
            <div className={clean ? "text-emerald-300" : "text-amber-300"}>{verdict.summary}</div>
            <div className="mt-1 font-mono text-emerald-500/60">
              true 4K on the Ultra:{" "}
              <span className={verdict.will_be_4k ? "text-emerald-300" : "text-amber-300"}>
                {verdict.will_be_4k ? "YES" : "NO"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* stream facts */}
      <div className="grid grid-cols-2 gap-3 rounded border border-emerald-500/20 bg-black/40 p-3">
        <Field
          label="resolution"
          value={video ? `${video.width}x${video.height}` : "--"}
        />
        <Field label="fps" value={video?.fps ? `${video.fps}` : "--"} />
        <Field
          label="video"
          value={video ? `${video.codec.toUpperCase()} ${video.profile}` : "--"}
        />
        <Field label="level" value={video?.level ? `L${video.level}` : "--"} />
        <Field label="hdr" value={video?.hdr_format || "--"} />
        <Field label="bit depth" value={video ? `${video.bit_depth}-bit` : "--"} />
        <Field label="container" value={media.container} />
        <Field label="duration" value={formatDuration(media.duration_s)} />
      </div>

      {/* Track Selection */}
      <div className="grid grid-cols-2 gap-3 rounded border border-emerald-500/20 bg-black/40 p-3">
        <div>
          <div className="text-emerald-500/40 uppercase tracking-wider mb-1">Audio</div>
          {media.audio.length > 0 ? (
            <select
              className="w-full bg-black/60 border border-emerald-500/20 rounded p-1 text-emerald-200 outline-none focus:border-emerald-500/50"
              value={selectedAudioId ?? ""}
              onChange={(e) => setSelectedAudioId?.(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="" className="bg-black">Default</option>
              {media.audio.map(renderTrackOption)}
            </select>
          ) : <div className="text-emerald-200 font-mono">--</div>}
        </div>
        <div>
          <div className="text-emerald-500/40 uppercase tracking-wider mb-1">Subtitles</div>
          {media.subtitles.length > 0 ? (
            <select
              className="w-full bg-black/60 border border-emerald-500/20 rounded p-1 text-emerald-200 outline-none focus:border-emerald-500/50"
              value={selectedSubtitleId ?? ""}
              onChange={(e) => setSelectedSubtitleId?.(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="" className="bg-black">None / Default</option>
              {media.subtitles.map(renderTrackOption)}
            </select>
          ) : <div className="text-emerald-200 font-mono">--</div>}
        </div>
      </div>

      {/* issues */}
      {verdict.issues.length > 0 && (
        <div className="space-y-2">
          {verdict.issues.map((issue) => {
            const style = SEVERITY[issue.severity] ?? SEVERITY.info;
            const { Icon } = style;
            return (
              <div
                key={issue.code + issue.message}
                className={`rounded border p-2.5 ${style.border} ${style.bg}`}
              >
                <div className="flex items-start gap-2">
                  <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${style.tone}`} />
                  <div className="min-w-0">
                    <div className="text-emerald-100/90">{issue.message}</div>
                    {issue.remedy && (
                      <div className="mt-1 text-emerald-500/60">&rarr; {issue.remedy}</div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* the fix */}
      {plan && (
        <div className="rounded border border-emerald-500/25 bg-black/60 p-3">
          <div className="mb-2 flex items-center gap-2 text-emerald-400">
            <Terminal className="h-3.5 w-3.5" />
            <span>{plan.description}</span>
          </div>
          <div className="mb-2 text-emerald-500/50">estimated: {plan.estimated}</div>
          <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-black/70 p-2 font-mono text-emerald-300/80">
            {plan.shell_command}
          </pre>
        </div>
      )}

      {report.prepared_path && (
        <div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-2.5 font-mono text-emerald-300">
          converted copy ready: {report.prepared_path.split("/").pop()}
        </div>
      )}
    </div>
  );
}
