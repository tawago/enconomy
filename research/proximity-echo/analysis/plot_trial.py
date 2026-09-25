"""Per-trial diagnostic report generator (fix-plan C1).

Produces one self-contained HTML report per trial. The report re-derives every artifact
from the archived WAVs through the CURRENT pipeline (exactly as analysis/rescore_archive
does), so a failed trial is diagnosable from the report alone without touching raw audio:

  * per device: the matched-filter envelope with the self schedule grid, self-structure
    mask intervals, detected/assigned trains, and the per-beep self/cross selections
    overlaid (so a self-alias shows as cross selections sitting on the self mask);
  * per device: the offset sweep score curve (masked + raw diagnostic) with the chosen Δ,
    the A3 prior window when present, and the self-grid danger offsets marked;
  * per direction: the averaged echo signatures AA/AB/BA/BB before and after compensation,
    with the A2.3 cross-self-similarity values and the D3.6 dropped-beep count;
  * the validity verdict with ALL reasons/warnings, alignment_mode, and the guard
    measurements (grid-coherence lag, sum residual, alias overlaps).

Everything is embedded (PNGs as data: URIs), so the HTML opens anywhere offline. When the
WAVs are absent the report degrades to the logged records (validity + per-beep summary),
with a banner noting the figures could not be recomputed.

This module is driven by analysis/inspect_trial.py --plot; it is not a CLI on its own.
"""

from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")  # headless: no display needed, PNGs are embedded
import matplotlib.pyplot as plt  # noqa: E402

from alignment import canonicalize_audio  # noqa: E402
from challenge_generator import BeepSpec  # noqa: E402
from clipping import apply_clipping_exclusion, detect_clipping  # noqa: E402
from compensation import compute_compensated_signatures  # noqa: E402
from feature_extraction import (  # noqa: E402
    _prepare_recording,
    _score_offset,
    extract_pair_recording_spectra,
    platform_hint_from_user_agent,
)
from pipeline_constants import (  # noqa: E402
    SWEEP_MIN_UNMASKED_PREDICTIONS,
    SWEEP_PREDICTION_TOL_MS,
    SWEEP_SEARCH_HALF_RANGE_MS,
    SWEEP_STEP_MS,
)
from scoring import DEFAULT_VERDICT_THRESHOLD, cross_self_similarity, score_proximity  # noqa: E402
from server import _client_timing_meta, build_device_summary  # noqa: E402  (import only: offline-safe)
from validity import assess_capture_validity  # noqa: E402

DEFAULT_TRIALS = ROOT / "data" / "logs" / "trials.jsonl"
DEFAULT_AUDIO = ROOT / "data" / "audio"


# ---------------------------------------------------------------------------
# Record loading + full re-derivation from WAVs
# ---------------------------------------------------------------------------

def load_record(trial_id: str, trials_path: Path) -> dict | None:
    for line in trials_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("trial_id") == trial_id:
            return record
    return None


def _mask_from_intervals(intervals_ms: list, n_samples: int, rate: float) -> np.ndarray:
    """Rebuild the boolean self-structure mask from the logged interval list, using the
    exact sample-index convention feature_extraction._build_self_mask writes."""
    mask = np.zeros(n_samples, dtype=bool)
    for pair in intervals_ms or []:
        lo_ms, hi_ms = float(pair[0]), float(pair[1])
        lo = max(0, int(lo_ms * rate / 1000.0))
        hi = min(n_samples, int(hi_ms * rate / 1000.0) + 1)
        if hi > lo:
            mask[lo:hi] = True
    return mask


def _sweep_curves(envelope: np.ndarray, rate: float, schedule: list, role: str,
                  mask: np.ndarray, prior: dict | None) -> dict:
    """Reproduce the masked and raw (unmasked) offset-sweep score curves the pipeline
    scored over. The pipeline discards these; we recompute them with the same primitive
    (_score_offset) and the same grid so the plotted curve matches what the sweep saw."""
    cross_sched_ms = [float(e["offset_ms"]) for e in schedule if e["emitter_role"] != role]
    tol_samples = int(SWEEP_PREDICTION_TOL_MS / 1000.0 * rate)
    if prior is not None:
        search_min = float(prior["search_min_ms"])
        search_max = float(prior["search_max_ms"])
    else:
        search_min = -SWEEP_SEARCH_HALF_RANGE_MS
        search_max = SWEEP_SEARCH_HALF_RANGE_MS
    n_offsets = int((search_max - search_min) / SWEEP_STEP_MS) + 1
    offsets = np.linspace(search_min, search_max, n_offsets)
    masked = np.zeros(n_offsets)
    raw = np.zeros(n_offsets)
    counts = np.zeros(n_offsets, dtype=int)
    for i, off in enumerate(offsets):
        m_score, m_count = _score_offset(envelope, mask, rate, cross_sched_ms, float(off), tol_samples)
        r_score, _ = _score_offset(envelope, None, rate, cross_sched_ms, float(off), tol_samples)
        masked[i] = m_score
        raw[i] = r_score
        counts[i] = m_count
    return {"offsets_ms": offsets, "masked": masked, "raw": raw, "counts": counts}


def recompute(record: dict, audio_dir: Path) -> dict:
    """Re-run the full pipeline on the trial's WAVs and gather every artifact the report
    needs. Returns {"ok": True, ...} on success or {"ok": False, "reason": ...} when the
    WAVs are missing (the caller then renders the logged-only degraded report)."""
    trial_id = record["trial_id"]
    beep_spec_dict = record.get("beep_spec") or {}
    if not beep_spec_dict:
        return {"ok": False, "reason": "record has no beep_spec (pre-repro failure record)"}
    old_a = record.get("device_a") or {}
    old_b = record.get("device_b") or {}
    wav_a = audio_dir / f"{trial_id}_{old_a.get('id')}.wav"
    wav_b = audio_dir / f"{trial_id}_{old_b.get('id')}.wav"
    if not wav_a.exists() or not wav_b.exists():
        return {"ok": False, "reason": f"missing WAV(s): {wav_a.name}, {wav_b.name}"}

    beep_spec = BeepSpec(**beep_spec_dict)
    schedule = record["schedule"]
    bytes_a = wav_a.read_bytes()
    bytes_b = wav_b.read_bytes()

    audio_a, _, _ = canonicalize_audio(bytes_a, beep_spec.sample_rate)
    audio_b, _, _ = canonicalize_audio(bytes_b, beep_spec.sample_rate)
    clipping_a = detect_clipping(audio_a)
    clipping_b = detect_clipping(audio_b)

    # A3 timing prior: thread the client timing metadata through exactly as server.py does, so
    # the report reproduces prior_bounded alignment (green prior window in the sweep figure,
    # alignment_mode row) rather than silently re-deriving a full masked_full_sweep that would
    # contradict — and misrepresent — a failed prior_bounded trial. None for pre-A3 records
    # (all 24 current archives), so today's reports are byte-identical.
    timing_meta_a = _client_timing_meta(old_a.get("metadata") or {})
    timing_meta_b = _client_timing_meta(old_b.get("metadata") or {})
    spectra_a, spectra_b = extract_pair_recording_spectra(
        bytes_a, bytes_b, schedule, beep_spec,
        platform_hint_a=platform_hint_from_user_agent(old_a.get("user_agent")),
        platform_hint_b=platform_hint_from_user_agent(old_b.get("user_agent")),
        timing_meta_a=timing_meta_a,
        timing_meta_b=timing_meta_b,
    )
    exclusion_a = apply_clipping_exclusion(audio_a, spectra_a)
    exclusion_b = apply_clipping_exclusion(audio_b, spectra_b)
    summary_a = build_device_summary("initiator", spectra_a, clipping_a, old_a.get("metadata") or {}, exclusion_a)
    summary_b = build_device_summary("observer", spectra_b, clipping_b, old_b.get("metadata") or {}, exclusion_b)

    signatures = compute_compensated_signatures(
        spectra_a["per_beep"], spectra_b["per_beep"],
        low_hz=beep_spec.start_freq_hz, high_hz=beep_spec.end_freq_hz,
    )
    similarity = cross_self_similarity(signatures.to_dict())
    score = score_proximity(signatures.to_dict(), verdict_threshold=DEFAULT_VERDICT_THRESHOLD)
    validity = assess_capture_validity(
        summary_a, summary_b,
        signature_freq_points=len(signatures.freqs_hz),
        raw_score=score.score, raw_verdict=score.verdict,
        cross_self_similarity=similarity,
        compensation_dropped_beeps=signatures.n_grid_mismatch_dropped,
    )

    # Envelopes (discarded by the pipeline) — recomputed deterministically for the plots.
    prep_a = _prepare_recording(bytes_a, schedule, beep_spec, "initiator")
    prep_b = _prepare_recording(bytes_b, schedule, beep_spec, "observer")

    devices = {}
    for label, role, spectra, prep, old in (
        ("device_a", "initiator", spectra_a, prep_a, old_a),
        ("device_b", "observer", spectra_b, prep_b, old_b),
    ):
        rate = prep["canonical_rate"]
        env = prep["envelope"]
        mask = _mask_from_intervals(spectra.get("self_mask_intervals_ms"), env.size, rate)
        sweep_curves = _sweep_curves(env, rate, schedule, role, mask, spectra.get("cross_offset_prior"))
        devices[label] = {
            "id": old.get("id"),
            "role": role,
            "rate": rate,
            "envelope": env,
            "mask_intervals_ms": spectra.get("self_mask_intervals_ms") or [],
            "self_positions_ms": spectra.get("self_structure_positions_ms") or [],
            "self_sched_ms": prep["self_sched_ms"],
            "self_train": spectra.get("self_train"),
            "partner_train": spectra.get("partner_train"),
            "detected_trains": spectra.get("detected_trains") or [],
            "cross_offset_ms": spectra.get("cross_offset_ms"),
            "cross_offset_source": spectra.get("cross_offset_source"),
            "cross_offset_score": spectra.get("cross_offset_score"),
            "cross_status": spectra.get("cross_status"),
            "self_offset_ms": spectra.get("self_offset_ms"),
            "self_locked": spectra.get("self_locked"),
            "sweep": spectra.get("sweep") or {},
            "sweep_curves": sweep_curves,
            "cross_offset_prior": spectra.get("cross_offset_prior"),
            "alignment_mode": spectra.get("alignment_mode"),
            "alignment_warnings": spectra.get("alignment_warnings") or [],
            "per_beep": spectra.get("per_beep") or [],
        }

    assignment = spectra_a.get("train_assignment") or {}
    return {
        "ok": True,
        "beep_spec": beep_spec_dict,
        "devices": devices,
        "signatures": signatures,
        "similarity": similarity,
        "score": score,
        "validity": validity,
        "assignment": assignment,
    }


# ---------------------------------------------------------------------------
# Figures -> embedded PNGs
# ---------------------------------------------------------------------------

def _fig_to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def _downsample_env(env: np.ndarray, n_out: int = 6000):
    """Max-pool the envelope for plotting so sharp matched-filter peaks survive
    decimation (a naive stride would drop them)."""
    if env.size <= n_out:
        return np.arange(env.size), env
    step = env.size // n_out
    trimmed = env[: step * n_out].reshape(n_out, step)
    return np.arange(n_out) * step, trimmed.max(axis=1)


def _env_at(env: np.ndarray, sample: float) -> float:
    idx = int(sample)
    if idx < 0 or idx >= env.size:
        return 0.0
    return float(env[idx])


def _fig_envelope(dev: dict) -> str:
    rate = dev["rate"]
    env = dev["envelope"]
    to_ms = 1000.0 / rate
    fig, ax = plt.subplots(figsize=(11, 3.2))

    idx, env_ds = _downsample_env(env)
    ax.plot(idx * to_ms, env_ds, color="#3b6ea5", lw=0.7, label="matched-filter envelope")

    # Self-structure mask spans (never masks the partner).
    for i, pair in enumerate(dev["mask_intervals_ms"]):
        ax.axvspan(float(pair[0]), float(pair[1]), color="#d94f4f", alpha=0.14,
                   label="self-structure mask" if i == 0 else None)

    # Self schedule grid.
    for i, s in enumerate(dev["self_sched_ms"]):
        ax.axvline(float(s), color="#999999", ls=":", lw=0.5,
                   label="self schedule grid" if i == 0 else None)

    ymax = float(env_ds.max()) if env_ds.size else 1.0

    # Self-structure positions (τ per slot).
    pos = dev["self_positions_ms"]
    if pos:
        ax.scatter(pos, [_env_at(env, p * rate / 1000.0) for p in pos],
                   marker="v", s=26, color="#8b0000", zorder=5, label="self-structure τ")

    # Per-beep selections: self vs cross chirp starts.
    role = dev["role"]
    self_ms, self_y, cross_ms, cross_y = [], [], [], []
    for entry in dev["per_beep"]:
        sel = entry.get("selection") or {}
        if not sel.get("selection_ok"):
            continue
        start = sel.get("chirp_start")
        if start is None:
            continue
        t_ms = float(start) * to_ms
        y = _env_at(env, float(start))
        if entry.get("emitter_role") == role:
            self_ms.append(t_ms); self_y.append(y)
        else:
            cross_ms.append(t_ms); cross_y.append(y)
    if self_ms:
        ax.scatter(self_ms, self_y, marker="o", s=22, facecolors="none",
                   edgecolors="#1a7f37", lw=1.2, zorder=6, label="self selection")
    if cross_ms:
        ax.scatter(cross_ms, cross_y, marker="x", s=34, color="#b45309",
                   lw=1.4, zorder=7, label="cross (partner) selection")

    ax.set_xlim(0, env.size * to_ms)
    ax.set_ylim(0, ymax * 1.08 if ymax > 0 else 1.0)
    ax.set_xlabel("time (ms, recording clock)")
    ax.set_ylabel("envelope")
    ax.set_title(f"{dev['role']} ({dev['id']}) — matched-filter envelope, selections & self mask",
                 fontsize=10)
    ax.legend(loc="upper right", fontsize=7, ncol=3, framealpha=0.9)
    return _fig_to_data_uri(fig)


def _fig_sweep(dev: dict) -> str:
    curves = dev["sweep_curves"]
    offsets = curves["offsets_ms"]
    fig, ax = plt.subplots(figsize=(11, 3.0))

    ax.plot(offsets, curves["raw"], color="#bbbbbb", lw=1.0, label="raw sweep (unmasked, diagnostic)")
    ax.plot(offsets, curves["masked"], color="#3b6ea5", lw=1.3, label="masked sweep (scored)")

    # Self-grid danger: offsets whose predictions collide with the self mask are made
    # ineligible (fewer than the minimum unmasked predictions). Shading them shows exactly
    # where the sweep was blinded to a self-alias.
    ineligible = curves["counts"] < SWEEP_MIN_UNMASKED_PREDICTIONS
    danger_shown = False
    if ineligible.any():
        step = float(offsets[1] - offsets[0]) if offsets.size > 1 else SWEEP_STEP_MS
        for off, bad in zip(offsets, ineligible):
            if bad:
                ax.axvspan(off - step / 2, off + step / 2, color="#d94f4f", alpha=0.10,
                           label="self-grid danger (predictions masked)" if not danger_shown else None)
                danger_shown = True

    # A3 prior window (only present for prior-bounded trials).
    prior = dev.get("cross_offset_prior")
    if prior and prior.get("center_ms") is not None and prior.get("half_window_ms") is not None:
        c = float(prior["center_ms"]); h = float(prior["half_window_ms"])
        ax.axvspan(c - h, c + h, color="#1a7f37", alpha=0.10, label="A3 prior window")
        ax.axvline(c, color="#1a7f37", ls="--", lw=0.8)

    sweep = dev["sweep"]
    if sweep.get("offset_ms") is not None:
        ax.axvline(float(sweep["offset_ms"]), color="#888888", ls="-.", lw=1.0,
                   label=f"sweep argmax {sweep['offset_ms']:+.0f} ms")
    chosen = dev.get("cross_offset_ms")
    if chosen is not None:
        ax.axvline(float(chosen), color="#b45309", ls="-", lw=1.6,
                   label=f"chosen Δ {chosen:+.1f} ms ({dev.get('cross_offset_source')})")

    ax.set_xlabel("candidate cross offset Δ (ms)")
    ax.set_ylabel("mean envelope at predictions")
    status = sweep.get("status")
    ax.set_title(
        f"{dev['role']} — offset sweep  |  cross_status={dev.get('cross_status')}  "
        f"sweep={status}  score={_num(dev.get('cross_offset_score'))}",
        fontsize=10,
    )
    ax.legend(loc="upper right", fontsize=7, framealpha=0.9)
    return _fig_to_data_uri(fig)


def _fig_spectra(data: dict) -> str:
    sig = data["signatures"].to_dict()
    freqs = np.array(sig.get("freqs_hz") or [], dtype=float)
    sim = data["similarity"]
    score = data["score"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))

    def _panel(ax, self_key, raw_key, comp_key, self_name, cross_name, c_val, sim_val):
        self_sig = np.array(sig.get(self_key) or [], dtype=float)
        raw_sig = np.array(sig.get(raw_key) or [], dtype=float)
        comp_sig = np.array(sig.get(comp_key) or [], dtype=float)
        if freqs.size and freqs.size == self_sig.size:
            x = freqs / 1000.0
            if self_sig.size:
                ax.plot(x, self_sig, color="#1a7f37", lw=1.3, label=f"{self_name} (self)")
            if raw_sig.size:
                ax.plot(x, raw_sig, color="#bbbbbb", lw=1.1, label=f"{cross_name} raw (pre-comp)")
            if comp_sig.size:
                ax.plot(x, comp_sig, color="#b45309", lw=1.2, label=f"{cross_name} compensated")
            ax.set_xlabel("frequency (kHz)")
        ax.set_ylabel("echo signature")
        ax.set_title(f"c={_num(c_val)}   self-similarity(A2.3)={_num(sim_val)}", fontsize=9)
        ax.legend(loc="upper right", fontsize=7, framealpha=0.9)

    _panel(axes[0], "sig_AA", "sig_BA_raw", "sig_BA_compensated", "AA", "BA",
           score.c_a, sim.get("device_a"))
    _panel(axes[1], "sig_BB", "sig_AB_raw", "sig_AB_compensated", "BB", "AB",
           score.c_b, sim.get("device_b"))
    dropped = data["signatures"].n_grid_mismatch_dropped
    fig.suptitle(
        f"Echo signatures before/after compensation  |  score={score.score:.3f} "
        f"(thr {score.threshold})  |  grid-mismatch dropped beeps={dropped}",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return _fig_to_data_uri(fig)


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

def _num(value, digits: int = 4) -> str:
    if value is None:
        return "None"
    try:
        return f"{float(value):.{digits}g}"
    except (TypeError, ValueError):
        return html.escape(str(value))


def _train_line(train: dict | None) -> str:
    if not train:
        return "none"
    return (f"lag {train['mapped_lag_ms']:+.1f} ms, σ {train['sigma_ms']:.2f} ms, "
            f"drift {train['drift_us_per_beep']:+.1f} µs/beep, amp {train['median_amplitude']:.2f}, "
            f"{train['support']}/{train['n_slots']} beeps")


def _clipping_note(warnings: set) -> str | None:
    """Localized clipping is a WARNING (D3.7), not a failure reason. When it actually excluded
    beeps it is the defining story of the trial and earns a banner mention; a clipping_localized
    warning that excluded ZERO beeps (minor clipping that touched no analysis window) is
    SUPPRESSED — surfacing it would stamp a spurious clipping mechanism onto the headline of
    every trial with any cosmetic clip. The token is `<label>_clipping_localized_<n>_beeps`;
    we parse n and print the device + count rather than echoing the raw token."""
    parts = []
    for w in sorted(warnings):
        marker = "_clipping_localized_"
        if marker not in w:
            continue
        label, _, tail = w.partition(marker)
        n_str = tail.split("_", 1)[0]
        try:
            n = int(n_str)
        except ValueError:
            n = None
        if not n:  # None or 0 excluded beeps -> not a headline story
            continue
        parts.append(f"{label}: {n} beep(s)")
    if not parts:
        return None
    return "CLIPPING LOCALIZED (excluded " + ", ".join(parts) + ")"


def _diagnosis(validity, devices: dict) -> tuple[str, str]:
    """One-line headline that NAMES the failure story (acceptance gate for C1)."""
    v = validity
    warnings = set(v.warnings)
    clip_note = _clipping_note(warnings)
    if v.capture_valid:
        verdict = "ACCEPT" if v.proximity_verdict else "REJECT"
        text = f"CAPTURE VALID → {verdict} (score {v.raw_score:.3f} vs thr)"
        if clip_note:
            text += "; " + clip_note
        return text, "ok" if v.proximity_verdict else "reject"
    reasons = set(v.failure_reasons)
    stories = []
    if any("partner_inaudible" in r for r in reasons):
        deaf = [lbl for lbl, d in devices.items()
                if d.get("cross_status") == "partner_inaudible"]
        stories.append("DEAF CHANNEL — partner beep below the audible floor on "
                       + (", ".join(deaf) or "a device"))
    if "cross_selection_self_aliased" in reasons:
        stories.append("SELF-ALIAS — cross selections latched onto the device's own beeps "
                       f"(overlaps {validity.alias_overlaps})")
    if "negative_round_trip" in reasons:
        stories.append("IMPOSSIBLE GEOMETRY — negative joint round-trip (round-trip air time is "
                       "positive by geometry; a swapped/replica partner labeling won the joint "
                       "assignment — see the train-assignment round_trip below)")
    if any(r.endswith("_cross_grid_coherent") or r.endswith("_cross_self_similar") for r in reasons):
        stories.append("GRID-COHERENT/SELF-SIMILAR cross channel (re-measuring self)")
    if "cross_offset_sum_inconsistent" in reasons:
        stories.append(f"SUM-INCONSISTENT offsets (residual {validity.sum_residual_ms} ms)")
    if any("clipped" in r and "localized" not in r for r in reasons):
        stories.append("CLIPPING — whole-recording saturation")
    if any("cross_offset_ambiguous" in r for r in reasons):
        stories.append("AMBIGUOUS cross offset (above floor, failed peakiness/joint constraint)")
    if any(r.endswith("_weak_direct_path") for r in reasons):
        stories.append("WEAK DIRECT PATH on "
                       + ", ".join(sorted({r.split("_")[0] for r in reasons if r.endswith("_weak_direct_path")})))
    if any(r.endswith("_low_period_recovery") for r in reasons):
        stories.append("LOW PERIOD RECOVERY on "
                       + ", ".join(sorted({r.split("_")[0] for r in reasons if r.endswith("_low_period_recovery")})))
    if any("self_train_ambiguous" in r for r in reasons):
        stories.append("SELF-TRAIN AMBIGUOUS (joint assignment could not pick the self train)")
    if clip_note:
        stories.append(clip_note)
    if not stories:
        stories.append("WITHHELD — " + ", ".join(sorted(reasons)))
    return "WITHHELD → " + "; ".join(stories), "withheld"


def _ul(items: list[str]) -> str:
    if not items:
        return "<span class='muted'>none</span>"
    return "<ul>" + "".join(f"<li>{html.escape(str(i))}</li>" for i in items) + "</ul>"


def _validity_html(data: dict) -> str:
    v = data["validity"]
    devices = data["devices"]
    rows = []
    rows.append(f"<tr><th>capture_valid</th><td>{v.capture_valid}</td></tr>")
    rows.append(f"<tr><th>proximity_verdict</th><td>{v.proximity_verdict}</td></tr>")
    rows.append(f"<tr><th>score / threshold</th><td>{data['score'].score:.4f} / {data['score'].threshold}"
                f" &nbsp; (c_a={data['score'].c_a:.4f}, c_b={data['score'].c_b:.4f})</td></tr>")
    rows.append(f"<tr><th>alignment_mode</th><td>{html.escape(str(devices['device_a'].get('alignment_mode')))}</td></tr>")
    rows.append(f"<tr><th>alias_overlaps</th><td>{html.escape(json.dumps(v.alias_overlaps))}</td></tr>")
    rows.append(f"<tr><th>grid_coherence_lag_ms</th><td>{html.escape(json.dumps(v.grid_coherence_lag_ms))}</td></tr>")
    rows.append(f"<tr><th>cross_self_similarity (A2.3)</th><td>{html.escape(json.dumps(v.cross_self_similarity))}</td></tr>")
    rows.append(f"<tr><th>sum_residual_ms (A2.5)</th><td>{v.sum_residual_ms}</td></tr>")
    assignment = data["assignment"]
    rows.append(f"<tr><th>train assignment</th><td>status={html.escape(str(assignment.get('status')))}, "
                f"round_trip={_num(assignment.get('round_trip_ms'))} ms</td></tr>")
    guard_table = "<table class='kv'>" + "".join(rows) + "</table>"

    reasons_block = (
        "<div class='cols'>"
        f"<div><h4>failure reasons</h4>{_ul(v.failure_reasons)}</div>"
        f"<div><h4>warnings</h4>{_ul(v.warnings)}</div>"
        "</div>"
    )
    return guard_table + reasons_block


def _compact_train(train: dict) -> str:
    """One-line competitor descriptor for the detected-train list (lag/σ/drift/amp/support)."""
    return (f"lag {train['mapped_lag_ms']:+.1f} ms · σ {train['sigma_ms']:.2f} · "
            f"drift {train['drift_us_per_beep']:+.0f} µs/beep · amp {train['median_amplitude']:.2f} · "
            f"{train['support']}/{train['n_slots']}")


def _detected_trains_html(dev: dict) -> str:
    """List EVERY detected train (not just a bare count), tagging the ones the joint assignment
    chose as self/partner. Without this, a *_self_train_ambiguous / train_assignment_ambiguous
    failure is undiagnosable from the report — the analyst cannot see WHICH competitor (e.g. a
    ~128 ms replica at similar amplitude, replica-findings §3) made the assignment ambiguous."""
    detected = dev.get("detected_trains") or []
    if not detected:
        return "<span class='muted'>none</span>"
    self_lag = (dev.get("self_train") or {}).get("mapped_lag_ms")
    partner_lag = (dev.get("partner_train") or {}).get("mapped_lag_ms")
    items = []
    for t in detected:
        lag = t.get("mapped_lag_ms")
        tag = ""
        if self_lag is not None and lag == self_lag:
            tag = " <b>[self]</b>"
        elif partner_lag is not None and lag == partner_lag:
            tag = " <b>[partner]</b>"
        items.append(f"<li>{html.escape(_compact_train(t))}{tag}</li>")
    return f"{len(detected)} total<ul>" + "".join(items) + "</ul>"


def _device_meta_html(dev: dict) -> str:
    rows = [
        ("cross_offset_ms", f"{_num(dev.get('cross_offset_ms'))} ({dev.get('cross_offset_source')})"),
        ("cross_status", dev.get("cross_status")),
        ("cross_offset_score", _num(dev.get("cross_offset_score"))),
        ("self_offset_ms / locked", f"{_num(dev.get('self_offset_ms'))} / {dev.get('self_locked')}"),
        ("self train", _train_line(dev.get("self_train"))),
        ("partner train", _train_line(dev.get("partner_train"))),
        ("align warnings", ", ".join(dev.get("alignment_warnings") or []) or "none"),
    ]
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(val))}</td></tr>" for k, val in rows)
    # Detected-trains row carries raw HTML (nested <ul> + [self]/[partner] tags), so it is
    # appended after the escaped scalar rows rather than going through the escape join above.
    body += f"<tr><th>detected trains</th><td>{_detected_trains_html(dev)}</td></tr>"
    return f"<table class='kv'>{body}</table>"


CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
       background: #ffffff; color: #1a1a1a; }
@media (prefers-color-scheme: dark) { body { background: #16181c; color: #e6e6e6; } }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; border-bottom: 1px solid #8884; padding-bottom: 4px; }
h3 { font-size: 13px; margin: 14px 0 6px; }
h4 { font-size: 12px; margin: 8px 0 4px; }
.banner { padding: 12px 16px; border-radius: 8px; font-weight: 600; font-size: 14px; margin: 10px 0 4px; }
.banner.ok { background: #1a7f3722; border: 1px solid #1a7f37; }
.banner.reject { background: #b4530922; border: 1px solid #b45309; }
.banner.withheld { background: #d94f4f22; border: 1px solid #d94f4f; }
.banner.degraded { background: #88888822; border: 1px solid #888; }
.sub { color: #888; font-size: 12px; margin: 0 0 8px; }
img { max-width: 100%; height: auto; display: block; margin: 6px 0; }
table.kv { border-collapse: collapse; font-size: 12px; margin: 6px 0; }
table.kv th { text-align: left; padding: 2px 12px 2px 0; vertical-align: top; color: #888; font-weight: 600; white-space: nowrap; }
table.kv td { padding: 2px 0; }
.cols { display: flex; gap: 32px; flex-wrap: wrap; }
.devgrid { display: flex; gap: 24px; flex-wrap: wrap; }
.devgrid > div { flex: 1 1 340px; }
ul { margin: 2px 0; padding-left: 18px; font-size: 12px; }
.muted { color: #888; }
.scroll { overflow-x: auto; }
"""


def render_html(record: dict, data: dict) -> str:
    trial_id = record.get("trial_id")
    bs = record.get("beep_spec") or {}
    band = f"{bs.get('start_freq_hz')}–{bs.get('end_freq_hz')} Hz, {bs.get('duration_ms')} ms, amp {bs.get('amplitude')}"
    head = (f"<h1>Proximity-Echo diagnostic — {html.escape(str(trial_id))}</h1>"
            f"<p class='sub'>condition={html.escape(str(record.get('condition_label')))} · band={html.escape(band)} · "
            f"timestamp={html.escape(str(record.get('timestamp')))} · re-derived from WAVs through the current pipeline</p>")

    banner_text, banner_cls = _diagnosis(data["validity"], data["devices"])
    banner = f"<div class='banner {banner_cls}'>{html.escape(banner_text)}</div>"

    parts = [f"<style>{CSS}</style>", head, banner]

    parts.append("<h2>1 · Validity verdict &amp; guard measurements</h2>")
    parts.append(_validity_html(data))

    parts.append("<h2>2 · Matched-filter envelope, selections &amp; self mask</h2>")
    for label in ("device_a", "device_b"):
        dev = data["devices"][label]
        parts.append(f"<h3>{html.escape(label)} — {dev['role']}</h3>")
        parts.append("<div class='scroll'><img src='" + _fig_envelope(dev) + "' alt='envelope'></div>")
        parts.append(_device_meta_html(dev))

    parts.append("<h2>3 · Offset sweep (masked + raw diagnostic)</h2>")
    for label in ("device_a", "device_b"):
        dev = data["devices"][label]
        parts.append(f"<h3>{html.escape(label)} — {dev['role']}</h3>")
        parts.append("<div class='scroll'><img src='" + _fig_sweep(dev) + "' alt='sweep'></div>")

    parts.append("<h2>4 · Echo signatures before/after compensation (A2.3, D3.6)</h2>")
    parts.append("<div class='scroll'><img src='" + _fig_spectra(data) + "' alt='spectra'></div>")

    return "\n".join(parts)


def _degraded_html(record: dict, reason: str) -> str:
    """Logged-only fallback when the WAVs are gone: render what the record already holds."""
    trial_id = record.get("trial_id")
    pair = record.get("pair") or {}
    score = record.get("score") or {}
    parts = [f"<style>{CSS}</style>",
             f"<h1>Proximity-Echo diagnostic — {html.escape(str(trial_id))}</h1>",
             f"<div class='banner degraded'>DEGRADED REPORT — figures unavailable: {html.escape(reason)}. "
             "Rendering logged records only.</div>"]
    if record.get("failure_reason"):
        parts.append(f"<p class='sub'>logged failure_reason: {html.escape(str(record['failure_reason']))}</p>")
    rows = [
        ("capture_valid", pair.get("capture_valid")),
        ("failure_reasons", pair.get("failure_reasons")),
        ("warnings", pair.get("warnings")),
        ("alias_overlaps", pair.get("alias_overlaps")),
        ("grid_coherence_lag_ms", pair.get("grid_coherence_lag_ms")),
        ("cross_self_similarity", pair.get("cross_self_similarity")),
        ("sum_residual_ms", pair.get("sum_residual_ms")),
        ("score / c_a / c_b", f"{score.get('score')} / {score.get('c_a')} / {score.get('c_b')}"),
        ("alignment_mode", record.get("alignment_mode")),
    ]
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(json.dumps(v) if not isinstance(v, str) else v)}</td></tr>"
                   for k, v in rows)
    parts.append(f"<table class='kv'>{body}</table>")
    return "\n".join(parts)


def build_report(trial_id: str, trials_path: Path = DEFAULT_TRIALS,
                 audio_dir: Path = DEFAULT_AUDIO, out_dir: Path | None = None) -> Path:
    """Generate the self-contained HTML report and return its path. Raises on a missing
    log or unknown trial id; degrades to a logged-only report when the WAVs are absent."""
    trials_path = Path(trials_path)
    audio_dir = Path(audio_dir)
    if not trials_path.exists():
        raise FileNotFoundError(f"missing log file: {trials_path}")
    record = load_record(trial_id, trials_path)
    if record is None:
        raise KeyError(f"trial not found: {trial_id}")

    data = recompute(record, audio_dir)
    if data.get("ok"):
        html_text = render_html(record, data)
    else:
        html_text = _degraded_html(record, data.get("reason", "unknown"))

    out_dir = Path(out_dir) if out_dir else (ROOT / "data" / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{trial_id}_report.html"
    out_path.write_text(html_text, encoding="utf-8")
    return out_path
