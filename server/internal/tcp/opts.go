// Package tcp provides TCP-level socket-option helpers used at listener
// creation time (§9.17.8).
//
// SetTCPOpts applies TCP_USER_TIMEOUT (Linux-only; no-op elsewhere) to the
// underlying *net.TCPConn of any net.Conn accepted by the listener.
//
// WrapListener returns a net.Listener that calls SetTCPOpts on every accepted
// connection before returning it to the caller.  This is the correct injection
// point for per-connection TCP options with net/http: wrap the raw listener
// and pass it to http.Server.Serve() instead of calling ListenAndServe().
package tcp

import "net"

// SetTCPOpts sets TCP_USER_TIMEOUT to userTimeoutMs milliseconds on conn.
// conn must be a *net.TCPConn (or any net.Conn whose SyscallConn() returns a
// usable syscall.RawConn).  On non-Linux platforms this is a no-op.
func SetTCPOpts(conn net.Conn, userTimeoutMs int) error {
	tc, ok := conn.(*net.TCPConn)
	if !ok {
		return nil
	}
	raw, err := tc.SyscallConn()
	if err != nil {
		return err
	}
	var setsockoptErr error
	_ = raw.Control(func(fd uintptr) {
		setsockoptErr = setTCPUserTimeout(fd, userTimeoutMs)
	})
	return setsockoptErr
}

// wrappedListener wraps a net.Listener and applies SetTCPOpts to every
// accepted connection.
type wrappedListener struct {
	net.Listener
	userTimeoutMs int
}

func (wl *wrappedListener) Accept() (net.Conn, error) {
	conn, err := wl.Listener.Accept()
	if err != nil {
		return conn, err
	}
	// Best-effort: TCP options are a performance tuning knob, not a
	// correctness requirement; errors are non-fatal.
	_ = SetTCPOpts(conn, wl.userTimeoutMs)
	return conn, nil
}

// WrapListener returns a net.Listener that applies SetTCPOpts(conn,
// userTimeoutMs) on every accepted connection.  Pass the wrapped listener to
// http.Server.Serve() rather than calling ListenAndServe().
func WrapListener(l net.Listener, userTimeoutMs int) net.Listener {
	return &wrappedListener{Listener: l, userTimeoutMs: userTimeoutMs}
}
