// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// Frame-transaction introspection, as virtual functions.
///
/// solc cannot emit the EIP-8141 / EIP-8250 / EIP-8272 opcodes. `FrameEnvLive` implements these
/// functions with tiny raw-bytecode helper contracts (the same trick the forshtat hegota-support package uses).
/// Tests override them with a mock transaction. Contracts written against this base read no storage
/// for introspection: every value comes from the transaction envelope.
///
/// Ids follow ethrex eip8141-tracer @ 9aa3645d (docs/eip-8141.md, docs/eip-8250.md, docs/eip-8272.md).
abstract contract FrameEnv {
    // ---- TXPARAM (0xB0) ids -------------------------------------------------------------------
    uint256 internal constant TX_NONCE_SEQ = 0x01; // EIP-8250 re-points 0x01 to nonce_seq
    uint256 internal constant TX_SENDER = 0x02;
    uint256 internal constant TX_MAX_COST = 0x06; // ethrex: max_fee * total_gas_limit + blob cost
    uint256 internal constant TX_SIG_HASH = 0x08;
    uint256 internal constant TX_FRAME_COUNT = 0x09;
    uint256 internal constant TX_CURRENT_FRAME = 0x0A;
    uint256 internal constant TX_SIG_COUNT = 0x0B;
    uint256 internal constant TX_NONCE_KEY_COUNT = 0x0E; // EIP-8250
    uint256 internal constant TX_NONCE_KEYS_HASH = 0x0F; // EIP-8250: keccak(be32(len) || be32(k0) || ...)
    uint256 internal constant TX_NONCE_KEY_0 = 0x10; // EIP-8250
    uint256 internal constant TX_RECENT_ROOT_COUNT = 0x11; // EIP-8272

    // ---- FRAMEPARAM (0xB3) ids ----------------------------------------------------------------
    uint256 internal constant FP_TARGET = 0x00;
    uint256 internal constant FP_GAS_LIMIT = 0x01;
    uint256 internal constant FP_MODE = 0x02;
    uint256 internal constant FP_FLAGS = 0x03;
    uint256 internal constant FP_DATA_LEN = 0x04;
    uint256 internal constant FP_STATUS = 0x05; // 0 fail, 1 success, 2 skipped; halts for current/future frame
    uint256 internal constant FP_ALLOWED_SCOPE = 0x06;
    uint256 internal constant FP_VALUE = 0x08;

    // ---- SIGPARAM (0xB4) ids ------------------------------------------------------------------
    uint256 internal constant SP_SIGNER = 0x00;
    uint256 internal constant SP_SCHEME = 0x01;
    uint256 internal constant SP_MSG = 0x02; // 0 when the entry signs the canonical sig hash

    // ---- RECENTROOTREFLOAD (0xB6) fields -------------------------------------------------------
    uint256 internal constant RR_SOURCE_ID = 0;
    uint256 internal constant RR_SLOT = 1;
    uint256 internal constant RR_ROOT = 2;

    // ---- enums --------------------------------------------------------------------------------
    uint256 internal constant MODE_DEFAULT = 0;
    uint256 internal constant MODE_VERIFY = 1;
    uint256 internal constant MODE_SENDER = 2;
    uint256 internal constant SCHEME_SECP256K1 = 1;
    uint256 internal constant SCHEME_P256 = 2;
    uint256 internal constant SCOPE_PAYMENT = 1;
    uint256 internal constant SCOPE_EXECUTION = 2;
    uint256 internal constant SCOPE_EXECUTION_AND_PAYMENT = 3;

    // ---- predeploys ---------------------------------------------------------------------------
    address internal constant ENTRY_POINT = address(0xaa);
    address internal constant EXPIRY_VERIFIER = address(0x8141);
    address internal constant NONCE_MANAGER = address(0x8250);
    address internal constant RECENT_ROOT = address(0x8272);

    function _txParam(uint256 id) internal view virtual returns (uint256);
    function _frameParam(uint256 frameIndex, uint256 param) internal view virtual returns (uint256);
    function _frameDataLoad(uint256 frameIndex, uint256 offset) internal view virtual returns (bytes32);
    function _sigParam(uint256 sigIndex, uint256 param) internal view virtual returns (uint256);
    function _recentRoot(uint256 refIndex, uint256 field) internal view virtual returns (uint256);
    /// APPROVE ends the frame like RETURN. Code after it does not run on a real chain.
    function _approve(uint256 scope) internal virtual;

    /// EIP-8272: source_id = keccak256(source_address (20 bytes) || salt (32 bytes)).
    function _sourceId(address source, bytes32 salt) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(source, salt));
    }
}
