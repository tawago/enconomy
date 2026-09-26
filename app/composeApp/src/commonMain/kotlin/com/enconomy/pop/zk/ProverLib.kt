package com.enconomy.pop.zk

/**
 * app/prover native library (Android JNI `libpop_prover.so`, iOS static lib via cinterop).
 * Every call blocks for seconds and holds ~1.5–2 GB while a key is open: background threads only.
 * A build without the native library has [available] false and every call throws.
 */
expect object ProverLib {
    val available: Boolean
    /** Why [available] is false. */
    val loadError: String?
    fun version(): String
    /** Proving key (.pk or .pk.zst). Returns a handle for the other calls. */
    fun open(pkPath: String): Long
    fun close(handle: Long)
    /** 48000 / 44100: the circuit the key belongs to. */
    fun sampleRate(handle: Long): Int
    /** Witness + every R1CS constraint, no proof. Returns {"public": ["dec", ...]}. */
    fun check(handle: Long, inputJson: ByteArray): String
    /** Witness -> constraint check -> proof bytes (bincode R1CSSNARK). */
    fun prove(handle: Long, inputJson: ByteArray): ByteArray
}

/** [code]: Arg, Io, Witness, Unsat, Prove, Verify, Panic, Unavailable. */
class ProverException(val code: String, msg: String) : Exception("$code: $msg") {
    companion object {
        private val CODES = listOf("Ok", "Arg", "Io", "Witness", "Unsat", "Prove", "Verify", "Panic")
        fun ofRc(rc: Int, msg: String) = ProverException(CODES.getOrElse(rc) { "rc$rc" }, msg)
    }
}
