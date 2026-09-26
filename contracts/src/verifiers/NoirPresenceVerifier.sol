// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IPopPresenceVerifier, IHonkVerifier} from "../interfaces/IPopPresenceVerifier.sol";
import {PopCtx} from "../lib/PopCtx.sol";

/// Presence = Noir "option A" proofs, verified onchain by the bb UltraHonk verifiers (`verify(bytes, bytes32[])`).
/// Three proofs per session (enconomy-zk zkmobile/APP_SERVER_CONTRACT.md, noir/phone oaN_s48 + noir/pair):
///
///   phone proof (role A and role B, PhoneVerifier, 12 public inputs):
///     0 nonce_hi  1 nonce_lo  2 attempt  3 role_b  4 code_commit  5..8 issuer (X hi128, X lo128, Y hi128, Y lo128)
///     9 sr  10 valid_at  11 halfCommit
///   pair proof (PairVerifier, 7 public inputs; proves NEAR and xa != xb from the two private halves):
///     0 nonce_hi  1 nonce_lo  2 attempt  3 commit_a  4 commit_b  5 sr_a  6 sr_b
///
/// Onchain linking: nonce = PopCtx.nonce(chainid, safe, safeTxHash, notBefore, sid) split hi/lo in all three;
/// same attempt; role_b 0/1; issuer = the Safe's pinned P-256 key (the SBcred3 issuer); phone sr/halfCommit
/// = pair sr_x/commit_x; valid_at equal in A and B and fresh.
///
/// presence = abi.encode(Bundle).
///
/// TODO(zk lane):
///  - The circuits expose no device key, device hash, pairTag or nullifier, so this returns (0, 0): the guard can
///    only require two device-owning signers, not that the *proving* phones are those owners' phones, and human
///    uniqueness (nA != nB) stays a server claim. Ask for sha256(pub65) or X hi/lo of both devices as pair
///    public inputs; then return (devA, devB) here and the guard binds devices exactly like the POP2 path.
///  - code_commit (#4) is free onchain; the server vouches for it off chain (POPCC1). Optional: verify POPCC1 here.
///  - Pin final PhoneVerifier / PairVerifier (vk sha256) when the server produces the pair proof.
contract NoirPresenceVerifier is IPopPresenceVerifier {
    struct Bundle {
        uint64 notBefore; // PopCtx notBefore (server created_ms / 1000)
        bytes16 sid; // PopCtx sid (session id bytes)
        bytes proofA;
        bytes32[] pubA;
        bytes proofB;
        bytes32[] pubB;
        bytes proofPair;
        bytes32[] pubPair;
    }

    uint256 public constant N_PHONE = 12;
    uint256 public constant N_PAIR = 7;
    uint256 public constant CLOCK_SKEW = 300; // s, valid_at may be this far ahead of block.timestamp

    IHonkVerifier public immutable phoneVerifier;
    IHonkVerifier public immutable pairVerifier;
    uint64 public immutable maxAge; // s, block.timestamp <= valid_at + maxAge

    error BadPublicInputs(uint256 which); // 0 = lengths, 1 = nonce, 2 = attempt, 3 = role, 4 = issuer, 5 = sr, 6 = halfCommit
    error Stale();
    error ProofRejected(uint256 which); // 0 = A, 1 = B, 2 = pair

    constructor(IHonkVerifier phone, IHonkVerifier pair, uint64 maxAge_) {
        phoneVerifier = phone;
        pairVerifier = pair;
        maxAge = maxAge_;
    }

    function verifyPresence(address safe, bytes32 safeTxHash, uint256 qx, uint256 qy, bytes calldata presence)
        external
        view
        returns (bytes32, bytes32)
    {
        Bundle memory b = abi.decode(presence, (Bundle));
        _verify(_nonce(safe, safeTxHash, b), qx, qy, b);
        return (bytes32(0), bytes32(0));
    }

    function _nonce(address safe, bytes32 safeTxHash, Bundle memory b) internal view virtual returns (bytes32) {
        return PopCtx.nonce(block.chainid, safe, safeTxHash, b.notBefore, b.sid);
    }

    function _verify(bytes32 nonce, uint256 qx, uint256 qy, Bundle memory b) internal view {
        bytes32[] memory a = b.pubA;
        bytes32[] memory bb = b.pubB;
        bytes32[] memory p = b.pubPair;
        if (a.length != N_PHONE || bb.length != N_PHONE || p.length != N_PAIR) revert BadPublicInputs(0);

        (bytes32 hi, bytes32 lo) = PopCtx.split(nonce);
        if (a[0] != hi || a[1] != lo || bb[0] != hi || bb[1] != lo || p[0] != hi || p[1] != lo) {
            revert BadPublicInputs(1);
        }
        if (a[2] != p[2] || bb[2] != p[2]) revert BadPublicInputs(2);
        if (uint256(a[3]) != 0 || uint256(bb[3]) != 1) revert BadPublicInputs(3);
        if (!_issuerOk(a, qx, qy) || !_issuerOk(bb, qx, qy)) revert BadPublicInputs(4);
        if (a[9] != p[5] || bb[9] != p[6]) revert BadPublicInputs(5);
        if (a[11] != p[3] || bb[11] != p[4]) revert BadPublicInputs(6);

        uint256 validAt = uint256(a[10]);
        if (
            bb[10] != a[10] || validAt < b.notBefore || validAt > block.timestamp + CLOCK_SKEW
                || block.timestamp > validAt + maxAge
        ) revert Stale();

        if (!phoneVerifier.verify(b.proofA, a)) revert ProofRejected(0);
        if (!phoneVerifier.verify(b.proofB, bb)) revert ProofRejected(1);
        if (!pairVerifier.verify(b.proofPair, p)) revert ProofRejected(2);
    }

    function _issuerOk(bytes32[] memory v, uint256 qx, uint256 qy) internal pure returns (bool) {
        return uint256(v[5]) == qx >> 128 && uint256(v[6]) == uint128(qx) && uint256(v[7]) == qy >> 128
            && uint256(v[8]) == uint128(qy);
    }
}
