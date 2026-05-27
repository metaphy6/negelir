//go:build !linux

package tcp

// setTCPUserTimeout is a no-op on non-Linux platforms.
// TCP_USER_TIMEOUT is a Linux-specific socket option.
func setTCPUserTimeout(_ uintptr, _ int) error { return nil }
