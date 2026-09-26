// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IHonkVerifier} from "../../src/interfaces/IPopPresenceVerifier.sol";

/// Stand-in for a bb UltraHonk verifier: accepts iff `ok` and the public input count matches.
/// Burns `burn` gas per call to model the real verifier cost in guard-path gas tests.
contract MockHonkVerifier is IHonkVerifier {
    bool public ok = true;
    uint256 public immutable nPublic;
    uint256 public burn;

    constructor(uint256 n) {
        nPublic = n;
    }

    function set(bool ok_, uint256 burn_) external {
        ok = ok_;
        burn = burn_;
    }

    function verify(bytes calldata, bytes32[] calldata pub) external view returns (bool) {
        uint256 end = gasleft() > burn ? gasleft() - burn : 0;
        while (gasleft() > end) {}
        return ok && pub.length == nPublic;
    }
}
