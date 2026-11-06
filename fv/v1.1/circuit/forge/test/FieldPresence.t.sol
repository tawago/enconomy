// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {PhoneVerifier} from "../src/PhoneVerifier.sol";
import {PairNamedVerifier} from "../src/PairNamedVerifier.sol";
import {IHonkVerifier, IPopPresenceVerifier} from "pop/IPopPresenceVerifier.sol";

interface Vm {
    function readFileBinary(string calldata path) external view returns (bytes memory);
    function cool(address target) external;
    function envOr(string calldata name, bool fallback_) external view returns (bool);
    function deployCode(string calldata artifact, bytes calldata args) external returns (address);
}

/// Three real proofs of fixture 180ca04b_48k through the real adapter. No mocks.
/// The adapter is deployed from its artifact (src/AdapterBuild.sol makes forge build it, via-ir, see foundry.toml).
/// The per-verifier gas comes from the -vvvv trace of the first test, see run_field.sh.
contract FieldPresenceTest {
    event log_named_uint(string key, uint256 val);
    event log_named_bytes32(string key, bytes32 val);

    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    string constant FX = "fixtures/field_180ca04b/";

    bytes32 constant NONCE = 0xefa53688db41bdc0ef206e14cf42c5de874443d5b6d44c6e5fc1b0345738db85;
    uint256 constant DEVICE_A = 0xa3add80f0b308b87f91990aad20b1ba09eac2329cc4ca80940a29c5b27becd0c;
    uint256 constant DEVICE_B = 0xf567fcdaa2cb002d7b91763b5314008716328fb8d943c0a6f592badceae25b59;
    uint256 constant QX = 0x9178141b72e5cae00db063dbd38fda4f82a11e1dc8442d2735604719630d99b6;
    uint256 constant QY = 0x4b75c24fb3128f0646642e3828848d23348f1e08023f5378425a28cffd1885e3;
    // valid_at is 1790000000. notBefore <= valid_at <= deadline + 300, deadline <= valid_at + maxAge.
    uint64 constant NOT_BEFORE = 1789999400;
    uint256 constant DEADLINE = 1790000600;
    uint64 constant MAX_AGE = 1200;

    /// Same layout as EvpNoirPresenceVerifier.Bundle, which the adapter decodes.
    struct Bundle {
        bytes proofA;
        bytes32[] pubA;
        bytes proofB;
        bytes32[] pubB;
        bytes proofPair;
        bytes32[] pubPair;
        bytes ccSigA;
        bytes ccSigB;
    }

    IPopPresenceVerifier adapter;
    address phone;
    address pair;
    address[] libs;

    function setUp() public {
        phone = address(new PhoneVerifier());
        pair = address(new PairNamedVerifier());
        adapter = IPopPresenceVerifier(
            vm.deployCode(
                "EvpNoirPresenceVerifier.sol:EvpNoirPresenceVerifier",
                abi.encode(IHonkVerifier(phone), IHonkVerifier(pair), MAX_AGE)
            )
        );
        _findLibs(phone);
        _findLibs(pair);
        require(libs.length == 4, "want 2 linked libs per verifier");
    }

    /// Linked library addresses, read from the PUSH20s in the runtime, so they can be cooled too.
    function _findLibs(address v) internal {
        bytes memory c = v.code;
        for (uint256 i; i + 20 < c.length; i++) {
            if (c[i] != 0x73) continue;
            address a;
            assembly {
                a := shr(96, mload(add(add(c, 33), i)))
            }
            if (a.code.length == 0) continue;
            bool seen;
            for (uint256 j; j < libs.length; j++) seen = seen || libs[j] == a;
            if (!seen) libs.push(a);
        }
    }

    function _cool() internal {
        vm.cool(address(adapter));
        vm.cool(phone);
        vm.cool(pair);
        for (uint256 j; j < libs.length; j++) vm.cool(libs[j]);
    }

    function _words(string memory p) internal view returns (bytes32[] memory w) {
        bytes memory raw = vm.readFileBinary(string.concat(FX, p, "/public_inputs"));
        w = new bytes32[](raw.length / 32);
        for (uint256 i; i < w.length; i++) {
            bytes32 x;
            assembly {
                x := mload(add(add(raw, 32), mul(i, 32)))
            }
            w[i] = x;
        }
    }

    function _bundle() internal view returns (bytes memory) {
        return abi.encode(
            Bundle({
                proofA: vm.readFileBinary(string.concat(FX, "A/proof")),
                pubA: _words("A"),
                proofB: vm.readFileBinary(string.concat(FX, "B/proof")),
                pubB: _words("B"),
                proofPair: vm.readFileBinary(string.concat(FX, "pair/proof")),
                pubPair: _words("pair"),
                ccSigA: vm.readFileBinary(string.concat(FX, "A/ccsig")),
                ccSigB: vm.readFileBinary(string.concat(FX, "B/ccsig"))
            })
        );
    }

    function _accepts(bytes memory data, uint256 g) internal view returns (bool) {
        (bool ok, bytes memory out) = address(adapter).staticcall{gas: g}(data);
        return ok && out.length == 32 && bytes4(out) == IPopPresenceVerifier.verifyPresence.selector;
    }

    function test_field_bundle_accepted() public {
        bytes memory presence = _bundle();
        bytes memory data = abi.encodeCall(
            adapter.verifyPresence, (NONCE, DEVICE_A, DEVICE_B, QX, QY, NOT_BEFORE, DEADLINE, presence)
        );
        _cool();
        uint256 g = gasleft();
        (bool ok, bytes memory out) = address(adapter).staticcall(data);
        uint256 used = g - gasleft();
        require(ok, "verifyPresence reverted");
        require(bytes4(out) == IPopPresenceVerifier.verifyPresence.selector, "wrong selector");
        emit log_named_uint("total gas, gasleft delta, cold", used);
        emit log_named_uint("presence bytes", presence.length);
        emit log_named_uint("verifyPresence calldata bytes", data.length);
        emit log_named_bytes32("keccak of calldata", keccak256(data));

        if (vm.envOr("PRESENCE_NO_SEARCH", false)) return;
        // Smallest gas handed to the adapter that still accepts, 1/64 hold-backs included. Everything cold each try.
        uint256 lo = used * 9 / 10;
        uint256 hi = used * 11 / 10;
        while (hi - lo > 1) {
            uint256 mid = (lo + hi) / 2;
            _cool();
            if (_accepts(data, mid)) hi = mid;
            else lo = mid;
        }
        emit log_named_uint("smallest gas limit at the adapter that accepts", hi);
    }

    function test_field_wrong_deviceB_rejected() public {
        (bool ok, bytes memory out) = address(adapter).staticcall(
            abi.encodeCall(
                adapter.verifyPresence, (NONCE, DEVICE_A, DEVICE_B ^ 1, QX, QY, NOT_BEFORE, DEADLINE, _bundle())
            )
        );
        require(!ok, "wrong deviceB accepted");
        require(
            keccak256(out) == keccak256(abi.encodeWithSignature("BadPublicInputs(uint256)", uint256(8))),
            "wrong revert"
        );
    }
}
