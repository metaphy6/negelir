# 💰 MONETIZATION — tier-based commercialization (built-but-dormant)

> **Status:** Anchor doc for the commercial layer of Negelir. The
> system is engineered for a tiered subscription model
> (Free / Pro / Premium) with **edge-only enforcement** at the Go
> API. The full machinery — entitlement engine, rate limiter,
> per-tier feature gates, billing-ready hooks — ships **dormant**:
> shipped to production behind a single feature flag
> (`MONETIZATION_ENABLED=false`), works fully in dev/test, and
> flips on the day the business is ready to charge.
>
> **Companion docs:** [`LEAGUE_CATALOG.md`](LEAGUE_CATALOG.md)
> (per-league entitlements), [`COMPETITIONS.md`](COMPETITIONS.md)
> (per-competition entitlements), [`ENRICHMENT_DATA.md`](ENRICHMENT_DATA.md)
> (per-market entitlements), [`SECURITY.md`](SECURITY.md) (auth
> tokens, scopes, abuse).

---

## 0. Why this doc exists

The user's directive is unambiguous:

> *"Add monetization … parameterize features, rates, quotas. The
> functionality should be there, it should work but should be
> dormant — works in dev and tests but ready to flip in production
> when the time comes."*

Two constraints make this non-trivial:

1. **The commercial layer must not silently couple to the
   prediction layer.** A poorly-architected commercial layer leaks
   business rules into the predictor (e.g. a "premium-only" market
   gets a different model). That is unacceptable; the predictor
   doesn't know who's paying.
2. **It must be ready to flip on by config change alone.** No
   migration, no backfill, no last-minute schema change. Day-1
   production already accepts `MONETIZATION_ENABLED=true` and
   correctly serves Free / Pro / Premium tokens.

This doc defines the layer that satisfies both.

---

## 1. Doctrine (non-negotiable)

| # | Rule | Concretely |
|---|---|---|
| M1 | **Edge-only enforcement** | All entitlement decisions happen in the Go API (`server/internal/auth/entitlements`). The Python predictor swarm has zero awareness of who's calling. |
| M2 | **Single-source entitlement file** | `xops/monetization/entitlements.yaml` is *the* policy. Every gate the API enforces resolves to a row in this file. No conditional logic in handlers — only lookups. |
| M3 | **Tier × resource matrix** | A subscription tier (Free/Pro/Premium) crossed with a resource (league_id, competition_id, market_family) produces an `allow|deny`. No other axes (time of day, country, user history) in v1. |
| M4 | **Free is functional, not crippled** | Free tier serves real predictions on T1 leagues for basic markets. It's a discovery surface, not a teaser. |
| M5 | **Quotas are per-token, not per-IP** | Rate-limit and daily-call quotas live in the auth token's claims; IP rate limit (in `SECURITY.md`) is the abuse-prevention layer, not the commercial layer. |
| M6 | **Dormant ≠ stub** | When `MONETIZATION_ENABLED=false`, the entitlement engine returns "allow all" — but the engine *runs*. The lookup happens, the metric increments, the audit log records. Only the deny branch is short-circuited. This is what makes flipping the flag safe. |
| M7 | **No payment processor in v1** | The system is billing-ready (token claims include `tier`, `expires_at`, `customer_id`) but does not integrate Stripe/Iyzico/etc. That is a Phase 20.x add-on. |
| M8 | **Tier upgrade is instant** | Token re-issue (or token claim refresh from Redis) reflects the new tier within `cfg.tier_propagation_seconds_max` (default 30s). No batch jobs. |

---

## 2. The three tiers

| Tier | Default API behavior | Who | Realistic price (v1 estimate, illustrative) |
|---|---|---|---|
| **Free** | T1 leagues; 1X2/BTTS/totals (over-2.5/under-2.5); 100 calls/day; 10 calls/min | Anonymous (no auth) and registered free users | $0 |
| **Pro** | T1+T2 leagues; +Asian handicap, double-chance, exact score, HT/FT, cards markets; 5,000 calls/day; 60 calls/min; access to historical predictions | Registered + paid | TRY 99/mo ≈ $3 |
| **Premium** | All published leagues+competitions, all markets including player-prop and weather-sensitive; 50,000 calls/day; 600 calls/min; SLA dashboards | Registered + paid + power-user | TRY 299/mo ≈ $9 |
| **Admin** | Everything Premium has + T3 (research) leagues + admin-only endpoints (model debug, drift internals) | Internal staff only | n/a |

Tier is a **single field on the auth token's claims**:
`{"tier": "pro" | "free" | "premium" | "admin"}`. The token also
carries `subscription_id`, `customer_id`, and `expires_at` for
billing-system integration in Phase 20.x.

---

## 3. The entitlement engine

### 3.1 The decision

```go
// server/internal/auth/entitlements/engine.go
type EntitlementDecision struct {
    Allow      bool
    DenyReason string // "tier_too_low", "league_not_in_tier", "market_not_in_tier", "quota_exceeded"
    Tier       Tier
}

func Decide(ctx context.Context, claims *Claims, req ResourceRequest) EntitlementDecision {
    if !cfg.MonetizationEnabled {
        return EntitlementDecision{Allow: true, Tier: claims.Tier}
    }
    // ... lookup in entitlements.yaml ...
}
```

The decision is a **pure function** of:
1. The token claims (`tier`, optional `customer_id`).
2. The resource being requested (`league_id`, `competition_id`,
   `market_family`).
3. The current quota counter for the token (Redis).
4. The single config flag `MONETIZATION_ENABLED`.

No DB read, no HTTP call. Hot path is sub-millisecond.

### 3.2 The policy file

`xops/monetization/entitlements.yaml`:

```yaml
schema_version: 1

# League-tier entitlements — which subscription tier sees which league tier.
# Cross-references LEAGUE_CATALOG.md tiers (T1/T2/T3 — *the league's tier*)
# with subscription tiers (free/pro/premium/admin — *the user's tier*).
league_tier_access:
  T1: [free, pro, premium, admin]
  T2: [pro, premium, admin]
  T3: [admin]                    # research only; never paid

# Per-market families. Mapped to canonical market IDs in
# ai/common/betting_markets.json.
market_family_access:
  basic_1x2_btts_totals: [free, pro, premium, admin]
  asian_handicap:        [pro, premium, admin]
  exact_score_htft:      [pro, premium, admin]
  cards:                 [pro, premium, admin]
  corners:               [pro, premium, admin]
  player_props:          [premium, admin]
  weather_specials:      [premium, admin]
  live_in_play:          [premium, admin]    # Phase 5b/future

# Per-competition overrides. Used for one-off competitions
# (Super Cups, Club World Cup) where a tier upgrade is offered as
# a promo. Empty in v1 — included for the engine to know the lookup
# path exists.
competition_overrides: {}

# Quotas — per token, per day, per minute. Burst handled by the
# rate limiter in front (per-token bucket).
quotas:
  free:
    calls_per_day: 100
    calls_per_minute: 10
    historical_lookback_days: 7
    websocket_concurrent: 0
  pro:
    calls_per_day: 5000
    calls_per_minute: 60
    historical_lookback_days: 365
    websocket_concurrent: 1
  premium:
    calls_per_day: 50000
    calls_per_minute: 600
    historical_lookback_days: -1   # unlimited
    websocket_concurrent: 5
  admin:
    calls_per_day: -1
    calls_per_minute: -1
    historical_lookback_days: -1
    websocket_concurrent: -1
```

### 3.3 Where decisions are enforced

Every public HTTP handler in `server/cmd/api` ends in:

```go
func handlerPredict(w http.ResponseWriter, r *http.Request) {
    claims := auth.ClaimsFromContext(r.Context())
    req := ResourceRequest{
        LeagueID: chi.URLParam(r, "league_id"),
        // ...
    }
    if d := entitlements.Decide(r.Context(), claims, req); !d.Allow {
        api.WriteDeny(w, d)        // 403 + structured deny code
        metrics.EntitlementDenied.WithLabelValues(d.DenyReason).Inc()
        return
    }
    // ... handler body ...
}
```

A static-analysis test (`server/internal/auth/entitlements/coverage_test.go`)
walks the handler tree and asserts every public endpoint either
calls `entitlements.Decide()` or is in the explicit allowlist
(health, metrics, anonymous discovery).

---

## 4. The market families

`ai/common/betting_markets.json` carries the canonical market IDs.
Each ID maps to exactly one **family** (the entitlement axis):

```json
{
  "schema_version": 2,
  "markets": [
    { "id": "1x2", "family": "basic_1x2_btts_totals", "name_tr": "Maç Sonucu" },
    { "id": "btts", "family": "basic_1x2_btts_totals", "name_tr": "Karşılıklı Gol" },
    { "id": "ou_2_5", "family": "basic_1x2_btts_totals", "name_tr": "2.5 Üst/Alt" },

    { "id": "ah_+0_5", "family": "asian_handicap", "name_tr": "Asya Handikap +0.5" },
    { "id": "exact_score", "family": "exact_score_htft", "name_tr": "Skor Tahmini" },
    { "id": "ht_ft", "family": "exact_score_htft", "name_tr": "İY/MS" },

    { "id": "ou_cards_4_5", "family": "cards", "name_tr": "4.5 Kart Üst/Alt" },
    { "id": "team_corners_first", "family": "corners", "name_tr": "İlk Korner" },

    { "id": "anytime_scorer", "family": "player_props", "name_tr": "Maç İçinde Gol Atan" },
    { "id": "shots_on_target_player_2_5", "family": "player_props", "name_tr": "Oyuncu Şutu" },

    { "id": "ou_2_5_with_wind_warning", "family": "weather_specials", "name_tr": "Rüzgârlı Maçta 2.5 Üst" }
  ]
}
```

**Adding a market** = three changes:

1. Add to `betting_markets.json` with a `family`.
2. Predictor implements (and the calibration profile per
   `COMPETITIONS.md` §4 includes it).
3. If the family is new, add a row to `market_family_access` in
   `entitlements.yaml`.

Skipping (3) means the market is server-side accessible only to
admin tokens — a safe default.

---

## 5. Quotas & rate limiting

### 5.1 Per-token quota

A Redis sorted-set per `(token_id, window_id)`. The window granularity:

- 60-second sliding window for `calls_per_minute`.
- 24-hour fixed window aligned to UTC midnight for `calls_per_day`.

Reads at handler-time: `INCR` + `EXPIRE` (one Redis round-trip;
batched if pipelining). Latency budget: < 2 ms p99.

### 5.2 Per-token quota propagation in the dormant state

When `MONETIZATION_ENABLED=false`:

- The Redis counter still increments. (We want the metrics.)
- The deny branch never fires.
- A daily report (`xops/monetization/quota_report.py`) shows what
  *would* have been denied — useful for capacity-planning before
  flipping the flag.

### 5.3 Burst behavior

Each tier has a burst-allowance equal to `0.5 × calls_per_minute`
(half a minute of extra capacity). Implemented as a token bucket
in front of the per-minute counter.

---

## 6. The dormant flag — `MONETIZATION_ENABLED`

A single env var, documented in `xops/env/.env.example`:

```bash
# Master switch for the commercial layer.
# false (default) — entitlement engine returns allow-all but still
#                   runs counters + audit logs. Safe everywhere.
# true            — full enforcement; respects entitlements.yaml
#                   and quota limits.
MONETIZATION_ENABLED=false
```

Both `ai/common/config.py` and `server/internal/config` register
this. The Python side carries it because some predictors (e.g. the
optional player-props enricher) skip work when the feature is
gated everywhere — saves cycles when no Premium tokens exist yet.

**Toggling the flag is a single config change + a server restart
(or a `kill -HUP` of the API).** No data migration, no schema
change.

---

## 7. Tier × league × competition matrix

The full decision table, exhaustively:

```
Subscriber tier  ×  League catalog tier  ×  Market family  →  Decision

free       ×  T1   ×  basic_1x2_btts_totals  → ALLOW
free       ×  T1   ×  asian_handicap          → DENY (market_not_in_tier)
free       ×  T1   ×  player_props            → DENY (market_not_in_tier)
free       ×  T2   ×  *                       → DENY (league_not_in_tier)
free       ×  T3   ×  *                       → DENY (league_not_in_tier)

pro        ×  T1   ×  basic_1x2_btts_totals  → ALLOW
pro        ×  T1   ×  asian_handicap          → ALLOW
pro        ×  T1   ×  cards                   → ALLOW
pro        ×  T1   ×  player_props            → DENY (market_not_in_tier)
pro        ×  T2   ×  basic_1x2_btts_totals  → ALLOW
pro        ×  T2   ×  asian_handicap          → ALLOW
pro        ×  T2   ×  player_props            → DENY
pro        ×  T3   ×  *                       → DENY

premium    ×  T1   ×  *                       → ALLOW
premium    ×  T2   ×  *                       → ALLOW
premium    ×  T3   ×  *                       → DENY (league_not_in_tier; T3 is admin-only)

admin      ×  *    ×  *                       → ALLOW
```

Every cell is a row in or derivable from `entitlements.yaml`. CI
runs `xops/monetization/coverage_test.py` to assert the matrix is
exhaustive (no `(tier, league_tier, market_family)` triple lacks a
decision).

---

## 8. Audit & observability

Every entitlement decision (allow OR deny) emits a counter:

```
entitlement_decisions_total{tier="free",league_tier="T1",market_family="basic_1x2_btts_totals",decision="allow"}
entitlement_decisions_total{tier="free",league_tier="T2",market_family="basic_1x2_btts_totals",decision="deny",reason="league_not_in_tier"}
```

A small percentage (sampled at `cfg.entitlement_audit_sample_rate`,
default 0.01) lands in the audit log
(`server/internal/audit/entitlements.go`) with full context: token
ID, request shape, decision, deny reason, latency. Used for:

- Detecting tier-misconfiguration ("why are 80% of pro tokens
  hitting `quota_exceeded`?").
- Forensics on suspected token theft.
- Capacity planning before flipping `MONETIZATION_ENABLED=true`.

The dashboard (Phase 11/12) has a dedicated "monetization" panel
that's hidden until the flag flips on.

---

## 9. Discovery vs. paywall (the UX rule)

A core product rule, encoded in the API:

- **Discovery surfaces** (fixture lists, league standings, basic
  scoreboards, public news) are **never gated**. Anonymous tokens
  see them. This is what makes the system crawlable + shareable.
- **Predictions** are tier-gated.

The split is a per-endpoint allowlist
(`server/internal/auth/entitlements/discovery_allowlist.go`). Every
endpoint that returns publicly-available facts is on it; every
endpoint that returns inferences from our model is off it.

The Flutter app (Phase 15) renders deny-states as upsell prompts,
not error screens — *"Bu pazar Pro abonelik gerektiriyor."* with a
deep link to the upgrade flow (which is a stub in v1 — points to a
contact form).

---

## 10. Billing-readiness hooks (no processor in v1)

The token shape is forward-compatible:

```go
type Claims struct {
    Sub            string    // user ID
    Tier           Tier      // free / pro / premium / admin
    SubscriptionID string    // empty for free; opaque ID for paid
    CustomerID     string    // opaque external ID (Iyzico/Stripe later)
    ExpiresAt      int64     // unix; renewal tracked externally
    IssuedAt       int64
    BillingState   string    // "active" | "past_due" | "cancelled" | "trial"
}
```

A `past_due` claim in `BillingState` triggers a **soft downgrade**:
the engine treats the user as Free for the next request, the
response carries an `X-Subscription-State: past_due` header, and a
deferred event lands on the bus for the (Phase 20.x) billing
worker to act on.

This pre-wires Stripe/Iyzico/Paddle integration without binding to
any of them.

---

## 11. Testing matrix

`make test.monetization` runs:

| Test | Asserts |
|---|---|
| Engine returns allow-all when flag is false | M6 holds |
| Every public handler calls `entitlements.Decide()` or is on discovery allowlist | M1 + §3.3 |
| Every `(subscriber_tier, league_tier, market_family)` triple has a decision | §7 exhaustiveness |
| Every market in `betting_markets.json` has a `family` | §4 invariant |
| Every family in `betting_markets.json` has a row in `market_family_access` | §4 invariant |
| Quota counter increments even when flag is false | §5.2 |
| Token with `BillingState=past_due` gets soft-downgraded | §10 |
| Tier propagation latency < `cfg.tier_propagation_seconds_max` | M8 |
| Deny responses include structured `reason` codes | §3.1 |
| Deny responses do **not** leak prediction content | regression: SECURITY.md §… |
| `entitlements.yaml` schema validates against committed JSON Schema | governance |

---

## 12. Pivot v3 placement

Per [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md):

| Code | Lives under | Reason |
|---|---|---|
| Entitlement engine | `server/internal/auth/entitlements/` | Edge enforcement is API's job |
| Quota Redis writer | `server/internal/auth/quota/` | Same — server owns request-scoped state |
| `entitlements.yaml` policy file | `xops/monetization/` | Operational artifact; lives near other ops files |
| Coverage test | `xops/monetization/` | Operational verification |
| Tier-aware Python config gate | `common/config.py` (today: `ai/common/config.py`) | The Python side reads the master flag for cycle-saving only |
| Predictor swarm | `swarm/` (today: `ai/`) | **Knows nothing about monetization.** M1. |

---

## 13. Definition-of-Done for "monetization shipped dormant"

- [ ] `MONETIZATION_ENABLED` env var documented in
      `xops/env/.env.example`, defaulting to `false`.
- [ ] `entitlements.yaml` committed with schema validation in CI.
- [ ] Engine code in `server/internal/auth/entitlements/`.
- [ ] Quota counter in Redis with metric exposure.
- [ ] Every public handler audited (coverage test green).
- [ ] All §11 tests green.
- [ ] Audit log + Prometheus metrics live.
- [ ] Discovery allowlist explicit and reviewed.
- [ ] Token shape includes billing-ready fields (no processor wired).
- [ ] Phase 20 tracker rows show "shipped dormant" status.
- [ ] One end-to-end smoke test: flip the flag in a staging env,
      confirm the deny matrix matches §7, flip back to false.

---

## 14. What this doc does **not** cover

- **Payment processor integration** — Phase 20.x; out of scope for
  the dormant ship.
- **Tax / VAT / invoicing** — same; legal layer comes after the
  business decision to monetize.
- **Marketing pages, landing flows, upgrade UX copy** — Flutter +
  product layer (Phase 15+).
- **Anti-fraud (chargeback patterns, account linking)** — handled
  in Phase 20.x with the processor integration.
- **Affiliate / B2B API access** — possible later as an "enterprise"
  tier with its own quota row; explicitly not in v1 to keep the
  matrix simple.

---

## 15. Reading order for new contributors

1. This doc up to §3 — the doctrine + decision shape.
2. `LEAGUE_CATALOG.md` §1 — the league-tier model that crosses
   with subscriber tier in §7 here.
3. `ENRICHMENT_DATA.md` §10 — which enrichment plane each Premium
   market depends on.
4. `SECURITY.md` (existing) — auth tokens + abuse-prevention layer
   that sits underneath this commercial layer.
5. ROADMAP Phase 20 — the rollout plan for shipping dormant +
   eventually flipping the flag.
