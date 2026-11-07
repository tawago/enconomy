// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {PairNamedVerifier} from "../src/PairNamedVerifier.sol";
import {PairRefVerifier} from "../src/PairRefVerifier.sol";

interface Vm {
    function readFileBinary(string calldata path) external view returns (bytes memory);
}

interface IV {
    function verify(bytes calldata proof, bytes32[] calldata pub) external view returns (bool);
}

/// Real throwaway proofs through the bb verifiers. pair_ref is the frozen pair, kept as the same-tool baseline.
contract PairNamedGasTest {
    event log_named_uint(string key, uint256 val);
    event log_named_bytes(string key, bytes val);

    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    IV named;
    IV ref;

    function setUp() public {
        named = IV(address(new PairNamedVerifier()));
        ref = IV(address(new PairRefVerifier()));
    }

    function _load(string memory d) internal view returns (bytes memory proof, bytes32[] memory pub) {
        proof = vm.readFileBinary(string.concat("fixtures/", d, "/proof"));
        bytes memory raw = vm.readFileBinary(string.concat("fixtures/", d, "/public_inputs"));
        pub = new bytes32[](raw.length / 32);
        for (uint256 i; i < pub.length; i++) {
            bytes32 w;
            assembly {
                w := mload(add(add(raw, 32), mul(i, 32)))
            }
            pub[i] = w;
        }
    }

    function _measure(IV v, string memory d) internal {
        (bytes memory proof, bytes32[] memory pub) = _load(d);
        uint256 g = gasleft();
        bool ok = v.verify(proof, pub);
        g -= gasleft();
        require(ok, "real proof rejected");
        emit log_named_uint("public inputs", pub.length);
        emit log_named_uint("proof bytes", proof.length);
        emit log_named_uint("gasleft delta", g);
    }

    function test_evp_real_proof() public {
        _measure(named, "named");
    }

    function test_ref_real_proof() public {
        _measure(ref, "ref");
    }

    function test_evp_tampered_public_input_rejected() public {
        (bytes memory proof, bytes32[] memory pub) = _load("named");
        require(pub.length == 11, "want 11");
        for (uint256 i; i < 11; i++) {
            bytes32 keep = pub[i];
            pub[i] = keep ^ bytes32(uint256(1));
            try named.verify(proof, pub) returns (bool ok) {
                require(!ok, "tampered input accepted");
                emit log_named_uint("returned false at", i);
            } catch (bytes memory err) {
                emit log_named_uint("reverted at", i);
                emit log_named_bytes("error", err);
            }
            pub[i] = keep;
        }
    }
}
