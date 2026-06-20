from ai.common.config import cfg
from nlp.normalize import normalize_input


def test_ocr_ligature_expand(monkeypatch):
    monkeypatch.setattr(cfg, "nlp_ocr_repair_force", False)
    result = normalize_input("ﬁnal maç", cfg=cfg)

    assert tuple(result.tokens[:2]) == ("final", "maç")
    assert any(event.get("kind") == "ocr_confusion_repair" for event in result.normalization_events)


def test_ocr_softhyphen_collapse(monkeypatch):
    monkeypatch.setattr(cfg, "nlp_ocr_repair_force", False)
    result = normalize_input("Gala-\u00AD\ntasaray maç", cfg=cfg)

    assert result.tokens[0] == "galatasaray"
    assert any(event.get("kind") == "ocr_confusion_repair" for event in result.normalization_events)


def test_ocr_no_repair_on_clean_input(monkeypatch):
    monkeypatch.setattr(cfg, "nlp_ocr_repair_force", False)
    result = normalize_input("galatasaray maç", cfg=cfg)

    assert not any(event.get("kind") == "ocr_confusion_repair" for event in result.normalization_events)
