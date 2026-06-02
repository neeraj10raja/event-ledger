from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    event_id: str = Field(min_length=1, alias="eventId")
    type: Literal["CREDIT", "DEBIT"]
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=1)
    event_timestamp: datetime = Field(alias="eventTimestamp")

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_to_decimal(cls, v):
        return Decimal(str(v))


class TransactionApplied(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId")
    account_id: str = Field(alias="accountId")
    balance: Decimal
    currency: str
    applied_at: datetime = Field(alias="appliedAt")


class TransactionView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId")
    type: str
    amount: Decimal
    currency: str
    event_timestamp: datetime = Field(alias="eventTimestamp")


class BalanceView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: str = Field(alias="accountId")
    balance: Decimal
    currency: str


class AccountView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: str = Field(alias="accountId")
    balance: Decimal
    currency: str
    recent_transactions: list[TransactionView] = Field(alias="recentTransactions")
