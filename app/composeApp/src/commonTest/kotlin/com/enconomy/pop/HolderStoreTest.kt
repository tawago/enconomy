package com.enconomy.pop

import com.enconomy.pop.zk.Holder
import com.enconomy.pop.zk.Sbcred3
import com.enconomy.pop.zk.StoredCredential
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class MemSecrets : SecretStore {
    val m = mutableMapOf<String, ByteArray>()
    override fun get(name: String) = m[name]?.copyOf()
    override fun put(name: String, value: ByteArray) { m[name] = value.copyOf() }
    override fun delete(name: String) { m.remove(name) }
}

class MemKv : KeyValue {
    val m = mutableMapOf<String, String>()
    override fun get(key: String) = m[key]
    override fun set(key: String, value: String?) { if (value == null) m.remove(key) else m[key] = value }
}

class HolderStoreTest {
    private val pubA = byteArrayOf(4) + ByteArray(64) { (it + 1).toByte() }
    private val pubB = byteArrayOf(4) + ByteArray(64) { (it + 2).toByte() }
    private val issuer = byteArrayOf(4) + ByteArray(64) { 7 }

    @Test fun secretCreatedOnceAndKeptInSecretStore() {
        val sec = MemSecrets()
        val kv = MemKv()
        var calls = 0
        val h = HolderStore(sec, kv) { n -> calls++; ByteArray(n) { (it * 3 + 1).toByte() } }
        assertNull(h.secret())
        val s1 = h.loadOrCreate()
        val s2 = h.loadOrCreate()
        assertEquals(1, calls)
        assertEquals(Holder.SECRET_LEN, s1.size)
        assertContentEquals(s1, s2)
        assertContentEquals(s1, sec.m[HolderStore.SECRET])
        assertTrue(kv.m.isEmpty(), "secret must not reach plain prefs")
        assertEquals(Holder.commit(s1), h.commit())
        // a new store over the same storage sees the same secret
        assertContentEquals(s1, HolderStore(sec, kv) { error("no new secret") }.loadOrCreate())
    }

    @Test fun malformedSecretIsReplaced() {
        val sec = MemSecrets().also { it.m[HolderStore.SECRET] = ByteArray(5) }
        val h = HolderStore(sec, MemKv()) { ByteArray(it) { 9 } }
        assertContentEquals(ByteArray(31) { 9 }, h.loadOrCreate())
    }

    @Test fun unpersistedSecretFails() {
        val lossy = object : SecretStore {
            override fun get(name: String): ByteArray? = null
            override fun put(name: String, value: ByteArray) {}
            override fun delete(name: String) {}
        }
        assertFailsWith<IllegalStateException> { HolderStore(lossy, MemKv()) { ByteArray(it) }.commit() }
    }

    @Test fun realRandom() {
        val x = secureRandomBytes(31)
        val y = secureRandomBytes(31)
        assertEquals(31, x.size)
        assertFalse(x.contentEquals(y))
    }

    @Test fun credentialRoundTrip() {
        val kv = MemKv()
        val h = HolderStore(MemSecrets(), kv) { ByteArray(it) { 1 } }
        val commit = h.commit().toBytes()
        val cred = Sbcred3.build(pubA, 1792947305, commit)
        val sig = ByteArray(64) { 3 }
        h.saveCredential(StoredCredential(cred, sig, issuer))
        val got = assertNotNull(h.credential(pubA))
        assertContentEquals(cred.bytes, got.cred.bytes)
        assertContentEquals(sig, got.sig)
        assertContentEquals(issuer, got.issuerPub)
        assertEquals(1792947305, got.expiry)
        assertNotNull(h.credential())
        assertNull(h.credential(pubB), "credential of another key")
        kv.m["cred3.sig"] = "AAAA"
        assertNull(h.credential(pubA), "malformed")
        h.clearCredential()
        assertTrue(kv.m.isEmpty())
        assertNull(h.credential())
    }

    @Test fun wipe() {
        val sec = MemSecrets()
        val h = HolderStore(sec, MemKv()) { ByteArray(it) { 1 } }
        h.loadOrCreate()
        h.wipe()
        assertTrue(sec.m.isEmpty())
    }

    @Test fun enrollReqHolderCommit() {
        val base = EnrollReq("n", "d", "p", "x", "m", "tee", null)
        assertFalse("holder_commit" in popJson.encodeToString(EnrollReq.serializer(), base))
        val s = popJson.encodeToString(EnrollReq.serializer(), base.copy(holder_commit = "ab".repeat(32)))
        assertTrue("\"holder_commit\":\"${"ab".repeat(32)}\"" in s)
    }

    @Test fun enrollRespCredential() {
        val r = popJson.decodeFromString(
            EnrollResp.serializer(),
            """{"device_id":"d","attested":false,"credential":{"format":"SBcred3","cred_b64":"QQ==","sig_b64":"Qg==","expiry":5,"issuer_pubkey":"04"}}""",
        )
        assertEquals(5, r.credential?.expiry)
        assertNull(popJson.decodeFromString(EnrollResp.serializer(), """{"device_id":"d"}""").credential)
    }

    @Test fun issuerFromConfig() {
        val hex = issuer.toHex()
        val cfg = popJson.parseToJsonElement("""{"proto":"pop-v1","issuer":{"alg":"ES256","pubkey":"$hex"}}""")
        assertContentEquals(issuer, issuerPubkeyOf(cfg as kotlinx.serialization.json.JsonObject))
        assertNull(issuerPubkeyOf(popJson.parseToJsonElement("""{"proto":"pop-v1"}""") as kotlinx.serialization.json.JsonObject))
        assertNull(issuerPubkeyOf(popJson.parseToJsonElement("""{"issuer":{"pubkey":"04ab"}}""") as kotlinx.serialization.json.JsonObject))
    }

    @Test fun unixDay() {
        assertEquals("1970-01-01", formatUnixDay(0))
        assertEquals("2000-02-29", formatUnixDay(951782400))
        assertEquals("2026-10-25", formatUnixDay(1792947305))
    }
}
