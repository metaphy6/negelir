package auth_test

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/metaphy6/negelir/server/internal/auth"
)

type memRedis struct {
	mu   sync.Mutex
	data map[string]string
}

func newMemRedis() *memRedis { return &memRedis{data: make(map[string]string)} }

func (r *memRedis) Set(_ context.Context, key, value string, _ time.Duration) error {
	r.mu.Lock(); r.data[key] = value; r.mu.Unlock(); return nil
}
func (r *memRedis) Get(_ context.Context, key string) (string, error) {
	r.mu.Lock(); v := r.data[key]; r.mu.Unlock(); return v, nil
}
func (r *memRedis) GetDel(_ context.Context, key string) (string, error) {
	r.mu.Lock(); v := r.data[key]; delete(r.data, key); r.mu.Unlock(); return v, nil
}
func (r *memRedis) Del(_ context.Context, key string) error {
	r.mu.Lock(); delete(r.data, key); r.mu.Unlock(); return nil
}

func newStore(t *testing.T) (*auth.RefreshStore, *memRedis) {
	t.Helper()
	r := newMemRedis()
	s := auth.NewRefreshStore(r, 30*24*time.Hour, 30*time.Second)
	return s, r
}

func TestRefreshIssue_ReturnsNonEmptyToken(t *testing.T) {
	s, _ := newStore(t)
	ctx := context.Background()
	token, err := s.Issue(ctx, "user-1", "read write")
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}
	if token == "" {
		t.Fatal("Issue returned empty token")
	}
	val, hint, err := s.Validate(ctx, token)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if hint != "" {
		t.Errorf("unexpected hint %q for active token", hint)
	}
	if val == "" {
		t.Error("Validate returned empty value for active token")
	}
}

func TestRefreshIssue_UniqueTokens(t *testing.T) {
	s, _ := newStore(t)
	ctx := context.Background()
	t1, _ := s.Issue(ctx, "u", "r")
	t2, _ := s.Issue(ctx, "u", "r")
	if t1 == t2 {
		t.Error("Issue produced identical tokens on two calls")
	}
}

func TestRefreshRotate_HappyPath(t *testing.T) {
	s, _ := newStore(t)
	ctx := context.Background()
	old, _ := s.Issue(ctx, "user-2", "read")
	newTok, err := s.Rotate(ctx, old)
	if err != nil {
		t.Fatalf("Rotate: %v", err)
	}
	if newTok == "" || newTok == old {
		t.Errorf("want fresh non-empty token, got %q", newTok)
	}
	val, _, err := s.Validate(ctx, newTok)
	if err != nil {
		t.Fatalf("Validate new token: %v", err)
	}
	if val == "" {
		t.Error("Validate new token: empty value")
	}
}

func TestRefreshRotate_WithinGrace(t *testing.T) {
	s, _ := newStore(t)
	ctx := context.Background()
	old, _ := s.Issue(ctx, "user-3", "read")
	_, err := s.Rotate(ctx, old)
	if err != nil {
		t.Fatalf("Rotate: %v", err)
	}
	_, hint, err := s.Validate(ctx, old)
	if err == nil || !errors.Is(err, auth.ErrTokenReplay) {
		t.Errorf("within grace: want ErrTokenReplay, got %v", err)
	}
	if hint == "" {
		t.Error("within grace: expected non-empty newKeyHint")
	}
}

func TestRefreshRotate_OutsideGrace(t *testing.T) {
	s, r := newStore(t)
	ctx := context.Background()
	old, _ := s.Issue(ctx, "user-4", "read")
	_, err := s.Rotate(ctx, old)
	if err != nil {
		t.Fatalf("Rotate: %v", err)
	}
	r.mu.Lock()
	for k := range r.data {
		if len(k) > 17 && k[:18] == "auth:refresh:prev:" {
			delete(r.data, k)
		}
	}
	r.mu.Unlock()
	_, _, err = s.Validate(ctx, old)
	if err == nil || !errors.Is(err, auth.ErrTokenRevoked) {
		t.Errorf("outside grace: want ErrTokenRevoked, got %v", err)
	}
}

func TestRefreshRevoke_LogoutInvalidates(t *testing.T) {
	s, _ := newStore(t)
	ctx := context.Background()
	tok, _ := s.Issue(ctx, "user-5", "read")
	if err := s.Revoke(ctx, tok); err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	_, _, err := s.Validate(ctx, tok)
	if err == nil || !errors.Is(err, auth.ErrTokenRevoked) {
		t.Errorf("after revoke: want ErrTokenRevoked, got %v", err)
	}
}

func TestRefreshValidate_UnknownToken(t *testing.T) {
	s, _ := newStore(t)
	_, _, err := s.Validate(context.Background(), "completely-unknown-token")
	if err == nil || !errors.Is(err, auth.ErrTokenRevoked) {
		t.Errorf("unknown: want ErrTokenRevoked, got %v", err)
	}
}

func TestRefreshRotate_UnknownToken(t *testing.T) {
	s, _ := newStore(t)
	_, err := s.Rotate(context.Background(), "no-such-token")
	if err == nil || !errors.Is(err, auth.ErrTokenRevoked) {
		t.Errorf("rotate unknown: want ErrTokenRevoked, got %v", err)
	}
}
