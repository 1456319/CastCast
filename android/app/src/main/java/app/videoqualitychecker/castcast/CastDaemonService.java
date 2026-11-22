// synchronization-map: section=android-bridge; role=embedded-daemon-service; boundaries=core-service,web-client,config-state; doc=docs/SYNCHRONIZATION_MAP.md
package app.videoqualitychecker.castcast;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Environment;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import androidx.core.app.NotificationCompat;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;

public final class CastDaemonService extends Service {
    private static final String CHANNEL = "castcast_daemon";
    private static final int NOTIFICATION_ID = 8765;
    static final AtomicBoolean READY = new AtomicBoolean();
    private static final AtomicBoolean WORKER_ACTIVE = new AtomicBoolean();
    static volatile String state = "stopped";
    static volatile String lastError = "";

    private final AtomicBoolean stopRequested = new AtomicBoolean();
    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;
    private WifiManager.MulticastLock multicastLock;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(
            CHANNEL, "CastCast playback", NotificationManager.IMPORTANCE_LOW
        ));
        PendingIntent openApp = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
            PendingIntent.FLAG_IMMUTABLE);
        startForeground(NOTIFICATION_ID, new NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("CastCast")
            .setContentText("Casting service is active")
            .setContentIntent(openApp)
            .setOngoing(true)
            .build());

        if (!WORKER_ACTIVE.compareAndSet(false, true)) {
            if (stopRequested.get() || "stopping".equals(state)) stopSelf();
            return START_NOT_STICKY;
        }
        state = "starting";
        lastError = "";
        READY.set(false);
        try {
            acquireLocks();
        } catch (RuntimeException error) {
            Log.w("CastCast", "Could not acquire all casting locks", error);
        }

        new Thread(() -> {
            try {
                runDaemon();
            } catch (Exception error) {
                lastError = error.toString();
                Log.e("CastCast", "Embedded daemon failed", error);
            } finally {
                stopRequested.set(true);
                READY.set(false);
                state = "stopped";
                WORKER_ACTIVE.set(false);
                stopSelf();
            }
        }, "CastCast-Python").start();
        return START_NOT_STICKY;
    }

    private void runDaemon() throws IOException {
        File nativeDir = new File(getApplicationInfo().nativeLibraryDir);
        File ffmpeg = new File(nativeDir, "libffmpeg.so");
        File ffprobe = new File(nativeDir, "libffprobe.so");
        if (!ffmpeg.canExecute() || !ffprobe.canExecute()) {
            throw new IOException("This APK is missing its arm64 FFmpeg executables.");
        }
        File config = new File(getFilesDir(), "config");
        File work = new File(getFilesDir(), "work");
        File media = mediaRoot();
        mkdir(config);
        mkdir(work);
        mkdir(new File(media, "trash"));
        if (stopRequested.get()) return;

        if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
        Python python = Python.getInstance();
        PyObject environment = python.getModule("os").get("environ");
        environment.callAttr("__setitem__", "CASTCAST_FFMPEG", ffmpeg.getAbsolutePath());
        environment.callAttr("__setitem__", "CASTCAST_FFPROBE", ffprobe.getAbsolutePath());
        environment.callAttr("__setitem__", "CASTCAST_CONFIG_DIR", config.getAbsolutePath());
        environment.callAttr("__setitem__", "CASTCAST_MEDIA_ROOT", media.getAbsolutePath());
        environment.callAttr("__setitem__", "CASTCAST_WORK_DIR", work.getAbsolutePath());
        environment.callAttr("__setitem__", "CASTCAST_EMBEDDED", "1");
        python.getModule("castcast.android_entry").callAttr("run_blocking",
            media.getAbsolutePath(), work.getAbsolutePath(), config.getAbsolutePath(), stopRequested, READY);
    }

    private File mediaRoot() {
        boolean shared = Build.VERSION.SDK_INT >= 30 ? Environment.isExternalStorageManager()
            : checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
        if (!shared) return new File(getFilesDir(), "media");
        return new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            "CastCast/Chromecast");
    }

    private static void mkdir(File directory) throws IOException {
        if ((!directory.isDirectory() && !directory.mkdirs()) || !directory.canWrite()) {
            throw new IOException("Cannot write to " + directory);
        }
    }

    private void acquireLocks() {
        PowerManager power = getSystemService(PowerManager.class);
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CastCast:Playback");
        wakeLock.acquire();
        WifiManager wifi = getApplicationContext().getSystemService(WifiManager.class);
        if (wifi != null) {
            multicastLock = wifi.createMulticastLock("CastCast:Discovery");
            multicastLock.acquire();
            wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "CastCast:Playback");
            wifiLock.acquire();
        }
    }

    @Override
    public void onDestroy() {
        if (!stopRequested.getAndSet(true)) state = "stopping";
        if (multicastLock != null && multicastLock.isHeld()) multicastLock.release();
        if (wifiLock != null && wifiLock.isHeld()) wifiLock.release();
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        super.onDestroy();
    }
}
