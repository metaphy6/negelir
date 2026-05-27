package middleware

// idempotency_test.go — Proof tests for Phase 9 §9.3 Idempotency-Key cache.
//
//   (a) double-POST returns identical bytes (203 X-Replayed: true)
//   (b) same Idempotency-Key + different body -> 409 + alert fired
//   (c) inflight request -> second caller -> 425 too_early
//   (d) PurgeStaleIdemWaiters removes orphaned inflight keys

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// -- stub IdempotencyStore -------------------------------------------------

type stubIdemEntry struct {
	value string
	ttl   time.Duration
	setAt time.Time
}

type stubIdemStore struct {
	mu       sync.Mutex
	data     map[string]stubIdemEntry
	subs     map[string][]chan string
	scanKeys []string // pre-seeded keys for ScanKeys stub
}

func newStubIdemStore() *stubIdemStore {
	return &stubIdemStore{
		data: make(map[string]stubIdemEntry),
		subs: make(map[string][]chan string),
	}
}

func (s *stubIdemStore) Get(_ context.Context, key string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e, ok := s.data[key]
	if !ok {
		return "", errCacheMiss // reuse sentinel from cache_gen_test
	}
	return e.value, nil
}

func (s *stubIdemStore) Set(_ context.Context, key, value string, ttl time.Duration) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data[key] = stubIdemEntry{value: value, ttl: ttl, setAt: time.Now()}
	return nil
}

func (s *stubIdemStore) SetNX(_ context.Context, key, value string, ttl time.Duration) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.data[key]; ok {
		return false, nil
	}
	s.data[key] = stubIdemEntry{value: value, ttl: ttl, setAt: time.Now()}
	return true, nil
}

func (s *stubIdemStore) Del(_ context.Context, key string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.data, key)
	return nil
}

func (s *stubIdemStore) Subscribe(_ context.Context, channel string) (<-chan string, func(), error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	ch := make(chan string, 1)
	s.subs[channel] = append(s.subs[channel], ch)
	cleanup := func() {
		s.mu.Lock()
		defer s.mu.Unlock()
		list := s.subs[channel]
		for i, c := range list {
			if c == ch {
				s.subs[channel] = append(list[:i], list[i+1:]...)
				close(ch)
				break
			}
		}
	}
	return ch, cleanup, nil
}

func (s *stubIdemStore) Publish(_ context.Context, channel, msg string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, ch := range s.subs[channel] {
		select {
		case ch <- msg:
		default:
		}
	}
	return nil
}

func (s *stubIdemStore) ScanKeys(_ context.Context, _ string) ([]string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.scanKeys, nil
}

// -- helpers ---------------------------------------------------------------

func newIdemRouter(store IdempotencyStore, alertFn IdempotencyAlertFunc) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Idempotency(store, 24*time.Hour, 100*time.Millisecond, alertFn))
	r.POST("/v1/qa", func(c *gin.Context) {
		body, _ := c.GetRawData()
		c.JSON(http.StatusOK, gin.H{"echoed": string(body)})
	})
	return r
}

// -- (a) double-POST returns identical bytes with 203 X-Replayed: true ----

func TestIdempotency_Replay(t *testing.T) {
	store := newStubIdemStore()
	r := newIdemRouter(store, nil)

	// First POST — should succeed normally (200).
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(`{"q":"test"}`))
	req1.Header.Set("Content-Type", "application/json")
	req1.Header.Set("Idempotency-Key", "key-abc")
	r.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("first POST: got %d, want 200", w1.Code)
	}
	firstBody := w1.Body.String()

	// Second POST with same key and same body — should replay as 203.
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(`{"q":"test"}`))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Idempotency-Key", "key-abc")
	r.ServeHTTP(w2, req2)

	if w2.Code != http.StatusNonAuthoritativeInfo {
		t.Fatalf("replay: got %d, want 203", w2.Code)
	}
	if w2.Header().Get("X-Replayed") != "true" {
		t.Fatal("replay: X-Replayed header missing or not true")
	}
	if w2.Body.String() != firstBody {
		t.Fatalf("replay: body mismatch\ngot:  %q\nwant: %q", w2.Body.String(), firstBody)
	}
}

// -- (b) same Idempotency-Key + different body -> 409 + alert fired -------

func TestIdempotency_Drift(t *testing.T) {
	store := newStubIdemStore()
	var alertKind, alertSeverity string
	alertFn := IdempotencyAlertFunc(func(_ context.Context, kind, severity string) {
		alertKind = kind
		alertSeverity = severity
	})
	r := newIdemRouter(store, alertFn)

	// First POST — stored normally.
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(`{"q":"original"}`))
	req1.Header.Set("Content-Type", "application/json")
	req1.Header.Set("Idempotency-Key", "key-drift")
	r.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("first POST: got %d, want 200", w1.Code)
	}

	// Second POST with same key but DIFFERENT body -> 409.
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(`{"q":"changed"}`))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Idempotency-Key", "key-drift")
	r.ServeHTTP(w2, req2)

	if w2.Code != http.StatusConflict {
		t.Fatalf("drift: got %d, want 409", w2.Code)
	}
	var resp map[string]string
	if err := json.NewDecoder(w2.Body).Decode(&resp); err != nil {
		t.Fatalf("drift: decode response: %v", err)
	}
	if resp["error"] != "idempotency_key_replay_with_different_body" {
		t.Fatalf("drift: unexpected error code %q", resp["error"])
	}
	if alertKind != "idempotency_drift" || alertSeverity != "warn" {
		t.Fatalf("drift: alert not fired correctly: kind=%q severity=%q", alertKind, alertSeverity)
	}
}

// -- (c) inflight request -> second caller -> 425 too_early ---------------

func TestIdempotency_Inflight(t *testing.T) {
	store := newStubIdemStore()

	// Pre-seed the inflight key to simulate a request in-progress.
	inflightKey := idemInflightKey(
		idemRedisKey("", http.MethodPost, "/v1/qa", "key-inflight"),
	)
	store.data[inflightKey] = stubIdemEntry{value: "1", ttl: 5 * time.Second, setAt: time.Now()}

	r := newIdemRouter(store, nil)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(`{"q":"test"}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", "key-inflight")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooEarly {
		t.Fatalf("inflight: got %d, want 425", w.Code)
	}
	var resp map[string]string
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("inflight: decode response: %v", err)
	}
	if resp["error"] != "too_early" {
		t.Fatalf("inflight: unexpected error code %q", resp["error"])
	}
}

// -- (d) PurgeStaleIdemWaiters removes orphaned inflight keys at boot ------

func TestIdempotency_PurgeStaleWaiters(t *testing.T) {
	store := newStubIdemStore()

	// Pre-seed two orphaned inflight keys (simulating prior pod crash).
	store.data["idem:aaaa:inflight"] = stubIdemEntry{value: "1"}
	store.data["idem:bbbb:inflight"] = stubIdemEntry{value: "1"}
	store.data["idem:cccc"] = stubIdemEntry{value: "completed"} // NOT inflight; must survive
	store.scanKeys = []string{"idem:aaaa:inflight", "idem:bbbb:inflight"}

	if err := PurgeStaleIdemWaiters(context.Background(), store); err != nil {
		t.Fatalf("purge: unexpected error: %v", err)
	}

	store.mu.Lock()
	defer store.mu.Unlock()
	if _, ok := store.data["idem:aaaa:inflight"]; ok {
		t.Error("purge: idem:aaaa:inflight was not deleted")
	}
	if _, ok := store.data["idem:bbbb:inflight"]; ok {
		t.Error("purge: idem:bbbb:inflight was not deleted")
	}
	if _, ok := store.data["idem:cccc"]; !ok {
		t.Error("purge: idem:cccc (non-inflight key) was incorrectly deleted")
	}
}

// ---------------------------------------------------------------------------
// §9.14 Idempotency & cache proof tests (tests 10–13)
// ---------------------------------------------------------------------------

// TestIdempotencyReplayIdenticalBodySameResponse — §9.14 test 10: bytes-identical
// POST replay returns 203 X-Replayed: true with the exact same response body.
func TestIdempotencyReplayIdenticalBodySameResponse(t *testing.T) {
	store := newStubIdemStore()
	r := newIdemRouter(store, nil)

	const body = `{"q":"replay-proof-test"}`

	// First POST — stored normally.
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(body))
	req1.Header.Set("Content-Type", "application/json")
	req1.Header.Set("Idempotency-Key", "key-replay-proof")
	r.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("first POST: %d; body=%s", w1.Code, w1.Body.String())
	}
	firstBody := w1.Body.String()

	// Second POST with bytes-identical body → 203 X-Replayed: true, same body.
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(body))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Idempotency-Key", "key-replay-proof")
	r.ServeHTTP(w2, req2)

	if w2.Code != http.StatusNonAuthoritativeInfo {
		t.Fatalf("replay: got %d, want 203", w2.Code)
	}
	if w2.Header().Get("X-Replayed") != "true" {
		t.Error("X-Replayed header missing or not true")
	}
	if w2.Body.String() != firstBody {
		t.Errorf("replay body mismatch:\ngot:  %q\nwant: %q", w2.Body.String(), firstBody)
	}
}

// TestIdempotencyDrift409AndAlert — §9.14 test 11: same Idempotency-Key with
// different body → 409 Conflict + sec.alert (kind=idempotency_drift).
func TestIdempotencyDrift409AndAlert(t *testing.T) {
	store := newStubIdemStore()
	var alertKind, alertSeverity string
	alertFn := IdempotencyAlertFunc(func(_ context.Context, kind, severity string) {
		alertKind = kind
		alertSeverity = severity
	})
	r := newIdemRouter(store, alertFn)

	// First POST stores the response.
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(`{"q":"original"}`))
	req1.Header.Set("Content-Type", "application/json")
	req1.Header.Set("Idempotency-Key", "key-drift-proof")
	r.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("first POST: %d", w1.Code)
	}

	// Second POST same key, different body → 409.
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(`{"q":"different"}`))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Idempotency-Key", "key-drift-proof")
	r.ServeHTTP(w2, req2)

	if w2.Code != http.StatusConflict {
		t.Fatalf("drift: got %d, want 409", w2.Code)
	}
	if alertKind != "idempotency_drift" {
		t.Errorf("alert kind = %q; want %q", alertKind, "idempotency_drift")
	}
	if alertSeverity != "warn" {
		t.Errorf("alert severity = %q; want %q", alertSeverity, "warn")
	}
	var resp map[string]string
	if err := json.NewDecoder(w2.Body).Decode(&resp); err != nil {
		t.Fatalf("decode drift response: %v", err)
	}
	if resp["error"] != "idempotency_key_replay_with_different_body" {
		t.Errorf("error code = %q; want idempotency_key_replay_with_different_body", resp["error"])
	}
}

// TestIdempotencyInflightBlocksThenReturns — §9.14 test 12: second request with
// the same Idempotency-Key blocks on pubsub while the first request is in-flight;
// when the first request completes, the second receives the stored response as
// 203 X-Replayed: true.
func TestIdempotencyInflightBlocksThenReturns(t *testing.T) {
	store := newStubIdemStore()
	r := newIdemRouter(store, nil)

	const idemHeader = "key-inflight-wait"
	const reqBody = `{"q":"test-wait"}`
	const respBody = `{"echoed":"test-wait"}`

	// Derive the middleware's Redis key names.
	mainKey := idemRedisKey("", http.MethodPost, "/v1/qa", idemHeader)
	inflightKey := idemInflightKey(mainKey)
	waitChan := idemWaitChan(mainKey)

	// Pre-seed only the inflight sentinel (no stored response yet).
	store.mu.Lock()
	store.data[inflightKey] = stubIdemEntry{value: "1", ttl: 5 * time.Second, setAt: time.Now()}
	store.mu.Unlock()

	// Send request in background; it will block on Subscribe.
	type result struct {
		code int
		body string
	}
	resultCh := make(chan result, 1)
	go func() {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(reqBody))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Idempotency-Key", idemHeader)
		r.ServeHTTP(w, req)
		resultCh <- result{w.Code, w.Body.String()}
	}()

	// Give the goroutine time to reach Subscribe.
	time.Sleep(30 * time.Millisecond)

	// Simulate first request completing: build the idemEntry, store it, publish.
	rawHash := sha256.Sum256([]byte(reqBody))
	entry := idemEntry{
		Status:      http.StatusOK,
		ContentType: "application/json",
		BodyB64:     base64.StdEncoding.EncodeToString([]byte(respBody)),
		ReqBodySHA:  hex.EncodeToString(rawHash[:]),
		RequestID:   "req-001",
		ExpiresAt:   time.Now().Add(24 * time.Hour).Unix(),
	}
	data, _ := json.Marshal(entry)
	store.Set(context.Background(), mainKey, string(data), 24*time.Hour)
	store.Publish(context.Background(), waitChan, "1")

	// Assert the waiting request was unblocked and returned the stored response.
	select {
	case res := <-resultCh:
		if res.code != http.StatusNonAuthoritativeInfo {
			t.Errorf("inflight-unblock: got %d, want 203 (X-Replayed); body=%s", res.code, res.body)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("request did not complete within timeout after pubsub publish")
	}
}

// TestIdempotencyInflightTimeout425 — §9.14 test 13: first request stalls (no
// pubsub publish); second request hits api_idempotency_inflight_wait_ms → 425.
func TestIdempotencyInflightTimeout425(t *testing.T) {
	store := newStubIdemStore()
	r := newIdemRouter(store, nil) // inflightWait = 100 ms (see newIdemRouter)

	const idemHeader = "key-inflight-timeout"
	mainKey := idemRedisKey("", http.MethodPost, "/v1/qa", idemHeader)
	inflightKey := idemInflightKey(mainKey)

	// Pre-seed inflight sentinel; nothing will ever publish to the wait channel.
	store.mu.Lock()
	store.data[inflightKey] = stubIdemEntry{value: "1", ttl: 5 * time.Second, setAt: time.Now()}
	store.mu.Unlock()

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(`{"q":"test"}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", idemHeader)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooEarly {
		t.Fatalf("inflight-timeout: got %d, want 425; body=%s", w.Code, w.Body.String())
	}
	var resp map[string]string
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if resp["error"] != "too_early" {
		t.Errorf("error = %q; want %q", resp["error"], "too_early")
	}
}

// ---------------------------------------------------------------------------
// §9.14 adversarial proof test
// ---------------------------------------------------------------------------

// newIdemRouterWithSubject returns a test router that pre-sets ContextKeySubjectID
// to subjectID before the Idempotency middleware runs.  This exercises the
// per-user namespace: idemRedisKey hashes subjectID into the cache key, so two
// users with identical Idempotency-Key headers produce different Redis keys.
func newIdemRouterWithSubject(store IdempotencyStore, subjectID string) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set(ContextKeySubjectID, subjectID)
		c.Next()
	})
	r.Use(Idempotency(store, 24*time.Hour, 100*time.Millisecond, nil))
	r.POST("/v1/qa", func(c *gin.Context) {
		body, _ := c.GetRawData()
		c.JSON(http.StatusOK, gin.H{"echoed": string(body)})
	})
	return r
}

// TestAdvIdempotencyKeyCollisionUserIsolation — adv_test_idempotency_key_collision_user_isolation.
//
// User A and user B submit POST /v1/qa with the SAME Idempotency-Key header
// but DIFFERENT request bodies. The idempotency cache namespaces by subjectID
// (see idemRedisKey), so:
//
//   - user B's first request must succeed (200), not 409-conflict with user A.
//   - user A's replay returns their own response (203 X-Replayed: true).
//   - user B's replay returns their own response (203 X-Replayed: true).
//   - neither user sees the other's body (no cross-user leak).
func TestAdvIdempotencyKeyCollisionUserIsolation(t *testing.T) {
	store := newStubIdemStore()
	routerA := newIdemRouterWithSubject(store, "user-a")
	routerB := newIdemRouterWithSubject(store, "user-b")

	const sharedKey = "shared-idem-key"
	const bodyA = `{"q":"body-a"}`
	const bodyB = `{"q":"body-b"}`

	// -- User A: first request stores their response -------------------------
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(bodyA))
	req1.Header.Set("Content-Type", "application/json")
	req1.Header.Set("Idempotency-Key", sharedKey)
	routerA.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("user-a first POST: got %d, want 200; body=%s", w1.Code, w1.Body.String())
	}
	respA := w1.Body.String()

	// -- User B: first request with same key but different body ---------------
	// Must NOT return 409 (keys are namespaced by user; no collision).
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(bodyB))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Idempotency-Key", sharedKey)
	routerB.ServeHTTP(w2, req2)
	if w2.Code == http.StatusConflict {
		t.Fatal("adv: cross-user idempotency collision: user-B got 409 from user-A's key (subjectID namespace broken)")
	}
	if w2.Code != http.StatusOK {
		t.Fatalf("user-b first POST: got %d, want 200; body=%s", w2.Code, w2.Body.String())
	}
	respB := w2.Body.String()

	// Responses must differ (they echo different bodies).
	if respA == respB {
		t.Fatalf("adv: cross-user leak — user-A and user-B got identical responses for different bodies\nrespA=%q\nrespB=%q", respA, respB)
	}

	// -- User A: replay → must return their own response (203) ----------------
	w3 := httptest.NewRecorder()
	req3, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(bodyA))
	req3.Header.Set("Content-Type", "application/json")
	req3.Header.Set("Idempotency-Key", sharedKey)
	routerA.ServeHTTP(w3, req3)
	if w3.Code != http.StatusNonAuthoritativeInfo {
		t.Fatalf("user-a replay: got %d, want 203 (X-Replayed); body=%s", w3.Code, w3.Body.String())
	}
	if w3.Header().Get("X-Replayed") != "true" {
		t.Error("user-a replay: X-Replayed header missing or not true")
	}
	if w3.Body.String() != respA {
		t.Errorf("adv: user-a replay returned wrong body\ngot:  %q\nwant: %q", w3.Body.String(), respA)
	}

	// -- User B: replay → must return their own response (203) ----------------
	w4 := httptest.NewRecorder()
	req4, _ := http.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(bodyB))
	req4.Header.Set("Content-Type", "application/json")
	req4.Header.Set("Idempotency-Key", sharedKey)
	routerB.ServeHTTP(w4, req4)
	if w4.Code != http.StatusNonAuthoritativeInfo {
		t.Fatalf("user-b replay: got %d, want 203 (X-Replayed); body=%s", w4.Code, w4.Body.String())
	}
	if w4.Header().Get("X-Replayed") != "true" {
		t.Error("user-b replay: X-Replayed header missing or not true")
	}
	if w4.Body.String() != respB {
		t.Errorf("adv: user-b replay returned wrong body\ngot:  %q\nwant: %q", w4.Body.String(), respB)
	}
}

// TestAdvIdempotencyInflightDoubleSubmitNoDoubleCharge —
// adv_test_idempotency_inflight_double_submit_no_double_charge.
//
// Two goroutines POST simultaneously with the SAME Idempotency-Key.
// The idempotency middleware must guarantee:
//
//  1. The downstream handler (proxy for predict.request publication) is invoked
//     exactly ONCE — no double-charge, no duplicate publish.
//  2. Both clients receive the same response body.
//  3. No client receives an error response (425/500); each gets 200 or 203.
func TestAdvIdempotencyInflightDoubleSubmitNoDoubleCharge(t *testing.T) {
	store := newStubIdemStore()

	// handlerCalls is the proxy for "predict.request published".
	// Exactly one call is required.
	var (
		handlerMu    sync.Mutex
		handlerCalls int
	)

	gin.SetMode(gin.TestMode)
	r := gin.New()
	// inflightWait = 500 ms — generous enough for the concurrent goroutine to
	// complete its response before the waiter times out.
	r.Use(Idempotency(store, 24*time.Hour, 500*time.Millisecond, nil))
	r.POST("/v1/qa", func(c *gin.Context) {
		handlerMu.Lock()
		handlerCalls++
		handlerMu.Unlock()
		c.JSON(http.StatusOK, gin.H{"result": "prediction"})
	})

	const idemKey = "double-submit-key"
	const reqBody = `{"q":"match-123"}`

	type result struct {
		code int
		body string
	}
	results := make(chan result, 2)

	// Launch two goroutines simultaneously with the same Idempotency-Key.
	// One will acquire the inflight lock; the other will either block on
	// Subscribe (if it loses the SetNX race) or find the stored response
	// via Get (if the winner completed before it arrived).
	for i := 0; i < 2; i++ {
		go func() {
			w := httptest.NewRecorder()
			req, _ := http.NewRequest(http.MethodPost, "/v1/qa",
				strings.NewReader(reqBody))
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", idemKey)
			r.ServeHTTP(w, req)
			results <- result{w.Code, w.Body.String()}
		}()
	}

	r1 := <-results
	r2 := <-results

	// Invariant 1: exactly one predict.request published (handler called once).
	handlerMu.Lock()
	calls := handlerCalls
	handlerMu.Unlock()
	if calls != 1 {
		t.Errorf("adv: expected exactly 1 handler invocation (predict.request); got %d — double-charge detected",
			calls)
	}

	// Invariant 2: both clients receive the same response body.
	if r1.body != r2.body {
		t.Errorf("adv: response body mismatch between the two concurrent clients:\nclient1 (%d): %s\nclient2 (%d): %s",
			r1.code, r1.body, r2.code, r2.body)
	}

	// Invariant 3: both clients get a success code (200 or 203, not 425/500).
	for i, code := range []int{r1.code, r2.code} {
		if code != http.StatusOK && code != http.StatusNonAuthoritativeInfo {
			t.Errorf("adv: client %d got unexpected status %d (want 200 or 203)", i+1, code)
		}
	}

	// Invariant 3b: if both got 200, the handler ran twice — that is a
	// double-charge even if invariant 1 somehow passed (belt-and-suspenders).
	if r1.code == http.StatusOK && r2.code == http.StatusOK {
		t.Error("adv: both clients got 200; expected at most one 200 (the other must be 203 replay) — double predict.request charge")
	}
}
