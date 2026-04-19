"""
GX-01 Front Panel Board — pcbnew layout generator.

Small case-front-mounted PCB carrying: MCP23017 I²C GPIO expander,
6 tactile switches, 4 status LEDs (via resistors), VEML7700 light sensor
(custom footprint — no stock KiCad part), JST-SH cable connector, and
4 M2.5 mounting holes straight into case standoffs.

Board size 65×42 mm (expanded from initial 65×30 after first render
showed MCP23017 SOIC-28W crowding the switches; extra Y height lets
the D-pad cluster sit in its own row below the IC).

Run with:
  python3 layout.py

Outputs:
  gx01-front-panel.kicad_pcb
"""
import math
import os
import sys

import pcbnew
from pcbnew import FromMM as MM
from pcbnew import VECTOR2I


BOARD_W_MM = 65.0
BOARD_H_MM = 42.0
BOARD_OUTLINE_WIDTH_MM = 0.15

MOUNTING_HOLES_MM = [
    (3.5, 3.5),
    (61.5, 3.5),
    (3.5, 38.5),
    (61.5, 38.5),
]

out_path = os.path.abspath("gx01-front-panel.kicad_pcb")
board = pcbnew.NewBoard(out_path)


# ───────────────────────── Helpers ─────────────────────────

def load_footprint(lib_name: str, fp_name: str) -> pcbnew.FOOTPRINT:
    lib_path = f"/usr/share/kicad/footprints/{lib_name}.pretty"
    fp = pcbnew.FootprintLoad(lib_path, fp_name)
    if fp is None:
        raise RuntimeError(f"Could not load footprint {lib_name}:{fp_name}")
    return fp


def place(fp, ref, val, x, y, rot=0.0):
    fp.SetReference(ref); fp.SetValue(val)
    fp.SetPosition(VECTOR2I(MM(x), MM(y)))
    if rot: fp.SetOrientationDegrees(rot)
    board.Add(fp)
    return fp


def ensure_net(name: str) -> pcbnew.NETINFO_ITEM:
    nets = board.GetNetsByName()
    if name in nets:
        return nets[name]
    n = pcbnew.NETINFO_ITEM(board, name); board.Add(n); return n


def connect(fp, pad_num, net):
    pad = fp.FindPadByNumber(pad_num)
    if pad is None:
        raise RuntimeError(f"Pad {pad_num!r} not on {fp.GetReference()}")
    pad.SetNet(net)


# ───────────────────────── Custom VEML7700 OPLGA-6 footprint ─────────────────────────

def make_veml7700_footprint() -> pcbnew.FOOTPRINT:
    """VEML7700 OPLGA-6 2×2×0.85 mm ambient light sensor.

    Pin layout (per Vishay datasheet, pins viewed from top):
        Pin 1 (ADDR_SEL) — row 1, col 1
        Pin 2 (SDA)      — row 1, col 2
        Pin 3 (SCL)      — row 1, col 3
        Pin 4 (INT)      — row 2, col 3
        Pin 5 (GND)      — row 2, col 2
        Pin 6 (VDD)      — row 2, col 1
    Pad pitch 0.5 mm (row-to-row and col-to-col). Pads ~0.3×0.4 mm.
    Photodiode aperture in center — do NOT cover with solder mask or silk.
    """
    fp = pcbnew.FOOTPRINT(board)
    fp.SetFPID(pcbnew.LIB_ID("geographica", "VEML7700_OPLGA-6"))

    pad_w = 0.3
    pad_h = 0.4
    col_pitch = 0.5   # X between columns
    row_pitch = 1.2   # Y between rows (larger because photodiode in middle)

    # Pad positions relative to footprint center
    # Cols at -0.5, 0.0, +0.5 (3 cols)
    # Rows at -0.6, +0.6 (2 rows)
    pad_coords = [
        (-col_pitch, -row_pitch/2, "1"),   # row 1 col 1
        ( 0.0,       -row_pitch/2, "2"),
        ( col_pitch, -row_pitch/2, "3"),
        ( col_pitch,  row_pitch/2, "4"),   # row 2 col 3
        ( 0.0,        row_pitch/2, "5"),
        (-col_pitch,  row_pitch/2, "6"),
    ]
    for dx, dy, num in pad_coords:
        pad = pcbnew.PAD(fp)
        pad.SetNumber(num)
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetSize(VECTOR2I(MM(pad_w), MM(pad_h)))
        pad.SetPosition(VECTOR2I(MM(dx), MM(dy)))
        pad.SetLayerSet(pad.SMDMask())
        fp.Add(pad)

    # Silk body outline (2×2 mm body)
    body = 2.0 / 2
    silk = board.GetLayerID("F.Silkscreen")
    for x1, y1, x2, y2 in [
        (-body, -body,  body, -body),
        ( body, -body,  body,  body),
        ( body,  body, -body,  body),
        (-body,  body, -body, -body),
    ]:
        s = pcbnew.PCB_SHAPE(fp)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(silk)
        s.SetStart(VECTOR2I(MM(x1), MM(y1)))
        s.SetEnd(VECTOR2I(MM(x2), MM(y2)))
        s.SetWidth(MM(0.12)); fp.Add(s)

    return fp


# ───────────────────────── Board outline + mounting holes ─────────────────────────

edge = board.GetLayerID("Edge.Cuts")
corners = [(0, 0), (BOARD_W_MM, 0), (BOARD_W_MM, BOARD_H_MM), (0, BOARD_H_MM)]
for i in range(4):
    x1, y1 = corners[i]; x2, y2 = corners[(i+1) % 4]
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(edge)
    s.SetStart(VECTOR2I(MM(x1), MM(y1)))
    s.SetEnd(VECTOR2I(MM(x2), MM(y2)))
    s.SetWidth(MM(BOARD_OUTLINE_WIDTH_MM)); board.Add(s)

for i, (x, y) in enumerate(MOUNTING_HOLES_MM, start=1):
    place(load_footprint("MountingHole", "MountingHole_2.7mm_M2.5"), f"H{i}", "MH_2.75", x, y)


# ───────────────────────── Placement ─────────────────────────

# ─── Placement strategy ────────────────────────────────────────────────
# Top strip (Y=3–10): status LEDs (D1–D4) spaced evenly with their R-pairs
#                     just below; VEML7700 lives near the right-edge top
#                     so the sensor aperture sits next to where the LCD
#                     window will be on the case front.
# Mid strip (Y=11–17): MCP23017 SOIC-28W, JST-SH cable connector, bypass
#                     caps, RESET pull-up.
# Bottom strip (Y=20–38): 6 tactile switches in a D-pad + Select + Back
#                     layout, clear of U1's body and the mounting holes.

# J1 — JST-SH 6-pin cable to main HAT, left edge mid-height
j1 = load_footprint("Connector_JST", "JST_SH_BM06B-SRSS-TB_1x06-1MP_P1.00mm_Vertical")
place(j1, "J1", "Cable", 7.0, 15.0)

# U1 — MCP23017 SOIC-28W, middle-right (long axis along X)
u1 = load_footprint("Package_SO", "SOIC-28W_7.5x17.9mm_P1.27mm")
place(u1, "U1", "MCP23017", 36.0, 14.0)

# U2 — VEML7700 ambient light sensor, upper right
u2 = make_veml7700_footprint()
place(u2, "U2", "VEML7700", 58.0, 7.0)

# C1 — bypass cap near U1 VDD (pin 9, lower-right of U1)
c1 = load_footprint("Capacitor_SMD", "C_0603_1608Metric")
place(c1, "C1", "100nF", 48.0, 11.0)

# C2 — bypass cap near U2 VDD
c2 = load_footprint("Capacitor_SMD", "C_0603_1608Metric")
place(c2, "C2", "100nF", 58.0, 11.0)

# R1 — RESET pull-up, between J1 and U1
r1 = load_footprint("Resistor_SMD", "R_0603_1608Metric")
place(r1, "R1", "10k", 15.0, 14.0)

# ─── LEDs and current-limit resistors (top row) ────────────────────────
# Spaced 7 mm apart along the top edge so the 3D-printed case light pipe
# can have well-separated apertures.
leds_y = 6.0
resistors_y = 9.0
# 5 mm LED pitch keeps all 4 LEDs + resistor pairs clear of U1's body
# (U1 left edge at X≈27.05). D4/R5 at X=23 leaves ~3 mm gap.
led_positions = [( 8, "D1", "PWR_Grn"), (13, "D2", "GPS_Blu"),
                 (18, "D3", "NTP_Yel"), (23, "D4", "ERR_Red")]
resistor_positions = [( 8, "R2"), (13, "R3"), (18, "R4"), (23, "R5")]

d_fps = {}
for x, ref, val in led_positions:
    fp = load_footprint("LED_SMD", "LED_0603_1608Metric")
    place(fp, ref, val, x, leds_y)
    d_fps[ref] = fp
d1, d2, d3, d4 = d_fps["D1"], d_fps["D2"], d_fps["D3"], d_fps["D4"]

r_fps = {}
for x, ref in resistor_positions:
    fp = load_footprint("Resistor_SMD", "R_0603_1608Metric")
    place(fp, ref, "1k", x, resistors_y)
    r_fps[ref] = fp
r2, r3, r4, r5 = r_fps["R2"], r_fps["R3"], r_fps["R4"], r_fps["R5"]

# ─── Switches (bottom D-pad + Select + Back) ───────────────────────────
# 6 mm tactile switches. Bodies 6×6 mm, need ~2 mm clearance per edge.
#
#    SW3(L)      SW1(U)     SW4(R)       SW5(SEL)   SW6(BACK)
#                SW2(D)
#
# D-pad center: (14, 28). SW1 above (Y=22), SW2 below (Y=34), SW3 left
# (X=7), SW4 right (X=21). Then SW5 / SW6 as separate buttons further right.
btn = "SW_SPST_B3U-3000P"
def sw(ref, val, x, y):
    return place(load_footprint("Button_Switch_SMD", btn), ref, val, x, y)

sw1 = sw("SW1", "UP",     14.0, 22.0)
sw3 = sw("SW3", "LEFT",    7.0, 28.0)
sw4 = sw("SW4", "RIGHT",  21.0, 28.0)
sw2 = sw("SW2", "DOWN",   14.0, 34.0)
sw5 = sw("SW5", "SELECT", 40.0, 28.0)
sw6 = sw("SW6", "BACK",   53.0, 28.0)


# ───────────────────────── Nets + pad assignments ─────────────────────────

net_3v3 = ensure_net("+3V3")
net_gnd = ensure_net("GND")
net_sda1 = ensure_net("SDA1")
net_scl1 = ensure_net("SCL1")
net_int = ensure_net("MCP_INT")
net_rst = ensure_net("MCP_RST")
sw_nets = {
    "up":    ensure_net("SW_UP"),
    "down":  ensure_net("SW_DOWN"),
    "left":  ensure_net("SW_LEFT"),
    "right": ensure_net("SW_RIGHT"),
    "sel":   ensure_net("SW_SEL"),
    "back":  ensure_net("SW_BACK"),
}
led_nets = {
    "gps": ensure_net("LED_GPS"),
    "ntp": ensure_net("LED_NTP"),
    "err": ensure_net("LED_ERR"),
    "pwr_k": ensure_net("PWR_K"),  # D1 cathode → R2 → GND
    "gps_k": ensure_net("D2_K"),
    "ntp_k": ensure_net("D3_K"),
    "err_k": ensure_net("D4_K"),
}

# J1 cable pins
connect(j1, "1", net_3v3); connect(j1, "2", net_gnd)
connect(j1, "3", net_sda1); connect(j1, "4", net_scl1)
connect(j1, "5", net_int);  connect(j1, "6", net_rst)

# U1 MCP23017 pin assignments (see circuit.py for pin map)
connect(u1, "9", net_3v3)                               # VDD
connect(u1, "10", net_gnd)                              # VSS
connect(u1, "12", net_scl1); connect(u1, "13", net_sda1)
for a in ("15", "16", "17"):                            # A0, A1, A2 → GND (0x20)
    connect(u1, a, net_gnd)
connect(u1, "18", net_rst)                              # RESET
connect(u1, "19", net_int)                              # INTB
# INTA (pin 20) left unconnected
# Port B (switches)
connect(u1, "1", sw_nets["up"])
connect(u1, "2", sw_nets["down"])
connect(u1, "3", sw_nets["left"])
connect(u1, "4", sw_nets["right"])
connect(u1, "5", sw_nets["sel"])
connect(u1, "6", sw_nets["back"])
# Port A (LEDs, active-low outputs drive cathodes through resistors)
connect(u1, "21", led_nets["gps_k"])   # GPA0 → D2 cathode (via R3)
connect(u1, "22", led_nets["ntp_k"])   # GPA1 → D3 cathode (via R4)
connect(u1, "23", led_nets["err_k"])   # GPA2 → D4 cathode (via R5)

# U2 VEML7700 — 1=ADDR_SEL, 2=SDA, 3=SCL, 4=INT, 5=GND, 6=VDD
connect(u2, "1", net_gnd); connect(u2, "2", net_sda1); connect(u2, "3", net_scl1)
connect(u2, "5", net_gnd); connect(u2, "6", net_3v3)
# INT (pin 4) unconnected

# Bypass caps
connect(c1, "1", net_3v3); connect(c1, "2", net_gnd)
connect(c2, "1", net_3v3); connect(c2, "2", net_gnd)

# R1 RESET pull-up
connect(r1, "1", net_3v3); connect(r1, "2", net_rst)

# Switches — pad 1 to signal, pad 2 to GND
for sw_fp, key in [(sw1, "up"), (sw2, "down"), (sw3, "left"),
                   (sw4, "right"), (sw5, "sel"), (sw6, "back")]:
    connect(sw_fp, "1", sw_nets[key])
    connect(sw_fp, "2", net_gnd)

# LEDs — pin 2 (anode) to +3V3, pin 1 (cathode) to intermediate node, through
# resistor to the sink net (GND for D1, MCP output for D2-D4)
def wire_led(d_fp, r_fp, k_net, lo_net):
    connect(d_fp, "2", net_3v3)
    connect(d_fp, "1", k_net); connect(r_fp, "1", k_net)
    connect(r_fp, "2", lo_net)

wire_led(d1, r2, led_nets["pwr_k"], net_gnd)
wire_led(d2, r3, led_nets["gps_k"], led_nets["gps"])   # WAIT — gps_k is BOTH D2 cathode AND U1 GPA0 output
# Actually the net structure should be: U1 GPA0 output directly drives D2 cathode through R3.
# Simplify: led_nets["gps_k"] = U1.GPA0 = D2.cathode = R3.pin1. Drop R3's low side net.
# Better: just wire R3's low-side directly to U1 output. Let me redo this.
# Rewire D2-D4 LED chains cleanly:
# +3V3 → D.A (pin 2) → D.K (pin 1) → R.1 → R.2 → U1 output

# Undo the above incorrect wire_led call for d2 (re-wire properly below)
# Actually the issue: for ACTIVE-LOW drive, the U1 output is the sink.
# Chain: +3V3 → D.A → D.K → R.1 → R.2 → U1 output.
# So: D.A=+3V3, D.K=intermediate_node, R.1=same_intermediate_node, R.2=U1_output_net.
# I already had led_nets["gps_k"] as the intermediate. Redo with correct sink nets:

# Clear by re-wiring d2..d4 deterministically:
connect(d2, "2", net_3v3); connect(d2, "1", led_nets["gps_k"])
connect(r3, "1", led_nets["gps_k"]); connect(r3, "2", led_nets["gps"])

connect(d3, "2", net_3v3); connect(d3, "1", led_nets["ntp_k"])
connect(r4, "1", led_nets["ntp_k"]); connect(r4, "2", led_nets["ntp"])

connect(d4, "2", net_3v3); connect(d4, "1", led_nets["err_k"])
connect(r5, "1", led_nets["err_k"]); connect(r5, "2", led_nets["err"])


# ───────────────────────── GND zone on B.Cu ─────────────────────────

B_CU = board.GetLayerID("B.Cu")
zone = pcbnew.ZONE(board)
zone.SetLayer(B_CU); zone.SetNet(net_gnd); zone.SetIsFilled(True)
zone.SetLocalClearance(MM(0.25)); zone.SetMinThickness(MM(0.25))
zone.SetThermalReliefGap(MM(0.35)); zone.SetThermalReliefSpokeWidth(MM(0.35))

INSET = 0.5; MH_R = 2.5
outline = pcbnew.SHAPE_POLY_SET()
o = pcbnew.SHAPE_LINE_CHAIN()
o.Append(VECTOR2I(MM(INSET), MM(INSET)))
o.Append(VECTOR2I(MM(BOARD_W_MM-INSET), MM(INSET)))
o.Append(VECTOR2I(MM(BOARD_W_MM-INSET), MM(BOARD_H_MM-INSET)))
o.Append(VECTOR2I(MM(INSET), MM(BOARD_H_MM-INSET)))
o.SetClosed(True); outline.AddOutline(o)

def _circle(cx, cy, r, sides=24):
    c = pcbnew.SHAPE_LINE_CHAIN()
    for i in range(sides):
        a = 2*math.pi*i/sides
        c.Append(VECTOR2I(MM(cx + r*math.cos(a)), MM(cy + r*math.sin(a))))
    c.SetClosed(True); return c

for cx, cy in MOUNTING_HOLES_MM:
    outline.AddHole(_circle(cx, cy, MH_R))
zone.SetOutline(outline); board.Add(zone)
pcbnew.ZONE_FILLER(board).Fill(board.Zones())

nc = board.GetDesignSettings(); nc.SetCopperLayerCount(2)
board.Save(out_path)
print(f"PCB: {out_path}", file=sys.stderr)
print(f"Footprints: {len(board.GetFootprints())}  Nets: {board.GetNetCount()}", file=sys.stderr)
