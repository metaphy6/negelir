from pathlib import Path

from common.config import Config


def test_new_phase10_nlp_feature_flags_are_documented_in_env_example() -> None:
    env_text = Path("xops/env/.env.example").read_text(encoding="utf-8")
    for key in (
        "NEGELIR_NLP_PREAMBLE_STRIP_ENABLED",
        "NEGELIR_NLP_CONSONANT_ALTERNATION_ENABLED",
        "NEGELIR_NLP_ASSIMILATION_FOLD_ENABLED",
        "NEGELIR_NLP_COMPOUND_SPLIT_ENABLED",
        "NEGELIR_NLP_TR_PII_REDACT_ENABLED",
        "NEGELIR_NLP_LOANWORD_VARIANTS_ENABLED",
        "NEGELIR_NLP_LOANWORD_SINGULARISATION_ENABLED",
    ):
        assert key in env_text, f"{key} must be documented in xops/env/.env.example"


def test_new_phase10_nlp_feature_flags_defaults_true() -> None:
    cfg = Config()
    assert cfg.nlp_preamble_strip_enabled is True
    assert cfg.nlp_consonant_alternation_enabled is True
    assert cfg.nlp_assimilation_fold_enabled is True
    assert cfg.nlp_compound_split_enabled is True
    assert cfg.nlp_tr_pii_redact_enabled is True
    assert cfg.nlp_loanword_variants_enabled is True
    assert cfg.nlp_loanword_singularisation_enabled is True
