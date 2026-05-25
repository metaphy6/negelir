# Phase 11.45 — Model weight encryption-at-rest & secure unseal

> Extracted from `docs/planning/ROADMAP.md` §11.45
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.45 Model weight encryption-at-rest & secure unseal

> **Why this exists.** Fine-tuned bundles encode commercial IP and
> tenant-specific behaviour. A bundle leaving the host unencrypted
> (cache volume snapshot, debug dump, accidental log) is exfiltration.
> Wrong-assumption #22 retired. Applies only to bundles whose manifest
> declares `confidentiality=restricted`; public model bundles stay
> plaintext for cold-start speed.

- [ ] **At-rest encryption.** Restricted bundles are AES-256-GCM encrypted in the §11.15 object store and on the §11.15 local cache disk; key wrapping uses an envelope-encrypted KEK fetched from `cfg.compute_bundle_kms_url` (e.g. AWS KMS / GCP KMS / HashiCorp Vault — selection per CSP profile, never embedded). The cache file format is `{nonce, aad: bundle_sha256 + host_class, ciphertext, tag}`.
- [ ] **Tmpfs-only unseal.** Decryption happens once at load time into a tmpfs mount (`cfg.compute_bundle_unseal_tmpfs`, `noexec`, `nodev`, `nosuid`); the plaintext is `mmap`'d into the inference process and the tmpfs file is `unlink`'d immediately so a snapshot never captures plaintext. Tested via `proof_no_plaintext_bundle_on_disk`.
- [ ] **No swap.** The supervisor refuses to start with `confidentiality=restricted` agents when host swap is enabled and not explicitly disabled-for-this-mount (`cfg.compute_bundle_unseal_require_no_swap=true`); plaintext weight pages must not hit a swap partition. Visible in the §11.44 not-ready reasons if violated.
- [ ] **Telemetry redaction.** §11.9 autopsy / §11.28 tail-capture refuse to dump the address range of an `mmap`'d restricted bundle even on Xid crash; only metadata (sha256, dtype, dim) is captured. Lint refuses a capture sink without this rule.
- [ ] **Key rotation drill.** `make compute.kek.rotate` rewraps every restricted bundle in the object store under a new KEK without rebuilding the bundles; existing local caches re-fetch on next load. Tested.
- [ ] **Audit.** Every unseal emits `sec.audit.v1{kind=bundle_unseal, sha256, host, kms_key_id, tenant_id?}` (Phase 11.39 `data_class=tenant_internal` minimum); every refusal emits `sec.alert.v1{kind=bundle_unseal_refused, reason}`.
