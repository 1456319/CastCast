// synchronization-map: section=web-client; role=native-daemon-client; boundaries=android-bridge; doc=docs/SYNCHRONIZATION_MAP.md
import { Capacitor, registerPlugin, type PluginListenerHandle } from "@capacitor/core";

export interface RequisitionReport {
  state: "stopped" | "starting" | "running" | "stopping";
  items: Array<{ key: string; label: string; ok: boolean; detail: string }>;
}

type SettingsTarget = "app" | "storage" | "battery";

const native = registerPlugin<{
  checkRequisitions(): Promise<RequisitionReport>;
  checkRoot(): Promise<RequisitionReport>;
  requestAccess(): Promise<RequisitionReport>;
  startDaemon(): Promise<{ started: boolean }>;
  stopDaemon(): Promise<{ stopped: boolean }>;
  openSettings(options: { target: SettingsTarget }): Promise<void>;
  getSharedUrl(): Promise<{ url?: string }>;
  addListener(event: "sharedUrl", listener: () => void): Promise<PluginListenerHandle>;
}>("RootProvision");

export const isNativeAndroid = () => Capacitor.getPlatform() === "android";
export const checkRequisitions = () => native.checkRequisitions();
export const checkRoot = () => native.checkRoot();
export const requestAccess = () => native.requestAccess();
export const startNativeDaemon = () => native.startDaemon();
export const stopNativeDaemon = () => native.stopDaemon();
export const openNativeSettings = (target: SettingsTarget) => native.openSettings({ target });
export const getSharedUrl = async () => isNativeAndroid() ? native.getSharedUrl() : { url: undefined };
export const listenForSharedUrl = (listener: () => void) => native.addListener("sharedUrl", listener);
