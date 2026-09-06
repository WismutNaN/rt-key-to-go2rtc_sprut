"""Access-control domain types independent of Rostelecom and MQTT."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable

from rtkey_gateway.errors import ValidationError


_MQTT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_NON_KEY_RE = re.compile(r"[^a-z0-9]+")


def _clean_text(value: object, fallback: str) -> str:
    text = "".join(
        character
        for character in str(value)
        if not unicodedata.category(character).startswith("C")
    )
    return (" ".join(text.split()) or fallback)[:512]


class AccessPointKind(str, Enum):
    INTERCOM = "intercom"
    BARRIER = "barrier"


@dataclass(frozen=True, slots=True)
class AccessPointId:
    value: str

    def __post_init__(self) -> None:
        value = str(self.value).strip()
        if not value or len(value) > 256:
            raise ValidationError(
                "Access point ID must be non-empty and at most 256 chars"
            )
        if any(
            character.isspace()
            or unicodedata.category(character).startswith("C")
            for character in value
        ):
            raise ValidationError(
                "Access point ID must not contain whitespace or controls"
            )
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class MqttDeviceKey:
    value: str

    def __post_init__(self) -> None:
        value = str(self.value).strip().lower()
        if not _MQTT_KEY_RE.fullmatch(value):
            raise ValidationError(
                "MQTT device key must match [a-z0-9][a-z0-9_-]{0,63}"
            )
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


def mqtt_device_key(kind: AccessPointKind, point_id: AccessPointId) -> MqttDeviceKey:
    """Build a readable stable key without trusting an external ID as a topic."""
    safe_id = _NON_KEY_RE.sub("_", point_id.value.lower()).strip("_")
    safe_id = safe_id[:39].rstrip("_") or "device"
    digest = hashlib.sha256(
        f"{kind.value}:{point_id.value}".encode("utf-8")
    ).hexdigest()[:10]
    return MqttDeviceKey(f"{kind.value}_{safe_id}_{digest}")


@dataclass(frozen=True, slots=True)
class AccessPoint:
    point_id: AccessPointId
    kind: AccessPointKind
    title: str
    camera_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "title",
            _clean_text(
                self.title,
                f"{self.kind.value.title()} {self.point_id.value[:8]}",
            ),
        )
        if self.camera_id is not None:
            camera_id = str(self.camera_id).strip()
            if not camera_id or len(camera_id) > 256 or any(
                character.isspace()
                or unicodedata.category(character).startswith("C")
                for character in camera_id
            ):
                object.__setattr__(self, "camera_id", None)
            else:
                object.__setattr__(self, "camera_id", camera_id)

    @property
    def identity(self) -> str:
        return f"{self.kind.value}:{self.point_id.value}"


@dataclass(frozen=True, slots=True)
class AccessBinding:
    point: AccessPoint
    mqtt_key: MqttDeviceKey
    present: bool = True

    @property
    def identity(self) -> str:
        return self.point.identity


@dataclass(frozen=True, slots=True)
class AccessCatalogSnapshot:
    points: tuple[AccessPoint, ...]
    refreshed_kinds: frozenset[AccessPointKind]
    failed_kinds: frozenset[AccessPointKind] = frozenset()

    def __post_init__(self) -> None:
        identities = [point.identity for point in self.points]
        if len(identities) != len(set(identities)):
            raise ValidationError("Access catalog contains duplicate device identities")
        if self.refreshed_kinds & self.failed_kinds:
            raise ValidationError("Access catalog kind cannot be refreshed and failed")


@dataclass(frozen=True, slots=True)
class AccessState:
    schema_version: int = 1
    bindings: dict[str, AccessBinding] = field(default_factory=dict)
    last_fetch_at: int | None = None
    last_success_at: int | None = None
    last_error: str | None = None
    authentication_failed: bool = False


def reconcile_access_state(
    state: AccessState,
    snapshot: AccessCatalogSnapshot,
    *,
    now: int,
) -> AccessState:
    """Update only provider categories that returned a confirmed response."""
    bindings = dict(state.bindings)
    for identity, binding in tuple(bindings.items()):
        if binding.point.kind in snapshot.refreshed_kinds:
            bindings[identity] = replace(binding, present=False)

    for point in snapshot.points:
        current = bindings.get(point.identity)
        bindings[point.identity] = AccessBinding(
            point=point,
            mqtt_key=(
                current.mqtt_key
                if current is not None
                else mqtt_device_key(point.kind, point.point_id)
            ),
            present=True,
        )

    partial_error = None
    if snapshot.failed_kinds:
        failed = ", ".join(sorted(kind.value for kind in snapshot.failed_kinds))
        partial_error = f"Partial access catalog; failed categories: {failed}"
    return AccessState(
        schema_version=state.schema_version,
        bindings=bindings,
        last_fetch_at=now,
        last_success_at=now,
        last_error=partial_error,
        authentication_failed=False,
    )


def access_bindings_by_key(
    bindings: Iterable[AccessBinding],
) -> dict[str, AccessBinding]:
    return {binding.mqtt_key.value: binding for binding in bindings}
