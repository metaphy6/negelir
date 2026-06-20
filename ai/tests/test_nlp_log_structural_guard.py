"""Phase 10 §10.21 structural guard for NLP logger payload redaction."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
import sys

from ai.swarm.agents.nlp._log_filter import PIIScrubFilter, add_log_filter


def test_pii_scrub_filter_redacts_phone_from_log_args() -> None:
    flt = PIIScrubFilter()
    record = logging.LogRecord(
        name="swarm.agents.nlp.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="intent fail: %s",
        args=("telefon 0555 123 45 67",),
        exc_info=None,
    )

    assert flt.filter(record) is True
    rendered = record.getMessage()
    assert "0555 123 45 67" not in rendered
    assert "[REDACTED_PHONE]" in rendered


def test_nlp_log_filter_redacts_phone_in_exception_args() -> None:
    flt = PIIScrubFilter()
    try:
        raise ValueError("telefon 0555 123 45 67")
    except ValueError:
        record = logging.LogRecord(
            name="swarm.agents.nlp.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="caught exception",
            args=(),
            exc_info=sys.exc_info(),
        )

    assert flt.filter(record) is True
    assert "0555 123 45 67" not in str(record.exc_info[1])
    assert "[REDACTED_PHONE]" in str(record.exc_info[1])


def test_pii_scrub_filter_redacts_long_unrecognized_strings() -> None:
    flt = PIIScrubFilter()
    long_text = "x" * 64
    record = logging.LogRecord(
        name="swarm.agents.nlp.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="payload=%s",
        args=(long_text,),
        exc_info=None,
    )

    assert flt.filter(record) is True
    rendered = record.getMessage()
    assert long_text not in rendered
    assert "[REDACTED:len=64:sha8=" in rendered


def test_add_log_filter_is_idempotent_by_filter_type() -> None:
    logger = logging.getLogger("swarm.agents.nlp.test_guard")
    logger.filters.clear()

    add_log_filter(logger)
    add_log_filter(logger)

    pii_filters = [f for f in logger.filters if isinstance(f, PIIScrubFilter)]
    assert len(pii_filters) == 1


def test_nlp_every_logger_has_pii_scrub_filter() -> None:
    source_path = Path(__file__).resolve().parents[1] / "swarm" / "agents" / "nlp" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    agent_classes = {
        "NlpIntentAgent",
        "NlpDispatcherAgent",
        "NlpAnswerAgent",
        "NlpProofreaderAgent",
    }
    seen = set()

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in agent_classes:
            continue
        init_fn = next(
            (n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
            None,
        )
        assert init_fn is not None, f"{node.name} missing __init__"

        has_registration = False
        for call in ast.walk(init_fn):
            if not isinstance(call, ast.Call):
                continue
            if not (isinstance(call.func, ast.Name) and call.func.id == "add_log_filter"):
                continue

            for kw in call.keywords:
                if kw.arg != "filters":
                    continue
                if not isinstance(kw.value, ast.Tuple):
                    continue
                if any(
                    isinstance(elt, ast.Call)
                    and isinstance(elt.func, ast.Name)
                    and elt.func.id == "PIIScrubFilter"
                    for elt in kw.value.elts
                ):
                    has_registration = True
                    break
            if has_registration:
                break

        assert has_registration, f"{node.name}.__init__ must call add_log_filter(...PIIScrubFilter...)"
        seen.add(node.name)

    assert seen == agent_classes
