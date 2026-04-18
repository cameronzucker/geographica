# GX-01 Adapter PCB Fab + Assembly Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Order the GX-01 adapter HAT PCB from a fab house, procure the through-hole BOM, solder the board, and bench-verify it works before installation into the case (Plan 2 Phase 3).

**Architecture:** The PCB design is already complete and fully auto-routed (see `hardware/gx01-adapter-pcb/`). This plan covers the post-design workflow: verify the pipeline still runs clean → upload Gerbers to OSH Park → order through-hole parts from DigiKey → solder on receipt → bench-test with a multimeter and a Pi before integration.

**Tech Stack:** OSH Park (PCB fabricator, US-domestic), DigiKey (component supplier), hand-soldering with a Weller-class iron + leaded or lead-free solder + flux, multimeter for continuity + voltage verification, KiCad 9 GUI for visual review if desired.

**Prerequisite:** Plan 2 Task 0.6 (LC29H passthrough continuity) **must PASS** before ordering the PCB. If passthrough fails, the PCB needs a design change (the adapter HAT moves between AI HAT+ 2 and LC29H instead of on top) before fabbing.

---

## File structure (existing, just referenced)

- `hardware/gx01-adapter-pcb/circuit.py` — SKiDL circuit
- `hardware/gx01-adapter-pcb/layout.py` — pcbnew layout
- `hardware/gx01-adapter-pcb/autoroute.py` — FreeRouting pipeline
- `hardware/gx01-adapter-pcb/gerbers/` — fab output (generated)
- `hardware/gx01-adapter-pcb/BOM.md` — this plan creates it

---

## Phase 0: Pipeline verification (dry run)

### Task 0.1: Run the full pipeline end-to-end

**Files:** `hardware/gx01-adapter-pcb/`

- [ ] Run in that directory:

```bash
cd hardware/gx01-adapter-pcb
python3 circuit.py 2>&1 | tail -5
python3 layout.py 2>&1 | tail -5
python3 autoroute.py --passes 50 2>&1 | tail -5
```

- [ ] Expected output on each: "ERC: 0 errors", "Footprints: 11, Nets: 20, Tracks: 58", "Routed: 58 tracks now present."
- [ ] If any step errors: check for missing deps (`pip install --user --break-system-packages skidl` if SKiDL is missing), or check that `default-jre-headless` + `tools/freerouting-2.1.0.jar` are in place.

### Task 0.2: Run DRC

- [ ] Run: `kicad-cli pcb drc --output drc-report.txt --format report gx01-adapter.kicad_pcb`
- [ ] Open `drc-report.txt`
- [ ] Verify: "Found 4 violations" (all cosmetic) and "Found 0 unconnected items"
- [ ] If more than 4 violations or any unconnected items: routing is not clean; see `README.md` troubleshooting section before proceeding

### Task 0.3: Re-render previews

```bash
kicad-cli pcb render --output gx01-adapter-top-final.png --side top --quality high --zoom 1.0 gx01-adapter.kicad_pcb
kicad-cli pcb render --output gx01-adapter-bottom-final.png --side bottom --quality high --zoom 1.0 gx01-adapter.kicad_pcb
```

- [ ] Open both PNGs. Visually verify: all traces between J1 and J2 present on top layer, GND pour + routed traces visible on bottom, mounting holes have keepouts around them.

### Task 0.4: Re-export Gerbers

```bash
rm -rf gerbers && mkdir gerbers
kicad-cli pcb export gerbers --output gerbers/ \
    --layers "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts" \
    gx01-adapter.kicad_pcb
kicad-cli pcb export drill --output gerbers/ gx01-adapter.kicad_pcb
ls gerbers/ | wc -l  # should be 9
```

- [ ] Verify: 9 files in `gerbers/`: F_Cu, B_Cu, F_Mask, B_Mask, F_Silkscreen, B_Silkscreen, Edge_Cuts, drill file, job file

### Task 0.5: Sanity-check Gerbers in gerbv

```bash
gerbv gerbers/gx01-adapter-F_Cu.gtl gerbers/gx01-adapter-B_Cu.gbl gerbers/gx01-adapter-Edge_Cuts.gm1 &
```

- [ ] In gerbv: set F.Cu to red, B.Cu to blue, Edge.Cuts to black. Visually verify layers look correct — traces present, no floating copper islands, edge cuts is a closed rectangle.

### Task 0.6: Zip Gerbers for upload

```bash
cd hardware/gx01-adapter-pcb/gerbers
zip gx01-adapter-gerbers-v1.zip gx01-adapter-*.g* gx01-adapter.drl gx01-adapter-job.gbrjob
ls -la gx01-adapter-gerbers-v1.zip
```

- [ ] Expected: single zip file, ~50-100 KB

---

## Phase 1: Order PCB from OSH Park

### Task 1.1: Create OSH Park account (if needed)

- [ ] Browser: https://oshpark.com/users/sign_up
- [ ] Create account (free; pay per order)

### Task 1.2: Upload Gerbers

- [ ] Browser: https://oshpark.com
- [ ] Click "Upload" → select `gx01-adapter-gerbers-v1.zip`
- [ ] OSH Park auto-detects layer count and board size. Verify:
  - Layers: 2
  - Board size: ~65 × 56.5 mm (~2.56 × 2.22 inch)
  - Expected price: ~$5.20 for 3 boards (at US domestic $5/sq-in for 2-layer)

### Task 1.3: Visual review OSH Park's rendering

- [ ] OSH Park shows a preview of each layer before you check out. Visually confirm:
  - Top copper: all traces + pads + J1/J2 connector patterns visible
  - Bottom copper: GND pour covers ~80% of the board with circular keepouts around mounting holes
  - Silkscreen: component references visible (J1, J2, J3, J4, RV1, R1, C1, H1-H4)
  - Drill: all holes in expected positions
- [ ] If anything looks wrong: CANCEL before checkout, investigate

### Task 1.4: Checkout + ship

- [ ] Proceed to checkout
- [ ] Expected total: $5.20 (3 boards, free US shipping)
- [ ] Expected delivery: ~10-14 days

### Task 1.5: Record order

- [ ] Update `hardware/gx01-adapter-pcb/README.md` with the OSH Park order number + date for reference

---

## Phase 2: Procure BOM from DigiKey

### Task 2.1: Write the BOM document

**Files:** `hardware/gx01-adapter-pcb/BOM.md`

- [ ] Create with this content:

```markdown
# GX-01 Adapter HAT Bill of Materials

Order from DigiKey (or Mouser / any distributor). All through-hole, all 2.54 mm pitch.

| Ref | Qty | Part | DigiKey PN | Price ea | Notes |
|---|---|---|---|---|---|
| J1 | 1 | 2×20 pin socket, 2.54 mm pitch, THT, 8.5 mm mating height | S7109-ND or S7111-ND | ~$2.00 | Female; "stacking" height; mates with LC29H's top header |
| J2 | 1 | 1×20 pin header, 2.54 mm pitch, THT | S1011EC-20-ND | ~$0.40 | Breakaway strip, snap to length if needed |
| J3, J4 | 2 | JST-XH 2-pin male vertical header, 2.50 mm pitch | 455-1749-ND | ~$0.30 | For fan connectors |
| RV1 | 1 | Bourns 3296W 10 kΩ trim pot, vertical | 3296W-1-103LF-ND | ~$2.50 | 10k multi-turn |
| R1 | 1 | 10 Ω 1/2 W axial resistor | CF12JT10R0CT-ND | ~$0.10 | Backlight current limit |
| C1 | 1 | 100 nF ceramic disc cap, 2.54 mm pitch | 478-6007-ND | ~$0.15 | X7R, 50 V+ |
| — | 4 | M3 × 5 mm heat-set brass insert | 97395A418 (McMaster) | ~$1.00 | For shell mounting |
| — | ~20 | M3 × 8 mm socket cap screws, stainless or bronze PVD | 92095A182 (McMaster) | ~$0.20 | |
| — | ~20 | M3 × 5 mm heat-set brass inserts | 94459A130 (McMaster) | ~$0.50 | |
| — | 1 | 20-conductor female-female DuPont jumper wire set | 1528-1443-ND | ~$5.00 | Connects J2 to LCD module |

**Estimated total:** ~$25 from DigiKey + ~$10 shipping. Include 10-20% extras on the cheap resistors and caps in case you want to tune later.
```

- [ ] Commit: `docs(pcb): BOM for GX-01 adapter HAT`

### Task 2.2: Order from DigiKey

- [ ] Browser: https://www.digikey.com — paste each P/N into search, add to cart
- [ ] Verify cart totals match BOM estimate within ~$5
- [ ] Select standard shipping (3-5 days USPS)
- [ ] Checkout

### Task 2.3: (Optional) Order LCD if not already in hand

If you haven't ordered the LCD yet (SparkFun GDM12864H LCD-00710):

- [ ] Browser: https://www.sparkfun.com/products/710 (or whatever URL the LCD-00710 lives at)
- [ ] Order 1× LCD + the 1×20 female-to-female ribbon or 20-conductor cable if listed

---

## Phase 3: Receive PCBs + solder

### Task 3.1: On PCB receipt, visual inspection

- [ ] Unpack 3 boards
- [ ] Check for: visible shorts between adjacent pads, missing pads, silk misalignment, bent PCB. If any board has issues, set it aside; use a clean one for the build.
- [ ] Photograph the bare board for reference

### Task 3.2: Populate the board — easiest components first

Order matters for hand-soldering: shortest parts first so they don't interfere with later placement.

- [ ] Solder R1 (10 Ω axial resistor) flat against the board, trim leads flush
- [ ] Solder C1 (100 nF disc cap) flush, trim leads
- [ ] Solder J3 + J4 (JST-XH 2-pin headers) — verify pin 1 orientation matches the silkscreen
- [ ] Solder RV1 (trim pot) — verify pin 1 orientation
- [ ] Solder J2 (1×20 header) — use a jig or tape to keep perfectly perpendicular while soldering one end pin, then check angle before doing the rest
- [ ] Solder J1 (2×20 socket) LAST — tallest part, hardest to rework if misaligned. Again use tape/jig to hold perpendicular.

### Task 3.3: Verify solder joints

- [ ] Under magnification (4× loupe or USB microscope), inspect every joint for: cold joints (grainy surface), solder bridges between adjacent pads, unsoldered pins
- [ ] Clean flux residue with IPA + brush

### Task 3.4: Continuity testing with multimeter

With the board naked (nothing mated):

- [ ] Set multimeter to continuity mode
- [ ] Probe pin 1 of J1 (3.3V on Pi) to any other J1 pin — expect OPEN except for pin 17 (also 3.3V on Pi, but our board leaves these unconnected; so expect OPEN to every J1 pin).
- [ ] Probe pin 2 of J1 (5V) to: J1 pin 4, J2 pin 2, J3 pin 1, J4 pin 1, R1 pin 1, RV1 pin 1, C1 pin 1 — ALL should read CONTINUOUS (short, ~0 Ω)
- [ ] Probe pin 6 of J1 (GND) to: all other J1 GND pins (9, 14, 20, 25, 30, 34, 39), J2 pin 1, J2 pin 20, J3 pin 2, J4 pin 2, C1 pin 2 — ALL should read CONTINUOUS (via the GND pour)
- [ ] Probe pin 11 of J1 (LCD_RS) to J2 pin 4 — should read CONTINUOUS
- [ ] (Optionally spot-check 2-3 more LCD signal routes: J1 pin 33 to J2 pin 15 (CS1), J1 pin 40 to J2 pin 12 (DB5), etc.)
- [ ] **Critical:** probe J1 pin 2 (5V) to J1 pin 6 (GND) — must read OPEN. If it reads CONTINUOUS, there's a SHORT somewhere; DO NOT proceed with power-on. Inspect board under magnification.

### Task 3.5: Record verification

- [ ] Update `hardware/gx01-adapter-pcb/BOM.md` or create `hardware/gx01-adapter-pcb/VERIFICATION.md` with: continuity test results, date, any issues found
- [ ] Commit: `docs(pcb): soldering + continuity verification for build v1`

---

## Phase 4: Bench test before case integration

### Task 4.1: Standalone power test (optional but recommended)

Before stacking on the LC29H:

- [ ] Inject 5 V into J1 pin 2 (and GND into J1 pin 6) from a bench supply with current limit set to 100 mA
- [ ] Verify: current draw < 50 mA (essentially zero — no active components yet)
- [ ] Probe VDD at J2 pin 2 — should read 5.00 ± 0.05 V
- [ ] Probe between RV1 wiper (pin 2) and GND — adjust RV1; voltage should sweep smoothly between ~0 V and +5 V

### Task 4.2: Stack test on actual Pi (without LCD)

- [ ] Power off the existing running stack
- [ ] Mount the adapter HAT on top of the LC29H (without the LCD connected yet)
- [ ] Power on
- [ ] Verify Pi boots normally, no current spike, no unusual LED behavior on Pi or X1207
- [ ] SSH in, run: `sudo i2cdetect -y 1` to verify LC29H still enumerates (no GPIO interference from adapter HAT)

### Task 4.3: Connect LCD + verify driver responds

This step depends on Plan 1 Phase 2 being complete (`services/status-lcd` installed).

- [ ] Connect the 20-conductor ribbon: J2 on adapter HAT ↔ LCD module
- [ ] Ensure ribbon orientation is correct (pin 1 to pin 1 — indicated by a red stripe or pin-1 marking)
- [ ] Power on
- [ ] LCD should initialize: backlight comes on, driver logo or boot screen appears
- [ ] Adjust RV1 until characters are legible (contrast usually mid-travel on the pot)

### Task 4.4: Connect fans + verify spin-up

- [ ] Plug a fan into J3 (any Noctua NF-A4x10 5V will do for this test)
- [ ] Power on: fan should spin immediately
- [ ] Measure air movement (paper sheet test — fan should visibly flutter a page held in front of it)
- [ ] Repeat with J4

### Task 4.5: Full stack smoke test — the moment of truth

- [ ] Assemble the full stack: X1100 + SSD + Pi + X1207 + 21700 + AI HAT+ 2 + LC29H + GX-01 adapter HAT + LCD + 2× fans
- [ ] Power on via PoE injector
- [ ] Expected: Pi boots, LCD shows status daemon output with live network/GPS/battery stats, both fans spinning, LCD backlight steady
- [ ] Record any issues for troubleshooting before case assembly (Plan 2 Phase 3)

### Task 4.6: Commit final state

- [ ] `git add hardware/gx01-adapter-pcb/` and commit any updates to BOM / VERIFICATION / README
- [ ] Tag this milestone: `git tag gx-01-pcb-v1-verified`

---

## Spec → task coverage check

| Spec requirement | Plan task |
|---|---|
| Custom 2-layer adapter HAT | Phase 0 (pipeline run), Phase 1 (fab), Phase 3 (solder) |
| 2×20 GPIO socket + 1×20 LCD + 2× JST-XH | Task 3.2 (solder components) |
| RV1 contrast trim + R1 BL resistor + C1 bypass | Task 3.2 + Task 4.1 voltage sweep |
| Gerbers from programmatic pipeline | Tasks 0.1-0.6 |
| LC29H 40-pin passthrough dependency | Task 0 prerequisite (Plan 2 Task 0.6) |

Spec risks directly addressed:

| Spec risk | Plan task |
|---|---|
| LC29H passthrough completeness | Prerequisite, Task 0 gate before fab |
| Fan power wiring | Task 4.4 fan spin-up test |

## Execution

This plan is gated on physical delivery (PCBs from OSH Park: 10-14 days; BOM from DigiKey: 3-5 days). Use **superpowers:executing-plans** in batch mode with explicit waits after Tasks 1.4 (PCB order placed) and 2.2 (BOM order placed). Phase 3 can't start until both arrive.
