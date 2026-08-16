// [KEY 0] Agent Jules: File verified structurally sound.
/**
 * ADDITIONS FOR mobile/lib/daemon.ts -- not a standalone module.
 *
 * Append the contents of this file to `mobile/lib/daemon.ts`. It is kept
 * separate here only because the whisperer repo is not checked out in the
 * environment these were authored in; merging it by hand is a copy-paste, and
 * doing it that way avoids a conflicting rewrite of a file another agent owns.
 *
 * It reuses the existing `request()` helper, `DEFAULT_DAEMON_BASE`, and
 * `DaemonUnreachable` already defined in daemon.ts -- do not duplicate those.
 *
 * Two changes are needed beyond the append:
 *
 *   1. Add 'finished' to EVENT_NAMES. The daemon emits a `finished` SSE event
 *      when playback reaches the end; the client currently drops it, so the UI
 *      only notices via the 5s poll. One-line fix:
 *
 *        const EVENT_NAMES = [
 *          'status', 'log', 'media', 'state', 'reconnecting',
 *          'stall', 'load_failed', 'remux', 'error',
 *          'finished',            // <-- add
 *        ] as const;
 *
 *      ('error' is listened for but never emitted by the daemon. Harmless;
 *      leave it in place in case a future daemon build uses it.)
 *
 *   2. Export the two interfaces and the function below.
 */

/** One row of the readiness checklist, mirroring `castcast.health.Check`. */
export interface HealthCheck {
  key: string;
  label: string;
  /**
   * `true` pass, `false` fail, `null` unknown.
   *
   * The tri-state is load-bearing: the UI must render `null` as `?` rather
   * than as a failure. Do not narrow this to `boolean`.
   */
  ok: boolean | null;
  detail: string;
  /** Literal shell command to fix this row, or '' if there is nothing to run. */
  remedy: string;
  /**
   * Non-blocking checks (ffmpeg, ffprobe) are warnings: an already-compatible
   * MP4 still casts without them, which is the daemon's documented
   * degradation path. Only blocking failures clear `ready`.
   */
  blocking: boolean;
}

/** Response body of `GET /health`, mirroring `castcast.health.HealthReport`. */
export interface Health {
  ready: boolean;
  version: string;
  python: string;
  /** The exact `python -m castcast ... serve` line for this daemon's config. */
  serve_command: string;
  checks: HealthCheck[];
  /** Subset of `checks` that are blocking and failing. */
  blocking: HealthCheck[];
  connected: boolean;
}

/**
 * Fetch the readiness checklist.
 *
 * Throws `DaemonUnreachable` when the daemon is not running -- callers should
 * treat that as "row 1 red, everything below unknown", never as a set of
 * failing checks.
 *
 * Short timeout on purpose: /health does no network I/O and touches only the
 * local filesystem, so anything slower than a couple of seconds means the
 * daemon is wedged, and saying so quickly is more useful than waiting.
 */
export async function getHealth(base?: string): Promise<Health> {
  return request<Health>('GET', '/health', undefined, { timeoutMs: 5000, base });
}
