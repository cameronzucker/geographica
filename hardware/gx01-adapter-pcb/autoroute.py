"""
GX-01 Adapter HAT — autorouter pipeline.

Runs the full unrouted → routed pipeline:

  1. Load the .kicad_pcb produced by layout.py
  2. Export Specctra DSN file
  3. Invoke FreeRouting on the DSN (headless, N passes)
  4. Import the resulting SES session file back into the board
  5. Save the routed board
  6. Caller runs DRC and exports Gerbers separately

Run with:
  python3 autoroute.py [--passes N]

Outputs:
  gx01-adapter.dsn                 # exported design
  gx01-adapter.ses                 # autorouted session
  gx01-adapter.kicad_pcb           # rewritten in place with all routes
  freerouting.log                  # FreeRouting stdout/stderr
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import pcbnew


HERE = Path(__file__).parent.resolve()
PCB = HERE / "gx01-adapter.kicad_pcb"
DSN = HERE / "gx01-adapter.dsn"
SES = HERE / "gx01-adapter.ses"
LOG = HERE / "freerouting.log"
FR_JAR = HERE / "tools" / "freerouting-2.1.0.jar"


def run_freerouting(dsn_path: Path, ses_path: Path, passes: int) -> int:
    """Run FreeRouting on the DSN file, producing the SES.

    Uses --host 0.0.0.0 style arg is not needed; we're CLI-only.
    `gui.enabled=false` is set by writing a `freerouting.json` in the CWD
    (see FreeRouting docs/settings.md). Simpler: set system properties
    via -D args.
    """
    if not FR_JAR.exists():
        print(f"FreeRouting JAR not found at {FR_JAR}", file=sys.stderr)
        return 1

    cmd = [
        "java",
        # Limit JVM heap (adapter PCB is tiny, no need for default)
        "-Xmx2g",
        # Disable GUI attempts by setting the headless property
        "-Djava.awt.headless=true",
        "-jar",
        str(FR_JAR),
        "-de", str(dsn_path),   # design input
        "-do", str(ses_path),   # design output
        "-mp", str(passes),     # max passes
        "-oit", "0.1",          # optimizer improvement threshold
    ]

    print(f"Invoking: {' '.join(cmd)}", file=sys.stderr)
    with LOG.open("w") as log_fh:
        proc = subprocess.run(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=str(HERE),
        )
    print(f"FreeRouting exit code: {proc.returncode}", file=sys.stderr)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--passes",
        type=int,
        default=100,
        help="Max FreeRouting autorouter passes (default 100 — generous for tiny board)",
    )
    args = parser.parse_args()

    # Step 1: Load the unrouted .kicad_pcb
    board = pcbnew.LoadBoard(str(PCB))
    print(f"Loaded board with {len(board.GetFootprints())} footprints, "
          f"{len(board.GetTracks())} existing tracks.", file=sys.stderr)

    # Step 2: Export Specctra DSN
    print(f"Exporting DSN to {DSN}", file=sys.stderr)
    ok = pcbnew.ExportSpecctraDSN(board, str(DSN))
    if not ok or not DSN.exists():
        print("DSN export failed.", file=sys.stderr)
        return 2
    print(f"DSN size: {DSN.stat().st_size:,} bytes", file=sys.stderr)

    # Step 3: Run FreeRouting
    rc = run_freerouting(DSN, SES, args.passes)
    if rc != 0 or not SES.exists():
        print(f"FreeRouting did not produce {SES}. See {LOG}", file=sys.stderr)
        return 3
    print(f"SES size: {SES.stat().st_size:,} bytes", file=sys.stderr)

    # Step 4: Import SES back into the board
    print(f"Importing SES from {SES}", file=sys.stderr)
    ok = pcbnew.ImportSpecctraSES(board, str(SES))
    if not ok:
        print("SES import failed.", file=sys.stderr)
        return 4

    # Step 5: Refill zones so the GND pour respects the new traces
    # (stale pour from before SES import would overlap routed tracks and
    # produce zone-clearance DRC violations).
    print("Refilling zones to respect new routes...", file=sys.stderr)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    # Step 6: Save routed board
    print(f"Saving routed board to {PCB}", file=sys.stderr)
    board.Save(str(PCB))
    print(f"Routed: {len(board.GetTracks())} tracks now present.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
