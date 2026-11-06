// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Test.sol";
import {PopSafeBase, ISafe, IHandler, MockPermitToken} from "./utils/PopSafeBase.sol";
import {PopSafeGuard} from "../src/PopSafeGuard.sol";
import {P256Owner} from "../src/P256Owner.sol";
import {PopAttestationVerifier} from "../src/verifiers/PopAttestationVerifier.sol";
import {IPopPresenceVerifier} from "../src/interfaces/IPopPresenceVerifier.sol";

/// Acceptance (spec 02 §4.6, adapted): guard + P256Owner + POP2 attestation verifier on a real Safe 1.5.0.
abstract contract PopSafeAttestationTests is PopSafeBase {
    PopAttestationVerifier att;
    uint64 expiry; // 0 = now + 900
    uint256 issuerK = ISSUER;
    bytes32 constant PAIR_TAG = bytes32(uint256(0x33));

    function _verifier() internal override returns (IPopPresenceVerifier) {
        att = new PopAttestationVerifier();
        return att;
    }

    function _presenceFor(bytes32 h, uint256 px, uint256 py) internal view override returns (bytes memory) {
        uint64 e = expiry == 0 ? uint64(block.timestamp + 900) : expiry;
        bytes32 d = att.digest(block.chainid, address(safe), h, PAIR_TAG, dev(px), dev(py), e);
        (bytes32 r, bytes32 s) = vm.signP256(issuerK, d);
        return abi.encodePacked(PAIR_TAG, dev(px), dev(py), e, r, s, bytes4(0x504f5032));
    }

    // ---------------- setup ----------------

    function test_setup_state() public view {
        assertEq(address(uint160(uint256(vm.load(address(safe), GUARD_SLOT)))), address(guard));
        assertEq(uint256(vm.load(address(safe), FALLBACK_SLOT)), 0);
        assertEq(guard.deviceOwner(address(safe), dev(PHONE_A)), oA);
        assertEq(guard.deviceOwner(address(safe), dev(PHONE_B)), oB);
        assertEq(guard.deviceCount(address(safe), oA), 1);
        assertEq(address(guard.verifier()), address(att));
        assertEq(safe.getThreshold(), 2);
        assertTrue(safe.isOwner(rec));
        assertEq(safe.VERSION(), "1.5.0");
        assertTrue(guard.supportsInterface(0xe6d7a83a));
    }

    // ---------------- happy path ----------------

    function test_spend_two_phone_owners() public {
        uint256 g = gasleft();
        assertTrue(exec(bob, 0.1 ether, "", oA, oB, PHONE_A, PHONE_B));
        console.log("spend: 2x P256Owner sigs + POP2 verifier + guard, gas", g - gasleft());
        assertEq(bob.balance, 0.1 ether);
        assertTrue(exec(bob, 0.1 ether, "", oB, oA, PHONE_B, PHONE_A)); // role order irrelevant
        assertEq(bob.balance, 0.2 ether);
        vm.expectRevert(PopSafeGuard.PresentOwnersMustSign.selector); // a guardian can't stand in for a phone owner
        this.exec(bob, 0.1 ether, "", rec, oA, PHONE_A, PHONE_B);
    }

    // ---------------- missing / invalid / replayed presence ----------------

    function test_missing_presence() public {
        vm.expectRevert(PopSafeGuard.NoPresence.selector);
        this.exec(bob, 1, "", oA, oB, 0, 0);
    }

    function test_invalid_presence() public {
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(bob, 1, "", oA, oB, PHONE_A, STRANGER);

        vm.warp(block.timestamp + 1000);
        expiry = uint64(block.timestamp - 1);
        vm.expectRevert(PopAttestationVerifier.Expired.selector);
        this.exec(bob, 1, "", oA, oB, PHONE_A, PHONE_B);
        expiry = 0;

        issuerK = 0xBAD;
        vm.expectRevert(PopAttestationVerifier.BadAttestation.selector);
        this.exec(bob, 1, "", oA, oB, PHONE_A, PHONE_B);
        issuerK = ISSUER;

        // flipped byte in the attestation
        bytes32 h = _h(bob, 1, "");
        bytes memory p = _presenceFor(h, PHONE_A, PHONE_B);
        p[110] ^= 0x01;
        bytes memory sigs = abi.encodePacked(_sigs(h, oA, oB), frame(p));
        vm.expectRevert(PopAttestationVerifier.BadAttestation.selector);
        this.execRaw(bob, 1, "", 0, 0, sigs);

        // wrong length / missing "POP2" inside the frame
        sigs = abi.encodePacked(_sigs(h, oA, oB), frame(hex"deadbeef"));
        vm.expectRevert(PopAttestationVerifier.BadAttestation.selector);
        this.execRaw(bob, 1, "", 0, 0, sigs);

        // frame length larger than the signatures
        sigs = abi.encodePacked(_sigs(h, oA, oB), uint32(10_000), POPV);
        vm.expectRevert(PopSafeGuard.BadPresence.selector);
        this.execRaw(bob, 1, "", 0, 0, sigs);
    }

    function test_wrong_safeTxHash() public {
        // presence made for a different tx (other amount) is useless for this one
        bytes32 h = _h(bob, 1, "");
        bytes32 other = _h(bob, 0.5 ether, "");
        bytes memory sigs = abi.encodePacked(_sigs(h, oA, oB), frame(_presenceFor(other, PHONE_A, PHONE_B)));
        vm.expectRevert(PopAttestationVerifier.BadAttestation.selector);
        this.execRaw(bob, 1, "", 0, 0, sigs);
        // and for another Safe with the same tx fields
        ISafe s2 = _create(_owners(), _devs(), _devOwners(), address(0), DELAY, 99);
        vm.deal(address(s2), 1 ether);
        bytes32 h2 = s2.getTransactionHash(bob, 1, "", 0, 0, 0, 0, address(0), address(0), s2.nonce());
        bytes memory sigs2 = abi.encodePacked(_sigs(h2, oA, oB), frame(_presenceFor(h2, PHONE_A, PHONE_B))); // bound to `safe`, not s2
        vm.expectRevert(PopAttestationVerifier.BadAttestation.selector);
        s2.execTransaction(bob, 1, "", 0, 0, 0, 0, address(0), payable(address(0)), sigs2);
    }

    function test_replay() public {
        bytes32 h = _h(bob, 0.1 ether, "");
        bytes memory p = _presenceFor(h, PHONE_A, PHONE_B);
        bytes memory sigs = abi.encodePacked(_sigs(h, oA, oB), frame(p));
        assertTrue(execRaw(bob, 0.1 ether, "", 0, 0, sigs));
        // exact same calldata again: nonce moved, owner sigs no longer match
        vm.expectRevert(bytes("GS024"));
        this.execRaw(bob, 0.1 ether, "", 0, 0, sigs);
        // fresh owner sigs for the new nonce, old presence: rejected
        bytes32 h2 = _h(bob, 0.1 ether, "");
        bytes memory sigs2 = abi.encodePacked(_sigs(h2, oA, oB), frame(p));
        vm.expectRevert(PopAttestationVerifier.BadAttestation.selector);
        this.execRaw(bob, 0.1 ether, "", 0, 0, sigs2);
        assertEq(bob.balance, 0.1 ether);
    }

    // ---------------- owner / call rules ----------------

    function test_call_rules() public {
        vm.expectRevert(PopSafeGuard.DelegateCallNotAllowed.selector);
        this.execOp(bob, 0, hex"8d80ff0a", 1, 0, oA, oB, PHONE_A, PHONE_B);
        vm.expectRevert(PopSafeGuard.RefundNotAllowed.selector);
        this.execOp(bob, 1, "", 0, 1, oA, oB, PHONE_A, PHONE_B);
        vm.expectRevert(PopSafeGuard.ForbiddenSelfCall.selector);
        this.exec(address(safe), 0, abi.encodeCall(ISafe.enableModule, (bob)), oA, oB, PHONE_A, PHONE_B);
        vm.expectRevert(PopSafeGuard.ForbiddenSelfCall.selector); // fallback handler would re-open EIP-1271
        this.exec(address(safe), 0, abi.encodeCall(ISafe.setFallbackHandler, (fallbackHandler)), oA, oB, PHONE_A, PHONE_B);
        // same owner holding two registered phones
        assertTrue(exec(address(guard), 0, abi.encodeCall(PopSafeGuard.addDevice, (dev(PHONE_A2), oA)), oA, oB, PHONE_A, PHONE_B));
        vm.expectRevert(PopSafeGuard.SameOwner.selector);
        this.exec(bob, 1, "", oA, oB, PHONE_A, PHONE_A2);
        vm.expectRevert(PopSafeGuard.SameOwner.selector); // one phone twice
        this.exec(bob, 1, "", oA, oB, PHONE_A, PHONE_A);
    }

    function test_guardians_cannot_spend() public {
        vm.expectRevert(PopSafeGuard.NoPresence.selector);
        this.exec(bob, 0.1 ether, "", rec, rec2, 0, 0);
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(bob, 0.1 ether, "", rec, rec2, PHONE_A, STRANGER);
        vm.expectRevert(PopSafeGuard.PresentOwnersMustSign.selector); // even with valid presence for the owners' phones
        this.exec(bob, 0.1 ether, "", rec, rec2, PHONE_A, PHONE_B);
    }

    /// Guardians G1+G2 sign an EIP-2612 permit for the Safe (EIP-1271). With CompatibilityFallbackHandler it works
    /// (no guard involved); with fallbackHandler = 0 it must fail.
    function test_guardian_1271_permit_blocked() public {
        MockPermitToken tok = new MockPermitToken();
        ISafe bad = _create(_owners(), _devs(), _devOwners(), fallbackHandler, DELAY, 2); // control: with handler
        assertTrue(_permit(tok, bad), "control: handler lets G1+G2 sign for the Safe");
        assertFalse(_permit(tok, safe), "fallbackHandler=0: G1+G2 permit must fail");
        assertEq(tok.allowance(address(safe), bob), 0);
    }

    function _permit(MockPermitToken tok, ISafe s) internal returns (bool) {
        uint256 deadline = block.timestamp + 3600;
        bytes32 digest = tok.digestFor(address(s), bob, type(uint256).max, deadline);
        bytes32 mh = IHandler(fallbackHandler).getMessageHashForSafe(address(s), abi.encode(digest));
        (uint8 v1, bytes32 r1, bytes32 s1) = vm.sign(recK, mh);
        (uint8 v2, bytes32 r2, bytes32 s2) = vm.sign(rec2K, mh);
        bytes memory sig =
            rec < rec2 ? abi.encodePacked(r1, s1, v1, r2, s2, v2) : abi.encodePacked(r2, s2, v2, r1, s1, v1);
        try tok.permit(address(s), bob, type(uint256).max, deadline, sig) {
            return true;
        } catch {
            return false;
        }
    }

    // ---------------- escape hatch (§5) ----------------

    function test_announce_griefing_does_not_block_presence_path() public {
        uint256 n = safe.nonce();
        bytes memory unset = abi.encodeCall(ISafe.setGuard, (address(0)));
        vm.prank(rec);
        guard.announce(address(safe), address(safe), unset, n);
        vm.prank(rec);
        vm.expectRevert(PopSafeGuard.AlreadyAnnounced.selector);
        guard.announce(address(safe), address(safe), unset, n);
        vm.prank(rec);
        vm.expectRevert(PopSafeGuard.NotRecoveryTx.selector); // spends can't be announced
        guard.announce(address(safe), bob, "", n);
        assertTrue(exec(bob, 0.1 ether, "", oA, oB, PHONE_A, PHONE_B)); // presence path ignores announcements
    }

    function test_hatch_reinstall_A() public {
        address oA2 = ownerFor(PHONE_A2);
        uint256 n = safe.nonce();
        bytes memory swap = abi.encodeCall(ISafe.swapOwner, (address(1), oA, oA2)); // SENTINEL->oA->oB->rec->rec2
        bytes memory add = abi.encodeCall(PopSafeGuard.addDevice, (dev(PHONE_A2), oA2));
        vm.prank(bob);
        vm.expectRevert(PopSafeGuard.NotOwner.selector);
        guard.announce(address(safe), address(safe), swap, n);
        vm.startPrank(rec);
        guard.announce(address(safe), address(safe), swap, n);
        guard.announce(address(safe), address(guard), add, n + 1);
        vm.stopPrank();
        vm.expectRevert(PopSafeGuard.TooEarly.selector);
        this.exec(address(safe), 0, swap, rec, rec2, 0, 0);
        vm.warp(block.timestamp + DELAY);
        assertTrue(exec(address(safe), 0, swap, rec, rec2, 0, 0));
        assertTrue(exec(address(guard), 0, add, rec, rec2, 0, 0));
        assertEq(guard.deviceOwner(address(safe), dev(PHONE_A2)), oA2);
        // old phone key still maps to oA, but oA is no longer an owner
        vm.expectRevert(PopSafeGuard.UnknownDevice.selector);
        this.exec(bob, 0.1 ether, "", oA2, oB, PHONE_A, PHONE_B);
        assertTrue(exec(bob, 0.1 ether, "", oA2, oB, PHONE_A2, PHONE_B));
        vm.expectRevert(PopSafeGuard.NoPresence.selector);
        this.exec(bob, 0.1 ether, "", rec, rec2, 0, 0);
    }

    function test_hatch_remove_guard() public {
        bytes memory unset = abi.encodeCall(ISafe.setGuard, (address(0)));
        uint256 n = safe.nonce();
        vm.prank(rec);
        guard.announce(address(safe), address(safe), unset, n);
        vm.warp(block.timestamp + DELAY);
        assertTrue(exec(address(safe), 0, unset, rec, rec2, 0, 0));
        assertEq(uint256(vm.load(address(safe), GUARD_SLOT)), 0);
        // now a plain 2-of-4: guardians can spend
        assertTrue(exec(bob, 0.1 ether, "", rec, rec2, 0, 0));
    }

    function test_hatch_rotate_issuer() public {
        (uint256 qx, uint256 qy) = vm.publicKeyP256(0xC0FFEE2);
        bytes memory iss = abi.encodeCall(PopSafeGuard.setIssuer, (qx, qy));
        uint256 n = safe.nonce();
        vm.prank(rec2);
        guard.announce(address(safe), address(guard), iss, n);
        vm.warp(block.timestamp + DELAY + 1);
        assertTrue(exec(address(guard), 0, iss, rec, rec2, 0, 0));
        vm.expectRevert(PopAttestationVerifier.BadAttestation.selector); // old server key is dead
        this.exec(bob, 1, "", oA, oB, PHONE_A, PHONE_B);
        issuerK = 0xC0FFEE2;
        assertTrue(exec(bob, 1, "", oA, oB, PHONE_A, PHONE_B));
    }

    function test_announce_window_and_grace() public {
        uint256 n = safe.nonce();
        vm.startPrank(rec);
        for (uint256 i = 4; i <= 20; i++) {
            bytes memory d = abi.encodeCall(PopSafeGuard.setIssuer, (i, i));
            vm.expectRevert(PopSafeGuard.BadNonce.selector);
            guard.announce(address(safe), address(guard), d, n + i);
        }
        bytes memory unset = abi.encodeCall(ISafe.setGuard, (address(0)));
        guard.announce(address(safe), address(safe), unset, n);
        vm.stopPrank();
        vm.warp(block.timestamp + DELAY + GRACE + 1);
        vm.expectRevert(PopSafeGuard.AnnouncementExpired.selector);
        this.exec(address(safe), 0, unset, rec, rec2, 0, 0);
        vm.prank(rec);
        guard.announce(address(safe), address(safe), unset, n); // re-announce restarts the full delay
        vm.expectRevert(PopSafeGuard.TooEarly.selector);
        this.exec(address(safe), 0, unset, rec, rec2, 0, 0);
    }

    function test_cancelAll_presence_path() public {
        uint256 n = safe.nonce();
        bytes memory unset = abi.encodeCall(ISafe.setGuard, (address(0)));
        bytes memory iss = abi.encodeCall(PopSafeGuard.setIssuer, (1, 2));
        vm.startPrank(rec);
        guard.announce(address(safe), address(safe), unset, n + 1);
        guard.announce(address(safe), address(guard), iss, n + 2);
        vm.stopPrank();
        assertTrue(exec(address(guard), 0, abi.encodeCall(PopSafeGuard.cancelAll, ()), oA, oB, PHONE_A, PHONE_B));
        vm.warp(block.timestamp + DELAY);
        vm.expectRevert(PopSafeGuard.NoPresence.selector);
        this.exec(address(safe), 0, unset, rec, rec2, 0, 0);
    }

    function test_setGuard_to_uninitialized_guard_refused() public {
        PopSafeGuard g2 = new PopSafeGuard(att);
        bytes memory sg = abi.encodeCall(ISafe.setGuard, (address(g2)));
        vm.expectRevert(PopSafeGuard.GuardNotReady.selector);
        this.exec(address(safe), 0, sg, oA, oB, PHONE_A, PHONE_B);
        (uint256 qx, uint256 qy) = vm.publicKeyP256(ISSUER);
        assertTrue(
            exec(address(g2), 0, abi.encodeCall(PopSafeGuard.initSafe, (qx, qy, 900, 900, _devs(), _devOwners())), oA, oB, PHONE_A, PHONE_B)
        );
        assertTrue(exec(address(safe), 0, sg, oA, oB, PHONE_A, PHONE_B));
        assertEq(address(uint160(uint256(vm.load(address(safe), GUARD_SLOT)))), address(g2));
    }

    function test_threshold_floor_and_min_delay() public {
        uint256 n = safe.nonce();
        vm.startPrank(rec);
        vm.expectRevert(PopSafeGuard.NotRecoveryTx.selector);
        guard.announce(address(safe), address(safe), abi.encodeWithSelector(0x694e80c3, uint256(1)), n);
        vm.expectRevert(PopSafeGuard.NotRecoveryTx.selector);
        guard.announce(address(safe), address(safe), abi.encodeWithSelector(0xf8dc5dd9, address(1), oA, uint256(1)), n);
        vm.expectRevert(PopSafeGuard.NotRecoveryTx.selector);
        guard.announce(address(safe), address(safe), abi.encodeCall(ISafe.addOwnerWithThreshold, (bob, 1)), n);
        vm.stopPrank();
        vm.expectRevert(PopSafeGuard.ForbiddenSelfCall.selector);
        this.exec(address(safe), 0, abi.encodeWithSelector(0x694e80c3, uint256(1)), oA, oB, PHONE_A, PHONE_B);
        (address[] memory ow, bytes32[] memory ds, address[] memory dos) = (_owners(), _devs(), _devOwners());
        vm.expectRevert(); // initSafe refuses delay < MIN_DELAY; Safe.setup bubbles, the factory reverts
        this.createExt(ow, ds, dos, address(0), 0, 7);
    }

    // ---------------- vectors ----------------

    function test_phone_signature_parity() public view {
        // Python `cryptography` ECDSA(SHA256) over M = "pop-safe-owner-v1" || h, key 0xA1 (= Android SHA256withECDSA)
        P256Owner o = P256Owner(
            pf.ownerOf(
                0x33722147e2b1ac751bcda5630b9799c3323a5d85dfe902183bce4640e52ae125,
                0x03d7566a889ae6b64bcebd5e74c61458ce9cd27a640e4fc7df67cbacfb5eebf4
            )
        );
        assertEq(address(o), oA);
        bytes32 h = 0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5;
        bytes memory sig = abi.encodePacked(
            bytes32(0x76a33345d9c2e60b4cdab2063ca4f19855b058ba269a1408f9420dcbd7cfe842),
            bytes32(0x9c52547d6bf37b06a7614c1cd6ede11f15a7fe439aeab9cedd478b652e661fba) // high-s on purpose
        );
        assertEq(o.isValidSignature(h, sig), bytes4(0x1626ba7e));
        assertEq(dev(PHONE_A), 0x363b91cc982452b82ebd0195c163c65399e46dcbba27fb04959665808e0e53d5);
        sig[63] ^= 0x01;
        assertEq(o.isValidSignature(h, sig), bytes4(0xffffffff));
        assertEq(o.isValidSignature(h, hex"00"), bytes4(0xffffffff));
    }

    function test_digest_vector() public view {
        assertEq(
            att.digest(
                480,
                0x1111111111111111111111111111111111111111,
                bytes32(uint256(0x22)),
                bytes32(uint256(0x33)),
                bytes32(uint256(0x44)),
                bytes32(uint256(0x55)),
                1790000000
            ),
            0x923a0f96071090da810c42c7f0c43c56fefd454497a45fcde7138b1a45829720
        );
    }
}

/// Local EVM (osaka: 0x100 = EIP-7951), Safe 1.5.0 compiled from lib/safe-smart-account v1.5.0.
contract PopSafeTest is PopSafeAttestationTests {}

/// Ethereum Sepolia fork: real 0x100 precompile + canonical Safe 1.5.0 singleton/factory/handler.
/// Run: FORK=1 forge test --match-contract PopSafeForkTest   (skipped otherwise)
contract PopSafeForkTest is PopSafeAttestationTests {
    function _infra() internal override {
        vm.createSelectFork("sepolia");
        assertEq(block.chainid, 11155111);
        factory = SEPOLIA_FACTORY;
        singleton = SEPOLIA_SAFE_L2;
        fallbackHandler = SEPOLIA_FALLBACK;
    }

    function setUp() public override {
        if (!vm.envOr("FORK", false)) {
            vm.skip(true);
            return;
        }
        super.setUp();
    }
}
