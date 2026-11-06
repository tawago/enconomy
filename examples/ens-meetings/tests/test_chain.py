"""The real Chain against a recording subprocess: what the fake chain can't show. No process is started."""
import json
import subprocess
from types import SimpleNamespace

from backend.chain import NAME_TTL, Chain

RESOLVER, REGISTRY = "0x" + "11" * 20, "0x" + "22" * 20
PK = "0x" + "ab" * 32


def fake_run(calls):
    def run(argv, **_kw):
        calls.append(argv)
        out = ""
        if argv[0] == "cast":
            out = {"wallet": "0x" + "33" * 20, "client": "anvil", "block": "1000", "nonce": "7",
                   "keccak": "0x" + "44" * 32, "call": "true\n1\n2\n3",
                   "send": json.dumps({"status": "0x1", "transactionHash": "0xfeed"})}[argv[1]]
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    return run


def make(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", fake_run(calls))
    key = tmp_path / "k.key"
    key.write_text(PK + "\n")
    return Chain("http://rpc", key, RESOLVER, REGISTRY), calls


def test_register_then_touch_match_ens_sh(tmp_path, monkeypatch):
    ch, calls = make(tmp_path, monkeypatch)
    assert ch.register("carol") == "0xfeed"
    ch.touch("carol")
    reg, touch = [c for c in calls if c[:2] == ["cast", "send"]]
    assert reg[reg.index(REGISTRY) + 1:] == ["register(string,address,address,address,uint256,uint64)", "carol", ch.me,
                                             "0x" + "0" * 40, RESOLVER, "0", str(1000 + NAME_TTL)]
    assert touch[touch.index(RESOLVER) + 1:] == ["touch(string)", "carol"]


def test_counts(tmp_path, monkeypatch):
    ch, _ = make(tmp_path, monkeypatch)
    assert ch.counts("carol") == (True, 1, 2, 3)


def test_unreadable_key_is_an_error_the_worker_can_catch(tmp_path, monkeypatch):
    ch, _ = make(tmp_path, monkeypatch)
    ch.key_file = tmp_path / "missing.key"
    try:
        ch.register("carol")
    except RuntimeError as e:
        assert "not readable" in str(e) and PK not in str(e)
    else:
        raise AssertionError("no error")
