import { useCallback, useEffect, useState } from "react";
import { Cast, Check, Loader2 } from "lucide-react";
import { daemon, type CastDevice, type HealthReport, type Status } from "../lib/daemon";
import {
  checkTermuxRoot,
  getTermuxSetupStatus,
  launchTermuxDaemon,
  openTermuxSetupScreen,
  requestTermuxCommandPermission,
  type TermuxSetupStatus,
} from "../lib/termux-daemon";

interface Props {
  online: boolean;
  status: Status | null;
  onRefreshStatus: () => Promise<void>;
  onFinish: () => void;
  onStop: () => Promise<void>;
  retainedLogs: string;
}

const secondary = "rounded border border-emerald-500/30 px-3 py-2 text-sm hover:bg-emerald-500/10 disabled:opacity-50";
const primary = "rounded bg-emerald-400 px-4 py-2.5 text-sm font-semibold text-[#06100b] hover:bg-emerald-300 disabled:opacity-50";
const panel = "space-y-3 rounded-lg border border-emerald-500/20 bg-black/40 p-4";
const receiverConnectedStates = new Set(["connected", "launching", "ready", "loading", "buffering", "playing", "paused"]);

export default function FirstRunSetup({ online, status, onRefreshStatus, onFinish, onStop, retainedLogs }: Props) {
  const [setup, setSetup] = useState<TermuxSetupStatus | null>(null);
  const [rootGranted, setRootGranted] = useState(false);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [healthError, setHealthError] = useState("");
  const [healthRevision, setHealthRevision] = useState(0);
  const [devices, setDevices] = useState<CastDevice[] | null>(null);
  const [host, setHost] = useState("");
  const [amazonCode, setAmazonCode] = useState<{ publicCode: string; privateCode: string } | null>(null);
  const [amazonLinked, setAmazonLinked] = useState(false);

  const refreshSetup = useCallback(async () => {
    try {
      setSetup(await getTermuxSetupStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refreshSetup();
    const onReturn = () => {
      if (document.visibilityState === "visible") {
        void refreshSetup();
        setHealthRevision((value) => value + 1);
      }
    };
    document.addEventListener("visibilitychange", onReturn);
    window.addEventListener("focus", onReturn);
    return () => {
      document.removeEventListener("visibilitychange", onReturn);
      window.removeEventListener("focus", onReturn);
    };
  }, [refreshSetup]);

  const bootstrapping = setup?.bootstrapPhase === "running";
  useEffect(() => {
    if (!bootstrapping) return;
    const timer = window.setInterval(refreshSetup, 1500);
    return () => window.clearInterval(timer);
  }, [bootstrapping, refreshSetup]);

  useEffect(() => {
    if (setup?.bootstrapPhase === "complete" && !online) void onRefreshStatus();
  }, [setup?.bootstrapPhase, online, onRefreshStatus]);

  useEffect(() => {
    setHealth(null);
    setHealthError("");
    if (!online) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    let active = true;
    daemon.health(controller.signal).then((report) => {
      if (active) setHealth(report);
    }).catch((err) => {
      if (active) {
        setHealthError(controller.signal.aborted ? "The readiness check timed out." : String(err));
      }
    }).finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [online, healthRevision]);

  const run = async (label: string, operation: () => Promise<unknown>) => {
    setAction(label);
    setError(null);
    try {
      await operation();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAction(null);
    }
  };

  const connect = (address: string, port?: number) => run("Connecting to Chromecast", async () => {
    const result = await daemon.connect(address, port);
    if (!result.connected || !result.device) throw new Error("Could not connect to that Chromecast.");
    await onRefreshStatus();
  });

  const ready = online && health?.ready && !bootstrapping;
  const receiverConnected = !!status?.device && receiverConnectedStates.has(status.cast.state);

  return (
    <main className="min-h-screen bg-[#050807] px-4 py-8 text-emerald-200" style={{ fontFamily: "'Exo 2', sans-serif" }}>
      <div className="mx-auto max-w-lg space-y-4">
        <header className="space-y-2">
          <Cast aria-hidden="true" className="h-7 w-7 text-emerald-400" />
          <h1 className="text-2xl font-semibold">Set up CastCast</h1>
          <p className="text-sm text-emerald-200/70">Prepare Termux and connect to your Chromecast.</p>
        </header>

        {!online && (
          <>
            <section className={panel}>
              <h2 className="font-semibold">Termux</h2>
              {!setup ? <p className="text-sm">Checking for Termux…</p> : setup.termuxInstalled ? (
                <>
                  <p className="text-sm">Installed. On a new phone, open it once and wait for the shell prompt.</p>
                  <div className="flex flex-wrap gap-2">
                    <button className={secondary} disabled={!!action} onClick={() => void run("Opening Termux", () => openTermuxSetupScreen("termux"))}>Open Termux</button>
                    <button className={secondary} disabled={!!action} onClick={() => void run("Opening file access settings", () => openTermuxSetupScreen("termuxPermissions"))}>Termux file access</button>
                  </div>
                </>
              ) : (
                <button className={primary} disabled={!!action} onClick={() => void run("Opening F-Droid", () => openTermuxSetupScreen("installTermux"))}>Install Termux from F-Droid</button>
              )}
            </section>

            {setup?.termuxInstalled && (
              <section className={panel}>
                <h2 className="font-semibold">Permissions</h2>
                <div className="space-y-2">
                  <p className="text-sm">{rootGranted ? "Root access verified." : "Check root and approve CastCast if your root manager prompts."}</p>
                  <button className={secondary} disabled={!!action || bootstrapping} onClick={() => void run("Checking root", async () => {
                    setRootGranted(false);
                    const result = await checkTermuxRoot();
                    setRootGranted(result.hasRoot);
                    if (!result.hasRoot) throw new Error("CastCast could not get root. Approve it in your root manager, then retry.");
                  })}>{rootGranted ? "Check root again" : "Check root"}</button>
                </div>
                <div className="space-y-2">
                  <p className="text-sm">{setup.runCommandGranted ? "CastCast can run commands in Termux." : "In CastCast’s Android settings, open Permissions → Additional permissions and allow Run commands in Termux."}</p>
                  {!setup.runCommandGranted && (
                    <div className="flex flex-wrap gap-2">
                      <button className={secondary} disabled={!!action} onClick={() => void run("Requesting Termux permission", async () => {
                        setSetup(await requestTermuxCommandPermission());
                      })}>Request permission</button>
                      <button className={secondary} disabled={!!action} onClick={() => void run("Opening CastCast permissions", () => openTermuxSetupScreen("castCastPermissions"))}>Open CastCast permissions</button>
                    </div>
                  )}
                </div>
              </section>
            )}

            <section className={panel}>
              <h2 className="font-semibold">Prepare the daemon</h2>
              <p className="text-sm">Install missing packages and start the daemon using the copy bundled with CastCast.</p>
              <div className="flex flex-wrap gap-2">
                <button className={primary} disabled={!rootGranted || !setup?.runCommandGranted || !!action || bootstrapping} onClick={() => void run("Preparing Termux", async () => {
                  await launchTermuxDaemon();
                  await refreshSetup();
                })}>{setup?.bootstrapPhase === "failed" || setup?.bootstrapPhase === "timedOut" ? "Retry setup" : "Install dependencies and start"}</button>
                <button className={secondary} disabled={!!action} onClick={() => void run("Checking setup", async () => {
                  await refreshSetup();
                  await onRefreshStatus();
                })}>Check again</button>
              </div>
              {bootstrapping && <p role="status" className="text-sm">Installing missing packages and starting the daemon. This can take several minutes.</p>}
              {setup?.bootstrapPhase === "timedOut" && <p role="alert" className="text-sm text-amber-300">Termux has not returned a result. Open Termux to check the installation before retrying.</p>}
              {setup?.bootstrapPhase === "complete" && <p className="text-sm">Termux reported startup complete. Waiting for the local daemon.</p>}
              {setup?.bootstrapPhase === "failed" && <p role="alert" className="text-sm text-amber-300">Termux setup failed. Open Setup logs for the error.</p>}
              <details open={setup?.bootstrapPhase === "failed"} className="text-sm text-emerald-200/70">
                <summary className="cursor-pointer">Setup logs</summary>
                <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words text-xs">{[setup?.bootstrapDetail, retainedLogs].filter(Boolean).join("\n\n") || "No log entries yet."}</pre>
              </details>
              <details className="text-sm text-emerald-200/70">
                <summary className="cursor-pointer">Daemon recovery</summary>
                <button className={`${secondary} mt-2`} disabled={!!action || bootstrapping} onClick={() => void run("Stopping daemon", onStop)}>Force stop daemon</button>
              </details>
            </section>
          </>
        )}

        {online && (
          <section className={panel}>
            <h2 className="font-semibold">Readiness</h2>
            {!health && !healthError && <p role="status" className="text-sm">Checking tools, storage and network…</p>}
            {healthError && <p role="alert" className="text-sm text-amber-300">{healthError}</p>}
            {health?.checks.map((check) => (
              <div key={check.key} className="break-words text-sm">
                <div className={check.ok ? "text-emerald-200" : "text-amber-300"}>
                  {check.ok ? <Check aria-label="Passed" className="mr-1 inline h-4 w-4" /> : null}{check.label}
                </div>
                <p className="text-emerald-200/70">{check.detail}</p>
                {!check.ok && check.remedy && <p className="text-amber-300">{check.remedy}</p>}
              </div>
            ))}
            {status?.tools.yt_dlp === false && <p className="text-sm text-amber-300">yt-dlp is unavailable. Local casting is available when the checks pass.</p>}
            <button className={secondary} onClick={() => setHealthRevision((value) => value + 1)}>Run checks again</button>
          </section>
        )}

        {ready && (
          <section className={panel}>
            <h2 className="font-semibold">Chromecast</h2>
            {receiverConnected && status?.device ? <p className="text-sm">Connected to {status.device.friendly_name || status.device.host}.</p> : (
              <>
                {status?.device && (
                  <p className="text-sm" role="status">
                    {status.cast.last_error || `Connecting to ${status.device.friendly_name || status.device.host}…`}
                  </p>
                )}
                <button className={secondary} disabled={!!action} onClick={() => void run("Scanning for Chromecasts", async () => {
                  setDevices((await daemon.devices()).devices);
                })}>Find Chromecast</button>
                {devices?.length === 0 && <p className="text-sm">No receivers found. Check Wi-Fi or enter the receiver’s IP address.</p>}
                {devices?.map((device) => (
                  <button key={`${device.host}:${device.port}`} className={`${secondary} block w-full text-left`} disabled={!!action} onClick={() => void connect(device.host, device.port)}>
                    {device.friendly_name || device.host}
                  </button>
                ))}
                <form className="space-y-2" onSubmit={(event) => {
                  event.preventDefault();
                  if (host.trim()) void connect(host.trim());
                }}>
                  <label htmlFor="setup-chromecast-ip" className="block text-sm">Chromecast IP address</label>
                  <div className="flex gap-2">
                    <input id="setup-chromecast-ip" className="min-w-0 flex-1 rounded border border-emerald-500/30 bg-black px-3 py-2 text-sm" value={host} onChange={(event) => setHost(event.target.value)} autoCapitalize="off" autoCorrect="off" />
                    <button className={secondary} disabled={!!action || !host.trim()} type="submit">Connect</button>
                  </div>
                </form>
              </>
            )}
          </section>
        )}

        {ready && (
          <details className={panel}>
            <summary className="cursor-pointer font-semibold">Prime Video account</summary>
            {amazonLinked ? <p className="text-sm">Amazon approved this device.</p> : (
              <>
                <p className="text-sm">Link your Amazon account here if you plan to cast Prime Video.</p>
                {amazonCode ? (
                  <>
                    <p className="text-sm">Enter <strong className="font-mono text-emerald-300">{amazonCode.publicCode}</strong> at Amazon’s device registration page.</p>
                    <a className={`${secondary} inline-block`} href="https://www.amazon.com/code" rel="noreferrer">Open Amazon</a>
                    <button className={`${secondary} ml-2`} disabled={!!action} onClick={() => void run("Checking Amazon approval", async () => {
                      const result = await daemon.checkAmazonDeviceCode(amazonCode.publicCode, amazonCode.privateCode);
                      if (!result.response?.success) throw new Error("Amazon has not confirmed this code. Approve it at Amazon or request a new code.");
                      setAmazonLinked(true);
                      setAmazonCode(null);
                    })}>Check approval</button>
                  </>
                ) : null}
                <button className={`${secondary} block`} disabled={!!action} onClick={() => void run("Requesting Amazon code", async () => {
                  const result = await daemon.amazonDeviceCode();
                  const publicCode = result.public_code ?? result.code_data?.public_code;
                  const privateCode = result.private_code ?? result.code_data?.private_code;
                  if (!publicCode || !privateCode) throw new Error("Amazon did not return a registration code.");
                  setAmazonCode({ publicCode, privateCode });
                })}>{amazonCode ? "Get a new code" : "Get Amazon registration code"}</button>
              </>
            )}
          </details>
        )}

        {action && <p role="status" className="text-sm"><Loader2 aria-hidden="true" className="mr-2 inline h-4 w-4 animate-spin" />{action}…</p>}
        {error && <p role="alert" className="break-words rounded border border-amber-500/30 p-3 text-sm text-amber-300">{error}</p>}
        {ready && <button className={receiverConnected ? primary : secondary} disabled={!!action} onClick={onFinish}>{receiverConnected ? "Open CastCast" : "Continue without connecting"}</button>}
      </div>
    </main>
  );
}
