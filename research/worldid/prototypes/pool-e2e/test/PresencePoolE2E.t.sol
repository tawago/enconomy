// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;

import {Test, console2, Vm} from 'forge-std/Test.sol';
import {PresencePool} from '../src/PresencePool.sol';
import {WithdrawalVerifier} from '../src/WithdrawalVerifier.sol';
import {CommitmentVerifier} from '../src/CommitmentVerifier.sol';
import {TransferVerifier} from '../src/TransferVerifier.sol';
import {PoseidonT3} from '../src/lib/PoseidonT3.sol';
import {PoseidonT4} from '../src/lib/PoseidonT4.sol';

contract PresencePoolE2E is Test {
  uint256 constant P = 21_888_242_871_839_275_222_246_405_745_257_275_088_548_364_400_416_034_343_698_204_186_575_808_495_617;
  uint256 constant TAG_PAYER = 0x706f702d7061796572;
  uint256 constant TAG_PRES = 0x706f702d70726573;
  uint256 constant DENOM = 0.001 ether;
  uint256 constant TV = 0.0004 ether;

  PresencePool pool;
  address attester = makeAddr('attester');
  address relayer = makeAddr('relayer');
  address alice = makeAddr('alice'); // payer
  address charlie = makeAddr('charlie'); // untouched depositor -> ragequit
  address dave = makeAddr('dave'); // late depositor, moves the ASP root
  address bobFresh = makeAddr('bobFresh'); // payee cash-out address

  uint256[] stateLeaves;
  uint256[] aspLeaves;
  uint256[] presLeaves;

  struct Note { uint256 value; uint256 label; uint256 nul; uint256 sec; }

  function setUp() public {
    vm.createSelectFork(vm.envOr('RPC_480', string('https://worldchain-mainnet.g.alchemy.com/public')));
    assertEq(block.chainid, 480, 'not a 480 fork');
    pool = new PresencePool(
      DENOM, attester, address(new WithdrawalVerifier()), address(new CommitmentVerifier()), address(new TransferVerifier())
    );
    aspLeaves.push(pool.LABEL_TRANSFER());
    vm.deal(alice, 1 ether); vm.deal(charlie, 1 ether); vm.deal(dave, 1 ether);
  }

  // ---------------------------------------------------------------- helpers
  function _dep(address who, uint256 nul, uint256 sec) internal returns (Note memory n) {
    uint256 pre = PoseidonT3.hash([nul, sec]);
    vm.prank(who);
    uint256 g = gasleft();
    uint256 c = pool.deposit{value: DENOM}(pre);
    console2.log('deposit gas (inner)', g - gasleft());
    uint256 label = uint256(keccak256(abi.encodePacked(pool.SCOPE(), pool.nonce()))) % P;
    assertEq(c, PoseidonT4.hash([DENOM, label, pre]));
    stateLeaves.push(c);
    aspLeaves.push(label);
    n = Note(DENOM, label, nul, sec);
  }

  function _prove(string memory mode, bytes memory args) internal returns (bytes memory) {
    string[] memory cmd = new string[](4);
    cmd[0] = 'node'; cmd[1] = 'js/prove.mjs'; cmd[2] = mode; cmd[3] = vm.toString(args);
    return vm.ffi(cmd);
  }

  function _tryProve(string memory mode, bytes memory args) internal returns (Vm.FfiResult memory) {
    string[] memory cmd = new string[](4);
    cmd[0] = 'node'; cmd[1] = 'js/prove.mjs'; cmd[2] = mode; cmd[3] = vm.toString(args);
    return vm.tryFfi(cmd);
  }

  function _decode8(bytes memory b) internal pure returns (uint256[2] memory a, uint256[2][2] memory bb, uint256[2] memory c, uint256[8] memory s) {
    (a, bb, c, s) = abi.decode(b, (uint256[2], uint256[2][2], uint256[2], uint256[8]));
  }

  function _withdrawProof(Note memory n, uint256 newNul, uint256 newSec, uint256 wv, PresencePool.Withdrawal memory w)
    internal returns (PresencePool.WithdrawProof memory p)
  {
    uint256 ctx = uint256(keccak256(abi.encode(w, pool.SCOPE()))) % P;
    bytes memory out = _prove('withdraw', abi.encode(n.value, n.label, n.nul, n.sec, newNul, newSec, wv, ctx, stateLeaves, aspLeaves));
    (p.pA, p.pB, p.pC, p.pubSignals) = _decode8(out);
    assertEq(p.pubSignals[3], pool.currentRoot(), 'js state root != onchain');
    assertEq(p.pubSignals[5], pool.aspRoot(), 'js asp root != onchain');
  }

  // ---------------------------------------------------------------- the demo, end to end
  function test_e2e() public {
    // 1. deposits
    Note memory a = _dep(alice, 111, 222);
    Note memory c = _dep(charlie, 333, 444);

    // 2. payee builds the request, payer computes the presence leaf
    uint256 bNul = 31_337; uint256 bSec = 4242;
    uint256 payeePre = PoseidonT3.hash([bNul, bSec]);
    uint256 payeeCommitment = PoseidonT4.hash([TV, pool.LABEL_TRANSFER(), payeePre]);
    uint256 payerTag = PoseidonT3.hash([TAG_PAYER, a.nul]);
    uint256 leaf = PoseidonT4.hash([TAG_PRES, payerTag, payeeCommitment]);

    uint256 aNew = 555; uint256 aNewSec = 666;
    bytes memory targs = abi.encode(a.value, a.label, a.nul, a.sec, aNew, aNewSec, TV, payeePre, pool.TRANSFER_CONTEXT(), stateLeaves, presLeaves, leaf);

    // 3. no meeting yet -> the transfer cannot even be proven
    presLeaves.push(7); vm.prank(attester); pool.postPresence(7); // unrelated meeting
    targs = abi.encode(a.value, a.label, a.nul, a.sec, aNew, aNewSec, TV, payeePre, pool.TRANSFER_CONTEXT(), stateLeaves, presLeaves, leaf);
    assertTrue(_tryProve('transfer', targs).exitCode != 0, 'proof without presence leaf must fail');

    // 4. attester posts the leaf (onlyAttester)
    vm.expectRevert(PresencePool.OnlyAttester.selector);
    pool.postPresence(leaf);
    vm.prank(attester);
    uint256 g = gasleft();
    pool.postPresence(leaf);
    console2.log('postPresence gas (inner)', g - gasleft());
    presLeaves.push(leaf);
    presLeaves.push(8); vm.prank(attester); pool.postPresence(8); // another meeting after ours: root history must cover it

    // 5. payer proves and the relayer submits
    targs = abi.encode(a.value, a.label, a.nul, a.sec, aNew, aNewSec, TV, payeePre, pool.TRANSFER_CONTEXT(), stateLeaves, presLeaves, leaf);
    PresencePool.TransferProof memory tp;
    (tp.pA, tp.pB, tp.pC, tp.pubSignals) = _decode8(_prove('transfer', targs));
    assertEq(tp.pubSignals[2], payeeCommitment, 'payee commitment mismatch');
    assertEq(tp.pubSignals[5], pool.presenceRoot());

    // proof made against the root before leaf 8? no: we used the latest. Make one more presence post so the proof's root is historical
    presLeaves.push(9); vm.prank(attester); pool.postPresence(9);
    assertTrue(tp.pubSignals[5] != pool.presenceRoot(), 'expected historical presence root');

    uint256 sizeBefore = pool.currentTreeSize();
    vm.recordLogs();
    vm.prank(relayer);
    g = gasleft();
    pool.transfer(tp);
    console2.log('transfer gas (inner)', g - gasleft());
    Vm.Log[] memory logs = vm.getRecordedLogs();
    bytes32 LI = keccak256('LeafInserted(uint256,uint256,uint256)');
    uint256 k;
    for (uint256 i; i < logs.length; i++) {
      if (logs[i].topics[0] != LI) continue;
      (uint256 idx, uint256 lf,) = abi.decode(logs[i].data, (uint256, uint256, uint256));
      console2.log('LeafInserted index', idx);
      console2.log('  leaf', lf);
      if (k == 0) { assertEq(lf, tp.pubSignals[1], 'first insert must be change'); assertEq(idx, sizeBefore + 1); }
      if (k == 1) { assertEq(lf, payeeCommitment, 'second insert must be payee'); assertEq(idx, sizeBefore + 2); }
      k++;
    }
    assertEq(k, 2);
    stateLeaves.push(tp.pubSignals[1]);
    stateLeaves.push(tp.pubSignals[2]);

    // replay dies
    vm.expectRevert(PresencePool.NullifierAlreadySpent.selector);
    pool.transfer(tp);

    // 6. payee cash-out through the relayer with 0xbow production withdraw.zkey, fee 0
    Note memory b = Note(TV, pool.LABEL_TRANSFER(), bNul, bSec);
    PresencePool.Withdrawal memory w = PresencePool.Withdrawal(relayer, abi.encode(bobFresh, relayer, uint256(0)));
    PresencePool.WithdrawProof memory wp = _withdrawProof(b, 777, 888, TV, w);
    // a late deposit moves the ASP root: 0xbow's == latest rule would reject this proof
    _dep(dave, 999, 1000);
    assertTrue(wp.pubSignals[5] != pool.aspRoot(), 'expected historical ASP root');
    vm.prank(relayer);
    g = gasleft();
    pool.withdraw(w, wp);
    console2.log('payee withdraw gas (inner, relayed)', g - gasleft());
    assertEq(bobFresh.balance, TV, 'payee did not get paid');
    stateLeaves.push(wp.pubSignals[0]);

    // 7. payer withdraws the change directly (own label, ASP-approved at deposit)
    Note memory ch = Note(DENOM - TV, a.label, aNew, aNewSec);
    PresencePool.Withdrawal memory w2 = PresencePool.Withdrawal(alice, '');
    PresencePool.WithdrawProof memory wp2 = _withdrawProof(ch, 1212, 1313, DENOM - TV, w2);
    uint256 ab = alice.balance;
    vm.prank(alice);
    g = gasleft();
    pool.withdraw(w2, wp2);
    console2.log('payer change withdraw gas (inner, direct)', g - gasleft());
    assertEq(alice.balance, ab + DENOM - TV);
    stateLeaves.push(wp2.pubSignals[0]);

    // 8. untouched deposit ragequits with 0xbow production commitment.zkey
    PresencePool.RagequitProof memory rq;
    (rq.pA, rq.pB, rq.pC, rq.pubSignals) =
      abi.decode(_prove('ragequit', abi.encode(c.value, c.label, c.nul, c.sec)), (uint256[2], uint256[2][2], uint256[2], uint256[4]));
    uint256 cb = charlie.balance;
    vm.prank(charlie);
    g = gasleft();
    pool.ragequit(rq);
    console2.log('ragequit gas (inner)', g - gasleft());
    assertEq(charlie.balance, cb + DENOM);

    // accounting: 3 deposits in, TV + change + ragequit out -> dave's DENOM remains
    assertEq(address(pool).balance, DENOM);
    console2.log('SCOPE', pool.SCOPE());
    console2.log('TRANSFER_CONTEXT', pool.TRANSFER_CONTEXT());
  }

  // payee note cannot be ragequit (no depositor) and a wrong-context withdraw fails
  function test_negative() public {
    _dep(alice, 111, 222);
    PresencePool.RagequitProof memory rq;
    rq.pubSignals[3] = pool.LABEL_TRANSFER();
    vm.expectRevert(PresencePool.OnlyOriginalDepositor.selector);
    pool.ragequit(rq);
    vm.expectRevert(PresencePool.WrongValue.selector);
    vm.prank(alice);
    pool.deposit{value: DENOM + 1}(1);
  }
}
