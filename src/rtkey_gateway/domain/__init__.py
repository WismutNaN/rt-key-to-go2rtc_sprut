"""Pure domain models for the gateway bounded contexts."""

from .access import (
    AccessBinding,
    AccessCatalogSnapshot,
    AccessPoint,
    AccessPointId,
    AccessPointKind,
    AccessState,
    MqttDeviceKey,
    access_bindings_by_key,
    mqtt_device_key,
    reconcile_access_state,
)

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
    "AccessBinding",
    "AccessCatalogSnapshot",
    "AccessPoint",
    "AccessPointId",
    "AccessPointKind",
    "AccessState",
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
    "MqttDeviceKey",
    "SecretUrl",
    "StreamName",
    "StreamNamingPolicy",
    "VideoMode",
    "access_bindings_by_key",
    "mqtt_device_key",
    "reconcile_access_state",
]
