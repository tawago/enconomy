// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
interface ITransferVerifier { function verifyProof(uint[2] calldata, uint[2][2] calldata, uint[2] calldata, uint[8] calldata) external view returns (bool); }
/// Failure-path skeleton of PresencePool.transfer: same check order and named errors the real pool must use.
/// Trees are replaced by root sets so the test can use the one real proof we have (depth-2 trees).
contract PoolGate {
  error NotAttester();
  error InvalidContext(uint256 got, uint256 want);
  error UnknownStateRoot(uint256 root);
  error UnknownPresenceRoot(uint256 root);
  error NullifierAlreadySpent(uint256 nullifierHash);
  error InvalidProof();
  event PresencePosted(uint256 indexed index, uint256 leaf, uint256 root);
  event Transferred(uint256 indexed nullifierHash, uint256 changeCommitment, uint256 payeeCommitment);
  struct TransferProof { uint256[2] pA; uint256[2][2] pB; uint256[2] pC; uint256[8] pubSignals; }
  ITransferVerifier public immutable V; address public immutable ATTESTER; uint256 public immutable CONTEXT;
  mapping(uint256 => bool) public knownState; mapping(uint256 => bool) public knownPresence; mapping(uint256 => bool) public spent;
  uint256 public presenceCount;
  constructor(ITransferVerifier v, address attester, uint256 ctx, uint256 stateRoot) { V = v; ATTESTER = attester; CONTEXT = ctx; knownState[stateRoot] = true; }
  // real pool: _presence._insert(leaf) then push root; here the attester posts the resulting root directly
  function postPresenceRoot(uint256 leaf, uint256 root) external {
    if (msg.sender != ATTESTER) revert NotAttester();
    knownPresence[root] = true; emit PresencePosted(presenceCount++, leaf, root);
  }
  function transfer(TransferProof calldata p) external {
    uint256[8] calldata s = p.pubSignals;
    if (s[7] != CONTEXT) revert InvalidContext(s[7], CONTEXT);
    if (!knownState[s[3]]) revert UnknownStateRoot(s[3]);
    if (!knownPresence[s[5]]) revert UnknownPresenceRoot(s[5]);
    if (spent[s[0]]) revert NullifierAlreadySpent(s[0]);
    if (!V.verifyProof(p.pA, p.pB, p.pC, s)) revert InvalidProof();
    spent[s[0]] = true;
    emit Transferred(s[0], s[1], s[2]);
  }
}
