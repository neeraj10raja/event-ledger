import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, TypeVar

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import circuit_breaker_state

logger = get_logger("circuit_breaker")

T = TypeVar("T")


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


_STATE_GAUGE = {State.CLOSED: 0, State.HALF_OPEN: 1, State.OPEN: 2}


class CircuitBreakerError(Exception):
    """Raised when the breaker is open."""


@dataclass
class _Counters:
    consecutive_failures: int = 0


class AsyncCircuitBreaker:
    """A small async-native circuit breaker.

    - CLOSED: requests pass through; failures increment a consecutive counter.
      On the Nth failure, transitions to OPEN.
    - OPEN: requests fail fast with CircuitBreakerError. After reset_timeout
      seconds, transitions to HALF_OPEN.
    - HALF_OPEN: a single probe request is allowed. Success -> CLOSED;
      failure -> OPEN.
    """

    def __init__(self, *, fail_max: int, reset_timeout: float, name: str = "breaker"):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.name = name
        self._state = State.CLOSED
        self._counters = _Counters()
        self._opened_at: float | None = None
        self._half_open_in_flight = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> State:
        return self._state

    def _transition(self, new_state: State) -> None:
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        circuit_breaker_state.set(_STATE_GAUGE[new_state])
        logger.warning("circuit_breaker_state_change", breaker=self.name, old=old.value, new=new_state.value)

    async def call(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        async with self._lock:
            if self._state == State.OPEN:
                if self._opened_at is not None and (time.monotonic() - self._opened_at) >= self.reset_timeout:
                    self._transition(State.HALF_OPEN)
                    self._half_open_in_flight = True
                else:
                    raise CircuitBreakerError(f"Circuit '{self.name}' is OPEN")
            elif self._state == State.HALF_OPEN:
                if self._half_open_in_flight:
                    raise CircuitBreakerError(f"Circuit '{self.name}' probe already in flight")
                self._half_open_in_flight = True

        try:
            result = await func(*args, **kwargs)
        except Exception:
            async with self._lock:
                self._counters.consecutive_failures += 1
                if self._state == State.HALF_OPEN:
                    self._opened_at = time.monotonic()
                    self._half_open_in_flight = False
                    self._transition(State.OPEN)
                elif self._counters.consecutive_failures >= self.fail_max:
                    self._opened_at = time.monotonic()
                    self._transition(State.OPEN)
            raise
        else:
            async with self._lock:
                self._counters.consecutive_failures = 0
                if self._state == State.HALF_OPEN:
                    self._half_open_in_flight = False
                    self._transition(State.CLOSED)
            return result

    def reset(self) -> None:
        self._state = State.CLOSED
        self._counters = _Counters()
        self._opened_at = None
        self._half_open_in_flight = False
        circuit_breaker_state.set(0)


def build_breaker() -> AsyncCircuitBreaker:
    s = get_settings()
    return AsyncCircuitBreaker(
        fail_max=s.breaker_fail_max,
        reset_timeout=s.breaker_reset_timeout_seconds,
        name="account-service",
    )


account_breaker: AsyncCircuitBreaker = build_breaker()


def reset_breaker() -> None:
    account_breaker.reset()
