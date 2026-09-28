// The family's side: read one survey by its code, and hand in the answers.
//
// GET  /api/survey?t=<code>   → the clinic's name and logo, the questions
// POST /api/survey            → {t, answers}; once per code
//
// Answers are kept as the family's page sent them — field names the clinic's
// program already reads — and are judged there, by the same rules the page
// used (which questions were on the path, which values are allowed).
'use strict';

const { call, eq, bodyOf, TOKEN } = require('../lib/store');

// The fields a page can send: the built-in questions, the "what bothered
// you" taps, and the clinic's own questions (a_q<n>).
const FIELD = /^(doctor_rating|service_rating|finance_rating|nps|comment|concern|a_q[0-9]{1,4})$/;
const MAX_VALUE = 2000;
const MAX_BODY = 20000;

function cleanAnswers(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const out = {};
  for (const [key, value] of Object.entries(raw)) {
    if (!FIELD.test(key)) continue;
    const list = Array.isArray(value) ? value : [value];
    const kept = list.filter((v) => typeof v === 'string' || typeof v === 'number')
      .map((v) => String(v).slice(0, MAX_VALUE)).slice(0, 20);
    if (kept.length) out[key] = kept;
  }
  return out;
}

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  try {
    if (req.method === 'GET') {
      const t = String((req.query && req.query.t) || '');
      if (!TOKEN.test(t)) return res.status(404).json({ ok: false });
      const survey = await call('GET', 'surveys', {
        query: { select: 'config,expires_at', token: eq(t) } });
      const row = Array.isArray(survey.data) ? survey.data[0] : null;
      if (!row || new Date(row.expires_at) < new Date()) return res.status(404).json({ ok: false });
      const done = await call('GET', 'answers', { query: { select: 'token', token: eq(t) } });
      const brand = await call('GET', 'brand', { query: { select: 'config', id: 'eq.1' } });
      return res.status(200).json({
        ok: true,
        done: Array.isArray(done.data) && done.data.length > 0,
        brand: (Array.isArray(brand.data) && brand.data[0] && brand.data[0].config) || {},
        survey: row.config,
      });
    }
    if (req.method === 'POST') {
      const body = bodyOf(req);
      if (!body || JSON.stringify(body).length > MAX_BODY) return res.status(400).json({ ok: false });
      const t = String(body.t || '');
      const answers = cleanAnswers(body.answers);
      if (!TOKEN.test(t) || !answers) return res.status(400).json({ ok: false });
      const survey = await call('GET', 'surveys', { query: { select: 'expires_at', token: eq(t) } });
      const row = Array.isArray(survey.data) ? survey.data[0] : null;
      if (!row || new Date(row.expires_at) < new Date()) return res.status(404).json({ ok: false });
      // One answer per code: the table's key refuses a second.
      const put = await call('POST', 'answers', {
        body: { token: t, payload: answers }, prefer: 'return=minimal' });
      if (put.status === 409) return res.status(200).json({ ok: true, already: true });
      if (put.status >= 300) return res.status(502).json({ ok: false });
      return res.status(200).json({ ok: true });
    }
    res.setHeader('Allow', 'GET, POST');
    return res.status(405).json({ ok: false });
  } catch (e) {
    return res.status(503).json({ ok: false });
  }
};

module.exports.cleanAnswers = cleanAnswers;
