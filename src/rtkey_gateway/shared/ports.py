"""Small shared-kernel ports without provider or media concepts."""

from __future__ import annotations

from typing import Protocol


class AccessTokenSource(Protocol):
    def read(self) -> str: ...


class Clock(Protocol):
    def time(self) -> float: ...
