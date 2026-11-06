"""Strict money entry for Telegram rule prompts; no grouping or float rounding."""
import re
from decimal import Decimal

from fareflare.contracts import Money


def price_example(currency: str, locale: str) -> str:
    if Money(0, currency).exponent == 0:
        return "250"
    return "250.50" if locale in ("en-US", "en-GB") else "250,50"


def parse_amount(value: str, currency: str, locale: str, *, allow_zero: bool = False) -> int:
    exponent = Money(0, currency).exponent
    decimal = "." if locale in ("en-US", "en-GB") else ","
    pattern = r"[0-9]{1,9}"
    if exponent:
        pattern += rf"(?:{re.escape(decimal)}[0-9]{{1,{exponent}}})?"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("Enter an amount without currency signs or grouping separators")
    amount = int(Decimal(value.replace(",", ".")) * 10 ** exponent)
    if not (0 if allow_zero else 1) <= amount <= 100_000_000:
        raise ValueError("Amount is outside the supported range")
    return amount
