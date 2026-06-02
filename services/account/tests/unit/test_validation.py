from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.transaction import TransactionIn


def _good_payload(**overrides):
    base = {
        "eventId": "evt-1",
        "type": "CREDIT",
        "amount": "150.00",
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
    }
    base.update(overrides)
    return base


def test_valid_payload_parses():
    payload = TransactionIn.model_validate(_good_payload())
    assert payload.event_id == "evt-1"
    assert payload.amount == Decimal("150.00")


def test_rejects_negative_amount():
    with pytest.raises(ValidationError):
        TransactionIn.model_validate(_good_payload(amount="-1"))


def test_rejects_zero_amount():
    with pytest.raises(ValidationError):
        TransactionIn.model_validate(_good_payload(amount="0"))


def test_rejects_unknown_type():
    with pytest.raises(ValidationError):
        TransactionIn.model_validate(_good_payload(type="REFUND"))


def test_rejects_empty_event_id():
    with pytest.raises(ValidationError):
        TransactionIn.model_validate(_good_payload(eventId=""))


def test_rejects_missing_required_field():
    with pytest.raises(ValidationError):
        TransactionIn.model_validate({"eventId": "x", "type": "CREDIT", "amount": "1"})


def test_rejects_extra_fields():
    with pytest.raises(ValidationError):
        TransactionIn.model_validate(_good_payload(unexpected="boom"))


def test_amount_preserves_decimal_precision():
    payload = TransactionIn.model_validate(_good_payload(amount="100.00000001"))
    assert payload.amount == Decimal("100.00000001")
