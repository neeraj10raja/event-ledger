from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings


def build_limiter() -> Limiter:
    s = get_settings()
    return Limiter(key_func=get_remote_address, enabled=s.rate_limit_enabled, default_limits=[])


limiter = build_limiter()
