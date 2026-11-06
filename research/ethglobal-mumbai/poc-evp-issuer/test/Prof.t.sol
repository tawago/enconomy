// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "forge-std/Test.sol";
import {EvpVerifier} from "../src/EvpVerifier.sol";
import {Fixture} from "./Fixture.sol";
contract H is EvpVerifier {
    constructor() EvpVerifier(1, 1, "", "", "", 600) {}
    function dec(bytes memory p) external view returns (uint256 g) { g = gasleft(); _decode(p, 0, p.length); g -= gasleft(); }
    function hx(bytes32 h) external view returns (uint256 g) { g = gasleft(); _hex(h); g -= gasleft(); }
    function sh(bytes memory p) external view returns (uint256 g) { g = gasleft(); _sha256Slice(p, 0, p.length); g -= gasleft(); }
    function cp(bytes calldata p) external view returns (uint256 g) { g = gasleft(); bytes memory t = p; g -= gasleft(); t; }
}
contract Prof is Test {
    function test_prof() public {
        H h = new H();
        bytes memory t = Fixture.TOKEN;
        bytes memory s = new bytes(300); for (uint i; i<300; i++) s[i] = "A";
        emit log_named_uint("decode 300 chars", h.dec(s));
        for (uint L = 32; L <= 640; L *= 2) { bytes memory q = new bytes(L); for (uint i; i<L; i++) q[i] = "A"; emit log_named_uint("decode L", L); emit log_named_uint("  gas", h.dec(q)); }
        emit log_named_uint("hex 32", h.hx(keccak256("a")));
        emit log_named_uint("sha256 861", h.sh(t));
        emit log_named_uint("copy 861", h.cp(t));
    }
}
