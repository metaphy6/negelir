package api_test

import (
	"testing"

	"github.com/metaphy6/negelir/server/internal/api"
)

func TestNLPProblemForTerminalState_MappedStates(t *testing.T) {
	const detail = "detay"
	const requestID = "rid-123"

	tests := []struct {
		state          string
		wantStatus     int
		wantTypeSuffix string
		wantTitleTR    string
	}{
		{
			state:          "nlp_predict_timeout",
			wantStatus:     504,
			wantTypeSuffix: "/errors/nlp/predict-timeout",
			wantTitleTR:    "Tahmin zaman aşımına uğradı",
		},
		{
			state:          "nlp_bus_down",
			wantStatus:     503,
			wantTypeSuffix: "/errors/nlp/bus-down",
			wantTitleTR:    "Sistem geçici olarak kullanılamıyor",
		},
		{
			state:          "intent_classifier_unavailable",
			wantStatus:     503,
			wantTypeSuffix: "/errors/nlp/classifier-unavailable",
			wantTitleTR:    "Servis hazır değil",
		},
		{
			state:          "nlp_cold_start_timeout",
			wantStatus:     503,
			wantTypeSuffix: "/errors/nlp/cold-start-timeout",
			wantTitleTR:    "Servis henüz hazır değil",
		},
		{
			state:          "nlp_citation_signature_verify_failed",
			wantStatus:     502,
			wantTypeSuffix: "/errors/nlp/upstream-integrity",
			wantTitleTR:    "Üst sistem doğrulama hatası",
		},
	}

	for _, tc := range tests {
		t.Run(tc.state, func(t *testing.T) {
			problem, ok := api.NLPProblemForTerminalState(tc.state, detail, requestID)
			if !ok {
				t.Fatalf("NLPProblemForTerminalState(%q) returned ok=false", tc.state)
			}
			if problem.Status != tc.wantStatus {
				t.Fatalf("status=%d want=%d", problem.Status, tc.wantStatus)
			}
			if problem.Type != "https://negelir.io/problems"+tc.wantTypeSuffix {
				t.Fatalf("type=%q want suffix=%q", problem.Type, tc.wantTypeSuffix)
			}
			if problem.Title != tc.wantTitleTR {
				t.Fatalf("title=%q want=%q", problem.Title, tc.wantTitleTR)
			}
			if problem.Detail != detail {
				t.Fatalf("detail=%q want=%q", problem.Detail, detail)
			}
			if problem.Instance != requestID {
				t.Fatalf("instance=%q want=%q", problem.Instance, requestID)
			}
		})
	}
}

func TestNLPProblemForTerminalState_DegradesToHTTP200ForNonErrorStates(t *testing.T) {
	tests := []string{
		api.NLPTerminalStateMetaUnsupported,
		api.NLPTerminalStateProofreaderBlocked,
		"some_other_nlp_terminal_state",
	}

	for _, state := range tests {
		t.Run(state, func(t *testing.T) {
			problem, ok := api.NLPProblemForTerminalState(state, "detay", "rid")
			if ok {
				t.Fatalf("NLPProblemForTerminalState(%q) returned ok=true, problem=%+v", state, problem)
			}
		})
	}
}