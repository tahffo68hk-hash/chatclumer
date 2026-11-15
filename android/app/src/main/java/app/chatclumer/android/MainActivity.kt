package app.chatclumer.android

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import app.chatclumer.android.data.ComputerStore
import app.chatclumer.android.data.MemoryBucket
import app.chatclumer.android.data.SavedComputer
import app.chatclumer.android.data.SecureBuckets
import app.chatclumer.android.databinding.ActivityMainBinding
import app.chatclumer.android.databinding.ItemComputerBinding
import app.chatclumer.android.link.PairLinks
import app.chatclumer.android.link.TokenPolicy
import app.chatclumer.android.link.UrlPolicy
import app.chatclumer.android.link.displayVersion
import app.chatclumer.android.link.maskToken
import app.chatclumer.android.net.PageProblem
import app.chatclumer.android.net.Probe
import app.chatclumer.android.net.RateLimit
import app.chatclumer.android.net.ServerClient
import app.chatclumer.android.web.ChatChromeClient
import app.chatclumer.android.web.ChatWebViewClient
import app.chatclumer.android.web.WebHost
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.BarcodeResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity(), WebHost {
    private lateinit var binding: ActivityMainBinding
    private lateinit var store: ComputerStore
    private val server = ServerClient()
    private val clock = Handler(Looper.getMainLooper())

    private var screen = Screen.CONNECT
    private var errorKind = ErrorKind.OFFLINE
    private var webView: WebView? = null
    private var acceptWeb = false
    private var mainFrameFailed = false
    private var pendingClearHistory = false
    private var busy = false
    private var connectGen = 0
    private var scanArmed = false
    private var cameraRunning = false
    private var torchOn = false
    private var storagePersistent = true
    private var activeId: String? = null
    private var attemptBase: String? = null
    private var attemptToken: String? = null
    private var attemptVersion: String? = null
    private var rateOrigin: String? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    private val cameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) openScanner() else showCameraDenied()
    }

    private val fileChooser = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val callback = fileCallback
        fileCallback = null
        callback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data))
    }

    private val barcodeCallback = object : BarcodeCallback {
        override fun barcodeResult(result: BarcodeResult) {
            if (!scanArmed) return
            val text = result.text ?: return
            scanArmed = false
            stopCamera()
            onScan(text)
        }
    }

    private val rateTick = object : Runnable {
        override fun run() {
            if (screen != Screen.ERROR || errorKind != ErrorKind.RATE) return
            val origin = rateOrigin ?: return
            val left = store.remainingHoldSeconds(origin, System.currentTimeMillis())
            binding.errorWait.text = getString(R.string.rate_limit_remaining, RateLimit.formatWait(left))
            binding.retryButton.isEnabled = left <= 0L
            binding.retryButton.text = if (left > 0L) getString(R.string.rate_limit_button) else getString(R.string.retry)
            if (left > 0L) clock.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }
        store = openStore()
        binding.barcodeScanner.decodeContinuous(barcodeCallback)
        binding.barcodeScanner.setStatusText(getString(R.string.scan_status))
        binding.scanButton.setOnClickListener { startScan() }
        binding.manualButton.setOnClickListener { showScreen(Screen.MANUAL) }
        binding.manualCancel.setOnClickListener { showScreen(Screen.CONNECT) }
        binding.manualConnect.setOnClickListener {
            connect(
                binding.manualAddress.text?.toString().orEmpty(),
                binding.manualToken.text?.toString().orEmpty(),
                fromUserInput = true,
            )
        }
        binding.manualToken.setOnEditorActionListener { _, _, _ ->
            binding.manualConnect.performClick()
            true
        }
        binding.scannerCancel.setOnClickListener { closeScanner() }
        binding.torchButton.setOnClickListener { toggleTorch() }
        binding.toolbar.inflateMenu(R.menu.menu_web)
        binding.toolbar.setNavigationOnClickListener { showScreen(Screen.CONNECT) }
        binding.toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_reconnect -> {
                    retryConnection()
                    true
                }
                R.id.action_switch -> {
                    showScreen(Screen.CONNECT)
                    true
                }
                else -> false
            }
        }
        binding.swipe.setColorSchemeColors(ContextCompat.getColor(this, R.color.seed))
        binding.swipe.setOnChildScrollUpCallback { _, _ ->
            (webView?.scrollY ?: 0) > 0
        }
        binding.swipe.setOnRefreshListener { refreshWeb() }
        binding.retryButton.setOnClickListener { retryConnection() }
        binding.rescanButton.setOnClickListener { startScan() }
        binding.errorBack.setOnClickListener { showScreen(Screen.CONNECT) }
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when (screen) {
                    Screen.SCAN -> closeScanner()
                    Screen.MANUAL, Screen.ERROR -> showScreen(Screen.CONNECT)
                    Screen.WEB -> {
                        val web = webView
                        if (web != null && web.canGoBack()) web.goBack() else showScreen(Screen.CONNECT)
                    }
                    Screen.CONNECT -> {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            }
        })
        if (!storagePersistent) {
            toast(R.string.secure_storage_failed)
        }
        if (savedInstanceState != null) {
            restore(savedInstanceState)
        } else {
            showScreen(Screen.CONNECT)
            handleIntent(intent)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        if (screen == Screen.SCAN) startCamera()
    }

    override fun onPause() {
        stopCamera()
        CookieManager.getInstance().flush()
        super.onPause()
    }

    override fun onDestroy() {
        clock.removeCallbacks(rateTick)
        fileCallback?.onReceiveValue(null)
        fileCallback = null
        discardWeb()
        super.onDestroy()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_SCREEN, screen.name)
        outState.putString(STATE_ERROR, errorKind.name)
        outState.putString(STATE_ACTIVE, activeId)
        outState.putString(STATE_BASE, attemptBase)
        val web = webView
        val url = web?.url
        if (screen == Screen.WEB && web != null && (url == null || !UrlPolicy.containsCredentialQuery(url))) {
            web.saveState(outState)
            outState.putBoolean(STATE_WEB, true)
        }
    }

    override fun baseUrl(): String = attemptBase ?: "about:blank"

    override fun acceptCallbacks(): Boolean = acceptWeb

    override fun onPageFinished(url: String) {
        if (!acceptWeb) return
        binding.swipe.isRefreshing = false
        // Defer so an HTTP error reported in the same navigation can cancel this.
        webView?.post {
            if (!acceptWeb || mainFrameFailed) return@post
            if (UrlPolicy.containsCredentialQuery(url)) {
                webView?.loadUrl(UrlPolicy.rootUrl(baseUrl()))
                return@post
            }
            if (pendingClearHistory) {
                pendingClearHistory = false
                webView?.clearHistory()
            }
            val base = attemptBase ?: return@post
            val token = attemptToken ?: return@post
            if (!TokenPolicy.accept(token)) return@post
            val saved = store.upsert(base, token, attemptVersion.orEmpty())
            activeId = saved.id
            binding.toolbar.title = saved.name
            val host = UrlPolicy.hostLabel(saved.baseUrl)
            binding.toolbar.subtitle = if (host == saved.name) null else host
            binding.manualToken.text?.clear()
            Log.i(TAG, "page-ready")
        }
    }

    override fun onProblem(problem: PageProblem, retryAfterSeconds: Long) {
        if (!acceptWeb) return
        acceptWeb = false
        mainFrameFailed = true
        binding.swipe.isRefreshing = false
        val kind = when (problem) {
            PageProblem.UNAUTHORIZED -> ErrorKind.AUTH
            PageProblem.RATE_LIMITED -> ErrorKind.RATE
            PageProblem.UNAVAILABLE -> ErrorKind.HTTP
            PageProblem.OFFLINE -> ErrorKind.OFFLINE
        }
        if (kind == ErrorKind.RATE) {
            val origin = attemptBase?.let { UrlPolicy.origin(it) }
            if (origin != null) {
                val left = store.rememberHold(origin, retryAfterSeconds, System.currentTimeMillis())
                Log.i(TAG, "rate-limited")
                showRate(origin, left)
            } else {
                showProblem(ErrorKind.HTTP)
            }
        } else {
            if (kind == ErrorKind.OFFLINE || kind == ErrorKind.HTTP || kind == ErrorKind.AUTH) {
                Log.i(TAG, "page-error")
            }
            showProblem(kind)
        }
        binding.root.post { discardWeb() }
    }

    override fun openExternal(url: String) {
        if (UrlPolicy.containsCredentialQuery(url)) return
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (_: ActivityNotFoundException) {
            toast(R.string.external_failed)
        }
    }

    override fun onFileChooser(
        callback: ValueCallback<Array<Uri>>?,
        params: WebChromeClient.FileChooserParams?,
    ): Boolean {
        fileCallback?.onReceiveValue(null)
        fileCallback = callback
        val intent = try {
            params?.createIntent()
        } catch (_: Exception) {
            null
        } ?: Intent(Intent.ACTION_GET_CONTENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        }
        return try {
            fileChooser.launch(intent)
            true
        } catch (_: ActivityNotFoundException) {
            fileCallback = null
            toast(R.string.file_chooser_failed)
            false
        }
    }

    private fun openStore(): ComputerStore {
        return try {
            ComputerStore(SecureBuckets.create(applicationContext))
        } catch (_: Exception) {
            storagePersistent = false
            ComputerStore(MemoryBucket())
        }
    }

    private fun restore(state: Bundle) {
        activeId = state.getString(STATE_ACTIVE)
        attemptBase = state.getString(STATE_BASE)
        val saved = activeId?.let { store.findById(it) }
        if (saved != null) {
            attemptBase = saved.baseUrl
            attemptToken = saved.token
            attemptVersion = saved.serverVersion
        }
        val restoredScreen = runCatching { Screen.valueOf(state.getString(STATE_SCREEN) ?: "") }.getOrDefault(Screen.CONNECT)
        val restoredError = runCatching { ErrorKind.valueOf(state.getString(STATE_ERROR) ?: "") }.getOrDefault(ErrorKind.OFFLINE)
        if (restoredScreen == Screen.WEB && state.getBoolean(STATE_WEB)) {
            val web = ensureWeb()
            web.restoreState(state)
            val url = web.url
            if (url != null && UrlPolicy.containsCredentialQuery(url)) {
                discardWeb()
                showScreen(Screen.CONNECT)
            } else {
                showScreen(Screen.WEB)
                binding.toolbar.title = saved?.name ?: UrlPolicy.hostLabel(attemptBase ?: "")
                binding.toolbar.subtitle = attemptBase?.let { UrlPolicy.hostLabel(it) }
            }
        } else if (restoredScreen == Screen.ERROR && restoredError == ErrorKind.RATE) {
            val origin = attemptBase?.let { UrlPolicy.origin(it) }
            if (origin != null && store.remainingHoldSeconds(origin, System.currentTimeMillis()) > 0) {
                showRate(origin, store.remainingHoldSeconds(origin, System.currentTimeMillis()))
            } else {
                showScreen(Screen.CONNECT)
            }
        } else if (restoredScreen == Screen.MANUAL) {
            showScreen(Screen.MANUAL)
        } else {
            showScreen(Screen.CONNECT)
        }
    }

    private fun handleIntent(intent: Intent?) {
        val data = intent?.dataString ?: return
        if (!data.startsWith("chatclumer:", ignoreCase = true)) return
        val payload = PairLinks.parse(data)
        if (payload == null) {
            toast(R.string.qr_invalid)
            showScreen(Screen.CONNECT)
            return
        }
        connect(payload.baseUrl, payload.token, fromUserInput = false)
    }

    private fun connect(baseInput: String, token: String, fromUserInput: Boolean) {
        if (busy) return
        val base = if (fromUserInput) UrlPolicy.normalizeUserInput(baseInput) else UrlPolicy.normalizeBase(baseInput)
        if (base == null) {
            toast(R.string.url_invalid)
            return
        }
        if (!TokenPolicy.accept(token)) {
            toast(R.string.token_invalid)
            return
        }
        val origin = UrlPolicy.origin(base) ?: run {
            toast(R.string.url_invalid)
            return
        }
        attemptBase = base
        attemptToken = token
        val left = store.remainingHoldSeconds(origin, System.currentTimeMillis())
        if (left > 0L) {
            showRate(origin, left)
            return
        }
        stopCamera()
        busy = true
        showBusy(true)
        val generation = ++connectGen
        lifecycleScope.launch {
            val probe = withContext(Dispatchers.IO) { server.ping(base) }
            if (generation != connectGen || isDestroyed) return@launch
            busy = false
            showBusy(false)
            when (probe) {
                is Probe.Online -> openWeb(base, token, probe.version)
                Probe.NotChatClumer -> showProblem(ErrorKind.NOT_APP)
                is Probe.RateLimited -> {
                    val seconds = store.rememberHold(origin, probe.retryAfterSeconds, System.currentTimeMillis())
                    Log.i(TAG, "rate-limited")
                    showRate(origin, seconds)
                }
                is Probe.Failed -> showProblem(if (probe.kind == "network") ErrorKind.OFFLINE else ErrorKind.NOT_APP)
            }
        }
    }

    private fun openWeb(base: String, token: String, version: String) {
        attemptVersion = version
        acceptWeb = true
        mainFrameFailed = false
        pendingClearHistory = true
        val web = ensureWeb()
        val known = store.list().firstOrNull { it.baseUrl == base }
        val host = UrlPolicy.hostLabel(base)
        binding.toolbar.title = known?.name ?: host
        binding.toolbar.subtitle = if (binding.toolbar.title?.toString() == host) null else host
        showScreen(Screen.WEB)
        binding.swipe.isRefreshing = true
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        web.loadUrl(UrlPolicy.pairUrl(base, token))
    }

    private fun refreshWeb() {
        val origin = attemptBase?.let { UrlPolicy.origin(it) }
        if (origin != null && store.remainingHoldSeconds(origin, System.currentTimeMillis()) > 0L) {
            binding.swipe.isRefreshing = false
            showRate(origin, store.remainingHoldSeconds(origin, System.currentTimeMillis()))
            return
        }
        val web = webView
        if (web == null) {
            binding.swipe.isRefreshing = false
            retryConnection()
        } else {
            acceptWeb = true
            mainFrameFailed = false
            web.reload()
        }
    }

    private fun retryConnection() {
        val base = attemptBase
        val origin = base?.let { UrlPolicy.origin(it) }
        if (origin != null) {
            val left = store.remainingHoldSeconds(origin, System.currentTimeMillis())
            if (left > 0L) {
                showRate(origin, left)
                return
            }
        }
        val token = attemptToken
        if (base != null && token != null) {
            connect(base, token, fromUserInput = false)
            return
        }
        val saved = activeId?.let { store.findById(it) }
        if (saved != null) reconnect(saved) else showScreen(Screen.CONNECT)
    }

    private fun reconnect(computer: SavedComputer) {
        activeId = computer.id
        connect(computer.baseUrl, computer.token, fromUserInput = false)
    }

    private fun startScan() {
        when {
            ContextCompat.checkSelfPermission(this, android.Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED -> openScanner()
            shouldShowRequestPermissionRationale(android.Manifest.permission.CAMERA) -> {
                MaterialAlertDialogBuilder(this)
                    .setMessage(R.string.camera_rationale)
                    .setPositiveButton(R.string.continue_action) { _, _ ->
                        cameraPermission.launch(android.Manifest.permission.CAMERA)
                    }
                    .setNegativeButton(R.string.manual_entry) { _, _ -> showScreen(Screen.MANUAL) }
                    .show()
            }
            else -> cameraPermission.launch(android.Manifest.permission.CAMERA)
        }
    }

    private fun openScanner() {
        scanArmed = true
        torchOn = false
        binding.torchButton.text = getString(R.string.torch_on)
        showScreen(Screen.SCAN)
        startCamera()
    }

    private fun closeScanner() {
        scanArmed = false
        stopCamera()
        showScreen(Screen.CONNECT)
    }

    private fun onScan(text: String) {
        val payload = PairLinks.parse(text)
        if (payload == null) {
            toast(R.string.qr_invalid)
            scanArmed = true
            if (screen == Screen.SCAN) startCamera()
            return
        }
        connect(payload.baseUrl, payload.token, fromUserInput = false)
    }

    private fun startCamera() {
        if (cameraRunning) return
        binding.barcodeScanner.resume()
        cameraRunning = true
    }

    private fun stopCamera() {
        if (!cameraRunning) return
        binding.barcodeScanner.setTorchOff()
        binding.barcodeScanner.pause()
        cameraRunning = false
        torchOn = false
    }

    private fun toggleTorch() {
        if (!cameraRunning) return
        torchOn = !torchOn
        if (torchOn) binding.barcodeScanner.setTorchOn() else binding.barcodeScanner.setTorchOff()
        binding.torchButton.text = getString(if (torchOn) R.string.torch_off else R.string.torch_on)
    }

    private fun showCameraDenied() {
        MaterialAlertDialogBuilder(this)
            .setMessage(R.string.camera_denied)
            .setPositiveButton(R.string.open_settings) { _, _ ->
                startActivity(
                    Intent(
                        android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.fromParts("package", packageName, null),
                    ),
                )
            }
            .setNegativeButton(R.string.manual_entry) { _, _ -> showScreen(Screen.MANUAL) }
            .show()
    }

    private fun showProblem(kind: ErrorKind) {
        acceptWeb = false
        binding.swipe.isRefreshing = false
        showBusy(false)
        errorKind = kind
        clock.removeCallbacks(rateTick)
        binding.errorWait.visibility = View.GONE
        binding.retryButton.isEnabled = true
        binding.retryButton.text = getString(R.string.retry)
        when (kind) {
            ErrorKind.OFFLINE -> {
                binding.errorTitle.setText(R.string.offline_title)
                binding.errorBody.setText(R.string.offline_body)
                binding.rescanButton.visibility = View.GONE
                binding.retryButton.visibility = View.VISIBLE
            }
            ErrorKind.AUTH -> {
                binding.errorTitle.setText(R.string.auth_title)
                binding.errorBody.setText(R.string.auth_body)
                binding.rescanButton.visibility = View.VISIBLE
                binding.retryButton.visibility = View.VISIBLE
            }
            ErrorKind.NOT_APP -> {
                binding.errorTitle.setText(R.string.not_chatclumer_title)
                binding.errorBody.setText(R.string.not_chatclumer_body)
                binding.rescanButton.visibility = View.GONE
                binding.retryButton.visibility = View.GONE
            }
            ErrorKind.HTTP -> {
                binding.errorTitle.setText(R.string.http_title)
                binding.errorBody.setText(R.string.http_body)
                binding.rescanButton.visibility = View.GONE
                binding.retryButton.visibility = View.VISIBLE
            }
            ErrorKind.RATE -> Unit
        }
        showScreen(Screen.ERROR)
    }

    private fun showRate(origin: String, seconds: Long) {
        acceptWeb = false
        binding.swipe.isRefreshing = false
        showBusy(false)
        stopCamera()
        errorKind = ErrorKind.RATE
        rateOrigin = origin
        binding.errorTitle.setText(R.string.rate_limit_title)
        binding.errorBody.text = getString(R.string.rate_limit_body, RateLimit.formatWait(seconds))
        binding.errorWait.visibility = View.VISIBLE
        binding.rescanButton.visibility = View.GONE
        binding.retryButton.visibility = View.VISIBLE
        showScreen(Screen.ERROR)
        clock.removeCallbacks(rateTick)
        rateTick.run()
    }

    private fun showScreen(next: Screen) {
        if (next != Screen.SCAN) stopCamera()
        if (next != Screen.ERROR) clock.removeCallbacks(rateTick)
        if (next != Screen.WEB) {
            acceptWeb = false
            binding.swipe.isRefreshing = false
        }
        screen = next
        binding.connectScreen.visibility = if (next == Screen.CONNECT) View.VISIBLE else View.GONE
        binding.manualScreen.visibility = if (next == Screen.MANUAL) View.VISIBLE else View.GONE
        binding.scannerScreen.visibility = if (next == Screen.SCAN) View.VISIBLE else View.GONE
        binding.webScreen.visibility = if (next == Screen.WEB) View.VISIBLE else View.GONE
        binding.errorScreen.visibility = if (next == Screen.ERROR) View.VISIBLE else View.GONE
        if (next == Screen.CONNECT) renderComputers()
    }

    private fun showBusy(show: Boolean) {
        binding.busy.visibility = if (show) View.VISIBLE else View.GONE
    }

    private fun renderComputers() {
        val list = store.list()
        binding.emptyComputers.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
        binding.computerList.removeAllViews()
        for (computer in list) {
            val row = ItemComputerBinding.inflate(layoutInflater, binding.computerList, false)
            row.computerName.text = computer.name
            row.computerAddress.text = getString(R.string.list_address, UrlPolicy.hostLabel(computer.baseUrl))
            row.computerToken.text = getString(R.string.token_masked, maskToken(computer.token))
            val version = displayVersion(computer.serverVersion)
            row.computerVersion.visibility = if (version.isEmpty()) View.GONE else View.VISIBLE
            row.computerVersion.text = getString(R.string.server_version, version)
            row.computerReconnect.setOnClickListener { reconnect(computer) }
            row.computerRename.setOnClickListener { promptRename(computer) }
            row.computerDelete.setOnClickListener { confirmDelete(computer) }
            binding.computerList.addView(row.root)
        }
    }

    private fun promptRename(computer: SavedComputer) {
        val input = EditText(this).apply {
            setText(computer.name)
            hint = getString(R.string.rename_hint)
            setSingleLine()
        }
        val pad = (16 * resources.displayMetrics.density).toInt()
        val wrap = LinearLayout(this).apply {
            setPadding(pad, pad / 2, pad, 0)
            addView(input, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        }
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.rename_title)
            .setView(wrap)
            .setPositiveButton(R.string.save) { _, _ ->
                val updated = store.rename(computer.id, input.text?.toString().orEmpty())
                if (updated == null) toast(R.string.rename_empty) else renderComputers()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun confirmDelete(computer: SavedComputer) {
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.delete_title)
            .setMessage(getString(R.string.delete_message, computer.name))
            .setPositiveButton(R.string.delete) { _, _ ->
                store.delete(computer.id)
                if (activeId == computer.id) activeId = null
                renderComputers()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun ensureWeb(): WebView {
        webView?.let { return it }
        val created = WebView(this)
        created.setBackgroundColor(ContextCompat.getColor(this, R.color.window_bg))
        val settings = created.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.allowFileAccess = false
        settings.allowContentAccess = true
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        settings.setSupportMultipleWindows(true)
        settings.javaScriptCanOpenWindowsAutomatically = false
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        settings.mediaPlaybackRequiresUserGesture = true
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            settings.isAlgorithmicDarkeningAllowed = false
        } else if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
            @Suppress("DEPRECATION")
            settings.forceDark = WebSettings.FORCE_DARK_OFF
        }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        created.webViewClient = ChatWebViewClient(this)
        created.webChromeClient = ChatChromeClient(this)
        binding.webContainer.addView(
            created,
            android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        webView = created
        return created
    }

    private fun discardWeb() {
        val view = webView ?: return
        acceptWeb = false
        binding.webContainer.removeView(view)
        view.stopLoading()
        view.destroy()
        webView = null
    }

    private fun toast(message: Int) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    private enum class Screen { CONNECT, MANUAL, SCAN, WEB, ERROR }

    private enum class ErrorKind { OFFLINE, AUTH, RATE, NOT_APP, HTTP }

    companion object {
        private const val TAG = "ChatCluster"
        private const val STATE_SCREEN = "screen"
        private const val STATE_ERROR = "error"
        private const val STATE_ACTIVE = "active"
        private const val STATE_BASE = "base"
        private const val STATE_WEB = "web"
    }
}
