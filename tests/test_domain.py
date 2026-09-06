from __future__ import annotations

import unittest

from rtkey_gateway.domain import (
    AudioMode,
    CameraFeed,
    CameraId,
    GatewayState,
    MediaPolicy,
    MediaResolution,
    SecretUrl,
    StreamName,
    StreamNamingPolicy,
    VideoMode,
)
from rtkey_gateway.errors import ValidationError


def feed(uid: str, title: str) -> CameraFeed:
    return CameraFeed(
        CameraId(uid), title, SecretUrl(f"https://media.camera.rt.ru/{uid}?token=x"), 99
    )


class StreamNamingTests(unittest.TestCase):
    def test_russian_title_becomes_readable_slug(self) -> None:
        self.assertEqual(
            StreamNamingPolicy.slug_from_title("Подъезд № 1"), "podezd_1"
        )

    def test_names_are_stable_when_api_order_and_title_change(self) -> None:
        policy = StreamNamingPolicy()
        first = policy.reconcile(
            GatewayState(), [feed("uid-b", "Двор"), feed("uid-a", "Подъезд")]
        )
        second = policy.reconcile(
            first, [feed("uid-a", "Новый подъезд"), feed("uid-b", "Двор")]
        )
        self.assertEqual(first.bindings["uid-a"].stream_name.value, "podezd")
        self.assertEqual(second.bindings["uid-a"].stream_name.value, "podezd")
        self.assertEqual(second.bindings["uid-a"].title, "Новый подъезд")

    def test_duplicate_title_gets_uid_suffix(self) -> None:
        state = StreamNamingPolicy().reconcile(
            GatewayState(), [feed("abcdef12-one", "Двор"), feed("abcdef34-two", "Двор")]
        )
        names = {item.stream_name.value for item in state.bindings.values()}
        self.assertEqual(names, {"dvor", "dvor_abcdef34"})

    def test_secret_repr_is_redacted(self) -> None:
        secret = SecretUrl("https://x.invalid/?token=secret")
        self.assertNotIn("secret", repr(secret))
        self.assertEqual(str(secret), "***")

    def test_stream_name_rejects_path_characters(self) -> None:
        with self.assertRaises(ValidationError):
            StreamName("../camera")

    def test_external_text_cannot_inject_terminal_lines(self) -> None:
        with self.assertRaises(ValidationError):
            CameraId("uid\nspoofed")
        camera = CameraFeed(
            CameraId("uid"),
            "Подъезд\n\x1b[31mwarning",
            SecretUrl("https://media.camera.rt.ru/live?token=x"),
            99,
        )
        self.assertNotIn("\n", camera.title)
        self.assertNotIn("\x1b", camera.title)


class MediaPolicyTests(unittest.TestCase):
    def test_audio_override_does_not_change_copy_video(self) -> None:
        policy = MediaPolicy(
            default_audio=AudioMode.COPY,
            audio_overrides={"uid": AudioMode.PCMA},
        )
        profile = policy.profile_for("uid")
        self.assertEqual(profile.video_mode, VideoMode.COPY)
        self.assertEqual(profile.audio_mode, AudioMode.PCMA)

    def test_low_load_defaults_copy_source_video(self) -> None:
        policy = MediaPolicy()
        profile = policy.profile_for("uid")
        self.assertEqual(profile.audio_mode, AudioMode.NONE)
        self.assertEqual(profile.video_mode, VideoMode.COPY)
        self.assertEqual(profile.video_fps, 15)
        self.assertEqual(
            [variant.resolution.key for variant in policy.variants_for("uid")],
            ["source"],
        )

    def test_scaled_variants_are_not_supported(self) -> None:
        with self.assertRaises(ValidationError):
            MediaPolicy(
                resolutions=(MediaResolution(), MediaResolution(1_280, 720))
            )

    def test_resolution_rejects_odd_h264_dimensions(self) -> None:
        with self.assertRaises(ValidationError):
            MediaResolution.parse("1279x720")

    def test_invalid_mode_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AudioMode.parse("mp3")
        with self.assertRaises(ValidationError):
            VideoMode.parse("h264")


if __name__ == "__main__":
    unittest.main()
