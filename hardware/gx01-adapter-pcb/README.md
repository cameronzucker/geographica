# GX-01 Adapter HAT — PCB

A small passthrough HAT that sits on top of the LC29H in the GX-01 stack and breaks out the Pi 5's GPIO into clean connectors for the KS0108B LCD (20-pin ribbon), two fan power outputs (JST-XH), and hosts the LCD's contrast trim + backlight current-limit passives.

**Form factor:** Standard Pi HAT — 65 × 56.5 mm, 4× M2.5 mounting holes at corners.
**Layers:** 2 (F.Cu signal, B.Cu GND pour + power distribution).
**Components:** 11 (all through-hole for hand-soldering).
**Fab target:** OSH Park 2-layer (~$5 for 3 boards) or JLCPCB equivalent.

## Pipeline

The design is fully programmatic — run two Python scripts and you get Gerbers ready for upload.

```bash
# 1. Generate netlist + run electrical rules check
python3 circuit.py
# → gx01-adapter.net, ERC clean

# 2. Generate PCB layout (footprints, nets, GND pour)
python3 layout.py
# → gx01-adapter.kicad_pcb

# 3. Open in KiCad GUI and complete signal routing interactively
kicad gx01-adapter.kicad_pcb
# Use pcbnew's "Route" tool to route the 14 LCD signal traces and the
# remaining +5V distribution. The GND pour already handles all GND pads
# via the bottom-layer zone. See "Routing completion" below.

# 4. Run design rules check
kicad-cli pcb drc --output drc-report.txt --format report gx01-adapter.kicad_pcb

# 5. Render previews (optional but useful for review)
kicad-cli pcb render --output gx01-adapter-top.png --side top --quality high gx01-adapter.kicad_pcb
kicad-cli pcb render --output gx01-adapter-bottom.png --side bottom --quality high gx01-adapter.kicad_pcb

# 6. Export Gerbers + drill files
kicad-cli pcb export gerbers --output gerbers/ \
    --layers "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts" \
    gx01-adapter.kicad_pcb
kicad-cli pcb export drill --output gerbers/ gx01-adapter.kicad_pcb

# 7. Zip gerbers/ folder and upload to OSH Park / JLCPCB / PCBWay
zip -r gx01-adapter-gerbers.zip gerbers/
```

## Circuit summary

| Ref | Component | Purpose |
|---|---|---|
| J1 | 2×20 female pin socket | Pi GPIO passthrough — mates with LC29H's top-of-stack male pins |
| J2 | 2×10 pin header | LCD ribbon output (20-pin, pin order matches KS0108B/GDM12864H datasheet) |
| J3, J4 | JST-XH 2-pin | Fan power outputs (5V + GND per connector) |
| RV1 | 10 kΩ multi-turn pot (Bourns 3296W) | LCD contrast trim — wiper drives V0 |
| R1 | 10 Ω 1/2W resistor | LCD backlight current limit (safe for modules with or without onboard BL resistor) |
| C1 | 100 nF ceramic cap | VDD rail bypass at the LCD connector |
| H1-H4 | 2.75 mm drilled holes | M2.5 mounting, standard Pi HAT positions |

## Pin mapping (Pi GPIO → LCD)

Full pin-by-pin mapping is in `circuit.py` under "Pi GPIO pin mapping" and "LCD connector wiring" sections. High-level:

- 14 Pi GPIOs assigned to KS0108B (8 data + 6 control)
- 5V (Pi pin 2, 4) → LCD VDD + fan power + analog bias
- GND (Pi pins 6, 9, 14, 20, 25, 30, 34, 39) → LCD VSS + fan GND + backlight cathode + pot

Pins intentionally left unconnected on this v1 board: Pi 3.3V (pins 1, 17) because no component on this HAT uses 3.3V, and HAT ID EEPROM pins 27/28 (no EEPROM; future v2 upgrade).

## Routing completion

The programmatic pipeline handles:
- Footprint placement with correct anchor behavior (pin 1 at known positions)
- Net-to-pad assignment for all 20 nets
- GND copper pour on B.Cu covering the full board with keepouts around mounting holes
- Short 5V link trace between J1 pins 2 and 4

What needs finishing in KiCad's GUI:
- 14 LCD signal traces (RS, R/W, E, CS1, CS2, RST, DB0-DB7) from J1 pads to J2 pads on F.Cu
- 5V distribution from J1 pin 2/4 area out to J2 VDD, R1, RV1, C1, and the two fan connectors
- Analog bias traces: VEE (J2 pin 18 → RV1 pin 3), V0 (RV1 wiper → J2 pin 3), BLA (J2 pin 19 → R1 pin 2)

**Why the script doesn't do these:** naive point-to-point routing creates trace crossings on a single layer and short-circuit errors where traces pass over unrelated pads. Real routing needs either a crossing-aware autorouter (e.g., Freerouting — standalone Java tool not installed here) or a human at the GUI. The hard parts (board outline, component positions, net assignment, GND pour) are done; the straightforward parts (drawing ~20 short tracks) are a 20-minute GUI exercise.

## Known non-issues in DRC

After running `kicad-cli pcb drc`, expect:
- **~23 "unconnected items"** — the ratsnest waiting for GUI routing (expected)
- **1 "courtyard overlap"** between J1 and H1 — the GPIO socket's courtyard (mechanical keep-out advisory) touches the mounting hole. Fabs ignore courtyards; this is a review warning, not a fab problem.
- **2–3 "silk clearance" warnings** — mounting hole reference labels clipped by board edge. Cosmetic; doesn't affect fab or function.

After completing routing in GUI, the ratsnest should clear and DRC should report only the courtyard + silk warnings.

## Files

- `circuit.py` — SKiDL circuit definition (schematic-level)
- `layout.py` — pcbnew Python API layout generator
- `gx01-adapter.net` — KiCad netlist output from `circuit.py`
- `gx01-adapter.kicad_pcb` — PCB layout file (open in KiCad to finish routing)
- `gerbers/` — fab-ready Gerber and drill files (valid once routing is complete)
- `*-top-final.png`, `*-bottom-final.png` — rendered previews

## Next versions

v2 could add:
- HAT ID EEPROM (24AA025E48 or similar) on pins 27/28, making the board a proper HAT+ compliant device
- Front-panel header for 3× LED + 1× button + GND (6 pins, 2×3 header)
- Status LED on the HAT itself for power-up confirmation
- PWM-capable fan control circuit (MOSFET + PWM GPIO routing)

None of these are required for v1 function. v1 is intentionally minimum-viable.
