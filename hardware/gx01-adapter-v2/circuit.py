"""
GX-01 Adapter HAT v2 — SKiDL circuit definition.

Mechanically isolated v2 design: all user-facing hardware (buttons, LEDs,
light sensor) lives on a separate Front Panel Board (`gx01-front-panel`)
connected by a 6-wire JST-SH cable. This board carries only "silent"
electronics — RTC, sensors, EEPROM, PWM drivers, fan headers, LCD
signal breakout, Pi passthrough.

Principles vs v1:
  * All-SMT (except Pi passthrough socket + mounting holes): JLC PCBA end-to-end.
  * LCD connector becomes a 2×10 IDC box header accepting a 20-wire ribbon
    to the case-mounted LCD. HAT bears no LCD mechanical load.
  * I²C1 bus added for sensors (RTC, BME280, MCP9808) and for routing to FPB.
  * I²C0 bus used only for HAT ID EEPROM (24LC32 at 0x50) per Pi HAT spec.
  * PWM backlight driver (AO3400) replaces v1's fixed current-limit resistor.
  * Fan connectors upgrade from JST-XH 2-pin (V+, GND) to JST-PH 4-pin
    (V+, GND, PWM, TACH).

LCD GPIO assignments are **identical to v1** so the existing Python KS0108B
driver works without modification.

Run with:
  python3 circuit.py

Outputs:
  gx01-adapter-v2.net — KiCad netlist (input for layout.py)
  erc.log             — ERC report
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

# Power rails
p5v  = Net("+5V");   p5v.drive  = POWER
p3v3 = Net("+3V3");  p3v3.drive = POWER
gnd  = Net("GND");   gnd.drive  = POWER

# I²C1 (GPIO 2/3) — sensors on-board + out to FPB
sda1 = Net("SDA1")
scl1 = Net("SCL1")

# I²C0 (GPIO 0/1, ID_SD/ID_SC) — HAT EEPROM only (Pi HAT spec reserved bus)
id_sd = Net("ID_SD")
id_sc = Net("ID_SC")

# Pi peripheral passthroughs — signals go straight through to LC29H below
pps     = Net("PPS")       # GPIO 18 → pin 12
uart_tx = Net("UART_TX")   # GPIO 14 → pin 8
uart_rx = Net("UART_RX")   # GPIO 15 → pin 10

# FPB interface (via J5)
fpb_int = Net("FPB_INT")   # MCP23017 interrupt, GPIO 4 → pin 7
fpb_rst = Net("FPB_RST")   # MCP23017 reset (driven from GPIO or pulled up on FPB)

# LCD parallel interface (KS0108B) — GPIO mapping identical to v1
lcd_rs  = Net("LCD_RS")
lcd_rw  = Net("LCD_RW")
lcd_e   = Net("LCD_E")
lcd_cs1 = Net("LCD_CS1")
lcd_cs2 = Net("LCD_CS2")
lcd_rst = Net("LCD_RST")
lcd_db  = [Net(f"LCD_DB{i}") for i in range(8)]

# LCD analog
lcd_vee = Net("LCD_VEE")     # KS0108B negative-bias output (~-5V)
lcd_v0  = Net("LCD_V0")      # Contrast input (fixed via resistor divider)
lcd_bla = Net("LCD_BLA")     # Backlight anode (tied to +5V)
lcd_blk = Net("LCD_BLK")     # Backlight cathode (switched to GND via Q1)

# Backlight PWM + fan PWM/tach
bl_pwm   = Net("BL_PWM")     # GPIO 12 → Q1 gate
fan_pwm  = Net("FAN_PWM")    # GPIO 16 → both fan PWM inputs (shared)
fan1_tach = Net("FAN1_TACH") # GPIO 20 → J3 pin 4
fan2_tach = Net("FAN2_TACH") # GPIO 23 → J4 pin 4

# RTC supercap backup node
vbackup = Net("VBACKUP")


# ───────────────────────── Pi GPIO passthrough socket ─────────────────────────

# J1 — 2×20 female pin socket, sits on top of LC29H HAT, accepts Pi headers
J1 = Part(
    "Connector_Generic",
    "Conn_02x20_Odd_Even",
    ref="J1",
    value="Pi GPIO 40-pin socket",
    footprint="Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical",
)

# Pi 40-pin header reference:
#   1=3V3, 2=5V, 3=GPIO2 SDA1, 4=5V, 5=GPIO3 SCL1, 6=GND, 7=GPIO4, 8=GPIO14 TXD0,
#   9=GND, 10=GPIO15 RXD0, 11=GPIO17, 12=GPIO18 PPS, 13=GPIO27, 14=GND,
#   15=GPIO22, 16=GPIO23, 17=3V3, 18=GPIO24, 19=GPIO10, 20=GND, 21=GPIO9,
#   22=GPIO25, 23=GPIO11, 24=GPIO8, 25=GND, 26=GPIO7, 27=GPIO0 ID_SD,
#   28=GPIO1 ID_SC, 29=GPIO5, 30=GND, 31=GPIO6, 32=GPIO12, 33=GPIO13,
#   34=GND, 35=GPIO19, 36=GPIO16, 37=GPIO26, 38=GPIO20, 39=GND, 40=GPIO21

# Power & ground
p3v3 += J1[1], J1[17]
p5v  += J1[2], J1[4]
gnd  += J1[6], J1[9], J1[14], J1[20], J1[25], J1[30], J1[34], J1[39]

# I²C buses
sda1  += J1[3]          # GPIO 2
scl1  += J1[5]          # GPIO 3
id_sd += J1[27]         # GPIO 0 — HAT ID EEPROM SDA
id_sc += J1[28]         # GPIO 1 — HAT ID EEPROM SCL

# Pi peripheral passthroughs (no board-side component — just wire through to LC29H)
pps     += J1[12]       # GPIO 18
uart_tx += J1[8]        # GPIO 14
uart_rx += J1[10]       # GPIO 15

# FPB interface, backlight PWM, fan control
fpb_int   += J1[7]      # GPIO 4  — MCP23017 interrupt
bl_pwm    += J1[32]     # GPIO 12 — hardware PWM0 to Q1 gate
fan_pwm   += J1[36]     # GPIO 16 — shared fan PWM output
fan1_tach += J1[38]     # GPIO 20 — fan 1 tach input
fan2_tach += J1[16]     # GPIO 23 — fan 2 tach input

# LCD signals — IDENTICAL mapping to v1 so existing KS0108B driver works
lcd_rs  += J1[11]        # GPIO 17
lcd_rw  += J1[13]        # GPIO 27
lcd_e   += J1[15]        # GPIO 22
lcd_cs1 += J1[33]        # GPIO 13
lcd_cs2 += J1[35]        # GPIO 19
lcd_rst += J1[37]        # GPIO 26
lcd_db[0] += J1[18]      # GPIO 24
lcd_db[1] += J1[19]      # GPIO 10
lcd_db[2] += J1[22]      # GPIO 25
lcd_db[3] += J1[23]      # GPIO 11
lcd_db[4] += J1[26]      # GPIO 7
lcd_db[5] += J1[40]      # GPIO 21
lcd_db[6] += J1[29]      # GPIO 5
lcd_db[7] += J1[31]      # GPIO 6

# Pin 21 (GPIO 9 MISO) and pin 24 (GPIO 8 CE0) unused — SPI0 is blocked by LCD
# data on GPIO 10/11. Left floating intentionally.


# ───────────────────────── LCD output connector ─────────────────────────

# J2 — 2×10 shrouded IDC box header for 20-wire ribbon to case-mounted LCD.
# Pin k on this header carries the same signal as LCD pin k in the KS0108B
# pinout: 1=VSS, 2=VDD, 3=V0, 4=RS, 5=RW, 6=E, 7-14=DB0-DB7, 15=CS1,
# 16=CS2, 17=RST, 18=VEE, 19=BLA, 20=BLK.
J2 = Part(
    "Connector_Generic",
    "Conn_02x10_Odd_Even",
    ref="J2",
    value="LCD ribbon 2x10 IDC",
    footprint="Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical",
)

gnd        += J2[1]
p5v        += J2[2]
lcd_v0     += J2[3]
lcd_rs     += J2[4]
lcd_rw     += J2[5]
lcd_e      += J2[6]
for i in range(8):
    lcd_db[i] += J2[7 + i]
lcd_cs1    += J2[15]
lcd_cs2    += J2[16]
lcd_rst    += J2[17]
lcd_vee    += J2[18]
lcd_bla    += J2[19]
lcd_blk    += J2[20]


# ───────────────────────── Fan connectors (PWM + tach) ─────────────────────────
# JST-PH 4-pin vertical. Standard fan pinout: 1=GND, 2=V+, 3=TACH, 4=PWM.
# Notice: we're shipping 5V fans (Noctua NF-A4x10 5V etc.), but the signal-level
# convention is the same as 12V PC fans.

J3 = Part(
    "Connector_Generic", "Conn_01x04",
    ref="J3",
    value="Fan 1 (JST-PH 4pin)",
    footprint="Connector_JST:JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical",
)
gnd       += J3[1]
p5v       += J3[2]
fan1_tach += J3[3]
fan_pwm   += J3[4]

J4 = Part(
    "Connector_Generic", "Conn_01x04",
    ref="J4",
    value="Fan 2 (JST-PH 4pin)",
    footprint="Connector_JST:JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical",
)
gnd       += J4[1]
p5v       += J4[2]
fan2_tach += J4[3]
fan_pwm   += J4[4]


# ───────────────────────── FPB cable connector (JST-SH 6-pin SMT) ─────────────────────────
# Pin order chosen to match the FPB's J1 so a straight-through ribbon works.
# 1=+3V3, 2=GND, 3=SDA1, 4=SCL1, 5=INT, 6=RST

J5 = Part(
    "Connector_Generic", "Conn_01x06",
    ref="J5",
    value="FPB cable (JST-SH 6pin SMT)",
    footprint="Connector_JST:JST_SH_BM06B-SRSS-TB_1x06-1MP_P1.00mm_Vertical",
)
p3v3    += J5[1]
gnd     += J5[2]
sda1    += J5[3]
scl1    += J5[4]
fpb_int += J5[5]
fpb_rst += J5[6]


# ───────────────────────── RTC + supercap backup ─────────────────────────
# RV-3028-C7: I²C TCXO RTC with internal trickle charger for supercap backup.
# Pins (per datasheet, SON-8):
#   1=CLKOUT, 2=/INT, 3=VSS (GND), 4=SDA, 5=SCL, 6=/CLKOE, 7=VBACKUP, 8=VDD.

U1 = Part(
    "Timer_RTC", "RV-3028-C7",
    ref="U1",
    value="RV-3028-C7",
    footprint="Package_SON:MicroCrystal_C7_SON-8_1.5x3.2mm_P0.9mm",
)
# Pin names per KiCad Timer_RTC:RV-3028-C7 symbol (pin numbers match datasheet):
#   1=CLKOUT, 2=~INT, 3=SCL, 4=SDA, 5=VSS, 6=VBACKUP, 7=VDD, 8=EVI
sda1    += U1[4]
scl1    += U1[3]
gnd     += U1[5]
vbackup += U1[6]
p3v3    += U1[7]
# CLKOUT (1), ~INT (2), EVI (8) left floating — userspace-only features

# C1 — 1 F supercap between VBACKUP and GND. Custom footprint defined in
# layout.py matching Seiko CPH3225A 6.8×6.8×0.8 mm SMD pattern.
C1 = Part(
    "Device", "C",
    ref="C1",
    value="1F 3.3V",
    footprint="geographica:SuperCap_CPH3225A_6.8x6.8mm",
)
vbackup += C1[1]
gnd     += C1[2]

# C2 — 100 nF bypass on RTC VDD
C2 = Part(
    "Device", "C", ref="C2", value="100nF",
    footprint="Capacitor_SMD:C_0603_1608Metric",
)
p3v3 += C2[1]
gnd  += C2[2]


# ───────────────────────── BME280 environmental sensor ─────────────────────────
# BME280 LGA-8 2.5×2.5 mm. Pins (Bosch clockwise numbering from the notch):
#   1=CSB, 2=SDO (addr select), 3=SDA, 4=SCL, 5=GND, 6=GND, 7=Vdd, 8=VddIO.
# I²C mode: CSB tied high (to VddIO). SDO tied low → address 0x76.

U2 = Part(
    "Sensor", "BME280",
    ref="U2",
    value="BME280",
    footprint="Package_LGA:Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering",
)
# KiCad BME280 symbol uses SPI-convention pin names. In I²C mode:
#   SDI=SDA, SCK=SCL, CSB tied high to VDDIO (I²C mode), SDO=address select.
# Pin numbers per Bosch datasheet (clockwise from notch):
#   1=GND, 2=CSB, 3=SDI, 4=SCK, 5=SDO, 6=VDDIO, 7=GND, 8=VDD
gnd  += U2[1], U2[7]
p3v3 += U2[8], U2[6]     # VDD, VDDIO
p3v3 += U2[2]            # CSB tied high → I²C mode
gnd  += U2[5]            # SDO tied low → address 0x76
sda1 += U2[3]            # SDI is I²C data
scl1 += U2[4]            # SCK is I²C clock

# C3 — 100 nF bypass on BME280 Vdd
C3 = Part(
    "Device", "C", ref="C3", value="100nF",
    footprint="Capacitor_SMD:C_0603_1608Metric",
)
p3v3 += C3[1]
gnd  += C3[2]


# ───────────────────────── MCP9808 case air temperature ─────────────────────────
# MCP9808 MSOP-8, ±0.25 °C case air temperature.
# Pins: 1=SDA, 2=SCL, 3=ALERT, 4=GND, 5=A2, 6=A1, 7=A0, 8=Vdd.
# Address pins A0/A1/A2 all tied to GND → 0x18.

U3 = Part(
    "Sensor_Temperature", "MCP9808_MSOP",
    ref="U3",
    value="MCP9808",
    footprint="Package_SO:MSOP-8_3x3mm_P0.65mm",
)
# Pin numbers per MCP9808 MSOP-8 datasheet:
#   1=SDA, 2=SCL, 3=Alert, 4=GND, 5=A2, 6=A1, 7=A0, 8=V_DD
sda1 += U3[1]
scl1 += U3[2]
# Alert (3) left floating — no userspace consumer
gnd  += U3[4]
gnd  += U3[5], U3[6], U3[7]   # A2, A1, A0 → address 0x18
p3v3 += U3[8]                  # V_DD

# C4 — 100 nF bypass on MCP9808 Vdd
C4 = Part(
    "Device", "C", ref="C4", value="100nF",
    footprint="Capacitor_SMD:C_0603_1608Metric",
)
p3v3 += C4[1]
gnd  += C4[2]


# ───────────────────────── HAT ID EEPROM ─────────────────────────
# 24LC32 SOIC-8, 4 Kibit I²C EEPROM on the Pi HAT spec reserved bus (ID_SD/ID_SC).
# Stores DT overlays + vendor/product strings for auto-configuration.
# A0/A1/A2 tied to GND → address 0x50 (mandatory for HAT ID). WP tied to GND
# to allow initial programming; a solder-bridge jumper on the board can lift
# WP to VDD for write-protected deployment.

U4 = Part(
    "Memory_EEPROM", "24LC32",
    ref="U4",
    value="24LC32",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
)
# Pin numbers per 24LC32A SOIC-8 datasheet:
#   1=A0, 2=A1, 3=A2, 4=GND (VSS), 5=SDA, 6=SCL, 7=WP, 8=VCC
gnd   += U4[1], U4[2], U4[3]   # A0/A1/A2 → 0x50 (HAT spec)
gnd   += U4[4]                  # VSS
id_sd += U4[5]
id_sc += U4[6]
gnd   += U4[7]                  # WP low → write-enabled for initial programming
p3v3  += U4[8]                  # VCC

# C5 — 100 nF bypass on EEPROM VCC
C5 = Part(
    "Device", "C", ref="C5", value="100nF",
    footprint="Capacitor_SMD:C_0603_1608Metric",
)
p3v3 += C5[1]
gnd  += C5[2]


# ───────────────────────── PWM backlight driver (low-side FET) ─────────────────────────
# AO3400A N-ch MOSFET in SOT-23. Low-side switches the LCD backlight cathode
# (BLK) to GND; PWM duty cycle controls average current through the backlight
# LED. Gate driven by Pi GPIO 12 (hardware PWM0). R5 is a gate-to-GND pulldown
# so the FET stays OFF at boot before the GPIO is configured as an output.
# The backlight anode (BLA) is tied to +5V directly at J2 pin 19.

Q1 = Part(
    "Transistor_FET", "AO3400A",
    ref="Q1",
    value="AO3400A",
    footprint="Package_TO_SOT_SMD:SOT-23",
)
# Pin numbers per AO3400A SOT-23 (standard): 1=Gate, 2=Source, 3=Drain
bl_pwm  += Q1[1]         # Gate driven by Pi GPIO 12 (hardware PWM0)
gnd     += Q1[2]         # Source to GND
lcd_blk += Q1[3]         # Drain switches backlight cathode

# Backlight anode tied directly to +5V (no series resistor — LCD module has
# internal limiter and PWM controls average current). Wired at J2 via p5v.
p5v += lcd_bla   # synonym — J2[19] is already on lcd_bla net

# R5 — 10 kΩ gate pulldown
R5 = Part(
    "Device", "R", ref="R5", value="10k",
    footprint="Resistor_SMD:R_0603_1608Metric",
)
bl_pwm += R5[1]
gnd    += R5[2]


# ───────────────────────── LCD V0 contrast divider ─────────────────────────
# Fixed resistor divider between +5V and LCD_VEE (~-5V) to set V0 at midpoint
# (~0V). Yields ~5V contrast drive, a standard KS0108B value. If field
# experience shows readability issues, swap in a BGA trim pot on these pads.

R6 = Part(
    "Device", "R", ref="R6", value="10k",
    footprint="Resistor_SMD:R_0603_1608Metric",
)
p5v    += R6[1]
lcd_v0 += R6[2]

R7 = Part(
    "Device", "R", ref="R7", value="10k",
    footprint="Resistor_SMD:R_0603_1608Metric",
)
lcd_v0  += R7[1]
lcd_vee += R7[2]


# ───────────────────────── I²C1 pull-ups ─────────────────────────
# 4.7 kΩ to +3V3 on SDA1 and SCL1. Pi internal pull-ups are ~50 kΩ and not
# strong enough for 400 kHz I²C with 5 devices + a ~30 cm cable to the FPB.

R1 = Part(
    "Device", "R", ref="R1", value="4.7k",
    footprint="Resistor_SMD:R_0603_1608Metric",
)
p3v3 += R1[1]
sda1 += R1[2]

R2 = Part(
    "Device", "R", ref="R2", value="4.7k",
    footprint="Resistor_SMD:R_0603_1608Metric",
)
p3v3 += R2[1]
scl1 += R2[2]


# ───────────────────────── I²C0 (HAT ID) pull-ups ─────────────────────────
# Pi HAT spec requires the ID bus to have pull-ups on the HAT. 3.3 kΩ is
# the canonical value per the spec.

R3 = Part(
    "Device", "R", ref="R3", value="3.3k",
    footprint="Resistor_SMD:R_0603_1608Metric",
)
p3v3  += R3[1]
id_sd += R3[2]

R4 = Part(
    "Device", "R", ref="R4", value="3.3k",
    footprint="Resistor_SMD:R_0603_1608Metric",
)
p3v3  += R4[1]
id_sc += R4[2]


# ───────────────────────── Mounting holes ─────────────────────────
# Standard Pi HAT hole positions. Plated-through, M2.5 hardware.

H1 = Part("Mechanical", "MountingHole", ref="H1", value="MH_2.75mm",
          footprint="MountingHole:MountingHole_2.7mm_M2.5")
H2 = Part("Mechanical", "MountingHole", ref="H2", value="MH_2.75mm",
          footprint="MountingHole:MountingHole_2.7mm_M2.5")
H3 = Part("Mechanical", "MountingHole", ref="H3", value="MH_2.75mm",
          footprint="MountingHole:MountingHole_2.7mm_M2.5")
H4 = Part("Mechanical", "MountingHole", ref="H4", value="MH_2.75mm",
          footprint="MountingHole:MountingHole_2.7mm_M2.5")


# ───────────────────────── ERC + netlist ─────────────────────────

print("Running ERC...", file=sys.stderr)
ERC()

print("Generating netlist...", file=sys.stderr)
generate_netlist(file_="gx01-adapter-v2.net")
print("Netlist written: gx01-adapter-v2.net", file=sys.stderr)
