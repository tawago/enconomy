// SPDX-License-Identifier: MIT
pragma solidity ^0.8.27;

interface IHonkVerifier {
    function verify(bytes calldata proof, bytes32[] calldata publicInputs) external view returns (bool);
}

/// Calls a Honk verifier inside a tx so the result lands on-chain as an event.
contract VerifyLog {
    event Verified(address indexed verifier, bytes32 indexed proofHash, bytes32 publicInputsHash, bool ok, uint256 gasUsed);

    function verifyAndLog(address verifier, bytes calldata proof, bytes32[] calldata publicInputs) external returns (bool ok) {
        uint256 g = gasleft();
        ok = IHonkVerifier(verifier).verify(proof, publicInputs);
        uint256 used = g - gasleft();
        emit Verified(verifier, keccak256(proof), keccak256(abi.encodePacked(publicInputs)), ok, used);
    }
}
