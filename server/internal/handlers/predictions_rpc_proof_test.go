package handlers_test

// predictions_rpc_proof_test.go — §9.14 Request flow & RPC proof tests.
//
// Tests:
//   TestRPCHappyPathRoundTrip      (§9.14 test 2)
//   TestRPC503NoCache              (§9.14 test 3)
//   TestRPC503WithCacheServesCache (§9.14 test 4)

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/calibration"
	"github.com/metaphy6/negelir/server/internal/handlers"
	"github.com/metaphy6/negelir/server/internal/rpc"
)

// ---------------------------------------------------------------------------
// Stubs
// ---------------------------------------------------------------------------

// stubRPCClient implements rpc.PredictorRPCClient.
type stubRPCClient struct {
	result *rpc.PredictionResult
	err    error
}

func (s *stubRPCClient) Predict(_ context.Context, _, _, _ string) (*rpc.PredictionResult, error) {
	return s.result, s.err
}

// stubPredCache implements handlers.PredictionCacheChecker.
type stubPredCache struct {
	body    string
	isFresh bool
	isStale bool
}

func (s *stubPredCache) Check(_ context.Context, _ string) (string, bool, bool) {
	return s.body, s.isFresh, s.isStale
}
func (s *stubPredCache) TryFanout(_ context.Context, _, _ string) bool { return false }
func (s *stubPredCache) DoneFanout()                                   {}

// newRPCProofRouter builds a gin router wiring PredictionsHandler with the
// provided cache and rpcClient (either may be nil).
func newRPCProofRouter(
	store calibration.CalibrationStore,
	cache handlers.PredictionCacheChecker,
	rpcClient rpc.PredictorRPCClient,
) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	var h gin.HandlerFunc
	if rpcClient != nil {
		h = handlers.PredictionsHandler(store, cache, rpcClient)
	} else {
		h = handlers.PredictionsHandler(store, cache)
	}
	r.GET("/v1/matches/:id/predictions", h)
	return r
}

// ---------------------------------------------------------------------------
// §9.14 Test 2: TestRPCHappyPathRoundTrip
// ---------------------------------------------------------------------------

// TestRPCHappyPathRoundTrip — stub predictor publishes predict.approved.v1;
// handler returns 200 with X-Prediction-ID and X-Produced-At headers set.
func TestRPCHappyPathRoundTrip(t *testing.T) {
	stub := &stubRPCClient{
		result: &rpc.PredictionResult{
			PredictionID: "01928abc-0000-7000-8000-000000000001",
			ProducedAt:   "2026-05-26T12:00:00Z",
			Body:         `{"predictions":{"1x2":{"home":0.45,"draw":0.30,"away":0.25}}}`,
		},
	}
	store := calibration.NewInMemoryCalibrationStore()
	r := newRPCProofRouter(store, nil, stub)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/matches/m1/predictions?market=1x2", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("RPC happy path: got %d, want 200; body=%s", w.Code, w.Body.String())
	}
	if got := w.Header().Get("X-Prediction-ID"); got != "01928abc-0000-7000-8000-000000000001" {
		t.Errorf("X-Prediction-ID = %q; want 01928abc-...", got)
	}
	if got := w.Header().Get("X-Produced-At"); got != "2026-05-26T12:00:00Z" {
		t.Errorf("X-Produced-At = %q; want 2026-05-26T12:00:00Z", got)
	}
}

// ---------------------------------------------------------------------------
// §9.14 Test 3: TestRPC503NoCache
// ---------------------------------------------------------------------------

// TestRPC503NoCache — predictor unavailable (RPC returns error), no cache
// entry → 503 consensus_window_blown + Retry-After header.
func TestRPC503NoCache(t *testing.T) {
	stub := &stubRPCClient{err: errors.New("predictor: bus unreachable")}
	store := calibration.NewInMemoryCalibrationStore()
	r := newRPCProofRouter(store, nil, stub)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/matches/m1/predictions?market=1x2", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("RPC 503 no-cache: got %d, want 503; body=%s", w.Code, w.Body.String())
	}
	if w.Header().Get("Retry-After") == "" {
		t.Error("Retry-After header missing on 503 predictor-down response")
	}
}

// ---------------------------------------------------------------------------
// §9.14 Test 4: TestRPC503WithCacheServesCache
// ---------------------------------------------------------------------------

// TestRPC503WithCacheServesCache — fresh cache.v1 entry present; predictor is
// down but the cache-first path returns 200 + X-Cache: hit before RPC is called.
func TestRPC503WithCacheServesCache(t *testing.T) {
	const cachedBody = `{"predictions":{"1x2":{"home":0.50}}}`
	cache := &stubPredCache{
		body:    cachedBody,
		isFresh: true,
		isStale: false,
	}
	// Stub RPC would fail, but the cache-first path must prevent it from being called.
	stub := &stubRPCClient{err: errors.New("predictor: dead")}
	store := calibration.NewInMemoryCalibrationStore()
	r := newRPCProofRouter(store, cache, stub)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/matches/m1/predictions?market=1x2", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("cache-serves-when-rpc-dead: got %d, want 200; body=%s", w.Code, w.Body.String())
	}
	if got := w.Header().Get("X-Cache"); got != "hit" {
		t.Errorf("X-Cache = %q; want \"hit\"", got)
	}
	if w.Body.String() != cachedBody {
		t.Errorf("body = %q; want %q", w.Body.String(), cachedBody)
	}
}
