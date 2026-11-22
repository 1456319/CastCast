// synchronization-map: section=web-client; role=amazon-auth-card; boundaries=api-contract; doc=docs/SYNCHRONIZATION_MAP.md
import { useEffect, useState } from "react";
import { daemon } from "../lib/daemon";

export function AmazonAuthCard({ authenticated, publicUrl, onAuthenticated }: {
  authenticated: boolean;
  publicUrl?: string | null;
  onAuthenticated: () => Promise<void>;
}) {
  const [pair, setPair] = useState<{ publicCode: string; privateCode: string }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!pair) return;
    const controller = new AbortController();
    const expires = Date.now() + 120_000;
    let timer: number;
    const poll = async () => {
      try {
        const data = await daemon.amazonAuthPoll(pair.publicCode, pair.privateCode, controller.signal);
        if (controller.signal.aborted) return;
        if (data.response?.success) {
          setPair(undefined);
          void onAuthenticated();
          return;
        }
      } catch {
        if (controller.signal.aborted) return;
      }
      if (Date.now() >= expires) {
        setError("Registration timed out. Request a fresh code.");
        setPair(undefined);
      } else {
        timer = window.setTimeout(poll, 3500);
      }
    };
    timer = window.setTimeout(poll, 3500);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [pair, onAuthenticated]);

  return (
    <section className="space-y-2 rounded border border-emerald-500/20 bg-black/40 p-3 text-sm">
      <h2 className="font-semibold">Prime Video</h2>
      <p className={publicUrl ? "text-emerald-300" : "text-amber-300"}>{publicUrl ? "HTTPS license tunnel ready" : "HTTPS license tunnel unavailable"}</p>
      {pair ? (
        <>
          <p>Enter <strong className="font-mono text-emerald-300">{pair.publicCode}</strong> on Amazon’s registration page.</p>
          <a className="underline" href="https://www.amazon.com/code" rel="noreferrer">Open Amazon</a>
          <button className="ml-3 underline" onClick={() => setPair(undefined)}>Cancel</button>
        </>
      ) : (
        <>
          {authenticated && <p>Account paired</p>}
          <button className="rounded border border-emerald-500/35 px-3 py-2 disabled:opacity-50" disabled={busy} onClick={async () => {
            setBusy(true);
            setError("");
            try {
              const { code_data, public_code, private_code } = await daemon.amazonAuthStart();
              const publicCode = public_code ?? code_data?.public_code;
              const privateCode = private_code ?? code_data?.private_code;
              if (!publicCode || !privateCode) throw new Error("Amazon did not return a registration code.");
              setPair({ publicCode, privateCode });
            } catch (failure) {
              setError(failure instanceof Error ? failure.message : String(failure));
            } finally {
              setBusy(false);
            }
          }}>{busy ? "Requesting code…" : authenticated ? "Pair again" : "Pair Prime Video account"}</button>
        </>
      )}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
    </section>
  );
}
