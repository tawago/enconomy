@file:OptIn(ExperimentalForeignApi::class, BetaInteropApi::class, ExperimentalNativeApi::class)

package com.enconomy.pop

import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.alloc
import kotlinx.cinterop.convert
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.usePinned
import kotlinx.cinterop.value
import kotlin.concurrent.Volatile
import kotlin.experimental.ExperimentalNativeApi
import kotlin.native.ref.createCleaner
import platform.CoreFoundation.CFDataRef
import platform.CoreFoundation.CFDictionaryAddValue
import platform.CoreFoundation.CFDictionaryCreateMutable
import platform.CoreFoundation.CFDictionaryGetValue
import platform.CoreFoundation.CFDictionaryRef
import platform.CoreFoundation.CFErrorRefVar
import platform.CoreFoundation.CFMutableDictionaryRef
import platform.CoreFoundation.CFRelease
import platform.CoreFoundation.CFStringRef
import platform.CoreFoundation.CFTypeRef
import platform.CoreFoundation.CFTypeRefVar
import platform.CoreFoundation.kCFBooleanTrue
import platform.CoreFoundation.kCFTypeDictionaryKeyCallBacks
import platform.CoreFoundation.kCFTypeDictionaryValueCallBacks
import platform.DeviceCheck.DCAppAttestService
import platform.Foundation.CFBridgingRelease
import platform.Foundation.CFBridgingRetain
import platform.Foundation.NSBundle
import platform.Foundation.NSData
import platform.Foundation.NSError
import platform.Foundation.NSLog
import platform.Foundation.NSNumber
import platform.Foundation.NSProcessInfo
import platform.Foundation.create
import platform.Foundation.numberWithInt
import platform.Security.SecAccessControlCreateWithFlags
import platform.Security.SecItemCopyMatching
import platform.Security.SecItemDelete
import platform.Security.SecKeyCopyAttributes
import platform.Security.SecKeyCopyExternalRepresentation
import platform.Security.SecKeyCopyPublicKey
import platform.Security.SecKeyCreateRandomKey
import platform.Security.SecKeyCreateSignature
import platform.Security.SecKeyCreateWithData
import platform.Security.SecKeyRef
import platform.Security.errSecItemNotFound
import platform.Security.errSecSuccess
import platform.Security.kSecAccessControlPrivateKeyUsage
import platform.Security.kSecAttrAccessControl
import platform.Security.kSecAttrAccessible
import platform.Security.kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
import platform.Security.kSecAttrApplicationTag
import platform.Security.kSecAttrIsPermanent
import platform.Security.kSecAttrKeyClass
import platform.Security.kSecAttrKeyClassPrivate
import platform.Security.kSecAttrKeySizeInBits
import platform.Security.kSecAttrKeyType
import platform.Security.kSecAttrKeyTypeECSECPrimeRandom
import platform.Security.kSecAttrTokenID
import platform.Security.kSecAttrTokenIDSecureEnclave
import platform.Security.kSecClass
import platform.Security.kSecClassKey
import platform.Security.kSecKeyAlgorithmECDSASignatureMessageX962SHA256
import platform.Security.kSecPrivateKeyAttrs
import platform.Security.kSecReturnRef
import platform.darwin.DISPATCH_TIME_NOW
import platform.darwin.dispatch_semaphore_create
import platform.darwin.dispatch_semaphore_signal
import platform.darwin.dispatch_semaphore_wait
import platform.darwin.dispatch_time
import platform.posix.memcpy

actual fun createDeviceKeystore(): DeviceKeystore = IosDeviceKeystore()

/** No NSLog varargs: a Kotlin String through C varargs crashes. */
private fun log(msg: String) = NSLog("PopKeystore: ${msg.replace("%", "%%")}")

internal val isSimulator: Boolean get() = NSProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] != null

/** Info.plist PopAppAttest (else PopNfcReader), both = POP_PAID in Config.xcconfig. */
private val paidBuild: Boolean get() {
    val d = NSBundle.mainBundle.infoDictionary ?: return false
    val v = (d["PopAppAttest"] ?: d["PopNfcReader"]) as? String
    return v == "YES" || v == "1"
}

private const val SOFT_PREF = "key.soft"

/**
 * Contract §2.1 on iOS: P-256 in the Secure Enclave, keychain tag [KEY_ALIAS],
 * AfterFirstUnlockThisDeviceOnly + privateKeyUsage. Simulator only, when that fails: a software keychain
 * key, else (no keychain, e.g. the test binary) the raw key in Prefs; both report "software".
 * A real iPhone without a working SE surfaces the keygen error.
 * Attestation: no X.509 chain (chain = null). Paid builds add App Attest, see [AppAttestation].
 */
class IosDeviceKeystore : DeviceKeystore {
    override val platform: String get() = "ios"

    /** load() on main, generate()/delete() on Default. */
    @Volatile private var cached: IosDeviceKey? = null
    private val tag = KEY_ALIAS.encodeToByteArray()

    override fun load(): DeviceKey? {
        cached?.let { return it }
        val ref = keychainPrivate() ?: softPrivate() ?: return null
        return IosDeviceKey(ref).also { cached = it }
    }

    override fun delete() {
        cached = null
        val st = cfDict {
            put(kSecClass, kSecClassKey)
            putData(kSecAttrApplicationTag, tag)
            put(kSecAttrKeyType, kSecAttrKeyTypeECSECPrimeRandom)
        }.use { SecItemDelete(it) }
        if (st != errSecSuccess && st != errSecItemNotFound) log("keychain delete: $st")
        Prefs.set(SOFT_PREF, null)
    }

    override fun generate(challenge: ByteArray): GeneratedKey {
        delete()
        val ref = try {
            createKey(secureEnclave = true)
        } catch (e: IllegalStateException) {
            if (!isSimulator) throw IllegalStateException("secure enclave keygen failed: ${e.message}", e)
            log("SE keygen failed on simulator, software key: ${e.message}")
            try {
                createKey(secureEnclave = false)
            } catch (e2: IllegalStateException) {
                log("keychain unavailable, key in prefs: ${e2.message}")
                createSoftInPrefs()
            }
        }
        val key = IosDeviceKey(ref).also { cached = it }
        val att = if (paidBuild) appAttest(challenge, key.pubkey) else null
        log("generated ${key.deviceId} level=${key.securityLevel} appAttest=${att != null}")
        return GeneratedKey(key, chain = null, appAttest = att)
    }

    private fun createKey(secureEnclave: Boolean): SecKeyRef = memScoped {
        val err = alloc<CFErrorRefVar>()
        val acl = if (secureEnclave) {
            SecAccessControlCreateWithFlags(null, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly, kSecAccessControlPrivateKeyUsage, err.ptr)
                ?: error("access control: ${errText(err)}")
        } else null
        try {
            val priv = cfDict {
                put(kSecAttrIsPermanent, kCFBooleanTrue)
                putData(kSecAttrApplicationTag, tag)
                if (acl != null) put(kSecAttrAccessControl, acl) else put(kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly)
            }
            val ref = priv.use { p ->
                cfDict {
                    put(kSecAttrKeyType, kSecAttrKeyTypeECSECPrimeRandom)
                    putOwned(kSecAttrKeySizeInBits, CFBridgingRetain(NSNumber.numberWithInt(256)))
                    if (secureEnclave) put(kSecAttrTokenID, kSecAttrTokenIDSecureEnclave)
                    put(kSecPrivateKeyAttrs, p)
                }.use { SecKeyCreateRandomKey(it, err.ptr) }
            }
            ref ?: error(errText(err))
        } finally {
            if (acl != null) CFRelease(acl)
        }
    }

    private fun keychainPrivate(): SecKeyRef? = memScoped {
        val out = alloc<CFTypeRefVar>()
        val st = cfDict {
            put(kSecClass, kSecClassKey)
            putData(kSecAttrApplicationTag, tag)
            put(kSecAttrKeyType, kSecAttrKeyTypeECSECPrimeRandom)
            put(kSecAttrKeyClass, kSecAttrKeyClassPrivate)
            put(kSecReturnRef, kCFBooleanTrue)
        }.use { SecItemCopyMatching(it, out.ptr) }
        if (st != errSecSuccess) {
            if (st != errSecItemNotFound) log("keychain lookup: $st")
            return null
        }
        @Suppress("UNCHECKED_CAST")
        out.value as SecKeyRef?
    }

    /** Simulator only: 97-byte 04||X||Y||D in Prefs. */
    private fun createSoftInPrefs(): SecKeyRef = memScoped {
        val err = alloc<CFErrorRefVar>()
        val ref = cfDict {
            put(kSecAttrKeyType, kSecAttrKeyTypeECSECPrimeRandom)
            putOwned(kSecAttrKeySizeInBits, CFBridgingRetain(NSNumber.numberWithInt(256)))
        }.use { SecKeyCreateRandomKey(it, err.ptr) } ?: error("soft keygen: ${errText(err)}")
        val raw = copyData(SecKeyCopyExternalRepresentation(ref, err.ptr)) ?: error("soft export: ${errText(err)}")
        Prefs.set(SOFT_PREF, raw.toB64())
        ref
    }

    private fun softPrivate(): SecKeyRef? {
        if (!isSimulator) return null
        val raw = Prefs.get(SOFT_PREF)?.fromB64() ?: return null
        return memScoped {
            val err = alloc<CFErrorRefVar>()
            val data = cfData(raw)
            val ref = try {
                cfDict {
                    put(kSecAttrKeyType, kSecAttrKeyTypeECSECPrimeRandom)
                    put(kSecAttrKeyClass, kSecAttrKeyClassPrivate)
                    putOwned(kSecAttrKeySizeInBits, CFBridgingRetain(NSNumber.numberWithInt(256)))
                }.use { SecKeyCreateWithData(data, it, err.ptr) }
            } finally {
                CFRelease(data)
            }
            ref ?: run { log("soft key import: ${errText(err)}"); null }
        }
    }

    /**
     * App Attest (paid builds, real device): new App Attest key, attested over
     * clientDataHash = sha256(nonce32 || sha256(pubkey65)). Any failure -> null (unattested enroll).
     */
    private fun appAttest(nonce: ByteArray, pubkey65: ByteArray): AppAttestation? {
        val svc = DCAppAttestService.sharedService
        if (!svc.isSupported()) {
            log("app attest not supported"); return null
        }
        val keyId = awaitResult<String> { done -> svc.generateKeyWithCompletionHandler { id, e -> done(id, e) } }
            ?: return null
        val cdh = sha256(nonce + sha256(pubkey65)).toNSData()
        val obj = awaitResult<NSData> { done -> svc.attestKey(keyId, cdh) { d, e -> done(d, e) } } ?: return null
        return AppAttestation(keyId, obj.toByteArray())
    }
}

/** Blocks on a completion-handler call (never on the main queue: generate() runs on Dispatchers.Default). */
private fun <T : Any> awaitResult(call: ((T?, NSError?) -> Unit) -> Unit): T? {
    val sem = dispatch_semaphore_create(0)
    var res: T? = null
    var err: NSError? = null
    call { v, e -> res = v; err = e; dispatch_semaphore_signal(sem) }
    if (dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 30_000_000_000L)) != 0L) {
        log("app attest timed out"); return null
    }
    err?.let { log("app attest: ${it.localizedDescription}") }
    return res
}

/** Owns the +1 [priv]; released when this key is collected (a replaced key may still be signing). */
private class IosDeviceKey(private val priv: SecKeyRef) : DeviceKey {
    @Suppress("unused") private val cleaner = createCleaner(priv) { CFRelease(it) }

    override val pubkey: ByteArray = memScoped {
        val err = alloc<CFErrorRefVar>()
        val pub = SecKeyCopyPublicKey(priv) ?: error("no public key")
        try {
            copyData(SecKeyCopyExternalRepresentation(pub, err.ptr)) ?: error("pubkey export: ${errText(err)}")
        } finally {
            CFRelease(pub)
        }
    }.also { require(it.size == 65 && it[0] == 4.toByte()) { "pubkey not SEC1 uncompressed P-256" } }

    override val securityLevel: String by lazy {
        val attrs = SecKeyCopyAttributes(priv) ?: return@lazy "unknown"
        try {
            if (CFDictionaryGetValue(attrs, kSecAttrTokenID) != null) "secure_enclave" else "software"
        } finally {
            CFRelease(attrs)
        }
    }

    /** ECDSA P-256 SHA-256 over [message]; DER -> raw r||s. Low-s not required (§2.1). */
    override fun sign(message: ByteArray): ByteArray = memScoped {
        val err = alloc<CFErrorRefVar>()
        val data = cfData(message)
        val der = try {
            copyData(SecKeyCreateSignature(priv, kSecKeyAlgorithmECDSASignatureMessageX962SHA256, data, err.ptr))
        } finally {
            CFRelease(data)
        }
        derToRawRs(der ?: error("sign: ${errText(err)}"))
    }
}

// ---- CoreFoundation glue ----

internal class CfDictBuilder {
    val ref: CFMutableDictionaryRef =
        CFDictionaryCreateMutable(null, 0, kCFTypeDictionaryKeyCallBacks.ptr, kCFTypeDictionaryValueCallBacks.ptr)!!

    fun put(k: CFStringRef?, v: CFTypeRef?) = CFDictionaryAddValue(ref, k, v)

    /** Adds and drops our +1 (the dictionary retains). */
    fun putOwned(k: CFStringRef?, v: CFTypeRef?) {
        put(k, v); if (v != null) CFRelease(v)
    }

    fun putData(k: CFStringRef?, b: ByteArray) = putOwned(k, cfData(b))
}

internal fun cfDict(block: CfDictBuilder.() -> Unit): CFDictionaryRef = CfDictBuilder().apply(block).ref

internal inline fun <R> CFDictionaryRef.use(block: (CFDictionaryRef) -> R): R =
    try { block(this) } finally { CFRelease(this) }

/** +1 CFData; caller releases. */
@Suppress("UNCHECKED_CAST")
internal fun cfData(b: ByteArray): CFDataRef = CFBridgingRetain(b.toNSData()) as CFDataRef

/** Consumes a +1 CFData. */
internal fun copyData(d: CFDataRef?): ByteArray? = d?.let { (CFBridgingRelease(it) as NSData).toByteArray() }

internal fun errText(err: CFErrorRefVar): String =
    err.value?.let { (CFBridgingRelease(it) as? NSError)?.let { e -> "${e.domain} ${e.code} ${e.localizedDescription}" } } ?: "unknown error"

private fun ByteArray.toNSData(): NSData =
    if (isEmpty()) NSData() else usePinned { NSData.create(bytes = it.addressOf(0), length = size.convert()) }

private fun NSData.toByteArray(): ByteArray {
    val n = length.toInt()
    if (n == 0) return ByteArray(0)
    return ByteArray(n).also { out -> out.usePinned { memcpy(it.addressOf(0), bytes, length) } }
}
