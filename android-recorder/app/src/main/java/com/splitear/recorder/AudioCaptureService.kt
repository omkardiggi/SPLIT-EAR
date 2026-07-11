package com.splitear.recorder

import android.app.*
import android.content.Context
import android.content.Intent
import android.media.*
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.annotation.RequiresApi
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class AudioCaptureService : Service() {

    private var mediaProjection: MediaProjection? = null
    private var audioRecord: AudioRecord? = null
    private var isRecording = false
    private var roomId: String = "default"
    private var channelSide: String = "left"
    private var serverUrl: String = "https://split-ear-m30r.onrender.com"

    companion object {
        private const val CHANNEL_ID = "AudioCaptureServiceChannel"
        private const val NOTIFICATION_ID = 404
        private const val TAG = "SplitEarCapture"
    }

    override fun onBind(intent: Intent?): IBinder? = null

    @RequiresApi(Build.VERSION_CODES.Q)
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        roomId = intent?.getStringExtra("ROOM_ID") ?: "default"
        channelSide = intent?.getStringExtra("CHANNEL_SIDE") ?: "left"
        serverUrl = intent?.getStringExtra("SERVER_URL") ?: "https://split-ear-m30r.onrender.com"

        val resultCode = intent?.getIntExtra("RESULT_CODE", Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val resultData = intent?.getParcelableExtra<Intent>("RESULT_DATA")

        createNotificationChannel()
        val notification = createNotification()
        startForeground(NOTIFICATION_ID, notification)

        val mpManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        if (resultData != null) {
            mediaProjection = mpManager.getMediaProjection(resultCode, resultData)
            startAudioCapture()
        }

        return START_NOT_STICKY
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun startAudioCapture() {
        val proj = mediaProjection ?: return
        
        // Match only media/music and game audio playback
        val config = AudioPlaybackCaptureConfiguration.Builder(proj)
            .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
            .addMatchingUsage(AudioAttributes.USAGE_GAME)
            .build()

        val sampleRate = 44100
        val bufferSize = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_STEREO,
            AudioFormat.ENCODING_PCM_16BIT
        ) * 2

        try {
            audioRecord = AudioRecord.Builder()
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(sampleRate)
                        .setChannelMask(AudioFormat.CHANNEL_IN_STEREO)
                        .build()
                )
                .setBufferSizeInBytes(bufferSize)
                .setAudioPlaybackCaptureConfig(config)
                .build()

            audioRecord?.startRecording()
            isRecording = true
            
            thread {
                val buffer = ByteArray(bufferSize)
                while (isRecording) {
                    val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (read > 0) {
                        sendAudioToServer(buffer.copyOfRange(0, read))
                    }
                }
            }
            Log.d(TAG, "Audio capture started successfully.")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start AudioRecord", e)
        }
    }

    private fun sendAudioToServer(pcmData: ByteArray) {
        thread {
            try {
                // Post PCM chunk to our Flask endpoint
                val url = URL("$serverUrl/api/stream-upload?room=$roomId&channel=$channelSide")
                val connection = url.openConnection() as HttpURLConnection
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/octet-stream")
                connection.setConnectTimeout(2000)
                connection.setReadTimeout(2000)

                val os: OutputStream = connection.outputStream
                os.write(pcmData)
                os.flush()
                os.close()

                val code = connection.responseCode
                if (code != 200) {
                    Log.w(TAG, "Server responded with code $code")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to send audio packet", e)
            }
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val serviceChannel = NotificationChannel(
                CHANNEL_ID,
                "Split-Ear Capture Service",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(serviceChannel)
        }
    }

    private fun createNotification(): Notification {
        val pendingIntent: PendingIntent = Intent(this, MainActivity::class.java).let { notificationIntent ->
            PendingIntent.getActivity(this, 0, notificationIntent, PendingIntent.FLAG_IMMUTABLE)
        }

        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("Split-Ear Audio Link Active")
                .setContentText("Capturing and streaming system audio...")
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentIntent(pendingIntent)
                .build()
        } else {
            Notification.Builder(this)
                .setContentTitle("Split-Ear Audio Link Active")
                .setContentText("Capturing and streaming system audio...")
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentIntent(pendingIntent)
                .build()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        isRecording = false
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
        mediaProjection?.stop()
        mediaProjection = null
        Log.d(TAG, "Audio capture service stopped.")
    }
}
