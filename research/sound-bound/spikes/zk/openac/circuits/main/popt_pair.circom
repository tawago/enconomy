pragma circom 2.2.3;
include "../popt.circom";
component main {public [nonceHi, nonceLo, attempt, issuerX, issuerY, validAt, srA, srB]} = PoptPairMain();
