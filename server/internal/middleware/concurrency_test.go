package middleware

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// TestConcurrencyLimit_WithinCap — sequential requests all pass (slots always
// available when requests run one at a time).
func TestConcurrencyLimit_WithinCap(t *testing.T) {
	r := gin.New()
	r.Use(ConcurrencyLimit(5))
	r.GET("/", func(c *gin.Context) { c.Status(http.StatusOK) })

	for i := 0; i < 5; i++ {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("request %d: expected 200, got %d", i+1, w.Code)
		}
	}
}

// TestConcurrencyLimit_Overflow — when cap slots are all occupied, the N+1th
// concurrent request gets HTTP 503 with X-Overflow: true immediately; after
// the handlers finish their slots are released and the next request succeeds.
func TestConcurrencyLimit_Overflow(t *testing.T) {
	const cap = 3

	gate := make(chan struct{})        // closed to unblock handlers
	inFlight := make(chan struct{}, cap) // each handler sends on entry

	r := gin.New()
	r.Use(ConcurrencyLimit(cap))
	r.GET("/slow", func(c *gin.Context) {
		inFlight <- struct{}{}
		<-gate
		c.Status(http.StatusOK)
	})

	ts := httptest.NewServer(r)
	defer ts.Close()

	// Start cap goroutines that each occupy one semaphore slot.
	var wg sync.WaitGroup
	for i := 0; i < cap; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			resp, err := http.Get(ts.URL + "/slow")
			if err == nil {
				resp.Body.Close()
			}
		}()
	}

	// Wait until every slot is occupied.
	for i := 0; i < cap; i++ {
		select {
		case <-inFlight:
		case <-time.After(2 * time.Second):
			close(gate)
			t.Fatal("timed out waiting for in-flight handlers")
		}
	}

	// N+1th request must be shed immediately.
	resp, err := http.Get(ts.URL + "/slow")
	if err != nil {
		close(gate)
		t.Fatalf("overflow request: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusServiceUnavailable {
		close(gate)
		t.Fatalf("overflow: expected 503, got %d", resp.StatusCode)
	}
	if got := resp.Header.Get("X-Overflow"); got != "true" {
		close(gate)
		t.Fatalf("X-Overflow header: expected \"true\", got %q", got)
	}

	// Release all blocked handlers; semaphore slots are freed.
	close(gate)
	wg.Wait()

	// After release a new request must succeed.
	resp2, err := http.Get(ts.URL + "/slow")
	if err != nil {
		t.Fatalf("post-release request: %v", err)
	}
	defer resp2.Body.Close()
	if resp2.StatusCode != http.StatusOK {
		t.Fatalf("post-release: expected 200, got %d", resp2.StatusCode)
	}
}

// TestConcurrencyLimit_SlotReleasedAfterHandler — a single slot is released
// exactly when the handler returns, allowing the next request to proceed.
func TestConcurrencyLimit_SlotReleasedAfterHandler(t *testing.T) {
	gate := make(chan struct{})
	inFlight := make(chan struct{}, 1)

	r := gin.New()
	r.Use(ConcurrencyLimit(1))
	r.GET("/", func(c *gin.Context) {
		inFlight <- struct{}{}
		<-gate
		c.Status(http.StatusOK)
	})

	ts := httptest.NewServer(r)
	defer ts.Close()

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		resp, err := http.Get(ts.URL + "/")
		if err == nil {
			resp.Body.Close()
		}
	}()

	// Wait until the single slot is occupied.
	select {
	case <-inFlight:
	case <-time.After(2 * time.Second):
		close(gate)
		t.Fatal("timed out waiting for in-flight handler")
	}

	// While the slot is held, a second request must get 503.
	resp, err := http.Get(ts.URL + "/")
	if err != nil {
		close(gate)
		t.Fatalf("while-held request: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusServiceUnavailable {
		close(gate)
		t.Fatalf("while slot held: expected 503, got %d", resp.StatusCode)
	}

	// Release the slot.
	close(gate)
	wg.Wait()

	// The slot is now free — a fresh request succeeds.
	resp2, err := http.Get(ts.URL + "/")
	if err != nil {
		t.Fatalf("post-release request: %v", err)
	}
	defer resp2.Body.Close()
	if resp2.StatusCode != http.StatusOK {
		t.Fatalf("after release: expected 200, got %d", resp2.StatusCode)
	}
}

// TestConcurrencyLimit_Zero_Disabled — maxRequests=0 disables the cap;
// all requests pass through unconditionally.
func TestConcurrencyLimit_Zero_Disabled(t *testing.T) {
	r := gin.New()
	r.Use(ConcurrencyLimit(0))
	r.GET("/", func(c *gin.Context) { c.Status(http.StatusOK) })

	for i := 0; i < 10; i++ {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("request %d with cap=0: expected 200, got %d", i+1, w.Code)
		}
	}
}
