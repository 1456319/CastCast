package app.videoqualitychecker.castcast;

import com.getcapacitor.BridgeActivity;

import android.content.Intent;
import android.os.Bundle;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(TermuxDaemonPlugin.class);
        registerPlugin(DiscoveryBrowserPlugin.class);
        super.onCreate(savedInstanceState);
    }

    @Override
    public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
    }
}
