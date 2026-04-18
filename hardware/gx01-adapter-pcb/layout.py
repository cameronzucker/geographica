"""
GX-01 Adapter HAT — pcbnew layout generator.

Reads the netlist from circuit.py and produces a fully-placed 2-layer PCB.
Components positioned on a standard Pi HAT footprint (65 × 56.5 mm, mounting
holes per official HAT mechanical spec). Traces are left to auto-route or
manual routing after opening in KiCad GUI — this script produces a board
with all footprints placed, nets associated, and board outline drawn.

Run with:
  python3 layout.py

Outputs:
  gx01-adapter.kicad_pcb
"""
import os
import re
import sys

import pcbnew
from pcbnew import FromMM as MM
from pcbnew import VECTOR2I, BOX2I


BOARD_W_MM = 65.0
BOARD_H_MM = 56.5
BOARD_OUTLINE_WIDTH_MM = 0.15

# Standard Pi HAT mounting hole positions (mm from board top-left):
MOUNTING_HOLES_MM = [
    (3.5, 3.5),
    (61.5, 3.5),
    (3.5, 52.5),
    (61.5, 52.5),
]


# ───────────────────────── Helpers ─────────────────────────


def load_footprint(lib_name: str, fp_name: str) -> pcbnew.FOOTPRINT:
    """Load a footprint from the system KiCad library."""
    lib_path = f"/usr/share/kicad/footprints/{lib_name}.pretty"
    fp = pcbnew.FootprintLoad(lib_path, fp_name)
    if fp is None:
        raise RuntimeError(f"Could not load footprint {lib_name}:{fp_name} from {lib_path}")
    return fp


def place(
    board: pcbnew.BOARD,
    fp: pcbnew.FOOTPRINT,
    reference: str,
    value: str,
    x_mm: float,
    y_mm: float,
    rotation_deg: float = 0.0,
) -> pcbnew.FOOTPRINT:
    """Add a footprint to the board at the given position + rotation."""
    fp.SetReference(reference)
    fp.SetValue(value)
    fp.SetPosition(VECTOR2I(MM(x_mm), MM(y_mm)))
    if rotation_deg:
        fp.SetOrientationDegrees(rotation_deg)
    board.Add(fp)
    return fp


def ensure_net(board: pcbnew.BOARD, name: str) -> pcbnew.NETINFO_ITEM:
    """Return an existing NETINFO_ITEM by name, or create it if missing."""
    nets = board.GetNetsByName()
    if name in nets:
        return nets[name]
    net = pcbnew.NETINFO_ITEM(board, name)
    board.Add(net)
    return net


def connect_pad(fp: pcbnew.FOOTPRINT, pad_name: str, net: pcbnew.NETINFO_ITEM) -> None:
    """Assign a net to a named pad on a footprint."""
    pad = fp.FindPadByNumber(pad_name)
    if pad is None:
        raise RuntimeError(f"Pad {pad_name!r} not found on {fp.GetReference()}")
    pad.SetNet(net)


# ───────────────────────── Build board ─────────────────────────

out_path = os.path.abspath("gx01-adapter.kicad_pcb")

board = pcbnew.NewBoard(out_path)

# Board outline: simple rectangle on Edge.Cuts layer
edge_cuts = board.GetLayerID("Edge.Cuts")
corners = [
    (0, 0),
    (BOARD_W_MM, 0),
    (BOARD_W_MM, BOARD_H_MM),
    (0, BOARD_H_MM),
]
for i in range(4):
    x1, y1 = corners[i]
    x2, y2 = corners[(i + 1) % 4]
    seg = pcbnew.PCB_SHAPE(board)
    seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
    seg.SetLayer(edge_cuts)
    seg.SetStart(VECTOR2I(MM(x1), MM(y1)))
    seg.SetEnd(VECTOR2I(MM(x2), MM(y2)))
    seg.SetWidth(MM(BOARD_OUTLINE_WIDTH_MM))
    board.Add(seg)


# ───────────────────────── Place mounting holes ─────────────────────────
for i, (x, y) in enumerate(MOUNTING_HOLES_MM, start=1):
    fp = load_footprint("MountingHole", "MountingHole_2.7mm_M2.5")
    place(board, fp, f"H{i}", "MH_2.75", x, y)


# ───────────────────────── Place connectors + passives ─────────────────────────

# J1 — Pi GPIO 40-pin female socket along top edge.
# KiCad's 2x20 socket footprint has its natural orientation with the 20-pin
# axis along Y. Rotating 90° makes the 20-pin axis run along X (left-to-right),
# which is what HAT boards need to line up with the Pi's GPIO header.
# After 90° rotation, pin 1 lands at the left end of the connector.
# Place center at (32.5, 6.04) so the connector spans X ≈ 8.37 to X ≈ 56.63.
j1 = load_footprint(
    "Connector_PinSocket_2.54mm",
    "PinSocket_2x20_P2.54mm_Vertical",
)
place(board, j1, "J1", "Pi GPIO 40-pin", 7.11, 3.5, rotation_deg=90.0)

# J2 — LCD 2x10 pin header, horizontal, below GPIO socket.
# After 90° rotation, spans X ≈ 10.67 to X ≈ 33.53 (width = 9*2.54 = 22.86 mm).
# Placed on left half of board, leaving the right half for passive components
# and the LCD's ribbon cable to naturally run off the left edge toward the
# front panel.
j2 = load_footprint(
    "Connector_PinHeader_2.54mm",
    "PinHeader_2x10_P2.54mm_Vertical",
)
place(board, j2, "J2", "LCD 20-pin IDC", 8.0, 16.0, rotation_deg=90.0)

# J3, J4 — JST-XH 2-pin fan power, bottom edge of board.
# Natural orientation of JST-XH Vertical has the 2-pin axis along Y; leaving
# unrotated puts the cable exit pointing down (out the bottom edge of the
# board), which is convenient for fan wiring inside the case.
j3 = load_footprint("Connector_JST", "JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical")
place(board, j3, "J3", "Fan 1", 14.0, 48.0)

j4 = load_footprint("Connector_JST", "JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical")
place(board, j4, "J4", "Fan 2", 26.0, 48.0)

# RV1 — Contrast trim pot (Bourns 3296W, vertical multi-turn trimmer)
rv1 = load_footprint(
    "Potentiometer_THT",
    "Potentiometer_Bourns_3296W_Vertical",
)
place(board, rv1, "RV1", "10k", 47.0, 30.0)

# R1 — Backlight current-limit resistor (axial THT, horizontal)
r1 = load_footprint(
    "Resistor_THT",
    "R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
)
place(board, r1, "R1", "10R", 46.0, 20.0)

# C1 — Bypass cap (disc ceramic, 2.5mm lead spacing)
c1 = load_footprint("Capacitor_THT", "C_Disc_D3.0mm_W2.0mm_P2.50mm")
place(board, c1, "C1", "100nF", 46.0, 44.0)


# ───────────────────────── Create nets + associate pads ─────────────────────────

# Create all nets used in the circuit
net_5v = ensure_net(board, "+5V")
net_gnd = ensure_net(board, "GND")
net_vee = ensure_net(board, "VEE")
net_v0 = ensure_net(board, "V0")
net_bla = ensure_net(board, "BLA")
net_rs = ensure_net(board, "LCD_RS")
net_rw = ensure_net(board, "LCD_RW")
net_en = ensure_net(board, "LCD_E")
net_cs1 = ensure_net(board, "LCD_CS1")
net_cs2 = ensure_net(board, "LCD_CS2")
net_rst = ensure_net(board, "LCD_RST")
net_db = [ensure_net(board, f"LCD_DB{i}") for i in range(8)]

# J1 — Pi GPIO socket pad mapping
# Pi 5 GPIO header pin numbering (physical):
for pad, net in [
    ("2", net_5v), ("4", net_5v),
    ("6", net_gnd), ("9", net_gnd), ("14", net_gnd), ("20", net_gnd),
    ("25", net_gnd), ("30", net_gnd), ("34", net_gnd), ("39", net_gnd),
    ("11", net_rs),   # GPIO17
    ("13", net_rw),   # GPIO27
    ("15", net_en),   # GPIO22
    ("16", net_cs1),  # GPIO23
    ("18", net_cs2),  # GPIO24
    ("22", net_rst),  # GPIO25
    ("37", net_db[0]),  # GPIO26
    ("36", net_db[1]),  # GPIO16
    ("35", net_db[2]),  # GPIO19
    ("33", net_db[3]),  # GPIO13
    ("32", net_db[4]),  # GPIO12
    ("31", net_db[5]),  # GPIO6
    ("29", net_db[6]),  # GPIO5
    ("40", net_db[7]),  # GPIO21
]:
    connect_pad(j1, pad, net)

# J2 — LCD pad mapping (per GDM12864H datasheet)
for pad, net in [
    ("1", net_gnd),   # VSS
    ("2", net_5v),    # VDD
    ("3", net_v0),    # V0 (contrast)
    ("4", net_rs),
    ("5", net_rw),
    ("6", net_en),
    ("7", net_db[0]), ("8", net_db[1]), ("9", net_db[2]), ("10", net_db[3]),
    ("11", net_db[4]), ("12", net_db[5]), ("13", net_db[6]), ("14", net_db[7]),
    ("15", net_cs1),
    ("16", net_cs2),
    ("17", net_rst),
    ("18", net_vee),  # Vee output from LCD
    ("19", net_bla),  # Backlight anode
    ("20", net_gnd),  # Backlight cathode
]:
    connect_pad(j2, pad, net)

# J3, J4 — fan power
for fp in (j3, j4):
    connect_pad(fp, "1", net_5v)
    connect_pad(fp, "2", net_gnd)

# RV1 — pot (KiCad "R_Potentiometer" footprint uses pad names "1" "2" "3")
connect_pad(rv1, "1", net_5v)
connect_pad(rv1, "2", net_v0)  # wiper
connect_pad(rv1, "3", net_vee)

# R1 — BL current limit (pads "1" and "2")
connect_pad(r1, "1", net_5v)
connect_pad(r1, "2", net_bla)

# C1 — bypass cap
connect_pad(c1, "1", net_5v)
connect_pad(c1, "2", net_gnd)


# ───────────────────────── Routing ─────────────────────────
# Strategy: two-layer board, signals on F.Cu (top), power/ground on B.Cu
# (bottom). Straight-line routing where possible; this is a low-density
# board with generous free space, so most signals can go point-to-point
# without crossings.
#
# Trace widths:
#   Signals:         0.25 mm (10 mil) — plenty for low-speed parallel LCD
#   Power/ground:    0.50 mm (20 mil) — carries up to ~500 mA combined fan + LCD
#   Clearance:       0.20 mm default — comfortably within cheap-fab capability

F_CU = board.GetLayerID("F.Cu")
B_CU = board.GetLayerID("B.Cu")


def add_track(
    layer_id: int,
    start: pcbnew.VECTOR2I,
    end: pcbnew.VECTOR2I,
    net: pcbnew.NETINFO_ITEM,
    width_mm: float = 0.25,
) -> None:
    """Add a single PCB track segment on the specified layer."""
    track = pcbnew.PCB_TRACK(board)
    track.SetLayer(layer_id)
    track.SetStart(start)
    track.SetEnd(end)
    track.SetWidth(MM(width_mm))
    track.SetNet(net)
    board.Add(track)


def connect_pads(
    fp_a: pcbnew.FOOTPRINT,
    pad_a: str,
    fp_b: pcbnew.FOOTPRINT,
    pad_b: str,
    layer_id: int,
    net: pcbnew.NETINFO_ITEM,
    width_mm: float = 0.25,
) -> None:
    """Route a straight-line track between two named pads on two footprints."""
    a = fp_a.FindPadByNumber(pad_a).GetPosition()
    b = fp_b.FindPadByNumber(pad_b).GetPosition()
    add_track(layer_id, a, b, net, width_mm)


# Signal routing (LCD data, LCD control, analog bias/backlight) is LEFT AS
# RATSNEST for manual completion in the KiCad GUI. Programmatic point-to-
# point routing of 14 signals across two rows of a 2×20 header creates
# many crossings and near-pad shorts — real routing on a 2-layer board
# needs either a crossing-aware autorouter (freerouting) or a human eye.
#
# The GND pour (below) is the one exception where programmatic handling is
# reliably correct, because fills automatically respect clearance and
# connect all same-net pads without trace-layout decisions.

# Power and ground handled via a copper pour (zone) on B.Cu, not discrete
# traces. Chaining 5V/GND through multiple pads shorts to neighboring pads
# at the connector rows; a zone automatically connects all same-net pads
# within its polygon and respects clearance from other nets. This is the
# standard way to handle power on a 2-layer board.
#
# GND zone covers the whole board on B.Cu. 5V is routed as a small
# discrete trace on F.Cu (two 5V pins on J1 are adjacent, easy to bridge)
# plus a via into the B.Cu area where it can reach other 5V pads. Full 5V
# distribution is left for GUI-based manual routing in KiCad — the script
# demonstrates the programmatic pipeline up to the point where hand-tuning
# is appropriate.

# Short trace linking J1 pin 2 and pin 4 (both 5V) on F.Cu — they're right
# next to each other so a short direct segment works.
connect_pads(j1, "2", j1, "4", F_CU, net_5v, width_mm=0.50)

# GND copper pour on B.Cu
# Polygon covers the full board outline (same 0,0 to 65,56.5 as Edge.Cuts)
# with a small inset from the edge to respect fab clearance.
gnd_zone = pcbnew.ZONE(board)
gnd_zone.SetLayer(B_CU)
gnd_zone.SetNet(net_gnd)
gnd_zone.SetIsFilled(True)
gnd_zone.SetLocalClearance(MM(0.35))
gnd_zone.SetMinThickness(MM(0.25))
gnd_zone.SetThermalReliefGap(MM(0.35))
gnd_zone.SetThermalReliefSpokeWidth(MM(0.35))

# Build the zone polygon — rectangular, inset 0.5 mm from each edge.
# Add circular keepout holes (subtracted from the polygon) around each
# mounting hole so the fill doesn't encroach on the NPTH pad's required
# 0.25 mm hole clearance.
INSET = 0.5
MH_KEEPOUT_RADIUS_MM = 2.5  # mounting hole (2.75 dia) + clearance + margin

zone_outline = pcbnew.SHAPE_POLY_SET()
outer = pcbnew.SHAPE_LINE_CHAIN()
outer.Append(VECTOR2I(MM(INSET), MM(INSET)))
outer.Append(VECTOR2I(MM(BOARD_W_MM - INSET), MM(INSET)))
outer.Append(VECTOR2I(MM(BOARD_W_MM - INSET), MM(BOARD_H_MM - INSET)))
outer.Append(VECTOR2I(MM(INSET), MM(BOARD_H_MM - INSET)))
outer.SetClosed(True)
zone_outline.AddOutline(outer)

# Subtract keepout circles around each mounting hole (approximated as 24-sided
# polygons — SHAPE_POLY_SET doesn't accept true circles for holes)
def _circle_chain(cx_mm: float, cy_mm: float, r_mm: float, sides: int = 24):
    import math
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for i in range(sides):
        angle = 2 * math.pi * i / sides
        x = cx_mm + r_mm * math.cos(angle)
        y = cy_mm + r_mm * math.sin(angle)
        chain.Append(VECTOR2I(MM(x), MM(y)))
    chain.SetClosed(True)
    return chain


for cx, cy in MOUNTING_HOLES_MM:
    zone_outline.AddHole(_circle_chain(cx, cy, MH_KEEPOUT_RADIUS_MM))

gnd_zone.SetOutline(zone_outline)
board.Add(gnd_zone)

# Rebuild zone fills so the pour actually appears in the saved board
pcbnew.ZONE_FILLER(board).Fill(board.Zones())


# ───────────────────────── Save ─────────────────────────

# Set up basic design rules (sensible defaults for a simple 2-layer board)
nc = board.GetDesignSettings()
nc.SetCopperLayerCount(2)

board.Save(out_path)
print(f"PCB written: {out_path}", file=sys.stderr)
print(f"Footprints placed: {len(board.GetFootprints())}", file=sys.stderr)
print(f"Nets defined: {board.GetNetCount()}", file=sys.stderr)
print(f"Tracks: {len(board.GetTracks())}", file=sys.stderr)
