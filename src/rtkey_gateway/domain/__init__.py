"""Pure domain model for the Video Gateway bounded context."""

from .media import (
    AudioMode,
    AudioPolicy,
    MediaPolicy,
    MediaProfile,
    MediaResolution,
    MediaVariant,
    VideoMode,
)
from .video import (
    CameraBinding,
    CameraFeed,
    CameraId,
    GatewayState,
    SecretUrl,
    StreamName,
    StreamNamingPolicy,
)

__all__ = [
    "AudioMode",
    "AudioPolicy",
    "CameraBinding",
    "CameraFeed",
    "CameraId",
    "GatewayState",
    "MediaProfile",
    "MediaPolicy",
    "MediaResolution",
    "MediaVariant",
    "SecretUrl",
    "StreamName",
    "StreamNamingPolicy",
    "VideoMode",
]
