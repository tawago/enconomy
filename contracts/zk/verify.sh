#!/bin/bash
# usage: ./verify.sh VERIFIER_ADDR VERIFYLOG_ADDR FIXTURE_DIR   -> eth_call, VerifyLog tx, tampered eth_call
set -e
RPC=${RPC:-https://ethereum-sepolia-rpc.publicnode.com}; KEY_FILE=${KEY_FILE:-$HOME/.enconomy/ens-sepolia.key}
V=$1; VL=$2; D=$3
pubarr(){ python3 -c "import sys;d=open(sys.argv[1],'rb').read();print('['+','.join('0x'+d[i:i+32].hex() for i in range(0,len(d),32))+']')" $1; }
PR=0x$(xxd -p $D/proof | tr -d '\n'); P=$(pubarr $D/public_inputs)
echo "eth_call verify: $(cast call --rpc-url $RPC $V 'verify(bytes,bytes32[])(bool)' $PR "$P")"
for i in 1 2 3 4; do
  r=$(cast send --rpc-url $RPC --private-key "$(cat $KEY_FILE)" --gas-limit 5000000 $VL 'verifyAndLog(address,bytes,bytes32[])' $V $PR "$P" --json 2>&1) && break
  echo "retry: $(echo "$r" | tail -1)" >&2; sleep 4; done
echo "$r" | python3 -c "import json,sys;r=json.load(sys.stdin);l=r['logs'][0];print('tx',r['transactionHash'],'status',int(r['status'],16),'txGas',int(r['gasUsed'],16),'ok',int(l['data'][66:130],16),'verifyGas',int(l['data'][130:194],16))"
P2=$(echo "$P" | python3 -c "import sys;x=sys.stdin.read().strip().strip('[]').split(',');v=int(x[-1],16)^1;x[-1]='0x'+format(v,'064x');print('['+','.join(x)+']')")
echo "tampered eth_call: $(cast call --rpc-url $RPC $V 'verify(bytes,bytes32[])(bool)' $PR "$P2" 2>&1 | tail -1)"
