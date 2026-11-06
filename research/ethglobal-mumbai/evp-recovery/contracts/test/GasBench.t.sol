// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {TestBase} from "./Vm.sol";
import {Fixture} from "./Fixture.sol";
import {EvpCheck} from "../src/EvpCheck.sol";
import {EvpRecoveryAccount, EvpRecoveryAccountLogic} from "../src/EvpRecoveryAccount.sol";
import {EvpNoirPresenceVerifier} from "../src/pop/EvpNoirPresenceVerifier.sol";
import {IHonkVerifier} from "../src/pop/IPopPresenceVerifier.sol";
import {PopCtx} from "../src/pop/PopCtx.sol";

/// Accepts anything. The bench measures the account and the adapter around the proofs, not the proofs.
contract BenchHonk is IHonkVerifier {
    function verify(bytes calldata, bytes32[] calldata) external pure returns (bool) {
        return true;
    }
}

/// Burns about `burn` gas, then says yes. It stands in for a real verifier's cost so the 63/64 forwarding really
/// happens at those amounts. No proof runs. The loop overshoots by one iteration.
contract BurnHonk is IHonkVerifier {
    uint256 public immutable burn;

    constructor(uint256 b) {
        burn = b;
    }

    function verify(bytes calldata, bytes32[] calldata) external view returns (bool) {
        uint256 stop = gasleft() - burn; // reverts if the forwarded gas cannot cover it, like running out would
        while (gasleft() > stop) {}
        return true;
    }
}

/// Gas per frame on the REAL EvpRecoveryAccount (FrameEnvLiveMux), same method as poc-validation-rules
/// test/GasBench.t.sol: the mux helper is etched with a stub that runs the real dispatch but looks each value
/// up in a table in its own code (table[kind*1024 + a*16 + b]). Everything is deployed in setUp, so every
/// account and slot is cold in the measured test tx. Number = vm.lastCallGas().gasTotalUsed of the frame call.
///
/// ethrex charges forge does not model, added on top (checked in tmp/ethrex @ 9aa3645d by poc-validation-rules):
///   ENTRY 3,000  frame entry, cold account of the target, out of the frame's own limit
///   AMS     400  Amsterdam cold account 3,000 vs Cancun 2,600, per cold account touched. Cancel and finish touch
///                  one (the mux helper). Start frame 1 touches four: helper, adapter, phone and pair verifiers
/// EIP-8037 state gas: forge cannot price it. StateGas.t.sol shows a start writes no fresh slot (keep word in
/// slot 1, recoveryNonce starts at 1), so it needs none. Not modeled: the laptop's default-code pay frame.
///
/// Frame 1 budget. Forge numbers run the real account and the real adapter with mock Honk verifiers, so they cover
/// decode, the checks and 2 x P-256, not the proofs. The proof cost is CITED, not measured here:
/// ../../poc-verifier-gas/README.md, phone 4,072,116 x 2 + pair 3,313,313, bundle 11,473,237, Osaka. That pair is
/// the OLD 7-input verifier. No 11-input pair verifier exists, so its cost has never been measured.
/// Adding those numbers to the mock run ignores EIP-150: the account forwards 63/64 to the adapter and the adapter
/// 63/64 to each verifier, so gas held back along the way cannot be spent by the last proof. The real margin comes
/// from test_budget_start_frame1_forwarded, which burns the cited amounts through the real call chain.
///
/// Stub caveat: FRAMEDATALOAD is kind 3, idx = offset*16 + frame. Offset 68 (deadline in frame 3) gives
/// 3072 + 1091 = 4163, past kind 3's 1024 words, inside kind 4 (RECENTROOT). This account never calls
/// RECENTROOT, so the overlap is harmless. test_stub_deadlineReadIsLive proves the at offset 68 read is real.
contract EvpGasBench is TestBase {
    bytes constant MUX_STUB =
        hex"6040356020356000358060001461003a57806001146100565780600214610072578060031461008e57806004146100aa57806005146100c657fe5b5060041b016100000160051b6100c90160209060003960206000f35b5060041b016104000160051b6100c90160209060003960206000f35b5060041b016108000160051b6100c90160209060003960206000f35b5060041b01610c000160051b6100c90160209060003960206000f35b5060041b016110000160051b6100c90160209060003960206000f35b5000";

    uint256 constant ENTRY = 3000;
    uint256 constant AMS = 400;
    // ../../poc-verifier-gas/README.md, old 7-input pair
    uint256 constant CITED_PHONE = 4_072_116;
    uint256 constant CITED_PAIR_OLD = 3_313_313;
    uint256 constant CITED_BUNDLE_OLD = 11_473_237;
    // Same README, gasleft deltas that add up to the bundle: A 4,083,276, B 4,069,887, pair 3,320,074. One phone
    // verifier serves A and B, so the burn mock uses their mean, rounded up.
    uint256 constant CITED_PHONE_CALL = 4_076_582;
    uint256 constant CITED_PAIR_CALL = 3_320_074;
    uint256 constant COLD_FRAME1 = 4; // start frame 1: mux helper, adapter, phone verifier, pair verifier
    // real sizes, same README
    uint256 constant PHONE_PROOF_BYTES = 10_304;
    uint256 constant PAIR_PROOF_BYTES = 7_232;
    // limits
    uint256 constant SIDECAR_VERIFY_CAP = 16_000_000; // our devnet/sidecar.sh. The public sidecar's is 100,000
    uint256 constant TX_CAP = 16_777_216; // EIP-7825, ethrex TX_MAX_GAS_LIMIT_AMSTERDAM. Excludes state gas
    uint256 constant INTRINSIC = 12_000;
    uint256 constant PER_FRAME = 475;
    uint256 constant STATE_FLOOR3 = 100_000; // DESIGN.md 4.1 frame 3 state limit floor
    // DESIGN.md 4.1-4.3 limits
    uint256 constant LIMIT0_START = 4000;
    uint256 constant LIMIT1_START = 12_000_000; // the most the live probe mined, 2026-11-06
    uint256 constant LIMIT2_START = 8000; // laptop default-code pay frame: OPEN, not measurable here
    uint256 constant SIGS_START = 6700 + 2800;
    uint256 constant LIMIT_CANCEL = 12000;
    uint256 constant LIMIT_FINISH_DESIGN = 15000; // DESIGN.md 4.3: fits with ~100 gas to spare, too tight
    uint256 constant LIMIT_FINISH = 18000; // recommended
    uint256 constant EXPIRY_USE = 3050; // poc-validation-rules, modeled
    uint256 constant BODY_LIMIT = 110000; // proposed SENDER frame limit for startRotationEvp (execution part)

    address constant ACCT = 0xacACAcacAcACaCaCACACacACACacacaCACacaCAc;
    address constant PHONE = address(Fixture.PHONE_ADDR);
    address constant VERIFIER = address(0x7E57);
    uint256 constant LAPTOP_X = 0x1A97000000000000000000000000000000000000000000000000000000001A97;
    uint256 constant POP_SK = 0xB0B0;
    uint64 constant NOT_BEFORE = uint64(Fixture.IAT);
    bytes16 constant SID = bytes16(uint128(0x5151));
    address constant OWNER = address(0x0A01);
    address constant LAPTOP = address(0x1A97);
    bytes32 constant TH = 0x7777777777777777777777777777777777777777777777777777777777777777;
    uint256 constant DEADLINE = Fixture.DEADLINE;
    uint256 constant NOW = Fixture.IAT + 30;

    bytes table;
    address cancelAcct;
    address finishAcct;
    bytes startBody;
    bytes frame1Data;
    bytes32 phoneCtx;
    uint256 popX;
    uint256 popY;
    address startHelper;

    function _cfg() internal view returns (EvpCheck.Config memory) {
        return EvpCheck.Config(
            Fixture.ISSUER_X, Fixture.ISSUER_Y, keccak256(Fixture.EMAIL), keccak256(Fixture.AUD), popX, popY, VERIFIER
        );
    }

    function _filled(uint256 n) internal pure returns (bytes memory b) {
        b = new bytes(n);
        for (uint256 i = 0; i < n; i++) {
            b[i] = 0xAB; // no zero bytes: top calldata price, as real proofs nearly are
        }
    }

    function _phonePub(bytes32 hi, bytes32 lo, uint256 role) internal view returns (bytes32[] memory v) {
        v = new bytes32[](12);
        v[0] = hi;
        v[1] = lo;
        v[3] = bytes32(role);
        v[4] = bytes32(uint256(0xC0DE + role));
        v[5] = bytes32(popX >> 128);
        v[6] = bytes32(uint256(uint128(popX)));
        v[7] = bytes32(popY >> 128);
        v[8] = bytes32(uint256(uint128(popY)));
        v[9] = bytes32(uint256(48000));
        v[10] = bytes32(Fixture.IAT + 10);
        v[11] = bytes32(uint256(0xCAFE + role));
    }

    function _ccSig(bytes32 n, bytes1 role, bytes32 code) internal pure returns (bytes memory) {
        (bytes32 r, bytes32 s) = vm.signP256(POP_SK, sha256(abi.encodePacked("POPCC1", n, uint8(0), role, code)));
        return abi.encodePacked(r, s);
    }

    /// Frame 1 data at real proof sizes, real POPCC1 sigs, for the account at ACCT, nonce 7.
    function _frame1() internal view returns (bytes memory) {
        bytes32 n = PopCtx.nonce(1337, ACCT, phoneCtx, NOT_BEFORE, SID);
        (bytes32 hi, bytes32 lo) = PopCtx.split(n);
        bytes32[] memory pa = _phonePub(hi, lo, 0);
        bytes32[] memory pb = _phonePub(hi, lo, 1);
        bytes32[] memory pp = new bytes32[](11);
        pp[0] = hi;
        pp[1] = lo;
        pp[3] = pa[11];
        pp[4] = pb[11];
        pp[5] = pa[9];
        pp[6] = pb[9];
        (pp[7], pp[8]) = PopCtx.split(bytes32(LAPTOP_X));
        (pp[9], pp[10]) = PopCtx.split(bytes32(Fixture.PHONE_X));
        bytes memory bundle = abi.encode(
            EvpNoirPresenceVerifier.Bundle(
                _filled(PHONE_PROOF_BYTES),
                pa,
                _filled(PHONE_PROOF_BYTES),
                pb,
                _filled(PAIR_PROOF_BYTES),
                pp,
                _ccSig(n, "A", pa[4]),
                _ccSig(n, "B", pb[4])
            )
        );
        return abi.encodeCall(
            EvpRecoveryAccountLogic.evpVerify, (NOT_BEFORE, SID, Fixture.PHONE_X, Fixture.PHONE_Y, _cfg(), bundle)
        );
    }

    function _createAddr(address deployer, uint256 nonce) internal pure returns (address) {
        return address(uint160(uint256(keccak256(abi.encodePacked(hex"d694", deployer, uint8(nonce))))));
    }

    function _reset() internal {
        table = new bytes(5 * 1024 * 32);
    }

    function _put(uint256 kind, uint256 a, uint256 b, uint256 v) internal {
        uint256 idx = kind * 1024 + a * 16 + b;
        require(idx < 5 * 1024, "table");
        bytes memory t = table;
        assembly ("memory-safe") {
            mstore(add(add(t, 32), mul(idx, 32)), v)
        }
        table = t;
    }

    function _tx(uint256 id, uint256 v) internal {
        _put(0, id, 0, v);
    }

    function _frame(uint256 f, uint256 p, uint256 v) internal {
        _put(1, f, p, v);
    }

    function _sig(uint256 i, uint256 p, uint256 v) internal {
        _put(2, i, p, v);
    }

    function _data(uint256 f, uint256 off, bytes32 v) internal {
        _put(3, off, f, uint256(v));
    }

    function _etch(address acct) internal {
        vm.etch(_createAddr(acct, 1), bytes.concat(MUX_STUB, table));
    }

    function _deploy() internal returns (EvpRecoveryAccount) {
        return new EvpRecoveryAccount(OWNER, new address[](0), 120, LAPTOP, LAPTOP_X, keccak256(abi.encode(_cfg())));
    }

    function _selfCall(uint256 f, bytes memory body) internal {
        _frame(f, 0, uint160(ACCT));
        _frame(f, 2, 2);
        _frame(f, 4, body.length);
        _data(f, 0, _word(body, 0));
        _data(f, 4, _word(body, 4));
        _data(f, 36, _word(body, 36));
        _data(f, 68, _word(body, 68));
    }

    /// Start envelope tables (DESIGN.md 4.1) for the account at ACCT, nonce 7.
    function _startTables(uint256 frame0Deadline) internal {
        _reset();
        _tx(0x0B, 2);
        _tx(0x09, 4);
        _tx(0x0A, 1);
        _frame(0, 0, 0x8141);
        _frame(0, 2, 1);
        _data(0, 0, bytes32(frame0Deadline << 192));
        _frame(1, 0, uint160(ACCT));
        _frame(1, 2, 1);
        _frame(1, 6, 2);
        _frame(2, 0, uint160(LAPTOP));
        _frame(2, 2, 1);
        _frame(2, 6, 1);
        _selfCall(3, startBody);
        _sig(0, 0, uint160(PHONE));
        _sig(0, 1, 2);
        _sig(0, 2, uint256(phoneCtx));
        _sig(1, 0, uint160(LAPTOP));
        _sig(1, 1, 1);
    }

    /// Real account code at the vector's address with recoveryNonce 7, so the GOOD token is valid there.
    function _installAtVector(EvpRecoveryAccount impl) internal {
        vm.etch(ACCT, address(impl).code);
        for (uint256 s = 0; s <= 7; s++) {
            vm.store(ACCT, bytes32(s), vm.load(address(impl), bytes32(s)));
        }
        vm.store(ACCT, bytes32(uint256(2)), bytes32(uint256(7)));
        vm.deal(ACCT, 1 ether);
    }

    function _setPending(address acct, uint256 readyAt) internal {
        // keep word (1 << 224) stays set, as the constructor leaves it
        vm.store(acct, bytes32(uint256(1)), bytes32((uint256(1) << 224) | (readyAt << 160) | uint256(uint160(PHONE))));
        vm.store(acct, bytes32(uint256(2)), bytes32(uint256(8)));
    }

    function setUp() public {
        vm.chainId(1337);
        vm.warp(NOW);
        (popX, popY) = vm.publicKeyP256(POP_SK);
        startBody = abi.encodeCall(
            EvpRecoveryAccountLogic.startRotationEvp,
            (PHONE, TH, DEADLINE, _cfg(), Fixture.GOOD_PHONE, Fixture.OFFS_GOOD_PHONE)
        );
        BenchHonk honk = new BenchHonk();
        vm.etch(VERIFIER, address(new EvpNoirPresenceVerifier(honk, honk, 1200)).code);

        // start: real account at 0xacac.., helper stubbed with the start envelope
        EvpRecoveryAccount s = _deploy();
        _installAtVector(s);
        phoneCtx = EvpRecoveryAccount(payable(ACCT)).evpCtx(PHONE, TH, DEADLINE);
        frame1Data = _frame1();
        _startTables(DEADLINE);
        _etch(address(s)); // the helper address is an immutable in the code, so it is s's helper
        startHelper = _createAddr(address(s), 1);

        // cancel: owner, 1 sig, [VERIFY flags 3, SENDER cancelRotation()]
        EvpRecoveryAccount c = _deploy();
        _setPending(address(c), NOW + 120);
        _oneSigTables(OWNER, address(c), abi.encodeCall(EvpRecoveryAccountLogic.cancelRotation, ()));
        _etch(address(c));
        cancelAcct = address(c);

        // finish: pendingOwner, 1 sig, [VERIFY flags 3, SENDER finishRotation()]
        EvpRecoveryAccount f = _deploy();
        _setPending(address(f), NOW + 120);
        _oneSigTables(PHONE, address(f), abi.encodeCall(EvpRecoveryAccountLogic.finishRotation, ()));
        _etch(address(f));
        finishAcct = address(f);
    }

    function _oneSigTables(address signer, address acct, bytes memory body) internal {
        _reset();
        _tx(0x0B, 1);
        _tx(0x09, 2);
        _tx(0x0A, 0);
        _frame(0, 6, 3);
        _sig(0, 0, uint160(signer));
        _sig(0, 1, 2);
        _frame(1, 0, uint160(acct));
        _frame(1, 2, 2);
        _frame(1, 4, body.length);
        _data(1, 0, _word(body, 0));
    }

    function _call(address target, bytes memory data, uint256 gas, address from) internal returns (bool ok, uint256 used) {
        vm.prank(from);
        bytes memory ret;
        if (gas == 0) (ok, ret) = target.call(data);
        else (ok, ret) = target.call{gas: gas}(data);
        used = vm.lastCallGas().gasTotalUsed;
        if (!ok && gas == 0) {
            assembly ("memory-safe") {
                revert(add(ret, 32), mload(ret))
            }
        }
    }

    function _calldataGas(bytes memory cd) internal pure returns (uint256 g) {
        for (uint256 i; i < cd.length; ++i) {
            g += cd[i] == 0 ? 4 : 16;
        }
    }

    // ------------------------------------------------------------------ start tx ---------------------
    function test_gas_start_frame1_verify() public {
        (, uint256 used) = _call(ACCT, frame1Data, 0, EP);
        emit log_named_uint("start frame1 data bytes", frame1Data.length);
        emit log_named_uint("start frame1 MOCK proofs, measured (forge, cold)", used);
        emit log_named_uint("start frame1 MOCK proofs, modeled ethrex (+entry +AMS x4)", used + ENTRY + AMS * COLD_FRAME1);
    }

    /// Around-the-proofs cost plus the cited OLD bundle, as a plain sum. Does not account for 63/64, so this is a
    /// floor, not the margin: test_budget_start_frame1_forwarded below gives the margin.
    function test_budget_start_frame1() public {
        (bool ok, uint256 used) = _call(ACCT, frame1Data, LIMIT1_START - ENTRY - AMS * COLD_FRAME1, EP);
        require(ok, "mock frame 1 failed");
        require(CITED_PHONE * 2 + CITED_PAIR_OLD <= CITED_BUNDLE_OLD, "cited numbers");
        require(CITED_PHONE_CALL * 2 + CITED_PAIR_CALL <= CITED_BUNDLE_OLD + 1, "cited call numbers");
        uint256 around = used + ENTRY + AMS * COLD_FRAME1;
        uint256 modeled = around + CITED_BUNDLE_OLD;
        emit log_named_uint("frame1 around the proofs, mock (forge + entry + AMS x4)", around);
        emit log_named_uint("frame1 cited proofs, old 7-input pair", CITED_BUNDLE_OLD);
        emit log_named_uint("frame1 modeled total, plain sum", modeled);
        emit log_named_uint("frame1 limit", LIMIT1_START);
        require(modeled <= LIMIT1_START, "frame 1 does not fit its limit");
    }

    /// One frame 1 run at the real limit with burn mocks at the given costs, everything cold again.
    function _frame1Burning(uint256 phoneBurn, uint256 pairBurn) internal returns (bool ok) {
        BurnHonk ph = new BurnHonk(phoneBurn);
        BurnHonk pr = new BurnHonk(pairBurn);
        vm.etch(VERIFIER, address(new EvpNoirPresenceVerifier(ph, pr, 1200)).code);
        vm.cool(ACCT);
        vm.cool(VERIFIER);
        vm.cool(address(ph));
        vm.cool(address(pr));
        vm.cool(startHelper);
        (ok,) = _call(ACCT, frame1Data, LIMIT1_START - ENTRY - AMS * COLD_FRAME1, EP);
    }

    /// The real budget. The real account and adapter forward gas at the real frame limit, phone proofs burn their
    /// cited cost, and the largest pair that still fits is found by search (1,000 gas steps). Burn mocks only: this
    /// is not a real verifier, and a real one also holds back gas at its own precompile calls.
    function test_budget_start_frame1_forwarded() public {
        require(_frame1Burning(CITED_PHONE_CALL, CITED_PAIR_CALL), "cited bundle does not fit the frame 1 limit");
        uint256 lo = CITED_PAIR_CALL;
        uint256 hi = LIMIT1_START;
        while (hi - lo > 1000) {
            uint256 mid = (lo + hi) / 2;
            if (_frame1Burning(CITED_PHONE_CALL, mid)) lo = mid;
            else hi = mid;
        }
        emit log_named_uint("frame1 largest pair that fits (forwarded, burn mocks)", lo);
        emit log_named_uint("frame1 cited pair, old 7-input", CITED_PAIR_CALL);
        emit log_named_uint("frame1 margin for the unmeasured 11-input pair", lo - CITED_PAIR_CALL);
        require(lo - CITED_PAIR_CALL < 440_458, "the plain sum's margin should not survive forwarding");
        require(!_frame1Burning(CITED_PHONE_CALL, CITED_PAIR_CALL + 440_458), "pair at the plain-sum margin must not fit");
    }

    function test_budget_start_prefixSum() public {
        uint256 sum = LIMIT0_START + LIMIT1_START + LIMIT2_START + SIGS_START;
        emit log_named_uint("start prefix sum: limits 0..2 + P-256 + secp256k1 entries", sum);
        emit log_named_uint("start prefix sum: our sidecar cap", SIDECAR_VERIFY_CAP);
        require(sum <= SIDECAR_VERIFY_CAP, "over our sidecar cap");
        require(sum > 100_000, "would fit the public sidecar: fix the docs");
        require(LIMIT0_START >= EXPIRY_USE, "frame 0 cannot run");
    }

    /// The whole tx under the EIP-7825 cap, which is intrinsic + data + execution limits, state excluded (ethrex
    /// transaction.rs). Data at 16 per byte; the live probe paid 446,300 for 28,000 random bytes.
    function test_budget_start_txCap() public {
        uint256 mandatory = INTRINSIC + 4 * PER_FRAME + SIGS_START;
        uint256 data = _calldataGas(frame1Data) + _calldataGas(startBody) + 8 * 16;
        uint256 exec = LIMIT0_START + LIMIT1_START + LIMIT2_START + BODY_LIMIT;
        uint256 capped = mandatory + data + exec;
        emit log_named_uint("tx frame1 data gas", _calldataGas(frame1Data));
        emit log_named_uint("tx frame3 data gas", _calldataGas(startBody));
        emit log_named_uint("tx under EIP-7825: mandatory + data + execution limits", capped);
        emit log_named_uint("tx EIP-7825 cap", TX_CAP);
        require(capped <= TX_CAP, "over the per-tx cap");
        emit log_named_uint("tx headroom under the cap", TX_CAP - capped);
        emit log_named_uint("L must hold this x maxFee (adds frame 3 state floor)", capped + STATE_FLOOR3);
    }

    function test_gas_start_body() public {
        (, uint256 used) = _call(ACCT, startBody, 0, ACCT);
        require(EvpRecoveryAccount(payable(ACCT)).pendingOwner() == PHONE, "start did not land");
        uint256 cdg = _calldataGas(startBody);
        emit log_named_uint("start body token bytes", Fixture.GOOD_PHONE.length);
        emit log_named_uint("start body calldata bytes", startBody.length);
        emit log_named_uint("start body calldata gas (EIP-2028, intrinsic)", cdg);
        emit log_named_uint("start body execution measured (forge, cold slots)", used);
        emit log_named_uint("start body modeled ethrex (+entry)", used + ENTRY);
    }

    function test_budget_start_body() public {
        (bool ok, uint256 used) = _call(ACCT, startBody, BODY_LIMIT - ENTRY, ACCT);
        require(ok, "body does not fit BODY_LIMIT");
        emit log_named_uint("start body modeled use (limit 110000 execution; 0 fresh slots, see StateGas.t.sol)", used + ENTRY);
    }

    /// The stub really serves frame 3's deadline at offset 68: corrupt frame 0's copy and VERIFY must fail.
    function test_stub_deadlineReadIsLive() public {
        EvpRecoveryAccount s = _deploy();
        _installAtVector(s);
        _startTables(DEADLINE + 1);
        _etch(address(s));
        vm.prank(EP);
        (bool ok, bytes memory ret) = ACCT.call(frame1Data);
        require(!ok && bytes4(ret) == EvpRecoveryAccountLogic.DeadlineMismatch.selector, "deadline not read");
    }

    // ------------------------------------------------------------------ cancel / finish --------------
    function test_gas_cancel() public {
        (, uint256 v) = _call(cancelAcct, "", 0, EP);
        (, uint256 b) = _call(cancelAcct, abi.encodeCall(EvpRecoveryAccountLogic.cancelRotation, ()), 0, cancelAcct);
        emit log_named_uint("cancel frame0 VERIFY measured", v);
        emit log_named_uint("cancel frame0 VERIFY modeled (+entry +AMS)", v + ENTRY + AMS);
        emit log_named_uint("cancel body measured (pre-refund)", b);
        require(EvpRecoveryAccount(payable(cancelAcct)).pendingOwner() == address(0), "cancel did not land");
    }

    function test_budget_cancel() public {
        (bool ok, uint256 used) = _call(cancelAcct, "", LIMIT_CANCEL - ENTRY - AMS, EP);
        require(ok, "cancel VERIFY does not fit 12,000");
        emit log_named_uint("cancel VERIFY modeled use (limit 12000)", used + ENTRY + AMS);
    }

    function test_gas_finish() public {
        (, uint256 v) = _call(finishAcct, "", 0, EP);
        vm.warp(NOW + 120);
        (, uint256 b) = _call(finishAcct, abi.encodeCall(EvpRecoveryAccountLogic.finishRotation, ()), 0, finishAcct);
        emit log_named_uint("finish frame0 VERIFY measured", v);
        emit log_named_uint("finish frame0 VERIFY modeled (+entry +AMS)", v + ENTRY + AMS);
        emit log_named_uint("finish body measured (pre-refund)", b);
        require(EvpRecoveryAccount(payable(finishAcct)).owner() == PHONE, "finish did not land");
    }

    function test_budget_finish() public {
        (bool ok, uint256 used) = _call(finishAcct, "", LIMIT_FINISH - ENTRY - AMS, EP);
        require(ok, "finish VERIFY does not fit 18,000");
        emit log_named_uint("finish VERIFY modeled use (recommended limit 18000)", used + ENTRY + AMS);
        emit log_named_uint("finish VERIFY margin under DESIGN's 15000", LIMIT_FINISH_DESIGN - (used + ENTRY + AMS));
    }
}
