import pytest

from ratelimit import TokenBucket


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_starts_full_and_drains():
    clock = FakeClock()
    b = TokenBucket(capacity=3, rate=1, clock=clock)
    assert [b.allow() for _ in range(4)] == [True, True, True, False]


def test_never_exceeds_capacity_after_idle():
    clock = FakeClock()
    b = TokenBucket(capacity=5, rate=2, clock=clock)
    clock.advance(3600)
    assert b.tokens == 5
    assert sum(b.allow() for _ in range(10)) == 5


def test_fractional_refill_accumulates():
    clock = FakeClock()
    b = TokenBucket(capacity=2, rate=1, clock=clock)
    b.allow(); b.allow()
    # Polling the bucket every 250ms must not throw away partial tokens.
    for _ in range(3):
        clock.advance(0.25)
        assert b.allow() is False
    clock.advance(0.25)
    assert b.allow() is True


def test_retry_after():
    clock = FakeClock()
    b = TokenBucket(capacity=1, rate=4, clock=clock)
    assert b.allow()
    assert b.retry_after() == pytest.approx(0.25)


def test_rejects_bad_config():
    with pytest.raises(ValueError):
        TokenBucket(capacity=0, rate=1)
