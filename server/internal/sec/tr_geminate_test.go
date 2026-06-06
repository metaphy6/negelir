package sec

import (
	"testing"
)

func TestLoadGeminateRestorationsSuccess(t *testing.T) {
	rules, err := LoadGeminateRestorations("")
	if err != nil {
		t.Fatalf("LoadGeminateRestorations failed: %v", err)
	}
	if len(rules) != 5 {
		t.Fatalf("expected 5 geminate restoration rules, got %d", len(rules))
	}
}

func TestRestoreGeminateKnownDoubleForms(t *testing.T) {
	rules, err := LoadGeminateRestorations("")
	if err != nil {
		t.Fatalf("LoadGeminateRestorations failed: %v", err)
	}

	lexicon := map[string]struct{}{}
	for _, token := range []string{"hakkı", "sırrı", "hissi", "zannı", "şıkkı"} {
		lexicon[token] = struct{}{}
	}

	lookup := func(token string) bool {
		_, ok := lexicon[token]
		return ok
	}

	for _, token := range []string{"hakkı", "sırrı", "hissi", "zannı", "şıkkı"} {
		repaired, restored := RestoreGeminate(token, lookup, rules)
		if repaired != token {
			t.Fatalf("expected %q to remain unchanged, got %q", token, repaired)
		}
		if !restored {
			t.Fatalf("expected %q to be recognized as a geminate restoration candidate", token)
		}
	}
}

func TestRestoreGeminateNegativeForms(t *testing.T) {
	rules, err := LoadGeminateRestorations("")
	if err != nil {
		t.Fatalf("LoadGeminateRestorations failed: %v", err)
	}

	lexicon := map[string]struct{}{}
	for _, token := range []string{"golü", "topu", "bankı", "gollü", "toppu", "çayı", "maçı", "sahası", "futbolu", "şarkı"} {
		lexicon[token] = struct{}{}
	}

	lookup := func(token string) bool {
		_, ok := lexicon[token]
		return ok
	}

	for _, token := range []string{"golü", "topu", "bankı", "gollü", "toppu", "çayı", "maçı", "sahası", "futbolu", "şarkı"} {
		repaired, restored := RestoreGeminate(token, lookup, rules)
		if repaired != token {
			t.Fatalf("expected %q to remain unchanged, got %q", token, repaired)
		}
		if restored {
			t.Fatalf("expected %q not to be recognized as a geminate restoration candidate", token)
		}
	}
}

func TestGoGeminateRestorationUsesSharedRuleFile(t *testing.T) {
	path, err := defaultGeminateRestorationPath()
	if err != nil {
		t.Fatalf("default geminate restoration path failed: %v", err)
	}
	rules, err := LoadGeminateRestorations(path)
	if err != nil {
		t.Fatalf("LoadGeminateRestorations failed for shared file: %v", err)
	}
	if len(rules) != 5 {
		t.Fatalf("expected 5 rules from shared YAML, got %d", len(rules))
	}
}
