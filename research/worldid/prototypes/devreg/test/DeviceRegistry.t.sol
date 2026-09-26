// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import "forge-std/Test.sol";
import {PopSafeGuard, PopSafeSetup} from "../src/PopSafeGuard.sol";

interface IFactory { function createProxyWithNonce(address singleton, bytes memory initializer, uint256 saltNonce) external returns (address); }
interface ISafe {
    function setup(address[] calldata, uint256, address, bytes calldata, address, address, uint256, address payable) external;
    function execTransaction(address to, uint256 value, bytes calldata data, uint8 operation, uint256 safeTxGas, uint256 baseGas, uint256 gasPrice, address gasToken, address payable refundReceiver, bytes memory signatures) external payable returns (bool);
    function getTransactionHash(address to, uint256 value, bytes calldata data, uint8 operation, uint256 safeTxGas, uint256 baseGas, uint256 gasPrice, address gasToken, address refundReceiver, uint256 _nonce) external view returns (bytes32);
    function nonce() external view returns (uint256);
    function setGuard(address) external;
    function swapOwner(address, address, address) external;
    function addOwnerWithThreshold(address, uint256) external;
    function removeOwner(address, address, uint256) external;
    function changeThreshold(uint256) external;
}

contract DeviceRegistryTest is Test {
    address constant FALLBACK = 0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99;
    bytes32 constant GUARD_SLOT = 0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8;
    uint256 k1 = 0xA11CE; uint256 k2 = 0xB0B;
    uint256 issuerPk = 0xC0FFEE;
    // phone hardware keys (P-256 scalars stand in for Keystore / Secure Enclave keys)
    uint256 constant PHONE_A = 0xA1; uint256 constant PHONE_B = 0xB1;
    uint256 constant PHONE_A_REINSTALL = 0xA2; uint256 constant PHONE_B_REINSTALL = 0xB2;
    uint256 constant STRANGER_1 = 0x51; uint256 constant STRANGER_2 = 0x52; uint256 constant PHONE_A_SECOND = 0xA3;
    uint32 constant DELAY = 1 days;

    ISafe safe; PopSafeGuard guard; PopSafeSetup helper;
    address o1; address o2; address bob;

    function dev(uint256 pk) internal pure returns (bytes32) {
        (uint256 x, uint256 y) = vm.publicKeyP256(pk);
        return sha256(abi.encodePacked(bytes1(0x04), x, y)); // = full sha256(pubkey65); server device_id = first 16 bytes
    }

    function _deploy(address factory, address singleton) internal {
        o1 = vm.addr(k1); o2 = vm.addr(k2);
        if (o1 > o2) { (o1, o2) = (o2, o1); (k1, k2) = (k2, k1); }
        bob = makeAddr("bob");
        guard = new PopSafeGuard();
        helper = new PopSafeSetup();
        (uint256 qx, uint256 qy) = vm.publicKeyP256(issuerPk);
        address[] memory owners = new address[](2); owners[0] = o1; owners[1] = o2;
        bytes32[] memory devs = new bytes32[](2); devs[0] = dev(PHONE_A); devs[1] = dev(PHONE_B);
        bytes memory hdata = abi.encodeCall(PopSafeSetup.setup, (address(guard), qx, qy, DELAY, devs, owners));
        bytes memory init = abi.encodeCall(ISafe.setup, (owners, 2, address(helper), hdata, FALLBACK, address(0), 0, payable(address(0))));
        uint256 g = gasleft();
        safe = ISafe(IFactory(factory).createProxyWithNonce(singleton, init, 7));
        console.log("create Safe + guard + 2 devices, gas", g - gasleft());
        vm.deal(address(safe), 10 ether);
    }

    function _hash(address to, bytes memory data) internal view returns (bytes32) {
        return safe.getTransactionHash(to, 0, data, 0, 0, 0, 0, address(0), address(0), safe.nonce());
    }
    function _hashV(address to, uint256 v, bytes memory data, uint256 n) internal view returns (bytes32) {
        return safe.getTransactionHash(to, v, data, 0, 0, 0, 0, address(0), address(0), n);
    }

    function _ownerSigs(bytes32 h) internal view returns (bytes memory) {
        (uint8 v1, bytes32 r1, bytes32 s1) = vm.sign(k1, h);
        (uint8 v2, bytes32 r2, bytes32 s2) = vm.sign(k2, h);
        return abi.encodePacked(r1, s1, v1, r2, s2, v2);
    }

    function _tail(bytes32 h, uint256 phoneX, uint256 phoneY) internal view returns (bytes memory) {
        bytes32 pairTag = keccak256("pair"); uint64 expiry = uint64(block.timestamp + 600);
        bytes32 dA = dev(phoneX); bytes32 dB = dev(phoneY);
        bytes32 d = guard.digest(block.chainid, address(safe), h, pairTag, dA, dB, expiry);
        (bytes32 r, bytes32 s) = vm.signP256(issuerPk, d);
        return abi.encodePacked(pairTag, dA, dB, expiry, r, s, bytes4(0x504f5032));
    }

    /// exec with a PoP attestation for (phoneX, phoneY); phoneX == 0 means no attestation
    function exec(address to, uint256 value, bytes memory data, uint256 phoneX, uint256 phoneY) public returns (bool) {
        bytes32 h = _hashV(to, value, data, safe.nonce());
        bytes memory sigs = _ownerSigs(h);
        if (phoneX != 0) sigs = abi.encodePacked(sigs, _tail(h, phoneX, phoneY));
        return safe.execTransaction(to, value, data, 0, 0, 0, 0, address(0), payable(address(0)), sigs);
    }

    function _scenario(address factory, address singleton) internal {
        _deploy(factory, singleton);
        assertEq(address(uint160(uint256(vm.load(address(safe), GUARD_SLOT)))), address(guard), "guard set in setup");
        assertEq(guard.deviceOwner(address(safe), dev(PHONE_A)), o1);
        assertEq(guard.deviceOwner(address(safe), dev(PHONE_B)), o2);

        // 1. owners' phones met -> spend works
        uint256 g = gasleft();
        assertTrue(exec(bob, 1 ether, "", PHONE_A, PHONE_B));
        console.log("spend with registry check, gas", g - gasleft());
        // order of roles doesn't matter
        assertTrue(exec(bob, 1 ether, "", PHONE_B, PHONE_A));

        // 2. two strangers' enrolled phones met (valid issuer signature) -> rejected
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(bob, 1 ether, "", STRANGER_1, STRANGER_2);
        // 3. owner A's phone + a stranger -> rejected (a spend, not a device add)
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(bob, 1 ether, "", PHONE_A, STRANGER_1);
        // 4. owner A carries two registered phones -> rejected
        exec(address(guard), 0, abi.encodeCall(PopSafeGuard.addDevice, (dev(PHONE_A_SECOND), o1)), PHONE_A, PHONE_B);
        vm.expectRevert(PopSafeGuard.SameOwner.selector);
        this.exec(bob, 1 ether, "", PHONE_A, PHONE_A_SECOND);

        // 5. owner A reinstalls the app -> new Keystore key -> gate is locked for A's new phone
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(bob, 1 ether, "", PHONE_A_REINSTALL, PHONE_B);

        // 6. rotate by meeting: new phone A meets registered phone B, tx = replaceDevice(oldA, newA)
        //    (a stranger can't use this to add itself for B's slot: witness B's owner must differ)
        bytes memory addS1 = abi.encodeCall(PopSafeGuard.addDevice, (dev(STRANGER_1), o2));
        vm.expectRevert(PopSafeGuard.SameOwner.selector);
        this.exec(address(guard), 0, addS1, STRANGER_1, PHONE_B);
        // and the unknown device must be exactly the one being added
        bytes memory addS2 = abi.encodeCall(PopSafeGuard.addDevice, (dev(STRANGER_2), o1));
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(address(guard), 0, addS2, STRANGER_1, PHONE_B);
        g = gasleft();
        assertTrue(exec(address(guard), 0, abi.encodeCall(PopSafeGuard.replaceDevice, (dev(PHONE_A), dev(PHONE_A_REINSTALL))), PHONE_A_REINSTALL, PHONE_B));
        console.log("replaceDevice by meeting, gas", g - gasleft());
        assertEq(guard.deviceOwner(address(safe), dev(PHONE_A)), address(0), "old key gone");
        assertTrue(exec(bob, 1 ether, "", PHONE_A_REINSTALL, PHONE_B));

        // 7. both phones reinstalled: no registered device left to meet -> escape hatch
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(bob, 1 ether, "", PHONE_A_REINSTALL + 100, PHONE_B_REINSTALL);
        //    announce two consecutive recovery txs (nonces n, n+1)
        uint256 n = safe.nonce();
        // wipe both of B's slot and A's slot: replace A (current A_REINSTALL -> A_SECOND already registered? use fresh) and B
        bytes memory rA = abi.encodeCall(PopSafeGuard.replaceDevice, (dev(PHONE_A_REINSTALL), dev(0xA9)));
        bytes memory rB = abi.encodeCall(PopSafeGuard.replaceDevice, (dev(PHONE_B), dev(PHONE_B_REINSTALL)));
        bytes32 hA = _hashV(address(guard), 0, rA, n);
        bytes32 hB = _hashV(address(guard), 0, rB, n + 1);
        //    a non-owner can't announce
        vm.prank(bob); vm.expectRevert(PopSafeGuard.NotOwner.selector); guard.announce(address(safe), hA);
        vm.startPrank(o1); guard.announce(address(safe), hA); guard.announce(address(safe), hB); vm.stopPrank();
        //    too early
        vm.expectRevert(PopSafeGuard.TooEarly.selector);
        this.exec(address(guard), 0, rA, 0, 0);
        vm.warp(block.timestamp + DELAY);
        //    an announced spend is still not allowed through the hatch
        bytes32 hSpend = _hashV(bob, 1 ether, "", n);
        vm.prank(o1); guard.announce(address(safe), hSpend);
        vm.warp(block.timestamp + DELAY);
        vm.expectRevert(PopSafeGuard.NotRecoveryTx.selector);
        this.exec(bob, 1 ether, "", 0, 0);
        assertTrue(exec(address(guard), 0, rA, 0, 0));
        assertTrue(exec(address(guard), 0, rB, 0, 0));
        //    new phones work
        assertTrue(exec(bob, 1 ether, "", 0xA9, PHONE_B_REINSTALL));

        // 8. an owner removed from the Safe: their devices stop counting
        address o3 = makeAddr("o3");
        // hmm: removal keeps threshold 2 of {o1,o2,o3}->{o1,o2}; add o3 first
        assertTrue(exec(address(safe), 0, abi.encodeCall(ISafe.addOwnerWithThreshold, (o3, 2)), 0xA9, PHONE_B_REINSTALL));
        assertTrue(exec(address(guard), 0, abi.encodeCall(PopSafeGuard.addDevice, (dev(0xC1), o3)), 0xA9, PHONE_B_REINSTALL));
        assertTrue(exec(bob, 1, "", 0xC1, PHONE_B_REINSTALL));
        // owners list is o3 -> o1 -> o2 (addOwner prepends); prevOwner of o3 is SENTINEL (0x1)
        assertTrue(exec(address(safe), 0, abi.encodeCall(ISafe.removeOwner, (address(1), o3, 2)), 0xA9, PHONE_B_REINSTALL));
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(bob, 1, "", 0xC1, PHONE_B_REINSTALL);

        // 9. escape: remove the guard entirely after the delay
        n = safe.nonce();
        bytes memory unset = abi.encodeCall(ISafe.setGuard, (address(0)));
        bytes32 hUnset = _hashV(address(safe), 0, unset, n);
        vm.prank(o2); guard.announce(address(safe), hUnset);
        vm.warp(block.timestamp + DELAY);
        assertTrue(exec(address(safe), 0, unset, 0, 0));
        assertEq(uint256(vm.load(address(safe), GUARD_SLOT)), 0);
    }

    function test_selectors() public pure {
        assertEq(ISafe.setGuard.selector, bytes4(0xe19a9dd9));
        assertEq(ISafe.swapOwner.selector, bytes4(0xe318b52b));
        assertEq(ISafe.addOwnerWithThreshold.selector, bytes4(0x0d582f13));
        assertEq(ISafe.removeOwner.selector, bytes4(0xf8dc5dd9));
        assertEq(ISafe.changeThreshold.selector, bytes4(0x694e80c3));
    }

    function test_v141_wcsep() public {
        vm.createSelectFork("wcsep");
        _scenario(0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67, 0x29fcB43b46531BcA003ddC8FCB67FFE91900C762);
    }
    function test_v150_wcsep() public {
        vm.createSelectFork("wcsep");
        _scenario(0x14F2982D601c9458F93bd70B218933A6f8165e7b, 0xFf51A5898e281Db6DfC7855790607438dF2ca44b);
    }
    function test_v150L2_worldchain() public {
        vm.createSelectFork("wc");
        _scenario(0x14F2982D601c9458F93bd70B218933A6f8165e7b, 0xEdd160fEBBD92E350D4D398fb636302fccd67C7e);
    }
}
