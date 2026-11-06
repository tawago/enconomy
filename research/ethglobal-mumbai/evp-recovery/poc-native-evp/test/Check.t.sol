// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {NativeEvpCheck} from "../src/NativeEvpCheck.sol";
import {Fixture} from "./Fixture.sol";
import {YulSha} from "./YulSha.sol";

contract CheckTest is Test {
    NativeEvpCheck[7] c; // [0] claims only, [1] 1-lane+sd, [2] 1-lane no sd, [3] SWAR+sd, [4] SWAR no sd
    address issuer;
    address kbSigner;
    address newKeySigner;
    uint256 deadline;

    function setUp() public {
        issuer = address(uint160(uint256(keccak256(abi.encodePacked(Fixture.ISSUER_X, Fixture.ISSUER_Y)))));
        newKeySigner = address(uint160(uint256(keccak256(Fixture.NEW_KEY))));
        kbSigner = vm.parseAddress(vm.readFile("test/kb-signer.txt"));
        deadline = Fixture.IAT + 600;
        address sha = YulSha.deploy(vm.envOr("SHA_VARIANT", string("noopt")));
        uint256[7] memory modes = [uint256(0), 1, 1, 4, 4, 2, 2];
        bool[7] memory sds = [false, true, false, true, false, true, false]; // claims-only has no sd digest to compare
        for (uint256 i = 0; i < 7; i++) {
            c[i] = new NativeEvpCheck(issuer, Fixture.EVT_HEADER_B64, Fixture.EMAIL, Fixture.AUD, 900, modes[i], sds[i], sha);
        }
    }

    function _sigs(bytes32 hEvt, bytes32 hKb) internal view returns (NativeEvpCheck.Sig[3] memory s) {
        s[0] = NativeEvpCheck.Sig(issuer, hEvt);
        s[1] = NativeEvpCheck.Sig(kbSigner, hKb);
        s[2] = NativeEvpCheck.Sig(newKeySigner, 0);
    }

    function _digests() internal pure returns (bytes32 hEvt, bytes32 hKb) {
        bytes memory tok = Fixture.TOKEN;
        uint256 o = Fixture.OFFS;
        uint256 d2 = (o >> 16) & 0xffff;
        uint256 t = (o >> 32) & 0xffff;
        uint256 k2 = (o >> 64) & 0xffff;
        hEvt = sha256(_cut(tok, 0, d2));
        hKb = sha256(_cut(tok, t + 1, k2));
    }

    function _cut(bytes memory b, uint256 a, uint256 e) internal pure returns (bytes memory r) {
        r = new bytes(e - a);
        for (uint256 i = a; i < e; i++) r[i - a] = b[i];
    }

    function test_gas_variants() public {
        (bytes32 hEvt, bytes32 hKb) = _digests();
        NativeEvpCheck.Sig[3] memory s = _sigs(hEvt, hKb);
        string[7] memory names = [
            "claims only (digests trusted, no sd)",
            "1 lane, 3 digests (14 blocks)       ",
            "1 lane, 2 digests, no sd_hash (12)  ",
            "SWAR 4-lane, 3 digests (8 steps)    ",
            "SWAR 4-lane, 2 digests (7 steps)    ",
            "0x02 precompile, 3 digests (body)   ",
            "0x02 precompile, 2 digests (body)   "
        ];
        for (uint256 i = 0; i < 7; i++) {
            c[i].check(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY, s, deadline); // warm account
            uint256 g = gasleft();
            c[i].check(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY, s, deadline);
            console.log(names[i], g - gasleft());
        }
    }

    function test_negatives() public {
        (bytes32 hEvt, bytes32 hKb) = _digests();
        NativeEvpCheck.Sig[3] memory s;
        for (uint256 i = 1; i < 7; i++) {
            NativeEvpCheck v = c[i];
            s = _sigs(bytes32(uint256(hEvt) ^ 1), hKb);
            vm.expectRevert(abi.encodeWithSelector(NativeEvpCheck.BadSig.selector, 0));
            v.check(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY, s, deadline);
            s = _sigs(hEvt, bytes32(uint256(hKb) ^ 1));
            vm.expectRevert(abi.encodeWithSelector(NativeEvpCheck.BadSig.selector, 1));
            v.check(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY, s, deadline);
            s = _sigs(hEvt, hKb);
            s[0].signer = address(0xbad);
            vm.expectRevert(abi.encodeWithSelector(NativeEvpCheck.BadSig.selector, 0));
            v.check(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY, s, deadline);
            s = _sigs(hEvt, hKb);
            s[1].signer = address(0xbad);
            vm.expectRevert(abi.encodeWithSelector(NativeEvpCheck.BadSig.selector, 1));
            v.check(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY, s, deadline);
            s = _sigs(hEvt, hKb);
            s[2].signer = address(0xbad);
            vm.expectRevert(abi.encodeWithSelector(NativeEvpCheck.BadSig.selector, 2));
            v.check(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY, s, deadline);
            s = _sigs(hEvt, hKb);
            vm.expectRevert(NativeEvpCheck.Stale.selector);
            v.check(Fixture.TOKEN, Fixture.OFFS, Fixture.NEW_KEY, s, Fixture.IAT + 901);
            bytes memory other = Fixture.NEW_KEY;
            other[0] = other[0] ^ 0x01;
            vm.expectRevert(abi.encodeWithSelector(NativeEvpCheck.BadClaim.selector, 12));
            v.check(Fixture.TOKEN, Fixture.OFFS, other, s, deadline);
            // KB-JWT reused with another EVT: sd_hash catches it only when checked
            if (v.checkSd()) {
                (bytes32 e2, ) = _digestsOf(Fixture.TOKEN_SD_SWAP, Fixture.OFFS_SD_SWAP);
                s = _sigs(e2, hKb);
                vm.expectRevert(abi.encodeWithSelector(NativeEvpCheck.BadClaim.selector, 14));
                v.check(Fixture.TOKEN_SD_SWAP, Fixture.OFFS_SD_SWAP, Fixture.NEW_KEY, s, deadline);
            }
        }
    }

    function _digestsOf(bytes memory tok, uint256 o) internal pure returns (bytes32, bytes32) {
        uint256 d2 = (o >> 16) & 0xffff;
        uint256 t = (o >> 32) & 0xffff;
        uint256 k2 = (o >> 64) & 0xffff;
        return (sha256(_cut(tok, 0, d2)), sha256(_cut(tok, t + 1, k2)));
    }
}
