from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    event_id: str = Field(min_length=1, alias="eventId")
    account_id: str = Field(min_length=1, alias="accountId")
    type: Literal["CREDIT", "DEBIT"]
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=1)
    event_timestamp: datetime = Field(alias="eventTimestamp")
    metadata: dict[str, Any] | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_to_decimal(cls, v):
        return Decimal(str(v))


class EventOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId")
    account_id: str = Field(alias="accountId")
    type: str
    amount: Decimal
    currency: str
    event_timestamp: datetime = Field(alias="eventTimestamp")
    metadata: dict[str, Any] | None = None
    status: str
    received_at: datetime = Field(alias="receivedAt")
    trace_id: str | None = Field(default=None, alias="traceId")


class EventListOut(BaseModel):
    items: list[EventOut]
    total: int
