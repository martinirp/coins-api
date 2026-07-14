package com.coinsapi.solver;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import fi.iki.elonen.NanoHTTPD;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

public class MainActivity extends Activity {
    private WebView webView;
    private WebServer server;
    private String currentCookies = "";

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        
        // Spoofing the User-Agent to look like a real mobile Chrome, not a WebView
        String defaultUA = settings.getUserAgentString();
        String fakeUA = defaultUA.replace("; wv", "").replace("Version/4.0 ", "");
        settings.setUserAgentString(fakeUA);
        
        CookieManager.getInstance().setAcceptCookie(true);
        if (android.os.Build.VERSION.SDK_INT >= 21) {
            CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);
        }

        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
            }
        });

        webView.loadUrl("https://www.tibia.com/account/?subtopic=accountmanagement");

        server = new WebServer(8899);
        try {
            server.start();
            Toast.makeText(this, "Solver rodando na porta 8899", Toast.LENGTH_LONG).show();
        } catch (IOException e) {
            e.printStackTrace();
            Toast.makeText(this, "Erro na porta 8899", Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (server != null) {
            server.stop();
        }
    }

    private class WebServer extends NanoHTTPD {
        public WebServer(int port) {
            super(port);
        }

        @Override
        public Response serve(IHTTPSession session) {
            String uri = session.getUri();
            
            if ("/solve".equals(uri)) {
                String cookies = CookieManager.getInstance().getCookie("https://www.tibia.com");
                if (cookies == null) cookies = "";
                return newFixedLengthResponse(Response.Status.OK, "application/json", "{\"cookies\": \"" + cookies + "\"}");
            }
            
            if ("/navigate".equals(uri)) {
                final String url = session.getParameters().get("url").get(0);
                runOnUiThread(() -> webView.loadUrl(url));
                return newFixedLengthResponse("OK");
            }
            
            if ("/inject".equals(uri) && Method.POST.equals(session.getMethod())) {
                try {
                    Map<String, String> files = new HashMap<>();
                    session.parseBody(files);
                    final String js = session.getParameters().get("js").get(0);
                    runOnUiThread(() -> webView.evaluateJavascript(js, null));
                    return newFixedLengthResponse("OK");
                } catch (Exception e) {
                    return newFixedLengthResponse("Error");
                }
            }
            
            return newFixedLengthResponse("API do Solver Ativa");
        }
    }
}
