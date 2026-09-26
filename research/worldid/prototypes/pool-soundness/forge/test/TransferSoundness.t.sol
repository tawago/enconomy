// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;

import {Test} from 'forge-std/Test.sol';
import {PresencePool} from '../src/PresencePool.sol';
import {WithdrawalVerifier} from '../src/WithdrawalVerifier.sol';
import {CommitmentVerifier} from '../src/CommitmentVerifier.sol';
import {TransferVerifier} from '../src/TransferVerifier.sol';
import {PoseidonT3} from '../src/lib/PoseidonT3.sol';
import {PoseidonT4} from '../src/lib/PoseidonT4.sol';

// Negative tests for PresenceTransfer(32,20) + PresencePool.transfer glue. Real Groth16 proofs via FFI.
contract TransferSoundness is Test {
  uint256 constant P = 21_888_242_871_839_275_222_246_405_745_257_275_088_548_364_400_416_034_343_698_204_186_575_808_495_617;
  uint256 constant TAG_PAYER = 0x706f702d7061796572;
  uint256 constant TAG_PRES = 0x706f702d70726573;
  uint256 constant DENOM = 0.001 ether;

  PresencePool pool;
  TransferVerifier tv;
  address attester = makeAddr('attester');
  address alice = makeAddr('alice');
  uint256[] stateLeaves;
  uint256[] presLeaves;
  uint256[] aspLeaves;
  uint256 label;
  uint256 constant NUL = 111;
  uint256 constant SEC = 222;
  uint256 constant BNUL = 31_337;
  uint256 constant BSEC = 4242;

  function setUp() public {
    vm.chainId(480);
    tv = new TransferVerifier();
    pool = new PresencePool(DENOM, attester, address(new WithdrawalVerifier()), address(new CommitmentVerifier()), address(tv));
    aspLeaves.push(pool.LABEL_TRANSFER());
    vm.deal(alice, 1 ether);
    uint256 pre = PoseidonT3.hash([NUL, SEC]);
    vm.prank(alice);
    stateLeaves.push(pool.deposit{value: DENOM}(pre));
    label = uint256(keccak256(abi.encodePacked(pool.SCOPE(), pool.nonce()))) % P;
    aspLeaves.push(label);
    // second depositor + an unrelated meeting, so neither tree is a single leaf
    address bob = makeAddr('bob'); vm.deal(bob, 1 ether);
    vm.prank(bob);
    stateLeaves.push(pool.deposit{value: DENOM}(PoseidonT3.hash([uint256(9), uint256(10)])));
    aspLeaves.push(uint256(keccak256(abi.encodePacked(pool.SCOPE(), pool.nonce()))) % P);
    _post(7);
  }

  function _leaf(uint256 value) internal view returns (uint256 leaf) {
    uint256 pc = PoseidonT4.hash([value, pool.LABEL_TRANSFER(), PoseidonT3.hash([BNUL, BSEC])]);
    leaf = PoseidonT4.hash([TAG_PRES, PoseidonT3.hash([TAG_PAYER, NUL]), pc]);
  }

  function _post(uint256 leaf) internal {
    vm.prank(attester);
    pool.postPresence(leaf);
    presLeaves.push(leaf);
  }

  function _proveT(uint256 value, uint256 ctx, string memory ov) internal returns (PresencePool.TransferProof memory p) {
    bytes memory args = abi.encode(DENOM, label, NUL, SEC, uint256(555), uint256(666), value, PoseidonT3.hash([BNUL, BSEC]), ctx,
      stateLeaves, presLeaves, _leaf(value));
    string[] memory cmd = new string[](5);
    cmd[0] = 'node'; cmd[1] = 'js/prove.mjs'; cmd[2] = 'transfer'; cmd[3] = vm.toString(args); cmd[4] = ov;
    (p.pA, p.pB, p.pC, p.pubSignals) = abi.decode(vm.ffi(cmd), (uint256[2], uint256[2][2], uint256[2], uint256[8]));
  }

  function _ok(uint256 value) internal returns (PresencePool.TransferProof memory) {
    _post(_leaf(value));
    return _proveT(value, pool.TRANSFER_CONTEXT(), '{}');
  }

  function _cp(PresencePool.TransferProof memory p) internal pure returns (PresencePool.TransferProof memory q) {
    q.pA = p.pA; q.pB = p.pB; q.pC = p.pC;
    for (uint256 i; i < 8; i++) q.pubSignals[i] = p.pubSignals[i];
  }

  // --- baseline
  function test_good() public {
    PresencePool.TransferProof memory p = _ok(0.0004 ether);
    pool.transfer(p);
    vm.expectRevert(PresencePool.NullifierAlreadySpent.selector);
    pool.transfer(p);
  }

  // --- depth: circuit's LessEqThan(6) accepts actualDepth in [p-31, p-1] (state) / [p-43, p-1] (presence).
  // The proof is VALID; only the contract bound stops it. (Depth does not feed the root, so this is hygiene, not theft.)
  function test_stateDepthAlias_validProof_contractRejects() public {
    _post(_leaf(0.0004 ether));
    PresencePool.TransferProof memory p = _proveT(0.0004 ether, pool.TRANSFER_CONTEXT(), string.concat('{"stateTreeDepth":"', vm.toString(P - 1), '"}'));
    assertEq(p.pubSignals[4], P - 1);
    assertTrue(tv.verifyProof(p.pA, p.pB, p.pC, p.pubSignals), 'verifier accepts aliased depth');
    vm.expectRevert(PresencePool.InvalidTreeDepth.selector);
    pool.transfer(p);
  }

  function test_presenceDepthAlias_validProof_contractRejects() public {
    _post(_leaf(0.0004 ether));
    PresencePool.TransferProof memory p = _proveT(0.0004 ether, pool.TRANSFER_CONTEXT(), string.concat('{"presenceTreeDepth":"', vm.toString(P - 43), '"}'));
    assertTrue(tv.verifyProof(p.pA, p.pB, p.pC, p.pubSignals));
    vm.expectRevert(PresencePool.InvalidTreeDepth.selector);
    pool.transfer(p);
  }

  // depth lie inside range: proof valid AND accepted (actualDepth is unused by the root computation)
  function test_depthLieInRange_isHarmless() public {
    _post(_leaf(0.0004 ether));
    PresencePool.TransferProof memory p = _proveT(0.0004 ether, pool.TRANSFER_CONTEXT(), '{"stateTreeDepth":"17","presenceTreeDepth":"0"}');
    pool.transfer(p); // same nullifier/commitments as an honest proof, so no extra power
  }

  // --- public signals >= p (aliasing an existing nullifier to a new mapping key)
  function test_pubSignalPlusP_rejected() public {
    PresencePool.TransferProof memory p = _ok(0.0004 ether);
    pool.transfer(p);
    for (uint256 i = 0; i < 3; i++) {
      PresencePool.TransferProof memory q = _cp(p);
      q.pubSignals[i] = p.pubSignals[i] + P;
      vm.expectRevert(PresencePool.InvalidProof.selector);
      pool.transfer(q);
    }
  }

  function test_rootPlusP_rejected() public {
    PresencePool.TransferProof memory p = _ok(0.0004 ether);
    PresencePool.TransferProof memory q = _cp(p);
    q.pubSignals[3] = p.pubSignals[3] + P;
    vm.expectRevert(PresencePool.UnknownStateRoot.selector);
    pool.transfer(q);
    q = _cp(p); q.pubSignals[5] = p.pubSignals[5] + P;
    vm.expectRevert(PresencePool.UnknownPresenceRoot.selector);
    pool.transfer(q);
  }

  // --- output swap / tamper
  function test_swapOutputs_rejected() public {
    PresencePool.TransferProof memory p = _ok(0.0004 ether);
    (p.pubSignals[1], p.pubSignals[2]) = (p.pubSignals[2], p.pubSignals[1]);
    vm.expectRevert(PresencePool.InvalidProof.selector);
    pool.transfer(p);
  }

  // --- context
  function test_wrongContext_rejected() public {
    _post(_leaf(0.0004 ether));
    PresencePool.TransferProof memory p = _proveT(0.0004 ether, 42, '{}');
    vm.expectRevert(PresencePool.ContextMismatch.selector);
    pool.transfer(p);
  }

  // --- roots
  function test_unknownPresenceRoot_rejected() public {
    PresencePool.TransferProof memory p = _ok(0.0004 ether);
    p.pubSignals[5] = 12345;
    vm.expectRevert(PresencePool.UnknownPresenceRoot.selector);
    pool.transfer(p);
  }

  function test_stateRootAsPresenceRoot_rejected() public {
    PresencePool.TransferProof memory p = _ok(0.0004 ether);
    p.pubSignals[5] = pool.currentRoot();
    vm.expectRevert(PresencePool.UnknownPresenceRoot.selector);
    pool.transfer(p);
  }

  // --- zero value: CURRENT circuit accepts it. Documents the policy gap; flip to expectRevert once IsZero is added.
  function test_zeroValueTransfer_currentlyAccepted() public {
    PresencePool.TransferProof memory p = _ok(0);
    pool.transfer(p);
    assertEq(address(pool).balance, 2 * DENOM);
  }

  // --- cross-circuit double spend: transfer, then 0xbow withdraw of the same input note
  function test_transferThenWithdrawSameNote_rejected() public {
    PresencePool.TransferProof memory p = _ok(0.0004 ether);
    pool.transfer(p);
    stateLeaves.push(p.pubSignals[1]);
    stateLeaves.push(p.pubSignals[2]);
    PresencePool.Withdrawal memory w = PresencePool.Withdrawal(alice, '');
    uint256 ctx = uint256(keccak256(abi.encode(w, pool.SCOPE()))) % P;
    bytes memory args = abi.encode(DENOM, label, NUL, SEC, uint256(777), uint256(888), DENOM, ctx, stateLeaves, aspLeaves);
    string[] memory cmd = new string[](4);
    cmd[0] = 'node'; cmd[1] = 'js/prove.mjs'; cmd[2] = 'withdraw'; cmd[3] = vm.toString(args);
    PresencePool.WithdrawProof memory wp;
    (wp.pA, wp.pB, wp.pC, wp.pubSignals) = abi.decode(vm.ffi(cmd), (uint256[2], uint256[2][2], uint256[2], uint256[8]));
    assertEq(wp.pubSignals[1], p.pubSignals[0], 'same nullifierHash across circuits');
    vm.prank(alice);
    vm.expectRevert(PresencePool.NullifierAlreadySpent.selector);
    pool.withdraw(w, wp);
  }
}
