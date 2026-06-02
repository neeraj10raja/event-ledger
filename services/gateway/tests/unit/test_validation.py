from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.event import EventIn


def _good(**overrides):
    base = {
        "eventId": "evt-1",
        "accountId": "acct-1",
        "type": "CREDIT",
        "amount": "150.00",
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
    }
    base.update(overrides)
    return base


def test_valid_payload():
    e = EventIn.model_validate(_good())
    assert e.amount == Decimal("150.00")
    assert e.type == "CREDIT"


@pytest.mark.parametrize("override", [
    {"amount": "0"},
    {"amount": "-1"},
    {"type": "REFUND"},
    {"eventId": ""},
    {"accountId": ""},
    {"currency": ""},
])
def test_invalid_payloads(override):
    with pytest.raises(ValidationError):
        EventIn.model_validate(_good(**override))


def test_metadata_optional():
    e = EventIn.model_validate(_good(metadata={"source": "test"}))
    assert e.metadata == {"source": "test"}


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        EventIn.model_validate(_good(extraField="nope"))
