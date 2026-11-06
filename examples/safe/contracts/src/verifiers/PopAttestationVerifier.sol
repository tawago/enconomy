// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IPopPresenceVerifier} from "../interfaces/IPopPresenceVerifier.sol";
import {PopAttest} from "../lib/PopAttest.sol";

/// Presence = the PoP server's P-256 attestation, format `pop-safe-v2` (spec 01 §8.2), exactly the server's
/// 172 B tail: pairTag(32) | devA(32) | devB(32) | expiry(u64 BE, 8) | r(32) | s(32) | "POP2"(4).
/// The server signs only after NEAR, two distinct verified World ID humans (pairTag) and attested devices.
/// Stateless. Works today; the Noir verifier replaces it once the ZK lane ships.
contract PopAttestationVerifier is IPopPresenceVerifier {
    bytes4 internal constant MAGIC = 0x504f5032; // "POP2"
    uint256 public constant TAIL = 172;

    error BadAttestation();
    error Expired();

    function digest(
        uint256 chainId,
        address safe,
        bytes32 safeTxHash,
        bytes32 pairTag,
        bytes32 devA,
        bytes32 devB,
        uint64 expiry
    ) public pure returns (bytes32) {
        return PopAttest.safeDigest(chainId, safe, safeTxHash, pairTag, devA, devB, expiry);
    }

    function verifyPresence(address safe, bytes32 safeTxHash, uint256 qx, uint256 qy, bytes calldata p)
        external
        view
        returns (bytes32 devA, bytes32 devB)
    {
        if (p.length != TAIL || bytes4(p[168:172]) != MAGIC) revert BadAttestation();
        bytes32 pairTag = bytes32(p[0:32]);
        devA = bytes32(p[32:64]);
        devB = bytes32(p[64:96]);
        uint64 expiry = uint64(bytes8(p[96:104]));
        bytes32 d = PopAttest.safeDigest(block.chainid, safe, safeTxHash, pairTag, devA, devB, expiry);
        if (!PopAttest.p256(d, bytes32(p[104:136]), bytes32(p[136:168]), qx, qy)) revert BadAttestation();
        if (block.timestamp > expiry) revert Expired();
    }
}
