package com.enconomy.pop

import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertNull

/** Keychain (or, in the unentitled test binary, the simulator prefs fallback). */
class SecretStoreIosTest {
    private val name = "test.secret"
    private val store = createSecretStore()

    @AfterTest fun cleanup() = store.delete(name)

    @Test fun roundTrip() {
        store.delete(name)
        assertNull(store.get(name))
        val v = secureRandomBytes(31)
        store.put(name, v)
        assertContentEquals(v, store.get(name))
        val w = secureRandomBytes(31)
        store.put(name, w)
        assertContentEquals(w, store.get(name))
        store.delete(name)
        assertNull(store.get(name))
    }

    @Test fun holderOverKeychain() {
        val kv = object : KeyValue {
            val m = mutableMapOf<String, String>()
            override fun get(key: String) = m[key]
            override fun set(key: String, value: String?) { if (value == null) m.remove(key) else m[key] = value }
        }
        val secrets = object : SecretStore by store {
            // every holder name maps to the test item
            override fun get(name: String) = store.get(this@SecretStoreIosTest.name)
            override fun put(name: String, value: ByteArray) = store.put(this@SecretStoreIosTest.name, value)
            override fun delete(name: String) = store.delete(this@SecretStoreIosTest.name)
        }
        val s = HolderStore(secrets, kv).loadOrCreate()
        assertContentEquals(s, HolderStore(secrets, kv) { error("no new secret") }.loadOrCreate())
    }
}
