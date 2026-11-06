package com.enconomy.pop

// Verbatim copy of derToRawRs from app/composeApp/src/commonMain/kotlin/com/enconomy/pop/Signing.kt (commit 53604e3).
// Only here so the spike compiles standalone. In the app the original is used.

/** DER ECDSA-Sig-Value -> raw r||s, each 32 bytes big-endian. */
fun derToRawRs(der: ByteArray, n: Int = 32): ByteArray {
    var i = 0
    fun len(): Int {
        val b = der[i++].toInt() and 0xff
        if (b < 0x80) return b
        var l = 0
        repeat(b and 0x7f) { l = (l shl 8) or (der[i++].toInt() and 0xff) }
        return l
    }
    fun int(): ByteArray {
        require(der[i++] == 0x02.toByte()) { "bad DER int" }
        val l = len()
        var v = der.copyOfRange(i, i + l)
        i += l
        var s = 0
        while (s < v.size - 1 && v[s] == 0.toByte()) s++
        v = v.copyOfRange(s, v.size)
        require(v.size <= n) { "int too long" }
        return ByteArray(n - v.size) + v
    }
    require(der[i++] == 0x30.toByte()) { "bad DER seq" }
    len()
    return int() + int()
}
