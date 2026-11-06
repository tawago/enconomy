// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import {Test} from "forge-std/Test.sol";
import {MeetResolver} from "../src/MeetResolver.sol";
import {IPermissionedRegistryLite} from "../src/interfaces/IPermissionedRegistryLite.sol";

contract MockRegistry is IPermissionedRegistryLite {
    mapping(uint256 => State) internal _states;

    function set(string memory label, Status status, uint256 resource, address owner) external {
        uint256 id = uint256(keccak256(bytes(label)));
        _states[id] = State(status, type(uint64).max, owner, id, resource);
    }

    function getState(uint256 anyId) external view returns (State memory) {
        return _states[anyId];
    }
}

contract MeetResolverTest is Test {
    string constant K_MET = "eth.enconomy.met";
    string constant K_MEETINGS = "eth.enconomy.meetings";
    string constant K_ZK = "eth.enconomy.zk";

    // abi.encodePacked("\x08enconomy\x03eth\x00")
    bytes constant PARENT_DNS = hex"08656e636f6e6f6d790365746800";

    address admin = address(0xA11CE);
    address attester = address(0xB0B);
    address stranger = address(0xBAD);
    address phone = address(0xCAFE);

    bytes32 parentNode;
    MockRegistry reg;
    MeetResolver r;

    bytes32 alice = keccak256("alice");
    bytes32 bob = keccak256("bob");
    bytes32 carol = keccak256("carol");
    bytes32 ghost = keccak256("ghost");
    bytes32 m1 = keccak256("meeting-1");
    bytes32 m2 = keccak256("meeting-2");

    function setUp() public {
        parentNode = keccak256(abi.encodePacked(keccak256(abi.encodePacked(bytes32(0), keccak256("eth"))), keccak256("enconomy")));
        reg = new MockRegistry();
        r = new MeetResolver(reg, parentNode, PARENT_DNS, admin, attester, "Test Event", "https://site.test/");
        reg.set("alice", IPermissionedRegistryLite.Status.REGISTERED, 11, attester);
        reg.set("bob", IPermissionedRegistryLite.Status.REGISTERED, 22, attester);
        reg.set("carol", IPermissionedRegistryLite.Status.REGISTERED, 33, phone);
        vm.startPrank(attester);
    }

    function _counts(bytes32 lh) internal view returns (uint32 met, uint32 meetings, uint32 zk) {
        (, met, meetings, zk) = r.countsOf(lh);
    }

    function _dns(string memory label) internal pure returns (bytes memory) {
        return abi.encodePacked(uint8(bytes(label).length), label, PARENT_DNS);
    }

    function _text(string memory label, string memory key) internal view returns (string memory) {
        bytes memory data = abi.encodeWithSelector(bytes4(0x59d1d43c), bytes32(0), key);
        return abi.decode(r.resolve(_dns(label), data), (string));
    }

    // ---- record, firstTime

    function test_record_first_then_repeat() public {
        assertTrue(r.record(m1, alice, bob, 100, keccak256("ev")));
        (uint32 met, uint32 meetings, uint32 zk) = _counts(alice);
        assertEq(met, 1);
        assertEq(meetings, 1);
        assertEq(zk, 0);

        // the same pair in the other order is still the same pair
        assertFalse(r.record(m2, bob, alice, 101, keccak256("ev2")));
        (met, meetings,) = _counts(alice);
        assertEq(met, 1);
        assertEq(meetings, 2);
        (met, meetings,) = _counts(bob);
        assertEq(met, 1);
        assertEq(meetings, 2);

        assertTrue(r.record(keccak256("m3"), alice, carol, 102, keccak256("ev3")));
        (met, meetings,) = _counts(alice);
        assertEq(met, 2);
        assertEq(meetings, 3);
    }

    function test_record_emits_met() public {
        bytes32 pairKey = keccak256(abi.encode(uint256(11), uint256(22)));
        vm.expectEmit(true, true, true, true, address(r));
        emit MeetResolver.Met(m1, r.nodeOf(alice), r.nodeOf(bob), pairKey, 100, keccak256("ev"), true);
        r.record(m1, bob, alice, 100, keccak256("ev"));
    }

    function test_record_same_name_refused() public {
        vm.expectRevert(MeetResolver.SameName.selector);
        r.record(m1, alice, alice, 100, bytes32(0));

        // two labels on one registry resource are one name too
        reg.set("alias", IPermissionedRegistryLite.Status.REGISTERED, 11, attester);
        vm.expectRevert(MeetResolver.SameName.selector);
        r.record(m1, alice, keccak256("alias"), 100, bytes32(0));
    }

    function test_record_duplicate_refused() public {
        r.record(m1, alice, bob, 100, bytes32(0));
        vm.expectRevert(abi.encodeWithSelector(MeetResolver.DuplicateMeeting.selector, m1));
        r.record(m1, alice, carol, 100, bytes32(0));
    }

    function test_record_not_registered_refused() public {
        vm.expectRevert(abi.encodeWithSelector(MeetResolver.NotRegistered.selector, ghost));
        r.record(m1, ghost, bob, 100, bytes32(0));
        vm.expectRevert(abi.encodeWithSelector(MeetResolver.NotRegistered.selector, ghost));
        r.record(m1, alice, ghost, 100, bytes32(0));

        reg.set("reserved", IPermissionedRegistryLite.Status.RESERVED, 44, attester);
        vm.expectRevert(abi.encodeWithSelector(MeetResolver.NotRegistered.selector, keccak256("reserved")));
        r.record(m1, alice, keccak256("reserved"), 100, bytes32(0));
    }

    // ---- who may write

    function test_unauthorized() public {
        r.record(m1, alice, bob, 100, bytes32(0));
        vm.stopPrank();
        vm.startPrank(stranger);

        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.record(m2, alice, bob, 100, bytes32(0));
        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.touch("alice");
        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.markZkVerified(m1);
        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.voidMeeting(m1);
        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.multicall(new bytes[](0));
        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.setAttester(stranger);
        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.setAdmin(stranger);
        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.setSite("x", "y");
    }

    function test_admin_is_not_attester_but_may_void() public {
        r.record(m1, alice, bob, 100, bytes32(0));
        vm.stopPrank();
        vm.startPrank(admin);

        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.record(m2, alice, bob, 100, bytes32(0));
        vm.expectRevert(MeetResolver.Unauthorized.selector);
        r.markZkVerified(m1);

        r.voidMeeting(m1);
        (,, bool exists,, bool voided) = _meeting(m1);
        assertTrue(exists);
        assertTrue(voided);
    }

    function _meeting(bytes32 id) internal view returns (uint256, uint256, bool, bool, bool) {
        return r.meetingOf(id);
    }

    // ---- zk

    function test_mark_zk_once() public {
        r.record(m1, alice, bob, 100, bytes32(0));
        vm.expectEmit(true, false, false, false, address(r));
        emit MeetResolver.ZkVerified(m1);
        r.markZkVerified(m1);
        r.markZkVerified(m1); // no second count

        (,, uint32 zk) = _counts(alice);
        assertEq(zk, 1);
        (,, zk) = _counts(bob);
        assertEq(zk, 1);
        (,,, bool isZk,) = _meeting(m1);
        assertTrue(isZk);
    }

    function test_mark_zk_unknown_meeting() public {
        vm.expectRevert(abi.encodeWithSelector(MeetResolver.UnknownMeeting.selector, m1));
        r.markZkVerified(m1);
    }

    function test_mark_zk_after_void_does_nothing() public {
        r.record(m1, alice, bob, 100, bytes32(0));
        r.voidMeeting(m1);
        r.markZkVerified(m1);
        (,, uint32 zk) = _counts(alice);
        assertEq(zk, 0);
    }

    // ---- void

    function test_void_keeps_met_while_the_pair_has_another_meeting() public {
        r.record(m1, alice, bob, 100, bytes32(0));
        r.record(m2, alice, bob, 101, bytes32(0));
        r.markZkVerified(m1);

        r.voidMeeting(m1);
        r.voidMeeting(m1); // no second decrement
        (uint32 met, uint32 meetings, uint32 zk) = _counts(alice);
        assertEq(met, 1);
        assertEq(meetings, 1);
        assertEq(zk, 0);

        r.voidMeeting(m2);
        (met, meetings, zk) = _counts(bob);
        assertEq(met, 0);
        assertEq(meetings, 0);
        assertEq(zk, 0);
    }

    function test_void_unknown_meeting() public {
        vm.expectRevert(abi.encodeWithSelector(MeetResolver.UnknownMeeting.selector, m1));
        r.voidMeeting(m1);
    }

    function test_voided_id_stays_used() public {
        r.record(m1, alice, bob, 100, bytes32(0));
        r.voidMeeting(m1);
        vm.expectRevert(abi.encodeWithSelector(MeetResolver.DuplicateMeeting.selector, m1));
        r.record(m1, alice, bob, 100, bytes32(0));
    }

    // ---- text counters

    function test_text_counters_follow_the_writes() public {
        assertEq(_text("alice", K_MET), "0");
        assertEq(_text("alice", K_MEETINGS), "0");
        assertEq(_text("alice", K_ZK), "0");

        r.record(m1, alice, bob, 100, bytes32(0));
        r.record(m2, alice, bob, 101, bytes32(0));
        r.markZkVerified(m1);
        assertEq(_text("alice", K_MET), "1");
        assertEq(_text("alice", K_MEETINGS), "2");
        assertEq(_text("alice", K_ZK), "1");
        assertEq(_text("alice", "description"), unicode"Met 1 hacker at Test Event · acoustic proof of presence");

        r.record(keccak256("m3"), alice, carol, 102, bytes32(0));
        assertEq(_text("alice", K_MET), "2");
        assertEq(_text("alice", "description"), unicode"Met 2 hackers at Test Event · acoustic proof of presence");
        assertEq(_text("alice", "url"), "https://site.test/?name=alice.enconomy.eth");

        r.voidMeeting(m1);
        assertEq(_text("alice", K_MEETINGS), "2");
        assertEq(_text("alice", K_ZK), "0");
    }

    function test_text_is_empty_when_not_registered() public view {
        assertEq(_text("ghost", K_MET), "");
        assertEq(_text("ghost", "description"), "");
    }

    function test_counters_follow_the_registry_resource() public {
        r.record(m1, alice, bob, 100, bytes32(0));
        assertEq(_text("alice", K_MET), "1");

        // alice expired and someone else registered the label: new resource, clean counters
        reg.set("alice", IPermissionedRegistryLite.Status.REGISTERED, 99, attester);
        assertEq(_text("alice", K_MET), "0");
    }

    function test_parent_text() public view {
        bytes memory data = abi.encodeWithSelector(bytes4(0x59d1d43c), parentNode, "description");
        assertEq(abi.decode(r.resolve(PARENT_DNS, data), (string)), unicode"Test Event · proof-of-presence names");
    }

    function test_unknown_profile_refused() public {
        vm.expectRevert(abi.encodeWithSelector(MeetResolver.UnsupportedResolverProfile.selector, bytes4(0xdeadbeef)));
        r.resolve(_dns("alice"), hex"deadbeef");
    }

    // ---- touch, addr

    function test_touch_emits_records() public {
        vm.expectEmit(true, true, false, true, address(r));
        emit MeetResolver.Member(r.nodeOf(alice), alice, "alice");
        vm.expectEmit(true, true, false, true, address(r));
        emit MeetResolver.TextChanged(r.nodeOf(alice), K_MET, K_MET, "0");
        r.touch("alice");

        vm.expectRevert(abi.encodeWithSelector(MeetResolver.NotRegistered.selector, ghost));
        r.touch("ghost");
    }

    function test_addr_empty_for_custodial_names() public view {
        bytes memory data = abi.encodeWithSelector(bytes4(0x3b3b57de), bytes32(0));
        assertEq(abi.decode(r.resolve(_dns("alice"), data), (address)), address(0));
        assertEq(abi.decode(r.resolve(_dns("carol"), data), (address)), phone);
    }
}
