from engine.quality import clean_pdf_text
from engine.text_normalizer import normalize_pdf_text


def test_normalize_pdf_text_joins_long_split_word():
    assert normalize_pdf_text("A P P L I C A T I O N") == "APPLICATION"


def test_normalize_pdf_text_restores_known_split_phrase():
    assert normalize_pdf_text("H O W T O R E A D") == "HOW TO READ"


def test_normalize_pdf_text_does_not_join_short_acronym():
    assert normalize_pdf_text("A U D I strategy") == "A U D I strategy"


def test_normalize_pdf_text_does_not_join_question_word_before_sentence():
    assert normalize_pdf_text("W H O is responsible") == "W H O is responsible"


def test_clean_pdf_text_applies_split_letter_normalizer():
    assert clean_pdf_text("A P P L I C A T I O N layer") == "APPLICATION layer"
