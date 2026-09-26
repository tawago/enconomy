// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
import "forge-std/Test.sol"; import "../src/PresenceSink.sol";
contract SinkTest is Test {
  PresenceSink p; uint256 constant LEAF = 11011320419327886381298776674271937664568292783180157783978689262892574625042;
  bytes32 constant PT = bytes32(uint256(0x3333333333333333333333333333333333333333333333333333333333333333));
  function setUp() public { p = new PresenceSink(0xd360332fad9bc83afaff4a740de8a516bf1b8fb3fde360ff1d03979c1f943ee2, 0xe8a66007fd276b0271265c6db092c4a0c5eb8c45fdc436502c8a095f5d5745f2); assertEq(address(p), 0x5615dEB798BB3E4dFa0139dFa1b3D433Cc23b72f); assertEq(block.chainid, 480); vm.warp(1789999000); }
  function test_digest() public view { assertEq(p.digest(LEAF, PT, 1790000000), bytes32(0xcf8db6e6efb8aade57d4e3c37fbc30f447ba14ac1bd97cb11bd2d776a3d6e1aa)); }
  function test_post_anyone() public { vm.prank(address(0xBEEF)); uint g = gasleft(); p.postPresence(LEAF, PT, 1790000000, bytes32(0x2574031bfc8914399f4dc43902d0a96014bb337b461e5adb883237e9f4dd87e6), bytes32(0x001d26379d439e5012655df797902a44a7afe8cfd45b5746367657eac9c35c58)); console.log("gas", g - gasleft()); assertTrue(p.posted(LEAF)); }
  function test_dup() public { p.postPresence(LEAF, PT, 1790000000, bytes32(0x2574031bfc8914399f4dc43902d0a96014bb337b461e5adb883237e9f4dd87e6), bytes32(0x001d26379d439e5012655df797902a44a7afe8cfd45b5746367657eac9c35c58)); vm.expectRevert(abi.encodeWithSelector(PresenceSink.LeafAlreadyPosted.selector, LEAF)); p.postPresence(LEAF, PT, 1790000000, bytes32(0x2574031bfc8914399f4dc43902d0a96014bb337b461e5adb883237e9f4dd87e6), bytes32(0x001d26379d439e5012655df797902a44a7afe8cfd45b5746367657eac9c35c58)); }
  function test_wrong_leaf() public { vm.expectRevert(PresenceSink.BadAttestation.selector); p.postPresence(LEAF+1, PT, 1790000000, bytes32(0x2574031bfc8914399f4dc43902d0a96014bb337b461e5adb883237e9f4dd87e6), bytes32(0x001d26379d439e5012655df797902a44a7afe8cfd45b5746367657eac9c35c58)); }
  function test_expired() public { vm.warp(1790000001); vm.expectRevert(abi.encodeWithSelector(PresenceSink.Expired.selector, uint64(1790000000))); p.postPresence(LEAF, PT, 1790000000, bytes32(0x2574031bfc8914399f4dc43902d0a96014bb337b461e5adb883237e9f4dd87e6), bytes32(0x001d26379d439e5012655df797902a44a7afe8cfd45b5746367657eac9c35c58)); }
}
