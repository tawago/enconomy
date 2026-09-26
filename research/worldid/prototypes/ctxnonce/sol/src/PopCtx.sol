// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
library PopCtx {
    bytes32 internal constant DOMAIN = keccak256("pop-ctx-v1");
    function sessionNonce(uint256 chainId, address consumer, bytes32 ctxHash, uint64 notBefore, bytes16 sid)
        internal pure returns (bytes32)
    { return keccak256(abi.encode(DOMAIN, chainId, consumer, ctxHash, notBefore, sid)); }
    function signalHash(bytes32 nonce, bytes1 role) internal pure returns (uint256) {
        return uint256(keccak256(abi.encodePacked(nonce, role))) >> 8;
    }
}
