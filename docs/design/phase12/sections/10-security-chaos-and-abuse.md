# Phase 12.10 — Security chaos & abuse

> Binding per-section detail for Phase 12 §12.10. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A6 (adversarial = only prompt injection). **Depends
> on:** §12.2, §12.4, §12.5. Targets the threat model in
> [`SECURITY.md`](../../SECURITY.md); asserts the Phase 7 sec plane,
> Phase 9 identity, and Phase 8 operator controls under attack.

### 12.10 Attack the security controls themselves

The sec plane (Phase 7), identity (Phase 9), and operator controls
(Phase 8) are the system's defenses. Phase 12 attacks **them** — not
just the business endpoints — to prove the defenses hold and fail
safely.

### 12.10.1 Input-abuse scenarios (binding)

- [ ] **`chaos.prompt-injection`** — replay the §12.2
      `prompt_injection/` corpus (TR + EN) through the gateway → NLP;
      assert **100 % block / route-to-`meta.adversarial`**, humanizer-
      bypassed fixed phrasing, and a defense-in-depth secondary probe
      (Phase 10 §10.15). Zero `xfail` (§12.0 A9). This is the original
      stub's `test_qa_resists_ignore_previous_instructions`, promoted to
      a corpus-driven gate.
- [ ] **`chaos.homoglyph-rtl-flood`** — Cyrillic/Greek confusables,
      RTL-flip, zero-width, mojibake, bidi-control payloads; assert the
      confusables fold (Phase 10 §10.21.5/§10.33) normalises before the
      classifier and the bidi/Cf strip fires, never a silent bypass.
- [ ] **`chaos.oversize-zerowidth`** — oversized + zero-width-padded
      Turkish queries; assert the **byte** length cap (not codepoint)
      holds before sanitize (Phase 7 P12-7.1-A), so a multi-byte
      grapheme can't smuggle past.
- [ ] **`chaos.slur-obfuscation`** — the Phase 10 §10.30.10 obfuscated-
      slur corpus (≥ 99 % detection, ≤ 1 % FP); assert detection after
      confusables-fold + PII-redaction, with the legitimate-text
      negation guard intact.

### 12.10.2 Rate / identity abuse (binding)

- [ ] **`chaos.credential-stuffing`** — burst `/v1/auth/*` from one and
      many subjects; assert pre-auth caps (Phase 7 P12-7.3-A) hold,
      bcrypt-bound login latency budget (Phase 9 §9.17.5) is respected,
      and denylist escalation engages — never a silent bypass.
- [ ] **`chaos.xff-spoof`** — spoofed `X-Forwarded-For` from an
      untrusted peer; assert the trusted-proxy gate (Phase 7 P12-7.3-C)
      ignores it and buckets on the real peer; IPv6 /64 prefix bucketing
      defeats end-site spraying.
- [ ] **`chaos.redis-fail-open`** — kill Redis under rate-limit load;
      assert fail-open to per-process secondary buckets (Phase 7
      P12-7.3-H) with `rate_redis_unreachable` (error) — the system
      never silently *removes* rate limiting, and never hard-fails the
      user.
- [ ] **`chaos.token-replay`** — replay a single-use refresh token + a
      revoked operator key past its grace (Phase 8 P12-8-Z, Phase 9
      §9.2 JTI deny-set); assert rejection with the documented reason +
      exit code.

### 12.10.3 Credential / cert lifecycle chaos (binding)

- [ ] **`chaos.cert-expiry`** — present an mTLS cert with < 7 days
      remaining / expired (Phase 9 §9.2 refuse-boot ≥ 7 d); assert the
      agent refuses to start / refuses the connection rather than
      serving on an expired chain.
- [ ] **`chaos.key-rotation-midflight`** — rotate an HMAC/signing key
      (citation, answer-envelope, opsctl, lexicon-feed) **during** an
      in-flight request stream; assert the dual-acceptance window (24 h,
      Phase 10 §10.21.8 / §10.26.8 / Phase 8 §8.14.4) means **zero**
      false rejects during the window and correct rejection after it.
- [ ] **`chaos.secret-unreadable`** — make a `mode 0400` key path
      unreadable mid-run; assert fail-safe (refuse + critical alert),
      never a silent downgrade to unsigned.

### 12.10.4 Supply-chain chaos (binding)

- [ ] **`chaos.tampered-binary`** — swap the `age` binary / an engine
      cache / an image to an unsigned substitute (Phase 8 P12-8-V,
      Phase 11 §11.7 cosign admission, §11.11 engine HMAC); assert the
      SHA/signature gate refuses to start or refuses the artifact.
- [ ] **`chaos.cve-injection`** — pin a known-vulnerable dependency in a
      throwaway lock; assert the daily CVE scan (Phase 10 §10.23.12 /
      §11.11 SBOM) flags CRITICAL/HIGH and the gate blocks promotion.

### 12.10.5 Make targets & gates

- [x] `make chaos.prompt-injection`, `make chaos.homoglyph-rtl-flood`,
      `make chaos.oversize-zerowidth`, `make chaos.slur-obfuscation`,
      `make chaos.credential-stuffing`, `make chaos.xff-spoof`,
      `make chaos.redis-fail-open`, `make chaos.token-replay`,
      `make chaos.cert-expiry`, `make chaos.key-rotation-midflight`,
      `make chaos.secret-unreadable`, `make chaos.tampered-binary`,
      `make chaos.cve-injection` — dispatched via `xops/makefile/chaos.py`
      (test scenarios stubbed pending CI harness). Gateway
      (`make verify.security-coverage`) validates test coverage.
- [ ] The §12.14 scorecard's **undetected-attack count must be zero**
      for every shipped security surface; a single missed injection /
      spoof / forgery blocks the release gate (§12.17).
