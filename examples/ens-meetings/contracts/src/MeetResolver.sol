// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import {IPermissionedRegistryLite} from "./interfaces/IPermissionedRegistryLite.sol";

/// @title MeetResolver
/// @notice ENSIP-10 resolver for <parent> and every <label>.<parent> in our UserRegistry.
///         Stores acoustic proof-of-presence meetings and serves counters as live text records.
///         Every read and write is gated on the registry state, keyed by registry `resource`.
contract MeetResolver {
    // ---- errors
    error UnsupportedResolverProfile(bytes4 selector);
    error NotRegistered(bytes32 labelhash);
    error SameName();
    error DuplicateMeeting(bytes32 meetingId);
    error UnknownMeeting(bytes32 meetingId);
    error Unauthorized();

    // ---- events
    event TextChanged(bytes32 indexed node, string indexed indexedKey, string key, string value);
    event Member(bytes32 indexed node, bytes32 indexed labelhash, string label);
    event Met(
        bytes32 indexed meetingId,
        bytes32 indexed nodeLo,
        bytes32 indexed nodeHi,
        bytes32 pairKey,
        uint32 timeBucket,
        bytes32 evidence,
        bool firstTime
    );
    event ZkVerified(bytes32 indexed meetingId);
    event MeetVoided(bytes32 indexed meetingId);
    event AttesterChanged(address attester);
    event SiteChanged(string eventName, string siteUrl);

    // ---- keys
    string internal constant K_MET = "eth.enconomy.met";
    string internal constant K_MEETINGS = "eth.enconomy.meetings";
    string internal constant K_ZK = "eth.enconomy.zk";
    string internal constant K_DESCRIPTION = "description";
    string internal constant K_URL = "url";

    bytes4 internal constant SEL_TEXT = 0x59d1d43c; // text(bytes32,string)
    bytes4 internal constant SEL_ADDR = 0x3b3b57de; // addr(bytes32)
    bytes4 internal constant SEL_ADDR_COIN = 0xf1cb7e06; // addr(bytes32,uint256)

    // ---- config
    IPermissionedRegistryLite public immutable REG;
    bytes32 public immutable PARENT_NODE;
    bytes32 public immutable PARENT_DNS_HASH;
    uint256 public immutable DEPLOY_BLOCK;
    address public admin;
    address public attester;
    string public eventName;
    string public siteUrl;

    // ---- state (keyed by registry resource)
    // `void` is a reserved word in Solidity, so the flag is named `voided`.
    struct Meeting {
        uint256 resLo;
        uint256 resHi;
        bool exists;
        bool zk;
        bool voided;
    }

    mapping(uint256 => uint32) public met;
    mapping(uint256 => uint32) public meetings;
    mapping(uint256 => uint32) public zkMeetings;
    mapping(bytes32 => uint32) public pairCount;
    mapping(bytes32 => Meeting) public meetingOf;
    /// labelhashes of a meeting in (lo, hi) resource order; used only to emit TextChanged.
    mapping(bytes32 => bytes32[2]) internal _labelsOf;
    /// DNS-encoded parent, for building `url` values in touch().
    bytes internal _parentDnsBytes;

    modifier onlyAttester() {
        if (msg.sender != attester) revert Unauthorized();
        _;
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    constructor(
        IPermissionedRegistryLite reg,
        bytes32 parentNode,
        bytes memory parentDns,
        address admin_,
        address attester_,
        string memory eventName_,
        string memory siteUrl_
    ) {
        REG = reg;
        PARENT_NODE = parentNode;
        PARENT_DNS_HASH = keccak256(parentDns);
        _parentDnsBytes = parentDns;
        DEPLOY_BLOCK = block.number;
        admin = admin_;
        attester = attester_;
        eventName = eventName_;
        siteUrl = siteUrl_;
        emit AttesterChanged(attester_);
        emit SiteChanged(eventName_, siteUrl_);
    }

    // ------------------------------------------------------------------ writes

    function touch(string calldata label) external onlyAttester {
        bytes32 lh = keccak256(bytes(label));
        IPermissionedRegistryLite.State memory s = REG.getState(uint256(lh));
        if (s.status != IPermissionedRegistryLite.Status.REGISTERED) revert NotRegistered(lh);
        bytes32 node = nodeOf(lh);
        emit Member(node, lh, label);
        _emitText(node, K_MET, _dec(met[s.resource]));
        _emitText(node, K_MEETINGS, _dec(meetings[s.resource]));
        _emitText(node, K_ZK, _dec(zkMeetings[s.resource]));
        _emitText(node, K_DESCRIPTION, _description(met[s.resource]));
        _emitText(node, K_URL, string.concat(siteUrl, "?name=", label, ".", _dnsToDotted(_parentDns())));
    }

    function record(bytes32 meetingId, bytes32 labelhashA, bytes32 labelhashB, uint32 timeBucket, bytes32 evidence)
        external
        onlyAttester
        returns (bool firstTime)
    {
        if (meetingOf[meetingId].exists) revert DuplicateMeeting(meetingId);
        uint256 ra = _resourceOrRevert(labelhashA);
        uint256 rb = _resourceOrRevert(labelhashB);
        if (ra == rb) revert SameName();

        (uint256 lo, uint256 hi, bytes32 lhLo, bytes32 lhHi) =
            ra < rb ? (ra, rb, labelhashA, labelhashB) : (rb, ra, labelhashB, labelhashA);
        bytes32 pairKey = keccak256(abi.encode(lo, hi));

        firstTime = pairCount[pairKey] == 0;
        if (firstTime) {
            met[lo]++;
            met[hi]++;
        }
        pairCount[pairKey]++;
        meetings[lo]++;
        meetings[hi]++;
        meetingOf[meetingId] = Meeting(lo, hi, true, false, false);
        _labelsOf[meetingId] = [lhLo, lhHi];

        bytes32 nodeLo = nodeOf(lhLo);
        bytes32 nodeHi = nodeOf(lhHi);
        emit Met(meetingId, nodeLo, nodeHi, pairKey, timeBucket, evidence, firstTime);
        _emitCounts(nodeLo, lo);
        _emitCounts(nodeHi, hi);
    }

    function markZkVerified(bytes32 meetingId) external onlyAttester {
        Meeting storage m = meetingOf[meetingId];
        if (!m.exists) revert UnknownMeeting(meetingId);
        if (m.zk || m.voided) return;
        m.zk = true;
        zkMeetings[m.resLo]++;
        zkMeetings[m.resHi]++;
        emit ZkVerified(meetingId);
        bytes32[2] memory lhs = _labelsOf[meetingId];
        _emitText(nodeOf(lhs[0]), K_ZK, _liveCount(lhs[0], 2));
        _emitText(nodeOf(lhs[1]), K_ZK, _liveCount(lhs[1], 2));
    }

    function voidMeeting(bytes32 meetingId) external {
        if (msg.sender != admin && msg.sender != attester) revert Unauthorized();
        Meeting storage m = meetingOf[meetingId];
        if (!m.exists) revert UnknownMeeting(meetingId);
        if (m.voided) return;
        m.voided = true;
        uint256 lo = m.resLo;
        uint256 hi = m.resHi;
        meetings[lo]--;
        meetings[hi]--;
        if (m.zk) {
            zkMeetings[lo]--;
            zkMeetings[hi]--;
        }
        bytes32 pairKey = keccak256(abi.encode(lo, hi));
        if (--pairCount[pairKey] == 0) {
            met[lo]--;
            met[hi]--;
        }
        emit MeetVoided(meetingId);
        bytes32[2] memory lhs = _labelsOf[meetingId];
        _emitLive(lhs[0]);
        _emitLive(lhs[1]);
    }

    function multicall(bytes[] calldata calls) external onlyAttester returns (bytes[] memory results) {
        results = new bytes[](calls.length);
        for (uint256 i; i < calls.length; ++i) {
            (bool ok, bytes memory ret) = address(this).delegatecall(calls[i]);
            if (!ok) {
                assembly ("memory-safe") {
                    revert(add(ret, 32), mload(ret))
                }
            }
            results[i] = ret;
        }
    }

    function setAttester(address a) external onlyAdmin {
        attester = a;
        emit AttesterChanged(a);
    }

    function setAdmin(address a) external onlyAdmin {
        admin = a;
    }

    function setSite(string calldata eventName_, string calldata siteUrl_) external onlyAdmin {
        eventName = eventName_;
        siteUrl = siteUrl_;
        emit SiteChanged(eventName_, siteUrl_);
    }

    // ------------------------------------------------------------------ reads

    function supportsInterface(bytes4 id) external pure returns (bool) {
        return id == 0x01ffc9a7 // ERC-165
            || id == 0x9061b923 // IExtendedResolver (ENSIP-10)
            || id == 0x582de3e7; // IERC7996
    }

    /// ERC-7996: we support no optional features. Declaring the interface makes the UR call us directly.
    function supportsFeature(bytes4) external pure returns (bool) {
        return false;
    }

    function nodeOf(bytes32 labelhash) public view returns (bytes32) {
        return keccak256(abi.encodePacked(PARENT_NODE, labelhash));
    }

    function countsOf(bytes32 labelhash)
        external
        view
        returns (bool registered, uint32 met_, uint32 meetings_, uint32 zk_)
    {
        IPermissionedRegistryLite.State memory s = REG.getState(uint256(labelhash));
        if (s.status != IPermissionedRegistryLite.Status.REGISTERED) return (false, 0, 0, 0);
        return (true, met[s.resource], meetings[s.resource], zkMeetings[s.resource]);
    }

    function resolve(bytes calldata name, bytes calldata data) external view returns (bytes memory) {
        if (data.length < 4) revert UnsupportedResolverProfile(bytes4(0));
        bytes4 sel = bytes4(data[:4]);
        if (sel != SEL_TEXT && sel != SEL_ADDR && sel != SEL_ADDR_COIN) revert UnsupportedResolverProfile(sel);

        // parent itself
        if (keccak256(name) == PARENT_DNS_HASH) {
            if (sel != SEL_TEXT) return _emptyFor(sel);
            (, string memory k) = abi.decode(data[4:], (bytes32, string));
            bytes32 kh = keccak256(bytes(k));
            if (kh == keccak256(bytes(K_DESCRIPTION))) {
                return abi.encode(string.concat(eventName, unicode" · proof-of-presence names"));
            }
            if (kh == keccak256(bytes(K_URL))) return abi.encode(siteUrl);
            return abi.encode("");
        }

        // exactly one label under the parent
        if (name.length == 0) return _emptyFor(sel);
        uint256 len = uint8(name[0]);
        if (len == 0 || name.length < 1 + len || keccak256(name[1 + len:]) != PARENT_DNS_HASH) {
            return _emptyFor(sel);
        }
        IPermissionedRegistryLite.State memory s = REG.getState(uint256(keccak256(name[1:1 + len])));
        if (s.status != IPermissionedRegistryLite.Status.REGISTERED) return _emptyFor(sel);

        if (sel == SEL_TEXT) {
            (, string memory k) = abi.decode(data[4:], (bytes32, string));
            return abi.encode(_textFor(s.resource, k, name));
        }
        // addr: custodial mode (owner is our attester key) returns empty
        if (s.latestOwner == attester) return _emptyFor(sel);
        if (sel == SEL_ADDR) return abi.encode(s.latestOwner);
        (, uint256 coinType) = abi.decode(data[4:], (bytes32, uint256));
        if (coinType == 60) return abi.encode(abi.encodePacked(s.latestOwner));
        return abi.encode(bytes(""));
    }

    // ------------------------------------------------------------------ internals

    function _textFor(uint256 r, string memory k, bytes calldata name) internal view returns (string memory) {
        bytes32 kh = keccak256(bytes(k));
        if (kh == keccak256(bytes(K_MET))) return _dec(met[r]);
        if (kh == keccak256(bytes(K_MEETINGS))) return _dec(meetings[r]);
        if (kh == keccak256(bytes(K_ZK))) return _dec(zkMeetings[r]);
        if (kh == keccak256(bytes(K_DESCRIPTION))) return _description(met[r]);
        if (kh == keccak256(bytes(K_URL))) return string.concat(siteUrl, "?name=", _dnsToDotted(name));
        return "";
    }

    function _emptyFor(bytes4 sel) internal pure returns (bytes memory) {
        if (sel == SEL_TEXT) return abi.encode("");
        if (sel == SEL_ADDR) return abi.encode(address(0));
        return abi.encode(bytes(""));
    }

    function _resourceOrRevert(bytes32 lh) internal view returns (uint256) {
        IPermissionedRegistryLite.State memory s = REG.getState(uint256(lh));
        if (s.status != IPermissionedRegistryLite.Status.REGISTERED) revert NotRegistered(lh);
        return s.resource;
    }

    function _emitCounts(bytes32 node, uint256 r) internal {
        _emitText(node, K_MET, _dec(met[r]));
        _emitText(node, K_MEETINGS, _dec(meetings[r]));
        _emitText(node, K_DESCRIPTION, _description(met[r]));
    }

    /// Emit the values a resolve() would return right now (the label may have been re-registered since).
    function _emitLive(bytes32 lh) internal {
        bytes32 node = nodeOf(lh);
        IPermissionedRegistryLite.State memory s = REG.getState(uint256(lh));
        if (s.status != IPermissionedRegistryLite.Status.REGISTERED) {
            _emitText(node, K_MET, "");
            _emitText(node, K_MEETINGS, "");
            _emitText(node, K_ZK, "");
            _emitText(node, K_DESCRIPTION, "");
            return;
        }
        uint256 r = s.resource;
        _emitText(node, K_MET, _dec(met[r]));
        _emitText(node, K_MEETINGS, _dec(meetings[r]));
        _emitText(node, K_ZK, _dec(zkMeetings[r]));
        _emitText(node, K_DESCRIPTION, _description(met[r]));
    }

    /// which: 2 = zk. Current live value for a labelhash ("" if not registered).
    function _liveCount(bytes32 lh, uint8 which) internal view returns (string memory) {
        IPermissionedRegistryLite.State memory s = REG.getState(uint256(lh));
        if (s.status != IPermissionedRegistryLite.Status.REGISTERED) return "";
        if (which == 0) return _dec(met[s.resource]);
        if (which == 1) return _dec(meetings[s.resource]);
        return _dec(zkMeetings[s.resource]);
    }

    function _emitText(bytes32 node, string memory key, string memory value) internal {
        emit TextChanged(node, key, key, value);
    }

    function _description(uint32 n) internal view returns (string memory) {
        return string.concat(
            "Met ", _dec(n), n == 1 ? " hacker at " : " hackers at ", eventName, unicode" · acoustic proof of presence"
        );
    }

    function _parentDns() internal view returns (bytes memory) {
        return _parentDnsBytes;
    }

    function _dnsToDotted(bytes memory dns) internal pure returns (string memory) {
        bytes memory out = new bytes(dns.length);
        uint256 o;
        uint256 i;
        while (i < dns.length) {
            uint256 l = uint8(dns[i]);
            if (l == 0) break;
            if (o > 0) out[o++] = ".";
            for (uint256 j = 1; j <= l && i + j < dns.length; ++j) {
                out[o++] = dns[i + j];
            }
            i += l + 1;
        }
        assembly ("memory-safe") {
            mstore(out, o)
        }
        return string(out);
    }

    function _dec(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        uint256 t = v;
        uint256 d;
        while (t != 0) {
            d++;
            t /= 10;
        }
        bytes memory b = new bytes(d);
        while (v != 0) {
            b[--d] = bytes1(uint8(48 + v % 10));
            v /= 10;
        }
        return string(b);
    }
}
