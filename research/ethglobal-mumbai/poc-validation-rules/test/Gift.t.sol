// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {MockEnv} from "./MockEnv.sol";
import {TestBase} from "./Vm.sol";
import {GiftP256AccountLogic} from "../src/GiftP256Account.sol";
import {P256AccountLogic} from "../src/P256Account.sol";
import {MeetBook} from "../src/MeetBook.sol";

contract GiftHarness is GiftP256AccountLogic, MockEnv {
    constructor(address owner_) P256AccountLogic(owner_) {}

    function gift(uint256 cap) external {
        _gift(cap);
    }

    function verify() external {
        _verifyFrame();
    }
}

/// W4 Gas Gift: B's account (this harness, owner KB) pays for A's tx. Logic on MockEnv.
contract GiftTest is TestBase {
    address constant A = address(0xA11CE); // A's account (tx.sender)
    address constant KA = address(0xAA01); // A's device
    address constant KB = address(0xBB01); // B's device = owner of the gift account
    bytes32 constant TRANSCRIPT = keccak256("acoustic transcript");
    uint256 constant DEADLINE = 1793560702;
    uint256 constant CAP = 0.001 ether;
    uint256 constant KEY = 0; // legacy nonce lane: A's first tx is nonce_keys = [0], seq 0
    bytes32 constant KEYS_HASH = keccak256(abi.encode(uint256(1), KEY));

    GiftHarness g;
    MeetBook mb;
    bytes body;

    function _setup() internal {
        g = new GiftHarness(KB);
        mb = new MeetBook();
        body = abi.encodeCall(MeetBook.met, (KB, TRANSCRIPT));
        g.setTx(0x0A, 2);
        g.setTx(0x09, 4);
        g.setTx(0x0B, 2);
        g.setTx(0x02, uint160(A));
        g.setTx(0x01, 0);
        g.setTx(0x0E, 1);
        g.setTx(0x0F, uint256(KEYS_HASH));
        g.setTx(0x10, KEY);
        g.setTx(0x06, 0.0005 ether);
        g.setFrame(0, 0, uint160(address(0x8141)));
        g.setFrame(0, 2, 1);
        g.setFrameData(0, 0, bytes32(DEADLINE << 192));
        g.setFrame(1, 0, uint160(A));
        g.setFrame(2, 0x06, 1); // gift frame: flags = 1, payment only
        _setBody(address(mb), body);
        g.setSig(0, 0, uint160(KA));
        g.setSig(0, 1, 2);
        g.setSig(1, 0, uint160(KB));
        g.setSig(1, 1, 2);
        _signB(A, KEYS_HASH, 0, DEADLINE, CAP, address(mb), body);
    }

    function _setBody(address target, bytes memory data) internal {
        g.setFrame(3, 0, uint160(target));
        g.setFrame(3, 2, 2); // SENDER
        g.setFrame(3, 4, data.length);
        for (uint256 off = 0; off < data.length; off += 32) {
            g.setFrameData(3, off, _word(data, off));
        }
    }

    function _signB(address sender, bytes32 kh, uint256 seq, uint256 dl, uint256 cap, address t, bytes memory data)
        internal
    {
        g.setSig(1, 2, uint256(g.giftDigest(sender, kh, seq, dl, cap, keccak256(abi.encodePacked(t, data)))));
    }

    function _ok() internal {
        vm.prank(EP);
        g.gift(CAP);
        require(g.approvedScope() == 1, "not approved");
    }

    function _fail(bytes4 err) internal {
        _failCap(CAP, err);
    }

    function _failCap(uint256 cap, bytes4 err) internal {
        vm.prank(EP);
        vm.expectRevert(err);
        g.gift(cap);
    }

    // ---------------------------------------------------------------------------------------------
    function test_gift_happyPath() public {
        _setup();
        _ok();
    }

    function test_gift_maxCostAtCap() public {
        _setup();
        g.setTx(0x06, CAP);
        _ok();
    }

    function test_gift_maxCostOverCap() public {
        _setup();
        g.setTx(0x06, CAP + 1);
        _fail(GiftP256AccountLogic.GiftTooExpensive.selector);
    }

    function test_gift_capInDataNotSigned() public {
        _setup(); // A raises cap in frame 2 data: D no longer matches
        _failCap(1 ether, GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_notEntryPoint() public {
        _setup();
        vm.expectRevert(GiftP256AccountLogic.NotEntryPoint.selector);
        g.gift(CAP);
    }

    function test_gift_wrongSigner() public {
        _setup();
        g.setSig(1, 0, uint160(address(0xCC01)));
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_secpEntry() public {
        _setup();
        g.setSig(1, 1, 1);
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_sigHashEntryRejected() public {
        _setup(); // B over the canonical sig hash (msg empty) is not a gift
        g.setSig(1, 2, 0);
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_otherSender() public {
        _setup(); // B's gift to A, replayed by C's account
        address c = address(0xC0C);
        g.setTx(0x02, uint160(c));
        g.setFrame(1, 0, uint160(c));
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_otherSeq() public {
        _setup(); // one gift = one tx: seq 1 needs a new signature
        g.setTx(0x01, 1);
        _fail(GiftP256AccountLogic.GiftSig.selector);
        _signB(A, KEYS_HASH, 1, DEADLINE, CAP, address(mb), body);
        _ok();
    }

    function test_gift_otherNonceKey() public {
        _setup(); // same seq on another lane is another tx
        uint256 k = 7;
        g.setTx(0x10, k);
        g.setTx(0x0F, uint256(keccak256(abi.encode(uint256(1), k))));
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_otherBody() public {
        _setup(); // A swaps the call (last word is byte 64..67, past the second word)
        _setBody(address(mb), abi.encodeCall(MeetBook.met, (KB, keccak256("other"))));
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_otherBodyTarget() public {
        _setup();
        _setBody(address(0xBAD), body);
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_longerDeadline() public {
        _setup();
        g.setFrameData(0, 0, bytes32((DEADLINE + 1) << 192));
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_noExpiryFrame() public {
        _setup();
        g.setFrame(0, 0, uint160(address(0xBAD)));
        _fail(GiftP256AccountLogic.GiftNoExpiry.selector);
    }

    function test_gift_expiryNotVerify() public {
        _setup();
        g.setFrame(0, 2, 0);
        _fail(GiftP256AccountLogic.GiftNoExpiry.selector);
    }

    function test_gift_scopeNotPayment() public {
        _setup(); // gift frame with flags 2 or 3: refuse, never approve execution for someone else
        g.setFrame(2, 0x06, 2);
        _fail(GiftP256AccountLogic.GiftLayout.selector);
        g.setFrame(2, 0x06, 3);
        _fail(GiftP256AccountLogic.GiftLayout.selector);
    }

    function test_gift_frame1NotSender() public {
        _setup();
        g.setFrame(1, 0, uint160(address(0xBAD)));
        _fail(GiftP256AccountLogic.GiftLayout.selector);
    }

    function test_gift_wrongFrameIndex() public {
        _setup();
        g.setTx(0x0A, 1);
        _fail(GiftP256AccountLogic.GiftLayout.selector);
    }

    function test_gift_extraFrame() public {
        _setup();
        g.setTx(0x09, 5);
        _fail(GiftP256AccountLogic.GiftLayout.selector);
    }

    function test_gift_extraSig() public {
        _setup();
        g.setTx(0x0B, 3);
        _fail(GiftP256AccountLogic.GiftLayout.selector);
    }

    function test_gift_bodyNotSender() public {
        _setup();
        g.setFrame(3, 2, 0); // DEFAULT mode
        _fail(GiftP256AccountLogic.GiftLayout.selector);
    }

    function test_gift_otherChain() public {
        _setup();
        vm.chainId(1);
        _fail(GiftP256AccountLogic.GiftSig.selector);
    }

    function test_gift_otherAccountSameOwner() public {
        _setup(); // B's second account (same device key) can't reuse the gift: D commits to address(this)
        bytes32 d = bytes32(g.mSig(1, 2));
        GiftHarness g2 = new GiftHarness(KB);
        g2.setTx(0x0A, 2);
        g2.setTx(0x09, 4);
        g2.setTx(0x0B, 2);
        g2.setTx(0x02, uint160(A));
        g2.setTx(0x0F, uint256(KEYS_HASH));
        g2.setTx(0x06, 0.0005 ether);
        g2.setFrame(0, 0, uint160(address(0x8141)));
        g2.setFrame(0, 2, 1);
        g2.setFrameData(0, 0, bytes32(DEADLINE << 192));
        g2.setFrame(1, 0, uint160(A));
        g2.setFrame(2, 0x06, 1);
        g2.setFrame(3, 0, uint160(address(mb)));
        g2.setFrame(3, 2, 2);
        g2.setFrame(3, 4, body.length);
        for (uint256 off = 0; off < body.length; off += 32) {
            g2.setFrameData(3, off, _word(body, off));
        }
        g2.setSig(1, 0, uint160(KB));
        g2.setSig(1, 1, 2);
        g2.setSig(1, 2, uint256(d));
        vm.prank(EP);
        vm.expectRevert(GiftP256AccountLogic.GiftSig.selector);
        g2.gift(CAP);
    }

    /// The owner path is the plain P256AccountMux path, unchanged by the gift branch.
    function test_gift_ownerPathStillWorks() public {
        g = new GiftHarness(KB);
        g.setTx(0x0A, 0);
        g.setFrame(0, 0x06, 2);
        g.setSig(0, 0, uint160(KB));
        g.setSig(0, 1, 2);
        g.verify();
        require(g.approvedScope() == 2, "owner path");
    }

    /// A's entry 0 can't drive B's owner path: in A's tx, entry 0 is A.
    function test_gift_ownerPathNotFromA() public {
        g = new GiftHarness(KB);
        g.setTx(0x0A, 2);
        g.setFrame(2, 0x06, 1);
        g.setSig(0, 0, uint160(KA));
        g.setSig(0, 1, 2);
        vm.expectRevert(P256AccountLogic.NotOwner.selector);
        g.verify();
    }
}
