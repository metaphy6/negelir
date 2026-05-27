package rpc_test

// rpc_adversarial_test.go — §9.14 adversarial RPC proof tests.
//
// TestAdvCancellationRaceAfterFinal — adv_test_cancellation_race_after_final.
//
// A cancel signal arriving 0..50 ms AFTER predict.final (rpcDone closes)
// must not cause a DUPLICATE response or a panic. The HTTP response cannot
// be duplicated because gin's ResponseWriter is single-use; the predict.cancel.v1
// publish may still fire (at most once) when the race is won by the cancel branch
// of the outer select before rpcDone becomes observable — this is tolerated and
// documented in §9.3. The invariant is: ≤ 1 publish per request and no panic.
//
// Phase 12 prerequisite; must be green at Phase 9 close. Run with -race.

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/metaphy6/negelir/server/internal/rpc"
)

// TestAdvCancellationRaceAfterFinal — adv_test_cancellation_race_after_final.
//
// Runs 1000 iterations; each iteration:
//  1. Starts WatchAndCancel.
//  2. Closes rpcDone (predict.final received — RPC complete).
//  3. Cancels clientCtx after a 0–50 µs delay (within the spec's 0–50 ms window).
//  4. Asserts: ≤ 1 publish per iteration (no duplicate) and no panic.
//
// The "NO duplicate response" guarantee comes from gin's single-use
// ResponseWriter, not from predict.cancel.v1 suppression. WatchAndCancel may
// legitimately publish one cancel if the outer select lands on the clientCtx
// branch before rpcDone is visible; the inner guard prevents a second publish.
func TestAdvCancellationRaceAfterFinal(t *testing.T) {
	const iterations = 1000
	for i := 0; i < iterations; i++ {
		pub := &stubCancelPublisher{}
		rpcDone := make(chan struct{})
		clientCtx, clientCancel := context.WithCancel(context.Background())

		watchDone := make(chan struct{})
		go func() {
			defer close(watchDone)
			rpc.WatchAndCancel(clientCtx, rpcDone, "req-adv-race-final", pub)
		}()

		// Fire rpcDone and clientCancel from two goroutines; sleep on the cancel
		// side to bias toward the "cancel arrives just after final" ordering.
		var wg sync.WaitGroup
		wg.Add(2)
		go func() {
			defer wg.Done()
			close(rpcDone) // predict.final received
		}()
		go func() {
			defer wg.Done()
			// 0–50 µs delay to model the 0–50 ms spec window at µs scale;
			// the Go scheduler provides the non-deterministic interleaving.
			time.Sleep(time.Duration(i%50) * time.Microsecond)
			clientCancel()
		}()
		wg.Wait()

		select {
		case <-watchDone:
		case <-time.After(2 * time.Second):
			t.Fatalf("iter %d: WatchAndCancel did not return within 2s", i)
		}

		// Invariant: at most 1 publish (no duplicate cancel), never > 1.
		// 0 is the common case (rpcDone wins the outer select); 1 is the
		// tolerated race case (clientCtx wins the outer select but the inner
		// guard prevents a second publish).
		if n := pub.CallCount(); n > 1 {
			t.Errorf("iter %d: PublishCancel called %d times; want ≤ 1 (duplicate cancel is a §9.3 violation)", i, n)
		}
	}
}
