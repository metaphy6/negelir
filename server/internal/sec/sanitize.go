package sec

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// Idempotency invariant — the second call must return mutated=false:
//
//	clean1, _, _ := SanitizeText(raw)
//	_, _, m := SanitizeText(clean1)
//	// m == false
func SanitizeText(raw string) (clean string, stepsRun []string, mutated bool) {
	nfc := norm.NFC.String(raw)
	stripped := stripControlAndZeroWidth(nfc)
	lowercased := LowercaseTurkish(stripped)
	steps := []string{"nfc", "strip_control", "lowercase_tr"}
	return lowercased, steps, lowercased != raw
}

// stripControlAndZeroWidth removes the same code points the Python
// regex in `sec/input.py::_STRIP_CONTROL_RE` strips. Implemented as a
// rune-by-rune copy because Go's regexp engine compiles each pattern
// once but the per-call allocation cost matters for the hot path; the
// switch-based loop below is ~10x faster on benign inputs.
func stripControlAndZeroWidth(s string) string {
	if !needsStrip(s) {
		return s
	}
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		if isStripped(r) {
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}

var allowedFormatCodepoints = map[rune]bool{}
var hangulFillerRunes = map[rune]bool{
	0x115F: true,
	0x1160: true,
	0x3164: true,
}

const defaultTRNormalizeSpecPath = "ai/common/text/tr_normalize_spec.json"

var TRNormalizeSpecSHA string

func init() {
	if err := verifyTRNormalizeSpec(); err != nil {
		panic(err)
	}
}

func trNormalizeSpecPath() string {
	if path := strings.TrimSpace(os.Getenv("NEGELIR_TR_NORMALIZE_SPEC_PATH")); path != "" {
		return path
	}
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		panic("unable to resolve caller path")
	}
	repoRoot := filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(filename))))
	return filepath.Join(repoRoot, defaultTRNormalizeSpecPath)
}

func verifyTRNormalizeSpec() error {
	path := trNormalizeSpecPath()
	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("failed to open tr_normalize_spec: %w", err)
	}
	defer file.Close()
	raw, err := io.ReadAll(file)
	if err != nil {
		return fmt.Errorf("failed to read tr_normalize_spec: %w", err)
	}
	var parsed map[string]any
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return fmt.Errorf("invalid tr_normalize_spec JSON: %w", err)
	}
	version, ok := parsed["spec_version"]
	if !ok {
		return fmt.Errorf("tr_normalize_spec.spec_version missing")
	}
	versionFloat, ok := version.(float64)
	if !ok || int(versionFloat) != 1 {
		return fmt.Errorf("tr_normalize_spec.spec_version must be 1")
	}
	steps, ok := parsed["steps"].([]any)
	if !ok {
		return fmt.Errorf("tr_normalize_spec.steps must be a list")
	}
	required := map[string]bool{"nfc": true, "strip_control": true, "lowercase_tr": true}
	for _, rawStep := range steps {
		step, ok := rawStep.(string)
		if !ok {
			return fmt.Errorf("tr_normalize_spec.steps must be strings")
		}
		delete(required, step)
	}
	if len(required) > 0 {
		return fmt.Errorf("tr_normalize_spec missing required steps: %v", required)
	}
	mappings, ok := parsed["mappings"].(map[string]any)
	if !ok {
		return fmt.Errorf("tr_normalize_spec.mappings must be an object")
	}
	for _, requiredKey := range []string{"I", "İ"} {
		if _, ok := mappings[requiredKey]; !ok {
			return fmt.Errorf("tr_normalize_spec.mappings missing required key %q", requiredKey)
		}
	}
	hash := sha256.Sum256(raw)
	TRNormalizeSpecSHA = fmt.Sprintf("%x", hash[:])
	return nil
}

// needsStrip is a fast-path check: return false (no allocation needed)
// when the string is plain ASCII printable + whitespace + non-Latin
// codepoints that don't fall in any stripped range. The check inspects
// runes lazily — on the first hit it returns true.
func needsStrip(s string) bool {
	for _, r := range s {
		if isStripped(r) {
			return true
		}
	}
	return false
}

// isStripped reports whether the rune is in the strip-set documented
// above. Kept as a single function so the strip and the fast-path
// check stay in lock-step.
func isStripped(r rune) bool {
	switch {
	case r == '\t' || r == '\n' || r == '\r':
		return false // explicit allow-list
	case r >= 0x00 && r <= 0x08:
		return true
	case r == 0x0B || r == 0x0C:
		return true
	case r >= 0x0E && r <= 0x1F:
		return true
	case r == 0x7F: // DEL
		return true
	case r >= 0x80 && r <= 0x9F: // C1
		return true
	case r == 0x00AD: // SOFT HYPHEN
		return true
	case r >= 0x200B && r <= 0x200F: // ZWSP / ZWNJ / ZWJ / LRM / RLM
		return true
	case r >= 0x202A && r <= 0x202E: // LRE / RLE / PDF / LRO / RLO
		return true
	case r >= 0x2066 && r <= 0x2069: // LRI / RLI / FSI / PDI
		return true
	case r == 0xFEFF: // BOM / ZWNBSP
		return true
	case r >= 0xFE00 && r <= 0xFE0F: // Variation selectors
		return true
	case unicode.Is(unicode.Cf, r):
		return !allowedFormatCodepoints[r]
	case unicode.Is(unicode.Cn, r) || unicode.Is(unicode.Co, r) || unicode.Is(unicode.Cs, r):
		return true
	case hangulFillerRunes[r]:
		return true
	}
	return false
}

const combiningDotAbove = '\u0307'
const combiningMarkStart = '\u0300'
const combiningMarkEnd = '\u036F'

func composeTurkishDottedI(s string) string {
	runes := []rune(s)
	out := make([]rune, 0, len(runes))
	for i := 0; i < len(runes); {
		if i+1 < len(runes) && runes[i+1] == combiningDotAbove {
			switch runes[i] {
			case 'I':
				out = append(out, 'İ')
			case 'i', 'J':
				out = append(out, runes[i])
			default:
				out = append(out, runes[i])
			}
			i += 2
			continue
		}
		out = append(out, runes[i])
		i++
	}
	return string(out)
}

// LowercaseTurkish applies a Turkish-aware lowercase: 'I' → 'ı' and
// 'İ' → 'i' (the dotted/dotless-i contract that breaks naive
// `strings.ToLower`). Used by the deterministic-pattern path so a
// rule looking for "ignore previous" matches a Turkish keyboard's
// "İGNORE PREVİOUS" too.
//
// Doctrine: this function is NEVER applied to the password field
// (per ROADMAP §7.1 password-field carve-out). Callers route
// password bytes around the entire sec pipeline.
func stripTurkishCombiningMarks(s string) string {
	runes := []rune(s)
	out := make([]rune, 0, len(runes))
	for _, r := range runes {
		if r >= combiningMarkStart && r <= combiningMarkEnd {
			continue
		}
		out = append(out, r)
	}
	return string(out)
}

func LowercaseTurkish(s string) string {
	if s == "" {
		return s
	}
	s = composeTurkishDottedI(s)
	s = stripTurkishCombiningMarks(s)
	runes := []rune(s)
	for i, r := range runes {
		switch r {
		case 'I':
			runes[i] = 'ı'
		case 'İ':
			runes[i] = 'i'
		default:
			runes[i] = unicode.ToLower(r)
		}
	}
	return string(runes)
}
