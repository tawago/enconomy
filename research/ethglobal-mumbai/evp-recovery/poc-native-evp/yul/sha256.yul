object "Sha256Yul" {
  code { datacopy(0, dataoffset("runtime"), datasize("runtime")) return(0, datasize("runtime")) }
  object "runtime" {
    code {
      let hdr := calldataload(0)
      let len := sub(calldatasize(), 32)
      calldatacopy(4096, 32, len)
      let mode := and(hdr, 0xff)
      let withSd := and(shr(8, hdr), 0xff)
      let hd2 := and(shr(16, hdr), 0xffff)
      let ht := and(shr(32, hdr), 0xffff)
      let hk2 := and(shr(48, hdr), 0xffff)
      if eq(mode, 0) { mstore(0, sha1(0, len, 256, 3072)) return(0, 32) }
      if eq(mode, 1) { evp1(hd2, ht, hk2, withSd) return(0, 96) }
      if eq(mode, 4) { evp4(hd2, ht, hk2, withSd) return(0, 96) }
      revert(0, 0)

      function compress1(st, blk) {
                mstore(1024, and(shr(224, mload(add(blk, 0))), 0xffffffff))
                mstore(1056, and(shr(192, mload(add(blk, 0))), 0xffffffff))
                mstore(1088, and(shr(160, mload(add(blk, 0))), 0xffffffff))
                mstore(1120, and(shr(128, mload(add(blk, 0))), 0xffffffff))
                mstore(1152, and(shr(96, mload(add(blk, 0))), 0xffffffff))
                mstore(1184, and(shr(64, mload(add(blk, 0))), 0xffffffff))
                mstore(1216, and(shr(32, mload(add(blk, 0))), 0xffffffff))
                mstore(1248, and(shr(0, mload(add(blk, 0))), 0xffffffff))
                mstore(1280, and(shr(224, mload(add(blk, 32))), 0xffffffff))
                mstore(1312, and(shr(192, mload(add(blk, 32))), 0xffffffff))
                mstore(1344, and(shr(160, mload(add(blk, 32))), 0xffffffff))
                mstore(1376, and(shr(128, mload(add(blk, 32))), 0xffffffff))
                mstore(1408, and(shr(96, mload(add(blk, 32))), 0xffffffff))
                mstore(1440, and(shr(64, mload(add(blk, 32))), 0xffffffff))
                mstore(1472, and(shr(32, mload(add(blk, 32))), 0xffffffff))
                mstore(1504, and(shr(0, mload(add(blk, 32))), 0xffffffff))
        rounds1(st)
      }
      function compress4(st, p0, p1, p2, p3) {
                { let w0 := mload(add(p0, 0)) let w1 := mload(add(p1, 0)) let w2 := mload(add(p2, 0)) let w3 := mload(add(p3, 0))
                  mstore(1024, or(or(and(shr(224, w0), 0xffffffff), shl(64, and(shr(224, w1), 0xffffffff))), or(shl(128, and(shr(224, w2), 0xffffffff)), shl(192, and(shr(224, w3), 0xffffffff)))))
                  mstore(1056, or(or(and(shr(192, w0), 0xffffffff), shl(64, and(shr(192, w1), 0xffffffff))), or(shl(128, and(shr(192, w2), 0xffffffff)), shl(192, and(shr(192, w3), 0xffffffff)))))
                  mstore(1088, or(or(and(shr(160, w0), 0xffffffff), shl(64, and(shr(160, w1), 0xffffffff))), or(shl(128, and(shr(160, w2), 0xffffffff)), shl(192, and(shr(160, w3), 0xffffffff)))))
                  mstore(1120, or(or(and(shr(128, w0), 0xffffffff), shl(64, and(shr(128, w1), 0xffffffff))), or(shl(128, and(shr(128, w2), 0xffffffff)), shl(192, and(shr(128, w3), 0xffffffff)))))
                  mstore(1152, or(or(and(shr(96, w0), 0xffffffff), shl(64, and(shr(96, w1), 0xffffffff))), or(shl(128, and(shr(96, w2), 0xffffffff)), shl(192, and(shr(96, w3), 0xffffffff)))))
                  mstore(1184, or(or(and(shr(64, w0), 0xffffffff), shl(64, and(shr(64, w1), 0xffffffff))), or(shl(128, and(shr(64, w2), 0xffffffff)), shl(192, and(shr(64, w3), 0xffffffff)))))
                  mstore(1216, or(or(and(shr(32, w0), 0xffffffff), shl(64, and(shr(32, w1), 0xffffffff))), or(shl(128, and(shr(32, w2), 0xffffffff)), shl(192, and(shr(32, w3), 0xffffffff)))))
                  mstore(1248, or(or(and(shr(0, w0), 0xffffffff), shl(64, and(shr(0, w1), 0xffffffff))), or(shl(128, and(shr(0, w2), 0xffffffff)), shl(192, and(shr(0, w3), 0xffffffff)))))
                }
                { let w0 := mload(add(p0, 32)) let w1 := mload(add(p1, 32)) let w2 := mload(add(p2, 32)) let w3 := mload(add(p3, 32))
                  mstore(1280, or(or(and(shr(224, w0), 0xffffffff), shl(64, and(shr(224, w1), 0xffffffff))), or(shl(128, and(shr(224, w2), 0xffffffff)), shl(192, and(shr(224, w3), 0xffffffff)))))
                  mstore(1312, or(or(and(shr(192, w0), 0xffffffff), shl(64, and(shr(192, w1), 0xffffffff))), or(shl(128, and(shr(192, w2), 0xffffffff)), shl(192, and(shr(192, w3), 0xffffffff)))))
                  mstore(1344, or(or(and(shr(160, w0), 0xffffffff), shl(64, and(shr(160, w1), 0xffffffff))), or(shl(128, and(shr(160, w2), 0xffffffff)), shl(192, and(shr(160, w3), 0xffffffff)))))
                  mstore(1376, or(or(and(shr(128, w0), 0xffffffff), shl(64, and(shr(128, w1), 0xffffffff))), or(shl(128, and(shr(128, w2), 0xffffffff)), shl(192, and(shr(128, w3), 0xffffffff)))))
                  mstore(1408, or(or(and(shr(96, w0), 0xffffffff), shl(64, and(shr(96, w1), 0xffffffff))), or(shl(128, and(shr(96, w2), 0xffffffff)), shl(192, and(shr(96, w3), 0xffffffff)))))
                  mstore(1440, or(or(and(shr(64, w0), 0xffffffff), shl(64, and(shr(64, w1), 0xffffffff))), or(shl(128, and(shr(64, w2), 0xffffffff)), shl(192, and(shr(64, w3), 0xffffffff)))))
                  mstore(1472, or(or(and(shr(32, w0), 0xffffffff), shl(64, and(shr(32, w1), 0xffffffff))), or(shl(128, and(shr(32, w2), 0xffffffff)), shl(192, and(shr(32, w3), 0xffffffff)))))
                  mstore(1504, or(or(and(shr(0, w0), 0xffffffff), shl(64, and(shr(0, w1), 0xffffffff))), or(shl(128, and(shr(0, w2), 0xffffffff)), shl(192, and(shr(0, w3), 0xffffffff)))))
                }
        rounds4(st)
      }
      function rounds1(st) {
                { let sx := mload(1056) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1472) sd := or(sx, shl(32, sx))
                  mstore(1536, and(add(add(s0, mload(1024)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1312))), 0xffffffff)) }
                { let sx := mload(1088) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1504) sd := or(sx, shl(32, sx))
                  mstore(1568, and(add(add(s0, mload(1056)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1344))), 0xffffffff)) }
                { let sx := mload(1120) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1536) sd := or(sx, shl(32, sx))
                  mstore(1600, and(add(add(s0, mload(1088)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1376))), 0xffffffff)) }
                { let sx := mload(1152) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1568) sd := or(sx, shl(32, sx))
                  mstore(1632, and(add(add(s0, mload(1120)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1408))), 0xffffffff)) }
                { let sx := mload(1184) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1600) sd := or(sx, shl(32, sx))
                  mstore(1664, and(add(add(s0, mload(1152)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1440))), 0xffffffff)) }
                { let sx := mload(1216) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1632) sd := or(sx, shl(32, sx))
                  mstore(1696, and(add(add(s0, mload(1184)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1472))), 0xffffffff)) }
                { let sx := mload(1248) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1664) sd := or(sx, shl(32, sx))
                  mstore(1728, and(add(add(s0, mload(1216)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1504))), 0xffffffff)) }
                { let sx := mload(1280) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1696) sd := or(sx, shl(32, sx))
                  mstore(1760, and(add(add(s0, mload(1248)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1536))), 0xffffffff)) }
                { let sx := mload(1312) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1728) sd := or(sx, shl(32, sx))
                  mstore(1792, and(add(add(s0, mload(1280)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1568))), 0xffffffff)) }
                { let sx := mload(1344) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1760) sd := or(sx, shl(32, sx))
                  mstore(1824, and(add(add(s0, mload(1312)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1600))), 0xffffffff)) }
                { let sx := mload(1376) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1792) sd := or(sx, shl(32, sx))
                  mstore(1856, and(add(add(s0, mload(1344)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1632))), 0xffffffff)) }
                { let sx := mload(1408) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1824) sd := or(sx, shl(32, sx))
                  mstore(1888, and(add(add(s0, mload(1376)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1664))), 0xffffffff)) }
                { let sx := mload(1440) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1856) sd := or(sx, shl(32, sx))
                  mstore(1920, and(add(add(s0, mload(1408)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1696))), 0xffffffff)) }
                { let sx := mload(1472) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1888) sd := or(sx, shl(32, sx))
                  mstore(1952, and(add(add(s0, mload(1440)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1728))), 0xffffffff)) }
                { let sx := mload(1504) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1920) sd := or(sx, shl(32, sx))
                  mstore(1984, and(add(add(s0, mload(1472)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1760))), 0xffffffff)) }
                { let sx := mload(1536) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1952) sd := or(sx, shl(32, sx))
                  mstore(2016, and(add(add(s0, mload(1504)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1792))), 0xffffffff)) }
                { let sx := mload(1568) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(1984) sd := or(sx, shl(32, sx))
                  mstore(2048, and(add(add(s0, mload(1536)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1824))), 0xffffffff)) }
                { let sx := mload(1600) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2016) sd := or(sx, shl(32, sx))
                  mstore(2080, and(add(add(s0, mload(1568)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1856))), 0xffffffff)) }
                { let sx := mload(1632) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2048) sd := or(sx, shl(32, sx))
                  mstore(2112, and(add(add(s0, mload(1600)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1888))), 0xffffffff)) }
                { let sx := mload(1664) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2080) sd := or(sx, shl(32, sx))
                  mstore(2144, and(add(add(s0, mload(1632)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1920))), 0xffffffff)) }
                { let sx := mload(1696) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2112) sd := or(sx, shl(32, sx))
                  mstore(2176, and(add(add(s0, mload(1664)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1952))), 0xffffffff)) }
                { let sx := mload(1728) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2144) sd := or(sx, shl(32, sx))
                  mstore(2208, and(add(add(s0, mload(1696)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(1984))), 0xffffffff)) }
                { let sx := mload(1760) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2176) sd := or(sx, shl(32, sx))
                  mstore(2240, and(add(add(s0, mload(1728)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2016))), 0xffffffff)) }
                { let sx := mload(1792) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2208) sd := or(sx, shl(32, sx))
                  mstore(2272, and(add(add(s0, mload(1760)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2048))), 0xffffffff)) }
                { let sx := mload(1824) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2240) sd := or(sx, shl(32, sx))
                  mstore(2304, and(add(add(s0, mload(1792)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2080))), 0xffffffff)) }
                { let sx := mload(1856) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2272) sd := or(sx, shl(32, sx))
                  mstore(2336, and(add(add(s0, mload(1824)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2112))), 0xffffffff)) }
                { let sx := mload(1888) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2304) sd := or(sx, shl(32, sx))
                  mstore(2368, and(add(add(s0, mload(1856)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2144))), 0xffffffff)) }
                { let sx := mload(1920) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2336) sd := or(sx, shl(32, sx))
                  mstore(2400, and(add(add(s0, mload(1888)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2176))), 0xffffffff)) }
                { let sx := mload(1952) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2368) sd := or(sx, shl(32, sx))
                  mstore(2432, and(add(add(s0, mload(1920)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2208))), 0xffffffff)) }
                { let sx := mload(1984) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2400) sd := or(sx, shl(32, sx))
                  mstore(2464, and(add(add(s0, mload(1952)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2240))), 0xffffffff)) }
                { let sx := mload(2016) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2432) sd := or(sx, shl(32, sx))
                  mstore(2496, and(add(add(s0, mload(1984)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2272))), 0xffffffff)) }
                { let sx := mload(2048) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2464) sd := or(sx, shl(32, sx))
                  mstore(2528, and(add(add(s0, mload(2016)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2304))), 0xffffffff)) }
                { let sx := mload(2080) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2496) sd := or(sx, shl(32, sx))
                  mstore(2560, and(add(add(s0, mload(2048)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2336))), 0xffffffff)) }
                { let sx := mload(2112) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2528) sd := or(sx, shl(32, sx))
                  mstore(2592, and(add(add(s0, mload(2080)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2368))), 0xffffffff)) }
                { let sx := mload(2144) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2560) sd := or(sx, shl(32, sx))
                  mstore(2624, and(add(add(s0, mload(2112)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2400))), 0xffffffff)) }
                { let sx := mload(2176) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2592) sd := or(sx, shl(32, sx))
                  mstore(2656, and(add(add(s0, mload(2144)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2432))), 0xffffffff)) }
                { let sx := mload(2208) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2624) sd := or(sx, shl(32, sx))
                  mstore(2688, and(add(add(s0, mload(2176)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2464))), 0xffffffff)) }
                { let sx := mload(2240) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2656) sd := or(sx, shl(32, sx))
                  mstore(2720, and(add(add(s0, mload(2208)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2496))), 0xffffffff)) }
                { let sx := mload(2272) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2688) sd := or(sx, shl(32, sx))
                  mstore(2752, and(add(add(s0, mload(2240)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2528))), 0xffffffff)) }
                { let sx := mload(2304) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2720) sd := or(sx, shl(32, sx))
                  mstore(2784, and(add(add(s0, mload(2272)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2560))), 0xffffffff)) }
                { let sx := mload(2336) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2752) sd := or(sx, shl(32, sx))
                  mstore(2816, and(add(add(s0, mload(2304)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2592))), 0xffffffff)) }
                { let sx := mload(2368) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2784) sd := or(sx, shl(32, sx))
                  mstore(2848, and(add(add(s0, mload(2336)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2624))), 0xffffffff)) }
                { let sx := mload(2400) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2816) sd := or(sx, shl(32, sx))
                  mstore(2880, and(add(add(s0, mload(2368)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2656))), 0xffffffff)) }
                { let sx := mload(2432) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2848) sd := or(sx, shl(32, sx))
                  mstore(2912, and(add(add(s0, mload(2400)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2688))), 0xffffffff)) }
                { let sx := mload(2464) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2880) sd := or(sx, shl(32, sx))
                  mstore(2944, and(add(add(s0, mload(2432)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2720))), 0xffffffff)) }
                { let sx := mload(2496) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2912) sd := or(sx, shl(32, sx))
                  mstore(2976, and(add(add(s0, mload(2464)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2752))), 0xffffffff)) }
                { let sx := mload(2528) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2944) sd := or(sx, shl(32, sx))
                  mstore(3008, and(add(add(s0, mload(2496)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2784))), 0xffffffff)) }
                { let sx := mload(2560) let sd := or(sx, shl(32, sx)) let s0 := xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx))
                  sx := mload(2976) sd := or(sx, shl(32, sx))
                  mstore(3040, and(add(add(s0, mload(2528)), add(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), mload(2816))), 0xffffffff)) }
                let a := mload(st) let b := mload(add(st, 32)) let c := mload(add(st, 64)) let d := mload(add(st, 96))
                let e := mload(add(st, 128)) let f := mload(add(st, 160)) let g := mload(add(st, 192)) let h := mload(add(st, 224))
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(g, and(e, xor(f, g))), 0x428a2f98)), mload(1024))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff)
                  h := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(a, b), and(c, or(a, b))))), 0xffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(f, and(d, xor(e, f))), 0x71374491)), mload(1056))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff)
                  g := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(h, a), and(b, or(h, a))))), 0xffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(e, and(c, xor(d, e))), 0xb5c0fbcf)), mload(1088))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff)
                  f := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(g, h), and(a, or(g, h))))), 0xffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(d, and(b, xor(c, d))), 0xe9b5dba5)), mload(1120))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff)
                  e := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(f, g), and(h, or(f, g))))), 0xffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(c, and(a, xor(b, c))), 0x3956c25b)), mload(1152))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff)
                  d := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(e, f), and(g, or(e, f))))), 0xffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(b, and(h, xor(a, b))), 0x59f111f1)), mload(1184))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff)
                  c := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(d, e), and(f, or(d, e))))), 0xffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(a, and(g, xor(h, a))), 0x923f82a4)), mload(1216))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff)
                  b := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(c, d), and(e, or(c, d))))), 0xffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(h, and(f, xor(g, h))), 0xab1c5ed5)), mload(1248))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff)
                  a := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(b, c), and(d, or(b, c))))), 0xffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(g, and(e, xor(f, g))), 0xd807aa98)), mload(1280))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff)
                  h := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(a, b), and(c, or(a, b))))), 0xffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(f, and(d, xor(e, f))), 0x12835b01)), mload(1312))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff)
                  g := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(h, a), and(b, or(h, a))))), 0xffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(e, and(c, xor(d, e))), 0x243185be)), mload(1344))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff)
                  f := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(g, h), and(a, or(g, h))))), 0xffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(d, and(b, xor(c, d))), 0x550c7dc3)), mload(1376))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff)
                  e := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(f, g), and(h, or(f, g))))), 0xffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(c, and(a, xor(b, c))), 0x72be5d74)), mload(1408))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff)
                  d := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(e, f), and(g, or(e, f))))), 0xffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(b, and(h, xor(a, b))), 0x80deb1fe)), mload(1440))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff)
                  c := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(d, e), and(f, or(d, e))))), 0xffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(a, and(g, xor(h, a))), 0x9bdc06a7)), mload(1472))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff)
                  b := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(c, d), and(e, or(c, d))))), 0xffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(h, and(f, xor(g, h))), 0xc19bf174)), mload(1504))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff)
                  a := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(b, c), and(d, or(b, c))))), 0xffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(g, and(e, xor(f, g))), 0xe49b69c1)), mload(1536))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff)
                  h := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(a, b), and(c, or(a, b))))), 0xffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(f, and(d, xor(e, f))), 0xefbe4786)), mload(1568))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff)
                  g := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(h, a), and(b, or(h, a))))), 0xffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(e, and(c, xor(d, e))), 0xfc19dc6)), mload(1600))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff)
                  f := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(g, h), and(a, or(g, h))))), 0xffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(d, and(b, xor(c, d))), 0x240ca1cc)), mload(1632))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff)
                  e := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(f, g), and(h, or(f, g))))), 0xffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(c, and(a, xor(b, c))), 0x2de92c6f)), mload(1664))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff)
                  d := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(e, f), and(g, or(e, f))))), 0xffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(b, and(h, xor(a, b))), 0x4a7484aa)), mload(1696))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff)
                  c := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(d, e), and(f, or(d, e))))), 0xffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(a, and(g, xor(h, a))), 0x5cb0a9dc)), mload(1728))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff)
                  b := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(c, d), and(e, or(c, d))))), 0xffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(h, and(f, xor(g, h))), 0x76f988da)), mload(1760))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff)
                  a := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(b, c), and(d, or(b, c))))), 0xffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(g, and(e, xor(f, g))), 0x983e5152)), mload(1792))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff)
                  h := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(a, b), and(c, or(a, b))))), 0xffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(f, and(d, xor(e, f))), 0xa831c66d)), mload(1824))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff)
                  g := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(h, a), and(b, or(h, a))))), 0xffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(e, and(c, xor(d, e))), 0xb00327c8)), mload(1856))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff)
                  f := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(g, h), and(a, or(g, h))))), 0xffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(d, and(b, xor(c, d))), 0xbf597fc7)), mload(1888))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff)
                  e := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(f, g), and(h, or(f, g))))), 0xffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(c, and(a, xor(b, c))), 0xc6e00bf3)), mload(1920))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff)
                  d := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(e, f), and(g, or(e, f))))), 0xffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(b, and(h, xor(a, b))), 0xd5a79147)), mload(1952))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff)
                  c := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(d, e), and(f, or(d, e))))), 0xffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(a, and(g, xor(h, a))), 0x6ca6351)), mload(1984))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff)
                  b := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(c, d), and(e, or(c, d))))), 0xffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(h, and(f, xor(g, h))), 0x14292967)), mload(2016))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff)
                  a := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(b, c), and(d, or(b, c))))), 0xffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(g, and(e, xor(f, g))), 0x27b70a85)), mload(2048))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff)
                  h := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(a, b), and(c, or(a, b))))), 0xffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(f, and(d, xor(e, f))), 0x2e1b2138)), mload(2080))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff)
                  g := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(h, a), and(b, or(h, a))))), 0xffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(e, and(c, xor(d, e))), 0x4d2c6dfc)), mload(2112))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff)
                  f := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(g, h), and(a, or(g, h))))), 0xffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(d, and(b, xor(c, d))), 0x53380d13)), mload(2144))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff)
                  e := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(f, g), and(h, or(f, g))))), 0xffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(c, and(a, xor(b, c))), 0x650a7354)), mload(2176))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff)
                  d := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(e, f), and(g, or(e, f))))), 0xffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(b, and(h, xor(a, b))), 0x766a0abb)), mload(2208))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff)
                  c := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(d, e), and(f, or(d, e))))), 0xffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(a, and(g, xor(h, a))), 0x81c2c92e)), mload(2240))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff)
                  b := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(c, d), and(e, or(c, d))))), 0xffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(h, and(f, xor(g, h))), 0x92722c85)), mload(2272))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff)
                  a := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(b, c), and(d, or(b, c))))), 0xffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(g, and(e, xor(f, g))), 0xa2bfe8a1)), mload(2304))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff)
                  h := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(a, b), and(c, or(a, b))))), 0xffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(f, and(d, xor(e, f))), 0xa81a664b)), mload(2336))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff)
                  g := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(h, a), and(b, or(h, a))))), 0xffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(e, and(c, xor(d, e))), 0xc24b8b70)), mload(2368))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff)
                  f := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(g, h), and(a, or(g, h))))), 0xffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(d, and(b, xor(c, d))), 0xc76c51a3)), mload(2400))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff)
                  e := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(f, g), and(h, or(f, g))))), 0xffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(c, and(a, xor(b, c))), 0xd192e819)), mload(2432))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff)
                  d := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(e, f), and(g, or(e, f))))), 0xffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(b, and(h, xor(a, b))), 0xd6990624)), mload(2464))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff)
                  c := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(d, e), and(f, or(d, e))))), 0xffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(a, and(g, xor(h, a))), 0xf40e3585)), mload(2496))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff)
                  b := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(c, d), and(e, or(c, d))))), 0xffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(h, and(f, xor(g, h))), 0x106aa070)), mload(2528))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff)
                  a := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(b, c), and(d, or(b, c))))), 0xffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(g, and(e, xor(f, g))), 0x19a4c116)), mload(2560))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff)
                  h := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(a, b), and(c, or(a, b))))), 0xffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(f, and(d, xor(e, f))), 0x1e376c08)), mload(2592))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff)
                  g := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(h, a), and(b, or(h, a))))), 0xffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(e, and(c, xor(d, e))), 0x2748774c)), mload(2624))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff)
                  f := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(g, h), and(a, or(g, h))))), 0xffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(d, and(b, xor(c, d))), 0x34b0bcb5)), mload(2656))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff)
                  e := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(f, g), and(h, or(f, g))))), 0xffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(c, and(a, xor(b, c))), 0x391c0cb3)), mload(2688))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff)
                  d := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(e, f), and(g, or(e, f))))), 0xffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(b, and(h, xor(a, b))), 0x4ed8aa4a)), mload(2720))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff)
                  c := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(d, e), and(f, or(d, e))))), 0xffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(a, and(g, xor(h, a))), 0x5b9cca4f)), mload(2752))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff)
                  b := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(c, d), and(e, or(c, d))))), 0xffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(h, and(f, xor(g, h))), 0x682e6ff3)), mload(2784))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff)
                  a := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(b, c), and(d, or(b, c))))), 0xffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(g, and(e, xor(f, g))), 0x748f82ee)), mload(2816))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff)
                  h := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(a, b), and(c, or(a, b))))), 0xffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(f, and(d, xor(e, f))), 0x78a5636f)), mload(2848))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff)
                  g := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(h, a), and(b, or(h, a))))), 0xffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(e, and(c, xor(d, e))), 0x84c87814)), mload(2880))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff)
                  f := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(g, h), and(a, or(g, h))))), 0xffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(d, and(b, xor(c, d))), 0x8cc70208)), mload(2912))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff)
                  e := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(f, g), and(h, or(f, g))))), 0xffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(c, and(a, xor(b, c))), 0x90befffa)), mload(2944))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff)
                  d := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(e, f), and(g, or(e, f))))), 0xffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(b, and(h, xor(a, b))), 0xa4506ceb)), mload(2976))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff)
                  c := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(d, e), and(f, or(d, e))))), 0xffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(a, and(g, xor(h, a))), 0xbef9a3f7)), mload(3008))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff)
                  b := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(c, d), and(e, or(c, d))))), 0xffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, xor(xor(shr(6, de), shr(11, de)), shr(25, de))), add(xor(h, and(f, xor(g, h))), 0xc67178f2)), mload(3040))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff)
                  a := and(add(t1, add(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), or(and(b, c), and(d, or(b, c))))), 0xffffffff) }
                mstore(add(st, 0), and(add(mload(add(st, 0)), a), 0xffffffff))
                mstore(add(st, 32), and(add(mload(add(st, 32)), b), 0xffffffff))
                mstore(add(st, 64), and(add(mload(add(st, 64)), c), 0xffffffff))
                mstore(add(st, 96), and(add(mload(add(st, 96)), d), 0xffffffff))
                mstore(add(st, 128), and(add(mload(add(st, 128)), e), 0xffffffff))
                mstore(add(st, 160), and(add(mload(add(st, 160)), f), 0xffffffff))
                mstore(add(st, 192), and(add(mload(add(st, 192)), g), 0xffffffff))
                mstore(add(st, 224), and(add(mload(add(st, 224)), h), 0xffffffff))
      }
      function rounds4(st) {
                { let sx := mload(1056) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1472) sd := or(sx, shl(32, sx))
                  mstore(1536, and(add(add(s0, mload(1024)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1312))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1088) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1504) sd := or(sx, shl(32, sx))
                  mstore(1568, and(add(add(s0, mload(1056)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1344))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1120) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1536) sd := or(sx, shl(32, sx))
                  mstore(1600, and(add(add(s0, mload(1088)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1376))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1152) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1568) sd := or(sx, shl(32, sx))
                  mstore(1632, and(add(add(s0, mload(1120)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1408))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1184) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1600) sd := or(sx, shl(32, sx))
                  mstore(1664, and(add(add(s0, mload(1152)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1440))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1216) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1632) sd := or(sx, shl(32, sx))
                  mstore(1696, and(add(add(s0, mload(1184)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1472))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1248) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1664) sd := or(sx, shl(32, sx))
                  mstore(1728, and(add(add(s0, mload(1216)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1504))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1280) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1696) sd := or(sx, shl(32, sx))
                  mstore(1760, and(add(add(s0, mload(1248)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1536))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1312) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1728) sd := or(sx, shl(32, sx))
                  mstore(1792, and(add(add(s0, mload(1280)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1568))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1344) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1760) sd := or(sx, shl(32, sx))
                  mstore(1824, and(add(add(s0, mload(1312)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1600))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1376) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1792) sd := or(sx, shl(32, sx))
                  mstore(1856, and(add(add(s0, mload(1344)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1632))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1408) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1824) sd := or(sx, shl(32, sx))
                  mstore(1888, and(add(add(s0, mload(1376)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1664))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1440) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1856) sd := or(sx, shl(32, sx))
                  mstore(1920, and(add(add(s0, mload(1408)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1696))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1472) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1888) sd := or(sx, shl(32, sx))
                  mstore(1952, and(add(add(s0, mload(1440)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1728))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1504) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1920) sd := or(sx, shl(32, sx))
                  mstore(1984, and(add(add(s0, mload(1472)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1760))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1536) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1952) sd := or(sx, shl(32, sx))
                  mstore(2016, and(add(add(s0, mload(1504)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1792))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1568) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(1984) sd := or(sx, shl(32, sx))
                  mstore(2048, and(add(add(s0, mload(1536)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1824))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1600) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2016) sd := or(sx, shl(32, sx))
                  mstore(2080, and(add(add(s0, mload(1568)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1856))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1632) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2048) sd := or(sx, shl(32, sx))
                  mstore(2112, and(add(add(s0, mload(1600)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1888))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1664) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2080) sd := or(sx, shl(32, sx))
                  mstore(2144, and(add(add(s0, mload(1632)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1920))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1696) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2112) sd := or(sx, shl(32, sx))
                  mstore(2176, and(add(add(s0, mload(1664)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1952))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1728) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2144) sd := or(sx, shl(32, sx))
                  mstore(2208, and(add(add(s0, mload(1696)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(1984))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1760) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2176) sd := or(sx, shl(32, sx))
                  mstore(2240, and(add(add(s0, mload(1728)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2016))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1792) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2208) sd := or(sx, shl(32, sx))
                  mstore(2272, and(add(add(s0, mload(1760)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2048))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1824) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2240) sd := or(sx, shl(32, sx))
                  mstore(2304, and(add(add(s0, mload(1792)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2080))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1856) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2272) sd := or(sx, shl(32, sx))
                  mstore(2336, and(add(add(s0, mload(1824)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2112))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1888) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2304) sd := or(sx, shl(32, sx))
                  mstore(2368, and(add(add(s0, mload(1856)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2144))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1920) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2336) sd := or(sx, shl(32, sx))
                  mstore(2400, and(add(add(s0, mload(1888)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2176))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1952) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2368) sd := or(sx, shl(32, sx))
                  mstore(2432, and(add(add(s0, mload(1920)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2208))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(1984) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2400) sd := or(sx, shl(32, sx))
                  mstore(2464, and(add(add(s0, mload(1952)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2240))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2016) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2432) sd := or(sx, shl(32, sx))
                  mstore(2496, and(add(add(s0, mload(1984)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2272))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2048) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2464) sd := or(sx, shl(32, sx))
                  mstore(2528, and(add(add(s0, mload(2016)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2304))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2080) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2496) sd := or(sx, shl(32, sx))
                  mstore(2560, and(add(add(s0, mload(2048)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2336))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2112) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2528) sd := or(sx, shl(32, sx))
                  mstore(2592, and(add(add(s0, mload(2080)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2368))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2144) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2560) sd := or(sx, shl(32, sx))
                  mstore(2624, and(add(add(s0, mload(2112)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2400))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2176) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2592) sd := or(sx, shl(32, sx))
                  mstore(2656, and(add(add(s0, mload(2144)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2432))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2208) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2624) sd := or(sx, shl(32, sx))
                  mstore(2688, and(add(add(s0, mload(2176)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2464))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2240) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2656) sd := or(sx, shl(32, sx))
                  mstore(2720, and(add(add(s0, mload(2208)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2496))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2272) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2688) sd := or(sx, shl(32, sx))
                  mstore(2752, and(add(add(s0, mload(2240)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2528))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2304) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2720) sd := or(sx, shl(32, sx))
                  mstore(2784, and(add(add(s0, mload(2272)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2560))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2336) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2752) sd := or(sx, shl(32, sx))
                  mstore(2816, and(add(add(s0, mload(2304)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2592))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2368) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2784) sd := or(sx, shl(32, sx))
                  mstore(2848, and(add(add(s0, mload(2336)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2624))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2400) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2816) sd := or(sx, shl(32, sx))
                  mstore(2880, and(add(add(s0, mload(2368)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2656))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2432) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2848) sd := or(sx, shl(32, sx))
                  mstore(2912, and(add(add(s0, mload(2400)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2688))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2464) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2880) sd := or(sx, shl(32, sx))
                  mstore(2944, and(add(add(s0, mload(2432)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2720))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2496) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2912) sd := or(sx, shl(32, sx))
                  mstore(2976, and(add(add(s0, mload(2464)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2752))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2528) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2944) sd := or(sx, shl(32, sx))
                  mstore(3008, and(add(add(s0, mload(2496)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2784))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                { let sx := mload(2560) let sd := or(sx, shl(32, sx)) let s0 := and(xor(xor(shr(7, sd), shr(18, sd)), shr(3, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  sx := mload(2976) sd := or(sx, shl(32, sx))
                  mstore(3040, and(add(add(s0, mload(2528)), add(and(xor(xor(shr(17, sd), shr(19, sd)), shr(10, sx)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), mload(2816))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)) }
                let a := mload(st) let b := mload(add(st, 32)) let c := mload(add(st, 64)) let d := mload(add(st, 96))
                let e := mload(add(st, 128)) let f := mload(add(st, 160)) let g := mload(add(st, 192)) let h := mload(add(st, 224))
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(g, and(e, xor(f, g))), 0x428a2f9800000000428a2f9800000000428a2f9800000000428a2f98)), mload(1024))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  h := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(a, b), and(c, or(a, b))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(f, and(d, xor(e, f))), 0x71374491000000007137449100000000713744910000000071374491)), mload(1056))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  g := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(h, a), and(b, or(h, a))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(e, and(c, xor(d, e))), 0xb5c0fbcf00000000b5c0fbcf00000000b5c0fbcf00000000b5c0fbcf)), mload(1088))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  f := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(g, h), and(a, or(g, h))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(d, and(b, xor(c, d))), 0xe9b5dba500000000e9b5dba500000000e9b5dba500000000e9b5dba5)), mload(1120))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  e := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(f, g), and(h, or(f, g))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(c, and(a, xor(b, c))), 0x3956c25b000000003956c25b000000003956c25b000000003956c25b)), mload(1152))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  d := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(e, f), and(g, or(e, f))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(b, and(h, xor(a, b))), 0x59f111f10000000059f111f10000000059f111f10000000059f111f1)), mload(1184))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  c := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(d, e), and(f, or(d, e))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(a, and(g, xor(h, a))), 0x923f82a400000000923f82a400000000923f82a400000000923f82a4)), mload(1216))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  b := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(c, d), and(e, or(c, d))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(h, and(f, xor(g, h))), 0xab1c5ed500000000ab1c5ed500000000ab1c5ed500000000ab1c5ed5)), mload(1248))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  a := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(b, c), and(d, or(b, c))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(g, and(e, xor(f, g))), 0xd807aa9800000000d807aa9800000000d807aa9800000000d807aa98)), mload(1280))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  h := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(a, b), and(c, or(a, b))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(f, and(d, xor(e, f))), 0x12835b010000000012835b010000000012835b010000000012835b01)), mload(1312))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  g := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(h, a), and(b, or(h, a))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(e, and(c, xor(d, e))), 0x243185be00000000243185be00000000243185be00000000243185be)), mload(1344))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  f := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(g, h), and(a, or(g, h))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(d, and(b, xor(c, d))), 0x550c7dc300000000550c7dc300000000550c7dc300000000550c7dc3)), mload(1376))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  e := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(f, g), and(h, or(f, g))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(c, and(a, xor(b, c))), 0x72be5d740000000072be5d740000000072be5d740000000072be5d74)), mload(1408))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  d := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(e, f), and(g, or(e, f))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(b, and(h, xor(a, b))), 0x80deb1fe0000000080deb1fe0000000080deb1fe0000000080deb1fe)), mload(1440))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  c := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(d, e), and(f, or(d, e))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(a, and(g, xor(h, a))), 0x9bdc06a7000000009bdc06a7000000009bdc06a7000000009bdc06a7)), mload(1472))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  b := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(c, d), and(e, or(c, d))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(h, and(f, xor(g, h))), 0xc19bf17400000000c19bf17400000000c19bf17400000000c19bf174)), mload(1504))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  a := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(b, c), and(d, or(b, c))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(g, and(e, xor(f, g))), 0xe49b69c100000000e49b69c100000000e49b69c100000000e49b69c1)), mload(1536))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  h := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(a, b), and(c, or(a, b))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(f, and(d, xor(e, f))), 0xefbe478600000000efbe478600000000efbe478600000000efbe4786)), mload(1568))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  g := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(h, a), and(b, or(h, a))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(e, and(c, xor(d, e))), 0xfc19dc6000000000fc19dc6000000000fc19dc6000000000fc19dc6)), mload(1600))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  f := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(g, h), and(a, or(g, h))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(d, and(b, xor(c, d))), 0x240ca1cc00000000240ca1cc00000000240ca1cc00000000240ca1cc)), mload(1632))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  e := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(f, g), and(h, or(f, g))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(c, and(a, xor(b, c))), 0x2de92c6f000000002de92c6f000000002de92c6f000000002de92c6f)), mload(1664))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  d := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(e, f), and(g, or(e, f))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(b, and(h, xor(a, b))), 0x4a7484aa000000004a7484aa000000004a7484aa000000004a7484aa)), mload(1696))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  c := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(d, e), and(f, or(d, e))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(a, and(g, xor(h, a))), 0x5cb0a9dc000000005cb0a9dc000000005cb0a9dc000000005cb0a9dc)), mload(1728))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  b := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(c, d), and(e, or(c, d))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(h, and(f, xor(g, h))), 0x76f988da0000000076f988da0000000076f988da0000000076f988da)), mload(1760))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  a := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(b, c), and(d, or(b, c))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(g, and(e, xor(f, g))), 0x983e515200000000983e515200000000983e515200000000983e5152)), mload(1792))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  h := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(a, b), and(c, or(a, b))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(f, and(d, xor(e, f))), 0xa831c66d00000000a831c66d00000000a831c66d00000000a831c66d)), mload(1824))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  g := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(h, a), and(b, or(h, a))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(e, and(c, xor(d, e))), 0xb00327c800000000b00327c800000000b00327c800000000b00327c8)), mload(1856))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  f := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(g, h), and(a, or(g, h))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(d, and(b, xor(c, d))), 0xbf597fc700000000bf597fc700000000bf597fc700000000bf597fc7)), mload(1888))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  e := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(f, g), and(h, or(f, g))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(c, and(a, xor(b, c))), 0xc6e00bf300000000c6e00bf300000000c6e00bf300000000c6e00bf3)), mload(1920))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  d := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(e, f), and(g, or(e, f))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(b, and(h, xor(a, b))), 0xd5a7914700000000d5a7914700000000d5a7914700000000d5a79147)), mload(1952))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  c := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(d, e), and(f, or(d, e))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(a, and(g, xor(h, a))), 0x6ca63510000000006ca63510000000006ca63510000000006ca6351)), mload(1984))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  b := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(c, d), and(e, or(c, d))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(h, and(f, xor(g, h))), 0x14292967000000001429296700000000142929670000000014292967)), mload(2016))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  a := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(b, c), and(d, or(b, c))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(g, and(e, xor(f, g))), 0x27b70a850000000027b70a850000000027b70a850000000027b70a85)), mload(2048))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  h := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(a, b), and(c, or(a, b))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(f, and(d, xor(e, f))), 0x2e1b2138000000002e1b2138000000002e1b2138000000002e1b2138)), mload(2080))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  g := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(h, a), and(b, or(h, a))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(e, and(c, xor(d, e))), 0x4d2c6dfc000000004d2c6dfc000000004d2c6dfc000000004d2c6dfc)), mload(2112))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  f := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(g, h), and(a, or(g, h))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(d, and(b, xor(c, d))), 0x53380d130000000053380d130000000053380d130000000053380d13)), mload(2144))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  e := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(f, g), and(h, or(f, g))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(c, and(a, xor(b, c))), 0x650a735400000000650a735400000000650a735400000000650a7354)), mload(2176))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  d := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(e, f), and(g, or(e, f))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(b, and(h, xor(a, b))), 0x766a0abb00000000766a0abb00000000766a0abb00000000766a0abb)), mload(2208))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  c := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(d, e), and(f, or(d, e))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(a, and(g, xor(h, a))), 0x81c2c92e0000000081c2c92e0000000081c2c92e0000000081c2c92e)), mload(2240))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  b := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(c, d), and(e, or(c, d))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(h, and(f, xor(g, h))), 0x92722c850000000092722c850000000092722c850000000092722c85)), mload(2272))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  a := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(b, c), and(d, or(b, c))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(g, and(e, xor(f, g))), 0xa2bfe8a100000000a2bfe8a100000000a2bfe8a100000000a2bfe8a1)), mload(2304))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  h := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(a, b), and(c, or(a, b))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(f, and(d, xor(e, f))), 0xa81a664b00000000a81a664b00000000a81a664b00000000a81a664b)), mload(2336))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  g := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(h, a), and(b, or(h, a))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(e, and(c, xor(d, e))), 0xc24b8b7000000000c24b8b7000000000c24b8b7000000000c24b8b70)), mload(2368))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  f := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(g, h), and(a, or(g, h))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(d, and(b, xor(c, d))), 0xc76c51a300000000c76c51a300000000c76c51a300000000c76c51a3)), mload(2400))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  e := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(f, g), and(h, or(f, g))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(c, and(a, xor(b, c))), 0xd192e81900000000d192e81900000000d192e81900000000d192e819)), mload(2432))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  d := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(e, f), and(g, or(e, f))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(b, and(h, xor(a, b))), 0xd699062400000000d699062400000000d699062400000000d6990624)), mload(2464))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  c := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(d, e), and(f, or(d, e))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(a, and(g, xor(h, a))), 0xf40e358500000000f40e358500000000f40e358500000000f40e3585)), mload(2496))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  b := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(c, d), and(e, or(c, d))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(h, and(f, xor(g, h))), 0x106aa07000000000106aa07000000000106aa07000000000106aa070)), mload(2528))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  a := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(b, c), and(d, or(b, c))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(g, and(e, xor(f, g))), 0x19a4c1160000000019a4c1160000000019a4c1160000000019a4c116)), mload(2560))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  h := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(a, b), and(c, or(a, b))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(f, and(d, xor(e, f))), 0x1e376c08000000001e376c08000000001e376c08000000001e376c08)), mload(2592))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  g := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(h, a), and(b, or(h, a))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(e, and(c, xor(d, e))), 0x2748774c000000002748774c000000002748774c000000002748774c)), mload(2624))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  f := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(g, h), and(a, or(g, h))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(d, and(b, xor(c, d))), 0x34b0bcb50000000034b0bcb50000000034b0bcb50000000034b0bcb5)), mload(2656))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  e := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(f, g), and(h, or(f, g))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(c, and(a, xor(b, c))), 0x391c0cb300000000391c0cb300000000391c0cb300000000391c0cb3)), mload(2688))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  d := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(e, f), and(g, or(e, f))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(b, and(h, xor(a, b))), 0x4ed8aa4a000000004ed8aa4a000000004ed8aa4a000000004ed8aa4a)), mload(2720))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  c := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(d, e), and(f, or(d, e))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(a, and(g, xor(h, a))), 0x5b9cca4f000000005b9cca4f000000005b9cca4f000000005b9cca4f)), mload(2752))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  b := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(c, d), and(e, or(c, d))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(h, and(f, xor(g, h))), 0x682e6ff300000000682e6ff300000000682e6ff300000000682e6ff3)), mload(2784))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  a := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(b, c), and(d, or(b, c))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(e, shl(32, e))
                  let t1 := add(add(add(h, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(g, and(e, xor(f, g))), 0x748f82ee00000000748f82ee00000000748f82ee00000000748f82ee)), mload(2816))
                  let da := or(a, shl(32, a))
                  d := and(add(d, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  h := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(a, b), and(c, or(a, b))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(d, shl(32, d))
                  let t1 := add(add(add(g, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(f, and(d, xor(e, f))), 0x78a5636f0000000078a5636f0000000078a5636f0000000078a5636f)), mload(2848))
                  let da := or(h, shl(32, h))
                  c := and(add(c, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  g := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(h, a), and(b, or(h, a))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(c, shl(32, c))
                  let t1 := add(add(add(f, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(e, and(c, xor(d, e))), 0x84c878140000000084c878140000000084c878140000000084c87814)), mload(2880))
                  let da := or(g, shl(32, g))
                  b := and(add(b, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  f := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(g, h), and(a, or(g, h))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(b, shl(32, b))
                  let t1 := add(add(add(e, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(d, and(b, xor(c, d))), 0x8cc70208000000008cc70208000000008cc70208000000008cc70208)), mload(2912))
                  let da := or(f, shl(32, f))
                  a := and(add(a, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  e := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(f, g), and(h, or(f, g))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(a, shl(32, a))
                  let t1 := add(add(add(d, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(c, and(a, xor(b, c))), 0x90befffa0000000090befffa0000000090befffa0000000090befffa)), mload(2944))
                  let da := or(e, shl(32, e))
                  h := and(add(h, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  d := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(e, f), and(g, or(e, f))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(h, shl(32, h))
                  let t1 := add(add(add(c, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(b, and(h, xor(a, b))), 0xa4506ceb00000000a4506ceb00000000a4506ceb00000000a4506ceb)), mload(2976))
                  let da := or(d, shl(32, d))
                  g := and(add(g, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  c := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(d, e), and(f, or(d, e))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(g, shl(32, g))
                  let t1 := add(add(add(b, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(a, and(g, xor(h, a))), 0xbef9a3f700000000bef9a3f700000000bef9a3f700000000bef9a3f7)), mload(3008))
                  let da := or(c, shl(32, c))
                  f := and(add(f, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  b := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(c, d), and(e, or(c, d))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                { let de := or(f, shl(32, f))
                  let t1 := add(add(add(a, and(xor(xor(shr(6, de), shr(11, de)), shr(25, de)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)), add(xor(h, and(f, xor(g, h))), 0xc67178f200000000c67178f200000000c67178f200000000c67178f2)), mload(3040))
                  let da := or(b, shl(32, b))
                  e := and(add(e, t1), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff)
                  a := and(add(t1, add(and(xor(xor(shr(2, da), shr(13, da)), shr(22, da)), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff), or(and(b, c), and(d, or(b, c))))), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff) }
                mstore(add(st, 0), and(add(mload(add(st, 0)), a), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff))
                mstore(add(st, 32), and(add(mload(add(st, 32)), b), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff))
                mstore(add(st, 64), and(add(mload(add(st, 64)), c), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff))
                mstore(add(st, 96), and(add(mload(add(st, 96)), d), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff))
                mstore(add(st, 128), and(add(mload(add(st, 128)), e), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff))
                mstore(add(st, 160), and(add(mload(add(st, 160)), f), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff))
                mstore(add(st, 192), and(add(mload(add(st, 192)), g), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff))
                mstore(add(st, 224), and(add(mload(add(st, 224)), h), 0xffffffff00000000ffffffff00000000ffffffff00000000ffffffff))
      }
            function init1(st) {
                mstore(add(st, 0), 0x6a09e667)
                mstore(add(st, 32), 0xbb67ae85)
                mstore(add(st, 64), 0x3c6ef372)
                mstore(add(st, 96), 0xa54ff53a)
                mstore(add(st, 128), 0x510e527f)
                mstore(add(st, 160), 0x9b05688c)
                mstore(add(st, 192), 0x1f83d9ab)
                mstore(add(st, 224), 0x5be0cd19)
            }
            function init4(st) {
                mstore(add(st, 0), 0x6a09e667000000006a09e667000000006a09e667000000006a09e667)
                mstore(add(st, 32), 0xbb67ae8500000000bb67ae8500000000bb67ae8500000000bb67ae85)
                mstore(add(st, 64), 0x3c6ef372000000003c6ef372000000003c6ef372000000003c6ef372)
                mstore(add(st, 96), 0xa54ff53a00000000a54ff53a00000000a54ff53a00000000a54ff53a)
                mstore(add(st, 128), 0x510e527f00000000510e527f00000000510e527f00000000510e527f)
                mstore(add(st, 160), 0x9b05688c000000009b05688c000000009b05688c000000009b05688c)
                mstore(add(st, 192), 0x1f83d9ab000000001f83d9ab000000001f83d9ab000000001f83d9ab)
                mstore(add(st, 224), 0x5be0cd19000000005be0cd19000000005be0cd19000000005be0cd19)
            }
            function digest1(st) -> hh {
                for { let i := 0 } lt(i, 8) { i := add(i, 1) } { hh := or(hh, shl(sub(224, mul(32, i)), mload(add(st, mul(32, i))))) }
            }
            function digest4(st, lane) -> hh {
                let s := mul(64, lane)
                for { let i := 0 } lt(i, 8) { i := add(i, 1) } { hh := or(hh, shl(sub(224, mul(32, i)), and(shr(s, mload(add(st, mul(32, i)))), 0xffffffff))) }
            }
            // padded tail of MSG[a..b) at tp (128 bytes); returns tail block count
            function tail(a, b, tp) -> nt {
                let n := sub(b, a)
                let full := div(n, 64)
                let rem := mod(n, 64)
                nt := add(1, gt(add(rem, 9), 64))
                mstore(tp, 0) mstore(add(tp, 32), 0) mstore(add(tp, 64), 0) mstore(add(tp, 96), 0)
                mcopy(tp, add(4096, add(a, mul(full, 64))), rem)
                mstore8(add(tp, rem), 0x80)
                let end := add(tp, mul(nt, 64))
                mstore(sub(end, 32), or(and(mload(sub(end, 32)), not(0xffffffffffffffff)), mul(n, 8)))
            }
            function ptr(a, full, tp, k) -> p {
                p := add(tp, mul(sub(k, full), 64))
                if lt(k, full) { p := add(4096, add(a, mul(k, 64))) }
            }
            function sha1(a, b, st, tp) -> hh {
                init1(st)
                let full := div(sub(b, a), 64)
                let total := add(full, tail(a, b, tp))
                for { let k := 0 } lt(k, total) { k := add(k, 1) } { compress1(st, ptr(a, full, tp, k)) }
                hh := digest1(st)
            }
            function evp1(d2, t, k2, wsd) {
                let shared := div(d2, 64)
                init1(256)
                for { let k := 0 } lt(k, shared) { k := add(k, 1) } { compress1(256, add(4096, mul(k, 64))) }
                if wsd { mcopy(512, 256, 256) }
                let nt := tail(0, d2, 3072)
                for { let k := 0 } lt(k, nt) { k := add(k, 1) } { compress1(256, add(3072, mul(k, 64))) }
                mstore(0, digest1(256))
                mstore(64, 0)
                if wsd {
                    let fullC := div(add(t, 1), 64)
                    let totalC := add(fullC, tail(0, add(t, 1), 3328))
                    for { let k := shared } lt(k, totalC) { k := add(k, 1) } { compress1(512, ptr(0, fullC, 3328, k)) }
                    mstore(64, digest1(512))
                }
                mstore(32, sha1(add(t, 1), k2, 256, 3200))
            }
            function evp4(d2, t, k2, wsd) {
                mstore(3584, 0) mstore(add(3584, 32), 0)
                let fullA := div(d2, 64)
                let nA := add(fullA, tail(0, d2, 3072))
                let aB := add(t, 1)
                let fullB := div(sub(k2, aB), 64)
                let nB := add(fullB, tail(aB, k2, 3200))
                let fullC := div(add(t, 1), 64)
                let nC := 0
                if wsd { nC := add(fullC, tail(0, add(t, 1), 3328)) }
                let steps := nA
                if gt(nB, steps) { steps := nB }
                if gt(nC, steps) { steps := nC }
                init4(256)
                mstore(64, 0)
                for { let s := 0 } lt(s, steps) { s := add(s, 1) } {
                    if and(wsd, eq(s, fullA)) {
                        for { let i := 0 } lt(i, 8) { i := add(i, 1) } {
                            let p := add(256, mul(32, i))
                            let w := mload(p)
                            mstore(p, or(and(w, not(shl(128, 0xffffffff))), shl(128, and(w, 0xffffffff))))
                        }
                    }
                    let p0 := 3584 if lt(s, nA) { p0 := ptr(0, fullA, 3072, s) }
                    let p1 := 3584 if lt(s, nB) { p1 := ptr(aB, fullB, 3200, s) }
                    let p2 := 3584 if and(iszero(lt(s, fullA)), lt(s, nC)) { p2 := ptr(0, fullC, 3328, s) }
                    compress4(256, p0, p1, p2, 3584)
                    if eq(add(s, 1), nA) { mstore(0, digest4(256, 0)) }
                    if eq(add(s, 1), nB) { mstore(32, digest4(256, 1)) }
                    if and(wsd, eq(add(s, 1), nC)) { mstore(64, digest4(256, 2)) }
                }
            }
    }
  }
}
