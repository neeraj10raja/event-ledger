from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

import httpx

from app.core.config import get_settings


class TransientHttpError(Exception):
    """Raised when a 5xx is received; tells tenacity to retry."""


def build_retry() -> AsyncRetrying:
    s = get_settings()
    return AsyncRetrying(
        stop=stop_after_attempt(s.retry_attempts),
        wait=wait_exponential_jitter(initial=s.retry_min_wait_seconds, max=s.retry_max_wait_seconds),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException, TransientHttpError)),
        reraise=True,
    )
