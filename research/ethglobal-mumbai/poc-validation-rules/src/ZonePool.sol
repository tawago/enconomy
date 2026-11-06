// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnv} from "./frame/FrameEnv.sol";
import {FrameEnvLive} from "./frame/FrameEnvLive.sol";

/// Groth16 verifier interface (snarkjs / circom layout). A real verifier STATICCALLs 0x06, 0x07, 0x08.
interface IGroth16Verifier {
    function verifyProof(uint256[2] calldata a, uint256[2][2] calldata b, uint256[2] calldata c, uint256[5] calldata pub)
        external
        view
        returns (bool);
}

/// Design B: zone privacy pool, relayer-free withdrawal. The pool is tx.sender for every withdrawal.
///
/// Frame layout:
///   0  self_verify  VERIFY flags=3 target=null (the pool)  data=abi.encodeCall(withdraw, (w))
///   1  SENDER       target=recipient  value=DENOMINATION - feeCap  data=empty
///
/// Envelope:
///   nonce_keys = [nullifier], nonce_seq = 0   (EIP-8250: the protocol is the nullifier set)
///   recent_root_references: pool root (POOL_SOURCE) and zone membership root (ZONE_SOURCE)
///   signatures = []                           (nobody signs; the proof binds recipient and fee)
///
/// Validation footprint: no SLOAD at all. Roots come from RECENTROOTREFLOAD, the nullifier from
/// TXPARAM, the payout from FRAMEPARAM. The only external call is the verifier, which has its keys
/// in code. So the storage rules pass even UNSTAKED. What fails today is gas and precompiles:
///   - Groth16 verify is ~242k-263k gas (research/worldid/notes/pool.md, forge-measured) > 100,000.
///   - the verifier's STATICCALLs to 0x06/0x07/0x08 hit sidecar CODE_ACCESS while
///     skandha_config.precompiles == [] (live, 2026-11-01).
abstract contract ZonePoolLogic is FrameEnv {
    struct Withdrawal {
        uint256[2] a;
        uint256[2][2] b;
        uint256[2] c;
        address recipient;
        uint256 feeCap; // wei the note gives up for gas; bound into the proof
        uint256 poolRefIndex;
        uint256 zoneRefIndex;
    }

    uint256 internal constant VERIFY_FRAME = 0;
    uint256 internal constant PAYOUT_FRAME = 1;
    uint256 internal constant FRAME_COUNT = 2;
    bytes32 public constant POOL_SALT = keccak256("enconomy.zone.pool.v1");

    uint256 public immutable DENOMINATION;
    bytes32 public immutable ZONE_SOURCE; // DAO publishes the zone (association set) root here
    IGroth16Verifier public immutable VERIFIER;

    error NotEntryPoint();
    error Layout();
    error WrongSource();
    error BadNonce();
    error BadPayout();
    error FeeTooHigh();
    error BadProof();

    constructor(uint256 denomination, bytes32 zoneSource, IGroth16Verifier verifier) {
        DENOMINATION = denomination;
        ZONE_SOURCE = zoneSource;
        VERIFIER = verifier;
    }

    function poolSource() public view returns (bytes32) {
        return _sourceId(address(this), POOL_SALT);
    }

    function _withdraw(Withdrawal calldata w) internal {
        if (msg.sender != ENTRY_POINT) revert NotEntryPoint();

        // 1. pin the whole frame list: approval covers EVERY later SENDER frame (ERC-8421 security
        //    note), and the pool is the sender, so an extra frame would spend pool money.
        if (_txParam(TX_FRAME_COUNT) != FRAME_COUNT) revert Layout();
        if (_txParam(TX_CURRENT_FRAME) != VERIFY_FRAME) revert Layout();
        if (_frameParam(PAYOUT_FRAME, FP_MODE) != MODE_SENDER) revert BadPayout();
        if (_frameParam(PAYOUT_FRAME, FP_TARGET) != uint256(uint160(w.recipient))) revert BadPayout();
        if (w.feeCap >= DENOMINATION) revert FeeTooHigh();
        if (_frameParam(PAYOUT_FRAME, FP_VALUE) != DENOMINATION - w.feeCap) revert BadPayout();
        if (_frameParam(PAYOUT_FRAME, FP_DATA_LEN) != 0) revert BadPayout();

        // 2. nullifier = the single nonce key at sequence 0. A second spend of the same note is a
        //    conflicting tx (LIFECYCLE-020), never a second inclusion.
        if (_txParam(TX_NONCE_KEY_COUNT) != 1) revert BadNonce();
        if (_txParam(TX_NONCE_SEQ) != 0) revert BadNonce();
        uint256 nullifier = _txParam(TX_NONCE_KEY_0);

        // 3. gas comes out of the note: APPROVE debits max cost from the pool, so cap it by the proof
        if (_txParam(TX_MAX_COST) > w.feeCap) revert FeeTooHigh();

        // 4. roots from the envelope; the protocol already checked age and commitment
        if (bytes32(_recentRoot(w.poolRefIndex, RR_SOURCE_ID)) != poolSource()) revert WrongSource();
        if (bytes32(_recentRoot(w.zoneRefIndex, RR_SOURCE_ID)) != ZONE_SOURCE) revert WrongSource();
        uint256 root = _recentRoot(w.poolRefIndex, RR_ROOT);
        uint256 zoneRoot = _recentRoot(w.zoneRefIndex, RR_ROOT);

        // 5. the proof binds root, zone, nullifier, recipient and fee
        uint256[5] memory pub = [root, zoneRoot, nullifier, uint256(uint160(w.recipient)), w.feeCap];
        if (!VERIFIER.verifyProof(w.a, w.b, w.c, pub)) revert BadProof();

        _approve(SCOPE_EXECUTION_AND_PAYMENT);
    }
}

contract ZonePool is ZonePoolLogic, FrameEnvLive {
    address internal constant RECENT_ROOT_PREDEPLOY = address(0x8272);

    bytes32[] public leaves; // deposit commitments; a real pool keeps an incremental Poseidon tree

    event Deposit(bytes32 commitment, uint256 index);
    event RootPublished(bytes32 root);

    constructor(uint256 denomination, bytes32 zoneSource, IGroth16Verifier verifier)
        ZonePoolLogic(denomination, zoneSource, verifier)
    {}

    /// VERIFY entry. Not `view`: APPROVE runs inside.
    function withdraw(Withdrawal calldata w) external {
        _withdraw(w);
    }

    /// Normal tx (any rules). Zone admission (border fee for outsiders) would sit here.
    function deposit(bytes32 commitment) external payable {
        require(msg.value == DENOMINATION, "denomination");
        leaves.push(commitment);
        emit Deposit(commitment, leaves.length - 1);
    }

    /// Anyone may publish; batching deposits keeps the 127k-gas write rare. Placeholder root: a real
    /// pool publishes its Poseidon tree root.
    function publishRoot() external {
        bytes32 root = keccak256(abi.encode(leaves));
        (bool ok,) = RECENT_ROOT_PREDEPLOY.call(abi.encodePacked(POOL_SALT, root));
        require(ok, "8272 write");
        emit RootPublished(root);
    }

    receive() external payable {}
}
