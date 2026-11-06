// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnv} from "./frame/FrameEnv.sol";
import {FrameEnvLive} from "./frame/FrameEnvLive.sol";

/// Design A1: humans-only gas sponsor that reads NO storage in its VERIFY frame.
///
/// Frame layout (indices are fixed and checked):
///   0  expiry_verify  VERIFY flags=0  target=0x..8141  data=uint64 deadline (8 bytes)
///   1  only_verify    VERIFY flags=2  target=null      sender = P256Account of device A
///   2  pay            VERIFY flags=1  target=this      data=abi.encodeCall(pay, (att))
///   3+ SENDER frames  the user's actions
///
/// Envelope:
///   signatures[0]  P256, signer=device key A, msg=empty     checked by P256Account (sender)
///   signatures[1]  P256, signer=B, msg=D (explicit digest)  checked here
///   nonce_keys     [epochKey(S)], nonce_seq < QUOTA         the daily quota IS the keyed nonce
///   recent_root_references[att.refIndex] = (HUMANS_SOURCE, S, R), R = keccak(treeRoot, beaconSalt)
///
/// What replaces storage:
///   - who is human: Merkle proofs against a humans root that the registry publishes to the EIP-8272
///     predeploy. The protocol checks the reference before any frame runs; the frame reads it with
///     RECENTROOTREFLOAD. No SLOAD, so no stake needed and no mass-invalidation surface.
///   - freshness: lower bound = slot S of the reference (R is unpredictable before S, the partner signed
///     over R). Upper bound = expiry_verify deadline, which the protocol enforces (deadline >= timestamp)
///     and the mempool drops after it passes (PREFIX-080). We require deadline <= time(S) + WINDOW.
///   - daily quota: nonce key = keccak(this, epoch(S)), nonce_seq < QUOTA. NONCE_MANAGER is the
///     counter; the protocol bumps it at APPROVE. Nothing to write, nothing for pending txs to race on.
abstract contract HumansOnlySponsorLogic is FrameEnv {
    struct Attestation {
        uint256 refIndex; // index into recent_root_references
        bytes32 treeRoot; // humans Merkle root; leaf = keccak(keccak(abi.encode(account, deviceKey, humanId)))
        bytes32 beaconSalt; // registry's random salt mixed into the published value
        address partner; // device key of B (resolved P-256 signer of signatures[1])
        address partnerAccount; // B's P256Account; binds B's leaf the same way as A's
        bytes32 humanA; // World ID nullifier hash of A's human (app-scoped action)
        bytes32 humanB;
        bytes32 transcript; // hash of the acoustic session transcript both phones produced
        bytes32[] proofA;
        bytes32[] proofB;
    }

    uint256 internal constant EXPIRY_FRAME = 0;
    uint256 internal constant SENDER_FRAME = 1;
    uint256 internal constant PAY_FRAME = 2;
    uint256 internal constant PARTNER_SIG = 1;
    bytes32 internal constant DOMAIN = keccak256("enconomy.HumansOnlySponsor.v1");

    bytes32 public immutable HUMANS_SOURCE; // keccak(registry || salt), EIP-8272 source_id
    uint256 public immutable GENESIS_TIME; // devnet: slot 0 time (measured ~1791464620, 6 s slots)
    uint256 public immutable SLOT_SECONDS;
    uint256 public immutable WINDOW; // seconds an attestation stays usable, e.g. 900
    uint256 public immutable EPOCH_SLOTS; // quota epoch length in slots, e.g. 14400 = 24 h at 6 s
    uint256 public immutable QUOTA; // sponsored txs per human per epoch
    uint256 public immutable MAX_COST; // cap on TXPARAM max cost, wei

    error Layout();
    error NotEntryPoint();
    error WrongSource();
    error WrongRoot();
    error NotHuman();
    error SameHuman();
    error PartnerSig();
    error NoExpiry();
    error Stale();
    error WrongNonceKey();
    error QuotaUsed();
    error TooExpensive();

    constructor(
        bytes32 humansSource,
        uint256 genesisTime,
        uint256 slotSeconds,
        uint256 window,
        uint256 epochSlots,
        uint256 quota,
        uint256 maxCost
    ) {
        HUMANS_SOURCE = humansSource;
        GENESIS_TIME = genesisTime;
        SLOT_SECONDS = slotSeconds;
        WINDOW = window;
        EPOCH_SLOTS = epochSlots;
        QUOTA = quota;
        MAX_COST = maxCost;
    }

    /// The key a sender must use in epoch `epoch`. Wallets compute it off-chain.
    function epochKey(uint256 epoch) public view returns (uint256) {
        return uint256(keccak256(abi.encode(DOMAIN, address(this), epoch)));
    }

    /// The digest device B signs during the meeting (device A signs the same transcript off-chain;
    /// on-chain A is covered by signatures[0] over the sig hash, which commits to this frame's data).
    function attestationDigest(uint256 slot, bytes32 root, address a, address b, bytes32 transcript)
        public
        view
        returns (bytes32)
    {
        return keccak256(abi.encode(DOMAIN, block.chainid, address(this), slot, root, a, b, transcript));
    }

    function _pay(Attestation calldata att) internal {
        if (msg.sender != ENTRY_POINT) revert NotEntryPoint();
        if (_txParam(TX_CURRENT_FRAME) != PAY_FRAME) revert Layout();
        address sender = address(uint160(_txParam(TX_SENDER)));

        // 1. the humans root, from the envelope (protocol checked: 1 <= head_slot - S <= 8191, committed)
        if (bytes32(_recentRoot(att.refIndex, RR_SOURCE_ID)) != HUMANS_SOURCE) revert WrongSource();
        uint256 slot = _recentRoot(att.refIndex, RR_SLOT);
        bytes32 root = bytes32(_recentRoot(att.refIndex, RR_ROOT));
        if (keccak256(abi.encode(att.treeRoot, att.beaconSalt)) != root) revert WrongRoot();

        // 2. both (account, device key) pairs are registered, to two different humans. One leaf per
        //    World ID nullifier, so the per-sender quota below is a per-human quota.
        address deviceA = address(uint160(_sigParam(0, SP_SIGNER))); // checked by the account's own frame
        if (att.partnerAccount == sender || att.humanA == att.humanB) revert SameHuman();
        if (!_member(att.treeRoot, _leaf(sender, deviceA, att.humanA), att.proofA)) revert NotHuman();
        if (!_member(att.treeRoot, _leaf(att.partnerAccount, att.partner, att.humanB), att.proofB)) revert NotHuman();

        // 3. the partner device signed the meeting digest (the protocol already checked the P-256 math)
        bytes32 d = attestationDigest(slot, root, sender, att.partner, att.transcript);
        if (_sigParam(PARTNER_SIG, SP_SCHEME) != SCHEME_P256) revert PartnerSig();
        if (address(uint160(_sigParam(PARTNER_SIG, SP_SIGNER))) != att.partner) revert PartnerSig();
        if (bytes32(_sigParam(PARTNER_SIG, SP_MSG)) != d) revert PartnerSig();

        // 4. freshness without TIMESTAMP: inclusion time <= deadline <= time(S) + WINDOW
        if (_frameParam(EXPIRY_FRAME, FP_TARGET) != uint256(uint160(EXPIRY_VERIFIER))) revert NoExpiry();
        if (_frameParam(EXPIRY_FRAME, FP_MODE) != MODE_VERIFY) revert NoExpiry();
        uint256 deadline = uint256(_frameDataLoad(EXPIRY_FRAME, 0)) >> 192; // 8-byte big-endian
        if (deadline > GENESIS_TIME + slot * SLOT_SECONDS + WINDOW) revert Stale();

        // 5. quota = keyed nonce under this epoch's key
        if (_txParam(TX_NONCE_KEY_COUNT) != 1) revert WrongNonceKey();
        if (_txParam(TX_NONCE_KEY_0) != epochKey(slot / EPOCH_SLOTS)) revert WrongNonceKey();
        if (_txParam(TX_NONCE_SEQ) >= QUOTA) revert QuotaUsed();

        // 6. bounded spend per tx (APPROVE debits max cost up front, refunds the unused part)
        if (_txParam(TX_MAX_COST) > MAX_COST) revert TooExpensive();

        // 7. the sender frame is the one we expect (approval order is enforced by the protocol too)
        if (_frameParam(SENDER_FRAME, FP_TARGET) != uint256(uint160(sender))) revert Layout();

        _approve(SCOPE_PAYMENT);
    }

    function _leaf(address account, address deviceKey, bytes32 human) internal pure returns (bytes32) {
        return keccak256(bytes.concat(keccak256(abi.encode(account, deviceKey, human))));
    }

    /// Sorted-pair keccak Merkle proof (OpenZeppelin layout). keccak is an opcode: no precompile.
    function _member(bytes32 treeRoot, bytes32 leaf, bytes32[] calldata proof) internal pure returns (bool) {
        bytes32 h = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            h = h < p ? keccak256(abi.encode(h, p)) : keccak256(abi.encode(p, h));
        }
        return h == treeRoot;
    }
}

contract HumansOnlySponsor is HumansOnlySponsorLogic, FrameEnvLive {
    constructor(
        bytes32 humansSource,
        uint256 genesisTime,
        uint256 slotSeconds,
        uint256 window,
        uint256 epochSlots,
        uint256 quota,
        uint256 maxCost
    )
        payable
        HumansOnlySponsorLogic(humansSource, genesisTime, slotSeconds, window, epochSlots, quota, maxCost)
    {}

    function pay(Attestation calldata att) external {
        _pay(att);
    }

    receive() external payable {}
}
