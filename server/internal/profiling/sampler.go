// Package profiling implements §9.17.10 continuous CPU profiling.
//
// StartSampler runs a background goroutine that captures a 10-second CPU
// profile every 10 minutes, gzips it, and writes it to:
//
//	<dir>/<hostname>/<utc-timestamp>.pprof.gz
//
// Files older than 7 days are automatically deleted after each write cycle.
// The goroutine exits when ctx is cancelled (graceful shutdown).
//
// Design constraints (§9.17.10):
//   - Profile duration: 10 seconds.
//   - Capture interval: 10 minutes.
//   - CPU overhead: < 1% (enforced by the short profile window).
//   - Retention: 7 days (older files are removed after each write).
//   - The pod identity used as the directory name is os.Hostname(); on K8s
//     this resolves to the pod name, which matches the Redis pprof key scheme.
package profiling

import (
	"compress/gzip"
	"context"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"runtime/pprof"
	"time"
)

const (
	profileDuration = 10 * time.Second
	sampleInterval  = 10 * time.Minute
	retentionPeriod = 7 * 24 * time.Hour
)

// StartSampler starts the background continuous-profiling goroutine and
// returns immediately. The goroutine runs until ctx is cancelled.
//
// dir is the base directory (cfg.APIPprofDir, default "data/api/profiles").
// It is created on first write if absent.
func StartSampler(ctx context.Context, dir string) {
	hostname, err := os.Hostname()
	if err != nil {
		hostname = "unknown"
	}
	podDir := filepath.Join(dir, hostname)

	go func() {
		// Capture an initial profile immediately at startup so operators get
		// a baseline without waiting 10 minutes.
		if err := captureProfile(ctx, podDir); err != nil && ctx.Err() == nil {
			log.Printf("[profiling] first capture failed: %v", err)
		}

		ticker := time.NewTicker(sampleInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if err := captureProfile(ctx, podDir); err != nil && ctx.Err() == nil {
					log.Printf("[profiling] capture failed: %v", err)
				}
				rotateOld(podDir)
			}
		}
	}()
}

// captureProfile records a CPU profile for profileDuration and writes it as a
// gzip-compressed pprof file under dir named by the UTC start time.
func captureProfile(ctx context.Context, dir string) error {
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return fmt.Errorf("profiling: mkdir %s: %w", dir, err)
	}

	startTime := time.Now().UTC()
	filename := filepath.Join(dir, startTime.Format("20060102T150405Z")+".pprof.gz")

	f, err := os.OpenFile(filename, os.O_CREATE|os.O_WRONLY|os.O_EXCL, 0o640)
	if err != nil {
		return fmt.Errorf("profiling: create %s: %w", filename, err)
	}
	defer func() {
		if cerr := f.Close(); cerr != nil {
			log.Printf("[profiling] close %s: %v", filename, cerr)
		}
	}()

	gz := gzip.NewWriter(f)
	defer func() {
		if cerr := gz.Close(); cerr != nil {
			log.Printf("[profiling] gz close %s: %v", filename, cerr)
		}
	}()

	if err := pprof.StartCPUProfile(gz); err != nil {
		_ = os.Remove(filename)
		return fmt.Errorf("profiling: start cpu profile: %w", err)
	}

	// Sleep for profileDuration or until context is cancelled.
	select {
	case <-time.After(profileDuration):
	case <-ctx.Done():
	}

	pprof.StopCPUProfile()

	log.Printf("[profiling] wrote %s", filename)
	return nil
}

// rotateOld removes pprof.gz files in dir older than retentionPeriod.
func rotateOld(dir string) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		// Dir may not exist yet on the first pass; that's fine.
		return
	}
	cutoff := time.Now().Add(-retentionPeriod)
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		if info.ModTime().Before(cutoff) {
			path := filepath.Join(dir, e.Name())
			if rerr := os.Remove(path); rerr != nil {
				log.Printf("[profiling] rotate remove %s: %v", path, rerr)
			}
		}
	}
}
