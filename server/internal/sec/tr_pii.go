package sec

import (
	"crypto/sha256"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

type TrPiiSpan struct {
    Kind  string
    Start int
    End   int
}

var (
    redactedTokenRe = regexp.MustCompile(`\[REDACTED:([A-Z_]+):sha8=([0-9a-f]{8})\]`)
    tcKimlikRe      = regexp.MustCompile(`(^|[^0-9])([1-9][0-9]{10})([^0-9]|$)`)
    ibanTrRe        = regexp.MustCompile(`(TR[0-9]{2}(?:\s?[0-9]{4}){6})`)
    phoneTrRe       = regexp.MustCompile(`(?:\+90|0090|0)\s?[0-9]{3}[\s\-]?[0-9]{3}[\s\-]?[0-9]{2}[\s\-]?[0-9]{2}`)
    plateTrRe       = regexp.MustCompile(`\b(0[1-9]|[1-7][0-9]|8[01])\s?[A-ZÇĞİÖŞÜ]{1,3}\s?[0-9]{2,4}\b`)
    vknRe           = regexp.MustCompile(`(^|[^0-9])([0-9]{10})([^0-9]|$)`)
)

func sha8(value string) string {
    h := sha256.Sum256([]byte(value))
    return fmt.Sprintf("%x", h[:4])
}

func validateTcKimlik(value string) bool {
    if len(value) != 11 || value[0] == '0' {
        return false
    }
    digits := make([]int, len(value))
    for i, ch := range value {
        digits[i] = int(ch - '0')
    }
    if (digits[0]+digits[1]+digits[2]+digits[3]+digits[4]+digits[5]+digits[6]+digits[7]+digits[8]+digits[9])%10 != digits[10] {
        return false
    }
    oddSum := digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
    evenSum := digits[1] + digits[3] + digits[5] + digits[7]
    return ((oddSum*7 - evenSum) % 10) == digits[9]
}

func validateVkn(value string) bool {
    if len(value) != 10 {
        return false
    }
    total := 0
    weights := []int{1, 2, 1, 2, 1, 2, 1, 2, 1, 2}
    for i, ch := range value {
        digit := int(ch - '0')
        product := digit * weights[i]
        total += product/10 + product%10
    }
    return total%10 == 0
}

func appendSpan(spans []TrPiiSpan, candidate TrPiiSpan) []TrPiiSpan {
    for _, existing := range spans {
        if candidate.Start < existing.End && existing.Start < candidate.End {
            return spans
        }
    }
    return append(spans, candidate)
}

func DetectTrPiiSpans(text string) []TrPiiSpan {
    spans := make([]TrPiiSpan, 0, 4)

    for _, match := range tcKimlikRe.FindAllStringSubmatchIndex(text, -1) {
        value := text[match[4]:match[5]]
        if validateTcKimlik(value) {
            spans = appendSpan(spans, TrPiiSpan{"tc_kimlik", match[4], match[5]})
        }
    }
    for _, match := range ibanTrRe.FindAllStringSubmatchIndex(text, -1) {
        spans = appendSpan(spans, TrPiiSpan{"iban_tr", match[1], match[2]})
    }
    for _, match := range phoneTrRe.FindAllStringIndex(text, -1) {
        spans = appendSpan(spans, TrPiiSpan{"phone_tr", match[0], match[1]})
    }
    for _, match := range plateTrRe.FindAllStringIndex(text, -1) {
        spans = appendSpan(spans, TrPiiSpan{"plate_tr", match[0], match[1]})
    }
    for _, match := range vknRe.FindAllStringSubmatchIndex(text, -1) {
        value := text[match[4]:match[5]]
        if validateVkn(value) {
            spans = appendSpan(spans, TrPiiSpan{"vkn", match[4], match[5]})
        }
    }

    sort.Slice(spans, func(i, j int) bool {
        if spans[i].Start != spans[j].Start {
            return spans[i].Start < spans[j].Start
        }
        return spans[i].End < spans[j].End
    })
    return spans
}

func RedactTrPii(text string) string {
    spans := DetectTrPiiSpans(text)
    if len(spans) == 0 {
        return text
    }
    var builder strings.Builder
    last := 0
    for _, span := range spans {
        builder.WriteString(text[last:span.Start])
        builder.WriteString("[REDACTED:")
        builder.WriteString(strings.ToUpper(span.Kind))
        builder.WriteString(":sha8=")
        builder.WriteString(sha8(text[span.Start:span.End]))
        builder.WriteString("]")
        last = span.End
    }
    builder.WriteString(text[last:])
    return builder.String()
}

func ParseRedactedTrPii(text string) []TrPiiSpan {
    spans := make([]TrPiiSpan, 0)
    for _, match := range redactedTokenRe.FindAllStringSubmatchIndex(text, -1) {
        kind := strings.ToLower(text[match[2]:match[3]])
        spans = append(spans, TrPiiSpan{kind, match[2], match[5]})
    }
    return spans
}
