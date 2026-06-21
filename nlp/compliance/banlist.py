from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import yaml

from ai.common.logger import get_logger

_ALLOWED_ACTIONS = frozenset({"redact", "refuse", "replace_with"})
_CITATION_DELIMITER = "\n---\n"


@dataclass(frozen=True)
class BanlistEntry:
    term: str
    action: str
    replace_text: str | None = None
    expires_at_utc: str | None = None
    source_pr_url: str | None = None
    added_by: str | None = None
    added_at: str | None = None


def _sha8(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _token_boundaries_ok(text: str, start: int, end: int) -> bool:
    if start > 0 and _is_word_char(text[start - 1]):
        return False
    if end < len(text) and _is_word_char(text[end]):
        return False
    return True


def _sort_entries(entries: list[BanlistEntry]) -> list[BanlistEntry]:
    return sorted(entries, key=lambda entry: len(entry.term), reverse=True)


def _find_refusal_match(text: str, entries: list[BanlistEntry]) -> BanlistEntry | None:
    for entry in _sort_entries(entries):
        if entry.action != "refuse":
            continue
        term = entry.term
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            end = index + len(term)
            if _token_boundaries_ok(text, index, end):
                return entry
            start = index + 1
    return None


def _replace_terms(text: str, entries: list[BanlistEntry]) -> str:
    ordered = [entry for entry in _sort_entries(entries) if entry.action in {"redact", "replace_with"}]
    if not ordered:
        return text

    result: list[str] = []
    i = 0
    while i < len(text):
        match_found = False
        for entry in ordered:
            term = entry.term
            if not text.startswith(term, i):
                continue
            end = i + len(term)
            if not _token_boundaries_ok(text, i, end):
                continue
            replacement = entry.replace_text if entry.action == "replace_with" else "[***]"
            if replacement is None:
                replacement = "[***]"
            result.append(replacement)
            i = end
            match_found = True
            break
        if not match_found:
            result.append(text[i])
            i += 1
    return "".join(result)


def _render_refusal_template(locale: str) -> str:
    template_dir = Path(__file__).resolve().parents[1] / "templates"
    template_name = f"meta.compliance_refused.{locale}.j2"
    if not (template_dir / template_name).exists():
        template_name = "meta.compliance_refused.tr.j2"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir), encoding="utf-8"),
        autoescape=False,
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.get_template(template_name).render()


def _extract_citation_block(text: str) -> tuple[str, str | None]:
    parts = text.split(_CITATION_DELIMITER, 1)
    if len(parts) == 2:
        return parts[0], _CITATION_DELIMITER + parts[1]
    return text, None


def load_banlist_file(path: Path) -> tuple[dict[str, list[BanlistEntry]], str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"banlist file must contain a mapping at top level: {path}")

    entries_by_tenant: dict[str, list[BanlistEntry]] = {}
    for tenant_id, raw_items in raw.items():
        if not isinstance(tenant_id, str):
            continue
        if not isinstance(raw_items, list):
            continue
        entries: list[BanlistEntry] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            term = raw_item.get("term")
            action = raw_item.get("action")
            if not isinstance(term, str) or not term.strip():
                continue
            if not isinstance(action, str) or action not in _ALLOWED_ACTIONS:
                continue
            replace_text = raw_item.get("replace_text")
            if replace_text is not None and not isinstance(replace_text, str):
                replace_text = None
            expires_at_utc = raw_item.get("expires_at_utc")
            source_pr_url = raw_item.get("source_pr_url")
            added_by = raw_item.get("added_by")
            added_at = raw_item.get("added_at")
            entries.append(
                BanlistEntry(
                    term=term,
                    action=action,
                    replace_text=replace_text,
                    expires_at_utc=str(expires_at_utc) if isinstance(expires_at_utc, str) else None,
                    source_pr_url=str(source_pr_url) if isinstance(source_pr_url, str) else None,
                    added_by=str(added_by) if isinstance(added_by, str) else None,
                    added_at=str(added_at) if isinstance(added_at, str) else None,
                )
            )
        if entries:
            entries_by_tenant[tenant_id] = entries

    snapshot_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries_by_tenant, snapshot_sha


class BanlistStore:
    def __init__(self, path: Path | str, reload_s: int = 60) -> None:
        self._path = Path(path)
        self._reload_s = reload_s
        self._lock = threading.Lock()
        self._last_checked = 0.0
        self._mtime = 0.0
        self._snapshot: dict[str, list[BanlistEntry]] = {}
        self._snapshot_sha = ""

    def maybe_reload(self) -> None:
        now = time.time()
        if now - self._last_checked < self._reload_s:
            return
        self._last_checked = now
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return
        if mtime == self._mtime:
            return
        with self._lock:
            if mtime == self._mtime:
                return
            try:
                entries, sha = load_banlist_file(self._path)
            except Exception as exc:
                get_logger("nlp.compliance.banlist").warning(
                    "Failed to reload banlist %s: %s", self._path, exc
                )
                return
            self._snapshot = entries
            self._snapshot_sha = sha
            self._mtime = mtime

    @property
    def snapshot(self) -> dict[str, list[BanlistEntry]]:
        self.maybe_reload()
        return self._snapshot

    @property
    def snapshot_sha(self) -> str:
        self.maybe_reload()
        return self._snapshot_sha


def build_compliance_refusal_event(term: str, tenant_id: str) -> dict[str, str]:
    return {
        "kind": "compliance_refusal_triggered",
        "tenant_id_h": _sha8(tenant_id),
        "term_sha8": _sha8(term),
    }


def apply_banlist_overlay(
    answer_text: str,
    *,
    tenant_id: str | None = None,
    locale: str = "tr-TR",
    store: BanlistStore | None = None,
) -> str:
    if not tenant_id:
        return answer_text
    if store is None:
        path = Path(__file__).resolve().parent / "banlist.tr.yaml"
        store = BanlistStore(path, reload_s=60)
    entries = store.snapshot.get(tenant_id, [])
    if not entries:
        return answer_text

    refusal = _find_refusal_match(answer_text, entries)
    if refusal is not None:
        _, citation = _extract_citation_block(answer_text)
        refusal_text = _render_refusal_template(locale)
        return refusal_text + (citation or "")

    return _replace_terms(answer_text, entries)
