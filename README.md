# Wi-Fi Gesture Recognition with an ESP32-S3

EECS 635 (Embedded Machine Learning) final project. We detect hand gestures from how they disturb
Wi-Fi signals. The ESP32-S3 measures **Channel State Information (CSI)**, the per-subcarrier
strength of every Wi-Fi packet it receives from a phone hotspot. A hand moving between the phone and
the antenna changes that pattern, and each gesture changes it differently.

```
 phone hotspot [▯] ─────── ~34 cm ─────── [▭] antenna ── XIAO ESP32-S3 ── USB ── laptop
                         ↑ gestures here
```

## Quick start

### 1. One-time setup

Install:
- [VS Code](https://code.visualstudio.com/) + the **PlatformIO IDE** extension
- [Python 3.10+](https://www.python.org/downloads/)

Then, in a terminal in this folder:

```powershell
python -m pip install -r tools/requirements.txt
```

> ⚠️ **Windows:** keep this repo in a folder path **with no spaces**. The ESP32 build tools fail otherwise.

### 2. Wi-Fi details

Copy `firmware/src/secrets.example.h` to `firmware/src/secrets.h` and fill in your phone hotspot's
name and password. `secrets.h` is git-ignored, so your password never gets committed.

Set the hotspot to **2.4 GHz**:
- **iPhone:** Personal Hotspot → turn on **Maximize Compatibility**, and keep that screen open until the board connects.
- **Android:** Hotspot → AP band → **2.4 GHz**.

School Wi-Fi (eduroam) won't work.

### 3. Flash the board

Open the **`firmware`** folder in VS Code (File → Open Folder) and click PlatformIO's **Upload** (→) button
in the bottom bar. The first build downloads the ESP32 toolchain and takes ~5 min; later builds take ~30 s.

### 4. Set up the hardware

- Click the antenna's small round connector onto the board (press straight down until it snaps).
- Tape the flat antenna to a **non-metal** surface, a few cm from the laptop and cables.
- Put the phone **~34 cm** from the antenna with a clear line between them. Tape it down. Don't move either one during a session.
- Sit to the **side** of the phone-antenna line so only your arm reaches in.

### 5. Check it works

```powershell
python tools/csi_live.py COM11
```

Use your board's COM port. The title should show **~100 pkt/s**. Wave your hand between the phone and
antenna: the heatmap should streak and the motion line should spike.

Not sure which port? `record_session.py` finds it automatically, or look in PlatformIO → Devices.

## Recording data (everyone, please!)

```powershell
python tools/record_session.py
```

1. Close `csi_live.py` first, since only one program can use the board at a time.
2. Fill in your name, the location, and the phone-antenna distance.
3. Follow the full-screen colors:

| Screen | Meaning |
|---|---|
| 🟨 Yellow | Get ready: shows the next gesture |
| 🟩 Green | Do the gesture **once** |
| ⬛ Gray | Rest: shows ✓ or ⚠ for the trial you just did |

**Gestures** (relative to the phone-antenna line, ~15–30 cm from the antenna):

| Gesture | How |
|---|---|
| **Swipe** | Hand crosses the line once, sideways |
| **Push** | Hand *in* the line, palm facing the antenna: move toward it and back |
| **Circle** | One circle centered on the line, like drawing on a window between phone and antenna |
| **Stay still** | Hand in your lap (control trial) |

**Keys:** `SPACE` continue · `R` redo last trial · `P` pause · `ESC` save and quit.

A session takes about 5 minutes and saves to `data/<your-name>/<date>_<location>/`. **Commit and push your
session folder** so everyone can use it.

Want to practice without the board? Run `python tools/record_session.py --demo`.

## Analyzing data

```powershell
python tools/analyze_session.py data/jack/20261124_094437_eecs-635-classroom-half-capacity
```

This reports how well gestures are detected and classified, and saves `analysis.png` in the session folder.
Pass several session folders to also test **training on one session and testing on another**:

```powershell
python tools/analyze_session.py data/jack/20261124_091828_home-desk data/jack/20261124_094437_eecs-635-classroom-half-capacity
```

`tools/augment.py` (same arguments) tests whether synthetic data augmentation improves cross-session accuracy.

## What's where

```
firmware/              ESP32-S3 code (PlatformIO + ESP-IDF)
  src/main.c           joins hotspot, pings it at 100 Hz, streams CSI over USB
  src/secrets.h        your Wi-Fi name/password (create from secrets.example.h, not committed)
tools/
  csi_live.py          live heatmap + motion score
  record_session.py    guided, labeled recording sessions
  analyze_session.py   detection / segmentation / classification report
  augment.py           data augmentation experiment
data/<person>/<session>/
  csi.csv              every CSI packet + label + trial id
  trials.csv           trial list with ok / redo / aborted status
  meta.json            who, where, distance, notes
docs/project_log.md    problems, fixes, decisions and results, for the final report
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Build error about whitespace in path | Move the repo to a folder with no spaces in its path |
| Upload fails "No serial data received" | Already handled by `--no-stub` in `platformio.ini`. If it still fails, hold **BOOT**, tap **RESET**, release **BOOT**, then upload |
| 0 pkt/s, log shows `reason 201` | Board can't see the hotspot: turn it on, set to 2.4 GHz |
| Log shows `reason 15` or `204` | Wrong Wi-Fi password in `secrets.h` |
| "Port busy" / can't open COM port | Close `csi_live.py`, the VS Code serial monitor, or another recorder |
| Plot window doesn't open | `python -m pip install PyQt6` |

## Data size

Each session is about 10 MB. Keeping data in the repo is fine up to a few hundred MB. If we get past ~30
sessions, move `data/` to Git LFS or a shared drive.
