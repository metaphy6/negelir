package api

import (
	"context"
	"net/http"

	"github.com/gin-gonic/gin"

	aperrors "github.com/metaphy6/negelir/server/internal/errors"
	"github.com/metaphy6/negelir/server/internal/middleware"
	"github.com/metaphy6/negelir/server/internal/sec"
)

// QAQuarantineAlertFunc is called by NewQAInputHandler when the QA input gate
// issues VerdictQuarantine. The eventCorrelationID argument MUST equal the
// request_id stored in the Gin context (set by middleware.RequestID) so that
// downstream consumers can join the sec.alert.v1 event to the originating
// api.request.v1 record — per the §8.16.9 dual-emit doctrine.
//
// Production wiring (cmd/api): the concrete implementation publishes a
// sec.alert.v1 message to the bus with the event_correlation_id field set
// to eventCorrelationID. The interface is injected so tests can capture the
// value without a running bus.
type QAQuarantineAlertFunc func(ctx context.Context, kind, severity, eventCorrelationID string)

// NewQAInputHandler returns a gin.HandlerFunc that applies the sec QA input
// gate to POST /v1/qa request bodies.
//
// On VerdictQuarantine:
//  1. alertFn is called (when non-nil) with:
//     - kind  = the gate hit-rule kind (or "payload_oversize" / "prompt_injection")
//     - severity = "warn"
//     - eventCorrelationID = the request_id from the Gin context (§8.16.9)
//  2. The handler responds 422 with code qa_quarantined.
//
// On VerdictPass or VerdictSanitize the handler responds 202 Accepted.
// alertFn may be nil (alert silently skipped — useful in unit tests that
// only care about HTTP status).
func NewQAInputHandler(gate *sec.QAInputGate, alertFn QAQuarantineAlertFunc) gin.HandlerFunc {
	return func(c *gin.Context) {
		var req struct {
			Q      string `json:"q"`
			Locale string `json:"locale"`
		}
		if err := c.ShouldBindJSON(&req); err != nil || req.Q == "" {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, "q is required")
			return
		}

		decision := gate.Inspect(req.Q)
		if decision.Verdict == sec.VerdictQuarantine {
			if alertFn != nil {
				kind := "prompt_injection"
				if decision.OversizeKind != "" {
					kind = decision.OversizeKind
				} else if decision.HitRule != nil && decision.HitRule.Kind != "" {
					kind = decision.HitRule.Kind
				}
				requestID := c.GetString(middleware.ContextKeyRequestID)
				alertFn(c.Request.Context(), kind, "warn", requestID)
			}
			aperrors.Respond(c, aperrors.CodeQAQuarantined, "input rejected by security gate")
			return
		}

		// Phase 10 NLP fan-out is wired here when that phase is implemented.
		c.JSON(http.StatusAccepted, gin.H{"status": "accepted"})
	}
}
