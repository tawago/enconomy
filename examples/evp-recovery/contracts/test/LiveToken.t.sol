// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {TestBase} from "./Vm.sol";
import {EvpCheck} from "../src/EvpCheck.sol";
import {EvpBase} from "./EvpRecovery.t.sol";
import {EvpRecoveryAccountLogic} from "../src/EvpRecoveryAccount.sol";
import {LiveFixture as F} from "live-chrome/verify/test/LiveFixture.sol";

/// The 15 real Chrome 156 tokens against this account's own EvpCheck, through checkEvp. Their KB nonce is the shared
/// vector's ctx. This is as far as they get: see test_liveToken_cannotReachBody.
contract EvpLiveTokenTest is EvpBase {
    EvpCheck.Config cfg;

    function setUp() public {
        _setUpAccount();
        cfg = EvpCheck.Config(
            F.ISSUER_X, F.ISSUER_Y, keccak256(F.EMAIL), keccak256(F.AUD), POP_X, POP_Y, VERIFIER
        );
        vm.prank(address(a));
        a.setConfig(keccak256(abi.encode(cfg)));
    }

    /// fixture.mjs writes the PoC's 15 fields. Field 15 is this account's aud length.
    function _offs(uint256 offs) private pure returns (uint256) {
        return offs | (F.AUD.length << 240);
    }

    function test_liveToken_allPassCheckEvp() public {
        for (uint256 i; i < F.N; ++i) {
            (bytes memory t, uint256 offs, uint256 iat) = F.tok(i);
            vm.warp(iat + 30);
            a.checkEvp(t, _offs(offs), cfg, CTX);
        }
        emit log_named_uint("live tokens through checkEvp", F.N);
    }

    function test_liveToken_otherCtxFails() public {
        (bytes memory t, uint256 offs, uint256 iat) = F.tok(0);
        vm.warp(iat + 30);
        vm.expectRevert(abi.encodeWithSelector(EvpCheck.BadClaim.selector, 12));
        a.checkEvp(t, _offs(offs), cfg, bytes32(uint256(CTX) ^ 1));
    }

    /// The tokens were minted about 8 days after the vector's deadline, and they name 0xeeee.., which has no
    /// (qx, qy), so frame 1 cannot take them either. They never run the body or evpVerify.
    function test_liveToken_cannotReachBody() public {
        (bytes memory t, uint256 offs, uint256 iat) = F.tok(0);
        require(iat > DEADLINE, "vector deadline moved");
        vm.warp(iat + 30);
        vm.prank(address(a));
        vm.expectRevert(EvpRecoveryAccountLogic.Expired.selector);
        a.startRotationEvp(NEWKEY, TH, DEADLINE, cfg, t, _offs(offs));
    }
}
