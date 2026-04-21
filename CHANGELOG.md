# Changelog

All notable changes to Geographica are documented here.

This project adheres to [Semantic Versioning](https://semver.org) with
project-specific rules described in [VERSIONING.md](VERSIONING.md). Entries
from v1.1.0 onward are generated automatically by `release-please` from
Conventional Commits.

## [Unreleased]

### Added

- **Nav voice picker** — Preferences sidebar section with Default / Male / Female gender quick-pick and an advanced disclosure for picking a specific installed voice. Cloud voices are filtered out by default for offline-reliability; opt-in via a labeled checkbox. Per-device localStorage. Hard-refresh (Ctrl/Cmd-Shift-R) once after upgrade.
- Screen keep-awake during active navigation — prevents phone auto-dim/auto-lock from silently stopping nav on mobile. Uses the Screen Wake Lock API on HTTPS, and a first-party silent-video fallback (`SilentVideoLock`) on plain HTTP (AREDN mesh, Pi-hotspot, LAN). No UI change; the existing nav banner is the evidence that keep-awake is active.
  - **Known limitation:** On iOS, Low Power Mode may disable screen keep-awake. Disable Low Power Mode or keep the phone plugged in for uninterrupted navigation.

## [1.5.2](https://github.com/cameronzucker/geographica/compare/v1.5.1...v1.5.2) (2026-04-19)


### Bug Fixes

* **pipeline:** expand supported regions to 48 states + DC; pipeline scripts use /usr/bin/python3 ([fe05fac](https://github.com/cameronzucker/geographica/commit/fe05facc0b73a649fe18a2d989051b14f10d3105))

## [1.5.1](https://github.com/cameronzucker/geographica/compare/v1.5.0...v1.5.1) (2026-04-19)


### Bug Fixes

* **setup:** drop fileinfo from download step; fix merge error for osmium 1.18; refresh btn-next text ([8a62b78](https://github.com/cameronzucker/geographica/commit/8a62b78bc47e3606aaa949637c2fe8e868fa2bde))

## [1.5.0](https://github.com/cameronzucker/geographica/compare/v1.4.0...v1.5.0) (2026-04-19)


### Features

* **harness:** exploratory_agent control + reporting tools + writers ([dd02ae2](https://github.com/cameronzucker/geographica/commit/dd02ae221794eec75f9c7770136b28e635debd23))
* **harness:** exploratory_agent loop + CLI + wizard-ci.sh --exploratory ([173d1e8](https://github.com/cameronzucker/geographica/commit/173d1e86bb564486605e4190d4e04eeaf0b09a17))
* **harness:** exploratory_agent system prompt + seeded bug-class list ([24febc6](https://github.com/cameronzucker/geographica/commit/24febc62ff5814640e89f59f2b0346b1e763c700))


### Bug Fixes

* **setup:** two bugs from 2026-04-20 beta tester screenshot (undefinedundefined... + missing --download) ([11ecf9d](https://github.com/cameronzucker/geographica/commit/11ecf9d2b5b0a1a11b91803464ad556841e7f941))

## [1.4.0](https://github.com/cameronzucker/geographica/compare/v1.3.3...v1.4.0) (2026-04-19)


### Features

* **harness:** exploratory_agent api_request tool ([5a730a3](https://github.com/cameronzucker/geographica/commit/5a730a39f64e38b2379fec5108beffc50e3314de))
* **harness:** exploratory_agent browser tools (Playwright wrappers) ([3e78d9a](https://github.com/cameronzucker/geographica/commit/3e78d9ae29ee0233539782932a6fe806e4eab464))
* **harness:** scaffold exploratory_agent package + deps + test shell ([16903be](https://github.com/cameronzucker/geographica/commit/16903be75bad7aeb3bc63c48f02cdc7954321ea5))


### Bug Fixes

* **pipeline:** osm_download + osm_merge filter states by user bbox ([5fb6583](https://github.com/cameronzucker/geographica/commit/5fb6583e9a731f8a0b430e536726ac9f579173ae))

## [1.3.3](https://github.com/cameronzucker/geographica/compare/v1.3.2...v1.3.3) (2026-04-19)


### Bug Fixes

* **setup:** normalize paths (strip trailing /, collapse //) at frontend + backend ([1d59197](https://github.com/cameronzucker/geographica/commit/1d591971b4401cb33c0359dd9627f53d7d2a2c88))

## [1.3.2](https://github.com/cameronzucker/geographica/compare/v1.3.1...v1.3.2) (2026-04-19)


### Bug Fixes

* **pipeline:** verify OSM PBF integrity at download, name the file at merge ([44c5ea6](https://github.com/cameronzucker/geographica/commit/44c5ea6702b57e4ab031892879e652557149589b))
* **setup:** CSRF token survives uvicorn restart + auto-reload stale tabs + verbatim error detail ([9325e93](https://github.com/cameronzucker/geographica/commit/9325e931dc97cd731cebfd019c667033612565f9))

## [1.3.1](https://github.com/cameronzucker/geographica/compare/v1.3.0...v1.3.1) (2026-04-19)


### Bug Fixes

* **setup:** wizard needs `websockets` package; surface WS failures in UI; harness probes venv deps ([ef28cd8](https://github.com/cameronzucker/geographica/commit/ef28cd861259c5e5f77ab84a155024ca94998ac3))

## [1.3.0](https://github.com/cameronzucker/geographica/compare/v1.2.1...v1.3.0) (2026-04-19)


### Features

* **hardware:** GX-01 Front Panel Board — full pipeline through JLC bundle ([e5e2bc4](https://github.com/cameronzucker/geographica/commit/e5e2bc469d594754426897dd3a78b729cdc78167))
* **hardware:** GX-01 v2 HAT — JLC bundle zip generated from v2b routed board ([2154f4a](https://github.com/cameronzucker/geographica/commit/2154f4ac8a085d56810ce80677962241828ea2a4))
* **hardware:** GX-01 v2 HAT — placement iteration v2b routes successfully ([fadec69](https://github.com/cameronzucker/geographica/commit/fadec6922c89c2caa77e2fc1b408d9d8c6c9599d))
* **hardware:** GX-01 v2 HAT + FPB WIP — placement done, routing blocked ([ba6de68](https://github.com/cameronzucker/geographica/commit/ba6de688a5affb7c85df653e5c414788a01c2b9c))
* **hardware:** swap C1 supercap → CR1632 coin cell holder ([da7f7f1](https://github.com/cameronzucker/geographica/commit/da7f7f1da77bc33eb63504ad31c95199d142cfba))
* **hardware:** wire JLC rotation-correction DB into make_jlc_bundle.py ([490ecf6](https://github.com/cameronzucker/geographica/commit/490ecf66331f3ceb37e54cedcf87cdb8d87b12a4))


### Bug Fixes

* **hardware:** correct LCSC codes for v2 HAT — all 4 rejected ICs now map to JLC-stocked parts ([ead0949](https://github.com/cameronzucker/geographica/commit/ead09498850f9e53702558c129b877e9fefc581a))
* **hardware:** J2 + J5 LCSC codes had low JLC stock — swapped to deep-stock alternatives ([daa46e5](https://github.com/cameronzucker/geographica/commit/daa46e5b76a9f7dff210542f61e7951bf802ec7d))
* **hardware:** J2 shroud vs J1 body collision + bypass cap pad overlaps ([4190ca1](https://github.com/cameronzucker/geographica/commit/4190ca1c044a757a3f155fe3d29e44e034c0d771))
* **hardware:** move R5/R6/R7/Q1 from Y=20 → Y=23 to clear J2 IDC shroud ([35b9620](https://github.com/cameronzucker/geographica/commit/35b9620729b9c8ee432a83ee093d4939fd7eb601))
* **hardware:** swap FPB switches from B3U (side-actuated) to B3S (top-actuated) ([9b70ebd](https://github.com/cameronzucker/geographica/commit/9b70ebd0f473e517ed0fcde2b23cc01df484cbb4))
* **setup:** unblock beta testers stuck in preflight + bootstrap loops ([5e400c5](https://github.com/cameronzucker/geographica/commit/5e400c5ae00030c56e8d666ce9230d12ff1f5c47))

## [1.2.1](https://github.com/cameronzucker/geographica/compare/v1.2.0...v1.2.1) (2026-04-19)


### Bug Fixes

* **setup:** purge Debian-native docker packages before docker-ce install ([59f00b5](https://github.com/cameronzucker/geographica/commit/59f00b5bfc4a503c8592f68b0687c81e4689a232))

## [1.2.0](https://github.com/cameronzucker/geographica/compare/v1.1.0...v1.2.0) (2026-04-19)


### Features

* GX-01 adapter HAT PCB (programmatic KiCad design) ([4686249](https://github.com/cameronzucker/geographica/commit/4686249566242306dc23f24836ce87b9ec409bf0))
* **hardware:** JLCPCB PCBA bundle generator for any KiCad project ([fa67865](https://github.com/cameronzucker/geographica/commit/fa6786582fd08f448dfb600858523e61dcfd019e))
* **hardware:** verified LCSC part numbers + fab-ready JLC bundle ([71a780b](https://github.com/cameronzucker/geographica/commit/71a780b686c878b4edb1ff52fc9ed0d4241a8f82))
* **hardware:** verify_lcsc.py — live JLCPCB catalog verification ([3bc40d9](https://github.com/cameronzucker/geographica/commit/3bc40d9161d490c769ccc12e7d9f33a12e4b4e38))
* **pcb:** fully automated routing via FreeRouting integration ([b3aade8](https://github.com/cameronzucker/geographica/commit/b3aade8bb4f5ed84a69379f3e4f29fc68ad0466e))
* **setup:** bootstrap installs tippecanoe from GitHub Release (B21/B27) ([c930fe0](https://github.com/cameronzucker/geographica/commit/c930fe0c853d007d01258cb605ab991f5b2402de))
* **setup:** bootstrap pip-installs pipeline deps as ACTUAL_USER (B21) ([19c1548](https://github.com/cameronzucker/geographica/commit/19c15481f84147354efa7dc82d645bb89b875a66))
* **setup:** drive+subpath+custom path UI, debounced validation (D1/B9) ([caf8b4a](https://github.com/cameronzucker/geographica/commit/caf8b4a29c812a188594c1ebf5d66f411a00eb77))
* **setup:** full command-builder library for pipeline (B10/B28) ([2c8022a](https://github.com/cameronzucker/geographica/commit/2c8022ad1b4ee09aebf5a5feee99ef4e3d54e15b))
* **setup:** JS sends layer_bbox overrides + zoom to backend (B20) ([a6170fc](https://github.com/cameronzucker/geographica/commit/a6170fc6c8f52999f4d4321ddfcb02ec3e073d46))
* **setup:** per-layer bbox/zoom/source in StartRequest (Option B + B20) ([d98d57e](https://github.com/cameronzucker/geographica/commit/d98d57ef282d3bf7a319e6dd0c956947cd9da474))
* **setup:** per-layer customize-coverage UI (Option B) ([a911778](https://github.com/cameronzucker/geographica/commit/a911778c48ae93e191385fb57ff154749c1221ef))
* **setup:** preflight covers tippecanoe, Python deps, keyring, cgroup, openssl (B21) ([5805731](https://github.com/cameronzucker/geographica/commit/5805731f7494d07bcd63880524e8185d78fe92ba))
* **setup:** reproducible ARM64 tippecanoe build tool (B21/B27) ([56bec6c](https://github.com/cameronzucker/geographica/commit/56bec6c977947770479eaedc227e42b6013b1e24))
* **setup:** structured PipelineStep registry (D5/B10) ([42f657a](https://github.com/cameronzucker/geographica/commit/42f657a5fb476c8d3fb93d0120487eef39e0222c))
* **setup:** two-control install-location UI; drop HOST_IP field (D1/D6) ([e914af3](https://github.com/cameronzucker/geographica/commit/e914af397a5cc55dc7a1d94300f8b978bd70d336))


### Bug Fixes

* **hardware:** correct JLC bundle CPL geometry and LCSC parts ([dc94255](https://github.com/cameronzucker/geographica/commit/dc9425545aa84def250f94498f33baba0ebcc414))
* **pipeline:** add completed_partial status for NOAA runs with failures (D2) ([6e253be](https://github.com/cameronzucker/geographica/commit/6e253bed882d35f395b8def21134642b6027316d))
* **pipeline:** cancel guards + WAL mode + no-erode-on-resume in NOAA Phase 5 (B1,B9,D1,D3) ([48092e6](https://github.com/cameronzucker/geographica/commit/48092e6fabf051c726c0b1a7e65e9d822a7449a3))
* **pipeline:** capture rasterio src dims before with exits (B3) ([aace75c](https://github.com/cameronzucker/geographica/commit/aace75ca1cc557daa9cb8e258eebab7f85847523))
* **pipeline:** count composite errors in merge_mbtiles (B7) ([6f26ed5](https://github.com/cameronzucker/geographica/commit/6f26ed50cb18f8d1ff502a520ad8ebca3844c09d))
* **pipeline:** detect _noaa_checkpoint divergence from tiles table (B13) ([8aa827c](https://github.com/cameronzucker/geographica/commit/8aa827c2c7fb8b765a278567deb6795b8b773b6b))
* **pipeline:** detect short-reads and reuse cached staging tiles (B10, B11) ([d943968](https://github.com/cameronzucker/geographica/commit/d943968639a41c880eeeabbdfa3910037d2722b6))
* **pipeline:** honor cancel during M2M overview build (B2) ([e8f5f2b](https://github.com/cameronzucker/geographica/commit/e8f5f2b46cfc42ee448960568dcae29d4eda2f90))
* **pipeline:** reject fully-out-of-bounds tiles in rasterize (B4) ([ffb93f3](https://github.com/cameronzucker/geographica/commit/ffb93f37cb371e317e922faf88f2136cf210d3b7))
* **pipeline:** share cancellable GDAL subprocess wrapper (B5) ([fc7e03d](https://github.com/cameronzucker/geographica/commit/fc7e03d96f2766b07f9c14122d8456f4e1dac69c))
* **pipeline:** wire NAIP --concurrency via asyncio.gather (B16) ([1f77a70](https://github.com/cameronzucker/geographica/commit/1f77a701f5dd39a49f7b8aaee9003d9895b72cfb))
* **pipeline:** write progress on _merger failure branches (B12) ([c619ec4](https://github.com/cameronzucker/geographica/commit/c619ec412d5029fe2800aa67335d8bd6f55bed9f))
* **search:** restart TileServer on clean pipeline completion (B1 2026-04-17) ([f6f7365](https://github.com/cameronzucker/geographica/commit/f6f736569956618cb1a5e53f3b52900caf15b182))
* **search:** target WAL checkpoint by pipeline type, not mode (B14) ([38b9d32](https://github.com/cameronzucker/geographica/commit/38b9d329fd437bbd1400d680ca9d1e94d27c4635))
* **setup:** __main__ binds 127.0.0.1 only (B36) ([4dca35c](https://github.com/cameronzucker/geographica/commit/4dca35c88dd4944202c77081f08f2ad801a86a1f))
* **setup:** _run_pipeline actually invokes run_command per step (B10) ([a3709aa](https://github.com/cameronzucker/geographica/commit/a3709aa3f568a3ab40b2098cb8a2309e10d9a99c))
* **setup:** /api/launch builds the pipeline profile image (B4) ([5edfd83](https://github.com/cameronzucker/geographica/commit/5edfd8358c0aa5193d26691e8212f41f8c4c982b))
* **setup:** add sudo -H so pip --user installs to ACTUAL_USER's home (B21) ([feaa18f](https://github.com/cameronzucker/geographica/commit/feaa18f14673d8b33a6215ac5accbe7c3866ece4))
* **setup:** broaden docker keyring guard to accept docker.asc too (T4 follow-up I1) ([8608b6d](https://github.com/cameronzucker/geographica/commit/8608b6d281318e0bc3de974bc2edad16e27887ff))
* **setup:** bump progress_buffer maxlen to 5000 (B43) ([be5f515](https://github.com/cameronzucker/geographica/commit/be5f5150db7aeee9bbd9c1509ebc5182f60c5ed9))
* **setup:** canonicalize TLS modes to http|https|tailscale (B1/B19) ([e24b799](https://github.com/cameronzucker/geographica/commit/e24b79968e999750add8682d96c206d2bd6f1971))
* **setup:** crash-resilient checkpoint + reset endpoint/UI (B14) ([30b893a](https://github.com/cameronzucker/geographica/commit/30b893a283a97b31e1bf903bd3d9de95f546ae24))
* **setup:** dedupe bootstrap Next-step + remind user to log out (B37) ([8dd5622](https://github.com/cameronzucker/geographica/commit/8dd5622a7174beea1ca86723cc469983432221f4))
* **setup:** defend TLS_MODE canonicalization at runtime boundaries ([98994d5](https://github.com/cameronzucker/geographica/commit/98994d5020236946a9ddd29963f3a4c5ab8e0874))
* **setup:** detect cmdline.txt location before editing (B31) ([9448947](https://github.com/cameronzucker/geographica/commit/9448947ae898986895efd4cda079d8fa6e130041))
* **setup:** emit every docker-compose VAR from generate_env; drop HOST_IP (B2/B3/B11/B29) ([b3d3792](https://github.com/cameronzucker/geographica/commit/b3d3792dcd21d9202de710bf33dbd5c551f39728))
* **setup:** enforce path-boundary in validate_path (B34) ([356dd1d](https://github.com/cameronzucker/geographica/commit/356dd1d531603808e529f66cd2937433227f0dd6))
* **setup:** filter detect_storage through allowlist (B41) ([9d25339](https://github.com/cameronzucker/geographica/commit/9d25339ef4ba0ea0ea47783845cb94124b28ea95))
* **setup:** guard tippecanoe mv against set-e abort; log existing-version ([9c40c01](https://github.com/cameronzucker/geographica/commit/9c40c013f301649b6bdfd955319020d3c52f17ce))
* **setup:** idempotent data symlink creation (B32) ([ee0872b](https://github.com/cameronzucker/geographica/commit/ee0872b26d82ff2b637d78a8c775c8ee3cc342b9))
* **setup:** install Docker Compose v2 plugin, not legacy v1 (B5) ([9eb7cc0](https://github.com/cameronzucker/geographica/commit/9eb7cc0919d6794963e1b842dc5eb0cc2ddd06f9))
* **setup:** launch re-targets ./data symlink to DATA_HOST_PATH (B2) ([14fba05](https://github.com/cameronzucker/geographica/commit/14fba052ffae3170a5cd58613e9bc8dfcb41208c))
* **setup:** one-connection-per-credential-store; revert fixture to real protocol ([46879b8](https://github.com/cameronzucker/geographica/commit/46879b8747d891a2af78c22f39a28bf8d02b3b76))
* **setup:** parallel ws broadcast with per-socket 2s timeout (B18) ([74b9641](https://github.com/cameronzucker/geographica/commit/74b96414fa2328beb8a585050f3a6adcb62d15d5))
* **setup:** parameterize container memory limits (B30) ([a1d3865](https://github.com/cameronzucker/geographica/commit/a1d386588c6ea01d4626ad9005ffe7a6a22233d2))
* **setup:** pin Planetiler to 0.10.2 (B28) ([6a04a50](https://github.com/cameronzucker/geographica/commit/6a04a508bb7adbad6fe585c955c16cbc6fbe8bd1))
* **setup:** preserve non-wizard .env keys + pre-fill from existing (B12) ([d179034](https://github.com/cameronzucker/geographica/commit/d17903430cf2854ada20f04292dc0eb7a74d8a03))
* **setup:** process-group + killpg for subprocess cleanup (B17) ([286ed56](https://github.com/cameronzucker/geographica/commit/286ed56c9b8030aa34a54b849660a1862a2f4fc8))
* **setup:** retune RAM profiles for good-neighbor memory ceilings (T12 follow-up) ([0e33c32](https://github.com/cameronzucker/geographica/commit/0e33c3282ce2f0f5c3a3032580dc117f17d003da))
* **setup:** scope bootstrap chown to top-level dirs only (B33) ([98adc27](https://github.com/cameronzucker/geographica/commit/98adc27f8b813694234632e06e073eb1ce552c76))
* **setup:** shared showError helper; await saves in nextStep (B13) ([3131f56](https://github.com/cameronzucker/geographica/commit/3131f567c6500516bf5143fb5ce02c61e9c04e27))
* **setup:** snapshot progress_buffer during ws replay (B16) ([946ed33](https://github.com/cameronzucker/geographica/commit/946ed33a462063e8b7b9576d88bdae6e39285198))
* **setup:** strict all_healthy — no false positives on unhealthy (B7) ([aef25ef](https://github.com/cameronzucker/geographica/commit/aef25ef9b2e99fd9c8bb1a76e63a4d261bb43371))
* **setup:** TOCTOU-safe /api/start with asyncio.Lock (B15) ([c4e1119](https://github.com/cameronzucker/geographica/commit/c4e1119d75eedc2edaf129bb2b66a03ad6a2ca35))
* **setup:** use communicate() for pipeline image check (compatible with test fakes) ([e427ac3](https://github.com/cameronzucker/geographica/commit/e427ac3e934084826ba26c4414e3e3abaca597b5))
* **setup:** walk original path for symlink check (B35) ([49ccc05](https://github.com/cameronzucker/geographica/commit/49ccc05013491b714467c4522e41d5dc515d170b))
* **setup:** write credentials through keyring Unix socket (B6) ([8726bf3](https://github.com/cameronzucker/geographica/commit/8726bf381c098ae7aa429ab0c620feffcfb2f6ed))
* **tests:** isolate Task 42 test cwd so it can't hijack real ./data symlink ([a2cf6dc](https://github.com/cameronzucker/geographica/commit/a2cf6dcd07ddc0fc219408b44f04b8063696dfc7))
* **tests:** unnest 5 TestValidatePath tests from TestEnvGenerationFull ([498b96a](https://github.com/cameronzucker/geographica/commit/498b96a3ffa811cfa6e9140e359c33324ba09a77))
* **tools:** tippecanoe default version 2.79.0 (plan's 2.80.0 doesn't exist upstream) ([d9cf18f](https://github.com/cameronzucker/geographica/commit/d9cf18fd81450800adfd434951e4e0277c9f92a9))


### Refactors

* **pcb:** switch LCD connector to 1x20 matching GDM12864H native layout ([2ddd8dc](https://github.com/cameronzucker/geographica/commit/2ddd8dc8d921c2dc8344966b387f261c2bb712f9))
* **pipeline:** write progress state once per call (B15) ([b1086ab](https://github.com/cameronzucker/geographica/commit/b1086ab3ce98802ea97553a4112935bfe914b2f4))
* **setup:** drop /api/fix-dependency; point users at bootstrap (D3/B22/B23/B24) ([e909c23](https://github.com/cameronzucker/geographica/commit/e909c236fea820531099db0e8b8a67b8336256ca))

## [1.1.0](https://github.com/cameronzucker/geographica/compare/v1.0.0...v1.1.0) (2026-04-18)


### Features

* add CLI entry point to tileserver_config.py — add/remove sources via command line ([e0b50e3](https://github.com/cameronzucker/geographica/commit/e0b50e313514080fa92aaa27341abe8662af0711))
* add site favicon across frontend, admin, and setup wizard ([dc93ab4](https://github.com/cameronzucker/geographica/commit/dc93ab406467ec2fc5e171d45a296778a9a1a852))
* admin panel bbox drawing uses toggle button — matches companion UX ([df1a200](https://github.com/cameronzucker/geographica/commit/df1a2007bdeea25207d86eb5c8960c329451f543))
* NOAA pipeline — quad dedup + bounds metadata fix ([5cc0973](https://github.com/cameronzucker/geographica/commit/5cc097392928e70a65ad4d0e5b1c0fe341f5a5c8))
* NOAA pipeline progress meter shows 3-stage progress + live ETA ([f3ddb53](https://github.com/cameronzucker/geographica/commit/f3ddb539d2a1dafdc4f1122aea009c7f2ee56107))
* port 3-stage parallel NOAA pipeline from companion ([42d9248](https://github.com/cameronzucker/geographica/commit/42d9248563f8a24c5ee703dc53dfeae1847225ac))


### Bug Fixes

* 15 pipeline fixes from 8-agent adversarial review ([6843090](https://github.com/cameronzucker/geographica/commit/6843090a71c238ca989694305312aa1e30b3003e))
* cap USGS basemap layer at z15 for smooth NOAA transition ([2e78d64](https://github.com/cameronzucker/geographica/commit/2e78d64a268b5c3c7fbd9046e7a8fb2331052b51))
* centralize TileServer restart in search service after pipeline completion ([cd66c6b](https://github.com/cameronzucker/geographica/commit/cd66c6bef62aa00b186dff1c33eac2daa3832cf6))
* compositing merge + nodata cleanup for NAIP tile pipeline ([e7e3b32](https://github.com/cameronzucker/geographica/commit/e7e3b32064e24090f8ad568eb14ff7c9e7252292))
* don't cap USGS basemap zoom — overzoom where no detail imagery exists ([3e233d5](https://github.com/cameronzucker/geographica/commit/3e233d5313ebbd9dd2835b62de047f24daabbf6d))
* overview orphan tiles at coverage edges + memory leak mitigation ([1bab361](https://github.com/cameronzucker/geographica/commit/1bab361d1b99c8fdeacdc59bf58d419b3c05d380))
* pipeline card grid — stop polling from nuking expanded cards ([452b103](https://github.com/cameronzucker/geographica/commit/452b103c2f7ed3e0ec4a66a5b74f44120fbb79bb))
* pipeline container deps, cancel button, draw box, download concurrency ([7b6af5b](https://github.com/cameronzucker/geographica/commit/7b6af5bebc4dda734159098f54065009b7446dff))
* set tileSize 256 on imagery sources — fixes zoom level alignment ([52b10e2](https://github.com/cameronzucker/geographica/commit/52b10e20698073eabe45d177b7a15bc8649717b2))
* WAL checkpoint after post-processing prevents TileServer 404 ([68edf6d](https://github.com/cameronzucker/geographica/commit/68edf6d27230f5afc235952ee945635f8bc74b4c))

## [1.0.0] — 2026-04-15

Initial release. Commits prior to v1.0.0 were experimental and are not
retroactively documented. See `README.md` for the feature overview at
release time.
