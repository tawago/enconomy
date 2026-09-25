package com.enconomy.pop

import android.app.Application
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent

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
        super.onCreate(savedInstanceState)
        val controller = (application as PopApplication).controller
        setContent { App(controller) }
    }
}
