from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

registry = CollectorRegistry()

transactions_applied_total = Counter(
    "transactions_applied_total",
    "Transactions successfully applied to accounts",
    labelnames=("type", "result"),
    registry=registry,
)

transaction_apply_duration_seconds = Histogram(
    "transaction_apply_duration_seconds",
    "Duration of POST /accounts/{id}/transactions in seconds",
    registry=registry,
)


def render() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
