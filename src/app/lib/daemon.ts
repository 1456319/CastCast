/**
 * Client for the castcast daemon's local control API.
 *
 * The daemon runs on the phone (Termux) and binds 127.0.0.1:8765. This UI is
 * just a face for it -- all the CASTv2 work happens in the daemon, because a
 * browser cannot open the raw TLS socket the protocol requires.
 */

export const DAEMON_BASE =
  (typeof localStorage !== "undefined" && localStorage.getItem("castcast.base")) ||
  "http://127.0.0.1:8765";

export interface Issue {
  severity: "fatal" | "warning" | "info";
  code: string;
  message: string;
  remedy?: string;
}

export interface Verdict {
  castable: boolean;
  needs_processing: boolean;
  will_be_4k: boolean;
  issues: Issue[];
  summary: string;
  target_container: string | null;
  video_action: string;
  audio_action: string;
}

export interface VideoStream {
  codec: string;
  profile: string;
  level: number | null;
  width: number;
  height: number;
  fps: number;
  bit_depth: number;
  hdr_format: string;
  color_space: string;
  bitrate_kbps: number | null;
}

export interface AudioStream {
  codec: string;
  channels: number;
  channel_layout: string;
  bitrate_kbps: number | null;
}

export interface MediaInfo {
  path: string;
  container: string;
  format_long: string;
  duration_s: number;
  size_bytes: number;
  bitrate_kbps: number | null;
  video: VideoStream[];
  audio: AudioStream[];
  is_4k: boolean;
}

export interface Preflight {
  media: MediaInfo | null;
  verdict: Verdict | null;
  plan: { description: string; shell_command: string; estimated: string } | null;
  prepared_path?: string | null;
  tools_missing?: boolean;
  warning?: string;
  error?: string | null;
}

export interface LibraryItem extends Partial<Preflight> {
  path: string;
  name: string;
  rel: string;
  size_bytes: number;
}

export interface CastState {
  state: string;
  position: number;
  duration: number;
  volume: number;
  muted: boolean;
  title: string;
  reconnects: number;
  stream_stalls: number;
  last_error: string;
  idle_reason: string;
  source_path: string;
  active_track_ids?: number[];
}

export interface Status {
  connected: boolean;
  device: { host: string; friendly_name: string; model: string; is_ultra: boolean } | null;
  media_server: { base_url: string; lan_ip: string; port: number; roots: string[] };
  tools: { ffmpeg: boolean; ffprobe: boolean };
  remux: { state: string; progress: number; error: string; description: string } | null;
  cast: CastState;
}

export interface LogLine {
  seq: number;
  ts: number;
  level: string;
  message: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${DAEMON_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok && !body?.error) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return body as T;
}

const post = <T,>(path: string, payload?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(payload ?? {}) });

export const daemon = {
  status: () => request<Status>("/status"),
  devices: () => request<{ devices: any[] }>("/devices"),
  library: (deep = false) => request<{ items: LibraryItem[] }>(`/library${deep ? "?deep=1" : ""}`),
  getTrash: () => request<{ items: LibraryItem[] }>("/trash"),
  preflight: (path: string) => request<Preflight>(`/preflight?path=${encodeURIComponent(path)}`),
  connect: (host: string, port = 8009) => post<Status>("/connect", { host, port }),
  disconnect: () => post<Status>("/disconnect"),
  cast: (path: string, allowUnsafe = false) =>
    post<Preflight & { casting?: boolean; url?: string; converting?: boolean; requires_confirmation?: boolean }>(
      "/cast",
      { path, allow_unsafe: allowUnsafe },
    ),
  prepare: (path: string) => post<Preflight>("/prepare", { path }),
  cancelPrepare: () => post<Status>("/prepare/cancel"),
  trash: (path: string) => post<{ trashed?: string; error?: string }>("/trash", { path }),
  delete: (path: string) => post<{ deleted?: string; error?: string }>("/delete", { path }),
  play: () => post<Status>("/play"),
  pause: () => post<Status>("/pause"),
  stop: () => post<Status>("/stop"),
  seek: (position: number) => post<Status>("/seek", { position }),
  volume: (level: number) => post<Status>("/volume", { level }),
  requestOpenSubtitles: (path: string, language = "eng") =>
    post<Preflight & { subtitles?: { path: string; language: string; url: string; label: string } }>(
      "/subtitles/opensubtitles",
      { path, language },
    ),
};

/** Subscribe to the daemon's SSE stream. Returns an unsubscribe function. */
export function subscribe(handlers: {
  onStatus?: (s: Status) => void;
  onLog?: (l: LogLine) => void;
  onMedia?: (m: CastState) => void;
  onState?: () => void;
  onRemux?: () => void;
  onOpen?: () => void;
  onError?: () => void;
}): () => void {
  let source: EventSource | null = null;
  try {
    source = new EventSource(`${DAEMON_BASE}/events`);
  } catch {
    handlers.onError?.();
    return () => undefined;
  }

  const bind = (name: string, fn?: (data: any) => void) =>
    source!.addEventListener(name, (event) => {
      if (!fn) return;
      try {
        fn(JSON.parse((event as MessageEvent).data));
      } catch {
        /* malformed frame; ignore */
      }
    });

  source.onopen = () => handlers.onOpen?.();
  source.onerror = () => handlers.onError?.();
  bind("status", handlers.onStatus);
  bind("log", handlers.onLog);
  bind("media", handlers.onMedia);
  bind("state", () => handlers.onState?.());
  bind("reconnecting", () => handlers.onState?.());
  bind("stall", () => handlers.onState?.());
  bind("load_failed", () => handlers.onState?.());
  bind("remux", () => handlers.onRemux?.());

  return () => source?.close();
}

export function formatDuration(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return "0:00";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
