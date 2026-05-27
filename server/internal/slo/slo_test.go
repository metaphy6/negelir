package slo_test

import (
	"context"
	"testing"

	"github.com/metaphy6/negelir/server/internal/slo"
)

// -- helpers -----------------------------------------------------------------

func noAlert(t *testing.T) slo.AlertFunc {
	t.Helper()
	return func(_ context.Context, _, severity string) {
		t.Errorf("unexpected alert: severity=%s", severity)
	}
}

func captureAlerts() (slo.AlertFunc, *[]string, *[]string) {
	var kinds, severities []string
	fn := func(_ context.Context, kind, severity string) {
		kinds = append(kinds, kind)
		severities = append(severities, severity)
	}
	return fn, &kinds, &severities
}

// alwaysOK returns a RateFunc that always reports the given error fraction.
func alwaysOK(fraction float64) slo.RateFunc {
	return func(_ int) (float64, bool) { return fraction, true }
}

// neverOK returns a RateFunc that always signals insufficient data.
func neverOK() slo.RateFunc {
	return func(_ int) (float64, bool) { return 0, false }
}

// -- tests -------------------------------------------------------------------

// TestCheckBurnRate_BelowThreshold: error rate well below budget (0.1x) -> no alert.
func TestCheckBurnRate_BelowThreshold(t *testing.T) {
	// error fraction 0.0005 -> burn = 0.0005/0.005 = 0.1 (< threshold 2.0)
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, alwaysOK(0.0005), noAlert(t))
}

// TestCheckBurnRate_WarnThreshold: burn rate between threshold and 3x -> warn.
func TestCheckBurnRate_WarnThreshold(t *testing.T) {
	// error fraction 0.012 -> burn = 0.012/0.005 = 2.4 (> 2.0, < 6.0) -> warn
	alertFn, _, severities := captureAlerts()
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, alwaysOK(0.012), alertFn)
	if len(*severities) != 1 || (*severities)[0] != "warn" {
		t.Fatalf("expected [warn], got %v", *severities)
	}
}

// TestCheckBurnRate_CriticalThreshold: burn rate > 3x threshold -> critical.
func TestCheckBurnRate_CriticalThreshold(t *testing.T) {
	// error fraction 0.040 -> burn = 0.040/0.005 = 8.0 (> 6.0) -> critical
	alertFn, _, severities := captureAlerts()
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, alwaysOK(0.040), alertFn)
	if len(*severities) != 1 || (*severities)[0] != "critical" {
		t.Fatalf("expected [critical], got %v", *severities)
	}
}

// TestCheckBurnRate_InsufficientData: ok==false for both windows -> no alert.
func TestCheckBurnRate_InsufficientData(t *testing.T) {
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, neverOK(), noAlert(t))
}

// TestCheckBurnRate_OnlyShortWindowExceedsThreshold: spike in short window -> warn.
func TestCheckBurnRate_OnlyShortWindowExceedsThreshold(t *testing.T) {
	// short window: fraction 0.012 -> burn 2.4 -> warn
	// long window:  fraction 0.001 -> burn 0.2 -> no alert on its own
	rateFn := func(windowS int) (float64, bool) {
		if windowS == 300 {
			return 0.012, true
		}
		return 0.001, true
	}
	alertFn, _, severities := captureAlerts()
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, rateFn, alertFn)
	if len(*severities) != 1 || (*severities)[0] != "warn" {
		t.Fatalf("expected [warn] from short-window spike, got %v", *severities)
	}
}

// TestCheckBurnRate_LongWindowDrivesCritical: long window worst -> critical.
func TestCheckBurnRate_LongWindowDrivesCritical(t *testing.T) {
	// long window: fraction 0.040 -> burn 8.0 -> critical
	// short window: fraction 0.012 -> burn 2.4 -> would be warn alone
	rateFn := func(windowS int) (float64, bool) {
		if windowS == 3600 {
			return 0.040, true
		}
		return 0.012, true
	}
	alertFn, _, severities := captureAlerts()
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, rateFn, alertFn)
	if len(*severities) != 1 || (*severities)[0] != "critical" {
		t.Fatalf("expected [critical] driven by long window, got %v", *severities)
	}
}

// TestCheckBurnRate_KindIsAPISLOBurn: kind label is always "api_slo_burn".
func TestCheckBurnRate_KindIsAPISLOBurn(t *testing.T) {
	// error fraction 0.012 -> burn 2.4 -> warn
	alertFn, kinds, _ := captureAlerts()
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, alwaysOK(0.012), alertFn)
	if len(*kinds) != 1 || (*kinds)[0] != "api_slo_burn" {
		t.Fatalf("expected kind=api_slo_burn, got %v", *kinds)
	}
}

// TestCheckBurnRate_AtExactThresholdNoAlert: burn == threshold -> no alert (strictly >).
func TestCheckBurnRate_AtExactThresholdNoAlert(t *testing.T) {
	// burn = threshold exactly (2.0): must NOT fire
	// fraction = 0.005 * 2.0 / (slo.ErrorBudget/slo.ErrorBudget) ... let us
	// use fraction = slo.ErrorBudget * 2.0 = 0.01 -> burn = 2.0 exactly
	fraction := slo.ErrorBudget * 2.0 // burn == threshold, not >
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, alwaysOK(fraction), noAlert(t))
}

// TestCheckBurnRate_SingleFirePerCall: alertFn called at most once per call.
func TestCheckBurnRate_SingleFirePerCall(t *testing.T) {
	// Both windows in critical territory; alertFn must still be called once.
	alertFn, _, severities := captureAlerts()
	slo.CheckBurnRate(context.Background(), 300, 3600, 2.0, alwaysOK(0.040), alertFn)
	if len(*severities) != 1 {
		t.Fatalf("expected exactly 1 alert per call, got %d: %v", len(*severities), *severities)
	}
}

// TestBurnRateMonitor_StopsOnContextCancel: goroutine exits when ctx is done.
func TestBurnRateMonitor_StopsOnContextCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	// Use a long window so the ticker never fires; we only test clean shutdown.
	slo.BurnRateMonitor(ctx, 3600, 2.0, neverOK(), noAlert(t))
	cancel() // signal shutdown -- goroutine must return without blocking
	// No assertion beyond "no panic/hang"; test timeout enforces the latter.
}
