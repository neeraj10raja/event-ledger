import asyncio

import pytest

from app.resilience.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerError, State


async def _ok():
    return "ok"


async def _boom():
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_closed_breaker_passes_calls_through():
    cb = AsyncCircuitBreaker(fail_max=3, reset_timeout=10)
    assert await cb.call(_ok) == "ok"
    assert cb.state == State.CLOSED


@pytest.mark.asyncio
async def test_breaker_opens_after_fail_max():
    cb = AsyncCircuitBreaker(fail_max=3, reset_timeout=10)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(_boom)
    assert cb.state == State.OPEN


@pytest.mark.asyncio
async def test_open_breaker_short_circuits():
    cb = AsyncCircuitBreaker(fail_max=1, reset_timeout=10)
    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    assert cb.state == State.OPEN
    with pytest.raises(CircuitBreakerError):
        await cb.call(_ok)  # would succeed, but the breaker refuses


@pytest.mark.asyncio
async def test_breaker_half_open_and_recovers():
    cb = AsyncCircuitBreaker(fail_max=1, reset_timeout=0.05)
    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    assert cb.state == State.OPEN

    await asyncio.sleep(0.1)
    # The first call after timeout becomes the probe. Success closes the breaker.
    assert await cb.call(_ok) == "ok"
    assert cb.state == State.CLOSED


@pytest.mark.asyncio
async def test_breaker_half_open_failure_reopens():
    cb = AsyncCircuitBreaker(fail_max=1, reset_timeout=0.05)
    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    await asyncio.sleep(0.1)
    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    assert cb.state == State.OPEN


@pytest.mark.asyncio
async def test_success_resets_consecutive_failure_count():
    cb = AsyncCircuitBreaker(fail_max=3, reset_timeout=10)
    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    await cb.call(_ok)  # success resets the counter
    # We should now be able to fail 2 more times without tripping
    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    assert cb.state == State.CLOSED
