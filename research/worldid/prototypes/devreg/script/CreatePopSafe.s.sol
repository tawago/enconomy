// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import "forge-std/Script.sol";
import {PopSafeGuard, PopSafeSetup} from "../src/PopSafeGuard.sol";

interface IFactory { function createProxyWithNonce(address, bytes memory, uint256) external returns (address); }
interface ISafeSetup { function setup(address[] calldata, uint256, address, bytes calldata, address, address, uint256, address payable) external; }

/// env: OWNER_A, OWNER_B (addresses), PUB_A, PUB_B (hex65 device pubkeys from the PoP server
///      session view / result record devices[role].pubkey), ISSUER_X, ISSUER_Y (POP_ATTEST_KEY pub),
///      DELAY (s), GUARD, SETUP (0 = deploy new), FACTORY, SINGLETON, FALLBACK, SALT
/// ex (480, 1.5.0 L2): FACTORY=0x14F2982D601c9458F93bd70B218933A6f8165e7b SINGLETON=0xEdd160fEBBD92E350D4D398fb636302fccd67C7e
///     FALLBACK=0x3EfCBb83A4A7AfcB4F68D501E2c2203a38be77f4
contract CreatePopSafe is Script {
    function run() external {
        address[] memory owners = new address[](2);
        owners[0] = vm.envAddress("OWNER_A"); owners[1] = vm.envAddress("OWNER_B");
        bytes32[] memory devs = new bytes32[](2);
        devs[0] = sha256(vm.envBytes("PUB_A")); devs[1] = sha256(vm.envBytes("PUB_B"));
        require(vm.envBytes("PUB_A").length == 65 && vm.envBytes("PUB_B").length == 65, "pubkey65");
        vm.startBroadcast();
        address guard = vm.envOr("GUARD", address(0));
        if (guard == address(0)) guard = address(new PopSafeGuard());
        address helper = vm.envOr("SETUP", address(0));
        if (helper == address(0)) helper = address(new PopSafeSetup());
        bytes memory hdata = abi.encodeCall(PopSafeSetup.setup,
            (guard, vm.envUint("ISSUER_X"), vm.envUint("ISSUER_Y"), uint32(vm.envUint("DELAY")), devs, owners));
        bytes memory init = abi.encodeCall(ISafeSetup.setup,
            (owners, 2, helper, hdata, vm.envAddress("FALLBACK"), address(0), 0, payable(address(0))));
        address safe = IFactory(vm.envAddress("FACTORY")).createProxyWithNonce(vm.envAddress("SINGLETON"), init, vm.envUint("SALT"));
        vm.stopBroadcast();
        console.log("safe", safe); console.log("guard", guard); console.logBytes32(devs[0]); console.logBytes32(devs[1]);
    }
}
