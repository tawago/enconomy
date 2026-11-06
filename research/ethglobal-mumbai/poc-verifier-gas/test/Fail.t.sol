// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import {Fx} from "./Groth16Fixtures.sol";
/// How much gas a failing BN254 precompile call eats, per fork.
contract FailTest {
    event log_named_uint(string key, uint256 val);
    function test_pairing_offcurve_raw() public {
        uint256[2][2] memory b = Fx.b();
        bytes memory inp = abi.encodePacked(uint256(1), uint256(3), b[0][0], b[0][1], b[1][0], b[1][1]); // (1,3) off-curve
        uint256 g = gasleft();
        (bool ok,) = address(8).staticcall{gas: 500_000}(inp);
        emit log_named_uint("pairing(off-curve) gas used, 500k cap", g - gasleft());
        require(!ok, "should fail");
        g = gasleft();
        (ok,) = address(7).staticcall{gas: 500_000}(abi.encode(uint256(1), uint256(3), uint256(5)));
        emit log_named_uint("ecMul(off-curve) gas used, 500k cap", g - gasleft());
        require(!ok, "should fail");
    }
}
