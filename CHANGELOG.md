# Changelog

All notable changes to Geographica are documented here.

This project adheres to [Semantic Versioning](https://semver.org) with
project-specific rules described in [VERSIONING.md](VERSIONING.md). Entries
from v1.1.0 onward are generated automatically by `release-please` from
Conventional Commits.

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
