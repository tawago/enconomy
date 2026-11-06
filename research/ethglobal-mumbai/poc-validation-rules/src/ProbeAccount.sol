// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnv} from "./frame/FrameEnv.sol";
import {FrameEnvLive} from "./frame/FrameEnvLive.sol";

/// Precompile probe for a dry run (eth_estimateFrameTransactionGas), plan item 6.
/// Frames: [self_verify(this, flags=3)] (+ any SENDER frame). VERIFY STATICCALLs P256VERIFY (0x100) with a
/// known-good vector (go-ethereum p256Verify.json, first "expected 1" case = poc/clients/p256verify-vector.hex),
/// requires the 32-byte 1, then APPROVEs what the frame allows.
///
/// Expected on the live sidecar (precompiles: [], settled from source in ../notes/precompile-rule.md):
///   "payer accesses un-deployed contract address 0x0000000000000000000000000000000000000100 with opcode STATICCALL"
///   while ethrex_simulateFrameTransaction on the same tx reports the frame clean (ethrex allows precompile targets).
/// Reading the dry-run report:
///   - sidecar CODE_ACCESS violation on 0x..0100  -> the mempool bans the precompile (live precompiles: [])
///   - revert ProbeFailed(ok, len) with len == 0  -> the node has no 0x100 (empty account)
///   - green                                      -> P256VERIFY usable in VERIFY on that mempool
/// Only signatures[0].signer == owner is approved (any scheme), so nobody else can spend its gas money.
abstract contract ProbeAccountLogic is FrameEnv {
    address internal constant P256VERIFY = address(0x100);
    bytes internal constant VECTOR = hex"4cee90eb86eaa050036147a12d49004b6b9c72bd725d39d4785011fe190f0b4da73bd4903f0ce3b639bbbf6e8e80d16931ff4bcf5993d58468e8fb19086e8cac36dbcd03009df8c59286b162af3bd7fcc0450c9aa81be5d10d312af6c66b1d604aebd3099c618202fcfe16ae7770b0c49ab5eadf74b754204a3bb6060e44eff37618b065f9832de4ca6ca971a7a1adc826d0f7c00181a5fb2ddf79ae00b4e10e";

    address public immutable owner;

    error NotOwner();
    error ProbeFailed(bool ok, uint256 len);

    constructor(address owner_) {
        owner = owner_;
    }

    function _verifyFrame() internal {
        if (msg.sender != ENTRY_POINT) revert NotOwner();
        if (address(uint160(_sigParam(0, SP_SIGNER))) != owner) revert NotOwner();
        (bool ok, bytes memory out) = P256VERIFY.staticcall(VECTOR);
        if (!ok || out.length != 32 || abi.decode(out, (uint256)) != 1) revert ProbeFailed(ok, out.length);
        _approve(_frameParam(_txParam(TX_CURRENT_FRAME), FP_ALLOWED_SCOPE));
    }
}

contract ProbeAccount is ProbeAccountLogic, FrameEnvLive {
    constructor(address owner_) payable ProbeAccountLogic(owner_) {}

    fallback() external payable {
        if (msg.sender == ENTRY_POINT) _verifyFrame();
    }

    // No receive(): a VERIFY frame with empty data would land there and never APPROVE. The payable
    // fallback takes plain ETH too.
}
