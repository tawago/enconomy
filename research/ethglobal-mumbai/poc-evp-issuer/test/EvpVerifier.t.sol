// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {EvpVerifier} from "../src/EvpVerifier.sol";
import {Fixture} from "./Fixture.sol";

contract EvpVerifierTest is Test {
    EvpVerifier v;

    function setUp() public {
        v = new EvpVerifier(Fixture.ISSUER_X, Fixture.ISSUER_Y, Fixture.EVT_HEADER_B64, Fixture.EMAIL, Fixture.AUD, 600);
        vm.warp(Fixture.IAT + 30);
    }

    function _calldataCost(bytes memory cd) internal pure returns (uint256 std, uint256 floorTokens) {
        uint256 z;
        for (uint256 i; i < cd.length; ++i) {
            if (cd[i] == 0) z++;
        }
        uint256 nz = cd.length - z;
        std = 4 * z + 16 * nz; // EIP-2028
        floorTokens = z + 4 * nz; // EIP-7623 tokens
    }

    function test_gas() public {
        bytes memory cd = abi.encodeCall(EvpVerifier.verify, (Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY));
        uint256 g = gasleft();
        (bool ok,) = address(v).staticcall(cd);
        g = g - gasleft();
        assertTrue(ok, "verify reverted");
        (uint256 std, uint256 tok) = _calldataCost(cd);
        emit log_named_uint("token bytes", Fixture.TOKEN.length);
        emit log_named_uint("calldata bytes", cd.length);
        emit log_named_uint("exec gas (call incl. cold account access)", g);
        emit log_named_uint("calldata gas EIP-2028", std);
        emit log_named_uint("tx total standard = 21000 + calldata + exec", 21000 + std + g);
        emit log_named_uint("tx floor EIP-7623 = 21000 + 10*tokens", 21000 + 10 * tok);
    }

    /// Second call: account already warm, so this is ~ the body's own cost (+100 warm CALL).
    /// Closest proxy for what a VERIFY frame charges against MAX_VERIFY_GAS.
    function test_gas_warm() public {
        bytes memory cd = abi.encodeCall(EvpVerifier.verify, (Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY));
        (bool ok0,) = address(v).staticcall(cd);
        assertTrue(ok0);
        uint256 g = gasleft();
        (bool ok,) = address(v).staticcall(cd);
        g = g - gasleft();
        assertTrue(ok);
        emit log_named_uint("exec gas warm", g);
    }

    function test_p256_precompile_alone() public {
        // cost of one 0x100 call from Solidity with abi.encode, warm
        bytes32 h = sha256("x");
        (bytes32 r, bytes32 s) = vm.signP256(1, h);
        (uint256 x, uint256 y) = vm.publicKeyP256(1);
        bytes memory inp = abi.encode(h, r, s, x, y);
        address(0x100).staticcall(inp); // warm
        uint256 g = gasleft();
        (bool ok, bytes memory out) = address(0x100).staticcall(inp);
        g = g - gasleft();
        assertTrue(ok && out.length == 32 && uint256(bytes32(out)) == 1);
        emit log_named_uint("p256 staticcall gas (warm)", g);
    }

    function test_returnsBrowserKey() public view {
        (uint256 bx, uint256 by) = v.verify(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY);
        assertTrue(bx != 0 && by != 0);
    }

    function test_revert_wrongNewKey() public {
        bytes memory k = Fixture.NEW_KEY;
        k[0] ^= 0x01;
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadClaim.selector, 12));
        v.verify(Fixture.TOKEN, Fixture.OFFS, k);
    }

    function test_revert_kbSignedByOtherKey() public {
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadSig.selector, 1));
        v.verify(Fixture.TOKEN_WRONG_KB_KEY, Fixture.OFFS_WRONG_KB_KEY, Fixture.NEW_KEY);
    }

    function test_revert_otherEmail() public {
        EvpVerifier w =
            new EvpVerifier(Fixture.ISSUER_X, Fixture.ISSUER_Y, Fixture.EVT_HEADER_B64, "bob@pop.enconomy.dev", Fixture.AUD, 600);
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadClaim.selector, 5));
        w.verify(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY);
    }

    function test_revert_otherAud() public {
        EvpVerifier w =
            new EvpVerifier(Fixture.ISSUER_X, Fixture.ISSUER_Y, Fixture.EVT_HEADER_B64, Fixture.EMAIL, "https://evil.example", 600);
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadClaim.selector, 11));
        w.verify(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY);
    }

    function test_revert_otherIssuer() public {
        (uint256 x, uint256 y) = vm.publicKeyP256(7);
        EvpVerifier w = new EvpVerifier(x, y, Fixture.EVT_HEADER_B64, Fixture.EMAIL, Fixture.AUD, 600);
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadSig.selector, 0));
        w.verify(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY);
    }

    function test_revert_stale() public {
        vm.warp(Fixture.IAT + 601);
        vm.expectRevert(EvpVerifier.Stale.selector);
        v.verify(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY);
    }

    function test_revert_tamperedEvtPayload() public {
        bytes memory t = Fixture.TOKEN;
        uint256 d1 = Fixture.OFFS & 0xffff;
        t[d1 + 10] = t[d1 + 10] == "A" ? bytes1("B") : bytes1("A");
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadSig.selector, 0));
        v.verify(t, Fixture.OFFS, Fixture.NEW_KEY);
    }

    function test_revert_sdHashOtherEvt() public {
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadClaim.selector, 14));
        v.verify(Fixture.TOKEN_SD_SWAP, Fixture.OFFS_SD_SWAP, Fixture.NEW_KEY);
    }

    function test_revert_tamperedKbPayload() public {
        bytes memory t = Fixture.TOKEN;
        uint256 k1 = (Fixture.OFFS >> 48) & 0xffff;
        t[k1 + 10] = t[k1 + 10] == "A" ? bytes1("B") : bytes1("A");
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadSig.selector, 1));
        v.verify(t, Fixture.OFFS, Fixture.NEW_KEY);
    }

    function test_revert_badHint() public {
        uint256 offs = Fixture.OFFS ^ (1 << (16 * 12)); // shift nonce hint by one
        vm.expectRevert(abi.encodeWithSelector(EvpVerifier.BadClaim.selector, 12));
        v.verify(Fixture.TOKEN, offs, Fixture.NEW_KEY);
    }
}
