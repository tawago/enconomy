"""fieldtest server: two phones, one recording each, probes in fieldprobes.SEQUENCE order
(v2 default: N250 -> N500 -> N1s -> JBL -> JBL250; N30/JB/JBQ still served for old sessions).

Flask + SocketIO over TLS on :5004. One pair at a time. See CONTRACT.md sections 6-8.

Signal code (fieldprobes.py, fieldanalysis.py) is imported lazily inside functions so
this server boots and serves pages even before it lands. Missing signal code gives
503 on the probe route and a failed result.json on analysis.

Choices not pinned by the contract (simplest option):
- If fieldprobes cannot be imported, SCHEDULE falls back to FALLBACK_SCHEDULE below
  (a verbatim copy of fieldprobes.SCHEDULE, v2) so pairing still works.
- FIELD_PORT overrides the port (tests run a second instance next to the live one).
- The probe route re-reads FIELD_GAIN_DB from session.json, not the environment.
- /sessions lists SESSIONS_DIR only (not data/synth).
- FIELD_SESSIONS_DIR overrides SESSIONS_DIR (run.sh e2e points it at data/e2e so
  fake-phone sessions never mix with field runs). /api/info reports it.
- Stuck-run watchdog: a started session with no analysis after
  START_DELAY + record_total_s + UPLOAD_GRACE_S is reset (pair_reset "timeout").
  `abort` is accepted from any client (trusted-client spike, CONTRACT section 12).
"""

from __future__ import annotations

import io
import json
import os
import secrets
import sys
import threading
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from flask_socketio import SocketIO, emit

HERE = Path(__file__).resolve().parent            # fieldtest/
MELODY = HERE.parent                              # spikes/melody/
SB_ROOT = HERE.parents[2]                         # research/sound-bound/
CERTS = HERE.parents[3] / "fuzzy-commitment"      # cert.pem, key.pem
for _p in (HERE, MELODY, SB_ROOT):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

DEFAULT_SESSIONS_DIR = HERE / "data" / "sessions"
SESSIONS_DIR = Path(os.environ.get("FIELD_SESSIONS_DIR") or DEFAULT_SESSIONS_DIR).resolve()
SSL_CERT_PATH = CERTS / "cert.pem"
SSL_KEY_PATH = CERTS / "key.pem"

VERSION = "fieldtest-v1"
PORT = int(os.environ.get("FIELD_PORT", "5004"))  # contract port; env override only for tests
HOST = "0.0.0.0"
PROBES = ("N30", "N250", "N500", "N1s", "JB", "JBQ", "JBL", "JBL250")   # every probe the routes accept (= fieldprobes.PROBES)
ROLES = ("A", "B")
START_DELAY_MS = 2500.0          # start = now + 2.5 s: both phones get the event and schedule ahead
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 19 s float32 at 96 kHz is ~7 MB; generous ceiling
MIN_RATE, MAX_RATE = 36000, 96000     # fieldprobes accepts this sr range only
UPLOAD_GRACE_S = 45.0            # after capture ends: upload + slow phone; then the run is declared dead
PREVIEW_SEED = "11" * 32         # fixed public seed for listening previews
PREVIEW_SR = 48000               # preview WAV rate
PREVIEW_PAD_S = 0.3              # silence each side of a preview
ROOMS = ("small", "big", "other")
POSES = ("table", "hand")
NOISES = ("quiet", "music", "talk")

# Verbatim copy of fieldprobes.SCHEDULE (v2), used only if fieldprobes is missing.
FALLBACK_SCHEDULE = {
    "lead_s": 0.5,
    "record_total_s": 27.0,
    "search_pre_s": 0.15,
    "search_post_s": 0.25,
    "order": [
        "N250",
        "N500",
        "N1s",
        "JBL",
        "JBL250"
    ],
    "probes": {
        "N250": {
            "start_s": 0.0,
            "rounds": 2,
            "period_s": 1.9,
            "b_offset_s": 0.95,
            "dur_s": 0.25
        },
        "N500": {
            "start_s": 3.8,
            "rounds": 2,
            "period_s": 2.4,
            "b_offset_s": 1.2,
            "dur_s": 0.5
        },
        "N1s": {
            "start_s": 8.6,
            "rounds": 2,
            "period_s": 3.4,
            "b_offset_s": 1.7,
            "dur_s": 1.0
        },
        "JBL": {
            "start_s": 15.4,
            "rounds": 2,
            "period_s": 3.4,
            "b_offset_s": 1.7,
            "dur_s": 1.0
        },
        "JBL250": {
            "start_s": 22.2,
            "rounds": 2,
            "period_s": 1.9,
            "b_offset_s": 0.95,
            "dur_s": 0.25
        }
    }
}


def parse_gain_env(raw: str | None) -> dict:
    """FIELD_GAIN_DB="N250:0,N1s:-3,JBL:0" -> {probe: dB}; missing or junk = 0."""
    gains = {p: 0.0 for p in PROBES}
    for part in (raw or "").split(","):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        name = name.strip()
        if name in gains:
            try:
                gains[name] = float(value)
            except ValueError:
                pass
    return gains


GAIN_DB = parse_gain_env(os.environ.get("FIELD_GAIN_DB"))

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


# ---------------------------------------------------------------- signal code (lazy)

class MissingSignalCode(RuntimeError):
    """fieldprobes.py / fieldanalysis.py not importable."""


def _fieldprobes():
    try:
        import fieldprobes
    except Exception as exc:
        raise MissingSignalCode(f"fieldprobes unavailable: {exc!r}") from exc
    return fieldprobes


def schedule_constant() -> dict:
    try:
        return json.loads(json.dumps(_fieldprobes().SCHEDULE))
    except Exception as exc:
        log(f"WARNING using FALLBACK_SCHEDULE ({exc})")
        return json.loads(json.dumps(FALLBACK_SCHEDULE))


def render_probe(seed_hex: str, probe: str, role: str, sr: int, gain_db: float):
    fp = _fieldprobes()
    try:
        wave_, info = fp.render(seed_hex, probe, role, int(sr), gain_db=float(gain_db))
    except ValueError:
        raise
    except Exception as exc:
        raise MissingSignalCode(f"fieldprobes.render failed: {exc!r}") from exc
    return wave_, info


def run_analysis(session_dir: Path) -> dict:
    try:
        import fieldanalysis
    except Exception as exc:
        raise MissingSignalCode(f"fieldanalysis unavailable: {exc!r}") from exc
    return fieldanalysis.analyze_session(session_dir)


# ---------------------------------------------------------------- pending pair

class Pair:
    """The single session being assembled right now."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        self.session_id: str | None = None
        self.seed_hex: str | None = None
        self.members: dict[str, dict] = {}   # role -> {sid, client_id, user_agent, sample_rate}
        self.armed: set[str] = set()
        self.started = False
        self.labels: dict | None = None
        self.schedule: dict | None = None


PAIR = Pair()
FILE_LOCK = threading.RLock()   # guards session.json read-modify-write across threads


def session_dir_for(session_id: str) -> Path:
    safe = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in "-_")
    return SESSIONS_DIR / safe


def update_session_json(session_id: str, mutate) -> dict | None:
    path = session_dir_for(session_id) / "session.json"
    with FILE_LOCK:
        session = read_json(path)
        if session is None:
            return None
        mutate(session)
        write_json_atomic(path, session)
        return session


def _number(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _choice(value, allowed, default):
    return value if value in allowed else default


def _sample_rate(value):
    try:
        rate = int(value)
    except (TypeError, ValueError):
        return None
    return rate if MIN_RATE <= rate <= MAX_RATE else None


def clean_labels(data: dict) -> dict:
    return {
        "label_cm": _number(data.get("label_cm")),
        "room": _choice(data.get("room"), ROOMS, "other"),
        "pose": _choice(data.get("pose"), POSES, "table"),
        "noise": _choice(data.get("noise"), NOISES, "quiet"),
        "note": str(data.get("note") or "")[:200],
    }


def build_session_json() -> dict:
    return {
        "version": VERSION,
        "session_id": PAIR.session_id,
        "created_at": iso_now(),
        "seed_hex": PAIR.seed_hex,
        "labels": PAIR.labels,
        "schedule": {**PAIR.schedule, "start_server_ms": None},
        "gain_db": dict(GAIN_DB),
        "roles": {
            role: {
                "client_id": info["client_id"],
                "sample_rate": info["sample_rate"],
                "user_agent": info["user_agent"],
                "render": {},
            }
            for role, info in PAIR.members.items()
        },
        "synthetic": None,
    }


# ---------------------------------------------------------------- HTTP routes

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/time")
def api_time():
    return jsonify({"server_ms": now_ms()})


@app.route("/api/info")
def api_info():
    return jsonify({"version": VERSION, "sessions_dir": str(SESSIONS_DIR),
                    "default_sessions_dir": SESSIONS_DIR == DEFAULT_SESSIONS_DIR.resolve()})


@app.route("/api/probe/<session_id>/<role>/<probe>.f32")
def api_probe(session_id: str, role: str, probe: str):
    if role not in ROLES or probe not in PROBES:
        return jsonify({"error": "bad role or probe"}), 400
    sr = _sample_rate(request.args.get("sr"))
    if sr is None:
        return jsonify({"error": f"sr must be an int in {MIN_RATE}..{MAX_RATE}"}), 400
    session = read_json(session_dir_for(session_id) / "session.json")
    if session is None:
        return jsonify({"error": "unknown session"}), 404
    gain = float((session.get("gain_db") or {}).get(probe, 0.0))
    try:
        samples, info = render_probe(session["seed_hex"], probe, role, sr, gain)
    except MissingSignalCode as exc:
        return jsonify({"error": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    import numpy as np
    body = np.asarray(samples, dtype="<f4").tobytes()

    def mutate(s):
        s.setdefault("roles", {}).setdefault(role, {}).setdefault("render", {})[probe] = info
    update_session_json(session_id, mutate)
    log(f"probe session={session_id[:8]} role={role} probe={probe} sr={sr} n={len(samples)}")
    return Response(body, mimetype="application/octet-stream", headers={
        "X-Sample-Rate": str(sr), "X-Samples": str(len(samples)),
        "Cache-Control": "no-store",
        "Access-Control-Expose-Headers": "X-Sample-Rate, X-Samples",
    })


@app.route("/preview/<probe>.wav")
def preview(probe: str):
    role = request.args.get("role", "A")
    if probe not in PROBES or role not in ROLES:
        return jsonify({"error": "bad role or probe"}), 400
    try:
        samples, _ = render_probe(PREVIEW_SEED, probe, role, PREVIEW_SR, GAIN_DB[probe])
    except MissingSignalCode as exc:
        return jsonify({"error": str(exc)}), 503
    import numpy as np
    pad = np.zeros(int(round(PREVIEW_PAD_S * PREVIEW_SR)), dtype=np.float64)
    x = np.concatenate([pad, np.asarray(samples, dtype=np.float64), pad])
    pcm = np.clip(np.round(x * 32767.0), -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(PREVIEW_SR)
        w.writeframes(pcm.tobytes())
    return Response(buf.getvalue(), mimetype="audio/wav",
                    headers={"Cache-Control": "no-store"})


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


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


@app.route("/sessions")
def sessions_page():
    items = []
    skipped_e2e = 0
    for directory in SESSIONS_DIR.glob("*") if SESSIONS_DIR.exists() else []:
        if not directory.is_dir():
            continue
        session = read_json(directory / "session.json") or {}
        if SESSIONS_DIR == DEFAULT_SESSIONS_DIR.resolve() and (session.get("labels") or {}).get("note") == "e2e":
            skipped_e2e += 1   # fake-phone test run, not field data
            continue
        result = read_json(directory / "result.json") or {}
        items.append((session.get("created_at", ""), directory.name, session, result))
    items.sort(key=lambda t: t[0], reverse=True)

    used = {p for _, _, _, r in items for p in (r.get("probes") or {})}
    used |= {p for _, _, s, _ in items for p in ((s.get("schedule") or {}).get("probes") or {})}
    shown = [p for p in PROBES if p in used] or list(schedule_constant()["order"])
    rows = []
    for created, name, session, result in items:
        labels = session.get("labels") or {}
        cells = [
            f"<td class=mono title='{_esc(name)}'>{_esc(name[:8])}</td>",
            f"<td>{_esc(created[:19])}</td>",
            f"<td>{'touch' if labels.get('label_cm') == 0 else _fmt(labels.get('label_cm'), 0)}</td>",
            f"<td>{_esc(labels.get('room', ''))}</td>",
            f"<td>{_esc(labels.get('pose', ''))}</td>",
            f"<td>{_esc(labels.get('noise', ''))}</td>",
        ]
        probes = result.get("probes") or {}
        for p in shown:
            pr = probes.get(p) or {}
            summ = pr.get("summary") or {}
            dec = (pr.get("decision") or {}).get("label")
            ow = (pr.get("decision_ownwalk") or {}).get("label") or ""
            if dec is None:
                dec = result.get("status", "pending") if p == shown[0] else ""
            ur, tr = summ.get("usable_rounds"), summ.get("total_rounds")
            cells += [
                f"<td class='sep dec {_esc(str(dec).lower())}'>{_esc(dec)}</td>",
                f"<td class='dec {_esc(ow.lower())}'>{_esc(ow)}</td>",
                f"<td>{_fmt(summ.get('flight_median'))}</td>",
                f"<td>{_fmt(summ.get('spread'))}</td>",
                f"<td>{'&mdash;' if ur is None else f'{ur}/{tr}'}</td>",
                f"<td>{_fmt(summ.get('min_margin_db'))}</td>",
            ]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    hidden_note = f" &middot; {skipped_e2e} e2e test session(s) hidden" if skipped_e2e else ""
    probe_heads = "".join(
        f"<th class=sep>{p}</th><th>ownwalk</th><th>flight</th><th>spread</th><th>usable</th><th>margin dB</th>"
        for p in shown)
    html = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>fieldtest sessions</title>
<style>
:root{{color-scheme:dark}}
body{{font:13px/1.5 system-ui,sans-serif;margin:16px;background:#0f1115;color:#e8e8ea}}
.wrap{{overflow-x:auto}}
table{{border-collapse:collapse}}
th,td{{border-bottom:1px solid #2a2e37;padding:5px 7px;text-align:right;white-space:nowrap}}
th{{color:#8b93a1;font-weight:500}}
td:nth-child(-n+6),th:nth-child(-n+6){{text-align:left}}
.sep{{border-left:1px solid #3a404c}}
.mono{{font-family:ui-monospace,monospace}}
.near{{color:#7ee2a8}} .far{{color:#7ab7ff}} .undecided{{color:#ffcf6b}} .failed{{color:#ff7b72}}
a{{color:#7ab7ff}}
</style></head><body>
<h1>fieldtest sessions ({len(rows)})</h1>
<p><a href="/">&larr; back</a> &middot; decision/flight/spread/margin by the primary rule ("first"); ownwalk = decision by the ownwalk rule &middot; flight/spread in cm &middot; all decisions PROVISIONAL.
{hidden_note} &middot; dir {_esc(SESSIONS_DIR.name)}</p>
<div class=wrap><table><thead><tr>
<th>id</th><th>created (UTC)</th><th>label cm</th><th>room</th><th>pose</th><th>noise</th>{probe_heads}
</tr></thead><tbody>{''.join(rows)}</tbody></table></div></body></html>"""
    return Response(html, mimetype="text/html")


@app.route("/api/upload/<session_id>/<role>", methods=["POST"])
def api_upload(session_id: str, role: str):
    if role not in ROLES:
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
    log(f"upload session={session_id[:8]} role={role} bytes={len(payload)}")

    with FILE_LOCK:
        both = all((directory / f"recording_{r}.wav").exists() and
                   (directory / f"meta_{r}.json").exists() for r in ROLES)
        marker = directory / ".analysis_started"
        launch = both and not marker.exists()
        if launch:
            marker.write_text(iso_now())
    if launch:
        socketio.emit("analyzing", {"session_id": session_id})
        socketio.start_background_task(analyze_and_broadcast, session_id)
    return jsonify({"ok": True, "both_uploaded": both})


def analyze_and_broadcast(session_id: str) -> None:
    directory = session_dir_for(session_id)
    log(f"analysis start session={session_id[:8]}")
    t0 = time.time()
    try:
        result = run_analysis(directory)
        if not isinstance(result, dict):
            raise RuntimeError(f"analyze_session returned {type(result).__name__}")
    except MissingSignalCode as exc:
        result = {"status": "failed", "version": VERSION, "session_id": session_id,
                  "reasons": [f"server_missing_signal_code: {exc}"]}
        write_json_atomic(directory / "result.json", result)
    except Exception as exc:
        result = {"status": "failed", "version": VERSION, "session_id": session_id,
                  "reasons": [f"analysis_crashed: {exc!r}"]}
        write_json_atomic(directory / "result.json", result)
    log(f"analysis done session={session_id[:8]} status={result.get('status')} "
        f"in {time.time() - t0:.1f} s")
    socketio.emit("result", {"session_id": session_id, "result": result})
    with PAIR.lock:
        if PAIR.session_id == session_id:
            PAIR.reset()
            log("pair reset, ready for the next session")


# ---------------------------------------------------------------- socket events

@socketio.on("connect")
def on_connect(auth=None):
    log(f"connect sid={request.sid}")


@socketio.on("disconnect")
def on_disconnect(reason=None):
    with PAIR.lock:
        for role, info in list(PAIR.members.items()):
            if info["sid"] == request.sid and not PAIR.started:
                log(f"role {role} left before start; dropping pending pair")
                PAIR.reset()
                socketio.emit("pair_reset", {"why": "a device disconnected"})
                break


def joined_payload(role: str, both: bool) -> dict:
    return {
        "session_id": PAIR.session_id,
        "role": role,
        "partner_present": both,
        "labels": PAIR.labels,
        "schedule": {**PAIR.schedule, "start_server_ms": None},
        "probes": list(PAIR.schedule.get("order") or PAIR.schedule["probes"]),
    }


@socketio.on("join")
def on_join(data=None):
    data = data or {}
    with PAIR.lock:
        if PAIR.started:
            emit("error_msg", {"message": "a session is already running; wait for it"})
            return
        if any(i["sid"] == request.sid for i in PAIR.members.values()):
            emit("error_msg", {"message": "already joined"})
            return
        free = [r for r in ROLES if r not in PAIR.members]
        if not free:
            emit("error_msg", {"message": "both roles taken"})
            return
        prefer = data.get("prefer_role")
        role = prefer if prefer in free else free[0]
        if not PAIR.members:
            PAIR.session_id = uuid.uuid4().hex
            PAIR.seed_hex = secrets.token_bytes(32).hex()
            PAIR.labels = clean_labels(data)
            PAIR.schedule = schedule_constant()
        PAIR.members[role] = {
            "sid": request.sid,
            "client_id": uuid.uuid4().hex[:12],
            "sample_rate": None,
            "user_agent": str(data.get("user_agent") or request.headers.get("User-Agent", ""))[:300],
        }
        both = len(PAIR.members) == 2
        log(f"join role={role} session={PAIR.session_id[:8]} both={both}")
        if both:
            directory = session_dir_for(PAIR.session_id)
            directory.mkdir(parents=True, exist_ok=True)
            with FILE_LOCK:
                write_json_atomic(directory / "session.json", build_session_json())
            log(f"session dir ready {directory}")
        targets = [(r, i["sid"]) for r, i in PAIR.members.items()] if both else [(role, request.sid)]
        payloads = [(sid, joined_payload(r, both)) for r, sid in targets]
    for sid, payload in payloads:
        socketio.emit("joined", payload, to=sid)


@socketio.on("arm")
def on_arm(data=None):
    data = data or {}
    session_id = data.get("session_id")
    with PAIR.lock:
        if not PAIR.session_id or session_id != PAIR.session_id:
            emit("error_msg", {"message": "stale session; reload and join again"})
            return
        if len(PAIR.members) < 2:
            emit("error_msg", {"message": "partner has not joined yet"})
            return
        role = next((r for r, i in PAIR.members.items() if i["sid"] == request.sid), None)
        if role is None:
            emit("error_msg", {"message": "you are not in this session"})
            return
        rate = _sample_rate(data.get("sample_rate"))
        PAIR.members[role]["sample_rate"] = rate
        PAIR.armed.add(role)
        armed = sorted(PAIR.armed)
        log(f"arm role={role} sr={rate} armed={armed}")
        go = len(PAIR.armed) == 2 and not PAIR.started
        if go:
            PAIR.started = True
            start_server_ms = now_ms() + START_DELAY_MS
            rates = {r: i["sample_rate"] for r, i in PAIR.members.items()}

            def mutate(s):
                s.setdefault("schedule", {})["start_server_ms"] = start_server_ms
                for r, sr in rates.items():
                    s.setdefault("roles", {}).setdefault(r, {})["sample_rate"] = sr
            session = update_session_json(PAIR.session_id, mutate) or {}
            schedule = session.get("schedule") or {**PAIR.schedule,
                                                   "start_server_ms": start_server_ms}
    socketio.emit("armed", {"armed": armed})
    if go:
        deadline_s = START_DELAY_MS / 1000.0 + float(schedule.get("record_total_s", 19.0)) + UPLOAD_GRACE_S
        socketio.start_background_task(watchdog, session_id, deadline_s)
        log(f"start broadcast session={session_id[:8]} at {start_server_ms:.1f}")
        socketio.emit("start", {"session_id": session_id, "start_server_ms": start_server_ms,
                                "schedule": schedule, "server_ms": now_ms()})


def watchdog(session_id: str, deadline_s: float) -> None:
    """Reset a started pair whose uploads never completed (tab closed, upload failed, ...)."""
    socketio.sleep(deadline_s)
    with PAIR.lock:
        if PAIR.session_id != session_id or not PAIR.started:
            return
        if (session_dir_for(session_id) / ".analysis_started").exists():
            return   # analysis running; its result resets the pair
        log(f"watchdog: session={session_id[:8]} no complete upload after {deadline_s:.0f} s; pair reset")
        PAIR.reset()
    socketio.emit("pair_reset", {"why": "timeout: an upload never arrived", "session_id": session_id})


@socketio.on("abort")
def on_abort(data=None):
    with PAIR.lock:
        sid = PAIR.session_id
        log(f"abort requested by {request.sid}; pair reset (session={str(sid)[:8]})")
        PAIR.reset()
    socketio.emit("pair_reset", {"why": "aborted", "session_id": sid})


if __name__ == "__main__":
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    missing = [p for p in (SSL_CERT_PATH, SSL_KEY_PATH) if not p.exists()]
    if missing:
        raise SystemExit(f"TLS material missing: {', '.join(str(p) for p in missing)}")
    log(f"fieldtest serving on https://{HOST}:{PORT}/  gains={GAIN_DB}  (sessions at /sessions)")
    socketio.run(app, host=HOST, port=PORT,
                 ssl_context=(str(SSL_CERT_PATH), str(SSL_KEY_PATH)),
                 allow_unsafe_werkzeug=True)
