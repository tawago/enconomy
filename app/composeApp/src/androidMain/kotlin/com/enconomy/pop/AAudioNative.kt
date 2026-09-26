package com.enconomy.pop

import android.os.Build
import android.util.Log

/** JNI to libpop_aaudio.so (src/androidMain/cpp/pop_aaudio.cpp). API 28+ (input presets). */
internal object AAudioNative {
    val available: Boolean by lazy {
        Build.VERSION.SDK_INT >= 28 && try {
            System.loadLibrary("pop_aaudio")
            true
        } catch (t: Throwable) {
            Log.w("PopAudio", "pop_aaudio: $t")
            false
        }
    }

    const val SHARING_EXCLUSIVE = 0
    const val PRESET_VOICE_RECOGNITION = 6
    const val PRESET_UNPROCESSED = 9

    /** Opens output (float, [play]) + input (int16, [recFrames] capacity). 0 = failed, see [lastError]. */
    @JvmStatic external fun open(sr: Int, exclusive: Boolean, preset: Int, play: FloatArray?, recFrames: Int): Long
    @JvmStatic external fun lastError(): String
    @JvmStatic external fun info(h: Long): IntArray
    @JvmStatic external fun startIn(h: Long): Int
    @JvmStatic external fun startOut(h: Long): Int
    @JvmStatic external fun stop(h: Long)
    /** [ok, framePosition − first-callback frame, nanoTime]. */
    @JvmStatic external fun timestamp(h: Long, output: Boolean): LongArray
    @JvmStatic external fun status(h: Long): LongArray
    @JvmStatic external fun latency(h: Long): DoubleArray
    @JvmStatic external fun capture(h: Long, start: Int, n: Int): ShortArray?
    @JvmStatic external fun close(h: Long)
}
