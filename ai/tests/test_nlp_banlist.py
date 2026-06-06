from __future__ import annotations

import hashlib
from pathlib import Path

from nlp.compliance.banlist import (
    BanlistStore,
    apply_banlist_overlay,
    build_compliance_refusal_event,
    load_banlist_file,
)


def _write_banlist_yaml(path: Path) -> None:
    path.write_text(
        """
tenant_a:
  - term: rakip bahis sitesi adı
    action: replace_with
    replace_text: '[***]'
  - term: yasak kelime
    action: redact
  - term: yasak ifadeler
    action: refuse
""",
        encoding='utf-8',
    )


def test_load_banlist_file_produces_snapshot_sha(tmp_path: Path) -> None:
    banlist_path = tmp_path / 'banlist.tr.yaml'
    _write_banlist_yaml(banlist_path)

    entries, sha = load_banlist_file(banlist_path)
    assert 'tenant_a' in entries
    assert sha == hashlib.sha256(banlist_path.read_bytes()).hexdigest()


def test_apply_banlist_overlay_preserves_citation_on_refuse(tmp_path: Path) -> None:
    banlist_path = tmp_path / 'banlist.tr.yaml'
    _write_banlist_yaml(banlist_path)
    store = BanlistStore(banlist_path, reload_s=0)
    store.maybe_reload()

    answer_text = "Maç tahmini burada yasak ifadeler içeriyor.\n---\ntahmin:123"
    refused = apply_banlist_overlay(answer_text, tenant_id='tenant_a', locale='tr-TR', store=store)

    assert refused.startswith('Bu konuda bilgi veremiyoruz.')
    assert refused.endswith('\n---\ntahmin:123')


def test_apply_banlist_overlay_chooses_longest_match_first(tmp_path: Path) -> None:
    banlist_path = tmp_path / 'banlist.tr.yaml'
    banlist_path.write_text(
        """
tenant_a:
  - term: bahis sitesi adı
    action: redact
  - term: rakip bahis sitesi adı
    action: redact
""",
        encoding='utf-8',
    )
    store = BanlistStore(banlist_path, reload_s=0)
    store.maybe_reload()

    answer_text = 'Bu rakip bahis sitesi adı bir örnektir.'
    result = apply_banlist_overlay(answer_text, tenant_id='tenant_a', locale='tr-TR', store=store)

    assert 'rakip [***]' not in result
    assert '[***]' in result


def test_build_compliance_refusal_event_hides_term_and_tenant(tmp_path: Path) -> None:
    event = build_compliance_refusal_event('yasak ifadeler', 'tenant_a')
    assert event['kind'] == 'compliance_refusal_triggered'
    assert event['tenant_id_h'] == hashlib.sha256(b'tenant_a').hexdigest()[:8]
    assert event['term_sha8'] == hashlib.sha256(b'yasak ifadeler').hexdigest()[:8]
