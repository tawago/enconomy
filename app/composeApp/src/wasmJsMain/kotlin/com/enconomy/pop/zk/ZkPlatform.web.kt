package com.enconomy.pop.zk

import com.enconomy.pop.jsDeviceMemoryGb
import com.enconomy.pop.jsSaveData

/** Web: no on-device proving; proofs go through POST /v1/session/{id}/proof/delegate. */
actual object ProverLib {
    actual val available: Boolean = false
    actual val loadError: String? = "web: delegated proving"
    actual fun version(): String = "unavailable"
    actual fun prove(circuitJson: String, inputs: ByteArray, crs: String, vk: String?): ZkProof =
        throw ProverException("Unavailable", loadError!!)
}

/** In-memory stand-in (no proving keys are downloaded on web). */
actual object ZkFiles {
    private val files = HashMap<String, ByteArray>()

    actual fun dir(): String = "/mem/zk"
    actual fun size(path: String): Long = files[path]?.size?.toLong() ?: -1
    actual fun append(path: String, bytes: ByteArray) { files[path] = (files[path] ?: ByteArray(0)) + bytes }
    actual fun write(path: String, bytes: ByteArray) { files[path] = bytes.copyOf() }
    actual fun read(path: String): ByteArray = files[path]?.copyOf() ?: error("cannot read $path")
    actual fun rename(from: String, to: String): Boolean {
        val b = files.remove(from) ?: return false
        files[to] = b
        return true
    }
    actual fun delete(path: String) { files.remove(path) }
}

actual object DeviceMemory {
    actual fun info(): MemInfo = MemInfo((jsDeviceMemoryGb() * 1024 * 1024 * 1024).toLong(), null)
    actual fun footprint(): Long = 0
    actual fun peak(): Long? = null
    actual fun resetPeak() {}
    actual fun nativeHeap(): Long? = null
    actual fun trim() {}
}

actual fun networkIsMetered(): Boolean? = when (jsSaveData()) { 1 -> true; 0 -> false; else -> null }
