// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {EvpVerifier} from "../src/EvpVerifier.sol";
import {LiveFixture as F} from "./LiveFixture.sol";

/// Real Chrome 156 tokens against the unchanged poc-evp-issuer verifier.
contract LiveChromeTest is Test {
    EvpVerifier v;

    function setUp() public {
        v = new EvpVerifier(F.ISSUER_X, F.ISSUER_Y, F.EVT_HEADER_B64, F.EMAIL, F.AUD, 900);
    }

    function test_ctx() public pure {
        assertEq(keccak256(F.PREIMAGE), 0x22cbad28b2d580114630eb65e51e47305a5d6efbbb8c6d48fca64bd7d4b5655a);
    }

    function test_first_token_gas() public {
        (bytes memory t, uint256 offs, uint256 iat) = F.tok(0);
        vm.warp(iat + 30);
        bytes memory cd = abi.encodeCall(EvpVerifier.verify, (t, offs, F.PREIMAGE));
        (bool ok0,) = address(v).staticcall(cd); // warm
        assertTrue(ok0, "verify reverted");
        uint256 g = gasleft();
        (bool ok,) = address(v).staticcall(cd);
        g = g - gasleft();
        assertTrue(ok);
        emit log_named_uint("token bytes", t.length);
        emit log_named_uint("exec gas warm (224-byte preimage as newKey)", g);
    }

    function test_all_tokens() public {
        for (uint256 i; i < F.N; ++i) {
            (bytes memory t, uint256 offs, uint256 iat) = F.tok(i);
            vm.warp(iat + 30);
            (uint256 bx, uint256 by) = v.verify(t, offs, F.PREIMAGE);
            assertTrue(bx != 0 && by != 0);
        }
        emit log_named_uint("tokens verified", F.N);
    }

    function test_revert_other_ctx() public {
        (bytes memory t, uint256 offs, uint256 iat) = F.tok(0);
        vm.warp(iat + 30);
        bytes memory p = F.PREIMAGE;
        p[223] ^= 0x01; // deadline + 1 bit -> other ctx
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadClaim.selector, 12));
        v.verify(t, offs, p);
    }

    function test_revert_other_aud() public {
        EvpVerifier w = new EvpVerifier(F.ISSUER_X, F.ISSUER_Y, F.EVT_HEADER_B64, F.EMAIL, "https://recover.tawago.com", 900);
        (bytes memory t, uint256 offs, uint256 iat) = F.tok(0);
        vm.warp(iat + 30);
        vm.expectRevert();
        w.verify(t, offs, F.PREIMAGE);
    }

    function test_revert_stale() public {
        (bytes memory t, uint256 offs, uint256 iat) = F.tok(0);
        vm.warp(iat + 901);
        vm.expectRevert();
        v.verify(t, offs, F.PREIMAGE);
    }
}
