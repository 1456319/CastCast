// synchronization-map: section=android-bridge; role=setup-result-receiver; boundaries=web-client,operations-release; doc=docs/SYNCHRONIZATION_MAP.md
package app.videoqualitychecker.castcast;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.util.Log;

public class TermuxSetupResultReceiver extends BroadcastReceiver {
    private static final String TAG = "TermuxSetupResult";
    public static final String ACTION_SETUP_RESULT = "app.videoqualitychecker.castcast.TERMUX_SETUP_RESULT";

    private static int lastExitCode = -1;
    private static String lastStdout = "";
    private static String lastStderr = "";
    private static boolean received = false;

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) return;
        Bundle extras = intent.getExtras();
        if (extras != null) {
            lastExitCode = extras.getInt("exitCode", -1);
            lastStdout = extras.getString("stdout", "");
            lastStderr = extras.getString("stderr", "");
            received = true;
            Log.d(TAG, "Termux setup command result: exitCode=" + lastExitCode);
        }
    }

    public static int getLastExitCode() {
        return lastExitCode;
    }

    public static String getLastStdout() {
        return lastStdout;
    }

    public static String getLastStderr() {
        return lastStderr;
    }

    public static boolean hasReceived() {
        return received;
    }

    public static void reset() {
        lastExitCode = -1;
        lastStdout = "";
        lastStderr = "";
        received = false;
    }
}
