package app.videoqualitychecker.castcast;

import android.content.Intent;
import android.content.pm.PackageManager;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

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
            result.put("auditLog", "/storage/emulated/0/Download/Chromecast/.castcast/audit.log");
            result.put("note", "If nothing appears to happen, enable allow-external-apps=true in ~/.termux/termux.properties and grant the Run commands permission when Android prompts.");
            call.resolve(result);
        } catch (SecurityException e) {
            call.reject("Android blocked Termux RUN_COMMAND. Enable allow-external-apps=true in Termux and grant this app the Run commands in Termux permission.", e);
        } catch (Exception e) {
            call.reject("Unable to start Termux RunCommandService: " + e.getMessage(), e);
        }
    }
}
