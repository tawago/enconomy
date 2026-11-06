// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {FrameEnv} from "./frame/FrameEnv.sol";
import {FrameEnvLiveMux} from "./frame/FrameEnvLiveMux.sol";
import {EvpCheck} from "./EvpCheck.sol";
import {IPopPresenceVerifier} from "./pop/IPopPresenceVerifier.sol";
import {PopCtx} from "./pop/PopCtx.sol";

/// RecoverableP256Account (poc-validation-rules) plus the EVP start of DESIGN.md. VERIFY reads own storage only, no
/// stake, no keeper. The EVP start also calls the presence verifier and checks the proximity proofs in VERIFY, so it
/// needs our own sidecar (16M verify cap, precompiles allowed). The public sidecar rejects it. Other paths unchanged.
///
/// VERIFY branches on the signature count (DESIGN.md 4.4):
///   1 sig, signer == owner         normal use, any frame list (cancel goes here)
///   1 sig, signer == pendingOwner  finish; frames pinned to [self_verify, SENDER finishRotation()]
///   2 sigs                         EVP start, frames pinned to
///       0 VERIFY target=0x..8141 scope 0     data = be64(deadline)
///       1 VERIFY target=this     scope EXEC  data = evpVerify(notBefore, sid, qx, qy, cfg, bundle). Never pays
///       2 VERIFY target=laptop   scope PAY   (laptop EOA, default code, pays)
///       3 SENDER target=this     data = startRotationEvp(newKey, sessionTag, deadline, cfg, token, offs)
///     sig[0] = P-256, signer newKey, msg = ctx       sig[1] = secp256k1, signer laptop, msg empty (sig hash)
///   3 sigs                         Meet-to-Recover (unchanged): new key + two guardians over D
///
/// ctx = keccak(abi.encode(DOMAIN, chainid, this, newKey, recoveryNonce, sessionTag, deadline)). sessionTag is
/// chosen by the page before the chirp. It is not a hash of the recording, so the proof can commit to ctx:
/// popNonce = PopCtx.nonce(chainid, this, ctx, notBefore, sid), carried by all three proofs. The body recomputes
/// ctx from the same storage and checks the EVP token's KB nonce == "0x" + hex(ctx).
/// recoveryNonce bumps on start, cancel and finish, so a token, a phone entry, a proof and a tx die with the attempt.
///
/// Frame 1 data is in the sig hash on our ethrex (compute_sig_hash: frames verbatim), so L signs it. The contract
/// does not rely on that: notBefore and sid go into popNonce, cfg into configHash, (qx, qy) into newKey, and the
/// bundle is held to popNonce, the pinned issuer and the two device Xs.
abstract contract EvpRecoveryAccountLogic is FrameEnv, EvpCheck {
    bytes32 internal constant DOMAIN = keccak256("enconomy.MeetToRecover.v1"); // guardian path
    bytes32 public constant EVP_DOMAIN = keccak256("enconomy.EvpRecover.v1"); // DESIGN.md section 3

    uint256 public immutable DELAY; // seconds; 120 s demo

    address public owner; // device address keccak(qx||qy)[12:]
    address public pendingOwner;
    uint64 public readyAt;
    // Packs into slot 1 with pendingOwner and readyAt (20 + 8 + 4 = 32 bytes). Set once, never cleared, so
    // slot 1 is never zero and no start pays EIP-8037 state gas for a fresh slot (64 * 1530 = 97,920). Inside
    // a frame tx a frame's state budget is all it gets: no spill from execution gas (ethrex vm.rs
    // increase_state_gas). Same reason recoveryNonce starts at 1.
    uint32 private slot1Keep;
    uint256 public recoveryNonce;
    uint256 public guardianCount;
    mapping(address device => bool) public isGuardian;
    address public laptop; // L: secp256k1 EOA, payer and enrolled second factor
    bytes32 public configHash; // keccak(abi.encode(Config)): EVP issuer, emailHash, audHash, PoP issuer, verifier
    // Laptop's P-256 device X, role A of the chirp. L above stays the payer. Set in the constructor and read at
    // start, so a start writes no fresh slot.
    uint256 public laptopDeviceX;

    event GuardianSet(address indexed guardian, bool on);
    event LaptopSet(address indexed laptop);
    event LaptopDeviceSet(uint256 x);
    event ConfigSet(bytes32 configHash);
    event RotationStarted(address indexed newOwner, uint64 readyAt, bytes32 transcript);
    event RotationCancelled(address indexed newOwner);
    event RotationFinished(address indexed oldOwner, address indexed newOwner);

    error NotEntryPoint();
    error NotSelf();
    error NotP256();
    error NotSigHash();
    error NotOwner();
    error Layout();
    error NoExpiry();
    error BadGuardian();
    error GuardianSig();
    error NoPending();
    error TooEarly();
    error Zero();
    // EVP start
    error NotEvpScope(); // frame 1 must approve execution only
    error BadPayer(); // frame 2 / sig[1] is not the enrolled laptop paying
    error DeadlineMismatch(); // calldata deadline != frame 0
    error BadNewKey(); // zero, or the current owner
    error BadCtxSig(); // sig[0] is not newKey's P-256 entry over ctx
    error BadConfig(); // keccak(cfg) != configHash
    error Expired();
    error NoLaptopDevice(); // no laptop P-256 device X enrolled
    error BadNewDevice(); // keccak(qx||qy)[12:] != newKey
    error BadPresence(); // verifier did not return its selector

    constructor(
        address owner_,
        address[] memory guardians,
        uint256 delay,
        address laptop_,
        uint256 laptopDeviceX_,
        bytes32 configHash_
    ) {
        if (owner_ == address(0)) revert Zero();
        owner = owner_;
        slot1Keep = 1;
        recoveryNonce = 1; // slot 2 never fresh either
        DELAY = delay;
        laptop = laptop_;
        laptopDeviceX = laptopDeviceX_;
        configHash = configHash_;
        for (uint256 i = 0; i < guardians.length; i++) {
            _setGuardian(guardians[i], true);
        }
    }

    // ------------------------------------------------------------------ digests -----------------------
    function recoveryDigest(address newKey, uint256 nonce, bytes32 transcript, uint256 deadline)
        public
        view
        returns (bytes32)
    {
        return keccak256(abi.encode(DOMAIN, block.chainid, address(this), newKey, nonce, transcript, deadline));
    }

    /// DESIGN.md section 3, pure, so the shared vector can be checked for any account address.
    function ctxFor(
        uint256 chainId,
        address account,
        address newKey,
        uint256 nonce,
        bytes32 sessionTag,
        uint256 deadline
    ) public pure returns (bytes32) {
        return keccak256(abi.encode(EVP_DOMAIN, chainId, account, newKey, nonce, sessionTag, deadline));
    }

    /// ctx for this account at the current recoveryNonce. The page calls this (eth_call) or recomputes it.
    function evpCtx(address newKey, bytes32 sessionTag, uint256 deadline) public view returns (bytes32) {
        return ctxFor(block.chainid, address(this), newKey, recoveryNonce, sessionTag, deadline);
    }

    /// The nonce all three proofs carry, split hi/lo. The page calls this before the chirp.
    function popNonceFor(bytes32 ctx, uint64 notBefore, bytes16 sid) public view returns (bytes32) {
        return PopCtx.nonce(block.chainid, address(this), ctx, notBefore, sid);
    }

    /// Offline / eth_call check of a token against the pinned config and a ctx. Same code as the body.
    function checkEvp(bytes calldata token, uint256 offs, Config calldata cfg, bytes32 ctx) external view {
        if (keccak256(abi.encode(cfg)) != configHash) revert BadConfig();
        _checkEvp(token, offs, cfg, ctx);
    }

    // ------------------------------------------------------------------ VERIFY ------------------------
    function _verifyFrame() internal {
        if (msg.sender != ENTRY_POINT) revert NotEntryPoint();
        uint256 n = _txParam(TX_SIG_COUNT);
        uint256 cur = _txParam(TX_CURRENT_FRAME);
        if (n == 1) {
            address signer = _p256SigHashSigner(0);
            if (signer == owner) {
                // normal path
            } else if (signer == pendingOwner && signer != address(0)) {
                if (_txParam(TX_FRAME_COUNT) != 2 || cur != 0) revert Layout();
                _pinSelfCall(1, 4, this.finishRotation.selector);
            } else {
                revert NotOwner();
            }
        } else if (n == 3) {
            _verifyRecovery(cur);
        } else {
            revert Layout();
        }
        _approve(_frameParam(cur, FP_ALLOWED_SCOPE));
    }

    /// Frame 1 of the EVP start. The only way into the 2-sig branch: the fallback path refuses 2 sigs, so a start
    /// cannot skip the proofs. A bad proof reverts here, the tx is invalid and L pays nothing.
    function evpVerify(
        uint64 notBefore,
        bytes16 sid,
        uint256 qx,
        uint256 qy,
        Config calldata cfg,
        bytes calldata bundle
    ) external {
        if (msg.sender != ENTRY_POINT) revert NotEntryPoint();
        if (_txParam(TX_SIG_COUNT) != 2) revert Layout();
        (address newKey, bytes32 c, uint256 deadline) = _verifyEvpStart(_txParam(TX_CURRENT_FRAME));

        // Checked again in the body on frame 3's copy. One hash pins both.
        if (keccak256(abi.encode(cfg)) != configHash) revert BadConfig();
        if (address(uint160(uint256(keccak256(abi.encode(qx, qy))))) != newKey) revert BadNewDevice();
        uint256 laptopX = laptopDeviceX;
        if (laptopX == 0) revert NoLaptopDevice();
        bytes4 ok = IPopPresenceVerifier(cfg.presenceVerifier).verifyPresence(
            popNonceFor(c, notBefore, sid), laptopX, qx, cfg.popIssuerX, cfg.popIssuerY, notBefore, deadline, bundle
        );
        if (ok != IPopPresenceVerifier.verifyPresence.selector) revert BadPresence();

        // Execution only. The laptop pays (frame 2). If this frame approved payment, junk tokens would be
        // paid by the account: threat-model.md 2.7.
        _approve(SCOPE_EXECUTION);
    }

    /// DESIGN.md 4.1. Reads own storage only: laptop, owner, recoveryNonce. Returns what the proof check needs.
    function _verifyEvpStart(uint256 cur) private view returns (address newKey, bytes32 c, uint256 deadline) {
        if (_txParam(TX_FRAME_COUNT) != 4 || cur != 1) revert Layout();
        if (_frameParam(1, FP_MODE) != MODE_VERIFY) revert Layout(); // a failed proof must invalidate the tx
        if (_frameParam(1, FP_ALLOWED_SCOPE) != SCOPE_EXECUTION) revert NotEvpScope();

        // frame 0: expiry predeploy in VERIFY mode, deadline = be64 data
        if (_frameParam(0, FP_TARGET) != uint256(uint160(EXPIRY_VERIFIER))) revert NoExpiry();
        if (_frameParam(0, FP_MODE) != MODE_VERIFY) revert NoExpiry();
        deadline = uint256(_frameDataLoad(0, 0)) >> 192;

        // frame 2 + sig[1]: the enrolled laptop pays and signs the sig hash
        address l = laptop;
        if (l == address(0)) revert BadPayer();
        if (_frameParam(2, FP_MODE) != MODE_VERIFY) revert BadPayer();
        if (_frameParam(2, FP_TARGET) != uint256(uint160(l))) revert BadPayer();
        if (_frameParam(2, FP_ALLOWED_SCOPE) != SCOPE_PAYMENT) revert BadPayer();
        if (_sigParam(1, SP_SCHEME) != SCHEME_SECP256K1) revert BadPayer();
        if (_sigParam(1, SP_MSG) != 0) revert BadPayer();
        if (_sigParam(1, SP_SIGNER) != uint256(uint160(l))) revert BadPayer();

        // frame 3: SENDER self-call to startRotationEvp. Variable length (token), so no length pin; fixed ABI
        // head: newKey @4, sessionTag @36, deadline @68.
        if (_frameParam(3, FP_MODE) != MODE_SENDER) revert Layout();
        if (_frameParam(3, FP_TARGET) != uint256(uint160(address(this)))) revert Layout();
        if (bytes4(_frameDataLoad(3, 0)) != this.startRotationEvp.selector) revert Layout();
        uint256 rawKey = uint256(_frameDataLoad(3, 4));
        if (rawKey >> 160 != 0) revert BadNewKey(); // the body's ABI decoder would reject it anyway
        newKey = address(uint160(rawKey));
        bytes32 sessionTag = _frameDataLoad(3, 36);
        if (uint256(_frameDataLoad(3, 68)) != deadline) revert DeadlineMismatch();
        if (newKey == address(0) || newKey == owner) revert BadNewKey();

        // sig[0]: the new phone signed ctx (explicit msg), once, at chirp time
        c = ctxFor(block.chainid, address(this), newKey, recoveryNonce, sessionTag, deadline);
        if (_sigParam(0, SP_SCHEME) != SCHEME_P256) revert BadCtxSig();
        if (bytes32(_sigParam(0, SP_MSG)) != c) revert BadCtxSig();
        if (_sigParam(0, SP_SIGNER) != rawKey) revert BadCtxSig();
    }

    function _verifyRecovery(uint256 cur) private view {
        if (_txParam(TX_FRAME_COUNT) != 3 || cur != 1) revert Layout();
        if (_frameParam(0, FP_TARGET) != uint256(uint160(EXPIRY_VERIFIER))) revert NoExpiry();
        if (_frameParam(0, FP_MODE) != MODE_VERIFY) revert NoExpiry();
        uint256 deadline = uint256(_frameDataLoad(0, 0)) >> 192;
        _pinSelfCall(2, 68, this.startRotation.selector);
        address newKey = address(uint160(uint256(_frameDataLoad(2, 4))));
        bytes32 transcript = _frameDataLoad(2, 36);
        if (newKey == address(0) || _p256SigHashSigner(0) != newKey) revert NotOwner();

        bytes32 d = recoveryDigest(newKey, recoveryNonce, transcript, deadline);
        address g1 = _guardianSigner(1, d);
        address g2 = _guardianSigner(2, d);
        if (g1 == g2) revert BadGuardian();
    }

    function _guardianSigner(uint256 i, bytes32 d) private view returns (address g) {
        if (_sigParam(i, SP_SCHEME) != SCHEME_P256) revert GuardianSig();
        if (bytes32(_sigParam(i, SP_MSG)) != d) revert GuardianSig();
        g = address(uint160(_sigParam(i, SP_SIGNER)));
        if (!isGuardian[g]) revert BadGuardian();
    }

    function _p256SigHashSigner(uint256 i) private view returns (address) {
        if (_sigParam(i, SP_SCHEME) != SCHEME_P256) revert NotP256();
        if (_sigParam(i, SP_MSG) != 0) revert NotSigHash();
        return address(uint160(_sigParam(i, SP_SIGNER)));
    }

    function _pinSelfCall(uint256 frame, uint256 len, bytes4 selector) private view {
        if (_frameParam(frame, FP_MODE) != MODE_SENDER) revert Layout();
        if (_frameParam(frame, FP_TARGET) != uint256(uint160(address(this)))) revert Layout();
        if (_frameParam(frame, FP_DATA_LEN) != len) revert Layout();
        if (bytes4(_frameDataLoad(frame, 0)) != selector) revert Layout();
    }

    // ------------------------------------------------------------------ body frames -------------------
    modifier onlySelf() {
        if (msg.sender != address(this)) revert NotSelf();
        _;
    }

    /// Body of the EVP start tx (frame 3). Checks the email token, then starts the timelocked rotation. The proofs
    /// were checked in frame 1. ctx is computed here before _startRotation bumps the nonce.
    function startRotationEvp(
        address newKey,
        bytes32 sessionTag,
        uint256 deadline,
        Config calldata cfg,
        bytes calldata token,
        uint256 offs
    ) external onlySelf {
        if (keccak256(abi.encode(cfg)) != configHash) revert BadConfig();
        if (block.timestamp > deadline) revert Expired();
        if (newKey == address(0) || newKey == owner) revert BadNewKey();
        _checkEvp(token, offs, cfg, evpCtx(newKey, sessionTag, deadline));
        _startRotation(newKey, sessionTag);
    }

    /// SENDER frame of a guardian recovery tx (or the owner rotating on purpose). Replaces any pending rotation.
    function startRotation(address newKey, bytes32 transcript) external onlySelf {
        if (newKey == address(0)) revert Zero();
        _startRotation(newKey, transcript);
    }

    function _startRotation(address newKey, bytes32 transcript) private {
        pendingOwner = newKey;
        uint64 t = uint64(block.timestamp + DELAY);
        readyAt = t;
        recoveryNonce++;
        emit RotationStarted(newKey, t, transcript);
    }

    /// Owner's normal tx. A thief holding the owner key can also cancel forever: this design protects
    /// against LOSS, not theft.
    function cancelRotation() external onlySelf {
        address p = pendingOwner;
        if (p == address(0)) revert NoPending();
        delete pendingOwner;
        delete readyAt;
        recoveryNonce++;
        emit RotationCancelled(p);
    }

    /// Anyone, after the delay: the new phone via the pinned finish path, or any EOA.
    function finishRotation() external {
        address p = pendingOwner;
        if (p == address(0)) revert NoPending();
        if (block.timestamp < readyAt) revert TooEarly();
        emit RotationFinished(owner, p);
        owner = p;
        delete pendingOwner;
        delete readyAt;
        recoveryNonce++;
    }

    function setGuardian(address guardian, bool on) external onlySelf {
        _setGuardian(guardian, on);
    }

    function setLaptop(address l) external onlySelf {
        laptop = l;
        emit LaptopSet(l);
    }

    function setLaptopDevice(uint256 x) external onlySelf {
        laptopDeviceX = x;
        emit LaptopDeviceSet(x);
    }

    function setConfig(bytes32 h) external onlySelf {
        configHash = h;
        emit ConfigSet(h);
    }

    function _setGuardian(address g, bool on) internal {
        if (g == address(0)) revert Zero();
        if (isGuardian[g] == on) return;
        isGuardian[g] = on;
        if (on) guardianCount++;
        else guardianCount--;
        emit GuardianSet(g, on);
    }
}

contract EvpRecoveryAccount is EvpRecoveryAccountLogic, FrameEnvLiveMux {
    constructor(
        address owner_,
        address[] memory guardians,
        uint256 delay,
        address laptop_,
        uint256 laptopDeviceX_,
        bytes32 configHash_
    ) payable EvpRecoveryAccountLogic(owner_, guardians, delay, laptop_, laptopDeviceX_, configHash_) {}

    fallback() external payable {
        if (msg.sender == ENTRY_POINT) _verifyFrame();
    }

    // No receive(): a VERIFY frame with empty data would land there and never APPROVE.
}
