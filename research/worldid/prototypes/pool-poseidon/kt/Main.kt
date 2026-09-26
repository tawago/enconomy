import com.enconomy.pop.zk.*
import java.io.File
fun main() {
    val j = File("golden.json").readText()
    val re = Regex("\"name\": \"([^\"]+)\",\\s*\"t\": \\d+,\\s*\"in\": \\[([^\\]]*)\\],\\s*\"out\": \"0x([0-9a-f]+)\"")
    var bad = 0; var n = 0
    for (m in re.findAll(j)) {
        val ins = Regex("0x([0-9a-f]+)").findAll(m.groupValues[2]).map { BigNat.fromHex(it.groupValues[1]) }.toList()
        val got = PoseidonBn254.hash(ins); val want = BigNat.fromHex(m.groupValues[3]); n++
        if (got != want) { bad++; println("MISMATCH ${m.groupValues[1]}") }
    }
    val x = listOf(BigNat.of(1), BigNat.of(2), BigNat.of(3)); repeat(20) { PoseidonBn254.hash(x) }
    val t0 = System.nanoTime(); repeat(50) { PoseidonBn254.hash(x) }; val us = (System.nanoTime() - t0) / 50 / 1000
    println(if (bad == 0 && n > 0) "KT ALL AGREE ($n cases), T4 ${us} us/hash JVM" else "KT FAIL $bad/$n")
}
