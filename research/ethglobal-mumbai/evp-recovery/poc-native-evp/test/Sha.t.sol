// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {Fixture} from "./Fixture.sol";
import {YulSha} from "./YulSha.sol";

/// Correctness of the pure-Yul SHA-256 against the 0x02 precompile (precompile used ONLY as the test oracle),
/// and gas of the raw hasher calls.
contract ShaTest is Test {
    address s;

    function setUp() public {
        string memory v = vm.envOr("SHA_VARIANT", string("noopt"));
        s = YulSha.deploy(v);
        console.log("variant", v, "runtime bytes", s.code.length);
    }

    function _offs() internal pure returns (uint256 d2, uint256 t, uint256 k2) {
        uint256 o = Fixture.OFFS;
        d2 = (o >> 16) & 0xffff; t = (o >> 32) & 0xffff; k2 = (o >> 64) & 0xffff;
    }

    function _cut(bytes memory b, uint256 a, uint256 e) internal pure returns (bytes memory c) {
        c = new bytes(e - a);
        for (uint256 i = a; i < e; i++) c[i - a] = b[i];
    }

    function test_vectors() public view {
        assertEq(YulSha.plain(s, ""), sha256(""));
        assertEq(YulSha.plain(s, "abc"), sha256("abc"));
        assertEq(YulSha.plain(s, "abc"), 0xba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad);
        bytes memory b = new bytes(260);
        for (uint256 i = 0; i < 260; i++) b[i] = bytes1(uint8(i * 7 + 3));
        for (uint256 n = 0; n <= 260; n++) assertEq(YulSha.plain(s, _cut(b, 0, n)), sha256(_cut(b, 0, n)));
    }

    function test_fuzz(bytes memory b) public view {
        vm.assume(b.length < 3000);
        assertEq(YulSha.plain(s, b), sha256(b));
    }

    function _one(uint256 mode, bool sd) internal view {
        bytes memory tok = Fixture.TOKEN;
        (uint256 d2, uint256 t, uint256 k2) = _offs();
        (bytes32 e, bytes32 k, bytes32 x) = YulSha.evp(s, mode, sd, tok, d2, t, k2);
        assertEq(e, sha256(_cut(tok, 0, d2)));
        assertEq(k, sha256(_cut(tok, t + 1, k2)));
        assertEq(x, sd ? sha256(_cut(tok, 0, t + 1)) : bytes32(0));
    }

    function test_evp_digests_match() public view {
        _one(1, true); _one(1, false); _one(4, true); _one(4, false);
        assertEq(YulSha.plain(s, Fixture.TOKEN), sha256(Fixture.TOKEN));
    }

    /// gas of one STATICCALL to the hasher, measured from the caller: includes call + calldata + memory.
    /// The account is warm after the first call; the cold-access delta (2,500) is added in the README.
    function _g(bytes memory cd) internal view returns (uint256 used) {
        address a = s;
        uint256 g = gasleft();
        assembly ("memory-safe") { pop(staticcall(gas(), a, add(cd, 32), mload(cd), 0, 0)) }
        used = g - gasleft();
    }

    function test_gas() public view {
        bytes memory tok = Fixture.TOKEN;
        (uint256 d2, uint256 t, uint256 k2) = _offs();
        console.log("token bytes", tok.length);
        console.log("EVT signing input bytes", d2);
        console.log("KB signing input bytes", k2 - t - 1);
        console.log("sd_hash input bytes", t + 1);
        _g(abi.encodePacked(uint256(0), "")); // warm
        console.log("plain sha256('')              1 block ", _g(abi.encodePacked(uint256(0), "")));
        console.log("plain sha256(55 B)            1 block ", _g(abi.encodePacked(uint256(0), new bytes(55))));
        console.log("plain sha256(whole token)          ", _g(abi.encodePacked(uint256(0), tok)));
        console.log("plain sha256(KB input only)        ", _g(abi.encodePacked(uint256(0), _cut(tok, t + 1, k2))));
        console.log("plain sha256(EVT input only)       ", _g(abi.encodePacked(uint256(0), _cut(tok, 0, d2))));
        console.log("EVP 1-lane, EVT+KB (2 digests)     ", _g(abi.encodePacked(YulSha.hdr(1, false, d2, t, k2), tok)));
        console.log("EVP 1-lane, EVT+KB+sd_hash (3)     ", _g(abi.encodePacked(YulSha.hdr(1, true, d2, t, k2), tok)));
        console.log("EVP SWAR4, EVT+KB (2 digests)      ", _g(abi.encodePacked(YulSha.hdr(4, false, d2, t, k2), tok)));
        console.log("EVP SWAR4, EVT+KB+sd_hash (3)      ", _g(abi.encodePacked(YulSha.hdr(4, true, d2, t, k2), tok)));
    }
}
