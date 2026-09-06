"""Versioned Rostelecom camera adapters behind the VideoCatalogPort."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Protocol
from urllib.parse import quote, urlencode, urlparse

from rtkey_gateway.domain import CameraFeed, CameraId, SecretUrl
from rtkey_gateway.errors import (
    AuthenticationError,
    GatewayError,
    SchemaError,
    TransportError,
    ValidationError,
)
from rtkey_gateway.infrastructure.http import HttpResponse, HttpTransport
from rtkey_gateway.shared import AccessTokenSource


NEW_CAMERAS_URL = "https://keyapis.key.rt.ru/vc/api/v1/camera_video_data/list"
LEGACY_CAMERAS_URL = "https://vc.key.rt.ru/api/v1/cameras"


def decode_jwt_exp(token: str) -> int | None:
    """Read an unverified JWT exp claim only for scheduling refresh."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        exp = data.get("exp")
        return int(exp) if exp is not None and int(exp) > 0 else None
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def build_live_url(
    camera_id: str,
    streamer_url: str,
    streamer_token: str,
    allowed_host_suffixes: Iterable[str],
) -> SecretUrl:
    try:
        parsed = urlparse(str(streamer_url).strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Invalid streamer URL authority") from exc
    if parsed.scheme.lower() not in {"http", "https", "ws", "wss"}:
        raise ValidationError("Unsupported streamer URL scheme")
    if parsed.username or parsed.password or not hostname:
        raise ValidationError("Invalid streamer URL authority")

    hostname = hostname.lower().rstrip(".")
    suffixes = tuple(item.lower().lstrip(".") for item in allowed_host_suffixes if item)
    if suffixes and not any(
        hostname == suffix or hostname.endswith(f".{suffix}") for suffix in suffixes
    ):
        raise ValidationError("Streamer host is outside allowed domains")

    host = hostname
    if port is not None:
        host = f"{host}:{port}"
    path_id = quote(camera_id, safe="")
    query = urlencode(
        {
            "mp4-fragment-length": "0.5",
            "mp4-use-speed": "0",
            "mp4-afiller": "1",
            "token": streamer_token,
        }
    )
    return SecretUrl(f"https://{host}/stream/{path_id}/live.mp4?{query}")


class CameraApiStrategy(Protocol):
    name: str

    def fetch_feeds(self) -> list[CameraFeed]: ...


@dataclass(slots=True)
class _BaseCameraApiStrategy:
    transport: HttpTransport
    token_source: AccessTokenSource
    timeout: float = 20.0
    page_size: int = 100
    max_pages: int = 100
    allowed_host_suffixes: tuple[str, ...] = ("camera.rt.ru",)
    logger: logging.Logger | None = None

    def _request_json(self, url: str) -> object:
        token = self.token_source.read()
        response = self.transport.request(
            "GET",
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "rtkey-go2rtc-gateway/1.0",
            },
            timeout=self.timeout,
        )
        self._check_response(response)
        return response.json()

    @staticmethod
    def _check_response(response: HttpResponse) -> None:
        if response.status in {401, 403}:
            raise AuthenticationError("Camera API rejected the Bearer token")
        if not 200 <= response.status < 300:
            raise TransportError(f"Camera API returned HTTP {response.status}")

    def _to_feed(
        self,
        item: Mapping[str, object],
        *,
        uid_key: str,
        token_key: str,
        url_keys: tuple[str, ...],
    ) -> CameraFeed:
        uid = str(item.get(uid_key) or "").strip()
        token = str(item.get(token_key) or "").strip()
        streamer_url = ""
        for key in url_keys:
            value = item.get(key)
            if value:
                streamer_url = str(value).strip()
                break
        if not uid or not token or not streamer_url:
            raise SchemaError("Camera record is missing uid, streamer token or URL")
        title = str(item.get("title") or item.get("name") or f"Camera {uid[:8]}")
        return CameraFeed(
            camera_id=CameraId(uid),
            title=title,
            upstream_url=build_live_url(
                uid, streamer_url, token, self.allowed_host_suffixes
            ),
            expires_at=decode_jwt_exp(token),
        )

    def _collect_pages(
        self,
        page_loader: Callable[[int], list[Mapping[str, object]]],
        mapper: Callable[[Mapping[str, object]], CameraFeed],
    ) -> list[CameraFeed]:
        feeds: dict[str, CameraFeed] = {}
        saw_records = False
        invalid_records = 0
        previous_page_ids: tuple[str, ...] | None = None
        log = self.logger or logging.getLogger(__name__)

        for page_number in range(self.max_pages):
            offset = page_number * self.page_size
            items = page_loader(offset)
            if not items:
                break
            saw_records = True
            page_ids = tuple(str(item.get("uid") or item.get("id") or "") for item in items)
            if page_ids == previous_page_ids:
                raise SchemaError("Camera API repeated a page during pagination")
            previous_page_ids = page_ids

            for item in items:
                try:
                    feed = mapper(item)
                except (SchemaError, ValidationError) as exc:
                    raw_id = str(item.get("uid") or item.get("id") or "unknown")
                    safe_id = "".join(
                        char if char.isalnum() or char in "-_." else "_"
                        for char in raw_id[:64]
                    )
                    log.warning("Skipping invalid camera %s: %s", safe_id, exc)
                    invalid_records += 1
                    continue
                feeds.setdefault(feed.camera_id.value, feed)

            if len(items) < self.page_size:
                break
        else:
            raise SchemaError("Camera API pagination exceeded the safety limit")

        if invalid_records and not feeds:
            raise SchemaError(
                f"Camera API returned {invalid_records} invalid camera record(s)"
            )
        if invalid_records:
            log.warning(
                "Camera API skipped %d invalid record(s); keeping %d valid camera(s)",
                invalid_records,
                len(feeds),
            )
        if saw_records and not feeds:
            raise SchemaError("Camera API returned records but none were usable")
        return list(feeds.values())


class NewCameraApiStrategy(_BaseCameraApiStrategy):
    name = "rtkey-camera-video-data-v1"

    def fetch_feeds(self) -> list[CameraFeed]:
        def load(offset: int) -> list[Mapping[str, object]]:
            query = urlencode(
                {"paging.limit": self.page_size, "paging.offset": offset}
            )
            payload = self._request_json(f"{NEW_CAMERAS_URL}?{query}")
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise SchemaError("New camera API response has no data list")
            if not all(isinstance(item, dict) for item in payload["data"]):
                raise SchemaError("New camera API data contains non-object entries")
            return payload["data"]

        return self._collect_pages(
            load,
            lambda item: self._to_feed(
                item,
                uid_key="uid",
                token_key="streamerToken",
                url_keys=("streamerUrl",),
            ),
        )


class LegacyCameraApiStrategy(_BaseCameraApiStrategy):
    name = "rtkey-cameras-legacy"

    def fetch_feeds(self) -> list[CameraFeed]:
        def load(offset: int) -> list[Mapping[str, object]]:
            query = urlencode({"limit": self.page_size, "offset": offset})
            payload = self._request_json(f"{LEGACY_CAMERAS_URL}?{query}")
            data = payload.get("data") if isinstance(payload, dict) else None
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise SchemaError("Legacy camera API response has no data.items list")
            if not all(isinstance(item, dict) for item in items):
                raise SchemaError("Legacy camera API contains non-object entries")
            return items

        return self._collect_pages(
            load,
            lambda item: self._to_feed(
                item,
                uid_key="id",
                token_key="streamer_token",
                url_keys=("streamer_url", "streamerUrl"),
            ),
        )


class FallbackVideoCatalog:
    def __init__(
        self,
        strategies: Iterable[CameraApiStrategy],
        logger: logging.Logger | None = None,
    ) -> None:
        self.strategies = tuple(strategies)
        if not self.strategies:
            raise ValidationError("At least one camera API strategy is required")
        self.log = logger or logging.getLogger(__name__)

    def fetch_feeds(self) -> list[CameraFeed]:
        errors: list[GatewayError] = []
        empty_result: list[CameraFeed] | None = None
        for index, strategy in enumerate(self.strategies):
            try:
                feeds = strategy.fetch_feeds()
                if not feeds and index < len(self.strategies) - 1:
                    empty_result = feeds
                    self.log.warning(
                        "Camera adapter %s returned no cameras; trying fallback",
                        strategy.name,
                    )
                    continue
                if index:
                    self.log.warning("Using fallback camera adapter: %s", strategy.name)
                return feeds
            except GatewayError as exc:
                errors.append(exc)
                self.log.warning("Camera adapter %s failed: %s", strategy.name, exc)

        if empty_result is not None:
            return empty_result
        if errors and all(isinstance(error, AuthenticationError) for error in errors):
            raise AuthenticationError("All camera APIs rejected the Bearer token")
        kinds = ", ".join(type(error).__name__ for error in errors)
        raise TransportError(f"All camera API strategies failed ({kinds})")
