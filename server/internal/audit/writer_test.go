package audit

import (
	"context"
	"sync"
	"testing"
	"time"
)

// --- test helpers ---

type captureBackend struct {
	mu   sync.Mutex
	rows []Row
	err  error
}

func (b *captureBackend) Flush(_ context.Context, rows []Row) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	batch := make([]Row, len(rows))
	copy(batch, rows)
	b.rows = append(b.rows, batch...)
	return b.err
}

func (b *captureBackend) Rows() []Row {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make([]Row, len(b.rows))
	copy(out, b.rows)
	return out
}

func (b *captureBackend) Len() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.rows)
}

func smallCfg(batchMax int, batchDur time.Duration, chanCap int) WriterConfig {
	return WriterConfig{
		BatchMax:               batchMax,
		BatchMaxDuration:       batchDur,
		ChanCap:                chanCap,
		SamplePctUnderPressure: 10,
	}
}

func makeRow(status int) Row {
	return Row{
		Kind:       "response",
		RequestID:  "req-1",
		Method:     "GET",
		Path:       "/v1/predict",
		StatusCode: status,
		ProducedAt: time.Now(),
	}
}

// --- tests ---

// TestBatchFiresOnMaxRows verifies that the shipper flushes immediately
// when cfg.BatchMax rows have accumulated (section 9.17.7 bullet a).
func TestBatchFiresOnMaxRows(t *testing.T) {
	normal := &captureBackend{}
	quar := &captureBackend{}
	cfg := smallCfg(4, 500*time.Millisecond, 64)
	w := New(cfg, normal, quar, nil)
	defer w.Stop()

	for i := 0; i < 4; i++ {
		w.Submit(makeRow(200))
	}

	// The batch fires synchronously when len(batch) >= BatchMax.
	// Give shipper a brief moment to execute the flush.
	deadline := time.Now().Add(200 * time.Millisecond)
	for time.Now().Before(deadline) {
		if normal.Len() == 4 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if got := normal.Len(); got != 4 {
		t.Fatalf("expected 4 rows flushed on batch-max; got %d", got)
	}
}

// TestBatchFiresOnTimeout verifies that the shipper flushes after
// cfg.BatchMaxDuration even when the batch is not full (section 9.17.7 bullet a).
func TestBatchFiresOnTimeout(t *testing.T) {
	normal := &captureBackend{}
	quar := &captureBackend{}
	cfg := smallCfg(64, 20*time.Millisecond, 256)
	w := New(cfg, normal, quar, nil)
	defer w.Stop()

	w.Submit(makeRow(200))
	w.Submit(makeRow(200))

	// Wait for at least one timer tick plus margin.
	deadline := time.Now().Add(200 * time.Millisecond)
	for time.Now().Before(deadline) {
		if normal.Len() == 2 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if got := normal.Len(); got != 2 {
		t.Fatalf("expected 2 rows flushed after timeout; got %d", got)
	}
}

// TestChannelFullDropsAndDebounces verifies that a completely full channel
// drops rows and emits a sec.alert with 60-second debounce (section 9.17.7).
func TestChannelFullDropsAndDebounces(t *testing.T) {
	// Very small channel so we can fill it easily.
	normal := &captureBackend{}
	quar := &captureBackend{}

	var alertCalls []string
	var alertMu sync.Mutex
	alertFn := func(_ context.Context, kind, _ string) {
		alertMu.Lock()
		alertCalls = append(alertCalls, kind)
		alertMu.Unlock()
	}

	// chanCap=2, batchMaxDuration very long so shipper does not drain quickly.
	cfg := smallCfg(64, 10*time.Second, 2)
	w := New(cfg, normal, quar, alertFn)
	defer w.Stop()

	// Fill the channel completely.
	w.enqueue(makeRow(200))
	w.enqueue(makeRow(200))

	// Third submit must drop and trigger alert.
	okA := w.Submit(makeRow(200))
	time.Sleep(10 * time.Millisecond)

	alertMu.Lock()
	n := len(alertCalls)
	alertMu.Unlock()

	if okA {
		t.Fatal("expected Submit to return false (drop) when channel full")
	}
	if n == 0 {
		t.Fatal("expected sec.alert to be emitted on drop")
	}

	// Immediate second drop must be debounced (no second alert within 60s).
	w.Submit(makeRow(200))
	time.Sleep(10 * time.Millisecond)
	alertMu.Lock()
	n2 := len(alertCalls)
	alertMu.Unlock()
	if n2 > n {
		t.Fatalf("expected debounce to suppress second alert; got %d total alerts", n2)
	}
}

// TestBackpressureSamples2xxUnderPressure verifies that 2xx rows are sampled
// at cfg.SamplePctUnderPressure=10 once underPressureF is set (section 9.17.7).
func TestBackpressureSamples2xxUnderPressure(t *testing.T) {
	normal := &captureBackend{}
	quar := &captureBackend{}
	cfg := WriterConfig{
		BatchMax:               512,
		BatchMaxDuration:       20 * time.Millisecond,
		ChanCap:                512,
		SamplePctUnderPressure: 10, // 10% pass-through
	}
	w := New(cfg, normal, quar, nil)
	defer w.Stop()

	// Force pressure state directly (bypasses the 5s gate in unit tests).
	w.underPressureF = true

	const tries = 1000
	for i := 0; i < tries; i++ {
		w.Submit(makeRow(200))
	}

	// Wait for the shipper to flush.
	deadline := time.Now().Add(300 * time.Millisecond)
	for time.Now().Before(deadline) {
		if normal.Len() > 0 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	// Allow a full extra batch window for any stragglers.
	time.Sleep(50 * time.Millisecond)

	// With 10% pass-through, expect roughly 100 in 1000; allow 30-170 for noise.
	got := normal.Len()
	if got < 30 || got > 170 {
		t.Fatalf("expected ~10%% of 2xx rows flushed under pressure (30-170); got %d/%d", got, tries)
	}
}

// TestBackpressureAlwaysPass4xx verifies that 4xx rows bypass sampling
// regardless of pressure state (section 9.17.7).
func TestBackpressureAlwaysPass4xx(t *testing.T) {
	normal := &captureBackend{}
	quar := &captureBackend{}
	cfg := WriterConfig{
		BatchMax:               256,
		BatchMaxDuration:       10 * time.Millisecond,
		ChanCap:                256,
		SamplePctUnderPressure: 10,
	}
	w := New(cfg, normal, quar, nil)
	defer w.Stop()

	w.underPressureF = true

	const tries = 100
	for i := 0; i < tries; i++ {
		if !w.Submit(makeRow(404)) {
			t.Fatalf("4xx row dropped under pressure; should always pass")
		}
	}
}

// TestBackpressureRestores verifies the state machine transitions back to
// normal when channel fill drops below 50% for 30s (section 9.17.7 bullet b).
// This test uses updatePressure directly to avoid wall-clock delays.
func TestBackpressureRestores(t *testing.T) {
	normal := &captureBackend{}
	quar := &captureBackend{}
	cfg := smallCfg(64, 10*time.Millisecond, 100)
	w := New(cfg, normal, quar, nil)
	defer w.Stop()

	// Simulate already under pressure.
	w.underPressureF = true

	// Channel is empty -> fill=0 < 50%. Simulate calmStart 31s ago.
	past := time.Now().Add(-31 * time.Second)
	w.calmStart = past
	w.updatePressure(time.Now())

	if w.UnderPressure() {
		t.Fatal("expected pressure to be released after 30s below 50% fill")
	}
}

// TestBackpressureEntersAfter5s verifies the state machine transitions to
// pressure state when channel fill exceeds 80% for 5s.
func TestBackpressureEntersAfter5s(t *testing.T) {
	normal := &captureBackend{}
	quar := &captureBackend{}
	// chanCap=10 so we can control fill precisely.
	cfg := smallCfg(64, 10*time.Millisecond, 10)
	w := New(cfg, normal, quar, nil)
	defer w.Stop()

	// Fill 9/10 = 90% > 80%.
	for i := 0; i < 9; i++ {
		w.ch <- makeRow(200)
	}

	// Simulate pressureStart 6s ago.
	w.pressureStart = time.Now().Add(-6 * time.Second)
	w.updatePressure(time.Now())

	if !w.UnderPressure() {
		t.Fatal("expected pressure to be entered after 5s above 80% fill")
	}
}

// TestQuarantineModeRoutesToQuarantineBackend verifies that after
// NotifyIntegrityBreak, rows go to the quarantine backend (section 9.17.7 bullet c).
func TestQuarantineModeRoutesToQuarantineBackend(t *testing.T) {
	normal := &captureBackend{}
	quar := &captureBackend{}
	cfg := smallCfg(4, 20*time.Millisecond, 64)
	w := New(cfg, normal, quar, nil)
	defer w.Stop()

	w.NotifyIntegrityBreak()

	for i := 0; i < 4; i++ {
		w.Submit(makeRow(200))
	}

	deadline := time.Now().Add(300 * time.Millisecond)
	for time.Now().Before(deadline) {
		if quar.Len() >= 4 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if quar.Len() == 0 {
		t.Fatal("expected rows routed to quarantine backend after NotifyIntegrityBreak")
	}
	if normal.Len() != 0 {
		t.Fatalf("expected no rows in normal backend after quarantine; got %d", normal.Len())
	}
	if !w.IsInQuarantine() {
		t.Fatal("expected IsInQuarantine() to return true")
	}
}
