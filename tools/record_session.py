"""Guided CSI recording session - full-screen visual prompts, no audio needed.

    python tools/record_session.py              # auto-finds the ESP32-S3 port
    python tools/record_session.py COM11
    python tools/record_session.py --demo       # practice run with fake data, no board

Close csi_live.py first (only one program can use the COM port).

Keys:  SPACE continue   R redo last trial   P pause / resume   ESC finish & save

Output: data/<person>/<YYYYmmdd_HHMMSS>_<location>/
    csi.csv     every CSI packet with the label + trial id active when it arrived
    trials.csv  one row per trial: label, start/end time, status (ok/redo/aborted), motion ratio
    meta.json   who / where / setup notes
"""

import argparse
import collections
import csv
import json
import os
import random
import re
import sys
import threading
import time

import numpy as np
import serial
import serial.tools.list_ports
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QSpinBox,
                             QVBoxLayout, QWidget)

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
VALID = np.r_[1:27, 38:64]
GESTURES = {
    "swipe": ("SWIPE", "Hand crosses the phone-antenna line once, sideways"),
    "push": ("PUSH", "Hand IN the line, palm to antenna: move toward it and back"),
    "circle": ("CIRCLE", "One circle centered on the line, like drawing on a window"),
    "none": ("STAY STILL", "Control trial: hand in your lap, don't move"),
}
COLORS = {"idle": "#264653", "ready": "#b08900", "go": "#1b7f5b", "rest": "#3d4451",
          "still": "#5a5f6b", "hold": "#c0622b", "pause": "#8b1e1e"}
READY_S, GO_S, REST_S = 2.0, 2.0, 2.0
TRIALS_PER_BREAK = 16


# ----------------------------------------------------------------- data source
class Source:
    """Reads CSI from serial (or fakes it) on a thread and tags rows with the current label."""

    def __init__(self, port, baud, fake):
        self.fake = fake
        self.label, self.trial = "setup", -1
        self.out = None
        self.amp = collections.deque(maxlen=40)
        self.motion = collections.deque(maxlen=3000)  # (host_time, motion)
        self.count, self.rssi = 0, 0
        self.stop = threading.Event()
        self.ser = None if fake else serial.Serial(port, baud, timeout=1)
        threading.Thread(target=self._run, daemon=True).start()

    def _serial_lines(self):
        while not self.stop.is_set():
            yield self.ser.readline().decode("ascii", errors="ignore")

    def _fake_lines(self):
        k, seq, t0 = np.arange(64), 0, time.time()
        base = 35 + 15 * np.sin(k / 5)
        while not self.stop.is_set():
            time.sleep(max(0.0, t0 + seq * 0.01 - time.time()))  # hold ~100 pkt/s on average
            seq += 1
            a = base + np.random.randn(64) * 0.6
            if self.label in ("swipe", "push", "circle", "hold_enter", "hold_exit"):
                a += 12 * np.sin(k / 3 + time.time() * 9)
            elif self.label == "hold":
                a += 8 * np.cos(k / 4)
            ph = np.random.uniform(0, 2 * np.pi, 64)
            buf = np.empty(128, np.int8)
            buf[0::2] = np.clip(a * np.sin(ph), -127, 127)
            buf[1::2] = np.clip(a * np.cos(ph), -127, 127)
            yield f"CSI,{seq},{int((time.time() - t0) * 1e6)},-50,11,1,0,128,{buf.tobytes().hex()}\n"

    def _run(self):
        for line in (self._fake_lines() if self.fake else self._serial_lines()):
            line = line.strip()
            if not line.startswith("CSI,"):
                continue
            parts = line.split(",")
            if len(parts) != 9 or len(parts[8]) != 256:
                continue  # truncated / corrupted line
            try:
                raw = np.frombuffer(bytes.fromhex(parts[8]), np.int8).astype(np.float32)
                rssi = int(parts[3])
            except ValueError:
                continue
            now = time.time()
            a = np.hypot(raw[1::2], raw[0::2])[VALID]
            self.amp.append(a / (a.mean() + 1e-6))
            if len(self.amp) >= 20:
                w = np.array(self.amp)[-20:]
                self.motion.append((now, float((w.std(0) / (w.mean(0) + 1e-6)).mean())))
            self.count += 1
            self.rssi = rssi
            if self.out:
                self.out.write(f"{now:.6f},{self.label},{self.trial},{line[4:]}\n")
        if self.ser:
            self.ser.close()

    def motion_between(self, t0, t1):
        return np.array([m for t, m in list(self.motion) if t0 <= t < t1])


def find_port():
    for p in serial.tools.list_ports.comports():
        if p.vid == 0x303A:
            return p.device
    return None


# ----------------------------------------------------------------- setup dialog
class SetupDialog(QDialog):
    def __init__(self, last):
        super().__init__()
        self.setWindowTitle("CSI recording - session setup")
        f = QFormLayout(self)
        self.name = QLineEdit(last.get("person", ""))
        self.location = QLineEdit(last.get("location", ""))
        self.location.setPlaceholderText("e.g. EECS classroom, busy")
        self.distance = QSpinBox()
        self.distance.setRange(5, 1000)
        self.distance.setSuffix(" cm")
        self.distance.setValue(last.get("distance_cm", 70))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("anything unusual: people walking by, phone on stand, ...")
        self.reps = QSpinBox()
        self.reps.setRange(1, 50)
        self.reps.setValue(last.get("reps", 8))
        self.holds = QCheckBox("Include held-hand trials (~1 min)")
        self.holds.setChecked(last.get("holds", True))
        f.addRow("Your name", self.name)
        f.addRow("Location", self.location)
        f.addRow("Phone-antenna distance", self.distance)
        f.addRow("Notes", self.notes)
        f.addRow("Reps per gesture", self.reps)
        f.addRow("", self.holds)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _ok(self):
        if not self.name.text().strip() or not self.location.text().strip():
            QMessageBox.warning(self, "Missing info", "Please fill in your name and the location.")
            return
        self.accept()

    def values(self):
        return dict(person=self.name.text().strip(), location=self.location.text().strip(),
                    distance_cm=self.distance.value(), notes=self.notes.text().strip(),
                    reps=self.reps.value(), holds=self.holds.isChecked())


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


# ----------------------------------------------------------------- session plan
def build_plan(cfg):
    """List of groups; each group is a list of steps. A group is redone as a unit."""
    groups = []

    def wait(title, sub, label="idle"):
        groups.append(dict(kind="wait", steps=[dict(wait=True, label=label, color="idle", title=title, sub=sub)]))

    wait("Setup check",
         "Phone hotspot on, antenna taped down, phone 0.5-1 m away in a clear line.\n"
         "Sit to the SIDE of the line - only your arm should reach in.\n"
         "Don't move the phone or antenna until the session ends.\n\n"
         "Watch the bar at the bottom: packets should be ~100/s.\n\nPress SPACE to begin")
    wait("Room baseline", "Hands in your lap, sit still for 15 seconds.\n\nPress SPACE when ready")
    groups.append(dict(kind="empty", steps=[
        dict(label="empty", color="still", dur=15, title="STAY STILL", sub="Recording the room with no gesture")]))

    if cfg["holds"]:
        wait("Held hand",
             "3 times: move your hand INTO the line (about 20 cm from the antenna),\n"
             "freeze it there for 8 seconds, then take it away.\n\nPress SPACE when ready")
        for _ in range(3):
            groups.append(dict(kind="hold", label="hold", steps=[
                dict(label="rest", color="ready", dur=3, title="Get ready", sub="Hand in lap"),
                dict(label="hold_enter", color="go", dur=2, title="HAND IN", sub="Move your hand into the line", go=True),
                dict(label="hold", color="hold", dur=8, title="FREEZE", sub="Hold your hand perfectly still"),
                dict(label="hold_exit", color="go", dur=2, title="HAND OUT", sub="Back to your lap"),
                dict(label="rest", color="rest", dur=3, title="Rest", sub="", feedback=True),
            ]))

    trials = [g for g in GESTURES for _ in range(cfg["reps"])]
    random.shuffle(trials)
    wait("Gestures",
         f"{len(trials)} short trials. Each one: the next gesture is shown in yellow,\n"
         "then the screen turns GREEN - do the gesture ONCE, then rest.\n\n"
         + "\n".join(f"{v[0]:>10}:  {v[1]}" for v in GESTURES.values())
         + "\n\nMade a mistake? Press R during the rest to redo it.\n\nPress SPACE to start")
    for i, g in enumerate(trials):
        if i and i % TRIALS_PER_BREAK == 0:
            wait("Break", f"{i} of {len(trials)} done. Shake out your arm.\n\nPress SPACE to continue")
        groups.append(gesture_group(g))
    groups.append(dict(kind="done", steps=[dict(wait=True, label="idle", color="go", title="Done!",
                                                sub="Thanks! Press SPACE or ESC to save and close")]))
    return groups


def gesture_group(g):
    name, desc = GESTURES[g]
    return dict(kind="gesture", label=g, steps=[
        dict(label="ready", color="ready", dur=READY_S, title=f"Next: {name}", sub=desc),
        dict(label=g, color="go", dur=GO_S, title=f"{name}  NOW", sub=desc, go=True),
        dict(label="rest", color="rest", dur=REST_S, title="Rest", sub="", feedback=True),
    ])


# ----------------------------------------------------------------- main window
class Recorder(QWidget):
    def __init__(self, src, cfg, outdir, autopilot=False):
        super().__init__()
        self.src, self.cfg, self.outdir, self.autopilot = src, cfg, outdir, autopilot
        self.groups = build_plan(cfg)
        self.n_gesture = sum(g["kind"] == "gesture" for g in self.groups)
        self.gi, self.si = 0, 0
        self.step_t0 = time.time()
        self.paused = False
        self.trial_id = -1
        self.trials = []            # dicts written to trials.csv
        self.cur = None             # current trial record
        self.feedback = ""
        self.rate, self._last_count, self._last_rate_t = 0.0, 0, time.time()

        self.setWindowTitle("CSI recording")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 20)
        self.top = QLabel()
        self.top.setFont(QFont("Segoe UI", 16))
        self.title = QLabel()
        self.title.setFont(QFont("Segoe UI", 80, QFont.Weight.Bold))
        self.sub = QLabel()
        self.sub.setFont(QFont("Segoe UI", 22))
        self.sub.setWordWrap(True)
        self.fb = QLabel()
        self.fb.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        for w in (self.title, self.sub, self.fb):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(28)
        self.status = QLabel()
        self.status.setFont(QFont("Consolas", 14))
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedWidth(220)
        self.meter.setFixedHeight(18)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(QLabel("motion"))
        bottom.addWidget(self.meter)
        lay.addWidget(self.top)
        lay.addStretch(1)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addSpacing(20)
        lay.addWidget(self.fb)
        lay.addStretch(1)
        lay.addWidget(self.bar)
        lay.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.enter_step()

    # -- plan navigation
    @property
    def group(self):
        return self.groups[self.gi]

    @property
    def step(self):
        return self.group["steps"][self.si]

    def enter_step(self):
        s = self.step
        if self.si == 0 and self.group["kind"] in ("gesture", "hold"):
            self.trial_id += 1
            self.cur = dict(trial=self.trial_id, label=self.group["label"], start=time.time(),
                            go_start=None, go_end=None, end=None, status="in_progress", motion_ratio="")
            self.trials.append(self.cur)
            self.feedback = ""
        if self.group["kind"] not in ("gesture", "hold"):
            self.cur = None
        self.src.label = s["label"]
        self.src.trial = self.trial_id if self.cur else -1
        if s.get("go") and self.cur:
            self.cur["go_start"] = time.time()
        self.step_t0 = time.time()
        self.fb.setText(self.feedback if s.get("feedback") else "")
        self.render()
        self.save_trials()

    def next_step(self):
        s = self.step
        if s.get("go") and self.cur and self.group["kind"] == "gesture":
            self.cur["go_end"] = time.time()
        if self.group["kind"] == "hold" and s["label"] == "hold" and self.cur:
            self.cur["go_end"] = time.time()
        self.si += 1
        if self.si >= len(self.group["steps"]):
            if self.cur and self.cur["status"] == "in_progress":
                self.cur["status"] = "ok"
                self.cur["end"] = time.time()
            self.gi += 1
            self.si = 0
            if self.gi >= len(self.groups):
                self.finish()
                return
        self.enter_step()

    # -- feedback: did the trial contain motion?
    def check_trial(self):
        c = self.cur
        if not c or c.get("checked") or not c["go_start"]:
            return
        c["checked"] = True
        if self.group["kind"] == "hold":
            return
        before = self.src.motion_between(c["start"], c["go_start"])
        during = self.src.motion_between(c["go_start"], (c["go_end"] or time.time()) + 0.5)
        if before.size < 20 or during.size < 20:
            self.feedback = "⚠ Missing data for this trial - press R to redo"
            return
        ratio = np.percentile(during, 90) / (np.median(before) + 1e-6)
        c["motion_ratio"] = round(float(ratio), 2)
        moving = ratio > 1.5
        if c["label"] == "none":
            self.feedback = ("✓ Nice and still" if not moving
                             else f"⚠ Movement detected ({ratio:.1f}×) - press R to redo")
        else:
            self.feedback = (f"✓ Motion captured ({ratio:.1f}×)" if moving
                             else f"⚠ Little motion detected ({ratio:.1f}×) - press R to redo")
        self.fb.setText(self.feedback)

    # -- keys
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.finish()
        elif k == Qt.Key.Key_Space and self.step.get("wait") and not self.paused:
            if self.group["kind"] == "done":
                self.finish()
            elif self.gi == 0 and self.rate < 30 and not self.src.fake:
                self.fb.setText("⚠ Not receiving data - check the hotspot and USB before starting")
            else:
                self.next_step()
        elif k == Qt.Key.Key_P:
            self.toggle_pause()
        elif k == Qt.Key.Key_R:
            self.redo_last()

    def toggle_pause(self):
        if self.group["kind"] == "done":
            return
        self.paused = not self.paused
        if self.paused:
            self.src.label = "pause"
            if self.cur and self.cur["status"] == "in_progress":
                self.cur["status"] = "aborted"
                self.cur["end"] = time.time()
                # replay this group from the start after resuming
                if self.group["kind"] == "gesture":
                    self.groups.insert(self.gi + 1, gesture_group(self.group["label"]))
                else:
                    self.groups.insert(self.gi + 1, dict(self.group))
                self.gi += 1
                self.si = 0
                self.cur = None
            self.render()
        else:
            self.si = 0
            self.enter_step()

    def redo_last(self):
        done = [t for t in self.trials if t["status"] == "ok" and t["label"] in GESTURES]
        cur_ok = self.cur and self.cur["label"] in GESTURES and self.cur["go_end"]
        target = self.cur if cur_ok else (done[-1] if done else None)
        if target is None or target["status"] == "redo":
            return
        target["status"] = "redo"
        target["end"] = target["end"] or time.time()
        self.groups.insert(self.gi + 1, gesture_group(target["label"]))
        self.n_gesture += 1
        self.feedback = f"↺ {GESTURES[target['label']][0]} will be redone next"
        self.fb.setText(self.feedback)
        self.save_trials()

    # -- loop
    def tick(self):
        now = time.time()
        if now - self._last_rate_t >= 1:
            self.rate = (self.src.count - self._last_count) / (now - self._last_rate_t)
            self._last_count, self._last_rate_t = self.src.count, now
        s = self.step
        if not self.paused and not s.get("wait"):
            el = now - self.step_t0
            self.bar.setValue(int(1000 * min(1, el / s["dur"])))
            if s.get("feedback") and el > 0.6:
                self.check_trial()
            if el >= s["dur"]:
                self.next_step()
                return
        elif self.autopilot and s.get("wait") and now - self.step_t0 > 1.0:
            if self.group["kind"] == "done":
                self.finish()
                return
            self.next_step()
            return
        self.render_status()

    def render(self):
        s = self.step
        color = COLORS["pause"] if self.paused else COLORS[s["color"]]
        self.setStyleSheet(f"QWidget {{ background: {color}; color: white; }}"
                           "QProgressBar { background: rgba(255,255,255,40); border: none; }"
                           "QProgressBar::chunk { background: white; }")
        if self.paused:
            self.title.setText("PAUSED")
            self.sub.setText("Press P to resume - the current trial will restart")
        else:
            self.title.setText(s["title"])
            self.sub.setText(s["sub"])
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setVisible(not s.get("wait"))
        done = sum(t["status"] == "ok" and t["label"] in GESTURES for t in self.trials)
        self.top.setText(f"{self.cfg['person']}  ·  {self.cfg['location']}  ·  "
                         f"gesture trials {done}/{self.n_gesture}")

    def render_status(self):
        ok = self.rate >= 50
        m = self.src.motion[-1][1] if self.src.motion else 0
        self.meter.setValue(int(min(100, m / 0.3 * 100)))
        warn = "" if ok else "   ⚠ LOW DATA RATE - check hotspot / USB"
        self.status.setText(f"{'●' if ok else '○'} {self.rate:3.0f} pkt/s   RSSI {self.src.rssi} dBm{warn}"
                            f"      [SPACE] continue  [R] redo last  [P] pause  [ESC] finish")
        self.status.setStyleSheet("color: white;" if ok else "color: #ffd166; font-weight: bold;")

    # -- saving
    def save_trials(self):
        with open(os.path.join(self.outdir, "trials.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, ["trial", "label", "status", "start", "go_start", "go_end", "end", "motion_ratio"],
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(self.trials)

    def finish(self):
        if getattr(self, "_finished", False):
            return
        self._finished = True
        self.timer.stop()
        if self.cur and self.cur["status"] == "in_progress":
            self.cur["status"] = "aborted"
            self.cur["end"] = time.time()
        self.save_trials()
        self.src.stop.set()
        time.sleep(0.2)
        self.src.out.close()
        meta_path = os.path.join(self.outdir, "meta.json")
        meta = json.load(open(meta_path))
        counts = collections.Counter(t["label"] for t in self.trials if t["status"] == "ok")
        meta.update(end_time=time.strftime("%Y-%m-%d %H:%M:%S"), packets=self.src.count,
                    ok_trials=dict(counts), redo_or_aborted=sum(t["status"] != "ok" for t in self.trials))
        json.dump(meta, open(meta_path, "w"), indent=2)
        print(f"\nSaved {self.src.count} packets to {self.outdir}")
        print("OK trials:", dict(counts))
        QApplication.instance().quit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", help="serial port (default: auto-detect ESP32-S3)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--demo", action="store_true", help="fake data, 2 reps - practice without a board")
    ap.add_argument("--autopilot", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--screenshots", help=argparse.SUPPRESS)
    args = ap.parse_args()

    app = QApplication(sys.argv)
    last_path = os.path.join(ROOT, ".last_setup.json")
    last = json.load(open(last_path)) if os.path.exists(last_path) else {}

    if args.autopilot:
        cfg = dict(person="demo", location="test", distance_cm=70, notes="", reps=1, holds=True)
    else:
        dlg = SetupDialog(last)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cfg = dlg.values()
    if args.demo:
        cfg["reps"] = min(cfg["reps"], 2)

    port = args.port or (None if args.demo else find_port())
    if not args.demo and not port:
        QMessageBox.critical(None, "No board", "Couldn't find the ESP32-S3. Is it plugged in?\n"
                                               "You can also pass the port, e.g. record_session.py COM11")
        return
    try:
        src = Source(port, args.baud, fake=args.demo)
    except serial.SerialException as e:
        QMessageBox.critical(None, "Port busy", f"Can't open {port}: {e}\n\nClose csi_live.py / the VS Code "
                                                "serial monitor and try again.")
        return

    os.makedirs(ROOT, exist_ok=True)
    if not args.autopilot:
        json.dump({k: cfg[k] for k in ("person", "location", "distance_cm", "reps", "holds")},
                  open(last_path, "w"))
    sub = "demo" if args.demo else slug(cfg["person"])
    outdir = os.path.join(ROOT, sub, time.strftime("%Y%m%d_%H%M%S_") + slug(cfg["location"]))
    os.makedirs(outdir, exist_ok=True)
    json.dump(dict(cfg, port=port, demo=args.demo, start_time=time.strftime("%Y-%m-%d %H:%M:%S"),
                   gestures={k: v[1] for k, v in GESTURES.items()},
                   timing=dict(ready_s=READY_S, go_s=GO_S, rest_s=REST_S)),
              open(os.path.join(outdir, "meta.json"), "w"), indent=2)
    src.out = open(os.path.join(outdir, "csi.csv"), "w", buffering=1)
    src.out.write("host_time,label,trial,seq,esp_us,rssi,rate,sig_mode,first_word_invalid,len,data\n")

    win = Recorder(src, cfg, outdir, autopilot=args.autopilot)
    if args.screenshots:
        os.makedirs(args.screenshots, exist_ok=True)
        win.resize(1280, 720)
        win.show()
        shots = iter(range(1000))
        def snap():
            if not getattr(win, "_finished", False):
                win.grab().save(os.path.join(args.screenshots, f"{next(shots):03d}_{win.step['label']}.png"))
        t = QTimer(win)
        t.timeout.connect(snap)
        t.start(700)
    else:
        win.showMaximized()
    app.exec()


if __name__ == "__main__":
    main()
