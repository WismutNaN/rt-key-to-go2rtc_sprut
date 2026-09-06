from __future__ import annotations

import unittest

from rtkey_gateway.config import Settings
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


if __name__ == "__main__":
    unittest.main()
