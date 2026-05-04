-- Phase 7 §7.3 — sec.rate.v1 atomic bucket-check + denylist-lookup.
--
-- VERSION: 1.0.0
-- SHA256: ad2fabdca56c380f07465d1028a31ad5cf1363a0de04384b6de7b9bcb276bdfa
--
-- The Go gateway calls this script via `EVALSHA` on every request
-- entering `/v1/*`. One round-trip, atomic by Redis's single-threaded
-- execution model. Returns `(allow|throttle|denied, remaining,
-- retry_after_ms, cost_charged)`.
--
-- KEYS:
--   [1] = "sec:bucket:<subject>"     — GCRA bucket state (a single string
--                                      holding the next-allowed-monotonic-ms)
--   [2] = "sec:denylist:<subject>"   — denylist hash (presence = denied)
--
-- ARGV:
--   [1] = capacity            (integer; max burst tokens)
--   [2] = refill_per_s        (float; tokens per second)
--   [3] = cost                (integer; weighted token cost for this call)
--   [4] = now_ms              (integer; gateway-supplied monotonic ms)
--   [5] = idle_ttl_s          (integer; bucket-key TTL when idle)
--
-- Returns: { status_string, remaining_int, retry_after_ms_int, cost_charged_int }
--
-- Doctrine notes:
--   * GCRA chosen over leaky-bucket because it needs only one
--     scalar of state per subject (the next-allowed timestamp).
--   * Time arithmetic uses gateway-supplied monotonic ms — Redis's
--     `TIME` is wall-clock and can rewind across NTP slews.
--   * Denylist short-circuit fires BEFORE bucket charge so a denied
--     subject never gets a free token (defense-in-depth: even if
--     the gateway forgets to check the return code, the bucket
--     still decrements; even if it doesn't, the response is denied).

local bucket_key = KEYS[1]
local denylist_key = KEYS[2]

local capacity = tonumber(ARGV[1])
local refill_per_s = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now_ms = tonumber(ARGV[4])
local idle_ttl_s = tonumber(ARGV[5])

-- Defensive parameter validation. Wrong/zero capacity must NOT
-- silently allow infinite traffic.
if capacity == nil or capacity <= 0 then
    return {"error", 0, 0, 0}
end
if refill_per_s == nil or refill_per_s <= 0 then
    return {"error", 0, 0, 0}
end
if cost == nil or cost < 0 then
    return {"error", 0, 0, 0}
end
if now_ms == nil or now_ms < 0 then
    return {"error", 0, 0, 0}
end

-- 1. Denylist short-circuit. EXISTS is O(1).
if redis.call("EXISTS", denylist_key) == 1 then
    -- Surface the residual TTL as retry_after for the gateway's
    -- 403 response. PTTL returns ms; -1 means no expiry; -2 means
    -- key gone (race with TTL expiry between EXISTS and PTTL —
    -- treat as not-denied to avoid false-deny).
    local ttl_ms = redis.call("PTTL", denylist_key)
    if ttl_ms == -2 then
        -- Key disappeared between EXISTS and PTTL; fall through to
        -- bucket math (the next call will see no-deny cleanly).
    else
        if ttl_ms == -1 then ttl_ms = idle_ttl_s * 1000 end
        return {"denied", 0, ttl_ms, 0}
    end
end

-- 2. GCRA bucket math.
-- Token-cost-per-ms = refill_per_s / 1000.
-- "Increment" per request = cost / refill_per_s seconds, in ms.
local emission_interval_ms = (cost * 1000.0) / refill_per_s
local burst_tolerance_ms = (capacity * 1000.0) / refill_per_s

local tat_str = redis.call("GET", bucket_key)
local tat = tonumber(tat_str)
if tat == nil or tat < now_ms then
    tat = now_ms
end

local new_tat = tat + emission_interval_ms
local allow_at = new_tat - burst_tolerance_ms

if now_ms < allow_at then
    -- Throttle: do NOT advance tat (no double-charge on retries
    -- inside the retry-after window).
    local retry_after = math.ceil(allow_at - now_ms)
    return {"throttle", 0, retry_after, 0}
end

-- Allow: persist new tat with idle TTL.
redis.call("SET", bucket_key, tostring(new_tat), "EX", idle_ttl_s)

local remaining_ms = burst_tolerance_ms - (new_tat - now_ms)
local remaining = math.floor((remaining_ms * refill_per_s) / 1000.0)
if remaining < 0 then remaining = 0 end

return {"allow", remaining, 0, cost}
