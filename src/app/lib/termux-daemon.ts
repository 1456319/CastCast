// synchronization-map: section=web-client; role=termux-client; boundaries=android-bridge; doc=docs/SYNCHRONIZATION_MAP.md
import { Capacitor, registerPlugin, PluginListenerHandle } from "@capacitor/core";

export interface LaunchDaemonResult {
  started: boolean;
  auditLog?: string;
  note?: string;
  rootConfigured?: boolean;
}

export interface SharedContentResult {
  url?: string;
  isFile?: boolean;
  fileName?: string;
}

interface TermuxDaemonPlugin {
  launch(): Promise<LaunchDaemonResult>;
  stopDaemon(): Promise<{ stopped: boolean }>;
  getSharedUrl(): Promise<SharedContentResult>;
  addListener(eventName: "onSharedIntent", listenerFunc: () => void): Promise<PluginListenerHandle> & PluginListenerHandle;
}

const TermuxDaemon = registerPlugin<TermuxDaemonPlugin>("TermuxDaemon");

export function canLaunchTermuxDaemon() {
  return Capacitor.isNativePlatform();
}

export async function launchTermuxDaemon() {
  if (!canLaunchTermuxDaemon()) {
    throw new Error("Automatic launch is only available in the Android APK. In a browser, copy the Termux command below.");
  }
  return TermuxDaemon.launch();
}

export async function stopTermuxDaemon() {
  if (!canLaunchTermuxDaemon()) {
    return { stopped: false };
  }
  return TermuxDaemon.stopDaemon();
}

export async function getSharedUrl(): Promise<SharedContentResult> {
  if (!canLaunchTermuxDaemon()) return { url: undefined };
  return TermuxDaemon.getSharedUrl();
}

export function onSharedIntent(callback: () => void) {
  if (!canLaunchTermuxDaemon()) return { remove: () => {} };
  return TermuxDaemon.addListener("onSharedIntent", callback);
}

export const TERMUX_KILL_COMMAND = "pkill -9 -f castcast; pkill -9 -f mediaserver.py; pkill -9 -f 'localhost.run|pinggy.io' || true";

export const TERMUX_MANUAL_COMMAND = [
  "cd /data/data/com.termux/files/home/CastCast/daemon",
  "chmod +x ./termux_bootstrap.sh",
  "./termux_bootstrap.sh",
].join(" && ");
