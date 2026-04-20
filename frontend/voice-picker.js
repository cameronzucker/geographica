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

  window.VoicePicker = {
    init: function () { initBootstrap(); },
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
  };
})();
