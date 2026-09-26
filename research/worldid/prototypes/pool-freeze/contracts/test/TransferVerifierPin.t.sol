// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;
import {Test} from "forge-std/Test.sol";
import {TransferVerifier} from "../src/TransferVerifier.sol";

contract TransferVerifierPin is Test {
  struct Fx { uint256[2] a; uint256[2][2] b; uint256[2] c; uint256[8] pub; }
  function _fx() internal view returns (Fx memory f) {
    string memory j = vm.readFile("test/fixture.json");
    uint256[] memory a = vm.parseJsonUintArray(j, ".a");
    uint256[] memory b0 = vm.parseJsonUintArray(j, ".b[0]");
    uint256[] memory b1 = vm.parseJsonUintArray(j, ".b[1]");
    uint256[] memory c = vm.parseJsonUintArray(j, ".c");
    uint256[] memory p = vm.parseJsonUintArray(j, ".pub");
    f.a = [a[0], a[1]]; f.b = [[b0[0], b0[1]], [b1[0], b1[1]]]; f.c = [c[0], c[1]];
    for (uint i; i < 8; i++) f.pub[i] = p[i];
  }
  // proof made by the committed zkey+wasm is accepted: stronger than IC0 equality alone
  function test_canonicalProofAccepted() public {
    TransferVerifier v = new TransferVerifier();
    Fx memory f = _fx();
    assertTrue(v.verifyProof(f.a, f.b, f.c, f.pub));
    f.pub[2] ^= 1; // payeeCommitment
    assertFalse(v.verifyProof(f.a, f.b, f.c, f.pub));
  }
  // IC0 in the .sol source equals vkey.IC[0] (the 0xbow-style pin)
  function test_ic0MatchesVkey() public view {
    string memory src = vm.readFile("src/TransferVerifier.sol");
    string memory j = vm.readFile("test/fixture.json");
    string memory want = string.concat("IC0x = ", vm.toString(vm.parseJsonUint(j, ".ic0x")), ";");
    assertTrue(vm.indexOf(src, want) != type(uint256).max, "IC0x mismatch");
  }
  // deployed bytecode == compiled bytecode (run with --fork-url and TRANSFER_VERIFIER set)
  function test_deployedMatches() public {
    address d = vm.envOr("TRANSFER_VERIFIER", address(0));
    if (d == address(0)) return;
    assertEq(keccak256(d.code), keccak256(address(new TransferVerifier()).code));
  }
}
