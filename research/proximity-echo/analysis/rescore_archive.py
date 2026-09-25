"""Re-score archived trial pairs (WAVs + trials.jsonl metadata) through the CURRENT
pipeline, offline (fix-plan A1.6).

For each logged trial with both WAVs on disk, this re-runs joint alignment, period
selection, compensation, scoring, and validity, then prints old (logged) vs new values:
chosen cross offset per device, train assignment, self latencies, alias-overlap counts,
verdict + failure reasons, and score.

Scope: every band. Since fix-plan D3.5 the pipeline is band-parametric (bandpass, spectrum
band, and timing gates all derive from each trial's beep_spec), so 6-12 kHz and 14-15 kHz
trials both score through the same path — there is no 14-15 kHz skip. All 24 archive trials
are scorable, including the three 14-15 kHz captures c175938d, 361d4526, and fadae387.

usage: python analysis/rescore_archive.py [trial_id ...] [--log PATH] [--audio-dir PATH]
       python analysis/rescore_archive.py --json [trial_id ...]   # machine-readable

With --json the script emits a single JSON array (one object per trial, in log order)
of the structural facts each trial produced this run: per-device chosen cross offset +
source, assigned self/partner trains, self latency, alias-overlap counts, sweep offset +
status, alignment warnings; plus the joint-assignment status/round-trip, sum residual,
validity verdict/failure-reasons/warnings, and the final score. This output supports
manual comparison of saved experiments; it does not run regression assertions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alignment import canonicalize_audio  # noqa: E402
from challenge_generator import BeepSpec  # noqa: E402
from clipping import apply_clipping_exclusion, detect_clipping  # noqa: E402
from compensation import compute_compensated_signatures  # noqa: E402
from feature_extraction import (  # noqa: E402
    extract_pair_recording_spectra,
    platform_hint_from_user_agent,
)
from scoring import DEFAULT_VERDICT_THRESHOLD, cross_self_similarity, score_proximity  # noqa: E402
from server import _client_timing_meta, build_device_summary  # noqa: E402  (offline-safe: module import only)
from validity import assess_capture_validity  # noqa: E402


def _fmt(value, digits: int = 1) -> str:
    if value is None:
        return "None"
    return f"{value:.{digits}f}"


def _fmt_train(train: dict | None) -> str:
    if not train:
        return "none"
    return (
        f"lag {train['mapped_lag_ms']:+.1f} ms (σ {train['sigma_ms']:.2f} ms, "
        f"drift {train['drift_us_per_beep']:+.1f} µs/beep, "
        f"amp {train['median_amplitude']:.1f}, {train['support']}/{train['n_slots']} beeps)"
    )


def _old_verdict_text(record: dict) -> str:
    score = record.get("score") or {}
    if not score:
        return "n/a"
    capture_valid = score.get("capture_valid")
    verdict = score.get("verdict")
    if capture_valid is False or verdict is None:
        raw = score.get("raw_verdict")
        raw_text = "ACCEPT" if raw else "REJECT" if raw is not None else "?"
        return f"WITHHELD (raw {raw_text})"
    return "ACCEPT" if verdict else "REJECT"


def _compute_trial(record: dict, audio_dir: Path) -> dict:
    """Re-score one trial and return a structured result dict. The `status` key is
    "scored" | "skipped" | "logged_failed"; skipped/failed entries carry a `reason`
    and no measurements. This is the single source of truth for both the text renderer
    and the --json emitter, so the two can never disagree."""
    trial_id = record["trial_id"]
    condition = record.get("condition_label")
    base = {"trial_id": trial_id, "condition": condition}

    if record.get("failure_reason"):
        return {**base, "status": "logged_failed", "reason": record["failure_reason"]}

    beep_spec_dict = record.get("beep_spec") or {}
    # D3.5: the pipeline is now band-parametric (bandpass, spectrum band, and timing gates all
    # derive from beep_spec), so every band scores through the same path — no 14-15 kHz skip.
    old_a = record.get("device_a") or {}
    old_b = record.get("device_b") or {}
    wav_a = audio_dir / f"{trial_id}_{old_a.get('id')}.wav"
    wav_b = audio_dir / f"{trial_id}_{old_b.get('id')}.wav"
    if not wav_a.exists() or not wav_b.exists():
        return {
            **base,
            "status": "skipped",
            "reason": f"missing WAV(s) ({wav_a.name}, {wav_b.name})",
        }

    beep_spec = BeepSpec(**beep_spec_dict)
    schedule = record["schedule"]
    bytes_a = wav_a.read_bytes()
    bytes_b = wav_b.read_bytes()

    audio_a, _, _ = canonicalize_audio(bytes_a, beep_spec.sample_rate)
    audio_b, _, _ = canonicalize_audio(bytes_b, beep_spec.sample_rate)
    clipping_a = detect_clipping(audio_a)
    clipping_b = detect_clipping(audio_b)

    # A3 timing prior: thread the client timing metadata through exactly as server.py does, so
    # an A3-era archive re-scores under the SAME prior_bounded alignment it ran live instead of
    # a full masked_full_sweep. None for pre-A3 records (all 24 current archives), so today's
    # re-score — and the goldens pinned from it — are byte-identical.
    spectra_a, spectra_b = extract_pair_recording_spectra(
        bytes_a,
        bytes_b,
        schedule,
        beep_spec,
        platform_hint_a=platform_hint_from_user_agent(old_a.get("user_agent")),
        platform_hint_b=platform_hint_from_user_agent(old_b.get("user_agent")),
        timing_meta_a=_client_timing_meta(old_a.get("metadata") or {}),
        timing_meta_b=_client_timing_meta(old_b.get("metadata") or {}),
    )
    exclusion_a = apply_clipping_exclusion(audio_a, spectra_a)
    exclusion_b = apply_clipping_exclusion(audio_b, spectra_b)
    summary_a = build_device_summary("initiator", spectra_a, clipping_a, old_a.get("metadata") or {}, exclusion_a)
    summary_b = build_device_summary("observer", spectra_b, clipping_b, old_b.get("metadata") or {}, exclusion_b)

    signatures = compute_compensated_signatures(
        spectra_a["per_beep"], spectra_b["per_beep"],
        low_hz=beep_spec.start_freq_hz, high_hz=beep_spec.end_freq_hz,
    )
    score = score_proximity(signatures.to_dict(), verdict_threshold=DEFAULT_VERDICT_THRESHOLD)
    validity = assess_capture_validity(
        summary_a,
        summary_b,
        signature_freq_points=len(signatures.freqs_hz),
        raw_score=score.score,
        raw_verdict=score.verdict,
        cross_self_similarity=cross_self_similarity(signatures.to_dict()),
        compensation_dropped_beeps=signatures.n_grid_mismatch_dropped,
    )

    assignment = spectra_a.get("train_assignment") or {}
    # Trial-level alignment mode (A3.3), derived exactly as server.py::process_trial does for
    # the log / golden pins: prior_bounded iff at least one device's sweep was prior-bounded
    # this trial. Offline archive re-scores pass no timing metadata, so both devices fall back
    # to masked_full_sweep — pinning it here freezes that dual-mode default for the archive.
    alignment_mode = (
        "prior_bounded"
        if "prior_bounded" in (spectra_a.get("alignment_mode"), spectra_b.get("alignment_mode"))
        else "masked_full_sweep"
    )
    devices = {}
    for label, old_dev, spectra, role in (
        ("device_a", old_a, spectra_a, "initiator"),
        ("device_b", old_b, spectra_b, "observer"),
    ):
        sweep = spectra.get("sweep") or {}
        devices[label] = {
            "id": old_dev.get("id"),
            "role": role,
            "cross_offset_ms": spectra.get("cross_offset_ms"),
            "cross_offset_source": spectra.get("cross_offset_source"),
            "cross_status": spectra.get("cross_status"),
            "cross_offset_score": spectra.get("cross_offset_score"),
            "self_offset_ms": spectra.get("self_offset_ms"),
            "self_locked": spectra.get("self_locked"),
            "self_train": spectra.get("self_train"),
            "partner_train": spectra.get("partner_train"),
            "sweep": {"offset_ms": sweep.get("offset_ms"), "status": sweep.get("status")},
            "alias_overlaps": validity.alias_overlaps.get(label),
            "alignment_warnings": spectra.get("alignment_warnings") or [],
            "alignment_mode": spectra.get("alignment_mode"),
            "cross_offset_prior": spectra.get("cross_offset_prior"),
            "old_cross_offset_ms": old_dev.get("cross_offset_ms"),
        }

    new_verdict = (
        "WITHHELD" if not validity.capture_valid else ("ACCEPT" if score.verdict else "REJECT")
    )
    return {
        **base,
        "status": "scored",
        "feature_version": spectra_a.get("feature_version"),
        "alignment_mode": alignment_mode,
        "assignment": {
            "status": assignment.get("status"),
            "round_trip_ms": assignment.get("round_trip_ms"),
        },
        "sum_residual_ms": validity.sum_residual_ms,
        "capture_valid": validity.capture_valid,
        "channels": validity.channels,
        "verdict": new_verdict,
        "failure_reasons": list(validity.failure_reasons),
        "warnings": list(validity.warnings),
        "score": {
            "score": score.score,
            "c_a": score.c_a,
            "c_b": score.c_b,
            "raw_verdict": score.verdict,
            "threshold": score.threshold,
        },
        "old_score": (record.get("score") or {}).get("score"),
        "old_verdict": _old_verdict_text(record),
        "devices": devices,
    }


def _render_text(data: dict) -> None:
    trial_id = data["trial_id"]
    header = f"=== {trial_id} (condition={data.get('condition')}) ==="
    status = data["status"]
    if status == "logged_failed":
        print(f"{header}\n  SKIPPED: logged as failed ({data['reason']})")
        return
    if status == "skipped":
        print(f"{header}\n  SKIPPED: {data['reason']}")
        return

    print(header)
    for label in ("device_a", "device_b"):
        dev = data["devices"][label]
        print(f"  {label} ({dev.get('id')}, {dev.get('role')}):")
        print(
            f"    Δ old {_fmt(dev.get('old_cross_offset_ms'))} → new {_fmt(dev.get('cross_offset_ms'))} ms"
            f" [{dev.get('cross_offset_source') or dev.get('cross_status')}]"
        )
        print(f"    self train    : {_fmt_train(dev.get('self_train'))}"
              + ("" if dev.get("self_locked") else "  (NOT locked)"))
        print(f"    partner train : {_fmt_train(dev.get('partner_train'))}")
        print(
            f"    self latency {_fmt(dev.get('self_offset_ms'))} ms | cross status {dev.get('cross_status')}"
            f" | sweep {_fmt((dev.get('sweep') or {}).get('offset_ms'))} ms ({(dev.get('sweep') or {}).get('status')})"
        )
        print(f"    alias overlaps: {dev.get('alias_overlaps')}")
        warnings = dev.get("alignment_warnings") or []
        if warnings:
            print(f"    align warnings: {', '.join(warnings)}")
    assignment = data["assignment"]
    print(
        f"  assignment: {assignment.get('status')}"
        f" | round trip {_fmt(assignment.get('round_trip_ms'), 2)} ms"
        f" | sum residual {_fmt(data.get('sum_residual_ms'), 2)} ms"
    )
    for name, channel in data.get("channels", {}).items():
        print(f"  channel {name}: {channel['ok_beeps']}/{channel['total_beeps']} usable echo periods")
    score = data["score"]
    print(
        f"  score: old {_fmt(data.get('old_score'), 3)} ({data.get('old_verdict')})"
        f" → new {score['score']:.3f} c_a={score['c_a']:.3f} c_b={score['c_b']:.3f} ({data['verdict']})"
    )
    if data["failure_reasons"]:
        print(f"  failure reasons: {', '.join(data['failure_reasons'])}")
    if data["warnings"]:
        print(f"  warnings: {', '.join(data['warnings'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trial_ids", nargs="*", help="trial ids to re-score (default: every logged trial)")
    parser.add_argument("--log", type=Path, default=ROOT / "data" / "logs" / "trials.jsonl")
    parser.add_argument("--audio-dir", type=Path, default=ROOT / "data" / "audio")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON array of per-trial structural facts (no text report)",
    )
    args = parser.parse_args()

    if not args.log.exists():
        print(f"missing log file: {args.log}")
        return 1

    wanted = set(args.trial_ids)
    seen = set()
    results: list[dict] = []
    for line in args.log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        trial_id = record.get("trial_id")
        if wanted and trial_id not in wanted:
            continue
        seen.add(trial_id)
        try:
            data = _compute_trial(record, args.audio_dir)
        except Exception as exc:  # keep going: one bad trial must not kill the survey
            data = {"trial_id": trial_id, "status": "error", "reason": repr(exc)}
        if args.json:
            results.append(data)
        elif data.get("status") == "error":
            print(f"=== {trial_id} ===\n  ERROR: {data['reason']}\n")
        else:
            _render_text(data)
            print()

    for trial_id in sorted(wanted - seen):
        entry = {"trial_id": trial_id, "status": "not_found", "reason": f"not found in {args.log}"}
        if args.json:
            results.append(entry)
        else:
            print(f"=== {trial_id} ===\n  SKIPPED: not found in {args.log}\n")

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
