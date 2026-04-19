"""
GX-01 Front Panel Board — SKiDL circuit definition.

Case-front-mounted user input board. Connects to the Main HAT (gx01-adapter-v2)
via a 6-wire JST-SH cable (VCC, GND, SDA, SCL, INT, RST).

Carries 16-channel I²C GPIO expander (MCP23017) driving:
  - 6 tactile switches (D-pad: Up/Down/Left/Right + Select + Back) on port B
  - 3 software-driven status LEDs (GPS fix / NTP sync / Error) on port A

Plus:
  - 1 hard-wired "Power" LED (tied to +3V3 rail, always on when powered)
  - VEML7700 ambient light sensor (I²C, custom footprint — OPLGA-6 package)

Mechanical rule (from spec): user input forces MUST terminate in the case,
not on the main HAT or LCD. FPB standoffs go directly to the case; JST-SH
cable to main HAT carries signals only, zero mechanical load.

Run with:
  python3 circuit.py
"""
import os
import sys

os.environ.setdefault("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")
os.environ.setdefault("KICAD9_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
os.environ.setdefault("KICAD_SYMBOL_DIR", "/usr/share/kicad/symbols")

from skidl import Part, Net, generate_netlist, ERC, set_default_tool, KICAD9, POWER

set_default_tool(KICAD9)


# ───────────────────────── Nets ─────────────────────────

p3v3 = Net("+3V3"); p3v3.drive = POWER
gnd  = Net("GND");  gnd.drive = POWER
sda1 = Net("SDA1")
scl1 = Net("SCL1")
mcp_int = Net("MCP_INT")   # MCP23017 INTB → Pi GPIO 4 via cable
mcp_rst = Net("MCP_RST")   # MCP23017 RESET (active-low)

# Button signals (internal to FPB — connect switches to MCP23017 port B)
sw_up    = Net("SW_UP")
sw_down  = Net("SW_DOWN")
sw_left  = Net("SW_LEFT")
sw_right = Net("SW_RIGHT")
sw_sel   = Net("SW_SEL")
sw_back  = Net("SW_BACK")

# LED signals (internal to FPB — MCP23017 port A outputs drive LED cathodes
# through current-limit resistors; anodes tied to +3V3)
led_gps  = Net("LED_GPS")
led_ntp  = Net("LED_NTP")
led_err  = Net("LED_ERR")


# ───────────────────────── Cable connector ─────────────────────────
# J1 — JST-SH 6-pin SMT, matches main HAT's J5 pinout 1:1

J1 = Part(
    "Connector_Generic", "Conn_01x06",
    ref="J1",
    value="Cable to HAT (JST-SH 6pin)",
    footprint="Connector_JST:JST_SH_BM06B-SRSS-TB_1x06-1MP_P1.00mm_Vertical",
)
p3v3    += J1[1]
gnd     += J1[2]
sda1    += J1[3]
scl1    += J1[4]
mcp_int += J1[5]
mcp_rst += J1[6]


# ───────────────────────── MCP23017 I²C GPIO expander ─────────────────────────

U1 = Part(
    "Interface_Expansion", "MCP23017_SO",
    ref="U1",
    value="MCP23017",
    footprint="Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm",
)
# Pin map (from KiCad symbol, verified by introspection):
#   1-8=GPB0-GPB7, 9=VDD, 10=VSS, 11=NC, 12=SCL (labelled SCK), 13=SDA,
#   14=NC, 15=A0, 16=A1, 17=A2, 18=~RESET, 19=INTB, 20=INTA,
#   21-28=GPA0-GPA7.

# Power
p3v3 += U1[9]
gnd  += U1[10]

# I²C
scl1 += U1[12]   # labelled SCK in symbol, actually SCL pin
sda1 += U1[13]

# Address pins — all GND → 0x20
gnd += U1[15], U1[16], U1[17]

# RESET (active low)
mcp_rst += U1[18]

# INTB → Pi (via cable J1 pin 5). INTA unused but tie together is customary
# for "interrupt on any port change" — we do that in software, not here.
mcp_int += U1[19]
# U1[20] INTA left floating; software can mirror INT mode onto INTB only.

# Port B → buttons (inputs, pulled up internally by MCP23017)
sw_up    += U1[1]   # GPB0
sw_down  += U1[2]   # GPB1
sw_left  += U1[3]   # GPB2
sw_right += U1[4]   # GPB3
sw_sel   += U1[5]   # GPB4
sw_back  += U1[6]   # GPB5
# GPB6, GPB7 unused — left floating (internal pull-up disables safely)

# Port A → LEDs (outputs)
led_gps += U1[21]   # GPA0
led_ntp += U1[22]   # GPA1
led_err += U1[23]   # GPA2
# GPA3-GPA7 unused


# ───────────────────────── MCP23017 supporting passives ─────────────────────────

# C1 — 100 nF bypass on MCP23017 VDD
C1 = Part("Device", "C", ref="C1", value="100nF",
          footprint="Capacitor_SMD:C_0603_1608Metric")
p3v3 += C1[1]; gnd += C1[2]

# R1 — 10 kΩ pull-up on RESET so the chip doesn't reset at boot before
# the Pi's GPIO is configured as an output
R1 = Part("Device", "R", ref="R1", value="10k",
          footprint="Resistor_SMD:R_0603_1608Metric")
p3v3    += R1[1]
mcp_rst += R1[2]


# ───────────────────────── Tactile switches (6× B3U-3000P) ─────────────────────────
# Omron B3U-3000P. KiCad Button_Switch_SMD:SW_SPST_B3U-3000P has pads 1 & 2.
# One side of the switch ties to the MCP23017 input; the other side ties to
# GND. MCP23017's internal 100 kΩ pull-up holds the line high when open;
# pressing the switch grounds the line (active-low).

def button(ref: str, value: str, signal_net: Net) -> Part:
    global gnd
    sw = Part(
        "Switch", "SW_Push",
        ref=ref,
        value=value,
        footprint="Button_Switch_SMD:SW_SPST_B3U-3000P",
    )
    signal_net += sw[1]
    gnd        += sw[2]
    return sw

SW1 = button("SW1", "UP",     sw_up)
SW2 = button("SW2", "DOWN",   sw_down)
SW3 = button("SW3", "LEFT",   sw_left)
SW4 = button("SW4", "RIGHT",  sw_right)
SW5 = button("SW5", "SELECT", sw_sel)
SW6 = button("SW6", "BACK",   sw_back)


# ───────────────────────── Status LEDs ─────────────────────────
# 4 LEDs, all 0603 SMD. D1 (power) is hardwired — always on when powered.
# D2-D4 (GPS/NTP/Error) driven by MCP23017 port A outputs. LED anodes tie to
# +3V3 (or +3V3 for D1), cathodes tie to MCP23017 output (active-low drive:
# MCP output LOW → LED on; MCP output HIGH → LED off) through a 1 kΩ
# current-limit resistor.
#
# Drive math: V_LED ≈ 2.0V (red/green), I_LED = (3.3 - 2.0) / 1000 = 1.3 mA
# — dim-ish but visible in ambient and easy on the MCP23017 sink current.

# LED wiring convention: for KiCad `Device:LED`, pin 1 = K (cathode),
# pin 2 = A (anode). For active-low drive from an MCP23017 output:
#   +3V3 → anode (pin 2) → [LED] → cathode (pin 1) → resistor → MCP output
# When MCP output is LOW, current flows and the LED is ON.
# D1 (power, always on) has its resistor tied to GND instead of an MCP pin.

def led_driver(d: "Part", r: "Part", lo_net: Net) -> None:
    global p3v3
    node = Net(f"{d.ref}_K")     # intermediate cathode–resistor node
    p3v3 += d[2]
    node += d[1], r[1]
    lo_net += r[2]

def make_led(ref: str, value: str) -> "Part":
    return Part("Device", "LED", ref=ref, value=value,
                footprint="LED_SMD:LED_0603_1608Metric")
def make_r1k(ref: str) -> "Part":
    return Part("Device", "R", ref=ref, value="1k",
                footprint="Resistor_SMD:R_0603_1608Metric")

D1 = make_led("D1", "PWR_Green"); R2 = make_r1k("R2"); led_driver(D1, R2, gnd)
D2 = make_led("D2", "GPS_Blue");  R3 = make_r1k("R3"); led_driver(D2, R3, led_gps)
D3 = make_led("D3", "NTP_Yellow");R4 = make_r1k("R4"); led_driver(D3, R4, led_ntp)
D4 = make_led("D4", "ERR_Red");   R5 = make_r1k("R5"); led_driver(D4, R5, led_err)


# ───────────────────────── VEML7700 ambient light sensor ─────────────────────────
# VEML7700 has no KiCad symbol. We use a generic 6-pin connector placeholder
# and will map a custom OPLGA-6 footprint in layout.py. Pin assignments per
# Vishay datasheet:
#   1=ADDR_SEL (tie to GND → 0x10), 2=SDA, 3=SCL, 4=~INT (unused → floating),
#   5=GND, 6=VDD.

U2 = Part(
    "Connector_Generic", "Conn_01x06",
    ref="U2",
    value="VEML7700",
    footprint="geographica:VEML7700_OPLGA-6",
)
gnd  += U2[1]   # ADDR_SEL → GND → 0x10
sda1 += U2[2]
scl1 += U2[3]
# U2[4] INT — left floating
gnd  += U2[5]
p3v3 += U2[6]

# C2 — 100 nF bypass on VEML7700 VDD
C2 = Part("Device", "C", ref="C2", value="100nF",
          footprint="Capacitor_SMD:C_0603_1608Metric")
p3v3 += C2[1]; gnd += C2[2]


# ───────────────────────── Mounting holes ─────────────────────────
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
generate_netlist(file_="gx01-front-panel.net")
print("Netlist written: gx01-front-panel.net", file=sys.stderr)
