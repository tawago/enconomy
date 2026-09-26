// SPDX-License-Identifier: MIT
pragma solidity ^0.8.27;
import {PhoneVerifier} from "../src/PhoneVerifier.sol";

interface Vm {
    function readFileBinary(string calldata) external view returns (bytes memory);
    function envString(string calldata) external view returns (string memory);
}

// Execution gas of verify() on the real option A proof (gasleft around the call). RDIR = proof dir.
contract GasTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    PhoneVerifier pv;

    function pubs(string memory p) internal view returns (bytes32[] memory o) {
        bytes memory b = vm.readFileBinary(p);
        o = new bytes32[](b.length / 32);
        for (uint256 i; i < o.length; i++) {
            bytes32 w;
            assembly { w := mload(add(add(b, 32), mul(i, 32))) }
            o[i] = w;
        }
    }

    function setUp() public { pv = new PhoneVerifier(); }

    function test_phone() public {
        string memory d = vm.envString("RDIR");
        bytes memory proof = vm.readFileBinary(string.concat(d, "/proof"));
        bytes32[] memory pi = pubs(string.concat(d, "/public_inputs"));
        uint256 g = gasleft();
        bool ok = pv.verify(proof, pi);
        uint256 used = g - gasleft();
        require(ok, "verify failed");
        emit log_named_uint("verify phone (execution gas)", used);
        emit log_named_uint("proof bytes", proof.length);
        emit log_named_uint("public inputs", pi.length);
    }

    function test_phone_tampered_public_input() public {
        string memory d = vm.envString("RDIR");
        bytes memory proof = vm.readFileBinary(string.concat(d, "/proof"));
        bytes32[] memory pi = pubs(string.concat(d, "/public_inputs"));
        pi[pi.length - 1] = bytes32(uint256(pi[pi.length - 1]) ^ 1); // flip halfCommit
        try pv.verify(proof, pi) returns (bool ok) { require(!ok, "tampered accepted"); } catch {}
    }

    event log_named_uint(string, uint256);
}
