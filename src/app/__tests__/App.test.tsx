import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';
import * as daemonLib from '../lib/daemon';

// Mock daemon and subscribe
vi.mock('../lib/daemon', () => ({
  daemon: {
    status: vi.fn(),
    shutdown: vi.fn(() => Promise.resolve()),
    play: vi.fn(),
    pause: vi.fn(),
    stop: vi.fn(),
    library: vi.fn(),
    getTrash: vi.fn(),
    getAmazonQueue: vi.fn(),
    reorderAmazonQueue: vi.fn(),
    interceptDiscovery: vi.fn(),
  },
  subscribe: vi.fn(() => vi.fn()),
  DAEMON_BASE: 'http://localhost:8765',
  formatBytes: vi.fn(),
  formatDuration: vi.fn(),
}));

// Mock termux-daemon
vi.mock('../lib/termux-daemon', () => ({
  launchTermuxDaemon: vi.fn(),
  getSharedUrl: vi.fn(),
  TERMUX_MANUAL_COMMAND: 'mock manual command',
}));

// Mock discovery-browser
vi.mock('../lib/discovery-browser', () => ({
  DiscoveryBrowser: {
    addListener: vi.fn(() => Promise.resolve({ remove: vi.fn() }))
  }
}));

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders offline state initially', async () => {
    (daemonLib.daemon.status as any).mockRejectedValue(new Error('unreachable'));

    await act(async () => {
      render(<App />);
    });

    expect(screen.getByText('daemon unreachable')).toBeInTheDocument();
    expect(screen.getByText('Launch Daemon (Termux)')).toBeInTheDocument();
  });

  it('handles kill server button properly (Lifecycle & Cleanup Verification)', async () => {
    const mockUnsubscribe = vi.fn();
    (daemonLib.subscribe as any).mockReturnValue(mockUnsubscribe);

    // Simulate online state initially
    (daemonLib.daemon.status as any).mockResolvedValue({
      cast: { state: 'playing', position: 0, duration: 100 },
      server: { version: '1.0' },
      media_server: { lan_ip: '192.168.1.2', port: 8080 },
      device: { name: 'Living Room TV' },
      tools: { ffprobe: true, yt_dlp: true }
    });
    (daemonLib.daemon.library as any).mockResolvedValue({ items: [] });
    (daemonLib.daemon.getTrash as any).mockResolvedValue({ items: [] });
    (daemonLib.daemon.getAmazonQueue as any).mockResolvedValue({ items: [] });

    await act(async () => {
      render(<App />);
    });

    // Simulate online state via SSE callback
    await act(async () => {
      const subscribeCall = (daemonLib.subscribe as any).mock.calls[0][0];
      subscribeCall.onOpen();
      subscribeCall.onStatus({
        cast: { state: 'playing', position: 0, duration: 100 },
        server: { version: '1.0' },
        media_server: { lan_ip: '192.168.1.2', port: 8080 },
        device: { name: 'Living Room TV' },
        tools: { ffprobe: true, yt_dlp: true }
      });
    });

    expect(screen.queryByText('daemon unreachable')).not.toBeInTheDocument();

    // Find and click the kill server button
    const killButton = screen.getByText(/kill server/i);

    await act(async () => {
      fireEvent.click(killButton);
    });

    // Check that cleanup happened
    expect(mockUnsubscribe).toHaveBeenCalledTimes(1);
    expect(daemonLib.daemon.shutdown).toHaveBeenCalledTimes(1);

    // The UI should go back to offline state
    expect(screen.getByText('daemon unreachable')).toBeInTheDocument();
  });

  it('transitions between online, buffering, and playing states correctly', async () => {
    const mockUnsubscribe = vi.fn();
    (daemonLib.subscribe as any).mockReturnValue(mockUnsubscribe);

    (daemonLib.daemon.status as any).mockResolvedValue({
      cast: { state: 'connected', position: 0, duration: 100 },
      server: { version: '1.0' },
      media_server: { lan_ip: '192.168.1.2', port: 8080 },
      device: { name: 'Living Room TV' },
      tools: { ffprobe: true, yt_dlp: true }
    });

    await act(async () => {
      render(<App />);
    });

    // Send connected status
    await act(async () => {
      const subscribeCall = (daemonLib.subscribe as any).mock.calls[0][0];
      subscribeCall.onOpen();
      subscribeCall.onStatus({
        cast: { state: 'connected', position: 0, duration: 100 },
        server: { version: '1.0' },
        media_server: { lan_ip: '192.168.1.2', port: 8080 },
        device: { name: 'Living Room TV' },
        tools: { ffprobe: true, yt_dlp: true }
      });
    });

    // Should find the span with text connected
    expect(screen.getByText('connected', { selector: 'span.font-mono.text-emerald-400\\/70' })).toBeInTheDocument();

    // Transition to buffering
    await act(async () => {
      const subscribeCall = (daemonLib.subscribe as any).mock.calls[0][0];
      subscribeCall.onStatus({
        cast: { state: 'buffering', position: 0, duration: 100 },
        server: { version: '1.0' },
        media_server: { lan_ip: '192.168.1.2', port: 8080 },
        device: { name: 'Living Room TV' },
        tools: { ffprobe: true, yt_dlp: true }
      });
    });

    expect(screen.getByText('buffering', { selector: 'span.font-mono.text-amber-400' })).toBeInTheDocument();

    // Transition to playing
    await act(async () => {
      const subscribeCall = (daemonLib.subscribe as any).mock.calls[0][0];
      subscribeCall.onStatus({
        cast: { state: 'playing', position: 0, duration: 100 },
        server: { version: '1.0' },
        media_server: { lan_ip: '192.168.1.2', port: 8080 },
        device: { name: 'Living Room TV' },
        tools: { ffprobe: true, yt_dlp: true }
      });
    });

    expect(screen.getByText('playing', { selector: 'span.font-mono.text-emerald-400' })).toBeInTheDocument();
  });

  it('handles drag and drop correctly for queue integrity', async () => {
    const mockUnsubscribe = vi.fn();
    (daemonLib.subscribe as any).mockReturnValue(mockUnsubscribe);

    const initialQueue = [
      { url: 'url1', title: 'Item 1' },
      { url: 'url2', title: 'Item 2' },
      { url: 'url3', title: 'Item 3' }
    ];

    (daemonLib.daemon.status as any).mockResolvedValue({
      cast: { state: 'playing', position: 0, duration: 100 },
      server: { version: '1.0' },
      media_server: { lan_ip: '192.168.1.2', port: 8080 },
      device: { name: 'Living Room TV' },
      tools: { ffprobe: true, yt_dlp: true }
    });

    // We mock the queue endpoint returning our initial queue
    (daemonLib.daemon.getAmazonQueue as any).mockResolvedValue({ items: initialQueue });

    // Mock the reorder endpoint to just echo what we send
    (daemonLib.daemon.reorderAmazonQueue as any).mockImplementation((newOrder: any) => {
      return Promise.resolve({ items: newOrder });
    });

    await act(async () => {
      render(<App />);
    });

    // Send connected status & trigger the library fetch
    await act(async () => {
      const subscribeCall = (daemonLib.subscribe as any).mock.calls[0][0];
      subscribeCall.onOpen();
      subscribeCall.onStatus({
        cast: { state: 'playing', position: 0, duration: 100 },
        server: { version: '1.0' },
        media_server: { lan_ip: '192.168.1.2', port: 8080 },
        device: { name: 'Living Room TV' },
        tools: { ffprobe: true, yt_dlp: true }
      });

      // Simulate receiving the queue from the daemon
      subscribeCall.onAmazonQueue({ items: initialQueue });
    });

    expect(screen.getByText('Item 1')).toBeInTheDocument();
    expect(screen.getByText('Item 2')).toBeInTheDocument();
    expect(screen.getByText('Item 3')).toBeInTheDocument();

    // Now let's simulate a drag and drop
    const item1 = screen.getByText('Item 1').closest('div[draggable="true"]');
    const item3 = screen.getByText('Item 3').closest('div[draggable="true"]');

    expect(item1).not.toBeNull();
    expect(item3).not.toBeNull();

    const mockDataTransfer = {
      setData: vi.fn(),
      getData: vi.fn().mockReturnValue(JSON.stringify({ index: 0, type: 'amazon' })),
    };

    await act(async () => {
      fireEvent.dragStart(item1!, { dataTransfer: mockDataTransfer });
    });

    await act(async () => {
      fireEvent.drop(item3!, { dataTransfer: mockDataTransfer });
    });

    expect((daemonLib.daemon.reorderAmazonQueue as any)).toHaveBeenCalled();

    // The expected new order is moving index 0 to index 2
    const expectedNewQueue = [
      { url: 'url2', title: 'Item 2' },
      { url: 'url3', title: 'Item 3' },
      { url: 'url1', title: 'Item 1' }
    ];

    expect((daemonLib.daemon.reorderAmazonQueue as any)).toHaveBeenCalledWith(expectedNewQueue);
  });

  it('handles sudden SSE drop and transitions back to offline splash screen', async () => {
    const mockUnsubscribe = vi.fn();
    (daemonLib.subscribe as any).mockReturnValue(mockUnsubscribe);

    (daemonLib.daemon.status as any).mockResolvedValue({
      cast: { state: 'playing', position: 0, duration: 100 },
      server: { version: '1.0' },
      media_server: { lan_ip: '192.168.1.2', port: 8080 },
      device: { name: 'Living Room TV' },
      tools: { ffprobe: true, yt_dlp: true }
    });
    // Explicitly reject status endpoint simulating backend dying when we poll again after drop
    (daemonLib.daemon.status as any).mockImplementation(() => {
        return Promise.reject(new Error('unreachable'));
    });

    await act(async () => {
      render(<App />);
    });

    // Send connected status
    await act(async () => {
      const subscribeCall = (daemonLib.subscribe as any).mock.calls[0][0];
      subscribeCall.onOpen();
      subscribeCall.onStatus({
        cast: { state: 'playing', position: 0, duration: 100 },
        server: { version: '1.0' },
        media_server: { lan_ip: '192.168.1.2', port: 8080 },
        device: { name: 'Living Room TV' },
        tools: { ffprobe: true, yt_dlp: true }
      });
    });

    expect(screen.queryByText('daemon unreachable')).not.toBeInTheDocument();

    // Simulate SSE error/drop
    await act(async () => {
      const subscribeCall = (daemonLib.subscribe as any).mock.calls[0][0];
      subscribeCall.onError();
    });

    expect(screen.getByText('daemon unreachable')).toBeInTheDocument();
    expect(screen.getByText('Launch Daemon (Termux)')).toBeInTheDocument();
  });
});
