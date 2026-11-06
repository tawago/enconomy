"""An example uses only the core's public HTTP routes and the presence record."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = [re.compile(r"^\s*(from|import)\s+pop\b", re.M), re.compile(r"\bserver/"), re.compile(r"\.\./\.\./"),
             re.compile(r"examples/")]


def test_no_core_or_other_example_paths():
    files = [p for d in ("backend", "tests") for p in (ROOT / d).rglob("*.py") if p != Path(__file__).resolve()]
    assert any(p.name == "main.py" for p in files)
    hits = [f"{p.relative_to(ROOT)}: {rx.pattern}" for p in files for rx in FORBIDDEN if rx.search(p.read_text())]
    assert not hits, hits
