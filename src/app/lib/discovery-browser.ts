import { registerPlugin, PluginListenerHandle } from "@capacitor/core";

export interface StreamDetectedEvent {
  url: string;
  method: string;
  headers: Record<string, string>;
  type: "manifest" | "drm";
}

export interface DiscoveryBrowserPlugin {
  open(options: { url: string }): Promise<void>;
  close(): Promise<void>;
  addListener(
    eventName: "onStreamDetected",
    listenerFunc: (event: StreamDetectedEvent) => void
  ): Promise<PluginListenerHandle> & PluginListenerHandle;
}

const DiscoveryBrowser = registerPlugin<DiscoveryBrowserPlugin>("DiscoveryBrowser");

export { DiscoveryBrowser };
