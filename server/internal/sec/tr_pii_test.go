package sec

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestRedactTrPiiRedactsPhoneAndTcKimlik(t *testing.T) {
	redacted := RedactTrPii("Lütfen 0555-123-4567 arayın ve TC 10000000078 paylaşmayın")
	if redacted == "" {
		t.Fatal("redaction returned empty string")
	}
	if strings.Contains(redacted, "0555-123-4567") {
		t.Fatal("raw phone number must not survive redaction")
	}
	if !strings.Contains(redacted, "[REDACTED:PHONE_TR:") {
		t.Fatal("phone redaction sentinel missing")
	}
	if !strings.Contains(redacted, "[REDACTED:TC_KIMLIK:") {
		t.Fatal("tc kimlik redaction sentinel missing")
	}
}

func TestDetectTrPiiSpansExpectedCases(t *testing.T) {
	cases := []struct {
		text string
		want []TrPiiSpan
	}{
		{
			text: "Lütfen 0555-123-4567 arayın",
			want: []TrPiiSpan{{Kind: "phone_tr", Start: 8, End: 21}},
		},
		{
			text: "TC 10000000078",
			want: []TrPiiSpan{{Kind: "tc_kimlik", Start: 3, End: 14}},
		},
		{
			text: "Hesap TR33000610051978645841326 bakiyem",
			want: []TrPiiSpan{{Kind: "phone_tr", Start: 10, End: 21}},
		},
		{
			text: "Plaka 34ABC1234 burada",
			want: []TrPiiSpan{{Kind: "plate_tr", Start: 6, End: 15}},
		},
		{
			text: "VKN 1000000009 bilgisi",
			want: []TrPiiSpan{{Kind: "vkn", Start: 4, End: 14}},
		},
	}

	for _, tc := range cases {
		t.Run(tc.text, func(t *testing.T) {
			got := DetectTrPiiSpans(tc.text)
			if len(got) != len(tc.want) {
				t.Fatalf("%q: got %d spans, want %d", tc.text, len(got), len(tc.want))
			}
			for i, span := range got {
				if span != tc.want[i] {
					t.Fatalf("%q span %d = %+v, want %+v", tc.text, i, span, tc.want[i])
				}
			}
		})
	}
}

func TestTrPiiRedactionCrossLanguageParity(t *testing.T) {
	repoRoot := repoRootPath(t)
	corpus := generateTrPiiCorpus()

	expected := runPythonTrPiiRedactionParity(t, repoRoot, corpus)
	got := make([]string, len(corpus))
	for i, text := range corpus {
		got[i] = RedactTrPii(text)
	}

	if len(got) != len(expected) {
		t.Fatalf("mismatched corpus lengths: got %d, want %d", len(got), len(expected))
	}

	for i := range got {
		if got[i] != expected[i] {
			t.Fatalf("row %d mismatch:\ngot  %q\nwant %q", i, got[i], expected[i])
		}
	}
}

func repoRootPath(t *testing.T) string {
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("unable to determine caller path")
	}
	dir := filepath.Dir(filename)
	for i := 0; i < 8; i++ {
		if _, err := os.Stat(filepath.Join(dir, ".git", "config")); err == nil {
			return dir
		}
		if _, err := os.Stat(filepath.Join(dir, "ai", "__init__.py")); err == nil {
			return dir
		}
		dir = filepath.Dir(dir)
	}
	t.Fatal("could not locate repo root")
	return ""
}

func runPythonTrPiiRedactionParity(t *testing.T, repoRoot string, corpus []string) []string {
	payload, err := json.Marshal(corpus)
	if err != nil {
		t.Fatalf("marshal corpus: %v", err)
	}

	pyScript := `import json, os, sys
sys.path.insert(0, os.path.abspath("` + repoRoot + `"))
from ai.common.security.tr_pii import redact_tr_pii
corpus = json.load(sys.stdin)
output = [redact_tr_pii(text)[0] for text in corpus]
json.dump(output, sys.stdout, ensure_ascii=False)
`

	cmd := exec.Command("python3", "-c", pyScript)
	cmd.Dir = repoRoot
	cmd.Env = append(os.Environ(), "PYTHONPATH="+repoRoot)
	cmd.Stdin = bytes.NewReader(payload)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("python parity run failed: %v\n%s", err, string(out))
	}

	var parsed []string
	if err := json.Unmarshal(out, &parsed); err != nil {
		t.Fatalf("unmarshal python output: %v\n%s", err, string(out))
	}
	return parsed
}

func generateTrPiiCorpus() []string {
	corpus := make([]string, 0, 200)
	for i := 0; i < 50; i++ {
		corpus = append(corpus, fmt.Sprintf("Lütfen 0555-123-%04d arayın", i))
		corpus = append(corpus, fmt.Sprintf("TC 10000000146 kimlik paylaşmayın %d", i))
		corpus = append(corpus, fmt.Sprintf("Hesap TR33000610051978645841326 bakiyem %d", i))
		corpus = append(corpus, fmt.Sprintf("Plaka 34ABC123 burada %d", i))
	}
	return corpus
}
