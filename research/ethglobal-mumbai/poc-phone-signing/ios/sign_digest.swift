// macOS stand-in for the iOS frame-key path. Same Security.framework calls the app makes on iOS:
// SecKeyCreateRandomKey (P-256) + SecKeyCreateSignature(.ecdsaSignatureDigestX962SHA256, 32 bytes).
// Keys are ephemeral (kSecAttrIsPermanent = false), nothing touches the keychain.
// Also tries a Secure Enclave key; on a CLI binary without entitlements that usually fails, and we
// just record the error.
//
// Usage: swiftc -O sign_digest.swift -o /tmp/x && /tmp/x <count> > ../vectors/macos-seckey.json
import Foundation
import Security

func hex(_ d: Data) -> String { d.map { String(format: "%02x", $0) }.joined() }

func randomDigest() -> Data {
    var b = [UInt8](repeating: 0, count: 32)
    precondition(SecRandomCopyBytes(kSecRandomDefault, 32, &b) == errSecSuccess)
    return Data(b)
}

func makeKey(secureEnclave: Bool) -> (SecKey?, String) {
    var attrs: [String: Any] = [
        kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
        kSecAttrKeySizeInBits as String: 256,
        kSecPrivateKeyAttrs as String: [kSecAttrIsPermanent as String: false],
    ]
    if secureEnclave {
        var e: Unmanaged<CFError>?
        guard let acl = SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly, .privateKeyUsage, &e) else {
            return (nil, "acl: \(e!.takeRetainedValue())")
        }
        attrs[kSecAttrTokenID as String] = kSecAttrTokenIDSecureEnclave
        attrs[kSecPrivateKeyAttrs as String] = [kSecAttrIsPermanent as String: false, kSecAttrAccessControl as String: acl]
    }
    var err: Unmanaged<CFError>?
    guard let k = SecKeyCreateRandomKey(attrs as CFDictionary, &err) else {
        return (nil, "\(err!.takeRetainedValue())")
    }
    return (k, "ok")
}

func sign(_ k: SecKey, _ alg: SecKeyAlgorithm, _ d: Data) -> Data? {
    var err: Unmanaged<CFError>?
    guard let s = SecKeyCreateSignature(k, alg, d as CFData, &err) else {
        FileHandle.standardError.write("sign failed: \(err!.takeRetainedValue())\n".data(using: .utf8)!)
        return nil
    }
    return s as Data
}

func run(_ k: SecKey, _ label: String, _ count: Int) -> [String: Any] {
    let pub = SecKeyCopyExternalRepresentation(SecKeyCopyPublicKey(k)!, nil)! as Data // 04||X||Y
    let supported = SecKeyIsAlgorithmSupported(k, .sign, .ecdsaSignatureDigestX962SHA256)
    var vecs: [[String: String]] = []
    for _ in 0..<count {
        let d = randomDigest()
        guard let der = sign(k, .ecdsaSignatureDigestX962SHA256, d) else { continue }
        // message mode over the same 32 bytes: what the app does today. Must NOT verify against d.
        let derMsg = sign(k, .ecdsaSignatureMessageX962SHA256, d) ?? Data()
        vecs.append(["digest": hex(d), "der": hex(der), "derMessageMode": hex(derMsg)])
    }
    // same check the app's securityLevel uses: a token id is present only for SE-backed keys
    let attrs = SecKeyCopyAttributes(k) as? [String: Any] ?? [:]
    let token = attrs[kSecAttrTokenID as String].map { "\($0)" } ?? "none"
    return ["key": label, "pub": hex(pub), "digestAlgSupported": supported, "tokenID": token, "vectors": vecs]
}

let count = CommandLine.arguments.count > 1 ? Int(CommandLine.arguments[1])! : 64
var keys: [[String: Any]] = []
let (soft, softNote) = makeKey(secureEnclave: false)
if let soft = soft { keys.append(run(soft, "software", count)) }
let (se, seNote) = makeKey(secureEnclave: true)
if let se = se { keys.append(run(se, "secure_enclave", count)) }
let out: [String: Any] = [
    "source": "macOS Security.framework, \(ProcessInfo.processInfo.operatingSystemVersionString)",
    "softwareKeygen": softNote,
    "secureEnclaveKeygen": seNote,
    "keys": keys,
]
let json = try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(json)
