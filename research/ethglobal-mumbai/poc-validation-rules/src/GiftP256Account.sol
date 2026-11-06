// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnvLiveMux} from "./frame/FrameEnvLiveMux.sol";
import {P256AccountLogic} from "./P256Account.sol";

/// W4 Gas Gift (../08-wildcards.md): B's own P-256 account pays for A's tx. No sponsor, no registry, no stake.
///
/// Same account as P256AccountMux (owner path unchanged: empty-data VERIFY frame -> fallback -> _verifyFrame),
/// plus one payer path: `gift(cap)` in a VERIFY frame of SOMEONE ELSE's tx.
///
/// Frames (pinned, exactly 4):
///   0  expiry_verify  VERIFY  target=0x..8141  flags=0  data = be64(deadline)
///   1  only_verify    VERIFY  target=null      flags=2  (A's account approves execution)
///   2  gift           VERIFY  target=this      flags=1  data = gift(cap)
///   3  SENDER         SENDER  target=any       data = A's call
/// Signatures (exactly 2): [0] A, sig hash (A's account checks it). [1] B = owner, P256, msg = D.
///
/// D = keccak(abi.encode(DOMAIN, chainid, this, sender, nonceKeysHash, seq, deadline, cap, bodyHash))
/// bodyHash = keccak(abi.encodePacked(frame3.target, frame3.data))
///
/// Why an explicit D, not B over the sig hash: the sidecar estimate rewrites body limits (poc/clients README,
/// gotcha 1), which moves the sig hash. D leaves gas limits and fees out (cap bounds them), so B's phone signs
/// once and the same entry works for the estimate copy and the send. D still pins who (sender), which tx
/// (key set + seq: one gift = one tx), until when (deadline), how much (cap) and what (body).
///
/// Footprint: zero SLOAD (owner is immutable), no precompile, no foreign account except the own mux helper.
/// The ChirpGas partner entry (msg = ChirpGas D, other domain) can never satisfy this D.
abstract contract GiftP256AccountLogic is P256AccountLogic {
    uint256 internal constant GIFT_EXPIRY_FRAME = 0;
    uint256 internal constant GIFT_ACCOUNT_FRAME = 1;
    uint256 internal constant GIFT_FRAME = 2;
    uint256 internal constant GIFT_BODY_FRAME = 3;
    uint256 internal constant GIFT_FRAME_COUNT = 4;
    uint256 internal constant GIFT_SIG_COUNT = 2;
    uint256 internal constant GIFT_SIG = 1;
    bytes32 internal constant GIFT_DOMAIN = keccak256("enconomy.Gift.v1");

    error NotEntryPoint();
    error GiftLayout();
    error GiftNoExpiry();
    error GiftSig();
    error GiftTooExpensive();

    /// What B's phone signs (signatures[1].msg).
    function giftDigest(
        address sender,
        bytes32 nonceKeysHash,
        uint256 seq,
        uint256 deadline,
        uint256 cap,
        bytes32 bodyHash
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(GIFT_DOMAIN, block.chainid, address(this), sender, nonceKeysHash, seq, deadline, cap, bodyHash)
        );
    }

    function _gift(uint256 cap) internal {
        // 1. caller and shape
        if (msg.sender != ENTRY_POINT) revert NotEntryPoint();
        if (_txParam(TX_CURRENT_FRAME) != GIFT_FRAME) revert GiftLayout();
        if (_txParam(TX_FRAME_COUNT) != GIFT_FRAME_COUNT) revert GiftLayout();
        if (_txParam(TX_SIG_COUNT) != GIFT_SIG_COUNT) revert GiftLayout();
        if (_frameParam(GIFT_FRAME, FP_ALLOWED_SCOPE) != SCOPE_PAYMENT) revert GiftLayout();
        address sender = address(uint160(_txParam(TX_SENDER)));
        if (_frameParam(GIFT_ACCOUNT_FRAME, FP_TARGET) != uint256(uint160(sender))) revert GiftLayout();
        if (_frameParam(GIFT_BODY_FRAME, FP_MODE) != MODE_SENDER) revert GiftLayout();

        // 2. frame 0 is the expiry predeploy (protocol enforces deadline >= block.timestamp)
        if (_frameParam(GIFT_EXPIRY_FRAME, FP_TARGET) != uint256(uint160(EXPIRY_VERIFIER))) revert GiftNoExpiry();
        if (_frameParam(GIFT_EXPIRY_FRAME, FP_MODE) != MODE_VERIFY) revert GiftNoExpiry();
        uint256 deadline = uint256(_frameDataLoad(GIFT_EXPIRY_FRAME, 0)) >> 192;

        // 3. B's entry over D
        bytes32 d = giftDigest(
            sender, bytes32(_txParam(TX_NONCE_KEYS_HASH)), _txParam(TX_NONCE_SEQ), deadline, cap, _bodyHash()
        );
        if (_sigParam(GIFT_SIG, SP_SCHEME) != SCHEME_P256) revert GiftSig();
        if (address(uint160(_sigParam(GIFT_SIG, SP_SIGNER))) != owner) revert GiftSig();
        if (bytes32(_sigParam(GIFT_SIG, SP_MSG)) != d) revert GiftSig();

        // 4. bounded spend: APPROVE(payment) debits TX_MAX_COST from this account (frame_tx.rs apply_approve)
        if (_txParam(TX_MAX_COST) > cap) revert GiftTooExpensive();

        // 5. payment only. Never execution: this path must not make B the authorizer of anything.
        _approve(SCOPE_PAYMENT);
    }

    /// keccak(target || data) of the body frame, data pulled 32 bytes at a time with FRAMEDATALOAD.
    function _bodyHash() internal view returns (bytes32 h) {
        uint256 len = _frameParam(GIFT_BODY_FRAME, FP_DATA_LEN);
        bytes memory buf = new bytes(20 + len + 32);
        uint256 target = _frameParam(GIFT_BODY_FRAME, FP_TARGET);
        assembly ("memory-safe") {
            mstore(add(buf, 0x20), shl(96, target))
        }
        for (uint256 off = 0; off < len; off += 32) {
            bytes32 w = _frameDataLoad(GIFT_BODY_FRAME, off);
            assembly ("memory-safe") {
                mstore(add(add(buf, 0x34), off), w)
            }
        }
        assembly ("memory-safe") {
            h := keccak256(add(buf, 0x20), add(20, len))
        }
    }
}

/// Build target: B's phone account, on the one-helper mux.
contract GiftP256Account is GiftP256AccountLogic, FrameEnvLiveMux {
    constructor(address owner_) payable P256AccountLogic(owner_) {}

    function gift(uint256 cap) external {
        _gift(cap);
    }

    fallback() external payable {
        if (msg.sender == ENTRY_POINT) _verifyFrame();
    }
}
