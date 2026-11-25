"""Figures for the project proposal (docs/proposal/).

    python tools/proposal_figures.py

Reads recorded sessions in data/ and writes PNGs to docs/proposal/fig/.
"""
import os
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
from analyze_session import Session, find_onset  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "proposal", "fig")
CLASSROOM = os.path.join(ROOT, "data", "jack", "20261124_094437_eecs-635-classroom-half-capacity")
APARTMENT = os.path.join(ROOT, "data", "jack", "20261124_180510_apartment-alone")
STL = os.path.join(ROOT, "hardware", "fixture", "stl")

PAPER = "#fbfaf7"
INK, MUTED, ACCENT, ACCENT2 = "#1d2433", "#667085", "#d1603d", "#12636b"
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
DIVERGE = LinearSegmentedColormap.from_list("teal_clay", ["#0b3f45", "#12636b", "#8fc1c0", "#fbfaf7",
                                                          "#f0b49a", "#d1603d", "#8a3216"])
plt.rcParams.update({
    "font.family": ["Inter", "Segoe UI", "DejaVu Sans"], "font.size": 10, "axes.edgecolor": "#9ca3af",
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 11,
    "axes.titleweight": "bold", "savefig.facecolor": PAPER, "figure.facecolor": PAPER, "axes.facecolor": PAPER, "axes.titlelocation": "left", "axes.titlecolor": INK,
})


def heat(ax, s, t0, dur, title):
    w = s.amp[s.idx(t0, t0 + dur)]
    im = ax.imshow((w - w[:10].mean(0)).T, aspect="auto", origin="lower", cmap=DIVERGE,
                   vmin=-0.4, vmax=0.4, extent=[0, dur, 0, w.shape[1]])
    ax.set_title(title)
    ax.set_xlabel("time (s)")
    for sp in ax.spines.values():
        sp.set_visible(False)
    return im


def fig_csi_example(s):
    """(a) CSI amplitude across subcarriers, empty vs hand held; (b) still room; (c) a gesture."""
    fig = plt.figure(figsize=(11, 3.4))
    gs = fig.add_gridspec(1, 4, width_ratios=[1.25, 1, 1, 0.05], wspace=0.35)

    ax = fig.add_subplot(gs[0])
    a, b = s.segments("empty")[0]
    ax.plot(s.amp[a:b].mean(0), color=INK, lw=2, label="empty room")
    ha, hb = s.segments("hold")[1]
    n1 = int(s.rate)
    ax.plot(s.amp[ha + n1:hb].mean(0), color=ACCENT, lw=2, label="hand held between antennas")
    ax.set_xlabel("subcarrier (frequency →)")
    ax.set_ylabel("relative amplitude")
    ax.set_title("(a) One CSI snapshot")
    ax.set_ylim(0.5, 1.75)
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncol=1)

    # still: a 2 s slice from the middle of the empty-room period
    mid = (s.t[a] + s.t[b - 1]) / 2
    ax = fig.add_subplot(gs[1])
    heat(ax, s, mid - 1, 2.0, "(b) Nobody moving")
    ax.set_ylabel("subcarrier")

    tr = [t for t in s.trials if t["label"] == "circle"]
    tr = tr[len(tr) // 2]
    on, _ = find_onset(s, tr)
    st = (on if on is not None else tr["go_start"]) - 0.2
    ax = fig.add_subplot(gs[2])
    im = heat(ax, s, st, 2.0, "(c) Hand circling")
    ax.set_yticklabels([])

    cax = fig.add_subplot(gs[3])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("change vs. start", color=MUTED)
    cb.outline.set_visible(False)
    fig.savefig(os.path.join(OUT, "csi_example.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def read_stl(path):
    d = open(path, "rb").read()
    if d[:5] == b"solid" and b"facet" in d[:400]:      # ASCII STL (OpenSCAD export)
        v = [l.split()[1:] for l in d.decode().splitlines() if l.strip().startswith("vertex")]
        return np.array(v, dtype=float).reshape(-1, 3, 3)
    n = int.from_bytes(d[80:84], "little")
    a = np.frombuffer(d[84:84 + n * 50], dtype=np.dtype([("n", "<f4", (3,)), ("v", "<f4", (9,)), ("a", "<u2")]))
    return a["v"].reshape(-1, 3, 3).astype(float)


def fig_fixture():
    """Shaded render of the assembled rig fixture."""
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(9, 3.6))
    ax = fig.add_subplot(projection="3d")
    light = np.array([0.4, -0.6, 0.7])
    light /= np.linalg.norm(light)
    for name, base in (("rx_half", np.array([0.82, 0.38, 0.24])), ("tx_half", np.array([0.07, 0.39, 0.42]))):
        tri = read_stl(os.path.join(STL, name + ".stl"))
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9
        shade = 0.5 + 0.5 * np.abs(nrm @ light)
        ax.add_collection3d(Poly3DCollection(tri, facecolors=base[None] * shade[:, None], edgecolor="none"))
    ax.set_xlim(-22, 362)
    ax.set_ylim(-120, 120)
    ax.set_zlim(0, 120)
    ax.set_box_aspect((384, 240, 120))
    ax.view_init(elev=28, azim=-58)
    ax.set_axis_off()
    path = os.path.join(OUT, "fixture.png")
    fig.savefig(path, dpi=220)
    plt.close(fig)
    from PIL import Image, ImageChops   # crop the empty 3D-axes margin
    im = Image.open(path).convert("RGB")
    box = ImageChops.difference(im, Image.new("RGB", im.size, PAPER)).getbbox()
    im.crop((box[0] - 20, box[1] - 20, box[2] + 20, box[3] + 20)).save(path, optimize=True)


def fig_recorder(shots):
    """Two recorder screens side by side: rest/countdown and GO."""
    from PIL import Image
    ims = [Image.open(os.path.join(shots, f)) for f in ("0042_rest.png", "0047_swipe.png")]
    ims = [im.crop((0, 120, im.width, im.height)) for im in ims]   # drop the session title bar
    w, h = ims[0].size
    gap = 40
    out = Image.new("RGB", (2 * w + gap, h), (253, 252, 249))
    out.paste(ims[0], (0, 0))
    out.paste(ims[1], (w + gap, 0))
    out = out.resize((1800, int(1800 * h / (2 * w + gap))), Image.LANCZOS)
    out.save(os.path.join(OUT, "recorder.png"), optimize=True)


def fig_gestures(s):
    """Onset-aligned CSI change for each music-v1 class, one typical trial each."""
    titles = {"swipe": "Swipe", "swipe_back": "Swipe + back", "palm": "Palm hold", "other": "Other motion"}
    fig = plt.figure(figsize=(12, 3.0))
    gs = fig.add_gridspec(1, 5, width_ratios=[1, 1, 1, 1, 0.05], wspace=0.12)
    win = s.win_s
    for j, g in enumerate(["swipe", "swipe_back", "palm", "other"]):
        ax = fig.add_subplot(gs[j])
        trs = [t for t in s.trials if t["label"] == g]
        if g == "other":
            st = trs[len(trs) // 2]["go_start"]
        else:
            for t in trs:
                t["onset"], _ = find_onset(s, t)
            trs = [t for t in trs if t["onset"] is not None]
            # example trial ranked by motion in the window: the top one for swipe (a short
            # motion, weak in most trials), the 75th percentile otherwise
            sc = [s.motion[s.idx(t["onset"] - 0.2, t["onset"] - 0.2 + win)].mean() for t in trs]
            q = 1.0 if g == "swipe" else 0.75
            t = trs[int(np.argsort(sc)[int(q * (len(sc) - 1))])]
            st = t["onset"] - 0.2
        im = heat(ax, s, st, win, titles[g])
        if j == 0:
            ax.set_ylabel("subcarrier")
        else:
            ax.set_yticklabels([])
    cax = fig.add_subplot(gs[4])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("change vs. start", color=MUTED)
    cb.outline.set_visible(False)
    fig.savefig(os.path.join(OUT, "gestures.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def fig_results(results):
    """Within- vs cross-session 3-gesture accuracy."""
    fig, ax = plt.subplots(figsize=(8, 3.2))
    labels = [r[0] for r in results]
    vals = [r[1] for r in results]
    cols = [ACCENT2 if r[2] == "within" else ACCENT for r in results]
    x = np.arange(len(results))
    ax.bar(x, vals, color=cols, width=0.62)
    for xi, v in zip(x, vals):
        ax.text(xi, v + 1.5, f"{v:.0f}%", ha="center", color=INK, fontsize=10, fontweight="bold")
    ax.axhline(33.3, color=MUTED, lw=1, ls="--")
    ax.set_xlim(-0.5, len(results) - 0.1)
    ax.text(len(results) - 0.12, 35, "chance", color=MUTED, fontsize=9, ha="right")
    ax.set_xticks(x, labels, fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_ylabel("3-gesture accuracy")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=ACCENT2), plt.Rectangle((0, 0), 1, 1, color=ACCENT)],
              labels=["within one session", "train on one session, test on another"],
              frameon=False, fontsize=9, loc="upper right", ncol=2, bbox_to_anchor=(1, 1.12))
    fig.savefig(os.path.join(OUT, "results.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


# 3-gesture accuracy (%), from tools/analyze_session.py; see docs/project_log.md
RESULTS = [
    ("Home\n(swipe/push/circle)", 71, "within"),
    ("Classroom\n(swipe/push/circle)", 88, "within"),
    ("Apartment\n(music gestures)", 62, "within"),
    ("Home →\nClassroom", 54, "cross"),
    ("Classroom →\nHome", 58, "cross"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    fig_csi_example(Session(CLASSROOM))
    fig_gestures(Session(APARTMENT))
    fig_fixture()
    fig_results(RESULTS)
    if len(sys.argv) > 1:          # folder of recorder screenshots (record_session.py --screenshots)
        fig_recorder(sys.argv[1])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
