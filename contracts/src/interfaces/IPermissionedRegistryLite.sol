// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

/// Subset of ENSv2 IPermissionedRegistry (contracts-v2 commit 71a3b733).
interface IPermissionedRegistryLite {
    enum Status {
        AVAILABLE,
        RESERVED,
        REGISTERED
    }

    struct State {
        Status status;
        uint64 expiry;
        address latestOwner;
        uint256 tokenId;
        uint256 resource;
    }

    function getState(uint256 anyId) external view returns (State memory);
}
