-- Phase 8 §8.8 — denylist decimation atomic sweeper.
--
-- VERSION: 1.0.0
-- SHA256: fb615689a03934646d6578e0d10d9cc3fafe7e354929dbc8ce7e6a93a0d7436c
--
-- Sole purpose: when the Redis sorted-set tracking active denylist
-- entries crosses `cap`, evict the bottom decile (oldest scores) in
-- a single atomic call, clear the cardinality-cap flag if we drop
-- back below `cap`, and return a summary the agent uses to publish
-- a `maint.event.v1{kind=denylist_decimate}` notification.
--
-- The Go gateway has a byte-equivalent embedded copy under
-- `server/internal/sec/embedded/`; the parity test in the maint
-- test suite asserts they stay in lock-step.
--
-- KEYS:
--   [1] = "sec:denylist:zset"        — sorted set: member=subject, score=last_seen_ms
--   [2] = "sec:denylist:capped"      — cardinality-cap flag (string "1" when set)
--
-- ARGV:
--   [1] = now_ms          (integer; for forensic logging only — the
--                          eviction itself uses score-rank order)
--   [2] = cap             (integer; cfg.sec_denylist_max_entries; 0 = unbounded)
--
-- Returns (numerically-keyed table — Redis flattens to {evicted,
-- decile, zcard, cap_cleared_int}):
--   { evicted_count, decile_size, new_zcard, cap_cleared }
--
-- Doctrine — what this script DOES NOT do:
--   * It does NOT touch per-subject denylist entries (those are
--     individual `sec:denylist:<subject>` keys with their own TTLs).
--     This sweep mutates only the bookkeeping zset; the gateway
--     consults the per-subject keys directly. A subject evicted from
--     the zset will simply NOT appear in cardinality counts and
--     becomes invisible to the operator dashboard, but its TTL
--     continues to enforce blocking until natural expiry. v2 may
--     add a `DEL` pass; v1 deliberately keeps the eviction lossless
--     on the security guarantee.

local zkey = KEYS[1]
local capkey = KEYS[2]
local now_ms = tonumber(ARGV[1]) or 0
local cap = tonumber(ARGV[2]) or 0

local zcard = redis.call("ZCARD", zkey)
if cap == 0 or zcard <= cap then
  return { 0, 0, zcard, 0 }
end

-- Decile is at least 1; we never evict less than one element when
-- the cap is breached.
local decile = math.floor(zcard / 10)
if decile < 1 then decile = 1 end

local evicted = redis.call("ZREMRANGEBYRANK", zkey, 0, decile - 1)
local new_zcard = redis.call("ZCARD", zkey)

local cleared = 0
if new_zcard <= cap then
  -- DEL returns number of keys removed; we don't care if it's 0
  -- (the cap flag may have been auto-expired by another process).
  redis.call("DEL", capkey)
  cleared = 1
end

return { evicted, decile, new_zcard, cleared }
