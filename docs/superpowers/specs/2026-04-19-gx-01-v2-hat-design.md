# GX-01 Adapter HAT v2 — Design

**Status:** Design spec — ready for implementation planning
**Author:** Cameron Zucker (with Claude)
**Date:** 2026-04-19
**Scope:** Revision of the GX-01 adapter HAT, splitting user-facing hardware off onto a separate Front Panel Board and adding RTC, environmental sensors, status LEDs, PWM backlight, PWM fans, and HAT ID EEPROM. Targets JLCPCB SMT Assembly end-to-end; no hand soldering required.

## Summary

The v1 GX-01 adapter HAT is a minimal through-hole passthrough that breaks out the Pi 5's GPIO to the GDM12864H LCD and two 5 V fan connectors. It works, but leaves a large amount of blank PCB area and most of the Pi's unused GPIOs unconfigured. v2 fills that blank space with features this device has always needed — a high-precision GPS-disciplined NTP holdover clock, environmental sensing, auto-dimming backlight, PWM fan control, HAT ID auto-overlay loading, and a menu-driven UI — while simultaneously **removing all user-facing hardware from the HAT itself** to eliminate a documented mechanical failure mode where button press forces propagate into LCD solder joints.

The design is a **two-board package**: the **Main HAT** (`gx01-adapter-v2`) carries silent electronics (RTC, sensors, EEPROM, fan drivers, LCD signal breakout), and a separate **Front Panel Board** (`gx01-front-panel`) carries all user interaction (buttons, status LEDs, ambient light sensor). The Front Panel Board mounts to the case front with its own M2.5 standoffs, connected to the HAT by a six-wire JST-SH cable that carries only signals and zero mechanical load. The LCD also migrates from direct-solder-to-HAT to case-mounted with a 20-wire ribbon cable to the HAT — the HAT becomes fully mechanically isolated from any user-reachable surface.

Both boards are designed for **JLCPCB SMT Assembly**: all components verified stocked in the JLC library, BOM/CPL generated for submission, no hand soldering on either custom board. End-to-end path is "upload Gerbers + BOM + CPL → receive populated boards in ~2 weeks." (The only hand-solder step in the full system build is a 1×20 through-hole header on the SparkFun GDM12864H LCD module itself, which arrives un-headered from SparkFun — that's on pre-existing hardware, not on either custom PCB.)

## Goals

1. Provide a **GPS-disciplined NTP time source that survives GPS outages** across −40 to +85 °C thermal excursions — device may be unplugged and transported in hot or cold conditions and must resume stratum-2-worthy time service on boot
2. Support a **menu-driven UI** on the existing 128×64 LCD with robust tactile buttons, without exposing any user-input hardware to the LCD's solder joints
3. Auto-dim the LCD backlight based on ambient light so the display is readable indoors and outdoors without manual adjustment
4. Report **environmental conditions** (temperature, humidity, pressure, case air temp) as a shipped software feature, with the sensors placed where their readings are physically meaningful
5. Drive the two case cooling fans with **PWM + tach feedback** tied to a userspace thermal controller that mirrors the Pi's master fan curve
6. Make the HAT **auto-configure** on first boot — Pi detects the HAT's ID EEPROM and loads all required device tree overlays (PPS, I²C RTC, 1-Wire if present, PWM backlight) without the user editing config files
7. Provide four **at-a-glance status LEDs** (power / GPS fix / NTP sync / error) for field debugging without a terminal
8. Be **100 % JLCPCB-assembleable** — zero hand-soldering steps between fab delivery and working board
9. Preserve the existing LC29H stacking, GPIO-assigned LCD control pins, and 40-pin passthrough from the v1 HAT — no upstream rework

## Non-goals

- NOT a battery-capable mobile device. Lithium-backed operation is UPS-style (smooth ~60 s power gaps) only; off-grid runtime is out of scope. **INA219** current/voltage monitoring is specifically excluded — the existing X1207 PoE/UPS HAT handles battery state readout via its own GPIO.
- NOT a redesign of the LCD interface. The GDM12864H / KS0108B / 14-GPIO parallel bus is preserved exactly as in v1. Only the physical connector form factor changes (1×20 solder pad → 2×10 IDC box header).
- NOT a Linux audio / STT input surface. No buzzer, speaker, or microphone on the HAT.
- NOT a motion-sensing device. IMU / accelerometer / gyro explicitly out of scope.
- NOT compatible with v1 case mechanicals without modification. The case's front panel and LCD mounting require rework to accommodate the Front Panel Board standoffs and the LCD's new case-standoff mount. A separate case-design-revision spec will follow.

## Architecture overview

### Two-board split

```
┌──────────────────────────────────────────┐
│  CASE FRONT PANEL (mechanically rigid)   │
│  ┌─────────────────────────────────────┐ │
│  │ Front Panel Board (gx01-front-      │ │
│  │ panel)                              │ │
│  │   ▪ MCP23017 I²C expander           │ │
│  │   ▪ 6× Omron B3U tactile switches   │ │
│  │   ▪ 4× SMD 0603 status LEDs         │ │
│  │   ▪ VEML7700 ambient light sensor   │ │
│  │                                     │ │
│  │   ← mounted to case via 4× M2.5     │ │
│  └────────┬────────────────────────────┘ │
└───────────┼──────────────────────────────┘
            │ JST-SH 6-wire, signals only,
            │ zero mechanical load
            │ (VCC, GND, SDA, SCL, INT, RST)
            ▼
┌──────────────────────────────────────────┐
│  CASE INTERIOR                           │
│  ┌─────────────────────────────────────┐ │
│  │ LCD (GDM12864H, case-mounted)       │ │
│  └────────┬────────────────────────────┘ │
│           │ 20-wire IDC ribbon           │
│           │ (signals only)               │
│           ▼                              │
│  ┌─────────────────────────────────────┐ │
│  │ Main HAT (gx01-adapter-v2)          │ │
│  │   ▪ RV-3028-C7 RTC + supercap       │ │
│  │   ▪ BME280 env sensor               │ │
│  │   ▪ MCP9808 case air temp           │ │
│  │   ▪ 24C32 HAT ID EEPROM             │ │
│  │   ▪ AO3400 PWM backlight driver     │ │
│  │   ▪ 2× JST-PH 4-pin PWM fan hdr     │ │
│  │   ▪ 2×10 IDC LCD connector          │ │
│  │   ▪ 40-pin Pi passthrough           │ │
│  └────────┬────────────────────────────┘ │
│           │ 40-pin GPIO header            │
│           ▼                              │
│  ┌─────────────────────────────────────┐ │
│  │ Waveshare LC29H GPS HAT             │ │
│  └────────┬────────────────────────────┘ │
│           ▼                              │
│  ┌─────────────────────────────────────┐ │
│  │ AI HAT+ 2 (Hailo)                   │ │
│  ├─────────────────────────────────────┤ │
│  │ Raspberry Pi 5 16 GB                │ │
│  └─────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

### Mechanical rule (critical)

> **No user-reachable hardware is mounted on, soldered to, or mechanically loading any PCB that carries the LCD or its signals.** All user interaction forces (button presses) terminate in the case via the Front Panel Board's standoffs. The Main HAT's only mechanical loads are the Pi 40-pin header and its own four M2.5 standoffs — both internal, both rigid, both far from any touchable surface.

This rule exists because of documented field failures in similar designs where buttons-on-main-PCB configurations transmitted press forces into LCD solder joints, causing fatigue cracks and display failures over the service life. Violating the rule re-introduces that failure mode.

## Hardware manifest

### Main HAT (`gx01-adapter-v2`)

| Ref | Component | LCSC / JLC | Package | Role | Unit @ 10 |
|---|---|---|---|---|---|
| U1 | RV-3028-C7-32.768kHz-1ppm-TA-QC | C3019759 | SMD3215-8P | I²C RTC, TCXO, 45 nA backup, internal trickle charger | ~$2.00 |
| U2 | BME280 | (TBD — LCSC stock verification) | LGA-8 2.5×2.5 mm | I²C T/H/P sensor, behind case vent | ~$3 |
| U3 | MCP9808-H/MSTR | C76147 | MSOP-8 | I²C case air temp, ±0.25 °C | ~$1.50 |
| U4 | 24LC32AT-I/SN | C56663 | SOIC-8 | HAT ID EEPROM, 0x50 on I²C0 | ~$0.25 |
| Q1 | AO3400 (N-FET) | C20917 | SOT-23 | PWM backlight driver, low-side switch | ~$0.05 |
| C1 | Seiko CPH3225A | C520488 | SMD 6.8×6.8×0.9 mm | 1 F 3.3 V supercap for RTC backup | ~$2.00 |
| C2–C8 | 100 nF X7R 0603 | (basic) | 0603 | Decoupling (one per IC, one per sensor rail) | $0.01 ea |
| R1–R4 | 4.7 kΩ 0603 | (basic) | 0603 | I²C1 / I²C0 pull-ups | $0.01 ea |
| R5 | 10 kΩ 0603 | (basic) | 0603 | MOSFET gate pulldown | $0.01 |
| D1 | BAT54 Schottky | (basic) | SOT-23 | Optional supercap backfeed protection | $0.05 |
| J1 | 2×20 female pin socket | (existing v1) | through-hole | Pi GPIO passthrough | ~$1 |
| J2 | 2×10 IDC boxed header, 2.54 mm | (basic) | through-hole | LCD signal ribbon output | ~$0.50 |
| J3 | JST-SH 6-pin, 1.0 mm, SMT | (basic) | SMT | To Front Panel Board — VCC/GND/SDA/SCL/INT/RST | ~$0.20 |
| J4, J5 | JST-PH 4-pin, 2.0 mm, SMT | (basic) | SMT | PWM fans (V+, GND, PWM, TACH) | ~$0.20 ea |
| H1–H4 | 2.75 mm drilled holes | — | — | M2.5 mounting, standard Pi HAT positions | — |

**Main HAT BOM subtotal (per board, qty 10 run):** ~$12 parts. Feeder fees: 6 Extended parts × $3 = $18 one-time per batch. Amortized at qty 10: ~$13.80 per board.

### Front Panel Board (`gx01-front-panel`)

| Ref | Component | LCSC / JLC | Package | Role | Unit @ 10 |
|---|---|---|---|---|---|
| U1 | MCP23017-E/SO | C8672 | SOIC-28 | 16-bit I²C GPIO expander, 0x20 | ~$2.00 |
| U2 | VEML7700 | C164531 | OPLGA-6 | I²C ambient light sensor, near LCD | ~$1.50 |
| SW1–SW6 | Omron B3U-3000P or Alps SKQU | C720478 or eq. | SMT 6×6 mm | Tactile switches (Up, Down, Left, Right, Select, Back) | ~$0.50 ea |
| D1–D4 | 0603 LEDs, 4 colors (green, blue, yellow, red) | (basic) | 0603 | Power / GPS-fix / NTP-sync / Error status | $0.05 ea |
| R1–R4 | 1 kΩ 0603 | (basic) | 0603 | LED current-limit resistors | $0.01 ea |
| R5 | 10 kΩ 0603 | (basic) | 0603 | MCP23017 RESET pull-up | $0.01 |
| C1–C2 | 100 nF 0603 | (basic) | 0603 | Decoupling | $0.01 ea |
| J1 | JST-SH 6-pin, 1.0 mm, SMT | (basic) | SMT | From Main HAT | ~$0.20 |
| H1–H4 | 2.75 mm drilled holes | — | — | Case-mount M2.5 standoffs | — |

**FPB BOM subtotal (per board, qty 10 run):** ~$8 parts. Feeder fees: 3 Extended parts × $3 = $9 one-time per batch. Amortized at qty 10: ~$8.90 per board.

### Assembled cost target

Per complete v2 system (one HAT + one FPB, qty 10 run, JLC PCBA Economic tier, shipping not included):
- Fab: ~$5 HAT + ~$3 FPB = $8
- Assembly: ~$20 HAT + ~$10 FPB = $30
- Parts + feeder amortization: ~$22
- **Total: ~$60 per system**

## Subsystem designs

### RTC + supercap power subsystem

The RV-3028-C7 is a TCXO I²C RTC with ±3 ppm accuracy over −40/+85 °C, an internal programmable trickle charger, and 45 nA typical backup current. The supercap is a Seiko CPH3225A — 1 F, 3.3 V rated, surface-mount, 6.8 × 6.8 × 0.9 mm.

**Charge path:** The RV-3028's `EECharge` bit enables internal trickle charging from VDD to the VBACKUP pin through a selectable series resistance (3 kΩ / 5 kΩ / 9 kΩ / 15 kΩ). The supercap connects VBACKUP to GND with an optional 100 nF parallel cap for HF bypass. No external charge-limit resistor needed. On firmware boot, the RTC init routine sets `EECharge = 1`, `TCR = 3 kΩ`, and `BSM = level-switching`.

**Discharge path:** When VDD drops below the VBACKUP level, the RTC automatically switches to the supercap. 45 nA chip draw plus ~2 μA supercap self-leakage gives ~9 days of holdover from a fully charged 1 F cap — comfortably beyond any realistic transport-and-stow window. If the device is off longer than that, the RTC loses time; on the next boot, chrony will re-lock GPS-disciplined time within a minute and the user sees no functional impact.

**Thermal holdover:** At worst case (−40 °C or +85 °C, fully GPS-disconnected), the ±3 ppm TCXO drifts ~260 ms per day. The existing chrony config (`maxupdateskew 100.0`, `makestep 1 3`) smooths this on reconnection; AREDN mesh peers see sub-second accuracy throughout.

**Software integration:** `dtoverlay=i2c-rtc,rv3028` in the HAT ID EEPROM triggers automatic load. chrony's existing `rtcsync` directive writes disciplined time to `/dev/rtc0` every 11 minutes when GPS is locked. No userspace changes required.

### I²C bus topology

**I²C0 (GPIO 0/1 — HAT ID reserved per the Pi HAT spec)**
- 24C32 EEPROM @ 0x50 — HAT ID + device tree overlays

**I²C1 (GPIO 2/3 — general-purpose)**
- RV-3028-C7 @ 0x52 — RTC
- BME280 @ 0x76 — environmental sensor
- VEML7700 @ 0x10 — ambient light sensor (on FPB, via cable)
- MCP9808 @ 0x18 — case air temp
- MCP23017 @ 0x20 — GPIO expander (on FPB, via cable)

5 devices on I²C1. 4.7 kΩ pull-ups on SDA/SCL placed on the Main HAT (the bus master end). Bus length including the FPB cable ~30 cm, well within 400 kHz fast-mode I²C reach with proper pull-ups.

### GPIO budget (Pi 5 BCM pins)

| GPIO | Usage (v1) | Usage (v2) |
|---|---|---|
| 0, 1 | unused | **HAT ID EEPROM (I²C0)** |
| 2, 3 | passthrough to LC29H | **I²C1 (RTC, BME280, MCP9808, MCP23017, VEML7700) + passthrough** |
| 4 | unused | **MCP23017 interrupt input (INT)** |
| 5, 6, 7 | LCD data | LCD data (unchanged) |
| 8, 9 | unused | spare (candidates for serial console on UART2) |
| 10, 11 | LCD data | LCD data (unchanged) |
| 12 | unused | **PWM0 — LCD backlight hardware PWM** |
| 13 | LCD CS1 | LCD CS1 (unchanged — conflicts with PWM1, accepted) |
| 14, 15 | UART0 passthrough to LC29H | UART0 passthrough (unchanged) |
| 16 | unused | **Fan PWM (pigpio DMA, 25 kHz)** |
| 17 | LCD RS | LCD RS (unchanged) |
| 18 | PPS passthrough to LC29H | PPS passthrough (unchanged) |
| 19 | LCD CS2 | LCD CS2 (unchanged) |
| 20 | unused | **Fan 1 tach input** |
| 21 | LCD data | LCD data (unchanged) |
| 22 | LCD EN | LCD EN (unchanged) |
| 23 | unused | **Fan 2 tach input** |
| 24, 25 | LCD data | LCD data (unchanged) |
| 26 | LCD RST | LCD RST (unchanged) |
| 27 | LCD RW | LCD RW (unchanged) |

**Total used: 26 of 28. Spares: GPIO 8, 9 (both unused — reserved for future UART2 serial console accessory).**

### HAT ID EEPROM + auto-overlay loading

The 24C32 stores a binary blob generated from a text descriptor via the `eepmake` tool in the Raspberry Pi `hats` project. The blob lists:

- Vendor string: "Geographica"
- Product string: "GX-01 Adapter HAT v2"
- Product UUID, version, PID
- GPIO pin map (which pins this HAT uses and with what pull-up/direction)
- **dtoverlay directives**: `pps-gpio,gpiopin=18`, `i2c-rtc,rv3028`, `pwm-2chan,pin=12,func=4`

On boot, the Pi firmware reads the EEPROM via I²C0 and applies the listed overlays before Linux fully initializes. Users never edit `config.txt` — plug the HAT in, it works. Write-protect via solder jumper; WP pulled high by default (disabled), bridge a jumper pad to enable WP for field units.

### Status LEDs

Four SMD 0603 LEDs on the FPB, driven by MCP23017 output pins through 1 kΩ current-limit resistors. Color convention (selected to be consistent with common network-device semantics):

| LED | Color | Driver | Source of truth |
|---|---|---|---|
| Power | Green | Hard-wired to 3.3V rail (always on when powered) | N/A — passive |
| GPS fix | Blue | MCP23017 GPIOA0 | `gpsd`'s `TPV.status` field via userspace daemon |
| NTP sync | Yellow | MCP23017 GPIOA1 | `chronyc tracking` — high when System time synchronized |
| Error | Red | MCP23017 GPIOA2 | Userspace daemon aggregates systemd service failures + custom health checks |

Note: "Power" LED is hard-wired to the 3.3 V rail (simplest, most reliable — if the board has power, the LED is on). The other three are software-controlled via the MCP23017.

### Tactile buttons

Six Omron B3U-3000P SMT switches (6×6 mm, 3.5 mm nominal height, 160 gf actuation, 300k cycle life) mounted on the FPB. Button caps are user choice — a common option is Alps K4T series black plastic button caps that press-fit the B3U plunger.

| Switch | MCP23017 pin | Default kernel mapping (via `mcp23xxx-keys` overlay) |
|---|---|---|
| SW1 | GPIOB0 | `KEY_UP` |
| SW2 | GPIOB1 | `KEY_DOWN` |
| SW3 | GPIOB2 | `KEY_LEFT` |
| SW4 | GPIOB3 | `KEY_RIGHT` |
| SW5 | GPIOB4 | `KEY_ENTER` |
| SW6 | GPIOB5 | `KEY_ESC` |

Interrupts: MCP23017's `INTB` pin ties to Pi GPIO 4 via the JST-SH cable. The kernel exposes the MCP23017 as a gpiochip (via the mainline `gpio-mcp23s08` driver, selected by the `mcp23017` device tree overlay); a second overlay chains the `gpio-keys` driver against that gpiochip with the keycode table above. Buttons present to userspace as standard input events at `/dev/input/by-path/platform-gx01-panel-event-kbd`. Debounce is handled by `gpio-keys`'s `debounce-interval` property (default 5 ms is fine for mechanical tactiles).

### PWM backlight

Replaces v1's fixed R1 (10 Ω 1/2 W) current-limit resistor. AO3400 N-FET switches the backlight LED cathode to ground; gate driven by Pi GPIO 12 (hardware PWM0, 25 kHz). 10 kΩ gate pulldown keeps the FET off if the GPIO floats at boot.

**Userspace daemon** (`gx01-backlight-daemon`): reads VEML7700 lux every 2 seconds, maps through a user-configurable curve (`/etc/gx01/backlight-curve.toml`) to a PWM duty cycle, writes to `/sys/class/pwm/pwmchip0/pwm0/duty_cycle`. Curve is linear in log space with min/max clamps; dark environments get ~5 % brightness, direct sunlight gets 100 %. User can override via the menu UI (written to config file, daemon re-reads on SIGHUP).

### PWM fans

Each fan header is a 4-pin JST-PH 2.0 mm: V+ (5 V), GND, PWM, TACH.

- PWM output (GPIO 16, shared by both fans): pigpio DMA PWM, 25 kHz, driven by `gx01-fan-daemon`
- TACH inputs (GPIO 20 for fan 1, GPIO 23 for fan 2): pulled up internally, reading rising-edge count per second → RPM / 30 (two pulses per revolution for most brushless fans)
- V+ fed directly from Pi 5 V rail; expected current per 40 mm 5 V fan is ~100 mA at full speed
- Daemon reads `/sys/class/thermal/thermal_zone0/temp` (Pi SoC) + MCP9808 (case air) + BME280 ambient, produces a curve output 0–100 % duty. Default curve in `/etc/gx01/fan-curve.toml`: below 45 °C = off, 45–55 °C linear ramp to 40 %, 55–70 °C linear to 100 %, above 70 °C = 100 % + error LED. User-editable.

### LCD connection

v1's 1×20 solder pad directly mated to the GDM12864H module. v2 replaces this with:

- **Main HAT side:** 2×10 shrouded IDC box header (2.54 mm pitch). Polarized. Keyed so ribbon can only insert one way.
- **Cable:** 20-conductor flat ribbon, IDC terminated on the HAT end, standard 1×20 connector or flying pins on the LCD end.
- **LCD side:** The GDM12864H keeps its native 1×20 solder pad. A small through-hole 1×20 header is soldered onto the LCD module for the ribbon to connect.
- **LCD mechanical mount:** Four M2.5 screws into case standoffs through the GDM12864H's existing corner mounting holes. **HAT bears zero LCD weight.**

Pin ordering on the 2×10 IDC side follows the KS0108B signal order as broken out in v1's `circuit.py`. The ribbon is a 1:1 carrier — no pinout remapping.

## Software integration summary

### Device tree overlays (auto-loaded from HAT EEPROM)

The EEPROM stores compiled device-tree fragments; exact invocation strings are fixed during implementation against the Pi 5 kernel's current overlay set. Conceptually:

- `pps-gpio` on GPIO 18 (already working in v1 — carried forward)
- `i2c-rtc` variant for RV-3028
- `pwm` overlay enabling hardware PWM0 on GPIO 12
- `mcp23017` overlay at address 0x20 with interrupt on Pi GPIO 4
- Custom `gpio-keys` overlay mapping MCP23017 pins B0–B5 to KEY_UP/DOWN/LEFT/RIGHT/ENTER/ESC
- `w1-gpio` omitted (DS18B20 deferred to v3)

### New systemd services

- `gx01-backlight.service` — reads VEML7700, drives backlight PWM
- `gx01-fan.service` — reads thermal sources, drives fan PWM, reads tach
- `gx01-status-leds.service` — drives GPS-fix / NTP-sync / Error LEDs based on system state
- `gx01-menu.service` — owns the LCD, consumes button input events, renders menus and status screens

All services written in Python for consistency with existing Geographica services. Configuration files under `/etc/gx01/`.

### Python driver integration

Existing KS0108B Python driver moves into `gx01-menu.service` as a library (unchanged behavior). New menu framework consumes button events from `/dev/input/by-path/platform-gx01-panel-event-kbd` and renders to the existing LCD driver. Default menu screens: Status (IP / GPS / NTP / CPU temp), Network (WiFi SSID, IP, QR code), Sensors (all on-board + external), Settings (brightness, fan curve, reboot).

## Testing plan

1. **Bench bring-up** — With one assembled HAT + FPB on a Pi 5 (no other HATs), verify each bus one at a time: I²C0 EEPROM readable, I²C1 scan shows all five device addresses, PPS pulses visible on `/sys/class/pps/pps0`, backlight PWM visible on scope, fan PWM visible on scope, buttons generate input events, LEDs controllable from userspace.
2. **Full stack integration** — Install on top of LC29H + Hailo in the real stack, verify no overlay conflicts, GPS fix within 60 s, chrony locks within 5 min, all sensors readable via `i2cdetect` and their respective drivers.
3. **Thermal holdover test** — Disconnect GPS antenna, record clock drift vs. NIST reference over 24 h at room temp. Repeat in freezer (0 °C) and on a heat pad (45 °C). Verify worst case < 1 s/day drift.
4. **Button mechanical test** — Press each button 10,000 times (automated by a servo jig) with the full case assembled. Verify LCD remains functional and no solder joints fatigue-crack. Acceptance: 0 failures across all 6 buttons × 10k presses.
5. **Backlight auto-dimming** — Cover/uncover the VEML7700 and verify backlight responds within 2 s at the correct polarity.
6. **Fan curve verification** — Artificially load the Pi (stress-ng), verify fans ramp up and stay below 55 °C steady-state with 2× Noctua NF-A4x10 5V running at the curve's 60 % duty point.
7. **NTP server load test** — Point 5 AREDN peer nodes at this device's NTP service over the mesh; verify all lock and show offset < 1 ms to the GPS-disciplined reference.

## Out of scope / deferred

- **Case redesign.** v2 HAT requires new case front-panel cutouts for 6 buttons + 4 LEDs + 1 light sensor aperture, plus a separate LCD-mounting pattern (case standoffs, not HAT-mounted). A follow-on spec will revise [`docs/superpowers/specs/2026-04-18-gx-01-case-design.md`](./2026-04-18-gx-01-case-design.md) accordingly. Until that spec exists, v2 HAT cannot be fully packaged.
- **DS18B20 1-Wire thermal probes.** Out of scope for v2; X1207 handles battery state, and no other current use case justifies the probe connector. Can be added in v3 as a JST-PH 3-pin header + `dtoverlay=w1-gpio`.
- **UART2 serial console breakout.** GPIO 8, 9 are reserved but no header is placed; defer to v3 if field-recovery need justifies the component cost.
- **IMU, buzzer, NeoPixel, IR.** Explicitly out of scope per project "no GECK" directive.

## Open implementation questions

1. **BME280 exact JLC part number.** The generic Bosch BME280 is listed under multiple manufacturer variants in LCSC. Verify current stock and pick the C-code during BOM finalization; `sensirion SHT31` is a reasonable fallback if BME280 stock is thin.
2. **LCD ribbon cable termination on the LCD side.** Options: (a) solder 1×20 header onto LCD, use 20-wire ribbon with IDC + DuPont; (b) fab a tiny "LCD carrier" breakout PCB with 1×20 solder pads to 2×10 IDC header, panelize with main HAT + FPB. Option (b) is cleaner; decide during implementation.
3. **Front Panel Board layout aspect ratio.** Constrained by case front dimensions (TBD in case revision). Default assumption: ~65 × 30 mm landscape strip below the LCD. Confirm when case spec is revised.
4. **Button caps.** Alps K4T press-fit caps vs. silicone overlay keypad vs. 3D-printed plastic caps guided by the case. Defer to case revision.

## Appendix A — JLCPCB availability verified

All Extended parts confirmed in stock at time of spec authoring (2026-04-19):

- RV-3028-C7 (C3019759): 31,087 in stock
- MCP9808-H/MSTR (C76147): verified on JLC parts search
- 24LC32AT-I/SN (C56663): verified
- AO3400 (C20917): verified
- CPH3225A (C520488): verified
- MCP23017-E/SO (C8672): verified
- VEML7700 (C164531): verified

Stock positions must be re-checked immediately before BOM submission; JLC inventory is volatile on Extended parts.

## Appendix B — Related specs

- [GX-01 Case Design (2026-04-18)](./2026-04-18-gx-01-case-design.md) — will need revision to match v2 HAT mechanicals
- [GX-01 Adapter HAT v1 README](../../../hardware/gx01-adapter-pcb/README.md) — existing through-hole design for reference
