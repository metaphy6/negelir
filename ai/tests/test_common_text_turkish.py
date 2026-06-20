from ai.common.text.turkish import int_to_number_word, parse_number_word


def test_parse_number_word_simple_terms() -> None:
    assert parse_number_word("sıfır") == 0
    assert parse_number_word("bir") == 1
    assert parse_number_word("on") == 10
    assert parse_number_word("yirmi") == 20


def test_int_to_number_word_roundtrip_0_to_9999() -> None:
    for value in range(0, 10000):
        phrase = int_to_number_word(value)
        assert parse_number_word(phrase) == value, f"roundtrip failed for {value}: {phrase}"


def test_int_to_number_word_ordinal_suffixes() -> None:
    assert int_to_number_word(1, register="ordinal") == "birinci"
    assert int_to_number_word(2, register="ordinal") == "ikinci"
    assert int_to_number_word(3, register="ordinal") == "üçüncü"
    assert int_to_number_word(21, register="ordinal") == "yirmi birinci"
    assert int_to_number_word(40, register="ordinal") == "kırkıncı"


def test_parse_number_word_composite_numbers() -> None:
    assert parse_number_word("yirmi bir") == 21
    assert parse_number_word("iki yüz otuz dört") == 234
    assert parse_number_word("dokuz yüz doksan dokuz") == 999
