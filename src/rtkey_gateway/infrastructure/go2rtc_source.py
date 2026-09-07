"""Map domain media values to the source syntax understood by go2rtc."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rtkey_gateway.domain import AudioMode, MediaProfile, SecretUrl


def build_go2rtc_source(upstream_url: SecretUrl, profile: MediaProfile) -> str:
    source = (
        f"ffmpeg:{upstream_url.value}"
        "#input=rtkey_http#video=rtkey_h264_copy#raw=rtkey_low_latency"
    )
    if profile.audio_mode is not AudioMode.NONE:
        source += f"#audio={profile.audio_mode.value}"
    return source


def redact_source(source: str) -> str:
    prefix = "ffmpeg:" if source.startswith("ffmpeg:") else ""
    raw = source[len(prefix):]
    url_part, separator, fragment = raw.partition("#")
    parsed = urlsplit(url_part)
    query = [
        (key, "***" if key.lower() == "token" else value)
        for key, value in parse_qsl(parsed.query)
    ]
    redacted = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
    return f"{prefix}{redacted}{separator}{fragment}" if separator else f"{prefix}{redacted}"
