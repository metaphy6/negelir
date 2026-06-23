package sec

import (
	"fmt"
	"regexp"
	"sort"

	"gopkg.in/yaml.v3"
)

// CompiledRule is one entry from `injection_patterns.yaml` after
// validation. The fields mirror the Python `RuleSet`/`CompiledRule`
// pair in `common/security/patterns.py`.
type CompiledRule struct {
	ID       string
	Severity string // info | warn | error | critical
	Kind     string // SecAlertKind member; defaults to "prompt_injection"
	Reason   string
	Regex    *regexp.Regexp
}

// RuleSet is the in-memory, hot-swappable view of an injection-pattern
// YAML file. Construct with LoadInjectionPatterns; then call Match to
// get the first hit (rules are scanned in YAML insertion order so an
// operator can place high-confidence patterns first to short-circuit
// the scan).
type RuleSet struct {
	Version int
	Rules   []*CompiledRule
}

// PatternHit is the outcome of a positive Match.
type PatternHit struct {
	Rule *CompiledRule
}

var allowedSeverities = map[string]struct{}{
	"info": {}, "warn": {}, "error": {}, "critical": {},
}

// allowedKinds mirrors the v1 KNOWN_SEC_ALERT_KINDS open-enum on the
// Python side; the Go side enforces the SAME allow-list to keep both
// producers in lockstep with the JSON schema.
var allowedKinds = map[string]struct{}{
	"prompt_injection":         {},
	"homoglyph_attack":         {},
	"language_spoof":           {},
	"payload_oversize":         {},
	"encoded_redirect":         {},
	"charset_anomaly":          {},
	"classifier_degraded":      {},
	"classifier_load_shed":     {},
	"pattern_reload":           {},
	"dom_size_delta":           {},
	"suspicious_js":            {},
	"content_type_mismatch":    {},
	"inflate_ratio_outlier":    {},
	"seed_drift":               {},
	"baseline_warmup":          {},
	"baseline_reset":           {},
	"rate_burst":               {},
	"rate_throttled":           {},
	"rate_redis_degraded":      {},
	"rate_script_reloaded":     {},
	"denylist_added":           {},
	"denylist_removed":         {},
	"denylist_growth_anomaly":  {},
	"subject_map_churn":        {},
	"quarantine_overflow":      {},
	"quarantine_storage_slow":  {},
	"refresh_token_replay":              {},
	"jti_revocation_set_pressure":       {},
}

var snakeCaseID = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

// rawPattern is the on-disk YAML shape (we do not export it).
type rawPattern struct {
	ID       string `yaml:"id"`
	Pattern  string `yaml:"pattern"`
	Severity string `yaml:"severity"`
	Kind     string `yaml:"kind"`
	Reason   string `yaml:"reason"`
}

type rawRuleFile struct {
	Version  int          `yaml:"version"`
	Patterns []rawPattern `yaml:"patterns"`
}

// LoadInjectionPatterns parses + validates an injection-pattern YAML
// payload (typically EmbeddedInjectionPatternsYAML). Returns a
// PatternFileError-equivalent (plain error wrapping the offending id
// or rule index) on the first validation failure — the caller does
// NOT swap in a partial ruleset, mirroring the Python loader's
// "validate-then-swap" doctrine.
//
// Validation rules (binding, mirror Python `load_ruleset`):
//
//   - top-level shape `{version: int, patterns: [...]}` only;
//   - version >= 1;
//   - patterns list non-empty;
//   - id snake_case (`^[a-z][a-z0-9_]*$`), unique across the file;
//   - severity in {info, warn, error, critical};
//   - kind in the closed allow-list (see `allowedKinds`); defaults to
//     "prompt_injection" if omitted;
//   - regex compiles under Go's RE2 engine. Patterns that use PCRE-
//     only constructs (backrefs, lookbehinds) will fail to compile —
//     that is a feature, not a bug; the Python loader already refuses
//     them so a Go-side compilation failure surfaces a Python-Go
//     drift.
func LoadInjectionPatterns(body []byte) (*RuleSet, error) {
	var raw rawRuleFile
	if err := yaml.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("injection_patterns: yaml parse: %w", err)
	}
	if raw.Version < 1 {
		return nil, fmt.Errorf("injection_patterns: version must be >= 1, got %d", raw.Version)
	}
	if len(raw.Patterns) == 0 {
		return nil, fmt.Errorf("injection_patterns: must list at least one pattern")
	}

	seen := make(map[string]struct{}, len(raw.Patterns))
	rules := make([]*CompiledRule, 0, len(raw.Patterns))
	for i, p := range raw.Patterns {
		if !snakeCaseID.MatchString(p.ID) {
			return nil, fmt.Errorf("injection_patterns[%d]: id %q must be snake_case (^[a-z][a-z0-9_]*$)", i, p.ID)
		}
		if _, dup := seen[p.ID]; dup {
			return nil, fmt.Errorf("injection_patterns[%d]: duplicate id %q", i, p.ID)
		}
		seen[p.ID] = struct{}{}

		if _, ok := allowedSeverities[p.Severity]; !ok {
			return nil, fmt.Errorf("injection_patterns[%s]: severity %q not in {info,warn,error,critical}", p.ID, p.Severity)
		}

		kind := p.Kind
		if kind == "" {
			kind = "prompt_injection"
		}
		if _, ok := allowedKinds[kind]; !ok {
			return nil, fmt.Errorf("injection_patterns[%s]: kind %q is not a known SecAlertKind", p.ID, kind)
		}

		// Patterns are case-insensitive (per YAML doctrine); RE2
		// accepts the (?i) flag prefix.
		re, err := regexp.Compile("(?i)" + p.Pattern)
		if err != nil {
			return nil, fmt.Errorf("injection_patterns[%s]: regex compile: %w", p.ID, err)
		}
		rules = append(rules, &CompiledRule{
			ID:       p.ID,
			Severity: p.Severity,
			Kind:     kind,
			Reason:   p.Reason,
			Regex:    re,
		})
	}
	return &RuleSet{Version: raw.Version, Rules: rules}, nil
}

// Match returns the first rule that fires on `s`, or nil if none.
// Order is the YAML insertion order (operators put high-confidence
// patterns first to short-circuit).
func (rs *RuleSet) Match(s string) *PatternHit {
	if rs == nil {
		return nil
	}
	for _, r := range rs.Rules {
		if r.Regex.MatchString(s) {
			return &PatternHit{Rule: r}
		}
	}
	return nil
}

// IDs returns every rule id in load order. Used by tests that want a
// stable enumeration.
func (rs *RuleSet) IDs() []string {
	out := make([]string, 0, len(rs.Rules))
	for _, r := range rs.Rules {
		out = append(out, r.ID)
	}
	return out
}

// IDsSorted returns the rule ids sorted alphabetically — handy for
// snapshot tests that should be insensitive to YAML re-ordering.
func (rs *RuleSet) IDsSorted() []string {
	out := rs.IDs()
	sort.Strings(out)
	return out
}
