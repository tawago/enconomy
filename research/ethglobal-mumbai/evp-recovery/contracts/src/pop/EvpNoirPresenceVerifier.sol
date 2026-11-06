// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IPopPresenceVerifier, IHonkVerifier} from "./IPopPresenceVerifier.sol";
import {PopCtx} from "./PopCtx.sol";
import {PopAttest} from "./PopAttest.sol";

/// contracts/src/verifiers/NoirPresenceVerifier.sol adapted for a VERIFY frame. Three proofs per session:
///
///   phone proof (role A and role B, 12 public inputs), unchanged:
///     0 nonce_hi  1 nonce_lo  2 attempt  3 role_b  4 code_commit  5..8 issuer (X hi128, X lo128, Y hi128, Y lo128)
///     9 sr  10 valid_at  11 halfCommit
///   pair proof, NEW interface, 11 public inputs. The existing 7 plus the circuit's xa and xb made public:
///     0 nonce_hi  1 nonce_lo  2 attempt  3 commit_a  4 commit_b  5 sr_a  6 sr_b  7 xa_hi  8 xa_lo  9 xb_hi  10 xb_lo
///
/// NO VERIFIER FOR THAT PAIR INTERFACE EXISTS YET. noir/pair keeps xa and xb private and is frozen, so this
/// contract has only run against mock IHonkVerifiers.
///
/// Why xa and xb are the signing keys: oalib check_signed verifies the transcript signature with X = t[40..72]
/// and takes x_own from those same bytes. phone_core hashes x_own and x_partner into halfCommit under TAG_HALF.
/// The checks below tie halfCommit to commit_a / commit_b, which the pair proof opens with (xa, xb) and (xb, xa).
///
/// Time: TIMESTAMP is a banned opcode in the prefix (sidecar frameTx.ts), so the valid_at window hangs off frame
/// 0's deadline, which the expiry predeploy holds against the clock: now <= deadline <= valid_at + maxAge gives
/// the old `now <= valid_at + maxAge`. The future side weakens from now + CLOCK_SKEW to deadline + CLOCK_SKEW.
/// maxAge must cover deadline - valid_at for an honest run. The page sets the deadline on the laptop's clock and the
/// server sets valid_at on its own, so use at least the 900 s attempt window + CLOCK_SKEW = 1200. Raising it costs
/// little: the prover picks valid_at anyway, inside notBefore and deadline + CLOCK_SKEW.
contract EvpNoirPresenceVerifier is IPopPresenceVerifier {
    struct Bundle {
        bytes proofA;
        bytes32[] pubA;
        bytes proofB;
        bytes32[] pubB;
        bytes proofPair;
        bytes32[] pubPair;
        bytes ccSigA; // POPCC1 r||s (64 B) over pubA's code_commit
        bytes ccSigB; // POPCC1 r||s (64 B) over pubB's code_commit
    }

    uint256 public constant N_PHONE = 12;
    uint256 public constant N_PAIR = 11;
    uint256 public constant CLOCK_SKEW = 300; // s, valid_at may be this far past the deadline

    IHonkVerifier public immutable phoneVerifier;
    IHonkVerifier public immutable pairVerifier;
    uint64 public immutable maxAge; // s, deadline <= valid_at + maxAge

    // 0 = lengths, 1 = nonce, 2 = attempt, 3 = role, 4 = issuer, 5 = sr, 6 = halfCommit, 7 = device A, 8 = device B
    error BadPublicInputs(uint256 which);
    error Stale();
    error ProofRejected(uint256 which); // 0 = A, 1 = B, 2 = pair
    error BadCodeAttest(uint256 which); // POPCC1 sig invalid: 0 = A, 1 = B

    constructor(IHonkVerifier phone, IHonkVerifier pair, uint64 maxAge_) {
        phoneVerifier = phone;
        pairVerifier = pair;
        maxAge = maxAge_;
    }

    function verifyPresence(
        bytes32 popNonce,
        uint256 deviceA,
        uint256 deviceB,
        uint256 qx,
        uint256 qy,
        uint64 notBefore,
        uint256 deadline,
        bytes calldata presence
    ) external view returns (bytes4) {
        Bundle memory b = abi.decode(presence, (Bundle));
        bytes32[] memory a = b.pubA;
        bytes32[] memory bb = b.pubB;
        bytes32[] memory p = b.pubPair;
        if (a.length != N_PHONE || bb.length != N_PHONE || p.length != N_PAIR) revert BadPublicInputs(0);

        (bytes32 hi, bytes32 lo) = PopCtx.split(popNonce);
        if (a[0] != hi || a[1] != lo || bb[0] != hi || bb[1] != lo || p[0] != hi || p[1] != lo) {
            revert BadPublicInputs(1);
        }
        if (a[2] != p[2] || bb[2] != p[2]) revert BadPublicInputs(2);
        if (uint256(a[3]) != 0 || uint256(bb[3]) != 1) revert BadPublicInputs(3);
        if (!_issuerOk(a, qx, qy) || !_issuerOk(bb, qx, qy)) revert BadPublicInputs(4);
        if (a[9] != p[5] || bb[9] != p[6]) revert BadPublicInputs(5);
        if (a[11] != p[3] || bb[11] != p[4]) revert BadPublicInputs(6);

        (hi, lo) = PopCtx.split(bytes32(deviceA));
        if (p[7] != hi || p[8] != lo) revert BadPublicInputs(7);
        (hi, lo) = PopCtx.split(bytes32(deviceB));
        if (p[9] != hi || p[10] != lo) revert BadPublicInputs(8);

        if (!_ccOk(popNonce, a, "A", b.ccSigA, qx, qy)) revert BadCodeAttest(0);
        if (!_ccOk(popNonce, bb, "B", b.ccSigB, qx, qy)) revert BadCodeAttest(1);

        uint256 validAt = uint256(a[10]);
        if (bb[10] != a[10] || validAt < notBefore || validAt > deadline + CLOCK_SKEW || deadline > validAt + maxAge) {
            revert Stale();
        }

        if (!phoneVerifier.verify(b.proofA, a)) revert ProofRejected(0);
        if (!phoneVerifier.verify(b.proofB, bb)) revert ProofRejected(1);
        if (!pairVerifier.verify(b.proofPair, p)) revert ProofRejected(2);
        return IPopPresenceVerifier.verifyPresence.selector;
    }

    /// POPCC1: sha256("POPCC1" || nonce || u8 attempt || 'A'|'B' || code_commit), P-256 by the pinned issuer.
    function _ccOk(bytes32 nonce, bytes32[] memory v, bytes1 role, bytes memory sig, uint256 qx, uint256 qy)
        private
        view
        returns (bool)
    {
        if (sig.length != 64 || uint256(v[2]) > type(uint8).max) return false;
        bytes32 r;
        bytes32 s;
        assembly ("memory-safe") {
            r := mload(add(sig, 32))
            s := mload(add(sig, 64))
        }
        bytes32 h = sha256(abi.encodePacked("POPCC1", nonce, uint8(uint256(v[2])), role, v[4]));
        return PopAttest.p256(h, r, s, qx, qy);
    }

    function _issuerOk(bytes32[] memory v, uint256 qx, uint256 qy) private pure returns (bool) {
        return uint256(v[5]) == qx >> 128 && uint256(v[6]) == uint128(qx) && uint256(v[7]) == qy >> 128
            && uint256(v[8]) == uint128(qy);
    }
}
