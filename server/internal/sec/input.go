package sec

// QAInputGate is the Phase 7 §7.1 in-process gate that the Go gateway
// runs on every QA payload BEFORE publishing `qa.request` /
// `qa.request.v1`. It owns the deterministic side of the sec.input
// pipeline (steps 1–4 of design/SECURITY.md):
//
//   1. length cap (bytes after UTF-8 encoding, NOT codepoints — a
//      4 KiB JSON body of \u0001 chars is 6 KiB on the wire)
//   2. NFC + control / zero-width / RTL strip
//   3. Turkish-aware lowercase pre-pattern fold
//   4. deterministic injection-pattern engine
//
// Step 5 (small classifier) lives in the Python `sec.input.v1` agent.
// The gate's verdicts are mutually exclusive and exhaustive:
//
//   * `Pass`       → publish qa.request.v1 directly with sec_verdict=pass
//   * `Sanitize`   → text was mutated; publish qa.request.v1 with
//                    sec_verdict=sanitized + the audit trail
//   * `Quarantine` → an injection rule fired; the gateway writes
//                    sec.quarantine.v1 + a 400 response, never
//                    publishes qa.request.v1
//
// The gate is constructor-injected with the RuleSet (so tests can
// drive a controlled set of rules without disk I/O) and the
// length cap (so tests can drive a 1-byte limit).
type QAInputGate struct {
	rules     *RuleSet
	maxLenB   int
}

// NewQAInputGate builds a gate. `rules` may be nil for a test that
// only wants to exercise length / sanitize behaviour; in production
// the loader fails the binary if injection_patterns.yaml is invalid.
func NewQAInputGate(rules *RuleSet, maxLenBytes int) *QAInputGate {
	if maxLenBytes < 0 {
		maxLenBytes = 0
	}
	return &QAInputGate{rules: rules, maxLenB: maxLenBytes}
}

// QAVerdict is one of the three exhaustive outcomes.
type QAVerdict string

const (
	VerdictPass       QAVerdict = "pass"
	VerdictSanitize   QAVerdict = "sanitize"
	VerdictQuarantine QAVerdict = "quarantine"
)

// QADecision is the gate's full output.
//
// `Sanitized` is the text safe to forward on `qa.request.v1`. For
// VerdictPass it equals the input. For VerdictSanitize it is the
// transformed text. For VerdictQuarantine the gateway MUST NOT
// publish `qa.request.v1` at all — `Sanitized` is left as the
// transformed text only so the quarantine envelope can carry it for
// forensic review (the raw bytes go on `sec.quarantine.v1` separately).
type QADecision struct {
	Verdict     QAVerdict
	Sanitized   string
	StepsRun    []string // ordered audit trail of which transforms ran
	Reasons     []string // populated for VerdictQuarantine (rule kind, rule id, reason)
	HitRule     *CompiledRule
	WireBytes   int    // length of the input *as bytes* (UTF-8)
	OversizedBy int    // bytes-over-cap for VerdictQuarantine{kind=payload_oversize}; 0 otherwise
	Mutated     bool   // true iff sanitize altered the bytes
	OversizeKind string // "payload_oversize" when oversize triggered (else "")
}

// Inspect runs the deterministic pipeline against `raw`.
//
// Length cap. The cap is `cfg.sec_input_max_len` BYTES. Empty cap
// (== 0) disables the check entirely (useful for tests; production
// config is always positive). Oversized → VerdictQuarantine with
// kind=payload_oversize.
//
// Sanitize. NFC + control-strip (mirror of Python sanitize_text).
// Mutated bytes flip the verdict to VerdictSanitize so the wire
// audit trail records `sec_verdict=sanitized`. The length cap is
// applied to the RAW bytes (pre-sanitize) — sanitize CAN shrink
// the byte count, but that does not retroactively rescue an
// oversized payload (otherwise an attacker could pad with stripped
// chars).
//
// Patterns. Run on the LOWERCASED, SANITIZED text so a rule
// targeting "ignore previous instructions" matches "İGNORE
// PREVİOUS" too. First match wins; the rule's kind + id + reason
// land in the wire `Reasons` field.
func (g *QAInputGate) Inspect(raw string) QADecision {
	rawBytes := len(raw)
	dec := QADecision{
		Sanitized: raw,
		StepsRun:  []string{},
		WireBytes: rawBytes,
	}
	// 1. length cap (before any other work — the cheapest gate).
	if g.maxLenB > 0 && rawBytes > g.maxLenB {
		dec.Verdict = VerdictQuarantine
		dec.OversizedBy = rawBytes - g.maxLenB
		dec.OversizeKind = "payload_oversize"
		dec.Reasons = []string{
			"payload_oversize",
			"exceeded sec_input_max_len",
		}
		return dec
	}
	// 2. sanitize
	clean, steps, mutated := SanitizeText(raw)
	dec.Sanitized = clean
	dec.StepsRun = steps
	dec.Mutated = mutated
	if mutated {
		dec.Verdict = VerdictSanitize
	} else {
		dec.Verdict = VerdictPass
	}
	// 3. patterns. Note: lowercase fold is applied for the MATCH only;
	// the wire payload carries the case-preserving sanitized text so
	// the NLP layer can do its own casing.
	if g.rules != nil {
		probe := LowercaseTurkish(clean)
		if hit := g.rules.Match(probe); hit != nil {
			dec.Verdict = VerdictQuarantine
			dec.HitRule = hit.Rule
			dec.Reasons = []string{hit.Rule.Kind, "rule:" + hit.Rule.ID, hit.Rule.Reason}
		}
	}
	return dec
}

// PasswordPasses lets the auth handler drop the password field
// straight through the sec pipeline — the gate ONLY checks that the
// length cap is respected (oversize defense, defense against memory-
// exhaustion bcrypt calls). It does NOT NFC-normalize, lowercase,
// pattern-match, or strip control chars. The returned `Sanitized`
// always equals the raw input on Pass; on payload_oversize it is
// the empty string and the caller MUST refuse the request.
//
// Boundary test (binding §7.1 password-field carve-out): a known
// non-NFC password byte-stream survives this call unchanged.
func (g *QAInputGate) PasswordPasses(raw string) QADecision {
	rawBytes := len(raw)
	dec := QADecision{
		Sanitized: raw,
		StepsRun:  []string{}, // intentionally empty — NO transforms applied
		WireBytes: rawBytes,
		Verdict:   VerdictPass,
	}
	if g.maxLenB > 0 && rawBytes > g.maxLenB {
		dec.Verdict = VerdictQuarantine
		dec.OversizedBy = rawBytes - g.maxLenB
		dec.OversizeKind = "payload_oversize"
		dec.Reasons = []string{
			"payload_oversize",
			"exceeded sec_input_max_len (password field)",
		}
		dec.Sanitized = ""
	}
	return dec
}
