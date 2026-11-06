// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Script.sol";
import {PopSafeSetup} from "../src/PopSafeGuard.sol";
import {P256OwnerFactory} from "../src/P256Owner.sol";

interface IFactory {
    function createProxyWithNonce(address, bytes memory, uint256) external returns (address);
}

interface ISafeSetup {
    function setup(address[] calldata, uint256, address, bytes calldata, address, address, uint256, address payable)
        external;
}

/// Creates the 2-of-4 PoP Safe (SafeL2 1.5.0, Sepolia canonical) with the guard set inside setup.
/// env: PUB_A, PUB_B (0x04||X||Y, 65 B), GUARDIAN_1, GUARDIAN_2 (EOAs), ISSUER_X, ISSUER_Y,
///      DELAY (s, >= 300), GRACE (s, >= 300), SALT, GUARD, SETUP, OWNER_FACTORY (from the deployments json),
///      PRIVATE_KEY (optional)
/// fallbackHandler is address(0) on purpose: CompatibilityFallbackHandler.isValidSignature would let any
/// 2 owners (G1+G2) sign EIP-1271 messages (permits) for the Safe without passing the guard.
contract CreatePopSafe is Script {
    address constant FACTORY = 0x14F2982D601c9458F93bd70B218933A6f8165e7b; // SafeProxyFactory 1.5.0
    address constant SINGLETON = 0xEdd160fEBBD92E350D4D398fb636302fccd67C7e; // SafeL2 1.5.0

    function _xy(bytes memory p) internal pure returns (uint256 x, uint256 y) {
        require(p.length == 65 && p[0] == 0x04, "pubkey65");
        assembly {
            x := mload(add(p, 33))
            y := mload(add(p, 65))
        }
    }

    function run() external returns (address safe) {
        bytes memory pa = vm.envBytes("PUB_A");
        bytes memory pb = vm.envBytes("PUB_B");
        (uint256 ax, uint256 ay) = _xy(pa);
        (uint256 bx, uint256 by) = _xy(pb);
        P256OwnerFactory pf = P256OwnerFactory(vm.envAddress("OWNER_FACTORY"));
        uint256 pk = vm.envOr("PRIVATE_KEY", uint256(0));
        if (pk != 0) vm.startBroadcast(pk);
        else vm.startBroadcast();
        address oA = pf.deploy(ax, ay);
        address oB = pf.deploy(bx, by);
        address[] memory owners = new address[](4);
        owners[0] = oA;
        owners[1] = oB;
        owners[2] = vm.envAddress("GUARDIAN_1");
        owners[3] = vm.envAddress("GUARDIAN_2");
        bytes32[] memory devs = new bytes32[](2);
        devs[0] = sha256(pa);
        devs[1] = sha256(pb);
        address[] memory devOwners = new address[](2);
        devOwners[0] = oA;
        devOwners[1] = oB;
        bytes memory hdata = abi.encodeCall(
            PopSafeSetup.setup,
            (
                vm.envAddress("GUARD"),
                vm.envUint("ISSUER_X"),
                vm.envUint("ISSUER_Y"),
                uint32(vm.envUint("DELAY")),
                uint32(vm.envUint("GRACE")),
                devs,
                devOwners
            )
        );
        bytes memory init = abi.encodeCall(
            ISafeSetup.setup, (owners, 2, vm.envAddress("SETUP"), hdata, address(0), address(0), 0, payable(address(0)))
        );
        safe = IFactory(FACTORY).createProxyWithNonce(SINGLETON, init, vm.envUint("SALT"));
        vm.stopBroadcast();
        console.log("safe", safe);
        console.log("ownerA", oA);
        console.log("ownerB", oB);
        console.logBytes32(devs[0]);
        console.logBytes32(devs[1]);
    }
}
