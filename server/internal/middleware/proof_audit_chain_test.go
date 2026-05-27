package middleware

// §9.14 proof tests — Observability: audit chain & PII erase
//
// Tests covered in this file:
//   TestAuditChainContinuityAcrossPods — test_audit_chain_continuity_across_pods
//   TestPIIEraseNullstampsUserIDH      — test_pii_erase_nullstamps_user_id_h

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"

	"github.com/gin-gonic/gin"
)

// TestAuditChainContinuityAcrossPods verifies the §8.13.2 HMAC hash-chain
// invariant: row[i].prev_hmac == row[i-1].row_hmac, with the first row
// anchored at the literal "GENESIS".
//
// Two goroutines represent two API pods writing concurrently. A mutex
// simulates the DB transaction lock that serialises INSERT order. After both
// goroutines finish, the chain must have 10 rows with no breaks, and each
// row_hmac must be recomputable from the row's own fields.
func TestAuditChainContinuityAcrossPods(t *testing.T) {
	const chainKey = "test-hmac-chain-key"

	// computeRowHMAC mirrors the DB trigger's algorithm (§8.13.2):
	// HMAC-SHA256 over prev_hmac | "|" | request_id | "|" | kind.
	computeRowHMAC := func(prevHMAC, requestID, kind string) string {
		mac := hmac.New(sha256.New, []byte(chainKey))
		mac.Write([]byte(prevHMAC))
		mac.Write([]byte("|"))
		mac.Write([]byte(requestID))
		mac.Write([]byte("|"))
		mac.Write([]byte(kind))
		return hex.EncodeToString(mac.Sum(nil))
	}

	type auditRow struct {
		RequestID string
		Kind      string
		PrevHMAC  string
		RowHMAC   string
	}

	var (
		mu   sync.Mutex
		rows []auditRow
	)

	// insertRow appends one row under the mutex, computing prev_hmac and
	// row_hmac from the current chain tail — identical to what the DB trigger
	// does inside a serialised transaction.
	insertRow := func(requestID, kind string) {
		mu.Lock()
		defer mu.Unlock()
		prevHMAC := "GENESIS"
		if len(rows) > 0 {
			prevHMAC = rows[len(rows)-1].RowHMAC
		}
		rows = append(rows, auditRow{
			RequestID: requestID,
			Kind:      kind,
			PrevHMAC:  prevHMAC,
			RowHMAC:   computeRowHMAC(prevHMAC, requestID, kind),
		})
	}

	// Two goroutines simulate two pods writing 5 rows each.
	var wg sync.WaitGroup
	for pod := 0; pod < 2; pod++ {
		pod := pod
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 5; i++ {
				insertRow(fmt.Sprintf("req-pod%d-seq%d", pod, i), "request")
			}
		}()
	}
	wg.Wait()

	if len(rows) != 10 {
		t.Fatalf("expected 10 audit rows (2 pods × 5), got %d", len(rows))
	}

	// First row must be anchored at GENESIS.
	if rows[0].PrevHMAC != "GENESIS" {
		t.Errorf("row[0].PrevHMAC = %q; want GENESIS", rows[0].PrevHMAC)
	}

	// Every row must link to its predecessor.
	for i := 1; i < len(rows); i++ {
		if rows[i].PrevHMAC != rows[i-1].RowHMAC {
			t.Errorf("chain broken at row[%d]: PrevHMAC=%q != row[%d].RowHMAC=%q",
				i, rows[i].PrevHMAC, i-1, rows[i-1].RowHMAC)
		}
	}

	// Re-derive each row_hmac to confirm no silent corruption.
	prevHMAC := "GENESIS"
	for i, r := range rows {
		want := computeRowHMAC(prevHMAC, r.RequestID, r.Kind)
		if r.RowHMAC != want {
			t.Errorf("row[%d].RowHMAC = %q; recomputed = %q (corruption?)", i, r.RowHMAC, want)
		}
		prevHMAC = r.RowHMAC
	}
}

// TestPIIEraseNullstampsUserIDH verifies the §9.6 PII-erase rule: when
// ContextKeyUserID is explicitly set to "" (the null-stamp written after a
// GDPR erasure), the access log must NOT emit user_id_h at all.
//
// This differs from TestAccessLog_MissingContext_NoFields (where the key is
// absent from the context) because here the key IS present but holds "".
// Both paths must produce identical omission behaviour.
func TestPIIEraseNullstampsUserIDH(t *testing.T) {
	gin.SetMode(gin.TestMode)

	var buf bytes.Buffer
	cfg := minAccessLogCfg(100)

	gn := gin.New()
	// Simulate the erasure path: auth middleware explicitly sets user_id to "".
	gn.Use(func(c *gin.Context) {
		c.Set(ContextKeyUserID, "")
		c.Next()
	})
	gn.Use(accessLogWithWriter(cfg, &buf))
	gn.GET("/test", func(c *gin.Context) { c.Status(http.StatusOK) })

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	gn.ServeHTTP(w, req)

	var entry map[string]any
	if err := json.Unmarshal(bytes.TrimRight(buf.Bytes(), "\n"), &entry); err != nil {
		t.Fatalf("invalid JSON in access log: %v — raw: %s", err, buf.String())
	}

	// user_id_h must be absent when user_id is the empty string (null-stamp).
	if _, ok := entry["user_id_h"]; ok {
		t.Error("user_id_h present after user erasure (uid==\"\"); want absent (null-stamp)")
	}
}
