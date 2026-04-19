# GX-01 Case Design

**Status:** Design spec — ready for implementation planning
**Author:** Cameron Zucker (with Claude)
**Date:** 2026-04-18
**Scope:** Hybrid 3D-printed + CNC-machined desk enclosure for Cameron's personal Pi 5 development/demo unit running Geographica

## Summary

A hybrid-construction desk enclosure — printed FDE (Flat Dark Earth) PETG body with bronze-anodized aluminum top plate and back I/O panel — that packages the existing Geographica hardware stack into a single clean object. The 2.5" SATA drive now rides on a Geekworm X1100 shield beneath the Pi (replacing the previous loose-drive + USB-A-to-SATA cable arrangement); the GPS antenna is externalized on an SMA pigtail (the only internal jumper); the Pi's native port bank is direct-exposed through the precision aluminum I/O shield (no USB hubs, no extensions).

Nominal exterior: **~125 × 100 × 95 mm (L × D × H).** Single-chamber stacked design driven by the X1100's 107.5 × 85 mm footprint (the largest PCB in the stack). Final dimensions to be pinned during implementation against physical measurements of the assembled hardware.

A front-facing 128×64 monochrome STN LCD (SparkFun GDM12864H / LCD-00710, KS0108B controller, parallel interface, transflective for daylight readability) surfaces network + GPS + battery + service status, including a live QR code to join the unit's WiFi AP. The LCD is driven by a custom Python driver implementing the KS0108B parallel protocol.

Because the KS0108B needs 14 GPIO pins and the LC29H fully covers the Pi's GPIO header, a small **custom 2-layer adapter PCB** sits on top of the LC29H, breaking out GPIOs + 5V into clean connectors for the LCD ribbon, two fan power outputs (JST-XH), and hosting passive components (contrast pot, backlight current-limit resistor, bypass cap). The PCB design lives in `hardware/gx01-adapter-pcb/` and was generated programmatically (SKiDL + pcbnew Python API); Gerbers are fab-ready for OSH Park (~$5 for 3 boards).

**Active cooling** via **two** 40 mm 5V axial fans — both installed from v0.1 rather than "start with one, add second if needed" as the earlier spec called for. The case's ~1.2 L interior volume is ~20 % smaller than the prior two-chamber design, while heat sources (Pi, Hailo, PoE transformer, and now the X1100's USB-SATA bridge IC + the SSD itself inside the stack) are unchanged or slightly increased. Empirical baseline of 67 °C on bare board under sustained imagery load means the enclosed design needs forced airflow, not just better venting. Primary exhaust fan mounts in the aluminum top plate over the HAT stack; secondary intake fan mounts in the front wall at the level of the X1100/SSD, pulling cool air across the drive before it rises through the HATs. Fans power from the adapter HAT's two JST-XH connectors (5V tapped from GPIO via the adapter PCB — see Construction below).

## Goals

1. Hold the current hardware stack as-is, without modifying or replacing any component
2. Expose the Pi 5's native I/O directly through an aluminum I/O shield on the back — no USB hubs, no extension cables, no signal degradation
3. Survive Arizona ambient temperatures (direct sun, up to ~45 °C air / ~70 °C radiant surface) with active airflow — two 40 mm 5 V fans (front intake + top exhaust) move air vertically through the single stack chamber, beating the bare-board 67 °C baseline. Light-colored body (FDE, ~55 °C equilibrium in sun) minimizes solar gain; aluminum top plate doubles as heat spreader over the HAT stack
4. Externalize the GPS antenna entirely (SMA bulkhead on the back panel → active GPS puck on coax), because the RF link budget requires ≥40 dB isolation from the Pi + PoE + USB 3.0 noise stack, which no printed enclosure can provide
5. Present live status at a glance via a front-mounted 128×64 monochrome STN LCD — IP address, uptime, GPS fix count, CPU temp, battery state, service health, and a scan-to-join WiFi QR code; transflective LCD chosen so display is readable in Arizona daylight without relying on backlight
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
| 2.5" SATA SSD (bare drive) | 1 | 100 × 70 × 7 mm | Already bare — mounts directly onto the X1100 shield below the Pi |
| Geekworm X1100 USB3-to-SATA shield | 1 | 107.5 × 85 mm PCB | Sits UNDER the Pi; SSD mounts onto it; connects to Pi via supplied rigid USB3 male-to-male bridge (no cable). Supports stacking with AI HAT+ (vendor confirmed compat with X1207 for this build via email). Largest PCB in the stack — drives the case footprint. |
| Geekworm X1100 USB3 rigid bridge | 1 | (ships with X1100) | Replaces the prior loose USB-A-to-SATA adapter + cable; consumes one Pi USB3-A port mechanically rather than via cable |

### New / to procure

| Item | Qty | Notes |
|---|---|---|
| u.FL → SMA-F bulkhead pigtail, 10–15 cm | 1 | Standard part, ~$3 |
| SMA-F bulkhead jack (panel-mount, D-cut or round) | 1 | Standard part |
| Active GPS puck antenna w/ magnetic base + SMA-M on ~1–3 m coax | 1 | User-supplied or shipped with unit |
| SparkFun GDM12864H STN LCD (LCD-00710) | 1 | 128×64 mono STN with LED backlight, KS0108B parallel controller. Module 75 × 52.7 mm, active 55 × 27.5 mm. Transflective — readable in daylight without backlight |
| Smoked or tinted acrylic window, ~60 × 33 × 2 mm | 1 | Front LCD window |
| Custom GX-01 adapter HAT PCB (OSH Park fab) | 1 (min order: 3) | Breaks out Pi GPIO into LCD + fan + analog connectors; sits on top of LC29H |
| 20-pin 1×20 socket strip 2.54mm pitch for LCD | 1 | Mates PCB → LCD module ribbon |
| 20-conductor female-female DuPont jumpers or 1×20 cable assembly | 1 set | PCB J2 header → LCD module |
| M2.5 × 8mm brass standoffs (for adapter PCB stacking) | 4 | Mount the new HAT on top of existing stack |
| M2.5 screws (adapter PCB to standoffs above) | 4 | |
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

**Exterior:** ~125 × 100 × 95 mm (L × D × H)

Single-chamber stacked design. Everything (X1100 + SSD + Pi + X1207 + HATs + adapter PCB + 21700 cell) occupies one cavity driven by the X1100's 107.5 × 85 mm PCB footprint plus wall/plate clearances.

- **Length (L, 125 mm):** parallel to the X1100's long edge (107.5 mm) with ~6 mm of interior clearance + 6 mm printed wall thickness on each side + 2 mm aluminum back-panel thickness.
- **Depth (D, 100 mm):** parallel to the X1100's short edge (85 mm) with clearance for the X1207's battery cradle that extends ~25 mm past the Pi's 56 mm edge; 6 mm interior clearance + 3 mm printed walls on each side.
- **Height (H, 95 mm):** stacked interior height of ~80 mm (X1100 + standoffs + Pi + Active Cooler + X1207 + AI HAT+ 2 + LC29H + adapter HAT) + top-plate fan clearance (~10 mm under the 2 mm aluminum top) + 3 mm printed bottom plate.

**Interior volume:** ~1.1–1.2 L (~20 % less than the previous two-chamber design). The volume reduction is why active cooling — with both fans — is mandatory rather than optional.

Final dimensions will be verified against physical measurements of the assembled hardware during the implementation plan phase. X1100 mounting hole positions + exact standoff heights require the Geekworm wiki (currently down; vendor notified) or direct measurement of the shipped unit.

Final dimensions will be verified against physical measurements of the assembled hardware during the implementation plan phase. Expected tolerance on overall dimensions: ±3 mm (slight warp on a 210 mm PETG print is normal).

## Construction

### Printed parts (FDE PETG)

One main "tray" shell comprising bottom + four walls — a single chamber, not the previous two-chamber design:

1. **Main shell** — two-piece split horizontally (the full height is tall enough that a bed-hugging single print would need excessive supports for the top-panel rim; cleaner to split)
   - **Bottom tray (~45 mm tall):** integrated bottom plate (3 mm thick) + lower portion of front/back/side walls. Hosts the X1100 shield via 4× M2.5 standoff receptacles with heat-set inserts at X1100's mounting-hole positions (to be confirmed from Geekworm wiki; fallback: measure shipped unit). Front wall lower section contains the **40 mm intake fan cutout** at the level of the X1100 / SSD so cool air enters at the bottom of the thermal column.
   - **Top cap (~50 mm tall):** upper portion of walls + rim for the aluminum top plate. Front wall upper section contains cutouts for LCD window (~55 × 38 mm), three 12 mm LED holes, one 16 mm shutdown button hole, and recessed pockets for etched nameplate.
   - Back wall (across both pieces): a frame-only structure that accepts the aluminum I/O shield as an inset (see below). No longer split into Pi-port / SSD-chamber sections — just the Pi's port cluster + SMA bulkhead + rear vents.
   - **Integrated cable-routing slot** in the upper section's floor for the rigid USB3 bridge between Pi (USB3-A ports) and X1100 below. Since the bridge is rigid, this is just a through-slot, not a cable gland.
   - Left + right walls (3 mm), solid with low ventilation slots near the fan-intake level for cross-airflow.
   - Integrated microSD slot access cutout in the bottom plate (aligned to the Pi's microSD card location AFTER the X1100 is mounted — Pi is ABOVE the X1100, so the microSD cutout goes through both the printed bottom AND a matching hole through the X1100 shield), with a small rubber grommet plug.

2. **Antenna dock insert** — a small separate printed part that drops into a recess on the top plate, holding the two N52 magnets for the GPS puck parking spot.

3. **Button cap** — the recessed cap that covers the momentary switch on the front, shaped to be glove-friendly.

Print settings: 0.2 mm layer height, 4 perimeters, 25% gyroid infill, minimal supports (the shell is designed to print bottom-down with minimal overhangs).

### CNC-machined parts (6061 aluminum, bronze-anodized)

Two precision parts where dimensional accuracy matters most:

1. **Back I/O shield** (2 mm thick, ~119 × 89 mm — matches the new smaller back-panel dimensions)
   - Cutouts sized to Pi 5's actual port positions (vertical position accounting for the Pi's Z-offset above the X1100 — Pi sits ~12 mm above the bottom plate, so port centerline is ~20-25 mm up from the bottom edge of the panel):
     - USB-C power: 9.5 × 4 mm
     - 2× Micro-HDMI: 7 × 4 mm each
     - USB 3.0 stacked pair: 14 × 15 mm — NOTE: only ONE of the two USB3 ports is externally accessible; the other is consumed internally by the X1100 USB3 bridge. The panel cutout covers the stacked pair; the occupied one will just be visibly filled by the bridge's protruding connector from behind.
     - USB 2.0 stacked pair: 14 × 15 mm
     - Ethernet RJ45 (PoE-in): 16 × 13.5 mm
   - SMA-F bulkhead hole: 6.35 mm diameter, positioned in the upper area of the panel (above the Pi ports, in the space the shorter panel now provides)
   - Back exhaust vent slots at the TOP of the panel (above ports and SMA): horizontal slats, ~20 × 0.8 mm × 8 slats total — let hot air out the top rear as it rises through the stack
   - Four M3 countersunk mounting holes at corners, mating with heat-set inserts in the printed shell's back frame
   - Laser-etched labels adjacent to each port group ("PoE-IN", "USB 3.0", "USB 2.0", "HDMI", "USB-C", "GPS ANT") + one centered header ("GEOGRAPHICA · GX-01 REAR · v0.1")

   **Critical:** port positions are mm-accurate from Pi 5 mechanical drawing + X1100 mounting-height offset, not guessed. The machinist should verify against the actual Pi 5 + X1100 stack BEFORE final cut. Post-drill recovery is planned if any hole is malformed.

2. **Top plate** (2 mm thick, ~119 × 94 mm — smaller than v1's 229 × 84 mm)
   - **Primary exhaust fan cutout** centered over the HAT stack: 42 mm round cutout with an integrated aluminum grille pattern (either a milled hex-mesh or an adhesive stainless mesh underneath). The 40 mm fan mounts to the underside of the top plate via four M3 × 20 mm screws through the fan's mounting ears into printed standoffs on the top cap's rim.
   - Recessed magnetic antenna dock pocket (~35 × 6 mm deep recess) off to one side of the fan cutout, sized to cradle a standard 28 mm GPS puck; two N52 magnets (in the printed insert underneath) hold the puck through the aluminum
   - Laser-etched small "GPS DOCK" label adjacent to the recess
   - Four M3 countersunk mounting holes at corners

**Secondary intake fan cutout** moves to the printed FRONT WALL (not the aluminum top plate) at the X1100/SSD level — ~42 mm round cutout + printed aluminum-mesh insert or a simple grille pattern in the printed plastic itself (the intake fan doesn't need a machined metal grille since it's not a visible feature on the top surface).

Finish: bead-blasted + clear anodized in bronze (Pantone ~7563 C). Bronze complements FDE and reflects near-IR significantly better than black anodize, reducing solar heat gain.

### Assembly sequence (planned)

1. Install heat-set inserts into printed bottom tray + top cap (all M2.5 + M3 locations — approx 16 inserts total)
2. **Mount 2.5" SSD onto X1100 shield** per Geekworm's included screws
3. **Mount X1100 (with SSD on it) to the printed bottom tray** via 4× M2.5 standoffs into the bottom tray's heat-set inserts
4. **Install the rigid USB3 male-to-male bridge** into X1100's USB3 receptacle (it's designed to stick upward, ready to receive the Pi above)
5. **Mount Pi 5 on top of X1100 via 4× M2.5 standoffs** (at least 12 mm tall to clear the SSD thickness + bridge height). The USB3 bridge plugs into one of the Pi's USB3-A ports during this step.
6. Mount X1207 on Pi's GPIO via its shoulder-bracket style connector; verify 21700 cell seats in the X1207 cradle.
7. Stack AI HAT+ 2 on top of X1207/Pi assembly (PCIe FPC between Pi and AI HAT+; standoffs at the remaining GPIO-header mounting points).
8. Stack LC29H on top of AI HAT+ 2 via its 40-pin passthrough.
9. **Install u.FL → SMA pigtail onto the LC29H's u.FL connector while the LC29H is still exposed** (critical — this becomes inaccessible once the adapter HAT is added on top); route the SMA end toward the back panel; mount SMA bulkhead into back I/O shield.
10. Attach back I/O shield (CNC aluminum) to printed shell's back frame with 4× M3 × 8 screws.
11. **Install the GX-01 adapter HAT on top of the LC29H** (verify orientation matches the 40-pin pinout before seating).
12. **Wire the front-panel harness:** LCD ribbon (20-conductor) from adapter HAT J2 to the LCD module; LED cathodes/anodes to corresponding GPIO pins on the adapter; shutdown button across its two designated pins. All routed through the cable-routing slot in the shell's internal partition.
13. **Wire the fans:**
    - Fan 1 (top exhaust, mounted to aluminum top plate via 4× M3 screws): plug into adapter HAT's J3 JST-XH header.
    - Fan 2 (front intake, mounted to printed shell's front wall at the X1100 level via 4× M3 screws): plug into adapter HAT's J4 JST-XH header.
    - Multimeter-verify 5 V ± 0.2 V at each JST-XH header before powering the Pi.
14. **Mount front panel components:** install LCD behind the front window with the smoked acrylic window in the cutout; install 3× 12 mm LED bezels; install the momentary shutdown button + printed glove-friendly cap.
15. **Test boot + LCD + GPS lock + WiFi AP + fan spin-up + all ports** through the back I/O shield before closing the case.
16. Install top plate + antenna dock insert on top of the printed shell, torque to hand-tight via 4× M3 × 8 screws.
17. Install rubber feet on bottom.

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

**LCD driver:** The KS0108B controller has no `luma.lcd` support; we write a ~200 LOC Python driver implementing its parallel protocol over 14 GPIO pins (8 data + 6 control). Driver exposes a clean interface (`Ks0108bDisplay` class with `init()`, `clear()`, `draw_bitmap(pil_image)`, `set_contrast()`) and is TDD-driven against a mock GPIO backend for unit tests, then integration-tested against the real LCD. Timing requirements are modest (status display updates at ~1 Hz; KS0108B's spec allows 3+ MHz bus clock, we run at 50-100 kHz via software GPIO — plenty of margin).

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

Python dependencies: `lgpio` (or `gpiozero`) for KS0108B GPIO driving, `Pillow` (PIL) for rendering, `qrcode` for the WiFi QR code, `smbus2` (for X1207 battery fuel gauge over I²C). Add to `services/status-lcd/requirements.txt`. The KS0108B driver itself lives at `services/status-lcd/driver/ks0108b.py` — pure Python, no C extensions, ~200 LOC.

## Thermal strategy

Active cooling, informed by empirical data: the user measured **67 °C under sustained imagery-processing load** on the bare board with the Pi 5 Active Cooler fan fully ramped. An enclosure without forced airflow would push this above the Pi 5's 85 °C thermal-throttle threshold, defeating the unit's purpose.

Mechanisms:

1. **Top-mounted exhaust fan (primary, mandatory)** — 40 mm 5V axial fan (Noctua NF-A4x10 5V or equivalent) mounted to underside of aluminum top plate, centered over the HAT stack. Pulls hot air up and out through the fan grille. The existing Pi Active Cooler blows upward into this exhaust path, so the two fans work together rather than fighting.
2. **Front-mounted intake fan (secondary, also mandatory)** — 40 mm 5V axial fan mounted to the printed front wall at the level of the X1100 / SSD. Pushes cool air in at the bottom of the chamber, across the SSD (which runs warm), then lets it rise naturally through the Pi + HATs + adapter HAT toward the exhaust fan on top. This creates a strong front-to-top vertical airflow column. Unlike the earlier side-intake "optional fan" design, this one is required from v0.1 because the reduced interior volume (~1.2 L vs. the previous ~1.5 L) leaves less thermal mass to absorb transients.
3. **Supplementary passive intakes** on the left + right walls near the bottom — slot vents ~2 mm × 15 mm each, supplementing the intake fan.
4. **Aluminum top plate as heat spreader** — the smaller 119 × 94 × 2 mm aluminum plate contacts the adapter HAT's top surface only indirectly (through ~5 mm air gap). Removed the direct Hailo-heatsink thermal pad contact from the earlier spec since the adapter HAT now sits between the Hailo and the top plate.
5. **FDE body color** — reflects ~70% of solar near-IR vs. black's ~5%, keeping exterior body temperature 15–20 °C lower in direct sun.
6. **Bronze-anodized aluminum top** — also high near-IR reflectance (~55% vs. black's 5%), reduces solar gain on the top plate.

**Fan power wiring:** the X1207 does not provide a fan header or auxiliary rails (confirmed via datasheet — delivers 5 V 5 A to Pi via GPIO header only). The Pi 5's own fan header is occupied by the Active Cooler. Giving up a USB port is not acceptable (X1100 USB3 bridge already consumes one; the remaining two USB-A + other HDMI/USB-C ports are planned for peripherals). The GPIO header itself sits flush inside the LC29H's 40-pin socket and is physically inaccessible without relocating the HAT.

Solution: **a custom 2-layer adapter HAT added to the TOP of the existing stack**, above the LC29H. The LCD also needs 14 GPIOs for its parallel interface, which the stackable breakout PCB provides in the same package — eliminating the need for a separate GPIO breakout. Stack becomes X1207(side) → AI HAT+ 2 → LC29H → GX-01 adapter HAT.

The adapter HAT provides:
- 2×20 female GPIO socket at the bottom, mating with the LC29H's male top header
- 1×20 pin header (J2) breaking out all GPIOs needed by the KS0108B LCD + VDD/VSS/contrast/Vee/BLA/BLK
- 2× JST-XH 2-pin headers (J3, J4) for fan power (5V + GND)
- 10 kΩ multi-turn pot (RV1) for LCD contrast trim, with the full VDD↔Vee divider standard for KS0108B
- 10 Ω backlight current-limit resistor (R1)
- 100 nF bypass cap (C1) on the LCD's VDD rail
- 4× M2.5 mounting holes at standard Pi HAT positions for mechanical stacking

Fab cost: ~$5 for 3 boards at OSH Park, ~2-week turnaround. All through-hole components, ~$10 BOM, hand-solderable in ~30 minutes. Design is fully generated by `circuit.py` (SKiDL) and `layout.py` (pcbnew Python API) — both committed to `hardware/gx01-adapter-pcb/`. 15 connections are left as ratsnest for ~5 minutes of GUI signal routing before Gerber export. Design generated with KiCad 9.0 on this dev machine, verified to pass DRC with only cosmetic warnings (courtyard + silk clearance).

Adds ~10 mm of stack height, within case height budget (see "Stack height verification" in Risks).

**Current budget:** X1207's 5V 5A output minus system baseline (Pi + HATs + SSD + LCD ≈ 3A) leaves ~2A of headroom — easily covers two 72 mA fans with >1A to spare. The Pi's current limiting at the USB-C input (the X1207's output) is sufficient protection; no separate fuse is required since overdraw would brown-out the Pi itself, providing clear failure signal.

**Expected thermal performance:** Pi 5 CPU ≤ 70 °C under continuous AI + tile-serving load at 35 °C ambient (target: match or beat the 67 °C bare-board baseline, despite enclosure AND the SSD now being in the same chamber). Hailo ≤ 75 °C. SSD ≤ 55 °C (intake fan flows cool air directly across it). Verified empirically after assembly. If exceeded, upgrade to higher-CFM fans (e.g., Noctua NF-A4x20 5V at 3× CFM, still desk-acceptable noise-wise).

## Risks + open questions

1. **X1100 mechanical dimensions not yet verified** — Geekworm's X1100 wiki (`wiki.geekworm.com/X1100`) is currently down (vendor notified). Exact mounting-hole positions, standoff heights needed between X1100 and Pi, and the USB3 bridge's physical offset from the X1100's PCB plane are all TBD until either (a) the wiki returns, or (b) the shipped X1100 is in hand and can be measured directly. The spec's nominal 125 × 100 × 95 mm exterior uses ~5 mm of slop on every axis to absorb this uncertainty; final shell dimensions get locked down after measurement.
2. **LC29H 40-pin passthrough completeness** — unchanged from v2 spec. Continuity-test pins 2, 4, 6 + 14 LCD signal pins before ordering adapter-HAT fab.
3. **Stack height verification** — adapter HAT adds ~8–10 mm; X1100 adds another ~12–15 mm below the Pi. Case interior ~85 mm accommodates the full stack (~80 mm measured) with ~5 mm slop + fan clearance. Verified against X1100's actual stack position in measurement phase.
4. **Reduced interior volume, increased thermal density** — NEW risk from the X1100 change. The case went from ~1.5 L to ~1.2 L (20 % reduction) while gaining a new heat source (SSD now internal). Mitigation is the mandatory second (intake) fan + vertical airflow path from front-bottom to top-rear. If empirical testing shows Pi > 75 °C despite both fans, upgrade to Noctua NF-A4x20 (3× CFM) or NF-A6x25 (larger 60 mm fan — requires top-plate redesign).
5. **Back panel port alignment tolerance stack-up** — printed shell warp + aluminum panel hole positions + Pi PCB tolerance + Pi's Z-offset above X1100 (~12 mm). Panel port centerlines are now at a non-zero vertical offset from panel-bottom. Mitigation: inset the aluminum shield with ~0.5 mm slop on each side AND add ±1 mm Z-tolerance for the ports (Pi's exact Z-offset depends on standoff vendor).
6. **LCD readability under bright ambient** — reflective/transflective LCDs with green backlight are readable in most conditions including modest direct light; full sun still challenging. Not a design goal for a desk unit.
7. **Assembly sequence ergonomics** — the u.FL connector on the LC29H is fragile AND becomes inaccessible once the adapter HAT is added on top. Wiring the SMA pigtail onto the LC29H BEFORE adding the adapter HAT is mandatory — if it's forgotten, the adapter HAT has to come off to access the u.FL. Document this as a bold warning in the assembly guide.
8. **USB3 bridge mechanical compatibility** — the X1100 ships with "a specially-made USB3.1 male-to-male bridge". Its exact length + orientation (90° vs. straight) affects Pi ↔ X1100 vertical spacing. Will verify on receipt of the X1100 kit.
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
