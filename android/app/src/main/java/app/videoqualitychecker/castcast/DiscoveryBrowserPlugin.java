package app.videoqualitychecker.castcast;

import android.app.Dialog;
import android.os.Handler;
import android.os.Looper;
import android.view.ViewGroup;
import android.view.Window;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.util.Map;

@CapacitorPlugin(name = "DiscoveryBrowser")
public class DiscoveryBrowserPlugin extends Plugin {
    private Dialog browserDialog;
    private WebView webView;

    @PluginMethod
    public void open(PluginCall call) {
        String url = call.getString("url");
        if (url == null) {
            call.reject("Must provide a URL");
            return;
        }

        new Handler(Looper.getMainLooper()).post(() -> {
            browserDialog = new Dialog(getContext(), android.R.style.Theme_NoTitleBar);
            browserDialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
            browserDialog.setCancelable(true);

            webView = new WebView(getContext());
            WebSettings settings = webView.getSettings();
            settings.setJavaScriptEnabled(true);
            settings.setDomStorageEnabled(true);
            settings.setMediaPlaybackRequiresUserGesture(false);

            // This is the core interception engine for Phase 1
            webView.setWebViewClient(new WebViewClient() {
                @Override
                public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                    String reqUrl = request.getUrl().toString();
                    String method = request.getMethod();
                    Map<String, String> headers = request.getRequestHeaders();

                    boolean isManifest = reqUrl.contains(".m3u8") || reqUrl.contains(".mpd");
                    boolean isDrm = reqUrl.toLowerCase().contains("widevine") || reqUrl.toLowerCase().contains("drm");

                    if (isManifest || isDrm) {
                        JSObject eventData = new JSObject();
                        eventData.put("url", reqUrl);
                        eventData.put("method", method);

                        JSObject headersJson = new JSObject();
                        for (Map.Entry<String, String> entry : headers.entrySet()) {
                            headersJson.put(entry.getKey(), entry.getValue());
                        }
                        eventData.put("headers", headersJson);

                        if (isDrm) {
                            eventData.put("type", "drm");
                        } else {
                            eventData.put("type", "manifest");
                        }

                        // Emit event back to Capacitor / React frontend
                        notifyListeners("onStreamDetected", eventData);
                    }

                    return super.shouldInterceptRequest(view, request);
                }
            });

            browserDialog.setContentView(webView, new ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT));

            webView.loadUrl(url);
            browserDialog.show();

            call.resolve();
        });
    }

    @PluginMethod
    public void close(PluginCall call) {
        new Handler(Looper.getMainLooper()).post(() -> {
            if (browserDialog != null) {
                browserDialog.dismiss();
                browserDialog = null;
            }
            if (webView != null) {
                webView.destroy();
                webView = null;
            }
            call.resolve();
        });
    }
}
