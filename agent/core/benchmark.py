"""Small in-memory timing collector for agent execution stages."""

from contextlib import contextmanager
from time import perf_counter
from typing import Dict, Iterator


class Benchmark:
    """Collect elapsed seconds by named stage without changing execution flow."""

    def __init__(self) -> None:
        self.timings: Dict[str, float] = {}

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.timings[stage] = self.timings.get(stage, 0.0) + (perf_counter() - started)

    def snapshot(self) -> Dict[str, float]:
        return dict(self.timings)
