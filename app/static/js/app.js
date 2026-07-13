// GROWELL CLINIC — front-end interactions (no framework dependency).
(function () {
  "use strict";

  const prefersReduced = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  document.addEventListener("DOMContentLoaded", function () {
    initFlashDismiss();
    initScrollReveal();
    initCounters();
    initRipple();
  });

  // Auto-dismiss flash messages after a few seconds.
  function initFlashDismiss() {
    document.querySelectorAll(".flash").forEach(function (el) {
      setTimeout(function () {
        el.style.transition = "opacity 0.4s ease, transform 0.4s ease";
        el.style.opacity = "0";
        el.style.transform = "translateY(-8px)";
        setTimeout(function () { el.remove(); }, 420);
      }, 5000);
    });
  }

  // Reveal [data-reveal] elements as they scroll into view.
  function initScrollReveal() {
    const items = document.querySelectorAll("[data-reveal]");
    if (!items.length) return;
    if (prefersReduced || !("IntersectionObserver" in window)) {
      items.forEach(function (el) { el.classList.add("is-visible"); });
      return;
    }
    const obs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            obs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    items.forEach(function (el) { obs.observe(el); });
  }

  // Animate elements with [data-count] from 0 to their numeric target.
  function initCounters() {
    const counters = document.querySelectorAll("[data-count]");
    counters.forEach(function (el) {
      const target = parseFloat(el.getAttribute("data-count")) || 0;
      if (prefersReduced) { el.textContent = target; return; }
      const duration = 900;
      const start = performance.now();
      function tick(now) {
        const progress = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
        el.textContent = Math.round(target * eased);
        if (progress < 1) requestAnimationFrame(tick);
        else el.textContent = target;
      }
      requestAnimationFrame(tick);
    });
  }

  // Material-style ripple on .gc-ripple elements.
  function initRipple() {
    if (prefersReduced) return;
    document.querySelectorAll(".gc-ripple").forEach(function (el) {
      el.addEventListener("click", function (e) {
        const circle = document.createElement("span");
        const rect = el.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        circle.className = "ripple";
        circle.style.width = circle.style.height = size + "px";
        circle.style.left = e.clientX - rect.left - size / 2 + "px";
        circle.style.top = e.clientY - rect.top - size / 2 + "px";
        el.appendChild(circle);
        setTimeout(function () { circle.remove(); }, 600);
      });
    });
  }
})();

// Center-square crop for avatar uploads (data-crop="square" on a file input):
// draws the picked image centered onto a 512px square canvas and swaps the
// input's file for the cropped JPEG, so the stored photo looks right
// everywhere (lists, profile, print) instead of relying on CSS cropping.
window.gcCropSquare = function (input, done) {
  var file = input.files && input.files[0];
  if (!file || !file.type || file.type.indexOf("image/") !== 0) { if (done) done(); return; }
  if (file.type === "image/gif" || file.type === "image/svg+xml") { if (done) done(); return; }
  var img = new Image();
  var url = URL.createObjectURL(file);
  img.onload = function () {
    try {
      var side = Math.min(img.naturalWidth, img.naturalHeight);
      var sx = (img.naturalWidth - side) / 2;
      var sy = (img.naturalHeight - side) / 2;
      var size = Math.min(side, 512);
      var canvas = document.createElement("canvas");
      canvas.width = canvas.height = size;
      canvas.getContext("2d").drawImage(img, sx, sy, side, side, 0, 0, size, size);
      canvas.toBlob(function (blob) {
        if (blob) {
          var name = (file.name || "photo").replace(/\.[^.]+$/, "") + ".jpg";
          var dt = new DataTransfer();
          dt.items.add(new File([blob], name, { type: "image/jpeg" }));
          input.files = dt.files;
        }
        URL.revokeObjectURL(url);
        if (done) done();
      }, "image/jpeg", 0.9);
    } catch (e) { URL.revokeObjectURL(url); if (done) done(); }
  };
  img.onerror = function () { URL.revokeObjectURL(url); if (done) done(); };
  img.src = url;
};

document.addEventListener("change", function (e) {
  var input = e.target;
  if (input && input.matches && input.matches('input[type="file"][data-crop="square"]')) {
    window.gcCropSquare(input);
  }
});
