// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "../src/PopCtx.sol";
contract CtxTest {
    address constant SAFE = 0x5afe5afE5afE5afE5afE5aFe5aFe5Afe5Afe5AfE;
    address constant GUARD = 0x6a7D6a7D6A7d6a7D6A7D6A7d6A7D6A7D6a7d6A7D;
    uint256 constant CHAIN = 480;
    uint64 constant NB = 1790000000;
    bytes16 constant SID = 0x00112233445566778899aabbccddeeff;
    function ctx() internal pure returns (bytes32 c) { c = 0xa0a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbebf; }
    function eq(bytes32 a, bytes32 b) internal pure { require(a == b, "mismatch"); }
    function test_golden() public pure {
        eq(PopCtx.DOMAIN, 0x2c71bde9118937099ebb172d5845794f571cc2982d44a563b229d1ea0db2af2f);
        bytes32 n = PopCtx.sessionNonce(CHAIN, SAFE, ctx(), NB, SID);
        eq(n, 0x2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c9);
        require(PopCtx.signalHash(n, 0x41) == 0x002916db5141cfe5584c6de9cf6f45579e83422ecdf3260c31e30bc7f2b964c6, "A");
        require(PopCtx.signalHash(n, 0x42) == 0x0097c2b664c193be4b2699e4224cd1c6c3bb1f8de93919ebee7d7e346f25ff2b, "B");
    }
    function test_traps() public pure {
        // spec U literally: string literal domain, consumer = guard
        eq(keccak256(abi.encode("pop-ctx-v1", CHAIN, GUARD, ctx(), NB, SID)), 0x5acffbeffd0ba155be27ac0beba39e9100dd749fc15b72ca842a6855cf78becf);
        eq(keccak256(abi.encode("pop-ctx-v1", CHAIN, SAFE, ctx(), NB, SID)), 0x36603c76b65742d4039f5fb98950286cfeac74c033b263139045e8beaf472430);
        eq(PopCtx.sessionNonce(CHAIN, GUARD, ctx(), NB, SID), 0xa0b4077ef6736018b1ddbc33a5d4b3e3c28a211f1a52566e6d400f7aecd6ff8b);
        eq(keccak256(abi.encode(PopCtx.DOMAIN, CHAIN, SAFE, ctx(), NB, uint128(SID))), 0xa3993cf3f5bce4adc7c16d5e5c9c50e78dbde87ce9e1b933ad53fc8665440661);
    }
    function test_chainedRowN() public pure {
        bytes32 n = PopCtx.sessionNonce(480, 0x3FAD7600f309B0C3d60a57023b0262460B0603dc,
            0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5, NB, SID);
        eq(n, 0x9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121);
        require(PopCtx.signalHash(n, 0x41) == 0x008f770c3f6700ffa8277d98ae286f59448b26c40ecc9b59eb4236aec76f5637, "A");
        require(PopCtx.signalHash(n, 0x42) == 0x00e9c210433251df53d3a8650bc8f0b54e5ad84ffcc0593e2785d0778f92199a, "B");
    }
}
