// The page's only way to its data: Supabase's REST interface, from the
// server side, with the service key from Vercel's environment.
//
// The request shapes are the ones Supabase's own clients send
// (supabase-py / postgrest-py 2.31): {url}/rest/v1/{table}, the key in both
// "apikey" and "Authorization: Bearer", filters as ?column=eq.value, and
// "Prefer: return=minimal" / "resolution=merge-duplicates" on writes.
'use strict';

const crypto = require('crypto');

function settings() {
  const url = (process.env.SUPABASE_URL || '').replace(/\/+$/, '');
  const key = process.env.SUPABASE_SERVICE_KEY || '';
  if (!url || !key) throw new Error('store_not_configured');
  return { url, key };
}

async function call(method, path, { body, prefer, query } = {}) {
  const { url, key } = settings();
  const qs = query ? '?' + new URLSearchParams(query).toString() : '';
  const headers = { apikey: key, Authorization: 'Bearer ' + key };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (prefer) headers.Prefer = prefer;
  const res = await fetch(`${url}/rest/v1/${path}${qs}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
  return { status: res.status, data };
}

// Filters as PostgREST reads them. Only ever given codes that passed TOKEN
// (letters, digits, "-", "_"), so nothing in them needs quoting; the whole
// value is URL-encoded by URLSearchParams.
const eq = (v) => 'eq.' + String(v);
const inList = (vs) => 'in.(' + vs.join(',') + ')';

// ------------------------------------------------------------------ the key
// The clinic's program proves itself with the key it was given in its
// clinic.env; the page holds the same one in Vercel's settings. Compared in
// constant time, and a page with no key set refuses everyone.
function clinicKeyOk(req) {
  const expected = process.env.CLINIC_SYNC_KEY || '';
  const given = String(req.headers['x-clinic-key'] || '');
  if (expected.length < 24 || !given) return false;
  const a = crypto.createHash('sha256').update(expected).digest();
  const b = crypto.createHash('sha256').update(given).digest();
  return crypto.timingSafeEqual(a, b);
}

function bodyOf(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') {
    try { return JSON.parse(req.body); } catch (e) { return null; }
  }
  return null;
}

// Codes are what the clinic makes: letters, digits, "-" and "_", 8 to 64.
const TOKEN = /^[A-Za-z0-9_-]{8,64}$/;

module.exports = { call, eq, inList, clinicKeyOk, bodyOf, TOKEN };
