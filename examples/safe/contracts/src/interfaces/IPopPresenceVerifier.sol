// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// Pluggable presence check for PopSafeGuard. One verifier per guard (immutable).
/// Must revert (with its own error) unless `presence` proves that two phones were physically together
/// in a PoP session bound to (block.chainid, safe, safeTxHash).
interface IPopPresenceVerifier {
    /// @param safe       the Safe (PopCtx consumer)
    /// @param safeTxHash the exact Safe tx being executed (PopCtx ctxHash)
    /// @param qx,qy      the Safe's PoP server key (per Safe in the guard, rotatable through the hatch)
    /// @param presence   verifier-specific bytes (POP2 tail, or the Noir proof bundle)
    /// @return devA sha256(pubkey65) of phone A, or 0 if this proof system does not reveal devices
    /// @return devB same for phone B. (0, 0) = the guard requires two device-owning signers instead.
    function verifyPresence(address safe, bytes32 safeTxHash, uint256 qx, uint256 qy, bytes calldata presence)
        external
        view
        returns (bytes32 devA, bytes32 devB);
}

/// bb-generated UltraHonk verifier (`bb write_solidity_verifier -t evm`).
interface IHonkVerifier {
    function verify(bytes calldata proof, bytes32[] calldata publicInputs) external view returns (bool);
}
