"""
GX-01 Adapter HAT v2 — autorouter pipeline.

See autoroute.py in v1 (hardware/gx01-adapter-pcb/) for architecture notes.
This is the same script, pointed at the v2 board file.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import pcbnew


HERE = Path(__file__).parent.resolve()
PCB = HERE / "gx01-adapter-v2.kicad_pcb"
DSN = HERE / "gx01-adapter-v2.dsn"
SES = HERE / "gx01-adapter-v2.ses"
LOG = HERE / "freerouting.log"
FR_JAR = HERE / "tools" / "freerouting-2.1.0.jar"


def run_freerouting(dsn_path: Path, ses_path: Path, passes: int) -> int:
    if not FR_JAR.exists():
        print(f"FreeRouting JAR not found at {FR_JAR}", file=sys.stderr)
        return 1
    cmd = [
        "java", "-Xmx2g", "-Djava.awt.headless=true",
        "-jar", str(FR_JAR),
        "-de", str(dsn_path),
        "-do", str(ses_path),
        "-mp", str(passes),
        "-oit", "0.1",
    ]
    print(f"Invoking: {' '.join(cmd)}", file=sys.stderr)
    with LOG.open("w") as log_fh:
        proc = subprocess.run(cmd, stdout=log_fh, stderr=subprocess.STDOUT, cwd=str(HERE))
    print(f"FreeRouting exit code: {proc.returncode}", file=sys.stderr)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passes", type=int, default=200,
                        help="Max FreeRouting autorouter passes (default 200 — v2 is denser than v1)")
    args = parser.parse_args()

    board = pcbnew.LoadBoard(str(PCB))
    print(f"Loaded board: {len(board.GetFootprints())} footprints, "
          f"{board.GetNetCount()} nets, {len(board.GetTracks())} existing tracks.",
          file=sys.stderr)

    print(f"Exporting DSN to {DSN}", file=sys.stderr)
    if not pcbnew.ExportSpecctraDSN(board, str(DSN)) or not DSN.exists():
        print("DSN export failed.", file=sys.stderr); return 2
    print(f"DSN size: {DSN.stat().st_size:,} bytes", file=sys.stderr)

    rc = run_freerouting(DSN, SES, args.passes)
    if rc != 0 or not SES.exists():
        print(f"FreeRouting did not produce {SES}. See {LOG}", file=sys.stderr); return 3
    print(f"SES size: {SES.stat().st_size:,} bytes", file=sys.stderr)

    print(f"Importing SES from {SES}", file=sys.stderr)
    if not pcbnew.ImportSpecctraSES(board, str(SES)):
        print("SES import failed.", file=sys.stderr); return 4

    # CRITICAL: refill zones after SES import (kicad-scripted-pcb skill rule)
    print("Refilling zones...", file=sys.stderr)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    board.Save(str(PCB))
    print(f"Saved: {len(board.GetTracks())} tracks now on board.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
