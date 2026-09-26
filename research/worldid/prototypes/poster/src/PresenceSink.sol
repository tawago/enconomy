// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
/// Presence posting part of PresencePool: permissionless, gated by a P-256 attestation from the PoP server.
contract PresenceSink {
  error BadAttestation();
  error Expired(uint64 expiry);
  error LeafAlreadyPosted(uint256 leaf);
  event PresencePosted(uint256 indexed index, uint256 leaf, uint256 root, bytes32 pairTag);
  address constant P256 = address(0x100);
  uint256 public immutable QX; uint256 public immutable QY;
  mapping(uint256 => bool) public posted;
  uint256 public presenceCount;
  constructor(uint256 qx, uint256 qy) { QX = qx; QY = qy; }
  function digest(uint256 leaf, bytes32 pairTag, uint64 expiry) public view returns (bytes32) {
    return sha256(abi.encodePacked("pop-pool-v1", block.chainid, address(this), leaf, pairTag, expiry));
  }
  function postPresence(uint256 leaf, bytes32 pairTag, uint64 expiry, bytes32 r, bytes32 s) external {
    if (block.timestamp > expiry) revert Expired(expiry);
    if (posted[leaf]) revert LeafAlreadyPosted(leaf);
    (bool ok, bytes memory ret) = P256.staticcall(abi.encode(digest(leaf, pairTag, expiry), r, s, QX, QY));
    if (!ok || ret.length != 32 || abi.decode(ret, (uint256)) != 1) revert BadAttestation();
    posted[leaf] = true;
    emit PresencePosted(presenceCount++, leaf, 0, pairTag); // real pool: _presence._insert(leaf) → root
  }
}
