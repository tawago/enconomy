// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import "forge-std/Test.sol";
import {PopSafeGuard} from "../src/PopSafeGuard.sol";
contract VectorTest is Test {
    function test_vector() public {
        PopSafeGuard g = new PopSafeGuard();
        bytes32 d = g.digest(480, 0x1111111111111111111111111111111111111111, bytes32(uint256(0x22)), bytes32(uint256(0x33)), bytes32(uint256(0x44)), bytes32(uint256(0x55)), 1790000000);
        console.logBytes32(d);
    }
}
