from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
ZERO_DECIMAL_CURRENCIES = frozenset({"HUF", "JPY", "TWD", "KRW", "VND", "CLP", "ISK"})
THREE_DECIMAL_CURRENCIES = frozenset({"BHD", "JOD", "KWD", "OMR", "TND"})


def currency_scale(currency: str) -> int:
    code = currency.strip().upper()
    if code in ZERO_DECIMAL_CURRENCIES:
        return 0
    if code in THREE_DECIMAL_CURRENCIES:
        return 3
    return 2


def parse_decimal_strict(value: Decimal | str | int) -> Decimal:
    """Strictly parse money into Decimal while explicitly rejecting float."""
    if isinstance(value, float):
        raise TypeError("Money amounts must be Decimal, str, or int; float is forbidden")
    if isinstance(value, bool):
        raise TypeError("Money amounts cannot be bool")
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid monetary amount: {value!r}") from exc
    if not dec.is_finite():
        raise ValueError(f"Monetary amount must be finite: {value!r}")
    return dec


class Money(BaseModel):
    """Exact monetary amount + ISO-4217 currency. Never uses floating point."""

    amount: Decimal
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise TypeError("Currency must be a 3-letter ISO string")
        code = v.strip().upper()
        if not ISO_CURRENCY_RE.match(code):
            raise ValueError(f"Invalid ISO-4217 currency code: {v!r}")
        return code

    @field_validator("amount", mode="before")
    @classmethod
    def _reject_float_amount(cls, v: Any) -> Decimal:
        return parse_decimal_strict(v)

    @model_validator(mode="after")
    def _validate_non_negative_and_scale(self) -> Money:
        if self.amount < Decimal("0"):
            raise ValueError(f"Money amount cannot be negative: {self.amount}")
        scale = currency_scale(self.currency)
        quant = Decimal("1") if scale == 0 else Decimal(f"1.{'0' * scale}")
        exponent = self.amount.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > scale:
            raise ValueError(
                f"Amount {self.amount} exceeds {scale} decimal places for {self.currency}"
            )
        object.__setattr__(self, "amount", self.amount.quantize(quant, rounding=ROUND_HALF_UP))
        return self

    @classmethod
    def of(cls, amount: Decimal | str | int, currency: str = "USD") -> Money:
        return cls(amount=parse_decimal_strict(amount), currency=currency)

    @classmethod
    def zero(cls, currency: str = "USD") -> Money:
        return cls.of("0", currency)

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        if self.amount < other.amount:
            raise ValueError(f"Subtraction results in negative money: {self.amount} - {other.amount}")
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, qty: int) -> Money:
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            raise ValueError(f"Quantity multiplier must be non-negative int, got {qty!r}")
        return Money(amount=self.amount * Decimal(qty), currency=self.currency)

    def __lt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount >= other.amount

    def to_str(self) -> str:
        return f"{self.amount} {self.currency}"
