package com.enconomy.pop.zk

import android.app.ActivityManager
import android.content.Context
import android.net.ConnectivityManager
import android.os.Debug
import com.enconomy.pop.PopApplication
import java.io.File
import java.io.FileOutputStream

actual object ZkFiles {
    actual fun dir(): String = File(PopApplication.instance.filesDir, "zk").apply { mkdirs() }.absolutePath
    actual fun size(path: String): Long = File(path).let { if (it.isFile) it.length() else -1L }
    actual fun append(path: String, bytes: ByteArray) = FileOutputStream(path, true).use { it.write(bytes) }
    actual fun write(path: String, bytes: ByteArray) = File(path).writeBytes(bytes)
    actual fun read(path: String): ByteArray = File(path).readBytes()
    actual fun rename(from: String, to: String): Boolean {
        val t = File(to)
        return File(from).renameTo(t) || (t.delete() && File(from).renameTo(t))
    }
    actual fun delete(path: String) { File(path).delete() }
}

actual object DeviceMemory {
    private val am get() = PopApplication.instance.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager

    actual fun info(): MemInfo {
        val mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        return MemInfo(mi.totalMem, mi.availMem)
    }

    actual fun footprint(): Long = status("VmRSS") ?: Debug.getNativeHeapAllocatedSize()
    actual fun peak(): Long? = status("VmHWM")
    actual fun resetPeak() { runCatching { File("/proc/self/clear_refs").writeText("5") } }
    actual fun nativeHeap(): Long? = Debug.getNativeHeapAllocatedSize()

    /** /proc/self/status "<key>:   123 kB" in bytes. */
    private fun status(key: String): Long? = runCatching {
        File("/proc/self/status").readLines().firstOrNull { it.startsWith("$key:") }
            ?.substringAfter(':')?.trim()?.substringBefore(' ')?.toLong()?.times(1024)
    }.getOrNull()
}

actual fun networkIsMetered(): Boolean? = runCatching {
    val cm = PopApplication.instance.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    cm.isActiveNetworkMetered
}.getOrNull()
