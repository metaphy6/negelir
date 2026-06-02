package sec

import (
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// SanitizeText mirrors `ai/swarm/agents/sec/input.py::sanitize_text`.
// It applies two deterministic, idempotent transforms:
//
//  1. NFC normalize. Defends against canonical-equivalence smuggling
//     where an attacker uses combining sequences that look identical
//     to a precomposed character but bypass keyword filters.
//
//  2. Strip control characters (C0 minus \t \n \r, DEL, C1), zero-
//     width characters (ZWSP / ZWNJ / ZWJ / LRM / RLM), bidi-override
//     characters (LRE / RLE / PDF / LRO / RLO / LRI / RLI / FSI / PDI),
//     the BOM (U+FEFF), and SOFT HYPHEN (U+00AD).
//
// Returns the cleaned string, the ordered audit trail of which
// transforms ran (always `["nfc", "strip_control"]` so the wire
// contract is deterministic), and a `mutated` flag that is true iff
// the bytes actually changed. The mutated flag is the gateway's
// signal that something tried to smuggle a charset bypass; the
// caller fires a `sec.alert.v1{kind=charset_anomaly}` when true.
//
// Idempotency invariant — the second call must return mutated=false:
//
//	clean1, _, _ := SanitizeText(raw)
//	_, _, m := SanitizeText(clean1)
//	// m == false
func SanitizeText(raw string) (clean string, stepsRun []string, mutated bool) {
	nfc := norm.NFC.String(raw)
	stripped := stripControlAndZeroWidth(nfc)
	steps := []string{"nfc", "strip_control"}
	return stripped, steps, stripped != raw
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

// LowercaseTurkish applies a Turkish-aware lowercase: 'I' → 'ı' and
// 'İ' → 'i' (the dotted/dotless-i contract that breaks naive
// `strings.ToLower`). Used by the deterministic-pattern path so a
// rule looking for "ignore previous" matches a Turkish keyboard's
// "İGNORE PREVİOUS" too.
//
// Doctrine: this function is NEVER applied to the password field
// (per ROADMAP §7.1 password-field carve-out). Callers route
// password bytes around the entire sec pipeline.
func LowercaseTurkish(s string) string {
	if s == "" {
		return s
	}
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
