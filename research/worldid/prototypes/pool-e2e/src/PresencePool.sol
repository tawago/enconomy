// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;

// Presence-gated fork of 0xbow privacy-pools-core (State.sol + PrivacyPool.sol + PrivacyPoolSimple, commit d494b63).
// Changes vs 0xbow:
//  - no Entrypoint: deposit is direct, fixed DENOM, the label is auto-inserted into an onchain ASP LeanIMT
//  - withdraw accepts any ASP root in a 64-entry history (0xbow: == Entrypoint.latestRoot())
//  - new presence LeanIMT written by ATTESTER (postPresence), new transfer() gated by a PresenceTransfer proof
// Unchanged: SCOPE formula, label formula, commitment formula, withdraw context formula, ProofLib signal order,
// WithdrawalVerifier/CommitmentVerifier (production 0xbow ceremony keys).

import {InternalLeanIMT, LeanIMTData} from './lib/InternalLeanIMT.sol';
import {PoseidonT4} from './lib/PoseidonT4.sol';

interface IVerifier8 {
  function verifyProof(uint256[2] calldata, uint256[2][2] calldata, uint256[2] calldata, uint256[8] calldata)
    external view returns (bool);
}

interface IVerifier4 {
  function verifyProof(uint256[2] calldata, uint256[2][2] calldata, uint256[2] calldata, uint256[4] calldata)
    external view returns (bool);
}

contract PresencePool {
  using InternalLeanIMT for LeanIMTData;

  uint256 internal constant P = 21_888_242_871_839_275_222_246_405_745_257_275_088_548_364_400_416_034_343_698_204_186_575_808_495_617;
  address internal constant NATIVE_ASSET = 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE;
  uint32 public constant ROOT_HISTORY_SIZE = 64;
  uint32 public constant MAX_TREE_DEPTH = 32;
  uint32 public constant MAX_PRESENCE_DEPTH = 20;
  uint256 public constant LABEL_TRANSFER = 0x706f702d7472616e73666572; // "pop-transfer"

  // same structs/encodings as 0xbow IPrivacyPool / ProofLib
  struct Withdrawal {
    address processooor;
    bytes data; // empty, or abi.encode(address recipient, address feeRecipient, uint256 feeBPS)
  }

  struct WithdrawProof { // pub: [newCommitment, existingNullifierHash, withdrawnValue, stateRoot, stateDepth, ASPRoot, ASPDepth, context]
    uint256[2] pA;
    uint256[2][2] pB;
    uint256[2] pC;
    uint256[8] pubSignals;
  }

  struct RagequitProof { // pub: [commitment, nullifierHash, value, label]
    uint256[2] pA;
    uint256[2][2] pB;
    uint256[2] pC;
    uint256[4] pubSignals;
  }

  struct TransferProof { // pub: [existingNullifierHash, changeCommitment, payeeCommitment, stateRoot, stateDepth, presenceRoot, presenceDepth, context]
    uint256[2] pA;
    uint256[2][2] pB;
    uint256[2] pC;
    uint256[8] pubSignals;
  }

  uint256 public immutable SCOPE;
  uint256 public immutable DENOM;
  uint256 public immutable TRANSFER_CONTEXT;
  address public immutable ATTESTER;
  IVerifier8 public immutable WITHDRAWAL_VERIFIER;
  IVerifier4 public immutable RAGEQUIT_VERIFIER;
  IVerifier8 public immutable TRANSFER_VERIFIER;

  uint256 public nonce;
  mapping(uint256 => bool) public nullifierHashes;
  mapping(uint256 => address) public depositors;

  // state tree (0xbow State.sol)
  LeanIMTData internal _state;
  mapping(uint256 => uint256) public roots;
  uint32 public currentRootIndex;
  // ASP tree (labels), onchain, auto-approve
  LeanIMTData internal _asp;
  mapping(uint256 => uint256) public aspRoots;
  uint32 public currentAspRootIndex;
  // presence tree
  LeanIMTData internal _presence;
  mapping(uint256 => uint256) public presenceRoots;
  uint32 public currentPresenceRootIndex;

  event LeafInserted(uint256 _index, uint256 _leaf, uint256 _root); // 0xbow IState event, same signature
  event ASPLeafInserted(uint256 _index, uint256 _label, uint256 _root);
  event PresencePosted(uint256 indexed index, uint256 leaf, uint256 root);
  event Deposited(address indexed _depositor, uint256 _commitment, uint256 _label, uint256 _value, uint256 _precommitmentHash);
  event Transferred(uint256 _nullifierHash, uint256 _changeCommitment, uint256 _payeeCommitment);
  event Withdrawn(address indexed _processooor, uint256 _value, uint256 _spentNullifier, uint256 _newCommitment);
  event Ragequit(address indexed _ragequitter, uint256 _commitment, uint256 _label, uint256 _value);

  error OnlyAttester();
  error WrongValue();
  error InvalidProcessooor();
  error ContextMismatch();
  error InvalidTreeDepth();
  error UnknownStateRoot();
  error UnknownASPRoot();
  error UnknownPresenceRoot();
  error InvalidProof();
  error NullifierAlreadySpent();
  error OnlyOriginalDepositor();
  error InvalidCommitment();
  error MaxTreeDepthReached();
  error PushFailed();

  constructor(uint256 denom, address attester, address withdrawalVerifier, address ragequitVerifier, address transferVerifier) {
    DENOM = denom;
    ATTESTER = attester;
    WITHDRAWAL_VERIFIER = IVerifier8(withdrawalVerifier);
    RAGEQUIT_VERIFIER = IVerifier4(ragequitVerifier);
    TRANSFER_VERIFIER = IVerifier8(transferVerifier);
    // identical to 0xbow State.sol with ASSET = NATIVE_ASSET
    SCOPE = uint256(keccak256(abi.encodePacked(address(this), block.chainid, NATIVE_ASSET))) % P;
    TRANSFER_CONTEXT = uint256(keccak256(abi.encode('pop-transfer-v1', SCOPE))) % P;
    _aspInsert(LABEL_TRANSFER); // payee notes carry this label; must be in ASP for the unchanged withdraw circuit
  }

  // ---------------------------------------------------------------- views
  function currentRoot() external view returns (uint256) { return _state._root(); }
  function currentTreeDepth() external view returns (uint256) { return _state.depth; }
  function currentTreeSize() external view returns (uint256) { return _state.size; }
  function aspRoot() external view returns (uint256) { return _asp._root(); }
  function aspDepth() external view returns (uint256) { return _asp.depth; }
  function presenceRoot() external view returns (uint256) { return _presence._root(); }
  function presenceDepth() external view returns (uint256) { return _presence.depth; }

  // ---------------------------------------------------------------- user methods
  function deposit(uint256 precommitment) external payable returns (uint256 commitment) {
    if (msg.value != DENOM) revert WrongValue();
    uint256 label = uint256(keccak256(abi.encodePacked(SCOPE, ++nonce))) % P; // 0xbow formula
    depositors[label] = msg.sender;
    commitment = PoseidonT4.hash([msg.value, label, precommitment]);
    _insert(commitment);
    _aspInsert(label);
    emit Deposited(msg.sender, commitment, label, msg.value, precommitment);
  }

  function postPresence(uint256 leaf) external {
    if (msg.sender != ATTESTER) revert OnlyAttester();
    uint256 root = _presence._insert(leaf); // reverts LeafAlreadyExists / LeafCannotBeZero / >= P
    if (_presence.depth > MAX_PRESENCE_DEPTH) revert MaxTreeDepthReached();
    uint32 i = (currentPresenceRootIndex + 1) % ROOT_HISTORY_SIZE;
    presenceRoots[i] = root;
    currentPresenceRootIndex = i;
    emit PresencePosted(_presence.size, leaf, root);
  }

  function transfer(TransferProof calldata p) external {
    uint256[8] calldata s = p.pubSignals;
    if (s[7] != TRANSFER_CONTEXT) revert ContextMismatch();
    if (s[4] > MAX_TREE_DEPTH || s[6] > MAX_PRESENCE_DEPTH) revert InvalidTreeDepth();
    if (!_known(roots, currentRootIndex, s[3])) revert UnknownStateRoot();
    if (!_known(presenceRoots, currentPresenceRootIndex, s[5])) revert UnknownPresenceRoot();
    if (!TRANSFER_VERIFIER.verifyProof(p.pA, p.pB, p.pC, s)) revert InvalidProof();
    _spend(s[0]);
    _insert(s[1]); // change first
    _insert(s[2]); // then payee
    emit Transferred(s[0], s[1], s[2]);
  }

  function withdraw(Withdrawal calldata w, WithdrawProof calldata p) external {
    uint256[8] calldata s = p.pubSignals;
    if (msg.sender != w.processooor) revert InvalidProcessooor();
    if (s[7] != uint256(keccak256(abi.encode(w, SCOPE))) % P) revert ContextMismatch(); // 0xbow formula
    if (s[4] > MAX_TREE_DEPTH || s[6] > MAX_TREE_DEPTH) revert InvalidTreeDepth();
    if (!_known(roots, currentRootIndex, s[3])) revert UnknownStateRoot();
    if (!_known(aspRoots, currentAspRootIndex, s[5])) revert UnknownASPRoot(); // the one semantic change
    if (!WITHDRAWAL_VERIFIER.verifyProof(p.pA, p.pB, p.pC, s)) revert InvalidProof();
    _spend(s[1]);
    _insert(s[0]);
    uint256 v = s[2];
    if (w.data.length == 0) {
      _push(w.processooor, v);
    } else {
      (address recipient, address feeRecipient, uint256 feeBPS) = abi.decode(w.data, (address, address, uint256));
      uint256 fee = v * feeBPS / 10_000;
      _push(recipient, v - fee);
      if (fee > 0) _push(feeRecipient, fee);
    }
    emit Withdrawn(w.processooor, v, s[1], s[0]);
  }

  function ragequit(RagequitProof calldata p) external {
    uint256 label = p.pubSignals[3];
    if (depositors[label] != msg.sender) revert OnlyOriginalDepositor();
    if (!RAGEQUIT_VERIFIER.verifyProof(p.pA, p.pB, p.pC, p.pubSignals)) revert InvalidProof();
    if (!_state._has(p.pubSignals[0])) revert InvalidCommitment();
    _spend(p.pubSignals[1]);
    _push(msg.sender, p.pubSignals[2]);
    emit Ragequit(msg.sender, p.pubSignals[0], label, p.pubSignals[2]);
  }

  // ---------------------------------------------------------------- internals
  function _spend(uint256 nh) internal {
    if (nullifierHashes[nh]) revert NullifierAlreadySpent();
    nullifierHashes[nh] = true;
  }

  function _insert(uint256 leaf) internal {
    uint256 root = _state._insert(leaf);
    if (_state.depth > MAX_TREE_DEPTH) revert MaxTreeDepthReached();
    uint32 i = (currentRootIndex + 1) % ROOT_HISTORY_SIZE;
    roots[i] = root;
    currentRootIndex = i;
    emit LeafInserted(_state.size, leaf, root);
  }

  function _aspInsert(uint256 label) internal {
    uint256 root = _asp._insert(label);
    uint32 i = (currentAspRootIndex + 1) % ROOT_HISTORY_SIZE;
    aspRoots[i] = root;
    currentAspRootIndex = i;
    emit ASPLeafInserted(_asp.size, label, root);
  }

  function _known(mapping(uint256 => uint256) storage hist, uint32 cur, uint256 r) internal view returns (bool) {
    if (r == 0) return false;
    uint32 idx = cur;
    for (uint32 k = 0; k < ROOT_HISTORY_SIZE; k++) {
      if (r == hist[idx]) return true;
      idx = (idx + ROOT_HISTORY_SIZE - 1) % ROOT_HISTORY_SIZE;
    }
    return false;
  }

  function _push(address to, uint256 v) internal {
    (bool ok,) = to.call{value: v}('');
    if (!ok) revert PushFailed();
  }
}
