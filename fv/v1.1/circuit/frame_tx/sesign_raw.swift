// Sign a raw 32-byte digest with a Secure Enclave P-256 key blob. Prints r||s hex, not low-S normalized.
// research/.../enclave/sesign always hashes first. The chain's P-256 entry checks the signature over the 32 bytes as given.
// CryptoKit's digest API only takes its own Digest types, so the 32 bytes are placed into a SHA256Digest.
// That relies on the struct's layout. The bytes are read back and compared, and the signature is checked here.
import CryptoKit
import Foundation

func unhex(_ s: String) -> Data {
    var d = Data(); var i = s.startIndex
    while i < s.endIndex { let j = s.index(i, offsetBy: 2); d.append(UInt8(s[i..<j], radix: 16)!); i = j }
    return d
}
let a = CommandLine.arguments
guard a.count == 3, a[2].count == 64 else { fatalError("usage: sesign_raw <blob> <64 hex digest>") }
let raw = unhex(a[2])
precondition(MemoryLayout<SHA256Digest>.size == 32)
var digest = SHA256.hash(data: Data())
withUnsafeMutableBytes(of: &digest) { $0.copyBytes(from: raw) }
precondition(Data(digest) == raw, "digest bytes did not land")
let k = try SecureEnclave.P256.Signing.PrivateKey(dataRepresentation: Data(contentsOf: URL(fileURLWithPath: a[1])))
let sig = try k.signature(for: digest)
precondition(k.publicKey.isValidSignature(sig, for: digest))
print(sig.rawRepresentation.map { String(format: "%02x", $0) }.joined())
