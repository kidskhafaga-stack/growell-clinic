// The clinic's program's side — and only the program's: every call carries
// the key from its clinic.env (x-clinic-key), or is refused.
//
// POST /api/sync {action: "push", brand, surveys: [{token, config, days}]}
//      — the clinic's name and logo, and the surveys just sent to families.
// POST /api/sync {action: "pull"}
//      — the answers waiting: [{token, payload, submitted_at}].
// POST /api/sync {action: "done", tokens: [...]}
//      — the program has them: the answers and their surveys are deleted.
//
// Nothing is ever read back that the program did not put here itself, and
// nothing stays once the program has collected it.
'use strict';

const { call, inList, clinicKeyOk, bodyOf, TOKEN } = require('../lib/store');

const MAX_SURVEYS = 200;
const MAX_DAYS = 60;

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ ok: false });
  }
  if (!clinicKeyOk(req)) return res.status(401).json({ ok: false });
  const body = bodyOf(req) || {};
  try {
    if (body.action === 'push') {
      if (body.brand && typeof body.brand === 'object') {
        const b = await call('POST', 'brand', {
          query: { on_conflict: 'id' },
          body: { id: 1, config: body.brand, updated_at: new Date().toISOString() },
          prefer: 'return=minimal,resolution=merge-duplicates' });
        if (b.status >= 300) return res.status(502).json({ ok: false, step: 'brand' });
      }
      const rows = (Array.isArray(body.surveys) ? body.surveys : []).slice(0, MAX_SURVEYS)
        .filter((s) => s && TOKEN.test(String(s.token || '')) && s.config && typeof s.config === 'object')
        .map((s) => {
          const days = Math.min(Math.max(parseInt(s.days, 10) || 30, 1), MAX_DAYS);
          return { token: String(s.token), config: s.config,
                   expires_at: new Date(Date.now() + days * 86400000).toISOString() };
        });
      if (rows.length) {
        const put = await call('POST', 'surveys', {
          query: { on_conflict: 'token' }, body: rows,
          prefer: 'return=minimal,resolution=merge-duplicates' });
        if (put.status >= 300) return res.status(502).json({ ok: false, step: 'surveys' });
      }
      return res.status(200).json({ ok: true, pushed: rows.map((r) => r.token) });
    }
    if (body.action === 'pull') {
      const got = await call('GET', 'answers', {
        query: { select: 'token,payload,submitted_at', order: 'submitted_at.asc', limit: '500' } });
      if (got.status >= 300) return res.status(502).json({ ok: false });
      return res.status(200).json({ ok: true, answers: got.data || [] });
    }
    if (body.action === 'done') {
      const tokens = (Array.isArray(body.tokens) ? body.tokens : [])
        .map(String).filter((t) => TOKEN.test(t)).slice(0, 500);
      if (tokens.length) {
        // The survey goes, and its answer with it (on delete cascade).
        const del = await call('DELETE', 'surveys', {
          query: { token: inList(tokens) }, prefer: 'return=minimal' });
        if (del.status >= 300) return res.status(502).json({ ok: false });
      }
      return res.status(200).json({ ok: true, deleted: tokens.length });
    }
    return res.status(400).json({ ok: false });
  } catch (e) {
    return res.status(503).json({ ok: false });
  }
};
