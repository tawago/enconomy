// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
import {Test} from "forge-std/Test.sol";
import {TransferVerifier} from "../src/TransferVerifier.sol";
import {PoolGate, ITransferVerifier} from "../src/PoolGate.sol";
contract FailPathTest is Test {
  PoolGate g; address attester = address(0xA77E);
  uint256 constant STATE_ROOT = 10355916116637146968684017284306093031548937770732436479785057476310854782972;
  uint256 constant PRES_ROOT  = 8123862404048223229432035290263267852744263573020889325278241819263984023933;
  function setUp() public {
    if (block.chainid != 480) emit log("WARN not on 480 fork");
    g = new PoolGate(ITransferVerifier(address(new TransferVerifier())), attester, 42, STATE_ROOT);
  }
  function pf() internal pure returns (PoolGate.TransferProof memory t) {
    t.pA=[uint256(0x1c320c37d61a39517b4dae1147fcad53c6239f1820f3c64fe904dde80a0ec657),uint256(0x17b7fbbc3d788aa1930f5bb5a577138d4e4eba89b6630beb17a7a364a993c566)]; t.pB=[[uint256(0x2cb4c295ad4816236aa6e66453857fd40a819571c401f6970c7d3e77eb0f4e8d),uint256(0x104346efddad6e256c069eaefc4e2a11bc902035912ea96d8bf5619630967c07)],[uint256(0x1098020b63686cf6b47fb1e49f1f106feb4c0def1a2246951fa264bd7ba0d20e),uint256(0x1dbda6d5969a1f9e50aff32e442554a4b960dab7a6a48957a75f5397d2886ac6)]]; t.pC=[uint256(0x1102f705a8b2894985c253cacbf49798f0de8974eb3a06303e0cd43c516e161f),uint256(0x1d7f73d82038a10a59f98f83fe4b512ceea96eef39483cbf68a42c674decbed4)];
    t.pubSignals=[uint256(0x126191e3989103e8ec96310a454135e2fd7cefd642eac92aef8f801aa2dc7579),uint256(0x0e6e61290a4ec5b3bd2a8a7b2f12f179c5dea050c13365680ca16dd0ea53bc33),uint256(0x0efb6a1dfc688152a20bb238b9452a073c8d521c763b2bc9fbe66a5bb197fcfa),uint256(0x16e53da58eef0b12d46981841baec89d7d0b9f5ac902f1b6333b25525e83cffc),uint256(0x0000000000000000000000000000000000000000000000000000000000000002),uint256(0x11f5f173f6def7a7710c87251cbb0528736a235bdd57dc07686f2bafc255397d),uint256(0x0000000000000000000000000000000000000000000000000000000000000002),uint256(0x000000000000000000000000000000000000000000000000000000000000002a)];
  }
  // F1: meeting never attested (NOT_NEAR). Wallet proves against its own local presence tree -> proof is valid, root unknown.
  function test_F1_unknownPresenceRoot() public {
    assertTrue(TransferVerifier(address(g.V())).verifyProof(pf().pA,pf().pB,pf().pC,pf().pubSignals)); // proof itself is fine
    vm.expectRevert(abi.encodeWithSelector(PoolGate.UnknownPresenceRoot.selector, PRES_ROOT));
    g.transfer(pf());
  }
  // success after attester posts the leaf/root
  function test_S_afterPresence() public {
    vm.prank(attester); g.postPresenceRoot(1, PRES_ROOT);
    uint gs=gasleft(); g.transfer(pf()); emit log_named_uint("transfer_gas", gs-gasleft());
  }
  // F2: meeting attested, but wallet tries to pay a different payee note (edited payeeCommitment)
  function test_F2_wrongPayee() public {
    vm.prank(attester); g.postPresenceRoot(1, PRES_ROOT);
    PoolGate.TransferProof memory t = pf(); t.pubSignals[2] += 1;
    vm.expectRevert(PoolGate.InvalidProof.selector); g.transfer(t);
  }
  // F3: replay of a spent ticket
  function test_F3_replay() public {
    vm.prank(attester); g.postPresenceRoot(1, PRES_ROOT);
    g.transfer(pf());
    vm.expectRevert(abi.encodeWithSelector(PoolGate.NullifierAlreadySpent.selector, uint256(8314022328977600502360236309892451910870238061452047842843754277126098679161)));
    g.transfer(pf());
  }
  function test_F4_notAttester() public {
    vm.expectRevert(PoolGate.NotAttester.selector); g.postPresenceRoot(1, PRES_ROOT);
  }
  function test_selectors() public {
    emit log_named_bytes32("UnknownPresenceRoot", bytes32(PoolGate.UnknownPresenceRoot.selector));
    emit log_named_bytes32("InvalidProof", bytes32(PoolGate.InvalidProof.selector));
    emit log_named_bytes32("NullifierAlreadySpent", bytes32(PoolGate.NullifierAlreadySpent.selector));
  }
}
