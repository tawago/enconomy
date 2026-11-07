// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Fixture} from "./Fixture.sol";
import {EvpBase} from "./EvpRecovery.t.sol";
import {EvpRecoveryAccountLogic} from "../src/EvpRecoveryAccount.sol";
import {EvpNoirPresenceVerifier as Adapter} from "../src/pop/EvpNoirPresenceVerifier.sol";
import {IHonkVerifier} from "../src/pop/IPopPresenceVerifier.sol";
import {PopCtx} from "../src/pop/PopCtx.sol";

/// Stands in for a bb verifier. No real proof runs in this file. It does look at what it is given: `refuse` turns
/// down one set of proof bytes, and once `bind` has been called a proof passes only with the inputs bound to it.
contract MockHonk is IHonkVerifier {
    uint256 public immutable nPub;
    bool public accept = true;
    bool public strict;
    mapping(bytes32 proof => bool) public refused;
    mapping(bytes32 proof => bytes32 inputs) public bound;

    constructor(uint256 n) {
        nPub = n;
    }

    function setAccept(bool a) external {
        accept = a;
    }

    function refuse(bytes calldata proof) external {
        refused[keccak256(proof)] = true;
    }

    function bind(bytes calldata proof, bytes32[] calldata pub) external {
        strict = true;
        bound[keccak256(proof)] = keccak256(abi.encode(pub));
    }

    function verify(bytes calldata proof, bytes32[] calldata pub) external view returns (bool) {
        require(pub.length == nPub, "input count");
        bytes32 h = keccak256(proof);
        if (refused[h]) return false;
        if (strict && bound[h] != keccak256(abi.encode(pub))) return false;
        return accept;
    }
}

/// The real adapter, with mock Honk verifiers and real POPCC1 P-256 signatures.
contract EvpAdapterTest is EvpBase {
    uint256 constant SK = 0xB0B0;
    uint64 constant MAX_AGE = 900;
    uint256 constant VALID_AT = Fixture.IAT + 10;
    bytes32 constant NONCE = keccak256("pop nonce");

    Adapter ad;
    MockHonk phone;
    MockHonk pair;
    uint256 qx;
    uint256 qy;
    Adapter.Bundle b;

    function setUp() public {
        (qx, qy) = vm.publicKeyP256(SK);
        phone = new MockHonk(12);
        pair = new MockHonk(11);
        ad = new Adapter(phone, pair, MAX_AGE);
        _build(NONCE);
    }

    function _phonePub(bytes32 n, uint256 role) private view returns (bytes32[] memory v) {
        (bytes32 hi, bytes32 lo) = PopCtx.split(n);
        v = new bytes32[](12);
        v[0] = hi;
        v[1] = lo;
        v[2] = bytes32(uint256(1));
        v[3] = bytes32(role);
        v[4] = bytes32(uint256(0xC0DE + role));
        v[5] = bytes32(qx >> 128);
        v[6] = bytes32(uint256(uint128(qx)));
        v[7] = bytes32(qy >> 128);
        v[8] = bytes32(uint256(uint128(qy)));
        v[9] = bytes32(uint256(48000 + role));
        v[10] = bytes32(VALID_AT);
        v[11] = bytes32(uint256(0xCAFE + role));
    }

    function _cc(bytes32 n, bytes1 role, bytes32 code) private pure returns (bytes memory) {
        (bytes32 r, bytes32 s) = vm.signP256(SK, sha256(abi.encodePacked("POPCC1", n, uint8(1), role, code)));
        return abi.encodePacked(r, s);
    }

    /// A bundle every check accepts, built only from the fields the adapter links.
    function _build(bytes32 n) internal {
        (bytes32 hi, bytes32 lo) = PopCtx.split(n);
        bytes32[] memory pa = _phonePub(n, 0);
        bytes32[] memory pb = _phonePub(n, 1);
        bytes32[] memory pp = new bytes32[](11);
        pp[0] = hi;
        pp[1] = lo;
        pp[2] = pa[2];
        pp[3] = pa[11];
        pp[4] = pb[11];
        pp[5] = pa[9];
        pp[6] = pb[9];
        (pp[7], pp[8]) = PopCtx.split(bytes32(LAPTOP_X));
        (pp[9], pp[10]) = PopCtx.split(bytes32(Fixture.PHONE_X));
        b.proofA = hex"aa";
        b.pubA = pa;
        b.proofB = hex"bb";
        b.pubB = pb;
        b.proofPair = hex"cc";
        b.pubPair = pp;
        b.ccSigA = _cc(n, "A", pa[4]);
        b.ccSigB = _cc(n, "B", pb[4]);
    }

    function _run() internal view returns (bytes4) {
        return ad.verifyPresence(
            NONCE, LAPTOP_X, Fixture.PHONE_X, qx, qy, NOT_BEFORE, DEADLINE, abi.encode(b)
        );
    }

    function _fails(bytes memory err) internal {
        bytes memory data = abi.encode(b);
        vm.expectRevert(err);
        ad.verifyPresence(NONCE, LAPTOP_X, Fixture.PHONE_X, qx, qy, NOT_BEFORE, DEADLINE, data);
    }

    function _pub(uint256 w) internal pure returns (bytes memory) {
        return abi.encodeWithSelector(Adapter.BadPublicInputs.selector, w);
    }

    function test_adapter_accept() public view {
        require(_run() == Adapter.verifyPresence.selector, "selector");
    }

    function test_adapter_sevenInputPairRefused() public {
        bytes32[] memory old = new bytes32[](7);
        for (uint256 i = 0; i < 7; i++) {
            old[i] = b.pubPair[i];
        }
        b.pubPair = old;
        _fails(_pub(0));
    }

    function test_adapter_wrongNonce_eachProof() public {
        for (uint256 i = 0; i < 2; i++) {
            bytes32 keep = b.pubA[i];
            b.pubA[i] = bytes32(uint256(keep) ^ 1);
            _fails(_pub(1));
            b.pubA[i] = keep;
            keep = b.pubB[i];
            b.pubB[i] = bytes32(uint256(keep) ^ 1);
            _fails(_pub(1));
            b.pubB[i] = keep;
            keep = b.pubPair[i];
            b.pubPair[i] = bytes32(uint256(keep) ^ 1);
            _fails(_pub(1));
            b.pubPair[i] = keep;
        }
    }

    /// All three proofs consistently about another nonce.
    function test_adapter_wrongNonce_wholeBundle() public {
        _build(keccak256("other"));
        _fails(_pub(1));
    }

    function test_adapter_wrongLaptopDevice_hi() public {
        b.pubPair[7] = bytes32(uint256(b.pubPair[7]) ^ 1);
        _fails(_pub(7));
    }

    function test_adapter_wrongLaptopDevice_lo() public {
        b.pubPair[8] = bytes32(uint256(b.pubPair[8]) ^ 1);
        _fails(_pub(7));
    }

    function test_adapter_wrongNewDevice_hi() public {
        b.pubPair[9] = bytes32(uint256(b.pubPair[9]) ^ 1);
        _fails(_pub(8));
    }

    function test_adapter_wrongNewDevice_lo() public {
        b.pubPair[10] = bytes32(uint256(b.pubPair[10]) ^ 1);
        _fails(_pub(8));
    }

    /// Roles are pinned: laptop = A, phone = B. A session with the two swapped is refused.
    function test_adapter_devicesSwapped() public {
        (b.pubPair[7], b.pubPair[8]) = PopCtx.split(bytes32(Fixture.PHONE_X));
        (b.pubPair[9], b.pubPair[10]) = PopCtx.split(bytes32(LAPTOP_X));
        _fails(_pub(7));
    }

    function test_adapter_attemptMismatch() public {
        b.pubB[2] = bytes32(uint256(2));
        _fails(_pub(2));
    }

    function test_adapter_roleSwapped() public {
        b.pubA[3] = bytes32(uint256(1));
        _fails(_pub(3));
    }

    function test_adapter_otherIssuer() public {
        b.pubB[6] = bytes32(uint256(b.pubB[6]) ^ 1);
        _fails(_pub(4));
    }

    function test_adapter_srNotLinked() public {
        b.pubPair[5] = bytes32(uint256(b.pubPair[5]) + 1);
        _fails(_pub(5));
    }

    function test_adapter_halfCommitNotLinked() public {
        b.pubPair[4] = bytes32(uint256(b.pubPair[4]) + 1);
        _fails(_pub(6));
    }

    function test_adapter_badCodeAttest() public {
        b.ccSigA = b.ccSigB; // the right issuer's sig, over role B's commit
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 0));
        _build(NONCE);
        b.ccSigB = hex"00";
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 1));
    }

    function test_adapter_validAtDiffers() public {
        b.pubB[10] = bytes32(VALID_AT + 1);
        _fails(abi.encodeWithSelector(Adapter.Stale.selector));
    }

    function _withValidAt(uint256 t) private {
        b.pubA[10] = bytes32(t);
        b.pubB[10] = bytes32(t);
    }

    function test_adapter_validAtBeforeNotBefore() public {
        _withValidAt(NOT_BEFORE - 1);
        _fails(abi.encodeWithSelector(Adapter.Stale.selector));
    }

    /// deadline <= valid_at + maxAge. The edge passes, one second older fails. notBefore is lowered for the second
    /// case so the failure comes from the age check, not from valid_at < notBefore.
    function test_adapter_validAtTooOldForDeadline() public {
        _withValidAt(DEADLINE - MAX_AGE);
        require(_run() == Adapter.verifyPresence.selector, "edge");
        _withValidAt(DEADLINE - MAX_AGE - 1);
        bytes memory data = abi.encode(b);
        vm.expectRevert(abi.encodeWithSelector(Adapter.Stale.selector));
        ad.verifyPresence(NONCE, LAPTOP_X, Fixture.PHONE_X, qx, qy, NOT_BEFORE - 1, DEADLINE, data);
    }

    function test_adapter_validAtPastDeadlineSkew() public {
        _withValidAt(DEADLINE + ad.CLOCK_SKEW() + 1);
        _fails(abi.encodeWithSelector(Adapter.Stale.selector));
    }

    function test_adapter_proofRejected() public {
        pair.setAccept(false);
        _fails(abi.encodeWithSelector(Adapter.ProofRejected.selector, 2));
    }

    function test_adapter_phoneProofRejected() public {
        phone.setAccept(false);
        _fails(abi.encodeWithSelector(Adapter.ProofRejected.selector, 0));
    }

    // Every paired check below is hit on each side, one side at a time, so losing either half fails a test.

    function test_adapter_inputCount_eachProof() public {
        b.pubA.push(bytes32(0));
        _fails(_pub(0));
        b.pubA.pop();
        b.pubB.pop();
        _fails(_pub(0));
        b.pubB.push(bytes32(0));
        b.pubPair.push(bytes32(0));
        _fails(_pub(0));
    }

    function test_adapter_attempt_eachSide() public {
        b.pubA[2] = bytes32(uint256(2));
        _fails(_pub(2));
        _build(NONCE);
        b.pubB[2] = bytes32(uint256(2));
        _fails(_pub(2));
        _build(NONCE);
        b.pubPair[2] = bytes32(uint256(2));
        _fails(_pub(2));
    }

    function test_adapter_role_eachSide() public {
        b.pubA[3] = bytes32(uint256(1));
        _fails(_pub(3));
        _build(NONCE);
        b.pubB[3] = bytes32(uint256(0));
        _fails(_pub(3));
    }

    function test_adapter_issuer_everyLimb_eachSide() public {
        for (uint256 i = 5; i <= 8; i++) {
            bytes32 keep = b.pubA[i];
            b.pubA[i] = bytes32(uint256(keep) ^ 1);
            _fails(_pub(4));
            b.pubA[i] = keep;
            keep = b.pubB[i];
            b.pubB[i] = bytes32(uint256(keep) ^ 1);
            _fails(_pub(4));
            b.pubB[i] = keep;
        }
    }

    function test_adapter_sr_eachSide() public {
        b.pubA[9] = bytes32(uint256(b.pubA[9]) + 1);
        _fails(_pub(5));
        _build(NONCE);
        b.pubB[9] = bytes32(uint256(b.pubB[9]) + 1);
        _fails(_pub(5));
        _build(NONCE);
        b.pubPair[5] = bytes32(uint256(b.pubPair[5]) + 1);
        _fails(_pub(5));
        _build(NONCE);
        b.pubPair[6] = bytes32(uint256(b.pubPair[6]) + 1);
        _fails(_pub(5));
    }

    function test_adapter_halfCommit_eachSide() public {
        b.pubA[11] = bytes32(uint256(b.pubA[11]) + 1);
        _fails(_pub(6));
        _build(NONCE);
        b.pubB[11] = bytes32(uint256(b.pubB[11]) + 1);
        _fails(_pub(6));
        _build(NONCE);
        b.pubPair[3] = bytes32(uint256(b.pubPair[3]) + 1);
        _fails(_pub(6));
        _build(NONCE);
        b.pubPair[4] = bytes32(uint256(b.pubPair[4]) + 1);
        _fails(_pub(6));
    }

    /// The commit each POPCC1 signature covers.
    function test_adapter_codeCommit_eachSide() public {
        b.pubA[4] = bytes32(uint256(b.pubA[4]) + 1);
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 0));
        _build(NONCE);
        b.pubB[4] = bytes32(uint256(b.pubB[4]) + 1);
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 1));
    }

    /// Same commit on both sides, so only the role byte differs between the two signed messages.
    function test_adapter_codeAttest_roleByte() public {
        bytes32 code = b.pubA[4];
        b.pubB[4] = code;
        b.ccSigB = _cc(NONCE, "B", code);
        b.ccSigA = _cc(NONCE, "B", code);
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 0));
        b.ccSigA = _cc(NONCE, "A", code);
        b.ccSigB = _cc(NONCE, "A", code);
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 1));
    }

    function test_adapter_codeAttest_otherIssuerKey() public {
        (bytes32 r, bytes32 s) = vm.signP256(SK + 1, sha256(abi.encodePacked("POPCC1", NONCE, uint8(1), bytes1("A"), b.pubA[4])));
        b.ccSigA = abi.encodePacked(r, s);
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 0));
        _build(NONCE);
        (r, s) = vm.signP256(SK + 1, sha256(abi.encodePacked("POPCC1", NONCE, uint8(1), bytes1("B"), b.pubB[4])));
        b.ccSigB = abi.encodePacked(r, s);
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 1));
    }

    function test_adapter_codeAttest_otherNonce() public {
        b.ccSigA = _cc(keccak256("other"), "A", b.pubA[4]);
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 0));
        _build(NONCE);
        b.ccSigB = _cc(keccak256("other"), "B", b.pubB[4]);
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 1));
    }

    /// All three proofs move to attempt 2 together: the link check passes, the signatures over attempt 1 do not.
    function test_adapter_codeAttest_otherAttempt() public {
        b.pubA[2] = bytes32(uint256(2));
        b.pubB[2] = bytes32(uint256(2));
        b.pubPair[2] = bytes32(uint256(2));
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 0));
        // Past a u8: the signed byte would wrap, so it is refused outright. Good sigs for attempt 1 and 257 are the same bytes.
        b.pubA[2] = bytes32(uint256(257));
        b.pubB[2] = bytes32(uint256(257));
        b.pubPair[2] = bytes32(uint256(257));
        _fails(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 0));
    }

    function test_adapter_validAtDiffers_eachSide() public {
        b.pubA[10] = bytes32(VALID_AT + 1);
        _fails(abi.encodeWithSelector(Adapter.Stale.selector));
        _build(NONCE);
        b.pubB[10] = bytes32(VALID_AT + 1);
        _fails(abi.encodeWithSelector(Adapter.Stale.selector));
    }

    /// valid_at is well inside the age window here, so only the notBefore side can refuse it.
    function test_adapter_validAtBeforeNotBefore_insideAgeWindow() public {
        bytes memory data = abi.encode(b);
        require(
            ad.verifyPresence(NONCE, LAPTOP_X, Fixture.PHONE_X, qx, qy, uint64(VALID_AT), DEADLINE, data)
                == Adapter.verifyPresence.selector,
            "notBefore edge"
        );
        vm.expectRevert(abi.encodeWithSelector(Adapter.Stale.selector));
        ad.verifyPresence(NONCE, LAPTOP_X, Fixture.PHONE_X, qx, qy, uint64(VALID_AT + 1), DEADLINE, data);
    }

    function test_adapter_validAtEdges() public {
        _withValidAt(NOT_BEFORE);
        require(_run() == Adapter.verifyPresence.selector, "notBefore edge");
        _withValidAt(DEADLINE + ad.CLOCK_SKEW());
        require(_run() == Adapter.verifyPresence.selector, "skew edge");
    }

    /// The page sets deadline = laptop now + 900, the server sets valid_at on its own clock. Laptop 120 s ahead of
    /// the server, chirp right away: 900 refuses an honest run, 900 + CLOCK_SKEW takes it.
    function test_adapter_laptopClockAhead_maxAge() public {
        uint256 laptopNow = DEADLINE - 900;
        _withValidAt(laptopNow - 120);
        bytes memory data = abi.encode(b);
        vm.expectRevert(abi.encodeWithSelector(Adapter.Stale.selector));
        ad.verifyPresence(NONCE, LAPTOP_X, Fixture.PHONE_X, qx, qy, NOT_BEFORE - 120, DEADLINE, data);
        Adapter roomy = new Adapter(phone, pair, MAX_AGE + uint64(ad.CLOCK_SKEW()));
        require(
            roomy.verifyPresence(NONCE, LAPTOP_X, Fixture.PHONE_X, qx, qy, NOT_BEFORE - 120, DEADLINE, data)
                == Adapter.verifyPresence.selector,
            "honest run with a fast laptop clock"
        );
    }

    function test_adapter_proofARefused() public {
        phone.refuse(b.proofA);
        _fails(abi.encodeWithSelector(Adapter.ProofRejected.selector, 0));
    }

    /// The bundle with a garbage B proof. Everything else in it is fine.
    function test_adapter_proofBRefused() public {
        phone.refuse(b.proofB);
        _fails(abi.encodeWithSelector(Adapter.ProofRejected.selector, 1));
    }

    function test_adapter_proofPairRefused() public {
        pair.refuse(b.proofPair);
        _fails(abi.encodeWithSelector(Adapter.ProofRejected.selector, 2));
    }

    /// Each proof goes to its own verifier with its own inputs.
    function test_adapter_eachProofChecksItsOwnInputs() public {
        phone.bind(b.proofA, b.pubA);
        phone.bind(b.proofB, b.pubB);
        pair.bind(b.proofPair, b.pubPair);
        require(_run() == Adapter.verifyPresence.selector, "bound bundle");
        bytes memory keep = b.proofA;
        b.proofA = b.proofB;
        _fails(abi.encodeWithSelector(Adapter.ProofRejected.selector, 0));
        b.proofA = keep;
        keep = b.proofB;
        b.proofB = b.proofA;
        _fails(abi.encodeWithSelector(Adapter.ProofRejected.selector, 1));
        b.proofB = keep;
        b.proofPair = hex"dd";
        _fails(abi.encodeWithSelector(Adapter.ProofRejected.selector, 2));
    }

    /// Static scan of the adapter's deployed code against the sidecar's banned-opcode list (frameTx.ts): none
    /// present, GAS only right before a call, and no SLOAD or SSTORE, since the sidecar's STORAGE rule stays on for
    /// this foreign contract. A chain run has never exercised this.
    function test_adapter_noBannedOpcodes() public view {
        bytes memory c = address(ad).code;
        uint256 cbor = (uint256(uint8(c[c.length - 2])) << 8) | uint8(c[c.length - 1]);
        uint256 end = c.length - cbor - 2;
        for (uint256 i = 0; i < end; i++) {
            uint8 op = uint8(c[i]);
            if (op >= 0x60 && op <= 0x7f) {
                i += op - 0x5f;
                continue;
            }
            require(
                op != 0x31 && op != 0x32 && op != 0x3a && (op < 0x40 || op > 0x45) && op != 0x47 && op != 0x48
                    && op != 0x49 && op != 0x4a && op != 0xff && op != 0x54 && op != 0x55, // 54, 55: no storage at all
                "banned opcode"
            );
            if (op == 0x5a) {
                uint8 next = uint8(c[i + 1]);
                require(next == 0xf1 || next == 0xf2 || next == 0xf4 || next == 0xfa, "GAS not before a call");
            }
        }
    }
}

/// VERIFY on the account + the real adapter + mock Honk, then the body with a real token: every check on the path
/// runs for real except the three proofs themselves.
contract EvpStartThroughAdapterTest is EvpBase {
    uint256 constant SK = 0xB0B0;
    MockHonk phone;
    MockHonk pair;

    function setUp() public {
        _setUpAccount();
        (uint256 qx, uint256 qy) = vm.publicKeyP256(SK);
        phone = new MockHonk(12);
        pair = new MockHonk(11);
        vm.etch(VERIFIER, address(new Adapter(phone, pair, 1200)).code);
        pCfg.popIssuerX = qx;
        pCfg.popIssuerY = qy;
        vm.prank(address(a));
        a.setConfig(keccak256(abi.encode(pCfg)));
        _startEnv(PHONE, TH, DEADLINE, Fixture.GOOD_PHONE, Fixture.OFFS_GOOD_PHONE);
        // Frame 3 as a real tx would carry it: the issuer config this test re-pinned.
        _setSelfCall(
            3,
            abi.encodeCall(
                EvpRecoveryAccountLogic.startRotationEvp,
                (PHONE, TH, DEADLINE, pCfg, Fixture.GOOD_PHONE, Fixture.OFFS_GOOD_PHONE)
            )
        );
        _bundle(LAPTOP_X, Fixture.PHONE_X, a.popNonceFor(a.evpCtx(PHONE, TH, DEADLINE), NOT_BEFORE, SID));
    }

    function _bundle(uint256 devA, uint256 devB, bytes32 n) internal {
        (uint256 qx, uint256 qy) = (pCfg.popIssuerX, pCfg.popIssuerY);
        (bytes32 hi, bytes32 lo) = PopCtx.split(n);
        bytes32[] memory pa = new bytes32[](12);
        bytes32[] memory pb = new bytes32[](12);
        for (uint256 i = 0; i < 2; i++) {
            bytes32[] memory v = i == 0 ? pa : pb;
            v[0] = hi;
            v[1] = lo;
            v[3] = bytes32(i);
            v[4] = bytes32(0xC0DE + i);
            v[5] = bytes32(qx >> 128);
            v[6] = bytes32(uint256(uint128(qx)));
            v[7] = bytes32(qy >> 128);
            v[8] = bytes32(uint256(uint128(qy)));
            v[9] = bytes32(uint256(48000));
            v[10] = bytes32(Fixture.IAT + 10);
            v[11] = bytes32(0xCAFE + i);
        }
        bytes32[] memory pp = new bytes32[](11);
        pp[0] = hi;
        pp[1] = lo;
        pp[3] = pa[11];
        pp[4] = pb[11];
        pp[5] = pa[9];
        pp[6] = pb[9];
        (pp[7], pp[8]) = PopCtx.split(bytes32(devA));
        (pp[9], pp[10]) = PopCtx.split(bytes32(devB));
        pBundle = abi.encode(
            Adapter.Bundle(hex"aa", pa, hex"bb", pb, hex"cc", pp, _cc(n, "A", pa[4]), _cc(n, "B", pb[4]))
        );
    }

    function _cc(bytes32 n, bytes1 role, bytes32 code) private pure returns (bytes memory) {
        (bytes32 r, bytes32 s) = vm.signP256(SK, sha256(abi.encodePacked("POPCC1", n, uint8(0), role, code)));
        return abi.encodePacked(r, s);
    }

    function _failsPub(uint256 w) private {
        vm.prank(EP);
        vm.expectRevert(abi.encodeWithSelector(Adapter.BadPublicInputs.selector, w));
        a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
    }

    function _failsErr(bytes memory err) private {
        vm.prank(EP);
        vm.expectRevert(err);
        a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
    }

    function test_e2e_acceptThenBody() public {
        _verify();
        require(a.approvedScope() == 2, "scope");
        vm.prank(address(a));
        a.startRotationEvp(PHONE, TH, DEADLINE, pCfg, Fixture.GOOD_PHONE, Fixture.OFFS_GOOD_PHONE);
        require(a.pendingOwner() == PHONE && a.recoveryNonce() == NONCE0 + 1, "start");
    }

    function test_e2e_wrongLaptopDevice() public {
        _bundle(LAPTOP_X + 1, Fixture.PHONE_X, a.popNonceFor(a.evpCtx(PHONE, TH, DEADLINE), NOT_BEFORE, SID));
        _failsPub(7);
    }

    function test_e2e_wrongNewDevice() public {
        _bundle(LAPTOP_X, Fixture.PHONE_X + 1, a.popNonceFor(a.evpCtx(PHONE, TH, DEADLINE), NOT_BEFORE, SID));
        _failsPub(8);
    }

    function test_e2e_wrongNonce_sid() public {
        pSid = bytes16(uint128(0x5152));
        _failsPub(1);
    }

    /// Same proofs after the nonce moved. The phone re-signs, so it reaches the adapter and dies on popNonce.
    function test_e2e_oldProofsAfterNonceBump() public {
        vm.store(address(a), bytes32(uint256(2)), bytes32(NONCE0 + 2));
        _sig(0, 2, PHONE, a.evpCtx(PHONE, TH, DEADLINE));
        _failsPub(1);
    }

    function test_e2e_wrongVerifierConfig() public {
        pCfg.presenceVerifier = address(0xBAD);
        vm.prank(EP);
        vm.expectRevert(EvpRecoveryAccountLogic.BadConfig.selector);
        a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
    }

    /// A bundle whose B proof is garbage. A bad proof dies in VERIFY, so no fee and no state change.
    function test_e2e_garbageProofB() public {
        phone.refuse(hex"bb");
        vm.prank(EP);
        vm.expectRevert(abi.encodeWithSelector(Adapter.ProofRejected.selector, 1));
        a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
        require(a.recoveryNonce() == NONCE0 && a.approvedScope() == 0, "state moved");
    }

    /// L signs frame 1 on our ethrex, but none of these lean on that: a relayer who could edit frame 1 data gets
    /// nowhere with any field. Proofs are bound to their inputs here, so a changed proof or input counts too.
    function test_e2e_frame1FieldsBoundWithoutSig() public {
        Adapter.Bundle memory bd = abi.decode(pBundle, (Adapter.Bundle));
        phone.bind(bd.proofA, bd.pubA);
        phone.bind(bd.proofB, bd.pubB);
        pair.bind(bd.proofPair, bd.pubPair);
        _verify();

        pNotBefore = NOT_BEFORE + 1;
        _failsPub(1);
        pNotBefore = NOT_BEFORE;

        pSid = bytes16(uint128(0x5152));
        _failsPub(1);
        pSid = SID;

        pQx = Fixture.PHONE_X + 1;
        _failsErr(abi.encodeWithSelector(EvpRecoveryAccountLogic.BadNewDevice.selector));
        pQx = Fixture.PHONE_X;

        pQy = Fixture.PHONE_Y + 1;
        _failsErr(abi.encodeWithSelector(EvpRecoveryAccountLogic.BadNewDevice.selector));
        pQy = Fixture.PHONE_Y;

        uint256 keep = pCfg.popIssuerX;
        pCfg.popIssuerX = keep + 1;
        _failsErr(abi.encodeWithSelector(EvpRecoveryAccountLogic.BadConfig.selector));
        pCfg.popIssuerX = keep;

        bytes memory good = pBundle;
        bd.ccSigA = bd.ccSigB;
        pBundle = abi.encode(bd);
        _failsErr(abi.encodeWithSelector(Adapter.BadCodeAttest.selector, 0));

        bd = abi.decode(good, (Adapter.Bundle));
        bd.proofB = hex"bbbb";
        pBundle = abi.encode(bd);
        _failsErr(abi.encodeWithSelector(Adapter.ProofRejected.selector, 1));

        bd = abi.decode(good, (Adapter.Bundle));
        bd.pubPair[5] = bytes32(uint256(bd.pubPair[5]) + 1);
        pBundle = abi.encode(bd);
        _failsPub(5);

        // sr moved on all three: the links hold, the proofs were made for other inputs.
        bd = abi.decode(good, (Adapter.Bundle));
        bd.pubA[9] = bytes32(uint256(bd.pubA[9]) + 1);
        bd.pubPair[5] = bd.pubA[9];
        pBundle = abi.encode(bd);
        _failsErr(abi.encodeWithSelector(Adapter.ProofRejected.selector, 0));
    }

    function test_e2e_proofRejectedLeavesStateAlone() public {
        pair.setAccept(false);
        vm.prank(EP);
        vm.expectRevert(abi.encodeWithSelector(Adapter.ProofRejected.selector, 2));
        a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
        require(a.recoveryNonce() == NONCE0 && a.approvedScope() == 0, "state moved");
    }
}
