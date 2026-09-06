"""Pure domain model for the Video Gateway bounded context."""

from .media import AudioMode, AudioPolicy, MediaProfile
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
    "SecretUrl",
    "StreamName",
    "StreamNamingPolicy",
]
