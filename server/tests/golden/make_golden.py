"""Write JBL250 goldens from fieldprobes (read-only import). Run once, commit the .f32 files.

  research/proximity-echo/.venv/bin/python3 server/tests/golden/make_golden.py

Files: jbl250_{generate|template}_{A|B}_{sr}.f32, little-endian float32, n = round(0.25*sr).
(.npy is gitignored in this repo, hence raw .f32.)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FIELDTEST = HERE.parents[2] / "research" / "sound-bound" / "spikes" / "melody" / "fieldtest"
sys.path.insert(0, str(FIELDTEST))
import fieldprobes  # noqa: E402

SEED = "5b" * 32
ROLES = ("A", "B")
RATES = (44100, 48000)


def main():
    for role in ROLES:
        for sr in RATES:
            g = fieldprobes.generate(SEED, "JBL250", role, sr).astype("<f4")
            t = fieldprobes.template(SEED, "JBL250", role, sr).astype("<f4")
            g.tofile(HERE / f"jbl250_generate_{role}_{sr}.f32")
            t.tofile(HERE / f"jbl250_template_{role}_{sr}.f32")
            print(role, sr, g.size, float(np.sqrt(np.mean(g.astype(float) ** 2))))


if __name__ == "__main__":
    main()
