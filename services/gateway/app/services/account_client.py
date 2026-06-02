import time
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import AccountServiceClientError, AccountServiceUnavailableError
from app.core.logging import get_logger
from app.core.metrics import account_client_duration_seconds
from app.resilience.circuit_breaker import CircuitBreakerError, account_breaker
from app.resilience.retry import TransientHttpError, build_retry

logger = get_logger("account_client")


class AccountClient:
    """Resilient client for the Account Service.

    Composition: circuit_breaker( retry( single_http_call ) ).
    Each Gateway request consumes exactly one breaker attempt; inner
    retries do not inflate the failure counter, so a brief blip won't
    trip the breaker but a sustained outage will.
    """

    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None):
        s = get_settings()
        self.base_url = base_url or s.account_service_url
        self.timeout = httpx.Timeout(s.account_call_timeout_seconds, connect=s.account_connect_timeout_seconds)
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def apply_transaction(
        self,
        account_id: str,
        *,
        event_id: str,
        type_: str,
        amount: Decimal,
        currency: str,
        event_timestamp: str,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        outcome = "ok"
        try:
            result = await self._call_with_resilience(account_id, event_id, type_, amount, currency, event_timestamp)
            return result
        except CircuitBreakerError as exc:
            outcome = "breaker_open"
            logger.warning("account_call_breaker_open", error=str(exc))
            raise AccountServiceUnavailableError("Account Service temporarily unavailable (circuit open)") from exc
        except AccountServiceClientError:
            outcome = "client_error"
            raise
        except Exception as exc:
            outcome = "failure"
            logger.warning("account_call_failed", error=str(exc), error_type=type(exc).__name__)
            raise AccountServiceUnavailableError("Account Service unreachable") from exc
        finally:
            account_client_duration_seconds.labels(outcome=outcome).observe(time.perf_counter() - start)

    async def _call_with_resilience(
        self,
        account_id: str,
        event_id: str,
        type_: str,
        amount: Decimal,
        currency: str,
        event_timestamp: str,
    ) -> dict[str, Any]:
        async def _retried() -> dict[str, Any]:
            retrying = build_retry()
            result: dict[str, Any] | None = None
            async for attempt in retrying:
                with attempt:
                    result = await self._one_call(account_id, event_id, type_, amount, currency, event_timestamp)
                if attempt.retry_state.outcome and not attempt.retry_state.outcome.failed:
                    attempt.retry_state.set_result(result)
            return result  # type: ignore[return-value]

        return await account_breaker.call(_retried)

    async def _one_call(
        self,
        account_id: str,
        event_id: str,
        type_: str,
        amount: Decimal,
        currency: str,
        event_timestamp: str,
    ) -> dict[str, Any]:
        client = await self._get_client()
        payload = {
            "eventId": event_id,
            "type": type_,
            "amount": str(amount),
            "currency": currency,
            "eventTimestamp": event_timestamp,
        }
        response = await client.post(f"/accounts/{account_id}/transactions", json=payload)
        if 500 <= response.status_code < 600:
            raise TransientHttpError(f"Account Service {response.status_code}: {response.text}")
        if 400 <= response.status_code < 500:
            raise AccountServiceClientError(
                f"Account Service rejected request ({response.status_code})",
                code="ACCOUNT_SERVICE_CLIENT_ERROR",
                status_code=response.status_code,
            )
        response.raise_for_status()
        return response.json()

    async def health(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/health", timeout=0.5)
            return response.status_code == 200
        except Exception:
            return False
