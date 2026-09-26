set -e
RPC=http://127.0.0.1:8611; PK=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
dep(){ forge create --broadcast --rpc-url $RPC --private-key $PK "$@" 2>&1 | grep "Deployed to" | awk '{print $3}'; }
L=""
for f in HalfVerifier PairVerifier; do for lib in RelationsLib ZKTranscriptLib; do a=$(dep src/$f.sol:$lib); echo $f $lib $a; L="$L --libraries src/$f.sol:$lib:$a"; done; done
HV=$(dep $L src/HalfVerifier.sol:HalfVerifier); PV=$(dep $L src/PairVerifier.sol:PairVerifier); echo HV=$HV PV=$PV
pubarr(){ python3 -c "import sys;d=open(sys.argv[1],'rb').read();print('['+','.join('0x'+d[i:i+32].hex() for i in range(0,len(d),32))+']')" $1; }
hexf(){ echo 0x$(xxd -p $1 | tr -d '\n'); }
A=$(pubarr ../noir/half/out_half/public_inputs); Bp=$(pubarr ../noir/half/out_halfB/public_inputs); P=$(pubarr ../noir/pair/out/public_inputs)
ISS=$(python3 -c "print('['+','.join('$A'.strip('[]').split(',')[:4])+']')"); CTX=$(echo "$A" | tr -d '[]' | cut -d, -f7); SC=$(echo "$A" | tr -d '[]' | cut -d, -f6)
G=$(dep $L src/PopGuard.sol:PopGuard --constructor-args $HV $PV "$ISS" $SC); echo G=$G
rcpt(){ python3 -c "import json,sys;r=json.load(sys.stdin);print('status',r['status'],'gasUsed',int(r['gasUsed'],16))"; }
echo -n "verify half A tx: "; cast send --rpc-url $RPC --private-key $PK $HV "verify(bytes,bytes32[])" $(hexf ../noir/half/out_half/proof) "$A" --json | rcpt
echo -n "verify pair tx: "; cast send --rpc-url $RPC --private-key $PK $PV "verify(bytes,bytes32[])" $(hexf ../noir/pair/out/proof) "$P" --json | rcpt
echo -n "checkHalves tx: "; cast send --rpc-url $RPC --private-key $PK $G "checkHalves(bytes,bytes32[],bytes,bytes32[],bytes32)" $(hexf ../noir/half/out_half/proof) "$A" $(hexf ../noir/half/out_halfB/proof) "$Bp" $CTX --json | rcpt
G2=$(dep $L src/PopGuard.sol:PopGuard --constructor-args $HV $PV "$ISS" $SC)
echo -n "checkPair tx: "; cast send --rpc-url $RPC --private-key $PK $G2 "checkPair(bytes,bytes32[],bytes32)" $(hexf ../noir/pair/out/proof) "$P" $CTX --json | rcpt || true
echo -n "replay checkHalves (expect revert nullified): "; cast send --rpc-url $RPC --private-key $PK $G "checkHalves(bytes,bytes32[],bytes,bytes32[],bytes32)" $(hexf ../noir/half/out_half/proof) "$A" $(hexf ../noir/half/out_halfB/proof) "$Bp" $CTX 2>&1 | grep -o "revert.*" | head -1
# tampered public input: flip half value of A
A2=$(echo "$A" | python3 -c "import sys;x=sys.stdin.read().strip().strip('[]').split(',');x[12]='0x'+format(5001,'064x');print('['+','.join(x)+']')")
echo -n "tampered half (expect revert): "; cast call --rpc-url $RPC $HV "verify(bytes,bytes32[])" $(hexf ../noir/half/out_half/proof) "$A2" 2>&1 | head -1
