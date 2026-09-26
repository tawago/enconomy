// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Test.sol";
import {PopSafeBase} from "./utils/PopSafeBase.sol";
import {NoirPresenceVerifier} from "../src/verifiers/NoirPresenceVerifier.sol";
import {IPopPresenceVerifier, IHonkVerifier} from "../src/interfaces/IPopPresenceVerifier.sol";

/// Test-only: pins the session nonce to the fixture's (the real proofs were made for a server session, not for a
/// safeTxHash we can reproduce). Everything else is the production adapter.
contract NoirFixedNonce is NoirPresenceVerifier {
    bytes32 immutable pinned;

    constructor(IHonkVerifier phone, IHonkVerifier pair, uint64 maxAge_, bytes32 n) NoirPresenceVerifier(phone, pair, maxAge_) {
        pinned = n;
    }

    function _nonce(address, bytes32, Bundle memory) internal view override returns (bytes32) {
        return pinned;
    }

    function verifyNonce(bytes32 n, uint256 qx, uint256 qy, Bundle memory b) external view {
        _verify(n, qx, qy, b);
    }
}

/// Real option A proofs (iPhone fixtures, enconomy-zk pinned oaN_s48 A/B + noir/pair) through the real bb
/// verifiers, then through the whole Safe execTransaction path. Checks the gas fits one Sepolia tx
/// (EIP-7825 cap 16,777,216, block 60M).
contract NoirRealGasTest is PopSafeBase {
    uint256 constant TX_CAP = 16_777_216;
    bytes32 constant NONCE = 0xefa53688db41bdc0ef206e14cf42c5de874443d5b6d44c6e5fc1b0345738db85;
    uint256 constant QX = 0x9178141b72e5cae00db063dbd38fda4f82a11e1dc8442d2735604719630d99b6;
    uint256 constant QY = 0x4b75c24fb3128f0646642e3828848d23348f1e08023f5378425a28cffd1885e3;
    uint64 constant VALID_AT = 1_790_000_000;

    NoirFixedNonce nv;
    IHonkVerifier phoneV;
    IHonkVerifier pairV;

    function _verifier() internal override returns (IPopPresenceVerifier) {
        vm.warp(VALID_AT + 120);
        phoneV = IHonkVerifier(_deployLinked("PhoneVerifier", "PhoneVerifier"));
        pairV = IHonkVerifier(_deployLinked("PairVerifier", "HonkVerifier"));
        nv = new NoirFixedNonce(phoneV, pairV, 86_400, NONCE);
        return nv;
    }

    /// bb verifiers need two external libraries; forge can't auto-link them here because the fixtures build
    /// under their own compiler profile (no via_ir), so link by hand from the artifacts.
    function _deployLinked(string memory file, string memory name) internal returns (address a) {
        string memory src = string.concat("test/fixtures/zk/", file, ".sol");
        string memory obj = vm.parseJsonString(vm.readFile(string.concat("out/", file, ".sol/", name, ".json")), ".bytecode.object");
        string[2] memory libs = ["RelationsLib", "ZKTranscriptLib"];
        for (uint256 i; i < 2; i++) {
            bytes memory libCode = vm.parseJsonBytes(vm.readFile(string.concat("out/", file, ".sol/", libs[i], ".json")), ".bytecode.object");
            address lib;
            assembly {
                lib := create(0, add(libCode, 32), mload(libCode))
            }
            require(lib != address(0), "lib deploy");
            bytes32 k = keccak256(bytes(string.concat(src, ":", libs[i])));
            string memory ph = string.concat("__$", _hex(k, 17), "$__");
            obj = vm.replace(obj, ph, _hex(bytes32(bytes20(lib)), 20));
        }
        bytes memory code = vm.parseBytes(obj);
        assembly {
            a := create(0, add(code, 32), mload(code))
        }
        require(a != address(0), "verifier deploy");
    }

    function _hex(bytes32 v, uint256 n) internal pure returns (string memory) {
        bytes memory o = new bytes(2 * n);
        bytes16 d = "0123456789abcdef";
        for (uint256 i; i < n; i++) {
            o[2 * i] = d[uint8(v[i]) >> 4];
            o[2 * i + 1] = d[uint8(v[i]) & 15];
        }
        return string(o);
    }

    function _issuerKey() internal pure override returns (uint256, uint256) {
        return (QX, QY);
    }

    function _pubs(string memory p) internal view returns (bytes32[] memory o) {
        bytes memory b = vm.readFileBinary(p);
        o = new bytes32[](b.length / 32);
        for (uint256 i; i < o.length; i++) {
            bytes32 w;
            assembly {
                w := mload(add(add(b, 32), mul(i, 32)))
            }
            o[i] = w;
        }
    }

    function _bundle() internal view returns (NoirPresenceVerifier.Bundle memory b) {
        b.notBefore = VALID_AT - 10;
        b.sid = bytes16(0);
        b.proofA = vm.readFileBinary("test/fixtures/zk/A/proof");
        b.pubA = _pubs("test/fixtures/zk/A/public_inputs");
        b.proofB = vm.readFileBinary("test/fixtures/zk/B/proof");
        b.pubB = _pubs("test/fixtures/zk/B/public_inputs");
        b.proofPair = vm.readFileBinary("test/fixtures/zk/pair/proof");
        b.pubPair = _pubs("test/fixtures/zk/pair/public_inputs");
        b.ccSigA = abi.encodePacked(keccak256("ccA-r"), keccak256("ccA-s"));
        b.ccSigB = abi.encodePacked(keccak256("ccB-r"), keccak256("ccB-s"));
    }

    /// The fixture issuer's private key isn't in this repo (the proofs pin it), so the two POPCC1 checks hit a
    /// mocked 0x100 that accepts exactly these digests/sigs; anything else still goes to the real precompile.
    /// Real P-256 cost (EIP-7951: 6,900 each) is covered by NoirPresenceTest.test_noir_code_attest.
    function _mockCc(NoirPresenceVerifier.Bundle memory b) internal {
        bytes32[] memory v;
        bytes memory sig;
        for (uint256 r; r < 2; r++) {
            (v, sig) = r == 0 ? (b.pubA, b.ccSigA) : (b.pubB, b.ccSigB);
            bytes32 h = sha256(abi.encodePacked("POPCC1", NONCE, uint8(uint256(v[2])), r == 0 ? bytes1("A") : bytes1("B"), v[4]));
            (bytes32 sr, bytes32 ss) = abi.decode(sig, (bytes32, bytes32));
            vm.mockCall(address(0x100), abi.encode(h, sr, ss, QX, QY), abi.encode(uint256(1)));
        }
    }

    function setUp() public override {
        super.setUp();
        _mockCc(_bundle());
    }

    function _presenceFor(bytes32, uint256, uint256) internal view override returns (bytes memory) {
        return abi.encode(_bundle());
    }

    function test_real_verifiers_each() public view {
        NoirPresenceVerifier.Bundle memory b = _bundle();
        uint256 g = gasleft();
        assertTrue(phoneV.verify(b.proofA, b.pubA));
        uint256 ga = g - gasleft();
        g = gasleft();
        assertTrue(phoneV.verify(b.proofB, b.pubB));
        uint256 gb = g - gasleft();
        g = gasleft();
        assertTrue(pairV.verify(b.proofPair, b.pubPair));
        uint256 gp = g - gasleft();
        console.log("PhoneVerifier A execution gas", ga);
        console.log("PhoneVerifier B execution gas", gb);
        console.log("PairVerifier execution gas", gp);
        console.log("sum", ga + gb + gp);
        console.log("PhoneVerifier runtime bytes", address(phoneV).code.length);
        console.log("PairVerifier runtime bytes", address(pairV).code.length);
    }

    function test_real_adapter_linking() public view {
        nv.verifyNonce(NONCE, QX, QY, _bundle());
    }

    function test_real_adapter_rejects_tampered() public {
        NoirPresenceVerifier.Bundle memory b = _bundle();
        b.pubA[4] = bytes32(uint256(b.pubA[4]) ^ 1); // code_commit the server didn't vouch for
        vm.expectRevert(abi.encodeWithSelector(NoirPresenceVerifier.BadCodeAttest.selector, 0));
        nv.verifyNonce(NONCE, QX, QY, b);
        b = _bundle();
        b.proofB[100] ^= 0x01;
        vm.expectRevert(); // bb verifier reverts (or returns false -> ProofRejected)
        nv.verifyNonce(NONCE, QX, QY, b);
        b = _bundle();
        vm.expectRevert(abi.encodeWithSelector(NoirPresenceVerifier.BadPublicInputs.selector, 1));
        nv.verifyNonce(NONCE ^ bytes32(uint256(1)), QX, QY, b);
    }

    /// Whole spend: Safe.execTransaction -> 2x P256Owner -> guard -> adapter -> 3 real UltraHonk verifications.
    function test_real_guard_path_fits_one_tx() public {
        bytes32 h = _h(bob, 0.1 ether, "");
        bytes memory sigs = abi.encodePacked(_sigs(h, oA, oB), frame(_presenceFor(h, 0, 0)));
        bytes memory cd = abi.encodeWithSignature(
            "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)",
            bob, 0.1 ether, "", 0, 0, 0, 0, address(0), address(0), sigs
        );
        uint256 zeros;
        for (uint256 i; i < cd.length; i++) {
            if (cd[i] == 0) zeros++;
        }
        uint256 tokens = zeros + 4 * (cd.length - zeros);
        uint256 g = gasleft();
        assertTrue(execRaw(bob, 0.1 ether, "", 0, 0, sigs));
        uint256 execGas = g - gasleft();
        uint256 intrinsic = 21_000 + 4 * tokens;
        uint256 floor = 21_000 + 10 * tokens; // EIP-7623 calldata floor
        uint256 txGas = execGas + intrinsic > floor ? execGas + intrinsic : floor;
        console.log("signatures bytes", sigs.length);
        console.log("execTransaction execution gas", execGas);
        console.log("est. tx gas (incl. 21k + calldata)", txGas);
        assertEq(bob.balance, 0.1 ether);
        assertLt(txGas, TX_CAP, "must fit the EIP-7825 per-tx cap");
    }
}
