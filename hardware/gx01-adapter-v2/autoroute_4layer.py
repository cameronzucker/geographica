"""Autoroute pipeline for the 4-layer variant of the v2 HAT.

Same structure as autoroute.py but pointed at gx01-adapter-v2-4layer.kicad_pcb.
FreeRouting detects the 4 copper layers from the DSN automatically; inner
signal layers (In1.Cu, In2.Cu) become available routing surfaces, which
typically closes the last-mile routing problems seen on dense 2-layer boards.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import pcbnew


HERE = Path(__file__).parent.resolve()
PCB = HERE / "gx01-adapter-v2-4layer.kicad_pcb"
DSN = HERE / "gx01-adapter-v2-4layer.dsn"
SES = HERE / "gx01-adapter-v2-4layer.ses"
LOG = HERE / "freerouting-4layer.log"
FR_JAR = HERE / "tools" / "freerouting-2.1.0.jar"


def run_freerouting(dsn_path: Path, ses_path: Path, passes: int) -> int:
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
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passes", type=int, default=100)
    args = parser.parse_args()

    board = pcbnew.LoadBoard(str(PCB))
    print(f"4-layer board: {len(board.GetFootprints())} footprints, "
          f"{board.GetNetCount()} nets, "
          f"{board.GetDesignSettings().GetCopperLayerCount()} copper layers",
          file=sys.stderr)

    if not pcbnew.ExportSpecctraDSN(board, str(DSN)) or not DSN.exists():
        print("DSN export failed."); return 2
    print(f"DSN: {DSN.stat().st_size:,} bytes", file=sys.stderr)

    rc = run_freerouting(DSN, SES, args.passes)
    if rc != 0 or not SES.exists():
        print(f"FreeRouting didn't produce SES (rc={rc}). See {LOG}", file=sys.stderr); return 3
    print(f"SES: {SES.stat().st_size:,} bytes", file=sys.stderr)

    if not pcbnew.ImportSpecctraSES(board, str(SES)):
        print("SES import failed."); return 4

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB))
    print(f"Saved: {len(board.GetTracks())} tracks.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
