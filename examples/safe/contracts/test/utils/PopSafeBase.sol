// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Test.sol";
import {SafeL2} from "safe-smart-account/contracts/SafeL2.sol";
import {SafeProxyFactory} from "safe-smart-account/contracts/proxies/SafeProxyFactory.sol";
import {CompatibilityFallbackHandler} from "safe-smart-account/contracts/handler/CompatibilityFallbackHandler.sol";
import {PopSafeGuard, PopSafeSetup} from "../../src/PopSafeGuard.sol";
import {P256Owner, P256OwnerFactory} from "../../src/P256Owner.sol";
import {IPopPresenceVerifier} from "../../src/interfaces/IPopPresenceVerifier.sol";

interface IFactory {
    function createProxyWithNonce(address singleton, bytes memory initializer, uint256 saltNonce)
        external
        returns (address);
}

interface ISafe {
    function setup(address[] calldata, uint256, address, bytes calldata, address, address, uint256, address payable)
        external;
    function execTransaction(
        address to,
        uint256 value,
        bytes calldata data,
        uint8 operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address payable refundReceiver,
        bytes memory signatures
    ) external payable returns (bool);
    function getTransactionHash(
        address to,
        uint256 value,
        bytes calldata data,
        uint8 operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address refundReceiver,
        uint256 _nonce
    ) external view returns (bytes32);
    function nonce() external view returns (uint256);
    function getOwners() external view returns (address[] memory);
    function getThreshold() external view returns (uint256);
    function isOwner(address) external view returns (bool);
    function setGuard(address) external;
    function enableModule(address) external;
    function setFallbackHandler(address) external;
    function swapOwner(address, address, address) external;
    function addOwnerWithThreshold(address, uint256) external;
    function VERSION() external view returns (string memory);
}

interface IHandler {
    function getMessageHashForSafe(address safe, bytes memory message) external view returns (bytes32);
}

/// Shared Safe + guard fixture. Local: Safe 1.5.0 from lib/safe-smart-account. Fork: canonical Sepolia addresses.
/// Presence bytes come from the concrete test (`_presenceFor`).
abstract contract PopSafeBase is Test {
    // Safe 1.5.0 canonical on Ethereum Sepolia (contracts/PREFLIGHT.md)
    address constant SEPOLIA_FACTORY = 0x14F2982D601c9458F93bd70B218933A6f8165e7b;
    address constant SEPOLIA_SAFE_L2 = 0xEdd160fEBBD92E350D4D398fb636302fccd67C7e;
    address constant SEPOLIA_FALLBACK = 0x3EfCBb83A4A7AfcB4F68D501E2c2203a38be77f4;

    bytes32 constant GUARD_SLOT = 0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8;
    bytes32 constant FALLBACK_SLOT = 0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5;
    bytes4 constant POPV = 0x504f5056;
    uint32 constant DELAY = 300;
    uint32 constant GRACE = 600;

    uint256 constant ISSUER = 0xC0FFEE;
    uint256 constant PHONE_A = 0xA1;
    uint256 constant PHONE_B = 0xB1;
    uint256 constant PHONE_A2 = 0xA2;
    uint256 constant STRANGER = 0x51;
    uint256 constant recK = 0x7EC0;
    uint256 constant rec2K = 0x7EC1;

    address factory;
    address singleton;
    address fallbackHandler;

    ISafe safe;
    PopSafeGuard guard;
    PopSafeSetup helper;
    P256OwnerFactory pf;
    address oA;
    address oB;
    address rec;
    address rec2;
    address bob;
    mapping(address => uint256) phoneOf; // P256Owner => phone key

    function _verifier() internal virtual returns (IPopPresenceVerifier);

    /// presence bytes (unframed) for tx hash h, devices of phones px/py
    function _presenceFor(bytes32 h, uint256 px, uint256 py) internal view virtual returns (bytes memory);

    /// the Safe's PoP server / issuer key in the guard
    function _issuerKey() internal view virtual returns (uint256 qx, uint256 qy) {
        return vm.publicKeyP256(ISSUER);
    }

    function _infra() internal virtual {
        factory = address(new SafeProxyFactory());
        singleton = address(new SafeL2());
        fallbackHandler = address(new CompatibilityFallbackHandler());
    }

    function setUp() public virtual {
        _infra();
        pf = new P256OwnerFactory();
        oA = ownerFor(PHONE_A);
        oB = ownerFor(PHONE_B);
        rec = vm.addr(recK);
        rec2 = vm.addr(rec2K);
        bob = makeAddr("bob");
        guard = new PopSafeGuard(_verifier());
        helper = new PopSafeSetup();
        uint256 g = gasleft();
        safe = _create(_owners(), _devs(), _devOwners(), address(0), DELAY, 1); // fallbackHandler = 0
        console.log("create 2-of-4 Safe + guard slot + 2 devices, gas", g - gasleft());
        vm.deal(address(safe), 1 ether);
    }

    // ---- helpers ----

    function dev(uint256 pk) internal pure returns (bytes32) {
        (uint256 x, uint256 y) = vm.publicKeyP256(pk);
        return sha256(abi.encodePacked(bytes1(0x04), x, y));
    }

    function ownerFor(uint256 pk) internal returns (address o) {
        (uint256 x, uint256 y) = vm.publicKeyP256(pk);
        o = pf.deploy(x, y);
        phoneOf[o] = pk;
    }

    function _owners() internal view returns (address[] memory owners) {
        owners = new address[](4);
        owners[0] = oA;
        owners[1] = oB;
        owners[2] = rec;
        owners[3] = rec2;
    }

    function _devs() internal pure returns (bytes32[] memory devs) {
        devs = new bytes32[](2);
        devs[0] = dev(PHONE_A);
        devs[1] = dev(PHONE_B);
    }

    function _devOwners() internal view returns (address[] memory d) {
        d = new address[](2);
        d[0] = oA;
        d[1] = oB;
    }

    function _create(address[] memory owners, bytes32[] memory devs, address[] memory devOwners, address fb, uint32 delay, uint256 salt)
        internal
        returns (ISafe)
    {
        (uint256 qx, uint256 qy) = _issuerKey();
        bytes memory hdata = abi.encodeCall(PopSafeSetup.setup, (address(guard), qx, qy, delay, GRACE, devs, devOwners));
        bytes memory init =
            abi.encodeCall(ISafe.setup, (owners, 2, address(helper), hdata, fb, address(0), 0, payable(address(0))));
        return ISafe(IFactory(factory).createProxyWithNonce(singleton, init, salt));
    }

    function createExt(address[] memory owners, bytes32[] memory devs, address[] memory devOwners, address fb, uint32 delay, uint256 salt)
        external
        returns (ISafe)
    {
        return _create(owners, devs, devOwners, fb, delay, salt);
    }

    // ---- signature assembly (what the relayer does) ----
    struct S {
        address owner;
        bytes sig;
        bool contractSig;
    }

    function _ownerSig(address o, bytes32 h) internal view returns (S memory x) {
        x.owner = o;
        if (o == rec || o == rec2) {
            (uint8 v, bytes32 r, bytes32 s) = vm.sign(o == rec ? recK : rec2K, h);
            x.sig = abi.encodePacked(r, s, v);
        } else {
            (bytes32 r, bytes32 s) = vm.signP256(phoneOf[o], sha256(abi.encodePacked("pop-safe-owner-v1", h)));
            x.sig = abi.encodePacked(r, s);
            x.contractSig = true;
        }
    }

    /// static part sorted by owner; contract sigs get v=0 and an offset into the dynamic part
    function _sigs(bytes32 h, address s1, address s2) internal view returns (bytes memory out) {
        S[2] memory a = [_ownerSig(s1, h), _ownerSig(s2, h)];
        if (a[0].owner > a[1].owner) (a[0], a[1]) = (a[1], a[0]);
        bytes memory dyn;
        uint256 off = 130;
        for (uint256 i; i < 2; i++) {
            if (a[i].contractSig) {
                out = abi.encodePacked(out, bytes32(uint256(uint160(a[i].owner))), bytes32(off + dyn.length), uint8(0));
                dyn = abi.encodePacked(dyn, uint256(64), a[i].sig);
            } else {
                out = abi.encodePacked(out, a[i].sig);
            }
        }
        out = abi.encodePacked(out, dyn);
    }

    function frame(bytes memory presence) internal pure returns (bytes memory) {
        return abi.encodePacked(presence, uint32(presence.length), POPV);
    }

    function _h(address to, uint256 value, bytes memory data) internal view returns (bytes32) {
        return safe.getTransactionHash(to, value, data, 0, 0, 0, 0, address(0), address(0), safe.nonce());
    }

    function execRaw(address to, uint256 value, bytes memory data, uint8 op, uint256 gasPrice, bytes memory sigs)
        public
        returns (bool)
    {
        return safe.execTransaction(to, value, data, op, 0, 0, gasPrice, address(0), payable(address(0)), sigs);
    }

    function execOp(address to, uint256 value, bytes memory data, uint8 op, uint256 gasPrice, address s1, address s2, uint256 px, uint256 py)
        public
        returns (bool)
    {
        bytes32 h = safe.getTransactionHash(to, value, data, op, 0, 0, gasPrice, address(0), address(0), safe.nonce());
        bytes memory sigs = _sigs(h, s1, s2);
        if (px != 0) sigs = abi.encodePacked(sigs, frame(_presenceFor(h, px, py)));
        return execRaw(to, value, data, op, gasPrice, sigs);
    }

    /// px == 0: no presence (hatch path)
    function exec(address to, uint256 value, bytes memory data, address s1, address s2, uint256 px, uint256 py)
        public
        returns (bool)
    {
        return execOp(to, value, data, 0, 0, s1, s2, px, py);
    }
}

/// EIP-2612 token that validates contract owners through EIP-1271 (like USDC FiatToken v2.2).
contract MockPermitToken {
    bytes32 public constant PERMIT_TYPEHASH =
        keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)");
    bytes32 public immutable DOMAIN_SEPARATOR = keccak256(abi.encode(keccak256("MockPermit"), block.chainid, address(this)));
    mapping(address => uint256) public nonces;
    mapping(address => mapping(address => uint256)) public allowance;

    function permit(address owner, address spender, uint256 value, uint256 deadline, bytes memory signature) external {
        require(block.timestamp <= deadline, "expired");
        bytes32 d = keccak256(
            abi.encodePacked(
                hex"1901",
                DOMAIN_SEPARATOR,
                keccak256(abi.encode(PERMIT_TYPEHASH, owner, spender, value, nonces[owner]++, deadline))
            )
        );
        (bool ok, bytes memory ret) =
            owner.staticcall(abi.encodeWithSignature("isValidSignature(bytes32,bytes)", d, signature));
        require(ok && ret.length == 32 && bytes4(ret) == 0x1626ba7e, "bad sig");
        allowance[owner][spender] = value;
    }

    function digestFor(address owner, address spender, uint256 value, uint256 deadline) external view returns (bytes32) {
        return keccak256(
            abi.encodePacked(
                hex"1901",
                DOMAIN_SEPARATOR,
                keccak256(abi.encode(PERMIT_TYPEHASH, owner, spender, value, nonces[owner], deadline))
            )
        );
    }
}
