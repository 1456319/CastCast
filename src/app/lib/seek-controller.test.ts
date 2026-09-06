import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SeekController } from './seek-controller';

describe('SeekController', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('accumulates rapid steps and debounces network calls', async () => {
    const sendSeek = vi.fn().mockResolvedValue({});
    const onOptimisticChange = vi.fn();
    const currentPos = 800;

    const controller = new SeekController({
      getPosition: () => currentPos,
      getDuration: () => 1000,
      sendSeek,
      onOptimisticChange,
      debounceMs: 300,
    });

    // Tap fast-forward 5 times rapidly (+10s each)
    controller.step(10);
    controller.step(10);
    controller.step(10);
    controller.step(10);
    controller.step(10);

    // Should immediately notify optimistic position = 850
    expect(onOptimisticChange).toHaveBeenLastCalledWith(850);
    expect(controller.getPendingPosition()).toBe(850);

    // No network seek should have fired yet
    expect(sendSeek).not.toHaveBeenCalled();

    // Advance timer past debounce threshold (300ms)
    await vi.advanceTimersByTimeAsync(300);

    // Exactly one seek should be dispatched with final target 850
    expect(sendSeek).toHaveBeenCalledTimes(1);
    expect(sendSeek).toHaveBeenCalledWith(850);
  });

  it('clamps to [0, duration - 2] bounds', async () => {
    const sendSeek = vi.fn().mockResolvedValue({});
    const controller = new SeekController({
      getPosition: () => 995,
      getDuration: () => 1000,
      sendSeek,
      debounceMs: 200,
    });

    // Should clamp to 998
    controller.step(10);
    expect(controller.getPendingPosition()).toBe(998);

    // Rewind below 0 clamps to 0
    const rewinder = new SeekController({
      getPosition: () => 5,
      getDuration: () => 1000,
      sendSeek,
      debounceMs: 200,
    });
    rewinder.step(-20);
    expect(rewinder.getPendingPosition()).toBe(0);
  });

  it('handles immediate seekTo by flushing directly', async () => {
    const sendSeek = vi.fn().mockResolvedValue({});
    const controller = new SeekController({
      getPosition: () => 100,
      getDuration: () => 1000,
      sendSeek,
    });

    await controller.seekTo(500);
    expect(sendSeek).toHaveBeenCalledWith(500);
  });

  it('does not lose trailing steps during in-flight network dispatch', async () => {
    let resolveFirstSeek!: (val?: unknown) => void;
    const sendSeek = vi.fn().mockImplementationOnce(() => new Promise((resolve) => {
      resolveFirstSeek = resolve;
    })).mockResolvedValue({});

    const controller = new SeekController({
      getPosition: () => 100,
      getDuration: () => 1000,
      sendSeek,
      debounceMs: 100,
    });

    // Step +10 and let debounce fire
    controller.step(10); // target: 110
    await vi.advanceTimersByTimeAsync(100);
    expect(sendSeek).toHaveBeenCalledTimes(1);
    expect(sendSeek).toHaveBeenLastCalledWith(110);

    // Now sendSeek(110) is still in flight!
    // User taps fast-forward two more times
    controller.step(10); // target: 120
    controller.step(10); // target: 130
    expect(controller.getPendingPosition()).toBe(130);

    // Resolve the first in-flight seek
    resolveFirstSeek();
    await Promise.resolve(); // drain microtasks

    // Let the trailing seek flush
    await vi.advanceTimersByTimeAsync(100);
    await Promise.resolve();

    // Now sendSeek should have been called again with 130!
    expect(sendSeek).toHaveBeenCalledTimes(2);
    expect(sendSeek).toHaveBeenLastCalledWith(130);
    expect(controller.getPendingPosition()).toBe(null);
  });

  it('awaits until queued seekTo is completely dispatched', async () => {
    let resolveFirstSeek!: (val?: unknown) => void;
    const sendSeek = vi.fn().mockImplementationOnce(() => new Promise((resolve) => {
      resolveFirstSeek = resolve;
    })).mockResolvedValue({});

    const controller = new SeekController({
      getPosition: () => 100,
      getDuration: () => 1000,
      sendSeek,
      debounceMs: 100,
    });

    // Step once to get seek in flight
    controller.step(10);
    await vi.advanceTimersByTimeAsync(100);
    expect(sendSeek).toHaveBeenCalledTimes(1);

    // Now call seekTo(500) while first seek is in flight
    let seekToCompleted = false;
    const seekToPromise = controller.seekTo(500).then(() => {
      seekToCompleted = true;
    });

    await Promise.resolve();
    // Must NOT be completed yet!
    expect(seekToCompleted).toBe(false);

    // Resolve the first seek
    resolveFirstSeek();
    await Promise.resolve();

    await seekToPromise;
    expect(seekToCompleted).toBe(true);
    expect(sendSeek).toHaveBeenCalledWith(500);
  });

  it('propagates errors to onError and rejects pending seekTo', async () => {
    const error = new Error('Network error');
    const sendSeek = vi.fn().mockRejectedValue(error);
    const onError = vi.fn();

    const controller = new SeekController({
      getPosition: () => 100,
      getDuration: () => 1000,
      sendSeek,
      onError,
      debounceMs: 100,
    });

    await expect(controller.seekTo(300)).rejects.toThrow('Network error');
    expect(onError).toHaveBeenCalledWith(error);
  });

  it('calls onError only once when seek fails', async () => {
    const error = new Error('Network timeout');
    const sendSeek = vi.fn().mockRejectedValue(error);
    const onError = vi.fn();

    const controller = new SeekController({
      getPosition: () => 100,
      getDuration: () => 1000,
      sendSeek,
      onError,
      debounceMs: 100,
    });

    controller.step(10);
    await vi.advanceTimersByTimeAsync(100);

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(error);
  });
});
