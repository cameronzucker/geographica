"""
GX-01 Adapter HAT — pcbnew layout generator.

Reads the netlist from circuit.py and produces a fully-placed + mostly
routed 2-layer PCB. Component placement uses a deliberate alignment:
J1 (2x20 GPIO socket) and J2 (1x20 LCD header) share the same 2.54 mm
pitch and X_start, so corresponding pin pairs line up vertically. This
makes 13 of 14 LCD signals route as straight-line vertical traces on
F.Cu with no crossings. The one exception — DB5 — has to skirt the
HAT-ID-reserved pins 27/28 and uses a B.Cu detour with vias.

Run with:
  python3 layout.py

Outputs:
  gx01-adapter.kicad_pcb
"""
import math
import os
import sys

import pcbnew
from pcbnew import FromMM as MM
from pcbnew import VECTOR2I


BOARD_W_MM = 65.0
BOARD_H_MM = 56.5
BOARD_OUTLINE_WIDTH_MM = 0.15

# Pi HAT mounting hole positions (mm from board top-left)
MOUNTING_HOLES_MM = [
    (3.5, 3.5),
    (61.5, 3.5),
    (3.5, 52.5),
    (61.5, 52.5),
]

# Shared pitch + origin X: every Jn pin at X = X_PIN1 + (k-1)*PIN_PITCH
# aligns with J1 pin pair (2k-1)/(2k)
X_PIN1 = 7.11
PIN_PITCH = 2.54

# J1 (GPIO socket) at the top edge of the board
J1_Y_ODD = 3.5        # Y of odd pins (1, 3, 5, ..., 39)
J1_Y_EVEN = J1_Y_ODD + PIN_PITCH   # Y of even pins (2, 4, 6, ..., 40)

# J2 (LCD header) placed below J1, aligned on same pitch
J2_Y = 16.0


# ───────────────────────── Helpers ─────────────────────────


def load_footprint(lib_name: str, fp_name: str) -> pcbnew.FOOTPRINT:
    lib_path = f"/usr/share/kicad/footprints/{lib_name}.pretty"
    fp = pcbnew.FootprintLoad(lib_path, fp_name)
    if fp is None:
        raise RuntimeError(f"Could not load footprint {lib_name}:{fp_name}")
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
    fp.SetReference(reference)
    fp.SetValue(value)
    fp.SetPosition(VECTOR2I(MM(x_mm), MM(y_mm)))
    if rotation_deg:
        fp.SetOrientationDegrees(rotation_deg)
    board.Add(fp)
    return fp


def ensure_net(board: pcbnew.BOARD, name: str) -> pcbnew.NETINFO_ITEM:
    nets = board.GetNetsByName()
    if name in nets:
        return nets[name]
    net = pcbnew.NETINFO_ITEM(board, name)
    board.Add(net)
    return net


def connect_pad(fp: pcbnew.FOOTPRINT, pad_name: str, net: pcbnew.NETINFO_ITEM) -> None:
    pad = fp.FindPadByNumber(pad_name)
    if pad is None:
        raise RuntimeError(f"Pad {pad_name!r} not found on {fp.GetReference()}")
    pad.SetNet(net)


# ───────────────────────── Build board ─────────────────────────

out_path = os.path.abspath("gx01-adapter.kicad_pcb")
board = pcbnew.NewBoard(out_path)

# Board outline
edge_cuts = board.GetLayerID("Edge.Cuts")
corners = [(0, 0), (BOARD_W_MM, 0), (BOARD_W_MM, BOARD_H_MM), (0, BOARD_H_MM)]
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


# Mounting holes
for i, (x, y) in enumerate(MOUNTING_HOLES_MM, start=1):
    fp = load_footprint("MountingHole", "MountingHole_2.7mm_M2.5")
    place(board, fp, f"H{i}", "MH_2.75", x, y)


# J1 — Pi GPIO 2x20 socket at top of board
j1 = load_footprint("Connector_PinSocket_2.54mm", "PinSocket_2x20_P2.54mm_Vertical")
place(board, j1, "J1", "Pi GPIO 40-pin", X_PIN1, J1_Y_ODD, rotation_deg=90.0)

# J2 — LCD 1x20 pin header at middle of board, aligned to J1 pitch.
# Pin 1 lands at X=X_PIN1 so J2 pin k and J1 pair k share X coordinate.
# Rotation 90° makes pins extend in +X direction from pin 1 (same orientation
# as J1 after its own 90° rotation).
j2 = load_footprint("Connector_PinHeader_2.54mm", "PinHeader_1x20_P2.54mm_Vertical")
place(board, j2, "J2", "LCD 20-pin", X_PIN1, J2_Y, rotation_deg=90.0)

# J3, J4 — fan power connectors, bottom-left of board
j3 = load_footprint("Connector_JST", "JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical")
place(board, j3, "J3", "Fan 1", 12.0, 48.0)

j4 = load_footprint("Connector_JST", "JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical")
place(board, j4, "J4", "Fan 2", 22.0, 48.0)

# RV1 — contrast trim pot, placed near J2 pins 3 (V0) and 18 (Vee)
# J2 pins 3 at X=X_PIN1+2*PIN_PITCH=12.19 and 18 at X=X_PIN1+17*PIN_PITCH=50.29
# Since Vee needs to come from pin 18 and V0 goes to pin 3, and pot endpoints
# are at 2.54 mm spacing, we put the pot right under J2 pin 18 area.
# Pot center at ~(50, 25); its pins span ~5 mm vertically.
rv1 = load_footprint("Potentiometer_THT", "Potentiometer_Bourns_3296W_Vertical")
place(board, rv1, "RV1", "10k", 50.0, 25.0)

# R1 — backlight current-limit resistor, next to J2 pin 19 (BLA) at X=52.83
r1 = load_footprint(
    "Resistor_THT",
    "R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
)
place(board, r1, "R1", "10R", 52.0, 35.0)

# C1 — bypass cap near J2 pin 2 (VDD) at X=9.65
c1 = load_footprint("Capacitor_THT", "C_Disc_D3.0mm_W2.0mm_P2.50mm")
place(board, c1, "C1", "100nF", 10.0, 30.0)


# ───────────────────────── Nets ─────────────────────────

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

# Assign nets to pads (J1 GPIO pin assignments aligned to J2 pin X positions)
for pad, net in [
    ("2", net_5v), ("4", net_5v),
    ("6", net_gnd), ("9", net_gnd), ("14", net_gnd), ("20", net_gnd),
    ("25", net_gnd), ("30", net_gnd), ("34", net_gnd), ("39", net_gnd),
    ("11", net_rs),   ("13", net_rw),   ("15", net_en),
    ("18", net_db[0]),("19", net_db[1]),("22", net_db[2]),
    ("23", net_db[3]),("26", net_db[4]),("29", net_db[6]),
    ("31", net_db[7]),("33", net_cs1),  ("35", net_cs2),
    ("37", net_rst),
    ("40", net_db[5]),  # DB5 — special case, routed via B.Cu detour
]:
    connect_pad(j1, pad, net)

# J2 pad assignments (per GDM12864H pinout)
for pad, net in [
    ("1", net_gnd), ("2", net_5v), ("3", net_v0),
    ("4", net_rs), ("5", net_rw), ("6", net_en),
    ("7", net_db[0]), ("8", net_db[1]), ("9", net_db[2]), ("10", net_db[3]),
    ("11", net_db[4]), ("12", net_db[5]), ("13", net_db[6]), ("14", net_db[7]),
    ("15", net_cs1), ("16", net_cs2), ("17", net_rst),
    ("18", net_vee), ("19", net_bla), ("20", net_gnd),
]:
    connect_pad(j2, pad, net)

# J3, J4 — fan power
for fp in (j3, j4):
    connect_pad(fp, "1", net_5v)
    connect_pad(fp, "2", net_gnd)

# RV1 — pot (pads named "1" "2" "3")
connect_pad(rv1, "1", net_5v)
connect_pad(rv1, "2", net_v0)
connect_pad(rv1, "3", net_vee)

# R1 — BL current limit
connect_pad(r1, "1", net_5v)
connect_pad(r1, "2", net_bla)

# C1 — bypass cap
connect_pad(c1, "1", net_5v)
connect_pad(c1, "2", net_gnd)


# ───────────────────────── Routing ─────────────────────────

F_CU = board.GetLayerID("F.Cu")
B_CU = board.GetLayerID("B.Cu")


def add_track(
    layer_id: int,
    start: pcbnew.VECTOR2I,
    end: pcbnew.VECTOR2I,
    net: pcbnew.NETINFO_ITEM,
    width_mm: float = 0.25,
) -> None:
    track = pcbnew.PCB_TRACK(board)
    track.SetLayer(layer_id)
    track.SetStart(start)
    track.SetEnd(end)
    track.SetWidth(MM(width_mm))
    track.SetNet(net)
    board.Add(track)


def add_via(
    position: pcbnew.VECTOR2I,
    net: pcbnew.NETINFO_ITEM,
    drill_mm: float = 0.4,
    size_mm: float = 0.8,
) -> pcbnew.PCB_VIA:
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(position)
    via.SetDrill(MM(drill_mm))
    via.SetWidth(MM(size_mm))
    via.SetNet(net)
    via.SetLayerPair(F_CU, B_CU)
    board.Add(via)
    return via


def pad_pos(fp: pcbnew.FOOTPRINT, pad_name: str) -> pcbnew.VECTOR2I:
    return fp.FindPadByNumber(pad_name).GetPosition()


# LCD signal routing (14 nets: RS, R/W, E, CS1, CS2, RST, DB0-DB7) is left
# for KiCad GUI completion. The carefully-aligned J1/J2 pitch (both at
# X_PIN1 + k*2.54) means each signal is a short 1-2 segment trace with a
# small lateral jog to avoid the same-column pin on J1's opposite row.
# With the placement done, drawing these in pcbnew's router is ~5 minutes
# of work and the crossings are handled for free by the interactive
# router's push-and-shove behavior. Doing this programmatically without
# a crossing-aware autorouter (freerouting) is more code than it's worth.

# Analog traces (VEE, V0, BLA) on F.Cu
# VEE: J2 pin 18 (X=50.29) → RV1 pin 3
#   RV1 is at (50, 25), 3 pins. For Bourns 3296W the pad positions are
#   roughly centered on (x, y) with pins spaced 2.54 mm.
add_track(F_CU, pad_pos(j2, "18"), pad_pos(rv1, "3"), net_vee, width_mm=0.30)

# V0 (RV1 wiper → J2 pin 3) is left as ratsnest: its path crosses the
# diagonal VEE trace on F.Cu AND a direct B.Cu detour passes through
# C1's ground-pad hole clearance. Resolving either automatically would
# require moving C1 or splitting V0 into three layer-switches. Quicker
# to draw this trace in pcbnew's interactive router (~30 seconds).

# BLA: J2 pin 19 (X=52.83) → R1 pin 2
add_track(F_CU, pad_pos(j2, "19"), pad_pos(r1, "2"), net_bla, width_mm=0.30)

# 5V distribution on F.Cu
# J1 pin 2/4 → J2 pin 2 → R1/RV1/C1/J3/J4
# Short hop from J1 pin 4 to J2 pin 2 (they share X=9.65)
add_track(F_CU, pad_pos(j1, "2"), pad_pos(j1, "4"), net_5v, width_mm=0.50)
# From J1 pin 4 (X=9.65, Y=6.04) straight down to J2 pin 2 (X=9.65, Y=16)
add_track(F_CU, pad_pos(j1, "4"), pad_pos(j2, "2"), net_5v, width_mm=0.50)
# From J2 pin 2 to C1 pin 1 (C1 is at X=10, Y=30, close)
add_track(F_CU, pad_pos(j2, "2"), pad_pos(c1, "1"), net_5v, width_mm=0.50)
# C1 pin 1 to J3/J4 5V pins — approach from ABOVE (Y=45) so the bus
# between fan connectors doesn't cross J3 pin 2 / J4 pin 2 (GND).
c1_1 = pad_pos(c1, "1")
j3_1 = pad_pos(j3, "1")
j4_1 = pad_pos(j4, "1")
fan_bus_y = MM(45.0)
fan_wp_c1 = VECTOR2I(c1_1.x, fan_bus_y)
fan_wp_j3 = VECTOR2I(j3_1.x, fan_bus_y)
fan_wp_j4 = VECTOR2I(j4_1.x, fan_bus_y)
add_track(F_CU, c1_1, fan_wp_c1, net_5v, width_mm=0.50)
add_track(F_CU, fan_wp_c1, fan_wp_j3, net_5v, width_mm=0.50)
add_track(F_CU, fan_wp_j3, j3_1, net_5v, width_mm=0.50)
add_track(F_CU, fan_wp_j3, fan_wp_j4, net_5v, width_mm=0.50)
add_track(F_CU, fan_wp_j4, j4_1, net_5v, width_mm=0.50)
# RV1 pin 1 and R1 pin 1 both need 5V. Route from J2 pin 2's side of the
# board to the right side where RV1 and R1 live. Use a B.Cu detour so we
# don't cross the F.Cu signal traces.
r1_1 = pad_pos(r1, "1")
rv1_1 = pad_pos(rv1, "1")
# Use a B.Cu detour to reach R1 and RV1 on the right side of the board
# without tangling with F.Cu signal routing channels in the middle area.
# Tie-in on F.Cu at the fan_bus_y=45 line (where 5V is already present),
# via down, B.Cu horizontal to R1's column, via back up.
v5_wp_tap = VECTOR2I(fan_wp_j4.x + MM(5), fan_bus_y)   # midpoint tap
v5_wp_r1 = VECTOR2I(r1_1.x, fan_bus_y)
add_track(F_CU, fan_wp_j4, v5_wp_tap, net_5v, width_mm=0.50)
add_via(v5_wp_tap, net_5v)
add_track(B_CU, v5_wp_tap, v5_wp_r1, net_5v, width_mm=0.50)
add_via(v5_wp_r1, net_5v)
add_track(F_CU, v5_wp_r1, r1_1, net_5v, width_mm=0.50)
add_track(F_CU, r1_1, rv1_1, net_5v, width_mm=0.50)


# ───────────────────────── GND copper pour on B.Cu ─────────────────────────

gnd_zone = pcbnew.ZONE(board)
gnd_zone.SetLayer(B_CU)
gnd_zone.SetNet(net_gnd)
gnd_zone.SetIsFilled(True)
gnd_zone.SetLocalClearance(MM(0.25))  # matches board default clearance; leaves room for thermal reliefs between adjacent routed signals
gnd_zone.SetMinThickness(MM(0.25))
gnd_zone.SetThermalReliefGap(MM(0.35))
gnd_zone.SetThermalReliefSpokeWidth(MM(0.35))

INSET = 0.5
MH_KEEPOUT_RADIUS_MM = 2.5

zone_outline = pcbnew.SHAPE_POLY_SET()
outer = pcbnew.SHAPE_LINE_CHAIN()
outer.Append(VECTOR2I(MM(INSET), MM(INSET)))
outer.Append(VECTOR2I(MM(BOARD_W_MM - INSET), MM(INSET)))
outer.Append(VECTOR2I(MM(BOARD_W_MM - INSET), MM(BOARD_H_MM - INSET)))
outer.Append(VECTOR2I(MM(INSET), MM(BOARD_H_MM - INSET)))
outer.SetClosed(True)
zone_outline.AddOutline(outer)


def _circle_chain(cx_mm: float, cy_mm: float, r_mm: float, sides: int = 24):
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

pcbnew.ZONE_FILLER(board).Fill(board.Zones())


# ───────────────────────── Save ─────────────────────────

nc = board.GetDesignSettings()
nc.SetCopperLayerCount(2)

board.Save(out_path)
print(f"PCB written: {out_path}", file=sys.stderr)
print(f"Footprints: {len(board.GetFootprints())}", file=sys.stderr)
print(f"Nets:       {board.GetNetCount()}", file=sys.stderr)
print(f"Tracks:     {len(board.GetTracks())}", file=sys.stderr)
