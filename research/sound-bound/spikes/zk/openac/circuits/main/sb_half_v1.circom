pragma circom 2.2.3;
include "../sb.circom";
component main {public [nonceHi, nonceLo, attempt, issuerX, issuerY, sr, roleB, validAt]} = SBHalf(1, 1);
