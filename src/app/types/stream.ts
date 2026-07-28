export type StreamState = "idle" | "requesting_root" | "root_denied" | "scanning" | "active" | "error";

export interface StreamInfo {
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
}

export interface StreamMetrics {
  bufferHealth: number;
  networkSpeed: number;
}
