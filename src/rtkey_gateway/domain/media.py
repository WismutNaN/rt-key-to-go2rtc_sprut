"""Media policy that can evolve independently from providers and gateways."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from rtkey_gateway.errors import ValidationError


class AudioMode(str, Enum):
    COPY = "copy"
    AAC = "aac"
    PCMA = "pcma"
    PCMU = "pcmu"
    NONE = "none"

    @classmethod
    def parse(cls, value: str) -> "AudioMode":
        try:
            return cls(value.strip().lower())
        except (AttributeError, ValueError) as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValidationError(
                f"Unsupported audio mode {value!r}; expected one of: {allowed}"
            ) from exc


class VideoMode(str, Enum):
    COPY = "copy"
    H264 = "h264"

    @classmethod
    def parse(cls, value: str) -> "VideoMode":
        try:
            return cls(value.strip().lower())
        except (AttributeError, ValueError) as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValidationError(
                f"Unsupported video mode {value!r}; expected one of: {allowed}"
            ) from exc


@dataclass(frozen=True, slots=True)
class MediaResolution:
    """One stable public resolution variant of a camera stream."""

    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if self.width is None and self.height is None:
            return
        if self.width is None or self.height is None:
            raise ValidationError("Media resolution requires width and height")
        if (
            isinstance(self.width, bool)
            or isinstance(self.height, bool)
            or not isinstance(self.width, int)
            or not isinstance(self.height, int)
        ):
            raise ValidationError("Media resolution dimensions must be integers")
        if not 160 <= self.width <= 3_840 or not 90 <= self.height <= 2_160:
            raise ValidationError("Media resolution is outside 160x90..3840x2160")
        if self.width % 2 or self.height % 2:
            raise ValidationError("H.264 resolution dimensions must be even")

    @property
    def key(self) -> str:
        return "source" if self.width is None else f"{self.width}x{self.height}"

    @classmethod
    def parse(cls, value: str) -> "MediaResolution":
        normalized = str(value).strip().lower()
        if normalized == "source":
            return cls()
        parts = normalized.split("x", 1)
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValidationError(
                "Video resolution must be 'source' or WIDTHxHEIGHT"
            )
        return cls(int(parts[0]), int(parts[1]))

    def stream_name_value(self, base: str) -> str:
        if self.width is None:
            return base
        suffix = f"_{self.key}"
        if len(base) + len(suffix) <= 64:
            return f"{base}{suffix}"
        digest = hashlib.sha256(base.encode("ascii")).hexdigest()[:6]
        suffix = f"_{digest}_{self.key}"
        return f"{base[:64 - len(suffix)].rstrip('_')}{suffix}"


@dataclass(frozen=True, slots=True)
class MediaProfile:
    """Codec choices exposed to a media gateway adapter."""

    audio_mode: AudioMode = AudioMode.COPY
    video_mode: VideoMode = VideoMode.COPY
    video_fps: int = 30
    video_width: int | None = None
    video_height: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.audio_mode, AudioMode):
            object.__setattr__(self, "audio_mode", AudioMode.parse(self.audio_mode))
        if not isinstance(self.video_mode, VideoMode):
            object.__setattr__(self, "video_mode", VideoMode.parse(self.video_mode))
        if isinstance(self.video_fps, bool) or not 1 <= self.video_fps <= 60:
            raise ValidationError("Stable video FPS must be between 1 and 60")
        MediaResolution(self.video_width, self.video_height)


@dataclass(frozen=True, slots=True)
class MediaVariant:
    resolution: MediaResolution
    profile: MediaProfile

    def stream_name_value(self, base: str) -> str:
        return self.resolution.stream_name_value(base)


@dataclass(frozen=True, slots=True)
class MediaPolicy:
    """Resolve independent audio/video modes with per-camera overrides."""

    default_audio: AudioMode = AudioMode.COPY
    audio_overrides: Mapping[str, AudioMode] = field(default_factory=dict)
    default_video: VideoMode = VideoMode.H264
    video_overrides: Mapping[str, VideoMode] = field(default_factory=dict)
    video_fps: int = 30
    resolutions: tuple[MediaResolution, ...] = (
        MediaResolution(),
        MediaResolution(1_280, 720),
        MediaResolution(640, 360),
    )

    def __post_init__(self) -> None:
        resolutions = tuple(self.resolutions)
        if not 1 <= len(resolutions) <= 4:
            raise ValidationError("Configure between one and four video resolutions")
        if resolutions[0] != MediaResolution():
            raise ValidationError("The first video resolution must be 'source'")
        if len(set(resolutions)) != len(resolutions):
            raise ValidationError("Video resolutions must be unique")
        object.__setattr__(self, "resolutions", resolutions)

    def profile_for(self, camera_id: str) -> MediaProfile:
        return MediaProfile(
            audio_mode=self.audio_overrides.get(camera_id, self.default_audio),
            video_mode=self.video_overrides.get(camera_id, self.default_video),
            video_fps=self.video_fps,
        )

    def variants_for(
        self,
        camera_id: str,
        *,
        base_profile: MediaProfile | None = None,
    ) -> tuple[MediaVariant, ...]:
        base = base_profile or self.profile_for(camera_id)
        variants: list[MediaVariant] = []
        for resolution in self.resolutions:
            scaled = resolution.width is not None
            variants.append(
                MediaVariant(
                    resolution,
                    MediaProfile(
                        audio_mode=base.audio_mode,
                        video_mode=VideoMode.H264 if scaled else base.video_mode,
                        video_fps=base.video_fps,
                        video_width=resolution.width,
                        video_height=resolution.height,
                    ),
                )
            )
        return tuple(variants)


# Backward-compatible import for extensions built against v1.0.
AudioPolicy = MediaPolicy
