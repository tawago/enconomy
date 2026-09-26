package com.enconomy.pop.zk

/** Build without app/prover/dist/ios (see app/prover/README.md): no on-phone proofs. */
actual object ProverLib {
    actual val available: Boolean = false
    actual val loadError: String? = "native prover not in this build (app/prover/dist/ios missing at build time)"
    actual fun version(): String = "unavailable"
    actual fun open(pkPath: String): Long = throw ProverException("Unavailable", loadError!!)
    actual fun close(handle: Long) {}
    actual fun sampleRate(handle: Long): Int = throw ProverException("Unavailable", loadError!!)
    actual fun check(handle: Long, inputJson: ByteArray): String = throw ProverException("Unavailable", loadError!!)
    actual fun prove(handle: Long, inputJson: ByteArray): ByteArray = throw ProverException("Unavailable", loadError!!)
}
