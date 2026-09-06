"""Rostelecom Key anti-corruption adapters."""

from .video_catalog import (
    FallbackVideoCatalog,
    LegacyCameraApiStrategy,
    NewCameraApiStrategy,
)

__all__ = [
    "FallbackVideoCatalog",
    "LegacyCameraApiStrategy",
    "NewCameraApiStrategy",
]
