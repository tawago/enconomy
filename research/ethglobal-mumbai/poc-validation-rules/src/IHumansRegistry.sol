// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// What ChirpGasSponsor reads inside VERIFY. Keyed by DEVICE address (keccak(qx||qy)[12:]), never by
/// account address: a mapping keyed by the sender would be sender-associated and readable unstaked,
/// which would hide the stake-gated step. These reads are foreign, read-only (ERC-8421 STORAGE-032),
/// so the paying entity must be staked.
interface IHumansRegistry {
    /// World ID nullifier hash of the human that owns `device`, or 0.
    function humanOf(address device) external view returns (bytes32);

    /// The one sender account the registry bound to `device`, or 0. Quota is a keyed nonce, and keyed
    /// nonces are per sender, so without this a human could open N accounts on one device and get N quotas.
    function accountOf(address device) external view returns (address);
}
