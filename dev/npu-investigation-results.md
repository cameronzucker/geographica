# NPU Investigation Results: Whisper on Hailo 10H

**Date:** 2026-04-08
**Firmware:** HailoRT 5.1.1
**HEF Source:** Whisper-Base.hef from hailo-tappas-core resources (compiled for 5.3.0)
**HEF Path:** `/usr/local/hailo/resources/models/hailo10h/Whisper-Base.hef` (131MB)

## Finding: HEF loads but cannot execute on firmware 5.1.1

### What works

The HEF file format IS compatible — metadata parsing succeeds:

```
Network groups: ['base-whisper-decoder-10s-out-seq-64', 'base-whisper-encoder-10s']

Encoder (base-whisper-encoder-10s):
  Input:  (1, 1000, 80) UINT8  — 10s mel spectrogram (1000 frames x 80 mel bins)
  Output: (1, 500, 512) UINT8  — encoder hidden states

Decoder (base-whisper-decoder-10s-out-seq-64):
  Input1: (1, 500, 512) UINT8  — encoder output (cross-attention)
  Input2: (1, 64, 512) UINT8   — token embeddings (max 64 output tokens)
  Output: 4 tensors totaling (1, 64, 51865) — Whisper vocab logits split across 4 outputs
```

### What fails

`VDevice.configure()` fails with `HAILO_NOT_IMPLEMENTED` (status code 7):

```
hailo_platform.pyhailort.pyhailort.HailoRTException: 
  libhailort failed with error: 7 (HAILO_NOT_IMPLEMENTED)
```

The decoder network group triggers the failure first. The API configures all groups from a multi-group HEF simultaneously — individual group configuration is not possible.

### Interpretation

The HEF was compiled with Hailo Dataflow Compiler 5.3.0, which uses operations or execution modes not supported by the 5.1.1 runtime. This is expected — Hailo typically maintains forward compatibility (new runtime reads old HEFs) but not backward compatibility (old runtime reads new HEFs).

### Architecture insights (for future implementation)

The Whisper-Base HEF uses a non-autoregressive decoder design:
- Single forward pass produces all 64 output tokens simultaneously
- Causal masking is baked into the compiled model
- No token-by-token autoregressive loop needed
- Vocab logits split across 4 output tensors (12966 + 12966 + 12966 + 12967 = 51865)
- Token embedding matrix needed separately (input is pre-embedded UINT8, not token IDs)

### Decision

**Ship with CPU backend (faster-whisper base.en INT8).** The NPU backend skeleton code is written and ready. When `hailo-10-all` reaches 5.3.0 for the Pi 5:

1. `configure()` should succeed with the existing HEF
2. Implement mel spectrogram preprocessing (CPU numpy)
3. Wire encoder inference → decoder inference pipeline
4. Handle UINT8 quantization (scale/zero-point from the HEF)
5. Decode output logits to tokens via Whisper tokenizer

### Version tracking

| Component | Current | Required | Gap |
|-----------|---------|----------|-----|
| HailoRT firmware | 5.1.1 | 5.3.0 | 2 minor versions |
| hailo-10-all metapackage | 5.1.1 | 5.3.0 | Pi 5 PCIe driver lag |
| Whisper-Base.hef | 5.3.0 | N/A | Already on disk |
| npu.py skeleton | Written | Needs inference impl | Ready for 5.3.0 |
