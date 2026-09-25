package com.enconomy.pop

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

/**
 * Foreground service, type microphone (§4.3 pre-flight, Android 14+): keeps the mic and the
 * process at foreground priority for the few seconds of a run. Started by prepare(), stopped by
 * release(). Best effort: if the system refuses, the run still goes on with the activity visible.
 */
class PopAudioService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        try {
            val type = if (Build.VERSION.SDK_INT >= 30) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0
            ServiceCompat.startForeground(this, NOTIF_ID, notification(this), type)
        } catch (e: Throwable) {
            Log.w("PopAudio", "startForeground: $e")
            stopSelf()
        }
        return START_NOT_STICKY
    }

    companion object {
        private const val CHANNEL = "pop-run"
        private const val NOTIF_ID = 4201

        fun start(ctx: Context) {
            try {
                ContextCompat.startForegroundService(ctx, Intent(ctx, PopAudioService::class.java))
            } catch (e: Throwable) {
                Log.w("PopAudio", "start service: $e")
            }
        }

        fun stop(ctx: Context) {
            runCatching { ctx.stopService(Intent(ctx, PopAudioService::class.java)) }
        }

        private fun notification(ctx: Context): Notification {
            if (Build.VERSION.SDK_INT >= 26) {
                val nm = ctx.getSystemService(NotificationManager::class.java)
                if (nm.getNotificationChannel(CHANNEL) == null) {
                    nm.createNotificationChannel(NotificationChannel(CHANNEL, "Presence check", NotificationManager.IMPORTANCE_LOW))
                }
            }
            return NotificationCompat.Builder(ctx, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("Checking presence")
                .setContentText("Using the microphone for a few seconds")
                .setOngoing(true)
                .build()
        }
    }
}
