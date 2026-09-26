// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Test.sol";
import {PopSafeBase, ISafe} from "./utils/PopSafeBase.sol";
import {PopSafeGuard} from "../src/PopSafeGuard.sol";
import {NoirPresenceVerifier} from "../src/verifiers/NoirPresenceVerifier.sol";
import {IPopPresenceVerifier, IHonkVerifier} from "../src/interfaces/IPopPresenceVerifier.sol";
import {PopCtx} from "../src/lib/PopCtx.sol";
import {MockHonkVerifier} from "./mocks/MockHonkVerifier.sol";

/// Guard + NoirPresenceVerifier (option A public-input linking) with mock Honk verifiers.
contract NoirPresenceTest is PopSafeBase {
    MockHonkVerifier phone;
    MockHonkVerifier pair;
    NoirPresenceVerifier nv;
    uint64 constant MAX_AGE = 900;
    bytes16 constant SID = 0x00112233445566778899aabbccddeeff;

    function _verifier() internal override returns (IPopPresenceVerifier) {
        vm.warp(1_790_000_100);
        phone = new MockHonkVerifier(12);
        pair = new MockHonkVerifier(7);
        nv = new NoirPresenceVerifier(IHonkVerifier(address(phone)), IHonkVerifier(address(pair)), MAX_AGE);
        return nv;
    }

    function _bundle(bytes32 h) internal view returns (NoirPresenceVerifier.Bundle memory b) {
        b.notBefore = uint64(block.timestamp - 60);
        b.sid = SID;
        (bytes32 hi, bytes32 lo) = PopCtx.split(PopCtx.nonce(block.chainid, address(safe), h, b.notBefore, SID));
        (uint256 qx, uint256 qy) = _issuerKey();
        b.pubA = new bytes32[](12);
        b.pubB = new bytes32[](12);
        b.pubPair = new bytes32[](7);
        for (uint256 r; r < 2; r++) {
            bytes32[] memory v = r == 0 ? b.pubA : b.pubB;
            v[0] = hi;
            v[1] = lo;
            v[2] = bytes32(uint256(1)); // attempt
            v[3] = bytes32(r);
            v[4] = keccak256(abi.encode("code", r));
            v[5] = bytes32(qx >> 128);
            v[6] = bytes32(uint256(uint128(qx)));
            v[7] = bytes32(qy >> 128);
            v[8] = bytes32(uint256(uint128(qy)));
            v[9] = bytes32(uint256(48000));
            v[10] = bytes32(block.timestamp - 30); // valid_at
            v[11] = keccak256(abi.encode("half", r));
        }
        b.pubPair[0] = hi;
        b.pubPair[1] = lo;
        b.pubPair[2] = bytes32(uint256(1));
        b.pubPair[3] = b.pubA[11];
        b.pubPair[4] = b.pubB[11];
        b.pubPair[5] = bytes32(uint256(48000));
        b.pubPair[6] = bytes32(uint256(48000));
        b.proofA = hex"aa";
        b.proofB = hex"bb";
        b.proofPair = hex"cc";
    }

    function _presenceFor(bytes32 h, uint256, uint256) internal view override returns (bytes memory) {
        return abi.encode(_bundle(h));
    }

    function _sigsWith(bytes32 h, NoirPresenceVerifier.Bundle memory b) internal view returns (bytes memory) {
        return abi.encodePacked(_sigs(h, oA, oB), frame(abi.encode(b)));
    }

    function test_spend_noir() public {
        uint256 g = gasleft();
        assertTrue(exec(bob, 0.1 ether, "", oA, oB, 1, 1));
        console.log("spend via Noir adapter (mock verifiers), gas", g - gasleft());
        assertEq(bob.balance, 0.1 ether);
    }

    function test_noir_device_owners_must_sign() public {
        vm.expectRevert(PopSafeGuard.PresentOwnersMustSign.selector);
        this.exec(bob, 1, "", rec, oA, 1, 1);
        vm.expectRevert(PopSafeGuard.PresentOwnersMustSign.selector);
        this.exec(bob, 1, "", rec, rec2, 1, 1);
        vm.expectRevert(PopSafeGuard.NoPresence.selector);
        this.exec(bob, 1, "", oA, oB, 0, 0);
    }

    function _expectBad(bytes32 h, NoirPresenceVerifier.Bundle memory b, bytes memory err) internal {
        bytes memory sigs = _sigsWith(h, b);
        vm.expectRevert(err);
        this.execRaw(bob, 1, "", 0, 0, sigs);
    }

    function test_noir_linking_rejections() public {
        bytes32 h = _h(bob, 1, "");
        bytes4 sel = NoirPresenceVerifier.BadPublicInputs.selector;
        NoirPresenceVerifier.Bundle memory b;

        b = _bundle(_h(bob, 2, "")); // proofs for another tx (wrong safeTxHash)
        _expectBad(h, b, abi.encodeWithSelector(sel, 1));
        b = _bundle(h);
        b.sid = bytes16(uint128(1)); // nonce rebuilt from other sid
        _expectBad(h, b, abi.encodeWithSelector(sel, 1));
        b = _bundle(h);
        b.pubPair[1] = bytes32(uint256(b.pubPair[1]) ^ 1);
        _expectBad(h, b, abi.encodeWithSelector(sel, 1));
        b = _bundle(h);
        b.pubB[2] = bytes32(uint256(2)); // attempt mismatch
        _expectBad(h, b, abi.encodeWithSelector(sel, 2));
        b = _bundle(h);
        (b.pubA[3], b.pubB[3]) = (b.pubB[3], b.pubA[3]); // roles swapped
        _expectBad(h, b, abi.encodeWithSelector(sel, 3));
        b = _bundle(h);
        b.pubB[3] = bytes32(0); // one phone proving both roles
        _expectBad(h, b, abi.encodeWithSelector(sel, 3));
        b = _bundle(h);
        b.pubA[6] = bytes32(uint256(7)); // other issuer
        _expectBad(h, b, abi.encodeWithSelector(sel, 4));
        b = _bundle(h);
        b.pubPair[6] = bytes32(uint256(44100)); // sr
        _expectBad(h, b, abi.encodeWithSelector(sel, 5));
        b = _bundle(h);
        b.pubPair[3] = bytes32(uint256(5)); // pair proof over other halves
        _expectBad(h, b, abi.encodeWithSelector(sel, 6));
        b = _bundle(h);
        b.pubPair = new bytes32[](6);
        _expectBad(h, b, abi.encodeWithSelector(sel, 0));
    }

    function test_noir_freshness() public {
        bytes32 h = _h(bob, 1, "");
        NoirPresenceVerifier.Bundle memory b = _bundle(h);
        bytes memory sigs = _sigsWith(h, b);
        vm.warp(block.timestamp + MAX_AGE + 31);
        vm.expectRevert(NoirPresenceVerifier.Stale.selector);
        this.execRaw(bob, 1, "", 0, 0, sigs);

        b = _bundle(h);
        b.pubA[10] = bytes32(uint256(b.notBefore) - 1); // measured before the session existed
        b.pubB[10] = b.pubA[10];
        _expectBad(h, b, abi.encodeWithSelector(NoirPresenceVerifier.Stale.selector));
        b = _bundle(h);
        b.pubB[10] = bytes32(uint256(b.pubB[10]) + 1);
        _expectBad(h, b, abi.encodeWithSelector(NoirPresenceVerifier.Stale.selector));
    }

    function test_noir_proof_rejected() public {
        bytes32 h = _h(bob, 1, "");
        phone.set(false, 0);
        _expectBad(h, _bundle(h), abi.encodeWithSelector(NoirPresenceVerifier.ProofRejected.selector, 0));
        phone.set(true, 0);
        pair.set(false, 0);
        _expectBad(h, _bundle(h), abi.encodeWithSelector(NoirPresenceVerifier.ProofRejected.selector, 2));
    }

    /// Budget check with mocks burning the measured research gas (2 x phone + pair); the real-verifier
    /// numbers are in NoirRealGasTest.
    function test_noir_gas_budget_mock() public {
        phone.set(true, 2_730_000);
        pair.set(true, 2_230_000);
        uint256 g = gasleft();
        assertTrue(exec(bob, 1, "", oA, oB, 1, 1));
        uint256 used = g - gasleft();
        console.log("guard path, mock verifiers burning 2x2.73M + 2.23M, gas", used);
        assertLt(used, 16_777_216);
    }
}
