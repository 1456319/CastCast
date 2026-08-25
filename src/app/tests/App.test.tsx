import { render, screen, waitFor, act, fireEvent, cleanup } from '@testing-library/react';
import App from '../App';
import * as daemonLib from '../lib/daemon';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

vi.mock('../lib/daemon', async (importOriginal) => {
  const actual = await importOriginal<typeof daemonLib>();
  return {
    ...actual,
    daemon: {
      status: vi.fn(),
      shutdown: vi.fn(),
      getAmazonQueue: vi.fn(),
      getTrash: vi.fn(),
      library: vi.fn(),
      reorderAmazonQueue: vi.fn()
    },
    subscribe: vi.fn()
  };
});

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    // Set initial mock returns
    vi.mocked(daemonLib.daemon.status).mockRejectedValue(new Error('offline'));
    vi.mocked(daemonLib.daemon.library).mockResolvedValue({ items: [] });
    vi.mocked(daemonLib.daemon.getTrash).mockResolvedValue({ items: [] });
    vi.mocked(daemonLib.daemon.getAmazonQueue).mockResolvedValue({ items: [] });
    vi.mocked(daemonLib.subscribe).mockReturnValue(vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('renders Launch Daemon splash screen when offline', async () => {
    render(<App />);

    // Should initially show the disconnected view
    expect(screen.getByText('daemon unreachable')).toBeInTheDocument();
    expect(screen.getByText('Launch Daemon (Termux)')).toBeInTheDocument();

    // Verify it polls for status
    expect(daemonLib.daemon.status).toHaveBeenCalled();
  });

  it('transitions to online state when daemon responds', async () => {
    // Start with successful response
    vi.mocked(daemonLib.daemon.status).mockResolvedValue({
      connected: true,
      device: null,
      media_server: { base_url: '', lan_ip: '', port: 0, roots: [] },
      tools: { ffmpeg: true, ffprobe: true, yt_dlp: true },
      remux: null,
      cast: {
        state: 'idle', position: 0, duration: 0, volume: 1, muted: false,
        title: '', reconnects: 0, stream_stalls: 0, last_error: '',
        idle_reason: '', source_path: ''
      }
    });

    const mockUnsubscribe = vi.fn();
    vi.mocked(daemonLib.subscribe).mockReturnValue(mockUnsubscribe);

    render(<App />);

    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    await waitFor(() => {
      expect(screen.queryByText('Launch Daemon (Termux)')).not.toBeInTheDocument();
    });
  });

  it('properly cleans up on Kill Server', async () => {
    vi.mocked(daemonLib.daemon.status).mockResolvedValue({
      connected: true,
      device: { host: '192.168.1.100', friendly_name: 'Living Room TV', model: 'Chromecast', is_ultra: true },
      media_server: { base_url: '', lan_ip: '', port: 0, roots: [] },
      tools: { ffmpeg: true, ffprobe: true, yt_dlp: true },
      remux: null,
      cast: {
        state: 'idle', position: 0, duration: 0, volume: 1, muted: false,
        title: '', reconnects: 0, stream_stalls: 0, last_error: '',
        idle_reason: '', source_path: ''
      }
    });
    vi.mocked(daemonLib.daemon.shutdown).mockResolvedValue({});

    const mockUnsubscribe = vi.fn();
    vi.mocked(daemonLib.subscribe).mockReturnValue(mockUnsubscribe);
    const clearIntervalSpy = vi.spyOn(global, 'clearInterval');

    render(<App />);

    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    await waitFor(() => {
      expect(screen.getByText(/Living Room TV/i)).toBeInTheDocument();
    });

    vi.spyOn(window, 'confirm').mockImplementation(() => true);

    const buttons = screen.getAllByRole('button');
    const killBtn = buttons.find(b => b.textContent?.toLowerCase().includes('kill server'));
    if (killBtn) {
      fireEvent.click(killBtn);
    }

    await waitFor(() => {
      expect(daemonLib.daemon.shutdown).toHaveBeenCalled();
      expect(mockUnsubscribe).toHaveBeenCalled();
      expect(clearIntervalSpy).toHaveBeenCalled();
    });
  });

  it('updates state via SSE', async () => {
     let sseHandlers: daemonLib.SubscribeArgs = {};
     vi.mocked(daemonLib.subscribe).mockImplementation((handlers) => {
       sseHandlers = handlers;
       return vi.fn();
     });

     vi.mocked(daemonLib.daemon.status).mockResolvedValue({
       connected: true,
       device: null,
       media_server: { base_url: '', lan_ip: '', port: 0, roots: [] },
       tools: { ffmpeg: true, ffprobe: true, yt_dlp: true },
       remux: null,
       cast: {
         state: 'idle', position: 0, duration: 0, volume: 1, muted: false,
         title: '', reconnects: 0, stream_stalls: 0, last_error: '',
         idle_reason: '', source_path: ''
       }
     });

     render(<App />);

     await act(async () => {
       vi.advanceTimersByTime(100);
     });

     await waitFor(() => {
       expect(screen.queryByText('Launch Daemon (Termux)')).not.toBeInTheDocument();
     });

     act(() => {
       if (sseHandlers.onMedia) {
         sseHandlers.onMedia({
           state: 'playing', position: 10, duration: 100, volume: 1, muted: false,
           title: 'Test Movie', reconnects: 0, stream_stalls: 0, last_error: '',
           idle_reason: '', source_path: ''
         });
       }
     });

     await waitFor(() => {
       expect(screen.queryByText(/Launch Daemon/i)).not.toBeInTheDocument();
     });
  });

  it('handles Amazon queue drag and drop', async () => {
    vi.mocked(daemonLib.daemon.status).mockResolvedValue({
      connected: true,
      device: null,
      media_server: { base_url: '', lan_ip: '', port: 0, roots: [] },
      tools: { ffmpeg: true, ffprobe: true, yt_dlp: true },
      remux: null,
      cast: {
        state: 'idle', position: 0, duration: 0, volume: 1, muted: false,
        title: '', reconnects: 0, stream_stalls: 0, last_error: '',
        idle_reason: '', source_path: ''
      }
    });

    render(<App />);

    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    // Simulate SSE
    act(() => {
      const calls = vi.mocked(daemonLib.subscribe).mock.calls;
      if (calls.length > 0) {
        const args = calls[0][0];
        if (args.onAmazonQueue) {
          args.onAmazonQueue({ items: [
            { url: 'url1', title: 'Video 1' },
            { url: 'url2', title: 'Video 2' }
          ] });
        }
      }
    });

    await waitFor(() => {
      expect(screen.getByText('Video 1')).toBeInTheDocument();
      expect(screen.getByText('Video 2')).toBeInTheDocument();
    });

    const items = screen.getAllByText(/Video \d/i);

    const dragWrapper1 = items[0].parentElement?.closest('div[draggable="true"]');
    const dragWrapper2 = items[1].parentElement?.closest('div[draggable="true"]');
    expect(dragWrapper1).toBeInTheDocument();
    expect(dragWrapper2).toBeInTheDocument();

    // Simulate drag drop (Video 1 -> Video 2)
    fireEvent.dragStart(dragWrapper1!, {
      dataTransfer: { setData: vi.fn() }
    });

    fireEvent.drop(dragWrapper2!, {
      dataTransfer: { getData: () => JSON.stringify({ index: 0, type: 'amazon' }) }
    });

    await waitFor(() => {
      expect(daemonLib.daemon.reorderAmazonQueue).toHaveBeenCalled();
    });
  });

  it('detects and warns about zombie daemon processes', async () => {
    // Mock status to simulate a 500 or malformed JSON (a rejected promise due to fetch throw)
    // specifically indicating the port is responsive but broken.
    vi.mocked(daemonLib.daemon.status).mockRejectedValue(new Error('500 Internal Server Error'));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Daemon process found, but unresponsive. You may need to Force Stop Termux.')).toBeInTheDocument();
    });

    cleanup();

    vi.mocked(daemonLib.daemon.status).mockRejectedValue(new SyntaxError('Unexpected end of JSON input'));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Daemon process found, but unresponsive. You may need to Force Stop Termux.')).toBeInTheDocument();
    });

  });
});
