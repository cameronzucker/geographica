# GX-01 Case Design

**Status:** Design spec — ready for implementation planning
**Author:** Cameron Zucker (with Claude)
**Date:** 2026-04-18
**Scope:** Hybrid 3D-printed + CNC-machined desk enclosure for Cameron's personal Pi 5 development/demo unit running Geographica

## Summary

A hybrid-construction desk enclosure — printed FDE (Flat Dark Earth) PETG body with bronze-anodized aluminum top plate and back I/O panel — that packages the existing Geographica hardware stack into a single clean object. The existing SATA drive stays; the GPS antenna is externalized on an SMA pigtail (the only internal jumper); the Pi's native port bank is direct-exposed through the precision aluminum I/O shield (no USB hubs, no extensions).

Nominal exterior: **~235 × 90 × 70 mm (L × D × H).** Final dimensions to be pinned during implementation against physical measurements of the assembled hardware.

A front-facing 128×64 monochrome graphical LCD (black-on-green, ST7565R or equivalent) surfaces network + GPS + battery + service status, including a live QR code to join the unit's WiFi AP. The status LCD is driven by a small Python daemon over SPI.

**Active cooling** via one or two 40 mm 5V axial fans: empirical measurements on the bare board show 67 °C under sustained imagery-processing load with the Pi 5 Active Cooler fan ramped up — passive cooling alone would worsen this significantly inside an enclosure. Fans power from the Pi's GPIO 5V rail (supplied by X1207's 5A PoE conversion, ~2A of headroom available above system baseline). The X1207 does NOT provide its own fan header or auxiliary power rails; wiring taps GPIO pins 2/4 (5V) and 6 (GND) via a small custom harness with 2-pin JST-XH connectors per fan.

## Goals

1. Hold the current hardware stack as-is, without modifying or replacing any component
2. Expose the Pi 5's native I/O directly through an aluminum I/O shield on the back — no USB hubs, no extension cables, no signal degradation
3. Survive Arizona ambient temperatures (direct sun, up to ~45 °C air / ~70 °C radiant surface) with active airflow — the existing Pi 5 Active Cooler already hits 67 °C under sustained load at room ambient, so an enclosed case needs forced airflow to match or beat that baseline. Light-colored body (FDE, ~55 °C equilibrium in sun) minimizes solar gain; aluminum top plate doubles as heat spreader; one or two 40 mm fans move air through the Pi chamber
4. Externalize the GPS antenna entirely (SMA bulkhead on the back panel → active GPS puck on coax), because the RF link budget requires ≥40 dB isolation from the Pi + PoE + USB 3.0 noise stack, which no printed enclosure can provide
5. Present live status at a glance via a front-mounted 128×64 monochrome graphical LCD — IP address, uptime, GPS fix count, CPU temp, battery state, service health, and a scan-to-join WiFi QR code
6. Be fabricable by one person with a consumer 3D printer plus a friend with CNC capability — no injection molding, no cast metal, no custom PCBs
7. Communicate "purposeful tool, user-serviceable" visually — FDE + bronze palette, exposed M3 fasteners, stenciled model number, etched nameplate

## Non-goals

- NOT IP-rated, NOT drop-tested, NOT ruggedized for field deployment. A desk unit.
- NOT a go-box insert for a Pelican case. Standalone enclosure.
- NOT designed for mass production. One-off personal build; may template later.
- NOT a general Pi 5 case. Specific to this exact hardware stack.

## Hardware manifest

### Existing (to be enclosed without modification)

| Component | Qty | Dimensions | Notes |
|---|---|---|---|
| Raspberry Pi 5 16 GB | 1 | 85 × 56 × 17 mm (board + tallest connector) | Primary SBC |
| Geekworm X1207 PoE/UPS HAT | 1 | ~85 × 80 mm (extends ~24 mm past Pi's 56 mm edge) | PoE-in via Pi's built-in RJ45 magnetics + 21700 UPS |
| 21700 Li-ion cell | 1 | 21 × 70 mm cylinder | Installed in X1207 cradle, lies flat, extending perpendicular from Pi past the Pi's short (56 mm) edge |
| Raspberry Pi AI HAT+ 2 (Hailo) | 1 | ~65 × 56 mm + Hailo heatsink (~15 mm tall) | Uses Pi's single PCIe lane |
| Waveshare LC29H GPS HAT | 1 | ~65 × 56 mm | u.FL connector exposed for external antenna |
| 2.5" SATA SSD (bare drive) | 1 | 100 × 70 × 7 mm | Already bare — no enclosure to remove |
| Existing USB-A → SATA bridge adapter | 1 | ~25 × 40 × 10 mm PCB clipped onto drive's SATA edge, with USB cable tail | Keeps current working configuration; adds ~25 mm of length past the drive's short edge |

### New / to procure

| Item | Qty | Notes |
|---|---|---|
| u.FL → SMA-F bulkhead pigtail, 10–15 cm | 1 | Standard part, ~$3 |
| SMA-F bulkhead jack (panel-mount, D-cut or round) | 1 | Standard part |
| Active GPS puck antenna w/ magnetic base + SMA-M on ~1–3 m coax | 1 | User-supplied or shipped with unit |
| 128×64 monochrome graphical LCD w/ backlight (ST7565R, ST7920, or equivalent — SPI) | 1 | Front status display; green or white backlight; module ~60 × 40 mm, active area ~50 × 30 mm |
| Smoked or tinted acrylic window, ~55 × 38 × 2 mm | 1 | Front LCD window |
| 12 mm illuminated green LED (power) | 1 | Front panel |
| 12 mm illuminated blue LED (link/activity) | 1 | Front panel |
| 12 mm illuminated amber LED (battery charging) | 1 | Front panel |
| 16 mm momentary pushbutton, recessed, SPST | 1 | Shutdown button |
| M3 × 8 mm socket head cap screws (bronze PVD or black oxide) | ~20 | Visible fasteners |
| M3 × 5 mm heat-set brass inserts | ~20 | For 3D-printed parts |
| M2.5 × 10 mm brass standoffs | 4 | Pi 5 mount |
| Silicone rubber feet, M3-mount | 4 | Bottom |
| N52 neodymium disc magnet, ~20 × 3 mm | 2 | Antenna dock recess (top-mount, for GPS puck storage) |
| 6061 aluminum plate, 2 mm, ~250 × 100 mm stock | ~2 sheets | Top plate + back I/O shield |
| FDE PETG filament, ~500 g | 1 roll | Body |
| 40 mm 5V axial fan (Noctua NF-A4x10 5V or equivalent, 3-pin) | 1–2 | Active cooling. Primary exhaust mounts in aluminum top plate over Pi chamber; optional intake mounts in front panel or left side wall |
| 40 mm fan grille (aluminum or steel mesh, adhesive-mount) | 1–2 | Protects fan blades, looks intentional |
| GPIO screw-terminal breakout HAT (Waveshare or equivalent, with 40-pin passthrough) | 1 | Sits on top of LC29H, exposes 5V/GND to screw terminals |
| 2-pin JST-XH-to-bare-wire pigtails, ~10 cm | 2 | One per fan; bare-wire ends screw into the breakout HAT's 5V/GND terminals |
| 20 AWG insulated hookup wire, red + black, ~0.5 m each | 1 each | For fan power runs from breakout to fans |
| MicroSD slot rubber grommet plug | 1 | Dust cover for bottom microSD access slot |

## Physical dimensions (nominal)

**Exterior:** ~235 × 90 × 70 mm (L × D × H)

- **Length (L, 235 mm):** parallel to Pi's long (85 mm) I/O edge. Split ~90 mm Pi chamber / 3 mm divider / ~135 mm SSD chamber. The measured SSD + USB-SATA adapter assembly is ~125.4 mm end-to-end (5" minus 1/16"); SSD chamber interior is sized to ~132 mm to give ~7 mm of routing clearance for the USB-A cable tail and adapter play.
- **Depth (D, 90 mm):** front face to back face. Accommodates the Pi + X1207 + 21700 assembly's ~81 mm depth + wall thicknesses.
- **Height (H, 70 mm):** bottom to top plate. Accommodates the stacked Pi + X1207 + AI HAT+ 2 + LC29H + 21700 battery assembly (~55 mm) plus top-plate fan clearance (~10 mm for a 40 mm fan under the plate) + wall/plate thicknesses.

Final dimensions will be verified against physical measurements of the assembled hardware during the implementation plan phase. Expected tolerance on overall dimensions: ±3 mm (slight warp on a 210 mm PETG print is normal).

## Construction

### Printed parts (FDE PETG)

One main "tray" shell comprising bottom + four walls:

1. **Main shell** — single-piece or two-piece (split at mid-height if print bed size requires)
   - Bottom plate integrated, 3 mm thick
   - Front wall (3 mm) with cutouts for LCD window (~55 × 38 mm), three 12 mm LED holes, one 16 mm shutdown button hole, and recessed pockets for etched nameplate
   - Left wall (3 mm) with an optional 42 mm round cutout for a secondary intake fan (blanked with a printed plug if only one fan is used in v0.1)
   - Right wall (3 mm), solid, with low ventilation slots for SSD chamber passive intake
   - Back wall: a frame-only structure that accepts the aluminum I/O shield as an inset (see below)
   - Internal divider rib separating Pi chamber (left) from SSD chamber (right)
   - Integrated Pi mounting posts (4× M2.5 standoff receptacles with heat-set inserts)
   - Integrated SSD mount posts (2× M3 receptacles for flat-mounting the 2.5" drive)
   - Integrated rim on top edge to accept the aluminum top plate with M3 captive screws at all four corners
   - Integrated microSD slot access cutout in the bottom plate, with a small rubber grommet plug

2. **Antenna dock insert** — a small separate printed part that drops into a recess on the top plate, holding the two N52 magnets for the GPS puck parking spot (printed part is needed because magnets can't be machined into aluminum plate cleanly)

3. **Button cap** — the recessed cap that covers the momentary switch on the front, shaped to be glove-friendly

Print settings: 0.2 mm layer height, 4 perimeters, 25% gyroid infill, minimal supports (the shell is designed to print bottom-down with minimal overhangs).

### CNC-machined parts (6061 aluminum, bronze-anodized)

Two precision parts where dimensional accuracy matters most:

1. **Back I/O shield** (2 mm thick, ~229 × 64 mm — spans full interior height minus top/bottom plate overlap)
   - Cutouts sized to Pi 5's actual port positions:
     - USB-C power: 9.5 × 4 mm, centerline at 13 mm from Pi's port-row origin
     - 2× Micro-HDMI: 7 × 4 mm each, centerlines at 26 mm and 39 mm
     - USB 3.0 stacked pair: 14 × 15 mm, centerline at ~58 mm
     - USB 2.0 stacked pair: 14 × 15 mm, centerline at ~73 mm
     - Ethernet RJ45 (PoE-in): 16 × 13.5 mm, centerline at ~89 mm
   - SMA-F bulkhead hole: 6.35 mm diameter, positioned just past the divider (~113 mm from panel left edge, centered vertically)
   - Horizontal vent slots across the SSD-chamber portion (right side), roughly 30 slots × 0.8 mm × 80 mm long
   - Four M3 countersunk mounting holes at corners, mating with heat-set inserts in the printed shell's back frame
   - Laser-etched labels adjacent to each port group ("PoE-IN", "USB 3.0", "USB 2.0", "HDMI", "USB-C", "GPS ANT") + one centered header ("GEOGRAPHICA · GX-01 REAR · v0.1")

   **Critical:** port positions are mm-accurate from Pi 5 mechanical drawing, not guessed. The machinist should verify against the actual Pi 5 before final cut. Post-drill recovery is planned if any hole is malformed.

2. **Top plate** (2 mm thick, ~229 × 84 mm)
   - **Primary exhaust fan cutout** over the Pi chamber portion (left ~40% of plate): 42 mm round cutout with an integrated aluminum grille pattern (either a milled hex-mesh or an adhesive stainless mesh underneath). The 40 mm fan mounts to the underside of the top plate via four M3 × 20 mm screws through the fan's mounting ears into printed standoffs on the Pi chamber's top rim.
   - Smaller passive vent pattern over the SSD chamber portion: 2× rows of ~10 holes, 2.5 mm diameter each, for convection out of the SSD chamber
   - Recessed magnetic antenna dock pocket (~45 × 8 mm deep recess), positioned in the clear area between fan cutout and vent pattern, sized to cradle a standard 28 mm GPS puck; two N52 magnets (in the printed insert underneath) hold the puck through the aluminum
   - Laser-etched small "GPS DOCK" label adjacent to the recess
   - Four M3 countersunk mounting holes at corners

Finish: bead-blasted + clear anodized in bronze (Pantone ~7563 C). Bronze complements FDE and reflects near-IR significantly better than black anodize, reducing solar heat gain.

### Assembly sequence (planned)

1. Install heat-set inserts into printed shell (all ~20)
2. Mount Pi 5 + X1207 + 21700 battery assembly to Pi chamber floor via 4× M2.5 standoffs
3. Stack AI HAT+ 2 and LC29H per existing working configuration
4. Install u.FL → SMA pigtail onto the LC29H's u.FL connector while the LC29H is still exposed (critical — this becomes inaccessible once the GPIO breakout HAT is added on top); mount SMA bulkhead into back I/O shield
5. Attach back I/O shield to printed shell's back frame with 4× M3 × 8 screws
6. Install LCD behind front window, LEDs, shutdown button — all wired to the Pi via a small breakout harness routed through the chamber divider's wiring pass-through. LCD uses SPI (4 wires: MOSI, SCLK, CS, DC) + backlight power + ground.
6a. **Install GPIO screw-terminal breakout HAT on top of the LC29H** (verify orientation matches the 40-pin pinout before seating); wire fan power:
   - Strip ~5 mm from each hookup wire end
   - Screw 2× red wires (both fans' +) into one 5V terminal (e.g., pin 2 or 4)
   - Screw 2× black wires (both fans' −) into one GND terminal (e.g., pin 6)
   - Crimp/connect the other ends of the hookup wires to the 2-pin JST-XH pigtails
   - Mate each JST-XH pigtail to a fan's connector (PWM wire floats)
   - Multimeter-verify 5V ± 0.2V between red and black at the fan end before powering Pi
6b. Install top-exhaust fan to the underside of the aluminum top plate via 4× M3 screws; route fan cable to the breakout HAT's terminals
7. Mount SSD to SSD chamber floor via 2× M3 screws into mount posts; clip the existing USB-A-to-SATA adapter onto the drive's SATA edge; route the adapter's USB-A cable through a slot in the chamber divider and plug into a Pi USB 3.0 port on the back
8. Test boot + LCD + GPS lock + WiFi AP + fan spin-up + all ports
9. Install top plate + antenna dock insert, torque to hand-tight via 4× M3 × 8 screws
10. Install rubber feet on bottom

## Front panel specification

Elements, left to right:

- **Status LCD** — 128×64 monochrome graphical LCD (ST7565R / ST7920 / or other common Pi-compatible controller) over SPI. Green or white backlight. Module dimensions ~60 × 40 mm, active area ~50 × 30 mm. Recessed ~2 mm behind a tinted acrylic window.
- **LED stack** (three 12 mm illuminated LEDs, vertical):
  - Green: PWR (solid = on)
  - Blue: LINK (solid = ethernet up, blinking = activity)
  - Amber: CHG (solid = charging 21700, off = on mains + full, blinking = running on battery)
- **Shutdown button** — 16 mm momentary, recessed, tied to GPIO. Long-press triggers graceful shutdown via a small systemd service.
- **Nameplate block** — stenciled "GX-01" in bold monospace (~18 mm tall), followed by a thin etched separator line, then sublines: "GEOGRAPHICA FIELD UNIT", "REV 0.1 · SN _________", "PoE 802.3at · 21700 UPS · Pi 5 16GB"

**NOT on the front:** USB port (all four USB-A are on the back), HDMI (on the back), power input (on the back).

## Back panel specification

See dimensioned drawing in brainstorm session (`field-kit-to-scale.html`). In order from left to right:

| Port | Cutout | CL position | Purpose |
|---|---|---|---|
| USB-C | 9.5 × 4 mm | 13 mm | Fallback power (e.g., when not on PoE) |
| Micro-HDMI 0 | 7 × 4 mm | 26 mm | Bench/debug display |
| Micro-HDMI 1 | 7 × 4 mm | 39 mm | Second display |
| USB 3.0 ×2 (stacked) | 14 × 15 mm | ~58 mm | SSD + peripherals |
| USB 2.0 ×2 (stacked) | 14 × 15 mm | ~73 mm | Low-bandwidth accessories |
| RJ45 Ethernet (PoE-in) | 16 × 13.5 mm | ~89 mm | **Primary power + data** (802.3at) |
| SMA-F bulkhead (GPS) | 6.35 mm round | ~113 mm | External active GPS antenna |
| Passive exhaust slot array | ~80 × 40 mm | ~120–200 mm | SSD chamber air venting |

All Pi-native ports direct-expose through the shield — no jumpers. Only the GPS SMA has an internal jumper (u.FL → SMA pigtail).

## Top plate specification

- Punched vent pattern over Pi chamber (hot components below): acts as both vent and partial heat-spreader
- Magnetic antenna dock recess on the SSD-chamber side (cool zone, no active heat source below, so puck stays cool enough to hold station)
- No other features — the top plate is visually the simplest surface, letting the vents + dock read cleanly

## Status LCD software specification

A small Python daemon (`geographica-status-lcd`) running under systemd, refreshing the display every ~1 s.

Data sources:
- **IP address** — `ip addr show eth0` (or the AP interface) parsed
- **Uptime** — `/proc/uptime`
- **GPS fix + sat count** — existing GPS service's WebSocket API (already part of Geographica stack)
- **CPU temp** — `/sys/class/thermal/thermal_zone0/temp`
- **Battery state (% / voltage)** — X1207's I²C interface (chip-specific, typically at address 0x43 for the fuel gauge)
- **Service health** — `systemctl is-active` for each of: tileserver, valhalla, nominatim, gps, search, stt
- **WiFi AP QR code** — generated once at service start from `/etc/geographica/wifi-ap.json` (SSID + password), rendered via the `qrcode` Python library, rasterized to a 28 × 28 pixel region of the display

Display layout (128 × 64 pixels — tighter than the prior OLED layout; alternates between a "status" screen and a "QR code" screen on a ~5 s cycle, or user can toggle via a GPIO button/gesture):

```
STATUS SCREEN (default):
┌───────────────────────────┐
│ PiField  10.0.0.42        │  header + IP
│ BAT 87%  GPS 11/fix       │  battery + gps
│ CPU 47°C  UP 3h12m        │  cpu + uptime
│ svc: ● ● ● ● ● ◐          │  services (6 dots)
└───────────────────────────┘

QR SCREEN (every ~5 s):
┌───────────────────────────┐
│ join: PiField             │
│                           │
│    ┌──────────┐           │
│    │   QR     │  scan →   │
│    │  (25×25) │           │
│    └──────────┘           │
└───────────────────────────┘
```

QR code sizing: a WiFi v2 QR (25×25 modules) fits as ~50×50 px (2 px/module); cell phone cameras reliably decode this at ~20 cm focal distance.

Idle-timeout: backlight dims to ~20% after 2 minutes of no change, fully off after 10 minutes. Wakes on any significant change (IP, GPS fix gained/lost, battery transition) or on shutdown-button press.

Python dependencies: `luma.lcd` (supports ST7565/ST7920), `Pillow`, `qrcode`, `smbus2` (for X1207 battery fuel gauge, still I²C). Add to `services/status-lcd/requirements.txt`.

## Thermal strategy

Active cooling, informed by empirical data: the user measured **67 °C under sustained imagery-processing load** on the bare board with the Pi 5 Active Cooler fan fully ramped. An enclosure without forced airflow would push this above the Pi 5's 85 °C thermal-throttle threshold, defeating the unit's purpose.

Mechanisms:

1. **Top-mounted exhaust fan (primary)** — 40 mm 5V axial fan (Noctua NF-A4x10 5V or equivalent) mounted to underside of aluminum top plate, directly over the Pi chamber. Pulls hot air up and out through the fan grille. The existing Pi Active Cooler blows upward into this exhaust path, so the two fans work together rather than fighting.
2. **Passive low intakes** on the front lower edge and/or both side walls — slot vents ~2 mm × 15 mm each, positioned near the case bottom to feed cool air into the chamber as the exhaust fan creates negative pressure.
3. **Optional secondary intake fan** on the left side wall — adds ~30% more CFM, useful if Arizona summer ambient temps prove too much for the top-exhaust-only config. Spec'd as a cutout with a printed plug by default; swap the plug for a fan if thermals demand.
4. **Aluminum top plate as heat spreader** — the 229 × 84 × 2 mm aluminum plate contacts the AI HAT+ 2's Hailo heatsink top via a thermal pad. Spreads heat radially, dumps it through the top surface + the fan cutout grille.
5. **FDE body color** — reflects ~70% of solar near-IR vs. black's ~5%, keeping exterior body temperature 15–20 °C lower in direct sun.
6. **Bronze-anodized aluminum top** — also high near-IR reflectance (~55% vs. black's 5%), reduces solar gain on the top plate.

**Fan power wiring:** the X1207 does not provide a fan header or auxiliary rails (confirmed via datasheet — delivers 5V 5A to Pi via GPIO header only). The Pi 5's own fan header is occupied by the Active Cooler. Giving up a USB port is not acceptable (SSD already consumes one; the remaining three are planned for other peripherals). The GPIO header itself sits flush inside the LC29H's 40-pin socket and is physically inaccessible without relocating the HAT.

Solution: **a COTS GPIO screw-terminal breakout HAT added to the TOP of the existing stack**, above the LC29H. Stack becomes X1207(side) → AI HAT+ 2 → LC29H → GPIO breakout HAT. The breakout plugs into the LC29H's 40-pin passthrough header and exposes all 40 GPIO pins to labeled screw terminals on the side of the PCB. Fans wire to the 5V and GND terminals via standard hookup wire + 2-pin JST-XH pigtails; two fans share the same 5V/GND terminals (double-wire the screws — standard practice). Fans' PWM wire (if they're 3-pin) is left floating; fans run fixed-full-speed at 17.9 dB(A) each (Noctua NF-A4x10 5V), quieter than typical desk ambient.

Example part: Waveshare "GPIO Screw Terminal Expansion Board" or equivalent. ~$13 COTS. Adds ~8–10 mm of stack height, which the case height budget accommodates (see "Stack height verification" in Risks).

**Current budget:** X1207's 5V 5A output minus system baseline (Pi + HATs + SSD + LCD ≈ 3A) leaves ~2A of headroom — easily covers two 72 mA fans with >1A to spare. The Pi's current limiting at the USB-C input (the X1207's output) is sufficient protection; no separate fuse is required since overdraw would brown-out the Pi itself, providing clear failure signal.

**Expected thermal performance:** Pi 5 CPU ≤ 70 °C under continuous AI + tile-serving load at 35 °C ambient (target: match or beat the 67 °C bare-board baseline, despite enclosure). Hailo ≤ 75 °C. Verified empirically after assembly. If exceeded, install the secondary side-intake fan and/or upgrade to higher-CFM fans (e.g., Noctua NF-A4x20 5V at 3× CFM, still desk-acceptable noise-wise).

## Risks + open questions

1. **Fan quantity — 1 vs. 2** — v0.1 builds with just the top-exhaust fan. The side-intake cutout is in the printed shell but blanked with a plug. If thermal testing shows the Pi exceeds ~75 °C under sustained load, pop the plug and add the intake fan. Design already accommodates both; this is a "start minimal, upgrade if needed" choice.
2. **LC29H 40-pin passthrough completeness** — the GPIO-screw-breakout-on-top approach depends on the LC29H having full 40-pin passthrough with all pins electrically connected between its bottom female socket and top male header, including 5V (pin 2/4) and GND (pin 6/9/14/...). Most Waveshare HATs do full passthrough, but some HATs short only the pins they use. **Verify before ordering the breakout HAT:** continuity-test LC29H pins 2/4/6 top-to-bottom with a multimeter, or read the LC29H schematic on Waveshare's wiki. If passthrough is incomplete, fallback is to move the breakout between AI HAT+ 2 and LC29H (inside the stack rather than on top) — same electrical outcome, slightly harder assembly access.
3. **Stack height verification** — the breakout HAT adds ~8–10 mm to the top of the HAT stack. Current case interior height of ~65 mm (70 mm exterior minus plates minus fan clearance) must accommodate full stack + breakout. If tight, grow case height by 5 mm to 75 mm exterior. Will pin during measurement phase of the plan.
4. **SSD chamber and case length sized to measured SSD+adapter (~125.4 mm)** — resolved. Adapter and drive measured at 5" minus ~1/16". SSD chamber sized to 132 mm internal, case to 235 mm external. No further measurement needed.
5. **Back panel port alignment tolerance stack-up** — printed shell warp + aluminum panel hole positions + Pi PCB tolerance. Mitigation: inset the aluminum shield with ~0.5 mm slop on each side so small dimensional variation is absorbed by panel float.
6. **LCD readability under bright ambient** — reflective/transflective LCDs with green backlight are readable in most conditions including modest direct light; full sun still challenging. Not a design goal for a desk unit.
7. **SSD + PoE component heat** — user reports SSD and PoE components get hot under sustained load, contributing to the 67 °C measurement. Within the enclosure, the SSD chamber has its own passive vent slots (low intake on right side wall, passive upward exhaust through top plate's smaller vent pattern); the PoE transformer on the X1207 is in the Pi chamber's active-airflow path, so the exhaust fan pulls heat off it directly.
8. **Assembly sequence ergonomics** — the u.FL connector on the LC29H is fragile AND becomes inaccessible once the GPIO breakout HAT is added on top. Wiring the SMA pigtail onto the LC29H BEFORE adding the breakout HAT is mandatory — if it's forgotten, the breakout HAT has to come off to access the u.FL. Document this as a bold warning in the assembly guide.
9. **Battery runtime under PoE-loss** — 21700 @ ~4000 mAh × 3.7 V = ~15 Wh. Pi 5 + HATs + SSD draws ~8-12 W. Expected runtime: 1-2 hours on battery. Acceptable for the "survive a PoE switch reboot" use case.

## What comes next

1. User reviews this spec.
2. On approval, invoke `writing-plans` to create the implementation plan, which will cover:
   - OpenSCAD source for the printed shell (parametric dimensions driven by measured hardware)
   - CAM drawings for the aluminum top plate (with fan cutout + grille pattern) + back I/O shield (DXF output for the machinist)
   - `services/status-lcd/` Python daemon implementation
   - systemd unit for the LCD service
   - X1207 I²C integration for battery stats
   - Fan power harness diagram + assembly photos
   - Assembly guide / photo checklist
   - Empirical thermal test protocol
3. Physical build in a few iterations — print v0.1, fit-check, adjust parametric dimensions, print v0.2, finalize, then CNC the aluminum parts (which are expensive to iterate so we validate geometry against printed aluminum-stand-in first).
