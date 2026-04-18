# GX-01 Case Hardware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the physical GX-01 case: a hybrid FDE-PETG shell + bronze-anodized aluminum top/back plates, housing the single-chamber stacked assembly (X1100 + Pi 5 + X1207 + AI HAT+ 2 + LC29H + custom adapter HAT) with two 40 mm fans, validated against the 67 °C bare-board thermal baseline.

**Architecture:** OpenSCAD parametric shell → PrusaSlicer → 3D print; FreeCAD / KiCad for aluminum DXF generation → send to CNC machinist; physical assembly per the spec's 17-step sequence; empirical thermal validation using Linux userspace temperature sensors.

**Tech Stack:** OpenSCAD (text-based parametric CAD), PrusaSlicer (FDM slicing), FreeCAD 1.x (DXF viewing + DXF generation as fallback), `stress-ng` + `glances` + `/sys/class/thermal/` for thermal validation, Noctua NF-A4x10 5V fans.

---

## File structure

- `hardware/gx01-case/parameters.scad` — single source of truth for every dimension
- `hardware/gx01-case/bottom_tray.scad` — lower shell (3 mm bottom + ~45 mm walls, X1100 mount posts, front fan cutout)
- `hardware/gx01-case/top_cap.scad` — upper shell (~50 mm walls, front LCD/LED/button cutouts, rim for aluminum top)
- `hardware/gx01-case/button_cap.scad` — glove-friendly recessed button cap
- `hardware/gx01-case/antenna_dock_insert.scad` — dock insert holding N52 magnets under the aluminum top plate
- `hardware/gx01-case/back_io_shield.scad` — 2D sketch of the back aluminum panel (exports to DXF)
- `hardware/gx01-case/top_plate.scad` — 2D sketch of the top aluminum plate (exports to DXF)
- `hardware/gx01-case/thermal_test.py` — stress + monitor harness
- `hardware/gx01-case/ASSEMBLY.md` — step-by-step build guide with photo checkpoints
- `hardware/gx01-case/README.md` — project overview + run instructions

---

## Phase 0: Prerequisites & measurements

### Task 0.1: Install OpenSCAD + PrusaSlicer

**Files:** none (system install)

- [ ] Run: `sudo apt install -y openscad prusa-slicer`
- [ ] Verify: `openscad --version` and `prusa-slicer --version`
- [ ] Expected: OpenSCAD ≥ 2021.01, PrusaSlicer ≥ 2.6

### Task 0.2: Install FreeCAD (for DXF viewing)

- [ ] Run: `sudo apt install -y freecad`
- [ ] Verify: `freecad --version`

### Task 0.3: Create project directory

**Files:** `hardware/gx01-case/`

- [ ] Run: `mkdir -p hardware/gx01-case`
- [ ] Create empty `hardware/gx01-case/README.md` (will populate in Task 4.8)

### Task 0.4: Measure current assembled stack (baseline, pre-X1100)

**Files:** `hardware/gx01-case/measurements.md`

Use digital calipers. Record every value in `measurements.md` with a date.

- [ ] Measure Pi 5 → X1207 vertical offset (distance from Pi PCB top surface to X1207 PCB bottom surface). Expected: ~9–12 mm.
- [ ] Measure X1207 → AI HAT+ 2 vertical offset. Expected: ~8–10 mm.
- [ ] Measure AI HAT+ 2 → LC29H vertical offset. Expected: ~10–12 mm. NOTE: AI HAT+ has the Hailo heatsink on top; measure from top of heatsink to bottom of LC29H.
- [ ] Measure 21700 cell's position relative to X1207 PCB: distance it extends past the short edge of the Pi, and its height above/below the X1207 PCB plane.
- [ ] Record: **total stack height from Pi PCB bottom to top of LC29H connector pins** (before the adapter HAT is added).

### Task 0.5: On X1100 arrival, measure its dimensions

**Files:** `hardware/gx01-case/measurements.md` (append)

- [ ] Measure X1100 PCB outline (expected 107.5 × 85 mm)
- [ ] Measure 4× mounting hole positions (from PCB origin)
- [ ] Measure PCB thickness (expected 1.6 mm)
- [ ] Measure the rigid USB3 bridge's total length (from X1100 USB3 receptacle to the end that plugs into the Pi's USB3-A port)
- [ ] Measure the required standoff height between X1100 and Pi (must clear: SSD thickness 7 mm + USB3 bridge vertical plug height ~9 mm = ~12–15 mm standoff)
- [ ] Record: **X1100 mounting-hole pattern relative to the X1100 PCB's lower-left corner** (X and Y coordinates for each of the 4 holes)

### Task 0.6: Verify LC29H 40-pin passthrough

**Files:** `hardware/gx01-case/measurements.md` (append)

Before ordering aluminum parts OR fab-running a second PCB batch.

- [ ] Remove the LC29H from the stack (unplug cleanly)
- [ ] Place on a bench, female socket facing up
- [ ] With a multimeter in continuity mode, probe EACH of the 14 LCD signal pins from top-side to bottom-side: pins 11, 13, 15, 18, 19, 22, 23, 26, 29, 31, 33, 35, 37, 40 (per the adapter HAT's pin mapping in `hardware/gx01-adapter-pcb/circuit.py`).
- [ ] Also probe continuity on pins 2, 4 (5V), 6, 9, 14, 20, 25, 30, 34, 39 (all GND).
- [ ] Record: **PASS** (all pins continuous top-to-bottom) or list any pins that fail continuity.
- [ ] If any fail: see spec Risk #2 — fallback is to move the adapter HAT between AI HAT+ 2 and LC29H in the stack. Not a disaster.

### Task 0.7: Commit measurements

- [ ] Run: `git add hardware/gx01-case/measurements.md`
- [ ] Commit with message: `docs(case): record physical measurements of assembled stack + X1100`

---

## Phase 1: OpenSCAD parametric shell v0.1

### Task 1.1: Write `parameters.scad` — the single source of dimensional truth

**Files:** `hardware/gx01-case/parameters.scad`

- [ ] Create the file with this content:

```scad
// GX-01 Case — parametric dimensions
// Every dimension used in other .scad files is defined here.
// After Task 0.5 measurements, UPDATE the values marked "MEASURED" below.

// ── External envelope ────────────────────────────────────────────
EXT_L = 125;   // length (parallel to X1100's long edge)
EXT_D = 100;   // depth (parallel to X1100's short edge)
EXT_H = 95;    // height (bottom plate to top plate)

// ── Wall thicknesses ─────────────────────────────────────────────
WALL = 3;           // printed PETG walls
BOTTOM = 3;         // printed bottom plate
TOP_METAL = 2;      // aluminum top plate
BACK_METAL = 2;     // aluminum back panel

// ── Shell split ──────────────────────────────────────────────────
BOTTOM_TRAY_H = 45; // bottom shell piece height
TOP_CAP_H = EXT_H - BOTTOM_TRAY_H - TOP_METAL;

// ── Interior ─────────────────────────────────────────────────────
INT_L = EXT_L - 2*WALL;           // ≈ 119
INT_D = EXT_D - WALL - BACK_METAL; // ≈ 95
INT_H = EXT_H - BOTTOM - TOP_METAL; // ≈ 90

// ── X1100 (the big PCB, sits on bottom) ───────────────────────────
X1100_L = 107.5;              // MEASURED (Task 0.5)
X1100_D = 85;                 // MEASURED
X1100_MOUNT_INSET = 3.5;      // MEASURED — inset from PCB corners to mounting holes
X1100_Z = 5;                  // X1100 PCB sits this high above bottom plate (standoffs)

// ── Pi mount on X1100 ────────────────────────────────────────────
PI_L = 85;
PI_D = 56;
PI_ABOVE_X1100 = 14;          // MEASURED (Task 0.5) — SSD thickness + bridge + clearance

// ── Fan cutouts (40mm Noctua NF-A4x10) ───────────────────────────
FAN_CUTOUT_D = 40;            // 40mm fan hole
FAN_MOUNT_HOLE_SPACING = 32;  // 32mm square mount spacing (NF-A4 standard)
FAN_MOUNT_HOLE_D = 3.3;       // clearance hole for M3

// ── LCD (SparkFun GDM12864H LCD-00710) ───────────────────────────
LCD_WINDOW_W = 58;  // active area visible through window
LCD_WINDOW_H = 31;

// ── Front panel features ─────────────────────────────────────────
LED_HOLE_D = 12;              // 12mm bezel LEDs
BUTTON_HOLE_D = 16;           // momentary pushbutton
BUTTON_RECESS_D = 20;         // recessed bowl around button

// ── Back panel (aluminum insert sized separately) ────────────────
BACK_INSERT_L = EXT_L - 2*WALL - 1; // 0.5mm slop on each side
BACK_INSERT_H = INT_H - 2;          // fit within interior height

// ── Mounting hardware ────────────────────────────────────────────
M3_HEATSET_HOLE_D = 4.2;      // pilot for M3 heat-set insert
M25_HEATSET_HOLE_D = 3.6;     // pilot for M2.5 heat-set insert

// ── Antenna dock (for GPS puck storage on top) ───────────────────
DOCK_RECESS_L = 35;
DOCK_RECESS_W = 30;
DOCK_RECESS_D = 6;            // depth of recess
MAGNET_HOLE_D = 10;           // hole for N52 disc magnet
MAGNET_HOLE_DEPTH = 3;
```

### Task 1.2: Write `bottom_tray.scad`

**Files:** `hardware/gx01-case/bottom_tray.scad`

- [ ] Create with content (use OpenSCAD's difference() + translate()):

```scad
include <parameters.scad>

$fn = 60;  // render quality

module bottom_tray() {
    difference() {
        // Outer shell
        cube([EXT_L, EXT_D, BOTTOM + BOTTOM_TRAY_H]);

        // Carve out interior
        translate([WALL, WALL, BOTTOM])
            cube([INT_L, INT_D + BACK_METAL - WALL, BOTTOM_TRAY_H + 1]);

        // Back wall opening for aluminum back panel (inset so panel sits flush)
        translate([WALL - BACK_METAL, EXT_D - BACK_METAL - 0.1, BOTTOM])
            cube([EXT_L - 2*(WALL - BACK_METAL), BACK_METAL + 0.2, BACK_INSERT_H + 1]);

        // Front fan cutout (at X1100/SSD level ≈ Z = 5 to Z = 15)
        translate([EXT_L/2, -0.1, BOTTOM + 5 + FAN_CUTOUT_D/2])
            rotate([-90, 0, 0])
                cylinder(d = FAN_CUTOUT_D, h = WALL + 0.2);

        // Fan mount holes (4 × M3 clearance)
        for (dx = [-FAN_MOUNT_HOLE_SPACING/2, FAN_MOUNT_HOLE_SPACING/2])
            for (dz = [-FAN_MOUNT_HOLE_SPACING/2, FAN_MOUNT_HOLE_SPACING/2])
                translate([EXT_L/2 + dx, -0.1, BOTTOM + 5 + FAN_CUTOUT_D/2 + dz])
                    rotate([-90, 0, 0])
                        cylinder(d = FAN_MOUNT_HOLE_D, h = WALL + 0.2);
    }

    // Pi/X1100 mount posts (heat-set inserts for M2.5)
    translate([WALL + (INT_L - X1100_L)/2, WALL + (INT_D - X1100_D)/2, BOTTOM])
        x1100_mount_posts();

    // Rim on top edge to mate with top_cap
    // (simple butt-join with 4× screw bosses — M3 heat-set inserts)
    for (corner = [
        [WALL/2, WALL/2],
        [EXT_L - WALL/2, WALL/2],
        [WALL/2, EXT_D - WALL/2],
        [EXT_L - WALL/2, EXT_D - WALL/2],
    ]) {
        translate([corner[0], corner[1], BOTTOM + BOTTOM_TRAY_H - 8])
            difference() {
                cylinder(d = 8, h = 8);
                translate([0, 0, -0.1])
                    cylinder(d = M3_HEATSET_HOLE_D, h = 8.2);
            }
    }
}

module x1100_mount_posts() {
    // 4 posts at X1100 mounting hole positions
    for (corner = [
        [X1100_MOUNT_INSET, X1100_MOUNT_INSET],
        [X1100_L - X1100_MOUNT_INSET, X1100_MOUNT_INSET],
        [X1100_MOUNT_INSET, X1100_D - X1100_MOUNT_INSET],
        [X1100_L - X1100_MOUNT_INSET, X1100_D - X1100_MOUNT_INSET],
    ]) {
        translate([corner[0], corner[1], 0])
            difference() {
                cylinder(d = 6, h = X1100_Z);
                translate([0, 0, -0.1])
                    cylinder(d = M25_HEATSET_HOLE_D, h = X1100_Z + 0.2);
            }
    }
}

bottom_tray();
```

- [ ] Open in OpenSCAD GUI: `openscad hardware/gx01-case/bottom_tray.scad &`
- [ ] Press F6 to render
- [ ] Verify: all features present, no geometry errors
- [ ] Expected: a tray ~125 × 100 × 48 mm with a fan cutout on the front, mount posts on the bottom, and screw bosses in the corners

### Task 1.3: Write `top_cap.scad`

**Files:** `hardware/gx01-case/top_cap.scad`

- [ ] Similar structure to bottom_tray but for the upper ~48 mm, with:
  - Front wall cutouts (LCD window, 3× LED holes, button hole + recess)
  - Rim to receive aluminum top plate
  - Mating screw holes in corners (matching bottom_tray bosses)
  - Back wall is hollow — the aluminum back panel mates through both pieces

- [ ] Full code follows the same pattern as bottom_tray; refer to spec section "Construction → Printed parts" for feature list
- [ ] Render + visual check

### Task 1.4: Write `button_cap.scad`

- [ ] Small glove-friendly cap — ~22 mm OD × 4 mm tall, with a push-fit post underneath
- [ ] Render + STL export

### Task 1.5: Write `antenna_dock_insert.scad`

- [ ] Small rectangular insert that sits under the aluminum top plate's antenna recess
- [ ] Two 10 mm × 3 mm magnet pockets; magnets press-fit and then get CA-glued
- [ ] Render + STL export

### Task 1.6: Export all STLs

- [ ] Run the following commands in `hardware/gx01-case/`:

```bash
openscad -o bottom_tray.stl bottom_tray.scad
openscad -o top_cap.stl top_cap.scad
openscad -o button_cap.stl button_cap.scad
openscad -o antenna_dock_insert.stl antenna_dock_insert.scad
```

- [ ] Verify: all 4 STL files present, each non-zero size
- [ ] Open each in PrusaSlicer visually (`prusa-slicer bottom_tray.stl` etc.) to inspect

### Task 1.7: Slice + print v0.1

- [ ] Open PrusaSlicer
- [ ] Load all 4 STLs onto a single print plate (if printer bed allows) or in separate jobs
- [ ] Printer settings: 0.2 mm layer height, 4 perimeters, 25% gyroid infill, FDE PETG, support-on-build-plate only (minimal supports — the shell is designed to print bottom-down)
- [ ] Slice, export G-code, print
- [ ] Expected print time: 6-10 hours total for all 4 parts at 0.2 mm

### Task 1.8: v0.1 fit check

- [ ] Dry-fit the X1100 onto the bottom_tray mount posts — does it seat flat? Do mounting screws align?
- [ ] Dry-fit the Pi 5 on top with 14 mm standoffs — does the USB3 bridge reach cleanly? Clearance from SSD underneath?
- [ ] Test-fit the assembled stack into the full shell (both pieces)
- [ ] Record issues in `measurements.md` (expected to need ~3-5 mm adjustments in at least one dimension)
- [ ] Commit current state: `git add hardware/gx01-case/ && git commit -m "feat(case): OpenSCAD shell v0.1 + first fit check notes"`

### Task 1.9: Iterate to v0.2

- [ ] Update `parameters.scad` based on fit-check feedback
- [ ] Re-export STLs, re-slice, re-print only the pieces that changed
- [ ] Second fit check — should be clean
- [ ] Commit v0.2 parameters + STLs: `git commit -m "feat(case): OpenSCAD shell v0.2 after fit check"`

---

## Phase 2: CNC aluminum part design

### Task 2.1: Write `back_io_shield.scad`

**Files:** `hardware/gx01-case/back_io_shield.scad`

- [ ] Create 2D sketch:

```scad
include <parameters.scad>

// 2D projection of the back I/O shield for DXF export
// Expected exterior: BACK_INSERT_L × BACK_INSERT_H mm

projection(cut = false) back_io_shield_3d();

module back_io_shield_3d() {
    difference() {
        cube([BACK_INSERT_L, BACK_METAL, BACK_INSERT_H]);

        // Pi 5 port cluster — positioned at Y = (the Pi's port edge height
        //    above the back panel's bottom edge, after X1100 + standoffs put
        //    the Pi at Z ≈ X1100_Z + PI_ABOVE_X1100 above the shell's bottom
        //    plate). Adjust after Task 0.5 measurement confirms exact Z.
        pi_port_z = X1100_Z + PI_ABOVE_X1100 - BOTTOM + 2; // Pi edge above panel bottom

        // USB-C at X = 13 mm from Pi's long-edge origin
        translate([13 - 4.75, -0.1, pi_port_z - 2])
            cube([9.5, BACK_METAL + 0.2, 4]);
        // Micro-HDMI ×2
        translate([26 - 3.5, -0.1, pi_port_z - 2])
            cube([7, BACK_METAL + 0.2, 4]);
        translate([39 - 3.5, -0.1, pi_port_z - 2])
            cube([7, BACK_METAL + 0.2, 4]);
        // USB 3.0 stacked pair (remember: one port consumed internally by X1100 bridge;
        //    leave full cutout so from outside it's still visible — internal port will be "blocked" by the bridge)
        translate([58 - 7, -0.1, pi_port_z - 7.5])
            cube([14, BACK_METAL + 0.2, 15]);
        // USB 2.0 stacked pair
        translate([73 - 7, -0.1, pi_port_z - 7.5])
            cube([14, BACK_METAL + 0.2, 15]);
        // RJ45 (PoE-in)
        translate([89 - 8, -0.1, pi_port_z - 6.75])
            cube([16, BACK_METAL + 0.2, 13.5]);

        // SMA bulkhead — 6.35 mm diameter hole, positioned above the Pi ports
        sma_z = pi_port_z + 25;
        translate([BACK_INSERT_L - 15, BACK_METAL/2, sma_z])
            rotate([0, 90, 0])
                cylinder(d = 6.35, h = BACK_METAL + 0.2, center = true);

        // Corner mounting holes for M3 screws (that thread into the printed shell's rim)
        for (corner = [
            [3, 3], [BACK_INSERT_L - 3, 3],
            [3, BACK_INSERT_H - 3], [BACK_INSERT_L - 3, BACK_INSERT_H - 3],
        ]) {
            translate([corner[0], -0.1, corner[1]])
                rotate([-90, 0, 0])
                    cylinder(d = 3.2, h = BACK_METAL + 0.2);
        }
    }
}
```

- [ ] Render in OpenSCAD, visual check: all port cutouts visible, panel size looks right
- [ ] Export to DXF: `openscad -o back_io_shield.dxf back_io_shield.scad`
- [ ] Open DXF in FreeCAD: `freecad back_io_shield.dxf &` — verify port cutout shapes, dimensions

### Task 2.2: Write `top_plate.scad`

**Files:** `hardware/gx01-case/top_plate.scad`

- [ ] 2D sketch with: 40 mm fan cutout (centered), antenna dock recess (35 × 30 × 6 mm deep pocket — but DXF is 2D, so the recess is a separate 2D cut-out pattern for the CNC to mill), 4× corner mounting holes
- [ ] Note for the machinist: "mill a 6 mm deep pocket in the antenna dock area" — goes in a separate spec document alongside the DXF
- [ ] Export to DXF

### Task 2.3: Write `fabrication_notes.md` — package for machinist

**Files:** `hardware/gx01-case/fabrication_notes.md`

- [ ] Include:
  - Material: 6061 aluminum, 2 mm thick, ~250 × 100 mm stock required
  - Two parts: `back_io_shield.dxf` (119 × 89 mm) and `top_plate.dxf` (119 × 94 mm)
  - Finish: bead-blasted + clear anodized in bronze (Pantone 7563 C or similar)
  - Notes on the antenna dock pocket milling
  - Tolerance expectation: ±0.1 mm on port cutouts (the critical features)

### Task 2.4: Send to machinist + receive

- [ ] Zip `back_io_shield.dxf`, `top_plate.dxf`, `fabrication_notes.md` and email to your machinist
- [ ] Estimated turnaround: 1-2 weeks
- [ ] On receipt: fit-check against the latest printed shell
- [ ] Verify all Pi ports align with the actual Pi 5 + X1100 stack (test-fit without fasteners first)

### Task 2.5: Commit aluminum files

- [ ] Run: `git add hardware/gx01-case/*.dxf hardware/gx01-case/fabrication_notes.md`
- [ ] Commit: `feat(case): CNC aluminum parts DXF + fab spec`

---

## Phase 3: Assembly

### Task 3.1: Install heat-set inserts into printed shell

**Files:** `hardware/gx01-case/ASSEMBLY.md` (document as you go)

- [ ] Tools: soldering iron with a heat-set insert tip (or a clean fine tip), needle-nose pliers
- [ ] At 240-260 °C, push each M3 heat-set insert into its pilot hole; wait for PETG to soften (~5 sec), press in until flush, let cool
- [ ] Repeat for all ~16 inserts (4 at bottom mount, 4 at X1100 posts, 4 at rim, 4 at top cap mate)
- [ ] Photograph the completed tray for ASSEMBLY.md

### Task 3.2: Assemble the stack per spec assembly sequence

Reference the spec's 17-step assembly sequence (`docs/superpowers/specs/2026-04-18-gx-01-case-design.md` → "Assembly sequence (planned)").

- [ ] Step 2 (spec): mount SSD onto X1100 shield
- [ ] Step 3: mount X1100 (with SSD) to bottom tray via 4× M2.5 standoffs
- [ ] Step 4: insert rigid USB3 bridge into X1100
- [ ] Step 5: mount Pi 5 on top of X1100 via 4× M2.5 standoffs; seat USB3 bridge into Pi's USB3-A port
- [ ] Step 6: mount X1207 on Pi GPIO; seat 21700 cell
- [ ] Step 7: stack AI HAT+ 2
- [ ] Step 8: stack LC29H
- [ ] **Step 9 (CRITICAL):** install u.FL → SMA pigtail onto LC29H BEFORE the adapter HAT goes on top. If you forget, the adapter HAT will cover the u.FL and you'll have to remove it.
- [ ] Step 10: attach back I/O shield (aluminum) to shell's back frame via 4× M3 × 8 screws
- [ ] Step 11: install the GX-01 adapter HAT on top of LC29H

### Task 3.3: Wire front panel + fans

- [ ] Route LCD 20-conductor ribbon from adapter HAT J2 to the LCD module
- [ ] Connect 3× LEDs to front panel openings + wire to adapter HAT's LED header (if present in your PCB revision — v1 board doesn't include front panel header; route LEDs directly to GPIO via DuPont jumpers if needed)
- [ ] Connect shutdown button to adapter HAT (or directly to GPIO)
- [ ] Mount top-exhaust fan to underside of aluminum top plate via 4× M3 × 20 screws (through fan's mount ears into heat-set inserts on the top cap's upper rim)
- [ ] Plug top-exhaust fan's JST-XH connector into adapter HAT J3
- [ ] Mount front-intake fan to front wall via 4× M3 × 12 screws
- [ ] Plug front-intake fan's JST-XH into adapter HAT J4
- [ ] **Multimeter-verify: 5 V ± 0.2 V at each JST-XH header BEFORE powering the Pi**

### Task 3.4: Mount front panel components

- [ ] Install smoked acrylic window in LCD cutout (friction-fit, or secure with 2× M2 screws through printed bosses)
- [ ] Install 3× 12 mm bezel LEDs into front panel holes
- [ ] Install momentary shutdown button + press-fit button cap

### Task 3.5: Smoke test before closing case

- [ ] Connect PoE ethernet (or USB-C power); power-on
- [ ] Verify: PWR LED lights, LINK LED blinks, Pi boots (check with SSH or HDMI), fans spin up, LCD shows status daemon output (assumes Plan 1 is already deployed — if not, skip LCD verification)
- [ ] Use multimeter to verify 5 V at each fan header under load (fans running)

### Task 3.6: Close case

- [ ] Install top plate + antenna dock insert
- [ ] Torque M3 × 8 corner screws to hand-tight (~1 Nm)
- [ ] Install rubber feet on bottom

### Task 3.7: Commit assembly guide

- [ ] Populate `ASSEMBLY.md` with photos + notes from each step
- [ ] Commit: `docs(case): ASSEMBLY.md with photos from build`

---

## Phase 4: Thermal validation

### Task 4.1: Write `thermal_test.py`

**Files:** `hardware/gx01-case/thermal_test.py`

- [ ] Create a Python script that:
  - Runs `stress-ng --cpu 4 --io 2 --vm 1 --vm-bytes 512M --timeout 900s` in the background
  - Polls `/sys/class/thermal/thermal_zone0/temp` every 10 seconds
  - Polls the Hailo's thermal endpoint (path TBD — via `hailortcli fw-control get-temperature` or similar)
  - Logs Pi CPU temp, Hailo temp, ambient (external sensor if available) for 15 minutes
  - Prints summary: peak, mean, 95th percentile

- [ ] Code sketch:

```python
#!/usr/bin/env python3
import subprocess, time, statistics, sys
from pathlib import Path

DURATION_S = 900
POLL_INTERVAL_S = 10

cpu_temps = []
hailo_temps = []

stress = subprocess.Popen(
    ["stress-ng", "--cpu", "4", "--io", "2",
     "--vm", "1", "--vm-bytes", "512M",
     "--timeout", f"{DURATION_S}s"]
)

start = time.monotonic()
try:
    while time.monotonic() - start < DURATION_S:
        cpu_temp_milli = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip())
        cpu_temp = cpu_temp_milli / 1000.0
        cpu_temps.append(cpu_temp)
        # Hailo temp — adjust command based on actual installation
        try:
            r = subprocess.run(["hailortcli", "fw-control", "get-temperature"],
                              capture_output=True, text=True, timeout=5)
            # Parse result; expect line like "Temperature: 65.2 C"
            for line in r.stdout.splitlines():
                if "Temperature" in line:
                    hailo_temps.append(float(line.split(":")[1].strip().rstrip("C").strip()))
                    break
        except Exception:
            pass
        print(f"{int(time.monotonic() - start):4}s  CPU {cpu_temp:.1f}°C  "
              f"Hailo {hailo_temps[-1] if hailo_temps else 'N/A'}°C")
        time.sleep(POLL_INTERVAL_S)
finally:
    stress.terminate()

print()
print(f"=== Pi CPU temperature ({len(cpu_temps)} samples) ===")
print(f"  peak:   {max(cpu_temps):.1f}°C")
print(f"  mean:   {statistics.mean(cpu_temps):.1f}°C")
print(f"  p95:    {statistics.quantiles(cpu_temps, n=20)[18]:.1f}°C")
if hailo_temps:
    print(f"=== Hailo temperature ({len(hailo_temps)} samples) ===")
    print(f"  peak:   {max(hailo_temps):.1f}°C")
    print(f"  mean:   {statistics.mean(hailo_temps):.1f}°C")
```

### Task 4.2: Baseline run (before case)

- [ ] Run `thermal_test.py` with the stack in open air (bare board configuration, same as current state before the case is built)
- [ ] Expected result: peak ~67 °C on CPU (per spec's empirical baseline)
- [ ] Record results in `hardware/gx01-case/thermal_results.md`

### Task 4.3: Cased run (after assembly)

- [ ] Close the case fully; run `thermal_test.py` again
- [ ] Compare: peak cased temp vs. peak bare-board temp
- [ ] PASS criterion: peak CPU ≤ 75 °C, peak Hailo ≤ 80 °C
- [ ] If over: check fan operation, consider upgrading to NF-A4x20 (3× CFM)

### Task 4.4: Document results

- [ ] Update `thermal_results.md` with both runs, graph if useful
- [ ] Commit: `docs(case): thermal validation results v0.1 build`

---

## Spec → task coverage check

Each numbered goal in the spec maps to at least one task:

| Spec goal | Plan coverage |
|---|---|
| Hold current hardware stack unchanged | Phase 3 assembly tasks |
| Direct-expose Pi I/O | Task 2.1 back_io_shield + Task 3.2 step 10 |
| Survive Arizona ambient | Phase 4 thermal tasks 4.1-4.4 |
| Externalize GPS via SMA | Task 2.1 SMA hole + Task 3.2 step 9 (u.FL pigtail) |
| 128×64 status LCD | Task 1.3 LCD cutout + Task 3.3 front panel wiring (daemon from Plan 1) |
| Fabricable with 3D printer + CNC | Phase 1 + Phase 2 |
| Purposeful / user-serviceable aesthetic | Phase 1 shell design + Phase 2 aluminum finish notes |

Spec risks map to tasks:

| Spec risk | Plan task |
|---|---|
| X1100 dimensions not verified | Task 0.5 measurement |
| LC29H passthrough completeness | Task 0.6 continuity test |
| Stack height verification | Task 0.4 + Task 1.8 fit check |
| Reduced interior volume, thermal density | Phase 4 + fan upgrade path |
| Back panel port alignment tolerance | Task 2.1 panel slop + Task 2.4 test-fit |
| Assembly sequence u.FL ergonomics | Task 3.2 step 9 bold warning |
| USB3 bridge mechanical compat | Task 0.5 measurement |

## Execution

This plan runs best with **superpowers:executing-plans** in batch mode per phase (Phase 0 → checkpoint, Phase 1 → checkpoint, etc.), because phases have physical gating: you can't start Phase 2 until measurements are complete; you can't run Phase 3 until both prints + aluminum parts are in hand.
