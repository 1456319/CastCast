// synchronization-map: section=android-bridge; role=root-provision-plugin; boundaries=web-client,config-state,operations-release; doc=docs/SYNCHRONIZATION_MAP.md
package app.videoqualitychecker.castcast;

import android.Manifest;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.OpenableColumns;
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
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentLinkedQueue;

@CapacitorPlugin(name = "RootProvision", permissions = {
    @Permission(alias = "notifications", strings = {Manifest.permission.POST_NOTIFICATIONS}),
    @Permission(alias = "nearby", strings = {Manifest.permission.NEARBY_WIFI_DEVICES}),
    @Permission(alias = "legacyStorage", strings = {Manifest.permission.WRITE_EXTERNAL_STORAGE})
})
public final class RootProvisionPlugin extends Plugin {
    private volatile String rootState = "Unchecked";
    private final ConcurrentLinkedQueue<Intent> pendingShares = new ConcurrentLinkedQueue<>();
    private Intent lastCapturedShare;

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
    public void load() {
        if (getActivity() != null) captureShare(getActivity().getIntent());
    }

    @Override
    protected void handleOnNewIntent(Intent intent) {
        super.handleOnNewIntent(intent);
        if (captureShare(intent)) notifyListeners("sharedUrl", new JSObject());
    }

    private synchronized boolean captureShare(Intent intent) {
        if (intent == null || intent == lastCapturedShare) return false;
        String action = intent.getAction();
        if (!Intent.ACTION_SEND.equals(action) && !Intent.ACTION_SEND_MULTIPLE.equals(action)
            && !Intent.ACTION_VIEW.equals(action)) return false;
        lastCapturedShare = intent;
        pendingShares.add(new Intent(intent));
        return true;
    }

    @PluginMethod
    public void getSharedUrl(PluginCall call) {
        Intent intent = pendingShares.poll();
        JSObject result = new JSObject();
        if (intent == null) {
            call.resolve(result);
            return;
        }

        JSArray files = new JSArray();
        JSArray errors = new JSArray();
        try {
            Set<Uri> uris = sharedUris(intent);
            int index = 0;
            for (Uri uri : uris) {
                String name = "File " + ++index;
                try {
                    name = displayName(uri);
                    files.put(importFile(uri, name));
                } catch (IOException | RuntimeException error) {
                    errors.put(name + ": " + error.getMessage());
                }
            }

            if (uris.isEmpty() && Intent.ACTION_SEND.equals(intent.getAction())) {
                CharSequence text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
                if (text != null && !text.toString().trim().isEmpty()) {
                    result.put("url", text.toString().trim());
                    result.put("isFile", false);
                }
            }
            boolean batch = Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction()) || uris.size() > 1;
            result.put("batch", batch);
            if (!batch && files.length() == 1) {
                JSObject file = (JSObject) files.opt(0);
                result.put("url", file.getString("url"));
                result.put("fileName", file.getString("fileName"));
                result.put("isFile", true);
            }
        } catch (RuntimeException error) {
            errors.put("Could not read the share: " + error.getMessage());
        }
        result.put("files", files);
        result.put("errors", errors);
        result.put("morePending", !pendingShares.isEmpty());
        call.resolve(result);
    }

    private static Set<Uri> sharedUris(Intent intent) {
        Set<Uri> uris = new LinkedHashSet<>();
        Bundle extras = intent.getExtras();
        Object streams = extras == null ? null : extras.get(Intent.EXTRA_STREAM);
        if (streams instanceof Uri) {
            uris.add((Uri) streams);
        } else if (streams instanceof List<?>) {
            for (Object stream : (List<?>) streams) {
                if (stream instanceof Uri) uris.add((Uri) stream);
            }
        }
        if (intent.getData() != null) uris.add(intent.getData());
        ClipData clip = intent.getClipData();
        if (clip != null) {
            for (int index = 0; index < clip.getItemCount(); index++) {
                Uri uri = clip.getItemAt(index).getUri();
                if (uri != null) uris.add(uri);
            }
        }
        return uris;
    }

    private String displayName(Uri uri) {
        String name = null;
        if ("content".equalsIgnoreCase(uri.getScheme())) {
            try (Cursor cursor = getContext().getContentResolver().query(
                    uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
                if (cursor != null && cursor.moveToFirst()) {
                    int column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                    if (column >= 0) name = cursor.getString(column);
                }
            } catch (RuntimeException ignored) {
                // Some providers permit reading data but omit metadata.
            }
        }
        if (name == null || name.trim().isEmpty()) name = uri.getLastPathSegment();
        name = name == null ? "" : new File(name).getName().trim();
        if (name.isEmpty() || ".".equals(name) || "..".equals(name)) return "shared_file";
        return name.startsWith(".") ? "shared" + name : name;
    }

    private JSObject importFile(Uri uri, String name) throws IOException {
        File root = CastDaemonService.mediaDirectory(getContext()).getCanonicalFile();
        File inbox = new File(root, "inbox");
        if (!inbox.equals(inbox.getCanonicalFile()) ||
            (!inbox.isDirectory() && !inbox.mkdirs()) || !inbox.canWrite()) {
            throw new IOException("Cannot write to " + inbox);
        }

        File folder = Files.createTempDirectory(inbox.toPath(), "share-").toFile();
        File destination = new File(folder, name);
        File temporary = null;
        boolean complete = false;
        try {
            temporary = File.createTempFile(".pending-", ".part", folder);
            try (InputStream input = getContext().getContentResolver().openInputStream(uri)) {
                if (input == null) throw new IOException("The source app did not provide a readable file.");
                try (OutputStream output = new FileOutputStream(temporary)) {
                    byte[] buffer = new byte[65536];
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        output.write(buffer, 0, count);
                    }
                }
            }
            if (!temporary.renameTo(destination)) throw new IOException("Could not finish importing the file.");
            complete = true;
            JSObject file = new JSObject();
            file.put("url", destination.getAbsolutePath());
            file.put("fileName", name);
            return file;
        } finally {
            if (!complete) {
                if (temporary != null) temporary.delete();
                folder.delete();
            }
        }
    }

    private JSObject report() {
        File binaries = new File(getContext().getApplicationInfo().nativeLibraryDir);
        boolean tools = new File(binaries, "libffmpeg.so").canExecute()
            && new File(binaries, "libffprobe.so").canExecute();
        boolean notifications = Build.VERSION.SDK_INT < 33 || granted(Manifest.permission.POST_NOTIFICATIONS);
        boolean nearby = Build.VERSION.SDK_INT < 33 || granted(Manifest.permission.NEARBY_WIFI_DEVICES);
        boolean storage = CastDaemonService.hasSharedStorage(getContext());
        File configuredDirectory = CastDaemonService.configuredMediaDirectory(getContext());
        File mediaDirectory = CastDaemonService.mediaDirectory(getContext());
        boolean battery = getContext().getSystemService(PowerManager.class)
            .isIgnoringBatteryOptimizations(getContext().getPackageName());
        JSArray items = new JSArray();
        items.put(item("root", "Superuser", "Approved".equals(rootState), rootState));
        items.put(item("binaries", "FFmpeg and FFprobe", tools, tools ? "Bundled" : "Missing from APK"));
        items.put(item("notifications", "Notifications", notifications, notifications ? "Allowed" : "Optional"));
        items.put(item("nearby", "Nearby devices", nearby, nearby ? "Allowed" : "Optional on this build"));
        items.put(item("storage", "Library folder", CastDaemonService.READY.get() && mediaDirectory.canWrite(),
            mediaDirectory.getAbsolutePath()));
        String storageDetail = storage ? "Allowed" : "Using private storage";
        if (!configuredDirectory.equals(mediaDirectory)) storageDetail += ". Restart the daemon to apply the change.";
        items.put(item("storage", "Shared storage", storage, storageDetail));
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
