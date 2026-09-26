// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
/// Safe owner backed by a phone hardware P-256 key (Android Keystore / iOS Secure Enclave).
/// Phone signs the 32-byte safeTxHash with SHA256withECDSA, so digest = sha256(safeTxHash).
/// signature = r(32) || s(32)
contract P256Owner {
    uint256 public immutable x; uint256 public immutable y;
    constructor(uint256 _x, uint256 _y) { x = _x; y = _y; }
    function _ok(bytes32 h, bytes memory sig) internal view returns (bool) {
        if (sig.length != 64) return false;
        (bytes32 r, bytes32 s) = abi.decode(sig, (bytes32, bytes32));
        (bool ok, bytes memory ret) = address(0x100).staticcall(abi.encode(sha256(abi.encodePacked(h)), r, s, x, y));
        return ok && ret.length == 32 && abi.decode(ret, (uint256)) == 1;
    }
    // EIP-1271 (Safe 1.5.0)
    function isValidSignature(bytes32 h, bytes memory sig) external view returns (bytes4) {
        return _ok(h, sig) ? bytes4(0x1626ba7e) : bytes4(0xffffffff);
    }
    // legacy (Safe 1.3.0/1.4.1): data = EIP-712 preimage 0x1901||domain||struct
    function isValidSignature(bytes memory data, bytes memory sig) external view returns (bytes4) {
        return _ok(keccak256(data), sig) ? bytes4(0x20c13b0b) : bytes4(0xffffffff);
    }
}
