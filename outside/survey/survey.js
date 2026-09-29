// The family's page: one question at a time, following the answers.
//
// The rules are the clinic program's own (app/utils/survey_flow.py): start
// at the first question that is not a branch; after each, a jump written
// for that answer's group, else the next question that is not a branch. The
// program walks them again when it collects the answers, and keeps only
// what lies on the path — so this page cannot add anything the rules refuse.
//
// Everything shown is text: no answer, name or label is ever put in as HTML.
(function () {
  'use strict';
  var app = document.getElementById('app');
  var token = (new URLSearchParams(location.search).get('t') || '').trim();
  var FIELD = { doctor: 'doctor_rating', service: 'service_rating',
                finance: 'finance_rating', nps: 'nps', comment: 'comment' };

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'on') Object.keys(attrs.on).forEach(function (e) { node.addEventListener(e, attrs.on[e]); });
      else node.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }

  function message(text) {
    app.textContent = '';
    app.appendChild(el('p', { class: 'thanks', text: text }));
  }

  // ------------------------------------------------------------- the rules
  function bucket(kind, v) {
    if (v === undefined || v === null || v === '') return null;
    var n = parseInt(v, 10);
    if (kind === 'stars') return n <= 2 ? 'low' : (n === 3 ? 'mid' : 'high');
    if (kind === 'nps') return n <= 6 ? 'low' : (n <= 8 ? 'mid' : 'high');
    if (kind === 'yesno') return (v === 'yes' || v === 'no') ? v : null;
    if (kind === 'single') return String(v).charAt(0) === 'o' ? v : null;
    return null;
  }
  function after(steps, i) { var j = i + 1; while (j < steps.length && steps[j].branch_only) j++; return j < steps.length ? j : -1; }
  function next(steps, i, answers) {
    var s = steps[i], to = (s.jumps || {})[bucket(s.kind, answers[s.key])];
    if (to === 'end') return -1;
    if (to) for (var n = i + 1; n < steps.length; n++) if (steps[n].key === to) return n;
    return after(steps, i);
  }

  // ------------------------------------------------------------- the page
  function head(brand, survey) {
    var logo = brand.logo && /^data:image\/(png|jpe?g|webp|gif);base64,/.test(brand.logo)
      ? el('img', { src: brand.logo, alt: '' })
      : el('div', { class: 'mark', text: (brand.name || '★').trim().charAt(0) });
    return el('div', { class: 'head' }, [
      logo, el('h1', { text: survey.intro || '' }),
      el('p', { text: [brand.name, survey.unit].filter(Boolean).join(' · ') })]);
  }

  function run(brand, survey) {
    var L = survey.labels || {};
    var steps = survey.steps || [];
    var answers = {}, concerns = [];
    if (brand.colour && /^#[0-9a-fA-F]{6}$/.test(brand.colour)) document.documentElement.style.setProperty('--brand', brand.colour);
    document.title = brand.name || document.title;
    if (survey.dir) document.documentElement.dir = survey.dir;
    if (survey.lang) document.documentElement.lang = survey.lang;
    var trail = [after(steps, -1)];
    if (trail[0] === -1) return message(L.missing || '');

    function ahead(i) { var k = 0; while (i !== -1 && k < steps.length) { k++; i = next(steps, i, answers); } return k; }

    function choose(key, value, auto) {
      answers[key] = value; draw();
      if (auto) setTimeout(forward, 260);
    }

    function body(s) {
      var v = answers[s.key];
      if (s.kind === 'stars') {
        return el('div', { class: 'stars' }, [5, 4, 3, 2, 1].map(function (n) {
          return el('button', { type: 'button', class: v >= n ? 'on' : '', 'aria-label': n + '/5', text: '★',
            on: { click: function () { choose(s.key, n, !(s.concerns && s.concerns.length)); } } });
        }));
      }
      if (s.kind === 'nps') {
        var grid = el('div', { class: 'nps' }, Array.from({ length: 11 }, function (_, n) {
          return el('button', { type: 'button', class: v === n ? 'on' : '', text: String(n),
            on: { click: function () { choose(s.key, n, true); } } });
        }));
        return el('div', {}, [grid, el('div', { class: 'ends' }, [el('span', { text: L.nps_low || '' }), el('span', { text: L.nps_high || '' })])]);
      }
      if (s.kind === 'yesno') {
        return el('div', { class: 'choices yn' }, [['yes', L.yes], ['no', L.no]].map(function (p) {
          return el('button', { type: 'button', class: v === p[0] ? 'on' : '', text: p[1] || p[0],
            on: { click: function () { choose(s.key, p[0], true); } } });
        }));
      }
      if (s.kind === 'single' || s.kind === 'multi') {
        return el('div', { class: 'choices' }, (s.options || []).map(function (o, n) {
          var code = 'o' + n, picked = s.kind === 'multi' ? (v || []).indexOf(code) !== -1 : v === code;
          return el('button', { type: 'button', class: picked ? 'on' : '', text: o,
            on: { click: function () {
              if (s.kind === 'single') return choose(s.key, code, true);
              var list = (answers[s.key] || []).slice(), at = list.indexOf(code);
              if (at === -1) list.push(code); else list.splice(at, 1);
              choose(s.key, list, false);
            } } });
        }));
      }
      var box = el('textarea', { maxlength: '2000', dir: 'auto' });
      box.value = v || '';
      box.addEventListener('input', function () { answers[s.key] = box.value; });
      return box;
    }

    function why(s) {
      if (!s.concerns || !s.concerns.length) return null;
      var d = el('details', { class: 'why' }, [el('summary', { text: L.why_q || '' }),
        el('div', { class: 'chips' }, s.concerns.map(function (c) {
          return el('button', { type: 'button', class: concerns.indexOf(c.value) !== -1 ? 'on' : '', text: c.label,
            on: { click: function () {
              var at = concerns.indexOf(c.value);
              if (at === -1) concerns.push(c.value); else concerns.splice(at, 1);
              draw(true);
            } } });
        }))]);
      if (s.concerns.some(function (c) { return concerns.indexOf(c.value) !== -1; })) d.open = true;
      return d;
    }

    function draw(keepOpen) {
      var cur = trail[trail.length - 1], s = steps[cur];
      var total = trail.length - 1 + ahead(cur);
      app.textContent = '';
      app.appendChild(head(brand, survey));
      var bar = el('span'); bar.style.width = Math.round((trail.length - 1) * 100 / Math.max(total, 1)) + '%';
      app.appendChild(el('div', { class: 'prog' }, [bar]));
      app.appendChild(el('div', { class: 'count', text: trail.length + ' / ' + total }));
      app.appendChild(el('div', { class: 'q' }, [el('label', { class: 'qlab', text: s.label }), body(s), why(s)]));
      var last = next(steps, cur, answers) === -1;
      app.appendChild(el('div', { class: 'nav' }, [
        trail.length > 1 ? el('button', { type: 'button', class: 'back', text: L.back || '←',
          on: { click: function () { trail.pop(); draw(); } } }) : null,
        el('button', { type: 'button', text: last ? (L.send || '✓') : (L.next || '→'), on: { click: forward } })]));
      app.appendChild(el('p', { class: 'note', text: L.privacy || '' }));
    }

    function forward() {
      var n = next(steps, trail[trail.length - 1], answers);
      if (n === -1) return send();
      trail.push(n); draw();
    }

    function send() {
      // Only the questions on the path go.
      var out = {}, asked = {};
      trail.forEach(function (i) { asked[steps[i].key] = true; });
      steps.forEach(function (s) {
        if (!asked[s.key] || answers[s.key] === undefined || answers[s.key] === '') return;
        var field = s.builtin ? FIELD[s.key] : 'a_' + s.key;
        if (field) out[field] = answers[s.key];
      });
      out.concern = concerns.filter(function (c) { return asked[c.split(':')[0]]; });
      message(L.sending || '…');
      fetch('/api/survey', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ t: token, answers: out }) })
        .then(function (r) { return r.json(); })
        .then(function (r) { if (r && r.ok) thanks(); else message(L.failed || ''); })
        .catch(function () { message(L.failed || ''); });
    }

    function thanks() {
      var low = ['doctor', 'service', 'finance'].some(function (k) { return answers[k] !== undefined && answers[k] <= 2; });
      var promoter = answers.nps !== undefined && answers.nps >= 9;
      app.textContent = '';
      app.appendChild(head(brand, { intro: '', unit: '' }));
      var box = el('div', { class: 'thanks' }, [
        el('h2', { text: L.thanks_title || '' }),
        el('p', { text: brand.thanks || '' }),
        el('strong', { text: brand.name || '' })]);
      if (low) box.appendChild(el('div', { class: 'care', text: (L.care || '').replace('{clinic}', brand.name || '') }));
      else if (promoter && brand.review_url && /^https?:\/\//.test(brand.review_url)) {
        box.appendChild(el('div', {}, [el('a', { class: 'review', href: brand.review_url, target: '_blank', rel: 'noopener', text: '★ ' + (L.review || '') })]));
      }
      app.appendChild(box);
    }

    draw();
  }

  if (!/^[A-Za-z0-9_-]{8,64}$/.test(token)) return message('✕');
  fetch('/api/survey?t=' + encodeURIComponent(token))
    .then(function (r) { return r.json(); })
    .then(function (r) {
      if (!r || !r.ok) return message('✕');
      var L = (r.survey && r.survey.labels) || {};
      if (r.done) return message(L.already || '✓');
      run(r.brand || {}, r.survey || {});
    })
    .catch(function () { message('…'); });

})();
