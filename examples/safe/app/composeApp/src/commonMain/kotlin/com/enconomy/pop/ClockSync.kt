package com.enconomy.pop

/**
 * Contract §4.1. Phone time base = System.nanoTime() (CLOCK_MONOTONIC, same clock as
 * AudioTimestamp.nanoTime). One ping: t0 before GET /v1/time, t1 after; keep the ping
 * with the smallest rtt; offset_ns = server_ms·1e6 − (t0 + rtt/2).
 */
data class ClockPing(val t0Ns: Long, val t1Ns: Long, val serverMs: Long) {
    val rttNs: Long get() = t1Ns - t0Ns
}

data class ClockOffset(val offsetNs: Long, val rttMinMs: Double, val pings: Int) {
    /** server_ms(now) = (nanoTime + offset_ns) / 1e6 */
    fun serverMs(localNs: Long): Double = (localNs + offsetNs) / 1e6

    /** Local nanoTime of a server instant: t0_ns = t0_ms·1e6 − offset_ns. */
    fun localNs(serverMs: Long): Long = serverMs * 1_000_000L - offsetNs

    /** §4.1: refuse to arm above this. */
    val ok: Boolean get() = rttMinMs <= ClockSync.MAX_RTT_MS
}

object ClockSync {
    const val PINGS = 10
    const val MAX_RTT_MS = 300.0

    fun best(pings: List<ClockPing>): ClockOffset {
        require(pings.isNotEmpty()) { "no pings" }
        val p = pings.filter { it.rttNs >= 0 }.minByOrNull { it.rttNs } ?: error("all pings have negative rtt")
        val offset = p.serverMs * 1_000_000L - (p.t0Ns + p.rttNs / 2)
        return ClockOffset(offset, p.rttNs / 1e6, pings.size)
    }

    /** [n] sequential pings. A failed ping is skipped; all failed = the last error. */
    suspend fun measure(n: Int = PINGS, nanoTime: () -> Long = ::monoNanos, serverMs: suspend () -> Long): ClockOffset {
        val got = ArrayList<ClockPing>(n)
        var err: Throwable? = null
        repeat(n) {
            val t0 = nanoTime()
            val s = try {
                serverMs()
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Throwable) {
                err = e; null
            }
            val t1 = nanoTime()
            if (s != null) got += ClockPing(t0, t1, s)
        }
        if (got.isEmpty()) throw err ?: IllegalStateException("clock sync: no pings")
        return best(got)
    }

    suspend fun measure(api: PopApi, n: Int = PINGS): ClockOffset = measure(n) { api.time().server_ms }
}
