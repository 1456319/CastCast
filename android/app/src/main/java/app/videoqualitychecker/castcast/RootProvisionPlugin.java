// synchronization-map: section=android-bridge; role=root-provision-plugin; boundaries=web-client,config-state,operations-release; doc=docs/SYNCHRONIZATION_MAP.md
package app.videoqualitychecker.castcast;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.PowerManager;
import android.provider.Settings;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;
import com.topjohnwu.superuser.Shell;

import java.io.File;

@CapacitorPlugin(name = "RootProvision", permissions = {
    @Permission(alias = "notifications", strings = {Manifest.permission.POST_NOTIFICATIONS}),
    @Permission(alias = "nearby", strings = {Manifest.permission.NEARBY_WIFI_DEVICES}),
    @Permission(alias = "legacyStorage", strings = {Manifest.permission.WRITE_EXTERNAL_STORAGE})
})
public final class RootProvisionPlugin extends Plugin {
    private volatile String rootState = "Unchecked";

    @PluginMethod
    public void checkRequisitions(PluginCall call) {
        call.resolve(report());
    }

    @PluginMethod
    public void checkRoot(PluginCall call) {
        Shell.getShell(shell -> {
            rootState = shell.isRoot() ? "Approved" : "Unavailable or denied";
            call.resolve(report());
        });
    }

    @PluginMethod
    public void requestAccess(PluginCall call) {
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissionForAliases(new String[]{"notifications", "nearby"}, call, "accessResult");
        } else if (Build.VERSION.SDK_INT < 30) {
            requestPermissionForAlias("legacyStorage", call, "accessResult");
        } else {
            call.resolve(report());
        }
    }

    @PermissionCallback
    private void accessResult(PluginCall call) {
        call.resolve(report());
    }

    @PluginMethod
    public void openSettings(PluginCall call) {
        Uri app = Uri.parse("package:" + getContext().getPackageName());
        String target = call.getString("target", "");
        Intent intent;
        switch (target) {
            case "storage":
                intent = Build.VERSION.SDK_INT >= 30
                    ? new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, app)
                    : new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, app);
                break;
            case "battery":
                intent = new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
                break;
            default:
                intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, app);
        }
        try {
            getActivity().startActivity(intent);
            call.resolve();
        } catch (RuntimeException error) {
            call.reject("Android could not open these settings.", error);
        }
    }

    @PluginMethod
    public void startDaemon(PluginCall call) {
        if ("stopping".equals(CastDaemonService.state)) {
            call.reject("The daemon is still stopping. Retry in a moment.");
            return;
        }
        try {
            ContextCompat.startForegroundService(getContext(), new Intent(getContext(), CastDaemonService.class));
            JSObject result = new JSObject();
            result.put("started", true);
            call.resolve(result);
        } catch (RuntimeException error) {
            call.reject("Android could not start the foreground service.", error);
        }
    }

    @PluginMethod
    public void stopDaemon(PluginCall call) {
        JSObject result = new JSObject();
        result.put("stopped", getContext().stopService(new Intent(getContext(), CastDaemonService.class)));
        call.resolve(result);
    }

    @Override
    protected void handleOnNewIntent(Intent intent) {
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            notifyListeners("sharedUrl", new JSObject());
        }
    }

    @PluginMethod
    public void getSharedUrl(PluginCall call) {
        Intent intent = getActivity().getIntent();
        JSObject result = new JSObject();
        if (intent != null && Intent.ACTION_SEND.equals(intent.getAction())) {
            String value = intent.getStringExtra(Intent.EXTRA_TEXT);
            if (value != null) {
                result.put("url", value);
                intent.removeExtra(Intent.EXTRA_TEXT);
            }
        }
        call.resolve(result);
    }

    private JSObject report() {
        File binaries = new File(getContext().getApplicationInfo().nativeLibraryDir);
        boolean tools = new File(binaries, "libffmpeg.so").canExecute()
            && new File(binaries, "libffprobe.so").canExecute();
        boolean notifications = Build.VERSION.SDK_INT < 33 || granted(Manifest.permission.POST_NOTIFICATIONS);
        boolean nearby = Build.VERSION.SDK_INT < 33 || granted(Manifest.permission.NEARBY_WIFI_DEVICES);
        boolean storage = Build.VERSION.SDK_INT >= 30 ? Environment.isExternalStorageManager()
            : granted(Manifest.permission.WRITE_EXTERNAL_STORAGE);
        boolean battery = getContext().getSystemService(PowerManager.class)
            .isIgnoringBatteryOptimizations(getContext().getPackageName());
        JSArray items = new JSArray();
        items.put(item("root", "Superuser", "Approved".equals(rootState), rootState));
        items.put(item("binaries", "FFmpeg and FFprobe", tools, tools ? "Bundled" : "Missing from APK"));
        items.put(item("notifications", "Notifications", notifications, notifications ? "Allowed" : "Optional"));
        items.put(item("nearby", "Nearby devices", nearby, nearby ? "Allowed" : "Optional on this build"));
        items.put(item("storage", "Shared media folder", storage, storage ? "Allowed" : "Using private storage"));
        items.put(item("battery", "Unrestricted battery", battery, battery ? "Allowed" : "Optional"));
        String state = CastDaemonService.READY.get() ? "running" : CastDaemonService.state;
        items.put(item("daemon", "Embedded Python", "running".equals(state),
            CastDaemonService.lastError.isEmpty() ? state : CastDaemonService.lastError));
        JSObject output = new JSObject();
        output.put("items", items);
        output.put("state", state);
        return output;
    }

    private boolean granted(String permission) {
        return getContext().checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    private static JSObject item(String key, String label, boolean ok, String detail) {
        JSObject item = new JSObject();
        item.put("key", key);
        item.put("label", label);
        item.put("ok", ok);
        item.put("detail", detail);
        return item;
    }
}
