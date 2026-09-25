// synchronization-map: section=web-client; role=seek-controller; boundaries=api-contract; doc=docs/SYNCHRONIZATION_MAP.md
export interface SeekControllerOptions {
  getDuration: () => number;
  getPosition: () => number;
  onOptimisticChange?: (pos: number) => void;
  sendSeek: (pos: number) => Promise<unknown>;
  onError?: (err: unknown) => void;
  debounceMs?: number;
}

interface PendingWaiter {
  target: number;
  resolve: () => void;
  reject: (err: unknown) => void;
}

export class SeekController {
  private pendingTarget: number | null = null;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private inFlight = false;
  private waiters: PendingWaiter[] = [];

  constructor(private options: SeekControllerOptions) {}

  public getPendingPosition(): number | null {
    return this.pendingTarget;
  }

  private clamp(target: number): number {
    const duration = this.options.getDuration() || 0;
    if (duration <= 0) return Math.max(0, target);
    const maxTarget = duration > 2 ? duration - 2 : Math.max(0, duration - 0.1);
    return Math.max(0, Math.min(target, maxTarget));
  }

  public step(deltaSeconds: number): number {
    const currentBase = this.pendingTarget !== null ? this.pendingTarget : this.options.getPosition();
    const nextTarget = this.clamp(currentBase + deltaSeconds);

    this.pendingTarget = nextTarget;
    this.options.onOptimisticChange?.(nextTarget);

    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
    }

    const debounce = this.options.debounceMs ?? 300;
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      this.flush().catch(() => {});
    }, debounce);

    return nextTarget;
  }

  public async seekTo(absoluteSeconds: number): Promise<void> {
    const target = this.clamp(absoluteSeconds);
    this.pendingTarget = target;
    this.options.onOptimisticChange?.(target);

    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }

    return new Promise<void>((resolve, reject) => {
      this.waiters.push({ target, resolve, reject });
      this.flush().catch(() => {});
    });
  }

  public async flush(): Promise<void> {
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }

    if (this.inFlight) {
      return;
    }

    while (this.pendingTarget !== null && this.debounceTimer === null) {
      const target = this.pendingTarget;
      this.inFlight = true;

      let sendError: unknown = null;
      try {
        await this.options.sendSeek(target);
      } catch (err) {
        sendError = err;
        this.options.onError?.(err);
      } finally {
        this.inFlight = false;
        if (this.pendingTarget === target || sendError !== null) {
          this.pendingTarget = null;
        }

        const remainingWaiters: PendingWaiter[] = [];
        for (const w of this.waiters) {
          if (w.target === target || (this.pendingTarget === null && sendError === null)) {
            if (sendError) w.reject(sendError);
            else w.resolve();
          } else if (sendError && this.pendingTarget === null) {
            w.reject(sendError);
          } else {
            remainingWaiters.push(w);
          }
        }
        this.waiters = remainingWaiters;
      }

      if (sendError !== null) {
        throw sendError;
      }
    }
  }

  public cancel(): void {
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.pendingTarget = null;
    for (const w of this.waiters) {
      w.resolve();
    }
    this.waiters = [];
  }
}
