import '@testing-library/jest-dom';
import { vi } from 'vitest';

vi.mock('@capacitor/core', () => ({
  Capacitor: {
    getPlatform: () => 'web',
    isNativePlatform: () => false
  },
  registerPlugin: () => ({
    addListener: vi.fn(),
    removeAllListeners: vi.fn()
  })
}));

vi.mock('../lib/discovery-browser', () => ({
  DiscoveryBrowser: {
    addListener: vi.fn().mockImplementation(async () => ({ remove: vi.fn() })),
    removeAllListeners: vi.fn(),
    open: vi.fn()
  }
}));

global.document.createRange = () => ({
  setStart: () => {},
  setEnd: () => {},
  commonAncestorContainer: {
    nodeName: 'BODY',
    ownerDocument: document,
  },
} as unknown as Range);
