// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// Runs verifyPresence inside a plain tx so the result lands on chain as an event. `data` is the whole
/// verifyPresence calldata. Same idea as contracts/zk/src/VerifyLog.sol. Holds nothing.
contract PresenceLog {
    event Presence(address indexed adapter, bytes32 indexed dataHash, bytes4 ret, uint256 gasUsed);

    function run(address adapter, bytes calldata data) external returns (bytes4 ret) {
        uint256 g = gasleft();
        (bool ok, bytes memory out) = adapter.staticcall(data);
        uint256 used = g - gasleft();
        if (!ok) {
            assembly ("memory-safe") {
                revert(add(out, 32), mload(out))
            }
        }
        ret = abi.decode(out, (bytes4));
        emit Presence(adapter, keccak256(data), ret, used);
    }
}
