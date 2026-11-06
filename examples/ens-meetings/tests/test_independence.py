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


def test_nothing_reads_core_data():
    """No path or setting of the old bridge that reached into the core's files. import_names is the one exception:
    an old database, given by hand, is its whole job."""
    gone = re.compile(r"pop\.sqlite|sessions/|POP_DATA_DIR|POP_DB|dataDir|popDb|find_proof|sessions_dir")
    hits = [str(p.relative_to(ROOT)) for p in python_files()
            if p.name != "import_names.py" and p.parent.name != "tests" and gone.search(p.read_text())]
    assert not hits, hits


def test_env_example_has_no_keys():
    env = dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text().splitlines()
               if line and not line.startswith("#"))
    assert env["ENS_CORE_PRESENCE_PUBKEY"] == ""
    assert env["ENS_KEY_FILE"].startswith("~/")     # a path outside this folder, never the key
    assert not any(re.search(r"(0x)?[0-9a-fA-F]{40,}", v) for v in env.values())
