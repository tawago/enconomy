// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import "forge-std/Test.sol";
import {PopSafeGuard, PopSafeSetup} from "../src/PopSafeGuardU.sol";
import {P256Owner} from "../src/P256Owner.sol";

interface IFactory { function createProxyWithNonce(address singleton, bytes memory initializer, uint256 saltNonce) external returns (address); }
interface ISafe {
    function setup(address[] calldata, uint256, address, bytes calldata, address, address, uint256, address payable) external;
    function execTransaction(address to, uint256 value, bytes calldata data, uint8 operation, uint256 safeTxGas, uint256 baseGas, uint256 gasPrice, address gasToken, address payable refundReceiver, bytes memory signatures) external payable returns (bool);
    function getTransactionHash(address to, uint256 value, bytes calldata data, uint8 operation, uint256 safeTxGas, uint256 baseGas, uint256 gasPrice, address gasToken, address refundReceiver, uint256 _nonce) external view returns (bytes32);
    function nonce() external view returns (uint256);
}

/// Test-only: the spike proofs were made with signal "spike" and two different actions.
/// Returns the spike signal only for the bound safeTxHash; any other tx gets the real formula.
contract SpikeGuard is PopSafeGuard {
    uint256 constant SPIKE_SH = 0x0022ec8cb931f2fe813df7a9380c0ead38cf6d798b02260c0f9c08f3fb50b989;
    uint256 immutable ACT_A; uint256 immutable ACT_B;
    bytes32 public boundTx;
    constructor(address wid, uint64 rp, uint256 a, uint256 b) PopSafeGuard(wid, rp) { ACT_A = a; ACT_B = b; }
    function bind(bytes32 h) external { boundTx = h; }
    function _signalHash(bytes32 h, bytes32 n, bytes1 role, uint256 slot) internal view override returns (uint256) {
        return h == boundTx ? SPIKE_SH : super._signalHash(h, n, role, slot);
    }
    function _action(bytes16, uint256 slot) internal view override returns (uint256) { return slot == 0 ? ACT_A : ACT_B; }
}

contract GuardUTest is Test {
    uint256 constant FORK_BLOCK = 35464545;
    address constant WID = 0x00000000009E00F9FE82CfeeBB4556686da094d7;
    uint64 constant RP = 1470746745086940220;
    address constant FACTORY = 0x14F2982D601c9458F93bd70B218933A6f8165e7b;
    address constant SAFE_L2_150 = 0xEdd160fEBBD92E350D4D398fb636302fccd67C7e;
    address constant FALLBACK = 0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99;
    bytes4 constant PROOF_INVALID = 0x7fcdd1f4;
    bytes4 constant INVALID_ROOT = 0x9dd854d3;

    uint256 constant NA = 0x162aa2ced980fe203e8f444fd161cbfecb8079444c811f49c1e36d91b42e8a53;
    uint256 constant NB = 0x0df44fb1e78d4df639919fa6f8fc06f4d1914d84f579e53c78fb2b5eba2d8ef6;
    bytes32 constant PAIRTAG_PY = 0xe0a248dd5ec084994b2aca7fee294660f9ee6a93dd5a3a49f6d2b1d7d78c76bb;

    uint256 k1 = 0xA11CE; uint256 issuerPk = 0xC0FFEE; uint256 ownerP256 = 0x2222;
    uint256 constant PHONE_A = 0xA1; uint256 constant PHONE_B = 0xB1;
    bytes16 constant SID = 0x00112233445566778899aabbccddeeff; uint64 constant NB4 = 1790264600;

    ISafe safe; PopSafeGuard guard; PopSafeSetup helper; P256Owner pOwner; address o1; address bob;

    function hA() internal pure returns (bytes memory) {
        return abi.encodePacked(NA, uint256(0x00cdad407e31b93f4101ea84c3a382039f587d5ffbae86bb766a6ac1ce7c0343), uint64(1790264612),
            uint256(24643224222707417029235725305950213670563643092921051588895189505834811955013),
            uint256(14761244667611688071578738893930367803737017631766736836509722972277099603488),
            uint256(18686117517150256267261864360170007600795782682159741038080100617914270529257),
            uint256(36800890520520620314742234858180444131156994310855377760873443653148406885981),
            uint256(4811351604658854053044351946818995910976871300870904331801469560226850856258));
    }
    function hB() internal pure returns (bytes memory) {
        return abi.encodePacked(NB, uint256(0x007ddfa3c720af841089b304f04a56984d2923597f539f077f8aa5c3be745937), uint64(1790264710),
            uint256(37183917788145304656128941188184950821425108496979245454197728313001633701254),
            uint256(2566330577237361697742599925580279901334213109221252382621840224538606151890),
            uint256(47131415224415926704292289891893636373565981270433731100239796061138122967499),
            uint256(42355138331779422575622705574569781989598922695273201623568392473313876838217),
            uint256(4811351604658854053044351946818995910976871300870904331801469560226850856258));
    }
    function act(string memory s) internal pure returns (uint256) { return uint256(keccak256(bytes(s))) >> 8; }

    function dev(uint256 pk) internal pure returns (bytes32) {
        (uint256 x, uint256 y) = vm.publicKeyP256(pk);
        return sha256(abi.encodePacked(bytes1(0x04), x, y));
    }

    function _deploy(uint256 blk, bool spike) internal {
        vm.createSelectFork("wc", blk);
        o1 = vm.addr(k1); bob = makeAddr("bob");
        (uint256 px, uint256 py) = vm.publicKeyP256(ownerP256);
        pOwner = new P256Owner(px, py);
        guard = spike ? PopSafeGuard(address(new SpikeGuard(WID, RP, act("spike-1790264612780"), act("spike-1790264710529"))))
                      : new PopSafeGuard(WID, RP);
        helper = new PopSafeSetup();
        (uint256 qx, uint256 qy) = vm.publicKeyP256(issuerPk);
        address[] memory owners = new address[](2); owners[0] = o1; owners[1] = address(pOwner);
        bytes32[] memory devs = new bytes32[](2); devs[0] = dev(PHONE_A); devs[1] = dev(PHONE_B);
        bytes memory hdata = abi.encodeCall(PopSafeSetup.setup, (address(guard), qx, qy, uint32(1 days), devs, owners));
        bytes memory init = abi.encodeCall(ISafe.setup, (owners, 2, address(helper), hdata, FALLBACK, address(0), 0, payable(address(0))));
        safe = ISafe(IFactory(FACTORY).createProxyWithNonce(SAFE_L2_150, init, 7));
        vm.deal(address(safe), 10 ether);
    }

    /// owner sigs: EOA (65 B) + P256Owner contract sig (65 B static, 96 B dynamic) in owner-address order
    function _ownerSigs(bytes32 h) internal view returns (bytes memory) {
        (uint8 v1, bytes32 r1, bytes32 s1) = vm.sign(k1, h);
        (bytes32 r2, bytes32 s2) = vm.signP256(ownerP256, sha256(abi.encodePacked(h)));
        bytes memory eoa = abi.encodePacked(r1, s1, v1);
        bytes memory con = abi.encodePacked(bytes32(uint256(uint160(address(pOwner)))), uint256(130), uint8(0));
        bytes memory stat = o1 < address(pOwner) ? abi.encodePacked(eoa, con) : abi.encodePacked(con, eoa);
        return abi.encodePacked(stat, uint256(64), r2, s2);
    }

    function _pop2(bytes32 h, bytes32 pairTag) internal view returns (bytes memory) {
        uint64 expiry = uint64(block.timestamp + 600);
        bytes32 dA = dev(PHONE_A); bytes32 dB = dev(PHONE_B);
        bytes32 d = guard.digest(block.chainid, address(safe), h, pairTag, dA, dB, expiry);
        (bytes32 r, bytes32 s) = vm.signP256(issuerPk, d);
        return abi.encodePacked(pairTag, dA, dB, expiry, r, s, bytes4(0x504f5032));
    }

    function _wid(bytes memory a, bytes memory b) internal pure returns (bytes memory) {
        return abi.encodePacked(SID, NB4, a, b, bytes4(0x57494431));
    }

    function execRaw(uint256 value, bytes memory sigs) public returns (bool) {
        return safe.execTransaction(bob, value, "", 0, 0, 0, 0, address(0), payable(address(0)), sigs);
    }
    function _h(uint256 value) internal view returns (bytes32) {
        return safe.getTransactionHash(bob, value, "", 0, 0, 0, 0, address(0), address(0), safe.nonce());
    }

    // ---------- positive ----------
    function test_pairTag_parity_with_python() public pure {
        PopSafeGuard g = PopSafeGuard(address(0));
        g; // pure helper recomputed inline to avoid a deploy
        (uint256 lo, uint256 hi) = NA < NB ? (NA, NB) : (NB, NA);
        assertEq(sha256(abi.encodePacked("pop-pair-v1", lo, hi)), PAIRTAG_PY);
    }

    function test_actionOf_matches_text() public {
        vm.createSelectFork("wc", FORK_BLOCK);
        PopSafeGuard g = new PopSafeGuard(WID, RP);
        assertEq(g.actionOf(SID), act("pop:00112233445566778899aabbccddeeff"));
        assertEq(g.pairTagOf(NA, NB), PAIRTAG_PY);
        assertEq(g.pairTagOf(NB, NA), PAIRTAG_PY);
    }

    function test_real_exec_two_real_proofs() public {
        _deploy(FORK_BLOCK, true);
        bytes32 h = _h(1 ether);
        SpikeGuard(address(guard)).bind(h);
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _wid(hA(), hB()), _pop2(h, guard.pairTagOf(NA, NB)));
        console.log("signatures bytes", sigs.length);
        uint256 g = gasleft();
        assertTrue(execRaw(1 ether, sigs));
        console.log("execTransaction gas (in-test, excl. intrinsic+calldata)", g - gasleft());
        assertEq(bob.balance, 1 ether);
        assertEq(safe.nonce(), 1);
        // replay of the identical blob: Safe nonce moved -> owner sig check fails first
        vm.expectRevert();
        this.execRaw(1 ether, sigs);
    }

    // ---------- negatives ----------
    function test_neg_same_nullifier_twice() public {
        _deploy(FORK_BLOCK, true);
        bytes32 h = _h(1 ether); SpikeGuard(address(guard)).bind(h);
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _wid(hA(), hA()), _pop2(h, guard.pairTagOf(NA, NA)));
        vm.expectRevert(PopSafeGuard.SameHuman.selector);
        this.execRaw(1 ether, sigs);
    }

    function test_neg_swapped_roles() public {
        _deploy(FORK_BLOCK, true);
        bytes32 h = _h(1 ether); SpikeGuard(address(guard)).bind(h);
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _wid(hB(), hA()), _pop2(h, guard.pairTagOf(NA, NB)));
        vm.expectRevert(PROOF_INVALID);
        this.execRaw(1 ether, sigs);
    }

    function test_neg_proof_from_other_safeTxHash() public {
        _deploy(FORK_BLOCK, true);
        SpikeGuard(address(guard)).bind(_h(1 ether));        // proofs "belong" to the 1 ETH tx
        bytes32 h2 = _h(2 ether);                              // owners + server sign the 2 ETH tx
        bytes memory sigs = abi.encodePacked(_ownerSigs(h2), _wid(hA(), hB()), _pop2(h2, guard.pairTagOf(NA, NB)));
        vm.expectRevert(PROOF_INVALID);
        this.execRaw(2 ether, sigs);
    }

    function test_neg_pairTag_not_from_nullifiers() public {
        _deploy(FORK_BLOCK, true);
        bytes32 h = _h(1 ether); SpikeGuard(address(guard)).bind(h);
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _wid(hA(), hB()), _pop2(h, keccak256("pair")));
        vm.expectRevert(PopSafeGuard.PairTagMismatch.selector);
        this.execRaw(1 ether, sigs);
    }

    function test_neg_no_wid_block() public {
        _deploy(FORK_BLOCK, true);
        bytes32 h = _h(1 ether); SpikeGuard(address(guard)).bind(h);
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _pop2(h, guard.pairTagOf(NA, NB)));
        vm.expectRevert(); // NoHumans or magic mismatch
        this.execRaw(1 ether, sigs);
    }

    function test_neg_flipped_proof_bit() public {
        _deploy(FORK_BLOCK, true);
        bytes32 h = _h(1 ether); SpikeGuard(address(guard)).bind(h);
        bytes memory b = hB(); b[80] = bytes1(uint8(b[80]) ^ 1);
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _wid(hA(), b), _pop2(h, guard.pairTagOf(NA, NB)));
        vm.expectRevert(PROOF_INVALID);
        this.execRaw(1 ether, sigs);
    }

    function test_neg_production_guard_rejects_spike_signal() public {
        _deploy(FORK_BLOCK, false);                            // real signal + action formulas
        bytes32 h = _h(1 ether);
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _wid(hA(), hB()), _pop2(h, guard.pairTagOf(NA, NB)));
        vm.expectRevert(PROOF_INVALID);
        this.execRaw(1 ether, sigs);
    }

    function test_neg_root_expired_one_hour_later() public {
        _deploy(FORK_BLOCK + 1900, true);                      // +3800 s
        bytes32 h = _h(1 ether); SpikeGuard(address(guard)).bind(h);
        bytes memory sigs = abi.encodePacked(_ownerSigs(h), _wid(hA(), hB()), _pop2(h, guard.pairTagOf(NA, NB)));
        vm.expectRevert(INVALID_ROOT);
        this.execRaw(1 ether, sigs);
    }
}
