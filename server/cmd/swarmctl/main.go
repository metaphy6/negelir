// Command swarmctl is the read-only operator CLI for the Negelir swarm bus.
//
// Phase 3 surface: ps | topics | tail. Mutating commands (restart/scale/drain)
// are intentionally NOT in this build — they belong to Phase 8 maint.scaler.v1
// per ROADMAP §3.4.
//
// Usage:
//
//	swarmctl ps                       # list registered agents + heartbeats
//	swarmctl topics                   # XLEN + pending per stream
//	swarmctl tail <topic> [-n N]      # dump last N messages (JSON)
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/metaphy6/negelir/server/internal/config"
)

const (
	registryKey   = "agent_registry"
	heartbeatKey  = "agent_heartbeats"
	defaultTailN  = 20
	staleMultiple = 3 // dead-after-3-missed-heartbeats per ROADMAP §3.2
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	cfg, err := config.Load()
	if err != nil {
		fail("config: %v", err)
	}
	rdb := redis.NewClient(&redis.Options{Addr: cfg.EffectiveRedisURL()})
	defer rdb.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	switch os.Args[1] {
	case "ps":
		mustOK(cmdPs(ctx, rdb, cfg))
	case "topics":
		mustOK(cmdTopics(ctx, rdb))
	case "tail":
		fs := flag.NewFlagSet("tail", flag.ExitOnError)
		n := fs.Int("n", defaultTailN, "number of messages to show")
		_ = fs.Parse(os.Args[2:])
		if fs.NArg() < 1 {
			fail("tail: missing <topic>")
		}
		mustOK(cmdTail(ctx, rdb, fs.Arg(0), *n))
	case "-h", "--help", "help":
		usage()
	default:
		fail("unknown command %q", os.Args[1])
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, `swarmctl — read-only operator CLI for the Negelir swarm bus.

Commands:
  ps                       list registered agents + heartbeats + stale marker
  topics                   list streams with XLEN + pending count
  tail <topic> [-n N]      dump last N messages (default 20)`)
}

// ── ps ─────────────────────────────────────────────────────────────────

type agentRow struct {
	Name        string `json:"name"`
	InstanceID  string `json:"instance_id"`
	Pid         int    `json:"pid"`
	Subscribes  []any  `json:"subscribes"`
	Publishes   []any  `json:"publishes"`
}

func cmdPs(ctx context.Context, rdb *redis.Client, cfg *config.Config) error {
	specs, err := rdb.HGetAll(ctx, registryKey).Result()
	if err != nil {
		return fmt.Errorf("hgetall %s: %w", registryKey, err)
	}
	beats, err := rdb.HGetAll(ctx, heartbeatKey).Result()
	if err != nil {
		return fmt.Errorf("hgetall %s: %w", heartbeatKey, err)
	}
	if len(specs) == 0 {
		fmt.Println("(no registered agents)")
		return nil
	}
	hbWindow := time.Duration(cfg.SwarmHeartbeatSec) * time.Second * staleMultiple
	now := time.Now().UTC()

	ids := make([]string, 0, len(specs))
	for id := range specs {
		ids = append(ids, id)
	}
	sort.Strings(ids)

	fmt.Printf("%-32s %-30s %-25s %-7s %s\n", "INSTANCE", "AGENT", "LAST_HEARTBEAT", "STATE", "SUBS→PUBS")
	for _, id := range ids {
		var row agentRow
		if err := json.Unmarshal([]byte(specs[id]), &row); err != nil {
			row.Name = "(unparseable)"
		}
		hb := beats[id]
		state := "OK"
		if hb == "" {
			state = "✗STALE"
		} else if t, err := time.Parse(time.RFC3339, hb); err == nil {
			if now.Sub(t) > hbWindow {
				state = "✗STALE"
			}
		}
		fmt.Printf("%-32s %-30s %-25s %-7s %v→%v\n",
			id, row.Name, hb, state, row.Subscribes, row.Publishes)
	}
	return nil
}

// ── topics ─────────────────────────────────────────────────────────────

func cmdTopics(ctx context.Context, rdb *redis.Client) error {
	// SCAN for stream keys; conservative — agents/topics naming has no
	// reserved prefix today, so we type-check each candidate.
	streams, err := scanStreams(ctx, rdb)
	if err != nil {
		return err
	}
	if len(streams) == 0 {
		fmt.Println("(no streams)")
		return nil
	}
	sort.Strings(streams)
	fmt.Printf("%-40s %-10s %-12s %s\n", "TOPIC", "XLEN", "PENDING", "GROUPS")
	for _, s := range streams {
		xlen, _ := rdb.XLen(ctx, s).Result()
		groups, _ := rdb.XInfoGroups(ctx, s).Result()
		var totalPending int64
		names := make([]string, 0, len(groups))
		for _, g := range groups {
			totalPending += g.Pending
			names = append(names, g.Name)
		}
		fmt.Printf("%-40s %-10d %-12d %s\n", s, xlen, totalPending, strings.Join(names, ","))
	}
	return nil
}

func scanStreams(ctx context.Context, rdb *redis.Client) ([]string, error) {
	var (
		cursor uint64
		out    []string
	)
	for {
		keys, next, err := rdb.Scan(ctx, cursor, "*", 256).Result()
		if err != nil {
			return nil, fmt.Errorf("scan: %w", err)
		}
		for _, k := range keys {
			t, err := rdb.Type(ctx, k).Result()
			if err == nil && t == "stream" {
				out = append(out, k)
			}
		}
		if next == 0 {
			return out, nil
		}
		cursor = next
	}
}

// ── tail ───────────────────────────────────────────────────────────────

func cmdTail(ctx context.Context, rdb *redis.Client, topic string, n int) error {
	if n <= 0 {
		n = defaultTailN
	}
	entries, err := rdb.XRevRangeN(ctx, topic, "+", "-", int64(n)).Result()
	if err != nil {
		return fmt.Errorf("xrevrange %s: %w", topic, err)
	}
	// Print oldest first for readability.
	for i := len(entries) - 1; i >= 0; i-- {
		e := entries[i]
		raw, ok := e.Values["data"].(string)
		if !ok {
			fmt.Printf("[%s] (non-data entry: %v)\n", e.ID, e.Values)
			continue
		}
		fmt.Printf("[%s] %s\n", e.ID, raw)
	}
	return nil
}

// ── helpers ────────────────────────────────────────────────────────────

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "swarmctl: "+format+"\n", args...)
	os.Exit(1)
}

func mustOK(err error) {
	if err != nil {
		fail("%v", err)
	}
}
