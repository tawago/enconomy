"""An example uses only the core's public HTTP routes and the presence record."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".venv", "lib", "out", "cache"}
FORBIDDEN = [re.compile(r"^\s*(from|import)\s+pop\b", re.M), re.compile(r"\bserver/"), re.compile(r"\.\./\.\./"),
             re.compile(r"examples/")]


def python_files():
    for p in ROOT.rglob("*.py"):
        if SKIP.isdisjoint(p.relative_to(ROOT).parts) and p != Path(__file__).resolve():
            yield p


def test_no_core_or_other_example_paths():
    files = list(python_files())
    assert any(p.name == "main.py" for p in files)
    hits = [f"{p.relative_to(ROOT)}: {rx.pattern}" for p in files for rx in FORBIDDEN if rx.search(p.read_text())]
    assert not hits, hits


def test_scan_would_catch_it():
    assert FORBIDDEN[0].search("x = 1\nfrom pop.crypto import verify_raw\n")
    assert FORBIDDEN[0].search("import pop\n")
    assert FORBIDDEN[1].search('Path("../../server/data")')
    assert not FORBIDDEN[0].search("from popper import x\n")
