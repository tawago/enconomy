// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnv} from "./frame/FrameEnv.sol";
import {FrameEnvLive} from "./frame/FrameEnvLive.sol";
import {FrameEnvLiveMux} from "./frame/FrameEnvLiveMux.sol";

/// Sender account for a phone whose key is a hardware P-256 key.
///
/// Why a contract at all: ethrex default code (opcode_handlers/frame_tx.rs execute_default_verify) only
/// approves when the signature entry is SECP256K1. A P-256-only device therefore needs code.
///
/// Validation footprint: zero SLOADs (owner is an immutable), no precompile (the protocol verified the
/// P-256 signature before any frame ran, 6,700 gas counted in the verify budget). It only reads its own
/// signature entry with SIGPARAM. Passes every ERC-8421 storage rule staked or not.
abstract contract P256AccountLogic is FrameEnv {
    /// keccak256(qx || qy)[12:], the address EIP-8141 resolves a P256 signer to.
    address public immutable owner;

    error NotOwner();
    error NotP256();
    error NotSigHash();

    constructor(address owner_) {
        owner = owner_;
    }

    /// VERIFY frame entry. Signature entry 0 must be the owner over the canonical sig hash, which
    /// commits to every frame (ERC-8421 security note: approval covers all later SENDER frames).
    function _verifyFrame() internal {
        if (_sigParam(0, SP_SCHEME) != SCHEME_P256) revert NotP256();
        if (address(uint160(_sigParam(0, SP_SIGNER))) != owner) revert NotOwner();
        if (_sigParam(0, SP_MSG) != 0) revert NotSigHash();
        // only_verify frames allow EXECUTION; self_verify frames allow both. Approve what the frame allows.
        _approve(_frameParam(_txParam(TX_CURRENT_FRAME), FP_ALLOWED_SCOPE));
    }
}

contract P256Account is P256AccountLogic, FrameEnvLive {
    constructor(address owner_) payable P256AccountLogic(owner_) {}

    fallback() external payable {
        if (msg.sender == ENTRY_POINT) _verifyFrame();
        // SENDER frames call the account as itself; a real wallet would dispatch calls here.
    }

    // No receive(): a VERIFY frame with empty data would land there and never APPROVE. The payable
    // fallback takes plain ETH too.
}

/// Same account on the one-helper FrameEnvLiveMux (ChirpGas build target for frame 1).
contract P256AccountMux is P256AccountLogic, FrameEnvLiveMux {
    constructor(address owner_) payable P256AccountLogic(owner_) {}

    fallback() external payable {
        if (msg.sender == ENTRY_POINT) _verifyFrame();
    }
}
