/* =====================================================================
   Geographica STT — AudioWorklet Processor
   =====================================================================
   Runs in the AudioWorklet scope (separate thread from main).
   Accumulates Float32 PCM samples during recording at the browser's
   native sample rate. The main thread handles resampling to 16kHz.
   ===================================================================== */

class SttProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._recording = false;
    this._chunks = [];
    this.port.onmessage = this._onMessage.bind(this);
  }

  _onMessage(event) {
    if (event.data.command === 'start') {
      this._recording = true;
      this._chunks = [];
    } else if (event.data.command === 'stop') {
      this._recording = false;
      // Concatenate all accumulated chunks into a single Float32Array
      var totalLength = 0;
      for (var i = 0; i < this._chunks.length; i++) {
        totalLength += this._chunks[i].length;
      }
      var result = new Float32Array(totalLength);
      var offset = 0;
      for (var j = 0; j < this._chunks.length; j++) {
        result.set(this._chunks[j], offset);
        offset += this._chunks[j].length;
      }
      this.port.postMessage({ command: 'audio_data', samples: result.buffer }, [result.buffer]);
      this._chunks = [];
    }
  }

  process(inputs, outputs, parameters) {
    if (this._recording && inputs[0] && inputs[0][0]) {
      // Copy the input samples — the buffer is reused by the audio system
      var channelData = inputs[0][0];
      var copy = new Float32Array(channelData.length);
      copy.set(channelData);
      this._chunks.push(copy);
    }
    // Return true to keep the processor alive
    return true;
  }
}

registerProcessor('stt-processor', SttProcessor);
