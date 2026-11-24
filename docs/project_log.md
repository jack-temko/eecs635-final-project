# Wi-Fi CSI Gesture Recognition — Project Log

Running record of problems, solutions, design decisions and results, for the final report.
Newest entries go at the bottom of each section. Dates are when the work was done.

## System overview

| Part | What it is |
|---|---|
| Hardware | Seeed XIAO ESP32-S3 + external flexible PCB antenna (U.FL); phone hotspot as the Wi-Fi access point |
| Firmware | `firmware/` — ESP-IDF 5.3 via PlatformIO. Joins the hotspot, pings the gateway at 100 Hz, captures CSI of every reply from the AP, streams it over native USB |
| CSI format | L-LTF only: 64 subcarriers × (imag, real) int8 = 128 bytes/packet; 52 data subcarriers after dropping DC/guard nulls |
| Host tools | `tools/csi_live.py` (live view), `tools/record_session.py` (guided labeled recording), `tools/analyze_session.py` (feasibility analysis), `tools/augment.py` (augmentation experiment) |

**Why a single board works:** CSI is measured on frames the ESP *receives*. Pinging the gateway makes the phone send ~100 replies/s, so the ESP gets a steady stream of frames from a fixed transmitter without a second device. CSI is filtered to the AP's MAC so other networks' traffic is ignored.

## Problems and solutions

| # | Date | Problem | Cause | Solution | Outcome |
|---|---|---|---|---|---|
| 1 | 2026-11-24 | First PlatformIO build hung ~15 min | Package download stalled (`tool-mconf`, connections stuck in CLOSE_WAIT) | Killed and restarted the build | Toolchain installed normally on retry |
| 2 | 2026-11-24 | Build error: "whitespace character in project paths" | ESP-IDF's CMake build doesn't support spaces in paths (`EECS 635 - Embedded Machine Learning`) | Temporary `subst P:` drive, then renamed folder to `EECS635-Embedded-Machine-Learning` | Builds from normal path |
| 3 | 2026-11-24 | `MACSTR` undefined | Moved to `esp_mac.h` in ESP-IDF 5.x | Added include | — |
| 4 | 2026-11-24 | Upload failed: "No serial data received" after esptool's stub started | XIAO uses the S3's native USB-Serial/JTAG; on Windows it drops out when the flasher stub reconfigures the link | `upload_speed = 115200` and `upload_flags = --no-stub` in `platformio.ini` | Reliable uploads (~10 s for 780 KB) |
| 5 | 2026-11-24 | Only ~40 of 100 CSI frames/s reached the PC; firmware reported drops | Default console writes to USB-Serial/JTAG by polling a 64-byte FIFO, too slow for ~30 KB/s of text | Installed the USB-Serial/JTAG driver with a 16 KB TX buffer and routed stdout through it; CSI callback only copies to a queue, a separate task formats/prints | Full 100 pkt/s, no drops |
| 6 | 2026-11-24 | Board silently kept reconnecting | Hotspot was off; disconnect reason wasn't logged | Firmware logs the disconnect reason (201 = network not found, 15/204 = wrong password) | Problem obvious from the log |
| 7 | 2026-11-24 | Live plot window wouldn't open | This Python install has no Tk, so matplotlib fell back to a non-GUI backend | Installed PyQt6, forced `QtAgg` backend | Works |
| 8 | 2026-11-24 | Couldn't rename the project folder ("access denied") | A leftover `tail -f` log watcher held `build.log` open | Killed the stale process | Lesson: stop log watchers before moving folders |
| 9 | 2026-11-24 | ~0.16% of recorded rows corrupted (54 / 34.6k) | Occasional garbled/merged lines on the serial link | Parsers validate field count and exact payload length (256 hex chars) and skip bad rows | Negligible data loss |
| 10 | 2026-11-24 | Recording prompts used beeps the user couldn't hear; reaction times after the cue ranged 0.16–2.15 s | Audio-only cue, user watching a terminal | Rewrote the recorder as a full-screen color-coded GUI (yellow = get ready, green = go, gray = rest) with live data-rate/RSSI health, per-trial motion check, redo (R) and pause (P) | Classroom session: median reaction 0.41 s, 0 redos needed |
| 11 | 2026-11-24 | Gesture windows misaligned with the actual gesture | Windows cut at the cue, not at the movement | Per-trial onset detection: threshold = trial's own quiet median + 4·MAD (≥1.4× median), first run above it ≥0.15 s. No model needed | 3-gesture accuracy 75% → 88% in classroom session |
| 12 | 2026-11-24 | A fixed motion threshold doesn't hold across a session | Baseline motion level drifts (0.04–0.08 within one session), busy rooms raise it | Label-free stream detector with adaptive floor (rolling 20th percentile over 10 s, trigger at 1.6×) | 88–100% of gestures caught; ~27% of events are non-gesture motion (arm resets, people nearby) |
| 13 | 2026-11-24 | Overall amplitude jumps between packets | Receiver automatic gain control | Normalize each packet by its mean amplitude across subcarriers | Keeps spectral shape, removes gain jumps |
| 14 | 2026-11-24 | Models trained on one session drop to ~50–58% (3 gestures) on another | Different room, distance (unrecorded vs 34 cm), timing quality, hand placement. Changes the static multipath pattern the features see | **Open.** Tried physics-motivated augmentation (see Experiments) — did not help with this little data. Next: fixed rig + more sessions, baseline-relative inputs, calibration | Open |
| 15 | 2026-11-24 | Background-motion augmentation hurt accuracy by 15–20 points | Background pool included "rest" periods, which contain the arm returning from the last gesture, so gesture-like motion was pasted into every class | Restricted pool to empty-room periods, reduced scale to 0.3–1.0× | Still hurt (−5 to −14 points); left out of the default |
| 16 | 2026-11-24 | Held-hand (static presence) signal weaker in busy classroom | Rest-period drift is almost as large as the held-hand change (6.5× vs 6.0× baseline noise); hand placement differed between holds | Open — needs marked hand position on a rig | Open |

## Design decisions

| Decision | Why |
|---|---|
| ESP-IDF instead of Arduino framework | Direct control of the CSI config and Wi-Fi driver (`CONFIG_ESP_WIFI_CSI_ENABLED`), USB driver, power-save off |
| L-LTF only (not HT-LTF) | Present on every frame type; 128 bytes/packet keeps the serial link well within budget |
| Wi-Fi power save disabled | Power save makes the radio sleep and drop frames, breaking the 100 Hz sample rate |
| Text lines with hex payload over serial | Easy to parse and debug, robust to resync after corruption; ~30 KB/s is fine for USB |
| Amplitude only (no phase) | ESP32 phase has per-packet random offsets (CFO/timing); amplitude is usable as-is. Phase sanitization is a possible later improvement |
| Phone–antenna distance ~34 cm | Classroom session at 34 cm gave 3.3× gesture/still motion vs 1.8× in the first session; stronger hand effect relative to the room |
| Recordings kept in the git repo (`data/<person>/<session>/`) | Easiest way for the team to share data; ~10 MB per session (~4 MB compressed in git). Move to Git LFS or a shared drive past ~30 sessions. `data/** -diff` in `.gitattributes` avoids huge text diffs |
| Gestures defined relative to the phone–antenna line | Swipe crosses it once, push stays in it, circle crosses it repeatedly → distinct temporal signatures |

## Experiments

### Sessions

| Session | Where | Distance | Trials (ok) | RSSI | Notes |
|---|---|---|---|---|---|
| `data/jack/20261124_091828_home-desk` | Home, desk | not recorded | 8 × swipe/push/circle/none, 3 holds | −53 dBm | Old terminal recorder; beeps inaudible → poor timing |
| `data/jack/20261124_094437_eecs-635-classroom-half-capacity` | EECS 635 classroom, ~half full | 34 cm | 8 × each, 3 holds, 0 redos | −45 dBm | Visual recorder |

### Within-session results (leave-one-trial-out)

| Metric | Home | Classroom |
|---|---|---|
| Detection AUC (gesture vs still) | 0.95 | 0.99 |
| Gesture / still motion ratio | 1.8× | 3.3× |
| Held hand vs baseline noise | 18× | 6.5× |
| 3 gestures, beep-aligned (chance 33%) | 71% | 75% |
| 3 gestures, onset-aligned | 71% | **88%** (random forest) |
| 4 classes incl. none, onset-aligned (chance 25%) | 81% | **94%** (random forest) |

Features: 10-bin motion profile, 10-bin deviation-from-start profile, motion std in 8 subcarrier bands, max/mean motion, zero-crossings of first principal component (36 total). Classifiers: logistic regression, 3-NN, random forest (300 trees).

### Cross-session results (train on one, test on the other)

| Train → Test | 3 gestures | 4 classes |
|---|---|---|
| Home → Classroom | 54% | 68% |
| Classroom → Home | 58% | 68% |
| Pooled, leave-one-out over both | 65–71% | — |

Per-session feature standardization (a stand-in for calibration) did not help (46–58%).

### Augmentation experiment (`tools/augment.py`)

Each augmentation imitates a real source of variation: smooth random gain across subcarriers (new room's multipath), real empty-room background motion (busy room), dynamic-part scaling (distance / hand size), time warp 0.8–1.25× (speed), ±0.25 s shift (reaction time), Gaussian noise. 15 augmented copies per training trial.

| Train → Test, 3 gestures | None | Room gain | Background | Strength | Time warp | Time shift | Noise | All |
|---|---|---|---|---|---|---|---|---|
| Home → Classroom | 54% | 56% | 40%* | 38% | 46% | 42% | 51% | 51% |
| Classroom → Home | 58% | 56% | 51%* | 54% | 58% | 58% | 57% | 57% |

\*after fix #15. **Conclusion:** no augmentation helped with 2 sessions × 24 trials and handcrafted features. Each test trial is ~4 points, so differences under ~10 points are noise. The gap between these two sessions is mostly setup/timing differences the augmentations don't model. Revisit once there are ≥4 sessions on a fixed rig and a model trained on raw windows (1D CNN), which is where augmentation usually pays off.

## Open questions / next steps

1. Fixed rig (phone + antenna at a set 34 cm, marked hand zone) and 3–4 sessions across times and teammates → fair leave-one-session-out test.
2. Baseline-relative inputs (subtract a quiet-period profile per session) and a short calibration step at startup.
3. Add a "non-gesture motion" class (people walking by, arm resets) so the live detector's false events get rejected.
4. Small 1D CNN on raw onset-aligned windows (52 subcarriers × 200 samples) with augmentation; check size/latency for on-device inference on the ESP32-S3.
