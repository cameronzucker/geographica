"""
GX-01 Adapter HAT — SKiDL circuit definition.

Sits on top of the LC29H in the GX-01 stack. Breaks out the Pi's GPIO into
three clean COTS-friendly connectors for:

  * A KS0108B parallel-interface 128x64 LCD (1x20 pin strip → front panel)
  * Two fan power outputs (2-pin JST-XH headers, 5V + GND)
  * Contrast trim + backlight current limit for the LCD

No active components. Passive routing + three passive components (pot, resistor,
bypass cap) + connectors + mounting holes. Through-hole only for easy
hand-soldering.

The LCD connector is 1x20 to natively match the GDM12864H's connector
(20 solder holes in a single row on the LCD PCB). This also enables clean
routing: by aligning J2's pitch with J1's and assigning GPIOs to matching
X positions, most LCD signals become short straight-line traces.

Run with:
  python3 circuit.py

Outputs:
  gx01-adapter.net — KiCad netlist (input for pcbnew layout)
  erc.log          — electrical rules check report
"""
import os
import sys

os.environ.setdefault("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")
os.environ.setdefault("KICAD9_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
os.environ.setdefault("KICAD_SYMBOL_DIR", "/usr/share/kicad/symbols")

from skidl import (
    Part,
    Net,
    generate_netlist,
    ERC,
    set_default_tool,
    KICAD9,
    POWER,
)

set_default_tool(KICAD9)


# ───────────────────────── Nets ─────────────────────────

p5v = Net("+5V")
p5v.drive = POWER
gnd = Net("GND")
gnd.drive = POWER
vee = Net("VEE")   # LCD's negative contrast bias (from LCD pin 18)
v0 = Net("V0")     # Contrast wiper → LCD pin 3
bla = Net("BLA")   # Backlight anode (after current-limit resistor)

rs = Net("LCD_RS")
rw = Net("LCD_RW")
en = Net("LCD_E")
cs1 = Net("LCD_CS1")
cs2 = Net("LCD_CS2")
rst = Net("LCD_RST")
db = [Net(f"LCD_DB{i}") for i in range(8)]


# ───────────────────────── Components ─────────────────────────

# J1 — Pi GPIO female socket (bottom of this HAT, mates with LC29H's top pins)
J1 = Part(
    "Connector_Generic",
    "Conn_02x20_Odd_Even",
    ref="J1",
    value="Pi GPIO 40-pin socket",
    footprint="Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical",
)

# J2 — LCD output, 1x20 pin header.
# Matches GDM12864H's native 1x20 pad layout for straight-through connection.
J2 = Part(
    "Connector_Generic",
    "Conn_01x20",
    ref="J2",
    value="LCD 20-pin header",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x20_P2.54mm_Vertical",
)

# J3, J4 — JST-XH 2-pin fan power outputs
J3 = Part(
    "Connector_Generic",
    "Conn_01x02",
    ref="J3",
    value="Fan 1 (JST-XH 2pin)",
    footprint="Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical",
)
J4 = Part(
    "Connector_Generic",
    "Conn_01x02",
    ref="J4",
    value="Fan 2 (JST-XH 2pin)",
    footprint="Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical",
)

# RV1 — 10 kΩ multi-turn trim pot for LCD contrast
RV1 = Part(
    "Device",
    "R_Potentiometer",
    ref="RV1",
    value="10k",
    footprint="Potentiometer_THT:Potentiometer_Bourns_3296W_Vertical",
)

# R1 — backlight current-limit resistor
R1 = Part(
    "Device",
    "R",
    ref="R1",
    value="10",
    footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
)

# C1 — 100 nF ceramic bypass cap at LCD VDD input
C1 = Part(
    "Device",
    "C",
    ref="C1",
    value="100nF",
    footprint="Capacitor_THT:C_Disc_D3.0mm_W2.0mm_P2.50mm",
)

# Mounting holes — Pi HAT spec corners
H1 = Part("Mechanical", "MountingHole", ref="H1", value="MH_2.75mm",
          footprint="MountingHole:MountingHole_2.7mm_M2.5")
H2 = Part("Mechanical", "MountingHole", ref="H2", value="MH_2.75mm",
          footprint="MountingHole:MountingHole_2.7mm_M2.5")
H3 = Part("Mechanical", "MountingHole", ref="H3", value="MH_2.75mm",
          footprint="MountingHole:MountingHole_2.7mm_M2.5")
H4 = Part("Mechanical", "MountingHole", ref="H4", value="MH_2.75mm",
          footprint="MountingHole:MountingHole_2.7mm_M2.5")


# ───────────────────────── Pi GPIO pin mapping ─────────────────────────
#
# LC29H GPS HAT uses (minimum): pins 1 (3.3V), 2 (5V) — wait, LC29H gets
# power from the Pi's 5V/3.3V rails — plus pins 8 (UART TX), 10 (UART RX),
# 6 (GND), and possibly 7 (GPIO4 / PPS) and 12 (GPIO18 / reset). HAT ID
# pins 27, 28 are reserved per Raspberry Pi HAT spec.
#
# Our board drives 5V and GND from the Pi rails (no conflict) and leaves
# pins 7, 8, 10, 12, 27, 28 alone.
#
# GPIO-to-LCD mapping chosen so each LCD signal's J1 pad aligns with the
# J2 pad at the same X — trace is a short straight vertical line.
# Exception: LCD DB5 lands on J2 pin 12 whose X aligns with J1 pair 14
# (pins 27/28, HAT-ID reserved). DB5 therefore routes to J1 pair 20
# (pin 40) and jumps to the bottom layer via two vias to clear the other
# vertical traces — one unavoidable detour, documented in the layout file.

# Power + ground pins
gnd += J1[6], J1[9], J1[14], J1[20], J1[25], J1[30], J1[34], J1[39]
p5v += J1[2], J1[4]

# LCD control (each signal aligned to a J2 pin X)
rs  += J1[11]  # GPIO17 → pair 6  (same X as J2 pin 4)
rw  += J1[13]  # GPIO27 → pair 7  (same X as J2 pin 5)
en  += J1[15]  # GPIO22 → pair 8  (same X as J2 pin 6)
cs1 += J1[33]  # GPIO13 → pair 17 (same X as J2 pin 15)
cs2 += J1[35]  # GPIO19 → pair 18 (same X as J2 pin 16)
rst += J1[37]  # GPIO26 → pair 19 (same X as J2 pin 17)

# LCD data lines DB0..DB7 (each aligned to corresponding J2 pin X)
db[0] += J1[18]  # GPIO24 → pair 9  (J2 pin 7)
db[1] += J1[19]  # GPIO10 → pair 10 (J2 pin 8)
db[2] += J1[22]  # GPIO25 → pair 11 (J2 pin 9)
db[3] += J1[23]  # GPIO11 → pair 12 (J2 pin 10)
db[4] += J1[26]  # GPIO7  → pair 13 (J2 pin 11)
db[5] += J1[40]  # GPIO21 → pair 20 (L-bend + via to J2 pin 12; pair 14 = HAT ID)
db[6] += J1[29]  # GPIO5  → pair 15 (J2 pin 13)
db[7] += J1[31]  # GPIO6  → pair 16 (J2 pin 14)


# ───────────────────────── LCD connector wiring ─────────────────────────
# GDM12864H 1x20 pinout:
#   1=VSS, 2=VDD, 3=V0, 4=RS/DI, 5=R/W, 6=E, 7-14=DB0-DB7,
#   15=CS1, 16=CS2, 17=RSTB, 18=Vee, 19=BLA, 20=BLK
gnd += J2[1]              # VSS
p5v += J2[2]              # VDD
v0  += J2[3]              # Contrast wiper
rs  += J2[4]
rw  += J2[5]
en  += J2[6]
for i in range(8):
    db[i] += J2[7 + i]    # DB0..DB7 → J2 pins 7..14
cs1 += J2[15]
cs2 += J2[16]
rst += J2[17]
vee += J2[18]             # Vee comes OUT of the LCD
bla += J2[19]             # Backlight anode
gnd += J2[20]             # Backlight cathode


# ───────────────────────── Fan connectors ─────────────────────────
p5v += J3[1], J4[1]
gnd += J3[2], J4[2]


# ───────────────────────── Analog routing ─────────────────────────
# Contrast pot: VDD ↔ VEE divider, wiper → V0
p5v += RV1[1]
v0  += RV1[2]
vee += RV1[3]

# Backlight current limit: 5V → R1 → BLA
p5v += R1[1]
bla += R1[2]

# Bypass cap on LCD VDD rail
p5v += C1[1]
gnd += C1[2]


# ───────────────────────── ERC + netlist ─────────────────────────

print("Running ERC...", file=sys.stderr)
ERC()

print("Generating netlist...", file=sys.stderr)
generate_netlist(file_="gx01-adapter.net")
print("Netlist written: gx01-adapter.net", file=sys.stderr)
