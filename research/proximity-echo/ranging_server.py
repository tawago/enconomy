"""Isolated, two-browser acoustic ranging diagnostics for the LAN harness.

The /ranging namespace owns its participants, trial state, and artifacts. It never
reads or writes the legacy echo log. Browser metadata and recordings are diagnostic
inputs, not trusted attestations. Emission timing is recovered from the recordings;
the start message only keeps the two recording windows roughly overlapping.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
from flask import abort, jsonify, render_template, request, send_file


NAMESPACE = "/ranging"
ROLES = ("initiator", "observer")
RECEIVERS = {"initiator": "A", "observer": "B"}
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_RECORDING_SECONDS = 45.0
READY_TIMEOUT_SECONDS = 45.0
UPLOAD_GRACE_SECONDS = 35.0
ANALYSIS_TIMEOUT_SECONDS = 120.0
START_DELAY_MS = 600
SCHEMA_VERSION = "ranging-server-v1"
PROFILES = {"coded-probes", "beepbeep-reference"}


def source_provenance(analyzer, protocol: dict) -> dict:
    base = Path(__file__).parent
    files = ("server.py", "ranging_server.py", "ranging_protocol.py", "ranging_analysis.py",
             "beepbeep_protocol.py", "beepbeep_analysis.py", "analysis/beepbeep_reference.py",
             "ranging_integrity.py", "ranging_peaks.py",
             "static/ranging.js", "static/ranging-view.js", "static/ranging-audio.js",
             "static/ranging-recorder-worklet.js")
    sources = {}
    for name in files:
        path = base / name
        if path.is_file():
            data = path.read_bytes()
            sources[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        else:
            sources[name] = {"sha256": None, "available": False}
    module = sys.modules.get(getattr(analyzer, "__module__", ""))
    if protocol.get("version") == "beepbeep-v1":
        import beepbeep_analysis
        module = beepbeep_analysis
    return {"server_schema_version": SCHEMA_VERSION,
            "analysis_version": getattr(module, "ANALYSIS_VERSION", None),
            "protocol_version": protocol.get("version"),
            "protocol_profile": protocol.get("profile", "coded-probes") if protocol else None,
            "sources": sources,
            "source_snapshot_at": _now_iso(),
            "source_hash_semantics": "On-disk source at trial creation; restart the server after editing code."}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_create(path: Path, data: bytes) -> None:
    """Publish a complete new artifact without replacing an existing artifact."""
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def write_json(path: Path, value: dict) -> None:
    atomic_create(path, json.dumps(value, ensure_ascii=False, indent=2,
                                 allow_nan=False).encode("utf-8"))


def _object(value, *, limit: int = MAX_METADATA_BYTES) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Metadata must contain finite JSON values") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError("Metadata exceeds the size limit")
    return json.loads(encoded)


def _label(value, *, limit=200) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Labels must be text of at most {limit} characters")
    return value


def _experiment(value) -> dict:
    value = _object({} if value is None else value, limit=16 * 1024)
    result = {}
    for key in ("session_label", "room", "pose", "device_a_label", "device_b_label", "notes"):
        result[key] = _label(value.get(key), limit=1000 if key == "notes" else 200)
    for key in ("measured_body_gap_cm", "self_speaker_mic_a_cm", "self_speaker_mic_b_cm"):
        item = value.get(key)
        if item is None or item == "":
            result[key] = None
        elif (isinstance(item, bool) or not isinstance(item, (int, float))
              or not math.isfinite(item) or not 0 <= item <= 100_000):
            raise ValueError(f"{key} must be a finite, nonnegative measurement in cm")
        else:
            result[key] = float(item)
    return result


def _capture_identity(metadata: dict, protocol: dict) -> None:
    """New reference captures must acknowledge the exact server-selected profile.

    This binds the software configuration only. Identical reference chirps do not
    acoustically authenticate an emission or establish replay resistance.
    """
    if protocol.get("version") != "beepbeep-v1":
        return
    expected = {"protocol_id": protocol["protocol_id"], "session_id": protocol["session_id"],
                "protocol_version": protocol["version"], "profile": protocol["profile"]}
    for name, value in expected.items():
        if metadata.get(name) != value:
            raise ValueError(f"Capture {name} does not match the selected reference protocol; refresh both pages")


def validate_wav(encoded, metadata: dict, duration_s: float) -> tuple[bytes, dict]:
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("Missing base64 WAV payload")
    if len(encoded) > 4 * ((MAX_AUDIO_BYTES + 2) // 3):
        raise ValueError("WAV exceeds the upload size limit")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid base64 WAV payload") from exc
    if len(raw) > MAX_AUDIO_BYTES:
        raise ValueError("WAV exceeds the upload size limit")
    try:
        with sf.SoundFile(io.BytesIO(raw)) as wav:
            if wav.format not in {"WAV", "WAVEX"}:
                raise ValueError("Only an uncompressed WAV recording is accepted")
            if wav.subtype not in {"FLOAT", "PCM_16", "PCM_24", "PCM_32"}:
                raise ValueError("WAV must contain uncompressed PCM or float32 samples")
            if wav.channels != 1 or not 16_000 <= wav.samplerate <= 192_000:
                raise ValueError("Expected a mono WAV with a supported sample rate")
            if not 0 < wav.frames <= wav.samplerate * min(MAX_RECORDING_SECONDS, duration_s + 5.0):
                raise ValueError("Recording has zero frames or exceeds the duration limit")
            actual = {"sample_rate": wav.samplerate, "frame_count": wav.frames,
                      "channel_count": wav.channels, "subtype": wav.subtype,
                      "duration_s": wav.frames / wav.samplerate}
            for field_name in ("sample_rate", "frame_count", "channel_count"):
                declared = metadata.get(field_name)
                if declared is not None and (isinstance(declared, bool) or declared != actual[field_name]):
                    raise ValueError(f"Metadata {field_name} does not match the WAV")
            if not np.isfinite(wav.read(dtype="float32")).all():
                raise ValueError("Recording contains nonfinite samples")
    except (RuntimeError, sf.LibsndfileError) as exc:
        raise ValueError("The payload is not a readable WAV recording") from exc
    actual.update({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return raw, actual


@dataclass
class RangingTrial:
    trial_id: str
    directory: Path
    protocol: dict
    experiment: dict
    members: dict[str, dict]
    state: str = "preparing"
    created_at: str = field(default_factory=_now_iso)
    deadline: float = 0.0
    ready: set[str] = field(default_factory=set)
    uploads: dict[str, dict] = field(default_factory=dict)
    report: dict | None = None
    provenance: dict = field(default_factory=dict)
    timer: threading.Timer | None = None


class RangingService:
    def __init__(self, app, socketio, data_dir: Path, *, protocol_builder: Callable,
                 analyzer: Callable, clock: Callable = time.monotonic, watchdog: bool = True):
        self.app, self.socketio = app, socketio
        self.data_dir = Path(data_dir)
        self.protocol_builder, self.analyzer = protocol_builder, analyzer
        self.clock, self.watchdog = clock, watchdog
        self.lock = threading.RLock()
        self.participants: dict[str, dict] = {}
        self.trials: dict[str, RangingTrial] = {}
        self.current: RangingTrial | None = None

    def emit(self, event: str, payload: dict, sid: str | None = None) -> None:
        # An unjoined third browser must not receive the two participants' capture.
        recipients = (sid,) if sid is not None else tuple(self.participants)
        for recipient in recipients:
            self.socketio.emit(event, payload, to=recipient, namespace=NAMESPACE)

    def error(self, message: str, *, code="invalid_request", trial_id=None) -> None:
        self.emit("error", {"message": message, "code": code, "trial_id": trial_id}, request.sid)

    def broadcast_status(self) -> None:
        with self.lock:
            active = self.current
            armed = [p["role"] for p in self.participants.values() if p["armed"]]
            payload = {
                "participants": {p["role"]: {"participant_id": p["participant_id"],
                                              "device_label": p["device_label"]}
                                 for p in self.participants.values()},
                "count": len(self.participants), "armed_roles": armed,
                "state": active.state if active else "idle",
                "trial_id": active.trial_id if active else None,
                "can_start": active is None and len(armed) == 2,
            }
        self.emit("peer_status", payload)

    def _deadline(self, trial: RangingTrial, seconds: float) -> None:
        if trial.timer:
            trial.timer.cancel()
        trial.deadline = self.clock() + seconds
        if self.watchdog:
            trial.timer = threading.Timer(seconds, self.check_timeout)
            trial.timer.daemon = True
            trial.timer.start()

    def check_timeout(self, now=None) -> None:
        with self.lock:
            trial = self.current
            if trial is None or (self.clock() if now is None else now) < trial.deadline:
                return
            stage = trial.state
            self._fail(trial, f"{stage}_timeout", f"Timed out while {stage}")

    def _attempt(self, trial: RangingTrial, event: str, detail: dict) -> None:
        write_json(trial.directory / f"attempt_{uuid.uuid4().hex}.json",
                   {"event": event, "at": _now_iso(), **detail})

    def _finish(self, trial: RangingTrial, report: dict) -> None:
        """Called under the lock. A timeout and an analysis result cannot both win."""
        if trial.report is not None:
            return
        report = _object(report, limit=32 * 1024 * 1024)
        report.setdefault("analysis_version", trial.provenance.get("analysis_version"))
        report.update({"schema_version": SCHEMA_VERSION, "trial_id": trial.trial_id,
                       "experiment": trial.experiment, "created_at": trial.created_at,
                       "provenance": trial.provenance,
                       "completed_at": _now_iso(),
                       "capture_trust": "Cooperative browser diagnostic; capture and metadata are not attestations.",
                       "artifacts": self.artifacts(trial)})
        write_json(trial.directory / "report.json", report)
        trial.report = report
        trial.state = "finished"
        if trial.timer:
            trial.timer.cancel()
        if self.current is trial:
            self.current = None
        payload = {"trial_id": trial.trial_id, "report": report,
                   "artifact_url": f"/ranging/trials/{trial.trial_id}/report.json",
                   "manifest_url": f"/ranging/trials/{trial.trial_id}/manifest.json",
                   "recordings": self.artifacts(trial)["recordings"]}
        self.emit("result", payload)
        self.broadcast_status()

    def _fail(self, trial: RangingTrial, code: str, message: str) -> None:
        if trial.report is not None:
            return
        self._attempt(trial, "trial_failed", {"code": code, "message": message})
        self._finish(trial, {"status": "failed", "server_status": code,
                            "decision": {"label": "INCONCLUSIVE", "reasons": [message]},
                            "reasons": [message], "quality_reasons": [code],
                            "failure": {"code": code, "message": message}})
        self.emit("trial_aborted", {"trial_id": trial.trial_id, "reason": message})

    def artifacts(self, trial: RangingTrial) -> dict:
        base = f"/ranging/trials/{trial.trial_id}"
        return {"protocol": f"{base}/protocol.json", "trial": f"{base}/trial.json",
                "manifest": f"{base}/manifest.json", "provenance": f"{base}/provenance.json",
                "recordings": {role: f"{base}/recording_{RECEIVERS[role]}.wav"
                               for role in trial.uploads},
                "metadata": {role: f"{base}/upload_{RECEIVERS[role]}.json"
                             for role in trial.uploads}}

    @staticmethod
    def trial_record(trial: RangingTrial) -> dict:
        return {"schema_version": SCHEMA_VERSION, "trial_id": trial.trial_id,
                "protocol_profile": trial.protocol.get("profile", "coded-probes") if trial.protocol else None,
                "created_at": trial.created_at, "experiment": trial.experiment,
                "provenance": trial.provenance,
                "participants": {p["role"]: p for p in trial.members.values()},
                "timing_use": "Start timestamps coordinate capture only; they are not arrival measurements."}

    def on_join(self, data=None):
        try:
            data = _object({} if data is None else data, limit=16 * 1024)
            label = _label(data.get("device_label"))
            user_agent = _label(data.get("user_agent"), limit=2000)
            session_label = _label(data.get("session_label"))
        except ValueError as exc:
            return self.error(str(exc))
        self.check_timeout()
        with self.lock:
            if request.sid in self.participants:
                participant = self.participants[request.sid]
            elif len(self.participants) == 2:
                return self.error("Ranging room already has two participants", code="room_full")
            else:
                held = {p["role"] for p in self.participants.values()}
                participant = {"participant_id": uuid.uuid4().hex, "role": next(r for r in ROLES if r not in held),
                               "device_label": label, "user_agent": user_agent,
                               "session_label": session_label, "armed": False, "arm_metadata": {}}
                self.participants[request.sid] = participant
            self.emit("joined", participant, request.sid)
        self.broadcast_status()

    def on_arm(self, data=None):
        try:
            data = _object({} if data is None else data, limit=MAX_METADATA_BYTES)
            armed = data.get("armed", True)
            if not isinstance(armed, bool):
                raise ValueError("armed must be a boolean")
            metadata = _object(data.get("metadata", {}))
        except ValueError as exc:
            return self.error(str(exc))
        self.check_timeout()
        with self.lock:
            participant = self.participants.get(request.sid)
            if participant is None:
                return self.error("Join this ranging session first", code="not_joined")
            if self.current and armed:
                return self.error("Audio is already in use by a trial", code="trial_active")
            participant.update(armed=armed, arm_metadata=metadata)
            self.emit("armed", {"role": participant["role"], "armed": armed}, request.sid)
            if self.current and not armed:
                self._fail(self.current, "disarmed", "A participant disarmed audio")
        self.broadcast_status()

    def on_start(self, data=None):
        try:
            data = _object({} if data is None else data, limit=32 * 1024)
            experiment = _experiment(data.get("metadata"))
            profile = data.get("profile", "coded-probes")
            if not isinstance(profile, str) or profile not in PROFILES:
                raise ValueError("Unsupported ranging profile")
        except ValueError as exc:
            return self.error(str(exc))
        self.check_timeout()
        with self.lock:
            participant = self.participants.get(request.sid)
            if not participant or participant["role"] != "initiator":
                return self.error("Only the initiator can start a ranging trial", code="not_initiator")
            if self.current:
                return self.error("A ranging trial is already active", code="trial_active")
            if len(self.participants) != 2 or not all(p["armed"] for p in self.participants.values()):
                return self.error("Both participants must arm audio first", code="not_armed")
            trial_id = uuid.uuid4().hex
            directory = self.data_dir / trial_id
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                directory.mkdir()
                trial = RangingTrial(trial_id, directory, {}, experiment,
                                     {sid: dict(p) for sid, p in self.participants.items()})
                self.trials[trial_id] = trial
                self.current = trial
                trial.provenance = source_provenance(self.analyzer, {})
                # Preserve the original injected-builder contract and default for
                # archived clients. New clients request the reference explicitly.
                builder_options = {"session_id": trial_id}
                if profile != "coded-probes":
                    builder_options["profile"] = profile
                protocol = self.protocol_builder(**builder_options)
                if profile == "beepbeep-reference" and (protocol.get("version") != "beepbeep-v1"
                                                        or protocol.get("profile") != profile):
                    raise ValueError("Protocol builder did not return the requested reference profile")
                if not 0 < float(protocol["duration_s"]) <= MAX_RECORDING_SECONDS - 5:
                    raise ValueError("Protocol recording window exceeds the limit")
                trial.protocol = protocol
                trial.provenance = source_provenance(self.analyzer, protocol)
                write_json(directory / "trial.json", self.trial_record(trial))
                write_json(directory / "protocol.json", protocol)
                write_json(directory / "provenance.json", trial.provenance)
                self._deadline(trial, READY_TIMEOUT_SECONDS)
            except Exception as exc:
                if self.current and self.current.trial_id == trial_id:
                    if not (directory / "trial.json").exists():
                        write_json(directory / "trial.json", self.trial_record(self.current))
                    self._fail(self.current, "prepare_failed", str(exc))
                else:
                    self.error(f"Could not prepare trial: {exc}", code="prepare_failed")
                return
            for sid, member in trial.members.items():
                self.emit("prepare_trial", {"trial_id": trial_id, "protocol": protocol,
                                           "role": member["role"],
                                           "readiness_deadline_ms": int(time.time() * 1000 + READY_TIMEOUT_SECONDS * 1000)}, sid)
        self.broadcast_status()

    def _member_trial(self, data) -> tuple[RangingTrial, dict]:
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        trial_id = data.get("trial_id")
        if not isinstance(trial_id, str) or trial_id not in self.trials:
            raise ValueError("Unknown ranging trial")
        trial = self.trials[trial_id]
        member = trial.members.get(request.sid)
        if member is None:
            raise ValueError("This socket does not belong to the trial")
        for key in ("role", "participant_id"):
            if key in data and data[key] != member[key]:
                raise ValueError(f"The supplied {key} does not match this session")
        return trial, member

    def on_ready(self, data=None):
        self.check_timeout()
        with self.lock:
            try:
                data = _object(data, limit=MAX_METADATA_BYTES)
                trial, member = self._member_trial(data)
                metadata = _object(data.get("metadata", {}))
                if self.current is not trial or trial.state != "preparing":
                    raise ValueError("Trial is not waiting for readiness")
                _capture_identity(metadata, trial.protocol)
                role = member["role"]
                if role in trial.ready:
                    return
                write_json(trial.directory / f"ready_{RECEIVERS[role]}.json", metadata)
                trial.ready.add(role)
                if len(trial.ready) != 2:
                    return
                trial.state = "recording"
                self._deadline(trial, float(trial.protocol["duration_s"]) + START_DELAY_MS / 1000 + UPLOAD_GRACE_SECONDS)
                start = {"trial_id": trial.trial_id, "protocol": trial.protocol,
                         "start_after_ms": START_DELAY_MS,
                         "start_at_unix_ms": int(time.time() * 1000) + START_DELAY_MS,
                         "record_window_ms": round(trial.protocol["duration_s"] * 1000)}
                write_json(trial.directory / "start.json", start)
                self.emit("trial_start", start)
            except ValueError as exc:
                return self.error(str(exc))
        self.broadcast_status()

    def on_upload(self, data=None):
        self.check_timeout()
        process = None
        with self.lock:
            trial = None
            try:
                trial, member = self._member_trial(data)
                role = member["role"]
                if role in trial.uploads:
                    raise ValueError("This participant already uploaded; the first recording is retained")
                # Retain a peer's partial capture arriving after an abort. Never analyze it.
                late = trial.report is not None and trial.report.get("status") == "failed"
                if not late and (self.current is not trial or trial.state != "recording"):
                    raise ValueError("Trial is not accepting recordings")
                metadata = _object(data.get("metadata", {}))
                _capture_identity(metadata, trial.protocol)
                raw, actual = validate_wav(data.get("audio_base64"), metadata, float(trial.protocol["duration_s"]))
                tag = RECEIVERS[role]
                atomic_create(trial.directory / f"recording_{tag}.wav", raw)
                saved = {"participant_id": member["participant_id"], "role": role,
                         "receiver": tag, "received_at": _now_iso(), "late_after_failure": late,
                         "wav": actual, "metadata": metadata}
                write_json(trial.directory / f"upload_{tag}.json", saved)
                trial.uploads[role] = saved
                self.emit("upload_received", {"trial_id": trial.trial_id, "role": role,
                                              "count": len(trial.uploads), "late": late}, request.sid)
                if late:
                    payload = {"trial_id": trial.trial_id,
                               "recordings": self.artifacts(trial)["recordings"],
                               "manifest_url": f"/ranging/trials/{trial.trial_id}/manifest.json"}
                    for sid, original in trial.members.items():
                        connected = self.participants.get(sid)
                        if connected and connected["participant_id"] == original["participant_id"]:
                            self.emit("artifacts_updated", payload, sid)
                    return
                if metadata.get("partial") or metadata.get("capture_error") or metadata.get("recording_complete") is False:
                    self._fail(trial, "capture_failed", str(metadata.get("capture_error") or "Incomplete capture"))
                elif len(trial.uploads) == 2:
                    # Exactly one upload thread claims completion under the lock.
                    trial.state = "processing"
                    self._deadline(trial, ANALYSIS_TIMEOUT_SECONDS)
                    write_json(trial.directory / "processing.json", {"started_at": _now_iso()})
                    process = trial
            except (ValueError, OSError) as exc:
                if trial is not None and request.sid in trial.members:
                    self._attempt(trial, "upload_rejected", {"role": trial.members[request.sid]["role"], "message": str(exc)})
                return self.error(str(exc), code="upload_rejected", trial_id=trial.trial_id if trial else None)
        self.broadcast_status()
        if process is not None:
            self._process(process)

    def _process(self, trial: RangingTrial) -> None:
        try:
            recordings = {RECEIVERS[role]: {"wav_path": trial.directory / f"recording_{RECEIVERS[role]}.wav",
                                          "metadata": saved["metadata"]}
                          for role, saved in trial.uploads.items()}
            config = {}
            self_paths = [trial.experiment.get(f"self_speaker_mic_{tag}_cm") for tag in ("a", "b")]
            if all(value is not None for value in self_paths):
                config["self_path_m"] = dict(zip(("A", "B"), (value / 100 for value in self_paths)))
            report = self.analyzer(recordings=recordings, protocol=trial.protocol, config=config)
            report.setdefault("protocol_profile", trial.protocol.get("profile", "coded-probes"))
            # The LAN recorder never issues a calibrated body-gap decision.
            report["decision"] = {"label": "INCONCLUSIVE", "reasons": [
                "No physical calibration validates a device-body gap decision.",
                *(report.get("decision", {}).get("reasons") or []),
            ]}
            report["server_status"] = "analysis_complete"
            with self.lock:
                self._finish(trial, report)
        except Exception as exc:
            with self.lock:
                self._fail(trial, "analysis_failed", f"Analysis failed: {exc}")

    def on_abort(self, data=None):
        with self.lock:
            try:
                data = _object(data, limit=16 * 1024)
                trial, _ = self._member_trial(data)
                reason = _label(data.get("reason"), limit=1000) or "Aborted by participant"
                self._fail(trial, "aborted", reason)
            except ValueError as exc:
                self.error(str(exc))

    def on_disconnect(self, reason=None):
        with self.lock:
            participant = self.participants.pop(request.sid, None)
            if participant and self.current and request.sid in self.current.members:
                self._fail(self.current, "disconnected", "A participant disconnected")
        self.broadcast_status()

    def download(self, trial_id: str, filename: str):
        with self.lock:
            trial = self.trials.get(trial_id)
            if not re.fullmatch(r"[0-9a-f]{32}", trial_id):
                abort(404)
            directory = self.data_dir / trial_id
            if (directory.is_symlink() or not directory.is_dir()
                    or not (directory / "trial.json").is_file()
                    or (directory / "trial.json").is_symlink()):
                abort(404)
            if filename == "manifest.json":
                names = sorted(p.name for p in directory.iterdir()
                               if p.is_file() and not p.is_symlink() and not p.name.startswith("."))
                base = f"/ranging/trials/{trial_id}"
                links = {"protocol": f"{base}/protocol.json", "trial": f"{base}/trial.json",
                         "manifest": f"{base}/manifest.json", "provenance": f"{base}/provenance.json",
                         "recordings": {role: f"{base}/recording_{tag}.wav"
                                        for role, tag in RECEIVERS.items() if f"recording_{tag}.wav" in names},
                         "metadata": {role: f"{base}/upload_{tag}.json"
                                      for role, tag in RECEIVERS.items() if f"upload_{tag}.json" in names}}
                return jsonify({"trial_id": trial_id,
                                "state": trial.state if trial else "archived" if "report.json" in names else "interrupted",
                                "artifacts": links, "files": names})
            allowed = {"protocol.json", "trial.json", "provenance.json", "report.json", "start.json", "processing.json",
                       "recording_A.wav", "recording_B.wav", "upload_A.json", "upload_B.json",
                       "ready_A.json", "ready_B.json"}
            if filename not in allowed and not re.fullmatch(r"(?:attempt|reanalysis)_[0-9a-f]{32}\.json", filename):
                abort(404)
            path = directory / filename
            if not path.is_file() or path.is_symlink():
                abort(404)
        return send_file(path, as_attachment=True, download_name=f"{trial_id}_{filename}")


def register_ranging(app, socketio, data_dir=None, *, protocol_builder=None, analyzer=None,
                     clock=time.monotonic, watchdog=True) -> RangingService:
    """Register routes and events; dependency injection keeps lifecycle tests acoustic-free."""
    if protocol_builder is None:
        from ranging_protocol import build_protocol
        protocol_builder = build_protocol
    if analyzer is None:
        from ranging_analysis import analyze_ranging
        analyzer = analyze_ranging
    service = RangingService(app, socketio, data_dir or Path(__file__).parent / "data" / "ranging",
                             protocol_builder=protocol_builder, analyzer=analyzer, clock=clock,
                             watchdog=watchdog)
    app.extensions["ranging"] = service
    app.add_url_rule("/ranging", "ranging_index", lambda: render_template("ranging.html"))
    app.add_url_rule("/ranging/trials/<trial_id>/<filename>", "ranging_download", service.download)
    for name, handler in {"join": service.on_join, "arm": service.on_arm,
                          "start_trial": service.on_start, "ready": service.on_ready,
                          "upload": service.on_upload, "abort": service.on_abort,
                          "disconnect": service.on_disconnect}.items():
        socketio.on_event(name, handler, namespace=NAMESPACE)
    return service
