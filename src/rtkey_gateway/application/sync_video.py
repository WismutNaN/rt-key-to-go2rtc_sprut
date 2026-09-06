"""Use case that keeps stable media gateway names pointed at fresh feeds."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace

from rtkey_gateway.application.ports import (
    MediaGatewayPort,
    MediaProbePort,
    VideoCatalogPort,
    VideoStateRepository,
)
from rtkey_gateway.domain import (
    CameraBinding,
    CameraFeed,
    GatewayState,
    MediaPolicy,
    MediaProfile,
    StreamNamingPolicy,
)
from rtkey_gateway.errors import AuthenticationError, GatewayError, ValidationError
from rtkey_gateway.shared import Clock


@dataclass(frozen=True, slots=True)
class SyncResult:
    discovered: int
    updated: int
    failed: int
    next_refresh_in: float


class SynchronizeVideoFeeds:
    def __init__(
        self,
        catalog: VideoCatalogPort,
        media_gateway: MediaGatewayPort,
        repository: VideoStateRepository,
        clock: Clock,
        media_policy: MediaPolicy,
        media_probe: MediaProbePort | None = None,
        naming_policy: StreamNamingPolicy | None = None,
        refresh_margin: int = 900,
        fallback_interval: int = 14_400,
        retry_min: int = 30,
        retry_max: int = 300,
        runtime_check_interval: int = 60,
        logger: logging.Logger | None = None,
    ) -> None:
        self.catalog = catalog
        self.media_gateway = media_gateway
        self.repository = repository
        self.clock = clock
        self.media_policy = media_policy
        self.media_probe = media_probe
        self.naming_policy = naming_policy or StreamNamingPolicy()
        self.refresh_margin = refresh_margin
        self.fallback_interval = fallback_interval
        self.retry_min = retry_min
        self.retry_max = retry_max
        self.runtime_check_interval = runtime_check_interval
        self.log = logger or logging.getLogger(__name__)

    def restore_last_good(self, state: GatewayState | None = None) -> int:
        state = state or self.repository.load()
        now = int(self.clock.time())
        restored = 0
        for binding in state.bindings.values():
            if not binding.present:
                continue
            if binding.last_good_upstream is None:
                continue
            if (
                binding.last_good_expires_at is not None
                and binding.last_good_expires_at <= now + 60
            ):
                continue
            profile = binding.last_good_profile or self.media_policy.profile_for(
                binding.camera_id.value
            )
            try:
                self.media_gateway.upsert_stream(
                    binding.stream_name, binding.last_good_upstream, profile
                )
                restored += 1
            except GatewayError as exc:
                self.log.warning(
                    "Could not restore camera %s: %s",
                    binding.camera_id.value,
                    exc,
                )
        return restored

    def restore_missing_runtime(self) -> int:
        """Repair runtime streams lost after a standalone go2rtc restart."""
        state = self.repository.load()
        runtime_streams = self.media_gateway.list_streams()
        now = int(self.clock.time())
        restored = 0
        for binding in state.bindings.values():
            if not binding.present or binding.last_good_upstream is None:
                continue
            if binding.stream_name.value in runtime_streams:
                continue
            if (
                binding.last_good_expires_at is not None
                and binding.last_good_expires_at <= now + 60
            ):
                continue
            profile = binding.last_good_profile or self.media_policy.profile_for(
                binding.camera_id.value
            )
            try:
                self.media_gateway.upsert_stream(
                    binding.stream_name, binding.last_good_upstream, profile
                )
                restored += 1
            except GatewayError as exc:
                self.log.warning(
                    "Could not reconcile camera %s: %s",
                    binding.camera_id.value,
                    exc,
                )
        return restored

    def _wait_with_runtime_checks(
        self, stop_event: threading.Event, delay: float
    ) -> bool:
        remaining = max(0.0, delay)
        while remaining > 0:
            interval = min(float(self.runtime_check_interval), remaining)
            if stop_event.wait(interval):
                return True
            remaining -= interval
            if remaining <= 0:
                break
            try:
                restored = self.restore_missing_runtime()
                if restored:
                    self.log.warning(
                        "Restored %d stream(s) after runtime reconciliation",
                        restored,
                    )
            except GatewayError as exc:
                self.log.warning("Runtime reconciliation failed: %s", exc)
        return False

    def _next_refresh_delay(self, expirations: list[int | None]) -> float:
        now = self.clock.time()
        deadlines = [
            (
                float(self.fallback_interval)
                if value is None
                else float(value) - now - self.refresh_margin
            )
            for value in expirations
        ]
        if not deadlines:
            deadlines.append(float(self.fallback_interval))
        return max(float(self.retry_min), min(deadlines))

    def refresh_once(self) -> SyncResult:
        state = self.repository.load()
        now = int(self.clock.time())
        try:
            feeds = self.catalog.fetch_feeds()
        except GatewayError as exc:
            failed_state = replace(
                state,
                last_error=str(exc),
                authentication_failed=isinstance(exc, AuthenticationError),
            )
            self.repository.save(failed_state)
            raise

        state = self.naming_policy.reconcile(state, feeds)
        bindings = dict(state.bindings)
        runtime_streams = self.media_gateway.list_streams()
        updated = 0
        failed = 0
        expirations: list[int | None] = []
        pending: dict[str, tuple[CameraFeed, CameraBinding, MediaProfile]] = {}

        for feed in feeds:
            uid = feed.camera_id.value
            binding = bindings[uid]
            profile = self.media_policy.profile_for(uid)
            try:
                if feed.expires_at is not None and feed.expires_at <= now + 60:
                    raise ValidationError(
                        "Camera API returned an expired streamer token"
                    )
                if (
                    binding.last_good_upstream == feed.upstream_url
                    and binding.last_good_profile == profile
                    and binding.stream_name.value in runtime_streams
                ):
                    # PATCH replaces the producer and can interrupt an active RTSP
                    # consumer. A provider may return the same token near expiry,
                    # so keep the existing lazy producer until something changed.
                    expiry = (
                        feed.expires_at
                        if feed.expires_at is not None
                        else binding.last_good_expires_at
                    )
                    bindings[uid] = replace(
                        binding,
                        last_good_expires_at=expiry,
                        last_error=None,
                    )
                    expirations.append(expiry)
                    continue
                self.media_gateway.upsert_stream(
                    binding.stream_name, feed.upstream_url, profile
                )
                pending[uid] = (feed, binding, profile)
            except GatewayError as exc:
                failed += 1
                bindings[uid] = replace(binding, last_error=str(exc))
                self.log.error("Camera %s update failed: %s", uid, exc)

        verified_names = {
            binding.stream_name.value
            for _feed, binding, _profile in pending.values()
        }
        if self.media_probe is not None and verified_names:
            verified_names = set(self.media_probe.probe(verified_names).available_streams)

        for uid, (feed, binding, profile) in pending.items():
            if binding.stream_name.value not in verified_names:
                failed += 1
                error = "RTSP/upstream probe failed after stream update"
                bindings[uid] = replace(binding, last_error=error)
                old_is_usable = (
                    binding.last_good_upstream is not None
                    and (
                        binding.last_good_expires_at is None
                        or binding.last_good_expires_at > now + 60
                    )
                )
                if old_is_usable:
                    old_profile = (
                        binding.last_good_profile
                        or self.media_policy.profile_for(binding.camera_id.value)
                    )
                    try:
                        self.media_gateway.upsert_stream(
                            binding.stream_name,
                            binding.last_good_upstream,
                            old_profile,
                        )
                    except GatewayError as exc:
                        error = f"{error}; last-known-good rollback failed"
                        bindings[uid] = replace(binding, last_error=error)
                        self.log.error("Camera %s rollback failed: %s", uid, exc)
                self.log.error("Camera %s media probe failed", uid)
                continue

            bindings[uid] = replace(
                binding,
                last_good_upstream=feed.upstream_url,
                last_good_profile=profile,
                last_good_expires_at=feed.expires_at,
                last_error=None,
            )
            expirations.append(feed.expires_at)
            updated += 1

        last_error = f"{failed} camera(s) failed to update" if failed else None
        state = replace(
            state,
            bindings=bindings,
            last_fetch_at=now,
            last_success_at=now if failed == 0 else state.last_success_at,
            last_error=last_error,
            authentication_failed=False,
        )
        self.repository.save(state)
        delay = self._next_refresh_delay(expirations)
        if failed:
            delay = float(self.retry_min)
        return SyncResult(len(feeds), updated, failed, delay)

    def run(self, stop_event: threading.Event) -> None:
        self.media_gateway.wait_ready(timeout=60.0)
        self.restore_last_good()
        retry_delay = float(self.retry_min)

        while not stop_event.is_set():
            try:
                result = self.refresh_once()
                retry_delay = float(self.retry_min)
                delay = result.next_refresh_in
                self.log.info(
                    "Sync complete: discovered=%d updated=%d failed=%d; next in %.0fs",
                    result.discovered,
                    result.updated,
                    result.failed,
                    delay,
                )
            except AuthenticationError as exc:
                delay = float(self.retry_max)
                self.log.error("Bearer token was rejected: %s", exc)
            except GatewayError as exc:
                delay = retry_delay
                retry_delay = min(float(self.retry_max), retry_delay * 2)
                self.log.error("Sync failed; retry in %.0fs: %s", delay, exc)

            if self._wait_with_runtime_checks(stop_event, delay):
                break
