---
description: Go server / mocksrv conventions (server/**)
applyTo: 'server/**/*.go'
---

# Go (`server/**`) — stack-specific tips

Doctrine lives in [`AGENTS.md`](../../AGENTS.md). This file only adds
the Go-specific bits.

## Run modes

- One binary, two modes selected by `MODE` env:
  - `MODE=api` — public REST API (Gin).
  - `MODE=mocksrv` — local mock upstream used by Phase 2 tests.
- Never branch on the mode outside the entry-point wiring; routes
  and handlers are mode-agnostic.

## Config

- All tunables go through `server/internal/config` and are
  documented in `xops/env/.env.example`. No `os.Getenv` scattered
  through handlers.
- Go config layer mirrors `ai/common/config.py` patterns
  (`AGENTS.md` §6, Rule 1).

## Tests

- Run with `go test ./...` from `server/` or via `make test`.
- Prefer table tests (`tests := []struct{...}{ ... }; for _, tc := …`).
- Integration tests use `mocksrv` (never real upstreams), aligned
  with `AGENTS.md` §5 mock-data discipline.
- **Rule 10 — tests track code.** New handler / package surface
  → new `_test.go` cases. Bug fix → regression case in the
  matching `_test.go`. Refactor / rename / signature change →
  update every affected test in the same diff. Never weaken or
  skip a test to make `go test ./...` green.

## Concurrency

- Background goroutines must have an explicit lifecycle owner
  (parent context + cancel). No fire-and-forget goroutines in
  request handlers.
- Use `context.Context` consistently; the first parameter on any
  function that does I/O.
- State lives in Redis / Postgres, never in process memory
  (`AGENTS.md` Rule 5 — scale symmetry).

## Forbidden surfaces

- `server/internal/auth/`, `server/internal/payment/`, and any
  `*/crypto/` package are **AI-forbidden** unless the human
  request names the file (per `.github/copilot-instructions.md`).

## Style

- `gofmt` + `goimports`; group imports stdlib / third-party / local.
- Errors wrap with `fmt.Errorf("…: %w", err)`; never swallow.
- Log at module level via the project logger; never `log.Println`.
