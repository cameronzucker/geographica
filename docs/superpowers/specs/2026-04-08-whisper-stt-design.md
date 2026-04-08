# Phase 2b: Whisper STT on Hailo 10H NPU

**Date:** 2026-04-08
**Status:** Design approved
**Author:** Cameron Zucker + Claude
**Depends on:** Phase 2a natural language spatial search (complete)

## Overview

Add offline speech-to-text to Geographica so users can voice-search while wearing gloves or driving. A push-to-hold mic button in the browser captures audio, sends it to a new STT service for transcription via OpenAI Whisper, and feeds the resulting text into the existing `POST /search/spatial` endpoint.

The STT service supports two inference backends — CPU (faster-whisper/CTranslate2) and NPU (HailoRT on Hailo 10H) — selectable via environment variable. The CPU backend ships immediately. The NPU backend is developed in parallel, contingent on compatibility testing of Hailo 5.2.0 Whisper HEF files on the current 5.1.1 firmware.

## Use case

Primary scenario: operator in the field with gloved hands. Typing is impractical, but tapping and holding a large mic button is doable. Short spatial queries like "gas stations near me" or "hospitals along my route" are transcribed and fed into the spatial search pipeline.

Secondary scenario: hands-free while driving. Same push-to-hold interaction.

## Architecture

### System data flow

```
Browser (HTTPS)
  [Mic Button] ──press+hold──► AudioWorklet (16kHz mono PCM)
       │                              │
       │ release                      │ WAV blob
       ▼                              ▼
  POST /stt/transcribe ◄──── audio payload (WAV, ≤1MB)
       │
       │ response: {text: "gas stations near me",
       │            backend: "cpu", duration_ms: 2847}
       ▼
  POST /search/spatial ◄──── text + gps_position + route_coords
       │
       │ response: {results: [...], intent: "proximity", ...}
       ▼
  Render numbered pins + result list
```

### Two-step frontend flow

The frontend makes two sequential HTTP requests:

1. `POST /stt/transcribe` with WAV audio → receives `{text}`
2. `POST /search/spatial` with transcribed text + GPS position + route geometry → receives search results

This keeps the STT service decoupled from spatial search. The STT service has no knowledge of GPS, routes, or map state. The spatial search endpoint remains unchanged from Phase 2a.

### Service topology

```
                    NGINX (:8093 HTTP / :443 HTTPS)
                    ├── /stt/        → stt:8000
                    ├── /search/     → search:8000
                    ├── /tiles/      → tileserver:8080
                    ├── /route/      → valhalla:8002
                    ├── /nominatim/  → nominatim:8080
                    └── /gps/        → gps:8000
```

The STT service is a new standalone Docker container on port 8098 (host) / 8000 (container). It is independent of all other services — no `depends_on` constraints.

## STT service

### Container structure

```
services/stt/
  Dockerfile          # Python 3.11-slim + faster-whisper + hailo deps
  main.py             # FastAPI: POST /transcribe, GET /health (NGINX adds /stt/ prefix)
  backends/
    __init__.py       # TranscribeResult dataclass, backend protocol
    cpu.py            # faster-whisper (CTranslate2, INT8)
    npu.py            # HailoRT (loads HEF from /data/models/)
  requirements.txt    # faster-whisper, fastapi, uvicorn, numpy
```

### Backend interface

Both backends implement the same contract:

```python
@dataclass
class TranscribeResult:
    text: str
    duration_ms: int

def load_model(model_path: str) -> None:
    """Load model weights into memory. Called once at startup."""
    ...

def transcribe(audio_pcm: np.ndarray, sample_rate: int) -> TranscribeResult:
    """Transcribe 16kHz mono PCM audio to text."""
    ...
```

At startup, `main.py` reads the `STT_BACKEND` environment variable, imports the corresponding backend module, and calls `load_model()`. The model stays loaded in memory for the life of the process.

### CPU backend (cpu.py)

- Uses `faster-whisper` with `WhisperModel("base.en", device="cpu", compute_type="int8")`
- INT8 quantization: best speed on ARM without significant accuracy loss
- Model files (~140MB) stored at `/data/models/faster-whisper-base.en/`
- Configure `no_speech_threshold=0.8` (higher than default 0.6) and `log_prob_threshold=-0.8` to aggressively filter silence/noise hallucinations. faster-whisper returns per-segment `no_speech_prob` and `avg_logprob` — if either exceeds threshold, return `{text: '', reason: 'no_speech'}` instead of the hallucinated text.
- First call after startup ~5s (CTranslate2 warmup); subsequent calls ~3s for 5s audio
- Model pre-download: the Dockerfile `RUN` step downloads the base.en CTranslate2 model during image build (`ct2-opus-mt-en-de` pattern). This ensures the container works offline immediately — no runtime network access needed. The downloaded model is baked into the image at `/opt/models/faster-whisper-base.en/`, and at startup, `main.py` checks `MODEL_PATH` env var first (for user-provided models in `/data/models/`), falling back to the baked-in path

### NPU backend (npu.py)

- Uses `hailo_platform` to load HEF file(s) from `/data/models/`
- Whisper encoder-decoder may be two separate HEFs (encoder + decoder) or one combined HEF depending on what Hailo provides
- Inference flow:
  1. Mel spectrogram: computed on CPU (numpy) from 16kHz PCM → 80-bin log-mel features
  2. Encoder: mel spectrogram → encoder hidden states (NPU inference)
  3. Decoder: autoregressive token generation using encoder states (NPU inference per token, greedy decoding on CPU)
- Token vocabulary and decoding logic use the `tiktoken` library with Whisper's multilingual tokenizer vocabulary. The tokenizer is small (~1MB) and bundled in the container image

### API endpoint

**POST /transcribe**

Request: `multipart/form-data` with field name `audio` containing a WAV file. The frontend sends this to `/stt/transcribe` — NGINX strips the `/stt/` prefix before proxying.

Response (200):
```json
{
  "text": "gas stations near me",
  "backend": "cpu",
  "duration_ms": 2847
}
```

Response (200, no speech detected):
```json
{
  "text": "",
  "reason": "no_speech",
  "backend": "cpu",
  "duration_ms": 412
}
```

**GET /health**

Response:
```json
{
  "status": "ok",
  "backend": "cpu",
  "model": "base.en",
  "npu_available": false
}
```

### Request validation

| Check | Limit | Error |
|-------|-------|-------|
| File size | 1 MB max | 413 |
| WAV format | 16kHz, mono, 16-bit PCM | 422 |
| Duration | 15 seconds max (truncated) | 200 with `{truncated: true}` — frontend shows 'Only first 15s used' |
| Too short | < 0.5 seconds | 200 with `{text: "", reason: "too_short"}` |

The frontend auto-stops recording at 15s, so server-side truncation is a safety net. The `truncated` flag lets the frontend warn the user.

### docker-compose.yml

```yaml
stt:
  build:
    context: ./services/stt
  container_name: geographica-stt
  restart: unless-stopped
  ports:
    - "8098:8000"
  environment:
    STT_BACKEND: "${STT_BACKEND:-cpu}"
    MODEL_PATH: "/data/models"
  volumes:
    - ./data:/data
  # devices:
  #   - "/dev/hailo0:/dev/hailo0"  # Uncomment or use docker-compose.hailo.yml
  deploy:
    resources:
      limits:
        memory: 1536M
  healthcheck:
    test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 30s
```

- 1.5GB memory limit: accommodates base.en model (~140MB) + CTranslate2 runtime + peak inference buffers (~400-600MB for attention matrices). NPU backend may need 2GB — adjust when switching to STT_BACKEND=npu.
- No `depends_on` — STT is independent of all other services

### Hailo device passthrough

Create a `docker-compose.hailo.yml` override file that adds the device mapping:

```yaml
services:
  stt:
    devices:
      - "/dev/hailo0:/dev/hailo0"
```

Use `docker compose -f docker-compose.yml -f docker-compose.hailo.yml up` when Hailo hardware is present. The STT container starts fine without the device — the CPU backend ignores it.

Also add `stt` to the `frontend` service's `depends_on` list (no health condition — just ensures the container is on the Docker network for NGINX DNS resolution).

## Frontend

### New module: frontend/stt.js

A new ~200-300 line module that handles audio capture and the mic button UX. Keeps STT logic out of the already-large `app.js` (~2800 lines).

Exports:
- `initSTT(onResult)` — requests mic permission, sets up AudioWorklet, creates mic button
- Calls `onResult(text)` when transcription completes

The AudioWorklet processor runs in a separate JS file (`frontend/stt-worklet.js`) loaded via `audioContext.audioWorklet.addModule()`. This file runs in the AudioWorklet scope and cannot share code with the main thread.

`app.js` calls `initSTT()` on startup and provides a callback that:
1. Populates the search input with the transcribed text
2. Fires `POST /search/spatial` with the text plus current GPS position and route coordinates from app state

### AudioWorklet resampling

```
getUserMedia({audio: true})
  → MediaStreamSource
    → AudioWorklet processor (resample to 16kHz, mono)
      → accumulate Float32 samples in array
        → on release: encode as 16-bit PCM WAV blob
          → POST /stt/transcribe
```

- Browser's native sample rate (typically 44.1kHz or 48kHz) is downsampled to 16kHz using the browser's OfflineAudioContext (which provides proper anti-aliased resampling). The AudioWorklet accumulates raw samples at native rate; on recording stop, an OfflineAudioContext at 16kHz renders the audio with the browser's built-in high-quality resampler, then encodes as WAV.
- Samples accumulate in a Float32Array buffer during recording
- On stop: convert Float32 to Int16, prepend WAV header, create Blob
- WAV encoding uses little-endian byte order (`dataView.setInt16(offset, sample, true)`)
- AudioWorklet chosen over ScriptProcessorNode (deprecated) for lower latency and off-main-thread processing

### UX states

| State | Search input | Mic button | Instruction |
|-------|-------------|------------|-------------|
| Idle | Normal text input | Mic icon | — |
| Recording | "Recording... 2.3s" with red dot | Pressed/active state | "Release to search" |
| Transcribing | "Transcribing..." with spinner | Disabled | — |
| Result | Transcribed text fills input | Normal | — |
| Error | Unchanged | Normal | Toast message |

### Push-to-hold interaction

- `pointerdown` on mic button → start recording, show recording state
- Uses `setPointerCapture()` on `pointerdown` to capture the pointer globally. Recording stops only on `pointerup` regardless of pointer position — prevents premature stop when gloved finger drifts off the button.
- Uses Pointer Events API (not touch/mouse) for unified input handling
- If recording duration < 0.5s on release, discard and show "Hold longer to record" toast
- If recording duration > 15s, auto-stop (the WAV would be truncated server-side anyway)

### Touch target sizing

Mic button: 56x56px starting point. Evaluate with actual gloved hands and adjust — this is a CSS-only change.

CSS `touch-action: none` and `user-select: none` on the mic button prevent browser default long-press behaviors (context menu, text selection) from interfering with push-to-hold.

### Mic permission handling

- HTTPS is required and already active (Tailscale TLS)
- First tap triggers browser permission dialog
- If denied: mic button shows disabled state with "Mic access denied" tooltip
- Permission grant is persistent per origin — one-time interaction

## NGINX configuration

Add to `nginx/nginx.conf`:

```nginx
location /stt/ {
    proxy_pass http://stt:8000/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    client_max_body_size 2m;
    proxy_read_timeout 30s;
}
```

NGINX strips the `/stt/` prefix — the FastAPI app defines routes at `/transcribe` and `/health` (no prefix).

- `client_max_body_size 2m`: generous ceiling above the 1MB server-side limit
- `proxy_read_timeout 30s`: headroom for cold start + longer utterances
- No `sub_filter` needed — STT responses are JSON without URLs to rewrite

## Error handling

| Layer | Error | Response | Frontend display |
|-------|-------|----------|-----------------|
| Browser | Mic permission denied | — | Disable button, "Mic access denied" tooltip |
| Browser | No microphone detected | — | Disable button, "No microphone detected" toast |
| Browser | Recording < 0.5s | — | "Hold longer to record" toast |
| NGINX | STT container down | 502 | "Voice search unavailable" toast |
| STT | Audio > 1MB | 413 | "Recording too long" toast |
| STT | Invalid WAV format | 422 | "Audio format error" toast |
| STT | Whisper returns empty | 200 `{text:"", reason:"no_speech"}` | "Didn't catch that, try again" toast |
| STT | Inference timeout > 15s | 504 | "Transcription timed out" toast |
| STT | NPU inference fails | 503 `{error:"npu_inference_failed"}` | "Voice search error" toast |
| Search | 0 results | Normal spatial response | Normal "no results" UX |

No silent fallback from NPU to CPU. If `STT_BACKEND=npu` and NPU inference fails, the service returns 503. This is intentional: the operator should know the NPU isn't working rather than silently degrading to slower CPU inference.

## NPU investigation strategy

### Context

Hailo's online model zoo lists Whisper models compiled for H10, but only in the 5.2.0 firmware catalog. The Pi 5 requires `hailo-10-all` for PCIe drivers, which is currently at 5.1.1. There is no hardware or firmware blocker — it is a package version lag.

### Investigation steps

1. **Obtain HEF files** — Cameron downloads Whisper Base HEF(s) for H10 from the Hailo 5.2.0 model zoo catalog. Place in `/srv/geographica/data/models/`.

2. **Probe compatibility** — Minimal Python script to test if the HEF loads on 5.1.1:
   ```python
   from hailo_platform import HEF, VDevice
   hef = HEF("/data/models/whisper_base_encoder_h10.hef")
   # Success = format compatible; exception = version mismatch
   ```

3. **Test inference** — If HEF loads, run a dummy inference pass with synthetic input (zeros). Verify output tensor shapes match expected Whisper dimensions.

4. **End-to-end test** — Feed a real WAV file through mel spectrogram → encoder → decoder. Compare transcription output to the same file run through `faster-whisper` on CPU.

5. **Benchmark** — Time NPU vs CPU on 3, 5, and 10 second utterances.

### Decision gate

| Outcome | Action |
|---------|--------|
| HEF loads, correct output, faster than CPU | Ship `STT_BACKEND=npu` as default, keep CPU backend as documented fallback |
| HEF loads, garbage output | Document artifacts, ship CPU, revisit at 5.2.0 |
| HEF won't load (version error) | Document exact error, ship CPU, revisit when `hailo-10-all` reaches 5.2.0 |
| Partial (encoder works, decoder fails) | Document, ship CPU — partial NPU is worse than full CPU |

### Effort boundary

Give the NPU investigation serious effort but don't spend hours on it. Use adversarial review and bug hunter skills if issues arise. If it becomes clear the version mismatch is a hard blocker, document findings and move on.

### What gets built regardless

The `npu.py` backend module is written either way — it is the skeleton code for loading HEF and running inference via HailoRT. If the 5.2.0 HEF doesn't work on 5.1.1, the code is ready for when the firmware catches up.

## Testing

### Unit tests

**`tests/test_stt.py`** — Service-level tests:
- WAV validation: reject non-WAV, wrong sample rate, wrong channels, too short, too large
- Backend dispatcher: correct backend selected based on env var
- Response shape: `{text, backend, duration_ms}` fields present and correctly typed
- Empty/silence handling: returns `{text: "", reason: "no_speech"}`

**`tests/test_stt_cpu.py`** — CPU backend tests:
- Model loads successfully from path
- Transcribes known test WAV to expected text
- INT8 quantization produces coherent output
- Edge cases: very short audio (~0.5s), very quiet audio

**`tests/test_stt_npu.py`** — NPU backend tests:
- Automatically skipped (`pytest.mark.skipif`) when `/dev/hailo0` absent or HEF files missing
- HEF loads without version error
- Encoder output tensor shape matches expected dimensions
- Full transcription matches expected text within Levenshtein distance threshold (NPU quantization may produce slightly different text than CPU)

### Integration tests

**`tests/test_stt_integration.py`**:
- POST known WAV to `/stt/transcribe`, verify text response
- Take returned text, POST to `/search/spatial` with mock GPS coords, verify results
- Validates the two-step pipeline without browser involvement

### Test fixture

`tests/fixtures/test_audio.wav` — 2-3 seconds of clear speech saying "gas stations near me" at 16kHz mono 16-bit PCM (~64KB). Committed to the repo. Used as ground truth by both CPU and NPU backend tests.

### Not tested (manual QA)

- AudioWorklet resampling in browser (requires real browser + mic)
- Push-to-hold timing and UX (requires actual gloved hands)
- NGINX proxy routing (covered by existing patterns, verified at deploy)

## Model storage

All model files live at `/srv/geographica/data/models/` (symlinked via `./data`), consistent with the project rule that large data stays outside the git repo.

```
/srv/geographica/data/models/
  faster-whisper-base.en/    # CTranslate2 model files (~140MB)
    config.json
    model.bin
    tokenizer.json
    vocabulary.txt
  whisper_base_encoder_h10.hef   # Hailo HEF (if available)
  whisper_base_decoder_h10.hef   # Hailo HEF (if available)
```

## Whisper model choice

**Model:** `base.en` (English-only, 74M parameters)

**Rationale:** Users will abandon a voice feature that misunderstands them. The `tiny.en` model (39M params, ~1s inference) has noticeably lower accuracy on noisy/accented speech. The `base.en` model (~3s inference on Pi 5 ARM) is accurate enough for short spatial queries that users will trust the feature and keep using it. The extra ~2s latency is acceptable for a search interaction.

**Quantization:** INT8 via CTranslate2 for the CPU backend. This provides the best speed on ARM without meaningful accuracy degradation for short utterances.
