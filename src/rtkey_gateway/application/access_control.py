"""Use cases for access discovery and one-shot open commands."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, replace

from rtkey_gateway.application.access_ports import (
    AccessControlProviderPort,
    AccessEventPort,
    AccessStateRepository,
)
from rtkey_gateway.domain import (
    AccessState,
    access_bindings_by_key,
    reconcile_access_state,
)
from rtkey_gateway.errors import AuthenticationError, GatewayError
from rtkey_gateway.shared import Clock


@dataclass(frozen=True, slots=True)
class AccessRefreshResult:
    discovered: int
    partial: bool
    succeeded: bool


class AccessControlService:
    """Runs independently from video and serializes all irreversible commands."""

    def __init__(
        self,
        provider: AccessControlProviderPort,
        repository: AccessStateRepository,
        events: AccessEventPort,
        clock: Clock,
        *,
        refresh_interval: int = 3_600,
        retry_interval: int = 60,
        open_cooldown: int = 5,
        queue_size: int = 64,
        logger: logging.Logger | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.events = events
        self.clock = clock
        self.refresh_interval = refresh_interval
        self.retry_interval = retry_interval
        self.open_cooldown = open_cooldown
        self.log = logger or logging.getLogger(__name__)
        self._commands: queue.Queue[str] = queue.Queue(maxsize=queue_size)
        self._last_attempt: dict[str, float] = {}

    def submit_command(self, mqtt_key: str) -> bool:
        try:
            self._commands.put_nowait(mqtt_key)
            return True
        except queue.Full:
            self.log.warning("Access command queue is full; rejecting %s", mqtt_key)
            self.events.publish_rejected(mqtt_key, "queue_full")
            return False

    def refresh_once(self) -> AccessRefreshResult:
        now = int(self.clock.time())
        try:
            state = self.repository.load()
            snapshot = self.provider.fetch_access_points()
            updated = reconcile_access_state(state, snapshot, now=now)
            self.repository.save(updated)
            self.events.publish_catalog(updated.bindings.values())
            self.events.publish_bridge_availability(True)
            present = sum(
                1 for binding in updated.bindings.values() if binding.present
            )
            if snapshot.failed_kinds:
                self.log.warning(updated.last_error)
            else:
                self.log.info("Published %d access point(s) to MQTT", present)
            return AccessRefreshResult(
                discovered=present,
                partial=bool(snapshot.failed_kinds),
                succeeded=True,
            )
        except GatewayError as exc:
            self.log.warning("Access catalog refresh failed: %s", exc)
            try:
                current = self.repository.load()
                failed = replace(
                    current,
                    last_fetch_at=now,
                    last_error=str(exc),
                    authentication_failed=isinstance(exc, AuthenticationError),
                )
                self.repository.save(failed)
                self.events.publish_catalog(failed.bindings.values())
            except GatewayError as state_exc:
                self.log.error("Could not preserve access state: %s", state_exc)
            self.events.publish_bridge_availability(False)
            return AccessRefreshResult(0, False, False)

    def handle_command(self, mqtt_key: str) -> bool:
        try:
            state = self.repository.load()
        except GatewayError as exc:
            self.log.error("Cannot load access catalog for command: %s", exc)
            self.events.publish_rejected(mqtt_key, "state_unavailable")
            return False

        binding = access_bindings_by_key(state.bindings.values()).get(mqtt_key)
        if binding is None or not binding.present:
            self.log.warning("Rejected command for unknown access key %s", mqtt_key)
            self.events.publish_rejected(mqtt_key, "unknown_device")
            return False

        now = self.clock.time()
        last_attempt = self._last_attempt.get(binding.identity)
        if last_attempt is not None and now - last_attempt < self.open_cooldown:
            self.log.warning("Access command for %s is in cooldown", mqtt_key)
            self.events.publish_rejected(mqtt_key, "cooldown")
            return False
        # Record before the remote call so duplicates cannot race through retries.
        self._last_attempt[binding.identity] = now

        try:
            self.provider.open_access_point(binding.point.point_id)
        except AuthenticationError as exc:
            self.log.error("Access open authentication failed for %s: %s", mqtt_key, exc)
            self.events.publish_open_failed(binding, "authentication_failed")
            return False
        except GatewayError as exc:
            self.log.warning("Access open failed for %s: %s", mqtt_key, exc)
            self.events.publish_open_failed(binding, "provider_error")
            return False

        self.log.info("Access open command succeeded for %s", mqtt_key)
        self.events.publish_open_succeeded(binding)
        return True

    def run(self, stop_event: threading.Event) -> None:
        self.events.start(self.submit_command)
        try:
            try:
                cached = self.repository.load()
                self.events.publish_catalog(cached.bindings.values())
            except GatewayError as exc:
                self.log.warning("Cached access state is unavailable: %s", exc)

            next_refresh = 0.0
            while not stop_event.is_set():
                now = self.clock.time()
                if now >= next_refresh:
                    result = self.refresh_once()
                    interval = (
                        self.refresh_interval if result.succeeded else self.retry_interval
                    )
                    next_refresh = self.clock.time() + interval

                timeout = min(1.0, max(0.05, next_refresh - self.clock.time()))
                try:
                    mqtt_key = self._commands.get(timeout=timeout)
                except queue.Empty:
                    continue
                try:
                    self.handle_command(mqtt_key)
                finally:
                    self._commands.task_done()
        finally:
            self.events.publish_bridge_availability(False)
            self.events.stop()
