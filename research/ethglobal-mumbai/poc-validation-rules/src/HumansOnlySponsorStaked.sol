// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnv} from "./frame/FrameEnv.sol";
import {FrameEnvLive} from "./frame/FrameEnvLive.sol";

/// Design A2: the "storage" version of the humans-only sponsor. Shown for contrast with A1.
///
/// Frame layout:
///   0  expiry_verify
///   1  only_verify   sender (P256Account of device A)
///   2  pre_verify    DEFAULT  target=this  data=abi.encodeCall(consume, (refIndex))
///   3  pay           VERIFY   target=this  data=abi.encodeCall(pay, (refIndex, partner, transcript))
///   4+ SENDER frames
///
/// Needs stake (sidecar frameTx.ts 765-777, ERC STORAGE-031): it reads and writes its OWN storage
/// (humanOf, used). It is the shape the prize text calls a "daily-quota paymaster".
///
/// Reputation cost vs A1:
///   - quota race: N pending txs of one human all pass `consume` against the head state; only QUOTA
///     can land, the rest fail revalidation and count as seen-not-included against this payer.
///     A1 does not have this, because the keyed nonce makes those txs conflict (LIFECYCLE-020) instead.
///   - revocation: `revoke` flips humanOf and invalidates that human's pending txs (rare, owner-made).
abstract contract HumansOnlySponsorStakedLogic is FrameEnv {
    uint256 internal constant PRE_FRAME = 2;
    uint256 internal constant PAY_FRAME = 3;
    uint256 internal constant PARTNER_SIG = 1;
    bytes32 internal constant DOMAIN = keccak256("enconomy.HumansOnlySponsorStaked.v1");

    bytes32 public immutable BEACON_SOURCE;
    uint256 public immutable EPOCH_SLOTS;
    uint256 public immutable QUOTA;
    address public immutable registrar;

    mapping(address device => bytes32 human) public humanOf; // own storage: staked read
    mapping(bytes32 human => mapping(uint256 epoch => uint256 count)) public used; // own storage: staked write

    error NotEntryPoint();
    error Layout();
    error WrongSource();
    error NotHuman();
    error SameHuman();
    error QuotaUsed();
    error PreVerifyFailed();
    error PartnerSig();
    error NotRegistrar();

    constructor(bytes32 beaconSource, uint256 epochSlots, uint256 quota, address registrar_) {
        BEACON_SOURCE = beaconSource;
        EPOCH_SLOTS = epochSlots;
        QUOTA = quota;
        registrar = registrar_;
    }

    /// Normal tx. In a real build this checks a World ID proof; here a registrar stands in.
    function register(address device, bytes32 human) external {
        if (msg.sender != registrar) revert NotRegistrar();
        humanOf[device] = human;
    }

    function revoke(address device) external {
        if (msg.sender != registrar) revert NotRegistrar();
        delete humanOf[device];
    }

    function _epoch(uint256 refIndex) internal view returns (uint256 slot) {
        if (bytes32(_recentRoot(refIndex, RR_SOURCE_ID)) != BEACON_SOURCE) revert WrongSource();
        slot = _recentRoot(refIndex, RR_SLOT);
    }

    /// pre_verify: DEFAULT mode, caller ENTRY_POINT, before any APPROVE. ERC-8421 says it SHOULD act
    /// only on tx.sender's state; it does (humanOf[sender]).
    function _consume(uint256 refIndex) internal {
        if (msg.sender != ENTRY_POINT) revert NotEntryPoint();
        if (_txParam(TX_CURRENT_FRAME) != PRE_FRAME) revert Layout();
        address sender = address(uint160(_txParam(TX_SENDER)));
        bytes32 human = humanOf[sender];
        if (human == bytes32(0)) revert NotHuman();
        uint256 epoch = _epoch(refIndex) / EPOCH_SLOTS;
        uint256 n = used[human][epoch];
        if (n >= QUOTA) revert QuotaUsed();
        used[human][epoch] = n + 1;
    }

    function _pay(uint256 refIndex, address partner, bytes32 transcript) internal {
        if (msg.sender != ENTRY_POINT) revert NotEntryPoint();
        if (_txParam(TX_CURRENT_FRAME) != PAY_FRAME) revert Layout();
        // ERC-8421: the approving frame MUST check its pre_verify frame succeeded; a failed DEFAULT
        // frame does not invalidate the tx, so without this the quota write could be silently reverted.
        if (_frameParam(PRE_FRAME, FP_STATUS) != 1) revert PreVerifyFailed();
        if (_frameParam(PRE_FRAME, FP_TARGET) != uint256(uint160(address(this)))) revert Layout();
        address sender = address(uint160(_txParam(TX_SENDER)));
        bytes32 hA = humanOf[sender];
        bytes32 hB = humanOf[partner];
        if (hA == bytes32(0) || hB == bytes32(0)) revert NotHuman();
        if (hA == hB) revert SameHuman();
        uint256 slot = _epoch(refIndex);
        bytes32 root = bytes32(_recentRoot(refIndex, RR_ROOT));
        bytes32 d = keccak256(abi.encode(DOMAIN, block.chainid, address(this), slot, root, sender, partner, transcript));
        if (_sigParam(PARTNER_SIG, SP_SCHEME) != SCHEME_P256) revert PartnerSig();
        if (address(uint160(_sigParam(PARTNER_SIG, SP_SIGNER))) != partner) revert PartnerSig();
        if (bytes32(_sigParam(PARTNER_SIG, SP_MSG)) != d) revert PartnerSig();
        // freshness: same expiry_verify bound as A1 (omitted here to keep the contrast short)
        _approve(SCOPE_PAYMENT);
    }
}

contract HumansOnlySponsorStaked is HumansOnlySponsorStakedLogic, FrameEnvLive {
    constructor(bytes32 beaconSource, uint256 epochSlots, uint256 quota, address registrar_)
        payable
        HumansOnlySponsorStakedLogic(beaconSource, epochSlots, quota, registrar_)
    {}

    function consume(uint256 refIndex) external {
        _consume(refIndex);
    }

    function pay(uint256 refIndex, address partner, bytes32 transcript) external {
        _pay(refIndex, partner, transcript);
    }

    /// The sponsor stakes itself: NaiveStakingRegistry keys stake on msg.sender, so a paymaster needs
    /// code that forwards addStake (docs guides/staking). Live registry 0xd51c04d7a0b01124e84de152f4e56d9eecb22d2f.
    function stake(address registry, uint32 unstakeDelaySec) external payable {
        if (msg.sender != registrar) revert NotRegistrar();
        (bool ok,) = registry.call{value: msg.value}(abi.encodeWithSignature("addStake(uint32)", unstakeDelaySec));
        require(ok, "stake");
    }

    receive() external payable {}
}
