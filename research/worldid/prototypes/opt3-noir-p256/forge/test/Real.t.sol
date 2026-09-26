// SPDX-License-Identifier: MIT
pragma solidity ^0.8.27;
import {HalfVerifier} from "../src/HalfVerifier.sol";
import {PairVerifier} from "../src/PairVerifier.sol";
import {PopGuard, IHonk} from "../src/PopGuard.sol";

interface Vm { function readFileBinary(string calldata) external view returns (bytes memory); function warp(uint256) external;
  function envString(string calldata) external view returns (string memory); }

contract RealTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    HalfVerifier hv; PairVerifier pv;
    bytes32 constant CTX = bytes32(uint256(0x0123456789abcdef));

    function pubs(string memory p) internal view returns (bytes32[] memory o) {
        bytes memory b = vm.readFileBinary(p); o = new bytes32[](b.length / 32);
        for (uint i; i < o.length; i++) { bytes32 w; assembly { w := mload(add(add(b, 32), mul(i, 32))) } o[i] = w; }
    }
    function dir() internal view returns (string memory) { return vm.envString("RDIR"); }
    function setUp() public { hv = new HalfVerifier(); pv = new PairVerifier(); }
    function guard(bytes32[] memory a) internal returns (PopGuard) {
        bytes32[4] memory iss = [a[0], a[1], a[2], a[3]];
        vm.warp(uint256(a[4]) + 1);
        return new PopGuard(IHonk(address(hv)), IHonk(address(pv)), iss, a[5]);
    }
    function test_halfA() public { string memory d = dir();
        uint g = gasleft(); bool ok = hv.verify(vm.readFileBinary(string.concat(d, "/half/r_half/proof")), pubs(string.concat(d, "/half/r_half/public_inputs")));
        require(ok); emit log_named_uint("verify half A", g - gasleft()); }
    function test_pair() public { string memory d = dir();
        uint g = gasleft(); bool ok = pv.verify(vm.readFileBinary(string.concat(d, "/pair/r_out/proof")), pubs(string.concat(d, "/pair/r_out/public_inputs")));
        require(ok); emit log_named_uint("verify pair", g - gasleft()); }
    function test_checkHalves() public { string memory d = dir();
        bytes32[] memory a = pubs(string.concat(d, "/half/r_half/public_inputs")); bytes32[] memory b = pubs(string.concat(d, "/half/r_halfB/public_inputs"));
        PopGuard G = guard(a);
        uint g = gasleft();
        G.checkHalves(vm.readFileBinary(string.concat(d, "/half/r_half/proof")), a, vm.readFileBinary(string.concat(d, "/half/r_halfB/proof")), b, CTX);
        emit log_named_uint("checkHalves", g - gasleft()); }
    function test_checkPair() public { string memory d = dir();
        bytes32[] memory p = pubs(string.concat(d, "/pair/r_out/public_inputs"));
        PopGuard G = guard(p);
        uint g = gasleft();
        G.checkPair(vm.readFileBinary(string.concat(d, "/pair/r_out/proof")), p, CTX);
        emit log_named_uint("checkPair", g - gasleft()); }
    event log_named_uint(string, uint);
}
