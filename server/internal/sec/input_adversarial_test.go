package sec

// input_adversarial_test.go — Phase 9 §9.14 adversarial QA injection proof test.
//
//   adv_test_qa_prompt_injection_corpus_300 (TestAdvQAPromptInjectionCorpus300)
//
// Replays the Phase 12 synthetic corpus of 300 injection payloads through the
// in-process QAInputGate. Every entry MUST produce VerdictQuarantine — none
// may slip through to predict.request.
//
// Corpus lives at: server/internal/sec/testdata/injection_corpus_300.yaml
// Patterns live at: server/internal/sec/embedded/injection_patterns.yaml (embedded)

import (
	"os"
	"testing"

	"gopkg.in/yaml.v3"
)

// corpusEntry mirrors one entry in injection_corpus_300.yaml.
type corpusEntry struct {
	ID   string `yaml:"id"`
	Text string `yaml:"text"`
}

// injectionCorpus is the top-level shape of the corpus YAML file.
type injectionCorpus struct {
	Version int           `yaml:"version"`
	Entries []corpusEntry `yaml:"entries"`
}

// TestAdvQAPromptInjectionCorpus300 — adv_test_qa_prompt_injection_corpus_300.
//
// Phase 12 corpus replayed at the in-process sec gate; asserts each entry
// catches at VerdictQuarantine and never leaks through to predict.request.
// NEVER xfail — a non-quarantine verdict is a build-blocking failure.
func TestAdvQAPromptInjectionCorpus300(t *testing.T) {
	raw, err := os.ReadFile("testdata/injection_corpus_300.yaml")
	if err != nil {
		t.Fatalf("adv: open corpus: %v", err)
	}

	var corpus injectionCorpus
	if err := yaml.Unmarshal(raw, &corpus); err != nil {
		t.Fatalf("adv: parse corpus YAML: %v", err)
	}
	if len(corpus.Entries) < 300 {
		t.Fatalf("adv: corpus must have ≥300 entries; got %d", len(corpus.Entries))
	}

	rs, err := LoadInjectionPatterns(EmbeddedInjectionPatternsYAML)
	if err != nil {
		t.Fatalf("adv: load embedded injection patterns: %v", err)
	}

	// No length cap — we are testing injection matching, not oversize defence.
	gate := NewQAInputGate(rs, 0)

	var leaked int
	for _, entry := range corpus.Entries {
		dec := gate.Inspect(entry.Text)
		if dec.Verdict != VerdictQuarantine {
			leaked++
			t.Errorf("adv: corpus entry %s leaked to predict.request: text=%q verdict=%s",
				entry.ID, entry.Text, dec.Verdict)
		}
	}

	if leaked > 0 {
		t.Errorf("adv: %d/%d corpus entries not quarantined — each leaks through sec gate to predict.request",
			leaked, len(corpus.Entries))
	}
}
