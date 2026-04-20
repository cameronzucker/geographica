(function () {
  'use strict';
  if (window.VoicePicker) return; // duplicate-load guard

  var KNOWN_VOICES = {
    // Apple — iOS + macOS (post-tokenization)
    'Samantha': 'female', 'Karen': 'female', 'Moira': 'female', 'Tessa': 'female',
    'Victoria': 'female', 'Veena': 'female', 'Fiona': 'female',
    'Kate': 'female', 'Serena': 'female',
    'Alex': 'male', 'Daniel': 'male', 'Fred': 'male', 'Oliver': 'male',
    'Tom': 'male', 'Rishi': 'male', 'Aaron': 'male',
    // Microsoft — Edge on Windows
    'Zira': 'female', 'Hazel': 'female', 'Susan': 'female',
    'David': 'male', 'Mark': 'male', 'George': 'male', 'James': 'male'
  };

  function inferGender(rawName) {
    if (!rawName || typeof rawName !== 'string') return null;
    var name = rawName.replace(/^(Microsoft|Google|Apple|Siri)\s+/i, '');
    name = name.replace(/\s*\((?:Enhanced|Premium|Compact|Natural)\)\s*/gi, '');
    name = name.replace(/\s+(?:Desktop|Mobile)\b/gi, '');
    name = name.replace(/\s*-\s*English.*$/i, '');
    var firstToken = name.split(/[\s\-_]+/)[0];
    if (KNOWN_VOICES[firstToken]) return KNOWN_VOICES[firstToken];
    if (/\b(?:female|woman|girl)\b/i.test(rawName)) return 'female';
    if (/(?<!fe)\b(?:male|man|boy)\b/i.test(rawName)) return 'male';
    return null;
  }

  var voiceListFingerprint = '';
  var voiceListCallbacks = [];
  var bootstrapPrimedOnce = false;
  var bootstrapPollInterval = null;
  var bootstrapPollCount = 0;
  var BOOTSTRAP_POLL_MAX = 10;
  var BOOTSTRAP_POLL_MS = 500;

  var previewGeneration = 0;
  var activePreview = null;
  var previewArmed = false;
  var idleResetTimer = null;
  var debounceTimer = null;
  var IDLE_RESET_MS = 30000;
  var DEBOUNCE_MS = 150;

  var LS_KEY = 'nav-voice-pref';

  function readPref() {
    var raw;
    try { raw = window.localStorage.getItem(LS_KEY); } catch (e) { return { mode: 'default' }; }
    if (!raw) return { mode: 'default' };
    var parsed;
    try { parsed = JSON.parse(raw); } catch (e) { return { mode: 'default' }; }
    if (!parsed || parsed.version !== 1) return { mode: 'default' };
    return parsed;
  }

  function writePref(update) {
    var prev = readPref();
    if (prev.version !== 1) prev = {};  // start fresh if version mismatch
    var next = {
      mode: update.mode != null ? update.mode : (prev.mode || 'default'),
      gender: update.gender != null ? update.gender : (prev.gender || null),
      voice: update.voice !== undefined ? update.voice : (prev.voice || null),
      storedGenderHint: update.storedGenderHint !== undefined
        ? update.storedGenderHint
        : (update.voice && update.voice.name ? inferGender(update.voice.name) : (prev.storedGenderHint || null)),
      allowCloudVoices: update.allowCloudVoices !== undefined ? update.allowCloudVoices : (prev.allowCloudVoices || false),
      version: 1,
    };
    if (next.mode === 'gender' || next.mode === 'default') {
      next.voice = null;
      next.storedGenderHint = null;
    }
    try { window.localStorage.setItem(LS_KEY, JSON.stringify(next)); } catch (e) { /* quota, private mode */ }
    return next;
  }

  function candidateVoices(allowCloud) {
    var list;
    try { list = window.speechSynthesis.getVoices(); } catch (e) { return []; }
    if (!list || !list.length) return [];
    return list.filter(function (v) {
      if (!v || typeof v.lang !== 'string' || !/^en[-_]?/i.test(v.lang)) return false;
      if (!allowCloud && v.localService === false) return false;
      return true;
    }).sort(function (a, b) {
      // default voice first (stable tie-break), then alphabetical by voiceURI
      var aD = a.default ? 0 : 1, bD = b.default ? 0 : 1;
      if (aD !== bD) return aD - bD;
      return (a.voiceURI || '').localeCompare(b.voiceURI || '');
    });
  }

  function resolveVoice(pref, candidates) {
    if (pref.mode === 'default') return null;

    if (pref.mode === 'specific' && pref.voice) {
      var byURI = candidates.find(function (v) { return v.voiceURI === pref.voice.voiceURI; });
      if (byURI) return byURI;
      var byNameLang = candidates.find(function (v) {
        return v.name === pref.voice.name && v.lang === pref.voice.lang;
      });
      if (byNameLang) return byNameLang;
      if (pref.storedGenderHint) {
        var byHint = candidates.find(function (v) { return inferGender(v.name) === pref.storedGenderHint; });
        if (byHint) return byHint;
      }
      return null;
    }

    if (pref.mode === 'gender' && pref.gender) {
      return candidates.find(function (v) { return inferGender(v.name) === pref.gender; }) || null;
    }

    if (pref.mode === 'unavailable' && pref.voice) {
      var reappeared = candidates.find(function (v) { return v.voiceURI === pref.voice.voiceURI; });
      if (reappeared) return reappeared;
      return null;
    }

    return null;
  }

  function getUtteranceVoice() {
    var pref = readPref();
    var candidates = candidateVoices(pref.allowCloudVoices);
    var v = resolveVoice(pref, candidates);
    if (pref.mode === 'specific' && v === null && pref.voice) {
      writePref({ mode: 'unavailable', voice: pref.voice, storedGenderHint: pref.storedGenderHint });
    }
    return v;
  }

  function fingerprintVoices(list) {
    if (!list || !list.length) return '';
    return list.map(function (v) {
      return (v.voiceURI || '') + '|' + (v.name || '') + '|' + (v.lang || '');
    }).sort().join('\n');
  }

  function notifyVoiceListChanged() {
    var list;
    try { list = window.speechSynthesis.getVoices() || []; } catch (e) { list = []; }
    var fp = fingerprintVoices(list);
    if (fp === voiceListFingerprint) return;
    voiceListFingerprint = fp;
    voiceListCallbacks.forEach(function (cb) {
      try { cb(); } catch (e) { console.warn('[voice-picker] callback threw', e); }
    });
  }

  function isIOS() {
    try { return /iPad|iPhone|iPod/.test(window.navigator.userAgent); }
    catch (e) { return false; }
  }

  function bootstrapPrime() {
    if (bootstrapPrimedOnce) return;
    bootstrapPrimedOnce = true;
    try {
      var Utter = window.SpeechSynthesisUtterance || function (t) { this.text = t; };
      var u = new Utter(' ');
      u.volume = 0;
      window.speechSynthesis.speak(u);
    } catch (e) { /* autoplay policy may reject */ }
  }

  function bootstrapPollTick() {
    bootstrapPollCount++;
    notifyVoiceListChanged();
    if (voiceListFingerprint) {
      clearInterval(bootstrapPollInterval);
      bootstrapPollInterval = null;
      return;
    }
    if (bootstrapPollCount >= BOOTSTRAP_POLL_MAX) {
      clearInterval(bootstrapPollInterval);
      bootstrapPollInterval = null;
      if (isIOS()) {
        bootstrapPrime();
        bootstrapPollCount = 0;
        bootstrapPollInterval = setInterval(bootstrapPollTick, BOOTSTRAP_POLL_MS);
      } else {
        bootstrapTimeoutFired();
      }
    }
  }

  function bootstrapTimeoutFired() {
    var detecting = window.document && window.document.getElementById('pref-voice-detecting');
    var stub = window.document && window.document.getElementById('pref-voice-stub');
    var buttons = window.document && window.document.getElementById('pref-voice-buttons');
    if (detecting) detecting.classList.add('hidden');
    if (stub) stub.classList.remove('hidden');
    if (buttons) buttons.classList.add('hidden');
  }

  function formatPreviewPhrase() {
    var imperial = true;
    try {
      var checked = window.document.querySelector('input[name="units"]:checked');
      if (checked && checked.value === 'metric') imperial = false;
    } catch (e) {}
    return imperial
      ? 'In 500 feet, turn right onto Main Street.'
      : 'In 150 meters, turn right onto Main Street.';
  }

  function speakPreview() {
    try {
      if (window.document.body && window.document.body.classList.contains('nav-active')) return;
    } catch (e) {}
    try { window.speechSynthesis.cancel(); } catch (e) {}
    var myGen = ++previewGeneration;
    var Utter = window.SpeechSynthesisUtterance;
    var utt = new Utter(formatPreviewPhrase());
    utt.rate = 1.0;
    var v = getUtteranceVoice();
    if (v) { utt.voice = v; utt.lang = v.lang || 'en-US'; }
    else   { utt.lang = 'en-US'; }
    utt.onerror = function () { if (myGen === previewGeneration) activePreview = null; };
    activePreview = { utterance: utt, gen: myGen };
    try { window.speechSynthesis.speak(utt); } catch (e) { activePreview = null; }
  }

  function speakPreviewDebounced() {
    if (!previewArmed) return;
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () { debounceTimer = null; speakPreview(); }, DEBOUNCE_MS);
  }

  function armPreview() {
    previewArmed = true;
    if (idleResetTimer) clearTimeout(idleResetTimer);
    idleResetTimer = setTimeout(function () { previewArmed = false; idleResetTimer = null; }, IDLE_RESET_MS);
  }

  function onSidebarClose() {
    previewArmed = false;
    if (idleResetTimer) { clearTimeout(idleResetTimer); idleResetTimer = null; }
    if (activePreview !== null) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
      activePreview = null;
    }
  }

  function onVisibilityHidden() {
    if (activePreview !== null) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
      activePreview = null;
    }
  }

  function $(id) { try { return window.document.getElementById(id); } catch (e) { return null; } }

  function renderHint() {
    var hintEl = $('pref-voice-hint');
    if (!hintEl) return;
    var detectingEl = $('pref-voice-detecting');
    var stubEl = $('pref-voice-stub');
    if (detectingEl && !detectingEl.classList.contains('hidden')) { hintEl.classList.add('hidden'); return; }
    if (stubEl && !stubEl.classList.contains('hidden')) { hintEl.classList.add('hidden'); return; }
    var pref = readPref();
    var candidates = candidateVoices(pref.allowCloudVoices);
    if (pref.mode === 'unavailable' && pref.voice) {
      hintEl.textContent = 'Saved voice "' + pref.voice.name + '" is not installed on this device — using device default.';
      hintEl.classList.remove('hidden');
      return;
    }
    var effectiveGender = null;
    if (pref.mode === 'gender') effectiveGender = pref.gender;
    else if (pref.mode === 'specific' && pref.storedGenderHint) effectiveGender = pref.storedGenderHint;
    if (effectiveGender) {
      var match = candidates.find(function (v) { return inferGender(v.name) === effectiveGender; });
      if (!match) {
        var gLabel = effectiveGender === 'male' ? 'Male' : 'Female';
        hintEl.textContent = 'No ' + gLabel + ' voice detected on this device — using device default.';
        hintEl.classList.remove('hidden');
        return;
      }
    }
    if (isIOS() && candidates.length <= 3 && candidates.length > 0) {
      hintEl.textContent = 'Only a few voices detected. On iOS, add more via Settings → Accessibility → Spoken Content → Voices.';
      hintEl.classList.remove('hidden');
      return;
    }
    hintEl.classList.add('hidden');
  }

  function renderButtons() {
    var pref = readPref();
    var navActive = false;
    try { navActive = window.document.body.classList.contains('nav-active'); } catch (e) {}
    ['default', 'male', 'female'].forEach(function (g) {
      var btn = window.document && window.document.querySelector('.pref-voice-btn[data-gender="' + g + '"]');
      if (!btn) return;
      btn.disabled = navActive;
      if (navActive) btn.setAttribute('title', 'Voice can only be changed before or after navigation.');
      else btn.removeAttribute('title');
      var active = (pref.mode === 'default' && g === 'default') ||
                   (pref.mode === 'gender' && pref.gender === g);
      btn.classList.toggle('active', active);
    });
  }

  function renderDropdown() {
    var sel = $('pref-voice-select');
    if (!sel) return;
    var pref = readPref();
    var candidates = candidateVoices(pref.allowCloudVoices);
    while (sel.firstChild) sel.removeChild(sel.firstChild);
    candidates.forEach(function (v) {
      var opt = window.document.createElement('option');
      opt.value = v.voiceURI;
      opt.textContent = v.name + ' — ' + v.lang;
      if (pref.mode === 'specific' && pref.voice && pref.voice.voiceURI === v.voiceURI) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });
    var cb = $('pref-voice-allow-cloud');
    if (cb) cb.checked = !!pref.allowCloudVoices;
  }

  function onVoiceButtonClick(e) {
    var btn = e.currentTarget;
    var gender = btn.getAttribute('data-gender');
    if (btn.disabled) return;
    if (gender === 'default') writePref({ mode: 'default' });
    else writePref({ mode: 'gender', gender: gender });
    armPreview();
    rerenderPreferences();
    speakPreviewDebounced();
  }

  function onDropdownChange(e) {
    var sel = e.currentTarget;
    var candidates = candidateVoices(readPref().allowCloudVoices);
    var picked = candidates.find(function (v) { return v.voiceURI === sel.value; });
    if (!picked) return;
    writePref({
      mode: 'specific',
      voice: { voiceURI: picked.voiceURI, name: picked.name, lang: picked.lang },
    });
    armPreview();
    rerenderPreferences();
    speakPreviewDebounced();
  }

  function onCloudCheckboxChange(e) {
    writePref({ allowCloudVoices: e.currentTarget.checked });
    rerenderPreferences();
  }

  function onAdvancedToggleClick(e) {
    var toggle = e.currentTarget;
    var panel = $('pref-voice-advanced');
    if (!panel) return;
    var expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    panel.classList.toggle('hidden', expanded);
  }

  function wireDOMHandlers() {
    try {
      var buttons = window.document.querySelectorAll('.pref-voice-btn');
      buttons.forEach(function (btn) { btn.addEventListener('click', onVoiceButtonClick); });
      var sel = $('pref-voice-select');
      if (sel) sel.addEventListener('change', onDropdownChange);
      var cb = $('pref-voice-allow-cloud');
      if (cb) cb.addEventListener('change', onCloudCheckboxChange);
      var toggle = $('pref-voice-advanced-toggle');
      if (toggle) toggle.addEventListener('click', onAdvancedToggleClick);
    } catch (e) {}
  }

  function rerenderPreferences() {
    renderButtons();
    renderDropdown();
    renderHint();
  }

  function initBootstrap() {
    notifyVoiceListChanged();
    try {
      window.speechSynthesis.addEventListener('voiceschanged', notifyVoiceListChanged);
    } catch (e) {}
    notifyVoiceListChanged();
    if (voiceListFingerprint) return;
    var detecting = window.document && window.document.getElementById('pref-voice-detecting');
    if (detecting) detecting.classList.remove('hidden');
    bootstrapPollCount = 0;
    bootstrapPollInterval = setInterval(bootstrapPollTick, BOOTSTRAP_POLL_MS);
  }

  function initEventListeners() {
    try {
      window.document.addEventListener('geographica:sidebar', function (e) {
        if (!e.detail || !e.detail.open) onSidebarClose();
      });
      window.document.addEventListener('visibilitychange', function () {
        if (window.document.hidden) onVisibilityHidden();
      });
    } catch (e) {}
    try {
      window.addEventListener('storage', function (e) {
        if (!e || e.key !== LS_KEY) return;
        if (typeof window.VoicePicker._onStorageEventForTest === 'function') {
          window.VoicePicker._onStorageEventForTest(e);
        }
        rerenderPreferences();
      });
    } catch (e) {}
  }

  window.VoicePicker = {
    init: function () {
      initBootstrap();
      initEventListeners();
      wireDOMHandlers();
      rerenderPreferences();
      voiceListCallbacks.push(rerenderPreferences);
    },
    getUtteranceVoice: getUtteranceVoice,
    onVoiceListChanged: function (cb) {
      voiceListCallbacks.push(cb);
      if (voiceListFingerprint) { try { cb(); } catch (e) {} }
    },
    _inferGender: inferGender,
    _KNOWN_VOICES: KNOWN_VOICES,
    _readPref: readPref,
    _writePref: writePref,
    _LS_KEY: LS_KEY,
    _candidateVoices: candidateVoices,
    _resolveVoice: resolveVoice,
    _bootstrapPrime: bootstrapPrime,
    _bootstrapTimeoutFired: bootstrapTimeoutFired,
    _armPreview: armPreview,
    _speakPreview: speakPreview,
    _speakPreviewDebounced: speakPreviewDebounced,
    _activePreview: function () { return activePreview; },
    _isArmed: function () { return previewArmed; },
    _fireIdleTimer: function () {
      if (idleResetTimer) { clearTimeout(idleResetTimer); idleResetTimer = null; }
      previewArmed = false;
    },
    _onSidebarClose: onSidebarClose,
    _onVisibilityHidden: onVisibilityHidden,
  };
})();
