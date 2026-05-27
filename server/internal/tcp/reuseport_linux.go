//go:build linux

// Package tcp -- SO_REUSEPORT listener (SS9.17.8, Linux only).
//
// NewReusePortListener creates a TCP listener with SO_REUSEPORT set so that
// multiple goroutines (one per GOMAXPROCS) can each bind the same address and
// the kernel load-balances incoming connections across them.
package tcp

import (
	"context"
	"net"
	"syscall"
)

// soReusePort is SO_REUSEPORT = 15 (0xf) on all Linux architectures.
// Not exported by Go's syscall package; defined here with build tag linux.
const soReusePort = 0xf

// NewReusePortListener creates a TCP listener on addr with SO_REUSEPORT
// enabled.  On Linux this allows multiple acceptor goroutines to share the
// same port without thundering-herd on accept().
//
// SS9.17.8 -- "SO_REUSEPORT on Linux: multiple acceptor goroutines, one per
// GOMAXPROCS."
func NewReusePortListener(network, addr string) (net.Listener, error) {
	lc := net.ListenConfig{
		Control: func(_, _ string, c syscall.RawConn) error {
			var setSockErr error
			if err := c.Control(func(fd uintptr) {
				setSockErr = syscall.SetsockoptInt(
					int(fd), syscall.SOL_SOCKET, soReusePort, 1)
			}); err != nil {
				return err
			}
			return setSockErr
		},
	}
	return lc.Listen(context.Background(), network, addr)
}
