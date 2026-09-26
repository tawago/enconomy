package com.enconomy.pop

import android.app.Application
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.lifecycleScope
import com.enconomy.pop.zk.ProofRunner
import kotlinx.coroutines.launch

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
        // Proving needs the app in the top-app cpuset (all 8 cores on a Pixel 6). Screen off / locked = background
        // cpuset, little cores only: 91 s instead of 25 s. Keep the screen on while a proof runs.
        lifecycleScope.launch {
            ProofRunner.awakeCount.collect { n ->
                if (n > 0) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
        // adb shell am start -n com.enconomy.pop/.MainActivity --es pop.bench 180ca04b_48k_A [--ez pop.force true]
        // The bench shows over the lock screen and wakes it, so a locked phone on the cable still proves at full speed.
        startBench(intent)
    }

    private fun startBench(i: Intent) {
        val name = i.getStringExtra("pop.bench") ?: return
        if (Build.VERSION.SDK_INT >= 27) { setShowWhenLocked(true); setTurnScreenOn(true) }
        val controller = (application as PopApplication).controller
        controller.openBench(); controller.benchRun(name, i.getBooleanExtra("pop.force", false))
    }

    /** enconomy://worldid from World App (singleTask). */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        startBench(intent)
        if (WorldId.isReturnLink(intent.dataString)) (application as PopApplication).controller.onWorldIdReturn()
    }

    /** Back in front (e.g. from World App by hand): resync the server clock, restart the World ID poll. */
    override fun onResume() {
        super.onResume()
        (application as PopApplication).controller.onForeground()
    }
}
