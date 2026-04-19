#!/usr/bin/env python3
"""Generate a JLCPCB PCBA bundle from a KiCad project.

JLC's PCB Assembly service expects three things:
  1. Gerber files (zipped)
  2. A BOM (bill of materials) CSV with: Comment, Designator, Footprint,
     and the LCSC part number (their supplier — https://www.lcsc.com).
  3. A Component Placement (CPL) CSV with: Designator, Mid X, Mid Y,
     Layer (T/B), Rotation in degrees.

This script reads a .kicad_pcb + a YAML mapping of designators to LCSC
part numbers, then produces all three in one self-contained zip suitable
for direct upload at https://jlcpcb.com/capabilities/pcb-assembly.

Usage
-----

    python3 make_jlc_bundle.py \\
        --pcb hardware/gx01-adapter-pcb/gx01-adapter.kicad_pcb \\
        --mapping hardware/gx01-adapter-pcb/lcsc_mapping.yaml \\
        --gerbers hardware/gx01-adapter-pcb/gerbers/ \\
        --output hardware/gx01-adapter-pcb/jlc_bundle.zip

Mapping file format
-------------------

The YAML mapping file tells the script which LCSC part number to use for
each component designator on the board. Example (`lcsc_mapping.yaml`):

    # Optional top-level field. Skip components whose designators match
    # these regexes (e.g. mounting holes that don't need assembly).
    skip_patterns:
      - "^H[0-9]+$"    # H1, H2, ...

    parts:
      R1:
        lcsc: C17520
        tier: basic         # informational; helps cost estimation
        note: "10 Ω 1/4W axial"
      C1:
        lcsc: C14663
        tier: basic
      RV1:
        lcsc: C3296W-103
        tier: extended
      J1:
        lcsc: C124379
        tier: extended
      # ... etc

Every component on the board that's NOT matched by `skip_patterns` must
have an entry in `parts` with a non-null `lcsc` value — otherwise the
script errors out with a list of the missing entries (and suggests an
LCSC search URL for each).

Output
------

On success, writes a zip with this structure::

    bundle.zip
    ├── gerbers/
    │   ├── <your-board>-F_Cu.gtl
    │   ├── <your-board>-B_Cu.gbl
    │   ├── ... (all standard Gerbers + drill)
    ├── BOM.csv           # JLC's BOM format
    └── CPL.csv           # JLC's component-placement format

Also prints a summary (component counts by tier, estimated setup-fee
count, through-hole warning) to stderr.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    import pcbnew  # type: ignore


# ───────────────────────── Data model ─────────────────────────


@dataclass
class Component:
    """One placed component on the board, as JLC needs to understand it.

    Position / rotation / layer are deliberately absent — those are sourced
    from `kicad-cli pcb export pos` (see `extract_positions_via_kicad_cli`)
    so the CPL's coordinate system matches the Gerbers. pcbnew's raw
    GetPosition() returns Y in KiCad-internal (Y-down) coordinates, which
    doesn't match the Gerber (Y-up) convention JLC aligns against.
    """

    designator: str
    value: str
    footprint: str       # KiCad library:name
    is_smd: bool
    lcsc: str | None = None
    tier: str = "unknown"   # "basic" | "extended" | "unknown"


@dataclass
class BundleSummary:
    total_components: int = 0
    skipped: int = 0
    basic_tier_count: int = 0
    extended_tier_count: int = 0
    unknown_tier_count: int = 0
    through_hole_count: int = 0
    smd_count: int = 0
    missing_lcsc: list[str] = field(default_factory=list)


# ───────────────────────── Board extraction ─────────────────────────


def _is_smd(fp: "pcbnew.FOOTPRINT") -> bool:
    """Detect whether a footprint is surface-mount.

    Heuristic: if ANY pad is a through-hole pad, classify as through-hole.
    JLC's assembly machines handle SMD and through-hole separately.
    """
    import pcbnew
    for pad in fp.Pads():
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            return False
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            return False
    return True


def extract_components(pcb_path: Path) -> list[Component]:
    """Read a .kicad_pcb and return a list of placed Component objects."""
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb_path))
    components: list[Component] = []
    for fp in board.GetFootprints():
        components.append(
            Component(
                designator=fp.GetReference(),
                value=fp.GetValue(),
                footprint=fp.GetFPIDAsString(),
                is_smd=_is_smd(fp),
            )
        )
    # Stable ordering by designator (natural-ish — R1, R2, R10, R11 not R1, R10, R11, R2)
    def sort_key(c: Component) -> tuple:
        m = re.match(r"^([A-Z]+)([0-9]+)$", c.designator)
        if m:
            return (m.group(1), int(m.group(2)))
        return (c.designator, 0)
    components.sort(key=sort_key)
    return components


@dataclass
class Position:
    """One component's placement as JLC expects it in the CPL."""
    mid_x_mm: float
    mid_y_mm: float
    layer: str        # "Top" or "Bottom"
    rotation_deg: float


def extract_positions(pcb_path: Path) -> dict[str, Position]:
    """Return a {designator: Position} map with JLC-CPL-ready coordinates.

    Why this doesn't just shell out to `kicad-cli pcb export pos`:

    - KiCad's footprint position is the **anchor point**, which for many
      THT footprints (pin headers, sockets) is pin 1 — not the geometric
      center. JLC's CPL "Mid X/Mid Y" expects the **center of the pads**
      (the reference the pick-and-place machine uses). For a 2×20 socket,
      anchor-vs-center differs by ~24 mm and the component lands off-board.
    - `kicad-cli pcb export pos` passes the anchor through unchanged.
      KiCad's GUI has a "Use pad origin as reference" toggle that computes
      pad centroid, but kicad-cli doesn't expose it. So we compute it here.

    Coordinate conventions applied:
    - Pad-bounding-box center is computed in KiCad-internal coords.
    - Y is negated (KiCad is Y-down, Gerber & JLC CPL are Y-up).
    - The board's aux axis origin is subtracted so coords match Gerbers
      exported with `--use-drill-file-origin`. If aux origin is (0,0),
      this is a no-op.
    """
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb_path))
    aux = board.GetDesignSettings().GetAuxOrigin()
    aux_x_mm = pcbnew.ToMM(aux.x)
    aux_y_mm = pcbnew.ToMM(aux.y)

    positions: dict[str, Position] = {}
    for fp in board.GetFootprints():
        pad_bbox = None
        for pad in fp.Pads():
            b = pad.GetBoundingBox()
            if pad_bbox is None:
                pad_bbox = b
            else:
                pad_bbox.Merge(b)

        if pad_bbox is None:
            # No pads (e.g. graphical-only footprint). Fall back to anchor.
            anchor = fp.GetPosition()
            cx_mm = pcbnew.ToMM(anchor.x)
            cy_mm = pcbnew.ToMM(anchor.y)
        else:
            center = pad_bbox.GetCenter()
            cx_mm = pcbnew.ToMM(center.x)
            cy_mm = pcbnew.ToMM(center.y)

        layer_id = fp.GetLayer()
        layer = "Bottom" if layer_id == pcbnew.B_Cu else "Top"

        positions[fp.GetReference()] = Position(
            mid_x_mm=cx_mm - aux_x_mm,
            mid_y_mm=-(cy_mm - aux_y_mm),
            layer=layer,
            rotation_deg=fp.GetOrientationDegrees(),
        )
    return positions


# ───────────────────────── Mapping ─────────────────────────


def load_mapping(mapping_path: Path) -> dict:
    with mapping_path.open() as fh:
        data = yaml.safe_load(fh) or {}
    # Normalize: ensure keys exist
    data.setdefault("skip_patterns", [])
    data.setdefault("parts", {})
    # Compile patterns once
    data["_skip_regexes"] = [re.compile(p) for p in data["skip_patterns"]]
    return data


def should_skip(designator: str, mapping: dict) -> bool:
    return any(rx.match(designator) for rx in mapping["_skip_regexes"])


def apply_mapping(components: list[Component], mapping: dict) -> tuple[list[Component], BundleSummary]:
    """Return (assembled_components, summary). Assembled excludes skipped."""
    summary = BundleSummary(total_components=len(components))
    assembled: list[Component] = []

    for comp in components:
        if should_skip(comp.designator, mapping):
            summary.skipped += 1
            continue

        entry = mapping["parts"].get(comp.designator)
        if not entry or not entry.get("lcsc"):
            summary.missing_lcsc.append(comp.designator)
            continue

        comp.lcsc = entry["lcsc"]
        comp.tier = entry.get("tier", "unknown")
        if comp.tier == "basic":
            summary.basic_tier_count += 1
        elif comp.tier == "extended":
            summary.extended_tier_count += 1
        else:
            summary.unknown_tier_count += 1

        if comp.is_smd:
            summary.smd_count += 1
        else:
            summary.through_hole_count += 1

        assembled.append(comp)

    return assembled, summary


# ───────────────────────── Output formats ─────────────────────────


def render_bom_csv(components: list[Component]) -> str:
    """JLC BOM format: Comment, Designator, Footprint, LCSC Part #.

    Grouping key is (footprint, LCSC) — JLC's pick-and-place machines
    care about the physical LCSC part and its footprint. Designator
    labels (e.g., "Fan 1" vs "Fan 2") are cosmetic and shouldn't create
    separate line items. The Comment column shows the first value
    encountered, with a "+N more" hint if multiple distinct values
    collapse into one row.
    """
    groups: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    # value_lists tracks distinct comments seen per LCSC, used for hint text
    for c in components:
        key = (c.footprint, c.lcsc or "")
        designators, values = groups.setdefault(key, ([], []))
        designators.append(c.designator)
        if c.value not in values:
            values.append(c.value)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    for (footprint, lcsc), (designators, values) in sorted(groups.items()):
        comment = values[0]
        if len(values) > 1:
            comment = f"{values[0]} (+{len(values) - 1} others)"
        w.writerow([comment, ",".join(sorted(designators)), footprint, lcsc])
    return buf.getvalue()


def render_cpl_csv(components: list[Component], positions: dict[str, Position]) -> str:
    """JLC CPL format: Designator, Mid X, Mid Y, Layer, Rotation."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for c in components:
        p = positions.get(c.designator)
        if p is None:
            raise SystemExit(
                f"kicad-cli produced no position for {c.designator!r}. "
                f"pcbnew and kicad-cli read the same .kicad_pcb, so this "
                f"indicates a KiCad version mismatch or a malformed board."
            )
        w.writerow([
            c.designator,
            f"{p.mid_x_mm:.3f}",
            f"{p.mid_y_mm:.3f}",
            p.layer,
            f"{p.rotation_deg:.1f}",
        ])
    return buf.getvalue()


# ───────────────────────── Bundle assembly ─────────────────────────


def build_bundle(
    pcb_path: Path,
    mapping_path: Path,
    gerbers_dir: Path,
    output_zip: Path,
    dry_run: bool = False,
) -> BundleSummary:
    components = extract_components(pcb_path)
    mapping = load_mapping(mapping_path)
    assembled, summary = apply_mapping(components, mapping)

    if summary.missing_lcsc:
        lines = ["Missing LCSC part numbers in mapping:"]
        for des in summary.missing_lcsc:
            lines.append(f"  - {des}")
            lines.append(f"    search: https://www.lcsc.com/search?q={des}")
        raise SystemExit("\n".join(lines))

    positions = extract_positions(pcb_path)
    bom_csv = render_bom_csv(assembled)
    cpl_csv = render_cpl_csv(assembled, positions)

    if dry_run:
        print("─── BOM.csv ───", file=sys.stderr)
        print(bom_csv, file=sys.stderr)
        print("─── CPL.csv ───", file=sys.stderr)
        print(cpl_csv, file=sys.stderr)
        return summary

    gerber_files = sorted(gerbers_dir.glob("*.*"))
    if not gerber_files:
        raise SystemExit(f"No Gerber files found in {gerbers_dir}. Run `kicad-cli pcb export gerbers` first.")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for gf in gerber_files:
            zf.write(gf, arcname=f"gerbers/{gf.name}")
        zf.writestr("BOM.csv", bom_csv)
        zf.writestr("CPL.csv", cpl_csv)

    return summary


# ───────────────────────── CLI ─────────────────────────


def print_summary(summary: BundleSummary, output_zip: Path) -> None:
    print(f"\nJLC bundle: {output_zip}", file=sys.stderr)
    print(f"  Total components on board: {summary.total_components}", file=sys.stderr)
    print(f"  Skipped (per skip_patterns): {summary.skipped}", file=sys.stderr)
    print(f"  Assembled:", file=sys.stderr)
    print(f"    Basic-tier parts  : {summary.basic_tier_count}  (no setup fee)", file=sys.stderr)
    print(f"    Extended-tier parts: {summary.extended_tier_count}  (~$3 setup each)", file=sys.stderr)
    if summary.unknown_tier_count:
        print(f"    Unknown-tier parts: {summary.unknown_tier_count}  (check mapping)", file=sys.stderr)
    print(f"    SMD: {summary.smd_count}  |  Through-hole: {summary.through_hole_count}", file=sys.stderr)
    if summary.through_hole_count > 0 and summary.smd_count == 0:
        print(
            "\n⚠  All components are through-hole. JLC PCBA supports through-hole but at higher\n"
            "   per-pad cost than SMD (~$0.05-0.20/pad vs ~$0.015/pad). Through-hole assembly\n"
            "   is often not economical for small batches — hand-soldering may be cheaper below\n"
            "   ~10 boards. Consider SMD-equivalent parts where possible for future designs.",
            file=sys.stderr,
        )
    setup_fee_estimate = summary.extended_tier_count * 3
    if setup_fee_estimate > 0:
        print(f"\n  Estimated setup fees: ~${setup_fee_estimate} (${summary.extended_tier_count} Extended parts × $3)",
              file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a JLCPCB PCBA bundle from a KiCad project.")
    parser.add_argument("--pcb", type=Path, required=True, help="Path to .kicad_pcb file")
    parser.add_argument("--mapping", type=Path, required=True, help="Path to lcsc_mapping.yaml")
    parser.add_argument("--gerbers", type=Path, required=True, help="Directory containing Gerber files")
    parser.add_argument("--output", type=Path, required=True, help="Output .zip path")
    parser.add_argument("--dry-run", action="store_true", help="Print BOM + CPL to stderr without writing zip")
    args = parser.parse_args()

    for p in (args.pcb, args.mapping, args.gerbers):
        if not p.exists():
            raise SystemExit(f"Path not found: {p}")

    summary = build_bundle(
        args.pcb, args.mapping, args.gerbers, args.output,
        dry_run=args.dry_run,
    )
    print_summary(summary, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
