// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;

// Same flow as test_e2e, but every call is its own broadcast tx so receipts give real (cold, intrinsic-included) gas.
import {Script, console2} from 'forge-std/Script.sol';
import {PresencePool} from '../src/PresencePool.sol';
import {WithdrawalVerifier} from '../src/WithdrawalVerifier.sol';
import {CommitmentVerifier} from '../src/CommitmentVerifier.sol';
import {TransferVerifier} from '../src/TransferVerifier.sol';
import {PoseidonT3} from '../src/lib/PoseidonT3.sol';
import {PoseidonT4} from '../src/lib/PoseidonT4.sol';

contract E2E is Script {
  uint256 constant P = 21_888_242_871_839_275_222_246_405_745_257_275_088_548_364_400_416_034_343_698_204_186_575_808_495_617;
  uint256 constant DENOM = 0.001 ether;
  uint256 constant TV = 0.0004 ether;
  uint256 constant K_ATT = 0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d;
  uint256 constant K_REL = 0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a;
  uint256 constant K_ALICE = 0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6;
  uint256 constant K_CHARLIE = 0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a;
  uint256 constant K_DEP = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;

  PresencePool pool;
  uint256[] stateLeaves;
  uint256[] aspLeaves;
  uint256[] presLeaves;

  function _prove(string memory mode, bytes memory args) internal returns (bytes memory) {
    string[] memory cmd = new string[](4);
    cmd[0] = 'node'; cmd[1] = 'js/prove.mjs'; cmd[2] = mode; cmd[3] = vm.toString(args);
    return vm.ffi(cmd);
  }

  function _dep(uint256 key, uint256 nul, uint256 sec) internal returns (uint256 label) {
    uint256 pre = PoseidonT3.hash([nul, sec]);
    vm.broadcast(key);
    uint256 c = pool.deposit{value: DENOM}(pre);
    label = uint256(keccak256(abi.encodePacked(pool.SCOPE(), pool.nonce()))) % P;
    stateLeaves.push(c);
    aspLeaves.push(label);
  }

  function run() external {
    vm.startBroadcast(K_DEP);
    address wv = address(new WithdrawalVerifier());
    address cv = address(new CommitmentVerifier());
    address tv = address(new TransferVerifier());
    pool = new PresencePool(DENOM, vm.addr(K_ATT), wv, cv, tv);
    vm.stopBroadcast();
    aspLeaves.push(pool.LABEL_TRANSFER());

    uint256 aLabel = _dep(K_ALICE, 111, 222);
    uint256 cLabel = _dep(K_CHARLIE, 333, 444);

    uint256 payeePre = PoseidonT3.hash([uint256(31_337), uint256(4242)]);
    uint256 payeeCommitment = PoseidonT4.hash([TV, pool.LABEL_TRANSFER(), payeePre]);
    uint256 leaf = PoseidonT4.hash([uint256(0x706f702d70726573), PoseidonT3.hash([uint256(0x706f702d7061796572), uint256(111)]), payeeCommitment]);

    vm.broadcast(K_ATT); pool.postPresence(7); presLeaves.push(7);
    vm.broadcast(K_ATT); pool.postPresence(leaf); presLeaves.push(leaf);

    PresencePool.TransferProof memory tp;
    (tp.pA, tp.pB, tp.pC, tp.pubSignals) = abi.decode(
      _prove('transfer', abi.encode(DENOM, aLabel, 111, 222, 555, 666, TV, payeePre, pool.TRANSFER_CONTEXT(), stateLeaves, presLeaves, leaf)),
      (uint256[2], uint256[2][2], uint256[2], uint256[8])
    );
    vm.broadcast(K_REL); pool.transfer(tp);
    stateLeaves.push(tp.pubSignals[1]); stateLeaves.push(tp.pubSignals[2]);

    address bobFresh = address(0xB0B0);
    PresencePool.Withdrawal memory w = PresencePool.Withdrawal(vm.addr(K_REL), abi.encode(bobFresh, vm.addr(K_REL), uint256(0)));
    PresencePool.WithdrawProof memory wp;
    (wp.pA, wp.pB, wp.pC, wp.pubSignals) = abi.decode(
      _prove('withdraw', abi.encode(TV, pool.LABEL_TRANSFER(), 31_337, 4242, 777, 888, TV, uint256(keccak256(abi.encode(w, pool.SCOPE()))) % P, stateLeaves, aspLeaves)),
      (uint256[2], uint256[2][2], uint256[2], uint256[8])
    );
    _dep(K_DEP, 999, 1000); // ASP root moves after the proof was made
    vm.broadcast(K_REL); pool.withdraw(w, wp);
    stateLeaves.push(wp.pubSignals[0]);

    PresencePool.RagequitProof memory rq;
    (rq.pA, rq.pB, rq.pC, rq.pubSignals) =
      abi.decode(_prove('ragequit', abi.encode(DENOM, cLabel, 333, 444)), (uint256[2], uint256[2][2], uint256[2], uint256[4]));
    vm.broadcast(K_CHARLIE); pool.ragequit(rq);

    console2.log('pool', address(pool));
    console2.log('bobFresh balance', bobFresh.balance);
  }
}
