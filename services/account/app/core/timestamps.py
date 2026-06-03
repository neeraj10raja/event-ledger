from datetime import datetime, timezone


def to_utc_iso(dt: datetime) -> str:
    """Return an ISO 8601 UTC string with a 'Z' suffix.

    Normalizes timezone-aware datetimes so that stored timestamps sort
    chronologically by simple string comparison, regardless of the
    offset used in the inbound payload.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    iso = dt.astimezone(timezone.utc).isoformat()
    return iso.replace("+00:00", "Z")
