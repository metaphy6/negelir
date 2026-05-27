#!/usr/bin/env python3
"""`make api.*` — Phase 9 REST API dispatchers.

Targets:
    up                  docker compose up -d api
    down                docker compose down api
    build               build the Go server binary (MODE=api)
    gen                 regenerate handlers from server/api/openapi.yaml (oapi-codegen)
    gen-check           CI gate: regenerate into tmpdir, assert no diff
    docs                serve Swagger UI on localhost:8081 (profile=docs)
    rotate-jwt-key      generate new JWT keypair and rotate atomically
    revoke-jti          add a JTI to the Redis revocation deny-set
    tls-rotate          renew mTLS service certs from Phase 2 internal CA
    rotate-cursor-key   rotate the AES-GCM cursor seal key
    bump-bcrypt-cost    bump NEGELIR_API_BCRYPT_COST and trigger rolling re-hash
    erase-user          GDPR right-to-erasure: purge user row + audit null-stamp
    slo-report          28-day rolling SLO summary (Phase 19 GA gate input)

Most targets are stubs pending Phase 9 Go implementation. They print a clear
"not yet implemented" message with the section reference so the build never
silently succeeds on an unimplemented path.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import COMPOSE, ENV_FILE, dispatch, info, ok, warn  # noqa: E402


# ── helpers ───────────────────────────────────────────────────


def _api_compose_base() -> str:
    """Return docker compose invocation string for the api service."""
    parts = list(COMPOSE)
    if ENV_FILE.is_file():
        parts += ["--env-file", str(ENV_FILE)]
    parts += ["-f", "docker-compose.yml"]
    return " ".join(parts)


def _not_yet(target: str, section: str) -> int:
    warn(
        f"make api.{target}: not yet implemented "
        f"(pending Phase 9 §{section} Go implementation). "
        "Run `make track.list` for current progress."
    )
    return 1


# ── commands ──────────────────────────────────────────────────


def cmd_up(_argv: List[str]) -> int:
    """Bring up the API compose service."""
    base = _api_compose_base()
    cmd = f"{base} up -d api"
    info(cmd)
    rc = os.system(cmd)
    return 0 if rc == 0 else 1


def cmd_down(_argv: List[str]) -> int:
    """Stop and remove the API compose service."""
    base = _api_compose_base()
    cmd = f"{base} stop api"
    info(cmd)
    rc = os.system(cmd)
    return 0 if rc == 0 else 1


def cmd_build(_argv: List[str]) -> int:
    """Build the Go server binary (MODE=api)."""
    info("go build -tags cpu_only -o bin/api ./server/cmd/api")
    rc = os.system(
        "cd "
        + str(REPO_ROOT)
        + " && go build -tags cpu_only -o bin/api ./server/cmd/api"
    )
    return 0 if rc == 0 else 1


def cmd_gen(_argv: List[str]) -> int:
    """Regenerate server/internal/apigen/api.gen.go from server/api/openapi.yaml.

    Runs oapi-codegen v2.3.0 via `go run` (no host install required).
    Output path is resolved from server/api/oapi-codegen.yaml (output:
    ../internal/apigen/api.gen.go), so we must cd into server/api/ before
    invoking the tool.
    """
    spec_dir = REPO_ROOT / "server" / "api"
    if not (spec_dir / "openapi.yaml").is_file():
        warn("server/api/openapi.yaml not found — cannot generate")
        return 1
    if not (spec_dir / "oapi-codegen.yaml").is_file():
        warn("server/api/oapi-codegen.yaml not found — cannot generate")
        return 1

    # Run from server/api/ so the relative output path in oapi-codegen.yaml
    # resolves correctly (../internal/apigen/api.gen.go).
    tool = "github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.3.0"
    cmd = (
        f"cd {spec_dir} && "
        f"go run {tool} --config oapi-codegen.yaml openapi.yaml"
    )
    info(cmd)
    rc = os.system(cmd)
    if rc != 0:
        warn("oapi-codegen failed — check server/api/openapi.yaml for errors")
        return 1
    info("Generated server/internal/apigen/api.gen.go")
    return 0


def _validate_spec_extensions(spec_path: "Path") -> "List[str]":
    """Return a list of violation strings (empty list = all OK).

    Checks that every HTTP operation in the OpenAPI YAML carries the three
    required Phase 9 extensions: x-rate-cost, x-tier-required,
    x-idempotent-mutation.  Pure stdlib — no PyYAML required.

    The parser assumes the spec uses consistent 2-space path / 4-space method /
    6-space field indentation, which is enforced by the project's YAML style.
    """
    import re as _re

    _REQUIRED = {"x-rate-cost", "x-tier-required", "x-idempotent-mutation"}
    _METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
    _path_re = _re.compile(r"^  (/\S+):\s*$")
    _method_re = _re.compile(r"^    (" + "|".join(_METHODS) + r"):\s*$")
    _ext_re = _re.compile(r"^      (x-[\w-]+):")

    violations: "List[str]" = []
    current_path: "List[str | None]" = [None]
    current_method: "List[str | None]" = [None]
    op_exts: "List[set]" = [set()]

    def _flush() -> None:
        if current_path[0] and current_method[0]:
            missing = sorted(_REQUIRED - op_exts[0])
            if missing:
                violations.append(
                    f"{current_method[0].upper()} {current_path[0]}: "
                    f"missing required extension(s): {missing}"
                )

    for line in spec_path.read_text().splitlines():
        pm = _path_re.match(line)
        if pm:
            _flush()
            current_path[0] = pm.group(1)
            current_method[0] = None
            op_exts[0] = set()
            continue
        mm = _method_re.match(line)
        if mm:
            _flush()
            current_method[0] = mm.group(1)
            op_exts[0] = set()
            continue
        em = _ext_re.match(line)
        if em and current_method[0]:
            op_exts[0].add(em.group(1).strip())

    _flush()  # flush the final operation
    return violations


def cmd_gen_check(_argv: List[str]) -> int:
    """CI gate: validate OpenAPI extensions, then assert no handler drift.

    Step 1 — Extension check (pure Python, fast):
      Verifies every operation in server/api/openapi.yaml carries all three
      required Phase 9 extensions: x-rate-cost, x-tier-required,
      x-idempotent-mutation.  Fails immediately if any are missing.

    Step 2 — Handler drift check (requires Go):
      Regenerates server/internal/apigen/api.gen.go into a tmp directory and
      compares it against the committed file. Exits non-zero on any drift,
      which fails the CI build. This ensures the committed generated types always
      match the OpenAPI spec.
    """
    import re
    import shutil
    import tempfile

    spec_dir = REPO_ROOT / "server" / "api"
    spec_yaml = spec_dir / "openapi.yaml"
    committed = REPO_ROOT / "server" / "internal" / "apigen" / "api.gen.go"

    # ── Step 1: extension check (pure Python, no Go required) ───────────────
    if not spec_yaml.is_file():
        warn("server/api/openapi.yaml not found — cannot validate extensions")
        return 1
    ext_violations = _validate_spec_extensions(spec_yaml)
    if ext_violations:
        warn(
            f"Extension check FAILED — {len(ext_violations)} route(s) missing "
            "required Phase 9 extensions (x-rate-cost, x-tier-required, "
            "x-idempotent-mutation):"
        )
        for v in ext_violations:
            warn(f"  {v}")
        return 1
    info(
        f"Extension check passed — all required extensions present on every route "
        f"in server/api/openapi.yaml."
    )

    # ── Step 2: handler drift check (requires Go + network for first run) ────
    if not committed.is_file():
        warn(
            "server/internal/apigen/api.gen.go is not committed — "
            "run `make api.gen` and commit the result first"
        )
        return 1

    tmpdir = Path(tempfile.mkdtemp(prefix="api_gen_check_"))
    try:
        tmp_out = tmpdir / "api.gen.go"
        # Patch the config to output into the tmp directory.
        cfg_src = (spec_dir / "oapi-codegen.yaml").read_text()
        cfg_patched = re.sub(
            r"^output:.*$",
            f"output: {tmp_out}",
            cfg_src,
            flags=re.MULTILINE,
        )
        tmp_cfg = tmpdir / "oapi-codegen.yaml"
        tmp_cfg.write_text(cfg_patched)

        tool = "github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.3.0"
        cmd = (
            f"cd {spec_dir} && "
            f"go run {tool} --config {tmp_cfg} openapi.yaml"
        )
        info(cmd)
        if os.system(cmd) != 0:
            warn("oapi-codegen failed during drift check")
            return 1

        # Compare bodies, skipping the first two comment lines which contain the
        # version string so a codegen version bump alone does not fail CI.
        def _body(path: Path) -> str:
            lines = path.read_text().splitlines(keepends=True)
            return "".join(lines[2:]) if len(lines) > 2 else "".join(lines)

        if _body(committed) != _body(tmp_out):
            warn(
                "Handler drift detected: committed server/internal/apigen/api.gen.go "
                "does not match what oapi-codegen produces from the current "
                "server/api/openapi.yaml.\n"
                "Run `make api.gen` and commit the updated file."
            )
            os.system(f"diff -u {committed} {tmp_out} | head -60")
            return 1

        info("No drift — committed api.gen.go matches the spec.")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def cmd_docs(_argv: List[str]) -> int:
    """Serve Swagger UI on localhost:8081 (compose profile=docs).

    Starts the `api-docs` compose service (profile=docs) which runs
    swaggerapi/swagger-ui mounted with server/api/openapi.yaml.
    Production image omits this service — no /v1/docs route is exposed
    on the public API (§9.4 security doctrine).
    """
    parts = list(COMPOSE)
    if ENV_FILE.is_file():
        parts += ["--env-file", str(ENV_FILE)]
    parts += ["-f", "docker-compose.yml", "--profile", "docs"]
    base = " ".join(parts)
    cmd = f"{base} up -d api-docs"
    info(cmd)
    info("Swagger UI will be available at http://localhost:8081")
    rc = os.system(cmd)
    if rc != 0:
        warn("Failed to start api-docs service. Is Docker running?")
        return 1
    return 0


def _psql_exec(sql: str) -> int:
    """Pipe *sql* to psql inside the compose 'postgres' service.

    Returns 0 on success, 1 on failure.  Uses subprocess so SQL is passed
    via stdin and is never interpolated into a shell command string.
    """
    import subprocess

    pg_user = os.environ.get("POSTGRES_USER", "negelir")
    pg_db = os.environ.get("POSTGRES_DB", "negelir")
    base_parts = list(COMPOSE)
    if ENV_FILE.is_file():
        base_parts += ["--env-file", str(ENV_FILE)]
    base_parts += ["-f", str(REPO_ROOT / "docker-compose.yml")]
    cmd = base_parts + [
        "exec", "-T", "postgres",
        "psql", "-U", pg_user, "-d", pg_db,
        "-v", "ON_ERROR_STOP=1",
    ]
    result = subprocess.run(cmd, input=sql, capture_output=True, text=True)
    if result.returncode != 0:
        warn(f"psql failed (exit {result.returncode}):\n{result.stderr.strip()}")
        return 1
    return 0


def cmd_rotate_jwt_key(argv: List[str]) -> int:
    """Generate new JWT keypair and rotate atomically (pending → active, old → retired)."""
    import shutil
    import stat
    import subprocess
    import time

    p = argparse.ArgumentParser(prog="api.py rotate-jwt-key")
    p.add_argument(
        "--alg", default="RS256", choices=["RS256", "ES256"],
        help="Key algorithm (default: RS256).",
    )
    p.add_argument(
        "--warm-wait", type=int, default=10,
        help="Seconds to wait after inserting pending key before promoting to active (default: 10).",
    )
    args = p.parse_args(argv)

    key_dir = REPO_ROOT / "data" / "api" / "jwt_keys"
    key_dir.mkdir(parents=True, exist_ok=True)

    # Determine next kid number from existing private-key files.
    existing = sorted(key_dir.glob("kid_*.priv.pem"))
    kid = f"kid_{len(existing) + 1:03d}"
    priv_pem_path = key_dir / f"{kid}.priv.pem"
    pub_pem_path = key_dir / f"{kid}.pub.pem"

    openssl = shutil.which("openssl")
    if not openssl:
        warn("openssl not found on PATH — install openssl and retry")
        return 1

    info(f"Generating {args.alg} keypair for {kid!r} …")
    if args.alg == "RS256":
        r = subprocess.run(
            [openssl, "genrsa", "-out", str(priv_pem_path), "2048"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            warn(f"openssl genrsa failed: {r.stderr.strip()}")
            return 1
        r = subprocess.run(
            [openssl, "rsa", "-in", str(priv_pem_path), "-pubout", "-out", str(pub_pem_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            warn(f"openssl rsa -pubout failed: {r.stderr.strip()}")
            return 1
    else:  # ES256 — P-256
        r = subprocess.run(
            [openssl, "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(priv_pem_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            warn(f"openssl ecparam failed: {r.stderr.strip()}")
            return 1
        r = subprocess.run(
            [openssl, "ec", "-in", str(priv_pem_path), "-pubout", "-out", str(pub_pem_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            warn(f"openssl ec -pubout failed: {r.stderr.strip()}")
            return 1

    try:
        os.chmod(priv_pem_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass

    pub_pem = pub_pem_path.read_text()
    priv_pem_abs = str(priv_pem_path.resolve())

    # Use PostgreSQL dollar-quoting ($TAG$…$TAG$) to embed PEM text without
    # single-quote escaping.  PEM content only uses base64 chars + dashes +
    # spaces so the $K$/$A$/$P$/$R$ delimiters will never appear inside it.
    insert_sql = (
        "BEGIN;\n"
        "INSERT INTO jwt_keys (kid, alg, pub_pem, priv_pem_path, status)\n"
        f"VALUES ($K${kid}$K$, $A${args.alg}$A$, $P${pub_pem}$P$, $R${priv_pem_abs}$R$, 'pending')\n"
        "ON CONFLICT (kid) DO NOTHING;\n"
        "COMMIT;\n"
    )
    info("Inserting pending key into jwt_keys table …")
    if _psql_exec(insert_sql) != 0:
        warn("Failed to insert pending key. Is the compose stack running?")
        return 1

    info(f"Key {kid!r} staged as pending. Waiting {args.warm_wait}s for replica warm-up …")
    time.sleep(args.warm_wait)

    # Atomically flip: current active → retired, pending → active.
    # The unique partial index (status='active') enforces at-most-one-active.
    promote_sql = (
        "BEGIN;\n"
        "UPDATE jwt_keys SET status='retired', rotated_out_at=now()\n"
        "  WHERE status='active';\n"
        "UPDATE jwt_keys SET status='active', rotated_in_at=now()\n"
        f"  WHERE kid=$K${kid}$K$;\n"
        "COMMIT;\n"
    )
    info(f"Promoting {kid!r} to active (previous active key → retired) …")
    if _psql_exec(promote_sql) != 0:
        warn(
            f"Failed to promote {kid!r}. Database may be stuck with the new key in "
            f"'pending' state — retry or promote manually:\n"
            f"  psql -c \"UPDATE jwt_keys SET status='active', rotated_in_at=now() "
            f"WHERE kid='{kid}';\""
        )
        return 1

    info(f"JWT key rotated: {kid!r} is now active.")
    ok("Rolling restart of API replicas recommended so they reload the signing key.")
    return 0


def cmd_revoke_jti(argv: List[str]) -> int:
    """Add a JTI to the Redis revocation deny-set (auth:rev:<jti>) via redis-cli."""
    import re

    p = argparse.ArgumentParser(prog="api.py revoke-jti")
    p.add_argument("--jti", required=True, help="JTI value from the JWT jti claim.")
    p.add_argument(
        "--ttl",
        type=int,
        default=900,
        help="Remaining token lifetime in seconds (default: 900 = api_access_ttl_s).",
    )
    args = p.parse_args(argv)

    # Validate JTI — only URL-safe chars to prevent redis-cli injection.
    if not re.match(r"^[A-Za-z0-9_\-]+$", args.jti):
        warn("--jti must contain only alphanumeric, hyphen, or underscore characters")
        return 1
    if args.ttl <= 0:
        warn("--ttl must be a positive integer (seconds)")
        return 1

    key = f"auth:rev:{args.jti}"
    score = str(int(__import__("time").time() * 1_000_000))

    base = _api_compose_base()
    # Write the individual deny-set key with TTL.
    set_cmd = f'{base} exec redis redis-cli SET "{key}" 1 EX {args.ttl}'
    # Update the sorted-set index for cardinality tracking and LRU eviction.
    zadd_cmd = f'{base} exec redis redis-cli ZADD auth:rev:idx {score} "{args.jti}"'

    info(f"Revoking JTI {args.jti!r} (TTL={args.ttl}s)")
    if os.system(set_cmd) != 0:
        warn("redis-cli SET failed. Is the compose stack running?")
        return 1
    if os.system(zadd_cmd) != 0:
        warn("redis-cli ZADD (index update) failed; key was set but cardinality index is stale")
        return 1
    info(f"JTI revoked → key={key} (TTL {args.ttl}s)")
    return 0


def cmd_tls_rotate(_argv: List[str]) -> int:
    """Renew mTLS service certs from Phase 2 internal CA."""
    import shutil
    import stat

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from xops.mock.ca import CAError, MOCK_ROOT, ca_exists, issue_leaf
    except ImportError as exc:
        warn(f"Cannot import xops.mock.ca: {exc}")
        return 1

    if not ca_exists():
        warn(
            "Phase 2 internal CA not found at infra/mock/ca/ — "
            "run `make mock.setup` first to initialise the CA, then retry."
        )
        return 1

    tls_dir = REPO_ROOT / "data" / "api" / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)

    # (host_id used for CA leaf, cert_name used for destination filename)
    services = [
        ("api",          "api"),
        ("client_redis", "client_redis"),
        ("client_pg",    "client_pg"),
        ("client_bus",   "client_bus"),
    ]
    for host_id, cert_name in services:
        info(f"Re-issuing cert for {host_id!r} …")
        try:
            leaf_dir = issue_leaf(host_id, force=True)
        except CAError as exc:
            warn(f"Failed to issue cert for {host_id!r}: {exc}")
            return 1
        dst_crt = tls_dir / f"{cert_name}.crt"
        dst_key = tls_dir / f"{cert_name}.key"
        shutil.copy2(leaf_dir / "leaf.crt", dst_crt)
        shutil.copy2(leaf_dir / "leaf.key", dst_key)
        try:
            os.chmod(dst_key, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass
        info(f"  → {dst_crt}  {dst_key}")

    # Copy the CA root cert so clients can verify the chain.
    ca_crt_dst = tls_dir / "ca.crt"
    shutil.copy2(MOCK_ROOT / "ca" / "root.crt", ca_crt_dst)
    info(f"  → {ca_crt_dst}  (CA root cert)")

    ok("mTLS certs renewed in data/api/tls/.")
    ok("Rolling restart of API replicas required to load new certs.")
    ok("Redis / Postgres / bus services also require restart if their client certs changed.")
    return 0


def cmd_rotate_cursor_key(_argv: List[str]) -> int:
    """Rotate the AES-GCM cursor seal key (data/api/cursor_key).

    Writes 32 fresh random bytes to data/api/cursor_key (mode 0600). The
    previous key file is renamed to cursor_key.retired.<unix_ts> so it can
    be recovered for forensic inspection. There is no grace period: all
    cursors minted with the old key immediately become invalid and callers
    receive 400 invalid_cursor — clients restart pagination from scratch.
    """
    import secrets
    import stat
    import time

    key_path = REPO_ROOT / "data" / "api" / "cursor_key"
    key_path.parent.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        backup = key_path.with_name(f"cursor_key.retired.{int(time.time())}")
        key_path.rename(backup)
        info(f"Old cursor key backed up → {backup}")

    # AES-256-GCM requires exactly 32 bytes; write raw bytes (not base64).
    raw = secrets.token_bytes(32)
    key_path.write_bytes(raw)
    try:
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass

    import base64
    b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    info(f"New cursor key written to {key_path} (32 bytes, mode 0600).")
    info(f"Key (base64url, verification only): {b64}")
    ok("Rolling restart of API replicas recommended.")
    ok("In-flight cursors from the old key will return 400 invalid_cursor — expected behaviour.")
    return 0


def cmd_rotate_tls_session_key(_argv: List[str]) -> int:
    """Rotate the TLS session ticket key stored in Redis (§9.17.8).

    Generates 32 cryptographically-random bytes and writes them to the Redis
    key "api:tls:session_ticket_key" with no TTL (key persists until the next
    rotation).  The running API server reads this key at startup and uses it
    for TLS session ticket resumption on inbound HTTPS connections; a rolling
    restart picks up the new key.

    The key is NOT stored on disk — it is ephemeral in Redis so a Redis flush
    or restart generates a new random key automatically (sessions can no longer
    be resumed, which is safe: clients fall back to a full TLS handshake).

    Rotation cadence: every 24 hours (per §9.17.8 spec).  Run via:
        make api.rotate-tls-session-key

    Cert rotation triggers an implicit session cache flush separately (see
    `make api.tls-rotate`); this command rotates only the session ticket key.
    """
    import secrets
    import base64

    raw = secrets.token_bytes(32)
    b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    # Write to Redis using redis-cli via the compose stack.  This keeps the
    # xops script free of a Python Redis dependency while staying consistent
    # with how make api.tls-rotate and make api.rotate-jwt-key operate.
    import subprocess
    redis_url = _redis_url_from_env()
    result = subprocess.run(
        ["redis-cli", "-u", redis_url, "SET", "api:tls:session_ticket_key", b64],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        warn(f"redis-cli SET failed: {result.stderr.strip()}")
        warn("Ensure Redis is running (make infra) and NEGELIR_REDIS_URL is set.")
        return 1

    info("New TLS session ticket key written to Redis api:tls:session_ticket_key.")
    info(f"Key (base64url, 32 bytes): {b64}")
    ok("Rolling restart of API replicas required to load the new session ticket key.")
    ok("In-flight TLS sessions using the old key will fall back to a full handshake — expected behaviour.")
    return 0


def _redis_url_from_env() -> str:
    """Return NEGELIR_REDIS_URL from xops/env/.env or fall back to a default."""
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("NEGELIR_REDIS_URL="):
                return line.split("=", 1)[1]
    return "redis://localhost:6379"


def cmd_bump_bcrypt_cost(argv: List[str]) -> int:
    """Bump NEGELIR_API_BCRYPT_COST and trigger rolling re-hash on next login.

    Validates that the new cost is in the range [10, 14] (server hard limit)
    and is not lower than the current value. Updates xops/env/.env in place.
    Existing password hashes are migrated lazily on the next successful login.
    """
    import re

    p = argparse.ArgumentParser(prog="api.py bump-bcrypt-cost")
    p.add_argument(
        "--cost", type=int, required=True,
        help="New bcrypt cost factor. Must be in [10, 14] and >= current value.",
    )
    args = p.parse_args(argv)

    if not (10 <= args.cost <= 14):
        warn(f"--cost {args.cost} is out of range [10, 14] (see NEGELIR_API_BCRYPT_COST docs)")
        return 1

    if not ENV_FILE.is_file():
        warn(f"Env file not found at {ENV_FILE} — run `make env` first")
        return 1

    content = ENV_FILE.read_text()
    m = re.search(r"^NEGELIR_API_BCRYPT_COST\s*=\s*(\d+)", content, re.MULTILINE)
    current_cost = int(m.group(1)) if m else 12  # default from config.go

    if args.cost < current_cost:
        warn(
            f"New cost {args.cost} is lower than current {current_cost}. "
            "Bcrypt cost may only increase — decreasing would weaken security."
        )
        return 1

    if args.cost == current_cost:
        info(f"NEGELIR_API_BCRYPT_COST is already {current_cost} — no change needed.")
        return 0

    if m:
        new_content = re.sub(
            r"^(NEGELIR_API_BCRYPT_COST\s*=\s*)\d+",
            rf"\g<1>{args.cost}",
            content,
            flags=re.MULTILINE,
        )
    else:
        new_content = content.rstrip("\n") + f"\nNEGELIR_API_BCRYPT_COST={args.cost}\n"

    ENV_FILE.write_text(new_content)
    info(f"NEGELIR_API_BCRYPT_COST updated: {current_cost} → {args.cost} in {ENV_FILE}")
    ok("Rolling restart of API replicas will pick up the new cost factor.")
    ok("Existing passwords are re-hashed lazily on the next successful login (no forced logout).")
    return 0


def cmd_init(argv: List[str]) -> int:
    """First-run bootstrap (§9.10): JWT keypair kid_001, cursor seal key, optional mTLS.

    Idempotent — re-running is a no-op when output files already exist.

    Steps:
      (a) JWT keypair → data/api/jwt_keys/kid_001.{priv,pub}.pem + DB row.
      (b) Cursor seal key → data/api/cursor_key (32 bytes, base64url, mode 0600).
      (c) mTLS bundle → data/api/tls/ (only when --with-tls is given).
    """
    import base64
    import secrets
    import shutil
    import stat
    import subprocess

    p = argparse.ArgumentParser(prog="api.py init")
    p.add_argument(
        "--with-tls",
        action="store_true",
        default=False,
        help="Also mint the mTLS bundle in data/api/tls/ (default: off; use in dev/compose).",
    )
    args = p.parse_args(argv)

    any_error = False

    # ── (a) JWT keypair kid_001 ───────────────────────────────────────────────
    key_dir = REPO_ROOT / "data" / "api" / "jwt_keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    kid = "kid_001"
    priv_pem_path = key_dir / f"{kid}.priv.pem"
    pub_pem_path = key_dir / f"{kid}.pub.pem"

    if priv_pem_path.exists() and pub_pem_path.exists():
        ok(f"JWT keypair {kid!r}: already-exists — skipping")
    else:
        openssl = shutil.which("openssl")
        if not openssl:
            warn("openssl not found on PATH — cannot generate JWT keypair")
            return 1

        info(f"Generating RSA-2048 keypair for {kid!r} …")
        r = subprocess.run(
            [openssl, "genrsa", "-out", str(priv_pem_path), "2048"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            warn(f"openssl genrsa failed: {r.stderr.strip()}")
            return 1
        try:
            os.chmod(priv_pem_path, stat.S_IRUSR)  # 0400 — read-only by owner
        except OSError:
            pass

        r = subprocess.run(
            [openssl, "rsa", "-in", str(priv_pem_path), "-pubout", "-out", str(pub_pem_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            warn(f"openssl rsa -pubout failed: {r.stderr.strip()}")
            return 1

        pub_pem = pub_pem_path.read_text()
        priv_pem_abs = str(priv_pem_path.resolve())
        insert_sql = (
            "BEGIN;\n"
            "INSERT INTO jwt_keys (kid, alg, pub_pem, priv_pem_path, status)\n"
            f"VALUES ($K${kid}$K$, $A$RS256$A$, $P${pub_pem}$P$, $R${priv_pem_abs}$R$, 'active')\n"
            "ON CONFLICT (kid) DO NOTHING;\n"
            "COMMIT;\n"
        )
        info(f"Inserting {kid!r} as active into jwt_keys …")
        if _psql_exec(insert_sql) != 0:
            warn(
                "DB insert failed — compose stack may not be running. "
                "Key files are on disk; re-run `make api.init` once the stack is up."
            )
            any_error = True
        else:
            ok(f"JWT keypair {kid!r}: created")

    # ── (b) Cursor seal key ───────────────────────────────────────────────────
    cursor_path = REPO_ROOT / "data" / "api" / "cursor_key"
    cursor_path.parent.mkdir(parents=True, exist_ok=True)

    if cursor_path.exists():
        ok("Cursor seal key: already-exists — skipping")
    else:
        raw = secrets.token_bytes(32)
        b64 = base64.urlsafe_b64encode(raw).rstrip(b"=")
        cursor_path.write_bytes(b64)
        try:
            os.chmod(cursor_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass
        ok("Cursor seal key: created (data/api/cursor_key, mode 0600)")

    # ── (c) mTLS bundle ───────────────────────────────────────────────────────
    if args.with_tls:
        try:
            from xops.mock.ca import CAError, MOCK_ROOT, ca_exists, issue_leaf
        except ImportError as exc:
            warn(f"Cannot import xops.mock.ca: {exc}")
            return 1

        tls_dir = REPO_ROOT / "data" / "api" / "tls"
        ca_crt_dst = tls_dir / "ca.crt"
        services = [
            ("api",          "api"),
            ("client_redis", "client_redis"),
            ("client_pg",    "client_pg"),
            ("client_bus",   "client_bus"),
        ]
        all_exist = ca_crt_dst.exists() and all(
            (tls_dir / f"{cert_name}.crt").exists()
            and (tls_dir / f"{cert_name}.key").exists()
            for _, cert_name in services
        )
        if all_exist:
            ok("mTLS bundle: already-exists — skipping")
        else:
            if not ca_exists():
                warn(
                    "Phase 2 internal CA not found at infra/mock/ca/ — "
                    "run `make mock.setup` first to initialise the CA, then retry."
                )
                return 1

            tls_dir.mkdir(parents=True, exist_ok=True)
            for host_id, cert_name in services:
                dst_crt = tls_dir / f"{cert_name}.crt"
                dst_key = tls_dir / f"{cert_name}.key"
                if dst_crt.exists() and dst_key.exists():
                    ok(f"  cert {cert_name!r}: already-exists — skipping")
                    continue
                info(f"  Issuing cert for {host_id!r} …")
                try:
                    leaf_dir = issue_leaf(host_id, force=False)
                except CAError as exc:
                    warn(f"  Failed to issue cert for {host_id!r}: {exc}")
                    return 1
                shutil.copy2(leaf_dir / "leaf.crt", dst_crt)
                shutil.copy2(leaf_dir / "leaf.key", dst_key)
                try:
                    os.chmod(dst_key, stat.S_IRUSR | stat.S_IWUSR)  # 0600
                except OSError:
                    pass
                ok(f"  cert {cert_name!r}: created")

            shutil.copy2(MOCK_ROOT / "ca" / "root.crt", ca_crt_dst)
            ok("mTLS bundle: created in data/api/tls/")
    else:
        info("mTLS bundle: skipped (pass --with-tls to generate, or: make api.init WITH_TLS=--with-tls)")

    if any_error:
        warn(
            "Bootstrap completed with warnings — some steps need the compose stack. "
            "Re-run `make api.init` once `make up` is done."
        )
        return 1
    ok("Bootstrap complete.")
    return 0


def cmd_pprof_enable(argv: List[str]) -> int:
    """§9.17.10 Enable pprof on the metrics port for a live pod (1h TTL).

    Writes the Redis key api:pprof:<pod> with a 1-hour TTL so the running API
    pod picks it up and serves /debug/pprof/* on the metrics port (:9091).
    The pod re-checks the key on each request to the debug path; a rolling
    restart is NOT required.

    Usage:
        make api.pprof-enable POD=<pod-name-or-hostname>
    """
    import subprocess

    p = argparse.ArgumentParser(prog="api.py pprof-enable")
    p.add_argument("--pod", required=True, help="Pod name or hostname to enable pprof for.")
    args = p.parse_args(argv)

    # Validate: only alphanumeric + hyphens to prevent redis-cli injection.
    import re
    if not re.match(r"^[A-Za-z0-9._-]+$", args.pod):
        warn("--pod must contain only alphanumeric, dot, hyphen, or underscore characters")
        return 1

    key = f"api:pprof:{args.pod}"
    ttl = 3600  # 1 hour

    redis_url = _redis_url_from_env()
    result = subprocess.run(
        ["redis-cli", "-u", redis_url, "SET", key, "1", "EX", str(ttl)],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        warn(f"redis-cli SET failed: {result.stderr.strip()}")
        warn("Ensure Redis is running (make infra) and NEGELIR_REDIS_URL is set.")
        return 1

    info(f"pprof enabled for pod {args.pod!r}: key={key} (TTL={ttl}s)")
    ok(f"Visit http://<pod>:{9091}/debug/pprof/ to inspect profiles (metrics port only).")
    return 0


def cmd_profile_show(argv: List[str]) -> int:
    """§9.17.10 Print the path(s) of continuous CPU profile files.

    With --latest: prints the most recently modified .pprof.gz file under
    data/api/profiles/ (or NEGELIR_API_PPROF_DIR when set). Without
    --latest: lists all files grouped by pod directory.

    Usage:
        make api.profile-show LATEST=1
        make api.profile-show
    """
    p = argparse.ArgumentParser(prog="api.py profile-show")
    p.add_argument("--latest", action="store_true", help="Print only the most recent profile file.")
    args = p.parse_args(argv)

    # Respect NEGELIR_API_PPROF_DIR if set in the env file; fall back to default.
    pprof_dir_env = ""
    env_path = REPO_ROOT / "xops" / "env" / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.startswith("NEGELIR_API_PPROF_DIR="):
                pprof_dir_env = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    base_dir = Path(pprof_dir_env) if pprof_dir_env else REPO_ROOT / "data" / "api" / "profiles"
    if not base_dir.is_absolute():
        base_dir = REPO_ROOT / base_dir

    if not base_dir.exists():
        warn(f"Profile directory {base_dir} does not exist yet.")
        warn("Start the API and wait for the first 10-minute profile cycle.")
        return 1

    all_files = sorted(base_dir.rglob("*.pprof.gz"), key=lambda f: f.stat().st_mtime)
    if not all_files:
        warn(f"No .pprof.gz files found under {base_dir}.")
        return 1

    if args.latest:
        latest = all_files[-1]
        info(f"Latest profile: {latest}")
        info(f"Inspect with: go tool pprof {latest}")
        return 0

    info(f"CPU profiles under {base_dir}:")
    for f in all_files:
        import datetime
        mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size_kb = f.stat().st_size // 1024
        info(f"  {f.relative_to(REPO_ROOT)}  ({size_kb} KiB, {mtime})")
    info(f"\nTotal: {len(all_files)} file(s)")
    info("Inspect the latest with: make api.profile-show LATEST=1")
    return 0


def cmd_erase_user(argv: List[str]) -> int:
    """GDPR right-to-erasure: purge user row + audit null-stamp + pii_erased event."""
    p = argparse.ArgumentParser(prog="api.py erase-user")
    p.add_argument("--user", required=True, help="User ID or email to erase.")
    p.parse_args(argv)
    return _not_yet("erase-user", "9.8")


def cmd_slo_report(_argv: List[str]) -> int:
    """28-day rolling SLO summary (Phase 19 GA gate input).

    Queries api_audit_log (kind='response') for the last 28 days and reports:
      - total request count
      - error count / error rate  (5xx responses)
      - availability percentage
      - p95 latency: split into cache-hit (budget 250 ms) and cache-miss (800 ms)
      - GA gate: PASS / FAIL / INCONCLUSIVE against §9.8 SLO thresholds.

    Read-only: no writes to the database.
    Requires the compose postgres service to be running.
    """
    import subprocess

    # §9.8 SLO thresholds (binding for Phase 19 GA gate)
    AVAIL_THRESHOLD = 99.5       # availability %
    ERROR_RATE_THRESHOLD = 0.5   # error rate %
    P95_CACHE_HIT_BUDGET = 250   # ms
    P95_CACHE_MISS_BUDGET = 800  # ms

    # Pure read — window is 28 days.
    # percentile_cont FILTER clause is valid PostgreSQL syntax (9.4+).
    sql = (
        "SELECT\n"
        "  COUNT(*)                                                             AS total_requests,\n"
        "  COUNT(*) FILTER (WHERE status_code >= 500)                          AS error_count,\n"
        "  ROUND(\n"
        "    100.0 * COUNT(*) FILTER (WHERE status_code < 500 OR status_code IS NULL)\n"
        "    / NULLIF(COUNT(*), 0), 4\n"
        "  )                                                                   AS availability_pct,\n"
        "  ROUND(\n"
        "    100.0 * COUNT(*) FILTER (WHERE status_code >= 500)\n"
        "    / NULLIF(COUNT(*), 0), 4\n"
        "  )                                                                   AS error_rate_pct,\n"
        "  ROUND(CAST(\n"
        "    percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)\n"
        "    FILTER (WHERE cache_hit = true) AS NUMERIC\n"
        "  ), 1)                                                               AS p95_cache_hit_ms,\n"
        "  ROUND(CAST(\n"
        "    percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)\n"
        "    FILTER (WHERE cache_hit IS DISTINCT FROM true) AS NUMERIC\n"
        "  ), 1)                                                               AS p95_cache_miss_ms\n"
        "FROM api_audit_log\n"
        "WHERE kind = 'response'\n"
        "  AND created_at >= now() - INTERVAL '28 days';\n"
    )

    pg_user = os.environ.get("POSTGRES_USER", "negelir")
    pg_db = os.environ.get("POSTGRES_DB", "negelir")
    base_parts = list(COMPOSE)
    if ENV_FILE.is_file():
        base_parts += ["--env-file", str(ENV_FILE)]
    base_parts += ["-f", str(REPO_ROOT / "docker-compose.yml")]
    cmd = base_parts + [
        "exec", "-T", "postgres",
        "psql", "-U", pg_user, "-d", pg_db,
        "-t",              # tuple-only (no header/footer)
        "-A",              # unaligned
        "-F", "|",         # pipe-separated
        "-v", "ON_ERROR_STOP=1",
    ]

    result = subprocess.run(cmd, input=sql, capture_output=True, text=True)
    if result.returncode != 0:
        warn(
            "SLO query failed — is the compose stack running?\n"
            + result.stderr.strip()
        )
        return 1

    raw = result.stdout.strip()
    if not raw:
        info("─" * 60)
        info("28-day rolling SLO summary  (Phase 19 GA gate)")
        info("─" * 60)
        warn("No response rows in api_audit_log for the last 28 days.")
        info(f"GA gate ({AVAIL_THRESHOLD}% availability): INCONCLUSIVE — no traffic data")
        return 0

    parts = raw.split("|")
    if len(parts) < 6:
        warn(f"Unexpected psql output format — expected 6 fields, got {len(parts)}: {raw!r}")
        return 1

    try:
        total = int(parts[0]) if parts[0] else 0
        errors = int(parts[1]) if parts[1] else 0
        avail_pct = float(parts[2]) if parts[2] else None
        error_rate_pct = float(parts[3]) if parts[3] else None
        p95_hit_ms = float(parts[4]) if parts[4] else None
        p95_miss_ms = float(parts[5]) if parts[5] else None
    except ValueError as exc:
        warn(f"Could not parse SLO query output: {exc}\nRaw: {raw!r}")
        return 1

    avail_str = f"{avail_pct:.4f}%" if avail_pct is not None else "N/A"
    err_str = f"{error_rate_pct:.4f}%" if error_rate_pct is not None else "N/A"
    p95_hit_str = f"{p95_hit_ms:.1f} ms" if p95_hit_ms is not None else "N/A"
    p95_miss_str = f"{p95_miss_ms:.1f} ms" if p95_miss_ms is not None else "N/A"

    info("─" * 60)
    info("28-day rolling SLO summary  (Phase 19 GA gate)")
    info("─" * 60)
    info(f"  Window               : last 28 days")
    info(f"  Total requests       : {total:,}")
    info(f"  Error count (5xx)    : {errors:,}")
    info(f"  Error rate           : {err_str}  (budget ≤ {ERROR_RATE_THRESHOLD}%)")
    info(f"  Availability         : {avail_str}  (budget ≥ {AVAIL_THRESHOLD}%)")
    info(f"  p95 latency cache-hit: {p95_hit_str}  (budget ≤ {P95_CACHE_HIT_BUDGET} ms)")
    info(f"  p95 latency cache-miss: {p95_miss_str}  (budget ≤ {P95_CACHE_MISS_BUDGET} ms)")
    info("─" * 60)

    if total == 0:
        info(f"GA gate: INCONCLUSIVE — no traffic data in the last 28 days")
        return 0

    failures: List[str] = []
    if avail_pct is not None and avail_pct < AVAIL_THRESHOLD:
        failures.append(
            f"availability {avail_pct:.4f}% < {AVAIL_THRESHOLD}% threshold"
        )
    if error_rate_pct is not None and error_rate_pct > ERROR_RATE_THRESHOLD:
        failures.append(
            f"error rate {error_rate_pct:.4f}% > {ERROR_RATE_THRESHOLD}% threshold"
        )
    if p95_hit_ms is not None and p95_hit_ms > P95_CACHE_HIT_BUDGET:
        failures.append(
            f"p95 cache-hit {p95_hit_ms:.1f} ms > {P95_CACHE_HIT_BUDGET} ms budget"
        )
    if p95_miss_ms is not None and p95_miss_ms > P95_CACHE_MISS_BUDGET:
        failures.append(
            f"p95 cache-miss {p95_miss_ms:.1f} ms > {P95_CACHE_MISS_BUDGET} ms budget"
        )

    if not failures:
        ok(f"GA gate: PASS  — all SLO thresholds met")
        return 0
    else:
        for f in failures:
            warn(f"GA gate: FAIL  — {f}")
        return 1


# ── dispatch table ────────────────────────────────────────────

COMMANDS = {
    "init": cmd_init,
    "up": cmd_up,
    "down": cmd_down,
    "build": cmd_build,
    "gen": cmd_gen,
    "gen-check": cmd_gen_check,
    "docs": cmd_docs,
    "rotate-jwt-key": cmd_rotate_jwt_key,
    "revoke-jti": cmd_revoke_jti,
    "tls-rotate": cmd_tls_rotate,
    "rotate-cursor-key": cmd_rotate_cursor_key,
    "rotate-tls-session-key": cmd_rotate_tls_session_key,
    "bump-bcrypt-cost": cmd_bump_bcrypt_cost,
    "erase-user": cmd_erase_user,
    "slo-report": cmd_slo_report,
    "pprof-enable": cmd_pprof_enable,
    "profile-show": cmd_profile_show,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="api.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
