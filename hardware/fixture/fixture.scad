// EECS 635 Wi-Fi CSI gesture rig fixture
// Two Seeed XIAO ESP32-S3 boards with flexible FPC antennas facing each other.
//
// Coordinates: X runs along the tx-rx line. The RX antenna face is at x = 0 and
// the TX antenna face at x = spacing. Y is across the rail (+y is the side the
// U.FL leads wrap around). Z is up from the table.
//
// Parts (set `part`, or use -D part="\"rx_half\"" on the command line):
//   assembly : both halves + pin in place (preview only)
//   rx_half  : receiver tower + rail up to the joint, with the dovetail tongue
//   tx_half  : transmitter tower + rail from the joint, with the dovetail groove
//   pin      : locking pin for the joint
// All parts print in the orientation they are modelled in (no supports).
// No metal anywhere: everything is printed, press-fit or adhesive.

part = "assembly"; // [assembly, rx_half, tx_half, pin]

/* [Geometry] */
spacing    = 340;   // antenna face to antenna face (mm)
antenna_h  = 100;   // antenna centre height above the table (mm)

tower_t    = 6;     // tower plate thickness
tower_w    = 60;    // tower width (across the rail)
tower_h    = 118;   // tower height

foot_back  = 22;    // foot extends this far behind the antenna face
foot_front = 40;    // ...and this far in front of it
foot_w     = 80;    // foot width (anti-tip)
foot_t     = 6;     // foot plate thickness

rail_w     = 30;    // rail width
rail_t     = 10;    // rail thickness

rib_t      = 3;     // gusset thickness
rib_top    = 60;    // gusset height on the tower

/* [Antenna (estimated; measure yours)] */
ant_l      = 50;    // FPC antenna length (horizontal on the plate)
ant_w      = 18;    // FPC antenna width (vertical on the plate)
ant_recess = 0.6;   // depth of the locating recess
ant_lead_w = 4;     // channel for the antenna's U.FL lead, toward +y edge

/* [XIAO ESP32-S3 board] */
board_l     = 21.0; // along the USB axis (USB-C points down)
board_w     = 17.5;
board_pcb   = 1.2;
board_clear = 0.15; // per side; raise to 0.25 if it won't press in
board_top_z = 92;   // height of the board's top (non-USB) edge
pocket_wall = 2;
nub         = 0.4;  // snap nub protrusion over the PCB edge
usb_cut_w   = 13;   // opening in the bottom wall for the USB-C plug
top_gap_w   = 8;    // opening in the top wall (lead / finger to pry out)
side_gap    = 5;    // gaps at both ends of the +y wall for the U.FL lead

/* [USB cable] */
usb_cable_d = 4.0;  // cable diameter at the clip
usb_clip_z  = 22;   // bottom of the cable clip ring
usb_clip_h  = 8;

/* [Joint] */
joint_x     = spacing / 2;
tongue_len  = 10;
tongue_neck = 12;
tongue_end  = 18;
joint_clear = 0.15; // per side
pin_d       = 4;
pin_clear   = 0.15; // hole = pin_d + pin_clear (snug press)
pin_head_d  = 7;
pin_head_t  = 1.5;

/* [Markings] */
tick_every = 50;    // tick spacing (mm from the RX antenna face)
zone_start = 150;   // gesture zone start (mm from RX antenna)
zone_end   = 300;   // gesture zone end
engrave    = 0.6;   // engraving depth
font       = "Liberation Sans:style=Bold";

/* [Feet] */
bumper_d     = 10.5; // recess for stick-on rubber bumpers (optional)
bumper_depth = 1.0;

$fn = 48;
eps = 0.01;

// ---------------------------------------------------------------- derived
pocket_y  = board_w / 2 + board_clear;            // half-width of pocket
pocket_z0 = board_top_z - board_l - board_clear;  // pocket bottom
pocket_z1 = board_top_z + board_clear;            // pocket top
nub_r     = 0.5;
frame_h   = board_pcb + board_clear + 2 * nub_r;  // frame height off tower back
cable_x   = -tower_t - board_pcb - 1.6;           // USB-C centre line (approx)

// ============================================================ tower (local)
// Built for the RX end: antenna face at x = 0 facing +x, tower behind it.
// The TX tower is this mirrored about x = spacing / 2.

module rib() {
    rotate([90, 0, 0])
        linear_extrude(rib_t, center = true)
            polygon([[-tower_t + eps, foot_t - eps], [-foot_back, foot_t - eps],
                     [-tower_t + eps, rib_top]]);
}

module pocket_frame() {
    difference() {
        translate([-tower_t - frame_h, -pocket_y - pocket_wall, pocket_z0 - pocket_wall])
            cube([frame_h + eps, 2 * (pocket_y + pocket_wall),
                  pocket_z1 - pocket_z0 + 2 * pocket_wall]);
        // board cavity
        translate([-tower_t - frame_h - 1, -pocket_y, pocket_z0])
            cube([frame_h + 1, 2 * pocket_y, pocket_z1 - pocket_z0]);
        // USB-C opening, bottom wall
        translate([-tower_t - frame_h - 1, -usb_cut_w / 2, pocket_z0 - pocket_wall - 1])
            cube([frame_h + 1, usb_cut_w, pocket_wall + 2]);
        // top wall opening
        translate([-tower_t - frame_h - 1, -top_gap_w / 2, pocket_z1 - 1])
            cube([frame_h + 1, top_gap_w, pocket_wall + 2]);
        // +y wall gaps at both ends for the U.FL lead
        for (z = [pocket_z0 - pocket_wall - 1, pocket_z1 - side_gap])
            translate([-tower_t - frame_h - 1, pocket_y - 1, z])
                cube([frame_h + 1, pocket_wall + 2, side_gap + 1]);
    }
    // snap nubs on the long walls, just above the PCB
    nub_len = 8;
    for (s = [-1, 1])
        translate([-tower_t - board_pcb - board_clear - nub_r,
                   s * (pocket_y + nub_r - nub),
                   (pocket_z0 + pocket_z1) / 2 - nub_len / 2])
            cylinder(r = nub_r, h = nub_len, $fn = 16);
}

module usb_clip() {
    ri = usb_cable_d / 2 + 0.2;
    ro = ri + 1.6;
    difference() {
        union() {
            translate([cable_x, 0, usb_clip_z]) cylinder(r = ro, h = usb_clip_h);
            // stem to the tower back
            translate([cable_x, -ro + 0.5, usb_clip_z])
                cube([-tower_t - cable_x + eps, 2 * ro - 1, usb_clip_h]);
        }
        translate([cable_x, 0, usb_clip_z - 1]) cylinder(r = ri, h = usb_clip_h + 2);
        // snap-in opening facing away from the tower
        translate([cable_x - ro - 1, -0.375 * usb_cable_d, usb_clip_z - 1])
            cube([ro + 1, 0.75 * usb_cable_d, usb_clip_h + 2]);
    }
}

module tower_solid() {
    translate([-tower_t, -tower_w / 2, 0]) cube([tower_t, tower_w, tower_h]);
    translate([-foot_back, -foot_w / 2, 0]) cube([foot_back + foot_front, foot_w, foot_t]);
    for (s = [-1, 1]) translate([0, s * (tower_w / 2 - rib_t / 2), 0]) rib();
    pocket_frame();
    usb_clip();
}

module tower_cuts() {
    // antenna locating recess on the front face
    translate([-ant_recess, -ant_l / 2 - 0.5, antenna_h - ant_w / 2 - 0.5])
        cube([ant_recess + 1, ant_l + 1, ant_w + 1]);
    // lead channel from the recess to the +y edge
    translate([-ant_recess, 0, antenna_h - ant_lead_w / 2])
        cube([ant_recess + 1, tower_w, ant_lead_w]);
    // centre marks: vertical above the recess, horizontal on the -y side
    translate([-engrave, -0.4, antenna_h + ant_w / 2]) cube([engrave + 1, 0.8, tower_h]);
    translate([-engrave, -tower_w, antenna_h - 0.4]) cube([engrave + 1, tower_w, 0.8]);
    // notch across the +y edge where the lead wraps from the board to the front
    translate([-tower_t - 1, tower_w / 2 - 2, board_top_z - 5])
        cube([tower_t + 2, 3, 4]);
    // cable groove across the foot behind the tower
    translate([-foot_back - 1, -(usb_cable_d + 0.5) / 2, foot_t - 2.5])
        cube([foot_back - tower_t + 1 + eps, usb_cable_d + 0.5, 3]);
    // bumper recesses under the foot corners
    for (x = [-foot_back + 7, foot_front - 7], y = [-foot_w / 2 + 7, foot_w / 2 - 7])
        translate([x, y, -eps]) cylinder(d = bumper_d, h = bumper_depth + eps);
}

module tower_rx() { difference() { tower_solid(); tower_cuts(); } }
module tower_tx() { translate([spacing, 0, 0]) mirror([1, 0, 0]) tower_rx(); }

// ================================================================== joint
module tongue_2d(grow = 0) {
    offset(delta = grow)
        polygon([[joint_x - 1, -tongue_neck / 2], [joint_x + tongue_len, -tongue_end / 2],
                 [joint_x + tongue_len, tongue_end / 2], [joint_x - 1, tongue_neck / 2]]);
}

module pin_hole() {
    translate([joint_x + tongue_len / 2, 0, rail_t / 2])
        rotate([90, 0, 0]) cylinder(d = pin_d + pin_clear, h = rail_w + 2, center = true);
}

// ================================================================ markings
module markings() {
    // ticks every tick_every mm, measured from the RX antenna face
    for (x = [tick_every : tick_every : spacing - tick_every]) {
        full = (x == zone_start || x == zone_end);
        translate([x - 0.4, full ? -rail_w / 2 - 1 : -rail_w / 2 - 1, rail_t - engrave])
            cube([0.8, full ? rail_w + 2 : 11, engrave + 1]);
        translate([x, -3, rail_t - engrave])
            linear_extrude(engrave + 1)
                text(str(x / 10), size = 5, font = font, halign = "center");
    }
    // gesture zone bracket along the far edge of the rail
    translate([zone_start, rail_w / 2 - 4, rail_t - engrave])
        cube([zone_end - zone_start, 0.8, engrave + 1]);
    // end labels on the feet
    translate([foot_front / 2, -(foot_w + rail_w) / 4, foot_t - engrave])
        linear_extrude(engrave + 1)
            text("RX", size = 8, font = font, halign = "center", valign = "center");
    translate([spacing - foot_front / 2, -(foot_w + rail_w) / 4, foot_t - engrave])
        linear_extrude(engrave + 1)
            text("TX", size = 8, font = font, halign = "center", valign = "center");
    // bumper recesses under the rail near the joint
    for (x = [joint_x - 50, joint_x + 50])
        translate([x, 0, -eps]) cylinder(d = bumper_d, h = bumper_depth + eps);
}

// =================================================================== halves
module rx_half() {
    difference() {
        union() {
            tower_rx();
            translate([0, -rail_w / 2, 0]) cube([joint_x, rail_w, rail_t]);
            linear_extrude(rail_t) tongue_2d();
        }
        markings();
        pin_hole();
    }
}

module tx_half() {
    difference() {
        union() {
            tower_tx();
            translate([joint_x, -rail_w / 2, 0]) cube([spacing - joint_x, rail_w, rail_t]);
        }
        translate([0, 0, -1]) linear_extrude(rail_t + 2) tongue_2d(joint_clear);
        markings();
        pin_hole();
    }
}

module pin() {
    // printed lying down; bottom flattened 0.4 mm so it sits on the bed
    flat = 0.4;
    translate([0, 0, pin_head_d / 2 - flat])
        intersection() {
            rotate([0, 90, 0]) union() {
                cylinder(d = pin_head_d, h = pin_head_t);
                cylinder(d = pin_d, h = pin_head_t + rail_w);
                translate([0, 0, pin_head_t + rail_w])
                    cylinder(d1 = pin_d, d2 = pin_d - 1, h = 0.5);
            }
            translate([-1, -pin_head_d, -pin_head_d / 2 + flat])
                cube([rail_w + pin_head_t + 3, 2 * pin_head_d, pin_head_d]);
        }
}

// ================================================================== output
if (part == "rx_half") rx_half();
else if (part == "tx_half") tx_half();
else if (part == "pin") pin();
else {
    color("SteelBlue") rx_half();
    color("Orange") tx_half();
    // pin inserted from the +y side (preview only, round)
    color("Gray")
        translate([joint_x + tongue_len / 2, rail_w / 2 + pin_head_t, rail_t / 2])
            rotate([90, 0, 0]) {
                cylinder(d = pin_head_d, h = pin_head_t);
                cylinder(d = pin_d, h = pin_head_t + rail_w);
            }
}
