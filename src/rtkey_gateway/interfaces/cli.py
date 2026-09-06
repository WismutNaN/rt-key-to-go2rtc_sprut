"""Command-line interface used by Docker and management scripts."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote

from rtkey_gateway.application.health import evaluate_state
from rtkey_gateway.application.snapshot import GetCameraSnapshot
from rtkey_gateway.application.sync_video import SynchronizeVideoFeeds
from rtkey_gateway.config import Settings
from rtkey_gateway.errors import GatewayError
from rtkey_gateway.infrastructure.clock import SystemClock
from rtkey_gateway.infrastructure.go2rtc_gateway import Go2RtcMediaGateway
from rtkey_gateway.infrastructure.http import UrllibTransport
from rtkey_gateway.infrastructure.json_state import JsonVideoStateRepository
from rtkey_gateway.infrastructure.rtkey import (
    FallbackVideoCatalog,
    LegacyCameraApiStrategy,
    NewCameraApiStrategy,
)
from rtkey_gateway.infrastructure.rtsp_probe import Go2RtcRtspProbe
from rtkey_gateway.infrastructure.secrets import FileAccessTokenSource
from rtkey_gateway.interfaces.snapshot_http import SnapshotHttpService


@dataclass(slots=True)
class Container:
    settings: Settings
    repository: JsonVideoStateRepository
    media_gateway: Go2RtcMediaGateway
    media_probe: Go2RtcRtspProbe
    synchronizer: SynchronizeVideoFeeds
    snapshot_server: SnapshotHttpService


def build_container(settings: Settings) -> Container:
    transport = UrllibTransport()
    token_source = FileAccessTokenSource(settings.access_token_file)
    strategy_options = {
        "transport": transport,
        "token_source": token_source,
        "timeout": float(settings.http_timeout),
        "allowed_host_suffixes": settings.allowed_stream_host_suffixes,
    }
    catalog = FallbackVideoCatalog(
        [
            NewCameraApiStrategy(**strategy_options),
            LegacyCameraApiStrategy(**strategy_options),
        ]
    )
    media_gateway = Go2RtcMediaGateway(
        settings.go2rtc_url,
        settings.go2rtc_api_username,
        settings.go2rtc_api_password,
        transport,
        timeout=float(settings.http_timeout),
    )
    repository = JsonVideoStateRepository(settings.state_file)
    media_probe = Go2RtcRtspProbe(
        "go2rtc",
        8554,
        settings.rtsp_username,
        settings.rtsp_password,
        timeout=float(settings.rtsp_probe_timeout),
        workers=settings.rtsp_probe_workers,
    )
    synchronizer = SynchronizeVideoFeeds(
        catalog=catalog,
        media_gateway=media_gateway,
        repository=repository,
        clock=SystemClock(),
        media_policy=settings.media_policy,
        media_probe=media_probe,
        refresh_margin=settings.refresh_margin,
        fallback_interval=settings.fallback_interval,
        retry_min=settings.retry_min,
        retry_max=settings.retry_max,
        runtime_check_interval=settings.runtime_check_interval,
    )
    snapshot_server = SnapshotHttpService(
        "0.0.0.0",
        settings.snapshot_listen_port,
        settings.rtsp_username,
        settings.rtsp_password,
        GetCameraSnapshot(repository, media_gateway, settings.media_policy),
        workers=settings.snapshot_workers,
    )
    return Container(
        settings,
        repository,
        media_gateway,
        media_probe,
        synchronizer,
        snapshot_server,
    )


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _format_rtsp_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def command_show(container: Container) -> int:
    state = container.repository.load()
    cameras = [item for item in state.bindings.values() if item.present]
    if not cameras:
        print("Камеры ещё не обнаружены.", file=sys.stderr)
        return 2
    unverified = [item for item in cameras if item.last_good_upstream is None]
    if unverified:
        names = ", ".join(item.stream_name.value for item in unverified)
        print(
            f"Потоки ещё не прошли первичную проверку: {names}",
            file=sys.stderr,
        )
        return 2
    settings = container.settings
    user = quote(settings.rtsp_username, safe="")
    password = quote(settings.rtsp_password, safe="")
    host = _format_rtsp_host(settings.rtsp_host)

    print("==========================================")
    print("SprutHub camera connection data")
    print("==========================================")
    print(f"Username: {settings.rtsp_username}")
    print(f"Password: {settings.rtsp_password}")
    print()
    for binding in sorted(cameras, key=lambda item: item.stream_name.value):
        print(f"Camera: {binding.title} [{binding.camera_id.value}]")
        print(f"Stream name: {binding.stream_name.value}")
        for variant in settings.media_policy.variants_for(
            binding.camera_id.value,
            base_profile=binding.last_good_profile,
        ):
            stream_name = variant.stream_name_value(binding.stream_name.value)
            print(f"Resolution: {variant.resolution.key}")
            print("RTSP URL:")
            print(
                f"rtsp://{user}:{password}@{host}:{settings.rtsp_port}/"
                f"{stream_name}"
            )
            print("Snapshot URL:")
            print(
                f"http://{user}:{password}@{host}:{settings.snapshot_port}/snapshot/"
                f"{stream_name}.jpg"
            )
            print()
    print("==========================================")
    return 0


def command_status(container: Container) -> int:
    print(json.dumps(container.repository.sanitized(), ensure_ascii=False, indent=2))
    return 0


def _command_healthcheck(container: Container, *, deep: bool) -> int:
    state = container.repository.load()
    streams = container.media_gateway.list_streams()
    expected = {
        binding.stream_name.value
        for binding in state.bindings.values()
        if binding.present
    }
    rtsp = container.media_probe.probe(expected if deep else set())
    report = evaluate_state(
        state,
        now=int(time.time()),
        runtime_streams=streams,
        max_stale=container.settings.health_max_stale,
        rtsp_reachable=rtsp.server_reachable,
        rtsp_streams=rtsp.available_streams if deep else None,
    )
    label = "healthy"
    if not report.healthy:
        label = "unhealthy"
    elif report.degraded:
        label = "degraded"
    print(label)
    for message in report.messages:
        print(f"- {message}")
    return 0 if report.healthy else 1


def command_healthcheck(container: Container) -> int:
    return _command_healthcheck(container, deep=False)


def command_deep_healthcheck(container: Container) -> int:
    return _command_healthcheck(container, deep=True)


def command_sync_once(container: Container) -> int:
    container.media_gateway.wait_ready(timeout=60.0)
    result = container.synchronizer.refresh_once()
    print(
        f"discovered={result.discovered} updated={result.updated} "
        f"failed={result.failed}"
    )
    return 0 if result.failed == 0 else 1


def command_run(container: Container) -> int:
    stop_event = threading.Event()

    def stop(_signum, _frame) -> None:  # noqa: ANN001
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    container.snapshot_server.start()
    try:
        container.synchronizer.run(stop_event)
    finally:
        container.snapshot_server.stop()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RT Key video gateway controller")
    parser.add_argument(
        "command",
        choices=(
            "run",
            "sync-once",
            "show",
            "status",
            "healthcheck",
            "deep-healthcheck",
        ),
        nargs="?",
        default="run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        settings = Settings.from_env()
        _configure_logging(settings.log_level)
        container = build_container(settings)
        command = parse_args(argv).command
        return {
            "run": command_run,
            "sync-once": command_sync_once,
            "show": command_show,
            "status": command_status,
            "healthcheck": command_healthcheck,
            "deep-healthcheck": command_deep_healthcheck,
        }[command](container)
    except GatewayError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
