import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import App from '../App';
import * as daemonLib from '../lib/daemon';
import { DiscoveryBrowser } from '../lib/discovery-browser';

// Mock the daemon library
vi.mock('../lib/daemon', () => ({
  DAEMON_BASE: 'http://localhost:8765',
  daemon: {
    status: vi.fn(),
    shutdown: vi.fn(),
    play: vi.fn(),
    pause: vi.fn(),
    getAmazonQueue: vi.fn().mockResolvedValue({ items: [] }),
    getLibrary: vi.fn().mockResolvedValue({ items: [] }),
    getTrash: vi.fn().mockResolvedValue({ items: [] }),
    reorderAmazonQueue: vi.fn().mockResolvedValue({}),
    cast: vi.fn()
  },
  subscribe: vi.fn(),
  formatBytes: (bytes: number) => `${bytes} B`,
  formatDuration: vi.fn(),
}));

// Mock Capacitor plugins
vi.mock('@capacitor/core', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    Capacitor: {
      getPlatform: () => 'web',
      isNativePlatform: () => false,
      isPluginAvailable: () => true
    }
  };
});

// Mock DiscoveryBrowser
vi.mock('../lib/discovery-browser', () => {
  return {
    startDiscovery: vi.fn().mockResolvedValue(undefined),
    stopDiscovery: vi.fn().mockResolvedValue(undefined),
    DiscoveryBrowser: {
      addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
    }
  };
});

describe('App Component Synchronization', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders Launch Daemon fallback when offline', async () => {
    // Setup initial offline state
    vi.mocked(daemonLib.daemon.status).mockRejectedValue(new Error('Offline'));
    vi.mocked(daemonLib.subscribe).mockReturnValue(() => {});

    render(<App />);

    // Fast-forward effects
    await waitFor(() => {
      expect(screen.getByText('Launch Daemon (Termux)')).toBeInTheDocument();
    });
    expect(screen.getByText('daemon unreachable')).toBeInTheDocument();
  });

  it('cleans up correctly on kill server', async () => {
    // Setup online state
    vi.mocked(daemonLib.daemon.status).mockResolvedValue({
      host: '192.168.1.50',
      connected: false,
      media_server: { lan_ip: '192.168.1.50', port: 8765 },
      tools: { ffprobe: true },
      cast: { state: 'idle', position: 0, duration: 0, volume: 1, muted: false, content_id: null, content_type: null }
    } as any);

    const unsubscribeMock = vi.fn();
    vi.mocked(daemonLib.subscribe).mockReturnValue(unsubscribeMock);

    // Spy on window.clearInterval
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval');

    render(<App />);

    // Wait to be online
    await waitFor(() => {
      expect(screen.getByText('kill server')).toBeInTheDocument();
    });

    vi.mocked(daemonLib.daemon.shutdown).mockResolvedValue({} as any);

    const killButton = screen.getByText('kill server');

    await act(async () => {
      fireEvent.click(killButton);
    });

    // Verify cleanup order
    expect(unsubscribeMock).toHaveBeenCalledTimes(1);
    expect(clearIntervalSpy).toHaveBeenCalled();
    expect(daemonLib.daemon.shutdown).toHaveBeenCalledTimes(1);

    // UI should switch back to offline immediately
    await waitFor(() => {
      expect(screen.getByText('Launch Daemon (Termux)')).toBeInTheDocument();
    });
  });

  it('updates state based on SSE events correctly', async () => {
    vi.mocked(daemonLib.daemon.status).mockResolvedValue({
      host: '192.168.1.50',
      connected: true,
      media_server: { lan_ip: '192.168.1.50', port: 8765 },
      tools: { ffprobe: true },
      cast: { state: 'idle', position: 0, duration: 100, volume: 1, muted: false, content_id: null, content_type: null }
    } as any);

    let sseCallback: any = null;
    vi.mocked(daemonLib.subscribe).mockImplementation((callbacks: any) => {
      sseCallback = callbacks;
      return vi.fn();
    });

    render(<App />);

    await waitFor(() => {
      expect(sseCallback).not.toBeNull();
    });

    // We can simulate playing and check if UI reacts
    await act(async () => {
      sseCallback.onMedia({ state: 'playing', position: 10 });
    });

    // Simple wait to ensure React processes the state update
    await waitFor(() => {
      expect(screen.getByText('playing')).toBeInTheDocument();
    });

    await act(async () => {
      sseCallback.onMedia({ state: 'buffering', position: 10 });
    });

    await waitFor(() => {
      expect(screen.getByText('buffering')).toBeInTheDocument();
    });
  });

  it('handles amazon queue drag and drop (mocked backend)', async () => {
    vi.mocked(daemonLib.daemon.status).mockResolvedValue({
      host: '192.168.1.50',
      connected: true,
      media_server: { lan_ip: '192.168.1.50', port: 8765 },
      tools: { ffprobe: true },
      cast: { state: 'idle', position: 0, duration: 0, volume: 1, muted: false, content_id: null, content_type: null }
    } as any);

    let sseCallback: any = null;
    vi.mocked(daemonLib.subscribe).mockImplementation((callbacks: any) => {
      sseCallback = callbacks;
      return vi.fn();
    });

    render(<App />);

    await waitFor(() => {
      expect(sseCallback).not.toBeNull();
    });

    // Simulate an amazon queue update from backend
    await act(async () => {
      sseCallback.onAmazonQueue({ items: [
        { url: 'url1', title: 'Amazon Video 1', path: 'path1' },
        { url: 'url2', title: 'Amazon Video 2', path: 'path2' }
      ]});
    });

    await waitFor(() => {
      expect(screen.getByText('Amazon Video 1')).toBeInTheDocument();
      expect(screen.getByText('Amazon Video 2')).toBeInTheDocument();
    });

    // Trigger drag and drop
    const items = screen.getAllByText(/Amazon Video/);
    expect(items.length).toBe(2);

    // Simulate drag start on Video 1
    const dragStartEvent = new Event('dragstart', { bubbles: true, cancelable: true });
    Object.defineProperty(dragStartEvent, 'dataTransfer', {
      value: {
        setData: vi.fn(),
        getData: vi.fn().mockReturnValue(JSON.stringify({ index: 0, type: 'amazon' }))
      }
    });

    await act(async () => {
      fireEvent(items[0], dragStartEvent);
    });

    // Simulate drop on Video 2
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, 'dataTransfer', {
      value: {
        getData: vi.fn().mockReturnValue(JSON.stringify({ index: 0, type: 'amazon' }))
      }
    });

    await act(async () => {
      fireEvent(items[1], dropEvent);
    });

    await waitFor(() => {
      expect(daemonLib.daemon.reorderAmazonQueue).toHaveBeenCalledWith([
        { url: 'url2', title: 'Amazon Video 2', path: 'path2' },
        { url: 'url1', title: 'Amazon Video 1', path: 'path1' }
      ]);
    });
  });
});
