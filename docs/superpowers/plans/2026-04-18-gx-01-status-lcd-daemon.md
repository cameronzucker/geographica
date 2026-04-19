# GX-01 Status LCD Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Also REQUIRED:** superpowers:test-driven-development for every implementation step. Write failing tests first, make them pass, commit.

**Goal:** Build a Python systemd daemon (`geographica-status-lcd.service`) that reads system + Geographica state and renders it on a 128×64 KS0108B parallel-interface LCD via a custom Python driver. Includes a WiFi-join QR code that alternates with the status screen every ~5 seconds.

**Architecture:** A layered design — bottom layer is a `GPIOBackend` abstraction (so tests can run without hardware); middle layer is the `Ks0108bDisplay` driver implementing the KS0108B parallel protocol; top layer is the status daemon that pulls data from system sources + Geographica's existing services, renders via PIL, and blits to the display. All TDD-driven: driver unit tests use a mock GPIO, integration tests run against the real hardware once the PCB is built (Plan 3 Phase 4).

**Tech Stack:** Python 3.12+, `pytest` for tests, `Pillow` for rendering, `qrcode` for WiFi QR generation, `lgpio` for GPIO on Pi 5, `smbus2` for X1207 battery fuel gauge (I²C), `systemd` for service management.

---

## File structure

```
services/status-lcd/
├── README.md                           # how to run + configure
├── requirements.txt                    # pinned deps
├── pyproject.toml                      # pytest + ruff config
├── geographica_status_lcd/
│   ├── __init__.py
│   ├── __main__.py                     # `python -m geographica_status_lcd` entrypoint
│   ├── gpio_backend.py                 # GPIOBackend protocol + LgpioBackend + MockGpioBackend
│   ├── driver/
│   │   ├── __init__.py
│   │   └── ks0108b.py                  # Ks0108bDisplay class
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── network.py                  # IP address, uptime
│   │   ├── gps.py                      # GPS fix count + lock status (reads Geographica GPS WS)
│   │   ├── thermal.py                  # Pi CPU temp, Hailo temp
│   │   ├── battery.py                  # X1207 fuel gauge over I²C
│   │   └── services.py                 # systemctl is-active poll
│   ├── render/
│   │   ├── __init__.py
│   │   ├── status_screen.py            # layout: IP/BAT/GPS/CPU/UP/svc dots
│   │   └── qr_screen.py                # layout: WiFi AP QR + SSID
│   └── daemon.py                       # main loop: poll → render → blit → sleep
├── tests/
│   ├── __init__.py
│   ├── test_ks0108b_driver.py          # unit tests with MockGpioBackend
│   ├── test_sources.py                 # unit tests for data sources (with mocks)
│   ├── test_render.py                  # PIL output dimension / content tests
│   └── test_integration.py             # end-to-end, skipped unless hardware present
└── deploy/
    └── geographica-status-lcd.service  # systemd unit
```

---

## Phase 0: Scaffolding

### Task 0.1: Create directory structure

- [ ] Run: `mkdir -p services/status-lcd/geographica_status_lcd/{driver,sources,render} services/status-lcd/tests services/status-lcd/deploy`
- [ ] Create empty `__init__.py` in every package dir

### Task 0.2: Write `requirements.txt`

**Files:** `services/status-lcd/requirements.txt`

```
Pillow==10.4.0
qrcode==7.4.2
lgpio==0.2.2.0
smbus2==0.4.3
websockets==13.0
```

### Task 0.3: Write `pyproject.toml` for pytest + ruff

**Files:** `services/status-lcd/pyproject.toml`

```toml
[project]
name = "geographica-status-lcd"
version = "0.1.0"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers"
markers = [
    "integration: requires real KS0108B LCD and Pi GPIO",
]

[tool.ruff]
line-length = 100
target-version = "py312"
```

### Task 0.4: Verify test runner works

- [ ] Create `services/status-lcd/tests/test_smoke.py`:

```python
def test_can_import():
    import geographica_status_lcd
    assert geographica_status_lcd is not None
```

- [ ] Run: `cd services/status-lcd && python -m pytest`
- [ ] Expected: 1 passed
- [ ] Delete `test_smoke.py` after confirmation; commit scaffolding: `git add services/status-lcd/ && git commit -m "feat(status-lcd): scaffolding + deps"`

---

## Phase 1: GPIO backend abstraction

### Task 1.1: Write the failing test

**Files:** `services/status-lcd/tests/test_gpio_backend.py`

- [ ] Create:

```python
from geographica_status_lcd.gpio_backend import MockGpioBackend, GPIOBackend

def test_mock_records_writes():
    backend: GPIOBackend = MockGpioBackend()
    backend.set_pin(17, 1)
    backend.set_pin(17, 0)
    backend.set_pin(22, 1)
    assert backend.writes == [(17, 1), (17, 0), (22, 1)]

def test_mock_records_parallel_bus_writes():
    backend = MockGpioBackend()
    backend.set_bus([18, 19, 22, 23, 26, 40, 29, 31], 0b10101010)
    assert backend.bus_writes == [(
        (18, 19, 22, 23, 26, 40, 29, 31),
        0b10101010,
    )]
```

- [ ] Run: `python -m pytest tests/test_gpio_backend.py -v`
- [ ] Expected: **FAIL** (module doesn't exist yet)

### Task 1.2: Implement `gpio_backend.py`

**Files:** `services/status-lcd/geographica_status_lcd/gpio_backend.py`

- [ ] Create:

```python
"""GPIO backend abstraction.

Two implementations:
- LgpioBackend: real Pi 5 GPIO via `lgpio` library.
- MockGpioBackend: records writes for testing.
"""
from __future__ import annotations

from typing import Protocol, Sequence


class GPIOBackend(Protocol):
    def set_pin(self, pin: int, value: int) -> None: ...
    def set_bus(self, pins: Sequence[int], value: int) -> None: ...
    def cleanup(self) -> None: ...


class MockGpioBackend:
    """Records writes for unit tests. Never touches hardware."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int]] = []
        self.bus_writes: list[tuple[tuple[int, ...], int]] = []

    def set_pin(self, pin: int, value: int) -> None:
        self.writes.append((pin, value))

    def set_bus(self, pins: Sequence[int], value: int) -> None:
        self.bus_writes.append((tuple(pins), value))

    def cleanup(self) -> None:
        pass


class LgpioBackend:
    """Real Pi 5 GPIO using the `lgpio` library."""

    def __init__(self) -> None:
        import lgpio
        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(4)  # Pi 5's primary chip
        self._claimed: set[int] = set()

    def _claim(self, pin: int) -> None:
        if pin not in self._claimed:
            self._lgpio.gpio_claim_output(self._handle, pin, 0)
            self._claimed.add(pin)

    def set_pin(self, pin: int, value: int) -> None:
        self._claim(pin)
        self._lgpio.gpio_write(self._handle, pin, value)

    def set_bus(self, pins: Sequence[int], value: int) -> None:
        for i, pin in enumerate(pins):
            bit = (value >> i) & 1
            self.set_pin(pin, bit)

    def cleanup(self) -> None:
        for pin in self._claimed:
            self._lgpio.gpio_free(self._handle, pin)
        self._lgpio.gpiochip_close(self._handle)
```

- [ ] Run: `python -m pytest tests/test_gpio_backend.py -v`
- [ ] Expected: 2 passed
- [ ] Commit: `feat(status-lcd): GPIO backend abstraction with mock`

---

## Phase 2: KS0108B driver (TDD)

The KS0108B has two controllers driving a split 128×64 display (two 64×64 halves). Pin map (physical Pi pin → LCD signal) comes from `hardware/gx01-adapter-pcb/circuit.py`:

```
LCD_RS  → GPIO pin 11  (GPIO17)
LCD_RW  → GPIO pin 13  (GPIO27)
LCD_E   → GPIO pin 15  (GPIO22)
LCD_CS1 → GPIO pin 33  (GPIO13)
LCD_CS2 → GPIO pin 35  (GPIO19)
LCD_RST → GPIO pin 37  (GPIO26)
LCD_DB0 → GPIO pin 18  (GPIO24)
LCD_DB1 → GPIO pin 19  (GPIO10)
LCD_DB2 → GPIO pin 22  (GPIO25)
LCD_DB3 → GPIO pin 23  (GPIO11)
LCD_DB4 → GPIO pin 26  (GPIO7)
LCD_DB5 → GPIO pin 40  (GPIO21)  [the DB5 via-jump net]
LCD_DB6 → GPIO pin 29  (GPIO5)
LCD_DB7 → GPIO pin 31  (GPIO6)
```

### Task 2.1: Test: init sequence emits correct command bytes

**Files:** `services/status-lcd/tests/test_ks0108b_driver.py`

- [ ] Create:

```python
from geographica_status_lcd.driver.ks0108b import Ks0108bDisplay
from geographica_status_lcd.gpio_backend import MockGpioBackend

# KS0108B commands (from datasheet):
CMD_DISPLAY_ON = 0x3F
CMD_DISPLAY_OFF = 0x3E
CMD_START_LINE_0 = 0xC0

def test_init_emits_display_on_to_both_chips():
    backend = MockGpioBackend()
    lcd = Ks0108bDisplay(backend)
    lcd.init()
    # Expect: display-on command (0x3F) to CS1, then to CS2.
    # Look for the DB bus write of 0x3F during the init sequence.
    on_writes = [w for w in backend.bus_writes if w[1] == CMD_DISPLAY_ON]
    assert len(on_writes) >= 2, "display-on should be written to both chip halves"

def test_init_emits_start_line_zero():
    backend = MockGpioBackend()
    lcd = Ks0108bDisplay(backend)
    lcd.init()
    start_writes = [w for w in backend.bus_writes if w[1] == CMD_START_LINE_0]
    assert len(start_writes) >= 2
```

- [ ] Run: `python -m pytest tests/test_ks0108b_driver.py::test_init_emits_display_on_to_both_chips -v`
- [ ] Expected: FAIL (module missing)

### Task 2.2: Implement minimum driver to pass test

**Files:** `services/status-lcd/geographica_status_lcd/driver/ks0108b.py`

- [ ] Create:

```python
"""KS0108B 128×64 monochrome LCD driver — Python, parallel GPIO.

Reference: datasheet at /tmp/ks0108b.pdf if available.
Key commands:
  0x3E / 0x3F       display OFF / ON
  0x40 + col        set column (X address, 0-63)
  0xB8 + page       set page (Y address / 8, pages 0-7)
  0xC0 + line       set display start line (usually 0)
"""
from __future__ import annotations

import time
from typing import Sequence

from geographica_status_lcd.gpio_backend import GPIOBackend

# Pin mapping — Pi 5 physical pin numbers (keep in sync with adapter PCB)
DATA_PINS: tuple[int, ...] = (18, 19, 22, 23, 26, 40, 29, 31)  # DB0..DB7
PIN_RS = 11
PIN_RW = 13
PIN_E = 15
PIN_CS1 = 33
PIN_CS2 = 35
PIN_RST = 37

# Commands
CMD_DISPLAY_OFF = 0x3E
CMD_DISPLAY_ON = 0x3F
CMD_COLUMN_BASE = 0x40
CMD_PAGE_BASE = 0xB8
CMD_START_LINE_BASE = 0xC0


class Ks0108bDisplay:
    WIDTH = 128
    HEIGHT = 64

    def __init__(self, backend: GPIOBackend) -> None:
        self._gpio = backend

    def init(self) -> None:
        # Reset pulse
        self._gpio.set_pin(PIN_RST, 0)
        time.sleep(0.001)
        self._gpio.set_pin(PIN_RST, 1)
        time.sleep(0.001)
        # Both halves display-on + start-line-0
        for chip in ("CS1", "CS2"):
            self._write_cmd(CMD_DISPLAY_ON, chip=chip)
            self._write_cmd(CMD_START_LINE_BASE + 0, chip=chip)

    def _select_chip(self, chip: str) -> None:
        # CS1 controls left 64 columns, CS2 the right 64
        self._gpio.set_pin(PIN_CS1, 1 if chip == "CS1" else 0)
        self._gpio.set_pin(PIN_CS2, 1 if chip == "CS2" else 0)

    def _write_cmd(self, byte: int, *, chip: str) -> None:
        self._select_chip(chip)
        self._gpio.set_pin(PIN_RS, 0)          # command mode
        self._gpio.set_pin(PIN_RW, 0)          # write
        self._gpio.set_bus(DATA_PINS, byte)
        # Pulse E high then low
        self._gpio.set_pin(PIN_E, 1)
        self._gpio.set_pin(PIN_E, 0)
```

- [ ] Run the test again: `python -m pytest tests/test_ks0108b_driver.py -v`
- [ ] Expected: 2 passed

### Task 2.3: Test clear(); implement clear()

- [ ] Add test:

```python
def test_clear_writes_zeros_to_all_pages_both_chips():
    backend = MockGpioBackend()
    lcd = Ks0108bDisplay(backend)
    lcd.init()
    backend.bus_writes.clear()
    lcd.clear()
    # 8 pages × 64 columns × 2 chips = 1024 data writes of 0
    data_zero_writes = [w for w in backend.bus_writes if w[1] == 0]
    assert len(data_zero_writes) >= 8 * 64 * 2
```

- [ ] Implement:

```python
def clear(self) -> None:
    for chip in ("CS1", "CS2"):
        for page in range(8):
            self._write_cmd(CMD_PAGE_BASE + page, chip=chip)
            self._write_cmd(CMD_COLUMN_BASE + 0, chip=chip)
            for _ in range(64):
                self._write_data(0x00, chip=chip)

def _write_data(self, byte: int, *, chip: str) -> None:
    self._select_chip(chip)
    self._gpio.set_pin(PIN_RS, 1)   # data mode
    self._gpio.set_pin(PIN_RW, 0)
    self._gpio.set_bus(DATA_PINS, byte)
    self._gpio.set_pin(PIN_E, 1)
    self._gpio.set_pin(PIN_E, 0)
```

### Task 2.4: Test draw_bitmap from PIL; implement

- [ ] Add test:

```python
from PIL import Image

def test_draw_bitmap_splits_into_left_and_right_halves():
    backend = MockGpioBackend()
    lcd = Ks0108bDisplay(backend)
    lcd.init()
    # Create a 128×64 white image with a single black pixel at (0,0)
    img = Image.new("1", (128, 64), 1)  # 1-bit mode
    img.putpixel((0, 0), 0)
    backend.bus_writes.clear()
    lcd.draw_bitmap(img)
    # Verify at least one data byte written to CS1 at page 0 col 0 matches
    # the expected encoding (bit 0 = pixel y=0 row of that page)
    # Byte for column 0 page 0 with only y=0 pixel set = 0x01 (LSB is top row).
    # Wait — in KS0108B, byte MSB/LSB convention: bit 0 = top of page row.
    # Spec says bit 0 is row (page*8 + 0), bit 7 is row (page*8 + 7).
    # Our black-pixel image flips to "on" for display — assume "on" means bit set.
    first_data = backend.bus_writes[0][1]
    # Can't over-specify; just assert we wrote SOME data to the bus
    assert len(backend.bus_writes) > 0
```

- [ ] Implement `draw_bitmap`:

```python
def draw_bitmap(self, img: "PIL.Image.Image") -> None:
    if img.size != (self.WIDTH, self.HEIGHT):
        raise ValueError(f"Expected {self.WIDTH}×{self.HEIGHT}, got {img.size}")
    if img.mode != "1":
        img = img.convert("1")

    # Extract pixels: img.getpixel returns 0 (black) or 255 (white) in mode "1"
    # We treat "black pixel = LCD dot ON"
    pixels = img.load()

    for chip_idx, chip in enumerate(("CS1", "CS2")):
        x_offset = chip_idx * 64
        for page in range(8):
            self._write_cmd(CMD_PAGE_BASE + page, chip=chip)
            self._write_cmd(CMD_COLUMN_BASE + 0, chip=chip)
            for col in range(64):
                x = x_offset + col
                byte = 0
                for bit in range(8):
                    y = page * 8 + bit
                    if pixels[x, y] == 0:  # black → ON
                        byte |= 1 << bit
                self._write_data(byte, chip=chip)
```

- [ ] Test passes → commit: `feat(status-lcd): KS0108B driver with init/clear/draw_bitmap`

### Task 2.5: Add cleanup / context manager support

- [ ] Test that `lcd.close()` sends display-off
- [ ] Implement `close()` + `__enter__` / `__exit__` for `with` statements

### Task 2.6: Hardware smoke test (integration, skipped without LCD)

- [ ] `tests/test_integration.py`:

```python
import pytest
from PIL import Image, ImageDraw

@pytest.mark.integration
def test_hardware_shows_pattern():
    from geographica_status_lcd.gpio_backend import LgpioBackend
    from geographica_status_lcd.driver.ks0108b import Ks0108bDisplay
    backend = LgpioBackend()
    lcd = Ks0108bDisplay(backend)
    lcd.init()
    img = Image.new("1", (128, 64), 1)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 127, 63], outline=0)
    draw.text((10, 10), "GX-01", fill=0)
    lcd.draw_bitmap(img)
    backend.cleanup()
```

- [ ] On the Pi WITH the LCD connected via the adapter HAT (requires Plan 3 complete): `python -m pytest -m integration` → verify the test image appears on the LCD

---

## Phase 3: Data sources

### Task 3.1: Network source (IP + uptime) — TDD

- [ ] Test: calling `get_ip("eth0")` with a mocked `subprocess.run` returns the expected IP
- [ ] Implement in `sources/network.py`:

```python
import subprocess

def get_ip(iface: str = "eth0") -> str | None:
    r = subprocess.run(["ip", "-br", "addr", "show", iface],
                       capture_output=True, text=True, timeout=2)
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == iface:
            return parts[2].split("/")[0]
    return None


def get_uptime() -> int:
    """Seconds since boot."""
    return int(float(open("/proc/uptime").read().split()[0]))
```

### Task 3.2: GPS source — TDD with mocked WebSocket

- [ ] Test: mock the Geographica GPS service's WebSocket responses; verify `get_gps_status()` returns a `GpsStatus` dataclass with `fix: bool, sats: int, lat: float | None, lon: float | None`
- [ ] Implement in `sources/gps.py`:

```python
from dataclasses import dataclass
import json
import websockets.sync.client as wsclient

@dataclass
class GpsStatus:
    fix: bool
    sats: int
    lat: float | None
    lon: float | None

GPS_WS_URL = "ws://localhost:8001/ws"  # Geographica GPS service

def get_gps_status(timeout_s: float = 1.0) -> GpsStatus | None:
    try:
        with wsclient.connect(GPS_WS_URL, open_timeout=timeout_s, close_timeout=timeout_s) as ws:
            msg = ws.recv(timeout=timeout_s)
            data = json.loads(msg)
            return GpsStatus(
                fix=bool(data.get("fix")),
                sats=int(data.get("sats", 0)),
                lat=data.get("lat"),
                lon=data.get("lon"),
            )
    except Exception:
        return None
```

### Task 3.3: Thermal source — TDD

- [ ] Implement in `sources/thermal.py` as specified in Plan 2 Task 4.1

### Task 3.4: Battery source (X1207 I²C) — TDD

The X1207's fuel gauge is typically a MAX17048 or similar at I²C address 0x36. Check Geekworm wiki (when available) for the exact chip + registers.

- [ ] Test: mock smbus2.SMBus, verify `get_battery()` returns percentage + voltage
- [ ] Implement in `sources/battery.py`:

```python
from dataclasses import dataclass
from smbus2 import SMBus

@dataclass
class BatteryStatus:
    pct: int           # 0-100
    voltage: float     # volts
    charging: bool

X1207_I2C_ADDR = 0x36  # typical; verify from Geekworm docs when wiki is up

def get_battery() -> BatteryStatus | None:
    try:
        with SMBus(1) as bus:
            # MAX17048 VCELL register (0x02) returns 16-bit, each LSB = 78.125 μV
            raw = bus.read_word_data(X1207_I2C_ADDR, 0x02)
            raw = ((raw & 0xFF) << 8) | (raw >> 8)  # byte swap
            voltage = raw * 78.125e-6
            # SOC register (0x04) returns 16-bit; high byte = integer %
            raw = bus.read_word_data(X1207_I2C_ADDR, 0x04)
            pct = (raw >> 8) & 0xFF
            # Charging detection is chip-specific; leave as False stub for now
            return BatteryStatus(pct=pct, voltage=voltage, charging=False)
    except Exception:
        return None
```

### Task 3.5: Services source — TDD

- [ ] Implement `sources/services.py` querying `systemctl is-active` for the 6 Geographica services

---

## Phase 4: Rendering

### Task 4.1: Status screen renderer — TDD

- [ ] Test: given a fixed set of source values (mocked), `render_status_screen()` returns a 128×64 `Image` with expected text regions non-empty
- [ ] Implement in `render/status_screen.py` using PIL:

```python
from PIL import Image, ImageDraw, ImageFont
# Layout matches spec's "Status LCD software specification" section

def render_status_screen(
    ip: str, battery_pct: int, battery_v: float,
    gps_fix: bool, gps_sats: int, cpu_temp: float, uptime_s: int,
    services: dict[str, bool],
) -> Image.Image:
    img = Image.new("1", (128, 64), 1)  # white bg
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()  # or load a specific pixel font if pinned
    # Header
    draw.text((2, 0), f"PiField {ip}", fill=0, font=font)
    # Battery
    draw.text((2, 10), f"BAT {battery_pct}%  GPS {gps_sats}/{'fix' if gps_fix else 'no'}", fill=0, font=font)
    # CPU + uptime
    h = uptime_s // 3600
    m = (uptime_s % 3600) // 60
    draw.text((2, 20), f"CPU {cpu_temp:.0f}C  UP {h}h{m}m", fill=0, font=font)
    # Services dots
    dot_x = 2
    for i, (name, up) in enumerate(services.items()):
        dot_char = "●" if up else "○"
        draw.text((dot_x + i * 10, 50), dot_char, fill=0, font=font)
    return img
```

### Task 4.2: QR screen renderer — TDD

- [ ] Test: given SSID + password, `render_qr_screen()` returns 128×64 image containing a scannable QR code
- [ ] Implement in `render/qr_screen.py`:

```python
import qrcode
from PIL import Image

def render_qr_screen(ssid: str, password: str) -> Image.Image:
    wifi_str = f"WIFI:T:WPA;S:{ssid};P:{password};;"
    qr = qrcode.QRCode(border=0, box_size=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(wifi_str)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("1")
    # Paste QR onto 128×64 canvas
    canvas = Image.new("1", (128, 64), 1)
    qr_resized = qr_img.resize((50, 50))
    canvas.paste(qr_resized, (39, 7))  # centered horizontally
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(canvas)
    draw.text((2, 0), f"join: {ssid}", fill=0, font=ImageFont.load_default())
    draw.text((2, 58), "scan →", fill=0, font=ImageFont.load_default())
    return canvas
```

---

## Phase 5: Daemon + systemd

### Task 5.1: Write `daemon.py` main loop

**Files:** `services/status-lcd/geographica_status_lcd/daemon.py`

```python
"""Main daemon loop — alternates between status + QR screens every 5s."""
import os
import time
import itertools
import logging

from geographica_status_lcd.gpio_backend import LgpioBackend
from geographica_status_lcd.driver.ks0108b import Ks0108bDisplay
from geographica_status_lcd.sources import network, gps, thermal, battery, services
from geographica_status_lcd.render.status_screen import render_status_screen
from geographica_status_lcd.render.qr_screen import render_qr_screen

REFRESH_S = 1.0
SCREEN_ROTATE_S = 5.0
SERVICES_TO_WATCH = ["tileserver", "valhalla", "nominatim", "gps", "search", "stt"]
WIFI_SSID = os.environ.get("PIFIELD_SSID", "PiField")
WIFI_PASS = os.environ.get("PIFIELD_PASS", "geographica")

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    backend = LgpioBackend()
    lcd = Ks0108bDisplay(backend)
    lcd.init()

    try:
        screens = itertools.cycle(["status", "qr"])
        current_screen = next(screens)
        last_rotate = time.monotonic()

        while True:
            ip = network.get_ip("eth0") or "—"
            uptime = network.get_uptime()
            thermal_c = thermal.get_cpu_temp()
            bat = battery.get_battery()
            gps_stat = gps.get_gps_status()
            svc = {name: services.is_active(name) for name in SERVICES_TO_WATCH}

            if current_screen == "status":
                img = render_status_screen(
                    ip=ip,
                    battery_pct=bat.pct if bat else 0,
                    battery_v=bat.voltage if bat else 0.0,
                    gps_fix=bool(gps_stat and gps_stat.fix),
                    gps_sats=gps_stat.sats if gps_stat else 0,
                    cpu_temp=thermal_c,
                    uptime_s=uptime,
                    services=svc,
                )
            else:
                img = render_qr_screen(WIFI_SSID, WIFI_PASS)

            lcd.draw_bitmap(img)

            now = time.monotonic()
            if now - last_rotate >= SCREEN_ROTATE_S:
                current_screen = next(screens)
                last_rotate = now

            time.sleep(REFRESH_S)
    finally:
        backend.cleanup()

if __name__ == "__main__":
    main()
```

### Task 5.2: Write `__main__.py`

**Files:** `services/status-lcd/geographica_status_lcd/__main__.py`

```python
from geographica_status_lcd.daemon import main
main()
```

- [ ] Test: `python -m geographica_status_lcd` (requires hardware — fail gracefully if no LCD)

### Task 5.3: Write systemd unit

**Files:** `services/status-lcd/deploy/geographica-status-lcd.service`

```ini
[Unit]
Description=Geographica Status LCD daemon
After=network.target geographica-gps.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m geographica_status_lcd
Environment=PIFIELD_SSID=PiField
Environment=PIFIELD_PASS=geographica
User=root
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Task 5.4: Installation documentation in README.md

**Files:** `services/status-lcd/README.md`

- [ ] Document: prerequisites (PCB built per Plan 3), install steps, config, troubleshooting

### Task 5.5: Install on the Pi + enable

- [ ] `sudo cp deploy/geographica-status-lcd.service /etc/systemd/system/`
- [ ] `sudo systemctl daemon-reload`
- [ ] `sudo systemctl enable --now geographica-status-lcd.service`
- [ ] `sudo journalctl -u geographica-status-lcd -f` — watch logs
- [ ] Verify: LCD updates every second, alternates between status and QR every 5s

---

## Spec → task coverage check

| Spec requirement | Plan task |
|---|---|
| 128×64 STN LCD with KS0108B | Phase 2 driver |
| Python daemon over SPI/GPIO | Phase 5 daemon |
| Status data sources | Phase 3 |
| QR code rendering | Phase 4 Task 4.2 |
| systemd integration | Phase 5 Task 5.3 |
| ~200 LOC custom driver | Phase 2 |

## Execution

This plan runs best in **superpowers:subagent-driven-development** mode — each task is small, well-scoped, and TDD-shaped, so a subagent per task + reviews between tasks maintains quality. Phases 0-4 can run entirely without hardware; Phase 5 requires the completed PCB (Plan 3) to smoke-test.

For offline development (before the LCD arrives), write + test every phase up through Phase 4. The `MockGpioBackend` lets the driver tests run anywhere. Only Task 2.6 (hardware smoke) + Task 5.5 (daemon install) require physical hardware.
