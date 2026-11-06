// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// The one context-binding formula (spec 01 §5). session_nonce binds a PoP session to
/// (chain, consumer, ctxHash). SAFE: consumer = the Safe proxy, ctxHash = safeTxHash.
/// Preimage is exactly 192 bytes: DOMAIN(hash, not string) | chainId | consumer | ctxHash | u64 notBefore | bytes16 sid.
library PopCtx {
    bytes32 internal constant DOMAIN = 0x2c71bde9118937099ebb172d5845794f571cc2982d44a563b229d1ea0db2af2f; // keccak256("pop-ctx-v1")

    function nonce(uint256 chainId, address consumer, bytes32 ctxHash, uint64 notBefore, bytes16 sid)
        internal
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(DOMAIN, chainId, consumer, ctxHash, notBefore, sid));
    }

    /// World ID signal hash for role 0x41 'A' / 0x42 'B'.
    function signalHash(bytes32 n, bytes1 role) internal pure returns (uint256) {
        return uint256(keccak256(abi.encodePacked(n, role))) >> 8;
    }

    /// keccak256("pop:" || lowercase hex32(sid)) >> 8
    function actionOf(bytes16 sid) internal pure returns (uint256) {
        bytes memory s = new bytes(36);
        s[0] = "p";
        s[1] = "o";
        s[2] = "p";
        s[3] = ":";
        bytes16 hexd = "0123456789abcdef";
        for (uint256 i = 0; i < 16; ++i) {
            uint8 b = uint8(sid[i]);
            s[4 + 2 * i] = hexd[b >> 4];
            s[5 + 2 * i] = hexd[b & 0x0f];
        }
        return uint256(keccak256(s)) >> 8;
    }

    /// Noir circuits carry the nonce as two 128-bit fields: hi = bytes [0:16], lo = bytes [16:32].
    function split(bytes32 n) internal pure returns (bytes32 hi, bytes32 lo) {
        hi = bytes32(uint256(n) >> 128);
        lo = bytes32(uint256(uint128(uint256(n))));
    }
}
