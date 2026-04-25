/**
 * DoneConditionGuard — manages the draining phase between receiving the
 * backend's `done` signal and sending the client done-ACK.
 *
 * Protocol:
 *   1. Backend emits `done`.
 *   2. Caller creates a DoneConditionGuard with a set of DoneConditionFns.
 *   3. Caller calls `trigger()` — starts the drain-window timer and runs an
 *      immediate condition check (resolves immediately if all met).
 *   4. As new events arrive (tokens, completed tasks), caller calls `recheck()`.
 *   5. When all conditions return `true`, `onReady(false)` is called.
 *   6. If the drain window expires first, `onReady(true)` is called (forced).
 *   7. The guard is single-use — subsequent calls are no-ops after resolution.
 *
 * Thread-safety note: designed for a single JS execution context (no shared
 * mutable state across concurrent calls).
 */
import type { DoneGuardOptions } from "./types";

const DEFAULT_DRAIN_WINDOW_MS = 3_000;

export class DoneConditionGuard {
  private readonly drainWindowMs: number;
  private readonly label: string;
  private readonly conditions: (() => boolean)[];
  private readonly onReady: (forced: boolean) => void;

  private timer: ReturnType<typeof setTimeout> | null = null;
  private triggered = false;
  private resolved = false;

  constructor(opts: DoneGuardOptions) {
    this.drainWindowMs = opts.drainWindowMs ?? DEFAULT_DRAIN_WINDOW_MS;
    this.label = opts.label;
    this.conditions = opts.conditions;
    this.onReady = opts.onReady;
  }

  /**
   * Start the drain window.
   * Call exactly once when the `done` signal is received.
   * If all conditions are already satisfied, resolves synchronously
   * without starting the timer.
   */
  trigger(): void {
    if (this.resolved || this.triggered) return;
    this.triggered = true;

    if (this._allMet()) {
      this._resolve(false);
      return;
    }

    this.timer = setTimeout(() => {
      this.timer = null;
      if (!this.resolved) {
        console.warn(
          "[DoneConditionGuard] drain window expired label=%s drainWindowMs=%d",
          this.label,
          this.drainWindowMs,
        );
        this._resolve(true);
      }
    }, this.drainWindowMs);
  }

  /**
   * Re-evaluate all conditions.
   * Call after any event that might satisfy a condition (e.g. a task
   * completing, or a new token batch arriving).
   *
   * No-op if the guard has not been triggered yet or has already resolved.
   */
  recheck(): void {
    if (!this.triggered || this.resolved) return;
    if (this._allMet()) {
      if (this.timer !== null) {
        clearTimeout(this.timer);
        this.timer = null;
      }
      this._resolve(false);
    }
  }

  /**
   * Cancel the guard without calling `onReady`.
   * Call on component unmount or session cleanup to prevent timer leaks.
   */
  cleanup(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.resolved = true;
  }

  // ── Private helpers ─────────────────────────────────────────────────────────

  private _allMet(): boolean {
    return this.conditions.every((fn) => fn());
  }

  private _resolve(forced: boolean): void {
    if (this.resolved) return;
    this.resolved = true;
    console.info(
      "[DoneConditionGuard] resolved forced=%s label=%s",
      forced,
      this.label,
    );
    this.onReady(forced);
  }
}
