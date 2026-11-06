// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// Publishes the humans Merkle root to the EIP-8272 recent-root predeploy.
///
/// Runs in normal transactions, never in VERIFY, so TIMESTAMP / PREVRANDAO and any gas are fine here.
/// Registration itself (World ID proof, one leaf per nullifier hash) is off-chain or in a separate
/// contract; this sketch keeps an operator. On the alt-mempool devnet there is no World ID verifier:
/// the v4 WorldIDVerifier is on World Chain 480 only (research/worldid/notes/pool.md).
///
/// Cost: one write measured at 127,256 gas in ethrex (docs/eip-8272.md). A root written in slot S is
/// referenceable from S+1 until S+8191 (13.65 h at the devnet's 6 s slots).
contract HumansRegistry {
    address internal constant RECENT_ROOT = address(0x8272);
    bytes32 public constant SALT = keccak256("enconomy.humans.v1");

    address public immutable operator;

    event Published(bytes32 treeRoot, bytes32 beaconSalt, bytes32 value);

    error NotOperator();
    error WriteFailed();

    constructor(address operator_) {
        operator = operator_;
    }

    /// EIP-8272 source_id for this registry; HumansOnlySponsor pins it.
    function sourceId() external view returns (bytes32) {
        return keccak256(abi.encodePacked(address(this), SALT));
    }

    function publish(bytes32 treeRoot) external {
        if (msg.sender != operator) revert NotOperator();
        // unpredictable before this block, so an attestation signed over `value` was made after it
        bytes32 beaconSalt = keccak256(abi.encode(treeRoot, block.prevrandao, block.number));
        bytes32 value = keccak256(abi.encode(treeRoot, beaconSalt));
        // predeploy calldata: exactly 64 bytes, salt || root, zero value
        (bool ok,) = RECENT_ROOT.call(abi.encodePacked(SALT, value));
        if (!ok) revert WriteFailed();
        emit Published(treeRoot, beaconSalt, value);
    }
}
