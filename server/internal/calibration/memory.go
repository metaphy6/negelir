package calibration

import "sync"

// InMemoryCalibrationStore is the default backend for Phase 9 (tests + CI).
// Phase 16 (Emitter) replaces this with a feed-plane backend via constructor
// injection at cmd/api/main.go — no handler code changes.
//
// Safe for concurrent use via RWMutex.
type InMemoryCalibrationStore struct {
	mu     sync.RWMutex
	latest map[storeKey]CalibrationTable
}

type storeKey struct{ profileID, market string }

// NewInMemoryCalibrationStore returns an initialised in-memory store.
func NewInMemoryCalibrationStore() *InMemoryCalibrationStore {
	return &InMemoryCalibrationStore{
		latest: make(map[storeKey]CalibrationTable),
	}
}

// Latest implements CalibrationStore.
// Returns a zero-version table (identity) when no table has been saved yet.
func (s *InMemoryCalibrationStore) Latest(profileID, market string) (CalibrationTable, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if t, ok := s.latest[storeKey{profileID, market}]; ok {
		return t, nil
	}
	return CalibrationTable{ProfileID: profileID, Market: market, Version: 0}, nil
}

// Upsert saves or replaces the calibration table for its (ProfileID, Market) key.
func (s *InMemoryCalibrationStore) Upsert(t CalibrationTable) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.latest[storeKey{t.ProfileID, t.Market}] = t
}
