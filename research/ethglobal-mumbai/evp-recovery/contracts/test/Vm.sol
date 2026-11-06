// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// The few forge cheatcodes these tests use (no forge-std in this project). Copied from poc-validation-rules.
interface Vm {
    struct Gas {
        uint64 gasLimit;
        uint64 gasTotalUsed;
        uint64 gasMemoryUsed;
        int64 gasRefunded;
        uint64 gasRemaining;
    }

    function prank(address) external;
    function expectRevert() external;
    function expectRevert(bytes4) external;
    function signP256(uint256 privateKey, bytes32 digest) external pure returns (bytes32 r, bytes32 s);
    function publicKeyP256(uint256 privateKey) external pure returns (uint256 x, uint256 y);
    function expectRevert(bytes calldata) external;
    function warp(uint256) external;
    function etch(address, bytes calldata) external;
    function cool(address) external;
    function lastCallGas() external view returns (Gas memory);
    function record() external;
    function accesses(address) external returns (bytes32[] memory reads, bytes32[] memory writes);
    function chainId(uint256) external;
    function sign(uint256 privateKey, bytes32 digest) external pure returns (uint8 v, bytes32 r, bytes32 s);
    function addr(uint256 privateKey) external pure returns (address);
    function store(address target, bytes32 slot, bytes32 value) external;
    function deal(address who, uint256 amount) external;
    function load(address target, bytes32 slot) external view returns (bytes32);
    function expectEmit() external;
    function readFile(string calldata path) external view returns (string memory);
    function parseJsonBytes32(string calldata json, string calldata key) external pure returns (bytes32);
    function parseJsonBytes(string calldata json, string calldata key) external pure returns (bytes memory);
    function parseJsonUint(string calldata json, string calldata key) external pure returns (uint256);
    function parseJsonAddress(string calldata json, string calldata key) external pure returns (address);
}

abstract contract TestBase {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address internal constant EP = address(0xaa);

    event log_named_uint(string key, uint256 val);
    event log_named_string(string key, string val);

    function _word(bytes memory b, uint256 off) internal pure returns (bytes32 w) {
        bytes memory padded = bytes.concat(b, new bytes(32));
        assembly ("memory-safe") {
            w := mload(add(add(padded, 32), off))
        }
    }
}
