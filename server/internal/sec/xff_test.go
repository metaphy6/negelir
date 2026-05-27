package sec

import (
	"net"
	"testing"
)

func TestParseTrustedProxiesEmpty(t *testing.T) {
	tp, err := ParseTrustedProxies("")
	if err != nil {
		t.Fatalf("empty: %v", err)
	}
	if !tp.IsEmpty() {
		t.Fatal("empty list must report IsEmpty=true")
	}
}

func TestParseTrustedProxiesValid(t *testing.T) {
	tp, err := ParseTrustedProxies("10.0.0.0/8, 172.16.0.0/12,2001:db8::/32")
	if err != nil {
		t.Fatalf("valid: %v", err)
	}
	if tp.IsEmpty() {
		t.Fatal("non-empty list must not report IsEmpty")
	}
	if !tp.Contains(net.ParseIP("10.5.6.7")) {
		t.Fatal("10.5.6.7 must be inside 10.0.0.0/8")
	}
	if tp.Contains(net.ParseIP("11.0.0.1")) {
		t.Fatal("11.0.0.1 must NOT be inside trusted set")
	}
	if !tp.Contains(net.ParseIP("2001:db8:cafe::1")) {
		t.Fatal("2001:db8:cafe::1 must be inside 2001:db8::/32")
	}
}

func TestParseTrustedProxiesRejectsMalformed(t *testing.T) {
	if _, err := ParseTrustedProxies("not-a-cidr"); err == nil {
		t.Fatal("expected error on malformed entry")
	}
	if _, err := ParseTrustedProxies("10.0.0.0"); err == nil {
		t.Fatal("expected error on bare IP without mask")
	}
}

// TestDeriveClientIPNoTrustedProxies — XFF is ignored entirely; the
// TCP peer wins. Defends against an attacker setting their own XFF.
func TestDeriveClientIPNoTrustedProxies(t *testing.T) {
	tp, _ := ParseTrustedProxies("")
	got := DeriveClientIP("203.0.113.7, 198.51.100.1", "192.0.2.5", tp)
	if !got.Equal(net.ParseIP("192.0.2.5")) {
		t.Fatalf("expected TCP peer to win, got %v", got)
	}
}

// TestDeriveClientIPSkipsTrusted — walk right-to-left, skip trusted
// hops, return first untrusted.
func TestDeriveClientIPSkipsTrusted(t *testing.T) {
	tp, _ := ParseTrustedProxies("10.0.0.0/8")
	// XFF = "spoofed, real_client, trusted_lb"
	// Trusted CIDR contains 10.x; right-most untrusted is real_client.
	got := DeriveClientIP("198.51.100.99, 203.0.113.42, 10.0.0.1", "10.0.0.1", tp)
	if !got.Equal(net.ParseIP("203.0.113.42")) {
		t.Fatalf("expected right-most untrusted to win, got %v", got)
	}
}

// TestDeriveClientIPMalformedHopSkipped — a junk hop in XFF must not
// crash; the walk continues to the next (right-to-left) entry.
func TestDeriveClientIPMalformedHopSkipped(t *testing.T) {
	tp, _ := ParseTrustedProxies("10.0.0.0/8")
	got := DeriveClientIP("203.0.113.42, garbage, 10.0.0.1", "10.0.0.1", tp)
	if !got.Equal(net.ParseIP("203.0.113.42")) {
		t.Fatalf("expected 203.0.113.42 (skipping junk), got %v", got)
	}
}

// TestDeriveClientIPAllTrustedFallsBackToPeer — if every hop is in
// the trusted set, we fall back to the TCP peer.
func TestDeriveClientIPAllTrustedFallsBackToPeer(t *testing.T) {
	tp, _ := ParseTrustedProxies("10.0.0.0/8")
	got := DeriveClientIP("10.0.0.5, 10.0.0.6", "10.0.0.6", tp)
	if !got.Equal(net.ParseIP("10.0.0.6")) {
		t.Fatalf("expected TCP peer fallback, got %v", got)
	}
}

// TestSubjectKeyIPv4Default — /32 makes each address its own bucket.
func TestSubjectKeyIPv4Default(t *testing.T) {
	a := SubjectKey(net.ParseIP("203.0.113.7"), 32, 64)
	b := SubjectKey(net.ParseIP("203.0.113.8"), 32, 64)
	if a == b {
		t.Fatalf("/32 must give distinct buckets, got %s == %s", a, b)
	}
	if a != "203.0.113.7/32" {
		t.Fatalf("unexpected canonical form: %s", a)
	}
}

// TestSubjectKeyIPv6PrefixCollapse — the binding §7.6 anti-spray
// invariant: two addresses inside one /64 collapse to ONE bucket.
// This is the test the design doc explicitly calls out.
func TestSubjectKeyIPv6PrefixCollapse(t *testing.T) {
	a := SubjectKey(net.ParseIP("2001:db8::1"), 32, 64)
	b := SubjectKey(net.ParseIP("2001:db8::ffff"), 32, 64)
	if a != b {
		t.Fatalf("/64 collapse failed: %s != %s", a, b)
	}
	if a != "2001:db8::/64" {
		t.Fatalf("unexpected canonical form: %s", a)
	}
}

// TestSubjectKeyIPv6DifferentSubnetsDoNotCollide — the inverse: two
// addresses outside the /64 must NOT collide.
func TestSubjectKeyIPv6DifferentSubnetsDoNotCollide(t *testing.T) {
	a := SubjectKey(net.ParseIP("2001:db8:1::1"), 32, 64)
	b := SubjectKey(net.ParseIP("2001:db8:2::1"), 32, 64)
	if a == b {
		t.Fatalf("different /64s collapsed: %s == %s", a, b)
	}
}

// TestSubjectKeyOutOfRangePrefixClampsToFamilyDefault — caller
// misconfig must NOT crash; we clamp to /32 (v4) or /64 (v6).
func TestSubjectKeyOutOfRangePrefixClampsToFamilyDefault(t *testing.T) {
	got := SubjectKey(net.ParseIP("203.0.113.7"), 99, 99)
	if got != "203.0.113.7/32" {
		t.Fatalf("v4 clamp failed: %s", got)
	}
	got = SubjectKey(net.ParseIP("2001:db8::1"), 0, 0)
	if got != "2001:db8::/64" {
		t.Fatalf("v6 clamp failed: %s", got)
	}
}

func TestSubjectKeyNilIP(t *testing.T) {
	if SubjectKey(nil, 32, 64) != "" {
		t.Fatal("nil IP must return empty string")
	}
}

// TestSubjectKeyIPv6_64Collapse is the proof test for §9.14
// test_subject_key_ipv6_64_collapse: two IPv6 addresses that share
// the same /64 prefix must collapse to ONE rate bucket; two addresses
// in different /64 prefixes must produce distinct bucket keys.
func TestSubjectKeyIPv6_64Collapse(t *testing.T) {
	// Same /64: 2001:db8:aabb:ccdd::/64 — host parts differ.
	sameA := SubjectKey(net.ParseIP("2001:db8:aabb:ccdd:1111:2222:3333:4444"), 32, 64)
	sameB := SubjectKey(net.ParseIP("2001:db8:aabb:ccdd:eeee:ffff:0000:0001"), 32, 64)
	if sameA != sameB {
		t.Fatalf("same /64 must collapse to one bucket: %s != %s", sameA, sameB)
	}
	want := "2001:db8:aabb:ccdd::/64"
	if sameA != want {
		t.Fatalf("unexpected canonical bucket key: got %s, want %s", sameA, want)
	}

	// Different /64: third quad differs (ccdd vs eeff).
	diffA := SubjectKey(net.ParseIP("2001:db8:aabb:ccdd::1"), 32, 64)
	diffB := SubjectKey(net.ParseIP("2001:db8:aabb:eeff::1"), 32, 64)
	if diffA == diffB {
		t.Fatalf("different /64 prefixes must not share a bucket: both gave %s", diffA)
	}
}
