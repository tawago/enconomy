// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {MockEnv} from "./MockEnv.sol";
import {TestBase} from "./Vm.sol";
import {ProbeAccountLogic} from "../src/ProbeAccount.sol";

contract ProbeHarness is ProbeAccountLogic, MockEnv {
    constructor(address o) ProbeAccountLogic(o) {}

    function verifyFrame() external {
        _verifyFrame();
    }
}

/// Default profile (cancun): 0x100 is an empty account, the call "succeeds" with 0 bytes -> ProbeFailed.
/// `FOUNDRY_PROFILE=osaka forge test --offline --match-contract Probe`: forge's revm has P256VERIFY -> approves.
contract ProbeTest is TestBase {
    address constant OWNER = address(0x0A01);

    function _probe() internal returns (ProbeHarness p) {
        p = new ProbeHarness(OWNER);
        p.setSig(0, 0, uint160(OWNER));
        p.setTx(0x0A, 0);
        p.setFrame(0, 0x06, 3);
    }

    function test_probe() public {
        ProbeHarness p = _probe();
        bool present;
        {
            (bool ok, bytes memory o) = address(0x100).staticcall(
                hex"4cee90eb86eaa050036147a12d49004b6b9c72bd725d39d4785011fe190f0b4da73bd4903f0ce3b639bbbf6e8e80d16931ff4bcf5993d58468e8fb19086e8cac36dbcd03009df8c59286b162af3bd7fcc0450c9aa81be5d10d312af6c66b1d604aebd3099c618202fcfe16ae7770b0c49ab5eadf74b754204a3bb6060e44eff37618b065f9832de4ca6ca971a7a1adc826d0f7c00181a5fb2ddf79ae00b4e10e"
            );
            present = ok && o.length == 32;
        }
        vm.prank(EP);
        if (present) {
            p.verifyFrame();
            require(p.approvedScope() == 3, "scope");
            emit log_named_string("probe", "0x100 present (osaka): approved");
        } else {
            vm.expectRevert(abi.encodeWithSelector(ProbeAccountLogic.ProbeFailed.selector, true, 0));
            p.verifyFrame();
            emit log_named_string("probe", "0x100 absent (cancun): ProbeFailed(true, 0)");
        }
    }

    function test_probe_notOwner() public {
        ProbeHarness p = _probe();
        p.setSig(0, 0, uint160(address(0xEE)));
        vm.prank(EP);
        vm.expectRevert(ProbeAccountLogic.NotOwner.selector);
        p.verifyFrame();
    }
}
