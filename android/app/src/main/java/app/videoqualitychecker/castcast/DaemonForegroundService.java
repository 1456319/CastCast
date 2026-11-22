// synchronization-map: section=android-bridge; role=foreground-daemon-service; boundaries=core-service,config-state,operations-release; doc=docs/SYNCHRONIZATION_MAP.md
package app.videoqualitychecker.castcast;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import androidx.core.app.NotificationCompat;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class DaemonForegroundService extends Service {
    private static final String CHANNEL_ID = "castcast_daemon_channel";
    private static final int NOTIFICATION_ID = 8765;
    public static final String ACTION_START = "app.videoqualitychecker.castcast.START_DAEMON";
    public static final String ACTION_STOP = "app.videoqualitychecker.castcast.STOP_DAEMON";

    private PowerManager.WakeLock wakeLock;
    private WifiManager.MulticastLock multicastLock;
    private WifiManager.WifiLock wifiLock;
    private Thread daemonThread;
    private volatile boolean isRunning = false;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();

        PowerManager powerManager = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (powerManager != null) {
            wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CastCast::DaemonWakeLock");
            wakeLock.setReferenceCounted(false);
        }

        WifiManager wifiManager = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (wifiManager != null) {
            multicastLock = wifiManager.createMulticastLock("CastCast::MulticastLock");
            multicastLock.setReferenceCounted(false);

            int wifiLockMode = WifiManager.WIFI_MODE_FULL_HIGH_PERF;
            wifiLock = wifiManager.createWifiLock(wifiLockMode, "CastCast::WifiLock");
            wifiLock.setReferenceCounted(false);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopDaemon();
            stopSelf();
            return START_NOT_STICKY;
        }

        startForeground(NOTIFICATION_ID, buildNotification("CastCast Media Server is running"));
        startDaemon();
        return START_STICKY;
    }

    private void startDaemon() {
        if (isRunning) return;
        isRunning = true;

        if (wakeLock != null && !wakeLock.isHeld()) {
            wakeLock.acquire();
        }
        if (multicastLock != null && !multicastLock.isHeld()) {
            multicastLock.acquire();
        }
        if (wifiLock != null && !wifiLock.isHeld()) {
            wifiLock.acquire();
        }

        daemonThread = new Thread(() -> {
            try {
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(getApplicationContext()));
                }
                Python py = Python.getInstance();
                PyObject castcastModule = py.getModule("castcast.__main__");
                // Run castcast serve with loopback bind
                castcastModule.callAttr("main_embedded", "serve", "--bind", "127.0.0.1", "--port", "8765");
            } catch (Exception e) {
                e.printStackTrace();
            }
        }, "castcast-chaquopy-thread");
        daemonThread.start();
    }

    private void stopDaemon() {
        isRunning = false;
        try {
            if (Python.isStarted()) {
                Python py = Python.getInstance();
                PyObject apiModule = py.getModule("castcast.api");
                apiModule.callAttr("stop_embedded");
            }
        } catch (Exception ignored) {}

        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }
        if (multicastLock != null && multicastLock.isHeld()) {
            multicastLock.release();
        }
        if (wifiLock != null && wifiLock.isHeld()) {
            wifiLock.release();
        }
    }

    @Override
    public void onDestroy() {
        stopDaemon();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "CastCast Service",
                NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Keeps CastCast local streaming daemon active in background");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }

    private Notification buildNotification(String text) {
        Intent notificationIntent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(
            this, 0, notificationIntent,
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0
        );

        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("CastCast Streaming Engine")
            .setContentText(text)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build();
    }
}
