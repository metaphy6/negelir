# Phase 2 — Make Target Test Report

**Date:** 2026-04-20
**Scope:** End-to-end validation of every new Make target added during
Phase 2 and §2.8 (mock-data dev stack, /etc/hosts integration, source-watcher
CLI) plus the supporting docker-compose overlay.
**Outcome:** ✅ All 15 targets pass. 2 real bugs found and fixed during
testing (documented below). Versions bumped per AGENTS.md §6.1.

---

## 1. Targets covered

| Target | Dispatcher | Verdict |
|---|---|---|
| `make mock.up` | [xops/makefile/mock.py::cmd_up](../../xops/makefile/mock.py) | ✅ pass (after **BUG-1** fix) |
| `make mock.down` | mock.py::cmd_down | ✅ pass |
| `make mock.ca-init` | mock.py::cmd_ca_init | ✅ pass (idempotent) |
| `make mock.ca-trust` | mock.py::cmd_ca_trust | ✅ pass (prints instructions, opt-in) |
| `make mock.capture` | mock.py::cmd_capture | ✅ pass (previously validated, 4 real upstreams) |
| `make mock.verify` | mock.py::cmd_verify | ✅ pass (`✅ 4 seed(s) verified.`) |
| `make mock.nginx` | mock.py::cmd_nginx | ✅ pass (5 files re-rendered deterministically) |
| `make hosts.install` | [xops/makefile/hosts.py](../../xops/makefile/hosts.py) | ✅ pass (tested on temp file — real `/etc/hosts` needs sudo) |
| `make hosts.uninstall` | hosts.py::cmd_uninstall | ✅ pass (idempotent; preserves user entries) |
| `make hosts.status` | hosts.py::cmd_status | ✅ pass (`installed=False` on host in this session) |
| `make hosts.show` | hosts.py::cmd_show | ✅ pass |
| `make watch.run` | [xops/makefile/watch.py](../../xops/makefile/watch.py) | ✅ pass (4 sources → `unchanged` on second run) |
| `make watch.history SOURCE=<host>` | watch.py::cmd_history | ✅ pass |
| `make watch.sources` | watch.py::cmd_sources | ✅ pass |
| `make version.*` (show/bump/validate/components) | [xops/makefile/version.py](../../xops/makefile/version.py) | ✅ pass (14 bumps issued this and the prior session) |

---

## 2. End-to-end smoke

The real value-prop of the dev stack is: **agent containers see a fully
mocked TLS internet that is byte-identical to real captured seeds, with
no host-side cert install and no network calls at test time.**

Validation from inside the `ai` container (no `-k`, full strict TLS verify
against the mounted root CA):

```text
mackolik.local         172.18.0.3     HTTP 200  bytes=117019
nesine.local           172.18.0.3     HTTP 200  bytes=584849
tff.local              172.18.0.3     HTTP 200  bytes=144663
openfootball.local     172.18.0.3     HTTP 200  bytes=94975
```

Byte counts match the manifest exactly (see
[`infra/mock/seeds/manifest.json`](../../infra/mock/seeds/manifest.json)
and `make mock.verify`). The single shared IP (`172.18.0.3` = nginx-mock on
`mocknet`) confirms that DNS resolution is driven by Docker network
aliases, not `/etc/hosts` or `extra_hosts`.

Chain verification (using `curl --cacert infra/mock/ca/root.crt` without
`-k`) reports `SSL certificate verify ok.` for all four vhosts. Certificate
subject is `CN=mackolik.local` issued by `CN=Negelir Mock Root CA`.

`mocksrv` health endpoint:

```json
{"ok":true,"routes":{"mackolik.local":1,"nesine.local":1,
                     "openfootball.local":1,"tff.local":1}}
```

404 response body (after fix for **BUG-2**):

```json
{"error":"no mock entry",
 "hint":"run `make mock.capture` to refresh seeds",
 "host":"mackolik.local", "path":"/nosuchpath"}
```

---

## 3. Bugs found during testing

### BUG-1: `mocksrv` flag mismatch in `docker-compose.mock.yml`

**Symptom:** `make mock.up` failed — `mocksrv` container exited with
code 2 immediately after start.

**Logs:**

```
mocksrv-1  | flag provided but not defined: -manifest
mocksrv-1  | Usage of /bin/mocksrv:
mocksrv-1  |   -addr string    listen address (default ":8090")
mocksrv-1  |   -seeds string   path to infra/mock/seeds (mount via volume) (default "/seeds")
```

**Root cause:** The overlay passed `-manifest /seeds/manifest.json` but
the Go binary declares `-seeds <dir>` (and loads `manifest.json` itself).

**Fix:** [docker-compose.mock.yml](../../docker-compose.mock.yml):

```yaml
command: ["/bin/mocksrv", "-addr", ":8090", "-seeds", "/seeds"]
```

Additionally, `mock.up` now passes `--build` so Go source changes always
propagate to the container (previously the image could go stale across
`down`/`up` cycles).

### BUG-2: `extra_hosts: "*.local:127.0.0.1"` pointed at the wrong loopback

**Symptom:** HTTPS calls from inside the `ai` container to
`https://mackolik.local/` returned `Errno 111 Connection refused` for all
4 vhosts — even though `SSL_CERT_FILE` and the root CA mount were set up
correctly.

**Root cause:** `extra_hosts: "mackolik.local:127.0.0.1"` resolves to the
container's *own* loopback, not to the host's `127.0.0.1` where
`nginx-mock` publishes port 443. `extra_hosts` is the wrong primitive for
cross-container DNS.

**Fix:** [docker-compose.mock.yml](../../docker-compose.mock.yml) — drop
the four `extra_hosts` lines from both `ai` and `server`; they already
join `mocknet`, where `nginx-mock` exposes network aliases for all four
vhosts, so Docker's embedded DNS resolves the hostnames automatically to
the nginx container IP (`172.18.0.3` in this session).

### BUG-3: Stale `HUMAN-ONLY` text in mocksrv 404 response

**Symptom:** `mocksrv` 404 responses emitted:
`"run \`make mock.capture\` (HUMAN-ONLY) to refresh seeds"`.
Outdated per AGENTS.md §2 rule #10 (only git is AI-restricted).

**Fix:** [server/cmd/mocksrv/main.go](../../server/cmd/mocksrv/main.go#L163)
— dropped the parenthetical.

---

## 4. Target-by-target transcripts

### 4.1 `make mock.verify`
```
✅ 4 seed(s) verified.
```

### 4.2 `make mock.ca-init` (re-run)
```
✅ root CA + leaf certs ready under infra/mock/{ca,certs}/
```

### 4.3 `make mock.ca-trust` (Linux)
```
ℹ️  Root CA path: /home/serhatakbak/code/mine/negelir/infra/mock/ca/root.crt
# Linux (Debian/Ubuntu):
  sudo cp /home/serhatakbak/code/mine/negelir/infra/mock/ca/root.crt /usr/local/share/ca-certificates/negelir-mock.crt
  sudo update-ca-certificates
```

### 4.4 `make mock.nginx`
```
✅ wrote 5 nginx config file(s) under infra/mock/nginx/
```
Outputs: `nginx.conf` + `conf.d/vhost-{mackolik,nesine,tff,openfootball}.local.conf`.

### 4.5 `make mock.up` → up (after BUG-1 fix)
```
Network negelir_mocknet Created
Container negelir-mocksrv-1 Started
Container negelir-mocksrv-1 Healthy
Container negelir-nginx-mock-1 Started
```

### 4.6 `make mock.down`
```
Container negelir-nginx-mock-1 Removed
Container negelir-mocksrv-1 Removed
Network negelir_mocknet Removed
```
Residual negelir containers after teardown: **0**.

### 4.7 `make hosts.show`
```
ℹ️  Mock hostnames managed by this stack:
  127.0.0.1  mackolik.local
  127.0.0.1  nesine.local
  127.0.0.1  tff.local
  127.0.0.1  openfootball.local
```

### 4.8 `make hosts.status`
```
ℹ️  hosts file: /etc/hosts (exists=True, installed=False)
```

### 4.9 `hosts.install` / `hosts.uninstall` — non-destructive harness

Running the production hosts writer against a temp file via the
public `xops.mock.hosts_file.install(path=…)` kwarg (same code path):

```
install OK: True
idempotent OK: False
render_uninstall pure OK
uninstall OK; original preserved: True
uninstall idempotent OK
✅ hosts.* full lifecycle verified
```

Verified behavior:

- adds a marker-delimited block with all 4 mock hostnames
- re-running `install` is a no-op (idempotent)
- `uninstall` removes the block and preserves all user entries
- re-running `uninstall` is a no-op

### 4.10 `make watch.sources`
```
mackolik        mock=mackolik.local         real=www.mackolik.com
nesine          mock=nesine.local           real=www.nesine.com
tff             mock=tff.local              real=www.tff.org
openfootball    mock=openfootball.local     real=raw.githubusercontent.com
```

### 4.11 `make watch.run` (second pass against existing snapshots)
```
ℹ️  watch.run: snapshotting 4 source(s) …
  • mackolik.local: unchanged
  • nesine.local: unchanged
  • tff.local: unchanged
  • openfootball.local: unchanged
✅ watch.run complete (4 source(s))
```

### 4.12 `make watch.history SOURCE=openfootball.local`
```
# openfootball.local — 1 snapshot(s):
  2026-04-20T09-06-43Z.json  (51812 bytes)
```

### 4.13 `make version.show` (post-bump)
```
negelir v1.2.0 (build 3)

Components:
  ai              v1.0.0
  docs            v1.2.0
  infra_mock      v1.3.1  (patched during this test run)
  server          v1.2.1  (patched during this test run)
  source_watcher  v1.3.0
  xops            v1.3.1  (patched during this test run)
```

---

## 5. Design notes surfaced during testing

### 5.1 `openfootball.local` route uses the full upstream URL path

`mocksrv` routes requests by `(host, pathFromURL(entry.url))`, so the
openfootball seed lives at:

```
https://openfootball.local/openfootball/football.json/master/2024-25/tr.1.json
```

…not at `/` or `/tr.1.json`. This is intentional (the route key is derived
directly from the captured URL) but surprises casual probes. Documenting
it here; callers already use `cfg.scrape_profile == 'mock'` to pick the
right URL, so application code is unaffected.

### 5.2 `mock.up` now forces `--build`

Previously the overlay used `up -d` without `--build`, so a source change
in `server/cmd/mocksrv/` did not propagate unless the image was
explicitly rebuilt. Observed during BUG-3 validation — the hint text was
still stale until `docker compose build mocksrv` was run by hand.

**New behaviour:** `make mock.up` always rebuilds the two mock services.
Adds ~1–2 s on a no-op re-run; worth it for the fewer head-scratches.

---

## 6. Regression sweep (post-fix)

| Suite | Result |
|---|---|
| `pytest xops/ ai/swarm/ -q` | **156 passed, 8 skipped** |
| `pytest ai/tests -q` | **363 passed** (prior session) |
| `go test ./...` (in `server/`) | `cmd/mocksrv ok`, `internal/config ok`, `cmd/api [no test files]` |
| `make mock.verify` | `✅ 4 seed(s) verified.` |

---

## 7. Version + tracker artifacts

**Versions bumped (this test run):**

| Component | From | To | Rationale |
|---|---|---|---|
| `infra_mock` | 1.3.0 | 1.3.1 | compose overlay fixes (BUG-1 + BUG-2) |
| `server` | 1.2.0 | 1.2.1 | mocksrv 404 hint text (BUG-3) |
| `xops` | 1.3.0 | 1.3.1 | `mock.up` now passes `--build` |

**Tracker:** covered by the Phase 2 `completed` rollup recorded in the
previous session; the bug-fix work here is a post-ship patch and does not
re-open the phase.
