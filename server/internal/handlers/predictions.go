package handlers

import (
	"context"
	"fmt"
	"net/http"
	"sort"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/metaphy6/negelir/server/internal/calibration"
	aperrors "github.com/metaphy6/negelir/server/internal/errors"
	"github.com/metaphy6/negelir/server/internal/rpc"
)

// PredictionCacheChecker is the cache-read / SWR interface injected into
// PredictionsHandler at construction time.
//
// The concrete implementation (middleware.PredictionSWR) lives in
// internal/middleware; cmd/api wires it. Pass nil to disable cache reads (dev /
// test default — all requests fall through to the RPC stub).
//
// Interface contract mirrors §9.3 cache-first spec:
//   - Check: classify a cache entry as fresh HIT, stale HIT, or miss.
//   - TryFanout: attempt to acquire the SWR SETNX lock; returns true when the
//     caller should fire an async predict.request publish.
//   - DoneFanout: release the inflight counter; MUST be called after async work.
type PredictionCacheChecker interface {
	Check(ctx context.Context, key string) (body string, isFresh, isStale bool)
	TryFanout(ctx context.Context, matchID, marketSet string) bool
	DoneFanout()
}

// PredictionsHandler returns a gin.HandlerFunc for
// GET /v1/matches/{match_id}/predictions?market=<csv>.
//
// The handler reads calibration data exclusively through the
// CalibrationStore interface; swapping the backend (Phase 16 Emitter
// feed-plane) changes 0 lines here.
//
// Constructor injection: callers supply a CalibrationStore, an optional
// PredictionCacheChecker, and an optional PredictorRPCClient (variadic,
// zero or one element). The concrete choices live in cmd/api/main.go.
func PredictionsHandler(store calibration.CalibrationStore, cache PredictionCacheChecker, rpcClients ...rpc.PredictorRPCClient) gin.HandlerFunc {
	var rpcClient rpc.PredictorRPCClient
	if len(rpcClients) > 0 {
		rpcClient = rpcClients[0]
	}
	return func(c *gin.Context) {
		ctx := c.Request.Context()

		matchID := strings.TrimSpace(c.Param("id"))
		if matchID == "" {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, "match_id required")
			return
		}

		// market= is a comma-separated list; default to a well-known set
		// until cfg.api_allowed_markets is wired (Phase 9 config knob).
		marketParam := strings.TrimSpace(c.Query("market"))
		var markets []string
		for _, m := range strings.Split(marketParam, ",") {
			if m = strings.TrimSpace(m); m != "" {
				markets = append(markets, m)
			}
		}
		if len(markets) == 0 {
			// Default to the canonical match-result market.
			markets = []string{"1x2"}
		}

		// Sort markets for a deterministic, order-invariant cache key.
		sort.Strings(markets)
		marketSet := strings.Join(markets, ",")

		// Read calibration version through the Protocol seam.
		// Phase 16 swaps the backend; this call is unchanged.
		//
		// profileID defaults to matchID until Phase 13a ResolveProfileID
		// is wired in cmd/api (the handler never resolves it directly).
		profileID := matchID
		calibVersion := 0
		for _, market := range markets {
			tbl, err := store.Latest(profileID, market)
			if err != nil {
				aperrors.Respond(c, aperrors.CodeInternal, "calibration store error")
				return
			}
			if tbl.Version > calibVersion {
				calibVersion = tbl.Version
			}
		}

		// X-Calibration-Version header (§9.1 header inventory).
		c.Header("X-Calibration-Version", fmt.Sprintf("%d", calibVersion))

		// §9.3 Cache-first: check SWR prediction cache before issuing the RPC.
		// Cache key: cache.v1:prediction:<match_id>:<market_set>:<calibration_version>
		if cache != nil {
			cacheKey := fmt.Sprintf("cache.v1:prediction:%s:%s:%d", matchID, marketSet, calibVersion)
			body, isFresh, isStale := cache.Check(ctx, cacheKey)

			if isFresh {
				c.Header("X-Cache", "hit")
				c.String(http.StatusOK, "%s", body)
				return
			}

			if isStale {
				c.Header("X-Cache", "stale")
				c.String(http.StatusOK, "%s", body)
				// Async SWR: trigger predict.request if fan-out budget permits.
				// Phase 9.3 RPC publish will be wired here; no-op until then.
				if cache.TryFanout(ctx, matchID, marketSet) {
					go func() {
						defer cache.DoneFanout()
						// No-op stub: Phase 9.3 wires the actual publish.
					}()
				}
				return
			}
		}

		// §9.3 RPC path: attempt predict.request.v1 when a client is injected.
		if rpcClient != nil {
			requestID := c.GetString("request_id") // set by middleware.RequestID
			result, err := rpcClient.Predict(ctx, matchID, marketSet, requestID)
			if err != nil {
				c.Header("X-Degraded", "true")
				aperrors.RespondWithRetryAfter(c, aperrors.CodeConsensusWindowBlown,
					"predictor unavailable",
					aperrors.RetryAfterConsensusWindowBlown)
				return
			}
			if result.PredictionID != "" {
				c.Header("X-Prediction-ID", result.PredictionID)
			}
			if result.ProducedAt != "" {
				c.Header("X-Produced-At", result.ProducedAt)
			}
			c.String(http.StatusOK, "%s", result.Body)
			return
		}

		c.Header("X-Degraded", "true")

		// No RPC client wired: degrade with 503 + Retry-After.
		// §9.3 503 + Retry-After contract: consensus window blown while all
		// predictors are DLQ'd → 503 consensus_window_blown + Retry-After: 10.
		aperrors.RespondWithRetryAfter(c, aperrors.CodeConsensusWindowBlown,
			"RPC path not yet wired (Phase 9.3)",
			aperrors.RetryAfterConsensusWindowBlown)
	}
}

