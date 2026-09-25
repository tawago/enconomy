"""Print a compact summary for a logged proximity-echo trial, or render a full
self-contained HTML diagnostic report (--plot, fix-plan C1)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _print_summary(record: dict) -> None:
    print(f"trial_id     : {record.get('trial_id')}")
    print(f"timestamp    : {record.get('timestamp')}")
    print(f"condition    : {record.get('condition_label')}")
    print(f"family       : {record.get('challenge_family')}")
    print(f"feature_ver  : {record.get('feature_version')}")
    if record.get("failure_reason"):
        print(f"FAILURE      : {record['failure_reason']}")
        return

    beep_spec = record.get("beep_spec") or {}
    print(f"beep         : {beep_spec.get('start_freq_hz')}–{beep_spec.get('end_freq_hz')}Hz, {beep_spec.get('duration_ms')}ms, amp={beep_spec.get('amplitude')}")

    schedule = record.get("schedule") or []
    print(f"schedule     : {len(schedule)} beeps over {record.get('record_window_ms')}ms")

    pair = record.get("pair") or {}
    if pair:
        print(f"capture_valid: {pair.get('capture_valid')} ({pair.get('validity_version')})")
        failures = pair.get("failure_reasons") or []
        if failures:
            print(f"invalid_why  : {', '.join(failures)}")
        warnings = pair.get("warnings") or []
        if warnings:
            print(f"warnings     : {', '.join(warnings)}")

    score = record.get("score") or {}
    if score:
        print(f"c_a / c_b    : {score.get('c_a')} / {score.get('c_b')}")
        print(f"score / thr  : {score.get('score')} / {score.get('threshold')}")
        verdict = score.get("verdict")
        if verdict is None:
            verdict_text = "WITHHELD"
        else:
            verdict_text = "ACCEPT" if verdict else "REJECT"
        print(f"verdict      : {verdict_text} ({score.get('classifier_version')})")

    for label in ("device_a", "device_b"):
        device = record.get(label) or {}
        per_beep = device.get("per_beep_summary") or []
        ok_count = sum(1 for entry in per_beep if entry.get("selection_ok"))
        print(f"{label:<12}: id={device.get('id')} role={device.get('role')} period_ok={ok_count}/{len(per_beep)}")

    channels = pair.get("channels") or {}
    for name in ("AA", "AB", "BA", "BB"):
        channel = channels.get(name)
        if not channel:
            continue
        print(
            f"channel {name:<3}: ok={channel.get('ok_beeps')}/{channel.get('total_beeps')} "
            f"ratio={channel.get('ok_ratio'):.2f} median_chirp={channel.get('median_chirp_peak'):.4f}"
        )

    metadata = record.get("device_a", {}).get("metadata") or {}
    granted = metadata.get("granted_track_settings") or {}
    if granted:
        print(f"device_a DSP : echoCancellation={granted.get('echoCancellation')} noiseSuppression={granted.get('noiseSuppression')} autoGainControl={granted.get('autoGainControl')}")
    metadata = record.get("device_b", {}).get("metadata") or {}
    granted = metadata.get("granted_track_settings") or {}
    if granted:
        print(f"device_b DSP : echoCancellation={granted.get('echoCancellation')} noiseSuppression={granted.get('noiseSuppression')} autoGainControl={granted.get('autoGainControl')}")


DEFAULT_TRIALS = Path(__file__).parent.parent / "data" / "logs" / "trials.jsonl"
DEFAULT_AUDIO = Path(__file__).parent.parent / "data" / "audio"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_id")
    parser.add_argument("trials_path", nargs="?", type=Path, default=DEFAULT_TRIALS,
                        help="trial log (default: data/logs/trials.jsonl)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--raw", action="store_true", help="print the raw JSON record")
    mode.add_argument("--plot", action="store_true",
                      help="render a self-contained HTML diagnostic report (C1)")
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO,
                        help="WAV directory for --plot re-derivation (default: data/audio)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="output directory for --plot (default: data/reports)")
    args = parser.parse_args()

    if not args.trials_path.exists():
        print(f"missing log file: {args.trials_path}")
        return 1

    if args.plot:
        # Imported lazily: --plot pulls in matplotlib + the whole pipeline, which a plain
        # summary/--raw call has no reason to load.
        from plot_trial import build_report  # noqa: E402
        try:
            out_path = build_report(args.trial_id, args.trials_path, args.audio_dir, args.out_dir)
        except KeyError:
            print(f"trial not found: {args.trial_id}")
            return 1
        print(f"wrote {out_path}")
        return 0

    for line in args.trials_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("trial_id") == args.trial_id:
            if args.raw:
                print(json.dumps(record, indent=2))
            else:
                _print_summary(record)
            return 0

    print(f"trial not found: {args.trial_id}")
    return 1


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
