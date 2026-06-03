"""Phase 10 §10.2 — Lexicon loader: versioning + schema-version validation
and atomic hot-reload (LexiconStore).

Responsibilities:
  * Parse a lexicon YAML file (format: ``{_meta: {...}, entries: [...]}``)
  * Validate ``_meta.schema_version`` against ``LEXICON_SCHEMA_VERSION``
  * Raise ``LexiconSchemaError`` on any schema mismatch or malformed header
  * ``LexiconStore`` — hot-reloadable registry with atomic swap under
    ``threading.Lock`` (§10.2 Atomic swap bullet).

Usage::

    from nlp.lexicon_loader import load_lexicon_file, LexiconSchemaError
    from nlp.lexicon_loader import LexiconStore
    from pathlib import Path

    # Basic file load:
    try:
        meta, entries = load_lexicon_file(Path("ai/nlp/lexicon/teams.tr.yaml"))
    except LexiconSchemaError as exc:
        # refuse load — schema version mismatch
        ...

    # Hot-reloadable store (call maybe_reload() periodically from agent loop):
    store = LexiconStore(Path("ai/nlp/lexicon/"), reload_s=30)
    alerts = store.maybe_reload()   # list[dict] — nlp.alert.v1 payloads to publish
    data = store.get("teams.tr.yaml")   # tuple[LexiconMeta, list[dict]] | None
"""
from __future__ import annotations

import collections
import datetime
import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, NamedTuple, TYPE_CHECKING

import yaml

from common.config import Config
from common.logger import get_logger

if TYPE_CHECKING:
    from nlp.vendor.symspell import SymSpellIndex

# ── Versioning constant ────────────────────────────────────────────────────
# Increment when the lexicon file format changes in a backward-incompatible way.
# All lexicon files must declare this exact integer or load is refused.
LEXICON_SCHEMA_VERSION: int = 1

# Required keys inside every _meta block.
_META_REQUIRED_KEYS = ("schema_version", "lexicon_version", "generated_at_utc", "generator")


# ── Public types ───────────────────────────────────────────────────────────

class LexiconSchemaError(ValueError):
    """Raised when a lexicon file's schema version does not match LEXICON_SCHEMA_VERSION
    or when the _meta block is missing / malformed."""


class LexiconFeedSchemaTooNewError(LexiconSchemaError):
    """Raised when feed schema_version is higher than this NLP build allows."""


@dataclass(frozen=True)
class LexiconMeta:
    """Validated contents of the ``_meta`` block in a lexicon YAML file."""

    schema_version: int
    lexicon_version: str
    generated_at_utc: str
    generator: str


class AliasHit(NamedTuple):
    """Immutable alias lookup result (§10.2 Bounded memory).

    canonical_id:
        The canonical entity identifier.  Empty string for no-canonical-id
        files (``dialects.tr.yaml``, ``entities_negative.tr.yaml``).
    kind:
        Entity type — one of ``team | player | league | competition |
        market | dialect | entity_negative | unknown``.
    lexicon_version:
        SemVer string from the ``_meta.lexicon_version`` of the source file.
    """

    canonical_id: str
    kind: str
    lexicon_version: str


# ── Loader ─────────────────────────────────────────────────────────────────

def _compute_sha256(data: bytes) -> str:
    """Return the SHA-256 hex digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def _parse_lexicon_raw(
    name: str,
    raw_text: str,
    *,
    max_supported_schema_version: int = LEXICON_SCHEMA_VERSION,
) -> tuple[LexiconMeta, list[dict[str, Any]]]:
    """Parse and validate a lexicon from already-read text.

    Used internally by :func:`load_lexicon_file` and by
    :class:`LexiconStore` (which reads bytes once to compute SHA256 before
    decoding, avoiding a second ``read_text`` call).

    Parameters
    ----------
    name:
        File base-name used in error messages (e.g. ``"teams.tr.yaml"``).
    raw_text:
        Full UTF-8 decoded content of the lexicon file.

    Raises
    ------
    LexiconSchemaError
        Same conditions as :func:`load_lexicon_file`.
    yaml.YAMLError
        If *raw_text* is not valid YAML.
    """
    data = yaml.safe_load(raw_text)

    if not isinstance(data, dict):
        raise LexiconSchemaError(
            f"{name}: expected a YAML mapping at top level, "
            f"got {type(data).__name__!r}. "
            "Lexicon files must use the {{_meta: {{...}}, entries: [...]}} format."
        )

    if "_meta" not in data:
        raise LexiconSchemaError(
            f"{name}: missing required '_meta' key. "
            "Each lexicon file must carry a _meta block with "
            "{schema_version, lexicon_version, generated_at_utc, generator}."
        )

    meta_raw = data["_meta"]
    if not isinstance(meta_raw, dict):
        raise LexiconSchemaError(
            f"{name}: '_meta' must be a mapping, "
            f"got {type(meta_raw).__name__!r}."
        )

    missing = [k for k in _META_REQUIRED_KEYS if k not in meta_raw]
    if missing:
        raise LexiconSchemaError(
            f"{name}: '_meta' is missing required keys: {missing}."
        )

    declared = meta_raw["schema_version"]
    if not isinstance(declared, int):
        raise LexiconSchemaError(
            f"{name}: '_meta.schema_version' must be an integer, "
            f"got {type(declared).__name__!r} ({declared!r})."
        )
    if declared > int(max_supported_schema_version):
        raise LexiconFeedSchemaTooNewError(
            f"{name}: lexicon schema_version={declared} exceeds max supported "
            f"version {int(max_supported_schema_version)} for this NLP build. "
            "Refusing swap; upgrade NLP before switching emitter schema."
        )
    if declared != LEXICON_SCHEMA_VERSION:
        raise LexiconSchemaError(
            f"{name}: lexicon schema_version={declared} does not match "
            f"the expected version {LEXICON_SCHEMA_VERSION}. "
            "Update the file or upgrade the loader."
        )

    if "entries" not in data:
        raise LexiconSchemaError(
            f"{name}: missing required 'entries' key."
        )
    entries = data["entries"]
    if not isinstance(entries, list):
        raise LexiconSchemaError(
            f"{name}: 'entries' must be a list, "
            f"got {type(entries).__name__!r}."
        )

    meta = LexiconMeta(
        schema_version=declared,
        lexicon_version=str(meta_raw["lexicon_version"]),
        generated_at_utc=str(meta_raw["generated_at_utc"]),
        generator=str(meta_raw["generator"]),
    )
    return meta, entries


def _signature_file_for(path: Path) -> Path:
    return path.with_name(path.name + ".hmac")


def _load_lexicon_feed_hmac_keys(cfg: Config, now: float | None = None) -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    key_path = Path(cfg.nlp_lexicon_feed_hmac_key_path).expanduser()
    prev_path = Path(f"{key_path}.prev")
    if key_path.exists():
        try:
            current_key = key_path.read_bytes().strip()
        except OSError:
            current_key = b""
        if current_key:
            keys["current"] = current_key
    if prev_path.exists():
        try:
            prev_key = prev_path.read_bytes().strip()
        except OSError:
            prev_key = b""
        if prev_key and prev_key != keys.get("current"):
            if now is None:
                now = time.time()
            try:
                prev_mtime = prev_path.stat().st_mtime
            except OSError:
                prev_mtime = 0.0
            if now - prev_mtime <= cfg.nlp_lexicon_feed_hmac_key_grace_s:
                keys["prev"] = prev_key
    return keys


_SENSITIVE_LEXICON_FILES = frozenset({"markets.tr.yaml", "entities_negative.tr.yaml"})


def _valid_hex_signature(value: str) -> bool:
    try:
        raw = bytes.fromhex(value.strip())
    except ValueError:
        return False
    return len(raw) == hashlib.sha256().digest_size


def _verify_lexicon_feed_signature(raw_bytes: bytes, signature: str, keys: dict[str, bytes]) -> bool:
    signature = signature.strip().lower()
    for key in keys.values():
        expected = hmac.new(key, raw_bytes, hashlib.sha256).hexdigest()
        if hmac.compare_digest(signature, expected):
            return True
    return False


def load_lexicon_file(path: Path) -> tuple[LexiconMeta, list[dict[str, Any]]]:
    """Load and validate a lexicon YAML file.

    Parameters
    ----------
    path:
        Path to the lexicon ``.yaml`` file.

    Returns
    -------
    tuple[LexiconMeta, list[dict]]
        The validated ``_meta`` block and the list of lexicon entries.

    Raises
    ------
    LexiconSchemaError
        If ``_meta`` is absent, malformed, or has a ``schema_version`` that
        does not equal ``LEXICON_SCHEMA_VERSION``.
    FileNotFoundError
        If *path* does not exist.
    yaml.YAMLError
        If the file is not valid YAML.
    """
    raw_text = path.read_text(encoding="utf-8")
    # Delegate to the shared parser (avoids duplicating validation logic).
    return _parse_lexicon_raw(
        path.name,
        raw_text,
        max_supported_schema_version=LEXICON_SCHEMA_VERSION,
    )


# ── Helpers used by LexiconStore ───────────────────────────────────────────

def _utc_iso() -> str:
    """Current UTC time as ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_uuid() -> str:
    """Generate a random UUID4 string."""
    return str(uuid.uuid4())


def _load_markets_ids(path: Path | None) -> frozenset[str]:
    """Extract the set of canonical market IDs from ``betting_markets.json``.

    Falls back to an empty set on any I/O or parse error so a missing
    markets file does not crash the lexicon store at boot.
    """
    if path is None:
        path = Path(__file__).parent.parent / "common" / "betting_markets.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids: set[str] = set()
        for cat in data.get("categories", []):
            for market in cat.get("markets", []):
                mid = market.get("id")
                if mid:
                    ids.add(str(mid))
        return frozenset(ids)
    except (OSError, ValueError, KeyError):
        return frozenset()


# ── LexiconStore ───────────────────────────────────────────────────────────

# Map from lexicon filename to the ``kind`` string embedded in AliasHit.
# §10.19 Locale future-keying: both `.tr.yaml` and `.tr-TR.yaml` variants
# supported (symlinks created; actual rename deferred to §R-locale).
_KIND_FOR_FILE: dict[str, str] = {
    "teams.tr.yaml": "team",
    "players.tr.yaml": "player",
    "leagues.tr.yaml": "league",
    "competitions.tr.yaml": "competition",
    "markets.tr.yaml": "market",
    "dialects.tr.yaml": "dialect",
    "entities_negative.tr.yaml": "entity_negative",
    # Locale-keyed variants (§10.19 — symlinks for forward compatibility):
    "teams.tr-TR.yaml": "team",
    "players.tr-TR.yaml": "player",
    "leagues.tr-TR.yaml": "league",
    "competitions.tr-TR.yaml": "competition",
    "markets.tr-TR.yaml": "market",
    "dialects.tr-TR.yaml": "dialect",
    "entities_negative.tr-TR.yaml": "entity_negative",
}


def _build_alias_index(
    entries: list[dict[str, Any]],
    lexicon_version: str,
    kind: str,
) -> "dict[str, AliasHit]":
    """Build a flat alias-string → :class:`AliasHit` lookup dict.

    Collects all strings from the ``names`` and ``aliases`` list-fields of
    each entry, plus the ``token`` field used by
    ``dialects.tr.yaml`` / ``entities_negative.tr.yaml``.
    Non-dict entries and empty / non-string alias values are silently skipped.
    """
    index: dict[str, AliasHit] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        canonical_id = str(entry.get("canonical_id", ""))
        hit = AliasHit(
            canonical_id=canonical_id,
            kind=kind,
            lexicon_version=lexicon_version,
        )
        for field_name in ("names", "aliases"):
            for alias in entry.get(field_name, []) or []:
                if alias and isinstance(alias, str):
                    index[alias] = hit
        token = entry.get("token")
        if token and isinstance(token, str):
            index[token] = hit
    return index


def _current_rss_kb() -> int:
    """Return the current process RSS in kilobytes.

    Reads ``VmRSS`` from ``/proc/self/status`` on Linux (containerized
    default); falls back to ``resource.getrusage`` (macOS / unexpected
    env).  Returns 0 on any failure so callers can treat 0 as
    "unknown / skip the budget check".
    """
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    try:
        import resource as _resource  # noqa: PLC0415
        rss = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
        import sys as _sys  # noqa: PLC0415
        # On macOS ru_maxrss is bytes; on Linux it is kilobytes.
        return rss // 1024 if _sys.platform == "darwin" else rss
    except Exception:  # noqa: BLE001
        return 0


@dataclass(frozen=True)
class _LoadedFile:
    """Internal snapshot of one lexicon file after a successful load."""

    meta: LexiconMeta
    entries: list[dict[str, Any]]
    mtime_ns: int
    sha256: str  # §10.2 Integrity: SHA-256 hex of the raw file bytes at load time
    alias_index: "dict[str, AliasHit]" = field(  # §10.2 Bounded memory
        default_factory=dict, hash=False, compare=False
    )


# Lexicon files where entries do NOT carry a ``canonical_id`` field
# (they use ``token`` / ``canonical_tokens`` instead — §10.2 Layout bullet).
# §10.19 Locale future-keying: both `.tr.yaml` and `.tr-TR.yaml` variants.
_NO_CANONICAL_ID_FILES: frozenset[str] = frozenset({
    "dialects.tr.yaml",
    "entities_negative.tr.yaml",
    "dialects.tr-TR.yaml",
    "entities_negative.tr-TR.yaml",
})

# Debounce interval for repeated ``lexicon_unreadable`` alerts.
# Mirrors the inline debounce in SecAlertDebouncer (§7.4); the shared
# swarm.sdk.AlertDebouncer base class is extracted in §10.20.
_ALERT_DEBOUNCE_S: float = 300.0


class LexiconStore:
    """Hot-reloadable lexicon registry with atomic swap (§10.2 Atomic swap).

    Lifecycle
    ---------
    1. Create a ``LexiconStore`` pointing at the lexicon directory.
    2. Call :meth:`maybe_reload` periodically (e.g., at the top of each
       agent ``handle()`` call).  The method returns a list of
       ``nlp.alert.v1`` payload dicts for the caller to publish on the bus.
    3. Read entries via :meth:`get` or :meth:`get_all`.

    Reload contract (mirrors §7.5 SecInputAgent pattern reload doctrine)
    ----------------------------------------------------------------
    * Mtime of every ``*.tr.yaml`` file is checked at most once every
      ``reload_s`` seconds (``cfg.nlp_lexicon_reload_s``).
    * When any mtime changes, ALL files are loaded into a shadow dict.
    * Each entry's ``canonical_id`` is validated:
      - ``markets.tr.yaml``: must be in the ``betting_markets.json`` enum.
      - Other files with canonical_id: must be in ``league_catalog_ids``
        (Phase 13a) if provided, OR entry has ``freeform: true``.
      - ``dialects.tr.yaml`` / ``entities_negative.tr.yaml``: skip (no
        canonical_id).
    * On validation success the shadow dict is swapped in under
      ``threading.Lock``.
    * On any failure (parse error or validation error) the old data is
      kept and a debounced ``nlp.alert.v1{kind=lexicon_unreadable,
      severity=error}`` payload is returned for the caller to publish.

    Thread safety
    -------------
    :meth:`get` and :meth:`get_all` may be called from any thread at any
    time.  :meth:`maybe_reload` is expected to be called from a single
    driver thread (the agent loop) but is also safe under concurrent
    access — at worst two concurrent reloads race and one wins the swap.
    """

    def __init__(
        self,
        lexicon_dir: Path,
        *,
        reload_s: int = 30,
        max_entries_per_file: int = 50000,
        max_rss_mb: int = 128,
        max_old_generations: int = 2,
        max_edit_distance: int = 2,
        markets_path: Path | None = None,
        league_catalog_ids: frozenset[str] | None = None,
        clock_mono: Callable[[], float] | None = None,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
        rss_kb_fn: Callable[[], int] | None = None,
    ) -> None:
        self._dir = lexicon_dir
        self._reload_s = max(1, int(reload_s))
        self._max_entries_per_file = max(1, int(max_entries_per_file))
        self._max_rss_mb = max(0, int(max_rss_mb))
        self._max_old_generations = max(0, int(max_old_generations))
        self._max_edit_distance = max(1, min(2, int(max_edit_distance)))
        self._markets_path = markets_path
        self._league_catalog_ids = league_catalog_ids
        self._clock_mono = clock_mono if clock_mono is not None else time.monotonic
        self._clock_iso = clock_iso if clock_iso is not None else _utc_iso
        self._new_id = new_id if new_id is not None else _new_uuid
        self._rss_kb_fn = rss_kb_fn if rss_kb_fn is not None else _current_rss_kb

        self._lock = threading.Lock()
        # Current live data: file_name → _LoadedFile.
        self._data: dict[str, _LoadedFile] = {}
        # Current SymSpellIndex (§10.21.2 Symspell dictionary lifetime).
        # Built from all lexicon aliases on boot; REBUILT on every swap.
        self._symspell: "SymSpellIndex | None" = None
        # Generation tracking (§10.21.2 Old-generation eviction contract).
        self._generation_counter: int = 0
        # Retired snapshots: deque[(generation: int, data: dict[str, _LoadedFile], symspell: SymSpellIndex | None)].
        # Bounded by max_old_generations; oldest dropped when full.
        # When max_old_generations=0, maxlen=0 means no retention (immediate drop).
        self._old_generations: "collections.deque[tuple[int, dict[str, _LoadedFile], SymSpellIndex | None]]" = (
            collections.deque(maxlen=self._max_old_generations if self._max_old_generations > 0 else 0)
        )
        # Monotonic time of the last mtime poll (guards the reload interval).
        self._last_check_mono: float = float("-inf")
        # Per-(kind, subject) last-alert monotonic time for inline debounce.
        self._debounce_last: dict[tuple[str, str], float] = {}
        # Markets canonical ID set — loaded lazily on first validation.
        self._markets_ids: frozenset[str] | None = None
        # Logger for generation swap events.
        self._logger = get_logger(__name__)
        # §10.21.3 Bounded swap latency: track the last lock hold time for testing.
        self._last_lock_hold_ms: float = 0.0
        # Lexicon snapshot identifier (§10.23.2 / §10.23.9).
        self._lexicon_version_id: str = ""

    @classmethod
    def _resolve_lexicon_dir(cls, cfg: object, *, canary: bool = False) -> Path:
        base_dir = Path(getattr(cfg, "nlp_lexicon_dir", "ai/nlp/lexicon"))
        if canary or getattr(cfg, "nlp_canary_pod", False):
            return base_dir.with_name(base_dir.name + ".canary")
        return base_dir

    @classmethod
    def from_cfg(cls, cfg: object, *, canary: bool = False, **kwargs) -> "LexiconStore":
        return cls(cls._resolve_lexicon_dir(cfg, canary=canary), **kwargs)

    @property
    def lexicon_version_id(self) -> str:
        """Return the current lexicon snapshot identifier."""
        with self._lock:
            return self._lexicon_version_id

    @staticmethod
    def _compute_snapshot_id(data: dict[str, "_LoadedFile"]) -> str:
        items = sorted(
            f"{filename}:{loaded.meta.lexicon_version}"
            for filename, loaded in data.items()
        )
        if not items:
            return ""
        return hashlib.sha256("|".join(items).encode("utf-8")).hexdigest()

    # ── Public interface ───────────────────────────────────────────────────

    def maybe_reload(self) -> list[dict[str, Any]]:
        """Poll file mtimes; reload and swap atomically if any changed.

        Returns a (possibly empty) list of ``nlp.alert.v1`` payload dicts
        that the caller must publish on the bus.  Keeps old data on failure.
        """
        alerts: list[dict[str, Any]] = []

        now = self._clock_mono()
        if now - self._last_check_mono < self._reload_s:
            return alerts
        self._last_check_mono = now

        # Snapshot current data (no load under the lock) for mtime comparison.
        with self._lock:
            current_data = dict(self._data)

        # Detect whether any file changed (cheap stat() loop).
        # Skip-if-SHA-unchanged optimization (§10.2 Integrity): when mtime
        # changes but the file bytes are identical, treat as no-op. This
        # defends against editor-touch-without-change and guards the reload
        # path against partial/truncated writes (SHA mismatch → refuse swap).
        # Exclude files starting with `_` (utility files: _aliases_delta, _diacritics).
        # §10.19 Locale future-keying: symlinks `.tr-TR.yaml → .tr.yaml` exist
        # on disk but are not loaded separately (resolved via get() fallback).
        yaml_files = sorted(
            f for f in self._dir.glob("*.tr.yaml") if not f.name.startswith("_")
        )
        changed = False
        for yaml_file in yaml_files:
            try:
                new_mtime_ns = yaml_file.stat().st_mtime_ns
            except OSError:
                continue
            loaded = current_data.get(yaml_file.name)
            if loaded is None:
                changed = True
                break
            if new_mtime_ns != loaded.mtime_ns:
                # mtime changed — verify SHA before committing to a full reload.
                try:
                    file_bytes = yaml_file.read_bytes()
                except OSError:
                    continue
                if _compute_sha256(file_bytes) != loaded.sha256:
                    changed = True
                    break
                # Same SHA: editor touched the file without changing content.
                # Subsequent polls will re-stat + re-SHA until the file content
                # actually changes — acceptable cost (lexicons are small).
                # No swap needed; keep existing _LoadedFile unchanged.
        # Also reload if any previously-loaded file disappeared (unlikely but safe).
        if not changed and set(current_data) - {f.name for f in yaml_files}:
            changed = True

        if not changed:
            return alerts

        # ── Shadow load ───────────────────────────────────────────────────
        # Read each file's bytes once: compute SHA256 and decode to text in a
        # single pass. This avoids a second read_text() call inside
        # load_lexicon_file and prevents TOCTOU races for the SHA capture.
        cfg = Config()
        hmac_keys = _load_lexicon_feed_hmac_keys(cfg)
        shadow: dict[str, _LoadedFile] = {}
        load_errors: list[str] = []
        schema_too_new_errors: list[str] = []
        signature_warn_files: list[str] = []
        signature_enforce_files: list[str] = []

        for yaml_file in yaml_files:
            try:
                mtime_ns = yaml_file.stat().st_mtime_ns
                raw_bytes = yaml_file.read_bytes()
                sha256 = _compute_sha256(raw_bytes)
                raw_text = raw_bytes.decode("utf-8")

                signature_path = _signature_file_for(yaml_file)
                effective_mode = cfg.nlp_lexicon_feed_signature_required
                if yaml_file.name in _SENSITIVE_LEXICON_FILES:
                    effective_mode = "enforce"

                if cfg.nlp_lexicon_source == "feed" and effective_mode != "off":
                    signature = None
                    if signature_path.exists():
                        try:
                            signature = signature_path.read_text(encoding="utf-8").strip()
                        except OSError:
                            signature = None

                    if signature is None or not _valid_hex_signature(signature):
                        if effective_mode == "enforce":
                            signature_enforce_files.append(yaml_file.name)
                            load_errors.append(
                                f"{yaml_file.name}: lexicon feed signature missing or malformed"
                            )
                            continue
                        signature_warn_files.append(yaml_file.name)
                    else:
                        if not _verify_lexicon_feed_signature(raw_bytes, signature, hmac_keys):
                            if effective_mode == "enforce":
                                signature_enforce_files.append(yaml_file.name)
                                load_errors.append(
                                    f"{yaml_file.name}: lexicon feed signature invalid"
                                )
                                continue
                            signature_warn_files.append(yaml_file.name)

                meta, entries = _parse_lexicon_raw(
                    yaml_file.name,
                    raw_text,
                    max_supported_schema_version=cfg.nlp_lexicon_feed_max_supported_schema_version,
                )
                kind = _KIND_FOR_FILE.get(yaml_file.name, "unknown")
                alias_index = _build_alias_index(
                    entries, meta.lexicon_version, kind
                )
                shadow[yaml_file.name] = _LoadedFile(
                    meta=meta,
                    entries=entries,
                    mtime_ns=mtime_ns,
                    sha256=sha256,
                    alias_index=alias_index,
                )
            except LexiconFeedSchemaTooNewError as exc:
                schema_too_new_errors.append(f"{yaml_file.name}: {exc}")
            except LexiconSchemaError as exc:
                load_errors.append(f"{yaml_file.name}: {exc}")
            except yaml.YAMLError as exc:
                load_errors.append(f"{yaml_file.name}: YAML parse error: {exc}")
            except UnicodeDecodeError as exc:
                load_errors.append(f"{yaml_file.name}: UTF-8 decode error: {exc}")
            except OSError as exc:
                load_errors.append(f"{yaml_file.name}: I/O error: {exc}")

        if signature_warn_files:
            alert = self._maybe_emit_alert(
                kind="nlp_lexicon_feed_signature_invalid",
                severity="warn",
                subject=",".join(sorted(set(signature_warn_files))),
                reason=(
                    "lexicon feed signature missing, malformed, or invalid; "
                    "valid HMAC required for enforce mode"
                ),
            )
            if alert:
                alerts.append(alert)

        if signature_enforce_files:
            alert = self._maybe_emit_alert(
                kind="nlp_lexicon_feed_signature_invalid",
                severity="critical",
                subject=",".join(sorted(set(signature_enforce_files))),
                reason=(
                    "lexicon feed signature missing, malformed, or invalid; "
                    "valid HMAC required"
                ),
            )
            if alert:
                alerts.append(alert)
            return alerts

        if schema_too_new_errors:
            alert = self._maybe_emit_alert(
                kind="nlp_lexicon_feed_schema_too_new",
                severity="warn",
                subject=",".join(
                    sorted({e.split(":")[0] for e in schema_too_new_errors})
                ),
                reason="lexicon feed schema too new: "
                + "; ".join(schema_too_new_errors[:5]),
            )
            if alert:
                alerts.append(alert)
            return alerts

        if load_errors:
            alert = self._maybe_emit_alert(
                kind="lexicon_unreadable",
                severity="error",
                subject=",".join(sorted({e.split(":")[0] for e in load_errors})),
                reason="lexicon load failed: " + "; ".join(load_errors[:5]),
            )
            if alert:
                alerts.append(alert)
            return alerts

        # ── Cardinality cap (§10.2) ────────────────────────────────────────
        # Defends against Phase 19 long-tail explosion silently bloating memory.
        cap_errors: list[str] = []
        for fname, loaded in sorted(shadow.items()):
            count = len(loaded.entries)
            if count > self._max_entries_per_file:
                cap_errors.append(
                    f"{fname}: {count} entries exceeds cap {self._max_entries_per_file}"
                )
        if cap_errors:
            alert = self._maybe_emit_alert(
                kind="dictionary_overflow",
                severity="warn",
                subject=",".join(sorted({e.split(":")[0] for e in cap_errors})),
                reason="lexicon cardinality cap exceeded: " + "; ".join(cap_errors[:5]),
            )
            if alert:
                alerts.append(alert)
            return alerts

        # ── RSS budget check (§10.2 Bounded memory) ───────────────────────
        # Validate total process RSS after shadow alias indices are in memory.
        # max_rss_mb=0 disables the check (useful in tests and CI without
        # tight memory constraints).
        if self._max_rss_mb > 0:
            rss_kb = self._rss_kb_fn()
            if rss_kb > self._max_rss_mb * 1024:
                alert = self._maybe_emit_alert(
                    kind="dictionary_overflow",
                    severity="error",
                    subject="rss_budget",
                    reason=(
                        f"lexicon RSS budget exceeded: "
                        f"{rss_kb // 1024} MB > {self._max_rss_mb} MB"
                    ),
                )
                if alert:
                    alerts.append(alert)
                return alerts

        # ── Validate canonical IDs ─────────────────────────────────────────
        markets_ids = self._get_markets_ids()
        validation_errors: list[str] = []
        for fname, loaded in sorted(shadow.items()):
            errs = self._validate_entries(fname, loaded.entries, markets_ids)
            validation_errors.extend(errs)

        if validation_errors:
            alert = self._maybe_emit_alert(
                kind="lexicon_unreadable",
                severity="error",
                subject=",".join(
                    sorted({e.split(":")[0] for e in validation_errors})
                ),
                reason="lexicon validation failed: "
                + "; ".join(validation_errors[:5]),
            )
            if alert:
                alerts.append(alert)
            return alerts

        # ── Cross-file referential integrity validation (§10.21.3) ────────
        # Under all_or_nothing swap mode, validate cross-file references
        # (player→team, team→league, competition→parent, dialects→entities,
        # entities_negative→all) before committing the shadow snapshot.
        if cfg.nlp_lexicon_swap_atomicity == "all_or_nothing":
            from nlp.lexicon._xref import validate_xref  # noqa: PLC0415
            xref_errors = validate_xref(shadow)
            if xref_errors:
                alert = self._maybe_emit_alert(
                    kind="nlp_lexicon_atomic_swap_failed",
                    severity="error",
                    subject=",".join(
                        sorted({e.split(".")[0] for e in xref_errors})
                    ),
                    reason="cross-file referential integrity failed: "
                    + "; ".join(xref_errors[:5]),
                )
                if alert:
                    alerts.append(alert)
                return alerts

        # ── Build SymSpellIndex ────────────────────────────────────────────
        # §10.21.2 Symspell dictionary lifetime: built once at boot from
        # current lexicon snapshot; on lexicon swap, REBUILT (not mutated).
        # Build from union of all aliases across all loaded lexicon files.
        new_symspell = self._build_symspell_index(shadow)
        new_lexicon_version_id = self._compute_snapshot_id(shadow)

        # ── Atomic swap under lock ─────────────────────────────────────────
        # §10.21.2 Old-generation eviction contract: capture old generation,
        # add to deque (auto-evicts oldest), increment counter, log swap.
        # §10.21.3 Bounded swap latency: lock held ONLY for pointer flip.
        # Validation ran OUTSIDE the lock (above); lock is held only for
        # dict-pointer assignment + generation bookkeeping (target: < 50ms).
        lock_start = self._clock_mono()
        with self._lock:
            old_gen = self._generation_counter
            old_data = self._data
            old_symspell = self._symspell
            self._generation_counter += 1
            new_gen = self._generation_counter
            
            # Add old generation to deque; if deque is at maxlen, oldest is
            # auto-dropped (refcount → 0 once last in-flight request returns).
            # Old SymSpellIndex dereferenced atomically with old lexicon generation.
            if old_data:  # Skip if this is the first load (no old generation).
                self._old_generations.append((old_gen, old_data, old_symspell))
            
            # Atomic swap (data + SymSpellIndex).
            self._data = shadow
            self._symspell = new_symspell
            self._lexicon_version_id = new_lexicon_version_id
            
            # in_flight_count proxy: number of old generations currently
            # retained (each represents a snapshot still potentially
            # referenced by in-flight requests).
            in_flight_count = len(self._old_generations)
        lock_hold_ms = (self._clock_mono() - lock_start) * 1000.0
        self._last_lock_hold_ms = lock_hold_ms
        
        # Log outside lock (I/O outside critical section).
        self._logger.debug(
            "Lexicon swap: old_gen=%d, new_gen=%d, in_flight_count=%d, lock_hold_ms=%.2f",
            old_gen,
            new_gen,
            in_flight_count,
            lock_hold_ms,
        )

        return alerts

    def get(
        self, filename: str
    ) -> tuple[LexiconMeta, list[dict[str, Any]]] | None:
        """Return the current loaded ``(meta, entries)`` for *filename*.

        Returns ``None`` if the file has not been loaded yet.
        Thread-safe.
        
        §10.19 Locale future-keying: if *filename* ends with ``.tr-TR.yaml``
        and is not found, falls back to the ``.tr.yaml`` variant (forward
        compatibility for the rename deferred to §R-locale).
        """
        with self._lock:
            loaded = self._data.get(filename)
            # Fallback for forward-compatibility: `.tr-TR.yaml` → `.tr.yaml`.
            if loaded is None and filename.endswith(".tr-TR.yaml"):
                alt_filename = filename.replace(".tr-TR.yaml", ".tr.yaml")
                loaded = self._data.get(alt_filename)
        if loaded is None:
            return None
        return loaded.meta, loaded.entries

    def get_all(self) -> dict[str, tuple[LexiconMeta, list[dict[str, Any]]]]:
        """Return a snapshot of all currently loaded files.

        Thread-safe.
        """
        with self._lock:
            snapshot = dict(self._data)
        return {fname: (lf.meta, lf.entries) for fname, lf in sorted(snapshot.items())}

    def get_alias_index(
        self, filename: str
    ) -> "dict[str, AliasHit] | None":
        """Return the current alias lookup index for *filename*.

        Returns ``None`` if the file has not been loaded yet.
        Thread-safe (snapshot of the dict at call time).
        
        §10.19 Locale future-keying: if *filename* ends with ``.tr-TR.yaml``
        and is not found, falls back to the ``.tr.yaml`` variant (forward
        compatibility for the rename deferred to §R-locale).
        """
        with self._lock:
            loaded = self._data.get(filename)
            # Fallback for forward-compatibility: `.tr-TR.yaml` → `.tr.yaml`.
            if loaded is None and filename.endswith(".tr-TR.yaml"):
                alt_filename = filename.replace(".tr-TR.yaml", ".tr.yaml")
                loaded = self._data.get(alt_filename)
        if loaded is None:
            return None
        return loaded.alias_index

    @property
    def is_loaded(self) -> bool:
        """``True`` if at least one successful load has happened."""
        with self._lock:
            return bool(self._data)

    def get_symspell(self) -> "SymSpellIndex | None":
        """Return the current SymSpellIndex built from all lexicon aliases.

        Returns ``None`` if no lexicon has been loaded yet.
        Thread-safe (returns the current generation's index).
        
        §10.21.2 Symspell dictionary lifetime: built once at boot from current
        lexicon snapshot; on lexicon swap, REBUILT (not mutated). Old
        SymSpellIndex instance dereferenced atomically with old lexicon generation.
        """
        with self._lock:
            return self._symspell

    @property
    def last_lock_hold_ms(self) -> float:
        """Return the lock hold time (in milliseconds) for the most recent swap.
        
        §10.21.3 Bounded swap latency: used by CI bench to validate p95 ≤ 50ms.
        Returns 0.0 if no swap has occurred yet.
        Thread-safe (reads a float, which is atomic in CPython).
        """
        return self._last_lock_hold_ms

    # ── Internals ──────────────────────────────────────────────────────────

    def _build_symspell_index(self, data: dict[str, _LoadedFile]) -> "SymSpellIndex":
        """Build a new SymSpellIndex from the union of all aliases in *data*.

        §10.21.2 Symspell dictionary lifetime: REBUILT on every lexicon swap,
        never mutated in place. Each swap creates a fresh instance.
        """
        from nlp.vendor.symspell import SymSpellIndex  # noqa: PLC0415
        
        idx = SymSpellIndex(max_edit_distance=self._max_edit_distance)
        for fname, loaded in sorted(data.items()):
            for alias, hit in sorted(loaded.alias_index.items()):
                idx.add_term(alias, hit)
        return idx

    def _get_markets_ids(self) -> frozenset[str]:
        """Return the cached markets canonical ID set (lazy load)."""
        if self._markets_ids is None:
            self._markets_ids = _load_markets_ids(self._markets_path)
        return self._markets_ids

    def _validate_entries(
        self,
        filename: str,
        entries: list[dict[str, Any]],
        markets_ids: frozenset[str],
    ) -> list[str]:
        """Validate that every ``canonical_id`` in *entries* resolves.

        Rules
        -----
        * ``markets.tr.yaml``: ``canonical_id`` must be in the
          ``betting_markets.json`` closed enum.
        * Other files with ``canonical_id``: must be in
          ``league_catalog_ids`` (if provided) OR entry has
          ``freeform: true``.  When ``league_catalog_ids`` is ``None``
          (Phase 13a not yet deployed) only the ``freeform`` check applies.
        * ``dialects.tr.yaml`` / ``entities_negative.tr.yaml``: no
          ``canonical_id`` field — validation is skipped.

        Returns a (possibly empty) list of error strings.
        """
        if filename in _NO_CANONICAL_ID_FILES:
            return []

        errors: list[str] = []
        is_markets = filename == "markets.tr.yaml"

        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"{filename}[{i}]: entry must be a mapping")
                continue
            cid = entry.get("canonical_id")
            if cid is None:
                # Missing canonical_id is caught by layout tests; skip here.
                continue

            if is_markets:
                if cid not in markets_ids:
                    errors.append(
                        f"{filename}[{i}]: canonical_id={cid!r} not in "
                        f"betting_markets.json enum"
                    )
            else:
                # team / player / league / competition files.
                if bool(entry.get("freeform", False)):
                    continue  # explicitly exempt
                catalog = self._league_catalog_ids
                if catalog is not None and cid not in catalog:
                    errors.append(
                        f"{filename}[{i}]: canonical_id={cid!r} not in "
                        f"LeagueCatalog and not freeform:true"
                    )
                # If catalog is None (Phase 13a not yet deployed) → accept.

        return errors

    def _maybe_emit_alert(
        self,
        *,
        kind: str,
        severity: str,
        subject: str,
        reason: str,
    ) -> dict[str, Any] | None:
        """Return an ``nlp.alert.v1`` payload dict if the debounce window
        has elapsed, else ``None``.

        Mirrors the §7.4 ``SecAlertDebouncer`` per-(kind, subject) gate.
        The shared ``swarm.sdk.AlertDebouncer`` base is extracted in §10.20;
        until then we inline the same logic here.
        """
        key = (kind, subject)
        now = self._clock_mono()
        last = self._debounce_last.get(key, float("-inf"))
        if now - last < _ALERT_DEBOUNCE_S:
            return None
        self._debounce_last[key] = now
        return {
            "alert_id": self._new_id(),
            "kind": kind,
            "severity": severity,
            "producer": "nlp.intent.v1",
            "reason": reason[:1024],  # nlp.alert.v1 schema cap
            "request_id": None,
            "produced_at": self._clock_iso(),
        }
