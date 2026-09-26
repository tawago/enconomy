from Crypto.Hash import keccak
def k(b): h=keccak.new(digest_bits=256); h.update(b); return h.digest()
def u256(n): return n.to_bytes(32,'big')
def addr(a): return bytes(12)+bytes.fromhex(a[2:])
def b16(x): assert len(x)==16; return x+bytes(16)      # bytesN: left-aligned, right zero pad
DOMAIN = k(b"pop-ctx-v1")
def nonce(chain, consumer, ctx, nb, sid):
    pre = DOMAIN + u256(chain) + addr(consumer) + ctx + u256(nb) + b16(sid)
    assert len(pre)==192
    return k(pre)
def sh(n, role): return "0x%064x" % (int.from_bytes(k(n+role),'big')>>8)
chain=480; safe="0x5afe5afe5afe5afe5afe5afe5afe5afe5afe5afe"; guard="0x6a7d6a7d6a7d6a7d6a7d6a7d6a7d6a7d6a7d6a7d"
ctx=bytes(range(0xa0,0xc0)); nb=1790000000; sid=bytes.fromhex("00112233445566778899aabbccddeeff")
print("DOMAIN", DOMAIN.hex())
n=nonce(chain,safe,ctx,nb,sid); print("NONCE", n.hex()); print("SH_A", sh(n,b"A")); print("SH_B", sh(n,b"B"))
print("signal_A 0x"+(n+b"A").hex())
# traps
n2=nonce(chain,guard,ctx,nb,sid); print("TRAP consumer=guard", n2.hex())
pre=DOMAIN+u256(chain)+addr(safe)+ctx+u256(nb)+bytes(16)+sid; print("TRAP sid as uint128", k(pre).hex())
# spec-U: abi.encode(string "pop-ctx-v1", ...): head has offset 0xc0, tail len+data
s=b"pop-ctx-v1"; pre=u256(0xc0)+u256(chain)+addr(guard)+ctx+u256(nb)+b16(sid)+u256(len(s))+s+bytes(32-len(s)); print("TRAP specU string-literal+guard", k(pre).hex())
pre=u256(0xc0)+u256(chain)+addr(safe)+ctx+u256(nb)+b16(sid)+u256(len(s))+s+bytes(32-len(s)); print("TRAP string-literal+safe", k(pre).hex())
# pool example: consumer = pool contract
pool="0x9001900190019001900190019001900190019001"; n3=nonce(chain,pool,ctx,nb,sid); print("POOL NONCE", n3.hex(), sh(n3,b"A"), sh(n3,b"B"))
print("--- chained to tx-composition-ux row 1/N")
safe2="0x3fad7600f309b0c3d60a57023b0262460b0603dc"; h1=bytes.fromhex("960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5")
nN=nonce(480,safe2,h1,1790000000,sid); print("N", nN.hex()); assert nN.hex()=="9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121"
print("N SH_A", sh(nN,b"A")); print("N SH_B", sh(nN,b"B")); print("N signal_A 0x"+(nN+b"A").hex())
