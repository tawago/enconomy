// sesign: Secure Enclave P-256 signer for sound-bound fixtures (dev spike).
//
//   sesign probe                      -> is SE available, can we make a key
//   sesign keygen <blobfile>          -> new SE key; writes the SE-wrapped handle
//                                        (dataRepresentation, only usable on this Mac)
//                                        to <blobfile>; prints {"pub_x","pub_y","key_kind"}
//   sesign sign <blobfile> <hex>      -> ECDSA P-256 over SHA-256(bytes(hex)), prints
//                                        {"r","s","digest"}; raw (not low-S normalized)
//   sesign --software ...             -> same, but CryptoKit software P256 key
//                                        (blobfile then holds the raw private scalar; dev only)
//
// CryptoKit hashes the message with SHA-256 before signing, so the signature is
// ECDSA over sha256(message). We also sign via the explicit digest API and check
// both verify, to make that explicit.
import CryptoKit
import Foundation

func hex(_ d: Data) -> String { d.map { String(format: "%02x", $0) }.joined() }
func unhex(_ s: String) -> Data {
    var d = Data(); var i = s.startIndex
    while i < s.endIndex {
        let j = s.index(i, offsetBy: 2)
        d.append(UInt8(s[i..<j], radix: 16)!); i = j
    }
    return d
}
func out(_ o: [String: Any]) {
    let j = try! JSONSerialization.data(withJSONObject: o, options: [.sortedKeys])
    print(String(data: j, encoding: .utf8)!)
}
func die(_ m: String) -> Never { FileHandle.standardError.write((m + "\n").data(using: .utf8)!); exit(1) }

var args = Array(CommandLine.arguments.dropFirst())
var software = false
if args.first == "--software" { software = true; args.removeFirst() }
guard let cmd = args.first else { die("usage: sesign [--software] probe|keygen <blob>|sign <blob> <hex>") }

func pubXY(_ raw: Data) -> [String: String] {  // rawRepresentation = x||y
    ["pub_x": hex(raw.prefix(32)), "pub_y": hex(raw.suffix(32))]
}

switch cmd {
case "probe":
    var o: [String: Any] = ["isAvailable": SecureEnclave.isAvailable]
    do {
        let k = try SecureEnclave.P256.Signing.PrivateKey()
        o["keygen"] = "ok"; o.merge(pubXY(k.publicKey.rawRepresentation)) { a, _ in a }
    } catch { o["keygen"] = "error: \(error)" }
    out(o)

case "keygen":
    guard args.count == 2 else { die("keygen <blobfile>") }
    let url = URL(fileURLWithPath: args[1])
    if software {
        let k = P256.Signing.PrivateKey()
        try! k.rawRepresentation.write(to: url, options: .atomic)
        var o: [String: Any] = pubXY(k.publicKey.rawRepresentation); o["key_kind"] = "software-fallback"; out(o)
    } else {
        do {
            let k = try SecureEnclave.P256.Signing.PrivateKey()
            try k.dataRepresentation.write(to: url, options: .atomic)
            var o: [String: Any] = pubXY(k.publicKey.rawRepresentation); o["key_kind"] = "secure-enclave"; out(o)
        } catch { die("secure enclave keygen failed: \(error)") }
    }

case "sign":
    guard args.count == 3 else { die("sign <blobfile> <hex>") }
    let blob = try! Data(contentsOf: URL(fileURLWithPath: args[1]))
    let msg = unhex(args[2])
    let digest = SHA256.hash(data: msg)
    let sig: P256.Signing.ECDSASignature
    let sig2: P256.Signing.ECDSASignature
    let pub: P256.Signing.PublicKey
    do {
        if software {
            let k = try P256.Signing.PrivateKey(rawRepresentation: blob)
            sig = try k.signature(for: msg); sig2 = try k.signature(for: digest); pub = k.publicKey
        } else {
            let k = try SecureEnclave.P256.Signing.PrivateKey(dataRepresentation: blob)
            sig = try k.signature(for: msg); sig2 = try k.signature(for: digest); pub = k.publicKey
        }
    } catch { die("sign failed: \(error)") }
    // Both must verify against the same digest: signing data == signing sha256(data).
    guard pub.isValidSignature(sig, for: digest), pub.isValidSignature(sig2, for: msg) else {
        die("self-check failed: data-signature and digest-signature disagree")
    }
    let raw = sig.rawRepresentation  // r||s, 32 bytes each
    out(["r": hex(raw.prefix(32)), "s": hex(raw.suffix(32)), "digest": hex(Data(digest))])

default:
    die("unknown command \(cmd)")
}
