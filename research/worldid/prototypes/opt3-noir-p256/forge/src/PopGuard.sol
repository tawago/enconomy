// SPDX-License-Identifier: MIT
pragma solidity ^0.8.27;

interface IHonk { function verify(bytes calldata proof, bytes32[] calldata pub) external view returns (bool); }

// Onchain combine of two per-phone proofs (opt3). Public input layout of half.nr:
// [0..3] issuer key, [4] now, [5] scope, [6] context, [7] role, [8] attempt, [9,10] nonce,
// [11] sample_rate, [12] half (u32, two's complement), [13] pair_tag, [14] nullifier
contract PopGuard {
    IHonk public immutable half;
    IHonk public immutable pair;
    bytes32[4] public issuer;
    bytes32 public immutable scope;
    mapping(bytes32 => bool) public used;
    event Presence(bytes32 indexed context, bytes32 pairTag, bytes32 nullA, bytes32 nullB);

    constructor(IHonk h, IHonk p, bytes32[4] memory iss, bytes32 sc) { half = h; pair = p; issuer = iss; scope = sc; }

    function _common(bytes32[] calldata p, bytes32 ctx) internal view {
        for (uint i; i < 4; i++) require(p[i] == issuer[i], "issuer");
        require(uint256(p[4]) <= block.timestamp && uint256(p[4]) + 600 > block.timestamp, "now");
        require(p[5] == scope, "scope");
        require(p[6] == ctx, "ctx");
    }

    function _i32(bytes32 v) internal pure returns (int256) { return int256(int32(uint32(uint256(v)))); }

    function checkHalves(bytes calldata pa, bytes32[] calldata a, bytes calldata pb, bytes32[] calldata b, bytes32 ctx) external {
        _common(a, ctx); _common(b, ctx);
        require(uint256(a[7]) == 0x41 && uint256(b[7]) == 0x42, "roles");
        require(a[8] == b[8] && a[9] == b[9] && a[10] == b[10] && a[13] == b[13], "session");
        // NEAR: -20 < 17150*(hA/srA - hB/srB) < 60
        int256 sa = int256(uint256(a[11])); int256 sb = int256(uint256(b[11]));
        int256 f = 17150 * (_i32(a[12]) * sb - _i32(b[12]) * sa);
        require(f > -20 * sa * sb && f < 60 * sa * sb, "not near");
        require(a[14] != b[14], "same holder");
        require(!used[a[14]] && !used[b[14]], "nullified");
        used[a[14]] = true; used[b[14]] = true;
        require(half.verify(pa, a), "proof A");
        require(half.verify(pb, b), "proof B");
        emit Presence(ctx, a[13], a[14], b[14]);
    }

    // pair.nr layout: [0..3] issuer, [4] now, [5] scope, [6] context, [7,8] nonce, [9] pair_tag, [10] nullA, [11] nullB
    function checkPair(bytes calldata pr, bytes32[] calldata p, bytes32 ctx) external {
        _common(p, ctx);
        require(!used[p[10]] && !used[p[11]], "nullified");
        used[p[10]] = true; used[p[11]] = true;
        require(pair.verify(pr, p), "proof");
        emit Presence(ctx, p[9], p[10], p[11]);
    }
}
