// GROWELL CLINIC — minimal front-end behaviour.
// Auto-dismiss flash messages after a few seconds.
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    const flashes = document.querySelectorAll(".flash");
    flashes.forEach(function (el) {
      setTimeout(function () {
        el.style.transition = "opacity 0.4s ease";
        el.style.opacity = "0";
        setTimeout(function () { el.remove(); }, 400);
      }, 5000);
    });
  });
})();
