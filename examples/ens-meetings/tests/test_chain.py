"""The real Chain against a recording subprocess: what the fake chain can't show. No process is started."""
import json
import subprocess
from types import SimpleNamespace

from backend.chain import NAME_TTL, Chain

RESOLVER, REGISTRY = "0x" + "11" * 20, "0x" + "22" * 20
PK = "0x" + "ab" * 32
SELECTORS = {"DuplicateMeeting(bytes32)": "0xdeadbeef"}


def fake_run(calls):
    def run(argv, **_kw):
        calls.append(argv)
        out = ""
        if argv[0] == "cast":
            out = {"wallet": "0x" + "33" * 20, "client": "anvil", "block": "1000", "nonce": "7",
                   "keccak": "0x" + "44" * 32, "call": "true\n1\n2\n3",
                   "send": json.dumps({"status": "0x1", "transactionHash": "0xfeed"}),
                   "sig": SELECTORS.get(argv[2] if len(argv) > 2 else "", "0x00000000")}[argv[1]]
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


def sends(calls):
    return [c[c.index("--nonce") + 2:] for c in calls if c[:2] == ["cast", "send"]]


def test_meeting_txs_match_the_old_bridge(tmp_path, monkeypatch):
    ch, calls = make(tmp_path, monkeypatch)
    mid, a, b, ev = "0x" + "01" * 32, "0x" + "02" * 32, "0x" + "03" * 32, "0x" + "04" * 32
    assert ch.record(mid, a, b, 497222, ev)["transactionHash"] == "0xfeed"
    ch.mark_zk(mid)
    ch.verify_send("0xverifier", "0xlog", "0xproof", "[0x01]")
    ch.verify_send("0xverifier", None, "0xproof", "[0x01]")
    assert sends(calls) == [[RESOLVER, "record(bytes32,bytes32,bytes32,uint32,bytes32)", mid, a, b, "497222", ev],
                            [RESOLVER, "markZkVerified(bytes32)", mid],
                            ["0xlog", "verifyAndLog(address,bytes,bytes32[])", "0xverifier", "0xproof", "[0x01]"],
                            ["0xverifier", "verify(bytes,bytes32[])", "0xproof", "[0x01]"]]


def test_record_preflight_is_a_call_from_the_attester(tmp_path, monkeypatch):
    ch, calls = make(tmp_path, monkeypatch)
    ch.record_would("m", "a", "b", 7, "e")
    call = [c for c in calls if c[:2] == ["cast", "call"]][0]
    assert call[call.index("--from") + 1] == ch.me and call[-6:] == [
        "record(bytes32,bytes32,bytes32,uint32,bytes32)(bool)", "m", "a", "b", "7", "e"]


def test_label_hash_never_hands_cast_the_raw_text(tmp_path, monkeypatch):
    """cast decodes 0xab as hex and takes --foo for a flag. The contract hashes the label's bytes."""
    ch, calls = make(tmp_path, monkeypatch)
    for label in ("0xab", "--foo"):
        ch.keccak_str(label)
        assert calls[-1] == ["cast", "keccak", "0x" + label.encode().hex()]


def test_revert_name(tmp_path, monkeypatch):
    ch, _ = make(tmp_path, monkeypatch)
    assert ch.revert_name("execution reverted, data: 0xdeadbeef") == "DuplicateMeeting"
    assert ch.revert_name("rpc down") == "rpc down"
