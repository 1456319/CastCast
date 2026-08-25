import { describe, it, expect } from 'vitest';
import { formatDuration, formatBytes } from './daemon';

describe('formatDuration', () => {
  it('should format 0 seconds correctly', () => {
    expect(formatDuration(0)).toBe('0:00');
  });

  it('should format less than a minute correctly', () => {
    expect(formatDuration(45)).toBe('0:45');
    expect(formatDuration(9)).toBe('0:09');
  });

  it('should format exactly a minute correctly', () => {
    expect(formatDuration(60)).toBe('1:00');
  });

  it('should format more than a minute correctly', () => {
    expect(formatDuration(125)).toBe('2:05');
    expect(formatDuration(65)).toBe('1:05');
  });

  it('should format exactly an hour correctly', () => {
    expect(formatDuration(3600)).toBe('1:00:00');
  });

  it('should format more than an hour correctly', () => {
    expect(formatDuration(3661)).toBe('1:01:01');
    expect(formatDuration(7325)).toBe('2:02:05');
  });

  it('should handle non-finite or falsy inputs', () => {
    expect(formatDuration(NaN)).toBe('0:00');
    expect(formatDuration(Infinity)).toBe('0:00');
    expect(formatDuration(-Infinity)).toBe('0:00');
    // @ts-expect-error testing invalid inputs
    expect(formatDuration(undefined)).toBe('0:00');
    // @ts-expect-error testing invalid inputs
    expect(formatDuration(null)).toBe('0:00');
  });

  it('should handle fractional seconds by flooring them', () => {
    expect(formatDuration(65.9)).toBe('1:05');
    expect(formatDuration(45.4)).toBe('0:45');
  });

  it('should handle negative durations', () => {
    expect(formatDuration(-10)).toBe('0:00');
    expect(formatDuration(-3600)).toBe('0:00');
  });
});

describe('formatBytes', () => {
  it('should format 0 bytes correctly', () => {
    expect(formatBytes(0)).toBe('0 B');
  });

  it('should format bytes correctly', () => {
    expect(formatBytes(500)).toBe('500 B');
  });

  it('should format KB correctly', () => {
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1500)).toBe('1.5 KB');
  });

  it('should format MB correctly', () => {
    expect(formatBytes(1048576)).toBe('1.0 MB');
  });
});
