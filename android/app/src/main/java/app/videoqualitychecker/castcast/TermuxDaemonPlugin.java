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
import android.content.Intent;
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
    private static final String DAEMON_DIR = "/data/data/com.termux/files/home/VideoQualityCheckerApp/daemon";
    private static final String BOOTSTRAP = DAEMON_DIR + "/termux_bootstrap.sh";

    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;

    @PluginMethod
    public void launch(PluginCall call) {
        PackageManager packageManager = getContext().getPackageManager();
        if (packageManager.getLaunchIntentForPackage(TERMUX_PACKAGE) == null) {
            call.reject("Termux is not installed. Install Termux, copy the project to Download/VideoQualityCheckerApp, then retry.");
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
            result.put("auditLog", "/storage/emulated/0/Download/VideoQualityCheckerApp/Chromecast/.castcast/audit.log");
            result.put("note", "Root configured Termux allow-external-apps and granted RUN_COMMAND. If the daemon stays offline, check that the repo exists at " + DAEMON_DIR + " and inspect the audit log.");
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
        String payload =
            "TERMUX_HOME=/data/data/com.termux/files/home\n" +
            "TERMUX_PROP=$TERMUX_HOME/.termux/termux.properties\n" +
            "\n" +
            "echo '[0/8] extracting bundled daemon code'\n" +
            "mkdir -p /storage/emulated/0/Download/VideoQualityCheckerApp || { echo 'FAIL: create app dir'; exit 1; }\n" +
            "unzip -qo " + shellQuote(apkPath) + " \"assets/public/daemon/*\" -d /data/local/tmp/ || { echo 'FAIL: unzip daemon'; exit 1; }\n" +
            "rm -rf " + shellQuote(DAEMON_DIR) + "/*\n" +
            "cp -rf /data/local/tmp/assets/public/daemon/* " + shellQuote(DAEMON_DIR) + "/ || { echo 'FAIL: copy daemon'; exit 1; }\n" +
            "rm -rf /data/local/tmp/assets\n" +
            "echo '[0/8] creating queue directories'\n" +
            "mkdir -p /storage/emulated/0/Download/VideoQualityCheckerApp/Chromecast/trash || { echo 'FAIL: create trash dir'; exit 1; }\n" +
            "mkdir -p /storage/emulated/0/Download/VideoQualityCheckerApp/Chromecast/.castcast || { echo 'FAIL: create castcast dir'; exit 1; }\n" +
            "\n" +
            "echo '[1/8] checking Termux home'\n" +
            "if [ ! -d \"$TERMUX_HOME\" ]; then echo 'FAIL: Termux home directory not found at '$TERMUX_HOME'. Is Termux installed and opened at least once?'; exit 1; fi\n" +
            "\n" +
            "echo '[2/8] reading Termux UID/GID'\n" +
            "TERMUX_UID=$(stat -c %u \"$TERMUX_HOME\" 2>/dev/null) || { echo 'FAIL: stat -c %u failed; trying ls fallback'; TERMUX_UID=$(ls -ldn \"$TERMUX_HOME\" | awk '{print $3}'); }\n" +
            "TERMUX_GID=$(stat -c %g \"$TERMUX_HOME\" 2>/dev/null) || { echo 'FAIL: stat -c %g failed; trying ls fallback'; TERMUX_GID=$(ls -ldn \"$TERMUX_HOME\" | awk '{print $4}'); }\n" +
            "echo \"  uid=$TERMUX_UID gid=$TERMUX_GID\"\n" +
            "\n" +
            "echo '[3/8] creating .termux dir'\n" +
            "mkdir -p \"$TERMUX_HOME/.termux\" || { echo 'FAIL: mkdir -p .termux'; exit 1; }\n" +
            "\n" +
            "echo '[4/8] ensuring termux.properties exists'\n" +
            "touch \"$TERMUX_PROP\" || { echo 'FAIL: touch termux.properties'; exit 1; }\n" +
            "\n" +
            "echo '[5/8] setting allow-external-apps=true'\n" +
            "grep -q '^allow-external-apps=true$' \"$TERMUX_PROP\" 2>/dev/null || echo 'allow-external-apps=true' >> \"$TERMUX_PROP\" || { echo 'FAIL: write termux.properties'; exit 1; }\n" +
            "\n" +
            "echo '[6/8] fixing ownership and permissions'\n" +
            "chown -R $TERMUX_UID:$TERMUX_GID \"$TERMUX_HOME/.termux\" || { echo 'FAIL: chown .termux'; exit 1; }\n" +
            "chmod 700 \"$TERMUX_HOME/.termux\" || { echo 'FAIL: chmod 700 .termux'; exit 1; }\n" +
            "chmod 600 \"$TERMUX_PROP\" || { echo 'FAIL: chmod 600 termux.properties'; exit 1; }\n" +
            "command -v restorecon >/dev/null 2>&1 && restorecon -R \"$TERMUX_HOME/.termux\" || true\n" +
            "\n" +
            "echo '[7/8] granting Android permissions'\n" +
            "pm grant " + shellQuote(packageName) + " com.termux.permission.RUN_COMMAND 2>&1 || { echo 'FAIL: pm grant RUN_COMMAND'; exit 1; }\n" +
            "appops set com.termux SYSTEM_ALERT_WINDOW allow 2>&1 || { echo 'FAIL: appops SYSTEM_ALERT_WINDOW'; exit 1; }\n" +
            "appops set com.termux MANAGE_EXTERNAL_STORAGE allow 2>&1 || { echo 'FAIL: appops MANAGE_EXTERNAL_STORAGE'; exit 1; }\n" +
            "\n" +
            "echo '[8/8] killing old daemon instance'\n" +
            "pkill -f mediaserver.py || true\n" +
            "\n" +
            "echo '[8/8] reloading Termux config'\n" +
            "am broadcast -a com.termux.app.reload_style com.termux >/dev/null 2>&1 || true\n" +
            "echo 'OK: all steps completed'\n";

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
