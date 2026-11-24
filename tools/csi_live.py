"""Live CSI viewer + recorder for the ESP32-S3 csi_capture firmware.

    python tools/csi_live.py COM5                       # just watch
    python tools/csi_live.py COM5 --record data/wave.csv  # watch and save

Top plot: amplitude heatmap (time x subcarrier). A hand wave shows up as
vertical streaks / color changes across many subcarriers.
Bottom plot: "motion score" = rolling std of amplitude, averaged over
subcarriers. Flat when the room is still, spikes when something moves.

Close the plot window to stop. Requires: pip install pyserial numpy matplotlib
"""

import argparse
import collections
import threading
import time

import re

import numpy as np
import serial
import matplotlib

matplotlib.use("QtAgg")  # this Python has no Tk; needs PyQt6
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

N_SUB = 64          # L-LTF subcarriers
HISTORY = 400       # packets shown (~4 s at 100 Hz)
MOTION_WIN = 20     # packets in the rolling-std window

# L-LTF null subcarriers (DC + guard bands) carry no signal; hide them.
VALID = np.r_[1:27, 38:64]
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def parse_line(line: str):
    """Return (seq, esp_us, rssi, amplitude[64]) or None."""
    if not line.startswith("CSI,"):
        return None
    parts = line.strip().split(",")
    if len(parts) != 9:
        return None
    try:
        raw = np.frombuffer(bytes.fromhex(parts[8]), dtype=np.int8).astype(np.float32)
    except ValueError:
        return None
    if raw.size < 2 * N_SUB:
        return None
    imag, real = raw[0 : 2 * N_SUB : 2], raw[1 : 2 * N_SUB : 2]
    return int(parts[1]), int(parts[2]), int(parts[3]), np.hypot(real, imag)


def reader(port, baud, buf, stats, record_path, stop):
    out = open(record_path, "w", buffering=1) if record_path else None
    if out:
        out.write("host_time,seq,esp_us,rssi,rate,sig_mode,first_word_invalid,len,data\n")
    with serial.Serial(port, baud, timeout=1) as ser:
        ser.reset_input_buffer()
        while not stop.is_set():
            line = ser.readline().decode("ascii", errors="ignore")
            if not line:
                continue
            parsed = parse_line(line)
            if parsed is None:
                text = ANSI.sub("", line).strip()
                # Skip the half line we join mid-stream on startup.
                if text and not re.fullmatch(r"[0-9a-f,]+", text):
                    print("[esp]", text)
                continue
            if out:
                out.write(f"{time.time():.6f},{line[4:].strip()}\n")
            buf.append(parsed)
            stats["count"] += 1
    if out:
        out.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", help="serial port, e.g. COM5")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--record", help="CSV file to save raw CSI lines to")
    args = ap.parse_args()

    buf = collections.deque(maxlen=HISTORY)
    stats = {"count": 0}
    stop = threading.Event()
    t = threading.Thread(target=reader, args=(args.port, args.baud, buf, stats, args.record, stop), daemon=True)
    t.start()

    fig, (ax_hm, ax_m) = plt.subplots(2, 1, figsize=(10, 7), height_ratios=[2, 1])
    hm = ax_hm.imshow(np.zeros((len(VALID), HISTORY)), aspect="auto", origin="lower",
                      cmap="viridis", interpolation="nearest")
    ax_hm.set_ylabel("subcarrier (nulls removed)")
    ax_hm.set_xticks([])
    (motion_line,) = ax_m.plot([], [])
    ax_m.set_xlim(0, HISTORY)
    ax_m.set_xlabel("packet")
    ax_m.set_ylabel("motion score")
    last = {"t": time.time(), "count": 0}

    def update(_):
        if len(buf) < MOTION_WIN:
            return hm, motion_line
        snap = list(buf)
        amp = np.stack([s[3][VALID] for s in snap])  # (T, sub)
        img = np.zeros((len(VALID), HISTORY))
        img[:, -amp.shape[0]:] = amp.T
        hm.set_data(img)
        hm.set_clim(np.percentile(amp, 2), np.percentile(amp, 98))

        # Rolling std over time per subcarrier, normalized by mean, averaged.
        win = np.lib.stride_tricks.sliding_window_view(amp, MOTION_WIN, axis=0)
        score = (win.std(axis=-1) / (win.mean(axis=-1) + 1e-6)).mean(axis=1)
        motion_line.set_data(np.arange(HISTORY - len(score), HISTORY), score)
        ax_m.set_ylim(0, max(0.05, score.max() * 1.2))

        now = time.time()
        if now - last["t"] > 1:
            rate = (stats["count"] - last["count"]) / (now - last["t"])
            last.update(t=now, count=stats["count"])
            ax_hm.set_title(f"CSI amplitude   {rate:.0f} pkt/s   rssi {snap[-1][2]} dBm"
                            + (f"   recording -> {args.record}" if args.record else ""))
        return hm, motion_line

    _anim = FuncAnimation(fig, update, interval=50, cache_frame_data=False)
    plt.tight_layout()
    plt.show()
    stop.set()
    t.join(timeout=2)


if __name__ == "__main__":
    main()
