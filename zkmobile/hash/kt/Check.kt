package com.enconomy.pop.zk
import java.io.File

fun main(args: Array<String>) {
    val vj = File(args[0]).readText()
    val hexes = Regex("\"(0x[0-9a-f]+)\"").findAll(vj).map { it.groupValues[1] }.toList()
    fun sect(k: String): List<String> {
        val i = vj.indexOf("\"$k\"")
        val j = listOf("\"perm\"","\"hash_n_tag5\"","\"leaf\"","\"node\"","\"code\"","\"half\"","\"holder\"").map { vj.indexOf(it) }.filter { it > i }.minOrNull() ?: vj.length
        return Regex("\"(0x[0-9a-f]+)\"").findAll(vj.substring(i, j)).map { it.groupValues[1] }.toList()
    }
    val res = mutableListOf<Pair<String, Boolean>>()
    fun ck(n: String, a: Fr, e: String) { res.add(n to (a == Fr.fromHex(e))) }
    val p = Poseidon2Bn()
    val perm = sect("perm")
    for (q in 0 until 2) {
        val o = p.permute(perm.subList(8*q, 8*q+4).map { Fr.fromHex(it) })
        for (k in 0 until 4) ck("perm$q[$k]", o[k], perm[8*q+4+k])
    }
    val hn = sect("hash_n_tag5"); val xs = hn.subList(0, 7).map { Fr.fromHex(it) }
    for (k in 0..7) ck("hash_n len$k", OaHash.hashN(Fr.of(5), xs.subList(0, k)), hn[7 + k])
    val lv = sect("leaf")
    val ins = listOf(IntArray(1024) { (it * 7919 + 13) % 65536 }, IntArray(1024) { 32768 }, IntArray(1024) { 65535 })
    for (k in 0..2) ck("leaf$k", OaHash.leafHashU(ins[k]), lv[k])
    ck("leaf1 via int16", OaHash.leafHash(ShortArray(1024), 0), lv[1])
    val nd = sect("node"); ck("node", OaHash.nodeHash(nd.subList(0, 4).map { Fr.fromHex(it) }), nd[4])
    val tm = List(4) { k -> ByteArray(12000) { i -> ((i * 37 + k * 11 + 5) % 256).toByte() } }
    ck("code", OaHash.codeCommitmentU8(tm[0], tm[1], tm[2], tm[3]), sect("code")[0])
    val hc = sect("half"); ck("half hashN", OaHash.hashN(OaHash.TAG_HALF, hc.subList(0, 11).map { Fr.fromHex(it) }), hc[11])
    val t128 = Fr.fromHex("ffffffffffffffffffffffffffffffff")
    val xo = ByteArray(32).also { val a = (t128 - Fr.ONE).toBytes(); a.copyInto(it, 0, 16, 32); it[31] = 7 }
    val xpB = ("0123456789abcdef0123456789abcdef" + "fedcba9876543210fedcba9876543210").chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    ck("half api", OaHash.halfCommit(t128, Fr.fromHex(hc[1]), 3, true, 48000, -45042, Fr.fromHex("deadbeefcafebabe"), xo, xpB), hc[11])
    val ho = sect("holder")
    ck("holder opt3", OaHash.holderCommitOpt3(Fr.fromHex(ho[0])), ho[1])
    ck("holder sp tag11", OaHash.holderCommitSp(Fr.fromHex(ho[0]), Fr.of(11)), ho[2])

    // real fixture
    val toml = File(args[1]).readText()
    fun arr(n: String) = Regex("^$n = \\[(.*?)\\]$", RegexOption.MULTILINE).find(toml)!!.groupValues[1].split(",").map { it.trim().trim('"') }
    val cap = arr("cap").map { (it.toInt() - 32768).toShort() }.toShortArray()
    var n = cap.size; while (n > 0 && cap[n - 1].toInt() == 0) n--
    val x = cap.copyOf(n)
    val fx = File(args[2]).readText()
    fun fv(k: String) = Regex("\"$k\": \"(0x[0-9a-f]+)\"").find(fx)!!.groupValues[1]
    OaHash.recTree(x) // warm-up
    var t0 = System.nanoTime(); val tree = OaHash.recTree(x); val tTree = (System.nanoTime() - t0) / 1e9
    ck("fixture rec_root", tree.root, fv("root")); ck("fixture leaf0", tree.levels[0][0], fv("leaf0")); ck("fixture leaf255", tree.levels[0][255], fv("leaf_last"))
    val t = listOf("c_is", "c_qs", "c_ip", "c_qp").map { k -> arr(k).map { it.toInt().toByte() }.toByteArray() }
    t0 = System.nanoTime(); val cc = OaHash.codeCommitmentU8(t[0], t[1], t[2], t[3]); val tCode = (System.nanoTime() - t0) / 1e9
    ck("fixture code", cc, fv("code"))
    val s8 = t.map { a -> ByteArray(a.size) { i -> ((a[i].toInt() and 0xFF) - 128).toByte() } }
    ck("fixture code int8 api", OaHash.codeCommitment(s8[0], s8[1], s8[2], s8[3]), fv("code"))
    for (side in listOf("a", "b")) ck("fixture half_${side.uppercase()}", OaHash.hashN(OaHash.TAG_HALF, arr("hc_$side").map { Fr.fromDecimal(it) }), fv("half_${side.uppercase()}"))
    for ((k, ok) in res) println("${k.padEnd(24)} ${if (ok) "ok" else "MISMATCH"}")
    println("samples $n, JVM rec tree ${"%.3f".format(tTree)} s, code ${"%.3f".format(tCode)} s")
    println(if (res.all { it.second }) "ALL MATCH (${res.size})" else "MISMATCH")
}
