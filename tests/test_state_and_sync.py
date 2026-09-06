from __future__ import annotations

import tempfile
import unittest
import json
from dataclasses import replace
from pathlib import Path

from rtkey_gateway.application.sync_video import SynchronizeVideoFeeds
from rtkey_gateway.application.ports import MediaProbeResult
from rtkey_gateway.domain import (
    AudioMode,
    CameraBinding,
    CameraFeed,
    CameraId,
    GatewayState,
    MediaProfile,
    MediaPolicy,
    SecretUrl,
    StreamName,
)
from rtkey_gateway.errors import MediaGatewayError, StateError
from rtkey_gateway.infrastructure.json_state import JsonVideoStateRepository
from tests.helpers import FakeClock, MemoryRepository


class Catalog:
    def __init__(self, feeds: list[CameraFeed]) -> None:
        self.feeds = feeds

    def fetch_feeds(self) -> list[CameraFeed]:
        return self.feeds


class Gateway:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.names: set[str] = set()
        self.updates: list[tuple[str, str, MediaProfile]] = []

    def wait_ready(self, timeout: float) -> None:
        return None

    def upsert_stream(self, name, upstream_url, profile) -> None:  # noqa: ANN001
        if name.value in self.fail:
            raise MediaGatewayError("mock update failed")
        self.names.add(name.value)
        self.updates.append((name.value, upstream_url.value, profile))

    def list_streams(self) -> set[str]:
        return self.names


class Probe:
    def __init__(self, available: set[str]) -> None:
        self.available = available

    def probe(self, stream_names: set[str]) -> MediaProbeResult:
        return MediaProbeResult(True, frozenset(stream_names & self.available))


def make_feed(uid: str, title: str, exp: int | None) -> CameraFeed:
    return CameraFeed(
        CameraId(uid),
        title,
        SecretUrl(f"https://live.camera.rt.ru/{uid}?token=secret"),
        exp,
    )


class StateRepositoryTests(unittest.TestCase):
    def test_round_trip_and_backup_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            repository = JsonVideoStateRepository(path)
            state = GatewayState(
                bindings={
                    "uid": CameraBinding(
                        CameraId("uid"),
                        StreamName("podezd"),
                        "Подъезд",
                        last_good_upstream=SecretUrl("https://x.camera.rt.ru/?token=secret"),
                        last_good_profile=MediaProfile(AudioMode.PCMU),
                        last_good_expires_at=2_000_000_000,
                    )
                }
            )
            repository.save(state)
            repository.save(replace(state, last_fetch_at=10))
            self.assertEqual(repository.load().last_fetch_at, 10)
            path.write_text("broken", encoding="utf-8")
            recovered = repository.load()
            self.assertIsNone(recovered.last_fetch_at)
            self.assertEqual(
                recovered.bindings["uid"].last_good_profile.audio_mode,
                AudioMode.PCMU,
            )
            self.assertNotIn("last_good_upstream", str(repository.sanitized()))
            repository.save(recovered)
            self.assertEqual(repository.load().bindings["uid"].stream_name.value, "podezd")

    def test_invalid_state_boolean_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "bindings": {
                            "uid": {
                                "camera_id": "uid",
                                "stream_name": "camera",
                                "title": "Camera",
                                "present": "false",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(StateError):
                JsonVideoStateRepository(path).load()

    def test_legacy_h264_profile_is_forgotten_for_safe_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "bindings": {
                            "uid": {
                                "camera_id": "uid",
                                "stream_name": "camera",
                                "title": "Camera",
                                "present": True,
                                "last_good_profile": {
                                    "video_mode": "h264",
                                    "video_fps": 30,
                                    "audio_mode": "pcma",
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            state = JsonVideoStateRepository(path).load()
            self.assertIsNone(state.bindings["uid"].last_good_profile)


class SynchronizerTests(unittest.TestCase):
    def test_refresh_updates_all_and_schedules_before_expiry(self) -> None:
        now = 1_000
        feeds = [make_feed("a", "Подъезд", 5_000), make_feed("b", "Двор", 6_000)]
        repository = MemoryRepository()
        gateway = Gateway()
        use_case = SynchronizeVideoFeeds(
            Catalog(feeds), gateway, repository, FakeClock(now), MediaPolicy(),
            refresh_margin=900, fallback_interval=14_400, retry_min=30,
        )
        result = use_case.refresh_once()
        self.assertEqual(result.updated, 2)
        self.assertEqual(result.next_refresh_in, 3_100)
        self.assertEqual(
            gateway.names,
            {
                "podezd",
                "dvor",
            },
        )

    def test_partial_failure_keeps_other_camera_success(self) -> None:
        repository = MemoryRepository()
        gateway = Gateway({"podezd"})
        use_case = SynchronizeVideoFeeds(
            Catalog([make_feed("a", "Подъезд", 5_000), make_feed("b", "Двор", 6_000)]),
            gateway,
            repository,
            FakeClock(1_000),
            MediaPolicy(),
        )
        result = use_case.refresh_once()
        self.assertEqual((result.updated, result.failed), (1, 1))
        self.assertIsNone(repository.state.bindings["a"].last_good_upstream)
        self.assertIsNotNone(repository.state.bindings["b"].last_good_upstream)

    def test_missing_exp_uses_fallback_even_when_other_exp_is_longer(self) -> None:
        use_case = SynchronizeVideoFeeds(
            Catalog([make_feed("a", "A", None), make_feed("b", "B", 100_000)]),
            Gateway(),
            MemoryRepository(),
            FakeClock(1_000),
            MediaPolicy(),
            refresh_margin=900,
            fallback_interval=14_400,
        )
        self.assertEqual(use_case.refresh_once().next_refresh_in, 14_400)

    def test_restore_skips_camera_no_longer_present(self) -> None:
        state = GatewayState(
            bindings={
                "old": CameraBinding(
                    CameraId("old"),
                    StreamName("old_camera"),
                    "Removed camera",
                    present=False,
                    last_good_upstream=SecretUrl(
                        "https://live.camera.rt.ru/old?token=secret"
                    ),
                    last_good_expires_at=5_000,
                )
            }
        )
        gateway = Gateway()
        use_case = SynchronizeVideoFeeds(
            Catalog([]), gateway, MemoryRepository(state), FakeClock(1_000), MediaPolicy()
        )
        self.assertEqual(use_case.restore_last_good(), 0)
        self.assertEqual(gateway.names, set())

    def test_runtime_reconciliation_restores_only_missing_valid_stream(self) -> None:
        state = GatewayState(
            bindings={
                "missing": CameraBinding(
                    CameraId("missing"),
                    StreamName("missing_camera"),
                    "Missing",
                    last_good_upstream=SecretUrl(
                        "https://live.camera.rt.ru/missing?token=secret"
                    ),
                    last_good_expires_at=5_000,
                ),
                "existing": CameraBinding(
                    CameraId("existing"),
                    StreamName("existing_camera"),
                    "Existing",
                    last_good_upstream=SecretUrl(
                        "https://live.camera.rt.ru/existing?token=secret"
                    ),
                    last_good_expires_at=5_000,
                ),
            }
        )
        gateway = Gateway()
        gateway.names.add("existing_camera")
        use_case = SynchronizeVideoFeeds(
            Catalog([]), gateway, MemoryRepository(state), FakeClock(1_000), MediaPolicy()
        )
        self.assertEqual(use_case.restore_missing_runtime(), 1)
        self.assertEqual(
            {update[0] for update in gateway.updates},
            {
                "missing_camera",
            },
        )

    def test_failed_media_probe_rolls_back_full_last_good_profile(self) -> None:
        old_upstream = SecretUrl("https://live.camera.rt.ru/old?token=old")
        state = GatewayState(
            bindings={
                "uid": CameraBinding(
                    CameraId("uid"),
                    StreamName("camera"),
                    "Camera",
                    last_good_upstream=old_upstream,
                    last_good_profile=MediaProfile(AudioMode.COPY),
                    last_good_expires_at=5_000,
                )
            }
        )
        repository = MemoryRepository(state)
        gateway = Gateway()
        use_case = SynchronizeVideoFeeds(
            Catalog([make_feed("uid", "Camera", 6_000)]),
            gateway,
            repository,
            FakeClock(1_000),
            MediaPolicy(AudioMode.AAC),
            media_probe=Probe(set()),
        )
        result = use_case.refresh_once()
        self.assertEqual((result.updated, result.failed), (0, 1))
        saved = repository.state.bindings["uid"]
        self.assertEqual(saved.last_good_upstream, old_upstream)
        self.assertEqual(saved.last_good_profile.audio_mode, AudioMode.COPY)
        self.assertEqual(gateway.updates[-1][1], old_upstream.value)
        self.assertEqual(gateway.updates[-1][2].audio_mode, AudioMode.COPY)

    def test_expired_token_is_not_applied(self) -> None:
        gateway = Gateway()
        result = SynchronizeVideoFeeds(
            Catalog([make_feed("uid", "Camera", 1_050)]),
            gateway,
            MemoryRepository(),
            FakeClock(1_000),
            MediaPolicy(),
        ).refresh_once()
        self.assertEqual((result.updated, result.failed), (0, 1))
        self.assertEqual(gateway.updates, [])

    def test_same_token_and_profile_do_not_replace_lazy_runtime(self) -> None:
        feed = make_feed("uid", "Camera", 5_000)
        repository = MemoryRepository()
        gateway = Gateway()
        use_case = SynchronizeVideoFeeds(
            Catalog([feed]),
            gateway,
            repository,
            FakeClock(1_000),
            MediaPolicy(),
            media_probe=Probe({"camera"}),
        )

        first = use_case.refresh_once()
        second = use_case.refresh_once()

        self.assertEqual((first.updated, second.updated), (1, 0))
        self.assertEqual(len(gateway.updates), 1)
        self.assertIsNone(repository.state.bindings["uid"].last_error)

if __name__ == "__main__":
    unittest.main()
