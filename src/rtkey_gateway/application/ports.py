"""Narrow outbound ports used by the Video Gateway application layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rtkey_gateway.domain import CameraFeed, GatewayState, MediaProfile, SecretUrl, StreamName


class VideoCatalogPort(Protocol):
    def fetch_feeds(self) -> list[CameraFeed]: ...


class MediaGatewayPort(Protocol):
    def wait_ready(self, timeout: float) -> None: ...

    def upsert_stream(
        self, name: StreamName, upstream_url: SecretUrl, profile: MediaProfile
    ) -> None: ...

    def list_streams(self) -> set[str]: ...


class VideoStateRepository(Protocol):
    def load(self) -> GatewayState: ...

    def save(self, state: GatewayState) -> None: ...


@dataclass(frozen=True, slots=True)
class MediaProbeResult:
    server_reachable: bool
    available_streams: frozenset[str]


class MediaProbePort(Protocol):
    def probe(self, stream_names: set[str]) -> MediaProbeResult: ...
