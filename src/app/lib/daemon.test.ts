import { describe, it, expect } from 'vitest';
import { formatDuration, mergeCastState, type CastState } from './daemon';

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
});


describe('receiver state ordering', () => {
  const state = { state: 'playing', connection_id: 'a', connection_epoch: 10, revision: 5, position: 100 } as CastState;
  it('rejects an older poll arriving after an SSE update', () => {
    expect(mergeCastState(state, { ...state, revision: 4, position: 50 })).toBe(state);
  });
  it('rejects a late response from a replaced supervisor', () => {
    expect(mergeCastState(state, { ...state, connection_id: 'old', connection_epoch: 9, revision: 100 })).toBe(state);
  });
  it('accepts a new connection without retaining old quality claims', () => {
    const fresh = { state: 'loading', connection_id: 'new', connection_epoch: 11, revision: 1 } as CastState;
    expect(mergeCastState({ ...state, quality_state: 'receiver_4k' }, fresh)).toEqual(fresh);
  });
});
