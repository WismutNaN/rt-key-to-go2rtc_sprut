"""Validated environment configuration for the composition root."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass, field

from rtkey_gateway.domain import AudioMode, MediaPolicy, VideoMode
from rtkey_gateway.errors import ValidationError


def _required(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ValidationError(f"Required environment variable {name} is empty")
    return value


def _username(env: dict[str, str], name: str) -> str:
    value = _required(env, name)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value):
        raise ValidationError(
            f"{name} must contain only ASCII letters, digits, dot, underscore or dash"
        )
    return value


def _password(env: dict[str, str], name: str) -> str:
    value = _required(env, name)
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", value):
        raise ValidationError(
            f"{name} must be 8-128 safe ASCII characters"
        )
    return value


def _server_host(env: dict[str, str]) -> str:
    value = (env.get("SERVER_IP", "127.0.0.1").strip() or "127.0.0.1")
    candidate = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        if len(candidate) > 253 or not re.fullmatch(
            r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
            candidate,
        ):
            raise ValidationError("SERVER_IP must be an IPv4, IPv6 or DNS host")
    return candidate


def _positive_int(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValidationError(f"{name} must be positive")
    return value


def _port(env: dict[str, str], name: str, default: int) -> int:
    value = _positive_int(env, name, default)
    if value > 65_535:
        raise ValidationError(f"{name} must be between 1 and 65535")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    access_token_file: str
    state_file: str
    go2rtc_url: str
    go2rtc_api_username: str
    go2rtc_api_password: str = field(repr=False)
    rtsp_host: str
    rtsp_port: int
    rtsp_username: str
    rtsp_password: str = field(repr=False)
    snapshot_port: int
    snapshot_listen_port: int
    snapshot_workers: int
    media_policy: MediaPolicy
    allowed_stream_host_suffixes: tuple[str, ...]
    http_timeout: int
    rtsp_probe_timeout: int
    rtsp_probe_workers: int
    refresh_margin: int
    fallback_interval: int
    retry_min: int
    retry_max: int
    runtime_check_interval: int
    health_max_stale: int
    log_level: str

    @classmethod
    def from_env(cls, source: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if source is None else source)
        default_audio = AudioMode.parse(env.get("AUDIO_MODE", "pcma"))
        raw_overrides = env.get("AUDIO_OVERRIDES_JSON", "{}").strip() or "{}"
        try:
            overrides_payload = json.loads(raw_overrides)
        except json.JSONDecodeError as exc:
            raise ValidationError("AUDIO_OVERRIDES_JSON must be valid JSON") from exc
        if not isinstance(overrides_payload, dict):
            raise ValidationError("AUDIO_OVERRIDES_JSON must be an object")
        overrides = {
            str(camera_id): AudioMode.parse(str(mode))
            for camera_id, mode in overrides_payload.items()
        }
        default_video = VideoMode.parse(env.get("VIDEO_MODE", "h264"))
        raw_video_overrides = env.get("VIDEO_OVERRIDES_JSON", "{}").strip() or "{}"
        try:
            video_overrides_payload = json.loads(raw_video_overrides)
        except json.JSONDecodeError as exc:
            raise ValidationError("VIDEO_OVERRIDES_JSON must be valid JSON") from exc
        if not isinstance(video_overrides_payload, dict):
            raise ValidationError("VIDEO_OVERRIDES_JSON must be an object")
        video_overrides = {
            str(camera_id): VideoMode.parse(str(mode))
            for camera_id, mode in video_overrides_payload.items()
        }
        video_fps = _positive_int(env, "VIDEO_FPS", 30)
        if video_fps > 60:
            raise ValidationError("VIDEO_FPS cannot be greater than 60")
        suffixes = tuple(
            item.strip().lstrip(".")
            for item in env.get("ALLOWED_STREAM_HOST_SUFFIXES", "camera.rt.ru").split(",")
            if item.strip()
        )
        if not suffixes:
            raise ValidationError("At least one allowed streamer host suffix is required")

        retry_min = _positive_int(env, "RETRY_MIN_SECONDS", 30)
        retry_max = _positive_int(env, "RETRY_MAX_SECONDS", 300)
        if retry_max < retry_min:
            raise ValidationError("RETRY_MAX_SECONDS cannot be less than RETRY_MIN_SECONDS")
        rtsp_probe_workers = _positive_int(env, "RTSP_PROBE_WORKERS", 1)
        if rtsp_probe_workers > 32:
            raise ValidationError("RTSP_PROBE_WORKERS cannot be greater than 32")
        snapshot_workers = _positive_int(env, "SNAPSHOT_WORKERS", 2)
        if snapshot_workers > 16:
            raise ValidationError("SNAPSHOT_WORKERS cannot be greater than 16")

        return cls(
            access_token_file=env.get(
                "ACCESS_TOKEN_FILE", "/run/secrets/rtkey_access_token"
            ),
            state_file=env.get("STATE_FILE", "/data/state.json"),
            go2rtc_url=env.get("GO2RTC_URL", "http://go2rtc:1984"),
            go2rtc_api_username=_username(env, "GO2RTC_API_USERNAME"),
            go2rtc_api_password=_password(env, "GO2RTC_API_PASSWORD"),
            rtsp_host=_server_host(env),
            rtsp_port=_port(env, "RTSP_PORT", 8554),
            rtsp_username=_username(env, "RTSP_USERNAME"),
            rtsp_password=_password(env, "RTSP_PASSWORD"),
            snapshot_port=_port(env, "SNAPSHOT_PORT", 8080),
            snapshot_listen_port=_port(env, "SNAPSHOT_LISTEN_PORT", 8080),
            snapshot_workers=snapshot_workers,
            media_policy=MediaPolicy(
                default_audio=default_audio,
                audio_overrides=overrides,
                default_video=default_video,
                video_overrides=video_overrides,
                video_fps=video_fps,
            ),
            allowed_stream_host_suffixes=suffixes,
            http_timeout=_positive_int(env, "HTTP_TIMEOUT_SECONDS", 20),
            rtsp_probe_timeout=_positive_int(
                env, "RTSP_PROBE_TIMEOUT_SECONDS", 12
            ),
            rtsp_probe_workers=rtsp_probe_workers,
            refresh_margin=_positive_int(env, "REFRESH_MARGIN_SECONDS", 900),
            fallback_interval=_positive_int(env, "FALLBACK_REFRESH_SECONDS", 14_400),
            retry_min=retry_min,
            retry_max=retry_max,
            runtime_check_interval=_positive_int(
                env, "RUNTIME_CHECK_SECONDS", 60
            ),
            health_max_stale=_positive_int(env, "HEALTH_MAX_STALE_SECONDS", 21_600),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
        )
