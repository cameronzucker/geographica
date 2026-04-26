# Changelog

All notable changes to Geographica are documented here.

This project adheres to [Semantic Versioning](https://semver.org) with
project-specific rules described in [VERSIONING.md](VERSIONING.md). Entries
from v1.1.0 onward are generated automatically by `release-please` from
Conventional Commits.

## [2.0.0](https://github.com/cameronzucker/geographica/compare/v1.5.3...v2.0.0) (2026-04-26)


### ⚠ BREAKING CHANGES

* **noaa:** --year is no longer a valid argument. Anyone scripting against the NOAA CLI must remove --year from their invocations.

### Features

* **app:** dispatch geographica:sidebar CustomEvent on open/close ([40b232f](https://github.com/cameronzucker/geographica/commit/40b232f3086f258e9da1cea1712677853b2e1619))
* **app:** export _formatDD and _haversineDistance to window ([6f50c69](https://github.com/cameronzucker/geographica/commit/6f50c69f2aa551ab32460507c7754f2fdd776262))
* **app:** invoke VoicePicker.init from DOMContentLoaded handler ([1f7c42b](https://github.com/cameronzucker/geographica/commit/1f7c42b2ca2deca1a09a298d2eb6b17194b28f59))
* **app:** ruler bail at reverse-geocode handler + exclusion list ([57ed307](https://github.com/cameronzucker/geographica/commit/57ed30762a6432459b9e32e998bf70e4430feccb))
* **app:** ruler bails at KMZ-pin + search-pin click handlers ([09eb077](https://github.com/cameronzucker/geographica/commit/09eb0775aff0b0b07510aac2db8161531c969707))
* **app:** whitelist measure-panel + wire initRuler in bootstrap ([d979d5f](https://github.com/cameronzucker/geographica/commit/d979d5fb3afd5103a798427cc43206d912e89475))
* **audit:** inference-cost audit script for Claude Code transcripts ([4f0fa46](https://github.com/cameronzucker/geographica/commit/4f0fa469264a954f2cee6b687fa64c8dbaca110e))
* **common:** add SLUG_BY_USPS canonicalization table ([85e8dac](https://github.com/cameronzucker/geographica/commit/85e8dac50fe32412ec02ef0c46272c092918e18a))
* **frontend:** cite 10-30 min duration in NOAA refresh confirm dialog ([ea7956f](https://github.com/cameronzucker/geographica/commit/ea7956f7d8d1b3de8e1606087256bec958614e4e))
* **frontend:** live progress bar + ETA for NOAA catalog refresh ([24639b7](https://github.com/cameronzucker/geographica/commit/24639b77f7839c98c9a4368342d46ac34421617b))
* **frontend:** load wake-lock scripts in index.html with cache-busters ([f7fb1aa](https://github.com/cameronzucker/geographica/commit/f7fb1aae0b8cc89fcf43252c97434b798d2e9b6b))
* **frontend:** NOAA card refactored into Whole state / Custom area tabs ([23ff95b](https://github.com/cameronzucker/geographica/commit/23ff95b4575555f8f55f7603133cb116d33a2f8d))
* **frontend:** NOAA catalog refresh-history panel + rollback button ([37a33ad](https://github.com/cameronzucker/geographica/commit/37a33add4a525168cce56fd469354faa57717785))
* **frontend:** NOAA custom-area tab shows current bbox + prompts when empty ([a37f4a9](https://github.com/cameronzucker/geographica/commit/a37f4a9937a8bac4f5ee111961dc8c777089561c))
* **frontend:** NOAA estimate UI — peak-disk gate + acknowledge_missing + bbox validation ([7a98433](https://github.com/cameronzucker/geographica/commit/7a9843338be23e8a42104a5f43d5a7ef0a1c880e))
* **frontend:** NOAA partial_failed pipeline — retry-failed-states UI ([c979205](https://github.com/cameronzucker/geographica/commit/c979205716de88120b5841cc1fd0cf32c8f6404d))
* **frontend:** NOAA refresh completion summary + dropdown reload ([72c496d](https://github.com/cameronzucker/geographica/commit/72c496df24faa6e532ca205f5440412d2122d80d))
* **frontend:** populate NOAA state dropdown from live catalog ([b82c3d9](https://github.com/cameronzucker/geographica/commit/b82c3d94387bdd459cd7e3d3444ebc88761ecc78))
* **frontend:** promote NOAA Refresh to primary empty-state CTA ([00f939e](https://github.com/cameronzucker/geographica/commit/00f939e1184233e5086b05ed920bc07d7de9ec34))
* **frontend:** rename Measure tab to Tools + reorder tabs (Cameron preference) ([0d25293](https://github.com/cameronzucker/geographica/commit/0d25293d843d90fb54a06a84b655fec8c7a4bc09))
* **frontend:** SilentVideoLock module — enable/disable/isActive ([e2dc957](https://github.com/cameronzucker/geographica/commit/e2dc95790ea6f2685e487dcaf69ec38d738a4773))
* **frontend:** vendor silent.mp4 for wake-lock fallback ([22fbc2a](https://github.com/cameronzucker/geographica/commit/22fbc2a5f0109491eb5e2f4d83f6c318b694825a))
* **frontend:** WakeLock edge cases — iOS PWA bypass + more ([d8a2200](https://github.com/cameronzucker/geographica/commit/d8a2200962b6aece04ea685521111dee90935b65))
* **frontend:** WakeLock fallback to SilentVideoLock ([95b8c5a](https://github.com/cameronzucker/geographica/commit/95b8c5a93012a2d712093163bbc0adc69087b72b))
* **frontend:** WakeLock module — primary path + idempotency ([272d156](https://github.com/cameronzucker/geographica/commit/272d156ba49defb06f3c33305a762ccdc7103db2))
* **frontend:** WakeLock visibility-change handler ([fac58fe](https://github.com/cameronzucker/geographica/commit/fac58fef68e526581e14a51db5c6967362d07f61))
* **nav:** _geographicaUseImperial helper for live-distance prefix ([7bad09c](https://github.com/cameronzucker/geographica/commit/7bad09c2aaab1ac1de43de065d1cbc9929802f77))
* **nav:** §6.5 field-gate debug hook ([fb30022](https://github.com/cameronzucker/geographica/commit/fb300221290caca841588655c4439bb4bb76f6a5))
* **nav:** add TTM constants (spec v2 §4.1) ([b12d619](https://github.com/cameronzucker/geographica/commit/b12d619b95c3a5d72a110a729cbfae5f42363034))
* **nav:** formatDistancePrefix — Google-Maps-style live-distance helper ([7800ae7](https://github.com/cameronzucker/geographica/commit/7800ae7db57f1ee492c0b0542ba71e0fa8434e77))
* **nav:** GPS-recovery flag for prefix-suppression on first post-stale tick ([7ab9bf7](https://github.com/cameronzucker/geographica/commit/7ab9bf768b27114772ff862738d417e25dda15d2))
* **nav:** integrate voice picker into nav-ui onVoice path ([55e71b9](https://github.com/cameronzucker/geographica/commit/55e71b935c38cb309b0f6356d1dec6f00d59c181))
* **nav:** integrate WakeLock acquire/release with nav lifecycle ([17f5cff](https://github.com/cameronzucker/geographica/commit/17f5cff34f62a0fbf3e7937682a5b2068cffa692))
* **nav:** live-distance prefix on far-tier voice prompts ([8956ead](https://github.com/cameronzucker/geographica/commit/8956ead88df1264c8ca48b36451d5b88d0818834))
* **nav:** live-distance prefix on near-tier base + chain-append ([90b41d8](https://github.com/cameronzucker/geographica/commit/90b41d8fd47dc55be0965b8124750cf92fdeebe9))
* **nav:** speed-smoothing state + pushSpeedSample/speedMedian (spec v2 §4.2) ([8bd7271](https://github.com/cameronzucker/geographica/commit/8bd727168fd5ea1d1d8a5c7c860a864f0b024417))
* **nav:** stripBakedDistance — strips Valhalla mid-string distance chains ([c259004](https://github.com/cameronzucker/geographica/commit/c2590041255f0ce86770d28f1736aa7faf2982a7))
* **nav:** TTM checkVoice rewrite + I1/I2/I3/I4/I10 invariant tests ([ae3eb65](https://github.com/cameronzucker/geographica/commit/ae3eb659ecf3305408710f59bad45308c7cc2968))
* **noaa:** accept --state slug or --bbox; remove --year ([bf27867](https://github.com/cameronzucker/geographica/commit/bf2786768267755b04cae34ce496239aa9b81a87))
* **noaa:** add catalog structure validator ([08163fa](https://github.com/cameronzucker/geographica/commit/08163fa9cc1c9799e2f883d3988c810b3dc0f676))
* **noaa:** async-dispatch POST /admin/pipeline/noaa/refresh ([015a325](https://github.com/cameronzucker/geographica/commit/015a325a255a2658b060e079fda6012b07743dc3))
* **noaa:** atomic snapshot + symlink swap ([07cbe83](https://github.com/cameronzucker/geographica/commit/07cbe8310df561058b11de88a94f718ed00ce546))
* **noaa:** Azure blob listing client with NextMarker pagination ([13c725e](https://github.com/cameronzucker/geographica/commit/13c725ecf615a364eed1f2db3580d932ce83634c))
* **noaa:** checkpoint PK = (snapshot, usps, filename) ([e30bcdb](https://github.com/cameronzucker/geographica/commit/e30bcdb27dd850b757413c810831383ec85273f8))
* **noaa:** detect running pipelines to gate refresh/rollback ([013dd89](https://github.com/cameronzucker/geographica/commit/013dd895be3e994633ee49eaad113d56ab2cbf94))
* **noaa:** extend estimate endpoint — catalog-driven, multi-state, backward-compatible ([c74a935](https://github.com/cameronzucker/geographica/commit/c74a93562fb74e00c58de97755c4029b19d6f39c))
* **noaa:** flag stale refresh in /progress response ([dcce6c5](https://github.com/cameronzucker/geographica/commit/dcce6c58516d5464dd141c92e8f79f5afce470f4))
* **noaa:** GET /admin/pipeline/noaa/refresh-log endpoint ([d347701](https://github.com/cameronzucker/geographica/commit/d347701529939fba2dbdb96890aadf115686bac7))
* **noaa:** GET /admin/pipeline/noaa/refresh/progress endpoint ([b3b4a39](https://github.com/cameronzucker/geographica/commit/b3b4a39d966483dc93c200f3731764c7cb06b878))
* **noaa:** implement placename logic for estimate endpoint (Task 21) ([3dc72e3](https://github.com/cameronzucker/geographica/commit/3dc72e36833582394ee2c4b9f234d211ac937be9))
* **noaa:** merge_mbtiles populates _overview_work_queue atomically ([1b17fc4](https://github.com/cameronzucker/geographica/commit/1b17fc492aa21999b916b581f81fc077abce0441))
* **noaa:** NOAA directory parser + tile-index validation ([119cb8f](https://github.com/cameronzucker/geographica/commit/119cb8fe2be7af22475ed06a2abbdb763c666506))
* **noaa:** partial-failed terminal state suppresses TileServer register ([eb30eb3](https://github.com/cameronzucker/geographica/commit/eb30eb34c39dbf7e13d6fa375c090fbb03d50491))
* **noaa:** peak-working-set disk estimate ([55da4e4](https://github.com/cameronzucker/geographica/commit/55da4e414217d083aacd39376e0d40231321e50f))
* **noaa:** peak-working-set disk estimate ([5719b3b](https://github.com/cameronzucker/geographica/commit/5719b3b738a2431fcf74a04e3d35065614c38d87))
* **noaa:** pipeline pins catalog snapshot at Start ([6be8db2](https://github.com/cameronzucker/geographica/commit/6be8db2a55af300babeba64ca765848455605b97))
* **noaa:** POST /admin/pipeline/noaa/force-unlock endpoint ([52b9d96](https://github.com/cameronzucker/geographica/commit/52b9d960478f5e4fff41e95db5153e5548ba5796))
* **noaa:** POST /admin/pipeline/noaa/refresh endpoint ([b1fb1cb](https://github.com/cameronzucker/geographica/commit/b1fb1cbc2ff1266eb5ea2e7dff9b23f13b7d20a6))
* **noaa:** POST /admin/pipeline/noaa/refresh/cancel endpoint ([5238834](https://github.com/cameronzucker/geographica/commit/5238834514c1795dfec88b1f48f7e8a5710bf841))
* **noaa:** POST /admin/pipeline/noaa/rollback endpoint ([53055cc](https://github.com/cameronzucker/geographica/commit/53055cc3e083023024242439fc0e18e40c300fad))
* **noaa:** POST /refresh/reset endpoint + Force Clear wiring ([edc8744](https://github.com/cameronzucker/geographica/commit/edc874414a40494fd097acea0f6e5b0db00f089c))
* **noaa:** progress callback + cancellation + event-loop-safe fetch_tile_count ([3956dff](https://github.com/cameronzucker/geographica/commit/3956dff6b7c64e24608a25e1efb5748f16065361))
* **noaa:** progress-state helpers for async catalog refresh ([6fdac47](https://github.com/cameronzucker/geographica/commit/6fdac47fe06356fdcdf593ed6448ac520608b138))
* **noaa:** refresh lockfile with PID-liveness force-unlock ([dfd6ce1](https://github.com/cameronzucker/geographica/commit/dfd6ce17450dc05365d5a8b2af7f7d54288aa816))
* **noaa:** refresh log append + snapshot pruning with pinning guard ([f8a2080](https://github.com/cameronzucker/geographica/commit/f8a2080f2ffd2280aa9731b6dd0f8f5b157e82ba))
* **noaa:** refresh_catalog orchestrator + CI baseline ([c45a0b7](https://github.com/cameronzucker/geographica/commit/c45a0b7c40c031c2bdaae8d6e8a54577f1db1417))
* **noaa:** reorder post-processing to merge→erode→inpaint→overviews ([22f026a](https://github.com/cameronzucker/geographica/commit/22f026a6bddc52b21f203807b99155cf75744692))
* **noaa:** resolver maps bbox/state to cataloged entries with missing[] ([4a67164](https://github.com/cameronzucker/geographica/commit/4a671644ed9efadd6fb7cfbcfd1f24a4e83c9f94))
* **noaa:** resume refuses run if pinned snapshot was pruned ([00befb7](https://github.com/cameronzucker/geographica/commit/00befb775fdd985591adb4f55dae9950dd623773))
* **noaa:** Start endpoint pins snapshot, gates on acknowledge_missing, rechecks disk ([8adb061](https://github.com/cameronzucker/geographica/commit/8adb0616f41c84e13db413074c4c87e2c03dea5b))
* **noaa:** unified download queue of (snapshot, usps, filename, url) tuples ([8c989bc](https://github.com/cameronzucker/geographica/commit/8c989bca5dc0af6380d17f43fb6733c9748299e0))
* **noaa:** unified download queue of (snapshot, usps, filename, url) tuples ([180231e](https://github.com/cameronzucker/geographica/commit/180231e227a7c9a56d2e66fe55d2dccf9c4ca6c1))
* **noaa:** whole-state mode skips ogr2ogr filter ([13535b0](https://github.com/cameronzucker/geographica/commit/13535b0d7696a33a54d859cbf14af38736088f3c))
* **overview:** _drain_journal — targeted ancestor rebuild via unified re-eval ([2cba28b](https://github.com/cameronzucker/geographica/commit/2cba28b0ae1e4f81a549a45f47977b270535fc7e))
* **overview:** _drain_nuclear — refactored legacy full-rebuild path ([2690dff](https://github.com/cameronzucker/geographica/commit/2690dff4dd2971ab220bdb5996d2b222eade49a1))
* **overview:** _enqueue_ancestors computes + inserts the dirty lineage ([b5d99ac](https://github.com/cameronzucker/geographica/commit/b5d99ac8cd61fb5c5cc17d47f42be81f7d528927))
* **overview:** _init_journal creates the _overview_work_queue table ([8532ef7](https://github.com/cameronzucker/geographica/commit/8532ef748a05d4adf2bf7653dd73b8ab109e5688))
* **overview:** _mutate_base_tile — atomic base-tile write + journal enqueue ([6fbc909](https://github.com/cameronzucker/geographica/commit/6fbc9096af1e5a42fce7da7bc20dd741aea59465))
* **overview:** A/B comparison harness for nuclear vs journal modes ([29d34e1](https://github.com/cameronzucker/geographica/commit/29d34e13834376412c74f6b85aa1c64eaeccd248))
* **overview:** build_overviews mode selector + empty guards + threshold ([b705107](https://github.com/cameronzucker/geographica/commit/b7051074a4cd48fbd16c75dce593c5721e25e6a7))
* **overview:** erode_nodata_edges returns deleted coords + enqueues ancestors ([6434549](https://github.com/cameronzucker/geographica/commit/64345498375f7eb1718307b63c28629450d3ffa2))
* **overview:** inpaint_nodata_pixels restricts to max_zoom + returns list ([aa22ae2](https://github.com/cameronzucker/geographica/commit/aa22ae299c1531de98483cabaa328ea8adfd8076))
* **ruler:** bearingDeg — true forward azimuth, [0,360) ([baebd7c](https://github.com/cameronzucker/geographica/commit/baebd7c5c05acb48f7e36d6302c08b2cf8b74eff))
* **ruler:** commitInsert + Insert-Before/After button wiring ([5219546](https://github.com/cameronzucker/geographica/commit/5219546596b9c2e40bf9e266d7a4dfff6431b126))
* **ruler:** CSS skeleton — palette, panel, vertex rows, sparkline ([4aaee74](https://github.com/cameronzucker/geographica/commit/4aaee74ee7295d5bb0fdc4d082ca20f1f598413f))
* **ruler:** elevationFromRGB — Mapzen Terrarium decode + guards ([4d4bf9a](https://github.com/cameronzucker/geographica/commit/4d4bf9a5ec37ac0f0e82776a24d053870ef3361e))
* **ruler:** formatRulerDistance — imperial/metric live-read formatter ([6e733c6](https://github.com/cameronzucker/geographica/commit/6e733c6c6be02ea29fbdbf31cdc0641b9201fa26))
* **ruler:** handleMapClick — debounce + modifier-key suppression ([77939b7](https://github.com/cameronzucker/geographica/commit/77939b741d4af9956f6e1c02c7ed041c0efd565d))
* **ruler:** keyboard handler — Backspace/Esc/Enter + input guard ([e8f6699](https://github.com/cameronzucker/geographica/commit/e8f66994aa784c855ec849b8b0d82df255e6597d))
* **ruler:** layer-scoped vertex click + tap-vs-drag detector ([7636a06](https://github.com/cameronzucker/geographica/commit/7636a06871a928269bb14416e59616eac2073f90))
* **ruler:** map sources + 6 layers + style-load reattach hook ([14d8531](https://github.com/cameronzucker/geographica/commit/14d85311b9dde7c1c6c03585db2411b60ba001e8))
* **ruler:** Measure tab DOM + script include ([ac2e297](https://github.com/cameronzucker/geographica/commit/ac2e29761887466de0da62afd3ce074ac7be020e))
* **ruler:** module skeleton with idempotent init / isActive / clear ([36b398d](https://github.com/cameronzucker/geographica/commit/36b398d05e8b66c2afbb22d7e9f7405224aae8bc))
* **ruler:** mouse drag-to-reposition with rAF-coalesced source updates ([dd7a879](https://github.com/cameronzucker/geographica/commit/dd7a8797074d122dca87cb3983c1905952438c8f))
* **ruler:** projectPointToSegment — closest-point-on-segment ([ac5c402](https://github.com/cameronzucker/geographica/commit/ac5c402986adabd093dec88b28294f382992ee84))
* **ruler:** renderPanel — state-driven DOM via safe-clear pattern ([d2e53ca](https://github.com/cameronzucker/geographica/commit/d2e53ca0e2923ac5e8858068fcc4551c35c9348c))
* **ruler:** samplePath — distance-uniform path sampling ([fc1c358](https://github.com/cameronzucker/geographica/commit/fc1c35800ec0c28a60e24aab8b716b88f145c25f))
* **ruler:** selected-vertex highlight via per-Feature property flag ([0a69d76](https://github.com/cameronzucker/geographica/commit/0a69d766e07a3cf00a437621033c383e1ca628b2))
* **ruler:** sparklinePath — SVG points string for elevation profile ([16a58dd](https://github.com/cameronzucker/geographica/commit/16a58dddd27910a181eb37593bcdbb3e699020a4))
* **ruler:** state-machine helpers + relabel/recompute ([7418c13](https://github.com/cameronzucker/geographica/commit/7418c13f5b851294129d7b6481add333b2942671))
* **ruler:** tab activation + cursor management + button wiring ([bd5d21f](https://github.com/cameronzucker/geographica/commit/bd5d21f1780a30505cc14537472271b341f8492a))
* **ruler:** touch drag (passive:false, multitouch cancel) + visibilitychange leak fix ([fa3bdab](https://github.com/cameronzucker/geographica/commit/fa3bdab3ad749ab3ad789ea25e11ef90b476395b))
* **scripts:** Playwright README screenshot capture framework ([f500250](https://github.com/cameronzucker/geographica/commit/f500250d666a6fc4716c2b736b4f148c321b0f38))
* **sidebar:** restore tab on pageshow/visibilitychange + preserve form focus ([0257bca](https://github.com/cameronzucker/geographica/commit/0257bcaef267e88f0a099186ef6dc094b4b3c334))
* **voice-picker:** core voice resolution with offline-first filter ([528f783](https://github.com/cameronzucker/geographica/commit/528f783dd30f92cbe785ee6af5ec8933d14f6044))
* **voice-picker:** cross-tab storage event listener ([0cfabb3](https://github.com/cameronzucker/geographica/commit/0cfabb3975009df64dc939ae27544fc9886c4699))
* **voice-picker:** CSS for Preferences section + .sr-only global ([dac13ff](https://github.com/cameronzucker/geographica/commit/dac13ff26a868b3302ecbd6c3aa7374289f49782))
* **voice-picker:** dev-only ?voice-picker-mock query param ([9309020](https://github.com/cameronzucker/geographica/commit/9309020222e202553ef9f653894da133c0094080))
* **voice-picker:** DOM handlers for buttons, dropdown, advanced toggle ([d4ae478](https://github.com/cameronzucker/geographica/commit/d4ae4783356c26280e5fb7203168161e5412dffc))
* **voice-picker:** inferGender + KNOWN_VOICES table ([1afa330](https://github.com/cameronzucker/geographica/commit/1afa3303df54a979000781276e0f9f283c464823))
* **voice-picker:** load voice-picker.js script in index.html ([5c09b5b](https://github.com/cameronzucker/geographica/commit/5c09b5bf5632f715c3243ffdd9f38cf724bc0871))
* **voice-picker:** localStorage read/write with schema version ([8505590](https://github.com/cameronzucker/geographica/commit/8505590509850d3d54924c99135870813905cdb2))
* **voice-picker:** Preferences section in sidebar ([5fb3972](https://github.com/cameronzucker/geographica/commit/5fb3972bf457cd16b605bfccce04ac8c98be8b3b))
* **voice-picker:** preview lifecycle with generation counter ([452856d](https://github.com/cameronzucker/geographica/commit/452856df872554c999681e9d587bb3e205e0c156))
* **voice-picker:** skeleton IIFE module with public API stubs ([4941912](https://github.com/cameronzucker/geographica/commit/4941912d4534c49b12e5938859d81e35642b13cf))
* **voice-picker:** voiceschanged bootstrap (triple-check + poll + iOS prime) ([f822885](https://github.com/cameronzucker/geographica/commit/f8228856d248af9565957f195c1d860a3e366da9))
* **voice-picker:** watch body.class for nav-active changes ([71a0163](https://github.com/cameronzucker/geographica/commit/71a01638774aab0605f3faa80b6fd3151236364e))


### Bug Fixes

* **admin+bootstrap:** structured 422 on missing pipeline image + bootstrap pre-build ([a1c0b0b](https://github.com/cameronzucker/geographica/commit/a1c0b0bb1626457f4668a0bc2cf7a41f4a4c3acd))
* **audit:** dedup by message.id + per-model pricing (CRITICAL bugs) ([e456666](https://github.com/cameronzucker/geographica/commit/e456666cb347e0608175caaa62660e3db180d95b))
* **audit:** restore flat subagent_glob; tests opt out via empty string ([6c6468a](https://github.com/cameronzucker/geographica/commit/6c6468a582859cd54fd36e3add3a898bd8eec92e))
* **ci:** add --test-force-exit to JS unit tests step ([9037d2f](https://github.com/cameronzucker/geographica/commit/9037d2f3612dcf66c14b71d8fc708a683ea779a5))
* **frontend:** cache-bust app.js + navigation.js + nav-ui.js ([d5f2a50](https://github.com/cameronzucker/geographica/commit/d5f2a50a5e61c09bc973652fec39712c991a53e2))
* **frontend:** cache-buster enforcement test + 3 missing busters + pitfall [#16](https://github.com/cameronzucker/geographica/issues/16) ([bc9e0df](https://github.com/cameronzucker/geographica/commit/bc9e0df37017299f70f5d9c528eb7c7d0748e477))
* **frontend:** Phase 4 review closeout — listener leak, injection surface, bbox gate ([bf83af4](https://github.com/cameronzucker/geographica/commit/bf83af4817572bfbe8dc843be8ed05a00eaaf2d3))
* **nav:** applyReroute/triggerReroute hardening (spec v2 §4.5) ([b5bf27b](https://github.com/cameronzucker/geographica/commit/b5bf27bfa170b03b515fcfc1fe1e7d13eaf86a5d))
* **nav:** BAND-AID voice tiers [far, near] capped at 2 per maneuver ([e63f6d9](https://github.com/cameronzucker/geographica/commit/e63f6d96bfa7c1b988a0ab0087cebbb8829de7c3))
* **nav:** cancel in-flight reroute fetches and retries on stop (B12) ([52149d3](https://github.com/cameronzucker/geographica/commit/52149d303f2a56701bd9b7e1886b4eee0e8a8784))
* **nav:** clamp begin_shape_index=0 in multi-leg route stitching (B13) ([5565caa](https://github.com/cameronzucker/geographica/commit/5565caa21749473e237d2bb1e4f3fc5cba103440))
* **nav:** clear lastRerouteTime when engine reroute timeout fires (B10) ([e70412c](https://github.com/cameronzucker/geographica/commit/e70412cdb01087deed60718b8d8b2863840abe43))
* **nav:** correct padding formula for short viewports (B3 follow-up) ([36e8e82](https://github.com/cameronzucker/geographica/commit/36e8e82f45081292df32ef661cde2266f8e78e9f))
* **nav:** dead-reckoning is position-only, no voice (spec v2 G11) ([664389d](https://github.com/cameronzucker/geographica/commit/664389d98fea35b981518b96afca56b762062388))
* **nav:** dual-state Get Route / Clear Route button + clearRoute nulls lastTrip ([9e454f4](https://github.com/cameronzucker/geographica/commit/9e454f438e0cdeb0f7f3c2e55b41721837c1bb5a))
* **nav:** engine dedups duplicate GPS positions for hysteresis (B7) ([633f176](https://github.com/cameronzucker/geographica/commit/633f176ae811e8e756f77afb20f52a5dd1d78ad9))
* **nav:** formatDistancePrefix rejects NaN/Infinity/negative input ([fc22927](https://github.com/cameronzucker/geographica/commit/fc229273a6d6027a9c3b86ce2b467cb120a58d74))
* **nav:** G11 mark-order in near-tier + comment hygiene ([1687bc9](https://github.com/cameronzucker/geographica/commit/1687bc9c3979f833d2c3d3490eb476b91409630d))
* **nav:** I11 chain-extension suppresses redundant far-tier in mixed-spacing clusters ([4a9c5b6](https://github.com/cameronzucker/geographica/commit/4a9c5b6d0ee1afe61c88fbcdd5f2f6392e4b8089))
* **nav:** iOS PWA bypass must also apply to visibility re-acquire ([c2179b4](https://github.com/cameronzucker/geographica/commit/c2179b4b9328b31963ebecbfc3b01ad41ce08e0f))
* **nav:** preserve costing_options across reroutes (B6) ([ce12c02](https://github.com/cameronzucker/geographica/commit/ce12c02507d2ed4efe8153f7ce9ce70956f8f032))
* **nav:** preserve intermediate waypoints across reroutes (B5) ([03624b5](https://github.com/cameronzucker/geographica/commit/03624b5f2bd7d9c59ddcc3a95a03976076db6fbe))
* **nav:** propagate UI mute state to engine on nav start (B14) ([8c5fd4e](https://github.com/cameronzucker/geographica/commit/8c5fd4e2a6d9a418e718e07262a5923094a6150b))
* **nav:** proportional nav padding + clear padding on nav exit (B3, B8) ([cf56e6a](https://github.com/cameronzucker/geographica/commit/cf56e6a051bf6c0f3ee1edb1de5980e4a11fdcc4))
* **nav:** raise near-tier distance floor for surface-street buffer ([1e91579](https://github.com/cameronzucker/geographica/commit/1e9157908215ae746e7926fa2f7eccccf4a60bf3))
* **nav:** reset announcedSet and lastAnnouncementTime on applyReroute (B9) ([830e4c7](https://github.com/cameronzucker/geographica/commit/830e4c7359c07871a2b2951fbc038d249a71909c))
* **nav:** stack recenter button above compass, resolve mobile overlap (B4) ([ddc9578](https://github.com/cameronzucker/geographica/commit/ddc9578e84073c62c333fdac58b44e87e2556cc0))
* **nav:** strip Valhalla's baked-in Then prefix/suffix in near-tier prompts ([b0a1b27](https://github.com/cameronzucker/geographica/commit/b0a1b27c2792d5ed7270e12a39dc9258e2b9a847))
* **nav:** suppress distance prefix on near-tier floor-fires (B1) ([e831803](https://github.com/cameronzucker/geographica/commit/e8318038f3f5417818c0fcb2d32ad187e7b509ab))
* **nav:** T3 quality-review follow-ups (tautology, orphan docs, I10 strength) ([8f63ee0](https://github.com/cameronzucker/geographica/commit/8f63ee0c6cf1aa3e11278227ea5a5f5a3f0f0dc0))
* **nav:** update map polyline + sidebar + _geographicaLastTrip on reroute (B2) ([cb3f27b](https://github.com/cameronzucker/geographica/commit/cb3f27b73aea5094c5f2513e3c3623a81fbd98e2))
* **nav:** wake-lock duplicate-load guard collides with native Screen Wake Lock API ([6bc0ba3](https://github.com/cameronzucker/geographica/commit/6bc0ba3b23477747a6da8fbdfec2ccc83b479792))
* **noaa:** correct tile-index URL pattern — drop spurious /tileindex/ subdir ([4ffd658](https://github.com/cameronzucker/geographica/commit/4ffd658e43c70c72182ca89dc5b366dc5ce3865c))
* **noaa:** install gdal-bin in search container + render real refresh-log shape ([1910e15](https://github.com/cameronzucker/geographica/commit/1910e15f9a30e6819cf169b2b5d05b902828a53f))
* **noaa:** metadata fixup survives overview-build failure ([407338c](https://github.com/cameronzucker/geographica/commit/407338c47dc54e546e2c501a7936a5ce00f9ee45))
* **noaa:** NOAA admin endpoints — module import path + aiohttp dep ([4d837db](https://github.com/cameronzucker/geographica/commit/4d837dba49f4af496e8fc9453e39d12601f6c453))
* **noaa:** ogrinfo instead of ogr2ogr for feature count (GDAL 3.10) + warning banner when ok+0-states ([e937d02](https://github.com/cameronzucker/geographica/commit/e937d02c34308617d40ec76e08a1467c3a71219a))
* **noaa:** peak-disk estimate wildly overcounts — 3 bugs in one path ([3c0da22](https://github.com/cameronzucker/geographica/commit/3c0da221a0b8cfb5aec51c041e4e0421cb4ccb55))
* **noaa:** Phase 1 review closeout — cancel granularity, duplicate log, stale TypeError ([fe8db7d](https://github.com/cameronzucker/geographica/commit/fe8db7d2651b60bcc3c559d7e1d4d8d34fb27c46))
* **noaa:** Phase 2 review closeout — 4 correctness fixes ([3cd2e58](https://github.com/cameronzucker/geographica/commit/3cd2e58911bcc3850bd462862c0fd9c7aa5fe323))
* **noaa:** Phase 2 review closeout — polling lifecycle + reset hang + UX polish ([5b97549](https://github.com/cameronzucker/geographica/commit/5b97549e44b75d5cc2f2af4791e008e869bc3e3e))
* **noaa:** Phase 3 review closeout — tile-count parity, docstring, 409 shape, test gaps ([649ed3d](https://github.com/cameronzucker/geographica/commit/649ed3da7e826a6393498bc5f04b948f75e2488a))
* **noaa:** pipeline container uses dynamic catalog — was still hitting legacy NOAA_NAIP_CATALOG ([5fbd71d](https://github.com/cameronzucker/geographica/commit/5fbd71d356ead76b1de08fb3d13177663d6adde0))
* **noaa:** reject path traversal on rollback to_snapshot ([7159080](https://github.com/cameronzucker/geographica/commit/7159080ec0a8cade1bb0aaf74c333dfeea849fc0))
* **noaa:** rename refresh progress card id to avoid collision with pre-existing scaffold ([9d700f1](https://github.com/cameronzucker/geographica/commit/9d700f1e45cd73fb20bb7b8cf0efb86c2fc844ea))
* **noaa:** Start returns 409 no_catalog instead of letting container crash ([135173a](https://github.com/cameronzucker/geographica/commit/135173a4f587c85ec0812b7bb9ed2aed3649e729))
* **overview:** _composite_2x2_children all-None guard + import cleanup ([b28d100](https://github.com/cameronzucker/geographica/commit/b28d100b6b5ee1c14c381505dbeec0bd508a7709))
* **overview:** _mutate_base_tile raises ValueError; rollback test robustness ([903a6f9](https://github.com/cameronzucker/geographica/commit/903a6f925193850252f5abf91c350a25b69020f6))
* **overview:** document _init_journal's transaction-neutral contract ([1cf9b66](https://github.com/cameronzucker/geographica/commit/1cf9b6660e94aae5cd4284ba38c8eb3a90136db1))
* **overview:** strengthen _enqueue_ancestors tests + fix stale comment ([426b386](https://github.com/cameronzucker/geographica/commit/426b3861c59fb9e10ebbd466a737184c5e2bc11b))
* **ruler:** clearAll re-enables dragPan + clears view.dragging ([2b07c57](https://github.com/cameronzucker/geographica/commit/2b07c571a172f45cd81f810eb15edb7bfe0081b8))
* **ruler:** CQ-3.4 fixes — touch index guard + multitouch panel commit + touchcancel passive ([5818146](https://github.com/cameronzucker/geographica/commit/581814602bcab9dc530f65fcddfdca849e2846ea))
* **ruler:** CQ-3.5 cleanups + plan lockstep — tighter test tolerance + comment + plan sync ([1b885f6](https://github.com/cameronzucker/geographica/commit/1b885f68c32c97d9fbaf2210e188340653940048))
* **ruler:** defer source/layer init, fix tab-active detection, add idle hint ([17f64a6](https://github.com/cameronzucker/geographica/commit/17f64a66acd8f6c865188cc10af5be498593b6e6))
* **ruler:** empty Measure tab showed stray banner — [hidden] overrides ([5013f31](https://github.com/cameronzucker/geographica/commit/5013f31dfa7fd38e8f218fd10e5b85efa3ec8084))
* **ruler:** explicit-activation model — button starts drawing, sidebar pinned ([eac9d9b](https://github.com/cameronzucker/geographica/commit/eac9d9b997cd39665f7c2b1f2fd4b25a3bea3881))
* **ruler:** extend body.ruler-active to editing state for drag-mouseup reliability ([681485f](https://github.com/cameronzucker/geographica/commit/681485f2d530499e2e6e8fef6a91b0b2322d21b3))
* **ruler:** Phase 0 cleanup — drop doubled hidden attr + add cache-buster ([b91225f](https://github.com/cameronzucker/geographica/commit/b91225f1f3fd0e63f4a0e5e04889cd45d23df715))
* **ruler:** reset view.lastClick in clearAll + name debounce constants ([868e4b9](https://github.com/cameronzucker/geographica/commit/868e4b9313052e9412a0c05cea530bace777fba8))
* **ruler:** setHidden toggles class="hidden" too — surfaced by browser smoke ([cc877ec](https://github.com/cameronzucker/geographica/commit/cc877ecd2fa99d5a9785a29eb9d3b3809573b8bf))
* **ruler:** surgical body.ruler-active drag-only toggle — restores tap-outside-to-close in editing ([01266ec](https://github.com/cameronzucker/geographica/commit/01266ecd825c5774b8851f916a885d3a2b91e82b))
* **ruler:** tap-vs-drag tests — single-axis integer offsets match labels ([d849645](https://github.com/cameronzucker/geographica/commit/d849645efd87acccad9846ed3bb93d7c85ad4b44))
* **scripts:** align capture script to live frontend (admin URL, selectors, framing) ([2d741a2](https://github.com/cameronzucker/geographica/commit/2d741a2ecb9f953fe6ff3a244b4fa313ad998f33))
* **scripts:** capture full admin-pipeline page (cards extend below fold) ([8c93cca](https://github.com/cameronzucker/geographica/commit/8c93cca4aeb8c5a93d2c2fc9520e32e87a47ab2a))
* **scripts:** replicate showStep DOM mutation directly for setup-wizard ([003f6fb](https://github.com/cameronzucker/geographica/commit/003f6fb3dd2c75123faefb95d29a749a04d1db10))
* **scripts:** screenshot timeouts + sidebar opener for capture script ([f88ca34](https://github.com/cameronzucker/geographica/commit/f88ca345fad552c52fae48af2b12ce881d8362ff))
* **scripts:** setup-wizard advances to step 3 + dark color-scheme ([385b4a3](https://github.com/cameronzucker/geographica/commit/385b4a3618282e3f23d5448c6b2902a6ecdde946))
* **scripts:** symmetric framing for imagery-before-after composite ([6351fd4](https://github.com/cameronzucker/geographica/commit/6351fd4189372eeee8a2687962da0b0e95d3ff59))
* **scripts:** T5.1 review fixes — selectors, deps, comment hygiene ([a809ac5](https://github.com/cameronzucker/geographica/commit/a809ac5e80db1a7cbd725fcc96efb5e15bbfdca8))
* **setup:** update stale STATE_BBOXES location in error message ([519790c](https://github.com/cameronzucker/geographica/commit/519790c9b6af3fae125950af5ed3a59f2adbf474))
* **sidebar:** persist last-selected tab across open/close ([f1687df](https://github.com/cameronzucker/geographica/commit/f1687dfd4c96ab604c673248e25c7c31e724b6c3))
* **sidebar:** restore saved tab on every sidebar-open (Scenario A) ([aff590a](https://github.com/cameronzucker/geographica/commit/aff590a6d0c5394eb19094524ffc3c9099fc98ae))
* **tests:** broaden wake-lock cache-buster regex to accept slug suffix ([80392d8](https://github.com/cameronzucker/geographica/commit/80392d89e48189ae397ecf80c40ee74eedeeb064))


### Refactors

* **common:** extract STATE_BBOXES to scripts/common ([cc03d42](https://github.com/cameronzucker/geographica/commit/cc03d42004765a258672d3cbed0f48ade65aa0e8))
* **nav:** closes B1, removes 2026-04-20 band-aid (e63f6d9) ([9a3836d](https://github.com/cameronzucker/geographica/commit/9a3836dfc2ff1bdd58d7a6811451bc46ff220209))
* **nav:** convert initial route fetch to setActiveRoute (B2 prep) ([a8cd7ba](https://github.com/cameronzucker/geographica/commit/a8cd7ba1bb291655d08d3e24d158511d266ff96b))
* **nav:** delete announce() helper and lastAnnouncementTime state ([d3f05fe](https://github.com/cameronzucker/geographica/commit/d3f05fe91076523012e357629cf10cb75fd6016d))
* **nav:** extract setActiveRoute as single source of truth (B2 prep) ([2c03471](https://github.com/cameronzucker/geographica/commit/2c03471d37422c6ae620dd9165a3df85cff73142))
* **nav:** remove band-aid constants + rewrite internals hook ([414a387](https://github.com/cameronzucker/geographica/commit/414a3870b16f9bcd529c5c3d5094458483526ee1))
* **overview:** final-review doc cleanup ([5705062](https://github.com/cameronzucker/geographica/commit/57050628a2b496a267b50e668c38c365d67371fe))
* **ruler:** apply Task 0.1 code-review fixes (I1 + M1 + M3) ([ef401bb](https://github.com/cameronzucker/geographica/commit/ef401bb7d6519e35d002bdffddac89b2cf7458ec))
* **ruler:** drop teardownSourcesAndLayers — spec §A says no teardown() ([8e1b5b3](https://github.com/cameronzucker/geographica/commit/8e1b5b377cd4a9a1d72912b703b5764e22a4e277))
* **test-nav:** rename fixture to match expanded 3-maneuver content ([adf2796](https://github.com/cameronzucker/geographica/commit/adf27969378902978146c60110f6e67fa00d84a3))
* **voice-picker:** collapse buttons + dropdown into unified select ([97922b8](https://github.com/cameronzucker/geographica/commit/97922b8926bc3c12d01e4e1a3784ca5d9cedcdc7))

## [Unreleased]

### Added

- **Nav voice picker** — Preferences sidebar section with Default / Male / Female gender quick-pick and an advanced disclosure for picking a specific installed voice. Cloud voices are filtered out by default for offline-reliability; opt-in via a labeled checkbox. Per-device localStorage. Hard-refresh (Ctrl/Cmd-Shift-R) once after upgrade.
- Screen keep-awake during active navigation — prevents phone auto-dim/auto-lock from silently stopping nav on mobile. Uses the Screen Wake Lock API on HTTPS, and a first-party silent-video fallback (`SilentVideoLock`) on plain HTTP (AREDN mesh, Pi-hotspot, LAN). No UI change; the existing nav banner is the evidence that keep-awake is active.
  - **Known limitation:** On iOS, Low Power Mode may disable screen keep-awake. Disable Low Power Mode or keep the phone plugged in for uninterrupted navigation.

## [1.5.3](https://github.com/cameronzucker/geographica/compare/v1.5.2...v1.5.3) (2026-04-20)


### Bug Fixes

* **pipeline:** use public catalog endpoint for PAD-US download ([1f597aa](https://github.com/cameronzucker/geographica/commit/1f597aaf866c8d97e45cf00a9f186e35fdf4af07))

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
