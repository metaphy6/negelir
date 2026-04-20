package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Build a minimal seeds tree + manifest, return root path.
func writeSeeds(t *testing.T, entries []manifestEntry, payloads map[string][]byte) string {
	t.Helper()
	root := t.TempDir()
	for rel, body := range payloads {
		full := filepath.Join(root, rel)
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, body, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	m := manifest{Schema: 1, Entries: entries}
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "manifest.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}
	return root
}

func TestPathFromURL(t *testing.T) {
	cases := []struct {
		in, want string
	}{
		{"https://example.com/", "/"},
		{"https://example.com", "/"},
		{"https://example.com/foo/bar", "/foo/bar"},
		{"https://example.com/foo?x=1", "/foo?x=1"},
		{"https://example.com/foo#frag", "/foo"},
	}
	for _, c := range cases {
		got, err := pathFromURL(c.in)
		if err != nil {
			t.Errorf("%s: unexpected error %v", c.in, err)
			continue
		}
		if got != c.want {
			t.Errorf("%s: got %q want %q", c.in, got, c.want)
		}
	}
	if _, err := pathFromURL("no-scheme"); err == nil {
		t.Error("expected error for scheme-less URL")
	}
}

func TestServeHit(t *testing.T) {
	body := []byte(`{"hello":"world"}`)
	root := writeSeeds(t,
		[]manifestEntry{{
			Source: "mackolik.local", URL: "https://www.mackolik.com/api/x",
			Path: "mackolik/x.json", SHA256: "deadbeef", Bytes: len(body),
			Status: 200, ContentType: "application/json", CapturedAt: "2026-04-20T00:00:00+00:00",
		}},
		map[string][]byte{"mackolik/x.json": body},
	)

	r := NewRouter(root)
	if err := r.LoadManifest(); err != nil {
		t.Fatal(err)
	}

	req := httptest.NewRequest("GET", "http://mackolik.local/api/x", nil)
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)

	if rr.Code != 200 {
		t.Fatalf("status: got %d want 200", rr.Code)
	}
	if rr.Body.String() != string(body) {
		t.Errorf("body mismatch: %q", rr.Body.String())
	}
	if got := rr.Header().Get("Content-Type"); got != "application/json" {
		t.Errorf("content-type: %q", got)
	}
	if rr.Header().Get("X-Negelir-Mock-Captured-At") == "" {
		t.Error("missing captured-at header")
	}
}

func TestServeMissReturns404Json(t *testing.T) {
	root := writeSeeds(t, nil, nil)
	r := NewRouter(root)
	r.fallback = false // exercise the strict path
	_ = r.LoadManifest()

	req := httptest.NewRequest("GET", "http://nesine.local/oops", nil)
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)

	if rr.Code != 404 {
		t.Fatalf("status: got %d want 404", rr.Code)
	}
	if !strings.Contains(rr.Body.String(), "no mock entry") {
		t.Errorf("body: %q", rr.Body.String())
	}
}

func TestServeUnknownPathFallsBackToHome(t *testing.T) {
	body := []byte("<html>HOME</html>")
	root := writeSeeds(t,
		[]manifestEntry{{
			Source: "mackolik.local", URL: "https://www.mackolik.com/",
			Path: "mackolik/home.html", Status: 200, ContentType: "text/html",
		}},
		map[string][]byte{"mackolik/home.html": body},
	)
	r := NewRouter(root)
	_ = r.LoadManifest()

	req := httptest.NewRequest("GET", "http://mackolik.local/totally/random/path", nil)
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)

	if rr.Code != 200 {
		t.Fatalf("status: got %d want 200 (fallback)", rr.Code)
	}
	if rr.Header().Get("X-Negelir-Mock-Fallback") != "1" {
		t.Errorf("missing X-Negelir-Mock-Fallback header; got %q", rr.Header().Get("X-Negelir-Mock-Fallback"))
	}
	if !strings.Contains(rr.Body.String(), "HOME") {
		t.Errorf("expected home body, got %q", rr.Body.String())
	}
}

func TestServeUnknownPathReturns404WhenFallbackDisabled(t *testing.T) {
	body := []byte("<html>HOME</html>")
	root := writeSeeds(t,
		[]manifestEntry{{
			Source: "mackolik.local", URL: "https://www.mackolik.com/",
			Path: "mackolik/home.html", Status: 200, ContentType: "text/html",
		}},
		map[string][]byte{"mackolik/home.html": body},
	)
	r := NewRouter(root)
	r.fallback = false
	_ = r.LoadManifest()

	req := httptest.NewRequest("GET", "http://mackolik.local/totally/random/path", nil)
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)

	if rr.Code != 404 {
		t.Fatalf("status: got %d want 404", rr.Code)
	}
}

func TestRoutingHonoursOverrideHeader(t *testing.T) {
	body := []byte("ok")
	root := writeSeeds(t,
		[]manifestEntry{{
			Source: "tff.local", URL: "https://www.tff.org/",
			Path: "tff/home.html", Status: 200, ContentType: "text/html",
		}},
		map[string][]byte{"tff/home.html": body},
	)
	r := NewRouter(root)
	_ = r.LoadManifest()

	// nginx may proxy to a different Host header but inject our X-Negelir header.
	req := httptest.NewRequest("GET", "http://internal-name/", nil)
	req.Header.Set("X-Negelir-Mock-Source", "tff.local")
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)

	if rr.Code != 200 {
		t.Fatalf("status: got %d want 200", rr.Code)
	}
}

func TestHealthEndpoint(t *testing.T) {
	root := writeSeeds(t,
		[]manifestEntry{{
			Source: "x.local", URL: "https://x.com/", Path: "a", Status: 200,
		}},
		map[string][]byte{"a": []byte("hi")},
	)
	r := NewRouter(root)
	_ = r.LoadManifest()

	req := httptest.NewRequest("GET", "http://anything/__mocksrv/health", nil)
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status: %d", rr.Code)
	}
	var payload map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["ok"] != true {
		t.Errorf("expected ok=true, got %v", payload["ok"])
	}
}

func TestReloadRereadsManifest(t *testing.T) {
	root := writeSeeds(t, nil, nil)
	r := NewRouter(root)
	_ = r.LoadManifest()

	// add an entry on disk
	body := []byte("added")
	if err := os.MkdirAll(filepath.Join(root, "x"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "x", "y.html"), body, 0o644); err != nil {
		t.Fatal(err)
	}
	m := manifest{Schema: 1, Entries: []manifestEntry{{
		Source: "x.local", URL: "https://x.com/y", Path: "x/y.html",
		Status: 200, ContentType: "text/html",
	}}}
	data, _ := json.Marshal(m)
	_ = os.WriteFile(filepath.Join(root, "manifest.json"), data, 0o644)

	// reload via HTTP
	req := httptest.NewRequest(http.MethodPost, "http://anything/__mocksrv/reload", nil)
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)
	if rr.Code != 200 {
		t.Fatalf("reload: %d %s", rr.Code, rr.Body.String())
	}

	// the new route now serves
	req2 := httptest.NewRequest("GET", "http://x.local/y", nil)
	rr2 := httptest.NewRecorder()
	r.ServeHTTP(rr2, req2)
	if rr2.Code != 200 || rr2.Body.String() != "added" {
		t.Errorf("post-reload: code=%d body=%q", rr2.Code, rr2.Body.String())
	}
}
