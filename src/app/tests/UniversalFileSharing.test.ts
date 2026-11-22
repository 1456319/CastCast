import { describe, it, expect, vi, beforeEach } from "vitest";
import * as nativeDaemon from "../lib/native-daemon";

let mockSharedResponse: { url?: string; isFile?: boolean; fileName?: string } = {
  url: "/storage/emulated/0/Download/CastCast/Chromecast/inbox/document.pdf",
  isFile: true,
  fileName: "document.pdf",
};

const registeredListeners: Record<string, Function[]> = {};

vi.mock("@capacitor/core", async () => {
  const actual = await vi.importActual<typeof import("@capacitor/core")>("@capacitor/core");
  return {
    ...actual,
    Capacitor: {
      getPlatform: vi.fn(() => "android"),
      isNativePlatform: vi.fn(() => true),
    },
    registerPlugin: vi.fn(() => ({
      checkRequisitions: vi.fn().mockResolvedValue({ state: "running", items: [] }),
      startDaemon: vi.fn().mockResolvedValue({ started: true }),
      stopDaemon: vi.fn().mockResolvedValue({ stopped: true }),
      getSharedUrl: vi.fn(async () => mockSharedResponse),
      addListener: vi.fn((event: string, cb: Function) => {
        if (!registeredListeners[event]) registeredListeners[event] = [];
        registeredListeners[event].push(cb);
        return {
          remove: vi.fn(() => {
            registeredListeners[event] = registeredListeners[event].filter((f) => f !== cb);
          }),
        };
      }),
    })),
  };
});

describe("Universal File Sharing Bridge (Native Embedded)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSharedResponse = {
      url: "/storage/emulated/0/Download/CastCast/Chromecast/inbox/document.pdf",
      isFile: true,
      fileName: "document.pdf",
    };
  });

  it("retrieves staged file information with isFile and fileName", async () => {
    const result = await nativeDaemon.getSharedUrl();
    expect(result).toBeDefined();
    expect(result.url).toBe("/storage/emulated/0/Download/CastCast/Chromecast/inbox/document.pdf");
    expect(result.isFile).toBe(true);
    expect(result.fileName).toBe("document.pdf");
  });

  it("retrieves shared plain text and web URLs when isFile is false", async () => {
    mockSharedResponse = {
      url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      isFile: false,
    };
    const result = await nativeDaemon.getSharedUrl();
    expect(result).toBeDefined();
    expect(result.url).toBe("https://www.youtube.com/watch?v=dQw4w9WgXcQ");
    expect(result.isFile).toBe(false);
  });

  it("registers and triggers sharedUrl event listener", async () => {
    const callback = vi.fn();
    const handle = await nativeDaemon.listenForSharedUrl(callback);
    expect(handle).toBeDefined();
    expect(registeredListeners["sharedUrl"]).toContain(callback);

    // Trigger listener callback
    registeredListeners["sharedUrl"].forEach((fn) => fn());
    expect(callback).toHaveBeenCalledTimes(1);

    // Remove listener
    handle.remove();
    expect(registeredListeners["sharedUrl"]).not.toContain(callback);
  });
});
