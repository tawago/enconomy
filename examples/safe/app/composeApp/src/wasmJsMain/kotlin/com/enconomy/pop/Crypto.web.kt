package com.enconomy.pop

/**
 * Web device key: software P-256 in localStorage ("pop.key.sk", hex). Demo tier only: the server takes it as
 * platform "web", security level "software", no attestation chain.
 */
private const val SK_KEY = "pop.key.sk"

private fun p256RandomSk(c: JsAny): String =
    js("Array.from(c.utils.randomPrivateKey(), x => x.toString(16).padStart(2, '0')).join('')")

private fun p256Pub(c: JsAny, skHex: String): String =
    js("Array.from(c.getPublicKey(Uint8Array.from(skHex.match(/../g), h => parseInt(h, 16)), false), x => x.toString(16).padStart(2, '0')).join('')")

/** Signs a 32-byte digest; raw r||s hex (64 bytes). */
private fun p256SignHash(c: JsAny, skHex: String, hashHex: String): String =
    js("Array.from(c.sign(Uint8Array.from(hashHex.match(/../g), h => parseInt(h, 16)), Uint8Array.from(skHex.match(/../g), h => parseInt(h, 16)), { lowS: false }).toCompactRawBytes(), x => x.toString(16).padStart(2, '0')).join('')")

private fun p256VerifyHash(c: JsAny, pubHex: String, hashHex: String, sigHex: String): Boolean =
    js("(function(){ try { const b = s => Uint8Array.from(s.match(/../g), h => parseInt(h, 16)); return c.verify(c.Signature.fromCompact(b(sigHex)), b(hashHex), b(pubHex), { lowS: false }); } catch (e) { return false; } })()")

class WebDeviceKey(private val skHex: String) : DeviceKey {
    override val pubkey: ByteArray = p256Pub(p256, skHex).hexToBytes()
    override val securityLevel: String get() = "software"
    override fun sign(message: ByteArray): ByteArray = p256SignHash(p256, skHex, sha256(message).toHex()).hexToBytes()
}

class WebDeviceKeystore : DeviceKeystore {
    override val platform: String get() = "web"

    override fun load(): DeviceKey? =
        jsStorageGet(SK_KEY)?.takeIf { it.length == 64 }?.let { runCatching { WebDeviceKey(it) }.getOrNull() }

    override fun generate(challenge: ByteArray): GeneratedKey {
        val sk = p256RandomSk(p256)
        jsStorageSet(SK_KEY, sk)
        return GeneratedKey(WebDeviceKey(sk), chain = null)
    }

    override fun delete() = jsStorageRemove(SK_KEY)
}

actual fun createDeviceKeystore(): DeviceKeystore = WebDeviceKeystore()

actual fun secureRandomBytes(n: Int): ByteArray = if (n == 0) ByteArray(0) else jsRandomHex(n).hexToBytes()

actual fun ecdsaP256Verify(pub65: ByteArray, message: ByteArray, sig: ByteArray): Boolean {
    if (pub65.size != 65 || sig.size != 64) return false
    return p256VerifyHash(p256, pub65.toHex(), sha256(message).toHex(), sig.toHex())
}

/** localStorage, base64, namespace "pop.secret.". Not hardware protected (web demo tier). */
class WebSecretStore : SecretStore {
    override fun get(name: String): ByteArray? = jsStorageGet("pop.secret.$name")?.let { runCatching { it.fromB64() }.getOrNull() }
    override fun put(name: String, value: ByteArray) {
        jsStorageSet("pop.secret.$name", value.toB64())
        check(get(name)?.contentEquals(value) == true) { "localStorage refused the secret" }
    }
    override fun delete(name: String) = jsStorageRemove("pop.secret.$name")
}

actual fun createSecretStore(): SecretStore = WebSecretStore()
