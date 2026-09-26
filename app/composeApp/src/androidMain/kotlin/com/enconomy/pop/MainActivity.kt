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
        // adb shell am start -n com.enconomy.pop/.MainActivity --es pop.bench 180ca04b_48k_A [--ez pop.force true]
        intent.getStringExtra("pop.bench")?.let { controller.openBench(); controller.benchRun(it, intent.getBooleanExtra("pop.force", false)) }
    }

    /** enconomy://worldid from World App (singleTask). */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (WorldId.isReturnLink(intent.dataString)) (application as PopApplication).controller.onWorldIdReturn()
    }

    /** Back from World App by hand: make sure the World ID poll is running. */
    override fun onResume() {
        super.onResume()
        (application as PopApplication).controller.onWorldIdReturn()
    }
}
