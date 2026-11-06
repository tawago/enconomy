@file:OptIn(ExperimentalForeignApi::class)

package com.enconomy.pop

import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.alloc
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import platform.CoreFoundation.CFRelease
import platform.CoreFoundation.CFErrorRefVar
import platform.Security.SecKeyCreateSignature
import platform.Security.SecKeyIsAlgorithmSupported
import platform.Security.SecKeyRef
import platform.Security.kSecKeyAlgorithmECDSASignatureDigestX962SHA256
import platform.Security.kSecKeyOperationTypeSign

/**
 * Kotlin/Native spike of the iOS frame key, readable on its own. Needs the cfData / copyData / errText
 * glue from DeviceKeystore.ios.kt, so it doesn't compile standalone. The patch (../patch/app.patch)
 * folds this method into IosDeviceKey instead (IosDeviceKey : DeviceKey, FrameKey), which keeps the
 * SecKeyRef owned by one object. That patched version is the one that compiled for iosSimulatorArm64.
 *
 * No new key on iOS: SecKey picks the algorithm at sign time, and a Secure Enclave P-256 key
 * created for kSecAccessControlPrivateKeyUsage can sign with any ECDSA X9.62 variant.
 * "DigestX962SHA256" means: input is already a SHA-256-sized digest, sign it as-is. The SE does not
 * check that the 32 bytes really came from SHA-256, so a keccak sig_hash is fine.
 *
 * UNTESTED on an iPhone. On macOS (M2) the same API works for a software key and for an ephemeral
 * Secure Enclave key (ios/sign_digest.swift). iPhone SE, a persistent keychain key, and the
 * existing enrolled pop-device-v1 key are still unproven.
 */
internal class IosFrameKey(
    /** Borrowed from IosDeviceKey, which owns and releases it. */
    private val priv: SecKeyRef,
    override val pubkey: ByteArray,
    override val securityLevel: String,
) : FrameKey {
    override fun signDigest(digest32: ByteArray): ByteArray = memScoped {
        FrameSig.requireDigest(digest32)
        check(SecKeyIsAlgorithmSupported(priv, kSecKeyOperationTypeSign, kSecKeyAlgorithmECDSASignatureDigestX962SHA256)) {
            "key does not support ECDSASignatureDigestX962SHA256"
        }
        val err = alloc<CFErrorRefVar>()
        val data = cfData(digest32)
        val der = try {
            copyData(SecKeyCreateSignature(priv, kSecKeyAlgorithmECDSASignatureDigestX962SHA256, data, err.ptr))
        } finally {
            CFRelease(data)
        }
        FrameSig.normalizeLowS(derToRawRs(der ?: error("signDigest: ${errText(err)}")))
    }
}
