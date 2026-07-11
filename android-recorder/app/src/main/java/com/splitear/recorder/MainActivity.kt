package com.splitear.recorder

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.drawable.GradientDrawable
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.*
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var etRoomId: EditText
    private lateinit var etServerUrl: EditText
    private lateinit var rgChannel: RadioGroup
    private lateinit var btnStart: Button
    private lateinit var btnStop: Button
    private lateinit var btnLoadPlayer: Button
    private lateinit var btnToggleControls: Button
    private lateinit var tvStatus: TextView
    private lateinit var controlsLayout: LinearLayout
    private lateinit var webView: WebView

    private val CAPTURE_PERMISSION_REQUEST_CODE = 2026

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Root container: Vertical LinearLayout, fills screen, dark background
        val rootLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xFF0C0F1E.toInt())
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        // Header bar: deep black-blue panel with cyan title and pink settings toggle
        val headerBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(32, 24, 32, 24)
            setBackgroundColor(0xFF0A0C16.toInt())
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        val tvTitle = TextView(this).apply {
            text = "SPLIT//EAR LINK"
            textSize = 16f
            setTextColor(0xFF00E5FF.toInt())
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        headerBar.addView(tvTitle)

        // Spacer to push toggle button to the right
        val headerSpacer = View(this).apply {
            layoutParams = LinearLayout.LayoutParams(0, 0, 1f)
        }
        headerBar.addView(headerSpacer)

        // Toggle controls button
        btnToggleControls = Button(this).apply {
            text = "[▲ HIDE]"
            setTextColor(0xFFFF2D95.toInt())
            textSize = 12f
            background = null // Transparent background
            setPadding(0, 0, 0, 0)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        headerBar.addView(btnToggleControls)

        rootLayout.addView(headerBar)

        // Collapsible Controls Panel
        controlsLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 16, 32, 24)
            setBackgroundColor(0xFF0C0F1E.toInt())
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        etServerUrl = createCyberpunkEditText("Server URL", "https://split-ear-m30r.onrender.com").apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                setMargins(0, 8, 0, 8)
            }
        }
        controlsLayout.addView(etServerUrl)

        etRoomId = createCyberpunkEditText("Room ID", "").apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                setMargins(0, 8, 0, 16)
            }
        }
        controlsLayout.addView(etRoomId)

        // Side selector layout
        val sideSelectorLayout = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                setMargins(0, 0, 0, 16)
            }
        }

        val tvSideLabel = TextView(this).apply {
            text = "STREAM SIDE:"
            setTextColor(0xFF6B7385.toInt())
            textSize = 12f
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        sideSelectorLayout.addView(tvSideLabel)

        rgChannel = RadioGroup(this).apply {
            orientation = RadioGroup.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                setMargins(16, 0, 0, 0)
            }
        }
        
        val rbLeft = RadioButton(this).apply {
            text = "L-EAR"
            id = View.generateViewId()
            setTextColor(0xFFFFFFFF.toInt())
            buttonTintList = android.content.res.ColorStateList.valueOf(0xFF00E5FF.toInt())
        }
        val rbRight = RadioButton(this).apply {
            text = "R-EAR"
            id = View.generateViewId()
            setTextColor(0xFFFFFFFF.toInt())
            buttonTintList = android.content.res.ColorStateList.valueOf(0xFFFF2D95.toInt())
        }
        rgChannel.addView(rbLeft)
        rgChannel.addView(rbRight)
        rbLeft.isChecked = true
        sideSelectorLayout.addView(rgChannel)

        controlsLayout.addView(sideSelectorLayout)

        // Action Buttons Row: Start, Stop, Load Player
        val buttonsRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        btnStart = createCyberpunkButton("START CAPTURE", 0xFF00E5FF.toInt(), 0xFF0C0F1E.toInt()).apply {
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(0, 0, 8, 0)
            }
        }
        buttonsRow.addView(btnStart)

        btnStop = createCyberpunkButton("STOP CAPTURE", 0xFFFF2D95.toInt(), 0xFFFFFFFF.toInt()).apply {
            isEnabled = false
            alpha = 0.5f
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(0, 0, 8, 0)
            }
        }
        buttonsRow.addView(btnStop)

        btnLoadPlayer = createCyberpunkButton("LOAD", 0xFF1C2138.toInt(), 0xFF00E5FF.toInt()).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        buttonsRow.addView(btnLoadPlayer)

        controlsLayout.addView(buttonsRow)

        tvStatus = TextView(this).apply {
            text = "Status: Disconnected"
            setTextColor(0xFF6B7385.toInt())
            textSize = 12f
            gravity = android.view.Gravity.CENTER
            setPadding(0, 16, 0, 0)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        controlsLayout.addView(tvStatus)

        rootLayout.addView(controlsLayout)

        // WebView: takes up remaining space
        webView = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    url?.let { checkAndSyncRoomId(it) }
                }

                override fun shouldOverrideUrlLoading(view: WebView?, request: android.webkit.WebResourceRequest?): Boolean {
                    val url = request?.url?.toString()
                    url?.let { checkAndSyncRoomId(it) }
                    return false
                }
            }
        }
        
        // Add JavascriptInterface to bridge the WebView click events and native projection capture
        webView.addJavascriptInterface(WebAppInterface(this), "AndroidApp")
        
        rootLayout.addView(webView)

        setContentView(rootLayout)

        // Collapse/expand animation logic
        btnToggleControls.setOnClickListener {
            if (controlsLayout.visibility == View.VISIBLE) {
                controlsLayout.visibility = View.GONE
                btnToggleControls.text = "[⚙ CONTROLS]"
            } else {
                controlsLayout.visibility = View.VISIBLE
                btnToggleControls.text = "[▲ HIDE]"
            }
        }

        btnLoadPlayer.setOnClickListener {
            loadPlayerFromInputs()
        }

        btnStart.setOnClickListener {
            val roomId = etRoomId.text.toString().trim()
            if (roomId.isEmpty()) {
                Toast.makeText(this, "Please enter a valid Room ID", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            requestScreenCapturePermission()
        }

        btnStop.setOnClickListener {
            stopCaptureService()
        }

        // Load the web page immediately on startup
        loadPlayerFromInputs()
    }

    private fun createCyberpunkEditText(hintText: String, defaultText: String): EditText {
        return EditText(this).apply {
            hint = hintText
            setText(defaultText)
            setTextColor(0xFFFFFFFF.toInt())
            setHintTextColor(0xFF6B7385.toInt())
            textSize = 14f
            val gd = GradientDrawable().apply {
                setColor(0xFF070912.toInt())
                cornerRadius = 12f
                setStroke(2, 0xFF1C2138.toInt())
            }
            background = gd
            setPadding(32, 24, 32, 24)
        }
    }

    private fun createCyberpunkButton(textStr: String, bgColor: Int, textColor: Int): Button {
        return Button(this).apply {
            text = textStr
            setTextColor(textColor)
            textSize = 12f
            val gd = GradientDrawable().apply {
                setColor(bgColor)
                cornerRadius = 12f
                setStroke(2, 0xFF1C2138.toInt())
            }
            background = gd
            setPadding(16, 16, 16, 16)
        }
    }

    private fun loadPlayerFromInputs() {
        val serverUrl = etServerUrl.text.toString().trim()
        val roomId = etRoomId.text.toString().trim()
        val url = if (roomId.isNotEmpty()) {
            "$serverUrl/?room=$roomId"
        } else {
            serverUrl
        }
        webView.loadUrl(url)
    }

    private fun checkAndSyncRoomId(url: String) {
        try {
            val uri = Uri.parse(url)
            val roomParam = uri.getQueryParameter("room")
            if (!roomParam.isNullOrEmpty()) {
                runOnUiThread {
                    val currentInput = etRoomId.text.toString().trim()
                    if (currentInput != roomParam.trim()) {
                        etRoomId.setText(roomParam.trim())
                        Toast.makeText(this@MainActivity, "Room ID Synced: $roomParam", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    fun startCaptureFromWeb(channelSide: String) {
        if (channelSide == "left") {
            rgChannel.check(rgChannel.getChildAt(0).id)
        } else {
            rgChannel.check(rgChannel.getChildAt(1).id)
        }
        val roomId = etRoomId.text.toString().trim()
        if (roomId.isEmpty()) {
            // Generate a random temporary room if empty
            val randRoom = "room-" + (100000..999999).random()
            etRoomId.setText(randRoom)
        }
        requestScreenCapturePermission()
    }

    fun stopCaptureFromWeb() {
        stopCaptureService()
    }

    private fun requestScreenCapturePermission() {
        val mediaProjectionManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(
            mediaProjectionManager.createScreenCaptureIntent(),
            CAPTURE_PERMISSION_REQUEST_CODE
        )
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == CAPTURE_PERMISSION_REQUEST_CODE) {
            if (resultCode == Activity.RESULT_OK && data != null) {
                startCaptureService(resultCode, data)
            } else {
                Toast.makeText(this, "Permission to capture audio was denied.", Toast.LENGTH_SHORT).show()
                // Revert state on Javascript UI
                val selectedRbId = rgChannel.checkedRadioButtonId
                val rb = findViewById<RadioButton>(selectedRbId)
                val channelSide = if (rb != null && (rb.text.toString().contains("LEFT") || rb.text.toString().contains("L-EAR"))) "left" else "right"
                webView.post {
                    webView.evaluateJavascript("javascript:onNativeCaptureStateChanged(false, '$channelSide')", null)
                }
            }
        }
    }

    private fun startCaptureService(resultCode: Int, data: Intent) {
        val selectedRbId = rgChannel.checkedRadioButtonId
        val rb = findViewById<RadioButton>(selectedRbId)
        val channelSide = if (rb != null && (rb.text.toString().contains("LEFT") || rb.text.toString().contains("L-EAR"))) "left" else "right"
        val serverUrl = etServerUrl.text.toString().trim()
        val roomId = etRoomId.text.toString().trim()

        val serviceIntent = Intent(this, AudioCaptureService::class.java).apply {
            putExtra("RESULT_CODE", resultCode)
            putExtra("RESULT_DATA", data)
            putExtra("ROOM_ID", roomId)
            putExtra("CHANNEL_SIDE", channelSide)
            putExtra("SERVER_URL", serverUrl)
        }

        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }

        btnStart.isEnabled = false
        btnStart.alpha = 0.5f
        btnStop.isEnabled = true
        btnStop.alpha = 1.0f
        tvStatus.text = "Status: Streaming to Room $roomId ($channelSide)"
        tvStatus.setTextColor(0xFF00E5FF.toInt())
        
        // Notify web UI via WebView injection
        webView.post {
            webView.evaluateJavascript("javascript:onNativeCaptureStateChanged(true, '$channelSide')", null)
        }
    }

    private fun stopCaptureService() {
        val serviceIntent = Intent(this, AudioCaptureService::class.java)
        stopService(serviceIntent)

        val selectedRbId = rgChannel.checkedRadioButtonId
        val rb = findViewById<RadioButton>(selectedRbId)
        val channelSide = if (rb != null && (rb.text.toString().contains("LEFT") || rb.text.toString().contains("L-EAR"))) "left" else "right"

        btnStart.isEnabled = true
        btnStart.alpha = 1.0f
        btnStop.isEnabled = false
        btnStop.alpha = 0.5f
        tvStatus.text = "Status: Stopped"
        tvStatus.setTextColor(0xFF6B7385.toInt())
        
        // Notify web UI via WebView injection
        webView.post {
            webView.evaluateJavascript("javascript:onNativeCaptureStateChanged(false, '$channelSide')", null)
        }
    }

    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }

    // JS interface bridge to listen to capture events inside the Web UI
    class WebAppInterface(private val activity: MainActivity) {
        
        @JavascriptInterface
        fun startCapture(channelSide: String) {
            activity.runOnUiThread {
                activity.startCaptureFromWeb(channelSide)
            }
        }

        @JavascriptInterface
        fun stopCapture() {
            activity.runOnUiThread {
                activity.stopCaptureFromWeb()
            }
        }

        @JavascriptInterface
        fun isApp(): Boolean {
            return true
        }
    }
}
