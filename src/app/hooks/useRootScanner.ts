import { useState, useEffect, useRef, useCallback } from "react";
import { StreamInfo, StreamMetrics, StreamState } from "../types/stream";
import { RootIpcService } from "../services/RootIpcService";

export function useRootScanner() {
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [streamInfo, setStreamInfo] = useState<StreamInfo | null>(null);
  const [metrics, setMetrics] = useState<StreamMetrics>({ bufferHealth: 0, networkSpeed: 0 });
  const [scanLog, setScanLog] = useState<string[]>([]);
  const [hasRoot, setHasRoot] = useState(false);

  const ipcService = useRef<RootIpcService | null>(null);

  useEffect(() => {
    // Initialize IPC service once
    ipcService.current = new RootIpcService();

    ipcService.current.onStateChange((state) => setStreamState(state));
    ipcService.current.onRootAccessChange((root) => setHasRoot(root));
    ipcService.current.onStreamFound((info) => setStreamInfo(info));
    ipcService.current.onMetrics((m) => setMetrics(m));
    ipcService.current.onLog((msg) => {
      const ts = new Date().toISOString().slice(11, 23);
      setScanLog((prev) => [...prev.slice(-40), `[${ts}] ${msg}`]);
    });

    return () => {
      ipcService.current?.disconnect();
    };
  }, []);

  const requestRootAccess = useCallback(() => {
    ipcService.current?.requestRootAccess();
  }, []);

  const startScan = useCallback(() => {
    setStreamInfo(null);
    setScanLog([]);
    ipcService.current?.startScan();
  }, []);

  const reset = useCallback(() => {
    setStreamInfo(null);
    setScanLog([]);
    ipcService.current?.reset();
  }, []);

  return {
    streamState,
    streamInfo,
    metrics,
    scanLog,
    hasRoot,
    requestRootAccess,
    startScan,
    reset
  };
}
