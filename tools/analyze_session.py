"""Feasibility analysis of labeled CSI sessions.

    python tools/analyze_session.py data/jack/20261124_094437_eecs-635-classroom-half-capacity
    python tools/analyze_session.py SESSION_A SESSION_B ...    # + cross-session tests

A session is a folder from record_session.py (csi.csv + trials.csv + meta.json)
or an old single-file session_*.csv. For each session it reports:
  1. Detection      - gesture windows vs still windows
  2. Segmentation   - label-free motion detector run over the whole stream
  3. Static hand    - held hand vs empty room
  4. Classification - swipe / push / circle (/ none), beep-aligned vs onset-aligned
With several sessions it also trains on one and tests on the others.
Figures are saved inside each session folder (or next to the old csv).
"""

import csv
import json
import os
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.metrics import roc_auc_score, confusion_matrix

VALID = np.r_[1:27, 38:64]          # L-LTF data subcarriers (nulls dropped)
GESTURES = ["swipe", "push", "circle"]
CLASSES = GESTURES + ["none"]
ROLL = 20                            # packets in rolling-std motion score
WIN_S = 2.0                          # analysis window length
COLORS = {"empty": "#cccccc", "hold": "#f4a261", "swipe": "#2a9d8f", "push": "#e76f51",
          "circle": "#6a4c93", "none": "#8ab17d"}


# ================================================================== loading
class Session:
    def __init__(self, path):
        path = path.rstrip("/\\")
        if os.path.isdir(path):
            self.dir, csv_path = path, os.path.join(path, "csi.csv")
            meta_p = os.path.join(path, "meta.json")
            self.meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
            self.name = os.path.basename(path)
            self.fig_path = os.path.join(path, "analysis.png")
        else:
            self.dir, csv_path, self.meta = os.path.dirname(path), path, {}
            self.name = os.path.splitext(os.path.basename(path))[0]
            self.fig_path = path.rsplit(".", 1)[0] + "_analysis.png"

        t, label, trial, rssi, amp, bad = [], [], [], [], [], 0
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                try:
                    raw = np.frombuffer(bytes.fromhex(row["data"] or ""), np.int8).astype(np.float32)
                    r = int(row["rssi"])
                    tr = int(row["trial"])
                except (ValueError, TypeError):
                    bad += 1
                    continue
                if raw.size < 128:
                    bad += 1
                    continue
                t.append(float(row["host_time"]))
                label.append(row["label"])
                trial.append(tr)
                rssi.append(r)
                amp.append(np.hypot(raw[1:128:2], raw[0:128:2])[VALID])
        self.bad = bad
        self.t0 = t[0]
        self.t = np.array(t) - self.t0
        self.label = np.array(label)
        self.trial = np.array(trial)
        self.rssi = np.array(rssi)
        amp = np.stack(amp)
        self.amp = amp / (amp.mean(1, keepdims=True) + 1e-6)   # remove per-packet gain (AGC)
        self.rate = len(self.t) / self.t[-1]
        self.motion = motion_score(self.amp)

        # trial status from trials.csv (new recorder); everything is "ok" otherwise
        self.status = {}
        tp = os.path.join(self.dir, "trials.csv") if os.path.isdir(path) else None
        if tp and os.path.exists(tp):
            for row in csv.DictReader(open(tp)):
                self.status[int(row["trial"])] = row["status"]
        self.trials = self._build_trials()

    def _build_trials(self):
        """One record per gesture/none trial: go window, ready (pre-GO) window, label."""
        out = []
        for g in CLASSES:
            for tr in np.unique(self.trial[self.label == g]):
                if self.status.get(tr, "ok") != "ok":
                    continue
                go = np.flatnonzero((self.label == g) & (self.trial == tr))
                ready = np.flatnonzero((self.label == "ready") & (self.trial == tr))
                if go.size < 50:
                    continue
                out.append(dict(label=g, trial=int(tr), go_start=self.t[go[0]], go_end=self.t[go[-1]],
                                ready=ready if ready.size >= 20 else
                                np.flatnonzero((self.t >= self.t[go[0]] - 1.5) & (self.t < self.t[go[0]]))))
        return sorted(out, key=lambda r: r["go_start"])

    def idx(self, t0, t1):
        return np.flatnonzero((self.t >= t0) & (self.t < t1))

    def segments(self, name):
        idx = np.flatnonzero(self.label == name)
        if idx.size == 0:
            return []
        br = np.flatnonzero(np.diff(idx) > 1)
        return list(zip(np.r_[idx[0], idx[br + 1]], np.r_[idx[br], idx[-1]] + 1))

    def title(self):
        m = self.meta
        if m:
            return f"{m.get('location', self.name)} ({m.get('distance_cm', '?')} cm, {m.get('person', '')})"
        return self.name


def motion_score(amp):
    """Rolling std / mean per subcarrier, averaged across subcarriers."""
    w = np.lib.stride_tricks.sliding_window_view(amp, ROLL, axis=0)
    s = (w.std(-1) / (w.mean(-1) + 1e-6)).mean(1)
    return np.r_[np.full(ROLL - 1, s[0]), s]


# ============================================================ segmentation
def find_onset(s, tr):
    """Motion onset inside a trial, relative to that trial's own quiet (ready) level.

    No model needed: threshold = quiet median + 4 * MAD (at least 1.4x the median),
    first run above threshold lasting >= 0.15 s, searched from 0.3 s before GO to 1 s after it.
    Returns (onset_time or None, threshold).
    """
    q = s.motion[tr["ready"]]
    floor = np.median(q)
    thr = max(floor + 4 * np.median(np.abs(q - floor)), 1.4 * floor)
    idx = s.idx(tr["go_start"] - 0.3, tr["go_end"] + 1.0)
    above = s.motion[idx] > thr
    need = int(0.15 * s.rate)
    run = 0
    for i, a in enumerate(above):
        run = run + 1 if a else 0
        if run >= need:
            return s.t[idx[i - need + 1]], thr
    return None, thr


def detect_events(s, ratio=1.6, min_dur=0.3, merge_gap=0.4, floor_win=10.0):
    """Label-free motion events over the whole stream (what a device would run live).

    Adaptive floor = 20th percentile of the motion score over the previous `floor_win` s,
    so slow drift and a busy background raise the bar automatically.
    """
    n_floor = int(floor_win * s.rate)
    step = max(1, int(0.25 * s.rate))
    floor = np.empty_like(s.motion)
    for i in range(0, len(s.motion), step):
        lo = max(0, i - n_floor)
        floor[i:i + step] = np.percentile(s.motion[lo:i + 1], 20) if i > lo else s.motion[0]
    active = s.motion > ratio * floor
    ev, start = [], None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        elif not a and start is not None:
            ev.append([s.t[start], s.t[i - 1]])
            start = None
    merged = []
    for e in ev:
        if merged and e[0] - merged[-1][1] < merge_gap:
            merged[-1][1] = e[1]
        else:
            merged.append(e)
    return [e for e in merged if e[1] - e[0] >= min_dur], floor


# ================================================================ features
def resample(x, n):
    edges = np.linspace(0, len(x), n + 1).astype(int)
    return np.stack([x[a:max(b, a + 1)].mean(0) for a, b in zip(edges[:-1], edges[1:])])


def features(amp, motion):
    prof = resample(motion, 10)                                   # temporal shape of motion
    rel = amp - amp[:10].mean(0)
    dev = resample(np.abs(rel).mean(1), 10)                       # drift from window start
    groups = np.array_split(np.arange(amp.shape[1]), 8)
    band = np.array([amp[:, g].std(0).mean() for g in groups])    # which subcarriers move
    c = amp - amp.mean(0)
    pc = c @ np.linalg.svd(c, full_matrices=False)[2][0]
    zc = np.sum(np.diff(np.sign(pc - pc.mean())) != 0)            # periodicity
    return np.r_[prof, dev, band, motion.max(), motion.mean(), zc]


def window_features(s, aligned):
    """Feature matrix for every trial; window starts at the beep or at the detected onset."""
    X, y = [], []
    for tr in s.trials:
        start = tr["go_start"]
        if aligned and tr.get("onset") is not None:
            start = tr["onset"] - 0.2
        i = s.idx(start, start + WIN_S)
        X.append(features(s.amp[i], s.motion[i]))
        y.append(tr["label"])
    return np.stack(X), np.array(y)


MODELS = {
    "logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=3000)),
    "kNN-3": lambda: make_pipeline(StandardScaler(), KNeighborsClassifier(3)),
    "forest": lambda: RandomForestClassifier(300, random_state=0),
}


def loo(X, y):
    res = {}
    for name, mk in MODELS.items():
        pred = cross_val_predict(mk(), X, y, cv=LeaveOneOut())
        res[name] = ((pred == y).mean(), pred)
    return res


# ================================================================ analysis
def analyze(s):
    print(f"\n{'=' * 78}\n{s.title()}\n{'=' * 78}")
    print(f"{len(s.t)} packets, {s.t[-1]:.0f} s, {s.rate:.0f} pkt/s, RSSI median {np.median(s.rssi):.0f} dBm"
          + (f", {s.bad} corrupted rows skipped" if s.bad else "")
          + (f", {sum(v != 'ok' for v in s.status.values())} redo/aborted trials excluded" if s.status else ""))
    out = {}

    # ---- 1. detection (beep-aligned GO windows vs still windows)
    still = []
    for a, b in s.segments("empty"):
        for k in range(a, b - int(WIN_S * s.rate), int(WIN_S * s.rate)):
            still.append(s.idx(s.t[k], s.t[k] + WIN_S))
    pos = [np.percentile(s.motion[s.idx(tr["go_start"], tr["go_end"] + 0.5)], 90)
           for tr in s.trials if tr["label"] != "none"]
    neg = ([np.percentile(s.motion[s.idx(tr["go_start"], tr["go_end"] + 0.5)], 90)
            for tr in s.trials if tr["label"] == "none"] + [np.percentile(s.motion[i], 90) for i in still])
    y = np.r_[np.ones(len(pos)), np.zeros(len(neg))]
    sc = np.r_[pos, neg]
    auc = roc_auc_score(y, sc)
    acc = max(((sc >= th) == y).mean() for th in sc)
    print(f"\n1. DETECTION   {len(pos)} gesture vs {len(neg)} still windows: AUC {auc:.3f}, "
          f"best fixed threshold {acc:.1%}, gesture/still motion x{np.median(pos) / np.median(neg):.1f}")
    out["detect_auc"], out["detect_acc"] = auc, acc

    # ---- 2. segmentation without labels
    for tr in s.trials:
        tr["onset"], tr["thr"] = find_onset(s, tr)
    g_on = [tr for tr in s.trials if tr["label"] != "none"]
    n_on = [tr for tr in s.trials if tr["label"] == "none"]
    hit = sum(tr["onset"] is not None for tr in g_on)
    fa = sum(tr["onset"] is not None for tr in n_on)
    lat = [tr["onset"] - tr["go_start"] for tr in g_on if tr["onset"] is not None]
    print(f"\n2. SEGMENTATION (per-trial onset vs that trial's quiet level)")
    print(f"   onset found in {hit}/{len(g_on)} gestures, {fa}/{len(n_on)} still trials (false alarms); "
          f"reaction time after GO: median {np.median(lat):.2f} s, range {min(lat):.2f}..{max(lat):.2f} s")
    events, floor = detect_events(s)
    g_start = s.trials[0]["go_start"] - 3 if s.trials else 0
    ev_g = [e for e in events if e[0] >= g_start]
    matched_tr, matched_ev = set(), 0
    for e in ev_g:
        m = [tr["trial"] for tr in s.trials if e[0] < tr["go_end"] + 1.0 and e[1] > tr["go_start"] - 0.3]
        lab = [tr["label"] for tr in s.trials if tr["trial"] in m]
        if any(l != "none" for l in lab):
            matched_ev += 1
        matched_tr.update(m)
    recall = sum(tr["trial"] in matched_tr for tr in g_on) / max(1, len(g_on))
    none_fa = sum(tr["trial"] in matched_tr for tr in n_on)
    print(f"   label-free stream detector: {len(ev_g)} events in the gesture phase; "
          f"{recall:.0%} of gestures caught, {matched_ev}/{len(ev_g)} events overlap a gesture, "
          f"{none_fa}/{len(n_on)} still trials triggered")
    out["seg_hit"], out["stream_recall"] = hit / max(1, len(g_on)), recall
    out["stream_precision"] = matched_ev / max(1, len(ev_g))
    out["events"], out["floor"] = events, floor

    # ---- 3. static hand
    empty = np.flatnonzero(s.label == "empty")
    n1 = int(s.rate)
    base = s.amp[empty].mean(0)
    chunks = [s.amp[empty[i:i + n1]].mean(0) for i in range(0, len(empty) - n1, n1)]
    noise = np.median([np.linalg.norm(a - b) for i, a in enumerate(chunks) for b in chunks[i + 1:]])
    holds = [(a, b) for a, b in s.segments("hold")]
    hold_d = [np.linalg.norm(s.amp[a + n1:b].mean(0) - base) for a, b in holds]
    rest_d = [np.linalg.norm(s.amp[a + n1:b].mean(0) - base) for a, b in s.segments("rest") if b - a > 2 * n1]
    print(f"\n3. STATIC HAND  held hand moves the profile {np.mean(hold_d) / noise:.1f}x baseline noise "
          f"(rest periods drift {np.median(rest_d) / noise:.1f}x)")
    out["static"] = np.mean(hold_d) / noise
    out["base"], out["holds"] = base, holds

    # ---- 4. classification
    print("\n4. CLASSIFICATION (leave-one-trial-out)       logreg  kNN-3  forest")
    for aligned in (False, True):
        X, y = window_features(s, aligned)
        for task, cls in (("3 gestures", GESTURES), ("4 classes", CLASSES)):
            m = np.isin(y, cls)
            r = loo(X[m], y[m])
            tag = "onset-aligned" if aligned else "beep-aligned "
            print(f"   {tag} {task:10s} (chance {1 / len(cls):.0%})   "
                  + "  ".join(f"{r[k][0]:5.0%}" for k in MODELS))
            out[(aligned, task)] = r
    Xa, ya = window_features(s, True)
    m = np.isin(ya, GESTURES)
    best = max(MODELS, key=lambda k: out[(True, "3 gestures")][k][0])
    acc3, pred = out[(True, "3 gestures")][best]
    out["cm"] = confusion_matrix(ya[m], pred, labels=GESTURES)
    out["cm_name"] = f"{best}, {acc3:.0%}"
    plot(s, out)
    return out


def cross_session(sessions):
    print(f"\n{'=' * 78}\nCROSS-SESSION (train on one, test on another; onset-aligned)\n{'=' * 78}")
    data = [window_features(s, True) for s in sessions]
    print(f"   {'train -> test':55s} 3-gest  4-class   (logreg / kNN-3 / forest)")
    for i, (Xi, yi) in enumerate(data):
        for j, (Xj, yj) in enumerate(data):
            if i == j:
                continue
            row = []
            for cls in (GESTURES, CLASSES):
                mi, mj = np.isin(yi, cls), np.isin(yj, cls)
                accs = []
                for mk in MODELS.values():
                    mdl = mk().fit(Xi[mi], yi[mi])
                    accs.append((mdl.predict(Xj[mj]) == yj[mj]).mean())
                row.append("/".join(f"{a:.0%}" for a in accs))
            name = f"{sessions[i].title()[:26]} -> {sessions[j].title()[:26]}"
            print(f"   {name:55s} {row[0]:15s} {row[1]}")
    # per-session feature standardization = a short calibration in the new room
    print("   with per-session feature standardization (simulates a quick calibration):")
    zdata = [((X - X.mean(0)) / (X.std(0) + 1e-6), y) for X, y in data]
    for i, (Xi, yi) in enumerate(zdata):
        for j, (Xj, yj) in enumerate(zdata):
            if i == j:
                continue
            mi, mj = np.isin(yi, GESTURES), np.isin(yj, GESTURES)
            accs = [(mk().fit(Xi[mi], yi[mi]).predict(Xj[mj]) == yj[mj]).mean() for mk in MODELS.values()]
            print(f"   {sessions[i].title()[:26]} -> {sessions[j].title()[:26]}: "
                  + " / ".join(f"{a:.0%}" for a in accs) + "  (3 gestures)")
    X = np.vstack([d[0] for d in zdata])
    y = np.concatenate([d[1] for d in zdata])
    m = np.isin(y, GESTURES)
    r = loo(X[m], y[m])
    print(f"   pooled, leave-one-out over all sessions (3 gestures): "
          + " / ".join(f"{r[k][0]:.0%}" for k in MODELS))


# ================================================================== figure
def plot(s, out):
    fig = plt.figure(figsize=(15, 11))
    gs = fig.add_gridspec(3, 4, height_ratios=[1.1, 1, 1])
    ax = fig.add_subplot(gs[0, :])
    for name, c in COLORS.items():
        for a, b in s.segments(name):
            ax.axvspan(s.t[a], s.t[b - 1], color=c, alpha=0.35, lw=0)
    ax.plot(s.t, s.motion, lw=0.6, color="k")
    ax.plot(s.t, 1.6 * out["floor"], lw=0.8, color="tab:red", alpha=0.7, label="detector threshold")
    for e in out["events"]:
        ax.axvspan(e[0], e[1], ymin=0.94, ymax=1.0, color="tab:red")
    ax.set_xlim(0, s.t[-1])
    ax.set_ylim(0, np.percentile(s.motion, 99.5) * 1.15)
    ax.set_ylabel("motion score")
    ax.set_xlabel("time (s)")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c, alpha=0.5) for c in COLORS.values()]
              + [plt.Line2D([], [], color="tab:red")], labels=list(COLORS) + ["detector (red ticks = events)"],
              ncol=7, loc="upper left", fontsize=8)
    ax.set_title(f"{s.title()}: motion score, labeled periods, label-free detector events")

    for j, g in enumerate(CLASSES):
        ax = fig.add_subplot(gs[1, j])
        trs = [tr for tr in s.trials if tr["label"] == g]
        if not trs:
            continue
        tr = trs[len(trs) // 2]
        st = tr["onset"] - 0.2 if tr.get("onset") is not None else tr["go_start"]
        w = s.amp[s.idx(st, st + WIN_S)]
        ax.imshow((w - w[:10].mean(0)).T, aspect="auto", origin="lower", cmap="RdBu_r",
                  vmin=-0.4, vmax=0.4, extent=[0, WIN_S, 0, w.shape[1]])
        ax.set_title(f"{g} (trial {tr['trial']}{', onset-aligned' if tr.get('onset') is not None else ''})",
                     fontsize=9)
        ax.set_xlabel("s")
        if j == 0:
            ax.set_ylabel("subcarrier\n(change vs start)")

    ax = fig.add_subplot(gs[2, 0:2])
    x = np.linspace(0, WIN_S, 50)
    for g in CLASSES:
        P = []
        for tr in s.trials:
            if tr["label"] == g:
                st = tr["onset"] - 0.2 if tr.get("onset") is not None else tr["go_start"]
                P.append(resample(s.motion[s.idx(st, st + WIN_S)], 50))
        P = np.stack(P)
        ax.plot(x, P.mean(0), label=g, color=COLORS[g])
        ax.fill_between(x, P.mean(0) - P.std(0), P.mean(0) + P.std(0), color=COLORS[g], alpha=0.15)
    ax.set_title("Mean motion profile per class, onset-aligned (±1 sd)")
    ax.set_xlabel("s from onset - 0.2 s")
    ax.legend(fontsize=8)

    ax = fig.add_subplot(gs[2, 2])
    ax.plot(out["base"], label="empty", color="k")
    n1 = int(s.rate)
    for k, (a, b) in enumerate(out["holds"]):
        ax.plot(s.amp[a + n1:b].mean(0), label=f"hold {k + 1}", alpha=0.8)
    ax.set_title("Static hand: amplitude profile")
    ax.set_xlabel("subcarrier")
    ax.legend(fontsize=7)

    ax = fig.add_subplot(gs[2, 3])
    cm = out["cm"]
    ax.imshow(cm, cmap="Blues")
    for (i, j), v in np.ndenumerate(cm):
        ax.text(j, i, v, ha="center", va="center")
    ax.set_xticks(range(3), GESTURES)
    ax.set_yticks(range(3), GESTURES)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(f"3-gesture confusion ({out['cm_name']})")
    fig.tight_layout()
    fig.savefig(s.fig_path, dpi=90)
    plt.close(fig)
    print(f"\n   figure: {s.fig_path}")


def main(paths):
    sessions = [Session(p) for p in paths]
    for s in sessions:
        analyze(s)
    if len(sessions) > 1:
        cross_session(sessions)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
