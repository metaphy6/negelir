from ai.common.numerics import is_valid_pmf


def test_is_valid_pmf_accepts_good_distribution() -> None:
    assert is_valid_pmf([0.2, 0.3, 0.5])


def test_is_valid_pmf_rejects_nan_inf_and_out_of_range() -> None:
    import math

    assert not is_valid_pmf([0.5, math.nan, 0.5])
    assert not is_valid_pmf([0.5, math.inf, -0.5])
    assert not is_valid_pmf([])
    # sum not equal to 1
    assert not is_valid_pmf([0.2, 0.2, 0.2])
