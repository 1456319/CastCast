import { describe, it, expect, vi, beforeEach } from "vitest";
import * as termuxDaemon from "../lib/termux-daemon";
import { Capacitor } from "@capacitor/core";

let mockSharedResponse: termuxDaemon.SharedContentResult = {
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
      isNativePlatform: vi.fn(() => true),
    },
    registerPlugin: vi.fn(() => ({
      launch: vi.fn().mockResolvedValue({ started: true }),
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

describe("Universal File Sharing Bridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSharedResponse = {
      url: "/storage/emulated/0/Download/CastCast/Chromecast/inbox/document.pdf",
      isFile: true,
      fileName: "document.pdf",
    };
  });

  it("retrieves staged file information with isFile and fileName", async () => {
    const result = await termuxDaemon.getSharedUrl();
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
    const result = await termuxDaemon.getSharedUrl();
    expect(result).toBeDefined();
    expect(result.url).toBe("https://www.youtube.com/watch?v=dQw4w9WgXcQ");
    expect(result.isFile).toBe(false);
  });

  it("registers and triggers onSharedIntent event listener", () => {
    const callback = vi.fn();
    const handle = termuxDaemon.onSharedIntent(callback);
    expect(handle).toBeDefined();
    expect(registeredListeners["onSharedIntent"]).toContain(callback);

    // Trigger listener callback
    registeredListeners["onSharedIntent"].forEach((fn) => fn());
    expect(callback).toHaveBeenCalledTimes(1);

    // Remove listener
    handle.remove();
    expect(registeredListeners["onSharedIntent"]).not.toContain(callback);
  });
});
