// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnv} from "./frame/FrameEnv.sol";
import {FrameEnvLiveMux} from "./frame/FrameEnvLiveMux.sol";

/// Fallback I14, Meet-to-Recover: a P-256 phone account whose key rotates when two guardian phones that
/// just chirped with the new phone co-sign. Self-paid, own storage only, no stake, no keeper, no precompile.
///
/// VERIFY branches on the signature count:
///   1 sig, signer == owner         normal use, any frame list; approves what the frame allows
///   1 sig, signer == pendingOwner  finish path; frames pinned to [self_verify, SENDER finishRotation()]
///   3 sigs                         recovery; frames pinned to
///       0 expiry_verify VERIFY target=0x..8141 data=uint64 deadline
///       1 self_verify   VERIFY target=this
///       2 SENDER        target=this data=startRotation(newKey, transcript), 68 bytes
///     sig[0] = newKey over the sig hash (proves the new phone holds the key, commits to the frames)
///     sig[1], sig[2] = two distinct guardians, explicit msg D = keccak(DOMAIN, chainid, this, newKey,
///                      recoveryNonce, transcript, deadline)
///
/// Freshness without a keeper: D commits to the expiry deadline. The protocol drops the tx after it, and
/// the guardian app only signs a deadline ~15 min out. No 8272 beacon, so no server in the loop.
/// Storage read in VERIFY: owner / pendingOwner / recoveryNonce / isGuardian[g] -- all the sender's own.
///
/// Timelock in body frames (TIMESTAMP is fine there): startRotation sets pendingOwner + readyAt; owner can
/// cancelRotation; anyone can finishRotation after readyAt. recoveryNonce bumps on start/cancel/finish,
/// so collected guardian signatures die with the attempt they were made for.
abstract contract RecoverableP256AccountLogic is FrameEnv {
    bytes32 internal constant DOMAIN = keccak256("enconomy.MeetToRecover.v1");

    uint256 public immutable DELAY; // seconds; 48 h real, 120 s demo

    address public owner; // device address keccak(qx||qy)[12:]
    address public pendingOwner;
    uint64 public readyAt;
    uint256 public recoveryNonce;
    uint256 public guardianCount;
    mapping(address device => bool) public isGuardian;

    event GuardianSet(address indexed guardian, bool on);
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

    constructor(address owner_, address[] memory guardians, uint256 delay) {
        if (owner_ == address(0)) revert Zero();
        owner = owner_;
        DELAY = delay;
        for (uint256 i = 0; i < guardians.length; i++) {
            _setGuardian(guardians[i], true);
        }
    }

    function recoveryDigest(address newKey, uint256 nonce, bytes32 transcript, uint256 deadline)
        public
        view
        returns (bytes32)
    {
        return keccak256(abi.encode(DOMAIN, block.chainid, address(this), newKey, nonce, transcript, deadline));
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

    /// SENDER frame of a recovery tx (or the owner rotating on purpose). Replaces any pending rotation.
    function startRotation(address newKey, bytes32 transcript) external onlySelf {
        if (newKey == address(0)) revert Zero();
        pendingOwner = newKey;
        uint64 t = uint64(block.timestamp + DELAY);
        readyAt = t;
        recoveryNonce++;
        emit RotationStarted(newKey, t, transcript);
    }

    /// Owner's normal tx. A thief holding the owner key can also cancel forever: this design protects
    /// against LOSS, not theft. Theft needs a guardian veto, out of scope here.
    function cancelRotation() external onlySelf {
        address p = pendingOwner;
        if (p == address(0)) revert NoPending();
        delete pendingOwner;
        delete readyAt;
        recoveryNonce++;
        emit RotationCancelled(p);
    }

    /// Anyone, after the delay: a guardian's EOA, or the new phone via the pinned finish path.
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

    function _setGuardian(address g, bool on) internal {
        if (g == address(0)) revert Zero();
        if (isGuardian[g] == on) return;
        isGuardian[g] = on;
        if (on) guardianCount++;
        else guardianCount--;
        emit GuardianSet(g, on);
    }
}

contract RecoverableP256Account is RecoverableP256AccountLogic, FrameEnvLiveMux {
    constructor(address owner_, address[] memory guardians, uint256 delay)
        payable
        RecoverableP256AccountLogic(owner_, guardians, delay)
    {}

    fallback() external payable {
        if (msg.sender == ENTRY_POINT) _verifyFrame();
        // SENDER frames call targets directly with caller = this account; nothing to dispatch here.
    }

    // No receive(): a VERIFY frame with empty data would land there and never APPROVE. The payable
    // fallback takes plain ETH too.
}
