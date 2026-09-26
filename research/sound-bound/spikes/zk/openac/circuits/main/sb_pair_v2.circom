pragma circom 2.2.3;
include "../sb.circom";
component main {public [nonceHi, nonceLo, attempt, issuerX, issuerY, sr, dLo, dHi, validAt]} = SBPair(1, 2);
