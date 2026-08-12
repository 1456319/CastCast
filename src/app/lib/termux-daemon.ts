import { Capacitor, registerPlugin } from "@capacitor/core";

export interface LaunchDaemonResult {
  started: boolean;
  auditLog?: string;
  note?: string;
  rootConfigured?: boolean;
}

interface TermuxDaemonPlugin {
  launch(): Promise<LaunchDaemonResult>;
  getSharedUrl(): Promise<{ url?: string }>;
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

export async function getSharedUrl() {
  if (!canLaunchTermuxDaemon()) return { url: undefined };
  return TermuxDaemon.getSharedUrl();
}

export const TERMUX_MANUAL_COMMAND = [
  "cd /data/data/com.termux/files/home/VideoQualityCheckerApp/daemon",
  "chmod +x ./termux_bootstrap.sh",
  "./termux_bootstrap.sh",
].join(" && ");
