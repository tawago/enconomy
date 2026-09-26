#!/bin/bash
# usage: gas.sh VERIFIER_NAME PROOF_DIR   (run in forge/, anvil must be up on $RPC)
# Deploys the two linked libraries + the verifier, sends verify() as a real tx (tx gas incl. calldata + 21k).
set -e
RPC=${RPC:-http://127.0.0.1:8622}; PK=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
V=$1; D=$2
dep(){ forge create --broadcast --rpc-url $RPC --private-key $PK "$@" 2>&1 | grep "Deployed to" | awk '{print $3}'; }
L=""; for lib in RelationsLib ZKTranscriptLib; do a=$(dep src/$V.sol:$lib); L="$L --libraries src/$V.sol:$lib:$a"; done
A=$(dep $L src/$V.sol:$V); echo "$V deployed at $A"
pubarr(){ python3 -c "import sys;d=open(sys.argv[1],'rb').read();print('['+','.join('0x'+d[i:i+32].hex() for i in range(0,len(d),32))+']')" $1; }
hexf(){ echo 0x$(xxd -p $1 | tr -d '\n'); }
P=$(pubarr $D/public_inputs)
echo -n "eth_call verify: "; cast call --rpc-url $RPC $A "verify(bytes,bytes32[])(bool)" $(hexf $D/proof) "$P"
echo -n "verify tx: "; cast send --rpc-url $RPC --private-key $PK $A "verify(bytes,bytes32[])" $(hexf $D/proof) "$P" --json \
  | python3 -c "import json,sys;r=json.load(sys.stdin);print('status',r['status'],'gasUsed',int(r['gasUsed'],16))"
P2=$(echo "$P" | python3 -c "import sys;x=sys.stdin.read().strip().strip('[]').split(',');v=int(x[-1],16)^1;x[-1]='0x'+format(v,'064x');print('['+','.join(x)+']')")
echo -n "tampered last public input (expect revert/false): "; cast call --rpc-url $RPC $A "verify(bytes,bytes32[])(bool)" $(hexf $D/proof) "$P2" 2>&1 | head -1
