"""
GX-01 Adapter HAT — SKiDL circuit definition.

Sits on top of the LC29H in the GX-01 stack. Its sole job is to break out the
Pi's GPIO rail into three clean COTS-friendly connectors for:

  * A KS0108B parallel-interface 128x64 LCD (20-pin ribbon cable → front panel)
  * Two fan power outputs (2-pin JST-XH headers, 5V + GND)
  * Contrast trim + backlight current limit for the LCD

No active components. Passive routing + three passive components (pot, resistor,
bypass cap) + connectors + mounting holes. Through-hole only for easy
hand-soldering.

Run with:
  KICAD9_SYMBOL_DIR=/usr/share/kicad/symbols \
  KICAD9_FOOTPRINT_DIR=/usr/share/kicad/footprints \
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
    erc_logger,
    set_default_tool,
    KICAD9,
    TEMPLATE,
    POWER,
)

set_default_tool(KICAD9)


# ───────────────────────── Nets ─────────────────────────

p5v = Net("+5V")
p5v.drive = POWER
gnd = Net("GND")
gnd.drive = POWER
vee = Net("VEE")  # LCD's negative contrast bias (from LCD pin 18, ~-5V)
v0 = Net("V0")  # Contrast wiper → LCD pin 3
bla = Net("BLA")  # Backlight anode (after current-limit resistor)

rs = Net("LCD_RS")  # data/instruction select
rw = Net("LCD_RW")  # read/write
en = Net("LCD_E")  # enable
cs1 = Net("LCD_CS1")
cs2 = Net("LCD_CS2")
rst = Net("LCD_RST")

db = [Net(f"LCD_DB{i}") for i in range(8)]


# ───────────────────────── Components ─────────────────────────

# J1 — Pi GPIO female socket (bottom of this HAT, mates with LC29H's top pins).
# Standard 2×20 0.1" pitch. Pi 5 pinout is the canonical Raspberry Pi
# numbering: pin 1 = 3.3V (square pad), pin 2 = 5V, odd pins on one row,
# even pins on the other. We use Odd_Even numbering (KiCad's default 2x20).
J1 = Part(
    "Connector_Generic",
    "Conn_02x20_Odd_Even",
    ref="J1",
    value="Pi GPIO 40-pin socket",
    footprint="Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical",
)

# J2 — LCD ribbon output (20-pin box header, 2×10 at 2.54 mm pitch).
# Pin order follows the SparkFun GDM12864H datasheet (1=VSS, 2=VDD, 3=V0,
# 4=RS, 5=R/W, 6=E, 7-14=DB0-DB7, 15=CS1, 16=CS2, 17=RST, 18=Vee, 19=BLA,
# 20=BLK). Match this pin order at connector placement so a straight ribbon
# works without crossing conductors.
J2 = Part(
    "Connector_Generic",
    "Conn_02x10_Odd_Even",
    ref="J2",
    value="LCD 20-pin IDC",
    footprint="Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical",
)

# J3, J4 — JST-XH 2-pin fan power outputs.
# Pin 1 = +5V, pin 2 = GND. Fans' 3-pin Noctua-style connectors mate via a
# COTS JST-XH-to-3pin-fan adapter pigtail.
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

# RV1 — 10 kΩ multi-turn trim pot for LCD contrast.
# Pot endpoints: VDD (+5V) ↔ VEE (from LCD pin 18, ~-5V).
# Wiper → V0 (LCD pin 3).
# The VEE-based divider gives full contrast sweep; simpler VDD-GND dividers
# work for some modules but leave contrast flat on the GDM12864H.
RV1 = Part(
    "Device",
    "R_Potentiometer",
    ref="RV1",
    value="10k",
    footprint="Potentiometer_THT:Potentiometer_Bourns_3296W_Vertical",
)

# R1 — backlight current-limit resistor.
# GDM12864H backlight is spec'd ~4.2V / 200mA; a 10Ω 1/2W resistor drops ~2V
# limiting current to ~180 mA at nominal. Safe if the module has no internal
# resistor; benign if it does (minor brightness reduction).
R1 = Part(
    "Device",
    "R",
    ref="R1",
    value="10",
    footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
)

# C1 — 100 nF ceramic bypass cap at LCD VDD input.
# Small-footprint disc cap adjacent to J2's VDD pin, returns to nearest GND.
C1 = Part(
    "Device",
    "C",
    ref="C1",
    value="100nF",
    footprint="Capacitor_THT:C_Disc_D3.0mm_W2.0mm_P2.50mm",
)

# Mounting holes — Pi HAT spec: 4× holes at 58 × 49 mm corners, 2.75 mm dia
# for M2.5 fasteners. KiCad has a "MountingHole" virtual component that
# places a drilled hole without a net connection.
H1 = Part(
    "Mechanical",
    "MountingHole",
    ref="H1",
    value="MH_2.75mm",
    footprint="MountingHole:MountingHole_2.7mm_M2.5",
)
H2 = Part(
    "Mechanical",
    "MountingHole",
    ref="H2",
    value="MH_2.75mm",
    footprint="MountingHole:MountingHole_2.7mm_M2.5",
)
H3 = Part(
    "Mechanical",
    "MountingHole",
    ref="H3",
    value="MH_2.75mm",
    footprint="MountingHole:MountingHole_2.7mm_M2.5",
)
H4 = Part(
    "Mechanical",
    "MountingHole",
    ref="H4",
    value="MH_2.75mm",
    footprint="MountingHole:MountingHole_2.7mm_M2.5",
)


# ───────────────────────── Pi GPIO pin mapping ─────────────────────────
# Pi 5 GPIO header pins (physical numbering) to nets.
# Ground pins: 6, 9, 14, 20, 25, 30, 34, 39 (all tied to GND).
# 5V pins: 2, 4.
# 3.3V pins: 1, 17 — we do not route these; they remain unconnected on the
#     adapter HAT since no component on this board runs on 3.3V.
# ID_SD (27), ID_SC (28) — HAT ID EEPROM pins; left unconnected (no EEPROM on
#     this v1 board; we may add one in v2 for proper HAT+ ID).
# All other GPIO pins get assigned to LCD control/data lines below.

gnd += J1[6], J1[9], J1[14], J1[20], J1[25], J1[30], J1[34], J1[39]
p5v += J1[2], J1[4]

# LCD control:
rs += J1[11]  # GPIO17
rw += J1[13]  # GPIO27
en += J1[15]  # GPIO22
cs1 += J1[16]  # GPIO23
cs2 += J1[18]  # GPIO24
rst += J1[22]  # GPIO25

# LCD data lines (DB0-DB7), chosen as a contiguous block on the lower half of
# the GPIO header to make trace routing cleaner on the PCB:
db[0] += J1[37]  # GPIO26
db[1] += J1[36]  # GPIO16
db[2] += J1[35]  # GPIO19
db[3] += J1[33]  # GPIO13
db[4] += J1[32]  # GPIO12
db[5] += J1[31]  # GPIO6
db[6] += J1[29]  # GPIO5
db[7] += J1[40]  # GPIO21


# ───────────────────────── LCD connector wiring ─────────────────────────
# GDM12864H pinout (confirmed from Sparkfun datasheet):
#  1=VSS, 2=VDD, 3=V0, 4=RS/DI, 5=R/W, 6=E, 7-14=DB0-DB7,
#  15=CS1, 16=CS2, 17=RSTB, 18=Vee, 19=BLA, 20=BLK
gnd += J2[1]  # VSS
p5v += J2[2]  # VDD
v0 += J2[3]  # Contrast
rs += J2[4]
rw += J2[5]
en += J2[6]
for i in range(8):
    db[i] += J2[7 + i]  # DB0..DB7 → J2 pins 7..14
cs1 += J2[15]
cs2 += J2[16]
rst += J2[17]
vee += J2[18]  # Vee comes OUT of the LCD on pin 18
bla += J2[19]  # Backlight anode (after current-limit resistor)
gnd += J2[20]  # Backlight cathode


# ───────────────────────── Fan connectors ─────────────────────────
p5v += J3[1], J4[1]
gnd += J3[2], J4[2]


# ───────────────────────── Analog routing ─────────────────────────
# Contrast pot: VDD ↔ VEE divider, wiper → V0
p5v += RV1[1]
v0 += RV1[2]  # wiper
vee += RV1[3]

# Backlight current limit: 5V → R1 → BLA
p5v += R1[1]
bla += R1[2]

# Bypass cap on LCD VDD rail
p5v += C1[1]
gnd += C1[2]


# ───────────────────────── ERC + netlist generation ─────────────────────────

print("Running ERC...", file=sys.stderr)
ERC()
# If ERC found any genuine issues they'll appear in the log; SKiDL's default
# ERC is strict (e.g., it flags unconnected pins, including pins we intend to
# leave floating like Pi 3.3V pins). This is noise for this design, not a
# bug; we review the ERC log manually.

print("Generating netlist...", file=sys.stderr)
generate_netlist(file_="gx01-adapter.net")
print("Netlist written: gx01-adapter.net", file=sys.stderr)
