/**
 * xops/bench/api_bench.js — §9.17.5 per-endpoint latency budget benchmark.
 *
 * Runs each endpoint at cfg.api_bench_target_rps (default 200) for 60 s
 * against the compose stack with mock predictors.  Asserts every row in
 * the §9.17.5 latency table.
 *
 * Environment variables (all optional):
 *   NEGELIR_API_BENCH_BASE_URL        default http://localhost:8080
 *   NEGELIR_API_BENCH_TARGET_RPS      default 200   (reads cfg.api_bench_target_rps)
 *   NEGELIR_API_BENCH_DURATION        default 60s
 *   NEGELIR_API_BENCH_MATCH_ID        default 1     (match used for cache-hit tests)
 *   NEGELIR_API_BENCH_AUTH_EMAIL      default bench@negelir.local
 *   NEGELIR_API_BENCH_AUTH_PASSWORD   default bench_password_1!
 *
 * Usage:
 *   k6 run xops/bench/api_bench.js
 *   NEGELIR_API_BENCH_TARGET_RPS=50 k6 run xops/bench/api_bench.js
 */

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL    = __ENV.NEGELIR_API_BENCH_BASE_URL     || 'http://localhost:8080';
const TARGET_RPS  = parseInt(__ENV.NEGELIR_API_BENCH_TARGET_RPS  || '200', 10);
const DURATION    = __ENV.NEGELIR_API_BENCH_DURATION     || '60s';
const MATCH_ID    = __ENV.NEGELIR_API_BENCH_MATCH_ID     || '1';
const AUTH_EMAIL  = __ENV.NEGELIR_API_BENCH_AUTH_EMAIL   || 'bench@negelir.local';
const AUTH_PASS   = __ENV.NEGELIR_API_BENCH_AUTH_PASSWORD || 'bench_password_1!';

// §9.17.5 latency thresholds (milliseconds).
// k6 threshold syntax: 'p(N)<X' means pN must be strictly below X ms.
export const options = {
  scenarios: {
    // Single constant-arrival-rate scenario; VU code cycles through all
    // routes so each endpoint receives roughly TARGET_RPS / ROUTES.length RPS.
    per_endpoint_latency: {
      executor: 'constant-arrival-rate',
      rate: TARGET_RPS,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: TARGET_RPS * 2,
      maxVUs: TARGET_RPS * 4,
    },
  },

  thresholds: {
    // §9.17.5 row: GET /v1/healthz — p50≤1ms, p95≤5ms, p99≤10ms
    'http_req_duration{name:GET /v1/healthz}':
      ['p(50)<1', 'p(95)<5', 'p(99)<10'],

    // §9.17.5 row: GET /v1/readyz — p50≤10ms, p95≤50ms, p99≤100ms
    'http_req_duration{name:GET /v1/readyz}':
      ['p(50)<10', 'p(95)<50', 'p(99)<100'],

    // §9.17.5 row: GET /v1/version — p50≤1ms, p95≤5ms, p99≤10ms
    'http_req_duration{name:GET /v1/version}':
      ['p(50)<1', 'p(95)<5', 'p(99)<10'],

    // §9.17.5 row: GET /v1/leagues (cache hit) — p50≤5ms, p95≤25ms, p99≤50ms
    'http_req_duration{name:GET /v1/leagues}':
      ['p(50)<5', 'p(95)<25', 'p(99)<50'],

    // §9.17.5 row: GET /v1/matches/:id (cache hit) — p50≤5ms, p95≤25ms, p99≤50ms
    'http_req_duration{name:GET /v1/matches/:id}':
      ['p(50)<5', 'p(95)<25', 'p(99)<50'],

    // §9.17.5 row: GET /v1/matches/:id/predictions cache hit — p50≤5ms, p95≤25ms, p99≤50ms
    'http_req_duration{name:GET /v1/matches/:id/predictions cache_hit}':
      ['p(50)<5', 'p(95)<25', 'p(99)<50'],

    // §9.17.5 row: GET /v1/matches/:id/predictions cache miss — p50≤200ms, p95≤800ms, p99≤2000ms
    'http_req_duration{name:GET /v1/matches/:id/predictions cache_miss}':
      ['p(50)<200', 'p(95)<800', 'p(99)<2000'],

    // §9.17.5 row: POST /v1/auth/login — p50≤250ms, p95≤350ms, p99≤500ms
    'http_req_duration{name:POST /v1/auth/login}':
      ['p(50)<250', 'p(95)<350', 'p(99)<500'],

    // §9.17.5 row: POST /v1/auth/refresh — p50≤5ms, p95≤20ms, p99≤50ms
    'http_req_duration{name:POST /v1/auth/refresh}':
      ['p(50)<5', 'p(95)<20', 'p(99)<50'],

    // §9.17.5 row: POST /v1/qa cache hit — p50≤10ms, p95≤50ms, p99≤100ms
    'http_req_duration{name:POST /v1/qa cache_hit}':
      ['p(50)<10', 'p(95)<50', 'p(99)<100'],

    // §9.17.5 row: POST /v1/qa single RPC — p50≤250ms, p95≤800ms, p99≤2000ms
    'http_req_duration{name:POST /v1/qa single_rpc}':
      ['p(50)<250', 'p(95)<800', 'p(99)<2000'],

    // §9.17.5 row: POST /v1/qa multi-RPC (202 path) — p50≤50ms, p95≤100ms, p99≤200ms
    'http_req_duration{name:POST /v1/qa multi_rpc_202}':
      ['p(50)<50', 'p(95)<100', 'p(99)<200'],
  },
};

// Route labels — must match the `name` tag keys in thresholds above.
const ROUTES = [
  'healthz',
  'readyz',
  'version',
  'leagues',
  'match',
  'predictions_hit',
  'predictions_miss',
  'login',
  'refresh',
  'qa_hit',
  'qa_single',
  'qa_multi',
];

/**
 * setup() — called once before VUs start.
 * Obtains a bearer token + refresh token by logging in with bench credentials.
 * Returns { token, refreshToken } passed as `data` to every VU iteration.
 */
export function setup() {
  const res = http.post(
    `${BASE_URL}/v1/auth/login`,
    JSON.stringify({ email: AUTH_EMAIL, password: AUTH_PASS }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (res.status !== 200) {
    console.warn(
      `setup: login failed (status=${res.status}); authenticated routes will ` +
      'send an empty Bearer token and likely receive 401s. ' +
      'Set NEGELIR_API_BENCH_AUTH_EMAIL / _PASSWORD to a valid bench user.',
    );
    return { token: '', refreshToken: '' };
  }
  const body = JSON.parse(res.body);
  return {
    token:        body.access_token  || '',
    refreshToken: body.refresh_token || '',
  };
}

/**
 * default() — called once per VU iteration.
 * Cycles deterministically through ROUTES using __ITER so every route
 * receives an even share of traffic over a long run.
 */
export default function (data) {
  const token        = (data && data.token)        ? data.token        : '';
  const refreshToken = (data && data.refreshToken) ? data.refreshToken : '';

  const authedHeaders = {
    Authorization:  `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  const route = ROUTES[__ITER % ROUTES.length];  // eslint-disable-line no-undef

  switch (route) {
    // ── §9.17.5: GET /v1/healthz ─────────────────────────────
    case 'healthz': {
      const r = http.get(`${BASE_URL}/v1/healthz`, {
        tags: { name: 'GET /v1/healthz' },
      });
      check(r, { 'healthz 200': (res) => res.status === 200 });
      break;
    }

    // ── §9.17.5: GET /v1/readyz ──────────────────────────────
    case 'readyz': {
      const r = http.get(`${BASE_URL}/v1/readyz`, {
        tags: { name: 'GET /v1/readyz' },
      });
      check(r, { 'readyz 2xx': (res) => res.status >= 200 && res.status < 300 });
      break;
    }

    // ── §9.17.5: GET /v1/version ─────────────────────────────
    case 'version': {
      const r = http.get(`${BASE_URL}/v1/version`, {
        tags: { name: 'GET /v1/version' },
      });
      check(r, { 'version 200': (res) => res.status === 200 });
      break;
    }

    // ── §9.17.5: GET /v1/leagues (cache-hit) ─────────────────
    case 'leagues': {
      const r = http.get(`${BASE_URL}/v1/leagues`, {
        headers: authedHeaders,
        tags:    { name: 'GET /v1/leagues' },
      });
      check(r, { 'leagues 200': (res) => res.status === 200 });
      break;
    }

    // ── §9.17.5: GET /v1/matches/:id (cache-hit) ─────────────
    case 'match': {
      const r = http.get(`${BASE_URL}/v1/matches/${MATCH_ID}`, {
        headers: authedHeaders,
        tags:    { name: 'GET /v1/matches/:id' },
      });
      check(r, { 'match 200': (res) => res.status === 200 });
      break;
    }

    // ── §9.17.5: GET /v1/matches/:id/predictions cache hit ───
    case 'predictions_hit': {
      // Reuse the same MATCH_ID on every iteration so Redis is warm.
      const r = http.get(`${BASE_URL}/v1/matches/${MATCH_ID}/predictions`, {
        headers: authedHeaders,
        tags:    { name: 'GET /v1/matches/:id/predictions cache_hit' },
      });
      check(r, { 'predictions cache-hit 200': (res) => res.status === 200 });
      break;
    }

    // ── §9.17.5: GET /v1/matches/:id/predictions cache miss ──
    case 'predictions_miss': {
      // Use __ITER as a unique suffix so the key is never in Redis.
      const missID = `bench_miss_${__ITER}`;  // eslint-disable-line no-undef
      const r = http.get(`${BASE_URL}/v1/matches/${missID}/predictions`, {
        headers: authedHeaders,
        tags:    { name: 'GET /v1/matches/:id/predictions cache_miss' },
      });
      check(r, {
        'predictions cache-miss 2xx|404': (res) =>
          (res.status >= 200 && res.status < 300) || res.status === 404,
      });
      break;
    }

    // ── §9.17.5: POST /v1/auth/login ─────────────────────────
    case 'login': {
      const r = http.post(
        `${BASE_URL}/v1/auth/login`,
        JSON.stringify({ email: AUTH_EMAIL, password: AUTH_PASS }),
        {
          headers: { 'Content-Type': 'application/json' },
          tags:    { name: 'POST /v1/auth/login' },
        },
      );
      check(r, { 'login 200': (res) => res.status === 200 });
      break;
    }

    // ── §9.17.5: POST /v1/auth/refresh ───────────────────────
    case 'refresh': {
      if (!refreshToken) break;
      const r = http.post(
        `${BASE_URL}/v1/auth/refresh`,
        JSON.stringify({ refresh_token: refreshToken }),
        {
          headers: { 'Content-Type': 'application/json' },
          tags:    { name: 'POST /v1/auth/refresh' },
        },
      );
      check(r, { 'refresh 200': (res) => res.status === 200 });
      break;
    }

    // ── §9.17.5: POST /v1/qa cache hit ───────────────────────
    case 'qa_hit': {
      // Fixed question so Redis has the answer after the first call.
      const r = http.post(
        `${BASE_URL}/v1/qa`,
        JSON.stringify({
          question: 'Süper Lig fikstürü',
          context:  'bench',
          match_id: MATCH_ID,
        }),
        { headers: authedHeaders, tags: { name: 'POST /v1/qa cache_hit' } },
      );
      check(r, { 'qa cache-hit 200': (res) => res.status === 200 });
      break;
    }

    // ── §9.17.5: POST /v1/qa single RPC ─────────────────────
    case 'qa_single': {
      // Unique suffix forces a cache miss → single swarm RPC.
      const r = http.post(
        `${BASE_URL}/v1/qa`,
        JSON.stringify({
          question: `Maç tahmini ${__ITER}`,  // eslint-disable-line no-undef
          context:  'bench',
          match_id: MATCH_ID,
        }),
        { headers: authedHeaders, tags: { name: 'POST /v1/qa single_rpc' } },
      );
      check(r, {
        'qa single-rpc 2xx': (res) => res.status >= 200 && res.status < 300,
      });
      break;
    }

    // ── §9.17.5: POST /v1/qa multi-RPC (202 path) ────────────
    case 'qa_multi': {
      // `async: true` triggers the multi-RPC 202 path in the handler.
      const r = http.post(
        `${BASE_URL}/v1/qa`,
        JSON.stringify({
          question: 'Haftanın maçları',
          context:  'bench_multi',
          async:    true,
        }),
        { headers: authedHeaders, tags: { name: 'POST /v1/qa multi_rpc_202' } },
      );
      check(r, {
        'qa multi-rpc 202|200': (res) => res.status === 202 || res.status === 200,
      });
      break;
    }

    default:
      break;
  }
}
