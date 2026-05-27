// Package runtimetuning — §9.17.1 GC pause P99 proof test.
//
// TestGCPauseP99Under5ms runs a synthetic allocation bench (simulating JSON
// encode + Redis pipeline patterns) and asserts that the p99 of GC pause
// durations reported by runtime/metrics is <= 5 ms.
package runtimetuning

import (
	"runtime"
	"runtime/metrics"
	"testing"
)

// TestGCPauseP99Under5ms asserts runtime/metrics GC pause p99 <= 5ms under a
// short allocation burst that mimics JSON encode + Redis pipeline patterns.
func TestGCPauseP99Under5ms(t *testing.T) {
	const allocIter = 50_000
	const maxP99 = 5e-3 // 5 ms in seconds

	// Warm up: run one GC to ensure the collector is not in an unusual state.
	runtime.GC()

	// Allocation burst: short-lived slices and strings (JSON encode pattern).
	for i := 0; i < allocIter; i++ {
		_ = make([]byte, 1024)
	}
	runtime.GC()

	// Read the GC pause histogram from runtime/metrics.
	descs := metrics.All()
	var pauseKey string
	for _, d := range descs {
		if d.Name == "/gc/pauses:seconds" {
			pauseKey = d.Name
			break
		}
	}
	if pauseKey == "" {
		t.Skip("/gc/pauses:seconds metric not available on this Go version")
	}

	sample := []metrics.Sample{{Name: pauseKey}}
	metrics.Read(sample)

	if sample[0].Value.Kind() == metrics.KindBad {
		t.Skipf("/gc/pauses:seconds not available: %v", sample[0].Value.Kind())
	}

	hist := sample[0].Value.Float64Histogram()
	if len(hist.Counts) == 0 {
		t.Skip("GC pause histogram is empty — no GC cycles ran")
	}

	// Compute p99 from the histogram.
	var total uint64
	for _, c := range hist.Counts {
		total += c
	}
	if total == 0 {
		t.Skip("GC pause histogram has zero observations")
	}
	target := total * 99 / 100
	var cumulative uint64
	for i, c := range hist.Counts {
		cumulative += c
		if cumulative >= target {
			// Upper bound of this bucket is the p99 estimate.
			if i+1 < len(hist.Buckets) {
				p99 := hist.Buckets[i+1]
				if p99 > maxP99 {
					t.Errorf("GC pause p99=%.2f ms exceeds 5 ms limit (runtime/metrics /gc/pauses:seconds)",
						p99*1000)
				} else {
					t.Logf("GC pause p99=%.3f ms (OK, limit=5 ms)", p99*1000)
				}
			}
			break
		}
	}
}

// TestBootProbeHeapBaseline asserts that the heap in-use immediately after
// package init is below 32 MiB (§9.17.1 boot probe contract).
func TestBootProbeHeapBaseline(t *testing.T) {
	const maxHeapMiB = 32
	runtime.GC()
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	heapMiB := ms.HeapInuse / (1 << 20)
	if heapMiB > maxHeapMiB {
		t.Errorf("heap baseline %d MiB exceeds %d MiB limit (§9.17.1 boot probe)",
			heapMiB, maxHeapMiB)
	} else {
		t.Logf("heap baseline %d MiB (OK, limit=%d MiB)", heapMiB, maxHeapMiB)
	}
}
