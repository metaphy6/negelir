package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

type stubShedderCfg struct{ floor int64 }

func (s *stubShedderCfg) PriorityTierFloor() int64 { return s.floor }

// ginContext returns a ready-to-use *gin.Context wired to a ResponseRecorder.
func ginContext(tierID int64) (*gin.Context, *httptest.ResponseRecorder) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request, _ = http.NewRequest(http.MethodGet, "/test", nil)
	if tierID != 0 {
		c.Set(ContextKeyTierID, tierID)
	}
	return c, w
}

// TestInflightShedder_DormantWhenFloorZero verifies the built-but-dormant
// behaviour: with floor=0 shedding never triggers even at 100% load.
func TestInflightShedder_DormantWhenFloorZero(t *testing.T) {
	t.Parallel()

	now := time.Unix(1_000_000, 0)
	cfg := &stubShedderCfg{floor: 0}
	s := newInflightShedder(10, cfg, nil, func() time.Time { return now })

	// Simulate 9 in-flight requests (90% of 10).
	for i := 0; i < 9; i++ {
		s.incr()
	}
	// Advance clock past the 5-second threshold.
	now = now.Add(10 * time.Second)

	// tier_id=1 with floor=0 → should never shed.
	if s.shouldShed(1) {
		t.Fatal("should not shed when floor==0")
	}
}

// TestInflightShedder_NoShedBelow5s verifies that shedding does not engage
// until 5 seconds of sustained pressure have elapsed.
func TestInflightShedder_NoShedBelow5s(t *testing.T) {
	t.Parallel()

	now := time.Unix(2_000_000, 0)
	cfg := &stubShedderCfg{floor: 5} // floor > any test tier
	s := newInflightShedder(10, cfg, nil, func() time.Time { return now })

	// 9 in-flight = 90%.
	for i := 0; i < 9; i++ {
		s.incr()
	}

	// First check — pressureStart is just now; timer hasn't elapsed.
	if s.shouldShed(1) {
		t.Fatal("should not shed: < 5 s of pressure")
	}

	// Advance only 3 s — still under the 5 s gate.
	now = now.Add(3 * time.Second)
	if s.shouldShed(1) {
		t.Fatal("should not shed: 3 s < 5 s")
	}
}

// TestInflightShedder_ShedsAfter5sAndLowTier verifies shedding engages when
// the ratio exceeds 0.85 for > 5 s and the tier is below the floor.
func TestInflightShedder_ShedsAfter5sAndLowTier(t *testing.T) {
	t.Parallel()

	now := time.Unix(3_000_000, 0)
	cfg := &stubShedderCfg{floor: 5} // tier_id 1-4 are shed; 5+ are not
	var alertFired bool
	alertFn := func(_ context.Context, _ string, _ string) { alertFired = true }
	s := newInflightShedder(10, cfg, alertFn, func() time.Time { return now })

	// 9/10 = 90% in-flight.
	for i := 0; i < 9; i++ {
		s.incr()
	}

	// Seed the pressureStart by calling shouldShed once.
	_ = s.shouldShed(1)

	// Advance past the 5-second gate.
	now = now.Add(6 * time.Second)

	// tier_id=1 is below floor=5 → should shed.
	if !s.shouldShed(1) {
		t.Fatal("should shed: >5 s pressure, tier below floor")
	}
	if !alertFired {
		t.Fatal("alert must fire when shedding")
	}
}

// TestInflightShedder_DoesNotShedHighTier verifies that high-tier requests
// are never shed even under sustained load.
func TestInflightShedder_DoesNotShedHighTier(t *testing.T) {
	t.Parallel()

	now := time.Unix(4_000_000, 0)
	cfg := &stubShedderCfg{floor: 3} // tier_id < 3 shed; 3+ are safe
	s := newInflightShedder(10, cfg, nil, func() time.Time { return now })

	for i := 0; i < 9; i++ {
		s.incr()
	}
	_ = s.shouldShed(5) // seed pressureStart
	now = now.Add(10 * time.Second)

	// tier_id=5 >= floor=3 → should NOT shed.
	if s.shouldShed(5) {
		t.Fatal("must not shed tier >= floor")
	}
}

// TestInflightPressureShed_Middleware_DormantPath is an end-to-end test that
// confirms the middleware passes requests through when shedding is dormant
// (floor=0 default) regardless of load.
func TestInflightPressureShed_Middleware_DormantPath(t *testing.T) {
	t.Parallel()

	now := time.Unix(5_000_000, 0)
	cfg := &stubShedderCfg{floor: 0}
	s := newInflightShedder(10, cfg, nil, func() time.Time { return now })
	for i := 0; i < 9; i++ {
		s.incr()
	}
	now = now.Add(10 * time.Second) // past 5s gate — still dormant due to floor=0

	c, w := ginContext(1) // tier_id=1, floor=0 → never shed
	mw := InflightPressureShed(s)
	mw(c)

	if w.Code == 503 {
		t.Fatalf("dormant path must not 503; got %d", w.Code)
	}
}
