package sec

import (
	"fmt"
	"net"
	"strings"
)

// TrustedProxies is the parsed form of `cfg.sec_rate_trusted_proxies`
// (a comma-separated list of CIDRs). The empty list means "trust no
// XFF hops" — the gateway uses the TCP peer address.
type TrustedProxies struct {
	nets []*net.IPNet
}

// ParseTrustedProxies parses a comma-separated CIDR list. Whitespace
// around entries is trimmed; empty entries are skipped. A malformed
// CIDR fails the call loud — the operator must fix the env before
// the gateway starts.
func ParseTrustedProxies(raw string) (*TrustedProxies, error) {
	tp := &TrustedProxies{}
	if strings.TrimSpace(raw) == "" {
		return tp, nil
	}
	for _, entry := range strings.Split(raw, ",") {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		// net.ParseCIDR rejects bare IPs without a mask; require a mask
		// so the operator is explicit about the trust scope.
		_, n, err := net.ParseCIDR(entry)
		if err != nil {
			return nil, fmt.Errorf("trusted-proxies: parse %q: %w", entry, err)
		}
		tp.nets = append(tp.nets, n)
	}
	return tp, nil
}

// Contains reports whether the given IP is inside one of the trusted
// proxy CIDRs. A nil receiver / empty list returns false (no trust).
func (tp *TrustedProxies) Contains(ip net.IP) bool {
	if tp == nil || ip == nil {
		return false
	}
	for _, n := range tp.nets {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}

// IsEmpty reports whether the trusted-proxy list is empty (the safe
// default — XFF is ignored entirely and the TCP peer wins).
func (tp *TrustedProxies) IsEmpty() bool {
	return tp == nil || len(tp.nets) == 0
}

// DeriveClientIP picks the right-most-untrusted hop of `xff` if XFF
// trust is enabled; otherwise it returns the TCP peer address. This
// is the binding §7.3 contract (defense against XFF spoofing): an
// attacker can only spoof their TCP source.
//
// `xff` is the comma-separated value of the X-Forwarded-For header
// (whatever was on the wire — the function trims and parses each
// entry). `peer` is the TCP source address as a string (Gin's
// `c.RemoteIP()` value works).
//
// Returns the chosen client IP. Returns peer (parsed) when XFF is
// disabled, malformed, or every entry is trusted.
//
// Worked example, from the right (newest hop) to the left (oldest):
//
//	X-Forwarded-For: spoofed, real_client, trusted_lb
//	trusted_proxies: 10.0.0.0/8 (matches trusted_lb)
//
// Walk right-to-left, skipping `trusted_lb` (in trusted CIDRs); pick
// `real_client` (first non-trusted hop). `spoofed` is to the left of
// the first non-trusted hop and is ignored entirely — an attacker
// can prepend whatever they want there but the right-most untrusted
// hop is always our gateway's view of "who we got the request from".
//
// If the chosen hop fails to parse as an IP, the function falls back
// to the next hop (right-to-left) and ultimately to the TCP peer.
func DeriveClientIP(xff string, peer string, trusted *TrustedProxies) net.IP {
	peerIP := net.ParseIP(strings.TrimSpace(peer))
	// XFF disabled (no trusted proxies) — TCP peer always wins.
	if trusted == nil || trusted.IsEmpty() {
		return peerIP
	}
	if strings.TrimSpace(xff) == "" {
		return peerIP
	}
	// Walk hops right-to-left.
	hops := strings.Split(xff, ",")
	for i := len(hops) - 1; i >= 0; i-- {
		hop := strings.TrimSpace(hops[i])
		ip := net.ParseIP(hop)
		if ip == nil {
			// malformed hop; skip
			continue
		}
		if trusted.Contains(ip) {
			continue
		}
		return ip
	}
	return peerIP
}

// SubjectKey returns the deterministic per-IP bucket subject for the
// rate limiter, applying the IPv4 / IPv6 prefix masks (default 32 / 64).
// Defends against IPv6 address-space spray: a single end-site /64 maps
// to ONE bucket.
//
// Returns the canonical `<network>/<prefix>` string (e.g.
// "203.0.113.7/32" or "2001:db8::/64") so two requests from the same
// allocation collapse to the same Redis key.
//
// Negative or out-of-range prefixes (caller misconfig) are clamped to
// the family-default (32 for IPv4, 64 for IPv6). A nil IP returns "".
func SubjectKey(ip net.IP, ipv4Prefix, ipv6Prefix int) string {
	if ip == nil {
		return ""
	}
	if v4 := ip.To4(); v4 != nil {
		prefix := ipv4Prefix
		if prefix < 1 || prefix > 32 {
			prefix = 32
		}
		mask := net.CIDRMask(prefix, 32)
		return (&net.IPNet{IP: v4.Mask(mask), Mask: mask}).String()
	}
	prefix := ipv6Prefix
	if prefix < 1 || prefix > 128 {
		prefix = 64
	}
	mask := net.CIDRMask(prefix, 128)
	return (&net.IPNet{IP: ip.Mask(mask), Mask: mask}).String()
}
