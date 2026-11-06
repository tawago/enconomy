package com.enconomy.pop.zk

/** App-private files under [dir] (proving keys, proofs). Paths are absolute. */
expect object ZkFiles {
    /** Android external app files/zk (fallback filesDir/zk), iOS Application Support/zk (excluded from backup). Created on first use. */
    fun dir(): String
    /** -1 when missing. */
    fun size(path: String): Long
    fun append(path: String, bytes: ByteArray)
    fun write(path: String, bytes: ByteArray)
    fun read(path: String): ByteArray
    /** Replaces [to]. */
    fun rename(from: String, to: String): Boolean
    fun delete(path: String)
}

/**
 * [availBytes]: what the OS says it can still give (Android availMem, iOS os_proc_available_memory).
 * [hardLimit]: availBytes is this process's own kill limit minus [usedBytes] (iOS jetsam), not reclaimable system RAM.
 */
class MemInfo(val totalBytes: Long, val availBytes: Long?, val hardLimit: Boolean = false, val usedBytes: Long = 0)

expect object DeviceMemory {
    fun info(): MemInfo
    /** Current process footprint (Android RSS, iOS phys_footprint). */
    fun footprint(): Long
    /** OS-tracked process peak (Android VmHWM after [resetPeak], iOS ledger peak for the process lifetime). */
    fun peak(): Long?
    /** Android: clear_refs 5 (resets VmHWM); iOS: no-op. */
    fun resetPeak()
    /** Android Debug.getNativeHeapAllocatedSize, null elsewhere. */
    fun nativeHeap(): Long?
    /** Drop what we can before the native prove: iOS full Kotlin GC; Android no-op. */
    fun trim()
}

/** true = cellular / metered, false = Wi-Fi / unmetered, null = unknown. */
expect fun networkIsMetered(): Boolean?
