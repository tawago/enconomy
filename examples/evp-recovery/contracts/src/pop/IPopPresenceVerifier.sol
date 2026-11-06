// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// Copied from contracts/src/interfaces and adapted for the EVP start: the account computes popNonce and passes
/// the device Xs it expects, so the verifier checks them instead of reporting them. Runs inside a VERIFY frame.
/// Returns its own selector so solc decodes return data instead of emitting EXTCODESIZE, and a target with no
/// code fails on the empty return.
interface IPopPresenceVerifier {
    /// Must revert unless `presence` proves a session bound to popNonce between these two devices.
    /// @param popNonce  PopCtx.nonce(chainid, account, ctx, notBefore, sid)
    /// @param deviceA   P-256 X of role A, the preregistered laptop
    /// @param deviceB   P-256 X of role B, the new phone
    /// @param qx,qy     PoP credential issuer pinned in configHash
    /// @param deadline  frame 0's expiry. Stands in for block.timestamp, see EvpNoirPresenceVerifier
    function verifyPresence(
        bytes32 popNonce,
        uint256 deviceA,
        uint256 deviceB,
        uint256 qx,
        uint256 qy,
        uint64 notBefore,
        uint256 deadline,
        bytes calldata presence
    ) external view returns (bytes4);
}

/// bb-generated UltraHonk verifier (`bb write_solidity_verifier -t evm`).
interface IHonkVerifier {
    function verify(bytes calldata proof, bytes32[] calldata publicInputs) external view returns (bool);
}
