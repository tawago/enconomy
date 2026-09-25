"""Interactive 3D viewer for the Proximity-Echo simulation.

Opens a window with a 3D room + two devices you can reposition/reorient with sliders, and
re-runs the physics simulation through the real scorer on demand, showing c_a / c_b / the
proximity verdict live. This is a research dial, not a product UI: it exists so you can
*see* a scene and watch how distance, device orientation, SNR and room absorption move the
score — especially the directional-mic blocker and the touch-distance clipping dip.

Run (needs a display):
    cd research/proximity-echo && source .venv/bin/activate
    python simulation/viewer.py

Controls
    distance        laptop<->phone separation on the desk
    laptop facing   azimuth the laptop mic/speaker point (180 deg = toward the phone here)
    phone speaker   azimuth the phone speaker points (0 deg = toward the laptop here)
    SNR             recording signal-to-noise ratio
    absorption      average wall absorption (more = deader room, weaker echoes)
    [Run]           render both recordings and score them (~0.6 s)
    different room  toggle: put the devices in separate rooms (negative case)

Each slider move redraws the geometry instantly and marks the score stale; press Run (or
release a slider) to recompute.
"""

from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, CheckButtons, Slider

import scene
from scene import (
    Room,
    Trial,
    compute_shared_room_rirs,
    compute_split_rirs,
    laptop,
    phone,
)

BEEPS = 8                # small L keeps a run ~0.6 s; raise for fidelity
ROOM_DIMS = (4.5, 3.5, 2.7)
CZ = 0.75               # desk height


def _az_to_vec(az_deg: float) -> np.ndarray:
    a = np.radians(az_deg)
    return np.array([np.cos(a), np.sin(a), 0.0])


def build(params: dict):
    """Return (laptop_device, phone_device, rir_bundle, mode_label)."""
    d = params["distance"]
    cx, cy = ROOM_DIMS[0] / 2, ROOM_DIMS[1] / 2
    lap = laptop((cx - d / 2, cy, CZ), facing_az_deg=params["lap_facing"])
    ph = phone((cx + d / 2, cy, CZ), speaker_az_deg=params["phone_spk"])
    if params["different_room"]:
        room_a = Room(dims=ROOM_DIMS, absorption=params["absorption"], max_order=8)
        room_b = Room(dims=(3.2, 2.8, 2.5), absorption=params["absorption"] + 0.08, max_order=8)
        # Re-home the phone into its own room's coordinate frame.
        ph = phone((1.6, 1.4, CZ), speaker_az_deg=params["phone_spk"])
        rirs = compute_split_rirs(room_a, lap, room_b, ph, attenuation_db=60.0,
                                  lowpass_hz=2_500.0, seed=params["seed"])
        return lap, ph, rirs, "different rooms"
    room = Room(dims=ROOM_DIMS, absorption=params["absorption"], max_order=8)
    rirs = compute_shared_room_rirs(room, lap, ph)
    return lap, ph, rirs, "same room"


def run_sim(params: dict) -> dict:
    lap, ph, rirs, mode = build(params)
    trial = Trial(lap, ph, rirs, mode, snr_db=params["snr"], agc=False, seed=params["seed"])
    r = scene.run_trial(trial, beeps_per_device=BEEPS)
    r["mode"] = mode
    r["devices"] = (lap, ph)
    return r


# --------------------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------------------
def draw_room_box(ax, dims):
    x, y, z = dims
    pts = np.array([[0, 0, 0], [x, 0, 0], [x, y, 0], [0, y, 0],
                    [0, 0, z], [x, 0, z], [x, y, z], [0, y, z]])
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    for a, b in edges:
        ax.plot(*zip(pts[a], pts[b]), color="0.7", lw=0.8)


def draw_scene(ax, params):
    ax.clear()
    lap, ph, _, mode = build(params)
    draw_room_box(ax, ROOM_DIMS)

    lp = np.array(lap.mic_pos)
    pp = np.array(ph.speaker_pos)
    ax.scatter(*lp, color="tab:blue", s=80, depthshade=False)
    ax.text(*lp + np.array([0, 0, 0.12]), "laptop", color="tab:blue", fontsize=9)
    ax.scatter(*pp, color="tab:orange", s=80, depthshade=False)
    ax.text(*pp + np.array([0, 0, 0.12]), "phone", color="tab:orange", fontsize=9)

    # Direction arrows: laptop mic, phone speaker.
    mic_dir = _az_to_vec(params["lap_facing"]) * 0.5
    spk_dir = _az_to_vec(params["phone_spk"]) * 0.5
    ax.quiver(*lp, *mic_dir, color="tab:blue", lw=2, arrow_length_ratio=0.3)
    ax.quiver(*pp, *spk_dir, color="tab:orange", lw=2, arrow_length_ratio=0.3)

    if mode == "same room":
        ax.plot(*zip(lp, pp), color="0.4", ls="--", lw=1)
        mid = (lp + pp) / 2
        ax.text(*mid + np.array([0, 0, 0.15]), f"{params['distance']*100:.0f} cm", fontsize=9)

    ax.set_xlim(0, ROOM_DIMS[0]); ax.set_ylim(0, ROOM_DIMS[1]); ax.set_zlim(0, ROOM_DIMS[2])
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)"); ax.set_zlabel("z (m)")
    ax.set_title(f"scene: {mode}")


def format_result(r: dict) -> str:
    ca, cb, mean = r["c_a"], r["c_b"], r["score"]
    mn = min(ca, cb)
    verdict = "ACCEPT" if r["verdict"] else "reject"
    ok = r["period_ok"]
    return (f"mode: {r['mode']}\n\n"
            f"c_a (A self vs B)  = {ca:+.3f}\n"
            f"c_b (B self vs A)  = {cb:+.3f}\n\n"
            f"mean (paper)       = {mean:+.3f}\n"
            f"   -> {verdict} @ {r['threshold']:.2f}\n"
            f"min(c_a,c_b)       = {mn:+.3f}\n"
            f"   (best discriminator)\n\n"
            f"period_ok\n"
            f"  AA={ok['AA']} BB={ok['BB']} BA@A={ok['BA_at_A']} AB@B={ok['AB_at_B']}\n"
            f"cross_offset_ms\n"
            f"  A={r['cross_offset_ms']['A']}  B={r['cross_offset_ms']['B']}")


# --------------------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------------------
def make_app():
    fig = plt.figure(figsize=(13, 7))
    fig.canvas.manager.set_window_title("Proximity-Echo simulation")
    ax3d = fig.add_axes([0.02, 0.30, 0.58, 0.66], projection="3d")
    ax_txt = fig.add_axes([0.63, 0.30, 0.36, 0.66]); ax_txt.axis("off")

    params = {"distance": 0.30, "lap_facing": 180.0, "phone_spk": 0.0,
              "snr": 48.0, "absorption": 0.22, "different_room": False, "seed": 1}

    txt = ax_txt.text(0.0, 1.0, "press Run", va="top", family="monospace", fontsize=10)
    status = fig.text(0.65, 0.26, "", color="tab:red", fontsize=10)

    def add_slider(rect, label, lo, hi, val, fmt="%.2f"):
        return Slider(fig.add_axes(rect), label, lo, hi, valinit=val, valfmt=fmt)

    s_dist = add_slider([0.10, 0.20, 0.50, 0.02], "distance (m)", 0.05, 2.0, params["distance"])
    s_lap = add_slider([0.10, 0.16, 0.50, 0.02], "laptop facing (deg)", 0, 360, params["lap_facing"], "%.0f")
    s_phone = add_slider([0.10, 0.12, 0.50, 0.02], "phone speaker (deg)", 0, 360, params["phone_spk"], "%.0f")
    s_snr = add_slider([0.10, 0.08, 0.50, 0.02], "SNR (dB)", 20, 60, params["snr"], "%.0f")
    s_abs = add_slider([0.10, 0.04, 0.50, 0.02], "absorption", 0.10, 0.50, params["absorption"])

    chk = CheckButtons(fig.add_axes([0.72, 0.13, 0.18, 0.10]), ["different room"], [False])
    btn = Button(fig.add_axes([0.72, 0.05, 0.18, 0.05]), "Run simulation")

    def read_params():
        params.update(distance=s_dist.val, lap_facing=s_lap.val, phone_spk=s_phone.val,
                      snr=s_snr.val, absorption=s_abs.val,
                      different_room=chk.get_status()[0])
        return params

    def redraw_scene(_=None):
        draw_scene(ax3d, read_params())
        status.set_text("scene changed - press Run to rescore")
        fig.canvas.draw_idle()

    def run(_=None):
        status.set_text("running...")
        fig.canvas.draw_idle()
        r = run_sim(read_params())
        txt.set_text(format_result(r))
        txt.set_color("tab:green" if r["verdict"] else "black")
        status.set_text("")
        fig.canvas.draw_idle()

    for s in (s_dist, s_lap, s_phone, s_snr, s_abs):
        s.on_changed(redraw_scene)
    chk.on_clicked(redraw_scene)
    btn.on_clicked(run)

    draw_scene(ax3d, params)
    run()  # initial score
    return fig


def main() -> int:
    make_app()
    plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
