# Security Exceptions

This registry is the operator-audited source of truth for sensitive replay
exceptions and other narrowly-scoped security carve-outs.

## DLQ Replay Policy Overrides

Every topic listed here must also appear in NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES.
CI verifies parity with make verify.dlq-replay-policy.

| topic | reason | responsible_agent | phase12_stub | sign_off |
| --- | --- | --- | --- | --- |

Sign-off note: add one row per override before enabling it; use a stable
agent id in responsible_agent and a concrete Phase 12 stub identifier in
phase12_stub.
