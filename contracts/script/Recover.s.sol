// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Script.sol";

interface ISafeR {
    function nonce() external view returns (uint256);
    function getTransactionHash(address, uint256, bytes calldata, uint8, uint256, uint256, uint256, address, address, uint256)
        external
        view
        returns (bytes32);
    function execTransaction(address, uint256, bytes calldata, uint8, uint256, uint256, uint256, address, address payable, bytes memory)
        external
        payable
        returns (bool);
}

interface IGuardR {
    function announce(address safe, address to, bytes calldata data, uint256 nonce) external returns (bytes32);
    function ann(address, bytes32) external view returns (uint64 readyAt, uint64 epoch);
}

/// Escape hatch (spec 02 §5), run by the two guardian owners (no phone, no presence proof).
/// env: SAFE, GUARD, TO, DATA (hex calldata), NONCE (Safe nonce this tx will use, in [nonce(), nonce()+4)), G1_PK
///   MODE=announce : G1 calls guard.announce(SAFE, TO, DATA, NONCE)  (then wait cfg.delay, execute within cfg.grace)
///   MODE=exec     : also needs G2_PK. G1+G2 sign safeTxHash, G1 sends execTransaction with NO presence suffix
/// Keys: contracts/.env.guardians (gitignored, chmod 600), `source` it only for the hatch.
contract Recover is Script {
    function run() external {
        ISafeR safe = ISafeR(vm.envAddress("SAFE"));
        IGuardR guard = IGuardR(vm.envAddress("GUARD"));
        address to = vm.envAddress("TO");
        bytes memory data = vm.envBytes("DATA");
        uint256 n = vm.envUint("NONCE");
        bytes32 h = safe.getTransactionHash(to, 0, data, 0, 0, 0, 0, address(0), address(0), n);
        console.log("safeTxHash");
        console.logBytes32(h);
        uint256 k1 = vm.envUint("G1_PK");
        if (keccak256(bytes(vm.envString("MODE"))) == keccak256("announce")) {
            vm.startBroadcast(k1);
            guard.announce(address(safe), to, data, n);
            vm.stopBroadcast();
            (uint64 readyAt,) = guard.ann(address(safe), h);
            console.log("readyAt", readyAt);
            return;
        }
        uint256 k2 = vm.envUint("G2_PK");
        require(safe.nonce() == n, "nonce moved: re-announce for the current nonce");
        (address a1, address a2) = (vm.addr(k1), vm.addr(k2));
        (uint8 v1, bytes32 r1, bytes32 s1) = vm.sign(k1, h);
        (uint8 v2, bytes32 r2, bytes32 s2) = vm.sign(k2, h);
        bytes memory sigs =
            a1 < a2 ? abi.encodePacked(r1, s1, v1, r2, s2, v2) : abi.encodePacked(r2, s2, v2, r1, s1, v1);
        vm.startBroadcast(k1);
        safe.execTransaction(to, 0, data, 0, 0, 0, 0, address(0), payable(address(0)), sigs);
        vm.stopBroadcast();
    }
}
