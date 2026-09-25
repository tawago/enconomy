package com.enconomy.pop

/**
 * TODO(key lane): Secure Enclave P-256 (kSecAttrTokenIDSecureEnclave), App Attest when the
 * paid entitlement is present, else an unattested key (chain = null).
 */
actual fun createDeviceKeystore(): DeviceKeystore = IosDeviceKeystore()

class IosDeviceKeystore : DeviceKeystore {
    override fun load(): DeviceKey? = null
    override fun generate(challenge: ByteArray): GeneratedKey = error("iOS keystore not implemented")
    override fun delete() {}
}
