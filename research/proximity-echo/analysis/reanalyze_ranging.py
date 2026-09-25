"""Reanalyze a saved ranging trial into a new report; never replace capture artifacts.

Usage: .venv/bin/python analysis/reanalyze_ranging.py data/ranging/TRIAL_ID
The original report, protocol, metadata, and WAV files remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ranging_analysis import DEFAULTS, analyze_ranging
from ranging_server import source_provenance, write_json
from ranging_timeline import TIMELINE_DEFAULTS, TIMELINE_POLICIES
from beepbeep_analysis import LATE_TAIL_POLICIES
from analysis.inspect_ranging_channels import inspect_trial

# Every config key an analyzer validates, restated here so that a misspelled
# --set is refused at the command line instead of being silently discarded.
ALLOWED_OVERRIDES = dict.fromkeys(
    list(DEFAULTS) + ["self_path_m"] + list(TIMELINE_DEFAULTS)
    + ["late_tail_policy", "shadow_window_ms"])


def _check_overrides(overrides: dict) -> None:
    """Reject unknown or invalid --set keys before any analysis runs."""
    unknown = [key for key in overrides if key not in ALLOWED_OVERRIDES]
    if unknown:
        raise ValueError(
            f"Unknown config key(s): {', '.join(sorted(unknown))}. "
            f"Allowed keys: {', '.join(sorted(ALLOWED_OVERRIDES))}")
    if "late_tail_policy" in overrides and overrides["late_tail_policy"] not in LATE_TAIL_POLICIES:
        raise ValueError(f"late_tail_policy must be one of {list(LATE_TAIL_POLICIES)}")
    if "timeline_policy" in overrides and overrides["timeline_policy"] not in TIMELINE_POLICIES:
        raise ValueError(f"timeline_policy must be one of {list(TIMELINE_POLICIES)}")


def response_diagnostic(directory: Path, report: dict) -> dict:
    """Supplement the report without providing arrivals or accepting a distance."""
    diagnostic = {
        "version": "whole-response-clock-v1", "status": "unavailable",
        "physical_timing_validated": False,
        "interpretation": "Whole-response alignment estimates relative clock trends and response consistency, not physical first arrivals or distance.",
        "reasons": [],
    }
    if report.get("protocol_version") == "beepbeep-v1":
        diagnostic["reasons"].append("Whole-response inspection applies only to the original coded-probe profile")
        return diagnostic
    for tag in ("A", "B"):
        recording = report.get("recordings", {}).get(tag, {})
        if recording.get("usable") is not True:
            diagnostic["reasons"].append(f"Device {tag}: recording quality or continuity checks failed")
    if diagnostic["reasons"]:
        return diagnostic
    try:
        result = inspect_trial(directory)
        # Refuse nonfinite exploratory output before creating a derived report.
        json.dumps(result, allow_nan=False)
        supplemental = {key: result[key] for key in ("channels", "clock_by_band", "input_sha256")}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        diagnostic["reasons"].append(str(exc))
        return diagnostic
    diagnostic.update({"status": "exploratory", **supplemental})
    diagnostic["reasons"] = list(report.get("quality_warnings", []))
    return diagnostic


def reanalyze(directory: Path, *, include_responses: bool = False,
              overrides: dict | None = None, output_dir: Path | None = None) -> Path:
    directory = directory.resolve()
    trial = json.loads((directory / "trial.json").read_text())
    protocol = json.loads((directory / "protocol.json").read_text())
    recordings = {
        tag: {"wav_path": directory / f"recording_{tag}.wav",
              "metadata": json.loads((directory / f"upload_{tag}.json").read_text())["metadata"]}
        for tag in ("A", "B")
    }
    experiment = trial.get("experiment", {})
    paths = [experiment.get(f"self_speaker_mic_{tag}_cm") for tag in ("a", "b")]
    config = {}
    if all(value is not None for value in paths):
        config["self_path_m"] = dict(zip(("A", "B"), (value / 100 for value in paths)))
    # Explicit operator overrides. The analyzers validate the values; the key
    # names are checked here as well, because a config key they do not know is
    # otherwise ignored without a word.
    _check_overrides(overrides or {})
    config.update(overrides or {})
    report = analyze_ranging(recordings=recordings, protocol=protocol, config=config)
    report.update({"trial_id": trial["trial_id"], "experiment": experiment,
                   "capture_provenance": trial.get("provenance"),
                   "reanalysis_provenance": source_provenance(analyze_ranging, protocol),
                   "original_report": "report.json", "reanalysis": True})
    if include_responses:
        report["response_diagnostic"] = response_diagnostic(directory, report)
        base = Path(__file__).resolve().parents[1]
        for name in ("analysis/reanalyze_ranging.py", "analysis/inspect_ranging_channels.py"):
            content = (base / name).read_bytes()
            report["reanalysis_provenance"]["sources"][name] = {
                "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    if overrides:
        report["reanalysis_config_overrides"] = overrides
    destination = Path(output_dir).resolve() if output_dir is not None else directory
    destination.mkdir(parents=True, exist_ok=True)
    prefix = f"{trial['trial_id']}_" if destination != directory else ""
    output = destination / f"{prefix}reanalysis_{uuid.uuid4().hex}.json"
    write_json(output, report)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_directory", type=Path, help="Saved data/ranging/<trial_id> directory")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=JSON", dest="overrides",
                        help=("Override one analyzer config key; the value is parsed as JSON (repeatable). "
                              "The key must be one of: " + ", ".join(sorted(ALLOWED_OVERRIDES)) + ". "
                              "Unknown keys and invalid values are rejected before analysis."))
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Write the derived report here instead of inside the capture directory; capture artifacts are never modified either way")
    parser.add_argument("--include-responses", action="store_true",
                        help="Add exploratory whole-response clock and consistency diagnostics without changing the arrival or distance decision")
    args = parser.parse_args()
    overrides = {}
    for item in args.overrides:
        key, separator, raw = item.partition("=")
        if not separator or not key.strip():
            parser.error(f"--set expects KEY=JSON, received {item!r}")
        try:
            overrides[key.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            # Bare words stay usable for string-valued settings such as a policy name.
            overrides[key.strip()] = raw
    try:
        output = reanalyze(args.trial_directory, include_responses=args.include_responses,
                           overrides=overrides, output_dir=args.output_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"Cannot reanalyze this trial: {exc}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
