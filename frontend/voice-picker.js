(function () {
  'use strict';
  if (window.VoicePicker) return; // duplicate-load guard

  window.VoicePicker = {
    init: function () {},
    getUtteranceVoice: function () { return null; },
    onVoiceListChanged: function (_callback) {},
  };
})();
