"""Ports owned by the Access Control application boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from rtkey_gateway.domain import (
    AccessBinding,
    AccessCatalogSnapshot,
    AccessPointId,
    AccessState,
)


class AccessControlProviderPort(Protocol):
    def fetch_access_points(self) -> AccessCatalogSnapshot: ...

    def open_access_point(self, point_id: AccessPointId) -> None: ...


class AccessStateRepository(Protocol):
    def load(self) -> AccessState: ...

    def save(self, state: AccessState) -> None: ...


class AccessEventPort(Protocol):
    def start(self, command_handler: Callable[[str], bool]) -> None: ...

    def stop(self) -> None: ...

    def publish_catalog(self, bindings: Iterable[AccessBinding]) -> None: ...

    def publish_bridge_availability(self, online: bool) -> None: ...

    def publish_open_succeeded(self, binding: AccessBinding) -> None: ...

    def publish_open_failed(self, binding: AccessBinding, reason: str) -> None: ...

    def publish_rejected(self, mqtt_key: str, reason: str) -> None: ...
