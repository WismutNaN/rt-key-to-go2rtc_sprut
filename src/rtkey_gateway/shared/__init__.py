"""Minimal contracts that may be shared by independent bounded contexts."""

from .ports import AccessTokenSource, Clock

__all__ = ["AccessTokenSource", "Clock"]
