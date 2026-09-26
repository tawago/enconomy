package com.enconomy.pop.zk

/** JNI entry points of app/prover/src/jni_android.rs; names must match exactly. */
object PopProverNative {
    @JvmStatic external fun open(pkPath: String): Long
    @JvmStatic external fun close(handle: Long)
    @JvmStatic external fun sampleRate(handle: Long): Int
    @JvmStatic external fun check(handle: Long, inputJson: ByteArray): String
    @JvmStatic external fun prove(handle: Long, inputJson: ByteArray): ByteArray
}

actual object ProverLib {
    /** jniLibs/arm64-v8a/libpop_prover.so (gradle copyProverSo); absent on other ABIs. */
    actual val loadError: String? = try {
        System.loadLibrary("pop_prover")
        null
    } catch (e: Throwable) {
        "native prover not in this build (${e.message})"
    }

    actual val available: Boolean get() = loadError == null

    actual fun version(): String = if (available) "pop-prover (jni)" else "unavailable"

    actual fun open(pkPath: String): Long = jni { PopProverNative.open(pkPath) }
    actual fun close(handle: Long) { if (available && handle != 0L) PopProverNative.close(handle) }
    actual fun sampleRate(handle: Long): Int = jni { PopProverNative.sampleRate(handle) }
    actual fun check(handle: Long, inputJson: ByteArray): String = jni { PopProverNative.check(handle, inputJson) }
    actual fun prove(handle: Long, inputJson: ByteArray): ByteArray = jni { PopProverNative.prove(handle, inputJson) }

    /** RuntimeException("pop-prover <Code>: <message>") -> ProverException. */
    private inline fun <T> jni(f: () -> T): T {
        loadError?.let { throw ProverException("Unavailable", it) }
        try {
            return f()
        } catch (e: RuntimeException) {
            val m = Regex("^pop-prover (\\w+): (.*)$", RegexOption.DOT_MATCHES_ALL).find(e.message ?: "") ?: throw e
            throw ProverException(m.groupValues[1], m.groupValues[2])
        }
    }
}
