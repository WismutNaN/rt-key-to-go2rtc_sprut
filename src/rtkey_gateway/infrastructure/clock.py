"""System clock adapter."""

import time


class SystemClock:
    def time(self) -> float:
        return time.time()
