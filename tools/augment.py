"""Physics-motivated augmentation for CSI amplitude windows + cross-session test.

    python tools/augment.py SESSION_A SESSION_B [...]

Each augmentation imitates a real source of variation between recordings:

  room_gain     new room / furniture  -> random smooth gain curve across subcarriers
                (multipath changes the frequency-selective fading pattern)
  background    busy room             -> add real background motion taken from the
                                         TRAINING session's still/rest periods
  strength      distance / hand size  -> scale the dynamic part of the window
  time_warp     gesture speed         -> stretch/squeeze time by 0.8-1.25x
  time_shift    reaction time         -> move the window +-0.25 s
  noise         electronics           -> small Gaussian noise

The experiment trains on one session (with and without augmentation) and tests on
another, per augmentation and all combined, so you can see which ones actually help.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_session import (Session, find_onset, features, motion_score, MODELS,  # noqa: E402
                             GESTURES, CLASSES, WIN_S)

PAD_S = 0.5           # extra context each side so time shifts/warps have real data


def resample_rows(w, n):
    x = np.linspace(0, len(w) - 1, n)
    xp = np.arange(len(w))
    return np.stack([np.interp(x, xp, w[:, k]) for k in range(w.shape[1])], 1)


def wide_windows(s):
    """(N, T_wide, K) windows: onset-aligned (or GO-aligned), padded by PAD_S each side."""
    n_win = int(round(WIN_S * s.rate))
    n_pad = int(round(PAD_S * s.rate))
    X, y = [], []
    for tr in s.trials:
        tr["onset"], _ = find_onset(s, tr)
        start = (tr["onset"] - 0.2) if tr["onset"] is not None else tr["go_start"]
        i = s.idx(start - PAD_S, start + WIN_S + PAD_S)
        X.append(resample_rows(s.amp[i], n_win + 2 * n_pad))
        y.append(tr["label"])
    return np.stack(X), np.array(y), n_win, n_pad


def background_pool(s, n_win):
    """Empty-room stretches = realistic background with nobody gesturing.

    Not 'rest'/'ready': those contain the arm returning from the last gesture, and
    pasting that into every class blurs the labels (tested: -15 to -20 points).
    """
    pool = []
    for name in ("empty",):
        for a, b in s.segments(name):
            for k in range(a, b - n_win, n_win // 2):
                pool.append(s.amp[k:k + n_win])
    return pool


def augment(wide, n_win, n_pad, rng, bg_pool, use):
    w = wide
    K = w.shape[1]
    nominal = n_pad
    if "time_warp" in use:
        f = rng.uniform(0.8, 1.25)
        w = resample_rows(w, int(round(len(w) * f)))
        nominal = int(round(n_pad * f))
    shift = rng.integers(-n_pad // 2, n_pad // 2 + 1) if "time_shift" in use else 0
    start = int(np.clip(nominal + shift, 0, len(w) - n_win))
    w = w[start:start + n_win].copy()
    if "strength" in use:
        mu = w.mean(0)
        w = mu + (w - mu) * rng.uniform(0.6, 1.5)
    if "room_gain" in use:
        k = np.arange(K) / K
        g = sum(rng.uniform(0.05, 0.15) * np.cos(2 * np.pi * rng.uniform(0.5, 3) * k + rng.uniform(0, 2 * np.pi))
                for _ in range(3))
        w = w * np.exp(g)
    if "background" in use and bg_pool:
        b = bg_pool[rng.integers(len(bg_pool))]
        w = w + (b - b.mean(0)) * rng.uniform(0.3, 1.0)
    if "noise" in use:
        w = w + rng.normal(0, 0.01, w.shape)
    w = np.clip(w, 1e-3, None)
    return w / w.mean(1, keepdims=True)          # same per-packet normalization as real data


def center(wide, n_win, n_pad):
    return wide[n_pad:n_pad + n_win]


def featurize(windows):
    return np.stack([features(w, motion_score(w)) for w in windows])


ALL = ["room_gain", "background", "strength", "time_warp", "time_shift", "noise"]


def experiment(sessions, copies=15, seed=0):
    rng = np.random.default_rng(seed)
    data = []
    for s in sessions:
        W, y, n_win, n_pad = wide_windows(s)
        data.append(dict(s=s, W=W, y=y, n_win=n_win, n_pad=n_pad, bg=background_pool(s, n_win),
                         X=featurize([center(w, n_win, n_pad) for w in W])))
    configs = [("no augmentation", [])] + [(f"+ {a}", [a]) for a in ALL] + [("all combined", ALL)]
    for task, cls in (("3 gestures", GESTURES), ("4 classes", CLASSES)):
        print(f"\n{task} (chance {1 / len(cls):.0%}) - train -> test accuracy, mean of logreg/kNN-3/forest")
        header = "".join(f"{d['s'].title()[:14]:>16s}" for d in data)
        for i, tr in enumerate(data):
            for j, te in enumerate(data):
                if i == j:
                    continue
                print(f"  {tr['s'].title()[:30]} -> {te['s'].title()[:30]}")
                mi, mj = np.isin(tr["y"], cls), np.isin(te["y"], cls)
                for name, use in configs:
                    Xtr, ytr = [tr["X"][mi]], [tr["y"][mi]]
                    if use:
                        aug = [augment(w, tr["n_win"], tr["n_pad"], rng, tr["bg"], use)
                               for w, lab in zip(tr["W"][mi], tr["y"][mi]) for _ in range(copies)]
                        Xtr.append(featurize(aug))
                        ytr.append(np.repeat(tr["y"][mi], copies))
                    Xtr, ytr = np.vstack(Xtr), np.concatenate(ytr)
                    accs = [(mk().fit(Xtr, ytr).predict(te["X"][mj]) == te["y"][mj]).mean()
                            for mk in MODELS.values()]
                    print(f"    {name:18s} {np.mean(accs):5.0%}   ({' / '.join(f'{a:.0%}' for a in accs)})")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    experiment([Session(p) for p in sys.argv[1:]])
