from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

from rtkey_gateway.errors import (
    AuthenticationError,
    SchemaError,
    TransportError,
    ValidationError,
)
from rtkey_gateway.infrastructure.rtkey.video_catalog import (
    FallbackVideoCatalog,
    LegacyCameraApiStrategy,
    NewCameraApiStrategy,
    build_live_url,
    decode_jwt_exp,
)
from tests.helpers import QueueTransport, json_response, jwt_with_exp


class TokenSource:
    def read(self) -> str:
        return "bearer-secret"


class RtKeyAdapterTests(unittest.TestCase):
    def test_new_api_maps_fields_and_dynamic_host(self) -> None:
        token = jwt_with_exp(2_000_000_000)
        transport = QueueTransport(
            [
                json_response(
                    {
                        "data": [
                            {
                                "uid": "cam-1",
                                "title": "Подъезд",
                                "streamerToken": token,
                                "streamerUrl": "wss://live-vdk7.camera.rt.ru/source",
                                "screenshotToken": "unused",
                            }
                        ]
                    }
                )
            ]
        )
        feeds = NewCameraApiStrategy(transport, TokenSource()).fetch_feeds()
        self.assertEqual(len(feeds), 1)
        self.assertEqual(feeds[0].camera_id.value, "cam-1")
        self.assertEqual(feeds[0].expires_at, 2_000_000_000)
        self.assertIn("live-vdk7.camera.rt.ru", feeds[0].upstream_url.value)
        self.assertNotIn("live-vdk4.camera.rt.ru", feeds[0].upstream_url.value)
        self.assertEqual(transport.requests[0][2]["Authorization"], "Bearer bearer-secret")

    def test_legacy_api_is_used_after_new_schema_error(self) -> None:
        transport = QueueTransport(
            [
                json_response({"unexpected": []}),
                json_response(
                    {
                        "data": {
                            "items": [
                                {
                                    "id": "legacy-1",
                                    "title": "Двор",
                                    "streamer_token": "a.b.c",
                                    "streamer_url": "https://live-vdk2.camera.rt.ru",
                                }
                            ]
                        }
                    }
                ),
            ]
        )
        options = {"transport": transport, "token_source": TokenSource()}
        catalog = FallbackVideoCatalog(
            [NewCameraApiStrategy(**options), LegacyCameraApiStrategy(**options)]
        )
        feeds = catalog.fetch_feeds()
        self.assertEqual(feeds[0].camera_id.value, "legacy-1")
        self.assertIn("live-vdk2.camera.rt.ru", feeds[0].upstream_url.value)
        self.assertEqual(len(transport.requests), 2)

    def test_all_auth_failures_are_classified(self) -> None:
        transport = QueueTransport(
            [json_response({}, 401), json_response({}, 403)]
        )
        options = {"transport": transport, "token_source": TokenSource()}
        catalog = FallbackVideoCatalog(
            [NewCameraApiStrategy(**options), LegacyCameraApiStrategy(**options)]
        )
        with self.assertRaises(AuthenticationError):
            catalog.fetch_feeds()

    def test_token_is_one_encoded_query_value(self) -> None:
        secret = build_live_url(
            "camera/id", "https://live.camera.rt.ru/x", "a+b/c=", ("camera.rt.ru",)
        )
        parsed = urlsplit(secret.value)
        self.assertEqual(parsed.path, "/stream/camera%2Fid/live.mp4")
        self.assertEqual(parse_qs(parsed.query)["token"], ["a+b/c="])

    def test_untrusted_stream_host_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            build_live_url("id", "https://evil.example", "token", ("camera.rt.ru",))

    def test_malformed_stream_authority_is_rejected_as_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            build_live_url(
                "id", "https://[broken.camera.rt.ru", "token", ("camera.rt.ru",)
            )

    def test_jwt_without_valid_exp_is_safe(self) -> None:
        self.assertIsNone(decode_jwt_exp("not-a-jwt"))

    def test_new_api_paginates_with_dotted_parameters(self) -> None:
        def item(uid: str) -> dict[str, str]:
            return {
                "uid": uid,
                "title": uid,
                "streamerToken": "a.b.c",
                "streamerUrl": "https://live.camera.rt.ru",
            }

        transport = QueueTransport(
            [
                json_response({"data": [item("a"), item("b")]}),
                json_response({"data": [item("c")]}),
            ]
        )
        feeds = NewCameraApiStrategy(
            transport, TokenSource(), page_size=2
        ).fetch_feeds()
        self.assertEqual([feed.camera_id.value for feed in feeds], ["a", "b", "c"])
        queries = [parse_qs(urlsplit(request[1]).query) for request in transport.requests]
        self.assertEqual(queries[0]["paging.offset"], ["0"])
        self.assertEqual(queries[1]["paging.offset"], ["2"])

    def test_one_invalid_record_does_not_hide_valid_cameras(self) -> None:
        transport = QueueTransport(
            [
                json_response(
                    {
                        "data": [
                            {
                                "uid": "valid",
                                "title": "Двор",
                                "streamerToken": "a.b.c",
                                "streamerUrl": "https://live.camera.rt.ru",
                            },
                            {"uid": "broken"},
                        ]
                    }
                )
            ]
        )
        feeds = NewCameraApiStrategy(transport, TokenSource()).fetch_feeds()
        self.assertEqual([feed.camera_id.value for feed in feeds], ["valid"])

    def test_successful_apis_are_merged_with_new_api_precedence(self) -> None:
        new_token = jwt_with_exp(2_000_000_000)
        legacy_token = jwt_with_exp(2_000_000_100)
        transport = QueueTransport(
            [
                json_response(
                    {
                        "data": [
                            {
                                "uid": "shared",
                                "title": "New title",
                                "streamerToken": new_token,
                                "streamerUrl": "https://new.camera.rt.ru",
                            }
                        ]
                    }
                ),
                json_response(
                    {
                        "data": {
                            "items": [
                                {
                                    "id": "shared",
                                    "title": "Old title",
                                    "streamer_token": legacy_token,
                                    "streamer_url": "https://old.camera.rt.ru",
                                },
                                {
                                    "id": "legacy-only",
                                    "title": "Legacy only",
                                    "streamer_token": legacy_token,
                                    "streamer_url": "https://old.camera.rt.ru",
                                },
                            ]
                        }
                    }
                ),
            ]
        )
        options = {"transport": transport, "token_source": TokenSource()}
        feeds = FallbackVideoCatalog(
            [NewCameraApiStrategy(**options), LegacyCameraApiStrategy(**options)]
        ).fetch_feeds()
        by_uid = {feed.camera_id.value: feed for feed in feeds}
        self.assertEqual(set(by_uid), {"shared", "legacy-only"})
        self.assertEqual(by_uid["shared"].title, "New title")
        self.assertIn("new.camera.rt.ru", by_uid["shared"].upstream_url.value)

    def test_empty_catalog_is_not_confirmed_when_other_api_failed(self) -> None:
        transport = QueueTransport(
            [json_response({"data": []}), json_response({}, 500)]
        )
        options = {"transport": transport, "token_source": TokenSource()}
        catalog = FallbackVideoCatalog(
            [NewCameraApiStrategy(**options), LegacyCameraApiStrategy(**options)]
        )
        with self.assertRaises(TransportError):
            catalog.fetch_feeds()


if __name__ == "__main__":
    unittest.main()
