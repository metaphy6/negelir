package sec

import (
	"encoding/json"
	"os/exec"
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

func TestDetectTrPiiSpansParityWithPython(t *testing.T) {
    root := repoRoot(t)
    cmd := exec.Command(
        "python3",
        "-c",
        `import json, sys, pathlib
root = pathlib.Path.cwd()
sys.path.insert(0, str(root / 'ai'))
from common.security.tr_pii import detect_tr_pii_spans
cases = [
    "Lütfen 0555-123-4567 arayın",
    "TC 10000000078",
    "Hesap TR33000610051978645841326 bakiyem",
    "Plaka 34ABC1234 burada",
    "VKN 1000000009 bilgisi",
]
results = []
for text in cases:
    spans = detect_tr_pii_spans(text)
    results.append([
        {"kind": span.kind, "text": text[span.start:span.end], "start": span.start, "end": span.end}
        for span in spans
    ])
print(json.dumps(results))
`,
    )
    cmd.Dir = root
    out, err := cmd.CombinedOutput()
    if err != nil {
        t.Fatalf("python parity check failed: %v: %s", err, out)
    }
    var pyResults [][]struct {
        Kind  string `json:"kind"`
        Text  string `json:"text"`
        Start int    `json:"start"`
        End   int    `json:"end"`
    }
    if err := json.Unmarshal(out, &pyResults); err != nil {
        t.Fatalf("unmarshal python output: %v", err)
    }
    if len(pyResults) != 5 {
        t.Fatalf("expected 5 python result rows, got %d", len(pyResults))
    }
    cases := []string{
        "Lütfen 0555-123-4567 arayın",
        "TC 10000000078",
        "Hesap TR33000610051978645841326 bakiyem",
        "Plaka 34ABC1234 burada",
        "VKN 1000000009 bilgisi",
    }
    for i, text := range cases {
        got := DetectTrPiiSpans(text)
        if len(got) != len(pyResults[i]) {
            t.Fatalf("case %d mismatch count: go=%d python=%d", i, len(got), len(pyResults[i]))
        }
        for j, span := range got {
            if span.Kind != pyResults[i][j].Kind {
                t.Fatalf("case %d span %d kind mismatch: go=%s python=%s", i, j, span.Kind, pyResults[i][j].Kind)
            }
            if text[span.Start:span.End] != pyResults[i][j].Text {
                t.Fatalf("case %d span %d text mismatch: go=%q python=%q", i, j, text[span.Start:span.End], pyResults[i][j].Text)
            }
        }
    }
}
