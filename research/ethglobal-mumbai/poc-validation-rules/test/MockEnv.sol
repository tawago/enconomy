// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {FrameEnv} from "../src/frame/FrameEnv.sol";

/// Test-only FrameEnv: the "transaction" lives in storage the test writes. No forge-std.
abstract contract MockEnv is FrameEnv {
    mapping(uint256 => uint256) public mTx;
    mapping(uint256 => mapping(uint256 => uint256)) public mFrame;
    mapping(uint256 => mapping(uint256 => bytes32)) public mFrameData;
    mapping(uint256 => mapping(uint256 => uint256)) public mSig;
    mapping(uint256 => mapping(uint256 => uint256)) public mRoot;
    uint256 public approvedScope;

    function setTx(uint256 id, uint256 v) external {
        mTx[id] = v;
    }

    function setFrame(uint256 i, uint256 p, uint256 v) external {
        mFrame[i][p] = v;
    }

    function setFrameData(uint256 i, uint256 off, bytes32 v) external {
        mFrameData[i][off] = v;
    }

    function setSig(uint256 i, uint256 p, uint256 v) external {
        mSig[i][p] = v;
    }

    function setRoot(uint256 i, uint256 f, uint256 v) external {
        mRoot[i][f] = v;
    }

    function _txParam(uint256 id) internal view override returns (uint256) {
        return mTx[id];
    }

    function _frameParam(uint256 i, uint256 p) internal view override returns (uint256) {
        return mFrame[i][p];
    }

    function _frameDataLoad(uint256 i, uint256 off) internal view override returns (bytes32) {
        return mFrameData[i][off];
    }

    function _sigParam(uint256 i, uint256 p) internal view override returns (uint256) {
        return mSig[i][p];
    }

    function _recentRoot(uint256 i, uint256 f) internal view override returns (uint256) {
        return mRoot[i][f];
    }

    function _approve(uint256 scope) internal override {
        approvedScope = scope;
    }
}
