// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {MockEnv} from "./MockEnv.sol";
import {TestBase} from "./Vm.sol";
import {Fixture} from "./Fixture.sol";
import {EvpCheck} from "../src/EvpCheck.sol";
import {EvpRecoveryAccountLogic} from "../src/EvpRecoveryAccount.sol";
import {IPopPresenceVerifier} from "../src/pop/IPopPresenceVerifier.sol";

contract EvpHarness is EvpRecoveryAccountLogic, MockEnv {
    constructor(address o, address[] memory g, uint256 d, address l, uint256 lx, bytes32 c)
        EvpRecoveryAccountLogic(o, g, d, l, lx, c)
    {}

    function verifyFrame() external {
        _verifyFrame();
    }
}

/// Stands in for the proofs: `prove` sets the session the "proofs" are about, and verifyPresence refuses anything
/// else the account passes in. EvpPresence.t.sol runs the real adapter.
contract MockPresenceVerifier is IPopPresenceVerifier {
    bytes32 public pNonce;
    uint256 public pA;
    uint256 public pB;
    uint256 public pIssuerX;
    uint256 public pDeadline;
    uint64 public pNotBefore;
    bytes32 public pBundleHash;

    error WrongNonce();
    error WrongDeviceA();
    error WrongDeviceB();
    error WrongIssuer();
    error WrongWindow();
    error WrongBundle();

    function prove(bytes32 n, uint256 a, uint256 b, uint256 ix, uint64 nb, uint256 dl, bytes32 h) external {
        pNonce = n;
        pA = a;
        pB = b;
        pIssuerX = ix;
        pNotBefore = nb;
        pDeadline = dl;
        pBundleHash = h;
    }

    function verifyPresence(
        bytes32 popNonce,
        uint256 deviceA,
        uint256 deviceB,
        uint256 qx,
        uint256,
        uint64 notBefore,
        uint256 deadline,
        bytes calldata presence
    ) external view returns (bytes4) {
        if (popNonce != pNonce) revert WrongNonce();
        if (deviceA != pA) revert WrongDeviceA();
        if (deviceB != pB) revert WrongDeviceB();
        if (qx != pIssuerX) revert WrongIssuer();
        if (notBefore != pNotBefore || deadline != pDeadline) revert WrongWindow();
        if (keccak256(presence) != pBundleHash) revert WrongBundle();
        return IPopPresenceVerifier.verifyPresence.selector;
    }
}

contract WrongReturnVerifier is IPopPresenceVerifier {
    function verifyPresence(bytes32, uint256, uint256, uint256, uint256, uint64, uint256, bytes calldata)
        external
        pure
        returns (bytes4)
    {
        return bytes4(0);
    }
}

/// Logic tests on MockEnv. The account sits at the vector's address 0xacac.. on chain 1337 with
/// recoveryNonce 7, so the GOOD token (KB nonce = the vector's ctx) is the DESIGN.md test vector end to end.
abstract contract EvpBase is TestBase {
    address constant ACCT = 0xacACAcacAcACaCaCACACacACACacacaCACacaCAc;
    address constant NEWKEY = 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE;
    address constant OTHERKEY = 0xDDdDddDdDdddDDddDDddDDDDdDdDDdDDdDDDDDDd;
    address constant OWNER = address(0x0A01);
    address constant LAPTOP = address(0x1A97);
    address constant G1 = address(0x6001);
    address constant G2 = address(0x6002);
    bytes32 constant TH = 0x7777777777777777777777777777777777777777777777777777777777777777;
    bytes32 constant CTX = 0x22cbad28b2d580114630eb65e51e47305a5d6efbbb8c6d48fca64bd7d4b5655a;
    uint256 constant NONCE0 = 7;
    uint256 constant DEADLINE = Fixture.DEADLINE; // 1793000900
    uint256 constant NOW = Fixture.IAT + 30;
    address constant PHONE = address(Fixture.PHONE_ADDR); // real P-256 new phone, role B
    uint256 constant LAPTOP_X = 0x1A97000000000000000000000000000000000000000000000000000000001A97; // role A
    uint256 constant POP_X = 0xB0B0;
    uint256 constant POP_Y = 0xB1B1;
    address constant VERIFIER = address(0x7E57);
    uint64 constant NOT_BEFORE = uint64(Fixture.IAT);
    bytes16 constant SID = bytes16(uint128(0x5151));

    EvpHarness a;
    // frame 1 data
    uint64 pNotBefore = NOT_BEFORE;
    bytes16 pSid = SID;
    uint256 pQx = Fixture.PHONE_X;
    uint256 pQy = Fixture.PHONE_Y;
    EvpCheck.Config pCfg;
    bytes pBundle = hex"b0b0";

    function _cfg() internal pure returns (EvpCheck.Config memory) {
        return EvpCheck.Config(
            Fixture.ISSUER_X, Fixture.ISSUER_Y, keccak256(Fixture.EMAIL), keccak256(Fixture.AUD), POP_X, POP_Y, VERIFIER
        );
    }

    function _mock() internal pure returns (MockPresenceVerifier) {
        return MockPresenceVerifier(VERIFIER);
    }

    /// The proofs are about (the phone's ctx at the current nonce, the laptop, the phone).
    function _prove() internal {
        bytes32 n = a.popNonceFor(a.evpCtx(PHONE, TH, DEADLINE), NOT_BEFORE, SID);
        _mock().prove(n, LAPTOP_X, Fixture.PHONE_X, POP_X, NOT_BEFORE, DEADLINE, keccak256(pBundle));
    }

    function _setUpAccount() internal {
        vm.chainId(1337);
        vm.warp(NOW);
        address[] memory g = new address[](2);
        g[0] = G1;
        g[1] = G2;
        EvpHarness impl = new EvpHarness(OWNER, g, 120, LAPTOP, LAPTOP_X, keccak256(abi.encode(_cfg())));
        // Same code at the vector's address. Copy the constructor's storage, then recoveryNonce = 7.
        vm.etch(ACCT, address(impl).code);
        for (uint256 s = 0; s <= 7; s++) {
            vm.store(ACCT, bytes32(s), vm.load(address(impl), bytes32(s)));
        }
        vm.store(ACCT, keccak256(abi.encode(G1, uint256(4))), bytes32(uint256(1)));
        vm.store(ACCT, keccak256(abi.encode(G2, uint256(4))), bytes32(uint256(1)));
        vm.store(ACCT, bytes32(uint256(2)), bytes32(NONCE0));
        a = EvpHarness(ACCT);
        vm.etch(VERIFIER, address(new MockPresenceVerifier()).code);
        pCfg = _cfg();
    }

    function _body(address newKey, bytes32 th, uint256 deadline, bytes memory token, uint256 offs)
        internal
        pure
        returns (bytes memory)
    {
        return abi.encodeCall(EvpRecoveryAccountLogic.startRotationEvp, (newKey, th, deadline, _cfg(), token, offs));
    }

    function _setSelfCall(uint256 frame, bytes memory data) internal {
        a.setFrame(frame, 0, uint160(address(a)));
        a.setFrame(frame, 2, 2); // SENDER
        a.setFrame(frame, 4, data.length);
        a.setFrameData(frame, 0, _word(data, 0));
        a.setFrameData(frame, 4, _word(data, 4));
        a.setFrameData(frame, 36, _word(data, 36));
        a.setFrameData(frame, 68, _word(data, 68));
    }

    function _sig(uint256 i, uint256 scheme, address signer, bytes32 m) internal {
        a.setSig(i, 0, uint160(signer));
        a.setSig(i, 1, scheme);
        a.setSig(i, 2, uint256(m));
    }

    /// DESIGN.md 4.1 start envelope, phone signed ctx for (newKey, th, deadline) at the current nonce.
    function _startEnv(address newKey, bytes32 th, uint256 deadline, bytes memory token, uint256 offs) internal {
        a.setTx(0x0B, 2);
        a.setTx(0x09, 4);
        a.setTx(0x0A, 1);
        a.setFrame(0, 0, uint160(address(0x8141)));
        a.setFrame(0, 2, 1);
        a.setFrameData(0, 0, bytes32(deadline << 192));
        a.setFrame(1, 0, uint160(address(a)));
        a.setFrame(1, 2, 1);
        a.setFrame(1, 0x06, 2); // flags 2: execution
        a.setFrame(2, 0, uint160(LAPTOP));
        a.setFrame(2, 2, 1);
        a.setFrame(2, 0x06, 1); // flags 1: pay
        _setSelfCall(3, _body(newKey, th, deadline, token, offs));
        _sig(0, 2, newKey, a.evpCtx(newKey, th, deadline));
        _sig(1, 1, LAPTOP, 0);
    }

    function _goodEnv() internal {
        _startEnv(PHONE, TH, DEADLINE, Fixture.GOOD_PHONE, Fixture.OFFS_GOOD_PHONE);
        _prove();
    }

    /// 2 sigs: frame 1 enters through evpVerify with the frame 1 data. Otherwise the fallback path.
    function _verify() internal {
        bool evp = a.mTx(0x0B) == 2;
        vm.prank(EP);
        if (evp) a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
        else a.verifyFrame();
    }

    function _verifyFails(bytes4 err) internal {
        bool evp = a.mTx(0x0B) == 2;
        vm.prank(EP);
        vm.expectRevert(err);
        if (evp) a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
        else a.verifyFrame();
    }

    function _startPhone(bytes memory token, uint256 offs) internal {
        vm.prank(address(a));
        a.startRotationEvp(PHONE, TH, DEADLINE, _cfg(), token, offs);
    }

    function _startPhoneFails(bytes memory token, uint256 offs, bytes memory err) internal {
        vm.prank(address(a));
        vm.expectRevert(err);
        a.startRotationEvp(PHONE, TH, DEADLINE, _cfg(), token, offs);
    }

    function _start(bytes memory token, uint256 offs) internal {
        vm.prank(address(a));
        a.startRotationEvp(NEWKEY, TH, DEADLINE, _cfg(), token, offs);
    }

    function _startFails(bytes memory token, uint256 offs, bytes memory err) internal {
        vm.prank(address(a));
        vm.expectRevert(err);
        a.startRotationEvp(NEWKEY, TH, DEADLINE, _cfg(), token, offs);
    }

    function _claim(uint256 f) internal pure returns (bytes memory) {
        return abi.encodeWithSelector(EvpCheck.BadClaim.selector, f);
    }

    function _badSig(uint256 w) internal pure returns (bytes memory) {
        return abi.encodeWithSelector(EvpCheck.BadSig.selector, w);
    }
}

contract EvpVectorTest is EvpBase {
    function setUp() public {
        _setUpAccount();
    }

    /// ../ctx-vector.json is read at test time, so the file and the contract cannot drift apart.
    function test_vector_ctxMatchesFile() public view {
        string memory j = vm.readFile("../ctx-vector.json");
        bytes32 dom = vm.parseJsonBytes32(j, ".DOMAIN");
        require(a.EVP_DOMAIN() == dom, "DOMAIN");
        uint256 chainId = vm.parseJsonUint(j, ".inputs.chainId");
        address account = vm.parseJsonAddress(j, ".inputs.account");
        address newKey = vm.parseJsonAddress(j, ".inputs.newKey");
        uint256 nonce = vm.parseJsonUint(j, ".inputs.recoveryNonce");
        bytes32 th = vm.parseJsonBytes32(j, ".inputs.transcriptHash");
        uint256 deadline = vm.parseJsonUint(j, ".inputs.deadline");
        bytes memory pre = abi.encode(dom, chainId, account, newKey, nonce, th, deadline);
        require(pre.length == 224, "224 bytes");
        require(keccak256(pre) == keccak256(vm.parseJsonBytes(j, ".preimage")), "preimage");
        bytes32 ctx = a.ctxFor(chainId, account, newKey, nonce, th, deadline);
        require(ctx == vm.parseJsonBytes32(j, ".ctx") && ctx == CTX, "ctx");
        require(keccak256(abi.encodePacked(uint64(deadline))) == keccak256(vm.parseJsonBytes(j, ".frame0Data")), "frame0");
        require(keccak256(Fixture.AUD) == vm.parseJsonBytes32(j, ".audHash.keccak"), "audHash");
        require(keccak256(Fixture.EMAIL) == vm.parseJsonBytes32(j, ".emailHash.keccak"), "emailHash");
    }

    /// The live path (block.chainid, address(this), SLOAD recoveryNonce) gives the vector's ctx.
    function test_vector_liveCtx() public view {
        require(block.chainid == 1337 && address(a) == ACCT && a.recoveryNonce() == NONCE0, "setup");
        require(a.evpCtx(NEWKEY, TH, DEADLINE) == CTX, "live ctx");
    }
}

contract EvpStartVerifyTest is EvpBase {
    function setUp() public {
        _setUpAccount();
        _goodEnv();
    }

    function test_happy_verifyApprovesExecutionOnly() public {
        _verify();
        require(a.approvedScope() == 2, "scope must be EXECUTION only");
    }

    function test_deadlineMismatch() public {
        a.setFrameData(0, 0, bytes32((DEADLINE + 3600) << 192)); // frame 0 stretched, calldata not
        _verifyFails(EvpRecoveryAccountLogic.DeadlineMismatch.selector);
    }

    function test_noExpiryFrame() public {
        a.setFrame(0, 0, uint160(address(0x1234)));
        _verifyFails(EvpRecoveryAccountLogic.NoExpiry.selector);
    }

    function test_expiryFrameNotVerifyMode() public {
        a.setFrame(0, 2, 0);
        _verifyFails(EvpRecoveryAccountLogic.NoExpiry.selector);
    }

    function test_frameCountPinned() public {
        a.setTx(0x09, 5);
        _verifyFails(EvpRecoveryAccountLogic.Layout.selector);
    }

    function test_mustBeFrameOne() public {
        a.setTx(0x0A, 2);
        _verifyFails(EvpRecoveryAccountLogic.Layout.selector);
    }

    function test_bodyMustBeStartRotationEvp() public {
        _setSelfCall(3, abi.encodeCall(EvpRecoveryAccountLogic.setLaptop, (address(0xBAD))));
        _verifyFails(EvpRecoveryAccountLogic.Layout.selector);
    }

    function test_bodyMustBeSelf() public {
        a.setFrame(3, 0, uint160(address(0xBAD)));
        _verifyFails(EvpRecoveryAccountLogic.Layout.selector);
    }

    function test_bodyMustBeSenderMode() public {
        a.setFrame(3, 2, 0);
        _verifyFails(EvpRecoveryAccountLogic.Layout.selector);
    }

    function test_newKeyIsOwner() public {
        _startEnv(OWNER, TH, DEADLINE, Fixture.GOOD_PHONE, Fixture.OFFS_GOOD_PHONE);
        _verifyFails(EvpRecoveryAccountLogic.BadNewKey.selector);
    }

    function test_newKeyZero() public {
        _startEnv(address(0), TH, DEADLINE, Fixture.GOOD_PHONE, Fixture.OFFS_GOOD_PHONE);
        _verifyFails(EvpRecoveryAccountLogic.BadNewKey.selector);
    }

    function test_newKeyDirtyHighBits() public {
        a.setFrameData(3, 4, bytes32(uint256(uint160(PHONE)) | (uint256(1) << 200)));
        _verifyFails(EvpRecoveryAccountLogic.BadNewKey.selector);
    }

    // ---- the laptop leg (DESIGN.md 4.1 frame 2, sig[1]) ----
    function test_payerFrameNotLaptop() public {
        a.setFrame(2, 0, uint160(address(0xBAD)));
        _verifyFails(EvpRecoveryAccountLogic.BadPayer.selector);
    }

    function test_payerSigNotLaptop() public {
        _sig(1, 1, address(0xBAD), 0);
        _verifyFails(EvpRecoveryAccountLogic.BadPayer.selector);
    }

    function test_payerSigNotSecp256k1() public {
        _sig(1, 2, LAPTOP, 0);
        _verifyFails(EvpRecoveryAccountLogic.BadPayer.selector);
    }

    function test_payerSigExplicitMsg() public {
        _sig(1, 1, LAPTOP, CTX); // laptop must sign the sig hash (whole tx), not a side message
        _verifyFails(EvpRecoveryAccountLogic.BadPayer.selector);
    }

    function test_payerFrameNotPaying() public {
        a.setFrame(2, 0x06, 3);
        _verifyFails(EvpRecoveryAccountLogic.BadPayer.selector);
    }

    function test_payerFrameNotVerifyMode() public {
        a.setFrame(2, 2, 0);
        _verifyFails(EvpRecoveryAccountLogic.BadPayer.selector);
    }

    function test_noLaptopEnrolled() public {
        vm.prank(address(a));
        a.setLaptop(address(0));
        a.setFrame(2, 0, 0);
        _sig(1, 1, address(0), 0);
        _verifyFails(EvpRecoveryAccountLogic.BadPayer.selector);
    }

    // ---- griefing, threat-model.md 2.7 ----

    /// Anyone with a fresh P-256 key and an old public token, no laptop: dies in VERIFY, nobody pays.
    function test_grief_freshKeyWithoutLaptop() public {
        _startEnv(OTHERKEY, TH, DEADLINE, Fixture.GOOD_PHONE, Fixture.OFFS_GOOD_PHONE);
        _sig(1, 1, OTHERKEY, 0);
        a.setFrame(2, 0, uint160(OTHERKEY));
        _verifyFails(EvpRecoveryAccountLogic.BadPayer.selector);
    }

    /// The self-paid shape (frame 1 flags 3) is refused, so the account never pays for a start.
    function test_grief_accountNeverPaysStart() public {
        a.setFrame(1, 0x06, 3);
        _verifyFails(EvpRecoveryAccountLogic.NotEvpScope.selector);
        a.setFrame(1, 0x06, 1);
        _verifyFails(EvpRecoveryAccountLogic.NotEvpScope.selector);
    }

    /// VERIFY does not look at the token (the proofs are checked, the token is not). A junk token passes VERIFY and reverts in the body; the gas is
    /// the laptop's because VERIFY approved EXECUTION only. Only the laptop key can send this at all.
    function test_grief_junkTokenIsPaidByLaptop() public {
        bytes memory junk = Fixture.WRONG_AUD;
        _startEnv(PHONE, TH, DEADLINE, junk, Fixture.OFFS_WRONG_AUD);
        _verify();
        require(a.approvedScope() == 2, "account approved payment");
        _startPhoneFails(junk, Fixture.OFFS_WRONG_AUD, _claim(11));
        require(a.recoveryNonce() == NONCE0 && a.pendingOwner() == address(0), "state moved");
    }

    // ---- replay ----

    // ---- presence, DESIGN.md 5 ----

    function test_presence_accept() public {
        _verify();
        require(a.approvedScope() == 2, "scope");
        require(a.pendingOwner() == address(0), "VERIFY moved state");
    }

    /// Without a proof a start cannot get through the fallback path, even with a perfect envelope.
    function test_presence_fallbackPathRefusesTwoSigs() public {
        vm.prank(EP);
        vm.expectRevert(EvpRecoveryAccountLogic.Layout.selector);
        a.verifyFrame();
    }

    function test_presence_onlyEntryPoint() public {
        vm.expectRevert(EvpRecoveryAccountLogic.NotEntryPoint.selector);
        a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
    }

    function test_presence_frame1MustBeVerifyMode() public {
        a.setFrame(1, 2, 0);
        _verifyFails(EvpRecoveryAccountLogic.Layout.selector);
    }

    /// The proofs are about LAPTOP_X. The account now expects another laptop.
    function test_presence_wrongLaptopDevice() public {
        vm.prank(address(a));
        a.setLaptopDevice(LAPTOP_X + 1);
        _verifyFails(MockPresenceVerifier.WrongDeviceA.selector);
    }

    function test_presence_noLaptopDeviceEnrolled() public {
        vm.prank(address(a));
        a.setLaptopDevice(0);
        _verifyFails(EvpRecoveryAccountLogic.NoLaptopDevice.selector);
    }

    /// The proofs name some other device as role B, not the phone that gets the key.
    function test_presence_wrongNewDevice() public {
        bytes32 n = a.popNonceFor(a.evpCtx(PHONE, TH, DEADLINE), NOT_BEFORE, SID);
        _mock().prove(n, LAPTOP_X, Fixture.PHONE_X + 1, POP_X, NOT_BEFORE, DEADLINE, keccak256(pBundle));
        _verifyFails(MockPresenceVerifier.WrongDeviceB.selector);
    }

    /// (qx, qy) must hash to newKey, so a proof about another device X cannot be lined up by editing frame 1.
    function test_presence_qxQyNotNewKey() public {
        pQx = Fixture.PHONE_X + 1;
        _verifyFails(EvpRecoveryAccountLogic.BadNewDevice.selector);
        pQx = Fixture.PHONE_X;
        pQy = Fixture.PHONE_Y + 1;
        _verifyFails(EvpRecoveryAccountLogic.BadNewDevice.selector);
    }

    function test_presence_wrongNonce_sid() public {
        pSid = bytes16(uint128(0x5152));
        _verifyFails(MockPresenceVerifier.WrongNonce.selector);
    }

    function test_presence_wrongNonce_notBefore() public {
        pNotBefore = NOT_BEFORE + 1;
        _verifyFails(MockPresenceVerifier.WrongNonce.selector);
    }

    /// Proofs for another session tag: ctx differs, so popNonce differs.
    function test_presence_wrongNonce_otherCtx() public {
        bytes32 n = a.popNonceFor(a.evpCtx(PHONE, keccak256("other session"), DEADLINE), NOT_BEFORE, SID);
        _mock().prove(n, LAPTOP_X, Fixture.PHONE_X, POP_X, NOT_BEFORE, DEADLINE, keccak256(pBundle));
        _verifyFails(MockPresenceVerifier.WrongNonce.selector);
    }

    /// A proof dies with the attempt: nonce bumped, the phone re-signs the new ctx, the old proofs do not match.
    function test_presence_oldProofAfterNonceBump() public {
        vm.store(address(a), bytes32(uint256(2)), bytes32(NONCE0 + 2));
        _sig(0, 2, PHONE, a.evpCtx(PHONE, TH, DEADLINE));
        _verifyFails(MockPresenceVerifier.WrongNonce.selector);
    }

    function test_presence_wrongVerifierConfig() public {
        pCfg.presenceVerifier = address(0xBAD);
        _verifyFails(EvpRecoveryAccountLogic.BadConfig.selector);
    }

    function test_presence_wrongPopIssuerConfig() public {
        pCfg.popIssuerX = POP_X + 1;
        _verifyFails(EvpRecoveryAccountLogic.BadConfig.selector);
        pCfg.popIssuerX = POP_X;
        pCfg.popIssuerY = POP_Y + 1;
        _verifyFails(EvpRecoveryAccountLogic.BadConfig.selector);
    }

    /// The owner re-pins the config: the old cfg no longer opens configHash.
    function test_presence_configRepinned() public {
        vm.prank(address(a));
        a.setConfig(keccak256("other"));
        _verifyFails(EvpRecoveryAccountLogic.BadConfig.selector);
    }

    /// A pinned verifier address with no code fails instead of passing on empty return data.
    function test_presence_verifierWithoutCode() public {
        pCfg.presenceVerifier = address(0xC0DE);
        vm.prank(address(a));
        a.setConfig(keccak256(abi.encode(pCfg)));
        bool evp = a.mTx(0x0B) == 2;
        require(evp, "env");
        vm.prank(EP);
        vm.expectRevert();
        a.evpVerify(pNotBefore, pSid, pQx, pQy, pCfg, pBundle);
    }

    /// A verifier that returns without its selector does not count as a pass.
    function test_presence_verifierWrongReturn() public {
        address other = address(new WrongReturnVerifier());
        pCfg.presenceVerifier = other;
        vm.prank(address(a));
        a.setConfig(keccak256(abi.encode(pCfg)));
        _verifyFails(EvpRecoveryAccountLogic.BadPresence.selector);
    }

    function test_presence_bundleForwardedIntact() public {
        pBundle = hex"b0b1";
        _verifyFails(MockPresenceVerifier.WrongBundle.selector);
    }
}

contract EvpStartBodyTest is EvpBase {
    function setUp() public {
        _setUpAccount();
    }

    function test_happy_body() public {
        _start(Fixture.GOOD, Fixture.OFFS_GOOD);
        require(a.pendingOwner() == NEWKEY, "pending");
        require(a.readyAt() == NOW + 120, "readyAt");
        require(a.recoveryNonce() == NONCE0 + 1, "nonce");
        require(a.owner() == OWNER, "owner unchanged");
    }

    function test_checkEvp_offline() public view {
        a.checkEvp(Fixture.GOOD, Fixture.OFFS_GOOD, _cfg(), CTX);
    }

    function test_checkEvp_offline_otherOrigin() public {
        vm.expectRevert(_claim(11));
        a.checkEvp(Fixture.WRONG_AUD, Fixture.OFFS_WRONG_AUD, _cfg(), CTX);
    }

    function test_replay_sameTokenTwice() public {
        _start(Fixture.GOOD, Fixture.OFFS_GOOD);
        _startFails(Fixture.GOOD, Fixture.OFFS_GOOD, _claim(12));
    }

    function test_wrongAud() public {
        _startFails(Fixture.WRONG_AUD, Fixture.OFFS_WRONG_AUD, _claim(11));
    }

    /// aud = "https://recover.tawago.com.evil.example" with the honest length hint: the quote check catches it.
    function test_audPrefixOrigin() public {
        _startFails(Fixture.AUD_PREFIX, Fixture.OFFS_AUD_PREFIX, _claim(15));
    }

    function test_wrongNonce_otherKeysCtx() public {
        _startFails(Fixture.WRONG_NONCE, Fixture.OFFS_WRONG_NONCE, _claim(12));
    }

    function test_wrongNonce_notACtx() public {
        _startFails(Fixture.NONCE_PLAIN_KEY, Fixture.OFFS_NONCE_PLAIN_KEY, _claim(12));
    }

    function test_wrongNonce_tokenForNextAttempt() public {
        _startFails(Fixture.NONCE9, Fixture.OFFS_NONCE9, _claim(12));
    }

    function test_goodToken_otherNewKey() public {
        vm.prank(address(a));
        vm.expectRevert(_claim(12));
        a.startRotationEvp(OTHERKEY, TH, DEADLINE, _cfg(), Fixture.GOOD, Fixture.OFFS_GOOD);
    }

    function test_goodToken_otherSessionTag() public {
        vm.prank(address(a));
        vm.expectRevert(_claim(12));
        a.startRotationEvp(NEWKEY, keccak256("x"), DEADLINE, _cfg(), Fixture.GOOD, Fixture.OFFS_GOOD);
    }

    function test_staleIat() public {
        _startFails(Fixture.STALE, Fixture.OFFS_STALE, abi.encodeWithSelector(EvpCheck.Stale.selector));
    }

    function test_futureIat() public {
        _startFails(Fixture.FUTURE, Fixture.OFFS_FUTURE, abi.encodeWithSelector(EvpCheck.Stale.selector));
    }

    /// iat window edge: at iat + 900 (== deadline) the token still passes; one second later the deadline fails.
    function test_iatWindowEdgeEqualsDeadline() public {
        vm.warp(Fixture.IAT + 900);
        _start(Fixture.GOOD, Fixture.OFFS_GOOD);
    }

    function test_expired() public {
        vm.warp(DEADLINE + 1);
        _startFails(Fixture.GOOD, Fixture.OFFS_GOOD, abi.encodeWithSelector(EvpRecoveryAccountLogic.Expired.selector));
    }

    function test_wrongIssuer_tokenFromOtherKey() public {
        _startFails(Fixture.OTHER_ISSUER, Fixture.OFFS_OTHER_ISSUER, _badSig(0));
    }

    /// The relayer cannot bring its own issuer: cfg is pinned by configHash.
    function test_wrongIssuer_cfgSwap() public {
        EvpCheck.Config memory c = _cfg();
        c.issuerX = Fixture.OTHER_ISSUER_X;
        c.issuerY = Fixture.OTHER_ISSUER_Y;
        vm.prank(address(a));
        vm.expectRevert(EvpRecoveryAccountLogic.BadConfig.selector);
        a.startRotationEvp(NEWKEY, TH, DEADLINE, c, Fixture.OTHER_ISSUER, Fixture.OFFS_OTHER_ISSUER);
    }

    function test_otherEmail() public {
        _startFails(Fixture.OTHER_EMAIL, Fixture.OFFS_OTHER_EMAIL, _claim(5));
    }

    function test_kbNotByCnfKey() public {
        _startFails(Fixture.KB_OTHER_KEY, Fixture.OFFS_KB_OTHER_KEY, _badSig(1));
    }

    function test_tamperedKbPayload() public {
        bytes memory t = Fixture.GOOD;
        uint256 k1 = (Fixture.OFFS_GOOD >> 48) & 0xffff;
        t[k1 + 10] = t[k1 + 10] == "A" ? bytes1("B") : bytes1("A");
        _startFails(t, Fixture.OFFS_GOOD, _badSig(1));
    }

    function test_badHint() public {
        _startFails(Fixture.GOOD, Fixture.OFFS_GOOD ^ (1 << (16 * 12)), _claim(12));
    }

    /// WebCrypto does not normalize s, EIP-7951 accepts both. A high-s KB signature must pass.
    function test_highS_kbAccepted() public {
        _start(Fixture.HIGH_S_KB, Fixture.OFFS_HIGH_S_KB);
        require(a.pendingOwner() == NEWKEY, "pending");
    }

    function test_highS_issuerAccepted() public {
        _start(Fixture.HIGH_S_ISSUER, Fixture.OFFS_HIGH_S_ISSUER);
        require(a.pendingOwner() == NEWKEY, "pending");
    }

    /// Malleability buys nothing: after GOOD lands, its high-s twin (same claims, same ctx) is dead.
    function test_highS_malleatedTwinCannotReplay() public {
        _start(Fixture.GOOD, Fixture.OFFS_GOOD);
        _startFails(Fixture.HIGH_S_KB, Fixture.OFFS_HIGH_S_KB, _claim(12));
    }

    function test_bodyOnlySelf() public {
        vm.expectRevert(EvpRecoveryAccountLogic.NotSelf.selector);
        a.startRotationEvp(NEWKEY, TH, DEADLINE, _cfg(), Fixture.GOOD, Fixture.OFFS_GOOD);
    }

    function test_bodyRejectsOwnerAsNewKey() public {
        vm.prank(address(a));
        vm.expectRevert(EvpRecoveryAccountLogic.BadNewKey.selector);
        a.startRotationEvp(OWNER, TH, DEADLINE, _cfg(), Fixture.GOOD, Fixture.OFFS_GOOD);
    }

    function test_setters_onlySelf() public {
        vm.expectRevert(EvpRecoveryAccountLogic.NotSelf.selector);
        a.setLaptop(address(0xBAD));
        vm.expectRevert(EvpRecoveryAccountLogic.NotSelf.selector);
        a.setLaptopDevice(1);
        vm.expectRevert(EvpRecoveryAccountLogic.NotSelf.selector);
        a.setConfig(bytes32(uint256(1)));
    }

    function test_setConfig_changesPin() public {
        vm.prank(address(a));
        a.setConfig(keccak256("other"));
        _startFails(Fixture.GOOD, Fixture.OFFS_GOOD, abi.encodeWithSelector(EvpRecoveryAccountLogic.BadConfig.selector));
    }
}

/// DESIGN.md 4.2 / 4.3 and the untouched paths.
contract EvpFinishCancelTest is EvpBase {
    function setUp() public {
        _setUpAccount();
        _start(Fixture.GOOD, Fixture.OFFS_GOOD); // pendingOwner = NEWKEY, readyAt = NOW + 120, nonce 8
    }

    function _oneSigEnv(address signer, bytes memory body) internal {
        a.setTx(0x0B, 1);
        a.setTx(0x09, 2);
        a.setTx(0x0A, 0);
        a.setFrame(0, 0x06, 3);
        _sig(0, 2, signer, 0);
        _setSelfCall(1, body);
    }

    function test_finish_verifyPassesForPendingKey() public {
        _oneSigEnv(NEWKEY, abi.encodeCall(EvpRecoveryAccountLogic.finishRotation, ()));
        _verify();
        require(a.approvedScope() == 3, "self-paid finish");
    }

    /// Accepted grief (DESIGN.md 4.3): N can send finish early; VERIFY passes, the body reverts, A pays.
    function test_finish_early_bodyReverts() public {
        vm.expectRevert(EvpRecoveryAccountLogic.TooEarly.selector);
        a.finishRotation();
        vm.warp(NOW + 119);
        vm.expectRevert(EvpRecoveryAccountLogic.TooEarly.selector);
        a.finishRotation();
    }

    function test_finish_strangerCannotPassVerify() public {
        _oneSigEnv(OTHERKEY, abi.encodeCall(EvpRecoveryAccountLogic.finishRotation, ()));
        _verifyFails(EvpRecoveryAccountLogic.NotOwner.selector);
    }

    function test_finish_afterDelay() public {
        vm.warp(NOW + 120);
        a.finishRotation();
        require(a.owner() == NEWKEY && a.pendingOwner() == address(0) && a.readyAt() == 0, "rotated");
        require(a.recoveryNonce() == NONCE0 + 2, "nonce");
    }

    function test_pendingKey_cannotCancelOrCallOther() public {
        _oneSigEnv(NEWKEY, abi.encodeCall(EvpRecoveryAccountLogic.cancelRotation, ()));
        _verifyFails(EvpRecoveryAccountLogic.Layout.selector);
        _oneSigEnv(NEWKEY, abi.encodeCall(EvpRecoveryAccountLogic.setLaptop, (NEWKEY)));
        _verifyFails(EvpRecoveryAccountLogic.Layout.selector);
    }

    function test_cancel_byOwner() public {
        _oneSigEnv(OWNER, abi.encodeCall(EvpRecoveryAccountLogic.cancelRotation, ()));
        _verify();
        vm.prank(address(a));
        a.cancelRotation();
        require(a.pendingOwner() == address(0) && a.owner() == OWNER && a.recoveryNonce() == NONCE0 + 2, "cancel");
        vm.warp(NOW + 1 days);
        vm.expectRevert(EvpRecoveryAccountLogic.NoPending.selector);
        a.finishRotation();
    }

    function test_cancel_nothingPending() public {
        vm.prank(address(a));
        a.cancelRotation();
        vm.prank(address(a));
        vm.expectRevert(EvpRecoveryAccountLogic.NoPending.selector);
        a.cancelRotation();
    }

    /// The laptop alone (no token, no phone) cannot use the account: only the 2-sig start branch knows it.
    function test_laptopAloneIsNotOwner() public {
        a.setTx(0x0B, 1);
        a.setTx(0x0A, 0);
        _sig(0, 1, LAPTOP, 0);
        _verifyFails(EvpRecoveryAccountLogic.NotP256.selector);
    }

    /// Meet-to-Recover (3 sigs) is untouched.
    function test_guardianPath_stillGreen() public {
        a.setTx(0x0B, 3);
        a.setTx(0x09, 3);
        a.setTx(0x0A, 1);
        a.setFrame(0, 0, uint160(address(0x8141)));
        a.setFrame(0, 2, 1);
        a.setFrameData(0, 0, bytes32(DEADLINE << 192));
        a.setFrame(1, 0x06, 3);
        bytes memory body = abi.encodeCall(EvpRecoveryAccountLogic.startRotation, (OTHERKEY, TH));
        a.setFrame(2, 0, uint160(address(a)));
        a.setFrame(2, 2, 2);
        a.setFrame(2, 4, body.length);
        a.setFrameData(2, 0, _word(body, 0));
        a.setFrameData(2, 4, _word(body, 4));
        a.setFrameData(2, 36, _word(body, 36));
        bytes32 d = a.recoveryDigest(OTHERKEY, a.recoveryNonce(), TH, DEADLINE);
        _sig(0, 2, OTHERKEY, 0);
        _sig(1, 2, G1, d);
        _sig(2, 2, G2, d);
        _verify();
        require(a.approvedScope() == 3, "scope");
        _sig(2, 2, G1, d);
        _verifyFails(EvpRecoveryAccountLogic.BadGuardian.selector);
    }

    function test_normalOwnerPath() public {
        a.setTx(0x0B, 1);
        a.setTx(0x0A, 0);
        a.setFrame(0, 0x06, 3);
        _sig(0, 2, OWNER, 0);
        _verify();
        require(a.approvedScope() == 3, "scope");
    }
}
