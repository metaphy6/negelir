package cursor

import (
	"encoding/base64"
	"errors"
	"sort"
	"testing"
	"time"
)

func testKey() []byte {
	return []byte("negelir-cursor-seal-key-32bytes!")
}

func basePayload(ttlSec int64) Payload {
	now := time.Now().Unix()
	return Payload{
		Table:           "matches",
		LastPK:          "42",
		QueryFilterHash: "abc123",
		ExpiresAtUnix:   now + ttlSec,
	}
}

// TestCursorRoundTrip — sanity: seal+unseal with same key and matching filter.
func TestCursorRoundTrip(t *testing.T) {
	key := testKey()
	p := basePayload(1800)
	encoded, err := Seal(key, p)
	if err != nil {
		t.Fatalf("Seal: %v", err)
	}
	got, err := Unseal(key, encoded, time.Now().Unix(), p.QueryFilterHash)
	if err != nil {
		t.Fatalf("Unseal: %v", err)
	}
	if got.LastPK != p.LastPK {
		t.Errorf("LastPK: got %q, want %q", got.LastPK, p.LastPK)
	}
}

// TestCursorTamperedByte — proof test (a): any tampered byte -> ErrInvalidCursor.
func TestCursorTamperedByte(t *testing.T) {
	key := testKey()
	p := basePayload(1800)
	encoded, err := Seal(key, p)
	if err != nil {
		t.Fatalf("Seal: %v", err)
	}
	raw, _ := base64.RawURLEncoding.DecodeString(encoded)
	for i := 0; i < len(raw); i++ {
		mangled := make([]byte, len(raw))
		copy(mangled, raw)
		mangled[i] ^= 0xFF
		bad := base64.RawURLEncoding.EncodeToString(mangled)
		_, got := Unseal(key, bad, time.Now().Unix(), p.QueryFilterHash)
		if got == nil || !errors.Is(got, ErrInvalidCursor) {
			t.Errorf("byte[%d] tampered: got %v, want ErrInvalidCursor", i, got)
		}
	}
}

// TestCursorExpired — proof test (b): expired cursor -> ErrInvalidCursor.
func TestCursorExpired(t *testing.T) {
	key := testKey()
	p := basePayload(-1)
	encoded, err := Seal(key, p)
	if err != nil {
		t.Fatalf("Seal: %v", err)
	}
	_, err = Unseal(key, encoded, time.Now().Unix(), p.QueryFilterHash)
	if !errors.Is(err, ErrInvalidCursor) {
		t.Errorf("expired cursor: got %v, want ErrInvalidCursor", err)
	}
}

// TestCursorFilterDrift — proof test (c): different filter hash -> ErrFilterDrift.
func TestCursorFilterDrift(t *testing.T) {
	key := testKey()
	p := basePayload(1800)
	encoded, err := Seal(key, p)
	if err != nil {
		t.Fatalf("Seal: %v", err)
	}
	_, err = Unseal(key, encoded, time.Now().Unix(), "different-filter-hash")
	if !errors.Is(err, ErrFilterDrift) {
		t.Errorf("filter drift: got %v, want ErrFilterDrift", err)
	}
}

// TestCursorRotatedKey — proof test (d): cursor sealed with old key -> ErrInvalidCursor, NOT panic.
func TestCursorRotatedKey(t *testing.T) {
	oldKey := []byte("old-cursor-rotate-test-key32byte")
	newKey := testKey()
	p := basePayload(1800)
	encoded, err := Seal(oldKey, p)
	if err != nil {
		t.Fatalf("Seal with old key: %v", err)
	}
	_, err = Unseal(newKey, encoded, time.Now().Unix(), p.QueryFilterHash)
	if !errors.Is(err, ErrInvalidCursor) {
		t.Errorf("rotated key: got %v, want ErrInvalidCursor", err)
	}
}

// ---------------------------------------------------------------------------
// §9.14 adversarial proof test
// ---------------------------------------------------------------------------

// TestAdvCursorOracleAttack — adv_test_cursor_oracle_attack.
//
// Submits malformed cursors at high rate (500 tampered cursors cycling through
// every byte position) and asserts:
//
//  1. All malformed cursors return ErrInvalidCursor — no panic, no nil error.
//  2. No timing oracle: the median latency for cursors that fail at byte 0
//     vs the last byte must not differ by more than 50×. AES-256-GCM's Open()
//     runs a constant-time GHASH + CTR decrypt regardless of which bytes are
//     tampered; the 50× bound is generous to tolerate OS scheduling noise while
//     catching any pathological early-exit path.
//
// The timing section is skipped under -short.
func TestAdvCursorOracleAttack(t *testing.T) {
	key := testKey()
	p := basePayload(1800)
	encoded, err := Seal(key, p)
	if err != nil {
		t.Fatalf("Seal: %v", err)
	}
	raw, _ := base64.RawURLEncoding.DecodeString(encoded)

	// -- Part 1: correctness at high rate ------------------------------------
	// Cycle through every byte position 500 times.  Every tampered cursor
	// must return ErrInvalidCursor (AES-GCM tag verification always fails on
	// any single-bit difference in nonce, ciphertext, or tag bytes).
	const batchSize = 500
	for i := 0; i < batchSize; i++ {
		pos := i % len(raw)
		mangled := make([]byte, len(raw))
		copy(mangled, raw)
		mangled[pos] ^= 0xFF
		bad := base64.RawURLEncoding.EncodeToString(mangled)
		_, gotErr := Unseal(key, bad, time.Now().Unix(), p.QueryFilterHash)
		if !errors.Is(gotErr, ErrInvalidCursor) {
			t.Fatalf("high-rate i=%d pos=%d: expected ErrInvalidCursor, got %v", i, pos, gotErr)
		}
	}

	// -- Part 2: timing oracle check ----------------------------------------
	if testing.Short() {
		t.Skip("adv: timing oracle check skipped in -short mode")
	}

	const reps = 200

	// Early-failure cursor: tamper byte 0 (corrupts nonce bytes → gcm.Open
	// authentication fails after processing the entire ciphertext+tag).
	earlyMangled := make([]byte, len(raw))
	copy(earlyMangled, raw)
	earlyMangled[0] ^= 0xFF
	badEarly := base64.RawURLEncoding.EncodeToString(earlyMangled)

	// Late-failure cursor: tamper last byte (corrupts last tag byte → same
	// code path through gcm.Open, same constant-time authentication).
	lateMangled := make([]byte, len(raw))
	copy(lateMangled, raw)
	lateMangled[len(lateMangled)-1] ^= 0xFF
	badLate := base64.RawURLEncoding.EncodeToString(lateMangled)

	earlyNs := make([]int64, reps)
	lateNs := make([]int64, reps)

	for i := 0; i < reps; i++ {
		start := time.Now()
		Unseal(key, badEarly, time.Now().Unix(), p.QueryFilterHash) //nolint:errcheck
		earlyNs[i] = time.Since(start).Nanoseconds()

		start = time.Now()
		Unseal(key, badLate, time.Now().Unix(), p.QueryFilterHash) //nolint:errcheck
		lateNs[i] = time.Since(start).Nanoseconds()
	}

	// Use medians — more robust than means against OS scheduling outliers.
	sort.Slice(earlyNs, func(i, j int) bool { return earlyNs[i] < earlyNs[j] })
	sort.Slice(lateNs, func(i, j int) bool { return lateNs[i] < lateNs[j] })
	earlyMed := earlyNs[reps/2]
	lateMed := lateNs[reps/2]

	// Guard against zero (sub-nanosecond resolution on some VMs).
	if earlyMed < 1 {
		earlyMed = 1
	}
	if lateMed < 1 {
		lateMed = 1
	}

	var ratio float64
	if lateMed > earlyMed {
		ratio = float64(lateMed) / float64(earlyMed)
	} else {
		ratio = float64(earlyMed) / float64(lateMed)
	}

	// AES-GCM is constant-time: ratio should be ~1×; 50× catches a broken
	// early-exit path while tolerating worst-case OS scheduling jitter.
	if ratio > 50.0 {
		t.Errorf("adv: timing oracle detected — earlyMed=%dns lateMed=%dns ratio=%.1f (threshold 50×); "+
			"AES-GCM Open() must be constant-time regardless of byte-position tampered",
			earlyMed, lateMed, ratio)
	}
	t.Logf("adv cursor timing: earlyMed=%dns lateMed=%dns ratio=%.2f", earlyMed, lateMed, ratio)
}
