package com.enconomy.pop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class PairingIosTest {
    /** Finder pattern at (x0, y0): 7x7 dark ring, light ring, 3x3 dark core, light separator. */
    private fun assertFinder(m: QrMatrix, x0: Int, y0: Int) {
        for (y in -1..7) for (x in -1..7) {
            // ring index from the outside: 0 = dark edge, 1 = light, 2..3 = dark core, -1 = separator
            val ring = if (x < 0 || y < 0 || x > 6 || y > 6) -1 else minOf(x, 6 - x, minOf(y, 6 - y))
            val want = ring == 0 || ring >= 2
            val px = x0 + x
            val py = y0 + y
            if (px !in 0 until m.n || py !in 0 until m.n) continue
            assertEquals(want, m.dark[py * m.n + px], "finder ($x0,$y0) at ($x,$y)")
        }
    }

    @Test
    fun qrMatrixHasFinderPatterns() {
        val text = "pop1:" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdEfGhIjKlMnOpQrStUvWxYz0"
        val m = assertNotNull(qrMatrix(text))
        val q = 2
        val side = m.n - 2 * q
        assertTrue(side >= 21 && (side - 17) % 4 == 0, "side $side")
        // quiet zone light
        for (i in 0 until m.n) for (k in 0 until q) {
            assertTrue(!m.dark[k * m.n + i] && !m.dark[(m.n - 1 - k) * m.n + i], "quiet row")
            assertTrue(!m.dark[i * m.n + k] && !m.dark[i * m.n + m.n - 1 - k], "quiet col")
        }
        assertFinder(m, q, q)
        assertFinder(m, q + side - 7, q)
        assertFinder(m, q, q + side - 7)
        // bottom-right is data, not a finder: not all dark
        val dark = m.dark.count { it }
        assertTrue(dark in (side * side / 4)..(side * side * 3 / 4), "dark $dark of ${side * side}")
    }
}
