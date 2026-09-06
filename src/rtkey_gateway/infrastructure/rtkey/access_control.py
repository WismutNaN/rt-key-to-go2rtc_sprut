"""Rostelecom household API adapter for intercoms and barriers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import quote

from rtkey_gateway.domain import (
    AccessCatalogSnapshot,
    AccessPoint,
    AccessPointId,
    AccessPointKind,
)
from rtkey_gateway.errors import (
    AuthenticationError,
    GatewayError,
    SchemaError,
    TransportError,
    ValidationError,
)
from rtkey_gateway.infrastructure.http import HttpResponse, HttpTransport
from rtkey_gateway.shared import AccessTokenSource


ACCESS_DEVICES_BASE_URL = "https://household.key.rt.ru/api/v2/app/devices"


@dataclass(slots=True)
class RtKeyAccessControl:
    transport: HttpTransport
    token_source: AccessTokenSource
    timeout: float = 20.0
    logger: logging.Logger | None = None

    def _request(self, method: str, url: str) -> HttpResponse:
        token = self.token_source.read()
        response = self.transport.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Length": "0",
                "User-Agent": "rtkey-go2rtc-gateway/1.0",
            },
            timeout=self.timeout,
        )
        if response.status in {401, 403}:
            raise AuthenticationError("Access API rejected the Bearer token")
        if not 200 <= response.status < 300:
            raise TransportError(f"Access API returned HTTP {response.status}")
        return response

    @staticmethod
    def _map_point(item: Mapping[str, object], kind: AccessPointKind) -> AccessPoint:
        raw_id = item.get("id")
        if raw_id is None:
            raise SchemaError("Access device has no id")
        point_id = AccessPointId(str(raw_id))
        title = (
            item.get("name_by_company")
            or item.get("name")
            or item.get("title")
            or ""
        )
        camera_id = item.get("camera_id")
        return AccessPoint(
            point_id=point_id,
            kind=kind,
            title=str(title),
            camera_id=str(camera_id) if camera_id is not None else None,
        )

    def _fetch_kind(self, kind: AccessPointKind) -> tuple[AccessPoint, ...]:
        payload = self._request("GET", f"{ACCESS_DEVICES_BASE_URL}/{kind.value}").json()
        data = payload.get("data") if isinstance(payload, dict) else None
        devices = data.get("devices") if isinstance(data, dict) else None
        if not isinstance(devices, list):
            raise SchemaError(
                f"Access {kind.value} response has no data.devices list"
            )
        if not all(isinstance(item, dict) for item in devices):
            raise SchemaError(f"Access {kind.value} list contains non-object entries")

        result: dict[str, AccessPoint] = {}
        invalid = 0
        log = self.logger or logging.getLogger(__name__)
        for item in devices:
            try:
                point = self._map_point(item, kind)
            except (SchemaError, ValidationError) as exc:
                invalid += 1
                log.warning("Skipping invalid %s access device: %s", kind.value, exc)
                continue
            result.setdefault(point.identity, point)
        if devices and not result:
            raise SchemaError(
                f"Access {kind.value} API returned {invalid} invalid record(s)"
            )
        return tuple(result.values())

    def fetch_access_points(self) -> AccessCatalogSnapshot:
        points: list[AccessPoint] = []
        refreshed: set[AccessPointKind] = set()
        failed: set[AccessPointKind] = set()
        errors: list[GatewayError] = []
        log = self.logger or logging.getLogger(__name__)

        for kind in AccessPointKind:
            try:
                points.extend(self._fetch_kind(kind))
                refreshed.add(kind)
            except GatewayError as exc:
                failed.add(kind)
                errors.append(exc)
                log.warning("Access adapter %s failed: %s", kind.value, exc)

        if refreshed:
            return AccessCatalogSnapshot(
                points=tuple(points),
                refreshed_kinds=frozenset(refreshed),
                failed_kinds=frozenset(failed),
            )
        if errors and all(isinstance(error, AuthenticationError) for error in errors):
            raise AuthenticationError("All access APIs rejected the Bearer token")
        kinds = ", ".join(type(error).__name__ for error in errors)
        raise TransportError(f"All access API categories failed ({kinds})")

    def open_access_point(self, point_id: AccessPointId) -> None:
        encoded_id = quote(point_id.value, safe="")
        self._request("POST", f"{ACCESS_DEVICES_BASE_URL}/{encoded_id}/open")
