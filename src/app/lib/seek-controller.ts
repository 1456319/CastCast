// synchronization-map: section=web-client; role=seek-controller; boundaries=api-contract; doc=docs/SYNCHRONIZATION_MAP.md
export interface SeekControllerOptions {
  getDuration: () => number;
  getPosition: () => number;
  onOptimisticChange?: (pos: number) => void;
  sendSeek: (pos: number) => Promise<unknown>;
  debounceMs?: number;
}

export class SeekController {
  private pendingTarget: number | null = null;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private inFlight = false;
  private queuedTarget: number | null = null;

  constructor(private options: SeekControllerOptions) {}

  public getPendingPosition(): number | null {
    return this.pendingTarget;
  }

  public step(deltaSeconds: number): number {
    const duration = this.options.getDuration() || 0;
    const currentBase = this.pendingTarget !== null ? this.pendingTarget : this.options.getPosition();
    let nextTarget = currentBase + deltaSeconds;
    nextTarget = Math.max(0, duration > 2 ? Math.min(nextTarget, duration - 2) : nextTarget);

    this.pendingTarget = nextTarget;
    this.options.onOptimisticChange?.(nextTarget);

    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
    }

    const debounce = this.options.debounceMs ?? 300;
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      this.flush();
    }, debounce);

    return nextTarget;
  }

  public async seekTo(absoluteSeconds: number): Promise<void> {
    const duration = this.options.getDuration() || 0;
    const target = Math.max(0, duration > 2 ? Math.min(absoluteSeconds, duration - 2) : absoluteSeconds);
    this.pendingTarget = target;
    this.options.onOptimisticChange?.(target);

    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }

    await this.flush();
  }

  public async flush(): Promise<void> {
    if (this.pendingTarget === null) return;
    const target = this.pendingTarget;

    if (this.inFlight) {
      this.queuedTarget = target;
      return;
    }

    this.inFlight = true;
    try {
      await this.options.sendSeek(target);
    } finally {
      this.inFlight = false;
      if (this.queuedTarget !== null) {
        const next = this.queuedTarget;
        this.queuedTarget = null;
        if (next !== target) {
          this.pendingTarget = next;
          await this.flush();
          return;
        }
      }
      this.pendingTarget = null;
    }
  }

  public cancel(): void {
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.pendingTarget = null;
    this.queuedTarget = null;
  }
}
