# CSI rig fixture

3D-printed fixture that holds the two XIAO ESP32-S3 boards and their FPC antennas in the same geometry every session. It has no metal parts.

- Antennas face each other, **340 mm** face to face, centered **100 mm** above the table.
- Two L-shaped halves (`rx_half`, `tx_half`). Each is a tower with a foot plus half the rail. A dovetail and a printed pin join the halves into one rigid piece.
- Each board press-fits into a pocket on the **back** of its tower, so the board and its cables stay behind the antenna plane and out of the link.
- The rail top is engraved every 5 cm, measured from the RX antenna face. The **15–30 cm gesture zone** has full-width ticks at 15 and 30 cm and a line along the far edge.

| File | What |
|---|---|
| `fixture.scad` | Parametric OpenSCAD source (spacing, antenna height, board/antenna size, tolerances) |
| `stl/rx_half.stl` | Receiver tower + rail 0–180 mm with dovetail tongue (202 × 80 × 118 mm) |
| `stl/tx_half.stl` | Transmitter tower + rail 170–340 mm with dovetail groove (192 × 80 × 118 mm) |
| `stl/pin.stl` | Joint locking pin |

## Print settings

Tuned for an Ender 3-class printer (220 × 220 mm bed). Each half fits the bed lying straight.

- PLA, 0.4 mm nozzle, 0.2 mm layers
- 3 walls, 4 top/bottom layers, 20–25 % infill
- **No supports.** Print every part as exported: the halves stand on their foot with the tower vertical, and the pin lies on its flat side.
- Use a 5 mm brim on the halves. The towers are tall and thin, and the brim stops the corners lifting.
- Print a test of the board pocket first if you're unsure of your printer's tolerance (see Tuning).

## Assembly

1. **Join the halves.** Lower the `tx_half` groove straight down onto the `rx_half` tongue. Push the pin in from the +y side (the side away from the "RX"/"TX" labels) until its head is flush with the rail.
2. **Boards.** Press each bare XIAO into the pocket on the back of its tower. The component side faces out and the USB-C points down. The rim nubs click over the PCB edge. Put the receiver in the RX tower and the transmitter in the TX tower.
3. **Antennas.** Peel the backing and stick each FPC antenna into the shallow rectangle on the front (inner) face of its tower. The lead end goes toward the side with the small channel, and the antenna is centered on the engraved crosshair lines.
   - Both antennas must face each other in the same orientation every time. Don't re-stick them once placed.
4. **U.FL leads.** Run each lead through the channel to the tower edge, around the edge notch, and through the gap in the pocket wall to the board's U.FL connector.
   - Tape any slack flat to the **back** of the tower. Nothing should sit in front of the antenna face.
5. **USB cables.** Plug the USB-C in from below, snap the cable into the clip on the tower back, and lay it in the groove across the foot so it leaves straight out the back.
   - RX goes to the laptop. TX goes to any USB charger or laptop port.
6. **Optional:** stick 10 mm rubber bumpers into the 10 recesses under the feet and rail. They're non-slip and stop the rig rocking.

## Using it

- **Hand height:** the link runs between the two antenna centers, 100 mm above the rail top, at the crosshair on each tower.
- **Gesture zone:** gestures go 15–30 cm from the RX antenna along that line, between the two full-width ticks.
  - Swipe crosses the line once.
  - Push moves toward/away from the RX antenna while staying in the line.
  - Circle is centered on the line.
- **Same placement every session.** Before the first session at a location, put tape marks on the table at the four outer corners of the two feet, and note the location in the session notes.
- **Keep metal away.** Laptops, phones, power bricks and metal desk parts stay at least ~30 cm from the link. Keep them behind the towers, not beside the gesture zone.

## Tuning

Edit the parameters at the top of `fixture.scad`, then re-export the STLs:

```powershell
& "C:\Program Files\OpenSCAD\openscad.com" -o stl/rx_half.stl -D 'part=\"rx_half\"' fixture.scad
```

(Repeat for `tx_half` and `pin`. `part="assembly"` previews the whole rig.)

| Parameter | Default | Change if |
|---|---|---|
| `board_clear` | 0.15 mm | Board won't press in → 0.25; falls out → 0.1 |
| `pin_clear` | 0.15 mm | Pin too tight/loose |
| `joint_clear` | 0.15 mm | Halves won't slide together / joint rattles |
| `ant_l`, `ant_w` | 50 × 18 mm | **Estimated.** Measure your FPC antenna and set these |
| `board_top_z` | 92 mm | U.FL lead too short to reach the antenna → raise (max ≈ 105) |
| `usb_cable_d` | 4.0 mm | Your cable is thicker/thinner at the clip |
| `spacing`, `antenna_h` | 340, 100 mm | Changing the rig geometry. Halves get longer past ~350 mm spacing, so check your bed |

Changing `spacing` or `antenna_h` changes the CSI, so recordings from different settings aren't directly comparable. Note the values in the session notes.
