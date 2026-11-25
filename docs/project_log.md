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
| 17 | 2026-11-24 | Every tool hard-coded the 128-byte, 52-subcarrier L-LTF layout, so 40 MHz or HT-LTF packets would be dropped or misread | Packet layout was duplicated in four scripts | One shared decoder, `tools/csi_format.py`, keyed on payload length (128 / 256 / 384 bytes) using the 802.11 subcarrier layout; it returns subcarriers in frequency order. Sessions that mix packet types keep the most common one. L-LTF layout verified on recorded data: all 12 dropped slots are exactly 0 | Re-analysis of both sessions matches within noise (classroom still 88% / 94%). The HT-LTF layouts are still untested on hardware |
| 18 | 2026-11-24 | Both 40 MHz firmware builds failed with "internal compiler error: Segmentation fault" in an ESP-IDF LCD driver file | The compiler crashed (not our code), most likely from memory pressure while an analysis ran at the same time | Retried each build on its own with nothing else running | Both built cleanly: a one-off crash, not a code problem |
| 19 | 2026-11-24 | Apartment session (music-v1, phone hotspot): detection failed (AUC 0.33), still trials flagged as motion 10/16, and only 50 pkt/s instead of 100 | Motion in rests (0.07–0.10) was as high as during gestures and ~2× the empty-room baseline (0.05) for the whole gesture part, so something other than the gestures kept moving the link. RSSI was −17 dBm at a check just before recording and −53 dBm during it, so the phone's position likely changed. The halved rate suggests phone power saving | Phone was fixed on the table, and quiet-period motion showed no correlation with the phone's packet rate or timing gaps (r ≈ 0). The noise was high exactly while gesturing (60–400 s) and quiet in the baseline and at the end, with an RSSI step at ~410 s: body/hand position. The recorder itself told the user to hold the hand at the swipe's start point, which is on the line, during every rest, so a hovering hand disturbed the link between reps. Fix (gesture set `music-v2`): every gesture starts and ends with the hands in the lap (animation includes reach-in and drop-back, windows +1 s), rests are always hands-in-lap, and the recorder warns after 3 rests in a row that are >2× the empty-room baseline (`rest_ratio` logged per trial). Still to verify with a new session; the halved packet rate is unexplained | Fix in, untested |
| 16 | 2026-11-24 | Held-hand (static presence) signal weaker in busy classroom | Rest-period drift is almost as large as the held-hand change (6.5× vs 6.0× baseline noise); hand placement differed between holds | Open — needs marked hand position on a rig | Open |

## Design decisions

| Decision | Why |
|---|---|
| ESP-IDF instead of Arduino framework | Direct control of the CSI config and Wi-Fi driver (`CONFIG_ESP_WIFI_CSI_ENABLED`), USB driver, power-save off |
| L-LTF only (not HT-LTF) by default | Present on every frame type; 128 bytes/packet keeps the serial link well within budget; matches all recordings so far |
| Optional 40 MHz / HT-LTF capture (`tx_40mhz` + `rx_40mhz`, `rx_hotspot_htltf`; 2026-11-24) | 40 MHz doubles the bandwidth (path-delay resolution ~15 m → ~7.5 m, more frequency diversity) and gives 114 usable subcarriers vs 52. Kept as separate PlatformIO environments so 20 vs 40 MHz is a clean comparison. Secondary channel chosen automatically to stay in-band (ch 11 → below). Costs: overlaps more neighboring networks, 3× the serial data (~80 KB/s). Phone hotspots almost always use 20 MHz on 2.4 GHz, so the phone can only test HT-LTF at 20 MHz (56 subcarriers) |
| Wi-Fi power save disabled | Power save makes the radio sleep and drop frames, breaking the 100 Hz sample rate |
| Text lines with hex payload over serial | Easy to parse and debug, robust to resync after corruption; ~30 KB/s is fine for USB |
| Amplitude only (no phase) | ESP32 phase has per-packet random offsets (CFO/timing); amplitude is usable as-is. Phase sanitization is a possible later improvement |
| Phone–antenna distance ~34 cm | Classroom session at 34 cm gave 3.3× gesture/still motion vs 1.8× in the first session; stronger hand effect relative to the room |
| Recordings kept in the git repo (`data/<person>/<session>/`) | Easiest way for the team to share data; ~10 MB per session (~4 MB compressed in git). Move to Git LFS or a shared drive past ~30 sessions. `data/** -diff` in `.gitattributes` avoids huge text diffs |
| Switch from phone hotspot to a second ESP32-S3 as transmitter (2026-11-24) | Phone changes data rate, TX power and antenna selection on its own, and its ping replies have OS timing jitter; each of those shifts CSI between sessions (suspected contributor to the cross-session drop, #14). An ESP32 transmitter gives a fixed rate, power, channel and PHY mode, no network to join or drop, and a self-contained rig for demo day. Phone mode kept as `rx_hotspot` for comparison |
| ESP-NOW broadcast, 100 Hz, channel 11, HT20 MCS0, 13 dBm | Connectionless (no pairing), any number of receivers can listen. 100 Hz keeps recordings comparable with the phone sessions and the tools' window sizes. MCS0 is the most robust rate and is an 802.11n frame, so HT-LTF CSI is available later |
| Transmitter puts a sequence number in every packet | Receiver logs the transmitter's counter as `seq`: gaps measure packet loss exactly, and recordings from several receivers can later be aligned packet-by-packet without synchronized clocks |
| Receiver locks onto the first transmitter carrying our magic marker | No MAC addresses to configure per board; another team's rig on the same channel is ignored once locked. The locked MAC is printed |
| One firmware codebase, three PlatformIO environments (`tx`, `rx`, `rx_hotspot`) | Shared USB/CSI code stays in one place; teammates pick the role from VS Code's environment selector |
| Single rig with two boards first (not 2 rigs or 1 tx + 3 rx) | Get a clean single-link baseline before adding receivers; the rig isn't built yet |
| Gesture set `music-v1` (2026-11-24): swipe = next, swipe + back = previous, palm hold = pause/resume, still, free movement | Picked a real use case (touch-free music control). Left vs right swipe was rejected: with one link the geometry is mirror-symmetric (about the line and about its midpoint), so the two directions give near-identical CSI. Swipe vs swipe-and-back differ in *structure* (one motion hump vs two with a dip at the turnaround), which doesn't depend on direction. Palm uses the strong static-hand signal. Swipe direction alternates and is logged, so the symmetry claim can be tested on real data. Old sessions are tagged `v0` and analyzed with their own gestures |
| Each trial recorded at one of three paces (fast/normal/slow; palm short/medium/long hold), shown on screen | A model that only sees one speed fails on other people's speeds; varying pace in the data covers it |
| Free-movement block (`other`, default 45 s) in every session | Gives real non-gesture motion (walking, reaching, sitting down) so the model can learn to ignore it. Previously ~27% of detector events were non-gestures |
| Blocked recording order (all reps of one gesture, then the next), with gesture and pace order shuffled every session | Much faster: one instruction screen per gesture instead of per trial. Risk: signal drift over a session lines up with gesture order, inflating within-session accuracy. Shuffling the order per session plus judging the model by cross-session tests counters that |
| Recorder shows an animated top-view diagram, timed exactly to the recording window | The user mirrors a moving hand instead of reading text. During rest, the next path and the hand's start point are shown with a countdown, so there's no separate "get ready" step. Built after two text-only layouts were hard to follow |
| Recorder chains sessions (SPACE after "Session saved") and `--quick` reuses the last setup | Data collection speed; each session still gets its own folder and metadata |
| Gestures defined relative to the phone–antenna line | Swipe crosses it once, push stays in it, circle crosses it repeatedly → distinct temporal signatures |
| 3D-printed rig fixture (`hardware/fixture/`, 2026-11-24) | Inconsistent placement of the transmitter, antennas and hand is a suspected cause of the cross-session accuracy drop (#14), so the fixture fixes the geometry: antennas face each other 340 mm apart at 100 mm height, stuck into locating recesses. It is one rigid printed rail in two halves (dovetail + printed pin) because 34 cm exceeds a 220 mm bed. Boards press-fit on the back of each tower so boards and cables sit behind the antenna plane. The 15–30 cm gesture zone is engraved on the rail. The fixture has no metal at all (no screws or inserts), so it adds nothing that reflects near the link. Parametric OpenSCAD so a second identical rig is a reprint |

## Experiments

### Sessions

| Session | Where | Distance | Trials (ok) | RSSI | Notes |
|---|---|---|---|---|---|
| `data/jack/20261124_091828_home-desk` | Home, desk | not recorded | 8 × swipe/push/circle/none, 3 holds | −53 dBm | Old terminal recorder; beeps inaudible → poor timing |
| `data/jack/20261124_094437_eecs-635-classroom-half-capacity` | EECS 635 classroom, ~half full | 34 cm | 8 × each, 3 holds, 0 redos | −45 dBm | Visual recorder |
| `data/jack/20261124_180510_apartment-alone` | Apartment, alone | 34 cm | 16 × swipe/swipe_back/palm/none, 45 s other | −53 dBm | First `music-v1` session (phone hotspot). Ran at only **50 pkt/s** (half rate). Detection AUC 0.33: "still" trials moved as much as gestures (×0.9). 3 gestures onset-aligned: 58% logreg / **62% kNN** / 54% forest; + none + other: 40–49% |
| `data/jack/20261124_180510_apartment-alone` | Apartment, alone | 34 cm (entered) | music-v1: 16 × swipe / swipe+back / palm / still, 45 s free movement, 0 redos | −53 dBm | Animated recorder, phone hotspot. Only 50 pkt/s; link disturbed throughout (problem #19). Within-session: 3 gestures 54–62%, palm 13/16 correct; swipe direction (L→R vs R→L) at chance, 50% |

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

## Proposal (2026-11-24)

Short blog-style proposal page at `docs/proposal/index.html`; figures regenerated by `python tools/proposal_figures.py <recorder screenshot folder>` (screenshots from `record_session.py --autopilot --demo --screenshots <dir>`). Uses the classroom session for the CSI example, the apartment session for per-gesture heatmaps, and the numbers above for the results chart.

## Open questions / next steps

1. Fixed rig (phone + antenna at a set 34 cm, marked hand zone) and 3–4 sessions across times and teammates → fair leave-one-session-out test.
2. Baseline-relative inputs (subtract a quiet-period profile per session) and a short calibration step at startup.
3. Add a "non-gesture motion" class (people walking by, arm resets) so the live detector's false events get rejected.
4. Small 1D CNN on raw onset-aligned windows (52 subcarriers × 200 samples) with augmentation; check size/latency for on-device inference on the ESP32-S3.
