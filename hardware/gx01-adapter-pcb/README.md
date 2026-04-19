# GX-01 Adapter HAT — PCB

A small passthrough HAT that sits on top of the LC29H in the GX-01 stack and breaks out the Pi 5's GPIO into clean connectors for the KS0108B LCD (20-pin ribbon), two fan power outputs (JST-XH), and hosts the LCD's contrast trim + backlight current-limit passives.

**Form factor:** Standard Pi HAT — 65 × 56.5 mm, 4× M2.5 mounting holes at corners.
**Layers:** 2 (F.Cu signals + short power/analog traces, B.Cu GND pour).
**Components:** 11 (all through-hole for hand-soldering).
**LCD connector:** 1×20 pin header at 2.54 mm pitch — natively matches the GDM12864H's 1×20 solder pad layout; no custom ribbon cable required.
**Pitch alignment:** J1 (GPIO) and J2 (LCD) share the same X origin (7.11 mm) and 2.54 mm pitch, so J1 pin pair k and J2 pin k are in the same vertical column. This makes LCD signal routing a set of short, mostly-straight drops in the GUI router.
**Fab target:** OSH Park 2-layer (~$5 for 3 boards) or JLCPCB equivalent.

## Pipeline — fully automated

The design is 100% programmatic — run three Python scripts and you get DRC-clean Gerbers ready for upload. No GUI interaction required.

```bash
# 1. Generate netlist + run electrical rules check
python3 circuit.py
# → gx01-adapter.net, ERC clean

# 2. Generate PCB layout (footprints, nets, GND pour, minimal seed routing)
python3 layout.py
# → gx01-adapter.kicad_pcb (15 nets unrouted, zone pour present)

# 3. Auto-route all remaining signals via FreeRouting
python3 autoroute.py --passes 50
# → gx01-adapter.kicad_pcb (rewritten in place with all routes)
# → gx01-adapter.dsn (Specctra DSN export — FreeRouting input)
# → gx01-adapter.ses (Specctra session — FreeRouting output)
# → freerouting.log (autorouter log for debugging)

# 4. Run design rules check
kicad-cli pcb drc --output drc-report.txt --format report gx01-adapter.kicad_pcb
# Expect: 0 unconnected, 0 clearance violations, ~4 cosmetic warnings

# 5. Render previews
kicad-cli pcb render --output gx01-adapter-top-final.png --side top --quality high gx01-adapter.kicad_pcb
kicad-cli pcb render --output gx01-adapter-bottom-final.png --side bottom --quality high gx01-adapter.kicad_pcb

# 6. Export Gerbers + drill files
kicad-cli pcb export gerbers --output gerbers/ \
    --layers "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts" \
    gx01-adapter.kicad_pcb
kicad-cli pcb export drill --output gerbers/ gx01-adapter.kicad_pcb

# 7. Zip gerbers/ folder and upload to OSH Park / JLCPCB / PCBWay
zip -r gx01-adapter-gerbers.zip gerbers/
```

**Prerequisites:** KiCad 9.0+, Python 3.12+, `skidl` pip package, `default-jre-headless` (for FreeRouting), and the FreeRouting JAR at `tools/freerouting-2.1.0.jar` (downloadable via `gh release download v2.1.0 --repo freerouting/freerouting --pattern 'freerouting-*.jar' --dir tools/`).

**Typical runtime on Pi 5:** circuit.py ≈ 2 s, layout.py ≈ 2 s, autoroute.py ≈ 15 s (50 passes on this tiny board), DRC ≈ 1 s, renders ≈ 70 s (3D ray-trace), Gerber export ≈ 2 s. End-to-end: **~90 seconds** from source files to fab-ready Gerbers.

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

## How the routing works

**FreeRouting handles 100% of the signal routing** — an open-source Java autorouter (https://github.com/freerouting/freerouting) that takes Specctra DSN as input and produces SES session files. The `autoroute.py` orchestrator exports DSN from the unrouted board, invokes FreeRouting headlessly, imports the resulting SES back into the .kicad_pcb, and refills the GND pour so it respects the new traces.

What each script does:

- **`layout.py`** — places footprints, assigns nets to pads, draws the GND copper pour on B.Cu with circular keepouts at each mounting hole. Does NOT attempt signal routing (naive trace-drawing creates crossings and shorts; FreeRouting does it properly).
- **`autoroute.py`** — invokes FreeRouting on the output of `layout.py`. With 50 passes on this ~20-net design, it typically routes all 15 remaining nets in ~15 seconds with 45° bends, 0 clearance violations, and minimal vias (just 2 for the V0 trace that needs to cross from RV1's side of the board to J2's side).
- **Zone refill post-import** — critical step: the GND pour is filled BEFORE routing, so after SES import it's stale with respect to the new traces. `ZONE_FILLER.Fill(board.Zones())` regenerates the fill with proper clearances around every route.

Typical FreeRouting output for this board (see `freerouting.log`):
- 14 LCD signal traces + V0 + 5V distribution = fully routed
- 27 bends, all 45° (FreeRouting prefers angled routes for shorter path)
- 2 through-hole vias (for the V0 layer-switch)
- 0 clearance violations

## Known non-issues in DRC

After running the full pipeline, expect:
- **0 unconnected items** (everything routed)
- **0 clearance violations** (zone respects all traces)
- **1 "courtyard overlap"** between J1 and H1 — the GPIO socket's courtyard touches the mounting hole. Fabs ignore courtyards; cosmetic advisory.
- **3 silk warnings** — mounting hole reference labels clipped by board edge, and J1's reference label over its own copper area. Cosmetic; doesn't affect fab or function.

## Known non-issues in DRC

After running `kicad-cli pcb drc`, expect:
- **15 "unconnected items"** — the ratsnest waiting for GUI routing (expected)
- **1 "courtyard overlap"** between J1 and H1 — the GPIO socket's courtyard (mechanical keep-out advisory) touches the mounting hole. Fabs ignore courtyards; this is a review advisory, not a fab problem. Can be suppressed in KiCad's DRC rules if it bothers you.
- **3 silk warnings** — mounting hole reference labels clipped by board edge, and J1's reference label over its own copper area. Cosmetic; doesn't affect fab or function. Can be fixed by manually repositioning the silkscreen reference text in GUI.

After completing routing in GUI, the ratsnest should clear and DRC should report only the courtyard + silk warnings.

## Files

- `circuit.py` — SKiDL circuit definition (schematic-level)
- `layout.py` — pcbnew Python API layout generator
- `autoroute.py` — FreeRouting orchestrator (DSN export → route → SES import → zone refill)
- `tools/freerouting-2.1.0.jar` — FreeRouting autorouter (downloaded via `gh release download`)
- `gx01-adapter.net` — KiCad netlist output from `circuit.py`
- `gx01-adapter.kicad_pcb` — PCB layout file (routed after `autoroute.py`)
- `gx01-adapter.dsn` — Specctra design export (FreeRouting input)
- `gx01-adapter.ses` — Specctra session (FreeRouting output)
- `freerouting.log` — FreeRouting run log (includes statistics JSON at end)
- `gerbers/` — fab-ready Gerber and drill files
- `*-top-final.png`, `*-bottom-final.png` — rendered previews

## Next versions

v2 could add:
- HAT ID EEPROM (24AA025E48 or similar) on pins 27/28, making the board a proper HAT+ compliant device
- Front-panel header for 3× LED + 1× button + GND (6 pins, 2×3 header)
- Status LED on the HAT itself for power-up confirmation
- PWM-capable fan control circuit (MOSFET + PWM GPIO routing)

None of these are required for v1 function. v1 is intentionally minimum-viable.
