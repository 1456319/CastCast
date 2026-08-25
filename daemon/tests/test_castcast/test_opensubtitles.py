import pytest
from castcast.opensubtitles import language3

class TestLanguage3:
    def test_known_aliases(self):
        assert language3("en") == "eng"
        assert language3("english") == "eng"
        assert language3("es") == "spa"
        assert language3("spanish") == "spa"
        assert language3("fr") == "fre"
        assert language3("fra") == "fre"
        assert language3("french") == "fre"
        assert language3("de") == "ger"
        assert language3("deu") == "ger"
        assert language3("german") == "ger"

    def test_case_and_whitespace_insensitivity(self):
        assert language3(" EN ") == "eng"
        assert language3("English\n") == "eng"
        assert language3("eS") == "spa"

    def test_unknown_language_fallback(self):
        assert language3("italian") == "ita"
        assert language3("it") == "it"
        assert language3("por") == "por"
        assert language3("portuguese") == "por"

    def test_none_value(self):
        assert language3(None) == "eng"
        assert language3(None, default="spa") == "spa"

    def test_empty_value(self):
        assert language3("") == "eng"
        assert language3("   ") == "eng"
        assert language3("", default="spa") == "spa"
