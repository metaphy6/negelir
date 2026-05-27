// Package audit implements the Phase 9 §9.17.7 audit pipeline performance
// layer for api.request.v1 + api.response.v1.
//
// The Writer:
//   - Accepts rows via a bounded channel (cap=cfg.APIAuditChanCap, default 4096).
//   - A background goroutine drains the channel and publishes to a Backend
//     in batches of up to cfg.APIAuditBatchMax rows or cfg.APIAuditBatchMaxMs,
//     whichever fires first.
//   - NEVER blocks the response: Submit is non-blocking; a full channel drops
//     the row and emits a debounced sec.alert.v1{kind=api_audit_dropped,
//     severity=warn} (debounce 60 s).
//   - Backpressure sampling: when the channel is >80% full for >5s, 2xx rows
//     are sampled at cfg.APIAuditSamplePctUnderPressure (default 10%). 4xx/5xx
//     and sec-relevant events are always 100%. Sampling is restored when the
//     channel drops below 50% for 30s.
//   - Integrity-break quarantine: when NotifyIntegrityBreak() is called, all
//     subsequent rows are routed to the quarantine Backend instead of the normal
//     Backend until the operator runs make audit.repair-api and restarts the pod.
package audit

import (
	"context"
	"math/rand"
	"sync"
	"sync/atomic"
	"time"
)

// Row is one api.request.v1 or api.response.v1 audit event.
type Row struct {
	// Kind is "request" or "response" - determines the bus topic.
	Kind          string
	RequestID     string
	Method        string
	Path          string
	StatusCode    int
	LatencyMs     int64
	ResponseBytes int
	CacheHit      bool
	Degraded      bool
	UserID        string // empty for anonymous
	ClientIP      string
	Payload       map[string]any
	ProducedAt    time.Time
	// SecRelevant marks login attempts, revocations, and other security events
	// that bypass sampling and are always written at 100%.
	SecRelevant bool
}

// Backend is the publish/write target for a batch of audit rows.
// Two backends are wired at construction time:
//   - normal     - publishes to the Redis bus streams (api.request.v1 / api.response.v1).
//   - quarantine - writes directly to api_audit_log_quarantine (PG) after an integrity break.
type Backend interface {
	Flush(ctx context.Context, rows []Row) error
}

// AlertFunc is the sec.alert.v1 emission callback injected from cmd/api.
// kind is "api_audit_dropped"; severity is "warn".
type AlertFunc func(ctx context.Context, kind, severity string)

const (
	kindAuditDropped = "api_audit_dropped"

	// Channel-fill thresholds (section 9.17.7).
	pressureHighPct = 0.80
	pressureLowPct  = 0.50

	// Time gates (section 9.17.7).
	pressureEnterDuration = 5 * time.Second
	pressureExitDuration  = 30 * time.Second

	// Drop-alert debounce (section 9.17.7).
	dropAlertDebounce = 60 * time.Second
)

// WriterConfig holds the section 9.17.7 tunable knobs.
type WriterConfig struct {
	BatchMax               int
	BatchMaxDuration       time.Duration
	ChanCap                int
	SamplePctUnderPressure int
}

// Writer is the audit pipeline entry point.
type Writer struct {
	cfg        WriterConfig
	normal     Backend
	quarantine Backend
	alertFn    AlertFunc

	ch chan Row

	// quarantine mode flag: set atomically when NotifyIntegrityBreak() is called.
	inQuarantine atomic.Bool

	// backpressure state (accessed only by the fill-monitor goroutine).
	pressureStart  time.Time
	calmStart      time.Time
	underPressureF bool // underPressure field (prefixed to avoid shadowing method)

	// drop-alert debounce: guarded by mu.
	mu            sync.Mutex
	lastDropAlert time.Time

	stopOnce sync.Once
	stopCh   chan struct{}
	wg       sync.WaitGroup
}

// New constructs a Writer and starts its background goroutines.
// normal is the Redis-pipeline backend for normal operation.
// quarantine is the PG quarantine backend used after an integrity break.
// alertFn may be nil (disables sec.alert.v1 emission).
func New(cfg WriterConfig, normal, quarantine Backend, alertFn AlertFunc) *Writer {
	if cfg.BatchMax <= 0 {
		cfg.BatchMax = 64
	}
	if cfg.BatchMaxDuration <= 0 {
		cfg.BatchMaxDuration = 10 * time.Millisecond
	}
	if cfg.ChanCap <= 0 {
		cfg.ChanCap = 4096
	}
	if cfg.SamplePctUnderPressure <= 0 {
		cfg.SamplePctUnderPressure = 10
	}
	w := &Writer{
		cfg:        cfg,
		normal:     normal,
		quarantine: quarantine,
		alertFn:    alertFn,
		ch:         make(chan Row, cfg.ChanCap),
		stopCh:     make(chan struct{}),
	}
	w.wg.Add(2)
	go w.shipper()
	go w.fillMonitor()
	return w
}

// Submit enqueues row for async publish. Non-blocking: if the channel is full
// the row is dropped and a debounced sec.alert is emitted.
// 4xx/5xx and SecRelevant rows bypass sampling regardless of pressure state.
func (w *Writer) Submit(row Row) bool {
	// 4xx / 5xx and sec-relevant rows always bypass sampling.
	if row.StatusCode >= 400 || row.SecRelevant {
		return w.enqueue(row)
	}
	// Under-pressure sampling for 2xx.
	if w.underPressureF {
		pct := w.cfg.SamplePctUnderPressure
		if pct <= 0 || rand.Intn(100) >= pct {
			return true // sampled out; not a drop
		}
	}
	return w.enqueue(row)
}

func (w *Writer) enqueue(row Row) bool {
	select {
	case w.ch <- row:
		return true
	default:
		w.onDrop()
		return false
	}
}

func (w *Writer) onDrop() {
	if w.alertFn == nil {
		return
	}
	now := time.Now()
	w.mu.Lock()
	elapsed := now.Sub(w.lastDropAlert)
	if elapsed < dropAlertDebounce {
		w.mu.Unlock()
		return
	}
	w.lastDropAlert = now
	w.mu.Unlock()
	w.alertFn(context.Background(), kindAuditDropped, "warn")
}

// NotifyIntegrityBreak switches the Writer to quarantine mode permanently
// (until pod restart + operator make audit.repair-api).
func (w *Writer) NotifyIntegrityBreak() {
	w.inQuarantine.Store(true)
}

// IsInQuarantine reports whether the Writer is in quarantine mode.
func (w *Writer) IsInQuarantine() bool {
	return w.inQuarantine.Load()
}

// UnderPressure reports whether 2xx sampling is currently active.
func (w *Writer) UnderPressure() bool {
	return w.underPressureF
}

// Stop drains the channel and shuts down background goroutines.
func (w *Writer) Stop() {
	w.stopOnce.Do(func() {
		close(w.stopCh)
	})
	w.wg.Wait()
}

func (w *Writer) activeBackend() Backend {
	if w.inQuarantine.Load() {
		return w.quarantine
	}
	return w.normal
}

// shipper is the background goroutine that drains w.ch in batches.
func (w *Writer) shipper() {
	defer w.wg.Done()
	batch := make([]Row, 0, w.cfg.BatchMax)
	ticker := time.NewTicker(w.cfg.BatchMaxDuration)
	defer ticker.Stop()

	flush := func() {
		if len(batch) == 0 {
			return
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		_ = w.activeBackend().Flush(ctx, batch)
		cancel()
		batch = batch[:0]
	}

	for {
		select {
		case row, ok := <-w.ch:
			if !ok {
				flush()
				return
			}
			batch = append(batch, row)
			if len(batch) >= w.cfg.BatchMax {
				flush()
			}
		case <-ticker.C:
			flush()
		case <-w.stopCh:
			// Drain remaining rows.
		drainLoop:
			for {
				select {
				case row := <-w.ch:
					batch = append(batch, row)
					if len(batch) >= w.cfg.BatchMax {
						flush()
					}
				default:
					break drainLoop
				}
			}
			flush()
			return
		}
	}
}

// fillMonitor samples the channel fill ratio and manages the backpressure
// state machine (section 9.17.7).
func (w *Writer) fillMonitor() {
	defer w.wg.Done()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			w.updatePressure(time.Now())
		case <-w.stopCh:
			return
		}
	}
}

// updatePressure implements the section 9.17.7 backpressure state machine.
// Called only from fillMonitor goroutine.
func (w *Writer) updatePressure(now time.Time) {
	fill := float64(len(w.ch)) / float64(w.cfg.ChanCap)

	if !w.underPressureF {
		if fill > pressureHighPct {
			if w.pressureStart.IsZero() {
				w.pressureStart = now
			} else if now.Sub(w.pressureStart) >= pressureEnterDuration {
				w.underPressureF = true
				w.pressureStart = time.Time{}
				w.calmStart = time.Time{}
			}
		} else {
			w.pressureStart = time.Time{}
		}
	} else {
		if fill < pressureLowPct {
			if w.calmStart.IsZero() {
				w.calmStart = now
			} else if now.Sub(w.calmStart) >= pressureExitDuration {
				w.underPressureF = false
				w.calmStart = time.Time{}
				w.pressureStart = time.Time{}
			}
		} else {
			w.calmStart = time.Time{}
		}
	}
}
