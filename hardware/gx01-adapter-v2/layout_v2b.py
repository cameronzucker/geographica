"""
GX-01 Adapter HAT v2 — pcbnew layout generator.

Places all footprints, defines a custom Seiko CPH3225A supercap footprint
inline, draws the board outline + mounting holes, and creates a B.Cu GND
zone with keepouts around the mounting holes. FreeRouting (autoroute.py)
handles all signal routing after this script.

Run with:
  python3 layout.py

Outputs:
  gx01-adapter-v2.kicad_pcb
"""
import math
import os
import sys

import pcbnew
from pcbnew import FromMM as MM
from pcbnew import VECTOR2I


# ───────────────────────── Constants ─────────────────────────

BOARD_W_MM = 65.0
BOARD_H_MM = 56.5
BOARD_OUTLINE_WIDTH_MM = 0.15

# Standard Pi HAT mounting hole positions
MOUNTING_HOLES_MM = [
    (3.5, 3.5),
    (61.5, 3.5),
    (3.5, 52.5),
    (61.5, 52.5),
]

# J1 (Pi GPIO socket) pitch + origin — identical to v1
X_PIN1 = 7.11
PIN_PITCH = 2.54
J1_Y_ODD = 3.5
J1_Y_EVEN = J1_Y_ODD + PIN_PITCH

# J2 (LCD IDC 2×10) — placed below J1 with clear separation. After 90°
# rotation, its long axis runs in X and its short axis in Y.
# J2 anchor moved from 11.5 → 15.0 after JLC preview showed the real IDC
# box header's plastic shroud (extends ~4 mm above pin 1 for the retention
# clip) colliding with J1's socket body. The bare-footprint courtyard didn't
# catch it; the 3D preview did. J1 socket body occupies Y≈2-8 mm including
# its plastic skirt; giving J2's shroud top ~3 mm clearance means the shroud
# should start at Y≈11 and the anchor (pin 1) at Y=15.
J2_Y_ANCHOR = 15.0


# ───────────────────────── Board + helpers ─────────────────────────

out_path = os.path.abspath("gx01-adapter-v2b.kicad_pcb")
board = pcbnew.NewBoard(out_path)


def load_footprint(lib_name: str, fp_name: str) -> pcbnew.FOOTPRINT:
    lib_path = f"/usr/share/kicad/footprints/{lib_name}.pretty"
    fp = pcbnew.FootprintLoad(lib_path, fp_name)
    if fp is None:
        raise RuntimeError(f"Could not load footprint {lib_name}:{fp_name}")
    return fp


def place(fp: pcbnew.FOOTPRINT, reference: str, value: str,
          x_mm: float, y_mm: float, rotation_deg: float = 0.0,
          layer: int | None = None) -> pcbnew.FOOTPRINT:
    fp.SetReference(reference)
    fp.SetValue(value)
    fp.SetPosition(VECTOR2I(MM(x_mm), MM(y_mm)))
    if rotation_deg:
        fp.SetOrientationDegrees(rotation_deg)
    if layer is not None:
        fp.SetLayer(layer)
    board.Add(fp)
    return fp


def ensure_net(name: str) -> pcbnew.NETINFO_ITEM:
    nets = board.GetNetsByName()
    if name in nets:
        return nets[name]
    net = pcbnew.NETINFO_ITEM(board, name)
    board.Add(net)
    return net


def connect_pad(fp: pcbnew.FOOTPRINT, pad_name: str,
                net: pcbnew.NETINFO_ITEM) -> None:
    pad = fp.FindPadByNumber(pad_name)
    if pad is None:
        raise RuntimeError(f"Pad {pad_name!r} not found on {fp.GetReference()}")
    pad.SetNet(net)


# ───────────────────────── Custom CPH3225A supercap footprint ─────────────────────────

def make_cph3225a_footprint() -> pcbnew.FOOTPRINT:
    """Create a custom footprint for the Seiko CPH3225A 1F 3.3V SMD supercap.

    Geometry (from Seiko CPH3225A datasheet):
      * Body: 6.8 × 6.8 × 0.9 mm (square SMD)
      * 4 solder pads: 2 on the +X side (cathode), 2 on the −X side (anode).
        Each pad is 1.5 mm (X) × 2.5 mm (Y). Pads on the same side are spaced
        2.5 mm center-to-center in Y. Pad centers are 5.6 mm apart in X.
      * Anchor at the body center.

    Electrical convention: pad number "1" for both anode pads, "2" for both
    cathode pads. pcbnew aggregates pads with duplicate numbers into a single
    logical pin, so `FindPadByNumber("1")` returns either — for net assignment
    that's fine because both physically carry the same potential.
    """
    fp = pcbnew.FOOTPRINT(board)
    fp.SetFPID(pcbnew.LIB_ID("geographica", "SuperCap_CPH3225A_6.8x6.8mm"))

    pad_w_mm = 1.5
    pad_h_mm = 2.5
    pad_pitch_y_mm = 2.5     # same-side pad center-to-center (Y)
    pad_span_x_mm = 5.6      # opposite-side pad center-to-center (X)

    # Four pads: (x_offset, y_offset, pad_number)
    pad_coords = [
        (-pad_span_x_mm / 2, -pad_pitch_y_mm / 2, "1"),   # anode top
        (-pad_span_x_mm / 2,  pad_pitch_y_mm / 2, "1"),   # anode bottom
        ( pad_span_x_mm / 2, -pad_pitch_y_mm / 2, "2"),   # cathode top
        ( pad_span_x_mm / 2,  pad_pitch_y_mm / 2, "2"),   # cathode bottom
    ]

    for dx_mm, dy_mm, num in pad_coords:
        pad = pcbnew.PAD(fp)
        pad.SetNumber(num)
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetSize(VECTOR2I(MM(pad_w_mm), MM(pad_h_mm)))
        pad.SetPosition(VECTOR2I(MM(dx_mm), MM(dy_mm)))
        pad.SetLayerSet(pad.SMDMask())   # F.Cu + F.Mask + F.Paste
        fp.Add(pad)

    # Silk outline on F.Silkscreen (body outline for visual reference)
    body_half_mm = 6.8 / 2
    silk_layer = board.GetLayerID("F.Silkscreen")
    for x1, y1, x2, y2 in [
        (-body_half_mm, -body_half_mm,  body_half_mm, -body_half_mm),  # top
        ( body_half_mm, -body_half_mm,  body_half_mm,  body_half_mm),  # right
        ( body_half_mm,  body_half_mm, -body_half_mm,  body_half_mm),  # bottom
        (-body_half_mm,  body_half_mm, -body_half_mm, -body_half_mm),  # left
    ]:
        line = pcbnew.PCB_SHAPE(fp)
        line.SetShape(pcbnew.SHAPE_T_SEGMENT)
        line.SetLayer(silk_layer)
        line.SetStart(VECTOR2I(MM(x1), MM(y1)))
        line.SetEnd(VECTOR2I(MM(x2), MM(y2)))
        line.SetWidth(MM(0.15))
        fp.Add(line)

    # Courtyard on F.Courtyard (body + 0.25 mm margin per IPC-7351)
    cyd_layer = board.GetLayerID("F.Courtyard")
    cyd_margin_mm = 0.25
    cx = body_half_mm + cyd_margin_mm
    # Also include the pads in the courtyard bounding box
    cx_pads = pad_span_x_mm / 2 + pad_w_mm / 2 + cyd_margin_mm
    cy = body_half_mm + cyd_margin_mm
    cx_total = max(cx, cx_pads)
    for x1, y1, x2, y2 in [
        (-cx_total, -cy,  cx_total, -cy),
        ( cx_total, -cy,  cx_total,  cy),
        ( cx_total,  cy, -cx_total,  cy),
        (-cx_total,  cy, -cx_total, -cy),
    ]:
        line = pcbnew.PCB_SHAPE(fp)
        line.SetShape(pcbnew.SHAPE_T_SEGMENT)
        line.SetLayer(cyd_layer)
        line.SetStart(VECTOR2I(MM(x1), MM(y1)))
        line.SetEnd(VECTOR2I(MM(x2), MM(y2)))
        line.SetWidth(MM(0.05))
        fp.Add(line)

    return fp


# ───────────────────────── Board outline + mounting holes ─────────────────────────

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

for i, (x, y) in enumerate(MOUNTING_HOLES_MM, start=1):
    fp = load_footprint("MountingHole", "MountingHole_2.7mm_M2.5")
    place(fp, f"H{i}", "MH_2.75", x, y)


# ───────────────────────── Component placement ─────────────────────────

# J1 — Pi 40-pin socket at top edge. Rotation 90° so the long axis of the
# 2×20 grid lies along X (same convention as v1 — anchor pin stays at
# X_PIN1, J1_Y_ODD but pairs extend to the right in X).
j1 = load_footprint("Connector_PinSocket_2.54mm", "PinSocket_2x20_P2.54mm_Vertical")
place(j1, "J1", "Pi GPIO 40-pin", X_PIN1, J1_Y_ODD, rotation_deg=90.0)

# J2 — 2×10 IDC box header for LCD ribbon, below J1, long axis along X.
# Using the plain PinHeader_2x10 footprint (no shroud) to keep pcbnew
# happy; the physical part is a shrouded IDC with an identical pad pattern.
j2 = load_footprint("Connector_PinHeader_2.54mm", "PinHeader_2x10_P2.54mm_Vertical")
place(j2, "J2", "LCD 2x10 IDC", X_PIN1, J2_Y_ANCHOR, rotation_deg=90.0)

# J3, J4 — JST-PH 4-pin fan connectors, bottom-left. Shifted inward from
# mounting holes at (3.5, 52.5) / (61.5, 52.5) so no courtyard conflict.
j3 = load_footprint("Connector_JST", "JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical")
place(j3, "J3", "Fan 1", 13.0, 51.0)

j4 = load_footprint("Connector_JST", "JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical")
place(j4, "J4", "Fan 2", 27.0, 51.0)

# J5 — JST-SH 6-pin SMT to FPB, bottom-right
j5 = load_footprint("Connector_JST", "JST_SH_BM06B-SRSS-TB_1x06-1MP_P1.00mm_Vertical")
place(j5, "J5", "FPB cable", 52.0, 52.0)

# v2b placement revision: remove R1/R2 from J1-J2 corridor (they were blocking
# LCD signal routes). Put the RTC cluster on the right side, EEPROM on the
# left, sensors spread far apart. Trades longer I²C0 traces for a clearer
# LCD signal corridor through the center of the board.

u4 = load_footprint("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm")
place(u4, "U4", "24LC32", 13.0, 30.0)

u3 = load_footprint("Package_SO", "MSOP-8_3x3mm_P0.65mm")
place(u3, "U3", "MCP9808", 13.0, 40.0)

u1 = load_footprint("Package_SON", "MicroCrystal_C7_SON-8_1.5x3.2mm_P0.9mm")
place(u1, "U1", "RV-3028-C7", 45.0, 27.0)

c1 = make_cph3225a_footprint()
place(c1, "C1", "1F 3.3V", 54.0, 27.0)

u2 = load_footprint("Package_LGA", "Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering")
place(u2, "U2", "BME280", 53.0, 42.0)

q1 = load_footprint("Package_TO_SOT_SMD", "SOT-23")
place(q1, "Q1", "AO3400A", 33.0, 20.0)

# Bypass caps — moved further from their ICs after DRC flagged pad overlaps
# on C4/U3 and C5/U4 (0603 pad reaching into SOIC/MSOP pad keep-out zone).
# Original X=17 was 4 mm from IC center (at X=13) but SOIC-8 pads extend
# ±2.5 mm and the 0603 pad extends ±0.825 mm, leaving only 0.675 mm gap
# which is under clearance. New X=19 gives ~3 mm of pad-edge clearance.
c2 = load_footprint("Capacitor_SMD", "C_0603_1608Metric")
place(c2, "C2", "100nF", 47.0, 30.0)    # was 49 — move 2 mm from C1 to fix courtyard overlap
c3 = load_footprint("Capacitor_SMD", "C_0603_1608Metric")
place(c3, "C3", "100nF", 48.0, 42.0)
c4 = load_footprint("Capacitor_SMD", "C_0603_1608Metric")
place(c4, "C4", "100nF", 19.0, 40.0)    # was 17 — clear U3 MSOP-8 pads
c5 = load_footprint("Capacitor_SMD", "C_0603_1608Metric")
place(c5, "C5", "100nF", 19.0, 30.0)    # was 17 — clear U4 SOIC-8 pads

# I²C1 pull-ups near RTC (clearing the J1-J2 corridor)
r1 = load_footprint("Resistor_SMD", "R_0603_1608Metric")
place(r1, "R1", "4.7k", 42.0, 22.0)
r2 = load_footprint("Resistor_SMD", "R_0603_1608Metric")
place(r2, "R2", "4.7k", 42.0, 24.0)

# I²C0 (HAT ID) pull-ups — moved from X=20 to X=22 after C5 shifted to X=19
# (C5 pads reach X=19.8; R4 at X=20 put its pad at X=19.175 — 0.6 mm gap, fail).
r3 = load_footprint("Resistor_SMD", "R_0603_1608Metric")
place(r3, "R3", "3.3k", 22.0, 27.0)
r4 = load_footprint("Resistor_SMD", "R_0603_1608Metric")
place(r4, "R4", "3.3k", 22.0, 29.0)

# Q1 gate pulldown
r5 = load_footprint("Resistor_SMD", "R_0603_1608Metric")
place(r5, "R5", "10k", 37.0, 20.0)

# LCD V0 divider
r6 = load_footprint("Resistor_SMD", "R_0603_1608Metric")
place(r6, "R6", "10k", 20.0, 20.0)
r7 = load_footprint("Resistor_SMD", "R_0603_1608Metric")
place(r7, "R7", "10k", 26.0, 20.0)


# ───────────────────────── Nets ─────────────────────────

# Power
net_5v   = ensure_net("+5V")
net_3v3  = ensure_net("+3V3")
net_gnd  = ensure_net("GND")

# I²C1 (general)
net_sda1 = ensure_net("SDA1")
net_scl1 = ensure_net("SCL1")

# I²C0 (HAT ID bus)
net_id_sd = ensure_net("ID_SD")
net_id_sc = ensure_net("ID_SC")

# Pi passthroughs (just terminal on J1, no other pad — but create nets for
# completeness so ratsnest doesn't get confused)
net_pps     = ensure_net("PPS")
net_uart_tx = ensure_net("UART_TX")
net_uart_rx = ensure_net("UART_RX")

# FPB interface
net_fpb_int = ensure_net("FPB_INT")
net_fpb_rst = ensure_net("FPB_RST")

# LCD
net_lcd_rs  = ensure_net("LCD_RS")
net_lcd_rw  = ensure_net("LCD_RW")
net_lcd_e   = ensure_net("LCD_E")
net_lcd_cs1 = ensure_net("LCD_CS1")
net_lcd_cs2 = ensure_net("LCD_CS2")
net_lcd_rst = ensure_net("LCD_RST")
net_lcd_db  = [ensure_net(f"LCD_DB{i}") for i in range(8)]
net_lcd_vee = ensure_net("LCD_VEE")
net_lcd_v0  = ensure_net("LCD_V0")
net_lcd_bla = ensure_net("LCD_BLA")
net_lcd_blk = ensure_net("LCD_BLK")

# PWM / tach
net_bl_pwm    = ensure_net("BL_PWM")
net_fan_pwm   = ensure_net("FAN_PWM")
net_fan1_tach = ensure_net("FAN1_TACH")
net_fan2_tach = ensure_net("FAN2_TACH")

# RTC backup
net_vbackup = ensure_net("VBACKUP")


# ───────────────────────── J1 pad assignments (Pi GPIO) ─────────────────────────

for pad, net in [
    ("1", net_3v3),  ("17", net_3v3),
    ("2", net_5v),   ("4", net_5v),
    ("6", net_gnd),  ("9", net_gnd),  ("14", net_gnd), ("20", net_gnd),
    ("25", net_gnd), ("30", net_gnd), ("34", net_gnd), ("39", net_gnd),
    ("3", net_sda1), ("5", net_scl1),
    ("27", net_id_sd), ("28", net_id_sc),
    ("7", net_fpb_int),
    ("8", net_uart_tx), ("10", net_uart_rx), ("12", net_pps),
    ("32", net_bl_pwm), ("36", net_fan_pwm),
    ("38", net_fan1_tach), ("16", net_fan2_tach),
    ("11", net_lcd_rs),  ("13", net_lcd_rw),  ("15", net_lcd_e),
    ("33", net_lcd_cs1), ("35", net_lcd_cs2), ("37", net_lcd_rst),
    ("18", net_lcd_db[0]), ("19", net_lcd_db[1]),
    ("22", net_lcd_db[2]), ("23", net_lcd_db[3]),
    ("26", net_lcd_db[4]), ("40", net_lcd_db[5]),
    ("29", net_lcd_db[6]), ("31", net_lcd_db[7]),
]:
    connect_pad(j1, pad, net)


# ───────────────────────── J2 pad assignments (LCD ribbon) ─────────────────────────

for pad, net in [
    ("1", net_gnd), ("2", net_5v), ("3", net_lcd_v0),
    ("4", net_lcd_rs), ("5", net_lcd_rw), ("6", net_lcd_e),
    ("7", net_lcd_db[0]), ("8", net_lcd_db[1]),
    ("9", net_lcd_db[2]), ("10", net_lcd_db[3]),
    ("11", net_lcd_db[4]), ("12", net_lcd_db[5]),
    ("13", net_lcd_db[6]), ("14", net_lcd_db[7]),
    ("15", net_lcd_cs1), ("16", net_lcd_cs2), ("17", net_lcd_rst),
    ("18", net_lcd_vee), ("19", net_lcd_bla), ("20", net_lcd_blk),
]:
    connect_pad(j2, pad, net)


# ───────────────────────── J3, J4, J5 ─────────────────────────

for fp in (j3, j4):
    connect_pad(fp, "1", net_gnd)
    connect_pad(fp, "2", net_5v)
    # pads 3,4 handled per-connector below
connect_pad(j3, "3", net_fan1_tach); connect_pad(j3, "4", net_fan_pwm)
connect_pad(j4, "3", net_fan2_tach); connect_pad(j4, "4", net_fan_pwm)

for pad, net in [
    ("1", net_3v3), ("2", net_gnd), ("3", net_sda1), ("4", net_scl1),
    ("5", net_fpb_int), ("6", net_fpb_rst),
]:
    connect_pad(j5, pad, net)


# ───────────────────────── IC pad assignments ─────────────────────────

# U1 RV-3028 — pin map: 1=CLKOUT, 2=~INT, 3=SCL, 4=SDA, 5=VSS, 6=VBACKUP, 7=VDD, 8=EVI
connect_pad(u1, "4", net_sda1)
connect_pad(u1, "3", net_scl1)
connect_pad(u1, "5", net_gnd)
connect_pad(u1, "6", net_vbackup)
connect_pad(u1, "7", net_3v3)

# C1 — supercap; "1" = anode (VBACKUP), "2" = cathode (GND)
connect_pad(c1, "1", net_vbackup)
connect_pad(c1, "2", net_gnd)

# U2 BME280 — pin map: 1=GND, 2=CSB, 3=SDI, 4=SCK, 5=SDO, 6=VDDIO, 7=GND, 8=VDD
connect_pad(u2, "1", net_gnd); connect_pad(u2, "7", net_gnd)
connect_pad(u2, "8", net_3v3); connect_pad(u2, "6", net_3v3)
connect_pad(u2, "2", net_3v3)    # CSB → I²C mode
connect_pad(u2, "5", net_gnd)    # SDO → addr 0x76
connect_pad(u2, "3", net_sda1); connect_pad(u2, "4", net_scl1)

# U3 MCP9808 — pin map: 1=SDA, 2=SCL, 3=Alert, 4=GND, 5=A2, 6=A1, 7=A0, 8=V_DD
connect_pad(u3, "1", net_sda1); connect_pad(u3, "2", net_scl1)
connect_pad(u3, "4", net_gnd); connect_pad(u3, "5", net_gnd)
connect_pad(u3, "6", net_gnd); connect_pad(u3, "7", net_gnd)
connect_pad(u3, "8", net_3v3)

# U4 24LC32 — pin map: 1=A0, 2=A1, 3=A2, 4=GND, 5=SDA, 6=SCL, 7=WP, 8=VCC
for pn in ("1", "2", "3", "4", "7"):
    connect_pad(u4, pn, net_gnd)
connect_pad(u4, "5", net_id_sd); connect_pad(u4, "6", net_id_sc)
connect_pad(u4, "8", net_3v3)

# Q1 AO3400 — 1=G, 2=S, 3=D
connect_pad(q1, "1", net_bl_pwm)
connect_pad(q1, "2", net_gnd)
connect_pad(q1, "3", net_lcd_blk)

# Bypass caps
for fp, net_hi in [(c2, net_3v3), (c3, net_3v3), (c4, net_3v3), (c5, net_3v3)]:
    connect_pad(fp, "1", net_hi); connect_pad(fp, "2", net_gnd)

# Pull-ups
connect_pad(r1, "1", net_3v3); connect_pad(r1, "2", net_sda1)
connect_pad(r2, "1", net_3v3); connect_pad(r2, "2", net_scl1)
connect_pad(r3, "1", net_3v3); connect_pad(r3, "2", net_id_sd)
connect_pad(r4, "1", net_3v3); connect_pad(r4, "2", net_id_sc)

# Gate pulldown
connect_pad(r5, "1", net_bl_pwm); connect_pad(r5, "2", net_gnd)

# V0 divider
connect_pad(r6, "1", net_5v);    connect_pad(r6, "2", net_lcd_v0)
connect_pad(r7, "1", net_lcd_v0); connect_pad(r7, "2", net_lcd_vee)


# ───────────────────────── GND zone on B.Cu ─────────────────────────

B_CU = board.GetLayerID("B.Cu")

gnd_zone = pcbnew.ZONE(board)
gnd_zone.SetLayer(B_CU)
gnd_zone.SetNet(net_gnd)
gnd_zone.SetIsFilled(True)
gnd_zone.SetLocalClearance(MM(0.25))
gnd_zone.SetMinThickness(MM(0.25))
gnd_zone.SetThermalReliefGap(MM(0.35))
gnd_zone.SetThermalReliefSpokeWidth(MM(0.35))

INSET = 0.5
MH_KEEPOUT_R_MM = 2.5

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
    zone_outline.AddHole(_circle_chain(cx, cy, MH_KEEPOUT_R_MM))

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
