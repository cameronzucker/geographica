# `_shared/` — KiCad → JLCPCB pipeline tools

Reusable scripts for any KiCad project that wants to be fabbable + assembled at JLCPCB. Both scripts work on any `.kicad_pcb` — not specific to GX-01.

## Tools

### `make_jlc_bundle.py` — turn KiCad output into a JLC-ready zip

Reads a `.kicad_pcb`, a directory of exported Gerbers, and a YAML mapping of designators to LCSC part numbers; produces a single zip that's uploadable at https://jlcpcb.com/capabilities/pcb-assembly with nothing further needed.

Output structure:

```
bundle.zip
├── gerbers/           # full set of Gerbers + drill file
├── BOM.csv            # JLC-format BOM (grouped by LCSC PN)
└── CPL.csv            # JLC-format pick-and-place (mm-accurate)
```

See `make_jlc_bundle.py` module docstring for YAML format, grouping rules, and CLI flags.

### `verify_lcsc.py` — validate mapping against JLCPCB's live catalog

Queries JLCPCB's public parts-search endpoint per LCSC PN in the mapping and flags:

- **NOT FOUND** — the PN isn't in JLC's PCBA catalog (can't be factory-assembled)
- **Fuzzy-matched** — JLC's search returned a DIFFERENT `componentCode`, meaning your declared PN probably doesn't exist
- **Tier mismatch** — your YAML claims `basic` but JLC classifies it `extended` (or vice versa), affecting setup fees
- **Stock issues** — out of stock or low stock (< default threshold 500)
- **Footprint type mismatch** (with `--pcb PATH.kicad_pcb`) — your KiCad footprint is THT but JLC part is SMD (or vice versa) — parts won't physically fit

Run with `--pcb` to enable the footprint sanity check; omit it for a pure API-level validation.

`--update` rewrites the mapping in place with verified values. **Caveat:** PyYAML's default serializer strips inline comments — if your mapping file has hand-written explanatory comments, run without `--update` and apply the suggested changes manually.

## Recommended workflow for a new KiCad project

1. Design the board in `circuit.py` + `layout.py` (SKiDL + pcbnew API).
2. Auto-route via FreeRouting (`autoroute.py`).
3. Export Gerbers (`kicad-cli pcb export gerbers`).
4. Create `lcsc_mapping.yaml` alongside the `.kicad_pcb`:
   - Pick an LCSC part number for each designator (look on https://www.lcsc.com or https://jlcpcb.com/parts)
   - Prefer **Basic Parts** (https://jlcpcb.com/parts/basic_parts) — no setup fee
5. Verify: `python3 make_jlc_bundle.py --pcb ... --mapping ... --gerbers ... --output ... --dry-run`
6. Verify live: `python3 verify_lcsc.py --mapping lcsc_mapping.yaml --pcb *.kicad_pcb`
7. Fix any issues flagged.
8. Real bundle: drop `--dry-run` from step 5.
9. Upload the zip at JLCPCB.

## Why we query JLCPCB directly rather than LCSC

LCSC's website is a JavaScript SPA — trafilatura (the backbone of the `url-to-markdown` skill) can't extract it. JLCPCB's own search backend, however, is a simple JSON API that accepts unauthenticated POST requests and returns everything we need about a part's PCBA status (stock, tier, pricing tiers, datasheet URL, LCSC product page URL). Every KiCad-JLCPCB integration plugin uses this same endpoint; it's been stable for years.

## Tested

Both tools work on a Raspberry Pi 5 with `python3-yaml`, `kicad` 9.0+, `skidl`, `pcbnew` Python bindings (ships with KiCad). `verify_lcsc.py` additionally requires internet access. No other dependencies.
