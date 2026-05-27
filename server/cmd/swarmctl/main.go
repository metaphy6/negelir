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

// staticAgentSpec describes a well-known agent shim that always appears in
// `swarmctl ps` whether or not a live dynamic registry entry exists in Redis.
// hbKey is a Redis string (SET, RFC3339) written by the agent process on
// startup; swarmctl reads it for the LAST_HEARTBEAT column.
type staticAgentSpec struct {
	id    string
	row   agentRow
	hbKey string
}

// staticAgentManifest is the authoritative list of agents that must always
// appear in `swarmctl ps`. Phase 9 §9.13: api.gateway.v1 is wired here so
// the gateway shim is visible regardless of Redis dynamic-registry state.
// Adding an entry here requires a tracker row + server patch bump (AGENTS.md §6.1).
var staticAgentManifest = []staticAgentSpec{
	{
		id: "api.gateway.v1",
		row: agentRow{
			Name:       "api.gateway.v1",
			InstanceID: "api.gateway.v1",
			Subscribes: []any{"predict.request.v1"},
			Publishes:  []any{"api.request.v1", "api.response.v1", "predict.cancel.v1"},
		},
		hbKey: "agent:api.gateway.v1:heartbeat",
	},
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

	// Merge static agent shims that are not already registered dynamically.
	// Phase 9 §9.13: api.gateway.v1 must always appear in ps output.
	for _, sa := range staticAgentManifest {
		if _, ok := specs[sa.id]; ok {
			continue // live dynamic registration wins
		}
		enc, merr := json.Marshal(sa.row)
		if merr != nil {
			continue
		}
		specs[sa.id] = string(enc)
		// Per-agent heartbeat: a simple Redis string (SET, RFC3339).
		if hb, herr := rdb.Get(ctx, sa.hbKey).Result(); herr == nil {
			beats[sa.id] = hb
		}
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

// ── wire-authority (static; Go side of ai/swarm/sdk/wire_contracts.py) ──
//
// Maps topic name → sole/declared producer. This is the Go-side mirror of
// the Python `API_TOPIC_V1_ALLOWED_PRODUCERS` and
// `PREDICT_CANCEL_V1_ALLOWED_PRODUCERS` constants in
// `ai/swarm/sdk/wire_contracts.py`. The `topics` command reads this map so
// it can show a PRODUCER column alongside XLEN/PENDING/GROUPS for every
// known gateway-owned stream, whether or not the stream already exists in
// Redis (streams are created on first publish).
//
// Phase 9 §9.5 wire-authority delta: three topics owned by api.gateway.v1.
// Adding a producer here requires a corresponding update to wire_contracts.py
// and a tracker row + minor version bump (AGENTS.md §6.1).
var wireAuthorityProducers = map[string]string{
	"api.request.v1":    "api.gateway.v1",
	"api.response.v1":   "api.gateway.v1",
	"predict.cancel.v1": "api.gateway.v1",
}

// wireAuthorityConsumers maps topic name → the declared consumer component.
// The API gateway must consume predict.approved.v1 (the proofreader-approved
// reply) and must NEVER subscribe to raw predict.final, which is a
// swarm-internal topic (§9.3 forward contract).
//
// Phase 9 §9.14 wire-authority delta: predict.approved.v1 consumed by api.gateway.v1.
// Adding a consumer here requires a tracker row + server patch bump (AGENTS.md §6.1).
var wireAuthorityConsumers = map[string]string{
	"predict.approved.v1": "api.gateway.v1",
}

// ── topics ─────────────────────────────────────────────────────────────

func cmdTopics(ctx context.Context, rdb *redis.Client) error {
	// SCAN for stream keys; conservative — agents/topics naming has no
	// reserved prefix today, so we type-check each candidate.
	streams, err := scanStreams(ctx, rdb)
	if err != nil {
		return err
	}

	// Merge wire-authority topics that may not yet have a live Redis stream.
	// This ensures the command always lists the three Phase 9 topics with
	// their declared producer, even before the Go gateway has published its
	// first message (streams are created lazily on first XADD).
	knownWA := make(map[string]struct{}, len(wireAuthorityProducers))
	for t := range wireAuthorityProducers {
		knownWA[t] = struct{}{}
	}
	streamSet := make(map[string]struct{}, len(streams))
	for _, s := range streams {
		streamSet[s] = struct{}{}
	}
	for t := range knownWA {
		if _, ok := streamSet[t]; !ok {
			streams = append(streams, t)
		}
	}

	if len(streams) == 0 {
		fmt.Println("(no streams)")
		return nil
	}
	sort.Strings(streams)
	fmt.Printf("%-40s %-10s %-12s %-30s %s\n", "TOPIC", "XLEN", "PENDING", "GROUPS", "PRODUCER")
	for _, s := range streams {
		var xlen int64
		var totalPending int64
		var names []string
		if _, live := streamSet[s]; live {
			xlen, _ = rdb.XLen(ctx, s).Result()
			groups, _ := rdb.XInfoGroups(ctx, s).Result()
			names = make([]string, 0, len(groups))
			for _, g := range groups {
				totalPending += g.Pending
				names = append(names, g.Name)
			}
		}
		producer := wireAuthorityProducers[s]
		fmt.Printf("%-40s %-10d %-12d %-30s %s\n", s, xlen, totalPending, strings.Join(names, ","), producer)
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
