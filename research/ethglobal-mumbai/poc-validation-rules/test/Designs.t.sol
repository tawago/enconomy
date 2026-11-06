// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {MockEnv} from "./MockEnv.sol";
import {HumansOnlySponsorLogic} from "../src/HumansOnlySponsor.sol";
import {ZonePoolLogic, IGroth16Verifier} from "../src/ZonePool.sol";
import {P256AccountLogic} from "../src/P256Account.sol";

interface Vm {
    function prank(address) external;
    function expectRevert(bytes4) external;
}

contract SponsorHarness is HumansOnlySponsorLogic, MockEnv {
    constructor(bytes32 src)
        HumansOnlySponsorLogic(src, 1791464620, 6, 900, 14400, 5, 1 ether)
    {}

    function pay(Attestation calldata att) external {
        _pay(att);
    }

    function leaf(address a, address d, bytes32 h) external pure returns (bytes32) {
        return _leaf(a, d, h);
    }
}

contract AccountHarness is P256AccountLogic, MockEnv {
    constructor(address o) P256AccountLogic(o) {}

    function verifyFrame() external {
        _verifyFrame();
    }
}

contract MockVerifier is IGroth16Verifier {
    bytes32 public expected;

    function expect(uint256[5] calldata pub) external {
        expected = keccak256(abi.encode(pub));
    }

    function verifyProof(uint256[2] calldata, uint256[2][2] calldata, uint256[2] calldata, uint256[5] calldata pub)
        external
        view
        returns (bool)
    {
        return keccak256(abi.encode(pub)) == expected;
    }
}

contract PoolHarness is ZonePoolLogic, MockEnv {
    constructor(bytes32 zone, IGroth16Verifier v) ZonePoolLogic(0.1 ether, zone, v) {}

    function withdraw(Withdrawal calldata w) external {
        _withdraw(w);
    }
}

/// Plain contract tests (no forge-std); a failing require fails the test.
contract DesignsTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address constant EP = address(0xaa);

    address constant A = address(0xA11CE); // A's P256Account (tx.sender)
    address constant KA = address(0xAA01); // A's device key
    address constant AB = address(0xB0B); // B's P256Account
    address constant B = address(0xBB01); // B's device key
    bytes32 constant HA = keccak256("human-a");
    bytes32 constant HB = keccak256("human-b");
    bytes32 constant SRC = keccak256("humans-source");
    bytes32 constant SALT = keccak256("beacon-salt");
    uint256 constant SLOT = 349197; // live devnet slot seen 2026-11-01

    SponsorHarness s;
    uint256 public lastGas;

    // ------------------------------------------------------------------ A1 ------------------------
    function _setupSponsor() internal returns (HumansOnlySponsorLogic.Attestation memory att) {
        s = new SponsorHarness(SRC);
        bytes32 la = s.leaf(A, KA, HA);
        bytes32 lb = s.leaf(AB, B, HB);
        bytes32 tree = la < lb ? keccak256(abi.encode(la, lb)) : keccak256(abi.encode(lb, la));
        bytes32 r = keccak256(abi.encode(tree, SALT));

        att.refIndex = 0;
        att.treeRoot = tree;
        att.beaconSalt = SALT;
        att.partner = B;
        att.partnerAccount = AB;
        att.humanA = HA;
        att.humanB = HB;
        att.transcript = keccak256("acoustic transcript");
        att.proofA = new bytes32[](1);
        att.proofA[0] = lb;
        att.proofB = new bytes32[](1);
        att.proofB[0] = la;

        s.setTx(0x0A, 2); // current frame = pay
        s.setTx(0x02, uint160(A)); // sender
        s.setRoot(0, 0, uint256(SRC));
        s.setRoot(0, 1, SLOT);
        s.setRoot(0, 2, uint256(r));
        s.setSig(0, 0, uint160(KA)); // A's entry signer
        s.setSig(1, 1, 2); // P256
        s.setSig(1, 0, uint160(B));
        s.setSig(1, 2, uint256(s.attestationDigest(SLOT, r, A, B, att.transcript)));
        s.setFrame(0, 0, uint160(address(0x8141)));
        s.setFrame(0, 2, 1); // VERIFY
        _setDeadline(1791464620 + SLOT * 6 + 600); // 10 min after the reference slot
        s.setTx(0x0E, 1);
        s.setTx(0x10, s.epochKey(SLOT / 14400));
        s.setTx(0x01, 0);
        s.setTx(0x06, 0.01 ether);
        s.setFrame(1, 0, uint160(A));
    }

    function _setDeadline(uint256 deadline) internal {
        s.setFrameData(0, 0, bytes32(deadline << 192));
    }

    function _pay(HumansOnlySponsorLogic.Attestation memory att) internal {
        vm.prank(EP);
        uint256 g = gasleft();
        s.pay(att);
        lastGas = g - gasleft();
    }

    function test_A1_happyPath() public {
        HumansOnlySponsorLogic.Attestation memory att = _setupSponsor();
        _pay(att);
        require(s.approvedScope() == 1, "not approved");
    }

    function test_A1_staleDeadline() public {
        HumansOnlySponsorLogic.Attestation memory att = _setupSponsor();
        _setDeadline(1791464620 + SLOT * 6 + 901);
        vm.prank(EP);
        vm.expectRevert(HumansOnlySponsorLogic.Stale.selector);
        s.pay(att);
    }

    function test_A1_quotaUsed() public {
        HumansOnlySponsorLogic.Attestation memory att = _setupSponsor();
        s.setTx(0x01, 5);
        vm.prank(EP);
        vm.expectRevert(HumansOnlySponsorLogic.QuotaUsed.selector);
        s.pay(att);
    }

    function test_A1_oldEpochKeyRejected() public {
        HumansOnlySponsorLogic.Attestation memory att = _setupSponsor();
        s.setTx(0x10, s.epochKey(SLOT / 14400 - 1));
        vm.prank(EP);
        vm.expectRevert(HumansOnlySponsorLogic.WrongNonceKey.selector);
        s.pay(att);
    }

    function test_A1_sameHumanRejected() public {
        HumansOnlySponsorLogic.Attestation memory att = _setupSponsor();
        att.humanB = HA;
        vm.prank(EP);
        vm.expectRevert(HumansOnlySponsorLogic.SameHuman.selector);
        s.pay(att);
    }

    function test_A1_partnerSignedOtherDigest() public {
        HumansOnlySponsorLogic.Attestation memory att = _setupSponsor();
        att.transcript = keccak256("another meeting");
        vm.prank(EP);
        vm.expectRevert(HumansOnlySponsorLogic.PartnerSig.selector);
        s.pay(att);
    }

    function test_A1_wrongDeviceForAccount() public {
        HumansOnlySponsorLogic.Attestation memory att = _setupSponsor();
        s.setSig(0, 0, uint160(address(0xEE))); // sender account signed by an unregistered key
        vm.prank(EP);
        vm.expectRevert(HumansOnlySponsorLogic.NotHuman.selector);
        s.pay(att);
    }

    function test_A1_notEntryPoint() public {
        HumansOnlySponsorLogic.Attestation memory att = _setupSponsor();
        vm.expectRevert(HumansOnlySponsorLogic.NotEntryPoint.selector);
        s.pay(att);
    }

    // ------------------------------------------------------------------ account -------------------
    function test_P256Account_approvesAllowedScope() public {
        AccountHarness acct = new AccountHarness(A);
        acct.setSig(0, 1, 2);
        acct.setSig(0, 0, uint160(A));
        acct.setTx(0x0A, 1);
        acct.setFrame(1, 0x06, 2);
        acct.verifyFrame();
        require(acct.approvedScope() == 2, "scope");
    }

    function test_P256Account_rejectsSecp() public {
        AccountHarness acct = new AccountHarness(A);
        acct.setSig(0, 1, 1);
        acct.setSig(0, 0, uint160(A));
        vm.expectRevert(P256AccountLogic.NotP256.selector);
        acct.verifyFrame();
    }

    // ------------------------------------------------------------------ B -------------------------
    PoolHarness p;
    MockVerifier mv;

    function _setupPool() internal returns (ZonePoolLogic.Withdrawal memory w) {
        mv = new MockVerifier();
        bytes32 zone = keccak256("zone-source");
        p = new PoolHarness(zone, mv);
        uint256 nullifier = uint256(keccak256("nullifier")) >> 4;
        address recipient = address(0xF00D);
        w.recipient = recipient;
        w.feeCap = 0.002 ether;
        w.poolRefIndex = 0;
        w.zoneRefIndex = 1;

        p.setTx(0x09, 2);
        p.setTx(0x0A, 0);
        p.setFrame(1, 0x02, 2);
        p.setFrame(1, 0x00, uint160(recipient));
        p.setFrame(1, 0x08, 0.1 ether - 0.002 ether);
        p.setFrame(1, 0x04, 0);
        p.setTx(0x0E, 1);
        p.setTx(0x01, 0);
        p.setTx(0x10, nullifier);
        p.setTx(0x06, 0.0015 ether);
        p.setRoot(0, 0, uint256(p.poolSource()));
        p.setRoot(0, 2, 111);
        p.setRoot(1, 0, uint256(zone));
        p.setRoot(1, 2, 222);
        mv.expect([uint256(111), 222, nullifier, uint256(uint160(recipient)), 0.002 ether]);
    }

    function test_B_happyPath() public {
        ZonePoolLogic.Withdrawal memory w = _setupPool();
        vm.prank(EP);
        uint256 g = gasleft();
        p.withdraw(w);
        lastGas = g - gasleft();
        require(p.approvedScope() == 3, "not approved");
    }

    function test_B_extraFrameRejected() public {
        ZonePoolLogic.Withdrawal memory w = _setupPool();
        p.setTx(0x09, 3);
        vm.prank(EP);
        vm.expectRevert(ZonePoolLogic.Layout.selector);
        p.withdraw(w);
    }

    function test_B_reusedNullifierSeq() public {
        ZonePoolLogic.Withdrawal memory w = _setupPool();
        p.setTx(0x01, 1);
        vm.prank(EP);
        vm.expectRevert(ZonePoolLogic.BadNonce.selector);
        p.withdraw(w);
    }

    function test_B_feeAboveCap() public {
        ZonePoolLogic.Withdrawal memory w = _setupPool();
        p.setTx(0x06, 0.003 ether);
        vm.prank(EP);
        vm.expectRevert(ZonePoolLogic.FeeTooHigh.selector);
        p.withdraw(w);
    }

    function test_B_proofBoundToRecipient() public {
        ZonePoolLogic.Withdrawal memory w = _setupPool();
        w.recipient = address(0xBAD);
        p.setFrame(1, 0x00, uint160(address(0xBAD)));
        vm.prank(EP);
        vm.expectRevert(ZonePoolLogic.BadProof.selector);
        p.withdraw(w);
    }
}
