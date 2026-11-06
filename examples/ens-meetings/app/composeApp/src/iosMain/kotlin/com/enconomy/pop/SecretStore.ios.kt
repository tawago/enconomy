@file:OptIn(ExperimentalForeignApi::class)

package com.enconomy.pop

import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.alloc
import kotlinx.cinterop.convert
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.usePinned
import kotlinx.cinterop.value
import platform.CoreFoundation.CFDataRef
import platform.CoreFoundation.CFErrorRefVar
import platform.CoreFoundation.CFRelease
import platform.CoreFoundation.CFTypeRefVar
import platform.CoreFoundation.kCFBooleanTrue
import platform.Foundation.CFBridgingRetain
import platform.Foundation.NSLog
import platform.Foundation.NSNumber
import platform.Foundation.numberWithInt
import platform.Security.SecItemAdd
import platform.Security.SecItemCopyMatching
import platform.Security.SecItemDelete
import platform.Security.SecKeyCreateWithData
import platform.Security.SecKeyVerifySignature
import platform.Security.SecRandomCopyBytes
import platform.Security.errSecItemNotFound
import platform.Security.errSecSuccess
import platform.Security.kSecAttrAccessible
import platform.Security.kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
import platform.Security.kSecAttrAccount
import platform.Security.kSecAttrKeyClass
import platform.Security.kSecAttrKeyClassPublic
import platform.Security.kSecAttrKeySizeInBits
import platform.Security.kSecAttrKeyType
import platform.Security.kSecAttrKeyTypeECSECPrimeRandom
import platform.Security.kSecAttrService
import platform.Security.kSecClass
import platform.Security.kSecClassGenericPassword
import platform.Security.kSecKeyAlgorithmECDSASignatureMessageX962SHA256
import platform.Security.kSecMatchLimit
import platform.Security.kSecMatchLimitOne
import platform.Security.kSecRandomDefault
import platform.Security.kSecReturnData
import platform.Security.kSecValueData

private const val SERVICE = "com.enconomy.pop.secret"

private fun log(msg: String) = NSLog("PopSecrets: ${msg.replace("%", "%%")}")

actual fun createSecretStore(): SecretStore = IosSecretStore()

/**
 * Keychain generic passwords (service [SERVICE], account = name), AfterFirstUnlockThisDeviceOnly: no iCloud
 * sync, not in backups restored to another device. Simulator only, when the keychain refuses
 * (test binary without entitlements): Prefs, like the device key's soft fallback.
 */
class IosSecretStore : SecretStore {
    private fun query(name: String, extra: CfDictBuilder.() -> Unit) = cfDict {
        put(kSecClass, kSecClassGenericPassword)
        putOwned(kSecAttrService, CFBridgingRetain(SERVICE))
        putOwned(kSecAttrAccount, CFBridgingRetain(name))
        extra()
    }

    override fun get(name: String): ByteArray? = memScoped {
        val out = alloc<CFTypeRefVar>()
        val st = query(name) {
            put(kSecReturnData, kCFBooleanTrue)
            put(kSecMatchLimit, kSecMatchLimitOne)
        }.use { SecItemCopyMatching(it, out.ptr) }
        @Suppress("UNCHECKED_CAST")
        if (st == errSecSuccess) return@memScoped copyData(out.value as CFDataRef?)
        if (st != errSecItemNotFound) log("keychain get $name: $st")
        if (isSimulator) Prefs.get("secret.$name")?.fromB64() else null
    }

    override fun put(name: String, value: ByteArray) {
        deleteKeychain(name)
        val st = query(name) {
            putData(kSecValueData, value)
            put(kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly)
        }.use { SecItemAdd(it, null) }
        if (st == errSecSuccess) {
            Prefs.set("secret.$name", null)
            return
        }
        if (!isSimulator) error("keychain add $name: $st")
        log("keychain add $name: $st, simulator: prefs")
        Prefs.set("secret.$name", value.toB64())
    }

    override fun delete(name: String) {
        deleteKeychain(name)
        Prefs.set("secret.$name", null)
    }

    private fun deleteKeychain(name: String) {
        val st = query(name) {}.use { SecItemDelete(it) }
        if (st != errSecSuccess && st != errSecItemNotFound) log("keychain delete $name: $st")
    }
}

actual fun secureRandomBytes(n: Int): ByteArray {
    val out = ByteArray(n)
    if (n == 0) return out
    val st = out.usePinned { SecRandomCopyBytes(kSecRandomDefault, n.convert(), it.addressOf(0)) }
    check(st == errSecSuccess) { "SecRandomCopyBytes: $st" }
    return out
}

actual fun ecdsaP256Verify(pub65: ByteArray, message: ByteArray, sig: ByteArray): Boolean {
    if (pub65.size != 65 || pub65[0] != 4.toByte() || sig.size != 64) return false
    return memScoped {
        val err = alloc<CFErrorRefVar>()
        val pd = cfData(pub65)
        val key = try {
            cfDict {
                put(kSecAttrKeyType, kSecAttrKeyTypeECSECPrimeRandom)
                put(kSecAttrKeyClass, kSecAttrKeyClassPublic)
                putOwned(kSecAttrKeySizeInBits, CFBridgingRetain(NSNumber.numberWithInt(256)))
            }.use { SecKeyCreateWithData(pd, it, err.ptr) }
        } finally {
            CFRelease(pd)
        }
        if (key == null) {
            err.value?.let { CFRelease(it) }
            return@memScoped false
        }
        val m = cfData(message)
        val s = cfData(rawRsToDer(sig))
        try {
            val ok = SecKeyVerifySignature(key, kSecKeyAlgorithmECDSASignatureMessageX962SHA256, m, s, err.ptr)
            err.value?.let { CFRelease(it) }
            ok
        } finally {
            CFRelease(m); CFRelease(s); CFRelease(key)
        }
    }
}
