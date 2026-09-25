"""Structured JSONL logging for fuzzy commitment trials."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, asdict

LOGS_DIR = Path(__file__).parent / "logs"
TRIALS_FILE = LOGS_DIR / "trials.jsonl"


@dataclass
class TrialRecord:
    trial_id: str
    timestamp: str
    condition_label: Optional[str]

    device_a_id: str
    device_a_user_agent: Optional[str]
    device_b_id: str
    device_b_user_agent: Optional[str]

    scheduled_start_ms: int
    device_a_actual_start_ms: Optional[int]
    device_a_actual_stop_ms: Optional[int]
    device_a_upload_ms: Optional[int]
    device_b_actual_start_ms: Optional[int]
    device_b_actual_stop_ms: Optional[int]
    device_b_upload_ms: Optional[int]

    audio_duration_a_ms: Optional[int]
    audio_duration_b_ms: Optional[int]

    feature_params: dict
    bch_params: dict

    hamming_distance: Optional[int]
    disagreement_pct: Optional[float]
    bch_correction_threshold: int

    reproduce_success: bool
    key_match: bool
    corrected_errors: Optional[int]

    error_reason: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


def ensure_logs_dir():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def log_trial(record: TrialRecord):
    """Append a trial record to the JSONL log."""
    ensure_logs_dir()
    with open(TRIALS_FILE, 'a') as f:
        f.write(json.dumps(record.to_dict()) + '\n')


def log_trial_dict(data: dict):
    """Append a raw dict to the JSONL log."""
    ensure_logs_dir()
    with open(TRIALS_FILE, 'a') as f:
        f.write(json.dumps(data) + '\n')


def read_trials() -> list[dict]:
    """Read all trial records from the log."""
    if not TRIALS_FILE.exists():
        return []

    trials = []
    with open(TRIALS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                trials.append(json.loads(line))
    return trials


def summarize_trials(condition: Optional[str] = None) -> dict:
    """Summarize trial results, optionally filtered by condition label."""
    trials = read_trials()

    if condition:
        trials = [t for t in trials if t.get('condition_label') == condition]

    if not trials:
        return {'count': 0}

    successful = [t for t in trials if t.get('reproduce_success')]
    failed = [t for t in trials if not t.get('reproduce_success')]

    distances = [t['hamming_distance'] for t in trials if t.get('hamming_distance') is not None]

    return {
        'count': len(trials),
        'success_count': len(successful),
        'success_rate': len(successful) / len(trials) * 100,
        'fail_count': len(failed),
        'hamming_mean': sum(distances) / len(distances) if distances else None,
        'hamming_median': sorted(distances)[len(distances)//2] if distances else None,
        'hamming_min': min(distances) if distances else None,
        'hamming_max': max(distances) if distances else None,
        'bch_threshold': trials[0].get('bch_correction_threshold') if trials else None,
    }


def clear_logs():
    """Clear the trial log (use with caution)."""
    if TRIALS_FILE.exists():
        TRIALS_FILE.unlink()
