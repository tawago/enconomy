"""pop-v1 shared constants (contract §6.1) + POPT v2 (docs/pop-transcript-v2.md §6). Same values in dsp_ref.py
and Kotlin PopConstants; the app reads them from GET /v1/config."""
PROTO = "pop-v1"
SR_MIN, SR_MAX = 36000, 96000
CODE_S = 0.25
BAND_HZ = (2000, 18000)
FADE_S = 0.005
TARGET_RMS, MAX_PEAK = 0.15, 0.95
PRIMER_S = 0.3
LEAD_S = 0.5
CAPTURE_S = 2.5
A_PLAY_S, B_PLAY_S = 0.0, 0.95
SEARCH_PRE_S, SEARCH_POST_S = 0.150, 0.250
SEGMENT_MARGIN_S = 0.1
N_NULL = 64
NULL_P = 1e-4
NULL_P_SAFETY = 3.0
FLOOR_SCORE = 0.05
HALF_FRAC = 0.5
HALF_LOOKAHEAD_S = 0.005
FLAT_RUN_MIN_S = 0.008
IMPOSSIBLE_CM = -20
NEAR_CM = 60
SPEED_OF_SOUND_CM_S = 34300
# |self_os_delta| bound for the plaintext verdict, v1 and v2; one value for server and app (/v1/config).
# TODO: set after on-device timestamp measurement (the option A circuit allows DELTA_MS = 2).
SELF_OS_TOL_MS = 50
# enrollment calibration (pop/calibration.py): N audio checks, median µs, reject spread / range, clamp small negatives.
# The self check is |self_os_delta - cal_frames| <= SELF_OS_TOL_MS, cal_us in 0..CAL_MAX_US.
CAL_N = 5
CAL_SPREAD_MAX_US = 1000
CAL_MAX_US = 50000
CAL_NEG_CLAMP_US = 2000
TRANSCRIPT_DEADLINE_S = 20
MAX_ATTEMPTS = 2

# POPT v2 (option A): transcript/commit version chosen per role at arm ("popt": 1 | 2)
POPT_VERSIONS = (1, 2)
DELTA_MS = 2
T0_V2 = 0.09
FIR_TAPS = 63
TEMPLATE_BITS = 8
LEAF = 1024
TREE_DEPTH = 4
ZK_RATES = (44100, 48000)

# server-side timing (contract §2.2, §2.3, §3.1, §9.1)
ENROLL_NONCE_TTL_S = 600
AUTH_SKEW_S = 60
AUTH_REPLAY_S = 120
JOIN_TOKEN_TTL_S = 120
SESSION_MAX_AGE_S = 600
LONGPOLL_MAX_S = 25


def table() -> dict:
    """§6.1 as JSON for GET /v1/config (lowercase keys)."""
    names = ["PROTO", "SR_MIN", "SR_MAX", "CODE_S", "BAND_HZ", "FADE_S", "TARGET_RMS", "MAX_PEAK",
             "PRIMER_S", "LEAD_S", "CAPTURE_S", "A_PLAY_S", "B_PLAY_S", "SEARCH_PRE_S", "SEARCH_POST_S",
             "SEGMENT_MARGIN_S", "N_NULL", "NULL_P", "NULL_P_SAFETY", "FLOOR_SCORE", "HALF_FRAC",
             "HALF_LOOKAHEAD_S", "FLAT_RUN_MIN_S", "IMPOSSIBLE_CM", "NEAR_CM", "SPEED_OF_SOUND_CM_S",
             "SELF_OS_TOL_MS", "TRANSCRIPT_DEADLINE_S", "MAX_ATTEMPTS",
             "CAL_N", "CAL_SPREAD_MAX_US", "CAL_MAX_US", "CAL_NEG_CLAMP_US",
             "POPT_VERSIONS", "DELTA_MS", "T0_V2", "FIR_TAPS", "TEMPLATE_BITS", "LEAF", "TREE_DEPTH", "ZK_RATES"]
    g = globals()
    return {n.lower(): (list(g[n]) if isinstance(g[n], tuple) else g[n]) for n in names}
