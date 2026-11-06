// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Fixture} from "./Fixture.sol";
import {EvpBase, EvpHarness} from "./EvpRecovery.t.sol";

/// REFUTE.md section 3. Under EIP-8037 a frame tx's body frame pays state gas only from its own
/// `limits.state`; a slot that goes 0 -> non-zero costs 64 * 1530 = 97,920 and nothing spills over from
/// execution gas. Forge prices Osaka and cannot charge state gas, so these tests count fresh slots instead:
/// every SSTORE in a start must hit a slot that was already non-zero before the tx.
contract EvpStateGasTest is EvpBase {
    function setUp() public {
        _setUpAccount();
    }

    function _snap() internal view returns (bytes32[7] memory pre) {
        for (uint256 s = 0; s < 7; s++) {
            pre[s] = vm.load(address(a), bytes32(s));
        }
    }

    /// Number of slots written by the last recorded call that were zero before it.
    function _freshWrites(bytes32[7] memory pre) internal returns (uint256 fresh) {
        (, bytes32[] memory writes) = vm.accesses(address(a));
        for (uint256 i = 0; i < writes.length; i++) {
            uint256 s = uint256(writes[i]);
            require(s < 7, "start wrote an unexpected slot");
            if (pre[s] == 0) fresh++;
        }
    }

    function _startCounted(bytes memory token, uint256 offs) internal returns (uint256) {
        bytes32[7] memory pre = _snap();
        vm.record();
        _start(token, offs);
        return _freshWrites(pre);
    }

    /// Straight from the constructor: slot 1 (pendingOwner, readyAt, keep) and slot 2 (recoveryNonce) are
    /// already non-zero, so the first start on a fresh deploy writes no fresh slot.
    function test_stateGas_constructorLeavesNoFreshSlot() public {
        address[] memory g = new address[](0);
        EvpHarness fresh = new EvpHarness(OWNER, g, 120, LAPTOP, LAPTOP_X, bytes32(uint256(1)));
        require(fresh.laptopDeviceX() == LAPTOP_X, "device X set at deploy");
        require(vm.load(address(fresh), bytes32(uint256(1))) != 0, "slot 1 zero after deploy");
        require(vm.load(address(fresh), bytes32(uint256(2))) != 0, "slot 2 zero after deploy");
        require(fresh.recoveryNonce() == 1, "nonce starts at 1");
        require(fresh.pendingOwner() == address(0) && fresh.readyAt() == 0, "nothing pending");
    }

    /// start -> cancel -> start -> finish. No start writes a fresh slot, and cancel and finish leave
    /// slots 1 and 2 non-zero, so the next start does not either.
    function test_stateGas_noFreshSlotAcrossCycle() public {
        require(_startCounted(Fixture.GOOD, Fixture.OFFS_GOOD) == 0, "start 1 wrote a fresh slot");
        vm.prank(address(a));
        a.cancelRotation();
        require(a.pendingOwner() == address(0) && a.readyAt() == 0, "cancelled");
        require(vm.load(address(a), bytes32(uint256(1))) != 0, "slot 1 zero after cancel");

        require(_startCounted(Fixture.NONCE9, Fixture.OFFS_NONCE9) == 0, "start 2 wrote a fresh slot");
        vm.warp(NOW + 120);
        a.finishRotation();
        require(a.owner() == NEWKEY && a.pendingOwner() == address(0) && a.readyAt() == 0, "finished");
        require(vm.load(address(a), bytes32(uint256(1))) != 0, "slot 1 zero after finish");
        require(vm.load(address(a), bytes32(uint256(2))) != 0, "slot 2 zero after finish");
    }

    /// The laptop's device X is slot 7. _freshWrites already refuses any write at slot 7 or above; this names it.
    function test_stateGas_startNeverWritesDeviceX() public {
        require(_startCounted(Fixture.GOOD, Fixture.OFFS_GOOD) == 0, "start wrote a fresh slot");
        require(a.laptopDeviceX() == LAPTOP_X, "device X moved");
    }

    /// The same check fails without the keep word: zero slot 1 by hand and the start writes one fresh slot.
    /// This is the 97,920 state gas the body would need with no budget for it.
    function test_stateGas_withoutKeepWordStartIsFresh() public {
        vm.store(address(a), bytes32(uint256(1)), bytes32(0));
        require(_startCounted(Fixture.GOOD, Fixture.OFFS_GOOD) == 1, "expected one fresh slot");
    }
}
