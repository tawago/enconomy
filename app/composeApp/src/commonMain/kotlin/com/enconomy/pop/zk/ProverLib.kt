package com.enconomy.pop.zk

/**
 * app/zkprove native library (Android JNI `libzkprove.so`, iOS static lib via cinterop): in-process ACVM witness
 * (noir v1.0.0-beta.22) + Barretenberg UltraHonk prove (bb v5.0.0-nightly.20260522, `-t evm`).
 * One call blocks for 10-40 s and holds ~1.3-1.7 GB: background threads only.
 * A build without the native library has [available] false and every call throws.
 */
expect object ProverLib {
    val available: Boolean
    /** Why [available] is false. */
    val loadError: String?
    fun version(): String
    /**
     * [circuitJson]: nargo artifact path; [inputs]: the ABI input map as JSON (WitnessInput); [crs]: BN254 G1 points;
     * [vk]: optional vk path (skips the vk computation). Witness failure = ProverException("Witness").
     */
    fun prove(circuitJson: String, inputs: ByteArray, crs: String, vk: String?): ZkProof
}

/** Exactly the files `bb prove -t evm` writes: proof (10,304 B) and public_inputs (32 B per public). */
class ZkProof(val proof: ByteArray, val publicInputs: ByteArray)

/** [code]: Arg, Io, Prove, Witness, Panic, Unavailable. */
class ProverException(val code: String, msg: String) : Exception("$code: $msg") {
    companion object {
        /** zkprove C ABI codes: 1 arg, 2 io, 3 prove, 4 witness, 9 panic. */
        fun ofRc(rc: Int, msg: String) = ProverException(
            when (rc) { 1 -> "Arg"; 2 -> "Io"; 3 -> "Prove"; 4 -> "Witness"; 9 -> "Panic"; else -> "rc$rc" }, msg,
        )
    }
}
