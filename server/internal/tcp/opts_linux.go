//go:build linux

package tcp

import "syscall"

// tcpUserTimeout is TCP_USER_TIMEOUT (RFC 5482).
// Defined in <linux/tcp.h> as 18; not exported by Go's syscall package on
// all architectures, so we define it explicitly here.
const tcpUserTimeout = 18

// setTCPUserTimeout sets TCP_USER_TIMEOUT on the given fd to ms milliseconds.
// Called by SetTCPOpts on every accepted connection.
func setTCPUserTimeout(fd uintptr, ms int) error {
	return syscall.SetsockoptInt(int(fd), syscall.IPPROTO_TCP, tcpUserTimeout, ms)
}
