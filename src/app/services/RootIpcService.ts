import { StreamInfo, StreamMetrics, StreamState } from "../types/stream";

// Mock presets for demonstration
const STREAM_PRESETS: (StreamInfo & StreamMetrics)[] = [
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

type LogCallback = (msg: string) => void;
type MetricsCallback = (metrics: StreamMetrics) => void;
type StreamFoundCallback = (info: StreamInfo) => void;
type StateChangeCallback = (state: StreamState) => void;
type RootAccessCallback = (hasRoot: boolean) => void;

export class RootIpcService {
  private logCallback?: LogCallback;
  private metricsCallback?: MetricsCallback;
  private streamFoundCallback?: StreamFoundCallback;
  private stateChangeCallback?: StateChangeCallback;
  private rootAccessCallback?: RootAccessCallback;

  private metricsInterval?: number;
  private presetIdx = 0;
  private hasRootAccess = false;
  private state: StreamState = "idle";

  constructor() {}

  onLog(cb: LogCallback) {
    this.logCallback = cb;
  }
  onMetrics(cb: MetricsCallback) {
    this.metricsCallback = cb;
  }
  onStreamFound(cb: StreamFoundCallback) {
    this.streamFoundCallback = cb;
  }
  onRootAccessChange(cb: RootAccessCallback) {
    this.rootAccessCallback = cb;
    cb(this.hasRootAccess);
  }
  onStateChange(cb: StateChangeCallback) {
    this.stateChangeCallback = cb;
  }

  private setState(newState: StreamState) {
    this.state = newState;
    this.stateChangeCallback?.(newState);
  }

  requestRootAccess() {
    if (this.hasRootAccess) {
        this.startScan();
        return;
    }
    this.setState("requesting_root");
    this.logCallback?.("Requesting su permissions...");

    setTimeout(() => {
      this.hasRootAccess = true;
      this.rootAccessCallback?.(true);
      this.logCallback?.("Root access granted by user.");
      this.startScan();
    }, 1500);
  }

  startScan() {
    if (!this.hasRootAccess) {
        this.logCallback?.("Cannot scan: Root access not granted.");
        this.setState("root_denied");
        return;
    }

    this.setState("scanning");

    // alternate presets for demo
    const preset = STREAM_PRESETS[this.presetIdx];
    this.presetIdx = (this.presetIdx + 1) % STREAM_PRESETS.length;

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
      setTimeout(() => this.logCallback?.(msg), delay);
    });

    setTimeout(() => {
      this.streamFoundCallback?.(preset);
      this.setState("active");
      this.startMetricsStream(preset.bufferHealth, preset.networkSpeed);
    }, 3000);
  }

  private startMetricsStream(baseBuffer: number, baseNetwork: number) {
    this.stopMetricsStream();
    this.metricsInterval = window.setInterval(() => {
      this.metricsCallback?.({
        bufferHealth: Math.max(60, Math.min(100, baseBuffer + (Math.random() * 6 - 3))),
        networkSpeed: Math.max(5, baseNetwork + (Math.random() * 4 - 2))
      });
    }, 2000);
  }

  private stopMetricsStream() {
    if (this.metricsInterval) {
      clearInterval(this.metricsInterval);
      this.metricsInterval = undefined;
    }
  }

  reset() {
    this.stopMetricsStream();
    this.setState("idle");
  }

  disconnect() {
      this.stopMetricsStream();
  }
}
