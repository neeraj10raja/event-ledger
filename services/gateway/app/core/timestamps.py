from datetime import datetime, timezone


def to_utc_iso(dt: datetime) -> str:
    """Return an ISO 8601 UTC string with a 'Z' suffix.

    Stored event timestamps are normalized so that lexicographical
    ordering in the DB matches chronological ordering — important
    because upstream systems may submit the same instant with
    different timezone offsets.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    iso = dt.astimezone(timezone.utc).isoformat()
    return iso.replace("+00:00", "Z")
