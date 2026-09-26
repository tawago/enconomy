package com.enconomy.pop

import android.app.Application
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge

class PopApplication : Application() {
    /** Process-lifetime controller: survives activity recreation. */
    val controller by lazy { PopController(createDeviceKeystore()) }

    override fun onCreate() {
        super.onCreate()
        instance = this
    }

    companion object {
        lateinit var instance: PopApplication
            private set
    }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val controller = (application as PopApplication).controller
        setContent { App(controller) }
    }

    /** enconomy://worldid from World App (singleTask). */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (WorldId.isReturnLink(intent.dataString)) (application as PopApplication).controller.onWorldIdReturn()
    }

    /** Back in front (e.g. from World App by hand): resync the server clock, restart the World ID poll. */
    override fun onResume() {
        super.onResume()
        (application as PopApplication).controller.onForeground()
    }
}
