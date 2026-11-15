package app.chatclumer.android.web

import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import androidx.annotation.RequiresApi
import android.os.Message
import android.webkit.GeolocationPermissions
import android.webkit.PermissionRequest
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.net.http.SslError
import app.chatclumer.android.link.UrlPolicy
import app.chatclumer.android.net.PageProblem
import app.chatclumer.android.net.RateLimit
import app.chatclumer.android.net.WebErrors

interface WebHost {
    fun baseUrl(): String
    fun acceptCallbacks(): Boolean
    fun onPageFinished(url: String)
    fun onProblem(problem: PageProblem, retryAfterSeconds: Long)
    fun openExternal(url: String)
    fun onFileChooser(callback: ValueCallback<Array<Uri>>?, params: WebChromeClient.FileChooserParams?): Boolean
}

class ChatWebViewClient(private val host: WebHost) : WebViewClient() {
    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
        val decision = UrlPolicy.decide(host.baseUrl(), request.url.toString(), request.hasGesture())
        return when (decision) {
            UrlPolicy.Decision.ALLOW -> false
            UrlPolicy.Decision.EXTERNAL -> {
                host.openExternal(request.url.toString())
                true
            }
            UrlPolicy.Decision.BLOCK -> true
        }
    }

    override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
        // A new main-frame navigation clears the failure flag from the previous one.
    }

    override fun onPageFinished(view: WebView, url: String) {
        if (!host.acceptCallbacks()) return
        host.onPageFinished(url)
    }

    override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
        if (!request.isForMainFrame || !host.acceptCallbacks()) return
        host.onProblem(PageProblem.OFFLINE, 0)
    }

    override fun onReceivedHttpError(
        view: WebView,
        request: WebResourceRequest,
        errorResponse: WebResourceResponse,
    ) {
        if (!request.isForMainFrame || !host.acceptCallbacks()) return
        val problem = WebErrors.fromHttpStatus(errorResponse.statusCode) ?: return
        val wait = if (problem == PageProblem.RATE_LIMITED) {
            RateLimit.holdSeconds(RateLimit.headerValue(errorResponse.responseHeaders))
        } else {
            0L
        }
        host.onProblem(problem, wait)
    }

    override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
        handler.cancel()
        if (host.acceptCallbacks()) host.onProblem(PageProblem.UNAVAILABLE, 0)
    }

    @RequiresApi(Build.VERSION_CODES.O)
    override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
        if (host.acceptCallbacks()) host.onProblem(PageProblem.OFFLINE, 0)
        return true
    }
}

class ChatChromeClient(private val host: WebHost) : WebChromeClient() {
    override fun onShowFileChooser(
        webView: WebView?,
        filePathCallback: ValueCallback<Array<Uri>>?,
        fileChooserParams: FileChooserParams?,
    ): Boolean = host.onFileChooser(filePathCallback, fileChooserParams)

    override fun onGeolocationPermissionsShowPrompt(origin: String?, callback: GeolocationPermissions.Callback?) {
        callback?.invoke(origin, false, false)
    }

    override fun onPermissionRequest(request: PermissionRequest?) {
        request?.deny()
    }

    override fun onCreateWindow(view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message): Boolean {
        val transport = resultMsg.obj as? WebView.WebViewTransport ?: return false
        val popup = WebView(view.context)
        popup.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(popupView: WebView, request: WebResourceRequest): Boolean {
                val decision = UrlPolicy.decide(host.baseUrl(), request.url.toString(), isUserGesture)
                when (decision) {
                    UrlPolicy.Decision.ALLOW -> view.loadUrl(request.url.toString())
                    UrlPolicy.Decision.EXTERNAL -> host.openExternal(request.url.toString())
                    UrlPolicy.Decision.BLOCK -> Unit
                }
                popupView.destroy()
                return true
            }
        }
        transport.webView = popup
        resultMsg.sendToTarget()
        return true
    }
}
