package sec

import (
	"context"
	"sync"
	"time"
)

// RateStatus mirrors the Lua script's return enum (sec_rate_check.lua).
type RateStatus string

const (
	RateAllow    RateStatus = "allow"
	RateThrottle RateStatus = "throttle"
	RateDenied   RateStatus = "denied"
	RateError    RateStatus = "error"
)

// RateDecision is the gateway's view of one rate-check result.
type RateDecision struct {
	Status        RateStatus
	Remaining     float64       // tokens left in the bucket post-charge
	RetryAfter    time.Duration // 0 for allow; positive for throttle / denied
	CostCharged   int           // tokens actually charged (zero for denied)
	UsedFallback  bool          // true when the secondary in-process bucket served the call
	UsedTier      string        // "redis" | "secondary" | "denylist"
	SubjectKey    string        // bucket key used (e.g. "203.0.113.7/32")
}

// RateChecker is the interface the middleware speaks to. The
// production implementation is `RedisRateChecker` (calls EVALSHA
// against sec_rate_check.lua); tests inject a fake.
type RateChecker interface {
	Check(ctx context.Context, subject string, capacity int, refillPerS float64, cost int) (RateDecision, error)
}

// SecondaryBucket is the in-process GCRA fallback used when Redis is
// unreachable or the EVALSHA round-trip blew the timeout. It is
// intentionally per-process (no cross-instance coordination) — the
// gateway's quorum live behind a load balancer, so the per-process
// budget acts as a coarse circuit-breaker against the load-balancer
// fanning a misbehaving subject across N instances.
//
// Doctrine: the secondary tier is FAIL-OPEN (lower capacity than
// Redis, refills slower) but it never DENIES — a sustained Redis
// outage degrades to "every legitimate user is throttled to the
// secondary's pace", not to "every user is denied". Denylisting only
// happens when Redis is healthy enough to consult sec.denylist.v1.
type SecondaryBucket struct {
	capacity   float64
	refillPerS float64

	mu      sync.Mutex
	buckets map[string]*gcraState
	maxKeys int
}

type gcraState struct {
	tokens    float64
	updatedAt time.Time
}

// NewSecondaryBucket builds a fail-open in-process limiter. `maxKeys`
// caps the LRU size; an entry past the cap evicts the oldest. Zero
// or negative means "unbounded" (only safe in tests).
func NewSecondaryBucket(capacity int, refillPerS float64, maxKeys int) *SecondaryBucket {
	cap := float64(capacity)
	if cap < 1 {
		cap = 1
	}
	if refillPerS <= 0 {
		refillPerS = 1
	}
	return &SecondaryBucket{
		capacity:   cap,
		refillPerS: refillPerS,
		buckets:    make(map[string]*gcraState),
		maxKeys:    maxKeys,
	}
}

// Check serves the same contract as RateChecker.Check but always
// against the in-process bucket. Returns RateAllow or RateThrottle
// only — never RateDenied (denylist enforcement requires Redis
// coordination).
//
// `cost` is the weighted token cost for the endpoint (per
// endpoint_costs.yaml). A cost of 0 always allows.
func (b *SecondaryBucket) Check(ctx context.Context, subject string, capacity int, refillPerS float64, cost int) (RateDecision, error) {
	if cost <= 0 {
		return RateDecision{
			Status:       RateAllow,
			Remaining:    b.capacity,
			SubjectKey:   subject,
			UsedFallback: true,
			UsedTier:     "secondary",
			CostCharged:  0,
		}, nil
	}
	now := time.Now()
	b.mu.Lock()
	defer b.mu.Unlock()
	st, ok := b.buckets[subject]
	if !ok {
		st = &gcraState{tokens: b.capacity, updatedAt: now}
		b.buckets[subject] = st
		b.evictIfFull(subject)
	}
	// Refill since last touch.
	elapsed := now.Sub(st.updatedAt).Seconds()
	if elapsed > 0 {
		st.tokens += elapsed * b.refillPerS
		if st.tokens > b.capacity {
			st.tokens = b.capacity
		}
		st.updatedAt = now
	}
	if st.tokens >= float64(cost) {
		st.tokens -= float64(cost)
		return RateDecision{
			Status:       RateAllow,
			Remaining:    st.tokens,
			SubjectKey:   subject,
			UsedFallback: true,
			UsedTier:     "secondary",
			CostCharged:  cost,
		}, nil
	}
	deficit := float64(cost) - st.tokens
	retryS := deficit / b.refillPerS
	return RateDecision{
		Status:       RateThrottle,
		Remaining:    st.tokens,
		RetryAfter:   time.Duration(retryS * float64(time.Second)),
		SubjectKey:   subject,
		UsedFallback: true,
		UsedTier:     "secondary",
		CostCharged:  0,
	}, nil
}

// evictIfFull is a coarse LRU: when the map exceeds maxKeys, evict
// the bucket with the oldest updatedAt. Linear scan is fine for the
// expected cap (low thousands of subjects per gateway pod).
func (b *SecondaryBucket) evictIfFull(latest string) {
	if b.maxKeys <= 0 || len(b.buckets) <= b.maxKeys {
		return
	}
	var oldestKey string
	var oldestTime time.Time
	first := true
	for k, st := range b.buckets {
		if k == latest {
			continue
		}
		if first || st.updatedAt.Before(oldestTime) {
			oldestKey = k
			oldestTime = st.updatedAt
			first = false
		}
	}
	if oldestKey != "" {
		delete(b.buckets, oldestKey)
	}
}

// Size returns the number of tracked subjects (handy for tests
// asserting LRU eviction).
func (b *SecondaryBucket) Size() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.buckets)
}

// ── HTTP throttle response (ROADMAP §7.3) ───────────────────────────
//
// BuildThrottleResponse turns a non-allow RateDecision into an
// RFC 6585-compliant HTTP response (status code, headers, body) that
// the gateway middleware can emit on the wire. Centralising it here
// keeps the wire contract testable in isolation and stops every
// caller from re-deriving the Retry-After ceiling.
//
//   * RateThrottle → 429 Too Many Requests
//   * RateDenied   → 403 Forbidden            (denylisted subject)
//   * anything else (RateAllow, RateError) → (0, nil, nil); callers
//     are expected to short-circuit before invoking this helper.
//
// Headers always include `Retry-After` (seconds, ceiling per RFC) and
// `Content-Type: application/json; charset=utf-8`. Body is a small,
// stable JSON object that downstream clients can parse without a
// schema lib.
//
// The helper does NOT touch http.ResponseWriter directly so it stays
// cheap to unit-test (no httptest.NewRecorder needed). The middleware
// owns the actual write.
func BuildThrottleResponse(d RateDecision, reason string) (status int, headers map[string]string, body []byte) {
	switch d.Status {
	case RateThrottle:
		status = 429
	case RateDenied:
		status = 403
	default:
		// allow / error — caller shouldn't have invoked us; refuse
		// to fabricate a throttle response.
		return 0, nil, nil
	}

	// Retry-After: ceiling(retry_after_ms / 1000), minimum 1s when
	// the upstream signal is positive (RFC 6585 — clients treat 0
	// as "no advice", which would be misleading).
	retryAfterMs := int64(d.RetryAfter / time.Millisecond)
	if retryAfterMs < 0 {
		retryAfterMs = 0
	}
	retryAfterS := retryAfterMs / 1000
	if retryAfterMs%1000 != 0 {
		retryAfterS++ // ceiling
	}
	if retryAfterS < 1 && retryAfterMs > 0 {
		retryAfterS = 1
	}

	headers = map[string]string{
		"Content-Type": "application/json; charset=utf-8",
		"Retry-After":  strconvFormatInt(retryAfterS),
	}

	if reason == "" {
		if d.Status == RateThrottle {
			reason = "rate_limited"
		} else {
			reason = "denylisted"
		}
	}
	// Hand-rolled JSON: zero allocations beyond the byte slice and
	// no risk of accidentally leaking a struct field. The shape is
	// pinned by TestBuildThrottleResponse_BodyShape.
	body = []byte(`{"error":"` + jsonEscape(errorCode(d.Status)) +
		`","retry_after_ms":` + strconvFormatInt(retryAfterMs) +
		`,"reason":"` + jsonEscape(reason) + `"}`)
	return status, headers, body
}

func errorCode(s RateStatus) string {
	if s == RateDenied {
		return "denylisted"
	}
	return "rate_limited"
}

// jsonEscape escapes the small subset of characters that can appear
// in operator-supplied reason strings. Keeps us off the
// encoding/json critical path for the hot middleware response.
func jsonEscape(s string) string {
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c == '"' || c == '\\' || c < 0x20 {
			return jsonEscapeSlow(s)
		}
	}
	return s
}

func jsonEscapeSlow(s string) string {
	out := make([]byte, 0, len(s)+8)
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c == '"':
			out = append(out, '\\', '"')
		case c == '\\':
			out = append(out, '\\', '\\')
		case c == '\n':
			out = append(out, '\\', 'n')
		case c == '\r':
			out = append(out, '\\', 'r')
		case c == '\t':
			out = append(out, '\\', 't')
		case c < 0x20:
			const hex = "0123456789abcdef"
			out = append(out, '\\', 'u', '0', '0', hex[c>>4], hex[c&0xf])
		default:
			out = append(out, c)
		}
	}
	return string(out)
}

// strconvFormatInt is a tiny stdlib-free int64 → decimal string
// converter. Avoids pulling strconv into this file's imports just
// for a 1-line call.
func strconvFormatInt(n int64) string {
	if n == 0 {
		return "0"
	}
	negative := n < 0
	if negative {
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if negative {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
