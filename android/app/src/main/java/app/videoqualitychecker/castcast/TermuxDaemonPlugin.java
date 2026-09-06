// synchronization-map: section=android-bridge; role=termux-launch-plugin; boundaries=web-client,config-state,operations-release; doc=docs/SYNCHRONIZATION_MAP.md
package app.videoqualitychecker.castcast;

import android.content.Intent;
import android.content.pm.PackageManager;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.BufferedReader;
import java.io.DataOutputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;
import android.os.PowerManager;
import android.net.wifi.WifiManager;
import android.content.Context;
import android.net.Uri;
import android.provider.Settings;

@CapacitorPlugin(name = "TermuxDaemon")
public class TermuxDaemonPlugin extends Plugin {
    private static final String TERMUX_PACKAGE = "com.termux";
    private static final String RUN_COMMAND_SERVICE = "com.termux.app.RunCommandService";
    private static final String ACTION_RUN_COMMAND = "com.termux.RUN_COMMAND";
    private static final String EXTRA_COMMAND_PATH = "com.termux.RUN_COMMAND_PATH";
    private static final String EXTRA_ARGUMENTS = "com.termux.RUN_COMMAND_ARGUMENTS";
    private static final String EXTRA_WORKDIR = "com.termux.RUN_COMMAND_WORKDIR";
    private static final String EXTRA_BACKGROUND = "com.termux.RUN_COMMAND_BACKGROUND";
    private static final String EXTRA_SESSION_ACTION = "com.termux.RUN_COMMAND_SESSION_ACTION";
    private static final int ROOT_TIMEOUT_SECONDS = 15;

    private static final String BASH = "/data/data/com.termux/files/usr/bin/bash";
    private String daemonDir;

    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;

    @PluginMethod
    public void launch(PluginCall call) {
        PackageManager packageManager = getContext().getPackageManager();
        if (packageManager.getLaunchIntentForPackage(TERMUX_PACKAGE) == null) {
            call.reject("Termux is not installed. Install Termux, copy the project to Download/CastCast, then retry.");
            return;
        }

        try {
            // Each APK installation owns an immutable daemon bundle. Never
            // overwrite code that an existing Termux process is importing.
            long installedAt = packageManager.getPackageInfo(getContext().getPackageName(), 0).lastUpdateTime;
            daemonDir = "/data/data/com.termux/files/home/CastCast/releases/" + installedAt + "/daemon";
        } catch (PackageManager.NameNotFoundException e) {
            call.reject("Cannot identify the installed APK bundle", e);
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
        intent.putExtra(EXTRA_ARGUMENTS, new String[] { "-lc", "exec bash " + shellQuote(daemonDir + "/termux_bootstrap.sh") });
        intent.putExtra(EXTRA_WORKDIR, daemonDir);
        intent.putExtra(EXTRA_BACKGROUND, true);
        intent.putExtra(EXTRA_SESSION_ACTION, "0");

        try {
            PowerManager pm = (PowerManager) getContext().getSystemService(Context.POWER_SERVICE);
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
                if (!pm.isIgnoringBatteryOptimizations(getContext().getPackageName())) {
                    Intent intentBattery = new Intent();
                    intentBattery.setAction(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                    intentBattery.setData(Uri.parse("package:" + getContext().getPackageName()));
                    getContext().startActivity(intentBattery);
                }
            }

            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
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
            result.put("note", "Root configured Termux allow-external-apps and granted RUN_COMMAND. If the daemon stays offline, check that the repo exists at " + daemonDir + " and inspect the audit log.");
            call.resolve(result);
        } catch (SecurityException e) {
            call.reject("Android blocked Termux RUN_COMMAND even after root configuration. Reopen your root manager, grant root to this app, and retry.", e);
        } catch (Exception e) {
            call.reject("Unable to start Termux RunCommandService: " + e.getMessage(), e);
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
        // Each step echoes progress to stdout; on failure, the step prints the
        // error and exits so the user sees exactly what went wrong.
        String apkPath = getContext().getApplicationInfo().sourceDir;
        String payload = "BUNDLE_DIR=" + shellQuote(daemonDir) + "\n"
            + "APK_PATH=" + shellQuote(apkPath) + "\n"
            + "APP_PACKAGE=" + shellQuote(packageName) + "\n"
            + String.join("\n",
                "set -eu",
                "TERMUX_HOME=/data/data/com.termux/files/home",
                "if [ ! -d \"$TERMUX_HOME\" ]; then echo \"Open Termux once before installing the daemon\"; exit 1; fi",
                "TERMUX_UID=$(stat -c %u \"$TERMUX_HOME\")",
                "TERMUX_GID=$(stat -c %g \"$TERMUX_HOME\")",
                "case \"$TERMUX_UID:$TERMUX_GID\" in *[!0-9:]*|0:*|:*) echo \"Invalid Termux ownership\"; exit 1;; esac",
                "TERMUX_PROP=\"$TERMUX_HOME/.termux/termux.properties\"",
                "mkdir -p \"$TERMUX_HOME/CastCast/releases\"",
                "if [ ! -f \"$BUNDLE_DIR/termux_bootstrap.sh\" ]; then",
                "  STAGE=$(mktemp -d \"$TERMUX_HOME/CastCast/releases/.stage.XXXXXX\")",
                "  trap 'rm -rf \"$STAGE\"' EXIT",
                "  unzip -qo \"$APK_PATH\" \"assets/public/daemon/*\" -d \"$STAGE\"",
                "  test -f \"$STAGE/assets/public/daemon/castcast/__main__.py\"",
                "  test -f \"$STAGE/assets/public/daemon/termux_bootstrap.sh\"",
                "  chown -R \"$TERMUX_UID:$TERMUX_GID\" \"$STAGE/assets/public\"",
                "  RELEASE_DIR=${BUNDLE_DIR%/daemon}",
                "  if [ ! -d \"$RELEASE_DIR\" ]; then mv \"$STAGE/assets/public\" \"$RELEASE_DIR\"; fi",
                "fi",
                "mkdir -p /storage/emulated/0/Download/CastCast/Chromecast/trash /storage/emulated/0/Download/CastCast/Chromecast/.castcast",
                "mkdir -p \"$TERMUX_HOME/.termux\"",
                "touch \"$TERMUX_PROP\"",
                "if ! grep -q \"^allow-external-apps=true$\" \"$TERMUX_PROP\"; then echo \"allow-external-apps=true\" >> \"$TERMUX_PROP\"; fi",
                "chown \"$TERMUX_UID:$TERMUX_GID\" \"$TERMUX_HOME/.termux\" \"$TERMUX_PROP\" \"$TERMUX_HOME/CastCast\" \"$TERMUX_HOME/CastCast/releases\"",
                "chmod 700 \"$TERMUX_HOME/.termux\"",
                "chmod 600 \"$TERMUX_PROP\"",
                "if command -v restorecon >/dev/null 2>&1; then restorecon -R \"$TERMUX_HOME/.termux\" \"$BUNDLE_DIR\" || true; fi",
                "pm grant \"$APP_PACKAGE\" com.termux.permission.RUN_COMMAND",
                "appops set com.termux MANAGE_EXTERNAL_STORAGE allow",
                "am broadcast -a com.termux.app.reload_style com.termux >/dev/null 2>&1 || true",
                "echo \"OK: bundled daemon ready\""
            ) + "\n";

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
