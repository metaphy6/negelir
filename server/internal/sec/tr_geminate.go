package sec

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"gopkg.in/yaml.v3"
)

type GeminateRestorationRule struct {
	Stem        string `yaml:"stem"`
	DoubledForm string `yaml:"doubled_form"`
	Source      string `yaml:"source"`
}

type geminateRestorationYAML struct {
	Meta                 map[string]any            `yaml:"_meta"`
	GeminateRestorations []GeminateRestorationRule `yaml:"geminate_restorations"`
}

func LoadGeminateRestorations(path string) ([]GeminateRestorationRule, error) {
	if path == "" {
		var err error
		path, err = defaultGeminateRestorationPath()
		if err != nil {
			return nil, err
		}
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read geminate restoration rules: %w", err)
	}

	var raw geminateRestorationYAML
	if err := yaml.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("parse geminate restoration rules: %w", err)
	}
	if raw.Meta == nil {
		return nil, fmt.Errorf("%s: missing _meta", filepath.Base(path))
	}
	schemaVersion, ok := raw.Meta["schema_version"]
	if !ok {
		return nil, fmt.Errorf("%s: missing schema_version", filepath.Base(path))
	}
	if sv, ok := schemaVersion.(int); ok {
		if sv != 1 {
			return nil, fmt.Errorf("%s: expected schema_version=1, got %d", filepath.Base(path), sv)
		}
	} else if sv, ok := schemaVersion.(float64); ok {
		if int(sv) != 1 {
			return nil, fmt.Errorf("%s: expected schema_version=1, got %v", filepath.Base(path), sv)
		}
	} else {
		return nil, fmt.Errorf("%s: expected integer schema_version, got %T", filepath.Base(path), schemaVersion)
	}

	rules := make([]GeminateRestorationRule, 0, len(raw.GeminateRestorations))
	for _, rule := range raw.GeminateRestorations {
		rate := strings.TrimSpace(rule.Stem)
		doubled := strings.TrimSpace(rule.DoubledForm)
		source := strings.TrimSpace(rule.Source)
		if rate == "" || doubled == "" {
			return nil, fmt.Errorf("%s: invalid geminate restoration row: %#v", filepath.Base(path), rule)
		}
		if !strings.HasPrefix(doubled, rate) {
			return nil, fmt.Errorf("%s: doubled_form %q must start with stem %q", filepath.Base(path), doubled, rate)
		}
		rules = append(rules, GeminateRestorationRule{
			Stem:        rate,
			DoubledForm: doubled,
			Source:      source,
		})
	}
	return rules, nil
}

func defaultGeminateRestorationPath() (string, error) {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		return "", fmt.Errorf("cannot determine source path")
	}
	return filepath.Join(filepath.Dir(file), "..", "..", "..", "ai", "nlp", "lang_tr", "spelling", "geminate_restoration.tr.yaml"), nil
}

func RestoreGeminate(token string, lookup func(string) bool, rules []GeminateRestorationRule) (string, bool) {
	if token == "" || lookup == nil {
		return token, false
	}
	for _, rule := range rules {
		if !strings.HasPrefix(token, rule.DoubledForm) {
			continue
		}
		if !isVowelInitialSuffix(token, rule.DoubledForm) {
			continue
		}
		if !lookup(token) {
			continue
		}
		return token, true
	}
	return token, false
}

func isVowelInitialSuffix(token, prefix string) bool {
	tokenRunes := []rune(token)
	prefixRunes := []rune(prefix)
	if len(tokenRunes) <= len(prefixRunes) {
		return false
	}
	return isTurkishVowel(tokenRunes[len(prefixRunes)])
}

func isTurkishVowel(r rune) bool {
	switch r {
	case 'a', 'e', 'ı', 'i', 'o', 'ö', 'u', 'ü',
		'A', 'E', 'I', 'İ', 'O', 'Ö', 'U', 'Ü':
		return true
	}
	return false
}
