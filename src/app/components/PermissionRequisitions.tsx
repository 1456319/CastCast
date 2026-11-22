// synchronization-map: section=web-client; role=permission-requisitions; boundaries=android-bridge; doc=docs/SYNCHRONIZATION_MAP.md
import { useEffect, useState } from "react";
import {
  checkRequisitions, checkRoot, openNativeSettings, requestAccess,
  startNativeDaemon, stopNativeDaemon, type RequisitionReport,
} from "../lib/native-daemon";

const button = "rounded border border-emerald-500/30 px-3 py-2 text-xs hover:bg-emerald-500/15 disabled:opacity-50";

export function PermissionRequisitions({ online, onRefresh }: {
  online: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [report, setReport] = useState<RequisitionReport>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    const update = () => {
      void checkRequisitions().then((value) => { if (mounted) setReport(value); })
        .catch((failure) => { if (mounted) setError(String(failure)); });
    };
    update();
    const timer = window.setInterval(update, 1500);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  const action = async (run: () => Promise<unknown>) => {
    setError("");
    setBusy(true);
    try {
      await run();
      setReport(await checkRequisitions());
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const starting = report?.state === "starting" || report?.state === "stopping";
  return (
    <section className="space-y-3 rounded border border-emerald-500/25 bg-black/40 p-4">
      <h2 className="font-semibold">Android setup</h2>
      <ul className="space-y-2 text-sm">
        {report?.items.map((item) => (
          <li key={item.key} className="flex items-start justify-between gap-3">
            <span>{item.label}</span>
            <span className={`max-w-[60%] break-words text-right ${item.ok ? "text-emerald-300" : "text-amber-300"}`}>{item.detail}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy} onClick={() => void action(checkRoot)}>Check root</button>
        <button className={button} disabled={busy} onClick={() => void action(requestAccess)}>Request permissions</button>
        <button className={button} disabled={busy} onClick={() => void action(() => openNativeSettings("storage"))}>Shared storage</button>
        <button className={button} disabled={busy} onClick={() => void action(() => openNativeSettings("battery"))}>Battery settings</button>
        {online || report?.state === "running" ? (
          <button className={button} disabled={busy} onClick={() => void action(stopNativeDaemon)}>Stop daemon</button>
        ) : (
          <button className={`${button} bg-emerald-500/15`} disabled={busy || starting} onClick={() => void action(async () => {
            await requestAccess();
            await startNativeDaemon();
          })}>{starting ? "Please wait…" : "Set up and launch"}</button>
        )}
      </div>
      {error && <p role="alert" className="break-words text-sm text-amber-300">{error}</p>}
    </section>
  );
}
