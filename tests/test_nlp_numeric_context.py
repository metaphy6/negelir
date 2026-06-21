from __future__ import annotations

from nlp.normalize import normalize_input


def _find_event(events: tuple[dict[str, object], ...], kind: str) -> list[dict[str, object]]:
    return [event for event in events if event.get("kind") == kind]


def test_nlp_one_comma_five_ust_resolves_to_ou_15() -> None:
    result = normalize_input("1,5 üst")
    events = _find_event(result.normalization_events, "numeric_context_preferred")
    assert events, "Expected numeric context preference event"
    assert any(event["choice"] == "market_decimal" and event["token"] == "1,5" for event in events)


def test_nlp_one_comma_zero_skor_resolves_to_score_1_0() -> None:
    result = normalize_input("1,0 skor")
    events = _find_event(result.normalization_events, "numeric_context_preferred")
    assert events
    assert any(event["choice"] == "score_line" and event["token"] == "1,0" for event in events)


def test_nlp_bare_decimal_no_context_routes_to_disambiguation() -> None:
    result = normalize_input("1,5")
    events = _find_event(result.normalization_events, "numeric_disambiguation_offer")
    assert events
    assert events[0]["token"] == "1,5"


def test_nlp_decimal_with_oran_prefers_market_context() -> None:
    result = normalize_input("1.5 oran")
    events = _find_event(result.normalization_events, "numeric_context_preferred")
    assert events
    assert any(event["choice"] == "market_decimal" and event["token"] == "1.5" for event in events)


def test_nlp_decimal_with_gol_prefers_thousands_context() -> None:
    result = normalize_input("1.234 gol")
    events = _find_event(result.normalization_events, "numeric_context_preferred")
    assert events
    assert any(event["choice"] == "thousands_decimal" and event["token"] == "1.234" for event in events)


def test_nlp_score_and_market_parser_never_called_on_same_span() -> None:
    import inspect
    import nlp.normalize as nlp_norm

    source = inspect.getsource(nlp_norm)
    assert "score_parser(" not in source
    assert "market_line_parser(" not in source
    assert "choose_numeric_parse(" in source
