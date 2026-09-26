// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import "forge-std/Script.sol";
import {PopSafeGuard, PopSafeSetup} from "../src/PopSafeGuardU.sol";
import {P256Owner} from "../src/P256Owner.sol";
import {SpikeGuard, GuardUTest, IFactory, ISafe} from "../test/GuardU.t.sol";

/// Deploys Safe L2 1.5.0 + SpikeGuard on an anvil fork of 480 at block 35464545, binds the tx, writes the exec calldata.
contract AnvilSetup is Script, GuardUTest {
    function run() external {
        o1 = vm.addr(k1); bob = address(0xB0B0);
        (uint256 px, uint256 py) = vm.publicKeyP256(ownerP256);
        vm.startBroadcast();
        pOwner = new P256Owner(px, py);
        guard = PopSafeGuard(address(new SpikeGuard(WID, RP, act("spike-1790264612780"), act("spike-1790264710529"))));
        helper = new PopSafeSetup();
        (uint256 qx, uint256 qy) = vm.publicKeyP256(issuerPk);
        address[] memory owners = new address[](2); owners[0] = o1; owners[1] = address(pOwner);
        bytes32[] memory devs = new bytes32[](2); devs[0] = dev(PHONE_A); devs[1] = dev(PHONE_B);
        bytes memory hdata = abi.encodeCall(PopSafeSetup.setup, (address(guard), qx, qy, uint32(1 days), devs, owners));
        bytes memory init = abi.encodeCall(ISafe.setup, (owners, 2, address(helper), hdata, FALLBACK, address(0), 0, payable(address(0))));
        safe = ISafe(IFactory(FACTORY).createProxyWithNonce(SAFE_L2_150, init, 7));
        payable(address(safe)).transfer(2 ether);
        bytes32 h = _h(1 ether);
        SpikeGuard(address(guard)).bind(h);
        vm.stopBroadcast();
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _wid(hA(), hB()), _pop2Long(h, guard.pairTagOf(NA, NB)));
        vm.writeFile("anvil_out.txt", string.concat(vm.toString(address(safe)), " ", vm.toString(sigs)));
    }
    function _pop2Long(bytes32 h, bytes32 pairTag) internal view returns (bytes memory) {
        uint64 expiry = uint64(block.timestamp + 3000);
        bytes32 dA = dev(PHONE_A); bytes32 dB = dev(PHONE_B);
        bytes32 d = guard.digest(block.chainid, address(safe), h, pairTag, dA, dB, expiry);
        (bytes32 r, bytes32 s) = vm.signP256(issuerPk, d);
        return abi.encodePacked(pairTag, dA, dB, expiry, r, s, bytes4(0x504f5032));
    }
}
