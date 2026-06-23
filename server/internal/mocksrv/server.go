// Package mocksrv provides the Phase 2 mock-data backend HTTP server.
package mocksrv

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

// manifestEntry represents one captured HTTP response in the seed corpus.
type manifestEntry struct {
	Source      string `json:"source"`
	URL         string `json:"url"`
	Path        string `json:"path"`
	CapturedAt  string `json:"captured_at"`
	SHA256      string `json:"sha256"`
	Bytes       int    `json:"bytes"`
	Status      int    `json:"status"`
	ContentType string `json:"content_type"`
}

// manifest is the top-level schema in infra/mock/seeds/manifest.json.
type manifest struct {
	Schema     int             `json:"schema"`
	CapturedAt *string         `json:"captured_at"`
	Entries    []manifestEntry `json:"entries"`
}

// routeKey is the (host, path) tuple for route lookup.
type routeKey struct{ host, path string }

// Router is the core request multiplexer for mocksrv.
type Router struct {
	mu       sync.RWMutex
	routes   map[routeKey]manifestEntry
	homes    map[string]manifestEntry // host → fallback HTML entry
	root     string
	srcHost  string // optional override for X-Negelir-Mock-Source
	fallback bool   // serve home HTML for unknown paths instead of 404
}

// NewRouter creates a new Router for the given seed corpus root.
func NewRouter(root string) *Router {
	return &Router{
		routes:   map[routeKey]manifestEntry{},
		homes:    map[string]manifestEntry{},
		root:     root,
		fallback: true, // dev-friendly default
	}
}

// LoadManifest reads manifest.json under r.root and rebuilds all routes.
func (r *Router) LoadManifest() error {
	path := filepath.Join(r.root, "manifest.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read manifest: %w", err)
	}
	var m manifest
	if err := json.Unmarshal(data, &m); err != nil {
		return fmt.Errorf("parse manifest: %w", err)
	}
	if m.Schema != 1 {
		return fmt.Errorf("unsupported manifest schema: %d", m.Schema)
	}

	next := make(map[routeKey]manifestEntry, len(m.Entries))
	homes := make(map[string]manifestEntry)
	for _, e := range m.Entries {
		urlPath, err := pathFromURL(e.URL)
		if err != nil {
			return fmt.Errorf("entry %s: %w", e.URL, err)
		}
		key := routeKey{host: e.Source, path: urlPath}
		next[key] = e
		// Pick a per-host fallback entry. Preference order:
		//   1) explicit "/" route
		//   2) any HTML payload
		//   3) the first entry we saw for this host (anything beats 404)
		existing, hasExisting := homes[e.Source]
		isHTML := strings.Contains(strings.ToLower(e.ContentType), "html")
		switch {
		case urlPath == "/":
			homes[e.Source] = e
		case !hasExisting:
			homes[e.Source] = e
		case isHTML && !strings.Contains(strings.ToLower(existing.ContentType), "html"):
			homes[e.Source] = e
		}
	}

	r.mu.Lock()
	r.routes = next
	r.homes = homes
	r.mu.Unlock()
	return nil
}

// pathFromURL extracts the path-and-query portion of an absolute URL
// without pulling in net/url just for a tiny string split.
func pathFromURL(u string) (string, error) {
	// strip scheme
	idx := strings.Index(u, "://")
	if idx < 0 {
		return "", fmt.Errorf("no scheme in URL: %s", u)
	}
	rest := u[idx+3:]
	slash := strings.IndexByte(rest, '/')
	if slash < 0 {
		return "/", nil
	}
	p := rest[slash:]
	// Drop fragment.
	if hash := strings.IndexByte(p, '#'); hash >= 0 {
		p = p[:hash]
	}
	return p, nil
}

// Lookup retrieves the entry for (host, path), or (ok=false) if not found.
func (r *Router) Lookup(host, path string) (manifestEntry, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	host = strings.ToLower(strings.SplitN(host, ":", 2)[0])
	e, ok := r.routes[routeKey{host: host, path: path}]
	return e, ok
}

// Stats returns the number of routes per host.
func (r *Router) Stats() map[string]int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	stats := map[string]int{}
	for k := range r.routes {
		stats[k.host]++
	}
	return stats
}

// ServeHTTP implements http.Handler.
func (r *Router) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	host := req.Host
	if h := req.Header.Get("X-Negelir-Mock-Source"); h != "" {
		host = h
	}
	path := req.URL.Path

	if path == "/__mocksrv/health" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"ok":     true,
			"routes": r.Stats(),
		})
		return
	}
	if path == "/__mocksrv/reload" && req.Method == http.MethodPost {
		if err := r.LoadManifest(); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		_, _ = fmt.Fprintln(w, "reloaded")
		return
	}

	entry, ok := r.Lookup(host, path)
	fallback := false
	if !ok {
		// Dev-friendly: serve the home HTML so a user clicking around the
		// mocked site never hits a 404. Set X-Negelir-Mock-Fallback=1 so
		// callers (and tests) can tell the difference.
		canonicalHost := strings.ToLower(strings.SplitN(host, ":", 2)[0])
		r.mu.RLock()
		home, hasHome := r.homes[canonicalHost]
		fallbackEnabled := r.fallback
		r.mu.RUnlock()
		if fallbackEnabled && hasHome {
			entry = home
			fallback = true
		} else {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusNotFound)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"error": "no mock entry",
				"host":  canonicalHost,
				"path":  path,
				"hint":  "run `make mock.capture` (or `make mock.capture FORCE=1 DEPTH=1`) to broaden the seed corpus",
			})
			return
		}
	}

	body, err := os.ReadFile(filepath.Join(r.root, entry.Path))
	if err != nil {
		http.Error(w, "seed payload missing: "+err.Error(), http.StatusInternalServerError)
		return
	}

	if entry.ContentType != "" {
		w.Header().Set("Content-Type", entry.ContentType)
	}
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.Header().Set("X-Negelir-Mock-Captured-At", entry.CapturedAt)
	w.Header().Set("X-Negelir-Mock-Sha256", entry.SHA256)
	if fallback {
		w.Header().Set("X-Negelir-Mock-Fallback", "1")
	}

	status := entry.Status
	if status == 0 {
		status = http.StatusOK
	}
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// Server wraps the mocksrv HTTP server with startup/shutdown handling.
type Server struct {
	addr   string
	router *Router
	srv    *http.Server
}

// New creates a new mocksrv server.
func New(addr, seedsDir string) (*Server, error) {
	r := NewRouter(seedsDir)
	if err := r.LoadManifest(); err != nil {
		return nil, err
	}
	stats := r.Stats()
	log.Printf("mocksrv: loaded %d hosts from %s", len(stats), seedsDir)
	for h, n := range stats {
		log.Printf("  • %s: %d route(s)", h, n)
	}
	return &Server{
		addr:   addr,
		router: r,
		srv:    &http.Server{Addr: addr, Handler: r},
	}, nil
}

// ListenAndServe starts the server.
func (s *Server) ListenAndServe() error {
	log.Printf("mocksrv listening on %s", s.addr)
	if err := s.srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

// Shutdown gracefully shuts down the server.
func (s *Server) Shutdown(ctx context.Context) error {
	return s.srv.Shutdown(ctx)
}
