-- Phase 7 §7.3 — sec.rate.v1 atomic denylist add/remove.
--
-- VERSION: 1.1.0
-- SHA256: a3f8e442e0115f067154547f878fe03ef580df365826b7484933d76f30642621
--
-- The Python `sec.rate.v1` agent calls this script on every burst-
-- trip / operator override. Atomic; survives at-least-once redelivery
-- without double-counting (idempotent on `add` for the same subject:
-- the TTL is reset, not stacked).
--
-- KEYS:
--   [1] = "sec:denylist:<subject>"
--   [2] = "sec:denylist:capped"      — cardinality-cap flag (set when
--                                      cfg.sec_denylist_max_entries is
--                                      reached; cleared by sweeper)
--
-- ARGV:
--   [1] = action          ("add" | "remove")
--   [2] = ttl_s           (integer; ignored for "remove")
--   [3] = max_entries     (integer; 0 = unbounded)
--   [4] = reason          (string; written into the value for forensic grep)
--   [5] = now_ms          (integer; gateway-supplied monotonic ms — used
--                          for lazy ZSET eviction so the cardinality
--                          tracker stays truthful as Redis TTLs expire
--                          underneath us. REQUIRED on add.)
--
-- Returns:
--   { "added", current_count }
--   { "removed", current_count }
--   { "rejected_capped", current_count }   — when max_entries exceeded
--   { "noop", current_count }              — remove on missing key
--   { "error", 0 }                         — bad action
--
-- Cardinality tracking — v1.1.0 design note:
--
-- v1.0.0 used a plain `INCR/DECR sec:denylist:_count` counter. That
-- was broken: when an entry's TTL expires naturally inside Redis the
-- counter is NOT decremented, so after enough churn the counter
-- over-reports cardinality and the cap flag flips on permanently —
-- the gateway then over-blocks legitimate users via subnet-mode.
-- The Phase 8 sweeper would have repaired it lazily, but the cap
-- flag is a security-sensitive availability switch and "broken until
-- Phase 8" is not acceptable.
--
-- v1.1.0 replaces the counter with a Redis sorted set
-- `sec:denylist:_zset` whose members are the denylist key names and
-- whose scores are the absolute expiration timestamps in ms. On every
-- mutation we lazily evict expired members via `ZREMRANGEBYSCORE`
-- before the cap check, so the cardinality is always truthful. ZCARD
-- is O(1) on Redis sorted sets; ZREMRANGEBYSCORE is O(log(N) + M)
-- where M is the number of evicted members — empty in steady state.

local denylist_key = KEYS[1]
local capped_flag = KEYS[2]

local action = ARGV[1]
local ttl_s = tonumber(ARGV[2])
local max_entries = tonumber(ARGV[3])
local reason = ARGV[4] or ""
local now_ms = tonumber(ARGV[5])

local zset_key = "sec:denylist:_zset"

-- Lazy expiry sweep: drop members whose score (expiration_ms) is
-- in the past. Steady-state work is empty.
local function sweep_expired()
    if now_ms ~= nil and now_ms > 0 then
        redis.call("ZREMRANGEBYSCORE", zset_key, "-inf", "(" .. tostring(now_ms))
    end
end

local function current_count()
    return tonumber(redis.call("ZCARD", zset_key)) or 0
end

if action == "add" then
    if ttl_s == nil or ttl_s <= 0 then
        return {"error", 0}
    end
    if now_ms == nil or now_ms <= 0 then
        -- Adds REQUIRE now_ms so the ZSET score is meaningful.
        return {"error", 0}
    end
    sweep_expired()
    local existed = redis.call("EXISTS", denylist_key)
    -- Cardinality cap fires only on NEW entries (re-adds of existing
    -- subjects refresh TTL without growing the set).
    if existed == 0 and max_entries ~= nil and max_entries > 0 then
        local current = current_count()
        if current >= max_entries then
            redis.call("SET", capped_flag, "1", "EX", 300)
            return {"rejected_capped", current}
        end
    end
    redis.call("SET", denylist_key, reason, "EX", ttl_s)
    local expires_at = now_ms + (ttl_s * 1000)
    -- ZADD overwrites the score on re-add; matches the SET EX TTL
    -- overwrite semantics.
    redis.call("ZADD", zset_key, expires_at, denylist_key)
    return {"added", current_count()}

elseif action == "remove" then
    sweep_expired()
    local existed = redis.call("DEL", denylist_key)
    redis.call("ZREM", zset_key, denylist_key)
    if existed == 1 then
        return {"removed", current_count()}
    else
        return {"noop", current_count()}
    end
end

return {"error", 0}
