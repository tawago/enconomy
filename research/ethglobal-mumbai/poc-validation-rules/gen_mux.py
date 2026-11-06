"""Assemble the multiplexed frame-opcode helper (FrameEnvLiveMux) and its forge gas stub.

Calldata: word0 = kind, word1 = a, word2 = b. Kinds, in dispatch order (most frequent first):
  0 TXPARAM(a=id)  1 FRAMEPARAM(a=frame,b=param)  2 SIGPARAM(a=sig,b=param)
  3 FRAMEDATALOAD(a=offset,b=frame)  4 RECENTROOTREFLOAD(a=field,b=ref)  5 APPROVE(a=scope)
`a` ends on top of the stack, same as the single-opcode helpers in FrameEnvLive.
Stub: same dispatch, but each branch looks up table[kind*1024 + a*16 + b] in its own code (CODECOPY).
Run: python3 gen_mux.py   (prints runtime, creation code, stub prefix)
"""
OPS = [0xB0, 0xB3, 0xB4, 0xB1, 0xB6, 0xAA]

def asm(branch_bodies):
    # prologue: [b, a, kind] kind on top
    pro = bytes.fromhex("604035" "602035" "600035")
    # dispatch entries: DUP1 PUSH1 i EQ PUSH2 dest JUMPI (8 bytes each), then INVALID fallthrough
    n = len(branch_bodies)
    disp_len = 8 * n + 1
    dest = len(pro) + disp_len
    disp = b""
    dests = []
    for i, body in enumerate(branch_bodies):
        dests.append(dest)
        dest += len(body)
    for i in range(n):
        disp += bytes([0x80, 0x60, i, 0x14, 0x61]) + dests[i].to_bytes(2, "big") + bytes([0x57])
    disp += bytes([0xFE])
    code = pro + disp + b"".join(branch_bodies)
    for d in dests:
        assert code[d] == 0x5B
    return code

def real():
    bodies = []
    for i, op in enumerate(OPS):
        if op == 0xAA:  # JUMPDEST POP(kind) PUSH1 0 DUP1 APPROVE  -> [b, scope, 0, 0]
            bodies.append(bytes.fromhex("5b50") + bytes.fromhex("600080") + bytes([0xAA]))
        else:  # JUMPDEST POP <op> PUSH1 0 MSTORE PUSH1 32 PUSH1 0 RETURN
            bodies.append(bytes.fromhex("5b50") + bytes([op]) + bytes.fromhex("600052" "60206000f3"))
    return asm(bodies)

def burn_body(start, burn):
    """APPROVE stand-in that burns `burn` gas, or halts if it can't (EIP-8250 keyed-nonce first use:
    ethrex charges KEYED_NONCE_FIRST_USE_GAS = 20000 to the frame that runs APPROVE, vm.rs ~1985).
    JUMPDEST POP | PUSH2 burn GAS LT PUSH2 bad JUMPI | PUSH2 burn GAS SUB |
    L: JUMPDEST DUP1 GAS GT PUSH2 L JUMPI STOP | bad: JUMPDEST INVALID"""
    loop = start + 2 + 9 + 5
    bad = loop + 9
    b = (bytes.fromhex("5b50") + bytes([0x61]) + burn.to_bytes(2, "big") + bytes.fromhex("5a10") + bytes([0x61])
         + bad.to_bytes(2, "big") + bytes([0x57]) + bytes([0x61]) + burn.to_bytes(2, "big") + bytes.fromhex("5a03")
         + bytes.fromhex("5b805a11") + bytes([0x61]) + loop.to_bytes(2, "big") + bytes.fromhex("5700") + bytes.fromhex("5bfe"))
    assert len(b) == bad + 2 - start
    return b

def stub(burn=0):
    # table base must be fixed: build twice
    def bodies(base, approve_at=0):
        out = []
        for i, op in enumerate(OPS):
            if op == 0xAA:
                out.append(bytes.fromhex("5b50") + bytes([0x00]) if not burn else burn_body(approve_at, burn))
            else:
                # [b, a] a top: PUSH1 4 SHL ADD PUSH2 i*1024 ADD PUSH1 5 SHL PUSH2 base ADD
                # PUSH1 32 SWAP1 PUSH1 0 CODECOPY PUSH1 32 PUSH1 0 RETURN
                out.append(bytes.fromhex("5b50" "60041b" "01" "61") + (i * 1024).to_bytes(2, "big")
                           + bytes.fromhex("01" "60051b" "61") + base.to_bytes(2, "big")
                           + bytes.fromhex("01" "602090" "600039" "60206000f3"))
        return out
    c = asm(bodies(0))
    # the APPROVE branch is last, so its start = len(code) - len(its body); fix positions, then the table base
    last = len(bodies(0)[-1])
    c = asm(bodies(0, len(c) - last))
    c = asm(bodies(len(c), len(c) - last))
    return c

r = real()
creation = bytes([0x60, len(r), 0x60, 0x0D, 0x60, 0x00, 0x39, 0x60, len(r), 0x60, 0x00, 0xF3, 0xFE]) + r
print("runtime ", len(r), r.hex())
print("creation", creation.hex())
print("stub    ", len(stub()), stub().hex())
print("stub20k ", len(stub(20000)), stub(20000).hex())
