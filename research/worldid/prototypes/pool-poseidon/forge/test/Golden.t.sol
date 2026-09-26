// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import "forge-std/Test.sol";
import {PoseidonT2} from "poseidon-solidity/PoseidonT2.sol";
import {PoseidonT3} from "poseidon-solidity/PoseidonT3.sol";
import {PoseidonT4} from "poseidon-solidity/PoseidonT4.sol";
import {InternalLeanIMT, LeanIMTData} from "leanimt/InternalLeanIMT.sol";

contract Golden is Test {
    using InternalLeanIMT for LeanIMTData;
    LeanIMTData tree;

    function h(uint256[] memory x) internal pure returns (uint256) {
        if (x.length == 1) return PoseidonT2.hash([x[0]]);
        if (x.length == 2) return PoseidonT3.hash([x[0], x[1]]);
        return PoseidonT4.hash([x[0], x[1], x[2]]);
    }

    function test_golden() public {
        string memory j = vm.readFile("../golden.json");
        uint256 n = 18;
        for (uint256 i = 0; i < n; i++) {
            string memory k = string.concat(".cases[", vm.toString(i), "]");
            uint256[] memory inp = vm.parseJsonUintArray(j, string.concat(k, ".in"));
            uint256 out = vm.parseJsonUint(j, string.concat(k, ".out"));
            assertEq(h(inp), out, vm.parseJsonString(j, string.concat(k, ".name")));
        }
    }

    function test_leanimt() public {
        string memory j = vm.readFile("../golden.json");
        uint256[] memory leaves = vm.parseJsonUintArray(j, ".leanimt.leaves");
        uint256[] memory roots = vm.parseJsonUintArray(j, ".leanimt.rootsAfterEachInsert");
        for (uint256 i = 0; i < leaves.length; i++) {
            tree._insert(leaves[i]);
            assertEq(tree._root(), roots[i]);
        }
    }

    function test_gas() public {
        uint256 g0 = gasleft(); PoseidonT3.hash([uint256(1), 2]); uint256 g1 = gasleft();
        PoseidonT4.hash([uint256(1), 2, 3]); uint256 g2 = gasleft();
        emit log_named_uint("T3 gas", g0 - g1); emit log_named_uint("T4 gas", g1 - g2);
    }
}
