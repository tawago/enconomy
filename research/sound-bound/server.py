"""sound-bound — two-phone acoustic proximity prototype (server).

One pair at a time. The first joiner is A, the second is B. The server issues a
seed, each role's own probe waveform, and a shared start time; both phones play
their own probe on that schedule while recording everything. Both uploads land in
data/sessions/<id>/, analysis runs, and the result is broadcast to both pages.

Signal code (probes.py, analysis.py) is owned by the other half of this project and
is imported lazily so the server still boots and serves pages without it.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from flask_socketio import SocketIO, emit

BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "data" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
SSL_CERT_PATH = BASE_DIR.parent / "fuzzy-commitment" / "cert.pem"
SSL_KEY_PATH = BASE_DIR.parent / "fuzzy-commitment" / "key.pem"

PORT = 5003
HOST = "0.0.0.0"

# Schedule defaults; these are copied verbatim into session.json.
SCHEDULE = {
    "period_s": 1.0,
    "b_offset_s": 0.5,
    "rounds": 4,
    "record_lead_s": 0.5,
    "record_total_s": 5.5,
}
START_DELAY_MS = 2000.0
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                    max_http_buffer_size=MAX_UPLOAD_BYTES)


def log(*parts) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='milliseconds')}]", *parts,
          flush=True)


def now_ms() -> float:
    return time.time() * 1000.0


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json_atomic(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    tmp.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
    os.replace(tmp, path)


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return None


class MissingSignalCode(RuntimeError):
    """probes.py / analysis.py are not in place yet."""


def probe_base64(seed_hex: str, role: str, sample_rate: int) -> str:
    """Render one role's probe as base64 float32 little-endian."""
    try:
        import numpy as np

        import probes
    except ImportError as exc:  # signal half not written yet
        raise MissingSignalCode(f"probes.py unavailable: {exc}") from exc
    wave = np.asarray(probes.generate(seed_hex, role, int(sample_rate)), dtype="<f4")
    return base64.b64encode(wave.tobytes()).decode("ascii")


def run_analysis(session_dir: Path) -> dict:
    try:
        import analysis
    except ImportError as exc:
        raise MissingSignalCode(f"analysis.py unavailable: {exc}") from exc
    return analysis.analyze_session(session_dir)


# ---------------------------------------------------------------- pending pair

class Pair:
    """The single session being assembled right now. One pair at a time."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        self.session_id: str | None = None
        self.seed_hex: str | None = None
        self.members: dict[str, dict] = {}   # role -> {sid, sample_rate, user_agent, client_id}
        self.armed: set[str] = set()
        self.started = False
        self.label_cm = None
        self.note = ""

    def free_role(self) -> str | None:
        for role in ("A", "B"):
            if role not in self.members:
                return role
        return None


PAIR = Pair()


def session_dir_for(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
    return SESSIONS_DIR / safe


def session_json_path(session_id: str) -> Path:
    return session_dir_for(session_id) / "session.json"


def build_session_json() -> dict:
    return {
        "session_id": PAIR.session_id,
        "created_at": iso_now(),
        "seed_hex": PAIR.seed_hex,
        "label_cm": PAIR.label_cm,
        "note": PAIR.note,
        "schedule": {"start_server_ms": None, **SCHEDULE},
        "roles": {
            role: {
                "client_id": info["client_id"],
                "sample_rate": info["sample_rate"],
                "user_agent": info["user_agent"],
            }
            for role, info in PAIR.members.items()
        },
    }


# ---------------------------------------------------------------- HTTP routes

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/time")
def api_time():
    return jsonify({"server_ms": now_ms()})


@app.route("/api/result/<session_id>")
def api_result(session_id: str):
    result = read_json(session_dir_for(session_id) / "result.json")
    if result is None:
        return jsonify({"error": "no result yet"}), 404
    return jsonify(result)


def _fmt(value, digits=1):
    if value is None:
        return "&mdash;"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


@app.route("/sessions")
def sessions_page():
    rows = []
    for directory in sorted(SESSIONS_DIR.glob("*"), reverse=True):
        if not directory.is_dir():
            continue
        session = read_json(directory / "session.json") or {}
        result = read_json(directory / "result.json") or {}
        summary = result.get("summary") or {}
        decision = result.get("decision") or {}
        rows.append({
            "id": session.get("session_id", directory.name),
            "created": session.get("created_at", ""),
            "label_cm": session.get("label_cm"),
            "note": session.get("note", ""),
            "usable": summary.get("usable_rounds"),
            "flight": summary.get("flight_cm_median"),
            "drr": summary.get("drr_db_median"),
            "cross": summary.get("crossfire_db_min"),
            "decision": decision.get("label", result.get("status", "")),
        })
    body = "\n".join(
        "<tr>"
        f"<td class=mono>{r['id'][:8]}</td>"
        f"<td>{r['created'][:19]}</td>"
        f"<td>{_fmt(r['label_cm'], 0)}</td>"
        f"<td>{_fmt(r['usable'], 0)}</td>"
        f"<td>{_fmt(r['flight'])}</td>"
        f"<td>{_fmt(r['drr'])}</td>"
        f"<td>{_fmt(r['cross'])}</td>"
        f"<td>{r['decision']}</td>"
        f"<td>{r['note'][:40]}</td>"
        "</tr>"
        for r in rows
    )
    html = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>sound-bound sessions</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;margin:16px;background:#0f1115;color:#e8e8ea}}
table{{border-collapse:collapse;width:100%}}
th,td{{border-bottom:1px solid #2a2e37;padding:6px 8px;text-align:right;white-space:nowrap}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),td:last-child{{text-align:left}}
.mono{{font-family:ui-monospace,monospace}}
a{{color:#7ab7ff}}
</style></head><body>
<h1>sessions ({len(rows)})</h1><p><a href="/">&larr; back</a> &mdash; all decisions are PROVISIONAL.</p>
<table><thead><tr>
<th>id</th><th>created (UTC)</th><th>label cm</th><th>usable</th>
<th>flight cm</th><th>DRR dB</th><th>crossfire dB</th><th>decision</th><th>note</th>
</tr></thead><tbody>{body}</tbody></table></body></html>"""
    return Response(html, mimetype="text/html")


@app.route("/api/upload/<session_id>/<role>", methods=["POST"])
def api_upload(session_id: str, role: str):
    if role not in ("A", "B"):
        return jsonify({"error": "bad role"}), 400
    directory = session_dir_for(session_id)
    if not (directory / "session.json").exists():
        return jsonify({"error": "unknown session"}), 404

    upload = request.files.get("wav")
    meta_raw = request.form.get("meta")
    if upload is None or meta_raw is None:
        return jsonify({"error": "need multipart fields 'wav' and 'meta'"}), 400
    try:
        meta = json.loads(meta_raw)
    except Exception:
        return jsonify({"error": "meta is not valid JSON"}), 400

    payload = upload.read()
    write_bytes_atomic(directory / f"recording_{role}.wav", payload)
    write_json_atomic(directory / f"meta_{role}.json", meta)
    log(f"upload session={session_id} role={role} bytes={len(payload)}")

    both = all((directory / f"recording_{r}.wav").exists() and
               (directory / f"meta_{r}.json").exists() for r in ("A", "B"))
    if both:
        socketio.start_background_task(analyze_and_broadcast, session_id)
    return jsonify({"ok": True, "both_uploaded": both})


def analyze_and_broadcast(session_id: str) -> None:
    directory = session_dir_for(session_id)
    log(f"analysis start session={session_id}")
    try:
        result = run_analysis(directory)
    except MissingSignalCode as exc:
        result = {"status": "failed", "reasons": [f"server_missing_signal_code: {exc}"],
                  "version": "sound-bound-v1"}
        write_json_atomic(directory / "result.json", result)
    except Exception as exc:  # analysis promises not to raise, but never trust that
        result = {"status": "failed", "reasons": [f"analysis_crashed: {exc!r}"],
                  "version": "sound-bound-v1"}
        write_json_atomic(directory / "result.json", result)
    log(f"analysis done session={session_id} status={result.get('status')}")
    socketio.emit("result", {"session_id": session_id, "result": result})
    with PAIR.lock:
        if PAIR.session_id == session_id:
            PAIR.reset()
            log("pair reset, ready for the next session")


# ---------------------------------------------------------------- socket events

@socketio.on("connect")
def on_connect(auth=None):
    log(f"connect sid={request.sid}")
    emit("hello", {"server_ms": now_ms()})


@socketio.on("ping")
def on_ping(data=None):
    client_ms = (data or {}).get("client_ms")
    emit("pong", {"server_ms": now_ms(), "client_ms": client_ms})


@socketio.on("disconnect")
def on_disconnect(reason=None):
    with PAIR.lock:
        for role, info in list(PAIR.members.items()):
            if info["sid"] == request.sid and not PAIR.started:
                log(f"role {role} left before start; dropping pending pair")
                PAIR.reset()
                socketio.emit("pair_reset", {"why": "a device disconnected"})
                break


@socketio.on("join")
def on_join(data=None):
    data = data or {}
    with PAIR.lock:
        if PAIR.started:
            emit("error_msg", {"message": "a session is already running; wait for it"})
            return
        role = PAIR.free_role()
        if role is None:
            emit("error_msg", {"message": "both roles taken"})
            return
        if not PAIR.members:
            PAIR.session_id = uuid.uuid4().hex
            PAIR.seed_hex = secrets.token_bytes(32).hex()
            PAIR.label_cm = _number(data.get("label_cm"))
            PAIR.note = str(data.get("note") or "")[:200]
        sample_rate = _sample_rate(data.get("sample_rate"))
        PAIR.members[role] = {
            "sid": request.sid,
            "client_id": uuid.uuid4().hex[:12],
            "sample_rate": sample_rate,
            "user_agent": str(data.get("user_agent") or request.headers.get("User-Agent", ""))[:300],
        }
        log(f"join role={role} session={PAIR.session_id} sr={sample_rate}")

        session_id, seed_hex = PAIR.session_id, PAIR.seed_hex
        schedule = {"start_server_ms": None, **SCHEDULE}
        both = len(PAIR.members) == 2
        members = dict(PAIR.members)
        if both:
            directory = session_dir_for(session_id)
            directory.mkdir(parents=True, exist_ok=True)
            write_json_atomic(directory / "session.json", build_session_json())
            log(f"session dir ready {directory}")

    for member_role, info in members.items():
        if not both and member_role != role:
            continue
        emit_joined(member_role, info, session_id, seed_hex, schedule, both)


MIN_RATE, MAX_RATE = 36000, 96000


def _sample_rate(value) -> int:
    """Accept only a plausible hardware rate; anything else falls back to 48 kHz."""
    try:
        rate = int(value)
    except (TypeError, ValueError):
        return 48000
    if not MIN_RATE <= rate <= MAX_RATE:
        log(f"rejected reported sample_rate {rate}; using 48000")
        return 48000
    return rate


def emit_joined(role: str, info: dict, session_id: str, seed_hex: str,
                schedule: dict, both: bool) -> None:
    payload = {
        "session_id": session_id,
        "role": role,
        "seed_hex": seed_hex,
        "schedule": schedule,
        "partner_present": both,
        "probe_sample_rate": info["sample_rate"],
    }
    try:
        payload["probe_b64"] = probe_base64(seed_hex, role, info["sample_rate"])
    except MissingSignalCode as exc:
        payload["probe_b64"] = None
        payload["probe_error"] = str(exc)
        log(f"WARNING {exc}")
    socketio.emit("joined", payload, to=info["sid"])


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@socketio.on("arm")
def on_arm(data=None):
    session_id = (data or {}).get("session_id")
    with PAIR.lock:
        if not PAIR.session_id or session_id != PAIR.session_id:
            emit("error_msg", {"message": "stale session; reload and join again"})
            return
        role = next((r for r, i in PAIR.members.items() if i["sid"] == request.sid), None)
        if role is None:
            emit("error_msg", {"message": "you are not in this session"})
            return
        rerate = None
        if (data or {}).get("sample_rate") is not None:
            reported = _sample_rate(data.get("sample_rate"))
            if reported != PAIR.members[role]["sample_rate"]:
                log(f"role={role} rate changed {PAIR.members[role]['sample_rate']} -> {reported}; "
                    "regenerating its probe")
                PAIR.members[role]["sample_rate"] = reported
                directory = session_dir_for(PAIR.session_id)
                session = read_json(directory / "session.json")
                if session:
                    session.setdefault("roles", {}).setdefault(role, {})["sample_rate"] = reported
                    write_json_atomic(directory / "session.json", session)
                rerate = (role, dict(PAIR.members[role]), PAIR.session_id, PAIR.seed_hex,
                          {"start_server_ms": None, **SCHEDULE}, len(PAIR.members) == 2)
        PAIR.armed.add(role)
        log(f"arm role={role} armed={sorted(PAIR.armed)}")
        socketio.emit("armed", {"armed": sorted(PAIR.armed)})
    if rerate:
        emit_joined(*rerate)
    with PAIR.lock:
        if len(PAIR.armed) < 2 or PAIR.started:
            return
        PAIR.started = True
        start_server_ms = now_ms() + START_DELAY_MS
        directory = session_dir_for(PAIR.session_id)
        session = read_json(directory / "session.json") or build_session_json()
        session.setdefault("schedule", dict(SCHEDULE))["start_server_ms"] = start_server_ms
        write_json_atomic(directory / "session.json", session)
        schedule = session["schedule"]
    log(f"start broadcast session={session_id} at {start_server_ms:.1f}")
    socketio.emit("start", {"session_id": session_id, "start_server_ms": start_server_ms,
                            "schedule": schedule, "server_ms": now_ms()})


@socketio.on("abort")
def on_abort(data=None):
    with PAIR.lock:
        log("abort requested; pair reset")
        PAIR.reset()
    socketio.emit("pair_reset", {"why": "aborted"})


if __name__ == "__main__":
    missing = [p for p in (SSL_CERT_PATH, SSL_KEY_PATH) if not p.exists()]
    if missing:
        raise SystemExit(f"TLS material missing: {', '.join(str(p) for p in missing)}")
    log(f"sound-bound serving on https://{HOST}:{PORT}/  (sessions at /sessions)")
    socketio.run(
        app,
        host=HOST,
        port=PORT,
        ssl_context=(str(SSL_CERT_PATH), str(SSL_KEY_PATH)),
        allow_unsafe_werkzeug=True,
    )
