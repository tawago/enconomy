// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IPopPresenceVerifier} from "./interfaces/IPopPresenceVerifier.sol";

interface ISafeView {
    function nonce() external view returns (uint256);
    function getThreshold() external view returns (uint256);
    function isOwner(address) external view returns (bool);
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
}

interface IPopGuardView {
    function isInit(address safe) external view returns (bool);
}

/// PoP transaction guard for Safe 1.5.0: a Safe tx executes only with a presence proof for that exact safeTxHash.
/// One instance serves many Safes; all state is keyed by the Safe (msg.sender).
///
/// execTransaction.signatures = ownerSigs | presence | u32 BE len(presence) | "POPV"
///   presence is handed to the immutable `verifier` (POP2 attestation or Noir proofs).
///   No "POPV" suffix = escape-hatch path (announced recovery call only).
///
/// The verifier is immutable. Switching verifiers = deploy a new guard, PoP-gated `newGuard.initSafe(...)`,
/// then PoP-gated `setGuard(newGuard)` (or the hatch `setGuard(0)`). No timelock code needed.
/// Replay: safeTxHash contains the Safe nonce, and every presence proof is bound to (chain, safe, safeTxHash).
contract PopSafeGuard {
    bytes4 internal constant MAGIC = 0x504f5056; // "POPV"
    uint32 public constant MIN_DELAY = 300; // s
    uint32 public constant MIN_GRACE = 300; // s
    uint256 public constant WINDOW = 4; // announce only for nonces [nonce(), nonce()+WINDOW)

    bytes4 internal constant SET_GUARD = 0xe19a9dd9;
    bytes4 internal constant SWAP_OWNER = 0xe318b52b;
    bytes4 internal constant ADD_OWNER = 0x0d582f13;
    bytes4 internal constant REMOVE_OWNER = 0xf8dc5dd9;
    bytes4 internal constant CHANGE_THRESHOLD = 0x694e80c3;
    bytes4 internal constant ENABLE_MODULE = 0x610b5925;
    bytes4 internal constant SET_FALLBACK = 0xf08a0323;
    bytes4 internal constant SET_MODULE_GUARD = 0xe068df37;

    struct Cfg {
        uint256 qx;
        uint256 qy;
        uint32 delay;
        uint32 grace;
        uint64 epoch;
        bool init;
    }

    struct Ann {
        uint64 readyAt;
        uint64 epoch;
    }

    IPopPresenceVerifier public immutable verifier;

    mapping(address => Cfg) public cfg;
    mapping(address => mapping(bytes32 => address)) public deviceOwner; // safe => sha256(pubkey65) => owner
    mapping(address => mapping(address => uint256)) public deviceCount; // safe => owner => #registered devices
    mapping(address => mapping(bytes32 => Ann)) public ann; // safe => safeTxHash => announcement

    event SafeInit(address indexed safe, uint256 qx, uint256 qy, uint32 delay, uint32 grace);
    event IssuerSet(address indexed safe, uint256 qx, uint256 qy);
    event DeviceSet(address indexed safe, bytes32 indexed dev, address owner);
    event Announced(
        address indexed safe, bytes32 indexed safeTxHash, uint256 readyAt, address by, address to, uint256 nonce, bytes data
    );
    event Cancelled(address indexed safe, bytes32 indexed safeTxHash);
    event CancelledAll(address indexed safe, uint64 epoch);

    error NotInit();
    error AlreadyInit();
    error NotOwner();
    error BadDevice();
    error AlreadyAnnounced();
    error NoPresence();
    error BadPresence();
    error UnknownDevice();
    error SameOwner();
    error DelegateCallNotAllowed();
    error RefundNotAllowed();
    error ForbiddenSelfCall();
    error NotRecoveryTx();
    error TooEarly();
    error PresentOwnersMustSign();
    error BadConfig();
    error BadNonce();
    error AnnouncementExpired();
    error GuardNotReady();

    modifier onlySafe() {
        if (!cfg[msg.sender].init) revert NotInit();
        _;
    }

    constructor(IPopPresenceVerifier v) {
        verifier = v;
    }

    // ---------------- config (msg.sender == the Safe) ----------------

    function initSafe(
        uint256 qx,
        uint256 qy,
        uint32 delay,
        uint32 grace,
        bytes32[] calldata devs,
        address[] calldata owners
    ) external {
        Cfg storage c = cfg[msg.sender];
        if (c.init) revert AlreadyInit();
        if (delay < MIN_DELAY || grace < MIN_GRACE || ISafeView(msg.sender).getThreshold() < 2) revert BadConfig();
        if (devs.length != owners.length || devs.length < 2) revert BadDevice();
        c.qx = qx;
        c.qy = qy;
        c.delay = delay;
        c.grace = grace;
        c.init = true;
        emit SafeInit(msg.sender, qx, qy, delay, grace);
        for (uint256 i; i < devs.length; i++) {
            _setDevice(devs[i], owners[i]);
        }
    }

    function isInit(address safe) external view returns (bool) {
        return cfg[safe].init;
    }

    function addDevice(bytes32 dev, address owner) external onlySafe {
        _setDevice(dev, owner);
    }

    function removeDevice(bytes32 dev) external onlySafe {
        _clearDevice(dev);
    }

    function replaceDevice(bytes32 oldDev, bytes32 newDev) external onlySafe {
        address o = deviceOwner[msg.sender][oldDev];
        if (o == address(0)) revert UnknownDevice();
        _clearDevice(oldDev);
        _setDevice(newDev, o);
    }

    function setIssuer(uint256 qx, uint256 qy) external onlySafe {
        cfg[msg.sender].qx = qx;
        cfg[msg.sender].qy = qy;
        emit IssuerSet(msg.sender, qx, qy);
    }

    function _setDevice(bytes32 dev, address owner) internal {
        if (dev == bytes32(0)) revert BadDevice();
        if (!ISafeView(msg.sender).isOwner(owner)) revert NotOwner();
        _clearDevice(dev);
        deviceOwner[msg.sender][dev] = owner;
        deviceCount[msg.sender][owner]++;
        emit DeviceSet(msg.sender, dev, owner);
    }

    function _clearDevice(bytes32 dev) internal {
        address prev = deviceOwner[msg.sender][dev];
        if (prev == address(0)) return;
        delete deviceOwner[msg.sender][dev];
        deviceCount[msg.sender][prev]--;
        emit DeviceSet(msg.sender, dev, address(0));
    }

    // ---------------- escape hatch ----------------

    /// An EOA owner (a guardian) announces one recovery call (value 0, CALL, no gas fields) for a nonce in
    /// [nonce(), nonce()+WINDOW). It can execute with no presence in [readyAt, readyAt + grace], unless cancelled.
    function announce(address safe, address to, bytes calldata data, uint256 nonce) external returns (bytes32 h) {
        Cfg storage c = cfg[safe];
        if (!c.init) revert NotInit();
        if (!ISafeView(safe).isOwner(msg.sender)) revert NotOwner();
        uint256 n = ISafeView(safe).nonce();
        if (nonce < n || nonce >= n + WINDOW) revert BadNonce();
        if (!_isRecovery(safe, to, 0, data)) revert NotRecoveryTx();
        h = ISafeView(safe).getTransactionHash(to, 0, data, 0, 0, 0, 0, address(0), address(0), nonce);
        Ann storage a = ann[safe][h];
        if (a.readyAt != 0 && a.epoch == c.epoch && block.timestamp <= uint256(a.readyAt) + c.grace) {
            revert AlreadyAnnounced(); // no timer reset griefing while live
        }
        uint64 t = uint64(block.timestamp + c.delay);
        a.readyAt = t;
        a.epoch = c.epoch;
        emit Announced(safe, h, t, msg.sender, to, nonce, data);
    }

    /// Veto one announcement (a presence-gated Safe tx to the guard).
    function cancel(bytes32 safeTxHash) external onlySafe {
        delete ann[msg.sender][safeTxHash];
        emit Cancelled(msg.sender, safeTxHash);
    }

    /// Veto every pending announcement at once.
    function cancelAll() external onlySafe {
        uint64 e = ++cfg[msg.sender].epoch;
        emit CancelledAll(msg.sender, e);
    }

    // ---------------- guard ----------------

    function supportsInterface(bytes4 id) external pure returns (bool) {
        return id == 0xe6d7a83a || id == 0x01ffc9a7; // ITransactionGuard, ERC165
    }

    function checkTransaction(
        address to,
        uint256 value,
        bytes memory data,
        uint8 operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address payable refundReceiver,
        bytes memory signatures,
        address
    ) external view {
        Cfg storage c = cfg[msg.sender];
        if (!c.init) revert NotInit();
        if (operation != 0) revert DelegateCallNotAllowed();
        if (gasPrice != 0) revert RefundNotAllowed();
        bytes32 h = ISafeView(msg.sender).getTransactionHash(
            to,
            value,
            data,
            operation,
            safeTxGas,
            baseGas,
            gasPrice,
            gasToken,
            refundReceiver,
            ISafeView(msg.sender).nonce() - 1
        );

        (bool has, bytes memory presence) = _presence(signatures);
        if (!has) {
            // escape hatch: announced in this epoch + delay elapsed + grace not over + recovery-only call
            Ann memory a = ann[msg.sender][h];
            if (a.readyAt == 0 || a.epoch != c.epoch) revert NoPresence();
            if (block.timestamp < a.readyAt) revert TooEarly();
            if (block.timestamp > uint256(a.readyAt) + c.grace) revert AnnouncementExpired();
            if (!_isRecovery(msg.sender, to, value, data)) revert NotRecoveryTx();
            return;
        }

        (bytes32 devA, bytes32 devB) = verifier.verifyPresence(msg.sender, h, c.qx, c.qy, presence);
        if (devA == bytes32(0) && devB == bytes32(0)) {
            // verifier does not reveal devices: both counted signers must be device-owning owners
            _requireDeviceOwnerSigners(h, signatures);
        } else {
            address oA = deviceOwner[msg.sender][devA];
            address oB = deviceOwner[msg.sender][devB];
            if (oA == address(0) || oB == address(0)) revert UnknownDevice();
            if (oA == oB) revert SameOwner();
            if (!ISafeView(msg.sender).isOwner(oA) || !ISafeView(msg.sender).isOwner(oB)) revert UnknownDevice();
            _requireSigners(h, signatures, oA, oB);
        }

        if (to == msg.sender && data.length >= 4) {
            bytes4 sel = bytes4(data);
            if (sel == ENABLE_MODULE || sel == SET_FALLBACK || sel == SET_MODULE_GUARD) revert ForbiddenSelfCall();
            if (!_thresholdOk(sel, data)) revert ForbiddenSelfCall();
            if (sel == SET_GUARD && data.length >= 36) {
                address ng = address(uint160(_word(data, 4)));
                if (ng != address(0) && ng != address(this)) {
                    (bool ok, bytes memory ret) = ng.staticcall(abi.encodeCall(IPopGuardView.isInit, (msg.sender)));
                    if (!ok || ret.length != 32 || abi.decode(ret, (uint256)) != 1) revert GuardNotReady();
                }
            }
        }
    }

    function checkAfterExecution(bytes32, bool) external pure {}

    /// Splits `ownerSigs | presence | u32 len | "POPV"`. Returns has = false when the suffix is absent.
    function _presence(bytes memory sigs) internal pure returns (bool has, bytes memory p) {
        uint256 n = sigs.length;
        if (n < 8) return (false, p);
        bytes32 w;
        assembly {
            w := mload(add(add(sigs, 32), sub(n, 8)))
        }
        if (bytes4(w << 32) != MAGIC) return (false, p);
        uint256 len = uint32(bytes4(w));
        if (len + 8 > n) revert BadPresence();
        p = new bytes(len);
        assembly {
            mcopy(add(p, 32), add(add(sigs, 32), sub(sub(n, 8), len)), len)
        }
        return (true, p);
    }

    /// Owner id of counted signature i, per Safe encoding: v=0 contract / v=1 approved hash -> r;
    /// v>30 eth_sign -> ecrecover(prefixed h, v-4); else ecrecover(h, v).
    function _signer(bytes32 h, bytes memory sigs, uint256 i) internal pure returns (address o) {
        uint8 v;
        bytes32 r;
        bytes32 s;
        assembly {
            let p := add(add(sigs, 32), mul(i, 65))
            r := mload(p)
            s := mload(add(p, 32))
            v := byte(0, mload(add(p, 64)))
        }
        if (v == 0 || v == 1) o = address(uint160(uint256(r)));
        else if (v > 30) o = ecrecover(keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", h)), v - 4, r, s);
        else o = ecrecover(h, v, r, s);
    }

    /// The owners bound to the two present devices must both be among the first `threshold` signers
    /// that Safe.checkNSignatures consumed.
    function _requireSigners(bytes32 h, bytes memory sigs, address oA, address oB) internal view {
        uint256 t = ISafeView(msg.sender).getThreshold();
        bool seenA;
        bool seenB;
        for (uint256 i; i < t; i++) {
            address o = _signer(h, sigs, i);
            if (o == oA) seenA = true;
            if (o == oB) seenB = true;
        }
        if (!seenA || !seenB) revert PresentOwnersMustSign();
    }

    /// Device-agnostic verifier: at least two of the counted signers (distinct, Safe sorts them) must own a
    /// registered device. Guardians (no device) can't stand in for a phone owner.
    function _requireDeviceOwnerSigners(bytes32 h, bytes memory sigs) internal view {
        uint256 t = ISafeView(msg.sender).getThreshold();
        uint256 k;
        for (uint256 i; i < t; i++) {
            if (deviceCount[msg.sender][_signer(h, sigs, i)] != 0) k++;
        }
        if (k < 2) revert PresentOwnersMustSign();
    }

    /// Threshold floor 2 for every owner-management call (threshold 1 would let one key act alone).
    function _thresholdOk(bytes4 sel, bytes memory data) internal pure returns (bool) {
        if (sel == CHANGE_THRESHOLD) return data.length == 36 && _word(data, 4) >= 2;
        if (sel == ADD_OWNER) return data.length == 68 && _word(data, 36) >= 2;
        if (sel == REMOVE_OWNER) return data.length == 100 && _word(data, 68) >= 2;
        return true;
    }

    function _isRecovery(address safe, address to, uint256 value, bytes memory data) internal view returns (bool) {
        if (value != 0 || data.length < 4) return false;
        bytes4 sel = bytes4(data);
        if (to == address(this)) {
            return sel == this.addDevice.selector || sel == this.removeDevice.selector
                || sel == this.replaceDevice.selector || sel == this.setIssuer.selector;
        }
        if (to == safe) {
            if (sel == SET_GUARD) return data.length == 36 && _word(data, 4) == 0;
            if (sel == SWAP_OWNER) return data.length == 100;
            if (sel == ADD_OWNER || sel == REMOVE_OWNER || sel == CHANGE_THRESHOLD) return _thresholdOk(sel, data);
        }
        return false;
    }

    function _word(bytes memory data, uint256 off) internal pure returns (uint256 w) {
        assembly {
            w := mload(add(add(data, 32), off))
        }
    }
}

/// Delegatecalled by Safe.setup(to = this, data = setup(...)); runs in the Safe's context, so the guard is
/// in place in the creation tx (never an unguarded moment).
contract PopSafeSetup {
    bytes32 internal constant GUARD_SLOT = 0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8;

    event ChangedGuard(address indexed guard);

    function setup(
        address guard,
        uint256 qx,
        uint256 qy,
        uint32 delay,
        uint32 grace,
        bytes32[] calldata devs,
        address[] calldata owners
    ) external {
        assembly {
            sstore(GUARD_SLOT, guard)
        }
        emit ChangedGuard(guard);
        PopSafeGuard(guard).initSafe(qx, qy, delay, grace, devs, owners);
    }
}
