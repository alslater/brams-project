import pytest

from server import is_valid_amount, is_valid_currency_code, is_valid_currency_list


class TestIsValidCurrencyCode:
    @pytest.mark.parametrize("code", ["USD", "GBP", "EUR", "JPY"])
    def test_accepts_three_uppercase_letters(self, code):
        assert is_valid_currency_code(code) is True

    @pytest.mark.parametrize(
        "code",
        [
            "usd",       # lowercase
            "Usd",       # mixed case
            "US",        # too short
            "USDD",      # too long
            "US1",       # contains digit
            "US$",       # contains symbol
            "",          # empty
            "USD;DROP",  # injection-style payload
        ],
    )
    def test_rejects_invalid_codes(self, code):
        assert is_valid_currency_code(code) is False


class TestIsValidCurrencyList:
    def test_accepts_single_code(self):
        assert is_valid_currency_list("USD") is True

    def test_accepts_multiple_comma_separated_codes(self):
        assert is_valid_currency_list("USD,EUR,GBP") is True

    def test_rejects_empty_string(self):
        assert is_valid_currency_list("") is False

    def test_rejects_list_with_one_invalid_code(self):
        assert is_valid_currency_list("USD,eur,GBP") is False

    def test_rejects_trailing_comma_empty_segment(self):
        assert is_valid_currency_list("USD,") is False

    def test_rejects_query_injection_payload(self):
        assert is_valid_currency_list("USD&amount=999999") is False

    def test_accepts_at_max_codes_boundary(self):
        codes = ",".join(["USD"] * 15)
        assert is_valid_currency_list(codes) is True

    def test_rejects_over_max_codes(self):
        codes = ",".join(["USD"] * 16)
        assert is_valid_currency_list(codes) is False


class TestIsValidAmount:
    @pytest.mark.parametrize("amount", ["1", "100", "0", "1.5", "0.0001", "123456789"])
    def test_accepts_numeric_strings(self, amount):
        assert is_valid_amount(amount) is True

    @pytest.mark.parametrize(
        "amount",
        [
            "-1",        # negative
            "1e10",      # scientific notation
            "abc",       # non-numeric
            "1,000",     # thousands separator
            "1.2.3",     # malformed decimal
            "",          # empty
            "1;DROP",    # injection-style payload
            " 1",        # leading whitespace
        ],
    )
    def test_rejects_invalid_amounts(self, amount):
        assert is_valid_amount(amount) is False
