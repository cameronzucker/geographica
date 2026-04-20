---
purpose: Background research for Spec B (field-mode / Pi-as-AP) brainstorm session
date: 2026-04-20
status: research-only, no design decisions made
related: Spec A (nav keep-awake) being written in parallel
---

# Spec B research: Pi-as-Wi-Fi in the field

## 1. Pi 5 Wi-Fi capabilities for simultaneous AP + client mode

The Pi 5 uses the Cypress/Infineon **CYW43455** (marketed in some places as BCM4345C0; datasheet naming varies), driven by `brcmfmac` in the mainline kernel with firmware `cyw43455-firmware`. The note in the brief about `cyw43` is accurate for the Pico W's chipset naming; on the Pi 5 the driver is `brcmfmac`.

**Same-radio AP+STA: technically supported, fragile in practice.**
- The chip supports concurrent AP+STA on a *single* channel. You create a virtual `ap0` interface on top of `wlan0` and run hostapd against `ap0` while `wlan0` remains the STA ([RaspAP AP-STA docs](https://docs.raspap.com/features-experimental/ap-sta/), [Nathan Lewis writeup for Pi 5](https://nrlewis.dev/blog/rpi-hotspot/)).
- Both interfaces must share the same channel — if the upstream STA roams to a different channel the AP hops with it, which breaks any already-associated clients. On a dual-band chip you cannot mix 2.4 GHz STA with 5 GHz AP.
- On-chip RAM limits reliable client count to roughly 5 while in concurrent mode ([Pi Forums thread](https://forums.raspberrypi.com/viewtopic.php?t=291824)).
- **Active 2025 regression:** [raspberrypi/linux#7092](https://github.com/raspberrypi/linux/issues/7092) — BCM43455 firmware crashes on kernel 6.12 (Trixie) in concurrent STA+AP. The AP on `ap0` works until a client associates, then the firmware panics. No fix committed as of the last comment at the time of this search. Flag this as a hard risk for any simultaneous design targeting current Raspberry Pi OS.

**Preferred alternatives:**
1. **Ethernet WAN + onboard Wi-Fi AP only.** Cleanest. At "home" the Pi takes DHCP on eth0; in the field it runs onboard Wi-Fi as a pure AP with nothing upstream. No concurrent-radio bug surface.
2. **USB dongle for the second radio.** Best-in-class for AP mode is the **MediaTek MT7612U** — `mt76x2u` driver is in-kernel since 4.19, supports AP / AP+VLAN / monitor, good hostapd story ([morrownr/7612u](https://github.com/morrownr/7612u), [morrownr/USB-WiFi list](https://github.com/morrownr/USB-WiFi/blob/main/home/USB_WiFi_Adapters_that_are_supported_with_Linux_in-kernel_drivers.md)). The Pi Hut sells a branded adapter. Realtek **RTL8812BU** works but needs an out-of-tree DKMS driver and is widely reported as a headache on kernel upgrades — not recommended for a "just works" product.
3. **Onboard Wi-Fi only, toggled AP/STA modes** with a user-facing switch. Avoids the firmware bug; loses the "stay connected to home LAN while also serving clients" capability.

## 2. hostapd + dnsmasq patterns on current Raspberry Pi OS

**The stack shifted in Bookworm.** Raspberry Pi OS 12 "Bookworm" moved from `dhcpcd` + `wpa_supplicant` to **NetworkManager** as the default network stack ([Geerling, 2023](https://www.jeffgeerling.com/blog/2023/nmcli-wifi-on-raspberry-pi-os-12-bookworm/)). Trixie (13) keeps this. Most older tutorials using `/etc/dhcpcd.conf` static blocks + manual hostapd units are now actively harmful — they fight NetworkManager.

**Two blessed patterns today:**

1. **`nmcli` native hotspot** ([RaspberryTips Bookworm guide](https://raspberrytips.com/access-point-setup-raspberry-pi/), [Pi Forums #357998](https://forums.raspberrypi.com/viewtopic.php?t=357998)). One-liner:
   ```
   nmcli device wifi hotspot ifname wlan0 ssid Geographica password "changeme"
   ```
   NetworkManager spins up its own internal dnsmasq for DHCP and DNS on the AP interface. Pros: no separate config files, survives reboot if `connection.autoconnect` is set, plays nice with connection priorities. Cons: less control over DHCP ranges, static leases, and DNS hijacking for captive-portal UX.

2. **NetworkManager-aware hostapd + standalone dnsmasq.** Disable NM management on the AP iface (`nmcli device set wlan0 managed no` or per-interface `unmanaged-devices` in `NetworkManager.conf`), then run hostapd + dnsmasq as systemd units. This is what you want if you need a captive-portal DNS shortcut.

**Minimal hostapd.conf (WPA2-PSK, 2.4 GHz, onboard):**
```
interface=wlan0
driver=nl80211
ssid=Geographica
hw_mode=g
channel=6
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
wpa_passphrase=<picked-per-Pi>
country_code=US
ieee80211n=1
```

**Minimal dnsmasq.conf fragment for DHCP + captive-DNS shortcut:**
```
interface=wlan0
bind-interfaces
dhcp-range=192.168.4.50,192.168.4.150,12h
dhcp-option=3,192.168.4.1          # default gateway
dhcp-option=6,192.168.4.1          # DNS server (us)
address=/geographica.local/192.168.4.1
address=/geographica/192.168.4.1
# Optional: wildcard-answer to trigger captive portal detection
# address=/#/192.168.4.1
```
The last line is the "answer every lookup with our own IP" trick that triggers Android/iOS captive-portal popups.

**Recommendation for Geographica:** nmcli hotspot is simplest for a v1, but it doesn't give us the DNS-shortcut-for-captive-portal hook we probably want. Preferred path is **NetworkManager for STA, hostapd+dnsmasq for AP** with an explicit `unmanaged-devices` rule.

## 3. Current nginx/entrypoint.sh detailed map

All paths are absolute. Files read: `/home/administrator/Code/geographica/nginx/{entrypoint.sh,nginx.conf,tls-include.conf,tls-include-empty.conf}` and the `frontend` service block in `/home/administrator/Code/geographica/docker-compose.yml`.

### entrypoint.sh line-by-line

- **L2:** `TLS_MODE` env var, default `http`.
- **L4-L19:** Back-compat: maps deprecated values `self-signed` → `https`, `external` → `tailscale`, `existing` → `http` (with a warning each).
- **L23-L57 (`TLS_MODE=https`):** If `/etc/nginx/tls/server.crt` doesn't exist, auto-generates a self-signed cert/CA pair: creates `/etc/nginx/tls/ca/ca.key`, `/etc/nginx/tls/ca.crt`, `/etc/nginx/tls/server.key`, `/etc/nginx/tls/server.crt`. SAN hardcoded at L39 is **`DNS:$HOSTNAME,DNS:localhost,IP:$IP,IP:127.0.0.1`** where `$HOSTNAME = hostname -f` and `$IP = hostname -I | awk '{print $1}'` (first IP on the host, which on a Pi with both eth0 and wlan0 is non-deterministic). Then copies `/etc/nginx/tls-modes/tls-include.conf` to `/etc/nginx/tls-include.conf` (this is the include that `nginx.conf` line 3 pulls in).
- **L58-L69 (`TLS_MODE=tailscale`):** Expects a cert already at `/etc/nginx/tls/server.crt` (provisioned by `scripts/provision_tailscale_tls.sh`). No generation. Falls back to HTTP if missing.
- **L70-L72 (else / http):** Copies the empty include so nginx starts HTTP-only on port 80.
- **L74-L78:** `nginx -t` for sanity, then `exec nginx -g 'daemon off;'`.

### TLS_MODE values and on-disk output

| Mode | Writes | Listens |
|---|---|---|
| `http` | copies `tls-include-empty.conf` (blank) | 80 only |
| `https` | auto-generates self-signed CA + server pair under `/etc/nginx/tls/` if absent; copies real `tls-include.conf` | 80 + 443 |
| `tailscale` | requires pre-provisioned cert + key at `/etc/nginx/tls/server.{crt,key}`; copies real `tls-include.conf` | 80 + 443 |

### Where the actual TLS + server directives live

- `listen 443 ssl http2` and `ssl_certificate[_key]` — `/home/administrator/Code/geographica/nginx/tls-include.conf` lines 1-3.
- `listen 80` — `nginx.conf` line 2 (public server block).
- `server_name _` — `nginx.conf` line 4. **There is no SNI-based server selection today.** Everything matches the catch-all.
- Second server block at `listen 8094` — `nginx.conf` line 192, access-controlled to Docker gateway + loopback for the config panel.
- Compose publishes host ports `8093:80`, `${TLS_PORT:-443}:443`, and `127.0.0.1:8097:8094`.

### Lines to touch for the Spec B multi-listener refactor

Goal: both self-signed and Tailscale server blocks active simultaneously when both cert files exist, chosen per-request by SNI.

- **entrypoint.sh L23-72:** Today mutually exclusive — the `if/elif/else` picks one mode and overwrites the same `tls-include.conf`. Replace with "detect-and-emit-each": probe `/etc/nginx/tls/selfsigned/server.crt` AND `/etc/nginx/tls/tailscale/server.crt` independently, write one `tls-include.conf` fragment per present cert (or render two `server {}` stanzas into a `conf.d/` drop-in). Drop the copy-from-`tls-modes` indirection.
- **nginx.conf L1-4:** Split the monolithic `server { listen 80; include tls-include.conf; server_name _; }` into:
  - A plain HTTP `server { listen 80; server_name _; ... }`
  - An HTTPS server for self-signed: `server { listen 443 ssl; server_name geographica.local *.local 192.168.4.1 <other RFC1918 IPs>; ssl_certificate <selfsigned path>; ... }`
  - An HTTPS server for Tailscale: `server { listen 443 ssl; server_name *.ts.net; ssl_certificate <tailscale path>; ... }`
  - A `default_server` HTTPS block (probably the self-signed one) to handle unknown SNI.
  All of them need to factor-out the location blocks — today all 188 lines of the public server block (locations for `/tiles/`, `/nominatim/`, `/valhalla/`, `/search/`, `/stt/`, `/admin/status`, `/gps/`, `/atak/`, `/tls/ca.crt`) would have to be duplicated three times unless extracted into an `include /etc/nginx/locations-public.conf;`.
- **tls-include.conf / tls-include-empty.conf / tls-modes/ volume mounts** (`docker-compose.yml` L202-L203): the single-include model goes away. Either inline the TLS directives per-server-block, or create per-cert includes (`tls-selfsigned.conf`, `tls-tailscale.conf`).
- **Compose `TLS_CERT_DIR` (line ~205):** Needs to become a directory containing both `selfsigned/` and `tailscale/` subdirs, or two env vars (`TLS_SELFSIGNED_DIR`, `TLS_TAILSCALE_DIR`), both optionally bound.

### SAN list for a refactored self-signed cert

The hotspot design forces the cert to be trustworthy for a wider set of names than the current `hostname -f + first-IP-from-hostname -I`. Suggested:

- `DNS:geographica.local` (mDNS / primary offline name)
- `DNS:geographica` (bare NetBIOS-ish / dnsmasq short name)
- `DNS:localhost`
- `DNS:<pi-hostname>.local` (whatever the user set during imager / wizard)
- `IP:192.168.4.1` (canonical AP gateway IP — pick and fix this in Spec B)
- `IP:10.42.0.1` (NetworkManager-hotspot default AP IP; include if we use nmcli)
- `IP:127.0.0.1`
- `IP:<current eth0 DHCP address>` (best-effort; cert needs re-issue on lease change)
- `IP:<current wlan0 STA address>` (same caveat)

Because self-signed certs on IPs that change are a UX disaster, the design principle should be: **prefer DNS names over IPs, and make `geographica.local` the one the docs tell users to type.** Then the SAN list is stable.

## 4. Neighbor Pi-project precedents

**Balena WiFi-Connect** ([balena-os/wifi-connect](https://github.com/balena-os/wifi-connect)) — the reference implementation for "if no known SSID, become one". Written in Rust, hard-depends on NetworkManager. On boot, runs a connectivity check (GET a known URL); if it fails, the device becomes an AP with an embedded HTTP captive-portal that lists nearby SSIDs, accepts a passphrase, then tears the AP down and tries the credentials. If that fails, the AP comes back up. This is the closest analog to the "friendly field mode" UX the brief gestures at. Caveats: WiFi Connect's provisioning model is one-shot at boot; re-triggering later requires a service restart or an on-device gesture. There is no "user chose to be offline on purpose" mode.

**OctoPi** — does **not** ship with AP-mode-by-default. It expects the user to edit `octopi-wpa-supplicant.txt` on the SD card before first boot, or use the Pi Imager advanced options. If the STA credentials fail there is no AP fallback; the user physically pulls the SD card and edits the file again. Simple and cheap, but a terrible field UX.

**Pi-hole** — installs fine with no upstream DNS ([pi-hole#5937](https://github.com/pi-hole/pi-hole/issues/5937)); it just doesn't resolve anything until configured. Not a direct analog, but relevant precedent that "install-and-warn" is an accepted pattern.

**PirateBox / LibraryBox** (now abandoned but influential) — ran a pure AP with no upstream, served a static site + file-share over a captive portal. Used `iptables` DNAT to redirect all port-80 traffic to the local webserver. This is the "intentional walled garden" model — the opposite of WiFi-Connect's "provisioning" model.

**balenaOS** — industrial provisioning: default AP fallback via WiFi-Connect if no network.

**raspi-config** as of Bookworm has a Network menu that can enable a hotspot via `nmcli` but it's an on/off toggle, not smart. No auto-detect-and-fall-back.

**Two UX archetypes emerge:** (a) *provisioning* (WiFi-Connect): AP is a recovery mode, you're expected to leave it. (b) *intentional offline* (PirateBox): AP is the product, no upstream ever. Geographica's field-mode use case is closer to (b) but the "home" case wants (a)'s STA-by-default. A user-facing toggle (UI button, physical switch, or boot-time prompt) is probably the honest answer.

## 5. Gotchas and constraints

**mDNS over a hotspot interface.** `avahi-daemon` binds to all interfaces by default, which works fine. But a hotspot with *no upstream* means the Pi has no route to resolve external `.local` names, only its own. Android's `.local` resolution arrived only in recent versions ([Esper blog](https://www.esper.io/blog/android-dessert-bites-26-mdns-local-47912385)) — older Android phones connecting to the hotspot still won't resolve `geographica.local`. iOS/macOS have had this forever. Mitigation: have dnsmasq statically answer `geographica.local` and `geographica` via the `address=/...` trick and hand the Pi's IP out as DHCP option 6 (DNS), so mDNS is a convenience, not a hard dependency.

**Captive-portal detection.** Android GETs `http://connectivitycheck.gstatic.com/generate_204` (and a few others); iOS uses `captive.apple.com` and related domains. If our dnsmasq wildcards all lookups back to ourselves **and** our nginx returns a non-204 for those probe URLs, both OSes pop a "Sign in to network" browser pointed at our site. This can be a feature (free deep-link to the Geographica UI) or a trap (users dismissing it never see the app at all). Two sensible options: (a) honor the probes by serving a real 204 at those specific URLs so the device thinks it has internet — good for STT-over-Wi-Fi style use where the phone stays on our network happily; (b) fully hijack them and let the captive-portal browser open our app. Can't have both. The Wireless Broadband Alliance publishes the full probe URL list at [captivebehavior.wballiance.com](https://captivebehavior.wballiance.com/).

**Power and thermals.** Pi 5 idle ~4 W, peaks ~12 W ([bret.dk](https://bret.dk/how-to-power-the-raspberry-pi-5-a-complete-guide/)). hostapd with a few associated clients adds on the order of 0.5-1 W sustained — not a thermal issue by itself, but combined with NOAA imagery processing + STT load it can push a fanless case into throttling. The X1207 PoE+UPS HAT should be fine on PoE+ (25 W budget), but running on battery alone you get meaningfully shorter runtime vs. idle. **TBD:** actual amp draw with hostapd active — no authoritative measurement in the search results, should be benchmarked.

**"Am I at home or in the field?" detection.** Candidate heuristics, roughly in order of robustness: (1) NetworkManager connection state — `nmcli -t -f STATE general` = `connected` and `nmcli -t -f DEVICE,STATE device | grep eth0:connected` means wired. (2) DHCP lease presence on `eth0` or a known-SSID lease on `wlan0`. (3) Ping test to a well-known IP (e.g., `1.1.1.1`) with 3s timeout. (4) Presence of specific SSIDs in the scan list. Any approach picks the right answer 99% of the time; all of them fail somewhere (home router is down but still advertising DHCP, cellular hotspot in the truck cab, etc.). A **manual override always wins** in the UI.

**Security.** Pi-as-open-AP is an attack surface. Hard constraints: WPA2-PSK at minimum (WPA3-SAE if the MT76 driver supports it reliably on the Pi). Per-device PSK derived from the Pi's serial or a wizard-provided passphrase printed to the setup screen. *Never* ship a hardcoded "geographica" passphrase — that's a supply-chain backdoor. SSID should be per-device too (`geographica-a1b2`) so co-located Pis don't collide and so a stolen SSID list doesn't inform a drive-by.

**Tailscale with no upstream.** Tailscale nodes on the same LAN can form direct connections without internet once they've previously exchanged coordination info ([Tailscale docs](https://tailscale.com/docs/reference/connection-types)). First login requires internet. After that, peers on the same subnet do NAT-free direct connections; peers off-subnet fall back to DERP which requires internet. In the field scenario (Pi + phone on the Pi's AP, no upstream): if the phone has Tailscale and has recently seen the coordination server, direct-on-subnet should work. If not, Tailscale is effectively dead in-field and the user has to use the LAN IP / `geographica.local`. Recommendation: don't rely on Tailscale for the in-field user flow. It's a "home" convenience, not a field requirement.

**Other gotchas to mention in brainstorm:**
- systemd ordering: `hostapd.service` needs `After=network-online.target` disabled on the AP iface, or it races NM.
- Docker networking: the nginx container binds to `0.0.0.0:443` which will serve the AP subnet for free — no extra compose work as long as the host routes it.
- `hostname -I` in entrypoint.sh (line 30) returns the first address which may be the AP IP, the STA IP, or the Docker bridge depending on boot order. The self-signed cert generation is fragile here — this is part of why Spec B needs the SAN rework.

---
*Word count target: under 3000. Total: ~2800.*
