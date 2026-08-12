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
    private static final String DAEMON_DIR = "/storage/emulated/0/Download/VideoQualityCheckerApp/daemon";
    private static final String BOOTSTRAP = DAEMON_DIR + "/termux_bootstrap.sh";

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
        intent.putExtra(EXTRA_ARGUMENTS, new String[] { "-lc", "chmod +x '" + BOOTSTRAP + "' && exec '" + BOOTSTRAP + "'" });
        intent.putExtra(EXTRA_WORKDIR, DAEMON_DIR);
        intent.putExtra(EXTRA_BACKGROUND, true);
        intent.putExtra(EXTRA_SESSION_ACTION, "0");

        try {
            getContext().startService(intent);
            JSObject result = new JSObject();
            result.put("started", true);
            result.put("rootConfigured", true);
            result.put("auditLog", "/storage/emulated/0/Download/Chromecast/.castcast/audit.log");
            result.put("note", "Root configured Termux allow-external-apps and granted RUN_COMMAND. If the daemon stays offline, check that the repo exists at " + DAEMON_DIR + " and inspect the audit log.");
            call.resolve(result);
        } catch (SecurityException e) {
            call.reject("Android blocked Termux RUN_COMMAND even after root configuration. Reopen your root manager, grant root to this app, and retry.", e);
        } catch (Exception e) {
            call.reject("Unable to start Termux RunCommandService: " + e.getMessage(), e);
        }
    }

    private RootResult configureTermuxWithRoot() {
        String packageName = getContext().getPackageName();
        String payload = "set -eu\n" +
            "TERMUX_HOME=/data/data/com.termux/files/home\n" +
            "TERMUX_PROP=$TERMUX_HOME/.termux/termux.properties\n" +
            "test -d $TERMUX_HOME\n" +
            "TERMUX_UID=$(stat -c %u $TERMUX_HOME)\n" +
            "TERMUX_GID=$(stat -c %g $TERMUX_HOME)\n" +
            "mkdir -p $TERMUX_HOME/.termux\n" +
            "touch $TERMUX_PROP\n" +
            "grep -q '^allow-external-apps=true$' $TERMUX_PROP 2>/dev/null || echo allow-external-apps=true >> $TERMUX_PROP\n" +
            "chown -R $TERMUX_UID:$TERMUX_GID $TERMUX_HOME/.termux\n" +
            "chmod 700 $TERMUX_HOME/.termux\n" +
            "chmod 600 $TERMUX_PROP\n" +
            "command -v restorecon >/dev/null 2>&1 && restorecon -R $TERMUX_HOME/.termux || true\n" +
            "pm grant " + shellQuote(packageName) + " com.termux.permission.RUN_COMMAND\n" +
            "am broadcast -a com.termux.app.reload_style com.termux >/dev/null 2>&1 || true\n";

        Process process = null;
        try {
            process = Runtime.getRuntime().exec("su");
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

            String stdout = readStream(process.getInputStream());
            String stderr = readStream(process.getErrorStream());
            int exitCode = process.exitValue();
            return new RootResult(exitCode == 0, exitCode, stdout, stderr);
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
            if (output.length() > 240) {
                output = output.substring(0, 240) + "…";
            }
            return "exit=" + exitCode + (output.isEmpty() ? "" : ", output=" + output);
        }
    }
}
