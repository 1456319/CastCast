// synchronization-map: section=android-bridge; role=termux-setup-result; boundaries=config-state,web-client; doc=docs/SYNCHRONIZATION_MAP.md
package app.videoqualitychecker.castcast;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;

/** Receives the one-shot result for a CastCast bootstrap, even after activity recreation. */
public class TermuxSetupResultReceiver extends BroadcastReceiver {
    static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences("castcastSetup", Context.MODE_PRIVATE);
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        SharedPreferences prefs = preferences(context);
        String attempt = prefs.getString("attemptId", "");
        if (intent.getData() == null || !attempt.equals(intent.getData().getSchemeSpecificPart())) return;

        Bundle result = intent.getBundleExtra("result");
        int exitCode = result == null ? -1 : result.getInt("exitCode", -1);
        int errorCode = result == null ? -1 : result.getInt("err", 0);
        boolean success = exitCode == 0 && errorCode == 0;
        String detail = "Termux did not return a setup result.";
        if (result != null) {
            String stdout = result.getString("stdout", "").trim();
            String stderr = result.getString("stderr", "").trim();
            String error = result.getString("errmsg", "").trim();
            detail = !error.isEmpty() ? error : (stdout + "\n" + stderr).trim();
            if (detail.isEmpty() && !success) detail = "Termux returned exit code " + exitCode + ".";
            if (detail.length() > 2500) detail = detail.substring(detail.length() - 2500);
        }
        prefs.edit().putString("phase", success ? "complete" : "failed").putString("detail", detail).apply();
    }
}
