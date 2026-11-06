// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {MockEnv} from "./MockEnv.sol";
import {TestBase} from "./Vm.sol";
import {RecoverableP256AccountLogic} from "../src/RecoverableP256Account.sol";

contract RecoverHarness is RecoverableP256AccountLogic, MockEnv {
    constructor(address o, address[] memory g, uint256 d) RecoverableP256AccountLogic(o, g, d) {}

    function verifyFrame() external {
        _verifyFrame();
    }
}

contract RecoverableTest is TestBase {
    address constant OWNER = address(0x0A01);
    address constant NEWKEY = address(0x0A02);
    address constant G1 = address(0x6001);
    address constant G2 = address(0x6002);
    address constant G3 = address(0x6003);
    bytes32 constant TRANSCRIPT = keccak256("meet transcript");
    uint256 constant DEADLINE = 1793617600;

    RecoverHarness a;

    function _deploy() internal {
        address[] memory g = new address[](3);
        g[0] = G1;
        g[1] = G2;
        g[2] = G3;
        a = new RecoverHarness(OWNER, g, 120);
    }

    function _setBody(uint256 frame, bytes memory data) internal {
        a.setFrame(frame, 0, uint160(address(a)));
        a.setFrame(frame, 2, 2); // SENDER
        a.setFrame(frame, 4, data.length);
        a.setFrameData(frame, 0, _word(data, 0));
        a.setFrameData(frame, 4, _word(data, 4));
        a.setFrameData(frame, 36, _word(data, 36));
    }

    /// Recovery envelope: [expiry, self_verify(a), SENDER a.startRotation(NEWKEY, T)], sigs [new, g1, g2].
    function _recoveryEnv(address g1, address g2) internal {
        _deploy();
        a.setTx(0x0B, 3);
        a.setTx(0x09, 3);
        a.setTx(0x0A, 1);
        a.setFrame(0, 0, uint160(address(0x8141)));
        a.setFrame(0, 2, 1);
        a.setFrameData(0, 0, bytes32(DEADLINE << 192));
        a.setFrame(1, 0x06, 3); // self_verify allows execution + payment
        _setBody(2, abi.encodeCall(RecoverableP256AccountLogic.startRotation, (NEWKEY, TRANSCRIPT)));
        bytes32 d = a.recoveryDigest(NEWKEY, a.recoveryNonce(), TRANSCRIPT, DEADLINE);
        _sig(0, NEWKEY, 0);
        _sig(1, g1, d);
        _sig(2, g2, d);
    }

    function _sig(uint256 i, address signer, bytes32 m) internal {
        a.setSig(i, 0, uint160(signer));
        a.setSig(i, 1, 2);
        a.setSig(i, 2, uint256(m));
    }

    function _verify() internal {
        vm.prank(EP);
        a.verifyFrame();
    }

    function _verifyFails(bytes4 err) internal {
        vm.prank(EP);
        vm.expectRevert(err);
        a.verifyFrame();
    }

    // ---------------------------------------------------------------------------------------------
    function test_normalOwner() public {
        _deploy();
        a.setTx(0x0B, 1);
        a.setTx(0x0A, 0);
        a.setFrame(0, 0x06, 3);
        _sig(0, OWNER, 0);
        _verify();
        require(a.approvedScope() == 3, "scope");
    }

    function test_normalRejectsStranger() public {
        _deploy();
        a.setTx(0x0B, 1);
        _sig(0, address(0xEE), 0);
        _verifyFails(RecoverableP256AccountLogic.NotOwner.selector);
    }

    function test_normalRejectsExplicitMsg() public {
        _deploy();
        a.setTx(0x0B, 1);
        _sig(0, OWNER, keccak256("not the sig hash"));
        _verifyFails(RecoverableP256AccountLogic.NotSigHash.selector);
    }

    function test_recovery_happy() public {
        _recoveryEnv(G1, G2);
        _verify();
        require(a.approvedScope() == 3, "scope");
    }

    function test_recovery_duplicateGuardian() public {
        _recoveryEnv(G1, G1);
        _verifyFails(RecoverableP256AccountLogic.BadGuardian.selector);
    }

    function test_recovery_nonGuardian() public {
        _recoveryEnv(G1, address(0x6666));
        _verifyFails(RecoverableP256AccountLogic.BadGuardian.selector);
    }

    function test_recovery_guardianSignedOtherKey() public {
        _recoveryEnv(G1, G2);
        bytes32 other = a.recoveryDigest(address(0xBAD), a.recoveryNonce(), TRANSCRIPT, DEADLINE);
        _sig(2, G2, other);
        _verifyFails(RecoverableP256AccountLogic.GuardianSig.selector);
    }

    function test_recovery_deadlineBound() public {
        _recoveryEnv(G1, G2);
        a.setFrameData(0, 0, bytes32((DEADLINE + 3600) << 192)); // relayer stretches the deadline
        _verifyFails(RecoverableP256AccountLogic.GuardianSig.selector);
    }

    function test_recovery_noExpiryFrame() public {
        _recoveryEnv(G1, G2);
        a.setFrame(0, 0, uint160(address(0x1234)));
        _verifyFails(RecoverableP256AccountLogic.NoExpiry.selector);
    }

    function test_recovery_framePinned() public {
        _recoveryEnv(G1, G2);
        a.setTx(0x09, 4); // an extra frame would run with the account's approval
        _verifyFails(RecoverableP256AccountLogic.Layout.selector);
        _recoveryEnv(G1, G2);
        _setBody(2, abi.encodeCall(RecoverableP256AccountLogic.setGuardian, (address(0xBAD), true)));
        _verifyFails(RecoverableP256AccountLogic.Layout.selector);
    }

    function test_recovery_newKeyMustSign() public {
        _recoveryEnv(G1, G2);
        _sig(0, address(0xEE), 0);
        _verifyFails(RecoverableP256AccountLogic.NotOwner.selector);
    }

    function test_rotation_finishAfterDelay() public {
        _recoveryEnv(G1, G2);
        vm.warp(1000);
        vm.prank(address(a));
        a.startRotation(NEWKEY, TRANSCRIPT);
        require(a.pendingOwner() == NEWKEY && a.readyAt() == 1120, "pending");

        vm.expectRevert(RecoverableP256AccountLogic.TooEarly.selector);
        a.finishRotation();

        vm.warp(1120);
        a.finishRotation(); // anyone
        require(a.owner() == NEWKEY && a.pendingOwner() == address(0), "rotated");
    }

    function test_rotation_cancelByOwner() public {
        _recoveryEnv(G1, G2);
        uint256 n0 = a.recoveryNonce();
        vm.prank(address(a));
        a.startRotation(NEWKEY, TRANSCRIPT);
        vm.prank(address(a));
        a.cancelRotation();
        require(a.pendingOwner() == address(0) && a.owner() == OWNER, "cancel");
        require(a.recoveryNonce() == n0 + 2, "nonce");
        vm.warp(block.timestamp + 1 days);
        vm.expectRevert(RecoverableP256AccountLogic.NoPending.selector);
        a.finishRotation();
    }

    /// Signatures collected for nonce n are useless after a start/cancel bumps it.
    function test_recovery_replayAfterCancel() public {
        _recoveryEnv(G1, G2);
        vm.prank(address(a));
        a.startRotation(NEWKEY, TRANSCRIPT);
        vm.prank(address(a));
        a.cancelRotation();
        _verifyFails(RecoverableP256AccountLogic.GuardianSig.selector);
    }

    function test_bodyFramesOnlySelf() public {
        _deploy();
        vm.expectRevert(RecoverableP256AccountLogic.NotSelf.selector);
        a.startRotation(NEWKEY, TRANSCRIPT);
        vm.expectRevert(RecoverableP256AccountLogic.NotSelf.selector);
        a.cancelRotation();
        vm.expectRevert(RecoverableP256AccountLogic.NotSelf.selector);
        a.setGuardian(address(0xBAD), true);
    }

    /// The new phone can self-pay finishRotation, and nothing else, while pending.
    function test_pendingKey_finishPathOnly() public {
        _deploy();
        vm.prank(address(a));
        a.startRotation(NEWKEY, TRANSCRIPT);
        a.setTx(0x0B, 1);
        a.setTx(0x09, 2);
        a.setTx(0x0A, 0);
        a.setFrame(0, 0x06, 3);
        _sig(0, NEWKEY, 0);
        _setBody(1, abi.encodeCall(RecoverableP256AccountLogic.finishRotation, ()));
        _verify();
        require(a.approvedScope() == 3, "scope");

        _setBody(1, abi.encodeCall(RecoverableP256AccountLogic.cancelRotation, ()));
        _verifyFails(RecoverableP256AccountLogic.Layout.selector);
    }

    function test_guardianSet() public {
        _deploy();
        require(a.guardianCount() == 3, "count");
        vm.prank(address(a));
        a.setGuardian(G3, false);
        require(!a.isGuardian(G3) && a.guardianCount() == 2, "removed");
    }
}
