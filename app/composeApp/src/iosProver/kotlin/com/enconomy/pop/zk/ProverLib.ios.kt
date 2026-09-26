@file:OptIn(ExperimentalForeignApi::class)

package com.enconomy.pop.zk

import com.enconomy.pop.zk.native.PopBuf
import com.enconomy.pop.zk.native.POP_OK
import com.enconomy.pop.zk.native.pop_buf_free
import com.enconomy.pop.zk.native.pop_prover_check
import com.enconomy.pop.zk.native.pop_prover_close
import com.enconomy.pop.zk.native.pop_prover_open
import com.enconomy.pop.zk.native.pop_prover_prove
import com.enconomy.pop.zk.native.pop_prover_sample_rate
import com.enconomy.pop.zk.native.pop_prover_version
import kotlinx.cinterop.CPointerVar
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.MemScope
import kotlinx.cinterop.UByteVar
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.alloc
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr as addr
import kotlinx.cinterop.readBytes
import kotlinx.cinterop.readValue
import kotlinx.cinterop.reinterpret
import kotlinx.cinterop.toCPointer
import kotlinx.cinterop.toKString
import kotlinx.cinterop.toLong
import kotlinx.cinterop.usePinned
import kotlinx.cinterop.value
import cnames.structs.PopProver

/** libpop_prover.a from app/prover/dist/ios (cinterop popprover.def). */
actual object ProverLib {
    actual val available: Boolean = true
    actual val loadError: String? = null

    actual fun version(): String = pop_prover_version()?.toKString() ?: "?"

    actual fun open(pkPath: String): Long = memScoped {
        val out = alloc<CPointerVar<PopProver>>()
        val err = alloc<PopBuf>()
        val rc = pop_prover_open(pkPath, out.addr, err.addr)
        failIf(rc, err)
        out.value.toLong()
    }

    actual fun close(handle: Long) {
        if (handle != 0L) pop_prover_close(handle.toCPointer<PopProver>())
    }

    actual fun sampleRate(handle: Long): Int = pop_prover_sample_rate(handle.toCPointer<PopProver>()).toInt()

    actual fun check(handle: Long, inputJson: ByteArray): String = memScoped {
        val pub = alloc<PopBuf>()
        val err = alloc<PopBuf>()
        val rc = inputJson.usePinned { pin ->
            pop_prover_check(handle.toCPointer<PopProver>(), pin.addressOf(0).reinterpret<UByteVar>(), inputJson.size.toULong(), pub.addr, err.addr)
        }
        failIf(rc, err)
        take(pub).decodeToString()
    }

    actual fun prove(handle: Long, inputJson: ByteArray): ByteArray = memScoped {
        val proof = alloc<PopBuf>()
        val err = alloc<PopBuf>()
        val rc = inputJson.usePinned { pin ->
            pop_prover_prove(handle.toCPointer<PopProver>(), pin.addressOf(0).reinterpret<UByteVar>(), inputJson.size.toULong(), proof.addr, err.addr)
        }
        failIf(rc, err)
        take(proof)
    }

    private fun take(b: PopBuf): ByteArray {
        val p = b.ptr ?: return ByteArray(0)
        val out = p.readBytes(b.len.toInt())
        pop_buf_free(b.readValue())
        return out
    }

    @Suppress("UnusedReceiverParameter")
    private fun MemScope.failIf(rc: Int, err: PopBuf) {
        if (rc == POP_OK.toInt()) return
        val msg = take(err).decodeToString()
        throw ProverException.ofRc(rc, msg)
    }
}
