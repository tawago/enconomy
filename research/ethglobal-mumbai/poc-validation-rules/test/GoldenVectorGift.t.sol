// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {TestBase} from "./Vm.sol";
import {GiftP256Account} from "../src/GiftP256Account.sol";
import {MeetBook} from "../src/MeetBook.sol";

/// W4 Gas Gift: fixed inputs -> fixed body hash and D. poc/clients/gift-shape.cjs `selftest` asserts the same hex.
contract GoldenVectorGiftTest is TestBase {
    address constant GIFT = address(0x6177000000000000000000000000000000000001); // B's GiftP256Account
    address constant OWNER_B = address(0xBB01);
    address constant SENDER = address(0xA11CE);
    address constant MEETBOOK = address(0x3B00C);
    uint256 constant SEQ = 0;
    uint256 constant DEADLINE = 1793560702;
    uint256 constant CAP = 1e15; // 0.001 ETH
    bytes32 constant TRANSCRIPT = keccak256("acoustic transcript");

    bytes32 constant KEYS_HASH_GOLDEN = 0xada5013122d395ba3c54772283fb069b10426056ef8ca54750cb9bb552a59e7d;
    bytes32 constant BODY_HASH_GOLDEN = 0x13813530eaeba2b9648dea89989c95fa65993283ba4775bffd689cce9af97c63;
    bytes32 constant D_GOLDEN = 0xc77f12778f6c3f37fee637f9c37619c303edf19138bfff0833c0cb2146cabced;

    event log_named_bytes32(string key, bytes32 val);

    function test_goldenGift() public {
        vm.chainId(1337);
        GiftP256Account a = new GiftP256Account(OWNER_B);
        vm.etch(GIFT, address(a).code); // owner is an immutable, so the copy is the same account
        GiftP256Account g = GiftP256Account(payable(GIFT));
        require(g.owner() == OWNER_B, "owner");
        bytes32 keysHash = keccak256(abi.encode(uint256(1), uint256(0))); // nonce_keys = [0]
        bytes memory body = abi.encodeCall(MeetBook.met, (OWNER_B, TRANSCRIPT));
        bytes32 bodyHash = keccak256(abi.encodePacked(MEETBOOK, body));
        bytes32 d = g.giftDigest(SENDER, keysHash, SEQ, DEADLINE, CAP, bodyHash);
        emit log_named_bytes32("keysHash", keysHash);
        emit log_named_bytes32("bodyHash", bodyHash);
        emit log_named_bytes32("D", d);
        // independent recompute of the D layout
        bytes32 d2 = keccak256(
            abi.encode(keccak256("enconomy.Gift.v1"), uint256(1337), GIFT, SENDER, keysHash, SEQ, DEADLINE, CAP, bodyHash)
        );
        require(d == d2, "layout");
        require(keysHash == KEYS_HASH_GOLDEN, "keys hash drifted");
        require(bodyHash == BODY_HASH_GOLDEN, "body hash drifted");
        require(d == D_GOLDEN, "D drifted");
    }
}
