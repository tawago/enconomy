// SPDX-License-Identifier: MIT
pragma solidity ^0.8.27;
contract Probe {
    function pair0() external view returns (uint256 used, bool ok) {
        uint256 g = gasleft(); (ok,) = address(8).staticcall(""); used = g - gasleft();
    }
    function modexpish() external view returns (uint256 used, bool ok) {
        uint256 g = gasleft(); (ok,) = address(0x100).staticcall(new bytes(160)); used = g - gasleft();
    }
}
interface IG16 { function verifyProof(uint[2] calldata, uint[2][2] calldata, uint[2] calldata, uint[6] calldata) external view returns (bool); }
contract G16Probe {
    function m(IG16 v, uint[2] calldata a, uint[2][2] calldata b, uint[2] calldata c, uint[6] calldata p) external view returns (uint256 used, bool ok) {
        uint256 g = gasleft(); ok = v.verifyProof(a, b, c, p); used = g - gasleft();
    }
}
interface IH { function verify(bytes calldata, bytes32[] calldata) external view returns (bool); }
contract HProbe {
    function m(IH v, bytes calldata pr, bytes32[] calldata p) external view returns (uint256 used, bool ok) {
        uint256 g = gasleft(); ok = v.verify(pr, p); used = g - gasleft();
    }
}
