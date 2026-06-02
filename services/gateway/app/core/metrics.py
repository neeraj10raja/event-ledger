from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

registry = CollectorRegistry()

events_received_total = Counter(
    "events_received_total",
    "Events received at the Gateway",
    labelnames=("type", "result"),
    registry=registry,
)

events_applied_total = Counter(
    "events_applied_total",
    "Events successfully applied via Account Service",
    labelnames=("type",),
    registry=registry,
)

event_processing_duration_seconds = Histogram(
    "event_processing_duration_seconds",
    "End-to-end POST /events handler duration",
    labelnames=("endpoint",),
    registry=registry,
)

account_client_duration_seconds = Histogram(
    "account_client_duration_seconds",
    "Time spent calling the Account Service",
    labelnames=("outcome",),
    registry=registry,
)

# 0=closed, 1=half_open, 2=open
circuit_breaker_state = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state on the Account Service client",
    registry=registry,
)

outbox_depth = Gauge(
    "outbox_depth",
    "Number of events waiting in the outbox for replay",
    registry=registry,
)


def render() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
