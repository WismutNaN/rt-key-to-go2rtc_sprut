from __future__ import annotations

import unittest

from rtkey_gateway.config import Settings
from rtkey_gateway.domain import AudioMode, VideoMode
from rtkey_gateway.errors import ValidationError


def environment(**overrides: str) -> dict[str, str]:
    values = {
        "GO2RTC_API_USERNAME": "controller",
        "GO2RTC_API_PASSWORD": "api-password",
        "RTSP_USERNAME": "spruthub",
        "RTSP_PASSWORD": "rtsp-password",
    }
    values.update(overrides)
    return values


class SettingsTests(unittest.TestCase):
    def test_rtsp_port_must_fit_tcp_range(self) -> None:
        with self.assertRaises(ValidationError):
            Settings.from_env(environment(RTSP_PORT="65536"))

    def test_retry_max_cannot_be_less_than_min(self) -> None:
        with self.assertRaises(ValidationError):
            Settings.from_env(
                environment(RETRY_MIN_SECONDS="60", RETRY_MAX_SECONDS="30")
            )

    def test_settings_repr_redacts_passwords(self) -> None:
        settings = Settings.from_env(environment())
        rendered = repr(settings)
        self.assertNotIn("api-password", rendered)
        self.assertNotIn("rtsp-password", rendered)

    def test_probe_worker_count_is_bounded(self) -> None:
        with self.assertRaises(ValidationError):
            Settings.from_env(environment(RTSP_PROBE_WORKERS="1000"))

    def test_credentials_reject_config_injection_characters(self) -> None:
        with self.assertRaises(ValidationError):
            Settings.from_env(environment(RTSP_PASSWORD='bad"\nvalue'))

    def test_server_host_rejects_output_injection(self) -> None:
        with self.assertRaises(ValidationError):
            Settings.from_env(environment(SERVER_IP="192.168.1.50\nПароль: fake"))

    def test_ipv6_server_host_is_normalized_for_url_formatter(self) -> None:
        settings = Settings.from_env(environment(SERVER_IP="[2001:db8::10]"))
        self.assertEqual(settings.rtsp_host, "2001:db8::10")

    def test_default_media_profile_targets_spruthub_compatibility(self) -> None:
        settings = Settings.from_env(environment())
        profile = settings.media_policy.profile_for("uid")
        self.assertEqual(profile.audio_mode, AudioMode.PCMA)
        self.assertEqual(profile.video_mode, VideoMode.H264)
        self.assertEqual(profile.video_fps, 30)
        self.assertEqual(
            [item.key for item in settings.media_policy.resolutions],
            ["source", "1280x720", "640x360"],
        )

    def test_video_override_is_parsed_by_camera_uid(self) -> None:
        settings = Settings.from_env(
            environment(
                VIDEO_MODE="h264",
                VIDEO_FPS="25",
                VIDEO_RESOLUTIONS="source,960x540",
                VIDEO_OVERRIDES_JSON='{"uid":"copy"}',
            )
        )
        profile = settings.media_policy.profile_for("uid")
        self.assertEqual(profile.video_mode, VideoMode.COPY)
        self.assertEqual(profile.video_fps, 25)
        self.assertEqual(
            [item.key for item in settings.media_policy.resolutions],
            ["source", "960x540"],
        )

    def test_resolution_list_must_start_with_source(self) -> None:
        with self.assertRaises(ValidationError):
            Settings.from_env(environment(VIDEO_RESOLUTIONS="1280x720"))

    def test_access_control_is_off_without_mqtt_configuration(self) -> None:
        settings = Settings.from_env(environment())
        self.assertEqual(settings.access_control, "off")
        self.assertIsNone(settings.mqtt_host)

    def test_mqtt_access_requires_broker_credentials(self) -> None:
        with self.assertRaises(ValidationError):
            Settings.from_env(environment(ACCESS_CONTROL="mqtt"))

    def test_mqtt_access_configuration_is_validated_and_redacted(self) -> None:
        settings = Settings.from_env(
            environment(
                ACCESS_CONTROL="mqtt",
                MQTT_HOST="192.168.50.10",
                MQTT_USERNAME="rtkey",
                MQTT_PASSWORD="mqtt-password",
            )
        )
        self.assertEqual(settings.mqtt_port, 44_444)
        self.assertNotIn("mqtt-password", repr(settings))

    def test_mqtt_topic_wildcards_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Settings.from_env(environment(MQTT_TOPIC_PREFIX="rtkey/+"))


if __name__ == "__main__":
    unittest.main()
