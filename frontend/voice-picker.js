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

  window.VoicePicker = {
    init: function () {},
    getUtteranceVoice: function () { return null; },
    onVoiceListChanged: function (_callback) {},
    _inferGender: inferGender,
    _KNOWN_VOICES: KNOWN_VOICES,
    _readPref: readPref,
    _writePref: writePref,
    _LS_KEY: LS_KEY,
  };
})();
