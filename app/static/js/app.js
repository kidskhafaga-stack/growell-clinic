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

// ---------------------------------------------------------------------------
// Interactive avatar cropper (iOS-style): pick a photo → a modal shows it
// behind a circular mask; drag to reposition, slider (or wheel/pinch-drag)
// to zoom, ✓ crops the visible circle to a 512px JPEG and swaps it into the
// file input, ✕ cancels. Attach with data-crop="square" on the input, or call
// window.gcAvatarCrop(input, done) directly. No external dependencies.
(function () {
  var V = 320; // viewport square (CSS pixels)

  function buildModal() {
    var el = document.createElement("div");
    el.id = "gc-cropper";
    el.innerHTML =
      '<div class="gcc-backdrop"></div>' +
      '<div class="gcc-box" role="dialog" aria-modal="true">' +
      '  <div class="gcc-viewport"><img alt="" draggable="false"><div class="gcc-mask"></div></div>' +
      '  <div class="gcc-zoom"><span>−</span><input type="range"><span>+</span></div>' +
      '  <div class="gcc-actions">' +
      '    <button type="button" class="gcc-cancel" aria-label="cancel">✕</button>' +
      '    <button type="button" class="gcc-ok" aria-label="confirm">✓</button>' +
      "  </div></div>";
    var style = document.createElement("style");
    style.textContent =
      "#gc-cropper{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;}" +
      "#gc-cropper .gcc-backdrop{position:absolute;inset:0;background:rgba(15,23,32,.72);}" +
      "#gc-cropper .gcc-box{position:relative;background:var(--card,#fff);border-radius:18px;padding:18px;box-shadow:0 18px 60px rgba(0,0,0,.35);max-width:92vw;}" +
      "#gc-cropper .gcc-viewport{position:relative;width:" + V + "px;height:" + V + "px;max-width:80vw;max-height:80vw;overflow:hidden;border-radius:12px;background:#111;touch-action:none;cursor:grab;}" +
      "#gc-cropper .gcc-viewport img{position:absolute;top:0;left:0;transform-origin:0 0;user-select:none;pointer-events:none;max-width:none;}" +
      "#gc-cropper .gcc-mask{position:absolute;left:50%;top:50%;width:100%;height:100%;transform:translate(-50%,-50%);border-radius:50%;box-shadow:0 0 0 9999px rgba(0,0,0,.55);pointer-events:none;outline:2px dashed rgba(255,255,255,.75);outline-offset:-2px;}" +
      "#gc-cropper .gcc-zoom{display:flex;align-items:center;gap:10px;margin:14px 4px 4px;}" +
      "#gc-cropper .gcc-zoom span{font-size:1.2rem;font-weight:700;color:var(--muted,#5b6673);width:18px;text-align:center;}" +
      "#gc-cropper .gcc-zoom input{flex:1;accent-color:var(--primary,#198754);}" +
      "#gc-cropper .gcc-actions{display:flex;justify-content:space-between;margin-top:12px;}" +
      "#gc-cropper .gcc-actions button{width:52px;height:52px;border-radius:50%;border:none;font-size:1.35rem;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.18);}" +
      "#gc-cropper .gcc-cancel{background:#fff;color:#1a2330;}" +
      "#gc-cropper .gcc-ok{background:var(--primary,#198754);color:#fff;}";
    el.appendChild(style);
    document.body.appendChild(el);
    return el;
  }

  window.gcAvatarCrop = function (input, done) {
    var file = input.files && input.files[0];
    if (!file || !file.type || file.type.indexOf("image/") !== 0 ||
        file.type === "image/gif" || file.type === "image/svg+xml") {
      if (done) done(); return;
    }
    var modal = document.getElementById("gc-cropper") || buildModal();
    modal.style.display = "flex";
    var img = modal.querySelector("img");
    var slider = modal.querySelector('input[type="range"]');
    var viewport = modal.querySelector(".gcc-viewport");
    var url = URL.createObjectURL(file);
    var s = 1, tx = 0, ty = 0, minS = 1;

    function clamp() {
      var w = img.naturalWidth * s, h = img.naturalHeight * s;
      tx = Math.min(0, Math.max(V - w, tx));
      ty = Math.min(0, Math.max(V - h, ty));
    }
    function render() { img.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + s + ")"; }
    function close() {
      modal.style.display = "none";
      URL.revokeObjectURL(url);
      slider.oninput = null; viewport.onpointerdown = null;
      modal.querySelector(".gcc-ok").onclick = null;
      modal.querySelector(".gcc-cancel").onclick = null;
    }

    img.onload = function () {
      minS = V / Math.min(img.naturalWidth, img.naturalHeight);
      s = minS;
      tx = (V - img.naturalWidth * s) / 2;
      ty = (V - img.naturalHeight * s) / 2;
      slider.min = String(minS);
      slider.max = String(minS * 4);
      slider.step = String(minS / 50);
      slider.value = String(s);
      render();
    };
    img.src = url;

    slider.oninput = function () {
      var ns = parseFloat(slider.value) || minS;
      // Zoom around the viewport centre so the subject stays put.
      var c = V / 2;
      tx = c - ((c - tx) / s) * ns;
      ty = c - ((c - ty) / s) * ns;
      s = ns; clamp(); render();
    };

    viewport.onpointerdown = function (e) {
      e.preventDefault();
      viewport.setPointerCapture(e.pointerId);
      var sx = e.clientX - tx, sy = e.clientY - ty;
      viewport.style.cursor = "grabbing";
      viewport.onpointermove = function (m) {
        tx = m.clientX - sx; ty = m.clientY - sy; clamp(); render();
      };
      viewport.onpointerup = viewport.onpointercancel = function () {
        viewport.onpointermove = null; viewport.style.cursor = "grab";
      };
    };

    modal.querySelector(".gcc-cancel").onclick = function () {
      input.value = ""; close(); if (done) done();
    };
    modal.querySelector(".gcc-ok").onclick = function () {
      var out = 512;
      var canvas = document.createElement("canvas");
      canvas.width = canvas.height = out;
      canvas.getContext("2d").drawImage(
        img, (0 - tx) / s, (0 - ty) / s, V / s, V / s, 0, 0, out, out);
      canvas.toBlob(function (blob) {
        if (blob) {
          var name = (file.name || "photo").replace(/\.[^.]+$/, "") + ".jpg";
          var dt = new DataTransfer();
          dt.items.add(new File([blob], name, { type: "image/jpeg" }));
          input.files = dt.files;
        }
        close(); if (done) done();
      }, "image/jpeg", 0.9);
    };
  };

  document.addEventListener("change", function (e) {
    var input = e.target;
    if (input && input.matches && input.matches('input[type="file"][data-crop="square"]')) {
      window.gcAvatarCrop(input);
    }
  });
})();

// Live refresh: poll a cheap fingerprint endpoint and reload only when the
// data actually changed. Pauses while the tab is hidden or a form field is
// focused (so it never eats what the user is typing).
window.gcLivePoll = function (url, everyMs) {
  var last = null;
  var every = everyMs || 12000;
  function busy() {
    var el = document.activeElement;
    return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
  }
  setInterval(function () {
    if (document.hidden || busy()) return;
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.fp) return;
        if (last === null) { last = j.fp; return; }
        if (j.fp !== last) window.location.reload();
      })
      .catch(function () {});
  }, every);
};

// Double-submit guard: a second submit of the same form within a few seconds
// is dropped (double clicks on Collect/Save used to post payments twice).
document.addEventListener("submit", function (e) {
  var f = e.target;
  if (!f || f.method.toLowerCase() !== "post") return;
  if (f.__gcBusy) { e.preventDefault(); return; }
  f.__gcBusy = true;
  setTimeout(function () { f.__gcBusy = false; }, 4000);
}, true);

// Live *notice*: same fingerprint poll as gcLivePoll, but it never reloads —
// it raises a bar offering to.
//
// The difference is not a preference. gcLivePoll suits a board: read-only, so
// throwing the page away costs nothing. The patient file and the visit record
// carry eighteen forms each, and a doctor who has typed half a page and
// clicked away would lose it — the focus check only pauses while the caret is
// actually in a field.
//
// And reloading was never what was asked for. The complaint was "the admin
// didn't see it until they refreshed", which is a complaint about not being
// *told*. Being told is the whole fix; when to refresh is the reader's call,
// because only they know whether they are mid-sentence.
window.gcLiveNotify = function (url, opts) {
  var o = opts || {};
  var every = o.everyMs || 15000;
  var last = null;
  var shown = false;

  function bar() {
    if (shown) return;
    shown = true;
    var el = document.createElement("div");
    el.className = "gc-live-note";
    el.setAttribute("role", "status");
    el.innerHTML =
      '<span>' + (o.text || "This page has changed.") + "</span>" +
      '<button type="button">' + (o.action || "Refresh") + "</button>";
    el.querySelector("button").addEventListener("click", function () {
      window.location.reload();
    });
    document.body.appendChild(el);
  }

  setInterval(function () {
    if (document.hidden) return;
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.fp) return;
        if (last === null) { last = j.fp; return; }
        // Deliberately not updating `last` after showing the bar: further
        // edits should not make it flicker away and back.
        if (j.fp !== last) bar();
      })
      .catch(function () {});
  }, every);
};

// Live search: results follow the typing, with no Enter.
//
// Deliberately *not* a JSON API per screen. Every one of these lists is
// already rendered correctly on the server — translated, paginated, permission
// checked — and rebuilding that in JavaScript would be a second version of
// each list to keep in step with the first. So this fetches the same URL the
// form would have submitted and swaps in the results block from the reply.
// One rendering path, and the screen keeps working with JavaScript off,
// because the form and its button are still there underneath.
//
// The important part is the sequence number. Type "ah" then "ahmed": if the
// first reply is slower, it arrives last and paints Ahmed's search with a list
// of every name containing "ah". A search that shows the wrong results
// *silently* is worse than a slow one, so a reply that is not the newest is
// dropped, and any in-flight request is aborted the moment the next keystroke
// makes it irrelevant.
window.gcLiveSearch = function (form) {
  var target = document.querySelector(form.dataset.liveSearch);
  var input = form.querySelector('input[name="q"]');
  if (!target || !input) return;

  var wait = parseInt(form.dataset.liveDelay, 10) || 250;
  var timer = null;
  var seq = 0;
  var inflight = null;

  // Screen readers need to be told the list underneath changed; sighted users
  // get the busy class.
  target.setAttribute("aria-live", "polite");
  target.setAttribute("aria-busy", "false");

  function run() {
    var mine = ++seq;
    var url = form.action.split("?")[0] + "?" +
      new URLSearchParams(new FormData(form)).toString();

    if (inflight) inflight.abort();
    inflight = ("AbortController" in window) ? new AbortController() : null;

    target.setAttribute("aria-busy", "true");
    fetch(url, {
      headers: { "X-Requested-With": "fetch" },
      signal: inflight ? inflight.signal : undefined
    })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        if (mine !== seq) return;              // a newer keystroke won
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.querySelector(form.dataset.liveSearch);
        if (fresh) target.innerHTML = fresh.innerHTML;
        target.setAttribute("aria-busy", "false");
        // replaceState, not pushState: every keystroke in the back button
        // would make the back button useless.
        try { window.history.replaceState({}, "", url); } catch (e) {}
      })
      .catch(function () {
        if (mine === seq) target.setAttribute("aria-busy", "false");
      });
  }

  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(run, wait);
  });
  // Changing a filter beside the box should search too, and without waiting.
  form.querySelectorAll("select, input[type=checkbox], input[type=radio]")
    .forEach(function (el) {
      el.addEventListener("change", function () { clearTimeout(timer); run(); });
    });
  // Enter still works, and must not also submit the page underneath.
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    clearTimeout(timer);
    run();
  });
};

document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("form[data-live-search]").forEach(window.gcLiveSearch);
});

// ---------------------------------------------------------------------------
// gcPicker — the one autocomplete, for drugs and everything else that asks
// "which one did you mean".
//
// Reported: *"the drug search looks odd and it's hard to choose."* There were
// three hand-written copies of this control and they had drifted into three
// different behaviours, none of them keyboard-operable:
//
//   * no arrow keys and no Enter — a doctor with a hand on the keyboard had to
//     reach for the mouse for every line of a prescription;
//   * an empty list when nothing matched, which looks the same as still
//     loading and the same as broken;
//   * `background = '#fff'` written straight onto the row by the hover
//     handler, so in dark mode it turned white under white text;
//   * and no guard against a slow reply landing last — the same fault fixed in
//     gcLiveSearch, and worse here, because the wrong list is one you then
//     *click*: what you picked is not what you read.
//
// **It holds no caller state and writes to nothing.** Closing over the
// caller's object would mean writing to the raw object rather than Alpine's
// proxy, and a write that misses the proxy renders nothing — the drug would be
// chosen and the field would sit there empty. So the picker owns the list and
// the highlight, and the screen does its own filling in, from template scope
// where everything is reactive.
//
// Usage (Alpine): x-data="{ picker: gcPicker({ url }) }"
//   input   x-on:keydown.enter="onEnter($event)"
//   option  x-on:click="take(s)"
window.gcPicker = function (config) {
  var cfg = config || {};
  return {
    q: cfg.value || "",
    items: [],
    open: false,
    searched: false,   // false until a reply lands: "nothing found" is a fact
    active: -1,
    _seq: 0,
    _abort: null,

    async search() {
      var text = (this.q || "").trim();
      if (text.length < (cfg.minChars || 1)) {
        this.items = []; this.open = false; this.searched = false; return;
      }
      var mine = ++this._seq;
      if (this._abort) this._abort.abort();
      var ctl = new AbortController();
      this._abort = ctl;
      try {
        var url = cfg.url + (cfg.url.indexOf("?") < 0 ? "?" : "&") +
          "q=" + encodeURIComponent(text) + (cfg.extra ? "&" + cfg.extra() : "");
        var reply = await fetch(url, { signal: ctl.signal });
        var data = await reply.json();
        // Not the newest question any more, so its answer is not an answer.
        if (mine !== this._seq) return;
        this.items = Array.isArray(data) ? data : [];
        this.active = this.items.length ? 0 : -1;
        this.searched = true;
        this.open = true;
      } catch (err) {
        if (err && err.name === "AbortError") return;
        if (mine !== this._seq) return;
        this.items = []; this.active = -1; this.searched = true; this.open = true;
      }
    },

    move(step) {
      if (!this.open || !this.items.length) return;
      this.active = (this.active + step + this.items.length) % this.items.length;
    },

    // The highlighted row, or null when there is nothing to take. Returning it
    // rather than acting on it is what keeps the caller's writes reactive.
    take() {
      if (!this.open || this.active < 0 || !this.items[this.active]) return null;
      var chosen = this.items[this.active];
      this.close();
      return chosen;
    },

    close() { this.open = false; this.items = []; this.active = -1; },
  };
};
