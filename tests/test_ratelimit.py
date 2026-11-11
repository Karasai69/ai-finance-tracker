from app.ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_blocks_after_limit_and_unblocks_after_window():
    clock = FakeClock()
    limiter = RateLimiter(max_attempts=3, window_seconds=60, clock=clock)
    for _ in range(3):
        assert not limiter.is_blocked("k")
        limiter.hit("k")
    assert limiter.is_blocked("k")
    assert 1 <= limiter.retry_after("k") <= 61

    clock.now += 61
    assert not limiter.is_blocked("k")


def test_keys_are_independent_and_reset_works():
    limiter = RateLimiter(max_attempts=1, window_seconds=60, clock=FakeClock())
    limiter.hit("a")
    assert limiter.is_blocked("a")
    assert not limiter.is_blocked("b")
    limiter.reset("a")
    assert not limiter.is_blocked("a")
