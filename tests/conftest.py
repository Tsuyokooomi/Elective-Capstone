import pytest

from app.ratelimit import limiter


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """The rate limiter keeps its counters in memory. Start every test with empty counters."""
    limiter.reset()
    yield
    limiter.reset()
