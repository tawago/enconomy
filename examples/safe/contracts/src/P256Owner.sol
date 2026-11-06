// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// Safe owner backed by a phone hardware P-256 key (Android Keystore / iOS Secure Enclave).
/// The phone signs M = "pop-safe-owner-v1"(17) || safeTxHash(32) with SHA256withECDSA,
/// so the precompile digest is sha256(M). signature = r(32) || s(32), high-s accepted.
contract P256Owner {
    uint256 public immutable x;
    uint256 public immutable y;

    constructor(uint256 _x, uint256 _y) {
        x = _x;
        y = _y;
    }

    function _ok(bytes32 h, bytes memory sig) internal view returns (bool) {
        if (sig.length != 64) return false;
        (bytes32 r, bytes32 s) = abi.decode(sig, (bytes32, bytes32));
        (bool ok, bytes memory ret) =
            address(0x100).staticcall(abi.encode(sha256(abi.encodePacked("pop-safe-owner-v1", h)), r, s, x, y));
        return ok && ret.length == 32 && abi.decode(ret, (uint256)) == 1;
    }

    /// EIP-1271, Safe 1.5.0 (h = safeTxHash)
    function isValidSignature(bytes32 h, bytes memory sig) external view returns (bytes4) {
        return _ok(h, sig) ? bytes4(0x1626ba7e) : bytes4(0xffffffff);
    }

    /// legacy EIP-1271 (Safe <= 1.4.1): data = 0x1901||domain||struct, so keccak(data) = safeTxHash
    function isValidSignature(bytes memory data, bytes memory sig) external view returns (bytes4) {
        return _ok(keccak256(data), sig) ? bytes4(0x20c13b0b) : bytes4(0xffffffff);
    }
}

/// CREATE2 factory: one P256Owner per device pubkey, address predictable from (x, y).
contract P256OwnerFactory {
    event OwnerDeployed(address indexed owner, uint256 x, uint256 y);

    function ownerOf(uint256 x, uint256 y) public view returns (address) {
        bytes32 salt = keccak256(abi.encode(x, y));
        bytes32 ch = keccak256(abi.encodePacked(type(P256Owner).creationCode, abi.encode(x, y)));
        return address(uint160(uint256(keccak256(abi.encodePacked(bytes1(0xff), address(this), salt, ch)))));
    }

    function deploy(uint256 x, uint256 y) external returns (address o) {
        o = ownerOf(x, y);
        if (o.code.length == 0) {
            new P256Owner{salt: keccak256(abi.encode(x, y))}(x, y);
            emit OwnerDeployed(o, x, y);
        }
    }
}
