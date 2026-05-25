"""Phase 8 §8.7 — sec.input.v1 read-side pattern_allowlist cache.

The §8.7 maint.sec.v1 writer promotes operator-confirmed false-
positive patterns into the ``pattern_allowlist`` table (state ``'a'``,
optional ``expires_at``). The sec.input.v1 reader consults this
allowlist on every deterministic-rule hit; if the
``(source, rule_id, hit_fingerprint)`` triple matches an active row,
the hit is suppressed (counted in ``sec_input_allowlist_hits_total``,
never silently lost) and the request continues to the classifier.

**Cache-reload race (binding).** The reader polls a single-row
``pattern_allowlist_meta(version)`` table every
``cfg.sec_input_allowlist_reload_s`` seconds. The version-row read
and the subsequent ``SELECT pattern FROM pattern_allowlist WHERE
state='a' ...`` MUST happen on the same connection under
``REPEATABLE READ`` snapshot isolation, so a concurrent writer that
commits between the two reads is invisible (consumer either sees
old version + old set OR new version + new set, never half-applied).
The next poll tick catches the new state. The proof test is in §8.9.

**Codec.** The lookup key is::

    hmac_sha256(k, NFC(f"{source}|{rule_id}|{hit_substring}")).hexdigest()[:16]

— deterministic, NFC-normalized, language-stable, and the raw
``hit_substring`` is never persisted (§8.7 SQL-injection guard line:
"hit_substring is never placed in a SQL LIKE or = clause — only the
fingerprint hash is").
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from common.config import cfg as _cfg


_log = logging.getLogger("swarm.agents.sec.allowlist")

_MOCK_ALLOWLIST_HMAC_KEY = b"negelir:mock:allowlist:hmac:v1"


def allowlist_hmac_key_age_days() -> float | None:
    """Return key-file age in days, or ``None`` when unknown.

    Unknown means the key path is unset or the file is unreadable.
    """
    key_path = str(getattr(_cfg, "sec_input_allowlist_hmac_key_path", "") or "").strip()
    if not key_path:
        return None
    try:
        mtime = Path(key_path).stat().st_mtime
    except OSError:
        return None
    age_s = max(0.0, time.time() - float(mtime))
    return age_s / 86400.0


def _load_allowlist_hmac_key() -> bytes:
    """Return the secret key used for allowlist fingerprint HMACs."""
    key_path = str(getattr(_cfg, "sec_input_allowlist_hmac_key_path", "") or "").strip()
    if key_path:
        try:
            key = Path(key_path).read_bytes()
        except OSError:
            key = b""
        if key:
            return key
    if str(getattr(_cfg, "profile", "mock")).lower() == "mock":
        return _MOCK_ALLOWLIST_HMAC_KEY
    raise RuntimeError(
        "allowlist HMAC key is missing; set NEGELIR_SEC_INPUT_ALLOWLIST_HMAC_KEY_PATH"
    )


# ── Codec ────────────────────────────────────────────────────────────
def compute_pattern_key(source: str, rule_id: str, hit_substring: str) -> str:
    """Return the canonical pattern_allowlist lookup key.

    Single source of truth for both reader and writer. Stable across
    locales: NFC normalize the composite string before hashing so a
    pre/post-NFC payload never produces two different keys.
    """
    composite = f"{source}|{rule_id}|{hit_substring}"
    nfc = unicodedata.normalize("NFC", composite)
    key = _load_allowlist_hmac_key()
    digest = hmac.new(key, nfc.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:16]


def compute_pattern_key_legacy_sha(
    source: str,
    rule_id: str,
    hit_substring: str,
) -> str:
    """Legacy pre-8.16.10 fingerprint (plain SHA-256[:16]).

    Keep this helper for backward-compatible reads while older
    allowlist rows are re-fingerprinted under HMAC.
    """
    composite = f"{source}|{rule_id}|{hit_substring}"
    nfc = unicodedata.normalize("NFC", composite)
    return hashlib.sha256(nfc.encode("utf-8")).hexdigest()[:16]


# ── Reader protocol ──────────────────────────────────────────────────
class PatternAllowlistReader(Protocol):
    """Read-only adapter over the ``pattern_allowlist`` + ``meta`` tables.

    Implementations MUST guarantee snapshot consistency between the
    returned ``version`` and ``active_keys`` set (REPEATABLE READ in
    Postgres; trivially atomic for the in-memory shim).
    """

    def read_active_snapshot(self) -> tuple[int, frozenset[str]]:
        """Return ``(version, active_keys)`` under snapshot isolation."""
        ...


@dataclass
class InMemoryAllowlistReader:
    """Test/bootstrap shim for :class:`PatternAllowlistReader`.

    Production driver (Phase 8.7b) lives in ``server/`` and wraps a
    psycopg connection with explicit ``BEGIN ISOLATION LEVEL
    REPEATABLE READ``.
    """

    version: int = 0
    active_keys: frozenset[str] = field(default_factory=frozenset)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def read_active_snapshot(self) -> tuple[int, frozenset[str]]:
        with self._lock:
            return self.version, self.active_keys

    # Test helpers — bump version on every mutation so the cache
    # picks up the change on the next poll tick.
    def add(self, key: str) -> None:
        with self._lock:
            self.active_keys = frozenset(self.active_keys | {key})
            self.version += 1

    def remove(self, key: str) -> None:
        with self._lock:
            self.active_keys = frozenset(self.active_keys - {key})
            self.version += 1

    def replace(self, keys: Iterable[str]) -> None:
        with self._lock:
            self.active_keys = frozenset(keys)
            self.version += 1


# ── Cache ────────────────────────────────────────────────────────────
class AllowlistCache:
    """Per-process cache wrapping a :class:`PatternAllowlistReader`.

    The first :meth:`is_allowlisted` call triggers an eager load.
    Subsequent calls within ``reload_s`` reuse the cached snapshot.
    Reader exceptions keep the previous snapshot in place (fail-open
    — same doctrine as §7.7 pattern reload).
    """

    __slots__ = (
        "_reader", "_reload_s", "_clock_mono",
        "_version", "_keys", "_last_check_mono",
        "_loaded", "_lock",
    )

    def __init__(
        self,
        reader: PatternAllowlistReader,
        *,
        reload_s: float,
        clock_mono: Callable[[], float] | None = None,
    ) -> None:
        self._reader = reader
        self._reload_s = max(1.0, float(reload_s))
        self._clock_mono = clock_mono or time.monotonic
        self._version = -1
        self._keys: frozenset[str] = frozenset()
        self._last_check_mono = 0.0
        self._loaded = False
        self._lock = threading.Lock()

    def is_allowlisted(self, key: str) -> bool:
        self._maybe_reload()
        return key in self._keys

    def first_match(self, keys: Iterable[str]) -> str | None:
        """Return the first key present in the cached active set."""
        self._maybe_reload()
        for key in keys:
            if key in self._keys:
                return key
        return None

    def force_reload(self) -> None:
        """Bypass the throttle and re-read the snapshot now.

        Used by tests and by the §8.9 race-proof test. Production
        callers should prefer the throttled :meth:`is_allowlisted`
        path.
        """
        with self._lock:
            self._last_check_mono = 0.0
            self._loaded = False
        self._maybe_reload()

    def snapshot_version(self) -> int:
        """Return the version of the currently-cached snapshot.

        ``-1`` means the cache has not loaded yet. Used by metrics
        + tests; not part of the hot path.
        """
        with self._lock:
            return self._version

    def _maybe_reload(self) -> None:
        now = self._clock_mono()
        with self._lock:
            if self._loaded and (now - self._last_check_mono) < self._reload_s:
                return
            self._last_check_mono = now
        try:
            version, keys = self._reader.read_active_snapshot()
        except Exception as exc:  # noqa: BLE001 — fail-open contract
            # Keep the stale snapshot. Loud log so an operator notices
            # repeated failures; the next poll tick will retry.
            _log.warning(
                "pattern_allowlist read failed (%s); keeping cached "
                "snapshot version=%d", exc, self._version,
            )
            return
        with self._lock:
            self._loaded = True
            if version != self._version:
                self._version = int(version)
                self._keys = frozenset(keys)


# ── Production Postgres reader ────────────────────────────────────
class PgAllowlistReader:
    """Production :class:`PatternAllowlistReader` backed by Postgres.

    Each :meth:`read_active_snapshot` call opens a new connection via
    ``conn_factory``, issues two SELECTs under
    ``ISOLATION LEVEL REPEATABLE READ``, commits, then closes the
    connection.  This satisfies the §8.7 snapshot-consistency binding:
    a writer that commits between the two reads is invisible — the
    reader sees the old version + old set OR the new version + new
    set, never a half-applied state. The next
    :class:`AllowlistCache` poll tick picks up any new state.

    Parameters
    ----------
    conn_factory:
        Zero-argument callable returning a new psycopg2 connection.
        Called once per :meth:`read_active_snapshot` invocation; the
        connection is committed and closed before the method returns,
        or rolled back and closed on error. Connection pools should
        wrap their ``getconn`` here.
    """

    # psycopg2.extensions.ISOLATION_LEVEL_REPEATABLE_READ == 2.
    # Stored as a class attribute so tests can assert the value
    # without importing psycopg2.extensions directly.
    _ISOLATION_LEVEL: int = 2  # REPEATABLE READ

    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn_factory = conn_factory

    def read_active_snapshot(self) -> tuple[int, frozenset[str]]:
        """Return ``(version, active_pattern_keys)`` under REPEATABLE READ.

        Queries, in order, on the same connection and snapshot:

        1. ``SELECT version FROM pattern_allowlist_meta``
           ``WHERE singleton = 'x'``
        2. ``SELECT pattern FROM pattern_allowlist``
           ``WHERE state = 'a'``
           ``AND (expires_at IS NULL OR expires_at > now())``

        The ``pattern`` column stores the 16-char hex hit-fingerprint
        produced by :func:`compute_pattern_key`.  Expired rows
        (``state='e'``) and pending rows (``state='p'``) are
        excluded by the SQL filter, so the returned frozenset only
        contains currently-active suppressions.
        """
        conn = self._conn_factory()
        try:
            conn.set_isolation_level(self._ISOLATION_LEVEL)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT version FROM pattern_allowlist_meta"
                    " WHERE singleton = 'x'"
                )
                row = cur.fetchone()
                version = int(row[0]) if row is not None else 0
                cur.execute(
                    "SELECT pattern FROM pattern_allowlist"
                    " WHERE state = 'a'"
                    " AND (expires_at IS NULL OR expires_at > now())"
                )
                keys: frozenset[str] = frozenset(
                    r[0] for r in cur.fetchall()
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        return version, keys
