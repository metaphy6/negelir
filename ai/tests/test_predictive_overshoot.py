"""Tests for known predictive-text overshoot offers."""

from tqu.normalizer import offer_predictive_overshoot, predictive_overshoot_pairs


def test_predictive_overshoot_known_pairs():
    pairs = predictive_overshoot_pairs()
    assert len(pairs) >= 50

    for original, offered in pairs.items():
        offers = offer_predictive_overshoot(f"galatasaray {original} mi")
        assert offers, f"missing offer for {original}"
        hit = next((item for item in offers if item.original_token == original), None)
        assert hit is not None, f"missing original token audit for {original}"
        assert hit.offered_token == offered
        assert hit.predictive_overshoot_audit == original


def test_predictive_overshoot_respects_cap():
    offers = offer_predictive_overshoot("yendir olucak olurmus", max_per_query=2)
    assert len(offers) == 2
