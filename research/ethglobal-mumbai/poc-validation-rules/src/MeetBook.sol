// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// The user action in a ChirpGas tx (frame 3, SENDER mode, caller = the sender account).
/// ChirpGasSponsor pins this frame: target, selector, length 68, and (partner, transcript) equal to the
/// attestation, so the event says exactly what the sponsor checked.
contract MeetBook {
    event Met(address indexed account, address indexed partnerDevice, bytes32 transcript);

    mapping(address account => uint256) public meetings;

    function met(address partnerDevice, bytes32 transcript) external {
        unchecked {
            meetings[msg.sender]++;
        }
        emit Met(msg.sender, partnerDevice, transcript);
    }
}
