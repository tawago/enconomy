#!/usr/bin/env python3
"""Generate yul/sha256.yul: a standalone Yul contract that computes SHA-256 with no precompile.

Calldata: word 0 = header, then the message bytes.
  header byte 31 = mode (0 plain sha256 of message, 1 EVP 1-lane, 4 EVP SWAR 4-lane); byte 30 = withSd (0/1)
  header bits [16..64) = d2, t, k2 (uint16 each, bits 16,32,48) for the EVP modes
EVP modes return 96 bytes: sha256(msg[0..d2)), sha256(msg[t+1..k2)), sha256(msg[0..t+1)) (0 if !withSd).

Compressors are fully unrolled with register renaming. compress4 is SWAR: 4 independent messages in the four
64-bit lanes of each word. Rotation trick for a clean u32 x: rotr(x,n) = low32((x | x<<32) >> n).
"""
K = [
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]
H0 = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]
ST, ST2, WP, T0, T1, T2, ZERO, MSG = 0x100, 0x200, 0x400, 0xC00, 0xC80, 0xD00, 0xE00, 0x1000

def bc(x, lanes): return hex(sum(x << (64 * l) for l in range(lanes)))

def rounds(lanes):
    M = bc(0xffffffff, lanes); L = []
    for t in range(16, 64):
        s0 = "xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))"; s1 = "xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx))"
        if lanes > 1: s0 = f"and({s0}, {M})"; s1 = f"and({s1}, {M})"
        L.append(f"{{ let sx := mload({WP + 32*(t-15)}) let sd := or(sx, shl(32, sx)) let s0 := {s0}")
        L.append(f"  sx := mload({WP + 32*(t-2)}) sd := or(sx, shl(32, sx))")
        L.append(f"  mstore({WP + 32*t}, and(add(add(s0, mload({WP + 32*(t-16)})), add({s1}, mload({WP + 32*(t-7)}))), {M})) }}")
    L.append(f"let a := mload({ST if lanes>0 else 0}) ".replace(str(ST), "st"))
    L[-1] = "let a := mload(st) let b := mload(add(st, 32)) let c := mload(add(st, 64)) let d := mload(add(st, 96))"
    L.append("let e := mload(add(st, 128)) let f := mload(add(st, 160)) let g := mload(add(st, 192)) let h := mload(add(st, 224))")
    v = list("abcdefgh")
    for t in range(64):
        a,b,c,d,e,f,g,h = v
        S1 = "xor(xor(shr(6, de), shr(11, de)), shr(25, de))"; S0 = "xor(xor(shr(2, da), shr(13, da)), shr(22, da))"
        if lanes > 1: S1 = f"and({S1}, {M})"; S0 = f"and({S0}, {M})"
        L.append(f"{{ let de := or({e}, shl(32, {e}))")
        L.append(f"  let t1 := add(add(add({h}, {S1}), add(xor({g}, and({e}, xor({f}, {g}))), {bc(K[t], lanes)})), mload({WP + 32*t}))")
        L.append(f"  let da := or({a}, shl(32, {a}))")
        L.append(f"  {d} := and(add({d}, t1), {M})")
        L.append(f"  {h} := and(add(t1, add({S0}, or(and({a}, {b}), and({c}, or({a}, {b}))))), {M}) }}")
        v = [h, a, b, c, d, e, f, g]
    for i, r in enumerate("abcdefgh"):
        L.append(f"mstore(add(st, {32*i}), and(add(mload(add(st, {32*i})), {r}), {M}))")
    return L

def ind(lines, n): return ["    " * n + l for l in lines]

load1 = [f"mstore({WP + 32*i}, and(shr({224-32*(i%8)}, mload(add(blk, {32*(i//8)}))), 0xffffffff))" for i in range(16)]
load4 = []
for half in range(2):
    load4.append(f"{{ let w0 := mload(add(p0, {32*half})) let w1 := mload(add(p1, {32*half})) let w2 := mload(add(p2, {32*half})) let w3 := mload(add(p3, {32*half}))")
    for j in range(8):
        sh = 224 - 32*j
        load4.append(f"  mstore({WP + 32*(half*8+j)}, or(or(and(shr({sh}, w0), 0xffffffff), shl(64, and(shr({sh}, w1), 0xffffffff))), or(shl(128, and(shr({sh}, w2), 0xffffffff)), shl(192, and(shr({sh}, w3), 0xffffffff)))))")
    load4.append("}")

drv = f"""
function init1(st) {{
{chr(10).join(f'    mstore(add(st, {32*i}), {hex(x)})' for i, x in enumerate(H0))}
}}
function init4(st) {{
{chr(10).join(f'    mstore(add(st, {32*i}), {bc(x, 4)})' for i, x in enumerate(H0))}
}}
function digest1(st) -> hh {{
    for {{ let i := 0 }} lt(i, 8) {{ i := add(i, 1) }} {{ hh := or(hh, shl(sub(224, mul(32, i)), mload(add(st, mul(32, i))))) }}
}}
function digest4(st, lane) -> hh {{
    let s := mul(64, lane)
    for {{ let i := 0 }} lt(i, 8) {{ i := add(i, 1) }} {{ hh := or(hh, shl(sub(224, mul(32, i)), and(shr(s, mload(add(st, mul(32, i)))), 0xffffffff))) }}
}}
// padded tail of MSG[a..b) at tp (128 bytes); returns tail block count
function tail(a, b, tp) -> nt {{
    let n := sub(b, a)
    let full := div(n, 64)
    let rem := mod(n, 64)
    nt := add(1, gt(add(rem, 9), 64))
    mstore(tp, 0) mstore(add(tp, 32), 0) mstore(add(tp, 64), 0) mstore(add(tp, 96), 0)
    mcopy(tp, add({MSG}, add(a, mul(full, 64))), rem)
    mstore8(add(tp, rem), 0x80)
    let end := add(tp, mul(nt, 64))
    mstore(sub(end, 32), or(and(mload(sub(end, 32)), not(0xffffffffffffffff)), mul(n, 8)))
}}
function ptr(a, full, tp, k) -> p {{
    p := add(tp, mul(sub(k, full), 64))
    if lt(k, full) {{ p := add({MSG}, add(a, mul(k, 64))) }}
}}
function sha1(a, b, st, tp) -> hh {{
    init1(st)
    let full := div(sub(b, a), 64)
    let total := add(full, tail(a, b, tp))
    for {{ let k := 0 }} lt(k, total) {{ k := add(k, 1) }} {{ compress1(st, ptr(a, full, tp, k)) }}
    hh := digest1(st)
}}
function evp1(d2, t, k2, wsd) {{
    let shared := div(d2, 64)
    init1({ST})
    for {{ let k := 0 }} lt(k, shared) {{ k := add(k, 1) }} {{ compress1({ST}, add({MSG}, mul(k, 64))) }}
    if wsd {{ mcopy({ST2}, {ST}, 256) }}
    let nt := tail(0, d2, {T0})
    for {{ let k := 0 }} lt(k, nt) {{ k := add(k, 1) }} {{ compress1({ST}, add({T0}, mul(k, 64))) }}
    mstore(0, digest1({ST}))
    mstore(64, 0)
    if wsd {{
        let fullC := div(add(t, 1), 64)
        let totalC := add(fullC, tail(0, add(t, 1), {T2}))
        for {{ let k := shared }} lt(k, totalC) {{ k := add(k, 1) }} {{ compress1({ST2}, ptr(0, fullC, {T2}, k)) }}
        mstore(64, digest1({ST2}))
    }}
    mstore(32, sha1(add(t, 1), k2, {ST}, {T1}))
}}
function evp4(d2, t, k2, wsd) {{
    mstore({ZERO}, 0) mstore(add({ZERO}, 32), 0)
    let fullA := div(d2, 64)
    let nA := add(fullA, tail(0, d2, {T0}))
    let aB := add(t, 1)
    let fullB := div(sub(k2, aB), 64)
    let nB := add(fullB, tail(aB, k2, {T1}))
    let fullC := div(add(t, 1), 64)
    let nC := 0
    if wsd {{ nC := add(fullC, tail(0, add(t, 1), {T2})) }}
    let steps := nA
    if gt(nB, steps) {{ steps := nB }}
    if gt(nC, steps) {{ steps := nC }}
    init4({ST})
    mstore(64, 0)
    for {{ let s := 0 }} lt(s, steps) {{ s := add(s, 1) }} {{
        if and(wsd, eq(s, fullA)) {{
            for {{ let i := 0 }} lt(i, 8) {{ i := add(i, 1) }} {{
                let p := add({ST}, mul(32, i))
                let w := mload(p)
                mstore(p, or(and(w, not(shl(128, 0xffffffff))), shl(128, and(w, 0xffffffff))))
            }}
        }}
        let p0 := {ZERO} if lt(s, nA) {{ p0 := ptr(0, fullA, {T0}, s) }}
        let p1 := {ZERO} if lt(s, nB) {{ p1 := ptr(aB, fullB, {T1}, s) }}
        let p2 := {ZERO} if and(iszero(lt(s, fullA)), lt(s, nC)) {{ p2 := ptr(0, fullC, {T2}, s) }}
        compress4({ST}, p0, p1, p2, {ZERO})
        if eq(add(s, 1), nA) {{ mstore(0, digest4({ST}, 0)) }}
        if eq(add(s, 1), nB) {{ mstore(32, digest4({ST}, 1)) }}
        if and(wsd, eq(add(s, 1), nC)) {{ mstore(64, digest4({ST}, 2)) }}
    }}
}}
"""

src = ['object "Sha256Yul" {',
       '  code { datacopy(0, dataoffset("runtime"), datasize("runtime")) return(0, datasize("runtime")) }',
       '  object "runtime" {',
       '    code {',
       '      let hdr := calldataload(0)',
       '      let len := sub(calldatasize(), 32)',
       f'      calldatacopy({MSG}, 32, len)',
       '      let mode := and(hdr, 0xff)',
       '      let withSd := and(shr(8, hdr), 0xff)',
       '      let hd2 := and(shr(16, hdr), 0xffff)',
       '      let ht := and(shr(32, hdr), 0xffff)',
       '      let hk2 := and(shr(48, hdr), 0xffff)',
       f'      if eq(mode, 0) {{ mstore(0, sha1(0, len, {ST}, {T0})) return(0, 32) }}',
       '      if eq(mode, 1) { evp1(hd2, ht, hk2, withSd) return(0, 96) }',
       '      if eq(mode, 4) { evp4(hd2, ht, hk2, withSd) return(0, 96) }',
       '      revert(0, 0)',
       '',
       '      function compress1(st, blk) {']
src += ind(load1, 4)
src += ['        rounds1(st)', '      }',
        '      function compress4(st, p0, p1, p2, p3) {']
src += ind(load4, 4)
src += ['        rounds4(st)', '      }',
        '      function rounds1(st) {']
src += ind(rounds(1), 4)
src += ['      }', '      function rounds4(st) {']
src += ind(rounds(4), 4)
src += ['      }']
src += ind(drv.strip().split("\n"), 3)
src += ['    }', '  }', '}']
open("yul/sha256.yul", "w").write("\n".join(src) + "\n")
print("wrote yul/sha256.yul", len(src), "lines")

# 1-lane-only variant (modes 0 and 1): small enough for the Yul optimizer to finish quickly
one = [l for l in src]
out = "\n".join(one)
a = out.index("      function compress4("); b = out.index("      function rounds1(")
out = out[:a] + out[b:]
a = out.index("      function rounds4("); b = out.index("      }\n", out.index("mstore(add(st, 224)", a)) + 8
out = out[:a] + out[b:]
a = out.index("function init4("); b = out.index("function digest1(")
out = out[:a] + out[b:]
a = out.index("function digest4("); b = out.index("// padded tail")
out = out[:a] + out[b:]
a = out.index("function evp4("); b = out.rindex("}\n", 0, out.rindex("    }\n  }\n}"))
out = out[:a] + out[out.index("\n", b) + 1:] if False else out
out = out.replace("      if eq(mode, 4) { evp4(hd2, ht, hk2, withSd) return(0, 96) }\n", "")
import re
i = out.index("function evp4(")
# drop evp4 through the end of the function body: find matching brace
depth = 0; j = out.index("{", i)
for k in range(j, len(out)):
    if out[k] == "{": depth += 1
    elif out[k] == "}":
        depth -= 1
        if depth == 0: break
out = out[:i] + out[k+1:]
open("yul/sha256_1lane.yul", "w").write(out + "\n")
print("wrote yul/sha256_1lane.yul")
