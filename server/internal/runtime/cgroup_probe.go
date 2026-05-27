// Package runtimetuning provides Go runtime tuning helpers applied at boot.
//
// §9.17.1 cgroup probe: reads memory.max from the Linux cgroup v2 hierarchy
// and returns 80% of that value as the default GOMEMLIMIT (in bytes).
// Falls back to the cgroup v1 path when v2 is absent.
package runtimetuning

import (
	"errors"
	"fmt"
	"math"
	"os"
	"strconv"
	"strings"
)

const (
	// cgroupV2MemMax is the standard cgroup v2 memory limit file.
	cgroupV2MemMax = "/sys/fs/cgroup/memory.max"
	// cgroupV1MemMax is the cgroup v1 equivalent.
	cgroupV1MemMax = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
	// GoMemLimitFraction is the fraction of cgroup memory.max used as
	// the default GOMEMLIMIT. 0.8 leaves 20% headroom for non-Go allocations
	// (kernel buffers, mmap files, CGO, etc.).
	GoMemLimitFraction = 0.80
	// cgroupUnlimited is the sentinel written by the kernel when no limit is set.
	cgroupUnlimited = "max"
)

// ErrCgroupUnlimited is returned when the cgroup reports no memory limit.
var ErrCgroupUnlimited = errors.New("cgroup memory.max is unlimited (no container limit set)")

// CgroupMemoryMaxBytes reads the container memory limit from the cgroup
// filesystem. Tries cgroup v2 first, then v1.
// Returns the raw byte limit or ErrCgroupUnlimited when no limit is configured.
func CgroupMemoryMaxBytes() (int64, error) {
	for _, path := range []string{cgroupV2MemMax, cgroupV1MemMax} {
		raw, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		s := strings.TrimSpace(string(raw))
		if s == cgroupUnlimited || s == "" {
			return 0, ErrCgroupUnlimited
		}
		v, parseErr := strconv.ParseInt(s, 10, 64)
		if parseErr != nil {
			return 0, fmt.Errorf("cgroup_probe: cannot parse %q from %s: %w", s, path, parseErr)
		}
		// cgroup v1 uses near-MaxInt64 as sentinel for "no limit" on 64-bit kernels.
		if v <= 0 || v == math.MaxInt64 || v >= (math.MaxInt64-4096) {
			return 0, ErrCgroupUnlimited
		}
		return v, nil
	}
	return 0, fmt.Errorf("cgroup_probe: neither %s nor %s is readable", cgroupV2MemMax, cgroupV1MemMax)
}

// DefaultGoMemLimitBytes returns 80% of the cgroup memory limit (rounded down
// to the nearest mebibyte) as the suggested GOMEMLIMIT value in bytes.
func DefaultGoMemLimitBytes() (int64, error) {
	total, err := CgroupMemoryMaxBytes()
	if err != nil {
		return 0, err
	}
	// Round down to whole MiB for readable log output.
	mib := int64(float64(total) * GoMemLimitFraction / (1 << 20))
	if mib < 1 {
		return 0, fmt.Errorf("cgroup_probe: computed GOMEMLIMIT (%d MiB) is too small", mib)
	}
	return mib << 20, nil
}
