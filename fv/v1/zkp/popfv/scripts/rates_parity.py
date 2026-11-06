#!/usr/bin/env python3
"""App invariant row 5: the rate constants are the same in the circuit, the app and the server.

Reads three source files as text and compares them. Nothing is imported or run from them.

  circuit  research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr   L, DELTA, WPRE, WPOST, BAR, NZT, NZH
  app      app/composeApp/.../dsp/Popt2Rule.kt                           Popt2Rates.builtIn
  server   server/pop/popt2.py                                           RATES

48 kHz is compared across all three. 44.1 kHz is app against server only, since no circuit carries it.
Evidence level: script. It reads text, so it shows the numbers match, not that any code uses them correctly.

  python3 scripts/rates_parity.py             exit 0 on full match, 1 on any difference
  python3 scripts/rates_parity.py --selftest  also breaks each value in memory and checks that it gets caught
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
LIB = ROOT / "research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr"
KT = ROOT / "app/composeApp/src/commonMain/kotlin/com/enconomy/pop/dsp/Popt2Rule.kt"
PY = ROOT / "server/pop/popt2.py"

TAPS = 63
SUM_ABS_H = 415  # row 5 of fv/v1/docs/06-app-invariants.md
FIELDS = ("L", "B", "delta", "wpre", "wpost")


class ParseError(Exception):
    pass


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def parse_lib(text):
    def scalar(name):
        m = re.search(rf"pub global {name}: (?:u32|Field) = (-?\d+);", text)
        if not m:
            raise ParseError(f"lib.nr: no scalar {name}")
        return int(m.group(1)), line_of(text, m.start())

    def array(name):
        m = re.search(rf"pub global {name}: \[(?:u32|Field); \d+\] =\s*\[([^\]]*)\];", text)
        if not m:
            raise ParseError(f"lib.nr: no array {name}")
        return [int(v) for v in m.group(1).replace("\n", " ").split(",") if v.strip()], line_of(text, m.start())

    out = {k: scalar(k) for k in ("SR", "L", "K", "DELTA", "HM", "NS", "NP", "NL", "NT", "WPRE", "WPOST", "BAR", "NZ")}
    out["NZT"], out["NZH"] = array("NZT"), array("NZH")
    return out


def parse_kt(text):
    rates = {}
    for m in re.finditer(
        r"(\d+) to Popt2Rate\((\d+), (\d+), (\d+), (\d+), (\d+), (\d+), intArrayOf\(([^)]*)\)\)", text
    ):
        key, sr, l_, b, d, pre, post, h = m.groups()
        if key != sr:
            raise ParseError(f"Popt2Rule.kt: map key {key} != sr {sr}")
        rates[int(key)] = {
            "L": int(l_), "B": int(b), "delta": int(d), "wpre": int(pre), "wpost": int(post),
            "h": [int(v) for v in h.split(",") if v.strip()], "_line": line_of(text, m.start()),
        }
    if not rates:
        raise ParseError("Popt2Rule.kt: no Popt2Rate entries")
    m = re.search(r"const val HM\s*=\s*(\d+)", text)
    t = re.search(r"const val TAPS\s*=\s*(\d+)", text)
    if not m or not t:
        raise ParseError("Popt2Rule.kt: no HM or TAPS")
    return rates, int(m.group(1)), int(t.group(1))


def parse_py(text):
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "RATES" for t in node.targets):
            rates = ast.literal_eval(node.value)
            return {sr: dict(v, _line=node.lineno) for sr, v in rates.items()}
    raise ParseError("popt2.py: no RATES")


def expand(nzt, nzh, n=TAPS):
    h = [0] * n
    for t, v in zip(nzt, nzh):
        h[t] = v
    return h


def check(lib_text, kt_text, py_text):
    """Returns (differences, number of comparisons). Raises ParseError if a value can't be found."""
    lib = parse_lib(lib_text)
    kt, kt_hm, kt_taps = parse_kt(kt_text)
    py = parse_py(py_text)
    bad, n = [], [0]

    def eq(what, a, b):
        n[0] += 1
        if a != b:
            bad.append(f"{what}: {a} != {b}")

    v = {k: lib[k][0] for k in lib}
    # the circuit's own numbers agree with each other
    eq("lib K vs 2 DELTA + 1", v["K"], 2 * v["DELTA"] + 1)
    eq("lib NS vs K + L - 1 + 2 HM", v["NS"], v["K"] + v["L"] - 1 + 2 * v["HM"])
    eq("lib NP vs L + 2 HM", v["NP"], v["L"] + 2 * v["HM"])
    eq("lib NT vs NL * 1024", v["NT"], v["NL"] * 1024)
    eq("lib len NZT vs NZ", len(v["NZT"]), v["NZ"])
    eq("lib len NZH vs NZ", len(v["NZH"]), v["NZ"])
    eq("lib NZT strictly rising", v["NZT"], sorted(set(v["NZT"])))
    eq("lib NZT inside 63 taps", all(0 <= t < TAPS for t in v["NZT"]), True)
    eq("lib NZH has no zero", all(x != 0 for x in v["NZH"]), True)
    eq("lib SR vs 48000", v["SR"], 48000)

    # same rates in the app and the server
    eq("rates app vs server", sorted(kt), sorted(py))
    for sr in sorted(set(kt) & set(py)):
        for f in FIELDS:
            eq(f"{sr} {f} app vs server", kt[sr][f], py[sr][f])
        eq(f"{sr} h app vs server", kt[sr]["h"], py[sr]["h"])
        eq(f"{sr} h length app", len(kt[sr]["h"]), TAPS)
        eq(f"{sr} h length server", len(py[sr]["h"]), TAPS)

    # 48 kHz: circuit against both
    h_lib = expand(v["NZT"], v["NZH"]) if all(0 <= t < TAPS for t in v["NZT"]) else []
    for name, r in (("app", kt.get(48000)), ("server", py.get(48000))):
        if r is None:
            bad.append(f"no 48000 in {name}")
            continue
        eq(f"48000 L lib vs {name}", v["L"], r["L"])
        eq(f"48000 BAR lib vs {name}", v["BAR"], r["B"])
        eq(f"48000 DELTA lib vs {name}", v["DELTA"], r["delta"])
        eq(f"48000 WPRE lib vs {name}", v["WPRE"], r["wpre"])
        eq(f"48000 WPOST lib vs {name}", v["WPOST"], r["wpost"])
        eq(f"48000 taps lib vs {name}", h_lib, r["h"])
    eq("sum |h| lib vs 415", sum(abs(x) for x in v["NZH"]), SUM_ABS_H)
    eq("HM lib vs app", v["HM"], kt_hm)
    eq("TAPS 2 HM + 1 vs app", 2 * v["HM"] + 1, kt_taps)
    return bad, n[0]


def selftest(lib_text, kt_text, py_text):
    """Change one number at a time in each source. Each change must be reported or refuse to parse."""
    cases, missed = 0, []

    def changed(text, start, end):
        return text[:start] + str(int(text[start:end]) + 1) + text[end:]

    def run(which, text):
        nonlocal cases
        cases += 1
        args = {"lib": lib_text, "kt": kt_text, "py": py_text}
        args[which] = text
        try:
            bad, _ = check(args["lib"], args["kt"], args["py"])
        except (ParseError, ValueError, SyntaxError):
            return True
        return bool(bad)

    def block(text, pat):
        m = re.search(pat, text, re.S)
        if not m:
            raise ParseError(f"selftest: no block {pat}")
        return m.start(), m.end()

    targets = {
        "lib": (lib_text, r"pub global L: u32.*?pub global NZH: \[Field; 31\] = \[.*?\];"),
        "kt": (kt_text, r"48000 to Popt2Rate\(.*?\)\),\s*44100 to Popt2Rate\(.*?\)\),"),
        "py": (py_text, r"RATES = \{.*?\n\}"),
    }
    for which, (text, pat) in targets.items():
        s, e = block(text, pat)
        for m in re.finditer(r"(?<![\w.])\d+(?![\w.])", text[s:e]):
            lit = text[s:e][max(0, m.start() - 16):m.start()]
            line_so_far = text[s:e][text[s:e].rfind("\n", 0, m.start()) + 1:m.start()]
            # comments aren't values; array lengths and type widths in the declarations aren't either
            if "//" in line_so_far or re.search(r"; $", lit) or lit.endswith("u"):
                continue
            mut = changed(text, s + m.start(), s + m.end())
            if not run(which, mut):
                missed.append(f"{which} line {line_of(text, s + m.start())}: {m.group(0)}")
    return cases, missed


def main():
    lib_text, kt_text, py_text = LIB.read_text(), KT.read_text(), PY.read_text()
    bad, n = check(lib_text, kt_text, py_text)
    lib = parse_lib(lib_text)
    kt, _, _ = parse_kt(kt_text)
    py = parse_py(py_text)
    print(f"lib.nr       L:{lib['L'][1]} DELTA:{lib['DELTA'][1]} WPRE:{lib['WPRE'][1]} WPOST:{lib['WPOST'][1]} "
          f"BAR:{lib['BAR'][1]} NZT:{lib['NZT'][1]} NZH:{lib['NZH'][1]}")
    print(f"Popt2Rule.kt 48000:{kt[48000]['_line']} 44100:{kt[44100]['_line']}")
    print(f"popt2.py     RATES:{py[48000]['_line']}")
    r = py[48000]
    print(f"48000: L={r['L']} B={r['B']} delta={r['delta']} wpre={r['wpre']} wpost={r['wpost']} "
          f"nonzero taps={sum(1 for x in r['h'] if x)} sum|h|={sum(abs(x) for x in r['h'])}")
    r = py[44100]
    print(f"44100: L={r['L']} B={r['B']} delta={r['delta']} wpre={r['wpre']} wpost={r['wpost']} "
          f"(app vs server only, no circuit)")
    print(f"{n} comparisons, {len(bad)} differences")
    for b in bad:
        print("  DIFF", b)

    failed = bool(bad)
    if "--selftest" in sys.argv:
        cases, missed = selftest(lib_text, kt_text, py_text)
        print(f"selftest: {cases} one-number changes, {cases - len(missed)} caught, {len(missed)} missed")
        for m in missed:
            print("  MISSED", m)
        failed = failed or bool(missed)
    print("FAIL" if failed else "ALL OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
