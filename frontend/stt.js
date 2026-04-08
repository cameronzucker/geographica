/* =====================================================================
   Geographica STT — Voice Search Module
   =====================================================================
   Push-to-hold mic button captures audio via AudioWorklet, resamples to
   16kHz using OfflineAudioContext, encodes as 16-bit PCM WAV, sends to
   POST /stt/transcribe, and feeds the result into spatial search.

   Exports: initSTT(onResult)
   ===================================================================== */

(function () {
  'use strict';

  // =====================================================================
  //  CONSTANTS
  // =====================================================================

  var TARGET_SAMPLE_RATE = 16000;
  var MAX_RECORDING_S = 15;
  var MIN_RECORDING_S = 0.5;
  var STT_ENDPOINT = '/stt/transcribe';

  // =====================================================================
  //  STATE
  // =====================================================================

  var audioContext = null;
  var workletNode = null;
  var mediaStream = null;
  var mediaSource = null;

  var isRecording = false;
  var recordingStartTime = 0;
  var recordingTimerId = null;

  var micButton = null;
  var searchInput = null;
  var onResultCallback = null;

  // =====================================================================
  //  MIC BUTTON CREATION (DOM methods, no innerHTML)
  // =====================================================================

  function _createMicSvg() {
    var svgNS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '24');
    svg.setAttribute('height', '24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('aria-hidden', 'true');

    // Microphone body
    var path1 = document.createElementNS(svgNS, 'path');
    path1.setAttribute('fill', 'currentColor');
    path1.setAttribute('d', 'M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z');
    svg.appendChild(path1);

    // Microphone stand/base
    var path2 = document.createElementNS(svgNS, 'path');
    path2.setAttribute('fill', 'currentColor');
    path2.setAttribute('d', 'M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z');
    svg.appendChild(path2);

    return svg;
  }

  function _createMicButton() {
    micButton = document.createElement('button');
    micButton.id = 'stt-mic-button';
    micButton.type = 'button';
    micButton.title = 'Hold to record voice search';
    micButton.setAttribute('aria-label', 'Voice search');

    // Style
    micButton.style.cssText = [
      'width: 56px',
      'height: 56px',
      'border-radius: 50%',
      'border: 2px solid #ccc',
      'background: #fff',
      'color: #555',
      'cursor: pointer',
      'display: flex',
      'align-items: center',
      'justify-content: center',
      'padding: 0',
      'margin-left: 8px',
      'touch-action: none',
      'user-select: none',
      '-webkit-user-select: none',
      'position: relative',
      'flex-shrink: 0',
      'transition: background 0.15s, border-color 0.15s, color 0.15s'
    ].join('; ');

    // Append SVG icon
    var svg = _createMicSvg();
    micButton.appendChild(svg);

    // Insert next to the search input
    searchInput = document.getElementById('search-input');
    if (searchInput && searchInput.parentNode) {
      searchInput.parentNode.appendChild(micButton);
    }

    return micButton;
  }

  // =====================================================================
  //  UX STATES
  // =====================================================================

  function _setIdle() {
    if (!micButton) return;
    micButton.style.background = '#fff';
    micButton.style.borderColor = '#ccc';
    micButton.style.color = '#555';
    micButton.disabled = false;
    // Restore SVG icon
    while (micButton.firstChild) {
      micButton.removeChild(micButton.firstChild);
    }
    micButton.appendChild(_createMicSvg());
  }

  function _setRecording() {
    if (!micButton) return;
    micButton.style.background = '#e53935';
    micButton.style.borderColor = '#c62828';
    micButton.style.color = '#fff';

    // Show recording indicator
    while (micButton.firstChild) {
      micButton.removeChild(micButton.firstChild);
    }

    // Red dot + "REC" text
    var dot = document.createElement('span');
    dot.style.cssText = 'display:inline-block;width:10px;height:10px;border-radius:50%;background:#fff;margin-right:4px;animation:stt-pulse 1s infinite';
    micButton.appendChild(dot);

    // Add pulse animation if not already present
    if (!document.getElementById('stt-keyframes')) {
      var style = document.createElement('style');
      style.id = 'stt-keyframes';
      style.textContent = '@keyframes stt-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }';
      document.head.appendChild(style);
    }
  }

  function _setTranscribing() {
    if (!micButton) return;
    micButton.style.background = '#1976d2';
    micButton.style.borderColor = '#1565c0';
    micButton.style.color = '#fff';
    micButton.disabled = true;

    while (micButton.firstChild) {
      micButton.removeChild(micButton.firstChild);
    }

    // Spinner
    var spinner = document.createElement('span');
    spinner.style.cssText = 'display:inline-block;width:20px;height:20px;border:3px solid rgba(255,255,255,0.3);border-top-color:#fff;border-radius:50%;animation:stt-spin 0.8s linear infinite';
    micButton.appendChild(spinner);

    if (!document.getElementById('stt-spin-keyframes')) {
      var style = document.createElement('style');
      style.id = 'stt-spin-keyframes';
      style.textContent = '@keyframes stt-spin { to { transform: rotate(360deg); } }';
      document.head.appendChild(style);
    }
  }

  function _setDisabled(reason) {
    if (!micButton) return;
    micButton.style.background = '#e0e0e0';
    micButton.style.borderColor = '#bdbdbd';
    micButton.style.color = '#9e9e9e';
    micButton.disabled = true;
    micButton.title = reason || 'Voice search unavailable';
  }

  function _updateSearchInput(text) {
    if (searchInput) {
      searchInput.value = text;
    }
  }

  // =====================================================================
  //  TOAST NOTIFICATIONS
  // =====================================================================

  function _showToast(message, durationMs) {
    var existing = document.getElementById('stt-toast');
    if (existing) {
      existing.parentNode.removeChild(existing);
    }

    var toast = document.createElement('div');
    toast.id = 'stt-toast';
    toast.textContent = message;
    toast.style.cssText = [
      'position: fixed',
      'bottom: 80px',
      'left: 50%',
      'transform: translateX(-50%)',
      'background: rgba(0,0,0,0.8)',
      'color: #fff',
      'padding: 10px 20px',
      'border-radius: 8px',
      'font-size: 14px',
      'z-index: 10000',
      'pointer-events: none',
      'transition: opacity 0.3s',
      'opacity: 1'
    ].join('; ');

    document.body.appendChild(toast);

    setTimeout(function () {
      toast.style.opacity = '0';
      setTimeout(function () {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    }, durationMs || 3000);
  }

  // =====================================================================
  //  AUDIO CAPTURE
  // =====================================================================

  function _initAudioContext() {
    if (audioContext) return Promise.resolve();

    return navigator.mediaDevices.getUserMedia({ audio: true })
      .then(function (stream) {
        mediaStream = stream;
        audioContext = new AudioContext();
        return audioContext.audioWorklet.addModule('stt-worklet.js');
      })
      .then(function () {
        mediaSource = audioContext.createMediaStreamSource(mediaStream);
        workletNode = new AudioWorkletNode(audioContext, 'stt-processor');
        mediaSource.connect(workletNode);
        // Don't connect to destination — we don't want playback
      });
  }

  // =====================================================================
  //  WAV ENCODING
  // =====================================================================

  function _resampleTo16kHz(samples, originalRate) {
    // Use OfflineAudioContext for proper anti-aliased resampling
    var duration = samples.length / originalRate;
    var targetLength = Math.ceil(duration * TARGET_SAMPLE_RATE);
    var offlineCtx = new OfflineAudioContext(1, targetLength, TARGET_SAMPLE_RATE);
    var buffer = offlineCtx.createBuffer(1, samples.length, originalRate);
    buffer.getChannelData(0).set(samples);
    var source = offlineCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(offlineCtx.destination);
    source.start(0);
    return offlineCtx.startRendering().then(function (renderedBuffer) {
      return renderedBuffer.getChannelData(0);
    });
  }

  function _encodeWav(float32Samples) {
    // Convert Float32 [-1.0, 1.0] to Int16 [-32768, 32767]
    var numSamples = float32Samples.length;
    var dataSize = numSamples * 2; // 16-bit = 2 bytes per sample
    var bufferSize = 44 + dataSize; // 44-byte WAV header + data
    var buffer = new ArrayBuffer(bufferSize);
    var view = new DataView(buffer);

    // RIFF header
    _writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true); // file size - 8
    _writeString(view, 8, 'WAVE');

    // fmt chunk
    _writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);           // chunk size
    view.setUint16(20, 1, true);            // PCM format
    view.setUint16(22, 1, true);            // mono
    view.setUint32(24, TARGET_SAMPLE_RATE, true); // sample rate
    view.setUint32(28, TARGET_SAMPLE_RATE * 2, true); // byte rate
    view.setUint16(32, 2, true);            // block align
    view.setUint16(34, 16, true);           // bits per sample

    // data chunk
    _writeString(view, 36, 'data');
    view.setUint32(40, dataSize, true);

    // PCM samples — little-endian 16-bit
    var offset = 44;
    for (var i = 0; i < numSamples; i++) {
      var s = Math.max(-1, Math.min(1, float32Samples[i]));
      var val = s < 0 ? s * 32768 : s * 32767;
      view.setInt16(offset, val, true); // true = little-endian
      offset += 2;
    }

    return new Blob([buffer], { type: 'audio/wav' });
  }

  function _writeString(view, offset, str) {
    for (var i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  // =====================================================================
  //  RECORDING CONTROL
  // =====================================================================

  function _startRecording() {
    if (isRecording) return;
    isRecording = true;
    recordingStartTime = Date.now();

    _setRecording();
    _updateSearchInput('Recording...');

    // Tell the worklet to start accumulating
    workletNode.port.postMessage({ command: 'start' });

    // Update the search input with elapsed time
    recordingTimerId = setInterval(function () {
      var elapsed = ((Date.now() - recordingStartTime) / 1000).toFixed(1);
      _updateSearchInput('Recording... ' + elapsed + 's');

      // Auto-stop at MAX_RECORDING_S
      if (parseFloat(elapsed) >= MAX_RECORDING_S) {
        _stopRecording();
      }
    }, 100);
  }

  function _stopRecording() {
    if (!isRecording) return;
    isRecording = false;

    if (recordingTimerId) {
      clearInterval(recordingTimerId);
      recordingTimerId = null;
    }

    var elapsed = (Date.now() - recordingStartTime) / 1000;

    if (elapsed < MIN_RECORDING_S) {
      _setIdle();
      _updateSearchInput('');
      _showToast('Hold longer to record', 2000);
      // Tell worklet to discard
      workletNode.port.postMessage({ command: 'stop' });
      // Discard the message that will come back
      workletNode.port.onmessage = function () {
        workletNode.port.onmessage = _onWorkletMessage;
      };
      return;
    }

    _setTranscribing();
    _updateSearchInput('Transcribing...');

    // Tell the worklet to stop and send accumulated audio
    workletNode.port.postMessage({ command: 'stop' });
  }

  function _onWorkletMessage(event) {
    if (event.data.command !== 'audio_data') return;

    var rawSamples = new Float32Array(event.data.samples);
    var nativeRate = audioContext.sampleRate;

    // Resample to 16kHz using OfflineAudioContext
    _resampleTo16kHz(rawSamples, nativeRate)
      .then(function (resampled) {
        var wavBlob = _encodeWav(resampled);

        // Check size
        if (wavBlob.size > 1024 * 1024) {
          _setIdle();
          _updateSearchInput('');
          _showToast('Recording too long', 3000);
          return;
        }

        return _sendToSTT(wavBlob);
      })
      .catch(function (err) {
        console.error('[STT] Resampling error:', err);
        _setIdle();
        _updateSearchInput('');
        _showToast('Audio processing error', 3000);
      });
  }

  // =====================================================================
  //  STT API
  // =====================================================================

  function _sendToSTT(wavBlob) {
    var formData = new FormData();
    formData.append('audio', wavBlob, 'recording.wav');

    return fetch(STT_ENDPOINT, {
      method: 'POST',
      body: formData,
    })
      .then(function (resp) {
        if (resp.status === 413) {
          throw new Error('Recording too long');
        }
        if (resp.status === 422) {
          throw new Error('Audio format error');
        }
        if (resp.status === 502) {
          throw new Error('Voice search unavailable');
        }
        if (resp.status === 503) {
          throw new Error('Voice search error');
        }
        if (resp.status === 504) {
          throw new Error('Transcription timed out');
        }
        if (!resp.ok) {
          throw new Error('STT request failed (' + resp.status + ')');
        }
        return resp.json();
      })
      .then(function (data) {
        _setIdle();

        if (data.truncated) {
          _showToast('Only first 15s used', 3000);
        }

        if (!data.text || data.reason === 'no_speech') {
          _updateSearchInput('');
          _showToast("Didn't catch that, try again", 3000);
          return;
        }

        if (data.reason === 'too_short') {
          _updateSearchInput('');
          _showToast('Hold longer to record', 2000);
          return;
        }

        // Success — populate search and trigger callback
        _updateSearchInput(data.text);

        if (onResultCallback) {
          onResultCallback(data.text);
        }
      })
      .catch(function (err) {
        console.error('[STT] Error:', err);
        _setIdle();
        _updateSearchInput('');
        _showToast(err.message || 'Voice search error', 3000);
      });
  }

  // =====================================================================
  //  POINTER EVENT HANDLERS (push-to-hold)
  // =====================================================================

  function _onPointerDown(e) {
    e.preventDefault();
    // Capture pointer so pointerup fires even if finger drifts off button
    micButton.setPointerCapture(e.pointerId);
    _initAudioContext()
      .then(function () {
        // Set up worklet message handler
        workletNode.port.onmessage = _onWorkletMessage;
        _startRecording();
      })
      .catch(function (err) {
        console.error('[STT] Audio init error:', err);
        if (err.name === 'NotAllowedError') {
          _setDisabled('Mic access denied');
          _showToast('Mic access denied', 3000);
        } else if (err.name === 'NotFoundError') {
          _setDisabled('No microphone detected');
          _showToast('No microphone detected', 3000);
        } else {
          _showToast('Mic initialization error', 3000);
        }
      });
  }

  function _onPointerUp(e) {
    e.preventDefault();
    _stopRecording();
  }

  // =====================================================================
  //  INITIALIZATION
  // =====================================================================

  /**
   * Initialize the STT module.
   *
   * @param {function(string)} onResult - Callback with transcribed text.
   *   Called when transcription succeeds with non-empty text.
   *   The caller should use this text to trigger spatial search.
   */
  function initSTT(onResult) {
    onResultCallback = onResult;

    // Check for required browser APIs
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      console.warn('[STT] getUserMedia not available — mic button disabled');
      return;
    }

    if (typeof AudioWorkletNode === 'undefined') {
      console.warn('[STT] AudioWorklet not available — mic button disabled');
      return;
    }

    if (typeof OfflineAudioContext === 'undefined') {
      console.warn('[STT] OfflineAudioContext not available — mic button disabled');
      return;
    }

    // Create the mic button
    _createMicButton();

    if (!micButton) {
      console.warn('[STT] Could not create mic button (search input not found)');
      return;
    }

    // Attach pointer event handlers
    micButton.addEventListener('pointerdown', _onPointerDown);
    micButton.addEventListener('pointerup', _onPointerUp);
    // Prevent context menu on long press
    micButton.addEventListener('contextmenu', function (e) {
      e.preventDefault();
    });

    console.log('[STT] Voice search initialized');
  }

  // Export
  window.initSTT = initSTT;

})();
