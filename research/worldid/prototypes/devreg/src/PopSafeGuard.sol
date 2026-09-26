// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

interface ISafeView {
    function nonce() external view returns (uint256);
    function isOwner(address) external view returns (bool);
    function getTransactionHash(
        address to, uint256 value, bytes calldata data, uint8 operation,
        uint256 safeTxGas, uint256 baseGas, uint256 gasPrice, address gasToken,
        address refundReceiver, uint256 _nonce
    ) external view returns (bytes32);
}

/// One guard instance serves many Safes; all state is keyed by the Safe (msg.sender).
///
/// Device id onchain: dev = sha256(pubkey65), pubkey65 = 0x04||X||Y (SEC1 uncompressed P-256),
/// i.e. the full 32 bytes whose first 16 bytes are the server's device_id.
///
/// Attestation tail appended to execTransaction `signatures` (172 bytes, last bytes of the blob):
///   pairTag(32) || devA(32) || devB(32) || expiry(u64 BE, 8) || r(32) || s(32) || "POP2"(4)
/// Issuer signs (P-256, prehashed):
///   sha256("pop-safe-v2" || chainId(32) || safe(20) || safeTxHash(32) || pairTag || devA || devB || expiry(8))
contract PopSafeGuard {
    bytes4 constant MAGIC = 0x504f5032; // "POP2"
    uint256 constant TAIL = 172;
    address constant P256 = address(0x100);
    address constant MSCO_141 = 0x9641d764fc13c8B624c04430C7356C1C7C8102e2; // MultiSendCallOnly 1.4.1
    address constant MSCO_150 = 0xA83c336B20401Af773B6219BA5027174338D1836; // MultiSendCallOnly 1.5.0

    struct Cfg { uint256 qx; uint256 qy; uint32 delay; bool init; }

    mapping(address => Cfg) public cfg;
    mapping(address => mapping(bytes32 => address)) public deviceOwner; // safe => dev => owner
    mapping(address => mapping(bytes32 => uint256)) public readyAt;     // safe => safeTxHash => time

    event DeviceSet(address indexed safe, bytes32 indexed dev, address owner);
    event Announced(address indexed safe, bytes32 indexed safeTxHash, uint256 readyAt, address by);
    event Cancelled(address indexed safe, bytes32 indexed safeTxHash);

    error NotInit(); error AlreadyInit(); error NotOwner(); error BadDevice();
    error NoAttestation(); error Expired(); error BadAttestation();
    error UnknownDevice(); error SameOwner(); error DelegateCallNotAllowed(); error NotRecoveryTx(); error TooEarly();

    modifier onlySafe() { if (!cfg[msg.sender].init) revert NotInit(); _; }

    // ---------------- config (always msg.sender == the Safe) ----------------

    /// Called once per Safe, from inside Safe.setup via PopSafeSetup (delegatecall -> call, msg.sender = safe).
    function initSafe(uint256 qx, uint256 qy, uint32 delay, bytes32[] calldata devs, address[] calldata owners) external {
        Cfg storage c = cfg[msg.sender];
        if (c.init) revert AlreadyInit();
        c.qx = qx; c.qy = qy; c.delay = delay; c.init = true;
        if (devs.length != owners.length) revert BadDevice();
        for (uint256 i; i < devs.length; i++) _setDevice(devs[i], owners[i]);
    }

    function addDevice(bytes32 dev, address owner) external onlySafe { _setDevice(dev, owner); }

    function removeDevice(bytes32 dev) external onlySafe {
        delete deviceOwner[msg.sender][dev];
        emit DeviceSet(msg.sender, dev, address(0));
    }

    /// One call for the common "phone reinstalled" case: new key replaces the old one for the same owner.
    function replaceDevice(bytes32 oldDev, bytes32 newDev) external onlySafe {
        address o = deviceOwner[msg.sender][oldDev];
        if (o == address(0)) revert UnknownDevice();
        delete deviceOwner[msg.sender][oldDev];
        emit DeviceSet(msg.sender, oldDev, address(0));
        _setDevice(newDev, o);
    }

    function setIssuer(uint256 qx, uint256 qy) external onlySafe { cfg[msg.sender].qx = qx; cfg[msg.sender].qy = qy; }

    function _setDevice(bytes32 dev, address owner) internal {
        if (dev == bytes32(0)) revert BadDevice();
        if (!ISafeView(msg.sender).isOwner(owner)) revert NotOwner();
        deviceOwner[msg.sender][dev] = owner;
        emit DeviceSet(msg.sender, dev, owner);
    }

    // ---------------- escape hatch ----------------

    /// Any current owner (EOA or contract that can call) announces a recovery tx by its safeTxHash.
    function announce(address safe, bytes32 safeTxHash) external {
        Cfg storage c = cfg[safe];
        if (!c.init) revert NotInit();
        if (!ISafeView(safe).isOwner(msg.sender)) revert NotOwner();
        uint256 t = block.timestamp + c.delay;
        readyAt[safe][safeTxHash] = t;
        emit Announced(safe, safeTxHash, t, msg.sender);
    }

    /// Owners veto an announcement (a normal PoP-gated Safe tx).
    function cancel(bytes32 safeTxHash) external onlySafe {
        delete readyAt[msg.sender][safeTxHash];
        emit Cancelled(msg.sender, safeTxHash);
    }

    // ---------------- guard ----------------

    function supportsInterface(bytes4 id) external pure returns (bool) { return id == 0xe6d7a83a || id == 0x01ffc9a7; }

    function digest(uint256 chainId, address safe, bytes32 safeTxHash, bytes32 pairTag, bytes32 devA, bytes32 devB, uint64 expiry)
        public pure returns (bytes32)
    {
        return sha256(abi.encodePacked("pop-safe-v2", chainId, safe, safeTxHash, pairTag, devA, devB, expiry));
    }

    function checkTransaction(
        address to, uint256 value, bytes memory data, uint8 operation,
        uint256 safeTxGas, uint256 baseGas, uint256 gasPrice, address gasToken,
        address payable refundReceiver, bytes memory signatures, address
    ) external view {
        Cfg storage c = cfg[msg.sender];
        if (!c.init) revert NotInit();
        if (operation == 1 && to != MSCO_141 && to != MSCO_150) revert DelegateCallNotAllowed();
        bytes32 h = ISafeView(msg.sender).getTransactionHash(
            to, value, data, operation, safeTxGas, baseGas, gasPrice, gasToken, refundReceiver,
            ISafeView(msg.sender).nonce() - 1
        );

        // escape hatch: announced + delay elapsed + recovery-only call
        uint256 ra = readyAt[msg.sender][h];
        if (ra != 0) {
            if (block.timestamp < ra) revert TooEarly();
            if (!_isRecovery(to, value, data, operation)) revert NotRecoveryTx();
            return;
        }

        (bytes32 pairTag, bytes32 devA, bytes32 devB, uint64 expiry) = _verifyTail(c, h, signatures);
        if (block.timestamp > expiry) revert Expired();
        if (devA == devB) revert SameOwner();

        address oA = deviceOwner[msg.sender][devA];
        address oB = deviceOwner[msg.sender][devB];
        pairTag; // bound in the digest; checked offchain against World ID nullifiers

        if (oA != address(0) && oB != address(0)) {
            if (oA == oB) revert SameOwner();
            // a device of a removed owner no longer counts
            if (!ISafeView(msg.sender).isOwner(oA) || !ISafeView(msg.sender).isOwner(oB)) revert UnknownDevice();
            return;
        }
        // re-enroll by meeting: exactly one side unknown, and the tx only adds THAT device
        // for an owner different from the known side's owner.
        if (oA == address(0) && oB == address(0)) revert UnknownDevice();
        (bytes32 newDev, address witness) = oA == address(0) ? (devA, oB) : (devB, oA);
        if (!ISafeView(msg.sender).isOwner(witness)) revert UnknownDevice();
        if (to != address(this) || value != 0 || operation != 0 || data.length < 4) revert UnknownDevice();
        bytes4 sel = bytes4(data);
        address forOwner;
        if (sel == this.addDevice.selector && data.length == 68) {
            (bytes32 d, address o) = abi.decode(_args(data), (bytes32, address));
            if (d != newDev) revert UnknownDevice();
            forOwner = o;
        } else if (sel == this.replaceDevice.selector && data.length == 68) {
            (bytes32 oldD, bytes32 d) = abi.decode(_args(data), (bytes32, bytes32));
            if (d != newDev) revert UnknownDevice();
            forOwner = deviceOwner[msg.sender][oldD];
        } else revert UnknownDevice();
        if (forOwner == witness) revert SameOwner();
    }

    function checkAfterExecution(bytes32, bool) external pure {}

    function _verifyTail(Cfg storage c, bytes32 h, bytes memory sigs)
        internal view returns (bytes32 pairTag, bytes32 devA, bytes32 devB, uint64 expiry)
    {
        uint256 n = sigs.length;
        if (n < TAIL) revert NoAttestation();
        bytes32 r; bytes32 s; bytes4 magic;
        assembly {
            let p := add(add(sigs, 32), sub(n, 172))
            pairTag := mload(p)
            devA := mload(add(p, 32))
            devB := mload(add(p, 64))
            expiry := shr(192, mload(add(p, 96)))
            r := mload(add(p, 104))
            s := mload(add(p, 136))
            magic := mload(add(p, 168))
        }
        if (magic != MAGIC) revert NoAttestation();
        bytes32 d = digest(block.chainid, msg.sender, h, pairTag, devA, devB, expiry);
        (bool ok, bytes memory ret) = P256.staticcall(abi.encode(d, r, s, c.qx, c.qy));
        if (!ok || ret.length != 32 || abi.decode(ret, (uint256)) != 1) revert BadAttestation();
    }

    function _isRecovery(address to, uint256 value, bytes memory data, uint8 operation) internal view returns (bool) {
        if (value != 0 || operation != 0 || data.length < 4) return false;
        bytes4 sel = bytes4(data);
        if (to == address(this)) {
            return sel == this.addDevice.selector || sel == this.removeDevice.selector
                || sel == this.replaceDevice.selector || sel == this.setIssuer.selector;
        }
        if (to == msg.sender) {
            // setGuard(0) only; owner management (swapOwner 0xe318b52b, addOwnerWithThreshold 0x0d582f13,
            // removeOwner 0xf8dc5dd9, changeThreshold 0x694e80c3) for device-bound owners
            if (sel == 0xe19a9dd9) return data.length == 36 && abi.decode(_args(data), (address)) == address(0);
            return sel == 0xe318b52b || sel == 0x0d582f13 || sel == 0xf8dc5dd9 || sel == 0x694e80c3;
        }
        return false;
    }

    function _args(bytes memory data) internal pure returns (bytes memory out) {
        out = new bytes(data.length - 4);
        for (uint256 i; i < out.length; i++) out[i] = data[i + 4];
    }
}

/// Delegatecalled by Safe.setup(to = this, data = setup(...)). Runs in the Safe's context:
/// writes the guard slot, then calls guard.initSafe as the Safe. One tx: the factory's createProxyWithNonce.
contract PopSafeSetup {
    bytes32 constant GUARD_SLOT = 0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8;
    event ChangedGuard(address indexed guard);

    function setup(address guard, uint256 qx, uint256 qy, uint32 delay, bytes32[] calldata devs, address[] calldata owners) external {
        assembly { sstore(GUARD_SLOT, guard) }
        emit ChangedGuard(guard);
        PopSafeGuard(guard).initSafe(qx, qy, delay, devs, owners);
    }
}
