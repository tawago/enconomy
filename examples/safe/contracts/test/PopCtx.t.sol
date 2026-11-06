// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Test.sol";
import {PopCtx} from "../src/lib/PopCtx.sol";
import {PopAttest} from "../src/lib/PopAttest.sol";

/// Golden vectors from spec 01 §5 / §8.2 (computed for chainId 480; the formula is chain-agnostic).
contract PopCtxTest is Test {
    address constant SAFE = 0x5afe5afE5afE5afE5afE5aFe5aFe5Afe5Afe5AfE;
    address constant GUARD = 0x6a7D6a7D6A7d6a7D6A7D6A7d6A7D6A7D6a7d6A7D;
    uint256 constant CHAIN = 480;
    uint64 constant NB = 1790000000;
    bytes16 constant SID = 0x00112233445566778899aabbccddeeff;
    bytes32 constant CTX = 0xa0a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbebf;

    function test_domain() public pure {
        assertEq(PopCtx.DOMAIN, keccak256("pop-ctx-v1"));
    }

    function test_golden_G() public pure {
        bytes32 n = PopCtx.nonce(CHAIN, SAFE, CTX, NB, SID);
        assertEq(n, 0x2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c9);
        assertEq(PopCtx.signalHash(n, 0x41), 0x002916db5141cfe5584c6de9cf6f45579e83422ecdf3260c31e30bc7f2b964c6);
        assertEq(PopCtx.signalHash(n, 0x42), 0x0097c2b664c193be4b2699e4224cd1c6c3bb1f8de93919ebee7d7e346f25ff2b);
        assertEq(abi.encode(PopCtx.DOMAIN, CHAIN, SAFE, CTX, NB, SID).length, 192);
    }

    function test_golden_N() public pure {
        bytes32 n = PopCtx.nonce(
            480, 0x3FAD7600f309B0C3d60a57023b0262460B0603dc, 0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5, NB, SID
        );
        assertEq(n, 0x9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121);
        assertEq(PopCtx.signalHash(n, 0x41), 0x008f770c3f6700ffa8277d98ae286f59448b26c40ecc9b59eb4236aec76f5637);
        assertEq(PopCtx.signalHash(n, 0x42), 0x00e9c210433251df53d3a8650bc8f0b54e5ad84ffcc0593e2785d0778f92199a);
    }

    function test_pool_and_action() public pure {
        assertEq(
            PopCtx.nonce(CHAIN, 0x9001900190019001900190019001900190019001, CTX, NB, SID),
            0xab8e50bb766db52b752932e48a63148cf015ac1a17c1345c35d4765f51027d66
        );
        assertEq(PopCtx.actionOf(SID), 0x003d0a5a51f4fe9954190e3c33adb92f760da336203f33ee63a29ad4ee6fd8ae);
    }

    function test_traps() public pure {
        assertEq(keccak256(abi.encode("pop-ctx-v1", CHAIN, GUARD, CTX, NB, SID)), 0x5acffbeffd0ba155be27ac0beba39e9100dd749fc15b72ca842a6855cf78becf);
        assertEq(keccak256(abi.encode("pop-ctx-v1", CHAIN, SAFE, CTX, NB, SID)), 0x36603c76b65742d4039f5fb98950286cfeac74c033b263139045e8beaf472430);
        assertEq(PopCtx.nonce(CHAIN, GUARD, CTX, NB, SID), 0xa0b4077ef6736018b1ddbc33a5d4b3e3c28a211f1a52566e6d400f7aecd6ff8b);
        assertEq(keccak256(abi.encode(PopCtx.DOMAIN, CHAIN, SAFE, CTX, NB, uint128(SID))), 0xa3993cf3f5bce4adc7c16d5e5c9c50e78dbde87ce9e1b933ad53fc8665440661);
    }

    function test_split() public pure {
        (bytes32 hi, bytes32 lo) = PopCtx.split(0x2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c9);
        assertEq(hi, bytes32(uint256(0x2b9a8528bf222c8cf60dd97fb4161833)));
        assertEq(lo, bytes32(uint256(0x76bd4bc5425b29c02583518590ef75c9)));
    }

    function test_attest_digest_vector() public pure {
        assertEq(
            PopAttest.safeDigest(480, 0x1111111111111111111111111111111111111111, bytes32(uint256(0x22)), bytes32(uint256(0x33)), bytes32(uint256(0x44)), bytes32(uint256(0x55)), 1790000000),
            0x923a0f96071090da810c42c7f0c43c56fefd454497a45fcde7138b1a45829720
        );
    }

    /// spec 02 §4.3 vector through the precompile (local EVM must be osaka)
    function test_p256_precompile() public view {
        bytes32 h = 0xe0005ceaee59d61859d4a867fc15897bbfeca13f9c737ebb6959cdde31f2b25d;
        bytes32 r = 0x76a33345d9c2e60b4cdab2063ca4f19855b058ba269a1408f9420dcbd7cfe842;
        bytes32 s = 0x9c52547d6bf37b06a7614c1cd6ede11f15a7fe439aeab9cedd478b652e661fba;
        uint256 x = 0x33722147e2b1ac751bcda5630b9799c3323a5d85dfe902183bce4640e52ae125;
        uint256 y = 0x03d7566a889ae6b64bcebd5e74c61458ce9cd27a640e4fc7df67cbacfb5eebf4;
        assertTrue(PopAttest.p256(h, r, s, x, y));
        assertFalse(PopAttest.p256(h ^ bytes32(uint256(1)), r, s, x, y));
    }
}
