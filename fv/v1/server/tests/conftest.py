"""Options and the coverage print for test_walk.py. No code from the server is changed here.

A pytest option has to live in a conftest, not in the test file. That is the only reason this file exists.
"""
import os
import sys


def pytest_addoption(parser):
    g = parser.getgroup("walk")
    g.addoption("--trace-out", default=None, help="write one JSON line per walk step to this file (format: test_walk.py header)")
    g.addoption("--directed-trace-out", default=None, help="write the steps of test_directed_cases to this file, same format")
    g.addoption("--walk-sessions", type=int, default=int(os.environ.get("WALK_SESSIONS", "2000")), help="sessions in the main walk")
    g.addoption("--walk-seed", type=int, default=int(os.environ.get("WALK_SEED", "20261106")), help="seed of the main walk")


def pytest_terminal_summary(terminalreporter):
    mod = sys.modules.get("test_walk")
    if mod is None:
        return
    for line in mod.summary_lines():
        terminalreporter.write_line(line)
