// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Vm} from "forge-std/Vm.sol";

/// Deploys build/sha256.<variant>.bin (pure-Yul SHA-256, no precompile) and wraps its calldata format.
library YulSha {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function deploy(string memory variant) internal returns (address a) {
        bytes memory init = vm.parseBytes(string.concat("0x", vm.readFile(string.concat("build/sha256.", variant, ".bin"))));
        assembly ("memory-safe") { a := create(0, add(init, 32), mload(init)) }
        require(a != address(0) && a.code.length > 0, "deploy");
    }

    function hdr(uint256 mode, bool sd, uint256 d2, uint256 t, uint256 k2) internal pure returns (uint256) {
        return mode | (sd ? 1 << 8 : 0) | (d2 << 16) | (t << 32) | (k2 << 48);
    }

    function plain(address s, bytes memory m) internal view returns (bytes32 h) {
        (bool ok, bytes memory r) = s.staticcall(abi.encodePacked(uint256(0), m));
        require(ok, "sha");
        h = abi.decode(r, (bytes32));
    }

    function evp(address s, uint256 mode, bool sd, bytes memory tok, uint256 d2, uint256 t, uint256 k2)
        internal view returns (bytes32 e, bytes32 k, bytes32 x)
    {
        (bool ok, bytes memory r) = s.staticcall(abi.encodePacked(hdr(mode, sd, d2, t, k2), tok));
        require(ok, "sha");
        (e, k, x) = abi.decode(r, (bytes32, bytes32, bytes32));
    }
}
