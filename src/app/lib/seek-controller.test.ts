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
});
