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
      // `cfg.minChars || 1` turned an explicit 0 into 1, so a caller that
      // wanted the whole (short) list on focus silently got nothing until two
      // letters were typed.
      var minChars = cfg.minChars === undefined ? 1 : cfg.minChars;
      if (text.length < minChars) {
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

// --------------------------------------------------------- live timers ----
// "This child has been waiting 41 minutes" — ticking, on the screen, without
// the server being asked anything. The page prints the moment once and the
// browser counts from it; there is no polling and no refresh, so a board left
// open on the reception desk all morning costs nothing.
//
// The trap this code exists to avoid: the program stores times with
// `datetime.utcnow()`, which is UTC with no timezone marker on it. Handed to
// the browser as-is it would be read as local time, and every counter in a
// clinic on UTC+3 would read three hours high — which looks exactly like a
// bug in the counter rather than a bug in the timestamp. So the template
// stamps a trailing `Z` and this reads it as UTC, always.
(function () {
  var AMBER = 20, RED = 40;   // minutes a family has been waiting

  function label(el, mins) {
    var hour = el.dataset.unitHour || 'h', min = el.dataset.unitMin || 'm';
    if (mins < 60) return mins + ' ' + min;
    var h = Math.floor(mins / 60), m = mins % 60;
    return m ? h + ' ' + hour + ' ' + m + ' ' + min : h + ' ' + hour;
  }

  function tick() {
    var now = Date.now();
    document.querySelectorAll('.live-timer').forEach(function (el) {
      var since = Date.parse(el.dataset.since);
      if (isNaN(since)) return;
      var mins = Math.floor((now - since) / 60000);
      if (mins < 0) mins = 0;              // clocks drift; never count down
      el.textContent = label(el, mins);
      // Only a waiting family goes red. A counter turning red while a doctor
      // is examining a sick child is pressure to hurry, and hurrying is not
      // what anybody wants bought with this feature.
      if (el.dataset.tone === 'wait') {
        el.classList.toggle('lt-amber', mins >= AMBER && mins < RED);
        el.classList.toggle('lt-red', mins >= RED);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    tick();
    // Half a minute: the number is shown in whole minutes, so anything
    // faster redraws the same text.
    setInterval(tick, 30000);
  });
})();

// ------------------------------------------------- inline add / remove ----
// Adding one drug should not reload the whole consultation.
//
// Every add on the visit screen was a form POST followed by a full page load.
// That threw away the scroll position and anything half-typed elsewhere, and
// a doctor adding four medicines paid for it four times — mid-consultation,
// with a child on the couch.
//
// The trick here is that no new endpoint is needed. The POST already redirects
// to the visit page, and `fetch` follows that redirect, so the response *is*
// the freshly rendered page: parse it, lift out the one list that changed, and
// put it in place. One request, same server code, same HTML the full reload
// would have produced — so the two can never drift apart, which is what makes
// this safe on a clinical screen rather than a second rendering path to
// maintain.
//
// If anything about the page is not as expected — no list to swap, a failed
// request, a response that is not the page we asked for — it falls back to
// letting the browser submit normally. A visit record that quietly fails to
// record something is far worse than one that blinks.
(function () {
  function panelOf(form) {
    return form.closest('[data-add-panel]');
  }

  // A visible "yes, that went in". Without it the only evidence a doctor has
  // that the press worked is the list being one row longer than they
  // remember, which is not evidence at all halfway through a consultation.
  function confirmAdd(form, row) {
    var note = form.querySelector('.gc-added-note');
    if (!note) {
      note = document.createElement('div');
      note.className = 'gc-added-note';
      form.appendChild(note);
    }
    var name = row ? (row.querySelector('strong') || row).textContent.trim() : '';
    note.innerHTML = '<i class="bi bi-check-circle-fill"></i> ' +
      (form.dataset.addedLabel || 'Added') +
      (name ? ' — <b></b>' : '');
    if (name) note.querySelector('b').textContent = name.slice(0, 60);
    note.classList.remove('is-gone');
    clearTimeout(note._timer);
    note._timer = setTimeout(function () { note.classList.add('is-gone'); }, 3500);
  }

  async function inlineSubmit(ev) {
    const form = ev.target.closest && ev.target.closest('form[data-inline]');
    if (!form) return;
    const panel = panelOf(form);
    const list = panel && panel.querySelector('[data-add-list]');
    if (!panel || !list) return;            // nowhere to put it: normal submit

    ev.preventDefault();
    const button = form.querySelector('[type=submit]');
    if (button) button.disabled = true;

    try {
      const res = await fetch(form.action, {
        method: 'POST', body: new FormData(form), redirect: 'follow',
        headers: { 'X-Requested-With': 'fetch' },
      });
      if (!res.ok) throw new Error(res.status);
      const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
      const fresh = doc.querySelector('#' + panel.id + ' [data-add-list]');
      if (!fresh) throw new Error('no list in response');

      // Which rows are new. Compared before the swap, because after it the
      // only way to tell would be to trust the order — and a doctor who
      // cannot see *what* was added has to re-read the whole list to be sure
      // the press worked, which is the thing this was meant to remove.
      const before = new Set(
        Array.from(list.children).map(function (el) { return el.outerHTML; }));

      list.innerHTML = fresh.innerHTML;
      // Alpine does not walk HTML that appeared after it started.
      if (window.Alpine && window.Alpine.initTree) window.Alpine.initTree(list);

      const fresh_rows = Array.from(list.querySelectorAll('tbody tr, .dx-row'))
        .filter(function (el) { return !before.has(el.outerHTML); });
      const landed = fresh_rows.length ? fresh_rows[fresh_rows.length - 1] : null;
      if (landed) {
        landed.classList.add('gc-just-added');
        landed.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        setTimeout(function () { landed.classList.remove('gc-just-added'); }, 2200);
      }
      if (form.hasAttribute('data-add-form')) confirmAdd(form, landed);

      // The tab badge counts what is in the list, so it moved too.
      const badge = document.querySelector('[data-count-for="' + panel.id + '"]');
      const freshBadge = doc.querySelector('[data-count-for="' + panel.id + '"]');
      if (badge && freshBadge) {
        badge.textContent = freshBadge.textContent;
        // It renders even at zero so that it exists to count up from; hidden
        // is what keeps an empty tab from wearing a "0".
        badge.hidden = freshBadge.hidden;
      }

      if (form.hasAttribute('data-add-form')) {
        form.reset();
        const first = form.querySelector('input:not([type=hidden]), textarea');
        if (first) first.focus();
      }
    } catch (e) {
      form.removeAttribute('data-inline');   // do it the reliable way instead
      form.submit();
      return;
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.addEventListener('submit', inlineSubmit);
})();

// ------------------------------------------------- the copy that is sent --
// Saving a page as an image, drawn by the browser that is already displaying
// it correctly.
//
// Rendering on the server was the alternative and is the wrong trade for this
// program. WeasyPrint and wkhtmltopdf are heavy installs on the Windows Server
// these clinics run, and both need their Arabic fonts and RTL handling
// configured by hand — so the first clinic installing unaided would stop
// there. The browser has already solved every one of those problems: what it
// is showing is, letter for letter, what should be sent.
//
// The first attempt at this rasterised the page through an SVG
// <foreignObject>, which *taints the canvas* in Chromium — every clinic —
// so toDataURL threw SecurityError and no file ever came out. The button
// silently fell through to window.print() each time. That approach cannot be
// made to work and should not be tried again.
//
// html2canvas works because it does not go through SVG at all: it walks the
// DOM and repaints it onto the canvas itself, so nothing ever taints it. It
// is vendored locally (app/static/vendor) rather than loaded from a CDN,
// because a clinic with no internet still has to be able to send a
// prescription.
(function () {
  const LIB = '/static/vendor/html2canvas.min.js';
  let loading = null;

  function library() {
    if (window.html2canvas) return Promise.resolve(window.html2canvas);
    // Loaded on first use rather than on every page: it is 194KB, and the
    // overwhelming majority of screens never render an image.
    if (!loading) {
      loading = new Promise(function (resolve, reject) {
        const tag = document.createElement('script');
        tag.src = LIB;
        tag.onload = function () { resolve(window.html2canvas); };
        tag.onerror = function () { loading = null; reject(new Error('load')); };
        document.head.appendChild(tag);
      });
    }
    return loading;
  }

  // Modern CSS colours, spelled the way a 2022 parser understands.
  //
  // The theme derives its palette with `color-mix(in srgb, …)`, which is how
  // one `--accent` recolours the whole brand. Chromium computes that to
  // `color(srgb r g b)` — a syntax html2canvas does not know, and it throws
  // rather than skipping the declaration: "Attempting to parse an unsupported
  // color function". Every capture failed on it, silently, by way of the
  // print fallback.
  //
  // Converting is exact rather than approximate: `color(srgb …)` carries the
  // same numbers in 0–1 that rgb() carries in 0–255. Doing it on the *clone*
  // means the real page keeps its modern colours and only the copy being
  // rasterised is written the old way.
  function toLegacyColour(value) {
    return value.replace(
      /color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)/g,
      function (_all, r, g, b, a) {
        const ch = function (x) { return Math.round(parseFloat(x) * 255); };
        return a !== undefined && parseFloat(a) < 1
          ? 'rgba(' + ch(r) + ',' + ch(g) + ',' + ch(b) + ',' + a + ')'
          : 'rgb(' + ch(r) + ',' + ch(g) + ',' + ch(b) + ')';
      });
  }

  // Every property, rather than a list of the ones that seemed likely.
  //
  // The list was tried first and was wrong: `color(srgb …)` turned up in 80
  // declarations on a single prescription page, including logical properties
  // (`border-inline-start-color`) and inside gradient stacks. Enumerating
  // which properties can hold a colour is a losing game — CSS keeps adding
  // them — so this sweeps whatever the browser says is set and rewrites only
  // what actually contains the unsupported syntax.
  // Land every entrance animation on its finished state.
  //
  // The renderer works on a *clone*, and a cloned element restarts its
  // animations from the first keyframe. Every card in this program enters with
  // `gc-scale-in`, whose first keyframe is `opacity: 0` — so the capture came
  // out of a page that was, at that instant, invisible. The first working
  // render produced a prescription with zero pixels darker than (228,230,231):
  // correct layout, correct text, all of it at nearly zero opacity.
  //
  // Zero duration with the `both` fill mode the animations already declare
  // means each one immediately holds its *last* keyframe. That settles them
  // whatever they animate, rather than naming opacity and being wrong about
  // the next animation somebody adds.
  function settleAnimations(doc) {
    const style = doc.createElement('style');
    style.textContent =
      '*, *::before, *::after {' +
      ' animation-delay: 0s !important;' +
      ' animation-duration: 0s !important;' +
      ' transition: none !important; }';
    (doc.head || doc.documentElement).appendChild(style);
  }

  // Arabic does not survive being drawn one letter at a time.
  //
  // With a non-zero `letter-spacing`, html2canvas positions each character
  // itself instead of letting the browser lay out the run — and Arabic is
  // contextual, so its letters stop joining and the leading alef disappears.
  // "المريض" came out as "لم ي ض" and "الجرعة" as "لج رعة", on the field
  // labels and table headers where the theme adds 0.4px of tracking. Body
  // text, which has none, was perfect.
  //
  // Only elements actually holding Arabic are touched, so the Latin wordmark
  // keeps its tracking. Losing 0.4px on a label is invisible; losing the
  // shaping makes a prescription unusable at a pharmacy.
  const ARABIC = /[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]/;

  function unspaceArabic(doc) {
    const view = doc.defaultView || window;
    doc.querySelectorAll('*').forEach(function (el) {
      const spacing = view.getComputedStyle(el).letterSpacing;
      if (!spacing || spacing === 'normal' || parseFloat(spacing) === 0) return;
      if (ARABIC.test(el.textContent || '')) {
        el.style.setProperty('letter-spacing', 'normal', 'important');
      }
    });
  }

  function flattenColours(doc) {
    const view = doc.defaultView || window;
    doc.querySelectorAll('*').forEach(function (el) {
      const computed = view.getComputedStyle(el);
      for (let i = 0; i < computed.length; i++) {
        const prop = computed[i];
        const value = computed.getPropertyValue(prop);
        if (value && value.indexOf('color(') !== -1) {
          el.style.setProperty(prop, toLegacyColour(value));
        }
      }
    });
  }

  // Turn one element into a PNG the user's browser downloads.
  //
  // `scale: 2` because a pharmacist reads this zoomed in on a phone, and a
  // screen-resolution capture of Arabic text is a smear at that size.
  window.gcSaveImage = async function (selector, filename, button) {
    const node = document.querySelector(selector);
    if (!node) return;
    const label = button ? button.innerHTML : null;
    if (button) { button.disabled = true; button.textContent = '…'; }
    try {
      const h2c = await library();
      const canvas = await h2c(node, {
        scale: 2,
        useCORS: true,
        // The rendered page must not carry the screen's dark theme into a
        // document somebody prints or forwards: white paper, always.
        backgroundColor: '#ffffff',
        // Anything marked no-print is furniture — buttons, nav, flash
        // messages. It has no business in a saved copy either.
        ignoreElements: function (el) {
          return el.classList && el.classList.contains('no-print');
        },
        onclone: function (doc) {
          settleAnimations(doc); unspaceArabic(doc); flattenColours(doc);
        }
      });
      const link = document.createElement('a');
      link.download = filename || 'page.png';
      link.href = canvas.toDataURL('image/png');
      link.click();
    } catch (e) {
      // Never leave somebody pressing a dead button. Printing is the route
      // that always works, and it is where a PDF comes from anyway.
      window.print();
    } finally {
      if (button) { button.disabled = false; button.innerHTML = label; }
    }
  };
})();

// gcDoctorPicker — "which doctor?", the same way on every screen that asks.
//
// A clinic with four doctors is fine with a <select>. A centre with forty is
// the screen: you open a list, scroll, and read forty names to find one. The
// searchable picker already existed and exactly one screen used it — the
// prescription — because it was written inside that template's <script> and
// could not be reached from anywhere else. Six other screens kept their
// dropdowns.
//
// `allowAll` is the difference between a *field* and a *filter*. Picking the
// doctor a schedule belongs to has no "all"; the appointments board and the
// roster do, and a search box with no way back to "everybody" would be a
// worse filter than the dropdown it replaced.
window.gcDoctorPicker = function (url, initialId, initialName, allowAll, field,
                                  autosubmit) {
  return {
    q: initialName || "",
    chosenId: initialId === null || initialId === undefined ? "" : String(initialId),
    allowAll: !!allowAll,
    // A filter that reloads on choice, or a field in a form with its own
    // button. Auto-submitting the second kind sends the form before the
    // person has filled in the date next to it.
    autosubmit: autosubmit !== false,
    picker: window.gcPicker({ url: url, minChars: 0 }),
    ask(all) {
      // Typing again means they are choosing somebody else. Leaving the old id
      // attached is how a form is submitted for a doctor whose name is no
      // longer in the box.
      this.chosenId = "";
      // On focus the box still holds the name of whoever is chosen, and
      // searching *that* returns only the one they already have. Opening the
      // list has to offer the others — which is why somebody clicked it.
      // Measured: focusing showed 2 of 40 doctors.
      this.picker.q = all ? "" : this.q;
      this.picker.search();
    },
    choose(d, el) {
      this.picker.close();
      this.chosenId = String(d.id);
      this.q = d.name;
      this.go(el);
    },
    clear(el) {
      this.chosenId = "";
      this.q = "";
      this.picker.close();
      if (this.allowAll) this.go(el);
    },
    // The element comes from the template rather than from `this.$el`, and the
    // field is written straight onto the DOM rather than through the `:value`
    // binding. Both were the other way round first, and the picker silently
    // did not submit: the id landed in the hidden input and the URL never
    // changed, so the screen went on showing the previous doctor while the box
    // showed the new one — the worst way for a picker to fail, because it
    // looks like it worked. Alpine's magics ($el, $nextTick) are reliable
    // inside expressions and not inside methods on an object built by a plain
    // function like this one, and the binding flushes a tick after the click.
    // Passing the element in and setting the value directly needs neither.
    go(el) {
      if (!this.autosubmit) return;
      var form = el && el.closest ? el.closest("form") : null;
      if (!form) return;
      var hidden = form.querySelector('input[name="' + field + '"]');
      if (hidden) hidden.value = this.chosenId;
      form.submit();
    },
    enter(ev, el) {
      var d = this.picker.take();
      if (d) { ev.preventDefault(); this.choose(d, el); }
    },
  };
};
