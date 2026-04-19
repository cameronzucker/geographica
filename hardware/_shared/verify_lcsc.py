#!/usr/bin/env python3
"""Verify an lcsc_mapping.yaml against JLCPCB's live parts catalog.

Queries JLCPCB's undocumented-but-public parts-search endpoint for each
LCSC part number in the mapping file and reports any of:

  * PN not found in JLCPCB's PCBA catalog (can't be factory-assembled)
  * JLCPCB's search fuzzy-matched to a different componentCode (your PN
    may be wrong)
  * Tier mismatch — your YAML says 'basic' but JLCPCB says 'expand',
    or vice versa (affects setup fees)
  * Part out of stock
  * Low stock (<500) — may not be available when you order

Usage
-----

    python3 verify_lcsc.py --mapping hardware/gx01-adapter-pcb/lcsc_mapping.yaml

Options
-------

  --mapping PATH        The YAML file to verify (required)
  --update              After reporting, rewrite the mapping in place
                        with the authoritative data from JLCPCB (fuzzy-matched
                        componentCode replaces the declared one; tier
                        corrected to match JLCPCB's library classification).
                        NOTE: PyYAML's default serializer drops inline
                        comments. If your mapping file has hand-written
                        explanatory comments you want to keep, run without
                        --update and manually apply the suggested changes.
  --low-stock-threshold N
                        Warn when stock is below this number (default 500)

Exit codes
----------

  0   All parts verified, no issues
  1   One or more parts have issues — review output
  2   Network / API error — try again later

API reference
-------------

The endpoint used (POST https://jlcpcb.com/api/.../selectSmtComponentList)
is the same one JLCPCB's own website uses for its parts search UI.
It's not officially documented but has been stable for years and is
what every KiCad-JLCPCB integration plugin uses.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


JLCPCB_API_URL = (
    "https://jlcpcb.com/api/overseas-pcb-order/v1/"
    "shoppingCart/smtGood/selectSmtComponentList"
)

LIBRARY_TYPE_TO_TIER = {
    "base": "basic",
    "expand": "extended",
}


@dataclass
class PartRecord:
    """What JLCPCB returns for a part. Fields are None if not found."""

    query: str
    actual_code: str | None = None
    description: str | None = None
    model: str | None = None
    tier: str | None = None     # "basic" / "extended"
    stock: int | None = None
    min_purchase: int | None = None
    datasheet_url: str | None = None
    lcsc_url: str | None = None
    found: bool = False


def query_jlcpcb(lcsc_pn: str, timeout_s: float = 10.0) -> PartRecord:
    """POST to JLCPCB's search API; return parsed record or a not-found stub."""
    body = json.dumps({
        "keyword": lcsc_pn,
        "currentPage": 1,
        "pageSize": 1,
    }).encode("utf-8")

    req = urllib.request.Request(
        JLCPCB_API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux aarch64; rv:128.0) "
                "Gecko/20100101 Firefox/128.0"
            ),
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.load(resp)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error querying JLCPCB for {lcsc_pn}: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JLCPCB returned malformed JSON for {lcsc_pn}: {e}")

    results = payload.get("data", {}).get("componentPageInfo", {}).get("list", [])
    if not results:
        return PartRecord(query=lcsc_pn, found=False)

    c = results[0]
    return PartRecord(
        query=lcsc_pn,
        actual_code=c.get("componentCode"),
        description=c.get("componentTypeEn"),
        model=c.get("componentModelEn"),
        tier=LIBRARY_TYPE_TO_TIER.get(c.get("componentLibraryType"), "unknown"),
        stock=c.get("stockCount"),
        min_purchase=c.get("minPurchaseNum"),
        datasheet_url=c.get("dataManualUrl"),
        lcsc_url=c.get("lcscGoodsUrl"),
        found=True,
    )


@dataclass
class Issue:
    designator: str
    severity: str   # "error" / "warning"
    message: str


def check_footprint_type_mismatch(
    kicad_footprint: str | None,
    jlc_description: str | None,
) -> str | None:
    """Return a human-readable issue string if the KiCad footprint's
    mounting type (THT vs SMD) disagrees with JLCPCB's description.

    Heuristic — we don't decode every footprint name, just catch the
    common clear mismatches (an axial THT resistor mapped to a 0603
    chip-resistor LCSC PN, etc.).
    """
    if not kicad_footprint or not jlc_description:
        return None
    fp = kicad_footprint.lower()
    desc = jlc_description.lower()

    # Clear THT indicators in KiCad footprint name
    is_tht_fp = any(m in fp for m in [
        "_axial_", "_leaded", "pinsocket_", "pinheader_", "_tht",
        "potentiometer_bourns_3296", "conn_01x", "jst_xh", "jst_ph",
        "mountinghole", "_disc_", "r_axial", "c_disc",
    ])
    # Clear SMD indicators
    is_smd_fp = any(m in fp for m in [
        "_smd", "_0402", "_0603", "_0805", "_1206", "_1210", "_2012",
        "_soic", "_qfn", "_qfp", "_sot", "_tssop", "_chipcap",
    ])

    # Clear THT indicators in JLC description
    is_tht_desc = any(m in desc for m in [
        "through hole", "through-hole", "axial", "radial", "dip-",
    ])
    is_smd_desc = any(m in desc for m in [
        "smd/smt", "smd ", "surface mount", "chip resistor", "chip capacitor",
    ])

    if is_tht_fp and is_smd_desc and not is_tht_desc:
        return (f"KiCad footprint {kicad_footprint!r} is THROUGH-HOLE but JLCPCB "
                f"part is SMD ({jlc_description!r}). Parts won't physically fit.")
    if is_smd_fp and is_tht_desc and not is_smd_desc:
        return (f"KiCad footprint {kicad_footprint!r} is SMD but JLCPCB part is "
                f"THROUGH-HOLE ({jlc_description!r}). Parts won't physically fit.")
    return None


def verify_entry(
    designator: str,
    entry: dict[str, Any],
    low_stock: int,
    kicad_footprints: dict[str, str] | None = None,
) -> tuple[PartRecord, list[Issue]]:
    """Query JLCPCB for one mapping entry, return record + list of issues."""
    issues: list[Issue] = []
    lcsc_pn = entry.get("lcsc", "")
    declared_tier = entry.get("tier", "unknown")

    if not lcsc_pn:
        issues.append(Issue(designator, "error", "No LCSC part number in mapping."))
        return PartRecord(query="", found=False), issues

    # Per-request rate limit pause (JLC isn't aggressive but be polite)
    time.sleep(0.15)
    record = query_jlcpcb(lcsc_pn)

    if not record.found:
        issues.append(Issue(
            designator, "error",
            f"{lcsc_pn}: NOT FOUND in JLCPCB catalog. Either the PN is wrong, or the part "
            f"isn't carried by JLC for PCBA (you'd have to assemble by hand or find a "
            f"different LCSC part). Search: https://www.lcsc.com/search?q={lcsc_pn}"
        ))
        return record, issues

    if record.actual_code != lcsc_pn:
        issues.append(Issue(
            designator, "error",
            f"{lcsc_pn}: JLCPCB's search fuzzy-matched this to {record.actual_code!r} "
            f"({record.description!r}). Your declared PN probably doesn't exist. "
            f"If the matched PN is what you want, update the mapping to {record.actual_code}."
        ))

    if declared_tier in ("basic", "extended") and record.tier != declared_tier:
        issues.append(Issue(
            designator, "warning",
            f"{lcsc_pn}: declared tier={declared_tier!r} but JLCPCB says tier={record.tier!r}. "
            f"Update the mapping; this affects estimated setup fees."
        ))

    if record.stock is not None and record.stock == 0:
        issues.append(Issue(
            designator, "error",
            f"{lcsc_pn}: OUT OF STOCK at JLCPCB (0 units). Pick an alternative."
        ))
    elif record.stock is not None and record.stock < low_stock:
        issues.append(Issue(
            designator, "warning",
            f"{lcsc_pn}: low stock ({record.stock} < {low_stock}). May run out before "
            f"your order is fulfilled."
        ))

    # Cross-check footprint type (THT vs SMD) if we have the KiCad footprint
    if kicad_footprints and designator in kicad_footprints:
        mismatch = check_footprint_type_mismatch(kicad_footprints[designator], record.description)
        if mismatch:
            issues.append(Issue(designator, "error", mismatch))

    return record, issues


def print_report(
    designator: str,
    entry: dict[str, Any],
    record: PartRecord,
    issues: list[Issue],
) -> None:
    prefix = f"  {designator:<6}"
    if not record.found:
        print(f"{prefix} ✗ NOT FOUND  ({entry.get('lcsc', 'no PN')})")
    elif not issues:
        print(f"{prefix} ✓ {record.actual_code}  tier={record.tier}  "
              f"stock={record.stock:,}  {record.description}")
    else:
        # Report with severity-prefixed issue lines
        top_icon = "✗" if any(i.severity == "error" for i in issues) else "⚠"
        match = "" if record.actual_code == entry.get("lcsc") else f" (matched {record.actual_code})"
        print(f"{prefix} {top_icon} {record.actual_code}  tier={record.tier}  "
              f"stock={record.stock:,}  {record.description}{match}")
        for issue in issues:
            icon = "✗" if issue.severity == "error" else "⚠"
            print(f"    {icon}  {issue.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify LCSC mapping against JLCPCB's live catalog.")
    parser.add_argument("--mapping", type=Path, required=True, help="Path to lcsc_mapping.yaml")
    parser.add_argument("--pcb", type=Path, default=None,
                        help="Optional .kicad_pcb — enables footprint-type (THT vs SMD) sanity check")
    parser.add_argument("--low-stock-threshold", type=int, default=500,
                        help="Warn when stock is below this number (default 500)")
    parser.add_argument("--update", action="store_true",
                        help="Rewrite the mapping in place with verified data")
    args = parser.parse_args()

    if not args.mapping.exists():
        print(f"Mapping file not found: {args.mapping}", file=sys.stderr)
        return 2

    with args.mapping.open() as fh:
        mapping = yaml.safe_load(fh) or {}
    parts = mapping.get("parts", {})

    # Optional: load footprint info from the .kicad_pcb
    kicad_footprints: dict[str, str] = {}
    if args.pcb and args.pcb.exists():
        try:
            import pcbnew
            board = pcbnew.LoadBoard(str(args.pcb))
            for fp in board.GetFootprints():
                kicad_footprints[fp.GetReference()] = fp.GetFPIDAsString()
            print(f"Loaded {len(kicad_footprints)} KiCad footprints from {args.pcb}\n",
                  file=sys.stderr)
        except ImportError:
            print("Warning: pcbnew module not available; skipping footprint cross-check.",
                  file=sys.stderr)

    print(f"Verifying {len(parts)} parts against JLCPCB catalog...\n", file=sys.stderr)

    total_errors = 0
    total_warnings = 0
    all_records: dict[str, PartRecord] = {}
    all_issues: dict[str, list[Issue]] = {}

    for designator in sorted(parts.keys()):
        entry = parts[designator]
        try:
            record, issues = verify_entry(
                designator, entry, args.low_stock_threshold,
                kicad_footprints=kicad_footprints or None,
            )
        except RuntimeError as e:
            print(f"  {designator:<6} ? API error: {e}", file=sys.stderr)
            return 2

        all_records[designator] = record
        all_issues[designator] = issues
        print_report(designator, entry, record, issues)
        total_errors += sum(1 for i in issues if i.severity == "error")
        total_warnings += sum(1 for i in issues if i.severity == "warning")

    print(file=sys.stderr)
    print(f"Summary: {len(parts)} parts verified, "
          f"{total_errors} errors, {total_warnings} warnings.", file=sys.stderr)

    if args.update:
        updated_count = 0
        for designator, record in all_records.items():
            if not record.found:
                continue
            entry = parts[designator]
            # Accept the authoritative values from JLCPCB
            if record.actual_code and entry.get("lcsc") != record.actual_code:
                entry["lcsc"] = record.actual_code
                updated_count += 1
            if record.tier in ("basic", "extended") and entry.get("tier") != record.tier:
                entry["tier"] = record.tier
                updated_count += 1
        with args.mapping.open("w") as fh:
            yaml.safe_dump(mapping, fh, sort_keys=False)
        print(f"Mapping rewritten in place ({updated_count} fields updated).", file=sys.stderr)

    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
