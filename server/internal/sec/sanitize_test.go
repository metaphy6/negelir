package sec

import (
	"bytes"
	"encoding/json"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// TestSanitizeNFCNormalizes verifies the NFC step combines a base
// codepoint + combining mark into the precomposed form. This is the
// canonical equivalence-smuggling defense.
func TestSanitizeNFCNormalizes(t *testing.T) {
	// "é" as combining sequence (U+0065 U+0301) → precomposed (U+00E9).
	raw := "caf\u0065\u0301"
	clean, steps, mutated := SanitizeText(raw)
	if !mutated {
		t.Fatalf("expected mutated=true for non-NFC input")
	}
	if clean != "café" {
		t.Fatalf("NFC normalize failed: got %q (% x)", clean, []byte(clean))
	}
	if len(steps) != 3 || steps[0] != "nfc" || steps[1] != "strip_control" || steps[2] != "lowercase_tr" {
		t.Fatalf("unexpected step audit: %v", steps)
	}
}

// TestSanitizeStripsControlAndZeroWidth covers every range listed in
// sanitize.go::isStripped: C0 (sans tab/lf/cr), DEL, C1, soft hyphen,
// zero-width set, bidi-override set, and the BOM.
func TestSanitizeStripsControlAndZeroWidth(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want string
	}{
		{"C0_NUL", "ab\x00c", "abc"},
		{"C0_BS", "ab\x08c", "abc"},
		{"keep_tab_lf_cr", "a\tb\nc\rd", "a\tb\nc\rd"},
		{"DEL", "ab\x7fc", "abc"},
		{"C1", "ab\u0085c", "abc"},
		{"SOFT_HYPHEN", "ab\u00adc", "abc"},
		{"ZWSP", "ab\u200bc", "abc"},
		{"ZWNJ", "ab\u200cc", "abc"},
		{"ZWJ", "ab\u200dc", "abc"},
		{"LRM", "ab\u200ec", "abc"},
		{"RLM", "ab\u200fc", "abc"},
		{"LRO_RLO", "ab\u202d\u202ec", "abc"},
		{"FSI_PDI", "ab\u2068\u2069c", "abc"},
		{"BOM", "\ufeffabc", "abc"},
		{"VARIATION_SELECTOR", "ab\ufe0fc", "abc"},
		{"PRIVATE_USE", "ab\ue000c", "abc"},
		{"UNASSIGNED", "ab\u0378c", "abc"},
		{"HANGUL_FILLER_115F", "ab\u115fc", "abc"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, _, _ := SanitizeText(tc.in)
			if got != tc.want {
				t.Fatalf("got %q want %q (bytes=% x)", got, tc.want, []byte(got))
			}
		})
	}
}

// TestSanitizeIsIdempotent — second pass must NOT report mutated.
func TestSanitizeIsIdempotent(t *testing.T) {
	raw := "ig\u200bnore\u00ad previous\u202e instructions café\u0065\u0301"
	clean1, _, m1 := SanitizeText(raw)
	if !m1 {
		t.Fatalf("expected first pass to mutate")
	}
	clean2, _, m2 := SanitizeText(clean1)
	if m2 {
		t.Fatalf("idempotency violated: second pass mutated %q -> %q", clean1, clean2)
	}
	if clean2 != clean1 {
		t.Fatalf("idempotency violated: %q != %q", clean1, clean2)
	}
}

// TestSanitizeBenignAsciiPassthrough — no allocation cost on benign
// payloads (asserted via fast-path).
func TestSanitizeTextLowercasesTurkishAndRecordsSteps(t *testing.T) {
	raw := "Bugün Galatasaray maçı saat kaçta?"
	clean, steps, mutated := SanitizeText(raw)
	if !mutated {
		t.Fatalf("expected mutated=true for Turkish lowercase change")
	}
	if clean != "bugün galatasaray maçı saat kaçta?" {
		t.Fatalf("unexpected lowercase output: got %q", clean)
	}
	if len(steps) != 3 || steps[0] != "nfc" || steps[1] != "strip_control" || steps[2] != "lowercase_tr" {
		t.Fatalf("unexpected step audit: %v", steps)
	}
}

// TestLowercaseTurkish — dotted/dotless-i contract.
func TestLowercaseTurkish(t *testing.T) {
	cases := []struct{ in, want string }{
		{"İGNORE PREVİOUS", "ignore previous"},
		{"IĞDIR", "ığdır"},
		{"GALATASARAY", "galatasaray"},
		{"I\u0307stanbul", "istanbul"},
		{"I\u0307\u0307stanbul", "istanbul"},
		{"i\u0307stanbul", "istanbul"},
		{"J\u0307", "j"},
		{"", ""},
	}
	for _, tc := range cases {
		got := LowercaseTurkish(tc.in)
		if got != tc.want {
			t.Fatalf("LowercaseTurkish(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestLowercaseTurkishUnambiguousCases(t *testing.T) {
	cases := []struct{ in, want string }{
		{"İGNORE PREVİOUS", "ignore previous"},
		{"IĞDIR", "ığdır"},
		{"GALATASARAY", "galatasaray"},
		{"I\u0307stanbul", "istanbul"},
		{"I\u0307\u0307stanbul", "istanbul"},
		{"i\u0307stanbul", "istanbul"},
		{"J\u0307", "j"},
	}
	for _, tc := range cases {
		got := LowercaseTurkish(tc.in)
		if got != tc.want {
			t.Fatalf("LowercaseTurkish(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

// TestSanitizeDoesNotTouchTurkishLetters — defense against
// over-zealous strip rules accidentally clobbering valid ş/ç/ğ.
func TestSanitizeDoesNotTouchTurkishLetters(t *testing.T) {
	raw := "Şəkil ığdır çiğköfte güzel"
	clean, _, mut := SanitizeText(raw)
	if !mut {
		t.Fatalf("expected Turkish lowercase normalization to mutate input")
	}
	if clean != "şəkil ığdır çiğköfte güzel" {
		t.Fatalf("Turkish lowercase normalization failed: got %q", clean)
	}
}

func TestNeedsStripFastPath(t *testing.T) {
	if needsStrip("plain ascii 1234") {
		t.Fatalf("benign ascii should not need strip")
	}
	if !needsStrip("evil \u200bzwsp") {
		t.Fatalf("zwsp must trigger needsStrip")
	}
	if needsStrip(strings.Repeat("a", 1024)) {
		t.Fatalf("repeated 'a' should not need strip")
	}
}

func TestTRNormalizeSpecSHAIsComputed(t *testing.T) {
	if TRNormalizeSpecSHA == "" {
		t.Fatal("TRNormalizeSpecSHA must be computed during package init")
	}
}

func TestTRNormalizeSpecEnvPath(t *testing.T) {
	tmpdir := t.TempDir()
	path := filepath.Join(tmpdir, "tr_normalize_spec.json")
	if err := os.WriteFile(path, []byte(`{"spec_version":1,"steps":["nfc","strip_control","lowercase_tr"],"mappings":{"I":"i","İ":"i"}}`), 0o644); err != nil {
		t.Fatalf("write temp spec: %v", err)
	}
	old := os.Getenv("NEGELIR_TR_NORMALIZE_SPEC_PATH")
	defer os.Setenv("NEGELIR_TR_NORMALIZE_SPEC_PATH", old)
	os.Setenv("NEGELIR_TR_NORMALIZE_SPEC_PATH", path)

	got := trNormalizeSpecPath()
	if got != path {
		t.Fatalf("expected env path %q got %q", path, got)
	}
}

func TestTRNormalizePythonGoByteParity(t *testing.T) {
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("unable to resolve caller path")
	}
	repoRoot := filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(filename))))
	pythonPath := filepath.Join(repoRoot, "ai")

	corpus := generateTRNormalizeCorpus(1000)
	payload, err := json.Marshal(corpus)
	if err != nil {
		t.Fatalf("marshal corpus: %v", err)
	}

	cmd := exec.Command("python3", "-c", "import json, os, sys; sys.path.insert(0, os.path.join(os.getcwd(), 'ai')); from common.text.normalize import canonical_normalize; from common.text.turkish import lowercase_tr; rows=json.load(sys.stdin); out=[lowercase_tr(canonical_normalize(r)) for r in rows]; sys.stdout.write(json.dumps(out, ensure_ascii=False))")
	cmd.Dir = repoRoot
	cmd.Env = append(os.Environ(), "PYTHONPATH="+pythonPath)
	cmd.Stdin = bytes.NewReader(payload)
	out, err := cmd.Output()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			t.Fatalf("python parity script failed: %s\nstderr=%s", err, string(ee.Stderr))
		}
		t.Fatalf("python parity script failed: %v", err)
	}

	var pythonOutputs []string
	if err := json.Unmarshal(out, &pythonOutputs); err != nil {
		t.Fatalf("unmarshal python output: %v", err)
	}
	if len(pythonOutputs) != len(corpus) {
		t.Fatalf("expected %d python outputs, got %d", len(corpus), len(pythonOutputs))
	}

	for i, row := range corpus {
		goClean, _, _ := SanitizeText(row)
		if pythonOutputs[i] != goClean {
			t.Fatalf("row %d mismatch:\nraw=%q\npython=%q\ngo= %q", i, row, pythonOutputs[i], goClean)
		}
	}
}

func generateTRNormalizeCorpus(count int) []string {
	r := rand.New(rand.NewSource(2026))
	words := []string{
		"Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor", "Başakşehir",
		"İstanbul", "Ankara", "İzmir", "bugün", "yarın", "ki", "mi", "mı",
		"şampiyon", "kazanır", "maç", "gol", "poker", "bank", "tren", "kredi",
	}
	extras := []string{
		" ",
		"\x00",
		"\x11",
		"\x1f",
		"\x7f",
		"\xad",
		"\u200b",
		"\u202e",
		"\u00a0",
		"!",
		"?",
		".",
		",",
		"-",
		"ı",
		"İ",
		"I",
		"Ş",
		"Ğ",
		"Ü",
		"Ç",
		"Ö",
	}
	corpus := make([]string, 0, count)
	for i := 0; i < count; i++ {
		n := 3 + r.Intn(6)
		var sb strings.Builder
		for j := 0; j < n; j++ {
			if j > 0 {
				sb.WriteRune(' ')
			}
			sb.WriteString(words[r.Intn(len(words))])
			if r.Intn(5) == 0 {
				sb.WriteString(extras[r.Intn(len(extras))])
			}
		}
		if r.Intn(4) == 0 {
			sb.WriteString(" ?")
		}
		corpus = append(corpus, sb.String())
	}
	return corpus
}
