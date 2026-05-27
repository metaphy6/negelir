// Package calibration defines the CalibrationStore Protocol seam.
//
// The Phase 9 default backend is in-memory (tests + CI); Phase 16 (Emitter)
// swaps in the feed-plane backend by providing a different CalibrationStore
// implementation — zero handler lines change.
//
// Dependency direction:
//
//	internal/handlers/predictions.go → internal/calibration (interface only)
//	internal/calibration/memory.go   → internal/calibration (concrete impl)
//
// internal/handlers/predictions.go MUST NEVER import internal/calibration
// concrete types (InMemoryCalibrationStore or any future backend).
// The handler receives a CalibrationStore via constructor injection;
// the wiring (concrete choice) lives in cmd/api/main.go.
package calibration

// CalibrationTable is an isotonic-regression snapshot for one
// (profile_id, market, version) triple.  Empty X/Y slices mean
// "no calibration learned yet" — callers treat the table as an
// identity function in that case.
type CalibrationTable struct {
	ProfileID string
	Market    string
	Version   int
	// Monotone non-decreasing pair: X[i] → Y[i].
	X []float64
	Y []float64
}

// CalibrationStore is the Phase 9 / Phase 16 seam.
//
//   - Phase 9  — in-memory backend (InMemoryCalibrationStore, cmd/api/main.go).
//   - Phase 16 — feed-plane backend replaces the constructor arg; 0 handler
//     lines change.
//
// Implementations MUST be safe for concurrent use.
type CalibrationStore interface {
	// Latest returns the most recent calibration table for the given
	// (profileID, market) pair.  If no table has been saved yet, Latest
	// returns a zero-version table (X/Y empty) so callers can treat the
	// result as an identity function rather than an error.
	Latest(profileID, market string) (CalibrationTable, error)
}
