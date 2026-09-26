// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// Server P-256 attestation helpers (spec 01 §8.2). sha256 digest, P-256 ECDSA over the prehash, raw r||s.
library PopAttest {
    address internal constant P256 = address(0x100); // RIP-7212 / EIP-7951, needs evm_version osaka locally

    /// failure = EMPTY returndata (not 0), so check length. High-s is accepted: never key replay on sig bytes.
    function p256(bytes32 h, bytes32 r, bytes32 s, uint256 qx, uint256 qy) internal view returns (bool ok) {
        (bool c, bytes memory out) = P256.staticcall(abi.encode(h, r, s, qx, qy));
        ok = c && out.length == 32 && uint256(bytes32(out)) == 1;
    }

    /// preimage (199 B) = "pop-safe-v2" | u256 chainId | safe | safeTxHash | pairTag | devA | devB | u64 expiry
    function safeDigest(
        uint256 chainId,
        address safe,
        bytes32 safeTxHash,
        bytes32 pairTag,
        bytes32 devA,
        bytes32 devB,
        uint64 expiry
    ) internal pure returns (bytes32) {
        return sha256(abi.encodePacked("pop-safe-v2", chainId, safe, safeTxHash, pairTag, devA, devB, expiry));
    }

    function pairTagOf(uint256 nA, uint256 nB) internal pure returns (bytes32) {
        (uint256 lo, uint256 hi) = nA < nB ? (nA, nB) : (nB, nA);
        return sha256(abi.encodePacked("pop-pair-v1", lo, hi));
    }
}
