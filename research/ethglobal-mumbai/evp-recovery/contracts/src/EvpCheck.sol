// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// EVP token check (EVT~KB-JWT, both ES256), for the body frame of the start tx.
/// Copied from poc-evp-issuer/src/EvpVerifier.sol and changed per DESIGN.md section 4.1 / 6:
///   - config comes from calldata (the account checks keccak(abi.encode(cfg)) == configHash), not immutables
///   - KB nonce must be "0x" + lowercase hex(ctx), was hex(keccak(newKey))
///   - aud: keccak of the bare origin string (cfg.audHash), length from offs field 15, closing quote checked
///   - iat window [now - 900, now + 60] on both iats; 900 = the 15 min deadline
///   - EVT header is no longer pinned by hash (Config is DESIGN's four fields). The issuer key is ours and
///     only signs EVTs, and 0x100 fixes the curve. typ is unchecked, as before for the KB header.
/// Precompiles 0x100 and 0x02: fine in a SENDER frame. In VERIFY only on our own sidecar (public one: CODE_ACCESS).
///
/// offs: 16 x uint16, field i at bits [16i, 16i+16):
///  0 d1   first '.' of EVT        1 d2  second '.' of EVT     2 t  '~'
///  3 k1   first '.' of KB-JWT     4 k2  second '.' of KB-JWT
///  EVT payload (decoded JSON) positions of the opening quote:
///  5 "email":"   6 email length   7 "email_verified":true   8 "iat":
///  9 "x":"      10 "y":"   (inside cnf.jwk)
///  KB payload: 11 "aud":"   12 "nonce":"   13 "iat":   14 "sd_hash":"   15 aud length (bytes)
///
/// High-s: accepted on purpose. EIP-7951 does not require low-s and WebCrypto/Chrome do not normalize, so
/// about half of real KB signatures are high-s. Malleating s gives a new token string with the same claims;
/// that buys nothing because the nonce is ctx, and ctx carries recoveryNonce, which the start bumps.
abstract contract EvpCheck {
    address constant P256VERIFY = address(0x100); // EIP-7951
    uint256 public constant MAX_AGE = 900;
    uint256 public constant FUTURE_SKEW = 60;

    struct Config {
        uint256 issuerX;
        uint256 issuerY;
        bytes32 emailHash; // keccak(email bytes, exactly as the issuer echoes them)
        bytes32 audHash; // keccak(origin), e.g. keccak("https://recover.tawago.com")
        uint256 popIssuerX; // PoP credential issuer. Phone proofs and POPCC1 are checked against it in VERIFY
        uint256 popIssuerY;
        address presenceVerifier; // IPopPresenceVerifier, called in VERIFY
    }

    error BadHint(uint256 field);
    error BadSig(uint256 which);
    error BadClaim(uint256 field);
    error Stale();
    error BadB64();

    function _f(uint256 offs, uint256 i) internal pure returns (uint256) {
        return (offs >> (16 * i)) & 0xffff;
    }

    /// Reverts on any failure. cfg must already be checked against configHash by the caller.
    function _checkEvp(bytes calldata token, uint256 offs, Config calldata cfg, bytes32 ctx) internal view {
        bytes memory tok = token;
        uint256 d1 = _f(offs, 0);
        uint256 d2 = _f(offs, 1);
        uint256 t = _f(offs, 2);
        uint256 k1 = _f(offs, 3);
        uint256 k2 = _f(offs, 4);
        if (!(d1 < d2 && d2 < t && t < k1 && k1 < k2 && k2 < tok.length)) revert BadHint(5);
        if (tok[d1] != ".") revert BadHint(0);
        if (tok[d2] != ".") revert BadHint(1);
        if (tok[t] != "~") revert BadHint(2);
        if (tok[k1] != ".") revert BadHint(3);
        if (tok[k2] != ".") revert BadHint(4);

        // 1. Issuer signature over b64(h).b64(p), key from the pinned config
        {
            (uint256 r, uint256 s) = _sig(tok, d2 + 1, t);
            if (!_p256(_sha256Slice(tok, 0, d2), r, s, cfg.issuerX, cfg.issuerY)) revert BadSig(0);
        }

        // 2. EVT claims
        uint256 bx;
        uint256 by;
        {
            bytes memory ep = _decode(tok, d1 + 1, d2);
            uint256 o = _f(offs, 5);
            uint256 n = _f(offs, 6);
            _expect(ep, o, '"email":"', 9, 5);
            if (_hashSlice(ep, o + 9, o + 9 + n) != cfg.emailHash) revert BadClaim(5);
            if (o + 9 + n >= ep.length || ep[o + 9 + n] != '"') revert BadClaim(6);
            _expect(ep, _f(offs, 7), '"email_verified":true', 21, 7);
            _fresh(ep, _f(offs, 8), 8);
            bx = _b64Word(ep, _f(offs, 9), '"x":"', 9);
            by = _b64Word(ep, _f(offs, 10), '"y":"', 10);
        }

        // 3. KB-JWT signature with the cnf.jwk key (this binds the KB-JWT to the EVT)
        {
            (uint256 r, uint256 s) = _sig(tok, k2 + 1, tok.length);
            if (!_p256(_sha256Slice(tok, t + 1, k2), r, s, bx, by)) revert BadSig(1);
        }

        // 4. KB claims
        bytes memory kp = _decode(tok, k1 + 1, k2);
        {
            uint256 o = _f(offs, 11);
            uint256 n = _f(offs, 15);
            _expect(kp, o, '"aud":"', 7, 11);
            if (_hashSlice(kp, o + 7, o + 7 + n) != cfg.audHash) revert BadClaim(11);
            if (o + 7 + n >= kp.length || kp[o + 7 + n] != '"') revert BadClaim(15);
        }
        _nonce(kp, _f(offs, 12), ctx);
        _fresh(kp, _f(offs, 13), 13);
        // sd_hash = b64url(sha256(EVT + "~")) binds this KB-JWT to this EVT
        if (_b64Word(kp, _f(offs, 14), '"sd_hash":"', 14) != uint256(_sha256Slice(tok, 0, t + 1))) {
            revert BadClaim(14);
        }
    }

    // ---------- claim helpers ----------

    /// bytes at p[o..o+n) == lit (n <= 32)
    function _expect(bytes memory p, uint256 o, bytes32 lit, uint256 n, uint256 field) internal pure {
        if (o + n > p.length) revert BadClaim(field);
        bytes32 w;
        assembly {
            w := mload(add(add(p, 32), o))
        }
        bytes32 mask = bytes32(type(uint256).max << (256 - 8 * n));
        if ((w & mask) != (lit & mask)) revert BadClaim(field);
    }

    /// "iat":<digits> and block.timestamp - MAX_AGE <= iat <= block.timestamp + FUTURE_SKEW
    function _fresh(bytes memory p, uint256 o, uint256 field) internal view {
        _expect(p, o, '"iat":', 6, field);
        uint256 i = o + 6;
        uint256 v;
        uint256 start = i;
        while (i < p.length) {
            uint8 c = uint8(p[i]);
            if (c < 48 || c > 57) break;
            v = v * 10 + (c - 48);
            unchecked {
                ++i;
            }
        }
        if (i == start || i - start > 12) revert BadClaim(field);
        if (v + MAX_AGE < block.timestamp || v > block.timestamp + FUTURE_SKEW) revert Stale();
    }

    /// <key>"<43 b64url chars>" -> 32-byte word
    function _b64Word(bytes memory p, uint256 o, bytes32 lit, uint256 field) internal pure returns (uint256 w) {
        uint256 n = field == 14 ? 11 : 5; // '"sd_hash":"' or '"x":"'
        _expect(p, o, lit, n, field);
        uint256 s = o + n;
        if (s + 44 > p.length || p[s + 43] != '"') revert BadClaim(field);
        bytes memory d = _decode(p, s, s + 43);
        assembly {
            w := mload(add(d, 32))
        }
    }

    /// "nonce":"0x<64 lowercase hex of ctx>"  (DESIGN.md: evpNonce = "0x" + lowercase hex(ctx))
    function _nonce(bytes memory p, uint256 o, bytes32 h) internal pure {
        _expect(p, o, '"nonce":"0x', 11, 12);
        uint256 s = o + 11;
        if (s + 65 > p.length || p[s + 64] != '"') revert BadClaim(12);
        (bytes32 hi, bytes32 lo) = _hex(h);
        bytes32 a;
        bytes32 b;
        assembly {
            a := mload(add(add(p, 32), s))
            b := mload(add(add(p, 64), s))
        }
        if (a != hi || b != lo) revert BadClaim(12);
    }

    /// 32 bytes -> 64 lowercase ASCII hex chars as two words (SWAR nibble spread)
    function _hex(bytes32 h) internal pure returns (bytes32 hi, bytes32 lo) {
        assembly {
            function hex16(x) -> c {
                x := and(or(shl(64, x), x), 0x0000000000000000ffffffffffffffff0000000000000000ffffffffffffffff)
                x := and(or(shl(32, x), x), 0x00000000ffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                x := and(or(shl(16, x), x), 0x0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff)
                x := and(or(shl(8, x), x), 0x00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff)
                x := and(or(shl(4, x), x), 0x0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f)
                let gt9 := and(add(x, 0x7676767676767676767676767676767676767676767676767676767676767676), 0x8080808080808080808080808080808080808080808080808080808080808080)
                c := add(add(x, 0x3030303030303030303030303030303030303030303030303030303030303030), mul(shr(7, gt9), 39))
            }
            hi := hex16(shr(128, h))
            lo := hex16(and(h, 0xffffffffffffffffffffffffffffffff))
        }
    }

    // ---------- crypto helpers ----------

    function _p256(bytes32 h, uint256 r, uint256 s, uint256 x, uint256 y) internal view returns (bool) {
        (bool ok, bytes memory out) = P256VERIFY.staticcall(abi.encode(h, r, s, x, y));
        return ok && out.length == 32 && uint256(bytes32(out)) == 1;
    }

    /// JWS ES256 signature segment: 86 b64url chars -> r||s
    function _sig(bytes memory tok, uint256 a, uint256 b) internal pure returns (uint256 r, uint256 s) {
        if (b - a != 86) revert BadSig(9);
        bytes memory d = _decode(tok, a, b);
        assembly {
            r := mload(add(d, 32))
            s := mload(add(d, 64))
        }
    }

    function _sha256Slice(bytes memory p, uint256 a, uint256 b) internal view returns (bytes32 h) {
        assembly {
            if iszero(staticcall(gas(), 2, add(add(p, 32), a), sub(b, a), 0x00, 0x20)) { revert(0, 0) }
            h := mload(0x00)
        }
    }

    function _hashSlice(bytes memory p, uint256 a, uint256 b) internal pure returns (bytes32 h) {
        if (b > p.length) revert BadB64();
        assembly {
            h := keccak256(add(add(p, 32), a), sub(b, a))
        }
    }

    /// base64url (no padding) decode of p[a..b), 32 chars per step (SWAR).
    /// Rejects any char outside [A-Za-z0-9-_] (so a stray '.' or '~' reverts).
    /// Non-canonical trailing bits are not rejected; the signer chose these bytes.
    function _decode(bytes memory p, uint256 a, uint256 b) internal pure returns (bytes memory out) {
        uint256 n = b - a;
        if (n % 4 == 1 || b > p.length) revert BadB64();
        uint256 outLen = (n * 3) / 4;
        uint256 bad;
        assembly {
            out := mload(0x40)
            mstore(out, outLen)
            mstore(0x40, add(add(out, 64), outLen)) // 32 bytes slack
            let src := add(add(p, 32), a)
            let end := add(src, n)
            let dst := add(out, 32)
            for {} lt(src, end) {} {
                let w := mload(src)
                let left := sub(end, src)
                if lt(left, 32) {
                    // pad missing chars with 'A' (value 0)
                    let keep := not(shr(mul(8, left), not(0)))
                    w := or(and(w, keep), and(not(keep), 0x4141414141414141414141414141414141414141414141414141414141414141))
                }
                bad := or(bad, and(w, 0x8080808080808080808080808080808080808080808080808080808080808080))
                let up := and(and(add(w, 0x3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f), 0x8080808080808080808080808080808080808080808080808080808080808080), not(and(add(w, 0x2525252525252525252525252525252525252525252525252525252525252525), 0x8080808080808080808080808080808080808080808080808080808080808080)))
                let lo := and(and(add(w, 0x1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f), 0x8080808080808080808080808080808080808080808080808080808080808080), not(and(add(w, 0x0505050505050505050505050505050505050505050505050505050505050505), 0x8080808080808080808080808080808080808080808080808080808080808080)))
                let dg := and(and(add(w, 0x5050505050505050505050505050505050505050505050505050505050505050), 0x8080808080808080808080808080808080808080808080808080808080808080), not(and(add(w, 0x4646464646464646464646464646464646464646464646464646464646464646), 0x8080808080808080808080808080808080808080808080808080808080808080)))
                let da := and(and(add(w, 0x5353535353535353535353535353535353535353535353535353535353535353), 0x8080808080808080808080808080808080808080808080808080808080808080), not(and(add(w, 0x5252525252525252525252525252525252525252525252525252525252525252), 0x8080808080808080808080808080808080808080808080808080808080808080)))
                let un := and(and(add(w, 0x2121212121212121212121212121212121212121212121212121212121212121), 0x8080808080808080808080808080808080808080808080808080808080808080), not(and(add(w, 0x2020202020202020202020202020202020202020202020202020202020202020), 0x8080808080808080808080808080808080808080808080808080808080808080)))
                bad := or(bad, xor(or(or(or(up, lo), or(dg, da)), un), 0x8080808080808080808080808080808080808080808080808080808080808080))
                // 0x80 flag -> 0xff byte mask
                up := mul(shr(7, up), 0xff)
                lo := mul(shr(7, lo), 0xff)
                dg := mul(shr(7, dg), 0xff)
                let v := or(
                    or(sub(and(w, up), and(up, 0x4141414141414141414141414141414141414141414141414141414141414141)), sub(and(w, lo), and(lo, 0x4747474747474747474747474747474747474747474747474747474747474747))),
                    or(
                        add(and(w, dg), and(dg, 0x0404040404040404040404040404040404040404040404040404040404040404)),
                        or(and(mul(shr(7, da), 0xff), 0x3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e), and(mul(shr(7, un), 0xff), 0x3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f))
                    )
                )
                // sextets -> 12-bit lanes -> 24-bit lanes -> 24 packed bytes
                v := or(and(v, 0x00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff), shr(2, and(v, 0xff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00)))
                v := or(and(v, 0x0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff), shr(4, and(v, 0xffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000)))
                let o := or(or(or(shl(8, and(v, 0xffffff00000000000000000000000000000000000000000000000000000000)), shl(16, and(v, 0xffffff000000000000000000000000000000000000000000000000))), or(shl(24, and(v, 0xffffff0000000000000000000000000000000000000000)), shl(32, and(v, 0xffffff00000000000000000000000000000000)))), or(or(shl(40, and(v, 0xffffff000000000000000000000000)), shl(48, and(v, 0xffffff0000000000000000))), or(shl(56, and(v, 0xffffff00000000)), shl(64, and(v, 0xffffff)))))
                mstore(dst, o)
                dst := add(dst, 24)
                src := add(src, 32)
            }
        }
        if (bad != 0) revert BadB64();
    }
}
