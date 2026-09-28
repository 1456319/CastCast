import { describe, it, expect, vi, beforeEach } from "vitest";
import * as termuxDaemon from "../lib/termux-daemon";
import { Capacitor } from "@capacitor/core";

vi.mock("@capacitor/core", async () => {
  const actual = await vi.importActual<typeof import("@capacitor/core")>("@capacitor/core");
  const listeners: Record<string, Function[]> = {};
  return {
    ...actual,
    Capacitor: {
      isNativePlatform: vi.fn(() => true),
    },
    registerPlugin: vi.fn(() => ({
      launch: vi.fn().mockResolvedValue({ started: true }),
      stopDaemon: vi.fn().mockResolvedValue({ stopped: true }),
      getSharedUrl: vi.fn().mockResolvedValue({
        url: "/storage/emulated/0/Download/CastCast/Chromecast/inbox/document.pdf",
        isFile: true,
        fileName: "document.pdf",
      }),
      addListener: vi.fn((event: string, cb: Function) => {
        if (!listeners[event]) listeners[event] = [];
        listeners[event].push(cb);
        return {
          remove: vi.fn(() => {
            listeners[event] = listeners[event].filter((f) => f !== cb);
          }),
        };
      }),
    })),
  };
});

describe("Universal File Sharing Bridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("retrieves staged file information with isFile and fileName", async () => {
    const result = await termuxDaemon.getSharedUrl();
    expect(result).toBeDefined();
    expect(result.url).toBe("/storage/emulated/0/Download/CastCast/Chromecast/inbox/document.pdf");
    expect(result.isFile).toBe(true);
    expect(result.fileName).toBe("document.pdf");
  });

  it("registers onSharedIntent event listener", async () => {
    const callback = vi.fn();
    const handle = termuxDaemon.onSharedIntent(callback);
    expect(handle).toBeDefined();
    expect(handle.remove).toBeInstanceOf(Function);
  });
});
