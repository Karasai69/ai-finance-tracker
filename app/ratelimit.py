"""Простое ограничение частоты запросов в памяти процесса.

Подходит для одного сервера (как на бесплатном Render). Для нескольких серверов
счётчики нужно хранить в общем хранилище, например Redis.
"""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: float, clock=time.monotonic):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        hits = self._hits[key]
        border = self.clock() - self.window
        while hits and hits[0] <= border:
            hits.popleft()
        return hits

    def is_blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.max_attempts

    def retry_after(self, key: str) -> int:
        hits = self._prune(key)
        if len(hits) < self.max_attempts:
            return 0
        return max(1, int(hits[0] + self.window - self.clock()) + 1)

    def hit(self, key: str) -> None:
        self._prune(key).append(self.clock())

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


# 5 неудачных входов за 15 минут для пары «IP + email»
login_limiter = RateLimiter(max_attempts=5, window_seconds=15 * 60)
# 10 регистраций в час с одного IP
register_limiter = RateLimiter(max_attempts=10, window_seconds=60 * 60)
