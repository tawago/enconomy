import java.math.BigInteger
import org.kotlincrypto.hash.sha3.Keccak256

/**
 * Independent reference for EIP-8141 scheme 2 (P256), written from the sidecar's
 * packages/executor/src/services/FrameTxService/signature.ts validateSignature (P256 branch, lines 58-79)
 * and the msg rules at its top (lines 19-35). P256VERIFY is done with plain BigInteger curve math here
 * (no java.security), so it does not share code with the signer under test.
 */
object Scheme2 {
    val P = BigInteger("ffffffff00000001000000000000000000000000ffffffffffffffffffffffff", 16)
    val A = P - BigInteger.valueOf(3)
    val B = BigInteger("5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b", 16)
    val N = BigInteger("ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551", 16)
    val GX = BigInteger("6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296", 16)
    val GY = BigInteger("4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5", 16)

    enum class Result { OK, BAD_MSG, BAD_LEN, R_RANGE, S_RANGE_OR_HIGH, SIGNER_MISMATCH, P256VERIFY_FAIL }

    /**
     * @param msg explicit msg bytes, or empty = use [sigHash]
     * @param signer 20-byte resolved signer
     * @param sig the 128-byte scheme-2 signature field
     */
    fun validate(msg: ByteArray, sigHash: ByteArray, signer: ByteArray, sig: ByteArray): Result {
        val m = if (msg.isEmpty()) sigHash else {
            if (msg.size != 32) return Result.BAD_MSG
            if (msg.all { it == 0.toByte() }) return Result.BAD_MSG
            msg
        }
        if (sig.size != 128) return Result.BAD_LEN
        val r = u(sig, 0); val s = u(sig, 32); val qx = u(sig, 64); val qy = u(sig, 96)
        if (!(r.signum() > 0 && r < N)) return Result.R_RANGE
        if (!(s.signum() > 0 && s <= N.shiftRight(1))) return Result.S_RANGE_OR_HIGH
        val expected = Keccak256().digest(sig.copyOfRange(64, 128)).copyOfRange(12, 32)
        if (!expected.contentEquals(signer)) return Result.SIGNER_MISMATCH
        return if (p256verify(m, r, s, qx, qy)) Result.OK else Result.P256VERIFY_FAIL
    }

    /** RIP-7212 P256VERIFY semantics: h is the raw 32 bytes as an integer. Accepts high s (like the precompile). */
    fun p256verify(h32: ByteArray, r: BigInteger, s: BigInteger, qx: BigInteger, qy: BigInteger): Boolean {
        if (!(r.signum() > 0 && r < N && s.signum() > 0 && s < N)) return false
        if (!onCurve(qx, qy)) return false
        val e = BigInteger(1, h32)
        val w = s.modInverse(N)
        val u1 = e.multiply(w).mod(N)
        val u2 = r.multiply(w).mod(N)
        val pt = add(mul(u1, GX to GY), mul(u2, qx to qy)) ?: return false
        return pt.first.mod(N) == r
    }

    fun onCurve(x: BigInteger, y: BigInteger): Boolean =
        x.signum() >= 0 && x < P && y.signum() >= 0 && y < P &&
            y.modPow(BigInteger.TWO, P) == x.pow(3).add(A.multiply(x)).add(B).mod(P)

    private fun u(b: ByteArray, off: Int) = BigInteger(1, b.copyOfRange(off, off + 32))

    // affine, null = infinity. Slow and fine for a test.
    private fun add(p1: Pair<BigInteger, BigInteger>?, p2: Pair<BigInteger, BigInteger>?): Pair<BigInteger, BigInteger>? {
        if (p1 == null) return p2
        if (p2 == null) return p1
        val (x1, y1) = p1; val (x2, y2) = p2
        val l = if (x1 == x2) {
            if ((y1 + y2).mod(P).signum() == 0) return null
            x1.pow(2).multiply(BigInteger.valueOf(3)).add(A).multiply(y1.shiftLeft(1).modInverse(P)).mod(P)
        } else {
            (y2 - y1).multiply((x2 - x1).modInverse(P)).mod(P)
        }
        val x3 = (l.pow(2) - x1 - x2).mod(P)
        return x3 to (l.multiply(x1 - x3) - y1).mod(P)
    }

    private fun mul(k: BigInteger, p: Pair<BigInteger, BigInteger>): Pair<BigInteger, BigInteger>? {
        var acc: Pair<BigInteger, BigInteger>? = null
        for (i in k.bitLength() - 1 downTo 0) {
            acc = add(acc, acc)
            if (k.testBit(i)) acc = add(acc, p)
        }
        return acc
    }
}
