from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HoldingRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z^][A-Za-z0-9.^=-]*$")
    shares: float = Field(gt=0)
    price: float = Field(ge=0)


class HoldingUpdateRequest(HoldingRequest):
    pass


class OptionRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z^][A-Za-z0-9.^=-]*$")
    option_type: Literal["call", "put"]
    strike: float = Field(gt=0)
    expiry: str
    premium: float = Field(ge=0)
    contracts: int = Field(default=1, gt=0, strict=True)
    position: Literal["long", "short"] = "long"
    option_id: int | None = Field(default=None, gt=0)

    @field_validator("expiry")
    @classmethod
    def valid_expiry(cls, value):
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Expiry must be YYYY-MM-DD")
        return value


class OptionUpdateRequest(OptionRequest):
    pass


class ClosedOptionRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z^][A-Za-z0-9.^=-]*$")
    option_type: Literal["call", "put"]
    position: Literal["long", "short"]
    strike: Decimal = Field(gt=0, max_digits=16, decimal_places=6)
    expiry: date
    contracts: int = Field(gt=0, strict=True)
    open_premium: Decimal = Field(gt=0, max_digits=16, decimal_places=6)
    close_premium: Decimal = Field(ge=0, max_digits=16, decimal_places=6)
    opened_at: date
    closed_at: date
    fees: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    notes: str = Field(default="", max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value):
        return value.upper()

    @model_validator(mode="after")
    def valid_trade_dates(self):
        if self.opened_at > self.closed_at:
            raise ValueError("Closing date cannot precede opening date")
        if self.closed_at > datetime.now(timezone.utc).date():
            raise ValueError("Completed trades cannot have future dates")
        if self.closed_at > self.expiry:
            raise ValueError("Closing date cannot be after expiry")
        return self


class AccountingEntryRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    kind: Literal["deposit", "withdrawal", "dividend", "fee", "valuation", "link", "reverse"]
    amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    occurred_at: datetime
    nav_before: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    event_id: int | None = Field(default=None, gt=0)
    cycle: str | None = Field(default=None, min_length=1, max_length=80)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=6)
    note: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("occurred_at")
    @classmethod
    def timestamp_has_timezone(cls, value):
        if value.tzinfo is None or value > datetime.now(timezone.utc):
            raise ValueError("Use a non-future timestamp with a timezone")
        return value.astimezone(timezone.utc)