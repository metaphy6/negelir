from common.text.turkish import parse_number_word


def test_parse_number_word_simple_terms() -> None:
    assert parse_number_word("sıfır") == 0
    assert parse_number_word("bir") == 1
    assert parse_number_word("on") == 10
    assert parse_number_word("yirmi") == 20


def test_parse_number_word_composite_numbers() -> None:
    assert parse_number_word("yirmi bir") == 21
    assert parse_number_word("iki yüz otuz dört") == 234
    assert parse_number_word("dokuz yüz doksan dokuz") == 999
