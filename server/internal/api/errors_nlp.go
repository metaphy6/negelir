package api

import aperrors "github.com/metaphy6/negelir/server/internal/errors"

const nlpProblemTypeBase = "https://negelir.io/problems"

// NLP terminal states that degrade to HTTP 200 and must not be surfaced as
// RFC 7807 errors.
const (
	NLPTerminalStateMetaUnsupported   = "meta.unsupported"
	NLPTerminalStateProofreaderBlocked = "proofreader_blocked"
)

type nlpProblemSpec struct {
	status     int
	typeSuffix string
	titleTR    string
}

var nlpProblemByTerminalState = map[string]nlpProblemSpec{
	"nlp_predict_timeout": {
		status:     504,
		typeSuffix: "/errors/nlp/predict-timeout",
		titleTR:    "Tahmin zaman aşımına uğradı",
	},
	"nlp_bus_down": {
		status:     503,
		typeSuffix: "/errors/nlp/bus-down",
		titleTR:    "Sistem geçici olarak kullanılamıyor",
	},
	"intent_classifier_unavailable": {
		status:     503,
		typeSuffix: "/errors/nlp/classifier-unavailable",
		titleTR:    "Servis hazır değil",
	},
	"nlp_cold_start_timeout": {
		status:     503,
		typeSuffix: "/errors/nlp/cold-start-timeout",
		titleTR:    "Servis henüz hazır değil",
	},
	"nlp_citation_signature_verify_failed": {
		status:     502,
		typeSuffix: "/errors/nlp/upstream-integrity",
		titleTR:    "Üst sistem doğrulama hatası",
	},
}

// NLPProblemForTerminalState maps NLP terminal states to the canonical
// RFC 7807 payload contract for gateway responses.
//
// The second return value is false when the state must degrade as HTTP 200
// (including unknown states), which means no problem+json should be emitted.
func NLPProblemForTerminalState(terminalState, detail, requestID string) (aperrors.Problem, bool) {
	if terminalState == NLPTerminalStateMetaUnsupported || terminalState == NLPTerminalStateProofreaderBlocked {
		return aperrors.Problem{}, false
	}

	spec, ok := nlpProblemByTerminalState[terminalState]
	if !ok {
		return aperrors.Problem{}, false
	}

	return aperrors.Problem{
		Type:     nlpProblemTypeBase + spec.typeSuffix,
		Title:    spec.titleTR,
		Status:   spec.status,
		Detail:   detail,
		Instance: requestID,
	}, true
}