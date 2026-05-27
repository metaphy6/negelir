//go:build !linux

// Package tcp — SO_REUSEPORT fallback for non-Linux platforms.
package tcp

import "net"

// NewReusePortListener falls back to a plain net.Listen on non-Linux
// platforms where SO_REUSEPORT semantics differ or are unavailable.
func NewReusePortListener(network, addr string) (net.Listener, error) {
	return net.Listen(network, addr)
}
