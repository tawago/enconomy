// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

// No forge-std on purpose: plain require + DSTest-style log events (forge decodes them).
import {Fx} from "./Groth16Fixtures.sol";
import {Groth16N1} from "../src/Groth16N1.sol";
import {Groth16N2} from "../src/Groth16N2.sol";
import {Groth16N4} from "../src/Groth16N4.sol";
import {Groth16N8} from "../src/Groth16N8.sol";
import {Groth16N16} from "../src/Groth16N16.sol";
import {Groth16N32} from "../src/Groth16N32.sol";

contract GasTest {
    event log_named_uint(string key, uint256 val);

    function test_groth16_n1() public {
        Groth16N1 v = new Groth16N1();
        (uint256[2] memory a, uint256[2] memory c, uint256[1] memory x) = Fx.n1();
        uint256 g = gasleft();
        bool ok = v.verifyProof(a, Fx.b(), c, x);
        emit log_named_uint("groth16 n=1 call gas (incl. CALL+calldata copy)", g - gasleft());
        require(ok, "valid proof rejected");
        x[0] ^= 1;
        require(!v.verifyProof(a, Fx.b(), c, x), "tampered accepted");
    }

    function test_groth16_n2() public {
        Groth16N2 v = new Groth16N2();
        (uint256[2] memory a, uint256[2] memory c, uint256[2] memory x) = Fx.n2();
        uint256 g = gasleft();
        bool ok = v.verifyProof(a, Fx.b(), c, x);
        emit log_named_uint("groth16 n=2 call gas", g - gasleft());
        require(ok, "valid proof rejected");
    }

    function test_groth16_n4() public {
        Groth16N4 v = new Groth16N4();
        (uint256[2] memory a, uint256[2] memory c, uint256[4] memory x) = Fx.n4();
        uint256 g = gasleft();
        bool ok = v.verifyProof(a, Fx.b(), c, x);
        emit log_named_uint("groth16 n=4 call gas", g - gasleft());
        require(ok, "valid proof rejected");
        require(!v.verifyProof(a, Fx.b(), a, x), "wrong C (valid point) accepted");
    }

    /// Off-curve C: the pairing precompile fails and eats all gas it was given (staticcall(gas(), 8, ...)).
    /// Forward a 1M cap so the test shows the burn without eating the block.
    function test_groth16_offcurve_burns_forwarded_gas() public {
        Groth16N4 v = new Groth16N4();
        (uint256[2] memory a, uint256[2] memory c, uint256[4] memory x) = Fx.n4();
        c[0] ^= 1;
        uint256 g = gasleft();
        (bool ok, bytes memory out) = address(v).call{gas: 1_000_000}(abi.encodeCall(v.verifyProof, (a, Fx.b(), c, x)));
        emit log_named_uint("off-curve C, gas used of 1M cap", g - gasleft());
        require(ok && !abi.decode(out, (bool)), "should return false");
    }

    function test_groth16_n8() public {
        Groth16N8 v = new Groth16N8();
        (uint256[2] memory a, uint256[2] memory c, uint256[8] memory x) = Fx.n8();
        uint256 g = gasleft();
        bool ok = v.verifyProof(a, Fx.b(), c, x);
        emit log_named_uint("groth16 n=8 call gas", g - gasleft());
        require(ok, "valid proof rejected");
    }

    function test_groth16_n16() public {
        Groth16N16 v = new Groth16N16();
        (uint256[2] memory a, uint256[2] memory c, uint256[16] memory x) = Fx.n16();
        uint256 g = gasleft();
        bool ok = v.verifyProof(a, Fx.b(), c, x);
        emit log_named_uint("groth16 n=16 call gas", g - gasleft());
        require(ok, "valid proof rejected");
    }

    function test_groth16_n32() public {
        Groth16N32 v = new Groth16N32();
        (uint256[2] memory a, uint256[2] memory c, uint256[32] memory x) = Fx.n32();
        uint256 g = gasleft();
        bool ok = v.verifyProof(a, Fx.b(), c, x);
        emit log_named_uint("groth16 n=32 call gas", g - gasleft());
        require(ok, "valid proof rejected");
    }

    /// EIP-7951 P256VERIFY at 0x100. Public test vector copied from contracts/test/PopCtx.t.sol (no key material).
    function test_p256_precompile() public {
        bytes memory inp = abi.encode(
            bytes32(0xe0005ceaee59d61859d4a867fc15897bbfeca13f9c737ebb6959cdde31f2b25d),
            bytes32(0x76a33345d9c2e60b4cdab2063ca4f19855b058ba269a1408f9420dcbd7cfe842),
            bytes32(0x9c52547d6bf37b06a7614c1cd6ede11f15a7fe439aeab9cedd478b652e661fba),
            uint256(0x33722147e2b1ac751bcda5630b9799c3323a5d85dfe902183bce4640e52ae125),
            uint256(0x03d7566a889ae6b64bcebd5e74c61458ce9cd27a640e4fc7df67cbacfb5eebf4)
        );
        uint256 g = gasleft();
        (bool ok, bytes memory out) = address(0x100).staticcall(inp);
        uint256 used = g - gasleft();
        emit log_named_uint("P256VERIFY staticcall gas (incl. call overhead)", used);
        require(ok && out.length == 32 && abi.decode(out, (uint256)) == 1, "p256 failed");
    }

    /// Raw pairing precompile cost for k pairs (repeat the valid n=1 check's 4 pairs only to time the call).
    function test_bn254_pairing_raw() public {
        // e(G1,G2) * e(-G1,G2) = 1, repeated
        uint256[2][2] memory b = Fx.b();
        uint256 q = 21888242871839275222246405745257275088696311157297823662689037894645226208583;
        for (uint256 k = 2; k <= 4; k++) {
            bytes memory inp;
            for (uint256 i; i < k; i++) {
                uint256 y = (i % 2 == 0) ? 2 : q - 2;
                if (k % 2 == 1 && i == k - 1) y = 2; // odd k: product != 1, cost is the same
                inp = abi.encodePacked(inp, uint256(1), y, b[0][0], b[0][1], b[1][0], b[1][1]);
            }
            uint256 g = gasleft();
            (bool ok,) = address(8).staticcall(inp);
            uint256 used = g - gasleft();
            require(ok, "pairing call failed");
            emit log_named_uint(k == 2 ? "pairing k=2" : k == 3 ? "pairing k=3" : "pairing k=4", used);
        }
    }
}
