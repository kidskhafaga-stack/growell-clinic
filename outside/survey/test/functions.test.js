// The page's two functions against a fake Supabase: run with `node`.
// The program's test suite runs this (tests/test_the_survey_page_outside.py).
'use strict';

const assert = require('assert');

process.env.SUPABASE_URL = 'https://db.example.co/';
process.env.SUPABASE_SERVICE_KEY = 'service-key';
process.env.CLINIC_SYNC_KEY = 'k'.repeat(32);

// ------------------------------------------------------------ fake store
const db = { brand: [], surveys: [], answers: [] };
const seen = [];
global.fetch = async (url, init) => {
  const u = new URL(url);
  seen.push({ url: u, init });
  assert.strictEqual(u.origin + u.pathname.replace(/\/[^/]+$/, ''), 'https://db.example.co/rest/v1');
  assert.strictEqual(init.headers.apikey, 'service-key');
  assert.strictEqual(init.headers.Authorization, 'Bearer service-key');
  const table = u.pathname.split('/').pop();
  const eqf = (row) => [...u.searchParams].every(([k, v]) => {
    if (['select', 'order', 'limit', 'on_conflict'].includes(k)) return true;
    if (v.startsWith('eq.')) return String(row[k]) === v.slice(3);
    if (v.startsWith('in.(')) return v.slice(4, -1).split(',').includes(String(row[k]));
    throw new Error('filter ' + v);
  });
  const reply = (status, body) => ({ status, text: async () => (body === undefined ? '' : JSON.stringify(body)) });
  if (init.method === 'GET') return reply(200, db[table].filter(eqf));
  if (init.method === 'POST') {
    const rows = [].concat(JSON.parse(init.body));
    const merge = (init.headers.Prefer || '').includes('resolution=merge-duplicates');
    const key = table === 'brand' ? 'id' : 'token';
    for (const r of rows) {
      const at = db[table].findIndex((x) => x[key] === r[key]);
      if (at !== -1 && !merge) return reply(409, { code: '23505' });
      if (at !== -1) db[table][at] = r; else db[table].push(r);
    }
    return reply(201);
  }
  if (init.method === 'DELETE') {
    const gone = db[table].filter(eqf).map((r) => r.token);
    db[table] = db[table].filter((r) => !eqf(r));
    if (table === 'surveys') db.answers = db.answers.filter((a) => !gone.includes(a.token));
    return reply(204);
  }
  throw new Error(init.method);
};

// ------------------------------------------------------- request doubles
function call(handler, { method = 'GET', query = {}, body, headers = {} } = {}) {
  return new Promise((resolve) => {
    const res = { code: 200, headers: {},
      setHeader(k, v) { this.headers[k] = v; },
      status(c) { this.code = c; return this; },
      json(b) { resolve({ code: this.code, body: b }); return this; } };
    handler({ method, query, body, headers }, res);
  });
}

const survey = require('../api/survey');
const sync = require('../api/sync');
const KEY = { 'x-clinic-key': 'k'.repeat(32) };

(async () => {
  // Without the key, nothing — and a key too short on the server refuses all.
  assert.strictEqual((await call(sync, { method: 'POST', body: { action: 'pull' } })).code, 401);
  assert.strictEqual((await call(sync, { method: 'POST', body: { action: 'pull' }, headers: { 'x-clinic-key': 'wrong' } })).code, 401);

  // The program sends two surveys and its brand.
  const push = await call(sync, { method: 'POST', headers: KEY, body: { action: 'push',
    brand: { name: 'جروويل' },
    surveys: [{ token: 'tok_one_1234', config: { steps: [] } },
              { token: 'bad token!', config: {} },
              { token: 'tok_two_1234', config: { steps: [] }, days: 999 }] } });
  assert.deepStrictEqual(push.body.pushed, ['tok_one_1234', 'tok_two_1234']);
  const exp = new Date(db.surveys.find((s) => s.token === 'tok_two_1234').expires_at);
  assert.ok(exp - Date.now() <= 60 * 86400000 + 5000, 'no more than 60 days');
  const put = seen.find((s) => s.url.pathname.endsWith('/surveys') && s.init.method === 'POST');
  assert.strictEqual(put.url.searchParams.get('on_conflict'), 'token');
  assert.ok(put.init.headers.Prefer.includes('return=minimal'));

  // The family reads it, and a made-up code reads nothing.
  const read = await call(survey, { query: { t: 'tok_one_1234' } });
  assert.strictEqual(read.code, 200);
  assert.strictEqual(read.body.brand.name, 'جروويل');
  assert.strictEqual((await call(survey, { query: { t: 'nope_nope_nope' } })).code, 404);
  assert.strictEqual((await call(survey, { query: { t: '<script>' } })).code, 404);

  // One answer per code; fields the program does not read are not kept.
  const first = await call(survey, { method: 'POST', body: { t: 'tok_one_1234',
    answers: { doctor_rating: '5', evil: 'x', a_q3: ['o1'], concern: ['finance:price'] } } });
  assert.deepStrictEqual(first.body, { ok: true });
  const again = await call(survey, { method: 'POST', body: JSON.stringify({ t: 'tok_one_1234', answers: { doctor_rating: '1' } }) });
  assert.strictEqual(again.body.already, true);
  assert.deepStrictEqual(db.answers[0].payload, { doctor_rating: ['5'], a_q3: ['o1'], concern: ['finance:price'] });
  assert.strictEqual((await call(survey, { query: { t: 'tok_one_1234' } })).body.done, true);
  assert.strictEqual((await call(survey, { method: 'POST', body: { t: 'tok_zzz_1234', answers: {} } })).code, 404);

  // The program collects, then has them deleted with their surveys.
  const pull = await call(sync, { method: 'POST', headers: KEY, body: { action: 'pull' } });
  assert.deepStrictEqual(pull.body.answers.map((a) => a.token), ['tok_one_1234']);
  await call(sync, { method: 'POST', headers: KEY, body: { action: 'done', tokens: ['tok_one_1234', 'x y'] } });
  assert.deepStrictEqual(db.surveys.map((s) => s.token), ['tok_two_1234']);
  assert.deepStrictEqual(db.answers, []);

  // An expired survey is not shown.
  db.surveys[0].expires_at = new Date(Date.now() - 1000).toISOString();
  assert.strictEqual((await call(survey, { query: { t: 'tok_two_1234' } })).code, 404);

  console.log('all passed');
})().catch((e) => { console.error(e); process.exit(1); });
