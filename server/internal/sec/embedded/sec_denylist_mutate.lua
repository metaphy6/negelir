-- Phase 7 §7.3 — sec.rate.v1 atomic denylist add/remove.
--
-- VERSION: 1.0.0
-- SHA256: 22df071d92402e35f5e6b84e0b51245c8e11643e598cb7aeee1a43d7910f0737
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
--
-- Returns:
--   { "added", current_count }
--   { "removed", current_count }
--   { "rejected_capped", current_count }   — when max_entries exceeded
--   { "noop", current_count }              — remove on missing key
--   { "error", 0 }                         — bad action

local denylist_key = KEYS[1]
local capped_flag = KEYS[2]

local action = ARGV[1]
local ttl_s = tonumber(ARGV[2])
local max_entries = tonumber(ARGV[3])
local reason = ARGV[4] or ""

-- Track total denylist cardinality with a separate counter key
-- (faster than DBSIZE-style scans). Real entries follow the
-- pattern "sec:denylist:<subject>"; the counter key is
-- "sec:denylist:_count" (leading underscore prevents subject-name
-- collision since IPs/client_ids never start with "_:").
local count_key = "sec:denylist:_count"

if action == "add" then
    if ttl_s == nil or ttl_s <= 0 then
        return {"error", 0}
    end
    local existed = redis.call("EXISTS", denylist_key)
    -- Cardinality cap check fires only on NEW entries (re-adds of
    -- existing subjects refresh TTL without growing the set).
    if existed == 0 and max_entries > 0 then
        local current = tonumber(redis.call("GET", count_key) or "0")
        if current >= max_entries then
            -- Set the cap flag so the gateway switches to subnet-mode
            -- denylist on the next request. TTL kept short so the
            -- flag clears once the sweeper drains entries below the
            -- cap (sweeper resets the flag explicitly; this TTL is
            -- a safety net).
            redis.call("SET", capped_flag, "1", "EX", 300)
            return {"rejected_capped", current}
        end
    end
    redis.call("SET", denylist_key, reason, "EX", ttl_s)
    if existed == 0 then
        local new_count = redis.call("INCR", count_key)
        return {"added", new_count}
    else
        local current = tonumber(redis.call("GET", count_key) or "0")
        return {"added", current}
    end

elseif action == "remove" then
    local existed = redis.call("DEL", denylist_key)
    if existed == 1 then
        local new_count = redis.call("DECR", count_key)
        if new_count < 0 then
            -- Counter drift recovery: never go negative.
            redis.call("SET", count_key, "0")
            new_count = 0
        end
        return {"removed", new_count}
    else
        local current = tonumber(redis.call("GET", count_key) or "0")
        return {"noop", current}
    end
end

return {"error", 0}
