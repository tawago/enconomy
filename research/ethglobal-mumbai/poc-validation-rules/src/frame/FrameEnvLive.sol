// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnv} from "./FrameEnv.sol";

/// FrameEnv on a real EIP-8141 chain: one raw-bytecode helper per opcode, deployed in the constructor.
///
/// Every helper is `PUSH word1, PUSH word0, <OPCODE>, return 32 bytes`, so calldata word0 ends on the top
/// of the stack. Creation code = 13-byte copier + runtime (layout copied from the forshtat hegota-support package 0.0.1
/// HelperCode.sol, ERC8421_WORKSHOP; RECENTROOTREFLOAD is new here because that package has no 0xB6 helper).
///
/// Mempool notes (sidecar frameTx.ts @ 2e22ff0a):
///   - helpers have code > 2 bytes, so CODE_ACCESS passes; they touch no storage.
///   - read helpers are STATICCALLed; APPROVE is DELEGATECALLed so it acts on this contract.
///   - solc puts GAS right before the call, which both the sidecar and ethrex allow.
abstract contract FrameEnvLive is FrameEnv {
    address private immutable H_TXPARAM;
    address private immutable H_FRAMEPARAM;
    address private immutable H_FRAMEDATALOAD;
    address private immutable H_SIGPARAM;
    address private immutable H_RECENTROOT;
    address private immutable H_APPROVE;

    error HelperDeployFailed();
    error HelperCallFailed();

    constructor() {
        // runtime: 600035 b0 600052 60206000f3            TXPARAM(word0)
        H_TXPARAM = _deploy(hex"600c600d600039600c6000f3fe600035b060005260206000f3");
        // runtime: 602035 600035 b3 ...                    FRAMEPARAM stack [param, frameIndex], frameIndex on top
        H_FRAMEPARAM = _deploy(hex"600f600d600039600f6000f3fe602035600035b360005260206000f3");
        // runtime: 602035 600035 b1 ...                    FRAMEDATALOAD stack [offset, frameIndex], offset on top
        H_FRAMEDATALOAD = _deploy(hex"600f600d600039600f6000f3fe602035600035b160005260206000f3");
        // runtime: 602035 600035 b4 ...                    SIGPARAM stack [param, sigIndex], sigIndex on top
        H_SIGPARAM = _deploy(hex"600f600d600039600f6000f3fe602035600035b460005260206000f3");
        // runtime: 602035 600035 b6 ...                    RECENTROOTREFLOAD stack [field, index], field on top
        H_RECENTROOT = _deploy(hex"600f600d600039600f6000f3fe602035600035b660005260206000f3");
        // runtime: 600035 6000 80 aa                       APPROVE stack [offset=0, length=0, scope]
        H_APPROVE = _deploy(hex"6007600d60003960076000f3fe600035600080aa");
    }

    function _txParam(uint256 id) internal view override returns (uint256) {
        return _read(H_TXPARAM, abi.encode(id));
    }

    function _frameParam(uint256 frameIndex, uint256 param) internal view override returns (uint256) {
        return _read(H_FRAMEPARAM, abi.encode(frameIndex, param));
    }

    function _frameDataLoad(uint256 frameIndex, uint256 offset) internal view override returns (bytes32) {
        return bytes32(_read(H_FRAMEDATALOAD, abi.encode(offset, frameIndex)));
    }

    function _sigParam(uint256 sigIndex, uint256 param) internal view override returns (uint256) {
        return _read(H_SIGPARAM, abi.encode(sigIndex, param));
    }

    function _recentRoot(uint256 refIndex, uint256 field) internal view override returns (uint256) {
        return _read(H_RECENTROOT, abi.encode(field, refIndex));
    }

    function _approve(uint256 scope) internal override {
        (bool ok,) = H_APPROVE.delegatecall(abi.encode(scope));
        if (!ok) revert HelperCallFailed();
    }

    function _read(address helper, bytes memory operands) private view returns (uint256 word) {
        (bool ok, bytes memory out) = helper.staticcall(operands);
        if (!ok || out.length != 32) revert HelperCallFailed();
        word = abi.decode(out, (uint256));
    }

    function _deploy(bytes memory creationCode) private returns (address helper) {
        assembly ("memory-safe") {
            helper := create(0, add(creationCode, 0x20), mload(creationCode))
        }
        if (helper == address(0)) revert HelperDeployFailed();
    }
}
