// synchronization-map: section=android-bridge; role=termux-launch-plugin; boundaries=web-client,config-state,operations-release; doc=docs/SYNCHRONIZATION_MAP.md
package app.videoqualitychecker.castcast;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.SharedPreferences;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.BufferedReader;
import java.io.DataOutputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

@CapacitorPlugin(name = "TermuxDaemon", permissions = {
    @Permission(alias = "runCommand", strings = { "com.termux.permission.RUN_COMMAND" })
})
public class TermuxDaemonPlugin extends Plugin {
    private static final String TERMUX_PACKAGE = "com.termux";
    private static final String RUN_COMMAND_SERVICE = "com.termux.app.RunCommandService";
    private static final String ACTION_RUN_COMMAND = "com.termux.RUN_COMMAND";
    private static final String EXTRA_COMMAND_PATH = "com.termux.RUN_COMMAND_PATH";
    private static final String EXTRA_ARGUMENTS = "com.termux.RUN_COMMAND_ARGUMENTS";
    private static final String EXTRA_WORKDIR = "com.termux.RUN_COMMAND_WORKDIR";
    private static final String EXTRA_BACKGROUND = "com.termux.RUN_COMMAND_BACKGROUND";
    private static final String EXTRA_SESSION_ACTION = "com.termux.RUN_COMMAND_SESSION_ACTION";
    private static final String EXTRA_PENDING_INTENT = "com.termux.RUN_COMMAND_PENDING_INTENT";
    private static final String RUN_COMMAND_PERMISSION = "com.termux.permission.RUN_COMMAND";
    private static final int ROOT_TIMEOUT_SECONDS = 30;
    private static final long SETUP_TIMEOUT_MS = TimeUnit.MINUTES.toMillis(10);

    private static final String BASH = "/data/data/com.termux/files/usr/bin/bash";
    private static final String DAEMON_DIR = "/data/data/com.termux/files/home/CastCast/daemon";
    private static final String BOOTSTRAP = DAEMON_DIR + "/termux_bootstrap.sh";

    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;

    private boolean canRunTermuxCommands() {
        return getContext().checkSelfPermission(RUN_COMMAND_PERMISSION) == PackageManager.PERMISSION_GRANTED;
    }

    private static String bootstrapPhase(SharedPreferences prefs) {
        String phase = prefs.getString("phase", "idle");
        if ("running".equals(phase) &&
                System.currentTimeMillis() - prefs.getLong("startedAt", 0) >= SETUP_TIMEOUT_MS) {
            return "timedOut";
        }
        return phase;
    }

    @PluginMethod
    public void getSetupStatus(PluginCall call) {
        Context context = getContext();
        SharedPreferences prefs = TermuxSetupResultReceiver.preferences(context);
        JSObject result = new JSObject();
        result.put("termuxInstalled", context.getPackageManager().getLaunchIntentForPackage(TERMUX_PACKAGE) != null);
        result.put("runCommandGranted", canRunTermuxCommands());
        result.put("bootstrapPhase", bootstrapPhase(prefs));
        result.put("bootstrapDetail", prefs.getString("detail", ""));
        call.resolve(result);
    }

    @PluginMethod
    public void requestRunCommandPermission(PluginCall call) {
        if (canRunTermuxCommands()) {
            getSetupStatus(call);
            return;
        }
        requestPermissionForAlias("runCommand", call, "onRunCommandPermissionResult");
    }

    @PermissionCallback
    private void onRunCommandPermissionResult(PluginCall call) {
        getSetupStatus(call);
    }

    @PluginMethod
    public void openSetupScreen(PluginCall call) {
        String target = call.getString("target", "");
        Intent intent;
        switch (target) {
            case "installTermux":
                intent = new Intent(Intent.ACTION_VIEW, Uri.parse("https://f-droid.org/packages/com.termux/"));
                break;
            case "termux":
                intent = getContext().getPackageManager().getLaunchIntentForPackage(TERMUX_PACKAGE);
                break;
            case "termuxPermissions":
                intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + TERMUX_PACKAGE));
                break;
            case "castCastPermissions":
                intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + getContext().getPackageName()));
                break;
            default:
                call.reject("Unknown setup screen.");
                return;
        }
        if (intent == null) {
            call.reject("Install Termux before opening it.");
            return;
        }
        try {
            getActivity().startActivity(intent);
            call.resolve();
        } catch (Exception e) {
            call.reject("Android could not open this setup screen.", e);
        }
    }

    @PluginMethod
    public synchronized void launch(PluginCall call) {
        PackageManager packageManager = getContext().getPackageManager();
        if (packageManager.getLaunchIntentForPackage(TERMUX_PACKAGE) == null) {
            call.reject("Install Termux, open it once, then return to setup.");
            return;
        }
        if (!canRunTermuxCommands()) {
            call.reject("Allow CastCast to run commands in Termux in Android Settings.");
            return;
        }
        SharedPreferences prefs = TermuxSetupResultReceiver.preferences(getContext());
        if ("running".equals(bootstrapPhase(prefs))) {
            call.reject("Termux is already preparing CastCast.");
            return;
        }

        RootResult rootResult = configureTermuxWithRoot();
        if (!rootResult.success) {
            call.reject(
                "Root automation could not configure Termux. Open your root manager, grant root to this app, then retry. Details: " + rootResult.summary()
            );
            return;
        }

        Intent intent = new Intent(ACTION_RUN_COMMAND);
        intent.setClassName(TERMUX_PACKAGE, RUN_COMMAND_SERVICE);
        intent.putExtra(EXTRA_COMMAND_PATH, BASH);
        intent.putExtra(EXTRA_ARGUMENTS, new String[] { "-lc", "bash '" + BOOTSTRAP + "'" });
        intent.putExtra(EXTRA_WORKDIR, DAEMON_DIR);
        intent.putExtra(EXTRA_BACKGROUND, true);
        intent.putExtra(EXTRA_SESSION_ACTION, "0");
        String attemptId = UUID.randomUUID().toString();
        Intent resultIntent = new Intent(getContext(), TermuxSetupResultReceiver.class)
            .setData(Uri.fromParts("castcast-setup", attemptId, null));
        int flags = PendingIntent.FLAG_ONE_SHOT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) flags |= PendingIntent.FLAG_MUTABLE;
        PendingIntent callback = PendingIntent.getBroadcast(getContext(), 0, resultIntent, flags);
        intent.putExtra(EXTRA_PENDING_INTENT, callback);
        prefs.edit().putString("attemptId", attemptId).putString("phase", "running")
            .putLong("startedAt", System.currentTimeMillis()).remove("detail").commit();

        try {
            PowerManager pm = (PowerManager) getContext().getSystemService(Context.POWER_SERVICE);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                getContext().startForegroundService(intent);
            } else {
                getContext().startService(intent);
            }

            if (wakeLock == null) {
                wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CastCast:DaemonWakeLock");
                wakeLock.acquire();
            }
            if (wifiLock == null) {
                WifiManager wm = (WifiManager) getContext().getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                wifiLock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "CastCast:DaemonWifiLock");
                wifiLock.acquire();
            }

            JSObject result = new JSObject();
            result.put("started", true);
            result.put("rootConfigured", true);
            result.put("auditLog", "/storage/emulated/0/Download/CastCast/Chromecast/.castcast/audit.log");
            result.put("note", "Termux is checking storage, installing missing packages and starting the daemon.");
            call.resolve(result);
        } catch (Exception e) {
            callback.cancel();
            String detail = "Unable to start Termux: " + e.getMessage();
            prefs.edit().putString("phase", "failed").putString("detail", detail).apply();
            call.reject(detail, e);
        }
    }

    @PluginMethod
    public void checkRoot(PluginCall call) {
        try {
            ProcessBuilder pb = new ProcessBuilder("su", "-M");
            pb.redirectErrorStream(true);
            Process process = pb.start();
            try (DataOutputStream stdin = new DataOutputStream(process.getOutputStream())) {
                stdin.writeBytes("id -u\nexit\n");
                stdin.flush();
            }
            boolean finished = process.waitFor(ROOT_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                call.reject("Root check timed out. Is your root manager (Magisk, KernelSU, etc.) running?");
                return;
            }
            String output = readStream(process.getInputStream());
            int exitCode = process.exitValue();
            JSObject result = new JSObject();
            boolean hasRoot = exitCode == 0 && output.matches("(?s)(.*\\n)?\\s*0\\s*(\\n.*)?");
            result.put("hasRoot", hasRoot);
            result.put("exitCode", exitCode);
            result.put("output", output);
            call.resolve(result);
        } catch (Exception e) {
            JSObject result = new JSObject();
            result.put("hasRoot", false);
            result.put("output", e.getMessage() != null ? e.getMessage() : "su binary not found");
            call.resolve(result);
        }
    }

    @PluginMethod
    public void stopDaemon(PluginCall call) {
        try {
            if (wakeLock != null && wakeLock.isHeld()) {
                wakeLock.release();
            }
        } catch (Exception ignored) {}
        wakeLock = null;

        try {
            if (wifiLock != null && wifiLock.isHeld()) {
                wifiLock.release();
            }
        } catch (Exception ignored) {}
        wifiLock = null;

        try {
            ProcessBuilder pb = new ProcessBuilder("su", "-M");
            pb.redirectErrorStream(true);
            Process process = pb.start();
            try (DataOutputStream stdin = new DataOutputStream(process.getOutputStream())) {
                stdin.write("pkill -9 -f castcast || true\npkill -9 -f mediaserver.py || true\npkill -9 -f 'localhost.run|pinggy.io' || true\nexit\n".getBytes(StandardCharsets.UTF_8));
                stdin.flush();
            }
            boolean finished = process.waitFor(ROOT_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                call.reject("Root kill command timed out after " + ROOT_TIMEOUT_SECONDS + "s");
                return;
            }
            JSObject ret = new JSObject();
            ret.put("stopped", true);
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Unable to terminate daemon processes: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void getSharedUrl(PluginCall call) {
        Intent intent = getActivity().getIntent();
        String action = intent.getAction();
        String type = intent.getType();

        JSObject ret = new JSObject();
        if (Intent.ACTION_SEND.equals(action) && type != null && "text/plain".equals(type)) {
            String sharedText = intent.getStringExtra(Intent.EXTRA_TEXT);
            if (sharedText != null) {
                ret.put("url", sharedText);
                // Clear the extra so we don't process it multiple times on resume
                intent.removeExtra(Intent.EXTRA_TEXT);
            }
        }
        call.resolve(ret);
    }

    private RootResult configureTermuxWithRoot() {
        String packageName = getContext().getPackageName();
        String apkPath = getContext().getApplicationInfo().sourceDir;
        String payload =
            "set -e\n" +
            "TERMUX_HOME=/data/data/com.termux/files/home\n" +
            "TERMUX_PROP=$TERMUX_HOME/.termux/termux.properties\n" +
            "if [ ! -d \"$TERMUX_HOME\" ] || [ ! -x " + shellQuote(BASH) + " ]; then\n" +
            "  echo 'Open Termux once and wait for its first launch to finish.'; exit 1\n" +
            "fi\n" +
            "TERMUX_OWNER=$(stat -c '%u:%g' \"$TERMUX_HOME\")\n" +
            "echo 'Installing the daemon bundled in CastCast'\n" +
            "STAGE=$(mktemp -d /data/local/tmp/castcast.XXXXXX)\n" +
            "trap 'rm -rf \"$STAGE\"' EXIT\n" +
            "unzip -qo " + shellQuote(apkPath) + " 'assets/public/daemon/*' -d \"$STAGE\"\n" +
            "mkdir -p " + shellQuote(DAEMON_DIR) + "\n" +
            "cp -R \"$STAGE/assets/public/daemon/.\" " + shellQuote(DAEMON_DIR) + "\n" +
            "chown \"$TERMUX_OWNER\" \"$TERMUX_HOME/CastCast\"\n" +
            "chown -R \"$TERMUX_OWNER\" " + shellQuote(DAEMON_DIR) + "\n" +
            "echo 'Configuring Termux for external commands'\n" +
            "mkdir -p \"$TERMUX_HOME/.termux\"\n" +
            "touch \"$TERMUX_PROP\"\n" +
            "sed '/^[[:space:]]*allow-external-apps[[:space:]]*[:=]/d' \"$TERMUX_PROP\" > \"$STAGE/termux.properties\"\n" +
            "printf '\\nallow-external-apps=true\\n' >> \"$STAGE/termux.properties\"\n" +
            "TEMP_PROP=$(mktemp \"$TERMUX_HOME/.termux/.castcast.XXXXXX\")\n" +
            "cat \"$STAGE/termux.properties\" > \"$TEMP_PROP\"\n" +
            "chown \"$TERMUX_OWNER\" \"$TERMUX_HOME/.termux\" \"$TEMP_PROP\"\n" +
            "chmod 600 \"$TEMP_PROP\"\n" +
            "mv -f \"$TEMP_PROP\" \"$TERMUX_PROP\"\n" +
            "if command -v restorecon >/dev/null 2>&1; then\n" +
            "  restorecon -R " + shellQuote(DAEMON_DIR) + " \"$TERMUX_HOME/.termux\" || true\n" +
            "fi\n" +
            "am broadcast -a com.termux.app.reload_style com.termux >/dev/null 2>&1\n";

        Process process = null;
        try {
            // Merge stderr into stdout so all diagnostics are captured together
            // Use -M (Mount Master) to run in the global mount namespace, otherwise
            // isolated app namespaces will hide Termux's /data/data directory.
            ProcessBuilder pb = new ProcessBuilder("su", "-M");
            pb.redirectErrorStream(true);
            process = pb.start();
            try (DataOutputStream stdin = new DataOutputStream(process.getOutputStream())) {
                stdin.write(payload.getBytes(StandardCharsets.UTF_8));
                stdin.writeBytes("\nexit\n");
                stdin.flush();
            }

            boolean finished = process.waitFor(ROOT_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                return new RootResult(false, -1, "root command timed out", "");
            }

            String output = readStream(process.getInputStream());
            int exitCode = process.exitValue();
            return new RootResult(exitCode == 0, exitCode, output, "");
        } catch (Exception e) {
            return new RootResult(false, -1, "", e.getMessage());
        } finally {
            if (process != null) {
                process.destroy();
            }
        }
    }

    private static String readStream(java.io.InputStream stream) throws java.io.IOException {
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (builder.length() > 0) builder.append('\n');
                builder.append(line);
            }
        }
        return builder.toString();
    }

    private static String shellQuote(String value) {
        return "'" + value.replace("'", "'\\''") + "'";
    }

    private static class RootResult {
        final boolean success;
        final int exitCode;
        final String stdout;
        final String stderr;

        RootResult(boolean success, int exitCode, String stdout, String stderr) {
            this.success = success;
            this.exitCode = exitCode;
            this.stdout = stdout == null ? "" : stdout.trim();
            this.stderr = stderr == null ? "" : stderr.trim();
        }

        String summary() {
            String output = stderr.isEmpty() ? stdout : stderr;
            if (output.length() > 800) {
                output = output.substring(output.length() - 800);
            }
            return "exit=" + exitCode + (output.isEmpty() ? "" : ", output=" + output);
        }
    }
}
